"""Stage 3 Slice 2 deterministic MemoryPolicy。

本模块只把输入文本映射成 :class:`MemoryDecision`，不执行任何写入、召回、删除、
prompt 注入、checkpoint 保存或 TUI 展示。

设计边界：
- 默认 no-op：普通消息不会自动进入长期记忆。
- explicit-only：只有明确的 remember/记住、forget/忘记、update/更新记忆 才产出
  retain/update/forget decision。
- 敏感内容与 prompt injection 走 reject，不静默 retain。

这不是完整 MemoryPolicy；它是 Stage 3 早期的 deterministic safety baseline，
为后续 confirmation UX、audit、store/provider slice 提供可测试决策语言。
"""

from __future__ import annotations

from hashlib import sha256

from agent.memory_contracts import (
    MemoryCandidate,
    MemoryDecision,
    MemoryDecisionType,
    MemoryScope,
    MemorySensitivity,
    MemorySource,
)


RETAIN_PREFIXES = (
    "remember that ",
    "remember:",
    "remember ",
    "save this:",
    "save that ",
    "记住：",
    "记住:",
    "记住",
)

FORGET_PREFIXES = (
    "forget that ",
    "forget:",
    "forget ",
    "忘记：",
    "忘记:",
    "忘记",
)

UPDATE_PREFIXES = (
    "update my memory:",
    "update memory:",
    "update:",
    "更新你的记忆：",
    "更新你的记忆:",
    "更新记忆：",
    "更新记忆:",
)

SENSITIVE_MARKERS = (
    "api key",
    "api_key",
    "token",
    "secret",
    "password",
    "private key",
    "passwd",
    "密钥",
    "秘钥",
    "密码",
    "令牌",
)

PROMPT_INJECTION_MARKERS = (
    "ignore previous instructions",
    "ignore all previous",
    "disregard previous instructions",
    "忽略之前",
    "无视之前",
)


class DeterministicMemoryPolicy:
    """最小 deterministic policy：只产出 decision，不执行副作用。

    为什么用 class 而不是散落函数：
    policy 的职责是把“输入文本 + 来源范围”集中解释为 MemoryDecision。放在一个
    小类里可以保持可替换 seam（后续 Slice 可引入更严格规则或 fake policy），
    但当前不持有 store/provider/client，因此不会变成依赖容器。
    """

    def decide(
        self,
        text: str,
        *,
        source: MemorySource = MemorySource.USER_INPUT,
        source_event: str | None = None,
        scope: MemoryScope = MemoryScope.USER,
        created_at: str | None = None,
    ) -> MemoryDecision:
        """把一段文本映射成 MemoryDecision。

        本函数只做 deterministic string boundary：
        - 普通文本 -> no-op
        - 显式 remember/记住 -> retain 或 sensitive reject
        - 显式 forget/忘记 -> forget decision
        - 显式 update/更新记忆 -> update decision
        - 模糊 memory 询问 -> clarify

        它不读取文件、不调用网络/LLM、不修改 runtime state。
        """

        raw_text = text.strip()
        lowered = raw_text.lower()

        if _looks_like_prompt_injection(lowered):
            candidate = _build_candidate(
                content=raw_text,
                source=source,
                source_event=source_event,
                proposed_type="memory_instruction",
                scope=scope,
                sensitivity=_classify_sensitivity(raw_text),
                stability="unknown",
                confidence=0.1,
                reason="疑似 prompt injection 试图影响 memory policy",
                created_at=created_at,
            )
            return MemoryDecision(
                decision_type=MemoryDecisionType.REJECT,
                target_candidate=candidate,
                action="reject",
                requires_user_confirmation=False,
                reason="疑似 prompt injection，不能授权长期记忆写入",
                safety_flags=("prompt_injection",),
                provenance=f"candidate:{candidate.id}",
            )

        retain_payload = _extract_payload(raw_text, lowered, RETAIN_PREFIXES)
        if retain_payload is not None:
            return self._retain_decision(
                retain_payload,
                source=source,
                source_event=source_event,
                scope=scope,
                created_at=created_at,
            )

        forget_payload = _extract_payload(raw_text, lowered, FORGET_PREFIXES)
        if forget_payload is not None:
            return self._targeted_decision(
                MemoryDecisionType.FORGET,
                forget_payload,
                action="forget",
                reason="用户显式要求忘记相关信息；本 Slice 只返回 decision，不执行删除",
                source=source,
                source_event=source_event,
                scope=scope,
                created_at=created_at,
            )

        update_payload = _extract_payload(raw_text, lowered, UPDATE_PREFIXES)
        if update_payload is not None:
            return self._targeted_decision(
                MemoryDecisionType.UPDATE,
                update_payload,
                action="update",
                reason="用户显式要求更新记忆；需要确认且不执行写入",
                source=source,
                source_event=source_event,
                scope=scope,
                created_at=created_at,
                requires_user_confirmation=True,
            )

        if _looks_like_ambiguous_memory_request(lowered):
            return MemoryDecision(
                decision_type=MemoryDecisionType.CLARIFY,
                target_candidate=None,
                action="clarify",
                requires_user_confirmation=True,
                reason="用户提到 memory，但没有明确说明要长期记住、更新或忘记什么",
                safety_flags=(),
                provenance=None,
            )

        return MemoryDecision(
            decision_type=MemoryDecisionType.NO_OP,
            target_candidate=None,
            action="no-op",
            requires_user_confirmation=False,
            reason="普通消息默认不进入长期记忆",
            safety_flags=(),
            provenance=None,
        )

    def _retain_decision(
        self,
        payload: str,
        *,
        source: MemorySource,
        source_event: str | None,
        scope: MemoryScope,
        created_at: str | None,
    ) -> MemoryDecision:
        sensitivity = _classify_sensitivity(payload)
        candidate = _build_candidate(
            content=payload,
            source=source,
            source_event=source_event,
            proposed_type="explicit_retain",
            scope=scope,
            sensitivity=sensitivity,
            stability="user_asserted",
            confidence=0.7,
            reason="用户显式提出长期记住这段信息",
            created_at=created_at,
        )

        if sensitivity is MemorySensitivity.SECRET:
            return MemoryDecision(
                decision_type=MemoryDecisionType.REJECT,
                target_candidate=candidate,
                action="reject",
                requires_user_confirmation=False,
                reason="显式 retain 内容包含明显 secret/password/token 风险，拒绝长期记住",
                safety_flags=("sensitive",),
                provenance=f"candidate:{candidate.id}",
            )

        return MemoryDecision(
            decision_type=MemoryDecisionType.RETAIN,
            target_candidate=candidate,
            action="retain",
            requires_user_confirmation=True,
            reason="显式 retain 仍必须经过用户确认后才能写入长期记忆",
            safety_flags=(),
            provenance=f"candidate:{candidate.id}",
        )

    def _targeted_decision(
        self,
        decision_type: MemoryDecisionType,
        payload: str,
        *,
        action: str,
        reason: str,
        source: MemorySource,
        source_event: str | None,
        scope: MemoryScope,
        created_at: str | None,
        requires_user_confirmation: bool = False,
    ) -> MemoryDecision:
        candidate = _build_candidate(
            content=payload,
            source=source,
            source_event=source_event,
            proposed_type=f"explicit_{decision_type.value}",
            scope=scope,
            sensitivity=_classify_sensitivity(payload),
            stability="user_asserted",
            confidence=0.7,
            reason=reason,
            created_at=created_at,
        )
        safety_flags = (
            ("sensitive",)
            if candidate.sensitivity is MemorySensitivity.SECRET
            else ()
        )

        return MemoryDecision(
            decision_type=decision_type,
            target_candidate=candidate,
            action=action,
            requires_user_confirmation=requires_user_confirmation,
            reason=reason,
            safety_flags=safety_flags,
            provenance=f"candidate:{candidate.id}",
        )


def _extract_payload(
    raw_text: str,
    lowered: str,
    prefixes: tuple[str, ...],
) -> str | None:
    """从显式命令前缀后提取 payload；未命中返回 None。"""

    for prefix in prefixes:
        if lowered.startswith(prefix):
            payload = raw_text[len(prefix):].strip(" :：")
            return payload or None
    return None


def _looks_like_ambiguous_memory_request(lowered: str) -> bool:
    """识别“提到记忆但没有明确动作”的请求。"""

    return any(marker in lowered for marker in ("remember", "memory", "记住", "记忆"))


def _looks_like_prompt_injection(lowered: str) -> bool:
    """识别最基础的 prompt injection 记忆写入诱导。"""

    return any(marker in lowered for marker in PROMPT_INJECTION_MARKERS)


def _classify_sensitivity(text: str) -> MemorySensitivity:
    """确定性低保真敏感度分类。

    这不是完整 DLP；它只拦截最明显的 secret/password/token 关键词，避免 Slice 2
    在没有外部分类器时静默 retain 高风险内容。
    """

    lowered = text.lower()
    if any(marker in lowered for marker in SENSITIVE_MARKERS):
        return MemorySensitivity.SECRET
    return MemorySensitivity.LOW


def _build_candidate(
    *,
    content: str,
    source: MemorySource,
    source_event: str | None,
    proposed_type: str,
    scope: MemoryScope,
    sensitivity: MemorySensitivity,
    stability: str,
    confidence: float,
    reason: str,
    created_at: str | None,
) -> MemoryCandidate:
    """构造候选，不写 store；id 仅用于 decision provenance。"""

    candidate_id = _candidate_id(source=source, scope=scope, content=content)
    return MemoryCandidate(
        id=candidate_id,
        content=content,
        source=source,
        source_event=source_event,
        proposed_type=proposed_type,
        scope=scope,
        sensitivity=sensitivity,
        stability=stability,
        confidence=confidence,
        reason=reason,
        created_at=created_at,
    )


def _candidate_id(*, source: MemorySource, scope: MemoryScope, content: str) -> str:
    """生成稳定候选 id；不代表持久化记录 id。"""

    digest = sha256(f"{source.value}:{scope.value}:{content}".encode("utf-8")).hexdigest()
    return f"candidate:{digest[:16]}"

