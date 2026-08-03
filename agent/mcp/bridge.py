"""MCP async owner-loop bridge（lifecycle）。

独占一条长生命周期 event-loop thread，但 startup 不创建 session/process。每次 invocation
把一个有限时 coroutine 提交到该 owner loop，并在该 coroutine 内创建/关闭独立 session。
同步等待由总 wall-clock cap 约束。bridge 不持有 Runtime state、不缓存 remote registry，
也不把 callback 送回 Runtime。cleanup 不确定时进入 terminal quarantine，拒绝后续 submission。
"""

from __future__ import annotations

import asyncio
import os
import threading
from collections.abc import Callable, Coroutine, Mapping
from dataclasses import dataclass
from typing import Any

from agent.mcp.catalog import McpCatalogError, SpawnIdentity, revalidate_spawn_identity
from agent.mcp.contracts import McpBridgeOutcome, McpOutcomeClassification
from agent.mcp.safety import LatchBinding, McpSafetyLatch


class BridgeClosedError(RuntimeError):
    """bridge 已关闭，不再接受 submission。"""


class BridgeQuarantinedError(RuntimeError):
    """bridge 进入 terminal quarantine，拒绝所有后续 submission。"""


class BridgeTimeoutError(RuntimeError):
    """submission 超过总 wall-clock cap；bridge 已 quarantine。"""


_CoroFactory = Callable[[], Coroutine[Any, Any, McpBridgeOutcome]]

# close() 在 owner loop 上 drain in-flight task 的 shielded cleanup 的有界上限。每个
# session 的 cleanup 自身被 shutdown_timeout（默认 3s，测试 ≤5s）有界约束，故该值只需
# 覆盖最长 cleanup + task-group 收口，保证 loop.stop 永远发生在 cleanup 完成之后。
_CLOSE_DRAIN_SECONDS = 8.0


class McpAsyncBridge:
    def __init__(self, *, total_timeout_seconds: float) -> None:
        if total_timeout_seconds <= 0:
            raise ValueError("total_timeout_seconds must be positive")
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop, name="mcp-bridge-loop", daemon=True
        )
        self._state = "open"
        self._state_lock = threading.Lock()
        self._submit_lock = threading.Lock()
        self._total_timeout = total_timeout_seconds
        self._thread.start()

    def is_open(self) -> bool:
        with self._state_lock:
            return self._state == "open"

    def submit(self, coro_factory: _CoroFactory) -> McpBridgeOutcome:
        with self._submit_lock:
            self._require_open()
            future = asyncio.run_coroutine_threadsafe(coro_factory(), self._loop)
            try:
                return future.result(timeout=self._total_timeout)
            except TimeoutError as error:
                future.cancel()
                self.quarantine(reason="total timeout exceeded")
                raise BridgeTimeoutError(str(error) or "bridge submission timed out") from error

    def quarantine(self, *, reason: str = "") -> None:
        with self._state_lock:
            if self._state != "closed":
                self._state = "quarantined"
            self._reason = reason

    def close(self) -> None:
        import contextlib

        with self._state_lock:
            if self._state == "closed":
                return
            self._state = "closed"

        # 先在 owner loop 上 drain：取消所有 in-flight task 并「有界」等它们的 finally 完成
        # shielded cleanup（_shutdown_process 的 kill+reap+aclose）。旧实现 cancel 后立即
        # loop.stop，会让 task 的 finally 来不及执行——hanging 子进程被取消打断后 SIGKILL
        # 被跳过、成为 orphan，且 transport 未关闭（P1/P2）。cleanup 必须在 loop 仍运行时完成。
        #
        # 注意：loop.stop 必须在 drain future 完成之后、经 call_soon_threadsafe 单独触发——
        # 若在 _drain 协程内直接 stop，loop 会在 future 的 done-callback 执行前就退出，
        # future.result 将一直等到超时（close 看似卡住 ~drain 上限）。
        async def _drain() -> None:
            import anyio

            tasks = [
                task
                for task in asyncio.all_tasks(self._loop)
                if task is not asyncio.current_task()
            ]
            for task in tasks:
                task.cancel()
            if tasks:
                with anyio.move_on_after(_CLOSE_DRAIN_SECONDS):
                    await asyncio.gather(*tasks, return_exceptions=True)

        future = asyncio.run_coroutine_threadsafe(_drain(), self._loop)
        # drain 超时或 loop 异常：不阻塞 close，下方 stop/join/close 兜底。
        with contextlib.suppress(Exception):
            future.result(timeout=_CLOSE_DRAIN_SECONDS + 1.0)
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=2.0)
        # loop 已停止、无 in-flight task：显式 close 以释放 selector 持有的 pipe transport
        # 引用，避免 loop/transport 残留到 GC 时触发 unclosed / "Event loop is closed"（P2）。
        if not self._loop.is_closed():
            self._loop.close()

    def _require_open(self) -> None:
        with self._state_lock:
            state = self._state
        if state == "quarantined":
            raise BridgeQuarantinedError("bridge is quarantined")
        if state == "closed":
            raise BridgeClosedError("bridge is closed")

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()


# ---------------------------------------------------------------------------
# Project-owned stdio transport + bounded protocol session（U3）
#
# 复刻 SDK stdio_client 的 framing/pump 模式，但进程 handle、commit receipt 与 process
# group cleanup 全部由本项目持有；只把 public memory stream contract 交给 SDK ClientSession，
# SDK 继续独占 JSON-RPC session lifecycle。不使用 SDK 的 stdio_client（避免 SDK-owned spawn）。
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SessionTimeouts:
    initialize: float = 5.0
    list_page: float = 5.0
    call: float = 10.0
    shutdown: float = 3.0


# transport-owned 字节上限。result cap 约束 outcome.result_text（持久容器）；stdout line
# hard cap 是单条 JSON-RPC line 的绝对内存上界——超限在 parse 前 fail closed，防止单条
# 超大行在 model_validate_json 处耗尽内存。line cap 必须 > result cap，才能让「超 result
# cap 但仍可解析」的结果被测出并映射为 known-executed oversized error（而非 parse 前 fail）。
_RESULT_CAP_BYTES_DEFAULT = 1_000_000
_STDOUT_LINE_HARD_CAP_BYTES = 16_000_000
# oversized 结果回传给模型的 bounded 样本（远小于 result cap，仅用于诊断）。
_OVERSIZED_SAMPLE_CHARS = 2_000


class _CommitState:
    """transport owner 设置的 commit-state。"""

    def __init__(self) -> None:
        self.call_may_have_been_sent = False
        self.terminal_response_received = False
        self.terminal_request_id_matched = False
        self.process_exit_confirmed = False


async def run_stdio_session(
    *,
    command: str,
    args: tuple[str, ...],
    cwd: str | None,
    env: dict[str, str],
    remote_name: str,
    arguments: dict[str, object],
    input_schema: Mapping[str, object],
    descriptor_digest: str,
    latch: McpSafetyLatch,
    binding: LatchBinding,
    expected_clear_revision: int,
    timeouts: SessionTimeouts,
    spawn_identity: SpawnIdentity | None = None,
    max_list_pages: int = 16,
    stderr_cap_bytes: int = 20_000,
    result_cap_bytes: int = _RESULT_CAP_BYTES_DEFAULT,
) -> McpBridgeOutcome:
    """一次有限时 stdio session：revalidate → spawn → initialize → list → verify → call → close。

    产出不可变 ``McpBridgeOutcome``。call 前可证明的失败为 NOT_EXECUTED；call bytes 可能
    写出后的失败为 UNKNOWN（交由上层 recovery）；完整 terminal result 为 EXECUTED。
    spawn 前复验 executable/ancestor/cwd identity（catalog 冻结），防止 approval 后 executable
    被替换：漂移是可证明的 pre-spawn 失败 → NOT_EXECUTED，绝不 spawn 被篡改的二进制。
    """

    token = latch.arm(expected_clear_revision=expected_clear_revision, binding=binding)
    commit = _CommitState()
    process = None
    outcome: McpBridgeOutcome | None = None
    try:
        if spawn_identity is not None:
            # spawn（与 latch arm）之前复验 identity：catalog 的 revalidate 重新计算并比较
            # executable/ancestor/cwd identity；漂移映射为 pre-spawn NOT_EXECUTED。
            try:
                revalidate_spawn_identity(command, cwd, spawn_identity)
            except McpCatalogError:
                raise _NotExecutedError(
                    "spawn_identity_drift",
                    "approved spawn identity (executable/ancestor/cwd) drifted; re-provision",
                ) from None
        process = await _spawn(command, args, cwd, env)
        await _validate_arguments(arguments, input_schema)
        outcome = await _drive_session(
            process=process,
            remote_name=remote_name,
            arguments=arguments,
            pinned_schema=input_schema,
            commit=commit,
            timeouts=timeouts,
            max_list_pages=max_list_pages,
            stderr_cap_bytes=stderr_cap_bytes,
            result_cap_bytes=result_cap_bytes,
        )
    except _NotExecutedError as error:
        outcome = McpBridgeOutcome(
            classification=McpOutcomeClassification.NOT_EXECUTED,
            error_code=error.code,
            error_message=error.sanitized,
        )
    except Exception as error:
        classification = (
            McpOutcomeClassification.UNKNOWN
            if commit.call_may_have_been_sent
            else McpOutcomeClassification.NOT_EXECUTED
        )
        outcome = McpBridgeOutcome(
            classification=classification,
            call_may_have_been_sent=commit.call_may_have_been_sent,
            error_code="session_failure",
            error_message=_sanitize(str(error)),
        )
    finally:
        # _drive_session 已在其 finally 内有界终止 process group、reap，并通过 anyio
        # Process.aclose 关闭全部 pipe/主 transports（task group 才能收口、transport 不残留）；
        # 仅当 _drive_session 未运行（如 validate 在 drive 前失败）时才在此补做。
        # _shutdown_process 对已退出进程幂等，且 cancellation-safe（shielded）。
        if process is not None and not commit.process_exit_confirmed:
            commit.process_exit_confirmed = await _shutdown_process(process, timeouts.shutdown)
        # auto-clear 必须保守：只在「确定无 unknown 风险」时清除 armed latch。
        # 从未 spawn（process is None）→ 无残留进程，可清除 stale ARMED marker；
        # 已 spawn 则必须 process_exit_confirmed 且 outcome 是确定的 EXECUTED/NOT_EXECUTED。
        # UNKNOWN 的 effect 可能已发生，latch 必须保持 ARMED 交由 operator-only recovery
        # （force_clear），绝不因 process 已退出就自动清除——退出不等于副作用未发生。
        classification = outcome.classification if outcome is not None else None
        safe_to_clear = process is None or (
            commit.process_exit_confirmed
            and classification
            in (McpOutcomeClassification.EXECUTED, McpOutcomeClassification.NOT_EXECUTED)
        )
        if safe_to_clear:
            latch.clear(revision=expected_clear_revision + 1, token=token, binding=binding)

    assert outcome is not None
    return _finalize_outcome(outcome, commit)


async def _drive_session(
    *,
    process,
    remote_name,
    arguments,
    pinned_schema,
    commit,
    timeouts,
    max_list_pages,
    stderr_cap_bytes,
    result_cap_bytes,
) -> McpBridgeOutcome:
    import anyio
    import mcp.types as mcp_types
    from mcp.shared.message import SessionMessage

    read_writer, read_stream = anyio.create_memory_object_stream(0)
    write_stream, write_reader = anyio.create_memory_object_stream(0)
    # stderr 持续 drain，避免 server 因 stderr pipe 写满而阻塞死锁；捕获量有界且不进
    # model/result（仅 transport owner 内部持有 bounded 字节，用于诊断）。
    stderr_captured = bytearray()

    async def stdout_reader() -> None:
        # 直接读 bytes 而非 TextReceiveStream：按 byte 维度对单条 JSON-RPC line 施加 hard cap，
        # 超限在 decode/parse 前 fail closed，防止单条超大行在 model_validate_json 处耗尽内存。
        try:
            async with read_writer:
                buffer = b""
                while True:
                    try:
                        chunk = await process.stdout.receive()
                    except anyio.EndOfStream:
                        break
                    buffer += chunk
                    # 单行（累积至今未出现换行）超过 hard cap → parse 前 fail closed。
                    if b"\n" not in buffer and len(buffer) > _STDOUT_LINE_HARD_CAP_BYTES:
                        await read_writer.send(
                            RuntimeError("stdout line exceeded transport hard cap")
                        )
                        return
                    *complete_lines, buffer = buffer.split(b"\n")
                    for raw_line in complete_lines:
                        if len(raw_line) > _STDOUT_LINE_HARD_CAP_BYTES:
                            await read_writer.send(
                                RuntimeError("stdout line exceeded transport hard cap")
                            )
                            return
                        try:
                            line = raw_line.decode("utf-8")
                            message = mcp_types.JSONRPCMessage.model_validate_json(line)
                        except Exception as error:  # stdout 污染 → fail closed
                            await read_writer.send(error)
                            return
                        await read_writer.send(SessionMessage(message))
        except anyio.ClosedResourceError:
            await anyio.lowlevel.checkpoint()

    async def stdin_writer() -> None:
        try:
            async with write_reader:
                async for session_message in write_reader:
                    # SDK 1.28.1 的 SessionMessage.message 是 RootModel JSONRPCMessage，
                    # 真实 method 在 .root.method（不是 .message.method）。同时兼容旧形状：
                    # 无 root 时退回 message 自身。
                    message = session_message.message
                    inner = getattr(message, "root", message)
                    method = getattr(inner, "method", None)
                    if method == "tools/call":
                        # 第一次 tools/call OS write attempt 之前保守置位，永不回退。
                        commit.call_may_have_been_sent = True
                    payload = session_message.message.model_dump_json(
                        by_alias=True, exclude_none=True
                    )
                    await process.stdin.send(f"{payload}\n".encode())
        except anyio.ClosedResourceError:
            await anyio.lowlevel.checkpoint()

    async def stderr_drainer() -> None:
        if process.stderr is None:
            return
        try:
            # 持续读取直到 EOF：不阻塞 server 的 stderr 写入。仅在 cap 内保留样本，
            # 超出后继续读取并丢弃，保证 bounded 且不泄漏到 model/result。
            while True:
                chunk = await process.stderr.receive()
                room = stderr_cap_bytes - len(stderr_captured)
                if room > 0:
                    stderr_captured.extend(chunk[:room])
        except anyio.EndOfStream:
            pass
        except anyio.ClosedResourceError:
            await anyio.lowlevel.checkpoint()
        except Exception:  # noqa: BLE001 - stderr drain 不能影响 protocol outcome
            pass

    outcome: McpBridgeOutcome | None = None
    async with anyio.create_task_group() as task_group:
        task_group.start_soon(stdout_reader)
        task_group.start_soon(stdin_writer)
        task_group.start_soon(stderr_drainer)
        try:
            outcome = await _interact(
                read_stream=read_stream,
                write_stream=write_stream,
                remote_name=remote_name,
                arguments=arguments,
                pinned_schema=pinned_schema,
                commit=commit,
                timeouts=timeouts,
                max_list_pages=max_list_pages,
                result_cap_bytes=result_cap_bytes,
            )
        except _NotExecutedError as error:
            outcome = McpBridgeOutcome(
                classification=McpOutcomeClassification.NOT_EXECUTED,
                error_code=error.code,
                error_message=error.sanitized,
            )
        except Exception as error:
            classification = (
                McpOutcomeClassification.UNKNOWN
                if commit.call_may_have_been_sent
                else McpOutcomeClassification.NOT_EXECUTED
            )
            outcome = McpBridgeOutcome(
                classification=classification,
                call_may_have_been_sent=commit.call_may_have_been_sent,
                error_code="session_failure",
                error_message=_sanitize(str(error)),
            )
        finally:
            # 有界、cancellation-safe 终止 process group，让 task group 能收口。_shutdown_process
            # 关 stdin（正常 server 见 EOF 退出）+ bounded wait + 必要时 SIGKILL 整个 process group
            # + anyio Process.aclose 关闭全部 transports。hanging server 不会因 stdin EOF 退出，
            # 必须 kill 才能让其 stdout/stderr pipe 关闭 → reader 收 EOF 退出；否则 task group
            # 永远等 hanging stdout、_drive_session 不返回，只能撞 bridge total_timeout 全局
            # quarantine 误伤无关 server。shield 保证 bridge.close 取消任务时 kill+reap+aclose
            # 仍完成（不留 orphan、不泄漏 transport）。stderr 持续 drain 到 EOF、buffer-0 commit
            # boundary、close stack 与无自动重试均不变。
            commit.process_exit_confirmed = await _shutdown_process(process, timeouts.shutdown)
            await write_stream.aclose()
            await read_stream.aclose()
    assert outcome is not None
    return outcome


async def _interact(
    *,
    read_stream,
    write_stream,
    remote_name,
    arguments,
    pinned_schema,
    commit,
    timeouts,
    max_list_pages,
    result_cap_bytes,
) -> McpBridgeOutcome:
    import anyio
    from mcp.client.session import ClientSession

    # 注意：在 ``async with ClientSession`` 内部不要 raise _NotExecuted——session 的
    # __aexit__ 会把它包成 ExceptionGroup 绕过外层分类。pre-call 条件直接返回 outcome，
    # 只有 tools/call 之后的失败才传播（由上层映射为 UNKNOWN）。
    async with ClientSession(read_stream, write_stream) as session:
        with anyio.fail_after(timeouts.initialize):
            initialized = await session.initialize()
        if initialized.capabilities is None or initialized.capabilities.tools is None:
            return McpBridgeOutcome(
                classification=McpOutcomeClassification.NOT_EXECUTED,
                error_code="server_lacks_tools",
                error_message="server did not declare tools capability",
            )
        try:
            remote_tools = await _list_tools_paginated(
                session, timeouts.list_page, max_list_pages
            )
            _verify_descriptor(remote_tools, remote_name, pinned_schema)
        except _NotExecutedError as error:
            return McpBridgeOutcome(
                classification=McpOutcomeClassification.NOT_EXECUTED,
                error_code=error.code,
                error_message=error.sanitized,
            )
        with anyio.fail_after(timeouts.call):
            call_result = await session.call_tool(remote_name, arguments)
        commit.terminal_response_received = True
        return _normalize_call_result(call_result, result_cap_bytes=result_cap_bytes)


async def _list_tools_paginated(session, timeout, max_pages) -> list:
    import anyio

    cursor = None
    tools: list = []
    for _ in range(max_pages):
        with anyio.fail_after(timeout):
            page = await session.list_tools(cursor=cursor)
        tools.extend(page.tools)
        cursor = page.nextCursor
        if cursor is None:
            return tools
    raise _NotExecutedError("list_page_limit", "tool list pagination exceeded the page limit")


def _verify_descriptor(remote_tools, remote_name, pinned_schema) -> None:

    match = next((tool for tool in remote_tools if tool.name == remote_name), None)
    if match is None:
        raise _NotExecutedError("descriptor_missing", "remote tool descriptor is missing")
    remote_schema = match.inputSchema
    if hasattr(remote_schema, "model_dump"):
        remote_schema = remote_schema.model_dump()
    if _canonical_schema(remote_schema) != _canonical_schema(pinned_schema):
        raise _NotExecutedError("descriptor_drift", "remote descriptor drifted; re-provision")


def _canonical_schema(value) -> str:
    import json
    from collections.abc import Mapping

    def clean(node):
        if isinstance(node, Mapping):
            return {key: clean(node[key]) for key in node if key not in _COSMETIC_SCHEMA_KEYS}
        if isinstance(node, list):
            return [clean(item) for item in node]
        return node

    return json.dumps(clean(value), sort_keys=True, ensure_ascii=False, default=str)


_COSMETIC_SCHEMA_KEYS = frozenset({"title", "$schema"})


async def _validate_arguments(arguments, input_schema) -> None:
    try:
        import jsonschema
    except ImportError as error:  # pragma: no cover - extra provides jsonschema
        raise _NotExecutedError("schema_validator_missing", "jsonschema is unavailable") from error
    try:
        jsonschema.validate(arguments, dict(input_schema))
    except jsonschema.ValidationError as error:
        raise _NotExecutedError(
            "invalid_arguments", "arguments do not match the pinned schema"
        ) from error


def _normalize_call_result(call_result, *, result_cap_bytes: int) -> McpBridgeOutcome:
    text_parts: list[str] = [
        getattr(block, "text", "")
        for block in call_result.content
        if getattr(block, "type", None) == "text"
    ]
    text = "\n".join(text_parts)
    if call_result.isError:
        return McpBridgeOutcome(
            classification=McpOutcomeClassification.EXECUTED,
            call_may_have_been_sent=True,
            terminal_response_received=True,
            terminal_request_id_matched=True,
            result_text=text,
            error_code="remote_error",
            error_message="remote tool reported isError",
        )
    if not text_parts:
        # v1 只呈现 text content block；structuredContent projection 与 binary/media 渲染
        # 均已 deferred（不在此处 error）。只有当结果没有任何 text block 可呈现时（仅
        # 非文本 block 或仅 structuredContent），call 虽完成但内容不可用，才作为
        # known-executed error，不能返回空成功字符串。
        return McpBridgeOutcome(
            classification=McpOutcomeClassification.EXECUTED,
            call_may_have_been_sent=True,
            terminal_response_received=True,
            terminal_request_id_matched=True,
            error_code="unsupported_content",
            error_message="result contained no presentable text content",
        )
    # transport-owned result cap：call 已执行、terminal response 已收到，但结果超过 cap。
    # 必须作为 known-executed oversized error（内容有界、不伪装成功），让上层映射为
    # KnownExecutedError 而非把超大文本当成功字符串塞给模型。stderr drain 不参与此处。
    if len(text.encode("utf-8")) > result_cap_bytes:
        return McpBridgeOutcome(
            classification=McpOutcomeClassification.EXECUTED,
            call_may_have_been_sent=True,
            terminal_response_received=True,
            terminal_request_id_matched=True,
            result_text=_bounded_oversized_sample(text, result_cap_bytes),
            error_code="oversized_result",
            error_message=f"result exceeded transport cap of {result_cap_bytes} bytes",
        )
    return McpBridgeOutcome(
        classification=McpOutcomeClassification.EXECUTED,
        call_may_have_been_sent=True,
        terminal_response_received=True,
        terminal_request_id_matched=True,
        process_exit_confirmed=False,
        result_text=text,
    )


def _bounded_oversized_sample(text: str, cap: int) -> str:
    """oversized 结果的有界样本：保留前若干字符 + 截断标记，绝不保留完整超大文本。"""
    marker = f"\n[...truncated; result exceeded transport cap of {cap} bytes]"
    return f"{text[:_OVERSIZED_SAMPLE_CHARS]}{marker}"


async def _spawn(command, args, cwd, env):
    import subprocess

    import anyio

    return await anyio.open_process(
        [command, *args],
        env=env,
        cwd=cwd,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )


async def _shutdown_process(process, timeout) -> bool:
    """有界、cancellation-safe 的 process-group shutdown + 完整 transport close。

    保证（即使调用方被 bridge.close / submit total_timeout 取消）：
      1. SIGKILL 整个 process group（``start_new_session=True`` 下 hanging server 自身即
         组长，含其同组子进程）；
      2. 有界 reap（确认 returncode）；
      3. 复用 anyio ``Process.aclose`` 关闭 stdin/stdout/stderr 底层 pipe transports 与
         主 subprocess transport——不靠进程退出的副作用，也不维护一套不完整的 wrapper cleanup
         （StreamReaderWrapper.aclose 仅 set_exception、不关底层 read-pipe transport）。

    ``CancelScope(shield=True)`` 让取消不会打断 kill+reap+aclose：旧实现只捕获 TimeoutError，
    CancelledError（BaseException）会跳过 SIGKILL 分支，使 hanging 子进程成为 orphan。scope
    退出时若有待决 cancellation，anyio 在此重新抛出——cleanup 已完成，原 cancellation 不被吞掉。
    """
    import contextlib
    import signal

    import anyio

    with anyio.CancelScope(shield=True):
        # 1. best-effort 关 stdin：正常 server 见 EOF 自行退出。
        with contextlib.suppress(BaseException):
            if process.stdin is not None:
                await process.stdin.aclose()
        # 2. 有界等 graceful exit；超时或被取消都进入强制 kill 分支。
        exited = False
        with anyio.move_on_after(timeout):
            try:
                await process.wait()
                exited = True
            except BaseException:
                pass
        # 3. 仍未退出 → SIGKILL 整个 process group + 有界 reap。
        if not exited:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except ProcessLookupError:
                exited = True
            except OSError:
                pass
            if not exited:
                with anyio.move_on_after(timeout):
                    try:
                        await process.wait()
                        exited = True
                    except BaseException:
                        pass
        # 4. 复用 anyio 生命周期关闭全部 pipe transports + 主 transport（对已退出进程幂等）。
        with contextlib.suppress(BaseException):
            await process.aclose()
        return exited


def _finalize_outcome(outcome: McpBridgeOutcome, commit: _CommitState) -> McpBridgeOutcome:
    # A5/R7：terminal response received 但 process-group cleanup
    # 未确认 → reclassify EXECUTED→UNKNOWN。
    classification = outcome.classification
    if classification is McpOutcomeClassification.EXECUTED and not commit.process_exit_confirmed:
        classification = McpOutcomeClassification.UNKNOWN
    return McpBridgeOutcome(
        classification=classification,
        call_may_have_been_sent=outcome.call_may_have_been_sent or commit.call_may_have_been_sent,
        terminal_response_received=outcome.terminal_response_received,
        terminal_request_id_matched=outcome.terminal_request_id_matched,
        process_exit_confirmed=commit.process_exit_confirmed,
        result_text=outcome.result_text,
        error_code=outcome.error_code,
        error_message=outcome.error_message or (
            "process cleanup unconfirmed"
            if classification is McpOutcomeClassification.UNKNOWN
            else ""
        ),
    )


def _sanitize(text: str) -> str:
    if len(text) > 500:
        text = text[:500]
    return text


class _NotExecutedError(Exception):
    def __init__(self, code: str, sanitized: str) -> None:
        super().__init__(sanitized)
        self.code = code
        self.sanitized = _sanitize(sanitized)

