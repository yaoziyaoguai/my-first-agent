"""Slash command 的轻量执行层。

这个模块位于 InputIntent 和 RuntimeEvent 之间：
- InputIntent 只负责识别“这是 slash command”以及解析 command_name/args；
- CommandRegistry 只负责执行 UI/control command 的本地控制语义；
- RuntimeEvent 仍由 main.py 负责投影到用户可见输出。

这里不能写 checkpoint，不能追加 conversation.messages，不能构造 Anthropic API
messages，也不能读取或推进 TaskState 状态机本体。它解决的是 main.py 里 command
分支继续硬编码扩散的根因；不是插件系统、权限系统或动态命令注册框架。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal


CommandResultKind = Literal["ok", "unknown", "invalid_args"]


@dataclass(frozen=True, slots=True)
class CommandSpec:
    """描述一个 UI/control slash command 的静态规格。

    CommandSpec 只属于本地 command 执行层，不是 InputIntent，也不是 RuntimeEvent。
    它不会进入 checkpoint、runtime_observer、conversation.messages 或 Anthropic API
    messages。当前 registry 是固定表，用来收敛 main.py 的 if/elif 分支；后续若要
    做插件化 command registry，需要单独设计生命周期、权限和 pending 状态策略，
    不能在这个轻量结构上继续堆兼容补丁。
    """

    name: str
    aliases: tuple[str, ...] = ()
    description: str = ""
    usage: str = ""
    allow_args: bool = False


@dataclass(frozen=True, slots=True)
class CommandContext:
    """执行 command 时允许读取的最小上下文。

    这里刻意只放只读 state 和少量依赖注入函数。CommandRegistry 不能保存 checkpoint，
    不能写 conversation.messages，不能触发模型调用，也不能把 RuntimeEvent 或
    InputIntent 对象塞进来。`reload_registry` 是现有 `/reload_skills` 行为所需的
    兼容依赖；删除条件是 skill reload 也迁移到更正式的 control command 服务层。
    """

    state: Any | None = None
    reload_registry: Callable[[], Any] | None = None


@dataclass(frozen=True, slots=True)
class CommandResult:
    """slash command 执行后的结构化控制结果。

    CommandResult 不是 RuntimeEvent：它只是 command 执行层给 adapter 的结果，main.py
    再把 message 投影成 `command.result` RuntimeEvent 或 simple CLI print。它也不是
    InputIntent，不应写入 checkpoint 或 conversation.messages，更不能影响
    Anthropic API messages、TaskState、tool_use_id 配对或 tool_result placeholder。
    """

    kind: CommandResultKind
    command_name: str
    message: str | None = None
    should_exit: bool = False
    should_clear: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def handled(self) -> bool:
        """CommandResult 一经生成就表示 control 输入已被 command 层消费。"""

        return True


class CommandRegistry:
    """固定 slash command registry。

    这是 UI/control command 执行层的集中入口，目的是让 main.py 不再为每个 command
    散落 if/elif。它不是动态插件系统，不做权限判断，不保存状态；执行结果通过
    CommandResult 返回，由 adapter 决定如何投影成 RuntimeEvent 或 simple CLI 输出。
    """

    def __init__(self, specs: tuple[CommandSpec, ...]) -> None:
        self._specs = specs
        self._by_name: dict[str, CommandSpec] = {}
        for spec in specs:
            self._by_name[spec.name] = spec
            for alias in spec.aliases:
                self._by_name[alias] = spec

    @property
    def specs(self) -> tuple[CommandSpec, ...]:
        """返回静态 command 列表，供 /help 渲染；调用方不能动态注册。"""

        return self._specs

    def execute(
        self,
        command_name: str,
        command_args: str = "",
        *,
        context: CommandContext | None = None,
    ) -> CommandResult:
        """执行一个已由 InputIntent 解析出的 command。

        这里消费的是 command_name/command_args，而不是重新解析 raw slash 字符串。
        未知 command 也在 command 层显式消费并返回错误提示，避免 `/unknown` 落入
        普通模型消息分支。pending 状态下是否允许 command 打断由 InputIntent 优先级
        决定；本函数不读取 pending_user_input_request/pending_tool 来改产品语义。
        """

        normalized = command_name.strip().lstrip("/").lower()
        args = command_args.strip()
        spec = self._by_name.get(normalized)
        if spec is None:
            return CommandResult(
                kind="unknown",
                command_name=normalized,
                message=(
                    f"[系统] 未知命令 /{normalized or '?'}。"
                    "输入 /help 查看可用命令。"
                ),
                metadata={"command_args": args},
            )

        if args and not spec.allow_args:
            return CommandResult(
                kind="invalid_args",
                command_name=spec.name,
                message=f"[系统] /{spec.name} 不接受参数。用法：{spec.usage}",
                metadata={"command_args": args},
            )

        ctx = context or CommandContext()
        if spec.name == "help":
            return self._help_result()
        if spec.name == "status":
            return self._status_result(ctx.state)
        if spec.name == "clear":
            return CommandResult(
                kind="ok",
                command_name=spec.name,
                message=(
                    "[系统] 已请求清空当前界面显示；Runtime 状态、checkpoint 和 "
                    "conversation.messages 均未改变。"
                ),
                should_clear=True,
            )
        if spec.name == "exit":
            return CommandResult(
                kind="ok",
                command_name=spec.name,
                message="[系统] 正在退出。",
                should_exit=True,
            )
        if spec.name == "reload_skills":
            return self._reload_skills_result(ctx)

        return CommandResult(
            kind="unknown",
            command_name=spec.name,
            message=f"[系统] 命令 /{spec.name} 尚未接入执行逻辑。",
        )

    def _help_result(self) -> CommandResult:
        """渲染 help 文本；只读静态 specs，不访问 Runtime state。"""

        lines = ["[系统] 可用命令："]
        for spec in self._specs:
            lines.append(f"  {spec.usage:<18} {spec.description}")
        return CommandResult(kind="ok", command_name="help", message="\n".join(lines))

    def _status_result(self, state: Any | None) -> CommandResult:
        """把 Runtime 状态做只读摘要；不写 checkpoint/messages。"""

        if state is None:
            return CommandResult(
                kind="ok",
                command_name="status",
                message="[系统] 当前 Runtime 状态不可用。",
            )

        task = getattr(state, "task", None)
        lines = ["[系统] 当前 Runtime 状态："]
        if task is None:
            lines.append("  task: <missing>")
            return CommandResult(kind="ok", command_name="status", message="\n".join(lines))

        lines.append(f"  status: {getattr(task, 'status', None)}")
        lines.append(f"  current_step_index: {getattr(task, 'current_step_index', None)}")
        pending_request = getattr(task, "pending_user_input_request", None)
        pending_tool = getattr(task, "pending_tool", None)
        if pending_request:
            question = pending_request.get("question") or "<unknown>"
            lines.append(f"  pending_user_input_request: {question}")
        if pending_tool:
            tool_name = pending_tool.get("tool") or "<unknown>"
            lines.append(f"  pending_tool: {tool_name}")
        if getattr(task, "current_plan", None):
            goal = task.current_plan.get("goal", "<unknown>")
            lines.append(f"  current_plan: {goal}")
        return CommandResult(kind="ok", command_name="status", message="\n".join(lines))

    def _reload_skills_result(self, ctx: CommandContext) -> CommandResult:
        """复用现有 skill reload 行为，并把输出收敛成 CommandResult。"""

        if ctx.reload_registry is None:
            return CommandResult(
                kind="invalid_args",
                command_name="reload_skills",
                message="[系统] 当前环境不支持重新加载 skills。",
            )
        skill_registry = ctx.reload_registry()
        lines = [f"[系统] Skill 已重新加载，当前 {skill_registry.count()} 个可用"]
        lines.extend(f"  {warning}" for warning in skill_registry.get_warnings())
        return CommandResult(
            kind="ok",
            command_name="reload_skills",
            message="\n".join(lines),
        )


DEFAULT_COMMAND_SPECS: tuple[CommandSpec, ...] = (
    CommandSpec("help", description="显示可用本地命令", usage="/help"),
    CommandSpec("status", description="显示当前 Runtime 状态摘要", usage="/status"),
    CommandSpec("clear", description="请求清空当前界面显示", usage="/clear"),
    CommandSpec("exit", aliases=("quit",), description="退出当前交互会话", usage="/exit"),
    CommandSpec("reload_skills", description="重新加载本地 skills", usage="/reload_skills"),
)

DEFAULT_COMMAND_REGISTRY = CommandRegistry(DEFAULT_COMMAND_SPECS)
