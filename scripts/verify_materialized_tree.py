"""009 delivery verifier（严格只读，绝不被自身生成的真值欺骗）。

manifest（``docs/implementation/009_DELIVERY_MANIFEST.json``）是 admission 根信任，
手工冻结；verifier 没有 generate/broad-add/自动扫描模式，从不写 manifest，从不修改
真实 Git index，从不读取或 hash denied/private/runtime 路径。

核心函数对任意 ``repo_root`` 可测（v2 测试用隔离 temp repo/fixtures 驱动）：

- ``validate_manifest`` / ``reconcile_membership``：schema + 单一 no-follow descriptor
  同时完成 metadata 与 digest 校验、baseline/operation/owner/Git-mode 绑定、tracked
  delta + 显式 untracked admission + manifest operations 三方对账。
- ``materialize_tree``：用 ``GIT_INDEX_FILE`` 临时索引从 pinned baseline 精确 apply
  manifest operations，真实 ``.git/index`` 不被触碰。
- ``run_content_gate``（``--content``，U8A）：non-editable 安装到临时 prefix、neutral cwd
  origin 断言、sandbox-exec 负向 DNS/TCP 探针先证明阻断再跑 Ruff/pytest（不忽略 delivery
  测试，不可用或未阻断则 fail closed）。
- ``control_seal``（``--control-seal``）：重算 ordinary digest 并校验 reviewer controls
  的 seal_state/digest；missing/null/unsealed/drifted 一律失败。
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import socket
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MANIFEST_V2 = REPO / "docs" / "implementation" / "009_DELIVERY_MANIFEST.json"
SCHEMA_V2 = "my-first-agent/delivery-manifest/v2"

KNOWN_OWNER_UNITS = frozenset(
    {"audited-baseline", "U1", "U2", "U3", "U4", "U5", "U6", "U7", "U8A", "U8B"}
)
VALID_GIT_MODES = frozenset({"100644", "100755"})
SEALED_STATE = "sealed-u8"

# Path prefixes that must NEVER be admitted, read, or hashed（仅按路径拒绝，永不读取内容）。
DENIED_PREFIXES = (
    "tui/",
    ".env",
    ".ua/",
    "graphify-out/",
    ".claude-runtime/",
    ".claude/",
    "config.local",
    "session_snapshots/",
    "sessions/",
    "runs/",
    "state.json",
    "memory/",
    "skills/",
    "pytest.ini",
    "agent_log.jsonl",
    ".tui_audit_log",
    ".DS_Store",
    "node_modules/",
    ".venv/",
    "__pycache__/",
    ".pytest_cache/",
    ".ruff_cache/",
    ".mypy_cache/",
    ".coverage",
    "htmlcov/",
    "build/",
    "dist/",
    ".codex/",
    # loop 约定的仓库根临时 prompt/log 前缀;保持窄范围,不隐藏普通用户文件。
    ".codex-tmp-",
    ".opencode/",
    ".git-credentials",
    ".netrc",
)

CONTROL_PATHS = {
    "docs/implementation/009_DELIVERY_MANIFEST.json",
    "docs/implementation/009_EXECUTION_LOG.md",
    "docs/architecture/CURRENT_CAPABILITY_STATUS.md",
    "docs/implementation/009_INDEPENDENT_REVIEW.md",
}

# 产品 console entrypoint（pyproject [project.scripts]）：(脚本名, main 中的可调用名)。
# 用于显式断言 entrypoint 由 non-editable 安装生成、解析到 prefix 而非 dirty tree（N1）。
CONSOLE_ENTRYPOINTS = (
    ("first-agent", "main"),
    ("first-agent-schedule", "run_schedule"),
)


def _is_denied(path: str) -> bool:
    import fnmatch

    for prefix in DENIED_PREFIXES:
        if path.startswith(prefix) or fnmatch.fnmatch(path, prefix):
            return True
    return False


def _git(repo_root: Path, *args: str, env: dict | None = None) -> str:
    result = subprocess.run(
        ["git", *args], cwd=str(repo_root), check=True, capture_output=True, text=True, env=env
    )
    return result.stdout


def _git_ok(repo_root: Path, *args: str, env: dict | None = None) -> tuple[int, str]:
    result = subprocess.run(
        ["git", *args], cwd=str(repo_root), capture_output=True, text=True, env=env
    )
    return result.returncode, result.stdout + result.stderr


def _load_manifest_at(path: Path) -> dict:
    if not path.is_file():
        print(f"FAIL: manifest not found: {path}", file=sys.stderr)
        sys.exit(1)
    return json.loads(path.read_text())


def _load_manifest() -> dict:
    return _load_manifest_at(MANIFEST_V2)


def _git_mode_for_stat(info: os.stat_result) -> str:
    return "100755" if (info.st_mode & 0o111) else "100644"


def admit_descriptor(path: Path) -> tuple[os.stat_result, str]:
    """单一 no-follow descriptor：同一 fd 同时做 metadata（fstat）与 digest（read）。

    消除“先 open/close 校验 metadata、再按 path 重开 hash”的 TOCTOU。拒绝 symlink、
    非 regular、link count != 1、非当前用户拥有的对象。
    """
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise ValueError("not a regular file")
        if info.st_nlink != 1:
            raise ValueError(f"link count {info.st_nlink}")
        if info.st_uid != os.getuid():
            raise ValueError("not owner-controlled")
        digest = hashlib.sha256()
        while True:
            chunk = os.read(fd, 65_536)
            if not chunk:
                break
            digest.update(chunk)
        return info, digest.hexdigest()
    finally:
        os.close(fd)


def validate_manifest(manifest: dict, repo_root: Path) -> list[str]:
    """schema + baseline + operation + owner ordering + Git mode/type 绑定（不读内容）。"""
    errors: list[str] = []
    if manifest.get("schema") != SCHEMA_V2:
        errors.append(f"schema must be {SCHEMA_V2!r}, got {manifest.get('schema')!r}")
    baseline = manifest.get("baseline_commit")
    if not isinstance(baseline, str) or len(baseline) != 40:
        errors.append("baseline_commit must be a full 40-char Git SHA")
    else:
        rc, _ = _git_ok(repo_root, "cat-file", "-e", f"{baseline}^{{commit}}")
        if rc != 0:
            errors.append(f"baseline_commit {baseline} does not exist in repo")
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        errors.append("entries must be a list")
        return errors
    paths: set[str] = set()
    manifest_rel = MANIFEST_V2.relative_to(REPO).as_posix() if repo_root == REPO else None
    for entry in entries:
        path = entry.get("path") if isinstance(entry, dict) else None
        if not isinstance(path, str) or not path:
            errors.append(f"entry missing path: {entry!r}")
            continue
        if Path(path).is_absolute() or ".." in Path(path).parts:
            errors.append(f"entry path must be repo-relative: {path}")
        if path in paths:
            errors.append(f"duplicate entry path: {path}")
        if _is_denied(path):
            errors.append(f"DENIED path admitted: {path}")
        if path in CONTROL_PATHS:
            errors.append(f"control path in entries (forbidden): {path}")
        if manifest_rel and path == manifest_rel:
            errors.append("manifest self-entry is forbidden")
        paths.add(path)
        op = entry.get("operation")
        if op not in ("add", "modify", "delete"):
            errors.append(f"{path}: invalid operation {op!r}")
        owners = entry.get("owner_units")
        if not isinstance(owners, list) or not owners:
            errors.append(f"{path}: owner_units must be a non-empty ordered list")
        else:
            unknown = [o for o in owners if o not in KNOWN_OWNER_UNITS]
            if unknown:
                errors.append(f"{path}: unknown owner_units {unknown}")
            if len(set(owners)) != len(owners):
                errors.append(f"{path}: owner_units must be ordered without duplicates")
        if op in ("add", "modify"):
            sha = entry.get("sha256")
            if not isinstance(sha, str) or len(sha) != 40 + 24:
                errors.append(f"{path}: add/modify requires 64-char sha256")
            mode = entry.get("git_mode")
            if mode not in VALID_GIT_MODES:
                errors.append(f"{path}: add/modify requires git_mode in {sorted(VALID_GIT_MODES)}")
        elif op == "delete":
            if "sha256" in entry or "git_mode" in entry:
                errors.append(f"{path}: delete must not carry sha256/git_mode")
    errors.extend(_validate_control_files(manifest))
    return errors


def _validate_control_files(manifest: dict) -> list[str]:
    errors: list[str] = []
    controls = manifest.get("control_files", [])
    if not isinstance(controls, list):
        errors.append("control_files must be a list")
        return errors
    for cf in controls:
        if not isinstance(cf, dict) or "path" not in cf:
            errors.append(f"control_files entry malformed: {cf!r}")
            continue
        if _is_denied(cf["path"]):
            errors.append(f"DENIED control path: {cf['path']}")
    return errors


def _tracked_name_status(repo_root: Path, baseline: str) -> dict[str, str]:
    """baseline..working-tree 的 tracked 文件变更（M=modify, D=delete）；不含 untracked。"""
    out = _git(repo_root, "diff", "--name-status", baseline, "--")
    result: dict[str, str] = {}
    for line in out.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        code = parts[0]
        path = parts[-1]
        if code.startswith("D"):
            result[path] = "delete"
        elif code.startswith(("M", "R", "C", "A", "T")):
            result[path] = "modify"
    return result


def _untracked_paths(repo_root: Path) -> list[str]:
    out = _git(repo_root, "ls-files", "--others", "--exclude-standard")
    return [line.strip() for line in out.splitlines() if line.strip()]


def reconcile_membership(manifest: dict, repo_root: Path) -> list[str]:
    """三方对账：tracked delta（pinned baseline）+ 显式 untracked admission + manifest ops。

    denied/unknown 路径在 open/read/hash 之前失败；add/modify 用同一 no-follow descriptor
    同时校验 metadata（regular/nlink/owner/Git mode）与 digest。
    """
    errors = validate_manifest(manifest, repo_root)
    baseline = manifest.get("baseline_commit", "")
    entries = manifest.get("entries", [])
    manifest_paths: dict[str, dict] = {e["path"]: e for e in entries}

    # 1) admission：denied 先于 read；add/modify 单一 descriptor 校验 digest + git_mode。
    for entry in entries:
        path = entry["path"]
        op = entry["operation"]
        if op == "delete" or _is_denied(path):
            continue
        full = repo_root / path
        if not full.is_file():
            errors.append(f"{path}: add/modify entry missing from worktree")
            continue
        try:
            info, digest = admit_descriptor(full)
        except (OSError, ValueError) as exc:
            errors.append(f"{path}: admission failed: {exc}")
            continue
        expected_sha = entry.get("sha256")
        if isinstance(expected_sha, str) and digest != expected_sha:
            errors.append(f"{path}: sha256 mismatch (manifest drift)")
        expected_mode = entry.get("git_mode")
        if expected_mode and _git_mode_for_stat(info) != expected_mode:
            errors.append(
                f"{path}: git_mode mismatch (declared {expected_mode}, "
                f"actual {_git_mode_for_stat(info)})"
            )

    # 2) tracked delta vs manifest operations。
    if isinstance(baseline, str) and len(baseline) == 40:
        try:
            tracked = _tracked_name_status(repo_root, baseline)
        except subprocess.CalledProcessError as exc:
            errors.append(f"baseline diff failed: {exc}")
            tracked = {}
        for path, real_op in tracked.items():
            # denied/control 路径排除在交付之外：其 tracked delta 无需 manifest 声明。
            if _is_denied(path) or path in CONTROL_PATHS:
                continue
            entry = manifest_paths.get(path)
            if entry is None:
                errors.append(f"tracked {real_op} '{path}' not declared in manifest")
            elif entry["operation"] != real_op:
                errors.append(
                    f"{path}: manifest op '{entry['operation']}' != tracked '{real_op}'"
                )
        for path, entry in manifest_paths.items():
            if _is_denied(path) or path in CONTROL_PATHS:
                continue
            if entry["operation"] in ("modify", "delete") and path not in tracked:
                errors.append(
                    f"{path}: manifest '{entry['operation']}' has no tracked delta vs baseline"
                )

    # 3) 显式 untracked admission：非 denied 的 untracked 必须作为 add 声明。
    for path in _untracked_paths(repo_root):
        if _is_denied(path) or path in CONTROL_PATHS:
            continue
        entry = manifest_paths.get(path)
        if entry is None:
            errors.append(f"unknown untracked not admitted: {path}")
        elif entry["operation"] != "add":
            errors.append(f"untracked '{path}' must be admitted as 'add'")

    return errors


def materialize_tree(manifest: dict, repo_root: Path, dest: Path) -> list[str]:
    """用临时 GIT_INDEX_FILE 从 pinned baseline 精确 apply manifest operations 到 dest。

    真实 ``.git/index`` 不被触碰（GIT_INDEX_FILE 指向临时文件）。
    """
    errors: list[str] = []
    baseline = manifest.get("baseline_commit", "")
    if not (isinstance(baseline, str) and len(baseline) == 40):
        return ["baseline_commit must be a full 40-char Git SHA"]
    dest.mkdir(parents=True, exist_ok=True)
    temp_index = Path(tempfile.mkstemp(prefix="009-index-", suffix=".tmp")[1])
    try:
        env = dict(os.environ)
        env["GIT_INDEX_FILE"] = str(temp_index)
        rc, out = _git_ok(repo_root, "read-tree", baseline, env=env)
        if rc != 0:
            return [f"read-tree baseline failed: {out.strip()}"]
        for entry in manifest.get("entries", []):
            path = entry["path"]
            op = entry["operation"]
            if op == "delete":
                _git_ok(repo_root, "update-index", "--force-remove", "--", path, env=env)
            else:
                rc, out = _git_ok(repo_root, "update-index", "--add", "--", path, env=env)
                if rc != 0:
                    errors.append(f"{path}: update-index failed: {out.strip()}")
        rc, out = _git_ok(
            repo_root, "checkout-index", "-a", "-f", f"--prefix={dest}/", env=env
        )
        if rc != 0:
            errors.append(f"checkout-index failed: {out.strip()}")
    finally:
        with __import__("contextlib").suppress(OSError):
            temp_index.unlink()
    # baseline 中的 denied/private/runtime 前缀（旧 tui/、skills/、.claude/ 等前端）不是产品：
    # 它们按路径拒绝、不进 manifest，checkout-index 后必须从 materialized tree 剥离。
    import shutil

    for leaked in list(dest.rglob("*")):
        if leaked.is_file():
            rel = leaked.relative_to(dest).as_posix()
            if _is_denied(rel):
                with __import__("contextlib").suppress(OSError):
                    leaked.unlink()
    # post-gate control 文件不是 entry、也不在 baseline，但 claim-verification 测试需要读取
    # 它们；manifest 自身（self-digest-forbidden）不复制。
    for cf in manifest.get("control_files", []):
        cf_path = cf.get("path") if isinstance(cf, dict) else None
        if not cf_path or cf_path.endswith("009_DELIVERY_MANIFEST.json"):
            continue
        src = repo_root / cf_path
        if src.is_file():
            dst = dest / cf_path
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    return errors


# --- deny-network boundary（sandbox-exec）---

SANDBOX_EXEC = "/usr/bin/sandbox-exec"


def build_sandbox_profile(*, extra_writable: tuple[Path, ...] = ()) -> str:
    # (allow default) 提供 ruff(Rust)/python/pytest 等所需的基线 syscall（guard page 等）；
    # 网络由后续 (deny network*) 显式阻断，deny 优先于 allow-default。
    write_clauses = ['(allow file-write* (subpath "/tmp"))']
    for path in extra_writable:
        write_clauses.append(f'(allow file-write* (subpath "{path}"))')
    return (
        "(version 1)\n"
        "(allow default)\n"
        "(deny network*)\n"
        + "\n".join(write_clauses)
        + "\n"
    )


def run_under_sandbox(
    cmd: list[str], profile: str, *, sandbox_exec: str = SANDBOX_EXEC, timeout: int = 900,
    env: dict | None = None, cwd: str | None = None,
) -> tuple[int, str]:
    try:
        result = subprocess.run(
            [sandbox_exec, "-p", profile, *cmd],
            capture_output=True, text=True, timeout=timeout, env=env, cwd=cwd,
        )
        return result.returncode, result.stdout + result.stderr
    except FileNotFoundError:
        return 127, f"sandbox-exec not found: {sandbox_exec}"
    except subprocess.TimeoutExpired:
        return 124, "sandbox command timed out"


def deny_network_preflight(
    profile: str, *, sandbox_exec: str = SANDBOX_EXEC, python: str | None = None
) -> tuple[bool, str]:
    """负向探针：在 sandbox 内尝试连接本地 listener。能连=未阻断；被拒=已阻断。"""
    py = python or sys.executable
    # 自身若已处于 deny-network 边界（content gate 把 pytest 整体置于 sandbox），任何 connect
    # 会立即 EPERM——这本身就是边界已生效的证明，且无法再嵌套 sandbox-exec。
    self_check = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    self_check.settimeout(1)
    try:
        self_check.connect(("127.0.0.1", 1))
        self_check.close()
    except OSError as exc:
        self_check.close()
        if exc.errno == errno.EPERM:
            return True, "deny-network enforced: connect denied under existing boundary"
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
    except OSError as exc:
        srv.close()
        # 自身已在 deny-network 边界下（content gate 把 pytest 整体置于 sandbox）：
        # bind 被拒（EPERM）即边界已生效，无需再跑 probe。
        if exc.errno == errno.EPERM:
            return True, "deny-network enforced: bind denied under existing boundary"
        return False, f"deny-network probe could not bind listener: {exc}"
    probe = (
        "import socket\n"
        "s=socket.socket(); s.settimeout(3)\n"
        "try:\n"
        f"    s.connect(('127.0.0.1',{port})); print('CONNECTED')\n"
        "except OSError:\n"
        "    print('DENIED')\n"
    )
    try:
        rc, out = run_under_sandbox(
            [py, "-c", probe], profile, sandbox_exec=sandbox_exec, timeout=15
        )
    finally:
        srv.close()
    if "CONNECTED" in out:
        return False, "deny-network NOT enforced: probe connected through sandbox"
    if "DENIED" in out:
        return True, "deny-network enforced via sandbox-exec"
    return False, (
        f"deny-network probe inconclusive: rc={rc} out={out.strip()[:200]}"
    )


# --- content gate（--content / U8A）---

def _site_packages_dir(prefix: Path, python: str) -> Path:
    info = subprocess.run(
        [python, "-c", "import sys; print(sys.version_info[0], sys.version_info[1])"],
        capture_output=True, text=True,
    )
    major, minor = info.stdout.split()
    return prefix / "lib" / f"python{major}.{minor}" / "site-packages"


def install_noneditable(
    tree_dir: Path, prefix: Path, *, python: str | None = None
) -> tuple[int, str]:
    """non-editable、no-deps 安装 materialized tree 到 prefix；返回 (rc, output)。"""
    py = python or sys.executable
    cmd = [
        py, "-m", "pip", "install", "--no-deps", "--no-build-isolation",
        "--prefix", str(prefix), str(tree_dir),
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300,
            env={**os.environ, "PIP_NO_INDEX": "1"},
        )
        return result.returncode, result.stdout + result.stderr
    except FileNotFoundError:
        return 127, "pip not available"
    except subprocess.TimeoutExpired:
        return 124, "install timed out"


def assert_origin(
    prefix: Path, dirty_root: Path, *, python: str | None = None, neutral_cwd: Path | None = None
) -> tuple[bool, str]:
    """neutral cwd 下从 prefix 导入 agent/main；origin 不得指回 dirty tree。"""
    py = python or sys.executable
    site_dir = _site_packages_dir(prefix, py)
    env = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "PYTHONHOME"}}
    env["PYTHONPATH"] = str(site_dir)
    script = (
        "import agent, main\n"
        f"assert {str(dirty_root)!r} not in agent.__file__, agent.__file__\n"
        f"assert {str(dirty_root)!r} not in main.__file__, main.__file__\n"
        f"assert {str(prefix)!r} in agent.__file__, agent.__file__\n"
        "print('ORIGIN_OK')\n"
    )
    cwd = neutral_cwd or Path(tempfile.gettempdir())
    try:
        result = subprocess.run(
            [py, "-c", script], cwd=str(cwd), capture_output=True, text=True, env=env, timeout=30
        )
    except FileNotFoundError:
        return False, "python not available"
    out = result.stdout + result.stderr
    if result.returncode == 0 and "ORIGIN_OK" in out:
        return True, "origin resolves to non-editable install"
    return False, f"origin check failed: {out.strip()[:300]}"


def assert_console_entrypoint_origin(
    prefix: Path,
    dirty_root: Path,
    *,
    python: str | None = None,
    neutral_cwd: Path | None = None,
    entrypoints: tuple[tuple[str, str] | tuple[str, str, str], ...] = CONSOLE_ENTRYPOINTS,
) -> tuple[bool, str]:
    """显式验证 console entrypoint 来自 prefix 安装而非 dirty tree（N1）。

    每个 entrypoint 必须作为 owner-controlled regular file 存在于 ``prefix/bin``、
    不解析到 prefix 之外、是 install 生成的 wrapper（target 为 ``main:<fn>``），并在
    prefix-first 环境、neutral cwd 下经 ``--help`` 端到端加载——这证明 wrapper 从安装
    处解析 ``main`` 及其全部传递导入。``--help`` 在任何真实工作前经 argparse 以 exit 0
    返回，故 exit 0 即说明 wrapper 的 ``from main import <fn>`` 在该环境下成功。

    与 :func:`assert_origin` 互补且组合使用：后者在同一 prefix-first 环境下证明
    ``agent``/``main`` 模块的 ``__file__`` 落在 prefix（而非 ``dirty_root``）；本函数
    证明 *console entrypoint*（pip 生成的 ``prefix/bin`` wrapper）在该环境下同样加载
    该 prefix 的 ``main``，且 wrapper 本身不是 dirty-tree 文件或指向它的链接。
    ``dirty_root`` 在此仅作为意图标注与 API 对称，实质 prefix-vs-dirty 区分由
    :func:`assert_origin` 与本函数的 ``--help`` 加载共同建立。
    """
    py = python or sys.executable
    site_dir = _site_packages_dir(prefix, py)
    bin_dir = prefix / "bin"
    cwd = neutral_cwd or Path(tempfile.gettempdir())
    env = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "PYTHONHOME"}}
    env["PYTHONPATH"] = str(site_dir)
    prefix_resolved = prefix.resolve()
    for entrypoint in entrypoints:
        if len(entrypoint) == 2:
            name, target = entrypoint
            module = "main"
        else:
            name, module, target = entrypoint
        ep = bin_dir / name
        if not ep.is_file():
            return False, f"console entrypoint missing in prefix/bin: {name}"
        # wrapper 必须是 owner-controlled regular file（拒绝 symlink/hardlink 进 dirty tree）。
        try:
            admit_descriptor(ep)
        except (OSError, ValueError) as exc:
            return False, f"console entrypoint {name} not owner-regular: {exc}"
        try:
            resolved = ep.resolve()
        except OSError as exc:
            return False, f"console entrypoint {name} unresolvable: {exc}"
        if not resolved.is_relative_to(prefix_resolved):
            return False, f"console entrypoint {name} escapes prefix"
        body = ep.read_text()
        if f"from {module} import {target}" not in body:
            return False, f"console entrypoint {name} does not target {module}:{target}"
        # 端到端：prefix-first 环境、neutral cwd 下 --help 加载 wrapper（main + 传递导入）。
        try:
            result = subprocess.run(
                [py, str(ep), "--help"],
                cwd=str(cwd), capture_output=True, text=True, env=env, timeout=30,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False, f"console entrypoint {name} --help probe failed"
        if result.returncode != 0:
            tail = (result.stdout + result.stderr).strip()[:200]
            return False, f"console entrypoint {name} --help exit {result.returncode}: {tail}"
    return True, "console entrypoints resolve to non-editable install"


def content_pytest_args(tree_dir: Path) -> list[str]:
    """content gate 跑的 pytest 参数：完整 tests，不 --ignore 任何 delivery 测试。"""
    return ["pytest", "-q", "--tb=short", str(tree_dir / "tests")]


def _cleanup(prefix: Path) -> None:
    import shutil

    with __import__("contextlib").suppress(Exception):
        shutil.rmtree(prefix, ignore_errors=True)


def run_content_gate(repo_root: Path = REPO, *, python: str | None = None) -> int:
    """U8A content gate。任一阶段失败即 fail closed；deny-network 不可用或未阻断直接失败。"""
    py = python or sys.executable
    manifest_path = MANIFEST_V2 if repo_root == REPO else _manifest_path_for(repo_root)
    manifest = _load_manifest_at(manifest_path)
    membership_errors = reconcile_membership(manifest, repo_root)
    if membership_errors:
        for error in membership_errors[:50]:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="009-tree-") as tree_dir_s:
        tree_dir = Path(tree_dir_s)
        mat_errors = materialize_tree(manifest, repo_root, tree_dir)
        if mat_errors:
            for error in mat_errors:
                print(f"FAIL: {error}", file=sys.stderr)
            return 1

        prefix = Path(tempfile.mkdtemp(prefix="009-prefix-"))
        install_rc, install_out = install_noneditable(tree_dir, prefix, python=py)
        if install_rc != 0:
            print(
                f"FAIL: non-editable install failed: {install_out.strip()[:400]}",
                file=sys.stderr,
            )
            _cleanup(prefix)
            return 1
        print("content gate: non-editable install ok", file=sys.stderr)

        ok, msg = assert_origin(prefix, repo_root, python=py)
        if not ok:
            print(f"FAIL: {msg}", file=sys.stderr)
            _cleanup(prefix)
            return 1
        print("content gate: origin ok", file=sys.stderr)

        ok, msg = assert_console_entrypoint_origin(prefix, repo_root, python=py)
        if not ok:
            print(f"FAIL: {msg}", file=sys.stderr)
            _cleanup(prefix)
            return 1
        print("content gate: console entrypoint origin ok", file=sys.stderr)

        profile = build_sandbox_profile(extra_writable=(prefix, tree_dir))
        denied, dmsg = deny_network_preflight(profile, python=py)
        if not denied:
            print(f"FAIL: {dmsg}", file=sys.stderr)
            _cleanup(prefix)
            return 1
        print(f"content gate: {dmsg}", file=sys.stderr)

        ruff_rc, ruff_out = run_under_sandbox(
            [
                str(REPO / ".venv" / "bin" / "ruff"), "check",
                str(tree_dir / "agent"), str(tree_dir / "tests"),
            ],
            profile,
        )
        if ruff_rc != 0:
            print(f"FAIL: ruff: {ruff_out.strip()[:400]}", file=sys.stderr)
            _cleanup(prefix)
            return 1
        print("content gate: ruff passed", file=sys.stderr)

        # pytest 从 non-editable install 导入 agent（PYTHONPATH=prefix 优先），tests 包来自
        # materialized tree；cwd 为 neutral，REPO 不进入 sys.path，满足 AE10。
        site_dir = _site_packages_dir(prefix, py)
        pt_env = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "PYTHONHOME"}}
        pt_env["PYTHONPATH"] = f"{site_dir}{os.pathsep}{tree_dir}"
        pt_cmd = content_pytest_args(tree_dir)
        neutral_cwd = tempfile.mkdtemp(prefix="009-neutral-")
        pt_rc, pt_out = run_under_sandbox(
            [py, "-m", *pt_cmd], profile, timeout=1200, env=pt_env, cwd=neutral_cwd
        )
        with __import__("contextlib").suppress(Exception):
            __import__("shutil").rmtree(neutral_cwd, ignore_errors=True)
        if pt_rc != 0:
            print(f"FAIL: pytest: {pt_out.strip()[:2000]}", file=sys.stderr)
            _cleanup(prefix)
            return 1
        last_line = pt_out.strip().split("\n")[-1] if pt_out.strip() else ""
        print(f"content gate: pytest passed ({last_line})", file=sys.stderr)
        _cleanup(prefix)

    print("content gate: ALL CHECKS PASSED", file=sys.stderr)
    return 0


def _manifest_path_for(repo_root: Path) -> Path:
    return repo_root / "docs" / "implementation" / "009_DELIVERY_MANIFEST.json"


def control_seal(manifest: dict, repo_root: Path) -> int:
    """重算 ordinary digest 并校验 reviewer controls 的 seal_state/digest。

    missing/null/unsealed/drifted control 一律失败。executor 不写 sealed 状态。
    """
    errors: list[str] = list(validate_manifest(manifest, repo_root))
    for entry in manifest.get("entries", []):
        if entry["operation"] == "delete":
            continue
        full = repo_root / entry["path"]
        if full.is_file():
            try:
                _, digest = admit_descriptor(full)
            except (OSError, ValueError) as exc:
                errors.append(f"{entry['path']}: admission failed: {exc}")
                continue
            if digest != entry.get("sha256"):
                errors.append(f"{entry['path']}: ordinary digest drifted since content gate")
    for cf in manifest.get("control_files", []):
        path = cf.get("path")
        if path == "docs/implementation/009_DELIVERY_MANIFEST.json":
            continue
        if not isinstance(path, str):
            errors.append(f"control_files entry missing path: {cf!r}")
            continue
        full = repo_root / path
        if not full.is_file():
            errors.append(f"control missing: {path}")
            continue
        sha = cf.get("sha256")
        seal = cf.get("seal_state")
        if not isinstance(sha, str) or len(sha) != 64:
            errors.append(f"control {path}: sha256 missing/null (not sealed)")
            continue
        if seal != SEALED_STATE:
            errors.append(f"control {path}: seal_state is {seal!r} (not sealed)")
            continue
        try:
            digest = hashlib.sha256(full.read_bytes()).hexdigest()
        except OSError as exc:
            errors.append(f"control {path}: unreadable: {exc}")
            continue
        if digest != sha:
            errors.append(f"control {path}: digest drifted (seal broken)")
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print("control seal: all digests verified")
    return 0


def check_membership(repo_root: Path = REPO) -> int:
    manifest = _load_manifest()
    errors = reconcile_membership(manifest, repo_root)
    if errors:
        for error in errors[:50]:
            print(f"FAIL: {error}", file=sys.stderr)
        if len(errors) > 50:
            print(f"... and {len(errors) - 50} more", file=sys.stderr)
        return 1
    print(f"membership ok: {len(manifest['entries'])} entries")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check-membership", action="store_true")
    group.add_argument("--content", action="store_true")
    group.add_argument("--control-seal", action="store_true")
    args = parser.parse_args(argv)
    if args.check_membership:
        return check_membership()
    if args.content:
        return run_content_gate()
    if args.control_seal:
        return control_seal(_load_manifest(), REPO)
    return 0


if __name__ == "__main__":
    sys.exit(main())
