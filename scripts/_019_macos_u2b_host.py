"""Sealed U2B host fixture that composes only production 019 ports.

The U2B runner installs this file twice under a dedicated owner root: once as
the fixed launchd reconcile executable and once as the occurrence child.  The
fixture supplies a deterministic provider, clock and public TLS resolver, but
all scheduling, claiming, Runtime, ToolRuntime, Seatbelt, browser and process
ownership remain the production implementations.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import platform
import secrets
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from agent.automation.claim_verifier import AutomationClaimVerifier
from agent.automation.composition import (
    AutomationControlConfigV1,
    AutomationControlCoreV1,
    build_automation_control_core,
)
from agent.automation.contracts import (
    AutomationSnapshotV1,
    parse_canonical_utc,
)
from agent.automation.reconcile import ReconcileAutomationsV1
from agent.automation.workspace import SourceBindingV1, WorkspaceBoundsV1
from agent.automation_hosts._posix_fs import ensure_owner_directory, source_root_identity
from agent.automation_hosts.launchd import (
    LAUNCHD_E3_LABEL,
    LaunchdConfigurationV1,
    LaunchdWakeAdapter,
    standard_user_launch_agents_root,
)
from agent.automation_hosts.macos_profile import (
    BackgroundSeatbeltPolicyV1,
    MacOSAutomationHostProfile,
    MacOSHostProfileConfigV1,
    compile_background_seatbelt_profile,
)
from agent.automation_hosts.macos_runtime import MacOSOccurrenceRuntimeFactory
from agent.automation_hosts.occurrence_child import run_posix_occurrence_child
from agent.automation_hosts.posix_repository import PosixAutomationRepository
from agent.automation_hosts.posix_supervisor import (
    PosixOccurrenceSupervisor,
    SupervisorProcessObservation,
)
from agent.automation_hosts.posix_workspace import PosixOwnedWorkspaceRepository
from agent.automation_hosts.runtime_executor import (
    RepositoryRuntimeOccurrenceResolver,
    RuntimeOccurrenceExecutor,
)
from agent.composition import browser_identity_digest_for_state_root
from agent.provider.config import AgentProviderConfig
from agent.runtime.contracts import (
    BlockedClaim,
    ContextPack,
    EvidenceOracleKind,
    GoalDraftProposal,
    ModelResponse,
    ModelToolCall,
    ProposedCriterion,
    canonical_json_digest,
)
from agent.runtime.events import CollectingEventSink
from agent.sandbox.seatbelt import SeatbeltConfiner

_SCHEMA = "my-first-agent/macos-u2b-host-fixture/v1"
_CLOCK_SCHEMA = "my-first-agent/macos-u2b-clock/v1"
_FIXTURE_SCHEMA = "my-first-agent/macos-u2b-browser-fixture/v1"
_SOURCE_BINDING_KEY = canonical_json_digest({"kind": "u2b-source-binding", "v": 1})
_BROWSER_POLICY_DIGEST = canonical_json_digest(
    {"kind": "public-read-ephemeral", "version": 1}
)
_DISCLOSURE_DIGEST = canonical_json_digest(
    {"kind": "u2b-provider-disclosure", "version": 1}
)
_WAKE_POLICY_DIGEST = canonical_json_digest({"kind": "u2b-launchd-wake", "version": 1})
_RUNTIME_READ_ROOTS = (Path("/System/Library"), Path("/usr/lib"))
_EXECUTABLE_LITERALS = (Path("/usr/bin/touch"),)
_WAKE_INTERVAL_SECONDS = 3_600
_SUPERVISOR_LIMITS = {
    "ready": 10.0,
    "start_ack": 10.0,
    "result": 90.0,
    "term": 2.0,
    "kill": 2.0,
    "cleanup": 5.0,
}


@dataclass(frozen=True, slots=True)
class U2BHostPathsV1:
    root: Path
    repository_root: Path
    owned_root: Path
    runtime_state_root: Path
    job_state_root: Path
    browser_state_root: Path
    source_root: Path
    launchd_state_root: Path
    results_root: Path
    process_observations_root: Path
    provider_events_root: Path
    clock_file: Path
    schedule_executable: Path
    child_executable: Path

    @classmethod
    def from_root(cls, root: Path) -> U2BHostPathsV1:
        root = Path(os.path.abspath(os.fspath(root)))
        return cls(
            root=root,
            repository_root=root / "automation-store",
            owned_root=root / "owned-workspaces",
            runtime_state_root=root / "runtime-checkpoints",
            job_state_root=root / "occurrence-jobs",
            browser_state_root=root / "browser-state",
            source_root=root / "source",
            launchd_state_root=root / "launchd-state",
            results_root=root / "wake-results",
            process_observations_root=root / "process-observations",
            provider_events_root=root / "provider-events",
            clock_file=root / "clock.json",
            schedule_executable=root / "bin" / "first-agent-schedule",
            child_executable=root / "bin" / "first-agent-occurrence-child",
        )


@dataclass(frozen=True, slots=True)
class U2BHostCompositionV1:
    core: AutomationControlCoreV1
    executor: RuntimeOccurrenceExecutor
    repository: PosixAutomationRepository
    workspace_repository: PosixOwnedWorkspaceRepository
    source_binding: SourceBindingV1
    config: MacOSHostProfileConfigV1
    wake_adapter: LaunchdWakeAdapter


class U2BHostUnavailableError(RuntimeError):
    """The concrete host cannot satisfy the sealed U2B profile."""


class _U2BProvider:
    """One bounded model fixture; it cannot schedule, approve or invoke tools."""

    def __init__(self, event_sink: Callable[[int], None] | None = None) -> None:
        self._calls = 0
        self._event_sink = event_sink

    def generate(self, context: ContextPack) -> ModelResponse:
        self._calls += 1
        if self._event_sink is not None:
            self._event_sink(self._calls)
        if self._calls == 1:
            return ModelResponse(
                (),
                control=GoalDraftProposal(
                    correlation_id="u2b-goal",
                    user_outcome="Exercise the confined background command once.",
                    beneficiary="owner",
                    targets=("isolated occurrence workspace",),
                    scope=("one bounded background occurrence",),
                    non_goals=("host workspace mutation", "network access"),
                    assumptions=(),
                    proposed_criteria=(
                        ProposedCriterion(
                            criterion_id="criterion:u2b-confined-command",
                            description="the bounded command is durably observed",
                            oracle_kind=EvidenceOracleKind.TOOL_RECEIPT,
                        ),
                    ),
                    next_step="run the exact confined command",
                    requires_local_process=True,
                ),
            )
        if self._calls == 2:
            return ModelResponse(
                (
                    ModelToolCall(
                        "u2b-sandbox-call",
                        "sandbox_exec",
                        {
                            "executable": "/usr/bin/touch",
                            "argv": ["u2b-effect-marker"],
                            "cwd": ".",
                            "mode": "workspace-write",
                            "network": "off",
                        },
                    ),
                )
            )
        goal_id, goal_revision = _trusted_goal_identity(context)
        return ModelResponse(
            (),
            control=BlockedClaim(
                correlation_id="u2b-bounded-terminal",
                goal_id=goal_id,
                goal_revision=goal_revision,
                blocker=(
                    "The confined command ran, but no local_process tool is available "
                    "to produce the required completion receipt."
                ),
                safe_attempts=("ran one network-off confined command",),
                resume_condition="attach the separately governed local_process capability",
            ),
        )


def build_u2b_host(root: Path) -> U2BHostCompositionV1:
    paths = U2BHostPathsV1.from_root(root)
    for directory in (
        paths.root,
        paths.repository_root,
        paths.owned_root,
        paths.runtime_state_root,
        paths.job_state_root,
        paths.browser_state_root,
        paths.source_root,
        paths.launchd_state_root,
        paths.results_root,
        paths.process_observations_root,
        paths.provider_events_root,
    ):
        ensure_owner_directory(directory)
    repository = PosixAutomationRepository(paths.repository_root)
    binding = SourceBindingV1(
        binding_id="source:u2b-host-fixture",
        root_identity_digest=source_root_identity(paths.source_root),
        excluded_components=("private", "runtime"),
    )
    workspaces = PosixOwnedWorkspaceRepository(paths.owned_root, {binding: paths.source_root})
    confiner = SeatbeltConfiner(
        profile_compiler=compile_background_seatbelt_profile,
    )
    qualification = confiner.qualify()
    if not qualification.available or qualification.backend_identity is None:
        raise U2BHostUnavailableError("sandbox_unavailable")
    qualification_policy = _qualification_policy(paths)
    descriptor = AgentProviderConfig(provider_type="fake").descriptor()
    trust_profile_digest = canonical_json_digest(descriptor.trust_profile)
    browser_identity = browser_identity_digest_for_state_root(paths.browser_state_root)
    supervisor_identity = _supervisor_identity(paths.child_executable)
    config = MacOSHostProfileConfigV1.create(
        supervisor_identity_digest=supervisor_identity,
        sandbox_backend_identity_digest=(
            qualification.backend_identity.backend_identity_digest
        ),
        background_policy_digest=qualification_policy.template_digest,
        browser_identity_digest=browser_identity,
        browser_origin_policy_digest=_BROWSER_POLICY_DIGEST,
        provider_descriptor_digest=descriptor.identity_digest,
        trust_profile_digest=trust_profile_digest,
        credential_environment_name=None,
        provider_disclosure_request_digest=_DISCLOSURE_DIGEST,
    )
    resolver, playwright_factory = _browser_fixture_ports(paths)
    profile = MacOSAutomationHostProfile(
        config=config,
        platform_system=platform.system(),
        supervisor_identity_digest=supervisor_identity,
        sandbox_qualification=qualification,
        browser_identity_digest=browser_identity,
        provider_descriptor=descriptor,
        credential_lookup=lambda _name: None,
        provider_factory=lambda _credential: _U2BProvider(
            lambda call_index: _write_unique_result(
                paths.provider_events_root,
                {
                    "schema": "my-first-agent/macos-u2b-provider-event/v1",
                    "call_index": call_index,
                },
            )
        ),
        background_claim_verifier=AutomationClaimVerifier(repository),
        sandbox_confiner=confiner,
        browser_resolver=resolver,
        playwright_factory=playwright_factory,
        tool_clock=lambda: _read_clock(paths.clock_file),
    )
    resolver_port = RepositoryRuntimeOccurrenceResolver(
        repository=repository,
        workspace_repository=workspaces,
    )
    runtime_factory = MacOSOccurrenceRuntimeFactory(
        profile=profile,
        repository=repository,
        workspace_repository=workspaces,
        job_state_root=paths.job_state_root,
        browser_state_root=paths.browser_state_root,
        runtime_read_roots=_RUNTIME_READ_ROOTS,
        executable_literals=_EXECUTABLE_LITERALS,
        event_sink_factory=CollectingEventSink,
        system_policy=(
            "This is one bounded background occurrence. Use only advertised governed "
            "tools, never request user approval, and report an exact blocked_claim when "
            "the required evidence class is unavailable."
        ),
        captured_path="/usr/bin:/bin",
    )
    executor = RuntimeOccurrenceExecutor(
        state_root=paths.runtime_state_root,
        resolver=resolver_port,
        runtime_factory=runtime_factory,
    )
    supervisor = PosixOccurrenceSupervisor(
        command=(os.fspath(paths.child_executable),),
        ready_timeout_seconds=_SUPERVISOR_LIMITS["ready"],
        start_ack_timeout_seconds=_SUPERVISOR_LIMITS["start_ack"],
        result_timeout_seconds=_SUPERVISOR_LIMITS["result"],
        term_grace_seconds=_SUPERVISOR_LIMITS["term"],
        kill_grace_seconds=_SUPERVISOR_LIMITS["kill"],
        cleanup_verify_seconds=_SUPERVISOR_LIMITS["cleanup"],
        observation_sink=lambda observation: _write_process_observation(
            paths.process_observations_root,
            observation,
        ),
    )
    launchd_config = LaunchdConfigurationV1(
        installed_executable=paths.schedule_executable,
        launch_agents_root=standard_user_launch_agents_root(),
        state_root=paths.launchd_state_root,
        start_interval_seconds=_WAKE_INTERVAL_SECONDS,
        policy_digest=_WAKE_POLICY_DIGEST,
        label=_u2b_label(paths.root),
    )
    wake = LaunchdWakeAdapter(launchd_config)
    control_config = AutomationControlConfigV1(
        source_bindings=((_SOURCE_BINDING_KEY, binding),),
        workspace_bounds=WorkspaceBoundsV1(),
        qualification_identity_digest=config.config_digest,
    )
    core = build_automation_control_core(
        control_config,
        repository=repository,
        workspace_repository=workspaces,
        clock=lambda: parse_canonical_utc(_read_clock(paths.clock_file), "u2b_clock"),
        supervisor=supervisor,
        provider_factory=lambda: executor,
        sandbox_capability=confiner,
        browser_capability=browser_identity,
        wake_adapter=wake,
        next_snapshot_token=lambda: "snapshot-" + secrets.token_hex(16),
        claim_fencing_token=lambda: "claim-" + secrets.token_hex(16),
        raw_capability=lambda: "opaque-capability-" + secrets.token_hex(32),
        checkpoint_identity=lambda: secrets.token_hex(32),
    )
    return U2BHostCompositionV1(
        core=core,
        executor=executor,
        repository=repository,
        workspace_repository=workspaces,
        source_binding=binding,
        config=config,
        wake_adapter=wake,
    )


def initialize_u2b_repository(root: Path) -> None:
    paths = U2BHostPathsV1.from_root(root)
    ensure_owner_directory(paths.repository_root)
    PosixAutomationRepository(
        paths.repository_root,
        initial_snapshot=AutomationSnapshotV1(
            revision=0,
            snapshot_token="snapshot-token-0000",
            records=(),
            tombstones=(),
        ),
    )


def run_installed_reconcile(root: Path) -> int:
    host = build_u2b_host(root)
    result = host.core.reconcile(ReconcileAutomationsV1())
    paths = U2BHostPathsV1.from_root(root)
    payload = {
        "schema": _SCHEMA,
        "code": result.code,
        "automation_id": result.automation_id,
        "occurrence_id": result.occurrence_id,
        "status": None if result.status is None else result.status.value,
        "reason": result.reason,
    }
    _write_unique_result(paths.results_root, payload)
    print(json.dumps({"code": "reconcile_finished"}, separators=(",", ":")))
    return 0


def run_installed_child(root: Path) -> int:
    host = build_u2b_host(root)
    return run_posix_occurrence_child(executor_factory=lambda: host.executor)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    name = Path(__file__).name
    try:
        if name == "first-agent-occurrence-child" and len(sys.argv) == 1:
            return run_installed_child(root)
        if name == "first-agent-schedule" and sys.argv[1:] == ["reconcile"]:
            return run_installed_reconcile(root)
        code = "invalid_installed_invocation"
        exit_code = 64
    except U2BHostUnavailableError:
        code = "needs_019_config"
        exit_code = 2
    except Exception:
        code = "host_composition_failed"
        exit_code = 2
    print(json.dumps({"code": code}, separators=(",", ":")))
    return exit_code


def _qualification_policy(paths: U2BHostPathsV1) -> BackgroundSeatbeltPolicyV1:
    roots = (
        paths.root / "qualification-workspace",
        paths.root / "qualification-temp",
        paths.root / "qualification-home",
    )
    for root in roots:
        ensure_owner_directory(root)
    return BackgroundSeatbeltPolicyV1.create(
        workspace_root=roots[0],
        temp_root=roots[1],
        home_root=roots[2],
        runtime_read_roots=_RUNTIME_READ_ROOTS,
        executable_literals=_EXECUTABLE_LITERALS,
    )


def _supervisor_identity(child: Path) -> str:
    payload = child.read_bytes()
    return canonical_json_digest(
        {
            "child_sha256": hashlib.sha256(payload).hexdigest(),
            "limits": _SUPERVISOR_LIMITS,
            "protocol": "ready-start-result-v1",
        }
    )


def _u2b_label(root: Path) -> str:
    suffix = canonical_json_digest(os.fspath(root))[:12]
    return f"{LAUNCHD_E3_LABEL}.{suffix}"


def _read_clock(path: Path) -> str:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or set(document) != {"schema", "utc"}:
        raise ValueError("u2b clock fields must be exact")
    if document["schema"] != _CLOCK_SCHEMA or not isinstance(document["utc"], str):
        raise ValueError("u2b clock is malformed")
    return document["utc"]


def _browser_fixture_ports(paths: U2BHostPathsV1):  # noqa: ANN202
    fixture_path = paths.root / "host" / "browser_e3_fixture.py"
    descriptor_path = paths.root / "browser-fixture.json"
    if not fixture_path.is_file() or not descriptor_path.is_file():
        return None, None
    descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
    if (
        not isinstance(descriptor, dict)
        or set(descriptor) != {"schema", "port"}
        or descriptor.get("schema") != _FIXTURE_SCHEMA
        or isinstance(descriptor.get("port"), bool)
        or not isinstance(descriptor.get("port"), int)
        or not 1 <= descriptor["port"] <= 65_535
    ):
        raise ValueError("browser fixture descriptor is malformed")
    module_name = "_u2b_browser_fixture_" + hashlib.sha256(
        os.fsencode(fixture_path)
    ).hexdigest()[:12]
    spec = importlib.util.spec_from_file_location(module_name, fixture_path)
    if spec is None or spec.loader is None:
        raise ValueError("browser fixture module is unavailable")
    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.get(module_name)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        if previous is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = previous
        raise
    return module.FixtureResolver(), module.FixturePlaywrightFactory(port=descriptor["port"])


def _trusted_goal_identity(context: ContextPack) -> tuple[str, int]:
    for message in context.messages:
        for block in message.content:
            if isinstance(block, dict) and block.get("type") == "trusted_goal":
                goal_id = block.get("goal_id")
                revision = block.get("goal_revision")
                if isinstance(goal_id, str) and isinstance(revision, int):
                    return goal_id, revision
    raise ValueError("trusted Goal identity is unavailable")


def _write_unique_result(root: Path, payload: dict[str, object]) -> None:
    ensure_owner_directory(root)
    encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if len(encoded) > 4_096:
        raise ValueError("u2b result exceeds its bound")
    path = root / f"result-{time.monotonic_ns()}-{secrets.token_hex(4)}.json"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        view = memoryview(encoded)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("u2b result write made no progress")
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_process_observation(
    root: Path,
    observation: SupervisorProcessObservation,
) -> None:
    payload = {
        "schema": "my-first-agent/macos-u2b-process-observation/v1",
        "leader_pid": observation.leader_pid,
        "process_group_id": observation.process_group_id,
        "descendant_pid": observation.descendant_pid,
        "descendant_process_group_id": observation.descendant_process_group_id,
    }
    _write_unique_result(root, payload)


if __name__ == "__main__":
    raise SystemExit(main())
