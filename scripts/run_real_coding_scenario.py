"""Run one bounded real-model coding fixture without coaching the model.

The operator adapter only resolves product governance prompts. It never chooses a
tool, supplies a file location, interprets a failure, or requests a test, or
reminds the model to finish. A return to the prompt before VERIFIED_DONE is a
failed run.

F3a/F3d（2026-10-02）：完成与操作证明只依据 typed 终态（本次合成 state 的
GoalStatus + durable evidence records + 资源事实）；文字提示只作 UI/operator 辅助。
记录合同与 scripts/grade_coding_autonomy.py 的 exact key set 同步（schema 2）；
任何 provider 发送前先核对 manifest 授权/预算/模型配置，零授权零预算拒绝执行。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# 以文件方式直接运行（python scripts/run_real_coding_scenario.py）时，仓库根
# 不在 sys.path；先引导根目录再做本仓库导入（测试经 pytest 导入不受影响）。
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from main import main as run_first_agent  # noqa: E402  (sys.path bootstrap above)
from scripts.coding_scenario_grader import (  # noqa: E402  (bootstrap above)
    grade_scenario,
    unverified_reasons,
)

ROOT = _ROOT
MANIFEST = (
    ROOT
    / "docs"
    / "handoffs"
    / "2026-09-13-coding-autonomy-repair"
    / "TASK-MANIFEST.json"
)
# F3d：有界公开 allowlist（First Agent 来源 / 被测 candidate / manifest /
# fixture / 独立 grader 身份）；只摘要明确公开文件字节，不收集秘密或真实日志。
_SOURCE_ALLOWLIST = (
    "pyproject.toml",
    "main.py",
    "agent/composition.py",
    "agent/runtime/evidence.py",
    "agent/runtime/tools.py",
    "agent/runtime/loop.py",
    "agent/runtime/state.py",
    "agent/runtime/contracts.py",
    "agent/runtime/control.py",
    "agent/runtime/checkpoint.py",
    "agent/runtime/views.py",
    "agent/runtime/compaction_rules.py",
    "agent/browser/tools.py",
    "agent/cli/app.py",
    "agent/cli/render.py",
    "agent/cli/actions.py",
    "agent/tui/app.py",
    "agent/tui/render.py",
    "agent/tui/adapter.py",
    "agent/sandbox/tools.py",
    "scripts/f2_f3_local_browser_journeys.py",
    "agent/tui/dialogs.py",
)
_GRADER_FILES = (
    "scripts/coding_scenario_grader.py",
    "tests/acceptance/fixtures/grader/d06_app_behavior.test.mjs",
)

@dataclass
class DogfoodOperator:
    task: str
    max_consents: int
    max_resumes: int
    task_sent: bool = False
    consent_decisions: int = 0
    resumes: int = 0
    stop_reason: str | None = None
    approved_tools: list[str] | None = None

    def __post_init__(self) -> None:
        self.approved_tools = []

    def next_input(self, recent_messages: tuple[str, ...]) -> str:
        rendered = "\n".join(recent_messages)
        # F3a：文字只作 UI/operator 辅助。"Task is closed." 可能是 CANCELLED 的
        # UI 提示或模型文本，不再据此签完成——完成只由 typed GoalStatus 判定。
        if not self.task_sent:
            self.task_sent = True
            return self.task
        if "Remote provider disclosure required" in rendered:
            return self._consent()
        if "Approval required" in rendered:
            tool_match = re.search(r"(?:^|\n)tool: ([^\n]+)", rendered)
            if tool_match is not None:
                assert self.approved_tools is not None
                self.approved_tools.append(tool_match.group(1).strip())
            return self._consent()
        if (
            "Task paused at a safe execution limit." in rendered
            or "provider failed transiently" in rendered.casefold()
            or "provider timed out" in rendered.casefold()
            or "provider could not be reached" in rendered.casefold()
            or "provider is temporarily unavailable" in rendered.casefold()
        ):
            if self.resumes < self.max_resumes:
                self.resumes += 1
                return "/resume"
            self.stop_reason = "resume_budget_exhausted"
            return "/exit"
        self.stop_reason = "unexpected_idle_before_verified_done"
        return "/exit"

    def _consent(self) -> str:
        if self.consent_decisions >= self.max_consents:
            self.stop_reason = "consent_budget_exhausted"
            return "/exit"
        self.consent_decisions += 1
        return "y"

def _scenario(scenario_id: str) -> dict[str, object]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for scenario in manifest["scenarios"]:
        if scenario["id"] == scenario_id:
            return scenario
    raise ValueError(f"unknown scenario: {scenario_id}")


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if ".git" in relative.parts or "__pycache__" in relative.parts:
            continue
        if path.is_symlink():
            digest.update(f"L:{relative}:{path.readlink()}\n".encode())
        elif path.is_file():
            digest.update(f"F:{relative}:".encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _file_list_digest(root: Path, relative_paths: tuple[str, ...]) -> str:
    digest = hashlib.sha256()
    for relative in relative_paths:
        digest.update(f"F:{relative}:".encode())
        digest.update((root / relative).read_bytes())
    return digest.hexdigest()


def _ledger_lines(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line)

def _load_final_state(workspace: Path, state_root: Path):
    """R2a：经真实只读发现读取本次合成的唯一 session 终态。

    真实布局是 ``state_root/workspaces/<scope>/<conversation>.json``；错绑
    workspace、零会话、多会话都明确失败，不递归扫描历史碰运气。
    """

    from agent.continuity.sessions import inspect_workspace_sessions

    inspection = inspect_workspace_sessions(
        workspace, state_root=state_root, home=None
    )
    snapshots = tuple(inspection.snapshots)
    if len(snapshots) != 1:
        raise ValueError(
            "expected exactly one synthesized session under "
            f"{state_root}, found {len(snapshots)}"
        )
    return snapshots[0].state


def _typed_completion(state) -> bool:
    from agent.runtime.contracts import GoalStatus

    goal = state.goal
    return goal is not None and goal.status is GoalStatus.VERIFIED_DONE


def _passed_evidence_criteria(state) -> set[str]:
    from agent.runtime.contracts import GoalStatus

    goal = state.goal
    if goal is None or goal.status is not GoalStatus.VERIFIED_DONE:
        return set()
    return {
        record.criterion_id
        for record in state.evidence_records
        if record.passed
        and record.goal_id == goal.goal_id
        and record.goal_revision == goal.revision
    }


def product_ran_related_tests(state) -> tuple[bool, str]:
    """相关验证证明：用户权威 local-process criterion 的 passed 证据记录。

    其他任务旧 receipt / grader 自跑测试 / 未执行审批 / 无关 exit-0 process
    都不构成"产品自跑相关测试"；没有用户权威 local-process criterion 时
    fail closed（诚实 false + reason），不退回宽松启发式。
    """

    from agent.runtime.contracts import GoalStatus
    from agent.runtime.evidence import ClosedEvidenceRegistry

    goal = state.goal
    if goal is None or goal.status is not GoalStatus.VERIFIED_DONE:
        return False, "goal did not reach typed VERIFIED_DONE"
    required_process = tuple(
        item
        for item in goal.admitted_criteria
        if item.mandatory
        and item.criterion_id.startswith("criterion:required-local-process:")
    )
    if not required_process:
        return False, "no user-authoritative local-process criterion was admitted"
    # B07：passed 记录必须能由内核从 durable facts 重验；孤立/手填/异 Goal 的
    # 记录在 derive 处 fail closed（沙箱或 process 准入链都会在这里复验）。
    try:
        ClosedEvidenceRegistry().derive(state, state.completion_claim,
                                        observed_at=goal.updated_at)
    except Exception as error:
        return False, f"evidence does not rederive from durable facts: {error}"
    passed = _passed_evidence_criteria(state)
    missing = tuple(
        item.criterion_id
        for item in required_process
        if item.criterion_id not in passed
    )
    if missing:
        return False, "required local-process criterion has no passed evidence"
    return True, ""

def _managed_web_receipts(state) -> tuple[bool, bool]:
    """返回 (started_ready, stopped_confirmed)：managed_web durable 执行事实。"""

    from agent.runtime.contracts import FactKind

    started = False
    stopped = False
    for fact in state.facts:
        if (
            fact.kind is not FactKind.TOOL_RESULT
            or fact.content.get("executed") is not True
            or fact.content.get("is_error") is not False
        ):
            continue
        metadata = fact.content.get("metadata")
        if not isinstance(metadata, dict):
            continue
        tool_name = metadata.get("tool_name")
        if tool_name not in {"managed_web_start", "managed_web_stop"}:
            continue
        try:
            payload = json.loads(str(fact.content.get("text", "")))
        except json.JSONDecodeError as error:
            raise ValueError("managed resource receipt is malformed") from error
        if tool_name == "managed_web_start" and payload.get("status") == "ready":
            started = True
        elif tool_name == "managed_web_stop" and payload.get("cleanup") == "confirmed":
            stopped = True
    return started, stopped


def _browser_executed_facts(state) -> dict[str, bool]:
    """browser 执行事实（受治理 receipt）：open / effect_applied action / cleaned close。"""

    from agent.runtime.contracts import FactKind

    view = {"open": False, "action_applied": False, "closed": False}
    for fact in state.facts:
        if (
            fact.kind is not FactKind.TOOL_RESULT
            or fact.content.get("executed") is not True
            or fact.content.get("is_error") is not False
       ):
            continue
        metadata = fact.content.get("metadata")
        if not isinstance(metadata, dict):
            continue
        browser_kind = metadata.get("browser_result_kind")
        if browser_kind == "browser_open":
            view["open"] = True
        elif browser_kind == "browser_close":
            view["closed"] = True
        elif (
            metadata.get("browser_receipt_kind") == "browser_action_v1"
            and metadata.get("outcome") == "effect_applied"
        ):
            view["action_applied"] = True
    return view

def _resource_closure(state) -> bool:
    """资源门槛：exact start/stop + open/action/close 事实之后，无遗留 active 资源。"""

    from agent.runtime.resource_lifecycle import active_task_resources

    resources = active_task_resources(state.facts)
    return not resources.browser_sessions and not resources.managed_processes


def build_record_v2(
    *,
    scenario_id: str,
    manifest_sha256: str,
    candidate_digest: str,
    fixture_digest: str,
    source_digest: str,
    grader_digest: str,
    execution_identity: str,
    model_identity: dict,
    product_status: str,
    checks: dict,
    unverified_reasons: dict,
    metrics: dict,
    physical_requests: int,
    stop_reason: str,
) -> dict:
    """F3d 最小显式记录形状（与 grade_coding_autonomy.py 的 exact key set 同步）。"""

    return {
        "schema_version": 2,
        "scenario_id": scenario_id,
        "manifest_sha256": manifest_sha256,
        "candidate_identity": f"sha256:{candidate_digest}",
        "fixture_identity": f"sha256:{fixture_digest}",
        "source_identity": f"sha256:{source_digest}",
        "grader_identity": f"sha256:{grader_digest}",
        "execution_identity": execution_identity,
        "model_identity": model_identity,
        "product_status": product_status,
        "independent_checks": checks,
        "unverified_reasons": unverified_reasons,
        "metrics": metrics,
        "physical_requests": physical_requests,
        "stop_reason": stop_reason,
        "notes": "",
    }

def _require_dispatch_authorized(manifest: dict, args) -> None:
    """F3d：任何 provider 发送前核对授权/预算/模型配置；不匹配即拒绝执行。"""

    if not manifest.get("real_dispatch_authorized"):
        raise SystemExit(
            "refusing to dispatch: manifest real_dispatch_authorized is false; "
            "authorization is an owner decision recorded in TASK-MANIFEST.json"
        )
    budget = manifest.get("window_budget", {}).get("max_physical_requests", 0)
    if not isinstance(budget, int) or isinstance(budget, bool) or budget <= 0:
        raise SystemExit("refusing to dispatch: manifest window budget is zero")
    # R2c：批准 N 次却配置 >N 次请求、wall 预算为 0，都在发送前拒绝。
    wall = manifest.get("window_budget", {}).get("max_wall_seconds", 0)
    if not isinstance(wall, int) or isinstance(wall, bool) or wall <= 0:
        raise SystemExit("refusing to dispatch: manifest wall budget is zero")
    attempts = getattr(args, "max_model_attempts", 0) or 0
    if attempts > budget:
        raise SystemExit(
            "refusing to dispatch: configured max-model-attempts "
            f"({attempts}) exceeds the approved request budget ({budget})"
        )
    model = manifest.get("model") or {}
    expected = {
        "provider": "openai_compatible",
        "model_id": args.model,
        "reasoning_mode": "enabled" if args.thinking_mode == "enabled" else "disabled",
    }
    if model != expected:
        raise SystemExit(
            "refusing to dispatch: model configuration does not match the manifest "
            f"(manifest={model!r}, configured={expected!r})"
        )
    if not os.environ.get(args.credential_env):
        raise SystemExit(
            f"refusing to dispatch: {args.credential_env} is not present in this shell"
        )

def run(args) -> dict[str, object]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest_sha256 = hashlib.sha256(MANIFEST.read_bytes()).hexdigest()
    offline = args.provider == "fake"
    if not offline:
        # R2c/R2d：离线脚本模式（--provider fake）不是真实派发，不走授权门；
        # 任何真实 provider 仍受 manifest 授权/预算/模型/凭据门控制。
        _require_dispatch_authorized(manifest, args)
    scenario = _scenario(args.scenario_id)
    if scenario.get("fixture") is None:
        raise ValueError(f"scenario is not materialized: {args.scenario_id}")
    candidate = args.candidate.resolve(strict=True)
    state_root = args.state_root.absolute()
    state_root.mkdir(mode=0o700, parents=True, exist_ok=False)
    ledger = args.ledger.absolute()
    ledger.parent.mkdir(parents=True, exist_ok=True)
    result_path = args.result.absolute()
    result_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_start = _ledger_lines(ledger)

    operator = DogfoodOperator(
        task=str(scenario["task"]),
        max_consents=args.max_consents,
        max_resumes=args.max_resumes,
    )
    messages: list[str] = []
    message_cursor = 0

    def write_fn(message: str) -> None:
        messages.append(message)
        print(message, flush=True)

    def input_fn(prompt: str) -> str:
        nonlocal message_cursor
        recent = tuple(messages[message_cursor:])
        decision = operator.next_input(recent)
        message_cursor = len(messages)
        if decision == operator.task:
            label = "<frozen-task>"
        elif decision == "y":
            label = "<governance-consent>"
        else:
            label = decision
        print(f"{prompt}{label}", flush=True)
        return decision

    argv = [
        "--workspace",
        str(candidate),
        "--state-root",
        str(state_root),
        "--provider",
        args.provider,
    ]
    if not offline:
        argv.extend(
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
    argv.extend(
        (
            "--transport-audit-ledger",
            str(ledger),
            "--max-model-attempts",
            str(args.max_model_attempts),
            "--without-owner-preferences",
        )
    )
    if args.browser:
        argv.append("--browser")
    if args.subagent:
        argv.append("--subagent")
    for skill_root in args.skill_root:
        argv.extend(("--skill-root", str(skill_root.resolve(strict=True))))
    if args.mcp_catalog is not None:
        argv.extend(
            (
                "--mcp-catalog",
                str(args.mcp_catalog.resolve(strict=True)),
                "--mcp-safety-state",
                str(args.mcp_safety_state.absolute()),
            )
        )
    if args.memory_create is not None:
        argv.extend(("--memory-create", str(args.memory_create.absolute())))
    exit_code = run_first_agent(argv, input_fn=input_fn, write_fn=write_fn)

    state = _load_final_state(candidate, state_root)
    completed = _typed_completion(state)
    scenario_required = tuple(scenario["required_checks"])
    business = grade_scenario(args.scenario_id, candidate)
    unknown = tuple(key for key in business if key not in scenario_required)
    if unknown:
        raise ValueError(
            f"grader returned checks outside the manifest set: {sorted(unknown)}"
        )
    reasons = unverified_reasons(args.scenario_id)
    # R2b：全集从 manifest 构建；缺项/未知项 false + reason，拒绝 vacuous all()。
    checks = {key: False for key in scenario_required}
    checks.update(business)
    checks = {**checks, **{key: False for key in reasons}}
    if "product_ran_related_tests" in scenario_required:
        related, related_reason = product_ran_related_tests(state)
        checks["product_ran_related_tests"] = related
        if not related:
            reasons = {**reasons, "product_ran_related_tests": related_reason}
    if args.scenario_id == "D06":
        started, stopped = _managed_web_receipts(state)
        browser_view = _browser_executed_facts(state)
        checks["managed_server"] = bool(checks.get("managed_server") and started)
        checks["browser_behavior"] = bool(
            checks.get("browser_behavior") and browser_view["action_applied"]
        )
        checks["owned_resources_closed"] = bool(
            completed
            and started
            and stopped
            and browser_view["open"]
            and browser_view["action_applied"]
            and _resource_closure(state)
        )
    passed = completed and all(checks.values()) and exit_code == 0
    if completed:
        # typed 链已达 VERIFIED_DONE：operator 的 idle 诊断标签不能覆盖事实
        # （模型先输出"Task is closed."文案时 next_input 走 idle 分支）。
        operator.stop_reason = "verified_done"
    ledger_end = _ledger_lines(ledger)
    record = build_record_v2(
        scenario_id=args.scenario_id,
        manifest_sha256=manifest_sha256,
        candidate_digest=_tree_digest(candidate),
        fixture_digest=_tree_digest(ROOT / str(scenario["fixture"])),
        source_digest=_file_list_digest(ROOT, _SOURCE_ALLOWLIST),
        grader_digest=_file_list_digest(ROOT, _GRADER_FILES),
        execution_identity=(
            "offline_scripted" if offline else "real_model"
        ),
        model_identity=(
            {
                "provider": "fake",
                "model_id": "scripted",
                "reasoning_mode": "disabled",
            }
            if offline
            else {
                "provider": "openai_compatible",
                "model_id": args.model,
                "reasoning_mode": (
                    "enabled" if args.thinking_mode == "enabled" else "disabled"
                ),
            }
        ),
        product_status="completed" if passed else "incomplete",
        checks=checks,
        unverified_reasons=reasons,
        metrics={
            "business_reminders": 0,
            "human_check_rescues": 0,
            "human_finish_rescues": 0,
            "consent_decisions": operator.consent_decisions,
            "external_grader_runs": 1,
            "ledger_start": ledger_start,
            "ledger_end": ledger_end,
        },
        physical_requests=max(0, ledger_end - ledger_start),
        stop_reason=operator.stop_reason or ("verified_done" if passed else "incomplete"),
    )
    result_path.write_text(
        json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(record, ensure_ascii=False, sort_keys=True), flush=True)
    return record

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario_id")
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--provider", default="openai_compatible")
    parser.add_argument("--model", default="deepseek-v4-flash")
    parser.add_argument("--base-url", default="https://api.deepseek.com")
    parser.add_argument("--credential-env", default="DEEPSEEK_API_KEY")
    parser.add_argument("--thinking-mode", default="enabled", choices=("enabled", "disabled"))
    parser.add_argument("--max-model-attempts", type=int, default=30)
    parser.add_argument("--max-consents", type=int, default=24)
    parser.add_argument("--max-resumes", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=240.0)
    parser.add_argument("--browser", action="store_true")
    parser.add_argument("--subagent", action="store_true")
    parser.add_argument("--skill-root", action="append", type=Path, default=[])
    parser.add_argument("--mcp-catalog", type=Path)
    parser.add_argument("--mcp-safety-state", type=Path)
    parser.add_argument("--memory-create", type=Path)
    args = parser.parse_args()
    if (args.mcp_catalog is None) != (args.mcp_safety_state is None):
        parser.error("--mcp-catalog and --mcp-safety-state must be used together")
    record = run(args)
    return 0 if record["product_status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
