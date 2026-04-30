"""Display event contract characterization tests（v0.6.1 Group D）。

模块职责
--------
把 `agent/display_events.py` 中 `DisplayEvent` / `RuntimeEvent` 的展示
契约钉成机器可校验的断言，作为 v0.6 进入 TUI 危险区前的第三层防回归网。
本文件聚焦：

- D1 · `DisplayEvent` / `RuntimeEvent` 是 `frozen=True` + `slots=True`
  dataclass —— 这两个事件**只能被传递、不能被 mutate**。
- D2 · `DisplayEvent` 字段集合 = `{event_type, title, body, severity,
  metadata}` 是 v0.6.1 时刻的 characterization baseline。
- D3 · `agent/display_events.py` 是**叶子模块** —— AST 检查它没有任何
  `from agent.* import` 反向依赖，意味着它**结构上不可能**直接 mutate
  runtime state、写 checkpoint 或调用 tool executor。
- D4 · `EVENT_*` 常量集合是当前 display/observation event 的 baseline。
- D5 · `render_display_event` / `render_runtime_event_for_cli` 返回 `str`，
  即"展示出口只产文本，不产 mutation/decision"。

模块**不**负责
--------------
- 不验证 display event 的渲染美观度、UI 表现、Textual widget 行为。
- 不替代 `tests/test_runtime_event_boundaries.py` 等已有功能性测试。
- **不**禁止未来新增 EVENT_* 常量或扩展字段——D2/D4 只是 characterization
  baseline；若未来新增，需要显式审视新增项是否仍属"展示/观察 event"，
  而不是 runtime decision event（如 "execute tool" / "save checkpoint"
  / "approve plan" 等）。

为什么这样设计
--------------
v0.5.x 已把 DisplayEvent/RuntimeEvent 设为 frozen+slots，且 display_events.py
天然没有 `from agent.*` import。但**没有测试钉死**这些不变量：任何后续
PR 可能悄悄把 `frozen=True` 去掉、加个 `runtime_state` 字段、或从
display_events.py `from agent.checkpoint import save_checkpoint`，让 display
层反向污染 runtime。本文件把这些不变量升级为可执行断言。

artifact 排查路径
-----------------
- D1 失败：有人改了 dataclass 配置；先 `git diff agent/display_events.py`，
  根因要么真有 mutation 需求（应改设计而非测试），要么是误改（回滚）。
- D2/D4 失败：字段或 EVENT_* 集合被扩——必须显式判断新增项是否仍是
  "展示/观察 event"；如果是，更新 baseline；如果是 runtime decision，
  改 production 把它移到 runtime_events 而非 display_events。
- D3 失败：display_events.py 出现 `from agent.*` import——这是 display
  层反向污染 runtime 的强信号，必须改 production。

未来扩展点
----------
- 若引入新 display event 模块（如 `agent/display_events_v2.py`），扩展
  `_DISPLAY_MODULE_FILES` 即可。
- 若需要更细粒度地区分 "display event" vs "runtime observation event"，
  可在本文件新增 group。

MVP / Mock 边界
---------------
本文件**不是** mock；也**不是** demo-only。它是 v0.6 进入 TUI 区域前
真正能拦住 display contract 漂移、防止 display 层反向污染 runtime 的
最小防回归测试集。
"""
from __future__ import annotations

import ast
import dataclasses
import inspect
from pathlib import Path

from agent.display_events import (
    EVENT_ASSISTANT_DELTA,
    EVENT_CONTROL_MESSAGE,
    EVENT_DISPLAY_EVENT,
    EVENT_FEEDBACK_INTENT_REQUESTED,
    EVENT_LOOP_MAX_ITERATIONS,
    EVENT_PLAN_CONFIRMATION_REQUESTED,
    EVENT_STATE_INCONSISTENCY_RESET,
    EVENT_TOOL_CONFIRMATION_REQUESTED,
    EVENT_TOOL_REQUESTED,
    EVENT_TOOL_RESULT_VISIBLE,
    EVENT_UNKNOWN_STOP_REASON,
    EVENT_USER_INPUT_REQUESTED,
    DisplayEvent,
    RuntimeEvent,
    render_display_event,
    render_runtime_event_for_cli,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
AGENT_DIR = PROJECT_ROOT / "agent"
_DISPLAY_MODULE_FILES = (AGENT_DIR / "display_events.py",)


# ===================== D1 · 不可变 dataclass 基线 =====================

def test_display_event_and_runtime_event_are_frozen_slots_dataclass() -> None:
    """`DisplayEvent` / `RuntimeEvent` 必须是 frozen=True + slots=True dataclass。

    fake/mock 边界说明：本测试只读 dataclass 元数据，不构造真实事件。
    设计意图：display/runtime observation event 是从 runtime 流向 UI 的
    单向不可变数据；frozen 防止 UI 层悄悄改字段、slots 防止 UI 层悄悄
    塞额外属性。任一不变量丢失，都意味着 display 层有潜力反过来 mutate
    runtime 在意的事件载荷。

    若失败：根因排查见模块 docstring "artifact 排查路径"。
    """
    for cls in (DisplayEvent, RuntimeEvent):
        assert dataclasses.is_dataclass(cls), f"{cls.__name__} 必须是 dataclass"
        assert cls.__dataclass_params__.frozen, (
            f"{cls.__name__} 必须 frozen=True，display 层不可 mutate event 字段。"
        )
        assert "__slots__" in cls.__dict__, (
            f"{cls.__name__} 必须 slots=True，避免 display 层悄悄塞额外属性。"
        )


# ===================== D2 · DisplayEvent 字段集合 baseline =====================

# 这是 v0.6.1 时刻的 characterization baseline，**不是**演进禁令。
# 若未来需要扩字段，必须在 PR 中显式回答：新字段是否会把 runtime state /
# checkpoint / transition decision 泄漏进 display contract？
_DISPLAY_EVENT_BASELINE_FIELDS: frozenset[str] = frozenset(
    {"event_type", "title", "body", "severity", "metadata"}
)


def test_display_event_fields_baseline_is_display_only() -> None:
    """`DisplayEvent` 的字段集合保持 display-only baseline。

    fake/mock 边界说明：dataclass `fields()` 反射，零副作用。
    baseline 含义：这些字段都是"给 UI 看的"——event_type 标识种类、
    title/body 是文本、severity 是 UI 颜色级别、metadata 是开放扩展点。
    任何形如 `runtime_state` / `pending_tool` / `checkpoint_id` 的新字段
    都会让 DisplayEvent 不再是纯展示，必须**先**重新审视而非机械改 baseline。
    """
    actual_fields = {f.name for f in dataclasses.fields(DisplayEvent)}
    assert actual_fields == _DISPLAY_EVENT_BASELINE_FIELDS, (
        f"DisplayEvent 字段集合从 baseline {sorted(_DISPLAY_EVENT_BASELINE_FIELDS)}"
        f" 漂移到 {sorted(actual_fields)}；新增/删除字段前必须显式审视是否仍属"
        " display-only contract（参见模块 docstring 'artifact 排查路径'）。"
    )


# ===================== D3 · display_events.py 是叶子模块 =====================

def test_display_events_module_is_leaf_no_reverse_agent_imports() -> None:
    """`agent/display_events.py` 不允许 import 任何 `agent.*` 子模块。

    fake/mock 边界说明：AST 解析，不执行模块。
    设计意图：display_events.py 在依赖图里应是**叶子**——它定义被 runtime
    与 TUI 共同消费的事件 schema，自己不应反向触达 runtime（core / state /
    checkpoint / tool_executor / handlers 等）。一旦它出现 `from agent.X
    import ...`，display 层就有路径直接 mutate runtime 在意的对象。

    若失败：检查最近改动是否把"渲染时顺手做点 runtime 副作用"的代码塞进
    display_events.py；根因必须改 production，不准修测试放行。
    """
    for path in _DISPLAY_MODULE_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        leaked: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and (node.module == "agent" or node.module.startswith("agent.")):
                    leaked.append(node.module)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "agent" or alias.name.startswith("agent."):
                        leaked.append(alias.name)
        assert leaked == [], (
            f"{path.name} 必须保持叶子模块（无 from agent.* import），"
            f" 发现反向依赖：{sorted(set(leaked))}。"
            " display 层一旦反向触达 runtime，TUI/display 就有路径 mutate runtime。"
        )


# ===================== D4 · EVENT_* 常量集合 baseline =====================

# 当前 display/observation event 常量 baseline。
# 与 D2 同样是 characterization，不是演进禁令：未来若需新增 event，必须
# 在 PR 中显式回答 "新 event 是 display/observation event，还是 runtime
# decision event（如 execute tool / save checkpoint / approve plan）？"
# 后者应当走 runtime_events 而非 display_events。
_EVENT_BASELINE: frozenset[str] = frozenset(
    {
        EVENT_ASSISTANT_DELTA,
        EVENT_DISPLAY_EVENT,
        EVENT_CONTROL_MESSAGE,
        EVENT_TOOL_REQUESTED,
        EVENT_PLAN_CONFIRMATION_REQUESTED,
        EVENT_USER_INPUT_REQUESTED,
        EVENT_TOOL_CONFIRMATION_REQUESTED,
        EVENT_TOOL_RESULT_VISIBLE,
        EVENT_FEEDBACK_INTENT_REQUESTED,
        EVENT_STATE_INCONSISTENCY_RESET,
        EVENT_LOOP_MAX_ITERATIONS,
        EVENT_UNKNOWN_STOP_REASON,
    }
)


def test_event_kind_constants_baseline_is_display_or_observation_only() -> None:
    """`EVENT_*` 常量集合是 v0.6.1 时刻的展示/观察 event baseline。

    fake/mock 边界说明：纯属性导入对比，零副作用。
    baseline 含义：清单中每一项都是"runtime 已经决定后告诉 UI 显示什么"，
    不包含"UI 让 runtime 做什么"。任何新增项都必须显式判断它是
    display/observation 还是 decision；后者请放到 runtime_events 模块。

    本测试**不**禁止演进——它强迫每次扩展 baseline 时必须做一次显式
    review（更新 baseline = 一行代码 + commit message 中的理由）。
    """
    from agent import display_events as de_module

    actual_event_constants: set[str] = set()
    for name, value in vars(de_module).items():
        if name.startswith("EVENT_") and isinstance(value, str):
            actual_event_constants.add(value)

    drift = actual_event_constants.symmetric_difference(_EVENT_BASELINE)
    assert drift == set(), (
        f"display event 常量集合从 baseline 漂移：差异 {sorted(drift)}。"
        " 若新增的是展示/观察 event，请同步更新本测试的 _EVENT_BASELINE 并在"
        " commit message 中说明；若新增的是 runtime decision event，请改"
        " production 把它移到 runtime_events 模块（display 层禁止决策）。"
    )


# ===================== D5 · render 函数只产展示文本 =====================

def test_render_functions_return_str() -> None:
    """display 渲染出口只能产 `str`，不能产 mutation 或 decision 对象。

    fake/mock 边界说明：通过 `inspect.get_annotations(eval_str=True)` 读
    返回类型注解（display_events.py 用了 `from __future__ import annotations`，
    注解被存为字符串，必须显式 eval）；不真正执行渲染（避免依赖具体 event
    实例构造细节）。

    设计意图：render 是 display 层的**最终出口**——任何"渲染时顺手返回
    一个 transition command"或"返回 mutated state"的设计都会破坏单向
    数据流。锁住返回类型为 str 是最弱、最稳的边界。

    若失败：可能有人把 render 改成返回 RichRenderable / Widget / dict 等
    复合类型——若是为了 UI 富文本，正确做法是返回 str + 由 TUI 层独立
    解析，而不是让 render 出口承担 UI 类型。
    """
    for fn in (render_display_event, render_runtime_event_for_cli):
        annotations = inspect.get_annotations(fn, eval_str=True)
        return_type = annotations.get("return")
        assert return_type is str, (
            f"{fn.__name__} 返回类型必须是 str，"
            f" 当前为 {return_type!r}。"
            " display 渲染出口禁止承担 mutation 或 decision 类型。"
        )
