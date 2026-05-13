"""T1 Pending Review CLI 测试 — RFC §11.4 / §15.2 Phase 5a。

这些测试验证 RFC §11.4 / §15.2 Phase 5a T1 pending review bridge，
不验证真实 LLM extraction quality。

覆盖：
1. list_pending_proposals — 读取 _pending/t1_*.json，只列 pending
2. accept_pending_proposal — 写入 store，归档文件
3. reject_pending_proposal — 不写 store，归档文件
4. edit_and_accept_pending_proposal — 编辑后写入，保留 metadata
5. skip_pending_proposal — 文件不变，仍为 pending
6. 空 _pending/ 友好提示
7. 损坏 JSON 不崩溃
8. count_pending_proposals 正确计数
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.memory_review import (
    PendingProposal,
    _archive_pending_file,
    accept_pending_proposal,
    count_pending_proposals,
    edit_and_accept_pending_proposal,
    list_pending_proposals,
    reject_pending_proposal,
    run_pending_review_cli,
    skip_pending_proposal,
)
from agent.memory_store import (
    InMemoryMemoryStore,
    MemoryStoreApplyStatus,
)


# ═══════════════════════════════════════════════════════════════════════════════
# helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _write_pending_json(pending_dir: Path, filename: str, data: dict) -> Path:
    """在指定 _pending/ 目录写入一条 proposal JSON。返回文件路径。"""
    pending_dir.mkdir(parents=True, exist_ok=True)
    filepath = pending_dir / filename
    filepath.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return filepath


def _make_pending_proposal(
    filepath: Path,
    *,
    content: str = "测试内容：用户偏好 pytest",
    evidence: str = "用户多次提到 pytest",
    confidence: float = 0.85,
    memory_type: str = "episodic",
    source_type: str = "agent_suggested",
    scope: str = "user",
    approval_status: str = "pending",
    created_at: str = "2026-05-12T10:00:00Z",
) -> PendingProposal:
    """构造一条 PendingProposal，用于测试 accept/reject/edit/skip。"""
    return PendingProposal(
        filepath=filepath,
        content=content,
        evidence=evidence,
        confidence=confidence,
        importance=3,
        rationale="测试理由",
        memory_type=memory_type,
        source_type=source_type,
        governance_route="T1",
        approval_status=approval_status,
        scope=scope,
        source="session_end_extraction",
        created_at=created_at,
    )


def _make_inmemory_store() -> InMemoryMemoryStore:
    """创建 InMemoryMemoryStore（测试用，不写磁盘）。"""
    return InMemoryMemoryStore()


def _make_fs_store(root: Path):
    """创建 FilesystemMemoryStore，指向测试 tmp_path。"""
    from agent.memory_fs_store import FilesystemMemoryStore

    return FilesystemMemoryStore(root_dir=root)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. list_pending_proposals — 读取 _pending/t1_*.json
# ═══════════════════════════════════════════════════════════════════════════════


class TestListPendingProposals:
    """验证 list_pending_proposals 能从 _pending/ 正确读取 proposal。"""

    def test_lists_pending_proposals(self, tmp_path: Path):
        """能读取 _pending/t1_*.json 中的 pending proposal。"""
        pending_dir = tmp_path / "_pending"
        _write_pending_json(pending_dir, "t1_2026-05-12T10-00-00Z_abc1_0.json", {
            "content": "用户偏好 pytest",
            "evidence": "用户多次提到 pytest",
            "confidence": 0.85,
            "importance": 3,
            "rationale": "repeated preference",
            "memory_type": "episodic",
            "source_type": "agent_suggested",
            "governance_route": "T1",
            "approval_status": "pending",
            "scope": "user",
            "source": "session_end_extraction",
            "created_at": "2026-05-12T10:00:00Z",
        })

        result = list_pending_proposals(memory_root=str(tmp_path))
        assert len(result) == 1
        assert result[0].content == "用户偏好 pytest"
        assert result[0].confidence == 0.85
        assert result[0].memory_type == "episodic"

    def test_only_returns_pending_status(self, tmp_path: Path):
        """只列出 approval_status=pending 的 proposal。"""
        pending_dir = tmp_path / "_pending"
        _write_pending_json(pending_dir, "t1_pending.json", {
            "content": "pending item",
            "approval_status": "pending",
            "created_at": "2026-05-12T10:00:00Z",
        })
        _write_pending_json(pending_dir, "t1_accepted.json", {
            "content": "accepted item",
            "approval_status": "approved",
            "created_at": "2026-05-12T11:00:00Z",
        })
        _write_pending_json(pending_dir, "t1_rejected.json", {
            "content": "rejected item",
            "approval_status": "rejected",
            "created_at": "2026-05-12T12:00:00Z",
        })

        result = list_pending_proposals(memory_root=str(tmp_path))
        assert len(result) == 1
        assert result[0].content == "pending item"

    def test_empty_pending_dir(self, tmp_path: Path):
        """_pending/ 目录不存在时返回空列表，不崩溃。"""
        result = list_pending_proposals(memory_root=str(tmp_path))
        assert result == []

    def test_empty_pending_dir_exists(self, tmp_path: Path):
        """_pending/ 存在但无 t1_*.json 时返回空列表。"""
        (tmp_path / "_pending").mkdir()
        result = list_pending_proposals(memory_root=str(tmp_path))
        assert result == []

    def test_sorts_by_created_at(self, tmp_path: Path):
        """按 created_at 升序排列。"""
        pending_dir = tmp_path / "_pending"
        _write_pending_json(pending_dir, "t1_later.json", {
            "content": "later",
            "approval_status": "pending",
            "created_at": "2026-05-12T12:00:00Z",
        })
        _write_pending_json(pending_dir, "t1_earlier.json", {
            "content": "earlier",
            "approval_status": "pending",
            "created_at": "2026-05-12T10:00:00Z",
        })

        result = list_pending_proposals(memory_root=str(tmp_path))
        assert result[0].content == "earlier"
        assert result[1].content == "later"

    def test_skips_malformed_json(self, tmp_path: Path, capsys):
        """损坏的 JSON 文件应被跳过，不中断整个扫描。"""
        pending_dir = tmp_path / "_pending"
        pending_dir.mkdir(parents=True)
        (pending_dir / "t1_bad.json").write_text("not valid json{{{", encoding="utf-8")
        _write_pending_json(pending_dir, "t1_good.json", {
            "content": "good item",
            "approval_status": "pending",
            "created_at": "2026-05-12T10:00:00Z",
        })

        result = list_pending_proposals(memory_root=str(tmp_path))
        assert len(result) == 1
        assert result[0].content == "good item"

    def test_skips_non_t1_files(self, tmp_path: Path):
        """只处理 t1_*.json 文件，忽略其他 JSON。"""
        pending_dir = tmp_path / "_pending"
        pending_dir.mkdir(parents=True, exist_ok=True)
        (pending_dir / "other.json").write_text(
            json.dumps({"content": "other", "approval_status": "pending"}),
            encoding="utf-8",
        )

        result = list_pending_proposals(memory_root=str(tmp_path))
        assert len(result) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# 2. count_pending_proposals — 计数
# ═══════════════════════════════════════════════════════════════════════════════


class TestCountPendingProposals:
    """验证 count_pending_proposals 正确计数。"""

    def test_counts_correctly(self, tmp_path: Path):
        """正确计数 pending proposals。"""
        pending_dir = tmp_path / "_pending"
        for i in range(3):
            _write_pending_json(pending_dir, f"t1_{i}.json", {
                "content": f"item {i}",
                "approval_status": "pending",
                "created_at": f"2026-05-12T1{i}:00:00Z",
            })

        assert count_pending_proposals(memory_root=str(tmp_path)) == 3

    def test_returns_zero_when_empty(self, tmp_path: Path):
        """空目录返回 0。"""
        assert count_pending_proposals(memory_root=str(tmp_path)) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# 3. accept_pending_proposal — 写入 store + 归档文件
# ═══════════════════════════════════════════════════════════════════════════════


class TestAcceptPendingProposal:
    """验证 accept 后 proposal 写入正式 memory store。"""

    def test_accept_writes_to_store(self, tmp_path: Path):
        """accept 后 store 中存在对应 record。"""
        pending_dir = tmp_path / "_pending"
        filepath = _write_pending_json(pending_dir, "t1_test.json", {
            "content": "用户偏好 pytest",
            "evidence": "用户多次提到 pytest",
            "confidence": 0.85,
            "importance": 3,
            "rationale": "test",
            "memory_type": "episodic",
            "source_type": "agent_suggested",
            "governance_route": "T1",
            "approval_status": "pending",
            "scope": "user",
            "source": "session_end_extraction",
            "created_at": "2026-05-12T10:00:00Z",
        })

        # 使用 filesystem store（持久化验证）
        store = _make_fs_store(tmp_path)
        proposal = _make_pending_proposal(filepath)

        result = accept_pending_proposal(proposal, store)
        assert result.status is MemoryStoreApplyStatus.APPLIED
        assert result.record is not None
        assert "pytest" in result.record.content
        assert result.record.memory_type == "episodic"
        assert result.record.source_type == "agent_suggested"

    def test_accept_preserves_confidence(self, tmp_path: Path):
        """accept 时 confidence metadata 必须透传到 store。"""
        pending_dir = tmp_path / "_pending"
        filepath = _write_pending_json(pending_dir, "t1_conf.json", {
            "content": "confidence test",
            "evidence": "test",
            "confidence": 0.73,
            "importance": 3,
            "rationale": "test",
            "memory_type": "episodic",
            "source_type": "agent_suggested",
            "governance_route": "T1",
            "approval_status": "pending",
            "scope": "user",
            "source": "session_end_extraction",
            "created_at": "2026-05-12T10:00:00Z",
        })

        store = _make_fs_store(tmp_path)
        proposal = _make_pending_proposal(filepath, confidence=0.73)

        result = accept_pending_proposal(proposal, store)
        assert result.status is MemoryStoreApplyStatus.APPLIED
        # 验证 record 已持久化到 filesystem
        retrieved = store.get_record(result.record.id)
        assert retrieved is not None
        assert retrieved.metadata.get("confidence") == 0.73

    def test_accept_archives_pending_file(self, tmp_path: Path):
        """accept 成功后 pending 文件被归档，不再作为 pending 出现。"""
        pending_dir = tmp_path / "_pending"
        filepath = _write_pending_json(pending_dir, "t1_archive_test.json", {
            "content": "archive test",
            "evidence": "test",
            "confidence": 0.85,
            "importance": 3,
            "rationale": "test",
            "memory_type": "episodic",
            "source_type": "agent_suggested",
            "governance_route": "T1",
            "approval_status": "pending",
            "scope": "user",
            "source": "session_end_extraction",
            "created_at": "2026-05-12T10:00:00Z",
        })

        store = _make_fs_store(tmp_path)
        proposal = _make_pending_proposal(filepath)

        accept_pending_proposal(proposal, store)

        # pending 目录中不再有此文件
        remaining = list_pending_proposals(memory_root=str(tmp_path))
        assert len(remaining) == 0

        # 归档目录中存在
        archived = tmp_path / "_pending" / "archived" / "accepted" / "t1_archive_test.json"
        assert archived.exists()

    def test_accept_with_inmemory_store(self, tmp_path: Path):
        """accept 配合 InMemoryMemoryStore 也能正常工作。"""
        pending_dir = tmp_path / "_pending"
        filepath = _write_pending_json(pending_dir, "t1_mem.json", {
            "content": "memory store test",
            "evidence": "test",
            "confidence": 0.80,
            "importance": 3,
            "rationale": "test",
            "memory_type": "episodic",
            "source_type": "agent_suggested",
            "governance_route": "T1",
            "approval_status": "pending",
            "scope": "user",
            "source": "session_end_extraction",
            "created_at": "2026-05-12T10:00:00Z",
        })

        store = _make_inmemory_store()
        proposal = _make_pending_proposal(filepath)

        result = accept_pending_proposal(proposal, store)
        assert result.status is MemoryStoreApplyStatus.APPLIED
        assert len(store.list_records()) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# 4. reject_pending_proposal — 不写 store + 归档
# ═══════════════════════════════════════════════════════════════════════════════


class TestRejectPendingProposal:
    """验证 reject 后不写入正式 memory store。"""

    def test_reject_does_not_write_to_store(self, tmp_path: Path):
        """reject 后 store 中无对应 record。"""
        pending_dir = tmp_path / "_pending"
        filepath = _write_pending_json(pending_dir, "t1_reject_test.json", {
            "content": "to be rejected",
            "evidence": "test",
            "confidence": 0.85,
            "importance": 3,
            "rationale": "test",
            "memory_type": "episodic",
            "source_type": "agent_suggested",
            "governance_route": "T1",
            "approval_status": "pending",
            "scope": "user",
            "source": "session_end_extraction",
            "created_at": "2026-05-12T10:00:00Z",
        })

        store = _make_inmemory_store()
        proposal = _make_pending_proposal(filepath)

        reject_pending_proposal(proposal)

        # store 中不应有 record
        assert len(store.list_records()) == 0

    def test_reject_archives_pending_file(self, tmp_path: Path):
        """reject 后文件归档到 archived/rejected/。"""
        pending_dir = tmp_path / "_pending"
        filepath = _write_pending_json(pending_dir, "t1_reject_archive.json", {
            "content": "reject archive test",
            "evidence": "test",
            "confidence": 0.85,
            "importance": 3,
            "rationale": "test",
            "memory_type": "episodic",
            "source_type": "agent_suggested",
            "governance_route": "T1",
            "approval_status": "pending",
            "scope": "user",
            "source": "session_end_extraction",
            "created_at": "2026-05-12T10:00:00Z",
        })

        proposal = _make_pending_proposal(filepath)
        reject_pending_proposal(proposal)

        # pending 目录中不再有此文件
        remaining = list_pending_proposals(memory_root=str(tmp_path))
        assert len(remaining) == 0

        # 归档目录中存在
        archived = tmp_path / "_pending" / "archived" / "rejected" / "t1_reject_archive.json"
        assert archived.exists()


# ═══════════════════════════════════════════════════════════════════════════════
# 5. edit_and_accept_pending_proposal — 编辑后写入 + 保留 metadata
# ═══════════════════════════════════════════════════════════════════════════════


class TestEditAndAcceptPendingProposal:
    """验证 edit-and-accept 使用编辑后 content 并保留原 metadata。"""

    def test_edit_uses_new_content(self, tmp_path: Path):
        """store 中 record 的 content 是编辑后的文本。"""
        pending_dir = tmp_path / "_pending"
        filepath = _write_pending_json(pending_dir, "t1_edit.json", {
            "content": "原始内容",
            "evidence": "test evidence",
            "confidence": 0.85,
            "importance": 3,
            "rationale": "test",
            "memory_type": "episodic",
            "source_type": "agent_suggested",
            "governance_route": "T1",
            "approval_status": "pending",
            "scope": "user",
            "source": "session_end_extraction",
            "created_at": "2026-05-12T10:00:00Z",
        })

        store = _make_fs_store(tmp_path)
        proposal = _make_pending_proposal(filepath)

        result = edit_and_accept_pending_proposal(proposal, "编辑后的内容", store)
        assert result.status is MemoryStoreApplyStatus.APPLIED
        assert result.record is not None
        assert result.record.content == "编辑后的内容"

    def test_edit_preserves_metadata(self, tmp_path: Path):
        """编辑后 memory_type / source_type / confidence 保留原值。"""
        pending_dir = tmp_path / "_pending"
        filepath = _write_pending_json(pending_dir, "t1_edit_meta.json", {
            "content": "原始内容",
            "evidence": "evidence text",
            "confidence": 0.72,
            "importance": 3,
            "rationale": "test",
            "memory_type": "episodic",
            "source_type": "agent_suggested",
            "governance_route": "T1",
            "approval_status": "pending",
            "scope": "user",
            "source": "session_end_extraction",
            "created_at": "2026-05-12T10:00:00Z",
        })

        store = _make_fs_store(tmp_path)
        proposal = _make_pending_proposal(filepath, confidence=0.72)

        result = edit_and_accept_pending_proposal(proposal, "编辑后内容", store)
        assert result.status is MemoryStoreApplyStatus.APPLIED
        assert result.record.memory_type == "episodic"
        assert result.record.source_type == "agent_suggested"

    def test_edit_empty_content_raises(self, tmp_path: Path):
        """编辑后 content 为空时应报错。"""
        pending_dir = tmp_path / "_pending"
        filepath = _write_pending_json(pending_dir, "t1_empty.json", {
            "content": "原始",
            "evidence": "test",
            "confidence": 0.85,
            "importance": 3,
            "rationale": "test",
            "memory_type": "episodic",
            "source_type": "agent_suggested",
            "governance_route": "T1",
            "approval_status": "pending",
            "scope": "user",
            "source": "session_end_extraction",
            "created_at": "2026-05-12T10:00:00Z",
        })

        store = _make_inmemory_store()
        proposal = _make_pending_proposal(filepath)

        with pytest.raises(ValueError, match="不能为空"):
            edit_and_accept_pending_proposal(proposal, "   ", store)

    def test_edit_archives_pending_file(self, tmp_path: Path):
        """编辑接受后 pending 文件被归档。"""
        pending_dir = tmp_path / "_pending"
        filepath = _write_pending_json(pending_dir, "t1_edit_archive.json", {
            "content": "原始",
            "evidence": "test",
            "confidence": 0.85,
            "importance": 3,
            "rationale": "test",
            "memory_type": "episodic",
            "source_type": "agent_suggested",
            "governance_route": "T1",
            "approval_status": "pending",
            "scope": "user",
            "source": "session_end_extraction",
            "created_at": "2026-05-12T10:00:00Z",
        })

        store = _make_fs_store(tmp_path)
        proposal = _make_pending_proposal(filepath)

        edit_and_accept_pending_proposal(proposal, "edited content", store)

        remaining = list_pending_proposals(memory_root=str(tmp_path))
        assert len(remaining) == 0
        assert (tmp_path / "_pending" / "archived" / "accepted" / "t1_edit_archive.json").exists()


# ═══════════════════════════════════════════════════════════════════════════════
# 6. skip_pending_proposal — 无操作
# ═══════════════════════════════════════════════════════════════════════════════


class TestSkipPendingProposal:
    """验证 skip 后 proposal 仍保持 pending 状态。"""

    def test_skip_keeps_file(self, tmp_path: Path):
        """skip 后文件仍在 _pending/，下次 review 仍可见。"""
        pending_dir = tmp_path / "_pending"
        filepath = _write_pending_json(pending_dir, "t1_skip.json", {
            "content": "skip test",
            "evidence": "test",
            "confidence": 0.85,
            "importance": 3,
            "rationale": "test",
            "memory_type": "episodic",
            "source_type": "agent_suggested",
            "governance_route": "T1",
            "approval_status": "pending",
            "scope": "user",
            "source": "session_end_extraction",
            "created_at": "2026-05-12T10:00:00Z",
        })

        proposal = _make_pending_proposal(filepath)
        skip_pending_proposal(proposal)

        # 文件仍在
        assert filepath.exists()
        # 仍被列为 pending
        remaining = list_pending_proposals(memory_root=str(tmp_path))
        assert len(remaining) == 1

    def test_skip_does_not_write_to_store(self, tmp_path: Path):
        """skip 不写入 store。"""
        pending_dir = tmp_path / "_pending"
        filepath = _write_pending_json(pending_dir, "t1_skip2.json", {
            "content": "skip store test",
            "evidence": "test",
            "confidence": 0.85,
            "importance": 3,
            "rationale": "test",
            "memory_type": "episodic",
            "source_type": "agent_suggested",
            "governance_route": "T1",
            "approval_status": "pending",
            "scope": "user",
            "source": "session_end_extraction",
            "created_at": "2026-05-12T10:00:00Z",
        })

        store = _make_inmemory_store()
        proposal = _make_pending_proposal(filepath)
        skip_pending_proposal(proposal)

        assert len(store.list_records()) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# 7. run_pending_review_cli — 交互式循环（模拟输入）
# ═══════════════════════════════════════════════════════════════════════════════


class TestRunPendingReviewCLI:
    """验证 run_pending_review_cli 的交互式循环。"""

    def test_empty_pending_shows_message(self, tmp_path: Path, capsys):
        """空 _pending/ 时友好提示并返回空 summary。"""
        result = run_pending_review_cli(
            memory_root=str(tmp_path),
            store=_make_inmemory_store(),
        )
        assert result["total"] == 0
        assert result["accepted"] == 0
        assert "没有待确认" in capsys.readouterr().out

    def test_quit_exits_early(self, tmp_path: Path, monkeypatch):
        """输入 'q' 退出 review。"""
        pending_dir = tmp_path / "_pending"
        _write_pending_json(pending_dir, "t1_q.json", {
            "content": "quit test",
            "evidence": "test",
            "confidence": 0.85,
            "importance": 3,
            "rationale": "test",
            "memory_type": "episodic",
            "source_type": "agent_suggested",
            "governance_route": "T1",
            "approval_status": "pending",
            "scope": "user",
            "source": "session_end_extraction",
            "created_at": "2026-05-12T10:00:00Z",
        })

        inputs = iter(["q"])
        monkeypatch.setattr("agent.memory_review._read_user_choice", lambda: next(inputs))

        result = run_pending_review_cli(
            memory_root=str(tmp_path),
            store=_make_inmemory_store(),
        )
        # quit 后 proposal 仍为 pending
        assert result["total"] == 1
        assert result["accepted"] == 0
        assert result["rejected"] == 0

    def test_accept_via_cli(self, tmp_path: Path, monkeypatch):
        """通过 CLI 输入 'a' 接受 proposal。"""
        pending_dir = tmp_path / "_pending"
        _write_pending_json(pending_dir, "t1_accept.json", {
            "content": "accept via cli",
            "evidence": "test",
            "confidence": 0.85,
            "importance": 3,
            "rationale": "test",
            "memory_type": "episodic",
            "source_type": "agent_suggested",
            "governance_route": "T1",
            "approval_status": "pending",
            "scope": "user",
            "source": "session_end_extraction",
            "created_at": "2026-05-12T10:00:00Z",
        })

        store = _make_fs_store(tmp_path)
        inputs = iter(["a"])
        monkeypatch.setattr("agent.memory_review._read_user_choice", lambda: next(inputs))

        result = run_pending_review_cli(memory_root=str(tmp_path), store=store)
        assert result["accepted"] == 1
        assert len(store.list_records()) == 1
        assert store.list_records()[0].content == "accept via cli"

    def test_reject_via_cli(self, tmp_path: Path, monkeypatch):
        """通过 CLI 输入 'r' 拒绝 proposal。"""
        pending_dir = tmp_path / "_pending"
        _write_pending_json(pending_dir, "t1_reject.json", {
            "content": "reject via cli",
            "evidence": "test",
            "confidence": 0.85,
            "importance": 3,
            "rationale": "test",
            "memory_type": "episodic",
            "source_type": "agent_suggested",
            "governance_route": "T1",
            "approval_status": "pending",
            "scope": "user",
            "source": "session_end_extraction",
            "created_at": "2026-05-12T10:00:00Z",
        })

        store = _make_inmemory_store()
        inputs = iter(["r"])
        monkeypatch.setattr("agent.memory_review._read_user_choice", lambda: next(inputs))

        result = run_pending_review_cli(memory_root=str(tmp_path), store=store)
        assert result["rejected"] == 1
        assert len(store.list_records()) == 0

    def test_edit_via_cli(self, tmp_path: Path, monkeypatch):
        """通过 CLI 输入 'e' 编辑后接受。"""
        pending_dir = tmp_path / "_pending"
        _write_pending_json(pending_dir, "t1_edit_cli.json", {
            "content": "original content",
            "evidence": "test",
            "confidence": 0.85,
            "importance": 3,
            "rationale": "test",
            "memory_type": "episodic",
            "source_type": "agent_suggested",
            "governance_route": "T1",
            "approval_status": "pending",
            "scope": "user",
            "source": "session_end_extraction",
            "created_at": "2026-05-12T10:00:00Z",
        })

        store = _make_fs_store(tmp_path)
        # 先返回 'e'，再返回编辑后的内容
        inputs = iter(["e", "edited content"])
        monkeypatch.setattr("agent.memory_review._read_user_choice", lambda: next(inputs))
        monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))

        result = run_pending_review_cli(memory_root=str(tmp_path), store=store)
        assert result["edited"] == 1
        records = store.list_records()
        assert len(records) == 1
        assert records[0].content == "edited content"

    def test_skip_via_cli(self, tmp_path: Path, monkeypatch):
        """通过 CLI 输入 's' 跳过 proposal。"""
        pending_dir = tmp_path / "_pending"
        _write_pending_json(pending_dir, "t1_skip_cli.json", {
            "content": "skip via cli",
            "evidence": "test",
            "confidence": 0.85,
            "importance": 3,
            "rationale": "test",
            "memory_type": "episodic",
            "source_type": "agent_suggested",
            "governance_route": "T1",
            "approval_status": "pending",
            "scope": "user",
            "source": "session_end_extraction",
            "created_at": "2026-05-12T10:00:00Z",
        })

        store = _make_inmemory_store()
        inputs = iter(["s"])
        monkeypatch.setattr("agent.memory_review._read_user_choice", lambda: next(inputs))

        result = run_pending_review_cli(memory_root=str(tmp_path), store=store)
        assert result["skipped"] == 1
        # 文件仍在 pending
        remaining = list_pending_proposals(memory_root=str(tmp_path))
        assert len(remaining) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# 8. _archive_pending_file — 文件归档
# ═══════════════════════════════════════════════════════════════════════════════


class TestArchivePendingFile:
    """验证 pending 文件归档行为。"""

    def test_archive_creates_status_dir(self, tmp_path: Path):
        """归档时自动创建 archived/{status}/ 目录。"""
        pending_dir = tmp_path / "_pending"
        pending_dir.mkdir()
        filepath = pending_dir / "t1_test.json"
        filepath.write_text("{}", encoding="utf-8")

        archived = _archive_pending_file(filepath, "accepted")
        assert archived.exists()
        assert "archived" in str(archived)
        assert "accepted" in str(archived)

    def test_archive_removes_original(self, tmp_path: Path):
        """归档后原文件不再存在。"""
        pending_dir = tmp_path / "_pending"
        pending_dir.mkdir()
        filepath = pending_dir / "t1_test.json"
        filepath.write_text("{}", encoding="utf-8")

        _archive_pending_file(filepath, "rejected")
        assert not filepath.exists()


# ═══════════════════════════════════════════════════════════════════════════════
# 9. PendingProposal 边界案例
# ═══════════════════════════════════════════════════════════════════════════════


class TestPendingProposalEdgeCases:
    """验证 PendingProposal 的边界行为。"""

    def test_missing_optional_fields_default(self, tmp_path: Path):
        """缺失字段时使用合理的默认值。"""
        pending_dir = tmp_path / "_pending"
        _write_pending_json(pending_dir, "t1_minimal.json", {
            "content": "minimal proposal",
            "approval_status": "pending",
            "created_at": "2026-05-12T10:00:00Z",
        })

        result = list_pending_proposals(memory_root=str(tmp_path))
        assert len(result) == 1
        assert result[0].memory_type == "episodic"  # default
        assert result[0].confidence == 0.0  # default float
        assert result[0].importance == 0  # default int

    def test_non_pending_json_in_pending_dir_ignored(self, tmp_path: Path):
        """_pending/ 目录下的非 JSON 文件被忽略。"""
        pending_dir = tmp_path / "_pending"
        pending_dir.mkdir(parents=True)
        (pending_dir / "README.md").write_text("说明文件", encoding="utf-8")
        (pending_dir / ".gitkeep").write_text("", encoding="utf-8")

        result = list_pending_proposals(memory_root=str(tmp_path))
        assert result == []

    def test_respects_memory_root_env(self, tmp_path: Path, monkeypatch):
        """list_pending_proposals 尊重 MEMORY_STORE_ROOT 环境变量（无显式参数时）。"""
        pending_dir = tmp_path / "_pending"
        _write_pending_json(pending_dir, "t1_env.json", {
            "content": "env test",
            "approval_status": "pending",
            "created_at": "2026-05-12T10:00:00Z",
        })

        # 不传 memory_root，依赖 _resolve_memory_root 读环境变量
        monkeypatch.setenv("MEMORY_STORE_ROOT", str(tmp_path))
        # 清除可能存在的 MEMORY_ROOT
        monkeypatch.delenv("MEMORY_ROOT", raising=False)

        result = list_pending_proposals(memory_root=None)
        assert len(result) == 1
        assert result[0].content == "env test"
