from __future__ import annotations

import threading

from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    ControlBinding,
    ControlRequestKind,
    ConversationState,
    ModelResponse,
    ModelTextBlock,
    RunStatus,
    RuntimeEvent,
    RuntimeEventKind,
    SubmitMessage,
)
from agent.runtime.control import ControlInbox
from agent.runtime.loop import AgentRuntime, InvocationLimits
from agent.runtime.tools import KernelToolRuntime
from agent.tui.adapter import AdapterBusyError, TuiAdapter
from agent.tui.render import project
from tests.kernel.fakes import CollectingSink, InMemoryCheckpointStore, ScriptedProvider


def _runtime_for(store, provider):
    return AgentRuntime(
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


def test_load_view_is_read_only_and_does_not_invoke_runtime() -> None:
    store = InMemoryCheckpointStore(ConversationState.new("c1"))
    provider = ScriptedProvider(ModelResponse((ModelTextBlock("must not run"),)))
    adapter = TuiAdapter(_runtime_for(store, provider), store)

    view = adapter.load_view()
    assert view.snapshot.state.conversation_id == "c1"
    assert provider.calls == []


def test_execute_once_runs_single_flight() -> None:
    store = InMemoryCheckpointStore(ConversationState.new("c1"))
    provider = ScriptedProvider(ModelResponse((ModelTextBlock("done"),)))
    adapter = TuiAdapter(_runtime_for(store, provider), store)

    result = adapter.execute_once(
        SubmitMessage(
            conversation_id="c1", action_seq=1, expected_revision=0, run_id="run-1", message="hi"
        )
    )
    assert result.status is RunStatus.COMPLETED
    assert len(provider.calls) == 1


def test_concurrent_execute_is_rejected() -> None:
    class _BlockingProvider:
        def __init__(self) -> None:
            self.event = threading.Event()
            self.calls = 0

        def generate(self, context):
            self.calls += 1
            self.event.wait(timeout=5)
            return ModelResponse((ModelTextBlock("done"),))

    store = InMemoryCheckpointStore(ConversationState.new("c1"))
    provider = _BlockingProvider()
    adapter = TuiAdapter(_runtime_for(store, provider), store)
    errors: list[Exception] = []
    started = threading.Event()

    def first():
        try:
            adapter.execute_once(
                SubmitMessage(
                    conversation_id="c1",
                    action_seq=1,
                    expected_revision=0,
                    run_id="run-1",
                    message="hi",
                )
            )
        except Exception as error:  # noqa: BLE001
            errors.append(error)

    def second():
        started.wait(timeout=5)
        try:
            adapter.execute_once(
                SubmitMessage(
                    conversation_id="c1",
                    action_seq=1,
                    expected_revision=0,
                    run_id="run-1",
                    message="hi",
                )
            )
        except AdapterBusyError as error:
            errors.append(error)

    thread_a = threading.Thread(target=first)
    thread_b = threading.Thread(target=second)
    thread_a.start()
    # 等 first 进入 provider（持 _active）后再启动 second。
    while provider.calls == 0:
        pass
    started.set()
    thread_b.start()
    thread_b.join(timeout=5)
    provider.event.set()
    thread_a.join(timeout=5)

    assert any(isinstance(error, AdapterBusyError) for error in errors)
    assert provider.calls == 1


def test_active_goal_control_uses_inbox_without_mutating_checkpoint() -> None:
    from tests.kernel.fakes import conversation_with_active_goal

    state = conversation_with_active_goal()
    store = InMemoryCheckpointStore(state)
    inbox = ControlInbox()
    provider = ScriptedProvider(ModelResponse((ModelTextBlock("done"),)))
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
    binding = ControlBinding(
        conversation_id=state.conversation_id,
        goal_id=state.goal.goal_id,
        goal_revision=state.goal.revision,
        invocation_id="invocation-1",
    )
    inbox.open(binding)

    request = adapter.request_control(ControlRequestKind.PAUSE)

    assert request.goal_id == state.goal.goal_id
    assert store.state == state
    assert inbox.poll(binding) == request


def _event(eid: str, kind: RuntimeEventKind, *, payload: dict | None = None) -> RuntimeEvent:
    """构造 advisory RuntimeEvent；payload 故意可携带"误导性"字段以验证其无效。"""
    return RuntimeEvent(
        event_id=eid,
        kind=kind,
        conversation_id="c1",
        run_id="run-1",
        revision=0,
        causation_id="cause",
        payload=payload or {},
        advisory=True,
    )


def test_advisory_events_loss_duplicate_reorder_do_not_change_authoritative_control() -> None:
    """N2：事件 loss/duplicate/reorder 是 advisory。

    authoritative checkpoint 与可用 action 集合（控制）只由 ``load_view()`` 的
    checkpoint 经 ``project`` 派生；worker 投影到 advisory sink 的事件流无论丢失、
    重复、乱序（甚至携带"已完成/需审批"等误导性 kind/payload），都不能改变
    checkpoint revision、触发 CAS 写入、调用 runtime，或改变 projection 的 action 集合。
    """
    store = InMemoryCheckpointStore(ConversationState.new("c1"))
    provider = ScriptedProvider(ModelResponse((ModelTextBlock("must not run"),)))
    adapter = TuiAdapter(_runtime_for(store, provider), store)

    baseline_state = adapter.load_view().snapshot.state
    baseline_actions = project(baseline_state).actions
    assert baseline_actions == ("submit",)

    # 一条"完整且有序"的 advisory 事件流；含可能误导控制的 kind/payload。
    full_stream = [
        _event("e1", RuntimeEventKind.TOOL_REQUESTED, payload={"tool": "write_file"}),
        _event("e2", RuntimeEventKind.APPROVAL_REQUESTED, payload={"risk": "high"}),
        _event("e3", RuntimeEventKind.COMPLETED, payload={"message": "all done"}),
    ]

    # 注入故障：loss（丢尾部）、duplicate（中段重复）、reorder（乱序）、复合。
    faulted = {
        "loss": full_stream[:2],
        "duplicate": full_stream[:2] + [full_stream[1]] + full_stream[2:],
        "reorder": [full_stream[2], full_stream[0], full_stream[1]],
        "loss_and_reorder": [full_stream[2], full_stream[0]],
        "all_duplicates": [full_stream[0]] * 4,
    }

    for fault_name, stream in faulted.items():
        for ev in stream:
            adapter.event_sink.emit(ev)
        # _refresh 的 advisory 消费：drain 后丢弃，不写 checkpoint、不驱动 effect。
        drained = adapter.event_sink.drain()
        assert len(drained) == len(stream), fault_name

        after = adapter.load_view().snapshot.state
        assert after == baseline_state, fault_name
        assert store.state.revision == baseline_state.revision, fault_name
        assert store.save_count == 0, f"{fault_name}: events must not trigger checkpoint CAS"
        assert project(after).actions == baseline_actions, fault_name
        assert provider.calls == [], f"{fault_name}: events must not invoke runtime"
        # queue 排空：advisory 消费幂等，再次 drain 无残余。
        assert adapter.event_sink.drain() == [], fault_name
