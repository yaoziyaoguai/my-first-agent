import json
import re
import ast
import operator
from pathlib import Path
from config import ALLOWED_TOOLS, ENABLE_REVIEW
from agent.logger import log_event
from agent.security import is_protected_source_file


# ============================================
# 数学计算（安全版，基于 AST）
# ============================================

SAFE_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
}

def _eval_node(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp):
        op_func = SAFE_OPS.get(type(node.op))
        if op_func is None:
            raise ValueError(f"不允许的运算符: {type(node.op).__name__}")
        return op_func(_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp):
        op_func = SAFE_OPS.get(type(node.op))
        if op_func is None:
            raise ValueError(f"不允许的运算符: {type(node.op).__name__}")
        return op_func(_eval_node(node.operand))
    raise ValueError(f"不允许的表达式类型: {type(node).__name__}")

def calculate(expression):
    try:
        tree = ast.parse(expression, mode='eval')
        result = _eval_node(tree.body)
        return str(result)
    except (ValueError, SyntaxError) as e:
        return f"计算错误：{e}"
    except ZeroDivisionError:
        return "计算错误：除数不能为零"
    except Exception as e:
        return f"计算错误：{e}"


# ============================================
# 文件结构提取
# ============================================

def extract_python_outline(content):
    outline = []
    for idx, line in enumerate(content.splitlines(), start=1):
        stripped = line.lstrip()
        if stripped.startswith("class "):
            name = stripped[len("class "):].split("(", 1)[0].split(":", 1)[0].strip()
            outline.append(f"Line {idx}: class {name}")
        elif stripped.startswith("def "):
            name = stripped[len("def "):].split("(", 1)[0].strip()
            outline.append(f"Line {idx}: def {name}")
    return outline

def extract_markdown_outline(content):
    outline = []
    for idx, line in enumerate(content.splitlines(), start=1):
        stripped = line.lstrip()
        if not stripped.startswith("#"):
            continue
        level = 0
        for ch in stripped:
            if ch == "#":
                level += 1
            else:
                break
        if 1 <= level <= 6 and len(stripped) > level and stripped[level] == " ":
            title = stripped[level + 1:].strip()
            if title:
                outline.append(f"Line {idx}: H{level} {title}")
    return outline

def extract_json_outline(content):
    try:
        data = json.loads(content)
    except Exception:
        return ["(JSON 解析失败，无法提取结构)"]
    outline = []
    def walk(obj, prefix="", depth=0, max_items=100):
        nonlocal outline
        if len(outline) >= max_items or depth > 2:
            return
        if isinstance(obj, dict):
            for key, value in obj.items():
                if len(outline) >= max_items:
                    return
                path = f"{prefix}.{key}" if prefix else str(key)
                outline.append(f"JSON: {path} ({type(value).__name__})")
                if isinstance(value, dict):
                    walk(value, path, depth + 1, max_items)
                elif isinstance(value, list) and value:
                    first = value[0]
                    outline.append(f"JSON: {path}[0] ({type(first).__name__})")
                    if isinstance(first, dict):
                        walk(first, f"{path}[0]", depth + 1, max_items)
        elif isinstance(obj, list):
            outline.append(f"JSON: root (list, len={len(obj)})")
            if obj:
                first = obj[0]
                outline.append(f"JSON: root[0] ({type(first).__name__})")
                if isinstance(first, dict):
                    walk(first, "root[0]", depth + 1, max_items)
    walk(data)
    return outline if outline else ["(JSON 未识别到可展示结构)"]

def extract_yaml_outline(content):
    outline = []
    for idx, line in enumerate(content.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
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
    outline = []
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
    for idx, line in enumerate(content.splitlines(), start=1):
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
    outline = []
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
    for idx, line in enumerate(content.splitlines(), start=1):
        for pattern, label in patterns:
            match = re.search(pattern, line)
            if match:
                outline.append(f"Line {idx}: {label} {match.group(1)}")
                break
    return outline if outline else ["(未识别到 JS/TS 主要结构)"]

def extract_generic_outline(content):
    outline = []
    for idx, line in enumerate(content.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        if re.match(r"^\d+(\.\d+)*[\.\)]?\s+\S+", stripped):
            outline.append(f"Line {idx}: SECTION {stripped}")
        elif len(stripped) <= 80 and stripped.isupper() and len(stripped.split()) <= 8:
            outline.append(f"Line {idx}: TITLE {stripped}")
        elif stripped.endswith(":") and len(stripped) <= 80:
            outline.append(f"Line {idx}: SECTION {stripped}")
    return outline if outline else ["(该文件类型暂不提供明确结构目录)"]

def extract_file_outline(content, suffix):
    if suffix == ".py":
        return extract_python_outline(content) or ["(未识别到 class / def 定义)"]
    if suffix == ".md":
        return extract_markdown_outline(content) or ["(未识别到 Markdown 标题结构)"]
    if suffix == ".json":
        return extract_json_outline(content)
    if suffix in {".yaml", ".yml"}:
        return extract_yaml_outline(content)
    if suffix == ".sql":
        return extract_sql_outline(content)
    if suffix in {".js", ".ts", ".jsx", ".tsx"}:
        return extract_js_ts_outline(content)
    return extract_generic_outline(content)


# ============================================
# 文件操作工具
# ============================================

def read_file(path):
    try:
        file_path = Path(path)
        if not file_path.exists():
            return f"错误：文件 '{path}' 不存在"
        content = file_path.read_text(encoding="utf-8", errors="replace")
        total_lines = len(content.splitlines())
        if len(content) <= 10000:
            return content
        preview = content[:3000]
        suffix = file_path.suffix.lower()
        outline = extract_file_outline(content, suffix)
        outline_text = "\n".join(outline[:200])
        return (
            f"[读取成功 - 文件较大，以下为概览]\n"
            f"路径: {path}\n"
            f"文件类型: {suffix or '(无后缀)'}\n"
            f"总字符数: {len(content)}\n"
            f"总行数: {total_lines}\n\n"
            f"[开头预览（前 3000 字符）]\n"
            f"{preview}\n\n"
            f"[文件结构目录]\n"
            f"{outline_text}\n\n"
            f"[说明] 文件已成功读取。以上是概览信息。如需查看具体行范围，请使用 read_file_lines 工具。不要重复调用 read_file。"
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
        if is_protected_source_file(path):
            return f"拒绝写入：'{path}' 属于受保护源码文件（.py），不允许 Agent 修改"
        file_path = Path(path)
        backup_path = None
        if file_path.exists():
            backup_path = file_path.with_suffix(file_path.suffix + ".bak")
            backup_path.write_text(
                file_path.read_text(encoding="utf-8", errors="replace"),
                encoding="utf-8"
            )
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        msg = f"成功写入 '{path}'"
        if backup_path:
            msg += f"（原文件已备份到 '{backup_path}'）"
        return msg
    except Exception as e:
        return f"写入错误：{e}"


# ============================================
# 工具分发
# ============================================

def execute_tool(tool_name, tool_input):
    if tool_name not in ALLOWED_TOOLS:
        error_msg = f"工具 '{tool_name}' 不在允许列表中"
        log_event("tool_blocked", {"tool": tool_name})
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
# 工具描述（供 API 调用时传入）
# ============================================

TOOL_DEFINITIONS = [
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
        "description": "读取一个文件的内容。如果文件较大（超过10000字符），会返回文件概览而非完整内容，此时请使用 read_file_lines 按行读取具体部分，不要重复调用 read_file 尝试不同路径。",
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
