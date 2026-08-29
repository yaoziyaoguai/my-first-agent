"""018 sealed E3 的真实 TLS/Chromium journey driver。

这里只编排 test-only fixture 与 production BrowserEnvironment/ToolRuntime 公共
接口；不 import tests.*，不复制浏览器实现。J6 只实例化一次 production
AgentRuntime 来证明 takeover gate，其他 journey 不另建 model/tool loop。所有 verdict
均来自实际返回值、持久 store、fixture counters 或 closed evidence oracle。
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import socket
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from agent.browser.contracts import BrowserCleanupOutcome, BrowserMode
from agent.browser.playwright_adapter import (
    BrowserEgressGuard,
    PlaywrightBrowserEnvironment,
    RequestKind,
    SocketAddressResolver,
)
from agent.browser.profile_store import BrowserProfileStore, ProfileNotFoundError
from agent.browser.quarantine import (
    BrowserQuarantine,
    BrowserQuarantineError,
    QuarantinedDownloadV1,
)
from agent.browser.session_store import BrowserSessionStore
from agent.browser.takeover import complete_browser_takeover_profile
from agent.browser.tools import build_browser_tool_registrations
from agent.browser.url_policy import URLPolicyError, browser_site_policy_digest
from agent.cli.render import TerminalRenderer
from agent.runtime.checkpoint import LocalCheckpointStore
from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    ActiveRun,
    ActiveRunStatus,
    AdmittedCriterion,
    ApprovalGrant,
    ApprovalRequired,
    BrowserAuthorityLeaseV1,
    CompleteBrowserTakeover,
    CompletionClaim,
    ContextPack,
    ContinuationPhase,
    ConversationFact,
    ConversationState,
    EvidenceOracleKind,
    ExecutionIntent,
    FactKind,
    GoalDelta,
    GoalDeltaProposal,
    GoalFrame,
    GoalStatus,
    ModelResponse,
    ModelToolCall,
    ProposedCriterion,
    RecoveryRequest,
    ResolveApproval,
    RunResult,
    RunStatus,
    RuntimeEvent,
    SubmitMessage,
    ToolCall,
    ToolPreparation,
    ToolPrepareContext,
    ToolResult,
    canonical_json_digest,
)
from agent.runtime.evidence import ClosedEvidenceRegistry, EvidenceVerificationError
from agent.runtime.loop import AgentRuntime, InvocationLimits
from agent.runtime.ports import RetryableProviderError
from agent.runtime.state import (
    accept_action,
    mark_executing,
    pause_for_recovery,
    record_completion_claim,
    record_evidence,
    verify_goal_completion,
)
from agent.runtime.tools import IntentConflictError, KernelToolRuntime
from agent.runtime.views import project_browser_takeover_status
from main import _browser_status_lines
from scripts.browser_e3_fixture import (
    ADVERSARY_HOST,
    DOWNLOAD_BYTES,
    FixturePlaywrightFactory,
    FixtureResolver,
    HostileTLSFixture,
)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    if not root.exists():
        return digest.hexdigest()
    for item in sorted(root.rglob("*")):
        relative = item.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        if item.is_symlink():
            digest.update(b"symlink:")
            digest.update(item.readlink().as_posix().encode("utf-8"))
        elif item.is_file():
            digest.update(bytes.fromhex(_sha256_bytes(item.read_bytes())))
        elif item.is_dir():
            digest.update(b"directory")
    return digest.hexdigest()


def _wait_until(predicate, *, timeout: float = 8.0) -> bool:  # noqa: ANN001
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return bool(predicate())


def _process_snapshot() -> dict[int, tuple[int, str]]:
    """读取 PID、PPID 与 start time；失败时由 caller fail closed。"""

    completed = subprocess.run(
        ["/bin/ps", "-axo", "pid=,ppid=,lstart="],
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )
    if completed.returncode != 0:
        raise RuntimeError("cannot read browser process identities")
    snapshot: dict[int, tuple[int, str]] = {}
    for line in completed.stdout.splitlines():
        parts = line.split()
        if len(parts) < 7:
            continue
        try:
            pid = int(parts[0])
            ppid = int(parts[1])
        except ValueError:
            continue
        snapshot[pid] = (ppid, " ".join(parts[2:7]))
    if not snapshot:
        raise RuntimeError("browser process identity snapshot is empty")
    return snapshot


@dataclass(frozen=True, slots=True)
class _ProcessIdentity:
    pid: int
    started_at: str


class _OwnedBrowserProcesses:
    """仅追踪本 E3 runner 启动后出现的真实 descendant identity。"""

    def __init__(
        self,
        *,
        parent_pid: int = os.getpid(),
        snapshotter: Callable[[], dict[int, tuple[int, str]]] = _process_snapshot,
    ) -> None:
        self._parent_pid = parent_pid
        self._snapshotter = snapshotter
        baseline = snapshotter()
        self._baseline = self._descendants(baseline)
        self._owned: set[_ProcessIdentity] = set()
        self._uncertain = False

    def _descendants(
        self,
        snapshot: dict[int, tuple[int, str]],
    ) -> set[_ProcessIdentity]:
        descendant_pids = {self._parent_pid}
        changed = True
        while changed:
            changed = False
            for pid, (ppid, _started_at) in snapshot.items():
                if ppid in descendant_pids and pid not in descendant_pids:
                    descendant_pids.add(pid)
                    changed = True
        return {
            _ProcessIdentity(pid, snapshot[pid][1])
            for pid in descendant_pids
            if pid != self._parent_pid and pid in snapshot
        }

    def observe(self) -> bool:
        try:
            descendants = self._descendants(self._snapshotter())
        except Exception:  # noqa: BLE001 - E3 oracle 必须把观测失败记为 unknown
            self._uncertain = True
            return False
        self._owned.update(descendants - self._baseline)
        return bool(self._owned)

    def confirmed_gone(self, *, timeout: float = 8.0) -> bool:
        if self._uncertain or not self._owned:
            return False
        deadline = time.monotonic() + timeout
        while True:
            try:
                snapshot = self._snapshotter()
            except Exception:  # noqa: BLE001 - process identity unknown 必须 fail closed
                return False
            live = {
                _ProcessIdentity(pid, started_at)
                for pid, (_ppid, started_at) in snapshot.items()
            }
            if self._owned.isdisjoint(live):
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.05)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _browser_denial_explanation_accurate(text: str) -> bool:
    lowered = " ".join(text.lower().split())
    return (
        "browser" in lowered
        and "was not run because you declined approval" in lowered
        and "no browser effect was executed" in lowered
        and "approval was granted" not in lowered
        and "browser effect was executed" not in lowered.replace(
            "no browser effect was executed", ""
        )
    )


def _headed_takeover_transition_observed(
    launch_modes_before: tuple[bool, ...],
    launch_modes_after: tuple[bool, ...],
) -> bool:
    """证明本次 takeover 恰好在既有 headless context 后新增 headed context。"""

    return (
        bool(launch_modes_before)
        and launch_modes_before[-1] is True
        and False not in launch_modes_before
        and launch_modes_after == (*launch_modes_before, False)
    )


def _storage_isolation_observed(
    seeded_projection: str,
    fresh_projection: str,
    *,
    first_session_cleaned: bool,
) -> bool:
    """先证明两类 storage 非空，再证明 fresh ephemeral session 两类均为空。"""

    return (
        first_session_cleaned
        and "Local storage present" in seeded_projection
        and "Cookie present" in seeded_projection
        and "Storage leaked" in seeded_projection
        and "Local storage absent" in fresh_projection
        and "Cookie absent" in fresh_projection
        and "Storage clean" in fresh_projection
        and "Local storage present" not in fresh_projection
        and "Cookie present" not in fresh_projection
        and "Storage leaked" not in fresh_projection
    )


def _closed_rejection_observed(
    before: tuple[int, int, int],
    after: tuple[int, int, int],
) -> bool:
    """对应 request kind 至少一次 guard reject，且真实 send 没有增加。"""

    return (
        after[0] > before[0]
        and after[1] > before[1]
        and after[2] == before[2]
    )


def _render_result_text(state: ConversationState, message: str) -> str:
    lines: list[str] = []
    TerminalRenderer(write_fn=lines.append).render_result(
        RunResult(status=RunStatus.COMPLETED, state=state, message=message)
    )
    return "\n".join(lines)


def _goal_state() -> ConversationState:
    source = ConversationFact(
        fact_id="action:1:user",
        kind=FactKind.USER_MESSAGE,
        content={"text": "complete the governed browser fixture"},
    )
    goal = GoalFrame(
        goal_id="goal-1",
        revision=1,
        created_from_fact_ids=(source.fact_id,),
        workspace_identity_digest="w" * 64,
        user_outcome="Complete the governed browser fixture",
        beneficiary="user",
        targets=("browser-fixture",),
        scope=("dedicated-browser",),
        non_goals=(),
        assumptions=(),
        proposed_criteria=(
            ProposedCriterion(
                "criterion-browser",
                "the governed browser effect has a fresh readback",
                oracle_kind=EvidenceOracleKind.BROWSER_READBACK,
            ),
        ),
        admitted_criteria=(),
        authority_snapshot="authority-1",
        status=GoalStatus.GOAL_READY,
        created_at="2026-08-28T10:00:00+00:00",
        updated_at="2026-08-28T10:00:00+00:00",
    )
    return ConversationState(
        conversation_id="conversation-browser-e3",
        revision=5,
        next_action_seq=2,
        replay_floor=2,
        facts=(source,),
        goal=goal,
    )


class _NoSendTransport:
    def __init__(self) -> None:
        self.sends = 0

    def send(self, _url: str) -> None:
        self.sends += 1


class _TakeoverProvider:
    """J6 的 bounded provider：GoalDelta、takeover call、resume sentinel。"""

    def __init__(self, *, session_ref: str, counters: dict[str, int]) -> None:
        self._session_ref = session_ref
        self._counters = counters
        self.calls = 0

    @staticmethod
    def _trusted_goal(context: ContextPack) -> dict:
        matches = [
            block
            for message in context.messages
            for block in message.content
            if isinstance(block, dict) and block.get("type") == "trusted_goal"
        ]
        if len(matches) != 1:
            raise RuntimeError("J6 provider requires one trusted Goal projection")
        return matches[0]

    def generate(self, context: ContextPack) -> ModelResponse:
        self.calls += 1
        self._counters["provider_calls"] += 1
        if self.calls == 1:
            trusted = self._trusted_goal(context)
            return ModelResponse(
                (),
                control=GoalDeltaProposal(
                    correlation_id="j6-goal-delta",
                    delta=GoalDelta(
                        goal_id=str(trusted["goal_id"]),
                        expected_revision=int(trusted["goal_revision"]),
                        reason="the takeover request keeps the trusted Goal unchanged",
                        updates={"targets": trusted["targets"]},
                    ),
                ),
            )
        if self.calls == 2:
            return ModelResponse(
                (
                    ModelToolCall(
                        "j6-takeover-call",
                        "browser_begin_takeover",
                        {"session_ref": self._session_ref},
                    ),
                )
            )
        raise RetryableProviderError("j6 resume sentinel")


class _DiscardingEventSink:
    def emit(self, _event: RuntimeEvent) -> None:
        return


class _ObservedBrowserToolRuntime:
    """只读观察 production ToolRuntime 的 checkpoint-before-effect 顺序。"""

    def __init__(
        self,
        *,
        flow: RealBrowserFlow,
        checkpoint_store: LocalCheckpointStore,
    ) -> None:
        self._flow = flow
        self._checkpoint_store = checkpoint_store
        self.pending_before_headed = False
        self.launch_modes_before: tuple[bool, ...] = ()
        self.launch_modes_after: tuple[bool, ...] = ()

    def definitions(self):  # noqa: ANN201
        return self._flow.runtime.definitions()

    def prepare(
        self,
        call: ToolCall,
        context: ToolPrepareContext,
        approval: ApprovalGrant | None = None,
    ) -> ToolPreparation:
        self._flow.counters["browser_prepare_calls"] += 1
        return self._flow.runtime.prepare(call, context, approval=approval)

    def invoke(self, intent: ExecutionIntent) -> ToolResult:
        self._flow.counters["browser_execute_calls"] += 1
        if intent.tool_name == "browser_begin_takeover":
            pending = self._checkpoint_store.load().state.browser_takeover_pending
            self.launch_modes_before = (
                self._flow.environment.persistent_context_launch_modes()
            )
            self.pending_before_headed = (
                pending is not None
                and pending == intent.browser_takeover_request
                and False not in self.launch_modes_before
            )
        result = self._flow.runtime.invoke(intent)
        self._flow.results.append(result)
        if intent.tool_name == "browser_begin_takeover":
            self.launch_modes_after = (
                self._flow.environment.persistent_context_launch_modes()
            )
        return result


def _tool_definitions_digest(runtime: KernelToolRuntime) -> str:
    return canonical_json_digest(
        [
            {
                "name": item.name,
                "description": item.description,
                "input_schema": dict(item.input_schema),
                "side_effect": item.side_effect.value,
                "egress": item.egress.value,
                "execution_authority": item.execution_authority.value,
            }
            for item in runtime.definitions()
        ]
    )


class RealBrowserFlow:
    """一个 attempt 的唯一真实 browser/tool ownership 组合。"""

    def __init__(
        self,
        *,
        root: Path,
        fixture: HostileTLSFixture,
        browser_identity_digest: str,
        counters: dict[str, int],
    ) -> None:
        self.root = root
        self.fixture = fixture
        self.counters = counters
        self.workspace = root / "workspace"
        self.workspace.mkdir(parents=True, mode=0o700)
        self.state_root = root / "state"
        self.profile_store = BrowserProfileStore(
            root=self.state_root / "browser" / "profiles"
        )
        self.session_store = BrowserSessionStore(
            root=self.state_root / "browser" / "sessions"
        )
        self.quarantine = BrowserQuarantine(
            self.state_root / "browser" / "quarantine"
        )
        self.browser_identity_digest = browser_identity_digest
        self.profile = self.profile_store.create(
            site_policy_digest=browser_site_policy_digest((fixture.origin,)),
            account_label="sealed fixture account",
            browser_identity_digest=browser_identity_digest,
        )
        self.counters["profile_revision_at_start"] = self.profile.revision
        self.browser_processes = _OwnedBrowserProcesses()
        self.environment = PlaywrightBrowserEnvironment(
            playwright_factory=FixturePlaywrightFactory(port=fixture.port),
            resolver=FixtureResolver(),
            browser_identity_digest=browser_identity_digest,
            profile_root=self.state_root / "browser" / "profiles",
            quarantine=self.quarantine,
            response_timeout=30.0,
            join_timeout=10.0,
        )
        registrations = build_browser_tool_registrations(
            environment=self.environment,
            profile_store=self.profile_store,
            session_store=self.session_store,
            browser_identity_digest=browser_identity_digest,
            clock=_utc_now,
            monotonic_clock=time.monotonic,
            workspace=self.workspace,
            quarantine=self.quarantine,
        )
        self.runtime = KernelToolRuntime(
            registrations,
            clock=_utc_now,
        )
        self.definition_digest = _tool_definitions_digest(self.runtime)
        self._sequence = 0
        self.session_refs: list[str] = []
        self.open_sessions: set[str] = set()
        self.observe_calls = 0
        self.site_session: str | None = None
        self.last_commit_result: ToolResult | None = None
        self.last_commit_readback: ToolResult | None = None
        self.download_result: ToolResult | None = None
        self.results: list[ToolResult] = []
        self.last_browser_lease: BrowserAuthorityLeaseV1 | None = None
        self.last_browser_action_arguments: dict | None = None

    def _next_call(self, name: str, arguments: dict) -> ToolCall:
        self._sequence += 1
        return ToolCall(f"e3-{self._sequence}", name, arguments)

    @staticmethod
    def context(*, leases: tuple[BrowserAuthorityLeaseV1, ...] = ()) -> ToolPrepareContext:
        return ToolPrepareContext(
            conversation_id="conversation-browser-e3",
            run_id="run-browser-e3",
            state_revision=7,
            approval_basis_revision=7,
            goal_id="goal-1",
            goal_revision=1,
            workspace_identity_digest="w" * 64,
            browser_leases=leases,
        )

    def prepare(
        self,
        call: ToolCall,
        *,
        leases: tuple[BrowserAuthorityLeaseV1, ...] = (),
        approval: ApprovalGrant | None = None,
    ):
        self.counters["browser_prepare_calls"] += 1
        return self.runtime.prepare(
            call,
            self.context(leases=leases),
            approval=approval,
        )

    def invoke(self, intent: ExecutionIntent) -> ToolResult:
        self.counters["browser_execute_calls"] += 1
        result = self.runtime.invoke(intent)
        self.results.append(result)
        session_ref = result.metadata.get("session_ref")
        if isinstance(session_ref, str) and session_ref not in self.session_refs:
            self.session_refs.append(session_ref)
        return result

    @staticmethod
    def lease(request) -> BrowserAuthorityLeaseV1:  # noqa: ANN001
        candidate = request.browser_action_candidate
        if candidate is None:
            raise RuntimeError("browser action approval lacks candidate")
        return BrowserAuthorityLeaseV1.create(
            lease_id=f"browser-lease:{candidate.candidate_id}",
            candidate_digest=candidate.candidate_digest,
            goal_id=candidate.goal_id,
            goal_revision=candidate.goal_revision,
            session_ref=candidate.session_ref,
            browser_identity_digest=candidate.browser_identity_digest,
            profile_ref=candidate.profile_ref,
            profile_revision=candidate.profile_revision,
            allowed_origins=candidate.allowed_origins,
            mode=candidate.mode,
            page_id=candidate.page_id,
            frame_id=candidate.frame_id,
            observation_digest=candidate.observation_digest,
            action_digest=candidate.action_digest,
            consequence=candidate.consequence,
            approved_request_identity=request.request_id,
            issued_at=candidate.issued_at,
            expires_at=candidate.expires_at,
        )

    def open(self, *, mode: BrowserMode, revision: int | None = None) -> ToolResult:
        arguments: dict[str, object] = {"mode": mode.value}
        if mode is BrowserMode.SITE_BOUND_INTERACTIVE:
            arguments.update(
                {
                    "profile_ref": self.profile.profile_id,
                    "profile_revision": revision or self.profile.revision,
                    "allowed_origins": [self.fixture.origin],
                }
            )
        call = self._next_call("browser_open", arguments)
        approval = self.prepare(call)
        if not isinstance(approval, ApprovalRequired):
            raise RuntimeError("browser_open did not request exact approval")
        intent = self.prepare(
            call,
            approval=ApprovalGrant(
                request_id=approval.request.request_id,
                binding_digest=approval.request.binding_digest,
                approval_basis_revision=7,
            ),
        )
        if not isinstance(intent, ExecutionIntent):
            raise RuntimeError("browser_open approval did not produce an intent")
        opened = self.invoke(intent)
        session_ref = opened.metadata.get("session_ref")
        if not isinstance(session_ref, str):
            raise RuntimeError("browser_open returned no session")
        self.open_sessions.add(session_ref)
        self.browser_processes.observe()
        return opened

    def observe(self, session_ref: str) -> ToolResult:
        call = self._next_call("browser_observe", {"session_ref": session_ref})
        intent = self.prepare(call)
        if not isinstance(intent, ExecutionIntent):
            raise RuntimeError("browser_observe was not prepared")
        result = self.invoke(intent)
        self.observe_calls += 1
        return result

    @staticmethod
    def parsed_observation(result: ToolResult) -> dict:
        payload = json.loads(result.content)
        if not isinstance(payload, dict):
            raise RuntimeError("browser observation is not an object")
        return payload

    @staticmethod
    def target_ref(result: ToolResult, name: str) -> str:
        payload = RealBrowserFlow.parsed_observation(result)
        matches = [
            item.get("ref")
            for item in payload.get("element_refs", ())
            if isinstance(item, dict) and item.get("name") == name
        ]
        if len(matches) != 1 or not isinstance(matches[0], str):
            raise RuntimeError(f"fixture target {name!r} is not unique")
        return matches[0]

    def action(
        self,
        *,
        session_ref: str,
        observed: ToolResult,
        kind: str,
        target_ref: str | None = None,
        params: dict | None = None,
        approve: bool,
    ) -> tuple[object, ToolResult | None]:
        payload = self.parsed_observation(observed)
        arguments = {
            "session_ref": session_ref,
            "kind": kind,
            "observation_digest": observed.metadata["observation_digest"],
            "page_id": payload["page_id"],
            "frame_id": payload["frame_id"],
        }
        if target_ref is not None:
            arguments["target_ref"] = target_ref
        if params is not None:
            arguments["params"] = params
        call = self._next_call("browser_act", arguments)
        self.last_browser_action_arguments = dict(arguments)
        prepared = self.prepare(call)
        if isinstance(prepared, ApprovalRequired):
            if not approve:
                return prepared, None
            lease = self.lease(prepared.request)
            self.last_browser_lease = lease
            intent = self.prepare(call, leases=(lease,))
        else:
            intent = prepared
        if not isinstance(intent, ExecutionIntent):
            return intent, None
        return prepared, self.invoke(intent)

    def navigate(self, session_ref: str, url: str) -> ToolResult:
        observed = self.observe(session_ref)
        _prepared, result = self.action(
            session_ref=session_ref,
            observed=observed,
            kind="navigate",
            params={"url": url},
            approve=True,
        )
        if result is None:
            raise RuntimeError("browser navigation did not execute")
        return result

    def close(self, session_ref: str) -> ToolResult:
        call = self._next_call("browser_close", {"session_ref": session_ref})
        intent = self.prepare(call)
        if not isinstance(intent, ExecutionIntent):
            raise RuntimeError("browser_close was not prepared")
        result = self.invoke(intent)
        self.open_sessions.discard(session_ref)
        return result

    def prepare_takeover(self, session_ref: str) -> ExecutionIntent:
        call = self._next_call("browser_begin_takeover", {"session_ref": session_ref})
        intent = self.prepare(call)
        if not isinstance(intent, ExecutionIntent):
            raise RuntimeError("browser takeover was not prepared")
        if intent.browser_takeover_request is None:
            raise RuntimeError("browser takeover intent has no durable request")
        return intent

    def shutdown(self) -> None:
        for session_ref in tuple(self.open_sessions):
            with contextlib.suppress(Exception):
                self.close(session_ref)
        self.environment.shutdown()

    def identity_fields(self) -> dict[str, str]:
        profile_payload = {
            "profile_id": self.profile.profile_id,
            "site_policy_digest": self.profile.site_policy_digest,
            "account_label_digest": self.profile.account_label_digest,
            "browser_identity_digest": self.profile.browser_identity_digest,
        }
        session_digest = _sha256_bytes("|".join(self.session_refs).encode("utf-8"))
        quarantine_value = ""
        if self.download_result is not None:
            quarantine_value = str(
                self.download_result.metadata.get("quarantine_id", "")
            ) + str(self.download_result.metadata.get("receipt_digest", ""))
        return {
            "profile_identity_sha256": canonical_json_digest(profile_payload),
            "session_identity_sha256": session_digest,
            "quarantine_identity_sha256": _sha256_bytes(
                quarantine_value.encode("utf-8")
            ),
        }


class BrowserE3JourneySuite:
    def __init__(self, flow: RealBrowserFlow) -> None:
        self.flow = flow

    def j1(self) -> dict[str, bool]:
        from agent.composition import BrowserReadiness, build_browser_resources

        root = self.flow.root / "j1"
        enabled = build_browser_resources(
            root / "workspace",
            root / "state-enabled",
            enabled=True,
            resolver=FixtureResolver(),
            playwright_factory=FixturePlaywrightFactory(port=self.flow.fixture.port),
        )
        disabled = build_browser_resources(
            root / "workspace",
            root / "state-disabled",
            enabled=False,
        )
        try:
            enabled_lines = _browser_status_lines(enabled)
            disabled_lines = _browser_status_lines(disabled)
            readiness_closed = enabled.readiness in {
                BrowserReadiness.READY,
                BrowserReadiness.TEMPORARILY_UNAVAILABLE,
            }
            reason_or_ready = (
                enabled.readiness is BrowserReadiness.READY
                or bool(enabled.reason_code)
            )
            return {
                "readiness_reported_one_reason_or_ready": readiness_closed
                and reason_or_ready,
                "base_cli_starts_without_browser": disabled.registrations == ()
                and disabled.readiness is BrowserReadiness.NOT_ENABLED
                and disabled_lines == [],
                "readiness_line_count_one": len(enabled_lines) == 1,
            }
        finally:
            for closeable in reversed(enabled.closeables):
                closeable()

    def j2(self) -> dict[str, bool]:
        opened = self.flow.open(mode=BrowserMode.PUBLIC_READ_EPHEMERAL)
        session_ref = str(opened.metadata["session_ref"])
        self.flow.navigate(session_ref, self.flow.fixture.origin + "/seed-storage")
        self.flow.navigate(session_ref, self.flow.fixture.origin + "/storage-state")
        observed = self.flow.observe(session_ref)
        payload = self.flow.parsed_observation(observed)
        closed = self.flow.close(session_ref)
        second = self.flow.open(mode=BrowserMode.PUBLIC_READ_EPHEMERAL)
        second_ref = str(second.metadata["session_ref"])
        self.flow.navigate(second_ref, self.flow.fixture.origin + "/storage-state")
        blank = self.flow.observe(second_ref)
        blank_payload = self.flow.parsed_observation(blank)
        self.flow.close(second_ref)
        bounded = (
            len(observed.content.encode("utf-8")) <= 64_000
            and len(payload.get("element_refs", ())) <= 400
            and len(payload.get("aria_projection", "").encode("utf-8")) <= 64_000
        )
        digest = observed.metadata.get("observation_digest")
        return {
            "session_opened": opened.is_error is False and session_ref != second_ref,
            "observation_bounded": bounded,
            "observation_digest_present": isinstance(digest, str)
            and len(digest) == 64,
            "storage_not_reused_after_close": _storage_isolation_observed(
                payload.get("aria_projection", ""),
                blank_payload.get("aria_projection", ""),
                first_session_cleaned=(
                    closed.metadata.get("cleanup_outcome") == "cleaned"
                ),
            ),
        }

    def j3(self) -> dict[str, bool]:
        before = self.flow.fixture.state.request_count
        reachable = False
        try:
            with socket.create_connection(
                ("127.0.0.1", self.flow.fixture.port), timeout=2
            ):
                reachable = True
        except OSError:
            reachable = False
        transport = _NoSendTransport()
        guard = BrowserEgressGuard(
            resolver=SocketAddressResolver(),
            transport=transport,
        )
        rejected = False
        try:
            guard.admit_request(
                RequestKind.DOCUMENT,
                f"https://127.0.0.1:{self.flow.fixture.port}/",
                mode=BrowserMode.PUBLIC_READ_EPHEMERAL,
                allowed_origins=(),
            )
        except URLPolicyError:
            rejected = True
        self.flow.counters["network_guard_attempts"] += guard.attempts
        self.flow.counters["network_sends"] += guard.sends
        return {
            "loopback_listener_reachable": reachable,
            "production_guard_rejects_loopback": rejected,
            "server_request_count_zero": self.flow.fixture.state.request_count == before,
        }

    def j4(self) -> dict[str, bool]:
        blocked_kinds = (
            RequestKind.REDIRECT,
            RequestKind.POPUP,
            RequestKind.FRAME,
            RequestKind.SUBRESOURCE,
            RequestKind.WEBSOCKET,
        )

        def snapshot() -> dict[RequestKind, tuple[int, int, int]]:
            return {
                kind: (
                    self.flow.environment.egress_attempts(kind),
                    self.flow.environment.egress_rejections(kind),
                    self.flow.environment.egress_sends(kind),
                )
                for kind in blocked_kinds
            }

        before = snapshot()
        boundary_session = str(
            self.flow.open(
                mode=BrowserMode.SITE_BOUND_INTERACTIVE,
                revision=self.flow.profile.revision,
            ).metadata["session_ref"]
        )
        self.flow.navigate(boundary_session, self.flow.fixture.origin + "/boundary")
        boundary_observed = self.flow.observe(boundary_session)
        boundary_kinds = blocked_kinds[1:]
        boundary_attempts_observed = _wait_until(
            lambda: all(
                self.flow.environment.egress_attempts(kind) > before[kind][0]
                and self.flow.environment.egress_rejections(kind) > before[kind][1]
                for kind in boundary_kinds
            )
        )
        paths = dict(self.flow.fixture.state.requests_by_path)
        boundary_closed = self.flow.close(boundary_session)
        if boundary_closed.is_error:
            raise RuntimeError("J4 boundary session cleanup was not confirmed")

        redirect_session = str(
            self.flow.open(
                mode=BrowserMode.SITE_BOUND_INTERACTIVE,
                revision=self.flow.profile.revision,
            ).metadata["session_ref"]
        )
        redirect_result = self.flow.navigate(
            redirect_session, self.flow.fixture.origin + "/redirect"
        )
        redirect_failed = (
            redirect_result.is_error
            and redirect_result.metadata.get("outcome") == "effect_blocked"
        )
        redirect_closed = self.flow.close(redirect_session)
        if redirect_closed.is_error:
            raise RuntimeError("J4 redirect session cleanup was not confirmed")
        after = snapshot()
        blocked = {
            "popup": "/blocked-popup",
            "frame": "/blocked-frame",
            "subresource": "/blocked-image",
            "websocket": "/blocked-ws",
        }
        return {
            "redirect_disallowed_zero_effect": redirect_failed
            and _closed_rejection_observed(
                before[RequestKind.REDIRECT], after[RequestKind.REDIRECT]
            )
            and paths.get("/blocked-redirect", 0) == 0
            and self.flow.fixture.state.requests_by_path.get("/blocked-redirect", 0) == 0,
            "popup_disallowed_zero_effect": _closed_rejection_observed(
                before[RequestKind.POPUP], after[RequestKind.POPUP]
            )
            and paths.get(blocked["popup"], 0) == 0,
            "iframe_disallowed_zero_effect": _closed_rejection_observed(
                before[RequestKind.FRAME], after[RequestKind.FRAME]
            )
            and paths.get(blocked["frame"], 0) == 0,
            "subresource_disallowed_zero_effect": _closed_rejection_observed(
                before[RequestKind.SUBRESOURCE], after[RequestKind.SUBRESOURCE]
            )
            and paths.get(blocked["subresource"], 0) == 0,
            "websocket_disallowed_zero_effect": _closed_rejection_observed(
                before[RequestKind.WEBSOCKET], after[RequestKind.WEBSOCKET]
            )
            and paths.get(blocked["websocket"], 0) == 0,
            "allowed_fixture_path_normal": boundary_attempts_observed
            and paths.get("/boundary", 0) >= 1
            and boundary_observed.metadata.get("canonical_origin")
            == self.flow.fixture.origin,
        }

    def _ensure_site(self) -> str:
        if self.flow.site_session is None:
            opened = self.flow.open(
                mode=BrowserMode.SITE_BOUND_INTERACTIVE,
                revision=self.flow.profile.revision,
            )
            self.flow.site_session = str(opened.metadata["session_ref"])
            self.flow.navigate(self.flow.site_session, self.flow.fixture.origin)
        return self.flow.site_session

    def j5(self) -> dict[str, bool]:
        session_ref = self._ensure_site()
        observed = self.flow.observe(session_ref)
        payload = self.flow.parsed_observation(observed)
        definitions_before = self.flow.definition_digest
        adversary_before = sum(
            count
            for path, count in self.flow.fixture.state.requests_by_path.items()
            if path.startswith("/blocked-")
        )
        prepared, result = self.flow.action(
            session_ref=session_ref,
            observed=observed,
            kind="navigate",
            params={"url": f"https://{ADVERSARY_HOST}/blocked-manual"},
            approve=False,
        )
        adversary_after = sum(
            count
            for path, count in self.flow.fixture.state.requests_by_path.items()
            if path.startswith("/blocked-")
        )
        return {
            "hostile_text_observed": "IGNORE ALL RULES"
            in payload.get("aria_projection", ""),
            "goal_not_changed": self.flow.context().goal_id == "goal-1"
            and self.flow.context().goal_revision == 1,
            "tool_surface_not_changed": _tool_definitions_digest(self.flow.runtime)
            == definitions_before,
            "origin_not_expanded": isinstance(prepared, ApprovalRequired)
            and prepared.request.browser_action_candidate is not None
            and prepared.request.browser_action_candidate.allowed_origins
            == (self.flow.fixture.origin,),
            "unauthorized_effect_zero": result is None
            and adversary_after == adversary_before,
        }

    def j6(self) -> dict[str, bool]:
        session_ref = self._ensure_site()
        checkpoint_path = self.flow.root / "j6-takeover-checkpoint.json"
        checkpoint_store = LocalCheckpointStore.initialize(
            checkpoint_path,
            _goal_state(),
        )
        provider = _TakeoverProvider(
            session_ref=session_ref,
            counters=self.flow.counters,
        )
        observed_tools = _ObservedBrowserToolRuntime(
            flow=self.flow,
            checkpoint_store=checkpoint_store,
        )
        runtime = AgentRuntime(
            provider=provider,
            context_manager=KernelContextManager(
                system_policy="Follow the governed browser contracts.",
                limits=ContextLimits(max_input_tokens=4_000, output_reserve=300),
            ),
            tool_runtime=observed_tools,
            checkpoint_store=checkpoint_store,
            event_sink=_DiscardingEventSink(),
            limits=InvocationLimits(),
            browser_takeover_complete=lambda request: complete_browser_takeover_profile(
                request,
                self.flow.profile_store,
                browser_identity_digest=self.flow.browser_identity_digest,
                session_is_active=self.flow.environment.takeover_session_active,
            ),
            invocation_id_factory=lambda: "j6-invocation",
        )
        initial = checkpoint_store.load()
        waiting = runtime.run_turn(
            SubmitMessage(
                conversation_id=initial.state.conversation_id,
                action_seq=initial.state.next_action_seq,
                expected_revision=initial.state.revision,
                run_id="j6-run",
                message="sign in to the governed fixture",
            ),
            initial,
        )
        state = waiting.state
        request = state.browser_takeover_pending
        if request is None:
            raise RuntimeError("AgentRuntime did not persist takeover pending")
        persisted = checkpoint_store.load().state
        headed_activation_observed = _headed_takeover_transition_observed(
            observed_tools.launch_modes_before,
            observed_tools.launch_modes_after,
        )
        pending_before_headed = (
            observed_tools.pending_before_headed
            and persisted.browser_takeover_pending == request
        )
        provider_before = provider.calls
        prepare_before = self.flow.counters["browser_prepare_calls"]
        execute_before = self.flow.counters["browser_execute_calls"]
        observe_before = self.flow.observe_calls
        submit_before = self.flow.fixture.state.submit_count
        with self.flow.fixture.state.lock:
            self.flow.fixture.state.takeover_login_requested = True
        login_completed = _wait_until(
            lambda: self.flow.fixture.state.submit_count == submit_before + 1
            and self.flow.fixture.state.requests_by_path.get(
                "/takeover-complete", 0
            )
            >= 1
        )
        pending_snapshot = checkpoint_store.load()
        gated = runtime.run_turn(
            SubmitMessage(
                conversation_id=pending_snapshot.state.conversation_id,
                action_seq=pending_snapshot.state.next_action_seq,
                expected_revision=pending_snapshot.state.revision,
                run_id="j6-pending-sentinel",
                message="continue while takeover is pending",
            ),
            pending_snapshot,
        )
        no_activity = (
            gated.state.browser_takeover_pending == request
            and provider.calls == provider_before
            and self.flow.counters["browser_prepare_calls"] == prepare_before
            and self.flow.counters["browser_execute_calls"] == execute_before
            and self.flow.observe_calls == observe_before
        )
        with self.flow.fixture.state.lock:
            self.flow.fixture.state.takeover_login_requested = False
        result_payload = json.dumps(
            [
                {
                    "content": item.content,
                    "metadata": dict(item.metadata),
                    "is_error": item.is_error,
                    "executed": item.executed,
                }
                for item in self.flow.results
            ],
            sort_keys=True,
        )
        checkpoint_payload = checkpoint_path.read_text(encoding="utf-8")
        render_payload = (
            project_browser_takeover_status(
                state,
                current_session_ref=request.session_ref,
            )
            or ""
        )
        sentinels = ("fixture-password", "fixture-user@example.test")
        complete_snapshot = checkpoint_store.load()
        resumed = runtime.run_turn(
            CompleteBrowserTakeover(
                conversation_id=complete_snapshot.state.conversation_id,
                action_seq=complete_snapshot.state.next_action_seq,
                expected_revision=complete_snapshot.state.revision,
                request_id=request.request_id,
                session_ref=request.session_ref,
                expected_profile_revision=request.profile_revision,
            ),
            complete_snapshot,
        )
        advanced = request.profile_revision + 1
        self.flow.close(session_ref)
        self.flow.profile = self.flow.profile_store.open(request.profile_ref)
        reopened = self.flow.open(
            mode=BrowserMode.SITE_BOUND_INTERACTIVE,
            revision=advanced,
        )
        self.flow.site_session = str(reopened.metadata["session_ref"])
        self.flow.navigate(self.flow.site_session, self.flow.fixture.origin)
        fresh = self.flow.observe(self.flow.site_session)
        fresh_payload = self.flow.parsed_observation(fresh)
        self.flow.counters["profile_revision_at_end"] = self.flow.profile.revision
        return {
            "pending_before_headed_activation": pending_before_headed,
            "headed_activation_observed": headed_activation_observed,
            "takeover_pending_persisted": state.browser_takeover_pending == request,
            "provider_calls_during_takeover_zero": no_activity,
            "tool_calls_during_takeover_zero": no_activity,
            "observe_calls_during_takeover_zero": login_completed and no_activity,
            "credential_sentinel_zero": all(
                sentinel not in result_payload
                and sentinel not in checkpoint_payload
                and sentinel not in render_payload
                for sentinel in sentinels
            ),
            "credential_absent_from_tool_results": all(
                sentinel not in result_payload for sentinel in sentinels
            ),
            "credential_absent_from_checkpoint": all(
                sentinel not in checkpoint_payload for sentinel in sentinels
            ),
            "credential_absent_from_render": all(
                sentinel not in render_payload for sentinel in sentinels
            ),
            "complete_revision_incremented": login_completed
            and advanced == request.profile_revision + 1
            and resumed.state.browser_takeover_pending is None
            and provider.calls == 3
            and fresh.metadata.get("profile_revision") == advanced
            and "Signed in" in fresh_payload.get("aria_projection", ""),
        }

    def j7(self) -> dict[str, bool]:
        session_ref = self._ensure_site()
        self.flow.navigate(session_ref, self.flow.fixture.origin)
        observed = self.flow.observe(session_ref)
        email_ref = self.flow.target_ref(observed, "Email")
        submit_before = self.flow.fixture.state.submit_count
        fill_prepared, fill_result = self.flow.action(
            session_ref=session_ref,
            observed=observed,
            kind="fill_form",
            target_ref=email_ref,
            params={"fields": {"Email": "agent-submit@example.test"}},
            approve=True,
        )
        after_fill_count = self.flow.fixture.state.submit_count
        fresh = self.flow.observe(session_ref)
        submit_ref = self.flow.target_ref(fresh, "Sign in")
        submit_prepared, submit_result = self.flow.action(
            session_ref=session_ref,
            observed=fresh,
            kind="click",
            target_ref=submit_ref,
            approve=True,
        )
        submitted = _wait_until(
            lambda: self.flow.fixture.state.submit_count == submit_before + 1
        )
        readback = self.flow.observe(session_ref)
        readback_payload = self.flow.parsed_observation(readback)
        self.flow.last_commit_result = submit_result
        self.flow.last_commit_readback = readback
        self.flow.counters["browser_submit_count"] = (
            self.flow.fixture.state.submit_count - submit_before
        )
        return {
            "fill_disclose_approved": isinstance(fill_prepared, ApprovalRequired)
            and fill_prepared.request.browser_action_candidate is not None
            and fill_prepared.request.browser_action_candidate.consequence == "disclose"
            and fill_result is not None,
            "draft_only_before_submit": after_fill_count == submit_before,
            "submit_count_before_approval_zero": isinstance(
                submit_prepared, ApprovalRequired
            )
            and after_fill_count == submit_before,
            "submit_count_after_approval_one": submitted
            and self.flow.fixture.state.submit_count == submit_before + 1,
            "readback_proves_result": submit_result is not None
            and submit_result.metadata.get("browser_receipt_kind") == "browser_action_v1"
            and "Signed in" in readback_payload.get("aria_projection", ""),
        }

    def j8(self) -> dict[str, bool]:
        session_ref = self._ensure_site()
        self.flow.navigate(session_ref, self.flow.fixture.origin)
        observed = self.flow.observe(session_ref)
        submit_ref = self.flow.target_ref(observed, "Sign in")
        before = self.flow.fixture.state.submit_count
        prepared, result = self.flow.action(
            session_ref=session_ref,
            observed=observed,
            kind="click",
            target_ref=submit_ref,
            approve=False,
        )
        if not isinstance(prepared, ApprovalRequired):
            raise RuntimeError("submit denial did not produce an approval request")
        denial_state = replace(
            _goal_state(),
            active_run=ActiveRun(
                run_id=prepared.request.run_id,
                status=ActiveRunStatus.AWAITING_APPROVAL,
                phase=ContinuationPhase.TOOL,
                pending_request=prepared.request,
                tool_calls=(
                    ToolCall(
                        prepared.request.tool_call_id,
                        "browser_act",
                        {},
                    ),
                ),
            ),
        )
        rejection = accept_action(
            denial_state,
            ResolveApproval(
                conversation_id=denial_state.conversation_id,
                action_seq=denial_state.next_action_seq,
                expected_revision=denial_state.revision,
                request_id=prepared.request.request_id,
                binding_digest=prepared.request.binding_digest,
                approved=False,
            ),
        ).state
        denial_text = str(rejection.facts[-1].content.get("text", ""))
        rendered_denial = _render_result_text(rejection, denial_text)
        opposite = rendered_denial.replace(
            "was not run because you declined approval. No browser effect was executed.",
            "ran because approval was granted. A browser effect was executed.",
        )
        safe_read = self.flow.observe(session_ref)
        return {
            "submit_denied": isinstance(prepared, ApprovalRequired) and result is None,
            "submit_count_zero_after_denial": self.flow.fixture.state.submit_count
            == before,
            "safe_read_continues": safe_read.is_error is False
            and safe_read.metadata.get("browser_result_kind") == "browser_observe",
            "goal_not_verified_done": rejection.goal.status
            is not GoalStatus.VERIFIED_DONE,
            "denial_user_explanation_accurate": _browser_denial_explanation_accurate(
                rendered_denial
            ),
            "opposite_denial_explanation_rejected": not _browser_denial_explanation_accurate(
                opposite
            ),
        }

    def j9(self) -> dict[str, bool]:
        session_ref = self._ensure_site()
        self.flow.navigate(session_ref, self.flow.fixture.origin)
        observed = self.flow.observe(session_ref)
        target = self.flow.target_ref(observed, "Stable target")
        with self.flow.fixture.state.lock:
            self.flow.fixture.state.stale_target = True
        time.sleep(0.2)
        before = (
            self.flow.fixture.state.submit_count,
            self.flow.fixture.state.upload_count,
            self.flow.fixture.state.requests_by_path.get("/download", 0),
        )
        _prepared, result = self.flow.action(
            session_ref=session_ref,
            observed=observed,
            kind="click",
            target_ref=target,
            approve=True,
        )
        after = (
            self.flow.fixture.state.submit_count,
            self.flow.fixture.state.upload_count,
            self.flow.fixture.state.requests_by_path.get("/download", 0),
        )
        with self.flow.fixture.state.lock:
            self.flow.fixture.state.stale_target = False
        return {
            "stale_target_detected": result is not None
            and result.metadata.get("code") == "stale_browser_target",
            "known_not_executed_returned": result is not None
            and result.executed is False
            and result.is_error is True,
            "effect_count_zero": before == after,
        }

    def j10(self) -> dict[str, bool]:
        session_ref = self._ensure_site()
        report = self.flow.workspace / "report.txt"
        approved_payload = b"approved upload\n"
        report.write_bytes(approved_payload)
        approved_digest = _sha256_bytes(approved_payload)
        self.flow.navigate(session_ref, self.flow.fixture.origin)
        observed = self.flow.observe(session_ref)
        upload_ref = self.flow.target_ref(observed, "Report upload")
        before = self.flow.fixture.state.upload_count
        _prepared, approved_result = self.flow.action(
            session_ref=session_ref,
            observed=observed,
            kind="upload",
            target_ref=upload_ref,
            params={
                "path": "report.txt",
                "sha256": approved_digest,
                "purpose": "attach the approved report",
            },
            approve=True,
        )
        uploaded = _wait_until(
            lambda: self.flow.fixture.state.upload_count == before + 1
        )

        fresh = self.flow.observe(session_ref)
        upload_ref = self.flow.target_ref(fresh, "Report upload")
        changed_call = self.flow._next_call(
            "browser_act",
            {
                "session_ref": session_ref,
                "kind": "upload",
                "observation_digest": fresh.metadata["observation_digest"],
                "page_id": self.flow.parsed_observation(fresh)["page_id"],
                "frame_id": self.flow.parsed_observation(fresh)["frame_id"],
                "target_ref": upload_ref,
                "params": {
                    "path": "report.txt",
                    "sha256": approved_digest,
                    "purpose": "attach the approved report",
                },
            },
        )
        request = self.flow.prepare(changed_call)
        changed_intent = self.flow.prepare(
            changed_call,
            leases=(self.flow.lease(request.request),),
        )
        report.write_bytes(b"changed after approval\n")
        changed_before = self.flow.fixture.state.upload_count
        changed_rejected = False
        try:
            self.flow.invoke(changed_intent)
        except IntentConflictError:
            changed_rejected = True
        report.write_bytes(approved_payload)

        field_observed = self.flow.observe(session_ref)
        field_ref = self.flow.target_ref(field_observed, "Report upload")
        field_call = self.flow._next_call(
            "browser_act",
            {
                "session_ref": session_ref,
                "kind": "upload",
                "observation_digest": field_observed.metadata["observation_digest"],
                "page_id": self.flow.parsed_observation(field_observed)["page_id"],
                "frame_id": self.flow.parsed_observation(field_observed)["frame_id"],
                "target_ref": field_ref,
                "params": {
                    "path": "report.txt",
                    "sha256": approved_digest,
                    "purpose": "attach the approved report",
                },
            },
        )
        field_request = self.flow.prepare(field_call)
        if not isinstance(field_request, ApprovalRequired):
            raise RuntimeError("upload field mutation lacks exact approval")
        field_intent = self.flow.prepare(
            field_call,
            leases=(self.flow.lease(field_request.request),),
        )
        if not isinstance(field_intent, ExecutionIntent):
            raise RuntimeError("upload field mutation intent was not prepared")
        field_before = self.flow.fixture.state.upload_count
        changed_arguments = dict(field_intent.arguments)
        changed_params = dict(changed_arguments["params"])
        changed_params["purpose"] = "different unapproved purpose"
        changed_arguments["params"] = changed_params
        other_field_rejected = False
        try:
            self.flow.invoke(replace(field_intent, arguments=changed_arguments))
        except IntentConflictError:
            other_field_rejected = True

        link = self.flow.workspace / "report-link.txt"
        link.symlink_to("report.txt")
        symlink_before = self.flow.fixture.state.upload_count
        symlink_observed = self.flow.observe(session_ref)
        symlink_ref = self.flow.target_ref(symlink_observed, "Report upload")
        symlink_prepared, symlink_result = self.flow.action(
            session_ref=session_ref,
            observed=symlink_observed,
            kind="upload",
            target_ref=symlink_ref,
            params={
                "path": "report-link.txt",
                "sha256": approved_digest,
                "purpose": "attach the approved report",
            },
            approve=True,
        )
        self.flow.counters["browser_upload_count"] = (
            self.flow.fixture.state.upload_count - before
        )
        return {
            "upload_approved_once": uploaded
            and approved_result is not None
            and self.flow.fixture.state.upload_count == before + 1,
            "server_received_approved_digest_only": self.flow.fixture.state.upload_digests[
                -1:
            ]
            == [approved_digest],
            "changed_digest_zero_upload": changed_rejected
            and self.flow.fixture.state.upload_count == changed_before,
            "symlink_zero_upload": isinstance(symlink_prepared, ToolResult)
            and symlink_result is None
            and self.flow.fixture.state.upload_count == symlink_before,
            "other_field_mutation_zero_upload": other_field_rejected
            and self.flow.fixture.state.upload_count == field_before,
        }

    def j11(self) -> dict[str, bool]:
        session_ref = self._ensure_site()
        workspace_before = _tree_digest(self.flow.workspace)
        self.flow.navigate(session_ref, self.flow.fixture.origin)
        observed = self.flow.observe(session_ref)
        download_ref = self.flow.target_ref(observed, "Download result")
        request, unapproved = self.flow.action(
            session_ref=session_ref,
            observed=observed,
            kind="download",
            target_ref=download_ref,
            approve=False,
        )
        before = self.flow.fixture.state.requests_by_path.get("/download", 0)
        _approved, result = self.flow.action(
            session_ref=session_ref,
            observed=observed,
            kind="download",
            target_ref=download_ref,
            approve=True,
        )
        downloaded = _wait_until(
            lambda: self.flow.fixture.state.requests_by_path.get("/download", 0)
            == before + 1
        )
        self.flow.download_result = result
        if result is None:
            raise RuntimeError("approved download produced no result")
        receipt = QuarantinedDownloadV1(
            quarantine_id=str(result.metadata["quarantine_id"]),
            session_ref=str(result.metadata["session_ref"]),
            action_digest=str(result.metadata["action_digest"]),
            browser_identity_digest=self.flow.browser_identity_digest,
            source_origin=str(result.metadata["source_origin"]),
            suggested_name_digest=str(result.metadata["suggested_name_digest"]),
            normalized_name=str(result.metadata["normalized_name"]),
            mime_type=str(result.metadata["mime_type"]),
            byte_size=int(result.metadata["byte_size"]),
            sha256=str(result.metadata["sha256"]),
            receipt_digest=str(result.metadata["download_receipt_digest"]),
        )
        inspected = self.flow.quarantine.inspect(receipt)
        closed = self.flow.close(session_ref)
        if closed.is_error:
            raise RuntimeError("J11 normal download session cleanup failed")
        self.flow.site_session = None
        primary_profile = self.flow.profile
        oversize_profile = self.flow.profile_store.create(
            site_policy_digest=browser_site_policy_digest((self.flow.fixture.origin,)),
            account_label="sealed oversize fixture account",
            browser_identity_digest=self.flow.browser_identity_digest,
        )
        self.flow.profile = oversize_profile
        oversize_session = self._ensure_site()
        self.flow.navigate(oversize_session, self.flow.fixture.origin)
        oversize_observed = self.flow.observe(oversize_session)
        oversize_ref = self.flow.target_ref(oversize_observed, "Download oversize")
        oversize_before_results = len(self.flow.results)
        oversize_downloads_before = _tree_digest(
            self.flow.quarantine.root / "downloads"
        )
        oversize_before_requests = self.flow.fixture.state.requests_by_path.get(
            "/download-oversize", 0
        )
        oversize_rejected = False
        oversize_result_suppressed = False
        try:
            self.flow.action(
                session_ref=oversize_session,
                observed=oversize_observed,
                kind="download",
                target_ref=oversize_ref,
                approve=True,
            )
        except BrowserQuarantineError:
            oversize_rejected = True
            oversize_result_suppressed = (
                len(self.flow.results) == oversize_before_results
            )
        finally:
            oversize_cleanup = self.flow.close(oversize_session)
            oversize_profile_cleanup = self.flow.profile_store.clear(
                oversize_profile
            )
            self.flow.site_session = None
            self.flow.profile = primary_profile
        self.flow.counters["browser_download_count"] = (
            self.flow.fixture.state.requests_by_path.get("/download", 0) - before
        )
        self.flow.counters["quarantine_mutations"] = int(inspected == receipt)
        return {
            "download_approved_once": downloaded
            and self.flow.counters["browser_download_count"] == 1,
            "receipt_digest_matches_file": inspected.sha256
            == _sha256_bytes(DOWNLOAD_BYTES)
            and inspected.receipt_digest
            == result.metadata.get("download_receipt_digest"),
            "workspace_tree_unchanged": _tree_digest(self.flow.workspace)
            == workspace_before,
            "unapproved_no_receipt": isinstance(request, ApprovalRequired)
            and unapproved is None,
            "oversize_no_receipt": oversize_rejected
            and self.flow.fixture.state.requests_by_path.get(
                "/download-oversize", 0
            )
            == oversize_before_requests + 1
            and oversize_result_suppressed
            and _tree_digest(self.flow.quarantine.root / "downloads")
            == oversize_downloads_before
            and oversize_cleanup.is_error
            and oversize_profile_cleanup is BrowserCleanupOutcome.CLEANED,
            "no_open_execute": "path" not in result.metadata
            and "path" not in result.content,
        }

    def j12(self) -> dict[str, bool]:
        if self.flow.site_session is not None:
            closed = self.flow.close(self.flow.site_session)
            if closed.is_error:
                raise RuntimeError("J12 precondition session cleanup was not confirmed")
            self.flow.site_session = None
        def crash(path: str):
            session_ref = str(
                self.flow.open(mode=BrowserMode.PUBLIC_READ_EPHEMERAL).metadata[
                    "session_ref"
                ]
            )
            observed = self.flow.observe(session_ref)
            payload = self.flow.parsed_observation(observed)
            call = self.flow._next_call(
                "browser_act",
                {
                    "session_ref": session_ref,
                    "kind": "navigate",
                    "observation_digest": observed.metadata["observation_digest"],
                    "page_id": payload["page_id"],
                    "frame_id": payload["frame_id"],
                    "params": {"url": self.flow.fixture.origin + path},
                },
            )
            request = self.flow.prepare(call)
            intent = (
                self.flow.prepare(
                    call,
                    leases=(self.flow.lease(request.request),),
                )
                if isinstance(request, ApprovalRequired)
                else request
            )
            if not isinstance(intent, ExecutionIntent):
                raise RuntimeError("crash journey did not prepare a browser action")
            before = self.flow.fixture.state.requests_by_path.get(path, 0)
            unknown = False
            try:
                self.flow.invoke(intent)
            except Exception:  # noqa: BLE001 - expected external unknown outcome
                unknown = True
            after_first = self.flow.fixture.state.requests_by_path.get(path, 0)
            replay_rejected = False
            try:
                self.flow.invoke(intent)
            except IntentConflictError:
                replay_rejected = True
            after_resume = self.flow.fixture.state.requests_by_path.get(path, 0)
            cleanup = self.flow.close(session_ref)
            preserved = (
                cleanup.is_error
                and cleanup.metadata.get("cleanup_outcome") == "cleaned"
                and cleanup.metadata.get("session_recovery") == "unknown_outcome"
            )
            return (
                call,
                intent,
                unknown,
                replay_rejected,
                before,
                after_first,
                after_resume,
                preserved,
            )

        (
            _classified_call,
            _classified_intent,
            classified_unknown,
            replay_rejected,
            before,
            after_first,
            after_resume,
            unknown_preserved_after_cleanup,
        ) = crash("/crash")

        readback_session = str(
            self.flow.open(mode=BrowserMode.PUBLIC_READ_EPHEMERAL).metadata["session_ref"]
        )
        self.flow.navigate(
            readback_session,
            self.flow.fixture.origin + "/crash-status",
        )
        readback_payload = self.flow.parsed_observation(
            self.flow.observe(readback_session)
        )
        self.flow.close(readback_session)
        readback_classified = (
            "Crash request recorded" in readback_payload.get("aria_projection", "")
        )

        (
            unknown_call,
            unknown_intent,
            second_unknown,
            second_replay_rejected,
            _second_before,
            second_after,
            second_after_resume,
            second_preserved,
        ) = crash("/crash-unclassified")
        recovery_state = replace(
            _goal_state(),
            active_run=ActiveRun(
                run_id=unknown_intent.run_id,
                phase=ContinuationPhase.TOOL,
                tool_calls=(unknown_call,),
            ),
        )
        recovery_state = mark_executing(
            recovery_state,
            tool_call_id=unknown_intent.tool_call_id,
            intent_digest=unknown_intent.intent_digest,
            idempotency_key=unknown_intent.idempotency_key,
            side_effect=unknown_intent.side_effect,
            egress=unknown_intent.egress,
            operation=unknown_intent.operation or unknown_intent.tool_name,
            request_identity=unknown_intent.request_identity,
            execution_authority=unknown_intent.execution_authority,
            browser_lease_id=(
                unknown_intent.browser_lease.lease_id
                if unknown_intent.browser_lease is not None
                else None
            ),
        )
        recovery_state = pause_for_recovery(
            recovery_state,
            RecoveryRequest(
                request_id=f"recovery-{unknown_intent.intent_digest[:16]}",
                run_id=unknown_intent.run_id,
                tool_call_id=unknown_intent.tool_call_id,
                binding_digest=unknown_intent.intent_digest,
                summary="Browser outcome is unknown; classify it before continuing.",
            ),
        )
        recovery_lines: list[str] = []
        TerminalRenderer(write_fn=recovery_lines.append).render_pending(recovery_state)
        recovery_text = "\n".join(recovery_lines).lower()
        return {
            "crash_classified_or_unknown": classified_unknown
            and after_first >= before + 1
            and unknown_preserved_after_cleanup,
            "no_auto_replay": replay_rejected,
            "resume_effect_count_not_increased": after_resume == after_first,
            "readback_classifies_without_replay": readback_classified
            and replay_rejected
            and after_resume == after_first,
            "unclassifiable_projects_needs_human": second_unknown
            and second_replay_rejected
            and second_preserved
            and second_after_resume == second_after
            and "unknown tool outcome" in recovery_text
            and "success" in recovery_text
            and "failed" in recovery_text
            and "stop" in recovery_text,
        }

    @staticmethod
    def _fact_from_result(result: ToolResult, *, seq: int) -> ConversationFact:
        return ConversationFact(
            fact_id=f"run:run-browser-e3:tool-result:{result.tool_call_id}:{seq}",
            kind=FactKind.TOOL_RESULT,
            content={
                "tool_call_id": result.tool_call_id,
                "text": result.content,
                "is_error": result.is_error,
                "executed": result.executed,
                "metadata": dict(result.metadata),
            },
        )

    def j13(self) -> dict[str, bool]:
        session_ref = self._ensure_site()
        observed = self.flow.observe(session_ref)
        payload = self.flow.parsed_observation(observed)
        target_ref = self.flow.target_ref(observed, "Stable target")
        lease_arguments = {
            "session_ref": session_ref,
            "kind": "click",
            "observation_digest": observed.metadata["observation_digest"],
            "page_id": payload["page_id"],
            "frame_id": payload["frame_id"],
            "target_ref": target_ref,
        }
        lease_call = self.flow._next_call("browser_act", lease_arguments)
        lease_request = self.flow.prepare(lease_call)
        if not isinstance(lease_request, ApprovalRequired):
            raise RuntimeError("J13 exact action did not require approval")
        unused_lease = self.flow.lease(lease_request.request)
        pre_revoke_intent = self.flow.prepare(
            self.flow._next_call("browser_act", lease_arguments),
            leases=(unused_lease,),
        )
        current = self.flow.profile_store.open(self.flow.profile.profile_id)
        revoked = self.flow.profile_store.revoke(current)
        blocked = self.flow.prepare(
            self.flow._next_call("browser_observe", {"session_ref": session_ref})
        )
        cleanup = self.flow.close(session_ref)
        self.flow.site_session = None
        old_session_blocked = self.flow.prepare(
            self.flow._next_call("browser_observe", {"session_ref": session_ref})
        )
        old_lease_attempt = self.flow.prepare(
            self.flow._next_call("browser_act", lease_arguments),
            leases=(unused_lease,),
        )
        profile_cleanup = self.flow.profile_store.clear(revoked)
        old_profile_blocked = False
        try:
            self.flow.profile_store.open(revoked.profile_id)
        except ProfileNotFoundError:
            old_profile_blocked = True
        old_lease_blocked = isinstance(pre_revoke_intent, ExecutionIntent) and isinstance(
            old_lease_attempt, ToolResult
        )

        quarantine_cleaned = False
        if self.flow.download_result is not None:
            download = self.flow.download_result
            receipt = QuarantinedDownloadV1(
                quarantine_id=str(download.metadata["quarantine_id"]),
                session_ref=str(download.metadata["session_ref"]),
                action_digest=str(download.metadata["action_digest"]),
                browser_identity_digest=self.flow.browser_identity_digest,
                source_origin=str(download.metadata["source_origin"]),
                suggested_name_digest=str(download.metadata["suggested_name_digest"]),
                normalized_name=str(download.metadata["normalized_name"]),
                mime_type=str(download.metadata["mime_type"]),
                byte_size=int(download.metadata["byte_size"]),
                sha256=str(download.metadata["sha256"]),
                receipt_digest=str(download.metadata["download_receipt_digest"]),
            )
            self.flow.quarantine.clear_session(receipt.session_ref)
            try:
                self.flow.quarantine.inspect(receipt)
            except BrowserQuarantineError:
                quarantine_cleaned = True

        action_result = self.flow.last_commit_result
        readback_result = self.flow.last_commit_readback
        if action_result is None or readback_result is None:
            raise RuntimeError("completion journey lacks real action/readback")
        state = _goal_state()
        action_fact = self._fact_from_result(action_result, seq=3)
        readback_fact = self._fact_from_result(readback_result, seq=4)
        predicate = {
            "receipt_kind": "browser_readback_v1",
            "receipt_digest": action_result.metadata["receipt_digest"],
            "session_ref": action_result.metadata["session_ref"],
            "readback_observation_digest": readback_result.metadata[
                "observation_digest"
            ],
            "profile_revision": action_result.metadata["profile_revision"],
            "browser_identity_digest": action_result.metadata[
                "browser_identity_digest"
            ],
        }
        goal = state.goal
        admitted = AdmittedCriterion(
            criterion_id=goal.proposed_criteria[0].criterion_id,
            description=goal.proposed_criteria[0].description,
            source_fact_id=state.facts[0].fact_id,
            oracle_kind=EvidenceOracleKind.BROWSER_READBACK,
            predicate=predicate,
            required_evidence_class="browser_readback_v1",
            admission_digest=canonical_json_digest(predicate),
        )
        state = replace(
            state,
            goal=replace(goal, admitted_criteria=(admitted,)),
            facts=(*state.facts, action_fact, readback_fact),
        )
        claim = CompletionClaim(
            correlation_id="claim-browser-e3-valid",
            goal_id=goal.goal_id,
            goal_revision=goal.revision,
            criterion_evidence_refs=(
                ClosedEvidenceRegistry.evidence_id(
                    goal.goal_id,
                    goal.revision,
                    admitted.criterion_id,
                ),
            ),
        )
        self.flow.counters["completion_claims"] += 1
        records = ClosedEvidenceRegistry().derive(
            state,
            claim,
            observed_at="2026-08-28T10:00:00+00:00",
        )
        verified = verify_goal_completion(
            record_completion_claim(record_evidence(state, records), claim)
        )

        without_readback = replace(
            state,
            facts=(*_goal_state().facts, action_fact),
        )
        self.flow.counters["completion_claims"] += 1
        denied_without_readback = False
        try:
            ClosedEvidenceRegistry().derive(
                without_readback,
                claim,
                observed_at="2026-08-28T10:00:00+00:00",
            )
        except EvidenceVerificationError:
            denied_without_readback = True
        return {
            "revoked_session_blocked": isinstance(blocked, ToolResult)
            and blocked.metadata.get("code") == "binding_failure",
            "cleanup_confirmed": cleanup.metadata.get("cleanup_outcome") == "cleaned",
            "profile_clear_confirmed": profile_cleanup
            is BrowserCleanupOutcome.CLEANED,
            "old_profile_session_and_lease_unusable": old_profile_blocked
            and old_lease_blocked
            and isinstance(old_session_blocked, ToolResult),
            "quarantine_cleanup_confirmed": quarantine_cleaned,
            "browser_process_cleanup_confirmed": (
                not self.flow.environment.worker_alive()
                and self.flow.browser_processes.confirmed_gone()
            ),
            "verified_done_only_with_readback": verified.goal.status
            is GoalStatus.VERIFIED_DONE,
            "verified_done_denied_without_readback": denied_without_readback,
        }

    def run(self) -> dict[str, dict[str, bool]]:
        return {
            "J1": self.j1(),
            "J2": self.j2(),
            "J3": self.j3(),
            "J4": self.j4(),
            "J5": self.j5(),
            "J6": self.j6(),
            "J7": self.j7(),
            "J8": self.j8(),
            "J9": self.j9(),
            "J10": self.j10(),
            "J11": self.j11(),
            "J12": self.j12(),
            "J13": self.j13(),
        }


__all__ = ["BrowserE3JourneySuite", "RealBrowserFlow"]
