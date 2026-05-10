"""Phase 2 — Agent-suggested Memory deterministic candidate generation.

本模块只做确定性 heuristic 候选识别。它不写 store、不调 LLM、不接外部 provider、
不读 checkpoint/logs、不 import MCP/provider/tool_executor/TUI backend。

核心原则：
- Agent-suggested memory **不是自动写入 memory**。
- 它只生成 MemoryCandidate，然后**必须走用户确认**。
- 所有 candidate 共享同一套 policy 安全检查（sensitive / prompt injection）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256

from agent.memory_contracts import (
    MemoryCandidate,
    MemoryScope,
    MemorySensitivity,
    MemorySource,
)
from agent.memory_store import MemoryStoreProtocol

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_MAX_CANDIDATES_PER_SESSION = 3
DEFAULT_MIN_CONFIDENCE = 0.6
DEFAULT_REPEATED_PATTERN_THRESHOLD = 3
BUFFER_MAX_SIZE = 50  # 防止 text_buffer 无限增长

# ---------------------------------------------------------------------------
# Heuristic patterns (deterministic, no LLM)
# ---------------------------------------------------------------------------

# 项目规则 / 约束声明
PROJECT_RULE_MARKERS = (
    "这个项目规定",
    "这个项目禁止",
    "这个项目必须",
    "这个项目要求",
    "这个项目的规范",
    "本项目规定",
    "本项目禁止",
    "本项目必须",
    "本项目要求",
    "项目规范是",
)

# Bug fix / 经验教训
BUG_FIX_MARKERS = (
    "上次就是因为",
    "之前踩过坑",
    "经验教训",
    "上回踩坑",
    "上次的坑",
    "之前遇到过一次",
    "历史经验",
    "血的教训",
)

# 架构/技术决策
ARCHITECTURE_DECISION_MARKERS = (
    "我们选了",
    "我们决定用",
    "我们采用",
    "我们选择",
    "我们统一用",
    "我们确定了",
    "架构上我们",
    "技术选型",
)

# 重复偏好触发词（用于在 buffer 中搜索同类声明）
PREFERENCE_PATTERN_PREFIXES = (
    "我喜欢",
    "我习惯",
    "我偏好",
    "我倾向于",
    "我一般",
    "我通常",
    "我不喜欢",
    "我不习惯",
    "我讨厌",
    "不要给我",
    "不要用",
    "别用",
    "别给我",
)

# ---------------------------------------------------------------------------
# Sensitivity / prompt injection (mirrors memory_policy.py)
# 重复这些函数是为了避免 memory_suggestions → memory_policy 的 import
# dependency。suggestion engine 是 policy 的上游输入源，不应反向依赖 policy。
# ---------------------------------------------------------------------------

SENSITIVE_MARKERS = (
    "api key", "api_key", "token", "secret", "password",
    "private key", "passwd", "密钥", "秘钥", "密码", "令牌",
)

PROMPT_INJECTION_MARKERS = (
    "ignore previous instructions",
    "ignore all previous",
    "disregard previous instructions",
    "忽略之前", "无视之前",
)


def _is_sensitive(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in SENSITIVE_MARKERS)


def _looks_like_prompt_injection(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in PROMPT_INJECTION_MARKERS)


# ---------------------------------------------------------------------------
# Engine config
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EngineConfig:
    """DeterministicSuggestionEngine 的可配置参数。"""

    max_candidates_per_session: int = DEFAULT_MAX_CANDIDATES_PER_SESSION
    min_confidence: float = DEFAULT_MIN_CONFIDENCE
    repeated_pattern_threshold: int = DEFAULT_REPEATED_PATTERN_THRESHOLD


# ---------------------------------------------------------------------------
# Deterministic engine
# ---------------------------------------------------------------------------


@dataclass
class DeterministicSuggestionEngine:
    """确定性 heuristic 引擎，基于规则识别 agent-suggested memory candidate。

    状态：
    - _text_buffer: 用户文本历史（最多 BUFFER_MAX_SIZE 条），用于重复偏好检测
    - _candidates_generated: 当前 session 已生成候选数，用于频率限制

    所有 heuristic 规则都是确定性的字符串/模式匹配，不使用 LLM、不调 API、
    不读文件、不接外部 provider。
    """

    config: EngineConfig = field(default_factory=EngineConfig)
    _text_buffer: list[str] = field(default_factory=list)
    _candidates_generated: int = 0

    # -- 核心入口 ------------------------------------------------------------

    def evaluate(
        self,
        user_text: str,
        *,
        existing_store: MemoryStoreProtocol | None = None,
        source: MemorySource = MemorySource.USER_INPUT,
        scope: MemoryScope = MemoryScope.USER,
    ) -> list[MemoryCandidate]:
        """评估 user_text 是否触发任何 suggestion pattern。

        返回符合条件的 MemoryCandidate 列表（可能为空）。
        每个 candidate.metadata 携带 source_type="agent_suggested"。
        """
        if self._candidates_generated >= self.config.max_candidates_per_session:
            return []

        text = user_text.strip()
        if not text:
            return []

        candidates: list[MemoryCandidate] = []

        # Rule 1: project rule（单条文本匹配）
        c = self._check_project_rule(text, source=source, scope=scope)
        if c is not None:
            candidates.append(c)

        # Rule 2: bug fix lesson（单条文本匹配）
        c = self._check_bug_fix_lesson(text, source=source, scope=scope)
        if c is not None:
            candidates.append(c)

        # Rule 3: architecture decision（单条文本匹配）
        c = self._check_architecture_decision(text, source=source, scope=scope)
        if c is not None:
            candidates.append(c)

        # Rule 4: repeated preference（需 buffer 累积）
        self._text_buffer.append(text)
        if len(self._text_buffer) > BUFFER_MAX_SIZE:
            self._text_buffer = self._text_buffer[-BUFFER_MAX_SIZE:]

        c = self._check_repeated_preference(
            text, self._text_buffer, source=source, scope=scope
        )
        if c is not None:
            candidates.append(c)

        # 过滤：confidence threshold / sensitivity / prompt injection / dedup
        result: list[MemoryCandidate] = []
        for c in candidates:
            if c.confidence < self.config.min_confidence:
                continue
            if _is_sensitive(c.content):
                continue
            if _looks_like_prompt_injection(c.content):
                continue
            if existing_store is not None and _is_duplicate(c.content, existing_store):
                continue
            if self._candidates_generated >= self.config.max_candidates_per_session:
                break
            result.append(c)
            self._candidates_generated += 1

        return result

    # -- Heuristic rules -----------------------------------------------------

    @staticmethod
    def _check_project_rule(
        text: str,
        *,
        source: MemorySource,
        scope: MemoryScope,
    ) -> MemoryCandidate | None:
        for marker in PROJECT_RULE_MARKERS:
            if marker in text:
                content = _truncate(text, 300)
                candidate_id = _derive_id("project_rule", content)
                return MemoryCandidate(
                    id=candidate_id,
                    content=content,
                    source=source,
                    source_event=None,
                    proposed_type="procedural",
                    scope=scope,
                    sensitivity=MemorySensitivity.LOW,
                    stability="stable",
                    confidence=0.80,
                    reason="用户显式声明了项目规则或约束",
                    metadata={
                        "source_type": "agent_suggested",
                        "memory_type": "procedural",
                    },
                )
        return None

    @staticmethod
    def _check_bug_fix_lesson(
        text: str,
        *,
        source: MemorySource,
        scope: MemoryScope,
    ) -> MemoryCandidate | None:
        for marker in BUG_FIX_MARKERS:
            if marker in text:
                content = _truncate(text, 300)
                candidate_id = _derive_id("bug_fix_lesson", content)
                return MemoryCandidate(
                    id=candidate_id,
                    content=content,
                    source=source,
                    source_event=None,
                    proposed_type="episodic",
                    scope=scope,
                    sensitivity=MemorySensitivity.LOW,
                    stability="moderate",
                    confidence=0.70,
                    reason="用户提到了历史经验或 bug fix 教训",
                    metadata={
                        "source_type": "agent_suggested",
                        "memory_type": "episodic",
                    },
                )
        return None

    @staticmethod
    def _check_architecture_decision(
        text: str,
        *,
        source: MemorySource,
        scope: MemoryScope,
    ) -> MemoryCandidate | None:
        for marker in ARCHITECTURE_DECISION_MARKERS:
            if marker in text:
                content = _truncate(text, 300)
                candidate_id = _derive_id("architecture_decision", content)
                return MemoryCandidate(
                    id=candidate_id,
                    content=content,
                    source=source,
                    source_event=None,
                    proposed_type="semantic",
                    scope=scope,
                    sensitivity=MemorySensitivity.LOW,
                    stability="stable",
                    confidence=0.75,
                    reason="用户描述了架构或技术决策",
                    metadata={
                        "source_type": "agent_suggested",
                        "memory_type": "semantic",
                    },
                )
        return None

    def _check_repeated_preference(
        self,
        text: str,
        buffer: list[str],
        *,
        source: MemorySource,
        scope: MemoryScope,
    ) -> MemoryCandidate | None:
        """检测与当前文本偏好相似的已累积次数 ≥ threshold。

        只检查当前 text 是否以偏好前缀开头；如果是，在 buffer 中搜索同前缀的条数。
        """
        matched_prefix = _match_preference_prefix(text)
        if matched_prefix is None:
            return None

        # 在 buffer（含当前 text）中数同前缀出现次数
        count = sum(
            1 for t in buffer if t.strip().startswith(matched_prefix)
        )
        if count < self.config.repeated_pattern_threshold:
            return None

        content = _truncate(text, 300)
        candidate_id = _derive_id("repeated_preference", content)
        return MemoryCandidate(
            id=candidate_id,
            content=content,
            source=source,
            source_event=None,
            proposed_type="semantic",
            scope=scope,
            sensitivity=MemorySensitivity.LOW,
            stability="stable",
            confidence=0.70,
            reason=f"用户重复表达了类似偏好（≥{count} 次）",
            metadata={
                "source_type": "agent_suggested",
                "memory_type": "semantic",
            },
        )

    # -- Session management --------------------------------------------------

    def reset_session_counts(self) -> None:
        """重置 session 计数器（text_buffer 保留，频率限制清零）。"""
        self._candidates_generated = 0

    def reset_all(self) -> None:
        """完全重置 engine 状态。"""
        self._text_buffer.clear()
        self._candidates_generated = 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _truncate(text: str, max_len: int) -> str:
    return text if len(text) <= max_len else text[:max_len] + "..."


def _derive_id(category: str, content: str) -> str:
    digest = sha256(f"{category}:{content}".encode("utf-8")).hexdigest()
    return f"suggestion:{category}:{digest[:16]}"


def _match_preference_prefix(text: str) -> str | None:
    """若 text 以偏好前缀开头，返回匹配的前缀字符串；否则返回 None。"""
    for prefix in PREFERENCE_PATTERN_PREFIXES:
        if text.startswith(prefix):
            return prefix
    return None


def _is_duplicate(content: str, store: MemoryStoreProtocol) -> bool:
    """检查 content 是否与 store 中已有 record 高度相似（简化：完全相同哈希）。"""
    content_digest = sha256(content.encode("utf-8")).hexdigest()
    for record in store.list_records():
        record_digest = sha256(record.content.encode("utf-8")).hexdigest()
        if record_digest == content_digest:
            return True
    return False
