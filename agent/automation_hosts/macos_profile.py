"""Optional macOS qualification and strict unattended Seatbelt policy."""

from __future__ import annotations

import os
import re
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from agent.automation.contracts import (
    AutomationDefinitionV1,
    BackgroundOccurrenceAuthorityV1,
)
from agent.automation_hosts.runtime_executor import RuntimeOccurrenceBindingV1
from agent.composition import (
    BrowserReadiness,
    Composition,
    browser_identity_digest_for_state_root,
    build_browser_resources,
    build_composition,
)
from agent.runtime.context import ContextLimits
from agent.runtime.contracts import (
    BackgroundExecutionAuthorityV1,
    ProviderDescriptor,
    canonical_json_digest,
)
from agent.runtime.loop import InvocationLimits
from agent.runtime.ports import BackgroundClaimVerifier, CheckpointStore, EventSink
from agent.sandbox.contracts import (
    SandboxMode,
    SandboxNetworkMode,
    SandboxQualificationV1,
)
from agent.sandbox.policy import escape_seatbelt_path
from agent.sandbox.tools import build_sandbox_exec_registration

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_QUALIFICATION_REASONS = frozenset(
    {
        "qualified",
        "unsupported_platform",
        "supervisor_identity_drift",
        "sandbox_unavailable",
        "sandbox_backend_identity_drift",
        "sandbox_policy_identity_drift",
        "browser_unavailable",
        "browser_identity_drift",
        "browser_policy_identity_drift",
        "provider_profile_identity_drift",
        "credential_unavailable",
    }
)
BACKGROUND_TOOL_NAMES = frozenset(
    {
        "sandbox_exec",
        "browser_open",
        "browser_observe",
        "browser_act",
        "browser_close",
        "browser_begin_takeover",
    }
)


def _hex64(value: object, name: str) -> str:
    if not isinstance(value, str) or not _HEX64.fullmatch(value):
        raise ValueError(f"{name} must be bare hex64")
    return value


def _canonical_existing(path: object, name: str, *, directory: bool) -> str:
    candidate = Path(path)  # type: ignore[arg-type]
    if not candidate.is_absolute():
        raise ValueError(f"{name} must be an absolute path")
    try:
        info = os.lstat(candidate)
        resolved = candidate.resolve(strict=True)
    except (FileNotFoundError, OSError) as error:
        raise ValueError(f"{name} must exist") from error
    if stat.S_ISLNK(info.st_mode) or str(candidate) != str(resolved):
        raise ValueError(f"{name} must be canonical and no-follow")
    if directory != stat.S_ISDIR(info.st_mode):
        raise ValueError(f"{name} has the wrong object type")
    return escape_seatbelt_path(str(candidate))


@dataclass(frozen=True, slots=True)
class BackgroundSeatbeltPolicyV1:
    workspace_root: str
    temp_root: str
    home_root: str
    runtime_read_roots: tuple[str, ...]
    executable_literals: tuple[str, ...]
    template_digest: str = ""
    policy_digest: str = ""

    @classmethod
    def create(
        cls,
        *,
        workspace_root: Path,
        temp_root: Path,
        home_root: Path,
        runtime_read_roots: tuple[Path, ...],
        executable_literals: tuple[Path, ...],
    ) -> BackgroundSeatbeltPolicyV1:
        return cls(
            workspace_root=_canonical_existing(
                workspace_root,
                "workspace_root",
                directory=True,
            ),
            temp_root=_canonical_existing(temp_root, "temp_root", directory=True),
            home_root=_canonical_existing(home_root, "home_root", directory=True),
            runtime_read_roots=tuple(
                sorted(
                    _canonical_existing(path, "runtime_read_root", directory=True)
                    for path in runtime_read_roots
                )
            ),
            executable_literals=tuple(
                sorted(
                    _canonical_existing(path, "executable_literal", directory=False)
                    for path in executable_literals
                )
            ),
        )

    def __post_init__(self) -> None:
        roots = (self.workspace_root, self.temp_root, self.home_root)
        for root in (*roots, *self.runtime_read_roots, *self.executable_literals):
            if not isinstance(root, str) or not root.startswith("/"):
                raise ValueError("background Seatbelt paths must be absolute strings")
            escape_seatbelt_path(root)
        if len(set(roots)) != len(roots) or any(
            Path(left) in Path(right).parents or Path(right) in Path(left).parents
            for index, left in enumerate(roots)
            for right in roots[index + 1 :]
        ):
            raise ValueError("background writable roots must be disjoint")
        for values, name in (
            (self.runtime_read_roots, "runtime_read_roots"),
            (self.executable_literals, "executable_literals"),
        ):
            if values != tuple(sorted(set(values))) or not values:
                raise ValueError(f"{name} must be sorted, unique and non-empty")
        template_digest = canonical_json_digest(
            {
                "kind": "macos_background_seatbelt_template_v1",
                "mode": self.mode.value,
                "network": self.network.value,
                "runtime_read_roots": self.runtime_read_roots,
                "executable_literals": self.executable_literals,
            }
        )
        if self.template_digest and self.template_digest != template_digest:
            raise ValueError("background Seatbelt template digest mismatch")
        object.__setattr__(self, "template_digest", template_digest)
        digest = canonical_json_digest(
            {
                "kind": "macos_background_seatbelt_v1",
                "mode": self.mode.value,
                "network": self.network.value,
                "workspace_root": self.workspace_root,
                "temp_root": self.temp_root,
                "home_root": self.home_root,
                "runtime_read_roots": self.runtime_read_roots,
                "executable_literals": self.executable_literals,
            }
        )
        if self.policy_digest and self.policy_digest != digest:
            raise ValueError("background Seatbelt policy digest mismatch")
        object.__setattr__(self, "policy_digest", digest)

    @property
    def mode(self) -> SandboxMode:
        return SandboxMode.WORKSPACE_WRITE

    @property
    def network(self) -> SandboxNetworkMode:
        return SandboxNetworkMode.OFF


def compile_background_seatbelt_profile(policy: BackgroundSeatbeltPolicyV1) -> str:
    """Compile one default-deny profile from the exact qualified read set."""

    if not isinstance(policy, BackgroundSeatbeltPolicyV1):
        raise TypeError("policy must use BackgroundSeatbeltPolicyV1")
    clauses = [
        "(version 1)",
        "(deny default)",
        "(allow process*)",
        "(allow signal (target self))",
        "(allow sysctl-read)",
        "(allow mach-lookup)",
        "(allow ipc-posix*)",
        "(allow file-read-metadata)",
        "(allow file-ioctl)",
    ]
    for root in (
        policy.workspace_root,
        policy.temp_root,
        policy.home_root,
        *policy.runtime_read_roots,
    ):
        clauses.append(f'(allow file-read* (subpath "{escape_seatbelt_path(root)}"))')
    for path in policy.executable_literals:
        clauses.append(f'(allow file-read* (literal "{escape_seatbelt_path(path)}"))')
    for root in (policy.workspace_root, policy.temp_root, policy.home_root):
        clauses.append(f'(allow file-write* (subpath "{escape_seatbelt_path(root)}"))')
    clauses.extend(
        (
            # macOS 启动系统二进制会读取根目录对象；只开放该 literal，不能扩大为整个根目录树。
            '(allow file-read* (literal "/"))',
            '(allow file-read* (literal "/dev/null"))',
            '(allow file-write* (literal "/dev/null"))',
            "(deny network*)",
        )
    )
    return "\n".join(clauses) + "\n"


@dataclass(frozen=True, slots=True)
class MacOSHostProfileConfigV1:
    supervisor_identity_digest: str
    sandbox_backend_identity_digest: str
    background_policy_digest: str
    browser_identity_digest: str
    browser_origin_policy_digest: str
    provider_descriptor_digest: str
    trust_profile_digest: str
    credential_environment_name: str | None
    provider_disclosure_request_digest: str
    config_digest: str = ""

    @classmethod
    def create(cls, **values: object) -> MacOSHostProfileConfigV1:
        return cls(**values)  # type: ignore[arg-type]

    def __post_init__(self) -> None:
        for name in (
            "supervisor_identity_digest",
            "sandbox_backend_identity_digest",
            "background_policy_digest",
            "browser_identity_digest",
            "browser_origin_policy_digest",
            "provider_descriptor_digest",
            "trust_profile_digest",
            "provider_disclosure_request_digest",
        ):
            _hex64(getattr(self, name), name)
        if self.credential_environment_name is not None and not _ENV_NAME.fullmatch(
            self.credential_environment_name
        ):
            raise ValueError("credential_environment_name must be canonical")
        values = {
            name: getattr(self, name)
            for name in self.__dataclass_fields__
            if name != "config_digest"
        }
        digest = canonical_json_digest(values)
        if self.config_digest and self.config_digest != digest:
            raise ValueError("macOS host config digest mismatch")
        object.__setattr__(self, "config_digest", digest)


@dataclass(frozen=True, slots=True)
class MacOSHostQualificationV1:
    available: bool
    reason_code: str
    qualification_identity_digest: str | None

    def __post_init__(self) -> None:
        if self.reason_code not in _QUALIFICATION_REASONS:
            raise ValueError("macOS qualification reason is not closed")
        if self.available != (self.reason_code == "qualified"):
            raise ValueError("macOS qualification availability mismatch")
        if self.available:
            _hex64(self.qualification_identity_digest, "qualification_identity_digest")
        elif self.qualification_identity_digest is not None:
            raise ValueError("unavailable qualification carries no identity")


class MacOSHostCompositionError(RuntimeError):
    """Closed pre-composition failure without carrying private occurrence data."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


@dataclass(frozen=True, slots=True)
class MacOSOccurrenceSpecV1:
    """Trusted host inputs for one already-created occurrence checkpoint."""

    definition: AutomationDefinitionV1
    authority: BackgroundOccurrenceAuthorityV1
    runtime_binding: RuntimeOccurrenceBindingV1
    workspace_root: Path
    state_root: Path
    sandbox_policy: BackgroundSeatbeltPolicyV1
    checkpoint_store: CheckpointStore
    event_sink: EventSink
    system_policy: str
    context_limits: ContextLimits
    invocation_limits: InvocationLimits
    captured_path: str

    def __post_init__(self) -> None:
        if not isinstance(self.definition, AutomationDefinitionV1):
            raise TypeError("definition must use AutomationDefinitionV1")
        if not isinstance(self.authority, BackgroundOccurrenceAuthorityV1):
            raise TypeError("authority must use BackgroundOccurrenceAuthorityV1")
        if not isinstance(self.runtime_binding, RuntimeOccurrenceBindingV1):
            raise TypeError("runtime_binding must use RuntimeOccurrenceBindingV1")
        if not isinstance(self.sandbox_policy, BackgroundSeatbeltPolicyV1):
            raise TypeError("sandbox_policy must use BackgroundSeatbeltPolicyV1")
        for path, name in (
            (self.workspace_root, "workspace_root"),
            (self.state_root, "state_root"),
        ):
            canonical = _canonical_existing(path, name, directory=True)
            if canonical != str(path):
                raise ValueError(f"{name} must be canonical")
        if not isinstance(self.system_policy, str) or not self.system_policy.strip():
            raise ValueError("system_policy must be bounded non-empty text")
        if not isinstance(self.context_limits, ContextLimits):
            raise TypeError("context_limits must use ContextLimits")
        if not isinstance(self.invocation_limits, InvocationLimits):
            raise TypeError("invocation_limits must use InvocationLimits")
        if not isinstance(self.captured_path, str):
            raise TypeError("captured_path must be a string")


@dataclass(frozen=True, slots=True)
class OccurrenceCompositionV1:
    """One existing Runtime composition plus its qualified host identity."""

    composition: Composition
    qualification_identity_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.composition, Composition):
            raise TypeError("composition must use the existing Composition")
        _hex64(
            self.qualification_identity_digest,
            "qualification_identity_digest",
        )

    def close(self) -> None:
        for closeable in reversed(self.composition.close_stack):
            closeable()

    @property
    def runtime(self):  # noqa: ANN201
        return self.composition.runtime


class MacOSAutomationHostProfile:
    def __init__(
        self,
        *,
        config: MacOSHostProfileConfigV1,
        platform_system: str,
        supervisor_identity_digest: str,
        sandbox_qualification: SandboxQualificationV1,
        browser_identity_digest: str | None,
        provider_descriptor: ProviderDescriptor,
        credential_lookup: Callable[[str], str | None],
        provider_factory: Callable[[str | None], object] | None = None,
        background_claim_verifier: BackgroundClaimVerifier | None = None,
        sandbox_confiner: object | None = None,
        browser_resolver: object | None = None,
        playwright_factory: object | None = None,
        tool_clock: Callable[[], str] | None = None,
    ) -> None:
        if not isinstance(config, MacOSHostProfileConfigV1):
            raise TypeError("config must use MacOSHostProfileConfigV1")
        self._config = config
        self._platform_system = platform_system
        self._supervisor_identity_digest = supervisor_identity_digest
        self._sandbox_qualification = sandbox_qualification
        self._browser_identity_digest = browser_identity_digest
        self._provider_descriptor = provider_descriptor
        self._credential_lookup = credential_lookup
        self._provider_factory = provider_factory
        self._background_claim_verifier = background_claim_verifier
        self._sandbox_confiner = sandbox_confiner
        self._browser_resolver = browser_resolver
        self._playwright_factory = playwright_factory
        if tool_clock is not None and not callable(tool_clock):
            raise TypeError("tool_clock must be callable or null")
        self._tool_clock = tool_clock
        self._composition_calls = 0

    @property
    def composition_calls(self) -> int:
        return self._composition_calls

    def qualify(self, definition: AutomationDefinitionV1) -> MacOSHostQualificationV1:
        if not isinstance(definition, AutomationDefinitionV1):
            raise TypeError("definition must use AutomationDefinitionV1")
        config = self._config
        body = definition.body
        reason = self._profile_reason(body)
        if reason is None and not self._credential()[0]:
            reason = "credential_unavailable"
        if reason is not None:
            return MacOSHostQualificationV1(False, reason, None)
        return MacOSHostQualificationV1(True, "qualified", config.config_digest)

    def build_occurrence(
        self,
        spec: MacOSOccurrenceSpecV1,
    ) -> OccurrenceCompositionV1:
        if not isinstance(spec, MacOSOccurrenceSpecV1):
            raise TypeError("spec must use MacOSOccurrenceSpecV1")
        reason = self._profile_reason(spec.definition.body)
        if reason is not None:
            raise MacOSHostCompositionError(reason)
        if (
            self._provider_factory is None
            or self._background_claim_verifier is None
            or self._sandbox_confiner is None
        ):
            raise MacOSHostCompositionError("composition_ports_unavailable")
        self._validate_occurrence(spec)
        actual_sandbox = self._sandbox_confiner.qualify()
        if actual_sandbox != self._sandbox_qualification:
            raise MacOSHostCompositionError("sandbox_backend_identity_drift")

        credential_available, credential = self._credential()
        if not credential_available:
            raise MacOSHostCompositionError("credential_unavailable")

        browser = build_browser_resources(
            spec.workspace_root,
            spec.state_root,
            enabled=spec.definition.body.budgets.browser_actions > 0,
            resolver=self._browser_resolver,
            playwright_factory=self._playwright_factory,
        )
        if browser.readiness is not BrowserReadiness.READY:
            raise MacOSHostCompositionError(browser.reason_code or "browser_unavailable")
        try:
            provider = self._provider_factory(credential)
            del credential
            if not callable(getattr(provider, "generate", None)):
                raise MacOSHostCompositionError("provider_unavailable")
            policy = spec.sandbox_policy

            def exact_policy(arguments, _roots, _private):  # noqa: ANN001, ANN202
                if arguments.get("mode", policy.mode.value) != policy.mode.value:
                    raise ValueError("background sandbox mode cannot change")
                if arguments.get("network", policy.network.value) != policy.network.value:
                    raise ValueError("background sandbox network cannot change")
                return policy

            sandbox_registration = build_sandbox_exec_registration(
                workspace=spec.workspace_root,
                temp_root=Path(policy.temp_root),
                state_root=spec.state_root,
                home=Path(policy.home_root),
                captured_path=spec.captured_path,
                confiner=self._sandbox_confiner,
                policy_builder=exact_policy,
                authority_policy_digest=policy.template_digest,
            )
            execution_authority = self._execution_authority(spec)
            occurrence = spec.runtime_binding.scheduled_occurrence
            composition = build_composition(
                provider=provider,
                checkpoint_store=spec.checkpoint_store,
                tool_registrations=(sandbox_registration, *browser.registrations),
                event_sink=spec.event_sink,
                system_policy=spec.system_policy,
                context_limits=spec.context_limits,
                invocation_limits=spec.invocation_limits,
                closeables=browser.closeables,
                workspace_identity_digest=(
                    spec.runtime_binding.workspace_identity_digest
                ),
                context_scope_digest=occurrence.workspace_scope_digest,
                provider_descriptor=self._provider_descriptor,
                workspace_binding=spec.runtime_binding.workspace_binding,
                background_claim_verifier=self._background_claim_verifier,
                background_execution_authority=execution_authority,
                tool_clock=self._tool_clock,
            )
        except Exception:
            for closeable in reversed(browser.closeables):
                closeable()
            raise
        actual_names = frozenset(
            definition.name for definition in composition.tool_runtime.definitions()
        )
        if actual_names != BACKGROUND_TOOL_NAMES:
            for closeable in reversed(composition.close_stack):
                closeable()
            raise MacOSHostCompositionError("background_tool_surface_drift")
        self._composition_calls += 1
        return OccurrenceCompositionV1(
            composition=composition,
            qualification_identity_digest=self._config.config_digest,
        )

    def _profile_reason(self, body) -> str | None:  # noqa: ANN001
        config = self._config
        if self._platform_system != "Darwin":
            return "unsupported_platform"
        if self._supervisor_identity_digest != config.supervisor_identity_digest:
            return "supervisor_identity_drift"
        sandbox = self._sandbox_qualification
        if not sandbox.available or sandbox.backend_identity is None:
            return "sandbox_unavailable"
        if (
            sandbox.backend_identity.backend_identity_digest
            != config.sandbox_backend_identity_digest
        ):
            return "sandbox_backend_identity_drift"
        if body.background_environment_policy_digest != config.background_policy_digest:
            return "sandbox_policy_identity_drift"
        if self._browser_identity_digest is None:
            return "browser_unavailable"
        if self._browser_identity_digest != config.browser_identity_digest:
            return "browser_identity_drift"
        if body.browser_origin_policy_digest != config.browser_origin_policy_digest:
            return "browser_policy_identity_drift"
        if (
            self._provider_descriptor.identity_digest
            != config.provider_descriptor_digest
            or body.provider_descriptor_digest != config.provider_descriptor_digest
            or body.trust_profile_digest != config.trust_profile_digest
            or body.credential_environment_name != config.credential_environment_name
            or body.provider_disclosure_request_digest
            != config.provider_disclosure_request_digest
        ):
            return "provider_profile_identity_drift"
        return None

    def _credential(self) -> tuple[bool, str | None]:
        name = self._config.credential_environment_name
        if name is None:
            return True, None
        value = self._credential_lookup(name)
        if not isinstance(value, str) or not value:
            return False, None
        return True, value

    def _validate_occurrence(self, spec: MacOSOccurrenceSpecV1) -> None:
        definition = spec.definition
        body = definition.body
        authority = spec.authority
        occurrence = spec.runtime_binding.scheduled_occurrence
        binding = occurrence.background_binding
        budgets = body.budgets
        if binding is None:
            raise MacOSHostCompositionError("occurrence_binding_drift")
        exact_authority = {
            "automation_id": authority.automation_id,
            "automation_revision": authority.automation_revision,
            "occurrence_id": authority.occurrence_id,
            "occurrence_index": authority.occurrence_index,
            "scheduled_for_utc": authority.scheduled_for_utc,
            "definition_digest": authority.definition_digest,
            "grant_digest": authority.grant_digest,
            "claim_authority_digest": authority.authority_digest,
            "claim_capability_digest": canonical_json_digest(authority.raw_capability),
            "checkpoint_identity_digest": authority.checkpoint_identity,
            "deadline_utc": authority.deadline_utc,
        }
        if (
            authority.definition_digest != definition.definition_digest
            or authority.grant_digest != definition.grant.grant_digest
            or occurrence.schedule_id != authority.automation_id
            or occurrence.occurrence_id != authority.occurrence_id
            or occurrence.scheduled_for_utc != authority.scheduled_for_utc
            or occurrence.message != body.task_text
            or any(
                getattr(binding, name) != value
                for name, value in exact_authority.items()
            )
        ):
            raise MacOSHostCompositionError("occurrence_binding_drift")
        expected_budgets = {
            "model_call_limit": budgets.model_calls,
            "tool_call_limit": budgets.tool_calls,
            "sandbox_command_limit": budgets.sandbox_commands,
            "browser_action_limit": budgets.browser_actions,
            "max_input_tokens": budgets.max_input_tokens,
            "max_output_tokens": budgets.max_output_tokens,
        }
        if any(
            getattr(binding, name) != value
            for name, value in expected_budgets.items()
        ):
            raise MacOSHostCompositionError("occurrence_budget_drift")
        if (
            spec.sandbox_policy.template_digest
            != body.background_environment_policy_digest
            or spec.sandbox_policy.workspace_root != str(spec.workspace_root)
        ):
            raise MacOSHostCompositionError("sandbox_policy_identity_drift")
        if (
            browser_identity_digest_for_state_root(spec.state_root)
            != self._config.browser_identity_digest
        ):
            raise MacOSHostCompositionError("browser_identity_drift")
        snapshot = spec.checkpoint_store.load()
        if (
            snapshot.state.background_occurrence_binding != binding
            or snapshot.state.workspace_binding
            != spec.runtime_binding.workspace_binding
        ):
            raise MacOSHostCompositionError("checkpoint_binding_drift")

    @staticmethod
    def _execution_authority(
        spec: MacOSOccurrenceSpecV1,
    ) -> BackgroundExecutionAuthorityV1:
        binding = spec.runtime_binding.scheduled_occurrence.background_binding
        assert binding is not None
        return BackgroundExecutionAuthorityV1.create(
            occurrence_binding=binding,
            claim_fencing_token=spec.authority.claim_fencing_token,
            raw_capability=spec.authority.raw_capability,
            isolated_workspace_identity_digest=(
                spec.runtime_binding.workspace_identity_digest
            ),
            background_environment_policy_digest=(
                spec.definition.body.background_environment_policy_digest
            ),
            browser_origin_policy_digest=(
                spec.definition.body.browser_origin_policy_digest
            ),
        )


__all__ = [
    "BACKGROUND_TOOL_NAMES",
    "BackgroundSeatbeltPolicyV1",
    "MacOSAutomationHostProfile",
    "MacOSHostCompositionError",
    "MacOSHostProfileConfigV1",
    "MacOSHostQualificationV1",
    "MacOSOccurrenceSpecV1",
    "OccurrenceCompositionV1",
    "compile_background_seatbelt_profile",
]
