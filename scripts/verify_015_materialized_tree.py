#!/usr/bin/env python3
"""015 closed overlay、014 parent seal 与 clean-room content gate。

本 verifier 只读当前 intended Git tree。ordinary paths 由 009 frozen manifest 与
baseline 后的 tracked/untracked delta 对账，denied/private/runtime paths 在读取或
hash 前拒绝；015 seal、verifier 和 execution log 是 control，不进入 ordinary root。
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
from contextlib import contextmanager
from pathlib import Path

try:
    from scripts import verify_014_materialized_tree as inherited
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
    import verify_014_materialized_tree as inherited  # type: ignore[no-redef]
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
PARENT_SEAL_PATH = REPO / "docs" / "implementation" / "014_DELIVERY_SEAL.json"
SEAL_PATH = REPO / "docs" / "implementation" / "015_DELIVERY_SEAL.json"
ATTESTATION_PATH = (
    REPO / "docs" / "acceptance" / "015_GOVERNED_LOCAL_ACTION_E3_RECEIPTS.json"
)
VERIFIER_PATH = REPO / "scripts" / "verify_015_materialized_tree.py"
SCHEMA = "my-first-agent/delivery-overlay-seal/v4"
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

# 每代 delivery control 都不进入 ordinary overlay。其余 015 设计、验收、handoff、
# 产品源码与测试必须进入 overlay 并由 content root 精确绑定。
CONTROL_PATHS = frozenset(
    {
        "docs/implementation/012_DELIVERY_SEAL.json",
        "docs/implementation/012_EXECUTION_LOG.md",
        "scripts/verify_012_materialized_tree.py",
        "docs/implementation/013_DELIVERY_SEAL.json",
        "docs/implementation/013_EXECUTION_LOG.md",
        "scripts/verify_013_materialized_tree.py",
        "docs/implementation/014_DELIVERY_SEAL.json",
        "docs/implementation/014_EXECUTION_LOG.md",
        "scripts/verify_014_materialized_tree.py",
        "docs/implementation/015_DELIVERY_SEAL.json",
        "docs/implementation/015_EXECUTION_LOG.md",
        "scripts/verify_015_materialized_tree.py",
        # E3 receipt 是对已封存 tree 的 detached attestation；若进入
        # ordinary overlay，写 receipt 会自动改变它所证明的 root。
        "docs/acceptance/015_GOVERNED_LOCAL_ACTION_E3_RECEIPTS.json",
    }
)

ATTESTATION_KEYS = frozenset(
    {
        "contract_version",
        "acceptance_status",
        "provider_family",
        "model",
        "destination_digest",
        "delivery_seal_sha256",
        "fixture_identity_digest",
        "materialized_identity",
        "reviewer_handoff",
        "attempts",
    }
)
ATTEMPT_KEYS = frozenset(
    {
        "attempt_id",
        "started_at",
        "ended_at",
        "journey_verdicts",
        "claims",
        "model_send_count",
        "process_receipt_digest",
        "process_output_digests",
        "artifact_digest",
        "fixture_invocation_count",
    }
)
CLAIM_NAMES = frozenset(
    {
        "production_composition_used",
        "real_model_adapter_used",
        "single_runtime_loop_preserved",
        "kernel_tool_runtime_used",
        "durable_goal_before_process",
        "zero_spawn_before_approval",
        "zero_process_side_effect_before_approval",
        "approval_preview_exact_and_informed",
        "lease_goal_revision_workspace_bound",
        "typed_same_uid_execution_authority_bound",
        "exact_reuse_without_reapproval",
        "changed_command_requires_reapproval",
        "rejected_command_zero_spawn",
        "shell_metacharacters_literal",
        "closed_environment_secret_free",
        "timeout_group_cleanup_confirmed",
        "timeout_not_verified_done",
        "executing_checkpoint_precedes_spawn",
        "restart_zero_duplicate_model_or_process",
        "unknown_recovery_requires_user",
        "process_receipt_kernel_minted",
        "artifact_requires_process_and_readback_evidence",
        "output_bounded_and_untrusted",
        "no_false_sandbox_claim",
        "closed_resource_profile_bound",
        "materialized_source_parity",
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
    """复用 014 已验证的 overlay/materialization，临时扩展 control 集合。"""

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
        raise ValueError("duplicate path in derived 015 overlay")
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
        errors.append("015 seal keys must match the strict schema")
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
        errors.append("014 parent seal digest drift")
    if seal.get("verifier_sha256") != verifier_digest:
        errors.append("015 verifier digest drift")

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
        errors.append("015 overlay root digest drift")
    return entries, errors


def _report(errors: list[str]) -> int:
    for error in errors:
        print(f"FAIL: {error}", file=sys.stderr)
    return 1


def check_membership(repo_root: Path = REPO) -> int:
    entries, errors = validate_delivery(repo_root)
    if errors:
        return _report(errors)
    print(f"015 overlay membership ok: {len(entries)} exact entries")
    return 0


def check_control_seal(repo_root: Path = REPO) -> int:
    _entries, errors = validate_delivery(repo_root)
    if errors:
        return _report(errors)
    print("015 control seal ok: 009 manifest + 014 parent + verifier + overlay")
    return 0


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _attestation_errors(
    receipt: dict,
    *,
    seal: dict,
    seal_digest: str,
    fixture_identity_digest: str,
) -> list[str]:
    """严格验证 detached E3 attestation；不将 receipt 重新混入 tree root。"""

    errors: list[str] = []
    if set(receipt) != ATTESTATION_KEYS:
        errors.append("015 E3 attestation keys must match the strict schema")
    if receipt.get("contract_version") != "015-e3/v1":
        errors.append("015 E3 attestation contract version mismatch")
    if receipt.get("acceptance_status") != "accepted":
        errors.append("015 E3 attestation is not accepted")
    if receipt.get("delivery_seal_sha256") != seal_digest:
        errors.append("015 E3 attestation delivery seal digest drift")
    if receipt.get("fixture_identity_digest") != fixture_identity_digest:
        errors.append("015 E3 attestation fixture identity drift")
    materialized = receipt.get("materialized_identity")
    if not isinstance(materialized, dict):
        errors.append("015 E3 attestation materialized identity is missing")
    else:
        if materialized.get("entry_count") != seal.get("entry_count"):
            errors.append("015 E3 materialized entry count does not match the seal")
        if materialized.get("overlay_root_sha256") != seal.get("overlay_root_sha256"):
            errors.append("015 E3 materialized root does not match the seal")
        if materialized.get("composition_under_install") is not True:
            errors.append("015 E3 did not drive composition from materialized install")
        if not _is_sha256(materialized.get("install_root_digest")):
            errors.append("015 E3 materialized install identity digest is invalid")
    attempts = receipt.get("attempts")
    if not isinstance(attempts, list) or len(attempts) != 3:
        errors.append("015 E3 attestation requires exactly three attempts")
        return errors
    attempt_ids: set[str] = set()
    for index, attempt in enumerate(attempts, start=1):
        if not isinstance(attempt, dict) or set(attempt) != ATTEMPT_KEYS:
            errors.append(f"015 E3 attempt {index} keys must match the strict schema")
            continue
        attempt_id = attempt.get("attempt_id")
        if not isinstance(attempt_id, str) or not attempt_id or attempt_id in attempt_ids:
            errors.append(f"015 E3 attempt {index} identity is missing or duplicated")
        else:
            attempt_ids.add(attempt_id)
        claims = attempt.get("claims")
        if not isinstance(claims, dict) or set(claims) != CLAIM_NAMES:
            errors.append(f"015 E3 attempt {index} claim set is not the frozen 26")
        elif any(value is not True for value in claims.values()):
            errors.append(f"015 E3 attempt {index} contains a non-passing claim")
        if not isinstance(attempt.get("model_send_count"), int) or isinstance(
            attempt.get("model_send_count"), bool
        ):
            errors.append(f"015 E3 attempt {index} model send count is invalid")
        if not isinstance(attempt.get("fixture_invocation_count"), int) or isinstance(
            attempt.get("fixture_invocation_count"), bool
        ):
            errors.append(f"015 E3 attempt {index} fixture invocation count is invalid")
    return errors


def check_attestation(repo_root: Path = REPO) -> int:
    _entries, errors = validate_delivery(repo_root)
    if errors:
        return _report(errors)
    try:
        receipt = _load_json(repo_root / ATTESTATION_PATH.relative_to(REPO))
        seal_path = repo_root / SEAL_PATH.relative_to(REPO)
        seal = _load_json(seal_path)
        seal_digest = _sha256(seal_path)
        # fixture identity 与真实 runner 使用的 closed script bytes 同源。
        import run_015_e3 as e3  # type: ignore[import-not-found]

        fixture_digest = hashlib.sha256(
            json.dumps(e3.FIXTURE_SCRIPTS, sort_keys=True).encode("utf-8")
        ).hexdigest()
    except (OSError, ValueError) as exc:
        return _report([f"015 E3 attestation unavailable: {exc}"])
    errors = _attestation_errors(
        receipt,
        seal=seal,
        seal_digest=seal_digest,
        fixture_identity_digest=fixture_digest,
    )
    if errors:
        return _report(errors)
    print("015 detached E3 attestation ok: current seal + 3 x 26 true claims")
    return 0


def materialize_tree(entries: list[dict], repo_root: Path, dest: Path) -> list[str]:
    with _inherited_controls():
        return inherited.materialize_tree(entries, repo_root, dest)


def _clean_test_environment(home: Path, site_dir: Path, tree: Path) -> dict[str, str]:
    """Materialized suite 不继承 host credential/provider/runtime 配置。"""

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

    with tempfile.TemporaryDirectory(prefix="015-tree-") as tree_name:
        tree = Path(tree_name)
        errors = materialize_tree(entries, repo_root, tree)
        if errors:
            return _report(errors)
        prefix = Path(tempfile.mkdtemp(prefix="015-prefix-"))
        # macOS 的 /var 是 /private/var symlink；产品 state root 正确地拒绝 symlink
        # component，因此 neutral HOME 必须先使用 canonical real path。
        home = Path(tempfile.mkdtemp(prefix="015-home-")).resolve()
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

            profile = build_sandbox_profile(extra_writable=(prefix, tree, home))
            denied, message = deny_network_preflight(profile, python=py)
            if not denied:
                return _report([message])
            site_dir = _site_packages_dir(prefix, py)
            test_env = _clean_test_environment(home, site_dir, tree)
            ruff = str(Path(py).with_name("ruff"))
            rc, output = run_under_sandbox(
                [ruff, "check", str(tree)],
                profile,
                timeout=300,
                env=test_env,
            )
            if rc != 0:
                return _report([f"materialized ruff: {output[-2000:]}"])

            neutral = tempfile.mkdtemp(prefix="015-neutral-")
            try:
                rc, output = run_under_sandbox(
                    [py, "-m", "pytest", "-q", "-rx", "-ra", str(tree / "tests")],
                    profile,
                    timeout=1500,
                    env=test_env,
                    cwd=neutral,
                )
            finally:
                shutil.rmtree(neutral, ignore_errors=True)
            if rc != 0:
                # 醒目输出失败测试 node ID（-ra summary），便于在截断展示下定位
                # （此前 supervisor 仅显示 "1 failed" summary，无法看到测试名）。
                failed = [
                    ln.strip()
                    for ln in output.splitlines()
                    if ln.strip().startswith("FAILED")
                ]
                failed_line = (
                    "015_CONTENT_FAILED_TESTS: "
                    + (" | ".join(failed) if failed else "(no FAILED line; see tail)")
                )
                # failed_line 放最后：supervisor 截断展示只显示最后一行，
                # 放在 pytest tail 之后确保测试名在任何截断下可见。
                return _report(
                    [f"materialized pytest: {output[-4000:]}", failed_line]
                )
            summary = output.strip().splitlines()[-1] if output.strip() else "no output"
            print(f"015 content gate: pytest passed ({summary})")
        finally:
            shutil.rmtree(prefix, ignore_errors=True)
            shutil.rmtree(home, ignore_errors=True)
    print("015 content gate: ALL CHECKS PASSED")
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
