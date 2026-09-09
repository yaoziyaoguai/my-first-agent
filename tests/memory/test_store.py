from __future__ import annotations

import stat
from pathlib import Path

import pytest

from agent.memory.contracts import (
    MemoryCapacityError,
    MemoryCasMismatchError,
    MemoryStoreError,
    ProviderTrustProfile,
)
from agent.memory.store import MemoryStore

SCOPE = "scope-digest-1"
PROFILE = ProviderTrustProfile("ops-profile", "openai_compatible", "https://provider.example")


def _store_path(tmp_path: Path) -> Path:
    directory = tmp_path / "memory"
    directory.mkdir(mode=0o700, exist_ok=True)
    return directory / "store.json"


def test_create_is_exclusive_and_revision_zero(tmp_path: Path) -> None:
    path = _store_path(tmp_path)
    store = MemoryStore.create(path, workspace_scope_digest=SCOPE, profile=PROFILE)

    assert store.revision == 0
    assert store.snapshot() == ()
    with pytest.raises(MemoryStoreError):
        MemoryStore.create(path, workspace_scope_digest=SCOPE, profile=PROFILE)


def test_load_validates_scope_and_profile(tmp_path: Path) -> None:
    path = _store_path(tmp_path)
    MemoryStore.create(path, workspace_scope_digest=SCOPE, profile=PROFILE)

    other_scope = MemoryStore.load(
        path, workspace_scope_digest=SCOPE, profile=PROFILE
    )
    assert other_scope.revision == 0

    with pytest.raises(MemoryStoreError):
        MemoryStore.load(path, workspace_scope_digest="other-scope", profile=PROFILE)
    other_profile = ProviderTrustProfile("other", "openai_compatible", "https://provider.example")
    with pytest.raises(MemoryStoreError):
        MemoryStore.load(path, workspace_scope_digest=SCOPE, profile=other_profile)


def test_remember_update_forget_with_cas(tmp_path: Path) -> None:
    path = _store_path(tmp_path)
    store = MemoryStore.create(path, workspace_scope_digest=SCOPE, profile=PROFILE)
    record = store.remember("prefer tabs over spaces")

    assert store.revision == 1
    assert len(store.snapshot()) == 1

    with pytest.raises(MemoryCasMismatchError):
        store.update(
            record.record_id, "new", expected_record_revision=99,
            expected_content_digest=record.content_digest,
        )
    with pytest.raises(MemoryCasMismatchError):
        store.update(
            record.record_id, "new",
            expected_record_revision=record.revision,
            expected_content_digest="wrong",
        )

    updated = store.update(
        record.record_id,
        "prefer spaces over tabs",
        expected_record_revision=record.revision,
        expected_content_digest=record.content_digest,
    )
    assert updated.content == "prefer spaces over tabs"
    assert store.revision == 2

    store.forget(
        record.record_id,
        expected_record_revision=updated.revision,
        expected_content_digest=updated.content_digest,
    )
    assert store.snapshot() == ()


def test_store_file_is_owner_only_and_regular(tmp_path: Path) -> None:
    path = _store_path(tmp_path)
    MemoryStore.create(path, workspace_scope_digest=SCOPE, profile=PROFILE)
    info = stat.S_ISREG(path.lstat().st_mode)
    assert info
    assert (path.stat().st_mode & 0o777) == 0o600


def test_malformed_store_fails_closed_without_overwrite(tmp_path: Path) -> None:
    path = _store_path(tmp_path)
    path.write_text("{not json", encoding="utf-8")
    original = path.read_bytes()
    with pytest.raises(MemoryStoreError):
        MemoryStore.load(path, workspace_scope_digest=SCOPE, profile=PROFILE)
    assert path.read_bytes() == original


def test_persistence_across_reload(tmp_path: Path) -> None:
    path = _store_path(tmp_path)
    store = MemoryStore.create(path, workspace_scope_digest=SCOPE, profile=PROFILE)
    record = store.remember("the build command is pyc build")

    reopened = MemoryStore.load(path, workspace_scope_digest=SCOPE, profile=PROFILE)
    assert len(reopened.snapshot()) == 1
    assert reopened.get(record.record_id).content == "the build command is pyc build"


def test_strict_snapshot_rejects_replacement_and_tampering(tmp_path: Path) -> None:
    """A8: a tampered store file (unknown fields, bad version, corrupted JSON) must fail
    closed on load without overwriting the source."""
    path = _store_path(tmp_path)
    store = MemoryStore.create(path, workspace_scope_digest=SCOPE, profile=PROFILE)
    store.remember("valid record")

    # corrupt the JSON
    path.write_text("{corrupted", encoding="utf-8")
    with pytest.raises(MemoryStoreError):
        MemoryStore.load(path, workspace_scope_digest=SCOPE, profile=PROFILE)

    # fix and add unknown field → must now fail closed (strict schema)
    path.write_text(
        '{"version": 1, "workspace_scope_digest": "' + SCOPE + '", '
        '"provider_profile": {"profile_id": "' + PROFILE.profile_id
        + '", "provider_family": "' + PROFILE.provider_family
        + '", "destination": "' + PROFILE.destination + '"}, '
        '"revision": 1, "records": {}, "evil_unknown": true}',
        encoding="utf-8",
    )
    with pytest.raises(MemoryStoreError):
        MemoryStore.load(path, workspace_scope_digest=SCOPE, profile=PROFILE)

    # wrong scope → fail
    with pytest.raises(MemoryStoreError):
        MemoryStore.load(path, workspace_scope_digest="wrong", profile=PROFILE)


def test_stale_content_digest_rejected_on_load(tmp_path: Path) -> None:
    """F4/R10: a store file with modified record content but unchanged content_digest
    must fail closed on load."""
    import json as _json

    path = _store_path(tmp_path)
    store = MemoryStore.create(path, workspace_scope_digest=SCOPE, profile=PROFILE)
    record = store.remember("original content")

    # Tamper: change content but keep old digest.
    data = _json.loads(path.read_text())
    rid = record.record_id
    data["records"][rid]["content"] = "tampered content"
    # Keep old content_digest unchanged.
    path.write_text(_json.dumps(data, sort_keys=True), encoding="utf-8")

    with pytest.raises(MemoryStoreError):
        MemoryStore.load(path, workspace_scope_digest=SCOPE, profile=PROFILE)


def test_unknown_top_level_field_rejected_on_load(tmp_path: Path) -> None:
    """F4/R10: unknown top-level keys in store JSON must fail closed."""
    import json as _json

    path = _store_path(tmp_path)
    store = MemoryStore.create(path, workspace_scope_digest=SCOPE, profile=PROFILE)
    store.remember("valid record")

    data = _json.loads(path.read_text())
    data["evil_unknown_key"] = True
    path.write_text(_json.dumps(data, sort_keys=True), encoding="utf-8")

    with pytest.raises(MemoryStoreError):
        MemoryStore.load(path, workspace_scope_digest=SCOPE, profile=PROFILE)


def test_load_rejects_coerced_or_wrong_typed_revision_and_timestamps(tmp_path: Path) -> None:
    """G3 strict load：禁止 int()/float() 容错 coercion。revision 与 record 时间戳必须是
    精确类型；字符串/缺失/错误类型一律 fail closed，不能被 coercion 静默接受。"""
    import json as _json

    def _fresh(name: str) -> tuple[Path, str]:
        directory = tmp_path / name
        directory.mkdir(mode=0o700)
        store_path = directory / "store.json"
        store = MemoryStore.create(store_path, workspace_scope_digest=SCOPE, profile=PROFILE)
        rid = store.remember("valid record").record_id
        return store_path, rid

    # store-level revision 改成字符串 "2"：int() 会把它 coerce 成 2；strict load 必须拒绝。
    path, _rid = _fresh("case-revision")
    data = _json.loads(path.read_text())
    data["revision"] = "2"
    path.write_text(_json.dumps(data, sort_keys=True), encoding="utf-8")
    with pytest.raises(MemoryStoreError):
        MemoryStore.load(path, workspace_scope_digest=SCOPE, profile=PROFILE)

    # record created_at 改成字符串 "1.5"：float() 会 coerce；必须拒绝。
    path, rid = _fresh("case-created")
    data = _json.loads(path.read_text())
    data["records"][rid]["created_at"] = "1.5"
    path.write_text(_json.dumps(data, sort_keys=True), encoding="utf-8")
    with pytest.raises(MemoryStoreError):
        MemoryStore.load(path, workspace_scope_digest=SCOPE, profile=PROFILE)

    # record revision 改成字符串 "1"：int() 会 coerce；必须拒绝。
    path, rid = _fresh("case-rec-revision")
    data = _json.loads(path.read_text())
    data["records"][rid]["revision"] = "1"
    path.write_text(_json.dumps(data, sort_keys=True), encoding="utf-8")
    with pytest.raises(MemoryStoreError):
        MemoryStore.load(path, workspace_scope_digest=SCOPE, profile=PROFILE)


def test_load_rejects_oversized_store_file(tmp_path: Path, monkeypatch) -> None:
    """G3 strict read：durable load 必须有界（bounded），超限文件在解析前 fail closed，
    不能无界 read 整个文件后再接受。"""
    import agent.memory.store as store_mod

    directory = tmp_path / "memory"
    directory.mkdir(mode=0o700)
    path = directory / "store.json"
    MemoryStore.create(path, workspace_scope_digest=SCOPE, profile=PROFILE)
    # 把 bounded read 上界压到极小，使一个正常的合法 store 文件也超限，证明 read 有界。
    monkeypatch.setattr(store_mod, "_MAX_STORE_BYTES", 8)
    with pytest.raises(MemoryStoreError):
        MemoryStore.load(path, workspace_scope_digest=SCOPE, profile=PROFILE)


def _write_json(path: Path, data: object) -> None:
    import json as _json

    path.write_text(_json.dumps(data, sort_keys=True), encoding="utf-8")


def test_load_rejects_coerced_or_missing_record_types(tmp_path: Path) -> None:
    """G3 009-gate：load 不做 int()/float() 容错 coercion。record timestamp/revision 与
    store revision 必须是精确类型；缺失或错误类型 fail closed（MemoryStoreError），既不静默
    coerce，也不把 ValueError/TypeError 泄漏给调用方。"""
    import json as _json

    path = _store_path(tmp_path)
    store = MemoryStore.create(path, workspace_scope_digest=SCOPE, profile=PROFILE)
    record = store.remember("valid")
    data = _json.loads(path.read_text())
    rid = record.record_id

    # record created_at 是字符串 → float() 会抛 ValueError；必须包成 MemoryStoreError。
    bad = _json.loads(_json.dumps(data))
    bad["records"][rid]["created_at"] = "not-a-number"
    _write_json(path, bad)
    with pytest.raises(MemoryStoreError):
        MemoryStore.load(path, workspace_scope_digest=SCOPE, profile=PROFILE)

    # 缺失 created_at → 不得 default 成 0.0 后继续。
    bad = _json.loads(_json.dumps(data))
    del bad["records"][rid]["created_at"]
    _write_json(path, bad)
    with pytest.raises(MemoryStoreError):
        MemoryStore.load(path, workspace_scope_digest=SCOPE, profile=PROFILE)

    # record revision 是字符串 "1" → int() 会静默 coerce 成 1；必须 fail closed。
    bad = _json.loads(_json.dumps(data))
    bad["records"][rid]["revision"] = "1"
    _write_json(path, bad)
    with pytest.raises(MemoryStoreError):
        MemoryStore.load(path, workspace_scope_digest=SCOPE, profile=PROFILE)

    # store-level revision 是字符串 → 同理 fail closed。
    bad = _json.loads(_json.dumps(data))
    bad["revision"] = "1"
    _write_json(path, bad)
    with pytest.raises(MemoryStoreError):
        MemoryStore.load(path, workspace_scope_digest=SCOPE, profile=PROFILE)


def test_mutation_rejects_document_above_capacity_before_any_write_side_effect(
    tmp_path: Path, monkeypatch
) -> None:
    """冻结容量合同：完整序列化 document 超过 _MAX_STORE_BYTES 时，remember 必须在任何
    temp 写入副作用之前失败；内存 revision/records、durable bytes 与预先存在的 temp
    文件都不得变化，且 durable 仍可被下一次 load 读取。"""
    import agent.memory.store as store_mod

    path = _store_path(tmp_path)
    store = MemoryStore.create(path, workspace_scope_digest=SCOPE, profile=PROFILE)
    record = store.remember("初始内容", clock=lambda: 50.0)
    durable_before = path.read_bytes()
    tmp_file = path.parent / f"{path.name}.tmp"
    tmp_file.write_bytes(b"pre-existing-temp-sentinel")
    # 压低上限到当前 durable 大小：等于上限仍可读取（边界接受），下一次写入增长后超限。
    monkeypatch.setattr(store_mod, "_MAX_STORE_BYTES", len(durable_before))

    with pytest.raises(MemoryCapacityError):
        store.remember("超限的新记录" * 24, clock=lambda: 60.0)

    # 内存状态不变（先于 snapshot 断言，避免 durable 刷新掩盖内存错误）。
    assert store.revision == 1
    assert store.get(record.record_id).content == "初始内容"
    # durable bytes 未变；预先存在的 temp 未被触碰，也没有留下新的 temp。
    assert path.read_bytes() == durable_before
    assert tmp_file.read_bytes() == b"pre-existing-temp-sentinel"
    assert [item.name for item in path.parent.glob("*.tmp")] == [tmp_file.name]
    # 之后再 snapshot 仍一致，durable 仍可被下一次 load 读取（不会写出自己读不回的文件）。
    assert len(store.snapshot()) == 1
    reopened = MemoryStore.load(path, workspace_scope_digest=SCOPE, profile=PROFILE)
    assert len(reopened.snapshot()) == 1


def test_update_rejects_document_above_capacity_before_any_write_side_effect(
    tmp_path: Path, monkeypatch
) -> None:
    """同上，update 路径：容量拒绝先于 temp open/truncate/write/replace。"""
    import agent.memory.store as store_mod

    path = _store_path(tmp_path)
    store = MemoryStore.create(path, workspace_scope_digest=SCOPE, profile=PROFILE)
    record = store.remember("初始内容", clock=lambda: 50.0)
    durable_before = path.read_bytes()
    tmp_file = path.parent / f"{path.name}.tmp"
    tmp_file.write_bytes(b"pre-existing-temp-sentinel")
    monkeypatch.setattr(store_mod, "_MAX_STORE_BYTES", len(durable_before))

    with pytest.raises(MemoryCapacityError):
        store.update(
            record.record_id,
            "超限内容" * 32,
            expected_record_revision=record.revision,
            expected_content_digest=record.content_digest,
            clock=lambda: 60.0,
        )

    assert store.revision == 1
    assert store.get(record.record_id).content == "初始内容"
    assert path.read_bytes() == durable_before
    assert tmp_file.read_bytes() == b"pre-existing-temp-sentinel"
    assert [item.name for item in path.parent.glob("*.tmp")] == [tmp_file.name]
    assert len(store.snapshot()) == 1


def test_capacity_boundary_exact_serialized_size_is_accepted(
    tmp_path: Path, monkeypatch
) -> None:
    """len(document) == _MAX_STORE_BYTES 必须接受：容量判断以完整序列化 bytes 的严格
    大于为准，不能把恰好等于上限的合法 store 拒之门外。"""
    from dataclasses import replace as _replace

    import agent.memory.store as store_mod
    from agent.memory.store import _content_digest

    path = _store_path(tmp_path)
    store = MemoryStore.create(path, workspace_scope_digest=SCOPE, profile=PROFILE)
    record = store.remember("初始内容", clock=lambda: 50.0)
    updated_record = _replace(
        record,
        content="边界内容",
        content_digest=_content_digest("边界内容"),
        updated_at=60.0,
        revision=2,
    )
    expected = MemoryStore._serialize(SCOPE, PROFILE, 2, {record.record_id: updated_record})
    monkeypatch.setattr(store_mod, "_MAX_STORE_BYTES", len(expected))

    updated = store.update(
        record.record_id,
        "边界内容",
        expected_record_revision=record.revision,
        expected_content_digest=record.content_digest,
        clock=lambda: 60.0,
    )

    assert updated.content == "边界内容"
    assert path.stat().st_size == len(expected)


def test_create_capacity_rejection_leaves_no_target_file_or_directory(
    tmp_path: Path, monkeypatch
) -> None:
    """create 的初始序列化（含容量拒绝）必须先于目标文件/目录创建：人为压低上限的
    拒绝不得留下目标文件或目录，也不得引入新的初始化机制。"""
    import agent.memory.store as store_mod

    path = tmp_path / "fresh" / "nested" / "store.json"
    monkeypatch.setattr(store_mod, "_MAX_STORE_BYTES", 8)

    with pytest.raises(MemoryCapacityError):
        MemoryStore.create(path, workspace_scope_digest=SCOPE, profile=PROFILE)
    assert not path.exists()
    assert not path.parent.exists()


def test_snapshot_rebuilds_from_durable_not_stale_cache(tmp_path: Path) -> None:
    """G3 009-gate：snapshot() 每次从 durable revision-consistent immutable view 构建，
    不复用进程内 _records 缓存。另一 instance 对 durable 的 mutation 必须在第一 instance
    的 snapshot 中可见（cross-conversation recall 正确性的基础）。"""
    path = _store_path(tmp_path)
    store_a = MemoryStore.create(path, workspace_scope_digest=SCOPE, profile=PROFILE)
    store_a.remember("from-a")
    assert len(store_a.snapshot()) == 1

    # 另一 instance load 后新增 record（模拟另一 conversation 的 approved mutation）。
    store_b = MemoryStore.load(path, workspace_scope_digest=SCOPE, profile=PROFILE)
    store_b.remember("from-b")
    assert len(store_b.snapshot()) == 2

    # store_a.snapshot() 必须重新读 durable，看到 store_b 的新增（不能返回 stale 1-record 缓存）。
    snapshot_a = store_a.snapshot()
    assert len(snapshot_a) == 2
    assert {record.content for record in snapshot_a} == {"from-a", "from-b"}
