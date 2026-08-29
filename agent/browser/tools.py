"""018 唯一 governed browser tool registrations（plan Task 6）。

本模块只组合 browser-owned stores/environment 与既有 ``RegisteredTool`` seam；
不认识 Provider、ContextManager、checkpoint 或 AgentRuntime。所有 callable 仅在
唯一 ToolRuntime 已持久化 EXECUTING 后才会被调用。
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent.browser.action_policy import BrowserActionBindingV1, BrowserActionPolicy
from agent.browser.contracts import (
    BrowserActionKind,
    BrowserActionOutcome,
    BrowserActionV1,
    BrowserCleanupOutcome,
    BrowserHandleV1,
    BrowserMode,
    BrowserObservationV1,
    BrowserSessionSpecV1,
)
from agent.browser.ports import (
    BrowserEnvironment,
    BrowserOpenNotStartedError,
    KnownNotExecuted,
)
from agent.browser.profile_store import (
    BrowserProfileStore,
    ProfileStatus,
    ProfileWriterLeaseV1,
)
from agent.browser.quarantine import (
    BrowserQuarantine,
    BrowserQuarantineError,
    UploadFileSnapshotV1,
)
from agent.browser.session_store import (
    BrowserSessionRecordV1,
    BrowserSessionStore,
    SessionActionOutcome,
    SessionPhase,
    SessionRecovery,
)
from agent.browser.url_policy import browser_site_policy_digest
from agent.runtime.contracts import (
    ApprovalPolicy,
    BrowserTakeoverRequestV1,
    EgressClass,
    ExecutionAuthorityClass,
    ExecutionIntent,
    OutputPolicy,
    SideEffectClass,
    ToolExecutionOutput,
    ToolRisk,
    ToolSpec,
)
from agent.runtime.tool_governance import BrowserActionToolPolicy
from agent.runtime.tools import RegisteredTool

BROWSER_TOOL_NAMES = (
    "browser_open",
    "browser_observe",
    "browser_act",
    "browser_close",
    "browser_begin_takeover",
)
_ACTION_KINDS = tuple(item.value for item in BrowserActionKind)
_MODES = tuple(item.value for item in BrowserMode)
_SESSION_SECONDS = 30 * 60
_ACTION_APPROVAL_SECONDS = 5 * 60


def _spec(
    name: str,
    description: str,
    properties: dict,
    *,
    required: tuple[str, ...] = (),
    side_effect: SideEffectClass,
    approval: ApprovalPolicy,
    kind: str,
    egress: EgressClass = EgressClass.NONE,
    risk: ToolRisk = ToolRisk.MEDIUM,
) -> ToolSpec:
    schema = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = list(required)
    return ToolSpec(
        name=name,
        version="governed-browser-v1",
        description=description,
        input_schema=schema,
        risk=risk,
        side_effect=side_effect,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=approval,
        safety_policy={"kind": kind, "closed_browser_surface": True},
        output_limit_chars=64_000,
        egress=egress,
        execution_authority=ExecutionAuthorityClass.BROWSER_SESSION,
    )


@dataclass(slots=True)
class _Session:
    handle: BrowserHandleV1
    spec: BrowserSessionSpecV1
    record: BrowserSessionRecordV1
    observation: BrowserObservationV1 | None = None
    writer_lease: ProfileWriterLeaseV1 | None = None


class _BrowserTools:
    def __init__(
        self,
        *,
        environment: BrowserEnvironment,
        profile_store: BrowserProfileStore,
        session_store: BrowserSessionStore,
        browser_identity_digest: str,
        clock: Callable[[], str],
        monotonic_clock: Callable[[], float],
        workspace: Path | None = None,
        quarantine: BrowserQuarantine | None = None,
    ) -> None:
        if len(browser_identity_digest) != 64 or any(
            item not in "0123456789abcdef" for item in browser_identity_digest
        ):
            raise ValueError("browser_identity_digest must be 64 lowercase hex chars")
        self._environment = environment
        self._profiles = profile_store
        self._sessions = session_store
        self._browser_identity_digest = browser_identity_digest
        self._clock = clock
        self._session_expiry = monotonic_clock() + _SESSION_SECONDS
        self._active: dict[str, _Session] = {}
        self._action_bindings: dict[str, BrowserActionBindingV1] = {}
        self._workspace = Path(workspace).absolute() if workspace is not None else None
        self._quarantine = quarantine
        self._upload_snapshots: dict[str, UploadFileSnapshotV1] = {}

    def prepare_open(self, arguments: dict) -> dict:
        mode = BrowserMode(arguments["mode"])
        origins = tuple(arguments.get("allowed_origins", ()))
        profile_ref = arguments.get("profile_ref")
        profile_revision = arguments.get("profile_revision")
        action_budget = arguments.get("action_budget", 64)
        if type(action_budget) is not int or action_budget <= 0 or action_budget > 256:
            raise ValueError("browser action_budget must be in 1..256")
        if mode is BrowserMode.PUBLIC_READ_EPHEMERAL:
            if profile_ref is not None or profile_revision is not None or origins:
                raise ValueError("public read cannot bind profile or origins")
        else:
            if not isinstance(profile_ref, str) or type(profile_revision) is not int:
                raise ValueError("interactive browser requires profile_ref/revision")
            if not origins or any(not isinstance(item, str) for item in origins):
                raise ValueError("interactive browser requires exact origins")
            current = self._profiles.open(profile_ref)
            if (
                current.revision != profile_revision
                or current.browser_identity_digest != self._browser_identity_digest
            ):
                raise ValueError("browser profile binding changed")
            if current.site_policy_digest != browser_site_policy_digest(origins):
                raise ValueError("browser profile site policy changed")
        return {
            "mode": mode.value,
            "profile_ref": profile_ref,
            "profile_revision": profile_revision,
            "allowed_origins": list(origins),
            "action_budget": action_budget,
            "browser_identity_digest": self._browser_identity_digest,
            "session_expiry_monotonic": self._session_expiry,
            "effect_preview": (
                f"Open dedicated {mode.value} Chromium session; origins="
                + (", ".join(origins) if origins else "public HTTPS policy")
            ),
        }

    def open(self, intent: ExecutionIntent) -> ToolExecutionOutput | KnownNotExecuted:
        binding = intent.safety_binding
        try:
            mode = BrowserMode(binding["mode"])
            if mode is BrowserMode.PUBLIC_READ_EPHEMERAL:
                spec = BrowserSessionSpecV1.public_read(
                    goal_id=intent.goal_id or "",
                    goal_revision=intent.goal_revision or 0,
                    action_budget=int(binding["action_budget"]),
                )
                profile = None
                writer = None
            else:
                profile = self._profiles.open(str(binding["profile_ref"]))
                writer = self._profiles.acquire_writer(profile)
                spec = BrowserSessionSpecV1.site_bound(
                    goal_id=intent.goal_id or "",
                    goal_revision=intent.goal_revision or 0,
                    profile_ref=profile.profile_id,
                    allowed_origins=tuple(binding["allowed_origins"]),
                    action_budget=int(binding["action_budget"]),
                    profile_revision=profile.revision,
                    browser_identity_digest=self._browser_identity_digest,
                    expiry_monotonic=float(binding["session_expiry_monotonic"]),
                )
        except (KeyError, TypeError, ValueError) as error:
            return KnownNotExecuted(code="browser_open_invalid", message=str(error))

        # open 一旦进入 adapter，异常可能发生在 Chromium 已启动之后。site-bound
        # writer 此时必须保留为 quarantine；只有拿到 handle 并确认 close=CLEANED
        # 才能安全释放，不能把 unknown 伪装成零 effect。
        try:
            handle = self._environment.open(spec)
        except BrowserOpenNotStartedError as error:
            if writer is not None:
                self._profiles.release_writer(writer)
            return KnownNotExecuted(
                code="browser_open_unavailable",
                message=str(error),
            )
        record = None
        try:
            if handle.authority_digest != spec.identity_digest:
                raise ValueError(
                    "browser handle did not bind the requested session"
                )
            record = self._sessions.begin(
                spec=spec,
                profile_revision=spec.profile_revision,
                browser_identity_digest=self._browser_identity_digest,
                session_ref=handle.session_ref,
            )
            record = self._sessions.compare_and_swap(
                record,
                new_phase=SessionPhase.ACTIVE,
                expected_profile_revision=spec.profile_revision,
            )
            self._active[handle.session_ref] = _Session(
                handle=handle,
                spec=spec,
                record=record,
                writer_lease=writer,
            )
        except Exception as error:
            receipt = self._environment.close(handle)
            if receipt.outcome is not BrowserCleanupOutcome.CLEANED:
                raise RuntimeError(
                    "browser open failed after effect and cleanup is unknown"
                ) from error
            if writer is not None:
                self._profiles.release_writer(writer)
            raise RuntimeError(
                "browser open failed after effect; cleanup confirmed"
            ) from error
        return ToolExecutionOutput(
            content=json.dumps(
                {"session_ref": handle.session_ref, "mode": mode.value},
                sort_keys=True,
            ),
            metadata={
                "browser_result_kind": "browser_open",
                "session_ref": handle.session_ref,
                "mode": mode.value,
                "profile_ref": spec.profile_ref,
                "profile_revision": spec.profile_revision,
                "browser_identity_digest": self._browser_identity_digest,
            },
        )

    def _session(self, session_ref: object) -> _Session:
        if not isinstance(session_ref, str) or session_ref not in self._active:
            raise ValueError("browser session is not active in this process")
        session = self._active[session_ref]
        if self._sessions.load(session_ref) != session.record:
            raise ValueError("browser session ledger changed")
        return session

    def _require_current_profile(self, session: _Session) -> None:
        if session.spec.mode is BrowserMode.PUBLIC_READ_EPHEMERAL:
            return
        profile_ref = session.spec.profile_ref
        if profile_ref is None:
            raise ValueError("interactive browser profile binding is missing")
        current = self._profiles.open(profile_ref)
        if (
            current.status is not ProfileStatus.ACTIVE
            or current.revision != session.spec.profile_revision
            or current.browser_identity_digest != self._browser_identity_digest
            or current.site_policy_digest
            != browser_site_policy_digest(session.spec.allowed_origins)
        ):
            raise ValueError("browser profile binding changed")

    def _active_session(self, session_ref: object) -> _Session:
        session = self._session(session_ref)
        self._require_current_profile(session)
        return session

    @staticmethod
    def _session_binding(session: _Session, browser_identity_digest: str) -> dict:
        return {
            "session_ref": session.handle.session_ref,
            "mode": session.spec.mode.value,
            "profile_ref": session.spec.profile_ref,
            "profile_revision": session.spec.profile_revision,
            "browser_identity_digest": browser_identity_digest,
            "allowed_origins": list(session.spec.allowed_origins),
        }

    def prepare_session(self, arguments: dict) -> dict:
        session = self._session(arguments.get("session_ref"))
        return self._session_binding(session, self._browser_identity_digest)

    def prepare_active_session(self, arguments: dict) -> dict:
        session = self._active_session(arguments.get("session_ref"))
        return self._session_binding(session, self._browser_identity_digest)

    def observe(self, intent: ExecutionIntent) -> ToolExecutionOutput:
        session = self._active_session(intent.arguments.get("session_ref"))
        observation = self._environment.observe(session.handle)
        if (
            observation.session_ref != session.handle.session_ref
            or observation.browser_revision != self._browser_identity_digest
            or observation.profile_revision != session.spec.profile_revision
        ):
            raise ValueError("browser observation identity mismatch")
        session.record = self._sessions.record_observation(
            session.record,
            observation_digest=observation.observation_digest,
            expected_profile_revision=session.spec.profile_revision,
        )
        session.observation = observation
        content = {
            "session_ref": observation.session_ref,
            "page_id": observation.page_id,
            "frame_id": observation.frame_id,
            "canonical_url": observation.canonical_url,
            "canonical_origin": observation.canonical_origin,
            "aria_projection": observation.aria_projection,
            "element_refs": [asdict(item) for item in observation.element_refs],
            "truncated": observation.truncated,
        }
        return ToolExecutionOutput(
            content=json.dumps(content, sort_keys=True),
            metadata={
                "browser_result_kind": "browser_observe",
                "session_ref": observation.session_ref,
                "observation_digest": observation.observation_digest,
                "page_id": observation.page_id,
                "frame_id": observation.frame_id,
                "canonical_origin": observation.canonical_origin,
                "profile_revision": observation.profile_revision,
                "browser_identity_digest": observation.browser_revision,
                # trusted Goal 绑定（来自 session spec）；evidence oracle 要求
                # 与当前 derive(goal) 全等。
                "goal_id": session.spec.goal_id,
                "goal_revision": session.spec.goal_revision,
            },
        )

    @staticmethod
    def _action(arguments: dict) -> BrowserActionV1:
        kind = BrowserActionKind(arguments["kind"])
        target_ref = arguments.get("target_ref")
        params = arguments.get("params")
        no_params = kind in {
            BrowserActionKind.BACK,
            BrowserActionKind.RELOAD,
            BrowserActionKind.CLOSE,
        }
        if no_params and (target_ref is not None or params is not None):
            raise ValueError(f"{kind.value} accepts no target or params")
        if kind is BrowserActionKind.SCROLL and (
            target_ref is not None
            or not isinstance(params, dict)
            or set(params) != {"delta_y"}
            or type(params["delta_y"]) is not int
        ):
            raise ValueError("scroll requires exact integer delta_y")
        if kind is BrowserActionKind.NAVIGATE and (
            target_ref is not None
            or not isinstance(params, dict)
            or set(params) != {"url"}
            or not isinstance(params["url"], str)
            or not params["url"]
        ):
            raise ValueError("navigate requires one exact url")
        if kind is BrowserActionKind.CLICK and (
            not isinstance(target_ref, str) or not target_ref or params is not None
        ):
            raise ValueError("click requires one exact target_ref")
        if kind is BrowserActionKind.SELECT and (
            not isinstance(target_ref, str)
            or not target_ref
            or not isinstance(params, dict)
            or set(params) != {"value"}
            or not isinstance(params["value"], str)
        ):
            raise ValueError("select requires exact target_ref and value")
        if kind is BrowserActionKind.FILL_FORM and (
            not isinstance(target_ref, str)
            or not target_ref
            or not isinstance(params, dict)
            or set(params) != {"fields"}
            or not isinstance(params["fields"], dict)
            or not params["fields"]
            or any(
                not isinstance(key, str)
                or not key
                or not isinstance(value, str)
                for key, value in params["fields"].items()
            )
        ):
            raise ValueError("fill_form requires exact string fields")
        if kind is BrowserActionKind.UPLOAD and (
            not isinstance(target_ref, str)
            or not target_ref
            or not isinstance(params, dict)
            or set(params) != {"path", "sha256", "purpose"}
            or not isinstance(params["path"], str)
            or not isinstance(params["sha256"], str)
            or not isinstance(params["purpose"], str)
            or not params["purpose"]
            or len(params["purpose"]) > 256
        ):
            raise ValueError("upload requires exact path, sha256, purpose and target_ref")
        if kind is BrowserActionKind.DOWNLOAD and (
            not isinstance(target_ref, str) or not target_ref or params is not None
        ):
            raise ValueError("download requires one exact target_ref and no params")
        return BrowserActionV1(
            kind=kind,
            observation_digest=arguments["observation_digest"],
            page_id=arguments["page_id"],
            frame_id=arguments["frame_id"],
            target_ref=target_ref,
            params=params,
        )

    def prepare_action(self, arguments: dict) -> dict:
        session = self._active_session(arguments.get("session_ref"))
        if session.observation is None:
            raise ValueError("browser_observe is required before browser_act")
        action = self._action(arguments)
        if action.observation_digest != session.observation.observation_digest:
            raise ValueError("browser action does not bind the current observation")
        policy_binding = BrowserActionPolicy.prepare(
            session.observation,
            action,
            allow_public_navigation=(
                session.spec.mode is BrowserMode.PUBLIC_READ_EPHEMERAL
            ),
        )
        self._action_bindings[action.identity_digest] = policy_binding
        if action.kind is BrowserActionKind.UPLOAD:
            if self._workspace is None or self._quarantine is None:
                raise ValueError("browser upload resources are unavailable")
            current_snapshot = self._quarantine.inspect_upload(
                self._workspace,
                action.params["path"],
                expected_sha256=action.params["sha256"],
            )
            previous_snapshot = self._upload_snapshots.get(action.identity_digest)
            if previous_snapshot is not None and previous_snapshot != current_snapshot:
                raise ValueError("upload source changed after approval")
            self._upload_snapshots[action.identity_digest] = current_snapshot
        elif action.kind is BrowserActionKind.DOWNLOAD and self._quarantine is None:
            raise ValueError("browser download quarantine is unavailable")
        issued = datetime.fromtimestamp(session.observation.observed_at, tz=UTC)
        return {
            **self.prepare_session({"session_ref": session.handle.session_ref}),
            "page_id": action.page_id,
            "frame_id": action.frame_id,
            "observation_digest": action.observation_digest,
            "action_digest": action.identity_digest,
            "consequence": policy_binding.consequence.value,
            "effect_preview": policy_binding.preview,
            "binding_digest": policy_binding.binding_digest,
            "issued_at": issued.isoformat(),
            "expires_at": (issued + timedelta(seconds=_ACTION_APPROVAL_SECONDS)).isoformat(),
        }

    def act(self, intent: ExecutionIntent) -> ToolExecutionOutput | KnownNotExecuted:
        session = self._active_session(intent.arguments.get("session_ref"))
        action = self._action(intent.arguments)
        binding = self._action_bindings.get(action.identity_digest)
        if binding is None or binding.binding_digest != intent.safety_binding.get(
            "binding_digest"
        ):
            return KnownNotExecuted(
                code="browser_binding_changed",
                message="browser action binding is unavailable or changed",
            )
        staging = None
        if action.kind is BrowserActionKind.UPLOAD:
            snapshot = self._upload_snapshots.get(action.identity_digest)
            if snapshot is None or self._quarantine is None:
                return KnownNotExecuted(
                    code="browser_upload_binding_changed",
                    message="approved upload snapshot is unavailable",
                )
            try:
                staging = self._quarantine.stage_upload(
                    snapshot,
                    session_ref=session.handle.session_ref,
                    action_digest=action.identity_digest,
                )
            except BrowserQuarantineError as error:
                return KnownNotExecuted(
                    code="browser_file_binding_changed",
                    message=str(error),
                )
        try:
            prepared = self._sessions.begin_action(
                session.record,
                action_digest=action.identity_digest,
                observation_digest=action.observation_digest,
                expected_profile_revision=session.spec.profile_revision,
            )
            executing = self._sessions.compare_and_swap(
                prepared,
                new_phase=SessionPhase.EXECUTING,
                expected_profile_revision=session.spec.profile_revision,
            )
            if action.kind is BrowserActionKind.UPLOAD:
                outcome = self._environment.execute(
                    session.handle,
                    action,
                    binding=binding,
                    upload_staging=(
                        staging.capability if staging is not None else None
                    ),
                )
            elif action.kind is BrowserActionKind.DOWNLOAD:
                outcome = self._environment.execute(
                    session.handle,
                    action,
                    binding=binding,
                )
            else:
                outcome = self._environment.execute(
                    session.handle,
                    action,
                    binding=binding,
                )
        except Exception:
            # begin_action/EXECUTING 已 durable；adapter exception 代表 unknown。
            # 内存镜像必须重读到同一 EXECUTING record，才能允许后续显式
            # cleanup，而不能因 stale mirror 连 browser_close 都拒绝。
            with contextlib.suppress(Exception):
                session.record = self._sessions.load(session.handle.session_ref)
            raise
        finally:
            if staging is not None and self._quarantine is not None:
                self._quarantine.delete_staging(staging)
            self._upload_snapshots.pop(action.identity_digest, None)
        if isinstance(outcome, KnownNotExecuted):
            session.record = self._sessions.record_result(
                executing,
                outcome=SessionActionOutcome.NOT_EXECUTED,
                expected_profile_revision=session.spec.profile_revision,
            )
            return outcome
        if (
            outcome.action_digest != action.identity_digest
            or outcome.pre_observation_digest != action.observation_digest
            or outcome.outcome
            not in {
                BrowserActionOutcome.EFFECT_APPLIED,
                BrowserActionOutcome.EFFECT_BLOCKED,
            }
        ):
            raise ValueError("browser action receipt does not bind the approved action")
        session.record = self._sessions.record_result(
            executing,
            outcome=SessionActionOutcome.APPLIED,
            expected_profile_revision=session.spec.profile_revision,
        )
        metadata = {
            "browser_result_kind": "browser_action",
            "browser_receipt_kind": "browser_action_v1",
            "receipt_digest": outcome.receipt_digest,
            "action_digest": outcome.action_digest,
            "pre_observation_digest": outcome.pre_observation_digest,
            "post_observation_digest": outcome.post_observation_digest,
            "outcome": outcome.outcome.value,
            # durable identity：evidence oracle 靠这些字段证明同 session/
            # profile/browser/Goal；缺失即证据不可推导。goal 绑定来自
            # trusted BrowserSessionSpecV1（spec identity digest 已覆盖）。
            "session_ref": session.handle.session_ref,
            "profile_revision": session.spec.profile_revision,
            "browser_identity_digest": self._browser_identity_digest,
            "goal_id": session.spec.goal_id,
            "goal_revision": session.spec.goal_revision,
        }
        if outcome.download is not None:
            metadata.update(
                {
                    "download_receipt_kind": "quarantined_download_v1",
                    "download_receipt_digest": outcome.download.receipt_digest,
                    "quarantine_id": outcome.download.quarantine_id,
                    "source_origin": outcome.download.source_origin,
                    "suggested_name_digest": outcome.download.suggested_name_digest,
                    "normalized_name": outcome.download.normalized_name,
                    "mime_type": outcome.download.mime_type,
                    "byte_size": outcome.download.byte_size,
                    "sha256": outcome.download.sha256,
                }
            )
        return ToolExecutionOutput(
            content=json.dumps(
                {
                    "action_digest": outcome.action_digest,
                    "outcome": outcome.outcome.value,
                    "post_observation_digest": outcome.post_observation_digest,
                },
                sort_keys=True,
            ),
            is_error=outcome.outcome is BrowserActionOutcome.EFFECT_BLOCKED,
            metadata=metadata,
        )

    def close(self, intent: ExecutionIntent) -> ToolExecutionOutput:
        session = self._session(intent.arguments.get("session_ref"))
        recovery = self._sessions.pending_recovery(session.record)
        receipt = self._environment.close(session.handle)
        cleanup_confirmed = (
            receipt.outcome is BrowserCleanupOutcome.CLEANED
            and recovery is SessionRecovery.NONE
        )
        if cleanup_confirmed:
            session.record = self._sessions.close(
                session.record,
                expected_profile_revision=session.spec.profile_revision,
            )
            if session.writer_lease is not None:
                self._profiles.release_writer(session.writer_lease)
            self._active.pop(session.handle.session_ref, None)
        return ToolExecutionOutput(
            content=json.dumps(
                {
                    "session_ref": receipt.session_ref,
                    "outcome": receipt.outcome.value,
                },
                sort_keys=True,
            ),
            is_error=(
                receipt.outcome is BrowserCleanupOutcome.CLEANUP_UNKNOWN
                or recovery is SessionRecovery.UNKNOWN_OUTCOME
            ),
            metadata={
                "browser_result_kind": "browser_close",
                "session_ref": receipt.session_ref,
                "cleanup_outcome": receipt.outcome.value,
                "session_recovery": recovery.value,
                "receipt_digest": receipt.receipt_digest,
            },
        )

    def begin_takeover(self, intent: ExecutionIntent) -> BrowserTakeoverRequestV1:
        session = self._active_session(intent.arguments.get("session_ref"))
        if session.spec.mode is not BrowserMode.SITE_BOUND_INTERACTIVE:
            raise ValueError("takeover requires a site-bound interactive session")
        request = intent.browser_takeover_request
        if (
            request is None
            or request.session_ref != session.handle.session_ref
            or request.profile_ref != session.spec.profile_ref
            or request.profile_revision != session.spec.profile_revision
            or request.browser_identity_digest != self._browser_identity_digest
        ):
            raise ValueError("takeover intent does not bind the active browser session")
        self._environment.begin_takeover(session.handle)
        return request


def build_browser_tool_registrations(
    *,
    environment: BrowserEnvironment,
    profile_store: BrowserProfileStore,
    session_store: BrowserSessionStore,
    browser_identity_digest: str,
    clock: Callable[[], str],
    monotonic_clock: Callable[[], float],
    workspace: Path | None = None,
    quarantine: BrowserQuarantine | None = None,
) -> tuple[RegisteredTool, ...]:
    tools = _BrowserTools(
        environment=environment,
        profile_store=profile_store,
        session_store=session_store,
        browser_identity_digest=browser_identity_digest,
        clock=clock,
        monotonic_clock=monotonic_clock,
        workspace=workspace,
        quarantine=quarantine,
    )
    session_property = {"session_ref": {"type": "string"}}
    action_properties = {
        **session_property,
        "kind": {"type": "string", "enum": list(_ACTION_KINDS)},
        "observation_digest": {"type": "string"},
        "page_id": {"type": "string"},
        "frame_id": {"type": "string"},
        "target_ref": {"type": "string"},
        "params": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "value": {"type": "string"},
                "fields": {"type": "object"},
                "delta_y": {"type": "integer"},
                "path": {"type": "string"},
                "sha256": {"type": "string"},
                "purpose": {"type": "string"},
            },
            "additionalProperties": False,
        },
    }
    return (
        RegisteredTool(
            spec=_spec(
                "browser_open",
                "Open one dedicated governed Chromium session.",
                {
                    "mode": {"type": "string", "enum": list(_MODES)},
                    "profile_ref": {"type": "string"},
                    "profile_revision": {"type": "integer", "minimum": 1},
                    "allowed_origins": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "action_budget": {"type": "integer", "minimum": 1},
                },
                required=("mode",),
                side_effect=SideEffectClass.EXTERNAL,
                approval=ApprovalPolicy.ALWAYS,
                kind="browser_open",
                risk=ToolRisk.HIGH,
            ),
            prepare_binding=tools.prepare_open,
            func=tools.open,
        ),
        RegisteredTool(
            spec=_spec(
                "browser_observe",
                "Read one bounded ARIA projection from the active session.",
                session_property,
                required=("session_ref",),
                side_effect=SideEffectClass.READ_ONLY,
                approval=ApprovalPolicy.NEVER,
                kind="browser_observe",
                risk=ToolRisk.LOW,
            ),
            prepare_binding=tools.prepare_active_session,
            func=tools.observe,
        ),
        RegisteredTool(
            spec=_spec(
                "browser_act",
                "Execute one closed action bound to the current browser observation.",
                action_properties,
                required=(
                    "session_ref",
                    "kind",
                    "observation_digest",
                    "page_id",
                    "frame_id",
                ),
                side_effect=SideEffectClass.EXTERNAL,
                approval=ApprovalPolicy.ALWAYS,
                kind="browser_action",
                egress=EgressClass.GOVERNED_NETWORK,
                risk=ToolRisk.HIGH,
            ),
            prepare_binding=tools.prepare_action,
            func=tools.act,
            policy=BrowserActionToolPolicy(),
        ),
        RegisteredTool(
            spec=_spec(
                "browser_close",
                "Close one active browser session and record bounded cleanup.",
                session_property,
                required=("session_ref",),
                side_effect=SideEffectClass.EXTERNAL,
                approval=ApprovalPolicy.NEVER,
                kind="browser_close",
            ),
            prepare_binding=tools.prepare_session,
            func=tools.close,
        ),
        RegisteredTool(
            spec=_spec(
                "browser_begin_takeover",
                "Pause automation for user interaction in the dedicated browser window.",
                session_property,
                required=("session_ref",),
                side_effect=SideEffectClass.EXTERNAL,
                approval=ApprovalPolicy.NEVER,
                kind="browser_takeover",
            ),
            prepare_binding=tools.prepare_active_session,
            func=tools.begin_takeover,
        ),
    )


__all__ = ["BROWSER_TOOL_NAMES", "build_browser_tool_registrations"]
