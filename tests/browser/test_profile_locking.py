"""018 Task 2 Step 1：persistent profile writer lock 的 fail-closed Reds（先 Red）。

覆盖 spec §3.2：一份 persistent profile 同时最多一个 writer；锁身份不确定时
fail closed——live 锁不偷、corrupt 锁不偷、pid/start identity 不匹配不偷；
release 后才允许下一位 writer；revoked profile 不能取得 writer。
"""

import json
import os
import subprocess
import sys
import time
from dataclasses import replace
from types import SimpleNamespace

import pytest

from agent.browser.contracts import BrowserCleanupOutcome
from agent.browser.profile_store import (
    BrowserProfileStore,
    ProfileLockHeldError,
    ProfileLockUnknownError,
    ProfileNotFoundError,
    ProfileRevisionConflict,
    ProfileRevokedError,
    ProfileStatus,
)
from tests.browser.profile_probe import DeterministicProcessIdentityProbe

SITE_DIGEST = "a" * 64
BROWSER_DIGEST = "b" * 64


def make_store(tmp_path) -> BrowserProfileStore:
    return BrowserProfileStore(
        root=tmp_path / "profiles",
        process_probe=DeterministicProcessIdentityProbe(),
    )


def create_profile(store):
    return store.create(
        site_policy_digest=SITE_DIGEST,
        account_label="test account",
        browser_identity_digest=BROWSER_DIGEST,
    )


def lock_path(tmp_path, ref):
    return tmp_path / "profiles" / ref.profile_id / "writer.lock"


def test_acquire_and_release_allow_serial_writers(tmp_path):
    store = make_store(tmp_path)
    ref = create_profile(store)
    lease = store.acquire_writer(ref)
    store.release_writer(lease)
    # 新 store 实例（重启后同一 root）在 release 后可以取得 writer。
    fresh = make_store(tmp_path)
    second = fresh.acquire_writer(ref)
    fresh.release_writer(second)


def test_live_lock_is_never_stolen_by_second_writer(tmp_path):
    store = make_store(tmp_path)
    ref = create_profile(store)
    lease = store.acquire_writer(ref)
    with pytest.raises(ProfileLockHeldError):
        make_store(tmp_path).acquire_writer(ref)
    store.release_writer(lease)


def test_corrupt_live_lock_fails_closed(tmp_path):
    store = make_store(tmp_path)
    ref = create_profile(store)
    lock_path(tmp_path, ref).write_bytes(b"\x00 not json")
    with pytest.raises(ProfileLockUnknownError):
        make_store(tmp_path).acquire_writer(ref)


def test_lock_identity_mismatch_fails_closed(tmp_path):
    # 格式有效但 pid/start identity 与当前进程不符：无法证明 stale，不得偷锁。
    store = make_store(tmp_path)
    ref = create_profile(store)
    lock_path(tmp_path, ref).write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "started_at": "mismatched-identity",
                "lease_id": "c" * 32,
                "acquired_revision": ref.revision,
            }
        )
    )
    with pytest.raises(ProfileLockUnknownError):
        make_store(tmp_path).acquire_writer(ref)


def test_revoked_profile_cannot_acquire_writer(tmp_path):
    store = make_store(tmp_path)
    ref = create_profile(store)
    revoked = store.revoke(ref)
    with pytest.raises(ProfileRevokedError):
        make_store(tmp_path).acquire_writer(revoked)


def test_clear_closes_writer_semantics_and_stale_release_never_touches_new_profile(
    tmp_path,
):
    # 003 合同：active writer 期间 clear 明确拒绝（busy），不删除 lock/profile；
    # release 后 clear 正常 CLEANED；旧 lease 的迟来 release 仍是安全 no-op。
    store = make_store(tmp_path)
    ref = create_profile(store)
    lease = store.acquire_writer(ref)
    with pytest.raises(ProfileLockHeldError):
        store.clear(ref)
    assert (tmp_path / "profiles" / ref.profile_id).is_dir()
    assert lock_path(tmp_path, ref).exists()
    store.release_writer(lease)
    outcome = store.clear(ref)
    assert outcome is BrowserCleanupOutcome.CLEANED
    assert not (tmp_path / "profiles" / ref.profile_id).exists()
    with pytest.raises(ProfileNotFoundError):
        store.open(ref.profile_id)
    # 旧 lease 的迟来 release 必须是安全 no-op，不影响任何新 profile。
    replacement = create_profile(store)
    store.release_writer(lease)
    assert (tmp_path / "profiles" / replacement.profile_id).is_dir()
    assert store.open(replacement.profile_id) == replacement


# --------------------------------------------------------------------------- #
# 审计 blocker A（2026-08-28 Codex review）：holder 存在性/identity unknown
# 不得被当作 dead/stale；只有明确不存在才允许 takeover。
# --------------------------------------------------------------------------- #


class StubIdentityProbe:
    """注入的 tri-state probe：self 与 holder 两套确定身份。"""

    def __init__(self, holder, self_identity):
        self._holder = holder
        self._self = self_identity

    def probe(self, pid):
        return self._self if pid == os.getpid() else self._holder


def guarded_store(tmp_path, holder, self_identity):
    return BrowserProfileStore(
        root=tmp_path / "profiles",
        process_probe=StubIdentityProbe(holder, self_identity),
    )


SELF_LIVE = lambda: SimpleNamespace(exists=True, started_at="self-start")  # noqa: E731


def test_unknown_holder_existence_never_takes_over_lock(tmp_path):
    store = make_store(tmp_path)
    ref = create_profile(store)
    lock_path(tmp_path, ref).write_text(
        json.dumps(
            {
                "pid": 4242,
                "started_at": "some-start",
                "lease_id": "c" * 32,
                "acquired_revision": ref.revision,
            }
        )
    )
    unknown = SimpleNamespace(exists=None, started_at=None)
    with pytest.raises(ProfileLockUnknownError):
        guarded_store(tmp_path, unknown, SELF_LIVE()).acquire_writer(ref)
    # fail closed 发生在 unlink/重写之前：原锁内容原样保留。
    assert json.loads(lock_path(tmp_path, ref).read_text())["pid"] == 4242


def test_confirmed_dead_holder_allows_stale_takeover(tmp_path):
    store = make_store(tmp_path)
    ref = create_profile(store)
    lock_path(tmp_path, ref).write_text(
        json.dumps(
            {
                "pid": 4242,
                "started_at": "old-start",
                "lease_id": "c" * 32,
                "acquired_revision": ref.revision,
            }
        )
    )
    dead = SimpleNamespace(exists=False, started_at=None)
    guarded = guarded_store(tmp_path, dead, SELF_LIVE())
    lease = guarded.acquire_writer(ref)
    payload = json.loads(lock_path(tmp_path, ref).read_text())
    assert payload["pid"] == os.getpid()
    assert payload["started_at"] == "self-start"
    assert payload["lease_id"] == lease.lease_id
    assert payload["acquired_revision"] == ref.revision
    guarded.release_writer(lease)


# --------------------------------------------------------------------------- #
# 第二轮审计（2026-08-28）：closed lock decode + takeover TOCTOU
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"pid": 4242, "started_at": "x", "extra": 1}, id="extra-key"),
        pytest.param(
            {
                "pid": 4242,
                "started_at": "x",
                "lease_id": "c" * 32,
                "acquired_revision": 1,
                "extra": 1,
            },
            id="four-field-extra-key",
        ),
        pytest.param({"pid": True, "started_at": "x"}, id="bool-pid"),
        pytest.param(
            {
                "pid": 4242,
                "started_at": "x",
                "lease_id": "c" * 32,
                "acquired_revision": True,
            },
            id="bool-acquired-revision",
        ),
        pytest.param(
            {
                "pid": 4242,
                "started_at": "x",
                "lease_id": "not-hex-nonce-0000000000000000",
                "acquired_revision": 1,
            },
            id="non-hex-lease-id",
        ),
        pytest.param({"pid": 4242, "started_at": ""}, id="empty-started-at"),
        pytest.param(
            {"pid": 4242, "started_at": "x", "lease_id": "c" * 32, "acquired_revision": 0},
            id="zero-acquired-revision",
        ),
        pytest.param({"pid": 4242, "started_at": "s" * 70000}, id="oversized-started-at"),
    ],
)
def test_lock_decode_rejects_non_contract_payloads(tmp_path, payload):
    store = make_store(tmp_path)
    ref = create_profile(store)
    lock_path(tmp_path, ref).write_text(json.dumps(payload))
    with pytest.raises(ProfileLockUnknownError):
        store.acquire_writer(ref)


# 两个 contender 都在进入 per-profile guard 前停靠（003 协议：self identity
# probe 在 guard 外，stale lock 的判定/unlink/create 全在 guard 内），然后按
# rank 错开——确定性重现“两位 contender 竞争同一 stale 锁”的 takeover 竞态。
# guard 序列化实现下必须恰好一位 writer。
CONTENDER_SCRIPT = """
import os
import sys
import time
from pathlib import Path

from agent.browser.profile_store import BrowserProfileStore
from tests.browser.profile_probe import DeterministicProcessIdentityProbe

root = Path(sys.argv[1])
profile_id = sys.argv[2]
rank = float(sys.argv[3])
go_path = Path(sys.argv[4])
done_path = Path(sys.argv[5])
flag_path = Path(sys.argv[6])
ready_path = flag_path.with_name(flag_path.stem.replace("flag", "arrived"))
STALE_PID = 4242

real = DeterministicProcessIdentityProbe()


class BarrierProbe:
    def probe(self, pid):
        if pid == os.getpid():
            # 停靠点在 guard 之前：两位 contender 可同时到达 barrier。
            ready_path.write_text("")
            deadline = time.monotonic() + 15
            while not go_path.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            time.sleep(rank)
            return real.probe(pid)
        return real.probe(pid)


store = BrowserProfileStore(root=root, process_probe=BarrierProbe())
ref = store.open(profile_id)
ready_path.write_text("")
try:
    store.acquire_writer(ref)
    flag_path.write_text("acquired")
except Exception:
    flag_path.write_text("rejected")
deadline = time.monotonic() + 30
while not done_path.exists() and time.monotonic() < deadline:
    time.sleep(0.02)
"""


def test_single_writer_under_deterministic_takeover_race(tmp_path):
    store = make_store(tmp_path)
    ref = create_profile(store)
    lock_path(tmp_path, ref).write_text(
        json.dumps(
            {
                "pid": 4242,
                "started_at": "old-start",
                "lease_id": "c" * 32,
                "acquired_revision": ref.revision,
            }
        )
    )
    go_path = tmp_path / "go"
    done_path = tmp_path / "done"
    flags = [tmp_path / f"flag-{index}" for index in range(2)]
    processes = [
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                CONTENDER_SCRIPT,
                str(tmp_path / "profiles"),
                ref.profile_id,
                str(rank),
                str(go_path),
                str(done_path),
                str(flag),
            ],
            cwd=os.getcwd(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for rank, flag in ((0.0, flags[0]), (0.25, flags[1]))
    ]
    try:
        deadline = time.monotonic() + 15
        arrived = [p.with_name(p.stem.replace("flag", "arrived")) for p in flags]
        while time.monotonic() < deadline:
            if all(path.exists() for path in arrived) or any(
                proc.poll() is not None for proc in processes
            ):
                break
            time.sleep(0.02)
        go_path.write_text("")
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and not all(path.exists() for path in flags):
            if any(proc.poll() is not None for proc in processes):
                break
            time.sleep(0.02)
        outcomes = [
            path.read_text() if path.exists() else "missing" for path in flags
        ]
    finally:
        done_path.write_text("")
        for proc in processes:
            proc.wait(timeout=30)
    # 无论时序如何，同一 persistent profile 同时最多一位 writer。
    assert outcomes.count("acquired") == 1, outcomes


# --------------------------------------------------------------------------- #
# 003：exact acquisition lease、四字段 lock 与 mutation 线性化
# --------------------------------------------------------------------------- #


def metadata_path(tmp_path, ref):
    return tmp_path / "profiles" / ref.profile_id / "metadata.json"


def test_late_release_keeps_new_acquisition_lock(tmp_path):
    # Lease ABA：L1 acquire/release → L2 acquire → 迟到的 release(L1)
    # 不得删除 L2 的锁；第三个 writer 仍被拒；两次 acquisition nonce 不同。
    store = make_store(tmp_path)
    ref = create_profile(store)
    first = store.acquire_writer(ref)
    store.release_writer(first)
    second = store.acquire_writer(ref)

    store.release_writer(first)

    payload = json.loads(lock_path(tmp_path, ref).read_text())
    assert set(payload) == {
        "pid",
        "started_at",
        "lease_id",
        "acquired_revision",
    }
    assert payload["lease_id"] == second.lease_id
    assert payload["acquired_revision"] == second.profile.revision
    assert first.lease_id != second.lease_id
    assert first.profile == second.profile
    with pytest.raises(ProfileLockHeldError):
        make_store(tmp_path).acquire_writer(ref)
    store.release_writer(second)


def test_live_writer_blocks_revoke_and_clear_from_independent_store(tmp_path):
    # mutation 与 writer acquisition 线性化：writer 先成功，普通 mutation
    # 明确 busy，状态与文件原样保留；release 后同一命令正常成功。
    store = make_store(tmp_path)
    ref = create_profile(store)
    lease = store.acquire_writer(ref)
    metadata_before = metadata_path(tmp_path, ref).read_bytes()
    independent = make_store(tmp_path)

    with pytest.raises(ProfileLockHeldError):
        independent.revoke(ref)
    with pytest.raises(ProfileLockHeldError):
        independent.clear(ref)

    assert metadata_path(tmp_path, ref).read_bytes() == metadata_before
    assert lock_path(tmp_path, ref).exists()
    assert store.open(ref.profile_id) == ref
    assert not (tmp_path / "profiles" / "_quarantine").exists()

    store.release_writer(lease)
    revoked = independent.revoke(ref)
    assert revoked.status is ProfileStatus.REVOKED
    outcome = independent.clear(revoked)
    assert outcome is BrowserCleanupOutcome.CLEANED


@pytest.mark.parametrize(
    "lock_text",
    [
        pytest.param(
            json.dumps({"pid": os.getpid(), "started_at": "legacy"}),
            id="legacy-two-field",
        ),
        pytest.param(b"\x00 not json", id="corrupt"),
    ],
)
def test_unknown_writer_lock_blocks_revoke_and_clear_without_quarantine(
    tmp_path, lock_text
):
    # writer identity 无法确定：mutation 不删除、不 quarantine、不报成功。
    store = make_store(tmp_path)
    ref = create_profile(store)
    lock_path(tmp_path, ref).write_bytes(
        lock_text.encode("utf-8") if isinstance(lock_text, str) else lock_text
    )
    metadata_before = metadata_path(tmp_path, ref).read_bytes()
    independent = make_store(tmp_path)

    with pytest.raises(ProfileLockUnknownError):
        independent.revoke(ref)
    with pytest.raises(ProfileLockUnknownError):
        independent.clear(ref)

    assert metadata_path(tmp_path, ref).read_bytes() == metadata_before
    assert lock_path(tmp_path, ref).exists()
    assert (tmp_path / "profiles" / ref.profile_id).is_dir()
    assert not (tmp_path / "profiles" / "_quarantine").exists()
    assert store.open(ref.profile_id) == ref


def test_advance_revision_requires_exact_lease_identity(tmp_path):
    store = make_store(tmp_path)
    ref = create_profile(store)
    lease = store.acquire_writer(ref)

    forged_nonce = replace(lease, lease_id="f" * 32)
    with pytest.raises(ProfileLockUnknownError):
        store.advance_revision(forged_nonce, expected_revision=1)
    forged_owner = replace(lease, pid=lease.pid + 1, started_at="other-start")
    with pytest.raises(ProfileLockUnknownError):
        store.advance_revision(forged_owner, expected_revision=1)
    with pytest.raises(ProfileRevisionConflict):
        store.advance_revision(lease, expected_revision=2)
    # revoked snapshot 不能推进：直接把 metadata 置为 revoked（保持其余字段），
    # 验证 lease snapshot 的 ACTIVE 要求。
    lock_path(tmp_path, ref).unlink()
    path = metadata_path(tmp_path, ref)
    payload = json.loads(path.read_text())
    payload["status"] = "revoked"
    path.write_text(json.dumps(payload))
    with pytest.raises(ProfileRevokedError):
        store.advance_revision(lease, expected_revision=1)
    assert store.open(ref.profile_id).revision == 1

    # released lease 无法推进。
    active = create_profile(store)
    second = store.acquire_writer(active)
    store.release_writer(second)
    with pytest.raises(ProfileLockUnknownError):
        store.advance_revision(second, expected_revision=1)
    assert store.open(active.profile_id).revision == 1


def test_advance_revision_is_cas_once_then_idempotent(tmp_path):
    store = make_store(tmp_path)
    ref = create_profile(store)
    lease = store.acquire_writer(ref)

    advanced = store.advance_revision(lease, expected_revision=1)
    assert advanced.revision == 2
    retried = store.advance_revision(lease, expected_revision=1)
    assert retried.revision == 2

    store.release_writer(lease)
    assert store.open(ref.profile_id).revision == 2


def test_new_lease_cannot_impersonate_old_completion(tmp_path):
    # 新 R2 lease 冒充旧 R1 completion：expected_revision 必须等于
    # acquisition revision，拒绝且 revision 不变。
    store = make_store(tmp_path)
    ref = create_profile(store)
    first = store.acquire_writer(ref)
    store.advance_revision(first, expected_revision=1)
    store.release_writer(first)

    current = store.open(ref.profile_id)
    assert current.revision == 2
    second = store.acquire_writer(current)
    with pytest.raises(ProfileRevisionConflict):
        store.advance_revision(second, expected_revision=1)
    assert store.open(ref.profile_id).revision == 2
    store.release_writer(second)


# --------------------------------------------------------------------------- #
# 003 修复批：clear 的 writer 判定先于 metadata 读取；锁 syscall 的
# closed 分类；acquisition snapshot 的 ACTIVE 身份。
# --------------------------------------------------------------------------- #


def damage_metadata(tmp_path, ref, *, missing):
    path = metadata_path(tmp_path, ref)
    if missing:
        path.unlink()
    else:
        path.write_text("{ not json")


@pytest.mark.parametrize("missing", [False, True], ids=["corrupt", "missing"])
def test_clear_with_live_writer_and_unreadable_metadata_fails_busy_without_quarantine(
    tmp_path, missing,
):
    # live writer 优先于 metadata 可读性：clear 不得把仍在使用的 canonical
    # profile（连同其 writer.lock）先 quarantine 掉。
    store = make_store(tmp_path)
    ref = create_profile(store)
    lease = store.acquire_writer(ref)
    damage_metadata(tmp_path, ref, missing=missing)

    with pytest.raises(ProfileLockHeldError):
        make_store(tmp_path).clear(ref)

    assert (tmp_path / "profiles" / ref.profile_id).is_dir()
    assert lock_path(tmp_path, ref).exists()
    assert not (tmp_path / "profiles" / "_quarantine").exists()
    store.release_writer(lease)


@pytest.mark.parametrize("missing", [False, True], ids=["corrupt", "missing"])
def test_clear_with_unknown_lock_and_unreadable_metadata_fails_closed_without_quarantine(
    tmp_path, missing,
):
    # malformed/unknown writer lock 同样优先于 metadata 可读性：不删除、
    # 不 quarantine、不报告成功。
    store = make_store(tmp_path)
    ref = create_profile(store)
    lock_path(tmp_path, ref).write_text("{ not a lock")
    damage_metadata(tmp_path, ref, missing=missing)

    with pytest.raises(ProfileLockUnknownError):
        make_store(tmp_path).clear(ref)

    assert (tmp_path / "profiles" / ref.profile_id).is_dir()
    assert lock_path(tmp_path, ref).read_text() == "{ not a lock"
    assert not (tmp_path / "profiles" / "_quarantine").exists()


def test_acquire_writer_classifies_lock_stat_failure_as_unknown(tmp_path, monkeypatch):
    # _lock_exists 只把 ENOENT 当“无锁”；其余 OSError（如 EACCES）必须
    # fail closed 为 unknown，不得当作“锁存在且有效”继续判定。
    import errno

    import agent.browser.profile_store as profile_store_module

    store = make_store(tmp_path)
    ref = create_profile(store)
    lease = store.acquire_writer(ref)
    real_stat = os.stat

    def stat_denying_lock(name, *args, **kwargs):
        if isinstance(name, str) and name == "writer.lock":
            raise PermissionError(errno.EACCES, "stat denied")
        return real_stat(name, *args, **kwargs)

    monkeypatch.setattr(profile_store_module.os, "stat", stat_denying_lock)
    try:
        with pytest.raises(ProfileLockUnknownError):
            make_store(tmp_path).acquire_writer(ref)
    finally:
        monkeypatch.undo()
    store.release_writer(lease)


def test_acquire_writer_classifies_lock_create_failure_as_unknown(tmp_path, monkeypatch):
    # _create_lock_fd 只有 FileExistsError 表示 held；其余 OSError fail
    # closed 为 unknown，不得伪装成“另一 writer 刚抢到锁”。
    import errno

    store = make_store(tmp_path)
    ref = create_profile(store)
    real_open = os.open

    def open_denying_lock_create(name, flags, *args, **kwargs):
        if isinstance(name, str) and name == "writer.lock" and flags & os.O_EXCL:
            raise PermissionError(errno.EACCES, "open denied")
        return real_open(name, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", open_denying_lock_create)
    try:
        with pytest.raises(ProfileLockUnknownError):
            store.acquire_writer(ref)
    finally:
        monkeypatch.undo()
    assert not lock_path(tmp_path, ref).exists()


def test_advance_revision_rejects_forged_non_active_lease_snapshot(tmp_path):
    # acquire_writer 只会发出 ACTIVE snapshot；status 非 ACTIVE 的 lease
    # 必然是伪造，completion 必须拒绝且 revision 不变。
    store = make_store(tmp_path)
    ref = create_profile(store)
    lease = store.acquire_writer(ref)
    forged = replace(
        lease, profile=replace(lease.profile, status=ProfileStatus.REVOKED)
    )
    with pytest.raises(ProfileRevokedError):
        store.advance_revision(forged, expected_revision=1)
    assert store.open(ref.profile_id).revision == 1
    store.release_writer(lease)


def test_acquire_writer_classifies_lock_write_confirmation_failure_as_unknown(
    tmp_path, monkeypatch
):
    # 003 修复批 2（fresh reviewer）：_create_lock_fd 的写入确认阶段
    # （fdopen/json.dump/flush/fsync）OSError 原样逃逸并留下已创建的 lock；
    # public acquire_writer 必须 fail closed 为 ProfileLockUnknownError，
    # 不 unlink 不确定状态，revision/metadata 不变。
    import errno

    store = make_store(tmp_path)
    ref = create_profile(store)
    metadata_before = metadata_path(tmp_path, ref).read_bytes()

    def fsync_failing(fd):
        raise OSError(errno.EIO, "lock write confirmation failed")

    monkeypatch.setattr(os, "fsync", fsync_failing)
    try:
        with pytest.raises(ProfileLockUnknownError):
            store.acquire_writer(ref)
    finally:
        monkeypatch.undo()

    # 不确定状态不删除：lock 原样保留，metadata/revision 未动，后续 writer
    # 被明确拒绝（残留 lock 按本进程 live 处理）。
    assert lock_path(tmp_path, ref).exists()
    assert metadata_path(tmp_path, ref).read_bytes() == metadata_before
    assert store.open(ref.profile_id) == ref
    with pytest.raises(ProfileLockHeldError):
        make_store(tmp_path).acquire_writer(ref)
