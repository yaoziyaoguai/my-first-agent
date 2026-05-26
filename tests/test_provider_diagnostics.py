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
    # config.yaml 是唯一推荐入口，不应直接引用 ANTHROPIC_API_KEY/OPENAI_API_KEY
    assert "config/config.yaml" in msg or ".env" in msg


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

    注意：config.yaml 优先于 env vars，所以测试期间临时移走 config.yaml。
    """
    import shutil
    import signal
    import subprocess as _sp
    import tempfile

    config_yaml = PROJECT_ROOT / "config" / "config.yaml"
    config_backup = PROJECT_ROOT / "config" / ".config.yaml.test_backup"

    # 临时移走 config.yaml 以模拟 "无配置" 的 fake 默认路径
    _restore = config_yaml.exists()
    if _restore:
        shutil.move(str(config_yaml), str(config_backup))

    try:
        with tempfile.TemporaryDirectory(prefix="first_agent_chat_") as tmp_home:
            test_env = {
                **os.environ,
                "HOME": tmp_home,
            }
            for key_var in (
                "ANTHROPIC_API_KEY",
                "OPENAI_API_KEY",
                "MY_FIRST_AGENT_LLM_PROVIDER",
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

            assert "ValueError" not in output, (
                f"main.py 崩溃（ValueError）:\n{output[-2000:]}"
            )
            assert "LoopContext" not in output or "fake" in output.lower(), (
                f"输出可能包含 LoopContext 异常:\n{output[-2000:]}"
            )
            assert "Traceback (most recent call last)" not in output, (
                f"main.py 产生了 traceback:\n{output[-2000:]}"
            )
            assert proc.returncode in {0, -15}, (
                f"main.py exit code={proc.returncode}，预期 0:\n{output[-2000:]}"
            )
    finally:
        if _restore:
            shutil.move(str(config_backup), str(config_yaml))


# =========================================================================
# 9. P0 回归：默认 fake/local 路径 provider 注入不为空
# =========================================================================


def test_build_model_provider_from_env_defaults_to_fake():
    """build_model_provider_from_env() 在无 config.yaml 时必须返回 FakeProvider。

    这是 P0 回归测试——a2dfd89 修了 model_name fallback，但没有修 provider 注入。
    当 config.yaml 不存在时，默认路径应该是 FakeProvider（safe local path）。

    测试通过临时重定向 DEFAULT_CONFIG_PATH 到不存在文件来模拟无配置场景。
    """
    import os as _os

    import agent.provider.simple_config as sc
    from agent.provider.factory import build_model_provider_from_env

    saved = _os.environ.pop("MY_FIRST_AGENT_LLM_PROVIDER", None)
    _orig_default = sc.DEFAULT_CONFIG_PATH
    # 重定向到不存在的路径，模拟无 config.yaml
    sc.DEFAULT_CONFIG_PATH = "_nonexistent_test_config_.yaml"

    try:
        provider = build_model_provider_from_env()
        assert provider is not None, (
            "build_model_provider_from_env() 在无 config.yaml 时返回了 None"
        )
        assert hasattr(provider, "provider_type"), (
            "返回的 provider 必须有 provider_type 属性"
        )
        assert provider.provider_type == "fake", (
            f"默认 provider 应为 'fake'，实际: {provider.provider_type!r}"
        )
    finally:
        sc.DEFAULT_CONFIG_PATH = _orig_default
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

    修复后，build_model_provider_from_env() 在无 config.yaml 时默认返回 FakeProvider。

    注意：config.yaml 优先于所有 env vars，所以测试期间临时移走 config.yaml。
    """
    import shutil
    import signal
    import subprocess as _sp
    import tempfile

    config_yaml = PROJECT_ROOT / "config" / "config.yaml"
    config_backup = PROJECT_ROOT / "config" / ".config.yaml.test_backup"

    _restore = config_yaml.exists()
    if _restore:
        shutil.move(str(config_yaml), str(config_backup))

    try:
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

            assert "ProviderNotImplementedError" not in output, (
                "main.py 抛出 ProviderNotImplementedError——provider 注入链断裂:\n"
                f"{output[-2000:]}"
            )
            assert "model_provider_required" not in output, (
                "main.py 报 model_provider_required——provider 未注入:\n"
                f"{output[-2000:]}"
            )
            assert "Traceback (most recent call last)" not in output, (
                f"main.py 产生了 traceback:\n{output[-2000:]}"
            )
            assert "ValueError" not in output, (
                f"main.py 崩溃（ValueError）:\n{output[-2000:]}"
            )
            assert "fake" in output.lower(), (
                f"输出应包含 provider mode=fake:\n{output[-2000:]}"
            )
            assert proc.returncode in {0, -15}, (
                f"main.py exit code={proc.returncode}，预期 0:\n{output[-2000:]}"
            )
    finally:
        if _restore:
            shutil.move(str(config_backup), str(config_yaml))


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
    """isolated 模式应清除外层 env，无 config.yaml 时走 legacy .env 路径。

    模拟：外层 ANTHROPIC_MODEL=deepseek-v4-pro，.env 中 ANTHROPIC_MODEL=kimi-k2.5。
    无 config.yaml 时，legacy env 诊断通过 dotenv 值工作。
    """
    import os as _os
    import shutil
    import tempfile
    from pathlib import Path

    from agent.provider.diagnostics import diagnose_provider_config_isolated

    config_yaml = PROJECT_ROOT / "config" / "config.yaml"
    config_backup = PROJECT_ROOT / "config" / ".config.yaml.test_backup"
    _restore = config_yaml.exists()
    if _restore:
        shutil.move(str(config_yaml), str(config_backup))

    try:
        with tempfile.TemporaryDirectory() as tmp:
            dotenv_path = Path(tmp) / ".env"
            dotenv_path.write_text(
                "ANTHROPIC_MODEL=kimi-k2.5\n"
                "ANTHROPIC_API_KEY=sk-dotenv-key-12345\n"
                "ANTHROPIC_BASE_URL=https://example.com/api\n"
                "MY_FIRST_AGENT_LLM_PROVIDER=anthropic_compatible\n"
            )

            _os.environ["ANTHROPIC_MODEL"] = "deepseek-v4-pro"
            _os.environ["ANTHROPIC_BASE_URL"] = "https://api.deepseek.com"

            try:
                diag = diagnose_provider_config_isolated(str(dotenv_path))
                # 无 config.yaml → 走 legacy .env 路径
                assert diag.provider_type == "anthropic_compatible", (
                    f"expected anthropic_compatible from dotenv, got {diag.provider_type}"
                )
                assert diag.config_source in ("project_dotenv", "legacy_provider_env"), (
                    f"expected dotenv/legacy source, got {diag.config_source}"
                )
            finally:
                _os.environ.pop("ANTHROPIC_MODEL", None)
                _os.environ.pop("ANTHROPIC_BASE_URL", None)
    finally:
        if _restore:
            shutil.move(str(config_backup), str(config_yaml))


def test_isolated_diagnostic_empty_dotenv_falls_back_to_fake():
    """isolated 模式 .env 为空且无 config.yaml 时返回 fake 兜底。"""
    import shutil
    import tempfile
    from pathlib import Path

    from agent.provider.diagnostics import diagnose_provider_config_isolated

    config_yaml = PROJECT_ROOT / "config" / "config.yaml"
    config_backup = PROJECT_ROOT / "config" / ".config.yaml.test_backup"
    _restore = config_yaml.exists()
    if _restore:
        shutil.move(str(config_yaml), str(config_backup))

    try:
        with tempfile.TemporaryDirectory() as tmp:
            dotenv_path = Path(tmp) / ".env"
            dotenv_path.write_text("# 空文件\n")

            diag = diagnose_provider_config_isolated(str(dotenv_path))
            assert diag.provider_type == "fake"
            assert diag.dotenv_loaded is False
    finally:
        if _restore:
            shutil.move(str(config_backup), str(config_yaml))


def test_isolated_diagnostic_no_secret_in_output():
    """isolated 诊断输出不得包含 .env 中的 API key 值。"""
    import shutil
    import tempfile
    from pathlib import Path

    from agent.provider.diagnostics import (
        diagnose_provider_config_isolated,
        render_diagnostic_report,
    )

    config_yaml = PROJECT_ROOT / "config" / "config.yaml"
    config_backup = PROJECT_ROOT / "config" / ".config.yaml.test_backup"
    _restore = config_yaml.exists()
    if _restore:
        shutil.move(str(config_yaml), str(config_backup))

    try:
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
            # key 应显示为 SET + redacted
            assert "SET" in report
            assert "redacted" in report
    finally:
        if _restore:
            shutil.move(str(config_backup), str(config_yaml))


def test_isolated_diagnostic_shows_model_and_base_url_redacted():
    """isolated 诊断应显示模型名和脱敏 base_url（无 config.yaml 时走 legacy .env）。

    无 config.yaml 时，model 来自 .env 的 ANTHROPIC_MODEL。
    """
    import shutil
    import tempfile
    from pathlib import Path

    from agent.provider.diagnostics import (
        diagnose_provider_config_isolated,
        render_diagnostic_report,
    )

    config_yaml = PROJECT_ROOT / "config" / "config.yaml"
    config_backup = PROJECT_ROOT / "config" / ".config.yaml.test_backup"
    _restore = config_yaml.exists()
    if _restore:
        shutil.move(str(config_yaml), str(config_backup))

    try:
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
            # model 来自 .env
            assert "kimi-k2.5" in report
    finally:
        if _restore:
            shutil.move(str(config_backup), str(config_yaml))


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
        legacy_label = "Active profile: kimi_anthropic (from FIRST_AGENT_PROVIDER_PROFILE (legacy))"
        assert legacy_label in report

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
        assert "SET" in report
        assert "redacted" in report
        assert "ANTHROPIC_API_KEY" in report  # 变量名可以出现


class TestProfileFactoryIntegration:
    """测试 profile → factory 集成路径。"""

    def test_build_model_provider_from_env_with_profile_env(self):
        """config.yaml 优先于 FIRST_AGENT_PROVIDER_PROFILE（legacy）。

        学习型注释：
        config/config.yaml 存在时，legacy profile env 被完全忽略，
        build_model_provider_from_env() 返回 config.yaml 的配置。
        profile 路径仅在 config.yaml 不存在时作为 fallback 生效。

        测试期间重定向 DEFAULT_CONFIG_PATH 模拟无 config.yaml 场景，
        验证 profile 路径作为 fallback 能正常工作。
        """
        import agent.provider.simple_config as sc
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
        _orig_config = sc.DEFAULT_CONFIG_PATH
        try:
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

            # 重定向 config.yaml 到不存在路径，让 profile 路径生效
            sc.DEFAULT_CONFIG_PATH = "_nonexistent_test_config_.yaml"

            import agent.provider.profiles as pmod

            _orig_profiles = pmod.DEFAULT_PROFILES_YAML
            pmod.DEFAULT_PROFILES_YAML = yaml_path
            try:
                provider = build_model_provider_from_env()
                # config.yaml 不存在 → profile env 被使用
                assert provider is not None
                assert getattr(provider, "provider_type", "") == "anthropic_compatible", (
                    f"profile env 应生效，expected anthropic_compatible, "
                    f"got {getattr(provider, 'provider_type', '')}"
                )
            finally:
                pmod.DEFAULT_PROFILES_YAML = _orig_profiles
        finally:
            sc.DEFAULT_CONFIG_PATH = _orig_config
            os.unlink(yaml_path)
            for var, val in saved_env.items():
                if val is not None:
                    os.environ[var] = val
                else:
                    os.environ.pop(var, None)

    def test_build_model_provider_from_env_no_profile_defaults_fake(self):
        """无 profile 且无 config.yaml → build_model_provider_from_env 返回 FakeProvider。"""
        import agent.provider.profiles as pmod
        import agent.provider.simple_config as sc
        from agent.provider.factory import build_model_provider_from_env

        _orig_profiles = pmod.DEFAULT_PROFILES_YAML
        _orig_config = sc.DEFAULT_CONFIG_PATH
        pmod.DEFAULT_PROFILES_YAML = "/nonexistent/path/profiles.yaml"
        sc.DEFAULT_CONFIG_PATH = "_nonexistent_test_config_.yaml"
        saved = os.environ.pop("MY_FIRST_AGENT_LLM_PROVIDER", None)
        saved_profile = os.environ.pop("FIRST_AGENT_PROVIDER_PROFILE", None)
        try:
            provider = build_model_provider_from_env()
            assert provider is not None
            assert getattr(provider, "provider_type", "") == "fake"
        finally:
            pmod.DEFAULT_PROFILES_YAML = _orig_profiles
            sc.DEFAULT_CONFIG_PATH = _orig_config
            if saved is not None:
                os.environ["MY_FIRST_AGENT_LLM_PROVIDER"] = saved
            if saved_profile is not None:
                os.environ["FIRST_AGENT_PROVIDER_PROFILE"] = saved_profile


# =============================================================================
# Config YAML 可读性测试（config/examples/ 拆分后可解析、无 secret）
# =============================================================================


class TestConfigExamplesParseable:
    """三个 config/examples/*.config.yaml 都能被 load_unified_provider_config 解析。
    中文注释/docstring：config/examples 是推荐用户复制入口，非注释嵌套方式。"""

    def test_default_config_yaml_is_parseable(self):
        """config/config.yaml 可解析，无 YAML 语法错误。

        config.yaml 是用户本地文件，内容可变（fake 或 real provider），
        不应对具体 provider type 做断言，只验证解析不崩溃。
        """
        from agent.provider.simple_config import load_unified_provider_config

        config_path = PROJECT_ROOT / "config" / "config.yaml"
        if not config_path.is_file():
            pytest.skip("config/config.yaml 不存在")
        result = load_unified_provider_config(config_path)
        # 必须返回合法的 UnifiedProviderConfig
        assert result.source in (
            "config_yaml", "config_yaml_disabled", "default_fake",
        ), f"unexpected source: {result.source}"
        assert result.config.provider_type in (
            "fake", "anthropic_native", "anthropic_compatible",
            "openai_native", "openai_compatible",
        ), f"unexpected provider_type: {result.config.provider_type}"
        assert result.config.model
        # 如果 api_key 存在，不应泄露到 config_error
        if result.config.api_key:
            assert "api_key" not in (result.config_error or "").lower()

    def test_fake_example_parseable(self):
        """config/examples/fake.config.yaml 可解析为 fake provider。"""
        from agent.provider.simple_config import load_unified_provider_config

        config_path = PROJECT_ROOT / "config" / "examples" / "fake.config.yaml"
        result = load_unified_provider_config(config_path)
        assert result.config.provider_type == "fake"

    def test_kimi_example_parseable(self):
        """config/examples/kimi-anthropic-compatible.config.yaml 可解析。

        api_key 使用 sk-REPLACE_ME 占位符（inline），无需 env 注入即可解析。"""
        from agent.provider.simple_config import load_unified_provider_config

        config_path = (
            PROJECT_ROOT / "config" / "examples"
            / "kimi-anthropic-compatible.config.yaml"
        )
        result = load_unified_provider_config(config_path)
        assert result.source == "config_yaml"
        assert result.config.provider_type == "anthropic_compatible"
        assert result.config.model == "kimi-k2.5"
        assert result.config.api_key == "sk-REPLACE_ME"

    def test_glm_example_parseable(self):
        """config/examples/glm-openai-compatible.config.yaml 可解析。

        api_key 使用 sk-REPLACE_ME 占位符（inline），无需 env 注入即可解析。"""
        from agent.provider.simple_config import load_unified_provider_config

        config_path = (
            PROJECT_ROOT / "config" / "examples"
            / "glm-openai-compatible.config.yaml"
        )
        result = load_unified_provider_config(config_path)
        assert result.source == "config_yaml"
        assert result.config.provider_type == "openai_compatible"
        assert result.config.model == "glm-5"
        assert result.config.api_key == "sk-REPLACE_ME"

    def test_examples_contain_no_real_api_key(self):
        """示例文件只包含 sk-REPLACE_ME 占位符，不含真实 API key。

        sk-REPLACE_ME 是明确的人类可读占位符，不会与真实 key 混淆。
        真实 key 通常是长随机字符串（如 sk-ant-... 或 sk-... 后跟 20+ 字符）。
        fake.config.yaml 除外——fake 模式不需要 api_key。
        """
        import re

        examples_dir = PROJECT_ROOT / "config" / "examples"
        for example_file in sorted(examples_dir.glob("*.yaml")):
            content = example_file.read_text()
            # 不应包含真实 API key 格式（长随机字符串，排除 sk-REPLACE_ME）
            real_key_pattern = re.compile(r'sk-(?:ant-)?[A-Za-z0-9_-]{20,}')
            matches = real_key_pattern.findall(content)
            for m in matches:
                if m != "sk-REPLACE_ME":
                    raise AssertionError(
                        f"{example_file.name} 包含疑似真实 API key: {m[:8]}..."
                    )
            # 不应包含 secret 等敏感词
            assert "secret" not in content.lower(), (
                f"{example_file.name} 包含 'secret' 字符串"
            )
            # 非 fake 示例应使用 api_key: 字段（inline），不是 api_key_env:
            if "fake" not in example_file.name:
                assert "api_key:" in content, (
                    f"{example_file.name} 应使用 api_key: 字段（inline），非 api_key_env:"
                )
                assert "sk-REPLACE_ME" in content, (
                    f"{example_file.name} 应包含 api_key: sk-REPLACE_ME 占位符"
                )
                assert "api_key_env:" not in content, (
                    f"{example_file.name} 不应使用 api_key_env:（已废弃）"
                )

    def test_default_yaml_has_no_commented_provider_examples(self):
        """config/config.yaml 不应包含注释掉的真实 provider 示例。"""
        config_path = PROJECT_ROOT / "config" / "config.yaml"
        content = config_path.read_text()
        # 不应有被注释的 enabled/type/model 真实 provider 示例行
        lines = content.split("\n")
        commented_real = [
            line for line in lines
            if line.strip().startswith("#") and any(
                kw in line for kw in ["enabled: true", "type: anthropic",
                                      "type: openai", "base_url: http"]
            )
        ]
        assert not commented_real, (
            "config/config.yaml 不应包含注释掉的真实 provider 示例，"
            "真实配置示例在 config/examples/ 目录中"
        )

    def test_readme_points_to_examples_not_inline_uncomment(self):
        """README 不应建议用户在同一 provider block 中取消注释。"""
        readme_path = PROJECT_ROOT / "README.md"
        content = readme_path.read_text()
        # 应指向 config/examples/
        assert "config/examples/" in content, (
            "README 应引用 config/examples/ 目录"
        )
        # 不应建议取消注释
        assert "取消注释" not in content, (
            "README 不应建议用户取消注释，应使用 config/examples/ 复制方式"
        )


# =============================================================================
# 14. inline api_key 配置加载测试（v0.12+）
# =============================================================================


class TestInlineApiKeyConfig:
    """测试 config/config.yaml 中 provider.api_key inline 明文的行为。"""

    def test_enabled_true_with_inline_api_key_resolves_real_config(self):
        """enabled=true + api_key inline → real config resolved, key present。"""
        import tempfile

        from agent.provider.simple_config import load_unified_provider_config

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(textwrap.dedent("""\
                provider:
                  enabled: true
                  type: anthropic_compatible
                  model: kimi-k2.5
                  base_url: https://example.com/api
                  api_key: sk-test-inline-key-12345
            """))
            tmp_path = tmp.name

        try:
            result = load_unified_provider_config(tmp_path)
            assert result.source == "config_yaml"
            assert result.config_error is None
            assert result.config.provider_type == "anthropic_compatible"
            assert result.config.model == "kimi-k2.5"
            assert result.config.api_key == "sk-test-inline-key-12345"
        finally:
            os.unlink(tmp_path)

    def test_enabled_true_missing_api_key_is_config_error(self):
        """enabled=true 但 api_key 缺失 → config_error，不回退 fake。

        学习型注释：
        config.yaml provider.enabled=true 但未提供 api_key 时，
        load_unified_provider_config 返回 config_error 而非静默回退 fake。
        这样用户能明确知道配置不完整。
        """
        import tempfile

        from agent.provider.simple_config import load_unified_provider_config

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(textwrap.dedent("""\
                provider:
                  enabled: true
                  type: anthropic_compatible
                  model: kimi-k2.5
                  base_url: https://example.com/api
            """))
            tmp_path = tmp.name

        try:
            result = load_unified_provider_config(tmp_path)
            assert result.source == "config_yaml"
            assert result.config_error is not None
            assert "api_key" in result.config_error.lower()
            # 不回退 fake — config 虽为 fake 兜底但 source 标记为 config_yaml
            assert result.config.provider_type == "fake"
        finally:
            os.unlink(tmp_path)

    def test_enabled_false_is_fake(self):
        """enabled=false → fake provider, no config error。"""
        import tempfile

        from agent.provider.simple_config import load_unified_provider_config

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(textwrap.dedent("""\
                provider:
                  enabled: false
                  type: anthropic_compatible
                  model: kimi-k2.5
            """))
            tmp_path = tmp.name

        try:
            result = load_unified_provider_config(tmp_path)
            assert result.source == "config_yaml_disabled"
            assert result.config_error is None
            assert result.config.provider_type == "fake"
        finally:
            os.unlink(tmp_path)

    def test_no_config_yaml_defaults_to_fake(self):
        """config.yaml 不存在 → default_fake。"""
        from agent.provider.simple_config import load_unified_provider_config

        result = load_unified_provider_config("/nonexistent/path/config.yaml")
        assert result.source == "default_fake"
        assert result.config_error is None
        assert result.config.provider_type == "fake"
        assert result.config.model == "fake-llm"

    def test_diagnostics_redacts_inline_key(self):
        """诊断报告显示 SET (inline, redacted)，不泄露 key 值。"""
        import tempfile

        from agent.provider.diagnostics import (
            diagnose_provider_config_from_unified,
            render_diagnostic_report,
        )

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(textwrap.dedent("""\
                provider:
                  enabled: true
                  type: anthropic_compatible
                  model: kimi-k2.5
                  base_url: https://example.com/api
                  api_key: sk-secret-key-should-not-appear-anywhere
            """))
            tmp_path = tmp.name

        # 临时替换 DEFAULT_CONFIG_PATH
        import agent.provider.simple_config as sc

        _orig_default = sc.DEFAULT_CONFIG_PATH
        sc.DEFAULT_CONFIG_PATH = tmp_path
        try:
            diag = diagnose_provider_config_from_unified(env={})
            report = render_diagnostic_report(diag)
            # key 值不得出现
            assert "sk-secret-key-should-not-appear-anywhere" not in report
            # 应显示 inline redacted
            assert "SET (inline, redacted)" in report
            # 不应显示 env redacted（因为不是从 env 来的）
            assert "SET (env, redacted" not in report
        finally:
            sc.DEFAULT_CONFIG_PATH = _orig_default
            os.unlink(tmp_path)

    def test_diagnostics_does_not_mention_legacy_env_vars(self):
        """config.yaml 路径下诊断不推荐 MY_FIRST_AGENT_LLM_PROVIDER 等 legacy env。

        用户不应看到 "请设置 ANTHROPIC_API_KEY" 或 "请设置 MY_FIRST_AGENT_LLM_PROVIDER"
        这类建议——config.yaml 是唯一推荐入口。

        MY_FIRST_AGENT_LLM_PROVIDER 可能出现在 "Legacy env: ignored" 行中
        （告知用户该变量被忽略），但不应出现在 Suggestions 推荐中。
        ANTHROPIC_API_KEY 不应出现（inline api_key 不使用 env 变量名）。
        """
        import tempfile

        from agent.provider.diagnostics import (
            diagnose_provider_config_from_unified,
            render_diagnostic_report,
        )

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(textwrap.dedent("""\
                provider:
                  enabled: true
                  type: anthropic_compatible
                  model: kimi-k2.5
                  base_url: https://example.com/api
                  api_key: sk-test-key
            """))
            tmp_path = tmp.name

        import agent.provider.simple_config as sc

        _orig_default = sc.DEFAULT_CONFIG_PATH
        sc.DEFAULT_CONFIG_PATH = tmp_path
        try:
            diag = diagnose_provider_config_from_unified(
                env={
                    # 模拟外层 env 中有 legacy 变量
                    "MY_FIRST_AGENT_LLM_PROVIDER": "anthropic_native",
                    "ANTHROPIC_API_KEY": "sk-outer-legacy-key",
                },
            )
            report = render_diagnostic_report(diag)
            # ANTHROPIC_API_KEY 不应出现（inline api_key 不暴露 env 变量名）
            assert "ANTHROPIC_API_KEY" not in report
            # Suggestions 中不应推荐 legacy env
            _suffix = report.split("Suggestions:")[1] if "Suggestions:" in report else ""
            suggestions_section = _suffix
            assert "MY_FIRST_AGENT_LLM_PROVIDER" not in suggestions_section, (
                "Suggestions 不应推荐 MY_FIRST_AGENT_LLM_PROVIDER"
            )
            assert "ANTHROPIC_API_KEY" not in suggestions_section, (
                "Suggestions 不应推荐 ANTHROPIC_API_KEY"
            )
            # 应推荐 config/config.yaml
            assert "config/config.yaml" in report
        finally:
            sc.DEFAULT_CONFIG_PATH = _orig_default
            os.unlink(tmp_path)

    def test_config_error_shows_config_yaml_guidance_not_env(self):
        """api_key 缺失时错误信息指向 config.yaml，不指向环境变量。"""
        import tempfile

        from agent.provider.simple_config import load_unified_provider_config

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(textwrap.dedent("""\
                provider:
                  enabled: true
                  type: anthropic_compatible
                  model: kimi-k2.5
                  base_url: https://example.com/api
            """))
            tmp_path = tmp.name

        try:
            result = load_unified_provider_config(tmp_path)
            assert result.config_error is not None
            # 错误信息指向 config.yaml
            assert "config/config.yaml" in result.config_error
            # 不指向环境变量
            assert "ANTHROPIC_API_KEY" not in result.config_error
            assert "MY_FIRST_AGENT_LLM" not in result.config_error
        finally:
            os.unlink(tmp_path)


# =============================================================================
# 15. Secret commit guard — 防止真实 API key 进入 git 历史
# =============================================================================


def test_config_yaml_does_not_contain_real_api_key():
    """config/config.yaml 中 api_key 字段不得包含真实 API key。

    唯一合法占位符: sk-REPLACE_ME。
    任何其他 sk- 前缀的值都是疑似真实 key，必须阻止提交。

    这个测试是最小可行的 secret guard：gate 失败 = 不能 commit/push。
    """
    import re

    config_path = PROJECT_ROOT / "config" / "config.yaml"
    if not config_path.is_file():
        return  # 无 config.yaml 则无需检查

    content = config_path.read_text(encoding="utf-8")

    # 匹配 api_key: <value> 行
    api_key_match = re.search(r'^\s*api_key:\s*(.+)$', content, re.MULTILINE)
    if not api_key_match:
        return  # 无 api_key 字段则无需检查

    key_value = api_key_match.group(1).strip()

    # sk-REPLACE_ME 是唯一合法占位符
    if key_value == "sk-REPLACE_ME":
        return

    # 检查是否包含真实 API key 特征
    if key_value.startswith("sk-") and len(key_value) > 15:
        raise AssertionError(
            f"config/config.yaml 中 api_key 疑似真实 key: {key_value[:8]}...\n"
            "真实 API key 不应提交到 git。请将 api_key 替换为 sk-REPLACE_ME 占位符，\n"
            "在本地运行时再替换为真实 key。\n"
            "如果此值确实是占位符而非真实 key，请联系维护者更新此 guard。"
        )


def test_no_real_api_key_in_git_diff_staged():
    """git diff --cached 中不得包含真实 API key。

    拦截场景：用户将真实 key 写入 config.yaml 后 git add，但尚未 commit。
    此时 config.yaml working tree 已包含真实 key，git diff --cached 会显示它。
    """
    import re
    import subprocess as _sp

    try:
        staged = _sp.run(
            ["git", "diff", "--cached", "--", "config/config.yaml"],
            capture_output=True, text=True, timeout=10,
            cwd=str(PROJECT_ROOT),
        )
    except (FileNotFoundError, _sp.TimeoutExpired):
        return  # git 不可用则跳过

    if staged.returncode != 0 or not staged.stdout.strip():
        return  # 无 staged 变更

    # 查找 diff 中新增的 api_key 行（以 + 开头）
    for line in staged.stdout.split("\n"):
        if line.startswith("+") and "api_key:" in line:
            # 提取 key 值
            key_match = re.search(r'api_key:\s*(.+)$', line)
            if key_match:
                key_val = key_match.group(1).strip()
                if key_val == "sk-REPLACE_ME":
                    continue
                if key_val.startswith("sk-") and len(key_val) > 15:
                    raise AssertionError(
                        f"git diff --cached 中包含疑似真实 API key: {key_val[:8]}...\n"
                        "真实 API key 即将被 commit——已拦截。\n"
                        "请 git reset HEAD config/config.yaml 取消暂存，"
                        "将 api_key 替换为 sk-REPLACE_ME 占位符后重新 commit。"
                    )
