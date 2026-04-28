"""v0.3 M3 · Skill 体系坦诚化的回归守护测试。

这些测试**不验证 Skill 功能本身**（M3 不实现 Skill runtime），它们守护
「文案 / 文档 / 入口不再让用户误以为 Skill 已经成熟」这个不变量。

历史背景：v0.2 启动屏曾印 `'/reload_skills' 重新加载 skill`，但主循环
从来没有 slash command 解析器，那行字符串纯粹误导。M3 删掉它后，需要
回归测试守护它不会再被悄悄复活。
"""
from __future__ import annotations

from pathlib import Path

from agent import cli_renderer
from agent.skills.registry import SkillRegistry

PROJECT_ROOT = Path(__file__).resolve().parents[1]


# ---------- 启动文案诚实度 ----------

def test_session_header_does_not_advertise_dead_slash_command():
    """slash command 在 v0.1 已下线，启动屏不应再宣称 /reload_skills 可用。"""
    out = cli_renderer.render_session_header(session_id="x", cwd=".")
    assert "/reload_skills" not in out
    # 不应出现任何 slash command 提示，避免下次又被人加回去
    assert "/reload" not in out


def test_session_header_marks_skill_as_experimental():
    """启动屏必须明确告诉用户 Skill 仍是实验性能力。"""
    out = cli_renderer.render_session_header(session_id="x", cwd=".")
    assert "实验性" in out
    # 指向 status doc，让用户知道去哪看现状
    assert "V0_3_SKILL_SYSTEM_STATUS" in out or "skill" in out.lower()


# ---------- README / 计划文档诚实度 ----------

def test_readme_marks_skill_as_experimental():
    text = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    # README 必须有 v0.3 M3 实验性声明指针
    assert "V0_3_SKILL_SYSTEM_STATUS" in text
    assert "实验性" in text
    # README 里若提到 /reload_skills，必须是在「不再印 / 历史误导」这种否定语境
    if "/reload_skills" in text:
        assert "不再印" in text or "历史" in text or "已删" in text or "误导" in text


def test_skill_status_doc_exists_and_covers_key_sections():
    doc = PROJECT_ROOT / "docs" / "V0_3_SKILL_SYSTEM_STATUS.md"
    assert doc.exists(), "M3 必须落地 docs/V0_3_SKILL_SYSTEM_STATUS.md"
    text = doc.read_text(encoding="utf-8")
    # 必须明确登记 /reload_skills 是死代码
    assert "/reload_skills" in text
    # 必须有「实验性」字样降预期
    assert "实验性" in text
    # 必须明确不做 sub-agent
    assert "sub-agent" in text.lower()


def test_planning_marks_m3_as_status_clarification_not_runtime():
    text = (PROJECT_ROOT / "docs" / "V0_3_PLANNING.md").read_text(encoding="utf-8")
    # M3 段必须出现「状态澄清」类语义，且不应承诺实现 Skill runtime
    assert "M3" in text
    # 不能宣称 M3 实现了 sub-agent / 权限白名单 / activation policy
    m3_section = text.split("M3")[1].split("M4")[0]
    for forbidden in ("sub-agent 触发", "Skill marketplace", "远端"):
        assert forbidden not in m3_section.split("不做")[0] if "不做" in m3_section else True


# ---------- Skill registry 优雅降级 ----------

def test_registry_handles_missing_skills_dir(tmp_path):
    """skills/ 目录不存在时 registry 不应抛异常，应返回空清单。"""
    reg = SkillRegistry(skills_dir=tmp_path / "nonexistent")
    reg.discover_skills()
    assert reg.list_skills() == []
    assert reg.count() == 0


def test_registry_handles_empty_skills_dir(tmp_path):
    """skills/ 目录存在但为空时也不应崩。"""
    empty = tmp_path / "skills"
    empty.mkdir()
    reg = SkillRegistry(skills_dir=empty)
    reg.discover_skills()
    assert reg.list_skills() == []
    assert reg.get_warnings() == []


def test_registry_skips_non_directory_entries(tmp_path):
    """skills/ 下的散文件 / 隐藏目录应被静默跳过，不计入 warnings。"""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "stray.txt").write_text("not a skill")
    (skills_dir / ".hidden").mkdir()
    reg = SkillRegistry(skills_dir=skills_dir)
    reg.discover_skills()
    assert reg.count() == 0
    # 散文件 / 隐藏目录不应产生 warning，否则用户每次启动都被吓
    assert reg.get_warnings() == []


# ---------- Skill section 注入对主流程的影响 ----------

def test_build_skills_section_returns_empty_when_no_skills(tmp_path, monkeypatch):
    """没有 skill 时 prompt 段应该完全为空字符串，不能注入空标题。"""
    from agent.skills import registry as reg_mod

    fake_reg = SkillRegistry(skills_dir=tmp_path / "none")
    fake_reg.discover_skills()
    monkeypatch.setattr(reg_mod, "_registry", fake_reg)

    section = reg_mod.build_skills_section()
    assert section == ""


# ---------- 没有 Skill 单测的事实登记 ----------

def test_status_doc_acknowledges_no_skill_unit_tests():
    """status doc 必须诚实声明当前没有 skill 单元测试，避免后续读者误以为
    Skill 子系统是受测过的。"""
    doc = (PROJECT_ROOT / "docs" / "V0_3_SKILL_SYSTEM_STATUS.md").read_text(
        encoding="utf-8"
    )
    assert "没有 skill 单元测试" in doc
