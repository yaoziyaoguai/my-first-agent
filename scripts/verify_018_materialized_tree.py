#!/usr/bin/env python3
"""验证 018 sealed overlay、materialized wheel 与真实 browser attestation。"""

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
    from scripts import run_018_e3 as e3
    from scripts import verify_017_materialized_tree as inherited
    from scripts.verify_materialized_tree import (
        _site_packages_dir,
        assert_console_entrypoint_origin,
        assert_origin,
    )
except ModuleNotFoundError:  # direct ``python scripts/...`` execution
    import run_018_e3 as e3  # type: ignore[no-redef]
    import verify_017_materialized_tree as inherited  # type: ignore[no-redef]
    from verify_materialized_tree import (  # type: ignore[no-redef]
        _site_packages_dir,
        assert_console_entrypoint_origin,
        assert_origin,
    )

REPO = Path(__file__).resolve().parents[1]
BASE_MANIFEST_PATH = REPO / "docs" / "implementation" / "009_DELIVERY_MANIFEST.json"
PARENT_SEAL_PATH = REPO / "docs" / "implementation" / "017_DELIVERY_SEAL.json"
SEAL_PATH = REPO / "docs" / "implementation" / "018_DELIVERY_SEAL.json"
ATTESTATION_PATH = REPO / "docs" / "implementation" / "018_E3_RECEIPT.json"
WHEEL_ARTIFACT_PATH = (
    REPO / "docs" / "acceptance" / "018_GOVERNED_BROWSER_TASKS_WHEEL.json"
)
VERIFIER_PATH = REPO / "scripts" / "verify_018_materialized_tree.py"
RUNNER_PATH = REPO / "scripts" / "run_018_e3.py"
SCHEMA = "my-first-agent/delivery-overlay-seal/v7"
SEAL_KEYS = frozenset({
    "schema",
    "base_manifest_sha256",
    "parent_seal_sha256",
    "verifier_sha256",
    "entry_count",
    "overlay_root_sha256",
})
CONTROL_PATHS = inherited.CONTROL_PATHS | frozenset({
    "docs/implementation/018_DELIVERY_SEAL.json",
    "docs/implementation/018_EXECUTION_LOG.md",
    "scripts/verify_018_materialized_tree.py",
    "docs/implementation/018_E3_RECEIPT.json",
    "docs/acceptance/018_GOVERNED_BROWSER_TASKS_INDEPENDENT_REVIEW.md",
    "docs/acceptance/018_GOVERNED_BROWSER_TASKS_WHEEL.json",
})
DETACHED_MUTABLE_PATHS = frozenset({
    "docs/implementation/018_EXECUTION_LOG.md",
    "docs/implementation/018_E3_RECEIPT.json",
    "docs/acceptance/018_GOVERNED_BROWSER_TASKS_INDEPENDENT_REVIEW.md",
    "docs/acceptance/018_GOVERNED_BROWSER_TASKS_WHEEL.json",
})
SOURCE_DATE_EPOCH = "315532800"


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
        raise ValueError("duplicate path in derived 018 overlay")
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
    except ValueError as error:
        return [], [str(error)]
    if set(seal) != SEAL_KEYS:
        errors.append("018 seal keys must match the strict schema")
    if seal.get("schema") != SCHEMA:
        errors.append(f"seal schema must be {SCHEMA!r}")
    try:
        base_digest = _sha256(repo_root / BASE_MANIFEST_PATH.relative_to(REPO))
        parent_digest = _sha256(repo_root / PARENT_SEAL_PATH.relative_to(REPO))
        verifier_digest = _sha256(repo_root / VERIFIER_PATH.relative_to(REPO))
    except OSError as error:
        return [], [*errors, f"delivery control unavailable: {error}"]
    if seal.get("base_manifest_sha256") != base_digest:
        errors.append("009 base manifest digest drift")
    if seal.get("parent_seal_sha256") != parent_digest:
        errors.append("017 parent seal digest drift")
    if seal.get("verifier_sha256") != verifier_digest:
        errors.append("018 verifier digest drift")
    try:
        entries = derive_overlay(base, repo_root)
    except (OSError, subprocess.CalledProcessError, ValueError) as error:
        return [], [*errors, f"overlay admission failed: {error}"]
    actual_root = overlay_root(base_digest, parent_digest, entries)
    if seal.get("entry_count") != len(entries):
        errors.append(
            f"overlay entry count drift: expected {seal.get('entry_count')}, "
            f"actual {len(entries)}"
        )
    if seal.get("overlay_root_sha256") != actual_root:
        errors.append("018 overlay root digest drift")
    return entries, errors


def _report(errors: list[str]) -> int:
    for error in errors:
        print(f"FAIL: {error}", file=sys.stderr)
    return 1


def check_membership(repo_root: Path = REPO) -> int:
    entries, errors = validate_delivery(repo_root)
    if errors:
        return _report(errors)
    print(f"018 overlay membership ok: {len(entries)} exact entries")
    return 0


def check_control_seal(repo_root: Path = REPO) -> int:
    _entries, errors = validate_delivery(repo_root)
    if errors:
        return _report(errors)
    print("018 control seal ok: 009 manifest + 017 parent + verifier + overlay")
    return 0


def materialize_tree(entries: list[dict], repo_root: Path, destination: Path) -> list[str]:
    with _inherited_controls():
        errors = inherited.materialize_tree(entries, repo_root, destination)
    if errors:
        return errors
    # 上游 materializer 会复制 delivery tests 所需的只读 controls；会在验收后
    # 改写的 receipt、wheel identity、review 与 log 不能进入它们证明的源码树。
    for relative in DETACHED_MUTABLE_PATHS:
        candidate = destination / relative
        if candidate.is_file() or candidate.is_symlink():
            candidate.unlink()
    return []


def _wheel_identity(repo_root: Path = REPO) -> dict:
    artifact = _load_json(repo_root / WHEEL_ARTIFACT_PATH.relative_to(REPO))
    expected = {"wheel_sha256", "materialized_root_sha256", "overlay_root_sha256"}
    if set(artifact) != expected:
        raise ValueError("018 wheel artifact keys must be exact")
    return artifact


def _current_materialized_root(entries: list[dict], repo_root: Path) -> str:
    with tempfile.TemporaryDirectory(prefix="018-attestation-tree-") as tree_name:
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
        available, reason, version, revision, executable_sha = e3._browser_identity()
    except (OSError, ValueError) as error:
        return _report([f"018 E3 attestation unavailable: {error}"])
    errors = e3.validate_receipt(receipt)
    expected = {
        "materialized_root_sha256": materialized_root,
        "seal_sha256": _sha256(repo_root / SEAL_PATH.relative_to(REPO)),
        "verifier_sha256": _sha256(repo_root / VERIFIER_PATH.relative_to(REPO)),
        "runner_sha256": _sha256(repo_root / RUNNER_PATH.relative_to(REPO)),
        "wheel_sha256": wheel.get("wheel_sha256"),
    }
    for key, value in expected.items():
        if receipt.get(key) != value:
            errors.append(f"receipt {key} does not match current delivery identity")
    if wheel.get("materialized_root_sha256") != materialized_root:
        errors.append("wheel artifact binds a different materialized root")
    if wheel.get("overlay_root_sha256") != seal.get("overlay_root_sha256"):
        errors.append("wheel artifact binds a different overlay root")
    if not available:
        errors.append(f"current bundled Chromium is unavailable: {reason}")
    else:
        browser_expected = {
            "playwright_version": version,
            "chromium_revision": revision,
            "chromium_executable_sha256": executable_sha,
        }
        for key, value in browser_expected.items():
            if receipt.get(key) != value:
                errors.append(f"receipt {key} does not match current browser identity")
    if errors:
        return _report(errors)
    print("018 detached E3 attestation ok: 3 real attempts × 13 true journeys")
    return 0


def _clean_environment(home: Path, site_dir: Path, tree: Path) -> dict[str, str]:
    return inherited._clean_test_environment(home, site_dir, tree)


def _install_offline(clean_python: str, *requirements: str) -> tuple[bool, str]:
    uv = shutil.which("uv")
    if uv is None:
        return False, "offline dependency installer unavailable"
    result = subprocess.run(
        [uv, "pip", "install", "--offline", "--python", clean_python, *requirements],
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    return result.returncode == 0, (result.stdout + result.stderr)[-2000:]


def run_content_gate(repo_root: Path = REPO, *, python: str | None = None) -> int:
    """sealed tree → wheel → clean base/browser install → materialized full suite。"""

    py = python or sys.executable
    entries, errors = validate_delivery(repo_root)
    if errors:
        return _report(errors)
    seal = _load_json(repo_root / SEAL_PATH.relative_to(REPO))
    # 安装前缀必须位于 dirty repo 之外，才能真实证明 import 来自 wheel，
    # 而不是因为 prefix 恰好嵌在 workspace 下被 origin guard 误判。
    bundle = Path(tempfile.gettempdir()).resolve() / (
        f"my-first-agent-018-{seal['overlay_root_sha256'][:12]}"
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
    if "include-system-site-packages = false" not in (
        prefix / "pyvenv.cfg"
    ).read_text(encoding="utf-8"):
        return _report(["clean venv inherited system site-packages"])
    clean_python = str(prefix / "bin" / "python")
    wheel, build_error = inherited.build_materialized_wheel(
        tree,
        wheel_dir,
        python=py,
    )
    if wheel is None:
        return _report([f"materialized wheel: {build_error}"])
    wheel_digest = _sha256(wheel)
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
        return _report(["clean base install: " + (installed.stdout + installed.stderr)[-1000:]])
    absent = subprocess.run(
        [
            clean_python,
            "-c",
            (
                "import importlib.util; "
                "assert importlib.util.find_spec('playwright') is None"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if absent.returncode != 0:
        return _report(["base install unexpectedly includes Playwright"])
    ok, detail = _install_offline(clean_python, "httpx>=0.27.1", "playwright==1.62.0")
    if not ok:
        return _report(["offline browser dependency install: " + detail])
    ok, message = assert_origin(prefix, repo_root, python=clean_python)
    if not ok:
        return _report([message])
    ok, message = assert_console_entrypoint_origin(prefix, repo_root, python=clean_python)
    if not ok:
        return _report([message])
    browser_probe = subprocess.run(
        [
            clean_python,
            "-c",
            (
                "import importlib.metadata; "
                "from playwright.sync_api import sync_playwright; "
                "print(importlib.metadata.version('playwright')); "
                "p=sync_playwright().start(); "
                "print(p.chromium.executable_path); p.stop()"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    probe_lines = browser_probe.stdout.strip().splitlines()
    if browser_probe.returncode != 0 or len(probe_lines) != 2:
        return _report(["receipt-bound bundled Chromium is unavailable"])
    clean_version, executable_value = probe_lines
    if clean_version != "1.62.0" or not Path(executable_value).is_file():
        return _report(["clean browser package/binary identity drift"])
    site_dir = _site_packages_dir(prefix, clean_python)
    host_site = _site_packages_dir(Path(sys.prefix), py)
    inherited.attach_verified_test_dependencies(site_dir, host_site)
    # packaging tests may legitimately create build/ metadata. Run them against an
    # exact disposable copy so the receipt-bound materialized source stays immutable.
    test_tree = bundle / "test-tree"
    shutil.copytree(tree, test_tree)
    test_env = _clean_environment(home, site_dir, test_tree)
    test_env["PYTHONPATH"] = os.pathsep.join((str(site_dir), str(test_tree)))
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
        [clean_python, "-m", "pytest", "-q", "-rx", str(test_tree / "tests")],
        cwd=test_tree,
        env=test_env,
        check=False,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    if tests.returncode != 0:
        return _report(["materialized pytest: " + (tests.stdout + tests.stderr)[-5000:]])
    if e3._sha256_tree(tree) != materialized_root:
        return _report(["receipt-bound materialized source mutated during content gate"])
    WHEEL_ARTIFACT_PATH.write_text(
        json.dumps(
            {
                "wheel_sha256": wheel_digest,
                "materialized_root_sha256": materialized_root,
                "overlay_root_sha256": seal["overlay_root_sha256"],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    summary = tests.stdout.strip().splitlines()[-1] if tests.stdout.strip() else "no output"
    print(f"018 content gate passed: {summary}")
    print(f"018 materialized bundle: {bundle}")
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
