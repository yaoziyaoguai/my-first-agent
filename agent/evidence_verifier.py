"""S4-G05: evidence verification / consistency check（AC-5）。

对 replay chain（G02）做**完整 / 自洽 / 有序 / 可复放**校验，使 evidence 不仅「存在」且
「可验证」，能检出残缺/篡改/乱序/空链/重复 ref。

判据（`S4_FIDELITY_CONTRACT.md §5`）：
- complete：源 state 产生的每个 tool_use_id / delegation_id 都在 chain 中（无缺失）。
- self_consistent：无重复 ref；tool status 计数与源计数一致（检出 status 篡改）。
- ordered：seq 单调 0..n-1；同一 step 内 decision 早于 tool 早于 delegation。
- replayable：chain 非空（可重导 governed path 摘要）。

边界：本模块是纯函数校验，不写 state、不改 checkpoint、不做密码学签名（非 goal）。
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any

from agent.task_replay_chain import ReplayChain, ReplayEvent, build_replay_chain

# 与 build_replay_chain 的 kind 排序权重一致（decision < tool < delegation）。
_KIND_ORDER: dict[str, int] = {"decision": 0, "tool": 1, "delegation": 2}


@dataclass(frozen=True, slots=True)
class VerificationFinding:
    """单项校验结果。"""

    check: str  # "complete" | "self_consistent" | "ordered" | "replayable"
    passed: bool
    reason: str  # 通过为 ""；失败为 chain_incomplete/count_mismatch/duplicate_ref/...
    detail: str


@dataclass(frozen=True, slots=True)
class VerificationReport:
    """evidence 校验报告。ok == 全部 finding 通过。"""

    ok: bool
    findings: tuple[VerificationFinding, ...]

    def finding(self, check: str) -> VerificationFinding:
        for f in self.findings:
            if f.check == check:
                return f
        raise KeyError(check)


def verify_replay_chain(
    chain: ReplayChain,
    *,
    expected_tool_use_ids: Collection[str] = (),
    expected_delegation_ids: Collection[str] = (),
    expected_tool_counts: Mapping[str, int] | None = None,
) -> VerificationReport:
    """校验一条 replay chain 相对于源参考的完整性/自洽/有序/可复放。

    参数:
        chain: 待校验的 ReplayChain（可能被篡改/残缺）。
        expected_tool_use_ids: 源 state 中应存在的 tool_use_id 集合（完整性参考）。
        expected_delegation_ids: 源 state 中应存在的 delegation_id 集合。
        expected_tool_counts: 源 tool status → count 映射（自洽参考；None 则跳过计数校验）。

    返回:
        VerificationReport（ok + 四项 finding）。
    """
    findings: list[VerificationFinding] = []
    findings.append(_check_complete(chain, expected_tool_use_ids, expected_delegation_ids))
    findings.append(_check_ordered(chain))
    findings.append(_check_self_consistent(chain, expected_tool_counts))
    findings.append(_check_replayable(chain))
    return VerificationReport(ok=all(f.passed for f in findings), findings=tuple(findings))


def verify_evidence(state: Any) -> VerificationReport:
    """便捷入口：从 state 构建 chain + 抽取源参考，再校验。

    用于校验「build_replay_chain(state) 的投影是否忠实于 state」。检出残缺/篡改需用
    ``verify_replay_chain`` 传入被改动的 chain + 显式参考。
    """
    chain = build_replay_chain(state)
    task = getattr(state, "task", None)
    tool_log: dict[str, Any] = dict(getattr(task, "tool_execution_log", {}) or {})
    delegation_log: list[Any] = list(getattr(task, "delegation_log", []) or [])

    expected_tool_ids = [str(k) for k in tool_log]
    expected_del_ids = [
        str(entry.get("delegation_id", ""))
        for entry in delegation_log
        if isinstance(entry, dict) and entry.get("delegation_id")
    ]

    expected_counts: dict[str, int] = {}
    for entry in tool_log.values():
        if isinstance(entry, dict):
            status = str(entry.get("status", "executed"))
            expected_counts[status] = expected_counts.get(status, 0) + 1

    return verify_replay_chain(
        chain,
        expected_tool_use_ids=expected_tool_ids,
        expected_delegation_ids=expected_del_ids,
        expected_tool_counts=expected_counts,
    )


# ──────────────────────────────────────────────────────────────────────────────
# 各项校验
# ──────────────────────────────────────────────────────────────────────────────


def _check_complete(
    chain: ReplayChain,
    expected_tool_use_ids: Collection[str],
    expected_delegation_ids: Collection[str],
) -> VerificationFinding:
    chain_tool_ids = {e.ref_id for e in chain.tool_events}
    chain_del_ids = {e.ref_id for e in chain.delegation_events}
    missing_tools = sorted(set(expected_tool_use_ids) - chain_tool_ids)
    missing_del = sorted(set(expected_delegation_ids) - chain_del_ids)
    if missing_tools or missing_del:
        detail = f"missing_tool_ids={missing_tools} missing_delegation_ids={missing_del}"
        return VerificationFinding("complete", False, "chain_incomplete", detail)
    return VerificationFinding("complete", True, "", "")


def _check_ordered(chain: ReplayChain) -> VerificationFinding:
    events = chain.events
    seqs = [e.seq for e in events]
    if seqs != list(range(len(events))):
        return VerificationFinding("ordered", False, "sequence_disorder", "seq_not_monotonic")
    # 同一 step 内：decision(0) < tool(1) < delegation(2)，kind_order 序列应非递减。
    last_kind_order = -1
    last_step: int | None = None
    for e in events:
        if last_step is not None and e.step_index != last_step:
            last_kind_order = -1  # 新 step 重新起算
        ko = _KIND_ORDER.get(e.kind, 9)
        if last_step == e.step_index and ko < last_kind_order:
            return VerificationFinding(
                "ordered", False, "sequence_disorder", "kind_order_violation"
            )
        last_kind_order = ko
        last_step = e.step_index
    return VerificationFinding("ordered", True, "", "")


def _check_self_consistent(
    chain: ReplayChain,
    expected_tool_counts: Mapping[str, int] | None,
) -> VerificationFinding:
    dup = _duplicate_refs(chain)
    if dup:
        return VerificationFinding("self_consistent", False, "duplicate_ref", str(dup))
    if expected_tool_counts is not None:
        actual = _count_by_status(chain.tool_events)
        for status, expected in expected_tool_counts.items():
            if actual.get(status, 0) != int(expected):
                detail = f"{status}: expected {expected}, got {actual.get(status, 0)}"
                return VerificationFinding("self_consistent", False, "count_mismatch", detail)
    return VerificationFinding("self_consistent", True, "", "")


def _check_replayable(chain: ReplayChain) -> VerificationFinding:
    if chain.events:
        return VerificationFinding("replayable", True, "", "")
    return VerificationFinding("replayable", False, "not_replayable", "empty chain")


# ──────────────────────────────────────────────────────────────────────────────
# helpers
# ──────────────────────────────────────────────────────────────────────────────


def _duplicate_refs(chain: ReplayChain) -> dict[str, list[str]]:
    """返回同 kind 内重复的 ref_id（按 kind 分组）。空 dict 表示无重复。"""
    result: dict[str, list[str]] = {}
    for kind, events in (
        ("tool", chain.tool_events),
        ("delegation", chain.delegation_events),
    ):
        seen: set[str] = set()
        dups: list[str] = []
        for e in events:
            if e.ref_id in seen and e.ref_id not in dups:
                dups.append(e.ref_id)
            seen.add(e.ref_id)
        if dups:
            result[kind] = dups
    return result


def _count_by_status(events: Collection[ReplayEvent]) -> dict[str, int]:
    return dict(Counter(e.status for e in events))
