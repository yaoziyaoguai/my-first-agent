"""Stage 8 local customization config foundation tests.

本文件只覆盖显式 safe path 的 fake/local config：不读取真实 home config、不读取
`.env`、不展开 env secret、不连接 provider/network。目标是先把 local productization
的数据模型和安全边界立住，而不是把 `config.py` 或 runtime core 大改。
"""

from __future__ import annotations

import json


def test_load_local_config_from_explicit_safe_path(tmp_path) -> None:
    """local config 应表达 project profile / safety / toggles / provider metadata。"""

    from agent.local_config import load_local_agent_config

    config_path = tmp_path / "agent.local.json"
    config_path.write_text(
        json.dumps(
            {
                "project_profile": {
                    "name": "demo-project",
                    "description": "fake local project",
                },
                "safety_policy": {
                    "allow_network": False,
                    "allow_real_mcp": False,
                    "allow_real_home_writes": False,
                },
                "module_toggles": {
                    "memory": False,
                    "skills": True,
                    "subagents": True,
                    "observability": True,
                },
                "model_provider": {
                    "name": "anthropic",
                    "model": "test-model",
                    "api_key_env": "ANTHROPIC_API_KEY",
                    "base_url": "${ANTHROPIC_BASE_URL}",
                },
                "unknown_future_field": {"preserve": True},
            }
        ),
        encoding="utf-8",
    )

    config = load_local_agent_config(config_path)

    assert config.project_profile.name == "demo-project"
    assert config.safety_policy.allow_network is False
    assert config.module_toggles.skills is True
    assert config.model_provider.api_key_env == "ANTHROPIC_API_KEY"
    assert config.model_provider.base_url == "${ANTHROPIC_BASE_URL}"
    assert config.unknown_fields == {"unknown_future_field": {"preserve": True}}


def test_local_config_redacted_dict_does_not_expand_or_print_secret_values(tmp_path) -> None:
    """provider config 只能输出 env var 名称/脱敏 marker，不能读取真实 env value。"""

    from agent.local_config import load_local_agent_config

    config_path = tmp_path / "agent.local.json"
    config_path.write_text(
        json.dumps(
            {
                "project_profile": {"name": "demo"},
                "model_provider": {
                    "name": "anthropic",
                    "model": "test-model",
                    "api_key_env": "ANTHROPIC_API_KEY",
                    "api_key": "sk-should-not-appear",
                },
            }
        ),
        encoding="utf-8",
    )

    redacted = load_local_agent_config(config_path).to_redacted_dict()
    encoded = json.dumps(redacted, ensure_ascii=False)

    assert "ANTHROPIC_API_KEY" in encoded
    assert "sk-should-not-appear" not in encoded
    assert "[REDACTED]" in encoded


def test_local_config_rejects_real_runtime_or_home_paths() -> None:
    """Stage 8 foundation 不允许默认读取真实用户目录或 runtime artifact。"""

    import pytest

    from agent.local_config import LocalConfigPathPolicyError, load_local_agent_config

    for path in [
        "~/.config/my-first-agent/config.json",
        "sessions/config.json",
        "runs/config.json",
        ".env",
        "agent_log.jsonl",
    ]:
        with pytest.raises(LocalConfigPathPolicyError):
            load_local_agent_config(path)


def test_local_config_defaults_are_safe_when_optional_sections_missing(tmp_path) -> None:
    """缺省配置必须 fail-closed：网络/MCP/home write 默认关闭，模块默认关闭。"""

    from agent.local_config import load_local_agent_config

    config_path = tmp_path / "minimal-agent.local.json"
    config_path.write_text('{"project_profile": {"name": "minimal"}}', encoding="utf-8")

    config = load_local_agent_config(config_path)

    assert config.safety_policy.allow_network is False
    assert config.safety_policy.allow_real_mcp is False
    assert config.safety_policy.allow_real_home_writes is False
    assert config.module_toggles.memory is False
    assert config.module_toggles.skills is False
    assert config.module_toggles.subagents is False
    assert config.module_toggles.observability is False
