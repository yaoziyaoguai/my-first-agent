"""Skill memory_scope recall enforcement tests for Memory v0."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from typing import Any

import pytest

from agent.memory_confirmation import MemoryConfirmationChoice, MemoryConfirmationStatus
from agent.memory_contracts import MemoryDecisionType, MemoryScope
from agent.memory_operations import (
    MemoryOperationIntent,
    MemoryOperationType,
    build_memory_audit_summary,
)
from agent.memory_store import InMemoryMemoryStore
from agent.runtime_integration import (
    ActionHandlerRegistry,
    RuntimeActionDispatcher,
    RuntimeActionType,
)
from agent.runtime_integration.memory_recall import MemoryRecallHandler
from agent.skill_system.lifecycle import get_default_lifecycle, reset_default_lifecycle
from agent.skill_system.registry import SkillRegistry


@pytest.fixture(autouse=True)
def _reset_lifecycle() -> None:
    reset_default_lifecycle()
    yield
    reset_default_lifecycle()


def _write_skill(root: Path, name: str, *, memory_scope: str) -> None:
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        dedent(
            f"""
            ---
            name: {name}
            description: Skill memory scope test fixture
            version: 0.1.0
            status: active
            risk_level: low
            allowed_tools:
              - read_file
            memory_scope: {memory_scope}
            ---

            # {name}

            Test skill body.
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )


def _registry(tmp_path: Path, *, scope: str) -> SkillRegistry:
    root = tmp_path / f"skills-{scope}"
    _write_skill(root, f"skill-{scope.replace('_', '-')}", memory_scope=scope)
    return SkillRegistry(roots=[root])


def _activate(session_id: str, *, skill_id: str) -> None:
    lifecycle = get_default_lifecycle(session_id)
    lifecycle.activate(
        skill_id,
        body=f"# {skill_id}\nTest body",
        allowed_tools=("read_file",),
        activated_by="test",
    )


def _store_with_memory(content: str) -> InMemoryMemoryStore:
    store = InMemoryMemoryStore()
    intent = MemoryOperationIntent(
        operation_type=MemoryOperationType.RETAIN,
        decision_type=MemoryDecisionType.RETAIN,
        confirmation_status=MemoryConfirmationStatus.APPROVED,
        user_choice=MemoryConfirmationChoice.ACCEPT,
        content_summary=content,
        source_summary="skill-memory-scope-test",
        scope=MemoryScope.USER,
        safety_summary="safe",
        sensitive_redacted=False,
        user_visible_summary=content[:80],
    )
    store.apply_operation_intent(intent, build_memory_audit_summary(intent))
    return store


class _RecallSpy:
    def __init__(self, store: InMemoryMemoryStore) -> None:
        registry = ActionHandlerRegistry()
        registry.register(RuntimeActionType.MEMORY_RECALL, MemoryRecallHandler(store=store))
        self._dispatcher = RuntimeActionDispatcher(registry=registry)
        self.captured: list[tuple[Any, Any]] = []

    @property
    def action_log(self):
        return self._dispatcher.action_log

    def route_from_runtime_loop(self, request, **kwargs: object):
        result = self._dispatcher.route_from_runtime_loop(request, **kwargs)
        self.captured.append((request, result))
        return result

    def route(self, request):
        result = self._dispatcher.route(request)
        self.captured.append((request, result))
        return result


def test_skill_memory_scope_none_suppresses_recall_injection(tmp_path: Path) -> None:
    from agent import core

    registry = _registry(tmp_path, scope="none")
    session_id = "skill-memory-none"
    _activate(session_id, skill_id="skill-none")
    store = _store_with_memory("RAW MEMORY SHOULD NOT APPEAR")
    spy = _RecallSpy(store)

    prompt, count = core.refresh_runtime_system_prompt(
        dispatcher=spy,
        skill_registry=registry,
        namespace_key=session_id,
    )

    assert count == 0
    assert "RAW MEMORY SHOULD NOT APPEAR" not in prompt
    request, result = spy.captured[-1]
    assert request.payload["decision"] == "blocked"
    assert result.payload["disposition"] == "policy_blocked"
    evidence = dict(result.evidence)
    assert evidence["memory_policy_blocked"]["event_type"] == "memory.policy_blocked"
    assert evidence["memory_recall_skipped"]["event_type"] == "memory.recall.skipped"


def test_skill_memory_scope_read_context_allows_recall_injection(tmp_path: Path) -> None:
    from agent import core

    registry = _registry(tmp_path, scope="read_context")
    session_id = "skill-memory-read-context"
    _activate(session_id, skill_id="skill-read-context")
    store = _store_with_memory("VISIBLE MEMORY FOR READ CONTEXT")
    spy = _RecallSpy(store)

    prompt, count = core.refresh_runtime_system_prompt(
        dispatcher=spy,
        skill_registry=registry,
        namespace_key=session_id,
    )

    assert count == 1
    assert "VISIBLE MEMORY FOR READ CONTEXT" in prompt
    _request, result = spy.captured[-1]
    assert result.payload["disposition"] == "recalled"


def test_skill_memory_scope_propose_memory_is_not_direct_store_write(tmp_path: Path) -> None:
    from agent import core

    registry = _registry(tmp_path, scope="propose_memory")
    session_id = "skill-memory-propose-memory"
    _activate(session_id, skill_id="skill-propose-memory")
    store = _store_with_memory("VISIBLE MEMORY FOR PROPOSE MEMORY")
    before = tuple(store.list_records())
    spy = _RecallSpy(store)

    prompt, count = core.refresh_runtime_system_prompt(
        dispatcher=spy,
        skill_registry=registry,
        namespace_key=session_id,
    )

    assert count == 1
    assert "VISIBLE MEMORY FOR PROPOSE MEMORY" in prompt
    assert tuple(store.list_records()) == before
    assert "skill-propose-memory" in prompt
