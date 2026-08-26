#!/usr/bin/env python3
"""验证 016 overlay、015 parent seal 与 clean-room installed content。"""

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
    from scripts import verify_015_materialized_tree as inherited
    from scripts.verify_materialized_tree import (
        _site_packages_dir,
        assert_console_entrypoint_origin,
        assert_origin,
        build_sandbox_profile,
        deny_network_preflight,
        run_under_sandbox,
    )
except ModuleNotFoundError:  # direct ``python scripts/...`` execution
    import verify_015_materialized_tree as inherited  # type: ignore[no-redef]
    from verify_materialized_tree import (  # type: ignore[no-redef]
        _site_packages_dir,
        assert_console_entrypoint_origin,
        assert_origin,
        build_sandbox_profile,
        deny_network_preflight,
        run_under_sandbox,
    )

REPO = Path(__file__).resolve().parents[1]
BASE_MANIFEST_PATH = REPO / "docs" / "implementation" / "009_DELIVERY_MANIFEST.json"
PARENT_SEAL_PATH = REPO / "docs" / "implementation" / "015_DELIVERY_SEAL.json"
SEAL_PATH = REPO / "docs" / "implementation" / "016_DELIVERY_SEAL.json"
ATTESTATION_PATH = REPO / "docs" / "acceptance" / "016_FIRST_AGENT_1_0_E3_RECEIPTS.json"
VERIFIER_PATH = REPO / "scripts" / "verify_016_materialized_tree.py"
SCHEMA = "my-first-agent/delivery-overlay-seal/v5"
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

# delivery controls 与真实 E3 receipt 是 detached evidence，不混入它们证明的 ordinary root。
CONTROL_PATHS = inherited.CONTROL_PATHS | frozenset(
    {
        "docs/implementation/016_DELIVERY_SEAL.json",
        "docs/implementation/016_EXECUTION_LOG.md",
        "scripts/verify_016_materialized_tree.py",
        "docs/acceptance/016_FIRST_AGENT_1_0_E3_RECEIPTS.json",
        "docs/acceptance/016_FIRST_AGENT_1_0_INDEPENDENT_REVIEW.md",
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
        raise ValueError("duplicate path in derived 016 overlay")
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


def validate_delivery(repo_root: Path = REPO) -> tuple[list[dict], list[str]]:
    errors: list[str] = []
    try:
        base = _load_json(repo_root / BASE_MANIFEST_PATH.relative_to(REPO))
        seal = _load_json(repo_root / SEAL_PATH.relative_to(REPO))
    except ValueError as exc:
        return [], [str(exc)]
    if set(seal) != SEAL_KEYS:
        errors.append("016 seal keys must match the strict schema")
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
        errors.append("015 parent seal digest drift")
    if seal.get("verifier_sha256") != verifier_digest:
        errors.append("016 verifier digest drift")
    try:
        entries = derive_overlay(base, repo_root)
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        return [], [*errors, f"overlay admission failed: {exc}"]
    actual_root = overlay_root(base_digest, parent_digest, entries)
    if seal.get("entry_count") != len(entries):
        errors.append(
            f"overlay entry count drift: expected {seal.get('entry_count')}, actual {len(entries)}"
        )
    if seal.get("overlay_root_sha256") != actual_root:
        errors.append("016 overlay root digest drift")
    return entries, errors


def _report(errors: list[str]) -> int:
    for error in errors:
        print(f"FAIL: {error}", file=sys.stderr)
    return 1


def check_membership(repo_root: Path = REPO) -> int:
    entries, errors = validate_delivery(repo_root)
    if errors:
        return _report(errors)
    print(f"016 overlay membership ok: {len(entries)} exact entries")
    return 0


def check_control_seal(repo_root: Path = REPO) -> int:
    _entries, errors = validate_delivery(repo_root)
    if errors:
        return _report(errors)
    print("016 control seal ok: 009 manifest + 015 parent + verifier + overlay")
    return 0


def check_attestation(repo_root: Path = REPO) -> int:
    _entries, errors = validate_delivery(repo_root)
    if errors:
        return _report(errors)
    try:
        receipt = _load_json(repo_root / ATTESTATION_PATH.relative_to(REPO))
        import run_016_e3 as e3  # type: ignore[import-not-found]
    except (OSError, ValueError) as exc:
        return _report([f"016 E3 attestation unavailable: {exc}"])
    try:
        current_identity = e3.delivery_identity(repo_root)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _report([f"016 delivery identity unavailable: {exc}"])
    errors = e3.receipt_errors(
        receipt,
        expected_delivery_identity=current_identity,
    )
    if errors:
        return _report(errors)
    print("016 detached E3 attestation ok: 3 x 12 journeys + 25 true claims")
    return 0


def materialize_tree(entries: list[dict], repo_root: Path, dest: Path) -> list[str]:
    with _inherited_controls():
        return inherited.materialize_tree(entries, repo_root, dest)


def _clean_test_environment(home: Path, site_dir: Path, tree: Path) -> dict[str, str]:
    env = {
        "HOME": str(home),
        "PATH": os.environ.get("PATH", ""),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": f"{site_dir}{os.pathsep}{tree}",
    }
    for name in ("LANG", "LC_ALL", "TMPDIR"):
        value = os.environ.get(name)
        if value:
            env[name] = value
    return env


def run_content_gate(repo_root: Path = REPO, *, python: str | None = None) -> int:
    py = python or sys.executable
    entries, errors = validate_delivery(repo_root)
    if errors:
        return _report(errors)
    with tempfile.TemporaryDirectory(prefix="016-tree-") as tree_name:
        tree = Path(tree_name)
        errors = materialize_tree(entries, repo_root, tree)
        if errors:
            return _report(errors)
        prefix = Path(tempfile.mkdtemp(prefix="016-prefix-"))
        home = Path(tempfile.mkdtemp(prefix="016-home-")).resolve()
        try:
            created = subprocess.run(
                [py, "-m", "venv", str(prefix)],
                check=False,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if created.returncode != 0:
                return _report([f"clean venv: {(created.stdout + created.stderr)[-1000:]}"])
            configuration = (prefix / "pyvenv.cfg").read_text(encoding="utf-8")
            if "include-system-site-packages = false" not in configuration:
                return _report(["clean venv inherited system site-packages"])
            clean_python = str(prefix / "bin" / "python")
            built = subprocess.run(
                [
                    py,
                    "-m",
                    "pip",
                    "wheel",
                    "--no-deps",
                    "--wheel-dir",
                    "dist",
                    ".",
                ],
                cwd=tree,
                check=False,
                capture_output=True,
                text=True,
                timeout=180,
            )
            if built.returncode != 0:
                return _report([f"materialized wheel: {(built.stdout + built.stderr)[-1000:]}"])
            wheel = next((tree / "dist").glob("first_agent-1.0.0-*.whl"), None)
            if wheel is None:
                return _report(["materialized wheel was not produced"])
            installed = subprocess.run(
                [clean_python, "-m", "pip", "install", "--force-reinstall", str(wheel)],
                check=False,
                capture_output=True,
                text=True,
                timeout=180,
            )
            if installed.returncode != 0:
                return _report(
                    [f"clean base install: {(installed.stdout + installed.stderr)[-1000:]}"]
                )
            optional_probe = subprocess.run(
                [
                    clean_python,
                    "-c",
                    (
                        "import importlib.util; "
                        "assert all(importlib.util.find_spec(name) is None "
                        "for name in ('yaml', 'mcp', 'textual'))"
                    ),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if optional_probe.returncode != 0:
                return _report(["base install pulled optional product dependencies"])
            test_dependencies = subprocess.run(
                [
                    clean_python,
                    "-m",
                    "pip",
                    "install",
                    "--force-reinstall",
                    f"first-agent[dev,skill,mcp,tui] @ {wheel.as_uri()}",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=300,
            )
            if test_dependencies.returncode != 0:
                return _report(
                    [
                        "clean test dependency install: "
                        + (test_dependencies.stdout + test_dependencies.stderr)[-1000:]
                    ]
                )
            ok, message = assert_origin(prefix, repo_root, python=clean_python)
            if not ok:
                return _report([message])
            ok, message = assert_console_entrypoint_origin(
                prefix,
                repo_root,
                python=clean_python,
            )
            if not ok:
                return _report([message])
            profile = build_sandbox_profile(extra_writable=(prefix, tree, home))
            denied, message = deny_network_preflight(profile, python=clean_python)
            if not denied:
                return _report([message])
            site_dir = _site_packages_dir(prefix, clean_python)
            test_env = _clean_test_environment(home, site_dir, tree)
            ruff = str(prefix / "bin" / "ruff")
            rc, output = run_under_sandbox(
                [ruff, "check", str(tree)],
                profile,
                timeout=300,
                env=test_env,
            )
            if rc != 0:
                return _report([f"materialized ruff: {output[-2000:]}"])
            neutral = Path(tempfile.mkdtemp(prefix="016-neutral-"))
            try:
                rc, output = run_under_sandbox(
                    [
                        clean_python,
                        "-m",
                        "pytest",
                        "-q",
                        "-rx",
                        "-ra",
                        str(tree / "tests"),
                    ],
                    profile,
                    timeout=1800,
                    env=test_env,
                    cwd=neutral,
                )
            finally:
                shutil.rmtree(neutral, ignore_errors=True)
            if rc != 0:
                failed = [
                    line.strip()
                    for line in output.splitlines()
                    if line.strip().startswith("FAILED")
                ]
                return _report(
                    [
                        f"materialized pytest: {output[-4000:]}",
                        "016_CONTENT_FAILED_TESTS: "
                        + (" | ".join(failed) if failed else "(no FAILED line; see tail)"),
                    ]
                )
            summary = output.strip().splitlines()[-1] if output.strip() else "no output"
            print(f"016 content gate: pytest passed ({summary})")
        finally:
            shutil.rmtree(prefix, ignore_errors=True)
            shutil.rmtree(home, ignore_errors=True)
    print("016 content gate: ALL CHECKS PASSED")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check-membership", action="store_true")
    group.add_argument("--content", action="store_true")
    group.add_argument("--control-seal", action="store_true")
    group.add_argument("--attestation", action="store_true")
    args = parser.parse_args(argv)
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
