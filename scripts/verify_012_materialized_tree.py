"""012 增量交付校验与 materialized content gate。

009 manifest 是已封存的 Kernel/capability 候选树。012 不改写它，而是计算当前树相对
009 候选树的精确 overlay，并用 ``012_DELIVERY_SEAL.json`` 中的单一根摘要绑定路径、
operation、mode 与内容。seal 和执行日志是 post-gate controls，不进入 overlay 自身。

本 verifier 没有 generate/write 模式，不修改真实 Git index，也不会读取 denied/private/
runtime 路径。materialization 使用临时 index，随后从 neutral cwd 对 non-editable 安装运行
Ruff 与完整 pytest，并在 macOS sandbox-exec deny-network 边界内 fail closed。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from scripts.verify_materialized_tree import (
        _git_mode_for_stat,
        _git_ok,
        _is_denied,
        _site_packages_dir,
        admit_descriptor,
        assert_console_entrypoint_origin,
        assert_origin,
        build_sandbox_profile,
        deny_network_preflight,
        install_noneditable,
        run_under_sandbox,
    )
except ModuleNotFoundError:  # direct ``python scripts/...`` execution
    from verify_materialized_tree import (  # type: ignore[no-redef]
        _git_mode_for_stat,
        _git_ok,
        _is_denied,
        _site_packages_dir,
        admit_descriptor,
        assert_console_entrypoint_origin,
        assert_origin,
        build_sandbox_profile,
        deny_network_preflight,
        install_noneditable,
        run_under_sandbox,
    )

REPO = Path(__file__).resolve().parents[1]
BASE_MANIFEST_PATH = REPO / "docs" / "implementation" / "009_DELIVERY_MANIFEST.json"
SEAL_PATH = REPO / "docs" / "implementation" / "012_DELIVERY_SEAL.json"
SCHEMA = "my-first-agent/delivery-overlay-seal/v1"

# 这些文件描述/校验交付，而不是产品交付内容。execution log 在 gate 后继续追加事实，
# 因此不能反向进入它所记录的 ordinary root。
CONTROL_PATHS = frozenset(
    {
        "docs/implementation/012_DELIVERY_SEAL.json",
        "docs/implementation/012_EXECUTION_LOG.md",
        "scripts/verify_012_materialized_tree.py",
    }
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON control {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"invalid JSON control {path.name}: object required")
    return value


def _untracked_paths(repo_root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z", "--others", "--exclude-standard"],
        cwd=repo_root,
        check=True,
        capture_output=True,
    )
    try:
        return [part.decode("utf-8") for part in result.stdout.split(b"\0") if part]
    except UnicodeDecodeError as exc:
        raise ValueError("untracked path is not UTF-8 representable") from exc


def _exists_no_follow(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def _descriptor(repo_root: Path, relative: str, operation: str) -> dict:
    info, digest = admit_descriptor(repo_root / relative)
    return {
        "path": relative,
        "operation": operation,
        "git_mode": _git_mode_for_stat(info),
        "sha256": digest,
    }


def derive_overlay(base_manifest: dict, repo_root: Path = REPO) -> list[dict]:
    """计算当前安全工作树相对 009 候选树的 closed overlay。"""
    entries = base_manifest.get("entries")
    if not isinstance(entries, list):
        raise ValueError("009 manifest entries must be a list")
    base_by_path = {entry["path"]: entry for entry in entries}
    base_controls = {
        item.get("path")
        for item in base_manifest.get("control_files", [])
        if isinstance(item, dict)
    }
    overlay: list[dict] = []

    for relative, base in base_by_path.items():
        if _is_denied(relative) or relative in CONTROL_PATHS or relative in base_controls:
            continue
        present = _exists_no_follow(repo_root / relative)
        base_operation = base.get("operation")
        if base_operation == "delete":
            if present:
                overlay.append(_descriptor(repo_root, relative, "add"))
            continue
        if base_operation not in {"add", "modify"}:
            raise ValueError(f"009 manifest has invalid operation for {relative}")
        if not present:
            overlay.append({"path": relative, "operation": "delete"})
            continue
        current = _descriptor(repo_root, relative, "modify")
        if current["sha256"] != base.get("sha256") or current["git_mode"] != base.get("git_mode"):
            overlay.append(current)

    for relative in _untracked_paths(repo_root):
        if (
            relative in base_by_path
            or relative in base_controls
            or relative in CONTROL_PATHS
            or _is_denied(relative)
        ):
            continue
        overlay.append(_descriptor(repo_root, relative, "add"))

    overlay.sort(key=lambda item: item["path"])
    if len({item["path"] for item in overlay}) != len(overlay):
        raise ValueError("duplicate path in derived 012 overlay")
    return overlay


def overlay_root(base_manifest_sha256: str, entries: list[dict]) -> str:
    payload = {
        "base_manifest_sha256": base_manifest_sha256,
        "entries": entries,
    }
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def validate_delivery(repo_root: Path = REPO) -> tuple[list[dict], list[str]]:
    errors: list[str] = []
    try:
        base = _load_json(repo_root / BASE_MANIFEST_PATH.relative_to(REPO))
        seal = _load_json(repo_root / SEAL_PATH.relative_to(REPO))
    except ValueError as exc:
        return [], [str(exc)]
    if seal.get("schema") != SCHEMA:
        errors.append(f"seal schema must be {SCHEMA!r}")
    base_digest = _sha256(repo_root / BASE_MANIFEST_PATH.relative_to(REPO))
    if seal.get("base_manifest_sha256") != base_digest:
        errors.append("009 base manifest digest drift")
    verifier_digest = _sha256(repo_root / "scripts" / "verify_012_materialized_tree.py")
    if seal.get("verifier_sha256") != verifier_digest:
        errors.append("012 verifier digest drift")
    try:
        entries = derive_overlay(base, repo_root)
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        return [], [*errors, f"overlay admission failed: {exc}"]
    actual_root = overlay_root(base_digest, entries)
    if seal.get("entry_count") != len(entries):
        errors.append(
            f"overlay entry count drift: expected {seal.get('entry_count')}, actual {len(entries)}"
        )
    if seal.get("overlay_root_sha256") != actual_root:
        errors.append("012 overlay root digest drift")
    return entries, errors


def check_membership(repo_root: Path = REPO) -> int:
    entries, errors = validate_delivery(repo_root)
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"012 overlay membership ok: {len(entries)} exact entries")
    return 0


def materialize_tree(entries: list[dict], repo_root: Path, dest: Path) -> list[str]:
    """从 009 pinned baseline + 当前 admitted 009 paths + 012 overlay 物化精确候选树。"""
    base = _load_json(repo_root / BASE_MANIFEST_PATH.relative_to(REPO))
    baseline = base.get("baseline_commit")
    if not isinstance(baseline, str) or len(baseline) != 40:
        return ["009 baseline_commit must be a full Git SHA"]
    overlay_by_path = {entry["path"]: entry for entry in entries}
    dest.mkdir(parents=True, exist_ok=True)
    fd, index_name = tempfile.mkstemp(prefix="012-index-", suffix=".tmp")
    os.close(fd)
    index_path = Path(index_name)
    errors: list[str] = []
    env = {**os.environ, "GIT_INDEX_FILE": str(index_path)}
    try:
        rc, out = _git_ok(repo_root, "read-tree", baseline, env=env)
        if rc != 0:
            return [f"read-tree baseline failed: {out.strip()}"]
        for base_entry in base.get("entries", []):
            relative = base_entry["path"]
            overlay = overlay_by_path.get(relative)
            if base_entry["operation"] == "delete" or (
                overlay is not None and overlay["operation"] == "delete"
            ):
                _git_ok(repo_root, "update-index", "--force-remove", "--", relative, env=env)
                continue
            rc, out = _git_ok(repo_root, "update-index", "--add", "--", relative, env=env)
            if rc != 0:
                errors.append(f"{relative}: update-index failed: {out.strip()}")
        for entry in entries:
            if entry["operation"] == "delete":
                _git_ok(
                    repo_root,
                    "update-index",
                    "--force-remove",
                    "--",
                    entry["path"],
                    env=env,
                )
            else:
                rc, out = _git_ok(repo_root, "update-index", "--add", "--", entry["path"], env=env)
                if rc != 0:
                    errors.append(f"{entry['path']}: update-index failed: {out.strip()}")
        if errors:
            return errors
        rc, out = _git_ok(repo_root, "checkout-index", "-a", "-f", f"--prefix={dest}/", env=env)
        if rc != 0:
            errors.append(f"checkout-index failed: {out.strip()}")
    finally:
        index_path.unlink(missing_ok=True)

    # baseline 可能包含后来明确切除的 private/legacy prefixes；按路径剥离且不读取内容。
    for candidate in sorted(dest.rglob("*"), reverse=True):
        relative = candidate.relative_to(dest).as_posix()
        if candidate.is_file() and _is_denied(relative):
            candidate.unlink()

    # 009/012 control 不是 ordinary overlay，但 delivery/content tests 需要 verifier 本身。
    controls = {
        item.get("path") for item in base.get("control_files", []) if isinstance(item, dict)
    }
    controls.update(CONTROL_PATHS - {"docs/implementation/012_EXECUTION_LOG.md"})
    for relative in controls:
        if not isinstance(relative, str) or relative.endswith("009_DELIVERY_MANIFEST.json"):
            continue
        source = repo_root / relative
        if source.is_file():
            target = dest / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    return errors


def run_content_gate(repo_root: Path = REPO, *, python: str | None = None) -> int:
    py = python or sys.executable
    entries, errors = validate_delivery(repo_root)
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="012-tree-") as tree_name:
        tree = Path(tree_name)
        errors = materialize_tree(entries, repo_root, tree)
        if errors:
            for error in errors:
                print(f"FAIL: {error}", file=sys.stderr)
            return 1
        prefix = Path(tempfile.mkdtemp(prefix="012-prefix-"))
        try:
            rc, output = install_noneditable(tree, prefix, python=py)
            if rc != 0:
                print(f"FAIL: non-editable install: {output[-1000:]}", file=sys.stderr)
                return 1
            ok, message = assert_origin(prefix, repo_root, python=py)
            if not ok:
                print(f"FAIL: {message}", file=sys.stderr)
                return 1
            ok, message = assert_console_entrypoint_origin(prefix, repo_root, python=py)
            if not ok:
                print(f"FAIL: {message}", file=sys.stderr)
                return 1
            profile = build_sandbox_profile(extra_writable=(prefix, tree))
            denied, message = deny_network_preflight(profile, python=py)
            if not denied:
                print(f"FAIL: {message}", file=sys.stderr)
                return 1
            ruff = str(Path(py).with_name("ruff"))
            rc, output = run_under_sandbox([ruff, "check", str(tree)], profile, timeout=300)
            if rc != 0:
                print(f"FAIL: materialized ruff: {output[-2000:]}", file=sys.stderr)
                return 1
            site_dir = _site_packages_dir(prefix, py)
            test_env = {
                key: value
                for key, value in os.environ.items()
                if key not in {"PYTHONPATH", "PYTHONHOME"}
            }
            test_env["PYTHONPATH"] = f"{site_dir}{os.pathsep}{tree}"
            neutral = tempfile.mkdtemp(prefix="012-neutral-")
            try:
                rc, output = run_under_sandbox(
                    [py, "-m", "pytest", "-q", "-rx", str(tree / "tests")],
                    profile,
                    timeout=1500,
                    env=test_env,
                    cwd=neutral,
                )
            finally:
                shutil.rmtree(neutral, ignore_errors=True)
            if rc != 0:
                print(f"FAIL: materialized pytest: {output[-4000:]}", file=sys.stderr)
                return 1
            summary = output.strip().splitlines()[-1] if output.strip() else "no output"
            print(f"012 content gate: pytest passed ({summary})")
        finally:
            shutil.rmtree(prefix, ignore_errors=True)
    print("012 content gate: ALL CHECKS PASSED")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check-membership", action="store_true")
    group.add_argument("--content", action="store_true")
    args = parser.parse_args(argv)
    if args.check_membership:
        return check_membership()
    if args.content:
        return run_content_gate()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
