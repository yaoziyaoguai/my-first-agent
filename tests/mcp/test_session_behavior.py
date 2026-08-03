"""真实 stdio server 行为测试：commit point / latch / hanging cleanup / result cap。

用裸 JSON-RPC ``behavior_server.py`` 驱动 project-owned transport，验证 reviewer 指出的
实质缺口——每个测试都以「server 旁路 marker 证明 call bytes 已到达」作为 commit-point
铁证，不依赖脆弱 sleep，不只用 stub outcome。
"""

from __future__ import annotations

import gc
import os
import signal
import sys
import threading
import time
import warnings
from pathlib import Path

from agent.mcp.bridge import (
    BridgeTimeoutError,
    McpAsyncBridge,
    SessionTimeouts,
    run_stdio_session,
)
from agent.mcp.contracts import McpOutcomeClassification
from agent.mcp.safety import LatchBinding, McpSafetyLatch

SERVER = Path(__file__).resolve().parents[1] / "fixtures" / "mcp" / "behavior_server.py"
STDIO_SERVER = Path(__file__).resolve().parents[1] / "fixtures" / "mcp" / "stdio_server.py"
PROBE_SCHEMA = {"type": "object", "properties": {}}
ECHO_SCHEMA = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}


def _latch(tmp_path: Path) -> McpSafetyLatch:
    directory = tmp_path / "safety"
    directory.mkdir(mode=0o700)
    return McpSafetyLatch(directory / "latch.json")


def _binding() -> LatchBinding:
    return LatchBinding(
        server_id="repo",
        config_digest="config-digest",
        credential_profile=None,
        safety_generation="gen-1",
        intent_digest="intent-1",
    )


def _run_behavior(
    bridge: McpAsyncBridge,
    tmp_path: Path,
    *,
    mode: str,
    marker: Path | None = None,
    size_mb: int | None = None,
    pidfile: Path | None = None,
    timeouts: SessionTimeouts,
):
    latch = _latch(tmp_path)
    env: dict[str, str] = {}
    if marker is not None:
        env["BEHAVIOR_MARKER"] = str(marker)
    if size_mb is not None:
        env["BEHAVIOR_SIZE_MB"] = str(size_mb)
    if pidfile is not None:
        env["BEHAVIOR_PIDFILE"] = str(pidfile)
    outcome = bridge.submit(
        lambda: run_stdio_session(
            command=sys.executable,
            args=(str(SERVER), mode),
            cwd=None,
            env=env,
            remote_name="probe",
            arguments={},
            input_schema=PROBE_SCHEMA,
            descriptor_digest="descriptor-digest",
            latch=latch,
            binding=_binding(),
            expected_clear_revision=0,
            timeouts=timeouts,
        )
    )
    return outcome, latch


def _behavior_session_factory(
    tmp_path: Path,
    *,
    mode: str,
    marker: Path | None = None,
    pidfile: Path | None = None,
    timeouts: SessionTimeouts,
):
    """构造一个 run_stdio_session coroutine factory（不在调用线程内 submit）。"""
    latch = _latch(tmp_path)
    env: dict[str, str] = {}
    if marker is not None:
        env["BEHAVIOR_MARKER"] = str(marker)
    if pidfile is not None:
        env["BEHAVIOR_PIDFILE"] = str(pidfile)

    def factory():
        return run_stdio_session(
            command=sys.executable,
            args=(str(SERVER), mode),
            cwd=None,
            env=env,
            remote_name="probe",
            arguments={},
            input_schema=PROBE_SCHEMA,
            descriptor_digest="descriptor-digest",
            latch=latch,
            binding=_binding(),
            expected_clear_revision=0,
            timeouts=timeouts,
        )

    return factory, latch


def _process_group_dead(pid: int, *, timeout: float = 8.0) -> bool:
    """有界等待 process group 完全消失（含 orphan）。start_new_session=True 下 PGID==PID。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.killpg(pid, 0)  # 组内仍有任何存活进程 → 不抛异常
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        time.sleep(0.05)
    return False


def _force_kill_group(pid: int) -> None:
    """best-effort 兜底清理：即使测试 Red 也不残留自己创建的 process group。"""
    import contextlib

    with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
        os.killpg(pid, signal.SIGKILL)


# ---------------------------------------------------------------------------
# P0: commit point 根本失效
# ---------------------------------------------------------------------------


def test_call_then_disconnect_is_unknown_with_commit_set_and_marker(tmp_path: Path) -> None:
    """P0：server 收到 tools/call（写 marker = 副作用已发生）后断连、不回 terminal response。
    call bytes 已写出，outcome 必须是 UNKNOWN 且 ``call_may_have_been_sent=True``——绝不
    NOT_EXECUTED（那会允许重跑副作用）。marker 存在证明 server 收到并执行了 call。"""
    marker = tmp_path / "marker.json"
    bridge = McpAsyncBridge(total_timeout_seconds=30.0)
    try:
        outcome, _latch_state = _run_behavior(
            bridge,
            tmp_path,
            mode="disconnect_after_call",
            marker=marker,
            timeouts=SessionTimeouts(initialize=10, list_page=10, call=10, shutdown=5),
        )
    finally:
        bridge.close()

    assert marker.exists(), "server must have received the call (marker is commit-point proof)"
    assert outcome.call_may_have_been_sent is True
    assert outcome.classification is McpOutcomeClassification.UNKNOWN


# ---------------------------------------------------------------------------
# P1: UNKNOWN 后 latch 被错误清除
# ---------------------------------------------------------------------------


def test_unknown_outcome_keeps_latch_armed_even_when_process_exit_confirmed(
    tmp_path: Path,
) -> None:
    """P1：UNKNOWN + process_exit_confirmed=True 必须保持 latch ARMED（operator-only
    recovery）；只有确定 EXECUTED/NOT_EXECUTED 且清理确认后才可自动 clear。disconnect
    server 干净退出 → process_exit_confirmed=True，但 outcome 仍是 UNKNOWN。"""
    marker = tmp_path / "marker.json"
    bridge = McpAsyncBridge(total_timeout_seconds=30.0)
    try:
        outcome, latch = _run_behavior(
            bridge,
            tmp_path,
            mode="disconnect_after_call",
            marker=marker,
            timeouts=SessionTimeouts(initialize=10, list_page=10, call=10, shutdown=5),
        )
    finally:
        bridge.close()

    assert outcome.classification is McpOutcomeClassification.UNKNOWN
    assert outcome.process_exit_confirmed is True
    assert latch.status() == "armed", "UNKNOWN must keep the latch armed for operator recovery"


# ---------------------------------------------------------------------------
# P1: hanging server cleanup 被 TaskGroup 卡死
# ---------------------------------------------------------------------------


def test_hanging_server_cleanup_is_bounded_and_terminates_process(tmp_path: Path) -> None:
    """P1：server 收到 call 后挂起。call_timeout + shutdown_timeout 必须有界收口、process
    group 被终止、outcome 为 UNKNOWN（recovery）。不能依赖 bridge total_timeout（否则
    quarantine 整个 bridge 并误伤无关 server）。"""
    marker = tmp_path / "marker.json"
    # total_timeout 收紧：若 cleanup 仍被 TaskGroup 卡死，会撞 total_timeout 而非有界返回。
    bridge = McpAsyncBridge(total_timeout_seconds=8.0)
    start = time.monotonic()
    try:
        outcome, latch = _run_behavior(
            bridge,
            tmp_path,
            mode="hang_after_call",
            marker=marker,
            timeouts=SessionTimeouts(initialize=10, list_page=10, call=1.5, shutdown=1.5),
        )
    except BridgeTimeoutError:
        raise AssertionError(
            "cleanup must be bounded by call+shutdown timeout, not bridge total timeout"
        ) from None
    finally:
        bridge.close()
    elapsed = time.monotonic() - start

    assert marker.exists(), "server must have received the call before hanging"
    assert outcome.classification is McpOutcomeClassification.UNKNOWN
    assert outcome.call_may_have_been_sent is True
    assert outcome.process_exit_confirmed is True, "process group must be terminated and reaped"
    assert latch.status() == "armed", "UNKNOWN must keep the latch armed"
    assert elapsed < 6.0, f"cleanup must be bounded by call+shutdown; took {elapsed:.1f}s"
    # bridge.submit 返回 outcome（未抛 BridgeTimeoutError）本身证明未撞 total_timeout、
    # 未全局 quarantine——单个 hanging server 不应误伤整个 bridge。


# ---------------------------------------------------------------------------
# P2: transport stdout/result 无上限
# ---------------------------------------------------------------------------


def test_oversized_result_is_known_executed_error_not_disguised_success(
    tmp_path: Path,
) -> None:
    """P2：server 返回 5MB text。transport-owned result cap 必须把 outcome 约束为
    EXECUTED + ``oversized_result`` known-executed error，内容有界——绝不把 5MB 当成
    成功字符串伪装成功。call 已执行、terminal response 已收到，故分类仍是 EXECUTED。"""
    bridge = McpAsyncBridge(total_timeout_seconds=30.0)
    try:
        outcome, latch = _run_behavior(
            bridge,
            tmp_path,
            mode="big_result",
            size_mb=5,
            timeouts=SessionTimeouts(initialize=10, list_page=10, call=20, shutdown=5),
        )
    finally:
        bridge.close()

    assert outcome.classification is McpOutcomeClassification.EXECUTED
    assert outcome.terminal_response_received is True
    assert outcome.error_code == "oversized_result"
    # 内容有界：绝不是完整 5MB。
    assert len(outcome.result_text.encode("utf-8")) < 100_000
    assert outcome.result_text != "X" * (5 * 1024 * 1024)


def test_abusive_line_size_fails_closed(tmp_path: Path) -> None:
    """P2 防御：单行 stdout 超过 transport hard cap（远超 result cap）时，必须在 parse
    前 fail closed——call bytes 已写出，故为 UNKNOWN（recovery），绝不把超长行塞进内存
    解析后当作成功。"""
    bridge = McpAsyncBridge(total_timeout_seconds=30.0)
    try:
        outcome, _latch_state = _run_behavior(
            bridge,
            tmp_path,
            mode="big_result",
            size_mb=20,
            timeouts=SessionTimeouts(initialize=10, list_page=10, call=20, shutdown=5),
        )
    finally:
        bridge.close()

    assert outcome.call_may_have_been_sent is True
    assert outcome.classification is McpOutcomeClassification.UNKNOWN
    assert len(outcome.result_text.encode("utf-8")) < 100_000


# ---------------------------------------------------------------------------
# P1（cancellation leak）：app teardown 取消路径泄漏 hanging 子进程
# ---------------------------------------------------------------------------


def test_close_during_inflight_hanging_call_kills_process_group(tmp_path: Path) -> None:
    """P1：hanging call 走到 tools/call 后，在 cleanup 窗口内调用 bridge.close（模拟
    app teardown / close_stack）。CancelledError 是 BaseException，旧 _shutdown_process
    只捕获 TimeoutError → SIGKILL 被跳过、子进程成为 orphan（PPID=1、PGID=自身、STAT=Ss）。

    修复后：cleanup 必须 cancellation-safe、shielded、有界；process group 被 SIGKILL +
    reap，bridge.close 有界返回。pidfile + marker 双握手确定性同步，不依赖脆弱 sleep。
    """
    marker = tmp_path / "marker.json"
    pidfile = tmp_path / "server.pid"
    # call 很短 → 快速进入 _shutdown_process；shutdown 较大 → cleanup 窗口宽，便于 close 命中。
    factory, _latch = _behavior_session_factory(
        tmp_path,
        mode="hang_after_call",
        marker=marker,
        pidfile=pidfile,
        timeouts=SessionTimeouts(initialize=10, list_page=10, call=0.6, shutdown=4.0),
    )
    bridge = McpAsyncBridge(total_timeout_seconds=30.0)

    submit_exc: list[BaseException] = []

    def submit_thread() -> None:
        try:
            bridge.submit(factory)
        except BaseException as error:  # noqa: BLE001 - 记录任意结束方式，断言只看进程存活
            submit_exc.append(error)

    thread = threading.Thread(target=submit_thread, name="p1-submit")
    thread.start()
    server_pid: int | None = None
    try:
        # 握手 1：server 已启动并写出 PID。
        _wait_for_file(pidfile, timeout=10.0)
        server_pid = int(pidfile.read_text())
        # 握手 2：tools/call 已到达 server（marker = commit-point 铁证）。
        _wait_for_file(marker, timeout=10.0)
        # call_timeout(0.6) 已过、shutdown(4.0) 未到 → 任务确定在 _shutdown_process 的
        # bounded wait 途中。再等一拍让任务进入 await process.wait()。
        time.sleep(0.6)

        close_start = time.monotonic()
        bridge.close()  # 模拟 app teardown：在 cleanup 途中取消任务
        close_elapsed = time.monotonic() - close_start

        # submit 线程应能在有界时间内结束（task 被 cancel/drain 后 future 收口）。
        thread.join(timeout=15.0)
        assert not thread.is_alive(), "submit thread must terminate bounded after close"

        assert server_pid is not None
        # 核心断言：process group 已被 kill + reap，无 orphan（含 PPID=1 的 reparent 孤儿）。
        reaped = _process_group_dead(server_pid, timeout=10.0)
        assert reaped, (
            f"process group {server_pid} survived bridge.close: orphan leak under cancellation"
        )
        # close 自身必须有界（不能靠 total_timeout 兜底）。
        assert close_elapsed < 15.0, f"bridge.close must be bounded; took {close_elapsed:.1f}s"
    finally:
        # best-effort 兜底：即使 Red 也不残留 process group。
        if server_pid is not None:
            _force_kill_group(server_pid)
        bridge.close()
        thread.join(timeout=5.0)


def _wait_for_file(path: Path, *, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists() and path.stat().st_size > 0:
            return
        time.sleep(0.02)
    raise AssertionError(f"{path} never appeared within {timeout}s (handshake failed)")


# ---------------------------------------------------------------------------
# P2（resource leak）：read pipe / 主 subprocess transport 未真正关闭
# ---------------------------------------------------------------------------


def test_no_subprocess_resource_leaks_after_close(tmp_path: Path) -> None:
    """P2：bridge.close 后释放引用 + 强制 GC，不得有 unclosed event loop /
    _UnixSubprocessTransport / _UnixReadPipeTransport / stdout FileIO，也不得在
    ``BaseEventLoop.__del__`` 上抛 "Event loop is closed" unraisable。

    旧实现 bridge 从不 ``loop.close()``，且 ``_release_process_streams`` 只调 wrapper
    stream.aclose（StreamReaderWrapper.aclose 仅 set_exception、不关底层 read pipe transport）。
    loop/transport 残留到 GC 时才暴露：``BaseEventLoop.__del__`` 与 transport ``__del__``
    在 loop 已关/未关的不一致状态下抛 unraisable / ResourceWarning。
    """
    leaks: list[str] = []
    prior_unraisable = sys.unraisablehook

    def record_unraisable(hook) -> None:  # type: ignore[override]
        msg = repr(getattr(hook, "err", None))
        leaks.append(f"unraisable: {msg}")

    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        sys.unraisablehook = record_unraisable
        try:
            # 路径 1：FastMCP echo 干净退出（正常 EXECUTED）。
            (tmp_path / "echo").mkdir()
            echo_bridge = McpAsyncBridge(total_timeout_seconds=40.0)
            try:
                echo_latch = _latch(tmp_path / "echo")
                echo_outcome = echo_bridge.submit(
                    lambda: run_stdio_session(
                        command=sys.executable,
                        args=(str(STDIO_SERVER),),
                        cwd=None,
                        env={},
                        remote_name="echo",
                        arguments={"text": "clean"},
                        input_schema=ECHO_SCHEMA,
                        descriptor_digest="descriptor-digest",
                        latch=echo_latch,
                        binding=_binding(),
                        expected_clear_revision=0,
                        timeouts=SessionTimeouts(initialize=10, list_page=10, call=10, shutdown=5),
                    )
                )
            finally:
                echo_bridge.close()
            assert echo_outcome.classification is McpOutcomeClassification.EXECUTED

            # 路径 2：hanging server 被 process-group kill 后 reap（UNKNOWN + cleanup confirmed）。
            (tmp_path / "hang").mkdir()
            hang_bridge = McpAsyncBridge(total_timeout_seconds=30.0)
            try:
                hang_outcome, _hang_latch = _run_behavior(
                    hang_bridge,
                    tmp_path / "hang",
                    mode="hang_after_call",
                    timeouts=SessionTimeouts(initialize=10, list_page=10, call=1.2, shutdown=2.0),
                )
            finally:
                hang_bridge.close()
            assert hang_outcome.process_exit_confirmed is True

            # 释放 bridge 引用：让 loop（与残留 transport）成为可回收对象，再强制 GC。
            # 旧实现下 loop 未 close → BaseEventLoop.__del__ 抛 unraisable；transport
            # __del__ 在 loop 已被 GC 时抛 "Event loop is closed"。
            del echo_bridge, hang_bridge, echo_outcome, hang_outcome
            for _ in range(5):
                gc.collect()
        finally:
            sys.unraisablehook = prior_unraisable

    forbidden = (
        "transport", "FileIO", "subprocess", "Event loop is closed",
        "ReadPipe", "WritePipe", "BaseEventLoop", "event loop",
    )
    offending: list[str] = []
    for w in captured:
        text = f"{getattr(w.category, '__name__', w.category)}: {w.message}"
        if any(token in text for token in forbidden):
            offending.append(text)
    offending += [entry for entry in leaks if any(token in entry for token in forbidden)]
    assert not offending, (
        "subprocess/event-loop resource leak after bridge.close: " + " | ".join(offending)
    )


# ---------------------------------------------------------------------------
# 依赖契约（Red→Green）：mcp optional extra 必须显式钉死 anyio>=4.14.2
# ---------------------------------------------------------------------------


def test_mcp_extra_pins_anyio_lower_bound_guarding_resource_leak_regression() -> None:
    """依赖契约：``[project.optional-dependencies] mcp`` 必须显式声明 ``anyio>=4.14.2``。

    根因：``mcp==1.28.1`` 仅传递要求 ``anyio>=4.5``；在 Python 3.12 + anyio 4.13.0 上，
    本文件里的 ``test_no_subprocess_resource_leaks_after_close`` 会复现 unclosed
    _UnixSubprocessTransport / _UnixReadPipeTransport / FileIO ResourceWarning。accepted
    环境已是 anyio 4.14.2。把下界写进 mcp extra 可阻止依赖解析器回退到 4.13.x 而重新打开该
    缺口——这是 declaration-level 修复，不引入新的 runtime 路径或 capability。
    """
    import tomllib

    from packaging.requirements import Requirement
    from packaging.version import Version

    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    mcp_extra = data["project"]["optional-dependencies"]["mcp"]

    # 只收集 anyio 上「抬高下界」的算子（>= > == ~=）；< / != 是上界/排除，不构成契约。
    lower_bounds: list[Version] = []
    for raw in mcp_extra:
        req = Requirement(raw)
        if req.name.lower() != "anyio":
            continue
        for spec in req.specifier:
            if spec.operator in (">=", ">", "==", "~="):
                lower_bounds.append(Version(spec.version))
    assert lower_bounds, (
        "mcp extra must explicitly declare anyio with a lower bound; relying on mcp's "
        "transitive anyio>=4.5 admits the resource-leak-regressing 4.13.x"
    )
    best = max(lower_bounds)
    assert best >= Version("4.14.2"), (
        f"mcp extra anyio lower bound {best} < 4.14.2; "
        "4.13.x regresses test_no_subprocess_resource_leaks_after_close"
    )
