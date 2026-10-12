"""020 长会话压缩：archive-before-CAS 的 archive 原语与 summary 解析。

固定提交顺序（计划 §3.1）：已持有 conversation mutation lease 的调用方
（``AgentRuntime``）先让 ``ConversationArchive`` 以 source checkpoint
digest 为 identity 幂等写入完整原样的 pre-compaction 状态，成功后才用
``CheckpointStore.compare_and_swap`` 提交 reduced 状态；CAS 本身属于
Runtime，不在本模块。archive 成功而 CAS 失败/进程崩溃时，旧 checkpoint
仍完整，重放只复用同 digest archive；绝不先覆盖活动 checkpoint 再归档。

本模块不引入第二套锁、重试或回滚：lease 归调用方所有；archive port
异常只在调用边界归一化为有界的 ``CompactionArchiveError``，原异常保留
为 cause。
"""

from __future__ import annotations

import re

from agent.runtime.contracts import (
    ConversationState,
    ConversationSummaryV1,
    FactKind,
    LoadedSnapshot,
    ModelResponse,
    ModelTextBlock,
)
from agent.runtime.ports import ConversationArchive

_TOKEN_PREFIX = "sha256:"
_CHECKPOINT_TOKEN_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
# 裸 digest（无 token 前缀）：compaction 响应绑定用的两个参数形状。
_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class CompactionCommitError(RuntimeError):
    """提交前置验证失败；此时未发生任何 archive/CAS 副作用。"""


class CompactionResponseError(ValueError):
    """compaction provider 响应不满足闭合形状；拒绝时零修复、零副作用。"""


class CompactionArchiveError(RuntimeError):
    """compaction archive port 在缩减 CAS 前失败。"""


def parse_compaction_response(
    response: ModelResponse,
    *,
    source_checkpoint_digest: str,
    source_fact_ids_digest: str,
) -> ConversationSummaryV1:
    """严格解析 compaction provider 响应中的唯一 summary JSON object。

    纯函数，不接 Runtime loop，不做任何状态变更或副作用；任何违规都在
    产生副作用前整条拒绝（``CompactionResponseError``），绝不部分接受、
    修复或截取。闭合形状要求：

    - 两个绑定参数必须是 64 位小写 hex 裸 digest（调用方合同，先行校验）；
    - ``response.control`` 必须为 None：compaction 响应不得携带控制面信号；
    - ``response.blocks`` 必须恰好一个 ``ModelTextBlock``：空、多 block、
      ``ModelToolCall`` 或空/纯空白 text 一律拒绝；
    - ``stop_reason == "max_tokens"`` 一律拒绝：截断的摘要不可部分接受；
    - text 必须是纯 JSON object（仅允许外围空白）：markdown fence、前后
      说明、非 JSON、非 object、截断 JSON 由 ``ConversationSummaryV1.from_json``
      闭合校验拒绝（未知键/缺失字段/非法字段值同理）；
    - 解析出的两个 source digest 必须 exact 匹配传入参数，防止模型摘要
      绑定到其他 checkpoint 或其他 removal 集合。
    """

    for label, digest in (
        ("source_checkpoint_digest", source_checkpoint_digest),
        ("source_fact_ids_digest", source_fact_ids_digest),
    ):
        if not isinstance(digest, str) or not _DIGEST_PATTERN.fullmatch(digest):
            raise CompactionResponseError(
                f"compaction binding {label} must be 64 lowercase hex characters"
            )
    if response.control is not None:
        raise CompactionResponseError(
            "compaction response must not carry a control block"
        )
    if len(response.blocks) != 1 or not isinstance(response.blocks[0], ModelTextBlock):
        raise CompactionResponseError(
            "compaction response must be exactly one model text block"
        )
    if response.stop_reason == "max_tokens":
        raise CompactionResponseError(
            "compaction response was truncated by the output token limit"
        )
    text = response.blocks[0].text
    if not text.strip():
        raise CompactionResponseError(
            "compaction response text must not be empty"
        )
    try:
        summary = ConversationSummaryV1.from_json(text)
    except ValueError as error:
        raise CompactionResponseError(
            "compaction response is not a closed summary JSON object"
        ) from error
    if summary.source_checkpoint_digest != source_checkpoint_digest:
        raise CompactionResponseError(
            "summary does not bind the source checkpoint digest"
        )
    if summary.source_fact_ids_digest != source_fact_ids_digest:
        raise CompactionResponseError(
            "summary does not bind the source fact ids digest"
        )
    return summary


def archive_compaction_source(
    archive: ConversationArchive,
    source: LoadedSnapshot,
    reduced_state: ConversationState,
    *,
    model_attempt_recorded: bool = False,
) -> None:
    """校验后把完整原样的 pre-compaction 状态幂等写入 archive。

    前置验证全部通过后才产生副作用：

    - ``source`` 与 ``reduced_state`` 的 conversation_id、workspace binding
      exact 相等，且双方都必须携带 binding；
    - ``reduced_state.revision`` 恰好是 ``source.state.revision + 1``；
    - ``reduced_state.facts`` 恰好含一个合法 ``CONTEXT_SUMMARY`` fact
      （位置无关：goal/evidence 保护的 turns 会原序保留在前，reducer
      把 summary 插在最早被移除 fact 的原位置），其
      ``source_checkpoint_digest`` 等于 ``source.token`` 的 ``sha256:`` 后
      64hex；token 本身必须是闭合 digest 形式。

    成功路径固定为 ``archive.archive(source.state, source.token, scope)``。
    本函数不接 CheckpointStore、不做 CAS：缩减提交的 CAS 由唯一 owner
    ``AgentRuntime`` 在本函数返回之后执行。调用方必须已持有 conversation
    mutation lease；本函数自身不做任何锁获取或回滚。archive port 异常
    归一化为 ``CompactionArchiveError``，供 Runtime 在本批 CAS 前恢复。
    """

    binding = source.state.workspace_binding
    if binding is None or reduced_state.workspace_binding is None:
        raise CompactionCommitError(
            "compaction commit requires a workspace binding on both states"
        )
    if reduced_state.conversation_id != source.state.conversation_id:
        raise CompactionCommitError(
            "compaction must not change conversation identity"
        )
    if reduced_state.workspace_binding != binding:
        raise CompactionCommitError(
            "compaction must not change the workspace binding"
        )
    revision_steps = 2 if model_attempt_recorded else 1
    if reduced_state.revision != source.state.revision + revision_steps:
        raise CompactionCommitError(
            "reduced state must advance by the accounting and compaction revisions"
        )
    if model_attempt_recorded:
        source_run = source.state.active_run
        reduced_run = reduced_state.active_run
        if (
            source_run is None
            or reduced_run is None
            or reduced_run.model_calls_used != source_run.model_calls_used + 1
            or reduced_run.input_tokens_used < source_run.input_tokens_used
        ):
            raise CompactionCommitError(
                "compaction source does not include one durable model attempt"
            )
    if not _CHECKPOINT_TOKEN_PATTERN.fullmatch(source.token):
        raise CompactionCommitError(
            "source snapshot token is not a closed sha256 digest token"
        )
    # reducer 会把 goal/evidence 保护的 turns 原序保留在前、summary 插在
    # 最早被移除 fact 的原位置，因此不能要求 summary 位于 facts[0]；位置
    # 无关，数量恰好一个、闭合形状与 digest 绑定才是不变量。
    summary_facts = [
        fact for fact in reduced_state.facts if fact.kind is FactKind.CONTEXT_SUMMARY
    ]
    if len(summary_facts) != 1:
        raise CompactionCommitError(
            "reduced state must carry exactly one CONTEXT_SUMMARY fact"
        )
    try:
        summary = ConversationSummaryV1.from_content(summary_facts[0].content)
    except ValueError as error:
        raise CompactionCommitError(
            "reduced state CONTEXT_SUMMARY fact is not a legal summary"
        ) from error
    if summary.source_checkpoint_digest != source.token.removeprefix(_TOKEN_PREFIX):
        raise CompactionCommitError(
            "conversation summary does not bind the source checkpoint digest"
        )

    try:
        archive.archive(
            source.state,
            source_checkpoint_digest=source.token,
            workspace_scope_digest=binding.workspace_scope_digest,
        )
    except Exception as error:
        # Runtime 只依赖 continuity 的失败语义，不反向依赖具体 filesystem
        # archive adapter；原异常保留为 cause 供诊断，外显消息保持有界。
        raise CompactionArchiveError(
            "conversation archive failed during compaction"
        ) from error
