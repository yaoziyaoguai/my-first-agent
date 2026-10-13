"""F2（2026-10-02 bounded-reliability）：正常 shutdown 后重启能补记资源关闭。

冻结的最小承诺：正常 shutdown 获得底层 CLEANED 且最小可信闭合记录（session
ledger CLOSED phase）持久化后，重启能用旧 opaque ref 经正常 browser_close 工具
结果路径补记 cleaned fact。新进程不得重新 open 浏览器伪装关闭；无凭据
（cleanup UNKNOWN / 损坏 ledger / 过期 browser identity / 未知 session）一律
fail closed，不签 cleaned。
"""

from __future__ import annotations

import json

import pytest

from agent.browser.session_store import BrowserSessionStore, SessionPhase
from agent.browser.tools import build_browser_tools
from agent.runtime.contracts import (
    ApprovalGrant,
    ConversationFact,
    EvidenceOracleKind,
    FactKind,
    ToolCall,
    ToolResult,
)
from agent.runtime.resource_lifecycle import active_task_resources
from agent.runtime.tools import KernelToolRuntime
from tests.browser.profile_probe import DeterministicProcessIdentityProbe
from tests.browser.test_tools import (
    CleanupUnknownEnvironment,
    RecordingEnvironment,
    _context,
)

IDENTITY = "b" * 64


def _profile_store(tmp_path):
    from agent.browser.profile_store import BrowserProfileStore

    return BrowserProfileStore(
        root=tmp_path / "profiles",
        process_probe=DeterministicProcessIdentityProbe(),
    )


def _make_bundle(tmp_path, environment, sessions_root, *, identity: str = IDENTITY):
    return build_browser_tools(
        environment=environment,
        profile_store=_profile_store(tmp_path),
        session_store=BrowserSessionStore(root=sessions_root),
        browser_identity_digest=identity,
        clock=lambda: "2026-08-28T10:00:00+00:00",
        monotonic_clock=lambda: 1000.0,
    )


def _runtime(tmp_path, environment, sessions_root, *, identity: str = IDENTITY):
    bundle = _make_bundle(tmp_path, environment, sessions_root, identity=identity)
    runtime = KernelToolRuntime(
        bundle.registrations, clock=lambda: "2026-08-28T10:00:00+00:00"
    )
    return runtime, bundle


def _open_public_session(runtime) -> ToolResult:
    open_call = ToolCall("open-1", "browser_open", {"mode": "public_read_ephemeral"})
    approval = runtime.prepare(open_call, _context())
    opened = runtime.invoke(
        runtime.prepare(
            open_call,
            _context(),
            approval=ApprovalGrant(
                request_id=approval.request.request_id,
                binding_digest=approval.request.binding_digest,
                approval_basis_revision=7,
            ),
        )
    )
    assert isinstance(opened, ToolResult) and opened.is_error is False
    return opened


def _fact_from_result(result: ToolResult, fact_id: str) -> ConversationFact:
    return ConversationFact(
        fact_id=fact_id,
        kind=FactKind.TOOL_RESULT,
        content={
            "tool_call_id": "call",
            "text": "browser tool result",
            "is_error": result.is_error,
            "executed": True,
            "metadata": dict(result.metadata),
        },
    )


def test_f2_normal_shutdown_then_new_owner_outcloses_old_ref(tmp_path) -> None:
    """A05（单元级）：CLEANED shutdown 落凭据 → 新 owner 用旧 ref 补记 cleaned。"""

    environment = RecordingEnvironment()
    sessions_root = tmp_path / "sessions"
    _runtime1, bundle1 = _runtime(tmp_path, environment, sessions_root)
    opened = _open_public_session(_runtime1)
    session_ref = opened.metadata["session_ref"]

    bundle1.owner_shutdown()
    # 正常 shutdown：environment 真实收到 close，且凭据落盘（ledger CLOSED）。
    assert len(environment.closed) == 1
    record = BrowserSessionStore(root=sessions_root).load(session_ref)
    assert record.phase is SessionPhase.CLOSED

    # 全新 owner（同持久 sessions root，空 _active）：用旧 ref 补记。
    environment2 = RecordingEnvironment()
    runtime2, _bundle2 = _runtime(tmp_path, environment2, sessions_root)
    closed = runtime2.invoke(
        runtime2.prepare(
            ToolCall("close-2", "browser_close", {"session_ref": session_ref}),
            _context(),
        )
    )
    assert isinstance(closed, ToolResult)
    assert closed.is_error is False
    assert closed.metadata["cleanup_outcome"] == "cleaned"
    assert closed.metadata["session_recovery"] == "none"
    assert closed.metadata["closure_basis"] == "durable_ledger_closed"
    # 未重新 open、未再物理 close：幂等补记。
    assert environment2.opened == [] and environment2.closed == []

    # 资源门槛解除：open fact + 补记的 cleaned close fact → 无 active 资源。
    open_fact = _fact_from_result(opened, "fact:open:1")
    close_fact = _fact_from_result(closed, "fact:close:1")
    view = active_task_resources((open_fact, close_fact))
    assert view.browser_sessions == frozenset()
    view.require_closed()  # 不再抛出

    # 其他 mandatory evidence 仍受校验：资源闭合≠完成（缺 readback 的 derive 必败）。
    from agent.runtime.evidence import ClosedEvidenceRegistry

    registry = ClosedEvidenceRegistry()
    with pytest.raises(Exception, match="no exact read-back fact"):
        registry._filesystem_digest(
            (_fact_from_result(closed, "fact:close:dup"),),
            goal_id="goal-f2",
            goal_revision=1,
            criterion=_filesystem_criterion(),
            evidence_id="evidence-f2",
            observed_at="2026-10-02T00:00:00+00:00",
        )


def _filesystem_criterion():
    from agent.runtime.contracts import AdmittedCriterion

    return AdmittedCriterion(
        criterion_id="criterion:artifact",
        description="artifact readback",
        source_fact_id="fact-user",
        oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
        predicate={"path": "reports/final.md", "sha256": "e" * 64},
        required_evidence_class="workspace_file",
        admission_digest="f" * 64,
        mandatory=True,
    )


def _outclose(runtime, session_ref: str, call_id: str) -> ToolResult:
    """经治理路径补记 close；prepare 级 fail-closed（binding_failure）也算未签 cleaned。"""

    prepared = runtime.prepare(
        ToolCall(call_id, "browser_close", {"session_ref": session_ref}),
        _context(),
    )
    if isinstance(prepared, ToolResult):
        return prepared
    closed = runtime.invoke(prepared)
    assert isinstance(closed, ToolResult)
    return closed


def test_f2_unknown_shutdown_leaves_no_credential_and_outclose_fails_closed(
    tmp_path,
) -> None:
    """A06：shutdown cleanup UNKNOWN → 无闭合凭据 → 新 owner 补记 fail closed。"""

    environment = CleanupUnknownEnvironment()
    sessions_root = tmp_path / "sessions"
    runtime1, bundle1 = _runtime(tmp_path, environment, sessions_root)
    opened = _open_public_session(runtime1)
    session_ref = opened.metadata["session_ref"]

    with pytest.raises(Exception, match="failed closed"):
        bundle1.owner_shutdown()

    environment2 = RecordingEnvironment()
    runtime2, _bundle2 = _runtime(tmp_path, environment2, sessions_root)
    closed = _outclose(runtime2, session_ref, "close-u2")
    assert closed.is_error is True
    assert closed.metadata.get("cleanup_outcome") != "cleaned"
    assert environment2.closed == []


def test_f2_corrupted_ledger_and_wrong_identity_and_unknown_session_fail_closed(
    tmp_path,
) -> None:
    """A06：损坏 ledger / 过期 identity / 未知 session 都不能补记 cleaned。"""

    environment = RecordingEnvironment()
    sessions_root = tmp_path / "sessions"
    runtime1, bundle1 = _runtime(tmp_path, environment, sessions_root)
    opened = _open_public_session(runtime1)
    session_ref = opened.metadata["session_ref"]
    bundle1.owner_shutdown()

    # (a) 损坏 ledger：非 JSON → fail closed，不签 cleaned。
    record = BrowserSessionStore(root=sessions_root).load(session_ref)
    import dataclasses

    drifted = dataclasses.replace(record, browser_identity_digest="c" * 64)
    from agent.browser.session_store import LEDGER_NAME

    drifted_payload = json.dumps(
        {
            "session_id": drifted.session_id,
            "spec_digest": drifted.spec_digest,
            "profile_ref": drifted.profile_ref,
            "profile_revision": drifted.profile_revision,
            "browser_identity_digest": drifted.browser_identity_digest,
            "phase": "closed",
            "observation_digest": None,
            "last_action_digest": None,
            "last_action_outcome": None,
            "action_count": 0,
        },
        sort_keys=True,
    )
    ledger_path = sessions_root / session_ref / LEDGER_NAME
    ledger_path.write_text("not json at all", encoding="utf-8")
    environment2 = RecordingEnvironment()
    runtime2, _ = _runtime(tmp_path, environment2, sessions_root)
    corrupted = _outclose(runtime2, session_ref, "close-c2")
    assert corrupted.is_error is True
    assert corrupted.metadata.get("cleanup_outcome") != "cleaned"
    assert environment2.closed == []

    # (b) 过期 identity：ledger 有效但 browser_identity 不匹配当前 owner。
    ledger_path.write_text(drifted_payload, encoding="utf-8")
    environment3 = RecordingEnvironment()
    runtime3, _ = _runtime(tmp_path, environment3, sessions_root)
    wrong_identity = _outclose(runtime3, session_ref, "close-c3")
    assert wrong_identity.is_error is True
    assert wrong_identity.metadata.get("cleanup_outcome") != "cleaned"

    # (c) 未知 session：直接 fail closed。
    unknown = _outclose(runtime3, "session-ffffffffffffffff", "close-c4")
    assert unknown.is_error is True
    assert unknown.metadata.get("cleanup_outcome") != "cleaned"

    # (d) 不同 state root（不同 workspace/state）→ 不可见 → fail closed。
    environment4 = RecordingEnvironment()
    runtime4, _ = _runtime(
        tmp_path, environment4, tmp_path / "other-sessions"
    )
    other_root = _outclose(runtime4, session_ref, "close-c5")
    assert other_root.is_error is True
    assert other_root.metadata.get("cleanup_outcome") != "cleaned"
    assert environment4.closed == []


def test_f2_repeated_outclose_is_idempotent_and_writer_released(tmp_path) -> None:
    """A07：重复 close 幂等（无 reopen/二次物理 close）；site writer 正确释放。"""

    from agent.browser.profile_store import BrowserProfileStore
    from agent.browser.url_policy import browser_site_policy_digest

    environment = RecordingEnvironment()
    sessions_root = tmp_path / "sessions"
    profiles = BrowserProfileStore(
        root=tmp_path / "profiles",
        process_probe=DeterministicProcessIdentityProbe(),
    )
    profile = profiles.create(
        site_policy_digest=browser_site_policy_digest(("https://site.example.test",)),
        account_label="test account",
        browser_identity_digest=IDENTITY,
    )
    bundle1 = build_browser_tools(
        environment=environment,
        profile_store=profiles,
        session_store=BrowserSessionStore(root=sessions_root),
        browser_identity_digest=IDENTITY,
        clock=lambda: "2026-08-28T10:00:00+00:00",
        monotonic_clock=lambda: 1000.0,
    )
    runtime1 = KernelToolRuntime(
        bundle1.registrations, clock=lambda: "2026-08-28T10:00:00+00:00"
    )
    open_call = ToolCall(
        "open-s1",
        "browser_open",
        {
            "mode": "site_bound_interactive",
            "profile_ref": profile.profile_id,
            "profile_revision": profile.revision,
            "allowed_origins": ["https://site.example.test"],
        },
    )
    approval = runtime1.prepare(open_call, _context())
    opened = runtime1.invoke(
        runtime1.prepare(
            open_call,
            _context(),
            approval=ApprovalGrant(
                request_id=approval.request.request_id,
                binding_digest=approval.request.binding_digest,
                approval_basis_revision=7,
            ),
        )
    )
    session_ref = opened.metadata["session_ref"]

    # 正常 shutdown：writer lease 正确释放（新 owner 可再 acquire 同一 profile）。
    bundle1.owner_shutdown()
    fresh_store = BrowserProfileStore(
        root=tmp_path / "profiles",
        process_probe=DeterministicProcessIdentityProbe(),
    )
    fresh_store.acquire_writer(fresh_store.open(profile.profile_id))  # 不应抛 LockHeld

    # 新 owner 重复补记两次（不同 call id）：都 cleaned、无 reopen、无二次物理 close。
    environment2 = RecordingEnvironment()
    runtime2, _ = _runtime(tmp_path, environment2, sessions_root)
    for index in range(2):
        closed = _outclose(runtime2, session_ref, f"close-r{index}")
        assert closed.is_error is False
        assert closed.metadata["cleanup_outcome"] == "cleaned"
    assert environment2.opened == [] and environment2.closed == []


def test_f2_composition_shutdown_then_new_owner_outcloses_old_ref(
    tmp_path, monkeypatch
) -> None:
    """A05（composition 级）：open→正常 shutdown→全新 composition→原 ref close。"""

    import agent.composition as composition_module
    from agent.composition import build_browser_resources
    from tests.browser.fakes import FakeResolver, Journal, make_fake_factory

    def build(factory):
        monkeypatch.setattr(
            composition_module,
            "_browser_binary_available_for_factory",
            lambda: True,
        )
        return build_browser_resources(
            tmp_path / "workspace",
            tmp_path / "state",
            enabled=True,
            playwright_factory=factory,
            resolver=FakeResolver({"site.example.test": ("93.184.216.34",)}),
        )

    journal = Journal()
    _handle, factory = make_fake_factory(journal)
    resources = build(factory)
    runtime1 = KernelToolRuntime(
        resources.registrations, clock=lambda: "2026-08-28T10:00:00+00:00"
    )
    open_call = ToolCall("open-1", "browser_open", {"mode": "public_read_ephemeral"})
    approval = runtime1.prepare(open_call, _context())
    opened = runtime1.invoke(
        runtime1.prepare(
            open_call,
            _context(),
            approval=ApprovalGrant(
                request_id=approval.request.request_id,
                binding_digest=approval.request.binding_digest,
                approval_basis_revision=7,
            ),
        )
    )
    assert isinstance(opened, ToolResult)
    session_ref = opened.metadata["session_ref"]

    for closeable in resources.closeables:
        closeable()
    assert len(journal.calls("playwright", "stop")) == 1
    record = BrowserSessionStore(
        root=tmp_path / "state" / "browser" / "sessions"
    ).load(session_ref)
    assert record.phase is SessionPhase.CLOSED

    # 全新 composition（同 state_root）：原 opaque ref 补记关闭。
    _journal2, factory2 = make_fake_factory(Journal())
    resources2 = build(factory2)
    runtime2 = KernelToolRuntime(
        resources2.registrations, clock=lambda: "2026-08-28T10:00:00+00:00"
    )
    closed = runtime2.invoke(
        runtime2.prepare(
            ToolCall("close-2", "browser_close", {"session_ref": session_ref}),
            _context(),
        )
    )
    assert isinstance(closed, ToolResult)
    assert closed.is_error is False
    assert closed.metadata["cleanup_outcome"] == "cleaned"


def test_f2_owner_shutdown_still_fails_closed_on_worker_alive(tmp_path, monkeypatch) -> None:
    """shutdown 后 worker 仍存活 → 既有 BrowserCleanupUnknownError 语义保留。"""
    import agent.composition as composition_module
    from agent.browser.playwright_adapter import BrowserCleanupUnknownError
    from agent.composition import build_browser_resources
    from agent.runtime.contracts import ApprovalGrant, ToolCall, ToolResult
    from tests.browser.fakes import FakeResolver, Journal, make_fake_factory

    journal = Journal()
    _handle, factory = make_fake_factory(journal)
    monkeypatch.setattr(
        composition_module, "_browser_binary_available_for_factory", lambda: True
    )
    resources = build_browser_resources(
        tmp_path,
        tmp_path / "state-owned",
        enabled=True,
        playwright_factory=factory,
        resolver=FakeResolver({"site.example.test": ("93.184.216.34",)}),
    )
    runtime = KernelToolRuntime(
        resources.registrations, clock=lambda: "2026-08-28T10:00:00+00:00"
    )
    open_call = ToolCall("open-1", "browser_open", {"mode": "public_read_ephemeral"})
    approval = runtime.prepare(open_call, _context())
    opened = runtime.invoke(
        runtime.prepare(
            open_call,
            _context(),
            approval=ApprovalGrant(
                request_id=approval.request.request_id,
                binding_digest=approval.request.binding_digest,
                approval_basis_revision=7,
            ),
        )
    )
    assert isinstance(opened, ToolResult)
    # 注入 page.close 失败 → cleanup UNKNOWN → owner shutdown fail closed。
    _handle.last_page.fail_on_close = True

    with pytest.raises((BrowserCleanupUnknownError, RuntimeError)):
        for closeable in resources.closeables:
            closeable()


def test_browser_lease_accepts_product_clock_z_format() -> None:
    """回归（2026-10-05 真实 D06 暴露）：产品时钟的 "…Z" 与 isoformat 的
    "…+00:00" 两种 zoned 形式都必须被 browser 租约合同接受。"""

    from agent.runtime.contracts import BrowserAuthorityLeaseV1

    def lease_with(issued_at: str, expires_at: str) -> None:
        BrowserAuthorityLeaseV1.create(
            lease_id="browser-lease:z-format",
            candidate_digest="a" * 64,
            goal_id="goal-z",
            goal_revision=1,
            session_ref="session-0123456789abcdef",
            browser_identity_digest="b" * 64,
            profile_ref=None,
            profile_revision=None,
            allowed_origins=("https://site.example.test",),
            mode="task_loopback_ephemeral",
            page_id="page-1",
            frame_id="main",
            observation_digest="c" * 64,
            action_digest="d" * 64,
            consequence="commit",
            approved_request_identity="approval-z",
            issued_at=issued_at,
            expires_at=expires_at,
        )

    lease_with("2026-10-05T12:00:00Z", "2026-10-05T12:05:00Z")
    lease_with(
        "2026-10-05T12:00:00+00:00", "2026-10-05T12:05:00+00:00"
    )
