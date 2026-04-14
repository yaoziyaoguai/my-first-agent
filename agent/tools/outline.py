import json
import re


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
        return ["(JSON 解析失败)"]
    outline = []
    def walk(obj, prefix="", depth=0):
        if len(outline) >= 100 or depth > 2:
            return
        if isinstance(obj, dict):
            for key, value in obj.items():
                if len(outline) >= 100:
                    return
                path = f"{prefix}.{key}" if prefix else str(key)
                outline.append(f"JSON: {path} ({type(value).__name__})")
                if isinstance(value, dict):
                    walk(value, path, depth + 1)
                elif isinstance(value, list) and value:
                    outline.append(f"JSON: {path}[0] ({type(value[0]).__name__})")
                    if isinstance(value[0], dict):
                        walk(value[0], f"{path}[0]", depth + 1)
        elif isinstance(obj, list):
            outline.append(f"JSON: root (list, len={len(obj)})")
            if obj and isinstance(obj[0], dict):
                walk(obj[0], "root[0]", depth + 1)
    walk(data)
    return outline if outline else ["(JSON 未识别到结构)"]


def extract_yaml_outline(content):
    outline = []
    for idx, line in enumerate(content.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        candidate = stripped[2:].strip() if stripped.startswith("- ") else stripped
        if ":" not in candidate:
            continue
        key_part = candidate.split(":", 1)[0].strip()
        if not key_part:
            continue
        if " " in key_part and not (key_part.startswith('"') and key_part.endswith('"')) and not (key_part.startswith("'") and key_part.endswith("'")):
            continue
        indent = len(line) - len(line.lstrip(" "))
        outline.append(f"Line {idx}: Y{indent // 2 + 1} {key_part}")
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
                outline.append(f"Line {idx}: {label} {match.group(1) if match.lastindex else ''}")
                break
    return outline if outline else ["(未识别到 SQL 结构)"]


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
    return outline if outline else ["(未识别到 JS/TS 结构)"]


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
    return outline if outline else ["(暂不提供结构目录)"]


def extract_file_outline(content, suffix):
    if suffix == ".py":
        return extract_python_outline(content) or ["(未识别到 class / def)"]
    if suffix == ".md":
        return extract_markdown_outline(content) or ["(未识别到 Markdown 标题)"]
    if suffix == ".json":
        return extract_json_outline(content)
    if suffix in {".yaml", ".yml"}:
        return extract_yaml_outline(content)
    if suffix == ".sql":
        return extract_sql_outline(content)
    if suffix in {".js", ".ts", ".jsx", ".tsx"}:
        return extract_js_ts_outline(content)
    return extract_generic_outline(content)
