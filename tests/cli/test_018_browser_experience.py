"""018 Task 8 slice 3：CLI readiness/UX 与 user-only browser controls（先 Red）。

startup 恰好一条 browser readiness 状态行 + 一条 next action；takeover
pending 的 restart 文本准确（/browser-done、/cancel，不出现 resuming）；
profile list/revoke/clear 与 takeover complete/cancel 是 user-only typed
命令，不在模型工具面；错误无 traceback/internal path/cookie/account 原文。
"""

import pytest

from agent.browser.profile_store import BrowserProfileStore
from agent.browser.takeover import complete_browser_takeover_profile
from agent.composition import BrowserReadiness, BrowserResources
from agent.continuity.restart import RestartProjection
from main import (
    _browser_status_lines,
    _startup_task_messages,
    browser_profile_user_command,
)
from tests.browser.profile_probe import DeterministicProcessIdentityProbe


def _profile_store(tmp_path) -> BrowserProfileStore:
    return BrowserProfileStore(
        root=tmp_path / "profiles",
        process_probe=DeterministicProcessIdentityProbe(),
    )


def _resources(readiness, reason=None):
    return BrowserResources(
        registrations=(),
        closeables=(),
        readiness=readiness,
        reason_code=reason,
    )


def test_disabled_browser_has_no_status_line():
    assert _browser_status_lines(_resources(BrowserReadiness.NOT_ENABLED)) == []


@pytest.mark.parametrize(
    ("reason", "next_action"),
    [
        ("browser_package_missing", "pip install"),
        ("browser_profile_permissions", "owner-only"),
        ("browser_binary_missing", "Playwright Chromium"),
        ("browser_egress_unavailable", "DNS/egress"),
    ],
)
def test_unavailable_browser_gives_one_reason_and_one_next_action(
    reason, next_action,
):
    lines = _browser_status_lines(
        _resources(BrowserReadiness.TEMPORARILY_UNAVAILABLE, reason)
    )
    assert len(lines) == 1
    assert "Browser: unavailable" in lines[0]
    assert next_action in lines[0]
    for forbidden in ("Traceback", "/Users/", "cookie", "account"):
        assert forbidden not in lines[0]


def test_ready_browser_gives_single_readiness_line():
    lines = _browser_status_lines(_resources(BrowserReadiness.READY))
    assert lines == [
        "Browser: public-read ready; interactive profiles available"
    ]


def test_startup_takeover_pending_projects_restart_recovery_not_resuming():
    from agent.continuity.sessions import StartupDisposition
    from agent.runtime.contracts import ActiveRunStatus, GoalStatus

    projection = RestartProjection(
        disposition=StartupDisposition.RESUMED,
        conversation_id="conversation-1",
        goal_id="goal-1",
        goal_revision=1,
        goal_status=GoalStatus.GOAL_READY,
        active_run_status=ActiveRunStatus.RUNNABLE,
        user_outcome="finish the task",
        progress_summary=None,
        next_step=None,
        required_action=None,
        sandbox_recovery=None,
        browser_takeover_pending=True,
    )
    banner, status = _startup_task_messages(projection)
    assert "needs human" in status.lower()
    assert "/browser-cancel" in banner
    assert "/browser-done" not in banner
    assert "resuming" not in banner.lower()
    assert "resuming" not in status.lower()


def test_profile_commands_are_user_only_not_model_tools():
    from agent.browser.tools import BROWSER_TOOL_NAMES

    for reserved in (
        "browser_profile_create",
        "browser_profile_list",
        "browser_profile_revoke",
        "browser_profile_clear",
    ):
        assert reserved not in BROWSER_TOOL_NAMES


def test_profile_list_revoke_clear_round_trip(tmp_path):
    store = _profile_store(tmp_path)
    ref = store.create(
        site_policy_digest="a" * 64,
        account_label="alice@example.test",
        browser_identity_digest="b" * 64,
    )
    listing = browser_profile_user_command("list", store)
    assert ref.profile_id in listing
    assert "alice" not in listing  # account 原文永不出现
    revoked = browser_profile_user_command(f"revoke {ref.profile_id}", store)
    assert "revoked" in revoked
    cleared = browser_profile_user_command(f"clear {ref.profile_id}", store)
    assert "cleared" in cleared


def test_takeover_profile_completion_is_idempotent_after_runtime_retry(tmp_path):
    from agent.runtime.contracts import BrowserTakeoverRequestV1

    store = _profile_store(tmp_path)
    ref = store.create(
        site_policy_digest="a" * 64,
        account_label="test account",
        browser_identity_digest="b" * 64,
    )
    request = BrowserTakeoverRequestV1(
        request_id="takeover-1",
        session_ref="session-0123456789abcdef",
        profile_ref=ref.profile_id,
        profile_revision=ref.revision,
        browser_identity_digest="b" * 64,
        goal_id="goal-1",
        goal_revision=1,
        requested_at="2026-08-28T10:00:00+00:00",
    )

    first = complete_browser_takeover_profile(
        request,
        store,
        browser_identity_digest="b" * 64,
        session_is_active=lambda session_ref: session_ref == request.session_ref,
    )
    second = complete_browser_takeover_profile(
        request,
        store,
        browser_identity_digest="b" * 64,
        session_is_active=lambda session_ref: session_ref == request.session_ref,
    )

    assert first == ref.revision + 1
    assert second == first


def test_profile_create_is_user_only_and_returns_only_opaque_identity(tmp_path):
    store = _profile_store(tmp_path)
    output = browser_profile_user_command(
        "create https://site.example.test alice@example.test",
        store,
        browser_identity_digest="b" * 64,
    )

    profile_id = output.split()[2]
    assert profile_id.startswith("profile-")
    assert "alice" not in output
    assert "site.example.test" not in output
    ref = store.open(profile_id)
    assert ref.browser_identity_digest == "b" * 64
    assert ref.account_label_digest != "alice@example.test"


def test_profile_create_rejects_noncanonical_or_non_https_origin(tmp_path):
    store = _profile_store(tmp_path)
    for command in (
        "create http://site.example.test account",
        "create https://SITE.example.test account",
        "create https://site.example.test/path account",
    ):
        with pytest.raises(ValueError, match="canonical HTTPS origin"):
            browser_profile_user_command(
                command,
                store,
                browser_identity_digest="b" * 64,
            )


def test_profile_command_rejects_unknown(tmp_path):
    store = _profile_store(tmp_path)
    with pytest.raises(ValueError):
        browser_profile_user_command("explode", store)


def test_takeover_completion_advances_the_exact_persistent_profile(tmp_path):
    from agent.runtime.contracts import BrowserTakeoverRequestV1

    browser_identity = "b" * 64
    store = _profile_store(tmp_path)
    profile = store.create(
        site_policy_digest="a" * 64,
        account_label="private account label",
        browser_identity_digest=browser_identity,
    )
    request = BrowserTakeoverRequestV1(
        request_id="takeover-1",
        session_ref="session-0123456789abcdef",
        profile_ref=profile.profile_id,
        profile_revision=profile.revision,
        browser_identity_digest=browser_identity,
        goal_id="goal-1",
        goal_revision=1,
        requested_at="2026-08-28T10:00:00+00:00",
    )

    assert complete_browser_takeover_profile(
        request,
        store,
        browser_identity_digest=browser_identity,
        session_is_active=lambda session_ref: session_ref == request.session_ref,
    ) == 2
    assert store.open(profile.profile_id).revision == 2


def test_takeover_completion_rejects_changed_browser_identity_without_mutation(
    tmp_path,
):
    from agent.runtime.contracts import BrowserTakeoverRequestV1

    store = _profile_store(tmp_path)
    profile = store.create(
        site_policy_digest="a" * 64,
        account_label="private account label",
        browser_identity_digest="b" * 64,
    )
    request = BrowserTakeoverRequestV1(
        request_id="takeover-1",
        session_ref="session-0123456789abcdef",
        profile_ref=profile.profile_id,
        profile_revision=profile.revision,
        browser_identity_digest="b" * 64,
        goal_id="goal-1",
        goal_revision=1,
        requested_at="2026-08-28T10:00:00+00:00",
    )

    with pytest.raises(ValueError, match="browser identity changed"):
        complete_browser_takeover_profile(
            request,
            store,
            browser_identity_digest="c" * 64,
            session_is_active=lambda _session_ref: True,
        )
    assert store.open(profile.profile_id).revision == 1


def test_error_output_has_no_internal_details(tmp_path):
    store = _profile_store(tmp_path)
    try:
        browser_profile_user_command("revoke profile-nonexistent00", store)
    except Exception as error:  # noqa: BLE001
        message = str(error)
        assert "Traceback" not in message
        assert str(tmp_path) not in message


def test_composition_integrates_browser_in_existing_root_only():
    # 静态断言：不存在 BrowserRuntime/第二 loop；browser 只经
    # build_browser_resources 进入唯一 composition root。
    import inspect

    import agent.composition as composition
    import main as main_module

    source = inspect.getsource(composition)
    assert "class BrowserRuntime" not in source
    # 唯一 AgentRuntime 构造点仍是既有 build_runtime（不因 browser 增加）。
    assert source.count("AgentRuntime(") == 1
    main_source = inspect.getsource(main_module)
    assert main_source.count("build_browser_resources(") == 1
    assert "BrowserRuntime" not in main_source


# --------------------------------------------------------------------------- #
# Task 8 二轮审计：/cancel takeover 映射、approval preview、profile list
# 公开接口
# --------------------------------------------------------------------------- #


def test_browser_act_approval_preview_is_exact_and_bounded(tmp_path):
    # 真实 governed browser_act 审批 UX：site-bound open（approve+invoke）→
    # observe → DISCLOSE fill_form 经实际 BrowserActionPolicy/
    # KernelToolRuntime.prepare 得到 ApprovalRequired.request.preview；
    # 只投影该真实 approval 数据为 APPROVAL_REQUESTED 事件交
    # TerminalRenderer 渲染。无平行 preview/event 构造。
    from agent.browser.session_store import BrowserSessionStore
    from agent.browser.tools import build_browser_tool_registrations
    from agent.browser.url_policy import browser_site_policy_digest
    from agent.cli.render import TerminalRenderer
    from agent.runtime.contracts import (
        ApprovalGrant,
        ApprovalRequired,
        RuntimeEvent,
        RuntimeEventKind,
        ToolCall,
    )
    from agent.runtime.tools import KernelToolRuntime
    from tests.browser.test_tools import RecordingEnvironment, _context

    environment = RecordingEnvironment()
    profiles = _profile_store(tmp_path)
    profile = profiles.create(
        site_policy_digest=browser_site_policy_digest(
            ("https://site.example.test",)
        ),
        account_label="test account",
        browser_identity_digest="b" * 64,
    )
    registrations = build_browser_tool_registrations(
        environment=environment,
        profile_store=profiles,
        session_store=BrowserSessionStore(root=tmp_path / "sessions"),
        browser_identity_digest="b" * 64,
        clock=lambda: "2026-08-28T10:00:00+00:00",
        monotonic_clock=lambda: 1000.0,
    )
    runtime = KernelToolRuntime(
        registrations, clock=lambda: "2026-08-28T10:00:00+00:00"
    )
    open_call = ToolCall(
        "open-1",
        "browser_open",
        {
            "mode": "site_bound_interactive",
            "profile_ref": profile.profile_id,
            "profile_revision": profile.revision,
            "allowed_origins": ["https://site.example.test"],
        },
    )
    open_approval = runtime.prepare(open_call, _context())
    assert isinstance(open_approval, ApprovalRequired)
    opened = runtime.invoke(
        runtime.prepare(
            open_call,
            _context(),
            approval=ApprovalGrant(
                request_id=open_approval.request.request_id,
                binding_digest=open_approval.request.binding_digest,
                approval_basis_revision=7,
            ),
        )
    )
    session_ref = opened.metadata["session_ref"]
    observed = runtime.invoke(
        runtime.prepare(
            ToolCall("observe-1", "browser_observe", {"session_ref": session_ref}),
            _context(),
        )
    )
    secret_value = "user-supplied-secret@example.test"
    act_call = ToolCall(
        "act-1",
        "browser_act",
        {
            "session_ref": session_ref,
            "kind": "fill_form",
            "observation_digest": observed.metadata["observation_digest"],
            "page_id": session_ref,
            "frame_id": "main",
            "target_ref": "form-1",
            "params": {"fields": {"Email": secret_value}},
        },
    )
    approval = runtime.prepare(act_call, _context())
    assert isinstance(approval, ApprovalRequired)
    # 真实 BrowserActionPolicy 产物：consequence/origin/kind/字段 digest。
    candidate = approval.request.browser_action_candidate
    assert candidate is not None
    assert candidate.consequence == "disclose"
    assert candidate.mode == "site_bound_interactive"
    assert candidate.allowed_origins == ("https://site.example.test",)
    # 真实 approval 数据 → 真实 Runtime event 形状 → TerminalRenderer。
    rendered_lines: list[str] = []
    renderer = TerminalRenderer(write_fn=rendered_lines.append)
    renderer.emit(
        RuntimeEvent(
            event_id="event-approval-act-1",
            kind=RuntimeEventKind.APPROVAL_REQUESTED,
            conversation_id="conversation-1",
            run_id="run-1",
            revision=1,
            causation_id="act-1",
            payload={
                "tool_name": "browser_act",
                "risk": "high",
                "side_effect": "external",
                "preview": approval.request.preview,
            },
        )
    )
    text = "\n".join(rendered_lines)
    preview = approval.request.preview
    assert len(preview) <= 512
    # exact/bounded 用户可见信息：action kind、origin、consequence、
    # 字段名与 value digest。
    assert "browser_act" in text
    assert "fill_form" in preview
    assert "https://site.example.test" in preview
    assert "disclose" in preview
    assert "Email" in preview
    # 真实 field value digest（BrowserActionPolicy 的 SHA-256 前 16 位）：
    # preview 与 TerminalRenderer 输出都必须出现。
    value_digest = "sha256:5ff18289182f7372"
    assert value_digest in preview
    assert value_digest in text
    # denylist：原值/secret/path/cookie/account 绝不出现。
    for forbidden in (
        secret_value,
        "password",
        "cookie",
        "/Users/",
        "account",
        str(tmp_path),
    ):
        assert forbidden not in preview, forbidden
        assert forbidden not in text, forbidden


def test_profile_list_uses_public_store_interface(tmp_path):
    store = _profile_store(tmp_path)
    store.create(
        site_policy_digest="a" * 64,
        account_label="alice@example.test",
        browser_identity_digest="b" * 64,
    )
    listing = browser_profile_user_command("list", store)
    assert "profile-" in listing
    import inspect

    import main as main_module

    source = inspect.getsource(main_module.browser_profile_user_command)
    assert "_root" not in source  # 不依赖私有属性
