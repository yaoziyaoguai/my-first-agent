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
from collections import Counter
from pathlib import Path
import re


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
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _qualified_name(node.func)
            operation = name.rsplit(".", 1)[-1] if name else None
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
        "agent.memory_fs_store",
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
        "agent.state",
        # Phase 2 SubAgent demo：chat() 内 local import，仅用于
        # "show subagents" / "delegate to" CLI meta-command。
        # 不改变 core 的模块级 import surface，不引入新的模块级耦合。
        "agent.subagent_system.delegation",
        "agent.subagent_system.registry",
        "agent.subagent_system.request",
        # Issue 1 Command Router extraction：CLI meta-command detect/render
        # 提取到独立模块。core.py 模块级 import cli_commands 以获取检测
        # 函数（_looks_like_*）和渲染函数。不引入新的 runtime 路径。
        "agent.cli_commands",
        "agent.tool_registry",
        "agent.tools",
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
        "_execute_subagent_delegation",
        "_extract_text",
        "_handle_planning_phase_result",
        "_is_explicit_l2_trigger",
        # _looks_like_* 检测函数已提取到 agent/cli_commands.py。
        # core.py 通过模块级 import alias 保留向后兼容，
        # 但它们不再是 FunctionDef 节点（只是 import 别名）。
        "_maybe_run_l2_inline",
        "_resolve_provider_evidence_metadata",
        "_run_main_loop",
        "_run_planning_phase",
        "_runtime_loop_fields",
        "_start_planning_for_handler",
        "chat",
        "get_l2_trigger_guard",
        "get_state",
        "refresh_runtime_system_prompt",
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
    ("agent.confirmation.dispatcher", "_request_feedback_intent_choice", "save_checkpoint", 1),
    ("agent.confirmation.plan", "handle_feedback_intent_choice", "clear_checkpoint", 3),
    ("agent.confirmation.plan", "handle_feedback_intent_choice", "save_checkpoint", 2),
    ("agent.confirmation.plan", "handle_plan_confirmation", "clear_checkpoint", 1),
    ("agent.confirmation.plan", "handle_plan_confirmation", "save_checkpoint", 1),
    ("agent.confirmation.plan", "handle_step_confirmation", "clear_checkpoint", 1),
    ("agent.confirmation.plan", "handle_step_confirmation", "save_checkpoint", 1),
    ("agent.confirmation.tool", "handle_tool_confirmation", "save_checkpoint", 4),
    ("agent.confirmation.user_input", "handle_user_input_step", "clear_checkpoint", 1),
    # Global Architecture Debt Remediation：loop guard 的 checkpoint clear
    # 已从 core.py 主循环实现迁到 agent.loop orchestration。
    ("agent.loop", "run_main_loop", "clear_checkpoint", 1),
    # Memory Interactive Confirmation v1：handle_memory_confirmation_reply 内
    # lazy import save_checkpoint 以清 pending 并保存状态（v1 compromise）。
    ("agent.memory_interaction", "handle_memory_confirmation_reply", "save_checkpoint", 1),
    ("agent.response_handlers", "_maybe_advance_step", "clear_checkpoint", 1),
    ("agent.response_handlers", "_maybe_advance_step", "save_checkpoint", 1),
    ("agent.response_handlers", "handle_end_turn_response", "clear_checkpoint", 1),
    ("agent.response_handlers", "handle_end_turn_response", "save_checkpoint", 3),
    ("agent.response_handlers", "handle_tool_use_response", "clear_checkpoint", 2),
    ("agent.session", "finalize_session", "save_checkpoint", 1),
    ("agent.session", "handle_double_interrupt", "save_checkpoint", 1),
    ("agent.session", "handle_interrupt_choice", "clear_checkpoint", 1),
    ("agent.session", "handle_interrupt_with_checkpoint", "save_checkpoint", 1),
    ("agent.session", "handle_resume_choice", "clear_checkpoint", 1),
    ("agent.session", "handle_resume_choice", "load_checkpoint_to_state", 1),
    ("agent.session", "try_resume_from_checkpoint", "clear_checkpoint", 1),
    ("agent.session", "try_resume_from_checkpoint", "load_checkpoint", 1),
    ("agent.session", "try_resume_from_checkpoint", "load_checkpoint_to_state", 1),
    ("agent.task_runtime", "advance_current_step_if_needed", "save_checkpoint", 2),
    ("agent.tool_executor", "execute_single_tool", "save_checkpoint", 4),
    ("agent.transitions", "apply_user_replied_transition", "clear_checkpoint", 1),
    ("agent.transitions", "apply_user_replied_transition", "save_checkpoint", 3),
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
    "agent.confirmation.plan",
    "agent.confirmation.tool",
    "agent.confirmation.user_input",
    "agent.core",
    "agent.loop",
    "agent.memory_interaction",
    "agent.response_handlers",
    "agent.session",
    "agent.task_runtime",
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
        ("agent.confirmation.dispatcher", "_request_feedback_intent_choice", "state.task.status"),
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
        ("agent.confirmation.plan", "handle_feedback_intent_choice", "state.task.status"),
        ("agent.confirmation.plan", "handle_plan_confirmation", "state.reset_task()"),
        ("agent.confirmation.plan", "handle_plan_confirmation", "state.task.status"),
        ("agent.confirmation.plan", "handle_step_confirmation", "state.reset_task()"),
        ("agent.confirmation.tool", "handle_tool_confirmation", "state.task.pending_tool"),
        ("agent.confirmation.tool", "handle_tool_confirmation", "state.task.status"),
        ("agent.confirmation.user_input", "handle_user_input_step", "state.reset_task()"),
        # Memory Interactive Confirmation v1：handle_memory_confirmation_reply
        # 清 pending 并恢复 origin_status。
        (
            "agent.memory_interaction",
            "handle_memory_confirmation_reply",
            "state.task.pending_user_input_request",
        ),
        (
            "agent.memory_interaction",
            "handle_memory_confirmation_reply",
            "state.task.status",
        ),
        # Phase 7 inline confirmation：terminal reply / fallback 后由
        # memory_interaction helper 清 pending 并恢复 origin_status。
        (
            "agent.memory_interaction",
            "_clear_pending_and_save",
            "state.task.pending_user_input_request",
        ),
        (
            "agent.memory_interaction",
            "_clear_pending_and_save",
            "state.task.status",
        ),
        ("agent.loop", "run_main_loop", "state.reset_task()"),
        ("agent.loop", "run_main_loop", "state.task.loop_iterations"),
        ("agent.core", "_run_planning_phase", "state.task.confirm_each_step"),
        ("agent.core", "_run_planning_phase", "state.task.current_plan"),
        ("agent.core", "_run_planning_phase", "state.task.current_step_index"),
        ("agent.core", "_run_planning_phase", "state.task.status"),
        ("agent.core", "_run_planning_phase", "state.task.user_goal"),
        (
            "agent.core",
            "_compress_history_and_sync_checkpoint",
            "state.conversation.messages",
        ),
        (
            "agent.core",
            "_compress_history_and_sync_checkpoint",
            "state.memory.working_summary",
        ),
        # Memory Interactive Confirmation v1：chat() CONFIRMATION_REQUIRED 分支
        # 设置 pending_user_input_request 和 status。
        ("agent.core", "chat", "state.task.pending_user_input_request"),
        ("agent.core", "chat", "state.task.status"),
        ("agent.core", "chat", "state.reset_task()"),
        ("agent.core", "refresh_runtime_system_prompt", "state.set_system_prompt()"),
        ("agent.response_handlers", "_maybe_advance_step", "state.reset_task()"),
        ("agent.response_handlers", "_maybe_advance_step", "state.task.status"),
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
        ("agent.response_handlers", "handle_end_turn_response", "state.task.status"),
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
        ("agent.session", "handle_interrupt_choice", "state.reset_task()"),
        ("agent.session", "handle_interrupt_choice", "state.task.status"),
        ("agent.session", "handle_interrupt_with_checkpoint", "state.task.status"),
        (
            "agent.task_runtime",
            "advance_current_step_if_needed",
            "state.task.current_step_index",
        ),
        ("agent.task_runtime", "advance_current_step_if_needed", "state.task.status"),
        ("agent.tool_executor", "execute_single_tool", "state.task.pending_tool"),
        (
            "agent.tool_executor",
            "execute_single_tool",
            "state.task.pending_user_input_request",
        ),
        ("agent.tool_executor", "execute_single_tool", "state.task.status"),
        ("agent.tool_executor", "execute_single_tool", "state.task.tool_execution_log"),
        ("agent.tool_executor", "execute_pending_tool", "state.task.tool_execution_log"),
        ("agent.transitions", "apply_user_replied_transition", "state.reset_task()"),
        (
            "agent.transitions",
            "apply_user_replied_transition",
            "state.task.pending_user_input_request",
        ),
        ("agent.transitions", "apply_user_replied_transition", "state.task.status"),
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
