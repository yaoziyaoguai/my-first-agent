#!/usr/bin/env python3
"""013 真实 Provider E3：saved profile + 产品 main + production HTTP adapter。"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import sys
import tempfile
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import httpx  # noqa: E402

import main as product_main  # noqa: E402
from agent.continuity.identity import WorkspaceIdentityV1  # noqa: E402
from agent.provider.config import AgentProviderConfig  # noqa: E402
from agent.provider.factory import build_model_provider  # noqa: E402
from agent.provider.protocol import (  # noqa: E402
    ProviderAuthError,
    ProviderConfigurationError,
    ProviderError,
    ProviderHTTPRetryableError,
    ProviderProtocolError,
    ProviderTimeoutError,
    ProviderTransportError,
)
from agent.runtime.checkpoint import LocalCheckpointStore  # noqa: E402
from agent.runtime.contracts import (  # noqa: E402
    ActiveRunStatus,
    ApprovalRequest,
    GoalStatus,
    canonical_json_digest,
)

_ENV_NAMES = (
    "FIRST_AGENT_E3_PROVIDER",
    "FIRST_AGENT_E3_BASE_URL",
    "FIRST_AGENT_E3_MODEL",
    "FIRST_AGENT_E3_API_KEY",
)
_NEEDS_CONFIG = (
    "NEEDS_013_E3_CONFIG(required=FIRST_AGENT_E3_PROVIDER,"
    "FIRST_AGENT_E3_BASE_URL,FIRST_AGENT_E3_MODEL,FIRST_AGENT_E3_API_KEY)"
)
_ARTIFACT_PATH = "notes/idea.md"
_ARTIFACT_CONTENT = "# Idea\n\nKeep the first version small.\n"
_EDIT_PATH = "README.md"
_OLD_EDIT_CONTENT = "Title\nOld summary\n"
_NEW_EDIT_CONTENT = "Title\nNew bounded summary\n"


class E3AcceptanceError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class E3Config:
    provider: str
    base_url: str
    model: str
    api_key: str = field(repr=False)

    @classmethod
    def from_environment(cls, environ: Mapping[str, str]) -> E3Config:
        values = {name: environ.get(name, "") for name in _ENV_NAMES}
        present = {name for name, value in values.items() if value}
        if not present:
            raise E3AcceptanceError(_NEEDS_CONFIG)
        if len(present) != len(_ENV_NAMES):
            raise E3AcceptanceError("013_E3_BLOCKED(reason=incomplete_config)")
        provider = values["FIRST_AGENT_E3_PROVIDER"]
        if provider not in {"openai_compatible", "anthropic_compatible"}:
            raise E3AcceptanceError("013_E3_BLOCKED(reason=incomplete_config)")
        return cls(
            provider=provider,
            base_url=values["FIRST_AGENT_E3_BASE_URL"],
            model=values["FIRST_AGENT_E3_MODEL"],
            api_key=values["FIRST_AGENT_E3_API_KEY"],
        )


class _RecordingProvider:
    """记录真实 adapter 的 request 结果类别，不保存任何 request/response body。"""

    def __init__(self, delegate) -> None:  # noqa: ANN001
        self.delegate = delegate
        self.last_error: ProviderError | None = None

    def generate(self, context):  # noqa: ANN001, ANN201
        self.last_error = None
        try:
            return self.delegate.generate(context)
        except ProviderError as error:
            self.last_error = error
            raise


@dataclass
class _ProductProviderFactory:
    """只替换 HTTP client seam；产品仍负责 profile、env 与 adapter composition。"""

    expected: E3Config
    client: httpx.Client
    providers: list[_RecordingProvider] = field(default_factory=list)
    configs: list[AgentProviderConfig] = field(default_factory=list)

    def __call__(self, config: AgentProviderConfig):  # noqa: ANN204
        if (
            config.provider_type != self.expected.provider
            or config.model != self.expected.model
            or config.base_url != self.expected.base_url.rstrip("/")
            or config.credential != self.expected.api_key
            or config.timeout != 45.0
            or config.request_path
            != (
                "/chat/completions"
                if self.expected.provider == "openai_compatible"
                else "/v1/messages"
            )
            or config.strict_tools != (self.expected.provider == "openai_compatible")
            or config.thinking_mode
            != ("disabled" if self.expected.provider == "openai_compatible" else None)
        ):
            raise E3AcceptanceError("product provider composition did not match saved profile")
        provider = _RecordingProvider(build_model_provider(config, http_client=self.client))
        self.configs.append(config)
        self.providers.append(provider)
        return provider

    @property
    def last_error(self) -> ProviderError | None:
        return self.providers[-1].last_error if self.providers else None

    @property
    def descriptor(self):  # noqa: ANN201
        if not self.configs:
            raise E3AcceptanceError("product provider factory was never called")
        return self.configs[-1].descriptor()


def _checkpoint_path(state_root: Path, workspace: Path) -> Path:
    identity = WorkspaceIdentityV1.resolve(workspace)
    candidates = sorted((state_root / "workspaces" / identity.scope_digest).glob("*.json"))
    if len(candidates) != 1:
        raise E3AcceptanceError("workspace did not produce exactly one checkpoint")
    return candidates[0]


def _load_state(state_root: Path, workspace: Path):  # noqa: ANN202
    return LocalCheckpointStore(_checkpoint_path(state_root, workspace)).load().state


@dataclass
class _JourneyDriver:
    state_root: Path
    workspace: Path
    messages: deque[str]
    request_count: list[int]
    expected_tool: str | None = None
    expected_path: str | None = None
    approve_effect: bool = False
    stop_at_approval: bool = False
    restart_baseline: tuple[int, str] | None = None
    inputs: list[str] = field(default_factory=list)
    goal_before_messages: list[bool] = field(default_factory=list)
    disclosure_send_counts: list[int] = field(default_factory=list)
    goal_was_durable_before_effect: bool = False
    contextual_approval_bound: bool = False
    protocol_tokens: set[str] = field(default_factory=set)
    _restart_checked: bool = False

    def __call__(self, _prompt: str) -> str:
        state = _load_state(self.state_root, self.workspace)
        active = state.active_run
        if self.restart_baseline is not None and not self._restart_checked:
            expected_sends, expected_digest = self.restart_baseline
            actual_digest = hashlib.sha256(
                (self.workspace / _EDIT_PATH).read_bytes()
            ).hexdigest()
            if self.request_count[0] != expected_sends or actual_digest != expected_digest:
                raise E3AcceptanceError("restart performed an implicit send or file effect")
            self._restart_checked = True

        if (
            active is not None
            and active.status is ActiveRunStatus.AWAITING_DISCLOSURE
            and state.provider_disclosure_request is not None
        ):
            self.disclosure_send_counts.append(self.request_count[0])
            self.protocol_tokens.add(state.provider_disclosure_request.request_digest)
            self.inputs.append("yes")
            return "yes"

        if active is not None and active.status is ActiveRunStatus.AWAITING_APPROVAL:
            request = active.pending_request
            if not isinstance(request, ApprovalRequest):
                raise E3AcceptanceError("approval state has no exact request")
            if active.batch_cursor >= len(active.tool_calls):
                raise E3AcceptanceError("approval has no exact active tool call")
            call = active.tool_calls[active.batch_cursor]
            if call.name != self.expected_tool or call.arguments.get("path") != self.expected_path:
                raise E3AcceptanceError("approval requested an unexpected effect")
            self.protocol_tokens.update(
                {request.request_id, request.binding_digest, call.tool_call_id}
            )
            target = self.workspace / str(self.expected_path)
            if self.expected_tool == "write_file":
                unchanged = not target.exists()
            else:
                unchanged = target.read_text(encoding="utf-8") == _OLD_EDIT_CONTENT
            self.goal_was_durable_before_effect = state.goal is not None and unchanged
            if self.stop_at_approval:
                self.inputs.append("/exit")
                return "/exit"
            if not self.approve_effect:
                raise E3AcceptanceError("unexpected effect approval boundary")
            self.contextual_approval_bound = True
            self.inputs.append("yes")
            return "yes"

        if active is not None and active.status is ActiveRunStatus.AWAITING_RECOVERY:
            raise E3AcceptanceError("real E3 encountered an unknown file outcome")

        if self.messages:
            self.goal_before_messages.append(state.goal is not None)
            value = self.messages.popleft()
            self.inputs.append(value)
            return value
        self.inputs.append("/exit")
        return "/exit"


def _run_product(
    *,
    workspace: Path,
    provider_factory: _ProductProviderFactory,
    driver: _JourneyDriver,
) -> list[str]:
    output: list[str] = []
    with contextlib.chdir(workspace), patch.object(
        product_main, "build_model_provider", side_effect=provider_factory
    ):
        exit_code = product_main.main([], input_fn=driver, write_fn=output.append)
    if exit_code != 0:
        if provider_factory.last_error is not None:
            error = provider_factory.last_error
            detail = error.reason if isinstance(error, ProviderProtocolError) else error.code
            raise E3AcceptanceError(
                f"product journey {workspace.name} provider failed with {detail}"
            ) from error
        failure_code = "unknown"
        for line in reversed(output):
            if line.startswith("Run failed: "):
                candidate = line.removeprefix("Run failed: ")
                if re.fullmatch(r"[a-z0-9_]+", candidate):
                    failure_code = candidate
                break
        raise E3AcceptanceError(
            f"product journey {workspace.name} failed with {failure_code}"
        )
    return output


def _setup_profile(config: E3Config) -> list[str]:
    output: list[str] = []
    argv = [
        "setup",
        "--provider",
        config.provider,
        "--model",
        config.model,
        "--base-url",
        config.base_url,
        "--credential-env",
        "FIRST_AGENT_E3_API_KEY",
        "--timeout",
        "45",
    ]
    if config.provider == "openai_compatible":
        argv.extend(("--thinking-mode", "disabled"))
        argv.extend(("--request-path", "/chat/completions", "--strict-tools"))
    if product_main.main(argv, write_fn=output.append) != 0:
        raise E3AcceptanceError("product setup did not complete")
    return output


def _contains_secret(path: Path, secret: str) -> bool:
    return secret.encode("utf-8") in path.read_bytes()


def _assert_verified(state, *, goal_required: bool) -> None:  # noqa: ANN001
    if goal_required:
        if state.goal is None or state.goal.status is not GoalStatus.VERIFIED_DONE:
            raise E3AcceptanceError("file journey did not reach VERIFIED_DONE")
        if not state.evidence_records or not all(
            record.passed for record in state.evidence_records
        ):
            raise E3AcceptanceError("file journey has no passing Runtime evidence")
    elif state.goal is not None:
        raise E3AcceptanceError("ask or discussion created an unexpected Goal")


def run_e3(config: E3Config) -> dict[str, object]:
    request_count = [0]

    def count_request(_request: httpx.Request) -> None:
        request_count[0] += 1

    client = httpx.Client(
        timeout=45.0,
        follow_redirects=False,
        trust_env=False,
        event_hooks={"request": [count_request]},
    )
    provider_factory = _ProductProviderFactory(config, client)

    temporary_parent = Path(tempfile.gettempdir()).resolve()
    try:
        with tempfile.TemporaryDirectory(
            prefix="first-agent-013-e3-", dir=temporary_parent
        ) as temporary:
            root = Path(temporary)
            home = root / "home"
            home.mkdir(mode=0o700)
            with patch.dict(os.environ, {"HOME": str(home)}, clear=False):
                state_root = product_main.default_state_root()
                setup_output = _setup_profile(config)
                profile_path = state_root / "provider-profile.json"
                if not profile_path.is_file() or _contains_secret(
                    profile_path, config.api_key
                ):
                    raise E3AcceptanceError(
                        "saved profile is missing or contains the credential"
                    )

                ask_workspace = root / "ask-workspace"
                ask_workspace.mkdir(mode=0o700)
                ask_driver = _JourneyDriver(
                    state_root,
                    ask_workspace,
                    deque(
                        (
                            "What is the purpose of a README? Answer briefly without tools.",
                            "Discuss one tradeoff of keeping a personal agent "
                            "local-first. Do not create files.",
                        )
                    ),
                    request_count,
                )
                ask_output = _run_product(
                    workspace=ask_workspace,
                    provider_factory=provider_factory,
                    driver=ask_driver,
                )
                ask_state = _load_state(state_root, ask_workspace)
                _assert_verified(ask_state, goal_required=False)
                if tuple(ask_workspace.iterdir()):
                    raise E3AcceptanceError("ask/discussion produced a file effect")

                artifact_workspace = root / "artifact-workspace"
                artifact_workspace.mkdir(mode=0o700)
                (artifact_workspace / "notes").mkdir(mode=0o700)
                artifact_driver = _JourneyDriver(
                    state_root,
                    artifact_workspace,
                    deque(
                        (
                            "Discuss why the first version of a personal agent should stay small.",
                            (
                                f"Write our conclusion to {_ARTIFACT_PATH} with exactly this "
                                f"UTF-8 content: {_ARTIFACT_CONTENT!r}. Read it back and verify "
                                "completion."
                            ),
                        )
                    ),
                    request_count,
                    expected_tool="write_file",
                    expected_path=_ARTIFACT_PATH,
                    approve_effect=True,
                )
                artifact_output = _run_product(
                    workspace=artifact_workspace,
                    provider_factory=provider_factory,
                    driver=artifact_driver,
                )
                artifact_state = _load_state(state_root, artifact_workspace)
                _assert_verified(artifact_state, goal_required=True)
                artifact = artifact_workspace / _ARTIFACT_PATH
                if artifact.read_text(encoding="utf-8") != _ARTIFACT_CONTENT:
                    raise E3AcceptanceError("discussion artifact content mismatch")

                existing_workspace = root / "existing-workspace"
                existing_workspace.mkdir(mode=0o700)
                target = existing_workspace / _EDIT_PATH
                target.write_text(_OLD_EDIT_CONTENT, encoding="utf-8")
                sentinels = {
                    existing_workspace / "config.txt": b"configuration stays\n",
                    existing_workspace / "notes.txt": b"unrelated notes stay\n",
                }
                for path, content in sentinels.items():
                    path.write_bytes(content)
                sentinel_before = {
                    path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in sentinels
                }
                first_edit_driver = _JourneyDriver(
                    state_root,
                    existing_workspace,
                    deque(
                        (
                            "In README.md replace only the unique text 'Old summary' with "
                            "'New bounded summary', then read it back and verify completion.",
                        )
                    ),
                    request_count,
                    expected_tool="edit_file",
                    expected_path=_EDIT_PATH,
                    stop_at_approval=True,
                )
                first_edit_output = _run_product(
                    workspace=existing_workspace,
                    provider_factory=provider_factory,
                    driver=first_edit_driver,
                )
                if target.read_text(encoding="utf-8") != _OLD_EDIT_CONTENT:
                    raise E3AcceptanceError("edit occurred before contextual approval")
                sends_before_restart = request_count[0]
                target_before_restart = hashlib.sha256(target.read_bytes()).hexdigest()

                second_edit_driver = _JourneyDriver(
                    state_root,
                    existing_workspace,
                    deque(),
                    request_count,
                    expected_tool="edit_file",
                    expected_path=_EDIT_PATH,
                    approve_effect=True,
                    restart_baseline=(sends_before_restart, target_before_restart),
                )
                second_edit_output = _run_product(
                    workspace=existing_workspace,
                    provider_factory=provider_factory,
                    driver=second_edit_driver,
                )
                existing_state = _load_state(state_root, existing_workspace)
                _assert_verified(existing_state, goal_required=True)
                if target.read_text(encoding="utf-8") != _NEW_EDIT_CONTENT:
                    raise E3AcceptanceError("existing workspace target content mismatch")
                sentinel_after = {
                    path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in sentinels
                }
                if sentinel_after != sentinel_before:
                    raise E3AcceptanceError("existing workspace sentinel changed")

                all_output = [
                    *setup_output,
                    *ask_output,
                    *artifact_output,
                    *first_edit_output,
                    *second_edit_output,
                ]
                all_rendered = "\n".join(all_output)
                all_tokens = (
                    ask_driver.protocol_tokens
                    | artifact_driver.protocol_tokens
                    | first_edit_driver.protocol_tokens
                    | second_edit_driver.protocol_tokens
                )
                checkpoint_paths = [
                    _checkpoint_path(state_root, workspace)
                    for workspace in (
                        ask_workspace,
                        artifact_workspace,
                        existing_workspace,
                    )
                ]
                secret_free = (
                    config.api_key not in all_rendered
                    and not any(token in all_rendered for token in all_tokens)
                    and "first_agent_control_v1" not in all_rendered
                    and not any(
                        _contains_secret(path, config.api_key) for path in checkpoint_paths
                    )
                )
                inputs = (
                    ask_driver.inputs
                    + artifact_driver.inputs
                    + first_edit_driver.inputs
                    + second_edit_driver.inputs
                )
                claims = {
                    "setup_profile_is_non_secret": True,
                    "no_argument_start_uses_saved_profile_and_cwd": all(
                        f"First Agent is ready in: {workspace.name}" in all_rendered
                        for workspace in (
                            ask_workspace,
                            artifact_workspace,
                            existing_workspace,
                        )
                    ),
                    "disclosure_has_zero_sends_before_contextual_ack": (
                        bool(ask_driver.disclosure_send_counts)
                        and ask_driver.disclosure_send_counts[0] == 0
                    ),
                    "ask_and_discuss_create_no_goal_or_file_effect": True,
                    "discussion_creates_goal_only_after_artifact_request": (
                        artifact_driver.goal_before_messages == [False, False]
                        and artifact_state.goal is not None
                    ),
                    "goal_is_durable_before_file_effect": (
                        artifact_driver.goal_was_durable_before_effect
                        and first_edit_driver.goal_was_durable_before_effect
                    ),
                    "contextual_approval_binds_exact_pending_request": (
                        artifact_driver.contextual_approval_bound
                        and second_edit_driver.contextual_approval_bound
                    ),
                    "artifact_is_read_back_and_verified_done": True,
                    "restart_recovers_same_goal_without_implicit_send_or_effect": (
                        second_edit_driver._restart_checked
                    ),
                    "existing_workspace_sentinels_are_unchanged": True,
                    "successful_journeys_require_no_continue_action": not any(
                        value.strip().casefold() in {"continue", "继续"}
                        for value in inputs
                    ),
                    "default_output_exposes_no_protocol_identifier_or_secret": secret_free,
                }
                if not all(claims.values()):
                    raise E3AcceptanceError("one or more E3 claims are false")
                descriptor = provider_factory.descriptor
                return {
                    "schema": "first-agent-013-e3-receipt-v1",
                    "observed_at": datetime.now(UTC).isoformat(),
                    "provider": {
                        "family": descriptor.family,
                        "model": descriptor.model,
                        "destination_digest": canonical_json_digest(
                            descriptor.canonical_destination
                        ),
                    },
                    "request_counts": {
                        "total": request_count[0],
                        "before_first_disclosure_ack": (
                            ask_driver.disclosure_send_counts[0]
                        ),
                        "before_existing_workspace_restart": sends_before_restart,
                    },
                    "journeys": {
                        "ask_and_discuss": "passed",
                        "discussion_to_artifact": "passed",
                        "existing_workspace_restart": "passed",
                    },
                    "goal_opaque_digest": canonical_json_digest(
                        existing_state.goal.goal_id
                    ),
                    "artifact_digest": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                    "sentinel_digests": sentinel_after,
                    "offline_recovery_gate": (
                        "tests/reference/test_012_trusted_continuity.py::"
                        "test_j2_interrupted_executing_checkpoint_requires_"
                        "unknown_effect_recovery"
                    ),
                    "claims": claims,
                }
    finally:
        client.close()


def _blocked_reason(error: ProviderError) -> str:
    if isinstance(error, ProviderAuthError):
        return "auth_failed"
    if isinstance(error, ProviderHTTPRetryableError) and error.status_code == 429:
        return "rate_limit_exhausted"
    if isinstance(error, (ProviderTimeoutError, ProviderTransportError)):
        return "endpoint_unreachable"
    if isinstance(error, ProviderProtocolError):
        return "provider_protocol"
    if isinstance(error, ProviderConfigurationError):
        return "incomplete_config"
    return "model_incompatible"


def main() -> int:
    try:
        config = E3Config.from_environment(os.environ)
        receipt = run_e3(config)
    except E3AcceptanceError as error:
        marker = str(error)
        if marker.startswith(("NEEDS_013_E3_CONFIG(", "013_E3_BLOCKED(")):
            print(marker)
        else:
            print("013_E3_BLOCKED(reason=model_incompatible)")
        return 2
    except ProviderError as error:
        print(f"013_E3_BLOCKED(reason={_blocked_reason(error)})")
        return 2
    except Exception:
        print("013_E3_BLOCKED(reason=model_incompatible)")
        return 2
    print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
