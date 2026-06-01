"""B7 Slice 3: Checkpoint Namespace — per-run path + schema v2.

覆盖 U9 checkpoint per-run path、v2 schema、v1 向后兼容、resume。
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from agent.state import AgentState, RuntimeState


def _make_state(**kwargs: object) -> AgentState:
    """构造测试用 AgentState，注入最小 RuntimeState。"""
    return AgentState(runtime=RuntimeState(system_prompt="test"), **kwargs)


# ── RED-3.1: Per-run checkpoint path ──────────────────────────────────────


class TestPerRunCheckpointPath:
    def test_checkpoint_path_includes_session_and_run(self):
        """checkpoint_path(session_id, run_id) 返回包含 session/run 的路径。"""
        from agent.checkpoint import checkpoint_path
        result = checkpoint_path(session_id="s1", run_id="r1")
        assert isinstance(result, Path)
        assert "s1" in str(result)
        assert "r1" in str(result)

    def test_checkpoint_save_creates_parent_dirs(self):
        """per-run checkpoint 保存时自动创建父目录。"""
        from agent.checkpoint import save_checkpoint

        with tempfile.TemporaryDirectory() as tmp:
            state = _make_state()
            run_path = Path(tmp) / "checkpoints" / "s-test" / "r-test.json"
            assert not run_path.parent.exists()

            save_checkpoint(
                state,
                session_id="s-test",
                run_id="r-test",
                path=run_path,
            )
            assert run_path.parent.exists()
            assert run_path.exists()

    def test_two_runs_dont_overwrite(self):
        """run1 和 run2 的 checkpoint 在独立文件中，互不覆盖。"""
        from agent.checkpoint import save_checkpoint

        with tempfile.TemporaryDirectory() as tmp:
            state1 = _make_state()
            state2 = _make_state()

            path1 = Path(tmp) / "checkpoints" / "s-x" / "run1.json"
            path2 = Path(tmp) / "checkpoints" / "s-x" / "run2.json"

            save_checkpoint(state1, session_id="s-x", run_id="run1", path=path1)
            save_checkpoint(state2, session_id="s-x", run_id="run2", path=path2)

            assert path1.exists()
            assert path2.exists()
            assert path1.read_text() != path2.read_text()


# ── RED-3.2: Schema v2 ───────────────────────────────────────────────────


class TestCheckpointSchemaV2:
    def test_v2_schema_includes_identity(self):
        """v2 checkpoint JSON 包含 session_id / run_id / created_at / updated_at。"""
        from agent.checkpoint import save_checkpoint

        with tempfile.TemporaryDirectory() as tmp:
            state = _make_state()
            path = Path(tmp) / "test_v2.json"

            save_checkpoint(
                state,
                session_id="s-v2",
                run_id="r-v2",
                path=path,
            )

            data = json.loads(path.read_text())
            meta = data.get("meta", {})
            assert meta.get("session_id") == "s-v2"
            assert meta.get("run_id") == "r-v2"
            assert "created_at" in meta
            assert "updated_at" in meta or "interrupted_at" in meta

    def test_v2_schema_includes_v1_fields(self):
        """v2 schema 包含 v1 所有字段（task / conversation / memory）。"""
        from agent.checkpoint import save_checkpoint

        with tempfile.TemporaryDirectory() as tmp:
            state = _make_state()
            state.task.user_goal = "test goal"
            path = Path(tmp) / "test_v2_fields.json"

            save_checkpoint(
                state,
                session_id="s-v2",
                run_id="r-v2",
                path=path,
            )

            data = json.loads(path.read_text())
            assert "task" in data
            assert "conversation" in data
            assert "memory" in data
            assert data["task"].get("user_goal") == "test goal"

    def test_v2_schema_version_field(self):
        """v2 checkpoint 的 schema_version == "checkpoint.v2"。"""
        from agent.checkpoint import save_checkpoint

        with tempfile.TemporaryDirectory() as tmp:
            state = _make_state()
            path = Path(tmp) / "test_v2_version.json"

            save_checkpoint(
                state,
                session_id="s-v2",
                run_id="r-v2",
                path=path,
            )

            data = json.loads(path.read_text())
            assert data["meta"]["schema_version"] == "checkpoint.v2"


# ── RED-3.3: v1 向后兼容 ───────────────────────────────────────────────────


class TestCheckpointV1BackwardCompat:
    def test_load_v1_checkpoint_does_not_crash(self):
        """旧 v1 checkpoint（memory/checkpoint.json）仍可加载。"""
        with tempfile.TemporaryDirectory() as tmp:
            v1_path = Path(tmp) / "checkpoint.json"
            v1_path.write_text(json.dumps({
                "meta": {"schema_version": "checkpoint.v1"},
                "task": {"user_goal": "old task", "status": "idle"},
                "memory": {},
                "conversation": {"messages": []},
            }))

            from agent.checkpoint import load_checkpoint
            result = load_checkpoint(path=v1_path)
            assert result is not None
            assert result["meta"]["schema_version"] == "checkpoint.v1"

    def test_v1_checkpoint_missing_identity_defaults(self):
        """加载 v1 checkpoint 时 session_id / run_id 使用空默认值。"""
        with tempfile.TemporaryDirectory() as tmp:
            v1_path = Path(tmp) / "checkpoint.json"
            v1_path.write_text(json.dumps({
                "meta": {"schema_version": "checkpoint.v1"},
                "task": {},
                "memory": {},
                "conversation": {"messages": []},
            }))

            from agent.checkpoint import load_checkpoint
            result = load_checkpoint(path=v1_path)
            assert result is not None
            # v1 checkpoint 无 session_id / run_id，应安全处理


# ── RED-3.4: Resume ──────────────────────────────────────────────────────


class TestCheckpointResume:
    def test_resume_finds_specific_session_and_run(self):
        """指定 session_id + run_id 时精确恢复对应 checkpoint。"""
        from agent.checkpoint import load_checkpoint, save_checkpoint

        with tempfile.TemporaryDirectory() as tmp:
            state_a = _make_state()
            state_a.task.user_goal = "task-a"
            state_b = _make_state()
            state_b.task.user_goal = "task-b"

            path_a = Path(tmp) / "checkpoints" / "s-a" / "run-a.json"
            path_b = Path(tmp) / "checkpoints" / "s-b" / "run-b.json"

            save_checkpoint(state_a, session_id="s-a", run_id="run-a", path=path_a)
            save_checkpoint(state_b, session_id="s-b", run_id="run-b", path=path_b)

            loaded_a = load_checkpoint(path=path_a)
            loaded_b = load_checkpoint(path=path_b)
            assert loaded_a is not None
            assert loaded_b is not None
            assert loaded_a["task"]["user_goal"] == "task-a"
            assert loaded_b["task"]["user_goal"] == "task-b"

    def test_clear_checkpoint_per_namespace(self):
        """clear_checkpoint 只清除指定 path 的 checkpoint。"""
        from agent.checkpoint import clear_checkpoint, save_checkpoint

        with tempfile.TemporaryDirectory() as tmp:
            state = _make_state()
            path_a = Path(tmp) / "checkpoints" / "s-a" / "run-a.json"
            path_b = Path(tmp) / "checkpoints" / "s-b" / "run-b.json"

            save_checkpoint(state, session_id="s-a", run_id="run-a", path=path_a)
            save_checkpoint(state, session_id="s-b", run_id="run-b", path=path_b)

            clear_checkpoint(path=path_a)
            assert not path_a.exists()
            assert path_b.exists()
