import os
import json
import datetime
import uuid
from pathlib import Path
from dotenv import load_dotenv
import anthropic

load_dotenv()

client = anthropic.Anthropic(
    api_key=os.getenv("ANTHROPIC_API_KEY"),
    base_url=os.getenv("ANTHROPIC_BASE_URL"),
)

SESSION_ID = str(uuid.uuid4())
LOG_FILE = "agent_log.jsonl"
SNAPSHOT_DIR = Path("sessions")
SNAPSHOT_DIR.mkdir(exist_ok=True)

# ============================================
# 项目目录：Agent 在这个目录下读文件不需要确认
# ============================================
PROJECT_DIR = Path.cwd()

def log_event(event_type, data):
    entry = {
        "timestamp": datetime.datetime.now().isoformat(),
        "session_id": SESSION_ID,
        "event": event_type,
        "data": data,
    }
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

# ============================================
# 权限分级系统（Guide - 计算型）
#
# 你设计的规则：
# - 写操作 → 全部确认
# - 读操作 + 项目外路径 → 确认
# - 读操作 + 项目内路径 → 静默执行
# ============================================

def needs_confirmation(tool_name, tool_input):
    """根据操作类型和路径判断是否需要人类确认"""
    
    if tool_name == "write_file":
        # 写操作：全部需要确认
        return True
    
    if tool_name == "read_file":
        # 读操作：检查路径是否在项目目录内
        file_path = Path(tool_input["path"]).resolve()
        if file_path.is_relative_to(PROJECT_DIR):
            return False  # 项目内，静默执行
        else:
            return True   # 项目外，需要确认
    
    if tool_name == "calculate":
        return False  # 计算器不需要确认
    
    # 未知工具：默认需要确认
    return True

def confirm_tool_call(tool_name, tool_input):
    print(f"\n{'='*50}")
    print(f"⚠️  Agent 想要执行以下操作：")
    print(f"   工具: {tool_name}")
    print(f"   参数: {json.dumps(tool_input, ensure_ascii=False)}")
    print(f"{'='*50}")
    while True:
        choice = input("允许执行吗？(y/n): ").strip().lower()
        if choice in ("y", "n"):
            return choice == "y"
        print("请输入 y 或 n")

# ============================================
# 工具实现
# ============================================

ALLOWED_TOOLS = {"calculate", "read_file", "write_file"}

def calculate(expression):
    try:
        allowed = set("0123456789+-*/.() ")
        if not all(c in allowed for c in expression):
            return "错误：表达式包含不允许的字符"
        result = eval(expression)
        return str(result)
    except Exception as e:
        return f"计算错误：{e}"

def read_file(path):
    try:
        file_path = Path(path)
        if not file_path.exists():
            return f"错误：文件 '{path}' 不存在"
        content = file_path.read_text(encoding="utf-8")
        # 防止读入过大的文件撑爆上下文
        if len(content) > 10000:
            content = content[:10000] + f"\n\n... [文件过大，只显示前 10000 字符，总共 {len(content)} 字符]"
        return content
    except Exception as e:
        return f"读取错误：{e}"

def write_file(path, content):
    try:
        file_path = Path(path)
        
        # 如果文件已存在，先备份（你提出的 Sensor 思路）
        backup_path = None
        if file_path.exists():
            backup_path = file_path.with_suffix(file_path.suffix + ".bak")
            backup_path.write_text(file_path.read_text(encoding="utf-8"), encoding="utf-8")
        
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        
        msg = f"成功写入 '{path}'"
        if backup_path:
            msg += f"（原文件已备份到 '{backup_path}'）"
        return msg
    except Exception as e:
        return f"写入错误：{e}"

def execute_tool(tool_name, tool_input):
    if tool_name not in ALLOWED_TOOLS:
        error_msg = f"工具 '{tool_name}' 不在允许列表中"
        log_event("tool_blocked", {"tool": tool_name})
        return error_msg
    
    if tool_name == "calculate":
        return calculate(tool_input["expression"])
    elif tool_name == "read_file":
        return read_file(tool_input["path"])
    elif tool_name == "write_file":
        return write_file(tool_input["path"], tool_input["content"])

# ============================================
# 工具描述
# ============================================

tools = [
    {
        "name": "calculate",
        "description": "计算一个数学表达式。",
        "input_schema": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "数学表达式，例如 '2 + 3 * 4'"
                }
            },
            "required": ["expression"]
        }
    },
    {
        "name": "read_file",
        "description": "读取一个文件的内容。用于查看文件内容、检查配置等。",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "文件路径，可以是相对路径或绝对路径"
                }
            },
            "required": ["path"]
        }
    },
    {
        "name": "write_file",
        "description": "将内容写入文件。如果文件已存在会被覆盖（会自动备份原文件）。如果目录不存在会自动创建。",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "要写入的文件路径"
                },
                "content": {
                    "type": "string",
                    "description": "要写入的文件内容"
                }
            },
            "required": ["path", "content"]
        }
    }
]

SYSTEM_PROMPT = """你是一个有用的助手，能够进行数学计算和文件操作。
你可以读取文件来了解信息，也可以创建和编辑文件。
在操作文件时请谨慎，先告诉用户你打算做什么，再执行操作。"""

# ============================================
# Agent Loop
# ============================================

messages = []

def chat(user_input):
    messages.append({"role": "user", "content": user_input})
    log_event("user_input", {"content": user_input})
    
    while True:
        log_event("llm_call", {"message_count": len(messages)})
        
        with client.messages.stream(
            model=os.getenv("MODEL_NAME"),
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=messages,
            tools=tools,
        ) as stream:
        # 实时打印文字
            for event in stream:
                if hasattr(event, 'type') and event.type == 'content_block_start':
                    if hasattr(event.content_block, 'type') and event.content_block.type == 'tool_use':
                        print(f"\n🔧 正在规划工具调用...", flush=True)
                if hasattr(event, 'type') and event.type == 'content_block_delta':
                    if hasattr(event.delta, 'text'):
                        print(event.delta.text, end="", flush=True)
            # 流结束后拿到完整 response
            response = stream.get_final_message()
            print()  # 换行
        
        log_event("llm_response", {"stop_reason": response.stop_reason})
        
        if response.stop_reason == "end_turn":
            assistant_text = ""
            for block in response.content:
                if block.type == "text":
                    assistant_text = block.text
            messages.append({"role": "assistant", "content": response.content})
            log_event("agent_reply", {"content": assistant_text})
            return assistant_text
        
        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})
            
            for block in response.content:
                if block.type == "tool_use":
                    tool_name = block.name
                    tool_input = block.input
                    tool_use_id = block.id
                    
                    log_event("tool_requested", {"tool": tool_name, "input": tool_input})
                    
                    # 分级控制：根据你设计的规则决定是否需要确认
                    if needs_confirmation(tool_name, tool_input):
                        approved = confirm_tool_call(tool_name, tool_input)
                    else:
                        print(f"  [自动执行] {tool_name}({json.dumps(tool_input, ensure_ascii=False)})")
                        approved = True
                    
                    if approved:
                        result = execute_tool(tool_name, tool_input)
                        log_event("tool_executed", {"tool": tool_name, "result": result})
                    else:
                        result = "用户拒绝了此操作"
                        log_event("tool_rejected", {"tool": tool_name})
                    
                    messages.append({
                        "role": "user",
                        "content": [{"type": "tool_result", "tool_use_id": tool_use_id, "content": result}],
                    })
            continue
        
        return "意外的响应"


def make_serializable(messages):
    result = []
    for msg in messages:
        if isinstance(msg.get("content"), list):
            new_content = []
            for block in msg["content"]:
                if hasattr(block, "model_dump"):
                    new_content.append(block.model_dump())
                else:
                    new_content.append(block)
            result.append({"role": msg["role"], "content": new_content})
        else:
            result.append(msg)
    return result

def save_session_snapshot(messages):
    snapshot = {
        "session_id": SESSION_ID,
        "saved_at": datetime.datetime.now().isoformat(),
        "message_count": len(messages),
        "messages": make_serializable(messages),
    }
    snapshot_file = SNAPSHOT_DIR / f"session_{SESSION_ID}.json"
    with open(snapshot_file, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)

# ============================================
# 主循环
# ============================================

log_event("session_start", {"system_prompt": SYSTEM_PROMPT})

print("=== My First Agent (with Files) ===")
print("我可以计算数学题、读写文件。输入 'quit' 退出\n")

while True:
    user_input = input("你: ")
    if user_input.strip().lower() == "quit":
        save_session_snapshot(messages)
        print("会话已保存，再见！")
        break
    reply = chat(user_input)
    print(f"\nAgent: {reply}\n")
