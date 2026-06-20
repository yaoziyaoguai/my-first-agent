"""S5-G02 redaction boundary 测试：ledger 持久化/投影前的脱敏硬边界。

锁定 AC-7：合成 key 形态出现在 task input / tool preview / evidence summary /
recovery metadata 等 free-text 字段时，``redact_ledger_record`` 必须在记录到达
任何持久化 (S5-G03) 或 summary 投影之前将其脱敏；同时结构化字段（id / path /
seq / 受控词表）必须原样保留——redact 它们会破坏 recovery (AC-4) 与 ref 匹配
(AC-8)。

这些测试在 ``redact_ledger_record`` 实现前必须失败（RED），实现后通过（GREEN）。
"""

from __future__ import annotations

import dataclasses
import json

from agent.task_ledger import (
    CheckpointRefRecord,
    EvidenceRefRecord,
    StepProgressRecord,
    TaskLifecycleRecord,
    build_reference_recovery_records,
    redact_ledger_record,
)

# 匹配 evidence_redaction 的 sk- 模式：sk- + 至少 16 个字母数字。
_SECRET = "sk-leaksurvives123456"


def test_redact_strips_synthetic_key_in_task_input():
    record = TaskLifecycleRecord(
        "t1", 1, "t1", "running", "running", f"goal {_SECRET}", None
    )
    safe = redact_ledger_record(record)
    assert _SECRET not in (safe.user_goal or "")
    assert "[REDACTED]" in safe.user_goal


def test_redact_strips_synthetic_key_in_plan_goal():
    record = TaskLifecycleRecord(
        "t1", 1, "t1", "planning", "awaiting_plan_confirmation", None, f"plan {_SECRET}"
    )
    safe = redact_ledger_record(record)
    assert _SECRET not in (safe.plan_goal or "")
    assert "[REDACTED]" in safe.plan_goal


def test_redact_strips_synthetic_key_in_step_completion_preview():
    record = StepProgressRecord(
        "t1", 2, "t2", 0, "s0", "completed", f"done api_key={_SECRET}"
    )
    safe = redact_ledger_record(record)
    assert _SECRET not in (safe.completion_summary or "")
    assert "[REDACTED]" in safe.completion_summary


def test_redact_strips_bearer_token_in_evidence_summary():
    record = EvidenceRefRecord(
        "t1", 3, "t3", "ev-1", "tool", f"preview Bearer {_SECRET}"
    )
    safe = redact_ledger_record(record)
    assert _SECRET not in (safe.safe_summary or "")
    assert "[REDACTED]" in safe.safe_summary


def test_redact_preserves_structural_fields_needed_for_recovery():
    # checkpoint_ref / step_id / evidence_ref / lifecycle / seq / task_id 必须精确——
    # redact 它们会破坏 recovery (AC-4) 或 ref 匹配 (AC-8)。
    cp = CheckpointRefRecord("t1", 4, "t4", "/tmp/s5/t1.json", "step_boundary", "running")
    safe_cp = redact_ledger_record(cp)
    assert safe_cp.checkpoint_ref == "/tmp/s5/t1.json"
    assert safe_cp.checkpoint_source == "step_boundary"
    assert safe_cp.task_status_at_save == "running"

    step = StepProgressRecord(
        "t1", 2, "t2", 0, "step-id-XYZ", "completed", f"done {_SECRET}"
    )
    safe_step = redact_ledger_record(step)
    assert safe_step.step_id == "step-id-XYZ"
    assert safe_step.step_status == "completed"
    assert safe_step.seq == 2
    assert _SECRET not in (safe_step.completion_summary or "")


def test_redact_preserves_none_text_fields():
    record = TaskLifecycleRecord("t1", 1, "t1", "running", "running", None, None)
    safe = redact_ledger_record(record)
    assert safe.user_goal is None
    assert safe.plan_goal is None


def test_redact_returns_new_record_original_immutable():
    record = TaskLifecycleRecord(
        "t1", 1, "t1", "running", "running", f"g {_SECRET}", None
    )
    safe = redact_ledger_record(record)
    assert _SECRET in (record.user_goal or "")
    assert safe is not record


def test_redacted_reference_records_summary_contains_no_secret():
    # 模拟「ledger summary output」：把 secret 注入若干记录的 free-text，整体
    # redact 后，任意投影（这里用 asdict JSON）都不得出现 secret。
    records = list(build_reference_recovery_records())
    records[0] = dataclasses.replace(records[0], user_goal=f"goal {_SECRET}")
    records[3] = dataclasses.replace(records[3], safe_summary=f"preview {_SECRET}")
    records[4] = dataclasses.replace(records[4], completion_summary=f"done {_SECRET}")
    redacted = [redact_ledger_record(r) for r in records]
    blob = json.dumps([dataclasses.asdict(r) for r in redacted], default=str)
    assert _SECRET not in blob
    assert "[REDACTED]" in blob


def test_redact_covers_known_secret_literal_patterns():
    # 拓宽合成 secret 形态覆盖：GitHub PAT / AWS / Slack / Google / password kv。
    cases = [
        ("ghp_" + "A" * 16, "github pat"),
        ("AKIA" + "B" * 16, "aws access key id"),
        ("xoxb-" + "c" * 11, "slack token"),
        ("AIza" + "D" * 20, "google api key"),
        ("password=hunter2", "password kv"),
    ]
    for secret, label in cases:
        record = EvidenceRefRecord(
            "t1", 1, "r1", "ev-1", "tool", f"preview {secret}"
        )
        safe = redact_ledger_record(record)
        assert secret not in (safe.safe_summary or ""), f"{label} not redacted"
        assert "[REDACTED]" in safe.safe_summary
