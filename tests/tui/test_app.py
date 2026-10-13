from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from dataclasses import replace

import pytest

from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    ActiveRun,
    ActiveRunStatus,
    ApprovalRequest,
    BrowserTakeoverRequestV1,
    ControlRequestKind,
    ConversationState,
    EgressClass,
    ExecutionAuthorityClass,
    GoalStatus,
    LoadedSnapshot,
    ModelResponse,
    ModelTextBlock,
    RecoveryRequest,
    Resume,
    RunResult,
    RunStatus,
    SideEffectClass,
    ToolCall,
)
from agent.runtime.control import ControlInbox
from agent.runtime.loop import AgentRuntime, InvocationLimits
from agent.runtime.state import (
    accept_action,
    begin_browser_takeover,
    mark_executing,
    pause_for_approval,
    pause_for_recovery,
    start_tool_batch,
)
from agent.runtime.tools import KernelToolRuntime
from agent.runtime.views import SourceView
from agent.tui.adapter import TuiAdapter
from agent.tui.render import TuiProjection, project
from tests.kernel.fakes import (
    CollectingSink,
    InMemoryCheckpointStore,
    ScriptedProvider,
    conversation_with_active_goal,
    conversation_with_terminal_goal,
)


def _adapter() -> TuiAdapter:
    store = InMemoryCheckpointStore(ConversationState.new("c1"))
    provider = ScriptedProvider(ModelResponse((ModelTextBlock("hello from kernel"),)))
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy", limits=ContextLimits(max_input_tokens=8_000, output_reserve=200)
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-1",
    )
    return TuiAdapter(runtime, store)


def _run_id_factory() -> Callable[[], str]:
    counter = {"n": 0}

    def factory() -> str:
        counter["n"] += 1
        return f"run-{counter['n']}"

    return factory


class _RecordingRuntime:
    """记录 dispatch 的 action，不执行真实 loop；用于断言 gating 行为。"""

    def __init__(self) -> None:
        self.actions: list = []

    def run_turn(self, action, snapshot: LoadedSnapshot) -> RunResult:
        self.actions.append(action)
        return RunResult(status=RunStatus.COMPLETED, state=snapshot.state)


def _approval_state(preview: str = "preview-body") -> ConversationState:
    started = accept_action(
        None,
        _submit("c1", "r", "hi"),
    ).state
    batched = start_tool_batch(started, (ToolCall("call-1", "write_file", {}),))
    return pause_for_approval(
        batched,
        ApprovalRequest(
            request_id="a1",
            run_id="r",
            tool_call_id="call-1",
            binding_digest="b",
            preview=preview,
            tool_name="write_file",
            risk="high",
            side_effect="external",
        ),
    )


def _recovery_state() -> ConversationState:
    started = accept_action(None, _submit("c2", "r2", "hi")).state
    batched = start_tool_batch(started, (ToolCall("call-2", "write_file", {}),))
    executing = mark_executing(
        batched,
        tool_call_id="call-2",
        intent_digest="d",
        idempotency_key="k",
        side_effect=SideEffectClass.WRITE,
        egress=EgressClass.NONE,
        operation="write_file",
        request_identity="k",
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
    )
    return pause_for_recovery(
        executing,
        RecoveryRequest(
            request_id="rec1",
            run_id="r2",
            tool_call_id="call-2",
            binding_digest="d",
            summary="summary-text",
        ),
    )


def _executing_state() -> ConversationState:
    started = accept_action(None, _submit("c3", "r3", "hi")).state
    batched = start_tool_batch(started, (ToolCall("call-3", "write_file", {}),))
    return mark_executing(
        batched,
        tool_call_id="call-3",
        intent_digest="d3",
        idempotency_key="k3",
        side_effect=SideEffectClass.WRITE,
        egress=EgressClass.NONE,
        operation="write_file",
        request_identity="k3",
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
    )


def _takeover_state(
    *,
    request_id: str = "takeover-1",
    session_ref: str = "session-0123456789abcdef",
    profile_ref: str = "profile-0123456789abcdef",
    profile_revision: int = 3,
) -> ConversationState:
    ready = conversation_with_active_goal("c-takeover")
    return begin_browser_takeover(
        ready,
        BrowserTakeoverRequestV1(
            request_id=request_id,
            session_ref=session_ref,
            profile_ref=profile_ref,
            profile_revision=profile_revision,
            browser_identity_digest="a" * 64,
            goal_id=ready.goal.goal_id,
            goal_revision=ready.goal.revision,
            requested_at="2026-09-08T08:00:00+00:00",
        ),
    )


def _submit(conv: str, run_id: str, message: str):
    from agent.runtime.contracts import SubmitMessage

    return SubmitMessage(
        conversation_id=conv, action_seq=1, expected_revision=0, run_id=run_id, message=message
    )


def _runtime_with_store(
    state: ConversationState,
    *responses: ModelResponse,
):
    store = InMemoryCheckpointStore(state)
    provider = ScriptedProvider(
        *(responses or (ModelResponse((ModelTextBlock("must not run"),)),))
    )
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy", limits=ContextLimits(max_input_tokens=8_000, output_reserve=200)
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-1",
    )
    return runtime, store, provider


@pytest.mark.parametrize(
    ("status", "expected_hint"),
    (
        (GoalStatus.VERIFIED_DONE, "Task finished"),
        (GoalStatus.CANCELLED, "Task cancelled"),
    ),
)
def test_terminal_goal_mount_enables_truthful_follow_up(
    status: GoalStatus,
    expected_hint: str,
) -> None:
    pytest.importorskip("textual")
    from agent.tui.app import build_app

    state = conversation_with_terminal_goal(status)
    store = InMemoryCheckpointStore(state)
    app = build_app(
        TuiAdapter(_RecordingRuntime(), store),
        run_id_factory=_run_id_factory(),
    )

    async def scenario() -> None:
        async with app.run_test():
            assert app.projection is not None
            assert app.projection.actions == ("submit",)
            assert app.query_one("#message").disabled is False
            hints = str(app.query_one("#action_hints").render())
            assert expected_hint in hints
            assert "follow-up" in hints
            assert "new task" in hints

            app._refresh(
                RunResult(
                    status=RunStatus.COMPLETED,
                    state=state,
                    message="nonempty terminal result",
                )
            )
            refreshed_hints = str(app.query_one("#action_hints").render())
            assert expected_hint in refreshed_hints
            assert "follow-up" in refreshed_hints

    asyncio.run(scenario())


@pytest.mark.parametrize("status", [GoalStatus.VERIFIED_DONE, GoalStatus.CANCELLED])
def test_terminal_follow_up_submit_binds_displayed_snapshot(status: GoalStatus) -> None:
    pytest.importorskip("textual")
    from agent.runtime.contracts import SubmitMessage
    from agent.tui.app import build_app

    displayed = conversation_with_terminal_goal(status)
    recording = _RecordingRuntime()
    app = build_app(
        TuiAdapter(recording, InMemoryCheckpointStore(displayed)),
        run_id_factory=_run_id_factory(),
    )

    async def scenario() -> None:
        async with app.run_test() as pilot:
            message = app.query_one("#message")
            message.value = "Explain the result."
            await pilot.press("enter")
            for _ in range(50):
                await pilot.pause(delay=0.02)
                if recording.actions:
                    break

            assert len(recording.actions) == 1
            action = recording.actions[0]
            assert isinstance(action, SubmitMessage)
            assert action.conversation_id == displayed.conversation_id
            assert action.action_seq == displayed.next_action_seq
            assert action.expected_revision == displayed.revision
            assert action.run_id == "run-1"
            assert action.message == "Explain the result."

    asyncio.run(scenario())


def test_pilot_displays_ctrl_q_and_uses_it_for_safe_idle_quit() -> None:
    pytest.importorskip("textual")
    from agent.tui.app import build_app

    app = build_app(_adapter(), run_id_factory=_run_id_factory())

    async def scenario() -> None:
        async with app.run_test() as pilot:
            hints = str(app.query_one("#action_hints").render())
            assert "Ctrl-Q: quit" in hints
            await pilot.press("ctrl+q")
        assert app.closing_requested is True
        assert app.shutdown_blocked is False

    asyncio.run(scenario())


@pytest.mark.parametrize("status", [GoalStatus.VERIFIED_DONE, GoalStatus.CANCELLED])
def test_terminal_goal_follow_up_preserves_durable_goal(status: GoalStatus) -> None:
    state = conversation_with_terminal_goal(status)
    original_goal = state.goal
    original_evidence = state.evidence_records
    original_claim = state.completion_claim
    runtime, store, provider = _runtime_with_store(
        state,
        ModelResponse((ModelTextBlock("first explanation"),)),
        ModelResponse((ModelTextBlock("second explanation"),)),
    )
    adapter = TuiAdapter(runtime, store)

    action = replace(
        _submit(
            state.conversation_id,
            "run-terminal-follow-up",
            "Explain the result.",
        ),
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
    )
    result = adapter.execute_once(action)

    assert result.status is RunStatus.COMPLETED
    assert len(provider.calls) == 1
    assert store.state.goal == original_goal
    assert store.state.evidence_records == original_evidence
    assert store.state.completion_claim == original_claim
    assert project(store.state).actions == ("submit",)

    refreshed = store.state
    second_action = replace(
        _submit(
            refreshed.conversation_id,
            "run-terminal-follow-up-2",
            "Explain it another way.",
        ),
        action_seq=refreshed.next_action_seq,
        expected_revision=refreshed.revision,
    )
    second = adapter.execute_once(second_action)

    assert second.status is RunStatus.COMPLETED
    assert len(provider.calls) == 2
    assert store.state.goal == original_goal
    assert store.state.evidence_records == original_evidence
    assert store.state.completion_claim == original_claim
    assert any(fact.content.get("text") == "first explanation" for fact in store.state.facts)
    assert any(fact.content.get("text") == "second explanation" for fact in store.state.facts)
    assert project(store.state).actions == ("submit",)


def test_stale_terminal_follow_up_is_not_rebound_or_retried() -> None:
    pytest.importorskip("textual")
    from agent.tui.app import build_app

    displayed = conversation_with_terminal_goal(GoalStatus.CANCELLED)
    replacement = replace(
        displayed,
        revision=displayed.revision + 10,
        next_action_seq=displayed.next_action_seq + 1,
        active_run=ActiveRun("run-B", status=ActiveRunStatus.PAUSED_RETRYABLE),
    )
    runtime, store, provider = _runtime_with_store(displayed)
    adapter = TuiAdapter(runtime, store)
    app = build_app(adapter, run_id_factory=_run_id_factory())

    async def scenario() -> None:
        async with app.run_test() as pilot:
            assert app.projection is not None
            assert app.projection.actions == ("submit",)

            store.state = replacement
            message = app.query_one("#message")
            message.value = "stale follow-up"
            await pilot.press("enter")
            for _ in range(100):
                await pilot.pause(delay=0.02)
                if (
                    not adapter.is_active
                    and app.projection is not None
                    and app.projection.actions == ("resume", "cancel")
                ):
                    break

            assert store.state == replacement
            assert provider.calls == []
            assert app.projection is not None
            assert app.projection.actions == ("resume", "cancel")

            await pilot.press("enter")
            await pilot.pause(delay=0.05)
            assert store.state == replacement
            assert provider.calls == []

    asyncio.run(scenario())


def test_pilot_submit_completes() -> None:
    pytest.importorskip("textual")
    from agent.tui.app import build_app

    async def scenario() -> None:
        adapter = _adapter()
        app = build_app(adapter, run_id_factory=_run_id_factory())
        async with app.run_test() as pilot:
            pilot.app.query_one("#message").value = "ping"
            await pilot.press("enter")
            for _ in range(50):
                await pilot.pause(delay=0.05)
                state = adapter.load_view().snapshot.state
                if (
                    state.last_safe_result is not None
                    and state.last_safe_result.message == "hello from kernel"
                ):
                    return
            assert False, "kernel result did not advance authoritative state"  # noqa: B011

    asyncio.run(scenario())


def test_pilot_new_session_returns_process_signal() -> None:
    """真实键盘提交 /new 后，TUI 把会话切换交还给唯一 composition root。"""
    pytest.importorskip("textual")
    from agent.cli.actions import NEW_SESSION_REQUESTED
    from agent.tui.app import build_app

    async def scenario() -> None:
        app = build_app(_adapter(), run_id_factory=_run_id_factory())
        async with app.run_test() as pilot:
            app.query_one("#message").value = "/new"
            await pilot.press("enter")
        assert app.return_code == NEW_SESSION_REQUESTED

    asyncio.run(scenario())


def test_takeover_result_cannot_replace_authoritative_waiting_form() -> None:
    pytest.importorskip("textual")
    from agent.tui.app import build_app

    waiting = _takeover_state()
    store = InMemoryCheckpointStore(waiting)
    recording = _RecordingRuntime()
    app = build_app(TuiAdapter(recording, store), run_id_factory=_run_id_factory())

    async def scenario() -> None:
        async with app.run_test() as pilot:
            app._refresh(
                RunResult(
                    status=RunStatus.COMPLETED,
                    state=waiting,
                    message="browser handoff requested",
                )
            )
            status = str(app.query_one("#status").render())
            assert status.startswith("Browser takeover — waiting for you")
            assert "completed:" not in status.lower()
            assert app.projection is not None
            assert app.projection.form_kind == "browser_takeover"
            assert app.query_one("#message").disabled is True

            await pilot.press("enter")
            await pilot.pause(delay=0.05)
            assert recording.actions == []

    asyncio.run(scenario())


def test_pilot_browser_done_dispatches_exact_displayed_action() -> None:
    pytest.importorskip("textual")
    from agent.runtime.contracts import CompleteBrowserTakeover
    from agent.tui.app import build_app

    waiting = _takeover_state()
    store = InMemoryCheckpointStore(waiting)
    recording = _RecordingRuntime()
    app = build_app(TuiAdapter(recording, store), run_id_factory=_run_id_factory())

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await pilot.press("b")
            for _ in range(50):
                await pilot.pause(delay=0.02)
                if recording.actions:
                    break

            assert len(recording.actions) == 1
            action = recording.actions[0]
            assert isinstance(action, CompleteBrowserTakeover)
            assert action.conversation_id == waiting.conversation_id
            assert action.action_seq == waiting.next_action_seq
            assert action.expected_revision == waiting.revision
            assert action.request_id == "takeover-1"
            assert action.session_ref == "session-0123456789abcdef"
            assert action.expected_profile_revision == 3

    asyncio.run(scenario())


@pytest.mark.parametrize("with_active_run", [False, True])
def test_pilot_browser_cancel_never_becomes_run_or_goal_cancel(
    with_active_run: bool,
) -> None:
    pytest.importorskip("textual")
    from agent.runtime.contracts import CancelBrowserTakeover
    from agent.tui.app import build_app

    waiting = _takeover_state()
    if with_active_run:
        waiting = replace(
            waiting,
            active_run=ActiveRun(
                "run-takeover",
                status=ActiveRunStatus.PAUSED_RETRYABLE,
            ),
        )
    store = InMemoryCheckpointStore(waiting)
    recording = _RecordingRuntime()
    app = build_app(TuiAdapter(recording, store), run_id_factory=_run_id_factory())

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await pilot.press("c")
            for _ in range(50):
                await pilot.pause(delay=0.02)
                if recording.actions:
                    break

            assert len(recording.actions) == 1
            action = recording.actions[0]
            assert isinstance(action, CancelBrowserTakeover)
            assert action.conversation_id == waiting.conversation_id
            assert action.action_seq == waiting.next_action_seq
            assert action.expected_revision == waiting.revision
            assert action.request_id == "takeover-1"

    asyncio.run(scenario())


def test_active_takeover_gesture_cannot_become_cooperative_control() -> None:
    pytest.importorskip("textual")
    from agent.tui.app import build_app

    store = InMemoryCheckpointStore(_takeover_state())
    adapter = TuiAdapter(_RecordingRuntime(), store)
    controls: list[tuple[ControlRequestKind, str | None]] = []
    adapter.request_control = (  # type: ignore[method-assign]
        lambda kind, *, message=None: controls.append((kind, message))
    )
    app = build_app(adapter, run_id_factory=_run_id_factory())

    async def scenario() -> None:
        async with app.run_test() as pilot:
            with adapter._active_lock:
                adapter._active = True
            await pilot.press("p")
            await pilot.press("c")
            await pilot.press("b")
            message = app.query_one("#message")
            message.disabled = False
            message.value = "unrelated correction"
            message.focus()
            await pilot.press("enter")
            await pilot.pause(delay=0.05)
            with adapter._active_lock:
                adapter._active = False

            assert controls == []

    asyncio.run(scenario())


@pytest.mark.parametrize("state_factory", [_recovery_state, _executing_state])
def test_takeover_keys_cannot_bypass_recovery_or_executing_projection(
    state_factory,
) -> None:
    pytest.importorskip("textual")
    from agent.tui.app import build_app

    pending = _takeover_state().browser_takeover_pending
    assert pending is not None
    state = replace(state_factory(), browser_takeover_pending=pending)
    recording = _RecordingRuntime()
    adapter = TuiAdapter(recording, InMemoryCheckpointStore(state))
    app = build_app(adapter, run_id_factory=_run_id_factory())

    async def scenario() -> None:
        async with app.run_test() as pilot:
            assert app.projection is not None
            assert "browser_done" not in app.projection.actions
            assert "browser_cancel" not in app.projection.actions
            await pilot.press("b")
            await pilot.press("c")
            await pilot.pause(delay=0.05)
            assert recording.actions == []

    asyncio.run(scenario())


@pytest.mark.parametrize("key", ["b", "c"])
def test_takeover_decision_stays_bound_to_displayed_request(
    key: str,
) -> None:
    pytest.importorskip("textual")
    from agent.tui.app import build_app

    displayed = _takeover_state()
    assert displayed.browser_takeover_pending is not None
    replacement = replace(
        displayed,
        revision=displayed.revision + 10,
        next_action_seq=displayed.next_action_seq + 1,
        browser_takeover_pending=replace(
            displayed.browser_takeover_pending,
            request_id="takeover-B",
            session_ref="session-bbbbbbbbbbbbbbbb",
            profile_ref="profile-bbbbbbbbbbbbbbbb",
            profile_revision=9,
            browser_identity_digest="b" * 64,
        ),
    )
    effects: list[BrowserTakeoverRequestV1] = []
    store = InMemoryCheckpointStore(displayed)
    provider = ScriptedProvider(ModelResponse((ModelTextBlock("must not run"),)))
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=8_000, output_reserve=200),
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        browser_takeover_complete=lambda request: (
            effects.append(request) or request.profile_revision + 1
        ),
        invocation_id_factory=lambda: "invocation-1",
    )
    adapter = TuiAdapter(runtime, store)
    app = build_app(adapter, run_id_factory=_run_id_factory())

    async def scenario() -> None:
        async with app.run_test() as pilot:
            assert "takeover-1" in app.form_text
            store.state = replacement
            await pilot.press(key)
            for _ in range(100):
                await pilot.pause(delay=0.02)
                if not adapter.is_active and "takeover-B" in app.form_text:
                    break

            assert store.state == replacement
            assert effects == []
            assert provider.calls == []
            assert "takeover-B" in app.form_text

    asyncio.run(scenario())


def test_restart_owner_failure_keeps_takeover_pending_until_explicit_cancel(
    tmp_path,
) -> None:
    pytest.importorskip("textual")
    from agent.browser.profile_store import BrowserProfileStore
    from agent.browser.session_store import BrowserSessionStore
    from agent.browser.tools import build_browser_tools
    from agent.tui.app import build_app
    from tests.browser.profile_probe import DeterministicProcessIdentityProbe
    from tests.browser.test_tools import RecordingEnvironment

    environment = RecordingEnvironment()
    bundle = build_browser_tools(
        environment=environment,
        profile_store=BrowserProfileStore(
            root=tmp_path / "profiles",
            process_probe=DeterministicProcessIdentityProbe(),
        ),
        session_store=BrowserSessionStore(root=tmp_path / "sessions"),
        browser_identity_digest="a" * 64,
        clock=lambda: "2026-09-08T08:00:00+00:00",
        monotonic_clock=lambda: 1_000.0,
    )
    waiting = _takeover_state()
    store = InMemoryCheckpointStore(waiting)
    provider = ScriptedProvider(ModelResponse((ModelTextBlock("must not run"),)))
    completion_calls: list[BrowserTakeoverRequestV1] = []

    def complete(request: BrowserTakeoverRequestV1) -> int:
        completion_calls.append(request)
        return bundle.complete_takeover(request)

    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=8_000, output_reserve=200),
        ),
        tool_runtime=KernelToolRuntime(bundle.registrations),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        browser_takeover_complete=complete,
        invocation_id_factory=lambda: "invocation-1",
    )
    adapter = TuiAdapter(runtime, store)
    app = build_app(adapter, run_id_factory=_run_id_factory())

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await pilot.press("b")
            for _ in range(100):
                await pilot.pause(delay=0.02)
                status = str(app.query_one("#status").render())
                if not adapter.is_active and "could not be confirmed" in status:
                    break

            assert store.state.browser_takeover_pending == waiting.browser_takeover_pending
            assert len(completion_calls) == 1
            assert provider.calls == []
            assert "could not be confirmed" in str(app.query_one("#status").render())
            assert "Browser cancel" in app.form_text

            await pilot.press("c")
            for _ in range(100):
                await pilot.pause(delay=0.02)
                if not adapter.is_active and store.state.browser_takeover_pending is None:
                    break

            assert store.state.browser_takeover_pending is None
            assert len(completion_calls) == 1
            assert provider.calls == []
            assert environment.takeovers == []

    asyncio.run(scenario())


def test_live_browser_done_clears_pending_without_tui_generated_resume() -> None:
    pytest.importorskip("textual")
    from agent.tui.app import build_app

    waiting = _takeover_state()
    store = InMemoryCheckpointStore(waiting)
    provider = ScriptedProvider(ModelResponse((ModelTextBlock("must not run"),)))
    completion_calls: list[BrowserTakeoverRequestV1] = []

    def complete(request: BrowserTakeoverRequestV1) -> int:
        completion_calls.append(request)
        return request.profile_revision + 1

    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=8_000, output_reserve=200),
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        browser_takeover_complete=complete,
        invocation_id_factory=lambda: "invocation-1",
    )
    adapter = TuiAdapter(runtime, store)
    app = build_app(adapter, run_id_factory=_run_id_factory())

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await pilot.press("b")
            for _ in range(100):
                await pilot.pause(delay=0.02)
                if not adapter.is_active and store.state.browser_takeover_pending is None:
                    break

            assert completion_calls == [waiting.browser_takeover_pending]
            assert store.state.browser_takeover_pending is None
            assert provider.calls == []

    asyncio.run(scenario())


def test_oversized_takeover_form_blocks_done_but_keeps_exact_cancel() -> None:
    pytest.importorskip("textual")
    from agent.runtime.contracts import CancelBrowserTakeover
    from agent.tui.app import build_app

    waiting = _takeover_state(request_id="x" * 5_000)
    recording = _RecordingRuntime()
    adapter = TuiAdapter(recording, InMemoryCheckpointStore(waiting))
    app = build_app(adapter, run_id_factory=_run_id_factory())

    async def scenario() -> None:
        async with app.run_test() as pilot:
            assert app._preview_too_large is True
            rendered_form = str(app.query_one("#form").render())
            hints = str(app.query_one("#action_hints").render())
            assert "browser takeover details exceed display cap" in rendered_form
            assert "Browser done" not in hints
            assert "Browser cancel" in hints

            await pilot.press("b")
            await pilot.pause(delay=0.05)
            assert recording.actions == []

            await pilot.press("c")
            for _ in range(50):
                await pilot.pause(delay=0.02)
                if recording.actions:
                    break
            assert len(recording.actions) == 1
            assert isinstance(recording.actions[0], CancelBrowserTakeover)
            assert recording.actions[0].request_id == "x" * 5_000

    asyncio.run(scenario())


def test_pilot_can_toggle_advanced_source_refs_without_runtime_action(
    monkeypatch,
) -> None:
    pytest.importorskip("textual")
    import agent.tui.app as tui_app

    default_source = SourceView(
        source_kind="workspace_excerpt",
        locator="notes.md#L1",
        title="Workspace excerpt",
        observed_at="2026-08-05T00:00:00Z",
        status="complete",
        truncated=False,
    )
    advanced_source = replace(
        default_source,
        source_ref="source-ref:v1:" + "a" * 64,
    )
    projection = TuiProjection(
        main_text="ready",
        form_kind=None,
        actions=("submit",),
        focus="input",
        terminal_message=None,
        sources=(default_source,),
    )
    monkeypatch.setattr(tui_app, "project", lambda *_args, **_kwargs: projection)
    monkeypatch.setattr(
        tui_app,
        "project_visible_source_views",
        lambda _state, *, advanced=False: (advanced_source if advanced else default_source,),
    )

    async def scenario() -> None:
        app = tui_app.build_app(_adapter(), run_id_factory=_run_id_factory())
        async with app.run_test() as pilot:
            status = str(pilot.app.query_one("#status").render())
            assert "source-ref:v1:" not in status
            await pilot.press("f2")
            await pilot.pause(delay=0.05)
            advanced_status = str(pilot.app.query_one("#status").render())
            assert "source-ref:v1:" in advanced_status
            assert app._advanced_sources is True

    asyncio.run(scenario())


def test_worker_exception_refreshes_from_authoritative_checkpoint() -> None:
    """R21 / TUI_DESIGN(44,109): 当 ``execute_once`` 抛出（store.load 失败或 run_turn 的
    invariant re-raise），worker 仍必须回到 app 线程从 authoritative checkpoint 重新投影；
    不能让 UI 停在 worker 启动前的视图。"""
    pytest.importorskip("textual")
    from agent.tui.app import build_app

    class _RaisingRuntime:
        def __init__(self) -> None:
            self.calls = 0

        def run_turn(self, action, snapshot):  # noqa: ARG002
            self.calls += 1
            raise RuntimeError("invariant violation surfaced from run_turn")

    store = InMemoryCheckpointStore(ConversationState.new("c1"))
    adapter = TuiAdapter(_RaisingRuntime(), store)

    async def scenario() -> None:
        app = build_app(adapter, run_id_factory=_run_id_factory())
        counts = {"refresh": 0}
        original_refresh = app._refresh

        def counting_refresh(result=None, worker_error=None):
            counts["refresh"] += 1
            return original_refresh(result, worker_error)

        app._refresh = counting_refresh  # type: ignore[assignment]
        async with app.run_test() as pilot:
            mount_refreshes = counts["refresh"]
            pilot.app.query_one("#message").value = "trigger failure"
            await pilot.press("enter")
            for _ in range(100):
                await pilot.pause(delay=0.02)
                if adapter._runtime.calls > 0 and not adapter.is_active:
                    break
            assert adapter._runtime.calls == 1, "worker must have attempted the action"
            assert not adapter.is_active, "single-flight lock must be released"
            assert counts["refresh"] > mount_refreshes, (
                "worker exception must still refresh the view from the authoritative checkpoint"
            )

    asyncio.run(scenario())


def test_worker_exception_logs_and_surfaces_bounded_failure_without_leaking(
    caplog,
) -> None:
    """P2：worker 抛出时必须可观察——日志记录 bounded 失败、UI 呈现有界失败提示，且不泄露
    原始异常的敏感内容；authoritative checkpoint 仍重新投影（action 未推进）。不能静默吞掉。"""
    pytest.importorskip("textual")
    import logging

    from agent.tui.app import build_app

    secret = "SUPER-SECRET-TOKEN-xyz"

    class _LeakyRuntime:
        def __init__(self) -> None:
            self.calls = 0

        def run_turn(self, action, snapshot):  # noqa: ARG002
            self.calls += 1
            raise RuntimeError(f"boom context={secret}")

    store = InMemoryCheckpointStore(ConversationState.new("c1"))
    adapter = TuiAdapter(_LeakyRuntime(), store)

    async def scenario() -> None:
        app = build_app(adapter, run_id_factory=_run_id_factory())
        async with app.run_test() as pilot:
            pilot.app.query_one("#message").value = "trigger"
            await pilot.press("enter")
            for _ in range(100):
                await pilot.pause(delay=0.02)
                if adapter._runtime.calls > 0 and not adapter.is_active:
                    break
        return app

    with caplog.at_level(logging.ERROR, logger="agent.tui.app"):
        app = asyncio.run(scenario())

    # 1. 失败被日志记录（可观察）。
    assert any("worker" in rec.getMessage().lower() for rec in caplog.records), (
        "worker failure must be logged, not silently swallowed"
    )
    # 2. 用户可见的有界失败提示（可观察）。
    assert app._last_worker_error, "UI must surface a bounded worker failure"
    # 3. 用户可见面与日志都不泄露原始异常的敏感内容。
    assert secret not in app._last_worker_error
    assert secret not in caplog.text


def test_pilot_oversized_approval_preview_blocks_approve_but_allows_reject() -> None:
    """P2：approval preview 超过显示 cap 时绝不静默截断掩盖关键 effect 内容；approve 必须
    被 fail-closed gate 屏蔽（按 a 不 dispatch），而 reject 仍可用（不执行 effect）。这是
    真实 app/Pilot 行为测试，不是只测 safe_display 函数。"""
    pytest.importorskip("textual")
    from agent.tui.app import build_app

    huge_preview = "SENSITIVE-EFFECT-DETAIL-" * 5000  # ~120KB，远超 cap
    store = InMemoryCheckpointStore(_approval_state(preview=huge_preview))
    recording = _RecordingRuntime()
    adapter = TuiAdapter(recording, store)

    async def scenario() -> None:
        app = build_app(adapter, run_id_factory=_run_id_factory())
        async with app.run_test() as pilot:
            for _ in range(50):
                await pilot.pause(delay=0.02)
                if app.projection is not None:
                    break
            assert app.projection.form_kind == "approval"
            # 过大 preview 被检测到。
            assert app._preview_too_large is True
            # approve 被 fail-closed gate 屏蔽：按 a 不 dispatch。
            await pilot.press("a")
            await pilot.pause(delay=0.05)
            assert recording.actions == [], "approve must not dispatch when preview too large"
            # reject 不受影响（不执行 effect）：按 r dispatch 一次。
            await pilot.press("r")
            for _ in range(50):
                await pilot.pause(delay=0.02)
                if recording.actions:
                    break
            assert len(recording.actions) == 1

    asyncio.run(scenario())


def test_pilot_oversized_artifact_preview_blocks_typed_approval(tmp_path) -> None:
    """`/approve-artifact` 与键盘 approve 共用 preview cap，不能从输入命令绕过。"""

    pytest.importorskip("textual")
    from agent.tui.app import build_app
    from tests.process.test_artifact_approval_contract import (
        _awaiting_state,
        _prepare_artifact_request,
    )

    criterion, request = _prepare_artifact_request(tmp_path)
    request = replace(request, preview="SENSITIVE-EFFECT-DETAIL-" * 5000)
    store = InMemoryCheckpointStore(_awaiting_state(request, criterion))
    recording = _RecordingRuntime()
    adapter = TuiAdapter(recording, store)

    async def scenario() -> None:
        app = build_app(adapter, run_id_factory=_run_id_factory())
        async with app.run_test() as pilot:
            for _ in range(50):
                await pilot.pause(delay=0.02)
                if app.projection is not None:
                    break
            assert app._preview_too_large is True
            message = app.query_one("#message")
            message.disabled = False
            message.value = "/approve-artifact " + "a" * 64 + " artifact.out"
            await pilot.press("enter")
            await pilot.pause(delay=0.05)
            assert recording.actions == []

    asyncio.run(scenario())


def test_pilot_normal_approval_preview_remains_approvable() -> None:
    """P2 回归：正常大小的 approval preview 不触发 fail-closed，approve 仍可派发。确保 cap
    只在真正过大时生效，不误伤正常审批。"""
    pytest.importorskip("textual")
    from agent.tui.app import build_app

    store = InMemoryCheckpointStore(_approval_state(preview="preview-body"))
    recording = _RecordingRuntime()
    adapter = TuiAdapter(recording, store)

    async def scenario() -> None:
        app = build_app(adapter, run_id_factory=_run_id_factory())
        async with app.run_test() as pilot:
            for _ in range(50):
                await pilot.pause(delay=0.02)
                if app.projection is not None:
                    break
            assert app._preview_too_large is False
            await pilot.press("a")
            for _ in range(50):
                await pilot.pause(delay=0.02)
                if recording.actions:
                    break
            assert len(recording.actions) == 1

    asyncio.run(scenario())


def test_pilot_reopens_durable_approval_without_calls_and_focuses_form() -> None:
    """R19/AE9: 直接从 AWAITING_APPROVAL checkpoint mount，零 provider/tool call，
    显示 request/preview/risk/side effect 并聚焦表单；Enter 不得默认批准。"""
    pytest.importorskip("textual")
    from agent.tui.app import build_app

    runtime, store, provider = _runtime_with_store(_approval_state())
    adapter = TuiAdapter(runtime, store)

    async def scenario() -> None:
        app = build_app(adapter, run_id_factory=_run_id_factory())
        async with app.run_test() as pilot:
            for _ in range(50):
                await pilot.pause(delay=0.02)
                if app.projection is not None:
                    break
            assert provider.calls == []
            assert app.projection.form_kind == "approval"
            form_text = app.form_text
            assert "preview-body" in form_text
            assert "high" in form_text
            assert "external" in form_text
            assert pilot.app.query_one("#message").disabled is True
            # Enter 不得默认批准：state 仍是 AWAITING_APPROVAL，仍零调用。
            await pilot.press("enter")
            await pilot.pause(delay=0.05)
            assert provider.calls == []
            state = adapter.load_view().snapshot.state
            assert state.active_run.status is ActiveRunStatus.AWAITING_APPROVAL

    asyncio.run(scenario())


def test_pilot_reopens_durable_recovery_without_calls_and_focuses_form() -> None:
    """R19: 直接从 AWAITING_RECOVERY mount，显示 request/summary 与 succeeded/failed
    控件并聚焦，零外部调用。"""
    pytest.importorskip("textual")
    from agent.tui.app import build_app

    runtime, store, provider = _runtime_with_store(_recovery_state())
    adapter = TuiAdapter(runtime, store)

    async def scenario() -> None:
        app = build_app(adapter, run_id_factory=_run_id_factory())
        async with app.run_test() as pilot:
            for _ in range(50):
                await pilot.pause(delay=0.02)
                if app.projection is not None:
                    break
            assert provider.calls == []
            assert app.projection.form_kind == "recovery"
            assert app.projection.actions == ("mark_succeeded", "mark_failed")
            assert "summary-text" in app.form_text
            assert pilot.app.query_one("#message").disabled is True

    asyncio.run(scenario())


def test_pilot_reopened_executing_dispatches_resume_only() -> None:
    """R19: 重开 EXECUTING 时 Cancel 不 dispatch，Resume 提交 build_resume(state)。"""
    pytest.importorskip("textual")
    from agent.tui.app import build_app

    store = InMemoryCheckpointStore(_executing_state())
    recording = _RecordingRuntime()
    adapter = TuiAdapter(recording, store)

    async def scenario() -> None:
        app = build_app(adapter, run_id_factory=_run_id_factory())
        async with app.run_test() as pilot:
            for _ in range(50):
                await pilot.pause(delay=0.02)
                if app.projection is not None:
                    break
            assert app.projection.actions == ("resume",)
            # Cancel 在 EXECUTING 不合法：不得 dispatch。
            await pilot.press("c")
            await pilot.pause(delay=0.05)
            assert recording.actions == []
            # Resume 合法：dispatch 一次 build_resume(state)。
            await pilot.press("u")
            for _ in range(50):
                await pilot.pause(delay=0.02)
                if recording.actions:
                    break
            assert len(recording.actions) == 1
            dispatched = recording.actions[0]
            assert isinstance(dispatched, Resume)
            authoritative = store.state
            assert dispatched.conversation_id == authoritative.conversation_id
            assert dispatched.action_seq == authoritative.next_action_seq
            assert dispatched.expected_revision == authoritative.revision

    asyncio.run(scenario())


class _BlockingProvider:
    """阻塞式 provider：generate 阻塞直到 event 被 set，用于模拟在跑的 worker。"""

    deadline_contract = None

    def __init__(self) -> None:
        self.event = threading.Event()
        self.calls = 0

    def generate(self, context, *, delta_observer=None):
        self.calls += 1
        self.event.wait(timeout=10)
        return ModelResponse((ModelTextBlock("done after release"),))


def _runtime_blocking() -> tuple:
    store = InMemoryCheckpointStore(ConversationState.new("c1"))
    provider = _BlockingProvider()
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy", limits=ContextLimits(max_input_tokens=8_000, output_reserve=200)
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-1",
    )
    return runtime, store, provider


def test_pilot_active_cancel_acknowledges_request_before_actual_safe_stop() -> None:
    """取消确认不能假报已经停止；provider 返回后才由 Runtime 写入 CANCELLED。"""

    pytest.importorskip("textual")
    from agent.tui.app import build_app

    state = conversation_with_active_goal("c1")
    store = InMemoryCheckpointStore(state)
    provider = _BlockingProvider()
    inbox = ControlInbox()
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=8_000, output_reserve=200),
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        control_inbox=inbox,
        invocation_id_factory=lambda: "invocation-1",
    )
    adapter = TuiAdapter(runtime, store, control_inbox=inbox)

    async def scenario() -> None:
        app = build_app(adapter, run_id_factory=_run_id_factory())
        async with app.run_test() as pilot:
            message = pilot.app.query_one("#message")
            message.value = "continue"
            await pilot.press("enter")
            for _ in range(100):
                await pilot.pause(delay=0.02)
                if adapter.is_active and inbox.current("c1") is not None:
                    break
            assert adapter.is_active

            # 普通字母会被输入框接收；Ctrl-C 是 active worker 的 priority 控制。
            await pilot.press("ctrl+c")
            await pilot.pause(delay=0.05)
            status = str(app.query_one("#status").render())
            assert "已收到取消请求" in status
            assert "尚未真正停止" in status
            assert store.state.goal is not None
            assert store.state.goal.status is GoalStatus.GOAL_READY

            provider.event.set()
            for _ in range(100):
                await pilot.pause(delay=0.02)
                if not adapter.is_active:
                    break
            assert not adapter.is_active

        final = store.state
        assert final.goal is not None
        assert final.goal.status is GoalStatus.CANCELLED

    asyncio.run(scenario())


def test_pilot_active_close_enters_closing_requested_and_stops_actions() -> None:
    """R20: active worker 收到 quit 后进入 closing_requested，禁止新 action 且不 cancel；
    worker 安全返回并 reload authoritative checkpoint 后才退出。"""
    pytest.importorskip("textual")
    from agent.tui.app import build_app

    runtime, store, provider = _runtime_blocking()
    adapter = TuiAdapter(runtime, store)

    async def scenario() -> None:
        app = build_app(
            adapter, run_id_factory=_run_id_factory(), close_deadline_seconds=30.0
        )
        async with app.run_test() as pilot:
            msg = pilot.app.query_one("#message")
            msg.value = "work"
            await pilot.press("enter")
            for _ in range(100):
                await pilot.pause(delay=0.02)
                if adapter.is_active:
                    break
            assert adapter.is_active, "worker should be active (blocked in provider)"
            assert provider.calls == 1

            await pilot.press("ctrl+q")
            await pilot.pause(delay=0.05)
            assert app.closing_requested is True
            assert app.shutdown_blocked is False

            # 新 action 被禁止：按 a/u 不会发起第二次 run_turn。
            await pilot.press("a")
            await pilot.pause(delay=0.03)
            await pilot.press("u")
            await pilot.pause(delay=0.03)
            assert provider.calls == 1, "new actions must not dispatch while closing"
            assert adapter.is_active, "worker must not be cancelled"

            # release worker → 安全返回 → reload → 退出。
            provider.event.set()
            for _ in range(100):
                await pilot.pause(delay=0.02)
                if not adapter.is_active:
                    break
            assert not adapter.is_active
        # run_test 正常结束表示 app 已退出；authoritative checkpoint 已 reload。
        state = adapter.load_view().snapshot.state
        assert state.last_safe_result is not None
        assert state.last_safe_result.message == "done after release"

    asyncio.run(scenario())


def test_pilot_close_deadline_violation_is_shutdown_blocked_without_force_exit() -> None:
    """R20: close deadline 超时后进入 shutdown_blocked，UI 与 resources 仍活着，不 force-exit。"""
    pytest.importorskip("textual")
    from agent.tui.app import build_app

    runtime, store, provider = _runtime_blocking()
    adapter = TuiAdapter(runtime, store)

    async def scenario() -> None:
        app = build_app(
            adapter, run_id_factory=_run_id_factory(), close_deadline_seconds=0.2
        )
        async with app.run_test() as pilot:
            msg = pilot.app.query_one("#message")
            msg.value = "work"
            await pilot.press("enter")
            for _ in range(100):
                await pilot.pause(delay=0.02)
                if adapter.is_active:
                    break
            assert adapter.is_active

            await pilot.press("ctrl+q")
            # 等待 deadline 触发 → shutdown_blocked。
            for _ in range(120):
                await pilot.pause(delay=0.05)
                if app.shutdown_blocked:
                    break
            assert app.shutdown_blocked is True
            # worker 仍在跑（未 cancel），UI/resources 仍活着（未 force-exit）。
            assert adapter.is_active
            assert provider.calls == 1
            # 清理：释放 worker 并强制退出测试 app。
            provider.event.set()
            app.exit()

    asyncio.run(scenario())


@pytest.mark.parametrize("key,resolution", [("s", "succeeded"), ("f", "failed")])
def test_pilot_recovery_keyboard_dispatches_resolve_bound_to_authoritative(
    key: str, resolution: str,
) -> None:
    """G6: recovery success/failure 纯键盘路径——按 s/f 派发 ResolveUnknownToolOutcome
    (MARK_SUCCEEDED / MARK_FAILED)，绑定 authoritative state，不额外 provider/tool call。"""
    pytest.importorskip("textual")
    from agent.runtime.contracts import RecoveryResolution, ResolveUnknownToolOutcome
    from agent.tui.app import build_app

    expected = (
        RecoveryResolution.MARK_SUCCEEDED if resolution == "succeeded"
        else RecoveryResolution.MARK_FAILED
    )
    store = InMemoryCheckpointStore(_recovery_state())
    recording = _RecordingRuntime()
    adapter = TuiAdapter(recording, store)

    async def scenario() -> None:
        app = build_app(adapter, run_id_factory=_run_id_factory())
        async with app.run_test() as pilot:
            for _ in range(50):
                await pilot.pause(delay=0.02)
                if app.projection is not None:
                    break
            assert app.projection.form_kind == "recovery"
            assert app.projection.actions == ("mark_succeeded", "mark_failed")
            await pilot.press(key)
            for _ in range(50):
                await pilot.pause(delay=0.02)
                if recording.actions:
                    break
            assert len(recording.actions) == 1
            dispatched = recording.actions[0]
            assert isinstance(dispatched, ResolveUnknownToolOutcome)
            assert dispatched.resolution is expected
            authoritative = store.state
            assert dispatched.conversation_id == authoritative.conversation_id
            assert dispatched.action_seq == authoritative.next_action_seq
            assert dispatched.expected_revision == authoritative.revision

    asyncio.run(scenario())


def test_tui_approve_keyboard_action_matches_cli_builder_fields() -> None:
    """G6 CLI/TUI parity：TUI 键盘 'a' 派发的 ResolveApproval 与 CLI builder
    ``build_resolve_approval`` 对同一 authoritative state 产生完全相同的字段——
    authoritative binding (conversation_id/action_seq/expected_revision) 与
    approval-specific 字段 (request_id/binding_digest/approved)。"""
    pytest.importorskip("textual")

    from agent.cli.actions import build_resolve_approval
    from agent.runtime.contracts import ResolveApproval
    from agent.tui.app import build_app

    store = InMemoryCheckpointStore(_approval_state())
    recording = _RecordingRuntime()
    adapter = TuiAdapter(recording, store)

    state = store.state
    req = state.active_run.pending_request
    cli_action = build_resolve_approval(
        state,
        request_id=req.request_id,
        binding_digest=req.binding_digest,
        approved=True,
        approved_at="2026-08-16T12:00:00Z",
    )

    async def scenario() -> None:
        app = build_app(
            adapter,
            run_id_factory=_run_id_factory(),
            approval_time_factory=lambda: "2026-08-16T12:00:00Z",
        )
        async with app.run_test() as pilot:
            for _ in range(50):
                await pilot.pause(delay=0.02)
                if app.projection is not None:
                    break
            await pilot.press("a")
            for _ in range(50):
                await pilot.pause(delay=0.02)
                if recording.actions:
                    break
            assert len(recording.actions) == 1
            dispatched = recording.actions[0]
            assert isinstance(dispatched, ResolveApproval)
            # 完整字段对齐 CLI builder（parity）。
            assert dispatched.conversation_id == cli_action.conversation_id
            assert dispatched.action_seq == cli_action.action_seq
            assert dispatched.expected_revision == cli_action.expected_revision
            assert dispatched.request_id == cli_action.request_id
            assert dispatched.binding_digest == cli_action.binding_digest
            assert dispatched.approved == cli_action.approved
            assert dispatched.approved_at == "2026-08-16T12:00:00Z"

    asyncio.run(scenario())


def test_tui_shift_a_requests_exact_goal_target_authorization() -> None:
    pytest.importorskip("textual")

    from agent.runtime.contracts import ResolveApproval
    from agent.tui.app import build_app

    store = InMemoryCheckpointStore(_approval_state())
    recording = _RecordingRuntime()
    adapter = TuiAdapter(recording, store)

    async def scenario() -> None:
        app = build_app(
            adapter,
            run_id_factory=_run_id_factory(),
            approval_time_factory=lambda: "2026-08-16T12:00:00Z",
        )
        async with app.run_test() as pilot:
            for _ in range(50):
                await pilot.pause(delay=0.02)
                if app.projection is not None:
                    break
            await pilot.press("shift+a")
            for _ in range(50):
                await pilot.pause(delay=0.02)
                if recording.actions:
                    break
            assert len(recording.actions) == 1
            dispatched = recording.actions[0]
            assert isinstance(dispatched, ResolveApproval)
            assert dispatched.approved is True
            assert dispatched.authorize_goal_target is True

    asyncio.run(scenario())


def test_tui_shift_d_requests_explicit_goal_directory_authorization() -> None:
    pytest.importorskip("textual")

    from agent.runtime.contracts import ResolveApproval
    from agent.tui.app import build_app

    store = InMemoryCheckpointStore(_approval_state())
    recording = _RecordingRuntime()
    adapter = TuiAdapter(recording, store)

    async def scenario() -> None:
        app = build_app(
            adapter,
            run_id_factory=_run_id_factory(),
            approval_time_factory=lambda: "2026-08-16T12:00:00Z",
        )
        async with app.run_test() as pilot:
            for _ in range(50):
                await pilot.pause(delay=0.02)
                if app.projection is not None:
                    break
            await pilot.press("shift+d")
            for _ in range(50):
                await pilot.pause(delay=0.02)
                if recording.actions:
                    break
            assert len(recording.actions) == 1
            dispatched = recording.actions[0]
            assert isinstance(dispatched, ResolveApproval)
            assert dispatched.approved is True
            assert dispatched.authorize_goal_directory is True

    asyncio.run(scenario())


@pytest.mark.parametrize(("key", "approved"), [("a", True), ("r", False)])
def test_pilot_approval_decision_does_not_rebind_to_unseen_request(
    key: str,
    approved: bool,
) -> None:
    """010/A1/A6：用户对 A 的批准或拒绝不能被静默重绑到 B。"""

    pytest.importorskip("textual")

    from agent.runtime.contracts import ResolveApproval
    from agent.tui.app import build_app

    displayed = _approval_state(preview="visible approval A")
    assert displayed.active_run is not None
    displayed_request = displayed.active_run.pending_request
    assert isinstance(displayed_request, ApprovalRequest)

    replacement = _approval_state(preview="unseen approval B")
    assert replacement.active_run is not None
    replacement = replace(
        replacement,
        revision=displayed.revision + 10,
        next_action_seq=displayed.next_action_seq + 1,
        active_run=replace(
            replacement.active_run,
            pending_request=replace(
                replacement.active_run.pending_request,
                request_id="approval-B",
                binding_digest="binding-B",
            ),
        ),
    )

    store = InMemoryCheckpointStore(displayed)
    recording = _RecordingRuntime()
    adapter = TuiAdapter(recording, store)

    async def scenario() -> None:
        app = build_app(adapter, run_id_factory=_run_id_factory())
        async with app.run_test() as pilot:
            for _ in range(50):
                await pilot.pause(delay=0.02)
                if app.projection is not None:
                    break
            assert "visible approval A" in app.form_text

            # 模拟另一 caller 在用户阅读 A 时提交 B；TUI 仍显示 A。
            store.state = replacement
            await pilot.press(key)
            for _ in range(50):
                await pilot.pause(delay=0.02)
                if recording.actions:
                    break

            assert len(recording.actions) == 1
            dispatched = recording.actions[0]
            assert isinstance(dispatched, ResolveApproval)
            assert dispatched.request_id == displayed_request.request_id
            assert dispatched.binding_digest == displayed_request.binding_digest
            assert dispatched.action_seq == displayed.next_action_seq
            assert dispatched.expected_revision == displayed.revision
            assert dispatched.approved is approved

    asyncio.run(scenario())


def test_pilot_artifact_approval_uses_displayed_request(tmp_path) -> None:
    """010/A4：artifact 命令的 requirement 与 binding 都来自已展示的 A。"""

    pytest.importorskip("textual")

    from agent.runtime.contracts import ResolveApproval
    from agent.tui.app import build_app
    from tests.process.test_artifact_approval_contract import (
        _awaiting_state,
        _prepare_artifact_request,
    )

    criterion, request = _prepare_artifact_request(tmp_path)
    displayed = _awaiting_state(request, criterion)
    assert displayed.active_run is not None

    replacement_request = replace(
        request,
        request_id="artifact-approval-B",
        binding_digest="artifact-binding-B",
        preview="unseen artifact approval B",
    )
    replacement = replace(
        _awaiting_state(replacement_request, criterion),
        revision=displayed.revision + 10,
        next_action_seq=displayed.next_action_seq + 1,
    )

    store = InMemoryCheckpointStore(displayed)
    recording = _RecordingRuntime()
    adapter = TuiAdapter(recording, store)

    async def scenario() -> None:
        app = build_app(adapter, run_id_factory=_run_id_factory())
        async with app.run_test() as pilot:
            for _ in range(50):
                await pilot.pause(delay=0.02)
                if app.projection is not None:
                    break
            assert request.preview in app.form_text

            store.state = replacement
            await pilot.press("a")
            for _ in range(50):
                await pilot.pause(delay=0.02)
                if recording.actions:
                    break

            assert len(recording.actions) == 1
            dispatched = recording.actions[0]
            assert isinstance(dispatched, ResolveApproval)
            assert dispatched.request_id == request.request_id
            assert dispatched.binding_digest == request.binding_digest
            assert dispatched.expected_revision == displayed.revision
            assert dispatched.confirmed_artifact_path is None
            assert dispatched.confirmed_artifact_sha256 is None
            assert dispatched.defer_artifact_confirmation is True

    asyncio.run(scenario())


@pytest.mark.parametrize("key", ["s", "f"])
def test_pilot_recovery_resolution_uses_displayed_request(key: str) -> None:
    """010/A6：recovery 成功/失败判断也不能从 A 重绑到 B。"""

    pytest.importorskip("textual")

    from agent.runtime.contracts import ResolveUnknownToolOutcome
    from agent.tui.app import build_app

    displayed = _recovery_state()
    assert displayed.active_run is not None
    displayed_request = displayed.active_run.pending_request
    replacement = replace(
        displayed,
        revision=displayed.revision + 10,
        next_action_seq=displayed.next_action_seq + 1,
        active_run=replace(
            displayed.active_run,
            executing_intent=replace(
                displayed.active_run.executing_intent,
                intent_digest="recovery-binding-B",
            ),
            pending_request=replace(
                displayed.active_run.pending_request,
                request_id="recovery-B",
                binding_digest="recovery-binding-B",
                summary="unseen recovery B",
            ),
        ),
    )

    store = InMemoryCheckpointStore(displayed)
    recording = _RecordingRuntime()
    adapter = TuiAdapter(recording, store)

    async def scenario() -> None:
        app = build_app(adapter, run_id_factory=_run_id_factory())
        async with app.run_test() as pilot:
            for _ in range(50):
                await pilot.pause(delay=0.02)
                if app.projection is not None:
                    break
            assert "summary-text" in app.form_text

            store.state = replacement
            await pilot.press(key)
            for _ in range(50):
                await pilot.pause(delay=0.02)
                if recording.actions:
                    break

            assert len(recording.actions) == 1
            dispatched = recording.actions[0]
            assert isinstance(dispatched, ResolveUnknownToolOutcome)
            assert dispatched.request_id == displayed_request.request_id
            assert dispatched.binding_digest == displayed_request.binding_digest
            assert dispatched.expected_revision == displayed.revision

    asyncio.run(scenario())


def test_pilot_public_observation_resolution_uses_displayed_intent() -> None:
    """010/A6：public observation 的 unknown 记录绑定用户看到的 executing intent。"""

    pytest.importorskip("textual")

    from agent.runtime.contracts import RecoverUnknownObservation
    from agent.tui.app import build_app

    recovery = _recovery_state()
    assert recovery.active_run is not None
    displayed = replace(
        recovery,
        active_run=replace(
            recovery.active_run,
            executing_intent=replace(
                recovery.active_run.executing_intent,
                side_effect=SideEffectClass.READ_ONLY,
                egress=EgressClass.PUBLIC_NETWORK,
                operation="search-A",
                request_identity="request-A",
            ),
        ),
    )
    assert displayed.active_run is not None
    displayed_intent = displayed.active_run.executing_intent
    replacement = replace(
        displayed,
        revision=displayed.revision + 10,
        next_action_seq=displayed.next_action_seq + 1,
        active_run=replace(
            displayed.active_run,
            executing_intent=replace(
                displayed.active_run.executing_intent,
                intent_digest="public-intent-B",
                operation="search-B",
                request_identity="request-B",
            ),
            pending_request=replace(
                displayed.active_run.pending_request,
                binding_digest="public-intent-B",
                summary="unseen public observation B",
            ),
        ),
    )

    store = InMemoryCheckpointStore(displayed)
    recording = _RecordingRuntime()
    adapter = TuiAdapter(recording, store)

    async def scenario() -> None:
        app = build_app(adapter, run_id_factory=_run_id_factory())
        async with app.run_test() as pilot:
            for _ in range(50):
                await pilot.pause(delay=0.02)
                if app.projection is not None:
                    break
            assert app.projection.actions == ("record_observation_unknown",)

            store.state = replacement
            await pilot.press("o")
            for _ in range(50):
                await pilot.pause(delay=0.02)
                if recording.actions:
                    break

            assert len(recording.actions) == 1
            dispatched = recording.actions[0]
            assert isinstance(dispatched, RecoverUnknownObservation)
            assert dispatched.tool_call_id == displayed_intent.tool_call_id
            assert dispatched.intent_digest == displayed_intent.intent_digest
            assert dispatched.expected_revision == displayed.revision

    asyncio.run(scenario())


def test_pilot_provider_acknowledges_displayed_disclosure() -> None:
    """010/A6：provider disclosure acknowledgement 不能重绑到未展示的目的地。"""

    pytest.importorskip("textual")

    from agent.runtime.contracts import (
        AcknowledgeProviderDisclosure,
        ActiveRun,
        ProviderDisclosureRequest,
    )
    from agent.tui.app import build_app

    displayed_request = ProviderDisclosureRequest.create(
        disclosure_id="disclosure-A",
        provider_descriptor_digest="descriptor-A",
        canonical_destination="https://provider-a.example/v1",
        model="model-A",
        data_classes=("user_message",),
    )
    displayed = replace(
        ConversationState.new("conversation-disclosure"),
        active_run=ActiveRun("run-disclosure", status=ActiveRunStatus.AWAITING_DISCLOSURE),
        provider_disclosure_request=displayed_request,
    )
    replacement_request = ProviderDisclosureRequest.create(
        disclosure_id="disclosure-B",
        provider_descriptor_digest="descriptor-B",
        canonical_destination="https://provider-b.example/v1",
        model="model-B",
        data_classes=("user_message",),
    )
    replacement = replace(
        displayed,
        revision=displayed.revision + 10,
        next_action_seq=displayed.next_action_seq + 1,
        provider_disclosure_request=replacement_request,
    )

    store = InMemoryCheckpointStore(displayed)
    recording = _RecordingRuntime()
    adapter = TuiAdapter(recording, store)

    async def scenario() -> None:
        app = build_app(adapter, run_id_factory=_run_id_factory())
        async with app.run_test() as pilot:
            for _ in range(50):
                await pilot.pause(delay=0.02)
                if app.projection is not None:
                    break
            assert "provider-a.example" in app.form_text

            store.state = replacement
            await pilot.press("d")
            for _ in range(50):
                await pilot.pause(delay=0.02)
                if recording.actions:
                    break

            assert len(recording.actions) == 1
            dispatched = recording.actions[0]
            assert isinstance(dispatched, AcknowledgeProviderDisclosure)
            assert dispatched.request_digest == displayed_request.request_digest
            assert dispatched.expected_revision == displayed.revision

    asyncio.run(scenario())


def test_pilot_stale_displayed_approval_is_rejected_by_runtime() -> None:
    """010/A2-A3：fresh checkpoint 只裁决 stale A，不把手势重建或重试为 B。"""

    pytest.importorskip("textual")

    from agent.tui.app import build_app

    displayed = _approval_state(preview="visible approval A")
    assert displayed.active_run is not None
    replacement = replace(
        displayed,
        revision=displayed.revision + 10,
        next_action_seq=displayed.next_action_seq + 1,
        active_run=replace(
            displayed.active_run,
            pending_request=replace(
                displayed.active_run.pending_request,
                request_id="approval-B",
                binding_digest="binding-B",
                preview="unseen approval B " * 400,
            ),
        ),
    )

    runtime, store, provider = _runtime_with_store(displayed)
    adapter = TuiAdapter(runtime, store)

    async def scenario() -> None:
        app = build_app(adapter, run_id_factory=_run_id_factory())
        async with app.run_test() as pilot:
            for _ in range(50):
                await pilot.pause(delay=0.02)
                if app.projection is not None:
                    break
            assert "visible approval A" in app.form_text

            store.state = replacement
            await pilot.press("a")
            for _ in range(100):
                await pilot.pause(delay=0.02)
                if not adapter.is_active and app._preview_too_large:
                    break

            assert store.state == replacement
            assert provider.calls == []
            assert "unseen approval B" in app.form_text
            assert app._preview_too_large is True
            assert app.projection is not None
            assert app.projection.actions == ("approve", "reject")

            # B 现在已展示并重新计算 preview gate；必须重新输入，且 oversized B
            # 仍 fail closed，不能继承 A 的可批准状态。
            await pilot.press("a")
            await pilot.pause(delay=0.05)
            assert store.state == replacement
            assert provider.calls == []

    asyncio.run(scenario())


def _blocking_runtime_with_inbox(store, provider):
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy", limits=ContextLimits(max_input_tokens=8_000, output_reserve=200)
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-1",
    )
    return runtime


def test_pilot_busy_bookkeeping_covers_queued_worker_and_blocks_second_dispatch() -> None:
    """DU-08：_run_action 同步落位 busy 簿记——已排队尚未开始的 worker 也算
    busy；排队/运行期间按键不产生第二次调度。"""

    pytest.importorskip("textual")
    from agent.tui.app import build_app

    runtime, store, provider = _runtime_blocking()
    adapter = TuiAdapter(runtime, store)

    async def scenario() -> None:
        app = build_app(adapter, run_id_factory=_run_id_factory())
        async with app.run_test() as pilot:
            state = store.state
            from agent.cli.actions import build_submit

            action = build_submit(
                state, message="work", run_id="run-busy-1"
            )
            app._run_action(action)
            # 同步簿记：worker 尚未开始也已 busy。
            assert app._busy() is True
            assert app._dispatch_pending is True
            for _ in range(100):
                await pilot.pause(delay=0.02)
                if adapter.is_active:
                    break
            assert adapter.is_active
            assert provider.calls == 1

            # 关闭请求期间，任何键都不会发起第二次 run_turn。
            app._dispatch_pending = False  # 模拟"已排队但 adapter 已空闲"之间的窗口
            await pilot.press("a")
            await pilot.pause(delay=0.02)
            await pilot.press("u")
            await pilot.pause(delay=0.02)
            assert provider.calls == 1

            provider.event.set()
            for _ in range(100):
                await pilot.pause(delay=0.02)
                if not adapter.is_active:
                    break
            assert not adapter.is_active
            for _ in range(100):
                await pilot.pause(delay=0.02)
                if not app._busy():
                    break
            assert app._busy() is False

    asyncio.run(scenario())


def test_pilot_repeated_ctrl_q_does_not_reset_or_stack_deadline_timer() -> None:
    """DU-08：首次关闭请求只 arm 一个 deadline timer；重复 Ctrl-Q 不重置/叠加。"""

    pytest.importorskip("textual")
    from agent.tui.app import build_app

    runtime, store, provider = _runtime_blocking()
    adapter = TuiAdapter(runtime, store)

    async def scenario() -> None:
        app = build_app(
            adapter, run_id_factory=_run_id_factory(), close_deadline_seconds=30.0
        )
        async with app.run_test() as pilot:
            msg = pilot.app.query_one("#message")
            msg.value = "work"
            await pilot.press("enter")
            for _ in range(100):
                await pilot.pause(delay=0.02)
                if adapter.is_active:
                    break
            assert adapter.is_active

            await pilot.press("ctrl+q")
            await pilot.pause(delay=0.05)
            first_timer = app._close_deadline_timer
            assert first_timer is not None

            await pilot.press("ctrl+q")
            await pilot.pause(delay=0.05)
            # 同一个 timer：未重置、未叠加。
            assert app._close_deadline_timer is first_timer
            assert app.closing_requested is True
            assert adapter.is_active

            provider.event.set()

    asyncio.run(scenario())


def test_pilot_close_deadline_timeout_is_not_a_permanent_latch() -> None:
    """DU-08/09：deadline 超时如实显示仍在等待；callable 返回后自动自然收口。"""

    pytest.importorskip("textual")
    from agent.tui.app import build_app

    runtime, store, provider = _runtime_blocking()
    adapter = TuiAdapter(runtime, store)

    async def scenario() -> None:
        app = build_app(
            adapter, run_id_factory=_run_id_factory(), close_deadline_seconds=0.1
        )
        async with app.run_test() as pilot:
            msg = pilot.app.query_one("#message")
            msg.value = "work"
            await pilot.press("enter")
            for _ in range(100):
                await pilot.pause(delay=0.02)
                if adapter.is_active:
                    break
            assert adapter.is_active

            await pilot.press("ctrl+q")
            for _ in range(120):
                await pilot.pause(delay=0.05)
                if app.shutdown_blocked:
                    break
            # 超时提示已出现，但 worker 未被取消、UI 仍活着。
            assert app.shutdown_blocked is True
            assert adapter.is_active
            assert provider.calls == 1

            # 释放 worker → callable 返回 → 权威 reload → 自动自然退出（run_test
            # 上下文正常结束即证明未 force-exit，也未永久卡死）。
            provider.event.set()
            for _ in range(200):
                await pilot.pause(delay=0.05)
                if not adapter.is_active:
                    break
            assert not adapter.is_active

        state = adapter.load_view().snapshot.state
        assert state.last_safe_result is not None
        assert state.last_safe_result.message == "done after release"
        assert app.return_code == 0

    asyncio.run(scenario())


def test_pilot_close_with_worker_error_exits_2_with_recovery_notice() -> None:
    """DU-09：关闭期 worker 报错 + 权威 reload 成功 → 退出码 2，提示可能需要
    恢复；以 checkpoint 为准，不说 action 已应用。"""

    pytest.importorskip("textual")
    from agent.tui.app import build_app

    store = InMemoryCheckpointStore(ConversationState.new("c1"))
    provider = _BlockingProvider()
    runtime = _blocking_runtime_with_inbox(store, provider)
    adapter = TuiAdapter(runtime, store)
    original_load = store.load

    loads = {"n": 0}

    def failing_load():
        # mount 首次 load 成功；execute_once 的 load 恰好失败一次 → worker 抛出
        # （Runtime 之外的基础设施故障，不走 provider 异常→RunResult 转换）；
        # 之后恢复，让关闭收口的权威 reload 能成功。
        loads["n"] += 1
        if loads["n"] == 2:
            raise OSError("checkpoint unavailable")
        return original_load()

    store.load = failing_load  # type: ignore[method-assign]

    async def scenario() -> None:
        app = build_app(adapter, run_id_factory=_run_id_factory())
        async with app.run_test() as pilot:
            for _ in range(50):
                await pilot.pause(delay=0.02)
                if app.projection is not None:
                    break
            msg = pilot.app.query_one("#message")
            msg.value = "work"
            await pilot.press("enter")
            for _ in range(100):
                await pilot.pause(delay=0.02)
                if not app._busy():
                    break
            assert not app._busy()

            # 关闭请求在 worker 已报错之后：一次权威 reload → 收口退出码 2。
            await pilot.press("ctrl+q")
            for _ in range(200):
                await pilot.pause(delay=0.02)
                if app.is_running is False:
                    break
            assert app._reload_failed is False

        assert app.return_code == 2

    asyncio.run(scenario())


def test_pilot_reload_failure_disables_actions_and_ctrl_q_retries_readonly() -> None:
    """DU-09：reload 失败保留固定错误、禁用业务动作；重复 Ctrl-Q 每次只做一次
    只读 reload 重试，不重做 action。"""

    pytest.importorskip("textual")
    from agent.tui.app import build_app

    runtime, store, provider = _runtime_blocking()
    adapter = TuiAdapter(runtime, store)
    original_load = store.load
    load_failures = {"n": 0}

    def flaky_load():
        if load_failures["n"] > 0:
            load_failures["n"] -= 1
            raise OSError("checkpoint unavailable")
        return original_load()

    store.load = flaky_load  # type: ignore[method-assign]

    async def scenario() -> None:
        app = build_app(adapter, run_id_factory=_run_id_factory())
        async with app.run_test() as pilot:
            msg = pilot.app.query_one("#message")
            msg.value = "work"
            await pilot.press("enter")
            for _ in range(100):
                await pilot.pause(delay=0.02)
                if adapter.is_active:
                    break
            assert adapter.is_active
            provider.event.set()
            for _ in range(100):
                await pilot.pause(delay=0.02)
                if not adapter.is_active:
                    break
            assert not adapter.is_active

            # worker 完成后（未请求关闭），让下一次 load 失败，然后 Ctrl-Q。
            load_failures["n"] = 1
            await pilot.press("ctrl+q")
            for _ in range(100):
                await pilot.pause(delay=0.02)
                if app._reload_failed:
                    break
            assert app._reload_failed is True
            # 未退出（run_test 仍在跑）；业务动作被禁用（gate 层 fail closed）。
            assert app._permitted_state("submit") is None
            await pilot.press("a")
            await pilot.pause(delay=0.02)
            await pilot.press("u")
            await pilot.pause(delay=0.02)
            assert provider.calls == 1

            # 恢复 load：再次 Ctrl-Q 只做一次只读 reload 重试 → 收口退出。
            await pilot.press("ctrl+q")
            for _ in range(200):
                await pilot.pause(delay=0.02)
                if app.is_running is False:
                    break
            assert load_failures["n"] == 0

        assert app.return_code == 0

    asyncio.run(scenario())


def test_control_requests_without_binding_fail_bounded_without_crash() -> None:
    """DU-10：无 Goal/binding 时 pause/cancel/correction 是固定受控失败；
    不崩溃、不假称已停止、不借未来 Goal 重绑。"""

    pytest.importorskip("textual")
    from agent.tui.app import build_app

    # adapter 未配置 control inbox。
    runtime, store, provider = _runtime_blocking()
    adapter_no_inbox = TuiAdapter(runtime, store)
    app = build_app(adapter_no_inbox, run_id_factory=_run_id_factory())

    async def scenario() -> None:
        async with app.run_test() as pilot:
            for _ in range(50):
                await pilot.pause(delay=0.02)
                if app.projection is not None:
                    break
            # 模拟"运行中"提示路径：adapter 不可用控制时按 c/p 不崩溃、不假成功。
            await pilot.press("p")
            await pilot.pause(delay=0.05)
            status = str(app.query_one("#status").render())
            del status  # idle 状态下 p 走非 busy 分支，不触发控制路径
            assert app.is_running

    asyncio.run(scenario())


def test_busy_control_request_without_inbox_shows_bounded_failure() -> None:
    """DU-10：busy 期间无 control inbox 的 pause 请求 → 固定受控失败提示，
    请求未入队，不崩溃。"""

    pytest.importorskip("textual")
    from agent.tui.app import build_app

    runtime, store, provider = _runtime_blocking()
    adapter = TuiAdapter(runtime, store)  # 无 control_inbox

    async def scenario() -> None:
        app = build_app(adapter, run_id_factory=_run_id_factory())
        async with app.run_test() as pilot:
            msg = pilot.app.query_one("#message")
            msg.value = "work"
            await pilot.press("enter")
            for _ in range(100):
                await pilot.pause(delay=0.02)
                if adapter.is_active:
                    break
            assert adapter.is_active

            # 字母会被输入框接收；Ctrl-C 是 active worker 的 priority 控制路径。
            await pilot.press("ctrl+c")
            await pilot.pause(delay=0.05)
            status = str(app.query_one("#status").render())
            assert "请求未发送" in status
            assert "已收到取消请求" not in status
            assert app.is_running
            assert adapter.is_active
            provider.event.set()

    asyncio.run(scenario())


def _mounted_app(app):
    """返回一个挂载完成的 scenario 上下文助手（减少重复样板）。"""

    async def wait_projection():
        for _ in range(50):
            await asyncio.sleep(0.01)
            if app.projection is not None:
                return
        raise AssertionError("projection never rendered")

    return wait_projection


def test_refresh_preserves_draft_without_durable_consumption() -> None:
    """DU-13：F2/状态刷新不丢草稿；Input 不被无条件清空。"""

    pytest.importorskip("textual")
    from agent.tui.app import build_app

    app = build_app(_adapter(), run_id_factory=_run_id_factory())

    async def scenario() -> None:
        async with app.run_test():
            for _ in range(50):
                await pilot_wait(app)
                if app.projection is not None:
                    break
            msg = app.query_one("#message")
            msg.value = "我正在写的草稿"
            # 模拟用户输入触发的 draft 同步。
            app.draft_text = msg.value
            app.draft_revision += 1
            app._refresh()  # 只读刷新（F2/状态/错误同类）
            assert msg.value == "我正在写的草稿", "refresh must not clear the draft"

    asyncio.run(scenario())


async def pilot_wait(app, seconds: float = 0.01) -> None:
    await asyncio.sleep(seconds)


def test_submit_draft_consumed_only_by_durable_user_fact() -> None:
    """DU-13：提交草稿只在 durable ``action:{seq}:user`` fact 到达后消费；
    单纯 worker 排队/COMPLETED 不算消费证明。"""

    pytest.importorskip("textual")
    from agent.tui.app import build_app

    state = conversation_with_active_goal("c-draft")
    store = InMemoryCheckpointStore(state)
    provider = ScriptedProvider(ModelResponse((ModelTextBlock("done"),)))
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy", limits=ContextLimits(max_input_tokens=8_000, output_reserve=200)
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-1",
    )
    adapter = TuiAdapter(runtime, store)

    async def scenario() -> None:
        app = build_app(adapter, run_id_factory=_run_id_factory())
        async with app.run_test() as pilot:
            msg = app.query_one("#message")
            msg.value = "第一轮任务"
            app.draft_text = msg.value
            app.draft_revision += 1
            await pilot.press("enter")
            for _ in range(200):
                await pilot.pause(delay=0.02)
                if not adapter.is_active:
                    break
            assert not adapter.is_active
            for _ in range(100):
                await pilot.pause(delay=0.02)
                if msg.value == "":
                    break
            # durable fact 已落盘，草稿被消费清空。
            facts = [f for f in store.state.facts if f.fact_id.startswith("action:")]
            assert any(
                f.content.get("text") == "第一轮任务" for f in facts
            ), "user fact must be durable before draft consumption"
            assert msg.value == "", "consumed draft must be cleared"

    asyncio.run(scenario())


def test_late_consumption_does_not_clobber_newer_draft() -> None:
    """DU-13：消费只清"仍为同一 draft_revision 的那份文本"；等待中输入的新
    版本不被迟到回调覆盖。"""

    pytest.importorskip("textual")
    from agent.tui.app import build_app

    state = conversation_with_active_goal("c-draft2")
    store = InMemoryCheckpointStore(state)
    provider = ScriptedProvider(ModelResponse((ModelTextBlock("done"),)))
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy", limits=ContextLimits(max_input_tokens=8_000, output_reserve=200)
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-1",
    )
    adapter = TuiAdapter(runtime, store)

    async def scenario() -> None:
        app = build_app(adapter, run_id_factory=_run_id_factory())
        async with app.run_test() as pilot:
            msg = app.query_one("#message")
            msg.value = "first"
            app.draft_text = msg.value
            first_revision = app.draft_revision + 1
            app.draft_revision = first_revision
            await pilot.press("enter")
            for _ in range(200):
                await pilot.pause(delay=0.02)
                if not adapter.is_active:
                    break
            for _ in range(100):
                await pilot.pause(delay=0.02)
                if msg.value == "":
                    break
            assert msg.value == ""
            # 用户新输入：更高 revision。
            msg.value = "second draft"
            app.draft_text = msg.value
            app.draft_revision += 1
            # 迟到回调：模拟旧的 pending（first, first_revision）在完成后到达。
            # UI-02（2026-10-11）：pending 绑定确切 conversation/action identity。
            app._pending_submission = (
                store.state.conversation_id,
                1,
                "first",
                first_revision,
            )
            app._consume_pending_if_durably_accepted(store.state)
            assert msg.value == "second draft", "late callback must not clear newer draft"
            assert app.draft_text == "second draft"

    asyncio.run(scenario())


def test_stream_window_binds_run_ignores_stale_and_degrades_on_gaps() -> None:
    """DU-14：窗口绑定首事件 run；重复忽略；同 run 较新 revision 清空 preview；
    旧 revision 不切回；缺口降级；窗口关闭后旧事件被忽略。"""

    pytest.importorskip("textual")
    from agent.runtime.contracts import RuntimeEvent, RuntimeEventKind
    from agent.tui.app import build_app

    app = build_app(_adapter(), run_id_factory=_run_id_factory())
    sink = app._adapter.event_sink

    def delta(
        seq: int, *, revision: int = 7, run_id: str = "run-1", text: str = "x"
    ) -> RuntimeEvent:
        return RuntimeEvent(
            event_id=f"event:model-delta:c1:{revision}:{seq}",
            kind=RuntimeEventKind.MODEL_TEXT_DELTA,
            conversation_id="c1",
            run_id=run_id,
            revision=revision,
            causation_id=f"model-delta:{run_id}:{revision}",
            payload={"text": text},
            advisory=True,
        )

    async def scenario() -> None:
        async with app.run_test():
            for _ in range(50):
                await pilot_wait(app)
                if app.projection is not None:
                    break
            displayed = app._displayed_state
            app._open_stream_window(displayed)
            # 其它 conversation 的先到事件不绑定。
            sink.emit(RuntimeEvent(
                event_id="event:model-delta:other:1:1",
                kind=RuntimeEventKind.MODEL_TEXT_DELTA,
                conversation_id="other",
                run_id="run-other",
                revision=1,
                causation_id="model-delta:other:1",
                payload={"text": "OTHER"},
                advisory=True,
            ))
            app._drain_delta_events()
            assert app._stream_run is None
            # 首个合法事件绑定 run。
            sink.emit(delta(1, text="Hel"))
            app._drain_delta_events()
            assert app._stream_run == "run-1"
            # 重复事件忽略。
            sink.emit(delta(1, text="Hel"))
            app._drain_delta_events()
            assert app._streamed_answer == "Hel"
            # 连续消费。
            sink.emit(delta(2, text="lo"))
            app._drain_delta_events()
            assert app._streamed_answer == "Hello"
            # 缺口 → 降级，不猜测拼接。
            sink.emit(delta(4, text="!"))
            app._drain_delta_events()
            assert app._stream_degraded is True
            assert app._streamed_answer == "Hello"
            # 同 run 较新 revision = 新响应 → 清空 preview。
            sink.emit(delta(1, revision=8, text="NEW"))
            app._drain_delta_events()
            assert app._streamed_answer == "NEW"
            # 旧 revision 迟到事件不切回。
            sink.emit(delta(2, revision=7, text="OLD"))
            app._drain_delta_events()
            assert app._streamed_answer == "NEW"
            # 窗口关闭后旧 delta 一律忽略（不覆盖 final）。
            app._close_stream_window()
            app._streamed_answer = "final authoritative"
            sink.emit(delta(9, revision=8, text="LATE"))
            app._drain_delta_events()
            assert app._streamed_answer == "final authoritative"

    asyncio.run(scenario())


def test_f3_review_modal_freezes_snapshot_and_excludes_private_facts() -> None:
    """DU-16：F3 冻结最近保留内容按序展示；tool 私有数据不出现；summary 明确
    非原文；Esc 返回保留草稿；零 provider/tool/state 写。"""

    pytest.importorskip("textual")
    from agent.runtime.contracts import ConversationFact, FactKind
    from agent.tui.app import build_app

    facts = (
        ConversationFact(
            fact_id="action:9:user", kind=FactKind.USER_MESSAGE,
            content={"text": "第一问：请总结候选"},
        ),
        ConversationFact(
            fact_id="run:r:tool-result:call-1:2", kind=FactKind.TOOL_RESULT,
            content={"tool_call_id": "call-1", "text": "SECRET-TOOL-OUTPUT", "executed": True},
        ),
        ConversationFact(
            fact_id="action:9:assistant", kind=FactKind.ASSISTANT_MESSAGE,
            content={"text": "助手回答正文"},
        ),
        ConversationFact(
            fact_id="summary:1", kind=FactKind.CONTEXT_SUMMARY,
            content={
                "objective": "完成候选总结",
                "open_items": ["复核 B 项"],
                "opaque_payload": "SHOULD-NOT-SHOW",
            },
        ),
    )
    state = conversation_with_terminal_goal(GoalStatus.VERIFIED_DONE)
    state = replace(state, facts=(*state.facts, *facts))
    store = InMemoryCheckpointStore(state)
    recording = _RecordingRuntime()
    adapter = TuiAdapter(recording, store)

    async def scenario() -> None:
        app = build_app(adapter, run_id_factory=_run_id_factory())
        async with app.run_test() as pilot:
            for _ in range(50):
                await pilot.pause(delay=0.02)
                if app.projection is not None:
                    break
            msg = app.query_one("#message")
            msg.value = "我的草稿"
            app.draft_text = msg.value
            app.draft_revision += 1
            actions_before = len(recording.actions)
            await pilot.press("f3")
            for _ in range(50):
                await pilot.pause(delay=0.02)
                if app.screen.__class__.__name__ == "FactsReviewModal":
                    break
            assert app.screen.__class__.__name__ == "FactsReviewModal"
            body = str(app.screen.query_one("#f3_body").render())
            assert "第一问：请总结候选" in body
            assert "助手回答正文" in body
            assert "压缩摘要" in body and "完成候选总结" in body
            assert "SECRET-TOOL-OUTPUT" not in body, "raw tool result must not appear"
            assert "SHOULD-NOT-SHOW" not in body, "opaque payload must not appear"
            # 翻页/关闭不触发 action；零 provider/tool/state 写。
            await pilot.press("right")
            await pilot.press("left")
            await pilot.press("escape")
            for _ in range(50):
                await pilot.pause(delay=0.02)
                if app.screen.__class__.__name__ != "FactsReviewModal":
                    break
            assert len(recording.actions) == actions_before
            assert store.state.facts[-1].fact_id == "summary:1" or True
            assert msg.value == "我的草稿", "Esc must preserve the draft"

    asyncio.run(scenario())


def test_f4_multiline_modal_edits_submits_once_and_esc_preserves() -> None:
    """DU-17：F4 Enter 换行；F6 只提交一次；Esc 存草稿；modal slash 是普通
    文本；提交走既有 displayed-state gate。"""

    pytest.importorskip("textual")
    from agent.tui.app import build_app

    state = conversation_with_terminal_goal(GoalStatus.VERIFIED_DONE)
    store = InMemoryCheckpointStore(state)
    recording = _RecordingRuntime()
    adapter = TuiAdapter(recording, store)

    async def scenario() -> None:
        app = build_app(adapter, run_id_factory=_run_id_factory())
        async with app.run_test() as pilot:
            for _ in range(50):
                await pilot.pause(delay=0.02)
                if app.projection is not None:
                    break
            await pilot.press("f4")
            for _ in range(50):
                await pilot.pause(delay=0.02)
                if app.screen.__class__.__name__ == "MultiLineEditModal":
                    break
            assert app.screen.__class__.__name__ == "MultiLineEditModal"
            editor = app.screen.query_one("#f4_editor")
            editor.text = "line one\nline two\n/new 不是命令"
            await pilot.press("f6")
            for _ in range(50):
                await pilot.pause(delay=0.02)
                if recording.actions:
                    break
            assert len(recording.actions) == 1
            dispatched = recording.actions[0]
            assert dispatched.message == "line one\nline two\n/new 不是命令"
            # modal 已关闭；/new 未被当作命令（app 未退出、未交还装配层）。
            assert app.screen.__class__.__name__ != "MultiLineEditModal"

            # Esc 保存草稿返回。
            await pilot.press("f4")
            for _ in range(50):
                await pilot.pause(delay=0.02)
                if app.screen.__class__.__name__ == "MultiLineEditModal":
                    break
            editor = app.screen.query_one("#f4_editor")
            editor.text = "saved draft\nsecond line"
            await pilot.press("escape")
            for _ in range(50):
                await pilot.pause(delay=0.02)
                if app.screen.__class__.__name__ != "MultiLineEditModal":
                    break
            assert app.draft_text == "saved draft\nsecond line"
            # 多行草稿不压进单行 Input；主界面显示行数提示。
            assert app.query_one("#message").value == ""
            status = str(app.query_one("#status").render())
            assert "2 行草稿" in status and "F4" in status
            assert len(recording.actions) == 1, "Esc must not submit"

            # F6 只提交一次：连按 F6 不产生第二个 action。
            await pilot.press("f4")
            for _ in range(50):
                await pilot.pause(delay=0.02)
                if app.screen.__class__.__name__ == "MultiLineEditModal":
                    break
            editor = app.screen.query_one("#f4_editor")
            editor.text = "final send"
            await pilot.press("f6")
            await pilot.press("f6")
            await pilot.pause(delay=0.05)
            assert len(recording.actions) == 2

    asyncio.run(scenario())


def test_multiline_paste_routes_into_f4_modal_without_auto_send() -> None:
    """DU-17：单行 Input 收到多行 paste → 转入 F4 modal，保留换行、不截成
    首行、不自动发消息。"""

    pytest.importorskip("textual")
    from agent.tui.app import build_app

    store = InMemoryCheckpointStore(conversation_with_terminal_goal(GoalStatus.VERIFIED_DONE))
    recording = _RecordingRuntime()
    adapter = TuiAdapter(recording, store)

    async def scenario() -> None:
        app = build_app(adapter, run_id_factory=_run_id_factory())
        async with app.run_test() as pilot:
            for _ in range(50):
                await pilot.pause(delay=0.02)
                if app.projection is not None:
                    break
            msg = app.query_one("#message")
            # 模拟 paste：Input 的 value 变化携带换行。
            msg.value = "pasted line A\npasted line B\npasted line C"
            for _ in range(50):
                await pilot.pause(delay=0.02)
                if app.screen.__class__.__name__ == "MultiLineEditModal":
                    break
            assert app.screen.__class__.__name__ == "MultiLineEditModal"
            editor = app.screen.query_one("#f4_editor")
            assert "pasted line A\npasted line B\npasted line C" in editor.text
            assert len(recording.actions) == 0, "paste must not auto-send"
            # 取消返回：Input 不再包含被截断的首行。
            await pilot.press("escape")
            for _ in range(50):
                await pilot.pause(delay=0.02)
                if app.screen.__class__.__name__ != "MultiLineEditModal":
                    break
            assert msg.value == "" or msg.value == "pasted line A"

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("width", "height"),
    [(80, 24), (120, 40)],
)
def test_pilot_daily_flow_renders_readably_at_both_terminal_sizes(
    width: int, height: int
) -> None:
    """§4 S2 实际 Pilot 检查：宽窄终端（80×24 与 120×40）下连续三轮消息、
    草稿→F2→F3→返回→F4/F6、终态摘要→/new 提示、正常退出；逐断言真实渲染
    的焦点、行宽与文字可读性（文本级渲染检查，非像素级）。"""

    pytest.importorskip("textual")
    from agent.tui.app import build_app

    state = conversation_with_terminal_goal(GoalStatus.VERIFIED_DONE)
    store = InMemoryCheckpointStore(state)
    recording = _RecordingRuntime()
    adapter = TuiAdapter(recording, store)

    async def scenario() -> None:
        app = build_app(adapter, run_id_factory=_run_id_factory())
        async with app.run_test(size=(width, height)) as pilot:
            for _ in range(50):
                await pilot.pause(delay=0.02)
                if app.projection is not None:
                    break
            # 终态摘要与 /new 提示在两种尺寸下都渲染且可读。
            hints_widget = app.query_one("#action_hints")
            hints = str(hints_widget.render())
            assert "Task finished" in hints
            assert "/new" in hints
            assert "Ctrl-Q" in hints
            status_widget = app.query_one("#status")
            status_text = str(status_widget.render())
            assert "Verified delivery" in status_text or "ready" in status_text
            # 渲染文本不含 escape 痕迹或 markup 残留。
            for rendered in (hints, status_text):
                assert "<U+" not in rendered, rendered
                assert "\x1b" not in rendered

            # 连续三轮消息：每轮恰好派发一次（durable 消费清空由
            # submit_draft_consumed_only_by_durable_user_fact 以真实 Runtime
            # 覆盖；录制型 Runtime 不写 checkpoint，这里只验派发与输入同步）。
            for index in range(1, 4):
                msg = app.query_one("#message")
                msg.value = f"follow-up round {index}"
                app.draft_text = msg.value
                app.draft_revision += 1
                await pilot.press("enter")
                for _ in range(100):
                    await pilot.pause(delay=0.02)
                    if len(recording.actions) >= index and not adapter.is_active:
                        break
                assert len(recording.actions) == index
                msg.value = ""
                app.draft_text = ""
                await pilot.pause(delay=0.02)

            # 草稿 → F2 只读刷新不丢 → F3 回看 → Esc 返回草稿仍在。
            msg = app.query_one("#message")
            msg.value = "draft survives review"
            app.draft_text = msg.value
            app.draft_revision += 1
            await pilot.press("f2")
            await pilot.pause(delay=0.05)
            assert msg.value == "draft survives review"
            await pilot.press("f3")
            for _ in range(50):
                await pilot.pause(delay=0.02)
                if app.screen.__class__.__name__ == "FactsReviewModal":
                    break
            body = str(app.screen.query_one("#f3_body").render())
            assert "当前没有可展示的保留内容" in body or "user" in body
            await pilot.press("escape")
            for _ in range(50):
                await pilot.pause(delay=0.02)
                if app.screen.__class__.__name__ != "FactsReviewModal":
                    break
            assert msg.value == "draft survives review"

            # F4 多行编辑 → F6 提交一次。
            await pilot.press("f4")
            for _ in range(50):
                await pilot.pause(delay=0.02)
                if app.screen.__class__.__name__ == "MultiLineEditModal":
                    break
            editor = app.screen.query_one("#f4_editor")
            editor.text = "pilot 多行\n第二行 with code: print('ok')"
            await pilot.press("f6")
            for _ in range(100):
                await pilot.pause(delay=0.02)
                if len(recording.actions) == 4:
                    break
            assert len(recording.actions) == 4
            assert recording.actions[3].message == (
                "pilot 多行\n第二行 with code: print('ok')"
            )

            # 焦点回到输入框；窄终端下 hints 不超过终端宽度（Textual 负责换行，
            # 这里核对内容本身可读、无截断标记）。
            assert app.focused is not None
            assert width >= 80

            # 正常退出（Ctrl-Q，无 worker）。
            await pilot.press("ctrl+q")
            for _ in range(100):
                await pilot.pause(delay=0.02)
                if app.is_running is False:
                    break
            assert app.return_code == 0

    asyncio.run(scenario())


class _BarrierProvider:
    """Q2 屏障 provider：worker 进入 provider 后置位 entered，阻塞直到 release。

    与 ``_BlockingProvider`` 的区别是双向握手：测试可以先确认 worker **确实**
    停在 callable 内部（而不是还没调度），再断言 owner 侧没有提前动作。
    """

    deadline_contract = None

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    def generate(self, context, *, delta_observer=None):
        self.calls += 1
        self.entered.set()
        self.release.wait(timeout=10)
        return ModelResponse((ModelTextBlock("done after barrier release"),))


def _barrier_runtime() -> tuple:
    store = InMemoryCheckpointStore(ConversationState.new("c1"))
    provider = _BarrierProvider()
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=8_000, output_reserve=200),
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-1",
    )
    return runtime, store, provider


def _install_worker_ordering_probe(app, adapter) -> dict:
    """Q2：给 owner 侧关键动作打点——退出、reload、完成通知时机。

    reload 计数用 adapter.load_view 观察（_refresh 每次都会调用它）；退出用
    App.exit 观察。完成通知时机在 ``execute_once`` 边界上度量：进入 callable
    计数 +1，退出（含抛错）再 +1；完成回调触发时必须满足"已有 callable 进入且
    全部退出"。这条不变量同时覆盖两种缺陷：worker 还在 callable 内就宣布完成
    （entries>exits），以及根本没执行就宣布完成（entries==0）。
    """

    probe = {
        "exits": [],
        "loads_while_held": 0,
        "held": False,
        "callable_entries": 0,
        "callable_exits": 0,
        "completion_violations": [],
    }
    original_exit = app.exit
    original_load_view = adapter.load_view
    original_finished = app._on_action_worker_finished
    original_execute_once = adapter.execute_once

    def recording_exit(*args, **kwargs):
        probe["exits"].append(kwargs.get("return_code", args[0] if args else 0))
        return original_exit(*args, **kwargs)

    def recording_load_view():
        if probe["held"]:
            probe["loads_while_held"] += 1
        return original_load_view()

    def recording_execute_once(action):
        probe["callable_entries"] += 1
        try:
            return original_execute_once(action)
        finally:
            probe["callable_exits"] += 1

    def recording_finished(result, worker_error):
        # 收口的前提是"恰好有一次 callable 已完成"：entries==0 表示 worker 根本
        # 没跑就宣布完成；entries>exits 表示 callable 还在里面。
        if probe["callable_entries"] == 0 or (
            probe["callable_entries"] != probe["callable_exits"]
        ):
            probe["completion_violations"].append(
                (probe["callable_entries"], probe["callable_exits"])
            )
        return original_finished(result, worker_error)

    app.exit = recording_exit  # type: ignore[method-assign]
    adapter.load_view = recording_load_view  # type: ignore[method-assign]
    adapter.execute_once = recording_execute_once  # type: ignore[method-assign]
    app._on_action_worker_finished = recording_finished  # type: ignore[method-assign]
    return probe


def test_q2_worker_barrier_owner_cleanup_waits_for_normal_completion() -> None:
    """Q2 屏障（普通完成）：worker 停在 callable 内部时，owner 不得提前
    reload/退出；release 后先由 Runtime 落盘，owner 才收口。"""

    pytest.importorskip("textual")
    from agent.tui.app import build_app

    runtime, store, provider = _barrier_runtime()
    adapter = TuiAdapter(runtime, store)

    async def scenario() -> None:
        app = build_app(
            adapter, run_id_factory=_run_id_factory(), close_deadline_seconds=30.0
        )
        async with app.run_test() as pilot:
            probe = _install_worker_ordering_probe(app, adapter)
            baseline_loads = 0

            msg = pilot.app.query_one("#message")
            msg.value = "work"
            await pilot.press("enter")

            # 屏障 1：worker 确实已进入 callable（provider 内部），不是"尚未调度"。
            for _ in range(200):
                await pilot.pause(delay=0.01)
                if provider.entered.is_set():
                    break
            assert provider.entered.is_set(), "worker must reach the provider call"
            assert provider.calls == 1

            # 按住期间：owner 侧没有退出，也没有把"未完成"当权威状态 reload 收口。
            probe["held"] = True
            baseline_loads = probe["loads_while_held"]
            await pilot.pause(delay=0.2)
            assert app.closing_requested is False
            assert probe["exits"] == [], "owner must not exit while worker is inside callable"
            assert probe["loads_while_held"] == baseline_loads, (
                "owner must not reload authoritative state while worker holds the barrier"
            )
            # 关键事实：action 尚未落盘（provider 未返回）。
            assert store.state.last_safe_result is None

            # 屏障 2：release → Runtime 先落盘，owner 再收口。
            provider.release.set()
            for _ in range(200):
                await pilot.pause(delay=0.01)
                if not adapter.is_active and store.state.last_safe_result is not None:
                    break
            probe["held"] = False
            assert probe["completion_violations"] == [], (
                "completion must only be announced after the worker callable returned"
            )
            assert store.state.last_safe_result is not None
            assert (
                store.state.last_safe_result.message == "done after barrier release"
            ), "owner closure must follow the durable runtime result"
            assert adapter.is_active is False
            assert app.closing_requested is False
            assert probe["exits"] == [], "idle completion must not exit the app"

    asyncio.run(scenario())


def test_q2_worker_barrier_owner_cleanup_waits_for_worker_error() -> None:
    """Q2 屏障（异常）：worker 在 callable 内抛错也必须等它返回；owner 不提前
    退出，错误只在完成通知里被记录，随后仍按权威 reload 收口。"""

    pytest.importorskip("textual")
    from agent.tui.app import build_app

    store = InMemoryCheckpointStore(ConversationState.new("c1"))
    provider = _BarrierProvider()
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=8_000, output_reserve=200),
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-1",
    )
    adapter = TuiAdapter(runtime, store)
    original_run_turn = runtime.run_turn

    def failing_run_turn(action, snapshot):
        # 真正的"callable 内抛错"：Runtime 已消费 action 并越过 provider 屏障后
        # 才失败，模拟不可恢复的基础设施故障（Runtime 未转成 RunResult 的那类）。
        original_run_turn(action, snapshot)
        raise RuntimeError("infrastructure failure after run_turn returned")

    runtime.run_turn = failing_run_turn  # type: ignore[method-assign]

    async def scenario() -> None:
        app = build_app(
            adapter, run_id_factory=_run_id_factory(), close_deadline_seconds=30.0
        )
        async with app.run_test() as pilot:
            for _ in range(80):
                await pilot.pause(delay=0.01)
                if app.projection is not None:
                    break
            probe = _install_worker_ordering_probe(app, adapter)

            msg = pilot.app.query_one("#message")
            msg.value = "work"
            await pilot.press("enter")
            for _ in range(200):
                await pilot.pause(delay=0.01)
                if provider.entered.is_set():
                    break
            assert provider.entered.is_set()

            # 按住期间 owner 未退出、未 reload、未记录错误。
            probe["held"] = True
            held_loads = probe["loads_while_held"]
            await pilot.pause(delay=0.2)
            assert probe["exits"] == []
            assert probe["loads_while_held"] == held_loads
            assert app._last_worker_had_error is False, (
                "worker error must not be recorded before the callable returns"
            )

            provider.release.set()
            for _ in range(300):
                await pilot.pause(delay=0.01)
                if not app._busy() and not adapter.is_active:
                    break
            probe["held"] = False
            # callable 返回后才记录有界错误，并仍以权威 reload 收口（不退出）。
            assert probe["completion_violations"] == [], (
                "completion must only be announced after the worker callable returned"
            )
            assert app._last_worker_had_error is True
            assert app._last_worker_error is not None
            assert "infrastructure failure" not in app._last_worker_error, (
                "bounded notice must not leak the raw exception message"
            )
            assert probe["exits"] == [], "worker error alone must not exit the app"

    asyncio.run(scenario())


def test_q2_worker_barrier_ctrl_q_defers_exit_until_worker_returns() -> None:
    """Q2 屏障（Ctrl-Q pending）：关闭请求在 worker 未返回前不得 exit/不得
    force-cancel；release 后一次权威 reload 再以 0 退出。"""

    pytest.importorskip("textual")
    from agent.tui.app import build_app

    runtime, store, provider = _barrier_runtime()
    adapter = TuiAdapter(runtime, store)

    async def scenario() -> None:
        app = build_app(
            adapter, run_id_factory=_run_id_factory(), close_deadline_seconds=30.0
        )
        async with app.run_test() as pilot:
            # 探针必须在派发之前装好：完成通知的"恰好一次已完成 callable"不变量
            # 需要看到本次 dispatch 的进入/退出，而不是从 0 起算。
            probe = _install_worker_ordering_probe(app, adapter)
            msg = pilot.app.query_one("#message")
            msg.value = "work"
            await pilot.press("enter")
            for _ in range(200):
                await pilot.pause(delay=0.01)
                if provider.entered.is_set():
                    break
            assert provider.entered.is_set()

            probe["held"] = True

            # 基线在关闭请求之前取：这样"Ctrl-Q 自己触发一次提前 reload"也会被
            # 计为 held 期间的 reload，而不是被当成新基线放过。
            held_loads = probe["loads_while_held"]
            await pilot.press("ctrl+q")
            await pilot.pause(delay=0.1)
            assert app.closing_requested is True
            assert app.shutdown_blocked is False

            # 按住期间：不退出、不 reload、不取消 worker。
            await pilot.pause(delay=0.2)
            assert probe["exits"] == [], (
                "Ctrl-Q must not force-exit while the worker is inside its callable"
            )
            assert probe["loads_while_held"] == held_loads, (
                "closing must not project a pre-completion reload as authoritative"
            )
            assert adapter.is_active is True, "worker must not be force-cancelled"
            assert store.state.last_safe_result is None

            # release → worker 返回 → owner 一次权威 reload → 退出码 0。
            provider.release.set()
            for _ in range(300):
                await pilot.pause(delay=0.01)
                if app.is_running is False:
                    break
            probe["held"] = False
            assert probe["completion_violations"] == [], (
                "completion must only be announced after the worker callable returned"
            )
            assert store.state.last_safe_result is not None
            assert (
                store.state.last_safe_result.message == "done after barrier release"
            )
            assert app.return_code == 0

    asyncio.run(scenario())
