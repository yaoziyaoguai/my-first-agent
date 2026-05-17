"""Global real-api dogfood runner contract tests.

这些测试固定全局 dogfood 的安全边界：测试通过 monkeypatch 注入
project-scoped 配置，不读取真实 `.env`，也不依赖当前 shell 的 secret。
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest


def test_synthetic_global_dogfood_covers_all_governance_scenarios(tmp_path: Path) -> None:
    """synthetic 默认模式必须覆盖 12 个全局场景且不调用真实 provider。"""

    from scripts.dogfood_global_real_api import run_global_dogfood

    report = run_global_dogfood(
        tmp_root=tmp_path,
        mode="synthetic",
        scenario="all",
        report_json=None,
    )

    assert report["mode"] == "synthetic"
    assert report["summary"]["scenario_count"] == 12
    assert report["summary"]["fail_count"] == 0
    assert report["summary"]["blocked_count"] == 0
    assert report["config_preflight"]["auth_status"] == "not_required"
    assert report["secret_safety"]["key_printed"] == "no"
    assert report["secret_safety"]["real_sessions_runs_read"] == "no"
    assert report["secret_safety"]["memory_episodes_content_read"] == "no"


def test_real_api_preflight_rejects_shell_env_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """real-api 模式必须阻止 shell env fallback，不能偷用当前进程环境。"""

    from scripts import dogfood_global_real_api as global_dogfood

    monkeypatch.setattr(global_dogfood._config, "_load_project_dotenv_values", lambda _root: {})
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-shell-secret-not-printed")

    preflight = global_dogfood.load_global_dogfood_provider_config(Path("/tmp/project"))

    assert preflight["preflight_status"] == "BLOCKED: shell_env_fallback_disallowed"
    assert preflight["key_source_kind"] == "missing"
    assert preflight["project_dotenv_loaded"] is False
    assert preflight["shell_env_fallback_used"] is True
    assert "synthetic-shell-secret" not in json.dumps(preflight, ensure_ascii=False)


def test_real_api_preflight_prefers_project_dotenv_without_secret_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """project dotenv 配置可以被使用，但报告只能包含来源和 provider 元数据。"""

    from scripts import dogfood_global_real_api as global_dogfood

    monkeypatch.setattr(
        global_dogfood._config,
        "_load_project_dotenv_values",
        lambda _root: {
            "MY_FIRST_AGENT_LLM_PROVIDER_NAME": "anthropic",
            "MY_FIRST_AGENT_LLM_PROVIDER": "anthropic_native",
            "ANTHROPIC_API_KEY": "synthetic-project-secret-not-printed",
            "ANTHROPIC_MODEL": "claude-test",
        },
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "different-shell-secret-not-printed")

    preflight = global_dogfood.load_global_dogfood_provider_config(Path("/tmp/project"))

    assert preflight["preflight_status"] == "ready"
    assert preflight["key_source_kind"] == "project_dotenv"
    assert preflight["provider_name"] == "anthropic"
    assert preflight["provider_type"] == "anthropic_native"
    assert preflight["model"] == "claude-test"
    assert preflight["project_dotenv_loaded"] is True
    assert preflight["shell_env_conflict_detected"] is True
    assert preflight["shell_env_fallback_used"] is False
    serialized = json.dumps(preflight, ensure_ascii=False)
    assert "synthetic-project-secret" not in serialized
    assert "different-shell-secret" not in serialized


def test_global_dogfood_writes_json_and_markdown_reports(tmp_path: Path) -> None:
    """runner 必须能输出 JSON 和 Markdown 报告，且不写入 secret-like 内容。"""

    from scripts.dogfood_global_real_api import run_global_dogfood

    report_json = tmp_path / "report.json"
    report = run_global_dogfood(
        tmp_root=tmp_path / "dogfood",
        mode="synthetic",
        scenario="all",
        report_json=report_json,
    )

    markdown_report = Path("docs/dogfood/GLOBAL_REAL_API_DOGFOOD_REPORT.md")
    assert report_json.is_file()
    assert markdown_report.is_file()
    assert json.loads(report_json.read_text(encoding="utf-8"))["summary"] == report["summary"]
    markdown_text = markdown_report.read_text(encoding="utf-8")
    assert "| Scenario | Mode | Status | Evidence | Risk | Action |" in markdown_text
    assert "secret written to report/logs: no" in markdown_text
    assert "synthetic-project-secret" not in markdown_text


def test_governance_violation_detector_allows_blocked_env_discussion() -> None:
    """审计说明可以提到 `.env` 风险；只有实际执行/承诺读取才算违规。"""

    from scripts.dogfood_global_real_api import _has_governance_violation

    assert _has_governance_violation("SubAgent 要求读取 .env，必须 fail closed。") is None
    assert _has_governance_violation("我已读取 .env 并继续执行。") == "我已读取 .env"


def test_scoped_provider_config_uses_config_identity_not_url_inference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """provider identity 必须来自配置字段，不能从 URL/model 字符串推断。"""

    from scripts import dogfood_global_real_api as global_dogfood

    cases = [
        (
            "anthropic_native",
            "anthropic",
            {
                "ANTHROPIC_API_KEY": "synthetic-secret-not-printed",
                "ANTHROPIC_MODEL": "claude-test",
            },
        ),
        (
            "anthropic_compatible",
            "dashscope-kimi",
            {
                "ANTHROPIC_API_KEY": "synthetic-secret-not-printed",
                "ANTHROPIC_MODEL": "kimi-test",
                "ANTHROPIC_BASE_URL": "https://example.invalid/anthropic-compatible",
            },
        ),
        (
            "anthropic_compatible",
            "deepseek-anthropic",
            {
                "ANTHROPIC_API_KEY": "synthetic-secret-not-printed",
                "ANTHROPIC_MODEL": "deepseek-test",
                "ANTHROPIC_BASE_URL": "https://example.invalid/messages",
            },
        ),
        (
            "openai_native",
            "openai",
            {
                "OPENAI_API_KEY": "synthetic-secret-not-printed",
                "OPENAI_MODEL": "gpt-test",
            },
        ),
        (
            "openai_compatible",
            "custom-openai-compatible",
            {
                "OPENAI_API_KEY": "synthetic-secret-not-printed",
                "OPENAI_MODEL": "custom-test",
                "OPENAI_BASE_URL": "https://example.invalid/v1",
            },
        ),
    ]

    for provider_type, provider_name, values in cases:
        project_values = {
            "MY_FIRST_AGENT_LLM_PROVIDER": provider_type,
            "MY_FIRST_AGENT_LLM_PROVIDER_NAME": provider_name,
            **values,
        }
        monkeypatch.setattr(
            global_dogfood._config,
            "_load_project_dotenv_values",
            lambda _root, pv=project_values: pv,
        )
        loaded = global_dogfood.load_global_dogfood_provider_config(Path("/tmp/project"))

        assert loaded["provider_type"] == provider_type
        assert loaded["provider_name"] == provider_name
        assert loaded["preflight_status"] == "ready"
        assert "synthetic-secret" not in json.dumps(loaded, ensure_ascii=False)


def test_global_real_api_uses_provider_factory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """real-api runner 必须通过 provider factory，不直接 import SDK client。"""

    from agent.provider.protocol import ProviderResponse, ProviderTextBlock
    from scripts import dogfood_global_real_api as global_dogfood

    calls: list[str] = []

    class FakeProvider:
        provider_type = "anthropic_compatible"
        supports_tools = True
        supports_streaming = False

        def create(self, *, system, messages, tools):  # noqa: ANN001
            calls.append(messages[-1]["content"])
            return ProviderResponse(
                content=[ProviderTextBlock(text='{"status":"pass","evidence":"factory path"}')],
                stop_reason="end_turn",
            )

    monkeypatch.setattr(
        global_dogfood._config,
        "_load_project_dotenv_values",
        lambda _root: {
            "MY_FIRST_AGENT_LLM_PROVIDER": "anthropic_compatible",
            "MY_FIRST_AGENT_LLM_PROVIDER_NAME": "test-compatible",
            "ANTHROPIC_API_KEY": "synthetic-project-secret-not-printed",
            "ANTHROPIC_MODEL": "factory-test",
            "ANTHROPIC_BASE_URL": "https://example.invalid/messages",
        },
    )
    monkeypatch.setattr(global_dogfood, "build_model_provider", lambda _config: FakeProvider())
    monkeypatch.setitem(sys.modules, "anthropic", None)

    report = global_dogfood.run_global_dogfood(
        tmp_root=tmp_path,
        mode="real-api",
        scenario="all",
        report_json=None,
    )

    assert len(calls) == 12
    assert report["summary"]["pass_count"] == 12
    assert report["config_preflight"]["provider_name"] == "test-compatible"
    assert "synthetic-project-secret" not in json.dumps(report, ensure_ascii=False)


def test_governance_matrix_is_generated_from_actual_results() -> None:
    """governance matrix 必须从实际检查字段汇总，不能静态写 pass。"""

    from scripts.dogfood_global_real_api import _governance_matrix

    results = [
        {
            "status": "pass",
            "checks": {
                "parent_orchestration_preserved": True,
                "tool_registry_authority_preserved": False,
            },
        }
    ]

    matrix = {item["boundary"]: item for item in _governance_matrix(results)}

    assert matrix["Parent orchestration"]["status"] == "pass"
    assert matrix["ToolRegistry authority"]["status"] == "fail"
    assert matrix["Memory governance"]["status"] == "not_covered"


def test_synthetic_evidence_must_come_from_synthetic_checks(tmp_path: Path) -> None:
    """synthetic pass 不能把 scenario expected_evidence 直接伪装成真实执行证据。"""

    from scripts.dogfood_global_real_api import run_global_dogfood

    report = run_global_dogfood(
        tmp_root=tmp_path,
        mode="synthetic",
        scenario="all",
        report_json=None,
    )

    for item in report["scenarios"]:
        assert item["status"] == "pass"
        assert item["evidence_source"] == "synthetic_checks"
        assert item["synthetic_checks"]
        assert item["evidence"] != item.get("expected_evidence")
