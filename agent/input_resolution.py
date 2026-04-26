"""用户输入解析层：把原始 user_input 归类为 runtime 可理解的输入语义。

这个模块存在的原因是：`awaiting_user_input` 下面有两种非常不同的用户回复：
一种是 plan 里 `collect_input/clarify` 步骤的答案，答完这一步就应推进；
另一种是执行中途 `request_user_input` 或 fallback 暂停后的补充信息，答完后
只应继续当前 step，不能推进 step。

过去这些判断直接散落在 handler 的 if/else 里。这里把它抽成一个可测试、
可观察的输入解析层：user input 先进来，被解析成 `InputResolution`，后续
transition 再根据 resolution 做真正的 state mutation。

重要边界：
- 本模块只判断输入语义，不修改 state；
- 不调用模型；
- 不调用工具；
- 不做 slot filling 或复杂意图识别。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.runtime_observer import log_resolution


COLLECT_INPUT_ANSWER = "collect_input_answer"
RUNTIME_USER_INPUT_ANSWER = "runtime_user_input_answer"
UNKNOWN_INPUT = "unknown"


@dataclass(frozen=True, slots=True)
class InputResolution:
    """一次用户输入的解析结果。

    字段含义：
    - kind：输入类型，也就是设计讨论里的 input_kind。第一阶段只有
      `collect_input_answer`、`runtime_user_input_answer` 和 `unknown`。
    - content：用户原始答复，也就是设计讨论里的 answer。这里保留完整原文，
      包括多行内容，避免解析层提前丢信息。
    - pending_user_input_request：如果这是执行中途求助的回答，这里保存当时
      pending 里的 question / why_needed 等上下文；collect_input 答案没有 pending。
    - should_advance_step：解析层给 transition 的流程提示。collect_input 答完
      默认推进 step；runtime 求助答完只补充当前 step，不推进。

    第一阶段暂不引入 event/source/should_continue 字段：这些语义目前由 kind 和
    transition 返回值表达，避免为了框架完整性提前扩大数据结构。
    """

    kind: str
    content: str
    pending_user_input_request: dict[str, Any] | None = None
    should_advance_step: bool = False


def resolve_user_input(state: Any, user_input: str) -> InputResolution:
    """把当前用户输入解析成 `InputResolution`。

    输入：
    - state：当前 runtime state，解析器只读取 `task.status` 和
      `task.pending_user_input_request`。
    - user_input：CLI / frontend 传进来的原始用户答复。

    输出：
    - `InputResolution`：告诉后续 transition 这次输入属于哪类语义，以及是否
      应推进当前 step。

    第一阶段只处理 `awaiting_user_input + USER_REPLIED`，因为这是当前最痛的
    恢复链路：同一个 `awaiting_user_input` 状态下，用户回复后的推进规则不同。

    两类核心区别：
    - collect_input_answer：用户回答的是计划里的信息收集步骤，这一步的目标
      本来就是问用户；回答后可以视为该 step 完成。
    - runtime_user_input_answer：用户回答的是执行中途的 request_user_input /
      fallback；当前 step 还没完成，只是多了补充上下文，所以不能推进 step。

    这里不做 slot filling、不抽取预算/偏好/人数，也不做复杂换话题判断。原因是
    第一阶段目标是明确状态机边界，而不是把自然语言理解逻辑塞进 runtime。
    """
    content = user_input

    if getattr(state.task, "status", None) != "awaiting_user_input":
        return InputResolution(kind=UNKNOWN_INPUT, content=content)

    pending = getattr(state.task, "pending_user_input_request", None)
    if pending is None:
        resolution = InputResolution(
            kind=COLLECT_INPUT_ANSWER,
            content=content,
            should_advance_step=True,
        )
    else:
        resolution = InputResolution(
            kind=RUNTIME_USER_INPUT_ANSWER,
            content=content,
            pending_user_input_request=pending,
            should_advance_step=False,
        )

    log_resolution(
        resolution.kind,
        event_type="user.replied",
        event_source="user",
        details={"should_advance_step": resolution.should_advance_step},
    )
    return resolution
