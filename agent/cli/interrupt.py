"""REPL 运行中 SIGINT → 协作取消投递；二段式保底退出。

TUI 已有同语义通道（tui/adapter.py request_control：界面请求 → control
inbox 投递 → Runtime 在 provider/tool 返回后的安全边界写 CANCELLED 终态）。
本模块把 CLI 的 run_turn 阻塞期 Ctrl-C 接到同一条通道，替代"整个会话
exit 130"的旧行为；协作取消不可用（goal-less 会话、无活跃 run）或用户
再按一次 Ctrl-C 时恢复默认 SIGINT 语义，由调用方既有 fail-closed 路径
接管。
"""

from __future__ import annotations

import signal
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from typing import Protocol

# 投递线程在 run_turn 早期（binding 尚未 open）的短重试窗口：覆盖 run
# 刚开始无 binding 可投递的竞态，窗口过后才宣告协作取消不可用。
_DELIVERY_RETRY_SECONDS = 1.5
_DELIVERY_POLL_SECONDS = 0.05


class _CancelCapableRuntime(Protocol):
    """AgentRuntime.request_active_cancel 的最小接口（测试 fake 对齐）。"""

    def request_active_cancel(self, conversation_id: str) -> bool: ...


class RunInterruptGuard:
    """run_turn 阻塞期间把 SIGINT 翻译为协作取消请求的上下文管理器。

    信号 handler 只翻转普通布尔标志（无锁、无 I/O，信号安全）；预启动的
    daemon 投递线程负责重试投递与提示输出。非主线程进入（signal.signal
    不可用）时退化为 no-op，行为等同未安装。
    """

    def __init__(
        self,
        runtime: _CancelCapableRuntime,
        conversation_id: str,
        write_fn: Callable[[str], None],
    ) -> None:
        self._runtime = runtime
        self._conversation_id = conversation_id
        self._write_fn = write_fn
        self._requested = False
        self._delivered = False
        self._escalated = False
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self._previous_handler: object = None

    # ---- 上下文管理：安装/恢复 handler，启动/停止投递线程 ----

    def __enter__(self) -> RunInterruptGuard:
        try:
            self._previous_handler = signal.signal(
                signal.SIGINT, self._handle_signal
            )
        except ValueError:
            # 非主线程（测试嵌入、嵌入宿主）——保持默认 SIGINT 语义。
            self._previous_handler = None
            return self
        self._worker = threading.Thread(
            target=self._deliver_loop,
            name="cli-sigint-cancel",
            daemon=True,
        )
        self._worker.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self._stop.set()
        # P3-1（PR #25 gate）：join 等待期间到达的 Ctrl-C 不再注入——
        # run_turn 已正常返回，此刻注入只会让 REPL 带 traceback 崩溃；
        # 退出意图可在随后的输入提示处再按一次（干净退出路径）。
        # finally 保证原 handler 恢复必达（不受 join 中断影响）。
        try:
            worker = self._worker
            if worker is not None:
                with suppress(KeyboardInterrupt):
                    worker.join(timeout=_DELIVERY_RETRY_SECONDS + 1.0)
        finally:
            if self._previous_handler is not None:
                with suppress(ValueError):
                    signal.signal(  # type: ignore[arg-type]
                        signal.SIGINT, self._previous_handler
                    )
        return False

    # ---- 信号段：只做标志翻转；二段恢复默认中断语义 ----

    def _handle_signal(self, signum, frame) -> None:
        if self._delivered or self._escalated or self._stop.is_set():
            # 已投递（或已确认不可用）后再按：用户明确要退出——注入
            # KeyboardInterrupt，走调用方既有 fail-closed 路径。
            signal.default_int_handler(signum, frame)
            return
        self._requested = True

    # ---- 投递段：普通线程上下文，可安全拿 ControlInbox 的锁 ----

    def _deliver_loop(self) -> None:
        while not self._stop.wait(_DELIVERY_POLL_SECONDS):
            if not self._requested:
                continue
            if self._deliver_with_retry():
                self._requested = False
                continue
            self._escalate_unavailable()

    def _escalate_unavailable(self) -> None:
        """重试窗口耗尽仍无 binding：goal-less 会话或无活跃 run。

        协作取消无处投递——提示二段退出；能否存活由调用方既有路径决定。
        """

        self._escalated = True
        self._requested = False
        self._write_fn(
            "Cooperative cancel is unavailable (no active task run is "
            "accepting control). Press Ctrl-C again to interrupt."
        )

    def _deliver_with_retry(self) -> bool:
        deadline = time.monotonic() + _DELIVERY_RETRY_SECONDS
        while not self._stop.is_set():
            if self._runtime.request_active_cancel(self._conversation_id):
                self._delivered = True
                self._write_fn(
                    "Cancellation requested; the current step will stop at "
                    "its next safe boundary. Press Ctrl-C again to "
                    "force-exit."
                )
                return True
            if time.monotonic() >= deadline:
                return False
            self._stop.wait(_DELIVERY_POLL_SECONDS)
        return False

    # ---- 测试入口：直接驱动两段（不依赖真实信号） ----

    def simulate_sigint(self) -> None:
        self._handle_signal(signal.SIGINT, None)

    def drive_delivery(self) -> None:
        """同步执行一次投递判定（集成测试用；等价投递线程的一轮）。"""

        if self._deliver_with_retry():
            self._requested = False
        else:
            self._escalate_unavailable()

    @property
    def delivered(self) -> bool:
        return self._delivered

    @property
    def escalated_note_shown(self) -> bool:
        return self._escalated
