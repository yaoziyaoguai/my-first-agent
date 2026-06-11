"""Unified Runtime Decision Spine — Loop 1.1.

为 First Agent 提供统一的 runtime turn 决策框架，让所有子系统
(Tool/MCP/Skill/Memory/SubAgent/Storage/Checkpoint/Trace) 都通过
有限 branch point 被主路径统一表达，而非各自走 shortcut/direct-call/fake 路径。

这不是新 runtime，不是第二 runtime，不是 scheduler rewrite。
这只是 core/loop 主路径内的轻量"决策脊柱"。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any

# ── Enums ──────────────────────────────────────────────────────────────────────


class BranchPointStatus(StrEnum):
    """Branch point 当前实现状态。"""
    READY = "READY"                        # 已接入主路径，真实执行业务闭环
    PARTIAL = "PARTIAL"                    # 部分接入，存在 direct/shortcut 路径
    DEFERRED = "DEFERRED"                  # 明确延期，不在当前阶段
    NOT_READY = "NOT_READY"                # 能力未就绪
    FAKE_DEMO = "FAKE_DEMO"               # 仅 fake/demo，无真实产品路径
    DIRECT_CALL_ONLY = "DIRECT_CALL_ONLY"  # 只有直接调用路径，无主路径入口
    STUB = "STUB"                          # 接口存在但无实际行为


class EvidenceLevel(StrEnum):
    """证据等级，从低到高。"""
    DOCS_DESIGN = "docs/design"               # 只有设计文档
    GUARD_TEST = "guard test"                  # 守护/不变式测试
    UNIT_DIRECT_CALL = "unit/direct-call"      # 直接子系统调用
    FAKE_LOCAL_USER_PATH = "fake/local user path"  # fake provider 下用户路径
    REAL_API_SMOKE = "real API smoke"          # 真实 API smoke 验证
    REAL_API_INTERACTIVE = "real API interactive"  # 真实 API 交互验证
    PRODUCTION_PATH = "production path"         # 生产级主路径验证


# ── Branch Point State ─────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class BranchPointState:
    """单个 branch point 在当前 turn 中的决策状态。

    这不是 action 执行结果，而是"这个子系统在本 turn 中处于什么状态"的描述。
    """

    branch_id: str
    """Branch point 标识 (如 skill.select, memory.recall, tool.gate)。"""

    status: BranchPointStatus
    """当前实现状态。"""

    evidence_level: EvidenceLevel
    """证据等级。"""

    trigger_condition: str = ""
    """何时会触发此 branch point（如 '每 turn turn-end hook'）。"""

    execution_path: str = ""
    """执行路径描述（如 'core.chat → dispatcher → handler'）。"""

    result_feedback_path: str = ""
    """结果反馈路径（如 'handler → dispatcher result → action_log'）。"""

    not_ready_behavior: str = ""
    """能力未就绪时的降级行为（如 '返回 empty string，引擎不 crash'）。"""

    decision_meta: Mapping[str, Any] = field(default_factory=dict)
    """当前 turn 的额外决策元数据。"""

    def is_capability_complete(self) -> bool:
        """此 branch point 是否可以声称能力完成？"""
        return (
            self.status == BranchPointStatus.READY
            and self.evidence_level in (
                EvidenceLevel.PRODUCTION_PATH,
                EvidenceLevel.REAL_API_INTERACTIVE,
                EvidenceLevel.REAL_API_SMOKE,
                EvidenceLevel.FAKE_LOCAL_USER_PATH,
            )
        )

    def should_not_silent_pass(self) -> bool:
        """此 branch point 是否不应 silent pass？"""
        return self.status in (
            BranchPointStatus.NOT_READY,
            BranchPointStatus.DEFERRED,
            BranchPointStatus.STUB,
        )


# ── Branch Point Registry ──────────────────────────────────────────────────────


# 有限 branch point 清单，禁止无限发散。
# 每个 branch point 声明当前真实状态，不允许 fake/direct-call 标 COMPLETE。
BRANCH_POINT_REGISTRY: dict[str, BranchPointState] = {
    "skill.select": BranchPointState(
        branch_id="skill.select",
        status=BranchPointStatus.PARTIAL,
        evidence_level=EvidenceLevel.FAKE_LOCAL_USER_PATH,
        trigger_condition="每 turn turn-end hook，skill_registry 已注入 LoopDependencies",
        execution_path="loop.turn_end → dispatcher → SkillSelectHandler "
                       "→ model_decision_metadata 校验 → result (success/rejected)",
        result_feedback_path="handler → dispatcher result → action_log → "
                             "_update_active_skill_from_dispatcher",
        not_ready_behavior="skill_registry=None 时 handler 返回 no_suitable_skill，引擎不 crash",
        decision_meta={
            "why_partial": "fake provider 路径通过 turn-end hook 自动选择第一个可见 skill；"
                           "真实模型路径尚未验证 SKILL_SELECT dispatch 是否被模型 tool call 触发；"
                           "auto-select 是 demo 机制，不是 production skill selection",
        },
    ),
    "skill.apply": BranchPointState(
        branch_id="skill.apply",
        status=BranchPointStatus.PARTIAL,
        evidence_level=EvidenceLevel.FAKE_LOCAL_USER_PATH,
        trigger_condition="skill.select 成功后，下一轮 refresh_runtime_system_prompt()",
        execution_path="core.chat → _update_active_skill_from_dispatcher → "
                       "refresh_runtime_system_prompt → build_system_prompt → "
                       "[Active Skill Instructions] section",
        result_feedback_path="system_prompt → model context（body 可见）",
        not_ready_behavior="无 active skill 时 skip，不影响主路径",
        decision_meta={
            "why_partial": "skill body 已注入 model prompt（[Active Skill Instructions]），"
                           "但 allowed_tools 约束尚未实现——模型仍可使用 skill 声明之外的任意工具；"
                           "tool constraint enforcement 是 skill.apply 的核心语义缺口",
        },
    ),
    "memory.recall": BranchPointState(
        branch_id="memory.recall",
        status=BranchPointStatus.PARTIAL,
        evidence_level=EvidenceLevel.FAKE_LOCAL_USER_PATH,
        trigger_condition="每 turn 开始时 refresh_runtime_system_prompt()",
        execution_path="core.chat → refresh_runtime_system_prompt(dispatcher=...) "
                       "→ dispatcher → MemoryRecallHandler → build_system_prompt",
        result_feedback_path="dispatcher result → system_prompt → model context",
        not_ready_behavior=(
            "dispatcher=None 时跳过 prompt-affecting recall，并记录 no_dispatcher_fallback"
        ),
        decision_meta={
            "why_partial": "默认路径需要 injected dispatcher；"
                           "dispatcher=None 时禁止 direct snapshot fallback，"
                           "避免无 evidence 注入 memory",
        },
    ),
    "memory.propose": BranchPointState(
        branch_id="memory.propose",
        status=BranchPointStatus.PARTIAL,
        evidence_level=EvidenceLevel.FAKE_LOCAL_USER_PATH,
        trigger_condition="turn-end hook 检查 pending_retain_proposals 队列",
        execution_path="core.chat → loop turn-end hook → dispatcher → MemoryRetainHandler",
        result_feedback_path="dispatcher result → action_log → store write",
        not_ready_behavior="无 pending proposal 时 skip",
        decision_meta={
            "why_partial": "用户主动 retain 路径已通过 dispatcher；"
                           "model-suggested/implicit 未实现",
        },
    ),
    "memory.retain": BranchPointState(
        branch_id="memory.retain",
        status=BranchPointStatus.PARTIAL,
        evidence_level=EvidenceLevel.FAKE_LOCAL_USER_PATH,
        trigger_condition="memory propose 确认后 retain execution",
        execution_path="dispatcher → MemoryRetainHandler → store.add()",
        result_feedback_path="store write confirmation → action_log",
        not_ready_behavior="retain 失败时 handler 返回 failed 状态",
        decision_meta={
            "why_partial": "用户主动 retain 路径已通过 dispatcher；"
                           "model-suggested/implicit 未实现",
        },
    ),
    "memory.forget": BranchPointState(
        branch_id="memory.forget",
        status=BranchPointStatus.PARTIAL,
        evidence_level=EvidenceLevel.FAKE_LOCAL_USER_PATH,
        trigger_condition="用户输入 forget/删除记忆 等命令时",
        execution_path="core.chat → _forget_via_dispatcher → dispatcher "
                       "→ MemoryForgetHandler → memory_runtime.remove_record()",
        result_feedback_path="dispatcher result → core.py 检查 forgotten 状态 → 用户通知",
        not_ready_behavior="dispatcher 不可用时 handler 返回 rejected",
        decision_meta={
            "why_partial": "dispatcher-mediated forget 主路径已实现；"
                           "L2+L3 contract tests pass（5 L2 + 5 L3 shared-store）；"
                           "store mismatch 已修复（retain/recall/forget 共享同一 store 实例）；"
                           "缺少 real core loop dogfood E2E 验证（实际 /forget 命令交互）",
        },
    ),
    "tool.gate": BranchPointState(
        branch_id="tool.gate",
        status=BranchPointStatus.PARTIAL,
        evidence_level=EvidenceLevel.FAKE_LOCAL_USER_PATH,
        trigger_condition="每 turn turn-end hook",
        execution_path="dispatcher → ToolGateHandler → _safe_noop (default)",
        result_feedback_path="dispatcher result → action_log",
        not_ready_behavior="默认 _safe_noop，不执行真实业务工具",
        decision_meta={
            "why_partial": "RuntimeAction tool pipeline 默认用 _safe_noop probe；"
                           "模型实际 tool_use 走 response_handlers.handle_tool_use_response + "
                           "tool_executor，不走 RuntimeAction pipeline。"
                           "两条 Tool 路径尚未统一。",
        },
    ),
    "tool.invoke": BranchPointState(
        branch_id="tool.invoke",
        status=BranchPointStatus.PARTIAL,
        evidence_level=EvidenceLevel.FAKE_LOCAL_USER_PATH,
        trigger_condition="tool.gate allowed 后触发",
        execution_path="dispatcher → ToolInvokeHandler → execute_single_tool() "
                       "(仅当 gate allowed 且 gate_result 成功)",
        result_feedback_path="dispatcher result → action_log",
        not_ready_behavior="gate blocked 时跳过；模型工具执行走 handle_tool_use_response",
        decision_meta={
            "why_partial": "模型 tool_use → tool_executor 路径和 RuntimeAction "
                           "TOOL_INVOKE 是两条分离路径",
        },
    ),
    "tool.result": BranchPointState(
        branch_id="tool.result",
        status=BranchPointStatus.PARTIAL,
        evidence_level=EvidenceLevel.FAKE_LOCAL_USER_PATH,
        trigger_condition="tool.invoke 完成后触发",
        execution_path="dispatcher → ToolResultHandler",
        result_feedback_path="dispatcher result → action_log (prompt_section 非模型上下文路径)",
        not_ready_behavior="invoke 失败时仍尝试 report error status",
        decision_meta={
            "why_partial": (
                "RuntimeAction TOOL_RESULT prompt_section 不是正常的"
                " 模型上下文反馈路径；模型工具结果通过"
                " tool_executor.append_tool_result() 进入 conversation"
            ),
        },
    ),
    "mcp.discover": BranchPointState(
        branch_id="mcp.discover",
        status=BranchPointStatus.PARTIAL,
        evidence_level=EvidenceLevel.FAKE_LOCAL_USER_PATH,
        trigger_condition="session 启动时 MY_FIRST_AGENT_MCP_ENABLE=1",
        execution_path="main.py → _init_mcp_bridge_if_enabled → run_mcp_bridge()"
                       " (server_allowlist + config_path 显式传入)"
                       " → set_mcp_bridge_result() → dispatcher.route(MCP_BRIDGE_LIFECYCLE)"
                       " → evidence recording",
        result_feedback_path="MCPBridgeReport + dispatcher evidence (MCP_BRIDGE_LIFECYCLE)"
                            " + is_mcp_active() → RuntimeDecisionFrame.mcp_available",
        not_ready_behavior="MCP bridge 默认 disabled；需显式 opt-in",
        decision_meta={
            "why_partial": (
                "code path complete: bridge lifecycle + server_allowlist + config_path"
                " 已通过 main.py 显式传入；mcp_available 由 set_mcp_bridge_result() 动态设置；"
                "仅 FakeMCPClient 验证；真实 MCP server 连接 pending (REAL-EVIDENCE-007)"
            ),
        },
    ),
    "mcp.invoke": BranchPointState(
        branch_id="mcp.invoke",
        status=BranchPointStatus.PARTIAL,
        evidence_level=EvidenceLevel.FAKE_LOCAL_USER_PATH,
        trigger_condition="模型发起 mcp__* tool call（需 MCP_ENABLE + bridge registration 成功）",
        execution_path="get_model_visible_tools(max_mcp_tools=5) → model tool_use →"
                       " handle_tool_use_response → ToolRuntimeMediator →"
                       " TOOL_GATE（含 server_allowlist 校验）→ TOOL_INVOKE"
                       " → TOOL_RESULT → execute_single_tool",
        result_feedback_path="append_tool_result → conversation context（复用 Tool pipeline）",
        not_ready_behavior="production 中 confirmation='always' 默认拦截；"
                           "MCP tools 需用户逐次确认",
        decision_meta={
            "why_partial": (
                "code path complete: MCP 工具复用统一 Tool pipeline（ToolRuntimeMediator"
                " → TOOL_GATE/INVOKE/RESULT → execute_single_tool）；"
                "L3 evidence 已通过 core.chat() 验证（test_mcp_l3_real_core_loop.py）；"
                "mcp_available 动态化（is_mcp_active()）；"
                "真实 MCP server 连接 pending (REAL-EVIDENCE-007)"
            ),
        },
    ),
    "subagent.delegate": BranchPointState(
        branch_id="subagent.delegate",
        status=BranchPointStatus.READY,
        evidence_level=EvidenceLevel.FAKE_LOCAL_USER_PATH,
        trigger_condition="每 turn turn-end hook (SUBAGENT_DELEGATE_L0 probe) + "
                          "CLI delegate/NL delegation shortcut (routes SUBAGENT_DELEGATE_L1, "
                          "falls back to inline-local); SUBAGENT_DELEGATE_V0 registered + "
                          "contract-verified but not yet production-routed",
        execution_path="Live CLI/NL delegation: core.chat → _dispatch_or_fallback_delegation → "
                       "dispatcher.route(SUBAGENT_DELEGATE_L1); L1 handler unregistered → "
                       "falls back to direct inline-local "
                       "(subagent_inline.execute_subagent_delegation, "
                       "execution_mode='local_fake'). "
                       "V0 path (registered, contract-tested, NOT yet "
                       "production-routed): dispatcher.route(SUBAGENT_DELEGATE_V0) "
                       "→ SubAgentV0Handler → V0 contract "
                       "(descriptors + bounded single-turn execution). "
                       "L0 probe: turn-end → SUBAGENT_DELEGATE_L0 → rejected (fallback). "
                       "L0 注册的 handler 与上面 inline-local fallback 不是同一条路径——"
                       "registered L0 是 turn-end probe；live fallback 是直接 inline。",
        result_feedback_path="L1-attempt/inline-local fallback: deterministic "
                             "keyword-match summary; "
                             "V0 (when wired): provider summary + child memory store write",
        not_ready_behavior="V0 handler registered + contract-verified (V0 evidence chain: "
                           "12/12 PASS) but production call site (core.py) still routes "
                           "L1→inline-local fallback; V0 production wiring pending; "
                           "L1 frozen (legacy/compat; not promoted to product); "
                           "L2 native loop SPEC 就绪, gated behind policy; "
                           "TOOL_MEDIATOR_GAP 已知 (production call site fix pending). "
                           "Live path 是 inline-local fallback（local_fake），"
                           "不是 registered L0 handler，也不是 V0 "
                           "（V0 production wiring pending，"
                           "see V0_WIRING_DECISION）。",
        decision_meta={
            "why_active": (
                "REAL-EVIDENCE-006: Live CLI/NL delegation path 已通过 dispatcher + 关键字匹配"
                " 在 fake provider 下验证（12/12 PASS）——但 path 本身是 L1-attempt → direct "
                "inline-local fallback（execution_mode='local_fake'），不是 registered L0 "
                "handler，也不是 V0。V0 contract-verified（12/12）但 production call site"
                "（core.py）尚未 routing；L1 frozen（legacy/compat）；L2 native loop SPEC "
                "就绪，implementation + real provider dogfood deferred。"
            ),
        },
    ),
    "checkpoint.save": BranchPointState(
        branch_id="checkpoint.save",
        status=BranchPointStatus.PARTIAL,
        evidence_level=EvidenceLevel.FAKE_LOCAL_USER_PATH,
        trigger_condition="plan 确认后、memory confirmation 时、loop 完成时",
        execution_path="core.chat → dispatcher.route(CHECKPOINT_SAVE) → "
                       "CheckpointSaveHandler → save_checkpoint → JSON dump",
        result_feedback_path="checkpoint 文件落盘 + dispatcher evidence",
        not_ready_behavior="save 失败不阻塞主路径",
        decision_meta={
            "why_partial": "code path complete: save 走 dispatcher + evidence chain 闭合；"
                           "real API/model validation pending (REAL-EVIDENCE-004)；"
                           "session.py 退出路径仍为 direct call",
        },
    ),
    "checkpoint.resume": BranchPointState(
        branch_id="checkpoint.resume",
        status=BranchPointStatus.PARTIAL,
        evidence_level=EvidenceLevel.FAKE_LOCAL_USER_PATH,
        trigger_condition="启动时存在未完成 checkpoint",
        execution_path="session.resume → load_checkpoint_to_state → "
                       "dispatcher.route(CHECKPOINT_RESUME) → evidence recording",
        result_feedback_path="恢复的 state 进入 main loop + dispatcher evidence",
        not_ready_behavior="resume 失败时从零开始",
        decision_meta={
            "why_partial": "code path complete: load 走 dispatcher evidence recording；"
                           "session.py 中 dispatcher 按需构建（非主 loop dispatcher 实例）；"
                           "real API/model validation pending (REAL-EVIDENCE-004)",
        },
    ),
    "trace.summary": BranchPointState(
        branch_id="trace.summary",
        status=BranchPointStatus.PARTIAL,
        evidence_level=EvidenceLevel.FAKE_LOCAL_USER_PATH,
        trigger_condition="每 turn 结束时 _emit_run_summary()",
        execution_path="loop turn-end → _emit_run_summary → "
                       "dispatcher action_log 统计 + state.task 计数",
        result_feedback_path="run_summary RuntimeEvent → on_runtime_event → UI",
        not_ready_behavior="dispatcher=None 时 action_log 为空，但 state 计数仍可用",
        decision_meta={
            "why_partial": "summary 依赖 in-memory action_log，无 durable evidence store；"
                           "模型 tool 路径和 CLI shortcut 未统一捕获",
        },
    ),
    # Loop 3.4: Advanced Scheduler branch points
    "scheduler.action_plan_start": BranchPointState(
        branch_id="scheduler.action_plan_start",
        status=BranchPointStatus.PARTIAL,
        evidence_level=EvidenceLevel.GUARD_TEST,
        trigger_condition="scheduler.load_plan() 时触发",
        execution_path="scheduler.load_plan → _dispatch_plan_start "
                       "→ dispatcher.route_from_runtime_loop → ActionSchedulerHandler",
        result_feedback_path="handler → evidence catalog → action_log",
        not_ready_behavior="dispatcher=None 时 evidence 收集静默跳过，不影响 plan 执行",
        decision_meta={
            "why_partial": "handler + evidence catalog 已注册；"
                           "缺少 contract test 和 real core loop dogfood 验证",
        },
    ),
    "scheduler.node_enter": BranchPointState(
        branch_id="scheduler.node_enter",
        status=BranchPointStatus.PARTIAL,
        evidence_level=EvidenceLevel.GUARD_TEST,
        trigger_condition="scheduler.execute_node() 开始时触发",
        execution_path="scheduler.execute_node → _dispatch_node_enter "
                       "→ dispatcher.route_from_runtime_loop → ActionSchedulerHandler",
        result_feedback_path="handler → evidence catalog → action_log",
        not_ready_behavior="dispatcher=None 时 evidence 收集静默跳过",
        decision_meta={
            "why_partial": "handler + evidence catalog 已注册；缺少 contract test",
        },
    ),
    "scheduler.node_exit": BranchPointState(
        branch_id="scheduler.node_exit",
        status=BranchPointStatus.PARTIAL,
        evidence_level=EvidenceLevel.GUARD_TEST,
        trigger_condition="scheduler.execute_node() 完成/跳过时触发",
        execution_path="scheduler.execute_node → _dispatch_node_exit / "
                       "_dispatch_skip_evidence → dispatcher.route_from_runtime_loop "
                       "→ ActionSchedulerHandler",
        result_feedback_path="handler → evidence catalog → action_log",
        not_ready_behavior="dispatcher=None 时 evidence 收集静默跳过",
        decision_meta={
            "why_partial": "handler + evidence catalog 已注册；缺少 contract test",
        },
    ),
    "scheduler.node_failure": BranchPointState(
        branch_id="scheduler.node_failure",
        status=BranchPointStatus.PARTIAL,
        evidence_level=EvidenceLevel.GUARD_TEST,
        trigger_condition="scheduler.execute_node() 失败时触发",
        execution_path="scheduler._handle_failure → _dispatch_node_failure "
                       "→ dispatcher.route_from_runtime_loop → ActionSchedulerHandler",
        result_feedback_path="handler → evidence catalog → action_log",
        not_ready_behavior="dispatcher=None 时 evidence 收集静默跳过",
        decision_meta={
            "why_partial": "handler + evidence catalog 已注册；缺少 contract test",
        },
    ),
    "scheduler.action_plan_complete": BranchPointState(
        branch_id="scheduler.action_plan_complete",
        status=BranchPointStatus.PARTIAL,
        evidence_level=EvidenceLevel.GUARD_TEST,
        trigger_condition="scheduler.complete_plan() / halt_plan() 时触发",
        execution_path="scheduler.complete_plan/halt_plan → _dispatch_plan_complete "
                       "→ dispatcher.route_from_runtime_loop → ActionSchedulerHandler",
        result_feedback_path="handler → evidence catalog → action_log",
        not_ready_behavior="dispatcher=None 时 evidence 收集静默跳过",
        decision_meta={
            "why_partial": "handler + evidence catalog 已注册；缺少 contract test "
                           "和 real core loop dogfood 验证",
        },
    ),
}


# 冻结注册表为只读——防止运行时意外修改导致决策脊柱状态不可信。
_FROZEN_REGISTRY: Mapping[str, BranchPointState] = MappingProxyType(BRANCH_POINT_REGISTRY)


def get_branch_point(branch_id: str) -> BranchPointState | None:
    """查询单个 branch point 状态。"""
    return _FROZEN_REGISTRY.get(branch_id)


def list_branch_points() -> list[BranchPointState]:
    """列出所有已注册 branch points。"""
    return list(_FROZEN_REGISTRY.values())


def count_by_status() -> dict[BranchPointStatus, int]:
    """统计各状态的 branch point 数量。"""
    counts: dict[BranchPointStatus, int] = {}
    for bp in _FROZEN_REGISTRY.values():
        counts[bp.status] = counts.get(bp.status, 0) + 1
    return counts


# ── Runtime Decision Frame ─────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class RuntimeDecisionFrame:
    """当前 turn 的统一决策脊柱。

    这不是新 runtime，不是 scheduler。它只是 core/loop 主路径内的决策状态描述，
    帮助统一表达各子系统的参与状态，防止 silent pass / fake PASS / direct-call 冒充 E2E。
    """

    # ── 输入层 ──
    user_input: str = ""
    """当前用户输入（原始文本）。"""

    user_input_stripped: str = ""
    """strip 后的用户输入。"""

    # ── Provider 层 ──
    provider_mode: str = "unknown"
    """Provider 模式：fake / anthropic / anthropic_compatible / unknown。"""

    provider_available: bool = False
    """Provider 是否可用。"""

    # ── Skill 层 ──
    skill_registry_active: bool = False
    """Skill registry 是否激活（不为 None 且有可见 skills）。"""

    active_skill_candidates: list[str] = field(default_factory=list)
    """当前 turn 可选的 skill 候选列表。"""

    skill_branch_points: tuple[str, ...] = ("skill.select", "skill.apply")
    """Skill 相关 branch point IDs。"""

    # ── Memory 层 ──
    memory_explicit_request: bool = False
    """当前输入是否为显式记忆请求。"""

    memory_model_suggested: bool = False
    """模型推荐记忆机会（当前 DEFERRED）。"""

    memory_implicit: bool = False
    """隐式记忆（当前 DEFERRED）。"""

    memory_type: str = "unknown"
    """记忆类型推断：semantic / contextual / procedural / unknown。"""

    memory_branch_points: tuple[str, ...] = (
        "memory.recall", "memory.propose", "memory.retain", "memory.forget",
    )

    # ── Tool 层 ──
    tool_call_expected: bool = False
    """是否预期有工具调用。"""

    tool_gate_tool_name: str = "_safe_noop"
    """Tool gate 时传递的 tool name。"""

    tool_branch_points: tuple[str, ...] = (
        "tool.gate", "tool.invoke", "tool.result",
    )

    # ── MCP 层 ──
    mcp_available: bool = False
    """MCP 工具是否可用（当前 DEFERRED）。"""

    mcp_branch_points: tuple[str, ...] = ("mcp.discover", "mcp.invoke")

    # ── SubAgent 层 ──
    subagent_available: bool = True
    """SubAgent 是否可用——"callable via inline-local (local_fake) fallback"
    on the live path。Available 不再等于 "real API verified"；当前 live
    执行是 inline-local fallback，``evidence_level`` 在 BranchPointState
    上反映这一事实（``FAKE_LOCAL_USER_PATH``）。V0 已 register +
    contract-verify，但 core 尚未 routing（见 ``V0_WIRING_DECISION``）。
    """

    subagent_level: str = "inline_local_fallback"
    """当前 live 实际执行的 subagent path 描述。

    值为冻结常量 ``"inline_local_fallback"``，表达"L1-attempt → direct
    inline-local fallback（``execution_mode='local_fake'``）"这一当前
    runtime fact；它既不暗示注册的 L0 handler 在执行，也不暗示 L0/
    inline 是目标架构（目标是 V0，see ``V0_WIRING_DECISION``）。registered
    vs requested 的区分由 ``BranchPointState["subagent.delegate"]
    .execution_path`` 承担。
    """

    subagent_l2_gated: bool = True
    """L2 是否被 policy gate 拦截（real_llm_tool_requesting_allowed）。"""

    subagent_branch_points: tuple[str, ...] = ("subagent.delegate",)

    # ── Checkpoint 层 ──
    checkpoint_pending: bool = False
    """是否有待处理的 checkpoint 操作。"""

    checkpoint_branch_points: tuple[str, ...] = (
        "checkpoint.save", "checkpoint.resume",
    )

    # ── Confirmation 层 ──
    confirmation_required: bool = False
    """是否需要用户确认。"""

    # ── Result Feedback 层 ──
    result_feedback_expected: bool = True
    """是否预期有结果反馈。"""

    # ── Scheduler 层（Loop 3.4）──
    scheduler_active: bool = False
    """是否有 active action plan（scheduler 正在推进 action node）。"""

    current_plan_id: str = ""
    """当前 active action plan 的 plan_id。"""

    current_node_id: str = ""
    """当前正在执行的 action node_id。"""

    completed_nodes: int = 0
    """已完成的 action node 数。"""

    total_nodes: int = 0
    """当前 plan 的总 action node 数。"""

    scheduler_branch_points: tuple[str, ...] = (
        "scheduler.action_plan_start",
        "scheduler.node_enter",
        "scheduler.node_exit",
        "scheduler.node_failure",
        "scheduler.action_plan_complete",
    )

    # ── Trace / Evidence 层 ──
    evidence_level: EvidenceLevel = EvidenceLevel.DOCS_DESIGN
    """当前 turn 预期证据等级。"""

    trace_summary_expected: bool = True
    """是否预期产出 summary。"""

    trace_branch_points: tuple[str, ...] = ("trace.summary",)

    # ── 元数据 ──
    decision_meta: Mapping[str, Any] = field(default_factory=dict)
    """额外决策元数据。"""

    def all_branch_point_ids(self) -> tuple[str, ...]:
        """返回所有关联的 branch point IDs。"""
        return (
            self.skill_branch_points
            + self.memory_branch_points
            + self.tool_branch_points
            + self.mcp_branch_points
            + self.subagent_branch_points
            + self.checkpoint_branch_points
            + self.scheduler_branch_points
            + self.trace_branch_points
        )

    def get_branch_point_states(self) -> dict[str, BranchPointState]:
        """获取此 frame 关联的所有 branch point 的当前状态。"""
        result: dict[str, BranchPointState] = {}
        for bp_id in self.all_branch_point_ids():
            bp = get_branch_point(bp_id)
            if bp is not None:
                result[bp_id] = bp
        return result

    def ready_count(self) -> int:
        """统计 READY 状态的 branch point 数。"""
        return sum(
            1 for bp in self.get_branch_point_states().values()
            if bp.status == BranchPointStatus.READY
        )

    def not_ready_count(self) -> int:
        """统计 NOT_READY / DEFERRED / STUB 状态的 branch point 数。"""
        return sum(
            1 for bp in self.get_branch_point_states().values()
            if bp.should_not_silent_pass()
        )

    def partial_count(self) -> int:
        """统计 PARTIAL 状态的 branch point 数。"""
        return sum(
            1 for bp in self.get_branch_point_states().values()
            if bp.status == BranchPointStatus.PARTIAL
        )

    def capability_summary(self) -> dict[str, Any]:
        """生成当前 turn 能力摘要。"""
        bp_states = self.get_branch_point_states()
        return {
            "total_branch_points": len(bp_states),
            "ready": self.ready_count(),
            "partial": self.partial_count(),
            "not_ready": self.not_ready_count(),
            "fake_demo": sum(
                1 for bp in bp_states.values()
                if bp.status == BranchPointStatus.FAKE_DEMO
            ),
            "can_claim_capability_complete": all(
                bp.is_capability_complete() for bp in bp_states.values()
            ),
        }


# ── Factory ────────────────────────────────────────────────────────────────────


def build_decision_frame(
    user_input: str,
    *,
    provider_mode: str = "unknown",
    provider_available: bool = False,
    skill_registry_active: bool = False,
    active_skill_candidates: list[str] | None = None,
    memory_explicit_request: bool = False,
    memory_type: str = "unknown",
    tool_gate_tool_name: str = "_safe_noop",
    mcp_available: bool = False,
    subagent_available: bool = True,
    subagent_level: str = "inline_local_fallback",
    subagent_l2_gated: bool = True,
    checkpoint_pending: bool = False,
    confirmation_required: bool = False,
    evidence_level: EvidenceLevel = EvidenceLevel.DOCS_DESIGN,
    decision_meta: Mapping[str, Any] | None = None,
    # Loop 3.4: Scheduler 字段
    scheduler_active: bool = False,
    current_plan_id: str = "",
    current_node_id: str = "",
    completed_nodes: int = 0,
    total_nodes: int = 0,
) -> RuntimeDecisionFrame:
    """构造 RuntimeDecisionFrame。

    这是 core.chat() 入口处调用的一次性工厂，不修改任何状态。
    """
    stripped = user_input.strip()

    return RuntimeDecisionFrame(
        user_input=user_input,
        user_input_stripped=stripped,
        provider_mode=provider_mode,
        provider_available=provider_available,
        skill_registry_active=skill_registry_active,
        active_skill_candidates=active_skill_candidates or [],
        memory_explicit_request=memory_explicit_request,
        memory_model_suggested=False,  # 当前 DEFERRED
        memory_implicit=False,         # 当前 DEFERRED
        memory_type=memory_type,
        tool_gate_tool_name=tool_gate_tool_name,
        mcp_available=mcp_available,
        mcp_branch_points=("mcp.discover", "mcp.invoke"),
        subagent_available=subagent_available,
        subagent_level=subagent_level,
        subagent_l2_gated=subagent_l2_gated,
        checkpoint_pending=checkpoint_pending,
        confirmation_required=confirmation_required,
        evidence_level=evidence_level,
        decision_meta=decision_meta or {},
        scheduler_active=scheduler_active,
        current_plan_id=current_plan_id,
        current_node_id=current_node_id,
        completed_nodes=completed_nodes,
        total_nodes=total_nodes,
    )


# ── Module-level inspection seam ────────────────────────────────────────────────
# 供测试和 evidence 检查用。每次 core.chat() 调用时更新。

_last_decision_frame: RuntimeDecisionFrame | None = None


def set_last_decision_frame(frame: RuntimeDecisionFrame) -> None:
    """存储最近一次 turn 的 decision frame（供测试 inspection）。"""
    global _last_decision_frame
    _last_decision_frame = frame


def get_last_decision_frame() -> RuntimeDecisionFrame | None:
    """获取最近一次 turn 的 decision frame（供测试 inspection）。"""
    return _last_decision_frame


def build_decision_frame_from_chat_params(
    user_input: str,
    *,
    provider=None,
    skill_registry=None,
    runtime_action_dispatcher=None,
    tool_gate_tool_name: str | None = None,
    action_scheduler=None,
    session_id: str = "",
) -> RuntimeDecisionFrame:
    """从 core.chat() 的参数构造 RuntimeDecisionFrame。

    自动推断各子系统状态——不做乐观假设，只陈述已知事实。

    B7: session_id 用于 per-session MCP bridge 查询，避免 decision frame
    总是读 default session。
    """
    # Provider 模式推断
    provider_mode = "unknown"
    provider_available = provider is not None
    if provider is not None:
        provider_type = getattr(provider, "provider_type", "")
        provider_mode = str(provider_type) if provider_type else "unknown"

    # Skill 状态
    skill_registry_active = skill_registry is not None
    active_candidates: list[str] = []
    if skill_registry_active:
        try:
            visible = skill_registry.list_visible()
            active_candidates = [s.name for s in visible]
        except Exception:
            active_candidates = []

    # Tool
    gate_name = tool_gate_tool_name if tool_gate_tool_name else "_safe_noop"

    # Evidence level
    if provider_mode in ("anthropic", "anthropic_compatible") and provider_available:
        ev_level = EvidenceLevel.REAL_API_SMOKE
    elif provider_mode == "fake" or not provider_available:
        ev_level = EvidenceLevel.FAKE_LOCAL_USER_PATH
    else:
        ev_level = EvidenceLevel.GUARD_TEST

    # MCP 默认 disabled（需显式 opt-in）。
    # Loop 3.3: mcp_available 不再硬编码——由 main.py bridge 成功后
    # set_mcp_bridge_result() 设置，is_mcp_active() 动态读取。
    from agent.mcp_bridge import is_mcp_active as _is_mcp_active

    # Loop 3.4: Scheduler 状态——从注入的 ActionScheduler 实例读取
    _scheduler_active = False
    _plan_id = ""
    _node_id = ""
    _completed = 0
    _total = 0
    if action_scheduler is not None:
        _sched_state = getattr(action_scheduler, "state", None)
        if _sched_state is not None:
            _scheduler_active = _sched_state.has_active_plan
            if _sched_state.current_plan is not None:
                _plan = _sched_state.current_plan
                _plan_id = _plan.plan_id
                _total = len(_plan.nodes)
            _node_id = _sched_state.current_node_id or ""
            _completed = len(_sched_state.completed_nodes)

    # B7: session_id 非空时查询 per-session MCP bridge，否则回退 default。
    _mcp_active = _is_mcp_active(session_id=session_id) if session_id else _is_mcp_active()

    return build_decision_frame(
        user_input=user_input,
        provider_mode=provider_mode,
        provider_available=provider_available,
        skill_registry_active=skill_registry_active,
        active_skill_candidates=active_candidates,
        memory_explicit_request=False,  # 由 evaluate_user_text 后置判定
        tool_gate_tool_name=gate_name,
        mcp_available=_mcp_active,
        subagent_available=True,   # live 路径可调用（inline-local fallback）
        subagent_level="inline_local_fallback",  # 当前 live 实际执行的 path
        subagent_l2_gated=True,    # L2 gated behind policy
        evidence_level=ev_level,
        decision_meta={
            "has_dispatcher": runtime_action_dispatcher is not None,
            "has_skill_registry": skill_registry_active,
        },
        scheduler_active=_scheduler_active,
        current_plan_id=_plan_id,
        current_node_id=_node_id,
        completed_nodes=_completed,
        total_nodes=_total,
    )
