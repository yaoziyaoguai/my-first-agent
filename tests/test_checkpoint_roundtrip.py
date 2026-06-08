"""Checkpoint 保存/恢复的 roundtrip 测试。

覆盖：
- save → load 之后 state 字段应当完整恢复
- 旧 checkpoint（缺字段）能被恢复，不会 crash
- conversation.messages 里大 tool_result 被正确截断
"""

from __future__ import annotations

import json

import pytest


@pytest.fixture
def tmp_checkpoint_path(tmp_path, monkeypatch):
    """把 checkpoint 写到临时目录，不污染真实 memory/checkpoint.json。"""
    from agent import checkpoint
    path = tmp_path / "checkpoint.json"
    monkeypatch.setattr(checkpoint, "CHECKPOINT_PATH", path)
    return path


def test_save_load_roundtrip_preserves_task_fields(tmp_checkpoint_path):
    """改完 task 各字段后 save → load，所有字段应当完整回来。"""
    from agent.checkpoint import load_checkpoint_to_state, save_checkpoint
    from agent.state import create_agent_state

    src = create_agent_state(system_prompt="test")
    src.task.user_goal = "原始目标"
    src.task.current_plan = {"goal": "some", "steps": [{"title": "step1"}]}
    src.task.current_step_index = 2
    src.task.status = "running"
    src.task.retry_count = 3
    src.task.consecutive_max_tokens = 1
    src.task.tool_call_count = 7
    src.task.pending_tool = {"tool_use_id": "T1", "tool": "x", "input": {}}
    src.task.tool_execution_log = {"T0": {"tool": "a", "input": {}, "result": "r"}}
    src.memory.working_summary = "一段摘要"
    src.memory.session_id = "abc123"
    src.conversation.messages = [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "收到"},
    ]

    save_checkpoint(src)

    # 造个空的 state，load 进来
    dst = create_agent_state(system_prompt="different")
    ok = load_checkpoint_to_state(dst)

    assert ok
    # task 字段
    assert dst.task.user_goal == "原始目标"
    assert dst.task.current_plan == {"goal": "some", "steps": [{"title": "step1"}]}
    assert dst.task.current_step_index == 2
    assert dst.task.status == "running"
    assert dst.task.retry_count == 3
    assert dst.task.consecutive_max_tokens == 1
    assert dst.task.tool_call_count == 7
    assert dst.task.pending_tool == {"tool_use_id": "T1", "tool": "x", "input": {}}
    assert "T0" in dst.task.tool_execution_log
    # memory 字段
    assert dst.memory.working_summary == "一段摘要"
    assert dst.memory.session_id == "abc123"
    # conversation
    assert len(dst.conversation.messages) == 2


def test_load_old_checkpoint_without_new_fields_does_not_crash(tmp_checkpoint_path):
    """旧 checkpoint 缺少后加的字段（比如 tool_call_count）时，
    load 应当不崩，新字段取 dataclass 默认值。"""
    from agent.checkpoint import load_checkpoint_to_state
    from agent.state import create_agent_state

    # 手工造一份"旧版" checkpoint：只有少数字段
    old_checkpoint = {
        "meta": {"session_id": "old"},
        "task": {
            "user_goal": "旧任务",
            "current_plan": None,
            "status": "idle",
            # tool_call_count / pending_tool / tool_execution_log 都缺
        },
        "memory": {"working_summary": None, "session_id": "old"},
        "conversation": {"messages": []},
    }
    tmp_checkpoint_path.write_text(
        json.dumps(old_checkpoint, ensure_ascii=False), encoding="utf-8"
    )

    dst = create_agent_state(system_prompt="test")
    ok = load_checkpoint_to_state(dst)

    assert ok
    # 旧字段正常恢复
    assert dst.task.user_goal == "旧任务"
    # 新字段保持 dataclass 默认值
    assert dst.task.tool_call_count == 0
    assert dst.task.pending_tool is None
    assert dst.task.tool_execution_log == {}


def test_checkpoint_summarizes_large_tool_results(tmp_checkpoint_path):
    """大 tool_result 内容应被摘要化，不保留原始 content。

    v0.5 统一持久化策略前，checkpoint 使用独立的 _truncate_messages_for_checkpoint
    做截断（保留前 N 字符的 raw string）。迁移到 evidence_persistence 后，超过
    2KB 的 tool_result 被替换为 summary dict（result_size/result_hash/preview_redacted），
    原始 content 不再写入 checkpoint。
    """
    from agent.checkpoint import save_checkpoint
    from agent.evidence_persistence import MAX_TOOL_RESULT_BYTES
    from agent.state import create_agent_state

    huge_result = "x" * (MAX_TOOL_RESULT_BYTES * 3)
    src = create_agent_state(system_prompt="test")
    src.conversation.messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "T1",
                    "content": huge_result,
                }
            ],
        }
    ]
    save_checkpoint(src)

    on_disk = json.loads(tmp_checkpoint_path.read_text(encoding="utf-8"))
    block = on_disk["conversation"]["messages"][0]["content"][0]

    # 统一策略后：大 tool_result → summary dict，没有 raw content
    assert "content" not in block, (
        "大 tool_result 不应保留 raw content，应替换为 summary dict"
    )
    summary = block.get("summary", {})
    assert summary.get("truncated") is True
    assert summary.get("result_size") == len(huge_result.encode("utf-8"))
    assert "result_hash" in summary
    assert len(summary.get("preview_redacted", "")) <= 200


def test_checkpoint_truncation_config_rejects_invalid_values():
    """非法 checkpoint budget 必须 fail closed，且不能污染当前配置。"""
    from agent.checkpoint import (
        get_checkpoint_truncation_config,
        set_checkpoint_truncation_config,
    )

    before = get_checkpoint_truncation_config()

    with pytest.raises(ValueError, match="max_result_length"):
        set_checkpoint_truncation_config(max_result_length=-1)
    with pytest.raises(ValueError, match="max_tool_results"):
        set_checkpoint_truncation_config(max_tool_results=-1)

    assert get_checkpoint_truncation_config() == before


def test_save_checkpoint_does_not_print_loaded(tmp_checkpoint_path, capsys, monkeypatch):
    """保存 checkpoint 时为了继承旧 meta 读取旧文件，不应打印 loaded 误导为恢复。"""
    from agent.checkpoint import save_checkpoint
    from agent.state import create_agent_state

    monkeypatch.setenv("MY_FIRST_AGENT_DEBUG", "1")
    src = create_agent_state(system_prompt="test")
    src.task.status = "running"

    save_checkpoint(src)
    first = capsys.readouterr().out
    assert "[CHECKPOINT] loaded" not in first
    assert "[CHECKPOINT] saved" in first

    # 第二次保存时磁盘已有 checkpoint；仍然只能打印 saved，不能打印 loaded。
    save_checkpoint(src)
    second = capsys.readouterr().out
    assert "[CHECKPOINT] loaded" not in second
    assert "[CHECKPOINT] saved" in second


def test_save_checkpoint_without_source_keeps_existing_log_shape(
    tmp_checkpoint_path,
    capsys,
    monkeypatch,
):
    """打开 debug 时，不传 source 仍保持旧短日志形态。"""
    from agent.checkpoint import save_checkpoint
    from agent.state import create_agent_state

    monkeypatch.setenv("MY_FIRST_AGENT_DEBUG", "1")
    src = create_agent_state(system_prompt="test")
    src.task.status = "running"

    save_checkpoint(src)

    out = capsys.readouterr().out
    assert "[CHECKPOINT] saved (status=running)" in out
    assert "source=" not in out


def test_save_checkpoint_with_source_logs_source_but_does_not_persist_it(
    tmp_checkpoint_path,
    capsys,
    monkeypatch,
):
    """source 是观测字段；debug stdout 可见，但不进入 checkpoint JSON。"""
    from agent.checkpoint import save_checkpoint
    from agent.state import create_agent_state

    monkeypatch.setenv("MY_FIRST_AGENT_DEBUG", "1")
    src = create_agent_state(system_prompt="test")
    src.task.status = "running"

    save_checkpoint(src, source="x.y")

    out = capsys.readouterr().out
    assert "[CHECKPOINT] saved (status=running, source=x.y)" in out

    on_disk = json.loads(tmp_checkpoint_path.read_text(encoding="utf-8"))
    assert "source" not in on_disk
    assert "source" not in on_disk["meta"]
    assert "source" not in on_disk["task"]


def test_checkpoint_terminal_debug_is_silent_by_default(tmp_checkpoint_path, capsys):
    """默认不把 [CHECKPOINT] 打到 terminal，避免污染 TUI conversation view。"""
    from agent.checkpoint import load_checkpoint, save_checkpoint
    from agent.state import create_agent_state

    src = create_agent_state(system_prompt="test")
    src.task.status = "running"

    save_checkpoint(src, source="tests.silent_default")
    assert load_checkpoint() is not None

    assert "[CHECKPOINT]" not in capsys.readouterr().out


def test_load_returns_false_when_no_file(tmp_checkpoint_path):
    """checkpoint 文件不存在时 load 应当返回 False，而不是崩。"""
    from agent.checkpoint import load_checkpoint_to_state
    from agent.state import create_agent_state

    # tmp_checkpoint_path 对应的文件确实不存在
    assert not tmp_checkpoint_path.exists()

    dst = create_agent_state(system_prompt="test")
    ok = load_checkpoint_to_state(dst)

    assert ok is False


# ===== Loop 6: schema version 测试 =====


def test_schema_version_written_to_checkpoint(tmp_checkpoint_path):
    """保存的 checkpoint meta 中包含 schema_version = "checkpoint.v1"。

    Loop 6 之后所有新保存的 checkpoint 自动携带版本号。
    """
    from agent.checkpoint import SCHEMA_VERSION, load_checkpoint, save_checkpoint
    from agent.state import create_agent_state

    state = create_agent_state(system_prompt="test")
    save_checkpoint(state, path=tmp_checkpoint_path)

    data = load_checkpoint(path=tmp_checkpoint_path)
    assert data is not None
    assert data["meta"]["schema_version"] == SCHEMA_VERSION
    assert SCHEMA_VERSION == "checkpoint.v1"


def test_v0_checkpoint_without_version_loads_via_migration(tmp_checkpoint_path):
    """v0 checkpoint（无 schema_version）可通过迁移安全加载。

    这是向后兼容保证：Loop 6 之前保存的 checkpoint 不能被拒绝。
    """
    from agent.checkpoint import load_checkpoint_to_state
    from agent.state import create_agent_state

    # 手工构造一个 v0 checkpoint（无 schema_version）
    v0_checkpoint = {
        "meta": {
            "session_id": "test-session",
            "created_at": "2026-01-01T00:00:00",
            "interrupted_at": "2026-01-01T00:00:00",
        },
        "task": {"status": "awaiting_user_input", "loop_iterations": 3},
        "memory": {"working_summary": "test"},
        "conversation": {"messages": []},
    }
    import json
    tmp_checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_checkpoint_path.write_text(json.dumps(v0_checkpoint), encoding="utf-8")

    state = create_agent_state(system_prompt="test")
    ok = load_checkpoint_to_state(state, path=tmp_checkpoint_path)
    assert ok is True
    # 迁移后数据正确恢复
    assert state.task.status == "awaiting_user_input"
    assert state.task.loop_iterations == 3


def test_unknown_future_version_rejected(tmp_checkpoint_path):
    """未知的 future schema version 拒绝加载，避免静默数据损坏。

    如果一个 checkpoint 的 schema_version 不在 _KNOWN_VERSIONS 且
    不在 _MIGRATION_REGISTRY 中，加载应返回 False。
    """
    from agent.checkpoint import load_checkpoint_to_state
    from agent.state import create_agent_state

    future_checkpoint = {
        "meta": {
            "schema_version": "checkpoint.v99-unknown",
            "session_id": "test-session",
            "created_at": "2026-01-01T00:00:00",
            "interrupted_at": "2026-01-01T00:00:00",
        },
        "task": {"status": "running"},
        "memory": {},
        "conversation": {"messages": []},
    }
    import json
    tmp_checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_checkpoint_path.write_text(json.dumps(future_checkpoint), encoding="utf-8")

    state = create_agent_state(system_prompt="test")
    ok = load_checkpoint_to_state(state, path=tmp_checkpoint_path)
    assert ok is False


def test_v0_roundtrip_preserves_all_data(tmp_checkpoint_path):
    """v0 checkpoint 加载后保存为 v1，数据完整不丢失。

    验证 v0 → v1 迁移后重新保存的 checkpoint 包含 schema_version
    且原始数据（task/memory/conversation）完全保留。
    """
    from agent.checkpoint import (
        SCHEMA_VERSION,
        load_checkpoint,
        load_checkpoint_to_state,
        save_checkpoint,
    )
    from agent.state import create_agent_state

    v0_checkpoint = {
        "meta": {
            "session_id": "test-session",
            "created_at": "2026-01-01T00:00:00",
            "interrupted_at": "2026-01-01T00:00:00",
        },
        "task": {
            "status": "awaiting_tool_confirmation",
            "loop_iterations": 5,
            "tool_call_count": 2,
            "pending_tool": {"tool": "test_tool", "args": {"x": 1}},
        },
        "memory": {"working_summary": "summary text", "long_term_notes": ["note 1"]},
        "conversation": {"messages": [{"role": "user", "content": "hello"}]},
    }
    import json
    tmp_checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_checkpoint_path.write_text(json.dumps(v0_checkpoint), encoding="utf-8")

    # 第一次加载 v0
    state = create_agent_state(system_prompt="test")
    ok = load_checkpoint_to_state(state, path=tmp_checkpoint_path)
    assert ok is True
    assert state.task.tool_call_count == 2
    assert state.memory.long_term_notes == []

    # 重新保存（应变为 v1）
    save_checkpoint(state, path=tmp_checkpoint_path)
    data = load_checkpoint(path=tmp_checkpoint_path)
    assert data is not None
    assert data["meta"]["schema_version"] == SCHEMA_VERSION
    # task / scratchpad 数据保留；长期 memory 正文不再由 checkpoint 恢复。
    assert data["task"]["status"] == "awaiting_tool_confirmation"
    assert data["task"]["loop_iterations"] == 5
    assert data["memory"]["working_summary"] == "summary text"
    assert data["memory"]["long_term_notes"] == []
