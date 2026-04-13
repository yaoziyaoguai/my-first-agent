import json
import re
import ast
import operator
import subprocess
# import hashlib
import httpx
from bs4 import BeautifulSoup
from pathlib import Path
from config import ALLOWED_TOOLS, PROJECT_DIR
from agent.logger import log_event
from agent.security import is_protected_source_file, _extract_script_path
from agent.security import is_sensitive_file

FETCH_TIMEOUT = 15  # 秒
FETCH_MAX_CHARS = 10000  # 最多返回的字符数

def fetch_url(url):
    """抓取网页内容，提取正文"""
    
    if not url.startswith(("http://", "https://")):
        return "错误：URL 必须以 http:// 或 https:// 开头"
    
    try:
        response = httpx.get(
            url,
            timeout=FETCH_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; AgentBot/1.0)"},
        )
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "iframe", "noscript"]):
            tag.decompose()
        
        text = soup.get_text(separator="\n", strip=True)
        lines = [line for line in text.splitlines() if line.strip()]
        text = "\n".join(lines)
        
        total_chars = len(text)
        
        if total_chars == 0:
            return f"[读取成功] URL: {url}\n\n页面没有可提取的文本内容。"
        
        # 内容较长时，保存到本地文件
        if total_chars > FETCH_MAX_CHARS:
            # 用 URL 生成一个安全的文件名
            import hashlib
            url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
            save_path = Path("workspace") / f"fetched_{url_hash}.txt"
            save_path.parent.mkdir(parents=True, exist_ok=True)
            save_path.write_text(text, encoding="utf-8")
            
            preview = text[:3000]
            total_lines = len(text.splitlines())
            
            return (
                f"[读取成功 - 内容较长，已保存到本地]\n"
                f"URL: {url}\n"
                f"总字符数: {total_chars}\n"
                f"总行数: {total_lines}\n"
                f"本地文件: {save_path}\n\n"
                f"[开头预览（前 3000 字符）]\n"
                f"{preview}\n\n"
                f"[说明] 完整内容已保存到 {save_path}。如需查看具体部分，请使用 read_file_lines 工具读取该文件。"
            )
        
        return (
            f"[读取成功]\n"
            f"URL: {url}\n"
            f"总字符数: {total_chars}\n\n"
            f"{text}"
        )
        
    except httpx.TimeoutException:
        return f"读取超时：{url} 在 {FETCH_TIMEOUT} 秒内未响应。"
    except httpx.HTTPStatusError as e:
        return f"HTTP 错误：{url} 返回状态码 {e.response.status_code}"
    except Exception as e:
        return f"读取失败：{e}"




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
    

# Shell 命令黑名单（正则模式）
SHELL_BLACKLIST = [
    r"\brm\s+(-[a-zA-Z]*f|-[a-zA-Z]*r|--force|--recursive)",  # rm -rf 等
    r"\bsudo\b",
    r"\bmkfs\b",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bpoweroff\b",
    r"\bdd\s+",
    r"\b:(){ :\|:& };:",  # fork bomb
    r"\b>\s*/dev/sd",      # 覆写磁盘
    r"\bchmod\s+777",
    r"\bchown\b",
    r"\bpasswd\b",
    r"\bkill\s+-9",
]

SHELL_TIMEOUT = 30  # 秒

def check_shell_blacklist(command):
    """检查命令是否匹配黑名单，返回匹配到的模式或 None"""
    for pattern in SHELL_BLACKLIST:
        if re.search(pattern, command):
            return pattern
    return None





def run_shell(command):
    # Guide: 命令本身的黑名单检查
    blocked_pattern = check_shell_blacklist(command)
    if blocked_pattern:
        return f"拒绝执行：命令匹配危险模式 '{blocked_pattern}'，禁止运行。"
        # Guide: 敏感文件保护——检查命令是否试图读取敏感文件
    words = command.split()
    for word in words:
        if is_sensitive_file(word):
            return f"拒绝执行：命令涉及敏感文件 '{word}'，禁止访问。"
    
    # Guide: 如果是执行脚本文件，检查脚本内容
    script_path = _extract_script_path(command)
    if script_path:
        script_file = Path(script_path)
        if not script_file.exists():
            script_file = PROJECT_DIR / script_path
        if script_file.exists():
            try:
                script_content = script_file.read_text(encoding="utf-8", errors="replace")
                blocked_pattern = check_shell_blacklist(script_content)
                if blocked_pattern:
                    return f"拒绝执行：脚本文件 '{script_path}' 内容匹配危险模式 '{blocked_pattern}'，禁止运行。"
            except Exception:
                pass

    # 后面的执行逻辑不变
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=SHELL_TIMEOUT,
            cwd=str(PROJECT_DIR),
        )
        
        output = ""
        if result.stdout:
            output += f"[stdout]\n{result.stdout}"
        if result.stderr:
            output += f"\n[stderr]\n{result.stderr}"
        if not output.strip():
            output = "(无输出)"
        
        # Sensor: 截断过长的输出
        if len(output) > 5000:
            output = output[:5000] + f"\n\n...(输出过长，已截断，共 {len(output)} 字符)"
        
        output = f"[退出码: {result.returncode}]\n{output}"
        return output
        
    except subprocess.TimeoutExpired:
        return f"执行超时：命令在 {SHELL_TIMEOUT} 秒内未完成，已被终止。"
    except Exception as e:
        print(f"[DEBUG] run_shell 错误: {e}")
        return f"执行错误：{e}"



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
    elif tool_name == "run_shell":
        return run_shell(tool_input["command"])
    elif tool_name == "fetch_url":
        return fetch_url(tool_input["url"])



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
                    "description": "计算一个数学表达式。仅在用户明确要求进行数学计算时使用。不要对文档内容、文件中出现的数字或表达式主动调用此工具。"
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
    },
    {
        "name": "fetch_url",
        "description": "读取一个网页的文本内容。仅在用户明确提供 URL 或要求访问网页时使用。不要主动搜索或猜测 URL。",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "要读取的网页 URL，必须以 http:// 或 https:// 开头"
                }
            },
            "required": ["url"]
        }
    },

    {
        "name": "run_shell",
        "description": "在项目目录下执行一条 Shell 命令。仅在用户明确要求执行命令时使用。不要主动执行命令来探索文件系统——使用 read_file 代替。危险命令（如 rm -rf、sudo）会被自动拦截。",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "要执行的 Shell 命令"
                }
            },
            "required": ["command"]
        }
    }
]
