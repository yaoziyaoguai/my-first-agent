"""Phase 4: Checkpoint v2 per-run namespace 测试。

验证 production save/load 使用 session/run namespace。
"""
from __future__ import annotations

import json
from pathlib import Path

from agent.checkpoint import (
    checkpoint_path,
    load_checkpoint,
    save_checkpoint,
)
from agent.runtime_identity import RuntimeIdentity


class TestSaveCheckpointV2Path:
    """save_checkpoint 使用 v2 per-run 路径。"""

    def test_v2_path_when_session_and_run_id_provided(self, fresh_state, monkeypatch):
        """session_id + run_id 均非空时，保存到 memory/checkpoints/{sid}/{rid}.json。"""
        sid, rid = "s1", "r1"
        save_checkpoint(fresh_state, session_id=sid, run_id=rid)

        expected = checkpoint_path(sid, rid)
        assert expected.exists(), f"v2 checkpoint 应保存到 {expected}"

    def test_v1_path_when_session_id_empty(self, fresh_state, tmp_path, monkeypatch):
        """session_id 为空时回退 v1 路径。"""
        import agent.checkpoint as ckpt

        v1_path = tmp_path / "checkpoint.json"
        monkeypatch.setattr(ckpt, "CHECKPOINT_PATH", v1_path)

        save_checkpoint(fresh_state, session_id="", run_id="r1")

        assert v1_path.exists(), "session_id 为空时应回退 v1"

    def test_v1_path_when_run_id_empty(self, fresh_state, tmp_path, monkeypatch):
        """run_id 为空时回退 v1 路径。"""
        import agent.checkpoint as ckpt

        v1_path = tmp_path / "checkpoint.json"
        monkeypatch.setattr(ckpt, "CHECKPOINT_PATH", v1_path)

        save_checkpoint(fresh_state, session_id="s1", run_id="")

        assert v1_path.exists(), "run_id 为空时应回退 v1"

    def test_v2_schema_includes_identity_fields(self, fresh_state):
        """v2 checkpoint 的 meta 包含 session_id/run_id/schema_version/updated_at。"""
        sid, rid = "s2", "r2"
        save_checkpoint(fresh_state, session_id=sid, run_id=rid)

        path = checkpoint_path(sid, rid)
        data = json.loads(path.read_text(encoding="utf-8"))
        meta = data["meta"]

        assert meta["schema_version"] == "checkpoint.v2"
        assert meta["session_id"] == sid
        assert meta["run_id"] == rid
        assert "updated_at" in meta

    def test_explicit_path_overrides_v2_derivation(self, fresh_state, tmp_path):
        """显式传 path 时使用显式路径，不自动推导 v2 路径。"""
        custom = tmp_path / "custom_checkpoint.json"
        save_checkpoint(fresh_state, path=custom, session_id="s", run_id="r")

        assert custom.exists()
        assert not checkpoint_path("s", "r").exists()


class TestLoadCheckpointBackwardCompat:
    """加载时 v1 向后兼容。"""

    def test_load_v1_path_when_v2_not_present(self, fresh_state, tmp_path, monkeypatch):
        """v2 路径不存在时，正常加载 v1 checkpoint。"""
        import agent.checkpoint as ckpt

        v1_path = tmp_path / "checkpoint.json"
        monkeypatch.setattr(ckpt, "CHECKPOINT_PATH", v1_path)

        save_checkpoint(fresh_state, path=v1_path)
        loaded = load_checkpoint()

        assert loaded is not None
        assert loaded["meta"]["schema_version"] == "checkpoint.v1"


class TestCheckpointSaveHandlerIdentity:
    """CheckpointSaveHandler 从 context.identity 提取 session_id/run_id。"""

    def test_context_stores_identity_for_handler_access(self):
        """RuntimeActionContext.identity 字段对 handler 可见。"""
        from agent.runtime_integration.dispatcher import RuntimeActionContext
        from agent.runtime_integration.schema import RuntimeActionType

        identity = RuntimeIdentity(session_id="test-s", run_id="test-r", instance_id="test-i")
        context = RuntimeActionContext(
            action_id="a1",
            action_type=RuntimeActionType.CHECKPOINT_SAVE,
            route_id="r1",
            handler_name="CheckpointSaveHandler",
            handler_identity="test",
            parent_trace_id="",
            observer=None,
            identity=identity,
        )

        assert context.identity is identity
        assert context.identity.session_id == "test-s"
        assert context.identity.run_id == "test-r"

    def test_context_identity_none_by_default(self):
        """未传 identity 时 context.identity 为 None。"""
        from agent.runtime_integration.dispatcher import RuntimeActionContext
        from agent.runtime_integration.schema import RuntimeActionType

        context = RuntimeActionContext(
            action_id="a2",
            action_type=RuntimeActionType.CHECKPOINT_SAVE,
            route_id="r2",
            handler_name="CheckpointSaveHandler",
            handler_identity="test",
            parent_trace_id="",
            observer=None,
        )

        assert context.identity is None

    def test_handler_extracts_session_id_and_run_id_from_identity(self, fresh_state):
        """handler 将 context.identity 的 session_id/run_id 写入 save_checkpoint。"""
        import agent.checkpoint as ckpt
        from agent.runtime_integration.dispatcher import RuntimeActionContext
        from agent.runtime_integration.schema import RuntimeActionType

        identity = RuntimeIdentity(session_id="h-s", run_id="h-r", instance_id="h-i")

        import tempfile
        with tempfile.TemporaryDirectory() as td:
            import agent.checkpoint
            orig = agent.checkpoint.checkpoint_path

            def _tmp_path(sid, rid):
                return Path(td) / "checkpoints" / sid / f"{rid}.json"

            agent.checkpoint.checkpoint_path = _tmp_path  # type: ignore[assignment]

            try:
                context = RuntimeActionContext(
                    action_id="a1",
                    action_type=RuntimeActionType.CHECKPOINT_SAVE,
                    route_id="r1",
                    handler_name="CheckpointSaveHandler",
                    handler_identity="test",
                    parent_trace_id="",
                    observer=None,
                    identity=identity,
                )

                _identity = context.identity
                assert _identity is not None
                _sid = getattr(_identity, "session_id", "") or ""
                _rid = getattr(_identity, "run_id", "") or ""

                assert _sid == "h-s"
                assert _rid == "h-r"

                # 验证 save_checkpoint 使用 identity 写 v2 路径
                ckpt.save_checkpoint(fresh_state, session_id=_sid, run_id=_rid)
                expected = _tmp_path(_sid, _rid)
                assert expected.exists(), (
                    f"save_checkpoint 应使用 identity 的 session_id/run_id 写 v2，"
                    f"期望路径: {expected}"
                )
            finally:
                agent.checkpoint.checkpoint_path = orig  # type: ignore[assignment]


class TestCheckpointPathNoCrossRunContamination:
    """不同 run 的 checkpoint 互不污染。"""

    def test_two_runs_use_different_paths(self, fresh_state):
        """两个不同 run 写到不同文件路径。"""
        save_checkpoint(fresh_state, session_id="s", run_id="r1")
        save_checkpoint(fresh_state, session_id="s", run_id="r2")

        p1 = checkpoint_path("s", "r1")
        p2 = checkpoint_path("s", "r2")
        assert p1 != p2, "不同 run 必须不同路径"
        assert p1.exists() and p2.exists()

    def test_two_sessions_use_different_dirs(self, fresh_state):
        """两个不同 session 写到不同目录。"""
        save_checkpoint(fresh_state, session_id="sA", run_id="r")
        save_checkpoint(fresh_state, session_id="sB", run_id="r")

        dir_a = checkpoint_path("sA", "r").parent
        dir_b = checkpoint_path("sB", "r").parent
        assert dir_a != dir_b, "不同 session 必须不同目录"
        assert dir_a.exists() and dir_b.exists()
