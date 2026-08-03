#!/usr/bin/env python3
"""013 closed overlay、交付 seal 与 clean-room content gate。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

try:
    from scripts import verify_012_materialized_tree as inherited
    from scripts.verify_materialized_tree import (
        _site_packages_dir,
        assert_console_entrypoint_origin,
        assert_origin,
        build_sandbox_profile,
        deny_network_preflight,
        install_noneditable,
        run_under_sandbox,
    )
except ModuleNotFoundError:  # direct ``python scripts/...`` execution
    import verify_012_materialized_tree as inherited  # type: ignore[no-redef]
    from verify_materialized_tree import (  # type: ignore[no-redef]
        _site_packages_dir,
        assert_console_entrypoint_origin,
        assert_origin,
        build_sandbox_profile,
        deny_network_preflight,
        install_noneditable,
        run_under_sandbox,
    )

REPO = Path(__file__).resolve().parents[1]
BASE_MANIFEST_PATH = REPO / "docs" / "implementation" / "009_DELIVERY_MANIFEST.json"
PARENT_SEAL_PATH = REPO / "docs" / "implementation" / "012_DELIVERY_SEAL.json"
SEAL_PATH = REPO / "docs" / "implementation" / "013_DELIVERY_SEAL.json"
VERIFIER_PATH = REPO / "scripts" / "verify_013_materialized_tree.py"
SCHEMA = "my-first-agent/delivery-overlay-seal/v2"
SEAL_KEYS = frozenset(
    {
        "schema",
        "base_manifest_sha256",
        "parent_seal_sha256",
        "verifier_sha256",
        "entry_count",
        "overlay_root_sha256",
    }
)

# 012 与 013 的 seal/verifier/log 是交付 control，不进入 ordinary overlay。013 的
# architecture/plan/E3/handoff 与产品代码、测试仍在 overlay 中并受 content root 约束。
CONTROL_PATHS = frozenset(
    {
        "docs/implementation/012_DELIVERY_SEAL.json",
        "docs/implementation/012_EXECUTION_LOG.md",
        "scripts/verify_012_materialized_tree.py",
        "docs/implementation/013_DELIVERY_SEAL.json",
        "docs/implementation/013_EXECUTION_LOG.md",
        "scripts/verify_013_materialized_tree.py",
    }
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON control {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"invalid JSON control {path.name}: object required")
    return value


@contextmanager
def _inherited_controls():
    """只复用 012 已验证的物化算法，不改写已封存的 012 文件。"""

    previous = inherited.CONTROL_PATHS
    inherited.CONTROL_PATHS = CONTROL_PATHS
    try:
        yield
    finally:
        inherited.CONTROL_PATHS = previous


def _exists_no_follow(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def _descriptor(repo_root: Path, relative: str, operation: str) -> dict:
    info, digest = inherited.admit_descriptor(repo_root / relative)
    return {
        "path": relative,
        "operation": operation,
        "git_mode": inherited._git_mode_for_stat(info),
        "sha256": digest,
    }


def _git_paths(repo_root: Path, *arguments: str) -> list[str]:
    result = subprocess.run(
        ["git", *arguments, "-z", "--"],
        cwd=repo_root,
        check=True,
        capture_output=True,
    )
    try:
        return [part.decode("utf-8") for part in result.stdout.split(b"\0") if part]
    except UnicodeDecodeError as exc:
        raise ValueError("Git path is not UTF-8 representable") from exc


def _baseline_has_path(repo_root: Path, baseline: str, relative: str) -> bool:
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{baseline}:{relative}"],
        cwd=repo_root,
        capture_output=True,
    )
    return result.returncode == 0


def derive_overlay(base_manifest: dict, repo_root: Path = REPO) -> list[dict]:
    """对账 009 entries、baseline 后 tracked delta 和显式 untracked admission。"""

    entries = base_manifest.get("entries")
    baseline = base_manifest.get("baseline_commit")
    if not isinstance(entries, list):
        raise ValueError("009 manifest entries must be a list")
    if not isinstance(baseline, str) or len(baseline) != 40:
        raise ValueError("009 baseline_commit must be a full Git SHA")
    base_by_path = {entry["path"]: entry for entry in entries}
    base_controls = {
        item.get("path")
        for item in base_manifest.get("control_files", [])
        if isinstance(item, dict)
    }
    overlay: dict[str, dict] = {}

    for relative, base in base_by_path.items():
        if (
            inherited._is_denied(relative)
            or relative in CONTROL_PATHS
            or relative in base_controls
        ):
            continue
        present = _exists_no_follow(repo_root / relative)
        base_operation = base.get("operation")
        if base_operation == "delete":
            if present:
                overlay[relative] = _descriptor(repo_root, relative, "add")
            continue
        if base_operation not in {"add", "modify"}:
            raise ValueError(f"009 manifest has invalid operation for {relative}")
        if not present:
            overlay[relative] = {"path": relative, "operation": "delete"}
            continue
        current = _descriptor(repo_root, relative, "modify")
        if (
            current["sha256"] != base.get("sha256")
            or current["git_mode"] != base.get("git_mode")
        ):
            overlay[relative] = current

    tracked = _git_paths(repo_root, "diff", "--name-only", "--no-renames", baseline)
    untracked = _git_paths(
        repo_root,
        "ls-files",
        "--others",
        "--exclude-standard",
    )
    for relative in (*tracked, *untracked):
        if (
            relative in base_by_path
            or relative in base_controls
            or relative in CONTROL_PATHS
            or inherited._is_denied(relative)
        ):
            continue
        if not _exists_no_follow(repo_root / relative):
            overlay[relative] = {"path": relative, "operation": "delete"}
            continue
        operation = (
            "modify" if _baseline_has_path(repo_root, baseline, relative) else "add"
        )
        overlay[relative] = _descriptor(repo_root, relative, operation)

    result = sorted(overlay.values(), key=lambda item: item["path"])
    if len({item["path"] for item in result}) != len(result):
        raise ValueError("duplicate path in derived 013 overlay")
    return result


def overlay_root(
    base_manifest_sha256: str,
    parent_seal_sha256: str,
    entries: list[dict],
) -> str:
    payload = {
        "base_manifest_sha256": base_manifest_sha256,
        "parent_seal_sha256": parent_seal_sha256,
        "entries": entries,
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def validate_delivery(repo_root: Path = REPO) -> tuple[list[dict], list[str]]:
    errors: list[str] = []
    try:
        base = _load_json(repo_root / BASE_MANIFEST_PATH.relative_to(REPO))
        seal = _load_json(repo_root / SEAL_PATH.relative_to(REPO))
    except ValueError as exc:
        return [], [str(exc)]
    if set(seal) != SEAL_KEYS:
        errors.append("013 seal keys must match the strict schema")
    if seal.get("schema") != SCHEMA:
        errors.append(f"seal schema must be {SCHEMA!r}")

    try:
        base_digest = _sha256(repo_root / BASE_MANIFEST_PATH.relative_to(REPO))
        parent_digest = _sha256(repo_root / PARENT_SEAL_PATH.relative_to(REPO))
        verifier_digest = _sha256(repo_root / VERIFIER_PATH.relative_to(REPO))
    except OSError as exc:
        return [], [*errors, f"delivery control unavailable: {exc}"]
    if seal.get("base_manifest_sha256") != base_digest:
        errors.append("009 base manifest digest drift")
    if seal.get("parent_seal_sha256") != parent_digest:
        errors.append("012 parent seal digest drift")
    if seal.get("verifier_sha256") != verifier_digest:
        errors.append("013 verifier digest drift")

    try:
        entries = derive_overlay(base, repo_root)
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        return [], [*errors, f"overlay admission failed: {exc}"]
    actual_root = overlay_root(base_digest, parent_digest, entries)
    if seal.get("entry_count") != len(entries):
        errors.append(
            "overlay entry count drift: "
            f"expected {seal.get('entry_count')}, actual {len(entries)}"
        )
    if seal.get("overlay_root_sha256") != actual_root:
        errors.append("013 overlay root digest drift")
    return entries, errors


def _report(errors: list[str]) -> int:
    for error in errors:
        print(f"FAIL: {error}", file=sys.stderr)
    return 1


def check_membership(repo_root: Path = REPO) -> int:
    entries, errors = validate_delivery(repo_root)
    if errors:
        return _report(errors)
    print(f"013 overlay membership ok: {len(entries)} exact entries")
    return 0


def check_control_seal(repo_root: Path = REPO) -> int:
    _entries, errors = validate_delivery(repo_root)
    if errors:
        return _report(errors)
    print("013 control seal ok: 009 manifest + 012 parent + verifier + overlay")
    return 0


def materialize_tree(entries: list[dict], repo_root: Path, dest: Path) -> list[str]:
    with _inherited_controls():
        return inherited.materialize_tree(entries, repo_root, dest)


def run_content_gate(repo_root: Path = REPO, *, python: str | None = None) -> int:
    py = python or sys.executable
    entries, errors = validate_delivery(repo_root)
    if errors:
        return _report(errors)

    with tempfile.TemporaryDirectory(prefix="013-tree-") as tree_name:
        tree = Path(tree_name)
        errors = materialize_tree(entries, repo_root, tree)
        if errors:
            return _report(errors)
        prefix = Path(tempfile.mkdtemp(prefix="013-prefix-"))
        try:
            rc, output = install_noneditable(tree, prefix, python=py)
            if rc != 0:
                return _report([f"non-editable install: {output[-1000:]}"])
            ok, message = assert_origin(prefix, repo_root, python=py)
            if not ok:
                return _report([message])
            ok, message = assert_console_entrypoint_origin(prefix, repo_root, python=py)
            if not ok:
                return _report([message])

            profile = build_sandbox_profile(extra_writable=(prefix, tree))
            denied, message = deny_network_preflight(profile, python=py)
            if not denied:
                return _report([message])
            ruff = str(Path(py).with_name("ruff"))
            rc, output = run_under_sandbox(
                [ruff, "check", str(tree)], profile, timeout=300
            )
            if rc != 0:
                return _report([f"materialized ruff: {output[-2000:]}"])

            site_dir = _site_packages_dir(prefix, py)
            test_env = {
                key: value
                for key, value in os.environ.items()
                if key not in {"PYTHONPATH", "PYTHONHOME"}
                and not key.startswith("FIRST_AGENT_E3_")
            }
            test_env["PYTHONPATH"] = f"{site_dir}{os.pathsep}{tree}"
            neutral = tempfile.mkdtemp(prefix="013-neutral-")
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
                return _report([f"materialized pytest: {output[-4000:]}"])
            summary = output.strip().splitlines()[-1] if output.strip() else "no output"
            print(f"013 content gate: pytest passed ({summary})")
        finally:
            shutil.rmtree(prefix, ignore_errors=True)
    print("013 content gate: ALL CHECKS PASSED")
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
        return check_control_seal()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
