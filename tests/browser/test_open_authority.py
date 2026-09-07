"""browser open 精确授权消费与 writer 生命周期线性化（002/003）。

002：获批的 site_bound_interactive open 只消费执行时刻的 exact profile
binding 与 session 租期；final 漂移在 BrowserEnvironment.open 前零 effect。
003：writer acquisition 与 mutation 的线性化——mutation 先成功则旧 binding
零调用拒绝；acquisition 先成功则 mutation busy 且 open 只消费 acquisition
snapshot。所有断言走 public KernelToolRuntime.prepare/invoke；interleaving
用注入 seam（DriftingProfileStore/monotonic clock/acquisition 停靠点）与
Event 同步，不用 sleep 猜竞态。
"""

import threading

import pytest

from agent.browser.contracts import BrowserCleanupOutcome, BrowserHandleV1
from agent.browser.profile_store import (
    BrowserProfileStore,
    ProfileLockHeldError,
    ProfileStatus,
)
from agent.browser.session_store import BrowserSessionStore
from agent.browser.tools import build_browser_tools
from agent.browser.url_policy import browser_site_policy_digest
from agent.runtime.contracts import (
    ApprovalGrant,
    ApprovalRequired,
    ExecutionIntent,
    ToolCall,
    ToolResult,
)
from agent.runtime.tools import KernelToolRuntime
from tests.browser.profile_probe import DeterministicProcessIdentityProbe
from tests.browser.test_tools import RecordingEnvironment, _context

CLOCK = "2026-08-28T10:00:00+00:00"
BROWSER_IDENTITY = "b" * 64


def _profile_store(tmp_path) -> BrowserProfileStore:
    return BrowserProfileStore(
        root=tmp_path / "profiles",
        process_probe=DeterministicProcessIdentityProbe(),
    )


class UniqueSessionRefEnvironment(RecordingEnvironment):
    """每次 open 返回唯一 session_ref，供多次顺序 open 的行为测试使用。"""

    def __init__(self) -> None:
        super().__init__()
        self._opens = 0

    def open(self, spec):
        # open-entry counter：方法入口即计数（self.opened.append），区分
        # “adapter 零调用”与 typed not-started 的一次调用。
        self._opens += 1
        self.opened.append(spec)
        self.profile_revision = spec.profile_revision
        return BrowserHandleV1(
            session_ref=f"session-{self._opens:016x}",
            mode=spec.mode,
            authority_digest=spec.identity_digest,
        )


class SequenceMonotonicClock:
    """按序返回注入的 monotonic 读数；多余读取抛 StopIteration 让测试失败。"""

    def __init__(self, *values: float) -> None:
        self._values = iter(values)
        self.reads = 0

    def __call__(self) -> float:
        self.reads += 1
        return next(self._values)


def _interactive_profile(profiles: BrowserProfileStore):
    return profiles.create(
        site_policy_digest=browser_site_policy_digest(
            ("https://site.example.test",)
        ),
        account_label="test account",
        browser_identity_digest=BROWSER_IDENTITY,
    )


def _interactive_open_call(call_id: str, profile) -> ToolCall:
    return ToolCall(
        call_id,
        "browser_open",
        {
            "mode": "site_bound_interactive",
            "profile_ref": profile.profile_id,
            "profile_revision": profile.revision,
            "allowed_origins": ["https://site.example.test"],
        },
    )


def _invoke_approved_open(runtime: KernelToolRuntime, call: ToolCall):
    """走 public prepare → ApprovalGrant → re-prepare → invoke 的完整路径。"""

    approval = runtime.prepare(call, _context())
    assert isinstance(approval, ApprovalRequired)
    prepared = runtime.prepare(
        call,
        _context(),
        approval=ApprovalGrant(
            request_id=approval.request.request_id,
            binding_digest=approval.request.binding_digest,
            approval_basis_revision=7,
        ),
    )
    assert isinstance(prepared, ExecutionIntent)
    return runtime.invoke(prepared)


def _open_authority_runtime(tmp_path, environment, *, profiles=None, clock=None):
    profiles = profiles or _profile_store(tmp_path)
    tools = build_browser_tools(
        environment=environment,
        profile_store=profiles,
        session_store=BrowserSessionStore(root=tmp_path / "sessions"),
        browser_identity_digest=BROWSER_IDENTITY,
        clock=lambda: CLOCK,
        monotonic_clock=clock or (lambda: 1000.0),
    )
    runtime = KernelToolRuntime(tools.registrations, clock=lambda: CLOCK)
    return tools, runtime


# --------------------------------------------------------------------------- #
# 002：session 租期与 final drift（从 test_tools.py 迁入，行为不变）
# --------------------------------------------------------------------------- #


class DriftingProfileStore:
    """包装 BrowserProfileStore：在指定第 N 次 open() 读取时注入一次 drift，
    模拟 final Runtime revalidation 通过之后、callable effect 之前的并发
    owner mutation（advance_revision/revoke）。"""

    def __init__(self, store, *, drift_on_read: int, drift) -> None:
        self._store = store
        self._drift_on_read = drift_on_read
        self._drift = drift
        self._reads = 0

    def open(self, profile_id):
        self._reads += 1
        if self._reads == self._drift_on_read:
            self._drift()
        return self._store.open(profile_id)

    def acquire_writer(self, ref):
        return self._store.acquire_writer(ref)

    def release_writer(self, lease):
        self._store.release_writer(lease)


def test_interactive_open_binds_session_duration_until_execution(tmp_path):
    environment = RecordingEnvironment()
    profiles = _profile_store(tmp_path)
    profile = _interactive_profile(profiles)
    monotonic_clock = SequenceMonotonicClock(1000.0)
    _tools, runtime = _open_authority_runtime(
        tmp_path, environment, profiles=profiles, clock=monotonic_clock
    )
    open_call = _interactive_open_call("open-duration", profile)

    # 构造 registrations、首次 prepare 与带 approval 的 re-prepare 都不读
    # monotonic clock；binding 只携带固定租期，不携带绝对 deadline。
    assert monotonic_clock.reads == 0
    approval = runtime.prepare(open_call, _context())
    assert isinstance(approval, ApprovalRequired)
    assert monotonic_clock.reads == 0
    prepared = runtime.prepare(
        open_call,
        _context(),
        approval=ApprovalGrant(
            request_id=approval.request.request_id,
            binding_digest=approval.request.binding_digest,
            approval_basis_revision=7,
        ),
    )
    assert isinstance(prepared, ExecutionIntent)
    assert monotonic_clock.reads == 0
    assert prepared.safety_binding["session_duration_seconds"] == 1800
    assert "session_expiry_monotonic" not in prepared.safety_binding

    opened = runtime.invoke(prepared)
    assert opened.metadata["browser_result_kind"] == "browser_open"
    # 真正开始执行才读一次 monotonic clock：expiry = execution_now + 1800。
    assert monotonic_clock.reads == 1
    assert environment.opened[0].expiry_monotonic == 1000.0 + 1800.0


def test_sequential_interactive_opens_keep_independent_deadlines(tmp_path):
    environment = UniqueSessionRefEnvironment()
    profiles = _profile_store(tmp_path)
    profile = _interactive_profile(profiles)
    monotonic_clock = SequenceMonotonicClock(1000.0, 5000.0)
    _tools, runtime = _open_authority_runtime(
        tmp_path, environment, profiles=profiles, clock=monotonic_clock
    )

    # production-like：同一 profile 的第一条 open 获批执行后经
    # browser_close CLEANED（writer 已释放），再推进 monotonic clock，
    # 同一 profile 重新获批第二次 open。
    first_opened = _invoke_approved_open(
        runtime, _interactive_open_call("open-first", profile)
    )
    first_ref = first_opened.metadata["session_ref"]
    closed = runtime.invoke(
        runtime.prepare(
            ToolCall("close-first", "browser_close", {"session_ref": first_ref}),
            _context(),
        )
    )
    assert closed.metadata["cleanup_outcome"] == "cleaned"
    second_opened = _invoke_approved_open(
        runtime, _interactive_open_call("open-second", profile)
    )

    # 两次顺序 open 各自从真正执行时刻起算独立的 30 分钟租期；第二次
    # open 不续期或改写第一次的 immutable spec。
    assert monotonic_clock.reads == 2
    assert first_ref != second_opened.metadata["session_ref"]
    assert environment.opened[0].expiry_monotonic == 1000.0 + 1800.0
    assert environment.opened[1].expiry_monotonic == 5000.0 + 1800.0
    assert environment.opened[0].identity_digest != environment.opened[1].identity_digest


class AcquireTimeDriftStore:
    """包装 BrowserProfileStore：在 acquire_writer 内部 metadata 二次重读前
    注入一次 owner mutation，模拟 callable final 校验已通过、writer acquisition
    重读时的并发漂移窗口（此刻 store 会抛异常而不是返回漂移 ref）。"""

    def __init__(self, store, *, drift) -> None:
        self._store = store
        self._drift = drift

    def open(self, profile_id):
        return self._store.open(profile_id)

    def acquire_writer(self, ref):
        self._drift()
        return self._store.acquire_writer(ref)

    def release_writer(self, lease):
        self._store.release_writer(lease)


@pytest.mark.parametrize("drift_kind", ["revision", "revoked"])
def test_final_drift_before_open_is_known_not_executed_zero_effect(
    tmp_path, drift_kind
):
    environment = RecordingEnvironment()
    profiles = _profile_store(tmp_path)
    profile = _interactive_profile(profiles)

    def drift():
        if drift_kind == "revision":
            lease = profiles.acquire_writer(profile)
            profiles.advance_revision(lease, expected_revision=profile.revision)
            profiles.release_writer(lease)
        else:
            profiles.revoke(profile)

    # 读取序：首次 prepare(1) → re-prepare(2) → invoke 内 revalidation(3) →
    # callable 内 final 校验(4)；在第 4 次读取时漂移即命中计划要求的风险窗口。
    drifting = DriftingProfileStore(profiles, drift_on_read=4, drift=drift)
    _tools, runtime = _open_authority_runtime(tmp_path, environment, profiles=drifting)

    result = _invoke_approved_open(
        runtime, _interactive_open_call("open-drift", profile)
    )

    # 漂移在 effect 前被 final exact 校验拦截：closed KnownNotExecuted、
    # BrowserEnvironment.open 调用次数为零、writer 不泄漏。
    assert isinstance(result, ToolResult)
    assert result.executed is False
    assert result.metadata["code"] == "browser_open_binding_changed"
    assert environment.opened == []
    lock_path = tmp_path / "profiles" / profile.profile_id / "writer.lock"
    assert not lock_path.exists()
    if drift_kind == "revision":
        current = profiles.open(profile.profile_id)
        writer = profiles.acquire_writer(current)
        profiles.release_writer(writer)


@pytest.mark.parametrize("drift_kind", ["revision", "revoked"])
def test_writer_reacquire_drift_before_open_is_known_not_executed_zero_effect(
    tmp_path, drift_kind
):
    environment = RecordingEnvironment()
    profiles = _profile_store(tmp_path)
    profile = _interactive_profile(profiles)

    def drift():
        if drift_kind == "revision":
            lease = profiles.acquire_writer(profile)
            profiles.advance_revision(lease, expected_revision=profile.revision)
            profiles.release_writer(lease)
        else:
            profiles.revoke(profile)

    # callable final 校验读取正常通过；漂移注入在 acquire_writer 的二次
    # metadata 重读前：revision 漂移显现为 ProfileRevisionConflict，revoke
    # 显现为 _verify_reference 的 ProfileIntegrityError（status 不一致）。
    drifting = AcquireTimeDriftStore(profiles, drift=drift)
    _tools, runtime = _open_authority_runtime(tmp_path, environment, profiles=drifting)

    result = _invoke_approved_open(
        runtime, _interactive_open_call("open-reacquire-drift", profile)
    )

    # 漂移发生在 BrowserEnvironment.open 之前：closed KnownNotExecuted、
    # adapter 零调用、writer 无泄漏（不进入 unknown-outcome）。
    assert isinstance(result, ToolResult)
    assert result.executed is False
    assert result.metadata["code"] == "browser_open_binding_changed"
    assert environment.opened == []
    lock_path = tmp_path / "profiles" / profile.profile_id / "writer.lock"
    assert not lock_path.exists()
    if drift_kind == "revision":
        current = profiles.open(profile.profile_id)
        writer = profiles.acquire_writer(current)
        profiles.release_writer(writer)


def test_second_open_of_active_profile_returns_unavailable(tmp_path):
    environment = RecordingEnvironment()
    profiles = _profile_store(tmp_path)
    profile = _interactive_profile(profiles)
    _tools, runtime = _open_authority_runtime(tmp_path, environment, profiles=profiles)

    first = _invoke_approved_open(
        runtime, _interactive_open_call("open-first", profile)
    )
    second = _invoke_approved_open(
        runtime, _interactive_open_call("open-second", profile)
    )

    # 同一 active profile 的第二次 open：final 校验通过，但 writer 仍由本进程
    # 的第一条 session 持有；adapter 前返回 closed browser_open_unavailable，
    # 不进入 unknown-outcome，第一条 session 的 writer 不被释放或偷取。
    assert isinstance(second, ToolResult)
    assert second.executed is False
    assert second.metadata["code"] == "browser_open_unavailable"
    assert len(environment.opened) == 1
    with pytest.raises(ProfileLockHeldError):
        profiles.acquire_writer(profile)
    closed = runtime.invoke(
        runtime.prepare(
            ToolCall(
                "close-first",
                "browser_close",
                {"session_ref": first.metadata["session_ref"]},
            ),
            _context(),
        )
    )
    assert closed.metadata["cleanup_outcome"] == "cleaned"


def test_interactive_open_prepare_rejects_revoked_profile(tmp_path):
    environment = RecordingEnvironment()
    profiles = _profile_store(tmp_path)
    profile = _interactive_profile(profiles)
    profiles.revoke(profile)
    _tools, runtime = _open_authority_runtime(tmp_path, environment, profiles=profiles)

    rejected = runtime.prepare(
        _interactive_open_call("open-revoked", profile), _context()
    )

    # revoked profile 不是可授权的 open 输入：prepare 阶段 fail closed，
    # 不形成审批请求，也没有任何 browser effect。
    assert isinstance(rejected, ToolResult)
    assert rejected.is_error is True
    assert rejected.metadata["code"] == "binding_failure"
    assert environment.opened == []


# --------------------------------------------------------------------------- #
# 003：writer acquisition 与 mutation 的线性化
# --------------------------------------------------------------------------- #


class MutationAtClockSeam:
    """第一次 monotonic 读数时（acquisition 已返回、adapter 尚未调用）执行
    一次注入 mutation；这是 open callable 的 execution clock seam。"""

    def __init__(self, mutation) -> None:
        self._mutation = mutation
        self.reads = 0

    def __call__(self) -> float:
        self.reads += 1
        if self.reads == 1:
            self._mutation()
        return 1000.0


@pytest.mark.parametrize("verb", ["revoke", "clear"])
def test_writer_acquisition_wins_against_mutation_at_clock_seam(tmp_path, verb):
    environment = RecordingEnvironment()
    profiles = _profile_store(tmp_path)
    profile = _interactive_profile(profiles)
    independent = _profile_store(tmp_path)

    def mutation():
        if verb == "revoke":
            with pytest.raises(ProfileLockHeldError):
                independent.revoke(profile)
        else:
            with pytest.raises(ProfileLockHeldError):
                independent.clear(profile)

    clock = MutationAtClockSeam(mutation)
    _tools, runtime = _open_authority_runtime(
        tmp_path, environment, profiles=profiles, clock=clock
    )

    opened = _invoke_approved_open(
        runtime, _interactive_open_call("open-writer-wins", profile)
    )

    # acquisition 先成功：mutation 在 clock seam 明确 busy、状态不变；
    # adapter 恰好按 acquisition snapshot open 一次。
    assert clock.reads == 1
    assert opened.metadata["browser_result_kind"] == "browser_open"
    assert len(environment.opened) == 1
    assert environment.opened[0].profile_revision == profile.revision
    assert profiles.open(profile.profile_id) == profile

    closed = runtime.invoke(
        runtime.prepare(
            ToolCall(
                "close-writer-wins",
                "browser_close",
                {"session_ref": opened.metadata["session_ref"]},
            ),
            _context(),
        )
    )
    assert closed.metadata["cleanup_outcome"] == "cleaned"
    if verb == "revoke":
        revoked = independent.revoke(profile)
        assert revoked.status is ProfileStatus.REVOKED
    else:
        assert independent.clear(profile) is BrowserCleanupOutcome.CLEANED


class GuardParkedStore:
    """armed 后的 acquire_writer 在进入 store guard 前停靠（Event 同步），
    模拟“final tool check 已通过、acquisition 线性化尚未发生”的窗口。"""

    def __init__(self, store) -> None:
        self._store = store
        self.armed = False
        self.parked = threading.Event()
        self.resume = threading.Event()

    def open(self, profile_id):
        return self._store.open(profile_id)

    def acquire_writer(self, ref):
        if self.armed:
            self.parked.set()
            assert self.resume.wait(timeout=15)
        return self._store.acquire_writer(ref)

    def advance_revision(self, lease, *, expected_revision):
        return self._store.advance_revision(lease, expected_revision=expected_revision)

    def release_writer(self, lease):
        return self._store.release_writer(lease)


def test_parked_acquisition_rereads_new_revision_after_exact_takeover(tmp_path):
    environment = RecordingEnvironment()
    profiles = _profile_store(tmp_path)
    profile = _interactive_profile(profiles)
    parked = GuardParkedStore(profiles)
    tools, runtime = _open_authority_runtime(
        tmp_path, environment, profiles=parked
    )

    # 第一条 session 正常获批打开，持有 writer lease。
    opened = _invoke_approved_open(
        runtime, _interactive_open_call("open-first", profile)
    )
    session_ref = opened.metadata["session_ref"]

    # 第二条 open 的 intent 先以 R1 获批（停靠只影响 execution 阶段）。
    stale_call = _interactive_open_call("open-stale", profile)
    approval = runtime.prepare(stale_call, _context())
    assert isinstance(approval, ApprovalRequired)
    prepared = runtime.prepare(
        stale_call,
        _context(),
        approval=ApprovalGrant(
            request_id=approval.request.request_id,
            binding_digest=approval.request.binding_digest,
            approval_basis_revision=7,
        ),
    )
    assert isinstance(prepared, ExecutionIntent)

    # governed takeover：begin（headed）→ durable request。
    takeover_intent = runtime.prepare(
        ToolCall(
            "takeover-1", "browser_begin_takeover", {"session_ref": session_ref}
        ),
        _context(),
    )
    runtime.invoke(takeover_intent)
    request = takeover_intent.browser_takeover_request
    assert request is not None

    parked.armed = True
    outcome: dict = {}
    thread = threading.Thread(
        target=lambda: outcome.setdefault("result", runtime.invoke(prepared))
    )
    thread.start()
    assert parked.parked.wait(timeout=15)

    # 原 lease holder 完成 exact takeover R1→R2 并 CLEANED release。
    assert tools.complete_takeover(request) == profile.revision + 1
    closed = runtime.invoke(
        runtime.prepare(
            ToolCall(
                "close-first", "browser_close", {"session_ref": session_ref}
            ),
            _context(),
        )
    )
    assert closed.metadata["cleanup_outcome"] == "cleaned"

    parked.resume.set()
    thread.join(timeout=15)
    result = outcome["result"]

    # A 恢复后必须重读 R2 并拒绝旧 R1：binding changed、adapter 零新调用
    #（opened 仅含第一条 session 的那一次 entry）。
    assert isinstance(result, ToolResult)
    assert result.executed is False
    assert result.metadata["code"] == "browser_open_binding_changed"
    assert len(environment.opened) == 1
    assert profiles.open(profile.profile_id).revision == profile.revision + 1
