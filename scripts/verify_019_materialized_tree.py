#!/usr/bin/env python3
"""验证 019 portable overlay、materialized wheel 与 U2A attestation。"""

from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from contextlib import contextmanager
from pathlib import Path

try:
    from scripts import run_019_core_e3 as e3
    from scripts import verify_018_materialized_tree as inherited
    from scripts.verify_materialized_tree import (
        _is_denied,
        _site_packages_dir,
        assert_console_entrypoint_origin,
        assert_origin,
    )
except ModuleNotFoundError:  # direct ``python scripts/...`` execution
    import run_019_core_e3 as e3  # type: ignore[no-redef]
    import verify_018_materialized_tree as inherited  # type: ignore[no-redef]
    from verify_materialized_tree import (  # type: ignore[no-redef]
        _is_denied,
        _site_packages_dir,
        assert_console_entrypoint_origin,
        assert_origin,
    )

REPO = Path(__file__).resolve().parents[1]
BASE_MANIFEST_PATH = REPO / "docs" / "implementation" / "009_DELIVERY_MANIFEST.json"
PARENT_SEAL_PATH = REPO / "docs" / "implementation" / "018_DELIVERY_SEAL.json"
SEAL_PATH = REPO / "docs" / "acceptance" / "019_CORE_SEAL.json"
ATTESTATION_PATH = REPO / "docs" / "acceptance" / "019_CORE_RECEIPT.json"
WHEEL_ARTIFACT_PATH = REPO / "docs" / "acceptance" / "019_CORE_WHEEL.json"
REVIEW_PATH = REPO / "docs" / "acceptance" / "019_CORE_INDEPENDENT_REVIEW.md"
VERIFIER_PATH = REPO / "scripts" / "verify_019_materialized_tree.py"
RUNNER_PATH = REPO / "scripts" / "run_019_core_e3.py"
SCHEMA = "my-first-agent/delivery-overlay-seal/v8"
SEAL_KEYS = frozenset({
    "schema",
    "base_manifest_sha256",
    "parent_seal_sha256",
    "verifier_sha256",
    "entry_count",
    "overlay_root_sha256",
})
CONTROL_PATHS = inherited.CONTROL_PATHS | frozenset({
    "docs/acceptance/019_CORE_SEAL.json",
    "docs/acceptance/019_CORE_RECEIPT.json",
    "docs/acceptance/019_CORE_WHEEL.json",
    "docs/acceptance/019_CORE_INDEPENDENT_REVIEW.md",
    "docs/implementation/019_EXECUTION_LOG.md",
    "scripts/verify_019_materialized_tree.py",
    "docs/acceptance/019_MACOS_PROFILE_SEAL.json",
    "docs/acceptance/019_MACOS_PROFILE_RECEIPT.json",
    "docs/acceptance/019_MACOS_PROFILE_WHEEL.json",
    "docs/acceptance/019_MACOS_PROFILE_INDEPENDENT_REVIEW.md",
    "docs/implementation/019_MACOS_PROFILE_EXECUTION_LOG.md",
    "scripts/verify_019_macos_materialized_tree.py",
})
DETACHED_MUTABLE_PATHS = frozenset({
    "docs/acceptance/019_CORE_RECEIPT.json",
    "docs/acceptance/019_CORE_WHEEL.json",
    "docs/acceptance/019_CORE_INDEPENDENT_REVIEW.md",
    "docs/implementation/019_EXECUTION_LOG.md",
    "docs/acceptance/019_MACOS_PROFILE_RECEIPT.json",
    "docs/acceptance/019_MACOS_PROFILE_WHEEL.json",
    "docs/acceptance/019_MACOS_PROFILE_INDEPENDENT_REVIEW.md",
    "docs/implementation/019_MACOS_PROFILE_EXECUTION_LOG.md",
})
SOURCE_DATE_EPOCH = "315532800"
_BANNED_IMPORT_ROOTS = frozenset({
    "fcntl",
    "playwright",
    "resource",
    "signal",
    "subprocess",
    "winreg",
})
_BANNED_BACKEND_TOKENS = ("launchd", "systemd", "seatbelt", "playwright")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid JSON control {path.name}: {error}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"invalid JSON control {path.name}: object required")
    return payload


@contextmanager
def _inherited_controls():
    previous = inherited.CONTROL_PATHS
    inherited.CONTROL_PATHS = CONTROL_PATHS
    try:
        yield
    finally:
        inherited.CONTROL_PATHS = previous


def derive_overlay(base_manifest: dict, repo_root: Path = REPO) -> list[dict]:
    with _inherited_controls():
        entries = inherited.derive_overlay(base_manifest, repo_root)
    if len({entry["path"] for entry in entries}) != len(entries):
        raise ValueError("duplicate path in derived 019 overlay")
    return entries


def overlay_root(
    base_manifest_sha256: str,
    parent_seal_sha256: str,
    entries: list[dict],
) -> str:
    return inherited.overlay_root(
        base_manifest_sha256,
        parent_seal_sha256,
        entries,
    )


def _delivery_identity(repo_root: Path) -> tuple[dict, list[dict]]:
    base = _load_json(repo_root / BASE_MANIFEST_PATH.relative_to(REPO))
    base_digest = _sha256(repo_root / BASE_MANIFEST_PATH.relative_to(REPO))
    parent_digest = _sha256(repo_root / PARENT_SEAL_PATH.relative_to(REPO))
    verifier_digest = _sha256(repo_root / VERIFIER_PATH.relative_to(REPO))
    entries = derive_overlay(base, repo_root)
    return (
        {
            "schema": SCHEMA,
            "base_manifest_sha256": base_digest,
            "parent_seal_sha256": parent_digest,
            "verifier_sha256": verifier_digest,
            "entry_count": len(entries),
            "overlay_root_sha256": overlay_root(
                base_digest,
                parent_digest,
                entries,
            ),
        },
        entries,
    )


def validate_delivery(repo_root: Path = REPO) -> tuple[list[dict], list[str]]:
    errors: list[str] = []
    try:
        expected, entries = _delivery_identity(repo_root)
        seal = _load_json(repo_root / SEAL_PATH.relative_to(REPO))
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        return [], [f"019 delivery identity unavailable: {error}"]
    if set(seal) != SEAL_KEYS:
        errors.append("019 seal keys must match the strict schema")
    for key, value in expected.items():
        if seal.get(key) != value:
            errors.append(f"019 {key} drift")
    return entries, errors


def _write_json_atomically(path: Path, payload: dict) -> None:
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


def write_seal(repo_root: Path = REPO) -> int:
    try:
        identity, _entries = _delivery_identity(repo_root)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        return _report([f"019 seal unavailable: {error}"])
    _write_json_atomically(repo_root / SEAL_PATH.relative_to(REPO), identity)
    print(
        "019 seal written: "
        f"{identity['entry_count']} entries / {identity['overlay_root_sha256']}"
    )
    return 0


def _report(errors: list[str]) -> int:
    for error in errors:
        print(f"FAIL: {error}", file=sys.stderr)
    return 1


def check_membership(repo_root: Path = REPO) -> int:
    entries, errors = validate_delivery(repo_root)
    if errors:
        return _report(errors)
    print(f"019 overlay membership ok: {len(entries)} exact entries")
    return 0


def check_control_seal(repo_root: Path = REPO) -> int:
    _entries, errors = validate_delivery(repo_root)
    if errors:
        return _report(errors)
    print("019 control seal ok: 009 manifest + 018 parent + verifier + overlay")
    return 0


def materialize_tree(
    entries: list[dict],
    repo_root: Path,
    destination: Path,
) -> list[str]:
    base = _load_json(repo_root / BASE_MANIFEST_PATH.relative_to(REPO))
    baseline = base.get("baseline_commit")
    if not isinstance(baseline, str) or len(baseline) != 40:
        return ["baseline_commit must be a full 40-char Git SHA"]
    archived = subprocess.run(
        ["git", "archive", "--format=tar", baseline],
        cwd=repo_root,
        check=False,
        capture_output=True,
        timeout=120,
    )
    if archived.returncode != 0:
        return ["git archive baseline failed"]
    destination.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    with tarfile.open(fileobj=io.BytesIO(archived.stdout), mode="r:") as archive:
        for member in archive.getmembers():
            relative = member.name.rstrip("/")
            if not relative or _is_denied(relative):
                continue
            if relative.startswith("/") or ".." in Path(relative).parts:
                errors.append(f"unsafe baseline archive path: {relative}")
                continue
            target = destination / relative
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                errors.append(f"unsupported baseline archive member: {relative}")
                continue
            source = archive.extractfile(member)
            if source is None:
                errors.append(f"baseline archive member unreadable: {relative}")
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read())
            target.chmod(0o755 if member.mode & 0o111 else 0o644)
    # ``entries`` 是当前树相对 009 candidate 的 delta，不是相对 Git baseline
    # 的完整清单。先应用 009 manifest 中未被本阶段覆盖的文件，才能在完全
    # 只读 ``.git`` 的前提下恢复父阶段已经验收、但本阶段没有再次修改的源码。
    overlay_paths = {entry["path"] for entry in entries}
    for entry in base.get("entries", []):
        relative = entry.get("path")
        operation = entry.get("operation")
        if (
            not isinstance(relative, str)
            or relative in overlay_paths
            or relative in CONTROL_PATHS
            or _is_denied(relative)
        ):
            continue
        target = destination / relative
        if operation == "delete":
            if target.is_file() or target.is_symlink():
                target.unlink()
            continue
        source = repo_root / relative
        if not source.is_file() or source.is_symlink():
            errors.append(f"009 source unavailable: {relative}")
            continue
        expected_digest = entry.get("sha256")
        if not isinstance(expected_digest, str) or _sha256(source) != expected_digest:
            errors.append(f"009 source digest drift: {relative}")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        target.chmod(0o755 if entry.get("git_mode") == "100755" else 0o644)

    for entry in entries:
        relative = entry["path"]
        target = destination / relative
        if entry["operation"] == "delete":
            if target.is_file() or target.is_symlink():
                target.unlink()
            continue
        source = repo_root / relative
        if not source.is_file() or source.is_symlink():
            errors.append(f"overlay source unavailable: {relative}")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        target.chmod(0o755 if entry["git_mode"] == "100755" else 0o644)
        if _sha256(target) != entry["sha256"]:
            errors.append(f"materialized digest drift: {relative}")
    controls = {
        control.get("path")
        for control in base.get("control_files", [])
        if isinstance(control, dict)
    }
    controls.update(CONTROL_PATHS)
    for relative in controls:
        if (
            not isinstance(relative, str)
            or relative in DETACHED_MUTABLE_PATHS
        ):
            continue
        source = repo_root / relative
        if source.is_file() and not source.is_symlink() and not _is_denied(relative):
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    for relative in DETACHED_MUTABLE_PATHS:
        candidate = destination / relative
        if candidate.is_file() or candidate.is_symlink():
            candidate.unlink()
    return errors


def portable_boundary_errors(tree: Path) -> list[str]:
    errors: list[str] = []
    package = tree / "agent" / "automation"
    for path in sorted(package.rglob("*.py")):
        relative = path.relative_to(tree).as_posix()
        source = path.read_text(encoding="utf-8")
        parsed = ast.parse(source)
        imports = {
            alias.name.split(".", 1)[0]
            for node in ast.walk(parsed)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            (node.module or "").split(".", 1)[0]
            for node in ast.walk(parsed)
            if isinstance(node, ast.ImportFrom)
        }
        for name in sorted(imports & _BANNED_IMPORT_ROOTS):
            errors.append(f"{relative}: concrete backend import {name}")
        folded = source.casefold()
        for token in _BANNED_BACKEND_TOKENS:
            if token in folded:
                errors.append(f"{relative}: concrete backend token {token}")
    return errors


def _wheel_identity(repo_root: Path = REPO) -> dict:
    artifact = _load_json(repo_root / WHEEL_ARTIFACT_PATH.relative_to(REPO))
    expected = {
        "wheel_sha256",
        "materialized_root_sha256",
        "overlay_root_sha256",
        "materialized_full_count",
    }
    if set(artifact) != expected:
        raise ValueError("019 wheel artifact keys must be exact")
    for key in ("wheel_sha256", "materialized_root_sha256", "overlay_root_sha256"):
        if not e3._valid_digest(artifact.get(key)):
            raise ValueError(f"019 wheel artifact {key} must be hex64")
    count = artifact.get("materialized_full_count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise ValueError("019 materialized_full_count must be positive")
    return artifact


def _current_materialized_root(entries: list[dict], repo_root: Path) -> str:
    with tempfile.TemporaryDirectory(prefix="019-attestation-tree-") as tree_name:
        tree = Path(tree_name)
        errors = materialize_tree(entries, repo_root, tree)
        if errors:
            raise ValueError("materialization failed: " + "; ".join(errors))
        return e3._sha256_tree(tree)


def check_attestation(repo_root: Path = REPO) -> int:
    entries, errors = validate_delivery(repo_root)
    if errors:
        return _report(errors)
    try:
        seal = _load_json(repo_root / SEAL_PATH.relative_to(REPO))
        receipt = _load_json(repo_root / ATTESTATION_PATH.relative_to(REPO))
        wheel = _wheel_identity(repo_root)
        materialized_root = _current_materialized_root(entries, repo_root)
        spec_digest, standards_digest = e3._review_section_digests(
            repo_root / REVIEW_PATH.relative_to(REPO)
        )
    except (OSError, ValueError) as error:
        return _report([f"019 U2A attestation unavailable: {error}"])
    errors = e3.validate_receipt(receipt)
    expected = {
        "materialized_root_sha256": materialized_root,
        "seal_sha256": _sha256(repo_root / SEAL_PATH.relative_to(REPO)),
        "verifier_sha256": _sha256(repo_root / VERIFIER_PATH.relative_to(REPO)),
        "runner_sha256": _sha256(repo_root / RUNNER_PATH.relative_to(REPO)),
        "wheel_sha256": wheel["wheel_sha256"],
        "spec_product_review_sha256": spec_digest,
        "standards_architecture_review_sha256": standards_digest,
    }
    for key, value in expected.items():
        if receipt.get(key) != value:
            errors.append(f"receipt {key} does not match current delivery identity")
    if wheel["materialized_root_sha256"] != materialized_root:
        errors.append("wheel artifact binds a different materialized root")
    if wheel["overlay_root_sha256"] != seal.get("overlay_root_sha256"):
        errors.append("wheel artifact binds a different overlay root")
    gate = receipt.get("materialized_full_gate")
    if isinstance(gate, dict) and gate.get("node_count") != wheel["materialized_full_count"]:
        errors.append("receipt materialized full count does not match content gate")
    errors.extend(portable_boundary_errors(repo_root))
    if errors:
        return _report(errors)
    print("019 detached U2A attestation ok: 3 fresh attempts × 13 journeys + 25 claims")
    return 0


def _clean_environment(home: Path, site_dir: Path, tree: Path) -> dict[str, str]:
    return inherited._clean_environment(home, site_dir, tree)


def _passed_count(output: str) -> int:
    import re

    plain = re.sub(r"\x1b\[[0-9;]*m", "", output)
    match = re.search(r"(?:^|\s)(\d+) passed(?:,|\s|$)", plain)
    return 0 if match is None else int(match.group(1))


def _verified_playwright_browsers_root(python: str) -> Path:
    """从已挂载的 Playwright 取得精确 browser bundle root，不继承用户 HOME。"""

    probe = subprocess.run(
        [
            python,
            "-c",
            (
                "from playwright.sync_api import sync_playwright; "
                "p=sync_playwright().start(); "
                "print(p.chromium.executable_path); p.stop()"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    lines = probe.stdout.strip().splitlines()
    if probe.returncode != 0 or len(lines) != 1:
        raise ValueError("verified Playwright browser probe failed")
    executable = Path(lines[0]).resolve(strict=True)
    for candidate in executable.parents:
        family, separator, revision = candidate.name.rpartition("-")
        if (
            separator
            and family in {"chromium", "chromium_headless_shell"}
            and revision.isdigit()
        ):
            return candidate.parent.resolve(strict=True)
    raise ValueError("verified Playwright browser root is not canonical")


def run_content_gate(repo_root: Path = REPO, *, python: str | None = None) -> int:
    py = python or sys.executable
    entries, errors = validate_delivery(repo_root)
    if errors:
        return _report(errors)
    seal = _load_json(repo_root / SEAL_PATH.relative_to(REPO))
    bundle = Path(tempfile.gettempdir()).resolve() / (
        f"my-first-agent-019-{seal['overlay_root_sha256'][:12]}"
    )
    if bundle.exists():
        shutil.rmtree(bundle)
    tree = bundle / "tree"
    wheel_dir = bundle / "wheel"
    prefix = bundle / "venv"
    home = bundle / "home"
    bundle.mkdir(parents=True, mode=0o700)
    home.mkdir(mode=0o700)
    errors = materialize_tree(entries, repo_root, tree)
    errors.extend(portable_boundary_errors(tree))
    if errors:
        return _report(errors)
    materialized_root = e3._sha256_tree(tree)
    created = subprocess.run(
        [py, "-m", "venv", str(prefix)],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if created.returncode != 0:
        return _report(["clean venv: " + (created.stdout + created.stderr)[-1000:]])
    clean_python = str(prefix / "bin" / "python")
    wheel, build_error = inherited.inherited.build_materialized_wheel(
        tree,
        wheel_dir,
        python=py,
    )
    if wheel is None:
        return _report([f"materialized wheel: {build_error}"])
    installed = subprocess.run(
        [
            clean_python,
            "-m",
            "pip",
            "install",
            "--no-index",
            "--no-deps",
            "--force-reinstall",
            str(wheel),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if installed.returncode != 0:
        return _report(["clean install: " + (installed.stdout + installed.stderr)[-1000:]])
    # origin check 会 import ``main``；先挂载已验证依赖，仍由后续检查保证
    # ``main`` / ``agent`` 自身只能来自新安装的 materialized wheel。
    site_dir = _site_packages_dir(prefix, clean_python)
    host_site = _site_packages_dir(Path(sys.prefix), py)
    inherited.inherited.attach_verified_test_dependencies(site_dir, host_site)
    try:
        playwright_browsers_root = _verified_playwright_browsers_root(clean_python)
    except (OSError, ValueError, subprocess.SubprocessError):
        return _report(["materialized browser dependency is unavailable"])
    ok, message = assert_origin(prefix, repo_root, python=clean_python)
    if not ok:
        return _report([message])
    ok, message = assert_console_entrypoint_origin(
        prefix,
        repo_root,
        python=clean_python,
        entrypoints=(
            ("first-agent", "main", "main"),
            ("first-agent-schedule", "agent.automation.cli", "main"),
        ),
    )
    if not ok:
        return _report([message])
    test_tree = bundle / "test-tree"
    shutil.copytree(tree, test_tree)
    test_env = _clean_environment(home, site_dir, test_tree)
    test_env["PYTHONPATH"] = os.pathsep.join((str(site_dir), str(test_tree)))
    test_env["PLAYWRIGHT_BROWSERS_PATH"] = str(playwright_browsers_root)
    ruff = str(Path(py).parent / "ruff")
    ruff_result = subprocess.run(
        [ruff, "check", "--no-cache", str(test_tree)],
        cwd=test_tree,
        env=test_env,
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if ruff_result.returncode != 0:
        return _report(["materialized ruff: " + (ruff_result.stdout + ruff_result.stderr)[-2000:]])
    tests = subprocess.run(
        [
            clean_python,
            "-m",
            "pytest",
            "-q",
            "-rx",
            "--color=no",
            str(test_tree / "tests"),
        ],
        cwd=test_tree,
        env=test_env,
        check=False,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    if tests.returncode != 0:
        return _report(["materialized pytest: " + (tests.stdout + tests.stderr)[-5000:]])
    count = _passed_count(tests.stdout)
    if count < 1:
        return _report(["materialized pytest count is unavailable"])
    if e3._sha256_tree(tree) != materialized_root:
        return _report(["receipt-bound materialized source mutated during content gate"])
    _write_json_atomically(
        repo_root / WHEEL_ARTIFACT_PATH.relative_to(REPO),
        {
            "wheel_sha256": _sha256(wheel),
            "materialized_root_sha256": materialized_root,
            "overlay_root_sha256": seal["overlay_root_sha256"],
            "materialized_full_count": count,
        },
    )
    print(f"019 content gate passed: {count} tests")
    print(f"019 materialized bundle: {bundle}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--seal", action="store_true")
    group.add_argument("--check-membership", action="store_true")
    group.add_argument("--content", action="store_true")
    group.add_argument("--control-seal", action="store_true")
    group.add_argument("--attestation", action="store_true")
    args = parser.parse_args(argv)
    if args.seal:
        return write_seal()
    if args.check_membership:
        return check_membership()
    if args.content:
        return run_content_gate()
    if args.control_seal:
        return check_control_seal()
    if args.attestation:
        return check_attestation()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
