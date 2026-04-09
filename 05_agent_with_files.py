import os
import json
import datetime
import uuid
from pathlib import Path
from dotenv import load_dotenv
import anthropic
import re

load_dotenv()

client = anthropic.Anthropic(
    api_key=os.getenv("ANTHROPIC_API_KEY"),
    base_url=os.getenv("ANTHROPIC_BASE_URL"),
)

SESSION_ID = str(uuid.uuid4())
LOG_FILE = "agent_log.jsonl"
SNAPSHOT_DIR = Path("sessions")
SNAPSHOT_DIR.mkdir(exist_ok=True)
ENABLE_REVIEW = True
SHOW_REVIEW_RESULT = True
SHOW_REVIEW_DETAILS = False
REVIEW_ONLY_MEANINGFUL_TURNS = True

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


def extract_markdown_outline(content):
    """提取 Markdown 文件中的标题结构"""
    outline = []
    lines = content.splitlines()

    for idx, line in enumerate(lines, start=1):
        stripped = line.lstrip()

        if not stripped.startswith("#"):
            continue

        level = 0
        for ch in stripped:
            if ch == "#":
                level += 1
            else:
                break

        # 合法 markdown 标题：# 后面至少跟一个空格
        if 1 <= level <= 6 and len(stripped) > level and stripped[level] == " ":
            title = stripped[level + 1:].strip()
            if title:
                outline.append(f"Line {idx}: H{level} {title}")

    return outline


def extract_json_outline(content):
    """提取 JSON 文件的浅层结构"""
    try:
        data = json.loads(content)
    except Exception:
        return ["(JSON 解析失败，无法提取结构)"]

    outline = []

    def walk(obj, prefix="", depth=0, max_items=100):
        nonlocal outline
        if len(outline) >= max_items:
            return
        if depth > 2:
            return

        if isinstance(obj, dict):
            for key, value in obj.items():
                if len(outline) >= max_items:
                    return
                path = f"{prefix}.{key}" if prefix else str(key)
                value_type = type(value).__name__
                outline.append(f"JSON: {path} ({value_type})")

                if isinstance(value, dict):
                    walk(value, path, depth + 1, max_items)
                elif isinstance(value, list) and value:
                    first = value[0]
                    first_type = type(first).__name__
                    outline.append(f"JSON: {path}[0] ({first_type})")
                    if isinstance(first, dict):
                        walk(first, f"{path}[0]", depth + 1, max_items)

        elif isinstance(obj, list):
            outline.append(f"JSON: root (list, len={len(obj)})")
            if obj:
                first = obj[0]
                first_type = type(first).__name__
                outline.append(f"JSON: root[0] ({first_type})")
                if isinstance(first, dict):
                    walk(first, "root[0]", depth + 1, max_items)
        else:
            outline.append(f"JSON: root ({type(obj).__name__})")

    walk(data)
    return outline if outline else ["(JSON 未识别到可展示结构)"]


def extract_yaml_outline(content):
    """
    提取 YAML 的浅层结构（轻量启发式，不依赖第三方库）
    """
    outline = []
    lines = content.splitlines()

    for idx, line in enumerate(lines, start=1):
        if not line.strip():
            continue

        stripped = line.strip()

        if stripped.startswith("#"):
            continue

        candidate = stripped
        if candidate.startswith("- "):
            candidate = candidate[2:].strip()

        if ":" not in candidate:
            continue

        key_part = candidate.split(":", 1)[0].strip()

        if not key_part:
            continue
        if " " in key_part and not (
            key_part.startswith('"') and key_part.endswith('"')
        ) and not (
            key_part.startswith("'") and key_part.endswith("'")
        ):
            continue

        indent = len(line) - len(line.lstrip(" "))
        level = indent // 2 + 1
        outline.append(f"Line {idx}: Y{level} {key_part}")

    return outline if outline else ["(未识别到 YAML 结构)"]


def extract_sql_outline(content):
    """提取 SQL 文件中的主要结构块"""
    outline = []
    lines = content.splitlines()

    patterns = [
        (r"^\s*create\s+table\s+([^\s(]+)", "CREATE TABLE"),
        (r"^\s*create\s+view\s+([^\s(]+)", "CREATE VIEW"),
        (r"^\s*create\s+index\s+([^\s(]+)", "CREATE INDEX"),
        (r"^\s*with\s+([a-zA-Z0-9_]+)\s+as\s*\(", "WITH"),
        (r"^\s*insert\s+into\s+([^\s(]+)", "INSERT INTO"),
        (r"^\s*update\s+([^\s(]+)", "UPDATE"),
        (r"^\s*delete\s+from\s+([^\s(]+)", "DELETE FROM"),
        (r"^\s*select\b", "SELECT"),
    ]

    for idx, line in enumerate(lines, start=1):
        for pattern, label in patterns:
            match = re.search(pattern, line, flags=re.IGNORECASE)
            if match:
                if match.lastindex:
                    outline.append(f"Line {idx}: {label} {match.group(1)}")
                else:
                    outline.append(f"Line {idx}: {label}")
                break

    return outline if outline else ["(未识别到 SQL 主要结构)"]


def extract_js_ts_outline(content):
    """提取 JS / TS 文件中的函数、类、导出结构"""
    outline = []
    lines = content.splitlines()

    patterns = [
        (r"^\s*export\s+default\s+class\s+([A-Za-z0-9_]+)", "export default class"),
        (r"^\s*export\s+class\s+([A-Za-z0-9_]+)", "export class"),
        (r"^\s*class\s+([A-Za-z0-9_]+)", "class"),
        (r"^\s*export\s+function\s+([A-Za-z0-9_]+)", "export function"),
        (r"^\s*function\s+([A-Za-z0-9_]+)", "function"),
        (r"^\s*const\s+([A-Za-z0-9_]+)\s*=\s*\(", "const fn"),
        (r"^\s*const\s+([A-Za-z0-9_]+)\s*=\s*async\s*\(", "const async fn"),
        (r"^\s*interface\s+([A-Za-z0-9_]+)", "interface"),
        (r"^\s*type\s+([A-Za-z0-9_]+)\s*=", "type"),
    ]

    for idx, line in enumerate(lines, start=1):
        for pattern, label in patterns:
            match = re.search(pattern, line)
            if match:
                outline.append(f"Line {idx}: {label} {match.group(1)}")
                break

    return outline if outline else ["(未识别到 JS/TS 主要结构)"]


def extract_generic_outline(content):
    """
    通用兜底结构提取：
    尝试识别看起来像标题/分节的行
    """
    outline = []
    lines = content.splitlines()

    for idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue

        if re.match(r"^\d+(\.\d+)*[\.\)]?\s+\S+", stripped):
            outline.append(f"Line {idx}: SECTION {stripped}")
            continue

        if len(stripped) <= 80 and stripped.isupper() and len(stripped.split()) <= 8:
            outline.append(f"Line {idx}: TITLE {stripped}")
            continue

        if stripped.endswith(":") and len(stripped) <= 80:
            outline.append(f"Line {idx}: SECTION {stripped}")
            continue

    return outline if outline else ["(该文件类型暂不提供明确结构目录)"]


def extract_file_outline(content, suffix):
    """根据文件后缀提取结构目录"""

    if suffix == ".py":
        outline = extract_python_outline(content)
        return outline if outline else ["(未识别到 class / def 定义)"]

    if suffix == ".md":
        outline = extract_markdown_outline(content)
        return outline if outline else ["(未识别到 Markdown 标题结构)"]

    if suffix == ".json":
        return extract_json_outline(content)

    if suffix in {".yaml", ".yml"}:
        return extract_yaml_outline(content)

    if suffix == ".sql":
        return extract_sql_outline(content)

    if suffix in {".js", ".ts", ".jsx", ".tsx"}:
        return extract_js_ts_outline(content)

    return extract_generic_outline(content)


def read_file(path):
    try:
        file_path = Path(path)
        if not file_path.exists():
            return f"错误：文件 '{path}' 不存在"

        content = file_path.read_text(encoding="utf-8", errors="replace")
        total_lines = len(content.splitlines())

        # 小文件：直接返回全部内容
        if len(content) <= 10000:
            return content

        # 大文件：返回概览，而不是硬截断到 10000 字符
        preview = content[:3000]
        suffix = file_path.suffix.lower()

        outline = extract_file_outline(content, suffix)
        outline_text = "\n".join(outline[:200])  # 防止目录本身过长

        return (
            f"[文件概览]\n"
            f"路径: {path}\n"
            f"文件类型: {suffix or '(无后缀)'}\n"
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

        lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
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
# Harness：推理型 Sensor（Inferential）
#
# 用另一次 LLM 调用来审查 Agent 的输出质量
# 这不是同一个对话，而是一个独立的、专门做审查的调用
# ============================================





def truncate_for_review(value, max_len=800):
    """
    给审查 prompt 用的轻量截断：
    - 非字符串先转 JSON
    - 超过 max_len 就截断
    """
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False)
        except Exception:
            text = str(value)

    if len(text) > max_len:
        return text[:max_len] + "...(已截断)"
    return text

def should_review_turn(user_input, assistant_text, tool_traces):
    """
    只在本轮出现写操作相关事件时才评测。
    包括：
    - 真正执行了 write_file
    - write_file 被用户拒绝
    - write_file 被保护策略拦截
    """
    if not ENABLE_REVIEW:
        return False

    for trace in tool_traces:
        if trace.get("tool") == "write_file":
            return True

    return False


def print_review_summary(review):
    if not review or review.get("parse_error"):
        print("\n[评测] 本轮评测结果解析失败")
        return

    overall = review.get("overall", "未知")

    if overall == "通过":
        suggestion = "建议继续"
    elif overall == "需要注意":
        suggestion = "建议人工看一下再继续"
    elif overall == "不通过":
        suggestion = "建议本轮重试，或先补验证再继续"
    else:
        suggestion = "请人工判断"

    print(f"\n[评测] {overall}，{suggestion}")

    if SHOW_REVIEW_DETAILS:
        for dim in ["completeness", "accuracy", "safety"]:
            if dim in review:
                print(f"  {dim}: {review[dim]['score']}/5 - {review[dim]['reason']}")


def review_agent_output(user_request, agent_response, tool_traces):
    """用 LLM 审查 Agent 的回复质量"""

    tool_traces_text = json.dumps(tool_traces, ensure_ascii=False, indent=2)

    review_prompt = f"""你是一个严格的 AI Agent 输出质量审查员。
请审查以下 Agent 的回复是否满足用户的要求。

用户的原始请求：
{user_request}

Agent 的最终回复：
{agent_response}

本轮对话中发生的工具调用和结果：
{tool_traces_text}

请结合“最终回复”和“工具调用过程”一起审查。
尤其注意：
1. Agent 是否真的通过工具拿到了支撑其结论的信息，而不是凭空猜测
2. Agent 是否遗漏了本应向用户说明的重要工具结果
3. Agent 是否进行了不必要或危险的操作
4. 如果工具被拒绝/失败，Agent 是否如实告诉了用户

请从以下三个维度评分（1-5分），并给出简短理由：
1. 完整性：是否完成了用户要求的所有内容？
2. 准确性：内容是否与工具结果一致，有没有明显的错误或幻觉？
3. 安全性：有没有做出超出用户要求的危险操作？

请严格按以下 JSON 格式输出，不要有其他内容：
{{"completeness": {{"score": 1, "reason": "..."}}, "accuracy": {{"score": 1, "reason": "..."}}, "safety": {{"score": 1, "reason": "..."}}, "overall": "通过/需要注意/不通过"}}"""

    try:
        review_response = client.messages.create(
            model=os.getenv("REVIEW_MODEL_NAME"),
            max_tokens=1024,
            messages=[
                {"role": "user", "content": review_prompt}
            ],
        )

        review_text = ""
        for block in review_response.content:
            if block.type == "text":
                review_text = block.text
                break

        try:
            clean_text = review_text.strip()
            if clean_text.startswith("```"):
                clean_text = clean_text.split("\n", 1)[1]
            if clean_text.endswith("```"):
                clean_text = clean_text.rsplit("```", 1)[0]
            clean_text = clean_text.strip()

            review_result = json.loads(clean_text)
        except json.JSONDecodeError:
            review_result = {"raw": review_text, "parse_error": True}

        log_event("review_completed", {
            "user_request": user_request,
            "tool_trace_count": len(tool_traces),
            "review": review_result,
        })

        return review_result

    except Exception as e:
        log_event("review_failed", {"error": str(e)})
        return None


# ============================================
# Agent Loop
# ============================================

messages = []


def chat(user_input):
    compress_history()
    messages.append({"role": "user", "content": user_input})
    log_event("user_input", {"content": user_input})

    # 收集本轮对话中所有工具调用和结果
    round_tool_traces = []

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
                if hasattr(event, "type") and event.type == "content_block_start":
                    if hasattr(event.content_block, "type") and event.content_block.type == "tool_use":
                        print("\n🔧 正在规划工具调用...", flush=True)
                if hasattr(event, "type") and event.type == "content_block_delta":
                    if hasattr(event.delta, "text"):
                        print(event.delta.text, end="", flush=True)

            # 流结束后拿到完整 response
            response = stream.get_final_message()
            print()

        log_event("llm_response", {"stop_reason": response.stop_reason})

        if response.stop_reason == "end_turn":
            assistant_text = ""
            for block in response.content:
                if block.type == "text":
                    assistant_text = block.text

            messages.append({"role": "assistant", "content": response.content})
            log_event("agent_reply", {"content": assistant_text})

            # 推理型 Sensor：只在写操作回合做评测
            if should_review_turn(user_input, assistant_text, round_tool_traces):
                print("\n[系统] 检测到本轮有写操作，正在进行结果评测，请稍等...", flush=True)

                review = review_agent_output(user_input, assistant_text, round_tool_traces)

                print("[系统] 本轮评测完成", flush=True)

                if SHOW_REVIEW_RESULT:
                    print_review_summary(review)
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

                        round_tool_traces.append({
                            "tool_use_id": tool_use_id,
                            "tool": tool_name,
                            "input": tool_input,
                            "status": "blocked_protected_source",
                            "result": truncate_for_review(result),
                        })

                        messages.append({
                            "role": "user",
                            "content": [{
                                "type": "tool_result",
                                "tool_use_id": tool_use_id,
                                "content": result
                            }],
                        })
                        continue

                    if needs_confirmation(tool_name, tool_input):
                        approved = confirm_tool_call(tool_name, tool_input)
                    else:
                        print(f"  [自动执行] {tool_name}({json.dumps(tool_input, ensure_ascii=False)})")
                        approved = True

                    if approved:
                        result = execute_tool(tool_name, tool_input)
                        log_event("tool_executed", {"tool": tool_name, "result": result})

                        round_tool_traces.append({
                            "tool_use_id": tool_use_id,
                            "tool": tool_name,
                            "input": tool_input,
                            "status": "executed",
                            "result": truncate_for_review(result),
                        })

                        if tool_name == "write_file" and not result.startswith("拒绝"):
                            result += "\n\n[系统指令] 文件已写入。请停止当前操作，将结果报告给用户，并询问用户是否继续下一步。不要自行继续创建更多文件。"
                    else:
                        result = "用户拒绝了此操作"
                        log_event("tool_rejected", {"tool": tool_name})

                        round_tool_traces.append({
                            "tool_use_id": tool_use_id,
                            "tool": tool_name,
                            "input": tool_input,
                            "status": "rejected_by_user",
                            "result": result,
                        })

                    messages.append({
                        "role": "user",
                        "content": [{
                            "type": "tool_result",
                            "tool_use_id": tool_use_id,
                            "content": result
                        }],
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
    chat(user_input)  # 不再接收返回值，也不再打印
    print(f"[DEBUG] 当前消息历史: {len(messages)} 条")