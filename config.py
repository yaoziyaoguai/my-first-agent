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
MAX_TOKENS = 8192
MAX_MESSAGES = 10
MAX_MESSAGE_CHARS = 50000

# 安全配置
PROTECTED_EXTENSIONS = {".py"}
ALLOWED_TOOLS = {"calculate", "read_file", "read_file_lines", "write_file"}

# 审查配置
ENABLE_REVIEW = True
SHOW_REVIEW_RESULT = True
SHOW_REVIEW_DETAILS = False
MAX_AUTO_RETRY = 2

# System Prompt
SYSTEM_PROMPT = """你是一个有用的助手，能够进行数学计算和文件操作。
你可以读取文件来了解信息，也可以创建和编辑文件。
在操作文件时请谨慎，先告诉用户你打算做什么，再执行操作。

重要规则：
- 如果任务涉及创建多个文件，请逐个创建，每次只写一个文件，写完后询问用户是否继续下一个。
- 不要试图在一次回复中完成所有文件的创建。"""
