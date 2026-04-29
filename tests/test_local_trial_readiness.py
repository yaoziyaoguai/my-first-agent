"""v0.3.x local-first trial readiness 守护测试。

本文件不测 Runtime 行为，只测「外部用户 clone 仓库后能不能在本地起来」
所必需的发布物：

- README.md 含 quickstart 必备命令（venv / pip install / main.py / health /
  logs / pytest）
- `.env.example` 存在、不含真实 secret
- `.gitignore` 覆盖本地运行产物（`.env` / `state.json` / `runs/` /
  `sessions/` / `agent_log.jsonl` / `summary.md`）
- 启动屏文案仍把 Skill 标为「实验性」，不会再印 `/reload_skills`
  （v0.3 M3 honesty pass 的不变量）
- `docs/V0_3_LOCAL_TRIAL.md` / checklist 存在并包含外部读者会用到的章节

约束：这些断言**只**保护「公开发布物的存在性 + 关键字段」，不绑定
全文文案。措辞调整不应让本测试假阳性。
"""

from __future__ import annotations

from pathlib import Path
import re

import main as main_module

REPO_ROOT = Path(__file__).resolve().parent.parent


def _read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def test_readme_quickstart_lists_essential_commands() -> None:
    """README 必须能让外部用户找到本地起步的关键命令。

    这里只检查「关键命令片段」是否出现，不绑定章节标题或顺序。
    """
    text = _read("README.md")
    must_contain = [
        "python3 -m venv .venv",
        "pip install -r requirements.txt",
        ".env.example",
        ".venv/bin/python main.py",
        "main.py health",
        "main.py logs",
        "pytest",
    ]
    missing = [s for s in must_contain if s not in text]
    assert not missing, f"README.md 缺少 quickstart 关键命令：{missing}"


def test_env_example_exists_and_carries_no_real_secret() -> None:
    """`.env.example` 是配置模板，必须不含真实 key。

    断言策略：必须存在；变量名出现但 `ANTHROPIC_API_KEY=` 后面只能是空
    或者注释掉的占位（`#` 开头的行不算赋值）。
    """
    path = REPO_ROOT / ".env.example"
    assert path.exists(), ".env.example 必须存在作为外部用户的配置模板"
    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            continue
        if "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        if "API_KEY" in key.upper() or "SECRET" in key.upper() or "TOKEN" in key.upper():
            assert value.strip() == "", (
                f".env.example 在赋值行 {key!r} 写了非空值，可能是真实 secret"
            )


def test_gitignore_covers_local_runtime_artifacts() -> None:
    """`.gitignore` 必须覆盖外部用户 clone 后会本地产生的运行时产物，
    避免他们 fork+push 时意外把这些泄到 GitHub。
    """
    text = _read(".gitignore")
    must_ignore = [
        ".env",
        "state.json",
        "runs/",
        "sessions/",
        "agent_log.jsonl",
        "summary.md",
        "workspace/",
        ".venv",
    ]
    missing = [pat for pat in must_ignore if pat not in text]
    assert not missing, f".gitignore 缺少必备运行时产物条目：{missing}"


def test_local_trial_doc_exists_with_outsider_sections() -> None:
    """`docs/V0_3_LOCAL_TRIAL.md` 是外部试用主入口。

    断言：文件存在 + 含外部读者必读的关键 section 关键字（不绑定全文）。
    """
    path = REPO_ROOT / "docs" / "V0_3_LOCAL_TRIAL.md"
    assert path.exists(), "docs/V0_3_LOCAL_TRIAL.md 必须存在作为本地试用指南"
    text = path.read_text(encoding="utf-8")
    landmarks = [
        "local-first",
        "Prerequisites",
        ".env.example",
        "main.py health",
        "main.py logs",
        "agent_log.jsonl",
        "实验",
    ]
    # 大小写不敏感地匹配
    lower = text.lower()
    missing = [s for s in landmarks if s.lower() not in lower]
    assert not missing, (
        f"docs/V0_3_LOCAL_TRIAL.md 缺少外部读者必读关键字：{missing}"
    )


def test_local_trial_checklist_exists_and_stays_roadmap_bounded() -> None:
    """v0.3.2 checklist 是人工试用入口，不是为了凑文档覆盖率。

    这条测试守护 Roadmap 防漂移：清单必须覆盖 trial 关键路径，同时继续明确
    Skill 只是 experimental/demo-level，且不会把 v0.4+ 能力写成当前已实现能力。
    """
    path = REPO_ROOT / "docs" / "V0_3_LOCAL_TRIAL_CHECKLIST.md"
    assert path.exists(), "v0.3.2 本地试用清单必须存在"
    text = path.read_text(encoding="utf-8")
    lower = text.lower()

    required_terms = [
        "python main.py --shell",
        "final answer",
        "request_user_input",
        "tool.completed",
        "tool.rejected",
        "tool.user_rejected",
        "tool.failed",
        "checkpoint/resume",
        "python main.py health",
        "python main.py health --json",
        "python main.py logs --tail 5",
        "现象",
        "命令/输入",
        "期望",
        "实际",
        "是否阻塞",
        "建议归类",
    ]
    missing = [term for term in required_terms if term.lower() not in lower]
    assert not missing, f"local trial checklist 缺少关键试用项：{missing}"

    assert "experimental" in lower
    assert "demo-level" in lower
    assert "skill" in lower

    # v0.4+ 能力可以作为边界出现，但附近必须带否定/规划标记，不能被写成已交付。
    for term in ["Textual", "sub-agent", "Reflect", "slash command"]:
        hits = list(re.finditer(re.escape(term), text, flags=re.IGNORECASE))
        assert hits, f"checklist 应显式登记 {term} 边界"
        assert any(
            any(marker in text[max(0, hit.start() - 120): hit.end() + 120]
                for marker in ["不做", "不是", "不会", "planning", "v0.4"])
            for hit in hits
        ), f"{term} 出现时必须带非目标/规划边界，避免能力夸大"


def test_local_trial_checklist_referenced_from_readme() -> None:
    """README 是外部入口，必须能把用户导到短 checklist。

    这里不绑定 README 章节，只守护入口链接，防止清单落地后无人能发现。
    """
    text = _read("README.md")
    assert "docs/V0_3_LOCAL_TRIAL_CHECKLIST.md" in text


def test_local_trial_checklist_commands_match_cli_entrypoints(monkeypatch, capsys) -> None:
    """清单里的核心命令要和 main.py 参数解析保持一致。

    这是轻量防漂移测试：不启动真实交互、不调用模型，只验证 checklist 承诺的
    health/logs/shell 入口仍由 CLI wiring 接住。
    """
    import agent.health_check as hc

    monkeypatch.setattr(
        hc,
        "collect_health_results",
        lambda: {
            "workspace_lint": {
                "status": "pass",
                "current_value": "0 文件",
                "path": "workspace",
                "risk": "无",
                "action": "无需操作",
                "message": "ok",
            }
        },
    )
    assert main_module.main(["health"]) == 0
    assert "项目健康检查报告" in capsys.readouterr().out

    assert main_module.main(["health", "--json"]) == 0
    assert '"overall"' in capsys.readouterr().out

    assert main_module.main(["logs", "--tail", "5"]) == 0
    assert "Runtime logs" in capsys.readouterr().out

    calls = []
    monkeypatch.setattr(main_module, "init_session", lambda: calls.append("init"))
    monkeypatch.setattr(main_module, "try_resume_from_checkpoint", lambda: calls.append("resume"))
    monkeypatch.setattr(main_module, "main_loop", lambda: calls.append("loop"))
    monkeypatch.setattr(main_module, "_selected_input_backend", lambda: "simple")
    assert main_module.main(["--shell"]) == 0
    assert calls == ["init", "resume", "loop"]


def test_release_notes_v0_3_published() -> None:
    """RELEASE_NOTES_v0.3.md 是 v0.3.1 发布的主要外部参考。"""
    path = REPO_ROOT / "RELEASE_NOTES_v0.3.md"
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    for landmark in ["M1", "M2", "M3", "M4", "request_user_input", "676 passed"]:
        assert landmark in text, f"RELEASE_NOTES_v0.3.md 缺少关键内容：{landmark}"
