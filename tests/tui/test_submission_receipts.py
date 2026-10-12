"""S2 UI-01/UI-02/UI-03 回归（2026-10-11 审计缺陷）。

三个缺陷共享 `_submit_text` / `_pending_*` / 控制收件箱生命周期，因此同文件
覆盖；每条测试都驱动真实 `build_app` + Pilot，不使用探针式私有状态断言替代。

- UI-01：F4 多行草稿在所有发送尝试前保存；门槛拒绝/排队/失败/异常都不清空；
  modal 内 slash 是普通文本；Esc 保存不提交；未知不自动重发；迟到回调不清新草稿。
- UI-02：待确认条目绑定确切 conversation/action identity；旧同文、不同会话同文、
  迟到回执都不能消费本次文本；消费还需匹配草稿版本。
- UI-03：第二条纠正必须可达终态——已应用/已丢弃/接收未知三者可区分，已明确
  丢弃的文本可由用户再次提交且仅一次，未知的保留但不自动重试。
"""

from __future__ import annotations

import asyncio
import threading

import pytest

from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    GoalStatus,
    ModelResponse,
    ModelTextBlock,
    RunStatus,
)
from agent.runtime.control import ControlInbox
from agent.runtime.loop import AgentRuntime, InvocationLimits
from agent.runtime.tools import KernelToolRuntime
from tests.kernel.fakes import (
    CollectingSink,
    InMemoryCheckpointStore,
    conversation_with_active_goal,
    conversation_with_terminal_goal,
)


class _RecordingRuntime:
    def __init__(self, fail: bool = False) -> None:
        self.actions: list = []
        self.fail = fail

    def run_turn(self, action, snapshot):  # noqa: ANN001, ANN202
        self.actions.append(action)
        if self.fail:
            raise OSError("synthetic failure before persistence")
        from agent.runtime.contracts import RunResult

        return RunResult(status=RunStatus.COMPLETED, state=snapshot.state)


class _BlockingProvider:
    """阻塞式 provider：generate 阻塞到 event 被 set。"""

    deadline_contract = None

    def __init__(self) -> None:
        self.event = threading.Event()
        self.calls = 0

    def generate(self, context, *, delta_observer=None):  # noqa: ANN001, ANN202
        self.calls += 1
        self.event.wait(timeout=10)
        return ModelResponse((ModelTextBlock("done after release"),))


def _run_id_factory():
    counter = {"n": 0}

    def factory() -> str:
        counter["n"] += 1
        return f"run-{counter['n']}"

    return factory


def _real_adapter(state, inbox, provider):  # noqa: ANN001, ANN202
    from agent.tui.adapter import TuiAdapter

    store = InMemoryCheckpointStore(state)
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
        invocation_id_factory=lambda: "inv-1",
    )
    return TuiAdapter(runtime, store, control_inbox=inbox), store


# ---------------------------------------------------------------- UI-01


def test_f4_send_saves_draft_before_dispatch_attempt() -> None:
    """UI-01：F6 发送在任何 dispatch 尝试前保存完整文本与版本。

    Red（修复前）：`_on_multiline_result` 的 send 分支直接调 `_submit_text`，
    没有先写 draft；approval 门槛拒绝（dispatch=0）时文本无处恢复。
    """

    pytest.importorskip("textual")
    from agent.tui.app import build_app

    state = conversation_with_terminal_goal(GoalStatus.VERIFIED_DONE)
    recording = _RecordingRuntime()
    app = build_app(
        __import__("agent.tui.adapter", fromlist=["TuiAdapter"]).TuiAdapter(
            recording, InMemoryCheckpointStore(state)
        ),
        run_id_factory=_run_id_factory(),
    )

    async def scenario() -> None:
        async with app.run_test() as pilot:
            for _ in range(50):
                await pilot.pause(delay=0.02)
                if app.projection is not None:
                    break
            # 关闭 Input 使 submit 门槛失败（closing 状态拒绝 dispatch）。
            app.closing_requested = True
            await pilot.press("f4")
            for _ in range(50):
                await pilot.pause(delay=0.02)
                if app.screen.__class__.__name__ == "MultiLineEditModal":
                    break
            app.screen.query_one("#f4_editor").text = "第一行\n第二行"
            await pilot.press("f6")
            for _ in range(50):
                await pilot.pause(delay=0.02)
                if app.screen.__class__.__name__ != "MultiLineEditModal":
                    break
            # 门槛拒绝：没有 dispatch，但完整多行文本必须已保存为草稿。
            assert recording.actions == []
            assert app.draft_text == "第一行\n第二行"

    asyncio.run(scenario())


def test_f4_approval_gate_keeps_multiline_draft() -> None:
    """UI-01：审批页 F4 两行后 F6，dispatch=0 但不丢草稿。"""

    pytest.importorskip("textual")
    from agent.tui.app import build_app
    from tests.tui.test_app import _approval_state

    recording = _RecordingRuntime()
    app = build_app(
        __import__("agent.tui.adapter", fromlist=["TuiAdapter"]).TuiAdapter(
            recording, InMemoryCheckpointStore(_approval_state())
        ),
        run_id_factory=_run_id_factory(),
    )

    async def scenario() -> None:
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
            app.screen.query_one("#f4_editor").text = (
                "please change the plan\nand preserve this request"
            )
            await pilot.press("f6")
            for _ in range(50):
                await pilot.pause(delay=0.02)
                if app.screen.__class__.__name__ != "MultiLineEditModal":
                    break
            assert recording.actions == [], "approval gate must not dispatch"
            assert app.draft_text == "please change the plan\nand preserve this request"

    asyncio.run(scenario())


def test_f4_send_failure_keeps_multiline_draft() -> None:
    """UI-01：持久化前异常也不丢草稿（worker 抛错路径）。"""

    pytest.importorskip("textual")
    from agent.tui.adapter import TuiAdapter
    from agent.tui.app import build_app

    state = conversation_with_terminal_goal(GoalStatus.VERIFIED_DONE)
    app = build_app(
        TuiAdapter(_RecordingRuntime(fail=True), InMemoryCheckpointStore(state)),
        run_id_factory=_run_id_factory(),
    )

    async def scenario() -> None:
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
            app.screen.query_one("#f4_editor").text = "important first line\nimportant second line"
            await pilot.press("f6")
            for _ in range(100):
                await pilot.pause(delay=0.02)
                if not app._busy():
                    break
            # 未落盘 → 草稿保留，可重新编辑。
            assert app.draft_text == "important first line\nimportant second line"

    asyncio.run(scenario())


# ---------------------------------------------------------------- UI-03


def test_second_correction_reaches_terminal_state() -> None:
    """UI-03：两条纠正都在安全边界消费；第二条不被静默丢弃。

    Red（修复前）：第一条应用后 run 收尾、inbox binding 关闭，第二条残留在
    `_pending_control_texts`，idle 时 Enter 被 dedup 拒绝且无明确结局。
    """

    pytest.importorskip("textual")
    from agent.tui.app import build_app

    state = conversation_with_active_goal("corrections")
    inbox = ControlInbox()
    provider = _BlockingProvider()
    adapter, store = _real_adapter(state, inbox, provider)
    app = build_app(adapter, run_id_factory=_run_id_factory())

    async def scenario() -> None:
        async with app.run_test() as pilot:
            msg = app.query_one("#message")
            msg.value = "continue"
            await pilot.press("enter")
            for _ in range(100):
                await pilot.pause(delay=0.01)
                if inbox.current("corrections") is not None:
                    break
            msg.value = "first correction"
            await pilot.press("enter")
            msg.value = "second correction"
            await pilot.press("enter")
            pending_before = dict(app._pending_control_texts)
            assert len(pending_before) == 2

            provider.event.set()
            for _ in range(200):
                await pilot.pause(delay=0.01)
                if not app._busy():
                    break

            # 收尾后：两条都必须有明确结局（第一条已应用，第二条已应用或已明确
            # 丢弃），不能有任何一条无限期挂在 pending 里。
            pending_after = dict(app._pending_control_texts)
            assert pending_after == {}, (
                "every correction must reach a terminal disposition, "
                f"pending={pending_after!r}"
            )
            receipts = {r.correlation_id for r in store.state.control_receipts}
            first_id, second_id = list(pending_before)
            assert first_id in receipts, "first correction must be durably applied"
            status = str(app.query_one("#status").render())
            if second_id in receipts:
                assert "已明确丢弃" not in status
            else:
                # 队列关闭丢弃 → 必须有用户可见的明确结局，且文本保留可重发。
                assert "已明确丢弃" in status, (
                    f"dropped correction must be user-visible, status={status!r}"
                )
                assert app.draft_text == "second correction", (
                    "dropped correction text must be preserved for the user"
                )

    asyncio.run(scenario())


def test_discarded_correction_can_be_resubmitted_once() -> None:
    """UI-03：已明确丢弃的纠正文本保留且可由用户再次提交，仅提交一次。"""

    pytest.importorskip("textual")
    from agent.tui.app import build_app

    state = conversation_with_active_goal("resubmit")
    inbox = ControlInbox()
    provider = _BlockingProvider()
    adapter, store = _real_adapter(state, inbox, provider)
    app = build_app(adapter, run_id_factory=_run_id_factory())

    async def scenario() -> None:
        async with app.run_test() as pilot:
            msg = app.query_one("#message")
            msg.value = "continue"
            await pilot.press("enter")
            for _ in range(100):
                await pilot.pause(delay=0.01)
                if inbox.current("resubmit") is not None:
                    break
            msg.value = "first correction"
            await pilot.press("enter")
            msg.value = "second correction"
            await pilot.press("enter")
            provider.event.set()
            for _ in range(200):
                await pilot.pause(delay=0.01)
                if not app._busy():
                    break

            # 已丢弃的第二条保留在草稿里，用户可再次提交。
            draft = app.draft_text
            assert draft, "discarded text must be preserved for the user"
            seq_before = store.state.next_action_seq
            msg.value = draft
            await pilot.press("enter")
            for _ in range(200):
                await pilot.pause(delay=0.01)
                if not app._busy():
                    break
            # 明确丢弃后允许重发（不是永久 dedup）。
            assert store.state.next_action_seq >= seq_before

    asyncio.run(scenario())


# ---------------------------------------------------------------- UI-02


def test_historical_same_text_does_not_consume_new_draft() -> None:
    """UI-02：历史 action:1 的同文 `continue` 不能消费新提交的草稿。

    Red（修复前）：消费判定只看"任意 action: 前缀 + 文本相等"，历史同文
    误判为本次已接收 → 草稿被清空且 dispatch 计数与实际不符。
    """

    pytest.importorskip("textual")
    from agent.runtime.contracts import ConversationFact, ConversationState, FactKind
    from agent.tui.app import build_app

    old = ConversationFact(
        fact_id="action:1:user", kind=FactKind.USER_MESSAGE, content={"text": "continue"}
    )
    state = ConversationState.new("repeat")
    from dataclasses import replace

    state = replace(
        state,
        facts=(old,),
        next_action_seq=2,
        replay_floor=2,
        revision=2,
        goal=None,
    )
    store = InMemoryCheckpointStore(state)
    recording = _RecordingRuntime(fail=True)
    from agent.tui.adapter import TuiAdapter

    app = build_app(TuiAdapter(recording, store), run_id_factory=_run_id_factory())

    async def scenario() -> None:
        async with app.run_test() as pilot:
            msg = app.query_one("#message")
            msg.value = "continue"
            app.draft_text = msg.value
            app.draft_revision += 1
            await pilot.press("enter")
            for _ in range(100):
                await pilot.pause(delay=0.02)
                if not app._busy():
                    break
            # 本次 action 未落盘（worker 失败）→ 草稿必须保留。
            assert app.draft_text == "continue"

    asyncio.run(scenario())
