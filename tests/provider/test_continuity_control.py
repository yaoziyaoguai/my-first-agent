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
    ExecutionAuthorityClass,
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
                execution_authority=ExecutionAuthorityClass.IN_PROCESS,
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
        workspace_identity_digest="workspace-schema",
        authority_snapshot="authority-schema",
        strict_control_schema=True,
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
    description = context.control_schema["description"]
    assert "Do not use goal_proposal for questions, explanations, or discussion" in description
    assert "explicit bounded task, artifact, or file change" in description
    schema = context.control_schema["input_schema"]
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["kind", "correlation_id"]
    assert set(schema["properties"]["kind"]["enum"]) == {
        "clarification_request",
        "goal_proposal",
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
    proposed = goal_schema["properties"]["proposed_criteria"]["items"]
    assert set(proposed["required"]) == {
        "criterion_id",
        "description",
        "oracle_kind",
        "artifact_path",
    }
    delta_updates = schema["properties"]["delta"]["properties"]["updates"]
    assert "admitted_criteria" not in delta_updates["properties"]
    assert "authority_snapshot" not in delta_updates["properties"]

    strict_schema = context.control_schema["strict_input_schema"]
    assert strict_schema["type"] == "object"
    assert strict_schema["required"] == ["payload"]
    assert strict_schema["additionalProperties"] is False
    variants = strict_schema["properties"]["payload"]["anyOf"]
    assert {
        variant["properties"]["kind"]["enum"][0] for variant in variants
    } == set(schema["properties"]["kind"]["enum"])

    def assert_strict_objects(value: object) -> None:
        if isinstance(value, dict):
            if value.get("type") == "object":
                properties = value.get("properties", {})
                assert set(value.get("required", [])) == set(properties)
                assert value.get("additionalProperties") is False
            for child in value.values():
                assert_strict_objects(child)
        elif isinstance(value, list):
            for child in value:
                assert_strict_objects(child)

    assert_strict_objects(strict_schema)


def test_openai_strict_control_wire_uses_schema_and_unwraps_exact_payload() -> None:
    state = ConversationState(
        conversation_id="strict-control-conversation",
        facts=(
            ConversationFact("action:1:user", FactKind.USER_MESSAGE, {"text": "continue"}),
        ),
        goal=_EXPECTED_GOAL_FRAME,
    )
    context = KernelContextManager(
        system_policy="policy",
        limits=ContextLimits(max_input_tokens=20_000, output_reserve=500),
        workspace_identity_digest="workspace-schema",
        authority_snapshot="authority-schema",
        strict_control_schema=True,
    ).build(
        state,
        SubmitMessage(
            conversation_id=state.conversation_id,
            action_seq=state.next_action_seq,
            expected_revision=state.revision,
            run_id="strict-control-run",
            message="continue",
        ),
        _context().tools,
    )
    context = replace(context, control_receipts=(_control_receipt(),))
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json=_openai_tool_call_payload(
                RESERVED_CONTROL_NAME,
                {"payload": dict(_GOAL_PROGRESS_ARGUMENTS)},
            ),
        )

    config = AgentProviderConfig(
        provider_type="openai_compatible",
        model="fixture-model",
        base_url="https://provider.invalid/beta",
        request_path="/chat/completions",
        credential="fixture-secret",
        strict_tools=True,
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        response = OpenAICompatibleProvider(config=config, http_client=client).generate(context)

    assert response.control == _EXPECTED_CONTROL
    body = requests[0]
    assert body["tool_choice"] == "required"
    functions = {tool["function"]["name"]: tool["function"] for tool in body["tools"]}
    assert all(function["strict"] is True for function in functions.values())
    assert functions[RESERVED_CONTROL_NAME]["parameters"] == context.control_schema[
        "strict_input_schema"
    ]
    assert set(functions) == {"read_file", RESERVED_CONTROL_NAME}
    # strict 模式下回执同样只进 trusted system,不得回放成历史 tool_calls,
    # 否则严格 Tool Calls 模型会模仿历史调用并把回执当成新的可调用工具。
    system_message = body["messages"][0]
    assert system_message["role"] == "system"
    assert _trusted_receipt_line(_control_receipt()) in system_message["content"]
    assert not any(message.get("tool_calls") for message in body["messages"])
    assert all(message.get("role") != "tool" for message in body["messages"])


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
        workspace_identity_digest="workspace-schema",
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
        "goal_delta_proposal",
        "completion_claim",
        "blocked_claim",
    }
    assert "goal_proposal is unavailable" in context.control_schema["description"]
    description = context.control_schema["description"]
    assert "goal_progress is currently unavailable" in description
    assert "call that product tool now" in context.control_schema["description"]


def test_source_result_in_same_user_action_hides_goal_proposal_until_fresh_action(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "agent.runtime.context.source_result_since_latest_user",
        lambda _state: True,
    )
    state = ConversationState(
        conversation_id="source-answer-conversation",
        facts=(
            ConversationFact(
                "action:1:user",
                FactKind.USER_MESSAGE,
                {"text": "answer from a source"},
            ),
        ),
    )
    context = KernelContextManager(
        system_policy="policy",
        limits=ContextLimits(max_input_tokens=20_000, output_reserve=500),
        workspace_identity_digest="workspace-schema",
        authority_snapshot="authority-schema",
    ).build(
        state,
        SubmitMessage(
            conversation_id=state.conversation_id,
            action_seq=state.next_action_seq,
            expected_revision=state.revision,
            run_id="source-answer-run",
            message="answer from a source",
        ),
        (),
    )

    assert context.control_schema is not None
    kinds = context.control_schema["input_schema"]["properties"]["kind"]["enum"]
    assert kinds == ["clarification_request"]
    assert "fresh user action" in context.control_schema["description"]


# U3C-R1B2B(013 修订):控制回执的上行 wire 合同。已受理回执是 runtime 生成的
# durable tuple,必须投影进 trusted SYSTEM 上下文(稳定前缀 + canonical JSON,
# 与 context.system 保序拼接),绝不回放成历史 assistant tool call/result 对——
# 严格 Tool Calls 模型(如 DeepSeek)会模仿历史调用形状,把回执当成新的可调用工具。
_TRUSTED_RECEIPT_PREFIX = "FIRST_AGENT_TRUSTED_CONTROL_RECEIPT"


def _content_blocks(message: dict[str, object]) -> list[dict[str, object]]:
    content = message.get("content")
    if not isinstance(content, list):
        return []
    return [block for block in content if isinstance(block, dict)]


def _trusted_receipt_line(receipt: ControlReceipt) -> str:
    # closed projection:恰好 kind + ControlReceipt 七个持久字段,
    # 不携带 summary/next_step 等易变叙述,可由 durable tuple 逐字节重建。
    return (
        _TRUSTED_RECEIPT_PREFIX
        + " "
        + json.dumps(
            {
                "kind": "control_receipt",
                "correlation_id": receipt.correlation_id,
                "control_kind": receipt.control_kind,
                "goal_id": receipt.goal_id,
                "goal_revision": receipt.goal_revision,
                "accepted_state_revision": receipt.accepted_state_revision,
                "payload_digest": receipt.payload_digest,
                "receipt_digest": receipt.receipt_digest,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
    )


def _second_control_receipt() -> ControlReceipt:
    return ControlReceipt.create(
        correlation_id="ctl-002",
        control_kind="completion_claim",
        goal_id="goal-1",
        goal_revision=2,
        accepted_state_revision=9,
        payload_digest=canonical_json_digest({"criterion_evidence_refs": ["evid-1"]}),
    )


def _assert_no_receipt_replay_in_messages(
    messages: list[dict[str, object]], receipts: tuple[ControlReceipt, ...]
) -> None:
    # 历史消息里不允许出现任何形态的回执 replay:没有 tool 角色消息、
    # 没有 assistant tool_calls/tool_use/tool_result,也没有摊平的回执文本。
    for message in messages:
        assert message.get("role") != "tool"
        assert not message.get("tool_calls")
        for block in _content_blocks(message):
            assert block.get("type") not in {"tool_use", "tool_result"}
        text = json.dumps(message, sort_keys=True)
        assert _TRUSTED_RECEIPT_PREFIX not in text
        for receipt in receipts:
            assert receipt.receipt_digest not in text
            assert receipt.correlation_id not in text


def test_anthropic_control_receipts_project_into_trusted_system_context() -> None:
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "continuing after receipt"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 13, "output_tokens": 7},
            },
        )

    receipts = (_control_receipt(), _second_control_receipt())
    context = replace(
        _context(),
        control_schema=_control_schema(),
        control_receipts=receipts,
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        response = AnthropicCompatibleProvider(
            config=_config("anthropic_compatible"), http_client=client
        ).generate(context)

    assert len(requests) == 1
    body = requests[0]
    # trusted 投影只进 system:context.system 在前,回执行按 durable 顺序在后。
    assert body["system"] == "\n\n".join(
        [context.system, *(_trusted_receipt_line(receipt) for receipt in receipts)]
    )
    # 当前可调用工具面不变:产品工具 + 保留控制名,永远没有可模仿的回执名。
    assert {tool["name"] for tool in body["tools"]} == {"read_file", RESERVED_CONTROL_NAME}
    _assert_no_receipt_replay_in_messages(body["messages"], receipts)
    assert response.control is None
    assert ModelTextBlock("continuing after receipt") in response.blocks


# U3C-R1B2C(013 修订):控制回执的 OpenAI 上行 wire 合同,与 Anthropic 版本
# 语义对称。回执投影必须由第一条 system message 携带,消息历史不得包含
# 任何 assistant tool_calls / tool message 形态的回执 replay。
def test_openai_control_receipts_project_into_trusted_system_context() -> None:
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "continuing after receipt"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 13, "completion_tokens": 7},
            },
        )

    receipts = (_control_receipt(), _second_control_receipt())
    context = replace(
        _context(),
        control_schema=_control_schema(),
        control_receipts=receipts,
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        response = OpenAICompatibleProvider(
            config=_config("openai_compatible"), http_client=client
        ).generate(context)

    assert len(requests) == 1
    body = requests[0]
    messages = body["messages"]
    # trusted 投影只进第一条 system message,与 context.system 保序拼接。
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == "\n\n".join(
        [context.system, *(_trusted_receipt_line(receipt) for receipt in receipts)]
    )
    # 当前可调用工具面不变:产品工具 + 保留控制名,永远没有可模仿的回执名。
    assert {tool["function"]["name"] for tool in body["tools"]} == {
        "read_file",
        RESERVED_CONTROL_NAME,
    }
    _assert_no_receipt_replay_in_messages(messages[1:], receipts)
    assert response.control is None
    assert ModelTextBlock("continuing after receipt") in response.blocks


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
    "proposed_criteria": [
        {
            "criterion_id": "crit-1",
            "description": "summary file exists",
            "oracle_kind": "filesystem_digest",
            "artifact_path": "notes/summary.md",
        }
    ],
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
    proposed_criteria=(
        ProposedCriterion(
            "crit-1",
            "summary file exists",
            oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
            artifact_path="notes/summary.md",
        ),
    ),
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
        workspace_identity_digest="ws-digest-1",
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
        _mutated_goal_proposal(lambda frame: frame["proposed_criteria"][0].pop("oracle_kind")),
        id="proposed-criterion-missing-oracle",
    ),
    pytest.param(
        _mutated_goal_proposal(
            lambda frame: frame["proposed_criteria"][0].update(artifact_path="../escape")
        ),
        id="proposed-criterion-unsafe-artifact-path",
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
