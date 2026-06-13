"""Architecture Characterization Pack 1：runtime 边界 inventory tests。

本文件是 v0.6.2 TUI MVP 封版后的第一层去巨石化安全网。它不执行真实
Runtime、不调用模型、不读 checkpoint 文件、不读取 `.env` / `agent_log.jsonl`
或真实 `sessions` / `runs` 内容；只用 AST 读取源码，把当前架构边界固化成
可回归的 characterization baseline。

为什么现在只写测试、不重构
--------------------------
architecture audit 已经确认：`core.py` 是 runtime hub，checkpoint save/clear
ownership 与 runtime state mutation ownership 分散在多个 handler/executor 中。
这些是债务，但直接拆 core 或集中 checkpoint 会同时碰到模型循环、pending
confirmation、tool execution、resume 语义。正确顺序是先钉住当前边界，再做
行为中性的 helper extraction；否则后续重构无法证明没有移动 runtime 决策。

baseline 不是永久禁令
--------------------
本文件里的 import / checkpoint / mutation inventory 都是 characterization：
未来确实需要新增调用点时，可以更新 baseline，但必须在 PR 中解释新 owner
为什么属于 runtime 层，而不是为了让测试通过随手扩大白名单。尤其是 input
backend / display / TUI 相关模块，不能通过 import core/checkpoint 或直接
mutate state 来绕过 runtime/handler 边界。
"""

from __future__ import annotations

import ast
import re
import textwrap
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
AGENT_DIR = PROJECT_ROOT / "agent"
OUT_OF_SCOPE_AGENT_PARTS = {"skills", "subagents"}
SUBAGENT_SYSTEM_DIR = AGENT_DIR / "subagent_system"

CORE_FILE = AGENT_DIR / "core.py"
LOOP_FILE = AGENT_DIR / "loop.py"
USER_INPUT_FILE = AGENT_DIR / "user_input.py"
DISPLAY_EVENTS_FILE = AGENT_DIR / "display_events.py"
INPUT_BACKEND_FILES = (
    AGENT_DIR / "input_backends" / "simple.py",
    AGENT_DIR / "input_backends" / "textual.py",
)
INPUT_DISPLAY_BOUNDARY_FILES = INPUT_BACKEND_FILES + (
    USER_INPUT_FILE,
    DISPLAY_EVENTS_FILE,
)


def _module_name(path: Path) -> str:
    """把源码路径转成 importable module name，`__init__.py` 归到 package。"""

    parts = list(path.relative_to(PROJECT_ROOT).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _agent_python_files() -> tuple[Path, ...]:
    """列出本轮架构守卫覆盖的 production `agent/` Python 源码。

    Skill/SubAgent 现有 prototype 是 future rewrite 范围；本测试包只守
    Non-Skill/SubAgent runtime 边界，避免 out-of-scope 原型影响全局 cleanup。
    """

    return tuple(
        sorted(
            path
            for path in AGENT_DIR.rglob("*.py")
            if "__pycache__" not in path.parts
            and not (OUT_OF_SCOPE_AGENT_PARTS & set(path.relative_to(AGENT_DIR).parts))
        )
    )


def _read_tree(path: Path) -> ast.Module:
    """AST 解析源码；只读文本，不 import production module，避免副作用。"""

    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _qualified_name(node: ast.AST) -> str | None:
    """返回 Name/Attribute/Subscript 的 dotted 名称，用于 AST inventory。"""

    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _qualified_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Subscript):
        return _qualified_name(node.value)
    return None


def _parent_map(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    return parents


def _enclosing_scope(tree: ast.AST, target: ast.AST) -> str:
    """找到调用/赋值所在函数；不用行号，避免 characterization 过脆。"""

    parents = _parent_map(tree)
    current = target
    while current in parents:
        current = parents[current]
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current.name
        if isinstance(current, ast.ClassDef):
            return f"{current.name}.<class>"
    return "<module>"


def _phase2_transition_request_inventory() -> set[tuple[str, str, str, str, str]]:
    """收集 Phase 2 transition request 的真实 call-site 使用关系。

    table exactness 只能证明规则集合完整；这里从 production AST 读取 event、
    expected_from_status 和 owner，防止 handler 回退后留下未使用规则。
    """

    phase2_events = {
        "USER_INPUT_RESOLVED",
        "STEP_CONFIRMATION_REQUIRED",
        "USER_INPUT_REQUIRED",
    }
    inventory: set[tuple[str, str, str, str, str]] = set()
    for path in (
        AGENT_DIR / "transitions.py",
        AGENT_DIR / "response_handlers.py",
        AGENT_DIR / "tool_executor.py",
    ):
        tree = _read_tree(path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if _qualified_name(node.func) != "TaskTransitionRequest":
                continue

            keywords = {keyword.arg: keyword.value for keyword in node.keywords}
            event_node = keywords.get("event")
            expected_node = keywords.get("expected_from_status")
            owner_node = keywords.get("owner")
            if not isinstance(event_node, ast.Attribute):
                continue
            if event_node.attr not in phase2_events:
                continue
            if expected_node is None or owner_node is None:
                continue

            expected_statuses = {
                child.value
                for child in ast.walk(expected_node)
                if isinstance(child, ast.Constant) and isinstance(child.value, str)
            }
            owners = {
                child.value
                for child in ast.walk(owner_node)
                if isinstance(child, ast.Constant) and isinstance(child.value, str)
            }
            for expected_status in expected_statuses:
                for owner in owners:
                    inventory.add(
                        (
                            _module_name(path),
                            _enclosing_scope(tree, node),
                            event_node.attr,
                            expected_status,
                            owner,
                        )
                    )
    return inventory


def _phase3_transition_request_inventory() -> set[tuple[str, str, str, str, str]]:
    """收集 Phase 3 直接 request 与 task-runtime 动态 request 的真实位置。"""
    phase3_events = {
        "MEMORY_CONFIRMATION_REQUIRED",
        "MEMORY_CONFIRMATION_RESOLVED",
        "PLAN_GENERATED",
        "TOOL_CONFIRMATION_REQUIRED",
    }
    inventory: set[tuple[str, str, str, str, str]] = set()
    for path in (
        AGENT_DIR / "core.py",
        AGENT_DIR / "memory_interaction.py",
        AGENT_DIR / "tool_executor.py",
        AGENT_DIR / "tool_runtime_mediator.py",
        AGENT_DIR / "transitions.py",
    ):
        tree = _read_tree(path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if _qualified_name(node.func) != "TaskTransitionRequest":
                continue

            keywords = {keyword.arg: keyword.value for keyword in node.keywords}
            event_node = keywords.get("event")
            expected_node = keywords.get("expected_from_status")
            owner_node = keywords.get("owner")
            event_name = _qualified_name(event_node) if event_node is not None else None
            event = (
                event_name.rsplit(".", 1)[-1]
                if event_name and event_name.startswith("TransitionEvent.")
                else "<dynamic>"
            )
            if event not in phase3_events and event != "<dynamic>":
                continue

            expected_statuses = {
                child.value
                for child in ast.walk(expected_node)
                if isinstance(child, ast.Constant) and isinstance(child.value, str)
            } if expected_node is not None else set()
            owners = {
                child.value
                for child in ast.walk(owner_node)
                if isinstance(child, ast.Constant) and isinstance(child.value, str)
            } if owner_node is not None else set()
            for expected_status in expected_statuses or {"<dynamic>"}:
                for owner in owners or {"<dynamic>"}:
                    inventory.add(
                        (
                            _module_name(path),
                            _enclosing_scope(tree, node),
                            event,
                            expected_status,
                            owner,
                        )
                    )
    return inventory


def _phase3_step_advance_caller_inventory() -> set[tuple[str, str, str]]:
    """收集共享 task-runtime 六条 rule 的三个真实 handler caller。"""
    inventory: set[tuple[str, str, str]] = set()
    for path in (
        AGENT_DIR / "transitions.py",
        AGENT_DIR / "confirmation" / "plan.py",
        AGENT_DIR / "response_handlers.py",
    ):
        tree = _read_tree(path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if _qualified_name(node.func) != "advance_current_step_if_needed":
                continue
            owner_node = next(
                (keyword.value for keyword in node.keywords if keyword.arg == "owner"),
                None,
            )
            if not isinstance(owner_node, ast.Constant) or not isinstance(
                owner_node.value, str
            ):
                continue
            inventory.add(
                (_module_name(path), _enclosing_scope(tree, node), owner_node.value)
            )
    return inventory


def _collect_agent_imports(path: Path) -> set[str]:
    """收集一个源码文件声明的 `agent.*` 依赖。

    `from agent import checkpoint` 会归一成 `agent.checkpoint`，这样 import
    graph inventory 能看到真实子模块边界，而不是只看到 package 名。
    """

    tree = _read_tree(path)
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "agent" or alias.name.startswith("agent."):
                    imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module == "agent":
                imports.update(f"agent.{alias.name}" for alias in node.names)
            elif node.module and node.module.startswith("agent."):
                imports.add(node.module)
    return imports


def _collect_imports(path: Path) -> set[str]:
    tree = _read_tree(path)
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def test_core_does_not_import_or_construct_anthropic_sdk() -> None:
    """core.py 只能依赖 provider abstraction，不能直接持有 SDK client。

    这条守 P1 provider 边界：新增 native/compatible provider 时，runtime 主循环
    不应再改 core.py，也不能在 core.py 根据 SDK 或 provider URL 分支。
    """

    tree = _read_tree(CORE_FILE)
    imports = _collect_imports(CORE_FILE)
    assert "anthropic" not in imports

    bad_calls: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _qualified_name(node.func) == "anthropic.Anthropic":
            bad_calls.append(f"line {node.lineno}")
    assert bad_calls == []


def test_non_provider_runtime_modules_do_not_import_provider_sdks() -> None:
    """非 provider 边界不得直接依赖 Anthropic/OpenAI Python SDK。

    这条 P3 审计护栏回答用户担心的 "Claude Code / Claude / Python SDK"
    是否扩散到全局架构：core、Memory、Skill、SubAgent 只能依赖 provider
    interface/factory 或 legacy facade，SDK lazy import 只能留在 agent/provider/。
    """

    checked_paths = [
        Path("agent/core.py"),
        Path("agent/model_call.py"),
        *Path("agent").glob("memory*.py"),
        *Path("agent/skill_system").glob("*.py"),
        *Path("agent/subagent_system").glob("*.py"),
    ]
    forbidden_imports = {"anthropic", "openai"}

    offenders: list[str] = []
    for path in checked_paths:
        imports = _collect_imports(path)
        leaked = sorted(imports & forbidden_imports)
        if leaked:
            offenders.append(f"{path}: {', '.join(leaked)}")

    assert offenders == []


def _checkpoint_call_inventory() -> Counter[tuple[str, str, str]]:
    """收集 checkpoint API 调用点。

    这里记录 `(module, function, operation)` 并保留 count：同一函数新增一次
    save/clear 也应被 review，但不用行号来锁源码排版。
    """

    operations = {
        "save_checkpoint",
        "clear_checkpoint",
        "load_checkpoint",
        "load_checkpoint_to_state",
    }
    inventory: Counter[tuple[str, str, str]] = Counter()

    for path in _agent_python_files():
        tree = _read_tree(path)
        module = _module_name(path)
        checkpoint_aliases: dict[str, str] = {}
        for import_node in ast.walk(tree):
            if isinstance(import_node, ast.ImportFrom):
                if import_node.module == "agent":
                    for alias in import_node.names:
                        if alias.name == "checkpoint":
                            checkpoint_aliases[alias.asname or alias.name] = (
                                "agent.checkpoint"
                            )
                elif import_node.module == "agent.checkpoint":
                    for alias in import_node.names:
                        if alias.name in operations:
                            checkpoint_aliases[alias.asname or alias.name] = (
                                f"agent.checkpoint.{alias.name}"
                            )
            elif isinstance(import_node, ast.Import):
                for alias in import_node.names:
                    if alias.name == "agent.checkpoint":
                        checkpoint_aliases[alias.asname or alias.name] = (
                            "agent.checkpoint"
                        )

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _qualified_name(node.func)
            if not name:
                continue

            operation: str | None = None
            if module == "agent.checkpoint" and name in operations:
                operation = name
            elif name in checkpoint_aliases and checkpoint_aliases[name].startswith(
                "agent.checkpoint."
            ):
                operation = checkpoint_aliases[name].rsplit(".", 1)[-1]
            elif "." in name:
                base, attr = name.rsplit(".", 1)
                if checkpoint_aliases.get(base) == "agent.checkpoint" and attr in operations:
                    operation = attr
                elif module == "agent.loop" and name == "dependencies.clear_checkpoint":
                    operation = "clear_checkpoint"

            if operation in operations:
                inventory[(module, _enclosing_scope(tree, node), operation)] += 1
    return inventory


def _is_state_expression(node: ast.AST) -> bool:
    name = _qualified_name(node)
    return bool(name and (name == "state" or name.startswith("state.")))


def _runtime_state_mutation_inventory() -> set[tuple[str, str, str]]:
    """收集对 module-level `state` 的可见 mutation owner。

    这不是完整数据流分析；它刻意只覆盖当前代码实际使用的 mutation 形态：
    `state.task.* = ...`、`state.conversation.* = ...`、`state.memory.* = ...`、
    `state.reset_task()`、`state.set_system_prompt()` 与 checkpoint restore 中的
    `setattr(state.task/memory, ...)`。目标是先防新增 owner，而不是本轮修复
    已存在的 mutation scattering。
    """

    inventory: set[tuple[str, str, str]] = set()
    for path in _agent_python_files():
        tree = _read_tree(path)
        module = _module_name(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = _qualified_name(node.func)
                if name in {"state.reset_task", "state.set_system_prompt"}:
                    inventory.add((module, _enclosing_scope(tree, node), f"{name}()"))
                if (
                    name == "setattr"
                    and node.args
                    and _is_state_expression(node.args[0])
                ):
                    target = _qualified_name(node.args[0])
                    inventory.add(
                        (module, _enclosing_scope(tree, node), f"setattr({target}, ...)")
                    )

            if not isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target_node in targets:
                name = _qualified_name(target_node)
                if name and (
                    name.startswith("state.task.")
                    or name.startswith("state.conversation.")
                    or name.startswith("state.memory.")
                    or name.startswith("state.runtime.")
                ):
                    inventory.add((module, _enclosing_scope(tree, target_node), name))
    return inventory


def test_core_agent_import_baseline_is_reviewed() -> None:
    """core.py 是 runtime orchestrator，但不能悄悄吸收新层依赖。

    这条测试不要求现在拆 core，也不禁止未来新增 import。它把当前 import
    surface 钉成 baseline：未来如果 core 需要直接依赖 input backend、checkpoint
    gateway 之外的新 runtime 子系统，必须显式 review，而不是在重构中顺手加入。
    """

    expected = {
        "agent.checkpoint",
        "agent.confirm_handlers",
        "agent.context_builder",
        "agent.core_contexts",
        "agent.display_events",
        "agent.loop",
        "agent.loop_context",
        "agent.memory",
        "agent.memory_interaction",
        "agent.memory_l2",
        "agent.memory_runtime",
        "agent.model_call",
        "agent.model_output_dispatch",
        "agent.pending_confirmation_dispatch",
        "agent.planner",
        "agent.prompt_builder",
        "agent.protocol_debug",
        "agent.response_handlers",
        "agent.runtime_event_safety",
        # v0.9.x Stabilization Phase 1：core slimming 允许这个行为中性 helper。
        # 它只能承载 runtime loop 字段/快照辅助逻辑，用于最小 debug/audit
        # evidence；不得拥有主 loop、ToolRegistry、Memory、Skill、SubAgent、
        # Checkpoint schema 或 provider 调用。
        "agent.runtime_loop_fields",
        # Phase 1 real core loop E2E：core.chat() 内部 local import，仅用于
        # 构建 RuntimeActionDispatcher 并注入到 LoopContext。不改变 core 的
        # 模块级 import surface，不引入新的模块级耦合。
        "agent.runtime_integration.phase1_hook",
        "agent.runtime_integration.skill_lifecycle",
        # Loop 3 (Memory E2E)：refresh_runtime_system_prompt() 内部 local import，
        # 仅用于构造 RuntimeActionRequest 并 dispatch MEMORY_RECALL。
        # 不改变 core 的模块级 import surface，不引入新的模块级耦合。
        "agent.runtime_integration.schema",
        # Post-Memory hardening：CLI meta-command glue 从 core.py 移到专用
        # handler；core 只做薄 dispatch，不直接承载 show/forget/show-subagents
        # 行为分支。
        "agent.runtime_integration.cli_handlers",
        "agent.state",
        # Phase 2 SubAgent demo：chat() 内 local import，仅用于
        # "show subagents" CLI meta-command。
        # 不改变 core 的模块级 import surface，不引入新的模块级耦合。
        "agent.subagent_system.registry",
        # Issue 1 Command Router extraction：CLI meta-command detect/render
        # 提取到独立模块。core.py 模块级 import cli_commands 以获取检测
        # 函数（_looks_like_*）和渲染函数。不引入新的 runtime 路径。
        "agent.cli_commands",
        "agent.tool_registry",
        "agent.tools",
        # Loop 8 (Surgical Hub Slimming)：_resolve_provider_evidence_metadata
        # 提取到 agent/provider_evidence.py。纯函数，零 intra-core 依赖。
        "agent.provider_evidence",
        # Loop 8 (Surgical Hub Slimming)：_execute_subagent_delegation
        # 提取到 agent/subagent_inline.py。行为保持型提取，所有委托执行
        # 仍通过 delegate_once() + SubAgentRegistry，不绕过统一入口。
        "agent.subagent_inline",
        # U3: SUBAGENT_V0_ROUTING_ENABLED env flag helper（default-off, opt-in）。
        "agent.subagent_routing_flag",
        # V0 budget constants（DEFAULT_V0_MAX_CONTEXT_CHARS / DEFAULT_V0_MAX_FILES）
        # used by production builder to source canonical context budget.
        "agent.subagent_system.v0_contract",
        # ── B7 Multi-Instance Readiness imports ──
        # 以下 imports 均为 B7 identity/namespace/checkpoint/memory/lifecycle
        # 主线所需。每个 import 都对应 B7 的具体能力：
        #   - runtime_identity: per-session identity (session_id/run_id)
        #   - runtime_decision_frame: chat() 入口决策帧 evidence
        #   - skill_system.lifecycle: per-session skill lifecycle 隔离
        #   - skill_system.retriever: turn-start skill candidate 检索
        #   - skill_system.prompt_section: skill selection prompt 注入
        #   - skill_system.loader: skill body 加载（_update_active_skill_from_dispatcher 内 local import）  # noqa: E501
        #   - skill_system.registry: skill 注册表查询（_update_active_skill_from_dispatcher 内 local import）  # noqa: E501
        #   - skill_system.skill_tool: SKILL_SELECT 工具注册（chat() 内 local import）
        #   - action_scheduler: ActionPlan 调度（_dispatch_or_fallback_delegation 内 local import）
        #   - plan_schema: ActionPlan 序列化 schema
        #   - tool_runtime_mediator: 统一 Tool 执行中介（B7 + pre-B7）
        #   - logger: log_event 结构化日志（pre-B7，之前遗漏在 baseline）
        #   - provider.protocol: ProviderError/ProviderResponse 类型（pre-B7，之前遗漏）
        #   - skill_state: 共享 skill 状态标记（B7 Targeted Cleanup: 打破 core↔loop 和 core↔skill_tool 循环）  # noqa: E501
        "agent.action_scheduler",
        "agent.logger",
        "agent.plan_schema",
        "agent.provider.protocol",
        "agent.runtime_decision_frame",
        "agent.runtime_identity",
        "agent.skill_state",
        "agent.skill_system.lifecycle",
        "agent.skill_system.loader",
        "agent.runtime_integration.checkpoint_save",
        "agent.skill_system.prompt_section",
        "agent.skill_system.registry",
        "agent.skill_system.retriever",
        "agent.skill_system.skill_tool",
        "agent.tool_runtime_mediator",
        "agent.transitions",
        # v1.1 Skill tool-scope fix：_call_model() 内 local import，仅用于
        # BASE_TOOLS 合并到 skill visible allowlist。不改变 core 的模块级
        # import surface，不引入新的模块级耦合。
        "agent.tool_scope",
        # Evidence migration: core.py / planner.py / response_handlers.py /
        # tool_executor.py / session.py 均通过 helper 函数在 Runtime branch
        # point 处延迟 import evidence_recorder，实现 dual-write 过渡。
        "agent.evidence_recorder",
    }

    assert _collect_agent_imports(CORE_FILE) == expected


def test_core_top_level_runtime_entrypoints_are_reviewed() -> None:
    """记录 core.py 当前顶层职责入口，避免继续无审查膨胀。

    不用行数阈值作为 pass/fail：core.py 变短或变长都不自动代表好坏。这里
    只钉顶层 class/function surface，后续 helper extraction 如果移动职责，
    必须同步解释哪些入口被移出、哪些仍留在 runtime orchestrator。
    """

    tree = _read_tree(CORE_FILE)
    actual = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    expected = {
        "TurnState",
        "_build_confirmation_context",
        "_build_loop_context",
        "_call_model",
        "_compress_history_and_sync_checkpoint",
        "_dispatch_model_output",
        "_dispatch_pending_confirmation",
        "_extract_text",
        "_handle_planning_phase_result",
        "_is_explicit_l2_trigger",
        # _looks_like_* 检测函数已提取到 agent/cli_commands.py。
        # core.py 通过模块级 import alias 保留向后兼容，
        # 但它们不再是 FunctionDef 节点（只是 import 别名）。
        "_maybe_run_l2_inline",
        # Loop 8: _resolve_provider_evidence_metadata 提取到 agent/provider_evidence.py
        # Loop 8: _execute_subagent_delegation 提取到 agent/subagent_inline.py
        # 两者均通过模块级 import 别名（import ... as _*）保持向后兼容。
        "_run_main_loop",
        "_run_planning_phase",
        "_runtime_loop_fields",
        "_start_planning_for_handler",
        "chat",
        "get_l2_trigger_guard",
        "get_state",
        "refresh_runtime_system_prompt",
        # ── B7 Multi-Instance Readiness helpers ──
        # B7 在 core.py 新增了这些 top-level helpers。每个都是 runtime orchestrator
        # 的编排胶水（orchestration glue），不属于 memory/skill/checkpoint 细节层：
        #   - get_memory_runtime: per-session MemoryRuntime 工厂/查找
        #   - _active_skill_section: 从 lifecycle 获取 active skill body（prompt 注入用）
        #   - _update_active_skill_from_dispatcher: 从 dispatcher action_log 同步 skill 状态
        #   - _dispatch_checkpoint_save: dispatcher 中介的 checkpoint 保存（产生 evidence）
        #   - _dispatch_skill_selection_entered: turn-start skill selection 进入 evidence
        #   - _dispatch_skill_candidates_built: skill candidate 检索结果 evidence
        #   - _dispatch_or_fallback_delegation: SubAgent/Planner 委托/回退路由
        #   - _action_plan_to_dict: ActionPlan → dict 序列化（dispatcher payload 用）
        #   - _render_v0_delegate_result: U3 — V0 success 渲染（V0 result → CLI 形状）
        #   - _runtime_event_not_supported_fallback: U3 — V0 handler-missing 的 display event
        "_action_plan_to_dict",
        "_active_skill_section",
        "_active_skill_memory_scope",
        "_dispatch_checkpoint_save",
        "_dispatch_or_fallback_delegation",
        "_dispatch_skill_candidates_built",
        "_dispatch_skill_selection_entered",
        "_memory_recall_policy_payload",
        "_record_direct_memory_recall_skipped_no_dispatcher",
        "_record_direct_skill_memory_recall_blocked",
        "_runtime_event_not_supported_fallback",
        "_update_active_skill_from_dispatcher",
        "_render_v0_delegate_result",
        "get_memory_runtime",
        # Evidence migration: 模块级 helper，把 Runtime branch point 事件送入
        # 统一 evidence recorder（dual-write：保留 legacy log_event + 新增 record_evidence）。
        "_record_core_evidence",
    }

    assert actual == expected


def test_loop_orchestration_boundary_has_no_ui_or_memory_internals() -> None:
    """agent.loop 只承载主循环编排，不反向理解 UI 或 Memory 内部语义。

    Global architecture debt remediation 把 loop orchestration 从 core.py 抽出，
    但抽文件不是目标；目标是让 loop 成为可注入依赖的编排层。它可以驱动
    checkpoint / model / response dispatch dependency，却不能直接 import UI、
    memory_interaction、memory store 或 CLI/TUI adapter。
    """

    assert LOOP_FILE.exists()
    forbidden = {
        "agent.memory",
        "agent.memory_fs_store",
        "agent.memory_interaction",
        "agent.memory_runtime",
        "agent.cli",
        "agent.input_backends.simple",
        "agent.input_backends.textual",
        "agent.user_input",
    }

    assert _collect_agent_imports(LOOP_FILE) & forbidden == set()


def test_confirmation_package_does_not_import_ui_or_tui_adapters() -> None:
    """confirmation handler 只处理 Runtime 决策，不依赖 CLI/TUI adapter。

    DisplayEvent 是 runtime 到 UI 的数据投影，允许由 confirmation 发出；
    但 confirmation 子包不能直接 import CLI、input backend 或 core 入口，
    否则 handler 会重新变成跨层巨石。
    """

    forbidden = {
        "agent.cli",
        "agent.cli.display",
        "agent.cli.input_backends",
        "agent.core",
        "agent.input_backends",
        "agent.input_backends.simple",
        "agent.input_backends.textual",
        "agent.user_input",
    }
    confirmation_files = tuple((AGENT_DIR / "confirmation").glob("*.py"))

    leaked = {
        _module_name(path): sorted(_collect_agent_imports(path) & forbidden)
        for path in confirmation_files
        if _collect_agent_imports(path) & forbidden
    }

    assert leaked == {}


def test_memory_interaction_does_not_import_core_or_ui_adapters() -> None:
    """memory interaction adapter 不应反向依赖 core/CLI/TUI。

    memory_interaction 可以解析 memory pending request，也可以 lazy 调
    checkpoint 保存确认结果；但它不能 import core 或输入后端来驱动 loop。
    """

    imports = _collect_agent_imports(AGENT_DIR / "memory_interaction.py")
    forbidden = {
        "agent.core",
        "agent.cli",
        "agent.input_backends",
        "agent.input_backends.simple",
        "agent.input_backends.textual",
    }

    assert imports & forbidden == set()


def test_default_tool_entrypoint_does_not_import_skill_or_subagent_prototypes() -> None:
    """默认工具入口不能把 out-of-scope Skill/SubAgent 原型带进模型工具面。

    Skill lifecycle 相关文件未来会重做，本轮不审计它们；这里只保护
    import agent.tools 的默认注册路径仍不加载 agent.skills / agent.subagents。
    """

    imports = _collect_agent_imports(AGENT_DIR / "tools" / "__init__.py")

    assert imports & {"agent.skills", "agent.subagents"} == set()


def test_agent_import_graph_has_no_direct_module_cycles() -> None:
    """钉住当前 agent import graph 没有直接双向依赖。

    本测试只查 A -> B 且 B -> A 的一跳循环，不做完整架构图求解。它的目的
    是防止下一步去巨石化时把 helper 抽到新模块后又反向 import core/handler，
    让“拆分”变成隐形循环依赖。
    """

    modules = {_module_name(path) for path in _agent_python_files()}
    graph = {
        _module_name(path): {
            imported for imported in _collect_agent_imports(path) if imported in modules
        }
        for path in _agent_python_files()
    }

    direct_cycles = sorted(
        (left, right)
        for left, imports in graph.items()
        for right in imports
        if left != right and left in graph.get(right, set())
    )

    assert direct_cycles == []


def test_input_display_boundary_modules_do_not_import_runtime_internals() -> None:
    """input/display/TUI 边界不允许反向 import runtime internals。

    input backend 只收集/封装输入，display event 只投影用户可见输出，
    user_input 只描述 envelope/event。它们不能直接 import core、checkpoint、
    handler 或 executor 来做 runtime decision；否则后续重构会失去层次边界。
    """

    forbidden = {
        "agent.checkpoint",
        "agent.confirm_handlers",
        "agent.confirmation.dispatcher",
        "agent.confirmation.plan",
        "agent.confirmation.tool",
        "agent.confirmation.user_input",
        "agent.core",
        "agent.input_resolution",
        "agent.loop_context",
        "agent.memory",
        "agent.response_handlers",
        "agent.runtime_observer",
        "agent.state",
        "agent.task_runtime",
        "agent.tool_executor",
        "agent.tool_registry",
        "agent.transitions",
    }

    leaked = {
        _module_name(path): sorted(_collect_agent_imports(path) & forbidden)
        for path in INPUT_DISPLAY_BOUNDARY_FILES
        if _collect_agent_imports(path) & forbidden
    }

    assert leaked == {}


def test_input_display_boundary_modules_do_not_call_checkpoint_api() -> None:
    """input/display/TUI 层不能保存或清理 checkpoint。

    checkpoint 是否保存是 runtime transition / handler 的责任；input backend
    如果在读取文本时写 checkpoint，就会把 I/O adapter 变成 runtime owner。
    本测试先锁“这些边界模块没有 checkpoint 调用”，不改变现有 checkpoint 债务。
    """

    boundary_modules = {_module_name(path) for path in INPUT_DISPLAY_BOUNDARY_FILES}
    checkpoint_calls = _checkpoint_call_inventory()
    leaked = {
        (module, function, operation): count
        for (module, function, operation), count in checkpoint_calls.items()
        if module in boundary_modules
    }

    assert leaked == {}


def test_input_display_boundary_modules_do_not_mutate_runtime_state() -> None:
    """input/display/TUI 层不能直接 mutate Runtime state。

    v0.6.2 paste burst fix 的正确边界是：simple backend 保留 multiline raw_text，
    Runtime/handler 再决定如何推进状态。这里用 AST 确认 input/display/user_input
    模块没有 `state.task.* = ...`、`state.reset_task()` 等 runtime mutation。
    """

    boundary_modules = {_module_name(path) for path in INPUT_DISPLAY_BOUNDARY_FILES}
    mutations = {
        item for item in _runtime_state_mutation_inventory() if item[0] in boundary_modules
    }

    assert mutations == set()


_CHECKPOINT_CALL_BASELINE: tuple[tuple[str, str, str, int], ...] = (
    ("agent.checkpoint", "load_checkpoint_to_state", "load_checkpoint", 1),
    ("agent.confirmation.plan", "handle_feedback_intent_choice", "clear_checkpoint", 3),
    ("agent.confirmation.plan", "handle_plan_confirmation", "clear_checkpoint", 1),
    ("agent.confirmation.plan", "handle_step_confirmation", "clear_checkpoint", 2),
    ("agent.confirmation.user_input", "handle_user_input_step", "clear_checkpoint", 1),
    # Global Architecture Debt Remediation：loop guard 的 checkpoint clear
    # 已从 core.py 主循环实现迁到 agent.loop orchestration。
    ("agent.loop", "run_main_loop", "clear_checkpoint", 1),
    ("agent.response_handlers", "_maybe_advance_step", "clear_checkpoint", 1),
    ("agent.response_handlers", "handle_end_turn_response", "clear_checkpoint", 1),
    ("agent.response_handlers", "handle_tool_use_response", "clear_checkpoint", 2),
    ("agent.runtime_integration.checkpoint_resume", "handle", "load_checkpoint_to_state", 1),
    ("agent.runtime_integration.checkpoint_save", "save_runtime_checkpoint", "save_checkpoint", 1),
    # B7: session checkpoint loading 收口到 _load_checkpoint_best_effort /
    # _load_selected_checkpoint_to_state_best_effort 两个 helper（per-session identity 感知）。
    ("agent.session", "_load_checkpoint_best_effort", "load_checkpoint", 2),
    # Gap 4 fix: _load_checkpoint_to_state_best_effort 新增 load_checkpoint()
    # 调用以验证 session-scoped checkpoint 可解析性（P2-2 损坏跳过）和
    # single-file checkpoint 存在性（P2-1 cross-session guard）。
    # U3: state restore 成功后重读同一路径，返回实际恢复的 checkpoint。
    ("agent.session", "_load_selected_checkpoint_to_state_best_effort", "load_checkpoint", 4),
    (
        "agent.session",
        "_load_selected_checkpoint_to_state_best_effort",
        "load_checkpoint_to_state",
        2,
    ),
    ("agent.session", "handle_interrupt_choice", "clear_checkpoint", 1),
    ("agent.session", "handle_resume_choice", "clear_checkpoint", 1),
    ("agent.session", "try_resume_from_checkpoint", "clear_checkpoint", 1),
    ("agent.transitions", "apply_user_replied_transition", "clear_checkpoint", 1),
)


def test_checkpoint_call_inventory_is_explicitly_reviewed() -> None:
    """固化当前 checkpoint save/load/clear ownership inventory。

    这是债务登记，不是本轮修复。当前 checkpoint 调用点分布在 core 周边多个
    handler/executor/session 中；未来要集中 gateway 或调整保存时机时，先让这
    条测试失败，再有意识地更新 baseline，而不是让新 checkpoint 写入点静默扩散。
    """

    actual = tuple(
        sorted(
            (module, function, operation, count)
            for (module, function, operation), count in (
                _checkpoint_call_inventory().items()
            )
        )
    )

    assert actual == _CHECKPOINT_CALL_BASELINE


_RUNTIME_MUTATION_OWNER_BASELINE = {
    "agent.checkpoint",
    "agent.confirmation.dispatcher",
    "agent.confirmation.memory",
    "agent.confirmation.plan",
    "agent.confirmation.tool",
    "agent.confirmation.user_input",
    "agent.core",
    "agent.loop",
    "agent.memory",
    "agent.memory_interaction",
    "agent.response_handlers",
    "agent.session",
    "agent.tool_executor",
    "agent.transitions",
}


def test_runtime_state_mutation_owner_modules_are_reviewed() -> None:
    """固化当前哪些模块允许直接 mutate runtime state。

    现状允许 core/handlers/executor/session/checkpoint/transition/task_runtime
    修改 state；这正是后续去巨石化要治理的债务。本轮不修复，但防止
    input/display/TUI 或其他新模块在没有 review 的情况下加入 mutation owner。
    """

    actual_owners = {module for module, _function, _target in _runtime_state_mutation_inventory()}

    assert actual_owners == _RUNTIME_MUTATION_OWNER_BASELINE


def test_runtime_state_mutation_function_inventory_is_reviewed() -> None:
    """记录当前 mutation function/target inventory，给后续拆分提供安全网。

    这里仍不用行号；如果未来某个 handler 多了新的 `state.task.*` target 或
    新函数开始 reset task，本测试会提示先审视 state transition ownership。
    """

    expected = {
        ("agent.checkpoint", "load_checkpoint_to_state", "setattr(state.memory, ...)"),
        ("agent.checkpoint", "load_checkpoint_to_state", "setattr(state.task, ...)"),
        ("agent.checkpoint", "load_checkpoint_to_state", "state.conversation.messages"),
        (
            "agent.confirmation.dispatcher",
            "_request_feedback_intent_choice",
            "state.task.pending_user_input_request",
        ),
        ("agent.confirmation.plan", "handle_feedback_intent_choice", "state.reset_task()"),
        ("agent.confirmation.plan", "handle_feedback_intent_choice", "state.task.current_plan"),
        (
            "agent.confirmation.plan",
            "handle_feedback_intent_choice",
            "state.task.current_step_index",
        ),
        (
            "agent.confirmation.plan",
            "handle_feedback_intent_choice",
            "state.task.pending_user_input_request",
        ),
        ("agent.confirmation.plan", "handle_plan_confirmation", "state.reset_task()"),
        ("agent.confirmation.plan", "handle_step_confirmation", "state.reset_task()"),
        ("agent.confirmation.tool", "handle_tool_confirmation", "state.task.pending_tool"),
        ("agent.confirmation.user_input", "handle_user_input_step", "state.reset_task()"),
        (
            "agent.memory_interaction",
            "handle_memory_confirmation_reply",
            "state.task.pending_user_input_request",
        ),
        (
            "agent.memory_interaction",
            "_clear_pending_and_save",
            "state.task.pending_user_input_request",
        ),
        (
            "agent.confirmation.memory",
            "_handle_memory_forget_confirmation",
            "state.task.pending_user_input_request",
        ),
        (
            "agent.memory",
            "set_working_summary_scratchpad",
            "state.memory.working_summary",
        ),
        ("agent.loop", "run_main_loop", "state.reset_task()"),
        ("agent.loop", "run_main_loop", "state.task.loop_iterations"),
        ("agent.core", "_run_planning_phase", "state.task.confirm_each_step"),
        ("agent.core", "_run_planning_phase", "state.task.current_plan"),
        ("agent.core", "_run_planning_phase", "state.task.current_step_index"),
        ("agent.core", "_run_planning_phase", "state.task.user_goal"),
        ("agent.core", "_run_planning_phase", "state.reset_task()"),
        (
            "agent.core",
            "_compress_history_and_sync_checkpoint",
            "state.conversation.messages",
        ),
        # Memory Interactive Confirmation v1：chat() CONFIRMATION_REQUIRED 分支
        # transition 后设置 pending_user_input_request。
        ("agent.core", "chat", "state.task.pending_user_input_request"),
        ("agent.core", "chat", "state.reset_task()"),
        ("agent.core", "refresh_runtime_system_prompt", "state.set_system_prompt()"),
        ("agent.response_handlers", "_maybe_advance_step", "state.reset_task()"),
        ("agent.response_handlers", "handle_end_turn_response", "state.reset_task()"),
        (
            "agent.response_handlers",
            "handle_end_turn_response",
            "state.task.consecutive_end_turn_without_progress",
        ),
        (
            "agent.response_handlers",
            "handle_end_turn_response",
            "state.task.consecutive_max_tokens",
        ),
        (
            "agent.response_handlers",
            "handle_end_turn_response",
            "state.task.pending_user_input_request",
        ),
        (
            "agent.response_handlers",
            "handle_max_tokens_response",
            "state.task.consecutive_max_tokens",
        ),
        ("agent.response_handlers", "handle_tool_use_response", "state.reset_task()"),
        (
            "agent.response_handlers",
            "handle_tool_use_response",
            "state.task.consecutive_end_turn_without_progress",
        ),
        (
            "agent.response_handlers",
            "handle_tool_use_response",
            "state.task.consecutive_max_tokens",
        ),
        ("agent.response_handlers", "handle_tool_use_response", "state.task.tool_call_count"),
        # UMT-P2-001: FORCE_STOP 不终止循环，写入 tool_execution_log 传递拒绝原因给模型
        (
            "agent.response_handlers",
            "handle_tool_use_response",
            "state.task.tool_execution_log",
        ),
        ("agent.session", "handle_interrupt_choice", "state.reset_task()"),
        ("agent.session", "handle_interrupt_choice", "state.task.status"),
        ("agent.session", "handle_interrupt_with_checkpoint", "state.task.status"),
        ("agent.tool_executor", "execute_single_tool", "state.task.pending_tool"),
        (
            "agent.tool_executor",
            "execute_single_tool",
            "state.task.pending_user_input_request",
        ),
        ("agent.tool_executor", "execute_single_tool", "state.task.tool_execution_log"),
        ("agent.tool_executor", "execute_pending_tool", "state.task.tool_execution_log"),
        (
            "agent.transitions",
            "advance_current_step_if_needed",
            "state.task.current_step_index",
        ),
        ("agent.transitions", "apply_task_transition", "state.task.status"),
        ("agent.transitions", "apply_user_replied_transition", "state.reset_task()"),
        (
            "agent.transitions",
            "apply_user_replied_transition",
            "state.task.pending_user_input_request",
        ),
    }

    assert _runtime_state_mutation_inventory() == expected


_SENSITIVE_LITERAL_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\.env\b", ".env"),
    (r"agent_log\.jsonl\b", "agent_log.jsonl"),
    (r"(?<![A-Za-z_])sessions/", "sessions/"),
    (r"(?<![A-Za-z_])runs/", "runs/"),
)


def test_input_display_boundary_source_does_not_reference_sensitive_paths() -> None:
    """input/display/TUI 源码不应硬编码敏感文件/目录路径。

    本测试只扫描 production source literal，不打开真实敏感文件。它防的是后续
    TUI/display/input 层为了“方便展示最近日志/会话”直接读取持久层，绕过 runtime
    和安全边界。
    """

    hits: dict[str, list[str]] = {}
    for path in INPUT_DISPLAY_BOUNDARY_FILES:
        source = path.read_text(encoding="utf-8")
        labels = [
            label
            for pattern, label in _SENSITIVE_LITERAL_PATTERNS
            if re.search(pattern, source)
        ]
        if labels:
            hits[_module_name(path)] = labels

    assert hits == {}


def test_subagent_system_preserves_parent_governance_boundaries() -> None:
    """formal SubAgent modules 不能导入会绕过 parent/runtime/governance 的层。

    这是 Phase 19 audit-readiness safety net：SubAgent System 可以定义
    contracts/boundaries/adapter，但不能直接接管 ToolExecutor、MemoryStore、
    provider、shell 或 legacy Safe Local MVP。
    """

    forbidden_imports = {
        "agent.core",
        "agent.loop",
        "agent.tool_executor",
        "agent.memory_store",
        "agent.memory_fs_store",
        "agent.provider.factory",
        "agent.subagents.local",
        "subprocess",
        "socket",
        "requests",
    }
    hits: dict[str, set[str]] = {}
    for path in sorted(SUBAGENT_SYSTEM_DIR.glob("*.py")):
        imports = _collect_imports(path) & forbidden_imports
        if imports:
            hits[_module_name(path)] = imports

    assert hits == {}


def test_subagent_system_does_not_create_future_modules_by_default() -> None:
    """L1+ context_window / L3 sandbox future modules 不应在 L0 loop 预创建。"""

    assert not (SUBAGENT_SYSTEM_DIR / "context_window.py").exists()
    assert not (SUBAGENT_SYSTEM_DIR / "sandbox.py").exists()


def test_subagent_system_public_api_is_explicit_and_side_effect_free() -> None:
    """package import 只能暴露稳定 contract，不触发 real LLM/shell 等 gated side effect。"""

    import agent.subagent_system as subagent_system

    public = set(subagent_system.__all__)

    assert public == {
        "SubAgentAuditRecord",
        "SubAgentContextPackage",
        "SubAgentDescriptor",
        "SubAgentError",
        "SubAgentExecutionMode",
        "SubAgentPolicy",
        "SubAgentRequest",
        "SubAgentResult",
        "SubAgentStopReason",
    }
    assert "sandbox" not in public
    assert "worktree" not in public
    assert "parallel" not in public

    namespace: dict[str, object] = {}
    exec("from agent.subagent_system import *", namespace)
    assert public.issubset(namespace)
    assert "delegate_once" not in namespace


def test_cli_subagent_delegation_uses_registry_and_delegate_once() -> None:
    """Loop 9: CLI delegation shortcut 必须通过 SubAgentRegistry + delegate_once 执行。

    P2-5 审计发现：CLI delegation shortcuts（detect_delegate_to_subagent、
    detect_nl_delegation）在 core.py 的 main loop 前直接执行委托，绕过
    RuntimeActionDispatcher。但这不代表它们绕过 SubAgent 系统本身——
    _execute_subagent_delegation() 仍然通过 SubAgentRegistry 查找 descriptor、
    通过 delegate_once() 执行委托。

    本测试验证：agent/subagent_inline.py 不导入 executor/直接执行路径
    （如 execute_local），所有委托必须经过 registry + delegate_once 边界。
    """
    import ast
    from pathlib import Path

    inline_path = Path("agent/subagent_inline.py")
    source = inline_path.read_text()
    tree = ast.parse(source)

    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                imports.add(f"{module}.{alias.name}")

    assert "agent.subagent_system.registry" in imports or any(
        "SubAgentRegistry" in i for i in imports
    ), "CLI delegation must import SubAgentRegistry"
    assert "agent.subagent_system.delegation" in imports or any(
        "delegate_once" in i for i in imports
    ), "CLI delegation must import delegate_once"
    assert "agent.subagent_system.executor" not in imports, (
        "CLI delegation must NOT import executor directly — use delegate_once()"
    )


def test_skill_system_does_not_import_legacy_skills() -> None:
    """Loop 11: skill_system 不能反向依赖 legacy_skills。

    P3-2 审计发现：legacy_skills 和 skill_system 两套体系并存。
    skill_system 是新架构，legacy_skills 是隔离历史材料。
    skill_system 的模块不应导入 legacy_skills——否则隔离失效。
    """
    import ast

    skill_system_dir = AGENT_DIR / "skill_system"
    forbidden = {"agent.legacy_skills", "agent.skills"}
    violations: dict[str, set[str]] = {}

    for path in sorted(skill_system_dir.glob("*.py")):
        tree = ast.parse(path.read_text())
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    imports.add(f"{module}.{alias.name}")
        hits = imports & forbidden
        if hits:
            violations[path.name] = hits

    assert violations == {}, (
        f"skill_system modules must not import legacy_skills: {violations}"
    )


def test_skill_runtime_handler_integration_is_wired() -> None:
    """Loop 11: SKILL_SELECT handler 在 phase1_hook 中正确注册。

    验证 SkillRuntimeActionHandler 的注册路径完整：
    phase1_hook 注册 SKILL_SELECT → SkillRuntimeActionHandler。
    """
    from agent.runtime_integration.phase1_hook import build_phase1_dispatcher

    dispatcher = build_phase1_dispatcher()
    assert dispatcher is not None

    # SKILL_SELECT 在 dispatcher 的 action registry 中
    import inspect
    source = inspect.getsource(build_phase1_dispatcher)
    assert "SKILL_SELECT" in source
    assert "SkillRuntimeActionHandler" in source


# ============================================================================
# Loop 10: MCP boundary hardening (P2)
# ============================================================================


def test_mcp_modules_do_not_import_runtime_core() -> None:
    """Loop 10: MCP 模块不能导入 runtime 核心模块。

    MCP 系统是独立的架构 seam：policy/sanitizer/audit/bridge/stdio
    都不能导入 core.py / loop.py / tool_executor.py / checkpoint.py。
    这确保 MCP tool 注册流程不会绕过 runtime governance。
    """
    import ast

    mcp_modules = [
        "agent/mcp.py",
        "agent/mcp_models.py",
        "agent/mcp_policy.py",
        "agent/mcp_sanitizer.py",
        "agent/mcp_audit.py",
        "agent/mcp_bridge.py",
        "agent/mcp_stdio.py",
    ]
    forbidden = {
        "agent.core",
        "agent.loop",
        "agent.tool_executor",
        "agent.checkpoint",
    }
    violations: dict[str, set[str]] = {}

    for mod_path in mcp_modules:
        path = PROJECT_ROOT / mod_path
        if not path.exists():
            continue
        tree = ast.parse(path.read_text())
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                imports.add(module)
                for alias in node.names:
                    if module:
                        imports.add(f"{module}.{alias.name}")
        hits = imports & forbidden
        if hits:
            violations[mod_path] = hits

    assert violations == {}, (
        f"MCP modules must not import runtime core: {violations}"
    )


def test_register_mcp_tools_is_only_registry_mutation_point() -> None:
    """Loop 10: register_mcp_tools 是 MCP 连接 tool_registry 的唯一入口。

    验证：只有 agent/mcp.py 的 register_mcp_tools() 函数调用
    TOOL_REGISTRY 的修改操作（register_tool）。
    其他 MCP 模块（policy/sanitizer/audit/bridge/stdio）不应直接
    注册工具到 TOOL_REGISTRY。

    mcp_policy.py 可以只读引用 TOOL_REGISTRY（用于名称冲突检测），
    但不应调用 register_tool / TOOL_REGISTRY.register / TOOL_REGISTRY.update。
    """
    registry_mutators = {
        "register_tool",
        "TOOL_REGISTRY.register",
        "TOOL_REGISTRY.update",
        "TOOL_REGISTRY.__setitem__",
    }

    mcp_modules = {
        "agent/mcp_policy.py",
        "agent/mcp_sanitizer.py",
        "agent/mcp_audit.py",
        "agent/mcp_bridge.py",
        "agent/mcp_stdio.py",
        "agent/mcp_models.py",
    }
    violations: dict[str, set[str]] = {}

    for mod_path in mcp_modules:
        path = PROJECT_ROOT / mod_path
        if not path.exists():
            continue
        source = path.read_text()
        hits = set()
        for mutator in registry_mutators:
            if mutator in source:
                hits.add(mutator)
        if hits:
            violations[mod_path] = hits

    assert violations == {}, (
        f"Only agent/mcp.py may mutate TOOL_REGISTRY. Violations: {violations}"
    )


def test_mediator_route_invoke_does_not_dispatch_tool_invoke() -> None:
    """ToolRuntimeMediator._route_invoke 不通过 dispatcher dispatch TOOL_INVOKE。

    P1-2 冲突复核关键修复：_route_invoke 改用 record_evidence 直接记录
    invoke_started evidence，不再调用 dispatcher.route / route_from_runtime_loop
    触发 ToolInvokeHandler → execute_tool() 双重执行路径。

    此测试用源码检查钉死该架构边界。如果未来有人在 _route_invoke 中重新
    加入 dispatcher route TOOL_INVOKE 调用，此测试必须失败。
    """
    mediator_path = PROJECT_ROOT / "agent" / "tool_runtime_mediator.py"
    source = mediator_path.read_text()

    # 提取 _route_invoke 方法体（从 def 行到下一个同缩进级别的 def / class）
    import re
    _invoke_re = (
        r'def _route_invoke\(.*?\n(.*?)(?=\n    def |\n    @|\nclass |\Z)'
    )
    match = re.search(_invoke_re, source, re.DOTALL)
    assert match is not None, "找不到 _route_invoke 方法"
    method_body = match.group(0)

    # 禁止在 _route_invoke 中通过 dispatcher 路由 TOOL_INVOKE
    _forbidden_route = "dispatcher.route(RuntimeActionRequest"
    _forbidden_route_loop = (
        "dispatcher.route_from_runtime_loop(RuntimeActionRequest"
    )
    forbidden_patterns = [
        (_forbidden_route, "dispatcher.route() 调用"),
        (_forbidden_route_loop, "dispatcher.route_from_runtime_loop() 调用"),
    ]
    for pattern, desc in forbidden_patterns:
        assert pattern not in method_body, (
            f"_route_invoke 禁止 {desc}——必须只使用 record_evidence 直接记录 evidence，"
            f"不得通过 dispatcher 触发 ToolInvokeHandler 工具执行"
        )

    # 必须包含 record_evidence 调用
    assert "record_evidence" in method_body, (
        "_route_invoke 必须调用 record_evidence 记录 invoke_started evidence"
    )


def test_dispatcher_tool_invoke_is_evidence_only_and_does_not_execute_tool(
    monkeypatch,
) -> None:
    """直接 dispatch TOOL_INVOKE 也不能执行工具。

    架构边界：TOOL_INVOKE 现在只表达 invoke_started evidence。真实工具执行
    只能发生在 ToolRuntimeMediator → tool_executor 路径；即使未来有旧路径误把
    TOOL_INVOKE dispatch 到 ToolInvokeHandler，也不能绕过 mediator 执行工具。
    """
    from agent.runtime_integration import (
        ActionHandlerRegistry,
        RuntimeActionDispatcher,
        RuntimeActionRequest,
        RuntimeActionType,
    )
    from agent.runtime_integration.evidence import RuntimeActionModuleObserver
    from agent.runtime_integration.tool_invoke import ToolInvokeHandler
    from agent.tool_registry import TOOL_REGISTRY, register_tool

    tool_name = "_architecture_boundary_no_execute"
    TOOL_REGISTRY.pop(tool_name, None)
    @register_tool(
        name=tool_name,
        description="architecture boundary fixture",
        parameters={"type": "object", "properties": {}},
        risk_level="medium",
        confirmation="never",
    )
    def _should_not_run():
        return "should not run"

    execute_calls: list[tuple[tuple, dict]] = []

    def _fail_if_executed(*args, **kwargs):
        execute_calls.append((args, kwargs))
        raise AssertionError("TOOL_INVOKE dispatcher path must not execute tools")

    monkeypatch.setattr("agent.tool_registry.execute_tool", _fail_if_executed)

    try:
        registry = ActionHandlerRegistry()
        registry.register(RuntimeActionType.TOOL_INVOKE, ToolInvokeHandler())
        dispatcher = RuntimeActionDispatcher(
            registry=registry,
            observer=RuntimeActionModuleObserver(),
        )

        result = dispatcher.route(RuntimeActionRequest(
            action_type=RuntimeActionType.TOOL_INVOKE,
            source="architecture_boundary_test",
            parent_trace_id="trace:architecture-boundary",
            payload={"tool_name": tool_name, "tool_input": {}},
        ))

        assert execute_calls == []
        assert result.payload["tool_invoked"] is False
        assert result.payload["execution_status"] == "not_executed"
    finally:
        TOOL_REGISTRY.pop(tool_name, None)


# ── MCP Boundary Hardening Phase 1: harness-only boundary ──


def test_run_mcp_tool_pipeline_is_harness_only() -> None:
    """run_mcp_tool_pipeline 是 harness-only，生产代码不得引用。

    mcp_tool_orchestrator.py 自身和 tests/ 下的文件可以引用。
    agent/ 下其他模块（包括 mcp.py/mcp_bridge.py/mcp_audit.py 等）
    不得 import 或调用 run_mcp_tool_pipeline。

    生产 MCP 工具执行路径：
    Agent Loop → ToolRuntimeMediator → tool_executor → registered MCP tool closure
    """
    import ast

    agent_root = PROJECT_ROOT / "agent"
    allowed_modules = {
        "agent/runtime_integration/mcp_tool_orchestrator.py",
    }

    violations: dict[str, set[str]] = {}

    for py_file in agent_root.rglob("*.py"):
        rel = str(py_file.relative_to(PROJECT_ROOT))
        if rel in allowed_modules:
            continue

        source = py_file.read_text()
        tree = ast.parse(source)

        found: set[str] = set()
        for node in ast.walk(tree):
            # bare import of mcp_tool_orchestrator
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if "mcp_tool_orchestrator" in alias.name:
                        found.add(f"bare import {alias.name}")
            # import from mcp_tool_orchestrator
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if "mcp_tool_orchestrator" in module:
                    for alias in node.names:
                        found.add(f"import {alias.name} from {module}")
            # call to run_mcp_tool_pipeline (name reference)
            elif isinstance(node, ast.Name):
                if node.id == "run_mcp_tool_pipeline":
                    found.add("call run_mcp_tool_pipeline")
            # attribute access
            elif (
                isinstance(node, ast.Attribute)
                and node.attr == "run_mcp_tool_pipeline"
            ):
                found.add("attribute: run_mcp_tool_pipeline")

        if found:
            violations[rel] = found

    assert violations == {}, (
        f"run_mcp_tool_pipeline is harness-only. "
        f"Production code must not reference it. Violations: {violations}"
    )


# ============================================================================
# Phase 1A: Direct Status Mutation Baseline
# ============================================================================
#
# 扫描范围说明：
# 本测试只检测 agent/ 下 `state.task.status = ...` 形式的直接赋值
# （包括 assign / setattr / 简单 alias）。以下模式不在 Phase 1A 扫描范围内，
# 因为在当前代码中它们不经过模块级 `state` 引用：
#   - self.task.status = ...（如 AgentState.reset_task，self 非 state 引用）
#   - self._state.task.status = ...（如 ToolRuntimeMediator）
#   - get_state().task.status = ...（如 session.py 部分路径）
# 这些写入点已在 §B baseline 中以注释形式登记，后续 Phase 扩展扫描范围时覆盖。


def _build_parent_map(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    return parents


def _enclosing_scope_opt(tree: ast.AST, target: ast.AST,
                         parents: dict[ast.AST, ast.AST]) -> str:
    """优化版 enclosing scope：使用预建的 parent_map。"""
    current = target
    while current in parents:
        current = parents[current]
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current.name
        if isinstance(current, ast.ClassDef):
            return f"{current.name}.<class>"
    return "<module>"


def _status_value_expr_opt(node: ast.AST) -> str:
    """归一化 status 值。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        if node.id == "origin_status":
            return "<origin_status>"
        return "<variable>"
    if isinstance(node, ast.Attribute):
        return "<variable>"
    return "<variable>"


def _scan_tree_mutations(
    tree: ast.Module, file_rel: str,
) -> list[dict[str, object]]:
    """扫描单个 AST 树中的 task.status 裸写点。

    Phase 4 扩展覆盖范围：
    - state.task.status = ...
    - self.task.status = ...
    - self._state.task.status = ...
    - get_state().task.status = ...
    - 简单 alias: task = state.task; task.status = ...
    - setattr(state.task, "status", ...)
    """
    mutations: list[dict[str, object]] = []
    parents = _build_parent_map(tree)

    # 收集 alias: task = state.task
    # Phase 1A alias 支持范围：函数作用域内简单变量别名
    alias_map: dict[tuple[str, str], str] = {}
    for node in ast.walk(tree):
        function = _enclosing_scope_opt(tree, node, parents)
        if isinstance(node, ast.Assign):
            val_name = _qualified_name(node.value)
            if val_name == "state.task":
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        alias_map[(function, target.id)] = target.id

    # Phase 4: 匹配 .task.status 写入的各种 receiver 模式
    task_status_receivers = {
        "state.task.status",
        "self.task.status",
        "self._state.task.status",
    }

    def _is_get_state_call_task_status(target: ast.AST) -> bool:
        """检测 get_state().task.status = ... 模式。"""
        if not (isinstance(target, ast.Attribute) and target.attr == "status"):
            return False
        mid = target.value
        if not (isinstance(mid, ast.Attribute) and mid.attr == "task"):
            return False
        call = mid.value
        if isinstance(call, ast.Call):
            fn = _qualified_name(call.func)
            return fn in {"get_state", "self.get_state"}
        return False

    for node in ast.walk(tree):
        function = _enclosing_scope_opt(tree, node, parents)

        # setattr(state.task, "status", ...)
        if isinstance(node, ast.Call):
            func_name = _qualified_name(node.func)
            if func_name == "setattr" and len(node.args) >= 2:
                arg0_name = _qualified_name(node.args[0])
                if arg0_name == "state.task" and (
                    isinstance(node.args[1], ast.Constant)
                    and node.args[1].value == "status"
                ):
                        mutations.append({
                            "file": file_rel,
                            "function": function,
                            "mutation_kind": "setattr",
                            "target_shape": "state.task.status",
                            "status_value": "<variable>",
                            "lineno": node.lineno,
                        })

        # direct assignment patterns
        if isinstance(node, ast.Assign):
            for target in node.targets:
                name = _qualified_name(target)
                shape = None

                # state.task.status / self.task.status / self._state.task.status
                if name and name in task_status_receivers:
                    shape = name

                # get_state().task.status = ...
                elif _is_get_state_call_task_status(target):
                    shape = "get_state().task.status"

                # alias: task.status = ...
                elif (isinstance(target, ast.Attribute)
                      and target.attr == "status"
                      and isinstance(target.value, ast.Name)):
                    alias_key = (function, target.value.id)
                    if alias_key in alias_map:
                        shape = "state.task.status"

                if shape is None:
                    continue
                status_val = _status_value_expr_opt(node.value)
                mutations.append({
                    "file": file_rel,
                    "function": function,
                    "mutation_kind": "assign",
                    "target_shape": shape,
                    "status_value": status_val,
                    "lineno": node.lineno,
                })

    return mutations


def _collect_direct_status_mutations() -> list[dict[str, object]]:
    """收集 agent/ 下所有 task.status 裸写点。

    Phase 4 检测模式：
    - state.task.status = "..." (ast.Assign)
    - self.task.status = "..." (ast.Assign)
    - self._state.task.status = "..." (ast.Assign)
    - get_state().task.status = "..." (ast.Assign + Call receiver)
    - state.task.status = variable (Name/Attribute rhs)
    - setattr(state.task, "status", ...) (ast.Call)
    - 简单 alias: task = state.task; task.status = "..." (Phase 1A 限定深度)

    返回 list[dict]，每项 file/function/mutation_kind/target_shape/
    status_value/lineno（行号仅用于错误报告）。
    """
    mutations: list[dict[str, object]] = []
    for path in _agent_python_files():
        tree = _read_tree(path)
        file_rel = str(path.relative_to(PROJECT_ROOT))
        mutations.extend(_scan_tree_mutations(tree, file_rel))
    return mutations


def _aggregate_mutations(
    mutations: list[dict[str, object]],
) -> dict[tuple[str, str, str, str, str], int]:
    """聚合 -> (file, function, kind, shape, value) 计数。行号不参与 key。"""
    from collections import Counter
    keys = [
        (
            str(m["file"]), str(m["function"]),
            str(m["mutation_kind"]), str(m["target_shape"]),
            str(m["status_value"]),
        )
        for m in mutations
    ]
    return dict(Counter(keys))


# Phase 4 final legal writer baseline。
#
# Key: (file, function, mutation_kind, target_shape, status_value)
# 行号仅用于错误报告。
#
# Phase 4 scanner 现在覆盖所有写入模式：
#   - state.task.status = ...
#   - self.task.status = ...
#   - self._state.task.status = ...
#   - get_state().task.status = ...
#   - alias: task = state.task; task.status = ...
#   - setattr(state.task, "status", ...)
#
# Final legal writers (8 total):
#   1. apply_task_transition — transition layer 唯一合法新增写入点
#   2. AgentState.reset_task — special factory reset (self.task.status)
#   3-8. session.py W18-W23 — session-only transient writes，不进入 task table
#
# Session transient contract:
#   - awaiting_resume_choice / awaiting_interrupt_choice 不持久化到 checkpoint
#   - 它们是 CLI session routing 内存态，不参与 plan/step/tool task transition
#   - handle_resume_choice / handle_interrupt_choice 的 idle/running 恢复是
#     session lifecycle 行为，不是普通 task transition

_DIRECT_STATUS_MUTATION_BASELINE: dict[tuple[str, str, str, str, str], int] = {
    # ── 1. transition layer 内部（唯一合法新增写入点）──
    ("agent/transitions.py", "apply_task_transition", "assign",
     "state.task.status", "<variable>"): 1,
    # ── 2. special factory reset ──
    ("agent/state.py", "reset_task", "assign",
     "self.task.status", "idle"): 1,
    # ── 3-8. session-only transient writes (W18-W23) ──
    # W23: try_resume_from_checkpoint — TTY 模式设 transient awaiting
    ("agent/session.py", "try_resume_from_checkpoint", "assign",
     "get_state().task.status", "awaiting_resume_choice"): 1,
    # W18: handle_interrupt_with_checkpoint — 保存后设 transient
    ("agent/session.py", "handle_interrupt_with_checkpoint", "assign",
     "state.task.status", "awaiting_interrupt_choice"): 1,
    # W19: handle_resume_choice — no-resume 回到 idle
    ("agent/session.py", "handle_resume_choice", "assign",
     "get_state().task.status", "idle"): 2,
    # W21: handle_interrupt_choice — 继续当前任务
    ("agent/session.py", "handle_interrupt_choice", "assign",
     "state.task.status", "running"): 1,
    # W22: handle_interrupt_choice — invalid/fallback 回到 idle
    ("agent/session.py", "handle_interrupt_choice", "assign",
     "state.task.status", "idle"): 1,
}

# apply_task_transition 是唯一合法新增写入点，已在 baseline 中以 count=1 登记。
# 同函数内新增第二个 state.task.status 写入将触发 count mismatch。


def test_direct_status_mutation_baseline() -> None:
    """Phase 4: final legal writer 双向 equality baseline。

    - baseline 匹配不依赖行号
    - 行号仅用于错误报告
    - Phase 4 scanner 覆盖全部写入模式
    - Final 8 legal writers: transition entry (1) + reset_task (1) + session-only (6)
    - 双向检测: unexpected actual + missing expected 同时发现
    """
    mutations = _collect_direct_status_mutations()
    actual = _aggregate_mutations(mutations)

    new_mutations: list[str] = []
    count_mismatches: list[str] = []

    for key, count in sorted(actual.items()):
        file, function, kind, shape, value = key
        expected_count = _DIRECT_STATUS_MUTATION_BASELINE.get(key)

        if expected_count is None:
            line_infos = [
                f"  line {m['lineno']}"
                for m in mutations
                if (m["file"] == file and m["function"] == function
                    and m["mutation_kind"] == kind and m["target_shape"] == shape
                    and str(m["status_value"]) == value)
            ]
            new_detail = (
                f"NEW: ({file}, {function}, {kind}, {shape}, {value!r}) "
                f"count={count}"
            )
            if line_infos:
                new_detail += "\n" + "\n".join(line_infos)
            new_mutations.append(new_detail)
        elif expected_count != count:
            line_infos = [
                f"  line {m['lineno']}"
                for m in mutations
                if (m["file"] == file and m["function"] == function
                    and m["mutation_kind"] == kind and m["target_shape"] == shape
                    and str(m["status_value"]) == value)
            ]
            detail = (
                f"COUNT MISMATCH: ({file}, {function}, {kind}, {shape}, {value!r}) "
                f"expected={expected_count}, actual={count}"
            )
            if line_infos:
                detail += "\n" + "\n".join(line_infos)
            count_mismatches.append(detail)

    errors: list[str] = []
    if new_mutations:
        errors.append(
            f"NEW direct status mutations detected ({len(new_mutations)}):\n"
            + "\n".join(f"  - {n}" for n in new_mutations)
            + "\n\nUse apply_task_transition() instead."
        )
    if count_mismatches:
        errors.append(
            f"COUNT MISMATCHES ({len(count_mismatches)}):\n"
            + "\n".join(f"  - {c}" for c in count_mismatches)
        )

    # Phase 4 双向检测: expected 中有但 actual 中缺失的 entry
    missing_expected = [
        f"MISSING: {key!r} expected_count={count}"
        for key, count in sorted(_DIRECT_STATUS_MUTATION_BASELINE.items())
        if key not in actual
    ]
    if missing_expected:
        errors.append(
            f"MISSING expected entries ({len(missing_expected)}):\n"
            + "\n".join(f"  - {m}" for m in missing_expected)
            + "\n\nBaseline expects writes that no longer exist in code."
        )

    if errors:
        raise AssertionError("\n\n".join(errors))


def test_phase2_transition_rules_have_real_callsite_usage_inventory() -> None:
    """Phase 2 五条规则必须由真实 handler path 使用。"""

    expected = {
        (
            "agent.transitions",
            "apply_user_replied_transition",
            "USER_INPUT_RESOLVED",
            "awaiting_user_input",
            "transitions.runtime_user_input_answer",
        ),
        (
            "agent.transitions",
            "apply_user_replied_transition",
            "STEP_CONFIRMATION_REQUIRED",
            "awaiting_user_input",
            "transitions.collect_input_answer",
        ),
        (
            "agent.response_handlers",
            "_maybe_advance_step",
            "STEP_CONFIRMATION_REQUIRED",
            "running",
            "response_handlers.maybe_advance_step",
        ),
        (
            "agent.response_handlers",
            "handle_end_turn_response",
            "USER_INPUT_REQUIRED",
            "running",
            "response_handlers.collect_input_required",
        ),
        (
            "agent.response_handlers",
            "handle_end_turn_response",
            "USER_INPUT_REQUIRED",
            "running",
            "response_handlers.end_turn_user_input_required",
        ),
        (
            "agent.tool_executor",
            "execute_single_tool",
            "USER_INPUT_REQUIRED",
            "running",
            "agent.tool_executor.execute_single_tool.request_user_input",
        ),
        (
            "agent.tool_executor",
            "execute_single_tool",
            "USER_INPUT_REQUIRED",
            "idle",
            "agent.tool_executor.execute_single_tool.request_user_input",
        ),
    }

    assert _phase2_transition_request_inventory() == expected


def test_phase3_transition_rules_have_real_callsite_usage_inventory() -> None:
    """Phase 3 十二条规则均登记真实 request/helper caller，不借 exactness 代替。"""
    direct_requests = {
        (
            "agent.core",
            "chat",
            "MEMORY_CONFIRMATION_REQUIRED",
            "<dynamic>",
            "core.chat.memory_confirmation",
        ),
        (
            "agent.core",
            "_run_planning_phase",
            "PLAN_GENERATED",
            "idle",
            "core.run_planning_phase.action_plan",
        ),
        (
            "agent.core",
            "_run_planning_phase",
            "PLAN_GENERATED",
            "idle",
            "core.run_planning_phase.legacy_plan",
        ),
        (
            "agent.memory_interaction",
            "handle_memory_confirmation_reply",
            "MEMORY_CONFIRMATION_RESOLVED",
            "awaiting_user_input",
            "memory_interaction.resolve_confirmation",
        ),
        (
            "agent.memory_interaction",
            "handle_inline_confirmation_reply",
            "MEMORY_CONFIRMATION_RESOLVED",
            "awaiting_user_input",
            "memory_interaction.inline_confirmation",
        ),
        (
            "agent.tool_executor",
            "execute_single_tool",
            "TOOL_CONFIRMATION_REQUIRED",
            "idle",
            "agent.tool_executor.execute_single_tool.tool_confirmation",
        ),
        (
            "agent.tool_executor",
            "execute_single_tool",
            "TOOL_CONFIRMATION_REQUIRED",
            "running",
            "agent.tool_executor.execute_single_tool.tool_confirmation",
        ),
        (
            "agent.tool_runtime_mediator",
            "_handle_confirmation_required",
            "TOOL_CONFIRMATION_REQUIRED",
            "idle",
            "tool_runtime_mediator.handle_confirmation_required",
        ),
        (
            "agent.tool_runtime_mediator",
            "_handle_confirmation_required",
            "TOOL_CONFIRMATION_REQUIRED",
            "running",
            "tool_runtime_mediator.handle_confirmation_required",
        ),
        (
            "agent.tool_runtime_mediator",
            "_set_memory_confirmation_pending",
            "MEMORY_CONFIRMATION_REQUIRED",
            "<dynamic>",
            "<dynamic>",
        ),
        (
            "agent.tool_runtime_mediator",
            "_set_memory_forget_pending",
            "MEMORY_CONFIRMATION_REQUIRED",
            "<dynamic>",
            "tool_runtime_mediator.memory_forget_request",
        ),
        (
            "agent.transitions",
            "advance_current_step_if_needed",
            "<dynamic>",
            "<dynamic>",
            "<dynamic>",
        ),
    }
    step_callers = {
        (
            "agent.transitions",
            "apply_user_replied_transition",
            "transitions.collect_input_answer",
        ),
        (
            "agent.confirmation.plan",
            "handle_step_confirmation",
            "confirmation.plan.step_accept",
        ),
        (
            "agent.response_handlers",
            "_maybe_advance_step",
            "response_handlers.maybe_advance_step",
        ),
    }

    assert _phase3_transition_request_inventory() == direct_requests
    assert _phase3_step_advance_caller_inventory() == step_callers

    # 显式 rule-to-caller inventory：shared rules 列出所有真实 caller。
    rule_callers = {
        ("idle", "MEMORY_CONFIRMATION_REQUIRED"): {"agent.core.chat"},
        ("running", "MEMORY_CONFIRMATION_REQUIRED"): {"agent.core.chat"},
        ("awaiting_user_input", "MEMORY_CONFIRMATION_RESOLVED"): {
            "agent.memory_interaction.handle_memory_confirmation_reply",
            "agent.memory_interaction.handle_inline_confirmation_reply",
        },
        ("running", "STEP_ADVANCED"): {"agent.response_handlers._maybe_advance_step"},
        ("running", "TASK_COMPLETED"): {"agent.response_handlers._maybe_advance_step"},
        ("awaiting_user_input", "STEP_ADVANCED"): {
            "agent.transitions.apply_user_replied_transition"
        },
        ("awaiting_user_input", "TASK_COMPLETED"): {
            "agent.transitions.apply_user_replied_transition"
        },
        ("awaiting_step_confirmation", "STEP_ADVANCED"): {
            "agent.confirmation.plan.handle_step_confirmation"
        },
        ("awaiting_step_confirmation", "TASK_COMPLETED"): {
            "agent.confirmation.plan.handle_step_confirmation"
        },
        ("idle", "PLAN_GENERATED"): {"agent.core._run_planning_phase"},
        ("idle", "TOOL_CONFIRMATION_REQUIRED"): {
            "agent.tool_executor.execute_single_tool",
            "agent.tool_runtime_mediator._handle_confirmation_required",
        },
        ("running", "TOOL_CONFIRMATION_REQUIRED"): {
            "agent.tool_executor.execute_single_tool",
            "agent.tool_runtime_mediator._handle_confirmation_required",
        },
    }
    assert len(rule_callers) == 12
    assert all(rule_callers.values())

    from agent.transitions import _TRANSITION_TABLE

    phase3_rule_keys = {
        (from_status, event.name)
        for from_status, event in _TRANSITION_TABLE
        if (from_status, event.name) in rule_callers
    }
    assert phase3_rule_keys == set(rule_callers)


def test_alias_detection_positive_fixture() -> None:
    """合成 AST 验证 alias 检测能识别 task = state.task; task.status = ...

    Phase 1A alias_map 使用 (function, var_name) 字符串 key。
    当前 agent 源码没有 task = state.task 模式，因此 baseline
    从未正向执行 alias 识别逻辑。此测试用合成 AST 钉死：
    - 即使以后 alias_map 退化回 AST 节点对象 key，此测试仍会失败。
    """
    src = textwrap.dedent("""\
    def handle_something():
        task = state.task
        task.status = "running"
    """)
    tree = ast.parse(src)
    mutations = _scan_tree_mutations(tree, "test/fixture.py")

    assert len(mutations) == 1, (
        f"expected 1 alias mutation, got {len(mutations)}: {mutations}"
    )
    m = mutations[0]
    assert m["target_shape"] == "state.task.status", (
        f"alias mutation should normalize to state.task.status, "
        f"got {m['target_shape']!r}"
    )
    assert m["status_value"] == "running"
    assert m["mutation_kind"] == "assign"
    assert m["function"] == "handle_something"


# ═══════════════════════════════════════════════════════════════════════════════
# W2-T3: CR-1 action_scheduler injection-seam boundary tests
# ═══════════════════════════════════════════════════════════════════════════════


_REPO_ROOT = Path(__file__).parent.parent


def test_cr1_chat_default_action_scheduler_is_none() -> None:
    """W2-T3a: CR-1 — core.chat() 默认 action_scheduler 参数值为 None（AST 验证）。

    action_scheduler 是 registered-not-routed / dormant-by-default 状态：
    chat() 接受参数但默认 None，生产入口不传此参数。
    使用 AST（非 grep）避免 docstring :221 中字面 ActionScheduler( 的误命中。
    """
    core_py = _REPO_ROOT / "agent" / "core.py"
    tree = _read_tree(core_py)

    # 找 def chat(...) 的函数定义
    chat_fn = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "chat":
            chat_fn = node
            break

    assert chat_fn is not None, "core.py 必须定义 chat() 函数"

    # 找 action_scheduler 参数及其默认值
    # defaults 对齐到 args 末尾；kw_defaults 对齐到 kwonlyargs
    args = chat_fn.args
    action_scheduler_default = None
    for i, arg in enumerate(args.args):
        if arg.arg == "action_scheduler":
            # positional arg：defaults 对齐末尾
            offset = len(args.args) - len(args.defaults)
            idx = i - offset
            if 0 <= idx < len(args.defaults):
                action_scheduler_default = args.defaults[idx]
            break

    # 也检查 kwonlyargs
    if action_scheduler_default is None:
        for i, arg in enumerate(args.kwonlyargs):
            if arg.arg == "action_scheduler":
                if i < len(args.kw_defaults) and args.kw_defaults[i] is not None:
                    action_scheduler_default = args.kw_defaults[i]
                break

    assert action_scheduler_default is not None, (
        "chat() 必须有 action_scheduler 参数（期望默认值 None）"
    )
    assert (
        isinstance(action_scheduler_default, ast.Constant)
        and action_scheduler_default.value is None
    ), (
        "chat() 的 action_scheduler 默认值必须是 None；"
        f"got AST node type {type(action_scheduler_default).__name__}"
    )


def test_cr1_main_py_does_not_pass_action_scheduler_kwarg() -> None:
    """W2-T3b: CR-1 — main.py 的 chat() 调用不传 action_scheduler= kwarg（AST 验证）。

    main.py 是 production entry point。若 chat() 被传入 action_scheduler，
    则 scheduler 会被激活（action_scheduler is not None 分支）。
    本测试确认 main.py 没有传此 kwarg，确保 dormant-by-default 状态。

    使用 AST 而非 grep——action_scheduler.py docstring :221 包含字面字符串
    `ActionScheduler(dispatcher=...)` 会污染 grep 结果。
    """
    main_py = _REPO_ROOT / "main.py"
    tree = _read_tree(main_py)

    chat_calls_with_scheduler: list[int] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            # 匹配 chat(...) 或 module.chat(...) 形式
            func = node.func
            is_chat_call = (
                (isinstance(func, ast.Name) and func.id == "chat")
                or (isinstance(func, ast.Attribute) and func.attr == "chat")
            )
            if is_chat_call:
                for kw in node.keywords:
                    if kw.arg == "action_scheduler":
                        chat_calls_with_scheduler.append(getattr(node, "lineno", -1))

    assert chat_calls_with_scheduler == [], (
        "main.py 的 chat() 调用不应传 action_scheduler= kwarg"
        "（action_scheduler 是 dormant-by-default）；"
        f"发现 {len(chat_calls_with_scheduler)} 处调用在行：{chat_calls_with_scheduler}"
    )


def test_cr1_action_scheduler_not_routed_in_production() -> None:
    """W2-T3c: CR-1 — action_scheduler 在 main.py 入口路径中不被注入（registered-not-routed）。

    验证 main.py 不从 agent.action_scheduler 导入 ActionScheduler（
    如果 main.py 注入 scheduler，则 dormant-by-default 状态被打破）。
    使用 _collect_agent_imports 基础设施（复用 :267）。
    """
    main_py = _REPO_ROOT / "main.py"
    imports = _collect_agent_imports(main_py)

    # main.py 不应 import agent.action_scheduler（注入端点）
    # core.py 允许 import（参数接受），但 main.py 不应主动构造 scheduler
    assert "agent.action_scheduler" not in imports, (
        "main.py 不应 import agent.action_scheduler"
        "（action_scheduler 是 dormant-by-default；"
        "如果 main.py import 并构造 ActionScheduler，则 dormant 状态被打破）"
    )


def test_cr1_action_scheduler_class_exists_and_is_not_wired() -> None:
    """W2-T3d: CR-1 — ActionScheduler class 存在（registered）但 core 默认 None（not-routed）。

    用 AST 验证 action_scheduler.py 定义了 ActionScheduler class，
    同时 core.py chat() 函数定义处 action_scheduler 参数默认 None。
    不用 grep 避免 docstring 误命中。
    """
    scheduler_py = _REPO_ROOT / "agent" / "action_scheduler.py"
    tree = _read_tree(scheduler_py)

    # 验证 ActionScheduler class 存在
    scheduler_class = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "ActionScheduler":
            scheduler_class = node
            break

    assert scheduler_class is not None, (
        "agent/action_scheduler.py 必须定义 ActionScheduler class（registered 状态）"
    )

    # 验证 docstring 中有 ActionScheduler( 但这是文档用法，不影响 AST 边界
    # （这也是为什么必须用 AST 而非 grep）
    # 真实类定义行存在，且 core.py 默认 None = registered-not-routed
    core_py = _REPO_ROOT / "agent" / "core.py"
    core_src = core_py.read_text(encoding="utf-8")
    assert "action_scheduler=None" in core_src, (
        "core.py 必须有 action_scheduler=None 默认参数（not-routed 状态）"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# W3: CM-1 config/provider import-boundary + scheduler dormancy precision
# ═══════════════════════════════════════════════════════════════════════════════


WINDOW3_CM1_INVENTORY_DOC = (
    _REPO_ROOT
    / "docs"
    / "06-audit"
    / "WINDOW_3_CM1_CONFIG_IMPORT_BOUNDARY_INVENTORY.zh.md"
)

EXPECTED_CM1_CONFIG_SURFACES = {
    "agent/provider/config.py",
    "agent/provider/simple_config.py",
    "agent/provider/profiles.py",
    "agent/local_config.py",
    "agent/mcp_config.py",
    "agent/mcp_config_cli.py",
    "agent/mcp_config_presenter.py",
    "agent/mcp_config_service.py",
}

EXPECTED_CM1_OWNER_TOKENS = {
    "agent/provider/config.py": ("AgentProviderConfig", "provider API"),
    "agent/provider/simple_config.py": ("UnifiedProviderConfig", "config/config.yaml"),
    "agent/provider/profiles.py": ("ProviderProfile", "profile"),
    "agent/local_config.py": ("local/dev", "display"),
    "agent/mcp_config.py": ("MCPConfig", "parser"),
    "agent/mcp_config_cli.py": ("CLI adapter", "thin"),
    "agent/mcp_config_presenter.py": ("Presenter", "render"),
    "agent/mcp_config_service.py": ("service/use-case", "safe apply"),
}

SCHEDULER_ACTION_TYPE_NAMES = {
    "ACTION_PLAN_START",
    "NODE_ENTER",
    "NODE_EXIT",
    "NODE_FAILURE",
    "ACTION_PLAN_COMPLETE",
}


def _markdown_table_rows_after_heading(
    content: str,
    heading: str,
) -> list[dict[str, str]]:
    """读取指定 heading 后的第一个 markdown table。

    这里不引入 markdown parser：本测试只需要固定 inventory table 的
    header/cell 快照。解析失败应让测试红，而不是静默猜测文档结构。
    """

    lines = content.splitlines()
    start_index = next(
        (index for index, line in enumerate(lines) if line.strip() == heading),
        None,
    )
    assert start_index is not None, f"missing heading: {heading}"

    table_lines: list[str] = []
    for line in lines[start_index + 1:]:
        if line.startswith("## ") and table_lines:
            break
        if line.startswith("|"):
            table_lines.append(line)
        elif table_lines and line.strip():
            break

    assert len(table_lines) >= 3, f"missing markdown table after {heading}"
    headers = [_clean_markdown_cell(cell) for cell in table_lines[0].strip("|").split("|")]
    rows: list[dict[str, str]] = []
    for line in table_lines[2:]:
        cells = [_clean_markdown_cell(cell) for cell in line.strip("|").split("|")]
        rows.append(dict(zip(headers, cells, strict=True)))
    return rows


def _clean_markdown_cell(cell: str) -> str:
    return cell.strip().strip(chr(96))


def _actual_cm1_config_surfaces() -> set[str]:
    mcp_config_surfaces = {
        str(path.relative_to(_REPO_ROOT))
        for path in (_REPO_ROOT / "agent").glob("mcp_config*.py")
    }
    return {
        "agent/provider/config.py",
        "agent/provider/simple_config.py",
        "agent/provider/profiles.py",
        "agent/local_config.py",
        *mcp_config_surfaces,
    }


def _production_python_files_for_entrypoint_scan() -> tuple[Path, ...]:
    return (
        _REPO_ROOT / "main.py",
        *_agent_python_files(),
    )


def _call_has_non_none_action_scheduler_kwarg(node: ast.Call) -> bool:
    for keyword in node.keywords:
        if keyword.arg != "action_scheduler":
            continue
        return not (
            isinstance(keyword.value, ast.Constant)
            and keyword.value.value is None
        )
    return False


def _phase1_registered_handler_names() -> dict[str, str]:
    """从 phase1_hook.py AST 读取 RuntimeActionType -> handler snapshot。"""

    tree = _read_tree(AGENT_DIR / "runtime_integration" / "phase1_hook.py")
    registered: dict[str, str] = {}

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _qualified_name(node.func) != "registry.register":
            continue
        if len(node.args) < 2:
            continue
        action_arg, handler_arg = node.args[0], node.args[1]
        action_name = _qualified_name(action_arg)
        if action_name and action_name.startswith("RuntimeActionType."):
            registered[action_name.rsplit(".", 1)[-1]] = _qualified_name(handler_arg) or ""

    for node in ast.walk(tree):
        if not isinstance(node, ast.For) or not isinstance(node.target, ast.Name):
            continue
        if not isinstance(node.iter, ast.Tuple):
            continue
        loop_action_names = {
            name.rsplit(".", 1)[-1]
            for element in node.iter.elts
            if (name := _qualified_name(element))
            and name.startswith("RuntimeActionType.")
        }
        if not loop_action_names:
            continue
        for child in ast.walk(ast.Module(body=node.body, type_ignores=[])):
            if not isinstance(child, ast.Call):
                continue
            if _qualified_name(child.func) != "registry.register":
                continue
            if len(child.args) < 2:
                continue
            if (
                isinstance(child.args[0], ast.Name)
                and child.args[0].id == node.target.id
            ):
                handler_name = _qualified_name(child.args[1]) or ""
                for action_name in loop_action_names:
                    registered[action_name] = handler_name

    return registered


def test_w3_cm1_config_inventory_matches_source_surfaces() -> None:
    """W3-T1: CM-1 inventory 的 config surface 列表必须与源码事实一致。"""

    assert WINDOW3_CM1_INVENTORY_DOC.is_file(), (
        "Window 3 必须新增 CM-1 config/provider import-boundary inventory 文档"
    )
    content = WINDOW3_CM1_INVENTORY_DOC.read_text(encoding="utf-8")
    rows = _markdown_table_rows_after_heading(
        content,
        "## 1. CM-1 Config Surface Inventory",
    )

    documented_paths = {row["Path"] for row in rows}
    actual_paths = _actual_cm1_config_surfaces()
    assert actual_paths == EXPECTED_CM1_CONFIG_SURFACES
    assert documented_paths == actual_paths, (
        "CM-1 inventory 必须以真实源码路径为准，尤其是 agent/provider/ "
        f"与 mcp_config*.py surfaces；documented={sorted(documented_paths)}, "
        f"actual={sorted(actual_paths)}"
    )


def test_w3_scheduler_dormant_by_default_full_entrypoint_scan() -> None:
    """W3-T2: production entrypoint 不默认注入 action_scheduler。

    scheduler seam 保留且可由测试手工注入；本测试只锁 production Python
    入口不传非 None 的 action_scheduler=。
    """

    chat_calls_with_scheduler: list[str] = []
    for path in _production_python_files_for_entrypoint_scan():
        tree = _read_tree(path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func_name = _qualified_name(node.func)
            if func_name is None:
                continue
            if func_name.rsplit(".", 1)[-1] != "chat":
                continue
            if _call_has_non_none_action_scheduler_kwarg(node):
                rel = path.relative_to(_REPO_ROOT)
                chat_calls_with_scheduler.append(f"{rel}:{getattr(node, 'lineno', '?')}")

    assert chat_calls_with_scheduler == [], (
        "production chat() 调用不应默认注入 action_scheduler；"
        f"found={chat_calls_with_scheduler}"
    )


def test_w3_scheduler_action_types_registered_but_not_core_injected() -> None:
    """W3-T3: scheduler action types 只注册到 ActionSchedulerHandler 边界。

    这锁住 handler registered/routed 的事实，同时防止 L1/L2 subagent action
    type 被误注册为 production dispatcher handler。
    """

    registered = _phase1_registered_handler_names()

    assert set(registered) >= SCHEDULER_ACTION_TYPE_NAMES, (
        f"scheduler action types must stay registered: {registered}"
    )
    scheduler_registrations = {
        action_name: registered[action_name]
        for action_name in SCHEDULER_ACTION_TYPE_NAMES
    }
    assert scheduler_registrations == {
        action_name: "_scheduler_handler"
        for action_name in SCHEDULER_ACTION_TYPE_NAMES
    }

    scheduler_handler_actions = {
        action_name
        for action_name, handler_name in registered.items()
        if handler_name == "_scheduler_handler"
    }
    assert scheduler_handler_actions == SCHEDULER_ACTION_TYPE_NAMES
    assert "SUBAGENT_DELEGATE_L1" not in registered
    assert "SUBAGENT_DELEGATE_L2" not in registered


def test_w3_cm1_per_surface_owner_snapshot_is_descriptive_only() -> None:
    """W3-T4: 每个 config surface 有 owner/用途快照，但不引入 CM-2 contract。"""

    assert WINDOW3_CM1_INVENTORY_DOC.is_file(), (
        "Window 3 CM-1 inventory doc must exist before owner snapshot can be checked"
    )
    content = WINDOW3_CM1_INVENTORY_DOC.read_text(encoding="utf-8")
    rows = _markdown_table_rows_after_heading(
        content,
        "## 2. Per-Surface Owner Snapshot",
    )
    snapshot = {row["Path"]: row for row in rows}

    assert set(snapshot) == EXPECTED_CM1_CONFIG_SURFACES
    for path, required_tokens in EXPECTED_CM1_OWNER_TOKENS.items():
        row_text = " ".join(snapshot[path].values())
        for token in required_tokens:
            assert token in row_text, f"{path} row must mention {token!r}"

    forbidden_cm2_symbols = {
        "CapabilityStatus",
        "CapabilityContract",
        "UnifiedCapability",
        "registry-of-registries",
    }
    for symbol in forbidden_cm2_symbols:
        assert symbol not in content, (
            f"Window 3 inventory must stay descriptive CM-1, not define {symbol}"
        )


def test_w3_scheduler_label_precision_avoids_unreachable_overclaim() -> None:
    """W3-T5: scheduler label 使用 dormant-by-default，而非不可达式 overclaim。"""

    checked_files = (
        AGENT_DIR / "action_scheduler.py",
        _REPO_ROOT / "docs" / "06-audit" / "WINDOW_2_CLOSURE_AUDIT.zh.md",
        _REPO_ROOT / "docs" / "06-audit" / "WINDOW_2_COMPAT_INVENTORY.zh.md",
    )
    forbidden_phrases = {
        "scheduler 逻辑不可达",
        "生产路径无法触达",
        "生产无法触达",
        "completely unreachable",
        "impossible to route",
        "dead path if seam remains injectable",
    }
    findings: list[str] = []
    for path in checked_files:
        text = path.read_text(encoding="utf-8")
        for phrase in forbidden_phrases:
            if phrase in text:
                findings.append(f"{path.relative_to(_REPO_ROOT)}: {phrase}")

    assert findings == [], (
        "scheduler seam 存在且测试可手工注入，当前文档/注释应使用 "
        "dormant-by-default / registered-not-routed in production，"
        f"不要使用不可达式 overclaim: {findings}"
    )

    scheduler_docstring = ast.get_docstring(_read_tree(AGENT_DIR / "action_scheduler.py"))
    assert scheduler_docstring is not None
    assert "dormant-by-default" in scheduler_docstring
    assert "registered-not-routed in production" in scheduler_docstring
    assert "injectable seam" in scheduler_docstring
    assert "manually injectable in tests" in scheduler_docstring
