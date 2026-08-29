"""018 browser external-effect port（spec §3.1）。

``BrowserEnvironment`` 是 adapter 合同：只消费已治理的 typed request 并返回
typed observation/receipt；不认识 Provider、Goal、ContextPack、checkpoint 或
approval，不调用模型、不声明 completion。唯一 ``KnownNotExecuted`` 复用
``agent.runtime.contracts``，本包不重复定义。
"""

from __future__ import annotations

from typing import Protocol

from agent.browser.contracts import (
    BrowserActionReceiptV1,
    BrowserActionV1,
    BrowserCleanupReceiptV1,
    BrowserHandleV1,
    BrowserObservationV1,
    BrowserSessionSpecV1,
)
from agent.browser.staging import BrowserUploadStagingV1
from agent.runtime.contracts import KnownNotExecuted

__all__ = [
    "BrowserEnvironment",
    "BrowserOpenNotStartedError",
    "BrowserUnavailableError",
    "KnownNotExecuted",
]


class BrowserUnavailableError(Exception):
    """browser 资源不可用/已终结；reason_code 是 closed 诊断码。"""

    def __init__(self, reason_code: str, message: str = "") -> None:
        super().__init__(message or reason_code)
        self.reason_code = reason_code


class BrowserOpenNotStartedError(BrowserUnavailableError):
    """adapter 在任何 browser open request 入队前已确定不可执行。"""


class BrowserEnvironment(Protocol):
    """唯一 browser external-effect port；execute 只在既有 EXECUTING checkpoint 后运行。"""

    def open(self, spec: BrowserSessionSpecV1) -> BrowserHandleV1: ...

    def observe(self, handle: BrowserHandleV1) -> BrowserObservationV1: ...

    def execute(
        self,
        handle: BrowserHandleV1,
        action: BrowserActionV1,
        *,
        binding: object | None = None,
        upload_staging: BrowserUploadStagingV1 | None = None,
    ) -> BrowserActionReceiptV1 | KnownNotExecuted: ...

    def begin_takeover(self, handle: BrowserHandleV1) -> None: ...

    def takeover_session_active(self, session_ref: str) -> bool: ...

    def close(self, handle: BrowserHandleV1) -> BrowserCleanupReceiptV1: ...
