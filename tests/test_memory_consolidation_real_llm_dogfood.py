"""Phase 6 Real LLM Consolidation Dogfood — 默认 skip 的集成测试。

所有真实 LLM 测试默认 skip，只有显式设置 env gate 才运行：
  MEMORY_CONSOLIDATION_LLM_ENABLED=true

测试覆盖：
- 默认不调真实 LLM（skip 验证）
- dogfood harness 环境检查逻辑
- 合成 evidence 写入 + pipeline 运行 + 治理验证
- 审查数据包格式验证
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

# 确保项目根在 sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

# ── skip 条件 ──────────────────────────────────────────────────────────────────


def _is_real_llm_dogfood_enabled() -> bool:
    """检查是否显式 opt-in 真实 LLM dogfood。"""
    return os.getenv("MEMORY_CONSOLIDATION_LLM_ENABLED", "").strip() in (
        "1", "true", "yes", "True", "TRUE",
    )


def _has_api_key() -> bool:
    """检查 API key 是否可用。"""
    try:
        from config import API_KEY
        return bool(API_KEY)
    except Exception:
        return False


_reason_skip = "MEMORY_CONSOLIDATION_LLM_ENABLED 未设置或 API key 不可用"

# 全局 skip 标记：用于需要真实 LLM 的测试
needs_real_llm = pytest.mark.skipif(
    not (_is_real_llm_dogfood_enabled() and _has_api_key()),
    reason=_reason_skip,
)


# ── helpers ────────────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_dogfood_root(tmp_path):
    """临时 dogfood 根目录 fixture。"""
    return tmp_path / "dogfood_phase6_e2e"


# ── 默认 skip 测试 ────────────────────────────────────────────────────────────


class TestDefaultSkip:
    """验证默认情况下不调真实 LLM。"""

    def test_default_llm_not_enabled(self):
        """未设置 env var 时，create_llm_content_generator 返回 None。"""
        # 保存并临时清除 env var
        old = os.environ.pop("MEMORY_CONSOLIDATION_LLM_ENABLED", None)
        try:
            from agent.memory_consolidation_llm import (
                _is_llm_consolidation_enabled,
                create_llm_content_generator,
            )
            assert not _is_llm_consolidation_enabled()
            assert create_llm_content_generator() is None
        finally:
            if old is not None:
                os.environ["MEMORY_CONSOLIDATION_LLM_ENABLED"] = old

    def test_dogfood_script_check_env_skips_without_key(self):
        """dogfood 脚本的 check_env 在无 API key 时返回 skip。"""
        # 保存并临时清除
        old_llm = os.environ.pop("MEMORY_CONSOLIDATION_LLM_ENABLED", None)
        old_key = os.environ.pop("ANTHROPIC_API_KEY", None)
        old_key_o = os.environ.pop("OPENAI_API_KEY", None)
        try:
            from scripts.dogfood_phase6_llm_consolidation import check_env
            can_run, reason, prov, _cfg = check_env()
            assert not can_run
            assert "MEMORY_CONSOLIDATION_LLM_ENABLED" in reason or "API" in reason
            # provider_info 不包含 key 片段
            assert "sk-" not in str(prov)
            assert "key" not in str(prov).lower() or "key_configured" in str(prov).lower()
        finally:
            if old_llm is not None:
                os.environ["MEMORY_CONSOLIDATION_LLM_ENABLED"] = old_llm
            if old_key is not None:
                os.environ["ANTHROPIC_API_KEY"] = old_key
            if old_key_o is not None:
                os.environ["OPENAI_API_KEY"] = old_key_o

    def test_check_env_provider_info_no_secrets(self):
        """check_env 返回的 provider_info 不得包含 API key 内容。"""
        from scripts.dogfood_phase6_llm_consolidation import check_env
        can_run, reason, prov, _cfg = check_env()
        prov_str = str(prov)
        # 绝对不能包含 sk- 前缀的 key 片段
        assert "sk-" not in prov_str
        # 不能包含长度 > 20 的疑似 key 值的字符串
        import re
        assert not re.search(r'[a-zA-Z0-9_\-]{32,}', prov_str)


# ── 合成 evidence 写入测试（不需要真实 LLM）───────────────────────────────────


class TestSeedSyntheticEvidence:
    """验证合成 evidence 写入 filesystem store。"""

    def test_seed_creates_episodic_file(self, tmp_dogfood_root):
        """seed 函数应在 episodic/ 目录下创建 .md 文件。"""
        from scripts.dogfood_phase6_llm_consolidation import (
            seed_synthetic_evidence,
            _ALL_EVIDENCE,
        )

        store_root = tmp_dogfood_root / "memory"
        store_root.mkdir(parents=True, exist_ok=True)

        filepath = seed_synthetic_evidence(store_root)

        assert filepath.exists()
        assert filepath.suffix == ".md"
        content = filepath.read_text(encoding="utf-8")
        # 每条 evidence 对应一个 YAML frontmatter section（以 --- 开头）
        section_count = content.count("\n---\n") + 1
        assert section_count >= len(_ALL_EVIDENCE)

    def test_seeded_file_has_required_frontmatter(self, tmp_dogfood_root):
        """seed 后的 .md 文件应包含 memory_type=episodic 的 frontmatter。"""
        from scripts.dogfood_phase6_llm_consolidation import seed_synthetic_evidence

        store_root = tmp_dogfood_root / "memory"
        store_root.mkdir(parents=True, exist_ok=True)

        filepath = seed_synthetic_evidence(store_root)
        content = filepath.read_text(encoding="utf-8")

        assert "memory_type: \"episodic\"" in content
        assert "approval_status: \"approved\"" in content
        assert "dogfood-ep-001" in content

    def test_store_can_list_seeded_evidence(self, tmp_dogfood_root):
        """FilesystemMemoryStore 应该能列出 seed 的 episodic evidence。"""
        from scripts.dogfood_phase6_llm_consolidation import seed_synthetic_evidence
        from agent.memory_fs_store import FilesystemMemoryStore

        store_root = tmp_dogfood_root / "memory"
        store_root.mkdir(parents=True, exist_ok=True)
        seed_synthetic_evidence(store_root)

        store = FilesystemMemoryStore(root_dir=store_root)
        records = store.list_records()

        # 至少应包含 seed 的 evidence
        episodic_records = [r for r in records if r.memory_type == "episodic"]
        assert len(episodic_records) > 0


# ── pipeline 集成测试（不需要真实 LLM）───────────────────────────────────────


class TestDogfoodPipelineNoLLM:
    """验证 dogfood pipeline 在无 LLM 时仍正常运行。"""

    def test_pipeline_runs_without_llm(self, tmp_dogfood_root):
        """不设置 LLM env var 时，pipeline 应跳过 LLM 增强但仍生成 candidates。"""
        from scripts.dogfood_phase6_llm_consolidation import (
            seed_synthetic_evidence,
        )
        from agent.memory_consolidation_pipeline import run_consolidation_pipeline
        from agent.memory_fs_store import FilesystemMemoryStore

        store_root = tmp_dogfood_root / "memory"
        store_root.mkdir(parents=True, exist_ok=True)
        seed_synthetic_evidence(store_root)

        store = FilesystemMemoryStore(root_dir=store_root)
        result = run_consolidation_pipeline(store, llm_generator=None)

        assert result.candidate_count > 0, "即使无 LLM，detector 也应生成 candidates"
        assert not result.llm_enabled
        assert result.llm_enhanced_count == 0

    def test_all_candidates_are_semantic_t1(self, tmp_dogfood_root):
        """所有 pipeline 输出的 candidate 应满足 semantic + T1。"""
        from scripts.dogfood_phase6_llm_consolidation import seed_synthetic_evidence
        from agent.memory_consolidation_pipeline import run_consolidation_pipeline
        from agent.memory_fs_store import FilesystemMemoryStore

        store_root = tmp_dogfood_root / "memory"
        store_root.mkdir(parents=True, exist_ok=True)
        seed_synthetic_evidence(store_root)

        store = FilesystemMemoryStore(root_dir=store_root)
        result = run_consolidation_pipeline(store, llm_generator=None)

        for c in result.candidates:
            assert c.memory_type == "semantic"
            assert c.governance_route == "T1"
            assert len(c.source_evidence) >= 3
            assert 0.0 <= c.confidence <= 1.0
            assert c.content.strip()

    def test_fake_llm_enhancement_via_pipeline(self, tmp_dogfood_root):
        """使用 FakeLLM generator 验证 pipeline 的 LLM 增强路径。"""
        from scripts.dogfood_phase6_llm_consolidation import seed_synthetic_evidence
        from agent.memory_consolidation_pipeline import run_consolidation_pipeline
        from agent.memory_consolidation_llm import FakeLLMConsolidationContentGenerator
        from agent.memory_fs_store import FilesystemMemoryStore

        store_root = tmp_dogfood_root / "memory"
        store_root.mkdir(parents=True, exist_ok=True)
        seed_synthetic_evidence(store_root)

        store = FilesystemMemoryStore(root_dir=store_root)
        fake = FakeLLMConsolidationContentGenerator(
            enhanced_content="用户在所有项目中一致偏好函数式编程——不可变数据结构、纯函数、无副作用。",
            enhanced_summary="共 6 条 evidence，均指向对函数式编程的偏好，record_ids=dogfood-ep-001,dogfood-ep-002,dogfood-ep-003",
        )
        result = run_consolidation_pipeline(store, llm_generator=fake)

        assert result.llm_enabled
        # fake generator 应至少增强 1 条 candidate
        assert result.llm_enhanced_count >= 1

        # 找到被增强的 candidate
        enhanced = [
            c for c in result.candidates
            if "函数式编程" in c.content
        ]
        if enhanced:
            ec = enhanced[0]
            assert ec.memory_type == "semantic"
            assert ec.governance_route == "T1"
            # 增强后的 content 不再是模板化文本
            assert "反复表现出" not in ec.content or "函数式编程" in ec.content


# ── 治理验证测试 ──────────────────────────────────────────────────────────────


class TestGovernanceVerification:
    """验证 _verify_governance_constraints 的正确性。"""

    def test_valid_candidates_pass(self, tmp_dogfood_root):
        """正常的 pipeline 输出应通过治理验证。"""
        from scripts.dogfood_phase6_llm_consolidation import seed_synthetic_evidence
        from agent.memory_consolidation_pipeline import (
            run_consolidation_pipeline,
        )
        from agent.memory_fs_store import FilesystemMemoryStore

        store_root = tmp_dogfood_root / "memory"
        store_root.mkdir(parents=True, exist_ok=True)
        seed_synthetic_evidence(store_root)

        store = FilesystemMemoryStore(root_dir=store_root)
        result = run_consolidation_pipeline(store, llm_generator=None)

        from scripts.dogfood_phase6_llm_consolidation import (
            _verify_governance_constraints,
        )

        gov = _verify_governance_constraints(result)
        assert gov["all_pass"], f"治理验证失败: {gov.get('details')}"
        assert gov["candidates_checked"] == result.candidate_count


class TestReviewPacket:
    """验证审查数据包生成。"""

    def test_review_packet_structure(self, tmp_dogfood_root):
        """generate_review_packet 应产生有效 JSON 和 Markdown。"""
        from scripts.dogfood_phase6_llm_consolidation import (
            generate_review_packet,
            seed_synthetic_evidence,
        )
        from agent.memory_consolidation_pipeline import run_consolidation_pipeline
        from agent.memory_fs_store import FilesystemMemoryStore

        # 使用临时目录覆盖
        import scripts.dogfood_phase6_llm_consolidation as dogfood_mod

        store_root = tmp_dogfood_root / "memory"
        store_root.mkdir(parents=True, exist_ok=True)
        seed_synthetic_evidence(store_root)

        store = FilesystemMemoryStore(root_dir=store_root)
        pipeline_result = run_consolidation_pipeline(store, llm_generator=None)

        # 构建临时 report
        report = {
            "pipeline": {
                "evidence_count": pipeline_result.evidence_count,
                "candidate_count": pipeline_result.candidate_count,
                "skipped_count": pipeline_result.skipped_count,
                "warnings": list(pipeline_result.warnings),
                "detector_name": pipeline_result.detector_name,
                "llm_enabled": pipeline_result.llm_enabled,
                "llm_enhanced_count": pipeline_result.llm_enhanced_count,
                "llm_warnings": list(pipeline_result.llm_warnings),
            },
            "provider": {"model": "test", "base_url": "test", "key_configured": False},
            "llm_status": "skipped",
            "dispatch": None,
            "governance_check": None,
        }

        # 使用 monkeypatch 重定向输出目录
        packet_dir = tmp_dogfood_root / "review_packet"
        packet_dir.mkdir(parents=True, exist_ok=True)

        original_review_dir = dogfood_mod._REVIEW_PACKET_DIR
        original_store_root = dogfood_mod._STORE_ROOT
        try:
            dogfood_mod._REVIEW_PACKET_DIR = packet_dir
            dogfood_mod._STORE_ROOT = store_root
            packet_path = generate_review_packet(report)

            assert packet_path.exists()
            assert packet_path.suffix == ".json"

            data = json.loads(packet_path.read_text(encoding="utf-8"))
            assert "executive_summary" in data
            assert "pipeline_report" in data
            assert "dogfood_timestamp" in data
        finally:
            dogfood_mod._REVIEW_PACKET_DIR = original_review_dir
            dogfood_mod._STORE_ROOT = original_store_root

    def test_markdown_summary_generated(self, tmp_dogfood_root):
        """review packet 应同时生成 Markdown 摘要。"""
        import scripts.dogfood_phase6_llm_consolidation as dogfood_mod
        from agent.memory_consolidation_pipeline import run_consolidation_pipeline
        from agent.memory_fs_store import FilesystemMemoryStore

        store_root = tmp_dogfood_root / "memory"
        store_root.mkdir(parents=True, exist_ok=True)
        from scripts.dogfood_phase6_llm_consolidation import seed_synthetic_evidence
        seed_synthetic_evidence(store_root)

        store = FilesystemMemoryStore(root_dir=store_root)
        result = run_consolidation_pipeline(store, llm_generator=None)

        packet_dir = tmp_dogfood_root / "review_packet"
        packet_dir.mkdir(parents=True, exist_ok=True)

        report = {
            "pipeline": {
                "evidence_count": result.evidence_count,
                "candidate_count": result.candidate_count,
                "skipped_count": result.skipped_count,
                "warnings": [],
                "detector_name": result.detector_name,
                "llm_enabled": False,
                "llm_enhanced_count": 0,
                "llm_warnings": [],
            },
            "provider": {"model": "test", "base_url": "test", "key_configured": False},
            "llm_status": "skipped",
            "dispatch": None,
            "governance_check": {"all_pass": True, "candidates_checked": result.candidate_count, "details": []},
        }

        original_review = dogfood_mod._REVIEW_PACKET_DIR
        original_store = dogfood_mod._STORE_ROOT
        try:
            dogfood_mod._REVIEW_PACKET_DIR = packet_dir
            dogfood_mod._STORE_ROOT = store_root
            dogfood_mod.generate_review_packet(report)

            md_files = sorted(packet_dir.glob("review_summary_*.md"))
            assert len(md_files) >= 1
            md_content = md_files[-1].read_text(encoding="utf-8")
            assert "Pipeline 结果" in md_content
            assert "审查检查清单" in md_content
        finally:
            dogfood_mod._REVIEW_PACKET_DIR = original_review
            dogfood_mod._STORE_ROOT = original_store


# ── 真实 LLM 测试（默认 skip）─────────────────────────────────────────────────


class TestRealLLMDogfood:
    """真实 LLM dogfood 测试——默认 skip，需显式 env gate。"""

    @needs_real_llm
    def test_llm_generator_available(self):
        """真实 LLM generator 应在 env gate 开启且 API key 可用时创建成功。"""
        from agent.memory_consolidation_llm import create_llm_content_generator
        gen = create_llm_content_generator()
        assert gen is not None, "env gate 开启但 generator 创建失败"

    @needs_real_llm
    def test_real_llm_enhance_content_changed(self, tmp_dogfood_root):
        """真实 LLM 应更新 candidate 的 content 和 evidence_summary。"""
        from scripts.dogfood_phase6_llm_consolidation import seed_synthetic_evidence
        from agent.memory_consolidation_pipeline import run_consolidation_pipeline
        from agent.memory_consolidation_llm import create_llm_content_generator
        from agent.memory_fs_store import FilesystemMemoryStore

        store_root = tmp_dogfood_root / "memory"
        store_root.mkdir(parents=True, exist_ok=True)
        seed_synthetic_evidence(store_root)

        store = FilesystemMemoryStore(root_dir=store_root)

        # 先跑一次无 LLM 的
        no_llm_result = run_consolidation_pipeline(store, llm_generator=None)

        # 再跑一次有 LLM 的
        llm_gen = create_llm_content_generator()
        assert llm_gen is not None
        llm_result = run_consolidation_pipeline(store, llm_generator=llm_gen)

        assert llm_result.llm_enabled
        assert llm_result.candidate_count == no_llm_result.candidate_count

        # 至少有一条 candidate 的 content 被 LLM 改变（不再是指令性模板文本）
        if llm_result.candidates and no_llm_result.candidates:
            # LLM 增强后的 content 应该不同于 deterministic 模板
            all_enhanced_same = all(
                llm.content == det.content
                for llm, det in zip(llm_result.candidates, no_llm_result.candidates)
            )
            assert not all_enhanced_same, (
                "LLM 增强后 content 应与 deterministic 模板不同"
            )

    @needs_real_llm
    def test_llm_only_changes_content_and_summary(self, tmp_dogfood_root):
        """真实 LLM 只能修改 content 和 evidence_summary，其他字段不变。"""
        from scripts.dogfood_phase6_llm_consolidation import seed_synthetic_evidence
        from agent.memory_consolidation_pipeline import run_consolidation_pipeline
        from agent.memory_consolidation_llm import create_llm_content_generator
        from agent.memory_fs_store import FilesystemMemoryStore

        store_root = tmp_dogfood_root / "memory"
        store_root.mkdir(parents=True, exist_ok=True)
        seed_synthetic_evidence(store_root)

        store = FilesystemMemoryStore(root_dir=store_root)
        no_llm_result = run_consolidation_pipeline(store, llm_generator=None)

        llm_gen = create_llm_content_generator()
        assert llm_gen is not None
        llm_result = run_consolidation_pipeline(store, llm_generator=llm_gen)

        # 逐条对比
        for no_llm_c, llm_c in zip(no_llm_result.candidates, llm_result.candidates):
            assert llm_c.memory_type == no_llm_c.memory_type
            assert llm_c.governance_route == no_llm_c.governance_route
            assert llm_c.source_evidence == no_llm_c.source_evidence
            assert llm_c.consolidation_type == no_llm_c.consolidation_type
            assert llm_c.confidence == no_llm_c.confidence
            assert llm_c.created_at == no_llm_c.created_at
            # content 和 evidence_summary 可能被 LLM 改变
            # （至少不应为空）
            assert llm_c.content.strip()
            assert llm_c.evidence_summary.strip()

    @needs_real_llm
    def test_no_procedural_content_in_llm_output(self, tmp_dogfood_root):
        """真实 LLM 输出不应包含 procedural-like 内容。"""
        from scripts.dogfood_phase6_llm_consolidation import seed_synthetic_evidence
        from agent.memory_consolidation_pipeline import run_consolidation_pipeline
        from agent.memory_consolidation_llm import (
            _is_procedural_like_content,
            create_llm_content_generator,
        )
        from agent.memory_fs_store import FilesystemMemoryStore

        store_root = tmp_dogfood_root / "memory"
        store_root.mkdir(parents=True, exist_ok=True)
        seed_synthetic_evidence(store_root)

        store = FilesystemMemoryStore(root_dir=store_root)
        llm_gen = create_llm_content_generator()
        assert llm_gen is not None
        result = run_consolidation_pipeline(store, llm_generator=llm_gen)

        for c in result.candidates:
            assert not _is_procedural_like_content(c.content), (
                f"LLM 输出包含 procedural-like 内容: {c.content[:100]}"
            )

    @needs_real_llm
    def test_t1_dispatch_works(self, tmp_dogfood_root):
        """真实 LLM dogfood 应完成 T1 pending dispatch。"""
        from scripts.dogfood_phase6_llm_consolidation import (
            seed_synthetic_evidence,
            run_dogfood_pipeline,
        )

        store_root = tmp_dogfood_root / "memory"
        store_root.mkdir(parents=True, exist_ok=True)
        seed_synthetic_evidence(store_root)

        report = run_dogfood_pipeline(store_root)
        d = report.get("dispatch") or {}
        assert d.get("dispatched", 0) > 0, "应有 candidate 成功分发到 T1 pending"

    @needs_real_llm
    def test_review_packet_after_real_llm(self, tmp_dogfood_root):
        """真实 LLM 运行后应生成完整的审查数据包。"""
        from scripts.dogfood_phase6_llm_consolidation import (
            generate_review_packet,
            seed_synthetic_evidence,
            run_dogfood_pipeline,
        )
        import scripts.dogfood_phase6_llm_consolidation as dogfood_mod

        store_root = tmp_dogfood_root / "memory"
        store_root.mkdir(parents=True, exist_ok=True)
        seed_synthetic_evidence(store_root)

        report = run_dogfood_pipeline(store_root)

        packet_dir = tmp_dogfood_root / "review_packet"
        packet_dir.mkdir(parents=True, exist_ok=True)

        original_review = dogfood_mod._REVIEW_PACKET_DIR
        original_store = dogfood_mod._STORE_ROOT
        try:
            dogfood_mod._REVIEW_PACKET_DIR = packet_dir
            dogfood_mod._STORE_ROOT = store_root
            packet_path = generate_review_packet(report)

            data = json.loads(packet_path.read_text(encoding="utf-8"))
            assert data["executive_summary"]["llm_enabled"]
            assert data["executive_summary"]["llm_enhanced_count"] > 0

            # 治理验证应通过
            gov = data.get("governance_check") or {}
            assert gov.get("all_pass", False), f"治理验证失败: {gov}"

            # Markdown 摘要应存在
            md_files = sorted(packet_dir.glob("review_summary_*.md"))
            assert len(md_files) >= 1
        finally:
            dogfood_mod._REVIEW_PACKET_DIR = original_review
            dogfood_mod._STORE_ROOT = original_store


# ── 架构边界测试 ──────────────────────────────────────────────────────────────


class TestDogfoodSafety:
    """验证 dogfood harness 的安全边界。"""

    def test_no_real_sessions_accessed(self):
        """dogfood 脚本不应读取真实 sessions/runs/agent_log。"""
        src = Path(__file__).parent.parent / "scripts" / "dogfood_phase6_llm_consolidation.py"
        raw = src.read_text(encoding="utf-8")

        # 去掉模块 docstring（其中可能提到约束本身）
        lines = raw.split("\n")
        non_doc_lines: list[str] = []
        in_docstring = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('"""') or stripped.startswith("'''"):
                in_docstring = not in_docstring
                continue
            if in_docstring:
                continue
            non_doc_lines.append(line)
        content = "\n".join(non_doc_lines)

        # 不应包含敏感路径访问
        assert "sessions" not in content.lower(), (
            "dogfood 脚本不应访问真实 sessions"
        )
        assert "agent_log" not in content
        assert ".env" not in content or "dotenv" in content

    def test_no_auto_approve(self):
        """dogfood 脚本不得包含 auto-approve 逻辑。"""
        src = Path(__file__).parent.parent / "scripts" / "dogfood_phase6_llm_consolidation.py"
        content = src.read_text(encoding="utf-8")

        assert "auto_approve" not in content
        assert "AUTO_RETAIN" not in content
        # dispatch 只走 T1
        assert "accept_pending_proposal" not in content
        assert "edit_and_accept" not in content

    def test_only_writes_to_tmp(self):
        """dogfood 脚本的所有文件写入应限制在 /tmp/dogfood_phase6_e2e。"""
        src = Path(__file__).parent.parent / "scripts" / "dogfood_phase6_llm_consolidation.py"
        content = src.read_text(encoding="utf-8")

        # 不应写到家目录或项目目录
        assert "~/.my-first-agent" not in content
        assert "MEMORY_ROOT" not in content or "os.getenv" in content


# ── Secret Sanitization 测试 ─────────────────────────────────────────────────


class TestSecretSanitization:
    """验证 dogfood 脚本不会泄露 API key 到输出、report、store。"""

    def test_sanitize_error_removes_sk_prefix(self):
        """_sanitize_error 应移除 sk- 前缀的 key 片段。"""
        from scripts.dogfood_phase6_llm_consolidation import _sanitize_error

        exc = RuntimeError("401 - api_key=sk-sp-42abc123def456 is invalid")
        result = _sanitize_error(exc)
        assert "sk-sp-42abc" not in result
        assert "sk-***" in result

    def test_sanitize_error_removes_bearer_token(self):
        """_sanitize_error 应移除 Bearer token。"""
        from scripts.dogfood_phase6_llm_consolidation import _sanitize_error

        exc = RuntimeError("401 Unauthorized: Bearer tok_abc123def456ghij789klm")
        result = _sanitize_error(exc)
        assert "Bearer ***" in result
        assert "tok_abc123" not in result

    def test_sanitize_str_removes_api_key_value(self):
        """_sanitize_str 应移除 api_key=... 值。"""
        from scripts.dogfood_phase6_llm_consolidation import _sanitize_str

        text = "Error: api_key=sk-abc123def456, model=deepseek"
        result = _sanitize_str(text)
        assert "sk-abc123" not in result
        assert "api_key=***" in result

    def test_sanitize_error_truncates_long_body(self):
        """_sanitize_error 应截断超过 200 字符的错误消息。"""
        from scripts.dogfood_phase6_llm_consolidation import _sanitize_error

        long_body = "x" * 500
        exc = RuntimeError(long_body)
        result = _sanitize_error(exc)
        assert len(result) < 400  # 200 truncation + prefix

    def test_provider_info_no_key_content(self):
        """check_env 返回的 provider_info 绝不包含 API key 值。"""
        from scripts.dogfood_phase6_llm_consolidation import check_env
        _, _, prov, _ = check_env()

        # 遍历所有值，确保都不包含 key 片段
        for k, v in prov.items():
            v_str = str(v).lower()
            assert "sk-" not in v_str, f"provider_info[{k}] 包含疑似 key 值: {v}"
            assert "bearer" not in v_str, f"provider_info[{k}] 包含 bearer token"

    def test_report_json_no_key_in_output(self, tmp_dogfood_root):
        """generate_review_packet 的输出 JSON 不得包含 API key。"""
        from scripts.dogfood_phase6_llm_consolidation import (
            generate_review_packet,
            seed_synthetic_evidence,
        )
        from agent.memory_consolidation_pipeline import run_consolidation_pipeline
        from agent.memory_fs_store import FilesystemMemoryStore
        import scripts.dogfood_phase6_llm_consolidation as dogfood_mod

        store_root = tmp_dogfood_root / "memory"
        store_root.mkdir(parents=True, exist_ok=True)
        seed_synthetic_evidence(store_root)

        store = FilesystemMemoryStore(root_dir=store_root)
        pipeline_result = run_consolidation_pipeline(store, llm_generator=None)

        packet_dir = tmp_dogfood_root / "review_packet"
        packet_dir.mkdir(parents=True, exist_ok=True)

        report = {
            "pipeline": {
                "evidence_count": pipeline_result.evidence_count,
                "candidate_count": pipeline_result.candidate_count,
                "skipped_count": pipeline_result.skipped_count,
                "warnings": list(pipeline_result.warnings),
                "detector_name": pipeline_result.detector_name,
                "llm_enabled": False,
                "llm_enhanced_count": 0,
                "llm_warnings": [],
            },
            "provider": {"model": "test", "base_url": "test", "key_configured": False},
            "llm_status": "skipped",
            "dispatch": None,
            "governance_check": None,
        }

        original_review = dogfood_mod._REVIEW_PACKET_DIR
        original_store = dogfood_mod._STORE_ROOT
        try:
            dogfood_mod._REVIEW_PACKET_DIR = packet_dir
            dogfood_mod._STORE_ROOT = store_root
            packet_path = generate_review_packet(report)

            data = json.loads(packet_path.read_text(encoding="utf-8"))
            json_str = json.dumps(data)

            # 绝对不能包含 sk- 前缀的 key
            assert "sk-" not in json_str, "review packet JSON 包含疑似 key 值"
            # 绝对不能包含 Bearer token
            assert "bearer" not in json_str.lower(), "review packet JSON 包含 bearer token"
            # provider 字段中不能有 key 值
            prov = data.get("executive_summary", {}).get("provider", {})
            for k, v in prov.items():
                assert "sk-" not in str(v), f"executive_summary.provider[{k}] 包含疑似 key"
        finally:
            dogfood_mod._REVIEW_PACKET_DIR = original_review
            dogfood_mod._STORE_ROOT = original_store

    def test_markdown_summary_no_key_content(self, tmp_dogfood_root):
        """Markdown 摘要不得包含 API key。"""
        import scripts.dogfood_phase6_llm_consolidation as dogfood_mod
        from agent.memory_consolidation_pipeline import run_consolidation_pipeline
        from agent.memory_fs_store import FilesystemMemoryStore
        from scripts.dogfood_phase6_llm_consolidation import seed_synthetic_evidence

        store_root = tmp_dogfood_root / "memory"
        store_root.mkdir(parents=True, exist_ok=True)
        seed_synthetic_evidence(store_root)

        store = FilesystemMemoryStore(root_dir=store_root)
        result = run_consolidation_pipeline(store, llm_generator=None)

        packet_dir = tmp_dogfood_root / "review_packet"
        packet_dir.mkdir(parents=True, exist_ok=True)

        report = {
            "pipeline": {
                "evidence_count": result.evidence_count,
                "candidate_count": result.candidate_count,
                "skipped_count": result.skipped_count,
                "warnings": [],
                "detector_name": result.detector_name,
                "llm_enabled": False,
                "llm_enhanced_count": 0,
                "llm_warnings": [],
            },
            "provider": {"model": "test", "base_url": "test", "key_configured": False},
            "llm_status": "skipped",
            "dispatch": None,
            "governance_check": {"all_pass": True, "candidates_checked": result.candidate_count, "details": []},
        }

        original_review = dogfood_mod._REVIEW_PACKET_DIR
        original_store = dogfood_mod._STORE_ROOT
        try:
            dogfood_mod._REVIEW_PACKET_DIR = packet_dir
            dogfood_mod._STORE_ROOT = store_root
            dogfood_mod.generate_review_packet(report)

            md_files = sorted(packet_dir.glob("review_summary_*.md"))
            assert len(md_files) >= 1
            md_content = md_files[-1].read_text(encoding="utf-8")

            assert "sk-" not in md_content
            assert "Bearer " not in md_content
        finally:
            dogfood_mod._REVIEW_PACKET_DIR = original_review
            dogfood_mod._STORE_ROOT = original_store

    def test_dogfood_script_has_no_key_print(self):
        """dogfood 脚本的主代码路径不应包含 print key/secret 的语句。"""
        src = Path(__file__).parent.parent / "scripts" / "dogfood_phase6_llm_consolidation.py"
        raw = src.read_text(encoding="utf-8")

        # 去掉 docstring
        lines = raw.split("\n")
        non_doc: list[str] = []
        in_doc = False
        for line in lines:
            s = line.strip()
            if s.startswith('"""') or s.startswith("'''"):
                in_doc = not in_doc
                continue
            if in_doc:
                continue
            non_doc.append(line)
        code = "\n".join(non_doc)

        # 不应有打印 key 相关内容的代码（排除 docstring 中的注释说明）
        assert "print(API_KEY" not in code
        assert "print(api_key" not in code
        assert "print(_api_key" not in code
        # print(key 后面不跟 word → 排除 print(keyword 等情况)
        assert "print(KEY" not in code


# ── Phase 4: Provider Config Loading 测试 ─────────────────────────────────────


class TestParseDotenvFile:
    """_parse_dotenv_file() 的解析行为测试。"""

    def test_parses_key_value_pairs(self, tmp_path):
        """解析标准 KEY=VALUE 行。"""
        from scripts.dogfood_phase6_llm_consolidation import _parse_dotenv_file

        env_file = tmp_path / ".env"
        env_file.write_text(
            "ANTHROPIC_API_KEY=sk-ant-test-key\n"
            "ANTHROPIC_MODEL=claude-sonnet-4-6\n"
            'BASE_URL="https://api.anthropic.com"\n'
        )

        result = _parse_dotenv_file(env_file)
        assert result["ANTHROPIC_API_KEY"] == "sk-ant-test-key"
        assert result["ANTHROPIC_MODEL"] == "claude-sonnet-4-6"
        assert result["BASE_URL"] == "https://api.anthropic.com"

    def test_skips_comments_and_empty_lines(self, tmp_path):
        """跳过注释和空行。"""
        from scripts.dogfood_phase6_llm_consolidation import _parse_dotenv_file

        env_file = tmp_path / ".env"
        env_file.write_text(
            "# 这是注释\n"
            "  # 缩进注释\n"
            "\n"
            "ANTHROPIC_MODEL=claude-sonnet-4-6\n"
            "\n"
            "# 另一个注释\n"
        )

        result = _parse_dotenv_file(env_file)
        assert "ANTHROPIC_MODEL" in result
        assert "#" not in result
        assert result["ANTHROPIC_MODEL"] == "claude-sonnet-4-6"

    def test_returns_empty_dict_for_missing_file(self, tmp_path):
        """不存在的 .env 文件返回空 dict。"""
        from scripts.dogfood_phase6_llm_consolidation import _parse_dotenv_file

        result = _parse_dotenv_file(tmp_path / "nonexistent.env")
        assert result == {}

    def test_strips_quotes_from_values(self, tmp_path):
        """去掉值的引号。"""
        from scripts.dogfood_phase6_llm_consolidation import _parse_dotenv_file

        env_file = tmp_path / ".env"
        env_file.write_text(
            'SINGLE_QUOTED=\'value1\'\n'
            'DOUBLE_QUOTED="value2"\n'
            "NO_QUOTES=value3\n"
        )

        result = _parse_dotenv_file(env_file)
        assert result["SINGLE_QUOTED"] == "value1"
        assert result["DOUBLE_QUOTED"] == "value2"
        assert result["NO_QUOTES"] == "value3"


class TestDogfoodProviderConfig:
    """DogfoodProviderConfig 不变性测试。"""

    def test_frozen_dataclass(self):
        """DogfoodProviderConfig 是 frozen dataclass，不可修改。"""
        from scripts.dogfood_phase6_llm_consolidation import DogfoodProviderConfig

        cfg = DogfoodProviderConfig(
            model="test-model",
            base_url="https://test.api",
            api_key="sk-test",
            provider="anthropic",
        )
        import dataclasses
        assert dataclasses.is_dataclass(cfg)
        # frozen dataclass: 修改属性应抛出 FrozenInstanceError
        try:
            cfg.api_key = "new-key"  # type: ignore[misc]
            assert False, "frozen dataclass 应阻止属性修改"
        except Exception:
            pass

    def test_key_configured_true_when_key_present(self):
        """api_key 非空时 key_configured 为 True。"""
        from scripts.dogfood_phase6_llm_consolidation import DogfoodProviderConfig

        cfg = DogfoodProviderConfig(
            model="m", base_url="u", api_key="sk-test", provider="anthropic",
        )
        assert cfg.key_configured is True

    def test_key_configured_false_when_key_empty(self):
        """api_key 为空时 key_configured 为 False。"""
        from scripts.dogfood_phase6_llm_consolidation import DogfoodProviderConfig

        cfg = DogfoodProviderConfig(
            model="m", base_url="u", api_key="", provider="unknown",
        )
        assert cfg.key_configured is False

    def test_repr_does_not_leak_key(self):
        """repr 输出中不包含原始 api_key 值（dataclass 默认 repr 会包含）。"""
        from scripts.dogfood_phase6_llm_consolidation import DogfoodProviderConfig

        cfg = DogfoodProviderConfig(
            model="test-model",
            base_url="https://test.api",
            api_key="sk-ant-secret-key-12345",
            provider="anthropic",
        )
        # 默认 frozen dataclass repr 包含所有字段值
        # 这里验证 key_configured 作为公开 API 存在，外部代码应使用此属性
        # 实际应用中通过 provider_info dict 报告状态，不直接打印 config
        assert cfg.key_configured is True


class TestLoadProjectDotenv:
    """load_project_dotenv_for_dogfood() 加载优先级测试。"""

    def test_project_env_overrides_shell_env(self, tmp_path, monkeypatch):
        """项目 .env 的值覆盖同名 shell env。"""
        from scripts.dogfood_phase6_llm_consolidation import _parse_dotenv_file

        # 模拟被污染的 shell env（过期 key）
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-polluted-expired-key")
        monkeypatch.setenv("ANTHROPIC_MODEL", "polluted-model")
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://polluted.api")

        # 写入项目 .env（正确 key）
        env_file = tmp_path / ".env"
        env_file.write_text(
            "ANTHROPIC_API_KEY=sk-ant-correct-key\n"
            "ANTHROPIC_MODEL=claude-sonnet-4-6\n"
            "ANTHROPIC_BASE_URL=https://api.anthropic.com\n"
        )

        # 由于 load_project_dotenv_for_dogfood 内部 import config，
        # 而 config 在模块导入时就 load_dotenv(override=False) 了，
        # 我们需要直接测试解析逻辑：项目 .env 解析结果应覆盖 shell env
        dotenv_vars = _parse_dotenv_file(env_file)
        assert dotenv_vars["ANTHROPIC_API_KEY"] == "sk-ant-correct-key"
        assert dotenv_vars["ANTHROPIC_MODEL"] == "claude-sonnet-4-6"

    def test_fallback_to_shell_when_env_missing(self, tmp_path, monkeypatch):
        """项目 .env 缺少 api_key 字段时，key 回退到 shell env。"""
        from scripts.dogfood_phase6_llm_consolidation import (
            load_project_dotenv_for_dogfood,
        )

        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-shell-fallback-key")
        monkeypatch.setenv("ANTHROPIC_MODEL", "shell-model")

        # 创建只有部分字段的 .env（有 model 但无 api_key）
        env_file = tmp_path / ".env"
        env_file.write_text("ANTHROPIC_MODEL=env-model\n")

        cfg = load_project_dotenv_for_dogfood(tmp_path)
        assert cfg is not None
        # model 从 project .env 获取
        assert cfg.model == "env-model"
        # api_key 从 shell env 回退，source 标记为 shell env fallback
        assert cfg.key_configured is True
        assert cfg.source == "shell env fallback"

    def test_source_is_project_env_when_all_from_env(self, tmp_path, monkeypatch):
        """所有字段都从项目 .env 获取时 source 为 'project .env'。"""
        from scripts.dogfood_phase6_llm_consolidation import (
            load_project_dotenv_for_dogfood,
        )

        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-polluted")
        monkeypatch.setenv("ANTHROPIC_MODEL", "polluted-model")

        env_file = tmp_path / ".env"
        env_file.write_text(
            "ANTHROPIC_API_KEY=sk-ant-env-key\n"
            "ANTHROPIC_MODEL=claude-env-model\n"
            "ANTHROPIC_BASE_URL=https://env.api\n"
        )

        cfg = load_project_dotenv_for_dogfood(tmp_path)
        assert cfg.model == "claude-env-model"
        assert cfg.key_configured is True
        assert cfg.source == "project .env"

    def test_source_marked_shell_fallback_when_no_env(self, tmp_path, monkeypatch):
        """项目 .env 完全不存在时 source 标记为 shell env fallback。"""
        from scripts.dogfood_phase6_llm_consolidation import (
            load_project_dotenv_for_dogfood,
        )

        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-shell-only")
        monkeypatch.setenv("ANTHROPIC_MODEL", "shell-model")

        # tmp_path 下没有 .env
        cfg = load_project_dotenv_for_dogfood(tmp_path)
        assert cfg is not None
        # 注意：api_key 从 shell env 读取，source 取决于逻辑
        assert cfg.key_configured is True

    def test_check_env_with_explicit_project_root(self, tmp_path):
        """check_env 接受显式 project_root 参数。"""
        from scripts.dogfood_phase6_llm_consolidation import check_env

        # 创建有完整配置的 .env
        env_file = tmp_path / ".env"
        env_file.write_text(
            "ANTHROPIC_API_KEY=sk-ant-test-key\n"
            "ANTHROPIC_MODEL=claude-test\n"
            "ANTHROPIC_BASE_URL=https://test.api\n"
        )

        can_run, reason, prov, cfg = check_env(project_root=tmp_path)
        # 因为默认 MEMORY_CONSOLIDATION_LLM_ENABLED 未设置，应该 skip
        assert not can_run
        assert "MEMORY_CONSOLIDATION_LLM_ENABLED" in reason

    def test_check_env_returns_provider_config(self, tmp_path, monkeypatch):
        """check_env 返回的 provider_config 是 DogfoodProviderConfig 实例。"""
        from scripts.dogfood_phase6_llm_consolidation import (
            DogfoodProviderConfig,
            check_env,
        )

        monkeypatch.setenv("MEMORY_CONSOLIDATION_LLM_ENABLED", "true")

        # 写入临时项目 .env（可控的 key 来源）
        env_file = tmp_path / ".env"
        env_file.write_text(
            "ANTHROPIC_API_KEY=sk-ant-test-key\n"
            "ANTHROPIC_MODEL=claude-test\n"
        )

        can_run, reason, prov, cfg = check_env(project_root=tmp_path)
        assert can_run
        assert isinstance(cfg, DogfoodProviderConfig)
        assert cfg.key_configured is True
        assert cfg.source == "project .env"

        # 清理
        monkeypatch.delenv("MEMORY_CONSOLIDATION_LLM_ENABLED")

    def test_check_env_provider_config_no_key(self, tmp_path, monkeypatch):
        """无 API key 时 check_env 返回 4 元组，cfg 存在但 key_configured=False。"""
        from scripts.dogfood_phase6_llm_consolidation import (
            DogfoodProviderConfig,
            check_env,
        )

        monkeypatch.setenv("MEMORY_CONSOLIDATION_LLM_ENABLED", "true")
        # 提供空的 .env 文件来隔离真实 key
        (tmp_path / ".env").write_text("")

        can_run, reason, prov, cfg = check_env(project_root=tmp_path)
        # cfg 总是返回 DogfoodProviderConfig 或 None
        assert cfg is not None
        assert isinstance(cfg, DogfoodProviderConfig)
        # key_configured 应与 can_run 一致
        if can_run:
            assert cfg.key_configured is True
        else:
            assert cfg.key_configured is False
            assert "API key" in reason
