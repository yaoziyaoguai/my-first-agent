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
PROJECT_DIR = Path.cwd().resolve()

# ============================================
# 源码保护：项目目录下的 .py 文件禁止写入
# ============================================
PROTECTED_EXTENSIONS = {".py"}

def is_protected_source_file(path):
    try:
        file_path = Path(path).expanduser().resolve(strict=False)
        return (
            file_path.is_relative_to(PROJECT_DIR)
            and file_path.suffix.lower() in PROTECTED_EXTENSIONS
            and file_path.exists()  # ← 只保护已存在的文件
        )
    except Exception:
        return False


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

    if tool_name == "read_file_lines":
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
# Context Engineering：上下文压缩
#
# 当消息历史超过阈值时，把旧消息总结成一段摘要
# 这就是在管理"模型桌上放什么文件"
# ============================================

MAX_MESSAGES = 10  # 超过这个数量就触发压缩

MAX_MESSAGE_CHARS = 50000


def estimate_messages_size(msgs):
    """
    估算 messages 的总大小（字符数）
    """
    try:
        serializable = make_serializable(msgs)
        return len(json.dumps(serializable, ensure_ascii=False))
    except Exception as e:
        print(f"[系统] 估算 messages 大小时出错: {e}")
        return 0


def _truncate_tool_result_content(obj, threshold=200, keep_prefix=200):
    """
    递归遍历消息内容：
    - 如果发现 type == "tool_result" 的 block
    - 且其 content 长度超过 threshold
    - 就截断为前 keep_prefix 个字符 + ...(已截断)
    """
    if isinstance(obj, list):
        return [_truncate_tool_result_content(item, threshold, keep_prefix) for item in obj]

    if isinstance(obj, dict):
        new_obj = {}
        is_tool_result = obj.get("type") == "tool_result"

        for k, v in obj.items():
            if is_tool_result and k == "content":
                if isinstance(v, str):
                    content_text = v
                else:
                    content_text = json.dumps(v, ensure_ascii=False)

                if len(content_text) > threshold:
                    content_text = content_text[:keep_prefix] + "...(已截断)"

                new_obj[k] = content_text
            else:
                new_obj[k] = _truncate_tool_result_content(v, threshold, keep_prefix)

        return new_obj

    return obj


def compress_history():
    """把较早的消息压缩成摘要"""
    global messages

    total_size = estimate_messages_size(messages)

    # 第二个触发条件：条数超过 MAX_MESSAGES 或 总字符数超过 MAX_MESSAGE_CHARS
    if len(messages) <= MAX_MESSAGES and total_size <= MAX_MESSAGE_CHARS:
        return

    print(
        f"\n[系统] 上下文较长，正在压缩历史记录..."
        f"（message_count={len(messages)}, total_chars={total_size}）"
    )
    log_event("context_compression_start", {
        "message_count": len(messages),
        "total_chars": total_size,
    })

    # 保留最近的 6 条消息（3 轮对话）
    recent = messages[-6:]
    old = messages[:-6]

    # 先转成可序列化结构，再对 tool_result 做截断
    old_for_summary = make_serializable(old)
    old_for_summary = _truncate_tool_result_content(
        old_for_summary,
        threshold=200,
        keep_prefix=200
    )

    # 用模型来总结旧的消息
    summary_response = client.messages.create(
        model=os.getenv("MODEL_NAME"),
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": (
                    "请用中文简要总结以下对话历史的关键信息，包括："
                    "完成了什么任务、重要的结论、用户的偏好。"
                    "只输出总结，不要多余的话。\n\n"
                    f"对话历史：\n{json.dumps(old_for_summary, ensure_ascii=False)}"
                )
            }
        ],
    )

    summary_text = ""
    for block in summary_response.content:
        if block.type == "text":
            summary_text = block.text
            break

    # 用摘要替换旧消息
    messages = [
        {"role": "user", "content": f"[以下是之前对话的摘要]\n{summary_text}"},
        {"role": "assistant", "content": "好的，我了解了之前的对话内容。请继续。"},
    ] + recent

    new_total_size = estimate_messages_size(messages)

    log_event("context_compression_done", {
        "old_count": len(old) + len(recent),
        "new_count": len(messages),
        "summary": summary_text,
        "old_total_chars": total_size,
        "new_total_chars": new_total_size,
    })

    print(
        f"[系统] 压缩完成：{len(old) + len(recent)} 条 → {len(messages)} 条，"
        f"{total_size} 字符 → {new_total_size} 字符\n"
    )
# ============================================
# 工具实现
# ============================================

ALLOWED_TOOLS = {"calculate", "read_file", "read_file_lines", "write_file"}

def calculate(expression):
    try:
        allowed = set("0123456789+-*/.() ")
        if not all(c in allowed for c in expression):
            return "错误：表达式包含不允许的字符"
        result = eval(expression)
        return str(result)
    except Exception as e:
        return f"计算错误：{e}"

def extract_python_outline(content):
    """提取 Python 文件中的类名和函数名（简单字符串匹配版）"""
    outline = []
    lines = content.splitlines()

    for idx, line in enumerate(lines, start=1):
        stripped = line.lstrip()

        if stripped.startswith("class "):
            name = stripped[len("class "):].split("(", 1)[0].split(":", 1)[0].strip()
            outline.append(f"Line {idx}: class {name}")
        elif stripped.startswith("def "):
            name = stripped[len("def "):].split("(", 1)[0].strip()
            outline.append(f"Line {idx}: def {name}")

    return outline

def read_file(path):
    try:
        file_path = Path(path)
        if not file_path.exists():
            return f"错误：文件 '{path}' 不存在"

        content = file_path.read_text(encoding="utf-8")
        total_lines = len(content.splitlines())

        # 小文件：直接返回全部内容
        if len(content) <= 10000:
            return content

        # 大文件：返回概览，而不是硬截断到 10000 字符
        preview = content[:3000]
        suffix = file_path.suffix.lower()

        if suffix == ".py":
            outline = extract_python_outline(content)
            if outline:
                outline_text = "\n".join(outline[:200])  # 防止目录本身过长
            else:
                outline_text = "(未识别到 class / def 定义)"
        else:
            outline_text = "(该文件不是 Python 文件，不提供函数/类目录)"

        return (
            f"[文件概览]\n"
            f"路径: {path}\n"
            f"总字符数: {len(content)}\n"
            f"总行数: {total_lines}\n\n"
            f"[开头预览（前 3000 字符）]\n"
            f"{preview}\n\n"
            f"[文件结构目录]\n"
            f"{outline_text}\n\n"
            f"[提示]\n"
            f"这个文件较大。请使用 read_file_lines 按行读取你感兴趣的范围。"
        )
    except Exception as e:
        return f"读取错误：{e}"

def read_file_lines(path, start_line, end_line):
    try:
        file_path = Path(path)
        if not file_path.exists():
            return f"错误：文件 '{path}' 不存在"

        if start_line < 1 or end_line < 1:
            return "错误：start_line 和 end_line 必须 >= 1"

        if start_line > end_line:
            return "错误：start_line 不能大于 end_line"

        lines = file_path.read_text(encoding="utf-8").splitlines()
        total_lines = len(lines)

        if start_line > total_lines:
            return f"错误：start_line={start_line} 超出文件总行数 {total_lines}"

        actual_end = min(end_line, total_lines)
        selected = lines[start_line - 1:actual_end]

        numbered_content = "\n".join(
            f"{idx}: {line}" for idx, line in enumerate(selected, start=start_line)
        )

        return (
            f"[按行读取]\n"
            f"路径: {path}\n"
            f"范围: 第 {start_line} 行 - 第 {actual_end} 行\n"
            f"总行数: {total_lines}\n\n"
            f"{numbered_content}"
        )
    except Exception as e:
        return f"读取错误：{e}"

def write_file(path, content):
    try:
        # 保护项目目录下的 .py 文件
        if is_protected_source_file(path):
            return f"拒绝写入：'{path}' 属于受保护源码文件（.py），不允许 Agent 修改"

        file_path = Path(path)

        # 如果文件已存在，先备份
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

    # 前置策略拦截：保护源码文件
    if tool_name == "write_file" and is_protected_source_file(tool_input["path"]):
        error_msg = f"工具 '{tool_name}' 被阻止：'{tool_input['path']}' 属于受保护源码文件（.py）"
        log_event("tool_blocked_protected_source", {
            "tool": tool_name,
            "path": tool_input["path"],
        })
        return error_msg

    if tool_name == "calculate":
        return calculate(tool_input["expression"])
    elif tool_name == "read_file":
        return read_file(tool_input["path"])
    elif tool_name == "read_file_lines":
        return read_file_lines(
            tool_input["path"],
            tool_input["start_line"],
            tool_input["end_line"],
        )
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
        "description": "读取一个文件的内容。如果文件较大，会返回文件概览：前 3000 字符、总行数，以及 Python 文件中的函数/类目录。",
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
        "name": "read_file_lines",
        "description": "按指定行号范围读取文件内容。适合在 read_file 查看概览后，进一步查看某一段代码或文本。",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "文件路径，可以是相对路径或绝对路径"
                },
                "start_line": {
                    "type": "integer",
                    "description": "起始行号（从 1 开始）"
                },
                "end_line": {
                    "type": "integer",
                    "description": "结束行号（从 1 开始，且必须 >= start_line）"
                }
            },
            "required": ["path", "start_line", "end_line"]
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
在操作文件时请谨慎，先告诉用户你打算做什么，再执行操作。

重要规则：
- 如果任务涉及创建多个文件，请逐个创建，每次只写一个文件，写完后询问用户是否继续下一个。
- 不要试图在一次回复中完成所有文件的创建。"""

# ============================================
# Agent Loop
# ============================================

messages = []

def chat(user_input):
    compress_history()
    messages.append({"role": "user", "content": user_input})
    log_event("user_input", {"content": user_input})

    while True:
        log_event("llm_call", {"message_count": len(messages)})

        with client.messages.stream(
            model=os.getenv("MODEL_NAME"),
            max_tokens=8192,
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

                    # 受保护源码文件直接拒绝，不进入确认流程
                    if tool_name == "write_file" and is_protected_source_file(tool_input["path"]):
                        result = f"拒绝执行：'{tool_input['path']}' 属于受保护源码文件（.py），不允许 Agent 修改"
                        log_event("tool_blocked_protected_source", {
                            "tool": tool_name,
                            "path": tool_input["path"],
                        })
                        messages.append({
                            "role": "user",
                            "content": [{"type": "tool_result", "tool_use_id": tool_use_id, "content": result}],
                        })
                        continue

                    # 分级控制：根据你设计的规则决定是否需要确认
                    if needs_confirmation(tool_name, tool_input):
                        approved = confirm_tool_call(tool_name, tool_input)
                    else:
                        print(f"  [自动执行] {tool_name}({json.dumps(tool_input, ensure_ascii=False)})")
                        approved = True

                    if approved:
                        result = execute_tool(tool_name, tool_input)
                        log_event("tool_executed", {"tool": tool_name, "result": result})
                        
                        # 写文件成功后，强制要求模型停下来等用户确认
                        if tool_name == "write_file" and not result.startswith("拒绝"):
                            result += "\n\n[系统指令] 文件已写入。请停止当前操作，将结果报告给用户，并询问用户是否继续下一步。不要自行继续创建更多文件。"
                    else:
                        result = "用户拒绝了此操作"
                        log_event("tool_rejected", {"tool": tool_name})

                    messages.append({
                        "role": "user",
                        "content": [{"type": "tool_result", "tool_use_id": tool_use_id, "content": result}],
                    })
            continue

        print(f"[DEBUG] 未知的 stop_reason: {response.stop_reason}")
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

print(f"[DEBUG] 当前消息历史: {len(messages)} 条")