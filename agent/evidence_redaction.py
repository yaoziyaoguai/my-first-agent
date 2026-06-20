"""S4-G03: secret-safe redaction 层（AC-3 硬边界）。

更高保真 evidence（replay chain 的 input/output preview）**绝不**持久化/暴露 raw
secret / API key / 完整凭证。本模块提供可复用的 redaction 层：

- ``redact_text(text)``：脱敏字符串中的常见 secret 形态（OpenAI/GitHub/AWS/Slack/Google
  key、Bearer token、敏感键赋值）。
- ``redact_metadata(mapping)``：递归脱敏 dict 中的字符串值（供 evidence 写入路径调用）。

设计原则（`S4_FIDELITY_CONTRACT.md §1/§4`）：保真提升**绝不**以泄露 secret 为代价；
redaction **宁可误伤（over-redact）也不漏过**。本模块只检测 fake/已知形态，**绝不**读取或
匹配真实生产凭证——它是对投影文本的纯函数脱敏。
"""

from __future__ import annotations

import re
from typing import Any

_REDACTED = "[REDACTED]"

# 1. Bearer / Authorization 头中的 token（保留 "Bearer" 字样便于 replay 识别字段）。
_BEARER_RE = re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._\-/=+]+")

# 2. 已知高熵 key 字面形态（OpenAI / GitHub / AWS / Slack / Google）。
_LITERAL_KEY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),  # OpenAI-style
    re.compile(r"gh[pousr]_[A-Za-z0-9]{16,}"),  # GitHub PAT/secret
    re.compile(r"AKIA[0-9A-Z]{16,}"),  # AWS access key id
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),  # Slack token
    re.compile(r"AIza[0-9A-Za-z_-]{20,}"),  # Google API key
)

# 3. 敏感键赋值（key:value / key=value，含 JSON/ini 形态）：保留键名，只脱敏 value。
_KV_RE = re.compile(
    r"(?P<key>(?:password|passwd|secret|api[_-]?key|access[_-]?key|access[_-]?token|"
    r"auth[_-]?token|token|credential|authorization))"
    r"\s*(?P<sep>[:=])\s*"
    r"(?P<q>[\"']?)"
    r"(?P<val>[^\s\"',}]+)",
    re.IGNORECASE,
)

# 用于递归脱敏的敏感键名集合（redact_metadata 中对 dict value 整体替换）。
_SENSITIVE_KEY_NAMES = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "api_key",
        "apikey",
        "access_key",
        "access_token",
        "auth_token",
        "authtoken",
        "token",
        "credential",
        "credentials",
        "authorization",
        "private_key",
    }
)


def redact_text(text: str) -> str:
    """脱敏字符串中的常见 secret 形态；非 secret 内容原样保留。

    参数:
        text: 待脱敏的字符串（如 tool input/result 的 safe-summary 投影）。

    返回:
        脱敏后的字符串；secret 被替换为 ``[REDACTED]``。
    """
    if not isinstance(text, str) or not text:
        return text if isinstance(text, str) else ""

    # 先脱敏字面 key 与 bearer，再处理 kv 赋值（顺序无关——均向 [REDACTED] 收敛）。
    out = _BEARER_RE.sub(r"\1 " + _REDACTED, text)
    for pattern in _LITERAL_KEY_PATTERNS:
        out = pattern.sub(_REDACTED, out)
    out = _KV_RE.sub(
        lambda m: f"{m.group('key')}{m.group('sep')}{m.group('q')}{_REDACTED}{m.group('q')}",
        out,
    )
    return out


def redact_metadata(mapping: Any) -> Any:
    """递归脱敏 mapping/list 中的字符串值；对敏感键名的 value 整体替换为 [REDACTED]。

    参数:
        mapping: dict / list / 标量（典型为 evidence metadata）。

    返回:
        同构的新结构（不修改输入）；字符串值经 ``redact_text``，敏感键值整体脱敏。
    """
    if isinstance(mapping, dict):
        out: dict[str, Any] = {}
        for key, value in mapping.items():
            key_name = str(key).lower()
            if key_name in _SENSITIVE_KEY_NAMES and isinstance(value, str) and value:
                out[key] = _REDACTED
            else:
                out[key] = redact_metadata(value)
        return out
    if isinstance(mapping, list):
        return [redact_metadata(item) for item in mapping]
    if isinstance(mapping, str):
        return redact_text(mapping)
    return mapping
