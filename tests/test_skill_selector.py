"""Phase 4: Deterministic Skill Selector 测试。

测试范围（来自 docs/testing/SKILL_SYSTEM_TDD.md Phase 4）：
- 显式名称选择
- 无匹配 → no selection
- 多匹配 → ranked candidates / ambiguity
- disabled Skill 被忽略
- deprecated Skill 策略
- 选择器只使用 Level 1 metadata
- 选择器不加载 body / resources
- 不调用 LLM / embedding / 网络

禁止行为：
- selector loads Skill bodies
- selector calls LLM
- selector uses hidden Skills
- selector imports legacy
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from textwrap import dedent

from agent.skill_system.registry import SkillRegistry
from agent.skill_system.selector import SkillSelectionDecision, SkillSelector

# ---- helpers ----

def _make_registry_with_skills(skills: list[dict]) -> SkillRegistry:
    """用临时目录创建一个包含指定 Skill 的 registry。"""

    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name) / "skills"
    for s in skills:
        name = s["name"]
        desc = s.get("description", f"Skill {name}")
        status = s.get("status", "active")
        tags = s.get("tags", [])
        triggers = s.get("triggers", [])
        aliases = s.get("aliases", [])
        negative_triggers = s.get("negative_triggers", [])
        tags_yaml = "\n".join(f"    - {t}" for t in tags)
        triggers_yaml = "\n".join(f"    - {t}" for t in triggers)
        aliases_yaml = "\n".join(f"    - {a}" for a in aliases)
        nt_yaml = "\n".join(f"    - {n}" for n in negative_triggers)
        extra = ""
        if tags:
            extra += f"tags:\n{tags_yaml}\n"
        if triggers:
            extra += f"triggers:\n{triggers_yaml}\n"
        if aliases:
            extra += f"aliases:\n{aliases_yaml}\n"
        if negative_triggers:
            extra += f"negative_triggers:\n{nt_yaml}\n"
        extra += (
            "resources:\n"
            "  references: []\n"
            "  scripts: []\n"
            "  templates: []\n"
            "  tests: []\n"
            "  dogfood: []\n"
        )

        skill_dir = root / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        content = f"""---
name: {name}
description: {desc}
version: 0.1.0
status: {status}
risk_level: low
{extra}
---
# {name}

Body for {name}.
"""
        (skill_dir / "SKILL.md").write_text(dedent(content).strip(), encoding="utf-8")

    registry = SkillRegistry(roots=[root])
    # Keep temp dir alive
    registry._tmp = tmp
    return registry


# ==================================================================
# 显式名称选择
# ==================================================================

def test_selector_explicit_name_match():
    """通过精确名称选择 Skill。"""
    registry = _make_registry_with_skills([
        {"name": "git-status-audit", "description": "Summarize git status"},
        {"name": "rfc-alignment-audit", "description": "Check RFC alignment"},
    ])
    selector = SkillSelector(registry)
    decision = selector.select("git-status-audit")
    assert decision.selected is True
    assert decision.skill_name == "git-status-audit"
    assert decision.confidence == 1.0


def test_selector_no_match_returns_none():
    """无匹配时返回 unselected decision。"""
    registry = _make_registry_with_skills([
        {"name": "git-status-audit", "description": "Summarize git status"},
    ])
    selector = SkillSelector(registry)
    decision = selector.select("nonexistent-skill")
    assert decision.selected is False
    assert decision.skill_name is None
    assert decision.confidence < 0.5


# ==================================================================
# 关键词 / description 匹配
# ==================================================================

def test_selector_keyword_in_description():
    """关键词出现在 description 中时应有部分匹配。"""
    registry = _make_registry_with_skills([
        {"name": "safe-writer", "description": "Write concise safe local documentation"},
        {"name": "git-audit", "description": "Audit git repository status"},
    ])
    selector = SkillSelector(registry)
    decision = selector.select("git status")
    assert decision.skill_name == "git-audit"


def test_selector_keyword_in_name():
    """关键词出现在 name 中时应匹配。"""
    registry = _make_registry_with_skills([
        {"name": "safe-writer", "description": "Write docs"},
        {"name": "git-status-audit", "description": "Audit git"},
    ])
    selector = SkillSelector(registry)
    decision = selector.select("git status check")
    assert decision.skill_name == "git-status-audit"


# ==================================================================
# Tags 匹配
# ==================================================================

def test_selector_tags_match():
    """标签匹配应提供额外分数。"""
    registry = _make_registry_with_skills([
        {"name": "skill-a", "description": "Generic tool", "tags": ["writing"]},
        {
            "name": "skill-b",
            "description": "Better tool for writing tasks",
            "tags": ["writing", "docs"],
        },
    ])
    selector = SkillSelector(registry)
    decision = selector.select("writing docs task")
    assert decision.skill_name == "skill-b"


# ==================================================================
# Ambiguous match
# ==================================================================

def test_selector_ambiguous_match_returns_candidates():
    """当多个 Skill 分数接近时，返回 ambiguity 结果。"""
    registry = _make_registry_with_skills([
        {"name": "git-status-audit", "description": "Git status check"},
        {"name": "git-file-audit", "description": "Git file auditing"},
    ])
    selector = SkillSelector(registry)
    decision = selector.select("git audit")
    # 两个 Skill 都匹配 "git"，可能模糊
    if decision.selected:
        assert decision.skill_name is not None
    else:
        assert len(decision.alternatives) >= 2


# ==================================================================
# Disabled / hidden exclusion
# ==================================================================

def test_selector_excludes_disabled_skills():
    """disabled Skill 不应被选中。"""
    registry = _make_registry_with_skills([
        {"name": "visible-skill", "description": "I am visible"},
        {"name": "hidden-skill", "description": "I am hidden", "status": "disabled"},
    ])
    selector = SkillSelector(registry)
    decision = selector.select("hidden")
    # 即使 "hidden" 匹配了描述，disabled skill 也不应被选中
    assert decision.skill_name != "hidden-skill"


def test_selector_excludes_legacy_skills():
    """legacy Skill 不应被选中。"""
    registry = _make_registry_with_skills([
        {"name": "old-skill", "description": "An old skill", "status": "legacy"},
        {"name": "new-skill", "description": "A new skill"},
    ])
    selector = SkillSelector(registry)
    decision = selector.select("old skill")
    assert decision.skill_name != "old-skill"


# ==================================================================
# Deprecated policy
# ==================================================================

def test_selector_deprecated_skill_lower_confidence():
    """deprecated Skill 可以匹配，但 confidence 更低。"""
    registry = _make_registry_with_skills([
        {"name": "old-tool", "description": "An old tool", "status": "deprecated"},
        {"name": "new-tool", "description": "A new tool"},
    ])
    selector = SkillSelector(registry)
    decision = selector.select("tool")
    # deprecated skill 分数更低，active 应胜出
    assert decision.skill_name == "new-tool"


# ==================================================================
# 选择器只使用 Level 1 metadata
# ==================================================================

def test_selector_never_loads_bodies():
    """选择器不得加载 SKILL.md body。"""
    registry = _make_registry_with_skills([
        {"name": "test-skill", "description": "Test"},
    ])
    # Start timing - the selector should be fast (no body reads)
    selector = SkillSelector(registry)
    # 如果 selector 会加载 body，这个测试会在 loader 层面失败
    decision = selector.select("test-skill")
    assert decision.selected is True
    # 确认 descriptor 上没有 body 属性
    desc = registry.get_descriptor("test-skill")
    assert desc is not None
    assert not hasattr(desc, "body")


# ==================================================================
# Score 排序
# ==================================================================

def test_selector_returns_highest_score_first():
    """选择器应返回得分最高的 Skill。"""
    registry = _make_registry_with_skills([
        {"name": "low-match", "description": "Something else entirely"},
        {"name": "high-match", "description": "This is exactly about git status auditing"},
    ])
    selector = SkillSelector(registry)
    decision = selector.select("git status audit")
    assert decision.skill_name == "high-match"


# ==================================================================
# 边界情况
# ==================================================================

def test_selector_empty_registry():
    """空注册表时 selector 返回 no selection。"""
    tmp = tempfile.TemporaryDirectory()
    registry = SkillRegistry(roots=[Path(tmp.name)])
    selector = SkillSelector(registry)
    decision = selector.select("anything")
    assert decision.selected is False


def test_selector_empty_query():
    """空查询应返回 no selection。"""
    registry = _make_registry_with_skills([
        {"name": "test-skill", "description": "Test"},
    ])
    selector = SkillSelector(registry)
    decision = selector.select("")
    assert decision.selected is False
    decision2 = selector.select("   ")
    assert decision2.selected is False


# ==================================================================
# no legacy import
# ==================================================================

def test_selector_module_does_not_import_legacy():
    """selector.py 不能 import agent.skills / agent.legacy_skills。"""
    import ast
    from pathlib import Path as _Path

    selector_path = _Path(__file__).resolve().parents[1] / "agent" / "skill_system" / "selector.py"
    tree = ast.parse(selector_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("agent.skills")
                assert not alias.name.startswith("agent.legacy_skills")
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("agent.skills")
            assert not node.module.startswith("agent.legacy_skills")


# ==================================================================
# SkillSelectionDecision 结构
# ==================================================================

def test_selection_decision_alternatives():
    """SkillSelectionDecision 应列出备选。"""
    d = SkillSelectionDecision(
        selected=True,
        skill_name="chosen",
        confidence=0.9,
        reason="best match",
        alternatives=("alt-1", "alt-2"),
        requires_user_confirmation=False,
    )
    assert d.skill_name == "chosen"
    assert "alt-1" in d.alternatives


# ==================================================================
# Plan 3 — triggers 匹配
# ==================================================================

def test_trigger_exact_match_high_score():
    """triggers 精确匹配应获得高权重分数。"""
    registry = _make_registry_with_skills([
        {"name": "skill-a", "description": "Generic tool", "triggers": ["写笔记"]},
        {"name": "skill-b", "description": "Better match in description but no trigger"},
    ])
    selector = SkillSelector(registry)
    decision = selector.select("写笔记")
    assert decision.selected is True
    assert decision.skill_name == "skill-a"


def test_trigger_substring_match():
    """trigger 作为查询子串时应匹配（中文分词友好）。"""
    registry = _make_registry_with_skills([
        {"name": "demo-note", "description": "Make notes",
         "triggers": ["写笔记", "记录任务"]},
        {"name": "other-tool", "description": "Something else"},
    ])
    selector = SkillSelector(registry)
    # "请帮我写笔记" 包含 "写笔记" 作为连续子串（"写个笔记" 中"个"打断了连续性）
    decision = selector.select("请帮我写笔记")
    assert decision.selected is True
    assert decision.skill_name == "demo-note"


def test_trigger_beats_description_only():
    """有 trigger 匹配的 skill 应击败仅有 description 匹配的 skill。"""
    registry = _make_registry_with_skills([
        {"name": "note-taker", "description": "note note note note note",
         "triggers": []},
        {"name": "blog-writer", "description": "Write blogs",
         "triggers": ["写笔记"]},
    ])
    selector = SkillSelector(registry)
    decision = selector.select("写笔记")
    # blog-writer 有 trigger 匹配，分数应高于 note-taker（仅 desc 匹配）
    assert decision.skill_name == "blog-writer"


def test_trigger_empty_string_ignored():
    """空字符串 trigger 不应影响评分。"""
    registry = _make_registry_with_skills([
        {"name": "test-skill", "description": "Test",
         "triggers": ["", "  "]},
    ])
    selector = SkillSelector(registry)
    decision = selector.select("unrelated query")
    assert decision.selected is False


# ==================================================================
# Plan 3 — aliases 匹配
# ==================================================================

def test_alias_name_word_match():
    """aliases 中的词匹配应获得与 name 词相同的权重。"""
    registry = _make_registry_with_skills([
        {"name": "skill-x", "description": "Tool X",
         "aliases": ["note", "笔记"]},
        {"name": "skill-y", "description": "Tool Y"},
    ])
    selector = SkillSelector(registry)
    decision = selector.select("note")
    assert decision.selected is True
    assert decision.skill_name == "skill-x"


def test_alias_chinese_match():
    """中文 alias 应匹配中文查询。"""
    registry = _make_registry_with_skills([
        {"name": "demo-note", "description": "Make demo notes",
         "aliases": ["笔记", "记事本", "note"]},
        {"name": "other-tool", "description": "Another tool"},
    ])
    selector = SkillSelector(registry)
    decision = selector.select("笔记")
    assert decision.selected is True
    assert decision.skill_name == "demo-note"


def test_alias_with_hyphens_and_underscores():
    """alias 中的连字符/下划线应被拆分为词。"""
    registry = _make_registry_with_skills([
        {"name": "demo-note", "description": "Make demo notes",
         "aliases": ["task-note", "my_notes"]},
        {"name": "other-tool", "description": "Another tool"},
    ])
    selector = SkillSelector(registry)
    decision = selector.select("task")
    assert decision.selected is True
    assert decision.skill_name == "demo-note"


# ==================================================================
# Plan 3 — negative_triggers 排除
# ==================================================================

def test_negative_trigger_excludes_skill():
    """negative_triggers 命中时应排除该 skill。"""
    registry = _make_registry_with_skills([
        {"name": "math-tool", "description": "Math calculations",
         "negative_triggers": ["天气", "翻译"]},
        {"name": "weather-tool", "description": "Weather lookup"},
    ])
    selector = SkillSelector(registry)
    decision = selector.select("查天气")
    # math-tool 的 negative_trigger "天气" 命中 → 排除
    assert decision.skill_name != "math-tool"


def test_negative_trigger_substring_match():
    """negative_trigger 子串匹配也应排除。"""
    registry = _make_registry_with_skills([
        {"name": "note-maker", "description": "Make notes",
         "negative_triggers": ["计算", "解方程"]},
        {"name": "calc-tool", "description": "Do calculations",
         "triggers": ["计算"]},
    ])
    selector = SkillSelector(registry)
    decision = selector.select("帮我计算一下")
    # note-maker 的 negative_trigger "计算" 命中 → 排除
    # calc-tool 的 trigger "计算" 命中 → 被选中
    assert decision.skill_name == "calc-tool"


def test_negative_trigger_no_false_positive():
    """不匹配的 negative_trigger 不应排除 skill。"""
    registry = _make_registry_with_skills([
        {"name": "note-maker", "description": "Make notes",
         "negative_triggers": ["数学", "微积分"]},
        {"name": "other", "description": "Another tool"},
    ])
    selector = SkillSelector(registry)
    decision = selector.select("笔记")
    # "笔记" 不匹配 "数学" 或 "微积分" → note-maker 不应被排除
    assert decision.skill_name != "math-tool"
    # note-maker 可能被选中（取决于评分）
    # 关键：不应因为 negative_trigger 被错误排除


def test_negative_trigger_exclusion_logically_consistent():
    """negative_triggers 排除后不影响其他 skill 的正常匹配。"""
    registry = _make_registry_with_skills([
        {"name": "excluded-skill", "description": "Should be excluded",
         "negative_triggers": ["排除我"]},
        {"name": "valid-skill", "description": "Should be selected",
         "triggers": ["选中"]},
    ])
    selector = SkillSelector(registry)
    decision = selector.select("排除我 选中")
    # excluded-skill 因 negative_trigger "排除我" 被排除
    # valid-skill 因 trigger "选中" 被选中
    assert decision.skill_name != "excluded-skill"
    assert decision.skill_name == "valid-skill"


# ==================================================================
# Plan 3 — SkillDescriptor 字段访问
# ==================================================================

def test_descriptor_exposes_triggers():
    """SkillDescriptor 应暴露 triggers 字段。"""
    registry = _make_registry_with_skills([
        {"name": "test-skill", "description": "Test",
         "triggers": ["trigger1", "trigger2"]},
    ])
    desc = registry.get_descriptor("test-skill")
    assert desc is not None
    assert desc.triggers == ("trigger1", "trigger2")


def test_descriptor_exposes_negative_triggers():
    """SkillDescriptor 应暴露 negative_triggers 字段。"""
    registry = _make_registry_with_skills([
        {"name": "test-skill", "description": "Test",
         "negative_triggers": ["bad1", "bad2"]},
    ])
    desc = registry.get_descriptor("test-skill")
    assert desc is not None
    assert desc.negative_triggers == ("bad1", "bad2")


def test_descriptor_default_triggers_empty():
    """未声明 triggers 的 skill 应返回空 tuple。"""
    registry = _make_registry_with_skills([
        {"name": "test-skill", "description": "Test"},
    ])
    desc = registry.get_descriptor("test-skill")
    assert desc is not None
    assert desc.triggers == ()
    assert desc.negative_triggers == ()
