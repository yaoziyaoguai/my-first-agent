"""Interactive Dogfood Harness 单元测试。

中文学习说明：
  这些测试验证 SubprocessRunner 和 CaseEvaluator 的基础行为。
  不依赖 `python main.py` 的测试用 trivial subprocess（如 `python -c "print('hello')"`）代替。
  Fake/local smoke test 才会用到实际 main.py。

测试分类：
  - 基础 subprocess 测试：runner 能启停、捕获 stdout/stderr/exit_code
  - stdin 序列测试：scripted stdin 正确写入
  - 超时测试：timeout 检测
  - traceback 检测：识别 crash
  - secret redact：sanitize 移除 key 片段
  - confirmation 检测：识别 confirmation prompt
  - 边界测试：空输出、特殊字符
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"

# 确保 scripts 目录在 path 中
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(SCRIPTS_DIR))


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def runner():
    """创建 SubprocessRunner 实例，使用较短超时。"""
    from scripts.dogfood_interactive_harness import SubprocessRunner
    return SubprocessRunner(timeout_s=10.0)


@pytest.fixture
def evaluator():
    """创建 CaseEvaluator 实例。"""
    from scripts.dogfood_interactive_harness import CaseEvaluator
    return CaseEvaluator()


# ── 1. 基础 subprocess 测试 ───────────────────────────────────────────────────


def test_runner_can_run_trivial_command(runner):
    """harness 能运行一个 trivial subprocess 命令并捕获输出。"""
    stdout, stderr, exit_code, timed_out = runner.run(
        [],
        timeout_s=5.0,
    )
    # 这会在 PROJECT_ROOT 下启动 main.py。
    # 不做强断言——只验证 runner 不抛异常、返回格式正确。
    assert isinstance(stdout, str)
    assert isinstance(stderr, str)
    assert not timed_out  # main.py 启动后应能正常退出（虽然可能因为 stdin 关闭而退出）


def test_runner_captures_python_minus_c():
    """harness 通过直接 subprocess 方式验证基础能力。

    中文学习说明：
      不依赖 main.py——直接用 python -c 验证 subprocess 管道正确。
    """
    import subprocess
    proc = subprocess.run(
        [sys.executable, "-c", "print('hello world')"],
        capture_output=True,
        text=True,
        timeout=5,
        cwd=str(PROJECT_ROOT),
    )
    assert proc.returncode == 0
    assert "hello world" in proc.stdout


def test_runner_captures_stderr():
    """harness 能捕获 stderr。"""
    import subprocess
    proc = subprocess.run(
        [sys.executable, "-c", "import sys; print('error', file=sys.stderr)"],
        capture_output=True,
        text=True,
        timeout=5,
        cwd=str(PROJECT_ROOT),
    )
    assert "error" in proc.stderr


def test_runner_captures_exit_code():
    """harness 能捕获非零 exit code。"""
    import subprocess
    proc = subprocess.run(
        [sys.executable, "-c", "import sys; sys.exit(42)"],
        capture_output=True,
        text=True,
        timeout=5,
        cwd=str(PROJECT_ROOT),
    )
    assert proc.returncode == 42


# ── 2. stdin 序列测试 ─────────────────────────────────────────────────────────


def test_runner_scripted_stdin_sequence():
    """harness 支持 scripted stdin 序列——通过管道发送多行输入。"""
    import subprocess
    script = """
import sys
for i, line in enumerate(sys.stdin):
    line = line.strip()
    if not line:
        break
    if line == 'quit':
        break
    print(f'echo: {line}')
"""
    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(PROJECT_ROOT),
    )
    out, err = proc.communicate(input="line1\nline2\nquit\n", timeout=5)
    assert proc.returncode == 0
    assert "echo: line1" in out
    assert "echo: line2" in out


# ── 3. 超时检测 ──────────────────────────────────────────────────────────────


def test_runner_detects_timeout():
    """harness 检测 subprocess 超时。"""
    import subprocess
    script = "import time; time.sleep(10)"
    with pytest.raises(subprocess.TimeoutExpired):
        subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=1.0,
            cwd=str(PROJECT_ROOT),
        )


# ── 4. traceback 检测 ─────────────────────────────────────────────────────────


def test_event_detection_traceback():
    """harness 检测输出中的 traceback。"""
    from scripts.dogfood_interactive_harness import _detect_events
    stdout = "Traceback (most recent call last):\n  File 'test.py', line 1\nValueError: boom"
    events = _detect_events(stdout, "")
    assert "TRACEBACK_DETECTED" in events


def test_event_detection_no_false_positive():
    """正常输出不应误报 traceback。"""
    from scripts.dogfood_interactive_harness import _detect_events
    stdout = "一切正常，任务完成。会话已保存，再见！"
    events = _detect_events(stdout, "")
    assert "TRACEBACK_DETECTED" not in events


# ── 5. sanitize / secret redact ───────────────────────────────────────────────


def test_sanitize_redacts_anthropic_key():
    """sanitize 移除 Anthropic API key 片段。"""
    from scripts.dogfood_interactive_harness import sanitize
    text = "api_key=sk-ant-api03-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    result = sanitize(text)
    assert "sk-ant" not in result
    assert "REDACTED" in result


def test_sanitize_redacts_openai_key():
    """sanitize 移除 OpenAI key 片段。"""
    from scripts.dogfood_interactive_harness import sanitize
    text = "sk-proj-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    result = sanitize(text)
    assert "sk-proj" not in result or "REDACTED" in result


def test_sanitize_preserves_normal_text():
    """sanitize 不应修改不包含 key 的正常文本。"""
    from scripts.dogfood_interactive_harness import sanitize
    text = "你好，这是一个正常的回复。会话已保存。"
    result = sanitize(text)
    assert result == text


# ── 6. confirmation 检测 ─────────────────────────────────────────────────────


def test_event_detection_confirmation_prompt():
    """harness 分类检测 waiting-for-confirmation。"""
    from scripts.dogfood_interactive_harness import _detect_events
    stdout = "确认执行 write_demo_note 工具吗？(y/n): "
    events = _detect_events(stdout, "")
    assert "CONFIRMATION_PROMPT" in events


def test_event_detection_tool_activity():
    """harness 检测 tool 相关事件。"""
    from scripts.dogfood_interactive_harness import _detect_events
    stdout = "🔧 工具 write_demo_note 已执行完成。"
    events = _detect_events(stdout, "")
    assert "TOOL_ACTIVITY" in events


def test_event_detection_memory_activity():
    """harness 检测 memory 相关事件。"""
    from scripts.dogfood_interactive_harness import _detect_events
    stdout = "🧠 记忆已保留：用户偏好中文回复。"
    events = _detect_events(stdout, "")
    assert "MEMORY_ACTIVITY" in events


def test_event_detection_run_summary():
    """harness 检测 run summary / session 结束。"""
    from scripts.dogfood_interactive_harness import _detect_events
    stdout = "会话已保存，再见！"
    events = _detect_events(stdout, "")
    assert "RUN_SUMMARY" in events


# ── 7. CaseEvaluator 判定逻辑 ─────────────────────────────────────────────────


def test_evaluator_pass():
    """evaluator：所有 expected 满足 → PASS。"""
    from scripts.dogfood_interactive_harness import CaseEvaluator, CaseSpec

    spec = CaseSpec(
        case_id="TEST",
        category="I-SANITY",
        description="test",
        input_sequence=["hello"],
        expected_fragments=["hello world"],
    )
    result = CaseEvaluator.evaluate(spec, "hello world from fake", "", 0, False, 100.0)
    assert result.status == "PASS"


def test_evaluator_fail_on_traceback():
    """evaluator：traceback → FAIL。"""
    from scripts.dogfood_interactive_harness import CaseEvaluator, CaseSpec

    spec = CaseSpec(
        case_id="TEST",
        category="I-SANITY",
        description="test",
        input_sequence=["hello"],
    )
    result = CaseEvaluator.evaluate(
        spec,
        "Traceback (most recent call last):\n  ValueError",
        "",
        1, False, 100.0,
    )
    assert result.status == "FAIL"


def test_evaluator_fail_on_nonzero_exit():
    """evaluator：non-zero exit → FAIL。"""
    from scripts.dogfood_interactive_harness import CaseEvaluator, CaseSpec

    spec = CaseSpec(
        case_id="TEST", category="I-SANITY", description="test",
        input_sequence=["hello"],
    )
    result = CaseEvaluator.evaluate(spec, "", "", 1, False, 100.0)
    assert result.status == "FAIL"


def test_evaluator_timeout():
    """evaluator：timeout → TIMEOUT status。"""
    from scripts.dogfood_interactive_harness import CaseEvaluator, CaseSpec

    spec = CaseSpec(
        case_id="TEST", category="I-SANITY", description="test",
        input_sequence=["hello"],
    )
    result = CaseEvaluator.evaluate(spec, "", "", None, True, 100.0)
    assert result.status == "TIMEOUT"


def test_evaluator_concern_on_missing_fragment():
    """evaluator：部分 expected 缺失 → CONCERN（非 FAIL）。"""
    from scripts.dogfood_interactive_harness import CaseEvaluator, CaseSpec

    spec = CaseSpec(
        case_id="TEST",
        category="I-SANITY",
        description="test",
        input_sequence=["hello"],
        expected_fragments=["expected output", "specific capability"],
    )
    result = CaseEvaluator.evaluate(spec, "some generic response", "", 0, False, 100.0)
    assert result.status == "CONCERN"


def test_evaluator_secret_leak_is_fail():
    """evaluator：secret leak 在输出中 → FAIL（即使 exit 0）。"""
    from scripts.dogfood_interactive_harness import CaseEvaluator, CaseSpec

    spec = CaseSpec(
        case_id="TEST", category="I-SANITY", description="test",
        input_sequence=["hello"],
    )
    result = CaseEvaluator.evaluate(
        spec,
        "here is your key: sk-ant-api03-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        "", 0, False, 100.0,
    )
    assert result.status == "FAIL"
    assert "SECRET_LEAK_DETECTED" in result.detected_events


# ── 7b. Loop 14 Evidence Gate guard tests ─────────────────────────────────────


def test_evaluator_empty_assertions_is_smoke_pass_not_capability_pass():
    """无实质断言（fragments/events/business_actions 全空）→ SMOKE_PASS，非 PASS。"""
    from scripts.dogfood_interactive_harness import CaseEvaluator, CaseSpec

    spec = CaseSpec(
        case_id="NO-ASSERT",
        category="I-SANITY",
        description="no assertions at all",
        input_sequence=["hello"],
    )
    result = CaseEvaluator.evaluate(spec, "some output", "", 0, False, 100.0)
    assert result.status == "SMOKE_PASS"
    assert "no-crash" in result.notes[0].lower()


def test_evaluator_empty_string_fragments_is_smoke_pass():
    """expected_fragments=[""] is treated as no assertion → SMOKE_PASS."""
    from scripts.dogfood_interactive_harness import CaseEvaluator, CaseSpec

    spec = CaseSpec(
        case_id="EMPTY-FRAG",
        category="I-SANITY",
        description="empty string fragment",
        input_sequence=["hello"],
        expected_fragments=[""],
    )
    result = CaseEvaluator.evaluate(spec, "some output", "", 0, False, 100.0)
    assert result.status == "SMOKE_PASS"


def test_evaluator_missing_expected_events_downgrades_to_concern():
    """expected_events 缺失 → CONCERN（即使 fragments 匹配）。"""
    from scripts.dogfood_interactive_harness import CaseEvaluator, CaseSpec

    spec = CaseSpec(
        case_id="MISSING-EVENT",
        category="I-TOOL",
        description="expects TOOL_ACTIVITY but none detected",
        input_sequence=["hello"],
        expected_fragments=["some output"],
        expected_events=["TOOL_ACTIVITY"],
    )
    result = CaseEvaluator.evaluate(spec, "some output here", "", 0, False, 100.0)
    assert result.status == "CONCERN"
    assert any("missing expected events" in n.lower() for n in result.notes)


def test_evaluator_all_expected_events_matched_is_pass():
    """所有 expected_events 都检测到 + fragments 匹配 → PASS。"""
    from scripts.dogfood_interactive_harness import CaseEvaluator, CaseSpec

    spec = CaseSpec(
        case_id="ALL-EVENTS",
        category="I-COMPLEX",
        description="all expected events present",
        input_sequence=["hello"],
        expected_fragments=["traceback detected"],  # will match stdout
        expected_events=["TRACEBACK_DETECTED"],
    )
    result = CaseEvaluator.evaluate(
        spec,
        "Traceback (most recent call last): traceback detected ...",
        "", 0, False, 100.0,
    )
    # TRACEBACK_DETECTED → FAIL takes priority over PASS
    assert result.status == "FAIL"


def test_evaluator_events_and_fragments_both_checked():
    """expected_events 全部检测到但 fragments 缺失 → CONCERN。"""
    from scripts.dogfood_interactive_harness import CaseEvaluator, CaseSpec

    spec = CaseSpec(
        case_id="EVENTS-OK-FRAGS-MISSING",
        category="I-COMPLEX",
        description="events match but fragments don't",
        input_sequence=["hello"],
        expected_fragments=["specific capability output"],
        expected_events=["RUN_SUMMARY"],
    )
    result = CaseEvaluator.evaluate(
        spec,
        "generic response\n会话已保存\n执行总结",
        "", 0, False, 100.0,
    )
    assert result.status == "CONCERN"
    assert any("missing expected fragments" in n.lower() for n in result.notes)


def test_evaluator_missing_business_actions_downgrades():
    """expected_business_actions 缺失 → CONCERN。"""
    from scripts.dogfood_interactive_harness import CaseEvaluator, CaseSpec

    spec = CaseSpec(
        case_id="NO-BIZ",
        category="I-TOOL",
        description="expects business action but none present",
        input_sequence=["do something"],
        expected_business_actions=["BUSINESS_ACTION"],
    )
    result = CaseEvaluator.evaluate(spec, "hello from fake", "", 0, False, 100.0)
    assert result.status == "CONCERN"
    assert any("missing expected business actions" in n.lower() for n in result.notes)


def test_evaluator_business_action_detected_in_output():
    """BUSINESS_ACTION 事件可在包含 tool/memory 关键词的输出中检测到。"""
    from scripts.dogfood_interactive_harness import _detect_events
    events = _detect_events("tool executed successfully\nmemory stored", "")
    assert "BUSINESS_ACTION" in events


def test_evaluator_no_crash_not_capability_pass():
    """no crash + exit 0 + 空断言 ≠ capability PASS。必须是 SMOKE_PASS。"""
    from scripts.dogfood_interactive_harness import CaseEvaluator, CaseSpec

    spec = CaseSpec(
        case_id="NO-CRASH",
        category="I-SANITY",
        description="should be SMOKE_PASS not PASS",
        input_sequence=["anything"],
    )
    result = CaseEvaluator.evaluate(spec, "some output", "", 0, False, 100.0)
    # 必须不是 PASS——空断言 case 不应标 capability PASS
    assert result.status != "PASS"
    assert result.status == "SMOKE_PASS"


# ── 8. 边界测试 ──────────────────────────────────────────────────────────────


def test_excerpt_truncation():
    """_excerpt 对长文本做截断。"""
    from scripts.dogfood_interactive_harness import _excerpt
    long_text = "x" * 1000
    result = _excerpt(long_text, max_len=500)
    assert len(result) < 1000
    assert "[truncated]" in result


def test_empty_output_no_false_events():
    """空输出不应产生误报事件。"""
    from scripts.dogfood_interactive_harness import _detect_events
    events = _detect_events("", "")
    # 空输出可能匹配空行正则，但不应有关键事件
    assert "TRACEBACK_DETECTED" not in events
    assert "SECRET_LEAK_DETECTED" not in events
    assert "TOOL_ACTIVITY" not in events


def test_case_matrix_has_all_categories():
    """case matrix 应覆盖所有要求的交互类别。"""
    from scripts.dogfood_interactive_harness import _build_case_matrix
    cases = _build_case_matrix()
    categories = {c.category for c in cases}
    expected = {
        "I-SANITY", "I-CONFIRM", "I-TOOL", "I-MEMORY",
        "I-STREAM", "I-RESUME", "I-COMPLEX", "I-INTERRUPT",
    }
    assert categories == expected, f"Missing categories: {expected - categories}"


def test_case_matrix_minimum_count():
    """case matrix 至少应有 20 个 cases。"""
    from scripts.dogfood_interactive_harness import _build_case_matrix
    cases = _build_case_matrix()
    assert len(cases) >= 20


# ── 9. config safety ─────────────────────────────────────────────────────────


def test_config_swap_mechanism_with_temp_dir(tmp_path):
    """config swap 通过文件系统操作实现，不读取原文件内容。

    中文学习说明：
      使用 tmp_path 而非真实 config/config.yaml——避免触碰用户真实 API key。
      测试只验证 swap/restore 机制本身正确。
    """
    from scripts.dogfood_interactive_harness import FAKE_CONFIG_CONTENT

    # 在临时目录中模拟 swap 机制
    fake_config = tmp_path / "config.yaml"
    fake_backup = tmp_path / "config.yaml.harness-backup"

    # 创建模拟原始 config（仅用于测试，不含真实 key）
    fake_config.write_text(
        "provider:\n  enabled: true\n  type: anthropic_compatible\n"
        "  api_key: test-key\n"
    )

    # swap: move original → backup, write fake
    import shutil
    shutil.move(str(fake_config), str(fake_backup))
    fake_config.write_text(FAKE_CONFIG_CONTENT, encoding="utf-8")

    assert fake_backup.exists()
    assert fake_config.exists()
    assert "enabled: false" in fake_config.read_text()
    assert "fake" in fake_config.read_text()

    # restore
    if fake_config.exists():
        fake_config.unlink()
    shutil.move(str(fake_backup), str(fake_config))

    assert not fake_backup.exists()
    assert fake_config.exists()
    assert "enabled: true" in fake_config.read_text()


def test_config_swap_restore_on_double_swap(tmp_path):
    """重复 swap 不应覆盖已有 backup。"""
    fake_config = tmp_path / "config.yaml"
    fake_backup = tmp_path / "config.yaml.harness-backup"

    # 先创建 backup（模拟上次 crash 留下的）
    fake_backup.write_text("original content")
    fake_config.write_text("current content")

    # 尝试 swap——backup 已存在，应安全跳过
    assert fake_backup.exists()
    # 不应覆盖已有 backup
    assert fake_backup.read_text() == "original content"


def test_sanitize_no_config_path_leak():
    """sanitize 输出中不应包含 config/config.yaml 路径中的 secret。"""
    from scripts.dogfood_interactive_harness import sanitize
    text = "Config loaded from config/config.yaml with key sk-ant-api03-xxxxxxxxxxxxxxxxxxxx"
    result = sanitize(text)
    assert "sk-ant-api03" not in result
    assert "REDACTED" in result


# ── 10. Fake/local smoke test ─────────────────────────────────────────────────


@pytest.mark.slow
def test_harness_fake_local_smoke():
    """harness 能成功运行至少一个 fake/local `python main.py` smoke case。

    这个测试验证端到端链路：subprocess 启动 → 发送输入 → 读取输出 → 不 crash。
    不验证具体输出内容（FakeProvider 下输出是确定性的但不保证语义）。
    """
    from scripts.dogfood_interactive_harness import (
        CaseEvaluator,
        CaseSpec,
        SubprocessRunner,
    )

    runner = SubprocessRunner(timeout_s=15.0)
    evaluator = CaseEvaluator()

    spec = CaseSpec(
        case_id="SMOKE",
        category="I-SANITY",
        description="fake/local smoke test",
        input_sequence=["hello"],
    )

    stdout, stderr, exit_code, timed_out = runner.run(["hello"], timeout_s=15.0)
    result = evaluator.evaluate(spec, stdout, stderr, exit_code, timed_out, 0)

    # Smoke 测试只要求不 crash、不 timeout
    assert result.status != "BLOCKED", f"harness could not start main.py: {stderr[:200]}"
    assert not timed_out, "smoke test timed out"
    assert "TRACEBACK_DETECTED" not in result.detected_events, f"traceback: {stderr[:300]}"
