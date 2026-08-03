"""Provider-neutral、确定性的上下文投影。"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, replace

from agent.runtime.contracts import (
    RESERVED_CONTROL_NAME,
    Action,
    BudgetReport,
    ContextCandidate,
    ContextPack,
    ContextQuery,
    ContextSourceLimits,
    ContextSourceSnapshot,
    ControlReceipt,
    ConversationFact,
    ConversationState,
    FactKind,
    GoalBootstrap,
    JSONValue,
    ModelMessage,
    SideEffectClass,
    SubmitMessage,
    ToolDefinition,
)
from agent.runtime.ports import ContextSource, RetryableContextSourceError


class ContextLimitError(Exception):
    code = "context_core_too_large"


# kind 闭集只含模型→内核方向的控制变体；control_receipt 是内核→模型的回放，
# 不进入 incoming enum，模型无法伪造已受理回执。
_CONTROL_KINDS = (
    "clarification_request",
    "goal_proposal",
    "goal_progress",
    "goal_delta_proposal",
    "completion_claim",
    "blocked_claim",
)


def _reserved_control_schema(*, goal_present: bool = False) -> dict[str, JSONValue]:
    # 真实模型必须能从 wire schema 独立构造完整控制消息；只暴露 kind/correlation_id
    # 会让 mock parser Green、真实 Provider 却稳定产出 malformed control。
    # 每次 build 构造独立副本，避免跨 ContextPack 共享可变嵌套结构。
    # 只使用 DeepSeek/OpenAI-compatible 普遍接受的基础 JSON Schema 子集。
    # non-empty/array cardinality 等安全不变量由下游 immutable contracts 严格校验。
    string = {"type": "string"}
    string_array = {"type": "array", "items": string}
    proposed_criterion = {
        "type": "object",
        "properties": {
            "criterion_id": string,
            "description": string,
        },
        "required": ["criterion_id", "description"],
        "additionalProperties": False,
    }
    goal_frame = {
        "type": "object",
        "properties": {
            "goal_id": string,
            "revision": {"type": "integer", "minimum": 1},
            "created_from_fact_ids": {
                **string_array,
                "description": "Non-empty; copy the trusted source_fact_id exactly.",
            },
            "workspace_identity_digest": string,
            "user_outcome": string,
            "beneficiary": string,
            "targets": {**string_array, "description": "Must contain at least one target."},
            "scope": {**string_array, "description": "Must contain at least one scope item."},
            "non_goals": string_array,
            "assumptions": string_array,
            "proposed_criteria": {
                "type": "array",
                "items": proposed_criterion,
                "description": "Must contain at least one proposed criterion.",
            },
            # admission 只能由 Runtime 从用户 action/approval 铸造。
            "admitted_criteria": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Runtime-owned; must be empty [].",
            },
            "authority_snapshot": string,
            "status": {"type": "string", "enum": ["goal_ready"]},
            "created_at": {
                **string,
                "description": "Non-empty ISO-8601 timestamp.",
            },
            "updated_at": {
                **string,
                "description": "Non-empty ISO-8601 timestamp.",
            },
            # Wire schema 保持 provider-portable；未产生进度时模型发送空字符串。
            # Runtime decoder 仍兼容 null，但不依赖 remote schema 支持 union type。
            "progress_summary": {"type": "string"},
            "next_step": {"type": "string"},
        },
        "required": [
            "goal_id",
            "revision",
            "created_from_fact_ids",
            "workspace_identity_digest",
            "user_outcome",
            "beneficiary",
            "targets",
            "scope",
            "non_goals",
            "assumptions",
            "proposed_criteria",
            "admitted_criteria",
            "authority_snapshot",
            "status",
            "created_at",
            "updated_at",
            "progress_summary",
            "next_step",
        ],
        "additionalProperties": False,
    }

    goal_delta = {
        "type": "object",
        "properties": {
            "goal_id": string,
            "expected_revision": {"type": "integer", "minimum": 1},
            "reason": string,
            "updates": {
                "type": "object",
                "properties": {
                    "user_outcome": string,
                    "beneficiary": string,
                    "targets": {
                        **string_array,
                        "description": "When present, must contain at least one target.",
                    },
                    "scope": {
                        **string_array,
                        "description": "When present, must contain at least one scope item.",
                    },
                    "non_goals": string_array,
                    "assumptions": string_array,
                    "proposed_criteria": {
                        "type": "array",
                        "items": proposed_criterion,
                        "description": "When present, must contain at least one criterion.",
                    },
                },
                "additionalProperties": False,
            },
            "updated_at": {"type": "string"},
        },
        "required": ["goal_id", "expected_revision", "reason", "updates", "updated_at"],
        "additionalProperties": False,
    }
    allowed_kinds = tuple(
        kind
        for kind in _CONTROL_KINDS
        if not (goal_present and kind == "goal_proposal")
    )
    lifecycle_description = (
        " A trusted_goal already exists, so goal_proposal is unavailable; continue with "
        "goal progress, completion, blockage, clarification, or correction controls."
        if goal_present
        else " goal_proposal is available only for the current trusted_goal_bootstrap."
    )
    return {
        "name": RESERVED_CONTROL_NAME,
        "description": (
            "Reserved continuity control channel; never a product tool. Required payloads: "
            "clarification_request(question,boundary_code,missing_fields,safe_assumptions); "
            "goal_proposal(goal_frame); goal_progress(goal_id,goal_revision,summary,next_step); "
            "goal_delta_proposal(delta); completion_claim(goal_id,goal_revision,"
            "criterion_evidence_refs); blocked_claim(goal_id,goal_revision,blocker,"
            "safe_attempts,resume_condition). Send no fields belonging to another kind. "
            "Propose criteria but leave admitted_criteria empty; only the runtime can admit "
            "completion authority."
            + lifecycle_description
        ),
        "input_schema": {
            # DeepSeek 与一部分 OpenAI-compatible endpoints 会在 request admission
            # 阶段拒绝 oneOf/anyOf。单一 object 列出闭合字段集；kind-specific exact
            # required/extra-field 规则仍由共享 Runtime decoder 强制，绝不在 adapter
            # 或第二条 workflow 中解释业务合法性。
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": list(allowed_kinds)},
                "correlation_id": string,
                "question": string,
                "boundary_code": string,
                "missing_fields": {
                    **string_array,
                    "description": "Must contain at least one missing field.",
                },
                "safe_assumptions": string_array,
                "goal_frame": goal_frame,
                "goal_id": string,
                "goal_revision": {"type": "integer", "minimum": 1},
                "summary": string,
                "next_step": string,
                "delta": goal_delta,
                "criterion_evidence_refs": string_array,
                "blocker": string,
                "safe_attempts": string_array,
                "resume_condition": string,
            },
            "required": ["kind", "correlation_id"],
            "additionalProperties": False,
        },
    }


def _receipt_continuity_payload(receipt: ControlReceipt) -> dict[str, JSONValue]:
    # 回执连续性只由这七个持久字段重建，预算按此闭合投影计费。
    return {
        "correlation_id": receipt.correlation_id,
        "control_kind": receipt.control_kind,
        "goal_id": receipt.goal_id,
        "goal_revision": receipt.goal_revision,
        "accepted_state_revision": receipt.accepted_state_revision,
        "payload_digest": receipt.payload_digest,
        "receipt_digest": receipt.receipt_digest,
    }


@dataclass(frozen=True, slots=True)
class ContextLimits:
    max_input_tokens: int
    output_reserve: int
    max_tool_result_chars: int = 8_000
    chars_per_token: int = 4

    def __post_init__(self) -> None:
        if self.max_input_tokens < 1:
            raise ValueError("max_input_tokens must be positive")
        if self.output_reserve < 1:
            raise ValueError("output_reserve must be positive")
        if self.output_reserve >= self.max_input_tokens:
            raise ValueError("output_reserve must leave a positive input budget")
        if self.max_tool_result_chars < 1:
            raise ValueError("max_tool_result_chars must be positive")
        if self.chars_per_token < 1:
            raise ValueError("chars_per_token must be positive")


@dataclass(frozen=True, slots=True)
class _ContextGroup:
    fact_ids: tuple[str, ...]
    messages: tuple[ModelMessage, ...]
    tool_call_ids: tuple[str, ...] = ()
    has_tool_result: bool = False
    pinned: bool = False
    data_class: str | None = None


class KernelContextManager:
    """只做预算和投影，不调用 Provider，也不修改 durable state。"""

    def __init__(
        self,
        *,
        system_policy: str,
        limits: ContextLimits,
        sources: tuple[ContextSource, ...] = (),
        workspace_scope_digest: str = "",
        authority_snapshot: str = "fixed-composition",
        source_item_cap: int = 8,
    ) -> None:
        if not system_policy.strip():
            raise ValueError("system_policy must not be empty")
        self._system_policy = system_policy
        self._limits = limits
        self._sources = tuple(sources)
        self._workspace_scope_digest = workspace_scope_digest
        self._authority_snapshot = authority_snapshot
        self._source_item_cap = source_item_cap

    def build(
        self,
        state: ConversationState,
        action: Action,
        tools: tuple[ToolDefinition, ...],
    ) -> ContextPack:
        if action.conversation_id != state.conversation_id:
            raise ValueError("action and state conversation must match")

        # 初始 no-Goal 阶段在模型可见能力层就移除 effectful callable；Runtime
        # 的 prepare 前检查仍保留为第二道 fail-closed 防线，防止模型臆造隐藏工具名。
        exposed_tools = (
            tools
            if state.goal is not None
            else tuple(
                tool for tool in tools if tool.side_effect is SideEffectClass.READ_ONLY
            )
        )

        projected_facts, clipped_ids = self._clip_tool_results(state.facts)
        groups = self._group_facts(projected_facts)
        groups = self._pin_groups(groups, state)
        goal_group = self._goal_group(state)
        if goal_group is not None:
            groups = (goal_group, *groups)
        goal_bootstrap, bootstrap_group = self._goal_bootstrap_group(state)
        if bootstrap_group is not None:
            groups = (bootstrap_group, *groups)
        source_groups, source_digests = self._collect_source_groups(state, action)
        groups = (*groups, *source_groups)

        # 控制 schema 与全部回执是 mandatory pinned fixed cost：不参与淘汰，
        # 也绝不降级为 user text；放不下只能走下方的 ContextLimitError。
        control_schema = _reserved_control_schema(goal_present=state.goal is not None)
        fixed_cost = (
            self._estimate(self._system_policy)
            + self._estimate_json(control_schema)
            + sum(
                self._estimate_json(_receipt_continuity_payload(receipt))
                for receipt in state.control_receipts
            )
            + sum(
                self._estimate_json(
                    {
                        "name": tool.name,
                        "description": tool.description,
                        "input_schema": tool.input_schema,
                    }
                )
                for tool in exposed_tools
            )
        )
        costed_groups = tuple((group, self._group_cost(group)) for group in groups)
        available_input = self._limits.max_input_tokens - self._limits.output_reserve
        pinned_cost = fixed_cost + sum(cost for group, cost in costed_groups if group.pinned)
        if pinned_cost > available_input:
            raise ContextLimitError(
                "pinned context and tool schemas exceed the provider input budget"
            )

        estimated = fixed_cost + sum(cost for _group, cost in costed_groups)
        excluded_indexes: set[int] = set()
        # 非 pinned 组按倒序排除（source 候选最低优先级，最后追加故先被淘汰）。
        for index in range(len(costed_groups) - 1, -1, -1):
            if estimated <= available_input:
                break
            group = costed_groups[index][0]
            if not group.pinned:
                excluded_indexes.add(index)
                estimated -= costed_groups[index][1]

        selected = [
            group
            for index, (group, _cost) in enumerate(costed_groups)
            if index not in excluded_indexes
        ]
        excluded: list[_ContextGroup] = []
        excluded.extend(
            group for index, (group, _cost) in enumerate(costed_groups) if index in excluded_indexes
        )

        messages = tuple(message for group in selected for message in group.messages)
        data_classes = {
            "system_policy",
            *(group.data_class for group in selected if group.data_class is not None),
        }
        if exposed_tools:
            data_classes.add("tool_schemas")
        if state.control_receipts:
            data_classes.add("control_receipts")
        return ContextPack(
            system=self._system_policy,
            messages=messages,
            tools=exposed_tools,
            control_schema=control_schema,
            control_receipts=state.control_receipts,
            data_classes=tuple(sorted(data_classes)),
            goal_bootstrap=goal_bootstrap,
            budget=BudgetReport(
                input_limit=self._limits.max_input_tokens,
                estimated_input_tokens=estimated,
                output_reserve=self._limits.output_reserve,
                included_ids=tuple(fact_id for group in selected for fact_id in group.fact_ids),
                excluded_ids=tuple(fact_id for group in excluded for fact_id in group.fact_ids),
                clipped_ids=clipped_ids,
                source_digests=source_digests,
            ),
        )

    def _goal_bootstrap_group(
        self,
        state: ConversationState,
    ) -> tuple[GoalBootstrap | None, _ContextGroup | None]:
        if state.goal is not None or not self._workspace_scope_digest:
            return None, None
        source = next(
            (fact for fact in reversed(state.facts) if fact.kind is FactKind.USER_MESSAGE),
            None,
        )
        if source is None:
            return None, None
        bootstrap = GoalBootstrap(
            source_fact_id=source.fact_id,
            workspace_identity_digest=self._workspace_scope_digest,
            authority_snapshot=self._authority_snapshot,
        )
        block: dict[str, JSONValue] = {
            "type": "trusted_goal_bootstrap",
            "trusted": True,
            "source_fact_id": bootstrap.source_fact_id,
            "workspace_identity_digest": bootstrap.workspace_identity_digest,
            "authority_snapshot": bootstrap.authority_snapshot,
        }
        return bootstrap, _ContextGroup(
            fact_ids=(f"goal-bootstrap:{source.fact_id}",),
            messages=(ModelMessage(role="user", content=(block,)),),
            pinned=True,
            data_class="goal_bootstrap",
        )

    def _collect_source_groups(
        self,
        state: ConversationState,
        action: Action,
    ) -> tuple[tuple[_ContextGroup, ...], tuple[str, ...]]:
        if not self._sources:
            return (), ()
        user_text = ""
        if isinstance(action, SubmitMessage):
            user_text = action.message
        elif state.facts:
            last_user = next(
                (fact for fact in reversed(state.facts) if fact.kind is FactKind.USER_MESSAGE),
                None,
            )
            if last_user is not None:
                text = last_user.content.get("text")
                if isinstance(text, str):
                    user_text = text
        query = ContextQuery(
            conversation_id=state.conversation_id,
            run_id=state.active_run.run_id if state.active_run else "",
            user_text=user_text,
            workspace_scope_digest=self._workspace_scope_digest,
            source_limits=ContextSourceLimits(
                max_tokens=self._limits.max_input_tokens,
                max_items=self._source_item_cap,
            ),
        )
        groups: list[_ContextGroup] = []
        digests: list[str] = []
        for source in self._sources:
            try:
                snapshot = source.snapshot(query)
            except RetryableContextSourceError:
                raise
            except Exception as error:  # noqa: BLE001 - source 损坏在 provider 前必须 fatal
                raise ContextLimitError("context source is inconsistent") from error
            if not isinstance(snapshot, ContextSourceSnapshot):
                raise ContextLimitError("context source returned an invalid snapshot")
            digests.append(f"{snapshot.source_name}:{snapshot.revision}:{snapshot.snapshot_digest}")
            for candidate in snapshot.candidates[: self._source_item_cap]:
                groups.append(self._candidate_group(source.name, candidate))
        return tuple(groups), tuple(digests)

    @staticmethod
    def _goal_group(state: ConversationState) -> _ContextGroup | None:
        goal = state.goal
        if goal is None:
            return None
        admitted_ids = tuple(criterion.criterion_id for criterion in goal.admitted_criteria)
        evidenced_ids = {
            record.criterion_id
            for record in state.evidence_records
            if record.goal_id == goal.goal_id
            and record.goal_revision == goal.revision
            and record.passed
        }
        block: dict[str, JSONValue] = {
            "type": "trusted_goal",
            "trusted": True,
            "goal_id": goal.goal_id,
            "goal_revision": goal.revision,
            "workspace_identity_digest": goal.workspace_identity_digest,
            "user_outcome": goal.user_outcome,
            "beneficiary": goal.beneficiary,
            "targets": list(goal.targets),
            "scope": list(goal.scope),
            "non_goals": list(goal.non_goals),
            "assumptions": list(goal.assumptions),
            "authority_snapshot": goal.authority_snapshot,
            "status": goal.status.value,
            "interaction_state": state.interaction_state.value,
            "progress_summary": goal.progress_summary,
            "next_step": goal.next_step,
            "proposed_criteria": [
                {
                    "criterion_id": criterion.criterion_id,
                    "description": criterion.description,
                }
                for criterion in goal.proposed_criteria
            ],
            "admitted_criteria": [
                {
                    "criterion_id": criterion.criterion_id,
                    "description": criterion.description,
                    "oracle_kind": criterion.oracle_kind.value,
                    "predicate": criterion.predicate,
                    "mandatory": criterion.mandatory,
                }
                for criterion in goal.admitted_criteria
            ],
            "evidence_gaps": [
                criterion_id
                for criterion_id in admitted_ids
                if criterion_id not in evidenced_ids
            ],
        }
        return _ContextGroup(
            fact_ids=(f"goal:{goal.goal_id}:{goal.revision}",),
            messages=(ModelMessage(role="user", content=(block,)),),
            pinned=True,
            data_class="goal",
        )

    def _candidate_group(self, source_name: str, candidate: ContextCandidate) -> _ContextGroup:
        block = {
            "type": "context",
            "untrusted": True,
            "source": source_name,
            "candidate_id": candidate.candidate_id,
            "digest": candidate.content_digest,
            "text": self._frame_candidate(candidate),
        }
        return _ContextGroup(
            fact_ids=(candidate.candidate_id,),
            messages=(ModelMessage(role="user", content=(block,)),),
            tool_call_ids=(),
            has_tool_result=False,
            pinned=False,
            data_class={
                "memory": "workspace_memory",
                "owner_preferences": "owner_preferences",
            }.get(source_name, "recalled_context"),
        )

    def _frame_candidate(self, candidate: ContextCandidate) -> str:
        provenance = " ".join(f"{key}={value}" for key, value in candidate.provenance.items())
        framed = (
            f"[untrusted memory from {candidate.source_name} "
            f"id={candidate.candidate_id} digest={candidate.content_digest[:8]}"
        )
        if provenance:
            framed += f" {provenance}"
        framed += f"] {candidate.content}"
        char_cap = self._limits.max_tool_result_chars
        if len(framed) > char_cap:
            framed = framed[:char_cap]
        return framed

    def _estimate(self, text: str) -> int:
        return max(1, math.ceil(len(text) / self._limits.chars_per_token))

    def _estimate_json(self, value: object) -> int:
        return self._estimate(
            json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        )

    def _group_cost(self, group: _ContextGroup) -> int:
        return sum(
            self._estimate_json({"role": message.role, "content": message.content})
            for message in group.messages
        )

    def _clip_tool_results(
        self,
        facts: tuple[ConversationFact, ...],
    ) -> tuple[tuple[ConversationFact, ...], tuple[str, ...]]:
        clipped: list[str] = []
        projected: list[ConversationFact] = []
        for fact in facts:
            text = fact.content.get("text")
            if (
                fact.kind is FactKind.TOOL_RESULT
                and isinstance(text, str)
                and len(text) > self._limits.max_tool_result_chars
            ):
                clipped.append(fact.fact_id)
                content = dict(fact.content)
                content.update(
                    {
                        "text": text[: self._limits.max_tool_result_chars],
                        "original_chars": len(text),
                        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                        "reason": "tool_result_char_limit",
                    }
                )
                projected.append(replace(fact, content=content))
            else:
                projected.append(fact)
        return tuple(projected), tuple(clipped)

    def _group_facts(self, facts: tuple[ConversationFact, ...]) -> tuple[_ContextGroup, ...]:
        groups: list[_ContextGroup] = []
        index = 0
        while index < len(facts):
            fact = facts[index]
            if fact.kind is not FactKind.TOOL_CALLS:
                groups.append(self._single_fact_group(fact))
                index += 1
                continue

            calls = fact.content.get("calls")
            if not isinstance(calls, list):
                raise ValueError("tool call fact must contain a calls list")
            call_blocks: list[dict[str, JSONValue]] = []
            preamble = fact.content.get("preamble")
            if isinstance(preamble, str) and preamble:
                call_blocks.append({"type": "text", "text": preamble})
            tool_call_ids: list[str] = []
            for call in calls:
                if not isinstance(call, dict):
                    raise ValueError("tool call must be an object")
                tool_call_id = call.get("tool_call_id")
                name = call.get("name")
                arguments = call.get("arguments", {})
                if not isinstance(tool_call_id, str) or not isinstance(name, str):
                    raise ValueError("tool call identity must be a string")
                if not isinstance(arguments, dict):
                    raise ValueError("tool call arguments must be an object")
                tool_call_ids.append(tool_call_id)
                call_blocks.append(
                    {
                        "type": "tool_call",
                        "tool_call_id": tool_call_id,
                        "name": name,
                        "arguments": arguments,
                    }
                )

            fact_ids = [fact.fact_id]
            result_blocks: list[dict[str, JSONValue]] = []
            next_index = index + 1
            while next_index < len(facts) and facts[next_index].kind is FactKind.TOOL_RESULT:
                result = facts[next_index]
                result_call_id = result.content.get("tool_call_id")
                if result_call_id not in tool_call_ids:
                    break
                block: dict[str, JSONValue] = {"type": "tool_result", **result.content}
                result_blocks.append(block)
                fact_ids.append(result.fact_id)
                next_index += 1

            messages = [ModelMessage(role="assistant", content=tuple(call_blocks))]
            if result_blocks:
                messages.append(ModelMessage(role="user", content=tuple(result_blocks)))
            groups.append(
                _ContextGroup(
                    fact_ids=tuple(fact_ids),
                    messages=tuple(messages),
                    tool_call_ids=tuple(tool_call_ids),
                    has_tool_result=bool(result_blocks),
                    data_class="tool_results" if result_blocks else "conversation_history",
                )
            )
            index = next_index
        return tuple(groups)

    def _single_fact_group(self, fact: ConversationFact) -> _ContextGroup:
        if fact.kind is FactKind.USER_MESSAGE:
            role = "user"
            block_type = "text"
        elif fact.kind is FactKind.ASSISTANT_MESSAGE:
            role = "assistant"
            block_type = "text"
        elif fact.kind is FactKind.TOOL_RESULT:
            role = "user"
            block_type = "tool_result"
        else:
            role = "user"
            block_type = "policy_result"
        block: dict[str, JSONValue] = {"type": block_type, **fact.content}
        tool_call_id = fact.content.get("tool_call_id")
        return _ContextGroup(
            fact_ids=(fact.fact_id,),
            messages=(ModelMessage(role=role, content=(block,)),),
            tool_call_ids=(tool_call_id,) if isinstance(tool_call_id, str) else (),
            has_tool_result=fact.kind is FactKind.TOOL_RESULT,
            data_class=(
                "user_messages"
                if fact.kind is FactKind.USER_MESSAGE
                else "tool_results"
                if fact.kind is FactKind.TOOL_RESULT
                else "conversation_history"
            ),
        )

    def _pin_groups(
        self,
        groups: tuple[_ContextGroup, ...],
        state: ConversationState,
    ) -> tuple[_ContextGroup, ...]:
        pinned_fact_ids: set[str] = set()
        user_fact_ids = [fact.fact_id for fact in state.facts if fact.kind is FactKind.USER_MESSAGE]
        if user_fact_ids:
            pinned_fact_ids.add(user_fact_ids[-1])

        tool_groups = [group for group in groups if group.has_tool_result]
        if tool_groups:
            pinned_fact_ids.update(tool_groups[-1].fact_ids)

        pending_call_id: str | None = None
        if state.active_run is not None:
            if state.active_run.pending_request is not None:
                pending_call_id = state.active_run.pending_request.tool_call_id
            elif state.active_run.executing_intent is not None:
                pending_call_id = state.active_run.executing_intent.tool_call_id

        pinned: list[_ContextGroup] = []
        for group in groups:
            is_pinned = bool(pinned_fact_ids.intersection(group.fact_ids))
            if pending_call_id is not None and pending_call_id in group.tool_call_ids:
                is_pinned = True
            pinned.append(replace(group, pinned=is_pinned))
        return tuple(pinned)
