"""全套件测试护栏：任何测试都不得写入用户真实默认 state root。

产品默认 root 派生自 owner home（``~/.local/state/my-first-agent/v1``）。测试必须注入
显式 ``--state-root``、fixture home 或自行 monkeypatch ``default_state_root``；
否则这里 fail loud，防止测试污染真实用户状态。这是 test-only seam，不是产品行为。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.continuity import sessions

_REAL_DEFAULT_STATE_ROOT = sessions.default_state_root


@pytest.fixture(autouse=True)
def _guard_real_default_state_root(monkeypatch: pytest.MonkeyPatch) -> None:
    def guarded(home: Path | None = None) -> Path:
        if home is None:
            raise AssertionError(
                "test derived the real user default state root; "
                "inject --state-root / fixture home instead"
            )
        return _REAL_DEFAULT_STATE_ROOT(home)

    monkeypatch.setattr(sessions, "default_state_root", guarded)
