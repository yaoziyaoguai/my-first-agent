"""U3C-R1A:provider 原生 reserved control 调用的第一组连续性合同。

边界意图:模型侧通过唯一保留工具名上报控制信号(goal_progress 等),
适配器必须把它规范化为 ModelResponse.control,而不是普通 ModelToolCall;
保留名永远不进入 KernelToolRuntime 注册表,provider 模块也不得反向依赖
runtime 的执行面(state/checkpoint/tools/ToolRuntime),只允许 contracts/ports。
"""

from __future__ import annotations

import ast
import copy
import json
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from agent.provider.anthropic_http import AnthropicCompatibleProvider
from agent.provider.config import AgentProviderConfig
from agent.provider.openai_http import OpenAICompatibleProvider
from agent.provider.protocol import ProviderProtocolError
from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    AdmittedCriterion,
    BlockedClaim,
    BudgetReport,
    ClarificationRequest,
    CompletionClaim,
    ContextPack,
    ControlReceipt,
    ConversationFact,
    ConversationState,
    EvidenceOracleKind,
    FactKind,
    GoalDelta,
    GoalDeltaProposal,
    GoalFrame,
    GoalProgress,
    GoalProposal,
    GoalStatus,
    ModelMessage,
    ModelResponse,
    ModelTextBlock,
    ModelToolCall,
    ProposedCriterion,
    SubmitMessage,
    ToolDefinition,
    canonical_json_digest,
)
from agent.runtime.tools import KernelToolRuntime

RESERVED_CONTROL_NAME = "first_agent_control_v1"

# 线上合同:保留调用的 arguments 用 kind 判别控制变体,其余字段平铺。
_GOAL_PROGRESS_ARGUMENTS: dict[str, object] = {
    "kind": "goal_progress",
    "correlation_id": "ctl-001",
    "goal_id": "goal-1",
    "goal_revision": 2,
    "summary": "finished reading the fixture",
    "next_step": "summarize the fixture contents",
}

_EXPECTED_CONTROL = GoalProgress(
    correlation_id="ctl-001",
    goal_id="goal-1",
    goal_revision=2,
    summary="finished reading the fixture",
    next_step="summarize the fixture contents",
)


def _context() -> ContextPack:
    return ContextPack(
        system="Use only the supplied tools.",
        messages=(
            ModelMessage(
                role="user",
                content=({"type": "text", "text": "report progress"},),
            ),
        ),
        tools=(
            ToolDefinition(
                name="read_file",
                description="Read one bounded fixture file",
                input_schema={
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            ),
        ),
        budget=BudgetReport(
            input_limit=2_000,
            estimated_input_tokens=120,
            output_reserve=200,
        ),
    )


def _config(provider_type: str) -> AgentProviderConfig:
    return AgentProviderConfig(
        provider_type=provider_type,
        model="fixture-model",
        base_url="https://provider.invalid",
        credential="fixture-secret",
        timeout=2.0,
    )


def _anthropic_tool_call_payload(name: str, arguments: dict[str, object]) -> dict[str, object]:
    return {
        "content": [
            {"type": "tool_use", "id": "call-ctl", "name": name, "input": arguments},
        ],
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 11, "output_tokens": 5},
    }


def _openai_tool_call_payload(name: str, arguments: dict[str, object]) -> dict[str, object]:
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call-ctl",
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(arguments),
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 11, "completion_tokens": 5},
    }


PROVIDER_CASES = [
    pytest.param(
        AnthropicCompatibleProvider,
        "anthropic_compatible",
        _anthropic_tool_call_payload,
        id="anthropic",
    ),
    pytest.param(
        OpenAICompatibleProvider,
        "openai_compatible",
        _openai_tool_call_payload,
        id="openai",
    ),
]


@pytest.mark.parametrize(("provider_cls", "provider_type", "payload_builder"), PROVIDER_CASES)
def test_reserved_native_call_normalizes_to_goal_progress_control(
    provider_cls, provider_type, payload_builder
) -> None:
    payload = payload_builder(RESERVED_CONTROL_NAME, dict(_GOAL_PROGRESS_ARGUMENTS))
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json=payload))
    with httpx.Client(transport=transport) as client:
        provider = provider_cls(config=_config(provider_type), http_client=client)
        response = provider.generate(_context())

    assert isinstance(response, ModelResponse)
    assert response.control == _EXPECTED_CONTROL
    # 保留名是控制通道,不允许退化成可执行的普通工具调用。
    assert not any(
        isinstance(block, ModelToolCall) and block.name == RESERVED_CONTROL_NAME
        for block in response.blocks
    )


@pytest.mark.parametrize(("provider_cls", "provider_type", "payload_builder"), PROVIDER_CASES)
def test_ordinary_product_tool_call_stays_an_ordinary_tool_call(
    provider_cls, provider_type, payload_builder
) -> None:
    payload = payload_builder("read_file", {"path": "next.txt"})
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json=payload))
    with httpx.Client(transport=transport) as client:
        provider = provider_cls(config=_config(provider_type), http_client=client)
        response = provider.generate(_context())

    assert response.control is None
    assert ModelToolCall("call-ctl", "read_file", {"path": "next.txt"}) in response.blocks


_FORBIDDEN_RUNTIME_MODULES = (
    "agent.runtime.state",
    "agent.runtime.checkpoint",
    "agent.runtime.tools",
)
_FORBIDDEN_IMPORT_NAMES = ("ToolRuntime",)


def _is_forbidden_module(module: str) -> bool:
    # 相对导入无法还原完整包名,用后缀匹配保持边界检查不漏。
    if module in _FORBIDDEN_RUNTIME_MODULES:
        return True
    suffixes = tuple(name.removeprefix("agent.") for name in _FORBIDDEN_RUNTIME_MODULES)
    return module.endswith(tuple("." + suffix for suffix in suffixes)) or module in suffixes


def test_provider_modules_do_not_import_runtime_execution_surface() -> None:
    provider_dir = Path(__file__).resolve().parents[2] / "agent" / "provider"
    offenders: list[str] = []
    for source_path in sorted(provider_dir.glob("*.py")):
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                offenders.extend(
                    f"{source_path.name}: import {alias.name}"
                    for alias in node.names
                    if _is_forbidden_module(alias.name)
                )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if _is_forbidden_module(module):
                    offenders.append(f"{source_path.name}: from {module} import ...")
                offenders.extend(
                    f"{source_path.name}: from {module} import {alias.name}"
                    for alias in node.names
                    if alias.name in _FORBIDDEN_IMPORT_NAMES
                )
    assert offenders == []


def test_kernel_tool_runtime_never_registers_the_reserved_control_name() -> None:
    runtime = KernelToolRuntime(())
    registered = {definition.name for definition in runtime.definitions()}
    assert RESERVED_CONTROL_NAME not in registered


# U3C-R1B1:控制通道违例必须 fail closed。保留调用一旦形状非法,
# 或与普通工具调用混在同一条响应里,适配器只能抛 ProviderProtocolError,
# 不允许把保留调用退化成普通 ModelToolCall 继续向 runtime 放行。
_FAIL_CLOSED_CASES = [
    pytest.param(
        dict(_GOAL_PROGRESS_ARGUMENTS, kind="unknown_control_kind"),
        False,
        id="unknown-kind",
    ),
    pytest.param(
        {key: value for key, value in _GOAL_PROGRESS_ARGUMENTS.items() if key != "next_step"},
        False,
        id="goal-progress-missing-next-step",
    ),
    pytest.param(
        dict(_GOAL_PROGRESS_ARGUMENTS),
        True,
        id="control-mixed-with-ordinary-tool-call",
    ),
]


def _append_ordinary_read_file_call(provider_type: str, payload: dict[str, object]) -> None:
    # 混合场景只调整响应 fixture 的形状:同一条响应里再挂一个普通 read_file 调用。
    if provider_type == "anthropic_compatible":
        payload["content"].append(
            {
                "type": "tool_use",
                "id": "call-tool",
                "name": "read_file",
                "input": {"path": "next.txt"},
            }
        )
    else:
        payload["choices"][0]["message"]["tool_calls"].append(
            {
                "id": "call-tool",
                "type": "function",
                "function": {
                    "name": "read_file",
                    "arguments": json.dumps({"path": "next.txt"}),
                },
            }
        )


@pytest.mark.parametrize(("provider_cls", "provider_type", "payload_builder"), PROVIDER_CASES)
@pytest.mark.parametrize(("arguments", "mixed_with_read_file"), _FAIL_CLOSED_CASES)
def test_reserved_control_violations_fail_closed(
    provider_cls, provider_type, payload_builder, arguments, mixed_with_read_file
) -> None:
    payload = payload_builder(RESERVED_CONTROL_NAME, arguments)
    if mixed_with_read_file:
        _append_ordinary_read_file_call(provider_type, payload)
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json=payload))
    with httpx.Client(transport=transport) as client:
        provider = provider_cls(config=_config(provider_type), http_client=client)
        with pytest.raises(ProviderProtocolError):
            provider.generate(_context())


# U3C-R1B2A:控制通道的下行 seam。ContextPack 必须以独立字段携带
# reserved control schema 与已受理回执,而不是把控制面伪装进产品 tools。
def _control_receipt() -> ControlReceipt:
    payload = {
        key: _GOAL_PROGRESS_ARGUMENTS[key]
        for key in ("goal_id", "goal_revision", "summary", "next_step")
    }
    return ControlReceipt.create(
        correlation_id=_GOAL_PROGRESS_ARGUMENTS["correlation_id"],
        control_kind=_GOAL_PROGRESS_ARGUMENTS["kind"],
        goal_id=_GOAL_PROGRESS_ARGUMENTS["goal_id"],
        goal_revision=_GOAL_PROGRESS_ARGUMENTS["goal_revision"],
        accepted_state_revision=7,
        payload_digest=canonical_json_digest(payload),
    )


def _control_schema() -> dict[str, object]:
    # provider-neutral 顶层形状 {name, description, input_schema}:刻意不是
    # ToolDefinition,控制面 schema 由各 adapter 自行翻译到自家 wire 形状。
    return {
        "name": RESERVED_CONTROL_NAME,
        "description": "Reserved continuity control channel; never a product tool.",
        "input_schema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string"},
                "correlation_id": {"type": "string"},
            },
            "required": ["kind", "correlation_id"],
        },
    }


def test_context_pack_has_independent_control_schema_and_atomic_receipts() -> None:
    base = _context()
    schema = _control_schema()
    receipt = _control_receipt()

    context = replace(base, control_schema=schema, control_receipts=(receipt,))

    # 值相等而非 identity:未来 immutable ContextPack 可安全 copy/freeze mapping。
    assert context.control_schema == schema
    assert context.control_receipts == (receipt,)
    # 控制面与产品工具面各自独立:tools 不因控制字段而变化,保留名不混入其中。
    assert context.tools == base.tools
    assert tuple(tool.name for tool in context.tools) == ("read_file",)
    assert RESERVED_CONTROL_NAME not in {tool.name for tool in context.tools}


def test_production_control_schema_is_portable_closed_and_model_readable() -> None:
    state = ConversationState(
        conversation_id="schema-conversation",
        facts=(
            ConversationFact(
                "action:1:user",
                FactKind.USER_MESSAGE,
                {"text": "create a report"},
            ),
        ),
    )
    context = KernelContextManager(
        system_policy="policy",
        limits=ContextLimits(max_input_tokens=20_000, output_reserve=500),
        workspace_scope_digest="workspace-schema",
        authority_snapshot="authority-schema",
    ).build(
        state,
        SubmitMessage(
            conversation_id=state.conversation_id,
            action_seq=state.next_action_seq,
            expected_revision=state.revision,
            run_id="schema-run",
            message="create a report",
        ),
        (),
    )

    assert context.control_schema is not None
    assert context.goal_bootstrap is not None
    assert context.goal_bootstrap.source_fact_id == "action:1:user"
    assert context.goal_bootstrap.workspace_identity_digest == "workspace-schema"
    assert context.goal_bootstrap.authority_snapshot == "authority-schema"
    assert "goal_bootstrap" in context.data_classes
    schema = context.control_schema["input_schema"]
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["kind", "correlation_id"]
    assert set(schema["properties"]["kind"]["enum"]) == {
        "clarification_request",
        "goal_proposal",
        "goal_progress",
        "goal_delta_proposal",
        "completion_claim",
        "blocked_claim",
    }
    assert set(schema["properties"]) == {
        "kind",
        "correlation_id",
        "question",
        "boundary_code",
        "missing_fields",
        "safe_assumptions",
        "goal_frame",
        "goal_id",
        "goal_revision",
        "summary",
        "next_step",
        "delta",
        "criterion_evidence_refs",
        "blocker",
        "safe_attempts",
        "resume_condition",
    }
    unsupported_keywords = {
        "oneOf",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "minProperties",
        "maxProperties",
    }

    def assert_portable_subset(value: object) -> None:
        if isinstance(value, dict):
            assert unsupported_keywords.isdisjoint(value)
            assert not isinstance(value.get("type"), list)
            for child in value.values():
                assert_portable_subset(child)
        elif isinstance(value, list):
            for child in value:
                assert_portable_subset(child)

    assert_portable_subset(schema)
    goal_schema = schema["properties"]["goal_frame"]
    assert set(goal_schema["required"]) == set(goal_schema["properties"])
    assert "must be empty" in goal_schema["properties"]["admitted_criteria"]["description"]
    assert goal_schema["properties"]["status"]["enum"] == ["goal_ready"]
    assert goal_schema["additionalProperties"] is False
    delta_updates = schema["properties"]["delta"]["properties"]["updates"]
    assert "admitted_criteria" not in delta_updates["properties"]
    assert "authority_snapshot" not in delta_updates["properties"]


def test_installed_goal_control_schema_no_longer_advertises_goal_proposal() -> None:
    state = ConversationState(
        conversation_id="schema-goal-conversation",
        facts=(
            ConversationFact(
                "action:1:user",
                FactKind.USER_MESSAGE,
                {"text": "create a report"},
            ),
        ),
        goal=_EXPECTED_GOAL_FRAME,
    )
    context = KernelContextManager(
        system_policy="policy",
        limits=ContextLimits(max_input_tokens=20_000, output_reserve=500),
        workspace_scope_digest="workspace-schema",
        authority_snapshot="authority-schema",
    ).build(
        state,
        SubmitMessage(
            conversation_id=state.conversation_id,
            action_seq=state.next_action_seq,
            expected_revision=state.revision,
            run_id="schema-run",
            message="continue the report",
        ),
        (),
    )

    assert context.control_schema is not None
    kinds = context.control_schema["input_schema"]["properties"]["kind"]["enum"]
    assert "goal_proposal" not in kinds
    assert set(kinds) == {
        "clarification_request",
        "goal_progress",
        "goal_delta_proposal",
        "completion_claim",
        "blocked_claim",
    }
    assert "goal_proposal is unavailable" in context.control_schema["description"]


# U3C-R1B2B:控制回执的 Anthropic 上行 wire 合同。已受理回执必须回放为
# 相邻的原生 tool_use/tool_result 原子对,控制 schema 只在 wire 层并入 tools,
# 不允许把回执摊平成普通文本块或单独 system/user text。
def _content_blocks(message: dict[str, object]) -> list[dict[str, object]]:
    content = message.get("content")
    if not isinstance(content, list):
        return []
    return [block for block in content if isinstance(block, dict)]


def test_anthropic_control_receipt_round_trips_as_native_atomic_pair() -> None:
    requests: list[dict[str, object]] = []
    responses = (
        _anthropic_tool_call_payload(RESERVED_CONTROL_NAME, dict(_GOAL_PROGRESS_ARGUMENTS)),
        {
            "content": [{"type": "text", "text": "continuing after receipt"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 13, "output_tokens": 7},
        },
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=responses[len(requests) - 1])

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = AnthropicCompatibleProvider(
            config=_config("anthropic_compatible"), http_client=client
        )
        first_response = provider.generate(_context())

        receipt = _control_receipt()
        second_context = replace(
            _context(),
            control_schema=_control_schema(),
            control_receipts=(receipt,),
        )
        second_response = provider.generate(second_context)

    assert len(requests) == 2
    # 控制面不污染产品工具面:ContextPack.tools 仍只有产品工具,
    # wire 层 tools 恰好多出保留控制名。
    assert tuple(tool.name for tool in second_context.tools) == ("read_file",)
    second_request = requests[1]
    assert {tool["name"] for tool in second_request["tools"]} == {
        "read_file",
        RESERVED_CONTROL_NAME,
    }

    messages = second_request["messages"]
    reserved_indexes = [
        index
        for index, message in enumerate(messages)
        if message.get("role") == "assistant"
        and any(
            block.get("type") == "tool_use" and block.get("name") == RESERVED_CONTROL_NAME
            for block in _content_blocks(message)
        )
    ]
    assert len(reserved_indexes) == 1
    assistant_index = reserved_indexes[0]

    reserved_uses = [
        block
        for block in _content_blocks(messages[assistant_index])
        if block.get("type") == "tool_use" and block.get("name") == RESERVED_CONTROL_NAME
    ]
    assert len(reserved_uses) == 1
    tool_use = reserved_uses[0]
    assert tool_use["id"] == receipt.correlation_id
    # closed projection:仅由 ControlReceipt 的七个持久字段可重建,
    # 不携带 summary/next_step 等易变叙述。
    assert tool_use["input"] == {
        "kind": "control_receipt",
        "correlation_id": receipt.correlation_id,
        "control_kind": receipt.control_kind,
        "goal_id": receipt.goal_id,
        "goal_revision": receipt.goal_revision,
        "accepted_state_revision": receipt.accepted_state_revision,
        "payload_digest": receipt.payload_digest,
        "receipt_digest": receipt.receipt_digest,
    }

    # 原子对:回执的 tool_result 必须紧邻其 tool_use,由下一条 user message 携带。
    assert assistant_index + 1 < len(messages)
    follower = messages[assistant_index + 1]
    assert follower.get("role") == "user"
    tool_results = [
        block for block in _content_blocks(follower) if block.get("type") == "tool_result"
    ]
    assert len(tool_results) == 1
    tool_result = tool_results[0]
    assert tool_result["tool_use_id"] == tool_use["id"]
    result_payload = json.loads(tool_result["content"])
    assert result_payload["accepted"] is True
    assert result_payload["correlation_id"] == receipt.correlation_id
    assert result_payload["receipt_digest"] == receipt.receipt_digest

    # parser 断言后置:先暴露 seam/wire Red,不被第一轮归一化 Red 掩盖。
    assert first_response.control == _EXPECTED_CONTROL
    assert second_response.control is None
    assert ModelTextBlock("continuing after receipt") in second_response.blocks


# U3C-R1B2C:控制回执的 OpenAI 上行 wire 合同,与 Anthropic 版本语义对称。
# 已受理回执必须回放为相邻的原生 assistant tool_calls / tool message 原子对,
# 控制 schema 只在 wire 层并入 tools,不允许摊平进普通 user/system 文本。
def test_openai_control_receipt_round_trips_as_native_atomic_pair() -> None:
    requests: list[dict[str, object]] = []
    responses = (
        _openai_tool_call_payload(RESERVED_CONTROL_NAME, dict(_GOAL_PROGRESS_ARGUMENTS)),
        {
            "choices": [
                {
                    "message": {"role": "assistant", "content": "continuing after receipt"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 13, "completion_tokens": 7},
        },
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=responses[len(requests) - 1])

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleProvider(config=_config("openai_compatible"), http_client=client)
        first_response = provider.generate(_context())

        receipt = _control_receipt()
        second_context = replace(
            _context(),
            control_schema=_control_schema(),
            control_receipts=(receipt,),
        )
        second_response = provider.generate(second_context)

    assert len(requests) == 2
    # 控制面不污染产品工具面:ContextPack.tools 仍只有产品工具,
    # wire 层 tools 恰好多出保留控制名。
    assert tuple(tool.name for tool in second_context.tools) == ("read_file",)
    second_request = requests[1]
    assert {tool["function"]["name"] for tool in second_request["tools"]} == {
        "read_file",
        RESERVED_CONTROL_NAME,
    }

    messages = second_request["messages"]
    reserved_indexes = [
        index
        for index, message in enumerate(messages)
        if message.get("role") == "assistant"
        and any(
            call.get("function", {}).get("name") == RESERVED_CONTROL_NAME
            for call in message.get("tool_calls") or []
            if isinstance(call, dict)
        )
    ]
    assert len(reserved_indexes) == 1
    assistant_index = reserved_indexes[0]

    reserved_calls = [
        call
        for call in messages[assistant_index].get("tool_calls") or []
        if isinstance(call, dict) and call.get("function", {}).get("name") == RESERVED_CONTROL_NAME
    ]
    assert len(reserved_calls) == 1
    tool_call = reserved_calls[0]
    assert tool_call["id"] == receipt.correlation_id
    arguments = json.loads(tool_call["function"]["arguments"])
    # closed projection:仅由 ControlReceipt 的七个持久字段可重建,
    # 不携带 summary/next_step 等易变叙述。
    assert arguments == {
        "kind": "control_receipt",
        "correlation_id": receipt.correlation_id,
        "control_kind": receipt.control_kind,
        "goal_id": receipt.goal_id,
        "goal_revision": receipt.goal_revision,
        "accepted_state_revision": receipt.accepted_state_revision,
        "payload_digest": receipt.payload_digest,
        "receipt_digest": receipt.receipt_digest,
    }

    # 原子对:回执结果必须紧邻其 assistant 调用,由下一条 tool message 携带。
    assert assistant_index + 1 < len(messages)
    follower = messages[assistant_index + 1]
    assert follower.get("role") == "tool"
    assert follower.get("tool_call_id") == tool_call["id"]
    result_payload = json.loads(follower["content"])
    assert result_payload["accepted"] is True
    assert result_payload["correlation_id"] == receipt.correlation_id
    assert result_payload["receipt_digest"] == receipt.receipt_digest

    # 回执只允许存在于该原生 assistant-call/tool-result 对,
    # 不得摊平进普通 user/system 文本。
    for message in messages:
        if message.get("role") not in {"user", "system"}:
            continue
        content_text = json.dumps(message.get("content"))
        assert receipt.correlation_id not in content_text
        assert receipt.receipt_digest not in content_text

    # parser 断言后置:先暴露 seam/wire Red,不被第一轮归一化 Red 掩盖。
    assert second_response.control is None
    assert ModelTextBlock("continuing after receipt") in second_response.blocks
    assert first_response.control == _EXPECTED_CONTROL


# U3C-G2T1:六个合法 control 变体的归一化合同。wire 形状规则:kind 与
# correlation_id 平铺;goal_proposal/goal_delta_proposal 分别以 goal_frame/delta
# 携带 canonical 嵌套对象(字段拼写与 enum 字符串值同 contracts/checkpoint 现行
# canonical 形状);其余变体字段平铺且与 immutable contract 字段名一致。
_CLARIFICATION_ARGUMENTS: dict[str, object] = {
    "kind": "clarification_request",
    "correlation_id": "ctl-clarify-1",
    "question": "Which fixture file is the summary target?",
    "boundary_code": "target",
    "missing_fields": ["target_path"],
    "safe_assumptions": ["workspace stays read-only until confirmed"],
}

_EXPECTED_CLARIFICATION = ClarificationRequest(
    correlation_id="ctl-clarify-1",
    question="Which fixture file is the summary target?",
    boundary_code="target",
    missing_fields=("target_path",),
    safe_assumptions=("workspace stays read-only until confirmed",),
)

_GOAL_FRAME_WIRE: dict[str, object] = {
    "goal_id": "goal-2",
    "revision": 1,
    "created_from_fact_ids": ["fact-user-1"],
    "workspace_identity_digest": "ws-digest-1",
    "user_outcome": "one fixture summary file exists",
    "beneficiary": "workspace owner",
    "targets": ["notes/summary.md"],
    "scope": ["notes/"],
    "non_goals": ["no repo-wide rewrite"],
    "assumptions": ["fixture file stays readable"],
    "proposed_criteria": [{"criterion_id": "crit-1", "description": "summary file exists"}],
    "admitted_criteria": [
        {
            "criterion_id": "crit-2",
            "description": "summary digest matches approved content",
            "source_fact_id": "fact-user-1",
            "oracle_kind": "filesystem_digest",
            "predicate": {"path": "notes/summary.md"},
            "required_evidence_class": "filesystem",
            "admission_digest": "adm-1",
            "mandatory": True,
        }
    ],
    "authority_snapshot": "auth-digest-1",
    "status": "goal_ready",
    "created_at": "2026-08-02T10:00:00Z",
    "updated_at": "2026-08-02T10:00:00Z",
    "progress_summary": None,
    "next_step": None,
}

_EXPECTED_GOAL_FRAME = GoalFrame(
    goal_id="goal-2",
    revision=1,
    created_from_fact_ids=("fact-user-1",),
    workspace_identity_digest="ws-digest-1",
    user_outcome="one fixture summary file exists",
    beneficiary="workspace owner",
    targets=("notes/summary.md",),
    scope=("notes/",),
    non_goals=("no repo-wide rewrite",),
    assumptions=("fixture file stays readable",),
    proposed_criteria=(ProposedCriterion("crit-1", "summary file exists"),),
    admitted_criteria=(
        AdmittedCriterion(
            criterion_id="crit-2",
            description="summary digest matches approved content",
            source_fact_id="fact-user-1",
            oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
            predicate={"path": "notes/summary.md"},
            required_evidence_class="filesystem",
            admission_digest="adm-1",
            mandatory=True,
        ),
    ),
    authority_snapshot="auth-digest-1",
    status=GoalStatus.GOAL_READY,
    created_at="2026-08-02T10:00:00Z",
    updated_at="2026-08-02T10:00:00Z",
    progress_summary=None,
    next_step=None,
)

_GOAL_PROPOSAL_ARGUMENTS: dict[str, object] = {
    "kind": "goal_proposal",
    "correlation_id": "ctl-proposal-1",
    "goal_frame": _GOAL_FRAME_WIRE,
}

_EXPECTED_GOAL_PROPOSAL = GoalProposal(
    correlation_id="ctl-proposal-1",
    goal_frame=_EXPECTED_GOAL_FRAME,
)


@pytest.mark.parametrize(("provider_cls", "provider_type", "_payload_builder"), PROVIDER_CASES)
def test_production_http_adapters_project_trusted_goal_as_closed_text_context(
    provider_cls, provider_type, _payload_builder
) -> None:
    captured: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        if provider_type == "anthropic_compatible":
            return httpx.Response(
                200,
                json={
                    "content": [{"type": "text", "text": "continued"}],
                    "stop_reason": "end_turn",
                    "usage": {"input_tokens": 11, "output_tokens": 5},
                },
            )
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "continued"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 11, "completion_tokens": 5},
            },
        )

    state = ConversationState(
        conversation_id="trusted-goal-context",
        facts=(
            ConversationFact(
                "fact-user-1",
                FactKind.USER_MESSAGE,
                {"text": "create the summary"},
            ),
        ),
        goal=_EXPECTED_GOAL_FRAME,
    )
    context = KernelContextManager(
        system_policy="policy",
        limits=ContextLimits(max_input_tokens=20_000, output_reserve=500),
        workspace_scope_digest="ws-digest-1",
        authority_snapshot="auth-digest-1",
    ).build(
        state,
        SubmitMessage(
            conversation_id=state.conversation_id,
            action_seq=state.next_action_seq,
            expected_revision=state.revision,
            run_id="trusted-goal-run",
            message="continue",
        ),
        (),
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        response = provider_cls(config=_config(provider_type), http_client=client).generate(context)

    assert response.blocks == (ModelTextBlock("continued"),)
    assert len(captured) == 1
    wire = json.dumps(captured[0], sort_keys=True)
    assert "FIRST_AGENT_TRUSTED_CONTROL_CONTEXT" in wire
    assert "goal-2" in wire

_GOAL_DELTA_WIRE: dict[str, object] = {
    "goal_id": "goal-2",
    "expected_revision": 1,
    "reason": "user narrowed the target directory",
    "updates": {"scope": ["notes/2026/"]},
    "updated_at": None,
}

_EXPECTED_GOAL_DELTA = GoalDelta(
    goal_id="goal-2",
    expected_revision=1,
    reason="user narrowed the target directory",
    updates={"scope": ["notes/2026/"]},
    updated_at=None,
)

_GOAL_DELTA_PROPOSAL_ARGUMENTS: dict[str, object] = {
    "kind": "goal_delta_proposal",
    "correlation_id": "ctl-delta-1",
    "delta": _GOAL_DELTA_WIRE,
}

_EXPECTED_GOAL_DELTA_PROPOSAL = GoalDeltaProposal(
    correlation_id="ctl-delta-1",
    delta=_EXPECTED_GOAL_DELTA,
)

_COMPLETION_ARGUMENTS: dict[str, object] = {
    "kind": "completion_claim",
    "correlation_id": "ctl-complete-1",
    "goal_id": "goal-1",
    "goal_revision": 2,
    "criterion_evidence_refs": ["evid-1", "evid-2"],
}

_EXPECTED_COMPLETION = CompletionClaim(
    correlation_id="ctl-complete-1",
    goal_id="goal-1",
    goal_revision=2,
    criterion_evidence_refs=("evid-1", "evid-2"),
)

_BLOCKED_ARGUMENTS: dict[str, object] = {
    "kind": "blocked_claim",
    "correlation_id": "ctl-blocked-1",
    "goal_id": "goal-1",
    "goal_revision": 2,
    "blocker": "target directory is missing",
    "safe_attempts": ["re-listed the workspace root"],
    "resume_condition": "user restores notes/ or corrects the target",
}

_EXPECTED_BLOCKED = BlockedClaim(
    correlation_id="ctl-blocked-1",
    goal_id="goal-1",
    goal_revision=2,
    blocker="target directory is missing",
    safe_attempts=("re-listed the workspace root",),
    resume_condition="user restores notes/ or corrects the target",
)

_VALID_CONTROL_CASES = [
    pytest.param(_CLARIFICATION_ARGUMENTS, _EXPECTED_CLARIFICATION, id="clarification-request"),
    pytest.param(_GOAL_PROPOSAL_ARGUMENTS, _EXPECTED_GOAL_PROPOSAL, id="goal-proposal"),
    pytest.param(_GOAL_PROGRESS_ARGUMENTS, _EXPECTED_CONTROL, id="goal-progress"),
    pytest.param(
        _GOAL_DELTA_PROPOSAL_ARGUMENTS,
        _EXPECTED_GOAL_DELTA_PROPOSAL,
        id="goal-delta-proposal",
    ),
    pytest.param(_COMPLETION_ARGUMENTS, _EXPECTED_COMPLETION, id="completion-claim"),
    pytest.param(_BLOCKED_ARGUMENTS, _EXPECTED_BLOCKED, id="blocked-claim"),
]


def _inject_leading_text(provider_type: str, payload: dict[str, object], text: str) -> None:
    # 文本与合法 control 并存是允许的组合:适配器不得为了控制通道丢弃正文。
    if provider_type == "anthropic_compatible":
        payload["content"].insert(0, {"type": "text", "text": text})
    else:
        payload["choices"][0]["message"]["content"] = text


@pytest.mark.parametrize(("provider_cls", "provider_type", "payload_builder"), PROVIDER_CASES)
@pytest.mark.parametrize(("arguments", "expected_control"), _VALID_CONTROL_CASES)
def test_all_six_valid_control_variants_normalize_to_typed_control(
    provider_cls, provider_type, payload_builder, arguments, expected_control
) -> None:
    payload = payload_builder(RESERVED_CONTROL_NAME, copy.deepcopy(arguments))
    _inject_leading_text(provider_type, payload, "control narration")
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json=payload))
    with httpx.Client(transport=transport) as client:
        provider = provider_cls(config=_config(provider_type), http_client=client)
        response = provider.generate(_context())

    assert response.control == expected_control
    # 正文原样保留;保留调用被吸收进 control,绝不退化成普通 ModelToolCall。
    assert response.blocks == (ModelTextBlock("control narration"),)
    assert response.stop_reason == "tool_use"
    assert (response.input_tokens, response.output_tokens) == (11, 5)


# U3C-G2T2:malformed/冲突 fail-closed 矩阵。每类违例取一个克隆变异用例,
# 全部只允许 ProviderProtocolError;ValueError/TypeError/KeyError 泄漏或
# 静默降级成普通 ModelToolCall 都算失败。receipt 只是上行 context 输入,
# 模型侧发出 kind=control_receipt 永远非法。
def _mutated_goal_proposal(mutate) -> dict[str, object]:
    arguments = copy.deepcopy(_GOAL_PROPOSAL_ARGUMENTS)
    mutate(arguments["goal_frame"])
    return arguments


def _mutated_goal_delta_proposal(mutate) -> dict[str, object]:
    arguments = copy.deepcopy(_GOAL_DELTA_PROPOSAL_ARGUMENTS)
    mutate(arguments["delta"])
    return arguments


# 模型回声既有回执的完整七字段投影:形状与上行 wire 一致,仍必须拒绝。
_RECEIPT_ECHO_ARGUMENTS: dict[str, object] = {
    "kind": "control_receipt",
    "correlation_id": "ctl-001",
    "control_kind": "goal_progress",
    "goal_id": "goal-1",
    "goal_revision": 2,
    "accepted_state_revision": 7,
    "payload_digest": "d" * 64,
    "receipt_digest": "e" * 64,
}

_MALFORMED_CONTROL_ARGUMENT_CASES = [
    pytest.param(dict(_GOAL_PROGRESS_ARGUMENTS, note="extra"), id="unknown-top-level-field"),
    pytest.param(dict(_GOAL_PROGRESS_ARGUMENTS, summary=7), id="summary-not-string"),
    pytest.param(
        dict(_BLOCKED_ARGUMENTS, safe_attempts="re-listed the workspace root"),
        id="safe-attempts-not-array",
    ),
    pytest.param(dict(_GOAL_PROGRESS_ARGUMENTS, goal_revision=True), id="goal-revision-bool"),
    pytest.param(_RECEIPT_ECHO_ARGUMENTS, id="model-emitted-control-receipt"),
    pytest.param(
        _mutated_goal_proposal(lambda frame: frame.update(revision=True)),
        id="goal-frame-revision-bool",
    ),
    pytest.param(
        _mutated_goal_proposal(lambda frame: frame.pop("authority_snapshot")),
        id="goal-frame-missing-authority-snapshot",
    ),
    pytest.param(
        _mutated_goal_proposal(lambda frame: frame.update(status="answering")),
        id="goal-frame-invalid-status-enum",
    ),
    pytest.param(
        _mutated_goal_proposal(
            lambda frame: frame["admitted_criteria"][0].update(oracle_kind="model_self_report")
        ),
        id="admitted-criterion-invalid-oracle-enum",
    ),
    pytest.param(
        _mutated_goal_proposal(lambda frame: frame["proposed_criteria"][0].pop("description")),
        id="proposed-criterion-missing-description",
    ),
    pytest.param(
        _mutated_goal_proposal(lambda frame: frame["admitted_criteria"][0].update(weight=1)),
        id="admitted-criterion-unknown-key",
    ),
    pytest.param(
        _mutated_goal_proposal(lambda frame: frame["admitted_criteria"][0].update(mandatory=1)),
        id="admitted-criterion-mandatory-not-bool",
    ),
    pytest.param(
        _mutated_goal_delta_proposal(lambda delta: delta.pop("updated_at")),
        id="goal-delta-missing-updated-at",
    ),
    pytest.param(
        _mutated_goal_delta_proposal(lambda delta: delta.update(note="why")),
        id="goal-delta-unknown-key",
    ),
    pytest.param(
        _mutated_goal_delta_proposal(lambda delta: delta.update(expected_revision="2")),
        id="goal-delta-expected-revision-not-int",
    ),
    pytest.param(
        _mutated_goal_delta_proposal(lambda delta: delta.update(updates=["scope"])),
        id="goal-delta-updates-not-object",
    ),
    pytest.param(
        _mutated_goal_delta_proposal(lambda delta: delta.update(updates={"goal_id": "goal-3"})),
        id="goal-delta-updates-illegal-key",
    ),
]


@pytest.mark.parametrize(("provider_cls", "provider_type", "payload_builder"), PROVIDER_CASES)
@pytest.mark.parametrize("arguments", _MALFORMED_CONTROL_ARGUMENT_CASES)
def test_malformed_reserved_control_arguments_fail_closed(
    provider_cls, provider_type, payload_builder, arguments
) -> None:
    payload = payload_builder(RESERVED_CONTROL_NAME, copy.deepcopy(arguments))
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json=payload))
    with httpx.Client(transport=transport) as client:
        provider = provider_cls(config=_config(provider_type), http_client=client)
        with pytest.raises(ProviderProtocolError):
            provider.generate(_context())


def _append_native_call(
    provider_type: str,
    payload: dict[str, object],
    *,
    call_id: str,
    name: str,
    arguments: dict[str, object],
) -> None:
    # 冲突场景的响应 fixture 塑形:在既有响应后再挂一个原生调用。
    if provider_type == "anthropic_compatible":
        payload["content"].append(
            {"type": "tool_use", "id": call_id, "name": name, "input": arguments}
        )
    else:
        payload["choices"][0]["message"]["tool_calls"].append(
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)},
            }
        )


@pytest.mark.parametrize(("provider_cls", "provider_type", "payload_builder"), PROVIDER_CASES)
def test_two_reserved_controls_in_one_response_fail_closed(
    provider_cls, provider_type, payload_builder
) -> None:
    payload = payload_builder(RESERVED_CONTROL_NAME, dict(_GOAL_PROGRESS_ARGUMENTS))
    _append_native_call(
        provider_type,
        payload,
        call_id="call-ctl-2",
        name=RESERVED_CONTROL_NAME,
        arguments=copy.deepcopy(_CLARIFICATION_ARGUMENTS),
    )
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json=payload))
    with httpx.Client(transport=transport) as client:
        provider = provider_cls(config=_config(provider_type), http_client=client)
        with pytest.raises(ProviderProtocolError):
            provider.generate(_context())


@pytest.mark.parametrize(("provider_cls", "provider_type", "payload_builder"), PROVIDER_CASES)
def test_ordinary_tool_call_before_reserved_control_fails_closed(
    provider_cls, provider_type, payload_builder
) -> None:
    # 与既有 reserved-then-ordinary 用例互补:顺序颠倒同样 fail closed。
    payload = payload_builder("read_file", {"path": "next.txt"})
    _append_native_call(
        provider_type,
        payload,
        call_id="call-ctl-2",
        name=RESERVED_CONTROL_NAME,
        arguments=dict(_GOAL_PROGRESS_ARGUMENTS),
    )
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json=payload))
    with httpx.Client(transport=transport) as client:
        provider = provider_cls(config=_config(provider_type), http_client=client)
        with pytest.raises(ProviderProtocolError):
            provider.generate(_context())
