#!/usr/bin/env python3
"""验证 019 optional macOS host profile 的 sealed/materialized/U2B identity。"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from contextlib import contextmanager
from pathlib import Path

try:
    from scripts import run_019_macos_e3 as e3
    from scripts import verify_019_materialized_tree as inherited
except ModuleNotFoundError:  # direct ``python scripts/...`` execution
    import run_019_macos_e3 as e3  # type: ignore[no-redef]
    import verify_019_materialized_tree as inherited  # type: ignore[no-redef]

REPO = Path(__file__).resolve().parents[1]
BASE_MANIFEST_PATH = REPO / "docs" / "implementation" / "009_DELIVERY_MANIFEST.json"
PARENT_SEAL_PATH = REPO / "docs" / "acceptance" / "019_CORE_SEAL.json"
SEAL_PATH = REPO / "docs" / "acceptance" / "019_MACOS_PROFILE_SEAL.json"
ATTESTATION_PATH = REPO / "docs" / "acceptance" / "019_MACOS_PROFILE_RECEIPT.json"
WHEEL_ARTIFACT_PATH = REPO / "docs" / "acceptance" / "019_MACOS_PROFILE_WHEEL.json"
REVIEW_PATH = REPO / "docs" / "acceptance" / "019_MACOS_PROFILE_INDEPENDENT_REVIEW.md"
VERIFIER_PATH = REPO / "scripts" / "verify_019_macos_materialized_tree.py"
RUNNER_PATH = REPO / "scripts" / "run_019_macos_e3.py"
SCHEMA = "my-first-agent/delivery-overlay-seal/v9"
CONTROL_PATHS = inherited.CONTROL_PATHS
DETACHED_MUTABLE_PATHS = inherited.DETACHED_MUTABLE_PATHS


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid JSON control {path.name}: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"invalid JSON control {path.name}: object required")
    return value


@contextmanager
def _host_controls():
    replacements = {
        "PARENT_SEAL_PATH": PARENT_SEAL_PATH,
        "SEAL_PATH": SEAL_PATH,
        "ATTESTATION_PATH": ATTESTATION_PATH,
        "WHEEL_ARTIFACT_PATH": WHEEL_ARTIFACT_PATH,
        "REVIEW_PATH": REVIEW_PATH,
        "VERIFIER_PATH": VERIFIER_PATH,
        "RUNNER_PATH": RUNNER_PATH,
        "SCHEMA": SCHEMA,
        "CONTROL_PATHS": CONTROL_PATHS,
        "DETACHED_MUTABLE_PATHS": DETACHED_MUTABLE_PATHS,
    }
    previous = {name: getattr(inherited, name) for name in replacements}
    for name, value in replacements.items():
        setattr(inherited, name, value)
    try:
        yield
    finally:
        for name, value in previous.items():
            setattr(inherited, name, value)


def write_seal(repo_root: Path = REPO) -> int:
    with _host_controls():
        return inherited.write_seal(repo_root)


def check_membership(repo_root: Path = REPO) -> int:
    with _host_controls():
        return inherited.check_membership(repo_root)


def check_control_seal(repo_root: Path = REPO) -> int:
    with _host_controls():
        return inherited.check_control_seal(repo_root)


def run_content_gate(repo_root: Path = REPO) -> int:
    with _host_controls():
        return inherited.run_content_gate(repo_root)


def check_attestation(repo_root: Path = REPO) -> int:
    with _host_controls():
        entries, errors = inherited.validate_delivery(repo_root)
        if errors:
            return _report(errors)
        try:
            receipt = _load_json(repo_root / ATTESTATION_PATH.relative_to(REPO))
            seal = _load_json(repo_root / SEAL_PATH.relative_to(REPO))
            wheel = inherited._wheel_identity(repo_root)
            materialized_root = inherited._current_materialized_root(entries, repo_root)
            spec_digest, standards_digest = e3._review_section_digests(
                repo_root / REVIEW_PATH.relative_to(REPO)
            )
        except (OSError, ValueError) as error:
            return _report([f"019 U2B attestation unavailable: {error}"])
        errors = e3.validate_u2b_receipt(receipt)
        expected = {
            "materialized_root_sha256": materialized_root,
            "seal_sha256": _sha256(repo_root / SEAL_PATH.relative_to(REPO)),
            "verifier_sha256": _sha256(repo_root / VERIFIER_PATH.relative_to(REPO)),
            "runner_sha256": _sha256(repo_root / RUNNER_PATH.relative_to(REPO)),
            "wheel_sha256": wheel.get("wheel_sha256"),
            "spec_product_review_sha256": spec_digest,
            "standards_architecture_review_sha256": standards_digest,
        }
        for key, expected_value in expected.items():
            if receipt.get(key) != expected_value:
                errors.append(f"receipt {key} does not match current delivery identity")
        if wheel.get("materialized_root_sha256") != materialized_root:
            errors.append("wheel artifact binds a different materialized root")
        if wheel.get("overlay_root_sha256") != seal.get("overlay_root_sha256"):
            errors.append("wheel artifact binds a different overlay root")
        gate = receipt.get("materialized_full_gate")
        if isinstance(gate, dict) and gate.get("node_count") != wheel.get(
            "materialized_full_count"
        ):
            errors.append("receipt materialized full count does not match content gate")
        if platform.system() != "Darwin":
            errors.append("current attestation host is not macOS")
        elif not e3._launchd_domain_available():
            errors.append("current launchd user domain is unavailable")
        elif not e3._seatbelt_available():
            errors.append("current Seatbelt backend is unavailable")
        elif not e3._browser_runtime_available():
            errors.append("current Playwright/Chromium runtime is unavailable")
        if errors:
            return _report(errors)
        print("019 macOS U2B attestation ok: 3 real wakes + qualified host cleanup")
        return 0


def _report(errors: list[str]) -> int:
    for error in errors:
        print(f"FAIL: {error}", file=sys.stderr)
    return 1


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
