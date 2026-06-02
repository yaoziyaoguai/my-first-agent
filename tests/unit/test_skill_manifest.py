"""Phase 1 TDD RED Tests — Plan 3 Manifest Foundation (M01-M06).

测试范围（来自 docs/design/002-skill-selection-sdd-vNext.md §7.1）：
- M01: 新字段默认值 (when_to_use/when_not_to_use/triggers/negative_triggers/aliases/locale)
- M02: triggers 从 YAML list 解析为 tuple
- M03: 旧 SKILL.md（无新字段）仍通过 validate_manifest（向后兼容）
- M04: when_to_use 在 raw_frontmatter 中完整保留（可审计）
- M05: SkillDescriptor.aliases 可访问（Level 1 公开元数据）
- M06: 新字段包含 secret 时被 redact

RED 状态说明：
- M01/M02/M05: 预期 FAIL — SkillManifest 尚无新字段，SkillDescriptor 尚无 aliases
- M03/M04: 预期 PASS — 向后兼容和 raw_frontmatter 保留已是现有行为
- M06: 预期 PASS — _redact_value 递归处理整个 raw dict，新字段自动覆盖

这些测试是 Plan 3 Phase 1 的 contract tests。在 SkillManifest 新增字段前，
M01/M02/M05 应失败；新增字段和 validate_manifest 解析后全部 GREEN。
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from textwrap import dedent

import pytest

from agent.skill_system.descriptor import SkillDescriptor
from agent.skill_system.schema import (
    load_skill_manifest,
)

# ---- helpers ----

def _write_skill_md(content: str, dir_path: Path) -> Path:
    dir_path.mkdir(parents=True, exist_ok=True)
    path = dir_path / "SKILL.md"
    path.write_text(dedent(content).strip(), encoding="utf-8")
    return path


def _valid_frontmatter_with_new_fields() -> str:
    """返回含 Plan 3 新字段的 SKILL.md 模板。"""
    return """
    ---
    name: demo-note-maker
    description: 围绕 demo 工具创建本地任务笔记。
    version: 0.1.0
    status: active
    risk_level: low
    allowed_tools:
      - demo.echo_task_summary
      - demo.write_demo_note
    tags:
      - demo
      - note
      - local
    memory_scope: none
    confirmation_policy: inherit_tool_policy
    owner: local
    # ── Plan 3 manifest foundation 新增字段 ──
    when_to_use: >
      用户需要记录任务、创建待办、写笔记、做备忘时选择此 skill。
      适用于对话中产生需要持久化的信息时。
    when_not_to_use: >
      不要用于代码编辑、git 操作、文件系统操作。
    triggers:
      - "写笔记"
      - "记录任务"
      - "待办"
      - "备忘"
      - "记个笔记"
    negative_triggers:
      - "写代码"
      - "git commit"
    aliases:
      - "note"
      - "笔记"
      - "demo-note"
    locale: zh-CN
    resources:
      references: []
      scripts: []
      templates: []
      tests: []
      dogfood: []
    ---
    # Demo Note Maker Skill

    这是 body 内容。
    """


def _valid_frontmatter_minimal() -> str:
    """返回仅含必填字段的旧格式 SKILL.md（无 Plan 3 新字段）。"""
    return """
    ---
    name: old-skill
    description: 一个没有新字段的旧 skill。
    version: 0.1.0
    status: active
    risk_level: low
    ---
    # Old Skill

    旧格式 body。
    """


# ==================================================================
# M01: 新字段默认值
# ==================================================================

def test_new_manifest_fields_default_to_none():
    """M01: SkillManifest 新字段在不提供时应为默认值 None/空 tuple。

    RED: SkillManifest 尚无 when_to_use / triggers / aliases 等字段，
    此测试预期因 AttributeError 或 TypeError 而失败。
    """
    frontmatter = """
    ---
    name: minimal-skill
    description: 最小 skill。
    version: 0.1.0
    status: active
    risk_level: low
    ---
    # Minimal
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "minimal-skill"
        path = _write_skill_md(frontmatter, root)
        manifest = load_skill_manifest(path)

        # 新字段未提供 → 默认值
        assert manifest.when_to_use is None, (
            "when_to_use 应默认为 None"
        )
        assert manifest.when_not_to_use is None, (
            "when_not_to_use 应默认为 None"
        )
        assert manifest.triggers == (), (
            "triggers 应默认为空 tuple"
        )
        assert manifest.negative_triggers == (), (
            "negative_triggers 应默认为空 tuple"
        )
        assert manifest.aliases == (), (
            "aliases 应默认为空 tuple"
        )
        assert manifest.locale is None, (
            "locale 应默认为 None"
        )


# ==================================================================
# M02: triggers 解析为 tuple
# ==================================================================

def test_triggers_parsed_as_tuple():
    """M02: YAML frontmatter 中的 triggers 列表应解析为 tuple[str, ...]。

    RED: validate_manifest() 尚未处理 triggers 字段，
    此测试预期因 SkillManifest 无 triggers 字段而失败。
    """
    frontmatter = """
    ---
    name: triggered-skill
    description: 带 triggers 的 skill。
    version: 0.1.0
    status: active
    risk_level: low
    triggers:
      - "写笔记"
      - "记录任务"
      - "待办"
    ---
    # Triggered
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "triggered-skill"
        path = _write_skill_md(frontmatter, root)
        manifest = load_skill_manifest(path)

        assert isinstance(manifest.triggers, tuple), (
            f"triggers 应为 tuple，实际为 {type(manifest.triggers)}"
        )
        assert manifest.triggers == ("写笔记", "记录任务", "待办"), (
            f"triggers 值不匹配: {manifest.triggers}"
        )


def test_aliases_parsed_as_tuple():
    """M02 扩展: aliases 列表应解析为 tuple[str, ...]。

    RED: validate_manifest() 尚未处理 aliases 字段。
    """
    frontmatter = """
    ---
    name: aliased-skill
    description: 带 aliases 的 skill。
    version: 0.1.0
    status: active
    risk_level: low
    aliases:
      - "note"
      - "笔记"
    ---
    # Aliased
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "aliased-skill"
        path = _write_skill_md(frontmatter, root)
        manifest = load_skill_manifest(path)

        assert manifest.aliases == ("note", "笔记"), (
            f"aliases 值不匹配: {manifest.aliases}"
        )


def test_negative_triggers_parsed_as_tuple():
    """M02 扩展: negative_triggers 列表应解析为 tuple[str, ...]。

    RED: validate_manifest() 尚未处理 negative_triggers 字段。
    """
    frontmatter = """
    ---
    name: guarded-skill
    description: 带 negative_triggers 的 skill。
    version: 0.1.0
    status: active
    risk_level: low
    negative_triggers:
      - "写代码"
      - "git commit"
    ---
    # Guarded
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "guarded-skill"
        path = _write_skill_md(frontmatter, root)
        manifest = load_skill_manifest(path)

        assert manifest.negative_triggers == ("写代码", "git commit"), (
            f"negative_triggers 值不匹配: {manifest.negative_triggers}"
        )


def test_full_new_fields_parsed_correctly():
    """M02 扩展: 所有新字段同时提供时应全部正确解析。

    RED: validate_manifest() 尚未处理新字段。
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "demo-note-maker"
        path = _write_skill_md(_valid_frontmatter_with_new_fields(), root)
        manifest = load_skill_manifest(path)

        assert manifest.name == "demo-note-maker"
        assert "记录任务" in manifest.when_to_use
        assert "代码编辑" in manifest.when_not_to_use
        assert len(manifest.triggers) == 5
        assert "写笔记" in manifest.triggers
        assert len(manifest.negative_triggers) == 2
        assert "写代码" in manifest.negative_triggers
        assert len(manifest.aliases) == 3
        assert "note" in manifest.aliases
        assert manifest.locale == "zh-CN"


# ==================================================================
# M03: 旧 SKILL.md 向后兼容
# ==================================================================

def test_old_skill_md_without_new_fields_passes_validation():
    """M03: 不带 Plan 3 新字段的旧 SKILL.md 仍应通过 validate_manifest。

    这是向后兼容性 contract——旧 skill 不应因缺少新字段而加载失败。
    预期 PASS（当前 validator 不要求新字段）。
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "old-skill"
        path = _write_skill_md(_valid_frontmatter_minimal(), root)
        manifest = load_skill_manifest(path)

        assert manifest.name == "old-skill"
        assert manifest.status == "active"
        assert manifest.is_visible() is True


def test_old_skill_md_new_fields_default_to_sensible_values():
    """M03 扩展: 旧 SKILL.md 的新字段应回退到安全的默认值。

    预期 PASS（当前 validator 用默认值构造 SkillManifest，新字段不存在
    时 SkillManifest 构造会失败——这是 M01 验证的 RED 行为）。
    一旦新字段加入 SkillManifest，此测试验证默认值的安全性。
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "old-skill"
        path = _write_skill_md(_valid_frontmatter_minimal(), root)
        manifest = load_skill_manifest(path)

        # 旧 skill 没有声明新字段 → 不应意外匹配任何 trigger
        assert manifest.triggers == ()
        assert manifest.negative_triggers == ()
        assert manifest.aliases == ()
        # 没有 when_to_use → retriever 不能依赖它做 routing
        assert manifest.when_to_use is None
        assert manifest.when_not_to_use is None
        # locale 未声明 → None
        assert manifest.locale is None


# ==================================================================
# M04: when_to_use 在 raw_frontmatter 中可审计
# ==================================================================

def test_when_to_use_preserved_in_raw_frontmatter():
    """M04: when_to_use 字段应在 raw_frontmatter 中完整保留，供审计。

    预期 PASS——当前 _redact_value 递归处理整个 raw dict，
    非 secret 值不会被修改。
    """
    frontmatter = """
    ---
    name: auditable-skill
    description: 可审计的 skill。
    version: 0.1.0
    status: active
    risk_level: low
    when_to_use: >
      仅当用户明确请求审计功能时使用此 skill。
      不要在日常对话中自动激活。
    ---
    # Auditable
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "auditable-skill"
        path = _write_skill_md(frontmatter, root)
        manifest = load_skill_manifest(path)

        # raw_frontmatter 应包含原始 when_to_use
        assert "when_to_use" in manifest.raw_frontmatter, (
            "raw_frontmatter 应包含 when_to_use 字段"
        )
        raw_wtu = manifest.raw_frontmatter["when_to_use"]
        assert "审计功能" in str(raw_wtu), (
            f"when_to_use 内容应完整保留，实际: {raw_wtu!r}"
        )
        assert "不要在日常对话中自动激活" in str(raw_wtu), (
            "when_to_use 的约束信息不应丢失"
        )


def test_triggers_preserved_in_raw_frontmatter():
    """M04 扩展: triggers 列表应在 raw_frontmatter 中原样保留。"""
    frontmatter = """
    ---
    name: triggered-audit
    description: 带 triggers 的可审计 skill。
    version: 0.1.0
    status: active
    risk_level: low
    triggers:
      - "审计"
      - "检查"
    ---
    # Triggered Audit
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "triggered-audit"
        path = _write_skill_md(frontmatter, root)
        manifest = load_skill_manifest(path)

        assert "triggers" in manifest.raw_frontmatter
        raw_triggers = manifest.raw_frontmatter["triggers"]
        assert isinstance(raw_triggers, list)
        assert "审计" in raw_triggers
        assert "检查" in raw_triggers


# ==================================================================
# M05: SkillDescriptor.aliases 可访问
# ==================================================================

def test_aliases_included_in_descriptor():
    """M05: SkillDescriptor 应暴露 aliases/triggers/negative_triggers 作为 Level 1 公开元数据。

    aliases/triggers/negative_triggers 必须是 Level 1 公开元数据——
    SkillSelector 需要通过 descriptor 访问它们做确定性匹配。
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "aliased-skill"
        path = _write_skill_md(_valid_frontmatter_with_new_fields(), root)
        manifest = load_skill_manifest(path)
        desc = manifest.to_descriptor()

        assert isinstance(desc, SkillDescriptor)
        # aliases
        assert hasattr(desc, "aliases"), (
            "SkillDescriptor 必须暴露 aliases 字段供 retriever 使用"
        )
        assert isinstance(desc.aliases, tuple)
        assert "note" in desc.aliases
        assert "笔记" in desc.aliases
        assert "demo-note" in desc.aliases
        # triggers
        assert hasattr(desc, "triggers"), (
            "SkillDescriptor 必须暴露 triggers 字段供 selector 使用"
        )
        assert isinstance(desc.triggers, tuple)
        assert "写笔记" in desc.triggers
        # negative_triggers
        assert hasattr(desc, "negative_triggers"), (
            "SkillDescriptor 必须暴露 negative_triggers 字段供 selector 使用"
        )
        assert isinstance(desc.negative_triggers, tuple)
        assert "写代码" in desc.negative_triggers


def test_descriptor_aliases_empty_for_old_skills():
    """M05 扩展: 旧 skill 的 descriptor Plan 3 字段应为空 tuple。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "old-skill"
        path = _write_skill_md(_valid_frontmatter_minimal(), root)
        manifest = load_skill_manifest(path)
        desc = manifest.to_descriptor()

        assert desc.aliases == ()
        assert desc.triggers == ()
        assert desc.negative_triggers == ()


# ==================================================================
# M06: 新字段 secret redact
# ==================================================================

def test_new_fields_redacted_in_audit():
    """M06: 新字段值若包含疑似 secret 模式，应在 raw_frontmatter 中被 redact。

    预期 PASS——_redact_value() 递归处理整个 raw dict，无论字段名是什么，
    只要值匹配 secret pattern 就会被替换为 <REDACTED>。
    """
    # when_to_use 包含一个看起来像 API key 的长 base64 串
    frontmatter = """
    ---
    name: leaky-skill
    description: 不小心在 when_to_use 里写了 key。
    version: 0.1.0
    status: active
    risk_level: low
    when_to_use: >
      使用此 skill 时需要 API key:
      dGhpcyBpc250IGEgcmVhbCBrZXkgYnV0IGl0IGxvb2tzIGxpa2Ugb25lIGJlY2F1c2UgaXQgaXMgdmVyeSBsb25n
    ---
    # Leaky
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "leaky-skill"
        path = _write_skill_md(frontmatter, root)
        manifest = load_skill_manifest(path)

        raw_wtu = manifest.raw_frontmatter.get("when_to_use")
        # 包含长 base64-like 字符串的 when_to_use 应被 redact
        if raw_wtu == "<REDACTED>":
            # 通过了——长 base64 串被正确识别和 redact
            pass
        else:
            # 可能长 base64-like 串没有被 _detect_secret 匹配到
            # 这取决于 _SECRET_PATTERNS 的覆盖范围
            # 但至少 when_to_use 不应包含原始的长 base64 串
            raw_str = str(raw_wtu)
            # 长 base64 串不应在 raw_frontmatter 中裸奔
            long_b64 = (
                "dGhpcyBpc250IGEgcmVhbCBrZXkgYnV0IGl0IGxvb2tzIGxpa2Ugb25lIGJl"
                "Y2F1c2UgaXQgaXMgdmVyeSBsb25n"
            )
            assert long_b64 not in raw_str, (
                f"长 base64-like 串不应在 raw_frontmatter 中裸奔: {raw_str[:100]}..."
            )


def test_trigger_field_with_secret_redacted():
    """M06 扩展: triggers 列表中的 secret-like 值应被 redact。"""
    frontmatter = """
    ---
    name: leaky-triggers
    description: triggers 中包含疑似 key。
    version: 0.1.0
    status: active
    risk_level: low
    triggers:
      - "正常 trigger"
      - "sk-ant-api-this-is-a-fake-key-for-testing-purposes-only"
    ---
    # Leaky Triggers
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "leaky-triggers"
        path = _write_skill_md(frontmatter, root)
        manifest = load_skill_manifest(path)

        raw_triggers = manifest.raw_frontmatter.get("triggers", [])
        # 至少有一个值被 redact
        redacted_count = sum(1 for v in raw_triggers if v == "<REDACTED>")
        assert redacted_count >= 1, (
            f"triggers 中的 sk-ant-api-... 应被 redact，实际: {raw_triggers}"
        )


def test_validate_manifest_rejects_secret_in_name_field():
    """M06 扩展: 确认现有 secret 检测仍然有效（回归保护）。

    新字段的加入不应削弱现有 secret 检测。
    """
    from agent.skill_system.errors import CODE_SECRET_DETECTED, SkillLoadError

    frontmatter = """
    ---
    name: sk-ant-api-this-is-a-fake-key-for-testing
    description: name 中包含疑似 API key。
    version: 0.1.0
    status: active
    risk_level: low
    ---
    # Bad Name
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "bad-name"
        path = _write_skill_md(frontmatter, root)
        with pytest.raises(SkillLoadError) as exc_info:
            load_skill_manifest(path)
        assert exc_info.value.code == CODE_SECRET_DETECTED
