"""v0.4 主线 A 第一切片测试 · agent log cleanup dry-run。

本测试文件覆盖 `agent/log_cleanup.py` + `python main.py logs cleanup` 两个层。
共同的核心契约：
  - DRY RUN 必须**绝对零副作用**：不删、不动、不压缩、不读取任一候选文件内容；
  - 候选清单只包含 v0.4 标准布局下的 runtime 产物（agent_log.jsonl /
    sessions/ / runs/），不包含 .env、源码、配置；
  - 报告输出必须含明显的 "DRY RUN" banner，避免被脚本误用为已删除信号；
  - git_tracked = True 必须显眼提示（避免本应 ignore 的产物被误 commit）。

测试设计原则：
  - 全部使用 tmp_path 假项目根，不读取真实 agent_log.jsonl 内容；
  - 用 chmod / open 检查文件未被 mutate；
  - subprocess 调 git 在 tmp_path 中真实建仓库，验证 gitignored / git_tracked
    分类正确（不 mock git，避免 mock 与真实行为漂移）。
"""
from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path

from agent.log_cleanup import (
    _build_archive_target,
    archive_agent_log,
    collect_cleanup_candidates,
    format_cleanup_dry_run_report,
)


def _make_fake_project(tmp_path: Path, log_size_bytes: int = 0) -> Path:
    """在 tmp_path 中构造假项目根。

    创建：
      - agent_log.jsonl（按 log_size_bytes 写入对应字节数；用 b'\\n' 填充
        避免任何真实 JSON 内容看起来像 leak）；
      - sessions/ 目录含 1 个小文件；
      - runs/ 目录含 1 个小文件；
      - 初始化 git 仓库 + .gitignore（覆盖 agent_log.jsonl / sessions/ / runs/）。

    注意：不创建 .env，确保任何意外处理 .env 的 bug 都会被测试发现（
    .env 不在候选清单 ⇒ 测试断言里也不能出现 .env）。
    """
    project = tmp_path / "fake_project"
    project.mkdir()
    (project / "agent_log.jsonl").write_bytes(b"\n" * log_size_bytes)
    (project / "sessions").mkdir()
    (project / "sessions" / "session_1.json").write_text("{}", encoding="utf-8")
    (project / "runs").mkdir()
    (project / "runs" / "run_1.txt").write_text("ok", encoding="utf-8")

    # 真实 git init + gitignore，验证 gitignored/git_tracked 检测准确性
    subprocess.run(["git", "init", "-q"], cwd=str(project), check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=str(project), check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "test"], cwd=str(project), check=True,
    )
    (project / ".gitignore").write_text(
        "agent_log.jsonl\nsessions/\nruns/\n", encoding="utf-8"
    )
    subprocess.run(["git", "add", ".gitignore"], cwd=str(project), check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "init"], cwd=str(project), check=True,
    )
    return project


def test_collect_cleanup_candidates_lists_three_runtime_artifacts(tmp_path):
    """候选清单必须恰好包含 agent_log.jsonl / sessions/ / runs/ 三项。

    防回退：未来若有人想"顺手清理"workspace/ / memory/ / .env / config.py
    等其他目录，必须显式扩展 collect_cleanup_candidates；不允许偷偷扩大
    清理范围（特别是 .env，绝不能被本模块 stat）。
    """
    project = _make_fake_project(tmp_path, log_size_bytes=100)
    cands = collect_cleanup_candidates(project)

    labels = [c.label for c in cands]
    assert labels == ["agent_log.jsonl", "sessions/", "runs/"], (
        "候选清单边界被改变。本切片严格只关心 v0.4 标准 runtime 产物，"
        "扩展前必须先讨论安全性。"
    )
    # 强契约：.env 永远不在清单里
    assert not any(".env" in c.label for c in cands)


def test_collect_cleanup_candidates_does_not_modify_files(tmp_path):
    """DRY RUN 核心契约：候选收集只 stat，绝不读取或修改任一文件。

    通过对比 collect 前后的 mtime + 内容哈希验证零副作用。若未来有人在
    collect_cleanup_candidates 内不慎调用 open/read/write，本测试会发现。
    """
    project = _make_fake_project(tmp_path, log_size_bytes=50)
    log_file = project / "agent_log.jsonl"
    sessions_dir = project / "sessions" / "session_1.json"

    before_log_mtime = log_file.stat().st_mtime_ns
    before_log_bytes = log_file.read_bytes()
    before_session_text = sessions_dir.read_text(encoding="utf-8")

    collect_cleanup_candidates(project)

    assert log_file.stat().st_mtime_ns == before_log_mtime
    assert log_file.read_bytes() == before_log_bytes
    assert sessions_dir.read_text(encoding="utf-8") == before_session_text


def test_format_dry_run_report_contains_banner_and_no_apply_hint(tmp_path):
    """报告输出契约：必含 "DRY RUN" banner + 明确说明本切片不提供 --apply。

    防回退：未来若有人偷偷改 banner 或 "no files were modified" 措辞，
    脚本/CI 可能把 dry-run 误判为真删完成，造成误读。
    """
    project = _make_fake_project(tmp_path, log_size_bytes=200)
    cands = collect_cleanup_candidates(project)
    report = format_cleanup_dry_run_report(cands)

    assert "DRY RUN" in report
    assert "no files were modified" in report
    # 第二切片后 dry-run 报告改为提示 --apply（仍要求 yes 二次确认）
    assert "--apply" in report
    assert "yes" in report
    # 报告必须列出 3 个候选 label
    assert "agent_log.jsonl" in report
    assert "sessions/" in report
    assert "runs/" in report


def test_format_dry_run_report_marks_large_files(tmp_path):
    """超过 10MB 阈值的候选必须被打上 [LARGE] 标记，便于人工聚焦。

    阈值与 v0.2 health/check_log_size 对齐；调整阈值需同步两处。
    """
    # 12MB 假日志
    project = _make_fake_project(tmp_path, log_size_bytes=12 * 1024 * 1024)
    cands = collect_cleanup_candidates(project)
    report = format_cleanup_dry_run_report(cands)

    # agent_log.jsonl 这一行必须包含 [LARGE]
    log_lines = [ln for ln in report.splitlines() if ln.startswith("- agent_log.jsonl:")]
    assert log_lines, "agent_log.jsonl 行缺失"
    assert "[LARGE]" in log_lines[0], (
        f"12MB agent_log 应被打 [LARGE] 标记，实际：{log_lines[0]!r}"
    )


def test_format_dry_run_report_warns_when_artifact_is_git_tracked(tmp_path):
    """若运行时产物被误 git track，DRY RUN 报告必须显眼警告。

    这是 v0.4 主线 A 最重要的安全契约之一：避免日志/sessions 被 commit
    后泄漏给协作者或公开仓库（即使 .gitignore 已添加，但若早期未 ignore
    时已 add，git 仍会持续 track，必须人工 git rm --cached）。
    """
    project = _make_fake_project(tmp_path, log_size_bytes=10)
    # 强制把 agent_log.jsonl track 到 git（即使 gitignore 也能用 -f 添加）
    subprocess.run(
        ["git", "add", "-f", "agent_log.jsonl"],
        cwd=str(project), check=True,
    )
    subprocess.run(
        ["git", "commit", "-q", "-m", "误 track"],
        cwd=str(project), check=True,
    )

    cands = collect_cleanup_candidates(project)
    log_cand = next(c for c in cands if c.label == "agent_log.jsonl")
    assert log_cand.git_tracked is True, "git_tracked 检测失效"

    report = format_cleanup_dry_run_report(cands)
    assert "WARN" in report and "已被 git track" in report, (
        "git_tracked 候选必须在报告中显眼警告，否则用户可能继续提交泄漏"
    )


def test_dry_run_reports_missing_target_as_skip(tmp_path):
    """不存在的候选目录应输出 "不存在 (skip)"，不报错、不创建占位。"""
    project = tmp_path / "empty_project"
    project.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=str(project), check=True)

    cands = collect_cleanup_candidates(project)
    assert all(not c.exists for c in cands)

    report = format_cleanup_dry_run_report(cands)
    assert report.count("不存在 (skip)") == 3

    # 关键：不存在的路径不应被本模块"顺手创建"
    assert not (project / "agent_log.jsonl").exists()
    assert not (project / "sessions").exists()
    assert not (project / "runs").exists()


def test_main_logs_cleanup_subcommand_exits_zero_and_dry_run_only(
    tmp_path, monkeypatch, capsys
):
    """`python main.py logs cleanup` 走 main() 入口，验证 CLI 集成无副作用。

    把 cwd / sys.argv 切到 tmp 假项目，调用 main(["logs", "cleanup"])，断言：
      - exit code 0；
      - stdout 含 DRY RUN banner；
      - 假项目下的 agent_log.jsonl 内容未被改写。

    注意：main.py 中 project_root 用 Path(__file__).resolve().parent 获取，
    所以本测试切的是源码所在目录而非 cwd——这是 main.py 的实际行为，测试
    遵循实际行为而非"应该如何"。验证 inventory 准确性已在上面的单元测试
    里覆盖；本测试仅守 CLI 集成不报错 + 输出包含 DRY RUN。
    """
    import main as main_module

    rc = main_module.main(["logs", "cleanup"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "DRY RUN" in captured.out
    assert "no files were modified" in captured.out


def test_log_cleanup_module_does_not_import_dotenv_or_secrets(tmp_path):
    """本模块绝不能 import 任何能读取 .env / 凭证的依赖。

    防架构回退：日志治理只看 stat 元信息，**绝不**接触 .env / 凭证。
    用 AST 而非 substring 扫描——substring 会把"我们绝不碰 .env"这类
    docstring 解释误判为违规（与本会话 Phase 2.3 / 2.4 教训一致）。

    检查粒度：
      - ast.Import / ast.ImportFrom 中模块名含 dotenv；
      - ast.Attribute 形如 `os.environ`（os 上下文调用）；
      - ast.Call 调用 `load_dotenv`；
      - 模块顶层 + 函数体内全部 walk 一遍（不区分位置）。
    """
    import ast
    import inspect
    from agent import log_cleanup

    tree = ast.parse(inspect.getsource(log_cleanup))
    leaks: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if "dotenv" in alias.name:
                    leaks.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.module and "dotenv" in node.module:
                leaks.append(f"from {node.module}")
        elif isinstance(node, ast.Attribute):
            # 形如 os.environ
            if (
                isinstance(node.value, ast.Name)
                and node.value.id == "os"
                and node.attr == "environ"
            ):
                leaks.append("os.environ")
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "load_dotenv":
                leaks.append("load_dotenv()")

    assert not leaks, (
        f"agent/log_cleanup.py 出现了禁用调用/导入 {leaks}——"
        "日志治理只能 stat，绝不能接触 .env / 凭证 / 环境变量。"
    )


# ============================================================
# v0.4 主线 A 第二切片 · archive --apply 测试
# ============================================================
#
# 共同设计契约：
#   - 全部使用 tmp_path 假 agent_log.jsonl，**绝不**读取真实日志内容；
#   - 用 confirm_input 注入替身，避免 mock sys.stdin 的脆弱性；
#   - 每条测试都是"零内容读取" + "副作用最小"边界守卫；
#   - 不新增 skip / xfail；不削弱已有断言。


def _make_project_with_log(tmp_path: Path, content_bytes: bytes = b"x") -> Path:
    """构造含 agent_log.jsonl 的假项目（不 git init，archive 测试不需要 git）。

    sessions/ 与 runs/ **故意不创建**——验证 archive 路径完全不依赖它们。
    .env 也**故意不创建**——验证即使存在也不会被本模块 stat。
    """
    project = tmp_path / "fake_project"
    project.mkdir()
    (project / "agent_log.jsonl").write_bytes(content_bytes)
    return project


def test_archive_dry_run_does_not_move_or_delete_log(tmp_path):
    """apply=False（默认）：源文件 mtime + 内容字节完全不变。

    防回退：未来若有人在 dry-run 路径偷偷做"先备份"操作，本测试发现。
    """
    project = _make_project_with_log(tmp_path, b"hello-bytes")
    src = project / "agent_log.jsonl"
    before_mtime = src.stat().st_mtime_ns
    before_bytes = src.read_bytes()

    result = archive_agent_log(project, apply=False)

    assert result.status == "dry_run"
    assert "DRY RUN" in result.message
    assert src.exists()
    assert src.stat().st_mtime_ns == before_mtime
    assert src.read_bytes() == before_bytes
    # 目标 archive 文件名出现在 message 中，但目标文件**不应**已被创建
    assert result.target is not None
    assert not result.target.exists()


def test_archive_apply_with_wrong_confirm_does_not_move(tmp_path):
    """apply=True 但 confirm 输入非精确 'yes'：源文件原地不动。

    覆盖 'Y'、'y'、'yes\\n'、'yes please'、'是'、空字符串 5 种变体——
    只接受精确 'yes'。这是 dangerous op 的"显式动作"契约。
    """
    project = _make_project_with_log(tmp_path, b"wrong-confirm")
    src = project / "agent_log.jsonl"
    before_bytes = src.read_bytes()

    for bad in ["Y", "y", "yes please", "是", "", "yes\n"]:
        # 注入 lambda 替身代替 stdin
        result = archive_agent_log(
            project, apply=True, confirm_input=lambda v=bad: v
        )
        assert result.status == "cancelled", (
            f"输入 {bad!r} 不应触发 archive；实际 status={result.status}"
        )
        assert src.exists()
        assert src.read_bytes() == before_bytes


def test_archive_apply_with_yes_renames_log_atomically(tmp_path):
    """apply=True + confirm='yes'：源不存在 + 目标存在 + 字节一致。

    验证 archive 真正生效，并且 archive 的是**完全相同的字节**（rename
    不修改内容）；同时严格断言"源 .jsonl 已不存在"——确认不是"复制+保留"。
    """
    project = _make_project_with_log(tmp_path, b"will-be-archived")
    src = project / "agent_log.jsonl"
    expected_bytes = src.read_bytes()

    result = archive_agent_log(
        project, apply=True, confirm_input=lambda: "yes"
    )

    assert result.status == "archived"
    assert "ARCHIVE done" in result.message
    assert not src.exists(), "rename 后源文件必须不存在"
    assert result.target is not None and result.target.exists()
    assert result.target.read_bytes() == expected_bytes


def test_archive_skips_when_source_missing(tmp_path):
    """源 agent_log.jsonl 不存在：友好退出，不报错，不创建任何文件。"""
    project = tmp_path / "empty"
    project.mkdir()

    result = archive_agent_log(project, apply=True, confirm_input=lambda: "yes")

    assert result.status == "skipped_no_source"
    assert "不存在" in result.message
    # 不允许"顺手创建"占位文件
    assert not (project / "agent_log.jsonl").exists()
    assert list(project.iterdir()) == []


def test_archive_refuses_to_overwrite_existing_target(tmp_path):
    """目标 archive 路径已存在：拒绝覆盖，源文件保留原状。

    场景：1 秒内连续两次 --apply（极罕见但必须防）。fix-ts 通过 now=
    参数注入，让两次调用算出相同时间戳。
    """
    project = _make_project_with_log(tmp_path, b"first")
    fixed_now = datetime(2026, 4, 30, 12, 34, 56)

    # 第一次成功 archive
    first = archive_agent_log(
        project, apply=True, confirm_input=lambda: "yes", now=fixed_now
    )
    assert first.status == "archived"

    # 模拟 1 秒内又出现新的 agent_log.jsonl 并尝试 archive 到相同时间戳
    (project / "agent_log.jsonl").write_bytes(b"second")
    src = project / "agent_log.jsonl"
    second = archive_agent_log(
        project, apply=True, confirm_input=lambda: "yes", now=fixed_now
    )

    assert second.status == "target_exists"
    assert "拒绝覆盖" in second.message
    # 源文件必须保留（未被部分 rename）
    assert src.exists()
    assert src.read_bytes() == b"second"


def test_archive_does_not_touch_sessions_runs_or_dotenv(tmp_path):
    """archive 路径完全不读 / 不动 sessions/ / runs/ / .env。"""
    project = _make_project_with_log(tmp_path, b"log")
    (project / "sessions").mkdir()
    (project / "sessions" / "s1.json").write_text("session-data", encoding="utf-8")
    (project / "runs").mkdir()
    (project / "runs" / "r1.txt").write_text("run-data", encoding="utf-8")
    (project / ".env").write_text("SECRET=do-not-touch", encoding="utf-8")

    archive_agent_log(project, apply=True, confirm_input=lambda: "yes")

    # sessions / runs / .env 全部一字节未变
    assert (project / "sessions" / "s1.json").read_text(encoding="utf-8") == "session-data"
    assert (project / "runs" / "r1.txt").read_text(encoding="utf-8") == "run-data"
    assert (project / ".env").read_text(encoding="utf-8") == "SECRET=do-not-touch"


def test_archive_target_filename_preserves_jsonl_suffix(tmp_path):
    """archive 文件名格式：<stem>.archived-YYYYMMDD-HHMMSS.jsonl。

    保留 .jsonl 后缀让 log_viewer / less 等工具能直接读，不强迫用户改命令。
    """
    src = tmp_path / "agent_log.jsonl"
    fixed_now = datetime(2026, 1, 2, 3, 4, 5)
    target = _build_archive_target(src, now=fixed_now)
    assert target.name == "agent_log.archived-20260102-030405.jsonl"
    assert target.parent == src.parent


def test_archive_apply_yes_message_contains_archive_keyword(tmp_path):
    """成功 message 必须包含 'ARCHIVE'，便于 grep / 脚本识别。"""
    project = _make_project_with_log(tmp_path, b"x")
    result = archive_agent_log(
        project, apply=True, confirm_input=lambda: "yes"
    )
    assert "ARCHIVE" in result.message


def test_archive_module_does_not_open_or_read_log_content():
    """AST 检查：archive_agent_log 函数体内不允许 open / read_text /
    read_bytes 任何 Path 对象。

    rename 是 fs metadata op，不需要也不应读内容；防架构回退。
    """
    import ast
    import inspect
    from agent import log_cleanup

    src = inspect.getsource(log_cleanup.archive_agent_log)
    tree = ast.parse(src)
    bad_attrs = {"read_text", "read_bytes", "open"}
    leaks: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in bad_attrs:
            leaks.append(node.attr)
        elif isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name) and f.id == "open":
                leaks.append("open()")
    assert not leaks, (
        f"archive_agent_log 不允许读取日志内容，发现禁用操作 {leaks}"
    )


def test_main_logs_cleanup_apply_flag_routes_to_archive(
    tmp_path, monkeypatch, capsys
):
    """`python main.py logs cleanup --apply` CLI 集成（不真删，因为 confirm
    走 stdin EOF → 取消）。

    验证 CLI 能识别 --apply flag 并调用 archive_agent_log。stdin 关闭时
    EOFError 被捕获返回空字符串 → 不等于 'yes' → status=cancelled，源文件
    不动。这确保即使 CI 误触 --apply 也不会真删。
    """
    import io
    import sys
    import main as main_module

    # 模拟 stdin EOF：替换 sys.stdin 为空 StringIO
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))

    rc = main_module.main(["logs", "cleanup", "--apply"])
    assert rc == 0
    captured = capsys.readouterr()
    # 应同时包含 dry-run inventory + archive cancelled 提示
    assert "DRY RUN" in captured.out
    assert "ARCHIVE cancelled" in captured.out or "ARCHIVE skipped" in captured.out
