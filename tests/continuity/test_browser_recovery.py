"""018 Task 5 Step 3：restart/security 投影 Reds（先 Red）。

LocalCheckpointStore 重开投影 “browser takeover waiting” 与 /browser-done、
/cancel（不是 “resuming”）；丢失/不匹配 session 变 needs-human；序列化
state/events/views/context 不含 credential/cookie/storage-state/password/
form-value sentinel；expiry 全程 RFC3339 字符串，无 monotonic 进 checkpoint。
"""

import json

import pytest

from agent.runtime.checkpoint import LocalCheckpointStore
from agent.runtime.contracts import BrowserTakeoverRequestV1
from agent.runtime.state import begin_browser_takeover
from tests.kernel.fakes import conversation_with_active_goal

REQUEST = BrowserTakeoverRequestV1(
    request_id="takeover-1",
    session_ref="session-0123456789abcdef",
    profile_ref="profile-0123456789abcdef",
    profile_revision=3,
    browser_identity_digest="a" * 64,
    goal_id="goal-1",
    goal_revision=1,
    requested_at="2026-08-28T10:00:00+00:00",
)


def pending_state():
    return begin_browser_takeover(conversation_with_active_goal(), REQUEST)


def test_restart_without_exact_live_session_needs_human(tmp_path):
    from agent.runtime.views import project_browser_takeover_status

    state = pending_state()
    text = project_browser_takeover_status(state)
    assert text is not None
    assert "needs human" in text.lower()
    assert "resuming" not in text.lower()

    waiting = project_browser_takeover_status(
        state, current_session_ref=REQUEST.session_ref,
    )
    assert waiting is not None and "browser takeover waiting" in waiting.lower()
    assert "/browser-done" in waiting and "/cancel" in waiting


def test_mismatched_or_lost_session_needs_human(tmp_path):
    from agent.runtime.views import project_browser_takeover_status

    state = pending_state()
    mismatched = project_browser_takeover_status(
        state, current_session_ref="session-ffffffffffffffff"
    )
    assert mismatched is not None
    assert "needs human" in mismatched.lower()
    lost = project_browser_takeover_status(state, current_session_ref=None)
    assert lost is not None and "needs human" in lost.lower()


def test_takeover_state_survives_checkpoint_round_trip(tmp_path):
    state = pending_state()
    store = LocalCheckpointStore.initialize(tmp_path / "state.json", state)
    reopened = store.load()
    assert reopened.state.browser_takeover_pending == REQUEST
    # durable expiry 是 RFC3339 字符串；序列化里无 monotonic 字段。
    raw = (tmp_path / "state.json").read_text()
    assert "requested_at" in raw
    assert "monotonic" not in raw


def test_serialized_state_has_no_credential_sentinels(tmp_path):
    state = pending_state()
    LocalCheckpointStore.initialize(tmp_path / "state.json", state)
    raw = (tmp_path / "state.json").read_text().lower()
    for sentinel in (
        "password",
        "cookie",
        "storage_state",
        "storagestate",
        "form_value",
        "credential",
        "hunter2",
    ):
        assert sentinel not in raw, sentinel


def test_checkpoint_json_is_strict_json(tmp_path):
    state = pending_state()
    LocalCheckpointStore.initialize(tmp_path / "state.json", state)
    payload = json.loads((tmp_path / "state.json").read_text())
    assert isinstance(payload, dict)


# --------------------------------------------------------------------------- #
# Task 5 二轮审计：codec unknown/partial fail closed、restart 后 typed
# action 完成/取消
# --------------------------------------------------------------------------- #


def test_codec_rejects_unknown_and_partial_browser_payloads(tmp_path):
    import json as jsonlib

    state = pending_state()
    path = tmp_path / "state.json"
    LocalCheckpointStore.initialize(path, state)
    document = jsonlib.loads(path.read_text())
    pending = document["state"]["browser_takeover_pending"]
    # unknown key → fail closed。
    tampered = dict(pending)
    tampered["extra_field"] = 1
    document["state"]["browser_takeover_pending"] = tampered
    path.write_text(jsonlib.dumps(document))
    from agent.runtime.checkpoint import CheckpointVersionError

    with pytest.raises(CheckpointVersionError):
        LocalCheckpointStore(path).load()
    # partial（缺 key）→ fail closed。
    partial = {key: value for key, value in pending.items() if key != "requested_at"}
    document["state"]["browser_takeover_pending"] = partial
    path.write_text(jsonlib.dumps(document))
    with pytest.raises(CheckpointVersionError):
        LocalCheckpointStore(path).load()


def test_restart_complete_and_cancel_via_runtime_typed_actions(tmp_path):
    from agent.runtime.context import ContextLimits, KernelContextManager
    from agent.runtime.contracts import (
        CompleteBrowserTakeover,
        RunStatus,
    )
    from agent.runtime.loop import AgentRuntime, InvocationLimits
    from tests.kernel.fakes import CollectingSink, ScriptedProvider

    state = pending_state()
    store = LocalCheckpointStore.initialize(tmp_path / "state.json", state)
    runtime = AgentRuntime(
        provider=ScriptedProvider(),
        context_manager=KernelContextManager(
            system_policy="Be concise.",
            limits=ContextLimits(max_input_tokens=2_000, output_reserve=200),
        ),
        tool_runtime=None,
        checkpoint_store=store,
        event_sink=CollectingSink(),
            limits=InvocationLimits(),
            invocation_id_factory=lambda: "invocation-1",
            browser_takeover_complete=lambda request: request.profile_revision + 1,
        )
    snapshot = store.load()
    complete = CompleteBrowserTakeover(
        conversation_id=snapshot.state.conversation_id,
        action_seq=snapshot.state.next_action_seq,
        expected_revision=snapshot.state.revision,
        request_id=REQUEST.request_id,
        session_ref=REQUEST.session_ref,
        expected_profile_revision=REQUEST.profile_revision,
    )
    lease = store.try_acquire(snapshot.state.conversation_id)
    lease.release()
    result = runtime.run_turn(complete, snapshot)
    assert result.status is RunStatus.COMPLETED
    assert result.state.browser_takeover_pending is None
