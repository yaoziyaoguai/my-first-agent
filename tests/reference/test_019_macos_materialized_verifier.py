from __future__ import annotations

from scripts import verify_019_macos_materialized_tree as verifier
from scripts import verify_019_materialized_tree as core_verifier


def test_host_controls_are_detached_from_the_portable_core_overlay() -> None:
    assert {
        "docs/acceptance/019_MACOS_PROFILE_SEAL.json",
        "docs/acceptance/019_MACOS_PROFILE_RECEIPT.json",
        "docs/acceptance/019_MACOS_PROFILE_WHEEL.json",
        "docs/acceptance/019_MACOS_PROFILE_INDEPENDENT_REVIEW.md",
        "docs/implementation/019_MACOS_PROFILE_EXECUTION_LOG.md",
        "scripts/verify_019_macos_materialized_tree.py",
    } <= core_verifier.CONTROL_PATHS


def test_host_verifier_temporarily_binds_the_host_identity_only() -> None:
    original = (
        core_verifier.SEAL_PATH,
        core_verifier.PARENT_SEAL_PATH,
        core_verifier.SCHEMA,
    )

    with verifier._host_controls():
        assert core_verifier.SEAL_PATH == verifier.SEAL_PATH
        assert core_verifier.PARENT_SEAL_PATH == verifier.PARENT_SEAL_PATH
        assert core_verifier.SCHEMA == verifier.SCHEMA

    assert original == (
        core_verifier.SEAL_PATH,
        core_verifier.PARENT_SEAL_PATH,
        core_verifier.SCHEMA,
    )


def test_host_receipt_and_review_remain_detached_mutable_controls() -> None:
    assert {
        "docs/acceptance/019_MACOS_PROFILE_RECEIPT.json",
        "docs/acceptance/019_MACOS_PROFILE_WHEEL.json",
        "docs/acceptance/019_MACOS_PROFILE_INDEPENDENT_REVIEW.md",
        "docs/implementation/019_MACOS_PROFILE_EXECUTION_LOG.md",
    } <= verifier.DETACHED_MUTABLE_PATHS
