"""Phase 6 — LLM-assisted Consolidation Content Generator.

只做 content / evidence_summary 增强，不决定 governance、不写 store、
不 auto-approve、不改变 consolidation_type 或 confidence。

架构边界（RFC §15.4, §6.4, §D.1）：
- 输入: ConsolidationCandidate draft（来自 deterministic detector）+ 对应 evidence group
- 输出: ConsolidationCandidate（content/evidence_summary 增强）
- 默认关闭 — MEMORY_CONSOLIDATION_LLM_ENABLED=true 才启用
- LLM 不可用时 fallback 到 deterministic candidate + warning
- 不改变 memory_type / governance_route / source_evidence / confidence
- 不写 store、不接 runtime、不 dispatch pending
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace

from agent.memory_consolidation import ConsolidationCandidate, EpisodicEvidence
from agent.provider.factory import build_model_provider_from_env
from agent.provider.protocol import ModelProvider, ProviderError

# ── LLM prompt ──────────────────────────────────────────────────────────────

_CONSOLIDATION_CONTENT_SYSTEM_PROMPT = """\
你是一个 memory consolidation 内容生成器。你的任务是：
根据多条 episodic evidence（用户的历史交互记录），为一条 semantic memory candidate
生成更自然、更具体的内容描述和证据摘要。

规则：
1. content：用 1-2 句话总结从这些 evidence 中可以提炼出的用户偏好、知识或事实。
   只写语义级的总结，不要逐条复述原文。
2. evidence_summary：用一句话概括支撑这个 candidate 的证据数量和主题。
   必须包含 record_id 引用（如 "record_ids=id1,id2,id3"）。
3. confidence_adjustment：始终为 0.0（不调整置信度）。
4. warnings：如果 evidence 不足以支撑语义总结，或内容互相矛盾，在 warnings 中说明。

禁止：
- 禁止生成行为指令（如 "以后必须..."、"Agent 应该..."）。
- 禁止编造输入 evidence 中不存在的 record_id。
- 禁止引入输入 evidence 之外的新事实。
- 禁止输出 procedural memory 候选。

输出格式（纯 JSON，不要包含 markdown 代码块标记）：
{"content": "...", "evidence_summary": "...", "confidence_adjustment": 0.0, "warnings": []}
"""

@dataclass(frozen=True, slots=True)
class EvidenceBudgetConfig:
    """LLM evidence prompt 的轻量 char budget。

    这是 P3 hardening，不是 tokenizer accounting：用 deterministic char guard
    限制 prompt 输入规模，避免 dogfood/真实 provider 路径构造过长上下文。
    """

    max_evidence_items: int = 12
    max_chars_per_evidence: int = 300
    max_total_chars: int = 3600


@dataclass(frozen=True, slots=True)
class EvidenceBudgetSummary:
    """budget 结果摘要，只包含计数，不包含原始 evidence 正文。"""

    evidence_input_count: int
    evidence_used_count: int
    truncated_count: int
    total_chars_used: int
    budget_applied: bool

    def to_safe_dict(self) -> dict[str, int | bool]:
        """返回可打印/写入 dogfood report 的脱敏摘要。"""

        return {
            "evidence_input_count": self.evidence_input_count,
            "evidence_used_count": self.evidence_used_count,
            "truncated_count": self.truncated_count,
            "total_chars_used": self.total_chars_used,
            "budget_applied": self.budget_applied,
        }


@dataclass(frozen=True, slots=True)
class EvidenceBudgetResult:
    """budget 后实际进入 LLM prompt 的 evidence 与脱敏摘要。"""

    evidence: tuple[EpisodicEvidence, ...]
    summary: EvidenceBudgetSummary


def apply_evidence_budget(
    evidence_list: list[EpisodicEvidence],
    budget: EvidenceBudgetConfig | None = None,
) -> EvidenceBudgetResult:
    """对 LLM evidence 输入应用轻量 budget guard。

    只裁剪传给 LLM prompt 的 content，不改变原始 store/evidence 对象，也不改变
    validator、source_evidence、T1 pending 语义。被省略或截断的 evidence 只在
    summary 中以计数呈现，避免输出 raw memory text 或 secret-like 内容。
    """

    cfg = budget or EvidenceBudgetConfig()
    used: list[EpisodicEvidence] = []
    truncated_count = 0
    total_chars = 0

    for index, evidence in enumerate(evidence_list):
        if index >= cfg.max_evidence_items:
            truncated_count += 1
            continue
        remaining = cfg.max_total_chars - total_chars
        if remaining <= 0:
            truncated_count += 1
            continue

        limit = min(cfg.max_chars_per_evidence, remaining)
        content = evidence.content[:limit]
        if len(content) < len(evidence.content):
            truncated_count += 1
        total_chars += len(content)
        used.append(replace(evidence, content=content))

    summary = EvidenceBudgetSummary(
        evidence_input_count=len(evidence_list),
        evidence_used_count=len(used),
        truncated_count=truncated_count,
        total_chars_used=total_chars,
        budget_applied=truncated_count > 0,
    )
    return EvidenceBudgetResult(evidence=tuple(used), summary=summary)


def _build_evidence_context(
    evidence_list: list[EpisodicEvidence],
    *,
    budget: EvidenceBudgetConfig | None = None,
) -> str:
    """将 evidence group 格式化为 LLM prompt 可用的上下文文本。

    通过 apply_evidence_budget() 统一做轻量 char budget，避免 prompt 过长。
    """
    parts: list[str] = []
    budgeted = apply_evidence_budget(evidence_list, budget)
    for e in budgeted.evidence:
        parts.append(
            f"[record_id={e.record_id}] scope={e.scope or '-'} "
            f"content={e.content}"
        )
    return "\n".join(parts)


# ── Validator ───────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class LLMConsolidationValidationResult:
    """LLM 增强 candidate 的校验结果。"""

    valid: bool
    candidate: ConsolidationCandidate | None = None
    warnings: tuple[str, ...] = ()

    @property
    def is_valid(self) -> bool:
        return self.valid


def _is_procedural_like_content(content: str) -> bool:
    """检查 content 是否包含 procedural-like 语言。

    复用 engine 中的检测模式，但只检查内容本身（不导入 engine）。
    """
    procedural_patterns: tuple[re.Pattern, ...] = (
        re.compile(r"以后.{0,10}(必须|禁止|不要|不能|不应该|永远|绝对)"),
        re.compile(r"记住.{0,10}(必须|禁止|不要|永远)"),
        re.compile(r"(以后|下次|从现在开始).{0,15}(先|再|不要|别)"),
        re.compile(r"(永远|千万|绝对).{0,5}(不要|禁止|不能|别)"),
        re.compile(r"(never|always|must)\s+\w+"),
    )
    return any(p.search(content) for p in procedural_patterns)


def validate_llm_enhanced_candidate(
    candidate: ConsolidationCandidate,
    input_evidence_ids: frozenset[str] | set[str],
) -> LLMConsolidationValidationResult:
    """验证 LLM 增强后的 ConsolidationCandidate 满足所有安全约束。

    Fail-closed：任何一项不满足即返回 invalid。
    这是 defense-in-depth 层——即使 LLM 输出违规，也不会进入 pending review。

    校验项：
    1. memory_type == "semantic"
    2. governance_route == "T1"
    3. source_evidence ⊆ input evidence ids（防止 hallucinated record_id）
    4. len(source_evidence) >= 3
    5. confidence ∈ [0, 1]
    6. content 非空
    7. content 不包含 procedural-like 语言
    8. evidence_summary 不得包含完整原始对话长文本（>500 字）
    """
    warnings: list[str] = []

    if candidate.memory_type != "semantic":
        return LLMConsolidationValidationResult(
            valid=False,
            warnings=(f"memory_type={candidate.memory_type}，非 semantic，拒绝",),
        )

    if candidate.governance_route != "T1":
        return LLMConsolidationValidationResult(
            valid=False,
            warnings=(f"governance_route={candidate.governance_route}，非 T1，拒绝",),
        )

    # 防止 hallucinated record_id：LLM 输出的 source_evidence 必须是输入的子集
    candidate_ids = set(candidate.source_evidence)
    expected_ids = set(input_evidence_ids)
    if not candidate_ids.issubset(expected_ids):
        extra = candidate_ids - expected_ids
        return LLMConsolidationValidationResult(
            valid=False,
            warnings=(f"source_evidence 包含不在输入中的 record_id: {extra}",),
        )

    if len(candidate.source_evidence) < 3:
        warnings.append(
            f"source_evidence 仅 {len(candidate.source_evidence)} 条，不足 N≥3"
        )
        return LLMConsolidationValidationResult(
            valid=False,
            warnings=tuple(warnings),
        )

    if not (0.0 <= candidate.confidence <= 1.0):
        warnings.append(f"confidence={candidate.confidence} 超出 [0, 1]")
        return LLMConsolidationValidationResult(
            valid=False,
            warnings=tuple(warnings),
        )

    if not candidate.content or not candidate.content.strip():
        return LLMConsolidationValidationResult(
            valid=False,
            warnings=("content 为空，拒绝",),
        )

    if _is_procedural_like_content(candidate.content):
        return LLMConsolidationValidationResult(
            valid=False,
            warnings=("content 包含 procedural-like 语言，拒绝",),
        )

    if len(candidate.evidence_summary) > 500:
        warnings.append(
            f"evidence_summary 过长 ({len(candidate.evidence_summary)} 字)，截断"
        )

    return LLMConsolidationValidationResult(
        valid=True,
        candidate=candidate,
        warnings=tuple(warnings),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# LLM Content Generator
# ═══════════════════════════════════════════════════════════════════════════════


class LLMConsolidationContentGenerator:
    """LLM 驱动的 consolidation content / evidence_summary 增强器。

    输入: ConsolidationCandidate draft + 对应 EpisodicEvidence 列表
    输出: ConsolidationCandidate（content / evidence_summary 增强）

    只做 content enhancement，不改变：
    - memory_type（保持 semantic）
    - governance_route（保持 T1）
    - source_evidence（保持原 record_ids）
    - confidence（保持或轻微降权，不提高）
    - consolidation_type（保持原类型）

    调用者负责 opt-in gate 和 T1 pending dispatch。
    """

    def __init__(
        self,
        *,
        provider: ModelProvider | None = None,
        model_name: str | None = None,
        max_tokens: int = 1024,
    ):
        """初始化 LLM content generator。

        Args:
            provider: 注入的 ModelProvider；None 时尝试 provider factory。
            model_name: 仅用于 summary 标识，不参与 SDK 构造。
            max_tokens: LLM 响应的最大 token 数。
        """
        if provider is None:
            try:
                provider = build_model_provider_from_env()
            except ProviderError:
                provider = None
        self._provider = provider
        self._model_name = model_name or (
            getattr(provider, "provider_type", "provider") if provider else None
        )
        self._max_tokens = max_tokens

    def _get_provider(self) -> ModelProvider:
        """返回可用 provider；不可用时 fail closed。

        Memory consolidation 只增强 content/evidence_summary，不拥有 provider
        选择权，也不直接读取 legacy config.py 或实例化具体 SDK。
        """
        if self._provider is None:
            raise ValueError(
                "ModelProvider 未设置。请通过 provider factory 注入 LLM provider。"
            )
        return self._provider

    # ── 公开 API ──────────────────────────────────────────────────────────

    def enhance(
        self,
        candidate: ConsolidationCandidate,
        evidence_group: list[EpisodicEvidence],
    ) -> tuple[ConsolidationCandidate | None, tuple[str, ...]]:
        """为一条 deterministic candidate 生成 LLM 增强的 content/evidence_summary。

        Args:
            candidate: 确定性 detector 产出的 ConsolidationCandidate draft。
            evidence_group: 生成此 candidate 的原始 EpisodicEvidence 列表。

        Returns:
            (enhanced_candidate, warnings):
            - enhanced_candidate: 增强后的 candidate（content/evidence_summary 更新），
              LLM 不可用或增强失败时返回 None。
            - warnings: 处理过程中的警告信息。
        """
        if not evidence_group:
            return None, ("evidence_group 为空，无法增强",)

        evidence_ids = frozenset(e.record_id for e in evidence_group)

        # 调用 LLM 生成增强内容
        try:
            llm_output = self._call_llm(evidence_group, candidate)
        except Exception as exc:
            return None, (f"LLM 调用失败: {exc}",)

        if llm_output is None:
            return None, ("LLM 返回为空或无法解析",)

        # 构建增强后的 candidate
        enhanced = ConsolidationCandidate(
            content=llm_output["content"],
            memory_type=candidate.memory_type,
            source_evidence=candidate.source_evidence,
            consolidation_type=candidate.consolidation_type,
            confidence=candidate.confidence,
            governance_route=candidate.governance_route,
            evidence_summary=llm_output["evidence_summary"],
            created_at=candidate.created_at,
        )

        # Fail-closed validation
        validation = validate_llm_enhanced_candidate(enhanced, evidence_ids)
        if not validation.is_valid:
            return None, validation.warnings

        all_warnings = tuple(llm_output.get("warnings", [])) + validation.warnings
        return validation.candidate, all_warnings

    def _call_llm(
        self,
        evidence_group: list[EpisodicEvidence],
        candidate: ConsolidationCandidate,
    ) -> dict | None:
        """调用 LLM 生成增强的 content 和 evidence_summary。

        Returns:
            解析后的 JSON dict，或 None（LLM 不可用或解析失败）。
        """
        try:
            provider = self._get_provider()
        except ValueError as exc:
            raise RuntimeError(f"LLM client 不可用: {exc}") from exc

        evidence_context = _build_evidence_context(evidence_group)
        user_prompt = (
            f"确定性检测器从以下 episodic evidence 中检测到一个 pattern：\n\n"
            f"检测类型: {candidate.consolidation_type.value}\n"
            f"当前模板化内容: {candidate.content}\n\n"
            f"原始 episodic evidence:\n{evidence_context}\n\n"
            f"请生成更自然的 content 和 evidence_summary。"
            f"只输出 JSON，不要包含 markdown 代码块标记。"
        )

        response = provider.create(
            system=_CONSOLIDATION_CONTENT_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
            tools=[],
        )

        raw_output = "".join(
            block.text for block in response.content
            if getattr(block, "text", None)
        ) if response.content else ""

        return self._parse_llm_output(raw_output)

    def _parse_llm_output(self, raw: str) -> dict | None:
        """从 LLM 原始输出中解析 JSON。

        处理可能的 markdown 代码块包裹。
        """
        if not raw or not raw.strip():
            return None

        text = raw.strip()

        # 尝试提取 ```json ... ``` 或 ``` ... ``` 包裹的内容
        m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if m:
            text = m.group(1).strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # 尝试提取第一个 { 到最后一个 }
            m2 = re.search(r"\{.*\}", text, re.DOTALL)
            if m2:
                try:
                    data = json.loads(m2.group(0))
                except json.JSONDecodeError:
                    return None
            else:
                return None

        if not isinstance(data, dict):
            return None
        if "content" not in data:
            return None

        return data


# ── Fake / test double ──────────────────────────────────────────────────────


class FakeLLMConsolidationContentGenerator(LLMConsolidationContentGenerator):
    """用于测试的 fake LLM content generator。

    不调用真实 LLM，返回预置的增强内容。
    行为完全 deterministic。
    """

    def __init__(self, *, enhanced_content: str = "", enhanced_summary: str = ""):
        self._enhanced_content = enhanced_content
        self._enhanced_summary = enhanced_summary
        self._call_count = 0

    def _get_provider(self):
        raise RuntimeError("Fake generator 不应尝试获取真实 provider")

    def enhance(
        self,
        candidate: ConsolidationCandidate,
        evidence_group: list[EpisodicEvidence],
    ) -> tuple[ConsolidationCandidate | None, tuple[str, ...]]:
        """返回 pre-set 增强内容，不调用 LLM。"""
        self._call_count += 1

        if not self._enhanced_content and not self._enhanced_summary:
            return None, ("fake generator 未配置增强内容",)

        evidence_ids = frozenset(e.record_id for e in evidence_group)

        content = self._enhanced_content or candidate.content
        summary = self._enhanced_summary or candidate.evidence_summary

        enhanced = ConsolidationCandidate(
            content=content,
            memory_type=candidate.memory_type,
            source_evidence=candidate.source_evidence,
            consolidation_type=candidate.consolidation_type,
            confidence=candidate.confidence,
            governance_route=candidate.governance_route,
            evidence_summary=summary,
            created_at=candidate.created_at,
        )

        validation = validate_llm_enhanced_candidate(enhanced, evidence_ids)
        if not validation.is_valid:
            return None, validation.warnings

        fake_warnings = ("fake generator used — 非真实 LLM 输出",)
        return validation.candidate, fake_warnings


# ── Pipeline integration helpers ────────────────────────────────────────────


def _is_llm_consolidation_enabled() -> bool:
    """读取 MEMORY_CONSOLIDATION_LLM_ENABLED 环境变量。

    与 _maybe_run_consolidation 的 gate 风格一致：
    只检查环境变量，不读取任何数据文件或 API 日志。
    """
    import os as _os

    return _os.getenv("MEMORY_CONSOLIDATION_LLM_ENABLED", "").strip() in (
        "1", "true", "yes", "True", "TRUE",
    )


def create_llm_content_generator() -> LLMConsolidationContentGenerator | None:
    """创建 LLM content generator 实例。

    API key 不可用时返回 None（不抛出异常），调用者 fallback 到 deterministic。

    不读取 .env 内容，也不依赖 config.py import 副作用。真实 provider 的
    构造统一委托给 agent/provider/factory.py；若没有显式 provider config，
    返回 None 并保持 deterministic fallback。
    """
    if not _is_llm_consolidation_enabled():
        return None

    try:
        provider = build_model_provider_from_env()
        if provider is None:
            return None
        return LLMConsolidationContentGenerator(provider=provider)
    except Exception:
        return None
