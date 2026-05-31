"""Skill Descriptor / Manifest —— Level 1 不可变元数据结构。

设计原则（来自 RFC）：
- SkillDescriptor 是公开的、不变的、注册表可见的元数据投影
- SkillManifest 是完整校验后的 frontmatter
- 所有字段不可变，确保跨层传递安全
- 不允许降级 risk_level 或绕过 confirmation_policy
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

# ---- 枚举型类型 ----
# 以下 Literal 匹配 RFC Sec 4 的字段 contract

SkillStatus = Literal["draft", "active", "deprecated", "disabled", "legacy"]
"""Skill 生命周期状态。

- draft: 开发中，默认不可用于生产
- active: 已验证可用
- deprecated: 仍可用但计划移除
- disabled: 被管理员禁用，不可选
- legacy: 历史材料，默认不可见
"""

RiskLevel = Literal["low", "medium", "high"]
"""Skill 声明的风险等级——不能降低 ToolRegistry 的真实风险等级。"""

ConfirmationPolicy = Literal["inherit_tool_policy"]
"""Skill 的确认策略——当前仅支持继承 ToolRegistry 策略。

RFC 明确：Skill 不能降低工具的确认要求。后续 RFC 才可能批准更严格的行为。
"""

MemoryScope = Literal["none", "read_context", "propose_memory"]
"""Skill 声明的 Memory 交互范围。

- none: 不读取也不提议 Memory
- read_context: 可通过适配器读取批准过的上下文
- propose_memory: 可提议 Memory 写入（仍需 governance）
"""

# ---- 允许值集合（用于校验） ----

SKILL_STATUSES: frozenset[str] = frozenset(
    {"draft", "active", "deprecated", "disabled", "legacy"}
)
RISK_LEVELS: frozenset[str] = frozenset({"low", "medium", "high"})
CONFIRMATION_POLICIES: frozenset[str] = frozenset({"inherit_tool_policy"})
MEMORY_SCOPES: frozenset[str] = frozenset({"none", "read_context", "propose_memory"})


@dataclass(frozen=True)
class SkillResourceManifest:
    """SKILL.md frontmatter 中声明的 resource 集合。

    每一项是相对于 skill root 的路径列表。
    """

    references: tuple[str, ...] = ()
    scripts: tuple[str, ...] = ()
    templates: tuple[str, ...] = ()
    tests: tuple[str, ...] = ()
    dogfood: tuple[str, ...] = ()


@dataclass(frozen=True)
class SkillDescriptor:
    """Level 1 不可变元数据——注册表可见的公开投影。

    字段按照 RFC Sec 4 的 field contracts 定义。
    root / manifest_path 为内部字段，不暴露给模型。
    """

    name: str
    """稳定、filesystem-safe 的标识符，在活跃 registry 内唯一。"""

    description: str
    """1-2 句描述，适合始终可见的元数据。"""

    version: str
    """语义化包版本，如 '0.1.0'。"""

    status: SkillStatus
    """生命周期状态。"""

    risk_level: RiskLevel
    """Skill 声明的风险等级。"""

    tags: tuple[str, ...] = ()
    """选择器提示标签。"""

    allowed_tools: tuple[str, ...] = ()
    """声明的工具上限，不是授权绕过。"""

    memory_scope: MemoryScope = "none"
    """Memory 交互范围声明。"""

    root: Path | None = None
    """Skill 目录根路径（内部字段）。"""

    manifest_path: Path | None = None
    """SKILL.md 文件路径（内部字段）。"""

    # ── Plan 3 manifest foundation — Level 1 公开字段 ──
    aliases: tuple[str, ...] = ()
    """skill 别名列表，供 SkillCandidateRetriever 做候选评分。"""

    def is_visible(self) -> bool:
        """disabled / legacy 状态默认不对模型可见。"""
        return self.status not in ("disabled", "legacy")


@dataclass(frozen=True)
class SkillManifest:
    """完整校验后的 SKILL.md frontmatter。

    扩展 SkillDescriptor 所有字段，加上以下仅内部使用的字段。
    """

    name: str = ""
    description: str = ""
    version: str = "0.0.0"
    status: SkillStatus = "draft"
    risk_level: RiskLevel = "low"
    tags: tuple[str, ...] = ()
    allowed_tools: tuple[str, ...] = ()
    memory_scope: MemoryScope = "none"
    root: Path | None = None
    manifest_path: Path | None = None
    confirmation_policy: ConfirmationPolicy = "inherit_tool_policy"
    owner: str = ""
    resources: SkillResourceManifest = field(default_factory=SkillResourceManifest)
    raw_frontmatter: dict[str, object] = field(default_factory=dict)
    """原始 frontmatter dict（仅审计用，已做 redact 处理）。"""

    # ── Plan 3 manifest foundation 新增字段（全部 optional）──
    when_to_use: str | None = None
    """适合使用此 skill 的场景描述，供 SkillCandidateRetriever 做 routing。"""
    when_not_to_use: str | None = None
    """不适合使用此 skill 的场景描述，供 negative matching 使用。"""
    triggers: tuple[str, ...] = ()
    """触发此 skill 的关键词/短语列表——精确匹配权重最高。"""
    negative_triggers: tuple[str, ...] = ()
    """反触发词——命中则排除此 skill。"""
    aliases: tuple[str, ...] = ()
    """skill 别名列表，用于中文/英文/缩写等多语言匹配。"""
    locale: str | None = None
    """skill 的主要语言区域（如 zh-CN, en-US）。"""

    def to_descriptor(self) -> SkillDescriptor:
        """从 Manifest 提取 Level 1 公开元数据投影。"""
        return SkillDescriptor(
            name=self.name,
            description=self.description,
            version=self.version,
            status=self.status,
            risk_level=self.risk_level,
            tags=self.tags,
            allowed_tools=self.allowed_tools,
            memory_scope=self.memory_scope,
            root=self.root,
            manifest_path=self.manifest_path,
            # Plan 3 manifest foundation — Level 1 公开字段
            aliases=self.aliases,
        )

    def is_visible(self) -> bool:
        return self.status not in ("disabled", "legacy")
