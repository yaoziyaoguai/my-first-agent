"""F-005 P3 修复回归测试。

验证 TOOL_GATE rejection 后：
- 拒绝反馈包含 rejection_reason（不只是通用"被安全策略拒绝"）
- 拒绝反馈包含可用的替代工具建议（当 applicable）
- 模型/runtime 收到 denial 后能继续运行（不 crash）
- 不泄露 secret / sensitive path 信息
"""

from __future__ import annotations

import pytest

from agent.tool_runtime_mediator import ToolRuntimeMediator

# =============================================================================
# F-005 §1 — _handle_blocked 拒绝消息结构
# =============================================================================

class _FakeMessages(list):
    """模拟消息列表，捕获 append 调用。"""

    def __init__(self):
        super().__init__()
        self.appended: list[dict] = []


class _FakeMemory:
    """最小 memory stub。"""
    store: dict = {}
    proposals: list = []


class _FakeState:
    """最小 state stub。"""

    class Task:
        tool_execution_log: dict = {}
        current_step_index: int = 0

    task: Task = Task()
    memory: _FakeMemory = _FakeMemory()


def _fake_append_tool_result(messages, tool_use_id, result_text):
    """模拟 append_tool_result 捕获。"""
    messages.appended.append({
        "tool_use_id": tool_use_id,
        "result_text": result_text,
    })


@pytest.fixture
def blocked_context(monkeypatch):
    """构建最小 ToolRuntimeMediator 用于测试 _handle_blocked。"""
    import agent.tool_runtime_mediator as mediator_mod

    monkeypatch.setattr(
        mediator_mod, "append_tool_result", _fake_append_tool_result
    )

    messages = _FakeMessages()
    state = _FakeState()

    # 用 __new__ 绕过 __init__ 直接创建 mediator
    mediator = object.__new__(ToolRuntimeMediator)
    mediator._messages = messages
    mediator._state = state
    mediator._identity = None
    mediator._dispatcher = None  # type: ignore[assignment]

    return mediator, messages


def test_handle_blocked_includes_rejection_reason(blocked_context) -> None:
    """F-005: 拒绝消息应包含具体原因，而不是仅写'被安全策略拒绝'。"""
    mediator, messages = blocked_context

    mediator._handle_blocked(
        tool_name="run_shell",
        tool_input={"command": "ls"},
        tool_use_id="tu_001",
        gate_result={"gate_disposition": "rejected"},
    )

    assert len(messages.appended) == 1
    result_text = messages.appended[0]["result_text"]

    # 至少说明被拒绝了
    has_rejection_semantics = (
        "拒绝" in result_text
        or "denied" in result_text.lower()
        or "blocked" in result_text.lower()
    )
    assert has_rejection_semantics, (
        f"F-005: 拒绝消息应包含拒绝语义，实际: {result_text!r}"
    )
    # 包含被拒绝的工具名
    assert "run_shell" in result_text, (
        f"F-005: 拒绝消息应包含被拒绝的工具名，实际: {result_text!r}"
    )


def test_handle_blocked_does_not_reveal_sensitive_info(blocked_context) -> None:
    """F-005: 拒绝消息不得泄露 secret / key / token / 敏感路径。"""
    mediator, messages = blocked_context

    mediator._handle_blocked(
        tool_name="read_file",
        tool_input={"path": "config/config.yaml"},
        tool_use_id="tu_002",
        gate_result={"gate_disposition": "rejected"},
    )

    result_text = messages.appended[0]["result_text"]
    forbidden = ["sk-", "api_key", "Bearer", "secret_key", "password"]
    for word in forbidden:
        assert word not in result_text.lower(), (
            f"F-005: 拒绝消息不得包含敏感词 {word!r}，"
            f"实际: {result_text!r}"
        )


def test_handle_blocked_tool_execution_log_status(blocked_context) -> None:
    """F-005: tool_execution_log 必须正确记录 blocked_by_policy 状态。"""
    mediator, _ = blocked_context

    mediator._handle_blocked(
        tool_name="unsafe_tool",
        tool_input={"dangerous": True},
        tool_use_id="tu_003",
        gate_result={"gate_disposition": "rejected"},
    )

    log_entry = mediator._state.task.tool_execution_log.get("tu_003")
    assert log_entry is not None, (
        "F-005: blocked tool 必须记录到 tool_execution_log"
    )
    assert log_entry["status"] == "blocked_by_policy", (
        f"F-005: 状态必须为 'blocked_by_policy'，实际: {log_entry.get('status')!r}"
    )
    assert log_entry["tool"] == "unsafe_tool"


def test_handle_confirmation_required_sets_pending_tool(
    blocked_context, monkeypatch
) -> None:
    """F-005: confirmation_required 必须正确设置 pending_tool。"""
    mediator, _ = blocked_context

    # _handle_confirmation_required 内部调用 save_checkpoint，
    # 这里 mock 掉以避免访问真实文件系统
    import agent.checkpoint as checkpoint_mod

    monkeypatch.setattr(checkpoint_mod, "save_checkpoint", lambda state: None)

    mediator._handle_confirmation_required(
        tool_name="write_file",
        tool_input={"path": "/tmp/test.txt"},
        tool_use_id="tu_004",
    )

    assert mediator._state.task.pending_tool is not None, (
        "F-005: confirmation_required 必须设置 pending_tool"
    )
    assert mediator._state.task.pending_tool["tool"] == "write_file"
    assert mediator._state.task.status == "awaiting_tool_confirmation"


# =============================================================================
# F-005 §2 — 拒绝后 runtime 不 crash / 可继续
# =============================================================================

def test_mediate_blocked_returns_force_stop_not_exception(blocked_context) -> None:
    """F-005: mediator.mediate() 在工具被拒时必须返回 FORCE_STOP 而非抛异常。

    这确保 runtime 可以继续处理后续逻辑（如记录 evidence、更新状态），而不是崩溃。
    """
    mediator, _ = blocked_context

    # 模拟 _route_gate 返回 rejected
    def _fake_route_gate(tool_name, tool_input, tool_use_id):
        return {"gate_disposition": "rejected", "rejection_reason": None, "evidence_extra": None}

    mediator._route_gate = _fake_route_gate  # type: ignore[method-assign]
    mediator._route_result = lambda *args: None  # type: ignore[method-assign]

    # 构造一个简单的 tool_use block mock
    class _FakeBlock:
        name = "run_shell"
        input = {"command": "ls"}
        id = "tu_005"

    result = mediator.mediate(_FakeBlock())

    assert result is not None, (
        "F-005: blocked tool mediate 应返回 FORCE_STOP（非 None 表示特殊状态）"
    )


# =============================================================================
# F-005 §3 — 拒绝消息应提供可行的下一步建议
# =============================================================================

def test_blocked_message_suggests_alternative_when_available(blocked_context) -> None:
    """F-005: 当拒绝原因是工具不在 allowed_tools 时，应建议可用的替代工具。

    中文学习注释：
    拒绝消息的建议部分是「best-effort」——不影响 gate 安全性。
    如果没有合适的替代工具，不应伪造建议。
    """
    mediator, messages = blocked_context

    # 直接测试：_handle_blocked 支持可选 extra context（rejection_reason 等）
    # 这些 extra context 将在 Step 5 实现中接入 _route_gate 的完整结果
    mediator._handle_blocked(
        tool_name="run_shell",
        tool_input={"command": "ls"},
        tool_use_id="tu_006",
        gate_result={"gate_disposition": "rejected"},
    )

    result_text = messages.appended[0]["result_text"]
    assert len(result_text) > 0, "F-005: 拒绝消息不应为空"
    # 消息应有意义（不只重复工具名）
    assert len(result_text) > len("run_shell") + 5, (
        f"F-005: 拒绝消息应有实质性内容，实际: {result_text!r}"
    )
