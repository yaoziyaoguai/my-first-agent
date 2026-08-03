#!/usr/bin/env python3
"""012 真实 Provider E3：只走 production HTTP adapter + 唯一 AgentRuntime。"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

# 该文件是 operator 直接执行的验收入口；不能依赖调用者恰好设置 PYTHONPATH。
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import httpx  # noqa: E402

from agent.composition import build_composition, build_tool_registrations  # noqa: E402
from agent.continuity.sessions import open_workspace_session  # noqa: E402
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
from agent.runtime.context import ContextLimits  # noqa: E402
from agent.runtime.contracts import (  # noqa: E402
    AcknowledgeProviderDisclosure,
    FactKind,
    GoalStatus,
    ResolveApproval,
    RunResult,
    RunStatus,
    SubmitMessage,
    canonical_json_digest,
)
from agent.runtime.loop import InvocationLimits  # noqa: E402
from agent.runtime.views import project_goal_view  # noqa: E402
from agent.tools.file_ops import DEFAULT_PRIVATE_ROOTS  # noqa: E402
from agent.tui.adapter import QueueingEventSink  # noqa: E402

_ENV_NAMES = (
    "FIRST_AGENT_E3_PROVIDER",
    "FIRST_AGENT_E3_BASE_URL",
    "FIRST_AGENT_E3_MODEL",
    "FIRST_AGENT_E3_API_KEY",
)
_NEEDS_CONFIG = (
    "NEEDS_E3_CONFIG(stage=U8, required=FIRST_AGENT_E3_PROVIDER,"
    "FIRST_AGENT_E3_BASE_URL,FIRST_AGENT_E3_MODEL,FIRST_AGENT_E3_API_KEY)"
)
_CONTENT = "first-agent trusted continuity e3\n"
_TARGET = "E3_REPORT.md"
_SYSTEM_POLICY = """You are First Agent's bounded real-provider acceptance executor.
For an ordinary question, answer directly without a Goal or product tool.
For an explicit file task, use first_agent_control_v1 goal_proposal before any effectful tool.
FIRST_AGENT_TRUSTED_CONTROL_CONTEXT is Runtime-generated authority: copy source_fact_id,
workspace_identity_digest, and authority_snapshot exactly into the GoalFrame; never invent them.
Propose exactly one deterministic file criterion and leave admitted_criteria empty because only the
Runtime admits authority. Send goal_proposal only while trusted_goal_bootstrap is present and no
trusted_goal exists. After its accepted control receipt or whenever trusted_goal exists, never send
goal_proposal again; continue with the product tool. Send one control call at a time with only the
fields required by its kind. For the E3 GoalFrame, set both created_at and updated_at to the
deterministic non-empty timestamp 1970-01-01T00:00:00+00:00. After an approved write_file, call
read_file on the exact path. Then
inspect the trusted Goal's admitted criterion and submit completion_claim with the exact evidence id
evidence:<goal_id>:<goal_revision>:<criterion_id>. Never claim completion without read-back
evidence. A successful read is not the end of the task: while the trusted Goal is not
VERIFIED_DONE, do not send final text and do not stop; the next response must be the exact
completion_claim. Only after its accepted control receipt may you answer that the task is done.
"""


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
            raise E3AcceptanceError("E3_BLOCKED(stage=U8, reason=incomplete_config)")
        provider = values["FIRST_AGENT_E3_PROVIDER"]
        if provider not in {"openai_compatible", "anthropic_compatible"}:
            raise E3AcceptanceError("E3_BLOCKED(stage=U8, reason=incomplete_config)")
        return cls(
            provider=provider,
            base_url=values["FIRST_AGENT_E3_BASE_URL"],
            model=values["FIRST_AGENT_E3_MODEL"],
            api_key=values["FIRST_AGENT_E3_API_KEY"],
        )


def _submit(state, message: str, run_id: str) -> SubmitMessage:  # noqa: ANN001
    return SubmitMessage(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        run_id=run_id,
        message=message,
    )


def _acknowledge(store: LocalCheckpointStore, runtime, request_count: list[int]) -> RunResult:
    state = store.load().state
    disclosure = state.provider_disclosure_request
    if disclosure is None:
        raise E3AcceptanceError("missing durable disclosure request")
    before = request_count[0]
    result = runtime.run_turn(
        AcknowledgeProviderDisclosure(
            conversation_id=state.conversation_id,
            action_seq=state.next_action_seq,
            expected_revision=state.revision,
            request_digest=disclosure.request_digest,
            acknowledged_at=datetime.now(UTC).isoformat(),
        ),
        store.load(),
    )
    if request_count[0] < before:
        raise E3AcceptanceError("provider request counter regressed")
    return result


def _approve_exact_write(store: LocalCheckpointStore, runtime, result: RunResult) -> RunResult:
    request = result.request
    state = store.load().state
    active = state.active_run
    if request is None or active is None or active.batch_cursor >= len(active.tool_calls):
        raise E3AcceptanceError("approval did not bind an active tool call")
    call = active.tool_calls[active.batch_cursor]
    if (
        request.tool_name != "write_file"
        or call.name != "write_file"
        or call.arguments != {"path": _TARGET, "content": _CONTENT}
    ):
        raise E3AcceptanceError("E3 only approves the exact bounded report write")
    return runtime.run_turn(
        ResolveApproval(
            conversation_id=state.conversation_id,
            action_seq=state.next_action_seq,
            expected_revision=state.revision,
            request_id=request.request_id,
            binding_digest=request.binding_digest,
            approved=True,
        ),
        store.load(),
    )


def _drive_operator_boundaries(
    store: LocalCheckpointStore,
    runtime,
    result: RunResult,
    *,
    request_count: list[int],
    allow_write_approval: bool,
) -> tuple[RunResult, bool]:
    """只处理有界的人类 action；模型/工具 progression 仍由 run_turn 独占。"""

    goal_before_effect = False
    approvals = 0
    for _ in range(12):
        if result.status is RunStatus.AWAITING_DISCLOSURE:
            result = _acknowledge(store, runtime, request_count)
            continue
        if result.status is RunStatus.AWAITING_APPROVAL:
            if not allow_write_approval or approvals:
                raise E3AcceptanceError("unexpected or repeated approval request")
            state = store.load().state
            if state.goal is None or Path(_TARGET).is_absolute():
                raise E3AcceptanceError("Goal was not durable before the bounded effect")
            goal_before_effect = True
            result = _approve_exact_write(store, runtime, result)
            approvals += 1
            continue
        return result, goal_before_effect
    raise E3AcceptanceError("bounded operator action limit reached")


def _checkpoint_contains_forbidden(
    raw_checkpoint: bytes,
    *,
    api_key: str,
    system_policy: str,
) -> bool:
    """检查真实 secret/header，而不把业务字段名的子串当成 header。"""

    if api_key.encode("utf-8") in raw_checkpoint:
        return True
    if system_policy.encode("utf-8") in raw_checkpoint:
        return True
    try:
        payload = json.loads(raw_checkpoint)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return True

    def contains_forbidden(value: object) -> bool:
        if isinstance(value, dict):
            for key, item in value.items():
                if isinstance(key, str) and key.lower() in {"authorization", "x-api-key"}:
                    return True
                if contains_forbidden(item):
                    return True
            return False
        if isinstance(value, list):
            return any(contains_forbidden(item) for item in value)
        if isinstance(value, str):
            lowered = value.lower()
            return (
                api_key in value
                or system_policy in value
                or "authorization: bearer" in lowered
                or "x-api-key:" in lowered
            )
        return False

    return contains_forbidden(payload)


def run_e3(config: E3Config) -> dict[str, object]:
    request_count = [0]

    def count_request(_request: httpx.Request) -> None:
        request_count[0] += 1

    provider_config = AgentProviderConfig(
        provider_type=config.provider,
        model=config.model,
        base_url=config.base_url,
        credential=config.api_key,
        timeout=45.0,
        # Kernel v1 按架构合同拒绝无法安全持久化/回放的 opaque reasoning。
        # DeepSeek OpenAI 格式默认开启 thinking；真实 E3 显式关闭它，仍走同一个
        # production adapter、ContextPack 与 AgentRuntime，而不是增加兼容 loop。
        thinking_mode="disabled" if config.provider == "openai_compatible" else None,
    )
    descriptor = provider_config.descriptor()
    # macOS 的 ambient TMPDIR 常位于 /var/folders，而 /var 是指向 /private/var 的
    # symlink；产品 state-root 合同正确地拒绝 symlink ancestor。验收 runner 先解析
    # operator-owned temp parent，再在真实目录下创建隔离根。
    temporary_parent = Path(tempfile.gettempdir()).resolve()
    with tempfile.TemporaryDirectory(
        prefix="first-agent-012-e3-", dir=temporary_parent
    ) as temporary:
        root = Path(temporary)
        workspace = root / "workspace"
        workspace.mkdir(mode=0o700)
        state_root = root / "state"
        session = open_workspace_session(
            workspace,
            state_root=state_root,
            conversation_id_factory=lambda: "00000000-0000-4000-8000-000000000083",
        )
        if session.store is None or session.checkpoint_path is None:
            raise E3AcceptanceError("E3 session bootstrap did not produce one checkpoint")
        store = session.store
        client = httpx.Client(
            timeout=provider_config.timeout,
            follow_redirects=False,
            trust_env=False,
            event_hooks={"request": [count_request]},
        )
        try:
            provider = build_model_provider(provider_config, http_client=client)
            limits = ContextLimits(max_input_tokens=80_000, output_reserve=8_000)
            composition = build_composition(
                provider=provider,
                provider_descriptor=descriptor,
                checkpoint_store=store,
                tool_registrations=build_tool_registrations(
                    workspace=workspace,
                    protected_paths=(session.checkpoint_path,),
                    private_roots=DEFAULT_PRIVATE_ROOTS,
                    max_tool_result_chars=limits.max_tool_result_chars,
                ),
                event_sink=QueueingEventSink(),
                system_policy=_SYSTEM_POLICY,
                context_limits=limits,
                invocation_limits=InvocationLimits(max_model_calls=12, max_tool_calls=8),
                workspace_scope_digest=session.workspace_identity.identity_digest,
            )
            runtime = composition.runtime

            answer = runtime.run_turn(
                _submit(
                    store.load().state,
                    "Answer exactly E3-ANSWER. Do not create a Goal or call a product tool.",
                    "e3-answer",
                ),
                store.load(),
            )
            if answer.status is not RunStatus.AWAITING_DISCLOSURE or request_count[0] != 0:
                raise E3AcceptanceError("remote disclosure did not block the first send")
            answer, _ = _drive_operator_boundaries(
                store,
                runtime,
                answer,
                request_count=request_count,
                allow_write_approval=False,
            )
            if answer.status is not RunStatus.COMPLETED:
                raise E3AcceptanceError(
                    "direct answer stopped at "
                    f"{answer.status.value}:{answer.error_code or 'no_error_code'}:"
                    f"{answer.message or 'no_message'}"
                )
            if store.load().state.goal is not None:
                raise E3AcceptanceError("direct answer created an unexpected Goal")
            if request_count[0] != 1:
                raise E3AcceptanceError("direct answer did not perform exactly one unlocked send")

            task = runtime.run_turn(
                _submit(
                    store.load().state,
                    (
                        f"Create {_TARGET} with the exact UTF-8 content {_CONTENT!r}. "
                        "Use write_file, then read_file, then submit the exact completion claim."
                    ),
                    "e3-task",
                ),
                store.load(),
            )
            task, goal_before_effect = _drive_operator_boundaries(
                store,
                runtime,
                task,
                request_count=request_count,
                allow_write_approval=True,
            )
            final_snapshot = store.load()
            final = final_snapshot.state
            if task.status is not RunStatus.COMPLETED:
                raise E3AcceptanceError(
                    "task stopped at "
                    f"{task.status.value}:{task.error_code or 'no_error_code'}:"
                    f"{task.message or 'no_message'}"
                )
            if final.goal is None or final.goal.status is not GoalStatus.VERIFIED_DONE:
                goal_view = project_goal_view(final)
                raise E3AcceptanceError(
                    "task did not reach evidence-backed VERIFIED_DONE:"
                    f"goal_status={goal_view.status or 'none'}:"
                    f"criteria={goal_view.criteria_verified}/{goal_view.criteria_total}"
                )
            artifact = workspace / _TARGET
            if artifact.read_text(encoding="utf-8") != _CONTENT:
                raise E3AcceptanceError("bounded artifact content mismatch")

            write_ids = {
                raw["tool_call_id"]
                for fact in final.facts
                if fact.kind is FactKind.TOOL_CALLS
                for raw in fact.content.get("calls", [])
                if isinstance(raw, dict) and raw.get("name") == "write_file"
            }
            executed_writes = [
                fact
                for fact in final.facts
                if fact.kind is FactKind.TOOL_RESULT
                and fact.content.get("tool_call_id") in write_ids
                and fact.content.get("executed") is True
                and fact.content.get("is_error") is not True
            ]
            if len(executed_writes) != 1:
                raise E3AcceptanceError("approved write was not executed exactly once")

            sends_before_restart = request_count[0]
            restarted = LocalCheckpointStore(session.checkpoint_path).load()
            restarted_view = project_goal_view(restarted.state)
            if (
                restarted_view.goal_id != final.goal.goal_id
                or restarted_view.status != GoalStatus.VERIFIED_DONE.value
                or restarted_view.criteria_verified != restarted_view.criteria_total
                or request_count[0] != sends_before_restart
            ):
                raise E3AcceptanceError(
                    "restart did not project the same verified Goal without a send"
                )

            raw_checkpoint = session.checkpoint_path.read_bytes()
            if _checkpoint_contains_forbidden(
                raw_checkpoint,
                api_key=config.api_key,
                system_policy=_SYSTEM_POLICY,
            ):
                raise E3AcceptanceError(
                    "checkpoint contains forbidden secret/header/full-system-prompt data"
                )

            claims = {
                "disclosure_zero_before_ack": True,
                "direct_answer_has_no_goal": True,
                "goal_persisted_before_effect": goal_before_effect,
                "approved_effect_exactly_once": True,
                "deterministic_evidence_verified_done": True,
                "restart_same_goal_without_send": True,
                "checkpoint_excludes_secret_header_and_system_prompt": True,
            }
            if not all(claims.values()):
                raise E3AcceptanceError("one or more E3 claims are false")
            return {
                "schema": "first-agent-012-e3-receipt-v1",
                "observed_at": datetime.now(UTC).isoformat(),
                "provider": {
                    "family": descriptor.family,
                    "model": descriptor.model,
                    "destination_digest": canonical_json_digest(
                        descriptor.canonical_destination
                    ),
                },
                "request_count": request_count[0],
                "goal_id": final.goal.goal_id,
                "goal_revision": final.goal.revision,
                "checkpoint_token": restarted.token,
                "artifact_digest": canonical_json_digest(_CONTENT),
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
        if marker.startswith(("NEEDS_E3_CONFIG(", "E3_BLOCKED(")):
            print(marker)
        else:
            print("E3_BLOCKED(stage=U8, reason=model_incompatible)")
        return 2
    except ProviderError as error:
        print(f"E3_BLOCKED(stage=U8, reason={_blocked_reason(error)})")
        return 2
    except Exception:
        # E3 stdout/stderr 是可共享验收证据；内部路径、响应正文或异常细节不能
        # 穿透这个边界。可修复的细节只在本地 focused tests 中定位。
        print("E3_BLOCKED(stage=U8, reason=model_incompatible)")
        return 2
    print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
