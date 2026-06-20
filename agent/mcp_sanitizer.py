"""MCP tool descriptor 文本清洗与对抗性模式扫描。

中文学习边界：
- 本模块只负责 MCP tool description 的文本清洗（截断、来源标记、URL 脱敏）
  和基于正则的对抗性指令扫描。它不评估 server policy、不做 allowlist 检查、
  不返回 policy decision。
- regex-based adversarial scan 只是低成本启发式检查——它只能捕获幼稚的显式
  模式（如 "ignore previous instructions" / "忽略之前的指令"），不能防御
  所有 MCP tool poisoning / indirect prompt injection 攻击。
- 这只是 defense-in-depth 的一层。真正的安全依赖：
  - server/tool allowlist（mcp_policy.py）
  - policy gate + risk assignment（mcp_policy.py）
  - 显式用户确认（tool_executor.py）
  - 结构化审计（tool_audit.py / mcp_audit.py）
  - MCP tool 上下文隔离（[MCP:server_name] 前缀）
  - 后续更强的语义安全评估（不在本轮范围）
- 本模块不 import agent/core.py / agent/tool_executor.py / agent/checkpoint.py /
  agent/mcp.py（只依赖标准库），保持零依赖以便独立测试和审计。
"""

from __future__ import annotations

import re

# MCP description 最大长度（防止超长描述侵占模型上下文）
MAX_MCP_DESCRIPTION_CHARS = 500

# 对抗性指令检测模式 —— 这些模式不应出现在正常的 tool description 中，
# 但可能出现在 tool poisoning 攻击中。
ADVERSARIAL_DESCRIPTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    # 隐式指令劫持：试图告诉 agent "忽略之前的指令"或"你的新任务是"
    re.compile(
        r"(忽略|无视|覆盖|取代|忘记).{0,20}(之前|上述|上面|系统|所有).{0,20}(指令|提示|规则|约束|限制)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(your new task|ignore previous|override system|disregard above|new instructions are)",
        re.IGNORECASE,
    ),
    # 工具欺骗：声称自己是另一个工具
    re.compile(
        r"(this is the real|this is the actual|只有我能|我才是真正的?|you must use me instead of)",
        re.IGNORECASE,
    ),
    # 权限提升暗示
    re.compile(
        r"(you have full access|no restrictions apply|bypass|disable safety"
        r"|跳过安全|绕过限制|完全权限)",
        re.IGNORECASE,
    ),
    # 隐藏的 URL / 命令注入
    re.compile(r"(curl|wget)\s+\S+\s*\|\s*(sh|bash|python)", re.IGNORECASE),
    re.compile(r"\b(eval|exec|system|os\.system|subprocess)\s*\(", re.IGNORECASE),
)

# 工具描述中允许出现的 URL scheme（防止 data: / javascript: 等注入）
ALLOWED_URL_SCHEMES_IN_DESCRIPTION: frozenset[str] = frozenset({"http", "https"})

# 有害 URL scheme 模式
UNSAFE_URL_PATTERN = re.compile(
    r"\b(data|javascript|vbscript|file):", re.IGNORECASE
)


def scan_adversarial_patterns(description: str) -> tuple[str, ...]:
    """扫描描述中的对抗性指令模式。

    对 MCP tool description 做基于正则的启发性扫描，检测常见的隐式 tool
    poisoning / prompt injection 模式。

    regex-based scan 只是低成本第一层防线：
    - 只能捕获幼稚的显式模式（如「忽略之前的指令」/「you have full access」）
    - 不能防御语义层面的间接注入、编码绕过、多语言变体
    - 攻击者可以使用同义替换、隐写、视觉混淆等方式绕开正则
    - 这不是完整的安全评估——最终安全决策由 policy gate、confirmation、
      audit、allowlist 和后续更强的语义评估共同完成

    返回命中的模式描述列表。空列表表示未检测到可疑内容。
    """
    hits: list[str] = []
    for pattern in ADVERSARIAL_DESCRIPTION_PATTERNS:
        match = pattern.search(description)
        if match:
            hits.append(
                f"命中模式 '{pattern.pattern[:60]}...'→'{match.group()[:80]}'"
            )
    return tuple(hits)


def sanitize_description(description: str, *, server_name: str) -> str:
    """对 MCP tool description 做安全脱敏。

    处理步骤：
    1. 截断到 MAX_MCP_DESCRIPTION_CHARS（防止超长描述侵占模型上下文）
    2. 添加 [MCP:server_name] 来源标记（让模型和用户知道这是外部工具）
    3. 移除明显的数据注入（如 data: / javascript: URL scheme）

    返回脱敏后的 model-visible description。
    该描述进入 Anthropic tool schema 的 description 字段，供模型在上下文中
    看到。脱敏后仍保留工具功能说明，但移除了明显的有害内容。
    """
    stripped = description.strip()
    if len(stripped) > MAX_MCP_DESCRIPTION_CHARS:
        stripped = stripped[:MAX_MCP_DESCRIPTION_CHARS] + "…(已截断)"

    # 标记外部来源 —— 这是模型提示中的关键安全信息
    sanitized = f"[MCP:{server_name}] {stripped}"

    # 移除有害 URL scheme
    sanitized = UNSAFE_URL_PATTERN.sub("[blocked:unsafe_url]", sanitized)

    return sanitized
