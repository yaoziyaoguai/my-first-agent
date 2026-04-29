"""主循环运行时依赖打包：v0.4 Phase 2.1 最小切片。

中文学习边界
============

本模块定义 :class:`LoopContext`，目的是把"主循环运行所需、但不属于 durable
state 的依赖"显式打包，让后续 Phase 2.2/2.3 sub-slice 可以逐步把
``_run_planning_phase`` / ``_run_main_loop`` / ``_call_model`` 等 helper 的
**隐式模块级依赖**（``agent.core.client``、``agent.core.MODEL_NAME``、
``agent.core.MAX_LOOP_ITERATIONS``）改为**显式参数**，最终让 helpers 不再
依赖 ``agent.core`` 的模块单例。

本切片**只定义类型 + 在 chat() 内构造一次实例 + 用契约测试钉死边界**；
不修改任何 helper 签名、不改变任何行为、不接入除 chat() 之外的任何调用方。
真正的依赖注入是 Phase 2.2/2.3 的工作。

负责什么
--------
- 描述主循环运行时可观察、可注入的依赖三元组：``client`` / ``model_name`` /
  ``max_loop_iterations``。
- 提供 ``frozen=True`` dataclass，不可变防止 helper 偷偷 mutate。

不负责什么
----------
- ❌ 不持有 ``state`` / ``state.task`` / ``state.conversation``：那是 durable
  state，归 ``agent.state`` 管，进 checkpoint。LoopContext 进 checkpoint 会
  污染 durable schema 并把 SDK 实例引用泄漏到磁盘。
- ❌ 不持有 ``API_KEY`` / ``BASE_URL`` / 任何 secret 字符串：``client`` 内部
  封装了它们，但 LoopContext 自己 ``__repr__`` 不允许把它们 leak 出来（已用
  ``repr=False`` 标记 ``client`` 字段以防 ``logging.info(ctx)`` 意外印出 key）。
- ❌ 不持有 ``conversation.messages`` / ``task`` / ``pending_*``：那些是状态
  机本体。
- ❌ 不持有 ``turn_state`` / ``ConfirmationContext`` / ``continue_fn``：那些是
  per-turn 流转对象，不是循环级 dependency bundle。
- ❌ 不持有 checkpoint 函数引用 / log_runtime_event：那些是模块函数，
  ``import`` 即可访问，不需要再封装一层。

为什么放在独立文件
------------------
``agent/runtime_events.py`` 是 Runtime intent 词汇层；``agent/state.py`` 是
durable state schema；``agent/core.py`` 是主入口实现。LoopContext 既不是
intent，也不是 durable state，也不能在 ``core.py`` 内定义（否则
``confirm_handlers`` / ``response_handlers`` 后续吃 LoopContext 时会反向
import core，触发循环依赖）。独立文件最干净。

Artifacts 排查路径
------------------
LoopContext 不应出现在任何 artifacts 中：
- ``checkpoint.json``：禁止，由 ``test_loop_context_does_not_enter_checkpoint``
  钉死；
- ``conversation.messages``：禁止，由 v0.4 transition boundary 测试集体守住；
- ``agent_log.jsonl``：允许 ``str(ctx.model_name)`` 这种粒度的引用，但禁止
  ``str(ctx)`` 整体 dump（``client`` 可能 repr 出 SDK 内部 ``api_key``
  字符串）。

未来扩展点
----------
- Phase 2.2：``_run_planning_phase`` 改吃 ``LoopContext`` 替代 ``client`` /
  ``MODEL_NAME`` 隐式引用；
- Phase 2.3：``_run_main_loop`` / ``_call_model`` 改吃 ``LoopContext``；
- 长远：``state`` 也注入（不进 LoopContext，而是新增 ``RuntimeContext``
  把 state + LoopContext 组装），让 chat() 不再依赖模块级 ``state`` 单例。

MVP / mock / demo 边界
----------------------
本类**不是**完整 dependency container，**不是** DI framework；它只是一个
``frozen dataclass``，不做 lazy init / scope management / factory chain。
未来如果出现"测试需要 swap client / 需要按 turn 改 model_name"等场景，
可以在 LoopContext 上加 ``replace()`` helper 或用 ``dataclasses.replace``，
但本切片不预先构造这些功能。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class LoopContext:
    """主循环运行时依赖三元组。

    字段约束：
    - ``client``：Anthropic SDK 实例。``repr=False``，避免 ``__repr__`` 把
      SDK 内部 api_key 字符串泄露到日志/错误信息。**不参与等价比较**
      （SDK 实例无业务标识），但因为 ``frozen=True``，hash 行为依然由
      默认实现给出（基于 id），符合"context 实例不应被作为 dict key"
      的预期。
    - ``model_name``：字符串，如 ``"claude-sonnet-4.5"``。可安全打印。
    - ``max_loop_iterations``：循环兜底次数。可安全打印。

    本类**只承载运行时依赖**，不持有任何 mutable runtime state；任何
    需要 mutate 的字段都不允许添加（dataclass frozen 强制）。
    """

    client: Any = field(repr=False, compare=False, hash=False)
    model_name: str
    max_loop_iterations: int

    def __post_init__(self) -> None:
        """构造期最小契约校验。

        - ``model_name`` 必须是非空字符串：避免后续 helper 拿到空模型名
          再去调 SDK 触发难定位的 ``invalid_request`` 错误。
        - ``max_loop_iterations`` 必须正：0 / 负数会让循环立刻 guard 触发
          ``"对话循环次数过多"`` 误导用户。
        - ``client`` 必须不是 None：None 进来等于把"未初始化"伪装成"已
          注入"，比 explicit fail 更难排查。
        """

        if not isinstance(self.model_name, str) or not self.model_name.strip():
            raise ValueError(
                "LoopContext.model_name 必须是非空字符串；"
                "传入空值通常意味着初始化顺序错乱"
            )
        if not isinstance(self.max_loop_iterations, int) or self.max_loop_iterations <= 0:
            raise ValueError(
                "LoopContext.max_loop_iterations 必须是正整数；"
                "0 / 负数会让循环 guard 立刻触发"
            )
        if self.client is None:
            raise ValueError(
                "LoopContext.client 不允许为 None；"
                "若要在测试中 stub，请传入显式 fake 而不是 None"
            )
