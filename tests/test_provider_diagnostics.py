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
from pathlib import Path

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
