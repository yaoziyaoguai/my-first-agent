"""v0.9.x config authority characterization tests.

这些测试锁住三层配置职责：legacy ``config.py`` 负责兼容入口，
``agent.provider.config`` 才是真实 provider/API authority，
``agent.local_config`` 只保存本地 customization metadata。
"""

from __future__ import annotations

import json


def test_provider_config_ignores_local_config_metadata(tmp_path) -> None:
    """真实 provider 配置不能从 local customization metadata 偷读 key/model。

    Local config 的 ``model_provider`` 只用于展示、fixture 和 future customization；
    如果 provider/API authority 开始读取它，就会绕过明确 env/scoped dotenv 边界。
    """

    from agent.local_config import load_local_agent_config
    from agent.provider.config import ProviderConfigurationError, load_agent_provider_config

    local_config_path = tmp_path / "agent.local.json"
    local_config_path.write_text(
        json.dumps(
            {
                "project_profile": {"name": "config-boundary"},
                "model_provider": {
                    "name": "anthropic",
                    "model": "metadata-only-model",
                    "api_key": "sk-local-metadata-must-not-be-used",
                    "api_key_env": "ANTHROPIC_API_KEY",
                },
            }
        ),
        encoding="utf-8",
    )

    loaded = load_local_agent_config(local_config_path)
    assert loaded.model_provider.model == "metadata-only-model"

    try:
        load_agent_provider_config("anthropic_native", env={})
    except ProviderConfigurationError as exc:
        assert str(exc) == "api_key_missing"
    else:
        raise AssertionError("provider config must not read local config metadata")


def test_legacy_config_is_not_provider_api_authority(monkeypatch) -> None:
    """legacy resolver 可以兼容旧入口，但 provider config 必须独立校验字段。

    这里用同一组 shell env 证明：legacy ``config.py`` 只提供旧常量/错误提示；
    真正四路 provider 配置的 provider_type/provider_name/model/key 解析仍由
    ``agent.provider.config`` 完成。
    """

    monkeypatch.setenv("MY_FIRST_AGENT_LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("MY_FIRST_AGENT_LLM_PROVIDER_NAME", "fixture-openai-compatible")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-secret-not-printed")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-boundary")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.invalid/v1")

    import config
    from agent.provider.config import load_agent_provider_config

    # legacy resolver 可以继续按历史优先级处理 MODEL_NAME；这不应影响
    # provider/API authority 对 provider_type/provider_name/base_url 的独立解析。
    assert config._resolve_model_name()

    provider_config = load_agent_provider_config()
    assert provider_config.provider_type == "openai_compatible"
    assert provider_config.provider_name == "fixture-openai-compatible"
    assert provider_config.model == "gpt-boundary"
    assert provider_config.base_url == "https://example.invalid/v1"
