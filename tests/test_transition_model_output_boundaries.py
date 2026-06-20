"""Model output classification and dispatch transition boundary tests.

本文件从原 3000+ 行 v0.4 transition characterization 巨型文件按行为边界拆出。
拆分只改变测试组织，不改变断言语义；这样后续 core / memory / SubAgent
重构时可以局部审查，避免一个历史巨石同时承载所有边界风险。
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace


def test_model_output_kind_enum_covers_known_dispatch_branches() -> None:
    """ModelOutputKind 必须显式覆盖 core.py 当前 dispatcher 的 4 类结果。

    模拟边界：如果未来有人新增分支但忘记加 enum，本测试会立刻失败；
    反过来如果有人删枚举想让 dispatch 缩减成 3 类，也会在这里被钉住。
    """

    from agent.runtime_events import ModelOutputKind

    assert {kind.value for kind in ModelOutputKind} == {
        "end_turn",
        "tool_use",
        "max_tokens",
        "unknown",
    }


def test_classify_model_output_is_pure_and_total() -> None:
    """classify_model_output 必须是纯函数并对未知输入显式返回 UNKNOWN。

    模拟边界：
    - 已知的 3 个 stop_reason 各自映射到独立 kind；
    - ``None`` / 空串 / 大小写变体 / SDK 未来新增字段一律 UNKNOWN，
      **不能**被静默归入 end_turn / tool_use / max_tokens——这是
      slice 5 的核心防回归点。
    """

    from agent.runtime_events import ModelOutputKind, classify_model_output

    assert classify_model_output("end_turn") is ModelOutputKind.END_TURN
    assert classify_model_output("tool_use") is ModelOutputKind.TOOL_USE
    assert classify_model_output("max_tokens") is ModelOutputKind.MAX_TOKENS

    for unknown in (None, "", "End_Turn", "stop_sequence", "refusal", "future_value"):
        assert classify_model_output(unknown) is ModelOutputKind.UNKNOWN, (
            f"未知 stop_reason {unknown!r} 不能被静默并入已知类别"
        )


def test_classify_model_output_does_not_touch_state_or_messages() -> None:
    """分类是纯计算：不能读写 state、messages、checkpoint、RuntimeEvent。

    模拟边界：通过给定一个明显不该被改动的 sentinel state，确认分类前后
    deepcopy 等价；如果未来有人在 classifier 里偷偷改 task / conversation，
    本测试立刻失败。
    """

    from agent.runtime_events import classify_model_output
    from agent.state import create_agent_state

    state = create_agent_state(system_prompt="test")
    snapshot_before = copy.deepcopy(
        {
            "status": state.task.status,
            "current_step_index": state.task.current_step_index,
            "messages_len": len(state.conversation.messages),
        }
    )

    for stop_reason in (None, "end_turn", "tool_use", "max_tokens", "weird"):
        classify_model_output(stop_reason)

    snapshot_after = {
        "status": state.task.status,
        "current_step_index": state.task.current_step_index,
        "messages_len": len(state.conversation.messages),
    }
    assert snapshot_before == snapshot_after


def test_model_output_dispatch_uses_classifier_and_routes_handlers_correctly() -> None:
    """model_output_dispatch 必须通过 classify_model_output 分派。

    模拟边界：
    - 这是 source-level 契约测试。``_run_main_loop`` 是定义在 ``chat()``
      内部的闭包，state 通过闭包捕获，从外部直接调用不可行——所以这里
      不再尝试单独调度循环（真实 dispatch 行为已被 723 全量测试覆盖），
      转为在源码层面钉死"分类层确实被使用"。
    - 任何把 ``classify_model_output`` 调用回退成 ``response.stop_reason
      == "..."`` inline 比较的回归都会立刻失败。
    - UNKNOWN 分支的显式注释/标识也必须保留，避免未来有人把 fallback
      路径删掉让未知 stop_reason 静默被吸收到已知类别。
    """

    import agent.model_output_dispatch as dispatch
    from agent.runtime_events import ModelOutputKind, classify_model_output

    # 1. dispatch 模块必须实际 import 分类符号（而不是只放在文档里）。
    assert dispatch.classify_model_output is classify_model_output
    assert dispatch.ModelOutputKind is ModelOutputKind

    source = Path(dispatch.__file__).read_text(encoding="utf-8")

    # 2. 分类调用必须出现在源码中。
    assert "classify_model_output(response.stop_reason)" in source

    # 3. 4 类标签必须各自在 dispatch 中显式比较一次。
    for kind_name in ("MAX_TOKENS", "END_TURN", "TOOL_USE"):
        assert f"ModelOutputKind.{kind_name}" in source, (
            f"model_output_dispatch 必须按 ModelOutputKind.{kind_name} 路由"
        )

    # 4. UNKNOWN 必须有显式 fallback（保留 "[系统] 未知的 stop_reason" 文案）。
    assert "未知的 stop_reason" in source
    assert "意外的响应" in source

    # 5. 旧的 inline 比较模式不能再出现在 _run_main_loop 范围内——
    #    以函数边界粗略截取做静态检查，避免误伤其它注释。
    dispatch_marker = "def dispatch_model_output"
    dispatch_start = source.index(dispatch_marker)
    dispatch_segment = source[dispatch_start: dispatch_start + 8000]
    for forbidden in (
        'response.stop_reason == "max_tokens"',
        'response.stop_reason == "end_turn"',
        'response.stop_reason == "tool_use"',
    ):
        assert forbidden not in dispatch_segment, (
            f"dispatch_model_output 已迁移到 ModelOutputKind 分派，不应再出现 {forbidden}"
        )


def test_core_dispatch_unknown_stop_reason_handled_via_explicit_fallback() -> None:
    """未知 stop_reason 必须走显式 UNKNOWN fallback，不能被静默吸收。

    模拟边界：
    - 同样是 source-level 契约：UNKNOWN 分支必须留有可识别的标记（注释
      或显式枚举引用），让未来"顺手简化"四类分支为三类的回归立刻失败。
    - 行为级别的"未知 stop_reason 不会进入 end_turn / tool_use /
      max_tokens handler"由 classify_model_output 纯函数测试 +
      上一条 source-level 测试共同保证。
    """

    import agent.model_output_dispatch as dispatch

    source = Path(dispatch.__file__).read_text(encoding="utf-8")
    # 必须保留对 UNKNOWN 的语义承诺：要么显式枚举引用，要么注释里写明。
    assert (
        "ModelOutputKind.UNKNOWN" in source
        or "UNKNOWN：未知 stop_reason" in source
    ), "model_output_dispatch 必须显式承认 UNKNOWN 分支存在，不能让未知 stop_reason 静默"


def test_classify_model_output_does_not_leak_into_durable_state(
    tmp_path,
    monkeypatch,
) -> None:
    """分类标签不能被写进 messages 或 checkpoint。

    模拟边界：跑一个 tool_use 真实路径，再 dump checkpoint+messages 找
    "ModelOutputKind" / "classify_model_output" 字面量，确保分类层只是
    Runtime 内部决策，不会泄漏到 durable state。
    """

    import agent.tool_executor as te
    from agent import checkpoint
    from agent.state import create_agent_state

    checkpoint_path = tmp_path / "checkpoint.json"
    monkeypatch.setattr(checkpoint, "CHECKPOINT_PATH", checkpoint_path)
    monkeypatch.setattr(te, "needs_tool_confirmation", lambda name, inp: False)
    monkeypatch.setattr(te, "execute_tool", lambda name, inp, context=None: "ok")

    state = create_agent_state(system_prompt="test")
    state.conversation.messages = [
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_classify",
                    "name": "read_file",
                    "input": {"path": "README.md"},
                }
            ],
        }
    ]
    turn_state = SimpleNamespace(
        round_tool_traces=[],
        on_runtime_event=None,
        on_display_event=lambda ev: None,
    )
    block = SimpleNamespace(
        id="toolu_classify",
        name="read_file",
        input={"path": "README.md"},
    )
    te.execute_single_tool(
        block,
        state=state,
        turn_state=turn_state,
        turn_context={},
        messages=state.conversation.messages,
    )

    serialized_messages = json.dumps(state.conversation.messages, ensure_ascii=False)
    payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    serialized_checkpoint = json.dumps(payload, ensure_ascii=False)
    for marker in ("ModelOutputKind", "classify_model_output"):
        assert marker not in serialized_messages
        assert marker not in serialized_checkpoint
