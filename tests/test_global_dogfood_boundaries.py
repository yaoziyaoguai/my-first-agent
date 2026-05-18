"""Global dogfood runner 的 D1/D2 边界测试。

从大测试文件拆出这些测试，是 v0.9.x Stabilization Phase 7 的行为中性拆分：
覆盖保持不变，只把 scenario definition 与 provider preflight 的架构边界单独归档。
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest


def test_global_dogfood_scenarios_are_definition_only() -> None:
    """D1: scenario definition 只能描述治理边界，不能偷偷执行 provider 或 IO。

    这个测试保护 dogfood runner 的可信度：场景定义是静态 contract，
    execution 层才允许把场景变成 synthetic / gated real-api result。
    """

    import scripts.dogfood_global_scenarios as scenarios

    source = Path(scenarios.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_from_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    all_imports = imported_modules | imported_from_modules

    assert "agent.provider.factory" not in all_imports
    assert "agent.provider.config" not in all_imports
    assert "os" not in all_imports
    assert len(scenarios.SCENARIOS) == 12
    assert all(item.expected_evidence for item in scenarios.SCENARIOS)


def test_provider_preflight_helper_public_result_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D2: provider preflight helper 可以审查来源，但 public packet 不能带 secret。"""

    from scripts import dogfood_provider_preflight as preflight

    monkeypatch.setattr(
        preflight._config,
        "_load_project_dotenv_values",
        lambda _root: {
            "MY_FIRST_AGENT_LLM_PROVIDER": "openai_compatible",
            "MY_FIRST_AGENT_LLM_PROVIDER_NAME": "fixture-compatible",
            "OPENAI_API_KEY": "synthetic-project-secret-not-printed",
            "OPENAI_MODEL": "fixture-model",
            "OPENAI_BASE_URL": "https://example.invalid/v1",
        },
    )

    packet = preflight.load_dogfood_provider_preflight(Path("/tmp/project"))

    assert packet["preflight_status"] == "ready"
    assert packet["provider_name"] == "fixture-compatible"
    assert packet["key_source_kind"] == "project_dotenv"
    assert "synthetic-project-secret" not in json.dumps(packet, ensure_ascii=False)
