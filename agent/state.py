from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# TaskState.status 目前仍是单字段，里面混合了 task 生命周期、plan 确认、
# step 确认、用户输入等待、工具确认等多个维度。下面这组 helper 是拆分状态模型
# 前的过渡层：先把硬编码字符串判断收口到一个地方，避免 core.py / handler 继续
# 散落 tuple。长期更清晰的方向是拆成 lifecycle_status / plan_status /
# user_input_status / tool_status，但第一阶段不迁移 schema，也不改 checkpoint。
KNOWN_TASK_STATUSES = {
    "idle",
    "planning",
    "running",
    "awaiting_plan_confirmation",
    "awaiting_step_confirmation",
    "awaiting_user_input",
    "awaiting_tool_confirmation",
    "done",
    "failed",
    "cancelled",
}

TERMINAL_TASK_STATUSES = {"done", "failed", "cancelled"}
PLAN_CONFIRMATION_STATUSES = {"awaiting_plan_confirmation"}
STEP_CONFIRMATION_STATUSES = {"awaiting_step_confirmation"}
USER_INPUT_WAIT_STATUSES = {"awaiting_user_input"}
TOOL_CONFIRMATION_STATUSES = {"awaiting_tool_confirmation"}


def is_known_task_status(status: str) -> bool:
    """判断 status 是否属于当前 Runtime 已知的任务状态集合。

    这是状态 schema 拆分前的集中枚举，不代表这些状态在同一维度上等价。
    """
    return status in KNOWN_TASK_STATUSES


def is_terminal_task_status(status: str) -> bool:
    """判断 status 是否表示任务已进入终止态。

    `done / failed / cancelled` 不应该因为 `current_plan is None` 被当作损坏态；
    它们通常已经完成清理，或者未来会进入独立的失败/取消收尾路径。
    """
    return status in TERMINAL_TASK_STATUSES


def task_status_requires_plan(task: "TaskState") -> bool:
    """判断当前 task.status 在 `current_plan is None` 时是否不一致。

    这个 helper 只服务第一阶段的 core invariant，不改变状态 schema：
    - plan / step confirmation 必须有 plan；
    - collect_input/clarify 的 awaiting_user_input 通过 pending=None 表达，也必须有 plan；
    - runtime request_user_input/fallback/no_progress 有 pending，本身携带恢复问题，
      第一阶段不强制要求 plan；
    - awaiting_tool_confirmation 由 pending_tool 表达工具审批子状态，单步无 plan
      工具确认是合法路径；
    - running 继续保持旧行为：plan=None 会被视为不一致。这里的语义确实混合，
      后续应在更正式的生命周期/step 状态拆分中处理；
    - unknown status 视为不一致，让 core 在 plan=None 时自愈 reset。
    """
    status = task.status

    if status == "running":
        return True
    if status in PLAN_CONFIRMATION_STATUSES | STEP_CONFIRMATION_STATUSES:
        return True
    if status in USER_INPUT_WAIT_STATUSES:
        return task.pending_user_input_request is None
    if status in TOOL_CONFIRMATION_STATUSES:
        return False
    if is_terminal_task_status(status) or status in {"idle", "planning"}:
        return False
    return not is_known_task_status(status)


@dataclass
class RuntimeState:
    """
    运行时稳定上下文。

    这一层放“规则”和“配置”：
    - system prompt
    - 模型名
    - 是否开启 review
    - 历史压缩时最多保留几条最近消息

    这层的特点：
    - 不属于原始对话
    - 不参与历史压缩
    - 每次调用模型时都会被使用
    """

    # 系统提示词：定义 agent 是谁、做事规则、能力边界等
    # 它代表当前这次 agent 会话真正使用的顶层规则文本
    # 后续如果 prompt_builder 有变化，最终产物也应该落到这里

    system_prompt: str

    # 当前使用的模型名，可为空
    model_name: str | None = None

    # 是否开启 review / retry 相关能力
    review_enabled: bool = True

    # 历史压缩时，最近保留多少条原始消息不压缩
    max_recent_messages: int = 6


@dataclass
class ConversationState:
    """
    短期会话状态。

    这一层放“当前会话里的原始内容”：
    - user / assistant 对话消息
    - tool 调用轨迹

    这里先不做太强的类型约束，方便后续迭代。
    """

    # 原始对话消息列表
    # 约定：尽量只放 user / assistant 消息
    # 例如：
    # [{"role": "user", "content": "你好"}]
    messages: list[dict[str, Any]] = field(default_factory=list)

    # 工具调用轨迹
    # 用来记录某一轮调用了哪些工具、输入输出是什么
    # 例如：
    # [{"tool": "read_file", "input": {...}, "output": "..."}]
    tool_traces: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class MemoryState:
    """
    记忆层状态。

    这一层放“不是原始对话，但会影响后续推理”的内容：
    - 历史摘要
    - 长期记忆
    - checkpoint 恢复数据
    - session id
    """

    # 会话工作摘要
    # 用来存较早历史对话的压缩结果
    # 例如：“用户之前让 agent 帮他分析 xxx，并已完成前两步……”
    working_summary: str | None = None

    # 长期记忆列表
    # 可放用户偏好、长期约束、跨会话记忆等
    long_term_notes: list[str] = field(default_factory=list)

    # checkpoint 数据
    # 先宽松一点，用 dict 保存恢复会话需要的信息
    checkpoint_data: dict[str, Any] | None = None

    # 当前 session 的唯一标识，可为空
    session_id: str | None = None


@dataclass
class TaskState:
    """
    当前任务执行态。

    这一层放“本轮任务的动态执行信息”：
    - 用户当前目标
    - 当前计划
    - 当前状态
    - 重试计数
    - 错误信息
    """

    # 用户当前目标
    # 例如：“帮我 review 这个仓库”
    user_goal: str | None = None

    # 当前计划
    # 先用 dict[str, Any]，后面如果 plan 结构稳定了再单独定义 Plan 类
    current_plan: dict[str, Any] | None = None

    current_step_index: int = 0

    # 当前任务状态
    # 可选值示例：
    # idle / planning / running / awaiting_plan_confirmation / awaiting_step_confirmation / awaiting_user_input / awaiting_tool_confirmation / done / failed
    status: str = "idle"

    # 当前轮重试次数
    retry_count: int = 0

    # 主循环已经跑了多少轮
    loop_iterations: int = 0

    # 连续达到 max_tokens 的次数
    consecutive_max_tokens: int = 0

    # 连续 end_turn 但没有任何"有效推进"的次数。
    # "有效推进"= 调任何工具（业务或元）。每次模型 end_turn 且当前 plan running 时 ++；
    # 任何工具被执行时清零。达到阈值（>=2）触发兜底切 awaiting_user_input，防死循环。
    consecutive_end_turn_without_progress: int = 0

    # 当前任务已发生的工具调用次数（持久化的真实计数，防止跨确认轮被清零）
    tool_call_count: int = 0

    # 最近一次错误信息
    last_error: str | None = None

    # 当前轮是否有效开启了 review 请求
    effective_review_request: bool = False

    # 当前待确认的工具（control plane）
    # 结构：{"tool_use_id": str, "tool": str, "input": dict}
    pending_tool: dict[str, Any] | None = None

    # 当前阻塞中的"执行期求助"请求（来自 request_user_input 元工具）。
    # 结构：{"question": str, "why_needed": str, "options": list[str], "context": str,
    #        "tool_use_id": str, "step_index": int}
    # 仅当 status == "awaiting_user_input" 且本轮由 request_user_input 触发时才非 None；
    # collect_input/clarify 步骤进入 awaiting_user_input 时此字段保持 None，
    # handle_user_input_step 据此区分两种 awaiting_user_input。
    pending_user_input_request: dict[str, Any] | None = None

    # 是否每完成一个计划步骤都等待用户确认后再继续。
    # 默认关闭：用户确认整体 plan 后，普通步骤自动推进；高风险工具仍走工具确认。
    confirm_each_step: bool = False

    # 工具执行记录（用于幂等执行）
    # key: tool_use_id
    # value: {"tool": str, "input": dict, "result": Any}
    tool_execution_log: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentState:
    """
    统一总状态容器。

    这是整个 agent 会话的“总装配对象”。

    它把 4 个层次组合起来：
    - runtime: 运行规则和配置
    - conversation: 原始对话和工具轨迹
    - memory: 摘要、长期记忆、checkpoint
    - task: 当前任务执行态
    """

    # 运行时稳定配置
    runtime: RuntimeState

    # 当前会话对话区
    conversation: ConversationState = field(default_factory=ConversationState)

    # 记忆区
    memory: MemoryState = field(default_factory=MemoryState)

    # 当前任务区
    task: TaskState = field(default_factory=TaskState)

    def get_system_prompt(self) -> str:
        """
        读取当前运行态真正生效的 system prompt。
        """
        return self.runtime.system_prompt


    def set_system_prompt(self, system_prompt: str) -> None:
        """
        更新当前运行态的 system prompt。

        参数:
            system_prompt: 新的完整 system prompt 文本
        """
        self.runtime.system_prompt = system_prompt


    def update_runtime(
        self,
        *,
        system_prompt: str | None = None,
        model_name: str | None = None,
        review_enabled: bool | None = None,
        max_recent_messages: int | None = None,
    ) -> None:
        """
        统一更新运行态配置。

        用途：
        - 只改 system prompt
        - 或者顺手更新 model / review / recent message 策略
        """
        if system_prompt is not None:
            self.runtime.system_prompt = system_prompt

        if model_name is not None:
            self.runtime.model_name = model_name

        if review_enabled is not None:
            self.runtime.review_enabled = review_enabled

        if max_recent_messages is not None:
            self.runtime.max_recent_messages = max_recent_messages





    

    def add_user_message(self, content: str) -> None:
        """
        添加一条用户消息到 conversation.messages 中。

        参数:
            content: 用户输入的文本内容
        """
        self.conversation.messages.append({
            "role": "user",
            "content": content,
        })

    def add_assistant_message(self, content: str) -> None:
        """
        添加一条助手消息到 conversation.messages 中。

        参数:
            content: 助手输出的文本内容
        """
        self.conversation.messages.append({
            "role": "assistant",
            "content": content,
        })

    def add_tool_trace(self, trace: dict[str, Any]) -> None:
        """
        添加一条工具调用轨迹。

        参数:
            trace: 工具调用记录，结构暂时保持灵活
        """
        self.conversation.tool_traces.append(trace)

    def reset_task(self) -> None:
        """
        重置当前任务执行态。

        用途：
        - 一轮任务结束后清空 task 状态
        - 开始新任务前做初始化
        """
        self.task.user_goal = None
        self.task.current_plan = None
        self.task.status = "idle"
        self.task.retry_count = 0
        self.task.current_step_index = 0
        self.task.loop_iterations = 0
        self.task.consecutive_max_tokens = 0
        self.task.consecutive_end_turn_without_progress = 0
        self.task.tool_call_count = 0
        self.task.last_error = None
        self.task.effective_review_request = False
        self.task.pending_tool = None
        self.task.pending_user_input_request = None
        self.task.confirm_each_step = False
        self.task.tool_execution_log = {}


def create_agent_state(
    system_prompt: str,
    model_name: str | None = None,
    review_enabled: bool = True,
    max_recent_messages: int = 6,
) -> AgentState:
    """
    创建一个新的 AgentState 对象。

    参数:
        system_prompt: 系统提示词，定义 agent 的顶层规则
        model_name: 模型名称，可为空
        review_enabled: 是否默认开启 review 能力
        max_recent_messages: 历史压缩时，最近保留几条原始消息

    返回:
        一个初始化完成的 AgentState 实例
    """
    return AgentState(
        runtime=RuntimeState(
            system_prompt=system_prompt,
            model_name=model_name,
            review_enabled=review_enabled,
            max_recent_messages=max_recent_messages,
        )
    )
