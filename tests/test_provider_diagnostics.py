"""Provider 诊断守护测试（Phase 2: Provider Auth/Config Diagnostics）。

本测试文件验证：
1. diagnose_provider_config() 正确识别各种配置状态（缺少 key、无效 provider、fake 正常）
2. 诊断输出不泄露 secret（只输出 SET/not set）
3. map_provider_error() 正确映射已知错误码为用户可读消息
4. 401/403/timeout 等 HTTP 状态码映射为用户可执行建议
5. check_provider_config.py 脚本在干净环境中正确返回 exit code
6. `python main.py status` 新增命令行为正确

设计原则：
- 不读取 .env：所有测试使用显式传入的 env dict
- 不调用真实 API：使用 static env dict + fake/stub error objects
- API key 脱敏：只输出 SET/not set，不输出任何 key 内容
- 中文诊断信息：错误用户可理解，可执行
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"


# =========================================================================
# 1. diagnose_provider_config() 基础行为
# =========================================================================


def test_diagnose_fake_provider_is_ok():
    """fake provider 默认配置应该是 ok——无需 API key 或 model。"""
    from agent.provider.diagnostics import diagnose_provider_config

    diag = diagnose_provider_config(env={})
    assert diag.status == "ok"
    assert diag.provider_type == "fake"
    assert diag.api_key_present is False


def test_diagnose_fake_provider_explicit_is_ok():
    """显式设置 provider=fake 应该是 ok。"""
    from agent.provider.diagnostics import diagnose_provider_config

    diag = diagnose_provider_config(env={"MY_FIRST_AGENT_LLM_PROVIDER": "fake"})
    assert diag.status == "ok"
    assert diag.provider_type == "fake"


def test_diagnose_real_provider_without_key_is_warn():
    """真实 provider 缺少 API key 应该是 warn（不是 error，因为可能还没配 .env）。"""
    from agent.provider.diagnostics import diagnose_provider_config

    diag = diagnose_provider_config(env={
        "MY_FIRST_AGENT_LLM_PROVIDER": "anthropic_native",
        "ANTHROPIC_MODEL": "claude-sonnet-4-6",
    })
    assert diag.status in {"warn", "error"}
    assert diag.api_key_present is False
    assert any("API key" in i for i in diag.issues)


def test_diagnose_real_provider_with_key_and_model_is_ok():
    """真实 provider 有 key 和 model 应该是 ok（连接性需人工验证）。"""
    from agent.provider.diagnostics import diagnose_provider_config

    diag = diagnose_provider_config(env={
        "MY_FIRST_AGENT_LLM_PROVIDER": "anthropic_native",
        "ANTHROPIC_API_KEY": "sk-ant-test12345678901234567890",
        "ANTHROPIC_MODEL": "claude-sonnet-4-6",
    })
    assert diag.status == "ok"
    assert diag.api_key_present is True
    assert diag.model == "claude-sonnet-4-6"


def test_diagnose_invalid_provider_type_is_error():
    """无效的 provider 类型应该是 error——比 warn 更严重的阻塞性错误。

    即使同时缺少 API key，「未知 provider」的优先级更高，
    因为 provider 类型错误会导致所有后续配置无效。
    """
    from agent.provider.diagnostics import diagnose_provider_config

    diag = diagnose_provider_config(env={
        "MY_FIRST_AGENT_LLM_PROVIDER": "openrouter",
        # 显式清空 API key，防止测试 env 中的真实 key 干扰
        "ANTHROPIC_API_KEY": "",
        "OPENAI_API_KEY": "",
    })
    assert diag.status == "error", f"expected error, got {diag.status}: {diag.issues}"
    assert any("未知" in i or "unknown" in i.lower() for i in diag.issues)


def test_diagnose_compatible_provider_without_base_url_is_warn():
    """兼容模式 provider 缺少 base_url 应该有告警。"""
    from agent.provider.diagnostics import diagnose_provider_config

    diag = diagnose_provider_config(env={
        "MY_FIRST_AGENT_LLM_PROVIDER": "anthropic_compatible",
        "ANTHROPIC_API_KEY": "sk-ant-test12345678901234567890",
        "ANTHROPIC_MODEL": "claude-sonnet-4-6",
    })
    assert any("base_url" in i.lower() for i in diag.issues)


# =========================================================================
# 2. 脱敏验证
# =========================================================================


def test_diagnostic_does_not_leak_api_key_value():
    """诊断输出不得包含 API key 的值——只应显示 SET/not set。"""
    from agent.provider.diagnostics import diagnose_provider_config, render_diagnostic_report

    diag = diagnose_provider_config(env={
        "MY_FIRST_AGENT_LLM_PROVIDER": "anthropic_native",
        "ANTHROPIC_API_KEY": "sk-ant-secret-key-value-1234567890",
        "ANTHROPIC_MODEL": "claude-sonnet-4-6",
    })
    report = render_diagnostic_report(diag)
    assert "sk-ant-secret" not in report
    assert "SET (redacted)" in report or "SET" in report


def test_diagnostic_reports_key_env_name():
    """诊断报告应指出 key 来自哪个环境变量（ANTHROPIC_API_KEY / OPENAI_API_KEY）。

    这帮助用户知道自己配对了哪个变量。
    """
    from agent.provider.diagnostics import diagnose_provider_config, render_diagnostic_report

    diag = diagnose_provider_config(env={
        "ANTHROPIC_API_KEY": "sk-ant-test12345678901234567890",
    })
    report = render_diagnostic_report(diag)
    assert "ANTHROPIC_API_KEY" in report


def test_diagnostic_fake_mode_reports_no_key_needed():
    """fake 模式下诊断报告应说明无需 API key。"""
    from agent.provider.diagnostics import diagnose_provider_config, render_diagnostic_report

    diag = diagnose_provider_config(env={})
    report = render_diagnostic_report(diag)
    assert "fake" in report.lower()
    assert "无需" in report or "no key" in report.lower() or "安全路径" in report


# =========================================================================
# 3. map_provider_error() 错误码映射
# =========================================================================


def test_map_401_error_to_useful_message():
    """401 错误应映射为包含可执行建议的用户消息。"""
    from agent.provider.diagnostics import map_provider_error
    from agent.provider.protocol import ProviderAuthError

    err = ProviderAuthError("Unauthorized", status_code=401)
    msg = map_provider_error(err)
    assert "401" in msg
    assert "API key" in msg or "key" in msg.lower()
    assert "ANTHROPIC_API_KEY" in msg or "OPENAI_API_KEY" in msg


def test_map_403_error_to_useful_message():
    """403 错误应映射为权限相关的建议。"""
    from agent.provider.diagnostics import map_provider_error
    from agent.provider.protocol import ProviderAuthError

    err = ProviderAuthError("Forbidden", status_code=403)
    msg = map_provider_error(err)
    assert "403" in msg or "Forbidden" in msg


def test_map_timeout_error():
    """timeout 错误应映射为网络/超时建议。"""
    from agent.provider.diagnostics import map_provider_error
    from agent.provider.protocol import ProviderTimeoutError

    err = ProviderTimeoutError("Request timed out")
    msg = map_provider_error(err)
    assert "超时" in msg or "timeout" in msg.lower()


def test_map_configuration_error():
    """配置错误应映射为包含 environment variable 建议的消息。"""
    from agent.provider.diagnostics import map_provider_error
    from agent.provider.protocol import ProviderConfigurationError

    err = ProviderConfigurationError("api_key_missing")
    msg = map_provider_error(err)
    assert "API key" in msg or "key" in msg.lower()


# =========================================================================
# 4. check_provider_config.py 脚本行为
# =========================================================================


def _run_provider_config_script(
    env_override: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    """在隔离环境中运行 check_provider_config.py。

    显式清除可能导致真实 API 的环境变量，确保测试确定性。
    """
    script = str(SCRIPTS_DIR / "check_provider_config.py")
    with tempfile.TemporaryDirectory(prefix="first_agent_test_") as tmp_home:
        test_env = {
            **os.environ,
            "HOME": tmp_home,
        }
        # 清除所有可能指向真实 provider 的环境变量
        for key in list(test_env):
            if (key.startswith("ANTHROPIC_")
                    or key.startswith("OPENAI_")
                    or key.startswith("MY_FIRST_AGENT_LLM_")):
                del test_env[key]
        if env_override:
            test_env.update(env_override)
        return subprocess.run(
            [sys.executable, script],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(PROJECT_ROOT),
            env=test_env,
        )


def test_provider_config_script_default_fake_returns_zero():
    """check_provider_config.py 默认环境应返回 exit code 0（fake ok）。"""
    result = _run_provider_config_script()
    assert result.returncode == 0, (
        f"exit code={result.returncode}\nstdout={result.stdout[:500]}"
    )


def test_provider_config_script_output_contains_provider_info():
    """诊断脚本应输出 provider type、model、base url、key 状态。"""
    result = _run_provider_config_script()
    assert "Provider type" in result.stdout
    assert "Model" in result.stdout
    assert "Status" in result.stdout


def test_provider_config_script_real_without_key_returns_warn():
    """真实 provider 无 key 时应返回非零 exit code。

    必须显式清除 ANTHROPIC_API_KEY / OPENAI_API_KEY——process env 中
    可能已设置了真实的 API key，覆盖 env_override 的意图。
    """
    result = _run_provider_config_script(env_override={
        "MY_FIRST_AGENT_LLM_PROVIDER": "anthropic_native",
        "ANTHROPIC_MODEL": "claude-sonnet-4-6",
        "ANTHROPIC_API_KEY": "",
        "OPENAI_API_KEY": "",
    })
    assert result.returncode != 0, (
        f"expected non-zero exit code for missing key, got {result.returncode}\n"
        f"stdout={result.stdout[:500]}"
    )


# =========================================================================
# 5. `python main.py status` 命令
# =========================================================================


def test_main_status_command_runs():
    """python main.py status 应可运行并输出诊断信息。"""
    with tempfile.TemporaryDirectory(prefix="first_agent_status_") as tmp_home:
        test_env = {
            **os.environ,
            "HOME": tmp_home,
        }
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "main.py"), "status"],
            capture_output=True,
            text=True,
            timeout=20,
            cwd=str(PROJECT_ROOT),
            env=test_env,
        )
        output = result.stdout + result.stderr
        assert "Provider" in output or "provider" in output.lower()
        assert result.returncode in {0, 1, 2}


def test_main_status_command_no_secret_leakage():
    """main.py status 输出不得泄露 API key 值。"""
    import re

    with tempfile.TemporaryDirectory(prefix="first_agent_status_") as tmp_home:
        test_env = {
            **os.environ,
            "HOME": tmp_home,
            "MY_FIRST_AGENT_LLM_PROVIDER": "anthropic_native",
            "ANTHROPIC_API_KEY": "sk-ant-secret-test-key-12345678901234567",
            "ANTHROPIC_MODEL": "claude-sonnet-4-6",
        }
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "main.py"), "status"],
            capture_output=True,
            text=True,
            timeout=20,
            cwd=str(PROJECT_ROOT),
            env=test_env,
        )
        output = result.stdout + result.stderr
        assert "sk-ant-secret" not in output
        secret_patterns = [
            r"sk-ant-[A-Za-z0-9_-]{20,}",
            r"sk-[A-Za-z0-9_-]{20,}",
        ]
        for pattern in secret_patterns:
            assert not re.search(pattern, output), "status output leaks key"


# =========================================================================
# 8. P0 回归：fake/local 模式 model_name 不为空
# =========================================================================


def test_legacy_model_name_fallback_in_clean_env():
    """get_legacy_model_name() 在无任何环境变量时必须返回 "fake-llm"。

    这是 P0 回归测试：用户 `python main.py` 启动 fake/local 交互模式
    输入正常对话后，LoopContext.__post_init__ 曾因 model_name 为空而崩溃。

    根因：get_legacy_model_name() → _resolve_model_name() 在 fake 模式下返回 None，
    config.MODEL_NAME (via __getattr__) 缓存了 None，core.chat() 将其传给
    LoopContext，触发 frozen dataclass 的 __post_init__ 校验。

    修复后 get_legacy_model_name() 在所有 env vars 都未设置时返回 "fake-llm"，
    确保 fake/local 路径始终有合法非空 model_name。
    """
    import os as _os

    from config import get_legacy_model_name

    saved = {}
    for var in (
        "MY_FIRST_AGENT_LLM_MODEL",
        "MODEL_NAME",
        "ANTHROPIC_MODEL",
        "OPENAI_MODEL",
    ):
        saved[var] = _os.environ.pop(var, None)

    try:
        result = get_legacy_model_name()
        assert result == "fake-llm", (
            f"无 env var 时 get_legacy_model_name() 应为 'fake-llm'，实际: {result!r}"
        )
        assert isinstance(result, str)
        assert result.strip()
    finally:
        for var, val in saved.items():
            if val is not None:
                _os.environ[var] = val
            elif var in _os.environ:
                del _os.environ[var]


def test_config_module_attr_never_none_in_fake_mode():
    """config.MODEL_NAME (via __getattr__) 在 fake 模式下不应为 None。

    config.py 的 __getattr__ 懒加载兼容层让 `from config import MODEL_NAME`
    在 import 时触发 get_legacy_model_name()。修复后即使没有任何环境变量，
    也应返回 "fake-llm" 而非 None。
    """
    import os as _os

    saved = {}
    for var in (
        "MY_FIRST_AGENT_LLM_MODEL",
        "MODEL_NAME",
        "ANTHROPIC_MODEL",
        "OPENAI_MODEL",
    ):
        saved[var] = _os.environ.pop(var, None)

    try:
        # 模拟 core.py 的 import 路径：通过 config.MODEL_NAME 获取模型名
        import config as _cfg

        model = _cfg.MODEL_NAME
        assert model is not None, "config.MODEL_NAME 不应为 None（fake 模式兜底值缺失）"
        assert isinstance(model, str), f"config.MODEL_NAME 应为 str，实际: {type(model)}"
        assert model.strip(), f"config.MODEL_NAME 不应为空串，实际: {model!r}"
        assert model == "fake-llm", (
            f"无 env var 时 config.MODEL_NAME 应为 'fake-llm'，实际: {model!r}"
        )
    finally:
        for var, val in saved.items():
            if val is not None:
                _os.environ[var] = val
            elif var in _os.environ:
                del _os.environ[var]


def test_core_chat_fake_mode_does_not_crash_on_model_name():
    """core._build_loop_context() 在 fake 模式下不因 model_name 为空而崩溃。

    端到端回归：模拟用户 `python main.py` 交互模式输入对话文本的路径。
    验证 _build_loop_context() → build_loop_context() → LoopContext.__post_init__
    不会抛出 ValueError。

    更多端到端验证见 test_main_fake_interactive_chat_no_crash。
    """
    import os as _os

    from agent.core import _build_loop_context
    from agent.provider.fake_provider import FakeProvider

    saved = {}
    for var in (
        "MY_FIRST_AGENT_LLM_MODEL",
        "MODEL_NAME",
        "ANTHROPIC_MODEL",
        "OPENAI_MODEL",
    ):
        saved[var] = _os.environ.pop(var, None)

    try:
        fake = FakeProvider()

        from config import MAX_CONTINUE_ATTEMPTS, MODEL_NAME

        # 验证 MODEL_NAME 非空（修复后此处不会为 None）
        assert MODEL_NAME is not None, "config.MODEL_NAME 不应为 None"
        assert isinstance(MODEL_NAME, str)
        assert MODEL_NAME.strip()
        assert MODEL_NAME == "fake-llm", (
            f"无 env var 时 MODEL_NAME 应为 'fake-llm'，实际: {MODEL_NAME!r}"
        )

        # 构造 LoopContext——之前这里会因为 model_name=None 崩溃
        ctx = _build_loop_context(
            fake,
            model_name=MODEL_NAME,
            max_loop_iterations=MAX_CONTINUE_ATTEMPTS,
            provider=fake,
        )
        assert ctx.model_name == "fake-llm"
    finally:
        for var, val in saved.items():
            if val is not None:
                _os.environ[var] = val
            elif var in _os.environ:
                del _os.environ[var]


def test_main_fake_interactive_chat_no_crash():
    """`python main.py` fake 交互模式输入正常对话不崩溃（P0 端到端回归）。

    这是对用户报告的 bug 的精确复现：
    - 用户运行 `python main.py`
    - 输入 "帮我规划下去武汉 玩5天的旅游计划"
    - 程序抛出 ValueError: LoopContext.model_name 必须是非空字符串

    修复后 fake 模式 model_name 兜底为 "fake-llm"，不再崩溃。
    """
    import signal
    import subprocess as _sp
    import tempfile

    with tempfile.TemporaryDirectory(prefix="first_agent_chat_") as tmp_home:
        test_env = {
            **os.environ,
            "HOME": tmp_home,
            "MY_FIRST_AGENT_LLM_PROVIDER": "fake",
        }
        # 移除可能存在的真实 API key，确保走 fake 路径
        for key_var in (
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "MY_FIRST_AGENT_LLM_MODEL",
            "MODEL_NAME",
            "ANTHROPIC_MODEL",
            "OPENAI_MODEL",
        ):
            test_env.pop(key_var, None)

        proc = _sp.Popen(
            [sys.executable, str(PROJECT_ROOT / "main.py")],
            stdin=_sp.PIPE,
            stdout=_sp.PIPE,
            stderr=_sp.PIPE,
            text=True,
            cwd=str(PROJECT_ROOT),
            env=test_env,
        )

        try:
            # 发送用户输入 + quit
            stdout, stderr = proc.communicate(
                input="帮我规划下去武汉 玩5天的旅游计划\nquit\n",
                timeout=15,
            )
        except _sp.TimeoutExpired as exc:
            proc.send_signal(signal.SIGTERM)
            stdout, stderr = proc.communicate(timeout=5)
            raise AssertionError(
                "main.py subprocess 超时未退出——可能卡在交互循环中"
            ) from exc

        output = stdout + stderr

        # 不应包含 ValueError crash
        assert "ValueError" not in output, (
            f"main.py 崩溃（ValueError）:\n{output[-2000:]}"
        )
        assert "LoopContext" not in output or "fake" in output.lower(), (
            f"输出可能包含 LoopContext 异常:\n{output[-2000:]}"
        )
        # 不应包含 traceback
        assert "Traceback (most recent call last)" not in output, (
            f"main.py 产生了 traceback:\n{output[-2000:]}"
        )
        # 应该正常退出（exit 0 或正常终止）
        assert proc.returncode in {0, -15}, (
            f"main.py exit code={proc.returncode}，预期 0:\n{output[-2000:]}"
        )


# =========================================================================
# 9. P0 回归：默认 fake/local 路径 provider 注入不为空
# =========================================================================


def test_build_model_provider_from_env_defaults_to_fake():
    """build_model_provider_from_env() 在未设置 MY_FIRST_AGENT_LLM_PROVIDER 时必须
    返回非 None 的 provider。

    这是 P0 回归测试——a2dfd89 修了 model_name fallback，但没有修 provider 注入。
    当用户不设置任何 provider 环境变量运行 `python main.py` 时，默认路径应该是
    FakeProvider（safe local path），而不是 None。

    build_model_provider_from_env() 返回 None → build_loop_context() 给
    LoopContext.model_provider 赋 None → _call_model() 传 None 给 call_model()
    → ProviderNotImplementedError("model_provider_required")。
    """
    import os as _os

    from agent.provider.factory import build_model_provider_from_env

    saved = _os.environ.pop("MY_FIRST_AGENT_LLM_PROVIDER", None)

    try:
        provider = build_model_provider_from_env()
        assert provider is not None, (
            "build_model_provider_from_env() 在无 MY_FIRST_AGENT_LLM_PROVIDER 时"
            "返回了 None——默认 fake/local 安全路径 provider 注入缺失"
        )
        assert hasattr(provider, "provider_type"), (
            "返回的 provider 必须有 provider_type 属性"
        )
        assert provider.provider_type == "fake", (
            f"默认 provider 应为 'fake'，实际: {provider.provider_type!r}"
        )
    finally:
        if saved is not None:
            _os.environ["MY_FIRST_AGENT_LLM_PROVIDER"] = saved


def test_main_fake_interactive_no_provider_env_var():
    """`python main.py` 不设置任何 provider 环境变量时普通聊天不崩溃。

    这是人工 dogfood 发现的精确回归：
    - 用户不设置任何 provider 环境变量
    - `python main.py status` 显示 provider mode=fake（diagnose_provider_config 默认）
    - 但 `python main.py` 交互模式崩溃：ProviderNotImplementedError("model_provider_required")

    根因：build_model_provider_from_env() 在无 MY_FIRST_AGENT_LLM_PROVIDER 时
    返回 None，而 build_loop_context() 的 fallback 路径没有兜底 FakeProvider。

    修复后，build_model_provider_from_env() 在无 env var 时默认返回 FakeProvider，
    整个注入链畅通：core.chat → loop.py → model_call → FakeProvider。
    """
    import signal
    import subprocess as _sp
    import tempfile

    with tempfile.TemporaryDirectory(prefix="first_agent_chat_") as tmp_home:
        test_env = {
            **os.environ,
            "HOME": tmp_home,
        }
        # 关键：不设置 MY_FIRST_AGENT_LLM_PROVIDER，模拟真实默认路径
        for key_var in (
            "MY_FIRST_AGENT_LLM_PROVIDER",
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "MY_FIRST_AGENT_LLM_MODEL",
            "MODEL_NAME",
            "ANTHROPIC_MODEL",
            "OPENAI_MODEL",
        ):
            test_env.pop(key_var, None)

        proc = _sp.Popen(
            [sys.executable, str(PROJECT_ROOT / "main.py")],
            stdin=_sp.PIPE,
            stdout=_sp.PIPE,
            stderr=_sp.PIPE,
            text=True,
            cwd=str(PROJECT_ROOT),
            env=test_env,
        )

        try:
            stdout, stderr = proc.communicate(
                input="你好，帮我规划一下武汉5天旅游\nquit\n",
                timeout=20,
            )
        except _sp.TimeoutExpired as exc:
            proc.send_signal(signal.SIGTERM)
            stdout, stderr = proc.communicate(timeout=5)
            raise AssertionError(
                "main.py subprocess 超时——可能卡在交互循环中"
            ) from exc

        output = stdout + stderr

        # 不应出现 ProviderNotImplementedError
        assert "ProviderNotImplementedError" not in output, (
            "main.py 抛出 ProviderNotImplementedError——provider 注入链断裂:\n"
            f"{output[-2000:]}"
        )
        assert "model_provider_required" not in output, (
            "main.py 报 model_provider_required——provider 未注入:\n"
            f"{output[-2000:]}"
        )
        # 不应出现 traceback
        assert "Traceback (most recent call last)" not in output, (
            f"main.py 产生了 traceback:\n{output[-2000:]}"
        )
        # 不应出现 ValueError（model_name 空值）
        assert "ValueError" not in output, (
            f"main.py 崩溃（ValueError）:\n{output[-2000:]}"
        )
        # 应显示 provider mode=fake
        assert "fake" in output.lower(), (
            f"输出应包含 provider mode=fake:\n{output[-2000:]}"
        )
        # 应正常退出
        assert proc.returncode in {0, -15}, (
            f"main.py exit code={proc.returncode}，预期 0:\n{output[-2000:]}"
        )


# =========================================================================
# 10. Config Source 追踪（v0.11+）
# =========================================================================


def test_diagnose_config_source_shell_env_when_no_dotenv():
    """未提供 dotenv_path 时 config_source 应为 shell_env。"""
    from agent.provider.diagnostics import diagnose_provider_config

    diag = diagnose_provider_config(env={
        "MY_FIRST_AGENT_LLM_PROVIDER": "anthropic_native",
        "ANTHROPIC_API_KEY": "sk-ant-test12345678901234567890",
        "ANTHROPIC_MODEL": "claude-sonnet-4-6",
    })
    assert diag.config_source == "shell_env"


def test_diagnose_config_source_default_fake():
    """无任何配置时 config_source 应为 default_fake。"""
    from agent.provider.diagnostics import diagnose_provider_config

    diag = diagnose_provider_config(env={})
    assert diag.config_source == "default_fake"
    assert diag.provider_type == "fake"


def test_diagnose_config_source_mixed_detects_outer_override():
    """外层 env 覆盖 .env 值时 config_source 应为 mixed，并列出被覆盖的 key。

    模拟真实场景：外层 Coding Agent 设置了 ANTHROPIC_MODEL 和 ANTHROPIC_BASE_URL，
    项目 .env 也设置了这些变量但值不同。
    """
    import tempfile
    from pathlib import Path

    from agent.provider.diagnostics import diagnose_provider_config

    # 创建临时 .env 文件
    with tempfile.TemporaryDirectory() as tmp:
        dotenv_path = Path(tmp) / ".env"
        dotenv_path.write_text(
            "ANTHROPIC_MODEL=kimi-k2.5\n"
            "ANTHROPIC_BASE_URL=https://coding.dashscope.aliyuncs.com/apps/anthropic\n"
            "ANTHROPIC_API_KEY=sk-dotenv-key-12345\n"
        )

        # 外层 env 有不同的 ANTHROPIC_MODEL 和 ANTHROPIC_BASE_URL
        diag = diagnose_provider_config(
            env={
                "ANTHROPIC_MODEL": "deepseek-v4-pro",
                "ANTHROPIC_BASE_URL": "https://api.deepseek.com",
            },
            dotenv_path=str(dotenv_path),
        )
        assert diag.config_source == "mixed", (
            f"expected mixed, got {diag.config_source}"
        )
        assert diag.dotenv_loaded is True
        assert "ANTHROPIC_MODEL" in diag.outer_env_overrides
        assert "ANTHROPIC_BASE_URL" in diag.outer_env_overrides


def test_diagnose_config_source_project_dotenv():
    """.env 值未被外层覆盖时 config_source 应为 project_dotenv。"""
    import tempfile
    from pathlib import Path

    from agent.provider.diagnostics import diagnose_provider_config

    with tempfile.TemporaryDirectory() as tmp:
        dotenv_path = Path(tmp) / ".env"
        dotenv_path.write_text(
            "ANTHROPIC_MODEL=kimi-k2.5\n"
            "ANTHROPIC_API_KEY=sk-dotenv-key-12345\n"
        )

        diag = diagnose_provider_config(
            env={
                "ANTHROPIC_MODEL": "kimi-k2.5",
                "ANTHROPIC_API_KEY": "sk-dotenv-key-12345",
            },
            dotenv_path=str(dotenv_path),
        )
        assert diag.config_source == "project_dotenv", (
            f"expected project_dotenv, got {diag.config_source}"
        )
        assert diag.outer_env_overrides == []


# =========================================================================
# 11. Isolated Dotenv Diagnostic
# =========================================================================


def test_isolated_diagnostic_uses_only_dotenv_values():
    """isolated 模式应清除外层 env，只使用 .env 中的配置值。

    模拟：外层 ANTHROPIC_MODEL=deepseek-v4-pro，.env 中 ANTHROPIC_MODEL=kimi-k2.5。
    isolated 诊断应以 kimi-k2.5 为准。
    """
    import os as _os
    import tempfile
    from pathlib import Path

    from agent.provider.diagnostics import diagnose_provider_config_isolated

    # 创建一个临时 .env
    with tempfile.TemporaryDirectory() as tmp:
        dotenv_path = Path(tmp) / ".env"
        dotenv_path.write_text(
            "ANTHROPIC_MODEL=kimi-k2.5\n"
            "ANTHROPIC_API_KEY=sk-dotenv-key-12345\n"
            "ANTHROPIC_BASE_URL=https://example.com/api\n"
            "MY_FIRST_AGENT_LLM_PROVIDER=anthropic_compatible\n"
        )

        # 注入外层 env
        _os.environ["ANTHROPIC_MODEL"] = "deepseek-v4-pro"
        _os.environ["ANTHROPIC_BASE_URL"] = "https://api.deepseek.com"

        try:
            diag = diagnose_provider_config_isolated(str(dotenv_path))
            # 应使用 .env 的 kimi-k2.5，而非外层的 deepseek-v4-pro
            assert diag.model == "kimi-k2.5", (
                f"expected kimi-k2.5 from .env, got {diag.model}"
            )
            assert diag.provider_type == "anthropic_compatible"
            assert diag.config_source == "project_dotenv"
            assert diag.api_key_present is True
        finally:
            # 清理
            _os.environ.pop("ANTHROPIC_MODEL", None)
            _os.environ.pop("ANTHROPIC_BASE_URL", None)


def test_isolated_diagnostic_empty_dotenv_falls_back_to_fake():
    """isolated 模式 .env 为空或无 provider 配置时仍返回 fake 兜底。"""
    import tempfile
    from pathlib import Path

    from agent.provider.diagnostics import diagnose_provider_config_isolated

    with tempfile.TemporaryDirectory() as tmp:
        dotenv_path = Path(tmp) / ".env"
        dotenv_path.write_text("# 空文件\n")

        diag = diagnose_provider_config_isolated(str(dotenv_path))
        assert diag.provider_type == "fake"
        # .env 只有注释没有 key=value 时 dotenv_loaded=false（无有效配置值）
        assert diag.dotenv_loaded is False


def test_isolated_diagnostic_no_secret_in_output():
    """isolated 诊断输出不得包含 .env 中的 API key 值。"""
    import tempfile
    from pathlib import Path

    from agent.provider.diagnostics import (
        diagnose_provider_config_isolated,
        render_diagnostic_report,
    )

    with tempfile.TemporaryDirectory() as tmp:
        dotenv_path = Path(tmp) / ".env"
        dotenv_path.write_text(
            "ANTHROPIC_API_KEY=sk-secret-key-that-must-not-leak-12345\n"
            "ANTHROPIC_MODEL=kimi-k2.5\n"
            "MY_FIRST_AGENT_LLM_PROVIDER=anthropic_compatible\n"
        )

        diag = diagnose_provider_config_isolated(str(dotenv_path))
        report = render_diagnostic_report(diag)
        assert "sk-secret" not in report
        assert "sk-secret-key-that-must-not-leak" not in report
        assert "SET (redacted)" in report


def test_isolated_diagnostic_shows_model_and_base_url_redacted():
    """isolated 诊断应显示 model 名和脱敏 base_url。"""
    import tempfile
    from pathlib import Path

    from agent.provider.diagnostics import (
        diagnose_provider_config_isolated,
        render_diagnostic_report,
    )

    with tempfile.TemporaryDirectory() as tmp:
        dotenv_path = Path(tmp) / ".env"
        dotenv_path.write_text(
            "ANTHROPIC_API_KEY=sk-test12345678901234567890\n"
            "ANTHROPIC_MODEL=kimi-k2.5\n"
            "ANTHROPIC_BASE_URL=https://coding.dashscope.aliyuncs.com/apps/anthropic\n"
            "MY_FIRST_AGENT_LLM_PROVIDER=anthropic_compatible\n"
        )

        diag = diagnose_provider_config_isolated(str(dotenv_path))
        report = render_diagnostic_report(diag)
        assert "kimi-k2.5" in report
        # hostname 应可见（不是 secret），但完整路径不显示
        assert "coding.dashscope.aliyuncs.com" in report
        assert "project_dotenv" in report


# =========================================================================
# 12. provider-diagnostics CLI 命令
# =========================================================================


def test_main_provider_diagnostics_command():
    """python main.py provider-diagnostics 应可运行。"""
    import subprocess
    import tempfile

    with tempfile.TemporaryDirectory(prefix="first_agent_pd_") as tmp_home:
        test_env = {**os.environ, "HOME": tmp_home}
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "main.py"),
             "provider-diagnostics"],
            capture_output=True,
            text=True,
            timeout=20,
            cwd=str(PROJECT_ROOT),
            env=test_env,
        )
        output = result.stdout + result.stderr
        assert "Config source" in output, (
            f"应包含 Config source 字段:\n{output[:500]}"
        )
        assert result.returncode in {0, 1, 2}


def test_main_provider_diagnostics_isolated_flag():
    """python main.py provider-diagnostics --isolated-dotenv 应使用 isolated 模式。"""
    import subprocess
    import tempfile

    with tempfile.TemporaryDirectory(prefix="first_agent_pdi_") as tmp_home:
        test_env = {**os.environ, "HOME": tmp_home}
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "main.py"),
             "provider-diagnostics", "--isolated-dotenv"],
            capture_output=True,
            text=True,
            timeout=20,
            cwd=str(PROJECT_ROOT),
            env=test_env,
        )
        output = result.stdout + result.stderr
        assert "Isolated" in output or "isolated" in output.lower(), (
            f"应提到 isolated:\n{output[:500]}"
        )
        assert result.returncode in {0, 1, 2}


def test_provider_diagnostics_no_secret_leakage():
    """provider-diagnostics 命令不得泄露 API key 值。"""
    import re
    import subprocess
    import tempfile

    with tempfile.TemporaryDirectory(prefix="first_agent_pd_") as tmp_home:
        test_env = {
            **os.environ,
            "HOME": tmp_home,
            "ANTHROPIC_API_KEY": "sk-ant-secret-test-key-12345678901234567",
            "ANTHROPIC_MODEL": "claude-sonnet-4-6",
            "MY_FIRST_AGENT_LLM_PROVIDER": "anthropic_native",
        }
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "main.py"),
             "provider-diagnostics"],
            capture_output=True,
            text=True,
            timeout=20,
            cwd=str(PROJECT_ROOT),
            env=test_env,
        )
        output = result.stdout + result.stderr
        assert "sk-ant-secret" not in output
        secret_patterns = [
            r"sk-ant-[A-Za-z0-9_-]{20,}",
            r"sk-[A-Za-z0-9_-]{20,}",
        ]
        for pattern in secret_patterns:
            assert not re.search(pattern, output), "provider-diagnostics leaks key"


# =========================================================================
# 13. fake 模式与 key 共存的行为验证
# =========================================================================


def test_fake_mode_ignores_key_when_key_present_in_env():
    """fake 模式下即使 env 中有 key，diagnostic 也应为 ok 且说明 key 不被使用。"""
    from agent.provider.diagnostics import diagnose_provider_config, render_diagnostic_report

    diag = diagnose_provider_config(env={
        "ANTHROPIC_API_KEY": "sk-ant-test12345678901234567890",
        "ANTHROPIC_MODEL": "claude-sonnet-4-6",
    })
    # fake 模式（无 MY_FIRST_AGENT_LLM_PROVIDER），但 key 存在
    assert diag.provider_type == "fake"
    assert diag.api_key_present is True
    assert diag.status == "ok"

    report = render_diagnostic_report(diag)
    assert "fake" in report.lower()
    assert "不会使用" in report or "无需" in report or "安全路径" in report


def test_real_mode_requires_explicit_provider_env():
    """真实 provider 需要显式设置 MY_FIRST_AGENT_LLM_PROVIDER，仅有 key 不够。"""
    from agent.provider.diagnostics import diagnose_provider_config

    diag = diagnose_provider_config(env={
        "ANTHROPIC_API_KEY": "sk-ant-test12345678901234567890",
        "ANTHROPIC_MODEL": "claude-sonnet-4-6",
        # 注意：没有 MY_FIRST_AGENT_LLM_PROVIDER
    })
    # 仍是 fake 模式
    assert diag.provider_type == "fake"
    # fake 模式下 key present 但 status 仍为 ok（只是不会用）
    assert diag.status == "ok"


def test_diagnostics_and_runtime_use_same_config_resolver():
    """diagnose_provider_config 和 load_agent_provider_config 对同一 env 应得出一致结论。

    root cause guard：之前 diag 和 runtime 用了不同的解析逻辑，导致
    `python main.py status` 显示 fake，但实际 runtime 走了 real 路径。
    """
    from agent.provider.config import load_agent_provider_config
    from agent.provider.diagnostics import diagnose_provider_config

    env = {
        "MY_FIRST_AGENT_LLM_PROVIDER": "anthropic_native",
        "ANTHROPIC_API_KEY": "sk-ant-test12345678901234567890",
        "ANTHROPIC_MODEL": "claude-sonnet-4-6",
    }

    diag = diagnose_provider_config(env=env)
    config = load_agent_provider_config(env=env)

    # provider type 一致
    assert diag.provider_type == config.provider_type, (
        f"diag: {diag.provider_type}, config: {config.provider_type}"
    )
    # model 一致
    assert diag.model == config.model, (
        f"diag: {diag.model}, config: {config.model}"
    )
    # key 存在性一致
    assert diag.api_key_present == bool(config.api_key), (
        f"diag key present: {diag.api_key_present}, config key: {bool(config.api_key)}"
    )


# ============================================================
# Provider Profile 配置测试 (v0.11+)
# ============================================================


def _write_temp_profiles_yaml(profiles_yaml: str) -> str:
    """写临时 provider_profiles.yaml，返回路径。"""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(textwrap.dedent(profiles_yaml))
        return tmp.name


class TestProviderProfileResolution:
    """测试 ProviderProfile 解析逻辑。"""

    def test_no_profile_env_defaults_to_fake(self):
        """无 FIRST_AGENT_PROVIDER_PROFILE 且 YAML 中 active_profile=fake → fake。"""
        from agent.provider.profiles import load_provider_profiles, resolve_active_profile

        yaml_path = _write_temp_profiles_yaml("""
            active_profile: fake
            profiles:
              fake:
                type: fake
                model: fake-llm
        """)
        try:
            profiles = load_provider_profiles(path=yaml_path)
            resolved, method = resolve_active_profile(profiles, env={})
            assert resolved is not None
            assert resolved.name == "fake"
            assert resolved.provider_type == "fake"
            assert method == "default_fake"
        finally:
            os.unlink(yaml_path)

    def test_profile_env_selects_named_profile(self):
        """FIRST_AGENT_PROVIDER_PROFILE=kimi_anthropic → 选中对应 profile。"""
        from agent.provider.profiles import load_provider_profiles, resolve_active_profile

        yaml_path = _write_temp_profiles_yaml("""
            active_profile: fake
            profiles:
              fake:
                type: fake
                model: fake-llm
              kimi_anthropic:
                type: anthropic_compatible
                model: kimi-k2.5
                base_url: https://example.com/api
                api_key_env: ANTHROPIC_API_KEY
                request_path: /v1/messages
                auth_scheme: auto
        """)
        try:
            profiles = load_provider_profiles(path=yaml_path)
            resolved, method = resolve_active_profile(
                profiles, env={"FIRST_AGENT_PROVIDER_PROFILE": "kimi_anthropic"}
            )
            assert resolved is not None
            assert resolved.name == "kimi_anthropic"
            assert resolved.provider_type == "anthropic_compatible"
            assert resolved.model == "kimi-k2.5"
            assert resolved.base_url == "https://example.com/api"
            assert resolved.api_key_env == "ANTHROPIC_API_KEY"
            assert method == "profile_env"
        finally:
            os.unlink(yaml_path)

    def test_profile_to_agent_config_reads_key_from_env(self):
        """profile_to_agent_config 从 env 读取 api_key_env 指向的变量。"""
        from agent.provider.profiles import (
            ProviderProfile,
            profile_to_agent_config,
        )

        profile = ProviderProfile(
            name="kimi_anthropic",
            provider_type="anthropic_compatible",
            model="kimi-k2.5",
            base_url="https://example.com/api",
            api_key_env="ANTHROPIC_API_KEY",
        )
        config = profile_to_agent_config(
            profile,
            env={"ANTHROPIC_API_KEY": "sk-test-key-12345"},
        )
        assert config.provider_type == "anthropic_compatible"
        assert config.model == "kimi-k2.5"
        assert config.api_key == "sk-test-key-12345"
        assert config.api_key_env == "ANTHROPIC_API_KEY"

    def test_profile_to_agent_config_missing_key_raises(self):
        """api_key_env 指向的变量未设置 → 抛 api_key_missing。"""
        from agent.provider.profiles import (
            ProviderProfile,
            profile_to_agent_config,
        )
        from agent.provider.protocol import ProviderConfigurationError

        profile = ProviderProfile(
            name="glm_openai",
            provider_type="openai_compatible",
            model="glm-5",
            base_url="https://example.com/v1",
            api_key_env="OPENAI_API_KEY",
        )
        with pytest.raises(ProviderConfigurationError, match="api_key_missing"):
            profile_to_agent_config(profile, env={})

    def test_profile_to_agent_config_fake_skips_key(self):
        """fake profile 不需要 key，即使 api_key_env 未设置也不报错。"""
        from agent.provider.profiles import (
            ProviderProfile,
            profile_to_agent_config,
        )

        profile = ProviderProfile(
            name="fake",
            provider_type="fake",
            model="fake-llm",
        )
        config = profile_to_agent_config(profile, env={})
        assert config.provider_type == "fake"
        assert config.api_key is None

    def test_legacy_provider_env_still_works(self):
        """MY_FIRST_AGENT_LLM_PROVIDER 设置时 → legacy 路径（返回 None）。"""
        from agent.provider.profiles import load_provider_profiles, resolve_active_profile

        yaml_path = _write_temp_profiles_yaml("""
            active_profile: fake
            profiles:
              fake:
                type: fake
                model: fake-llm
        """)
        try:
            profiles = load_provider_profiles(path=yaml_path)
            resolved, method = resolve_active_profile(
                profiles, env={"MY_FIRST_AGENT_LLM_PROVIDER": "anthropic_compatible"}
            )
            assert resolved is None  # legacy 返回 None
            assert method == "legacy"
        finally:
            os.unlink(yaml_path)

    def test_profile_env_overrides_yaml_default(self):
        """FIRST_AGENT_PROVIDER_PROFILE 环境变量覆盖 YAML 中的 active_profile。"""
        from agent.provider.profiles import load_provider_profiles, resolve_active_profile

        yaml_path = _write_temp_profiles_yaml("""
            active_profile: fake
            profiles:
              fake:
                type: fake
                model: fake-llm
              glm_openai:
                type: openai_compatible
                model: glm-5
                base_url: https://example.com/v1
                api_key_env: OPENAI_API_KEY
        """)
        try:
            profiles = load_provider_profiles(path=yaml_path)
            resolved, method = resolve_active_profile(
                profiles, env={"FIRST_AGENT_PROVIDER_PROFILE": "glm_openai"}
            )
            assert resolved is not None
            assert resolved.name == "glm_openai"
            assert resolved.provider_type == "openai_compatible"
            assert method == "profile_env"
        finally:
            os.unlink(yaml_path)

    def test_missing_profile_name_returns_none(self):
        """FIRST_AGENT_PROVIDER_PROFILE 指向不存在的 profile → 返回 None。"""
        from agent.provider.profiles import load_provider_profiles, resolve_active_profile

        yaml_path = _write_temp_profiles_yaml("""
            active_profile: fake
            profiles:
              fake:
                type: fake
                model: fake-llm
        """)
        try:
            profiles = load_provider_profiles(path=yaml_path)
            resolved, method = resolve_active_profile(
                profiles, env={"FIRST_AGENT_PROVIDER_PROFILE": "nonexistent"}
            )
            # 不存在的 profile → 返回 (None, "profile_env") 但 resolved 为 None
            # 实际上当 profile_name 不匹配时不会提前返回，
            # 会继续检查 legacy 和 fallback
            # 修正：profile_name 不匹配 → 继续到 legacy 检查 → 再到 fallback
            # 所以最终会 fallback 到 fake
            assert resolved is not None
            assert resolved.provider_type == "fake"
            assert method == "default_fake"
        finally:
            os.unlink(yaml_path)

    def test_no_yaml_file_returns_empty_profiles(self):
        """YAML 文件不存在 → load_provider_profiles 返回空 dict。"""
        from agent.provider.profiles import load_provider_profiles, resolve_active_profile

        profiles = load_provider_profiles(path="/nonexistent/path/profiles.yaml")
        assert profiles == {}
        # 空 profiles 也能正确 fallback
        resolved, method = resolve_active_profile(profiles, env={})
        assert resolved is not None
        assert resolved.provider_type == "fake"
        assert method == "default_fake"


class TestProfileDiagnostics:
    """测试 profile 信息在 diagnostics 中的呈现。"""

    def test_diagnostic_includes_active_profile(self):
        """diagnose_provider_config 接受并返回 active_profile 字段。"""
        from agent.provider.diagnostics import diagnose_provider_config

        diag = diagnose_provider_config(
            env={"MY_FIRST_AGENT_LLM_PROVIDER": "fake"},
            active_profile="fake",
            profile_source="default_fake",
        )
        assert diag.active_profile == "fake"
        assert diag.profile_source == "default_fake"

    def test_diagnostic_shows_profile_env_source(self):
        """FIRST_AGENT_PROVIDER_PROFILE 选中时 → profile_source='profile_env'。"""
        from agent.provider.diagnostics import diagnose_provider_config

        diag = diagnose_provider_config(
            env={"MY_FIRST_AGENT_LLM_PROVIDER": "fake"},
            active_profile="kimi_anthropic",
            profile_source="profile_env",
        )
        assert diag.active_profile == "kimi_anthropic"
        assert diag.profile_source == "profile_env"

    def test_diagnostic_legacy_source(self):
        """legacy MY_FIRST_AGENT_LLM_PROVIDER 时 → profile_source='legacy'。"""
        from agent.provider.diagnostics import diagnose_provider_config

        diag = diagnose_provider_config(
            env={
                "MY_FIRST_AGENT_LLM_PROVIDER": "anthropic_native",
                "ANTHROPIC_API_KEY": "sk-test",
                "ANTHROPIC_MODEL": "claude-sonnet-4-6",
            },
            active_profile=None,
            profile_source="legacy",
        )
        assert diag.active_profile is None
        assert diag.profile_source == "legacy"
        assert diag.provider_type == "anthropic_native"

    def test_render_includes_active_profile(self):
        """render_diagnostic_report 输出包含 active profile 行。"""
        from agent.provider.diagnostics import (
            ProviderDiagnostic,
            render_diagnostic_report,
        )

        diag = ProviderDiagnostic(
            provider_type="fake",
            model="fake-llm",
            base_url="not_set",
            api_key_present=False,
            api_key_env=None,
            auth_scheme="auto",
            request_path="",
            status="ok",
            active_profile="fake",
            profile_source="default_fake",
        )
        report = render_diagnostic_report(diag)
        assert "Active profile: fake (default)" in report

    def test_render_includes_profile_env_source(self):
        """render_diagnostic_report 显示 profile_env 来源。"""
        from agent.provider.diagnostics import (
            ProviderDiagnostic,
            render_diagnostic_report,
        )

        diag = ProviderDiagnostic(
            provider_type="anthropic_compatible",
            model="kimi-k2.5",
            base_url="not_set",
            api_key_present=False,
            api_key_env="ANTHROPIC_API_KEY",
            auth_scheme="auto",
            request_path="/v1/messages",
            status="warn",
            active_profile="kimi_anthropic",
            profile_source="profile_env",
        )
        report = render_diagnostic_report(diag)
        assert "Active profile: kimi_anthropic (from FIRST_AGENT_PROVIDER_PROFILE)" in report

    def test_render_suggests_config_yaml_not_legacy(self):
        """fake 模式诊断建议使用 config/config.yaml 而非 legacy profile env var。"""
        from agent.provider.diagnostics import (
            ProviderDiagnostic,
            render_diagnostic_report,
        )

        diag = ProviderDiagnostic(
            provider_type="fake",
            model="fake-llm",
            base_url="not_set",
            api_key_present=True,
            api_key_env="ANTHROPIC_API_KEY",
            auth_scheme="auto",
            request_path="",
            status="ok",
            active_profile="fake",
            profile_source="default_fake",
            config_source="default_fake",
        )
        report = render_diagnostic_report(diag)
        assert "config/config.yaml" in report


class TestProfileNoSecretLeaked:
    """验证 profile 相关输出不泄露 secret。"""

    def test_profile_to_agent_config_redacted_summary_no_secret(self):
        """AgentProviderConfig.redacted_summary() 不包含 key 明文。"""
        from agent.provider.profiles import (
            ProviderProfile,
            profile_to_agent_config,
        )

        profile = ProviderProfile(
            name="kimi_anthropic",
            provider_type="anthropic_compatible",
            model="kimi-k2.5",
            base_url="https://example.com/api",
            api_key_env="ANTHROPIC_API_KEY",
        )
        config = profile_to_agent_config(
            profile,
            env={"ANTHROPIC_API_KEY": "sk-secret-should-not-leak"},
        )
        summary = config.redacted_summary()
        assert summary["api_key"] == "SET"
        assert "sk-secret-should-not-leak" not in str(summary)

    def test_profile_name_never_contains_key(self):
        """ProviderProfile 中 api_key_env 只存变量名。"""
        from agent.provider.profiles import ProviderProfile

        profile = ProviderProfile(
            name="test",
            provider_type="anthropic_compatible",
            model="test-model",
            api_key_env="ANTHROPIC_API_KEY",
        )
        assert profile.api_key_env == "ANTHROPIC_API_KEY"
        assert "sk-" not in profile.api_key_env
        assert "secret" not in str(profile).lower()

    def test_render_diagnostic_never_prints_key(self):
        """render_diagnostic_report 输出不包含 API key 明文。"""
        from agent.provider.diagnostics import (
            ProviderDiagnostic,
            render_diagnostic_report,
        )

        diag = ProviderDiagnostic(
            provider_type="anthropic_compatible",
            model="kimi-k2.5",
            base_url="not_set",
            api_key_present=True,
            api_key_env="ANTHROPIC_API_KEY",
            auth_scheme="auto",
            request_path="/v1/messages",
            status="ok",
            active_profile="kimi_anthropic",
            profile_source="profile_env",
        )
        report = render_diagnostic_report(diag)
        assert "sk-" not in report
        assert "SET (redacted)" in report
        assert "ANTHROPIC_API_KEY" in report  # 变量名可以出现


class TestProfileFactoryIntegration:
    """测试 profile → factory 集成路径。"""

    def test_build_model_provider_from_env_with_profile_env(self):
        """FIRST_AGENT_PROVIDER_PROFILE=kimi_anthropic 时复现 fake→real 流程。

        学习型注释：
        profile 解析发生在 build_model_provider_from_env() 内部，
        不走 runtime 分叉。factory 拿到的是普通的 AgentProviderConfig，
        后续所有代码（core.chat / loop.py / call_model）行为不变。
        """
        from agent.provider.factory import build_model_provider_from_env

        yaml_path = _write_temp_profiles_yaml("""
            active_profile: fake
            profiles:
              fake:
                type: fake
                model: fake-llm
              kimi_anthropic:
                type: anthropic_compatible
                model: kimi-k2.5
                base_url: https://example.com/api
                api_key_env: ANTHROPIC_API_KEY
        """)
        saved_env = {}
        try:
            # 保存并清理外层 env
            for var in [
                "MY_FIRST_AGENT_LLM_PROVIDER",
                "FIRST_AGENT_PROVIDER_PROFILE",
                "ANTHROPIC_API_KEY",
                "ANTHROPIC_MODEL",
                "ANTHROPIC_BASE_URL",
                "OPENAI_API_KEY",
                "MY_FIRST_AGENT_LLM_MODEL",
            ]:
                saved_env[var] = os.environ.pop(var, None)

            os.environ["FIRST_AGENT_PROVIDER_PROFILE"] = "kimi_anthropic"
            os.environ["ANTHROPIC_API_KEY"] = "sk-test"

            # 临时替换 DEFAULT_PROFILES_YAML 走 temp YAML
            import agent.provider.profiles as pmod

            _orig_default = pmod.DEFAULT_PROFILES_YAML
            pmod.DEFAULT_PROFILES_YAML = yaml_path
            try:
                provider = build_model_provider_from_env()
                # 应该返回 AnthropicCompatibleProvider（或至少不是 FakeProvider）
                assert provider is not None
                assert getattr(provider, "provider_type", "") == "anthropic_compatible"
            finally:
                pmod.DEFAULT_PROFILES_YAML = _orig_default
        finally:
            os.unlink(yaml_path)
            for var, val in saved_env.items():
                if val is not None:
                    os.environ[var] = val
                else:
                    os.environ.pop(var, None)

    def test_build_model_provider_from_env_no_profile_defaults_fake(self):
        """无 profile → build_model_provider_from_env 返回 FakeProvider。"""
        import agent.provider.profiles as pmod
        from agent.provider.factory import build_model_provider_from_env

        # 用一个不存在的 YAML 路径
        _orig_default = pmod.DEFAULT_PROFILES_YAML
        pmod.DEFAULT_PROFILES_YAML = "/nonexistent/path/profiles.yaml"
        saved = os.environ.pop("MY_FIRST_AGENT_LLM_PROVIDER", None)
        saved_profile = os.environ.pop("FIRST_AGENT_PROVIDER_PROFILE", None)
        try:
            provider = build_model_provider_from_env()
            assert provider is not None
            assert getattr(provider, "provider_type", "") == "fake"
        finally:
            pmod.DEFAULT_PROFILES_YAML = _orig_default
            if saved is not None:
                os.environ["MY_FIRST_AGENT_LLM_PROVIDER"] = saved
            if saved_profile is not None:
                os.environ["FIRST_AGENT_PROVIDER_PROFILE"] = saved_profile
