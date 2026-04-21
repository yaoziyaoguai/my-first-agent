import os
import json
import datetime
import uuid
from pathlib import Path
from dotenv import load_dotenv
import anthropic

load_dotenv()
SNAPSHOT_DIR = Path("session_snapshots")
SNAPSHOT_DIR.mkdir(exist_ok=True)
client = anthropic.Anthropic(
    api_key=os.getenv("ANTHROPIC_API_KEY"),
    base_url=os.getenv("ANTHROPIC_BASE_URL"),
)

# ============================================
# Harness 机制 #1：日志系统（Sensor - 计算型）
# 
# 记录 Agent 每一步的决策，事后可以审查
# 这是最基础的反馈控制——你无法改进你看不见的东西
# ============================================

LOG_FILE = "agent_log.jsonl"

def log_event(event_type, data):
    """把每一个事件写入日志文件"""
    entry = {
        "timestamp": datetime.datetime.now().isoformat(),
        "event": event_type,
        "data": data,
    }
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    

# ============================================
# Harness 机制 #2：工具执行确认（Guide - 计算型）
# 
# Agent 想调用工具时，先让人类确认
# 这是一个前馈控制——在行动发生之前拦截
# ============================================

def confirm_tool_call(tool_name, tool_input):
    """在工具执行前请求人类确认"""
    print(f"\n{'='*50}")
    print("⚠️  Agent 想要执行以下操作：")
    print(f"   工具: {tool_name}")
    print(f"   参数: {json.dumps(tool_input, ensure_ascii=False)}")
    print(f"{'='*50}")
    
    while True:
        choice = input("允许执行吗？(y/n): ").strip().lower()
        if choice in ("y", "n"):
            return choice == "y"
        print("请输入 y 或 n")


# ============================================
# Harness 机制 #3：工具白名单（Guide - 计算型）
# 
# 只有在白名单里的工具才允许执行
# 即使模型幻觉出一个不存在的工具名，也会被拦截
# ============================================

ALLOWED_TOOLS = {"calculate"}

def execute_tool(tool_name, tool_input):
    """安全地执行工具，包含白名单检查"""
    
    # 白名单检查
    if tool_name not in ALLOWED_TOOLS:
        error_msg = f"工具 '{tool_name}' 不在允许列表中，拒绝执行"
        log_event("tool_blocked", {"tool": tool_name, "reason": "not_in_whitelist"})
        print(f"🚫 {error_msg}")
        return error_msg
    
    # 执行具体工具
    if tool_name == "calculate":
        return calculate(tool_input["expression"])
    

def calculate(expression):
    try:
        allowed = set("0123456789+-*/.() ")
        if not all(c in allowed for c in expression):
            return "错误：表达式包含不允许的字符"
        result = eval(expression)
        return str(result)
    except Exception as e:
        return f"计算错误：{e}"


# ============================================
# 工具定义（跟之前一样）
# ============================================

tools = [
    {
        "name": "calculate",
        "description": "计算一个数学表达式。当用户需要进行数学计算时使用此工具。",
        "input_schema": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "要计算的数学表达式，例如 '2 + 3 * 4'"
                }
            },
            "required": ["expression"]
        }
    }
]

SYSTEM_PROMPT = "你是一个数学辅导老师。你的风格是耐心、鼓励性的。当用户问数学题时，你不要直接给答案，而是先引导他们思考解题思路，然后再用计算器验证结果。"

# ============================================
# Agent Loop（加入了 Harness 机制）
# ============================================

messages = []

def chat(user_input):
    messages.append({"role": "user", "content": user_input})
    log_event("user_input", {"content": user_input})
    
    while True:
        log_event("llm_call", {"message_count": len(messages)})
        
        response = client.messages.create(
            model=os.getenv("MODEL_NAME"),
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=messages,
            tools=tools,
        )
        
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
                    
                    log_event("tool_requested", {
                        "tool": tool_name,
                        "input": tool_input,
                    })
                    
                    # Harness #2：人类确认
                    if confirm_tool_call(tool_name, tool_input):
                        # Harness #3：白名单检查 + 执行
                        result = execute_tool(tool_name, tool_input)
                        log_event("tool_executed", {
                            "tool": tool_name,
                            "result": result,
                        })
                    else:
                        result = "用户拒绝了此操作的执行"
                        log_event("tool_rejected", {
                            "tool": tool_name,
                            "reason": "user_denied",
                        })
                    
                    messages.append({
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_use_id,
                                "content": result,
                            }
                        ],
                    })
            
            continue
        
        return "意外的响应"
def make_serializable(messages):
    """把 messages 里的 SDK 对象转成普通字典"""
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
    """把完整 messages 存成 session 快照文件"""
    snapshot = {
        "session_id": SESSION_ID,
        "saved_at": datetime.datetime.now().isoformat(),
        "message_count": len(messages),
        "messages": make_serializable(messages),
    }
    snapshot_file = SNAPSHOT_DIR / f"session_{SESSION_ID}.json"
    with open(snapshot_file, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)

    return snapshot_file


SESSION_ID = str(uuid.uuid4())
log_event("system_prompt", {"content": SYSTEM_PROMPT})

print("=== My First Agent (with Harness) ===")
print("输入 'quit' 退出\n")
while True:
    user_input = input("你: ")
    if user_input.strip().lower() == "quit":
        save_session_snapshot(messages)
        print("再见！")
        break
    reply = chat(user_input)
    print(f"\nAgent: {reply}\n")
