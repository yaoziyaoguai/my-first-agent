"""声明式 Skill entrypoint 的 governed tool 行为。"""

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.composition import build_skill_execution_config, build_tool_registrations
from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    ApprovalPolicy,
    BlockedClaim,
    EgressClass,
    ExecutionAuthorityClass,
    ModelResponse,
    ModelToolCall,
    ResolveApproval,
    RunStatus,
    SandboxAuthorityLeaseV1,
    SideEffectClass,
    SubmitMessage,
    ToolCall,
    ToolPrepareContext,
    ToolRisk,
    canonical_json_digest,
)
from agent.runtime.loop import AgentRuntime, InvocationLimits
from agent.runtime.tools import ApprovalRequired, KernelToolRuntime
from agent.sandbox.contracts import (
    SandboxDraftOutcome,
    SandboxEnforcementFactsV1,
    SandboxExecutionDraftV1,
    SandboxMode,
    SandboxNetworkMode,
    StructuredReadbackOutcome,
    StructuredSandboxProcessDraftV1,
    structured_invocation_digest,
)
from agent.sandbox.executor import NativeSandboxExecutor
from agent.sandbox.hermetic_runtime import HermeticRuntimeClosureV1
from agent.skill.catalog import build_skill_catalog
from agent.skill.execution import SkillExecutionConfig
from agent.skill.tools import build_skill_tool_registrations
from tests.kernel.fakes import (
    RUNTIME_GOAL_ID,
    CollectingSink,
    RecordingCheckpointStore,
    ScriptedProvider,
    conversation_with_active_goal,
    goal_noop_response,
)
from tests.sandbox.test_hermetic_runtime import _make_runtime

NOW = "2026-09-04T08:00:00+00:00"


class RecordingExecutor:
    def __init__(self) -> None:
        self.calls = []

    def execute(self, prepared, policy, io_plan=None):  # noqa: ANN001, ANN202
        self.calls.append((prepared, policy, io_plan))
        result = json.dumps(
            {
                "kind": "observation",
                "payload": {"words": 2},
                "protocol": "first-agent-skill-result-v1",
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        process = SandboxExecutionDraftV1(
            outcome=SandboxDraftOutcome.EXITED,
            exit_code=0,
            signal=None,
            duration_seconds=0.01,
            stdout_bytes=0,
            stderr_bytes=0,
            stdout_digest=hashlib.sha256(b"").hexdigest(),
            stderr_digest=hashlib.sha256(b"").hexdigest(),
            stdout_projection="",
            stderr_projection="",
            stdout_truncated=False,
            stderr_truncated=False,
            original_command_fingerprint=prepared.command.command_fingerprint,
            enforcement=SandboxEnforcementFactsV1(
                backend="seatbelt",
                enforcement="confined",
                mode=SandboxMode.READ_ONLY,
                network=SandboxNetworkMode.OFF,
                policy_digest=policy.policy_digest,
                profile_digest="d" * 64,
            ),
        )
        return StructuredSandboxProcessDraftV1(
            process=process,
            structured_invocation_digest=structured_invocation_digest(
                prepared, policy, io_plan
            ),
            readback_outcome=StructuredReadbackOutcome.VALID,
            request_digest=io_plan.request_digest,
            input_digests=(),
            result_bytes=result,
            result_digest=hashlib.sha256(result).hexdigest(),
            artifact_bytes=None,
            artifact_digest=None,
        )


def _catalog_with_entrypoint(tmp_path: Path):  # noqa: ANN202
    root = tmp_path / "skills"
    skill = root / "text-stats"
    scripts = skill / "scripts"
    scripts.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\n"
        "name: text-stats\n"
        "description: Count text statistics.\n"
        "entrypoints:\n"
        "  - id: analyze\n"
        "    script: scripts/analyze.py\n"
        "---\n"
        "Use the analyze entrypoint.\n",
        encoding="utf-8",
    )
    (scripts / "analyze.py").write_text(
        "def run(arguments, inputs):\n    return None\n",
        encoding="utf-8",
    )
    return build_skill_catalog([root]), skill


def _catalog_with_full_execution_identity(tmp_path: Path):  # noqa: ANN202
    root = tmp_path / "skills"
    skill = root / "text-stats"
    scripts = skill / "scripts"
    references = skill / "references"
    scripts.mkdir(parents=True)
    references.mkdir()
    (skill / "SKILL.md").write_text(
        "---\n"
        "name: text-stats\n"
        "description: Count text statistics.\n"
        "entrypoints:\n"
        "  - id: analyze\n"
        "    script: scripts/analyze.py\n"
        "  - id: summarize\n"
        "    script: scripts/summarize.py\n"
        "---\n"
        "Use the analyze entrypoint.\n",
        encoding="utf-8",
    )
    for name in ("analyze.py", "summarize.py"):
        (scripts / name).write_text(
            "def run(arguments, inputs):\n    return None\n",
            encoding="utf-8",
        )
    (references / "rules.md").write_text("Original rules.\n", encoding="utf-8")
    return build_skill_catalog([root]), skill


def _approved_intent(runtime: KernelToolRuntime, call: ToolCall, lease_id: str):  # noqa: ANN202
    context = ToolPrepareContext(
        conversation_id="conversation-1",
        run_id="run-1",
        state_revision=1,
        goal_id="goal-1",
        goal_revision=1,
        workspace_identity_digest="c" * 64,
    )
    approval = runtime.prepare(call, context)
    candidate = approval.request.sandbox_authority_candidate
    lease = SandboxAuthorityLeaseV1.create(
        lease_id=lease_id,
        candidate_digest=candidate.candidate_digest,
        goal_id=candidate.goal_id,
        goal_revision=candidate.goal_revision,
        workspace_identity_digest=candidate.workspace_identity_digest,
        original_command_fingerprint=candidate.original_command_fingerprint,
        policy_digest=candidate.policy_digest,
        mode=candidate.mode,
        network=candidate.network,
        readable_command=candidate.readable_command,
        trust_notice_id=candidate.trust_notice_id,
        trust_notice_digest=candidate.trust_notice_digest,
        approved_request_identity=f"approval:{lease_id}",
        issued_at="2026-09-04T07:59:00+00:00",
        expires_at="2026-09-04T09:00:00+00:00",
    )
    return runtime.prepare(
        call,
        ToolPrepareContext(
            conversation_id="conversation-1",
            run_id="run-1",
            state_revision=1,
            goal_id="goal-1",
            goal_revision=1,
            workspace_identity_digest="c" * 64,
            sandbox_leases=(lease,),
        ),
    )


def _execution_config(
    tmp_path: Path, skill: Path, *, executor=None
) -> SkillExecutionConfig:
    roots = {}
    for name in ("workspace", "temp", "state", "home", "system"):
        roots[name] = tmp_path / name
        roots[name].mkdir()
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    interpreter = runtime / "python"
    interpreter.write_bytes(b"synthetic interpreter")
    interpreter.chmod(0o555)
    runtime.chmod(0o555)
    closure = HermeticRuntimeClosureV1(
        runtime_root=str(runtime),
        interpreter_path=str(interpreter),
        readable_roots=(str(runtime),),
        inventory=(),
        inventory_digest=canonical_json_digest([]),
        manifest_digest="b" * 64,
    )
    return SkillExecutionConfig(
        closure=closure,
        workspace_root=roots["workspace"],
        temp_root=roots["temp"],
        state_root=roots["state"],
        home_root=roots["home"],
        system_runtime_roots=(roots["system"],),
        system_runtime_digest=canonical_json_digest(
            {"roots": [str(roots["system"])]}
        ),
        private_roots=(),
        executor=executor
        or NativeSandboxExecutor(confiner=object(), captured_path=""),
    )


def test_declared_entrypoint_registers_one_closed_governed_tool(tmp_path: Path) -> None:
    catalog, skill = _catalog_with_entrypoint(tmp_path)
    config = _execution_config(tmp_path, skill)

    registrations = build_skill_tool_registrations(
        catalog,
        max_tool_result_chars=10_000,
        execution=config,
    )
    registration = next(
        item for item in registrations if item.spec.name == "skill__text-stats__analyze"
    )

    assert registration.spec.risk is ToolRisk.HIGH
    assert registration.spec.side_effect is SideEffectClass.EXTERNAL
    assert registration.spec.approval_policy is ApprovalPolicy.ALWAYS
    assert registration.spec.egress is EgressClass.NONE
    assert (
        registration.spec.execution_authority
        is ExecutionAuthorityClass.ISOLATED_SANDBOX
    )
    assert registration.spec.input_schema == {
        "type": "object",
        "properties": {"arguments": {"type": "object"}},
        "required": ["arguments"],
        "additionalProperties": False,
    }


def test_composition_registers_declared_entrypoint_when_execution_is_configured(
    tmp_path: Path,
) -> None:
    _catalog, skill = _catalog_with_entrypoint(tmp_path)
    config = _execution_config(tmp_path, skill)

    registrations = build_tool_registrations(
        workspace=config.workspace_root,
        skill_roots=(skill.parent,),
        max_tool_result_chars=10_000,
        skill_execution=config,
    )

    assert "skill__text-stats__analyze" in {
        registration.spec.name for registration in registrations
    }


@pytest.mark.skipif(sys.platform != "darwin", reason="native Skill sandbox is macOS-only")
def test_production_skill_execution_config_canonicalizes_system_temp_alias(
    tmp_path: Path, monkeypatch
) -> None:
    runtime_fixture = _make_runtime(tmp_path / "skill-runtime-v1")
    for directory in sorted(
        (path for path in runtime_fixture.root.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    ):
        directory.chmod(0o555)
    runtime_fixture.root.chmod(0o555)
    real_temp = tmp_path / "real-temp"
    real_temp.mkdir()
    temp_alias = tmp_path / "temp-alias"
    temp_alias.symlink_to(real_temp, target_is_directory=True)
    workspace = tmp_path / "workspace"
    state = tmp_path / "state"
    workspace.mkdir()
    state.mkdir()

    class AvailableConfiner:
        def qualify(self):  # noqa: ANN201
            return SimpleNamespace(available=True)

    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(temp_alias))
    monkeypatch.setattr(
        "agent.sandbox.seatbelt.SeatbeltConfiner", AvailableConfiner
    )

    config = build_skill_execution_config(
        workspace=workspace,
        state_root=state,
        runtime_root=runtime_fixture.root,
    )
    catalog, _skill = _catalog_with_entrypoint(tmp_path / "catalog")
    registrations = build_skill_tool_registrations(
        catalog,
        max_tool_result_chars=10_000,
        execution=config,
    )

    assert str(config.temp_root).startswith(str(real_temp.resolve(strict=True)))
    assert str(temp_alias) not in str(config.temp_root)
    assert "skill__text-stats__analyze" in {
        registration.spec.name for registration in registrations
    }


def test_entrypoint_prepare_builds_bounded_binding_and_requires_approval(
    tmp_path: Path,
) -> None:
    catalog, skill = _catalog_with_entrypoint(tmp_path)
    config = _execution_config(tmp_path, skill)
    registrations = build_skill_tool_registrations(
        catalog,
        max_tool_result_chars=10_000,
        execution=config,
    )
    runtime = KernelToolRuntime(registrations)

    prepared = runtime.prepare(
        ToolCall(
            "call-1",
            "skill__text-stats__analyze",
            {"arguments": {"text": "hello world"}},
        ),
        ToolPrepareContext(
            conversation_id="conversation-1",
            run_id="run-1",
            state_revision=1,
            goal_id="goal-1",
            goal_revision=1,
            workspace_identity_digest="c" * 64,
        ),
    )

    assert isinstance(prepared, ApprovalRequired)
    candidate = prepared.request.sandbox_authority_candidate
    assert candidate is not None
    assert candidate.mode == "read-only"
    assert candidate.network == "off"
    assert "text-stats" in candidate.readable_command
    assert "analyze" in candidate.readable_command
    disclosed = repr(prepared.request)
    for path in (
        skill,
        config.workspace_root,
        config.temp_root,
        Path(config.closure.runtime_root),
    ):
        assert str(path) not in disclosed
    assert os.path.abspath("scripts/analyze.py") not in disclosed


def test_approved_entrypoint_runs_through_structured_sandbox_boundary(
    tmp_path: Path,
) -> None:
    catalog, skill = _catalog_with_entrypoint(tmp_path)
    executor = RecordingExecutor()
    config = _execution_config(tmp_path, skill, executor=executor)
    runtime = KernelToolRuntime(
        build_skill_tool_registrations(
            catalog,
            max_tool_result_chars=10_000,
            execution=config,
        ),
        clock=lambda: NOW,
    )
    call = ToolCall(
        "call-1",
        "skill__text-stats__analyze",
        {"arguments": {"text": "hello world"}},
    )
    context = ToolPrepareContext(
        conversation_id="conversation-1",
        run_id="run-1",
        state_revision=1,
        goal_id="goal-1",
        goal_revision=1,
        workspace_identity_digest="c" * 64,
    )

    approval = runtime.prepare(call, context)
    assert isinstance(approval, ApprovalRequired)
    candidate = approval.request.sandbox_authority_candidate
    lease = SandboxAuthorityLeaseV1.create(
        lease_id="sandbox-lease:skill-entrypoint",
        candidate_digest=candidate.candidate_digest,
        goal_id=candidate.goal_id,
        goal_revision=candidate.goal_revision,
        workspace_identity_digest=candidate.workspace_identity_digest,
        original_command_fingerprint=candidate.original_command_fingerprint,
        policy_digest=candidate.policy_digest,
        mode=candidate.mode,
        network=candidate.network,
        readable_command=candidate.readable_command,
        trust_notice_id=candidate.trust_notice_id,
        trust_notice_digest=candidate.trust_notice_digest,
        approved_request_identity="approval-skill-entrypoint",
        issued_at="2026-09-04T07:59:00+00:00",
        expires_at="2026-09-04T09:00:00+00:00",
    )
    intent = runtime.prepare(
        call,
        ToolPrepareContext(
            conversation_id="conversation-1",
            run_id="run-1",
            state_revision=1,
            goal_id="goal-1",
            goal_revision=1,
            workspace_identity_digest="c" * 64,
            sandbox_leases=(lease,),
        ),
    )

    result = runtime.invoke(intent)

    assert result.executed is True
    assert result.is_error is False
    assert json.loads(result.content)["payload"] == {"words": 2}
    assert len(executor.calls) == 1
    assert executor.calls[0][2].inputs == ()
    assert executor.calls[0][1].package_read_paths == ("scripts/analyze.py",)


def test_agent_runtime_checkpoints_entrypoint_execution_before_result(
    tmp_path: Path,
) -> None:
    catalog, skill = _catalog_with_entrypoint(tmp_path)
    executor = RecordingExecutor()
    config = _execution_config(tmp_path, skill, executor=executor)
    store = RecordingCheckpointStore(conversation_with_active_goal("conversation-1"))
    provider = ScriptedProvider(
        goal_noop_response("skill-user-supplement"),
        ModelResponse(
            (
                ModelToolCall(
                    "call-1",
                    "skill__text-stats__analyze",
                    {"arguments": {"text": "hello world"}},
                ),
            )
        ),
        ModelResponse(
            (),
            control=BlockedClaim(
                correlation_id="skill-entrypoint-complete",
                goal_id=RUNTIME_GOAL_ID,
                goal_revision=1,
                blocker="fixture completed",
                safe_attempts=("ran the declared entrypoint",),
                resume_condition="provide a completion oracle",
            ),
        ),
    )
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=8_000, output_reserve=200),
        ),
        tool_runtime=KernelToolRuntime(
            build_skill_tool_registrations(
                catalog,
                max_tool_result_chars=10_000,
                execution=config,
            ),
            clock=lambda: NOW,
        ),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-1",
    )

    first = runtime.run_turn(
        SubmitMessage(
            conversation_id="conversation-1",
            action_seq=store.state.next_action_seq,
            expected_revision=store.state.revision,
            run_id="run-1",
            message="run the text stats skill",
        ),
        store.load(),
    )
    assert first.status is RunStatus.AWAITING_APPROVAL
    assert first.request is not None

    approved = runtime.run_turn(
        ResolveApproval(
            conversation_id="conversation-1",
            action_seq=store.state.next_action_seq,
            expected_revision=store.state.revision,
            request_id=first.request.request_id,
            binding_digest=first.request.binding_digest,
            approved=True,
            approved_at="2026-09-04T07:59:00+00:00",
        ),
        store.load(),
    )

    assert approved.status is RunStatus.COMPLETED
    assert len(executor.calls) == 1
    assert store.saved_phases.index("executing") < store.saved_fact_kinds.index(
        "tool_result"
    )


def test_entrypoint_drift_after_approval_fails_before_sandbox_call(
    tmp_path: Path,
) -> None:
    catalog, skill = _catalog_with_entrypoint(tmp_path)
    executor = RecordingExecutor()
    config = _execution_config(tmp_path, skill, executor=executor)
    runtime = KernelToolRuntime(
        build_skill_tool_registrations(
            catalog,
            max_tool_result_chars=10_000,
            execution=config,
        ),
        clock=lambda: NOW,
    )
    call = ToolCall(
        "call-1",
        "skill__text-stats__analyze",
        {"arguments": {"text": "hello world"}},
    )
    context = ToolPrepareContext(
        conversation_id="conversation-1",
        run_id="run-1",
        state_revision=1,
        goal_id="goal-1",
        goal_revision=1,
        workspace_identity_digest="c" * 64,
    )
    approval = runtime.prepare(call, context)
    candidate = approval.request.sandbox_authority_candidate
    lease = SandboxAuthorityLeaseV1.create(
        lease_id="sandbox-lease:skill-entrypoint",
        candidate_digest=candidate.candidate_digest,
        goal_id=candidate.goal_id,
        goal_revision=candidate.goal_revision,
        workspace_identity_digest=candidate.workspace_identity_digest,
        original_command_fingerprint=candidate.original_command_fingerprint,
        policy_digest=candidate.policy_digest,
        mode=candidate.mode,
        network=candidate.network,
        readable_command=candidate.readable_command,
        trust_notice_id=candidate.trust_notice_id,
        trust_notice_digest=candidate.trust_notice_digest,
        approved_request_identity="approval-skill-entrypoint",
        issued_at="2026-09-04T07:59:00+00:00",
        expires_at="2026-09-04T09:00:00+00:00",
    )
    intent = runtime.prepare(
        call,
        ToolPrepareContext(
            conversation_id="conversation-1",
            run_id="run-1",
            state_revision=1,
            goal_id="goal-1",
            goal_revision=1,
            workspace_identity_digest="c" * 64,
            sandbox_leases=(lease,),
        ),
    )
    (skill / "scripts" / "analyze.py").write_text(
        "def run(arguments, inputs):\n    return {'tampered': True}\n",
        encoding="utf-8",
    )

    result = runtime.invoke(intent)

    assert result.executed is False
    assert result.metadata["code"] == "skill_entrypoint_drift"
    assert executor.calls == []


def test_skill_body_drift_after_approval_fails_before_sandbox_call(
    tmp_path: Path,
) -> None:
    catalog, skill = _catalog_with_entrypoint(tmp_path)
    executor = RecordingExecutor()
    config = _execution_config(tmp_path, skill, executor=executor)
    runtime = KernelToolRuntime(
        build_skill_tool_registrations(
            catalog,
            max_tool_result_chars=10_000,
            execution=config,
        ),
        clock=lambda: NOW,
    )
    call = ToolCall(
        "call-1",
        "skill__text-stats__analyze",
        {"arguments": {"text": "hello world"}},
    )
    context = ToolPrepareContext(
        conversation_id="conversation-1",
        run_id="run-1",
        state_revision=1,
        goal_id="goal-1",
        goal_revision=1,
        workspace_identity_digest="c" * 64,
    )
    approval = runtime.prepare(call, context)
    candidate = approval.request.sandbox_authority_candidate
    lease = SandboxAuthorityLeaseV1.create(
        lease_id="sandbox-lease:skill-body",
        candidate_digest=candidate.candidate_digest,
        goal_id=candidate.goal_id,
        goal_revision=candidate.goal_revision,
        workspace_identity_digest=candidate.workspace_identity_digest,
        original_command_fingerprint=candidate.original_command_fingerprint,
        policy_digest=candidate.policy_digest,
        mode=candidate.mode,
        network=candidate.network,
        readable_command=candidate.readable_command,
        trust_notice_id=candidate.trust_notice_id,
        trust_notice_digest=candidate.trust_notice_digest,
        approved_request_identity="approval-skill-body",
        issued_at="2026-09-04T07:59:00+00:00",
        expires_at="2026-09-04T09:00:00+00:00",
    )
    intent = runtime.prepare(
        call,
        ToolPrepareContext(
            conversation_id="conversation-1",
            run_id="run-1",
            state_revision=1,
            goal_id="goal-1",
            goal_revision=1,
            workspace_identity_digest="c" * 64,
            sandbox_leases=(lease,),
        ),
    )
    skill_file = skill / "SKILL.md"
    skill_file.write_text(
        skill_file.read_text(encoding="utf-8") + "changed after approval\n",
        encoding="utf-8",
    )

    result = runtime.invoke(intent)

    assert result.executed is False
    assert result.metadata["code"] == "skill_entrypoint_drift"
    assert executor.calls == []


@pytest.mark.parametrize("drift", ["resource", "other-entrypoint"])
def test_any_execution_identity_drift_after_approval_fails_before_sandbox_call(
    tmp_path: Path, drift: str
) -> None:
    catalog, skill = _catalog_with_full_execution_identity(tmp_path)
    executor = RecordingExecutor()
    config = _execution_config(tmp_path, skill, executor=executor)
    runtime = KernelToolRuntime(
        build_skill_tool_registrations(
            catalog,
            max_tool_result_chars=10_000,
            execution=config,
        ),
        clock=lambda: NOW,
    )
    call = ToolCall(
        "call-1",
        "skill__text-stats__analyze",
        {"arguments": {"text": "hello world"}},
    )
    intent = _approved_intent(runtime, call, f"sandbox-lease:{drift}")
    if drift == "resource":
        target = skill / "references" / "rules.md"
        replacement = "Changed rules.\n"
    else:
        target = skill / "scripts" / "summarize.py"
        replacement = "def run(arguments, inputs):\n    return {'changed': True}\n"
    target.write_text(replacement, encoding="utf-8")

    result = runtime.invoke(intent)

    assert result.executed is False
    assert result.metadata["code"] == "skill_entrypoint_drift"
    assert executor.calls == []


def test_oversized_entrypoint_arguments_fail_before_approval_or_sandbox(
    tmp_path: Path,
) -> None:
    catalog, skill = _catalog_with_entrypoint(tmp_path)
    executor = RecordingExecutor()
    config = _execution_config(tmp_path, skill, executor=executor)
    runtime = KernelToolRuntime(
        build_skill_tool_registrations(
            catalog,
            max_tool_result_chars=10_000,
            execution=config,
        )
    )

    result = runtime.prepare(
        ToolCall(
            "call-1",
            "skill__text-stats__analyze",
            {"arguments": {"text": "x" * (64 * 1024)}},
        ),
        ToolPrepareContext(
            conversation_id="conversation-1",
            run_id="run-1",
            state_revision=1,
            goal_id="goal-1",
            goal_revision=1,
            workspace_identity_digest="c" * 64,
        ),
    )

    assert result.executed is False
    assert result.is_error is True
    assert result.metadata["code"] == "binding_failure"
    assert executor.calls == []
