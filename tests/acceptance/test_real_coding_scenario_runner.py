"""F3a 后的 operator 合同：文字只作 UI 辅助；完成只由 typed 终态判定。"""

from __future__ import annotations

from scripts.run_real_coding_scenario import DogfoodOperator


def test_operator_only_handles_governance_prompts_and_never_coaches() -> None:
    operator = DogfoodOperator(task="修复项目并验证。", max_consents=4, max_resumes=1)

    assert operator.next_input(("First Agent is ready",)) == "修复项目并验证。"
    assert operator.next_input(("Remote provider disclosure required",)) == "y"
    assert operator.next_input(
        ("Approval required\ntool: write_file\npreview: edit report.py",)
    ) == "y"
    assert operator.approved_tools == ["write_file"]
    assert operator.next_input(("Task paused at a safe execution limit.",)) == "/resume"
    # F3a："Task is closed." 文案不再签完成；operator 只把它当普通 idle 信号。
    assert operator.next_input(("Task is closed.",)) == "/exit"
    assert operator.stop_reason == "unexpected_idle_before_verified_done"

    stalled = DogfoodOperator(task="完成任务。", max_consents=1, max_resumes=0)
    assert stalled.next_input(("First Agent is ready",)) == "完成任务。"
    assert stalled.next_input(("I changed one file but did not test it.",)) == "/exit"
    assert stalled.stop_reason == "unexpected_idle_before_verified_done"
