"""v0.4 transition boundary tests 的兼容索引。

原文件曾承载 3000+ 行历史 characterization tests。v0.9.x deep stabilization
将实际测试体按行为主题拆到 ``tests/test_transition_*.py``，这里保留一个轻量
索引测试，证明 pytest discovery 能看到拆分后的目标文件。真实 coverage 在拆分文件中，
不要再把新测试塞回这个巨型入口。
"""

from __future__ import annotations

from pathlib import Path

_SPLIT_TRANSITION_TEST_FILES = (
    "test_transition_tool_success_boundaries.py",
    "test_transition_model_output_boundaries.py",
    "test_transition_pending_confirmation_boundaries.py",
    "test_transition_checkpoint_boundaries.py",
)


def test_v0_4_transition_boundaries_are_split_by_behavior_area() -> None:
    """原巨型文件只保留索引，防止后续又把跨主题 coverage 堆回这里。"""

    tests_dir = Path(__file__).resolve().parent
    for filename in _SPLIT_TRANSITION_TEST_FILES:
        path = tests_dir / filename
        assert path.is_file(), f"missing split transition test file: {filename}"
        assert path.read_text(encoding="utf-8").startswith('"""')
