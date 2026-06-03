"""F-001 / F-001-ext P0 修复回归测试。

验证 TOOL_GATE / read_file 前置边界的敏感路径策略：
- config*.yaml / config*.yml 必须在读取前被拒绝
- .env* / .pem / .key 等现有检查保持有效
- blocked 结果不包含文件内容
- provider-independent policy（fake/real 共享同一策略）

所有测试使用 tmp_path / fixture，不读取真实 config/config.yaml。
dummy secret 使用 TEST_ONLY_FAKE_SECRET_DO_NOT_USE 占位符。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.security import (
    CONFIG_DIR_SENSITIVE_SUFFIXES,
    CONFIG_FILE_NAMES,
    SENSITIVE_KEYWORDS,
    SENSITIVE_SUFFIXES,
    is_sensitive_file,
    needs_confirmation,
)

# =============================================================================
# 辅助：在 tmp_path 中创建 dummy sensitive 文件（不含真实 secret）
# =============================================================================

def _create_dummy_file(
    tmp_path: Path,
    name: str,
    content: str = "TEST_ONLY_FAKE_SECRET_DO_NOT_USE\n",
) -> Path:
    """创建仅用于测试的 dummy 文件。自动创建父目录。"""
    f = tmp_path / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content)
    return f


# =============================================================================
# §1 is_sensitive_file — config*.yaml / config*.yml 识别
# =============================================================================

@pytest.mark.parametrize("name", [
    "config.yaml",
    "config.yml",
    "config/config.yaml",
    "config/config.yml",
    "config.yaml.bak",       # 备份也可能含真实 secret
])
def test_config_files_are_sensitive(name: str, tmp_path: Path) -> None:
    """F-001 修复：config*.yaml / config*.yml 必须被 is_sensitive_file 识别为敏感。

    为什么必须在读文件前拦截：
    - config.yaml 通常包含 api_key、base_url 等真实凭证。
    - 一旦 read_file 返回文件内容，secret 就会进入 tool_result，
      进而通过 append_tool_result → session 文件持久化到磁盘。
    - 在 TOOL_GATE 确认阶段（needs_confirmation → is_sensitive_file）
      就拦截，可以阻止整条泄露链。

    为什么不能只靠模型拒绝：
    - 模型可能被对抗性 prompt 诱导生成 read_file("config/config.yaml")。
    - Skill / SubAgent 的 tool binding 只约束工具名，不约束参数。
    - 安全策略必须在服务端执行，不能依赖模型行为。
    """
    f = _create_dummy_file(tmp_path, name)
    assert is_sensitive_file(str(f)), (
        f"F-001 回归：{name!r} 应在读取前被 is_sensitive_file 识别为敏感文件"
    )


@pytest.mark.parametrize("name", [
    "config.toml",
    "config.json",
    "config/config.toml",
    "config/config.json",
])
def test_config_format_files_are_sensitive(name: str, tmp_path: Path) -> None:
    """配置格式文件（toml/json）同样可能包含 secret，应被识别。"""
    f = _create_dummy_file(tmp_path, name)
    assert is_sensitive_file(str(f)), (
        f"F-001 回归：{name!r}（常见配置格式）应在读取前被识别为敏感文件"
    )


# =============================================================================
# §2 现有 .env* / .pem / .key 检查不受影响
# =============================================================================

@pytest.mark.parametrize("name", [
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
    "config/.env",
    "server.pem",
    "api.key",
    "secrets/private.pem",
])
def test_existing_sensitive_patterns_still_blocked(name: str, tmp_path: Path) -> None:
    """确保 F-001 修复不改弱现有 .env*/.pem/.key 检查。"""
    f = _create_dummy_file(tmp_path, name)
    assert is_sensitive_file(str(f)), (
        f"回归：{name!r} 必须仍被 is_sensitive_file 识别（已有安全策略）"
    )


# =============================================================================
# §3 安全文件不受影响
# =============================================================================

@pytest.mark.parametrize("name", [
    "README.md",
    "docs/guide.txt",
])
def test_safe_files_remain_not_sensitive(name: str, tmp_path: Path) -> None:
    """F-001 修复不能误伤普通文件 — is_sensitive_file 必须返回 False。"""
    f = _create_dummy_file(tmp_path, name, "safe content")
    assert not is_sensitive_file(str(f)), (
        f"误伤：安全文件 {name!r} 被 is_sensitive_file 误识别"
    )


# =============================================================================
# §4 needs_confirmation 返回 "block" 的路径
# =============================================================================

@pytest.mark.parametrize("path,expected", [
    ("config/config.yaml", "block"),
    ("config.yaml", "block"),
    (".env", "block"),
    ("server.pem", "block"),
    # 项目外安全文件 → needs_confirmation 返回 True（项目外确认），但 is_sensitive_file=False
    ("README.md", True),                # tmp_path 文件在项目外 → 需确认但非 block
])
def test_read_file_confirmation_blocks_sensitive_paths(
    path: str, expected: object, tmp_path: Path
) -> None:
    """F-001 修复：needs_confirmation("read_file", {path: "config/config.yaml"})
    必须返回 "block"，由 TOOL_GATE 在 execute_single_tool 之前拦截。

    为什么 fake/real 必须共享 tool policy：
    - needs_confirmation 在 execute_single_tool 内部被调用，
      位于 provider 边界之下。
    - 无论是 FakeProvider 还是真实 AnthropicCompatibleProvider，
      tool_use → ToolRuntimeMediator → execute_single_tool 路径一致。
    - 如果 fake 路径不检查但 real 路径检查，会产生 fake/real split，
      违反 unified runtime 架构契约。
    """
    f = _create_dummy_file(tmp_path, path)
    result = needs_confirmation("read_file", {"path": str(f)})
    assert result == expected, (
        f"F-001 回归：read_file({path!r}) 的 needs_confirmation 期望 "
        f"{expected!r}，实际 {result!r}"
    )


# =============================================================================
# §5 read_file_lines 同样受保护
# =============================================================================

def test_read_file_lines_also_blocks_sensitive(tmp_path: Path) -> None:
    """read_file_lines 共享 _check_read_permission，敏感路径同样 block。"""
    f = _create_dummy_file(tmp_path, "config/config.yaml")
    result = needs_confirmation(
        "read_file_lines", {"path": str(f), "start_line": 1, "end_line": 10}
    )
    assert result == "block", (
        "F-001 回归：read_file_lines 也必须对 config 路径返回 'block'"
    )


# =============================================================================
# §6 is_sensitive_file 路径规范化（防止绕过）
# =============================================================================

@pytest.mark.parametrize("bypass_try", [
    "config/config.yaml",         # 相对路径
    "./config/config.yaml",       # ./ 前缀
    "config/../config/config.yaml",  # .. 绕过
])
def test_path_normalization_prevents_bypass(
    bypass_try: str, tmp_path: Path
) -> None:
    """F-001 修复：路径规范化防止 ../ 、 ./ 等绕过手法。

    敏感策略必须考虑：
    - exact path match
    - basename match
    - path segments
    - normalized path（resolve() 展开 .. 和 .）
    - 当前目录相对路径 ./config/
    """
    # 创建实际文件以便 resolve
    (tmp_path / "config").mkdir(exist_ok=True)
    f = tmp_path / "config" / "config.yaml"
    f.write_text("TEST_ONLY_FAKE_SECRET_DO_NOT_USE\n")
    # 用 bypass_try 的相对路径测试
    import os
    os.chdir(tmp_path)
    try:
        assert is_sensitive_file(bypass_try), (
            f"F-001 回归：绕过路径 {bypass_try!r} 必须被 is_sensitive_file 识别"
        )
    finally:
        os.chdir(Path(__file__).resolve().parent.parent)


# =============================================================================
# §7 SENSITIVE_PATTERNS / SUFFIXES 基线扩展
# =============================================================================

def test_sensitive_patterns_include_config_yaml() -> None:
    """F-001 修复：CONFIG_FILE_NAMES 必须包含 config.yaml / config.yml。"""
    assert "config.yaml" in CONFIG_FILE_NAMES, (
        "F-001 修复：CONFIG_FILE_NAMES 必须包含 'config.yaml'"
    )
    assert "config.yml" in CONFIG_FILE_NAMES, (
        "F-001 修复：CONFIG_FILE_NAMES 必须包含 'config.yml'"
    )


def test_config_dir_suffixes_include_yaml_toml_json() -> None:
    """F-001 修复：CONFIG_DIR_SENSITIVE_SUFFIXES 包含 .yaml/.yml/.toml/.json。"""
    assert {".yaml", ".yml", ".toml", ".json"} <= CONFIG_DIR_SENSITIVE_SUFFIXES, (
        "F-001 修复：CONFIG_DIR_SENSITIVE_SUFFIXES 必须覆盖配置格式"
    )


def test_sensitive_suffixes_include_yaml() -> None:
    """F-001 修复：CONFIG_DIR_SENSITIVE_SUFFIXES 包含 .yaml/.yml/.toml/.json。

    CONFIG_DIR_SENSITIVE_SUFFIXES 只在 config/ 目录上下文中生效，
    不会误伤项目外的 yaml/toml/json 文件。SENSITIVE_SUFFIXES（全局）
    保持不变，只包含 .pem/.key 这类明确的密钥文件扩展名。
    """
    assert ".pem" in SENSITIVE_SUFFIXES
    assert ".key" in SENSITIVE_SUFFIXES
    assert {".yaml", ".yml", ".toml", ".json"} <= CONFIG_DIR_SENSITIVE_SUFFIXES


def test_sensitive_keywords_baseline_unchanged() -> None:
    """确保 F-001 修复不改弱 SENSITIVE_KEYWORDS。"""
    expected = {"secret", "credential", "password", "token", "apikey"}
    assert expected <= set(SENSITIVE_KEYWORDS), (
        "SENSITIVE_KEYWORDS 不应被改弱"
    )


# =============================================================================
# §8 F-001-ext：tool_result 持久化不应保存 raw sensitive content
# =============================================================================

def test_blocked_tool_no_file_content_in_result(tmp_path: Path) -> None:
    """F-001-ext 修复：blocked read_file 的 tool_result 不应包含文件内容。

    为什么 session/event/log 不能保存 raw sensitive content：
    - tool_result 通过 append_tool_result → conversation messages →
      save_session_snapshot → sessions/*.json 持久化到磁盘。
    - 即使 TOOL_GATE 阻止了终端输出，session 文件中的 tool_result
      仍可能被后续 grep/glob 工具或人类直接读取。
    - F-001-ext 就是这种情况：TOOL_GATE ALLOWED read_file，
      完整 config 内容进入了 session_*.json 的 msg[2] tool_result。
    """
    f = _create_dummy_file(tmp_path, "config/config.yaml", "TEST_ONLY_FAKE_SECRET_DO_NOT_USE\n")
    # 确认 needs_confirmation 返回 "block"（即不会执行 read_file）
    result = needs_confirmation("read_file", {"path": str(f)})
    assert result == "block", (
        "F-001-ext 前置条件：config path 必须被 block，否则 tool_result 会包含内容"
    )
    # blocked 的情况下不会执行 read_file，所以不会有文件内容进入 tool_result。
    # 这是预防性测试 — 确认策略层面已阻止 raw content 进入 tool_result。
