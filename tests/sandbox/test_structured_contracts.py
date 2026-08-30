"""020a structured sandbox 的 immutable 输入/草稿合同。"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from types import SimpleNamespace

import pytest

from agent.sandbox.contracts import (
    STRUCTURED_ARTIFACT_MAX_BYTES,
    STRUCTURED_INPUT_MAX_BYTES,
    STRUCTURED_INPUT_MAX_ITEMS,
    STRUCTURED_OUTPUT_AGGREGATE_MAX_BYTES,
    STRUCTURED_REQUEST_MAX_BYTES,
    STRUCTURED_RESULT_MAX_BYTES,
    SandboxDraftOutcome,
    SandboxEnforcementFactsV1,
    SandboxExecutionDraftV1,
    SandboxMode,
    SandboxNetworkMode,
    StructuredReadbackOutcome,
    StructuredResultKind,
    StructuredSandboxInputV1,
    StructuredSandboxIoPlanV1,
    StructuredSandboxProcessDraftV1,
    structured_invocation_digest,
)

HEX_A = "a" * 64
HEX_B = "b" * 64
HEX_C = "c" * 64


def prepared():  # noqa: ANN201
    return SimpleNamespace(command=SimpleNamespace(command_fingerprint=HEX_A))


def policy():  # noqa: ANN201
    return SimpleNamespace(policy_digest=HEX_B, temp_root="/tmp/structured")


def input_one(
    *,
    slot: str = "source",
    content: bytes = b"pdf",
    allowed_magic_hex: tuple[str, ...] = (),
) -> StructuredSandboxInputV1:
    return StructuredSandboxInputV1(
        slot=slot,
        content=content,
        content_digest=hashlib.sha256(content).hexdigest(),
        allowed_magic_hex=allowed_magic_hex,
    )


def io_plan(**overrides) -> StructuredSandboxIoPlanV1:  # noqa: ANN003
    request = b'{"task":"inspect"}'
    values = {
        "package_digest": HEX_A,
        "entrypoint_id": "inspect",
        "entrypoint_digest": HEX_B,
        "request_bytes": request,
        "request_digest": hashlib.sha256(request).hexdigest(),
        "inputs": (input_one(),),
        "result_cap_bytes": 1024,
        "artifact_cap_bytes": 1024,
        "aggregate_output_cap_bytes": 2048,
        "expected_result_kind": StructuredResultKind.OBSERVATION,
    }
    values.update(overrides)
    return StructuredSandboxIoPlanV1(**values)


def process_draft(outcome: SandboxDraftOutcome = SandboxDraftOutcome.EXITED):
    return SandboxExecutionDraftV1(
        outcome=outcome,
        exit_code=0 if outcome is SandboxDraftOutcome.EXITED else None,
        signal=None,
        duration_seconds=0.1,
        stdout_bytes=0,
        stderr_bytes=0,
        stdout_digest=HEX_A,
        stderr_digest=HEX_B,
        stdout_projection="",
        stderr_projection="",
        stdout_truncated=False,
        stderr_truncated=False,
        original_command_fingerprint=HEX_A,
        enforcement=SandboxEnforcementFactsV1(
            backend="seatbelt",
            enforcement="confined",
            mode=SandboxMode.WORKSPACE_WRITE,
            network=SandboxNetworkMode.OFF,
            policy_digest=HEX_B,
            profile_digest=HEX_C,
        ),
    )


def structured_draft(
    process_outcome: SandboxDraftOutcome,
    readback_outcome: StructuredReadbackOutcome,
) -> StructuredSandboxProcessDraftV1:
    result = b"{}" if readback_outcome is StructuredReadbackOutcome.VALID else b""
    return StructuredSandboxProcessDraftV1(
        process=process_draft(process_outcome),
        structured_invocation_digest=HEX_A,
        readback_outcome=readback_outcome,
        request_digest=HEX_B,
        input_digests=(("source", 3, HEX_C),),
        result_bytes=result,
        result_digest=hashlib.sha256(result).hexdigest(),
        artifact_bytes=None,
        artifact_digest=None,
    )


def test_outer_digest_excludes_random_session_and_binds_every_authority_input():
    plan = io_plan()
    first = structured_invocation_digest(prepared(), policy(), plan)
    assert first == structured_invocation_digest(prepared(), policy(), plan)
    changed_request = b"{}"
    request_changed = replace(
        plan,
        request_bytes=changed_request,
        request_digest=hashlib.sha256(changed_request).hexdigest(),
    )
    assert first != structured_invocation_digest(prepared(), policy(), request_changed)
    assert first != structured_invocation_digest(
        prepared(), policy(), replace(plan, entrypoint_digest="f" * 64)
    )
    changed_magic = replace(
        plan,
        inputs=(replace(plan.inputs[0], allowed_magic_hex=("504b0304",)), *plan.inputs[1:]),
    )
    assert first != structured_invocation_digest(prepared(), policy(), changed_magic)


def test_io_plan_rejects_digest_drift_duplicate_slots_and_open_result_kind():
    with pytest.raises(ValueError, match="digest"):
        StructuredSandboxInputV1("source", b"pdf", "0" * 64)
    with pytest.raises(ValueError, match="unique"):
        replace(io_plan(), inputs=(input_one(), input_one()))
    with pytest.raises(TypeError, match="closed"):
        replace(io_plan(), expected_result_kind="future-kind")


@pytest.mark.parametrize(
    "mutation",
    [
        lambda plan: replace(
            plan,
            request_bytes=b"x" * (STRUCTURED_REQUEST_MAX_BYTES + 1),
            request_digest=hashlib.sha256(
                b"x" * (STRUCTURED_REQUEST_MAX_BYTES + 1)
            ).hexdigest(),
        ),
        lambda plan: replace(
            plan,
            inputs=tuple(
                input_one(slot=f"slot_{index}")
                for index in range(STRUCTURED_INPUT_MAX_ITEMS + 1)
            ),
        ),
        lambda plan: replace(
            plan,
            inputs=(input_one(content=b"x" * (STRUCTURED_INPUT_MAX_BYTES + 1)),),
        ),
        lambda plan: replace(plan, result_cap_bytes=STRUCTURED_RESULT_MAX_BYTES + 1),
        lambda plan: replace(plan, artifact_cap_bytes=STRUCTURED_ARTIFACT_MAX_BYTES + 1),
        lambda plan: replace(
            plan,
            aggregate_output_cap_bytes=STRUCTURED_OUTPUT_AGGREGATE_MAX_BYTES + 1,
        ),
    ],
)
def test_io_plan_rejects_every_product_maximum_overrun(mutation):  # noqa: ANN001
    with pytest.raises(ValueError, match="maximum|aggregate"):
        mutation(io_plan())


def test_magic_allowlist_is_sorted_unique_and_bounded():
    item = input_one(allowed_magic_hex=("89504e47", "25504446", "89504e47"))
    assert item.allowed_magic_hex == ("25504446", "89504e47")
    with pytest.raises(ValueError, match="magic"):
        input_one(allowed_magic_hex=tuple(f"{index:02x}" for index in range(17)))


def test_process_command_fingerprint_is_unchanged_by_io_plan():
    invocation = prepared()
    before = invocation.command.command_fingerprint
    structured_invocation_digest(invocation, policy(), io_plan())
    assert invocation.command.command_fingerprint == before


@pytest.mark.parametrize(
    ("process_outcome", "readback_outcome"),
    [
        (SandboxDraftOutcome.SPAWN_FAILED, StructuredReadbackOutcome.RESULT_MISSING),
        (SandboxDraftOutcome.EXITED, StructuredReadbackOutcome.NOT_READ),
    ],
)
def test_spawn_failed_is_equivalent_to_not_read(process_outcome, readback_outcome):
    with pytest.raises(ValueError, match="occur together"):
        structured_draft(process_outcome, readback_outcome)
