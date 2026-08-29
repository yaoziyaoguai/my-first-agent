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
from types import SimpleNamespace

import pytest

from agent.browser.contracts import BrowserCleanupOutcome
from agent.browser.profile_store import (
    BrowserProfileStore,
    ProfileLockHeldError,
    ProfileLockUnknownError,
    ProfileNotFoundError,
    ProfileRevokedError,
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
        json.dumps({"pid": os.getpid(), "started_at": "mismatched-identity"})
    )
    with pytest.raises(ProfileLockUnknownError):
        make_store(tmp_path).acquire_writer(ref)


def test_revoked_profile_cannot_acquire_writer(tmp_path):
    store = make_store(tmp_path)
    ref = create_profile(store)
    revoked = store.revoke(ref)
    with pytest.raises(ProfileRevokedError):
        make_store(tmp_path).acquire_writer(revoked)


def test_clear_closes_writer_and_stale_release_never_touches_new_profile(tmp_path):
    # clear 先 revoke/关闭 writer，再删 canonical owned root（plan Step 2）。
    store = make_store(tmp_path)
    ref = create_profile(store)
    lease = store.acquire_writer(ref)
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
        json.dumps({"pid": 4242, "started_at": "some-start"})
    )
    unknown = SimpleNamespace(exists=None, started_at=None)
    with pytest.raises(ProfileLockUnknownError):
        guarded_store(tmp_path, unknown, SELF_LIVE()).acquire_writer(ref)
    # fail closed 发生在 unlink/重写之前：原锁内容原样保留。
    assert json.loads(lock_path(tmp_path, ref).read_text()) == {
        "pid": 4242,
        "started_at": "some-start",
    }


def test_confirmed_dead_holder_allows_stale_takeover(tmp_path):
    store = make_store(tmp_path)
    ref = create_profile(store)
    lock_path(tmp_path, ref).write_text(
        json.dumps({"pid": 4242, "started_at": "old-start"})
    )
    dead = SimpleNamespace(exists=False, started_at=None)
    guarded = guarded_store(tmp_path, dead, SELF_LIVE())
    lease = guarded.acquire_writer(ref)
    payload = json.loads(lock_path(tmp_path, ref).read_text())
    assert payload["pid"] == os.getpid()
    assert payload["started_at"] == "self-start"
    guarded.release_writer(lease)


# --------------------------------------------------------------------------- #
# 第二轮审计（2026-08-28）：closed lock decode + takeover TOCTOU
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"pid": 4242, "started_at": "x", "extra": 1}, id="extra-key"),
        pytest.param({"pid": True, "started_at": "x"}, id="bool-pid"),
        pytest.param({"pid": 4242, "started_at": ""}, id="empty-started-at"),
        pytest.param({"pid": 4242, "started_at": "s" * 70000}, id="oversized-started-at"),
    ],
)
def test_lock_decode_rejects_non_contract_payloads(tmp_path, payload):
    store = make_store(tmp_path)
    ref = create_profile(store)
    lock_path(tmp_path, ref).write_text(json.dumps(payload))
    with pytest.raises(ProfileLockUnknownError):
        store.acquire_writer(ref)


# 两个 contender 都先读到同一个 stale 锁（barrier 保证判定阶段完成后才放行
# unlink/create），然后按 rank 错开——确定性重现“B unlink A 的 live 锁”的
# takeover TOCTOU。serialized 实现下必须恰好一位 writer。
CONTENDER_SCRIPT = """
import sys
import time
from pathlib import Path
from types import SimpleNamespace

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
        if pid == STALE_PID:
            ready_path.write_text("")
            deadline = time.monotonic() + 15
            while not go_path.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            time.sleep(rank)
            return SimpleNamespace(exists=False, started_at=None)
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
        json.dumps({"pid": 4242, "started_at": "old-start"})
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
