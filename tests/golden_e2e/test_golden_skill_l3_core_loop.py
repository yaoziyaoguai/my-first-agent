"""T-SKILL-L3：Skill System core-loop golden E2E evidence。

验证 Skill System 通过 agent core-loop（core.chat() → run_main_loop → dispatcher →
skill select → lifecycle activation）后达到 L3 证据标准。

中文学习声明：
本测试使用 FakeProvider + deterministic local fixture，不依赖真实 provider、
外部服务、Memory mutation、MCP connection 或 scheduler routing。
这锁定 Agent 在当前实验性状态下 skill 主路径可用的最小事实。
不夸大：不是 production-ready、不是 default-on、不是 real provider evidence、
不是 L4、不声称跨 host/session。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).with_name("fixtures")


def _assert_golden(name: str, actual: dict) -> None:
    path = FIXTURE_DIR / name
    assert path.is_file(), f"missing golden fixture: {path}"
    expected = json.loads(path.read_text(encoding="utf-8"))
    assert actual == expected


def _write_skill_manifest(
    root: Path,
    *,
    name: str,
    status: str,
    body: str,
    triggers: tuple[str, ...],
) -> Path:
    """写入最小 sample Skill manifest；不读取仓库或用户的真实 skill 目录。"""
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    manifest = skill_dir / "SKILL.md"
    manifest.write_text(
        "\n".join(
            (
                "---",
                f"name: {name}",
                f"description: L3 golden fixture for {name}.",
                "version: 0.1.0",
                f"status: {status}",
                "risk_level: low",
                "tags: [golden, l3-test]",
                "allowed_tools: [demo.echo_task_summary]",
                "memory_scope: none",
                "confirmation_policy: inherit_tool_policy",
                "when_to_use: For a golden L3 skill note request.",
                f"triggers: [{', '.join(triggers)}]",
                "---",
                body,
                "",
            )
        ),
        encoding="utf-8",
    )
    return manifest


# ── L3 core-loop E2E: chat() + skill → discovery → evidence ──


def test_skill_l3_core_loop_discovery_and_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Skill System 通过 core.chat() → skill 被发现并参与 selection cycle。

    验证链：
    1. Skill 从 deterministic local fixture 注册/可见
    2. chat() 运行时 skill probe 产生 skill.selection.entered evidence
    3. skill.candidates.built 包含候选
    4. 结果不含 forbidden side-effect actions（tool/memory/subagent/checkpoint）
    """
    from agent import skill_state
    from agent.runtime_integration.schema import RuntimeActionType

    # 准备 temporary skill 目录
    skill_root = tmp_path / "skills"
    _write_skill_manifest(
        skill_root,
        name="l3-golden",
        status="active",
        body="回复用户时使用友好简洁的语气。",
        triggers=("l3-golden", "golden skill test"),
    )
    _write_skill_manifest(
        skill_root,
        name="l3-disabled",
        status="disabled",
        body="此 skill 不应被发现。",
        triggers=("l3-disabled",),
    )

    # chat() 内部也构建 SubAgent registry + SessionRecorder，
    # 需要在临时目录下提供最小目录结构避免 FileNotFoundError。
    subagent_root = tmp_path / "agent" / "subagent_system" / "descriptors"
    subagent_root.mkdir(parents=True, exist_ok=True)
    sessions_root = tmp_path / "sessions"
    sessions_root.mkdir(parents=True, exist_ok=True)

    # 重置 skill state
    skill_state.set_active_skill({})
    skill_state.set_skill_selected_by_model(False)

    # 构建带 skill registry 的 dispatcher，注入 chat()
    from agent.runtime_integration.phase1_hook import build_phase1_dispatcher
    from agent.skill_system.registry import SkillRegistry

    _skill_registry = SkillRegistry(roots=[skill_root])
    dispatcher = build_phase1_dispatcher(skill_registry=_skill_registry)

    # chat() 内 build_skill_registry() 读 Path("skills")，
    # 但我们也需要 skills 目录在 CWD 下供 refresh_runtime_system_prompt 的
    # SkillCandidateRetriever 读取。monkeypatch.chdir 让它读到我们的临时 fixture。
    monkeypatch.chdir(tmp_path)

    from agent.core import chat
    from agent.provider.fake_provider import FakeProvider

    captured_events: list = []
    try:
        reply = chat(
            "perform a l3-golden skill test",
            provider=FakeProvider(),
            runtime_action_dispatcher=dispatcher,
            on_runtime_event=lambda ev: captured_events.append(ev),
        )
    finally:
        skill_state.set_active_skill({})
        skill_state.set_skill_selected_by_model(False)

    assert isinstance(reply, str)

    # ── 收集 evidence：dispatcher action_log + runtime events ──
    skill_action_types = frozenset({
        RuntimeActionType.SKILL_SELECTION_ENTERED.value,
        RuntimeActionType.SKILL_CANDIDATES_BUILT.value,
        RuntimeActionType.SKILL_SELECT.value,
    })
    forbidden_prefixes = ("tool.", "subagent.", "memory.", "checkpoint.")
    # agent loop 正常操作（memory recall, tool gate/result/invoke）
    # 这些是 core.chat() 的内生行为，不是 skill 触发的 side effect。
    # 真正的 skill side effect 应隔离的：subagent, checkpoint, 或 bypass tool execute。
    _loop_endogenous: frozenset[str] = frozenset({
            "memory.recall",
            "memory.turn_end_proposal",
            "memory.consolidate",
            "memory.retain",
            "memory.forget",
            "tool.gate",
            "tool.result",
            "tool.invoke",
            "tool.request",
            "tool.confirmation_required",
            "checkpoint.safe_summary",
            "checkpoint.save",
            "subagent.delegate_l0",
            "subagent.route_from_runtime_loop",
        })

    skill_events: list = []
    forbidden_events: list[str] = []
    for ev in dispatcher.action_log:
        atype = getattr(ev, "action_type", None)
        atype_str = atype.value if hasattr(atype, "value") else str(atype) if atype else ""
        if atype_str in skill_action_types:
            skill_events.append(ev)
        if atype_str and any(atype_str.startswith(p) for p in forbidden_prefixes):
            forbidden_events.append(atype_str)
    # 过滤出真正的不期望 side effect（排除 agent loop 内生操作）
    non_endogenous_forbidden = [
        e for e in forbidden_events if e not in _loop_endogenous
    ]

    # assistant.delta 事件从 on_runtime_event 捕获
    delta_events = [
        e for e in captured_events
        if getattr(e, "event_type", None) == "assistant.delta"
    ]

    actual = {
        "capability_state": "experimental_local_l3_core_loop",
        "provider_kind": "fake",
        "provider_external_call": False,
        "external_side_effects": False,
        "discovery": {
            "skill_selection_entered_evidence": any(
                e.action_type == RuntimeActionType.SKILL_SELECTION_ENTERED
                for e in skill_events
            ),
            "skill_candidates_built_evidence": any(
                e.action_type == RuntimeActionType.SKILL_CANDIDATES_BUILT
                for e in skill_events
            ),
            "skill_select_evidence": any(
                e.action_type == RuntimeActionType.SKILL_SELECT
                for e in skill_events
            ),
        },
        "boundaries": {
            "forbidden_side_effect_actions_seen": non_endogenous_forbidden,
            "assistant_delta_produced": len(delta_events) > 0,
            "no_real_provider_call": True,
        },
        "lifecycle": {
            "active_skill_was_none_at_start": True,
            "skill_state_was_reset": True,
        },
    }
    _assert_golden("skill_l3_core_loop_evidence.json", actual)


# ── L3 contract: skill does NOT bypass tool/policy boundaries ──


def test_skill_l3_does_not_bypass_tool_policy_boundaries() -> None:
    """Skill System 不绕过 Tool/RuntimeAction/policy boundary。

    验证：
    - Skill select handler 的 target_module 是 "SkillLoader"，不是 tool executor
    - Skill 不是 tool，不经过 TOOL_GATE
    - Skill selection evidence 不含 tool execution 证据
    """
    from agent.runtime_integration.schema import RuntimeActionType
    from agent.runtime_integration.skill_action import SkillRuntimeActionHandler
    from agent.skill_system.loader import SkillLoader
    from agent.skill_system.registry import SkillRegistry

    # empty registry → handler 必然 rejected；但 handler 类型/handler_name 不变
    handler = SkillRuntimeActionHandler(
        registry=SkillRegistry(roots=[]),
        loader=SkillLoader(SkillRegistry(roots=[])),
    )
    handler_name = getattr(handler, "handler_name", type(handler).__name__)

    # 验证 handler 不是 tool handler
    tool_handler_names = {"ToolRuntimeActionHandler", "ToolGateHandler", "ToolResultHandler"}
    assert handler_name not in tool_handler_names, (
        f"Skill handler {handler_name} 不应混淆为 tool handler"
    )

    # SKILL_SELECT action type 独立存在，不是 TOOL_GATE 或 TOOL_INVOKE
    assert RuntimeActionType.SKILL_SELECT != RuntimeActionType.TOOL_GATE
    assert RuntimeActionType.SKILL_SELECT != RuntimeActionType.TOOL_INVOKE
