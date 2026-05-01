"""Checkpoint ownership characterization tests.

本文件是 checkpoint ownership inventory 之后的 tests-only 安全网。它不创建
checkpoint gateway、不抽 helper、不改 production；只用 AST 与小型 tmp_path
行为测试固化当前 checkpoint 边界，让后续 core.py 去巨石化、helper extraction
或 gateway planning 有可回归基线。

为什么要独立文件
----------------
`tests/test_architecture_boundaries.py` 已经锁住总体 architecture boundary，但它的
checkpoint inventory 只按调用名匹配，会漏掉 `core.py` 中
`save_checkpoint as _save_checkpoint` / `clear_checkpoint as _clear_checkpoint`
这类 alias 调用。本文件补一个 alias-aware inventory，并把 pending user input /
pending tool / duplicate tool execution 风险单独钉住。

本轮不解决 XFAIL-1 / XFAIL-2：topic switch 与 generation interruption 需要
runtime lifecycle 设计；checkpoint tests 只负责持久化 ownership 安全网。
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent
AGENT_DIR = PROJECT_ROOT / "agent"

CHECKPOINT_OPERATIONS = frozenset(
    {
        "save_checkpoint",
        "clear_checkpoint",
        "load_checkpoint",
        "load_checkpoint_to_state",
    }
)

INPUT_DISPLAY_BOUNDARY_FILES = (
    AGENT_DIR / "input_backends" / "simple.py",
    AGENT_DIR / "input_backends" / "textual.py",
    AGENT_DIR / "user_input.py",
    AGENT_DIR / "display_events.py",
)

CHECKPOINT_PERSISTED_PENDING_FIELDS = frozenset(
    {
        "current_plan",
        "current_step_index",
        "pending_tool",
        "pending_user_input_request",
        "tool_execution_log",
    }
)


def _module_name(path: Path) -> str:
    """把源码路径转换成模块名；`__init__.py` 归到 package 名。"""

    parts = list(path.relative_to(PROJECT_ROOT).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _agent_python_files() -> tuple[Path, ...]:
    """列出 production `agent/` 源码，跳过 pycache，避免生成物噪声。"""

    return tuple(
        sorted(
            path
            for path in AGENT_DIR.rglob("*.py")
            if "__pycache__" not in path.parts
        )
    )


def _read_tree(path: Path) -> ast.Module:
    """只做 AST parse，不 import production module，避免触发 runtime 副作用。"""

    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _qualified_name(node: ast.AST) -> str | None:
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
    """返回节点所在函数；不用行号做 baseline，降低无意义排版漂移。"""

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
    """收集 `agent.*` imports，并把 `from agent import checkpoint` 归一化。"""

    imports: set[str] = set()
    for node in ast.walk(_read_tree(path)):
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


def _checkpoint_aliases(tree: ast.AST) -> dict[str, str]:
    """解析 checkpoint API alias，覆盖 `as _save_checkpoint` 这类调用。

    这是本文件相对 `test_architecture_boundaries.py` 的核心补强点：future
    gateway extraction 之前，不能让 core.py 的 alias 调用从 ownership
    inventory 里消失。
    """

    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module == "agent":
                for alias in node.names:
                    if alias.name == "checkpoint":
                        aliases[alias.asname or alias.name] = "agent.checkpoint"
            elif node.module == "agent.checkpoint":
                for alias in node.names:
                    if alias.name in CHECKPOINT_OPERATIONS:
                        aliases[alias.asname or alias.name] = (
                            f"agent.checkpoint.{alias.name}"
                        )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "agent.checkpoint":
                    aliases[alias.asname or alias.name] = "agent.checkpoint"
    return aliases


def _checkpoint_operation_calls() -> Counter[tuple[str, str, str, str]]:
    """返回 `(module, function, operation, call_name)` -> count。

    operation 是规范化后的 checkpoint 操作；call_name 是源码实际调用名。
    同时保留二者，是为了未来审查 alias 是否应被统一到 gateway seam。
    """

    calls: Counter[tuple[str, str, str, str]] = Counter()
    for path in _agent_python_files():
        tree = _read_tree(path)
        aliases = _checkpoint_aliases(tree)
        module = _module_name(path)

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            call_name = _qualified_name(node.func)
            if not call_name:
                continue

            operation: str | None = None
            if call_name in CHECKPOINT_OPERATIONS:
                operation = call_name
            elif call_name in aliases and aliases[call_name].startswith(
                "agent.checkpoint."
            ):
                candidate = aliases[call_name].rsplit(".", 1)[-1]
                if candidate in CHECKPOINT_OPERATIONS:
                    operation = candidate
            elif "." in call_name:
                base, attr = call_name.rsplit(".", 1)
                if aliases.get(base) == "agent.checkpoint" and attr in CHECKPOINT_OPERATIONS:
                    operation = attr

            if operation is not None:
                calls[
                    (
                        module,
                        _enclosing_scope(tree, node),
                        operation,
                        call_name,
                    )
                ] += 1
    return calls


def _state_task_field_writes() -> Counter[tuple[str, str, str]]:
    """收集 pending/checkpoint 关键字段的写入点。

    这不是完整数据流分析；它只钉当前 ownership inventory：哪些模块/函数会写
    `pending_user_input_request`、`pending_tool`、`tool_execution_log`，以及
    confirmation 恢复依赖的 `status` / `current_step_index`。后续若要建
    gateway，先让这些 writer 显式暴露。
    """

    fields = {
        "current_step_index",
        "pending_user_input_request",
        "pending_tool",
        "status",
        "tool_execution_log",
    }
    writes: Counter[tuple[str, str, str]] = Counter()

    for path in _agent_python_files():
        tree = _read_tree(path)
        module = _module_name(path)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    name = _qualified_name(target)
                    if name and any(name == f"state.task.{field}" for field in fields):
                        writes[(module, _enclosing_scope(tree, target), name)] += 1

            if isinstance(node, ast.Call):
                name = _qualified_name(node.func)
                if name and name.endswith(".pop"):
                    base = name[:-4]
                    if any(base == f"state.task.{field}" for field in fields):
                        writes[(module, _enclosing_scope(tree, node), f"{base}.pop()")] += 1

    return writes


def _task_field_references(path: Path) -> set[str]:
    """收集源码 AST 里直接引用的 checkpoint-persisted pending/task 字段名。"""

    found: set[str] = set()
    for node in ast.walk(_read_tree(path)):
        if isinstance(node, ast.Attribute) and node.attr in CHECKPOINT_PERSISTED_PENDING_FIELDS:
            found.add(node.attr)
        elif isinstance(node, ast.Name) and node.id in CHECKPOINT_PERSISTED_PENDING_FIELDS:
            found.add(node.id)
    return found


def test_forbidden_input_display_layers_do_not_touch_checkpoint_api() -> None:
    """input/display/TUI 层不拥有 checkpoint 持久化状态所有权。

    input backend 负责收集输入，display_events 负责 Runtime -> UI 投影，
    user_input 负责 envelope/event 数据契约。它们都不能 import checkpoint，
    也不能直接 save/load/clear checkpoint；否则会绕过 runtime/handler 边界。
    """

    leaked_imports = {
        _module_name(path): sorted(
            dep for dep in _collect_agent_imports(path) if dep == "agent.checkpoint"
        )
        for path in INPUT_DISPLAY_BOUNDARY_FILES
        if "agent.checkpoint" in _collect_agent_imports(path)
    }

    boundary_modules = {_module_name(path) for path in INPUT_DISPLAY_BOUNDARY_FILES}
    leaked_calls = {
        key: count
        for key, count in _checkpoint_operation_calls().items()
        if key[0] in boundary_modules
    }

    assert leaked_imports == {}
    assert leaked_calls == {}


def test_checkpoint_operation_call_inventory_is_alias_aware() -> None:
    """固化 save/load/clear 调用点白名单，包含 core.py alias 调用。

    这是 inventory，不是永久设计认可。当前 save/clear 很分散，后续 gateway
    或 helper extraction 应先更新这张表，再移动 production 代码。
    """

    expected: tuple[tuple[str, str, str, str, int], ...] = (
        ("agent.checkpoint", "load_checkpoint_to_state", "load_checkpoint", "load_checkpoint", 1),
        ("agent.confirm_handlers", "_request_feedback_intent_choice", "save_checkpoint", "save_checkpoint", 1),
        ("agent.confirm_handlers", "handle_feedback_intent_choice", "clear_checkpoint", "clear_checkpoint", 3),
        ("agent.confirm_handlers", "handle_feedback_intent_choice", "save_checkpoint", "save_checkpoint", 2),
        ("agent.confirm_handlers", "handle_plan_confirmation", "clear_checkpoint", "clear_checkpoint", 1),
        ("agent.confirm_handlers", "handle_plan_confirmation", "save_checkpoint", "save_checkpoint", 1),
        ("agent.confirm_handlers", "handle_step_confirmation", "clear_checkpoint", "_clear_ck", 1),
        ("agent.confirm_handlers", "handle_step_confirmation", "clear_checkpoint", "clear_checkpoint", 1),
        ("agent.confirm_handlers", "handle_step_confirmation", "save_checkpoint", "save_checkpoint", 1),
        ("agent.confirm_handlers", "handle_tool_confirmation", "save_checkpoint", "save_checkpoint", 4),
        ("agent.confirm_handlers", "handle_user_input_step", "clear_checkpoint", "clear_checkpoint", 1),
        ("agent.core", "_compress_history_and_sync_checkpoint", "save_checkpoint", "_save_checkpoint", 1),
        ("agent.core", "_run_main_loop", "clear_checkpoint", "_clear_checkpoint", 1),
        ("agent.core", "_run_planning_phase", "save_checkpoint", "_save_checkpoint", 1),
        ("agent.response_handlers", "_maybe_advance_step", "clear_checkpoint", "clear_checkpoint", 1),
        ("agent.response_handlers", "_maybe_advance_step", "save_checkpoint", "save_checkpoint", 1),
        ("agent.response_handlers", "handle_end_turn_response", "clear_checkpoint", "clear_checkpoint", 1),
        ("agent.response_handlers", "handle_end_turn_response", "save_checkpoint", "save_checkpoint", 3),
        ("agent.response_handlers", "handle_tool_use_response", "clear_checkpoint", "clear_checkpoint", 2),
        ("agent.session", "finalize_session", "save_checkpoint", "save_checkpoint", 1),
        ("agent.session", "handle_double_interrupt", "save_checkpoint", "save_checkpoint", 1),
        ("agent.session", "handle_interrupt_with_checkpoint", "clear_checkpoint", "clear_checkpoint", 1),
        ("agent.session", "handle_interrupt_with_checkpoint", "save_checkpoint", "save_checkpoint", 1),
        ("agent.session", "try_resume_from_checkpoint", "clear_checkpoint", "clear_checkpoint", 2),
        ("agent.session", "try_resume_from_checkpoint", "load_checkpoint", "load_checkpoint", 1),
        ("agent.session", "try_resume_from_checkpoint", "load_checkpoint_to_state", "load_checkpoint_to_state", 1),
        ("agent.task_runtime", "advance_current_step_if_needed", "save_checkpoint", "save_checkpoint", 2),
        ("agent.tool_executor", "execute_single_tool", "save_checkpoint", "save_checkpoint", 4),
        ("agent.transitions", "apply_user_replied_transition", "clear_checkpoint", "checkpoint.clear_checkpoint", 1),
        ("agent.transitions", "apply_user_replied_transition", "save_checkpoint", "checkpoint.save_checkpoint", 3),
    )
    actual = tuple(
        sorted(
            (*key, count)
            for key, count in _checkpoint_operation_calls().items()
        )
    )

    assert actual == expected


def test_core_checkpoint_alias_calls_are_not_invisible_to_inventory() -> None:
    """专门钉住本轮 inventory 发现的 core.py alias blind spot。

    Architecture Pack 1 已经有 checkpoint inventory，但缺少 alias 解析。此测试
    确认 `_save_checkpoint` / `_clear_checkpoint` 会被纳入未来 checkpoint
    gateway seam，而不是被误判为“core 没有 checkpoint 调用”。
    """

    calls = _checkpoint_operation_calls()

    assert (
        "agent.core",
        "_compress_history_and_sync_checkpoint",
        "save_checkpoint",
        "_save_checkpoint",
    ) in calls
    assert (
        "agent.core",
        "_run_planning_phase",
        "save_checkpoint",
        "_save_checkpoint",
    ) in calls
    assert (
        "agent.core",
        "_run_main_loop",
        "clear_checkpoint",
        "_clear_checkpoint",
    ) in calls


def test_checkpoint_operation_owner_modules_are_reviewed_for_future_gateway() -> None:
    """未来 checkpoint gateway 的收口对象必须从 owner module inventory 开始。

    本轮不创建 gateway，只把当前 owner modules 钉住。若未来新增模块直接
    save/load/clear checkpoint，本测试先失败，要求解释它是否应进入 gateway。
    """

    expected_owner_modules = {
        "agent.checkpoint",
        "agent.confirm_handlers",
        "agent.core",
        "agent.response_handlers",
        "agent.session",
        "agent.task_runtime",
        "agent.tool_executor",
        "agent.transitions",
    }

    actual_owner_modules = {
        module for module, _function, _operation, _call_name in _checkpoint_operation_calls()
    }

    assert actual_owner_modules == expected_owner_modules


def test_pending_confirmation_persistence_writers_are_reviewed() -> None:
    """显式钉住 pending confirmation 的持久化 ownership。

    plan/step/tool/feedback-intent confirmation 目前由 `confirm_handlers` 推进
    runtime state，并在必要时 save/clear checkpoint。这是 characterization，
    不是永久认可当前分散保存点；后续 gateway 或 helper extraction 要先看见这些
    owner，再移动生产代码。input/display/TUI 不能绕过 handler 自己保存确认态；
    XFAIL-1 topic switch 与 XFAIL-2 Esc cancel/interruption 也不在本测试里实现。
    """

    actual_checkpoint_calls = {
        (*key, count)
        for key, count in _checkpoint_operation_calls().items()
        if key[0] == "agent.confirm_handlers"
    }
    expected_checkpoint_calls = {
        ("agent.confirm_handlers", "_request_feedback_intent_choice", "save_checkpoint", "save_checkpoint", 1),
        ("agent.confirm_handlers", "handle_feedback_intent_choice", "clear_checkpoint", "clear_checkpoint", 3),
        ("agent.confirm_handlers", "handle_feedback_intent_choice", "save_checkpoint", "save_checkpoint", 2),
        ("agent.confirm_handlers", "handle_plan_confirmation", "clear_checkpoint", "clear_checkpoint", 1),
        ("agent.confirm_handlers", "handle_plan_confirmation", "save_checkpoint", "save_checkpoint", 1),
        ("agent.confirm_handlers", "handle_step_confirmation", "clear_checkpoint", "_clear_ck", 1),
        ("agent.confirm_handlers", "handle_step_confirmation", "clear_checkpoint", "clear_checkpoint", 1),
        ("agent.confirm_handlers", "handle_step_confirmation", "save_checkpoint", "save_checkpoint", 1),
        ("agent.confirm_handlers", "handle_tool_confirmation", "save_checkpoint", "save_checkpoint", 4),
        ("agent.confirm_handlers", "handle_user_input_step", "clear_checkpoint", "clear_checkpoint", 1),
    }
    actual_state_writes = {
        (*key, count)
        for key, count in _state_task_field_writes().items()
        if key[0] == "agent.confirm_handlers"
        and key[2]
        in {
            "state.task.current_step_index",
            "state.task.pending_tool",
            "state.task.pending_user_input_request",
            "state.task.status",
        }
    }
    expected_state_writes = {
        ("agent.confirm_handlers", "_request_feedback_intent_choice", "state.task.pending_user_input_request", 1),
        ("agent.confirm_handlers", "_request_feedback_intent_choice", "state.task.status", 1),
        ("agent.confirm_handlers", "handle_feedback_intent_choice", "state.task.current_step_index", 1),
        ("agent.confirm_handlers", "handle_feedback_intent_choice", "state.task.pending_user_input_request", 2),
        ("agent.confirm_handlers", "handle_feedback_intent_choice", "state.task.status", 3),
        ("agent.confirm_handlers", "handle_plan_confirmation", "state.task.status", 1),
        ("agent.confirm_handlers", "handle_tool_confirmation", "state.task.pending_tool", 2),
        ("agent.confirm_handlers", "handle_tool_confirmation", "state.task.status", 4),
    }

    assert actual_checkpoint_calls == expected_checkpoint_calls
    assert actual_state_writes == expected_state_writes


def test_checkpoint_schema_fields_do_not_leak_into_input_display_layers() -> None:
    """input/display/TUI 层不应该知道 checkpoint-persisted pending schema。

    这里不禁止 runtime handlers 读取 `pending_tool` / `pending_user_input_request`；
    当前架构确实依赖这些字段。本测试只防止 input backend、display_events、
    user_input 这类边界层直接理解并持久化 runtime pending schema。
    """

    leaked = {
        _module_name(path): sorted(_task_field_references(path))
        for path in INPUT_DISPLAY_BOUNDARY_FILES
        if _task_field_references(path)
    }

    assert leaked == {}


def test_pending_user_input_persistence_writers_are_reviewed() -> None:
    """固化 pending_user_input_request 的设置/清理 owner。

    request_user_input、fallback/no_progress、feedback intent 都复用同一 pending
    字段；这是可控债务。本测试只登记谁能写它，防止 input/display 层或新模块
    悄悄获得持久化语义。
    """

    actual = {
        (*key, count)
        for key, count in _state_task_field_writes().items()
        if key[2] == "state.task.pending_user_input_request"
    }
    expected = {
        ("agent.confirm_handlers", "_request_feedback_intent_choice", "state.task.pending_user_input_request", 1),
        ("agent.confirm_handlers", "handle_feedback_intent_choice", "state.task.pending_user_input_request", 2),
        ("agent.response_handlers", "handle_end_turn_response", "state.task.pending_user_input_request", 1),
        ("agent.tool_executor", "execute_single_tool", "state.task.pending_user_input_request", 1),
        ("agent.transitions", "apply_user_replied_transition", "state.task.pending_user_input_request", 1),
    }

    assert actual == expected


def test_pending_tool_and_execution_log_persistence_writers_are_reviewed() -> None:
    """固化 pending_tool / tool_execution_log 的 persistence writers。

    pending tool 和执行日志决定 resume 后是否需要重新确认、是否会重复执行工具。
    这些 writer 是后续 checkpoint gateway 与 sub-agent/Skill 工具化前必须看清的
    ownership 边界；本轮只 characterization，不改执行逻辑。
    """

    actual = {
        (*key, count)
        for key, count in _state_task_field_writes().items()
        if key[2] in {
            "state.task.pending_tool",
            "state.task.tool_execution_log",
            "state.task.tool_execution_log.pop()",
        }
    }
    expected = {
        ("agent.confirm_handlers", "handle_tool_confirmation", "state.task.pending_tool", 2),
        ("agent.tool_executor", "execute_pending_tool", "state.task.tool_execution_log", 1),
        ("agent.tool_executor", "execute_single_tool", "state.task.pending_tool", 3),
        ("agent.tool_executor", "execute_single_tool", "state.task.tool_execution_log", 3),
        ("agent.tool_executor", "execute_single_tool", "state.task.tool_execution_log.pop()", 1),
    }

    assert actual == expected


def test_resumed_tool_execution_log_prevents_duplicate_tool_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """resume 后同一个 tool_use_id 不应再次执行真实工具。

    这是 pending tool / duplicate execution risk 的最小行为钉子：checkpoint 已
    持久化 `tool_execution_log` 时，`execute_single_tool` 应复用缓存 result 并
    补 tool_result，不得再次调用 `execute_tool`。测试使用 tmp_path checkpoint，
    不读取真实 sessions/runs，也不触碰真实工具。
    """

    from agent import checkpoint
    from agent.checkpoint import load_checkpoint_to_state, save_checkpoint
    from agent.state import create_agent_state
    import agent.tool_executor as tool_executor

    checkpoint_path = tmp_path / "checkpoint.json"
    monkeypatch.setattr(checkpoint, "CHECKPOINT_PATH", checkpoint_path)

    src = create_agent_state(system_prompt="test")
    src.task.current_step_index = 0
    src.task.tool_execution_log = {
        "toolu_existing": {
            "tool": "read_file",
            "input": {"path": "README.md"},
            "result": "cached result",
            "status": "executed",
            "step_index": 0,
        }
    }
    save_checkpoint(src, source="tests.checkpoint_ownership.duplicate_tool")

    dst = create_agent_state(system_prompt="test")
    assert load_checkpoint_to_state(dst)

    def _unexpected_execute_tool(*_args, **_kwargs):
        raise AssertionError("resumed tool_use_id must use cached result, not execute")

    monkeypatch.setattr(tool_executor, "execute_tool", _unexpected_execute_tool)

    block = SimpleNamespace(
        id="toolu_existing",
        name="read_file",
        input={"path": "README.md"},
    )
    messages: list[dict] = []
    turn_state = SimpleNamespace(
        round_tool_traces=[],
        on_runtime_event=None,
        on_display_event=None,
    )

    result = tool_executor.execute_single_tool(
        block,
        state=dst,
        turn_state=turn_state,
        turn_context={},
        messages=messages,
    )

    assert result is None
    assert messages == [
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu_existing",
                    "content": "cached result",
                }
            ],
        }
    ]
