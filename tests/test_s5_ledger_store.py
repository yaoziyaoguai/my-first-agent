"""S5-G03 本地 JSONL 存储 API 测试。

锁定 AC-3（local + deterministic + fixture 友好）与 append-only 排序、redaction
前置、crash-survivable 读取、以及纯本地路径注入（无 DB / 网络 / home-config）。

这些测试在 ``TaskLedger`` / 序列化函数实现前必须失败（RED），实现后通过（GREEN）。
"""

from __future__ import annotations

import json

import pytest

from agent.task_ledger import (
    CheckpointRefRecord,
    EvidenceRefRecord,
    LedgerValidationError,
    StepProgressRecord,
    TaskLifecycleRecord,
    ledger_record_from_dict,
    ledger_record_to_dict,
)
from agent.task_ledger_store import TaskLedger

_SECRET = "sk-leaksurvives123456"


def test_to_dict_includes_kind_tag_and_fields():
    record = StepProgressRecord("t1", 2, "r2", 0, "s0", "completed", "done")
    payload = ledger_record_to_dict(record)
    assert payload["kind"] == "step_progress"
    assert payload["task_id"] == "t1"
    assert payload["seq"] == 2
    assert payload["step_status"] == "completed"


def test_from_dict_roundtrips_each_kind():
    originals = [
        TaskLifecycleRecord("t1", 1, "r1", "running", "running", "g", "p"),
        StepProgressRecord("t1", 2, "r2", 0, "s0", "active", None),
        CheckpointRefRecord("t1", 3, "r3", "/tmp/c.json", "step_boundary", "running"),
        EvidenceRefRecord("t1", 4, "r4", "ev-1", "tool", "summary"),
    ]
    for original in originals:
        assert ledger_record_from_dict(ledger_record_to_dict(original)) == original


def test_from_dict_rejects_unknown_kind():
    with pytest.raises(LedgerValidationError):
        ledger_record_from_dict({"kind": "not_a_kind", "task_id": "t1"})


def test_roundtrip_preserves_record_fields_and_types(tmp_path):
    ledger = TaskLedger(tmp_path / "ledger.jsonl")
    ledger.append(TaskLifecycleRecord("t1", 1, "r1", "running", "running", "goal-a", "plan-a"))
    ledger.append(StepProgressRecord("t1", 2, "r2", 0, "s0", "completed", "step 0 done"))
    ledger.append(CheckpointRefRecord("t1", 3, "r3", "/tmp/c.json", "step_boundary", "running"))
    ledger.append(EvidenceRefRecord("t1", 4, "r4", "ev-1", "tool", "summary"))
    records = ledger.read_all()
    assert [type(r) for r in records] == [
        TaskLifecycleRecord,
        StepProgressRecord,
        CheckpointRefRecord,
        EvidenceRefRecord,
    ]
    assert records[0].user_goal == "goal-a"
    assert records[1].completion_summary == "step 0 done"
    assert records[2].checkpoint_ref == "/tmp/c.json"
    assert records[3].evidence_ref == "ev-1"


def test_append_redacts_before_persisting(tmp_path):
    ledger = TaskLedger(tmp_path / "ledger.jsonl")
    ledger.append(TaskLifecycleRecord("t1", 1, "r1", "running", "running", f"goal {_SECRET}", None))
    # 读回的记录不得含 secret。
    records = ledger.read_all()
    assert _SECRET not in (records[0].user_goal or "")
    assert "[REDACTED]" in records[0].user_goal
    # 原始 JSONL 字节也不得含 secret。
    raw = (tmp_path / "ledger.jsonl").read_text(encoding="utf-8")
    assert _SECRET not in raw


def test_append_returns_redacted_record(tmp_path):
    ledger = TaskLedger(tmp_path / "ledger.jsonl")
    persisted = ledger.append(
        TaskLifecycleRecord("t1", 1, "r1", "running", "running", f"g {_SECRET}", None)
    )
    assert _SECRET not in (persisted.user_goal or "")
    assert "[REDACTED]" in persisted.user_goal


def test_append_enforces_monotonic_seq_per_task(tmp_path):
    ledger = TaskLedger(tmp_path / "ledger.jsonl")
    ledger.append(
        TaskLifecycleRecord("t1", 1, "r1", "planning", "awaiting_plan_confirmation", None, None)
    )
    # 同 task_id 重复 seq（非严格递增）——写入时即拒绝。
    with pytest.raises(LedgerValidationError):
        ledger.append(StepProgressRecord("t1", 1, "r2", 0, "s0", "active", None))
    # 严格递增的 seq 接受。
    ledger.append(StepProgressRecord("t1", 2, "r3", 0, "s0", "active", None))
    assert len(ledger.read_all()) == 2


def test_append_validates_required_fields(tmp_path):
    ledger = TaskLedger(tmp_path / "ledger.jsonl")
    with pytest.raises(LedgerValidationError):
        ledger.append(
            TaskLifecycleRecord("", 1, "r1", "running", "running", None, None)
        )


def test_read_all_missing_file_returns_empty(tmp_path):
    ledger = TaskLedger(tmp_path / "absent.jsonl")
    assert ledger.read_all() == []


def test_read_all_skips_malformed_lines_crash_survivable(tmp_path):
    # crash-survivable：半写/损坏行不得让整个 ledger 不可读——持久前缀仍可恢复。
    path = tmp_path / "ledger.jsonl"
    line_a = json.dumps(
        ledger_record_to_dict(TaskLifecycleRecord("t1", 1, "r1", "running", "running", "g", None))
    )
    line_b = json.dumps(
        ledger_record_to_dict(StepProgressRecord("t1", 2, "r2", 0, "s0", "active", None))
    )
    path.write_text(
        line_a + "\n" + "{this is not valid json\n" + line_b + "\n",
        encoding="utf-8",
    )
    ledger = TaskLedger(path)
    records = ledger.read_all()
    # 损坏行被跳过，两条合法记录按序保留。
    assert [r.seq for r in records] == [1, 2]


def test_store_uses_injected_local_path_only(tmp_path):
    # 纯本地：caller 注入路径，唯一产物就是该 ledger 文件（无 DB/网络/home-config）。
    nested = tmp_path / "nested" / "dir" / "ledger.jsonl"
    ledger = TaskLedger(nested)
    ledger.append(TaskLifecycleRecord("t1", 1, "r1", "running", "running", "g", None))
    assert nested.exists()
    # tmp_path 下除 ledger 文件外不应有其它意外产物。
    files = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert files == [nested]


def test_read_all_tolerates_half_written_tail(tmp_path):
    # crash-survivable tail：最后一行是半写/截断 JSON，持久前缀仍可读。
    path = tmp_path / "ledger.jsonl"
    good = json.dumps(
        ledger_record_to_dict(
            TaskLifecycleRecord("t1", 1, "r1", "running", "running", "g", None)
        )
    )
    path.write_text(good + "\n" + '{"kind": "task_lifecycle", "task_i', encoding="utf-8")
    records = TaskLedger(path).read_all()
    assert [r.seq for r in records] == [1]
