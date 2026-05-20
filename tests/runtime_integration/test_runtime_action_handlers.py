"""RuntimeAction subsystem handler tests.

这些测试用 fake/local fixture 验证 RuntimeAction path，而不是直接调用子系统后
把结果伪装成 E2E。每个正例都必须经过 dispatcher，并带独立 target_module_proof。
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from agent.runtime_integration import (
    ActionHandlerRegistry,
    RuntimeActionDispatcher,
    RuntimeActionRequest,
    RuntimeActionType,
)
from agent.runtime_integration.checkpoint_summary import CheckpointSafeSummaryHandler
from agent.runtime_integration.memory_hook import MemoryTurnEndProposalHandler
from agent.runtime_integration.skill_action import SkillRuntimeActionHandler
from agent.runtime_integration.streaming_provider import StreamingProviderCallHandler
from agent.runtime_integration.subagent_action import SubAgentDelegateL0Handler
from agent.runtime_integration.tool_gate import DogfoodOverlayTool, ToolGateHandler


def _dispatch(handler, request: RuntimeActionRequest):  # noqa: ANN001
    registry = ActionHandlerRegistry()
    registry.register(request.action_type, handler)
    dispatcher = RuntimeActionDispatcher(registry)
    return dispatcher.route(request), dispatcher


def _write_skill(root: Path, name: str, *, status: str = "active", allowed_tools: tuple[str, ...] = ("read_file",)) -> None:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    skill_dir.joinpath("SKILL.md").write_text(
        dedent(
            f"""\
            ---
            name: {name}
            description: {name} skill
            version: "0.1.0"
            status: {status}
            risk_level: low
            allowed_tools:
            {chr(10).join(f"  - {tool}" for tool in allowed_tools)}
            tags:
              - review
            ---
            # {name}

            Skill body for {name}.
            """
        ),
        encoding="utf-8",
    )


def _skill_request(payload: dict) -> RuntimeActionRequest:
    return RuntimeActionRequest(
        action_type=RuntimeActionType.SKILL_SELECT,
        source="llm_tool_call",
        parent_trace_id="trace-skill",
        payload=payload,
        constraints={"no_network", "no_shell"},
    )


def test_skill_select_uses_model_decision_metadata_and_loads_body_after_selection(tmp_path: Path) -> None:
    """Skill handler 只验证模型结构化选择，body 在 selected_skill_id 后才加载。"""

    skill_root = tmp_path / "skills"
    _write_skill(skill_root, "code-review", status="active")
    _write_skill(skill_root, "docs", status="disabled")

    handler = SkillRuntimeActionHandler.from_roots([skill_root], visible_tool_names={"read_file"})
    request = _skill_request({
        "task_summary": "review core.py",
        "available_skill_metadata": [
            {
                "skill_id": "code-review",
                "description": "code-review skill",
                "tags": ["review"],
                "risk_level": "low",
            }
        ],
        "model_decision_metadata": {
            "selected_skill_id": "code-review",
            "selection_reason": "The task is a code review.",
            "selection_confidence": "high",
        },
        "selected_skill_id": "code-review",
    })

    result, dispatcher = _dispatch(handler, request)

    assert dispatcher.action_log[0].action_type == RuntimeActionType.SKILL_SELECT
    assert result.status == "success"
    assert result.payload["selected_skill_id"] == "code-review"
    assert result.payload["selection_reason"] == "The task is a code review."
    assert result.payload["selection_confidence"] == "high"
    assert result.payload["body_load_decision"] is True
    assert "Skill body for code-review" in result.payload["loaded_body_preview"]
    assert result.evidence["evidence_level"] == "runtime_e2e"
    assert result.evidence["target_module"] == "SkillLoader"
    assert result.evidence["target_module_proof"]["observer_identity"] != "SkillRuntimeActionHandler"
    assert result.evidence["audit_only_skill_exclusion_evidence"]["excluded_count"] == 1
    assert "docs" not in str(result.payload)
    assert "docs" not in str(result.evidence["audit_only_skill_exclusion_evidence"])
    assert "status" not in result.payload["available_skill_metadata"][0]
    assert "body" not in result.payload["available_skill_metadata"][0]


@pytest.mark.parametrize("missing_key", ["selection_reason", "selection_confidence"])
def test_skill_missing_selection_metadata_is_not_runtime_e2e(tmp_path: Path, missing_key: str) -> None:
    """缺 selection_reason/confidence 时 handler 不得后验补字段。"""

    skill_root = tmp_path / "skills"
    _write_skill(skill_root, "code-review", status="active")
    handler = SkillRuntimeActionHandler.from_roots([skill_root], visible_tool_names={"read_file"})
    metadata = {
        "selected_skill_id": "code-review",
        "selection_reason": "review task",
        "selection_confidence": "medium",
    }
    metadata.pop(missing_key)

    result, _ = _dispatch(handler, _skill_request({
        "task_summary": "review core.py",
        "available_skill_metadata": [
            {"skill_id": "code-review", "description": "x", "tags": [], "risk_level": "low"}
        ],
        "model_decision_metadata": metadata,
    }))

    assert result.status == "failed"
    assert result.evidence["evidence_level"] != "runtime_e2e"
    assert result.payload["body_load_decision"] is False


def test_tool_fake_high_risk_blocked_overlay_does_not_pollute_production_registry() -> None:
    """fake.* 只存在于 dogfood overlay；blocked 是 evidence decision，不是 confirmation。"""

    import agent.tools  # noqa: F401
    from agent.tool_registry import TOOL_REGISTRY

    assert "fake.write_file" not in TOOL_REGISTRY
    handler = ToolGateHandler(
        dogfood_overlay={
            "fake.write_file": DogfoodOverlayTool(
                name="fake.write_file",
                requested_capability="file_write",
            )
        }
    )
    request = RuntimeActionRequest(
        action_type=RuntimeActionType.TOOL_REQUEST,
        source="llm_tool_call",
        parent_trace_id="trace-tool",
        payload={
            "tool_name": "fake.write_file",
            "tool_args": {"path": "demo.txt"},
            "risk_reason": "dogfood high-risk blocked path",
            "requested_capability": "file_write",
        },
        constraints={"no_write", "no_shell"},
    )

    result, _ = _dispatch(handler, request)

    assert result.status == "rejected"
    assert result.payload["gate_disposition"] is None
    assert result.evidence["decision"] == "blocked"
    assert result.evidence["requested_tool_name"] == "fake.write_file"
    assert result.evidence["requested_capability"] == "file_write"
    assert result.evidence["production_registry_found"] is False
    assert result.evidence["dogfood_overlay_found"] is True
    assert result.evidence["overlay_tool_name"] == "fake.write_file"
    assert result.evidence["resolved_test_tool_name"] == "fake.write_file"
    assert result.evidence["registry_handler_invoked"] is True
    assert result.evidence["target_module_invoked"] is True
    assert result.evidence["dangerous_tool_function_invoked"] is False
    assert result.evidence["decision"] != "confirmation_required"
    assert "fake.write_file" not in TOOL_REGISTRY


def test_tool_fake_prefix_in_production_registry_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """fake.* 若出现在 production ToolRegistry，必须 fail，不能被 overlay 美化。"""

    from agent.tool_registry import TOOL_REGISTRY

    monkeypatch.setitem(TOOL_REGISTRY, "fake.write_file", {
        "name": "fake.write_file",
        "description": "bad",
        "parameters": {},
        "confirmation": "always",
        "func": lambda **kwargs: "bad",
        "pre_execute": None,
        "post_execute": None,
        "meta_tool": False,
        "capability": "file_write",
        "risk_level": "high",
        "output_policy": "bounded_text",
    })
    handler = ToolGateHandler(
        dogfood_overlay={
            "fake.write_file": DogfoodOverlayTool(
                name="fake.write_file",
                requested_capability="file_write",
            )
        }
    )

    result, _ = _dispatch(handler, RuntimeActionRequest(
        action_type=RuntimeActionType.TOOL_REQUEST,
        source="llm_tool_call",
        parent_trace_id="trace-tool",
        payload={"tool_name": "fake.write_file", "tool_args": {}, "risk_reason": "test"},
        constraints={"no_write"},
    ))

    assert result.status == "failed"
    assert result.evidence["production_registry_found"] is True
    assert result.evidence["decision"] == "failed"
    assert result.evidence["evidence_level"] != "runtime_e2e"


def test_memory_turn_end_proposal_creates_pending_review_without_auto_approve() -> None:
    """Memory hook 是 turn-end proposal，不是 direct store write 或 auto approve。"""

    handler = MemoryTurnEndProposalHandler()
    request = RuntimeActionRequest(
        action_type=RuntimeActionType.MEMORY_TURN_END_PROPOSAL,
        source="runtime_policy",
        parent_trace_id="trace-memory",
        payload={
            "user_message": "记住：我偏好用简体中文解释实现细节",
            "assistant_response": "好的，我会按这个偏好回答。",
            "task_context_summary": "runtime integration test",
            "prior_confirmed_memory_snapshot": None,
        },
        constraints={"no_auto_approve", "no_real_episodes_read"},
    )

    result, _ = _dispatch(handler, request)

    assert result.status == "success"
    assert result.payload["disposition"] == "proposed"
    assert result.payload["proposal_id"]
    assert result.payload["pending_review"] is True
    assert result.payload["not_confirmed"] is True
    assert result.payload["auto_approved"] is False
    assert result.payload["real_episodes_read"] is False
    assert result.evidence["turn_end_hook_invoked"] is True
    assert result.evidence["evidence_level"] == "runtime_e2e"


def test_memory_secret_like_turn_is_redacted_and_not_proposed() -> None:
    """secret-like 内容只能 blocked/no proposal，不能进入 pending review body。"""

    handler = MemoryTurnEndProposalHandler()
    request = RuntimeActionRequest(
        action_type=RuntimeActionType.MEMORY_TURN_END_PROPOSAL,
        source="runtime_policy",
        parent_trace_id="trace-memory",
        payload={
            "user_message": "记住：api_key=sk-testsecret123456789",
            "assistant_response": "ok",
            "task_context_summary": "test",
            "prior_confirmed_memory_snapshot": None,
        },
        constraints={"no_auto_approve"},
    )

    result, _ = _dispatch(handler, request)

    assert result.status == "rejected"
    assert result.payload["proposal_id"] is None
    assert result.payload["disposition"] == "should_not_remember"
    assert result.payload["redacted_secret"] is True
    assert "sk-testsecret" not in str(result.payload)


def test_checkpoint_no_tool_turn_reaches_safe_summary_boundary() -> None:
    """Checkpoint boundary 是 turn-end / before save_checkpoint，不能只在 tool 后触发。"""

    handler = CheckpointSafeSummaryHandler()
    request = RuntimeActionRequest(
        action_type=RuntimeActionType.CHECKPOINT_SAFE_SUMMARY,
        source="runtime_policy",
        parent_trace_id="trace-checkpoint",
        payload={
            "runtime_state_summary": "assistant produced api_key=sk-test123456789 in a template",
            "last_tool_call": None,
            "last_tool_status": None,
            "trigger": "turn_end",
        },
        constraints={"no_schema_change"},
    )

    result, _ = _dispatch(handler, request)

    assert result.status == "success"
    assert result.payload["checkpoint_boundary"] == "turn_end_before_save_checkpoint"
    assert result.payload["no_tool_boundary_reached"] is True
    assert result.payload["secret_content_detected"] is True
    assert "sk-test123456789" not in result.payload["safe_summary"]
    assert result.evidence["checkpoint_schema_changed"] is False
    assert result.evidence["memory_hook_substituted"] is False
    assert result.evidence["evidence_level"] == "runtime_e2e"


def test_streaming_unsupported_provider_fails_closed_without_fake_final() -> None:
    """unsupported provider 只能 not_supported，不能 fallback 后伪造 streaming pass。"""

    handler = StreamingProviderCallHandler()
    request = RuntimeActionRequest(
        action_type=RuntimeActionType.STREAMING_PROVIDER_CALL,
        source="runtime_policy",
        parent_trace_id="trace-stream",
        payload={"provider_supports_streaming": False},
        constraints={"no_fake_final"},
    )

    result, _ = _dispatch(handler, request)

    assert result.status == "not_supported"
    assert result.payload["provider_supports_streaming"] is False
    assert result.payload["events_received"] == 0
    assert result.payload["final_event_received"] is False
    assert result.payload["silent_fallback_used"] is False
    assert result.evidence["evidence_level"] != "runtime_e2e"


def test_streaming_supported_final_only_is_not_runtime_e2e() -> None:
    """final-only 不是 streaming runtime_e2e；必须至少有 delta/final 与 action_id 绑定。"""

    handler = StreamingProviderCallHandler()
    request = RuntimeActionRequest(
        action_type=RuntimeActionType.STREAMING_PROVIDER_CALL,
        source="runtime_policy",
        parent_trace_id="trace-stream",
        payload={
            "provider_supports_streaming": True,
            "events": [{"event_type": "final", "sequence": 1}],
        },
        constraints=set(),
    )

    result, _ = _dispatch(handler, request)

    assert result.status == "success"
    assert result.payload["final_event_received"] is True
    assert result.payload["text_delta_event_received"] is False
    assert result.evidence["module_invoked"] is True
    assert result.evidence["target_module_proof"] is not None
    assert result.evidence["evidence_level"] != "runtime_e2e"


def _write_subagent(root: Path, name: str = "code-reviewer", *, status: str = "active") -> None:
    subagent_dir = root / name
    subagent_dir.mkdir(parents=True)
    subagent_dir.joinpath("SUBAGENT.md").write_text(
        dedent(
            f"""\
            ---
            name: {name}
            description: Code review subagent
            role: reviewer
            model: fake
            status: {status}
            risk_level: low
            allowed_tools:
              - read_file
            memory_scope: none
            max_iterations_default: 1
            confirmation_policy: inherit_tool_policy
            supported_modes:
              - local_fake
            ---
            # {name}
            """
        ),
        encoding="utf-8",
    )


def test_subagent_l0_delegate_uses_payload_name_and_parent_adjudicates(tmp_path: Path) -> None:
    """SubAgent L0 只能由 payload 指定名称，且必须经过 delegate_once + parent adjudication。"""

    subagent_root = tmp_path / "subagents"
    _write_subagent(subagent_root)
    handler = SubAgentDelegateL0Handler.from_roots([subagent_root])
    request = RuntimeActionRequest(
        action_type=RuntimeActionType.SUBAGENT_DELEGATE_L0,
        source="llm_tool_call",
        parent_trace_id="trace-subagent",
        payload={
            "subagent_name": "code-reviewer",
            "delegation_goal": "Review core.py",
            "context_package_summary": "bounded context",
            "allowed_tools": ["read_file"],
            "budget": {"max_iterations": 1},
            "parent_adjudication_required": True,
        },
        constraints={"no_nested_delegation", "no_shell"},
    )

    result, _ = _dispatch(handler, request)

    assert result.status == "success"
    assert result.payload["subagent_name"] == "code-reviewer"
    assert result.payload["subagent_request_built"] is True
    assert result.payload["delegate_once_called"] is True
    assert result.payload["parent_adjudicated"] is True
    assert result.payload["adjudication"] == "accept"
    assert result.payload["no_nested_delegation"] is True
    assert result.payload["no_shell_or_external_process"] is True
    assert result.evidence["parent_adjudicated"] is True
    assert result.evidence["target_module"] == "SubAgentExecutor"
    assert result.evidence["evidence_level"] == "runtime_e2e"


def test_subagent_nested_delegation_is_rejected(tmp_path: Path) -> None:
    """嵌套 delegation 是 L1/L2 方向，本轮必须 fail closed。"""

    subagent_root = tmp_path / "subagents"
    _write_subagent(subagent_root)
    handler = SubAgentDelegateL0Handler.from_roots([subagent_root])
    request = RuntimeActionRequest(
        action_type=RuntimeActionType.SUBAGENT_DELEGATE_L0,
        source="llm_tool_call",
        parent_trace_id="trace-subagent",
        payload={
            "subagent_name": "code-reviewer",
            "delegation_goal": "Spawn another subagent",
            "context_package_summary": "nested",
            "allowed_tools": ["read_file"],
            "budget": {"max_iterations": 1},
            "parent_adjudication_required": True,
            "in_delegation_context": True,
        },
        constraints={"no_nested_delegation"},
    )

    result, _ = _dispatch(handler, request)

    assert result.status == "rejected"
    assert result.payload["no_nested_delegation"] is False
    assert result.payload["delegate_once_called"] is False
    assert result.evidence["evidence_level"] != "runtime_e2e"
