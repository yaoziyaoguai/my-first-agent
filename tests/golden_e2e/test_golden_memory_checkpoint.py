"""GE-1 Phase B: memory 与 checkpoint 当前能力的 Golden E2E。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).with_name("fixtures")


def _assert_golden(name: str, actual: dict) -> None:
    path = FIXTURE_DIR / name
    assert path.is_file(), f"missing golden fixture: {path}"
    expected = json.loads(path.read_text(encoding="utf-8"))
    assert actual == expected


class _UnreadableStore:
    """默认关闭的 memory gate 不应触碰任何持久化 store。"""

    def list_records(self):
        raise AssertionError("disabled memory gate must not read the store")


def test_ge1_b1_memory_is_frozen_and_env_gated_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Golden-lock memory consolidation/emergence 的默认关闭事实。"""
    from agent import memory_consolidation_pipeline
    from agent.memory_runtime_hooks import (
        _maybe_run_consolidation,
        _maybe_run_emergence,
    )

    monkeypatch.delenv("MEMORY_CONSOLIDATION_ENABLED", raising=False)
    monkeypatch.delenv("MEMORY_EMERGENCE_ENABLED", raising=False)

    store = _UnreadableStore()
    consolidation = _maybe_run_consolidation(store, {})
    emergence = _maybe_run_emergence(store, {})

    actual = {
        "consolidation": {
            "state": "frozen_env_gated",
            "module_frozen": "FROZEN (2026-05-25)"
            in (memory_consolidation_pipeline.__doc__ or ""),
            "enabled": consolidation["enabled"],
            "direct_store_write": consolidation.get("direct_store_write", False),
        },
        "emergence": {
            "state": "disabled_by_env",
            "enabled": emergence["enabled"],
            "gate_reason": emergence["gate_reason"],
            "direct_store_write": emergence["direct_store_write"],
        },
    }
    _assert_golden("memory_disabled.json", actual)


def test_ge1_b2_checkpoint_local_roundtrip_restores_current_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Golden-lock 当前 local-file / intra-process checkpoint roundtrip。"""
    from agent import logger
    from agent.checkpoint import (
        load_checkpoint,
        load_checkpoint_to_state,
        save_checkpoint,
    )
    from agent.state import create_agent_state

    monkeypatch.setattr(logger, "log_event", lambda *args, **kwargs: None)

    checkpoint_path = tmp_path / "checkpoint.json"
    source = create_agent_state(system_prompt="golden-source")
    source.task.user_goal = "GE-1 checkpoint golden"
    source.task.status = "running"
    source.task.current_step_index = 1
    source.memory.working_summary = "local checkpoint summary"
    source.conversation.messages = [
        {"role": "user", "content": "resume this task"},
        {"role": "assistant", "content": "checkpoint saved"},
    ]

    save_checkpoint(
        source,
        source="golden.ge1_b2",
        path=checkpoint_path,
    )
    persisted = load_checkpoint(path=checkpoint_path)

    restored = create_agent_state(system_prompt="golden-restored")
    loaded = load_checkpoint_to_state(restored, path=checkpoint_path)

    actual = {
        "capability_scope": "local_file_intra_process",
        "checkpoint_exists": checkpoint_path.is_file(),
        "schema_version": persisted["meta"]["schema_version"] if persisted else None,
        "load_succeeded": loaded,
        "task": {
            "user_goal": restored.task.user_goal,
            "status": restored.task.status,
            "current_step_index": restored.task.current_step_index,
        },
        "memory": {
            "working_summary": restored.memory.working_summary,
        },
        "conversation_message_count": len(restored.conversation.messages),
    }
    _assert_golden("checkpoint_local_roundtrip.json", actual)
