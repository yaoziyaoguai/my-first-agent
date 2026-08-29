"""018 Task 2 Step 1：owner-only persistent profile store 的安全 Reds（先 Red）。

覆盖 spec §3.2：root/目录 0700、metadata 0600、opaque profile_id 与 digest-only
公开接口（account 原文不落盘）、no-follow（metadata/profile 目录 symlink 拒绝）、
revision CAS、revoke 阻断复用、clear 只删 canonical owned root，partial 或
identity 不确定返回 CLEANUP_UNKNOWN 并 quarantine。
"""

import json
import os
import stat
import subprocess
import sys
import time
from dataclasses import fields, replace

import pytest

from agent.browser.contracts import BrowserCleanupOutcome
from agent.browser.profile_store import (
    BrowserProfileRefV1,
    BrowserProfileStore,
    ProfileIntegrityError,
    ProfileNotFoundError,
    ProfileRevisionConflict,
    ProfileRevokedError,
    ProfileStatus,
)

SITE_DIGEST = "a" * 64
BROWSER_DIGEST = "b" * 64


def make_store(tmp_path) -> BrowserProfileStore:
    return BrowserProfileStore(root=tmp_path / "profiles")


def create_profile(store, account_label="alice@example.test"):
    return store.create(
        site_policy_digest=SITE_DIGEST,
        account_label=account_label,
        browser_identity_digest=BROWSER_DIGEST,
    )


def profile_dir(tmp_path, ref):
    return tmp_path / "profiles" / ref.profile_id


def test_profile_metadata_is_owner_only_and_opaque(tmp_path):
    store = make_store(tmp_path)
    ref = create_profile(store)
    assert "alice" not in ref.profile_id
    assert "example.test" not in ref.profile_id
    assert stat.S_IMODE((tmp_path / "profiles").stat().st_mode) == 0o700
    directory = profile_dir(tmp_path, ref)
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    metadata = directory / "metadata.json"
    assert stat.S_IMODE(metadata.stat().st_mode) == 0o600
    # account label 原文绝不落盘（metadata 只存 digest）。
    assert b"alice" not in metadata.read_bytes()
    assert b"example.test" not in metadata.read_bytes()


def test_public_interface_returns_only_opaque_digest_identity(tmp_path):
    ref = create_profile(make_store(tmp_path))
    assert {item.name for item in fields(BrowserProfileRefV1)} == {
        "profile_id",
        "revision",
        "site_policy_digest",
        "account_label_digest",
        "browser_identity_digest",
        "status",
    }
    assert ref.revision == 1
    assert ref.status is ProfileStatus.ACTIVE
    assert len(ref.account_label_digest) == 64


def test_open_returns_current_ref_and_missing_profile_rejected(tmp_path):
    store = make_store(tmp_path)
    ref = create_profile(store)
    assert store.open(ref.profile_id) == ref
    with pytest.raises(ProfileNotFoundError):
        store.open("profile-does-not-exist")


def test_open_rejects_metadata_symlink(tmp_path):
    store = make_store(tmp_path)
    ref = create_profile(store)
    metadata = profile_dir(tmp_path, ref) / "metadata.json"
    outside = tmp_path / "outside.json"
    outside.write_text("{}")
    metadata.unlink()
    metadata.symlink_to(outside)
    with pytest.raises(ProfileIntegrityError):
        store.open(ref.profile_id)


def test_open_rejects_profile_directory_symlink(tmp_path):
    store = make_store(tmp_path)
    ref = create_profile(store)
    canonical = profile_dir(tmp_path, ref)
    shadow = tmp_path / "profiles" / "shadow"
    canonical.rename(shadow)
    canonical.symlink_to(shadow)
    with pytest.raises(ProfileIntegrityError):
        store.open(ref.profile_id)


def test_revision_advance_requires_matching_expected_revision(tmp_path):
    store = make_store(tmp_path)
    ref = create_profile(store)
    bumped = store.advance_revision(ref, expected_revision=1)
    assert bumped.revision == 2
    with pytest.raises(ProfileRevisionConflict):
        store.advance_revision(ref, expected_revision=1)
    assert store.open(ref.profile_id).revision == 2


def test_revoke_blocks_reuse(tmp_path):
    store = make_store(tmp_path)
    ref = create_profile(store)
    revoked = store.revoke(ref)
    assert revoked.status is ProfileStatus.REVOKED
    with pytest.raises(ProfileRevokedError):
        store.advance_revision(revoked, expected_revision=1)


def test_clear_removes_only_canonical_owned_root(tmp_path):
    store = make_store(tmp_path)
    ref = create_profile(store)
    directory = profile_dir(tmp_path, ref)
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("keep")
    # profile 目录内的 symlink 指向 root 外：clear 不得 follow、不得删外部文件。
    (directory / "link").symlink_to(outside)
    outcome = store.clear(ref)
    assert outcome is BrowserCleanupOutcome.CLEANED
    assert not directory.exists()
    assert outside.exists()
    with pytest.raises(ProfileNotFoundError):
        store.open(ref.profile_id)


def test_clear_with_corrupt_metadata_returns_cleanup_unknown_and_quarantines(tmp_path):
    store = make_store(tmp_path)
    ref = create_profile(store)
    (profile_dir(tmp_path, ref) / "metadata.json").write_text("{ not json")
    outcome = store.clear(ref)
    assert outcome is BrowserCleanupOutcome.CLEANUP_UNKNOWN
    # canonical 名已被 quarantine，旧 identity 不可复用。
    with pytest.raises(ProfileNotFoundError):
        store.open(ref.profile_id)


def test_clear_rejects_path_escape_and_reports_cleanup_unknown(tmp_path):
    store = make_store(tmp_path)
    ref = create_profile(store)
    canonical = profile_dir(tmp_path, ref)
    escaped = tmp_path / "escaped"
    canonical.rename(escaped)
    canonical.symlink_to(escaped)
    outcome = store.clear(ref)
    assert outcome is BrowserCleanupOutcome.CLEANUP_UNKNOWN
    # 不 follow symlink 出 owned root，目标原样保留。
    assert escaped.exists()


def test_store_root_symlink_fails_closed_before_writing(tmp_path):
    target = tmp_path / "outside-profile-target"
    target.mkdir()
    (tmp_path / "profiles").symlink_to(target)
    store = BrowserProfileStore(root=tmp_path / "profiles")
    with pytest.raises(ProfileIntegrityError):
        create_profile(store)
    # fail closed 必须发生在向 symlink target 写入任何内容之前。
    assert list(target.iterdir()) == []


# --------------------------------------------------------------------------- #
# 审计 blockers B/C/D + owner-only drift（2026-08-28 Codex review）
# --------------------------------------------------------------------------- #


def test_forged_digest_reference_cannot_mutate_profile(tmp_path):
    store = make_store(tmp_path)
    ref = create_profile(store)
    forged = replace(ref, site_policy_digest="9" * 64)
    with pytest.raises(ProfileIntegrityError):
        store.advance_revision(forged, expected_revision=1)
    with pytest.raises(ProfileIntegrityError):
        store.revoke(forged)
    with pytest.raises(ProfileIntegrityError):
        store.acquire_writer(forged)
    # 全部拒绝且零副作用：metadata revision 未动。
    assert store.open(ref.profile_id).revision == 1


def test_forged_status_reference_cannot_acquire_writer(tmp_path):
    store = make_store(tmp_path)
    ref = create_profile(store)
    forged = replace(ref, status=ProfileStatus.REVOKED)
    with pytest.raises(ProfileIntegrityError):
        store.acquire_writer(forged)


def test_stale_revision_reference_cannot_revoke(tmp_path):
    store = make_store(tmp_path)
    ref = create_profile(store)
    store.advance_revision(ref, expected_revision=1)
    with pytest.raises(ProfileRevisionConflict):
        store.revoke(ref)
    stored = store.open(ref.profile_id)
    assert stored.revision == 2
    assert stored.status is ProfileStatus.ACTIVE


def test_quarantine_root_symlink_never_receives_profiles(tmp_path):
    store = make_store(tmp_path)
    ref = create_profile(store)
    outside = tmp_path / "outside-quarantine"
    outside.mkdir()
    (tmp_path / "profiles" / "_quarantine").symlink_to(outside)
    (profile_dir(tmp_path, ref) / "metadata.json").write_text("{ corrupt")
    outcome = store.clear(ref)
    assert outcome is BrowserCleanupOutcome.CLEANUP_UNKNOWN
    # canonical profile 未被 rename 出 owned root；symlink target 保持空。
    assert list(outside.iterdir()) == []
    assert profile_dir(tmp_path, ref).is_dir()


@pytest.mark.parametrize(
    "mutation",
    ["advance_revision", "revoke", "acquire_writer", "clear"],
)
def test_root_replaced_by_symlink_fails_closed_before_any_write(tmp_path, mutation):
    store = make_store(tmp_path)
    ref = create_profile(store)
    canonical_root = tmp_path / "profiles"
    escaped = tmp_path / "escaped-root"
    canonical_root.rename(escaped)
    canonical_root.symlink_to(escaped)
    metadata = escaped / ref.profile_id / "metadata.json"
    before = metadata.read_bytes()
    with pytest.raises(ProfileIntegrityError):
        if mutation == "advance_revision":
            store.advance_revision(ref, expected_revision=1)
        elif mutation == "revoke":
            store.revoke(ref)
        elif mutation == "acquire_writer":
            store.acquire_writer(ref)
        else:
            store.clear(ref)
    # outside metadata 一字节未动。
    assert metadata.read_bytes() == before


def test_overmode_files_are_hardened_to_owner_only(tmp_path):
    store = make_store(tmp_path)
    ref = create_profile(store)
    directory = profile_dir(tmp_path, ref)
    os.chmod(directory, 0o755)
    os.chmod(directory / "metadata.json", 0o644)
    assert make_store(tmp_path).open(ref.profile_id) == ref
    assert stat.S_IMODE((directory / "metadata.json").stat().st_mode) == 0o600
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700


# --------------------------------------------------------------------------- #
# 第二轮审计（2026-08-28）：revoked clear、closed decode
# --------------------------------------------------------------------------- #


def test_clear_revoked_profile_returns_cleaned(tmp_path):
    store = make_store(tmp_path)
    ref = create_profile(store)
    revoked = store.revoke(ref)
    assert store.clear(revoked) is BrowserCleanupOutcome.CLEANED
    assert not profile_dir(tmp_path, ref).exists()
    with pytest.raises(ProfileNotFoundError):
        store.open(ref.profile_id)


def rewrite_metadata(tmp_path, ref, mutation):
    path = profile_dir(tmp_path, ref) / "metadata.json"
    payload = json.loads(path.read_text())
    mutation(payload)
    path.write_text(json.dumps(payload))


@pytest.mark.parametrize(
    "mutation",
    [
        pytest.param(lambda p: p.update(revision="1"), id="string-revision"),
        pytest.param(lambda p: p.update(revision=True), id="bool-revision"),
        pytest.param(lambda p: p.update(extra=1), id="extra-key"),
        pytest.param(lambda p: p.update(site_policy_digest="Z" * 64), id="non-hex-digest"),
    ],
)
def test_metadata_decode_rejects_non_contract_payloads(tmp_path, mutation):
    store = make_store(tmp_path)
    ref = create_profile(store)
    rewrite_metadata(tmp_path, ref, mutation)
    with pytest.raises(ProfileIntegrityError):
        store.open(ref.profile_id)


def test_metadata_decode_rejects_non_regular_file(tmp_path):
    store = make_store(tmp_path)
    ref = create_profile(store)
    metadata = profile_dir(tmp_path, ref) / "metadata.json"
    metadata.unlink()
    metadata.mkdir()
    with pytest.raises(ProfileIntegrityError):
        store.open(ref.profile_id)


def test_metadata_decode_rejects_oversized_payload(tmp_path):
    store = make_store(tmp_path)
    ref = create_profile(store)
    # 合法 JSON + 70 KiB 尾随空白：解析层放行，只有 bounded 读取会拒绝。
    path = profile_dir(tmp_path, ref) / "metadata.json"
    path.write_text(path.read_text() + " " * 70000)
    with pytest.raises(ProfileIntegrityError):
        store.open(ref.profile_id)


# --------------------------------------------------------------------------- #
# 第三轮审计（2026-08-28）：CAS second-open descriptor safety、
# root-anchored guard、create 输入合同
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "bad_digest",
    ["Z" * 64, "a" * 63, "", "digest"],
)
def test_create_rejects_non_contract_digest_inputs(tmp_path, bad_digest):
    store = make_store(tmp_path)
    with pytest.raises(ProfileIntegrityError):
        store.create(
            site_policy_digest=bad_digest,
            account_label="alice@example.test",
            browser_identity_digest="b" * 64,
        )
    # 拒绝发生在创建任何目录之前：root 下没有 profile。
    profiles_root = tmp_path / "profiles"
    if profiles_root.exists():
        assert list(profiles_root.glob("profile-*")) == []


CAS_PROBE_SCRIPT = """
import os
import sys
from pathlib import Path

from agent.browser.profile_store import BrowserProfileStore, ProfileIntegrityError

root = Path(sys.argv[1])
profile_id = sys.argv[2]
mode = sys.argv[3]

store = BrowserProfileStore(root=root)
ref = store.open(profile_id)
original = store._read_metadata_fd


def read_then_replace(profile_fd):
    payload = original(profile_fd)
    metadata = root / profile_id / "metadata.json"
    if mode == "directory":
        metadata.unlink()
        metadata.mkdir()
    elif mode == "fifo":
        metadata.unlink()
        os.mkfifo(metadata)
    elif mode == "oversized":
        with open(metadata, "a") as handle:
            handle.write(" " * 70000)
    return payload


store._read_metadata_fd = read_then_replace
try:
    store.advance_revision(ref, expected_revision=1)
    print("CAS_COMPLETED")
except ProfileIntegrityError:
    print("CAS_REJECTED")
except BaseException as error:
    print(f"LEAKED:{type(error).__name__}")
"""


@pytest.mark.parametrize("mode", ["directory", "fifo", "oversized"])
def test_cas_second_open_fails_closed_on_replaced_metadata(tmp_path, mode):
    # pre-read 之后、CAS second open 之前替换 metadata：必须 closed 拒绝，
    # 不得 hang（FIFO）、不得泄漏原始 OSError（目录）、不得放行（oversized）。
    store = make_store(tmp_path)
    ref = create_profile(store)
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            CAS_PROBE_SCRIPT,
            str(tmp_path / "profiles"),
            ref.profile_id,
            mode,
        ],
        cwd=os.getcwd(),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        stdout, _ = process.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        pytest.fail(f"CAS second open hung on replaced metadata ({mode})")
    assert stdout.strip() == "CAS_REJECTED", stdout


LATE_CONTENDER_SCRIPT = """
import sys
import time
from pathlib import Path

from agent.browser.profile_store import BrowserProfileStore, OsProcessIdentityProbe

root = Path(sys.argv[1])
profile_id = sys.argv[2]
arrived_path = Path(sys.argv[3])
go_path = Path(sys.argv[4])
flag_path = Path(sys.argv[5])

real = OsProcessIdentityProbe()


class GateProbe:
    # acquire 内部、metadata 校验之后、guard 之前的确定性停靠点。
    def probe(self, pid):
        arrived_path.write_text("")
        deadline = time.monotonic() + 10
        while not go_path.exists() and time.monotonic() < deadline:
            time.sleep(0.005)
        return real.probe(pid)


store = BrowserProfileStore(root=root, process_probe=GateProbe())
ref = store.open(profile_id)
try:
    store.acquire_writer(ref)
    flag_path.write_text("acquired")
except BaseException as error:
    flag_path.write_text(f"rejected:{type(error).__name__}")
"""


def test_clear_serializes_against_late_guard_recreation(tmp_path, monkeypatch):
    # clear 的 tree removal 与 canonical rmdir 之间，late contender 不得进入
    # 临界区重建 writer lock，也不得把 clear 推成 quarantine 漂移。
    store = make_store(tmp_path)
    ref = create_profile(store)
    arrived = tmp_path / "late-arrived"
    go = tmp_path / "late-go"
    flag = tmp_path / "late-flag"
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            LATE_CONTENDER_SCRIPT,
            str(tmp_path / "profiles"),
            ref.profile_id,
            str(arrived),
            str(go),
            str(flag),
        ],
        cwd=os.getcwd(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    original_remove = BrowserProfileStore._remove_tree_fd

    def remove_then_release_contender(dir_fd):
        original_remove(dir_fd)
        go.write_text("")
        deadline = time.monotonic() + 4
        while not flag.exists() and time.monotonic() < deadline:
            time.sleep(0.02)

    monkeypatch.setattr(
        BrowserProfileStore,
        "_remove_tree_fd",
        staticmethod(remove_then_release_contender),
    )
    deadline = time.monotonic() + 15
    while not arrived.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    outcome = store.clear(ref)
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
    contender = flag.read_text() if flag.exists() else "blocked"
    assert outcome is BrowserCleanupOutcome.CLEANED
    # clear 临界区内 contender 必须被挡住；结束后也只能 fail closed。
    assert contender == "blocked" or contender.startswith("rejected"), contender
    assert not profile_dir(tmp_path, ref).exists()
