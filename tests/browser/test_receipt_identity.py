"""018 Task 8 审计闭合：production browser receipt identity（先 Red）。

真实 ``_BrowserTools.act``/``observe`` 输出的 durable metadata 必须精确绑定
session_ref、profile_revision、browser_identity_digest——evidence oracle 依赖
这些字段证明同 session/profile/browser；手工 fixture 不能替代 production
路径。
"""

from agent.browser.profile_store import BrowserProfileStore
from agent.browser.session_store import BrowserSessionStore
from agent.browser.tools import build_browser_tool_registrations
from agent.runtime.contracts import (
    ApprovalGrant,
    ToolCall,
    ToolResult,
)
from agent.runtime.tools import KernelToolRuntime
from tests.browser.test_tools import RecordingEnvironment, _context

BROWSER_IDENTITY = "b" * 64
SESSION_REF = "session-0123456789abcdef"
CLOCK = lambda: "2026-08-28T10:00:00+00:00"  # noqa: E731


def _runtime(tmp_path, environment):
    registrations = build_browser_tool_registrations(
        environment=environment,
        profile_store=BrowserProfileStore(root=tmp_path / "profiles"),
        session_store=BrowserSessionStore(root=tmp_path / "sessions"),
        browser_identity_digest=BROWSER_IDENTITY,
        clock=CLOCK,
        monotonic_clock=lambda: 1000.0,
    )
    return KernelToolRuntime(registrations, clock=CLOCK)


def _invoke_observed_act(runtime):
    open_call = ToolCall("open-1", "browser_open", {"mode": "public_read_ephemeral"})
    approval = runtime.prepare(open_call, _context())
    prepared_open = runtime.prepare(
        open_call,
        _context(),
        approval=ApprovalGrant(
            request_id=approval.request.request_id,
            binding_digest=approval.request.binding_digest,
            approval_basis_revision=7,
        ),
    )
    runtime.invoke(prepared_open)
    observe_call = ToolCall(
        "observe-1", "browser_observe", {"session_ref": SESSION_REF}
    )
    observed = runtime.invoke(runtime.prepare(observe_call, _context()))
    act_call = ToolCall(
        "act-1",
        "browser_act",
        {
            "session_ref": SESSION_REF,
            "kind": "navigate",
            "observation_digest": observed.metadata["observation_digest"],
            "page_id": SESSION_REF,
            "frame_id": "main",
            "params": {"url": "https://site.example.test/docs"},
        },
    )
    return runtime.invoke(runtime.prepare(act_call, _context()))


def test_production_action_receipt_binds_full_identity(tmp_path):
    runtime = _runtime(tmp_path, RecordingEnvironment())
    acted = _invoke_observed_act(runtime)
    assert isinstance(acted, ToolResult)
    assert acted.is_error is False
    assert acted.executed is True
    metadata = acted.metadata
    assert metadata["browser_receipt_kind"] == "browser_action_v1"
    assert metadata["session_ref"] == SESSION_REF
    assert metadata["browser_identity_digest"] == BROWSER_IDENTITY
    # public-read 的 profile_revision 为 None 也必须显式存在。
    assert "profile_revision" in metadata


def test_production_observe_metadata_binds_full_identity(tmp_path):
    environment = RecordingEnvironment()
    runtime = _runtime(tmp_path, environment)
    open_call = ToolCall("open-1", "browser_open", {"mode": "public_read_ephemeral"})
    approval = runtime.prepare(open_call, _context())
    runtime.invoke(
        runtime.prepare(
            open_call,
            _context(),
            approval=ApprovalGrant(
                request_id=approval.request.request_id,
                binding_digest=approval.request.binding_digest,
                approval_basis_revision=7,
            ),
        )
    )
    observe_call = ToolCall(
        "observe-1", "browser_observe", {"session_ref": SESSION_REF}
    )
    observed = runtime.invoke(runtime.prepare(observe_call, _context()))
    assert observed.metadata["session_ref"] == SESSION_REF
    assert observed.metadata["browser_identity_digest"] == BROWSER_IDENTITY
    assert "profile_revision" in observed.metadata


def test_production_receipt_and_observe_satisfy_evidence_oracle(tmp_path):
    from dataclasses import replace

    from agent.runtime.contracts import (
        AdmittedCriterion,
        CompletionClaim,
        EvidenceOracleKind,
        canonical_json_digest,
    )
    from agent.runtime.evidence import ClosedEvidenceRegistry
    from tests.kernel.fakes import conversation_with_active_goal

    environment = RecordingEnvironment()
    runtime = _runtime(tmp_path, environment)
    acted = _invoke_observed_act(runtime)
    # 同一 session 的 fresh readback observe。
    observe_again = ToolCall(
        "observe-2", "browser_observe", {"session_ref": SESSION_REF}
    )
    readback = runtime.invoke(runtime.prepare(observe_again, _context()))
    # 把两条 production tool result 变成 durable facts。
    from agent.runtime.contracts import ConversationFact, FactKind

    def _fact(result, call_id, seq):
        return ConversationFact(
            fact_id=f"run:run-1:tool-result:{call_id}:{seq}",
            kind=FactKind.TOOL_RESULT,
            content={
                "tool_call_id": call_id,
                "text": result.content,
                "is_error": result.is_error,
                "executed": result.executed,
                "metadata": dict(result.metadata),
            },
        )

    facts = (
        _fact(acted, "act-1", 3),
        _fact(readback, "observe-2", 4),
    )
    state = conversation_with_active_goal()
    goal = state.goal
    predicate = {
        "receipt_kind": "browser_readback_v1",
        "receipt_digest": acted.metadata["receipt_digest"],
        "session_ref": SESSION_REF,
        "readback_observation_digest": readback.metadata["observation_digest"],
        "profile_revision": acted.metadata["profile_revision"],
        "browser_identity_digest": BROWSER_IDENTITY,
    }
    criterion = AdmittedCriterion(
        criterion_id=goal.proposed_criteria[0].criterion_id,
        description=goal.proposed_criteria[0].description,
        source_fact_id=state.facts[0].fact_id,
        oracle_kind=EvidenceOracleKind.BROWSER_READBACK,
        predicate=predicate,
        required_evidence_class="browser_readback_v1",
        admission_digest=canonical_json_digest(predicate),
    )
    goal = replace(goal, admitted_criteria=(criterion,))
    claim = CompletionClaim(
        correlation_id="claim-1",
        goal_id=goal.goal_id,
        goal_revision=goal.revision,
        criterion_evidence_refs=(
            ClosedEvidenceRegistry.evidence_id(
                goal.goal_id, goal.revision, criterion.criterion_id
            ),
        ),
    )
    state = replace(state, goal=goal, facts=(*state.facts, *facts))
    records = ClosedEvidenceRegistry().derive(
        state, claim, observed_at="2026-08-28T00:00:00Z"
    )
    assert len(records) == 1
    assert records[0].oracle_identity == "browser-readback:v1"
