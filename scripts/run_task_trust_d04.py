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

- E1-A（normal）：D04 场景本身含「运行中追加旧参数名」，故 normal 模式同样在
  首个安全边界交付冻结 correction；须观测注入与 durable 落盘，消费/版本推进
  作为过程证据如实报告（不满足不判失败），不要求 pause→resume。业务门 =
  grader 的两个有界键（latest_correction / final_validation）为 true 且补充
  探针全部通过。
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
CONTINUABLE_IDLE_STATUSES = frozenset({"needs_authority", "blocked", "goal_ready"})
CONTINUE_MESSAGE = "继续当前任务"
MAX_REQUESTS_PER_SAMPLE = 40
BOUND_BUSINESS_KEYS = ("latest_correction", "final_validation")
PROCESS_DECLARED_KEYS = ("resume_without_restatement", "no_effect_replay")
REQUIRED_EVIDENCE = {
    "normal": ("correction_injected",),
    "staged": (
        "correction_injected",
        "correction_durable",
        "correction_consumed",
        "version_changed",
        "paused_after_consumption",
        "resumed_in_new_process",
        "resume_advanced",
        "precondition_alias_checks_pending",
    ),
}

ProbeFn = Callable[[Path], "dict[str, bool]"]


# ---------------------------------------------------------------------------
# durable 只读观察
# ---------------------------------------------------------------------------


def observe(candidate: Path, state_root: Path) -> dict | None:
    """只读加载本次合成会话的 durable 投影；零创建、零 mutation。"""

    from agent.continuity.sessions import inspect_workspace_sessions
    from agent.runtime.contracts import FactKind

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
    pending = {
        "awaiting_approval": "approval",
        "awaiting_disclosure": "disclosure",
        "awaiting_recovery": "recovery",
        "paused_limit": "limit",
        "paused_retryable": "retryable",
    }.get(status or "")
    effects: dict[str, int] = {}
    correction_ids: list[str] = []
    for fact in state.facts:
        if (
            fact.kind is FactKind.USER_MESSAGE
            and fact.content.get("control") == "goal_correction"
        ):
            correction_ids.append(fact.fact_id)
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
    return {
        "goal_status": goal.status.value if goal is not None else None,
        "goal_id": goal.goal_id if goal is not None else None,
        "goal_revision": goal.revision if goal is not None else None,
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
        "executed_file_effects": sum(effects.values()),
        "effect_tools": effects,
        "correction_fact_ids": correction_ids,
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
    max_resumes: int = 2
    max_continues: int = 3
    task: str = INITIAL_PROMPT
    correction: str = CORRECTION
    task_sent: bool = False
    consent_decisions: int = 0
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
                return self._resume(obs)
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
            return self._resume(obs)
        if self._should_inject(obs):
            return self._inject(obs, "idle")
        if active is None and status in {"paused", "blocked"}:
            return self._resume(obs)
        if active is None and status in CONTINUABLE_IDLE_STATUSES:
            return self._continue(obs)
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
            return self._resume(obs)
        if active is None and status in {"paused", "blocked"}:
            return self._resume(obs)
        if active is None and status in CONTINUABLE_IDLE_STATUSES:
            return self._continue(obs)
        return self._stop(obs, "unexpected_idle_before_verified_done")

    # -- 内部决策 ----------------------------------------------------------

    def _should_inject(self, obs: dict) -> bool:
        return (
            self.mode in {"normal", "inject"}
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
        if fact_id is None or fact_id not in obs["created_from_fact_ids"]:
            return False
        if self.consumption is None:
            before = self.pre_injection or {}
            goal_before = before.get("goal_revision")
            state_before = before.get("state_revision")
            goal_after = obs["goal_revision"]
            state_after = obs["state_revision"]
            self.consumption = {
                "fact_id": fact_id,
                "goal_revision_before": goal_before,
                "goal_revision_after": goal_after,
                "state_revision_before": state_before,
                "state_revision_after": state_after,
                "goal_version_changed": bool(
                    goal_after is not None
                    and goal_before is not None
                    and goal_after > goal_before
                ),
                "state_version_changed": bool(
                    state_after is not None
                    and state_before is not None
                    and state_after > state_before
                ),
                "created_from_fact_ids": list(obs["created_from_fact_ids"]),
                "user_outcome": obs["user_outcome"],
            }
        return True

    def _consent(self, obs: dict) -> str:
        if self.consent_decisions >= self.max_consents:
            return self._stop(obs, "consent_budget_exhausted")
        self.consent_decisions += 1
        self._event("consent", obs)
        return "y"

    def _resume(self, obs: dict) -> str:
        if self.resumes >= self.max_resumes:
            return self._stop(obs, "resume_budget_exhausted")
        self.resumes += 1
        self._event("resume", obs)
        return "/resume"

    def _continue(self, obs: dict) -> str:
        if self.continue_decisions >= self.max_continues:
            return self._stop(obs, "continue_budget_exhausted")
        self.continue_decisions += 1
        self._event("continue", obs)
        return CONTINUE_MESSAGE

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
        if not business.get(name, False):
            failures.append(f"business check false: {name}")
    for name, passed in sorted(supplemental.items()):
        if not passed:
            failures.append(f"supplemental check false: {name}")
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
    return {
        "mode": mode,
        "product_status": "completed" if not failures else "incomplete",
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


def _consumption_view(phase: dict) -> dict:
    consumption = phase.get("consumption") or {}
    fact_id = consumption.get("fact_id")
    created = consumption.get("created_from_fact_ids") or []
    return {
        "fact_id": fact_id,
        "consumed": bool(fact_id and fact_id in created),
        "version_changed": bool(
            consumption.get("goal_version_changed")
            or consumption.get("state_version_changed")
        ),
        "goal_version_changed": bool(consumption.get("goal_version_changed")),
        "state_version_changed": bool(consumption.get("state_version_changed")),
        "user_outcome": consumption.get("user_outcome"),
    }


def _staged_evidence(phase_a: dict, phase_b: dict, final_obs: dict | None) -> dict:
    a_final = phase_a.get("final_observation") or {}
    checks = (phase_a.get("pre_injection") or {}).get("alias_checks") or {}
    consumption = _consumption_view(phase_a)
    b_start = phase_b.get("start_observation") or {}
    effects_after = (final_obs or {}).get("executed_file_effects", 0)
    revision_after = (final_obs or {}).get("goal_revision")
    typed_terminal = bool(final_obs and final_obs.get("goal_status") == "verified_done")
    return {
        "correction_injected": bool(
            phase_a.get("injected") and phase_a.get("injection_point")
        ),
        "correction_durable": bool(
            phase_a.get("injected_fact_id")
            and phase_a.get("injected_fact_id") in a_final.get("correction_fact_ids", [])
        ),
        "correction_consumed": consumption["consumed"],
        "version_changed": consumption["version_changed"],
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
                effects_after > (b_start.get("executed_file_effects") or 0)
                or (
                    revision_after is not None
                    and revision_after > (b_start.get("goal_revision") or 0)
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
        max_resumes=args.max_resumes,
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
    return subprocess.run(command, cwd=str(_ROOT), timeout=timeout, check=False)


def _provider_extra(args) -> list[str]:
    if args.provider == "fake":
        return []
    return [
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
    ]


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
            "wall_seconds": round(wall_seconds, 3),
            "final_observation": final_obs,
            "frozen_inputs": {
                "initial_prompt": INITIAL_PROMPT,
                "correction": CORRECTION,
            },
        }
    )
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


def main() -> int:
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
    _add_provider_options(run)

    journey = subparsers.add_parser("journey")
    journey.add_argument("candidate", type=Path)
    journey.add_argument("--mode", choices=("normal", "staged"), required=True)
    journey.add_argument("--state-root", type=Path, required=True)
    journey.add_argument("--ledger", type=Path, required=True)
    journey.add_argument("--result", type=Path, required=True)
    journey.add_argument("--wall-seconds", type=float, default=1800.0)
    _add_provider_options(journey)

    args = parser.parse_args()
    if args.command == "prepare":
        _prepare(args)
        return 0
    if args.command == "run":
        result = _run_journey(args)
        return 0 if result.get("phase_ok") else 1
    return _journey(args)


if __name__ == "__main__":
    raise SystemExit(main())
