"""TUI / input backend 边界 characterization tests（v0.6.1）。

模块职责
--------
用 **AST 静态检查**把 `agent/input_backends/textual.py` /
`agent/input_backends/simple.py` 与 `agent/core.py` 三者之间的依赖边界、
以及 TUI 层不应触碰的敏感路径字符串（`.env` / `agent_log.jsonl` /
真实 `sessions/` / `runs/`）固化为测试，作为 v0.6 危险区进入前的
**防回归网**：

- Group A · 依赖边界：runtime core 不允许反向 import 任何 input_backend；
  TUI 层 (`textual.py` / `simple.py`) 不允许 import runtime core /
  checkpoint / handler / executor 等内部模块。
- Group E · 无敏感读取：TUI 层源码里不应**硬编码**敏感文件/目录字面量。

模块**不**负责
--------------
- 不执行真实 Textual / 真实 Runtime；本文件**只**做源码级 AST 检查，
  不会触发任何 I/O，也不会读取真实 `.env` / `sessions/` / `runs/` 内容。
- 不验证业务逻辑、不替代 `tests/test_input_backends_*` 的功能性测试。
- 不解任何 strict xfail，不新增 strict xfail。

为什么这样设计
--------------
v0.6 之前 TUI/runtime 边界**仅由 docstring 声明**（textual.py 顶部
docstring 列出"不写 checkpoint / 不持 runtime state / ..."）。
docstring 不是机器可校验的；任何后续 PR 可能悄悄从 textual.py 反向
`from agent.core import ...`，使 TUI 反向污染 runtime core。本文件把
docstring 升级为**可执行断言**，让 CI 在第一时间发现越界。

方法选用 AST 而非真实 import 的原因：
- AST 解析无副作用；不会因导入 `agent.core` 触发 logger / observer 副作用；
- 不依赖可选包 `textual` 是否已安装；
- 与 `tests/test_v0_4_transition_boundaries.py` 中的 `forbidden_import_markers`
  风格一致。

artifact 排查路径
-----------------
- 若本文件失败：先 `git diff agent/input_backends/ agent/core.py`，
  定位是谁加了越界 import；不要通过修改本测试来"通过"，必须改回 production。
- 若 Group E 失败：检查是否有人在 TUI 模块里硬编码了 `agent_log.jsonl`
  路径或 `sessions/` 字面量——这是日后悄悄读真实日志/会话的入口。

未来扩展点
----------
- 若 v0.6.2 需要扩充 display adapter boundary，可继续在本文件增加 group。
- 若引入 `agent/input_backends/<new>.py`，应将新文件加入 `_TUI_FILES`。
- Group E 当前只做源码字面量扫描；未来若需要 runtime 级别的"open() hook
  断言不读真实 sessions"，可放到独立文件，避免本文件变成混合关切。

MVP / Mock 边界
---------------
本文件**不是** mock；也**不是** demo-only。它是 v0.6 进入 TUI 区域前
真正能拦住越界改动的最小防回归测试集。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
AGENT_DIR = PROJECT_ROOT / "agent"

_TUI_FILES = (
    AGENT_DIR / "input_backends" / "textual.py",
    AGENT_DIR / "input_backends" / "simple.py",
)
_CORE_FILE = AGENT_DIR / "core.py"


def _collect_agent_imports(path: Path) -> set[str]:
    """提取一个 .py 文件里所有 `agent.*` 子模块依赖。

    只返回顶级 dotted 路径（如 `agent.checkpoint`），不展开
    `from agent.checkpoint import X` 中的 `X` 名字——边界关心的是
    **跨模块依赖**，不是符号名。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "agent" or alias.name.startswith("agent."):
                    found.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module and (node.module == "agent" or node.module.startswith("agent.")):
                found.add(node.module)
    return found


# ===================== Group A · 依赖边界 =====================

def test_core_does_not_import_any_input_backend() -> None:
    """v0.5.1 已建立 runtime core ↔ TUI 单向边界，本测试钉死该边界。

    fake/mock 边界说明：本测试**不**执行 runtime；只做 AST 检查。
    若失败，意味着有人从 `agent/core.py` 反向 import TUI 适配器，
    会让 runtime 直接耦合显示层——根因必须改 production，不准修测试放行。
    """
    imports = _collect_agent_imports(_CORE_FILE)
    leaked = sorted(i for i in imports if i.startswith("agent.input_backends"))
    assert leaked == [], (
        f"agent/core.py 不允许 import 任何 agent.input_backends.*，发现越界：{leaked}。"
        " 根因排查：检查最近改动是否把 TUI 渲染逻辑塞进 runtime core。"
    )


# 允许 TUI 层依赖的 agent 子模块白名单（v0.6.1 基线快照）。
# 任何新增项必须经过 review，禁止把 core / checkpoint / handler / executor
# 加入此列表来"通过"测试。
_ALLOWED_TUI_AGENT_DEPS: set[str] = {
    "agent.display_events",
    "agent.user_input",
}

# 明确禁止 TUI 层 import 的 runtime 内部模块。
# 这些是"如果出现就是越界"的硬黑名单。
_FORBIDDEN_TUI_AGENT_DEPS: set[str] = {
    "agent.core",
    "agent.checkpoint",
    "agent.confirm_handlers",
    "agent.response_handlers",
    "agent.tool_executor",
    "agent.tool_registry",
    "agent.state",
    "agent.runtime_observer",
    "agent.loop_context",
    "agent.context_builder",
    "agent.planner",
    "agent.memory",
}


@pytest.mark.parametrize("tui_file", _TUI_FILES, ids=lambda p: p.name)
def test_tui_backend_only_depends_on_allowed_agent_modules(tui_file: Path) -> None:
    """`textual.py` / `simple.py` 只允许依赖 display_events / user_input。

    fake/mock 边界说明：本测试只读源码，不会调用 backend。失败时禁止把
    新依赖塞入 `_ALLOWED_TUI_AGENT_DEPS`——必须先回答"为什么 TUI 适配器
    要直接依赖该 runtime 模块？是否应该改为通过 display event 解耦？"
    """
    imports = _collect_agent_imports(tui_file)
    extra = sorted(imports - _ALLOWED_TUI_AGENT_DEPS)
    assert extra == [], (
        f"{tui_file.name} 仅允许依赖 {sorted(_ALLOWED_TUI_AGENT_DEPS)}，"
        f"发现越界：{extra}。"
        " 根因排查：TUI 适配器引入新 runtime 依赖通常意味着应改走 display event。"
    )


@pytest.mark.parametrize("tui_file", _TUI_FILES, ids=lambda p: p.name)
def test_tui_backend_does_not_import_runtime_internals(tui_file: Path) -> None:
    """硬黑名单：TUI 不得 import runtime core / checkpoint / handler / executor。

    与上一个测试是双向防御：白名单防止"悄悄变宽"，黑名单防止"白名单被错误扩展"。
    """
    imports = _collect_agent_imports(tui_file)
    bad = sorted(imports & _FORBIDDEN_TUI_AGENT_DEPS)
    assert bad == [], (
        f"{tui_file.name} 不允许 import 以下 runtime 内部模块：{bad}。"
        " 任何此类 import 都意味着 TUI 层在绕过 display event 边界，必须改 production。"
    )


# ===================== Group E · 无敏感路径硬编码 =====================

# 禁止在 TUI 源码里直接出现的敏感路径**正则**（用 word boundary 避免误伤
# 像 `.envelope`、`runs/` 子串等的假阳性）。
# 设计要点：
# - `\.env\b` 匹配独立的 `.env` 但**不**匹配 `.envelope` / `.environ`；
# - `agent_log\.jsonl\b` 精确匹配日志文件名；
# - `(?<![A-Za-z_])sessions/` 仅在前面不是字母/下划线时匹配，避免误伤
#   `runtime_sessions/` 之类（项目当前并无此命名，但保险起见）；
# - `(?<![A-Za-z_])runs/` 同理。
_FORBIDDEN_SENSITIVE_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\.env\b", ".env"),
    (r"agent_log\.jsonl\b", "agent_log.jsonl"),
    (r"(?<![A-Za-z_])sessions/", "sessions/"),
    (r"(?<![A-Za-z_])runs/", "runs/"),
)


@pytest.mark.parametrize("tui_file", _TUI_FILES, ids=lambda p: p.name)
def test_tui_backend_source_does_not_reference_sensitive_paths(tui_file: Path) -> None:
    """TUI 适配器源码不得硬编码敏感文件/目录字面量。

    fake/mock 边界说明：本测试只 grep 源文件文本，不实际打开 `.env` /
    `agent_log.jsonl` / 真实 `sessions/` / `runs/`。它防的是"日后某人
    在 TUI 里加'读上次 session 做自动补全'之类便利功能"的隐蔽副作用。

    实现选择：使用带 word-boundary 的正则，避免把 `.envelope` /
    `.environ` 等合法标识符当作 `.env` 文件引用（这是本测试在 v0.6.1
    第一次跑全套时实际抓到的假阳性，根因是子串匹配过宽）。

    若失败：根因不是"测试太严"，而是真的有 TUI 代码开始触碰持久层。
    """
    source = tui_file.read_text(encoding="utf-8")
    hits = [label for pattern, label in _FORBIDDEN_SENSITIVE_PATTERNS if re.search(pattern, source)]
    assert hits == [], (
        f"{tui_file.name} 源码里出现敏感路径字面量 {hits}。"
        " TUI 层不应直接读取 .env / agent_log.jsonl / 真实 sessions/runs；"
        " 若需要这些数据，应通过 runtime event 或 display event 由 runtime 层提供。"
    )
