"""main.read_user_input 多行输入协议单元测试。

不触发真实 input() / 主循环——通过依赖注入 reader/writer 喂预录序列。
覆盖：
- 单行输入原样返回（不破坏历史行为）
- /multi + /done 拼接所有中间行
- /multi + /cancel 返回 None（让主循环跳过本轮）
- ``` 围栏 + ``` 结束 拼接所有中间行
- /multi 中 stdin 提前关闭（EOFError）→ 把已收集行当 done 提交，不丢数据
"""

from __future__ import annotations


def _make_reader(lines):
    """把字符串列表包成一个一次性 reader：每次 reader() 弹出一行。"""
    queue = list(lines)

    def reader(_prompt: str = "") -> str:
        if not queue:
            raise EOFError("test reader exhausted")
        return queue.pop(0)

    return reader


def _silent_writer(*_args, **_kwargs) -> None:
    """吞掉 _collect_multiline 的提示文案，避免污染 pytest 输出。"""
    return None


# ============================================================
# 1. 普通单行输入：与历史行为一致
# ============================================================

def test_single_line_input_returned_verbatim():
    """普通一行输入应原样返回（不 strip——strip 由 main_loop 外层做）。"""
    from main import read_user_input

    out = read_user_input(
        reader=_make_reader(["hello world"]),
        writer=_silent_writer,
    )
    assert out == "hello world"


def test_single_line_with_leading_slash_not_misrouted():
    """非 /multi / /``` 的普通输入即便以斜杠开头也直接返回，
    交给主循环的 handle_slash_command 处理（如 /reload_skills）。"""
    from main import read_user_input

    out = read_user_input(
        reader=_make_reader(["/reload_skills"]),
        writer=_silent_writer,
    )
    assert out == "/reload_skills"


# ============================================================
# 2. /multi + /done：完整拼接多行
# ============================================================

def test_multi_mode_with_done_returns_joined_lines():
    """/multi → 收集 line1/line2/line3 → /done → 返回 "\\n".join。"""
    from main import read_user_input

    out = read_user_input(
        reader=_make_reader([
            "/multi",
            "下周一到周三出行",
            "从北京出发偏好高铁",
            "豪华型住宿",
            "自然风光",
            "单人出行",
            "/done",
        ]),
        writer=_silent_writer,
    )
    assert out == (
        "下周一到周三出行\n"
        "从北京出发偏好高铁\n"
        "豪华型住宿\n"
        "自然风光\n"
        "单人出行"
    )


def test_multi_mode_done_with_surrounding_whitespace_still_terminates():
    """/done 周围有空白也应识别为终止信号——_collect_multiline 用 strip 比对。"""
    from main import read_user_input

    out = read_user_input(
        reader=_make_reader(["/multi", "line1", "  /done  "]),
        writer=_silent_writer,
    )
    assert out == "line1"


# ============================================================
# 3. /multi + /cancel：返回 None
# ============================================================

def test_multi_mode_cancel_returns_none():
    """/multi → 中途 /cancel → 返回 None；调用方应跳过本轮，**不**调 chat。"""
    from main import read_user_input

    out = read_user_input(
        reader=_make_reader([
            "/multi",
            "我打错了",
            "再来一行",
            "/cancel",
        ]),
        writer=_silent_writer,
    )
    assert out is None


# ============================================================
# 4. ``` 围栏：进入粘贴模式，``` 结束
# ============================================================

def test_paste_fence_collects_until_closing_fence():
    """``` 起头 → 收集到下一个单独的 ``` → 返回中间所有行拼接。"""
    from main import read_user_input

    out = read_user_input(
        reader=_make_reader([
            "```",
            "def foo():",
            "    return 42",
            "",
            "print(foo())",
            "```",
        ]),
        writer=_silent_writer,
    )
    assert out == "def foo():\n    return 42\n\nprint(foo())"


def test_paste_fence_no_cancel_token():
    """围栏模式下 /cancel 不应被识别为取消——应当作普通内容收集。"""
    from main import read_user_input

    out = read_user_input(
        reader=_make_reader([
            "```",
            "/cancel",   # 在围栏里这是普通内容
            "more",
            "```",
        ]),
        writer=_silent_writer,
    )
    assert out == "/cancel\nmore"


# ============================================================
# 5. EOF 鲁棒性：多行模式下 stdin 关闭不丢数据
# ============================================================

def test_multi_mode_eof_treats_as_done():
    """收集中途 stdin 关闭（EOFError）→ 把已收集行当 done 提交，避免 stdin 关闭吞掉用户输入。"""
    from main import read_user_input

    out = read_user_input(
        reader=_make_reader([
            "/multi",
            "first",
            "second",
            # 后面没有 /done——reader 队列耗尽抛 EOFError
        ]),
        writer=_silent_writer,
    )
    assert out == "first\nsecond"
