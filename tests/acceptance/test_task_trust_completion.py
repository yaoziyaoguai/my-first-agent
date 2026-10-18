"""任务结果可信（R2/R3）业务验收：真实 Runtime 主 loop + 冻结业务判据。

本文件承载 2026-10-13 任务结果可信修复包及其 2026-10-14 接续包的跨层场景：
真实 composition/AgentRuntime/ToolRuntime/审批链不可绕过，只替换 provider 响应。
外部业务判据（独立 grader/补充断言）与被测产品代码隔离，不把 grader 导入
production Runtime，产品代码也不识别场景名或 grader 名称做特判。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from agent.composition import (
    build_composition,
    build_sandbox_resources,
    build_tool_registrations,
)
from agent.continuity.sessions import open_workspace_session
from agent.runtime.checkpoint import LocalCheckpointStore
from agent.runtime.context import ContextLimits
from agent.runtime.contracts import (
    BlockedClaim,
    CompletionClaim,
    EvidenceOracleKind,
    FactKind,
    GoalDelta,
    GoalDeltaProposal,
    GoalFrame,
    GoalStatus,
    ModelResponse,
    ModelTextBlock,
    ModelToolCall,
    ProposedCriterion,
    RequirementCoverage,
    ResolveApproval,
    RunStatus,
    SubmitMessage,
    canonical_json_digest,
)
from agent.runtime.control import ControlInbox
from agent.runtime.loop import InvocationLimits
from agent.runtime.state import authoritative_deliverable_file_paths
from tests.kernel.fakes import CollectingSink, goal_draft_from_frame

R3_TASK = "创建 notes.txt 并 运行 ./check.sh"
R3_CORRECTION = "不要运行 ./check.sh，只创建 notes.txt，其他要求不变。"
R3_NOTES_CONTENT = "withdrawal notes\n"


def _approval_now() -> str:
    return (
        datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )


def _make_workspace(tmp_path: Path, *, scripts: tuple[str, ...] = ()) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    for name in scripts:
        script = workspace / name
        script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        os.chmod(script, stat.S_IRWXU)
    return workspace


def _context_goal(context) -> dict:
    return next(
        (
            block
            for msg in reversed(context.messages)
            for block in msg.content
            if isinstance(block, dict) and block.get("type") == "trusted_goal"
        ),
        {},
    )


def _context_text(context) -> str:
    parts: list[str] = []
    for msg in context.messages:
        for block in msg.content:
            if isinstance(block, dict):
                parts.append(str(block.get("text", "")))
            else:
                parts.append(str(getattr(block, "text", "")))
    return "\n".join(parts)


def _sandbox_call(call_id: str, executable: str) -> ModelToolCall:
    return ModelToolCall(
        call_id,
        "sandbox_exec",
        {
            "executable": executable,
            "argv": [],
            "cwd": ".",
            "mode": "read-only",
            "network": "off",
        },
    )


def _claim_for(context, correlation: str, *, hollow: bool = False) -> CompletionClaim:
    """按 trusted_goal 投影抄写 completion_claim（含逐项 coverage）。

    与真实模型同型：只引用投影下发的闭合 id；coverage 引用当前 Goal 的全部
    权威来源 fact 与全部 mandatory criterion。``hollow=True`` 抄写同样的
    evidence refs 但不带任何 coverage——用于复现"缺逐项复核就想收尾"的模型
    行为，真实完成门必须拒绝它。
    """
    goal = _context_goal(context)
    mandatory_ids = tuple(
        item["criterion_id"]
        for item in goal["admitted_criteria"]
        if item.get("mandatory") is True
    )
    return CompletionClaim(
        correlation_id=correlation,
        goal_id=goal["goal_id"],
        goal_revision=goal["goal_revision"],
        criterion_evidence_refs=tuple(goal["expected_completion_evidence_refs"]),
        requirement_coverage=(
            ()
            if hollow
            else (
                RequirementCoverage(
                    requirement_id="requirement:task",
                    requirement="完成用户当前权威要求（含已消费 correction）",
                    source_fact_ids=tuple(goal["source_fact_ids"]),
                    status="satisfied",
                    criterion_ids=mandatory_ids,
                ),
            )
        ),
    )


def _open_and_drive(
    tmp_path: Path,
    provider,
    inbox: ControlInbox,
    *,
    checkpoint_store=None,
):
    opened = open_workspace_session(
        tmp_path / "workspace",
        state_root=tmp_path / "state",
        conversation_id_factory=lambda: "00000000-0000-4000-8000-0000000000b2",
    )
    binding = opened.workspace_binding
    registrations = tuple(
        build_tool_registrations(
            workspace=tmp_path / "workspace",
            protected_paths=(opened.checkpoint_path,),
            max_tool_result_chars=50_000,
        )
    ) + tuple(
        build_sandbox_resources(
            tmp_path / "workspace",
            tmp_path / "state",
            "/usr/bin:/bin",
            host_home=Path.home(),
        ).registrations
    )
    composition = build_composition(
        provider=provider,
        checkpoint_store=checkpoint_store
        if checkpoint_store is not None
        else opened.store,
        tool_registrations=registrations,
        event_sink=CollectingSink(),
        control_inbox=inbox,
        system_policy="Complete the task with exact evidence.",
        context_limits=ContextLimits(max_input_tokens=100_000, output_reserve=5_000),
        invocation_limits=InvocationLimits(),
        workspace_identity_digest=binding.workspace_identity_digest,
        context_scope_digest=binding.workspace_scope_digest,
        workspace_binding=binding,
    )
    return opened, composition


def _submit(state, run_id: str, message: str) -> SubmitMessage:
    return SubmitMessage(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        run_id=run_id,
        message=message,
    )


def _approve_pending(opened, composition) -> None:
    from agent.cli.app import _parse_action as _parse

    for _ in range(16):
        state = LocalCheckpointStore(opened.checkpoint_path).load().state
        active = state.active_run
        if active is None or active.pending_request is None:
            return
        action, error = _parse(
            f"/approve {active.pending_request.request_id}",
            state,
            lambda: "run-unused",
            approval_time_factory=_approval_now,
        )
        assert error is None and action is not None
        composition.runtime.run_turn(action, opened.store.load())


def _sandbox_receipt_count(state) -> int:
    return sum(
        1
        for fact in state.facts
        if fact.kind is FactKind.TOOL_RESULT
        and isinstance(fact.content.get("metadata"), dict)
        and fact.content["metadata"].get("sandbox_receipt_kind") is not None
    )


class _WithdrawalProvider:
    """R3 跨层证明的脚本 provider：按 ContextPack 实际内容推进阶段。

    run1：draft（文本自动铸 process 义务）→ sandbox 执行（真实审批+准入）；
    run2：correction 消费 delta（真实撤回/失效）→ 写文件 → 读回 → 显式 claim。
    """

    def __init__(self) -> None:
        self.calls = 0
        self.stage = "draft"

    def generate(self, context, *, delta_observer=None):  # noqa: ANN001, ANN202
        self.calls += 1
        goal = _context_goal(context)
        assert goal or self.stage == "draft", (
            "trusted_goal must be visible after the draft is accepted"
        )
        if self.stage == "draft":
            bootstrap = context.goal_bootstrap
            assert bootstrap is not None
            frame = GoalFrame(
                goal_id="goal-r3-withdrawal",
                revision=1,
                created_from_fact_ids=(bootstrap.source_fact_id,),
                workspace_identity_digest=bootstrap.workspace_identity_digest,
                user_outcome="notes.txt created and ./check.sh validation recorded",
                beneficiary="user",
                targets=("notes.txt",),
                scope=("workspace",),
                non_goals=(),
                assumptions=(),
                proposed_criteria=(
                    ProposedCriterion(
                        "criterion:notes-file",
                        "notes.txt exists with the requested content",
                        oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
                        artifact_path="notes.txt",
                    ),
                ),
                admitted_criteria=(),
                authority_snapshot=bootstrap.authority_snapshot,
                status=GoalStatus.GOAL_READY,
                created_at="2026-10-14T00:00:00Z",
                updated_at="2026-10-14T00:00:00Z",
            )
            self.stage = "validate"
            return ModelResponse((), control=goal_draft_from_frame("proposal-r3", frame))

        if self.stage == "validate":
            self.stage = "ack"
            return ModelResponse((_sandbox_call("run-check-1", "./check.sh"),))

        if self.stage == "ack":
            self.stage = "delta"
            return ModelResponse((ModelTextBlock("validation recorded"),))

        if self.stage == "delta":
            # 直接 correction 路径：权威 fact 已落盘、尚未被消费；GoalDelta
            # 是消费它的唯一合法路径（plain 用户消息不置 NEEDS_AUTHORITY）。
            assert R3_CORRECTION in _context_text(context), (
                "the withdrawal correction text must be visible to the model"
            )
            self.stage = "write"
            return ModelResponse(
                (),
                control=GoalDeltaProposal(
                    correlation_id="delta-r3-withdrawal",
                    delta=GoalDelta(
                        goal_id=str(goal["goal_id"]),
                        expected_revision=int(goal["goal_revision"]),
                        reason="user withdrew the validation requirement",
                        updates={
                            "user_outcome": (
                                "notes.txt created; the ./check.sh validation is "
                                "withdrawn by the user's correction"
                            )
                        },
                        updated_at=_approval_now(),
                    ),
                ),
            )

        if self.stage == "write":
            self.stage = "read"
            return ModelResponse(
                (
                    ModelToolCall(
                        "write-notes",
                        "write_file",
                        {"path": "notes.txt", "content": R3_NOTES_CONTENT},
                    ),
                )
            )

        if self.stage == "read":
            self.stage = "claim"
            return ModelResponse(
                (ModelToolCall("read-notes", "read_file", {"path": "notes.txt"}),)
            )

        if self.stage == "claim":
            assert R3_TASK in _context_text(context), (
                "the original authoritative task must stay visible"
            )
            return ModelResponse((), control=_claim_for(context, "claim-r3"))

        raise AssertionError(f"unexpected stage {self.stage}")


def test_r3_admitted_process_withdrawal_invalidates_and_completes_remaining_work(
    tmp_path: Path,
) -> None:
    """R3 跨层证明：真实准入的 process 义务被明确撤回后按既有机制失效。

    链路全部走真实主 loop：权威文本铸造义务 → sandbox 审批执行 → 真实
    TOOL_RECEIPT 准入 → 用户撤回 correction → GoalDelta 消费（apply_goal_delta
    移除旧 admission/清证据与 claim/leases）→ 无新执行 → 剩余文件任务以
    fresh readback 完成到 VERIFIED_DONE。不手工替换 admitted 集合。
    """

    workspace = _make_workspace(tmp_path, scripts=("check.sh",))
    inbox = ControlInbox()
    provider = _WithdrawalProvider()
    opened, composition = _open_and_drive(tmp_path, provider, inbox)

    # ---- run 1：任务 + 真实 sandbox 校验（审批执行 + Runtime 准入）。
    state = opened.store.load().state
    composition.runtime.run_turn(_submit(state, "run-r3-1", R3_TASK), opened.store.load())
    _approve_pending(opened, composition)

    after_run1 = LocalCheckpointStore(opened.checkpoint_path).load().state
    goal1 = after_run1.goal
    assert goal1 is not None
    admitted_process = [
        criterion
        for criterion in goal1.admitted_criteria
        if criterion.oracle_kind is EvidenceOracleKind.TOOL_RECEIPT
    ]
    assert admitted_process, (
        "the real sandbox approval + execution must mint a TOOL_RECEIPT admission"
    )
    assert any(
        criterion.criterion_id.startswith("criterion:required-local-process:")
        for criterion in goal1.proposed_criteria
    ), "the authoritative task text must mint the runtime-owned process obligation"
    receipts_after_run1 = _sandbox_receipt_count(after_run1)
    assert receipts_after_run1 == 1
    revision_after_run1 = goal1.revision

    # ---- run 2：撤回 correction → 真实 delta 消费 → 文件完成。
    composition.runtime.run_turn(
        _submit(after_run1, "run-r3-2", R3_CORRECTION), opened.store.load()
    )
    _approve_pending(opened, composition)

    final = LocalCheckpointStore(opened.checkpoint_path).load().state
    goal = final.goal
    assert goal is not None
    assert goal.status is GoalStatus.VERIFIED_DONE, (
        goal.status,
        [c.criterion_id for c in goal.admitted_criteria],
    )
    # 旧 process admission/验证版本按既有机制失效：TOOL_RECEIPT 全部移除，
    # 证据为新 revision 下的 fresh 文件 readback，授权租约清空。
    assert all(
        criterion.oracle_kind is not EvidenceOracleKind.TOOL_RECEIPT
        for criterion in goal.admitted_criteria
    )
    assert goal.revision > revision_after_run1
    assert final.evidence_records
    assert all(
        record.goal_revision == goal.revision for record in final.evidence_records
    )
    assert final.process_leases == () and final.sandbox_leases == ()
    # 撤回后零新执行：sandbox receipt 数量不变。
    assert _sandbox_receipt_count(final) == receipts_after_run1
    # 剩余文件任务真实完成：磁盘内容 + claim 覆盖全部权威来源。
    assert (workspace / "notes.txt").read_text(encoding="utf-8") == R3_NOTES_CONTENT
    claim = final.completion_claim
    assert claim is not None
    cited_sources = {
        fact_id
        for coverage in claim.requirement_coverage
        for fact_id in coverage.source_fact_ids
    }
    assert cited_sources == set(goal.created_from_fact_ids), (
        "coverage must cite every authoritative source, original and correction"
    )


# ---------------------------------------------------------------------------
# R2-C：D04 原始输入 → admission → 执行 → 外部业务判据的业务闭合。
# 冻结判据分两层：scripts/coding_scenario_grader.py（不改）与本文件独立的
# 补充业务探针（隔离子进程执行）；产品代码不识别 D04/retry_count/grader 名称。
# ---------------------------------------------------------------------------

D04_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "d04_resume_correction"
D04_SERVICE_PATH = "retry_app/service.py"
D04_CLI_PATH = "retry_app/cli.py"
D04_TASK = (
    "完成 retry_app 的 bounded retry 行为：瞬态 RuntimeError 失败需要重试，新的"
    "公开参数名是 max_retries，命令行适配器 retry_app/cli.py 必须使用同一个值；"
    "负数限制无效，一次操作的执行次数上限是 1 + max_retries。同时保留旧的"
    " retry_count 关键字与 CLI 选项作为别名；旧名与新名同时提供时必须拒绝这个"
    "有歧义的请求。"
)

# 参考修正实现与 tests/acceptance/test_coding_autonomy_grader.py 的 D04 参考
# 候选同源（本文件冻结独立拷贝）；修订中间版故意缺少 legacy 别名，供"新写入
# 使旧验证失效"旅程使用。
_D04_SERVICE_REFERENCE = (
    "from __future__ import annotations\n\n"
    "class RetryService:\n"
    "    def run(self, operation, *, max_retries=None, retry_count=None):\n"
    "        if max_retries is not None and retry_count is not None:\n"
    "            raise ValueError('retry limit is ambiguous')\n"
    "        limit = (retry_count if retry_count is not None else "
    "max_retries if max_retries is not None else 0)\n"
    "        if limit < 0:\n"
    "            raise ValueError('retry limit must not be negative')\n"
    "        for attempt in range(limit + 1):\n"
    "            try:\n"
    "                return operation()\n"
    "            except RuntimeError:\n"
    "                if attempt == limit:\n"
    "                    raise\n"
)
_D04_SERVICE_PARTIAL = (
    "from __future__ import annotations\n\n"
    "class RetryService:\n"
    "    def run(self, operation, *, max_retries=None):\n"
    "        limit = max_retries if max_retries is not None else 0\n"
    "        if limit < 0:\n"
    "            raise ValueError('retry limit must not be negative')\n"
    "        for attempt in range(limit + 1):\n"
    "            try:\n"
    "                return operation()\n"
    "            except RuntimeError:\n"
    "                if attempt == limit:\n"
    "                    raise\n"
)
_D04_CLI_REFERENCE = (
    "import argparse\n\n"
    "def parse_retry_limit(argv):\n"
    "    parser = argparse.ArgumentParser()\n"
    "    group = parser.add_mutually_exclusive_group()\n"
    "    group.add_argument('--max-retries', type=int)\n"
    "    group.add_argument('--retry-count', type=int)\n"
    "    args = parser.parse_args(argv)\n"
    "    value = args.retry_count if args.retry_count is not None else "
    "args.max_retries\n"
    "    return 0 if value is None else value\n"
)

# 独立补充业务探针：与 grader 的 in-process _candidate_import 完全分开，经
# 隔离子进程（-I -B + 显式 sys.path 注入）执行 SPEC.md 的业务语义。
_D04_PROBE = r'''
import io
import json
import sys
from contextlib import redirect_stderr

sys.path.insert(0, sys.argv[1])

from retry_app import RetryService
from retry_app.cli import parse_retry_limit

checks = {}


def _counter(failures):
    state = {"attempts": 0}

    def operation():
        state["attempts"] += 1
        if state["attempts"] <= failures:
            raise RuntimeError("transient")
        return "done"

    return state, operation


def _record(name, probe):
    try:
        checks[name] = bool(probe())
    except Exception:
        checks[name] = False


state, operation = _counter(2)
_record("transient_new_name", lambda: (
    RetryService().run(operation, max_retries=2) == "done"
    and state["attempts"] == 3
))
state, operation = _counter(2)
_record("legacy_alias", lambda: (
    RetryService().run(operation, retry_count=2) == "done"
    and state["attempts"] == 3
))
state, operation = _counter(0)
_record("default_single_attempt", lambda: (
    RetryService().run(operation) == "done" and state["attempts"] == 1
))


def _bounded():
    state, operation = _counter(99)
    try:
        RetryService().run(operation, max_retries=2)
    except RuntimeError:
        return state["attempts"] == 3
    return False


def _conflict():
    try:
        RetryService().run(lambda: "done", max_retries=1, retry_count=1)
    except (TypeError, ValueError):
        return True
    return False


def _negative():
    try:
        RetryService().run(lambda: "done", max_retries=-1)
    except (TypeError, ValueError):
        return True
    return False


def _cli_both_names():
    try:
        with redirect_stderr(io.StringIO()):
            new_value = parse_retry_limit(["--max-retries", "3"])
            old_value = parse_retry_limit(["--retry-count", "2"])
    except SystemExit:
        return False
    return new_value == 3 and old_value == 2


checks["bounded_attempts"] = _bounded()
checks["conflict_rejected"] = _conflict()
checks["negative_invalid"] = _negative()
checks["cli_both_names"] = _cli_both_names()
print(json.dumps(checks))
'''


def _supplemental_d04_checks(candidate: Path) -> dict[str, bool]:
    """对候选目录执行冻结的补充业务判据，返回逐项 bool。"""

    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            "-c",
            _D04_PROBE,
            str(candidate),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(candidate.parent),
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return {
        str(key): bool(value) for key, value in json.loads(completed.stdout).items()
    }


def test_supplemental_d04_checks_freeze_unmodified_fixture_red(
    tmp_path: Path,
) -> None:
    """冻结负例：未修复的 D04 副本不能通过补充业务判据。

    默认单次成功是 fixture 本来就满足的行为（非回归项），其余业务要求
    （新名重试、legacy 别名、有界次数、负数拒绝、CLI 双名）全部为 False。
    """

    candidate = tmp_path / "cand-unmodified"
    shutil.copytree(D04_FIXTURE, candidate, ignore=shutil.ignore_patterns("__pycache__"))

    checks = _supplemental_d04_checks(candidate)

    assert checks["default_single_attempt"] is True
    failed = {name for name, passed in checks.items() if not passed}
    assert failed == {
        "transient_new_name",
        "legacy_alias",
        "bounded_attempts",
        "negative_invalid",
        "cli_both_names",
    }, checks


def test_supplemental_d04_checks_accept_reference_candidate(tmp_path: Path) -> None:
    """冻结正例：参考修正实现通过全部补充业务判据。"""

    candidate = tmp_path / "cand-reference"
    shutil.copytree(D04_FIXTURE, candidate, ignore=shutil.ignore_patterns("__pycache__"))
    (candidate / D04_SERVICE_PATH).write_text(_D04_SERVICE_REFERENCE, encoding="utf-8")
    (candidate / D04_CLI_PATH).write_text(_D04_CLI_REFERENCE, encoding="utf-8")

    checks = _supplemental_d04_checks(candidate)

    assert checks and all(checks.values()), checks


@dataclass(frozen=True)
class _FileTaskSpec:
    """双文件业务旅程的冻结形状（D04 与改名同构例共用）。"""

    goal_id: str
    outcome: str
    targets: tuple[str, ...]
    proposed: tuple[ProposedCriterion, ...]
    first_path: str
    first_content: str
    second_path: str
    second_content: str
    revise_first_content: str | None = None
    hollow_claim: bool = False


class _FileTaskProvider:
    """真实主 loop 的双文件业务旅程 provider。

    阶段序列按 spec 组合：draft → 写第一组件 →（可选修订）→（hollow 旅程：
    读回使 service 证据有效 → 空 coverage claim 被拒）→ 写第二组件 → 读回
    全部组件（读回必须晚于最后一次写入，晚写会使早读失效）→ 带 coverage 的
    显式 claim。写第二组件前断言原始任务文本仍可见（复核输入，R2-B 3.1）。
    """

    def __init__(self, spec: _FileTaskSpec, task: str, *, start_stage: str = "draft"):
        self.spec = spec
        self.task = task
        self.calls = 0
        self.stage = start_stage
        self.task_visible_at_review = False

    def _write(self, call_id: str, path: str, content: str) -> ModelResponse:
        return ModelResponse(
            (ModelToolCall(call_id, "write_file", {"path": path, "content": content}),)
        )

    def _read(self, call_id: str, path: str) -> ModelResponse:
        return ModelResponse((ModelToolCall(call_id, "read_file", {"path": path}),))

    def generate(self, context, *, delta_observer=None):  # noqa: ANN001, ANN202
        self.calls += 1
        spec = self.spec
        stage = self.stage

        if stage == "draft":
            bootstrap = context.goal_bootstrap
            assert bootstrap is not None
            frame = GoalFrame(
                goal_id=spec.goal_id,
                revision=1,
                created_from_fact_ids=(bootstrap.source_fact_id,),
                workspace_identity_digest=bootstrap.workspace_identity_digest,
                user_outcome=spec.outcome,
                beneficiary="user",
                targets=spec.targets,
                scope=("workspace",),
                non_goals=(),
                assumptions=(),
                proposed_criteria=spec.proposed,
                admitted_criteria=(),
                authority_snapshot=bootstrap.authority_snapshot,
                status=GoalStatus.GOAL_READY,
                created_at="2026-10-14T00:00:00Z",
                updated_at="2026-10-14T00:00:00Z",
            )
            self.stage = "write-1"
            return ModelResponse(
                (), control=goal_draft_from_frame(f"proposal-{spec.goal_id}", frame)
            )

        if stage == "write-1":
            self.stage = (
                "revise-1"
                if spec.revise_first_content
                else "hollow-read-1"
                if spec.hollow_claim
                else "write-2"
            )
            return self._write("write-first", spec.first_path, spec.first_content)

        if stage == "revise-1":
            assert spec.revise_first_content is not None
            self.stage = "hollow-read-1" if spec.hollow_claim else "write-2"
            return self._write("revise-first", spec.first_path, spec.revise_first_content)

        if stage == "hollow-read-1":
            assert spec.hollow_claim
            self.stage = "hollow"
            return self._read("read-first", spec.first_path)

        if stage == "hollow":
            # 缺逐项复核的 claim：refs 抄自当前投影，coverage 为空。
            self.stage = "write-2"
            return ModelResponse(
                (), control=_claim_for(context, f"hollow-{spec.goal_id}", hollow=True)
            )

        if stage == "write-2":
            # 复核发生在主 loop：原始权威任务文本必须仍然可见（R2-B 3.1）。
            self.task_visible_at_review = self.task in _context_text(context)
            assert self.task_visible_at_review, (
                "the original authoritative task must stay visible for review"
            )
            self.stage = "reread-1" if spec.hollow_claim else "read-1"
            return self._write("write-second", spec.second_path, spec.second_content)

        if stage in {"read-1", "reread-1"}:
            # 晚写使早读失效：读回全部放在最后一次写入之后。
            self.stage = "read-2"
            return self._read(
                "reread-first" if stage == "reread-1" else "read-first", spec.first_path
            )

        if stage == "read-2":
            self.stage = "claim"
            return self._read("read-second", spec.second_path)

        if stage == "claim":
            assert self.task in _context_text(context)
            return ModelResponse((), control=_claim_for(context, f"claim-{spec.goal_id}"))

        raise AssertionError(f"unexpected stage {self.stage}")


def _d04_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    shutil.copytree(D04_FIXTURE, workspace, ignore=shutil.ignore_patterns("__pycache__"))
    return workspace


_BROAD_D04_SPEC = _FileTaskSpec(
    goal_id="d04-broad",
    outcome="retry_app implements the requested bounded retry behavior in both files",
    targets=(D04_SERVICE_PATH, D04_CLI_PATH),
    proposed=(
        ProposedCriterion(
            "criterion:d04-retry-behavior",
            "the requested bounded retry behavior is implemented",
            EvidenceOracleKind.FILESYSTEM_DIGEST,
            artifact_path=None,
        ),
    ),
    first_path=D04_SERVICE_PATH,
    first_content=_D04_SERVICE_REFERENCE,
    second_path=D04_CLI_PATH,
    second_content=_D04_CLI_REFERENCE,
)


def test_d04_broad_draft_completes_both_components_before_done(
    tmp_path: Path,
) -> None:
    """R2-C 正例 + 自动早收尾反例（当前树）：宽泛 draft 也必须两件都做完。

    修前（ff686bd 自动收尾）：service 写入/读回使首文件证据闭合即 VERIFIED_DONE，
    CLI 组件被截断、永不做。当前树：批次结束后回到模型，CLI 继续执行，完成门
    只接受带逐项 coverage 的显式 claim；grader 与补充判据同时通过。
    """

    workspace = _d04_workspace(tmp_path)
    provider = _FileTaskProvider(_BROAD_D04_SPEC, D04_TASK)
    opened, composition = _open_and_drive(tmp_path, provider, ControlInbox())

    state = opened.store.load().state
    composition.runtime.run_turn(_submit(state, "run-d04-broad", D04_TASK), opened.store.load())
    _approve_pending(opened, composition)

    final = LocalCheckpointStore(opened.checkpoint_path).load().state
    goal = final.goal
    assert goal is not None
    assert goal.status is GoalStatus.VERIFIED_DONE, (
        goal.status,
        [c.criterion_id for c in goal.admitted_criteria],
    )
    # CLI 组件确实在完成之前执行：provider 走完全部 6 个阶段。
    assert provider.calls == 6, provider.calls
    assert (workspace / D04_SERVICE_PATH).read_text(encoding="utf-8") == (
        _D04_SERVICE_REFERENCE
    )
    assert (workspace / D04_CLI_PATH).read_text(encoding="utf-8") == _D04_CLI_REFERENCE
    assert len(goal.admitted_criteria) == 2, [
        c.criterion_id for c in goal.admitted_criteria
    ]
    # 外部业务判据：冻结 grader（过程项恒 False 是诚实声明）+ 独立补充探针。
    from scripts.coding_scenario_grader import grade_d04

    checks = grade_d04(workspace)
    assert checks["latest_correction"] is True, checks
    assert checks["final_validation"] is True, checks
    assert checks["resume_without_restatement"] is False
    assert checks["no_effect_replay"] is False
    supplemental = _supplemental_d04_checks(workspace)
    assert supplemental and all(supplemental.values()), supplemental
    # coverage 绑定当前全部 mandatory criterion 并引用权威来源。
    claim = final.completion_claim
    assert claim is not None and claim.requirement_coverage
    covered = {
        criterion_id
        for item in claim.requirement_coverage
        for criterion_id in item.criterion_ids
    }
    assert covered == {c.criterion_id for c in goal.admitted_criteria}


def test_d04_omitted_component_requires_review_before_done(tmp_path: Path) -> None:
    """R2-C admission 遗漏反例：draft 漏 CLI 时空 coverage claim 不得完成。

    原始双组件要求 → 模型 draft 只提 service criterion → service 写入/读回
    证据有效 → 缺逐项复核的 claim 被完成门拒绝（目标未终化）→ 模型回主 loop
    复核（原始任务文本可见）→ 补做 CLI（审批时由 Runtime 铸 admitted
    criterion，测试不预补）→ 带 coverage claim → VERIFIED_DONE，业务判据全过。
    """

    workspace = _d04_workspace(tmp_path)
    spec = _FileTaskSpec(
        goal_id="d04-omission",
        outcome="retry_app implements the requested bounded retry behavior",
        targets=(D04_SERVICE_PATH,),
        proposed=(
            ProposedCriterion(
                "criterion:d04-service",
                "the service implements the requested retry behavior",
                EvidenceOracleKind.FILESYSTEM_DIGEST,
                artifact_path=D04_SERVICE_PATH,
            ),
        ),
        first_path=D04_SERVICE_PATH,
        first_content=_D04_SERVICE_REFERENCE,
        second_path=D04_CLI_PATH,
        second_content=_D04_CLI_REFERENCE,
        hollow_claim=True,
    )
    provider = _FileTaskProvider(spec, D04_TASK)
    opened, composition = _open_and_drive(tmp_path, provider, ControlInbox())

    state = opened.store.load().state
    composition.runtime.run_turn(_submit(state, "run-d04-omission", D04_TASK), opened.store.load())
    _approve_pending(opened, composition)

    final = LocalCheckpointStore(opened.checkpoint_path).load().state
    goal = final.goal
    assert goal is not None
    # 空 coverage claim 被拒的 durable 证据：可修复拒绝的策略结果落盘。
    rejection = next(
        (
            str(fact.content.get("text", ""))
            for fact in final.facts
            if fact.kind is FactKind.POLICY_RESULT
            and fact.content.get("code") == "invalid_model_control"
            and "per-requirement coverage" in str(fact.content.get("text", ""))
        ),
        "",
    )
    assert rejection, "the hollow claim must be rejected with coverage guidance"
    # 复核发生在主 loop：原始任务文本在补做 CLI 前仍然可见。
    assert provider.task_visible_at_review
    assert provider.calls == 8, provider.calls
    assert goal.status is GoalStatus.VERIFIED_DONE, goal.status
    assert (workspace / D04_CLI_PATH).read_text(encoding="utf-8") == _D04_CLI_REFERENCE
    assert (workspace / D04_SERVICE_PATH).read_text(encoding="utf-8") == (
        _D04_SERVICE_REFERENCE
    )
    assert len(goal.admitted_criteria) == 2, [
        c.criterion_id for c in goal.admitted_criteria
    ]
    from scripts.coding_scenario_grader import grade_d04

    checks = grade_d04(workspace)
    assert checks["latest_correction"] is True and checks["final_validation"] is True
    supplemental = _supplemental_d04_checks(workspace)
    assert supplemental and all(supplemental.values()), supplemental


def test_d04_revised_write_invalidates_prior_file_verification(tmp_path: Path) -> None:
    """R2-C freshness：相关新写入使同路径旧 admission/验证不可用。

    service 先写入中间版（无 legacy 别名）再修订为完整版：旧 digest 的
    admission 被 supersede，最终只有当前内容 digest 的 criterion/证据能通过
    完成门；磁盘与验证都指向修订后的内容。
    """

    workspace = _d04_workspace(tmp_path)
    spec = replace(
        _BROAD_D04_SPEC,
        goal_id="d04-revise",
        first_content=_D04_SERVICE_PARTIAL,
        revise_first_content=_D04_SERVICE_REFERENCE,
    )
    provider = _FileTaskProvider(spec, D04_TASK)
    opened, composition = _open_and_drive(tmp_path, provider, ControlInbox())

    state = opened.store.load().state
    composition.runtime.run_turn(_submit(state, "run-d04-revise", D04_TASK), opened.store.load())
    _approve_pending(opened, composition)

    final = LocalCheckpointStore(opened.checkpoint_path).load().state
    goal = final.goal
    assert goal is not None
    assert goal.status is GoalStatus.VERIFIED_DONE, goal.status
    assert provider.calls == 7, provider.calls
    reference_digest = hashlib.sha256(
        _D04_SERVICE_REFERENCE.encode("utf-8")
    ).hexdigest()
    partial_digest = hashlib.sha256(_D04_SERVICE_PARTIAL.encode("utf-8")).hexdigest()
    service_admissions = [
        criterion
        for criterion in goal.admitted_criteria
        if criterion.predicate.get("path") == D04_SERVICE_PATH
    ]
    assert len(service_admissions) == 1
    assert service_admissions[0].predicate["sha256"] == reference_digest
    assert service_admissions[0].predicate["sha256"] != partial_digest
    # 验证证据同样只绑定当前 digest：旧 digest 没有可复用的已验证记录。
    assert all(
        record.predicate_digest
        == canonical_json_digest(
            {
                "path": D04_SERVICE_PATH,
                "sha256": reference_digest,
            }
        )
        for record in final.evidence_records
        if record.criterion_id == service_admissions[0].criterion_id
    )
    assert (workspace / D04_SERVICE_PATH).read_text(encoding="utf-8") == (
        _D04_SERVICE_REFERENCE
    )
    supplemental = _supplemental_d04_checks(workspace)
    assert supplemental and all(supplemental.values()), supplemental


def test_d04_pending_component_survives_process_reopen(tmp_path: Path) -> None:
    """R2-C 恢复：未完成义务跨暂停/新进程边界保留，新 composition 续做后完成。

    run1 显式 draft 含 service+CLI 两个 criterion，在第一笔写入的审批边界暂停
    （真实产品暂停路径：awaiting approval 落盘、run 边界持久）。新进程（对同一
    durable checkpoint 的新 store/composition）读到完整未完成义务：两项 criterion
    均未准入、目标未终化。新进程批准挂起写入后续做 CLI 并以带 coverage 的
    claim 完成。
    """

    workspace = _d04_workspace(tmp_path)
    spec = _FileTaskSpec(
        goal_id="d04-reopen",
        outcome="retry_app implements the requested bounded retry behavior in both files",
        targets=(D04_SERVICE_PATH, D04_CLI_PATH),
        proposed=(
            ProposedCriterion(
                "criterion:d04-service-file",
                "the service implements the requested retry behavior",
                EvidenceOracleKind.FILESYSTEM_DIGEST,
                artifact_path=D04_SERVICE_PATH,
            ),
            ProposedCriterion(
                "criterion:d04-cli-file",
                "the CLI adapter uses the same retry limit",
                EvidenceOracleKind.FILESYSTEM_DIGEST,
                artifact_path=D04_CLI_PATH,
            ),
        ),
        first_path=D04_SERVICE_PATH,
        first_content=_D04_SERVICE_REFERENCE,
        second_path=D04_CLI_PATH,
        second_content=_D04_CLI_REFERENCE,
    )
    provider1 = _FileTaskProvider(spec, D04_TASK)
    opened, composition = _open_and_drive(tmp_path, provider1, ControlInbox())

    state = opened.store.load().state
    result1 = composition.runtime.run_turn(
        _submit(state, "run-d04-r1", D04_TASK), opened.store.load()
    )
    # run1 在第一笔写入的审批边界暂停：不批准，保持挂起状态落盘。
    assert result1.status is RunStatus.AWAITING_APPROVAL
    assert result1.request is not None

    after_run1 = LocalCheckpointStore(opened.checkpoint_path).load().state
    active1 = after_run1.active_run
    assert active1 is not None and active1.pending_request is not None
    goal1 = after_run1.goal
    assert goal1 is not None
    assert goal1.status is not GoalStatus.VERIFIED_DONE
    assert provider1.calls == 2, provider1.calls
    assert goal1.admitted_criteria == ()
    assert {
        "criterion:d04-service-file",
        "criterion:d04-cli-file",
    } <= {c.criterion_id for c in goal1.proposed_criteria}, (
        "pending obligations must survive the paused run boundary"
    )
    original_cli = (D04_FIXTURE / "retry_app" / "cli.py").read_text(encoding="utf-8")
    assert (workspace / D04_CLI_PATH).read_text(encoding="utf-8") == original_cli

    # 新进程：对同一 durable checkpoint 构造全新 store/composition 续做。
    continuation = _FileTaskProvider(spec, D04_TASK, start_stage="write-2")
    composition2 = _open_and_drive(
        tmp_path,
        continuation,
        ControlInbox(),
        checkpoint_store=LocalCheckpointStore(opened.checkpoint_path),
    )[1]
    _approve_pending(opened, composition2)

    final = LocalCheckpointStore(opened.checkpoint_path).load().state
    goal = final.goal
    assert goal is not None
    assert goal.status is GoalStatus.VERIFIED_DONE, goal.status
    assert continuation.calls == 4, continuation.calls
    assert {c.criterion_id for c in goal.admitted_criteria} == {
        "criterion:d04-service-file",
        "criterion:d04-cli-file",
    }
    assert (workspace / D04_CLI_PATH).read_text(encoding="utf-8") == _D04_CLI_REFERENCE
    supplemental = _supplemental_d04_checks(workspace)
    assert supplemental and all(supplemental.values()), supplemental


# ---------------------------------------------------------------------------
# R2-C：不同名字的同构双组件例——产品不得识别 D04/retry_count/grader 名称。
# ---------------------------------------------------------------------------

RENAMED_TASK = (
    "为 metrics_app 新增阈值处理：在 metrics_app/threshold.py 实现 "
    "clamp(value, *, span)，把 value 限制在 [0, span] 区间内，越界时取最近的"
    "边界；span 必须是正数，非正数直接报错。metrics_app/report.py 的 "
    "format_row 也要改为对每个数值调用 clamp，输出 row=<序号>:<限幅值> 并用"
    "空格连接。"
)
RENAMED_FIRST_PATH = "metrics_app/threshold.py"
RENAMED_SECOND_PATH = "metrics_app/report.py"

_RENAMED_THRESHOLD_REFERENCE = (
    "from __future__ import annotations\n\n\n"
    "def clamp(value, *, span):\n"
    "    if span <= 0:\n"
    "        raise ValueError(\"span must be positive\")\n"
    "    if value < 0:\n"
    "        return 0\n"
    "    if value > span:\n"
    "        return span\n"
    "    return value\n"
)
_RENAMED_REPORT_REFERENCE = (
    "from __future__ import annotations\n\n"
    "from metrics_app.threshold import clamp\n\n\n"
    "def format_row(values, *, span):\n"
    '    return " ".join(\n'
    '        f"row={index}:{clamp(value, span=span)}"\n'
    "        for index, value in enumerate(values, start=1)\n"
    "    )\n"
)

_RENAMED_PROBE = r'''
import json
import sys

sys.path.insert(0, sys.argv[1])

from metrics_app.report import format_row
from metrics_app.threshold import clamp

checks = {}


def _record(name, probe):
    try:
        checks[name] = bool(probe())
    except Exception:
        checks[name] = False


_record("clamp_interior", lambda: clamp(7, span=10) == 7)
_record("clamp_upper", lambda: clamp(15, span=10) == 10)
_record("clamp_lower", lambda: clamp(-3, span=10) == 0)


def _span_positive_only():
    try:
        clamp(5, span=0)
    except (TypeError, ValueError):
        return True
    return False


def _row_uses_clamp():
    return format_row([5, 15, -3], span=10) == "row=1:5 row=2:10 row=3:0"


checks["span_positive_only"] = _span_positive_only()
checks["row_uses_clamp"] = _row_uses_clamp()
print(json.dumps(checks))
'''


def test_renamed_two_component_task_completes_without_scenario_special_casing(
    tmp_path: Path,
) -> None:
    """R2-C 改名同构例：同一完成门对不含 D04 命名的双组件任务同样成立。

    draft 漏第二组件 → 空 coverage claim 被拒 → 复核后补做 report.py →
    带 coverage claim → VERIFIED_DONE；独立业务探针（隔离子进程）通过。
    产品若按 D04/retry_count/grader 名称特判，本例无法通过。
    """

    workspace = tmp_path / "workspace"
    (workspace / "metrics_app").mkdir(parents=True)
    (workspace / "metrics_app" / "__init__.py").write_text("", encoding="utf-8")
    (workspace / "metrics_app" / "report.py").write_text(
        'def format_row(values, *, span):\n    return ""\n', encoding="utf-8"
    )
    spec = _FileTaskSpec(
        goal_id="renamed-threshold",
        outcome="metrics_app implements the requested clamping behavior in both files",
        targets=(RENAMED_FIRST_PATH,),
        proposed=(
            ProposedCriterion(
                "criterion:renamed-threshold",
                "clamp implements the requested threshold behavior",
                EvidenceOracleKind.FILESYSTEM_DIGEST,
                artifact_path=RENAMED_FIRST_PATH,
            ),
        ),
        first_path=RENAMED_FIRST_PATH,
        first_content=_RENAMED_THRESHOLD_REFERENCE,
        second_path=RENAMED_SECOND_PATH,
        second_content=_RENAMED_REPORT_REFERENCE,
        hollow_claim=True,
    )
    provider = _FileTaskProvider(spec, RENAMED_TASK)
    opened, composition = _open_and_drive(tmp_path, provider, ControlInbox())

    state = opened.store.load().state
    composition.runtime.run_turn(
        _submit(state, "run-renamed", RENAMED_TASK), opened.store.load()
    )
    _approve_pending(opened, composition)

    final = LocalCheckpointStore(opened.checkpoint_path).load().state
    goal = final.goal
    assert goal is not None
    assert goal.status is GoalStatus.VERIFIED_DONE, goal.status
    assert provider.calls == 8, provider.calls
    assert provider.task_visible_at_review
    assert (workspace / RENAMED_FIRST_PATH).read_text(encoding="utf-8") == (
        _RENAMED_THRESHOLD_REFERENCE
    )
    assert (workspace / RENAMED_SECOND_PATH).read_text(encoding="utf-8") == (
        _RENAMED_REPORT_REFERENCE
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            "-c",
            _RENAMED_PROBE,
            str(workspace),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(workspace.parent),
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    checks = {
        str(key): bool(value) for key, value in json.loads(completed.stdout).items()
    }
    assert checks and all(checks.values()), checks


# ---------------------------------------------------------------------------
# W1（2026-10-17 日用收口包）：非空泛化声明不能掩盖明确交付对象遗漏。
# 与 hollow（空 coverage）旅程互补：这里 coverage 非空、引用全部权威来源与
# 当前 admitted criterion——欺骗面是"泛化陈述覆盖一切"，不是"忘写 coverage"。
# ---------------------------------------------------------------------------

W1_CONFIRM_ONLY_TASK = (
    "在 retry_app/service.py 实现有界重试：瞬态 RuntimeError 失败需要重试，"
    "公开参数名是 max_retries，负数限制无效，一次操作的执行次数上限是 "
    "1 + max_retries；同时保留旧的 retry_count 关键字作为别名，旧名与新名"
    "同时提供时必须拒绝这个有歧义的请求。"
)


class _NonemptyOmissionProvider(_FileTaskProvider):
    """W1 反例 provider：非空泛化 coverage 声明后拒绝补做，直接停笔。

    hollow 阶段改为发出 `_claim_for` 的完整非空 coverage（引用全部权威
    来源 fact 与当前全部 mandatory criterion），随后仅回文本结束旅程——
    复现"草稿漏掉明确交付对象、泛化声明掩盖遗漏"的真实模型行为。修复后
    完成门必须点名缺的具体文件路径拒绝，而不是只说 coverage 不完整。
    """

    def generate(self, context, *, delta_observer=None):  # noqa: ANN001, ANN202
        # 拦截分支自行计数；透传分支由基类入口计数，避免双计。
        if self.stage == "hollow":
            self.calls += 1
            self.stage = "post-claim"
            return ModelResponse(
                (), control=_claim_for(context, f"omission-{self.spec.goal_id}")
            )
        if self.stage == "post-claim":
            self.calls += 1
            # 被拒后不补做（真实用户旅程里模型放弃）：仅回文本，run 结束。
            self.stage = "stopped"
            return ModelResponse((ModelTextBlock("I will stop here."),))
        return super().generate(context, delta_observer=delta_observer)


def _w1_rejection_naming(final, *paths: str) -> str:
    """取 invalid_model_control 拒绝文本；必须点名至少一个缺失交付对象。"""

    return next(
        (
            str(fact.content.get("text", ""))
            for fact in final.facts
            if fact.kind is FactKind.POLICY_RESULT
            and fact.content.get("code") == "invalid_model_control"
            and any(path in str(fact.content.get("text", "")) for path in paths)
        ),
        "",
    )


def test_w1_nonempty_omission_claim_cannot_verify_done(tmp_path: Path) -> None:
    """W1.4 首行原字节反例：非空泛化 claim + 永不补 CLI 不得 VERIFIED_DONE。

    原 P1 路径：draft 只提 service criterion → service 写入/读回证据有效 →
    一条非空 coverage（引用全部来源与全部 admitted criterion）。修前当前树
    会 VERIFIED_DONE 而 CLI 字节不变；修复后必须给出点名 retry_app/cli.py
    的可修复拒绝，且 run 非终态收尾（incomplete，不是假完成）。
    """

    workspace = _d04_workspace(tmp_path)
    spec = _FileTaskSpec(
        goal_id="w1-omission",
        outcome="retry_app implements the requested bounded retry behavior",
        targets=(D04_SERVICE_PATH,),
        proposed=(
            ProposedCriterion(
                "criterion:w1-service",
                "the service implements the requested retry behavior",
                EvidenceOracleKind.FILESYSTEM_DIGEST,
                artifact_path=D04_SERVICE_PATH,
            ),
        ),
        first_path=D04_SERVICE_PATH,
        first_content=_D04_SERVICE_REFERENCE,
        second_path=D04_CLI_PATH,
        second_content=_D04_CLI_REFERENCE,
        hollow_claim=True,
    )
    provider = _NonemptyOmissionProvider(spec, D04_TASK)
    opened, composition = _open_and_drive(tmp_path, provider, ControlInbox())

    state = opened.store.load().state
    composition.runtime.run_turn(
        _submit(state, "run-w1-omission", D04_TASK), opened.store.load()
    )
    _approve_pending(opened, composition)

    final = LocalCheckpointStore(opened.checkpoint_path).load().state
    goal = final.goal
    assert goal is not None
    assert goal.status is not GoalStatus.VERIFIED_DONE, (
        "non-empty generic coverage must not substitute for the omitted "
        "explicit deliverable",
    )
    # 拒绝必须点名具体缺失交付对象，可被模型在同一主 loop 读取修复。
    assert _w1_rejection_naming(final, D04_CLI_PATH), (
        "the rejection must name the missing explicit deliverable path"
    )
    # CLI 全程未被写入：与 fixture 原字节一致。
    assert (workspace / D04_CLI_PATH).read_text(encoding="utf-8") == (
        D04_FIXTURE / D04_CLI_PATH
    ).read_text(encoding="utf-8")
    # 外部业务判据同步作证：CLI 组件确实未完成。
    supplemental = _supplemental_d04_checks(workspace)
    assert supplemental["cli_both_names"] is False, supplemental
    assert provider.calls == 5, provider.calls


def test_w1_renamed_omission_isomorph_cannot_verify_done(tmp_path: Path) -> None:
    """W1.4 改名同构负例：产品不得靠 D04/retry_app/cli.py 专名特判。

    与上一测试同构：draft 漏 report.py → 非空泛化 claim → 停笔。修复后必须
    点名 metrics_app/report.py 拒绝；report.py 原字节保留。
    """

    workspace = tmp_path / "workspace"
    (workspace / "metrics_app").mkdir(parents=True)
    (workspace / "metrics_app" / "__init__.py").write_text("", encoding="utf-8")
    original_report = 'def format_row(values, *, span):\n    return ""\n'
    (workspace / "metrics_app" / "report.py").write_text(
        original_report, encoding="utf-8"
    )
    spec = _FileTaskSpec(
        goal_id="w1-renamed-omission",
        outcome="metrics_app implements the requested clamping behavior",
        targets=(RENAMED_FIRST_PATH,),
        proposed=(
            ProposedCriterion(
                "criterion:w1-threshold",
                "clamp implements the requested threshold behavior",
                EvidenceOracleKind.FILESYSTEM_DIGEST,
                artifact_path=RENAMED_FIRST_PATH,
            ),
        ),
        first_path=RENAMED_FIRST_PATH,
        first_content=_RENAMED_THRESHOLD_REFERENCE,
        second_path=RENAMED_SECOND_PATH,
        second_content=_RENAMED_REPORT_REFERENCE,
        hollow_claim=True,
    )
    provider = _NonemptyOmissionProvider(spec, RENAMED_TASK)
    opened, composition = _open_and_drive(tmp_path, provider, ControlInbox())

    state = opened.store.load().state
    composition.runtime.run_turn(
        _submit(state, "run-w1-renamed", RENAMED_TASK), opened.store.load()
    )
    _approve_pending(opened, composition)

    final = LocalCheckpointStore(opened.checkpoint_path).load().state
    goal = final.goal
    assert goal is not None
    assert goal.status is not GoalStatus.VERIFIED_DONE, goal.status
    assert _w1_rejection_naming(final, RENAMED_SECOND_PATH)
    assert (workspace / RENAMED_SECOND_PATH).read_text(encoding="utf-8") == (
        original_report
    )
    assert provider.calls == 5, provider.calls


class _ConfirmOnlyProvider:
    """W1.4“已正确目标无需改写”pin：draft → confirm_file → 显式 claim。

    目标文件已含正确内容；旅程不发生任何写文件。修复不得为凑 evidence 强制
    改写相同文件：confirm_file（exact_current_content_confirmation）+ 现有
    admission/derive 链必须足以 VERIFIED_DONE。
    """

    def __init__(self, goal_id: str, path: str) -> None:
        self.goal_id = goal_id
        self.path = path
        self.calls = 0
        self.stage = "draft"

    def generate(self, context, *, delta_observer=None):  # noqa: ANN001, ANN202
        self.calls += 1
        if self.stage == "draft":
            bootstrap = context.goal_bootstrap
            assert bootstrap is not None
            frame = GoalFrame(
                goal_id=self.goal_id,
                revision=1,
                created_from_fact_ids=(bootstrap.source_fact_id,),
                workspace_identity_digest=bootstrap.workspace_identity_digest,
                user_outcome=f"{self.path} implements the requested retry behavior",
                beneficiary="user",
                targets=(self.path,),
                scope=("workspace",),
                non_goals=(),
                assumptions=(),
                proposed_criteria=(
                    ProposedCriterion(
                        f"criterion:{self.goal_id}-file",
                        "the file matches the requested retry behavior",
                        EvidenceOracleKind.FILESYSTEM_DIGEST,
                        artifact_path=self.path,
                    ),
                ),
                admitted_criteria=(),
                authority_snapshot=bootstrap.authority_snapshot,
                status=GoalStatus.GOAL_READY,
                created_at="2026-10-17T00:00:00Z",
                updated_at="2026-10-17T00:00:00Z",
            )
            self.stage = "confirm"
            return ModelResponse(
                (),
                control=goal_draft_from_frame(f"proposal-{self.goal_id}", frame),
            )
        if self.stage == "confirm":
            self.stage = "claim"
            return ModelResponse(
                (ModelToolCall("confirm-file", "confirm_file", {"path": self.path}),)
            )
        if self.stage == "claim":
            return ModelResponse(
                (), control=_claim_for(context, f"claim-{self.goal_id}")
            )
        raise AssertionError(f"unexpected stage {self.stage}")


def test_w1_already_correct_target_completes_without_rewrite(tmp_path: Path) -> None:
    """W1.4“已正确目标”行：不产生多余写入也能取得有效证据并完成。

    service.py 预置参考实现；旅程只有 draft → confirm_file → claim，零
    write_file/edit_file。下界约束不得迫使模型改写相同内容来“凑证据”。
    """

    workspace = _d04_workspace(tmp_path)
    (workspace / D04_SERVICE_PATH).write_text(
        _D04_SERVICE_REFERENCE, encoding="utf-8"
    )
    provider = _ConfirmOnlyProvider("w1-confirm-only", D04_SERVICE_PATH)
    opened, composition = _open_and_drive(tmp_path, provider, ControlInbox())

    state = opened.store.load().state
    composition.runtime.run_turn(
        _submit(state, "run-w1-confirm", W1_CONFIRM_ONLY_TASK),
        opened.store.load(),
    )
    _approve_pending(opened, composition)

    final = LocalCheckpointStore(opened.checkpoint_path).load().state
    goal = final.goal
    assert goal is not None
    assert goal.status is GoalStatus.VERIFIED_DONE, goal.status
    assert provider.calls == 3, provider.calls
    # 全程零改写：字节保持参考实现。
    assert (workspace / D04_SERVICE_PATH).read_text(encoding="utf-8") == (
        _D04_SERVICE_REFERENCE
    )
    assert [c.criterion_id for c in goal.admitted_criteria] == [
        f"criterion:{provider.goal_id}-file"
    ]


# ---------------------------------------------------------------------------
# 2026-10-18 CLI 首发阻断包 A（审计 F1/F2）：两个完整生产 Runtime 反例。
# ---------------------------------------------------------------------------

D04_TASK_NO_SPACE = D04_TASK.replace(
    "适配器 retry_app/cli.py", "适配器retry_app/cli.py"
)


def test_release_a_no_space_chinese_adjacent_path_cannot_verify_done(
    tmp_path: Path,
) -> None:
    """F1 反例：删掉中文空格的同义任务不得漏做 CLI 仍 VERIFIED_DONE。

    与既有 W1 原文反例同构，仅把「适配器 retry_app/cli.py」改成无空格
    「适配器retry_app/cli.py」。provider 仍只做 service 并给非空泛化
    coverage；修复后下界必须仍含 retry_app/cli.py，完成门点名拒绝。
    """

    workspace = _d04_workspace(tmp_path)
    assert "适配器retry_app/cli.py" in D04_TASK_NO_SPACE
    spec = _FileTaskSpec(
        goal_id="release-a-omission",
        outcome="retry_app implements the requested bounded retry behavior",
        targets=(D04_SERVICE_PATH,),
        proposed=(
            ProposedCriterion(
                "criterion:release-a-service",
                "the service implements the requested retry behavior",
                EvidenceOracleKind.FILESYSTEM_DIGEST,
                artifact_path=D04_SERVICE_PATH,
            ),
        ),
        first_path=D04_SERVICE_PATH,
        first_content=_D04_SERVICE_REFERENCE,
        second_path=D04_CLI_PATH,
        second_content=_D04_CLI_REFERENCE,
        hollow_claim=True,
    )
    provider = _NonemptyOmissionProvider(spec, D04_TASK_NO_SPACE)
    opened, composition = _open_and_drive(tmp_path, provider, ControlInbox())

    state = opened.store.load().state
    composition.runtime.run_turn(
        _submit(state, "run-release-a-omission", D04_TASK_NO_SPACE),
        opened.store.load(),
    )
    _approve_pending(opened, composition)

    final = LocalCheckpointStore(opened.checkpoint_path).load().state
    goal = final.goal
    assert goal is not None
    assert goal.status is not GoalStatus.VERIFIED_DONE, (
        "Chinese-adjacent direct file requirement must stay in the "
        "completion lower bound",
    )
    assert D04_CLI_PATH in authoritative_deliverable_file_paths(final)
    assert _w1_rejection_naming(final, D04_CLI_PATH), (
        "the rejection must name the missing explicit deliverable path"
    )
    assert (workspace / D04_CLI_PATH).read_text(encoding="utf-8") == (
        D04_FIXTURE / D04_CLI_PATH
    ).read_text(encoding="utf-8")
    assert _supplemental_d04_checks(workspace)["cli_both_names"] is False


class _StopAfterConfirmationClaim(_ConfirmOnlyProvider):
    """F2 反例 provider：confirm/claim 后被卡住就停笔，不补做示例文件。"""

    def generate(self, context, *, delta_observer=None):  # noqa: ANN001, ANN202
        if self.calls >= 3:
            self.calls += 1
            return ModelResponse((ModelTextBlock("I stop here."),))
        return super().generate(context, delta_observer=delta_observer)


RELEASE_A_QUOTED_EXAMPLES_TASK = (
    W1_CONFIRM_ONLY_TASK
    + " 同时解释“创建 app/example.py；修改 app/other.py”的含义。"
    + "引文仅供解释，不要修改示例文件。"
)


def test_release_a_quoted_examples_do_not_block_confirm_only_completion(
    tmp_path: Path,
) -> None:
    """F2 反例：解释性跨分句引文不得凭空生成交付义务卡住合法收尾。

    目标文件已正确，confirm_file 取证后完成；附带引文只是解释对象。
    修复后：不产生 app/example.py/app/other.py 义务、零额外写入、
    VERIFIED_DONE；拒绝信息不得再点名两个示例文件。
    """

    workspace = _d04_workspace(tmp_path)
    (workspace / D04_SERVICE_PATH).write_text(
        _D04_SERVICE_REFERENCE, encoding="utf-8"
    )
    provider = _StopAfterConfirmationClaim(
        "release-a-inputs", D04_SERVICE_PATH
    )
    opened, composition = _open_and_drive(tmp_path, provider, ControlInbox())

    state = opened.store.load().state
    composition.runtime.run_turn(
        _submit(state, "run-release-a-inputs", RELEASE_A_QUOTED_EXAMPLES_TASK),
        opened.store.load(),
    )
    _approve_pending(opened, composition)

    final = LocalCheckpointStore(opened.checkpoint_path).load().state
    goal = final.goal
    assert goal is not None
    assert goal.status is GoalStatus.VERIFIED_DONE, goal.status
    assert authoritative_deliverable_file_paths(final) == frozenset(
        {D04_SERVICE_PATH}
    )
    assert provider.calls == 3, provider.calls
    assert (workspace / D04_SERVICE_PATH).read_text(encoding="utf-8") == (
        _D04_SERVICE_REFERENCE
    )
    # 两个示例文件从未被创建或写入。
    assert not (workspace / "app").exists()


class _BlockedOmissionProvider(_FileTaskProvider):
    """W1.5 探针 provider：service 证据闭合后不碰 CLI 直接报 blocked。

    blocked 被拒后按当时指引重发 completion_claim（复现模型服从引导的行为），
    随后停笔。用于验证 blocked 指引与完成门是否复用同一交付缺口判断——
    指引不得在明确交付对象缺失时断言"证据已完整、不要报 blocked"。
    """

    def generate(self, context, *, delta_observer=None):  # noqa: ANN001, ANN202
        # 拦截分支自行计数；透传分支由基类入口计数，避免双计。
        if self.stage == "hollow":
            self.calls += 1
            self.stage = "guided-claim"
            goal = _context_goal(context)
            return ModelResponse(
                (),
                control=BlockedClaim(
                    correlation_id=f"blocked-{self.spec.goal_id}",
                    goal_id=goal["goal_id"],
                    goal_revision=goal["goal_revision"],
                    blocker="cannot finish the remaining adapter work",
                    safe_attempts=("wrote the service component",),
                    resume_condition="user confirms the service-only scope",
                ),
            )
        if self.stage == "guided-claim":
            self.calls += 1
            self.stage = "stopped"
            return ModelResponse(
                (), control=_claim_for(context, f"guided-{self.spec.goal_id}")
            )
        if self.stage == "stopped":
            self.calls += 1
            self.stage = "ended"
            return ModelResponse((ModelTextBlock("I will stop here."),))
        return super().generate(context, delta_observer=delta_observer)


def test_w1_blocked_guidance_shares_deliverable_gap_with_completion_gate(
    tmp_path: Path,
) -> None:
    """W1.5：blocked 指引与完成门复用同一交付缺口，不产生分歧指引。

    service 写入/读回证据闭合、CLI 交付对象从未尝试时，blocked claim 仍应被
    拒绝（对 CLI 没有 durable blocker，goal 不得终化为 blocked），但拒绝指引
    必须点名与完成门相同的缺失交付对象 retry_app/cli.py——不能一边断言
    "every mandatory criterion already has derivable evidence, do not report
    blocked"，一边让随后服从指引的 completion_claim 被完成门以同一缺口拒绝。
    """

    workspace = _d04_workspace(tmp_path)
    spec = _FileTaskSpec(
        goal_id="w1-blocked-omission",
        outcome="retry_app implements the requested bounded retry behavior",
        targets=(D04_SERVICE_PATH,),
        proposed=(
            ProposedCriterion(
                "criterion:w1-blocked-service",
                "the service implements the requested retry behavior",
                EvidenceOracleKind.FILESYSTEM_DIGEST,
                artifact_path=D04_SERVICE_PATH,
            ),
        ),
        first_path=D04_SERVICE_PATH,
        first_content=_D04_SERVICE_REFERENCE,
        second_path=D04_CLI_PATH,
        second_content=_D04_CLI_REFERENCE,
        hollow_claim=True,
    )
    provider = _BlockedOmissionProvider(spec, D04_TASK)
    opened, composition = _open_and_drive(tmp_path, provider, ControlInbox())

    state = opened.store.load().state
    composition.runtime.run_turn(
        _submit(state, "run-w1-blocked", D04_TASK), opened.store.load()
    )
    _approve_pending(opened, composition)

    final = LocalCheckpointStore(opened.checkpoint_path).load().state
    goal = final.goal
    assert goal is not None
    # blocked 不得终化（CLI 没有 durable blocker），也不得假完成。
    assert goal.status not in {
        GoalStatus.VERIFIED_DONE,
        GoalStatus.BLOCKED,
    }, goal.status
    # blocked 分支的拒绝指引必须点名同一缺失交付对象（与完成门同一判断）。
    blocked_guidance = next(
        str(fact.content.get("text", ""))
        for fact in final.facts
        if fact.kind is FactKind.POLICY_RESULT
        and fact.content.get("code")
        in {"completion_evidence_available", "blocked_claim_not_verified"}
    )
    assert D04_CLI_PATH in blocked_guidance, blocked_guidance
    # 服从指引重发的 completion_claim 被完成门以同一缺口拒绝（收敛证据仍在）。
    assert _w1_rejection_naming(final, D04_CLI_PATH)
    assert (workspace / D04_CLI_PATH).read_text(encoding="utf-8") == (
        D04_FIXTURE / D04_CLI_PATH
    ).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# W2（2026-10-17 日用收口包）：散文 targets 下的精确文件复用授权。
# 冻结正例：散文 targets → 首次普通 y（单次、无租约、Runtime 绑定该文件）→
# 同文件再次写入的默认提示出现精确选项 → 用户显式 /approve-goal-target 铸
# 有界租约 → 第三次同范围执行复用 → 任务正常收尾。全程真实 Runtime 与
# 真实 checkpoint 重开，不手填 targets 文件值、不手造 admitted criterion。
# ---------------------------------------------------------------------------

W2_TASK = "按 SPEC.md 的说明实现笔记功能：创建 notes/idea.md，记录当天想法。"
W2_NOTE_V1 = "day one note\n"
W2_NOTE_V2 = "day one note, revised\n"
W2_NOTE_V3 = "day one note, final\n"
W2_PROSE_TARGETS = ("按 SPEC.md 的说明实现笔记功能",)


class _ProseTargetProvider:
    """W2 旅程 provider：draft（散文 targets）→ 三次同文件写入 → 读回 → claim。"""

    def __init__(self, *, start_stage: str = "draft") -> None:
        self.calls = 0
        self.stage = start_stage

    def generate(self, context, *, delta_observer=None):  # noqa: ANN001, ANN202
        self.calls += 1
        if self.stage == "draft":
            bootstrap = context.goal_bootstrap
            assert bootstrap is not None
            frame = GoalFrame(
                goal_id="goal-w2-prose",
                revision=1,
                created_from_fact_ids=(bootstrap.source_fact_id,),
                workspace_identity_digest=bootstrap.workspace_identity_digest,
                user_outcome="notes feature implemented per SPEC.md",
                beneficiary="user",
                targets=W2_PROSE_TARGETS,
                scope=("workspace",),
                non_goals=(),
                assumptions=(),
                proposed_criteria=(
                    ProposedCriterion(
                        "criterion:w2-note",
                        "the note file matches the requested feature",
                        EvidenceOracleKind.FILESYSTEM_DIGEST,
                        artifact_path=None,
                    ),
                ),
                admitted_criteria=(),
                authority_snapshot=bootstrap.authority_snapshot,
                status=GoalStatus.GOAL_READY,
                created_at="2026-10-17T00:00:00Z",
                updated_at="2026-10-17T00:00:00Z",
            )
            self.stage = "write-1"
            return ModelResponse(
                (),
                control=goal_draft_from_frame("proposal-w2-prose", frame),
            )
        if self.stage == "write-1":
            self.stage = "write-2"
            return ModelResponse(
                (
                    ModelToolCall(
                        "w2-write-1",
                        "write_file",
                        {"path": "notes/idea.md", "content": W2_NOTE_V1},
                    ),
                )
            )
        if self.stage == "write-2":
            self.stage = "write-3"
            return ModelResponse(
                (
                    ModelToolCall(
                        "w2-write-2",
                        "write_file",
                        {"path": "notes/idea.md", "content": W2_NOTE_V2},
                    ),
                )
            )
        if self.stage == "write-3":
            self.stage = "confirm"
            return ModelResponse(
                (
                    ModelToolCall(
                        "w2-write-3",
                        "write_file",
                        {"path": "notes/idea.md", "content": W2_NOTE_V3},
                    ),
                )
            )
        if self.stage == "confirm":
            # 租约执行的写入不经过逐笔审批事件，admitted criterion 仍绑定
            # write-2 的旧 digest；confirm_file（exact_current_content_
            # confirmation，ALWAYS 审批）为最终字节绑定当前 digest——与
            # W1“已正确目标”pin 同一条诚实完成链。
            self.stage = "claim"
            return ModelResponse(
                (
                    ModelToolCall(
                        "w2-confirm", "confirm_file", {"path": "notes/idea.md"}
                    ),
                )
            )
        if self.stage == "claim":
            self.stage = "done"
            return ModelResponse((), control=_claim_for(context, "claim-w2-prose"))
        if self.stage == "done":
            return ModelResponse((ModelTextBlock("I will stop here."),))
        raise AssertionError(f"unexpected stage {self.stage}")


def test_w2_prose_target_full_reuse_journey_with_checkpoint_reopen(
    tmp_path: Path,
) -> None:
    """W2 冻结正例：散文 targets 下 Runtime 准入文件可被显式选择为有界复用。

    旅程跨越两个进程（真实 durable checkpoint 重开）：run1 首次写入在真实
    ResolveApproval（普通 y，单次）边界暂停；新进程读到同一状态，同文件第
    二次写入的默认提示出现 /approve-goal-target（scope 由当前准入候选派
    生），用户显式选择后铸造租约，第三次同文件写入复用租约免逐笔审批，
    最终 VERIFIED_DONE。普通 y 不自动产生租约；SPEC.md 输入不被改写。
    """

    from agent.runtime.views import project_goal_authorization_scopes

    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "SPEC.md").write_text(
        "# Notes feature\n记录当天的想法。\n", encoding="utf-8"
    )
    (workspace / "notes").mkdir()
    original_spec = (workspace / "SPEC.md").read_text(encoding="utf-8")

    provider1 = _ProseTargetProvider()
    opened, composition = _open_and_drive(tmp_path, provider1, ControlInbox())
    state = opened.store.load().state
    result1 = composition.runtime.run_turn(
        _submit(state, "run-w2-1", W2_TASK), opened.store.load()
    )
    # 首次写入：真实审批边界暂停。
    assert result1.status is RunStatus.AWAITING_APPROVAL
    assert result1.request is not None

    from agent.cli.app import _parse_action as _parse

    paused1 = LocalCheckpointStore(opened.checkpoint_path).load().state
    active1 = paused1.active_run
    assert active1 is not None and active1.pending_request is not None
    # 普通 y：只批准这一次，不创建租约。
    approve, error = _parse(
        "/approve " + active1.pending_request.request_id,
        paused1,
        lambda: "run-w2-1",
        approval_time_factory=_approval_now,
    )
    assert error is None and approve is not None
    composition.runtime.run_turn(approve, opened.store.load())
    after_first = LocalCheckpointStore(opened.checkpoint_path).load().state
    assert after_first.goal_authorizations == (), "plain y must not mint a lease"
    # Runtime 已把该文件绑定为 admitted criterion（第一次写入的准入来源）。
    assert after_first.goal is not None
    assert {
        criterion.predicate.get("path")
        for criterion in after_first.goal.admitted_criteria
    } == {"notes/idea.md"}
    # 第二次同文件写入再次到达审批边界（尚无租约）。
    paused2 = LocalCheckpointStore(opened.checkpoint_path).load().state
    active2 = paused2.active_run
    assert active2 is not None and active2.pending_request is not None

    # 新进程：对同一 durable checkpoint 构造全新 store/composition。
    provider2 = _ProseTargetProvider(start_stage="write-3")
    opened2, composition2 = _open_and_drive(tmp_path, provider2, ControlInbox())
    state2 = opened2.store.load().state
    assert state2.active_run is not None
    assert state2.active_run.pending_request is not None
    # W2 修复点：散文 targets 下，当前准入候选使精确 scope 可用（P2 修前
    # 为 (None, None)）。
    scopes = project_goal_authorization_scopes(state2)
    assert scopes == ("notes/idea.md", None), scopes

    # 用户显式 opt-in：/approve-goal-target 绑定刚显示的同一 pending request。
    opt_in, opt_in_error = _parse(
        "/approve-goal-target",
        state2,
        lambda: "run-w2-2",
        approval_time_factory=_approval_now,
    )
    assert opt_in_error is None and opt_in is not None
    assert isinstance(opt_in, ResolveApproval)
    assert opt_in.authorize_goal_target is True
    composition2.runtime.run_turn(opt_in, opened2.store.load())

    # 租约生效证明：第三次同文件写入（write-3）复用授权执行，未再逐笔审批。
    # 铸造审批本身消耗 1 次、write-3 消耗 1 次；在终态关闭租约前读取。
    after_reuse = LocalCheckpointStore(opened2.checkpoint_path).load().state
    leases = after_reuse.goal_authorizations
    assert len(leases) == 1
    assert leases[0].normalized_target == "notes/idea.md"
    assert leases[0].operation == "write_file"
    assert leases[0].uses_consumed == 2
    assert leases[0].remaining_uses == 14

    # 租约写入后的最终字节仍需一次 exact-content 确认（confirm_file 的
    # ALWAYS 审批=每次必审）：普通 y 批准这一次，Runtime 为最终内容绑定
    # 当前 digest，随后 claim 在同一主 loop 内收尾。
    _approve_pending(opened2, composition2)

    final = LocalCheckpointStore(opened2.checkpoint_path).load().state
    goal = final.goal
    assert goal is not None
    assert goal.status is GoalStatus.VERIFIED_DONE, goal.status
    assert (workspace / "notes" / "idea.md").read_text(encoding="utf-8") == (
        W2_NOTE_V3
    )
    assert (workspace / "SPEC.md").read_text(encoding="utf-8") == original_spec
    # 终态关闭租约（既有合同）；旅程内只铸造过这一条文件租约。
    assert final.goal_authorizations == ()
