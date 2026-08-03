"""MCP capability 的不可变合同类型。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class McpOutcomeClassification(StrEnum):
    NOT_EXECUTED = "not_executed"
    EXECUTED = "executed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class McpBridgeOutcome:
    """transport/session owner 设置的不可变结果。

    只有 transport/session owner 可以设置 commit-state 字段；executor 只能据此把
    ``NOT_EXECUTED`` 映射为 ``executed=false``、``EXECUTED`` 映射为 known result、
    ``UNKNOWN`` 抛给 Runtime recovery。
    """

    classification: McpOutcomeClassification
    call_may_have_been_sent: bool = False
    terminal_response_received: bool = False
    terminal_request_id_matched: bool = False
    process_exit_confirmed: bool = False
    result_text: str = ""
    error_code: str = ""
    error_message: str = ""
