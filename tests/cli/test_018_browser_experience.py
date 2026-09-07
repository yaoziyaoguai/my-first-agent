"""018 Task 8 slice 3：CLI readiness/UX 与 user-only browser controls（先 Red）。

startup 恰好一条 browser readiness 状态行 + 一条 next action；takeover
pending 的 restart 文本准确（/browser-done、/cancel，不出现 resuming）；
profile list/revoke/clear 与 takeover complete/cancel 是 user-only typed
命令，不在模型工具面；错误无 traceback/internal path/cookie/account 原文。
"""

import os

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


# --------------------------------------------------------------------------- #
# 003：活跃/未知 writer 下的 revoke/clear 必须诚实拒绝（忙碌/未知，非清理未知）
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("verb", ["revoke", "clear"])
def test_profile_command_reports_busy_without_touching_active_writer(tmp_path, verb):
    from agent.browser.profile_store import ProfileLockHeldError

    store = _profile_store(tmp_path)
    ref = store.create(
        site_policy_digest="a" * 64,
        account_label="active account",
        browser_identity_digest="b" * 64,
    )
    lease = store.acquire_writer(ref)  # 模拟活跃 browser session 的 writer

    message = browser_profile_user_command(f"{verb} {ref.profile_id}", store)

    assert "is in use" in message
    assert "was not " + ("revoked" if verb == "revoke" else "cleared") in message
    # 诚实拒绝而不是清理未知：writer 仍在，profile 未被撤销。
    with pytest.raises(ProfileLockHeldError):
        store.acquire_writer(ref)
    assert store.open(ref.profile_id).status.value == "active"

    store.release_writer(lease)
    followup = browser_profile_user_command(f"{verb} {ref.profile_id}", store)
    assert ("revoked" if verb == "revoke" else "cleared") in followup


@pytest.mark.parametrize("verb", ["revoke", "clear"])
def test_profile_command_reports_unknown_writer_without_touching_anything(tmp_path, verb):
    from agent.browser.profile_store import ProcessIdentity

    class UnconfirmableForeignProbe:
        """本进程可确认；锁内 pid 的存活无法确认（非明确 dead）。"""

        def probe(self, pid: int) -> ProcessIdentity:
            if pid == os.getpid():
                return ProcessIdentity(exists=True, started_at=f"self:{pid}")
            return ProcessIdentity(exists=None, started_at=None)

    store = BrowserProfileStore(
        root=tmp_path / "profiles",
        process_probe=UnconfirmableForeignProbe(),
    )
    ref = store.create(
        site_policy_digest="a" * 64,
        account_label="legacy account",
        browser_identity_digest="b" * 64,
    )
    # 良构的四字段遗留 writer.lock（非本进程）：存在但身份无法确认，
    # 绝不能当作可清理垃圾。
    legacy_dir = tmp_path / "profiles" / ref.profile_id
    legacy_dir.joinpath("writer.lock").write_text(
        '{"pid": 4194304, "started_at": "foreign-start", '
        '"lease_id": "deadbeefdeadbeefdeadbeefdeadbeef", '
        '"acquired_revision": 1}',
        encoding="utf-8",
    )

    message = browser_profile_user_command(f"{verb} {ref.profile_id}", store)

    assert "writer state cannot be confirmed" in message
    assert "nothing was " + ("revoked" if verb == "revoke" else "cleared") in message
    # 零 secret：不泄漏 path/label/digest/nonce。
    assert str(tmp_path) not in message
    assert "deadbeef" not in message
    assert "legacy" not in message
    # 未清理：lock 与 profile 原样保留，交由人工确认。
    assert legacy_dir.joinpath("writer.lock").exists()
    assert store.open(ref.profile_id).status.value == "active"


def test_profile_command_double_revoke_reports_already_revoked_nothing_done(
    tmp_path,
):
    store = _profile_store(tmp_path)
    ref = store.create(
        site_policy_digest="a" * 64,
        account_label="double revoke account",
        browser_identity_digest="b" * 64,
    )
    first = browser_profile_user_command(f"revoke {ref.profile_id}", store)
    assert "revoked" in first

    second = browser_profile_user_command(f"revoke {ref.profile_id}", store)

    assert "already revoked" in second
    assert "nothing" in second
    # 未伪装成功，也未泄漏内部细节。
    assert str(tmp_path) not in second
    assert "double revoke" not in second


@pytest.mark.parametrize("verb", ["revoke", "clear"])
def test_profile_command_corrupt_metadata_surfaces_closed_value_error(tmp_path, verb):
    store = _profile_store(tmp_path)
    ref = store.create(
        site_policy_digest="a" * 64,
        account_label="corrupt metadata account",
        browser_identity_digest="b" * 64,
    )
    (tmp_path / "profiles" / ref.profile_id / "metadata.json").write_text(
        "{ not json"
    )

    try:
        browser_profile_user_command(f"{verb} {ref.profile_id}", store)
    except ValueError as error:
        message = str(error)
    else:
        pytest.fail("corrupt metadata must surface a closed ValueError")

    # closed 文本：不含 path/label 原文/digest，也不含 store 内部措辞。
    for forbidden in (str(tmp_path), "not json", "metadata", "corrupt metadata"):
        assert forbidden not in message, forbidden


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
    # 003：completion 只消费原 session 的 exact writer lease。
    lease = store.acquire_writer(ref)

    first = complete_browser_takeover_profile(
        request,
        store,
        lease=lease,
        browser_identity_digest="b" * 64,
    )
    second = complete_browser_takeover_profile(
        request,
        store,
        lease=lease,
        browser_identity_digest="b" * 64,
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
        lease=store.acquire_writer(profile),
        browser_identity_digest=browser_identity,
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
            lease=store.acquire_writer(profile),
            browser_identity_digest="c" * 64,
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
    # 只投影该真实 approval 数据为 authoritative pending state 交
    # TerminalRenderer.render_pending 渲染。无平行 preview/event 构造。
    from agent.browser.session_store import BrowserSessionStore
    from agent.browser.tools import build_browser_tools
    from agent.browser.url_policy import browser_site_policy_digest
    from agent.cli.render import TerminalRenderer
    from agent.runtime.contracts import (
        ApprovalGrant,
        ApprovalRequired,
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
    registrations = build_browser_tools(
        environment=environment,
        profile_store=profiles,
        session_store=BrowserSessionStore(root=tmp_path / "sessions"),
        browser_identity_digest="b" * 64,
        clock=lambda: "2026-08-28T10:00:00+00:00",
        monotonic_clock=lambda: 1000.0,
    ).registrations
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
    # 真实 approval 数据 → authoritative state → TerminalRenderer.render_pending。
    # （pending event 已不再是可操作提示权威，渲染载体改用 render_pending。）
    rendered_lines: list[str] = []
    renderer = TerminalRenderer(write_fn=rendered_lines.append)
    from dataclasses import replace as _replace

    from agent.runtime.contracts import (
        ActiveRun,
        ActiveRunStatus,
        ContinuationPhase,
        ConversationState,
    )

    renderer.render_pending(
        _replace(
            ConversationState.new("conversation-1"),
            active_run=ActiveRun(
                "run-1",
                status=ActiveRunStatus.AWAITING_APPROVAL,
                phase=ContinuationPhase.TOOL,
                pending_request=approval.request,
                tool_calls=(act_call,),
            ),
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


# --------------------------------------------------------------------------- #
# 003 修复批 2（fresh reviewer P2）：list/create 面对不可用 root 时，store 的
# closed 异常（ProfileNotFoundError/ProfileIntegrityError）不得穿透 handler，
# 只抛 closed ValueError，且消息不含 tmp path/account label/internal 细节。
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "damage",
    [
        pytest.param("missing", id="root-missing"),
        pytest.param("symlink", id="root-symlink"),
    ],
)
def test_profile_list_with_unusable_root_surfaces_closed_value_error(tmp_path, damage):
    store = _profile_store(tmp_path)
    if damage == "symlink":
        target = tmp_path / "elsewhere"
        target.mkdir()
        (tmp_path / "profiles").symlink_to(target)

    with pytest.raises(ValueError) as raised:
        browser_profile_user_command("list", store)

    message = str(raised.value)
    assert "unavailable" in message
    for forbidden in (
        str(tmp_path),
        "elsewhere",
        "root missing",
        "real directory",
        "Errno",
        "Traceback",
    ):
        assert forbidden not in message, forbidden


def test_profile_create_with_unusable_root_surfaces_closed_value_error(tmp_path):
    # root 位置被普通文件占用：无法创建 owned root，create 不得让 store 的
    # closed 异常穿透（乃至 run_repl），只抛 closed ValueError。
    (tmp_path / "profiles").write_text("not a directory", encoding="utf-8")
    store = _profile_store(tmp_path)

    with pytest.raises(ValueError) as raised:
        browser_profile_user_command(
            "create https://site.example.test secret-account-label",
            store,
            browser_identity_digest="b" * 64,
        )

    message = str(raised.value)
    assert "unavailable" in message
    for forbidden in (
        str(tmp_path),
        "secret-account-label",
        "site.example.test",
        "real directory",
        "Errno",
        "Traceback",
    ):
        assert forbidden not in message, forbidden
