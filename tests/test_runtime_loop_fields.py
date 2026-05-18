"""Runtime loop fields 是最小 debug/audit 投影，不拥有主循环。

这些测试先锁住现状：主循环日志字段只能从 TaskState 读出安全摘要，不能修改
runtime state，也不能引入 checkpoint、Memory、ToolRegistry 或 observability 平台。
"""

from __future__ import annotations

from dataclasses import asdict


def test_runtime_loop_fields_project_task_state_without_mutation() -> None:
    """字段投影只服务调试/审计证据；调用后 TaskState 必须保持不变。"""

    from agent.runtime_loop_fields import build_runtime_loop_fields
    from agent.state import create_agent_state

    state = create_agent_state(system_prompt="test")
    state.task.status = "running"
    state.task.loop_iterations = 3
    state.task.current_step_index = 0
    state.task.pending_tool = {"tool": "write_file"}
    state.task.pending_user_input_request = {"kind": "confirm"}
    state.task.current_plan = {
        "steps": [
            {
                "title": "写总结",
                "step_type": "report",
            }
        ]
    }

    before = asdict(state.task)

    assert build_runtime_loop_fields(state) == {
        "task_status": "running",
        "current_step_index": 0,
        "loop_iterations": 3,
        "has_pending_tool": True,
        "has_pending_user_input": True,
        "current_step_title": "写总结",
        "current_step_type": "report",
    }
    assert asdict(state.task) == before


def test_runtime_loop_fields_omit_step_metadata_when_index_is_out_of_range() -> None:
    """越界 step index 只省略 step metadata，不能猜测或修正状态。"""

    from agent.runtime_loop_fields import build_runtime_loop_fields
    from agent.state import create_agent_state

    state = create_agent_state(system_prompt="test")
    state.task.status = "running"
    state.task.current_step_index = 9
    state.task.current_plan = {"steps": [{"title": "不会被读取", "step_type": "tool"}]}

    fields = build_runtime_loop_fields(state)

    assert fields == {
        "task_status": "running",
        "current_step_index": 9,
        "loop_iterations": 0,
        "has_pending_tool": False,
        "has_pending_user_input": False,
    }
    assert "current_step_title" not in fields
    assert "current_step_type" not in fields
