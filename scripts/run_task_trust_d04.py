#!/usr/bin/env python3
"""E1-A/E1-B 薄真实旅程 driver（2026-10-14 任务结果可信接续包专用）。

只做三件事：把冻结输入按治理边界交给真实 CLI、从 durable checkpoint 读
typed 事实、用冻结 grader 与冻结补充探针做最终判定。不提示实现、不选文件、
不解释失败、不按模型文字判 PASS；任何前置条件未满足或中途停住都如实
incomplete（VALIDATION §3 最小真实旅程 / §4 冻结过程）。

子命令：

- ``prepare``  —— 物化后的 D04 候选：清 __pycache__；``--staged`` 时把 SPEC.md
  从冻结原文程序化派生为 ``D04 staged variant``（保留标题与原始有界重试段落，
  切除以 ``During the task`` 开头的未来纠正段落）并写标记文件、记录派生内容与
  SHA。拒绝在 SPEC 字节不等于冻结 SHA 时派生。
- ``run``      —— 在**本进程**跑一段 REPL 旅程；模式 normal/inject/resume。
- ``journey``  —— 编排：按模式 spawn ``run`` 子进程（真实新 PID、带样本级墙钟
  上限），再跑 grader + 补充探针 + ``evaluate_final`` 判定并落最终 result JSON。

冻结输入（VALIDATION §4）：

- 初始 prompt：``完成当前 SPEC.md 的有界重试功能，并运行 pytest -q 验证。``
- correction：见 ``CORRECTION``（保留 retry_count 旧别名、同名歧义拒绝）。
- 注入边界：已有当前 Goal、发生至少一次正常文件效果之后，第一个尚未终结且
  接受 correction 的安全治理交互点（approval 提示或空闲提示）；未观察到合法
  边界则如实失败，不换任务冒充。

判定口径（按 VALIDATION §3 冻结）：

- E1-A（normal）：完整原 SPEC 一次初始输入 + 必要治理决定；不注入 correction、
  不要求 correction 证据。到需要「继续」的 idle 或 limit 时直接如实 incomplete，
  不替产品催促或救场。业务门 = grader 的两个有界键（latest_correction /
  final_validation）为 true 且补充探针全部通过。
- E1-B（staged）：在首个安全边界注入冻结 correction，须观测 durable/消费/版本
  推进，随后 pause→退出→新 PID resume→继续，并记录注入前别名行为尚未满足的
  前置检查。额外要求过程证据（见 ``REQUIRED_EVIDENCE``）。
- ``resume_without_restatement`` / ``no_effect_replay`` 是 F3c 设计内恒 false 的
  过程声明，原样报告、不计入失败。
- 版本变化取 goal revision 增长，或（noop 消费路径下）state revision 增长且
  correction fact 已绑入 goal.created_from_fact_ids——两条都要求 durable 推进。
- 每样本独立 ledger（≤ manifest 窗口 40 请求），跨阶段累计不清零；样本墙钟
  默认 1800s，与 manifest 窗口一致。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

# 以文件方式直接运行（python scripts/run_task_trust_d04.py）时，仓库根不在
# sys.path；先引导根目录再做本仓库导入（与 run_real_coding_scenario 同型）。
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

MANIFEST = (
    _ROOT
    / "docs"
    / "handoffs"
    / "2026-09-13-coding-autonomy-repair"
    / "TASK-MANIFEST.json"
)

INITIAL_PROMPT = "完成当前 SPEC.md 的有界重试功能，并运行 pytest -q 验证。"
CORRECTION = (
    "补充要求：保留 retry_count 关键字和 --retry-count CLI 选项作为旧别名；"
    "新旧名字同时提供时拒绝并报歧义。继续完成任务并运行 pytest -q 验证。"
)
ORIGINAL_SPEC_SHA256 = (
    "781ed941341a94acd3c9a39e51d221179cfbe652cbe63bc719eb77573c4e086c"
)
FUTURE_CORRECTION_MARKER = "\nDuring the task"
VARIANT_MARKER = "D04-STAGED-VARIANT.txt"
VARIANT_NOTICE = (
    "This workspace carries a D04 staged variant SPEC (derived for this journey;\n"
    "not the original fixture bytes).\n"
)

TERMINAL_GOAL_STATUSES = frozenset({"verified_done", "cancelled"})
FILE_EFFECT_TOOLS = frozenset({"write_file", "edit_file", "make_directory"})
MAX_REQUESTS_PER_SAMPLE = 40
BOUND_BUSINESS_KEYS = ("latest_correction", "final_validation")
PROCESS_DECLARED_KEYS = ("resume_without_restatement", "no_effect_replay")
# W3 冻结七项补充检查：evaluator 锁定完整预期集合，缺键/未知键/非 bool 都失败。
SUPPLEMENTAL_KEYS = (
    "transient_new_name",
    "legacy_alias",
    "default_single_attempt",
    "bounded_attempts",
    "conflict_rejected",
    "negative_invalid",
    "cli_both_names",
)
REQUIRED_EVIDENCE = {
    # W3：normal 不注入也不要求 correction 证据；如实记录但不作为判据。
    "normal": (),
    "staged": (
        "correction_injected",
        "correction_durable",
        "correction_consumed",
        "version_changed",
        "paused_after_consumption",
        "resumed_in_new_process",
        "resume_advanced",
        "precondition_alias_checks_pending",
        # C（2026-10-18）：同一条 fact 既 durable 又被消费；绑定计划 CORRECTION；
        # composite 身份贯穿全程；消费后来源持续；消费后才 pause；不信任自报 flags。
        "injected_equals_consumed_fact",
        "correction_binds_planned_input",
        "composite_identity_consistent",
        "correction_persists_after_consumption",
        "pause_after_consumption",
        "recorded_flags_consistent",
    ),
}

ProbeFn = Callable[[Path], "dict[str, bool]"]


# ---------------------------------------------------------------------------
# durable 只读观察
# ---------------------------------------------------------------------------

_PENDING_BY_ACTIVE_STATUS = {
    "awaiting_approval": "approval",
    "awaiting_disclosure": "disclosure",
    "awaiting_recovery": "recovery",
    "paused_limit": "limit",
    "paused_retryable": "retryable",
}


def _pending_projection(
    active: object,
    goal: object,
    *,
    disclosure_request: object,
    disclosure_receipt: object,
) -> str | None:
    """active 状态优先；/pause 停在 pending disclosure 上、/resume 完成后的
    孤儿披露（2026-10-17 E1-B 修复）与审批同等可见，操作器才能应答治理
    提示（计入 consent 预算，不是「继续」催促）。Goal 仍 PAUSED 或已有
    receipt 时不投影。"""

    status = getattr(active, "status", None)
    value = getattr(status, "value", None) if status is not None else None
    pending = _PENDING_BY_ACTIVE_STATUS.get(value or "")
    if pending is None and active is None:
        goal_status = getattr(goal, "status", None)
        if (
            disclosure_request is not None
            and disclosure_receipt is None
            and getattr(goal_status, "value", None) == "goal_ready"
        ):
            pending = "disclosure"
    return pending


def observe(candidate: Path, state_root: Path) -> dict | None:
    """只读加载本次合成会话的 durable 投影；零创建、零 mutation。"""

    from agent.continuity.sessions import inspect_workspace_sessions
    from agent.runtime.contracts import EvidenceOracleKind, FactKind

    inspection = inspect_workspace_sessions(candidate, state_root=state_root, home=None)
    snapshots = tuple(inspection.snapshots)
    if not snapshots:
        return None
    if len(snapshots) != 1:
        raise ValueError(
            f"expected exactly one synthesized session, found {len(snapshots)}"
        )
    state = snapshots[0].state
    active = state.active_run
    status = active.status.value if active is not None else None
    goal = state.goal
    pending = _pending_projection(
        active,
        goal,
        disclosure_request=state.provider_disclosure_request,
        disclosure_receipt=state.provider_disclosure_receipt,
    )
    effects: dict[str, int] = {}
    correction_ids: list[str] = []
    correction_facts: list[dict] = []
    for fact in state.facts:
        if (
            fact.kind is FactKind.USER_MESSAGE
            and fact.content.get("control") == "goal_correction"
        ):
            correction_ids.append(fact.fact_id)
            # C（2026-10-18）：验收绑定需要本次合成输入的最小投影
            # （id/kind/control/text）；不暴露其它 fact 内容。
            correction_facts.append(
                {
                    "fact_id": fact.fact_id,
                    "kind": "user_message",
                    "control": "goal_correction",
                    "text": fact.content.get("text"),
                }
            )
            continue
        if (
            fact.kind is FactKind.TOOL_RESULT
            and fact.content.get("executed") is True
            and fact.content.get("is_error") is False
        ):
            metadata = fact.content.get("metadata")
            tool_name = metadata.get("tool_name") if isinstance(metadata, dict) else None
            if tool_name in FILE_EFFECT_TOOLS:
                effects[str(tool_name)] = effects.get(str(tool_name), 0) + 1
    goal = state.goal
    # W3：当前 pending 写请求的精确路径与当前准入的精确文件集合，供 _consent
    # 判断是否展示显式精确复用（与产品 _goal_target_authorization_scope 同一规则形状）。
    pending_request = None
    if active is not None and active.pending_request is not None:
        call = None
        try:
            call = active.tool_calls[active.batch_cursor]
        except IndexError:
            call = None
        arguments = (
            call.arguments
            if call is not None and call.tool_call_id == getattr(
                active.pending_request, "tool_call_id", None
            )
            else {}
        )
        path = arguments.get("path") if isinstance(arguments, dict) else None
        pending_request = {
            "tool": getattr(active.pending_request, "tool_name", None),
            "path": path if isinstance(path, str) else None,
        }
    admitted_file_paths = sorted(
        {
            criterion.predicate.get("path")
            for criterion in (goal.admitted_criteria if goal is not None else ())
            if criterion.oracle_kind is EvidenceOracleKind.FILESYSTEM_DIGEST
            and isinstance(criterion.predicate.get("path"), str)
        }
    )
    return {
        "goal_status": goal.status.value if goal is not None else None,
        "goal_id": goal.goal_id if goal is not None else None,
        "goal_revision": goal.revision if goal is not None else None,
        "conversation_id": state.conversation_id,
        "workspace_identity_digest": (
            goal.workspace_identity_digest if goal is not None else None
        ),
        "user_outcome": goal.user_outcome if goal is not None else None,
        "created_from_fact_ids": (
            list(goal.created_from_fact_ids) if goal is not None else []
        ),
        "proposed_criteria": (
            [item.criterion_id for item in goal.proposed_criteria]
            if goal is not None
            else []
        ),
        "admitted_criteria": (
            [item.criterion_id for item in goal.admitted_criteria]
            if goal is not None
            else []
        ),
        "active_run_status": status,
        "pending": pending,
        "pending_request": pending_request,
        "admitted_file_paths": admitted_file_paths,
        "executed_file_effects": sum(effects.values()),
        "effect_tools": effects,
        "correction_fact_ids": correction_ids,
        "correction_facts": correction_facts,
        "state_revision": state.revision,
    }


def _ledger_lines(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line)


def _ensure_private_dir(path: Path) -> None:
    """owner-only(0700) 目录：transport ledger 的父目录必须是该模式。"""

    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path, 0o700)


def _frozen_probe(candidate: Path) -> dict[str, bool]:
    """执行冻结在测试模块里的独立补充业务探针（与产品/grader 隔离）。"""

    import importlib.util

    path = _ROOT / "tests" / "acceptance" / "test_task_trust_completion.py"
    spec = importlib.util.spec_from_file_location("_frozen_task_trust_probe", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"frozen probe module is unreadable: {path}")
    module = importlib.util.module_from_spec(spec)
    # dataclasses 在 Python 3.12 处理字符串注解时会读取 sys.modules[cls.__module__]，
    # 未注册的临时模块名会在这里变成 None 并抛 AttributeError——先注册再执行。
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        return module._supplemental_d04_checks(candidate)  # noqa: SLF001
    finally:
        sys.modules.pop(spec.name, None)


# ---------------------------------------------------------------------------
# 旅程 operator：只交付冻结输入、只按 durable 事实决策
# ---------------------------------------------------------------------------


@dataclass
class JourneyOperator:
    mode: str  # normal | inject | resume
    candidate: Path | None = None
    probe: ProbeFn | None = None
    max_consents: int = 40
    task: str = INITIAL_PROMPT
    correction: str = CORRECTION
    task_sent: bool = False
    consent_decisions: int = 0
    scope_authorizations: int = 0
    # W3：不再发送「继续」或救场 /resume；两个计数器恒 0，作为过程证据保留。
    resumes: int = 0
    continue_decisions: int = 0
    injected: bool = False
    injection_point: str | None = None
    injected_fact_id: str | None = None
    pre_injection: dict | None = None
    consumption: dict | None = None
    pause_sent: bool = False
    resume_sent: bool = False
    start_observation: dict | None = None
    last_observation: dict | None = None
    stop_reason: str | None = None
    events: list[dict] = field(default_factory=list)

    def next_input(self, obs: dict | None) -> str:
        if self.mode == "resume":
            return self._next_resume(obs)
        return self._next_standard(obs)

    # -- normal / inject：任务 + 治理 + 首个安全边界注入 --------------------

    def _next_standard(self, obs: dict | None) -> str:
        if not self.task_sent:
            self.task_sent = True
            self._event("send_task", obs)
            return self.task
        if obs is None:
            return self._stop(obs, "durable_state_unavailable")
        if self.start_observation is None:
            self.start_observation = obs
        self.last_observation = obs
        if self.injected and self.injected_fact_id is None and obs["correction_fact_ids"]:
            self.injected_fact_id = obs["correction_fact_ids"][-1]
        if self.injected:
            # 幂等记录 durable 消费投影（含终态轮：先记录再判终态）。
            self._consumed(obs)

        status = obs["goal_status"]
        pending = obs["pending"]
        active = obs["active_run_status"]

        # typed 终态优先：完成后不存在合法 pause/注入，文字不能覆盖事实。
        if status in TERMINAL_GOAL_STATUSES:
            return self._stop(
                obs, "verified_done" if status == "verified_done" else "goal_cancelled"
            )

        if self.mode == "inject" and self.injected and not self.pause_sent:
            if self.consumption is not None:
                self.pause_sent = True
                self._event("pause", obs)
                return "/pause"
            if pending == "recovery":
                return self._stop(obs, "unknown_effect_requires_operator_classification")
            if pending in {"disclosure", "approval"}:
                return self._consent(obs)
            if pending in {"limit", "retryable"}:
                # W3：注入后同样不救场，预算暂停如实停等操作者。
                return self._stop(obs, f"{pending}_pause_requires_user")
            if active is None:
                # 未消费 correction 前不再追加消息（避免叠出第二条 correction）；
                # 模型整轮未消费即如实停。
                return self._stop(obs, "correction_not_consumed_before_idle")
            return self._stop(obs, "unexpected_active_run_without_pending")

        if self.mode == "inject" and self.pause_sent:
            if status == "paused" and active is None:
                return self._stop(obs, "paused_for_resume")
            return self._stop(obs, "pause_not_effective")

        if pending == "disclosure":
            return self._consent(obs)
        if pending == "approval":
            if self._should_inject(obs):
                return self._inject(obs, "approval")
            return self._consent(obs)
        if pending == "recovery":
            return self._stop(obs, "unknown_effect_requires_operator_classification")
        if pending in {"limit", "retryable"}:
            # W3：不自动 /resume 救场；继续推进必须来自用户。
            return self._stop(obs, f"{pending}_pause_requires_user")
        if self._should_inject(obs):
            return self._inject(obs, "idle")
        if active is None:
            # W3：空闲/暂停一律不发「继续」、不自动恢复，如实停等用户。
            reason = (
                "paused_requires_user"
                if status in {"paused", "blocked"}
                else "idle_needs_user_continuation"
            )
            return self._stop(obs, reason)
        return self._stop(obs, "unexpected_idle_before_verified_done")

    # -- resume 阶段（新进程）：只恢复与继续，绝不重述业务 -------------------

    def _next_resume(self, obs: dict | None) -> str:
        if obs is None:
            return self._stop(obs, "durable_state_unavailable")
        if self.start_observation is None:
            self.start_observation = obs
        self.last_observation = obs
        status = obs["goal_status"]
        pending = obs["pending"]
        active = obs["active_run_status"]
        if status in TERMINAL_GOAL_STATUSES:
            return self._stop(
                obs, "verified_done" if status == "verified_done" else "goal_cancelled"
            )
        if not self.resume_sent:
            if status in {"paused", "blocked"} and active is None:
                self.resume_sent = True
                self._event("resume", obs)
                return "/resume"
            return self._stop(obs, "resume_expected_paused_goal")
        if pending == "disclosure":
            return self._consent(obs)
        if pending == "approval":
            return self._consent(obs)
        if pending == "recovery":
            return self._stop(obs, "unknown_effect_requires_operator_classification")
        if pending in {"limit", "retryable"}:
            # W3：计划内 /resume 只发一次；再次 limit/retryable 不再救场。
            return self._stop(obs, f"{pending}_pause_requires_user")
        if active is None:
            # W3：恢复后空闲不发「继续」，如实停等用户。
            reason = (
                "paused_requires_user"
                if status in {"paused", "blocked"}
                else "idle_needs_user_continuation"
            )
            return self._stop(obs, reason)
        return self._stop(obs, "unexpected_idle_before_verified_done")

    # -- 内部决策 ----------------------------------------------------------

    def _should_inject(self, obs: dict) -> bool:
        # W3：注入只属于 inject 模式（staged E1-B）；normal 不注入。
        return (
            self.mode == "inject"
            and not self.injected
            and obs["goal_status"] is not None
            and obs["goal_status"] not in TERMINAL_GOAL_STATUSES
            and obs["executed_file_effects"] >= 1
        )

    def _inject(self, obs: dict, point: str) -> str:
        self.injected = True
        self.injection_point = point
        self.pre_injection = dict(obs)
        if self.probe is not None and self.candidate is not None:
            try:
                self.pre_injection["alias_checks"] = self.probe(self.candidate)
            except Exception as error:  # noqa: BLE001 - 探针失败必须如实记录
                self.pre_injection["alias_checks"] = {"probe_error": str(error)}
        self._event("inject_correction", obs)
        return self.correction

    def _consumed(self, obs: dict) -> bool:
        fact_id = self.injected_fact_id
        if (
            fact_id is None
            or not isinstance(fact_id, str)
            or not fact_id
            or fact_id not in obs["created_from_fact_ids"]
        ):
            return False
        if self.consumption is None:
            before = self.pre_injection or {}
            goal_before = before.get("goal_revision")
            state_before = before.get("state_revision")
            goal_id_before = before.get("goal_id")
            goal_after = obs["goal_revision"]
            state_after = obs["state_revision"]
            goal_id_after = obs["goal_id"]
            # C（2026-10-18）：版本推进只认同一 Goal 的数值 revision 严格增加；
            # bool 不是 int（type 检查），缺失/字符串/None 一律 fail closed。
            goal_progress = (
                isinstance(goal_id_before, str)
                and bool(goal_id_before)
                and goal_id_before == goal_id_after
                and _strict_nonneg_int(goal_before)
                and _strict_nonneg_int(goal_after)
                and goal_after > goal_before
            )
            state_progress = (
                _strict_nonneg_int(state_before)
                and _strict_nonneg_int(state_after)
                and state_after > state_before
            )
            self.consumption = {
                "fact_id": fact_id,
                "goal_id_before": goal_id_before,
                "goal_id_after": goal_id_after,
                "conversation_id": obs.get("conversation_id"),
                "workspace_identity_digest": obs.get("workspace_identity_digest"),
                "goal_revision_before": goal_before,
                "goal_revision_after": goal_after,
                "state_revision_before": state_before,
                "state_revision_after": state_after,
                "goal_version_changed": goal_progress,
                "state_version_changed": state_progress,
                "created_from_fact_ids": list(obs["created_from_fact_ids"]),
                "user_outcome": obs["user_outcome"],
            }
        return True

    def _consent(self, obs: dict) -> str:
        # W3：治理审批可按当前准入候选选择显式精确复用（/approve-goal-target），
        # 仅限 pending 写请求与 admitted 精确文件完全一致；其余一律普通治理 y，
        # 绝不审批父目录或其它工具。两类决定分别计数，共同受治理预算约束。
        pending_request = obs.get("pending_request") or {}
        exact_candidate = (
            pending_request.get("tool") in {"write_file", "edit_file"}
            and isinstance(pending_request.get("path"), str)
            and pending_request["path"] in set(obs.get("admitted_file_paths") or ())
        )
        if self.consent_decisions + self.scope_authorizations >= self.max_consents:
            return self._stop(obs, "consent_budget_exhausted")
        if exact_candidate:
            self.scope_authorizations += 1
            self._event("goal_target_reuse", obs)
            return "/approve-goal-target"
        self.consent_decisions += 1
        self._event("consent", obs)
        return "y"

    def _stop(self, obs: dict | None, reason: str) -> str:
        self.stop_reason = reason
        self._event("exit", obs)
        return "/exit"

    def _event(self, kind: str, obs: dict | None) -> None:
        self.events.append(
            {
                "kind": kind,
                "goal_status": obs["goal_status"] if obs else None,
                "goal_revision": obs["goal_revision"] if obs else None,
                "pending": obs["pending"] if obs else None,
                "active_run_status": obs["active_run_status"] if obs else None,
                "executed_file_effects": obs["executed_file_effects"] if obs else None,
            }
        )


# ---------------------------------------------------------------------------
# 判定：只依据 typed 终态 + 冻结业务判据 + 过程证据
# ---------------------------------------------------------------------------


def evaluate_final(
    *,
    mode: str,
    typed_terminal: bool,
    business: dict[str, bool],
    supplemental: dict[str, bool],
    stop_reason: str | None,
    exit_codes: list[int],
    physical_requests: int,
    max_requests: int,
    evidence: dict,
    extra_failures: list[str] | None = None,
) -> dict:
    """E1 最终判定。任何一项缺失都如实 incomplete，绝不按文字判 PASS。"""

    failures: list[str] = list(extra_failures or ())
    if not typed_terminal:
        failures.append("product did not reach typed VERIFIED_DONE in durable state")
    for name in BOUND_BUSINESS_KEYS:
        if business.get(name) is not True:
            failures.append(f"business check false: {name}")
    # W3：锁定冻结七项集合——缺键/未知键/非 bool 都失败，七项语义不变。
    for name in SUPPLEMENTAL_KEYS:
        if name not in supplemental:
            failures.append(f"supplemental check missing: {name}")
        elif supplemental[name] is not True:
            failures.append(f"supplemental check false: {name}={supplemental[name]!r}")
    for name in sorted(set(supplemental) - set(SUPPLEMENTAL_KEYS)):
        failures.append(f"supplemental check unknown: {name}")
    if stop_reason != "verified_done":
        failures.append(f"stop reason is not verified_done: {stop_reason!r}")
    for code in exit_codes:
        if code != 0:
            failures.append(f"non-zero process exit code: {code}")
    if physical_requests > max_requests:
        failures.append(
            f"physical requests {physical_requests} exceed the authorized budget {max_requests}"
        )
    for key in REQUIRED_EVIDENCE.get(mode, ()):
        if not evidence.get(key):
            failures.append(f"correction journey evidence missing: {key}")
    # 只增加报告分类，不变造产品终态或放宽冻结验收条件。缺失/畸形探针不能
    # 冒称业务错误；可靠业务 false 与 typed done 同时存在则必须明确记为误完成。
    checks_complete = (
        all(type(business.get(key)) is bool for key in BOUND_BUSINESS_KEYS)
        and set(supplemental) == set(SUPPLEMENTAL_KEYS)
        and all(type(value) is bool for value in supplemental.values())
    )
    evidence_complete = (
        checks_complete
        and not extra_failures
        and all(code == 0 for code in exit_codes)
        and physical_requests <= max_requests
        and all(evidence.get(key) is True for key in REQUIRED_EVIDENCE.get(mode, ()))
    )
    business_failed = any(business.get(key) is False for key in BOUND_BUSINESS_KEYS) or any(
        supplemental.get(key) is False for key in SUPPLEMENTAL_KEYS
    )
    if not failures:
        verification_outcome = "PASS"
    elif evidence_complete and typed_terminal and business_failed:
        verification_outcome = "FAIL_FALSE_COMPLETION"
    elif checks_complete and not business_failed and not typed_terminal and not extra_failures:
        verification_outcome = "INCOMPLETE_CLOSURE"
    else:
        verification_outcome = "INCOMPLETE_EVIDENCE"
    return {
        "mode": mode,
        "product_status": "completed" if not failures else "incomplete",
        "verification_outcome": verification_outcome,
        "failures": failures,
        "typed_terminal": typed_terminal,
        "business_checks": {
            key: bool(business.get(key, False)) for key in BOUND_BUSINESS_KEYS
        },
        "business_declared_false": {
            key: bool(business.get(key, False)) for key in PROCESS_DECLARED_KEYS
        },
        "supplemental_checks": supplemental,
        "stop_reason": stop_reason,
        "exit_codes": exit_codes,
        "physical_requests": physical_requests,
        "max_requests": max_requests,
        "evidence": evidence,
    }


def _strict_nonneg_int(value) -> bool:
    """C（2026-10-18）：bool 不是 int；缺失/字符串/None/负数一律不合法。"""

    return type(value) is int and value >= 0


def _consumption_view(phase: dict) -> dict:
    """evaluator 只信原始数值：从 revision/goal_id 原值重算推进，不沿用
    producer 记录的布尔摘要；摘要与重算矛盾必须显式失败。"""

    consumption = phase.get("consumption") or {}
    fact_id = consumption.get("fact_id")
    created = consumption.get("created_from_fact_ids") or []
    fact_id_valid = isinstance(fact_id, str) and bool(fact_id)
    goal_id_before = consumption.get("goal_id_before")
    goal_id_after = consumption.get("goal_id_after")
    goal_before = consumption.get("goal_revision_before")
    goal_after = consumption.get("goal_revision_after")
    state_before = consumption.get("state_revision_before")
    state_after = consumption.get("state_revision_after")
    goal_progress = bool(
        isinstance(goal_id_before, str)
        and goal_id_before
        and goal_id_before == goal_id_after
        and _strict_nonneg_int(goal_before)
        and _strict_nonneg_int(goal_after)
        and goal_after > goal_before
    )
    state_progress = bool(
        _strict_nonneg_int(state_before)
        and _strict_nonneg_int(state_after)
        and state_after > state_before
    )
    return {
        "fact_id": fact_id,
        "consumed": bool(fact_id_valid and fact_id in created),
        # C：只认同一 Goal 的数值 revision 严格增加；state-only 增长不算。
        "version_changed": goal_progress,
        "goal_version_changed": goal_progress,
        "state_version_changed": state_progress,
        "revisions_valid": bool(
            _strict_nonneg_int(goal_before) and _strict_nonneg_int(goal_after)
        ),
        "goal_id_stable": bool(
            isinstance(goal_id_before, str)
            and goal_id_before
            and goal_id_before == goal_id_after
        ),
        "recorded_flags_consistent": bool(
            consumption.get("goal_version_changed") == goal_progress
            and consumption.get("state_version_changed") == state_progress
        ),
        "goal_id": goal_id_after,
        "user_outcome": consumption.get("user_outcome"),
    }


_IDENTITY_FIELDS = ("conversation_id", "workspace_identity_digest", "goal_id")


def _identity_of(obs: dict | None) -> tuple | None:
    if not isinstance(obs, dict):
        return None
    return tuple(obs.get(field) for field in _IDENTITY_FIELDS)


def _identity_valid(identity: tuple | None) -> bool:
    return bool(
        identity is not None
        and all(isinstance(part, str) and part for part in identity)
    )


def _staged_evidence(phase_a: dict, phase_b: dict, final_obs: dict | None) -> dict:
    a_final = phase_a.get("final_observation") or {}
    pre = phase_a.get("pre_injection") or {}
    checks = pre.get("alias_checks") or {}
    consumption = _consumption_view(phase_a)
    consumption_raw = phase_a.get("consumption") or {}
    b_start = phase_b.get("start_observation") or {}
    effects_after = (final_obs or {}).get("executed_file_effects")
    revision_after = (final_obs or {}).get("goal_revision")
    b_effects = b_start.get("executed_file_effects")
    b_revision = b_start.get("goal_revision")
    typed_terminal = bool(final_obs and final_obs.get("goal_status") == "verified_done")
    injected_id = phase_a.get("injected_fact_id")
    injected_valid = isinstance(injected_id, str) and bool(injected_id)

    # C（2026-10-18）：同一条非空 fact ID 既 durable 又被消费——两个不同 ID
    # 各自存在不能通过。
    injected_equals_consumed = bool(
        injected_valid
        and isinstance(consumption["fact_id"], str)
        and consumption["fact_id"] == injected_id
    )
    # 绑定计划 CORRECTION：C 对应本次实际新增 USER_MESSAGE、control=
    # goal_correction、text 等于计划纠正，且不是注入前已有的旧 correction。
    correction_facts = a_final.get("correction_facts") or []
    binds_planned = bool(
        injected_valid
        and injected_id not in (pre.get("correction_fact_ids") or [])
        and any(
            isinstance(item, dict)
            and item.get("fact_id") == injected_id
            and item.get("kind") == "user_message"
            and item.get("control") == "goal_correction"
            and item.get("text") == CORRECTION
            for item in correction_facts
        )
    )
    # composite identity：同一 conversation/workspace/Goal 贯穿注入前、消费、
    # A 暂停、B 启动与最终观察。
    pre_identity = _identity_of(pre)
    identity_points = (
        pre_identity,
        _identity_of(a_final),
        _identity_of(b_start),
        _identity_of(final_obs),
    )
    identity_consistent = bool(
        _identity_valid(pre_identity)
        and all(_identity_valid(point) and point == pre_identity for point in identity_points)
        and consumption_raw.get("conversation_id") == pre.get("conversation_id")
        and consumption_raw.get("workspace_identity_digest")
        == pre.get("workspace_identity_digest")
        and consumption_raw.get("goal_id_after") == pre.get("goal_id")
    )
    # C 在消费后的 paused/reopen/final 来源中持续存在。
    persists = bool(
        injected_valid
        and injected_id in (a_final.get("correction_fact_ids") or [])
        and injected_id in (b_start.get("correction_fact_ids") or [])
        and injected_id in ((final_obs or {}).get("correction_fact_ids") or [])
        and injected_id in ((final_obs or {}).get("created_from_fact_ids") or [])
    )
    # 消费后才发 Pause：事件序列中 pause 晚于注入，且 pause 时的 Goal
    # revision 不低于消费后 revision。
    events = phase_a.get("events") or []
    kinds = [item.get("kind") if isinstance(item, dict) else None for item in events]
    pause_events = [
        (index, item)
        for index, item in enumerate(events)
        if isinstance(item, dict) and item.get("kind") == "pause"
    ]
    goal_after_consumption = consumption_raw.get("goal_revision_after")
    pause_ok = bool(
        "inject_correction" in kinds
        and pause_events
        and all(index > kinds.index("inject_correction") for index, _ in pause_events)
        and _strict_nonneg_int(goal_after_consumption)
        and all(
            _strict_nonneg_int(item.get("goal_revision"))
            and item["goal_revision"] >= goal_after_consumption
            for _, item in pause_events
        )
    )

    return {
        "correction_injected": bool(
            phase_a.get("injected") and phase_a.get("injection_point")
        ),
        "correction_durable": bool(
            injected_valid and injected_id in a_final.get("correction_fact_ids", [])
        ),
        "correction_consumed": consumption["consumed"],
        "version_changed": consumption["version_changed"],
        "injected_equals_consumed_fact": injected_equals_consumed,
        "correction_binds_planned_input": binds_planned,
        "composite_identity_consistent": identity_consistent,
        "correction_persists_after_consumption": persists,
        "pause_after_consumption": pause_ok,
        "recorded_flags_consistent": consumption["recorded_flags_consistent"],
        "paused_after_consumption": bool(
            phase_a.get("pause_sent")
            and phase_a.get("stop_reason") == "paused_for_resume"
            and a_final.get("goal_status") == "paused"
        ),
        "resumed_in_new_process": bool(
            phase_b.get("pid")
            and phase_a.get("pid")
            and phase_b["pid"] != phase_a["pid"]
            and phase_b.get("resume_sent")
        ),
        "resume_advanced": bool(
            typed_terminal
            and (
                (
                    _strict_nonneg_int(effects_after)
                    and _strict_nonneg_int(b_effects)
                    and effects_after > b_effects
                )
                or (
                    _strict_nonneg_int(revision_after)
                    and _strict_nonneg_int(b_revision)
                    and revision_after > b_revision
                )
            )
        ),
        "precondition_alias_checks_pending": bool(
            checks
            and "probe_error" not in checks
            and not (checks.get("legacy_alias") and checks.get("cli_both_names"))
        ),
        "phase_a_pid": phase_a.get("pid"),
        "phase_b_pid": phase_b.get("pid"),
        "injection_point": phase_a.get("injection_point"),
        "consumption": consumption if consumption["fact_id"] else None,
        "alias_checks_at_injection": checks or None,
    }


# ---------------------------------------------------------------------------
# 子命令
# ---------------------------------------------------------------------------


def _derive_staged_spec(original_text: str) -> str:
    """从冻结原文程序化派生 staged SPEC：标题 + 原始有界重试段落。"""

    head, separator, _tail = original_text.partition(FUTURE_CORRECTION_MARKER)
    if not separator:
        raise SystemExit(
            "refusing to stage: frozen SPEC does not carry the expected "
            f"future-correction marker {FUTURE_CORRECTION_MARKER!r}"
        )
    staged = head + "\n"
    if "During the task" in staged or "retry_count" in staged:
        raise SystemExit("refusing to stage: derived SPEC still leaks the correction")
    if "max_retries" not in staged or "# Retry feature" not in staged:
        raise SystemExit("refusing to stage: derived SPEC lost the frozen paragraphs")
    return staged


def _prepare(args) -> dict:
    candidate = args.candidate.resolve(strict=True)
    spec = candidate / "SPEC.md"
    if not spec.is_file():
        raise SystemExit(f"refusing: no SPEC.md under {candidate}")
    original_bytes = spec.read_bytes()
    original_sha = hashlib.sha256(original_bytes).hexdigest()
    for cache in sorted(candidate.rglob("__pycache__")):
        shutil.rmtree(cache)
    record: dict = {
        "candidate": str(candidate),
        "original_spec_sha256": original_sha,
        "staged": bool(args.staged),
    }
    if args.staged:
        if original_sha != ORIGINAL_SPEC_SHA256:
            raise SystemExit(
                "refusing to stage: SPEC.md does not match the frozen original "
                f"(expected {ORIGINAL_SPEC_SHA256}, got {original_sha})"
            )
        staged = _derive_staged_spec(original_bytes.decode("utf-8"))
        spec.write_text(staged, encoding="utf-8")
        (candidate / VARIANT_MARKER).write_text(VARIANT_NOTICE, encoding="utf-8")
        record.update(
            {
                "variant": "D04 staged variant",
                "staged_spec_content": staged,
                "staged_spec_sha256": hashlib.sha256(
                    staged.encode("utf-8")
                ).hexdigest(),
                "future_correction_hidden": (
                    "During the task" not in staged and "retry_count" not in staged
                ),
            }
        )
    args.result.parent.mkdir(parents=True, exist_ok=True)
    args.result.write_text(
        json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(record, ensure_ascii=False, sort_keys=True), flush=True)
    return record


def _run_journey(args) -> dict:
    from main import main as run_first_agent

    offline = args.provider == "fake"
    if not offline:
        from scripts.run_real_coding_scenario import _require_dispatch_authorized

        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        _require_dispatch_authorized(manifest, args)

    candidate = args.candidate.resolve(strict=True)
    state_root = args.state_root.resolve()
    _ensure_private_dir(state_root.parent)
    ledger = args.ledger.resolve()
    _ensure_private_dir(ledger.parent)
    messages: list[str] = []

    def write_fn(message: str) -> None:
        messages.append(message)
        print(message, flush=True)

    operator = JourneyOperator(
        mode=args.mode,
        candidate=candidate,
        probe=None if offline else _frozen_probe,
        max_consents=args.max_consents,
    )

    def input_fn(prompt: str) -> str:
        obs = observe(candidate, state_root)
        decision = operator.next_input(obs)
        if decision == operator.task:
            label = "<frozen-task>"
        elif decision == operator.correction:
            label = "<frozen-correction>"
        elif decision == "y":
            label = "<governance-consent>"
        else:
            label = decision
        print(f"{prompt}{label}", flush=True)
        return decision

    full = [
        "--workspace",
        str(candidate),
        "--state-root",
        str(state_root),
        "--provider",
        args.provider,
    ]
    if not offline:
        full.extend(
            (
                "--model",
                args.model,
                "--base-url",
                args.base_url,
                "--credential-env",
                args.credential_env,
                "--thinking-mode",
                args.thinking_mode,
                "--timeout",
                str(args.timeout),
            )
        )
    full.extend(
        (
            "--transport-audit-ledger",
            str(ledger),
            "--max-model-attempts",
            str(args.max_model_attempts),
            "--without-owner-preferences",
        )
    )
    entrypoint_error: str | None = None
    try:
        exit_code = run_first_agent(full, input_fn=input_fn, write_fn=write_fn)
    except Exception as error:  # noqa: BLE001 - 入口崩溃必须如实记录
        entrypoint_error = f"{type(error).__name__}: {error}"
        exit_code = 3

    final_obs = observe(candidate, state_root)
    terminal = bool(final_obs and final_obs["goal_status"] == "verified_done")
    if terminal:
        # typed 链已达 VERIFIED_DONE：文字诊断标签不能覆盖事实。
        operator.stop_reason = "verified_done"
    if args.mode == "inject":
        phase_ok = operator.pause_sent and operator.stop_reason == "paused_for_resume"
    else:
        phase_ok = terminal
    result = {
        "phase": args.mode,
        "pid": os.getpid(),
        "exit_code": exit_code,
        "entrypoint_error": entrypoint_error,
        "phase_ok": phase_ok,
        "stop_reason": operator.stop_reason,
        "terminal": terminal,
        "final_observation": final_obs,
        "start_observation": operator.start_observation,
        "task_sent": operator.task_sent,
        "consent_decisions": operator.consent_decisions,
        "scope_authorizations": operator.scope_authorizations,
        "resumes": operator.resumes,
        "continue_decisions": operator.continue_decisions,
        "injected": operator.injected,
        "injection_point": operator.injection_point,
        "injected_fact_id": operator.injected_fact_id,
        "pre_injection": operator.pre_injection,
        "consumption": operator.consumption,
        "pause_sent": operator.pause_sent,
        "resume_sent": operator.resume_sent,
        "ledger_lines": _ledger_lines(ledger),
        "events": operator.events,
        "frozen_inputs": {
            "initial_prompt": operator.task,
            "correction": operator.correction,
        },
        "tail_messages": messages[-12:],
    }
    args.result.parent.mkdir(parents=True, exist_ok=True)
    args.result.write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "phase": args.mode,
                "pid": result["pid"],
                "stop_reason": result["stop_reason"],
                "terminal": terminal,
                "phase_ok": phase_ok,
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        flush=True,
    )
    return result


def _child(
    args,
    *,
    mode: str,
    result_path: Path,
    state_root: Path,
    ledger: Path,
    extra: list[str],
    timeout: float,
) -> subprocess.CompletedProcess:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "run",
        str(args.candidate.resolve(strict=True)),
        "--mode",
        mode,
        "--state-root",
        str(state_root),
        "--ledger",
        str(ledger),
        "--result",
        str(result_path),
        "--provider",
        args.provider,
        *extra,
    ]
    # C.2（2026-10-18）：安装模式显式透传装配参数；子进程与父进程共用源码树
    # 外的同一中立 cwd（父进程 bootstrap 已 chdir），绝不回落 cwd=_ROOT。
    installed_site = getattr(args, "installed_site", None)
    if installed_site is not None:
        command.extend(
            ("--installed-site", str(installed_site), "--origin-log", str(args.origin_log))
        )
        # bootstrap 已把父进程 chdir 到中立 cwd；显式传给子进程，绝不回落 _ROOT。
        cwd = str(getattr(args, "neutral_cwd", None) or Path.cwd())
    else:
        cwd = str(_ROOT)
    return subprocess.run(command, cwd=cwd, timeout=timeout, check=False)


def _provider_extra(args) -> list[str]:
    extra: list[str] = []
    if args.provider != "fake":
        extra.extend(
            (
                "--model",
                args.model,
                "--base-url",
                args.base_url,
                "--credential-env",
                args.credential_env,
                "--thinking-mode",
                args.thinking_mode,
                "--timeout",
                str(args.timeout),
                "--max-model-attempts",
                str(args.max_model_attempts),
            )
        )
    # W3：干预上限必须按相同值传入 run 子进程，独立于 provider 是否 fake。
    extra.extend(
        (
            "--max-consents",
            str(args.max_consents),
            "--max-resumes",
            str(args.max_resumes),
        )
    )
    return extra


def _finalize(args, phase_results: list[dict], *, mode: str, wall_seconds: float) -> dict:
    from scripts.coding_scenario_grader import grade_scenario

    candidate = args.candidate.resolve(strict=True)
    state_root = args.state_root.resolve()
    final_obs = observe(candidate, state_root)
    typed_terminal = bool(final_obs and final_obs["goal_status"] == "verified_done")
    extra_failures: list[str] = []
    try:
        business = grade_scenario("D04", candidate)
    except Exception as error:  # noqa: BLE001 - grader 崩溃必须如实记录而非伪装
        business = {}
        extra_failures.append(
            f"business grader failed to execute: {type(error).__name__}: {error}"
        )
    try:
        supplemental = _frozen_probe(candidate)
    except Exception as error:  # noqa: BLE001 - 探针崩溃必须如实记录而非伪装
        supplemental = {"probe_execution": False}
        extra_failures.append(
            f"supplemental probe failed to execute: {type(error).__name__}: {error}"
        )
    physical_requests = _ledger_lines(args.ledger.resolve())
    exit_codes = [int(item.get("exit_code", 1)) for item in phase_results]
    if mode == "staged":
        phase_a = phase_results[0] if phase_results else {}
        phase_b = phase_results[1] if len(phase_results) > 1 else {}
        evidence = _staged_evidence(phase_a, phase_b, final_obs)
        evidence["phase_a"] = {
            "pid": phase_a.get("pid"),
            "stop_reason": phase_a.get("stop_reason"),
            "phase_ok": phase_a.get("phase_ok"),
            "consent_decisions": phase_a.get("consent_decisions"),
            "continue_decisions": phase_a.get("continue_decisions"),
        }
        evidence["phase_b"] = {
            "pid": phase_b.get("pid"),
            "stop_reason": phase_b.get("stop_reason"),
            "phase_ok": phase_b.get("phase_ok"),
            "resume_sent": phase_b.get("resume_sent"),
            "continue_decisions": phase_b.get("continue_decisions"),
            "consent_decisions": phase_b.get("consent_decisions"),
        }
        stop_reason = (
            phase_a.get("stop_reason") if not phase_b else phase_b.get("stop_reason")
        )
        if typed_terminal:
            stop_reason = "verified_done"
    else:
        phase = phase_results[0] if phase_results else {}
        evidence = {
            "pid": phase.get("pid"),
            "stop_reason": phase.get("stop_reason"),
            "consent_decisions": phase.get("consent_decisions"),
            "scope_authorizations": phase.get("scope_authorizations"),
            "continue_decisions": phase.get("continue_decisions"),
            "resumes": phase.get("resumes"),
            "correction_injected": bool(
                phase.get("injected") and phase.get("injection_point")
            ),
        }
        stop_reason = phase.get("stop_reason")
        if typed_terminal:
            stop_reason = "verified_done"
    record = evaluate_final(
        mode=mode,
        typed_terminal=typed_terminal,
        business=business,
        supplemental=supplemental,
        stop_reason=stop_reason,
        exit_codes=exit_codes,
        physical_requests=physical_requests,
        max_requests=args.max_model_attempts,
        evidence=evidence,
        extra_failures=extra_failures,
    )
    record.update(
        {
            "driver": "scripts/run_task_trust_d04.py",
            "candidate": str(candidate),
            "state_root": str(state_root),
            "ledger": str(args.ledger.resolve()),
            # C.2（2026-10-18）：安装身份单列；source 模式不可签 installed-real。
            "install": {
                "identity": (
                    "installed"
                    if getattr(args, "installed_site", None) is not None
                    else "source"
                ),
                "installed_site": (
                    str(args.installed_site)
                    if getattr(args, "installed_site", None) is not None
                    else None
                ),
                "origin_log": (
                    str(args.origin_log)
                    if getattr(args, "origin_log", None) is not None
                    else None
                ),
                "neutral_cwd": getattr(args, "neutral_cwd", None),
                "parent_pid": os.getpid(),
                "parent_executable": sys.executable,
            },
            "wall_seconds": round(wall_seconds, 3),
            "final_observation": final_obs,
            "frozen_inputs": {
                "initial_prompt": INITIAL_PROMPT,
                "correction": CORRECTION,
            },
        }
    )
    if record["install"]["identity"] == "installed":
        # 安装模式绝不悄悄回退：任何 origin guard 错误都进判据。
        origin_errors = [
            f"installed origin guard error: {item}"
            for item in _origin_log_errors(Path(args.origin_log))
        ]
        if origin_errors:
            record["failures"] = [*record["failures"], *origin_errors]
            record["product_status"] = "incomplete"
    args.result.parent.mkdir(parents=True, exist_ok=True)
    args.result.write_text(
        json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(record, ensure_ascii=False, sort_keys=True), flush=True)
    return record


def _journey(args) -> int:
    state_root = args.state_root.resolve()
    ledger = args.ledger.resolve()
    _ensure_private_dir(state_root.parent)
    _ensure_private_dir(ledger.parent)
    extra = _provider_extra(args)
    phase_results: list[dict] = []
    failures: list[str] = []
    started = time.monotonic()
    deadline = started + args.wall_seconds

    def remaining() -> float:
        return deadline - time.monotonic()

    def run_phase(mode: str, result_path: Path) -> dict:
        budget = remaining()
        if budget <= 5.0:
            failures.append(f"sample wall budget exhausted before the {mode} phase")
            return {"exit_code": 124, "stop_reason": "sample_wall_budget_exhausted"}
        try:
            completed = _child(
                args,
                mode=mode,
                result_path=result_path,
                state_root=state_root,
                ledger=ledger,
                extra=extra,
                timeout=budget,
            )
            exit_code = completed.returncode
        except subprocess.TimeoutExpired:
            failures.append(f"sample wall budget exceeded in the {mode} phase")
            exit_code = 124
        except Exception as error:  # noqa: BLE001 - 子进程启动失败也必须如实记录
            failures.append(
                f"{mode} phase could not start: {type(error).__name__}: {error}"
            )
            exit_code = 3
        if result_path.exists():
            phase = json.loads(result_path.read_text(encoding="utf-8"))
            # 不覆盖 phase 文件里的产品自身退出码（run_first_agent 返回值）；
            # driver 子进程返回码单列，避免同义反复式失败项。
            phase["driver_exit_code"] = exit_code
            return phase
        return {"exit_code": exit_code, "stop_reason": "child_result_missing"}

    if args.mode == "normal":
        phase_results.append(run_phase("normal", args.result.with_suffix(".phase.json")))
    else:
        phase_a = run_phase("inject", args.result.with_suffix(".a.json"))
        phase_results.append(phase_a)
        if phase_a.get("stop_reason") == "paused_for_resume":
            phase_results.append(run_phase("resume", args.result.with_suffix(".b.json")))
        else:
            failures.append(
                "injection phase did not pause for resume; resume phase skipped"
            )
    try:
        record = _finalize(
            args, phase_results, mode=args.mode, wall_seconds=time.monotonic() - started
        )
    except Exception as error:  # noqa: BLE001 - 判定失败也必须留下如实记录
        record = {
            "mode": args.mode,
            "product_status": "incomplete",
            "failures": [f"finalization failed: {type(error).__name__}: {error}"],
            "phase_stop_reasons": [
                item.get("stop_reason") for item in phase_results
            ],
        }
        args.result.parent.mkdir(parents=True, exist_ok=True)
        args.result.write_text(
            json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(record, ensure_ascii=False, sort_keys=True), flush=True)
        return 1
    if failures:
        record["failures"] = [*failures, *record["failures"]]
        record["product_status"] = "incomplete"
        args.result.write_text(
            json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
    return 0 if record["product_status"] == "completed" else 1


def _maybe_bootstrap_install_guard(args) -> None:
    """C.2（2026-10-18）：固定用途安装装配——在任何产品模块导入前装 guard。

    fail closed：参数必须成对；site 必须真实存在；产品模块已被源码预加载即
    拒绝（不清 sys.modules 假装干净）。ROOT 只供定位测试资料，产品导入由
    guard 强制从 installed-site 解析。父进程离开源码树到中立 cwd；子进程由
    _child 以同一 cwd 启动。
    """

    site_arg = getattr(args, "installed_site", None)
    log_arg = getattr(args, "origin_log", None)
    if site_arg is None and log_arg is None:
        return
    if site_arg is None or log_arg is None:
        raise SystemExit(
            "refusing: --installed-site and --origin-log must be provided together"
        )
    from scripts._019_installed_pytest import FIXED_PRODUCT_ROOTS, install_guard

    polluted = sorted(
        name
        for name in sys.modules
        if name.partition(".")[0] in FIXED_PRODUCT_ROOTS
    )
    if polluted:
        raise SystemExit(
            "refusing: product modules already imported before install guard: "
            f"{polluted}"
        )
    try:
        site = Path(site_arg).resolve(strict=True)
    except OSError as error:
        raise SystemExit(f"refusing: installed site unusable: {error}") from error
    if not site.is_dir():
        raise SystemExit(f"refusing: installed site is not a directory: {site}")
    # chdir 前先把工作路径绝对化，避免中立 cwd 破坏相对路径。
    for name in ("candidate", "state_root", "ledger", "result"):
        value = getattr(args, name, None)
        if value is not None:
            setattr(args, name, Path(value).resolve())
    log = Path(log_arg).resolve()
    log.parent.mkdir(parents=True, exist_ok=True)
    install_guard(str(site), str(_ROOT), str(log))
    args.installed_site = site
    args.origin_log = log
    cwd = Path.cwd().resolve()
    if cwd == _ROOT or _ROOT in cwd.parents:
        neutral = Path(args.result).parent / "installed-cwd"
        neutral.mkdir(parents=True, exist_ok=True)
        os.chdir(neutral)
    args.neutral_cwd = str(Path.cwd().resolve())


def _origin_log_errors(path: Path) -> list[str]:
    """安装模式 origin 追溯：任何 error 事件都让判据失败，绝不悄悄回退。"""

    if not path.exists():
        return [f"origin log missing: {path}"]
    errors: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        try:
            event = json.loads(line)
        except ValueError:
            errors.append("origin log has a broken line")
            continue
        if event.get("error") is not None:
            errors.append(
                f"{event.get('module')}: {event.get('error')} ({event.get('origin')})"
            )
    return errors


def _add_provider_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--provider",
        default="openai_compatible",
        choices=("fake", "openai_compatible"),
    )
    parser.add_argument("--model", default="deepseek-v4-flash")
    parser.add_argument("--base-url", default="https://api.deepseek.com")
    parser.add_argument("--credential-env", default="DEEPSEEK_API_KEY")
    parser.add_argument(
        "--thinking-mode", default="disabled", choices=("enabled", "disabled")
    )
    parser.add_argument("--max-model-attempts", type=int, default=MAX_REQUESTS_PER_SAMPLE)
    parser.add_argument("--max-consents", type=int, default=40)
    parser.add_argument("--max-resumes", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=240.0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("candidate", type=Path)
    prepare.add_argument("--staged", action="store_true")
    prepare.add_argument("--result", type=Path, required=True)

    run = subparsers.add_parser("run")
    run.add_argument("candidate", type=Path)
    run.add_argument("--mode", choices=("normal", "inject", "resume"), required=True)
    run.add_argument("--state-root", type=Path, required=True)
    run.add_argument("--ledger", type=Path, required=True)
    run.add_argument("--result", type=Path, required=True)
    run.add_argument(
        "--installed-site",
        type=Path,
        default=None,
        help="installed site-packages 目录；产品模块只允许从这里解析（与 --origin-log 成对）",
    )
    run.add_argument(
        "--origin-log",
        type=Path,
        default=None,
        help="安装导入 origin 追溯日志（与 --installed-site 成对）",
    )
    _add_provider_options(run)

    journey = subparsers.add_parser("journey")
    journey.add_argument("candidate", type=Path)
    journey.add_argument("--mode", choices=("normal", "staged"), required=True)
    journey.add_argument("--state-root", type=Path, required=True)
    journey.add_argument("--ledger", type=Path, required=True)
    journey.add_argument("--result", type=Path, required=True)
    journey.add_argument("--wall-seconds", type=float, default=1800.0)
    journey.add_argument(
        "--installed-site",
        type=Path,
        default=None,
        help="installed site-packages 目录；产品模块只允许从这里解析（与 --origin-log 成对）",
    )
    journey.add_argument(
        "--origin-log",
        type=Path,
        default=None,
        help="安装导入 origin 追溯日志（与 --installed-site 成对）",
    )
    _add_provider_options(journey)

    args = parser.parse_args(argv)
    if args.command in {"run", "journey"}:
        _maybe_bootstrap_install_guard(args)
    if args.command == "prepare":
        _prepare(args)
        return 0
    if args.command == "run":
        result = _run_journey(args)
        return 0 if result.get("phase_ok") else 1
    return _journey(args)


if __name__ == "__main__":
    raise SystemExit(main())
