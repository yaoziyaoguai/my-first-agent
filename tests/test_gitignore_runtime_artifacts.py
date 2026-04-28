"""保护 v0.2 RC 运行产物不会被误提交的轻量测试。

不读取 git 状态，只读 .gitignore 文本。这样测试在任何环境都稳定。
对应文档：docs/V0_2_HEALTH_MAINTENANCE.md §4。
"""
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
GITIGNORE = REPO_ROOT / ".gitignore"

REQUIRED_PATTERNS = [
    ".env",
    "agent_log.jsonl",
    "sessions/",
    "workspace/",
    "memory/",
    "summary.md",
    "state.json",
    "runs/",
]


@pytest.mark.parametrize("pattern", REQUIRED_PATTERNS)
def test_gitignore_covers_runtime_artifact(pattern: str):
    """v0.2 RC 必须保证这些运行产物不会进 commit：
    .env / agent_log.jsonl / sessions/ / workspace/ / memory/ /
    summary.md / state.json / runs/。"""
    text = GITIGNORE.read_text(encoding="utf-8")
    lines = {line.strip() for line in text.splitlines() if line.strip()}
    assert pattern in lines, (
        f".gitignore 缺少 {pattern}，可能导致敏感运行产物被误提交。"
        f" 详见 docs/V0_2_HEALTH_MAINTENANCE.md §4。"
    )
