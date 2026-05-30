"""Loop 3.4 — Advanced Scheduler: runtime-owned action graph executor.

中文学习说明：
这不是 cron/定时任务/后台 daemon，也不是第二条 agent 主流程。它是统一 runtime flow
内部的"下一步动作调度器 / action orchestration layer"。它的核心职责是：当 planner
生成了结构化 action plan 后，scheduler 按依赖顺序逐个推进 action node，复用现有
子系统 handler（TOOL_CALL → execute_single_tool 等），记录 evidence，处理失败恢复。

为什么不是独立 workflow engine？
- Scheduler 挂在 run_main_loop() 内层，不替换 model loop（AD-1）
- Scheduler 不解析自然语言，不生成 plan（AD-2/AD-7）
- Scheduler 不创建新的 tool/memory/skill 执行路径（AD-3）
- Scheduler 只是"选择何时执行、以什么顺序执行"（orchestration，非 execution）

与现有 runtime 的关系：
- run_main_loop() 的 while True 中，scheduler 在 call_model() 之前预处理
- 有 pending action → execute it → continue（跳过 model 调用）
- 无 pending action → fall through to model loop（现有路径不变）
- Turn-end hooks 在 scheduler node 完成后仍触发（保持 evidence chain 完整性）
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from agent.runtime_integration.schema import (
    RuntimeActionType,
    new_action_id,
)

# ═══════════════════════════════════════════════════════════════════════════════
# Data Classes
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class ActionRecoveryPolicy:
    """单个 action node 的失败恢复策略（AD-4: halt/skip 最小实现）。

    中文学习说明：
    retry 逻辑需要幂等性保证和 state tracking，本次不实现。halt（停止 plan 并报告）
    和 skip（跳过继续下一个 node）覆盖 90% 实际场景。
    """

    max_retries: int = 0
    """最多重试次数（0 = 不重试，本次不实现 retry 逻辑）。"""

    fallback_node_id: str | None = None
    """失败时 fallback 的目标 node_id。"""

    on_failure: str = "halt"
    """halt（停止并报告）/ skip（跳过继续）/ fallback（执行 fallback_node）。"""

    def __post_init__(self) -> None:
        if self.on_failure not in ("halt", "skip", "fallback"):
            raise ValueError(
                f"invalid on_failure: {self.on_failure!r}, expected halt/skip/fallback"
            )
        if self.on_failure == "fallback" and self.fallback_node_id is None:
            raise ValueError("on_failure=fallback requires fallback_node_id")


@dataclass(frozen=True, slots=True)
class ActionNode:
    """runtime-owned action graph 中的单个 action node。

    每个 node 代表一个 runtime 能验证和执行的操作，复用现有子系统 handler。
    depends_on 定义前置依赖——前置 node 全部完成后才能执行当前 node。
    """

    node_id: str
    """Graph 内唯一标识，如 "step_1", "step_2a"."""

    action_type: str
    """TOOL_CALL / MEMORY_RETAIN / MEMORY_FORGET / SKILL_SELECT / SUBAGENT_DELEGATE / ..."""

    target: str
    """tool name / skill name / subagent name / memory operation."""

    params: Mapping[str, Any] = field(default_factory=dict)
    """传给 target 的参数。"""

    depends_on: tuple[str, ...] = ()
    """前置依赖 node_id 列表——全部完成后才能执行当前 node。"""

    recovery: ActionRecoveryPolicy = field(default_factory=ActionRecoveryPolicy)
    """失败恢复策略。"""

    condition: str | None = None
    """可选 condition flag name——前置 result 设置此 flag 时跳过当前 node（AD-6）。"""

    description: str = ""
    """人类可读的 node 描述（用于 evidence / debug）。"""

    def __post_init__(self) -> None:
        if not self.node_id:
            raise ValueError("ActionNode.node_id must not be empty")
        if not self.action_type:
            raise ValueError("ActionNode.action_type must not be empty")
        if not self.target:
            raise ValueError("ActionNode.target must not be empty")
        object.__setattr__(self, "params", dict(self.params))
        object.__setattr__(self, "depends_on", tuple(self.depends_on))


@dataclass(frozen=True, slots=True)
class ActionPlan:
    """runtime-owned multi-action execution plan。

    plan 从 planner output 构造（AD-7），scheduler 不自己生成 plan。
    """

    plan_id: str
    nodes: tuple[ActionNode, ...]
    entry_node_id: str
    """起始 node_id——第一个被执行的 node。"""
    status: str = "pending"
    """pending / running / completed / failed / halted。"""
    description: str = ""
    """人类可读的 plan 描述。"""

    def __post_init__(self) -> None:
        if not self.plan_id:
            raise ValueError("ActionPlan.plan_id must not be empty")
        if not self.nodes:
            raise ValueError("ActionPlan.nodes must not be empty")
        if self.status not in ("pending", "running", "completed", "failed", "halted"):
            raise ValueError(f"invalid plan status: {self.status!r}")
        # 验证 entry_node_id 存在
        node_ids = {n.node_id for n in self.nodes}
        if self.entry_node_id not in node_ids:
            raise ValueError(
                f"entry_node_id={self.entry_node_id!r} not in nodes"
            )
        # 验证 depends_on 引用
        for node in self.nodes:
            for dep in node.depends_on:
                if dep not in node_ids:
                    raise ValueError(
                        f"node {node.node_id!r} depends_on={dep!r} not in nodes"
                    )


@dataclass
class SchedulerState:
    """per-turn scheduler 运行时状态（mutable，仅本 turn 有效）。

    中文学习说明：
    这是有状态的 mutable dataclass——不是 frozen。因为 scheduler 在
    run_main_loop() 的单次 while True 迭代中逐步修改它。turn 结束后
    可以丢弃或序列化到 checkpoint。
    """

    current_plan: ActionPlan | None = None
    """当前活跃的 action plan。"""

    current_node_id: str | None = None
    """当前正在执行的 node_id。"""

    completed_nodes: set[str] = field(default_factory=set)
    """已完成的 node_id 集合。"""

    failed_nodes: dict[str, int] = field(default_factory=dict)
    """node_id → failure_count（用于 retry 跟踪，AD-4 最小实现中仅记录）。"""

    condition_flags: dict[str, bool] = field(default_factory=dict)
    """AD-6: condition flags——node result 可 set flag，影响后续 node 是否跳过。"""

    node_results: dict[str, Any] = field(default_factory=dict)
    """node_id → result（execution result / error reason）。"""

    status: str = "idle"
    """idle / running / completed / failed / halted。"""

    @property
    def has_active_plan(self) -> bool:
        return self.current_plan is not None and self.status == "running"

    def reset(self) -> None:
        """清空所有 per-turn 状态。"""
        self.current_plan = None
        self.current_node_id = None
        self.completed_nodes.clear()
        self.failed_nodes.clear()
        self.condition_flags.clear()
        self.node_results.clear()
        self.status = "idle"


# ═══════════════════════════════════════════════════════════════════════════════
# Action Executor Protocol
# ═══════════════════════════════════════════════════════════════════════════════

# 中文学习说明：
# execute_node 不直接 import ToolRuntimeMediator / MemoryRetainHandler 等——
# 通过 ActionExecutor callable 注入，保持 scheduler 与子系统的单向依赖。
# 这样 scheduler 只负责 orchestration（何时执行、顺序、失败恢复），
# 不负责 execution（怎么执行、用什么参数调用子系统）。

ActionExecutor = callable  # type: ignore[type-arg]
"""ActionExecutor = Callable[[ActionNode, SchedulerState], dict[str, Any]]

接收 node 和当前 state，返回 result dict（至少含 success: bool）。
实际执行委托给子系统 handler（tool/memory/skill/subagent/checkpoint）。
"""


# ═══════════════════════════════════════════════════════════════════════════════
# ActionScheduler
# ═══════════════════════════════════════════════════════════════════════════════


class ActionScheduler:
    """runtime-owned action graph executor。

    挂在 run_main_loop() 内层，不引入第二条主流程。

    用法:
        scheduler = ActionScheduler(dispatcher=dispatcher, executor=my_executor)
        scheduler.load_plan(plan)

        # 在 run_main_loop() 的 while True 中:
        if scheduler.has_active_plan():
            node = scheduler.next_node()
            if node is not None:
                scheduler.execute_node(node)
                continue  # 跳过 model 调用
            else:
                # plan 完成
                scheduler.complete_plan()
    """

    def __init__(
        self,
        *,
        dispatcher: Any = None,
        executor: ActionExecutor | None = None,
    ) -> None:
        """初始化 scheduler。

        dispatcher: RuntimeActionDispatcher 实例——用于 route_from_runtime_loop()
                   产生 evidence。None 时 scheduler 仍可运行但不产生 evidence。
        executor: ActionExecutor callable——注入子系统执行逻辑。
        """
        self._dispatcher = dispatcher
        self._executor = executor
        self._state = SchedulerState()

    # ── 公共 API ────────────────────────────────────────────────────────────────

    @property
    def state(self) -> SchedulerState:
        return self._state

    def has_active_plan(self) -> bool:
        """是否有 pending action 需要执行。run_main_loop() 用此决定是否跳过 model 调用。"""
        return self._state.has_active_plan

    def next_node(self) -> ActionNode | None:
        """返回下一个待执行的 node，按 depends_on 拓扑顺序。

        Rules:
        1. 只返回 depends_on 全部满足的 node
        2. condition flag 匹配 → 跳过（标记 completed, 记录 skip evidence）
        3. 没有 pending node → 返回 None（plan 完成）
        """
        if self._state.current_plan is None:
            return None

        plan = self._state.current_plan
        for node in plan.nodes:
            if node.node_id in self._state.completed_nodes:
                continue
            # 检查 condition flag（AD-6）
            if node.condition is not None:
                flag_value = self._state.condition_flags.get(node.condition)
                if flag_value:
                    # condition flag 触发 → 跳过此 node
                    self._state.completed_nodes.add(node.node_id)
                    self._state.node_results[node.node_id] = {
                        "success": True,
                        "skipped": True,
                        "reason": f"condition flag {node.condition!r}=True",
                    }
                    self._dispatch_skip_evidence(node)
                    continue
            # 检查 depends_on 是否全部满足
            if all(dep in self._state.completed_nodes for dep in node.depends_on):
                self._state.current_node_id = node.node_id
                return node

        return None  # 所有 node 已完成

    def execute_node(self, node: ActionNode) -> dict[str, Any]:
        """执行单个 action node。

        通过注入的 executor 执行，不在此处 import 子系统模块。
        Scheduler 只负责 orchestration——选择何时、以什么顺序执行。
        实际执行委托给 executor（复用现有 subsystem handler）。

        Returns:
            result dict（至少含 success: bool）
        """
        self._dispatch_node_enter(node)

        if self._executor is None:
            reason = "no executor injected"
            self._state.node_results[node.node_id] = {
                "success": False,
                "error": reason,
            }
            self._state.completed_nodes.add(node.node_id)
            self._dispatch_node_exit(node, success=False)
            return {"success": False, "error": reason}

        try:
            result = self._executor(node, self._state)
        except Exception as exc:
            result = {
                "success": False,
                "error": f"{type(exc).__name__}: {exc}",
            }

        success = bool(result.get("success", False))
        self._state.node_results[node.node_id] = result

        if success:
            self._state.completed_nodes.add(node.node_id)
            # AD-6: merge condition_flags from executor result into scheduler state
            _flags = result.get("condition_flags")
            if isinstance(_flags, dict):
                self._state.condition_flags.update(_flags)
            self._dispatch_node_exit(node, success=True)
        else:
            self._handle_failure(node, result)

        return result

    def load_plan(self, plan: ActionPlan) -> None:
        """加载 action plan 并开始执行。"""
        self._state.reset()
        self._state.current_plan = plan
        self._state.status = "running"
        self._dispatch_plan_start(plan)

    def complete_plan(self) -> None:
        """标记 plan 为 completed 并产生 evidence。"""
        if self._state.current_plan is not None:
            self._dispatch_plan_complete("completed")
        self._state.status = "completed"

    def halt_plan(self, reason: str = "") -> None:
        """标记 plan 为 halted（失败停止）并产生 evidence。"""
        if self._state.current_plan is not None:
            self._state.status = "halted"
            self._dispatch_plan_complete(f"halted: {reason}" if reason else "halted")

    # ── 内部方法 ────────────────────────────────────────────────────────────────

    def _handle_failure(self, node: ActionNode, result: dict[str, Any]) -> None:
        """处理 node 执行失败（AD-4: halt/skip/fallback 最小实现）。"""
        self._state.failed_nodes[node.node_id] = (
            self._state.failed_nodes.get(node.node_id, 0) + 1
        )

        self._dispatch_node_failure(node, result)

        recovery = node.recovery
        if recovery.on_failure == "skip":
            # 跳过当前 node，继续下一个
            self._state.completed_nodes.add(node.node_id)
        elif recovery.on_failure == "fallback" and recovery.fallback_node_id:
            self._state.completed_nodes.add(node.node_id)
            # 不自动执行 fallback——下一轮 next_node() 会返回它
        else:
            # halt: 停止 plan
            error = str(result.get("error", "unknown error"))
            self.halt_plan(f"node {node.node_id!r} failed: {error}")

    def _dispatch_skip_evidence(self, node: ActionNode) -> None:
        """condition flag 触发跳过时记录 NODE_EXIT evidence（skipped）。"""
        self._dispatch_evidence(
            RuntimeActionType.NODE_EXIT,
            {
                "node_id": node.node_id,
                "action_type": node.action_type,
                "target": node.target,
                "disposition": "skipped",
                "success": True,
                "reason": f"condition flag {node.condition!r}=True",
            },
        )

    def _dispatch_node_enter(self, node: ActionNode) -> None:
        self._dispatch_evidence(
            RuntimeActionType.NODE_ENTER,
            {
                "node_id": node.node_id,
                "action_type": node.action_type,
                "target": node.target,
                "plan_id": self._state.current_plan.plan_id if self._state.current_plan else "",
                "params_preview": str(node.params)[:200],
                "depends_on": list(node.depends_on),
            },
        )

    def _dispatch_node_exit(self, node: ActionNode, *, success: bool) -> None:
        self._dispatch_evidence(
            RuntimeActionType.NODE_EXIT,
            {
                "node_id": node.node_id,
                "action_type": node.action_type,
                "target": node.target,
                "disposition": "completed" if success else "failed",
                "success": success,
            },
        )

    def _dispatch_node_failure(self, node: ActionNode, result: dict[str, Any]) -> None:
        self._dispatch_evidence(
            RuntimeActionType.NODE_FAILURE,
            {
                "node_id": node.node_id,
                "action_type": node.action_type,
                "target": node.target,
                "error": str(result.get("error", "unknown")),
                "failure_count": self._state.failed_nodes.get(node.node_id, 0),
                "recovery_on_failure": node.recovery.on_failure,
                "recovery_fallback": node.recovery.fallback_node_id,
            },
        )

    def _dispatch_plan_start(self, plan: ActionPlan) -> None:
        node_ids = [n.node_id for n in plan.nodes]
        self._dispatch_evidence(
            RuntimeActionType.ACTION_PLAN_START,
            {
                "plan_id": plan.plan_id,
                "total_nodes": len(plan.nodes),
                "node_ids": node_ids,
                "entry_node_id": plan.entry_node_id,
                "description": plan.description,
            },
        )

    def _dispatch_plan_complete(self, disposition: str) -> None:
        plan = self._state.current_plan
        completed = len(self._state.completed_nodes)
        total = len(plan.nodes) if plan else 0
        self._dispatch_evidence(
            RuntimeActionType.ACTION_PLAN_COMPLETE,
            {
                "plan_id": plan.plan_id if plan else "",
                "disposition": disposition,
                "completed_nodes": completed,
                "total_nodes": total,
                "failed_nodes": dict(self._state.failed_nodes),
            },
        )

    def _dispatch_evidence(
        self,
        action_type: RuntimeActionType,
        payload: dict[str, Any],
    ) -> None:
        """通过 dispatcher 产生 evidence（AD-5: 全部 business）。

        中文学习说明：
        所有 scheduler evidence 通过 route_from_runtime_loop() 产生，
        与现有 MEMORY_PROPOSE/TOOL_GATE 等 turn-end hook evidence 使用
        相同的 dispatcher 路径，保证 evidence chain 可追溯。
        """
        if self._dispatcher is None:
            return

        try:
            from agent.runtime_integration.schema import RuntimeActionRequest

            request = RuntimeActionRequest(
                action_type=action_type,
                source="action_scheduler._dispatch_evidence",
                parent_trace_id=str(new_action_id()),
                payload=payload,
            )
            self._dispatcher.route_from_runtime_loop(request)
        except Exception:
            # evidence 记录失败不阻塞执行
            pass


# ═══════════════════════════════════════════════════════════════════════════════
# Factory: 从 dict/planner output 构造 ActionPlan
# ═══════════════════════════════════════════════════════════════════════════════


def build_action_plan_from_dict(plan_dict: dict[str, Any]) -> ActionPlan:
    """从 dict 构造 ActionPlan（AD-7: plan 来源——planner output 或 model tool_use sequence）。

    中文学习说明：
    Scheduler 不自己生成 plan。这个 factory 负责将外部 plan 表示（JSON-like dict）
    转换为 runtime 能验证的不可变 ActionPlan。输入可能来自：
    1. planner.generate_plan() → JSON → dict
    2. model tool_use sequence → 动态构造的 dict
    3. 测试 fixture

    输入格式:
        {
            "plan_id": "...",
            "entry_node_id": "step_1",
            "description": "...",
            "nodes": [
                {
                    "node_id": "step_1",
                    "action_type": "TOOL_CALL",
                    "target": "web_search",
                    "params": {"query": "..."},
                    "depends_on": [],
                    "recovery": {"on_failure": "skip"},
                    "condition": None,
                    "description": "...",
                },
                ...
            ],
        }
    """
    nodes_raw: list[dict[str, Any]] = list(plan_dict.get("nodes", []))
    if not nodes_raw:
        raise ValueError("plan_dict must have non-empty 'nodes'")

    nodes: list[ActionNode] = []
    for raw in nodes_raw:
        recovery_raw = raw.get("recovery", {})
        recovery = ActionRecoveryPolicy(
            max_retries=int(recovery_raw.get("max_retries", 0)),
            fallback_node_id=recovery_raw.get("fallback_node_id"),
            on_failure=str(recovery_raw.get("on_failure", "halt")),
        )
        node = ActionNode(
            node_id=str(raw["node_id"]),
            action_type=str(raw["action_type"]),
            target=str(raw["target"]),
            params=raw.get("params", {}),
            depends_on=tuple(str(d) for d in raw.get("depends_on", [])),
            recovery=recovery,
            condition=str(raw["condition"]) if raw.get("condition") else None,
            description=str(raw.get("description", "")),
        )
        nodes.append(node)

    return ActionPlan(
        plan_id=str(plan_dict["plan_id"]),
        nodes=tuple(nodes),
        entry_node_id=str(plan_dict["entry_node_id"]),
        description=str(plan_dict.get("description", "")),
    )


def plan_to_action_plan(plan: Any, plan_id: str = "") -> ActionPlan:
    """从 planner 产出的 Plan 对象构造 ActionPlan。

    中文学习说明：
    这是 planner 和 scheduler 之间的 schema 桥接层（P1 fix）。
    Plan 使用 PlanStep（step_id/title/description/step_type/suggested_tool），
    ActionPlan 使用 ActionNode（node_id/action_type/target/params/depends_on/recovery）。
    本函数负责：
    1. step_type → action_type 映射（read→TOOL_CALL(read_file) 等）
    2. suggested_tool → target（fallback: step_type 推断工具）
    3. 隐式顺序 → 显式 depends_on（step_N depends_on step_N-1）
    4. title+description → ActionNode.description
    5. 默认 recovery=halt（安全默认：失败即停止）

    映射规则：
    - read/analyze → TOOL_CALL, target=read_file 或 suggested_tool
    - edit → TOOL_CALL, target=write_file 或 suggested_tool
    - run_command → TOOL_CALL, target=bash 或 suggested_tool
    - report → TOOL_CALL, target=read_file（报告由模型生成，非工具执行）
    - collect_input/clarify → TOOL_CALL, target=request_user_input
    - 未知 step_type → TOOL_CALL, target=step_type 原值（保持可追溯）
    """
    # 延迟 import 避免循环依赖
    from agent.plan_schema import Plan  # noqa: F811

    if not isinstance(plan, Plan):
        raise TypeError(f"plan_to_action_plan requires Plan object, got {type(plan).__name__}")

    if not plan.steps:
        raise ValueError("Plan.steps must not be empty")

    # step_type → (action_type, default_target) 映射表
    _step_type_map: dict[str, tuple[str, str]] = {
        "read": ("TOOL_CALL", "read_file"),
        "analyze": ("TOOL_CALL", "read_file"),
        "edit": ("TOOL_CALL", "write_file"),
        "run_command": ("TOOL_CALL", "bash"),
        "report": ("TOOL_CALL", "read_file"),
        "collect_input": ("TOOL_CALL", "request_user_input"),
        "clarify": ("TOOL_CALL", "request_user_input"),
    }

    nodes: list[ActionNode] = []
    prev_node_id: str | None = None

    for _i, step in enumerate(plan.steps):
        # 确定 action_type 和 target
        action_type, default_target = _step_type_map.get(
            step.step_type, ("TOOL_CALL", step.step_type)
        )
        target = step.suggested_tool if step.suggested_tool else default_target

        # 构造 params：含 description/expected_outcome/completion_criteria
        params: dict[str, Any] = {}
        if step.description:
            params["description"] = step.description
        if step.expected_outcome:
            params["expected_outcome"] = step.expected_outcome
        if step.completion_criteria:
            params["completion_criteria"] = step.completion_criteria

        # depends_on: 隐式顺序 → 显式依赖（step_N depends_on step_N-1）
        depends_on: tuple[str, ...] = (prev_node_id,) if prev_node_id else ()

        # recovery: 默认 halt（安全默认）
        recovery = ActionRecoveryPolicy(on_failure="halt")

        # description: title + description 合并
        desc = step.title
        if step.description:
            desc += f": {step.description}"

        node = ActionNode(
            node_id=step.step_id,
            action_type=action_type,
            target=target,
            params=params,
            depends_on=depends_on,
            recovery=recovery,
            condition=None,
            description=desc,
        )
        nodes.append(node)
        prev_node_id = step.step_id

    plan_id_final = plan_id if plan_id else f"plan-{plan.goal[:40]}"
    return ActionPlan(
        plan_id=plan_id_final,
        nodes=tuple(nodes),
        entry_node_id=plan.steps[0].step_id,
        description=plan.goal,
    )


def build_action_plan_from_model_output(raw_json: str) -> ActionPlan:
    """从模型输出的 JSON 字符串构造 ActionPlan。

    与 build_action_plan_from_dict 的关键区别：
    - 输入是未验证的模型输出字符串（可能含 markdown code fence、多余字段）
    - 无效 node（缺 node_id/action_type/target）被跳过而非 crash
    - 空 nodes → ValueError
    - 不连接 planner.generate_plan——这是纯 JSON→ActionPlan 桥接

    输入容忍：
    - ```json ... ``` code fence → 自动剥离
    - JSON 内多余未知字段 → 忽略
    - 单个 node 无效 → 跳过（不阻断整个 plan）
    """
    import json as _json

    cleaned = raw_json.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```json").removeprefix("```").strip()
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3].strip()

    plan_dict: dict[str, Any] = _json.loads(cleaned)
    nodes_raw: list[dict[str, Any]] = list(plan_dict.get("nodes", []))

    nodes: list[ActionNode] = []
    skipped: list[str] = []
    for raw in nodes_raw:
        try:
            node_id = str(raw.get("node_id", ""))
            action_type = str(raw.get("action_type", ""))
            target = str(raw.get("target", ""))
        except Exception:
            skipped.append(str(raw.get("node_id", "?")))
            continue

        if not node_id or not action_type or not target:
            skipped.append(node_id or "?")
            continue

        recovery_raw = raw.get("recovery", {})
        try:
            recovery = ActionRecoveryPolicy(
                max_retries=int(recovery_raw.get("max_retries", 0)),
                fallback_node_id=recovery_raw.get("fallback_node_id"),
                on_failure=str(recovery_raw.get("on_failure", "halt")),
            )
        except ValueError:
            recovery = ActionRecoveryPolicy()

        node = ActionNode(
            node_id=node_id,
            action_type=action_type,
            target=target,
            params=raw.get("params", {}),
            depends_on=tuple(str(d) for d in raw.get("depends_on", [])),
            recovery=recovery,
            condition=str(raw["condition"]) if raw.get("condition") else None,
            description=str(raw.get("description", "")),
        )
        nodes.append(node)

    if not nodes:
        raise ValueError(
            f"build_action_plan_from_model_output: no valid nodes "
            f"(parsed {len(nodes_raw)} raw, skipped {len(skipped)}: {skipped})"
        )

    return ActionPlan(
        plan_id=str(plan_dict["plan_id"]),
        nodes=tuple(nodes),
        entry_node_id=str(plan_dict["entry_node_id"]),
        description=str(plan_dict.get("description", "")),
    )
