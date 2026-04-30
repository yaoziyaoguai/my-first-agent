"""log_event 命名碰撞签名守卫（v0.5 Phase 1 第六小步）。

────────────────────────────────────────────────────────────────────
本测试模块要解决的真实风险
────────────────────────────────────────────────────────────────────
仓库内有两个 ``log_event`` 函数，**同名但签名不同**：

1. ``agent.logger.log_event(event_type, data)``
   - legacy 低层入口，两位 positional；
   - 9 处历史调用点（planner / memory / checks / session / review /
     context / health_check / checkpoint 懒加载 / runtime_observer 兜底）。

2. ``agent.runtime_observer.log_event(event_type, *, event_source=None,
   event_payload=None, event_channel=None)``
   - RuntimeEvent / confirmation evidence 入口，后三参 keyword-only；
   - 新代码（``agent/core.py``、``agent/confirm_handlers.py``）必须用此入口。

误用风险
--------
新人模仿 ``agent/confirm_handlers.py`` 的写法 ``log_event("...",
event_payload={...})``，但 ``import`` 时却拿到 ``agent.logger.log_event``
→ 立即 ``TypeError``；或反过来在 confirmation 处用两位 positional →
绕开 ``_safe_log_value`` 脱敏写入未净化 payload。

为什么本切片只做签名守卫，不重命名
-----------------------------------
- 重命名会牵动 9 处 legacy 调用点，跨出 v0.5 第六小步"0 runtime
  行为变更"边界；
- 重命名属独立 slice（见 ``docs/V0_5_OBSERVER_AUDIT.md`` §G5）；
- 在那之前，本测试用 ``inspect.signature`` 把两份签名钉死，**任何**
  让二者签名"看起来一致"的改动都会触发本测试失败，强制把变更暴露
  到 PR review。

本测试不做的事
---------------
- 不调真实日志写入；
- 不读 ``LOG_FILE`` / ``agent_log.jsonl`` / ``.env``；
- 不读 ``sessions/`` ``runs/`` 真实文件；
- 不削弱已有断言、不引入 skip / xfail；
- 不强制重命名（只锁签名）。
"""

from __future__ import annotations

import inspect

import agent.logger as legacy_logger_mod
import agent.runtime_observer as observer_mod


def test_two_log_events_are_distinct_callables():
    """两个 log_event 必须是不同函数对象。

    若有人把 ``from agent.runtime_observer import log_event`` 重新绑回
    ``agent.logger.log_event``（或反之），本断言立即失败。
    """
    assert legacy_logger_mod.log_event is not observer_mod.log_event


def test_legacy_logger_log_event_signature_pinned():
    """``agent.logger.log_event`` 当前签名 = ``(event_type, data)``。

    锁住两位 POSITIONAL_OR_KEYWORD 参数；任何加 keyword-only / 改名 /
    改默认值的 PR 都必须主动更新本测试，让 reviewer 看到契约变更。
    """
    sig = inspect.signature(legacy_logger_mod.log_event)
    params = list(sig.parameters.values())
    assert [p.name for p in params] == ["event_type", "data"]
    for p in params:
        assert p.kind == inspect.Parameter.POSITIONAL_OR_KEYWORD
        assert p.default is inspect.Parameter.empty


def test_runtime_observer_log_event_signature_pinned():
    """``agent.runtime_observer.log_event`` 当前签名锁住:

    - ``event_type`` 是唯一 POSITIONAL_OR_KEYWORD 必填；
    - ``event_source`` / ``event_payload`` / ``event_channel`` 全为
      KEYWORD_ONLY 且默认 ``None``。

    若有人把 keyword-only 改成 positional，新代码可能误传普通 dict
    到 ``event_source`` 字段（类型不一致但 Python 不报错）→ payload
    会出现在错误位置，evidence chain 被污染。本测试就是钉死这种回归。
    """
    sig = inspect.signature(observer_mod.log_event)
    params = sig.parameters

    assert list(params) == [
        "event_type",
        "event_source",
        "event_payload",
        "event_channel",
    ]

    assert params["event_type"].kind == inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert params["event_type"].default is inspect.Parameter.empty

    for kw_name in ("event_source", "event_payload", "event_channel"):
        p = params[kw_name]
        assert p.kind == inspect.Parameter.KEYWORD_ONLY, (
            f"{kw_name} 必须保持 keyword-only，否则新代码可能误用 positional"
        )
        assert p.default is None


def test_legacy_and_observer_log_event_signatures_are_not_compatible():
    """两个 log_event 的签名必须保持"不可互换"。

    用一组 keyword 参数（``event_payload=...``）尝试绑定到 legacy 签名，
    必须失败 → 证明二者 API 不兼容、不可通过简单 import 替换互相替代。
    这条断言失败意味着有人无意中把签名改"兼容"了，碰撞被掩盖。
    """
    sig_legacy = inspect.signature(legacy_logger_mod.log_event)
    try:
        sig_legacy.bind("evt", event_payload={"k": "v"})
    except TypeError:
        return
    raise AssertionError(
        "legacy logger.log_event 不应接受 event_payload 关键字；"
        "若它现在接受了，说明命名碰撞被掩盖，请 review 改动"
    )
