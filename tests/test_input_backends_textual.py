"""Textual backend 的 smoke test。

Textual backend 只是显式启用的 TUI v1 skeleton：它只做 I/O adapter，不碰
Runtime state，不保存 checkpoint，不判断 plan/tool/step。UserInputEvent 是
TUI/simple backend 和 main loop 的边界；cancelled/closed 不是空输入，不能进入
chat。
"""

from __future__ import annotations

import importlib.util

import pytest


def _require_textual():
    """Textual 是可选依赖；未安装时用 xfail 记录当前可观测风险。"""

    if importlib.util.find_spec("textual") is None:
        pytest.xfail(
            "当前环境未安装 optional textual 包，无法运行 headless TUI smoke。"
            "这暴露的风险是显式启用 MY_FIRST_AGENT_INPUT_BACKEND=textual 后才会"
            "发现依赖/构造问题；安装 textual 后应转为普通通过测试。"
        )


def test_textual_backend_app_class_can_be_built_when_dependency_exists():
    """安装 Textual 时，TUI App 类应可构造，并暴露预期 widget 标识。"""

    _require_textual()

    from agent.input_backends.textual import _build_textual_app_class

    app_cls = _build_textual_app_class()
    app = app_cls(prompt_text="你: ", latest_output="last answer")

    assert app.prompt_text == "你: "
    assert app.latest_output == "last answer"
    assert "#output-panel" in app.CSS
    assert "#input-area" in app.CSS
    assert "#help-bar" in app.CSS

    bindings = {(binding.key, binding.action) for binding in app.BINDINGS}
    assert ("ctrl+s", "submit") in bindings
    assert ("escape", "cancel") in bindings
    assert ("ctrl+d", "close_input") in bindings


def test_textual_backend_submit_helper_preserves_raw_multiline_text():
    """不启动真实 UI 时，也要钉住 TextArea 文本到 submitted event 的边界。"""

    from agent.input_backends.textual import (
        _cancelled_textual_event,
        _closed_textual_event,
        _submitted_textual_event,
    )

    raw_text = "line1\n\nline3"
    submitted = _submitted_textual_event(raw_text)
    cancelled = _cancelled_textual_event()
    closed = _closed_textual_event()

    assert submitted.event_type == "input.submitted"
    assert submitted.event_source == "tui"
    assert submitted.event_channel == "text_area_submit"
    assert submitted.envelope is not None
    assert submitted.envelope.raw_text == raw_text
    assert submitted.envelope.input_mode == "multiline"

    assert cancelled.event_type == "input.cancelled"
    assert cancelled.envelope is None

    assert closed.event_type == "input.closed"
    assert closed.envelope is None
