"""018 Playwright Chromium public-read adapter 与 egress guard（Task 3）。

adapter 是唯一 Playwright/Chromium owner：sync API 与所有 browser 对象只
存在于此处的 worker thread，caller 只交换 bounded typed request/response，
永远接触不到 Playwright 对象。本模块不 import Provider/Runtime、不推进
ConversationState、不做自授权；顶层不 import playwright（base install 可
安全加载，缺包时 fail closed 返回 ``browser_package_missing``）。

egress：HTTP(S) 用 ``route("**/*")`` 单 hop fetch（禁止自动 redirect），
WebSocket 用 ``route_web_socket`` pre-connect gate，popup 另经 ``on("page")``
收口。document/redirect/frame/subresource/WebSocket/popup 每个事件都在目标
send/connect 之前经过同一 ``BrowserEgressGuard``（session 绑定的 mode/
allowed_origins）；拒绝即 abort/close，目标 send 计数不动。

ARIA 观察与 click re-resolve 只用真实 Playwright 1.62 接口：固定
``evaluate`` 脚本收集 element refs（value 原文与 secret 空/非空都不离开
页面）、``get_by_role`` locator 点击、``mouse.wheel`` 滚动。真实
Chromium engine 证据由 018 U2 的 sealed materialized 三连 E3 提供；本模块的
deterministic unit tests 仍只经注入 fake 验证合同。
"""

from __future__ import annotations

import contextlib
import mimetypes
import os
import queue
import re
import secrets
import socket
import stat
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

from agent.browser.action_policy import BrowserActionPolicy
from agent.browser.contracts import (
    BrowserActionKind,
    BrowserActionOutcome,
    BrowserActionReceiptV1,
    BrowserActionV1,
    BrowserCleanupOutcome,
    BrowserCleanupReceiptV1,
    BrowserHandleV1,
    BrowserMode,
    BrowserObservationV1,
    BrowserSessionSpecV1,
)
from agent.browser.observation import (
    ObservationIdentityV1,
    RawAriaNodeV1,
    RawBrowserSnapshotV1,
    project_aria_snapshot,
)
from agent.browser.ports import BrowserOpenNotStartedError, BrowserUnavailableError
from agent.browser.quarantine import BrowserQuarantine, BrowserQuarantineError
from agent.browser.staging import BrowserUploadStagingV1
from agent.browser.url_policy import (
    AdmittedURLV1,
    BrowserURLPolicy,
    URLPolicyError,
)
from agent.runtime.contracts import KnownNotExecuted, canonical_json_digest

# public-read 的 closed action set（spec §4.1）；fill/upload/download 等 write
# 系 action 在任何 Playwright 调用之前拒绝。
PUBLIC_READ_ACTION_KINDS = frozenset(
    {
        BrowserActionKind.NAVIGATE,
        BrowserActionKind.BACK,
        BrowserActionKind.RELOAD,
        BrowserActionKind.SCROLL,
        BrowserActionKind.CLICK,
    }
)

# site-bound interactive 的 v1 action set：upload/download 的 staging/
# quarantine 属于 Task 7，本任务在 policy 层完成 consequence 分类、在
# adapter 层拒绝执行（不静默降级）。
INTERACTIVE_ACTION_KINDS = frozenset(
    {
        BrowserActionKind.NAVIGATE,
        BrowserActionKind.BACK,
        BrowserActionKind.RELOAD,
        BrowserActionKind.SCROLL,
        BrowserActionKind.CLICK,
        BrowserActionKind.SELECT,
        BrowserActionKind.FILL_FORM,
        BrowserActionKind.UPLOAD,
        BrowserActionKind.DOWNLOAD,
    }
)

# 与 BrowserProfileStore 同一 closed opaque identity；adapter 只做 closed
# validate + no-follow canonical 校验，不读取 profile 内容、不造第二 owner。
PROFILE_ID_PATTERN = re.compile(r"profile-[0-9a-f]{16}")

DEFAULT_TIMEOUT_MS = 10_000
MAX_TIMEOUT_MS = 30_000
_QUEUE_CAPACITY = 64
_PUT_TIMEOUT_SECONDS = 5.0
_IDLE_QUEUE_TIMEOUT_SECONDS = 0.05
_IDLE_BROWSER_PUMP_MS = 25
SCROLL_DELTA = 600
MAX_REDIRECT_HOPS = 10
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})

# 固定 adapter 脚本（不是模型输入）：refs 在浏览器内完成 secret/空值判定，
# 任何 input value 原文都不回传。marker 供 fake 识别同一真实接口。
COLLECT_ELEMENT_REFS_SCRIPT = """
() => {
  // __first_agent_collect_element_refs__
  const SECRET_INPUT_TYPES = new Set(["password", "secret", "hidden"]);
  const refs = [];
  const roleOf = (element) => {
    const explicit = element.getAttribute("role");
    if (explicit) return explicit;
    const tag = element.tagName.toLowerCase();
    if (tag === "a" && element.hasAttribute("href")) return "link";
    if (tag === "button") return "button";
    if (tag === "textarea") return "textbox";
    if (tag === "select") return "combobox";
    if (tag === "input") {
      const type = (element.getAttribute("type") || "text").toLowerCase();
      if (["button", "submit", "reset"].includes(type)) return "button";
      if (type === "checkbox") return "checkbox";
      if (type === "radio") return "radio";
      if (!["hidden", "file"].includes(type)) return "textbox";
    }
    if (/^h[1-6]$/.test(tag)) return "heading";
    if (tag === "img") return "img";
    return tag;
  };
  const labelOf = (element) => {
    if (element.labels && element.labels.length > 0) {
      return element.labels[0].innerText.slice(0, 128) || null;
    }
    const aria = element.getAttribute("aria-label");
    return aria ? aria.slice(0, 128) : null;
  };
  const walk = (element, depth) => {
    if (refs.length >= 4096 || depth > 15 || !element) return;
    const role = roleOf(element);
    const name = labelOf(element);
    const isInput = element.tagName === "INPUT";
    const inputType = isInput ? (element.getAttribute("type") || "text") : null;
    const form = element.form;
    const formAction =
      form && form.getAttribute("action") ? form.getAttribute("action").slice(0, 256) : null;
    const formMethod =
      form && form.getAttribute("method") ? form.getAttribute("method").toUpperCase() : null;
    let valueEmpty = null;
    if (inputType !== null && !SECRET_INPUT_TYPES.has(inputType)) {
      valueEmpty = element.value === "";
    }
    refs.push({
      ref: "e" + refs.length, role: role, name: name, depth: depth,
      input_type: inputType, form_action: formAction, form_method: formMethod,
      value_empty: valueEmpty,
    });
    for (const child of element.children) walk(child, depth + 1);
  };
  walk(document.body, 0);
  return refs;
}
"""


class BrowserActionRefusedError(Exception):
    """当前 mode 不允许该 action；发生在任何 Playwright 调用之前。"""


class BrowserEffectReceiptError(Exception):
    """effect 已发生但 post-observation/receipt 构建失败。

    binding 已在首个 effect 前消费（replay 会得到 browser_binding_changed）；
    session 不 poison——页面状态未知但单一 action 的重复已被挡住。"""


class BrowserCleanupUnknownError(Exception):
    """composition shutdown 的 fail-closed：session cleanup UNKNOWN 或
    worker 存活。session 已标记 unusable；无 fallback、不伪装成功。"""


class RequestKind(StrEnum):
    """每类 request 事件都经同一个 guard（无类别豁免）。"""

    DOCUMENT = "document"
    REDIRECT = "redirect"
    POPUP = "popup"
    FRAME = "frame"
    SUBRESOURCE = "subresource"
    WEBSOCKET = "websocket"


@dataclass(frozen=True, slots=True)
class BrowserQualificationV1:
    """startup 只读 qualification；不可用给一条 closed reason。"""

    ready: bool
    reason_code: str | None


class SocketAddressResolver:
    """production resolver：getaddrinfo 全量 A/AAAA；失败返回空（fail closed）。"""

    def resolve(self, host: str) -> tuple[str, ...]:
        try:
            infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        except OSError:
            return ()
        return tuple({info[4][0] for info in infos})


class _BrowserTransport:
    """production transport：send 即浏览器导航/请求实际发生。"""

    def send(self, url: str) -> None:
        return None


def _real_playwright_factory() -> Any:
    # lazy import：base install（无 playwright）加载本模块不受影响。
    from playwright.sync_api import sync_playwright

    return sync_playwright()


def _classify_request(
    request: Any,
    *,
    explicit_navigation_url: str | None = None,
    primary_page: Any | None = None,
) -> RequestKind:
    """真实 Playwright Request → closed 事件分类（redirected_from 是 property）。"""
    if request.resource_type == "websocket":
        return RequestKind.WEBSOCKET
    if request.redirected_from is not None:
        return RequestKind.REDIRECT
    if request.is_navigation_request():
        try:
            frame = request.frame
        except Exception:  # noqa: BLE001 - 初始导航尚未创建 frame
            if request.url == explicit_navigation_url:
                return RequestKind.DOCUMENT
            # popup 的首个 request 在 Chromium 创建 Frame 前进入 route；它
            # 不可能是已绑定的 exact top-level navigate。按 POPUP 归类只
            # 收紧 closed telemetry，所有类别仍走同一 admission policy。
            return RequestKind.POPUP
        try:
            frame_page = frame.page if frame is not None else None
            opener = frame_page.opener() if frame_page is not None else None
        except Exception:  # noqa: BLE001 - 初始 popup frame 可能尚未完整绑定
            frame_page = None
            opener = None
        if opener is not None or (
            primary_page is not None
            and frame_page is not None
            and frame_page is not primary_page
        ):
            return RequestKind.POPUP
        if frame is not None and frame.parent_frame is not None:
            return RequestKind.FRAME
        return RequestKind.DOCUMENT
    return RequestKind.SUBRESOURCE


def _origin_of(url: str) -> str:
    parts = urlsplit(url)
    # netloc 保留显式 port（页面 URL 不携带 userinfo）。
    return f"{parts.scheme}://{parts.netloc.lower()}"


def _redirect_location(response: Any) -> str | None:
    """只识别 HTTP redirect status + 非空 Location；header 名大小写无关。"""
    if getattr(response, "status", None) not in _REDIRECT_STATUSES:
        return None
    headers = getattr(response, "headers", {})
    if not isinstance(headers, dict):
        return None
    for name, value in headers.items():
        if str(name).casefold() == "location" and isinstance(value, str) and value:
            return value
    return None


def _best_effort_close(target: Any) -> None:
    # 兜底收尾尽力而为：清理异常不得掩盖原始错误。
    with contextlib.suppress(Exception):
        target.close()


def _already_closed(target: Any) -> bool:
    closed = getattr(target, "closed", None)
    if isinstance(closed, bool):
        return closed
    is_closed = getattr(target, "is_closed", None)
    return callable(is_closed) and is_closed()


def _browser_is_closed(browser: Any) -> bool:
    is_closed = getattr(browser, "is_closed", None)
    if callable(is_closed):
        return bool(is_closed())
    return bool(getattr(browser, "closed", False))


class BrowserEgressGuard:
    """adapter-owned SSRF guard：唯一记账 seam。

    ``admit_request`` 是纯 admission（attempt+1、policy 判定、rebinding 检查），
    不计 send；``record_send`` 只在真实 continuation/effect 发生后调用；
    ``is_admissible`` 是不计数纯查询（navigate 预检、popup containment）。
    同一 origin 的 address-set digest 漂移（DNS rebinding）fail closed。
    注入只经 constructor seam，不存在 allow_private/disable_guard 开关。
    """

    def __init__(self, *, resolver: Any, transport: Any) -> None:
        self._policy = BrowserURLPolicy(resolver=resolver)
        self._transport = transport
        self._attempts = 0
        self._sends = 0
        self._attempts_by_kind = {kind: 0 for kind in RequestKind}
        self._rejections_by_kind = {kind: 0 for kind in RequestKind}
        self._sends_by_kind = {kind: 0 for kind in RequestKind}
        self._origin_addresses: dict[str, str] = {}

    @property
    def attempts(self) -> int:
        return self._attempts

    @property
    def sends(self) -> int:
        return self._sends

    def attempts_for(self, kind: RequestKind) -> int:
        return self._attempts_by_kind[kind]

    def rejections_for(self, kind: RequestKind) -> int:
        return self._rejections_by_kind[kind]

    def sends_for(self, kind: RequestKind) -> int:
        return self._sends_by_kind[kind]

    def _admit(
        self,
        kind: RequestKind,
        url: str,
        *,
        mode: BrowserMode,
        allowed_origins: tuple[str, ...],
    ) -> AdmittedURLV1:
        # wss 与 https 同一安全语义（安全 WebSocket）；ws:// 不归一，仍被
        # https-only policy 拒绝。
        admit_url = url
        if kind is RequestKind.WEBSOCKET and url.startswith("wss://"):
            admit_url = "https://" + url[len("wss://"):]
        admitted = self._policy.admit(admit_url, mode=mode, allowed_origins=allowed_origins)
        previous = self._origin_addresses.get(admitted.canonical_origin)
        if previous is not None and previous != admitted.address_digest:
            raise URLPolicyError("dns_rebinding_address_drift")
        self._origin_addresses[admitted.canonical_origin] = admitted.address_digest
        return admitted

    def admit_request(
        self,
        kind: RequestKind,
        url: str,
        *,
        mode: BrowserMode,
        allowed_origins: tuple[str, ...],
    ) -> AdmittedURLV1:
        self._attempts += 1
        self._attempts_by_kind[kind] += 1
        try:
            return self._admit(kind, url, mode=mode, allowed_origins=allowed_origins)
        except Exception:
            self._rejections_by_kind[kind] += 1
            raise

    def is_admissible(
        self,
        kind: RequestKind,
        url: str,
        *,
        mode: BrowserMode,
        allowed_origins: tuple[str, ...],
    ) -> AdmittedURLV1:
        # 纯查询：不增 attempt、不写 rebinding 记录、不计 send。
        return self._policy.admit(_normalize_websocket(kind, url), mode=mode,
                                  allowed_origins=allowed_origins)

    def record_send(self, kind: RequestKind, admitted: AdmittedURLV1) -> None:
        self._sends += 1
        self._sends_by_kind[kind] += 1
        self._transport.send(admitted.canonical_url)


def _normalize_websocket(kind: RequestKind, url: str) -> str:
    if kind is RequestKind.WEBSOCKET and url.startswith("wss://"):
        return "https://" + url[len("wss://"):]
    return url


class PlaywrightBrowserEnvironment:
    """BrowserEnvironment 的唯一真实 adapter（public-read v1）。

    worker thread 独占 Playwright/Chromium 对象；caller 侧只维护 opaque
    session 状态与串行 roundtrip 锁。worker 内任何异常都作为 error
    response 返回（线程不死），非合同异常会把该 handle poison；close 按
    page→context→browser→Playwright(with 退出) 顺序恰好各一次收尾并确认
    worker exit，join 失败如实 CLEANUP_UNKNOWN。无任何 fallback。
    """

    def __init__(
        self,
        *,
        playwright_factory: Callable[[], Any] | None = None,
        resolver: Any | None = None,
        browser_identity_digest: str = "a" * 64,
        response_timeout: float = 60.0,
        join_timeout: float = 10.0,
        profile_root: Any | None = None,
        clock: Callable[[], float] | None = None,
        quarantine: BrowserQuarantine | None = None,
    ) -> None:
        self._playwright_factory = playwright_factory
        self._browser_identity_digest = browser_identity_digest
        self._response_timeout = response_timeout
        self._join_timeout = join_timeout
        self._profile_root = profile_root
        # injected clock：expiry 判定禁止真实 sleep/系统时间直读。
        self._clock = clock or time.monotonic
        self._consumed_bindings: set[str] = set()
        self._quarantine = quarantine
        self._guard = BrowserEgressGuard(
            resolver=resolver if resolver is not None else SocketAddressResolver(),
            transport=_BrowserTransport(),
        )
        self._thread: threading.Thread | None = None
        self._requests: queue.Queue = queue.Queue(maxsize=_QUEUE_CAPACITY)
        self._responses: queue.Queue = queue.Queue(maxsize=_QUEUE_CAPACITY)
        self._sessions: dict[str, dict] = {}
        # 只记录 persistent context 的 launch mode，不含 URL/profile/credential。
        # E3 用这个只读 journal 证明 takeover 真实执行了 headed transition；
        # 它不参与 authority、state progression 或 browser 调用决策。
        self._persistent_launch_modes: list[bool] = []
        self._caller_lock = threading.Lock()
        self._stopped = False
        self._anonymous_open_unknown = False

    # ------------------------------------------------------------------ #
    # qualification 与 caller 侧状态
    # ------------------------------------------------------------------ #

    def qualify(self) -> BrowserQualificationV1:
        if self._playwright_factory is not None:
            return BrowserQualificationV1(ready=True, reason_code=None)
        try:
            import playwright.sync_api  # noqa: F401  lazy：base install 不加载
        except ImportError:
            return BrowserQualificationV1(
                ready=False, reason_code="browser_package_missing"
            )
        return BrowserQualificationV1(ready=True, reason_code=None)

    def worker_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def egress_sends(self, kind: RequestKind | None = None) -> int:
        return self._guard.sends if kind is None else self._guard.sends_for(kind)

    def egress_attempts(self, kind: RequestKind | None = None) -> int:
        return self._guard.attempts if kind is None else self._guard.attempts_for(kind)

    def egress_rejections(self, kind: RequestKind) -> int:
        return self._guard.rejections_for(kind)

    def persistent_context_launch_modes(self) -> tuple[bool, ...]:
        return tuple(self._persistent_launch_modes)

    def _require_session(self, handle: BrowserHandleV1) -> dict:
        state = self._sessions.get(getattr(handle, "session_ref", ""))
        if state is None:
            raise BrowserUnavailableError("browser_session_unknown")
        if state["unusable"]:
            raise BrowserUnavailableError("browser_session_unusable")
        return state

    def _session_for_cleanup(self, handle: BrowserHandleV1) -> dict:
        state = self._sessions.get(getattr(handle, "session_ref", ""))
        if state is None:
            raise BrowserUnavailableError("browser_session_unknown")
        # unusable 只禁止继续 observe/execute；显式 cleanup 必须仍能到达
        # worker，否则一次未知 action 会永久泄漏浏览器资源。
        return state

    def _poison(self, session_ref: str | None) -> None:
        if session_ref is None:
            return
        state = self._sessions.get(session_ref)
        if state is not None:
            state["unusable"] = True

    # ------------------------------------------------------------------ #
    # 公开 API（全部经 bounded 队列与 worker 通信）
    # ------------------------------------------------------------------ #

    def open(self, spec: BrowserSessionSpecV1) -> BrowserHandleV1:
        try:
            self._ensure_worker()
        except BrowserUnavailableError as error:
            raise BrowserOpenNotStartedError(error.reason_code) from error
        try:
            response = self._roundtrip({"op": "open", "spec": spec})
        except Exception:
            # open timeout/error 可能发生在 worker 已创建 context 之后，此时
            # caller 尚无 session_ref。停止 worker 让其 finally cleanup，但因
            # 没有 receipt，始终保留 UNKNOWN 标记供 composition fail closed。
            self._anonymous_open_unknown = True
            self._stopped = True
            if self._thread is not None:
                self._thread.join(timeout=self._join_timeout)
            raise
        handle = response["result"]
        self._sessions[handle.session_ref] = {
            "unusable": False,
            "handle": handle,
            "headed": False,
        }
        return handle

    def observe(self, handle: BrowserHandleV1) -> BrowserObservationV1:
        self._require_session(handle)
        return self._roundtrip({"op": "observe", "session_ref": handle.session_ref})[
            "result"
        ]

    def execute(
        self,
        handle: BrowserHandleV1,
        action: BrowserActionV1,
        *,
        binding: Any = None,
        upload_staging: BrowserUploadStagingV1 | None = None,
    ) -> BrowserActionReceiptV1 | KnownNotExecuted:
        self._require_session(handle)
        return self._roundtrip(
            {
                "op": "execute",
                "session_ref": handle.session_ref,
                "action": action,
                "binding": binding,
                "upload_staging": upload_staging,
            }
        )["result"]

    def begin_takeover(self, handle: BrowserHandleV1) -> None:
        self._require_session(handle)
        self._roundtrip(
            {"op": "begin_takeover", "session_ref": handle.session_ref}
        )
        self._sessions[handle.session_ref]["headed"] = True

    def takeover_session_active(self, session_ref: str) -> bool:
        state = self._sessions.get(session_ref)
        return bool(
            state is not None
            and not state["unusable"]
            and state.get("headed") is True
            and self.worker_alive()
        )

    def shutdown(self) -> None:
        """composition closeable：逆序收尾时关闭全部仍 active 的 session。

        每个 session 走既有 close 链（page→context→browser→Playwright 并
        join worker）；已 unusable 的 session 仍走 cleanup-only close。任何 session 的
        cleanup 为 CLEANUP_UNKNOWN，或收尾后 worker 仍存活时，本方法抛出
        ``BrowserCleanupUnknownError`` fail closed（session 已标记 unusable，
        无 fallback）——绝不从成功路径的 journal 单独宣称清理闭合。
        """

        failed: list[str] = []
        if self._anonymous_open_unknown:
            failed.append("<open-outcome-unknown>")
        for session_ref, state in list(self._sessions.items()):
            try:
                receipt = self.close(state["handle"])
            except Exception:  # noqa: BLE001  close 内部已 fail closed；防御
                failed.append(session_ref)
                continue
            if receipt.outcome is BrowserCleanupOutcome.CLEANUP_UNKNOWN:
                failed.append(session_ref)
        if self.worker_alive():
            failed.append("<worker-still-alive>")
        if failed:
            raise BrowserCleanupUnknownError(
                "browser shutdown failed closed for sessions: "
                + ", ".join(sorted(failed))
            )

    def close(self, handle: BrowserHandleV1) -> BrowserCleanupReceiptV1:
        state = self._session_for_cleanup(handle)
        try:
            response = self._roundtrip({"op": "close", "session_ref": handle.session_ref})
            receipt = response["result"]
        except Exception:  # noqa: BLE001  cleanup 不抛：任何不确定都 UNKNOWN
            receipt = BrowserCleanupReceiptV1(
                session_ref=handle.session_ref,
                outcome=BrowserCleanupOutcome.CLEANUP_UNKNOWN,
            )
        state["unusable"] = True
        if receipt.outcome is BrowserCleanupOutcome.CLEANED:
            self._sessions.pop(handle.session_ref, None)
        self._stopped = True
        if self._thread is not None:
            self._thread.join(timeout=self._join_timeout)
        if self.worker_alive():
            return BrowserCleanupReceiptV1(
                session_ref=handle.session_ref,
                outcome=BrowserCleanupOutcome.CLEANUP_UNKNOWN,
            )
        if receipt.outcome is BrowserCleanupOutcome.CLEANED:
            # clean close 已确认 page/context/browser/Playwright 全部退出；后续
            # open 必须启动全新的 worker/scope，而不是复用任何旧 browser state。
            self._stopped = False
        return receipt

    # ------------------------------------------------------------------ #
    # worker 通信：串行锁 + bounded put + timeout poison
    # ------------------------------------------------------------------ #

    def _ensure_worker(self) -> None:
        if self._stopped:
            raise BrowserUnavailableError("browser_environment_stopped")
        if self.worker_alive():
            return
        qualification = self.qualify()
        if not qualification.ready:
            raise BrowserUnavailableError(
                qualification.reason_code or "browser_unavailable"
            )
        self._thread = threading.Thread(
            target=self._worker_main, name="first-agent-browser", daemon=True
        )
        self._thread.start()
        try:
            message = self._responses.get(timeout=self._response_timeout)
        except queue.Empty as error:
            self._stopped = True
            raise BrowserUnavailableError("browser_worker_timeout") from error
        if message.get("op") != "ready":
            self._stopped = True
            self._thread.join(timeout=self._join_timeout)
            raise BrowserUnavailableError(
                "browser_startup_failed", str(message.get("error", "unknown"))
            )

    def _roundtrip(self, request: dict) -> dict:
        session_ref = request.get("session_ref")
        with self._caller_lock:
            try:
                self._requests.put(request, timeout=_PUT_TIMEOUT_SECONDS)
            except queue.Full as error:
                self._poison(session_ref)
                raise BrowserUnavailableError("browser_queue_saturated") from error
            try:
                response = self._responses.get(timeout=self._response_timeout)
            except queue.Empty as error:
                self._poison(session_ref)
                raise BrowserUnavailableError("browser_worker_timeout") from error
        if "error" in response:
            error = response["error"]
            if not isinstance(error, (URLPolicyError, BrowserActionRefusedError)):
                # effect 已发生后的任何失败（含 receipt 构建）都是 unknown：
                # session 必须 fail closed，禁止任何 replay。
                self._poison(session_ref)
            raise error
        return response

    # ------------------------------------------------------------------ #
    # worker thread：唯一接触 Playwright/Chromium 对象的地方
    # ------------------------------------------------------------------ #

    def _worker_main(self) -> None:
        factory = self._playwright_factory or _real_playwright_factory
        try:
            scope = factory()
        except Exception as error:  # noqa: BLE001  factory 启动失败只报告
            self._responses.put({"op": "startup_error", "error": error})
            return
        # with 覆盖整个命令循环：Playwright stop 恰好一次且永远最后。
        with scope as playwright_handle:
            self._responses.put({"op": "ready"})
            # browser 延迟 launch：mode 决定 launch 方式（public-read 用
            # chromium.launch；site-bound 用 chromium.launch_persistent_context，
            # 后者自带 browser 进程，无独立 browser 对象）。
            state: dict[str, Any] = {"browser": None}
            worker_sessions: dict[str, dict] = {}
            try:
                while True:
                    if self._stopped:
                        return
                    try:
                        request = self._requests.get(
                            timeout=_IDLE_QUEUE_TIMEOUT_SECONDS
                        )
                    except queue.Empty:
                        # sync Playwright 只有在 API call 中才泵 driver events。
                        # 空闲接管期只推进 browser event loop，让用户页面和
                        # egress callbacks 继续工作；不 observe、不录制、不触发
                        # Runtime/provider/tool action。
                        for session in worker_sessions.values():
                            with contextlib.suppress(Exception):
                                session["page"].wait_for_timeout(
                                    _IDLE_BROWSER_PUMP_MS
                                )
                            self._close_rejected_websockets(session)
                        continue
                    op = request["op"]
                    try:
                        result = self._dispatch(
                            playwright_handle, state, worker_sessions, request
                        )
                    except Exception as error:  # noqa: BLE001  线程不死，error 回传
                        self._responses.put({"op": op, "error": error})
                        if op == "open" and not worker_sessions:
                            # 首次 open 失败且无任何 session：fail closed 退出
                            # worker，释放 Playwright scope（无 fallback）。
                            return
                        continue
                    self._responses.put({"op": op, "result": result})
                    if self._stopped:
                        return
                    if op == "close" and not worker_sessions:
                        return
            finally:
                # 兜底只清理异常退出时的残留；正常路径 _worker_close 已收尾，
                # 已关闭的资源绝不重复 close（double-close 会污染顺序观察）。
                for session in worker_sessions.values():
                    for key in ("page", "context"):
                        target = session.get(key)
                        if target is not None and not _already_closed(target):
                            _best_effort_close(target)
                if state["browser"] is not None and not _browser_is_closed(
                    state["browser"]
                ):
                    _best_effort_close(state["browser"])

    def _dispatch(
        self, playwright_handle: Any, state: dict, worker_sessions: dict, request: dict,
    ):
        op = request["op"]
        if op == "open":
            return self._worker_open(
                playwright_handle, state, worker_sessions, request["spec"]
            )
        if op == "observe":
            return self._worker_observe(worker_sessions, request["session_ref"])
        if op == "execute":
            return self._worker_execute(
                worker_sessions,
                request["session_ref"],
                request["action"],
                request.get("binding"),
                request.get("upload_staging"),
            )
        if op == "begin_takeover":
            return self._worker_begin_takeover(
                playwright_handle,
                worker_sessions,
                request["session_ref"],
            )
        if op == "close":
            return self._worker_close(state, worker_sessions, request["session_ref"])
        raise ValueError(f"unknown browser worker op {op!r}")

    def _worker_open(
        self,
        playwright_handle: Any,
        state: dict,
        worker_sessions: dict,
        spec: BrowserSessionSpecV1,
    ) -> BrowserHandleV1:
        if worker_sessions:
            # 每个 environment 只允许一个 active session：mode 不静默混用。
            raise BrowserUnavailableError("browser_session_active")
        if spec.mode is BrowserMode.SITE_BOUND_INTERACTIVE:
            # site-bound：唯一允许的 persistent context 在 owner profile root
            # 下的 canonical profile 目录，经 BrowserType（chromium）启动——
            # 这是真实 Playwright API surface；exact-origin confinement 由
            # guard 与 session allowed_origins 保证。
            if spec.browser_identity_digest != self._browser_identity_digest:
                # environment 配置的 browser identity 必须与 spec 一致。
                raise BrowserUnavailableError("browser_identity_mismatch")
            user_data_dir = self._canonical_profile_dir(spec.profile_ref)
            context = playwright_handle.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                # 自动化阶段保持 headless；Runtime durable-save takeover
                # pending 后，begin_takeover 才能切换到 headed window。
                headless=True,
                accept_downloads=self._quarantine is not None,
                downloads_path=(
                    str(self._quarantine.root / "incoming")
                    if self._quarantine is not None
                    else None
                ),
                service_workers="block",
            )
            self._persistent_launch_modes.append(True)
        else:
            if state["browser"] is None:
                try:
                    state["browser"] = playwright_handle.chromium.launch(headless=True)
                except Exception as error:  # noqa: BLE001  启动失败只报告，不 fallback
                    raise BrowserUnavailableError(
                        "browser_startup_failed", str(error)
                    ) from error
            # service_workers="block"：官方推荐——route 不拦截 SW 控制的请求，
            # 阻止 service worker 绕过 egress gate。
            context = state["browser"].new_context(
                accept_downloads=False, service_workers="block"
            )
        context.set_default_timeout(DEFAULT_TIMEOUT_MS)
        context.set_default_navigation_timeout(DEFAULT_TIMEOUT_MS)
        mode = spec.mode
        allowed_origins = tuple(spec.allowed_origins)
        session_ref = f"session-{secrets.token_hex(8)}"
        # session dict 先建：route/popup handler 闭包引用同一 session。
        session = {
            "context": context,
            "page": None,
            "last_observation": None,
            "mode": mode,
            "allowed_origins": allowed_origins,
            "canonical_url": None,
            "canonical_origin": None,
            "explicit_navigation_url": None,
            # Playwright 的 route handler 只观察 redirect chain 的首跳。
            # adapter 因此截断首跳，并把已重验的 top-level target 交回
            # execute 路径作为一次新的显式导航；target 绝不自动发送。
            "pending_redirect_url": None,
            "pending_redirect_admission": None,
            "explicit_navigation_error": None,
            "rejected_websockets": [],
            # spec §4.2 authority：budget/expiry/profile revision 显式绑定。
            "profile_revision": spec.profile_revision,
            "profile_ref": spec.profile_ref,
            "expiry_monotonic": spec.expiry_monotonic,
            "budget_remaining": spec.action_budget,
        }
        context.route(
            "**/*",
            lambda route, request: self._route_handler(route, request, session),
        )
        context.route_web_socket(
            "**/*",
            lambda websocket: self._websocket_handler(websocket, session),
        )
        context.on("page", lambda page: self._popup_containment(page, session))
        page = context.new_page()
        session["page"] = page
        self._bind_page_identity(session, page)
        session["approved_download_action"] = None
        if hasattr(page, "on"):
            page.on(
                "download",
                lambda download: self._unapproved_download(download, session),
            )
        worker_sessions[session_ref] = session
        return BrowserHandleV1(
            session_ref=session_ref,
            mode=spec.mode,
            authority_digest=spec.identity_digest,
        )

    def _worker_begin_takeover(
        self,
        playwright_handle: Any,
        worker_sessions: dict,
        session_ref: str,
    ) -> None:
        session = worker_sessions[session_ref]
        if session["mode"] is not BrowserMode.SITE_BOUND_INTERACTIVE:
            raise BrowserUnavailableError("browser_takeover_requires_site_bound")
        resume_url = session.get("canonical_url") or session["page"].url
        self._close_rejected_websockets(session)
        # 旧 headless context 必须先确认关闭，才可对同一 owner profile 启动
        # headed context；失败时抛出，绝不同时持有两个 profile writer。
        session["page"].close()
        session["context"].close()
        user_data_dir = self._canonical_profile_dir(session["profile_ref"])
        context = playwright_handle.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=False,
            accept_downloads=self._quarantine is not None,
            downloads_path=(
                str(self._quarantine.root / "incoming")
                if self._quarantine is not None
                else None
            ),
            service_workers="block",
        )
        self._persistent_launch_modes.append(False)
        context.set_default_timeout(DEFAULT_TIMEOUT_MS)
        context.set_default_navigation_timeout(DEFAULT_TIMEOUT_MS)
        session.update(
            {
                "context": context,
                "page": None,
                "last_observation": None,
                "canonical_url": None,
                "canonical_origin": None,
                "explicit_navigation_url": None,
                "pending_redirect_url": None,
                "pending_redirect_admission": None,
                "explicit_navigation_error": None,
                "rejected_websockets": [],
            }
        )
        context.route(
            "**/*",
            lambda route, request: self._route_handler(route, request, session),
        )
        context.route_web_socket(
            "**/*",
            lambda websocket: self._websocket_handler(websocket, session),
        )
        context.on("page", lambda page: self._popup_containment(page, session))
        page = context.new_page()
        session["page"] = page
        self._bind_page_identity(session, page)
        session["approved_download_action"] = None
        if hasattr(page, "on"):
            page.on(
                "download",
                lambda download: self._unapproved_download(download, session),
            )
        if resume_url and resume_url != "about:blank":
            outcome = self._navigate_page(page, session, resume_url)
            if outcome is not BrowserActionOutcome.EFFECT_APPLIED:
                raise BrowserUnavailableError("browser_takeover_restore_blocked")
            session["canonical_url"] = page.url
            session["canonical_origin"] = _origin_of(page.url)
        return None

    def _canonical_profile_dir(self, profile_ref: str | None) -> str:
        # closed validate exact opaque profile id + root/profile no-follow
        # canonical 校验；不读取 profile 内容，不造第二 profile owner。
        if PROFILE_ID_PATTERN.fullmatch(profile_ref or "") is None:
            raise BrowserUnavailableError("browser_profile_ref_invalid")
        if self._profile_root is None:
            raise BrowserUnavailableError("browser_profile_root_missing")
        root = Path(self._profile_root)
        try:
            root_info = os.lstat(root)
        except OSError as error:
            raise BrowserUnavailableError("browser_profile_root_missing") from error
        if stat.S_ISLNK(root_info.st_mode) or not stat.S_ISDIR(root_info.st_mode):
            raise BrowserUnavailableError("browser_profile_root_invalid")
        target = root / profile_ref
        try:
            target_info = os.lstat(target)
        except FileNotFoundError:
            return str(target)  # 首次由 launch_persistent_context 创建
        except OSError as error:
            raise BrowserUnavailableError("browser_profile_dir_invalid") from error
        if stat.S_ISLNK(target_info.st_mode) or not stat.S_ISDIR(target_info.st_mode):
            raise BrowserUnavailableError("browser_profile_dir_invalid")
        return str(target)

    def _route_handler(self, route: Any, request: Any, session: dict) -> None:
        # first-request gate（含 popup 初始请求）。导航响应由 adapter 以
        # max_redirects=0 拉取，避免 Chromium 自动跟随未重验的 Location；
        # 其他资源仍在 continue 前 admission。
        kind = _classify_request(
            request,
            explicit_navigation_url=session.get("explicit_navigation_url"),
            primary_page=session.get("page"),
        )
        explicit_document = (
            kind is RequestKind.DOCUMENT
            and request.url == session.get("explicit_navigation_url")
        )
        try:
            pre_admitted = session.get("pending_redirect_admission")
            if (
                explicit_document
                and pre_admitted is not None
                and pre_admitted.canonical_url == request.url
            ):
                admitted = pre_admitted
                session["pending_redirect_admission"] = None
            else:
                admitted = self._guard.admit_request(
                    kind,
                    request.url,
                    mode=session["mode"],
                    allowed_origins=session["allowed_origins"],
                )
            if request.is_navigation_request():
                response = route.fetch(max_redirects=0)
                # fetch 已完成一次真实首跳；即使后续 fulfill/redirect target
                # 被拒，这个已发生的 send 也必须如实计数。
                send_kind = (
                    RequestKind.REDIRECT if pre_admitted is admitted else kind
                )
                self._guard.record_send(send_kind, admitted)
                location = _redirect_location(response)
                if location is not None:
                    target_url = urljoin(request.url, location)
                    target = self._guard.admit_request(
                        RequestKind.REDIRECT,
                        target_url,
                        mode=session["mode"],
                        allowed_origins=session["allowed_origins"],
                    )
                    if explicit_document:
                        session["pending_redirect_url"] = target.canonical_url
                        session["pending_redirect_admission"] = target
                    # 原始 3xx 绝不交还 Chromium 自动 follow；只有上面的
                    # exact top-level target 才能由 execute 显式发起下一跳。
                    route.abort()
                    return
                route.fulfill(response=response)
                return
            route.continue_()
        except Exception as error:  # noqa: BLE001  guard/transport 拒绝均 fail closed
            if explicit_document:
                session["explicit_navigation_error"] = error
            route.abort()
            return
        self._guard.record_send(kind, admitted)

    def _websocket_handler(self, websocket: Any, session: dict) -> None:
        """WebSocket 专用 pre-connect gate；HTTP route 看不到握手事件。"""
        try:
            admitted = self._guard.admit_request(
                RequestKind.WEBSOCKET,
                websocket.url,
                mode=session["mode"],
                allowed_origins=session["allowed_origins"],
            )
            websocket.connect_to_server()
        except Exception:  # noqa: BLE001  不 connect 即只存在本地 mock，无外部 send
            # WebSocketRoute.close 在 route callback 内会等待 handler 完成，
            # sync API 因而可能自锁；交给同一 worker 的下一安全点关闭。
            session["rejected_websockets"].append(websocket)
            return
        self._guard.record_send(RequestKind.WEBSOCKET, admitted)

    @staticmethod
    def _close_rejected_websockets(session: dict) -> None:
        pending = session["rejected_websockets"]
        session["rejected_websockets"] = []
        for websocket in pending:
            with contextlib.suppress(Exception):
                websocket.close()

    def _popup_containment(self, page: Any, session: dict) -> None:
        # on("page") 对每个新 Page 触发（含 new_page 的主 page）：只做
        # post-creation containment——主 page 跳过、尚未导航的 about:blank
        # 跳过（first-request gate 由 route 负责）、纯查询不计数。
        if page is session.get("page"):
            return
        url = getattr(page, "url", "") or ""
        if not url or url == "about:blank":
            return
        try:
            self._guard.is_admissible(
                RequestKind.POPUP,
                url,
                mode=session["mode"],
                allowed_origins=session["allowed_origins"],
            )
        except Exception:  # noqa: BLE001  非 allowlist popup 只清理，不计数
            _best_effort_close(page)

    def _worker_observe(
        self, worker_sessions: dict, session_ref: str,
    ) -> BrowserObservationV1:
        session = worker_sessions[session_ref]
        self._close_rejected_websockets(session)
        page = session["page"]
        refs = page.evaluate(COLLECT_ELEMENT_REFS_SCRIPT)
        nodes = tuple(
            RawAriaNodeV1(
                ref=item["ref"],
                role=item.get("role"),
                name=item.get("name"),
                depth=item.get("depth", 0),
                input_type=item.get("input_type"),
                form_action=item.get("form_action"),
                form_method=item.get("form_method"),
                # 浏览器端已判定 value_empty；value 原文永不离开页面。空串/
                # 占位串只为 projection 保留 bool 语义。
                value=(
                    None
                    if item.get("value_empty") is None
                    else ("" if item["value_empty"] else "filled")
                ),
            )
            for item in refs
        )
        # Playwright page 是真实 navigation identity；BACK/RELOAD/CLICK 也可能
        # 改变 URL，不能继续复用只在 explicit NAVIGATE 写入的旧缓存。
        canonical_url = page.url
        canonical_origin = _origin_of(canonical_url)
        session["canonical_url"] = canonical_url
        session["canonical_origin"] = canonical_origin
        fake_revision = getattr(page, "navigation_revision", None)
        if (
            isinstance(fake_revision, int)
            and not isinstance(fake_revision, bool)
            and fake_revision > session["navigation_revision"]
        ):
            # deterministic fake 可直接推进；production 由 framenavigated 事件推进。
            session["navigation_revision"] = fake_revision
        observation = project_aria_snapshot(
            RawBrowserSnapshotV1(nodes=nodes),
            ObservationIdentityV1(
                session_ref=session_ref,
                page_id=session["page_id"],
                frame_id=session["frame_id"],
                navigation_revision=session["navigation_revision"],
                browser_revision=self._browser_identity_digest,
                profile_revision=session["profile_revision"],
                canonical_url=canonical_url,
                canonical_origin=canonical_origin,
                frame_tree_digest=self._frame_tree_digest(page),
                observed_at=time.time(),
            ),
        )
        session["last_observation"] = observation
        return observation

    @staticmethod
    def _frame_tree_digest(page: Any) -> str:
        frames = getattr(page, "frames", None)
        if isinstance(frames, (list, tuple)) and frames:
            index_by_identity = {id(frame): index for index, frame in enumerate(frames)}
            projected = []
            for index, frame in enumerate(frames):
                parent = getattr(frame, "parent_frame", None)
                projected.append(
                    {
                        "index": index,
                        "parent": index_by_identity.get(id(parent)) if parent else None,
                        "url": str(getattr(frame, "url", "")),
                        "name": str(getattr(frame, "name", "")),
                    }
                )
            return canonical_json_digest(projected)
        fake_digest = getattr(page, "frame_tree_digest", None)
        if (
            isinstance(fake_digest, str)
            and len(fake_digest) == 64
            and all(item in "0123456789abcdef" for item in fake_digest)
        ):
            return fake_digest
        return canonical_json_digest(
            {"url": str(getattr(page, "url", "")), "main_frame_only": True}
        )

    @staticmethod
    def _bind_page_identity(session: dict, page: Any) -> None:
        session["page_id"] = f"page-{secrets.token_hex(8)}"
        session["frame_id"] = f"frame-{secrets.token_hex(8)}"
        session["navigation_revision"] = 1

        def note_navigation(frame: Any) -> None:
            main_frame = getattr(page, "main_frame", None)
            if main_frame is None or frame is main_frame:
                session["navigation_revision"] += 1

        if hasattr(page, "on"):
            page.on("framenavigated", note_navigation)

    def _navigate_page(
        self, page: Any, session: dict, initial_url: str
    ) -> BrowserActionOutcome:
        """显式跟随已重验的 top-level redirects，且每一跳都先过 guard。"""
        target_url = initial_url
        sends_before = self._guard.sends
        for _hop in range(MAX_REDIRECT_HOPS + 1):
            session["pending_redirect_url"] = None
            session["explicit_navigation_error"] = None
            session["explicit_navigation_url"] = target_url
            goto_error: Exception | None = None
            try:
                page.goto(target_url)
            except Exception as error:  # noqa: BLE001  route abort 的外层载体
                goto_error = error
            finally:
                session["explicit_navigation_url"] = None
            self._close_rejected_websockets(session)
            route_error = session.pop("explicit_navigation_error", None)
            next_url = session.pop("pending_redirect_url", None)
            if route_error is not None:
                session["pending_redirect_admission"] = None
                if (
                    isinstance(route_error, URLPolicyError)
                    and self._guard.sends > sends_before
                ):
                    # 首跳已发送、redirect target 在 send 前被 guard 阻断：
                    # 这是可证明的 executed-but-blocked，不是 unknown，也不能
                    # 伪装成零 effect 的 KnownNotExecuted。
                    return BrowserActionOutcome.EFFECT_BLOCKED
                raise route_error from goto_error
            if next_url is None:
                if goto_error is not None:
                    raise goto_error
                return BrowserActionOutcome.EFFECT_APPLIED
            target_url = next_url
        session["pending_redirect_admission"] = None
        raise URLPolicyError("browser_redirect_limit_exceeded")

    def _worker_execute(
        self,
        worker_sessions: dict,
        session_ref: str,
        action: BrowserActionV1,
        binding: Any = None,
        upload_staging: BrowserUploadStagingV1 | None = None,
    ) -> BrowserActionReceiptV1 | KnownNotExecuted:
        session = worker_sessions[session_ref]
        bound = session["last_observation"]
        allowed = (
            PUBLIC_READ_ACTION_KINDS
            if session["mode"] is BrowserMode.PUBLIC_READ_EPHEMERAL
            else INTERACTIVE_ACTION_KINDS
        )
        if action.kind not in allowed:
            # upload/download 的 staging/quarantine 属于 Task 7；本任务在
            # policy 层完成 consequence 分类，adapter 层拒绝执行。
            raise BrowserActionRefusedError(
                f"{session['mode'].value} forbids action kind {action.kind.value}"
            )
        if session["mode"] is BrowserMode.SITE_BOUND_INTERACTIVE and binding is None:
            # site-bound 的每个 action 都必须携带 approval binding。
            raise BrowserActionRefusedError(
                "site_bound_interactive actions require an approval binding"
            )
        if binding is not None:
            # 唯一 recompute seam：伪造 digest / replace 字段在 effect 前拒。
            try:
                BrowserActionPolicy.validate_binding(binding)
            except ValueError:
                return KnownNotExecuted(
                    code="browser_binding_changed",
                    message="binding digest does not match its fields",
                )
            # binding revalidation（observation+action 的冻结字段）：action
            # 参数/observation 绑定被篡改，或 single-use binding 已被消费，
            # 都冻结为 browser_binding_changed，零副作用。
            if (
                binding.action_digest != action.identity_digest
                or binding.observation_digest != action.observation_digest
                or binding.page_id != action.page_id
                or binding.frame_id != action.frame_id
            ):
                return KnownNotExecuted(
                    code="browser_binding_changed",
                    message="action does not match the frozen binding",
                )
            if binding.binding_digest in self._consumed_bindings:
                return KnownNotExecuted(
                    code="browser_binding_changed",
                    message="action binding already consumed",
                )
        if (
            bound is None
            or action.observation_digest != bound.observation_digest
            or action.page_id != bound.page_id
            or action.frame_id != bound.frame_id
        ):
            return KnownNotExecuted(
                code="stale_browser_target",
                message="action does not bind current observation",
            )
        # authority 门槛：budget 耗尽或 session 过期都在任何 effect 前拒。
        if session["budget_remaining"] <= 0:
            return KnownNotExecuted(
                code="browser_budget_exhausted",
                message="session action budget exhausted",
            )
        if (
            session["expiry_monotonic"] is not None
            and self._clock() > session["expiry_monotonic"]
        ):
            return KnownNotExecuted(
                code="browser_session_expired",
                message="session authority expired",
            )
        page = session["page"]
        # effect 前完整 re-observe（fresh observation，不是旧引用），比较
        # 全部 page/frame/navigation/profile/browser/origin identity——
        # 逐字段比较，不比较含 observed_at 的整体 digest。
        fresh = self._worker_observe(worker_sessions, session_ref)
        if (
            fresh.page_id != bound.page_id
            or fresh.frame_id != bound.frame_id
            or fresh.navigation_revision != bound.navigation_revision
            or fresh.profile_revision != bound.profile_revision
            or fresh.browser_revision != bound.browser_revision
            or fresh.canonical_origin != bound.canonical_origin
            or fresh.canonical_url != bound.canonical_url
            or fresh.frame_tree_digest != bound.frame_tree_digest
        ):
            return KnownNotExecuted(
                code="stale_browser_target",
                message="page identity drifted before effect",
            )
        element = next(
            (item for item in bound.element_refs if item.ref == action.target_ref),
            None,
        )
        current = next(
            (item for item in fresh.element_refs if item.ref == action.target_ref),
            None,
        )
        if action.target_ref is not None and element is None:
            return KnownNotExecuted(
                code="stale_browser_target",
                message="target ref not present in bound observation",
            )
        if element is not None and (
            current is None
            or current.role != element.role
            or current.name != element.name
            or current.input_type != element.input_type
            or current.form_action != element.form_action
            or current.form_method != element.form_method
        ):
            return KnownNotExecuted(
                code="stale_browser_target",
                message="element metadata drifted before effect",
            )
        if binding is not None and element is not None and (
            element.role != binding.target_role
            or element.name != binding.target_name
            or element.input_type != binding.target_input_type
            or element.form_action != binding.target_form_action
            or element.form_method != binding.target_form_method
        ):
            return KnownNotExecuted(
                code="stale_browser_target",
                message="observation target drifted from binding",
            )
        # 先解析并冻结本 action 需要的全部 locators（零或全执行，杜绝
        # partial fill）；任何 missing/ambiguous 都 KnownNotExecuted。
        frozen: list[tuple[Any, str]] = []
        if action.kind is BrowserActionKind.FILL_FORM:
            for key in sorted(action.params["fields"]):
                field = next(
                    (item for item in fresh.element_refs if item.name == key), None
                )
                if field is None:
                    return KnownNotExecuted(
                        code="stale_browser_target",
                        message=f"fill field {key!r} not resolvable",
                    )
                locator = page.get_by_role(field.role or "", name=key, exact=True)
                if locator.count() != 1:
                    return KnownNotExecuted(
                        code="browser_target_ambiguous",
                        message=f"fill field {key!r} does not resolve to one element",
                    )
                frozen.append((locator, action.params["fields"][key]))
        elif action.kind in (
            BrowserActionKind.CLICK,
            BrowserActionKind.SELECT,
            BrowserActionKind.UPLOAD,
            BrowserActionKind.DOWNLOAD,
        ):
            locator = page.get_by_role(
                element.role or "", name=element.name, exact=True
            )
            if locator.count() != 1:
                return KnownNotExecuted(
                    code="browser_target_ambiguous",
                    message="target does not resolve to exactly one element",
                )
            frozen.append((locator, (action.params or {}).get("value", "")))
        admitted = None
        if action.kind is BrowserActionKind.NAVIGATE:
            # 纯查询预检：拒绝在 goto 前 fail closed；实际导航请求由
            # context.route 唯一 admit+record_send，不产生双计数。
            admitted = self._guard.is_admissible(
                RequestKind.DOCUMENT,
                action.params["url"],
                mode=session["mode"],
                allowed_origins=session["allowed_origins"],
            )
        # 全部 preflight Green：在首个 effect 前消费 single-use binding——
        # 即使后续 effect 已发生而 receipt 失败，binding 也不可 replay。
        if binding is not None:
            self._consumed_bindings.add(binding.binding_digest)
        download_receipt = None
        action_outcome = BrowserActionOutcome.EFFECT_APPLIED
        if action.kind is BrowserActionKind.NAVIGATE:
            action_outcome = self._navigate_page(page, session, admitted.canonical_url)
            if action_outcome is BrowserActionOutcome.EFFECT_BLOCKED:
                # abort 后 Chromium 会异步销毁旧 execution context；在同一
                # worker 内泵一个 bounded tick，再做 receipt read-back。
                page.wait_for_timeout(_IDLE_BROWSER_PUMP_MS)
            # goto 成功后才允许从真实 page URL 确认 canonical identity；
            # goto 异常由 worker error 路径 poison（unknown），不会预写。
            session["canonical_url"] = page.url
            session["canonical_origin"] = _origin_of(page.url)
        elif action.kind is BrowserActionKind.BACK:
            page.go_back()
        elif action.kind is BrowserActionKind.RELOAD:
            page.reload()
        elif action.kind is BrowserActionKind.SCROLL:
            page.mouse.wheel(0, SCROLL_DELTA)
        elif action.kind is BrowserActionKind.FILL_FORM:
            for locator, value in frozen:
                locator.fill(value)
        elif action.kind is BrowserActionKind.SELECT:
            frozen[0][0].select_option(action.params["value"])
        elif action.kind is BrowserActionKind.UPLOAD:
            if self._quarantine is None or upload_staging is None:
                return KnownNotExecuted(
                    code="browser_upload_staging_missing",
                    message="approved upload staging is unavailable",
                )
            try:
                upload_path = self._quarantine.resolve_staging(upload_staging)
            except BrowserQuarantineError as error:
                return KnownNotExecuted(
                    code="browser_upload_staging_changed",
                    message=str(error),
                )
            frozen[0][0].set_input_files(str(upload_path))
        elif action.kind is BrowserActionKind.DOWNLOAD:
            if (
                self._quarantine is None
                or not hasattr(page, "expect_download")
            ):
                return KnownNotExecuted(
                    code="browser_download_quarantine_missing",
                    message="approved download quarantine is unavailable",
                )
            session["approved_download_action"] = action.identity_digest
            try:
                with page.expect_download() as download_info:
                    frozen[0][0].click()
                download = download_info.value
                incoming = self._quarantine.allocate_incoming(
                    session_ref=session_ref,
                    action_digest=action.identity_digest,
                )
                try:
                    download.save_as(str(incoming))
                    mime_type = (
                        mimetypes.guess_type(download.suggested_filename)[0]
                        or "application/octet-stream"
                    )
                    download_receipt = self._quarantine.store(
                        incoming,
                        session_ref=session_ref,
                        action_digest=action.identity_digest,
                        browser_identity_digest=self._browser_identity_digest,
                        source_origin=bound.canonical_origin,
                        suggested_name=download.suggested_filename,
                        mime_type=mime_type,
                    )
                finally:
                    self._quarantine.discard_incoming(incoming)
            finally:
                session["approved_download_action"] = None
        else:
            frozen[0][0].click()
        # effect 已发生：budget 立即递减（即使 receipt 构建失败也已消耗）。
        session["budget_remaining"] -= 1
        try:
            post_observation = self._worker_observe_after_effect(
                worker_sessions,
                session_ref,
                navigation=action.kind is BrowserActionKind.NAVIGATE,
            )
        except Exception as error:  # noqa: BLE001  effect 已发生：receipt 失败
            raise BrowserEffectReceiptError(
                f"effect applied but post-observation failed: {error}"
            ) from error
        return BrowserActionReceiptV1(
            action_digest=action.identity_digest,
            pre_observation_digest=action.observation_digest,
            post_observation_digest=post_observation.observation_digest,
            outcome=action_outcome,
            download=download_receipt,
        )

    def _worker_observe_after_effect(
        self,
        worker_sessions: dict,
        session_ref: str,
        *,
        navigation: bool,
    ) -> BrowserObservationV1:
        page = worker_sessions[session_ref]["page"]
        for attempt in range(3):
            try:
                return self._worker_observe(worker_sessions, session_ref)
            except Exception as error:  # noqa: BLE001 - Playwright wraps this race
                if (
                    not navigation
                    or "Execution context was destroyed" not in str(error)
                    or attempt == 2
                ):
                    raise
                page.wait_for_timeout(_IDLE_BROWSER_PUMP_MS)
        raise AssertionError("bounded navigation observation retry exhausted")

    @staticmethod
    def _unapproved_download(download: Any, session: dict) -> None:
        if session.get("approved_download_action") is not None:
            return
        with contextlib.suppress(Exception):
            download.cancel()

    def _worker_close(
        self, state: dict, worker_sessions: dict, session_ref: str,
    ) -> BrowserCleanupReceiptV1:
        session = worker_sessions.pop(session_ref)
        outcome = BrowserCleanupOutcome.CLEANED
        # 顺序收尾：page→context（persistent context 的 browser 进程随
        # context.close 终结，无独立 browser 对象）；public-read 的共享
        # browser 最后关闭。Playwright stop 由 worker 的 with __exit__
        # 完成（顺序最后、恰好一次）。任何不确定都 UNKNOWN。
        self._close_rejected_websockets(session)
        try:
            session["page"].close()
        except Exception:  # noqa: BLE001  清理不确定必须显式 UNKNOWN
            outcome = BrowserCleanupOutcome.CLEANUP_UNKNOWN
        try:
            session["context"].close()
        except Exception:  # noqa: BLE001
            outcome = BrowserCleanupOutcome.CLEANUP_UNKNOWN
        browser = state.get("browser")
        if (
            not worker_sessions
            and session["mode"] is BrowserMode.PUBLIC_READ_EPHEMERAL
            and browser is not None
            and not _browser_is_closed(browser)
        ):
            try:
                browser.close()
            except Exception:  # noqa: BLE001
                outcome = BrowserCleanupOutcome.CLEANUP_UNKNOWN
        return BrowserCleanupReceiptV1(session_ref=session_ref, outcome=outcome)
