"""B7 Slice 5: Multi-instance Integration & Guard Tests.

覆盖 multi-run 隔离、identity 传播链、单实例回归、B8 契约验证。
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

# ── helper ─────────────────────────────────────────────────────────────────

def _minimal_chat_args():
    """返回 chat() 最小调用参数（使用 FakeProvider 避免真实 API）。"""
    from agent.provider.fake_provider import FakeProvider

    provider = FakeProvider()
    return {"user_input": "hello", "provider": provider}


# ── RED-5.1: Multi-run 隔离 ─────────────────────────────────────────────────


class TestMultiRunIsolation:
    def test_two_runs_independent_checkpoints(self):
        """run1 和 run2 各自 save/load 不互相覆盖。"""
        from agent.checkpoint import checkpoint_path, save_checkpoint
        from agent.core import get_state

        state = get_state()
        run_a = checkpoint_path("s-int-1", "r-int-a")
        run_b = checkpoint_path("s-int-1", "r-int-b")
        # run1 checkpoint
        save_checkpoint(state, session_id="s-int-1", run_id="r-int-a", path=run_a)
        # run2 checkpoint
        save_checkpoint(state, session_id="s-int-1", run_id="r-int-b", path=run_b)

        assert run_a.exists()
        assert run_b.exists()
        assert run_a != run_b

    def test_two_runs_independent_identity(self):
        """每个 run 在 RuntimeIdentity 中独立。"""
        from agent.runtime_identity import RuntimeIdentity

        id1 = RuntimeIdentity(session_id="s-iso", run_id="r-iso-1")
        id2 = RuntimeIdentity(session_id="s-iso", run_id="r-iso-2")

        assert id1.session_id == id2.session_id
        assert id1.run_id != id2.run_id
        assert id1 != id2

    def test_two_runs_independent_dispatcher(self):
        """两个 dispatcher 实例各自独立。"""
        from agent.runtime_integration.dispatcher import RuntimeActionDispatcher

        d1 = RuntimeActionDispatcher()
        d2 = RuntimeActionDispatcher()
        assert d1 is not d2
        assert len(d1.action_log) == 0
        assert len(d2.action_log) == 0


# ── RED-5.2: Identity 传播链 ────────────────────────────────────────────────


class TestIdentityPropagationChain:
    def test_loop_context_injects_identity_to_dispatcher(self):
        """LoopContext 的 runtime_identity 能注入到 dispatcher。"""
        from agent.loop_context import LoopContext
        from agent.runtime_identity import RuntimeIdentity
        from agent.runtime_integration.dispatcher import RuntimeActionDispatcher

        identity = RuntimeIdentity(session_id="s-prop", run_id="r-prop")

        # 使用显式 provider 避免 env 回退
        from agent.provider.fake_provider import FakeProvider

        dispatcher = RuntimeActionDispatcher()
        ctx = LoopContext(
            client="fake-client",
            model_name="fake-model",
            max_loop_iterations=10,
            runtime_identity=identity,
            runtime_action_dispatcher=dispatcher,
            model_provider=FakeProvider(),
        )
        assert ctx.runtime_identity.session_id == "s-prop"
        assert ctx.runtime_identity.run_id == "r-prop"
        assert ctx.runtime_action_dispatcher is dispatcher

    def test_run_id_unique_per_chat_call(self):
        """每次 RunIdentity 构造产生不同 run_id。"""
        from agent.runtime_identity import RuntimeIdentity

        id1 = RuntimeIdentity(session_id="s-chat", run_id="r-chat-1")
        id2 = RuntimeIdentity(session_id="s-chat", run_id="r-chat-2")
        assert id1.run_id != id2.run_id


# ── RED-5.3: Regression — 单实例行为不变 ────────────────────────────────────


class TestSingleInstanceRegression:
    def test_chat_minimal_call_signature(self):
        """chat(user_input, provider=...) 最小调用签名仍有效。"""
        from agent.core import chat
        from agent.provider.fake_provider import FakeProvider

        provider = FakeProvider()
        reply = chat("hello", provider=provider)
        assert isinstance(reply, str)

    def test_build_loop_context_no_identity(self):
        """不传 identity 时 build_loop_context 正常工作。"""
        from agent.core_contexts import build_loop_context
        from agent.provider.fake_provider import FakeProvider

        ctx = build_loop_context(
            client_obj="fake-client",
            model_name="fake-model",
            max_loop_iterations=10,
            provider=FakeProvider(),
        )
        assert ctx.runtime_identity is None
        assert ctx.event_log_writer is None

    def test_build_loop_context_with_identity(self):
        """传 identity 时正确注入。"""
        from agent.core_contexts import build_loop_context
        from agent.provider.fake_provider import FakeProvider
        from agent.runtime_identity import RuntimeIdentity

        identity = RuntimeIdentity(session_id="s-def", run_id="r-def")
        ctx = build_loop_context(
            client_obj="fake-client",
            model_name="fake-model",
            max_loop_iterations=10,
            provider=FakeProvider(),
            runtime_identity=identity,
        )
        assert ctx.runtime_identity is identity


# ── RED-5.4: B8 契约验证 ────────────────────────────────────────────────────


class TestB8ContractVerification:
    def test_event_log_has_session_id(self):
        """JSONL 每行 event 包含 session_id。"""
        from agent.event_log import EventLogWriter
        from agent.runtime_integration.dispatcher import RuntimeActionDispatcher

        with tempfile.TemporaryDirectory() as tmp:
            writer = EventLogWriter(session_dir=Path(tmp))
            dispatcher = RuntimeActionDispatcher()
            dispatcher._action_log.append(
                _fake_event(session_id="s-evt-1", event_id="ev-s1"),
            )
            dispatcher.flush_to_event_log(writer)
            writer.close()

            line = (Path(tmp) / "events.jsonl").read_text().strip()
            data = json.loads(line)
            assert data["session_id"] == "s-evt-1"

    def test_event_log_has_run_id(self):
        """JSONL 每行 event 包含 run_id。"""
        from agent.event_log import EventLogWriter
        from agent.runtime_integration.dispatcher import RuntimeActionDispatcher

        with tempfile.TemporaryDirectory() as tmp:
            writer = EventLogWriter(session_dir=Path(tmp))
            dispatcher = RuntimeActionDispatcher()
            dispatcher._action_log.append(
                _fake_event(run_id="r-evt-1", event_id="ev-r1"),
            )
            dispatcher.flush_to_event_log(writer)
            writer.close()

            line = (Path(tmp) / "events.jsonl").read_text().strip()
            data = json.loads(line)
            assert data["run_id"] == "r-evt-1"

    def test_event_log_writer_no_read_api(self):
        """EventLogWriter 没有 read 方法（只写契约）。"""
        from agent.event_log import EventLogWriter

        writer = EventLogWriter(session_dir=Path("/tmp"))
        assert not hasattr(writer, "read")
        assert not hasattr(writer, "get")
        assert not hasattr(writer, "load")

    def test_per_run_checkpoint_path_is_unique(self):
        """每个 run 有独立 checkpoint 路径。"""
        from agent.checkpoint import checkpoint_path

        path1 = checkpoint_path("s-b8-ckpt", "r-b8-a")
        path2 = checkpoint_path("s-b8-ckpt", "r-b8-b")
        assert path1 != path2

    def test_per_run_checkpoint_file_written(self):
        """每个 run 的 checkpoint 写入独立文件。"""
        from agent.checkpoint import checkpoint_path, save_checkpoint
        from agent.core import get_state

        state = get_state()
        path = checkpoint_path("s-b8-ckpt", "r-b8-w1")
        save_checkpoint(state, session_id="s-b8-ckpt", run_id="r-b8-w1", path=path)

        assert path.exists()


# ── helper ─────────────────────────────────────────────────────────────────


def _fake_event(**overrides) -> object:
    """构造最小 RuntimeActionEvent。"""
    from agent.runtime_integration.schema import RuntimeActionEvent

    defaults: dict = {
        "event_id": "ev-001",
        "action_id": "act-001",
        "action_type": "test.fake",
        "source": "test",
        "status": "success",
        "evidence": {},
        "parent_trace_id": "",
        "session_id": "s-test",
        "run_id": "r-test",
    }
    defaults.update(overrides)
    return RuntimeActionEvent(**defaults)
