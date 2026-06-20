"""FINAL-G04 (TD-013) 测试：evidence verifier 检测跨 kind 重复 ref_id。

TD-013：``_duplicate_refs`` 按 kind 分组，所以一个 ref_id 同时出现在 tool 与
delegation 事件中（``tool_use_id == delegation_id``）不会被标记——
``self_consistent`` 误判为 ok。本测试锁定该修复。

RED：当前实现漏报跨 kind 重复 → ``_check_self_consistent`` 误判 ok。
GREEN：扩展 ``_duplicate_refs`` 检测跨 kind 重复 → 报 ``duplicate_ref``。
"""

from __future__ import annotations

from agent.evidence_verifier import _check_self_consistent
from agent.task_replay_chain import ReplayChain, ReplayEvent


def _event(kind: str, ref_id: str) -> ReplayEvent:
    return ReplayEvent(
        seq=0,
        kind=kind,
        step_index=0,
        ref_id=ref_id,
        name="x",
        status="executed",
        input_preview="",
        output_preview="",
        policy_outcome="allow",
    )


def test_cross_kind_duplicate_ref_detected():
    # 同一 ref_id 同时出现在 tool 与 delegation 事件 —— 跨 kind 重复（TD-013）。
    chain = ReplayChain(
        task_scope_id="t",
        lifecycle="running",
        events=(
            _event("tool", "shared-ref-1"),
            _event("delegation", "shared-ref-1"),
        ),
    )
    finding = _check_self_consistent(chain, None)
    assert not finding.passed
    assert finding.reason == "duplicate_ref"


def test_same_kind_duplicate_still_detected():
    # 回归保护：同 kind 内重复仍被检出。
    chain = ReplayChain(
        task_scope_id="t",
        lifecycle="running",
        events=(
            _event("tool", "dup-ref"),
            _event("tool", "dup-ref"),
        ),
    )
    finding = _check_self_consistent(chain, None)
    assert not finding.passed
    assert finding.reason == "duplicate_ref"


def test_no_duplicate_is_ok():
    # 无重复（含跨 kind 不重叠）应通过。
    chain = ReplayChain(
        task_scope_id="t",
        lifecycle="running",
        events=(
            _event("tool", "tool-ref"),
            _event("delegation", "delegation-ref"),
        ),
    )
    finding = _check_self_consistent(chain, None)
    assert finding.passed
