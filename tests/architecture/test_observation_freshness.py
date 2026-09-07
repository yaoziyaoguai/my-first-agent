"""观察新鲜度契约：实际执行的 effect 使旧可变观察过期（公共边界旅程）。

同一 model run 内（含 checkpoint 恢复重建的 Runtime），Runtime 已 durable
记录一个实际执行的非 READ_ONLY tool result 之后，此前成功的“可变观察”
（workspace read/search 与 browser_observe）不得再被 exact product-request
dedup 当作仍然新鲜的旧事实而阻断同参数重新观察。effectful 请求自身的
exact dedup、approval/lease、未知结果 recovery 与 no-progress 保护不受影响。

所有旅程都从 typed action + ``AgentRuntime.run_turn`` 进入并经过真实
``KernelToolRuntime`` 治理边界（真实 file/browser/local_process 工具与
approval/lease 铸造），不做私有 inventory 直连。
"""

from __future__ import annotations

import os
import stat
from datetime import UTC, datetime
from pathlib import Path

from agent.browser.contracts import (
    BrowserActionOutcome,
    BrowserActionReceiptV1,
    BrowserCleanupOutcome,
    BrowserCleanupReceiptV1,
    BrowserHandleV1,
    BrowserObservationV1,
)
from agent.browser.profile_store import BrowserProfileStore
from agent.browser.session_store import BrowserSessionStore
from agent.browser.tools import build_browser_tools
from agent.process.tools import build_local_process_registration
from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    ActiveRunStatus,
    FactKind,
    ModelResponse,
    ModelToolCall,
    ResolveApproval,
    Resume,
    RunStatus,
    SubmitMessage,
)
from agent.runtime.loop import AgentRuntime, InvocationLimits
from agent.runtime.ports import RetryableProviderError
from agent.runtime.tools import KernelToolRuntime
from agent.tools.file_ops import build_file_tool_registrations
from tests.browser.profile_probe import DeterministicProcessIdentityProbe
from tests.kernel.fakes import (
    CollectingSink,
    InMemoryCheckpointStore,
    ScriptedProvider,
    conversation_with_active_goal,
    goal_noop_response,
)


def _end_of_script() -> RetryableProviderError:
    # 非终态 Goal 不接受 final prose，blocked_claim 又依赖真实证据裁决；
    # 旅程断言只关心 durable 工具执行序列，用可重试错误收尾最贴近既有
    # browser 测试模式，且不引入额外修复轮。
    return RetryableProviderError("fixture script reached its end")

CLOCK = "2026-08-28T10:00:00+00:00"
SESSION_REF = "session-0123456789abcdef"
ORIGIN = "https://site.example.test"


def _runtime(provider, registrations, store):  # noqa: ANN001, ANN202
    return AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="Be concise.",
            limits=ContextLimits(max_input_tokens=8_000, output_reserve=500),
        ),
        tool_runtime=KernelToolRuntime(registrations, clock=lambda: CLOCK),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-1",
    )


def _submit(state, run_id: str) -> SubmitMessage:  # noqa: ANN001
    return SubmitMessage(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        run_id=run_id,
        message="continue the requested task",
    )


def _approve(result, state) -> ResolveApproval:  # noqa: ANN001
    request = result.request
    assert request is not None
    return ResolveApproval(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        request_id=request.request_id,
        binding_digest=request.binding_digest,
        approved=True,
        approved_at=CLOCK,
    )


def _resume(state) -> Resume:  # noqa: ANN001
    return Resume(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
    )


def _executed_results(state, *tool_call_ids: str) -> tuple[dict, ...]:  # noqa: ANN001
    wanted = set(tool_call_ids)
    return tuple(
        fact.content
        for fact in state.facts
        if fact.kind is FactKind.TOOL_RESULT
        and fact.content.get("tool_call_id") in wanted
        and fact.content.get("executed") is True
    )


# ---------------------------------------------------------------- browser ---

def _browser_observation(index: int) -> BrowserObservationV1:
    """确定性 observation；不同 index 产生不同 observation_digest。"""

    return BrowserObservationV1(
        session_ref=SESSION_REF,
        page_id=SESSION_REF,
        frame_id="main",
        navigation_revision=1 + index,
        browser_revision="b" * 64,
        profile_revision=None,
        canonical_url=f"{ORIGIN}/page",
        canonical_origin=ORIGIN,
        frame_tree_digest="f" * 64,
        aria_projection=f"link Docs v{index}",
        element_refs=(),
        node_count=1,
        byte_size=13,
        truncated=False,
        observed_at=datetime(2026, 8, 28, 10, 0, tzinfo=UTC).timestamp(),
    )


class _ReObservingEnvironment:
    """每次 observe 返回新 digest 的 deterministic browser adapter。"""

    def __init__(self) -> None:
        self.observed: list[str] = []
        self.executed: list[str] = []

    def open(self, spec) -> BrowserHandleV1:  # noqa: ANN001
        self.opened_spec = spec
        return BrowserHandleV1(
            session_ref=SESSION_REF,
            mode=spec.mode,
            authority_digest=spec.identity_digest,
        )

    def observe(self, handle) -> BrowserObservationV1:  # noqa: ANN001
        self.observed.append(handle.session_ref)
        return _browser_observation(len(self.observed) - 1)

    def execute(self, handle, action, *, binding=None) -> BrowserActionReceiptV1:  # noqa: ANN001
        self.executed.append(handle.session_ref)
        return BrowserActionReceiptV1(
            action_digest=action.identity_digest,
            pre_observation_digest=action.observation_digest,
            post_observation_digest="2" * 64,
            outcome=BrowserActionOutcome.EFFECT_APPLIED,
        )

    def close(self, handle) -> BrowserCleanupReceiptV1:  # noqa: ANN001
        return BrowserCleanupReceiptV1(
            session_ref=handle.session_ref,
            outcome=BrowserCleanupOutcome.CLEANED,
        )


def _browser_registrations(environment, tmp_path):  # noqa: ANN001, ANN202
    return build_browser_tools(
        environment=environment,
        profile_store=BrowserProfileStore(
            root=tmp_path / "profiles",
            process_probe=DeterministicProcessIdentityProbe(),
        ),
        session_store=BrowserSessionStore(root=tmp_path / "sessions"),
        browser_identity_digest="b" * 64,
        clock=lambda: CLOCK,
        monotonic_clock=lambda: 1000.0,
    ).registrations


def test_browser_reobservation_after_act_returns_new_observation(tmp_path) -> None:  # noqa: ANN001
    """browser_observe -> browser_act -> 同 session_ref browser_observe。

    底层 observe 必须真的执行两次、act 一次；第二次返回新 observation
    digest，而不是被旧观察的 exact dedup 当作重复旧事实抑制。
    """

    environment = _ReObservingEnvironment()
    state = conversation_with_active_goal()
    store = InMemoryCheckpointStore(state)
    first_digest = _browser_observation(0).observation_digest
    observe_arguments = {"session_ref": SESSION_REF}
    provider = ScriptedProvider(
        goal_noop_response("delta-browser-observe"),
        ModelResponse(
            (ModelToolCall("open-1", "browser_open", {"mode": "public_read_ephemeral"}),)
        ),
        ModelResponse((ModelToolCall("observe-1", "browser_observe", observe_arguments),)),
        ModelResponse(
            (
                ModelToolCall(
                    "act-1",
                    "browser_act",
                    {
                        "session_ref": SESSION_REF,
                        "kind": "navigate",
                        "observation_digest": first_digest,
                        "page_id": SESSION_REF,
                        "frame_id": "main",
                        "params": {"url": f"{ORIGIN}/docs"},
                    },
                ),
            )
        ),
        ModelResponse((ModelToolCall("observe-2", "browser_observe", observe_arguments),)),
        _end_of_script(),
    )
    runtime = _runtime(
        provider, _browser_registrations(environment, tmp_path), store
    )

    paused = runtime.run_turn(_submit(state, "run-browser-fresh"), store.load())
    assert paused.status is RunStatus.AWAITING_APPROVAL  # browser_open 审批

    resumed = runtime.run_turn(
        _approve(paused, store.load().state), store.load()
    )
    assert resumed.status is RunStatus.FAILED_RETRYABLE

    final = store.load().state
    # 底层 observe 两次、act 一次。
    assert environment.observed == [SESSION_REF, SESSION_REF]
    assert environment.executed == [SESSION_REF]
    # 两个 observe 都真实执行，且第二次返回新 digest。
    observed = _executed_results(final, "observe-1", "observe-2")
    assert len(observed) == 2
    digests = [
        result["metadata"]["observation_digest"] for result in observed
    ]
    assert digests[0] == first_digest
    assert digests[1] == _browser_observation(1).observation_digest
    assert digests[0] != digests[1]


# ------------------------------------------------- file + local_process ---

def _process_workspace(tmp_path, script_text: str) -> tuple[Path, tuple]:  # noqa: ANN202
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "note.txt").write_text("old-content", encoding="utf-8")
    script = workspace / "mutate-note"
    script.write_text(script_text, encoding="utf-8")
    os.chmod(script, stat.S_IRWXU)
    registrations = (
        *build_file_tool_registrations(workspace),
        build_local_process_registration(
            workspace=workspace, captured_path="/usr/bin:/bin"
        ),
    )
    return workspace, registrations


def test_read_after_executed_local_process_sees_new_content(tmp_path) -> None:  # noqa: ANN001
    """read_file -> local_process 真实执行改文件 -> 同参数 read_file。

    底层 read 必须执行两次、effect 一次；第二次读到新内容。
    """

    workspace, registrations = _process_workspace(
        tmp_path, "#!/bin/sh\nprintf 'new-content' > note.txt\n"
    )
    state = conversation_with_active_goal()
    store = InMemoryCheckpointStore(state)
    read_arguments = {"path": "note.txt"}
    provider = ScriptedProvider(
        goal_noop_response("delta-read-fresh"),
        ModelResponse((ModelToolCall("read-1", "read_file", read_arguments),)),
        ModelResponse(
            (
                ModelToolCall(
                    "proc-1",
                    "local_process",
                    {
                        "executable": "mutate-note",
                        "argv": [],
                        "cwd": ".",
                        "profile": "short",
                    },
                ),
            )
        ),
        ModelResponse((ModelToolCall("read-2", "read_file", read_arguments),)),
        _end_of_script(),
    )
    runtime = _runtime(provider, registrations, store)

    paused = runtime.run_turn(_submit(state, "run-read-fresh"), store.load())
    # 第一次 read 已真实执行（fixture 有效性前提），local_process 等待审批。
    assert paused.status is RunStatus.AWAITING_APPROVAL
    assert len(_executed_results(store.load().state, "read-1")) == 1

    resumed = runtime.run_turn(_approve(paused, store.load().state), store.load())
    assert resumed.status is RunStatus.FAILED_RETRYABLE

    final = store.load().state
    # effect 恰好执行一次，文件已改变。
    assert (workspace / "note.txt").read_text(encoding="utf-8") == "new-content"
    assert len(_executed_results(final, "proc-1")) == 1
    # 同参数 read 重新执行且返回新内容。
    reads = _executed_results(final, "read-1", "read-2")
    assert len(reads) == 2
    assert "old-content" in reads[0]["text"]
    assert "new-content" in reads[1]["text"]


def test_read_after_failed_effect_execution_still_refreshes_observation(
    tmp_path,
) -> None:  # noqa: ANN001
    """executed=True,is_error=True 的 effect 同样使旧观察过期。

    失败的 local_process（exit 7）已经真实执行过，保守起见旧 read 不得
    继续抑制同参数重新观察。
    """

    workspace, registrations = _process_workspace(
        tmp_path, "#!/bin/sh\nexit 7\n"
    )
    state = conversation_with_active_goal()
    store = InMemoryCheckpointStore(state)
    read_arguments = {"path": "note.txt"}
    provider = ScriptedProvider(
        goal_noop_response("delta-read-error-effect"),
        ModelResponse((ModelToolCall("read-1", "read_file", read_arguments),)),
        ModelResponse(
            (
                ModelToolCall(
                    "proc-1",
                    "local_process",
                    {
                        "executable": "mutate-note",
                        "argv": [],
                        "cwd": ".",
                        "profile": "short",
                    },
                ),
            )
        ),
        ModelResponse((ModelToolCall("read-2", "read_file", read_arguments),)),
        _end_of_script(),
    )
    runtime = _runtime(provider, registrations, store)

    paused = runtime.run_turn(_submit(state, "run-read-error-effect"), store.load())
    assert paused.status is RunStatus.AWAITING_APPROVAL

    resumed = runtime.run_turn(_approve(paused, store.load().state), store.load())
    assert resumed.status is RunStatus.FAILED_RETRYABLE

    final = store.load().state
    effects = _executed_results(final, "proc-1")
    assert len(effects) == 1
    assert effects[0]["is_error"] is True
    # 失败 effect 之后同参数 read 仍重新执行。
    assert len(_executed_results(final, "read-1", "read-2")) == 2


def test_rebuilt_runtime_resumes_with_fresh_read_and_no_effect_replay(
    tmp_path,
) -> None:  # noqa: ANN001
    """durable effect result 之后重建 Runtime 并 Resume：fresh read 必须由
    inventory 从 durable facts 恢复失效语义。

    第一个 Runtime 完成 read-1、执行并 durable 记录 proc-1 result，随后
    provider 抛 RetryableProviderError 使 active run 进入 PAUSED_RETRYABLE。
    重建的第二个 Runtime 只能经由 durable facts 恢复“effect 已使旧可变
    观察过期”的语义——read-2 允许重新执行并读到新内容，proc-1 不重放
    （append 型脚本：重放一次 note.txt 为 ``old-contentx``，两次为
    ``old-contentxx``）。
    """

    workspace, registrations = _process_workspace(
        tmp_path, "#!/bin/sh\nprintf 'x' >> note.txt\n"
    )
    state = conversation_with_active_goal()
    store = InMemoryCheckpointStore(state)
    read_arguments = {"path": "note.txt"}
    provider = ScriptedProvider(
        goal_noop_response("delta-rebuild-fresh"),
        ModelResponse((ModelToolCall("read-1", "read_file", read_arguments),)),
        ModelResponse(
            (
                ModelToolCall(
                    "proc-1",
                    "local_process",
                    {
                        "executable": "mutate-note",
                        "argv": [],
                        "cwd": ".",
                        "profile": "short",
                    },
                ),
            )
        ),
        # proc-1 durable 之后、read-2 之前的下一次 provider 调用失败：
        # 中断点选在 effect result 已 durable、重观察尚未发生之间。
        _end_of_script(),
        ModelResponse((ModelToolCall("read-2", "read_file", read_arguments),)),
        _end_of_script(),
    )
    runtime = _runtime(provider, registrations, store)

    paused = runtime.run_turn(_submit(state, "run-rebuild-fresh"), store.load())
    assert paused.status is RunStatus.AWAITING_APPROVAL
    assert len(_executed_results(store.load().state, "read-1")) == 1

    # 批准后 proc-1 真实执行并 durable 记录 result；紧接着的 provider 调用
    # 抛 RetryableProviderError，run 暂停为 PAUSED_RETRYABLE。
    interrupted = runtime.run_turn(
        _approve(paused, store.load().state), store.load()
    )
    assert interrupted.status is RunStatus.FAILED_RETRYABLE
    interrupted_state = store.load().state
    active = interrupted_state.active_run
    assert active is not None
    assert active.status is ActiveRunStatus.PAUSED_RETRYABLE
    # 重建前明确断言：proc-1 executed result 已 durable，文件恰好被修改一次。
    assert len(_executed_results(interrupted_state, "proc-1")) == 1
    assert (workspace / "note.txt").read_text(encoding="utf-8") == "old-contentx"

    # 重建 Runtime（模拟 crash/重启后 Resume）：新实例共享同一个 checkpoint
    # store 与同一个已推进的 ScriptedProvider，工具链由新 composition 重建；
    # read-2 是否允许重新执行完全取决于从 durable facts 恢复的 inventory。
    rebuilt = _runtime(
        provider,
        (
            *build_file_tool_registrations(workspace),
            build_local_process_registration(
                workspace=workspace, captured_path="/usr/bin:/bin"
            ),
        ),
        store,
    )
    resumed = rebuilt.run_turn(_resume(store.load().state), store.load())
    assert resumed.status is RunStatus.FAILED_RETRYABLE

    final = store.load().state
    # proc-1 未重放（append 只发生一次），read 在新 Runtime 内重新执行。
    assert (workspace / "note.txt").read_text(encoding="utf-8") == "old-contentx"
    assert len(_executed_results(final, "proc-1")) == 1
    assert len(_executed_results(final, "read-1", "read-2")) == 2
    reads = _executed_results(final, "read-2")
    assert "old-contentx" in reads[0]["text"]


def test_duplicate_observation_without_intervening_effect_stays_suppressed(
    tmp_path,
) -> None:  # noqa: ANN001
    """无 effect 介入时，同参数重复观察仍被 exact dedup 抑制（现状锁定）。"""

    workspace, registrations = _process_workspace(tmp_path, "#!/bin/sh\nexit 0\n")
    state = conversation_with_active_goal()
    store = InMemoryCheckpointStore(state)
    read_arguments = {"path": "note.txt"}
    provider = ScriptedProvider(
        goal_noop_response("delta-no-effect-dedup"),
        ModelResponse((ModelToolCall("read-1", "read_file", read_arguments),)),
        ModelResponse((ModelToolCall("read-2", "read_file", read_arguments),)),
        _end_of_script(),
    )
    runtime = _runtime(provider, registrations, store)

    result = runtime.run_turn(_submit(state, "run-no-effect-dedup"), store.load())
    assert result.status is RunStatus.FAILED_RETRYABLE

    final = store.load().state
    assert len(_executed_results(final, "read-1")) == 1
    duplicate = next(
        fact.content
        for fact in final.facts
        if fact.kind is FactKind.TOOL_RESULT
        and fact.content.get("tool_call_id") == "read-2"
    )
    assert duplicate["executed"] is False
    assert "Duplicate request suppressed" in duplicate["text"]
