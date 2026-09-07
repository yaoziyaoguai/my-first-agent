"""020 长会话压缩：compaction provider 响应的严格纯解析合同。

只测 ``parse_compaction_response`` 这一个纯函数，不接 Runtime loop：

- ``response.control`` 必须为 None；blocks 必须恰好一个 ``ModelTextBlock``，
  禁止 ModelToolCall、多 block、空 blocks、空/纯空白 text；
- ``stop_reason == "max_tokens"`` 一律拒绝（truncated 摘要不得部分接受）；
- text 必须是纯 JSON object：允许外围空白，拒绝 markdown fence、前后说明、
  非 JSON 文本、非 object JSON、截断 JSON；闭合校验完全委托
  ``ConversationSummaryV1.from_json``（未知键/缺失字段/非法字段值同样拒绝）；
- 解析出的两个 digest 必须 exact 匹配关键字参数；参数本身必须是
  64 位小写 hex；
- 任何违规抛 ``CompactionResponseError(ValueError)``，零修复、零副作用。

Red 在 ``agent/continuity/compaction.py`` 落地前因函数不存在而准确失败；
用 importlib + getattr + pytest.fail 守卫保证失败是干净断言而非 collection
期 import error。
"""

from __future__ import annotations

import importlib

import pytest

from agent.runtime.contracts import (
    ConversationSummaryV1,
    DirectResponse,
    ModelResponse,
    ModelTextBlock,
    ModelToolCall,
    canonical_json_digest,
)

CHECKPOINT_DIGEST = "9" * 64
FACT_IDS_DIGEST = canonical_json_digest(
    ["action:1:user", "action:2:assistant"]
)
OTHER_DIGEST = "8" * 64


def _module():
    try:
        return importlib.import_module("agent.continuity.compaction")
    except ModuleNotFoundError:
        pytest.fail("020 requires agent.continuity.compaction")


def _parse():
    parse = getattr(_module(), "parse_compaction_response", None)
    if parse is None:
        pytest.fail(
            "020 requires agent.continuity.compaction.parse_compaction_response"
        )
    return parse


def _error():
    error = getattr(_module(), "CompactionResponseError", None)
    if error is None:
        pytest.fail(
            "020 requires agent.continuity.compaction.CompactionResponseError"
        )
    return error


def _summary(
    *,
    source_checkpoint_digest: str = CHECKPOINT_DIGEST,
    source_fact_ids_digest: str = FACT_IDS_DIGEST,
    objective: str = "compact earlier turns",
) -> ConversationSummaryV1:
    return ConversationSummaryV1(
        objective=objective,
        constraints=("keep workspace-relative paths",),
        decisions=("archive before CAS",),
        completed=("first closed turn",),
        open_items=("finish the plan slice",),
        key_references=("docs/plans/2026-09-04-001",),
        source_checkpoint_digest=source_checkpoint_digest,
        source_fact_ids_digest=source_fact_ids_digest,
    )


def _response(
    text: str,
    *,
    stop_reason: str | None = None,
    control: DirectResponse | None = None,
) -> ModelResponse:
    return ModelResponse(
        blocks=(ModelTextBlock(text=text),),
        control=control,
        stop_reason=stop_reason,
    )


def _assert_rejected(
    text_or_response: str | ModelResponse,
    *,
    source_checkpoint_digest: str = CHECKPOINT_DIGEST,
    source_fact_ids_digest: str = FACT_IDS_DIGEST,
) -> None:
    response = (
        text_or_response
        if isinstance(text_or_response, ModelResponse)
        else _response(text_or_response)
    )
    with pytest.raises(_error()):
        _parse()(
            response,
            source_checkpoint_digest=source_checkpoint_digest,
            source_fact_ids_digest=source_fact_ids_digest,
        )


# --------------------------------------------------------------------------- #
# 成功路径：纯 JSON object 闭合解析
# --------------------------------------------------------------------------- #


def test_error_is_a_value_error() -> None:
    assert issubclass(_error(), ValueError)


def test_accepts_canonical_summary_json() -> None:
    summary = _summary()

    parsed = _parse()(
        _response(summary.to_json()),
        source_checkpoint_digest=CHECKPOINT_DIGEST,
        source_fact_ids_digest=FACT_IDS_DIGEST,
    )

    assert parsed == summary


def test_accepts_surrounding_whitespace_unicode_and_other_stop_reasons() -> None:
    # 允许外围空白；合法 unicode 内容原样通过；max_tokens 之外的 stop_reason
    # 不构成拒绝理由。
    summary = ConversationSummaryV1(
        objective="压缩目标：整理工作区 ✅",
        constraints=("路径保持 workspace 相对",),
        decisions=("先归档再提交",),
        completed=("完成了第一个回合",),
        open_items=("完成剩余计划", "保持上下文有界"),
        key_references=("docs/plans/2026-09-04-001-完成长会话.md",),
        source_checkpoint_digest=CHECKPOINT_DIGEST,
        source_fact_ids_digest=FACT_IDS_DIGEST,
    )
    padded = f"\n\t  {summary.to_json()}  \r\n"

    parsed = _parse()(
        _response(padded, stop_reason="end_turn"),
        source_checkpoint_digest=CHECKPOINT_DIGEST,
        source_fact_ids_digest=FACT_IDS_DIGEST,
    )

    assert parsed == summary


# --------------------------------------------------------------------------- #
# 响应形状：control / tool call / 多 block / 空 text
# --------------------------------------------------------------------------- #


def test_rejects_control_block() -> None:
    summary = _summary()
    response = ModelResponse(
        blocks=(ModelTextBlock(text=summary.to_json()),),
        control=DirectResponse(correlation_id="corr-1", text="direct answer"),
    )
    with pytest.raises(_error()):
        _parse()(
            response,
            source_checkpoint_digest=CHECKPOINT_DIGEST,
            source_fact_ids_digest=FACT_IDS_DIGEST,
        )


def test_rejects_tool_call_block() -> None:
    call = ModelToolCall(
        tool_call_id="call-1",
        name="write_file",
        arguments={"path": "note.txt"},
    )
    response = ModelResponse(blocks=(call,))

    with pytest.raises(_error()):
        _parse()(
            response,
            source_checkpoint_digest=CHECKPOINT_DIGEST,
            source_fact_ids_digest=FACT_IDS_DIGEST,
        )


def test_rejects_multiple_blocks() -> None:
    json_text = _summary().to_json()
    two_texts = ModelResponse(
        blocks=(ModelTextBlock(text=json_text), ModelTextBlock(text=json_text))
    )
    text_plus_prose = ModelResponse(
        blocks=(ModelTextBlock(text=json_text), ModelTextBlock(text="all done"))
    )
    text_plus_tool = ModelResponse(
        blocks=(
            ModelTextBlock(text=json_text),
            ModelToolCall(tool_call_id="call-1", name="echo", arguments={}),
        )
    )
    for response in (two_texts, text_plus_prose, text_plus_tool):
        with pytest.raises(_error()):
            _parse()(
                response,
                source_checkpoint_digest=CHECKPOINT_DIGEST,
                source_fact_ids_digest=FACT_IDS_DIGEST,
            )


def test_rejects_empty_blocks() -> None:
    response = ModelResponse(blocks=())

    with pytest.raises(_error()):
        _parse()(
            response,
            source_checkpoint_digest=CHECKPOINT_DIGEST,
            source_fact_ids_digest=FACT_IDS_DIGEST,
        )


def test_rejects_empty_or_whitespace_only_text() -> None:
    _assert_rejected("")
    _assert_rejected("   \n\t  ")


# --------------------------------------------------------------------------- #
# 截断：max_tokens stop reason 与物理截断 JSON
# --------------------------------------------------------------------------- #


def test_rejects_max_tokens_stop_reason() -> None:
    # 即使 JSON 本身完整，max_tokens 意味着可能截断：不得部分接受。
    summary = _summary()
    response = _response(summary.to_json(), stop_reason="max_tokens")

    with pytest.raises(_error()):
        _parse()(
            response,
            source_checkpoint_digest=CHECKPOINT_DIGEST,
            source_fact_ids_digest=FACT_IDS_DIGEST,
        )


def test_rejects_truncated_json() -> None:
    json_text = _summary().to_json()
    half = json_text[: len(json_text) // 2]
    missing_close = json_text.rstrip()[:-1]

    _assert_rejected(half)
    _assert_rejected(missing_close)


# --------------------------------------------------------------------------- #
# 纯 JSON object：fence / 前后说明 / 非 JSON / 非 object
# --------------------------------------------------------------------------- #


def test_rejects_markdown_fence() -> None:
    json_text = _summary().to_json()
    _assert_rejected(f"```json\n{json_text}\n```")
    _assert_rejected(f"```\n{json_text}\n```")


def test_rejects_prose_around_json() -> None:
    json_text = _summary().to_json()
    _assert_rejected(f"Here is the summary: {json_text}")
    _assert_rejected(f"{json_text}\nThat is the summary.")


def test_rejects_non_json_text() -> None:
    _assert_rejected("the user wants to compact earlier turns")
    _assert_rejected("objective: compact, constraints: none")


def test_rejects_valid_json_that_is_not_an_object() -> None:
    _assert_rejected("[1, 2]")
    _assert_rejected("42")
    _assert_rejected('"a summary string"')
    _assert_rejected("null")
    _assert_rejected("true")


# --------------------------------------------------------------------------- #
# 闭合 summary 形状：未知键 / 缺失字段
# --------------------------------------------------------------------------- #


def test_rejects_unknown_keys() -> None:
    import json

    content = json.loads(_summary().to_json())
    content["extra"] = "unknown key"

    _assert_rejected(json.dumps(content, ensure_ascii=False))


def test_rejects_missing_fields() -> None:
    import json

    content = json.loads(_summary().to_json())
    del content["open_items"]

    _assert_rejected(json.dumps(content, ensure_ascii=False))


# --------------------------------------------------------------------------- #
# digest 绑定：解析值 exact 匹配参数，参数本身 64 lowerhex
# --------------------------------------------------------------------------- #


def test_rejects_source_checkpoint_digest_mismatch() -> None:
    summary = _summary(source_checkpoint_digest=OTHER_DIGEST)

    with pytest.raises(_error()):
        _parse()(
            _response(summary.to_json()),
            source_checkpoint_digest=CHECKPOINT_DIGEST,
            source_fact_ids_digest=FACT_IDS_DIGEST,
        )


def test_rejects_source_fact_ids_digest_mismatch() -> None:
    summary = _summary(source_fact_ids_digest=OTHER_DIGEST)

    with pytest.raises(_error()):
        _parse()(
            _response(summary.to_json()),
            source_checkpoint_digest=CHECKPOINT_DIGEST,
            source_fact_ids_digest=FACT_IDS_DIGEST,
        )


def test_rejects_invalid_digest_parameters() -> None:
    json_text = _summary().to_json()
    invalid = [
        "9" * 63,               # 短一位
        "9" * 65,               # 长一位
        "A" * 64,               # 大写 hex
        "g" * 64,               # 非 hex 字符
        f"sha256:{'9' * 64}",   # 带前缀 token，不是裸 digest
        "",                     # 空
    ]

    for digest in invalid:
        response = _response(json_text)
        with pytest.raises(_error()):
            _parse()(
                response,
                source_checkpoint_digest=digest,
                source_fact_ids_digest=FACT_IDS_DIGEST,
            )
        with pytest.raises(_error()):
            _parse()(
                response,
                source_checkpoint_digest=CHECKPOINT_DIGEST,
                source_fact_ids_digest=digest,
            )
