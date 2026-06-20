"""S5-G03 本地 JSONL durable ledger 存储 API。

``TaskLedger`` 是 governed task 记录的本地持久化层：

- append-only：一行一条合法 JSON 记录；
- 写入时校验必填字段、强制 per-task_id 严格递增 seq（append-only 不变量），
  并在落盘前过 ``redact_ledger_record``（AC-7）；
- 读取容忍半写/损坏行（crash-survivable）：持久前缀仍可恢复；
- 纯本地：caller 注入文件路径，不触达 DB / 网络 / home-config（AC-3）。

边界（与 frozen S5 goal 一致）：checkpoint 仍是唯一的状态恢复源（AC-4）；
本层只提供 durable 审计/进度连续性，不执行工具、不跑 loop、不绕过 seam（AC-6）。
"""

from __future__ import annotations

import json
from pathlib import Path

from agent.task_ledger import (
    LedgerRecord,
    LedgerValidationError,
    ledger_record_from_dict,
    ledger_record_to_dict,
    redact_ledger_record,
    validate_ledger_record,
)


class TaskLedger:
    """Local-only JSONL durable ledger for governed task records."""

    def __init__(self, path: Path | str):
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def append(self, record: LedgerRecord) -> LedgerRecord:
        """追加一条记录：校验 → 强制 seq 单调 → redact → 写一行 → 返回已落盘记录。

        per-task_id 的 seq 必须严格大于已有最大 seq；违反 append-only 排序则拒绝。
        """

        validate_ledger_record(record)
        last_seq_for_task = max(
            (existing.seq for existing in self.read_all() if existing.task_id == record.task_id),
            default=0,
        )
        if record.seq <= last_seq_for_task:
            raise LedgerValidationError(
                f"ledger append violates monotonic seq for task_id={record.task_id}: "
                f"last={last_seq_for_task}, got={record.seq}"
            )
        safe_record = redact_ledger_record(record)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(ledger_record_to_dict(safe_record), ensure_ascii=False) + "\n"
            )
        return safe_record

    def read_all(self) -> list[LedgerRecord]:
        """读回全部记录（按写入顺序）。

        crash-survivable：跳过空行与半写/损坏行（JSON 解析失败或 schema 不合法），
        使持久前缀在崩溃后仍可恢复。
        """

        if not self._path.exists():
            return []
        records: list[LedgerRecord] = []
        with self._path.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    records.append(ledger_record_from_dict(json.loads(line)))
                except (json.JSONDecodeError, LedgerValidationError):
                    continue
        return records
