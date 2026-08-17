"""P3（冻结合同）：post-spawn ``returncode=None`` 的 outcome taxonomy。

``SPAWN_FAILED`` 断言 spawn 前/时证明未执行（映射 ``executed=False``）。spawn 之后
无法确认退出（reap 后 returncode 仍 None 且未超时）不是「未执行」——把它分类为
SPAWN_FAILED 会让从未证明不存在的 effect 被当作 known-not-executed 消化。Green：
该形状必须进入 unknown（``ProcessCleanupError`` → Runtime recovery），不得产出 draft。
"""

from __future__ import annotations

import pytest

from agent.process.contracts import ProcessDraftOutcome
from agent.process.runner import ProcessCleanupError, _classify


def test_015_post_spawn_unconfirmed_exit_is_unknown_not_spawn_failed() -> None:
    """classify(False, None)（spawn 后、未超时、无法确认退出）必须 fail closed。"""

    with pytest.raises(ProcessCleanupError):
        _classify(timed_out=False, returncode=None)


def test_015_confirmed_exits_keep_closed_taxonomy() -> None:
    """既有 closed 分类不回归：exited/signaled/timed_out_reaped 语义不变。"""

    assert _classify(False, 0) == (ProcessDraftOutcome.EXITED, None)
    assert _classify(True, 0)[0] is ProcessDraftOutcome.TIMED_OUT_REAPED
    outcome, signal_name = _classify(False, -9)
    assert outcome is ProcessDraftOutcome.SIGNALED
    assert signal_name == "SIGKILL"
