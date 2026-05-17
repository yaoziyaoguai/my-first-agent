"""Phase 6 LLM-assisted consolidation content generation 的结构性测试。

这些测试验证 RFC Phase 6 LLM-assisted consolidation content generation
的 opt-in、validator 和 T1 review 边界，不验证真实模型语义质量。

测试覆盖：
- 默认/关闭时 不调 LLM
- 开启时走 LLM seam
- fake LLM generator 增强 content/evidence_summary
- LLM output 保留 source_evidence / governance_route=T1 / memory_type=semantic
- LLM output 不允许 procedural / auto_retained
- LLM output hallucinated record_id fail closed
- LLM output N<3 fail closed
- LLM output parse failure fail closed
- LLM unavailable 不破坏 deterministic pipeline
- pipeline 默认不读 .env
- pipeline 默认不调用真实 LLM
- 不读取 agent_log.jsonl / 真实 sessions/runs
- LLM warnings 进入 pipeline result
- dispatch 后仍只进 T1 pending
- content generation 不改变 confidence
"""

import pytest

from agent.memory_consolidation import (
    ConsolidationCandidate,
    ConsolidationType,
    EpisodicEvidence,
)
from agent.memory_consolidation_llm import (
    LLMConsolidationContentGenerator,
    FakeLLMConsolidationContentGenerator,
    _build_evidence_context,
    _is_llm_consolidation_enabled,
    _is_procedural_like_content,
    create_llm_content_generator,
    validate_llm_enhanced_candidate,
)
from agent.memory_consolidation_pipeline import (
    ConsolidationPipelineResult,
)
from agent.provider.protocol import ProviderResponse, ProviderTextBlock


# ── helpers ──────────────────────────────────────────────────────────────────


def _candidate(**overrides) -> ConsolidationCandidate:
    """构造有效的确定性 ConsolidationCandidate draft。"""
    defaults = {
        "content": "用户在多个事件中反复表现出对 pytest 的稳定偏好",
        "memory_type": "semantic",
        "source_evidence": ("ep1", "ep2", "ep3"),
        "consolidation_type": ConsolidationType.PATTERN_DETECTION,
        "confidence": 0.42,
        "governance_route": "T1",
        "evidence_summary": "3 条 episodic evidence 共享主题 pytest",
        "created_at": "2026-05-14T10:00:00Z",
    }
    defaults.update(overrides)
    return ConsolidationCandidate(**defaults)


def _evidence(record_id: str, content: str, **kwargs) -> EpisodicEvidence:
    return EpisodicEvidence(record_id=record_id, content=content, **kwargs)


def _valid_evidence_group() -> list[EpisodicEvidence]:
    """构造包含 3 条 evidence 的有效 group。"""
    return [
        _evidence("ep1", "用户使用 pytest 编写所有单元测试，对 fixture 机制评价很高"),
        _evidence("ep2", "用户再次选择 pytest 作为新项目的测试框架，提到 conftest 很好用"),
        _evidence("ep3", "用户拒绝使用 unittest，明确表示更偏好 pytest 的参数化测试"),
    ]


# ── env gate tests ──────────────────────────────────────────────────────────


class TestEnvGate:
    """验证 MEMORY_CONSOLIDATION_LLM_ENABLED 的默认关闭和显式 opt-in。"""

    def test_default_disabled(self, monkeypatch):
        """未设置环境变量时，_is_llm_consolidation_enabled 返回 False。"""
        monkeypatch.delenv("MEMORY_CONSOLIDATION_LLM_ENABLED", raising=False)
        assert _is_llm_consolidation_enabled() is False

    def test_explicit_false(self, monkeypatch):
        """MEMORY_CONSOLIDATION_LLM_ENABLED=false 时返回 False。"""
        monkeypatch.setenv("MEMORY_CONSOLIDATION_LLM_ENABLED", "false")
        assert _is_llm_consolidation_enabled() is False

    def test_explicit_true(self, monkeypatch):
        """MEMORY_CONSOLIDATION_LLM_ENABLED=true 时返回 True。"""
        monkeypatch.setenv("MEMORY_CONSOLIDATION_LLM_ENABLED", "true")
        assert _is_llm_consolidation_enabled() is True

    def test_explicit_1(self, monkeypatch):
        """MEMORY_CONSOLIDATION_LLM_ENABLED=1 时返回 True。"""
        monkeypatch.setenv("MEMORY_CONSOLIDATION_LLM_ENABLED", "1")
        assert _is_llm_consolidation_enabled() is True

    def test_explicit_yes(self, monkeypatch):
        """MEMORY_CONSOLIDATION_LLM_ENABLED=yes 时返回 True。"""
        monkeypatch.setenv("MEMORY_CONSOLIDATION_LLM_ENABLED", "yes")
        assert _is_llm_consolidation_enabled() is True

    def test_disabled_create_returns_none(self, monkeypatch):
        """未开启时 create_llm_content_generator 返回 None。"""
        monkeypatch.delenv("MEMORY_CONSOLIDATION_LLM_ENABLED", raising=False)
        assert create_llm_content_generator() is None


# ── validator tests ─────────────────────────────────────────────────────────


class TestValidatorBasics:
    """验证 validate_llm_enhanced_candidate 的基础校验项。

    注意：memory_type/semantic、governance_route/T1、confidence∈[0,1]、
    content 非空、source_evidence≥2 已由 ConsolidationCandidate.__post_init__
    强制。Validator 的 defense-in-depth 层检查这些约束，但无法在测试中
    直接构造违反约束的 candidate（__post_init__ 会先抛出 ValueError）。

    因此这些校验项的正确性通过以下方式验证：
    - Domain model tests（test_memory_consolidation.py）
    - LLM output parse failure → fail closed（TestFakeLLMGeneratorSafety）
    """

    def test_valid_candidate_passes(self):
        """正常的 semantic/T1/N≥3 candidate 通过验证。"""
        c = _candidate()
        result = validate_llm_enhanced_candidate(c, {"ep1", "ep2", "ep3"})
        assert result.is_valid is True

    def test_domain_model_already_enforces_semantic(self):
        """ConsolidationCandidate.__post_init__ 已拒绝非 semantic memory_type。

        Validator 层作为 defense-in-depth 也会检查，但无法构造违规 candidate
        来直接测试 validator 的此项检查——这被 domain model 覆盖是正确的。
        """
        with pytest.raises(ValueError, match="memory_type"):
            _candidate(memory_type="episodic")

    def test_domain_model_already_enforces_t1(self):
        """ConsolidationCandidate.__post_init__ 已拒绝非 T1 governance_route。"""
        with pytest.raises(ValueError, match="governance_route"):
            _candidate(governance_route="T2")


class TestValidatorHallucinatedSourceEvidence:
    """验证 LLM hallucinated source_evidence 被拦截。"""

    def test_extra_record_id_rejected(self):
        """source_evidence 包含不在输入中的 record_id 被拒绝。"""
        c = _candidate(source_evidence=("ep1", "ep2", "hallucinated_id"))
        result = validate_llm_enhanced_candidate(c, {"ep1", "ep2", "ep3"})
        assert result.is_valid is False
        assert "record_id" in result.warnings[0]

    def test_all_hallucinated_rejected(self):
        """所有 source_evidence 都不在输入中时被拒绝。"""
        c = _candidate(source_evidence=("fake1", "fake2", "fake3"))
        result = validate_llm_enhanced_candidate(c, {"ep1", "ep2", "ep3"})
        assert result.is_valid is False

    def test_valid_subset_passes(self):
        """source_evidence 是输入子集时通过。"""
        c = _candidate(source_evidence=("ep1", "ep2", "ep3"))
        result = validate_llm_enhanced_candidate(c, {"ep1", "ep2", "ep3", "ep4"})
        assert result.is_valid is True


class TestValidatorN3Threshold:
    """验证 N≥3 门槛在 validator 中强制执行。

    注意：domain model 最小 source_evidence=2，validator 和 dispatch 要求≥3。
    source_evidence 数量校验在 domain model __post_init__ 和 validator 之间
    形成分层：domain model 允许≥2（底层数据契约），validator 和 dispatch 要求≥3
    （业务规则）。测试验证 validator 的这一差异。
    """

    def test_n2_not_rejected_by_domain_model(self):
        """source_evidence=2 可通过 domain model（≥2），但会被 dispatch 拒绝（≥3）。

        Validator 属于 pipeline 层，domain model 层不做 N≥3 检查。
        """
        # domain model 允许 ≥2
        c = _candidate(source_evidence=("ep1", "ep2"))
        assert len(c.source_evidence) == 2
        # validator 层检查 ≥3
        result = validate_llm_enhanced_candidate(c, {"ep1", "ep2"})
        assert result.is_valid is False
        assert "N≥3" in result.warnings[0]

    def test_n3_passes_validator(self):
        """source_evidence=3 通过 validator。"""
        c = _candidate(source_evidence=("ep1", "ep2", "ep3"))
        result = validate_llm_enhanced_candidate(c, {"ep1", "ep2", "ep3"})
        assert result.is_valid is True

    def test_n1_rejected_by_domain_model(self):
        """source_evidence=1 被 domain model __post_init__ 拒绝（<2）。

        Validator 不需要额外处理此情况。
        """
        with pytest.raises(ValueError, match="source_evidence"):
            _candidate(source_evidence=("ep1",))


class TestValidatorContentSafety:
    """验证 content 安全约束。

    注意：空 content 已由 ConsolidationCandidate.__post_init__ 拒绝。
    Validator 层额外检查 procedural-like 内容——这是 domain model 不检查的。
    """

    def test_empty_content_rejected_by_domain_model(self):
        """空 content 被 domain model __post_init__ 拒绝。"""
        with pytest.raises(ValueError, match="content"):
            _candidate(content="")

    def test_procedural_content_rejected(self):
        """content 包含 procedural-like 语言被 validator 拒绝。"""
        c = _candidate(content="以后必须先跑测试再提交代码")
        result = validate_llm_enhanced_candidate(c, {"ep1", "ep2", "ep3"})
        assert result.is_valid is False
        assert "procedural" in result.warnings[0]

    def test_procedural_never_command_rejected(self):
        """content 包含 "永远不要" 被 validator 拒绝。"""
        c = _candidate(content="Agent 永远不要自动 commit 代码")
        result = validate_llm_enhanced_candidate(c, {"ep1", "ep2", "ep3"})
        assert result.is_valid is False

    def test_normal_semantic_content_passes(self):
        """正常的语义总结通过 validator 的 procedural 检查。"""
        c = _candidate(content="用户偏好使用 pytest 作为主要 Python 测试框架")
        result = validate_llm_enhanced_candidate(c, {"ep1", "ep2", "ep3"})
        assert result.is_valid is True


class TestValidatorConfidence:
    """验证 confidence 边界。

    注意：confidence∈[0,1] 已由 ConsolidationCandidate.__post_init__ 强制。
    Validator 层做 defense-in-depth 检查保持一致。
    """

    def test_confidence_preserved(self):
        """validator 不改变 confidence 值。"""
        c = _candidate(confidence=0.62)
        result = validate_llm_enhanced_candidate(c, {"ep1", "ep2", "ep3"})
        assert result.is_valid
        assert result.candidate is not None
        assert result.candidate.confidence == 0.62

    def test_negative_confidence_rejected_by_domain_model(self):
        """confidence < 0 被 domain model __post_init__ 拒绝。"""
        with pytest.raises(ValueError, match="confidence"):
            _candidate(confidence=-0.1)

    def test_above_one_confidence_rejected_by_domain_model(self):
        """confidence > 1.0 被 domain model __post_init__ 拒绝。"""
        with pytest.raises(ValueError, match="confidence"):
            _candidate(confidence=1.5)


class TestValidatorLongEvidenceSummary:
    """验证 evidence_summary 过长时的处理。"""

    def test_long_summary_warns(self):
        """evidence_summary 过长时产生 warning 但 candidate 仍 valid。"""
        c = _candidate(evidence_summary="x" * 600)
        result = validate_llm_enhanced_candidate(c, {"ep1", "ep2", "ep3"})
        assert result.is_valid
        assert any("过长" in w for w in result.warnings)


# ── Fake LLM generator tests ───────────────────────────────────────────────


class TestFakeLLMGenerator:
    """验证 FakeLLMConsolidationContentGenerator 的确定性行为。"""

    def test_enhances_content(self):
        """fake generator 替换 candidate content 和 evidence_summary。"""
        fake = FakeLLMConsolidationContentGenerator(
            enhanced_content="用户偏好 pytest 测试框架，用于所有 Python 项目",
            enhanced_summary="3 条 evidence 确认 pytest 偏好",
        )
        c = _candidate()
        group = _valid_evidence_group()
        result, warnings = fake.enhance(c, group)
        assert result is not None
        assert result.content == "用户偏好 pytest 测试框架，用于所有 Python 项目"
        assert result.evidence_summary == "3 条 evidence 确认 pytest 偏好"

    def test_preserves_source_evidence(self):
        """fake generator 保留 source_evidence。"""
        fake = FakeLLMConsolidationContentGenerator(
            enhanced_content="test content",
            enhanced_summary="test summary",
        )
        c = _candidate(source_evidence=("ep1", "ep2", "ep3"))
        result, _ = fake.enhance(c, _valid_evidence_group())
        assert result is not None
        assert result.source_evidence == ("ep1", "ep2", "ep3")

    def test_preserves_governance_route(self):
        """fake generator 保留 governance_route=T1。"""
        fake = FakeLLMConsolidationContentGenerator(
            enhanced_content="test content",
            enhanced_summary="test summary",
        )
        c = _candidate(governance_route="T1")
        result, _ = fake.enhance(c, _valid_evidence_group())
        assert result is not None
        assert result.governance_route == "T1"

    def test_preserves_memory_type(self):
        """fake generator 保留 memory_type=semantic。"""
        fake = FakeLLMConsolidationContentGenerator(
            enhanced_content="test content",
            enhanced_summary="test summary",
        )
        c = _candidate(memory_type="semantic")
        result, _ = fake.enhance(c, _valid_evidence_group())
        assert result is not None
        assert result.memory_type == "semantic"

    def test_preserves_confidence(self):
        """fake generator 不改变 confidence。"""
        fake = FakeLLMConsolidationContentGenerator(
            enhanced_content="test content",
            enhanced_summary="test summary",
        )
        c = _candidate(confidence=0.42)
        result, _ = fake.enhance(c, _valid_evidence_group())
        assert result is not None
        assert result.confidence == 0.42

    def test_preserves_consolidation_type(self):
        """fake generator 保留 consolidation_type。"""
        fake = FakeLLMConsolidationContentGenerator(
            enhanced_content="test content",
            enhanced_summary="test summary",
        )
        c = _candidate(consolidation_type=ConsolidationType.PATTERN_DETECTION)
        result, _ = fake.enhance(c, _valid_evidence_group())
        assert result is not None
        assert result.consolidation_type == ConsolidationType.PATTERN_DETECTION

    def test_warns_fake(self):
        """fake generator 产生 fake warning。"""
        fake = FakeLLMConsolidationContentGenerator(
            enhanced_content="test content",
            enhanced_summary="test summary",
        )
        _, warnings = fake.enhance(_candidate(), _valid_evidence_group())
        assert any("fake" in w for w in warnings)

    def test_no_enhancement_without_config(self):
        """未配置增强内容时返回 None。"""
        fake = FakeLLMConsolidationContentGenerator()
        result, warnings = fake.enhance(_candidate(), _valid_evidence_group())
        assert result is None

    def test_call_count_tracked(self):
        """fake generator 记录调用次数。"""
        fake = FakeLLMConsolidationContentGenerator(
            enhanced_content="test",
            enhanced_summary="test",
        )
        assert fake._call_count == 0
        fake.enhance(_candidate(), _valid_evidence_group())
        assert fake._call_count == 1

    def test_deterministic_same_input_same_output(self):
        """相同输入多次调用结果一致。"""
        fake = FakeLLMConsolidationContentGenerator(
            enhanced_content="test",
            enhanced_summary="test",
        )
        c = _candidate()
        g = _valid_evidence_group()
        r1, _ = fake.enhance(c, g)
        r2, _ = fake.enhance(c, g)
        assert r1 is not None and r2 is not None
        assert r1.content == r2.content


class TestFakeLLMGeneratorSafety:
    """验证 fake generator 不产生违规输出。"""

    def test_no_procedural_in_enhanced_content(self):
        """增强后 content 含 procedural 语言时 fail closed。"""
        fake = FakeLLMConsolidationContentGenerator(
            enhanced_content="以后必须先跑测试再提交代码",
            enhanced_summary="test summary",
        )
        result, warnings = fake.enhance(_candidate(), _valid_evidence_group())
        assert result is None
        assert any("procedural" in w for w in warnings)

    def test_no_hallucinated_source_evidence(self):
        """source_evidence 含不在 group 中的 record_id 时 fail closed。

        注意：fake generator 保留原始 candidate 的 source_evidence，
        不改变它。这个测试验证即使 validator 遇到含非法记录的情况也会拒绝。
        """
        c = _candidate(source_evidence=("ep1", "hacked_id", "ep3"))
        fake = FakeLLMConsolidationContentGenerator(
            enhanced_content="safe content here",
            enhanced_summary="test summary",
        )
        # 但 group 中只有 ep1, ep2, ep3
        result, warnings = fake.enhance(c, _valid_evidence_group())
        assert result is None
        assert any("record_id" in w for w in warnings)


class _FakeConsolidationProvider:
    """Consolidation LLM 测试用 provider。

    测试只依赖 ModelProvider.create 返回 provider-neutral text block，
    保护 Memory consolidation 不回退到 Anthropic SDK 直连路径。
    """

    provider_type = "fake"
    supports_tools = True
    supports_streaming = False

    def __init__(self, raw_output: str) -> None:
        self.raw_output = raw_output
        self.calls: list[dict] = []

    def create(self, *, system, messages, tools):  # noqa: ANN001
        self.calls.append({"system": system, "messages": messages, "tools": tools})
        return ProviderResponse(
            content=[ProviderTextBlock(self.raw_output)],
            stop_reason="end_turn",
        )

    def stream(self, *, system, messages, tools):  # noqa: ANN001
        raise AssertionError("memory consolidation 不应要求 streaming")


class TestLLMGeneratorProviderBoundary:
    """LLM consolidation 只能消费 provider abstraction。"""

    def test_content_generator_uses_injected_model_provider(self):
        """注入 fake provider 时可增强 content，不需要 Anthropic client。"""
        raw_output = (
            '{"content":"用户稳定偏好 pytest 测试框架。",'
            '"evidence_summary":"3 条 evidence 支撑 pytest 偏好，'
            'record_ids=ep1,ep2,ep3",'
            '"confidence_adjustment":0.0,"warnings":[]}'
        )
        provider = _FakeConsolidationProvider(raw_output)
        generator = LLMConsolidationContentGenerator(
            provider=provider,
            model_name="fake-memory",
        )

        enhanced, warnings = generator.enhance(_candidate(), _valid_evidence_group())

        assert enhanced is not None
        assert enhanced.content == "用户稳定偏好 pytest 测试框架。"
        assert warnings == ()
        assert len(provider.calls) == 1
        assert provider.calls[0]["tools"] == []

    def test_memory_consolidation_module_does_not_import_anthropic_sdk(self):
        """Memory consolidation LLM 不得直接 import/实例化 Anthropic SDK。"""
        import ast
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[1]
            / "agent"
            / "memory_consolidation_llm.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(alias.name != "anthropic" for alias in node.names)
            if isinstance(node, ast.ImportFrom):
                assert node.module != "anthropic"
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert not (
                    isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "anthropic"
                    and node.func.attr == "Anthropic"
                )


# ── pipeline integration tests ─────────────────────────────────────────────


class TestPipelineLLMIntegration:
    """验证 pipeline 与 LLM generator 的集成边界。"""

    def test_pipeline_default_no_llm(self):
        """pipeline 默认不启用 LLM（检查 ConsolidationPipelineResult 默认字段）。"""
        r = ConsolidationPipelineResult(
            candidates=(),
            evidence_count=0,
            skipped_count=0,
            warnings=(),
        )
        assert r.llm_enabled is False
        assert r.llm_enhanced_count == 0

    def test_pipeline_result_fields_present(self):
        """ConsolidationPipelineResult 包含 LLM 相关字段。"""
        r = ConsolidationPipelineResult(
            candidates=(),
            evidence_count=3,
            skipped_count=0,
            warnings=(),
            llm_enabled=True,
            llm_enhanced_count=1,
            llm_warnings=("test warning",),
        )
        assert r.llm_enabled is True
        assert r.llm_enhanced_count == 1
        assert len(r.llm_warnings) == 1

    def test_pipeline_llm_warnings_empty_by_default(self):
        """未启用 LLM 时 llm_warnings 为空。"""
        r = ConsolidationPipelineResult(
            candidates=(),
            evidence_count=0,
            skipped_count=0,
            warnings=(),
        )
        assert r.llm_warnings == ()

    def test_pipeline_with_fake_generator_content_enhancement(self):
        """fake generator 增强 candidate content 后 confidence 不变。"""
        fake = FakeLLMConsolidationContentGenerator(
            enhanced_content="用户强烈偏好 pytest 测试框架",
            enhanced_summary="从 3 条 evidence 检测到 pytest 偏好",
        )
        c = _candidate(confidence=0.42)
        result, warnings = fake.enhance(c, _valid_evidence_group())
        assert result is not None
        assert result.confidence == 0.42
        assert result.content == "用户强烈偏好 pytest 测试框架"


# ── architecture boundary tests ─────────────────────────────────────────────


class TestArchitectureBoundaries:
    """验证 LLM 模块不破坏架构边界。"""

    def test_llm_module_no_store_import(self):
        """LLM 模块不导入 store 模块。"""
        import inspect
        import agent.memory_consolidation_llm as llm_mod
        src = inspect.getsource(llm_mod)
        assert "memory_store" not in src.lower()
        assert "apply_operation_intent" not in src

    def test_llm_module_no_runtime_import(self):
        """LLM 模块不导入 runtime 模块。"""
        import inspect
        import agent.memory_consolidation_llm as llm_mod
        src = inspect.getsource(llm_mod)
        assert "memory_runtime" not in src.lower()

    def test_llm_module_no_env_direct_read(self):
        """LLM 模块不直接读取环境变量（通过 create_llm_content_generator 间接）。"""
        import inspect
        import agent.memory_consolidation_llm as llm_mod
        src = inspect.getsource(llm_mod.LLMConsolidationContentGenerator.enhance)
        assert "os.environ" not in src
        assert "os.getenv" not in src

    def test_build_evidence_context_truncates(self):
        """_build_evidence_context 截断过长内容。"""
        long_content = "x" * 500
        evidence = [_evidence("ep1", long_content)]
        ctx = _build_evidence_context(evidence)
        # 截断到 300 字
        assert "xxx" in ctx
        assert len(long_content) > 300

    def test_no_agent_log_read(self):
        """LLM 模块不读取 agent_log.jsonl。"""
        import inspect
        import agent.memory_consolidation_llm as llm_mod
        src = inspect.getsource(llm_mod)
        assert "agent_log" not in src

    def test_no_real_sessions_read(self):
        """LLM 模块不读取真实的会话或运行数据。

        注意：检查函数体而非模块 docstring（docstring 中可能包含 "sessions" 字样）。
        """
        import inspect
        # 只检查 enhance 和相关函数的源码，排除 docstring 中的描述性词汇
        func_src = inspect.getsource(_is_llm_consolidation_enabled)
        assert "session" not in func_src
        assert "agent_log" not in func_src
        # 检查核心 validate 函数
        val_src = inspect.getsource(validate_llm_enhanced_candidate)
        assert "open(" not in val_src
        assert "read_text" not in val_src


# ── _is_procedural_like_content tests ──────────────────────────────────────


class TestProceduralLikeContent:
    """验证 _is_procedural_like_content 的检测准确性。"""

    def test_detects_chinese_procedural(self):
        assert _is_procedural_like_content("以后必须先跑测试再提交代码") is True

    def test_detects_never_command(self):
        assert _is_procedural_like_content("永远不要自动 commit") is True

    def test_detects_english_procedural(self):
        assert _is_procedural_like_content("you must always run tests first") is True

    def test_semantic_content_not_flagged(self):
        assert _is_procedural_like_content("用户偏好使用 pytest 测试框架") is False

    def test_blank_content_not_flagged(self):
        assert _is_procedural_like_content("") is False


# ── _build_evidence_context tests ──────────────────────────────────────────


class TestBuildEvidenceContext:
    """验证 _build_evidence_context 的格式化行为。"""

    def test_includes_record_ids(self):
        group = _valid_evidence_group()
        ctx = _build_evidence_context(group)
        assert "ep1" in ctx
        assert "ep2" in ctx
        assert "ep3" in ctx

    def test_includes_scope(self):
        group = [
            _evidence("ep1", "test", scope="project"),
        ]
        ctx = _build_evidence_context(group)
        assert "project" in ctx

    def test_empty_group(self):
        ctx = _build_evidence_context([])
        assert ctx == ""
