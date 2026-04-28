"""Runtime v0.1 B3 smoke playbook 的离线护栏。

这些测试不调用真实模型，只把 B3 graduation smoke 中最关键的人工步骤和
判据钉住，避免 playbook 后续漂移到 v0.2 / v0.3 backlog 或弱化 B2 输出契约。
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK = ROOT / "docs" / "V0_1_SMOKE_PLAYBOOK.md"

SMOKE_TASK = "请读取仓库根目录 README.md，并把一段中文总结写入 summary.md。"


def _playbook_text() -> str:
    return PLAYBOOK.read_text(encoding="utf-8")


def test_b3_smoke_playbook_exists_and_freezes_canonical_task():
    """B3 smoke 必须继续验证 README -> summary.md 的最小毕业任务。"""

    text = _playbook_text()

    assert SMOKE_TASK in text
    assert "README.md" in text
    assert "summary.md" in text
    assert "仓库根目录" in text
    assert "不要静默改读 `tests/README.md`" in text


def test_b3_smoke_playbook_documents_preflight_and_artifact_policy():
    """真实 API smoke 前必须先检查 key、README 和 summary.md 产物约定。"""

    text = _playbook_text()

    required_markers = (
        'test -n "$ANTHROPIC_API_KEY"',
        "test -f README.md",
        "test -x .venv/bin/python",
        "test ! -e summary.md",
        "test -f summary.md",
        "sed -n '1,120p' summary.md",
    )
    for marker in required_markers:
        assert marker in text


def test_b3_smoke_playbook_keeps_cli_output_contract_checks_visible():
    """B3 必须显式审计 B2 输出契约中最容易回归的污染项。"""

    text = _playbook_text()

    forbidden_output_checks = (
        "裸 checkpoint dict",
        "checkpoint conversation messages",
        "[DEBUG] checkpoint:",
        "REQUEST → Anthropic",
        "RESPONSE ← Anthropic",
        "docs/CLI_OUTPUT_CONTRACT.md",
    )
    for marker in forbidden_output_checks:
        assert marker in text


def test_b3_smoke_playbook_documents_checkpoint_and_offline_gates():
    """playbook 需要固定 checkpoint 检查和离线 ruff / pytest gate。"""

    text = _playbook_text()

    required_markers = (
        "memory/checkpoint.json",
        ".venv/bin/python -m json.tool memory/checkpoint.json",
        ".venv/bin/python -m ruff check agent/ tests/",
        ".venv/bin/python -m pytest -q",
        "不调用真实模型",
    )
    for marker in required_markers:
        assert marker in text


def test_b3_smoke_playbook_rejects_out_of_scope_backlog():
    """B3 准备和真实 smoke 都不能扩张到后续版本能力。"""

    text = _playbook_text()

    out_of_scope_markers = (
        "P1 feedback intent flow",
        "Textual backend",
        "Skill/sub-agent",
        "generation cancellation",
        "复杂 topic switch",
        "slash command",
        "LLM 意图分类",
        "新 RuntimeEvent kind",
    )
    for marker in out_of_scope_markers:
        assert marker in text
