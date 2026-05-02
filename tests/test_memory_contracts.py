"""Stage 3 Slice 1: MemoryCandidate / MemoryDecision contract tests.

这些测试先于实现存在，保护 Slice 1 的最小边界：我们只定义无副作用的
candidate / decision 语言，不实现 MemoryRecord、MemoryStore、retrieval、
prompt 注入或用户确认 UI。MemoryCandidate 只是候选；MemoryDecision 只是决策
结果；真正的写入、召回、遗忘执行必须留给后续 Slice，并继续经过 policy /
approval / audit。
"""

from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, fields, is_dataclass
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_MODULE = PROJECT_ROOT / "agent" / "memory_contracts.py"


def _read_tree() -> ast.Module:
    return ast.parse(CONTRACT_MODULE.read_text(encoding="utf-8"))


def _agent_imports() -> set[str]:
    """用 AST 收集 contract 模块 imports，避免 runtime 依赖偷偷混进来。"""

    imports: set[str] = set()
    tree = _read_tree()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names if alias.name.startswith("agent"))
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "agent":
                imports.update(f"agent.{alias.name}" for alias in node.names)
            elif node.module.startswith("agent."):
                imports.add(node.module)
    return imports


def _called_names() -> set[str]:
    """收集函数调用名，确认 contract 层没有 IO/storage/network 副作用。"""

    names: set[str] = set()
    tree = _read_tree()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            names.add(func.id)
        elif isinstance(func, ast.Attribute):
            names.add(func.attr)
    return names


def test_memory_candidate_is_frozen_candidate_not_record() -> None:
    """Candidate 只是候选，不是已经保存的 MemoryRecord。

    这里故意断言 Candidate 没有 status/version/namespace 等持久化字段，避免
    Slice 1 偷偷把"可考虑记住"升级成"已经写入长期记忆"。
    """

    from agent.memory_contracts import (
        MemoryCandidate,
        MemoryScope,
        MemorySensitivity,
        MemorySource,
    )

    candidate = MemoryCandidate(
        id="cand-1",
        content="用户偏好回答简洁",
        source=MemorySource.USER_INPUT,
        source_event="turn-1",
        proposed_type="preference",
        scope=MemoryScope.USER,
        sensitivity=MemorySensitivity.LOW,
        stability="stable",
        confidence=0.9,
        reason="用户明确表达了稳定偏好",
        created_at="2026-01-01T00:00:00Z",
    )

    assert is_dataclass(candidate)
    assert candidate.content == "用户偏好回答简洁"

    field_names = {field.name for field in fields(candidate)}
    assert {"status", "version", "namespace", "updated_at", "expires_at"}.isdisjoint(
        field_names
    )

    with pytest.raises(FrozenInstanceError):
        candidate.content = "changed"  # type: ignore[misc]


def test_memory_decision_is_frozen_decision_not_write_operation() -> None:
    """Decision 只表达决策，不执行写入。

    `retain` decision 不能带 save/write/persist 这类方法语义；否则 contract 层会
    抢走后续 MemoryStore / approval / audit 的职责，形成新的小巨石。
    """

    from agent.memory_contracts import (
        MemoryCandidate,
        MemoryDecision,
        MemoryDecisionType,
        MemoryScope,
        MemorySensitivity,
        MemorySource,
    )

    candidate = MemoryCandidate(
        id="cand-2",
        content="项目使用 pytest",
        source=MemorySource.PROJECT_CONTEXT,
        source_event=None,
        proposed_type="project",
        scope=MemoryScope.PROJECT,
        sensitivity=MemorySensitivity.LOW,
        stability="stable",
        confidence=0.8,
        reason="来自当前 repo 公开测试配置",
        created_at=None,
    )
    decision = MemoryDecision(
        decision_type=MemoryDecisionType.RETAIN,
        target_candidate=candidate,
        action="suggest_retain",
        requires_user_confirmation=True,
        reason="项目偏好需要用户确认后才能长期记住",
        safety_flags=(),
        provenance="candidate:cand-2",
    )

    assert decision.decision_type is MemoryDecisionType.RETAIN
    assert decision.target_candidate is candidate
    assert not any(hasattr(decision, name) for name in {"save", "write", "persist"})

    with pytest.raises(FrozenInstanceError):
        decision.reason = "changed"  # type: ignore[misc]


def test_sensitive_retain_or_update_decision_requires_confirmation() -> None:
    """敏感候选进入 retain/update/recall 前必须能表达 human confirmation。

    这是 contract-level safety invariant，不是完整 MemoryPolicy：Slice 1 不判断
    文本是否敏感，只要求当候选已被标为 HIGH/SECRET 时，危险 decision 不能声明
    `requires_user_confirmation=False`。
    """

    from agent.memory_contracts import (
        MemoryCandidate,
        MemoryDecision,
        MemoryDecisionType,
        MemoryScope,
        MemorySensitivity,
        MemorySource,
    )

    candidate = MemoryCandidate(
        id="cand-secret",
        content="[redacted secret-like content]",
        source=MemorySource.USER_INPUT,
        source_event="turn-2",
        proposed_type="preference",
        scope=MemoryScope.USER,
        sensitivity=MemorySensitivity.SECRET,
        stability="unknown",
        confidence=0.2,
        reason="测试用敏感标记",
        created_at=None,
    )

    with pytest.raises(ValueError, match="requires user confirmation"):
        MemoryDecision(
            decision_type=MemoryDecisionType.RETAIN,
            target_candidate=candidate,
            action="retain",
            requires_user_confirmation=False,
            reason="unsafe",
        )

    decision = MemoryDecision(
        decision_type=MemoryDecisionType.RETAIN,
        target_candidate=candidate,
        action="retain",
        requires_user_confirmation=True,
        reason="only after explicit approval",
        safety_flags=("sensitive",),
    )
    assert decision.requires_user_confirmation is True


def test_forget_is_first_class_decision_not_update_alias() -> None:
    """Forget 必须是一等 decision，不能被折叠成普通 update。

    用户的遗忘权优先级最高；如果 contract vocabulary 里没有独立 forget，后续
    MemoryPolicy / audit / provider adapter 很容易把删除语义弱化成"改状态"。
    """

    from agent.memory_contracts import MemoryDecision, MemoryDecisionType

    decision = MemoryDecision(
        decision_type=MemoryDecisionType.FORGET,
        target_candidate=None,
        action="forget",
        requires_user_confirmation=False,
        reason="用户明确要求忘记相关信息",
    )

    assert MemoryDecisionType.FORGET.value == "forget"
    assert decision.decision_type is not MemoryDecisionType.UPDATE


def test_memory_contracts_do_not_import_prompt_runtime_checkpoint_or_mcp_layers() -> None:
    """Contract 层不能依赖 prompt/runtime/checkpoint/TUI/MCP。

    Slice 1 只是定义语言层；如果它 import prompt_builder、core、checkpoint、
    TUI 或 MCP，就会在还没有 policy/store 前制造反向依赖。
    """

    imports = _agent_imports()

    forbidden = {
        "agent.core",
        "agent.state",
        "agent.checkpoint",
        "agent.prompt_builder",
        "agent.context_builder",
        "agent.input_backends",
        "agent.display_events",
        "agent.mcp",
        "agent.tool_executor",
        "agent.tool_registry",
    }
    assert imports.isdisjoint(forbidden), imports & forbidden


def test_memory_contracts_do_not_perform_io_storage_or_network_calls() -> None:
    """Contract 层必须无 IO、无 storage、无网络。

    这样 MemoryCandidate / MemoryDecision 可以被 prompt、policy、tests 安全导入，
    不会读取真实 `memory/` 数据、`.env`、sessions/runs，也不会偷偷启动 provider。
    """

    calls = _called_names()

    forbidden_calls = {
        "open",
        "read_text",
        "write_text",
        "mkdir",
        "unlink",
        "glob",
        "iterdir",
        "connect",
        "request",
        "urlopen",
    }
    assert calls.isdisjoint(forbidden_calls), calls & forbidden_calls


def test_provider_and_store_are_not_implemented_in_slice_1() -> None:
    """future provider seam 不能伪装成当前实现。

    Slice 1 只到 Candidate/Decision；MemoryStore / MemoryProvider / MemoryRecord
    都必须留到后续授权 slice，否则会提前引入 persistence/provider 选择。
    """

    import agent.memory_contracts as contracts

    assert not hasattr(contracts, "MemoryRecord")
    assert not hasattr(contracts, "MemoryStore")
    assert not hasattr(contracts, "MemoryProvider")


def test_memory_decision_type_vocabulary_is_closed_for_slice_1() -> None:
    """决策词表必须覆盖治理动作，但保持小而闭合。

    retain/recall/update/forget/reject/no-op/clarify 足以表达 Stage 3 的核心
    decision contract；不要在 Slice 1 引入 provider/job/storage 之类执行词。
    """

    from agent.memory_contracts import MemoryDecisionType

    assert {item.value for item in MemoryDecisionType} == {
        "retain",
        "recall",
        "update",
        "forget",
        "reject",
        "no-op",
        "clarify",
    }
