import os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

# API 配置
API_KEY = os.getenv("ANTHROPIC_API_KEY")
BASE_URL = os.getenv("ANTHROPIC_BASE_URL")
MODEL_NAME = os.getenv("MODEL_NAME")
REVIEW_MODEL_NAME = os.getenv("REVIEW_MODEL_NAME")

# 路径配置
PROJECT_DIR = Path.cwd().resolve()
SNAPSHOT_DIR = Path("sessions")
SNAPSHOT_DIR.mkdir(exist_ok=True)
LOG_FILE = "agent_log.jsonl"

# Agent 配置
MAX_TOKENS = 128000
MAX_MESSAGES = 100
MAX_MESSAGE_CHARS = 400000
MAX_CONTINUE_ATTEMPTS = 3  # 遇到 max_tokens 时最多自动继续几次
# 安全配置
PROTECTED_EXTENSIONS = {".py"}

# 审查配置
ENABLE_REVIEW = True
SHOW_REVIEW_RESULT = True
SHOW_REVIEW_DETAILS = False
MAX_AUTO_RETRY = 2

# System Prompt
SYSTEM_PROMPT = """你是一个通用智能 Agent。
你的职责是理解用户的真实目标，结合上下文、记忆和可用工具，以可靠、简洁的方式帮助用户完成任务。

核心原则：
1. 目标导向：理解用户真正想完成什么，而不是机械回应表面措辞。
2. 先判断后行动：执行前评估必要性、信息充分性、风险和可逆性。
3. 真实可靠：不编造事实、结果或工具返回值。不知道就说不知道。
4. 错误透明：遇到失败必须说明原因，并提供替代方案。
5. 安全谨慎：高风险或不可逆操作默认先征求用户确认。
6. 可执行优先：能给结果就不只给方法，能解决问题就不泛泛而谈。

你具备记忆系统，下方会附加你已知的用户信息、知识和行为规则。当记忆与用户当前输入冲突时，以当前输入为准。"""