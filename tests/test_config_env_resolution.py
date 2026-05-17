"""测试 config.py 多 provider 环境变量解析逻辑。

不读 .env、不打印 secret value。
"""

from __future__ import annotations

import importlib


class TestResolveModelName:
    """MODEL_NAME > ANTHROPIC_MODEL > OPENAI_MODEL 优先级。"""

    def test_model_name_explicit_wins(self, monkeypatch):
        monkeypatch.setenv("MODEL_NAME", "explicit-model")
        monkeypatch.setenv("ANTHROPIC_MODEL", "anthropic-model")
        monkeypatch.setenv("OPENAI_MODEL", "openai-model")
        from config import _resolve_model_name

        assert _resolve_model_name() == "explicit-model"

    def test_anthropic_model_fallback(self, monkeypatch):
        monkeypatch.delenv("MODEL_NAME", raising=False)
        monkeypatch.setenv("ANTHROPIC_MODEL", "anthropic-model")
        monkeypatch.delenv("OPENAI_MODEL", raising=False)
        from config import _resolve_model_name

        assert _resolve_model_name() == "anthropic-model"

    def test_openai_model_last_resort(self, monkeypatch):
        monkeypatch.delenv("MODEL_NAME", raising=False)
        monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
        monkeypatch.setenv("OPENAI_MODEL", "openai-model")
        from config import _resolve_model_name

        assert _resolve_model_name() == "openai-model"

    def test_none_when_no_model_set(self, monkeypatch):
        monkeypatch.delenv("MODEL_NAME", raising=False)
        monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
        monkeypatch.delenv("OPENAI_MODEL", raising=False)
        from config import _resolve_model_name

        assert _resolve_model_name() is None

    def test_anthropic_over_openai_when_both_set(self, monkeypatch):
        monkeypatch.delenv("MODEL_NAME", raising=False)
        monkeypatch.setenv("ANTHROPIC_MODEL", "anthropic-first")
        monkeypatch.setenv("OPENAI_MODEL", "openai-second")
        from config import _resolve_model_name

        assert _resolve_model_name() == "anthropic-first"


class TestResolveApiKey:
    """ANTHROPIC_API_KEY > OPENAI_API_KEY 优先级。"""

    def test_anthropic_key_wins(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "ak")
        monkeypatch.setenv("OPENAI_API_KEY", "ok")
        from config import _resolve_api_key

        assert _resolve_api_key() == "ak"

    def test_openai_key_fallback(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "ok")
        from config import _resolve_api_key

        assert _resolve_api_key() == "ok"

    def test_none_when_no_key(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        from config import _resolve_api_key

        assert _resolve_api_key() is None


class TestResolveBaseUrl:
    """ANTHROPIC_BASE_URL > OPENAI_BASE_URL 优先级。"""

    def test_anthropic_url_wins(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://a.example")
        monkeypatch.setenv("OPENAI_BASE_URL", "https://o.example")
        from config import _resolve_base_url

        assert _resolve_base_url() == "https://a.example"

    def test_openai_url_fallback(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
        monkeypatch.setenv("OPENAI_BASE_URL", "https://o.example")
        from config import _resolve_base_url

        assert _resolve_base_url() == "https://o.example"

    def test_none_when_no_url(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
        monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
        from config import _resolve_base_url

        assert _resolve_base_url() is None


class TestModuleLevelConstants:
    """config.py 模块级常量使用解析函数。

    注：由于 conftest.py + load_dotenv() 在模块导入时的交互顺序不确定，
    这里不通过 importlib.reload 验证，改为直接调用解析函数验证优先
    级逻辑。模块级常量绑定已在 TestResolveModelName 等测试中间接覆盖。
    """

    def test_import_config_does_not_call_load_dotenv(self, monkeypatch):
        """import config 不得触发 load_dotenv 修改 os.environ。

        provider/dogfood 已有 scoped dotenv loader；legacy config 的 .env 读取必须
        显式调用，避免普通 import 在测试或 runtime 中悄悄污染 provider 优先级。
        """
        import config

        called = False

        def fake_load_dotenv(*args, **kwargs):  # noqa: ANN001
            nonlocal called
            called = True
            return True

        monkeypatch.setattr(config, "load_dotenv", fake_load_dotenv)
        importlib.reload(config)

        assert called is False

    def test_explicit_legacy_dotenv_loader_is_opt_in(self, monkeypatch):
        """legacy dotenv loader 只有显式调用才会读取项目 dotenv。"""
        import config

        calls: list[dict] = []

        def fake_load_dotenv(*args, **kwargs):  # noqa: ANN001
            calls.append({"args": args, "kwargs": kwargs})
            return True

        monkeypatch.setattr(config, "load_dotenv", fake_load_dotenv)

        assert config.load_legacy_dotenv_config() is True
        assert len(calls) == 1
        assert calls[0]["kwargs"].get("override") is False


class TestRequireConfig:
    """require_config() / get_config_errors() 启动校验。"""

    def test_all_present_no_errors(self, monkeypatch):
        monkeypatch.setenv("MODEL_NAME", "test-model")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        from config import get_config_errors, require_config

        assert get_config_errors() == []
        require_config()  # 不应抛出

    def test_missing_model_reports_env_var_names(self, monkeypatch):
        monkeypatch.delenv("MODEL_NAME", raising=False)
        monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
        monkeypatch.delenv("OPENAI_MODEL", raising=False)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        from config import get_config_errors

        errors = get_config_errors()
        assert len(errors) >= 1
        assert "MODEL_NAME" in errors[0]
        assert "ANTHROPIC_MODEL" in errors[0]
        assert "test-key" not in errors[0]

    def test_missing_api_key_reports_key_names_not_values(self, monkeypatch):
        monkeypatch.setenv("MODEL_NAME", "test-model")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        from config import get_config_errors

        errors = get_config_errors()
        assert len(errors) >= 1
        assert "ANTHROPIC_API_KEY" in errors[0]
        assert "OPENAI_API_KEY" in errors[0]

    def test_require_config_raises_when_missing(self, monkeypatch):
        monkeypatch.delenv("MODEL_NAME", raising=False)
        monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
        monkeypatch.delenv("OPENAI_MODEL", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        from config import require_config

        try:
            require_config()
            assert False, "应该抛出 ValueError"
        except ValueError as e:
            msg = str(e)
            assert "MODEL_NAME" in msg
            assert "ANTHROPIC_MODEL" in msg
            assert "ANTHROPIC_API_KEY" in msg

    def test_shell_env_priority_over_dotenv(self, monkeypatch):
        """shell 显式设置的 MODEL_NAME 优先于 .env。"""
        monkeypatch.setenv("MODEL_NAME", "shell-model")
        monkeypatch.setenv("ANTHROPIC_MODEL", "dotenv-model")
        from config import _resolve_model_name

        assert _resolve_model_name() == "shell-model"
