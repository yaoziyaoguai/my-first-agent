"""019 第一片：固定 import guard + 固定用途 installed-site pytest evidence runner。

guard 只做安装态导入拦截；CLI 先装 guard，再导入 pytest 与全部 required
module，最后以单个内联证据插件运行 materialized 树的 pytest。刻意不做通用
插件基础设施。
"""

import argparse
import importlib
import importlib.abc
import importlib.machinery
import json
import os
import sys
import tempfile
from pathlib import Path

# 固定产品根，刻意不做通用化配置。
FIXED_PRODUCT_ROOTS = ("main", "agent", "first_agent_skill_runner")

# 固定 evidence schema 标识，报告消费方按它校验结构。
EVIDENCE_SCHEMA = "my-first-agent/materialized-pytest-evidence/v1"

_GUARD_ENVIRONMENT_KEYS = (
    "FIRST_AGENT_019_INSTALLED_SITE",
    "FIRST_AGENT_019_SOURCE_ROOT",
    "FIRST_AGENT_019_ORIGIN_LOG",
)


def _append_origin_event(path, payload):
    """以单次 O_APPEND 写入追加一行紧凑 UTF-8 JSON 事件。"""
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    data = (text + "\n").encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


class _InstalledProductFinder(importlib.abc.MetaPathFinder):
    """只允许产品根模块从 installed_site 解析的 meta path finder。"""

    # 标记属性：install_guard 据此做幂等安装判断。
    _installed_product_guard_marker = True

    def __init__(self, installed_site, source_root, origin_log):
        self._installed_site = os.path.realpath(installed_site)
        self._source_root = source_root
        self._origin_log = origin_log

    def find_spec(self, fullname, path=None, target=None):
        if fullname.partition(".")[0] not in FIXED_PRODUCT_ROOTS:
            # 非产品导入不接管，交给后续 finder。
            return None
        # 无视传入 path，始终只在 installed_site 对应目录内解析，
        # 避免父包 __path__ 指向源码树时被带偏。
        spec = importlib.machinery.PathFinder.find_spec(
            fullname, self._search_path(fullname)
        )
        origin = spec.origin if spec is not None else None
        if spec is None or not self._origin_under_installed_site(origin):
            error = (
                "spec_missing_under_installed_site"
                if spec is None
                else "origin_outside_installed_site"
            )
            self._log(fullname, origin, error)
            # 抛错而非返回 None：返回 None 会让后续 sys.path finder
            # （例如源码树里的同名模块）把这次导入“救回”，guard 即失效。
            raise ModuleNotFoundError(
                f"{fullname}: installed import guard rejected "
                f"(error={error}, origin={origin!r}, "
                f"installed_site={self._installed_site!r})"
            )
        self._log(fullname, origin, None)
        return spec

    def _search_path(self, fullname):
        parts = fullname.split(".")
        if len(parts) == 1:
            return [self._installed_site]
        return [os.path.join(self._installed_site, *parts[:-1])]

    def _origin_under_installed_site(self, origin):
        if not origin:
            return False
        real_origin = os.path.realpath(origin)
        site = self._installed_site
        return real_origin == site or real_origin.startswith(site + os.sep)

    def _log(self, fullname, origin, error):
        _append_origin_event(
            self._origin_log,
            {
                "pid": os.getpid(),
                "module": fullname,
                "origin": origin,
                "error": error,
            },
        )


def install_guard(installed_site, source_root, origin_log):
    """幂等地把 guard 插到 sys.meta_path[0]。"""
    for existing in sys.meta_path:
        if getattr(existing, "_installed_product_guard_marker", False):
            return existing
    finder = _InstalledProductFinder(installed_site, source_root, origin_log)
    sys.meta_path.insert(0, finder)
    return finder


def install_guard_from_environment():
    """读取 FIRST_AGENT_019_* 环境变量：全缺省不动作，部分设置报错。"""
    values = {key: os.environ.get(key) for key in _GUARD_ENVIRONMENT_KEYS}
    missing = [key for key, value in values.items() if value is None]
    if len(missing) == len(_GUARD_ENVIRONMENT_KEYS):
        return None
    if missing:
        raise RuntimeError(
            "FIRST_AGENT_019_* environment partially set; missing: "
            + ", ".join(missing)
        )
    return install_guard(
        values["FIRST_AGENT_019_INSTALLED_SITE"],
        values["FIRST_AGENT_019_SOURCE_ROOT"],
        values["FIRST_AGENT_019_ORIGIN_LOG"],
    )


# ---------------------------------------------------------------------------
# 固定用途 pytest evidence runner（CLI + 内联插件）
# ---------------------------------------------------------------------------

# runtest protocol 固定三阶段，final 判定按此顺序覆盖。
_RUNTEST_PHASES = ("setup", "call", "teardown")


def _write_json_atomically(path: Path, payload: dict) -> None:
    """同目录临时文件 + os.replace 原子重写报告，失败时清理临时文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _read_origin_log(origin_log: Path) -> tuple[list[dict], list[str]]:
    """读取 JSONL origin log；返回 (事件列表, 无法解析的行列表)。"""
    events: list[dict] = []
    broken_lines: list[str] = []
    if not origin_log.exists():
        return events, broken_lines
    for line in origin_log.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            broken_lines.append(line)
    return events, broken_lines


def _origin_error_entries(events: list[dict], broken_lines: list[str]) -> list[dict]:
    """把 origin log 中的错误事件转成 origin_errors 记录。"""
    entries = []
    for event in events:
        if event.get("error") is None:
            continue
        entries.append(
            {
                "module": event.get("module"),
                "origin": event.get("origin"),
                "error": event.get("error"),
            }
        )
    for line in broken_lines:
        entries.append(
            {
                "module": None,
                "origin": None,
                "error": "origin_log_unparseable",
                "detail": line[:200],
            }
        )
    return entries


def _collect_loaded_product_origins(events: list[dict]) -> dict[str, str]:
    """合并 origin log 与当前 sys.modules 的固定产品根模块 origin。

    报告写入时重新扫描：收集/执行阶段才导入的 late import 会同时出现在
    log 与 sys.modules 中，两边合并即完整覆盖。
    """
    origins: dict[str, str] = {}
    for event in events:
        if event.get("error") is None and event.get("module") and event.get("origin"):
            origins[event["module"]] = event["origin"]
    for name, module in sorted(sys.modules.items()):
        if name.partition(".")[0] not in FIXED_PRODUCT_ROOTS:
            continue
        origin = getattr(module, "__file__", None)
        if origin:
            origins[name] = origin
    return origins


def _normalized_reason(longrepr) -> str | None:
    """归一化 logreport 的 longrepr：skip 的 (path, lineno, reason) 取第三段原文。"""
    if longrepr is None:
        return None
    if isinstance(longrepr, tuple) and len(longrepr) == 3:
        reason = str(longrepr[2])
        return reason.removeprefix("Skipped: ")
    return str(longrepr)


def _outcome_record(node_id: str, outcome: str, reason: str | None) -> dict:
    return {"node_id": node_id, "outcome": outcome, "reason": reason}


class _InstalledPytestEvidencePlugin:
    """019 专用 pytest 证据插件：只服务本 runner 的报告，不做通用基础设施。"""

    def __init__(self, report_path, origin_log, origin_errors):
        self._report_path = Path(report_path)
        self._origin_log = Path(origin_log)
        # 与 main 共享同一个错误列表：required import 失败先进入，log 错误
        # 在每次写报告时并入；跨写去重避免 collection/session 两次重复记录。
        self._origin_errors = origin_errors
        self._seen_origin_error_keys: set[tuple] = set()
        self._collected_node_ids: list[str] = []
        self._deselected_node_ids: list[str] = []
        # node_id -> {when: {outcome, wasxfail, reason}}，只存归一化结果。
        self._phase_reports: dict[str, dict[str, dict]] = {}
        self._session_completed = False

    def pytest_collection_finish(self, session) -> None:
        self._collected_node_ids = sorted(item.nodeid for item in session.items)
        self._write_report()

    def pytest_deselected(self, items) -> None:
        self._deselected_node_ids = sorted(
            set(self._deselected_node_ids) | {item.nodeid for item in items}
        )

    def pytest_runtest_logreport(self, report) -> None:
        self._phase_reports.setdefault(report.nodeid, {})[report.when] = {
            "outcome": report.outcome,
            "wasxfail": getattr(report, "wasxfail", None),
            "reason": _normalized_reason(getattr(report, "longrepr", None)),
        }

    def pytest_sessionfinish(self, session, exitstatus) -> None:
        self._session_completed = True
        self._write_report()

    def _final_outcome_records(self) -> list[dict]:
        records = []
        for node_id in sorted(self._phase_reports):
            phases = self._phase_reports[node_id]
            if self._node_executed(phases):
                records.append(self._final_outcome_record(node_id, phases))
        return records

    @staticmethod
    def _node_executed(phases: dict[str, dict]) -> bool:
        # 有 call、或出现 failed/skipped 阶段报告即视为已执行；
        # 只剩 setup passed（中断残留）的节点不发明 passed 记录。
        return any(
            when == "call" or info["outcome"] in ("failed", "skipped")
            for when, info in phases.items()
        )

    @staticmethod
    def _final_outcome_record(node_id: str, phases: dict[str, dict]) -> dict:
        # 覆盖顺序：任何阶段 failed（含 teardown 失败）> xfailed > xpassed
        # > skipped > passed。
        for when in _RUNTEST_PHASES:
            info = phases.get(when)
            if info and info["outcome"] == "failed":
                return _outcome_record(node_id, "failed", info["reason"])
        for when in _RUNTEST_PHASES:
            info = phases.get(when)
            if info and info["outcome"] == "skipped" and info["wasxfail"]:
                return _outcome_record(node_id, "xfailed", info["wasxfail"] or info["reason"])
        for when in _RUNTEST_PHASES:
            info = phases.get(when)
            if info and info["outcome"] == "passed" and info["wasxfail"]:
                return _outcome_record(node_id, "xpassed", info["wasxfail"] or info["reason"])
        for when in _RUNTEST_PHASES:
            info = phases.get(when)
            if info and info["outcome"] == "skipped":
                return _outcome_record(node_id, "skipped", info["reason"])
        return _outcome_record(node_id, "passed", None)

    def _write_report(self) -> None:
        events, broken_lines = _read_origin_log(self._origin_log)
        for entry in _origin_error_entries(events, broken_lines):
            key = (
                entry["module"],
                entry["origin"],
                entry["error"],
                entry.get("detail"),
            )
            if key not in self._seen_origin_error_keys:
                self._seen_origin_error_keys.add(key)
                self._origin_errors.append(entry)
        report = {
            "runner_pid": os.getpid(),
            "loaded_product_origins": _collect_loaded_product_origins(events),
            "origin_errors": list(self._origin_errors),
            "evidence": {
                "schema": EVIDENCE_SCHEMA,
                "collected_node_ids": list(self._collected_node_ids),
                "outcomes": self._final_outcome_records(),
                "deselected_node_ids": list(self._deselected_node_ids),
                # sessionfinish 之前一律 false，之后才置 true。
                "session_completed": self._session_completed,
            },
        }
        _write_json_atomically(self._report_path, report)


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="019 installed-site pytest evidence runner",
    )
    parser.add_argument("--installed-site", type=Path, required=True)
    parser.add_argument("--test-tree", type=Path, required=True)
    parser.add_argument("--report-path", type=Path, required=True)
    parser.add_argument("--origin-log", type=Path, required=True)
    parser.add_argument("--basetemp", type=Path, required=True)
    parser.add_argument(
        "--required-module",
        action="append",
        required=True,
        help="需要经 guard 导入的产品模块名，可重复",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_argument_parser().parse_args(argv)
    # guard 必须先于 pytest 与 required module 的导入安装，保证产品根导入
    # 只能从 installed_site 解析；source_root 仅作记录，取当前源码检出目录。
    install_guard(args.installed_site, args.test_tree, args.origin_log)

    origin_errors: list[dict] = []
    for module_name in args.required_module:
        try:
            importlib.import_module(module_name)
        except Exception as error:
            origin_errors.append(
                {
                    "module": module_name,
                    "origin": None,
                    "error": "required_module_import_failed",
                    "detail": f"{type(error).__name__}: {error}",
                }
            )

    # guard 装好、required module 导入完成后才导入 pytest。
    import pytest

    plugin = _InstalledPytestEvidencePlugin(
        args.report_path, args.origin_log, origin_errors
    )
    exit_code = int(
        pytest.main(
            [
                str(args.test_tree / "tests"),
                "-q",
                "-rx",
                "--color=no",
                "-p",
                "no:cacheprovider",
                "--rootdir",
                str(args.test_tree),
                "--basetemp",
                str(args.basetemp),
            ],
            plugins=[plugin],
        )
    )
    # origin 错误（guard 拒绝或 required import 失败）强制非零退出；
    # 报告无论成败都由插件保留。
    if origin_errors:
        return exit_code or 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
