"""CLI 运行中 SIGINT → 协作取消（Oracle #4，2026-10-25 能力缺口审计）。

契约（agent/cli/interrupt.py RunInterruptGuard + app.run_repl 接线）：
- 第一次 Ctrl-C 投递 CANCEL（与 TUI request_control 同通道）；run_turn 以
  CANCELLED 返回后 REPL 存活，可继续输入命令；
- 协作取消不可用（goal-less 会话/无活跃 run）时提示，再次 Ctrl-C 落回
  默认 KeyboardInterrupt 语义 → 既有 exit 130 fail-closed 路径；
- 已投递后再次 Ctrl-C 同样落回默认语义（强制退出）；
- run_repl 退出后恢复原 SIGINT handler。
"""

from __future__ import annotations

import signal
import threading

import pytest

import agent.cli.interrupt as interrupt_module
from agent.cli.app import run_repl
from agent.cli.interrupt import RunInterruptGuard
from agent.runtime.contracts import (
    ConversationState,
    LoadedSnapshot,
    RunResult,
    RunStatus,
)


class StaticStore:
    def __init__(self, state: ConversationState) -> None:
        self.state = state

    def load(self) -> LoadedSnapshot:
        return LoadedSnapshot(self.state, "token-1")


class _FakeCancelRuntime:
    def __init__(self, available: bool = True) -> None:
        self.available = available
        self.cancel_calls: list[str] = []

    def request_active_cancel(self, conversation_id: str) -> bool:
        self.cancel_calls.append(conversation_id)
        return self.available


# ---- 状态机单元（不依赖真实信号/投递线程） ----


def test_guard_delivers_cancel_and_notifies() -> None:
    runtime = _FakeCancelRuntime(available=True)
    writes: list[str] = []
    guard = RunInterruptGuard(runtime, "conversation-1", writes.append)

    guard.simulate_sigint()
    guard.drive_delivery()

    assert runtime.cancel_calls == ["conversation-1"]
    assert guard.delivered is True
    assert any("Cancellation requested" in line for line in writes)


def test_guard_escalates_when_cancel_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(interrupt_module, "_DELIVERY_RETRY_SECONDS", 0.01)
    runtime = _FakeCancelRuntime(available=False)
    writes: list[str] = []
    guard = RunInterruptGuard(runtime, "conversation-1", writes.append)

    guard.simulate_sigint()
    guard.drive_delivery()

    assert guard.delivered is False
    assert guard.escalated_note_shown is True
    assert any("Cooperative cancel is unavailable" in line for line in writes)


def test_second_sigint_after_delivery_raises_default_interrupt() -> None:
    runtime = _FakeCancelRuntime(available=True)
    guard = RunInterruptGuard(runtime, "conversation-1", lambda _line: None)
    guard.simulate_sigint()
    guard.drive_delivery()

    with pytest.raises(KeyboardInterrupt):
        guard.simulate_sigint()


def test_second_sigint_after_escalation_raises_default_interrupt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(interrupt_module, "_DELIVERY_RETRY_SECONDS", 0.01)
    runtime = _FakeCancelRuntime(available=False)
    guard = RunInterruptGuard(runtime, "conversation-1", lambda _line: None)
    guard.simulate_sigint()
    guard.drive_delivery()

    with pytest.raises(KeyboardInterrupt):
        guard.simulate_sigint()


def test_guard_is_noop_off_main_thread() -> None:
    # signal.signal 只允许主线程；嵌入宿主/测试线程进入时 guard 退化为
    # no-op（不安装 handler、不启动投递线程），行为等同未安装。
    observed: dict = {}

    def _run() -> None:
        runtime = _FakeCancelRuntime(available=True)
        guard = RunInterruptGuard(runtime, "conversation-1", lambda _l: None)
        with guard:
            observed["worker"] = guard._worker

    thread = threading.Thread(target=_run)
    thread.start()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert observed["worker"] is None


# ---- run_repl 集成（真实 SIGINT） ----


class _BlockingUntilCancelRuntime:
    """run_turn 阻塞到 request_active_cancel 被调用，随后返回 CANCELLED。

    模拟真实 Runtime 的协作取消语义：请求投递后 provider/tool 返回并到达
    安全边界，run_turn 以 CANCELLED 终态返回。
    """

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.cancel_requested = threading.Event()
        self.cancel_calls = 0

    def request_active_cancel(self, conversation_id: str) -> bool:
        self.cancel_calls += 1
        self.cancel_requested.set()
        return True

    def run_turn(self, action, snapshot):  # noqa: ANN001
        self.entered.set()
        assert self.cancel_requested.wait(timeout=10), "cancel never arrived"
        return RunResult(
            RunStatus.CANCELLED,
            snapshot.state,
            message="goal cancelled at a safe boundary",
        )


def test_run_repl_sigint_requests_cooperative_cancel_and_survives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(interrupt_module, "_DELIVERY_RETRY_SECONDS", 0.05)
    state = ConversationState.new("conversation-sigint")
    runtime = _BlockingUntilCancelRuntime()
    writes: list[str] = []
    inputs = iter(("do the work", "/exit"))
    previous = signal.getsignal(signal.SIGINT)

    def _send_sigint() -> None:
        # run_turn 已进入（guard 的 handler 已安装）后，从辅助线程向本进程
        # 发真实 SIGINT——os.kill 是系统调用，允许在非主线程使用。
        import os

        assert runtime.entered.wait(timeout=10), "run_turn never started"
        os.kill(os.getpid(), signal.SIGINT)

    sender = threading.Thread(target=_send_sigint)
    sender.start()
    exit_code = run_repl(
        runtime,
        StaticStore(state),
        input_fn=lambda _prompt: next(inputs),
        write_fn=writes.append,
        run_id_factory=lambda: "run-sigint",
    )
    sender.join(timeout=5)

    assert exit_code == 0, writes
    assert runtime.cancel_calls >= 1
    assert any("Cancellation requested" in line for line in writes)
    # LOW-3（PR #25 gate）：CANCELLED 的权威渲染行也要钉住（render.py 既有
    # 路径，防止未来渲染改动悄悄丢掉终态展示）。
    assert any("Run cancelled." in line for line in writes)
    # REPL 存活：CANCELLED 后继续消费了 /exit；handler 已恢复。
    assert signal.getsignal(signal.SIGINT) is previous


class _UncancelableBlockingRuntime:
    """goal-less 会话形状：无 binding 可投递，run_turn 阻塞直至被强断。"""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self._release = threading.Event()

    def request_active_cancel(self, conversation_id: str) -> bool:
        return False

    def run_turn(self, action, snapshot):  # noqa: ANN001
        self.entered.set()
        # 主线程 Event 等待可被 KeyboardInterrupt 打断；永不 set 的释放
        # 事件 + 循环重试保持阻塞。
        while not self._release.is_set():
            self._release.wait(timeout=5)
        return RunResult(RunStatus.COMPLETED, snapshot.state)


def test_run_repl_sigint_unavailable_falls_back_to_exit_130(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(interrupt_module, "_DELIVERY_RETRY_SECONDS", 0.05)
    state = ConversationState.new("conversation-goalless")
    runtime = _UncancelableBlockingRuntime()
    writes: list[str] = []
    inputs = iter(("just answer",))
    previous = signal.getsignal(signal.SIGINT)

    def _send_two_sigints() -> None:
        import os
        import time as _time

        assert runtime.entered.wait(timeout=10), "run_turn never started"
        os.kill(os.getpid(), signal.SIGINT)
        # 等 escalate 提示落盘（第一次的投递重试窗口走完）再发第二次，
        # 此时 handler 已处于 default-int 分支。
        deadline = _time.monotonic() + 10
        while _time.monotonic() < deadline:
            if any("Cooperative cancel is unavailable" in w for w in writes):
                break
            _time.sleep(0.02)
        assert any(
            "Cooperative cancel is unavailable" in w for w in writes
        ), writes
        os.kill(os.getpid(), signal.SIGINT)

    sender = threading.Thread(target=_send_two_sigints)
    sender.start()
    exit_code = run_repl(
        runtime,
        StaticStore(state),
        input_fn=lambda _prompt: next(inputs),
        write_fn=writes.append,
        run_id_factory=lambda: "run-goalless",
    )
    sender.join(timeout=5)

    # 二次 Ctrl-C 落回既有 fail-closed 路径：exit 130 + 状态保留指引。
    assert exit_code == 130, writes
    assert any("Run interrupted. Saved state was kept" in w for w in writes)
    assert signal.getsignal(signal.SIGINT) is previous
