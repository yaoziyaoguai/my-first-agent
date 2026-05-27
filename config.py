"""Legacy runtime config compatibility layer.

职责边界：
- 本模块服务旧 CLI/runtime 入口和少量历史 helper，保留 MODEL_NAME /
  REVIEW_MODEL_NAME / MAX_* 等兼容常量。
- 新 provider/API 配置的权威入口是 ``agent/provider/config.py``。
- 本地 agent customization 配置的权威入口是 ``agent/local_config.py``。
- provider dogfood / real-api path 不应依赖本模块的 os.environ mutation。
"""

import os
from pathlib import Path

from dotenv import dotenv_values, load_dotenv


def load_legacy_dotenv_config(project_root: Path | None = None) -> bool:
    """显式加载 legacy `.env` 配置，import config 时不会自动调用。

    新 provider/dogfood 路径使用 agent/provider/config.py 与 scoped dotenv loader，
    不依赖这里的 os.environ mutation。这个函数只保留给旧 CLI/手工入口在确实
    需要兼容 `.env` 时显式 opt-in；默认 override=False，shell 显式设置仍优先。
    """
    root = Path(project_root).resolve() if project_root is not None else Path.cwd().resolve()
    return bool(load_dotenv(root / ".env", override=False))


def _resolve_model_name() -> str | None:
    """按优先级解析模型名。

    MY_FIRST_AGENT_LLM_MODEL 是 v0.10+ 统一 provider 配置的权威 env var；
    MODEL_NAME / ANTHROPIC_MODEL / OPENAI_MODEL 是历史兼容名。

    返回 None 表示没有任何模型名配置——这在 fake 模式下是正常的，
    调用方应提供 fake-llm 兜底。
    """
    return (
        os.getenv("MY_FIRST_AGENT_LLM_MODEL")
        or os.getenv("MODEL_NAME")
        or os.getenv("ANTHROPIC_MODEL")
        or os.getenv("OPENAI_MODEL")
    )


def _resolve_api_key() -> str | None:
    """按优先级解析 API key：ANTHROPIC_API_KEY > OPENAI_API_KEY。"""
    return os.getenv("ANTHROPIC_API_KEY") or os.getenv("OPENAI_API_KEY")


def _resolve_base_url() -> str | None:
    """按优先级解析 base URL：ANTHROPIC_BASE_URL > OPENAI_BASE_URL。"""
    return os.getenv("ANTHROPIC_BASE_URL") or os.getenv("OPENAI_BASE_URL")


def get_legacy_api_key() -> str | None:
    """显式读取 legacy API key。

    v0.9.x deep stabilization 后，`API_KEY` 不再在 import config 时绑定。
    旧调用方仍可通过 lazy compatibility attribute 读取，但新代码应调用这个
    getter，避免把 provider config 权威路径和 legacy runtime 兼容层混在一起。
    """

    return _resolve_api_key()


def get_legacy_base_url() -> str | None:
    """显式读取 legacy base URL；不在模块 import 时触发 env read。"""

    return _resolve_base_url()


def get_legacy_model_name() -> str:
    """显式读取 legacy model name；新 provider 路径不要依赖此 getter。

    当所有环境变量都未设置时返回 "fake-llm" 兜底值，确保 fake/local 模式
    下 LoopContext 不会因为 model_name 为空而崩溃。
    """

    return _resolve_model_name() or "fake-llm"


def get_legacy_review_model_name() -> str | None:
    """显式读取 legacy review model name；只服务旧 review 兼容入口。"""

    return os.getenv("REVIEW_MODEL_NAME")


def _load_project_dotenv_values(project_root: Path | None = None) -> dict[str, str]:
    """通过项目配置层读取 dotenv 值，但不污染 ``os.environ``。

    这是给 dogfood/测试用的安全边界：允许程序自动加载项目配置，
    但返回值只在内存中传递，调用方不得打印、记录或序列化 secret value。
    """
    root = Path(project_root).resolve() if project_root is not None else Path.cwd().resolve()
    dotenv_path = root / ".env"
    if not dotenv_path.is_file():
        return {}
    raw_values = dotenv_values(dotenv_path)
    values: dict[str, str] = {}
    for key, value in raw_values.items():
        if isinstance(key, str) and isinstance(value, str) and value.strip():
            values[key] = value.strip()
    return values


def _resolve_scoped_config_value(
    names: tuple[str, ...],
    *,
    project_root: Path | None = None,
    prefer_project_dotenv: bool = False,
) -> tuple[str | None, str]:
    """按 source kind 解析配置值，不暴露配置值本身。

    ``source kind`` 只描述来源类别：project_dotenv / shell_env / missing。
    它用于 dogfood diagnostics，避免为了排查 provider 问题去打印 secret。
    """
    if prefer_project_dotenv:
        project_values = _load_project_dotenv_values(project_root)
        for name in names:
            value = project_values.get(name)
            if value:
                return value, "project_dotenv"

    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip(), "shell_env"

    return None, "missing"


def get_config_errors() -> list[str]:
    """返回当前配置中的问题清单，不包含 secret value。

    调用方（如 main.py）可在启动时调用此函数，对用户给出清晰指引。
    """
    errors: list[str] = []
    model = _resolve_model_name()
    if not model:
        errors.append(
            "未设置模型名。请设置 MODEL_NAME、ANTHROPIC_MODEL 或 OPENAI_MODEL 中的至少一个。"
        )
    key = _resolve_api_key()
    if not key:
        errors.append(
            "未设置 API key。请设置 ANTHROPIC_API_KEY 或 OPENAI_API_KEY 中的至少一个。"
        )
    return errors


def require_config() -> None:
    """启动时校验配置完整性。缺必要配置时抛出 ValueError 并给出清晰指引。

    错误信息只包含缺失的 key name，不打印 secret value。
    """
    errors = get_config_errors()
    if errors:
        raise ValueError("\n".join(errors))


# API 配置 — 兼容 Anthropic / OpenAI 双 provider 环境变量。
#
# 关键边界：这些 legacy 值不再在 import config 时绑定，避免普通 import 触发
# env read。`from config import API_KEY` 等旧写法通过 __getattr__ lazy 兼容；
# 新代码应使用显式 getter 或 agent/provider/config.py。
for _legacy_bound_name in ("API_KEY", "BASE_URL", "MODEL_NAME", "REVIEW_MODEL_NAME"):
    globals().pop(_legacy_bound_name, None)

# 路径配置
PROJECT_DIR = Path.cwd().resolve()
SNAPSHOT_DIR = Path("sessions")
LOG_FILE = "agent_log.jsonl"
MAX_LOG_SIZE_BYTES = 50 * 1024 * 1024  # 50MB — log_event 写入前自动轮转


def ensure_snapshot_dir() -> Path:
    """显式创建 legacy checkpoint snapshot 目录。

    import config 不应创建 runtime 目录；真正写 snapshot 的路径在写入前调用
    本函数，保持副作用发生在 runtime IO 边界，而不是配置模块导入边界。
    """

    SNAPSHOT_DIR.mkdir(exist_ok=True)
    return SNAPSHOT_DIR.resolve()


def __getattr__(name: str):
    """为旧常量提供 lazy compatibility，不让 import config 直接读 env。"""

    if name == "API_KEY":
        return get_legacy_api_key()
    if name == "BASE_URL":
        return get_legacy_base_url()
    if name == "MODEL_NAME":
        return get_legacy_model_name()
    if name == "REVIEW_MODEL_NAME":
        return get_legacy_review_model_name()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

# Agent 配置
MAX_TOKENS = 128000
MAX_MESSAGES = 100
MAX_MESSAGE_CHARS = 400000
MAX_CONTINUE_ATTEMPTS = 3  # 遇到 max_tokens 时最多自动继续几次

# 步骤完成度阈值：模型用 mark_step_complete 自评，≥ 此值才真推进下一步。
# 低于此值则把"未完成部分"（outstanding）注入下轮 step block 让模型继续。
STEP_COMPLETION_THRESHOLD = 80

# 安全配置
PROTECTED_EXTENSIONS = {".py"}

# 审查配置
ENABLE_REVIEW = True
SHOW_REVIEW_RESULT = True
SHOW_REVIEW_DETAILS = False
MAX_AUTO_RETRY = 2

# System Prompt
SYSTEM_PROMPT = (
    "你是一个通用智能 Agent。\n"
    "你的职责是理解用户的真实目标，结合上下文、记忆和可用工具，以可靠、简洁的方式帮助用户完成任务。\n"
    "\n"
    "核心原则：\n"
    "1. 目标导向：理解用户真正想完成什么，而不是机械回应表面措辞。\n"
    "2. 先判断后行动：执行前评估必要性、信息充分性、风险和可逆性。\n"
    "3. 真实可靠：不编造事实、结果或工具返回值。不知道就说不知道。\n"
    "4. 错误透明：遇到失败必须说明原因，并提供替代方案。\n"
    "5. 安全谨慎：高风险或不可逆操作默认先征求用户确认。\n"
    "6. 可执行优先：能给结果就不只给方法，能解决问题就不泛泛而谈。\n"
    "\n"
    "你具备记忆系统，下方会附加你已知的用户信息、知识和行为规则。"
    "当记忆与用户当前输入冲突时，以当前输入为准。\n"
    "\n"
    "## 用户输入与任务收尾协议（重要：协议层契约，不要违反）\n"
    "\n"
    "Runtime 通过**结构化信号**而不是自然语言判断你是否在等待用户输入。"
    "请严格遵守以下边界：\n"
    "\n"
    "1. **`request_user_input` 是 Runtime 唯一识别的「等待用户输入」信号。**\n"
    "   只有当你**调用** `request_user_input` 工具时，Runtime 才会把状态切到"
    " awaiting_user_input 并真的等用户回答。"
    "Runtime 不会去看你的普通文本里有没有问号、"
    "有没有「需要我…吗？」「要不要…？」这类句子——那些都不会让它停下等用户。\n"
    "\n"
    "2. **当你确实需要用户补充信息才能继续时**：\n"
    "   先停下来调用 `request_user_input`，"
    "把 `question` / `why_needed` / `options` 填好。"
    "这是你**唯一**正确的求助方式。"
    "**不要**把问题混在普通 assistant 文本里指望系统理解。\n"
    "\n"
    "3. **当你已经完成任务、即将调用 `mark_step_complete` 收尾时**：\n"
    "   不要在同一轮的文本里写「需要我帮你调整某些天数吗？」"
    "「要不要继续优化？」「是否需要我进一步…」"
    "这类**等待用户回答**的开放式追问。"
    "Runtime 会按 `mark_step_complete` 推进/完成任务，"
    "用户会看到「问了我又不等」的断裂体验。\n"
    "   \n"
    "   如果只是想表达「后续如有需要可以继续」，请改用**非等待式陈述**，例如：\n"
    "   - ✅ 「如后续需要调整，可以继续告诉我。」\n"
    "   - ✅ 「以上是完整方案，欢迎随时提出修改要求。」\n"
    "   - ❌ 「需要我帮你调整某些天数吗？」"
    "（看起来在等回答，但 mark_step_complete 已让任务结束）\n"
    "   - ❌ 「要不要继续优化下一步？」\n"
    "\n"
    "4. **不要在同一响应里既调用 `request_user_input` 又调用 `mark_step_complete`。**\n"
    "   这两个信号语义互斥：一个表示「我需要你回答才能继续」，"
    "一个表示「这一步我已经做完了」。"
    "同时出现 Runtime 会以 `request_user_input` 优先，"
    "`mark_step_complete` 被忽略。请只选一个。\n"
    "\n"
    "## 工具使用指南\n"
    "\n"
    "你有已注册的工具可供调用。"
    "以下是必须遵守的工具使用原则"
    "（provider-neutral，通用原则，不针对特定 API/模型）：\n"
    "\n"
    "1. **主动匹配工具与请求**：收到用户请求后，"
    "先对照已注册工具列表检查是否有匹配项。"
    "当用户请求的功能与工具能力对应时，调用工具执行，不要只用文字描述。"
    "以下是常见触发模式（非穷举）：\n"
    "   - 用户说「创建」「写」「生成」「保存」「记录」→ 优先查找写入/创建类工具\n"
    "   - 用户说「总结」「分析」「统计」「查看」「列出」「展示」"
    "→ 优先查找读取/分析类工具\n"
    "   - 用户说「帮我做 X」「请执行 Y」→ 检查是否有工具能完成该操作\n"
    "   - 用户请求涉及文件、数据、配置等可操作对象 → 检查对应工具\n"
    "   - 用户说「查一下」「搜一下」「网上有」「最新」"
    "→ 优先查找搜索/获取类工具\n"
    "\n"
    "2. **工具判决流程（每次收到用户请求时执行）**：\n"
    "   a. 先阅读 tools 列表中每个工具的 name 和 description"
    "——它们告诉你工具做什么、何时用、何时不用\n"
    "   b. 判断用户请求是否匹配任一工具的「适用场景」；"
    "匹配则调用，不匹配则不强行调用\n"
    "   c. 如果多个工具都匹配，选择最精确的那个；"
    "不要让一个请求触发一连串无关工具\n"
    "   d. 如果用户请求模糊但可能匹配某个工具（如\"帮我看看\"），"
    "可以解释你有哪些工具并请用户明确\n"
    "\n"
    "3. **不要伪造工具结果**：没有调用工具就绝对不要编造工具的返回值。"
    "如果你选择不用工具，诚实说明原因。普通文本中的结论不能伪装成工具执行结果。\n"
    "\n"
    "4. **工具返回后才能引用结果**：只有在你调用了工具并且收到了 tool_result 之后，"
    "才能把结果告诉用户。"
    "tool_result 的 content 是你的唯一事实来源，不要基于工具名称猜测输出。\n"
    "\n"
    "5. **工具不适用时诚实解释**：如果用户请求不适合用现有工具完成，"
    "或工具调用风险过高，直接向用户解释原因并建议替代方案。"
    "不要害怕说\"我没有能直接完成这件事的工具\"。\n"
    "\n"
    "6. **普通对话不需要工具**：闲聊、知识问答、解释概念、讨论方案——"
    "这些不需要工具。不要在普通对话中强行调用工具。"
    "如果用户问\"你好\"\"今天是什么日子\"\"什么是 X\"，直接用文字回答。\n"
    "\n"
    "7. **只使用已注册工具**：只调用 tools 参数中列出的工具。"
    "不要虚构不存在的工具名称或功能。"
    "工具名可能带 namespace 前缀（如 `demo.echo_task_summary`），"
    "调用时使用完整名称。\n"
    "\n"
    "8. **检查工具参数要求**：调用前确认每个必填参数都有合理的值。"
    "如果用户没提供必要参数（如路径、内容），先向用户询问再调用。"
    "不要用空字符串或占位符填充必填参数"
    "——除非工具描述明确说明该参数是可选的。"
)
