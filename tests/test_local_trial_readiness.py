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


def test_readme_keeps_local_trial_entry_short() -> None:
    """README 只做入口，不复制整张试用清单。

    这是 Roadmap 防漂移：README 是 quickstart，不是 v0.3.2 trial 工单系统。
    如果把 checklist 表格复制进 README，后续命令/边界会出现两份事实源。
    """
    text = _read("README.md")
    assert "docs/V0_3_LOCAL_TRIAL_CHECKLIST.md" in text
    copied_markers = [
        "| 1 | 启动 shell |",
        "| 2 | 普通 final answer |",
        "建议归类：v0.3.2 blocking / v0.3.x patch / v0.4 planning",
    ]
    leaked = [marker for marker in copied_markers if marker in text]
    assert not leaked, f"README 不应复制 checklist 正文：{leaked}"


def test_local_trial_checklist_feedback_format_is_stable() -> None:
    """反馈格式是本地试用闭环的最小数据结构。

    这不是为了绑定文案，而是守护 Roadmap 边界：v0.3.2 只需要能把失败现象
    稳定归类为 blocking / patch / planning，不引入复杂 issue tracker 或平台能力。
    """
    text = _read("docs/V0_3_LOCAL_TRIAL_CHECKLIST.md")
    required = [
        "现象：",
        "命令/输入：",
        "期望：",
        "实际：",
        "是否阻塞：yes/no",
        "v0.3.2 blocking / v0.3.x patch / v0.4 planning",
    ]
    missing = [term for term in required if term not in text]
    assert not missing, f"checklist 反馈格式缺字段：{missing}"


def test_v0_3_2_trial_run_report_exists_and_separates_coverage() -> None:
    """trial report 必须区分自动覆盖和 manual-only 覆盖。

    这是 Roadmap 防漂移测试：不能为了显得 release-ready，把需要真实 LLM 或
    人眼判断的路径伪装成自动化通过。报告只记录状态，不替代人工试用。
    """
    path = REPO_ROOT / "docs" / "V0_3_2_TRIAL_RUN_REPORT.md"
    assert path.exists(), "v0.3.2 trial run report 必须存在"
    text = path.read_text(encoding="utf-8")
    lower = text.lower()

    for section in [
        "automated coverage",
        "manual-only coverage",
        "findings",
        "v0.3.2 blocking issues",
        "v0.3.x patch candidates",
        "v0.4 planning candidates",
        "release recommendation",
    ]:
        assert section in lower, f"trial report 缺 section：{section}"

    required_terms = [
        "python main.py health",
        "python main.py health --json",
        "python main.py logs --tail 5",
        "python main.py --shell",
        "request_user_input",
        "final answer",
        "checkpoint/resume",
        "manual-only",
        "现象：",
        "建议归类：v0.3.2 blocking / v0.3.x patch / v0.4 planning",
    ]
    missing = [term for term in required_terms if term.lower() not in lower]
    assert not missing, f"trial report 缺关键覆盖/反馈项：{missing}"


def test_v0_3_2_trial_report_keeps_future_work_as_planning_only() -> None:
    """v0.4 gate 只能规划，不能把未来能力写成当前已实现。

    这条测试守护 v0.3.2 release honesty：Reflect、sub-agent、slash command、
    full Textual 等词可以作为非目标出现，但必须带否定或 planning 语境。
    """
    text = _read("docs/V0_3_2_TRIAL_RUN_REPORT.md")
    lower = text.lower()
    assert "local-first learning runtime prototype" in lower
    assert "not a full textual ide" in lower
    assert "experimental / demo-level" in lower
    assert "planning candidates only, not current features" in lower

    for term in [
        "Reflect",
        "sub-agent",
        "slash command",
        "full Textual IDE",
        "LangGraph",
        "complex cancellation",
    ]:
        hits = list(re.finditer(re.escape(term), text, flags=re.IGNORECASE))
        assert hits, f"trial report 应显式登记 {term} 边界"
        assert any(
            any(
                marker in text[max(0, hit.start() - 160): hit.end() + 160].lower()
                for marker in [
                    "not",
                    "do not",
                    "should not",
                    "planning",
                    "not current features",
                ]
            )
            for hit in hits
        ), f"{term} 出现时必须带非当前能力语境"


def test_v0_3_2_trial_report_commands_match_cli_entrypoints(monkeypatch, capsys) -> None:
    """trial report 中可自动验证的命令必须仍由 main.py 接住。

    这是 checklist/report 的命令防漂移测试：不启动真实 LLM，不进入交互，只验证
    local trial report 里列出的 health/logs/shell 入口没有和 CLI 参数解析分叉。
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


def test_cli_output_contract_keeps_final_answer_request_user_input_boundary() -> None:
    """输出契约文档必须继续锁住 final answer / request_user_input 边界。

    自动测试已经覆盖 Runtime 行为；这里守护对外契约文本，避免文档后来又暗示
    Runtime 可以靠自然语言问号或关键词进入等待状态。
    """
    text = _read("docs/CLI_OUTPUT_CONTRACT.md")
    section = text.split("## 14", 1)[1]
    required = [
        "request_user_input",
        "唯一",
        "final answer",
        "不",
        "问号",
        "关键词",
        "mark_step_complete",
    ]
    missing = [term for term in required if term not in section]
    assert not missing, f"CLI output contract §14 缺协议边界关键词：{missing}"


def test_main_logs_tail_masks_raw_secret_in_cli_output(monkeypatch, tmp_path, capsys) -> None:
    """logs tail smoke 不应把历史日志里的 secret 打到 stdout。

    这是本地试用安全边界：真实 agent_log.jsonl 可能混有早期 raw content。
    v0.3.2 只允许 logs viewer 展示结构化摘要和脱敏残留，不允许 raw token /
    api_key / private key 经 `python main.py logs --tail` 泄漏。
    """
    from agent import log_viewer

    fake_log = tmp_path / "agent_log.jsonl"
    fake_log.write_text(
        "\n".join(
            [
                (
                    '{"timestamp":"t","session_id":"s","event":"user_input",'
                    '"data":{"content":"token=sk-ant-api03-secretvalue"}}'
                ),
                (
                    '{"timestamp":"t","session_id":"s","event":"unknown",'
                    '"data":{"note":"api_key=sk-ant-api03-secretvalue",'
                    '"payload":{"raw":"BEGIN PRIVATE KEY"}}}'
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(log_viewer, "LOG_FILE", str(fake_log))

    assert main_module.main(["logs", "--tail", "5"]) == 0
    out = capsys.readouterr().out
    assert "sk-ant-api03-secretvalue" not in out
    assert "BEGIN PRIVATE KEY" not in out
    assert "PRIVATE KEY" not in out
    assert "[REDACTED]" in out or "len=" in out


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
