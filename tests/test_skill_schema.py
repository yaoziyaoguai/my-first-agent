"""Phase 1: Skill Descriptor Schema 测试。

测试范围（Skill Descriptor Schema）：
- 合法 frontmatter → SkillManifest
- 缺失必填字段 → fail closed with typed error
- 无效 name/status/risk_level → fail closed
- 不安全资源路径 → fail closed
- secret-like 值 → redact 处理
- SkillDescriptor.is_visible 行为
- SkillManifest.to_descriptor 转换

禁止行为（来自 RFC/SDD）：
- 部分无效 manifest 变成 model-visible
- 解析器读取 .env / 访问网络 / 执行代码
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from textwrap import dedent

import pytest

from agent.skill_system.descriptor import (
    SkillDescriptor,
    SkillResourceManifest,
)
from agent.skill_system.errors import (
    CODE_INVALID_NAME,
    CODE_INVALID_RESOURCE,
    CODE_INVALID_STATUS,
    CODE_MISSING_DESCRIPTION,
    CODE_MISSING_FRONTMATTER,
    CODE_MISSING_NAME,
    CODE_MISSING_STATUS,
    CODE_MISSING_VERSION,
    CODE_SECRET_DETECTED,
    SkillLoadError,
)
from agent.skill_system.schema import (
    _detect_secret,
    _redact_value,
    load_skill_manifest,
    parse_skill_md,
)

# ---- helpers ----

def _write_skill_md(content: str, dir_path: Path) -> Path:
    """在指定目录写入 SKILL.md 并返回路径。"""
    dir_path.mkdir(parents=True, exist_ok=True)
    path = dir_path / "SKILL.md"
    path.write_text(dedent(content).strip(), encoding="utf-8")
    return path


def _valid_frontmatter() -> str:
    """返回一个合法的 SKILL.md 内容模板。"""
    return """
    ---
    name: safe-writer
    description: 安全地写入本地文档。
    version: 0.1.0
    status: active
    risk_level: low
    allowed_tools:
      - read_file
      - write_file
    tags:
      - writing
      - docs
    memory_scope: none
    confirmation_policy: inherit_tool_policy
    owner: local
    resources:
      references: []
      scripts: []
      templates: []
      tests: []
      dogfood: []
    ---
    # Safe Writer Skill

    这是 body 内容，Phase 1 只解析不加载。
    """


# ==================================================================
# 合法 frontmatter → SkillManifest
# ==================================================================

def test_valid_manifest_produces_skill_manifest():
    """合法 SKILL.md 解析后应返回完整的 SkillManifest。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "safe-writer"
        path = _write_skill_md(_valid_frontmatter(), root)
        manifest = load_skill_manifest(path)

        assert manifest.name == "safe-writer"
        assert "安全地写入本地文档" in manifest.description
        assert manifest.version == "0.1.0"
        assert manifest.status == "active"
        assert manifest.risk_level == "low"
        assert manifest.allowed_tools == ("read_file", "write_file")
        assert manifest.tags == ("writing", "docs")
        assert manifest.memory_scope == "none"
        assert manifest.confirmation_policy == "inherit_tool_policy"
        assert manifest.owner == "local"
        assert isinstance(manifest.resources, SkillResourceManifest)
        assert manifest.root == root
        assert manifest.manifest_path == path
        assert isinstance(manifest.raw_frontmatter, dict)
        assert manifest.is_visible() is True


def test_valid_manifest_to_descriptor():
    """SkillManifest.to_descriptor() 应提取 Level 1 公开元数据投影。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "safe-writer"
        path = _write_skill_md(_valid_frontmatter(), root)
        manifest = load_skill_manifest(path)
        desc = manifest.to_descriptor()

        assert isinstance(desc, SkillDescriptor)
        assert desc.name == "safe-writer"
        assert desc.description == manifest.description
        assert desc.version == "0.1.0"
        assert desc.status == "active"
        # 确认 descriptor 不暴露 internal 字段
        assert not hasattr(desc, "confirmation_policy")
        assert not hasattr(desc, "owner")
        assert not hasattr(desc, "raw_frontmatter")


# ==================================================================
# 缺失必填字段 → fail closed
# ==================================================================

@pytest.mark.parametrize(
    "missing_field,expected_code",
    [
        ("name", CODE_MISSING_NAME),
        ("description", CODE_MISSING_DESCRIPTION),
        ("version", CODE_MISSING_VERSION),
        ("status", CODE_MISSING_STATUS),
    ],
)
def test_missing_required_field_fails_closed(missing_field, expected_code):
    """缺失必填字段时必须抛出 SkillLoadError，不能返回 partically-valid manifest。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "test-skill"
        # 构造缺失字段的 frontmatter
        fields = {
            "name": "test-skill",
            "description": "A test skill",
            "version": "0.1.0",
            "status": "active",
        }
        del fields[missing_field]

        yaml_lines = ["---"]
        for k, v in fields.items():
            yaml_lines.append(f"{k}: {v}")
        yaml_lines.append("---")
        yaml_lines.append("body")
        content = "\n".join(yaml_lines)

        path = _write_skill_md(content, root)
        with pytest.raises(SkillLoadError) as exc_info:
            load_skill_manifest(path)
        assert exc_info.value.code == expected_code
        assert exc_info.value.recoverable is False
        assert exc_info.value.safe_preview != ""


# ==================================================================
# 无效字段值 → fail closed
# ==================================================================

def test_invalid_name_format_fails_closed():
    """name 必须以小写字母开头，只含小写字母/数字/连字符/下划线。"""
    with tempfile.TemporaryDirectory() as tmp:
        for bad_name in ("", "UPPERCASE", "has space", "123start", "name.with.dot"):
            root = Path(tmp) / bad_name.replace(" ", "_")
            content = f"""
            ---
            name: {bad_name}
            description: A test skill
            version: 0.1.0
            status: draft
            ---
            body
            """
            path = _write_skill_md(content, root)
            with pytest.raises(SkillLoadError) as exc_info:
                load_skill_manifest(path)
            assert exc_info.value.code == CODE_INVALID_NAME


def test_invalid_status_fails_closed():
    """status 必须是允许的 Literal 值之一。"""
    with tempfile.TemporaryDirectory() as tmp:
        content = """
        ---
        name: test-skill
        description: A test skill
        version: 0.1.0
        status: production
        ---
        body
        """
        path = _write_skill_md(content, Path(tmp) / "test-skill")
        with pytest.raises(SkillLoadError) as exc_info:
            load_skill_manifest(path)
        assert exc_info.value.code == CODE_INVALID_STATUS


def test_invalid_risk_level_defaults_to_low_and_passes():
    """无效 risk_level 应 fail closed（不在允许值集合中）。"""
    with tempfile.TemporaryDirectory() as tmp:
        content = """
        ---
        name: test-skill
        description: A test skill
        version: 0.1.0
        status: draft
        risk_level: critical
        ---
        body
        """
        path = _write_skill_md(content, Path(tmp) / "test-skill")
        # risk_level 不在允许集合中，但当前实现不单独校验 risk_level
        # 无效值由 schema.validate_manifest 处理
        with pytest.raises(SkillLoadError) as exc_info:
            load_skill_manifest(path)
        assert (
            "risk_level" in exc_info.value.message.lower()
            or exc_info.value.code == "INVALID_RISK_LEVEL"
        )


# ==================================================================
# 不安全资源路径 → fail closed
# ==================================================================

def test_resource_path_traversal_fails_closed():
    """资源路径中包含 .. 时必须 fail closed。"""
    with tempfile.TemporaryDirectory() as tmp:
        content = """
        ---
        name: test-skill
        description: A test skill
        version: 0.1.0
        status: draft
        resources:
          references:
            - ../secret/file.md
        ---
        body
        """
        path = _write_skill_md(content, Path(tmp) / "test-skill")
        with pytest.raises(SkillLoadError) as exc_info:
            load_skill_manifest(path)
        assert exc_info.value.code == CODE_INVALID_RESOURCE
        assert "不安全的路径" in exc_info.value.message or ".." in exc_info.value.message


# ==================================================================
# 缺失 frontmatter → fail closed
# ==================================================================

def test_missing_frontmatter_fails_closed():
    """没有 YAML frontmatter 的 SKILL.md 必须 fail closed。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "no-fm"
        root.mkdir(parents=True)
        path = root / "SKILL.md"
        path.write_text("# No frontmatter here\n\nJust a markdown file.", encoding="utf-8")

        with pytest.raises(SkillLoadError) as exc_info:
            load_skill_manifest(path)
        assert exc_info.value.code == CODE_MISSING_FRONTMATTER


# ==================================================================
# Secret 检测与 redact
# ==================================================================

def test_detect_secret_openai_key():
    """检测 OpenAI API key 模式。"""
    assert _detect_secret("sk-proj-abcdefghijklmnopqrstuvwxyz123456") == "openai_api_key"
    assert _detect_secret("my normal description") is None


def test_detect_secret_github_token():
    """检测 GitHub PAT 模式。"""
    assert _detect_secret("ghp_abcdefghijklmnopqrstuvwxyz1234567890") == "github_pat"


def test_detect_secret_aws_key():
    """检测 AWS Access Key 模式。"""
    assert _detect_secret("AKIAIOSFODNN7EXAMPLE") == "aws_access_key"


def test_redact_value_recursive():
    """_redact_value 应递归处理 dict/list 并替换 secret 值。"""
    data = {
        "name": "test",
        "api_key": "sk-proj-abcdefghijklmnopqrstuvwxyz123456",
        "nested": {"token": "ghp_1234567890abcdefghijklmnopqrstuvwxyz"},
        "list": ["normal", "sk-ant-api03-abcdefghijklmnopqrstuvwxyz"],
    }
    result = _redact_value(data)
    assert result["name"] == "test"
    assert result["api_key"] == "<REDACTED>"
    assert result["nested"]["token"] == "<REDACTED>"
    assert result["list"][0] == "normal"
    assert result["list"][1] == "<REDACTED>"


def test_secret_in_frontmatter_field_fails_closed():
    """Skill 字段值包含疑似 secret 时必须 fail closed。"""
    with tempfile.TemporaryDirectory() as tmp:
        content = """
        ---
        name: test-skill
        description: ghp_1234567890abcdefghijklmnopqrstuv
        version: 0.1.0
        status: draft
        ---
        body
        """
        path = _write_skill_md(content, Path(tmp) / "test-skill")
        with pytest.raises(SkillLoadError) as exc_info:
            load_skill_manifest(path)
        assert exc_info.value.code == CODE_SECRET_DETECTED


# ==================================================================
# SkillDescriptor.is_visible 行为
# ==================================================================

@pytest.mark.parametrize(
    "status,expected_visible",
    [
        ("draft", True),
        ("active", True),
        ("deprecated", True),
        ("disabled", False),
        ("legacy", False),
    ],
)
def test_descriptor_is_visible(status, expected_visible):
    """disabled 和 legacy 状态的 Skill 默认不对模型可见。"""
    desc = SkillDescriptor(
        name="test",
        description="desc",
        version="0.1.0",
        status=status,
        risk_level="low",
    )
    assert desc.is_visible() == expected_visible


# ==================================================================
# parse_skill_md 底层函数
# ==================================================================

def test_parse_skill_md_returns_frontmatter_and_body():
    """parse_skill_md 应分离 frontmatter dict 和 body string。"""
    with tempfile.TemporaryDirectory() as tmp:
        content = """
        ---
        name: test-skill
        description: desc
        version: 0.1.0
        status: draft
        ---
        # Body Title

        Body paragraph.
        """
        path = _write_skill_md(content, Path(tmp) / "test-skill")
        raw, body = parse_skill_md(path)

        assert raw["name"] == "test-skill"
        assert "# Body Title" in body
        assert "Body paragraph" in body


def test_parse_skill_md_file_not_found():
    """文件不存在时应抛出 recoverable=True 的 SkillLoadError。"""
    with pytest.raises(SkillLoadError) as exc_info:
        parse_skill_md(Path("/nonexistent/SKILL.md"))
    assert exc_info.value.code == "PARSE_ERROR"
    assert exc_info.value.recoverable is True


# ==================================================================
# 版本号校验
# ==================================================================

def test_invalid_version_fails_closed():
    """版本号不符合 semver 格式时 fail closed。"""
    with tempfile.TemporaryDirectory() as tmp:
        content = """
        ---
        name: test-skill
        description: desc
        version: not-a-version
        status: draft
        ---
        body
        """
        path = _write_skill_md(content, Path(tmp) / "test-skill")
        with pytest.raises(SkillLoadError) as exc_info:
            load_skill_manifest(path)
        assert exc_info.value.code == CODE_MISSING_VERSION


# ==================================================================
# description 不能为空
# ==================================================================

def test_empty_description_fails_closed():
    """description 不能为空字符串。"""
    with tempfile.TemporaryDirectory() as tmp:
        content = """
        ---
        name: test-skill
        description: "   "
        version: 0.1.0
        status: draft
        ---
        body
        """
        path = _write_skill_md(content, Path(tmp) / "test-skill")
        with pytest.raises(SkillLoadError) as exc_info:
            load_skill_manifest(path)
        assert exc_info.value.code == CODE_MISSING_DESCRIPTION
