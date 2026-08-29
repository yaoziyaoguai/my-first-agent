from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from dataclasses import replace

import pytest

from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    ActiveRunStatus,
    ApprovalRequest,
    ConversationState,
    EgressClass,
    ExecutionAuthorityClass,
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
from agent.runtime.loop import AgentRuntime, InvocationLimits
from agent.runtime.state import (
    accept_action,
    mark_executing,
    pause_for_approval,
    pause_for_recovery,
    start_tool_batch,
)
from agent.runtime.tools import KernelToolRuntime
from agent.runtime.views import SourceView
from agent.tui.adapter import TuiAdapter
from agent.tui.render import TuiProjection
from tests.kernel.fakes import CollectingSink, InMemoryCheckpointStore, ScriptedProvider


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


def _submit(conv: str, run_id: str, message: str):
    from agent.runtime.contracts import SubmitMessage

    return SubmitMessage(
        conversation_id=conv, action_seq=1, expected_revision=0, run_id=run_id, message=message
    )


def _runtime_with_store(state: ConversationState):
    store = InMemoryCheckpointStore(state)
    provider = ScriptedProvider(ModelResponse((ModelTextBlock("must not run"),)))
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

    def generate(self, context):
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

            app.request_close()
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

            app.request_close()
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
