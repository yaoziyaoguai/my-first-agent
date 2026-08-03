from __future__ import annotations

from pathlib import Path

import pytest

from agent.mcp.safety import (
    LatchBinding,
    McpSafetyLatch,
    SafetyLatchError,
)


def _binding(server_id: str = "repo", intent: str = "intent-1") -> LatchBinding:
    return LatchBinding(
        server_id=server_id,
        config_digest="config-digest",
        credential_profile="ops-profile",
        safety_generation="gen-1",
        intent_digest=intent,
    )


def _latch_path(tmp_path: Path) -> Path:
    directory = tmp_path / "mcp-safety"
    directory.mkdir(mode=0o700)
    return directory / "latch.json"


def test_clear_latch_arms_with_full_binding(tmp_path: Path) -> None:
    latch = McpSafetyLatch(_latch_path(tmp_path))

    assert latch.status() == "clear"
    token = latch.arm(expected_clear_revision=0, binding=_binding())

    assert latch.status() == "armed"
    assert token
    state = latch.snapshot()
    assert state is not None
    assert state.revision == 1
    assert state.token == token


def test_arming_an_already_armed_latch_fails_closed(tmp_path: Path) -> None:
    latch = McpSafetyLatch(_latch_path(tmp_path))
    latch.arm(expected_clear_revision=0, binding=_binding())

    with pytest.raises(SafetyLatchError):
        latch.arm(expected_clear_revision=0, binding=_binding(intent="intent-2"))


def test_clear_requires_exact_revision_token_and_binding(tmp_path: Path) -> None:
    latch = McpSafetyLatch(_latch_path(tmp_path))
    token = latch.arm(expected_clear_revision=0, binding=_binding())

    assert latch.clear(revision=1, token="wrong", binding=_binding()) is False
    assert latch.clear(revision=99, token=token, binding=_binding()) is False
    assert latch.clear(revision=1, token=token, binding=_binding(intent="other")) is False
    assert latch.status() == "armed"

    assert latch.clear(revision=1, token=token, binding=_binding()) is True
    assert latch.status() == "clear"


def test_unresolved_armed_marker_blocks_startup(tmp_path: Path) -> None:
    path = _latch_path(tmp_path)
    latch = McpSafetyLatch(path)
    latch.arm(expected_clear_revision=0, binding=_binding())

    reopened = McpSafetyLatch(path)
    assert reopened.status() == "armed"
    with pytest.raises(SafetyLatchError):
        reopened.require_clear_for_composition()


def test_latch_file_is_owner_only(tmp_path: Path) -> None:
    path = _latch_path(tmp_path)
    McpSafetyLatch(path).arm(expected_clear_revision=0, binding=_binding())
    mode = path.stat().st_mode & 0o777
    assert mode == 0o600
    assert (path.parent.stat().st_mode & 0o777) == 0o700


def test_recovery_clear_requires_exact_binding_process_and_rotation_attestations(
    tmp_path: Path,
) -> None:
    """A6: operator-only recovery clear requires exact CAS + affirmative process-termination
    attestation; credential-bearing markers also require rotation attestation."""
    path = _latch_path(tmp_path)
    latch = McpSafetyLatch(path)
    token = latch.arm(expected_clear_revision=0, binding=_binding())

    # 缺少 process attestation → fail
    assert (
        latch.force_clear(
            revision=1,
            token=token,
            binding=_binding(),
            process_terminated=False,
        )
        is False
    )
    # wrong token → fail
    assert (
        latch.force_clear(
            revision=1,
            token="wrong",
            binding=_binding(),
            process_terminated=True,
        )
        is False
    )
    assert latch.status() == "armed"

    # exact + affirmative → clear
    assert (
        latch.force_clear(
            revision=1,
            token=token,
            binding=_binding(),
            process_terminated=True,
            credential_rotated=True,
        )
        is True
    )
    assert latch.status() == "clear"


def test_force_clear_credential_bearing_defaults_to_negative_rotation(tmp_path: Path) -> None:
    """A6/design (MCP_DESIGN.md:226): force_clear 的 credential-rotation attestation 默认否定。
    对 credential-bearing marker，operator 必须显式 attest rotation 才能清除；遗漏该参数不能
    默认放行（否则一次粗心的 recovery 会以虚假 rotation attestation 清除 latch）。"""
    path = _latch_path(tmp_path)
    latch = McpSafetyLatch(path)
    binding = _binding()  # credential_profile="ops-profile"
    token = latch.arm(expected_clear_revision=0, binding=binding)

    cleared = latch.force_clear(
        revision=1,
        token=token,
        binding=binding,
        process_terminated=True,
        # credential_rotated intentionally omitted → must default to negative
    )

    assert cleared is False
    assert latch.status() == "armed"
