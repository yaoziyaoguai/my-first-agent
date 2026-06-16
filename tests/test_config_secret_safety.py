"""Stage 3 — config 安全守卫测试。

验证 config 文件、examples、staged diff 不会意外包含真实 API key。
所有测试不读取本地 config/config.yaml（含真实 key）的内容。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = PROJECT_ROOT / "config"
EXAMPLES_DIR = CONFIG_DIR / "examples"

PLACEHOLDER_PATTERNS = (
    "sk-REPLACE_ME",
    "your-api-key",
    "YOUR_API_KEY",
    "REPLACE_ME",
    "your-key-here",
    "placeholder",
    "fake-llm",
)

# 真实 key 特征：sk- 后跟非占位符内容
REAL_KEY_INDICATORS = (
    "sk-sp-",  # DashScope real key prefix
    "sk-ant-",  # Anthropic real key prefix
    "sk-or-",  # OpenAI real key prefix
    "sk-proj-",  # OpenAI project key prefix
    "sk-svcacct-",  # OpenAI service account
)


def _git_show_file(rel_path: str) -> str:
    """读取追踪版本的指定文件（不是工作目录版本）。"""
    result = subprocess.run(
        ["git", "show", f"HEAD:{rel_path}"],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )
    if result.returncode != 0:
        return ""
    return result.stdout


def _git_path_is_tracked(rel_path: str) -> bool:
    """只查询 git index，不读取 working copy 文件内容。"""
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", rel_path],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )
    return result.returncode == 0


def _git_path_is_ignored(rel_path: str) -> bool:
    """验证路径由 .gitignore 覆盖，不读取被忽略文件内容。"""
    result = subprocess.run(
        ["git", "check-ignore", rel_path],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )
    return result.returncode == 0


def _contains_real_key(content: str) -> bool:
    """检查内容是否包含疑似真实 API key。

    只检查 HEAD 版本（git show）以确保不读取本地 dirty working copy。
    """
    return any(indicator in content for indicator in REAL_KEY_INDICATORS)


def test_runtime_config_yaml_is_untracked_and_ignored() -> None:
    """config/config.yaml 是本地 real runtime config，不能进入 git。

    G-15 后的安全策略是 tracked template + ignored local config：
    测试只问 git index / ignore 规则，不读取本地 config/config.yaml 内容。
    """

    rel_path = "config/config.yaml"
    assert not _git_path_is_tracked(rel_path), (
        "config/config.yaml 不应被 git 追踪；"
        "真实 runtime config 必须保持本地 ignored"
    )
    assert _git_path_is_ignored(rel_path), (
        "config/config.yaml 必须被 .gitignore 忽略，避免真实 key 进入 git"
    )


def test_dotenv_is_not_a_required_tracked_artifact() -> None:
    """.env 只能是 ignored local artifact；测试不得要求恢复它。"""

    rel_path = ".env"
    assert not _git_path_is_tracked(rel_path), ".env 不应被 git 追踪"
    assert _git_path_is_ignored(rel_path), (
        ".env 必须被 .gitignore 忽略；不要为了通过测试创建或恢复 .env"
    )


def test_config_example_yaml_has_no_real_key() -> None:
    """config.example.yaml 是 tracked template，且不得包含真实 API key。"""

    assert _git_path_is_tracked("config/config.example.yaml"), (
        "config/config.example.yaml 必须作为 tracked template 存在"
    )
    content = _git_show_file("config/config.example.yaml")

    assert content, "config/config.example.yaml 未在 git 中追踪"
    assert not _contains_real_key(content), (
        "config/config.example.yaml 包含疑似真实 API key"
    )


@pytest.mark.parametrize(
    "example_file",
    [
        "kimi-anthropic-compatible.config.yaml",
        "glm-openai-compatible.config.yaml",
        "fake.config.yaml",
    ],
)
def test_config_examples_only_placeholder_keys(example_file: str) -> None:
    """config/examples/ 下的所有示例文件只能含占位符 key。"""

    content = _git_show_file(f"config/examples/{example_file}")

    assert content, f"config/examples/{example_file} 未在 git 中追踪"
    assert not _contains_real_key(content), (
        f"config/examples/{example_file} 包含疑似真实 API key"
    )
    assert "sk-REPLACE_ME" in content or "api_key" not in content, (
        f"config/examples/{example_file}: 如有 api_key 字段，必须为 sk-REPLACE_ME"
    )


def test_config_yaml_not_staged_in_current_index() -> None:
    """config/config.yaml 不得被 staged。

    skip-worktree 是本地保护，此测试验证当前 staged 状态不含 config.yaml。
    """

    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )
    staged = result.stdout.strip().split("\n") if result.stdout.strip() else []
    assert "config/config.yaml" not in staged, (
        "config/config.yaml 已在 staging area — 不要 git add 此文件"
    )


def test_staged_diff_contains_no_real_key_pattern() -> None:
    """当前 staged diff 不得包含疑似真实 API key 特征。"""

    result = subprocess.run(
        ["git", "diff", "--cached"],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )
    staged_diff = result.stdout

    # 只检查新增行（+ 开头），避免 context lines 中的占位断言
    # （如 verify that Anthropic key prefix is excluded from banners）导致误报。
    added_lines = "\n".join(
        line[1:] for line in staged_diff.split("\n")
        if line.startswith("+") and not line.startswith("+++")
    )

    assert not _contains_real_key(added_lines), (
        "staged diff 中包含疑似真实 API key 片段 — "
        "立即检查，不要 commit"
    )


def test_gitignore_excludes_env_and_logs() -> None:
    """.gitignore 必须覆盖 .env、agent_log.jsonl 等常见 secret 载体。"""

    gitignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")

    required_entries = [".env", "agent_log.jsonl", "sessions/", "runs/"]
    for entry in required_entries:
        assert entry in gitignore, f".gitignore 缺少 {entry}"
