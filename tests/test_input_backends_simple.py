"""simple backend 的窄测试。

simple backend 是旧 input()/multi 协议的 fallback，不是终局 TUI。它的职责是
保留历史 CLI 行为，同时把结果统一包装成 UserInputEvent；cancelled/closed
不能被伪造成空字符串，也不能直接触发 Runtime 决策。
"""

from __future__ import annotations

from agent.input_backends.simple import read_user_input_event
from agent.user_input import build_user_input_envelope


def _make_reader(lines):
    """把预置行序列伪装成 input()，用于稳定复现终端输入。"""

    queue = list(lines)

    def reader(_prompt: str = "") -> str:
        value = queue.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value

    return reader


def _silent_writer(*_args, **_kwargs) -> None:
    """吞掉多行模式提示，避免测试输出干扰断言。"""

    return None


def test_simple_backend_single_line_returns_submitted_event():
    """普通一行输入应成为 input.submitted，并完整保留 raw_text。"""

    event = read_user_input_event(
        reader=_make_reader(["hello"]),
        writer=_silent_writer,
    )

    assert event.event_type == "input.submitted"
    assert event.event_source == "simple"
    assert event.event_channel == "stdin"
    assert event.envelope is not None
    assert event.envelope.raw_text == "hello"
    assert event.envelope.input_mode == "single_line"


def test_simple_backend_empty_line_is_submitted_empty_envelope():
    """空输入仍是 submitted 文本，后续由 Runtime empty guard 处理。"""

    event = read_user_input_event(
        reader=_make_reader(["   "]),
        writer=_silent_writer,
    )

    assert event.event_type == "input.submitted"
    assert event.envelope is not None
    assert event.envelope.raw_text == "   "
    assert event.envelope.is_empty is True
    assert event.envelope.input_mode == "empty"


def test_simple_backend_multi_mode_preserves_multiline_text():
    """/multi fallback 必须保留完整多行内容和空行。"""

    event = read_user_input_event(
        reader=_make_reader([
            "/multi",
            "北京出发",
            "",
            "预算 3500",
            "/done",
        ]),
        writer=_silent_writer,
    )

    assert event.event_type == "input.submitted"
    assert event.envelope is not None
    assert event.envelope.raw_text == "北京出发\n\n预算 3500"
    assert event.envelope.normalized_text == "北京出发\n\n预算 3500"
    assert event.envelope.input_mode == "multiline"
    assert event.envelope.line_count == 3


def test_simple_backend_multi_cancel_returns_cancelled_event():
    """/multi 中 /cancel 是取消输入，不是提交空文本。"""

    event = read_user_input_event(
        reader=_make_reader(["/multi", "draft", "/cancel"]),
        writer=_silent_writer,
    )

    assert event.event_type == "input.cancelled"
    assert event.event_source == "simple"
    assert event.event_channel == "multi_cancel"
    assert event.envelope is None


def test_simple_backend_keyboard_interrupt_returns_cancelled_event():
    """首行 Ctrl+C 映射为 input.cancelled，由 main loop 复用中断流程。"""

    event = read_user_input_event(
        reader=_make_reader([KeyboardInterrupt()]),
        writer=_silent_writer,
    )

    assert event.event_type == "input.cancelled"
    assert event.event_channel == "keyboard_interrupt"
    assert event.envelope is None


def test_simple_backend_eof_returns_closed_event():
    """首行 EOF 表示输入流关闭，不应进入 chat。"""

    event = read_user_input_event(
        reader=_make_reader([EOFError()]),
        writer=_silent_writer,
    )

    assert event.event_type == "input.closed"
    assert event.event_source == "simple"
    assert event.event_channel == "eof"
    assert event.envelope is None


def test_simple_backend_eof_during_multi_submits_collected_lines():
    """多行收集中 EOF 按既有 fallback 行为提交已收集内容，避免吞掉输入。"""

    event = read_user_input_event(
        reader=_make_reader(["/multi", "first", "second", EOFError()]),
        writer=_silent_writer,
    )

    assert event.event_type == "input.submitted"
    assert event.envelope is not None
    assert event.envelope.raw_text == "first\nsecond"
    assert event.envelope.input_mode == "multiline"
    assert event.envelope.line_count == 2


# ============================================================
# v0.6.2 TUI MVP characterization tests (Slice 5)
# ------------------------------------------------------------
# 目的
#   为 v0.6.2 TUI MVP（只解 XFAIL-3 paste burst）钉死「数据层 envelope」
#   与「simple backend 包装」两条契约。Slice 6 实现 paste burst 时，
#   必须继续满足这些契约；任何偷偷剥换行/剥编号/丢内容的实现都会被钉住。
#
# 为何只做 characterization、不动 production
#   - 本轮是 Slice 5（tests-only）；Slice 6 才允许改 production。
#   - UserInputEnvelope 的字段（input_mode / line_count / raw_text /
#     normalized_text / is_empty / source）已经就位，是数据层先于实现的
#     稳定边界，可以先用 tests 锁定「目标形态」，再让实现去翻 XFAIL-3。
#
# 为何只挑 4 条
#   - 多余测试堆砌只是噪音；4 条已经把数据层契约 + 后端包装契约 + 规范化
#     契约 + 防误解析契约都钉死了。
#   - Ask User free-text / display layer / AST 依赖边界已被其他测试文件
#     完整覆盖（test_display_event_contract.py / test_tui_dependency_boundaries.py /
#     response_handlers 系列），不重复。
#
# 为何不能为了让 XFAIL-3 「看起来通过」而削弱本组测试
#   - XFAIL-3 是 strict xfail，记录 main.read_user_input 端到端缺口；
#     本组测试是「下一层数据/后端契约钉子」。Slice 6 实现必须同时让
#     XFAIL-3 翻 PASS 且这 4 条仍 PASS——任何一边松动都不允许。
#
# 未来扩展点
#   - 当 Slice 6 引入 stdin readiness 检测 / bracketed paste 后，可在本组
#     之外新增「真实终端粘贴行为模拟」测试；本组保持数据/后端契约层不动。
# ============================================================


PASTED_NUMBERED_LINES = [
    "1. 北京出发",
    "2. 偏好高铁",
    "3. 高端酒店",
    "4. 先武汉后宜昌",
    "5. 自然风光和历史文化",
    "6. 预算 3500 元左右",
    "7. 单人出行",
    "8. 必须去黄鹤楼",
    "9. 出行日期：5 月 1 日到 5 月 3 日",
]


def test_envelope_classifies_pasted_multiline_string_as_multiline():
    """钉数据层契约：build_user_input_envelope 拿到一次粘贴的 9 行编号文本时，
    必须分类为 multiline、line_count 必须等于实际行数、raw_text 必须原样保留。

    这是 paste burst 解的「目标数据形态」。Slice 6 实现把粘贴包装成一次
    envelope 时，必须满足这些字段；任何丢行/合并/截断都会被这条钉住。

    本测试不依赖 simple backend 链路，只验证数据层契约本身——这样即便未来
    backend 路径重构，数据契约仍是稳定不变量。
    """

    pasted = "\n".join(PASTED_NUMBERED_LINES)

    env = build_user_input_envelope(pasted, source="cli")

    assert env.raw_text == pasted, "raw_text 必须 1:1 保留用户粘贴的原文"
    assert env.normalized_text == pasted, "纯 LF 输入下 normalized_text 必须等于 raw_text"
    assert env.input_mode == "multiline", "9 行编号粘贴必须分类为 multiline"
    assert env.line_count == 9, f"line_count 必须等于实际行数，实际={env.line_count}"
    assert env.is_empty is False
    assert env.source == "cli"


def test_envelope_normalizes_crlf_in_pasted_block_without_dropping_lines():
    """钉规范化契约：粘贴文本携带 CRLF / CR 行结束符时，normalized_text
    必须统一为 LF，line_count 与 LF 行数一致；同时 raw_text 必须原封保留
    用户实际敲下的字节序列（包括 CRLF），不允许"为方便后处理"改写 raw_text。

    paste burst 在不同终端 / OS / 输入法下经常带 CRLF；规范化层一旦悄悄
    丢内容（例如把空行折叠掉、或把 raw_text 也改写），后面的 runtime
    投影、checkpoint 写盘、日志回放都会跟着错。这条钉子防止该类回归。
    """

    raw_with_crlf = "1. 北京出发\r\n2. 高铁\r\n\r\n3. 高端酒店"
    expected_normalized = "1. 北京出发\n2. 高铁\n\n3. 高端酒店"

    env = build_user_input_envelope(raw_with_crlf, source="cli")

    assert env.raw_text == raw_with_crlf, "raw_text 必须保留 CRLF 字节，不允许被规范化覆盖"
    assert env.normalized_text == expected_normalized, "normalized_text 必须 CRLF→LF"
    assert env.input_mode == "multiline"
    # 4 行（含 1 个空行）：normalized 中有 3 个 \n，line_count = count('\n') + 1 = 4
    assert env.line_count == 4, f"line_count 必须按 LF 计数，实际={env.line_count}"
    assert env.is_empty is False


def test_simple_backend_wraps_multiline_raw_string_in_multiline_envelope():
    """钉 simple backend 契约：当输入源（未来 paste burst 实现 / 当前 fake reader）
    一次返回一段含 \\n 的字符串时，read_user_input_event 必须包装成
    input.submitted + multiline envelope，event_source/channel 仍是
    simple/stdin，envelope 字段与数据层契约一致。

    Slice 6 paste burst 实现的目标路径是：让 simple backend 在普通分支
    检测到 stdin 已就绪的连续行，并把它们一次合并成 raw_text 喂给
    build_user_input_envelope。这条测试用 fake reader 模拟那条路径的
    最终入参形态，提前锁定后端契约。

    fake/mock 边界说明：
      - _make_reader 用预置 list 模拟 input()，绕过真实 stdin；
      - 这里只测试「reader 给到 backend 的字符串如何被包装」，不测试
        backend 怎样从真实 stdin 拼出这个字符串（那是 Slice 6 的事）。
    """

    pasted = "\n".join(PASTED_NUMBERED_LINES)

    event = read_user_input_event(
        reader=_make_reader([pasted]),
        writer=_silent_writer,
    )

    assert event.event_type == "input.submitted"
    assert event.event_source == "simple"
    assert event.event_channel == "stdin"
    assert event.envelope is not None
    assert event.envelope.raw_text == pasted
    assert event.envelope.input_mode == "multiline"
    assert event.envelope.line_count == 9
    assert event.envelope.is_empty is False
    assert event.envelope.source == "cli"


def test_simple_backend_pasted_numbered_list_preserves_marker_chars():
    """钉防误解析契约：粘贴 "1." ~ "9." 编号列表时，raw_text 必须原样保留
    所有数字 + 点 + 空格的字符序列，**不得**被 backend 在包装阶段解释为
    菜单选择 / plan 编号 / step 索引。

    背景：runtime 在 plan/confirmation 场景里会处理 "y" / "n" / 数字选择；
    若 paste burst 实现误把粘贴块的 "1." 当成"用户选了第 1 项"，会把
    一段完整旅游需求拆成 9 次菜单选择，灾难级 UX。这条测试明确
    backend 层不允许做这种解释——解释属于 InputResolution / runtime，不属于
    输入后端。
    """

    pasted = "\n".join(PASTED_NUMBERED_LINES)

    event = read_user_input_event(
        reader=_make_reader([pasted]),
        writer=_silent_writer,
    )

    assert event.envelope is not None
    raw = event.envelope.raw_text
    for marker in ("1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9."):
        assert marker in raw, f"编号标记 {marker!r} 必须原样保留在 raw_text"
    # 同时确保「粘贴整体」没有被截成单独的菜单选择字符串
    assert raw.count("\n") == 8, "9 行编号粘贴应保留 8 个换行（即 9 行整体）"
    assert event.envelope.input_mode == "multiline"
