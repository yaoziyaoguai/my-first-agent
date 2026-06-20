"""S4-G02: replay-faithful evidence chain projection (redacted-faithful)。

把 task-state 既有字段（tool_execution_log / delegation_log / current_plan /
current_step_index / lifecycle）投影成一条**有序、可复放**的 ReplayChain，使 governed
task 的决策/工具/委派链路可忠实重建——超出 S3「tools.executed:N」标签级，消化 TD-001。

设计边界（`docs/current/S4_FIDELITY_CONTRACT.md §2/§3`）：
- 不新增数据源：只读投影 `state.task` 既有字段，不写 state、不改 checkpoint、不重写 spine。
- safe-summary 粒度：input/output preview 截断到 PREVIEW_MAX。
- secret redaction（G03）：preview 投影点强制经 ``evidence_redaction.redact_text``
  脱敏（**先 redact 再 truncate**），使更高保真 chain 绝不暴露 raw secret（AC-3）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Any

from agent.evidence_redaction import redact_text

# safe-summary 截断长度，与 evidence_recorder / user_input content_preview 一致。
PREVIEW_MAX = 200

# chain 内同类事件的排序权重：同一 step 内 decision 早于 tool 早于 delegation。
_KIND_ORDER: dict[str, int] = {"decision": 0, "tool": 1, "delegation": 2}

# 标记 tool 是否被 policy 拒绝（用于 policy_outcome 投影）。
_REJECTED_STATUSES = frozenset({"blocked_by_policy", "rejected_by_check"})
_SKIPPED_STATUSES = frozenset({"skipped", "idempotent_cache"})

# running 类 lifecycle：current_step_index 落在的 step 视为 in_progress。
_RUNNING_LIFECYCLES = frozenset({"running", "awaiting_step_confirmation"})


@dataclass(frozen=True, slots=True)
class ReplayEvent:
    """replay chain 单元：governed 链路中一个可复放事件（safe-summary 粒度）。"""

    seq: int
    kind: str  # "decision" | "tool" | "delegation"
    step_index: int
    ref_id: str  # tool_use_id / delegation_id / step_id
    name: str  # tool 名 / subagent 名 / step title
    status: str  # executed / failed / blocked_by_policy / delegated / advanced / ...
    input_preview: str
    output_preview: str
    policy_outcome: str  # allow / reject / skip / accept / plan_step


@dataclass(frozen=True, slots=True)
class ReplayChain:
    """一条 governed task 的有序可复放链路投影（redacted-faithful，非逐字）。"""

    task_scope_id: str
    lifecycle: str
    events: tuple[ReplayEvent, ...]

    @property
    def tool_events(self) -> tuple[ReplayEvent, ...]:
        return tuple(e for e in self.events if e.kind == "tool")

    @property
    def delegation_events(self) -> tuple[ReplayEvent, ...]:
        return tuple(e for e in self.events if e.kind == "delegation")

    @property
    def decision_events(self) -> tuple[ReplayEvent, ...]:
        return tuple(e for e in self.events if e.kind == "decision")


def build_replay_chain(state: Any) -> ReplayChain:
    """从 task-state 投影一条 replay chain（只读，不 mutate state）。

    参数:
        state: AgentState（或测试用 SimpleNamespace）；只读 `state.task` 下的
            tool_execution_log / delegation_log / current_plan / current_step_index /
            status / user_goal。

    返回:
        ReplayChain：按 (step_index, kind, ref_id) 排序、seq 从 0 单调递增的事件序列。
    """
    task = getattr(state, "task", None)
    tool_log: dict[str, Any] = dict(getattr(task, "tool_execution_log", {}) or {})
    delegation_log: list[Any] = list(getattr(task, "delegation_log", []) or [])
    plan: Any = getattr(task, "current_plan", None)
    current_step_index = int(getattr(task, "current_step_index", 0) or 0)
    status = str(getattr(task, "status", "idle") or "idle")

    raw: list[ReplayEvent] = []
    raw.extend(_decision_events(plan, current_step_index, status))
    raw.extend(_tool_events(tool_log))
    raw.extend(_delegation_events(delegation_log, current_step_index))

    raw.sort(key=lambda e: (e.step_index, _KIND_ORDER.get(e.kind, 9), e.ref_id))
    # frozen dataclass 用 dataclasses.replace 重新赋 seq（NamedTuple 的 _replace 在此不可用）。
    events = tuple(replace(e, seq=i) for i, e in enumerate(raw))

    return ReplayChain(
        task_scope_id=_task_scope_id(state),
        lifecycle=status,
        events=events,
    )


# ──────────────────────────────────────────────────────────────────────────────
# 投影 helpers
# ──────────────────────────────────────────────────────────────────────────────


def _decision_events(plan: Any, current_step_index: int, status: str) -> list[ReplayEvent]:
    """把 plan steps 投影为 decision 锚：已推进 / 进行中 / 待执行。

    decision 链让 replay 能重建「agent 按什么步骤顺序推进、推进到哪」，无需 transition
    历史（task-state 不持久化 transition 历史，见 `agent/transitions.py`）。
    """
    events: list[ReplayEvent] = []
    running = status in _RUNNING_LIFECYCLES
    for idx, step in enumerate(_plan_steps(plan)):
        if idx < current_step_index:
            step_status = "advanced"
        elif idx == current_step_index and running:
            step_status = "in_progress"
        else:
            step_status = "planned"
        ref_id = str(step.get("step_id") or f"step-{idx}")
        name = str(step.get("title") or step.get("description") or f"step-{idx}")
        events.append(
            ReplayEvent(
                seq=0,
                kind="decision",
                step_index=idx,
                ref_id=ref_id,
                name=name,
                status=step_status,
                input_preview="",
                output_preview=_truncate(redact_text(str(step.get("description") or ""))),
                policy_outcome="plan_step",
            )
        )
    return events


def _tool_events(tool_log: dict[str, Any]) -> list[ReplayEvent]:
    events: list[ReplayEvent] = []
    for tool_use_id, entry in tool_log.items():
        if not isinstance(entry, dict):
            continue
        tool_status = str(entry.get("status", "executed") or "executed")
        events.append(
            ReplayEvent(
                seq=0,
                kind="tool",
                step_index=int(entry.get("step_index", 0) or 0),
                ref_id=str(tool_use_id),
                name=str(entry.get("tool", "unknown")),
                status=tool_status,
                input_preview=_truncate(redact_text(_stringify(entry.get("input")))),
                output_preview=_truncate(redact_text(_stringify(entry.get("result")))),
                policy_outcome=_tool_policy_outcome(tool_status),
            )
        )
    return events


def _delegation_events(delegation_log: list[Any], current_step_index: int) -> list[ReplayEvent]:
    events: list[ReplayEvent] = []
    for entry in delegation_log:
        if not isinstance(entry, dict):
            continue
        adjudication = str(entry.get("adjudication_action", "") or "")
        events.append(
            ReplayEvent(
                seq=0,
                kind="delegation",
                step_index=int(entry.get("step_index", current_step_index) or current_step_index),
                ref_id=str(entry.get("delegation_id", "") or ""),
                name=str(entry.get("subagent_name", "subagent")),
                status=str(entry.get("status", "delegated") or "delegated"),
                input_preview="",
                output_preview=_truncate(redact_text(_stringify(entry.get("stop_reason", "")))),
                policy_outcome=adjudication or "delegate",
            )
        )
    return events


def _plan_steps(plan: Any) -> list[dict[str, Any]]:
    if isinstance(plan, dict):
        steps = plan.get("steps")
        if isinstance(steps, list):
            return [s for s in steps if isinstance(s, dict)]
    return []


def _tool_policy_outcome(status: str) -> str:
    if status in _REJECTED_STATUSES:
        return "reject"
    if status in _SKIPPED_STATUSES:
        return "skip"
    return "allow"


def _truncate(value: str) -> str:
    """safe-summary 截断：超长 preview 截到 PREVIEW_MAX（含省略号）。"""
    text = value if isinstance(value, str) else ""
    if len(text) <= PREVIEW_MAX:
        return text
    return text[: PREVIEW_MAX - 3] + "..."


def _stringify(value: Any) -> str:
    """把 input/result（dict/str/其他）投影为可读字符串，供截断。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return str(value)


def _task_scope_id(state: Any) -> str:
    """轻量 task scope 标识（不调重 builder，避免循环依赖与重复开销）。"""
    task = getattr(state, "task", None)
    goal = getattr(task, "user_goal", None)
    if goal:
        return str(goal)
    return "s4-replay-scope"
