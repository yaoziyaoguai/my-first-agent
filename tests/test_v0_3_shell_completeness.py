"""v0.3 完成态守护：CLI shell 子命令、文案、文档引用一致性回归。

本测试不验证 Runtime 行为本身（那由 600+ 既有测试覆盖），只守护
docs/CLI_OUTPUT_CONTRACT.md §13、docs/V0_3_BASIC_SHELL_USAGE.md、
README.md 里**承诺给用户的命令与文案**没有被悄悄回退。
"""
from __future__ import annotations

from pathlib import Path

import main as main_module
from agent import cli_renderer
from agent.health_check import collect_health_results
from agent.health_report import format_health_report, format_health_report_json

PROJECT_ROOT = Path(__file__).resolve().parents[1]


# ---------- 13.1 子命令清单：每个 doc-referenced 命令都必须 wire ----------

def test_health_subcommand_wired(monkeypatch, capsys):
    monkeypatch.setattr(
        "agent.health_check.collect_health_results",
        lambda: {"workspace_lint": {"status": "pass", "current_value": "0",
                                     "path": "workspace", "risk": "无",
                                     "action": "无需操作", "message": "ok"}},
    )
    assert main_module.main(["health"]) == 0
    assert "项目健康检查报告" in capsys.readouterr().out


def test_health_json_subcommand_wired(capsys):
    assert main_module.main(["health", "--json"]) == 0
    out = capsys.readouterr().out
    import json
    parsed = json.loads(out)
    assert "overall" in parsed and "checks" in parsed


def test_logs_subcommand_wired(capsys):
    assert main_module.main(["logs", "--tail", "1"]) == 0
    assert "Runtime logs" in capsys.readouterr().out


def test_logs_subcommand_filters_wired(capsys):
    # 各过滤参数应被解析（不一定有匹配）；不应崩溃
    for argv in (
        ["logs", "--tail", "1", "--session", "deadbeef"],
        ["logs", "--tail", "1", "--event", "tool_executed"],
        ["logs", "--tail", "1", "--tool", "calculate"],
        ["logs", "--tail", "1", "--include-observer"],
    ):
        capsys.readouterr()  # clear
        assert main_module.main(argv) == 0
        out = capsys.readouterr().out
        assert "Runtime logs" in out


def test_shell_flag_enters_normal_cli_shell(monkeypatch):
    calls = []

    monkeypatch.setattr(main_module, "init_session", lambda: calls.append("init"))
    monkeypatch.setattr(main_module, "try_resume_from_checkpoint", lambda: calls.append("resume"))
    monkeypatch.setattr(main_module, "main_loop", lambda: calls.append("loop"))
    monkeypatch.setattr(main_module, "_selected_input_backend", lambda: "simple")

    assert main_module.main(["--shell"]) == 0
    assert calls == ["init", "resume", "loop"]


# ---------- 13.2 启动屏 Skill 文案（M3 锁） ----------

def test_startup_header_marks_skill_experimental_and_drops_dead_command():
    out = cli_renderer.render_session_header(session_id="abc12345-x", cwd=".")
    assert "/reload_skills" not in out
    assert "实验性" in out
    assert "V0_3_SKILL_SYSTEM_STATUS" in out
    assert "python main.py health" in out
    assert "python main.py logs" in out


# ---------- 13.4 health/logs 联动 ----------

def test_health_log_size_action_links_to_logs_viewer(tmp_path, monkeypatch):
    from agent import health_check

    monkeypatch.setattr(health_check, "PROJECT_DIR", tmp_path)
    (tmp_path / "agent_log.jsonl").write_text("x" * (11 * 1024 * 1024))
    result = health_check.check_log_size()
    assert "python main.py logs" in result["action"]
    # 不得反向写自动 rm / 自动归档
    assert "rm -rf" not in result["action"]
    assert "rm " not in result["action"]


# ---------- 文档与代码一致性 ----------

def test_basic_shell_usage_doc_exists_and_lists_all_subcommands():
    doc = PROJECT_ROOT / "docs" / "V0_3_BASIC_SHELL_USAGE.md"
    assert doc.exists()
    text = doc.read_text(encoding="utf-8")
    # 文档承诺的每个命令都应该在 doc 里出现
    for cmd in (
        "python main.py",
        "python main.py --shell",
        "python main.py health",
        "python main.py health --json",
        "python main.py logs",
        "python main.py logs --tail",
        "python main.py logs --session",
        "python main.py logs --event",
        "python main.py logs --tool",
        "python main.py logs --include-observer",
    ):
        assert cmd in text, f"V0_3_BASIC_SHELL_USAGE.md 缺命令：{cmd}"


def test_v0_3_health_maintenance_doc_exists_and_matches_entrypoints():
    doc = PROJECT_ROOT / "docs" / "V0_3_HEALTH_MAINTENANCE.md"
    assert doc.exists()
    text = doc.read_text(encoding="utf-8")
    assert "python main.py health" in text
    assert "python main.py health --json" in text
    assert "python main.py logs --tail 100" in text
    assert "不会自动" in text


def test_cli_output_contract_section_13_present():
    text = (PROJECT_ROOT / "docs" / "CLI_OUTPUT_CONTRACT.md").read_text(encoding="utf-8")
    assert "## 13" in text
    assert "python main.py logs" in text
    assert "python main.py health" in text
    # §12.1 不能再宣称启动屏含 /reload_skills（M3 已删）
    sec_12 = text.split("## 12")[1].split("## 13")[0]
    assert "/reload_skills" not in sec_12 or "不再" in sec_12 or "无 handler" in sec_12


def test_readme_documents_all_v0_3_subcommands():
    text = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    for cmd in (
        "python main.py --shell",
        "python main.py health",
        "python main.py logs",
    ):
        assert cmd in text, f"README 缺命令：{cmd}"


# ---------- 烟雾：health 渲染器与 logs viewer 不互崩 ----------

def test_health_report_renders_without_error():
    results = collect_health_results()
    pretty = format_health_report(results)
    json_out = format_health_report_json(results)
    assert "项目健康检查报告" in pretty
    assert "overall" in json_out
    # 结果 dict 与渲染产物均不应裸暴露绝对家目录路径
    # （PROJECT_DIR 是仓库根，应该被 _relative_path 转成相对）
    for v in results.values():
        if isinstance(v, dict) and "path" in v:
            assert not v["path"].startswith("/Users/"), v


# ---------- M1-M4 不做的清单仍在文档中显式登记 ----------

def test_planning_doc_keeps_non_goals_visible():
    text = (PROJECT_ROOT / "docs" / "V0_3_PLANNING.md").read_text(encoding="utf-8")
    # v0.3 显式不做的能力清单必须保留，不能被「完成态」误读为已实现
    for forbidden in (
        "Reflect",
        "sub-agent",
        "generation cancel",
        "topic switch",
        "slash command",
    ):
        assert forbidden in text, f"PLANNING 丢失非目标声明：{forbidden}"


# ---------- 13.5 checkpoint/resume 不裸 dict ----------

def test_resume_status_never_dumps_raw_messages_or_keys():
    # 即便 summary 里被错塞 messages / api_key，渲染层也不能把它们打到屏幕上。
    # render_resume_status 是纯白名单消费 summary 字段（user_goal/status/...），
    # 不会反射式 dump。这里用一个污染 dict 验证：
    poisoned = {
        "actionable": True,
        "user_goal": "正常任务",
        "status": "running",
        "current_step_index": 1,
        "message_count": 3,
        "messages": [{"role": "user", "content": "raw secret"}],
        "api_key": "sk-ant-xxxxxxxxxxxxxxxxxxxxxx",
    }
    out = cli_renderer.render_resume_status(poisoned)
    assert "raw secret" not in out
    assert "sk-ant" not in out
    assert "messages" not in out
    assert "api_key" not in out
    assert "正常任务" in out


# ---------- protocol dump 不应出现在用户面向输出里 ----------

def test_logs_output_has_no_protocol_dump_markers(capsys):
    main_module.main(["logs", "--tail", "20"])
    out = capsys.readouterr().out
    # v0.1 § 输出契约禁止 prefix：REQUEST / RESPONSE / [DEBUG] 全文 dump
    assert "REQUEST:" not in out
    assert "RESPONSE:" not in out
    assert "[DEBUG]" not in out
    # 历史 jsonl 里有 system_prompt 全文 / messages 数组的话，logs viewer
    # 必须按白名单只留 *_len，不得出现明显的会话内容 marker
    assert "\"messages\":" not in out
    assert "\"system_prompt\":" not in out


# ---------- tool confirmation 参数预览不泄露 secret ----------

def test_log_viewer_masks_secrets_in_tool_input_preview():
    from agent.log_viewer import format_entry, mask_secrets

    fake_entry = {
        "timestamp": "2025-01-01T00:00:00",
        "session_id": "abcd1234",
        "event_type": "tool_confirmation_requested",
        "data": {
            "tool_name": "write_file",
            "tool_input": {
                "path": "creds.txt",
                "content": "api_key=sk-ant-secretvalueXXXXXXXXXX",
            },
        },
    }
    line = format_entry(fake_entry)
    # 渲染层白名单 + 兜底 mask_secrets 至少有一道命中
    assert "sk-ant-secretvalueXXXXXXXXXX" not in line
    assert "api_key=sk-ant-secretvalueXXXXXXXXXX" not in line
    # 兜底正则可独立验证
    assert "sk-ant-" not in mask_secrets("prefix sk-ant-zzzzzzzzzzzzzzzzzzzzzz suffix")


def test_tool_confirmation_preview_masks_secret_values():
    from agent.display_events import build_tool_awaiting_confirmation_event

    event = build_tool_awaiting_confirmation_event(
        tool_name="write_file",
        tool_input={
            "path": "workspace/creds.txt",
            "content": (
                "api_key=sk-ant-secretvalueXXXXXXXXXX\n"
                "-----BEGIN PRIVATE KEY-----\n"
            ),
        },
    )
    assert "sk-ant-secretvalueXXXXXXXXXX" not in event.body
    assert "api_key=sk-ant-secretvalueXXXXXXXXXX" not in event.body
    assert "BEGIN PRIVATE KEY" not in event.body
    assert "[REDACTED]" in event.body


# ---------- logs viewer 端到端 round-trip ----------
# 为什么是端到端而不是单元：runtime_observer 单测和 log_viewer 单测都在
# 自己 mock 边界上各自绿，但**真实 jsonl 写入 → viewer 读取**这条串行链路
# 之前没有回归。如果 observer schema 变（比如 event_type 改名）或 viewer
# 白名单字段漂移，单测可能各自仍绿，端到端却悄悄 leak / 漏渲染 / 类别错位。
# 本测试用真实 log_event 写四类 tool outcome，再让 log_viewer 把它读回，
# 守护这条「事件链路可还原」的小闭环。

def test_log_viewer_can_recover_four_tool_outcomes_from_real_jsonl(tmp_path, monkeypatch):
    import importlib

    log_path = tmp_path / "agent_log.jsonl"
    monkeypatch.setattr("config.LOG_FILE", str(log_path))

    import agent.logger as logger_mod
    importlib.reload(logger_mod)
    from agent.logger import log_event

    # log_event 当前签名是 (event_type, data)；session_id 由模块级 SESSION_ID 注入。
    # 写入的 jsonl 字段名是 "event"（不是 "event_type"），log_viewer 读的也是这个。
    log_event("tool.completed",
              {"tool_name": "calculate", "status_text": "执行完成。"})
    log_event("tool.failed",
              {"tool_name": "read_file", "status_text": "执行失败。"})
    log_event("tool.rejected",
              {"tool_name": "read_file", "status_text": "被安全策略拒绝：…"})
    log_event("tool.user_rejected",
              {"tool_name": "write_file", "status_text": "用户拒绝执行，已跳过。"})

    from agent.log_viewer import iter_log_entries, render_logs

    entries = list(iter_log_entries(log_path, include_observer=False))
    assert len(entries) == 4
    types = [e.get("event") for e in entries]
    assert types == [
        "tool.completed",
        "tool.failed",
        "tool.rejected",
        "tool.user_rejected",
    ], types

    rendered = render_logs(log_path=log_path, tail=10)
    # 四类 outcome 必须都能在最终单行摘要里被分辨出来
    assert "tool.completed" in rendered
    assert "tool.failed" in rendered
    assert "tool.rejected" in rendered
    assert "tool.user_rejected" in rendered
    # 不得 leak 任何 raw status_text 之外的内部字段名
    assert "messages" not in rendered
    assert "system_prompt" not in rendered


# ---------- v0.3 显式不做 Reflect / Self-Correction 的三文档一致性 ----------
# 这条非目标在 README / V0_3_PLANNING / V0_3_BASIC_SHELL_USAGE 三处都登记过，
# 但没有回归守护。如果未来某一轮误把 Reflect 写进 v0.3 完成态，这个测试会拦下。

def test_reflect_self_correction_marked_out_of_scope_in_all_user_docs():
    docs_to_check = [
        PROJECT_ROOT / "README.md",
        PROJECT_ROOT / "docs" / "V0_3_PLANNING.md",
        PROJECT_ROOT / "docs" / "V0_3_BASIC_SHELL_USAGE.md",
    ]
    for path in docs_to_check:
        text = path.read_text(encoding="utf-8")
        assert "Reflect" in text, f"{path.name} 未提到 Reflect 边界"
        # 至少一个 Reflect 出现位置附近 200 字内必须含「非目标」标记
        markers = ["❌", "不做", "non-goal", "not** include", "does not", "留给", "v0.4", "Roadmap"]
        ok = False
        start = 0
        while True:
            i = text.find("Reflect", start)
            if i == -1:
                break
            nearby = text[max(0, i - 250): i + 250]
            if any(m in nearby for m in markers):
                ok = True
                break
            start = i + 1
        assert ok, (
            f"{path.name} 提到 Reflect 但所有出现位置附近 250 字内都没有「非目标」标记，"
            f"可能被误读为已实现"
        )
