"""Stage 6 manual UX dogfooding runbook contract tests.

这些测试只检查 docs/checklist 是否把 fake memory UX dogfooding 讲清楚。
它们不读取真实 sessions/runs/agent_log，不调用 provider/LLM/MCP，也不触发 runtime。
"""

from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = PROJECT_ROOT / "docs" / "MEMORY_DOGFOODING.md"
ARCHITECTURE = PROJECT_ROOT / "docs" / "MEMORY_ARCHITECTURE.md"


def _runbook() -> str:
    return RUNBOOK.read_text(encoding="utf-8")


def test_stage6_runbook_exists_with_manual_steps_expected_behavior_and_safety_checks() -> None:
    """runbook 必须可人工执行，每一步都要有预期行为和安全检查。"""

    content = _runbook()

    required_markers = (
        "Stage 6 Manual UX Dogfooding Runbook",
        "Manual reviewer checklist",
        "Fake deterministic fixtures",
        "Expected behavior",
        "Safety checks",
        "Do not use real private data",
    )
    for marker in required_markers:
        assert marker in content


def test_stage6_runbook_documents_full_governance_path_without_runtime_activation() -> None:
    """dogfooding 要覆盖治理链，但不能宣称已经接入 runtime 自动记忆。"""

    content = _runbook()

    required_markers = (
        "DeterministicMemoryPolicy",
        "MemoryConfirmationRequest",
        "MemoryOperationIntent",
        "MemoryAuditSummary",
        "InMemoryMemoryStore",
        "build_memory_snapshot_from_store",
        "MemorySnapshot",
        "prompt_builder",
        "No runtime integration",
        "No automatic memory activation",
    )
    for marker in required_markers:
        assert marker in content


def test_stage6_runbook_covers_user_control_paths_and_sensitive_handling() -> None:
    """用户控制路径必须覆盖 accept/edit/reject/use_once/forget/update/sensitive。"""

    content = _runbook()

    required_markers = (
        "accept retain",
        "edit before retain",
        "reject retain",
        "use_once",
        "forget intent",
        "update intent",
        "sensitive redaction",
        "audit summary explanation",
        "store to governed snapshot",
    )
    for marker in required_markers:
        assert marker in content


def test_stage6_runbook_keeps_no_real_data_provider_network_or_log_boundary() -> None:
    """runbook 只能使用 fake/local deterministic fixtures，不能要求真实数据。"""

    content = _runbook()

    required_markers = (
        "fake/local deterministic data only",
        "no real sessions/runs/agent_log",
        "no real provider",
        "no MCP server",
        "no LLM call",
        "no network",
        "no real long-term memory write",
    )
    for marker in required_markers:
        assert marker in content

    forbidden_instructions = (
        "use your real profile",
        "read real sessions",
        "read real runs",
        "open agent_log.jsonl",
    )
    lowered = content.lower()
    for marker in forbidden_instructions:
        assert marker not in lowered


def test_stage6_architecture_readiness_is_documented_without_new_feature_stage() -> None:
    """architecture docs 只记录 final review readiness，不开启新的功能实现。"""

    content = ARCHITECTURE.read_text(encoding="utf-8")

    required_markers = (
        "Memory Architecture Final Review Readiness",
        "Stage 6 manual UX dogfooding",
        "fake/local deterministic data only",
        "no new feature stage",
        "no tag in this stage",
    )
    for marker in required_markers:
        assert marker in content
