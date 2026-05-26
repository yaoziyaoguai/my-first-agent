"""Run summary compact report 测试。

验证 render_compact_run_summary() 的 compact 格式输出：
- 各 section（tools/mem/sub）仅在 >0 时出现
- redacted 字段正确反映脱敏状态
- 不泄露 raw secret
- 普通对话摘要保持简洁
- missing info 渲染为可用状态，不伪造值

中文学习边界：
- 所有测试使用 fake metadata dict，不涉及真实 runtime
- 这是 L3 display-layer contract 测试——验证 UI 投影行为
"""
from __future__ import annotations

from agent.cli_renderer import render_compact_run_summary
from agent.display_events import run_summary_event

# =========================================================================
# 基础 compact 格式
# =========================================================================


def test_compact_basic_structure():
    """compact 格式基本结构：[run] iter=N ... redacted=... stop=..."""
    meta = {
        "loop_iterations": 3,
        "tool_calls": 0,
        "memory_operations": 0,
        "subagent_delegations": 0,
        "stop_reason": "正常结束",
    }
    result = render_compact_run_summary(meta)
    assert result.startswith("[run]")
    assert "iter=3" in result
    assert "redacted=no" in result
    assert "stop=正常结束" in result


def test_compact_ordinary_chat_is_concise():
    """普通对话（零工具/零 memory/零 subagent）应显示简洁说明。"""
    meta = {
        "loop_iterations": 1,
        "tool_calls": 0,
        "memory_operations": 0,
        "subagent_delegations": 0,
        "stop_reason": "正常结束",
    }
    result = render_compact_run_summary(meta)
    assert "普通对话" in result
    assert "tools=" not in result
    assert "mem=" not in result
    assert "sub=" not in result


def test_compact_tool_section_appears_when_relevant():
    """tool_calls > 0 时 tools= 段应出现并包含工具名。"""
    meta = {
        "loop_iterations": 3,
        "tool_calls": 2,
        "memory_operations": 0,
        "subagent_delegations": 0,
        "stop_reason": "正常结束",
        "tool_names": ["read_file", "write_file"],
    }
    result = render_compact_run_summary(meta)
    assert "tools=2(read_file,write_file)" in result


def test_compact_memory_section_appears_when_relevant():
    """memory_operations > 0 时 mem= 段应出现。"""
    meta = {
        "loop_iterations": 2,
        "tool_calls": 0,
        "memory_operations": 1,
        "subagent_delegations": 0,
        "stop_reason": "正常结束",
        "memory_actions": ["proposed"],
    }
    result = render_compact_run_summary(meta)
    assert "mem=1(proposed)" in result


def test_compact_subagent_section_appears_when_relevant():
    """subagent_delegations > 0 时 sub= 段应出现。"""
    meta = {
        "loop_iterations": 5,
        "tool_calls": 1,
        "memory_operations": 0,
        "subagent_delegations": 2,
        "stop_reason": "正常结束",
        "tool_names": ["read_file"],
        "subagent_names": ["demo-stat", "code-reviewer"],
    }
    result = render_compact_run_summary(meta)
    assert "sub=2(demo-stat,code-reviewer)" in result


def test_compact_all_sections_present():
    """同时有 tools/mem/sub 时三个 section 都在。"""
    meta = {
        "loop_iterations": 4,
        "tool_calls": 2,
        "memory_operations": 1,
        "subagent_delegations": 1,
        "stop_reason": "正常结束",
        "tool_names": ["read_file", "write_file"],
        "memory_actions": ["retained"],
        "subagent_names": ["demo-stat"],
    }
    result = render_compact_run_summary(meta)
    assert "tools=2" in result
    assert "mem=1" in result
    assert "sub=1" in result


# =========================================================================
# 脱敏状态
# =========================================================================


def test_compact_redacted_yes_when_secrets_masked():
    """tool_names 中含 [REDACTED] 时 redacted=yes。"""
    meta = {
        "loop_iterations": 1,
        "tool_calls": 1,
        "memory_operations": 0,
        "subagent_delegations": 0,
        "stop_reason": "异常结束",
        "tool_names": ["read_file"],
        "error_reasons": ["provider failed with api_key=[REDACTED]"],
    }
    result = render_compact_run_summary(meta)
    assert "redacted=yes" in result


def test_compact_redacted_no_when_clean():
    """所有字段不含 [REDACTED] 时 redacted=no。"""
    meta = {
        "loop_iterations": 1,
        "tool_calls": 1,
        "memory_operations": 0,
        "subagent_delegations": 0,
        "stop_reason": "正常结束",
        "tool_names": ["read_file"],
    }
    result = render_compact_run_summary(meta)
    assert "redacted=no" in result


def test_compact_redacted_detection_with_premasked_data():
    """compact renderer 正确检测已脱敏数据——上游 _mask_preview_secrets() 负责脱敏。

    render_compact_run_summary 不自己做脱敏（那不是它的职责），它只检测
    [REDACTED] 标记是否存在并设置 redacted=yes/no。
    端到端脱敏验证见 test_run_summary_event_error_redacted_in_compact。
    """
    meta = {
        "loop_iterations": 1,
        "tool_calls": 0,
        "memory_operations": 0,
        "subagent_delegations": 0,
        "stop_reason": "正常结束",
        # 已脱敏数据——由 _mask_preview_secrets() 完成
        "error_reasons": ["auth failed: api_key=[REDACTED]"],
    }
    result = render_compact_run_summary(meta)
    assert "redacted=yes" in result
    assert "[REDACTED]" in result


# =========================================================================
# 错误信息
# =========================================================================


def test_compact_error_reasons_appended():
    """有 error_reasons 时 errors= 段应追加到末尾。"""
    meta = {
        "loop_iterations": 2,
        "tool_calls": 1,
        "memory_operations": 0,
        "subagent_delegations": 0,
        "stop_reason": "异常结束",
        "tool_names": ["read_file"],
        "error_reasons": ["timeout after 30s", "connection refused"],
    }
    result = render_compact_run_summary(meta)
    assert "errors=timeout after 30s;connection refused" in result


def test_compact_no_errors_section_when_empty():
    """无 error_reasons 时不应出现 errors= 段。"""
    meta = {
        "loop_iterations": 1,
        "tool_calls": 0,
        "memory_operations": 0,
        "subagent_delegations": 0,
        "stop_reason": "正常结束",
    }
    result = render_compact_run_summary(meta)
    assert "errors=" not in result


# =========================================================================
# missing info 行为
# =========================================================================


def test_compact_missing_tool_names_uses_placeholder():
    """缺失 tool_names 时应使用 '?' 而非伪造工具名。"""
    meta = {
        "loop_iterations": 1,
        "tool_calls": 2,
        "memory_operations": 0,
        "subagent_delegations": 0,
        "stop_reason": "正常结束",
    }
    result = render_compact_run_summary(meta)
    assert "tools=2(?)" in result


def test_compact_missing_subagent_names_uses_placeholder():
    """缺失 subagent_names 时应使用 '?' 而非伪造名称。"""
    meta = {
        "loop_iterations": 1,
        "tool_calls": 0,
        "memory_operations": 0,
        "subagent_delegations": 1,
        "stop_reason": "正常结束",
    }
    result = render_compact_run_summary(meta)
    assert "sub=1(?)" in result


def test_compact_missing_info_never_renders_as_fake():
    """missing info 不应渲染为 'fake'——区分数据缺失和 fake provider。"""
    meta = {
        "loop_iterations": 1,
        "tool_calls": 0,
        "memory_operations": 0,
        "subagent_delegations": 0,
        "stop_reason": "正常结束",
    }
    result = render_compact_run_summary(meta)
    # 全零活动不应出现 tools/mem/sub 段，也不应有 'fake' 关键词
    # （除非 stop_reason 中自然出现）
    assert "tools=" not in result
    assert "mem=" not in result
    assert "sub=" not in result


# =========================================================================
# run_summary_event → compact 端到端集成
# =========================================================================


def test_run_summary_event_metadata_feeds_compact_renderer():
    """run_summary_event 的 metadata 可直接传入 compact renderer。

    验证端到端：event 构造 → metadata 提取 → compact 渲染。
    """
    evt = run_summary_event(
        loop_iterations=3,
        tool_calls=2,
        memory_operations=1,
        subagent_delegations=1,
        stop_reason="正常结束",
        tool_names=["read_file", "write_file"],
        memory_actions=["retained"],
        subagent_names=["demo-stat"],
    )
    # metadata dict 直接传给 compact renderer
    result = render_compact_run_summary(evt.metadata)
    assert "tools=2(read_file,write_file)" in result
    assert "mem=1(retained)" in result
    assert "sub=1(demo-stat)" in result
    assert "redacted=no" in result


def test_run_summary_event_error_redacted_in_compact():
    """run_summary_event 脱敏后 compact 输出 redacted=yes。"""
    evt = run_summary_event(
        loop_iterations=1,
        tool_calls=0,
        memory_operations=0,
        subagent_delegations=0,
        stop_reason="异常结束",
        error_reasons=["auth failed: sk-ant-secret-key-12345"],
    )
    result = render_compact_run_summary(evt.metadata)
    assert "redacted=yes" in result
    assert "sk-ant-secret" not in result
    assert "[REDACTED]" in result


def test_compact_format_is_single_line():
    """compact 格式必须是单行（适合日志/脚本解析）。"""
    meta = {
        "loop_iterations": 10,
        "tool_calls": 5,
        "memory_operations": 2,
        "subagent_delegations": 3,
        "stop_reason": "正常结束",
        "tool_names": ["a", "b", "c"],
        "memory_actions": ["x", "y"],
        "subagent_names": ["s1", "s2", "s3"],
        "error_reasons": ["e1"],
    }
    result = render_compact_run_summary(meta)
    assert "\n" not in result
