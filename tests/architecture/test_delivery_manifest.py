"""009 delivery content presence oracles（materialized-tree 兼容，不依赖 .git/manifest）。

content gate 不忽略任何 delivery 测试：这些测试在真实仓库与 materialized tree 中都成立——
它们只验证 delivery 内容存在与 verifier 合同，不读取 .git、不读取作为 control 的 manifest
（manifest 在 materialized tree 中并不物化）。membership 的真值由 v2 oracles 与 content
gate 自带的 reconcile 负责。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

_MEMORY_PATHS = (
    "agent/memory/__init__.py",
    "agent/memory/contracts.py",
    "agent/memory/source.py",
    "agent/memory/store.py",
    "agent/memory/tools.py",
    "tests/memory/__init__.py",
    "tests/memory/test_integration.py",
    "tests/memory/test_source.py",
    "tests/memory/test_store.py",
    "tests/memory/test_tools.py",
)

_CORE_MODULES = (
    "agent/__init__.py",
    "main.py",
    "agent/runtime/loop.py",
    "agent/runtime/contracts.py",
    "agent/runtime/checkpoint.py",
    "agent/tui/adapter.py",
    "agent/tui/app.py",
    "scripts/verify_materialized_tree.py",
)


def test_memory_files_are_delivered_in_tree() -> None:
    """delivery 必须包含 memory 源/测试包（不被 ignore/排除规则吞掉）。"""
    for relative in _MEMORY_PATHS:
        assert (ROOT / relative).is_file(), f"{relative} absent from delivered tree"


def test_core_product_modules_present() -> None:
    """delivery 必须包含 kernel + TUI + verifier 等核心模块。"""
    for relative in _CORE_MODULES:
        assert (ROOT / relative).is_file(), f"{relative} absent from delivered tree"


def test_verifier_rejects_generate_mode() -> None:
    """verifier 不得有 manifest-writing generate mode。"""
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "verify_materialized_tree.py"), "--generate"],
        capture_output=True, text=True,
    )
    assert result.returncode != 0, "--generate must be rejected (no generate mode)"
