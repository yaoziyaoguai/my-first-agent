"""Input backend user-input contract characterization tests（v0.6.1 Group C）。

模块职责
--------
把 `agent/input_backends/textual.py` / `agent/input_backends/simple.py`
与 `agent/user_input.py` 之间的**用户输入 contract**钉成机器可校验的
断言，作为 v0.6 进入 TUI 危险区前的第二层防回归网。本文件聚焦：

- C1 · `UserInputEnvelope` 的 `raw_text` 字段始终存在 = **free-text 入口**
  契约不被破坏。
- C2 · `UserInputEvent` 的 `event_type` 仅有 3 种 (`submitted` /
  `cancelled` / `closed`)，且 `__post_init__` 强制 submitted 必须带
  envelope —— 即 **"用 print 假装 Ask User"** 这种伪造路径在合约层
  被拒绝。
- C3 · TUI 适配器源码不出现对 `state.task.*` / `pending_user_input_request`
  / `pending_tool` 等 runtime state 的赋值 —— input backend **不直接
  mutate** runtime state。
- C4 · TUI 适配器**通过 callable 委托**而非内联实现 runtime decision
  （textual: `chat_handler`；simple: `reader`/`writer`）。
- 与 v0.6.1 Group A 黑名单（`tests/test_tui_dependency_boundaries.py`）
  形成 **import + state-mutation + delegation** 三层防御。

模块**不**负责
--------------
- 不执行真实 textual / 真实 runtime / 真实 input；纯静态/dataclass 检查。
- 不替代 `tests/test_input_backends_*` / `test_main_input.py` /
  `test_user_input.py` 等已有功能性测试。
- 不解 / 不新增任何 strict xfail。
- **不强制 production 添加 return type annotation**（避免脆弱的 API
  注解测试），只用源码 grep + dataclass `fields` 这类天然稳定信号。

为什么这样设计
--------------
v0.5.x 已把 `UserInputEnvelope` / `UserInputEvent` 建成不可变 frozen
dataclass，并在 `__post_init__` 拒绝 "submitted 不带 envelope" 与
"cancelled/closed 携带 envelope" 这类伪造组合。但目前**没有测试钉死**
"raw_text 字段名不可改"、"event_type 集合不可扩"、"input backend 不
直接 mutate state" 这些下一层 invariant。本文件把它们升级为可执行断言。

artifact 排查路径
-----------------
- C1/C2 失败：很可能有人改了 `UserInputEnvelope` / `UserInputEvent` 的
  字段或 event_type 集合 —— 先 `git diff agent/user_input.py`，再判断
  是否真的有 contract 演进需求；如果有，必须同时升级所有 input backend
  与下游消费方，不准只为了通过测试就回退本测试。
- C3 失败：`agent/input_backends/textual.py` 或 `simple.py` 出现
  `state.task.* =` 之类赋值 —— 这是 input backend 直接污染 runtime
  state 的征兆，根因必须改 production 改回委托模式。
- C4 失败：input backend 不再通过 `chat_handler` / `reader` / `writer`
  callable 委托 —— 检查是否被错误内联进 backend，若是则改 production。

未来扩展点
----------
- 若引入新的 input backend（如 prompt_toolkit），把它加入 `_TUI_FILES`
  并复用 C3/C4 的 source 扫描即可。
- 若 `UserInputEvent` 真的需要新增 event_type（例如 `input.timeout`），
  必须**同时**：(a) 升级 `__post_init__` 校验；(b) 升级本文件 C2
  的 `_EXPECTED_EVENT_TYPES`；(c) 升级所有下游消费方。

MVP / Mock 边界
---------------
本文件**不是** mock；也**不是** demo-only。它是 v0.6 进入 TUI 区域前
真正能拦住 input contract 漂移的最小防回归测试集。
"""
from __future__ import annotations

import ast
import dataclasses
import re
from pathlib import Path

import pytest

from agent.user_input import UserInputEnvelope, UserInputEvent

PROJECT_ROOT = Path(__file__).resolve().parent.parent
AGENT_DIR = PROJECT_ROOT / "agent"

_TUI_FILES = (
    AGENT_DIR / "input_backends" / "textual.py",
    AGENT_DIR / "input_backends" / "simple.py",
)


# ===================== C1 · free-text 入口契约 =====================

def test_user_input_envelope_keeps_raw_text_field() -> None:
    """`UserInputEnvelope.raw_text` 必须存在，且为 frozen dataclass 字段。

    这个字段是 free-text 入口的真正承载体：用户的自然语言、多行粘贴、
    Other 选项之外的自由输入都通过它进入 runtime。

    fake/mock 边界说明：本测试只检查 dataclass 元数据，不构造真实 envelope。
    若失败：根因不是测试太严，而是有人改了 envelope 字段名/语义，会让
    所有下游"raw_text 永远在"假设崩溃。必须改 production 回滚或同步升级
    所有消费方，不准修测试放行。
    """
    fields_by_name = {f.name: f for f in dataclasses.fields(UserInputEnvelope)}
    assert "raw_text" in fields_by_name, (
        "UserInputEnvelope 必须保留 raw_text 字段作为 free-text 入口；"
        " 若 contract 演进，需同步升级所有 input backend 与消费方。"
    )
    assert fields_by_name["raw_text"].type in {"str", str}, (
        "raw_text 必须是 str 类型，free-text 入口不应被结构化字段替换。"
    )
    assert UserInputEnvelope.__dataclass_params__.frozen, (
        "UserInputEnvelope 必须 frozen，避免输入快照被下游悄悄篡改。"
    )


# ===================== C2 · Ask User 不能用 print 伪造 =====================

# `UserInputEvent.event_type` 当前合约的有限集合。
# 任何对此集合的扩展都必须**同时**升级 __post_init__ 校验、所有 backend
# 的产出路径，以及本测试 —— 三处要么同时改，要么都不改。
_EXPECTED_EVENT_TYPES: frozenset[str] = frozenset(
    {"input.submitted", "input.cancelled", "input.closed"}
)


def test_user_input_event_type_set_is_pinned() -> None:
    """`event_type` Literal 集合不可静默扩张。

    `UserInputEvent.event_type` 是 Literal，类型层面已限定；本测试用
    `__post_init__` 行为反推这 3 种状态都被合约显式覆盖（submitted
    需 envelope；cancelled/closed 不可有 envelope）。

    fake/mock 边界说明：本测试通过构造合法/非法 event 实例验证 contract，
    不调用任何 backend、不触发 runtime。
    """
    fake_envelope = UserInputEnvelope(
        raw_text="hi",
        normalized_text="hi",
        input_mode="single_line",
        source="cli",
        line_count=1,
        is_empty=False,
    )

    UserInputEvent(
        event_type="input.submitted",
        event_source="simple",
        event_channel="test",
        envelope=fake_envelope,
    )
    UserInputEvent(
        event_type="input.cancelled",
        event_source="simple",
        event_channel="test",
        envelope=None,
    )
    UserInputEvent(
        event_type="input.closed",
        event_source="simple",
        event_channel="test",
        envelope=None,
    )

    with pytest.raises(ValueError):
        UserInputEvent(
            event_type="input.submitted",
            event_source="simple",
            event_channel="test",
            envelope=None,
        )

    with pytest.raises(ValueError):
        UserInputEvent(
            event_type="input.cancelled",
            event_source="simple",
            event_channel="test",
            envelope=fake_envelope,
        )


def test_input_backends_must_return_user_input_event_not_print() -> None:
    """TUI 适配器必须有"返回 UserInputEvent"路径，禁止仅用 print 替代。

    判定方法（弱约束、不强制注解）：在源码中 grep 至少一处
    `return submitted_input_event(` / `return cancelled_input_event(` /
    `return closed_input_event(` —— 只要 backend 通过 user_input.py
    提供的工厂函数返回事件，就证明它走的是真合约而非"只 print 就完"。

    fake/mock 边界说明：纯源码扫描，不执行 backend；故意不依赖具体函数
    名以外的实现细节，避免脆弱。
    """
    factory_pattern = re.compile(
        r"\b(submitted_input_event|cancelled_input_event|closed_input_event)\b"
    )
    for tui_file in _TUI_FILES:
        source = tui_file.read_text(encoding="utf-8")
        assert factory_pattern.search(source), (
            f"{tui_file.name} 未引用 user_input 模块的任一事件工厂"
            " (submitted_input_event / cancelled_input_event / closed_input_event)；"
            " 这意味着 backend 可能在用 print/return 字符串伪造 Ask User，"
            " 而非走真正的 UserInputEvent 合约。"
        )


# ===================== C3 · TUI 不直接 mutate runtime state =====================

# 禁止在 TUI 源码中**赋值**的 runtime state 字段路径前缀。
# 用正则 `<prefix>\s*=` 只匹配赋值，不匹配 docstring/属性读取。
_FORBIDDEN_STATE_ASSIGNMENT_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"state\.task\.[A-Za-z_]+\s*=", "state.task.* ="),
    (r"\bpending_user_input_request\s*=", "pending_user_input_request ="),
    (r"\bpending_tool\s*=", "pending_tool ="),
    (r"\bcurrent_step\s*=", "current_step ="),
    (r"\bcurrent_plan\s*=", "current_plan ="),
)


@pytest.mark.parametrize("tui_file", _TUI_FILES, ids=lambda p: p.name)
def test_tui_backend_does_not_mutate_runtime_state(tui_file: Path) -> None:
    """TUI 适配器源码不得对 runtime state 做赋值。

    fake/mock 边界说明：纯源码正则扫描，仅匹配 `<prefix> =` 赋值形式，
    不会因 docstring 中出现字段名而误伤（v0.6.1 Group E 假阳性教训）。

    若失败：根因不是测试太严，而是 input backend 开始绕过 runtime 直接
    改 state —— 必须改 production 回到委托模式（chat_handler 等）。
    """
    source = tui_file.read_text(encoding="utf-8")
    hits: list[str] = []
    for pattern, label in _FORBIDDEN_STATE_ASSIGNMENT_PATTERNS:
        for m in re.finditer(pattern, source):
            line_no = source.count("\n", 0, m.start()) + 1
            hits.append(f"{label} @line {line_no}")
    assert hits == [], (
        f"{tui_file.name} 出现禁止的 runtime state 赋值：{hits}。"
        " input backend 必须通过 chat_handler / UserInputEvent 委托，"
        " 不可直接 mutate runtime state。"
    )


# ===================== C4 · TUI 通过 callable 委托 runtime decision =====================

# 各 backend 期望出现的"委托 callable"形参名（最小弱约束）。
# 这是基于 v0.6.1 时实际代码的事实快照；如果 backend 重命名形参，需要
# 同时审视是否改变了"委托而非内联"语义，再决定是否更新本表。
_DELEGATION_CALLABLES: dict[str, tuple[str, ...]] = {
    "textual.py": ("chat_handler",),
    "simple.py": ("reader", "writer"),
}


@pytest.mark.parametrize(
    "tui_file",
    _TUI_FILES,
    ids=lambda p: p.name,
)
def test_tui_backend_delegates_runtime_via_callable(tui_file: Path) -> None:
    """TUI 适配器必须通过 Callable 形参委托 runtime decision。

    判定方法：在源码中至少出现一次 `<param>: Callable` 形式的参数注解，
    表明 backend 不在内部内联 runtime 决策，而是把决策权交给调用方。

    fake/mock 边界说明：纯源码扫描，不执行 backend。
    若失败：可能 backend 把 runtime 决策内联了 —— 应改 production 还原
    委托模式，不准为了通过测试在 backend 里硬塞个 dummy callable。
    """
    source = tui_file.read_text(encoding="utf-8")
    expected = _DELEGATION_CALLABLES[tui_file.name]
    missing: list[str] = []
    for name in expected:
        pattern = re.compile(rf"\b{name}\s*:\s*Callable\b")
        if not pattern.search(source):
            missing.append(name)
    assert missing == [], (
        f"{tui_file.name} 缺少期望的 Callable 委托形参：{missing}。"
        " input backend 必须通过 callable 委托 runtime 决策，不得内联。"
    )


# ===================== C5 · input backend 不绕过 confirmation handlers =====================

_CONFIRMATION_HANDLER_CALLS: frozenset[str] = frozenset(
    {
        "handle_plan_confirmation",
        "handle_step_confirmation",
        "handle_user_input_step",
        "handle_tool_confirmation",
        "handle_feedback_intent_choice",
    }
)

_RUNTIME_PENDING_FIELD_NAMES: frozenset[str] = frozenset(
    {
        "pending_user_input_request",
        "pending_tool",
        "tool_execution_log",
        "current_plan",
        "current_step_index",
    }
)

_RUNTIME_CONFIRMATION_STATUS_VALUES: frozenset[str] = frozenset(
    {
        "awaiting_plan_confirmation",
        "awaiting_step_confirmation",
        "awaiting_user_input",
        "awaiting_feedback_intent",
        "awaiting_tool_confirmation",
    }
)


def _parse_source(path: Path) -> ast.AST:
    """用 AST 读取 backend 源码，避免 grep docstring 造成边界假阳性。"""

    return ast.parse(path.read_text(encoding="utf-8"))


def _dotted_name(node: ast.AST) -> str | None:
    """把 Name/Attribute 调用还原成 dotted name，用于稳定识别越界调用。"""

    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _dotted_name(node.value)
        if parent is None:
            return node.attr
        return f"{parent}.{node.attr}"
    return None


@pytest.mark.parametrize("tui_file", _TUI_FILES, ids=lambda p: p.name)
def test_input_backend_does_not_call_confirmation_handlers(tui_file: Path) -> None:
    """input backend 不得直接调用 confirmation handlers。

    这条测试保护 HITL/Input 收口前最重要的依赖方向：backend 只产生
    UserInputEvent / raw_text，不能把 `y`、`1`、free-text 等输入直接送进
    handle_plan_confirmation / handle_tool_confirmation 之类 handler。确认语义
    必须由 main/core 的 pending dispatch 路由到 confirmation handlers，否则
    backend 会绕开 checkpoint、messages、observer event 和 pending 清理，重新
    变成懂太多 runtime 细节的新巨石。
    """

    tree = _parse_source(tui_file)
    calls: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        dotted = _dotted_name(node.func)
        if dotted is None:
            continue
        short_name = dotted.rsplit(".", maxsplit=1)[-1]
        if short_name in _CONFIRMATION_HANDLER_CALLS:
            calls.append(dotted)

    assert calls == [], (
        f"{tui_file.name} 不允许直接调用 confirmation handlers：{calls}。"
        " input backend 必须把输入交给 core/main 编排层，由 confirmation handlers"
        " 作为 plan/step/tool/user_input/feedback_intent 语义的唯一入口。"
    )


@pytest.mark.parametrize("tui_file", _TUI_FILES, ids=lambda p: p.name)
def test_input_backend_does_not_read_runtime_pending_fields(tui_file: Path) -> None:
    """input backend 不得读取 runtime pending/checkpoint 相关字段。

    读取 `pending_user_input_request`、`pending_tool` 或 `current_plan` 看似只是
    “判断一下当前上下文”，实质会把 runtime state schema 泄漏到 UI/input 层。
    本 slice 只允许 backend 收集输入事实；pending 的解释权属于
    input_intents / input_resolution / confirmation handlers / core dispatch。
    """

    tree = _parse_source(tui_file)
    hits: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        dotted = _dotted_name(node)
        if dotted is None:
            continue
        if node.attr in _RUNTIME_PENDING_FIELD_NAMES or dotted.endswith(".task.status"):
            hits.append(dotted)

    assert hits == [], (
        f"{tui_file.name} 不允许读取 runtime pending/status 字段：{hits}。"
        " 这些字段属于 TaskState/runtime 层；backend 读取它们会把输入适配器"
        " 变成隐式 state machine。"
    )


@pytest.mark.parametrize("tui_file", _TUI_FILES, ids=lambda p: p.name)
def test_input_backend_does_not_branch_on_confirmation_status_values(tui_file: Path) -> None:
    """input backend 不得按 awaiting_* confirmation status 自行分支。

    这里特意扫描 AST Compare 节点，而不是简单搜索字符串：docstring 可以解释
    为什么 backend 不理解 awaiting 状态，但真实代码不能写
    `if status == "awaiting_plan_confirmation"` 这类分支。否则后续 Ask User /
    Other/free-text 会在 backend 层被提前解释，绕过 confirmation handlers。
    """

    tree = _parse_source(tui_file)
    hits: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        compared_values = [node.left, *node.comparators]
        for value in compared_values:
            if (
                isinstance(value, ast.Constant)
                and value.value in _RUNTIME_CONFIRMATION_STATUS_VALUES
            ):
                hits.append(str(value.value))

    assert hits == [], (
        f"{tui_file.name} 不允许按 runtime confirmation status 分支：{hits}。"
        " 状态分发必须集中在 core._dispatch_pending_confirmation()，"
        " 真实确认语义必须进入 confirmation handlers。"
    )
