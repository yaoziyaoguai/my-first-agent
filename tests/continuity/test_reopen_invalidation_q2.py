"""Q2（2026-10-11 收口包）：验证失效语义的持久化与 compaction 证据。

合同要求（WORK_ITEMS Q2 / RC-01 / RC-02）：

- 与 RC-01/02 共用**真实临时 checkpoint** 的 save → owner close → 新实例
  reopen；用产物/receipt 身份断言，不只是同一对象传新 Runtime。
- 调用**真实 compaction 入口**，确认失效语义没有被裁剪抹掉；正常只读验证
  仍能继续。

本文件不做内存等价物替代：checkpoint 走 `LocalCheckpointStore`（真实
O_NOFOLLOW + flock + 原子 rename），compaction 走
`KernelContextManager._compaction_candidate_fact_ids` +
`state.apply_compaction_summary` 的真实选择与 reducer 路径。

**失效跨裁剪的语义（本轮确定）**：`CONTEXT_SUMMARY` 代表被裁剪掉的任意
历史跨度，Runtime 无法在裁剪后证明该跨度内没有写入或 same-UID 进程执行，
因此它本身是保守失效边界——早于它的验证一律不再满足义务（审计原文：
「两种恢复、checkpoint 重开以及 compaction 后，旧验证均不能满足义务，
显式重新验证必须可执行」）。晚于 summary 的新 receipt 重新可获信任，
只读验证不被永久禁止。
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from agent.runtime.checkpoint import LocalCheckpointStore
from agent.runtime.context import (
    _compaction_candidate_fact_ids,
)
from agent.runtime.contracts import (
    ActiveRunStatus,
    ContinuationPhase,
    ConversationFact,
    ConversationState,
    ConversationSummaryV1,
    ExecutingIntentRecord,
    ExecutionAuthorityClass,
    FactKind,
    RecoveryRequest,
    RecoveryResolution,
    ResolveUnknownToolOutcome,
    SideEffectClass,
    ToolCall,
    canonical_json_digest,
)
from agent.runtime.evidence import (
    ClosedEvidenceRegistry,
    EvidenceVerificationError,
)
from agent.runtime.state import accept_action, apply_compaction_summary
from tests.kernel.test_validation_request_freshness import (
    _closure_claim,
    _closure_criterion,
    _metadata_projection,
    _receipt,
    _runtime,
    _sandbox_fact,
    _state,
)

CONVERSATION = "conversation-fresh"


def _user(fact_id: str, text: str) -> ConversationFact:
    return ConversationFact(
        fact_id=fact_id, kind=FactKind.USER_MESSAGE, content={"text": text}
    )


def _assistant(fact_id: str, text: str) -> ConversationFact:
    return ConversationFact(
        fact_id=fact_id, kind=FactKind.ASSISTANT_MESSAGE, content={"text": text}
    )


def _calls(fact_id: str, *calls: tuple[str, str, dict]) -> ConversationFact:
    return ConversationFact(
        fact_id=fact_id,
        kind=FactKind.TOOL_CALLS,
        content={
            "calls": [
                {"tool_call_id": call_id, "name": name, "arguments": arguments}
                for call_id, name, arguments in calls
            ],
        },
    )


def _write_result(fact_id: str, tool_call_id: str) -> ConversationFact:
    return ConversationFact(
        fact_id=fact_id,
        kind=FactKind.TOOL_RESULT,
        content={
            "tool_call_id": tool_call_id,
            "text": "written",
            "is_error": False,
            "executed": True,
            "metadata": {
                "tool_name": "write_file",
                "governed_tool_receipt_kind": "governed_tool_v1",
            },
        },
    )


def _with_closure_criterion(state: ConversationState) -> ConversationState:
    return replace(
        state,
        goal=replace(state.goal, admitted_criteria=(_closure_criterion(),)),
    )


def _recovering(state: ConversationState) -> ConversationState:
    """把 active run 置入 AWAITING_RECOVERY，绑定一个 WRITE intent。"""

    active = state.active_run
    assert active is not None
    return replace(
        state,
        active_run=replace(
            active,
            status=ActiveRunStatus.AWAITING_RECOVERY,
            phase=ContinuationPhase.EXECUTING,
            tool_calls=(
                ToolCall(
                    "mutate",
                    "write_file",
                    {"path": "artifact.txt", "content": "changed"},
                ),
            ),
            batch_cursor=0,
            pending_request=RecoveryRequest(
                request_id="recovery",
                run_id="run-fresh",
                tool_call_id="mutate",
                binding_digest="intent",
                summary="unknown",
            ),
            executing_intent=ExecutingIntentRecord(
                tool_call_id="mutate",
                intent_digest="intent",
                idempotency_key="key",
                side_effect=SideEffectClass.WRITE,
                execution_authority=ExecutionAuthorityClass.IN_PROCESS,
            ),
        ),
    )


def _resolve(
    state: ConversationState, resolution: RecoveryResolution
) -> ConversationState:
    """走真实 reducer 追加恢复事实（生产形态，非手写 fact）。"""

    return accept_action(
        _recovering(state),
        ResolveUnknownToolOutcome(
            conversation_id=state.conversation_id,
            action_seq=state.next_action_seq,
            expected_revision=state.revision,
            request_id="recovery",
            binding_digest="intent",
            resolution=resolution,
        ),
    ).state


def _compacted(
    state: ConversationState, *, retain_recent_turns: int = 1
) -> tuple[ConversationState, tuple[str, ...]]:
    """走真实候选选择 + 真实 reducer 应用一次 compaction。"""

    candidates = _compaction_candidate_fact_ids(
        state, retain_recent_turns=retain_recent_turns
    )
    assert candidates, "fixture must produce a real compaction candidate"
    removable = tuple(
        fact for fact in state.facts if fact.fact_id in set(candidates)
    )
    summary = ConversationSummaryV1(
        objective="compact earlier turns",
        constraints=(),
        decisions=(),
        completed=(),
        open_items=(),
        key_references=(),
        source_checkpoint_digest="a" * 64,
        source_fact_ids_digest=canonical_json_digest(
            [fact.fact_id for fact in removable]
        ),
    )
    return apply_compaction_summary(state, summary, candidates), candidates


def _durable_roundtrip(
    tmp_path: Path, state: ConversationState
) -> ConversationState:
    """真实 checkpoint save → owner close → 新实例 reopen。"""

    path = tmp_path / "state" / "checkpoint.json"
    store = LocalCheckpointStore.initialize(path, state)
    lease = store.try_acquire(CONVERSATION)
    assert lease is not None
    try:
        store.compare_and_swap(store.load(), state)
    finally:
        lease.release()  # owner close：释放 flock 与目录 fd
    return LocalCheckpointStore(path).load().state


def _native_inventory(state: ConversationState) -> set[str]:
    runtime = _runtime()
    _o, _m, native = runtime._successful_product_request_inventory(state)
    return native


def _validate_digest() -> str:
    return _runtime()._product_request_digest(
        "sandbox_exec", {"executable": "./check-a"}
    )


@pytest.mark.parametrize(
    "resolution",
    (RecoveryResolution.MARK_SUCCEEDED, RecoveryResolution.MARK_FAILED),
)
def test_unknown_recovery_invalidation_survives_real_checkpoint_reopen(
    tmp_path: Path,
    resolution: RecoveryResolution,
) -> None:
    """Q2/RC-01：真实 checkpoint save → owner close → 新实例 reopen 后失效仍在。

    reopen 后由**新** Runtime 与新 store 实例判定，旧缓存（本进程的 fact 折叠
    结果）不参与；断言基于 durable fact 内容与 receipt 身份，而非同一对象。
    """

    base = _with_closure_criterion(
        _state(
            _calls(
                "run:run-fresh:tool-batch:1",
                ("validate-a", "sandbox_exec", {"executable": "./check-a"}),
                ("mutate", "write_file", {"path": "artifact.txt", "content": "changed"}),
            ),
            _sandbox_fact(_receipt()),
            _assistant("fact-val-asst", "validated"),
        )
    )
    registry = ClosedEvidenceRegistry()
    claim = _closure_claim(registry, base)

    # 旧验证在写入前是可信的。
    assert registry.derive(base, claim, observed_at="2026-10-11T00:00:00Z")

    # 真实 save：UNKNOWN 恢复落入 checkpoint。
    recovered = _resolve(base, resolution)
    reopened = _durable_roundtrip(tmp_path, recovered)

    recovery_fact = reopened.facts[-1]
    assert recovery_fact.content.get("unknown_outcome") is True
    assert recovery_fact.content.get("side_effect") == "write"
    assert recovery_fact.fact_id.startswith("action:")

    # 新 Runtime + 新 registry：旧验证不可满足 criterion。
    fresh_registry = ClosedEvidenceRegistry()
    with pytest.raises(EvidenceVerificationError):
        fresh_registry.derive(reopened, claim, observed_at="2026-10-11T00:00:00Z")

    # 抑制折叠也来自 reopen 后的状态：同参重验不被抑制（可显式重验）。
    assert _validate_digest() not in _native_inventory(reopened)

    # 最终真正重验：恢复之后的新 receipt 重新可获信任。
    revalidated = replace(
        reopened,
        facts=(
            *reopened.facts,
            _calls(
                "run:run-fresh:tool-batch:9",
                ("validate-a", "sandbox_exec", {"executable": "./check-a"}),
            ),
            ConversationFact(
                fact_id="run:run-fresh:tool-result:validate-a:9",
                kind=FactKind.TOOL_RESULT,
                content={
                    "tool_call_id": "validate-a",
                    "text": "ok",
                    "is_error": False,
                    "executed": True,
                    "metadata": _metadata_projection(
                        _receipt(
                            receipt_id="sandbox-receipt:fresh-9",
                            lease_id="sandbox-lease:fresh-9",
                        )
                    ),
                },
            ),
        ),
    )
    assert _validate_digest() in _native_inventory(revalidated)
    assert ClosedEvidenceRegistry().derive(
        revalidated, claim, observed_at="2026-10-11T00:00:00Z"
    )


def test_invalidation_survives_real_compaction_and_reopen(tmp_path: Path) -> None:
    """Q2/RC-01：真实 compaction 之后失效语义仍在，旧验证不会因裁剪复活。

    turn 结构：A（受 Goal 源 fact 保护，含可信只读验证）→ B（写入恢复 turn，
    含 reducer 铸造的 UNKNOWN 事实）→ C（最新，被 retain 保留）。真实候选选择
    会选中 B 并整 turn 裁掉；裁剪后旧验证 A 不得重新可用。
    """

    base = _with_closure_criterion(
        _state(
            _calls(
                "run:run-fresh:tool-batch:1",
                ("validate-a", "sandbox_exec", {"executable": "./check-a"}),
            ),
            _sandbox_fact(_receipt()),
            _assistant("fact-val-asst", "validated"),
            _user("fact-write-user", "now write the artifact"),
            _calls(
                "run:run-fresh:tool-batch:2",
                ("mutate", "write_file", {"path": "artifact.txt", "content": "changed"}),
            ),
        )
    )
    registry = ClosedEvidenceRegistry()
    claim = _closure_claim(registry, base)

    recovered = _resolve(base, RecoveryResolution.MARK_FAILED)
    recovery_fact = recovered.facts[-1]
    assert recovery_fact.content.get("unknown_outcome") is True

    # 关闭 turn B，并追加一个更晚的 turn C（retain_recent_turns=1 保留它）。
    compressible = replace(
        recovered,
        facts=(
            *recovered.facts,
            _assistant("fact-write-asst", "write attempted"),
            _user("fact-later-user", "later unrelated request"),
            _assistant("fact-later-asst", "acknowledged"),
        ),
    )
    # 失效已成立（恢复事实晚于验证）。
    with pytest.raises(EvidenceVerificationError):
        registry.derive(compressible, claim, observed_at="2026-10-11T00:00:00Z")

    compacted, candidates = _compacted(compressible)
    # 被裁剪的确实是恢复 turn：验证 turn A 因 Goal 源 fact 受保护而保留。
    assert recovery_fact.fact_id in candidates
    assert "run:run-fresh:tool-result:validate-a:1" not in candidates
    assert "run:run-fresh:tool-result:validate-a:1" in {
        fact.fact_id for fact in compacted.facts
    }
    assert any(fact.kind is FactKind.CONTEXT_SUMMARY for fact in compacted.facts)

    # 真实 checkpoint 往返：压缩后的状态落盘、owner close、新实例 reopen。
    durable = _durable_roundtrip(tmp_path, compacted)

    # 失效结论在压缩 + reopen 后仍成立：旧验证不能满足 criterion。
    fresh_registry = ClosedEvidenceRegistry()
    with pytest.raises(EvidenceVerificationError):
        fresh_registry.derive(durable, claim, observed_at="2026-10-11T00:00:00Z")

    # 抑制折叠同样不因裁剪而复活旧验证信任（否则重验被抑制 → 无法恢复）。
    assert _validate_digest() not in _native_inventory(durable)

    # 显式同参重验仍可执行，并在取得新 receipt 后重新可获信任。
    revalidated = replace(
        durable,
        facts=(
            *durable.facts,
            _calls(
                "run:run-fresh:tool-batch:9",
                ("validate-a", "sandbox_exec", {"executable": "./check-a"}),
            ),
            ConversationFact(
                fact_id="run:run-fresh:tool-result:validate-a:9",
                kind=FactKind.TOOL_RESULT,
                content={
                    "tool_call_id": "validate-a",
                    "text": "ok",
                    "is_error": False,
                    "executed": True,
                    "metadata": _metadata_projection(
                        _receipt(
                            receipt_id="sandbox-receipt:fresh-9",
                            lease_id="sandbox-lease:fresh-9",
                        )
                    ),
                },
            ),
        ),
    )
    assert _validate_digest() in _native_inventory(revalidated)
    assert ClosedEvidenceRegistry().derive(
        revalidated, claim, observed_at="2026-10-11T00:00:00Z"
    )


def test_readonly_validation_still_completes_after_compaction(tmp_path: Path) -> None:
    """Q2 反向：compaction 不永久禁止只读验证，重验后仍能继续完成。

    纯只读历史被裁剪后，早于 summary 的验证按保守边界不再可用（无法证明被
    裁剪的跨度内没有写入）；但显式重验必须可执行且重新可获信任——否则
    长会话会在压缩后陷入「不能完成也不能重验」的死锁。
    """

    base = _with_closure_criterion(
        _state(
            _calls(
                "run:run-fresh:tool-batch:1",
                ("validate-a", "sandbox_exec", {"executable": "./check-a"}),
            ),
            _sandbox_fact(_receipt()),
            _assistant("fact-val-asst", "validated"),
            _user("action:90:user", "later unrelated request"),
            _assistant("action:91:assistant", "acknowledged"),
            _user("action:92:user", "one more"),
            _assistant("action:93:assistant", "done"),
        )
    )
    registry = ClosedEvidenceRegistry()
    claim = _closure_claim(registry, base)
    assert registry.derive(base, claim, observed_at="2026-10-11T00:00:00Z")

    compacted, _candidates = _compacted(base)
    durable = _durable_roundtrip(tmp_path, compacted)

    fresh_registry = ClosedEvidenceRegistry()
    with pytest.raises(EvidenceVerificationError):
        fresh_registry.derive(durable, claim, observed_at="2026-10-11T00:00:00Z")

    # 关键反向条件：重验不被抑制，且重验后只读验证重新成立。
    assert _validate_digest() not in _native_inventory(durable)
    revalidated = replace(
        durable,
        facts=(
            *durable.facts,
            _user("action:94:user", "re-validate"),
            _calls(
                "run:run-fresh:tool-batch:9",
                ("validate-a", "sandbox_exec", {"executable": "./check-a"}),
            ),
            ConversationFact(
                fact_id="run:run-fresh:tool-result:validate-a:9",
                kind=FactKind.TOOL_RESULT,
                content={
                    "tool_call_id": "validate-a",
                    "text": "ok",
                    "is_error": False,
                    "executed": True,
                    "metadata": _metadata_projection(
                        _receipt(
                            receipt_id="sandbox-receipt:fresh-9",
                            lease_id="sandbox-lease:fresh-9",
                        )
                    ),
                },
            ),
            _assistant("action:95:assistant", "revalidated"),
        ),
    )
    assert _validate_digest() in _native_inventory(revalidated)
    assert fresh_registry.derive(
        revalidated, claim, observed_at="2026-10-11T00:00:00Z"
    )
    # summary 之后的验证不受影响：不因修复把所有只读执行都当成写入。
    assert ClosedEvidenceRegistry._may_invalidate_workspace_validation(
        _sandbox_fact(
            _receipt(receipt_id="sandbox-receipt:fresh-9", lease_id="sandbox-lease:fresh-9")
        )
    ) is False


def test_managed_writer_invalidation_survives_checkpoint_reopen(tmp_path: Path) -> None:
    """Q2/RC-02 第 5 条：可写进程启动事实经真实 checkpoint 重开后仍保守失效。

    用生产格式的 managed_web_start 结果（无 process_receipt 外形）证明重开
    后的新 Runtime 不依赖旧缓存：旧验证仍不可用，且未 stop 的资源仍被
    ``active_task_resources`` 认作未清理（completion 失去收尾义务会误报完成）。
    """

    from agent.runtime.resource_lifecycle import active_task_resources

    base = _with_closure_criterion(
        _state(
            _calls(
                "run:run-fresh:tool-batch:1",
                ("validate-a", "sandbox_exec", {"executable": "./check-a"}),
            ),
            _sandbox_fact(_receipt()),
            _assistant("fact-val-asst", "validated"),
        )
    )
    registry = ClosedEvidenceRegistry()
    claim = _closure_claim(registry, base)
    assert registry.derive(base, claim, observed_at="2026-10-11T00:00:00Z")

    managed = ConversationFact(
        fact_id="run:run-fresh:tool-result:start:1",
        kind=FactKind.TOOL_RESULT,
        content={
            "tool_call_id": "start",
            # 生产格式：managed_web_start 的 content 是 JSON payload（status=ready
            # 才是可信启动），resource_lifecycle 按同一形状解释所有权。
            "text": '{"resource_ref": "managed-web:conversation-fresh:1", '
            '"status": "ready", "origin": "http://127.0.0.1:1"}',
            "is_error": False,
            "executed": True,
            "metadata": {
                "tool_name": "managed_web_start",
                "governed_tool_receipt_kind": "governed_tool_v1",
            },
        },
    )
    started = replace(
        base,
        facts=(
            *base.facts,
            _calls(
                "run:run-fresh:tool-batch:2",
                ("start", "managed_web_start", {"executable": "./server.py"}),
            ),
            managed,
        ),
    )

    durable = _durable_roundtrip(tmp_path, started)

    # 重开后的新 Runtime：旧验证仍不成立，且同参重验不被抑制。
    with pytest.raises(EvidenceVerificationError):
        ClosedEvidenceRegistry().derive(
            durable, claim, observed_at="2026-10-11T00:00:00Z"
        )
    assert _validate_digest() not in _native_inventory(durable)

    # 资源所有权也跨重开保留：未 stop 的 start 仍要求收尾。
    resources = active_task_resources(durable.facts)
    assert resources.managed_processes, "started writer must stay owned after reopen"
    with pytest.raises(ValueError):
        resources.require_closed()
