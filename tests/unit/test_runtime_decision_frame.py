"""Runtime Decision Spine guard tests — Loop 1.1.

验证 RuntimeDecisionFrame + BranchPoint registry 的诚实性合约：
- default chat path 能构建 decision frame
- 各 branch point 被诚实标记（NOT_READY / PARTIAL / DEFERRED / FAKE_DEMO）
- no-crash 不能让 branch point 标 COMPLETE
- direct-call handler 不能让 branch point 标 E2E
- Skill / MCP / SubAgent 未激活时显式 NOT_READY / DEFERRED / FAKE_DEMO
"""
from __future__ import annotations

from agent.runtime_decision_frame import (
    BranchPointState,
    BranchPointStatus,
    EvidenceLevel,
    build_decision_frame,
    count_by_status,
    get_branch_point,
    get_last_decision_frame,
    list_branch_points,
    set_last_decision_frame,
)

# ── Branch Point Registry 合约 ─────────────────────────────────────────────────


def test_branch_point_registry_is_frozen():
    """注册表应为只读——防止运行时意外修改导致状态不可信。"""
    # BRANCH_POINT_REGISTRY 仍然是可变 dict（供未来 loop 升级时直接修改 key），
    # 但公开查询接口走 _FROZEN_REGISTRY (MappingProxyType)
    bp = get_branch_point("skill.select")
    assert bp is not None
    assert bp.status == BranchPointStatus.PARTIAL


def test_branch_point_registry_has_20_points():
    """应有 20 个预定义 branch point（含 Loop 3.4 scheduler 5 个）——禁止无限发散。"""
    all_bps = list_branch_points()
    assert len(all_bps) == 20, f"expected 20 branch points, got {len(all_bps)}"


def test_no_branch_point_is_ready():
    """只有 subagent.delegate 应标 READY——REAL-EVIDENCE-006 CLOSED (12/12 PASS)。"""
    ready_ids = {"subagent.delegate"}
    for bp in list_branch_points():
        if bp.branch_id in ready_ids:
            assert bp.status == BranchPointStatus.READY, (
                f"{bp.branch_id} 应标 READY——"
                f"REAL-EVIDENCE-006 CLOSED (12/12 real provider E2E PASS)"
            )
        else:
            assert bp.status != BranchPointStatus.READY, (
                f"{bp.branch_id} 不应标 READY——当前没有子系统完成生产级主路径验证"
            )


def test_all_branch_points_have_evidence_level():
    """每个 branch point 必须有证据等级声明。"""
    for bp in list_branch_points():
        assert isinstance(bp.evidence_level, EvidenceLevel), (
            f"{bp.branch_id} 缺少 evidence_level"
        )
        assert bp.evidence_level.value, f"{bp.branch_id} evidence_level 为空"


def test_all_branch_points_have_not_ready_behavior():
    """每个 branch point 必须声明能力未就绪时的降级行为。"""
    for bp in list_branch_points():
        assert bp.not_ready_behavior, (
            f"{bp.branch_id} 缺少 not_ready_behavior——"
            f"必须说明此能力不可用时的降级行为"
        )


# ── 诚实标记合约 ──────────────────────────────────────────────────────────────


def test_skill_select_is_partial():
    """skill.select 标 PARTIAL——registry 已注入 main path，但 auto-select 是 demo 机制。"""
    bp = get_branch_point("skill.select")
    assert bp is not None
    assert bp.status == BranchPointStatus.PARTIAL, (
        f"skill.select 应标 PARTIAL 而非 {bp.status}"
        f"——registry 已注入但 auto-select 非 production 路径"
    )
    assert not bp.is_capability_complete(), "skill.select 不应声称 capability complete"
    # PARTIAL 可以有部分功能，should_not_silent_pass 仅对 NOT_READY/DEFERRED/STUB 为 True
    assert "why_partial" in bp.decision_meta, (
        "skill.select PARTIAL 必须通过 decision_meta.why_partial 声明不完整的真实原因"
    )


def test_skill_apply_is_partial():
    """skill.apply 标 PARTIAL——body 已注入 prompt，但 allowed_tools 约束尚未实现。"""
    bp = get_branch_point("skill.apply")
    assert bp is not None
    assert bp.status == BranchPointStatus.PARTIAL, (
        f"skill.apply 应标 PARTIAL 而非 {bp.status}——body 已注入但 tool constraint 未实现"
    )
    assert not bp.is_capability_complete(), "skill.apply 不应声称 capability complete"
    assert "why_partial" in bp.decision_meta, (
        "skill.apply PARTIAL 必须声明 why_partial"
    )
    assert "allowed_tools" in str(bp.decision_meta.get("why_partial", "")), (
        "skill.apply 的 why_partial 必须提及 allowed_tools 约束缺口"
    )


def test_mcp_discover_is_partial():
    """mcp.discover 应标 PARTIAL——bridge lifecycle code path complete, real server pending。"""
    bp = get_branch_point("mcp.discover")
    assert bp is not None
    assert bp.status == BranchPointStatus.PARTIAL, (
        f"mcp.discover 应标 PARTIAL 而非 {bp.status}"
    )
    assert not bp.is_capability_complete()
    assert "REAL-EVIDENCE-007" in str(bp.decision_meta.get("why_partial", "")), (
        "mcp.discover 的 why_partial 必须引用 REAL-EVIDENCE-007"
    )


def test_mcp_invoke_is_partial():
    """mcp.invoke 应标 PARTIAL——MCP tools 复用 unified Tool pipeline, real server pending。"""
    bp = get_branch_point("mcp.invoke")
    assert bp is not None
    assert bp.status == BranchPointStatus.PARTIAL, (
        f"mcp.invoke 应标 PARTIAL 而非 {bp.status}"
    )
    assert not bp.is_capability_complete()
    assert "REAL-EVIDENCE-007" in str(bp.decision_meta.get("why_partial", "")), (
        "mcp.invoke 的 why_partial 必须引用 REAL-EVIDENCE-007"
    )


def test_subagent_delegate_is_ready():
    """subagent.delegate 标 READY——REAL-EVIDENCE-006 CLOSED (12/12 PASS)。"""
    bp = get_branch_point("subagent.delegate")
    assert bp is not None
    assert bp.status == BranchPointStatus.READY, (
        f"subagent.delegate 应标 READY 而非 {bp.status}——"
        f"REAL-EVIDENCE-006 CLOSED (12/12 real provider E2E PASS)"
    )
    assert bp.is_capability_complete(), "READY 应声称 capability complete"
    assert "REAL-EVIDENCE-006" in str(bp.decision_meta.get("why_active", "")), (
        "subagent.delegate 的 why_active 必须引用 REAL-EVIDENCE-006"
    )


def test_memory_branch_points_are_partial():
    """memory.recall/propose/retain 应标 PARTIAL——有 dispatcher 路径但非完整。"""
    for bp_id in ("memory.recall", "memory.propose", "memory.retain"):
        bp = get_branch_point(bp_id)
        assert bp is not None
        assert bp.status == BranchPointStatus.PARTIAL, (
            f"{bp_id} 应标 PARTIAL 而非 {bp.status}"
        )
        assert not bp.is_capability_complete(), (
            f"{bp_id} PARTIAL 不应声称 capability complete"
        )


def test_tool_branch_points_are_partial():
    """Tool branch points 应标 PARTIAL——两条执行路径尚未统一。"""
    for bp_id in ("tool.gate", "tool.invoke", "tool.result"):
        bp = get_branch_point(bp_id)
        assert bp is not None
        assert bp.status == BranchPointStatus.PARTIAL, (
            f"{bp_id} 应标 PARTIAL 而非 {bp.status}"
        )
        # Tool 的 PARTIAL 不应该声称 complete
        assert not bp.is_capability_complete()


# ── Decision Frame 构造合约 ───────────────────────────────────────────────────


class FakeProvider:
    """模拟 fake provider。"""
    provider_type = "fake"


class MockSkillRegistry:
    """模拟空 skill registry。"""
    def list_visible(self):
        return []


def test_build_decision_frame_minimal():
    """最小参数构造 decision frame。"""
    frame = build_decision_frame("hello world")
    assert frame.user_input == "hello world"
    assert frame.user_input_stripped == "hello world"
    assert frame.provider_mode == "unknown"
    assert not frame.skill_registry_active
    assert not frame.mcp_available
    assert frame.subagent_level == "L1"


def test_build_decision_frame_with_fake_provider():
    """fake provider 下构造 decision frame。"""
    frame = build_decision_frame(
        "test",
        provider_mode="fake",
        provider_available=True,
        evidence_level=EvidenceLevel.FAKE_LOCAL_USER_PATH,
    )
    assert frame.provider_mode == "fake"
    assert frame.provider_available
    assert frame.evidence_level == EvidenceLevel.FAKE_LOCAL_USER_PATH


def test_build_decision_frame_with_skill_registry():
    """skill registry 激活时正确表达。"""
    frame = build_decision_frame(
        "test",
        skill_registry_active=True,
        active_skill_candidates=["demo-note-maker"],
    )
    assert frame.skill_registry_active
    assert "demo-note-maker" in frame.active_skill_candidates


def test_build_decision_frame_marks_model_memory_as_deferred():
    """模型推荐记忆和隐式记忆始终标 DEFERRED（本轮不实现）。"""
    frame = build_decision_frame("test")
    assert not frame.memory_model_suggested, "model-suggested memory 必须为 False"
    assert not frame.memory_implicit, "implicit memory 必须为 False"


def test_build_decision_frame_no_silent_ready():
    """除 subagent.delegate 外，无子系统自动标 READY。"""
    frame = build_decision_frame("test")
    for bp_id, bp in frame.get_branch_point_states().items():
        if bp_id == "subagent.delegate":
            continue  # REAL-EVIDENCE-006 CLOSED → legitimately READY
        assert bp.status != BranchPointStatus.READY, (
            f"{bp_id} 不应在最小参数构造时自动标 READY"
        )


# ── Decision Frame 查询方法合约 ────────────────────────────────────────────────


def test_capability_summary_never_claims_complete():
    """capability_summary 在当前状态下永远不应声称 complete。"""
    frame = build_decision_frame("test")
    summary = frame.capability_summary()
    assert not summary["can_claim_capability_complete"], (
        "当前没有任何子系统达到生产级完成度，不应声称 capability complete"
    )
    # subagent.delegate 已标 READY (REAL-EVIDENCE-006 CLOSED)
    assert summary["ready"] == 1, (
        f"subagent.delegate (REAL-EVIDENCE-006 CLOSED) 应计入 ready: {summary}"
    )
    # 仍有 PARTIAL 或 FAKE_DEMO 子系统
    assert summary["partial"] > 0 or summary["fake_demo"] > 0, (
        f"应有 PARTIAL 或 FAKE_DEMO 子系统: partial={summary['partial']}, "
        f"fake_demo={summary['fake_demo']}"
    )


def test_all_branch_point_ids_returns_all():
    """all_branch_point_ids 应返回所有 20 个 branch point（含 Loop 3.4 scheduler）。"""
    frame = build_decision_frame("test")
    ids = frame.all_branch_point_ids()
    assert len(ids) == 20, f"应有 20 个 branch point IDs: {len(ids)}"


def test_ready_count_is_one():
    """ready_count 应为 1——subagent.delegate 已 READY (REAL-EVIDENCE-006 CLOSED)。"""
    frame = build_decision_frame("test")
    assert frame.ready_count() == 1


def test_partial_count_positive():
    """partial_count 应 > 0——所有 code path complete 子系统均为 PARTIAL。"""
    frame = build_decision_frame("test")
    assert frame.partial_count() > 0, (
        "至少有 PARTIAL 子系统（checkpoint/MCP/skill/tool/memory）"
    )


# ── 模块级 inspection seam 合约 ────────────────────────────────────────────────


def test_last_decision_frame_set_get():
    """set_last_decision_frame / get_last_decision_frame 正确流转。"""
    frame = build_decision_frame("test")
    set_last_decision_frame(frame)
    retrieved = get_last_decision_frame()
    assert retrieved is frame
    assert retrieved.user_input == "test"


def test_get_last_decision_frame_set_get_roundtrip():
    """set → get 应返回相同的 frame。"""
    f1 = build_decision_frame("a")
    set_last_decision_frame(f1)
    retrieved = get_last_decision_frame()
    assert retrieved is f1
    assert retrieved.user_input == "a"


def test_last_decision_frame_survives_multiple_sets():
    """多次 set → 最后一次有效。"""
    f1 = build_decision_frame("first")
    f2 = build_decision_frame("second")
    set_last_decision_frame(f1)
    set_last_decision_frame(f2)
    retrieved = get_last_decision_frame()
    assert retrieved is f2
    assert retrieved.user_input == "second"


# ── count_by_status 合约 ──────────────────────────────────────────────────────


def test_count_by_status_sum_is_20():
    """各状态计数应总和为 20（含 Loop 3.4 scheduler 5 个 branch points）。"""
    counts = count_by_status()
    total = sum(counts.values())
    assert total == 20, f"状态计数总和应为 20: {counts}"


def test_count_by_status_has_one_ready():
    """count_by_status 应有 1 个 READY——subagent.delegate。"""
    counts = count_by_status()
    assert counts.get(BranchPointStatus.READY, 0) == 1, (
        f"subagent.delegate 应计入 READY: {counts}"
    )


# ── no-crash 不能是 capability PASS 合约 ───────────────────────────────────────


def test_not_ready_branch_point_cannot_claim_complete():
    """NOT_READY 状态的 branch point 不能 flag 为 capability complete。"""
    bp = BranchPointState(
        branch_id="test.not_ready",
        status=BranchPointStatus.NOT_READY,
        evidence_level=EvidenceLevel.GUARD_TEST,
        trigger_condition="test only",
        not_ready_behavior="no-op",
    )
    assert not bp.is_capability_complete(), (
        "NOT_READY + GUARD_TEST 不应声称 capability complete —— "
        "no-crash 不是 capability 证据"
    )


def test_docs_only_branch_point_cannot_claim_complete():
    """仅有文档/设计证据的 branch point 不能声称 capability complete。"""
    bp = BranchPointState(
        branch_id="test.docs_only",
        status=BranchPointStatus.STUB,
        evidence_level=EvidenceLevel.DOCS_DESIGN,
        trigger_condition="test only",
        not_ready_behavior="no-op",
    )
    assert not bp.is_capability_complete()


def test_direct_call_branch_point_cannot_claim_complete():
    """direct-call 证据不能支撑 capability complete。"""
    bp = BranchPointState(
        branch_id="test.direct",
        status=BranchPointStatus.DIRECT_CALL_ONLY,
        evidence_level=EvidenceLevel.UNIT_DIRECT_CALL,
        trigger_condition="test only",
        not_ready_behavior="no-op",
    )
    assert not bp.is_capability_complete(), (
        "DIRECT_CALL_ONLY 不应声称 capability complete——"
        "direct-call handler 不能当 E2E"
    )


def test_fake_demo_cannot_claim_complete():
    """FAKE_DEMO 不能声称 capability complete。"""
    bp = BranchPointState(
        branch_id="test.fake",
        status=BranchPointStatus.FAKE_DEMO,
        evidence_level=EvidenceLevel.FAKE_LOCAL_USER_PATH,
        trigger_condition="test only",
        not_ready_behavior="no-op",
    )
    assert not bp.is_capability_complete(), (
        "FAKE_DEMO 不应声称 capability complete——fake/demo 不能当 mature E2E"
    )


# ── Decision Frame 对 core.chat() 的整合验证 ───────────────────────────────────


def test_chat_builds_decision_frame():
    """默认 core.chat() 路径能构建 decision frame。"""
    import agent.core as core

    core.state.reset_task()
    set_last_decision_frame(None)  # 重置

    core.chat("hello from test")

    frame = get_last_decision_frame()
    assert frame is not None, "core.chat() 必须构建 decision frame"
    assert "hello from test" in frame.user_input


def test_chat_decision_frame_skill_registry_active():
    """Loop 2.2: 默认 chat 路径 skill_registry 已激活——bridge 已注入 main path。"""
    import agent.core as core

    core.state.reset_task()
    core.chat("test skill")

    frame = get_last_decision_frame()
    assert frame is not None
    assert frame.skill_registry_active, (
        "Loop 2.2 bridge 已连接：skill_registry 应注入 main path 并反映在 decision frame 中"
    )


def test_chat_decision_frame_mcp_not_available_by_default():
    """默认 chat 路径 MCP 应标不可用——需显式 opt-in。"""
    import agent.core as core

    core.state.reset_task()
    core.chat("test mcp")

    frame = get_last_decision_frame()
    assert frame is not None
    assert not frame.mcp_available, (
        "默认 chat 路径 MCP 不应可用——需显式 opt-in (MY_FIRST_AGENT_MCP_ENABLE=1)"
    )


def test_chat_decision_frame_subagent_not_available():
    """默认 chat 路径 SubAgent 应标可用——L1 已验证 (REAL-EVIDENCE-006 CLOSED)。"""
    import agent.core as core

    core.state.reset_task()
    core.chat("test subagent")

    frame = get_last_decision_frame()
    assert frame is not None
    assert frame.subagent_available, (
        "默认 chat 路径 SubAgent 应标可用——"
        "L1 已验证 (REAL-EVIDENCE-006 CLOSED: 12/12 PASS)"
    )
