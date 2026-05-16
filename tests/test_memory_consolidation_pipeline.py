"""Phase 6 detector pipeline integration 的边界测试。

这些测试验证 RFC Phase 6 detector pipeline integration 的只读串联边界，
不验证真实 semantic consolidation quality，不写 memory store，也不接 pending review。

测试覆盖：
- 空 store / 不足 N≥3 / 足够 N≥3 → candidate 生成
- loader → detector 串联正确性
- warnings / skipped_count 传播
- candidate governance 约束（T1/semantic）
- pipeline 只读（不写 store）
- fail-closed 防御
- 确定性（幂等）
"""

import pytest
from pathlib import Path

from agent.memory_consolidation import ConsolidationCandidate, ConsolidationType
from agent.memory_consolidation_engine import DeterministicConsolidationDetector
from agent.memory_consolidation_pipeline import (
    ConsolidationPipelineResult,
    run_consolidation_pipeline,
    _validate_candidate,
)


# ── helpers ──────────────────────────────────────────────────────────────────


def _write_memory_file(
    root: Path,
    rel_path: str,
    sections: list[dict],
) -> Path:
    """在 filesystem store 根目录下写入一个 .md 文件。

    每个 section 是一个 dict，特殊键 '_content' 为 body 文本。
    自动注入 MemoryRecord 强制字段的测试默认值。
    """
    _RECORD_DEFAULTS = {
        "source_summary": "test-source",
        "safety_summary": "safe",
        "audit_id": "audit:test:0000",
    }

    filepath = root / rel_path
    filepath.parent.mkdir(parents=True, exist_ok=True)

    parts: list[str] = []
    for meta in sections:
        for key, default_val in _RECORD_DEFAULTS.items():
            if key not in meta:
                meta[key] = default_val
        content = meta.pop("_content", "")
        lines = ["---"]
        for k, v in meta.items():
            if v is None:
                continue
            if isinstance(v, bool):
                lines.append(f"{k}: {str(v).lower()}")
            elif isinstance(v, (int, float)):
                lines.append(f"{k}: {v}")
            else:
                escaped = str(v).replace('"', '\\"')
                lines.append(f'{k}: "{escaped}"')
        lines.append("---")
        lines.append("")
        lines.append(content)
        parts.append("\n".join(lines))

    filepath.write_text("\n\n---\n\n".join(parts), encoding="utf-8")
    return filepath


def _make_fs_store(tmp_path: Path, sections_by_file: dict[str, list[dict]] | None = None):
    """创建测试用 FilesystemMemoryStore。"""
    from agent.memory_fs_store import FilesystemMemoryStore

    root = tmp_path / "memory_store"
    root.mkdir(parents=True, exist_ok=True)

    if sections_by_file:
        for rel_path, sections in sections_by_file.items():
            _write_memory_file(root, rel_path, sections)

    return FilesystemMemoryStore(root_dir=root)


@pytest.fixture
def empty_store(tmp_path: Path):
    """空 filesystem store（无任何记录）。"""
    return _make_fs_store(tmp_path)


@pytest.fixture
def store_three_episodic(tmp_path: Path):
    """含 3 条同主题 episodic record 的 store。"""
    return _make_fs_store(tmp_path, {
        "episodic/2026-05-13.md": [
            {
                "id": "ep-001",
                "memory_type": "episodic",
                "scope": "user",
                "approval_status": "auto_retained",
                "confidence": 0.75,
                "stability": "stable",
                "created_at": "2026-05-13T10:00:00Z",
                "tags": "pytest,testing",
                "_content": "用户偏好使用 pytest 作为 Python 测试框架",
            },
            {
                "id": "ep-002",
                "memory_type": "episodic",
                "scope": "user",
                "approval_status": "auto_retained",
                "confidence": 0.78,
                "stability": "stable",
                "created_at": "2026-05-13T11:00:00Z",
                "tags": "pytest,testing",
                "_content": "在项目 A 中配置了 pytest 测试套件",
            },
            {
                "id": "ep-003",
                "memory_type": "episodic",
                "scope": "user",
                "approval_status": "auto_retained",
                "confidence": 0.80,
                "stability": "stable",
                "created_at": "2026-05-13T12:00:00Z",
                "tags": "pytest,testing",
                "_content": "迁移项目 B 的 unittest 到 pytest",
            },
        ],
    })


@pytest.fixture
def store_mixed_types(tmp_path: Path):
    """含 episodic + semantic + procedural 混合记录的 store。"""
    return _make_fs_store(tmp_path, {
        "episodic/2026-05-13.md": [
            {
                "id": "ep-a",
                "memory_type": "episodic",
                "scope": "user",
                "approval_status": "auto_retained",
                "stability": "stable",
                "created_at": "2026-05-13T10:00:00Z",
                "tags": "pytest",
                "_content": "episodic event A about pytest",
            },
            {
                "id": "ep-b",
                "memory_type": "episodic",
                "scope": "user",
                "approval_status": "auto_retained",
                "stability": "stable",
                "created_at": "2026-05-13T11:00:00Z",
                "tags": "pytest",
                "_content": "episodic event B about pytest",
            },
            {
                "id": "ep-c",
                "memory_type": "episodic",
                "scope": "user",
                "approval_status": "auto_retained",
                "stability": "stable",
                "created_at": "2026-05-13T12:00:00Z",
                "tags": "pytest",
                "_content": "episodic event C about pytest",
            },
        ],
        "semantic/user_preferences.md": [
            {
                "id": "sem-001",
                "memory_type": "semantic",
                "scope": "user",
                "approval_status": "approved",
                "_content": "用户偏好 pytest",
            },
        ],
        "procedural/learned.md": [
            {
                "id": "proc-001",
                "memory_type": "procedural",
                "scope": "user",
                "approval_status": "approved",
                "_content": "以后必须先跑测试",
            },
        ],
    })


# ── pipeline result 结构 ────────────────────────────────────────────────────


class TestPipelineResult:
    """ConsolidationPipelineResult 数据结构的正确性。"""

    def test_empty_result(self):
        result = ConsolidationPipelineResult(
            candidates=(), evidence_count=0, skipped_count=0, warnings=(),
        )
        assert result.candidate_count == 0
        assert result.has_candidates is False
        assert result.evidence_count == 0

    def test_with_candidates(self):
        from agent.memory_consolidation import ConsolidationCandidate, ConsolidationType

        c = ConsolidationCandidate(
            content="test",
            memory_type="semantic",
            source_evidence=("1", "2", "3"),
            consolidation_type=ConsolidationType.PATTERN_DETECTION,
            confidence=0.8,
            governance_route="T1",
            evidence_summary="test summary",
            created_at="2026-05-13T10:00:00Z",
        )
        result = ConsolidationPipelineResult(
            candidates=(c,), evidence_count=5, skipped_count=2,
            warnings=("w1",), detector_name="DeterministicConsolidationDetector",
        )
        assert result.candidate_count == 1
        assert result.has_candidates is True
        assert result.evidence_count == 5
        assert result.skipped_count == 2
        assert result.detector_name == "DeterministicConsolidationDetector"

    def test_frozen_immutable(self):
        from dataclasses import FrozenInstanceError
        result = ConsolidationPipelineResult(
            candidates=(), evidence_count=0, skipped_count=0, warnings=(),
        )
        with pytest.raises(FrozenInstanceError):
            result.evidence_count = 5  # type: ignore[misc]


# ── 空 / 不足 N≥3 ──────────────────────────────────────────────────────────


class TestPipelineInsufficientEvidence:
    """空 store / 不足 N≥3 evidence → 无 candidate。"""

    def test_empty_store_no_candidates(self, empty_store):
        """空 store 返回空 candidates。"""
        result = run_consolidation_pipeline(empty_store)
        assert result.candidate_count == 0
        assert result.has_candidates is False
        assert result.evidence_count == 0
        assert result.skipped_count == 0

    def test_single_episodic_no_candidate(self, tmp_path):
        """1 条 episodic 不足 N≥3 门槛。"""
        store = _make_fs_store(tmp_path, {
            "episodic/2026-05-13.md": [{
                "id": "ep-solo",
                "memory_type": "episodic",
                "scope": "user",
                "approval_status": "auto_retained",
                "stability": "stable",
                "created_at": "2026-05-13T10:00:00Z",
                "tags": "pytest",
                "_content": "pytest event",
            }],
        })
        result = run_consolidation_pipeline(store)
        assert result.candidate_count == 0
        assert result.evidence_count == 1
        assert result.skipped_count == 0

    def test_two_episodic_no_candidate(self, tmp_path):
        """2 条同主题 episodic 不足 N≥3 门槛。"""
        store = _make_fs_store(tmp_path, {
            "episodic/2026-05-13.md": [
                {
                    "id": "ep-1",
                    "memory_type": "episodic",
                    "scope": "user",
                    "approval_status": "auto_retained",
                    "stability": "stable",
                    "created_at": "2026-05-13T10:00:00Z",
                    "tags": "pytest",
                    "_content": "pytest event A",
                },
                {
                    "id": "ep-2",
                    "memory_type": "episodic",
                    "scope": "user",
                    "approval_status": "auto_retained",
                    "stability": "stable",
                    "created_at": "2026-05-13T11:00:00Z",
                    "tags": "pytest",
                    "_content": "pytest event B",
                },
            ],
        })
        result = run_consolidation_pipeline(store)
        assert result.candidate_count == 0
        assert result.evidence_count == 2


# ── 正常候选生成 ────────────────────────────────────────────────────────────


class TestPipelineCandidateGeneration:
    """3 条同主题 episodic → pattern_detection candidate。"""

    def test_three_same_topic_generates_candidate(self, store_three_episodic):
        """3 条同主题 episodic 满足 N≥3，生成 candidate。"""
        result = run_consolidation_pipeline(store_three_episodic)
        assert result.candidate_count == 1
        assert result.has_candidates is True
        assert result.evidence_count == 3

    def test_candidate_is_semantic_t1(self, store_three_episodic):
        """输出的 candidate 保持 semantic + T1 约束。"""
        result = run_consolidation_pipeline(store_three_episodic)
        c = result.candidates[0]
        assert c.memory_type == "semantic"
        assert c.governance_route == "T1"

    def test_source_evidence_references_original_ids(self, store_three_episodic):
        """source_evidence 正确引用原始 record id。"""
        result = run_consolidation_pipeline(store_three_episodic)
        c = result.candidates[0]
        assert len(c.source_evidence) == 3
        assert set(c.source_evidence) == {"ep-001", "ep-002", "ep-003"}

    def test_confidence_in_range(self, store_three_episodic):
        """confidence 在 [0, 1] 范围内。"""
        result = run_consolidation_pipeline(store_three_episodic)
        assert 0.0 <= result.candidates[0].confidence <= 1.0

    def test_pipeline_uses_detector_name(self, store_three_episodic):
        """pipeline 记录 detector 类名。"""
        result = run_consolidation_pipeline(store_three_episodic)
        assert result.detector_name == "DeterministicConsolidationDetector"


class TestPipelinePreferenceEvolved:
    """这些测试验证 RFC 中 preference_evolved 的最小 deterministic foundation：
    它属于 semantic consolidation 的演化候选，不是 procedural memory，
    不允许 silent retain，也不能绕过 T1 pending review。
    """

    def test_pipeline_routes_preference_evolved_as_semantic_t1(self, tmp_path: Path):
        """filesystem evidence 经过 loader → detector 后保留 preference_evolved 类型。"""
        store = _make_fs_store(tmp_path, {
            "episodic/2026-05-13.md": [
                {
                    "id": "pref-old",
                    "memory_type": "episodic",
                    "scope": "user",
                    "approval_status": "auto_retained",
                    "confidence": 0.82,
                    "stability": "stable",
                    "created_at": "2026-05-01T10:00:00Z",
                    "tags": "testing-preference",
                    "_content": "用户以前喜欢 unittest 作为 Python 测试框架",
                },
                {
                    "id": "pref-new-a",
                    "memory_type": "episodic",
                    "scope": "user",
                    "approval_status": "auto_retained",
                    "confidence": 0.86,
                    "stability": "stable",
                    "created_at": "2026-05-10T10:00:00Z",
                    "tags": "testing-preference",
                    "_content": "用户现在更喜欢 pytest 作为 Python 测试框架",
                },
                {
                    "id": "pref-new-b",
                    "memory_type": "episodic",
                    "scope": "user",
                    "approval_status": "auto_retained",
                    "confidence": 0.88,
                    "stability": "stable",
                    "created_at": "2026-05-12T10:00:00Z",
                    "tags": "testing-preference",
                    "_content": "用户说测试偏好从 unittest 变成 pytest",
                },
            ],
        })

        result = run_consolidation_pipeline(store)

        assert result.candidate_count == 1
        candidate = result.candidates[0]
        assert candidate.consolidation_type == ConsolidationType.PREFERENCE_EVOLVED
        assert candidate.memory_type == "semantic"
        assert candidate.governance_route == "T1"
        assert set(candidate.source_evidence) == {
            "pref-old", "pref-new-a", "pref-new-b",
        }
        assert 0.0 <= candidate.confidence <= 1.0
        assert not (tmp_path / "memory_store" / "semantic").exists()
        assert not (tmp_path / "memory_store" / "procedural").exists()


# ── loader 过滤传播 ─────────────────────────────────────────────────────────


class TestLoaderFilterPropagation:
    """loader 的过滤结果正确传播到 pipeline。"""

    def test_non_episodic_filtered_before_detector(self, store_mixed_types):
        """semantic/procedural 被 loader 过滤，只有 episodic 进入 detector。"""
        result = run_consolidation_pipeline(store_mixed_types)
        # 3 条 episodic 满足 N≥3，1 条 semantic + 1 条 procedural 被 loader 跳过
        assert result.evidence_count == 3
        assert result.skipped_count == 2
        assert result.candidate_count == 1

    def test_skipped_count_propagates(self, store_mixed_types):
        """loader 的 skipped_count 传到 pipeline result。"""
        result = run_consolidation_pipeline(store_mixed_types)
        assert result.skipped_count == 2

    def test_loader_warnings_propagate(self, tmp_path):
        """loader 的 warning 传到 pipeline result。"""
        store = _make_fs_store(tmp_path, {
            "semantic/user_preferences.md": [{
                "id": "sem-x",
                "memory_type": "semantic",
                "scope": "user",
                "approval_status": "approved",
                "_content": "non-episodic",
            }],
        })
        result = run_consolidation_pipeline(store)
        assert result.skipped_count == 1
        assert any("semantic" in w for w in result.warnings)


# ── pipeline 只读 ───────────────────────────────────────────────────────────


class TestPipelineReadOnly:
    """pipeline 不写 store，不创建新文件。"""

    def test_store_unchanged_after_pipeline(self, store_three_episodic):
        """pipeline 运行后 store 内容不变。"""
        record_count_before = len(store_three_episodic.list_records())
        index_before = dict(store_three_episodic._index) if hasattr(store_three_episodic, "_index") else None

        run_consolidation_pipeline(store_three_episodic)

        assert len(store_three_episodic.list_records()) == record_count_before
        if index_before is not None:
            assert store_three_episodic._index == index_before

    def test_no_new_files_created(self, store_three_episodic):
        """pipeline 不在 store 目录下创建新文件。"""
        files_before = set(
            str(p.relative_to(store_three_episodic.root_dir))
            for p in store_three_episodic.root_dir.rglob("*")
            if p.is_file()
        )
        run_consolidation_pipeline(store_three_episodic)
        files_after = set(
            str(p.relative_to(store_three_episodic.root_dir))
            for p in store_three_episodic.root_dir.rglob("*")
            if p.is_file()
        )
        assert files_after == files_before

    def test_no_pending_proposal_created(self, tmp_path):
        """pipeline 不创建 _pending 目录或 proposal 文件。"""
        store = _make_fs_store(tmp_path, {
            "episodic/2026-05-13.md": [
                {
                    "id": f"ep-{i}",
                    "memory_type": "episodic",
                    "scope": "user",
                    "approval_status": "auto_retained",
                    "stability": "stable",
                    "created_at": f"2026-05-13T1{i}:00:00Z",
                    "tags": "pytest",
                    "_content": f"pytest event {i}",
                }
                for i in range(3)
            ],
        })
        run_consolidation_pipeline(store)
        pending_dir = store.root_dir / "_pending"
        assert not pending_dir.exists()


# ── 无 LLM / 无 runtime import ──────────────────────────────────────────────


class TestNoLLMOrRuntime:
    """pipeline 不 import LLM / runtime 模块。"""

    def test_no_llm_import(self):
        """pipeline 不 import anthropic / openai。"""
        import ast
        with open("agent/memory_consolidation_pipeline.py") as f:
            tree = ast.parse(f.read())
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module)
        assert "anthropic" not in imports
        assert "openai" not in imports

    def test_no_runtime_import(self):
        """pipeline 不 import runtime / session / core 模块。"""
        import ast
        with open("agent/memory_consolidation_pipeline.py") as f:
            tree = ast.parse(f.read())
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module)
        forbidden = {"agent.runtime", "agent.session", "agent.core", "agent.memory_runtime"}
        assert not (imports & forbidden), f"Forbidden imports: {imports & forbidden}"


# ── fail-closed 防御 ────────────────────────────────────────────────────────


class TestFailClosed:
    """_validate_candidate 防御层：无效 candidate 被丢弃并产生 warning。

    ConsolidationCandidate 的 __post_init__ 已在构造时执行强制约束验证。
    为测试 pipeline 层 defense-in-depth，使用 object.__setattr__ 绕过 frozen
    dataclass 的初始化校验，构造"本不应存在"的非法 candidate。
    """

    def _make_valid_candidate(self, **overrides) -> ConsolidationCandidate:
        defaults = {
            "content": "test content",
            "memory_type": "semantic",
            "source_evidence": ("ep-a", "ep-b", "ep-c"),
            "consolidation_type": ConsolidationType.PATTERN_DETECTION,
            "confidence": 0.8,
            "governance_route": "T1",
            "evidence_summary": "test summary",
            "created_at": "2026-05-13T10:00:00Z",
        }
        defaults.update(overrides)
        return ConsolidationCandidate(**defaults)

    def _mutate(self, candidate: ConsolidationCandidate, **kwargs) -> ConsolidationCandidate:
        """绕过 frozen 校验修改 candidate 字段（仅用于测试防御层）。"""
        for key, val in kwargs.items():
            object.__setattr__(candidate, key, val)
        return candidate

    def test_valid_candidate_passes(self):
        """正常 candidate 通过验证。"""
        c = self._make_valid_candidate()
        assert _validate_candidate(c) is None

    def test_non_semantic_rejected(self):
        """memory_type 非 semantic → 失败。"""
        c = self._make_valid_candidate()
        self._mutate(c, memory_type="episodic")
        violation = _validate_candidate(c)
        assert violation is not None
        assert "semantic" in violation

    def test_non_t1_rejected(self):
        """governance_route 非 T1 → 失败。"""
        c = self._make_valid_candidate()
        self._mutate(c, governance_route="T2")
        violation = _validate_candidate(c)
        assert violation is not None
        assert "T1" in violation

    def test_confidence_out_of_range_rejected(self):
        """confidence 超出 [0, 1] → 失败。"""
        c = self._make_valid_candidate()
        self._mutate(c, confidence=1.5)
        violation = _validate_candidate(c)
        assert violation is not None
        assert "1.5" in violation

    def test_insufficient_source_evidence_rejected(self):
        """source_evidence 不足 3 条 → 失败。"""
        c = self._make_valid_candidate()
        self._mutate(c, source_evidence=("ep-a", "ep-b"))
        violation = _validate_candidate(c)
        assert violation is not None
        assert "N≥3" in violation

    def test_empty_content_rejected(self):
        """content 为空 → 失败。"""
        c = self._make_valid_candidate()
        self._mutate(c, content="")
        violation = _validate_candidate(c)
        assert violation is not None

    def test_pipeline_drops_invalid_candidate_with_warning(self, store_three_episodic):
        """通过自定义 detector 模拟无效输出，验证 pipeline 丢弃并 warning。

        使用 object.__setattr__ 绕过 ConsolidationCandidate 初始化校验，
        构造 "本不应存在" 的非法 candidate，验证 pipeline 层能正确 fail-closed。
        """

        class BuggyDetector:
            """模拟有 bug 的 detector：输出包含被篡改的非 semantic candidate。"""

            def detect(self, evidence_list):
                valid = ConsolidationCandidate(
                    content="valid",
                    memory_type="semantic",
                    source_evidence=("1", "2", "3"),
                    consolidation_type=ConsolidationType.PATTERN_DETECTION,
                    confidence=0.8,
                    governance_route="T1",
                    evidence_summary="valid summary",
                    created_at="2026-05-13T10:00:00Z",
                )
                # 先构造有效 candidate，再篡改为非法
                invalid = ConsolidationCandidate(
                    content="corrupted",
                    memory_type="semantic",  # 先正确构造
                    source_evidence=("4", "5", "6"),
                    consolidation_type=ConsolidationType.PATTERN_DETECTION,
                    confidence=0.8,
                    governance_route="T1",
                    evidence_summary="corrupted summary",
                    created_at="2026-05-13T10:00:00Z",
                )
                object.__setattr__(invalid, "memory_type", "procedural")
                return [valid, invalid]

        result = run_consolidation_pipeline(store_three_episodic, detector=BuggyDetector())
        # 只保留 valid candidate，invalid 被丢弃
        assert result.candidate_count == 1
        assert result.candidates[0].content == "valid"
        # 产生 warning
        assert any("procedural" in w for w in result.warnings)
        # detector_name 反映自定义 detector
        assert result.detector_name == "BuggyDetector"


# ── 确定性（幂等）───────────────────────────────────────────────────────────


class TestDeterministic:
    """pipeline 确定性：相同 store 多次运行结果一致。"""

    def test_idempotent(self, store_three_episodic):
        """相同 store 多次运行产出相同结果。"""
        r1 = run_consolidation_pipeline(store_three_episodic)
        r2 = run_consolidation_pipeline(store_three_episodic)
        assert r1.candidate_count == r2.candidate_count
        assert r1.evidence_count == r2.evidence_count
        assert r1.skipped_count == r2.skipped_count
        for a, b in zip(r1.candidates, r2.candidates):
            assert a.content == b.content
            assert a.confidence == b.confidence
            assert a.consolidation_type == b.consolidation_type
            assert a.source_evidence == b.source_evidence


# ── warnings 不含敏感信息 ───────────────────────────────────────────────────


class TestWarningSafety:
    """pipeline warnings 不包含 secret 或 memory 原文长文本。"""

    def test_warnings_no_long_content(self, store_mixed_types):
        """warning 不包含完整 memory content。"""
        result = run_consolidation_pipeline(store_mixed_types)
        for w in result.warnings:
            # warning 不应包含中文长文本片段
            assert "偏好" not in w
            assert "必须先跑" not in w

    def test_warnings_no_secret_patterns(self, store_three_episodic):
        """warning 不含 API key / token 模式。"""
        result = run_consolidation_pipeline(store_three_episodic)
        for w in result.warnings:
            assert "sk-" not in w.lower() or "skip" in w.lower()
            assert "api_key" not in w.lower()
            assert "token" not in w.lower()


# ── custom detector ─────────────────────────────────────────────────────────


class TestCustomDetector:
    """支持注入自定义 detector。"""

    def test_custom_detector_used(self, store_three_episodic):
        """注入自定义 detector 实例被使用。"""
        custom = DeterministicConsolidationDetector()
        result = run_consolidation_pipeline(store_three_episodic, detector=custom)
        assert result.candidate_count == 1

    def test_none_detector_creates_default(self, store_three_episodic):
        """不传 detector 时自动创建默认实例。"""
        result = run_consolidation_pipeline(store_three_episodic)
        assert result.detector_name == "DeterministicConsolidationDetector"
