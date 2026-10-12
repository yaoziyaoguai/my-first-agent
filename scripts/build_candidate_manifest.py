#!/usr/bin/env python3
"""S4：按审核清单把工作树物化成干净候选目录，并产出逐文件哈希 manifest。

用法：
    python scripts/build_candidate_manifest.py --out <候选目录> --manifest <json 路径>

规则（资料包 DL-01 §2/§3）：
- 候选是**工作树产品状态的干净副本**（HEAD 产品代码与工作树测试不自洽：
  例如 HEAD 的 ``ControlInbox`` 没有工作树 loop.py 调用的 ``pending``），
  因此产品/测试文件一律取工作树内容；
- 只复制审核清单内的路径，不整树复制；显式排除构建残留、私人目录与
  ``.git``/``.venv``/``graphify-out``/根 ``tui/``/``.ua``；
- 每个文件记录 sha256、纳入理由、HEAD 是否已有差异（既有用户工作）与
  本轮是否修改（本轮 = 2026-10-11 收口修复）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[1]

# 必须取工作树内容的产品文件：launch/运行时闭包（16 文件，含 file_ops 的
# project_paths 运行时缺口）+ 被产品代码引用的未跟踪模块。
WORKTREE_CLOSURE: dict[str, str] = {
    # --- 审计 S0 的 12 文件 import 闭包 ---
    "agent/browser/contracts.py": "launch closure: browser contracts symbols",
    "agent/cli/actions.py": "launch closure: typed action builders",
    "agent/composition.py": "launch closure: composition root symbols",
    "agent/continuity/sessions.py": "launch closure: session bootstrap",
    "agent/memory/contracts.py": "launch closure: memory contract symbols",
    "agent/provider/config.py": "launch closure: provider config",
    "agent/provider/protocol.py": "launch closure: provider protocol",
    "agent/runtime/ports.py": "launch closure: ModelAttemptBudgetExhaustedError",
    "agent/runtime/views.py": "launch closure: view projections",
    "agent/tools/path_safety.py": "launch closure: path safety helpers",
    # --- 未被 import 探测发现、但运行时调用缺口的第 16 个文件 ---
    "agent/tools/file_ops.py": (
        "runtime closure: composition.build_tool_registrations passes "
        "project_paths= to build_file_tool_registrations (TypeError on HEAD)"
    ),
    # --- 被产品代码引用的未跟踪模块 ---
    "agent/runtime/resource_lifecycle.py": "untracked module imported by state.py:97",
    "agent/process/managed_web.py": "untracked module; managed web process owner",
    "agent/process/managed_web_child.py": (
        "untracked child script referenced by managed_web.py via Path(__file__).with_name"
    ),
    "agent/subagent/evidence.py": (
        "untracked module imported by subagent runner.py:37 / child.py:128 / "
        "process_runner.py:456"
    ),
    "agent/tools/directory.py": "untracked module imported by file_ops.py:18",
}

# 本轮（2026-10-11 收口）修改的文件：必须出现在候选中，且 manifest 标注。
THIS_ROUND = {
    "agent/runtime/state.py",
    "agent/runtime/evidence.py",
    "agent/runtime/loop.py",
    "agent/tui/app.py",
    "agent/tui/adapter.py",
    "agent/tui/dialogs.py",
    "main.py",
    "scripts/f2_f3_local_browser_journeys.py",
    "pyproject.toml",
    "README.md",
}

# 本轮修复依赖、必须随候选一起取工作树内容的文件（非闭包但被本轮改动引用）。
THIS_ROUND_SUPPORT = {
    "agent/tools/file_ops.py",
}

# 本轮新增/更新的回归测试与验收脚本：候选必须自带，否则安装物验证只跑旧测试。
THIS_ROUND_TESTS = {
    "tests/kernel/test_validation_request_freshness.py",
    "tests/kernel/test_run_result_usage.py",
    "tests/continuity/test_reopen_invalidation_q2.py",
    "tests/process/test_managed_web.py",
    "tests/tui/test_dialogs.py",
    "tests/tui/test_submission_receipts.py",
    "tests/tui/test_app.py",
    "tests/tui/test_adapter.py",
    "tests/tui/test_approval_journey.py",
    "tests/acceptance/test_daily_use_browser_driver.py",
    "tests/acceptance/test_daily_use_browser_driver_ev.py",
    "tests/cli/test_entrypoint.py",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _head_bytes(rel: str) -> bytes | None:
    proc = subprocess.run(
        ["git", "show", f"HEAD:{rel}"], cwd=ROOT, capture_output=True
    )
    if proc.returncode != 0:
        return None
    return proc.stdout


def _dirty_tracked() -> set[str]:
    """会话开始时已存在差异的 tracked 文件（既有用户工作，不属于本轮）。"""

    proc = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    dirty: set[str] = set()
    for line in proc.stdout.splitlines():
        if len(line) < 4:
            continue
        status, path = line[:2], line[3:].strip()
        if status.strip() == "??":
            continue
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        dirty.add(path)
    return dirty


def _tracked_files() -> list[str]:
    """HEAD 里全部被跟踪的产品文件（用于把候选补成可运行整树）。"""

    proc = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in proc.stdout.splitlines() if line]


def _copy_tracked(rel: str, out: Path, use_worktree: bool) -> str:
    target = out / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    if use_worktree:
        source = ROOT / rel
        target.write_bytes(source.read_bytes())
        return "worktree"
    head = _head_bytes(rel)
    assert head is not None, f"HEAD missing tracked file {rel}"
    target.write_bytes(head)
    return "head"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args()

    out = Path(args.out).resolve()
    if out.exists():
        import shutil

        shutil.rmtree(out)
    out.mkdir(parents=True)

    entries: list[dict] = []
    tracked = _tracked_files()
    tracked_set = set(tracked)
    dirty = _dirty_tracked()
    # 构建残留绝不能进候选：``build/lib`` 会让 setuptools 复用旧源码，负例
    # （删掉闭包模块）会从残留里被补回而假通过。这里显式排除。
    excluded = {"build", "dist", "first_agent.egg-info"}
    paths = sorted(tracked_set | set(WORKTREE_CLOSURE) | set(THIS_ROUND_TESTS))
    for rel in paths:
        if rel.split("/")[0] in excluded:
            continue
        source_path = ROOT / rel
        assert source_path.is_file(), f"manifest path missing in worktree: {rel}"
        target = out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source_path.read_bytes())
        if rel not in tracked_set:
            source = "worktree-untracked"
        elif rel in dirty:
            source = "worktree-modified"
        else:
            source = "worktree-unmodified"
        reason = WORKTREE_CLOSURE.get(rel)
        if reason is None:
            reason = (
                "this round fix (2026-10-11 product reliability closure)"
                if rel in THIS_ROUND
                else "pre-existing user work (dirty at session start)"
                if source == "worktree-modified"
                else "new file this round"
                if source == "worktree-untracked"
                else "unmodified product source"
            )
        entries.append(
            {
                "path": rel,
                "source": source,
                "head_has_differences": rel in dirty,
                "this_round_modified": rel in THIS_ROUND,
                "reason": reason,
                "sha256": _sha256(target),
            }
        )

    manifest = {
        "generated_by": "scripts/build_candidate_manifest.py",
        "head": subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip(),
        "closure_files": sorted(WORKTREE_CLOSURE),
        "this_round_modified": sorted(
            THIS_ROUND | THIS_ROUND_SUPPORT | THIS_ROUND_TESTS
        ),
        "file_count": len(entries),
        "files": entries,
    }
    Path(args.manifest).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"candidate: {out}")
    print(f"manifest: {args.manifest}")
    print(f"files: {len(entries)} (worktree-sourced: "
          f"{sum(1 for e in entries if e['source'] != 'head')})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
