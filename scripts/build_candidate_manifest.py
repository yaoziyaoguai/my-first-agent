#!/usr/bin/env python3
"""按审核清单把工作树物化成干净候选目录，并产出逐文件哈希 manifest。

用法：
    python scripts/build_candidate_manifest.py --out <候选目录> --manifest <json 路径>

安全合同（2026-10-12 补漏 W2）：

- 默认**只创建全新 output**。已有目录、普通文件、软链接（含悬空）一律在
  任何写入前失败；不提供默认开启的覆盖/删除行为，也不做递归删除回滚。
- output 与 manifest 必须是「仓库之外、已存在的同一物理父目录」下两个不同、
  尚不存在的叶子。父目录先解析（允许系统级路径别名规范化），再做边界检查；
  叶子用不跟随链接的检查，不先 resolve 叶子。
- 整份输入清单在**任何目标写入之前**完成预检并冻结字节摘要；拒绝源路径链接、
  非普通文件、越界与私人路径。
- 复制使用 exclusive/no-overwrite；复制后校验与预检摘要一致。
- 全部复制成功后才发布 manifest：同父目录写本次独占临时文件，再用
  ``os.link``（目标已存在即失败）发布，不用会覆盖的 ``os.replace``。

规则（资料包 DL-01 §2/§3）：候选是**工作树产品状态的干净副本**（HEAD 产品代码
与工作树测试不自洽：例如 HEAD 的 ``ControlInbox`` 没有工作树 loop.py 调用的
``pending``），因此产品/测试文件一律取工作树内容；只复制审核清单内的路径，
不整树复制。
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parents[1]

ROUND = "2026-10-14 task-trust resume"

# 必须取工作树内容的产品文件：launch/运行时闭包（16 文件，含 file_ops 的
# project_paths 运行时缺口）+ 被产品代码引用的未跟踪模块。
WORKTREE_CLOSURE: dict[str, str] = {
    # --- 审计 S0 的 12 文件 import 闭包 ---
    "agent/browser/contracts.py": "launch closure: browser contracts symbols",
    "agent/cli/actions.py": "launch closure: typed action builders",
    "agent/composition.py": "launch closure: composition root symbols",
    "agent/continuity/sessions.py": "launch closure: session bootstrap",
    "agent/memory/contracts.py": "launch closure: memory contract symbols",
    "agent/provider/config.py": "launch closure: provider config",
    "agent/provider/protocol.py": "launch closure: provider protocol",
    "agent/runtime/ports.py": "launch closure: ModelAttemptBudgetExhaustedError",
    "agent/runtime/views.py": "launch closure: view projections",
    "agent/tools/path_safety.py": "launch closure: path safety helpers",
    # --- 未被 import 探测发现、但运行时调用缺口的第 16 个文件 ---
    "agent/tools/file_ops.py": (
        "runtime closure: composition.build_tool_registrations passes "
        "project_paths= to build_file_tool_registrations (TypeError on HEAD)"
    ),
    # --- 被产品代码引用的未跟踪模块 ---
    "agent/runtime/resource_lifecycle.py": "untracked module imported by state.py:97",
    "agent/process/managed_web.py": "untracked module; managed web process owner",
    "agent/process/managed_web_child.py": (
        "untracked child script referenced by managed_web.py via Path(__file__).with_name"
    ),
    "agent/subagent/evidence.py": (
        "untracked module imported by subagent runner.py:37 / child.py:128 / "
        "process_runner.py:456"
    ),
    "agent/tools/directory.py": "untracked module imported by file_ops.py:18",
}

# 本轮（2026-10-14 任务结果可信接续包）修改的产品/指南文件：必须出现在候选中，
# 且 manifest 标注。仅身份标签，不改安全算法。
THIS_ROUND = {
    "README.md",
    "agent/cli/app.py",
    "agent/cli/render.py",
    "agent/provider/normalize.py",
    "agent/runtime/checkpoint.py",
    "agent/runtime/context.py",
    "agent/runtime/contracts.py",
    "agent/runtime/evidence.py",
    "agent/runtime/loop.py",
    "agent/runtime/state.py",
    "agent/runtime/views.py",
    "docs/handoffs/2026-10-11-product-reliability-closure/RESULTS.md",
    "scripts/build_candidate_manifest.py",
}

# 本轮修复依赖、必须随候选一起取工作树内容的文件（非闭包但被本轮改动引用）。
THIS_ROUND_SUPPORT: set[str] = {
    "tests/kernel/fakes.py",
}

# 本轮新增/更新的回归测试与验收脚本：候选必须自带，否则安装物验证只跑旧测试。
# 未跟踪的公开新测试必须显式列入（脚本只自动收集 tracked）。
THIS_ROUND_TESTS = {
    "tests/acceptance/test_task_trust_completion.py",
    "tests/cli/test_commands.py",
    "tests/cli/test_contextual_decisions.py",
    "tests/cli/test_render.py",
    "tests/continuity/test_checkpoint_v4.py",
    "tests/continuity/test_contracts.py",
    "tests/continuity/test_verified_done.py",
    "tests/kernel/test_context_budgeting.py",
    "tests/kernel/test_runtime_compaction.py",
    "tests/kernel/test_validation_request_freshness.py",
    "tests/provider/test_continuity_control.py",
    "tests/reference/test_012_trusted_continuity.py",
    "tests/reference/test_013_everyday_workspace.py",
    "tests/reference/test_candidate_manifest_safety.py",
    "tests/subagent/test_integration.py",
}

# 构建残留绝不能进候选：``build/lib`` 会让 setuptools 复用旧源码，负例
# （删掉闭包模块）会从残留里被补回而假通过。
EXCLUDED_TOP_LEVEL = {
    "build",
    "dist",
    "first_agent.egg-info",
    ".git",
    ".venv",
    ".local",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "graphify-out",
    ".ua",
    ".claude",
    ".codex",
    ".opencode",
    "node_modules",
}

# 私人/凭据路径：不因 tracked 就可读取。
PRIVATE_NAMES = {".env", ".netrc", ".git-credentials", "config.yaml"}
PRIVATE_SUFFIXES = (".pem", ".key", ".pyc", ".pyo")


class CandidateBuildError(RuntimeError):
    """安全或输入预检失败；调用方必须以非零退出，且不留下有效 manifest。"""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _resolve_leaf(raw: str, label: str) -> tuple[Path, Path]:
    """解析一个目标叶子，返回 (已解析父目录, 叶子名)。

    父目录必须已存在；先解析父目录（允许 ``/var`` → ``/private/var`` 这类系统
    别名），叶子保持原样、不 resolve，以保留其链接身份供后续 lexists 检查。
    """

    candidate = Path(raw)
    name = candidate.name
    if name in {"", ".", ".."}:
        raise CandidateBuildError(f"{label} must name a new leaf, got {raw!r}")
    try:
        parent = candidate.parent.resolve(strict=True)
    except FileNotFoundError as error:
        raise CandidateBuildError(
            f"{label} parent directory does not exist: {candidate.parent}"
        ) from error
    if not parent.is_dir():
        raise CandidateBuildError(f"{label} parent is not a directory: {parent}")
    return parent, name


def _reject_existing_leaf(parent: Path, name: str, label: str) -> Path:
    """叶子存在性检查：用 lexists，不跟随链接，悬空链接也算存在。"""

    leaf = parent / name
    if os.path.lexists(leaf):
        raise CandidateBuildError(
            f"{label} already exists (including dangling links); "
            f"this tool only creates new targets: {leaf}"
        )
    return leaf


def _check_parent_boundary(parent: Path) -> None:
    """父目录必须在源仓库之外，且不能是仓库本身或仓库祖先。"""

    source = ROOT.resolve()
    if parent == source or source in parent.parents:
        raise CandidateBuildError(
            f"target parent is inside the source repository: {parent}"
        )
    if parent in source.parents:
        raise CandidateBuildError(
            f"target parent is an ancestor of the source repository: {parent}"
        )


def _plan_targets(out_raw: str, manifest_raw: str) -> tuple[Path, Path]:
    """在任何写入前确定 output 与 manifest 两个叶子。"""

    out_parent, out_name = _resolve_leaf(out_raw, "output")
    manifest_parent, manifest_name = _resolve_leaf(manifest_raw, "manifest")
    if out_parent != manifest_parent:
        raise CandidateBuildError(
            "output and manifest must be two leaves of the same physical parent "
            f"directory; got {out_parent} and {manifest_parent}"
        )
    if out_name == manifest_name:
        raise CandidateBuildError(
            f"output and manifest must be different leaves, both named {out_name!r}"
        )
    _check_parent_boundary(out_parent)
    out_leaf = _reject_existing_leaf(out_parent, out_name, "output")
    manifest_leaf = _reject_existing_leaf(out_parent, manifest_name, "manifest")
    return out_leaf, manifest_leaf


def _is_private(rel: str) -> bool:
    parts = rel.split("/")
    if parts[0] in EXCLUDED_TOP_LEVEL:
        return True
    if any(part == "__pycache__" for part in parts[:-1]):
        return True
    if any(part.endswith(".egg-info") for part in parts):
        return True
    name = parts[-1]
    if name in PRIVATE_NAMES or name.startswith(".env"):
        return True
    return name.endswith(PRIVATE_SUFFIXES)


def _head_bytes(rel: str) -> bytes | None:
    proc = subprocess.run(
        ["git", "show", f"HEAD:{rel}"], cwd=ROOT, capture_output=True
    )
    if proc.returncode != 0:
        return None
    return proc.stdout


def _dirty_tracked() -> set[str]:
    """会话开始时已存在差异的 tracked 文件（既有用户工作，不属于本轮）。"""

    proc = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    dirty: set[str] = set()
    for line in proc.stdout.splitlines():
        if len(line) < 4:
            continue
        status, path = line[:2], line[3:].strip()
        if status.strip() == "??":
            continue
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        dirty.add(path)
    return dirty


def _tracked_files() -> list[str]:
    """HEAD 里全部被跟踪的产品文件（用于把候选补成可运行整树）。"""

    proc = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in proc.stdout.splitlines() if line]


def _source_paths() -> list[str]:
    tracked = _tracked_files()
    paths = sorted(set(tracked) | set(WORKTREE_CLOSURE) | set(THIS_ROUND_TESTS))
    kept = []
    for rel in paths:
        if _is_private(rel):
            continue
        kept.append(rel)
    return kept


def _preflight(paths: list[str]) -> dict[str, str]:
    """在任何目标写入之前冻结整份输入清单的字节摘要。"""

    frozen: dict[str, str] = {}
    for rel in paths:
        source = ROOT / rel
        if os.path.islink(source):
            raise CandidateBuildError(f"input path is a symlink, refusing: {rel}")
        try:
            info = os.stat(source)
        except OSError as error:
            raise CandidateBuildError(f"input path is unreadable: {rel} ({error})") from error
        if not stat.S_ISREG(info.st_mode):
            raise CandidateBuildError(f"input path is not a regular file: {rel}")
        try:
            frozen[rel] = _sha256(source)
        except OSError as error:
            raise CandidateBuildError(f"input path is unreadable: {rel} ({error})") from error
    return frozen


def _create_directory(path: Path, label: str) -> None:
    try:
        os.mkdir(path)
    except FileExistsError as error:
        raise CandidateBuildError(f"{label} already exists: {path}") from error
    except OSError as error:
        raise CandidateBuildError(f"{label} could not be created: {path} ({error})") from error


def _ensure_directory(path: Path) -> None:
    """在本次独占创建的 output 内建子目录，并拒绝被换入的链接。"""

    try:
        os.makedirs(path, exist_ok=True)
    except OSError as error:
        raise CandidateBuildError(f"directory could not be created: {path} ({error})") from error
    if os.path.islink(path) or not os.path.isdir(path):
        raise CandidateBuildError(f"directory path is not a real directory: {path}")


def _write_exclusive(target: Path, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        handle = os.open(target, flags, 0o644)
    except FileExistsError as error:
        raise CandidateBuildError(
            f"target already exists, refusing to overwrite: {target}"
        ) from error
    except OSError as error:
        raise CandidateBuildError(
            f"target could not be created: {target} ({error})"
        ) from error
    with os.fdopen(handle, "wb") as stream:
        stream.write(payload)


def _copy_tree(
    out_leaf: Path,
    frozen: dict[str, str],
    dirty: set[str],
    tracked: set[str],
) -> list[dict]:
    entries: list[dict] = []
    for rel in sorted(frozen):
        source = ROOT / rel
        target = out_leaf / rel
        _ensure_directory(target.parent)
        try:
            payload = source.read_bytes()
        except OSError as error:
            raise CandidateBuildError(
                f"input became unreadable during copy: {rel} ({error})"
            ) from error
        if _sha256_bytes(payload) != frozen[rel]:
            raise CandidateBuildError(f"input changed after preflight, aborting: {rel}")
        _write_exclusive(target, payload)
        copied = _sha256(target)
        if copied != frozen[rel]:
            raise CandidateBuildError(f"copied bytes differ from preflight digest: {rel}")
        if rel not in tracked:
            source_kind = "worktree-untracked"
        elif rel in dirty:
            source_kind = "worktree-modified"
        else:
            source_kind = "worktree-unmodified"
        reason = WORKTREE_CLOSURE.get(rel)
        if reason is None:
            reason = (
                f"this round fix ({ROUND})"
                if rel in THIS_ROUND or rel in THIS_ROUND_SUPPORT
                else "this round regression test"
                if rel in THIS_ROUND_TESTS
                else "pre-existing user work (dirty at session start)"
                if source_kind == "worktree-modified"
                else "new file this round"
                if source_kind == "worktree-untracked"
                else "unmodified product source"
            )
        entries.append(
            {
                "path": rel,
                "source": source_kind,
                "head_has_differences": rel in dirty,
                "this_round_modified": rel in THIS_ROUND,
                "reason": reason,
                "sha256": copied,
            }
        )
    return entries


def _publish_manifest(manifest_leaf: Path, payload: bytes) -> None:
    """在相同父目录写独占临时文件，再用不覆盖的 link 发布。"""

    handle, temp_name = tempfile.mkstemp(
        dir=str(manifest_leaf.parent), prefix=".candidate-manifest-", suffix=".tmp"
    )
    temp = Path(temp_name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(payload)
        try:
            os.link(temp, manifest_leaf)
        except FileExistsError as error:
            raise CandidateBuildError(
                f"manifest target was occupied before publish: {manifest_leaf}"
            ) from error
        except OSError as error:
            raise CandidateBuildError(
                f"manifest could not be published: {manifest_leaf} ({error})"
            ) from error
    finally:
        with contextlib.suppress(OSError):
            os.unlink(temp)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args()

    try:
        out_leaf, manifest_leaf = _plan_targets(args.out, args.manifest)
        paths = _source_paths()
        frozen = _preflight(paths)
        dirty = _dirty_tracked()
        tracked = set(_tracked_files())
        _create_directory(out_leaf, "output")
        entries = _copy_tree(out_leaf, frozen, dirty, tracked)
        manifest = {
            "generated_by": "scripts/build_candidate_manifest.py",
            "round": ROUND,
            "head": subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip(),
            "closure_files": sorted(WORKTREE_CLOSURE),
            "this_round_modified": sorted(THIS_ROUND | THIS_ROUND_SUPPORT | THIS_ROUND_TESTS),
            "file_count": len(entries),
            "files": entries,
        }
        payload = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        _publish_manifest(manifest_leaf, payload)
    except CandidateBuildError as error:
        print(f"build_candidate_manifest: {error}", file=sys.stderr)
        print(
            "no manifest was published; a partial candidate is left in place as "
            "incomplete — rebuild with a fresh path",
            file=sys.stderr,
        )
        return 1

    print(f"candidate: {out_leaf}")
    print(f"manifest: {manifest_leaf}")
    print(f"files: {len(entries)} (worktree-sourced: "
          f"{sum(1 for e in entries if e['source'] != 'head')})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
