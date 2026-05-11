"""完整 resume 流程测试（P2-3）。

验证 checkpoint 保存 → 重启 → resume 提示 → 确认恢复 → 继续任务
的完整闭环。
"""

from __future__ import annotations


import pytest

from agent.state import create_agent_state


@pytest.fixture
def tmp_checkpoint_path(tmp_path, monkeypatch):
    from agent import checkpoint

    path = tmp_path / "checkpoint.json"
    monkeypatch.setattr(checkpoint, "CHECKPOINT_PATH", path)
    return path


class TestResumeFullFlow:
    """完整 resume 流程：保存 → 重启 → 提示 → 确认 → 继续。"""

    def test_resume_accept_restores_state(self, tmp_checkpoint_path, monkeypatch):
        """接受 resume 后 state 正确恢复。"""
        from agent.checkpoint import save_checkpoint
        from agent.session import try_resume_from_checkpoint, handle_resume_choice
        from agent.core import get_state

        # 1. 创建带进行中任务的 state 并保存 checkpoint
        src = create_agent_state(system_prompt="test")
        src.task.user_goal = "审查 auth 模块"
        src.task.current_plan = {
            "goal": "审查 auth 模块",
            "steps": [
                {"title": "读取 auth.py", "type": "read"},
                {"title": "生成报告", "type": "report"},
            ],
        }
        src.task.current_step_index = 1
        src.task.status = "awaiting_step_confirmation"
        src.task.loop_iterations = 5
        src.task.tool_call_count = 3
        src.conversation.messages = [
            {"role": "user", "content": "请审查 auth 模块"},
            {"role": "assistant", "content": "好的，正在审查"},
        ]

        save_checkpoint(src, source="tests.resume_full_flow")

        # 2. 模拟重启：新建 state 替换 core.state
        fresh = create_agent_state(system_prompt="other")
        monkeypatch.setattr(
            __import__("agent.core", fromlist=["state"]),
            "state",
            fresh,
        )
        # 确保 TTY 路径（测试环境 stdin 可能非 TTY）
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)

        # 3. try_resume_from_checkpoint 应设 status 为 awaiting_resume_choice
        try_resume_from_checkpoint()
        assert fresh.task.status == "awaiting_resume_choice"

        # 4. 用户选择 y
        handle_resume_choice("y")

        # 5. 验证 state 恢复
        restored = get_state()
        assert restored.task.user_goal == "审查 auth 模块"
        assert restored.task.current_plan == src.task.current_plan
        assert restored.task.current_step_index == 1
        assert restored.task.status == "awaiting_step_confirmation"
        assert restored.task.loop_iterations == 5
        assert restored.task.tool_call_count == 3
        assert len(restored.conversation.messages) == 2
        assert restored.conversation.messages[0]["content"] == "请审查 auth 模块"

    def test_resume_decline_clears_checkpoint(self, tmp_checkpoint_path, monkeypatch):
        """拒绝 resume 后 checkpoint 被清除，status 回到 idle。

        直接调用 agent.checkpoint.clear_checkpoint 路径，避免
        _reset_core_module 对 session.clear_checkpoint 的 monkeypatch 残留。
        """
        from agent.checkpoint import save_checkpoint

        # 1. 保存 checkpoint
        src = create_agent_state(system_prompt="test")
        src.task.user_goal = "任务"
        src.task.status = "awaiting_tool_confirmation"
        src.task.pending_tool = {
            "tool_use_id": "T1",
            "tool": "write_file",
            "input": {"path": "x.txt", "content": "hi"},
        }
        save_checkpoint(src, source="tests.resume_decline")
        assert tmp_checkpoint_path.exists()

        # 2. 模拟重启
        fresh = create_agent_state(system_prompt="other")
        monkeypatch.setattr(
            __import__("agent.core", fromlist=["state"]),
            "state",
            fresh,
        )
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)

        # 直接 stub session 模块里的 clear_checkpoint 引用，
        # 避免被其他测试的 monkeypatch 残留污染。
        import agent.session as session_mod
        from agent.checkpoint import clear_checkpoint as real_clear
        monkeypatch.setattr(session_mod, "clear_checkpoint", real_clear)

        # 3. try_resume_from_checkpoint 应设 awaiting_resume_choice
        from agent.session import try_resume_from_checkpoint, handle_resume_choice
        try_resume_from_checkpoint()
        assert fresh.task.status == "awaiting_resume_choice"

        # 4. 用户选择 n
        handle_resume_choice("n")

        # 5. checkpoint 文件被删除，status 回到 idle
        assert not tmp_checkpoint_path.exists()
        assert fresh.task.status == "idle"

    def test_resume_pipe_mode_auto_resumes(self, tmp_checkpoint_path, monkeypatch):
        """管道模式下自动恢复，不弹交互提示。"""
        from agent.checkpoint import save_checkpoint
        from agent.session import try_resume_from_checkpoint

        # 1. 保存 checkpoint
        src = create_agent_state(system_prompt="test")
        src.task.user_goal = "管道任务"
        src.task.status = "awaiting_user_input"
        src.task.pending_user_input_request = {
            "awaiting_kind": "request_user_input",
            "question": "预算多少？",
            "why_needed": "继续任务",
        }
        save_checkpoint(src, source="tests.pipe_mode")

        # 2. 模拟重启 + 管道模式（stdin 非 TTY）
        fresh = create_agent_state(system_prompt="other")
        monkeypatch.setattr(
            __import__("agent.core", fromlist=["state"]),
            "state",
            fresh,
        )
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)

        # 3. try_resume_from_checkpoint 应自动恢复
        try_resume_from_checkpoint()

        # 4. status 应恢复到原状态（不是 awaiting_resume_choice）
        assert fresh.task.status == "awaiting_user_input"
        assert fresh.task.user_goal == "管道任务"
        assert fresh.task.pending_user_input_request["question"] == "预算多少？"

    def test_resume_continue_task_after_restore(self, tmp_checkpoint_path, monkeypatch):
        """resume 后能继续执行任务（新 chat 调用正常处理）。"""
        from agent.checkpoint import save_checkpoint
        from agent.session import try_resume_from_checkpoint, handle_resume_choice
        from agent.core import get_state

        # 1. 保存 running 状态 checkpoint
        src = create_agent_state(system_prompt="test")
        src.task.user_goal = "继续任务"
        src.task.current_plan = {
            "goal": "继续任务",
            "steps": [{"title": "步骤1"}, {"title": "步骤2"}],
        }
        src.task.current_step_index = 1
        src.task.status = "running"
        src.conversation.messages = [
            {"role": "user", "content": "开始任务"},
            {"role": "assistant", "content": "正在执行步骤1"},
        ]
        save_checkpoint(src, source="tests.resume_continue")

        # 2. 模拟重启
        fresh = create_agent_state(system_prompt="other")
        monkeypatch.setattr(
            __import__("agent.core", fromlist=["state"]),
            "state",
            fresh,
        )
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)

        # 3. Resume
        try_resume_from_checkpoint()
        assert fresh.task.status == "awaiting_resume_choice"
        handle_resume_choice("y")

        # 4. 验证恢复后 state 可继续工作
        restored = get_state()
        assert restored.task.user_goal == "继续任务"
        assert restored.task.current_step_index == 1
        assert restored.task.status == "running"

        # 模拟用户继续输入后的行为：验证 messages 可继续追加
        restored.add_user_message("继续步骤2")
        assert len(restored.conversation.messages) == 3
        assert restored.conversation.messages[2]["content"] == "继续步骤2"


class TestInterruptChoiceFlow:
    """Ctrl+C 中断选择流程测试。"""

    def test_interrupt_choice_continue(self, monkeypatch):
        """选择 1（继续）后 status 回到 running。"""
        from agent.session import handle_interrupt_with_checkpoint, handle_interrupt_choice

        # 模拟 running 状态的 state
        from agent.state import create_agent_state
        state = create_agent_state(system_prompt="test")
        state.task.user_goal = "任务"
        state.task.status = "running"
        monkeypatch.setattr(
            __import__("agent.core", fromlist=["state"]),
            "state",
            state,
        )
        # stub save_checkpoint / clear_checkpoint
        monkeypatch.setattr(
            __import__("agent.checkpoint", fromlist=["save_checkpoint"]),
            "save_checkpoint",
            lambda s, source=None: None,
        )
        monkeypatch.setattr(
            __import__("agent.checkpoint", fromlist=["clear_checkpoint"]),
            "clear_checkpoint",
            lambda: None,
        )
        # stub save_session_snapshot
        monkeypatch.setattr(
            __import__("agent.session", fromlist=["save_session_snapshot"]),
            "save_session_snapshot",
            lambda m: None,
        )

        # 1. 触发中断
        should_exit = handle_interrupt_with_checkpoint()
        assert should_exit is False
        assert state.task.status == "awaiting_interrupt_choice"

        # 2. 选择 1：继续
        should_exit = handle_interrupt_choice("1")
        assert should_exit is False
        assert state.task.status == "running"

    def test_interrupt_choice_abandon(self, monkeypatch):
        """选择 2（放弃）后 reset_task，status 回到 idle。"""
        from agent.session import handle_interrupt_with_checkpoint, handle_interrupt_choice
        from agent.state import create_agent_state

        state = create_agent_state(system_prompt="test")
        state.task.user_goal = "任务"
        state.task.status = "running"
        monkeypatch.setattr(
            __import__("agent.core", fromlist=["state"]),
            "state",
            state,
        )
        monkeypatch.setattr(
            __import__("agent.checkpoint", fromlist=["save_checkpoint"]),
            "save_checkpoint",
            lambda s, source=None: None,
        )
        monkeypatch.setattr(
            __import__("agent.checkpoint", fromlist=["clear_checkpoint"]),
            "clear_checkpoint",
            lambda: None,
        )

        handle_interrupt_with_checkpoint()
        assert state.task.status == "awaiting_interrupt_choice"

        should_exit = handle_interrupt_choice("2")
        assert should_exit is False
        assert state.task.status == "idle"
        assert state.task.user_goal is None
        assert state.task.current_plan is None

    def test_interrupt_choice_exit(self, monkeypatch):
        """选择 3（退出）返回 True。"""
        from agent.session import handle_interrupt_with_checkpoint, handle_interrupt_choice
        from agent.state import create_agent_state

        state = create_agent_state(system_prompt="test")
        state.task.status = "running"
        monkeypatch.setattr(
            __import__("agent.core", fromlist=["state"]),
            "state",
            state,
        )
        monkeypatch.setattr(
            __import__("agent.checkpoint", fromlist=["save_checkpoint"]),
            "save_checkpoint",
            lambda s, source=None: None,
        )
        monkeypatch.setattr(
            __import__("agent.session", fromlist=["save_session_snapshot"]),
            "save_session_snapshot",
            lambda m: None,
        )

        handle_interrupt_with_checkpoint()
        assert state.task.status == "awaiting_interrupt_choice"

        should_exit = handle_interrupt_choice("3")
        assert should_exit is True
