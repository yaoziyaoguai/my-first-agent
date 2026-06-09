"""Test-only helpers for Sub-agent v0 RED guardrails.

These helpers are not production API. They let RED tests target the future v0
RuntimeAction route while making the current pre-U3 missing-contract failure
explicit and easy to remove when U3 adds the v0 action and handler.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from agent.runtime_integration.phase1_hook import build_phase1_dispatcher
from agent.runtime_integration.schema import RuntimeActionRequest, RuntimeActionType

V0_MISSING_REASON = "SubAgentV0 contract not implemented yet"
DEFAULT_V0_MAX_CONTEXT_CHARS = 100_000
DEFAULT_V0_MAX_FILES = 20


class MissingSubAgentV0Contract(RuntimeError):  # noqa: N818
    """测试专用异常：只表示 v0 RuntimeAction contract 尚未落地。"""


def _stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _coerce_str_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in value)


def _coerce_nonnegative_int(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, parsed)


def _safe_context_file_id(file_id: str) -> str:
    if "/" not in file_id and "\\" not in file_id:
        return file_id
    return f"context_file:{_stable_hash(file_id)[:12]}"


def read_v0_context_file(
    file_id: str,
    parent_context_blobs: Mapping[str, str],
) -> str:
    """测试专用 v0 context read seam：只从 parent-provided snapshot 取内容。"""

    return str(parent_context_blobs.get(file_id, ""))


def build_v0_context(payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Build the test-only parent-owned v0 context contract.

    中文学习边界：这个 helper 不读真实文件系统，也不代表 production
    implementation。RED tests patch `read_v0_context_file` 这个 seam，证明未来
    v0 context builder 必须只读取 parent-selected files。
    """

    payload_dict = dict(payload or {})
    raw_blobs = payload_dict.get("parent_context_blobs", {})
    parent_context_blobs = (
        {str(key): str(value) for key, value in raw_blobs.items()}
        if isinstance(raw_blobs, Mapping)
        else {}
    )
    parent_selected_files = _coerce_str_tuple(
        payload_dict.get("parent_selected_files", tuple(parent_context_blobs))
    )
    max_context_chars = _coerce_nonnegative_int(
        payload_dict.get("max_context_chars"),
        default=DEFAULT_V0_MAX_CONTEXT_CHARS,
    )
    max_files = _coerce_nonnegative_int(
        payload_dict.get("max_files"),
        default=DEFAULT_V0_MAX_FILES,
    )

    selected_file_ids = parent_selected_files[:max_files]
    remaining_chars = max_context_chars
    chunks: list[dict[str, Any]] = []
    for file_id in selected_file_ids:
        raw_text = read_v0_context_file(file_id, parent_context_blobs)
        bounded_text = raw_text[:remaining_chars] if remaining_chars > 0 else ""
        remaining_chars -= len(bounded_text)
        chunks.append({
            "file_id": _safe_context_file_id(file_id),
            "content": bounded_text,
            "content_hash": _stable_hash(bounded_text),
            "length": len(bounded_text),
        })

    context_fingerprint = "\n".join(
        f"{chunk['file_id']}:{chunk['content_hash']}:{chunk['length']}"
        for chunk in chunks
    )
    metadata = {
        "context_hash": _stable_hash(context_fingerprint),
        "context_length": sum(int(chunk["length"]) for chunk in chunks),
        "context_file_count": len(chunks),
        "selected_file_ids": tuple(str(chunk["file_id"]) for chunk in chunks),
        "max_context_chars": max_context_chars,
        "max_files": max_files,
        "context_read_seam_calls": len(chunks),
        "uncontrolled_path_read_text_calls": 0,
        "parent_policy_selects_all_files": True,
    }
    return {
        "chunks": tuple(chunks),
        "metadata": metadata,
    }


def v0_action_type() -> RuntimeActionType:
    try:
        return RuntimeActionType.SUBAGENT_DELEGATE_V0
    except AttributeError as exc:
        raise MissingSubAgentV0Contract(
            "RuntimeActionType.SUBAGENT_DELEGATE_V0 is missing"
        ) from exc


def build_v0_request(
    *,
    provider_mode: str = "fake_local",
    task: str = "summarize safely",
    payload: Mapping[str, Any] | None = None,
) -> RuntimeActionRequest:
    payload_dict = dict(payload or {})
    payload_dict["prepared_v0_context"] = build_v0_context(payload_dict)
    return RuntimeActionRequest(
        action_type=v0_action_type(),
        source="subagent-v0-red-guardrail",
        parent_trace_id="parent-trace",
        payload={
            "profile_id": "default-v0",
            "task": task,
            "provider_mode": provider_mode,
            "parent_opt_in": provider_mode == "real_opt_in",
            **payload_dict,
        },
    )


def build_v0_dispatcher_and_handler() -> tuple[Any, Any]:
    action_type = v0_action_type()
    dispatcher = build_phase1_dispatcher()
    handler = dispatcher.get_handler(action_type)
    if handler is None:
        raise MissingSubAgentV0Contract(
            "SUBAGENT_DELEGATE_V0 handler is not registered"
        )
    if type(handler).__name__ != "SubAgentV0Handler":
        raise AssertionError(f"unexpected v0 handler: {type(handler).__name__}")
    return dispatcher, handler


def route_v0(payload: Mapping[str, Any] | None = None, *, provider_mode: str = "fake_local"):
    dispatcher, _handler = build_v0_dispatcher_and_handler()
    return dispatcher.route(build_v0_request(provider_mode=provider_mode, payload=payload))


V0_XFAIL = {
    "strict": True,
    "raises": MissingSubAgentV0Contract,
    "reason": V0_MISSING_REASON,
}
