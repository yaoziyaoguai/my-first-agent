"""Checkpoint Save/Resume dispatcher mediation contract tests (Loop 2.3).

证明 save/load 通过 dispatcher 中介，产生 RuntimeAction evidence，
不是旁路保存机制。测试分层：
- L2: dispatcher.route() 直接调用 → handler evidence
- L3: core.chat() → route_from_runtime_loop() → dispatcher evidence chain
- roundtrip: save → load evidence chain 闭合
"""

from __future__ import annotations

import json

import pytest

from agent.runtime_integration import (
    ActionHandlerRegistry,
    RuntimeActionDispatcher,
    RuntimeActionType,
)
from agent.runtime_integration.checkpoint_resume import CheckpointResumeHandler
from agent.runtime_integration.checkpoint_save import CheckpointSaveHandler
from agent.runtime_integration.evidence import (
    REAL_CORE_LOOP_RUNTIME_E2E,
    RuntimeActionModuleObserver,
)
from agent.runtime_integration.schema import RuntimeActionRequest

# ========== helpers ==========


def _build_save_dispatcher() -> RuntimeActionDispatcher:
    registry = ActionHandlerRegistry()
    registry.register(RuntimeActionType.CHECKPOINT_SAVE, CheckpointSaveHandler())
    return RuntimeActionDispatcher(registry=registry, observer=RuntimeActionModuleObserver())


def _build_resume_dispatcher() -> RuntimeActionDispatcher:
    registry = ActionHandlerRegistry()
    registry.register(RuntimeActionType.CHECKPOINT_RESUME, CheckpointResumeHandler())
    return RuntimeActionDispatcher(registry=registry, observer=RuntimeActionModuleObserver())


def _build_save_resume_dispatcher() -> RuntimeActionDispatcher:
    registry = ActionHandlerRegistry()
    registry.register(RuntimeActionType.CHECKPOINT_SAVE, CheckpointSaveHandler())
    registry.register(RuntimeActionType.CHECKPOINT_RESUME, CheckpointResumeHandler())
    return RuntimeActionDispatcher(registry=registry, observer=RuntimeActionModuleObserver())


@pytest.fixture
def tmp_checkpoint_path(tmp_path, monkeypatch):
    from agent import checkpoint

    path = tmp_path / "checkpoint.json"
    monkeypatch.setattr(checkpoint, "CHECKPOINT_PATH", path)
    return path


# ========== TestCheckpointSaveDispatcherMediation ==========


class TestCheckpointSaveDispatcherMediation:
    """L2: CHECKPOINT_SAVE 通过 dispatcher 中介产生 evidence。"""

    def test_save_produces_checkpoint_save_event(self, tmp_checkpoint_path):
        """dispatcher.route(CHECKPOINT_SAVE) 产生正确 action_type 的 event。"""
        from agent.state import create_agent_state

        state = create_agent_state(system_prompt="test")
        state.task.status = "running"
        state.task.user_goal = "测试目标"

        dispatcher = _build_save_dispatcher()
        result = dispatcher.route(
            RuntimeActionRequest(
                action_type=RuntimeActionType.CHECKPOINT_SAVE,
                source="test",
                parent_trace_id="",
                payload={
                    "_state": state,
                    "source": "test.save",
                    "task_status": state.task.status,
                },
            )
        )

        assert result.status == "success"
        assert len(dispatcher.action_log) >= 1
        event = dispatcher.action_log[-1]
        assert event.action_type == RuntimeActionType.CHECKPOINT_SAVE

    def test_save_event_has_evidence(self, tmp_checkpoint_path):
        """CHECKPOINT_SAVE evidence 包含 save_succeeded 等关键字段。"""
        from agent.state import create_agent_state

        state = create_agent_state(system_prompt="test")
        state.task.status = "running"

        dispatcher = _build_save_dispatcher()
        result = dispatcher.route(
            RuntimeActionRequest(
                action_type=RuntimeActionType.CHECKPOINT_SAVE,
                source="test",
                parent_trace_id="",
                payload={
                    "_state": state,
                    "source": "test.save",
                    "task_status": "running",
                },
            )
        )

        evidence = dict(result.evidence)
        assert evidence.get("save_succeeded") is True, (
            f"save_succeeded 应为 True，实际 {evidence.get('save_succeeded')}"
        )
        assert evidence.get("checkpoint_mediated") is True
        assert evidence.get("capability_type") == "checkpoint_persistence"

    def test_save_no_dispatcher_does_not_crash(self, tmp_checkpoint_path):
        """_dispatch_checkpoint_save(dispatcher=None) 回退到直接调用，不 crash。"""
        from agent.core import _dispatch_checkpoint_save
        from agent.state import create_agent_state

        state = create_agent_state(system_prompt="test")
        state.task.status = "running"

        # 不应 raise
        _dispatch_checkpoint_save(None, state, source="test.fallback")

        # 验证 checkpoint 文件确实被创建
        assert tmp_checkpoint_path.exists()
        saved = json.loads(tmp_checkpoint_path.read_text())
        assert saved.get("task", {}).get("status") == "running"

    def test_save_no_state_does_not_crash(self):
        """payload 中 _state 为 None 时 handler 返回 failed，不 crash。"""
        dispatcher = _build_save_dispatcher()
        result = dispatcher.route(
            RuntimeActionRequest(
                action_type=RuntimeActionType.CHECKPOINT_SAVE,
                source="test",
                parent_trace_id="",
                payload={"_state": None, "source": "test"},
            )
        )
        assert result.status == "failed"


# ========== TestCheckpointResumeDispatcherMediation ==========


class TestCheckpointResumeDispatcherMediation:
    """L2: CHECKPOINT_RESUME 通过 dispatcher 中介产生 evidence。"""

    def test_resume_produces_checkpoint_resume_event(self, tmp_checkpoint_path):
        """dispatcher.route(CHECKPOINT_RESUME) 产生正确 action_type 的 event。"""
        from agent.checkpoint import save_checkpoint
        from agent.state import create_agent_state

        # 先 save 一份 checkpoint
        src = create_agent_state(system_prompt="test")
        src.task.status = "awaiting_plan_confirmation"
        src.task.user_goal = "恢复测试"
        save_checkpoint(src, source="test")

        # 用全新 state 做 resume
        dst = create_agent_state(system_prompt="different")

        dispatcher = _build_resume_dispatcher()
        result = dispatcher.route(
            RuntimeActionRequest(
                action_type=RuntimeActionType.CHECKPOINT_RESUME,
                source="test",
                parent_trace_id="",
                payload={"_state": dst, "resume_mode": "interactive"},
            )
        )

        assert result.status == "success"
        assert len(dispatcher.action_log) >= 1
        event = dispatcher.action_log[-1]
        assert event.action_type == RuntimeActionType.CHECKPOINT_RESUME

    def test_resume_event_has_evidence(self, tmp_checkpoint_path):
        """CHECKPOINT_RESUME evidence 包含 restore_succeeded 等关键字段。"""
        from agent.checkpoint import save_checkpoint
        from agent.state import create_agent_state

        src = create_agent_state(system_prompt="test")
        src.task.status = "running"
        save_checkpoint(src, source="test")

        dst = create_agent_state(system_prompt="different")

        dispatcher = _build_resume_dispatcher()
        result = dispatcher.route(
            RuntimeActionRequest(
                action_type=RuntimeActionType.CHECKPOINT_RESUME,
                source="test",
                parent_trace_id="",
                payload={"_state": dst, "resume_mode": "interactive"},
            )
        )

        evidence = dict(result.evidence)
        assert evidence.get("restore_succeeded") is True, (
            f"restore_succeeded 应为 True，实际 {evidence.get('restore_succeeded')}"
        )
        assert evidence.get("checkpoint_mediated") is True
        assert evidence.get("capability_type") == "checkpoint_restoration"

    def test_resume_restored_fields_in_evidence(self, tmp_checkpoint_path):
        """resume 后 evidence 包含 restored_task_status 等恢复字段。"""
        from agent.checkpoint import save_checkpoint
        from agent.state import create_agent_state

        src = create_agent_state(system_prompt="test")
        src.task.status = "awaiting_user_input"
        src.task.current_step_index = 3
        src.task.pending_tool = {"tool": "bash", "input": {}}
        save_checkpoint(src, source="test")

        dst = create_agent_state(system_prompt="different")

        dispatcher = _build_resume_dispatcher()
        result = dispatcher.route(
            RuntimeActionRequest(
                action_type=RuntimeActionType.CHECKPOINT_RESUME,
                source="test",
                parent_trace_id="",
                payload={"_state": dst, "resume_mode": "interactive"},
            )
        )

        evidence = dict(result.evidence)
        assert evidence.get("restored_task_status") == "awaiting_user_input", (
            f"restored_task_status 应为 'awaiting_user_input'，"
            f"实际 {evidence.get('restored_task_status')}"
        )
        assert evidence.get("restored_step_index") == 3
        assert evidence.get("restored_has_pending_tool") is True

    def test_resume_no_checkpoint_returns_failed(self, tmp_checkpoint_path):
        """无 checkpoint 文件时 resume 返回 failed，不 crash。"""
        from agent.state import create_agent_state

        state = create_agent_state(system_prompt="test")
        dispatcher = _build_resume_dispatcher()
        result = dispatcher.route(
            RuntimeActionRequest(
                action_type=RuntimeActionType.CHECKPOINT_RESUME,
                source="test",
                parent_trace_id="",
                payload={"_state": state, "resume_mode": "interactive"},
            )
        )
        assert result.status == "failed"
        evidence = dict(result.evidence)
        assert evidence.get("restore_succeeded") is False

    def test_resume_already_loaded_mode(self, tmp_checkpoint_path):
        """_already_loaded=True 时 handler 跳过实际 load，仅记录 evidence。"""
        from agent.checkpoint import load_checkpoint_to_state, save_checkpoint
        from agent.state import create_agent_state

        src = create_agent_state(system_prompt="test")
        src.task.status = "awaiting_plan_confirmation"
        save_checkpoint(src, source="test")

        # 模拟 session.py：先 load，再通过 handler 记录 evidence
        dst = create_agent_state(system_prompt="different")
        restored = load_checkpoint_to_state(dst)
        assert restored

        dispatcher = _build_resume_dispatcher()
        result = dispatcher.route(
            RuntimeActionRequest(
                action_type=RuntimeActionType.CHECKPOINT_RESUME,
                source="session.resume",
                parent_trace_id="",
                payload={
                    "_state": dst,
                    "resume_mode": "interactive",
                    "_already_loaded": True,
                },
            )
        )

        assert result.status == "success"
        evidence = dict(result.evidence)
        assert evidence.get("restore_succeeded") is True
        # restored fields 应来自已加载的 state
        assert evidence.get("restored_task_status") == "awaiting_plan_confirmation"


# ========== TestCheckpointTrueResumeRoundtrip ==========


class TestCheckpointTrueResumeRoundtrip:
    """save → load roundtrip 证明状态连续性 + evidence chain 闭合。"""

    def test_roundtrip_conversation_context_continuity(self, tmp_checkpoint_path):
        """save → load 后 conversation.messages 完整恢复。"""
        from agent.checkpoint import load_checkpoint_to_state, save_checkpoint
        from agent.state import create_agent_state

        src = create_agent_state(system_prompt="test")
        src.conversation.messages = [
            {"role": "user", "content": "帮我写代码"},
            {"role": "assistant", "content": "好的，我来帮你"},
        ]
        src.task.status = "running"
        src.task.user_goal = "写代码"

        save_checkpoint(src, source="test")
        dst = create_agent_state(system_prompt="different")
        ok = load_checkpoint_to_state(dst)
        assert ok

        assert len(dst.conversation.messages) == 2
        assert dst.conversation.messages[0]["content"] == "帮我写代码"
        assert dst.conversation.messages[1]["content"] == "好的，我来帮你"

    def test_roundtrip_pending_action_continuity(self, tmp_checkpoint_path):
        """save → load 后 pending_tool 和 status 完整恢复。"""
        from agent.checkpoint import load_checkpoint_to_state, save_checkpoint
        from agent.state import create_agent_state

        src = create_agent_state(system_prompt="test")
        src.task.status = "awaiting_tool_confirmation"
        src.task.pending_tool = {
            "tool_use_id": "T42",
            "tool": "bash",
            "input": {"command": "ls"},
        }
        src.task.current_step_index = 5

        save_checkpoint(src, source="test")
        dst = create_agent_state(system_prompt="different")
        ok = load_checkpoint_to_state(dst)
        assert ok

        assert dst.task.status == "awaiting_tool_confirmation"
        assert dst.task.pending_tool is not None
        assert dst.task.pending_tool["tool"] == "bash"
        assert dst.task.pending_tool["tool_use_id"] == "T42"
        assert dst.task.current_step_index == 5

    def test_roundtrip_dispatcher_evidence_chain(self, tmp_checkpoint_path):
        """save 和 resume 都通过 dispatcher 时，evidence chain 闭合。"""
        from agent.state import create_agent_state

        src = create_agent_state(system_prompt="test")
        src.task.status = "running"
        src.task.user_goal = "evidence chain 测试"

        dispatcher = _build_save_resume_dispatcher()

        # Step 1: dispatcher-mediated save
        save_result = dispatcher.route(
            RuntimeActionRequest(
                action_type=RuntimeActionType.CHECKPOINT_SAVE,
                source="test",
                parent_trace_id="",
                payload={
                    "_state": src,
                    "source": "test.chain",
                    "task_status": src.task.status,
                },
            )
        )
        assert save_result.status == "success"
        save_evidence = dict(save_result.evidence)
        assert save_evidence.get("save_succeeded") is True
        assert save_evidence.get("checkpoint_mediated") is True

        # Step 2: dispatcher-mediated resume
        dst = create_agent_state(system_prompt="different")
        resume_result = dispatcher.route(
            RuntimeActionRequest(
                action_type=RuntimeActionType.CHECKPOINT_RESUME,
                source="test",
                parent_trace_id="",
                payload={"_state": dst, "resume_mode": "interactive"},
            )
        )
        assert resume_result.status == "success"
        resume_evidence = dict(resume_result.evidence)
        assert resume_evidence.get("restore_succeeded") is True
        assert resume_evidence.get("checkpoint_mediated") is True

        # Step 3: evidence chain 闭合 —— 两个 action 都在 action_log 中
        assert len(dispatcher.action_log) >= 2
        action_types = [e.action_type for e in dispatcher.action_log]
        assert RuntimeActionType.CHECKPOINT_SAVE in action_types
        assert RuntimeActionType.CHECKPOINT_RESUME in action_types

        # Step 4: resume 后的 state 与 save 前一致
        assert dst.task.user_goal == "evidence chain 测试"
        assert dst.task.status == "running"

    def test_roundtrip_runtime_decision_frame_reflects_resume(self, tmp_checkpoint_path):
        """RuntimeDecisionFrame 正确反映 checkpoint 状态。"""
        from agent.runtime_decision_frame import build_decision_frame

        frame = build_decision_frame(
            user_input="hello",
            provider_mode="fake",
            checkpoint_pending=False,
        )
        branch_states = frame.get_branch_point_states()
        # checkpoint 相关 branch point 应在 branch_points 中
        assert "checkpoint.save" in branch_states
        assert "checkpoint.resume" in branch_states
        # 当前应标记为 PARTIAL（code path complete, real validation pending）
        assert branch_states["checkpoint.save"].status.value == "PARTIAL"
        assert branch_states["checkpoint.resume"].status.value == "PARTIAL"
        # why_partial 应反映 Loop 2.3 更新
        save_why = branch_states["checkpoint.save"].decision_meta.get("why_partial", "")
        assert "code path complete" in save_why
        assert "REAL-EVIDENCE-004" in save_why
        resume_why = branch_states["checkpoint.resume"].decision_meta.get("why_partial", "")
        assert "code path complete" in resume_why
        assert "REAL-EVIDENCE-004" in resume_why


# ========== TestCheckpointNotFakeable ==========


class TestCheckpointNotFakeable:
    """证明 checkpoint 能力不是 save/load file smoke 或 no-crash 就能冒充的。"""

    def test_not_just_save_load_file(self, tmp_checkpoint_path):
        """dispatcher-mediated save 产生的 evidence 超出纯文件 IO。

        纯文件 save/load 不会产生 RuntimeAction evidence。
        这里验证 dispatcher path 确实产生了 evidence。
        """
        from agent.state import create_agent_state

        state = create_agent_state(system_prompt="test")
        state.task.status = "running"

        dispatcher = _build_save_dispatcher()
        result = dispatcher.route(
            RuntimeActionRequest(
                action_type=RuntimeActionType.CHECKPOINT_SAVE,
                source="test",
                parent_trace_id="",
                payload={
                    "_state": state,
                    "source": "test.not_fakeable",
                    "task_status": "running",
                },
            )
        )

        # 文件确实存在（纯 IO 能做到）
        assert tmp_checkpoint_path.exists()

        # 但 dispatcher evidence 是纯 IO 做不到的
        evidence = dict(result.evidence)
        assert evidence.get("checkpoint_mediated") is True
        assert evidence.get("capability_type") == "checkpoint_persistence"
        assert evidence.get("production_capability") is True
        # L2 evidence 等级
        assert "evidence_level" in evidence

        # action_log 中有记录
        assert len(dispatcher.action_log) >= 1

    def test_no_crash_not_true_resume(self, tmp_checkpoint_path):
        """不 crash 不等于 true resume —— 需要 evidence chain 闭合。

        验证：即使 load 成功且不 crash，如果没有 dispatcher evidence，
        也不能声称 true resume complete。
        """
        from agent.checkpoint import load_checkpoint_to_state, save_checkpoint
        from agent.state import create_agent_state

        # 纯 direct call save/load —— 不 crash，但没有 evidence
        src = create_agent_state(system_prompt="test")
        src.task.status = "awaiting_user_input"
        src.task.pending_tool = {"tool": "bash", "input": {}}
        save_checkpoint(src, source="test")

        dst = create_agent_state(system_prompt="different")
        ok = load_checkpoint_to_state(dst)
        assert ok  # 不 crash
        assert dst.task.status == "awaiting_user_input"  # 状态恢复

        # 但这不是 true resume —— 没有 dispatcher evidence
        # 对比：dispatcher-mediated path
        dispatcher = _build_save_resume_dispatcher()

        # save through dispatcher
        src2 = create_agent_state(system_prompt="test2")
        src2.task.status = "awaiting_user_input"
        save_result = dispatcher.route(
            RuntimeActionRequest(
                action_type=RuntimeActionType.CHECKPOINT_SAVE,
                source="test",
                parent_trace_id="",
                payload={
                    "_state": src2,
                    "source": "test.not_fakeable",
                    "task_status": "awaiting_user_input",
                },
            )
        )
        assert save_result.status == "success"

        # resume through dispatcher
        dst2 = create_agent_state(system_prompt="different2")
        resume_result = dispatcher.route(
            RuntimeActionRequest(
                action_type=RuntimeActionType.CHECKPOINT_RESUME,
                source="test",
                parent_trace_id="",
                payload={"_state": dst2, "resume_mode": "interactive"},
            )
        )
        assert resume_result.status == "success"

        # dispatcher-mediated path 有 evidence chain
        assert len(dispatcher.action_log) >= 2
        save_evidence = dict(save_result.evidence)
        resume_evidence = dict(resume_result.evidence)
        assert save_evidence.get("checkpoint_mediated") is True
        assert resume_evidence.get("checkpoint_mediated") is True


# ========== TestCheckpointSaveHookL3 ==========


class TestCheckpointSaveHookL3:
    """L3: _dispatch_checkpoint_save 通过 route_from_runtime_loop 产生 L3 evidence。"""

    def test_dispatch_checkpoint_save_produces_l3_evidence(self, tmp_checkpoint_path):
        """_dispatch_checkpoint_save 通过 route_from_runtime_loop 路由，evidence 达 L3。"""
        from agent.core import _dispatch_checkpoint_save
        from agent.state import create_agent_state

        state = create_agent_state(system_prompt="test")
        state.task.status = "running"
        state.task.user_goal = "L3 测试"

        real_dispatcher = _build_save_dispatcher()

        class _Spy:
            def __init__(self, real):
                self._real = real
                self.captured = []

            def route(self, request):
                result = self._real.route(request)
                self.captured.append(("route", request, result))
                return result

            def route_from_runtime_loop(self, request, **kwargs):
                result = self._real.route_from_runtime_loop(request, **kwargs)
                self.captured.append(("route_from_runtime_loop", request, result))
                return result

            @property
            def action_log(self):
                return self._real.action_log

        spy = _Spy(real_dispatcher)
        _dispatch_checkpoint_save(spy, state, source="test.l3")

        assert len(spy.captured) >= 1
        method, request, result = spy.captured[0]
        assert method == "route_from_runtime_loop", (
            f"应通过 route_from_runtime_loop 路由，实际 {method!r}"
        )
        assert result.status == "success"

        evidence = dict(result.evidence)
        assert evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E, (
            f"应达到 {REAL_CORE_LOOP_RUNTIME_E2E}，"
            f"实际 {evidence.get('evidence_level')!r}"
        )
        assert evidence.get("save_succeeded") is True
        assert evidence.get("checkpoint_mediated") is True
        assert evidence.get("dispatcher_origin") == "runtime_loop"
        assert evidence.get("core_entrypoint") == "core.chat"
        assert evidence.get("runtime_hook_name") == "save_checkpoint"
