"""Gap 4: checkpoint scope selection — single-file vs session-scoped.

验证 _load_checkpoint_best_effort / _load_checkpoint_to_state_best_effort
在 single-file checkpoint (formerly "v1", 例如 memory/checkpoint.json)
和 session-scoped checkpoint (formerly "v2", 例如 memory/checkpoints/{sid}/*.json)
同时存在时的选择策略：

- 不无条件优先 session-scoped
- 按 mtime 选择最新 checkpoint
- 拒绝跨 session 的 single-file checkpoint
- session-scoped 损坏时 fallback 到下一个可用 checkpoint
- 无 session_id metadata 的 single-file checkpoint 保留向后兼容
"""

from __future__ import annotations

import json
import os as _os
from pathlib import Path

from agent.checkpoint import (
    save_checkpoint,
)
from agent.state import create_agent_state

# ── helpers ──────────────────────────────────────────────────────────

def _write_session_checkpoint(session_id: str, run_id: str, session_dir: Path,
                              state, mtime_offset: float = 0.0) -> Path:
    """向临时 session 目录写入 session-scoped checkpoint (formerly v2)，返回文件路径。"""
    target = session_dir / session_id / f"{run_id}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    save_checkpoint(state, path=target, session_id=session_id, run_id=run_id)
    if mtime_offset != 0.0:
        new_mtime = target.stat().st_mtime + mtime_offset
        target.touch()
        _os.utime(str(target), (new_mtime, new_mtime))
    return target


def _write_single_file_checkpoint(state, path: Path, mtime_offset: float = 0.0) -> Path:
    """向临时路径写入 single-file checkpoint (formerly v1)，返回文件路径。"""
    save_checkpoint(state, path=path)
    if mtime_offset != 0.0:
        new_mtime = path.stat().st_mtime + mtime_offset
        _os.utime(str(path), (new_mtime, new_mtime))
    return path


def _write_single_file_checkpoint_with_session(state, path: Path, session_id: str,
                                                mtime_offset: float = 0.0) -> Path:
    """写入 single-file checkpoint 并强制设置 meta.session_id。"""
    save_checkpoint(state, path=path, session_id=session_id)
    if mtime_offset != 0.0:
        new_mtime = path.stat().st_mtime + mtime_offset
        _os.utime(str(path), (new_mtime, new_mtime))
    return path


def _write_corrupted_session_checkpoint(session_id: str, run_id: str,
                                         session_dir: Path) -> Path:
    """写入一个损坏的 session-scoped checkpoint（无效 JSON）。"""
    target = session_dir / session_id / f"{run_id}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("this is not valid json {{{", encoding="utf-8")
    return target


def _make_state(status: str = "running", user_goal: str = "test goal"):
    """创建最小合法 AgentState fixture。"""
    st = create_agent_state(system_prompt="test")
    st.task.status = status
    st.task.user_goal = user_goal
    st.conversation.messages.append({"role": "user", "content": "hello"})
    return st


# ── _load_checkpoint_best_effort 测试 ─────────────────────────────────

class TestLoadCheckpointBestEffort:
    """_load_checkpoint_best_effort() 的 scope 选择语义。"""

    # ── 基本存在性 ──────────────────────────────────────────────

    def test_only_single_file_loads_it(self, tmp_path, monkeypatch):
        """只有 single-file checkpoint 存在时加载它。"""
        from agent.session import _load_checkpoint_best_effort

        single_path = tmp_path / "checkpoint.json"
        state = _make_state(status="awaiting_user_input")
        _write_single_file_checkpoint(state, single_path)

        import agent.checkpoint as ckpt
        import agent.session as session_mod

        monkeypatch.setattr(ckpt, "CHECKPOINT_PATH", single_path)
        monkeypatch.setattr(session_mod, "_resolve_session_id", lambda: "")

        cp = _load_checkpoint_best_effort()
        assert cp is not None
        assert cp["task"]["status"] == "awaiting_user_input"

    def test_only_session_scoped_loads_it(self, tmp_path, monkeypatch):
        """只有 session-scoped checkpoint 存在时加载它。"""
        from agent.session import _load_checkpoint_best_effort

        sid = "session-only"
        session_dir = tmp_path / "checkpoints"
        single_path = tmp_path / "checkpoint.json"
        state = _make_state(status="awaiting_plan_confirmation")
        _write_session_checkpoint(sid, "run-1", session_dir, state)

        import agent.checkpoint as ckpt
        import agent.session as session_mod

        monkeypatch.setattr(ckpt, "CHECKPOINT_PATH", single_path)
        monkeypatch.setattr(session_mod, "_resolve_session_id", lambda: sid)

        def _mock_cp(s, r):
            return session_dir / s / f"{r}.json"
        monkeypatch.setattr(session_mod, "checkpoint_path", _mock_cp)

        cp = _load_checkpoint_best_effort()
        assert cp is not None
        assert cp["task"]["status"] == "awaiting_plan_confirmation"

    # ── mtime 选择 ──────────────────────────────────────────────

    def test_single_file_newer_than_session_scoped(self, tmp_path, monkeypatch):
        """single-file 比 session-scoped 更新时加载 single-file
        （修复前会错误加载 session-scoped）。"""
        from agent.session import _load_checkpoint_best_effort

        sid = "session-split"
        session_dir = tmp_path / "checkpoints"
        single_path = tmp_path / "checkpoint.json"

        # session-scoped 先写（较旧）
        state_session = _make_state(status="idle")
        _write_session_checkpoint(sid, "run-old", session_dir, state_session)

        # single-file 后写（较新）—— 模拟 interrupt 发生在 session-scoped 写入之后
        state_single = _make_state(status="running")
        _write_single_file_checkpoint(state_single, single_path)
        # 确保 session-scoped 比 single-file 旧 10 秒
        _session_file = session_dir / sid / "run-old.json"
        _session_mtime = _session_file.stat().st_mtime
        _os.utime(str(_session_file), (_session_mtime - 10, _session_mtime - 10))

        import agent.checkpoint as ckpt
        import agent.session as session_mod

        monkeypatch.setattr(ckpt, "CHECKPOINT_PATH", single_path)
        monkeypatch.setattr(session_mod, "_resolve_session_id", lambda: sid)

        def _mock_cp(s, r):
            return session_dir / s / f"{r}.json"
        monkeypatch.setattr(session_mod, "checkpoint_path", _mock_cp)

        cp = _load_checkpoint_best_effort()
        assert cp is not None
        assert cp["task"]["status"] == "running", (
            f"应加载较新的 single-file (running)，而非较旧的 session-scoped (idle)。"
            f"实际加载: status={cp['task']['status']}"
        )

    def test_session_scoped_newer_than_single_file(self, tmp_path, monkeypatch):
        """session-scoped 比 single-file 更新时加载 session-scoped。"""
        from agent.session import _load_checkpoint_best_effort

        sid = "session-newer"
        session_dir = tmp_path / "checkpoints"
        single_path = tmp_path / "checkpoint.json"

        # single-file 先写（较旧）
        state_single = _make_state(status="idle")
        _write_single_file_checkpoint(state_single, single_path)

        # session-scoped 后写（较新）
        state_session = _make_state(status="awaiting_tool_confirmation")
        _write_session_checkpoint(sid, "run-new", session_dir, state_session)

        _single_mtime = single_path.stat().st_mtime
        _os.utime(str(single_path), (_single_mtime - 10, _single_mtime - 10))

        import agent.checkpoint as ckpt
        import agent.session as session_mod

        monkeypatch.setattr(ckpt, "CHECKPOINT_PATH", single_path)
        monkeypatch.setattr(session_mod, "_resolve_session_id", lambda: sid)

        def _mock_cp(s, r):
            return session_dir / s / f"{r}.json"
        monkeypatch.setattr(session_mod, "checkpoint_path", _mock_cp)

        cp = _load_checkpoint_best_effort()
        assert cp is not None
        assert cp["task"]["status"] == "awaiting_tool_confirmation"

    # ── 跨 session 隔离 ─────────────────────────────────────────

    def test_other_session_single_file_rejected(self, tmp_path, monkeypatch):
        """single-file 属于不同 session 且当前有 session-scoped 时，不加载 single-file。"""
        from agent.session import _load_checkpoint_best_effort

        current_sid = "session-current"
        other_sid = "session-other"
        session_dir = tmp_path / "checkpoints"
        single_path = tmp_path / "checkpoint.json"

        # single-file 属于 other session
        state_other = create_agent_state(system_prompt="test")
        state_other.task.status = "awaiting_user_input"
        state_other.memory.session_id = other_sid
        state_other.conversation.messages.append({"role": "user", "content": "x"})
        _write_single_file_checkpoint(state_other, single_path)

        # session-scoped 属于 current session（较旧，但 session 匹配优先）
        _session_file = _write_session_checkpoint(current_sid, "run-1", session_dir,
                                                   _make_state(status="running"))
        _session_mtime = _session_file.stat().st_mtime
        _os.utime(str(_session_file), (_session_mtime - 10, _session_mtime - 10))

        import agent.checkpoint as ckpt
        import agent.session as session_mod

        monkeypatch.setattr(ckpt, "CHECKPOINT_PATH", single_path)
        monkeypatch.setattr(session_mod, "_resolve_session_id", lambda: current_sid)

        def _mock_cp(s, r):
            return session_dir / s / f"{r}.json"
        monkeypatch.setattr(session_mod, "checkpoint_path", _mock_cp)

        cp = _load_checkpoint_best_effort()
        assert cp is not None
        # 不应加载 other session 的 single-file
        assert cp["meta"]["session_id"] == current_sid

    # ── 跨 session 拒绝（P2-1）──────────────────────────────────

    def test_single_file_from_other_session_rejected(self, tmp_path, monkeypatch):
        """P2-1: 无 session-scoped 时拒绝跨 session 的 single-file (contamination guard)"""
        from agent.session import _load_checkpoint_best_effort

        current_sid = "session-current"
        other_sid = "session-other"
        single_path = tmp_path / "checkpoint.json"
        session_dir = tmp_path / "checkpoints"

        # 只有 single-file checkpoint，属于 other session
        state_other = create_agent_state(system_prompt="test")
        state_other.task.status = "awaiting_user_input"
        state_other.memory.session_id = other_sid
        state_other.conversation.messages.append({"role": "user", "content": "x"})
        _write_single_file_checkpoint_with_session(state_other, single_path, other_sid)

        import agent.checkpoint as ckpt
        import agent.session as session_mod

        monkeypatch.setattr(ckpt, "CHECKPOINT_PATH", single_path)
        monkeypatch.setattr(session_mod, "_resolve_session_id", lambda: current_sid)

        def _mock_cp(s, r):
            return session_dir / s / f"{r}.json"
        monkeypatch.setattr(session_mod, "checkpoint_path", _mock_cp)

        cp = _load_checkpoint_best_effort()
        # P2-1: 不应加载 other session 的 checkpoint
        assert cp is None, (
            f"cross-session contamination: 不应将 {other_sid} 的 single-file "
            f"checkpoint 加载到 {current_sid}"
        )

    def test_single_file_matching_session_loads_when_no_session_scoped(self, tmp_path, monkeypatch):
        """P2-1 反例: 仅有当前 session 的 single-file checkpoint 时，正常加载。"""
        from agent.session import _load_checkpoint_best_effort

        current_sid = "session-current"
        single_path = tmp_path / "checkpoint.json"
        session_dir = tmp_path / "checkpoints"

        state = _make_state(status="running")
        _write_single_file_checkpoint_with_session(state, single_path, current_sid)

        import agent.checkpoint as ckpt
        import agent.session as session_mod

        monkeypatch.setattr(ckpt, "CHECKPOINT_PATH", single_path)
        monkeypatch.setattr(session_mod, "_resolve_session_id", lambda: current_sid)

        def _mock_cp(s, r):
            return session_dir / s / f"{r}.json"
        monkeypatch.setattr(session_mod, "checkpoint_path", _mock_cp)

        cp = _load_checkpoint_best_effort()
        assert cp is not None
        assert cp["task"]["status"] == "running"

    # ── 向后兼容 ────────────────────────────────────────────────

    def test_single_file_with_no_session_meta_still_loads(self, tmp_path, monkeypatch):
        """Legacy compatibility: single-file 缺少 session_id meta 且无 session-scoped 时回退。"""
        from agent.session import _load_checkpoint_best_effort

        single_path = tmp_path / "checkpoint.json"
        state = _make_state(status="running")

        # 手动构造一个不带 session_id 的 single-file checkpoint（模拟极早期数据）
        save_checkpoint(state, path=single_path)
        data = json.loads(single_path.read_text(encoding="utf-8"))
        meta = data.get("meta", {})
        if "session_id" in meta:
            del meta["session_id"]
        data["meta"] = meta
        single_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        import agent.checkpoint as ckpt
        import agent.session as session_mod

        monkeypatch.setattr(ckpt, "CHECKPOINT_PATH", single_path)
        monkeypatch.setattr(session_mod, "_resolve_session_id", lambda: "some-session")

        cp = _load_checkpoint_best_effort()
        assert cp is not None
        assert cp["task"]["status"] == "running"


# ── _load_checkpoint_to_state_best_effort 测试 ────────────────────────

class TestLoadCheckpointToStateBestEffort:
    """_load_checkpoint_to_state_best_effort() 的 scope 选择 + fallback 语义。"""

    def test_single_file_newer_than_session_scoped_loads_single_file(self, tmp_path, monkeypatch):
        """single-file 比 session-scoped 更新时恢复到 single-file state。"""
        from agent.session import _load_checkpoint_to_state_best_effort

        sid = "session-lcts-newer"
        session_dir = tmp_path / "checkpoints"
        single_path = tmp_path / "checkpoint.json"

        # session-scoped 先写（较旧）
        state_session = _make_state(status="idle")
        _write_session_checkpoint(sid, "run-old", session_dir, state_session)

        # single-file 后写（较新）
        state_single = _make_state(status="awaiting_user_input")
        _write_single_file_checkpoint(state_single, single_path)

        _session_file = session_dir / sid / "run-old.json"
        _session_mtime = _session_file.stat().st_mtime
        _os.utime(str(_session_file), (_session_mtime - 10, _session_mtime - 10))

        import agent.checkpoint as ckpt
        import agent.session as session_mod

        monkeypatch.setattr(ckpt, "CHECKPOINT_PATH", single_path)
        monkeypatch.setattr(session_mod, "_resolve_session_id", lambda: sid)

        def _mock_cp(s, r):
            return session_dir / s / f"{r}.json"
        monkeypatch.setattr(session_mod, "checkpoint_path", _mock_cp)

        dst = create_agent_state(system_prompt="test")
        restored = _load_checkpoint_to_state_best_effort(dst)
        assert restored is True
        assert dst.task.status == "awaiting_user_input"

    # ── P2-2: session-scoped fallback ───────────────────────────

    def test_corrupted_newest_session_scoped_falls_back_to_older(self, tmp_path, monkeypatch):
        """P2-2: 最新 session-scoped checkpoint 损坏时，回退到较旧可用 checkpoint。"""
        from agent.session import _load_checkpoint_to_state_best_effort

        sid = "session-fallback"
        session_dir = tmp_path / "checkpoints"
        single_path = tmp_path / "checkpoint.json"

        # 较旧的可用 session-scoped checkpoint
        state_old = _make_state(status="awaiting_user_input")
        _write_session_checkpoint(sid, "run-old", session_dir, state_old)

        # 最新的损坏 session-scoped checkpoint
        _write_corrupted_session_checkpoint(sid, "run-corrupt", session_dir)

        import agent.checkpoint as ckpt
        import agent.session as session_mod

        # 确保 CHECKPOINT_PATH 不存在（无 single-file）
        monkeypatch.setattr(ckpt, "CHECKPOINT_PATH", single_path)

        monkeypatch.setattr(session_mod, "_resolve_session_id", lambda: sid)

        def _mock_cp(s, r):
            return session_dir / s / f"{r}.json"
        monkeypatch.setattr(session_mod, "checkpoint_path", _mock_cp)

        dst = create_agent_state(system_prompt="test")
        restored = _load_checkpoint_to_state_best_effort(dst)
        assert restored is True, "应跳过损坏 checkpoint 并加载较旧可用 checkpoint"
        assert dst.task.status == "awaiting_user_input"

    def test_all_session_scoped_corrupted_falls_back(self, tmp_path, monkeypatch):
        """P2-2: 所有 session-scoped 损坏时 fallback 到 session 匹配的 single-file。"""
        from agent.session import _load_checkpoint_to_state_best_effort

        sid = "session-all-corrupt"
        session_dir = tmp_path / "checkpoints"
        single_path = tmp_path / "checkpoint.json"

        # 所有 session-scoped 都损坏
        _write_corrupted_session_checkpoint(sid, "run-1", session_dir)
        _write_corrupted_session_checkpoint(sid, "run-2", session_dir)

        # single-file 属于当前 session
        state_single = _make_state(status="awaiting_user_input")
        _write_single_file_checkpoint_with_session(state_single, single_path, sid)

        import agent.checkpoint as ckpt
        import agent.session as session_mod

        monkeypatch.setattr(ckpt, "CHECKPOINT_PATH", single_path)
        monkeypatch.setattr(session_mod, "_resolve_session_id", lambda: sid)

        def _mock_cp(s, r):
            return session_dir / s / f"{r}.json"
        monkeypatch.setattr(session_mod, "checkpoint_path", _mock_cp)

        dst = create_agent_state(system_prompt="test")
        restored = _load_checkpoint_to_state_best_effort(dst)
        assert restored is True, "所有 session-scoped 损坏时应 fallback 到 single-file"
        assert dst.task.status == "awaiting_user_input"

    # ── P2-1: cross-session 拒绝 ───────────────────────────────

    def test_single_file_from_other_session_rejected_to_state(self, tmp_path, monkeypatch):
        """P2-1: 仅有其他 session 的 single-file 时，
        _load_checkpoint_to_state_best_effort 应拒绝。"""
        from agent.session import _load_checkpoint_to_state_best_effort

        current_sid = "session-current"
        other_sid = "session-other"
        single_path = tmp_path / "checkpoint.json"
        session_dir = tmp_path / "checkpoints"

        state_other = create_agent_state(system_prompt="test")
        state_other.task.status = "awaiting_user_input"
        state_other.memory.session_id = other_sid
        state_other.conversation.messages.append({"role": "user", "content": "x"})
        _write_single_file_checkpoint_with_session(state_other, single_path, other_sid)

        import agent.checkpoint as ckpt
        import agent.session as session_mod

        monkeypatch.setattr(ckpt, "CHECKPOINT_PATH", single_path)
        monkeypatch.setattr(session_mod, "_resolve_session_id", lambda: current_sid)

        def _mock_cp(s, r):
            return session_dir / s / f"{r}.json"
        monkeypatch.setattr(session_mod, "checkpoint_path", _mock_cp)

        dst = create_agent_state(system_prompt="test")
        restored = _load_checkpoint_to_state_best_effort(dst)
        assert restored is False, (
            f"cross-session contamination: 不应将 {other_sid} 的 single-file "
            f"checkpoint 恢复到 {current_sid}"
        )


# ── 端到端：interrupt save → resume 加载最新状态 ──────────────────────

class TestInterruptResumeEndToEnd:
    """interrupt save (single-file) → resume 应加载 interrupt 时的最新状态。"""

    def test_interrupt_save_then_resume_loads_interrupt_state(self, tmp_path, monkeypatch):
        """E2E: turn-end 写 session-scoped → interrupt 写 single-file
        → resume 加载 single-file (最新)。"""
        from agent.session import _load_checkpoint_to_state_best_effort

        sid = "session-e2e"
        session_dir = tmp_path / "checkpoints"
        single_path = tmp_path / "checkpoint.json"

        # Step 1: turn-end 写 session-scoped checkpoint（较旧）
        state_turn_end = _make_state(status="awaiting_user_input")
        _write_session_checkpoint(sid, "run-turn-end", session_dir, state_turn_end)

        # Step 2: 用户继续对话，模型返回后 interrupt 写 single-file（较新）
        state_interrupt = _make_state(status="running")
        state_interrupt.conversation.messages.append(
            {"role": "assistant", "content": "interrupted response"}
        )
        _write_single_file_checkpoint(state_interrupt, single_path)

        _session_file = session_dir / sid / "run-turn-end.json"
        _session_mtime = _session_file.stat().st_mtime
        _os.utime(str(_session_file), (_session_mtime - 10, _session_mtime - 10))

        import agent.checkpoint as ckpt
        import agent.session as session_mod

        monkeypatch.setattr(ckpt, "CHECKPOINT_PATH", single_path)
        monkeypatch.setattr(session_mod, "_resolve_session_id", lambda: sid)

        def _mock_cp(s, r):
            return session_dir / s / f"{r}.json"
        monkeypatch.setattr(session_mod, "checkpoint_path", _mock_cp)

        # Step 3: resume
        dst = create_agent_state(system_prompt="test")
        restored = _load_checkpoint_to_state_best_effort(dst)
        assert restored is True

        # 应恢复 interrupt 时的状态（running + 2 messages），
        # 而非 turn-end 时的状态（awaiting_user_input + 1 message）
        assert dst.task.status == "running", (
            f"应恢复 interrupt 状态 (running)，而非 turn-end 状态。"
            f"实际: {dst.task.status}"
        )
        assert len(dst.conversation.messages) == 2, (
            f"应有 2 条消息（包含 interrupted response），"
            f"实际: {len(dst.conversation.messages)}"
        )
