"""有界真实本地浏览器旅程（A08 F2 重启补记 + A13 D06 提交/读回/清理）。

仅本地：专属 Chromium（既有安装）、loopback fixture、无真实 provider。
每条旅程 120s 上限；资源在 finally 清理；输出 JSON 判定供 RESULTS 记录。
"""
from __future__ import annotations

import json
import os
import select
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from agent.browser.session_store import BrowserSessionStore, SessionPhase  # noqa: E402
from agent.composition import build_browser_resources, build_managed_web_resources  # noqa: E402
from agent.process.group import group_alive, terminate_group, verified_group_identity  # noqa: E402
from agent.runtime.contracts import (  # noqa: E402
    ApprovalGrant,
    ProcessAuthorityLeaseV1,
    ToolCall,
    ToolPrepareContext,
    ToolResult,
)
from agent.runtime.tools import KernelToolRuntime  # noqa: E402

D06_FIXTURE = ROOT / "tests/acceptance/fixtures/d06_local_page"

# S3-B 固定清理预算（秒）：cooperative 15s + TERM 1s + KILL 1s + post-KILL
# verify 6s。工作预算默认 120s；两者分开，不承诺 143s 内外部资源必清。
_COOPERATIVE_CLEANUP_SECONDS = 15.0
_TERM_GRACE_SECONDS = 1.0
_KILL_GRACE_SECONDS = 1.0
_POST_KILL_VERIFY_SECONDS = 6.0
# 子进程 stdout/stderr 有界排空上限（真实字节）。
_CHILD_STDOUT_LIMIT = 1 * 1024 * 1024
_CHILD_STDERR_LIMIT = 64 * 1024
# EV-01：select 单次切片与退出后排空期限。排空期限独立于工作预算——继承写端
# 的后代可能让 pipe 永不 EOF，等待必须封顶。
_SELECT_SLICE_SECONDS = 0.2
_DRAIN_DEADLINE_SECONDS = 1.0

# EV-03：外部参数与子进程记录里的规范 journey 名的唯一映射。两边名字不同，
# 必须显式映射，不能直接比较导致正例全失败。
_JOURNEY_CANONICAL = {
    "f2": "f2_restart_outclosing",
    "d06": "d06_submit_readback_cleanup",
}


class _BoundedBytes:
    """EV-01：按真实**字节**计数的有界保留器。

    超过上限后继续排空 pipe（避免子进程写满管道阻塞）但不再追加保留内容；
    计数始终是字节，不因 UTF-8 分片解码而少计。UTF-8 分片在最后统一解码。
    """

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self._chunks: list[bytes] = []
        self.retained = 0
        self.total = 0

    def feed(self, chunk: bytes) -> None:
        self.total += len(chunk)
        room = self.limit - self.retained
        if room <= 0:
            return
        kept = chunk[:room]
        self._chunks.append(kept)
        self.retained += len(kept)

    @property
    def overflowed(self) -> bool:
        return self.total > self.limit

    def text(self) -> str:
        return b"".join(self._chunks).decode("utf-8", errors="replace")


def _clock():
    return datetime.now(UTC).isoformat()


class _JourneyCleanup:
    """S3-A：代际清理 owner——逆序、每 callback 最多一次、一个抛错仍尝试剩余。

    以 (generation, index, error_type) 聚合有界失败，不泄漏原始异常内容；
    close 幂等（重复调用不重复执行）。任务失败与清理失败分开保留。
    """

    def __init__(self, generation: str) -> None:
        self.generation = generation
        self._callbacks: list[tuple[str, object]] = []
        self.closed = False
        self.failures: list[dict] = []

    def register(self, closeable, *, label: str = "") -> None:
        # closeables 在 readiness 断言之前登记。
        self._callbacks.append(
            (label or getattr(closeable, "__name__", "closeable"), closeable)
        )

    def close(self) -> list[dict]:
        if self.closed:
            return self.failures
        self.closed = True
        for index in range(len(self._callbacks) - 1, -1, -1):
            _label, closeable = self._callbacks[index]
            try:
                closeable()
            except Exception as error:  # noqa: BLE001
                self.failures.append(
                    {
                        "generation": self.generation,
                        "index": index,
                        "error_type": type(error).__name__,
                    }
                )
        return self.failures

class _JourneyStopRequested(BaseException):
    """父进程关闭控制管道后的 cooperative stop：停后续步骤，进入 own finally。"""


def _stdin_open_check() -> bool:
    """子进程在步骤间非阻塞检查 stdin 管道是否仍开启。"""

    try:
        ready = select.select([sys.stdin], [], [], 0)[0]
    except (OSError, ValueError):
        return False
    if not ready:
        return True
    return sys.stdin.read(1) != ""


def _check_stop() -> None:
    """每个工具步骤入口调用；EOF 即抛 stop，资源由各 owner finally 收口。

    仅子进程模式启用（FIRST_AGENT_JOURNEY_CHILD=1）；父进程/直接运行时
    stdin 是控制台，非阻塞 select 不就绪即视为开启，不干扰交互运行。
    """

    if os.environ.get("FIRST_AGENT_JOURNEY_CHILD") != "1":
        return
    if not _stdin_open_check():
        raise _JourneyStopRequested()


def _child_emit(result: dict) -> None:
    """子进程终态协议：只在全部 owner finally 结束后输出一条 JSON。"""

    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _context() -> ToolPrepareContext:
    return ToolPrepareContext(
        conversation_id="conversation-journey",
        run_id="run-journey",
        state_revision=7,
        approval_basis_revision=7,
        goal_id="goal-journey",
        goal_revision=1,
        workspace_identity_digest="w" * 64,
    )


def _browser_lease(candidate, request_id: str):
    from agent.runtime.contracts import BrowserAuthorityLeaseV1

    return BrowserAuthorityLeaseV1.create(
        lease_id=f"browser-lease:{candidate.candidate_id}",
        candidate_digest=candidate.candidate_digest,
        goal_id=candidate.goal_id,
        goal_revision=candidate.goal_revision,
        session_ref=candidate.session_ref,
        browser_identity_digest=candidate.browser_identity_digest,
        profile_ref=candidate.profile_ref,
        profile_revision=candidate.profile_revision,
        allowed_origins=candidate.allowed_origins,
        mode=candidate.mode,
        page_id=candidate.page_id,
        frame_id=candidate.frame_id,
        observation_digest=candidate.observation_digest,
        action_digest=candidate.action_digest,
        consequence=candidate.consequence,
        approved_request_identity=request_id,
        issued_at=candidate.issued_at,
        expires_at=candidate.expires_at,
    )


def _invoke_browser_act(runtime, call: ToolCall) -> ToolResult:
    """browser_act 两阶段治理路径：approval candidate → exact browser lease。"""

    _check_stop()

    request = runtime.prepare(call, _context())
    if isinstance(request, ToolResult):
        raise RuntimeError(f"prepare failed: {request.content}")
    lease = _browser_lease(
        request.request.browser_action_candidate, request.request.request_id
    )
    intent = runtime.prepare(
        call,
        replace(_context(), browser_leases=(lease,)),
        approval=ApprovalGrant(
            request_id=request.request.request_id,
            binding_digest=request.request.binding_digest,
            approval_basis_revision=7,
        ),
    )
    if isinstance(intent, ToolResult):
        raise RuntimeError(f"prepared as error: {intent.content}")
    return runtime.invoke(intent)


def _invoke_governed(runtime, call: ToolCall, *, process_leases=()):
    from agent.runtime.contracts import ExecutionIntent

    request = runtime.prepare(
        call, replace(_context(), process_leases=tuple(process_leases))
    )
    if isinstance(request, ToolResult):
        raise RuntimeError(f"prepare failed: {request.content}")
    if isinstance(request, ExecutionIntent):
        # 无需审批的治理路径（browser_close 等）：prepare 直接给出 intent。
        return runtime.invoke(request)
    intent = runtime.prepare(
        call,
        replace(_context(), process_leases=tuple(process_leases)),
        approval=ApprovalGrant(
            request_id=request.request.request_id,
            binding_digest=request.request.binding_digest,
            approval_basis_revision=7,
    ),
    )
    if isinstance(intent, ToolResult):
        raise RuntimeError(f"prepared as error: {intent.content}")
    return runtime.invoke(intent)


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _lease(candidate) -> ProcessAuthorityLeaseV1:
    return ProcessAuthorityLeaseV1.create(
        lease_id=f"process-lease:{candidate.candidate_id}",
        candidate_digest=candidate.candidate_digest,
        goal_id=candidate.goal_id,
        goal_revision=candidate.goal_revision,
        workspace_identity_digest=candidate.workspace_identity_digest,
        command_fingerprint=candidate.command_fingerprint,
        readable_command=candidate.readable_command,
        executable_digest=candidate.executable_digest,
        argv_digest=candidate.argv_digest,
        cwd_digest=candidate.cwd_digest,
        resource_profile=candidate.resource_profile,
        environment_policy_digest=candidate.environment_policy_digest,
        execution_authority=candidate.execution_authority,
        approved_request_identity="journey-governed-approval",
        issued_at=candidate.issued_at,
        expires_at="2099-12-31T23:59:59Z",
        max_uses=8,
        uses_consumed=0,
    )


def journey_f2_restart_outclosing(base: Path) -> dict:
    """A08/F2：真实 Chromium open → 正常 shutdown → 新 owner 用旧 ref 补记。

    EV-02：每代有独立的词法清理 owner，且**取得资源后立刻登记、再运行可能失败
    的 readiness/open/ledger 检查**——任何一点抛异常都由本代 finally 收口。
    第一代确认清理并核对 durable ledger 后，才创建第二代；第一代失败不启动
    第二代。清理失败有界聚合（逆序、每 callback 至多一次、一个抛错仍尝试剩余），
    任务失败与清理失败按有界错误码分别保留。constructor 在返回前失败的资源由
    constructor 自己负责——调用者拿不到 handle，也不假装清理过。
    """

    _check_stop()

    workspace = base / "workspace"
    workspace.mkdir()
    state_root = base / "state"

    # ---- 第一代 ----
    generation1 = _JourneyCleanup("gen1")
    generation1_failures: list[dict] = []
    generation1_failure: str | None = None
    session_ref: str | None = None
    try:
        resources1 = build_browser_resources(workspace, state_root, enabled=True)
        for closeable in resources1.closeables:
            generation1.register(closeable)
        if resources1.readiness.value != "ready":
            generation1_failure = "generation1_not_ready"
        else:
            runtime1 = KernelToolRuntime(resources1.registrations, clock=_clock)
            opened = _invoke_governed(
                runtime1,
                ToolCall("open-1", "browser_open", {"mode": "public_read_ephemeral"}),
            )
            if isinstance(opened, ToolResult) and opened.is_error is False:
                session_ref = opened.metadata["session_ref"]
            else:
                generation1_failure = "generation1_open_failed"
    except _JourneyStopRequested:
        generation1_failure = "stopped_by_parent"
    except Exception as error:  # noqa: BLE001
        generation1_failure = f"generation1_{type(error).__name__}"
    finally:
        generation1_failures = generation1.close()
    if generation1_failures:
        return {
            "journey": "f2_restart_outclosing",
            "passed": False,
            "cleanup_confirmed": False,
            "failure_codes": ["generation1_cleanup_failed"],
            "cleanup_failures": generation1_failures,
        }
    if generation1_failure is not None:
        return {
            "journey": "f2_restart_outclosing",
            "passed": False,
            "cleanup_confirmed": True,
            "failure_codes": [generation1_failure],
        }
    # 第一代已确认清理：核对 durable ledger 后才允许创建第二代。
    try:
        record = BrowserSessionStore(root=state_root / "browser" / "sessions").load(
            session_ref
        )
    except _JourneyStopRequested:
        return {
            "journey": "f2_restart_outclosing",
            "passed": False,
            "cleanup_confirmed": True,
            "failure_codes": ["stopped_by_parent"],
        }
    except Exception as error:  # noqa: BLE001
        return {
            "journey": "f2_restart_outclosing",
            "passed": False,
            "cleanup_confirmed": True,
            "failure_codes": [f"generation1_ledger_{type(error).__name__}"],
        }
    credential = record.phase is SessionPhase.CLOSED
    if not credential:
        # 第一代未确认收口：不启动第二代（不掩盖清理缺口）。清理本身已确认
        # （generation1_failures 为空），失败在 target 层。
        return {
            "journey": "f2_restart_outclosing",
            "passed": False,
            "cleanup_confirmed": True,
            "failure_codes": ["generation1_ledger_not_closed"],
        }

    # ---- 第二代 ----
    generation2 = _JourneyCleanup("gen2")
    generation2_failures: list[dict] = []
    generation2_failure: str | None = None
    closed: ToolResult | None = None
    try:
        resources2 = build_browser_resources(workspace, state_root, enabled=True)
        for closeable in resources2.closeables:
            generation2.register(closeable)
        runtime2 = KernelToolRuntime(resources2.registrations, clock=_clock)
        closed = _invoke_governed(
            runtime2,
            ToolCall("close-2", "browser_close", {"session_ref": session_ref}),
        )
    except _JourneyStopRequested:
        generation2_failure = "stopped_by_parent"
    except Exception as error:  # noqa: BLE001
        generation2_failure = f"generation2_{type(error).__name__}"
    finally:
        generation2_failures = generation2.close()
    if generation2_failures:
        return {
            "journey": "f2_restart_outclosing",
            "passed": False,
            "cleanup_confirmed": False,
            "failure_codes": ["generation2_cleanup_failed"],
            "cleanup_failures": generation2_failures,
        }
    if generation2_failure is not None:
        return {
            "journey": "f2_restart_outclosing",
            "passed": False,
            "cleanup_confirmed": True,
            "failure_codes": [generation2_failure],
        }
    ok = (
        isinstance(closed, ToolResult)
        and closed.is_error is False
        and closed.metadata.get("cleanup_outcome") == "cleaned"
        and closed.metadata.get("closure_basis") == "durable_ledger_closed"
        and credential
    )
    return {
        "journey": "f2_restart_outclosing",
        "passed": bool(ok),
        "cleanup_confirmed": True,
        "session_ref": session_ref,
        "cleanup_outcome": closed.metadata.get("cleanup_outcome"),
        "closure_basis": closed.metadata.get("closure_basis"),
        "credential_persisted": credential,
        "cleanup_failures": generation2_failures,
    }


def _invoke_with_lease(runtime, call: ToolCall) -> ToolResult:
    """LOCAL_SAME_UID_PROCESS 两阶段治理路径：candidate → exact lease → invoke。"""

    _check_stop()

    request = runtime.prepare(call, _context())
    if isinstance(request, ToolResult):
        raise RuntimeError(f"prepare failed: {request.content}")
    lease = _lease(request.request.process_authority_candidate)
    intent = runtime.prepare(
        call, replace(_context(), process_leases=(lease,)),
        approval=ApprovalGrant(
            request_id=request.request.request_id,
            binding_digest=request.request.binding_digest,
            approval_basis_revision=7,
        ),
    )
    if isinstance(intent, ToolResult):
        raise RuntimeError(f"prepared as error: {intent.content}")
    return runtime.invoke(intent)


def journey_d06_submit_readback_cleanup(base: Path, candidate: Path) -> dict:
    """A13/D06：真实浏览器提交后列表更新；start/open/act/close/stop 全走治理路径。

    EV-02：managed_web 与 browser 两组资源各自登记到同一个逆序清理 owner，且
    **取得即登记**——readiness 检查、start/open/act/close/stop 任一点抛异常都由
    finally 收口。清理失败不掩盖任务失败：两者按有界错误码分别保留，一个回调
    抛错仍尝试剩余回调。
    """

    workspace = base / "workspace"
    workspace.mkdir(exist_ok=True)
    state_root = base / "state"
    owner = _JourneyCleanup("d06")
    target_failure: str | None = None
    result_payload: dict | None = None
    try:
        managed = build_managed_web_resources(
            candidate, captured_path="/usr/bin:/bin:/usr/local/bin"
        )
        for closeable in managed.closeables:
            owner.register(closeable)
        port = _free_port()
        runtime_m = KernelToolRuntime(managed.registrations, clock=_clock)
        started = _invoke_with_lease(
            runtime_m,
            ToolCall(
                "mstart-1",
                "managed_web_start",
                {
                    "executable": sys.executable,
                    "argv": [str(candidate / "server.py"), "--port", str(port)],
                    "cwd": ".",
                    "profile": "long",
                    "loopback_port": port,
                },
            ),
        )
        resource_ref = json.loads(started.content)["resource_ref"]
        browser_resources = build_browser_resources(
            workspace, state_root, enabled=True, loopback_authority=managed.owner
        )
        for closeable in browser_resources.closeables:
            owner.register(closeable)
        if browser_resources.readiness.value != "ready":
            target_failure = "browser_not_ready"
        else:
            runtime_b = KernelToolRuntime(browser_resources.registrations, clock=_clock)
            opened = _invoke_governed(
                runtime_b,
                ToolCall(
                    "open-1",
                    "browser_open",
                    {
                        "mode": "task_loopback_ephemeral",
                        "managed_process_ref": resource_ref,
                    },
                ),
            )
            session_ref = opened.metadata["session_ref"]
            observed = _invoke_governed(
                runtime_b,
                ToolCall(
                    "observe-1", "browser_observe", {"session_ref": session_ref}
                ),
            )
            first_view = json.loads(observed.content)
            target = next(
                (ref for ref in first_view["element_refs"] if ref["role"] == "textbox"),
                None,
            )
            if target is None:
                raise RuntimeError("fixture textbox not found in ARIA projection")
            button = next(
                (ref for ref in first_view["element_refs"] if ref["role"] == "button"),
                None,
            )
            if button is None:
                raise RuntimeError("fixture submit button not found in ARIA projection")
            acted = _invoke_browser_act(
                runtime_b,
                ToolCall(
                    "act-1",
                    "browser_act",
                    {
                        "session_ref": session_ref,
                        "kind": "fill_form",
                        "observation_digest": observed.metadata["observation_digest"],
                        "page_id": observed.metadata["page_id"],
                        "frame_id": observed.metadata["frame_id"],
                        "target_ref": target["ref"],
                        "params": {"fields": {target["name"]: "journey item 42"}},
                    },
                ),
            )
            assert acted.metadata.get("outcome") == "effect_applied"
            observed2 = _invoke_governed(
                runtime_b,
                ToolCall(
                    "observe-2", "browser_observe", {"session_ref": session_ref}
                ),
            )
            assert observed2.metadata["observation_digest"]
            acted2 = _invoke_browser_act(
                runtime_b,
                ToolCall(
                    "act-2",
                    "browser_act",
                    {
                        "session_ref": session_ref,
                        "kind": "click",
                        "observation_digest": observed2.metadata["observation_digest"],
                        "page_id": observed2.metadata["page_id"],
                        "frame_id": observed2.metadata["frame_id"],
                        "target_ref": button["ref"],
                    },
                ),
            )
            assert acted2.metadata.get("outcome") == "effect_applied"
            observed3 = _invoke_governed(
                runtime_b,
                ToolCall(
                    "observe-3", "browser_observe", {"session_ref": session_ref}
                ),
            )
            final_view = json.loads(observed3.content)
            # ARIA 投影中 li 不携带文本 name：以 li 数量变化证明"提交后列表更新"。
            list_updated = (
                final_view["aria_projection"].count("- li")
                > first_view["aria_projection"].count("- li")
            )
            closed = _invoke_governed(
                runtime_b,
                ToolCall("close-1", "browser_close", {"session_ref": session_ref}),
            )
            stopped = runtime_m.invoke(
                runtime_m.prepare(
                    ToolCall("mstop-1", "managed_web_stop", {"resource_ref": resource_ref}),
                    _context(),
                )
            )
            ok = (
                list_updated
                and closed.is_error is False
                and closed.metadata.get("cleanup_outcome") == "cleaned"
                and json.loads(stopped.content).get("cleanup") == "confirmed"
            )
            result_payload = {
                "journey": "d06_submit_readback_cleanup",
                "passed": bool(ok),
                "list_updated_after_submit": list_updated,
                "browser_close": closed.metadata.get("cleanup_outcome"),
                "managed_web_stop": json.loads(stopped.content).get("cleanup"),
                # R3b 分层：工具层 receipts（上面）/观察层（li 计数）/业务层（冻结
                # 外置 grader 单独运行，不在此签署）；一层不能替代另一层。
                "layers": {
                    "tool_receipts": {
                        "open": opened.is_error is False,
                        "action_applied": (
                            acted.metadata.get("outcome") == "effect_applied"
                            and acted2.metadata.get("outcome") == "effect_applied"
                        ),
                        "close": closed.metadata.get("cleanup_outcome"),
                        "managed_stop": json.loads(stopped.content).get("cleanup"),
                    },
                    "observation_layer": {
                        "li_count_first": first_view["aria_projection"].count("- li"),
                        "li_count_final": final_view["aria_projection"].count("- li"),
                    },
                    "business_layer": (
                        "frozen external grader runs separately (d06_app_behavior.test.mjs)"
                    ),
                },
                "final_aria": final_view["aria_projection"][:400],
                "first_aria": first_view["aria_projection"][:400],
            }
    except _JourneyStopRequested:
        target_failure = "stopped_by_parent"
    except Exception as error:  # noqa: BLE001
        # 有界错误码：只保留异常类型名，不把原始消息/路径写入报告。
        target_failure = f"d06_{type(error).__name__}"
    finally:
        cleanup_failures = owner.close()
    cleanup_confirmed = not cleanup_failures
    if result_payload is None:
        # 任务失败与清理失败分别保留；两者都不能总体 PASS。
        codes = [target_failure or "d06_target_incomplete"]
        if not cleanup_confirmed:
            codes.append("d06_cleanup_failed")
        return {
            "journey": "d06_submit_readback_cleanup",
            "passed": False,
            "cleanup_confirmed": cleanup_confirmed,
            "failure_codes": codes,
            "cleanup_failures": cleanup_failures,
        }
    result_payload["cleanup_confirmed"] = cleanup_confirmed
    if not cleanup_confirmed:
        # 清理失败保留为有界错误码；target 结果照常上报，但两者都不能总体 PASS。
        result_payload["passed"] = False
        result_payload["failure_codes"] = ["d06_cleanup_failed"]
    result_payload["cleanup_failures"] = cleanup_failures
    return result_payload


def _run_bounded(journey: str, base: Path, *, budget_seconds: float) -> dict:
    """EV-01/EV-03：每条旅程一个隐藏子进程；stdin 管道 = cooperative stop 通道。

    有界性（EV-01）：工作 deadline 在启动前算出并独立 latch——即使 child 在
    select 返回前刚好退出，只要墙钟已过期限，本次运行就不是成功。读取用非阻塞
    select 切片，stdout/stderr 各有真实**字节**保留上限；超限后仍排空 pipe
    （避免写端阻塞）但不再追加保留。收尾排空与清理各有独立期限，不等待无限
    EOF（继承 pipe 的后代不能让父进程挂住）。

    协议（EV-03）：child 记录里的 journey 名经 ``_JOURNEY_CANONICAL`` 映射后与
    本次请求比对；只有本次预期身份、字段类型合法、目标检查通过、清理确认且
    child 正常退出（exit 0、非 signal）的记录才允许 PASS。
    """

    import contextlib
    import math

    failure_codes: list[str] = []

    def failure(codes: list[str], **extra: object) -> dict:
        result = {
            "journey": journey,
            "passed": False,
            "timeout": False,
            "worker_terminated": False,
            "resource_cleanup_confirmed": False,
            "target_checks_passed": False,
            "failure_codes": list(codes),
            "retained_base": str(base),
        }
        result.update(extra)
        return result

    if not isinstance(budget_seconds, (int, float)) or isinstance(
        budget_seconds, bool
    ):
        return failure(["budget_not_finite"])
    if not math.isfinite(float(budget_seconds)) or budget_seconds <= 0:
        return failure(["budget_not_finite"])

    env = dict(os.environ)
    env["FIRST_AGENT_JOURNEY_CHILD"] = "1"
    child = subprocess.Popen(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--child",
            journey,
            str(base),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        text=False,
        cwd=str(ROOT),
        start_new_session=True,
    )
    try:
        pgid = verified_group_identity(child.pid)
    except Exception:  # noqa: BLE001
        failure_codes.append("group_identity_unverified")
        pgid = None
    opened_at = time.monotonic()
    deadline = opened_at + budget_seconds
    stdout_sink = _BoundedBytes(_CHILD_STDOUT_LIMIT)
    stderr_sink = _BoundedBytes(_CHILD_STDERR_LIMIT)

    # EOF 后 pipe 会持续"可读"（读到空）：必须把已关闭的流移出 select 集合，
    # 否则排空循环会空转到期限。
    live_streams = [child.stdout, child.stderr]

    def _read_available(stream) -> None:  # noqa: ANN001
        """读取当前可读的字节：select 已确认可读，``read1`` 不再等待补满缓冲区。"""

        with contextlib.suppress((OSError, ValueError)):
            # 二进制 pipe：read1 只返回当前可用字节，不等待补满缓冲区。
            chunk = stream.read1(65536)
            if chunk:
                sink = stdout_sink if stream is child.stdout else stderr_sink
                sink.feed(chunk)
            elif stream in live_streams:
                live_streams.remove(stream)

    def _drain_once(timeout: float) -> None:
        """非阻塞切片读取；不等待 EOF（继承写端的后代不能让父进程挂住）。"""

        if not live_streams:
            if timeout:
                time.sleep(timeout)
            return
        try:
            readable, _, _ = select.select(live_streams, [], [], timeout)
        except (OSError, ValueError):
            return
        for stream in readable:
            _read_available(stream)

    while True:
        if child.poll() is not None:
            break
        _drain_once(_SELECT_SLICE_SECONDS)
        if time.monotonic() >= deadline:
            break
    # EV-01：deadline latch 独立于 child 状态。墙钟越过期限即如实记为超时——
    # 即使 child 恰好在同一轮刚退出，超期运行也不变成成功。观测分辨率上界是
    # 一次 select 切片（``_SELECT_SLICE_SECONDS``），这是合同允许的 scheduler
    # 分辨率误差，不是漏判量级超时。
    elapsed_timeout = time.monotonic() >= deadline
    if elapsed_timeout:
        failure_codes.append("work_budget_timeout")
        with contextlib.suppress(OSError):
            child.stdin.close()
        # cooperative 清理宽限：等 child 在 15s 内自行收口（finally + 终态 JSON）。
        coop_deadline = time.monotonic() + _COOPERATIVE_CLEANUP_SECONDS
        while child.poll() is None and time.monotonic() < coop_deadline:
            _drain_once(_SELECT_SLICE_SECONDS)
    if stdout_sink.overflowed or stderr_sink.overflowed:
        failure_codes.append("output_limit")
    if child.poll() is None and pgid is not None:
        # cooperative 停止失败：仅对本次 verified group 有界 terminate。
        from agent.process.group import ProcessCleanupError

        try:
            terminate_group(
                child,
                pgid,
                term_grace_seconds=_TERM_GRACE_SECONDS,
                kill_grace_seconds=_KILL_GRACE_SECONDS,
            )
        except ProcessCleanupError:
            failure_codes.append("group_termination_unverified")
    worker_terminated = child.poll() is not None and (
        pgid is None or not group_alive(pgid)
    )
    if not worker_terminated:
        failure_codes.append("worker_not_terminated")
    # 读取子进程终态（全部 owner finally 后的一条 JSON）。
    if child.poll() is None:
        with contextlib.suppress(subprocess.TimeoutExpired):
            child.wait(timeout=_POST_KILL_VERIFY_SECONDS)
    # 收尾排空只读"已缓冲"的残余（select 0 超时，非阻塞）：独立后代可能仍
    # 继承写端，全量 read() 会等 EOF 被拖到后代自然退出（实测 30s）。
    drain_deadline = time.monotonic() + _DRAIN_DEADLINE_SECONDS
    while live_streams and time.monotonic() < drain_deadline:
        try:
            readable, _, _ = select.select(live_streams, [], [], 0)
        except (OSError, ValueError):
            break
        if not readable:
            break
        for stream in readable:
            _read_available(stream)
    full_out = stdout_sink.text()
    if (
        stdout_sink.overflowed or stderr_sink.overflowed
    ) and "output_limit" not in failure_codes:
        failure_codes.append("output_limit")
    # poll() 是既有访问器：进程已 reap 时返回退出码，运行中返回 None。
    exit_status = child.poll()
    if exit_status is None:
        failure_codes.append("child_exit_unobserved")
    elif exit_status < 0:
        failure_codes.append("child_exit_signal")
    elif exit_status != 0:
        failure_codes.append("child_exit_nonzero")
    # 协议校验：恰好一条 JSON 记录；必需字段齐全；布尔必须真 bool；journey
    # 必须是本次请求经唯一映射后的规范名。
    reports = []
    for line in full_out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            reports.append(json.loads(line))
        except json.JSONDecodeError:
            failure_codes.append("child_non_json_output")
    if len(reports) != 1:
        failure_codes.append("child_protocol_no_single_record")
        report = None
    else:
        report = reports[0]
    cleanup_confirmed = False
    target_checks_passed = False
    if report is None or not isinstance(report, dict):
        failure_codes.append("child_protocol_invalid_record")
    else:
        required = {
            "journey",
            "target_checks_passed",
            "resource_cleanup_confirmed",
            "failure_codes",
            "details",
        }
        missing = required - set(report)
        if missing:
            failure_codes.append("child_protocol_missing_fields")
        else:
            bad_types = (
                not isinstance(report.get("target_checks_passed"), bool)
                or not isinstance(report.get("resource_cleanup_confirmed"), bool)
                or not isinstance(report.get("failure_codes"), list)
            )
            if bad_types:
                failure_codes.append("child_protocol_bad_types")
            else:
                expected_journey = _JOURNEY_CANONICAL.get(journey, journey)
                if report.get("journey") != expected_journey:
                    failure_codes.append("child_journey_mismatch")
                cleanup_confirmed = report["resource_cleanup_confirmed"]
                target_checks_passed = report["target_checks_passed"]
                child_codes = report["failure_codes"]
                if child_codes:
                    failure_codes.extend(str(c) for c in child_codes[:8])
    verdict = {
        "journey": journey,
        "timeout": elapsed_timeout,
        "worker_terminated": bool(worker_terminated),
        "resource_cleanup_confirmed": bool(cleanup_confirmed),
        "target_checks_passed": bool(target_checks_passed),
        "passed": bool(
            (not elapsed_timeout)
            and worker_terminated
            and cleanup_confirmed
            and target_checks_passed
            and not failure_codes
        ),
        "failure_codes": failure_codes,
        "retained_base": str(base) if failure_codes else None,
        "details": {
            "stdout_bytes": stdout_sink.total,
            "stderr_bytes": stderr_sink.total,
            "stdout_retained": stdout_sink.retained,
            "stderr_retained": stderr_sink.retained,
            "child_exit_status": exit_status,
            "child_details": report if isinstance(report, dict) else None,
        },
    }
    return verdict


def main() -> int:
    import argparse
    import shutil

    parser = argparse.ArgumentParser()
    parser.add_argument("--journey", choices=("f2", "d06", "all"), default="all")
    parser.add_argument("--budget-seconds", type=float, default=120.0)
    parser.add_argument(
        "--child",
        nargs=2,
        metavar=("JOURNEY", "BASE"),
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()
    if args.child is not None:
        os.environ["FIRST_AGENT_JOURNEY_CHILD"] = "1"
        return _run_child(args.child[0], Path(args.child[1]))

    bases: list[Path] = []
    results: list[dict] = []
    order = ("f2", "d06") if args.journey == "all" else (args.journey,)
    for journey in order:
        journey_base = Path(
            tempfile.mkdtemp(prefix=f"first-agent-journey-{journey}-")
        ).resolve()
        bases.append(journey_base)
        verdict = _run_bounded(
            journey, journey_base, budget_seconds=args.budget_seconds
        )
        results.append(verdict)
        if not verdict.get("passed"):
            # timeout/协议失败/target 失败/cleanup 未确认：停止 all 的下一条。
            break
    for index, (result, base) in enumerate(zip(results, bases, strict=True)):
        if (
            result.get("passed")
            and result.get("resource_cleanup_confirmed") is True
        ):
            # 只有成功且资源已确认清理才删除本次精确临时目录。
            import shutil

            shutil.rmtree(base, ignore_errors=True)
        else:
            results[index]["retained_base"] = str(base)
    print(json.dumps({"results": results}, ensure_ascii=False, indent=2))
    return 0 if results and all(item["passed"] for item in results) else 1


def _journey_disposition(result: dict) -> tuple[bool, bool]:
    """EV-03：从旅程结果区分 (target_checks_passed, resource_cleanup_confirmed)。

    旅程显式声明 ``cleanup_confirmed``（清理回调全部执行且无失败）。字段缺失时
    保守回落到 ``cleanup_failures`` 是否为空，仍缺失则 False——不把"没有清理
    证据"当成清理成功。两类失败都不允许总体 PASS。
    """

    passed = result.get("passed") is True
    declared = result.get("cleanup_confirmed")
    if isinstance(declared, bool):
        return passed, declared
    cleanup_failures = result.get("cleanup_failures")
    if isinstance(cleanup_failures, list):
        return passed, not cleanup_failures
    return passed, False


def _run_child(journey: str, base: Path) -> int:
    """隐藏子进程模式：同步运行既有旅程；异常时输出有界协议失败记录。

    EV-03：记录里的 journey 名是**规范名**（``_JOURNEY_CANONICAL``）；父进程用
    同一映射比对，外部参数名与内部规范名不同不会导致正例失败。退出码：全部
    target 与清理都确认才 0；否则 1（父进程同时按退出码与记录判定）。
    """

    canonical = _JOURNEY_CANONICAL.get(journey)
    try:
        if journey == "f2":
            result = journey_f2_restart_outclosing(base)
        elif journey == "d06":
            import shutil

            candidate = base / "d06-candidate"
            shutil.copytree(D06_FIXTURE, candidate)
            app = candidate / "web" / "app.mjs"
            app.write_text(
                app.read_text(encoding="utf-8").replace(
                    '    input.value = "";\n',
                    '    input.value = "";\n    render();\n',
                ),
                encoding="utf-8",
            )
            result = journey_d06_submit_readback_cleanup(base, candidate)
        else:
            _child_emit(
                {
                    "journey": journey,
                    "target_checks_passed": False,
                    "resource_cleanup_confirmed": False,
                    "failure_codes": ["unknown_journey"],
                    "details": {},
                }
            )
            return 1
        target_passed, cleanup_confirmed = _journey_disposition(result)
        journey_codes = [
            str(code) for code in (result.get("failure_codes") or [])[:8]
        ]
        _child_emit(
            {
                "journey": canonical,
                "target_checks_passed": target_passed,
                "resource_cleanup_confirmed": cleanup_confirmed,
                "failure_codes": journey_codes,
                "details": result,
            }
        )
        return 0 if (target_passed and cleanup_confirmed) else 1
    except BaseException as error:  # noqa: BLE001
        if isinstance(error, _JourneyStopRequested):
            codes = ["stopped_by_parent"]
        else:
            codes = [f"child_{type(error).__name__}"]
        _child_emit(
            {
                "journey": canonical if canonical is not None else journey,
                "target_checks_passed": False,
                "resource_cleanup_confirmed": False,
                "failure_codes": codes,
                "details": {},
            }
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
