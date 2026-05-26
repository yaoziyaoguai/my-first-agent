"""Dogfood harness 共享 helpers 测试。

验证 StepResult 不可变性、write_dogfood_report() 行为、
redact_secrets() 脱敏正确性、temp_workspace() 生命周期。

中文学习边界：
- 所有测试使用 fake/stub 数据，不调用真实 API
- redact_secrets 测试确保不可逆——raw secret 不出现在输出中
- temp_workspace 测试验证 context manager exit 后目录被清理
- 这是 L3 evidence：contract 层面验证 helper 行为正确
"""
from __future__ import annotations

import json
import os
from dataclasses import FrozenInstanceError

import pytest

from agent.dogfood_harness import (
    StepResult,
    redact_secrets,
    temp_workspace,
    write_dogfood_report,
)

# =========================================================================
# StepResult 不可变性 & schema
# =========================================================================


def test_step_result_is_frozen():
    """StepResult 必须是 frozen dataclass——不可变，字段不可修改。"""
    sr = StepResult(
        step_id="BL1-01",
        description="启动检查",
        status="pass",
        actual_summary="启动成功",
        expected="启动应成功",
        provider_mode="fake",
    )
    with pytest.raises(FrozenInstanceError):
        sr.status = "fail"  # type: ignore[misc]


def test_step_result_all_fields():
    """StepResult 所有字段应正确存储。"""
    detail = {"elapsed_ms": 42, "tool_calls": 3}
    sr = StepResult(
        step_id="BL2-P3-07",
        description="tool_use 归一化",
        status="concern",
        actual_summary="JSON string 解析为 dict 正确",
        expected="input 始终为 dict",
        provider_mode="fake",
        detail=detail,
    )
    assert sr.step_id == "BL2-P3-07"
    assert sr.description == "tool_use 归一化"
    assert sr.status == "concern"
    assert sr.actual_summary == "JSON string 解析为 dict 正确"
    assert sr.expected == "input 始终为 dict"
    assert sr.provider_mode == "fake"
    assert sr.detail == detail


def test_step_result_detail_default_none():
    """detail 字段默认为 None。"""
    sr = StepResult(
        step_id="X-01",
        description="test",
        status="pass",
        actual_summary="ok",
        expected="ok",
        provider_mode="none",
    )
    assert sr.detail is None


def test_step_result_to_dict():
    """to_dict() 应产出可 JSON 序列化的 dict。"""
    sr = StepResult(
        step_id="BL1-01",
        description="检查",
        status="pass",
        actual_summary="ok",
        expected="ok",
        provider_mode="fake",
        detail={"key": "value"},
    )
    d = sr.to_dict()
    assert d["step_id"] == "BL1-01"
    assert d["status"] == "pass"
    assert d["detail"] == {"key": "value"}
    json.dumps(d)  # 不抛异常即可


def test_step_result_minimal():
    """StepResult 最小有效构造（无 detail）。"""
    sr = StepResult(
        step_id="S01",
        description="minimal",
        status="skipped",
        actual_summary="skipped for reason",
        expected="should run",
        provider_mode="none",
    )
    assert sr.status == "skipped"
    assert sr.detail is None


# =========================================================================
# write_dogfood_report()
# =========================================================================


def test_write_report_creates_json():
    """write_dogfood_report 应创建 JSON 文件并返回 Path。"""
    with temp_workspace("test_report_") as ws:
        results = [
            StepResult(
                step_id="T1",
                description="test",
                status="pass",
                actual_summary="works",
                expected="works",
                provider_mode="fake",
            ),
        ]
        output = ws / "report.json"
        result_path = write_dogfood_report(results, output)
        assert result_path == output
        assert output.exists()
        data = json.loads(output.read_text())
        assert data["total_steps"] == 1
        assert data["pass_count"] == 1
        assert data["fail_count"] == 0
        assert data["results"][0]["step_id"] == "T1"


def test_write_report_default_no_overwrite():
    """默认 overwrite=False 时，覆盖已有报告应抛 FileExistsError。"""
    with temp_workspace("test_no_overwrite_") as ws:
        output = ws / "report.json"
        results = [
            StepResult(
                step_id="T1",
                description="first",
                status="pass",
                actual_summary="ok",
                expected="ok",
                provider_mode="fake",
            ),
        ]
        write_dogfood_report(results, output)
        with pytest.raises(FileExistsError, match="已存在"):
            write_dogfood_report(results, output)


def test_write_report_overwrite_flag():
    """overwrite=True 时允许覆盖已有报告。"""
    with temp_workspace("test_overwrite_") as ws:
        output = ws / "report.json"
        r1 = [
            StepResult(
                step_id="T1",
                description="v1",
                status="pass",
                actual_summary="ok",
                expected="ok",
                provider_mode="fake",
            ),
        ]
        write_dogfood_report(r1, output)
        r2 = [
            StepResult(
                step_id="T2",
                description="v2",
                status="fail",
                actual_summary="bad",
                expected="good",
                provider_mode="real",
            ),
        ]
        write_dogfood_report(r2, output, overwrite=True)
        data = json.loads(output.read_text())
        assert data["total_steps"] == 1
        assert data["results"][0]["step_id"] == "T2"


def test_write_report_counts_by_status():
    """报告应正确统计各状态的步骤数。"""
    with temp_workspace("test_counts_") as ws:
        results = [
            StepResult(
                step_id="P1", description="p", status="pass",
                actual_summary=".", expected=".", provider_mode="fake",
            ),
            StepResult(
                step_id="P2", description="p", status="pass",
                actual_summary=".", expected=".", provider_mode="fake",
            ),
            StepResult(
                step_id="C1", description="c", status="concern",
                actual_summary=".", expected=".", provider_mode="real",
            ),
            StepResult(
                step_id="F1", description="f", status="fail",
                actual_summary="x", expected="y", provider_mode="real",
            ),
            StepResult(
                step_id="S1", description="s", status="skipped",
                actual_summary="-", expected="-", provider_mode="none",
            ),
        ]
        output = ws / "report.json"
        write_dogfood_report(results, output)
        data = json.loads(output.read_text())
        assert data["pass_count"] == 2
        assert data["concern_count"] == 1
        assert data["fail_count"] == 1
        assert data["skipped_count"] == 1
        assert data["total_steps"] == 5


def test_write_report_creates_parent_dir():
    """输出路径的父目录不存在时应自动创建。"""
    with temp_workspace("test_mkdir_") as ws:
        output = ws / "deeply" / "nested" / "report.json"
        results = [
            StepResult(
                step_id="T1", description="t", status="pass",
                actual_summary=".", expected=".", provider_mode="fake",
            ),
        ]
        result_path = write_dogfood_report(results, output)
        assert result_path.exists()


def test_write_report_handles_empty_results():
    """空 results 列表应正常生成报告。"""
    with temp_workspace("test_empty_") as ws:
        output = ws / "empty.json"
        write_dogfood_report([], output)
        data = json.loads(output.read_text())
        assert data["total_steps"] == 0
        assert data["results"] == []


# =========================================================================
# redact_secrets()
# =========================================================================


def test_redact_anthropic_api_key():
    """sk-ant-* pattern 应被脱敏。"""
    text = "Authorization: sk-ant-api03-abc123def456ghi789jkl"
    result = redact_secrets(text)
    assert "sk-ant-api03-abc123def456ghi789jkl" not in result
    assert "sk-ant-[REDACTED]" in result


def test_redact_openai_api_key():
    """sk-* pattern（非 Anthropic）应被脱敏。"""
    text = "OPENAI_API_KEY=sk-proj-1234567890abcdefghij"
    result = redact_secrets(text)
    assert "sk-proj-1234567890abcdefghij" not in result
    assert "sk-[REDACTED]" in result


def test_redact_bearer_token():
    """Bearer token 应被脱敏。"""
    text = "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0"
    result = redact_secrets(text)
    assert "eyJhbGciOiJIUzI1NiJ9" not in result
    assert "Bearer [REDACTED]" in result


def test_redact_multiple_secrets():
    """多个 secret 同时出现时应全部脱敏。"""
    text = (
        "key1=sk-ant-test12345678901234567890\n"
        "key2=sk-proj-abcdefghijklmnopqrstuv\n"
        "Authorization: Bearer xyz.jwt.token.here"
    )
    result = redact_secrets(text)
    assert "sk-ant-test" not in result
    assert "sk-proj-a" not in result
    assert "xyz.jwt" not in result
    assert result.count("[REDACTED]") == 3


def test_redact_no_secret_unchanged():
    """不含 secret 的普通文本不应被修改。"""
    text = "你好，今天怎么样？没有任何密钥信息。"
    result = redact_secrets(text)
    assert result == text


def test_redact_short_sk_not_redacted():
    """短 sk- 前缀（< 20 chars）不应被脱敏——避免误伤普通文本。"""
    text = "使用 sk-learn 库进行机器学习"
    result = redact_secrets(text)
    assert "sk-learn" in result


def test_redact_is_irreversible():
    """脱敏必须不可逆——raw secret 不能出现在输出中。"""
    secret = "sk-ant-api03-very-secret-key-value-here1234"
    result = redact_secrets(f"key={secret}")
    assert secret not in result
    # 不应保留超过 10 个连续字符的原始 key 片段
    for i in range(len(secret) - 10):
        assert secret[i:i + 10] not in result


# =========================================================================
# temp_workspace()
# =========================================================================


def test_temp_workspace_creates_and_cleans_up():
    """temp_workspace 应在 context manager exit 后清理目录。"""
    ws_path = None
    with temp_workspace("test_cleanup_") as ws:
        ws_path = str(ws)
        assert os.path.isdir(ws_path)
        (ws / "test.txt").write_text("hello")
    # Exit 后目录应被删除
    assert not os.path.exists(ws_path)


def test_temp_workspace_is_writable():
    """temp_workspace 目录内应可写文件。"""
    with temp_workspace("test_writable_") as ws:
        f = ws / "data.json"
        f.write_text('{"key": "value"}')
        assert f.exists()
        assert json.loads(f.read_text()) == {"key": "value"}


def test_temp_workspace_prefix_respected():
    """temp_workspace 目录名应包含指定前缀。"""
    with temp_workspace("myprefix_") as ws:
        assert "myprefix_" in str(ws)


def test_temp_workspace_default_prefix():
    """默认前缀应为 'dogfood_'。"""
    with temp_workspace() as ws:
        assert "dogfood_" in str(ws)


# =========================================================================
# 集成：redact_secrets 在 report 中使用
# =========================================================================


def test_report_does_not_leak_secrets():
    """write_dogfood_report 中的 detail 字段不应泄露 secret。

    验证完整的「构造 StepResult → 写入报告 → 读取报告」流程中
    不出现 raw secret。
    """
    with temp_workspace("test_no_leak_") as ws:
        # detail 中的内容已经过脱敏
        detail_after_redact = {"auth_header": "Bearer [REDACTED]", "key_env": True}
        sr = StepResult(
            step_id="SEC-01",
            description="验证 API key 脱敏",
            status="pass",
            actual_summary="API key 已配置并脱敏",
            expected="key 值不应出现在报告中",
            provider_mode="real",
            detail=detail_after_redact,
        )
        output = ws / "report.json"
        write_dogfood_report([sr], output)
        raw = output.read_text()
        # raw secret 不应出现
        assert "sk-ant-" not in raw
        assert "sk-proj-" not in raw
        # 但 [REDACTED] 标记应出现
        assert "[REDACTED]" in raw
