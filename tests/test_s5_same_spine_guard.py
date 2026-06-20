"""S5-G07 same-spine durability 守卫（不变量测试）。

锁定 AC-6：durable ledger 集成不得引入第二条 fake/real 执行路径、独立 task runner、
独立 tool 执行器、独立 policy gate 或独立 evidence recorder。本文件是「守卫」类测试
（与 ``test_architecture_boundaries.py`` 同性质）：现在通过（不变量成立），若有人把
执行主链路接进 ledger 模块则失败。

三道防线：
1. 结构（AST）：ledger 模块不得导入/调用执行主链路（tool_executor / provider /
   runtime_integration / core / loop / action_scheduler / checkpoint / evidence_recorder）；
2. 结构（API allowlist）：``TaskLedger`` 公共方法只有 ``append`` / ``read_all``，
   不得有 restore_state / execute / step 等方法——checkpoint 仍是唯一状态恢复源（AC-4）；
3. 行为：``record_checkpoint_boundary`` 只追加 ledger 记录，**不**推进 task step——
   推进只能由 governed runtime（``advance_governed_task_if_ready``）完成。
"""

from __future__ import annotations

import ast
import importlib
import inspect

from agent.state import create_agent_state
from agent.task_ledger_cooperation import record_checkpoint_boundary
from agent.task_ledger_store import TaskLedger
from agent.task_orchestration import accept_governed_plan, receive_governed_task
from agent.task_state_model import build_governed_task_state

_LEDGER_MODULES = (
    "agent.task_ledger",
    "agent.task_ledger_store",
    "agent.task_ledger_cooperation",
    "agent.ledger_audit_alignment",
)

# 这些模块属于执行主链路 / 状态恢复源 / evidence 写入路径——ledger 模块不得导入它们
# （ledger 只读投影 task_state_model / replay_chain，引用 checkpoint 路径字符串）。
_FORBIDDEN_MODULES = {
    "agent.tool_executor",
    "agent.tool_registry",
    "agent.core",
    "agent.loop",
    "agent.action_scheduler",
    "agent.checkpoint",
    "agent.evidence_recorder",
}


def _imported_module_names(module) -> set[str]:
    source = inspect.getsource(module)
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_ledger_modules_do_not_import_execution_spine():
    for module_name in _LEDGER_MODULES:
        module = importlib.import_module(module_name)
        imported = _imported_module_names(module)
        leaked = imported & _FORBIDDEN_MODULES
        assert not leaked, f"{module_name} imports execution-spine module(s): {leaked}"
        # provider / runtime_integration 子包也不得导入（执行主链路）。
        provider_imports = {i for i in imported if i.startswith("agent.provider")}
        assert not provider_imports, f"{module_name} imports provider: {provider_imports}"
        runtime_imports = {
            i for i in imported if i.startswith("agent.runtime_integration")
        }
        assert not runtime_imports, (
            f"{module_name} imports runtime_integration: {runtime_imports}"
        )


def test_task_ledger_api_is_storage_only():
    public_methods = {
        name
        for name, member in inspect.getmembers(TaskLedger)
        if not name.startswith("_") and callable(member)
    }
    # 只允许 append / read_all —— 不得有 restore_state / execute / step 等方法。
    assert public_methods == {"append", "read_all"}


def test_ledger_recording_does_not_drive_governed_stepping(tmp_path):
    # record_checkpoint_boundary 只追加 ledger 记录，不得改变 task state 的推进。
    state = create_agent_state(system_prompt="S5 same-spine guard")
    state.memory.session_id = "s5-spine-session"
    receive_governed_task(
        state,
        user_goal="S5 same-spine guard",
        plan_payload={
            "goal": "guard",
            "steps": [
                {"step_id": "g1", "title": "a", "description": "a", "step_type": "read"},
                {"step_id": "g2", "title": "b", "description": "b", "step_type": "edit"},
            ],
        },
    )
    accept_governed_plan(state)
    before = state.task.current_step_index

    ledger = TaskLedger(tmp_path / "guard.jsonl")
    record_checkpoint_boundary(
        ledger,
        build_governed_task_state(state),
        task_id="guard",
        checkpoint_ref="/tmp/guard.json",
        checkpoint_source="guard",
        recorded_at="r1",
    )
    after = state.task.current_step_index
    # ledger 记录未推进 step —— 推进只能由 governed runtime 完成。
    assert before == after
    # 但 ledger 确实落盘了记录（supplemental，不是 no-op）。
    assert len(ledger.read_all()) >= 1
