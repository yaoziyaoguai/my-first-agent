"""v0.5 Phase 1 第三小步 · 本地 artifact 只读 inventory 测试。

测试纪律说明：
    - 全部用 ``tmp_path`` 构造 fake sessions/runs 目录，**不**触碰真实
      项目下的 sessions/ 或 runs/；
    - AST guard 测试通过解析 ``agent/local_artifacts.py`` 模块源码，
      确保模块内**绝不**调用任何"可能 mutate fs"或"可能读取文件正文"
      的 API（unlink/remove/rmtree/rename/replace/move/write_text/
      write_bytes/open）；
    - 测试**不**为通过率而存在，每条都对应一个具体的真实 bug 风险：
        * count/total_bytes 错算 -> 误导 cleanup 决策；
        * mtime 极值算错 -> 误导"哪些是旧的"判断；
        * 模块偷偷 open() -> 可能读到未脱敏正文 / 触发 fd 泄漏；
        * 模块偷偷 unlink/rename -> dry-run 承诺被破坏。
    - 不削弱已有断言、不新增 skip / xfail。
"""

from __future__ import annotations

import ast
import inspect
import os
from pathlib import Path

import pytest

from agent import local_artifacts
from agent.local_artifacts import (
    ArtifactInventory,
    format_artifact_inventory_report,
    inventory_artifact_directory,
    inventory_known_artifact,
)


# ============================================================
# 基础功能：count / total_bytes / mtime range 正确
# ============================================================


def _write_file(p: Path, size: int, mtime: float | None = None) -> None:
    """测试辅助：tmp_path 下创建指定大小的文件并设 mtime。

    本 helper 只在测试代码内调用——production 模块严禁写文件。
    """
    p.write_bytes(b"x" * size)
    if mtime is not None:
        os.utime(p, (mtime, mtime))


def test_inventory_returns_immutable_dataclass(tmp_path: Path) -> None:
    """inventory 返回值是 frozen dataclass（不可变快照）。

    防止 caller 在传递过程中改写字段——inventory 的核心承诺是
    "你拿到的就是某一时刻磁盘的真实状态"，可变会让这个承诺破裂。
    """
    inv = inventory_artifact_directory(tmp_path, kind="sessions")
    assert isinstance(inv, ArtifactInventory)
    with pytest.raises(Exception):
        # frozen dataclass 应抛 FrozenInstanceError；用 Exception 兜底
        # 避免 dataclass 内部异常类型变化导致测试脆弱
        inv.file_count = 999  # type: ignore[misc]


def test_inventory_handles_missing_directory(tmp_path: Path) -> None:
    """目录不存在时 inventory 不报错，返回 exists=False 且其余字段为 0/空。

    真实场景：新装项目可能没有 sessions/，CLI 仍要给用户友好输出。
    """
    missing = tmp_path / "nope"
    inv = inventory_artifact_directory(missing, kind="sessions")
    assert inv.exists is False
    assert inv.file_count == 0
    assert inv.total_bytes == 0
    assert inv.oldest_mtime is None
    assert inv.newest_mtime is None
    assert inv.by_extension == {}
    assert inv.by_prefix == {}
    assert inv.sample_paths == []


def test_inventory_counts_files_and_bytes_correctly(tmp_path: Path) -> None:
    """count / total_bytes 必须精确匹配真实文件元信息。

    抓 bug：如果统计漏算或重复算，cleanup 决策会基于错误数字 -> 用户
    可能误以为没占空间而留垃圾，或误以为占了大量空间而误删。
    """
    sess = tmp_path / "sessions"
    sess.mkdir()
    _write_file(sess / "session_a.json", 100)
    _write_file(sess / "session_b.json", 250)
    _write_file(sess / "session_c.json", 50)

    inv = inventory_artifact_directory(sess, kind="sessions")
    assert inv.exists is True
    assert inv.file_count == 3
    assert inv.total_bytes == 400


def test_inventory_mtime_range_is_oldest_and_newest(tmp_path: Path) -> None:
    """oldest_mtime / newest_mtime 必须分别是最旧和最新的文件 mtime。

    抓 bug：如果实现搞反（用 max 当 oldest），用户会看到颠倒的"最旧"
    报告 -> 删错文件。
    """
    sess = tmp_path / "sessions"
    sess.mkdir()
    _write_file(sess / "old.json", 1, mtime=1_700_000_000)
    _write_file(sess / "new.json", 1, mtime=1_800_000_000)
    _write_file(sess / "mid.json", 1, mtime=1_750_000_000)

    inv = inventory_artifact_directory(sess, kind="sessions")
    assert inv.oldest_mtime is not None
    assert inv.newest_mtime is not None
    # ISO 字符串字典序与时间序一致
    assert inv.oldest_mtime < inv.newest_mtime
    # 1_700_000_000 -> 2023-11-14T22:13:20Z；不强绑定具体值，只断言
    # oldest_mtime 对应 1_700_000_000 而不是 1_800_000_000
    assert inv.oldest_mtime.startswith("2023-")
    assert inv.newest_mtime.startswith("2027-")


def test_inventory_groups_by_extension_and_prefix(tmp_path: Path) -> None:
    """by_extension / by_prefix 桶分组语义正确。

    by_extension 让用户一眼看到产物类型分布（.json vs .jsonl vs 其他）。
    by_prefix 让用户看出 ``session_*`` 还是 hash 文件名占多数。
    """
    runs = tmp_path / "runs"
    runs.mkdir()
    _write_file(runs / "abcdef0123456789.jsonl", 10)  # hash prefix
    _write_file(runs / "fedcba9876543210.jsonl", 20)  # hash prefix
    _write_file(runs / "session_x.json", 5)
    _write_file(runs / "session_y.json", 5)
    _write_file(runs / "report.txt", 3)

    inv = inventory_artifact_directory(runs, kind="runs")
    assert inv.by_extension == {".json": 2, ".jsonl": 2, ".txt": 1}
    # session_* 两个；hash prefix 两个；report 一个
    assert inv.by_prefix.get("session") == 2
    assert inv.by_prefix.get("hash") == 2
    assert inv.by_prefix.get("report") == 1


def test_inventory_sample_paths_capped(tmp_path: Path) -> None:
    """sample_paths 数量受 sample_limit 限制（默认 5）。

    防止 inventory 报告无限膨胀（目录里有几千个文件时）。
    """
    sess = tmp_path / "sessions"
    sess.mkdir()
    for i in range(10):
        _write_file(sess / f"s_{i}.json", 1)
    inv = inventory_artifact_directory(sess, kind="sessions")
    assert len(inv.sample_paths) == 5


def test_inventory_subdirectories_not_counted_as_files(tmp_path: Path) -> None:
    """顶层若有子目录，仅计入 by_prefix=(dir)，不计 file_count/total_bytes。

    防止把 sessions/<id>/ 这种"子目录式 checkpoint 容器"误算成 1 个
    巨大文件。
    """
    sess = tmp_path / "sessions"
    sess.mkdir()
    (sess / "subdir").mkdir()
    _write_file(sess / "x.json", 100)
    inv = inventory_artifact_directory(sess, kind="sessions")
    assert inv.file_count == 1  # 不含 subdir
    assert inv.total_bytes == 100
    assert inv.by_prefix.get("(dir)") == 1


def test_inventory_known_artifact_rejects_unknown_kind(tmp_path: Path) -> None:
    """``inventory_known_artifact`` 只接 sessions / runs，其余 kind 直接拒绝。

    防止用户误用 inventory_known_artifact("logs", ...) 触发 stat 在
    agent_log.jsonl 上——logs 治理走 log_cleanup 路径，不走本模块。
    """
    with pytest.raises(ValueError, match="unknown artifact kind"):
        inventory_known_artifact(tmp_path, kind="logs")


# ============================================================
# 报告渲染：DRY RUN banner + 字段顺序
# ============================================================


def test_format_report_starts_with_dry_run_banner(tmp_path: Path) -> None:
    """报告**第一行**必须是 DRY RUN banner——让用户不可能误以为做了修改。"""
    inv = inventory_artifact_directory(tmp_path, kind="sessions")
    report = format_artifact_inventory_report(inv)
    first_line = report.splitlines()[0]
    assert "DRY RUN" in first_line


def test_format_report_ends_with_no_changes_made(tmp_path: Path) -> None:
    """报告结尾必须明确写 ``no changes made``。

    防止有人未来加 --apply 时漏改这条收尾，让用户继续以为是 dry-run。
    """
    inv = inventory_artifact_directory(tmp_path, kind="runs")
    report = format_artifact_inventory_report(inv)
    assert "no changes made" in report


def test_format_report_for_missing_directory_says_directory_missing(tmp_path: Path) -> None:
    """目录不存在时报告必须显式说明，而不是装作有 0 个文件。"""
    inv = inventory_artifact_directory(tmp_path / "nope", kind="sessions")
    report = format_artifact_inventory_report(inv)
    assert "directory missing" in report


# ============================================================
# AST guard：模块**绝对**禁止 mutating call / 文件 open
# ============================================================


# 禁止的"可 mutate fs"调用——即使是间接通过 os/Path/shutil 拿到的
# 方法名，也由 AST attribute 名扫描兜住。
_FORBIDDEN_MUTATING_NAMES: frozenset[str] = frozenset({
    "unlink", "remove", "rmtree", "rename", "replace", "move",
    "write_text", "write_bytes", "mkdir", "rmdir", "touch",
    "chmod", "chown", "symlink_to", "hardlink_to",
})

# 禁止的"打开文件读内容"调用——本模块只做 metadata，绝不读正文。
_FORBIDDEN_OPEN_NAMES: frozenset[str] = frozenset({
    "open", "read_text", "read_bytes",
})


def _walk_local_artifacts_ast() -> ast.Module:
    """把 agent/local_artifacts.py 解析为 AST 供守卫测试用。"""
    src = inspect.getsource(local_artifacts)
    return ast.parse(src)


def test_local_artifacts_module_does_not_call_mutating_apis() -> None:
    """模块源码 AST 中**不存在**任何 mutating 调用。

    抓 bug：dry-run 模块若偷偷 unlink/rename 会破坏"零副作用"承诺。
    本测试用 AST 而非字符串扫描，避免 docstring 中的中文说明误伤。
    """
    tree = _walk_local_artifacts_ast()
    bad: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name: str | None = None
            if isinstance(func, ast.Attribute):
                name = func.attr
            elif isinstance(func, ast.Name):
                name = func.id
            if name in _FORBIDDEN_MUTATING_NAMES:
                bad.append(name)
    assert not bad, (
        f"agent/local_artifacts.py 内出现禁止的 mutating call：{bad}；"
        "inventory 必须严格只读"
    )


def test_local_artifacts_module_does_not_open_or_read_file_contents() -> None:
    """模块源码 AST 中**不存在**任何文件 open/read 调用。

    抓 bug：本模块只能 stat 元信息，绝不能读 sessions/runs 文件正文
    （可能含未脱敏对话片段）。
    """
    tree = _walk_local_artifacts_ast()
    bad: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name: str | None = None
            if isinstance(func, ast.Attribute):
                name = func.attr
            elif isinstance(func, ast.Name):
                name = func.id
            if name in _FORBIDDEN_OPEN_NAMES:
                bad.append(name)
    assert not bad, (
        f"agent/local_artifacts.py 内出现禁止的 open/read 调用：{bad}；"
        "inventory 必须只读 metadata，不读正文"
    )


def test_local_artifacts_module_does_not_import_dotenv_or_secrets() -> None:
    """模块**不**应 import dotenv / secrets 类敏感配置加载库。

    inventory 与 .env / 凭据无关；任何此类 import 都属"职责越界"。
    用 AST 走 Import / ImportFrom 节点，避免字符串扫描误伤 docstring。
    """
    tree = _walk_local_artifacts_ast()
    forbidden_modules = {"dotenv", "python_dotenv", "agent.config"}
    bad: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in forbidden_modules:
                    bad.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module in forbidden_modules:
                bad.append(node.module)
    assert not bad, (
        f"agent/local_artifacts.py 不应 import 敏感配置/凭据模块：{bad}"
    )


# ============================================================
# 真实场景：用 tmp_path 跑一遍后，目录原样无变化
# ============================================================


def test_inventory_does_not_modify_target_directory(tmp_path: Path) -> None:
    """跑完 inventory 后目标目录的所有 stat 与文件都未变化。

    端到端"零副作用"证据——AST 守卫管"代码长什么样"，本测试管"实际
    跑完磁盘状态没变"，互为冗余。
    """
    sess = tmp_path / "sessions"
    sess.mkdir()
    files = {
        sess / "a.json": 100,
        sess / "b.json": 200,
    }
    for p, sz in files.items():
        _write_file(p, sz, mtime=1_700_000_000)

    before = {
        p: (p.stat().st_size, p.stat().st_mtime, p.read_bytes())
        for p in files
    }

    _ = inventory_artifact_directory(sess, kind="sessions")
    _ = format_artifact_inventory_report(
        inventory_artifact_directory(sess, kind="sessions")
    )

    after = {
        p: (p.stat().st_size, p.stat().st_mtime, p.read_bytes())
        for p in files
    }
    assert before == after
    # 目录本身也没多/少文件
    assert sorted(p.name for p in sess.iterdir()) == ["a.json", "b.json"]
