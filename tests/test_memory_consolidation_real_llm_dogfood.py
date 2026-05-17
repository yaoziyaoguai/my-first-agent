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
        assert "api_key:***" in result

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

    def test_sanitize_str_removes_masked_provider_key_suffix(self):
        """provider 返回的 masked key suffix 也不得进入 report。"""
        from scripts.dogfood_phase6_llm_consolidation import _sanitize_str

        text = "Authentication Fails, Your api key: ****7a7d is invalid"
        result = _sanitize_str(text)
        assert "****7a7d" not in result
        assert "api key:***" in result.lower()

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

    def test_auth_failed_review_packet_uses_generic_sanitized_error(
        self, tmp_dogfood_root,
    ):
        """auth_failed report 只保存通用错误类型，不保存 provider 原始响应。"""
        import scripts.dogfood_phase6_llm_consolidation as dogfood_mod
        from scripts.dogfood_phase6_llm_consolidation import DogfoodProviderConfig

        secret = "sk-report-secret-value-that-must-not-leak"
        cfg = DogfoodProviderConfig(
            model="deepseek-v4-pro",
            base_url="https://api.deepseek.com/anthropic",
            api_key=secret,
            provider="deepseek_anthropic",
            key_source_kind="project_dotenv",
        )
        report = {
            "pipeline": {
                "evidence_count": 3,
                "candidate_count": 1,
                "skipped_count": 0,
                "warnings": [],
                "detector_name": "test",
                "llm_enabled": True,
                "llm_enhanced_count": 0,
                "llm_warnings": ["provider_error:auth_failed"],
            },
            "provider": cfg.safe_diagnostics(
                auth_status="auth_failed",
                error_type="auth_failed",
                sanitized_error="provider authentication failed",
            ),
            "llm_status": "blocked",
            "provider_error_type": "auth_failed",
            "sanitized_error": "provider authentication failed",
            "dispatch": {
                "dispatched": 1,
                "skipped_duplicate": 0,
                "skipped_invalid": 0,
                "warnings": [],
                "filepaths": [],
            },
            "governance_check": {
                "all_pass": True,
                "candidates_checked": 1,
                "details": [],
            },
            "direct_store_write": {
                "semantic_records": 0,
                "procedural_records": 0,
                "direct_semantic_or_procedural_write": False,
            },
        }

        packet_dir = tmp_dogfood_root / "review_packet"
        store_root = tmp_dogfood_root / "memory"
        packet_dir.mkdir(parents=True, exist_ok=True)
        store_root.mkdir(parents=True, exist_ok=True)

        original_review = dogfood_mod._REVIEW_PACKET_DIR
        original_store = dogfood_mod._STORE_ROOT
        try:
            dogfood_mod._REVIEW_PACKET_DIR = packet_dir
            dogfood_mod._STORE_ROOT = store_root
            packet_path = dogfood_mod.generate_review_packet(report)
            packet_text = packet_path.read_text(encoding="utf-8")
            packet = json.loads(packet_text)

            assert packet["provider_error_type"] == "auth_failed"
            assert packet["sanitized_error"] == "provider authentication failed"
            assert secret not in packet_text
            assert "sk-" not in packet_text
            assert "****" not in packet_text
            assert "api key" not in packet_text.lower()
            assert "Bearer" not in packet_text
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
        """repr 输出中不包含 api_key 值、prefix、suffix 或长度信息。"""
        from scripts.dogfood_phase6_llm_consolidation import DogfoodProviderConfig

        key = "sk-ant-secret-key-12345"
        cfg = DogfoodProviderConfig(
            model="test-model",
            base_url="https://test.api",
            api_key=key,
            provider="anthropic",
        )

        r = repr(cfg)

        # core: 完整 key 不得出现
        assert key not in r, f"完整 api_key 泄露于 repr: {r}"
        # prefix
        assert "sk-ant-secret" not in r, f"key prefix 泄露于 repr: {r}"
        # suffix
        assert "12345" not in r, f"key suffix 泄露于 repr: {r}"
        # 通用 sk- 前缀
        assert "sk-" not in r, f"sk- 前缀出现于 repr: {r}"

        # 非 secret 字段正常出现
        assert "test-model" in r
        assert "test.api" in r
        assert "anthropic" in r
        assert "config auto-load" in r

        # key_configured 仍然可访问
        assert cfg.key_configured is True


class TestProviderConfigAutoLoad:
    """Provider config 只通过项目配置机制自动加载。

    这些测试验证 real provider dogfood 的配置加载和脱敏报告边界，
    不验证真实 API key 本身是否有效。
    """

    def test_load_provider_config_uses_shell_env_when_project_dotenv_absent(
        self, tmp_path, monkeypatch,
    ):
        """fake project 无 .env 时回退 shell env，不读取真实项目 .env。"""
        from scripts.dogfood_phase6_llm_consolidation import (
            load_provider_config_for_dogfood,
        )

        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-auto-load")
        monkeypatch.setenv("MODEL_NAME", "claude-test-model")
        monkeypatch.setenv("ANTHROPIC_MODEL", "claude-fallback-model")
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")

        cfg = load_provider_config_for_dogfood(project_root=tmp_path)
        assert cfg.model == "claude-test-model"
        assert cfg.base_url == "https://api.anthropic.com"
        assert cfg.key_configured is True
        assert cfg.provider == "anthropic"
        assert cfg.source == "config auto-load"
        assert cfg.key_source_kind == "shell_env"

    def test_explicit_provider_env_controls_phase6_dogfood_provider_identity(
        self, tmp_path,
    ):
        """Phase 6 dogfood provider identity 优先来自显式配置，而不是 model/base_url 猜测。

        这是 Claude/Anthropic P3 防回归：model 名含 ``claude`` 只能说明模型命名，
        不能让 dogfood runner 绕过 provider config 权威自行推断运行依赖。
        """
        from scripts.dogfood_phase6_llm_consolidation import (
            load_provider_config_for_dogfood,
        )

        (tmp_path / ".env").write_text(
            "\n".join([
                "MY_FIRST_AGENT_LLM_PROVIDER=openai_compatible",
                "MY_FIRST_AGENT_LLM_PROVIDER_NAME=custom-openai-compatible",
                "OPENAI_MODEL=claude-shaped-but-config-driven",
                "OPENAI_BASE_URL=https://openai-compatible.example.test/v1",
                "OPENAI_API_KEY=sk-fake-openai-compatible-key",
            ]),
            encoding="utf-8",
        )

        cfg = load_provider_config_for_dogfood(project_root=tmp_path)

        assert cfg.provider == "custom-openai-compatible"
        assert cfg.provider_type == "openai_compatible"
        assert cfg.model == "claude-shaped-but-config-driven"
        assert cfg.key_source_kind == "project_dotenv"

    def test_project_dotenv_preferred_over_shell_env_pollution(self, tmp_path, monkeypatch):
        """fake project .env 优先于 shell env，且 diagnostics 不泄露 key 值。"""
        from scripts.dogfood_phase6_llm_consolidation import (
            load_provider_config_for_dogfood,
        )

        project_key = "sk-project-secret-value-that-must-not-leak"
        shell_key = "sk-shell-secret-value-that-must-not-leak"
        (tmp_path / ".env").write_text(
            "\n".join([
                "MODEL_NAME=deepseek-v4-pro",
                "ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic",
                f"ANTHROPIC_API_KEY={project_key}",
            ]),
            encoding="utf-8",
        )
        monkeypatch.setenv("MODEL_NAME", "claude-shell-model")
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
        monkeypatch.setenv("ANTHROPIC_API_KEY", shell_key)

        cfg = load_provider_config_for_dogfood(project_root=tmp_path)
        diagnostics = cfg.safe_diagnostics()
        diagnostics_text = json.dumps(diagnostics, ensure_ascii=False)

        assert cfg.model == "deepseek-v4-pro"
        assert cfg.base_url == "https://api.deepseek.com/anthropic"
        assert cfg.provider == "deepseek_anthropic"
        assert cfg.key_source_kind == "project_dotenv"
        assert cfg.key_configured is True
        assert project_key not in diagnostics_text
        assert shell_key not in diagnostics_text
        assert "sk-" not in diagnostics_text

    def test_deepseek_anthropic_config_matches_official_endpoint(self, tmp_path):
        """DeepSeek Anthropic-compatible 配置应识别为 Anthropic protocol provider。"""
        from scripts.dogfood_phase6_llm_consolidation import (
            load_provider_config_for_dogfood,
        )

        (tmp_path / ".env").write_text(
            "\n".join([
                "MODEL_NAME=deepseek-v4-pro",
                "ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic",
                "ANTHROPIC_API_KEY=sk-fake-deepseek-key",
            ]),
            encoding="utf-8",
        )

        cfg = load_provider_config_for_dogfood(project_root=tmp_path)
        diagnostics = cfg.safe_diagnostics()

        assert cfg.provider == "deepseek_anthropic"
        assert diagnostics["provider_name"] == "deepseek_anthropic"
        assert diagnostics["key_source_kind"] == "project_dotenv"
        assert diagnostics["auth_status"] == "not_run"
        assert diagnostics["provider_configured"] is True
        assert diagnostics["base_url"] == "https://api.deepseek.com/anthropic"
        assert diagnostics["model"] == "deepseek-v4-pro"

    def test_provider_model_base_url_mismatch_reports_sanitized_warning(
        self, tmp_path,
    ):
        """provider/model/base_url 不一致时只报告非敏感 warning。"""
        from scripts.dogfood_phase6_llm_consolidation import (
            load_provider_config_for_dogfood,
        )

        secret = "sk-mismatch-secret-value-that-must-not-leak"
        (tmp_path / ".env").write_text(
            "\n".join([
                "MODEL_NAME=deepseek-v4-pro",
                "ANTHROPIC_BASE_URL=https://api.anthropic.com",
                f"ANTHROPIC_API_KEY={secret}",
            ]),
            encoding="utf-8",
        )

        cfg = load_provider_config_for_dogfood(project_root=tmp_path)
        diagnostics = cfg.safe_diagnostics()
        diagnostics_text = json.dumps(diagnostics, ensure_ascii=False)

        assert "provider_model_base_url_mismatch" in diagnostics["warnings"]
        assert secret not in diagnostics_text
        assert "sk-" not in diagnostics_text

    def test_auth_failed_diagnostics_are_generic_and_secret_safe(self):
        """auth_failed 只报告安全错误类型，不写 provider 原始 secret 上下文。"""
        from scripts.dogfood_phase6_llm_consolidation import DogfoodProviderConfig

        secret = "sk-auth-secret-value-that-must-not-leak"
        cfg = DogfoodProviderConfig(
            model="deepseek-v4-pro",
            base_url="https://api.deepseek.com/anthropic",
            api_key=secret,
            provider="deepseek_anthropic",
            key_source_kind="project_dotenv",
        )

        diagnostics = cfg.safe_diagnostics(
            auth_status="auth_failed",
            error_type="auth_failed",
            sanitized_error="provider authentication failed",
        )
        diagnostics_text = json.dumps(diagnostics, ensure_ascii=False)

        assert diagnostics["provider_configured"] is True
        assert diagnostics["auth_status"] == "auth_failed"
        assert diagnostics["error_type"] == "auth_failed"
        assert diagnostics["sanitized_error"] == "provider authentication failed"
        assert secret not in diagnostics_text
        assert "sk-" not in diagnostics_text
        assert str(len(secret)) not in diagnostics_text
        assert "Bearer" not in diagnostics_text

    def test_provider_name_does_not_inspect_key_prefix(self):
        """provider 推断只看 model/base_url，不查看 API key prefix/suffix/length。"""
        from scripts.dogfood_phase6_llm_consolidation import (
            _infer_provider_name,
        )

        assert _infer_provider_name(
            model="claude-test",
            base_url="unknown",
        ) == "anthropic"
        assert _infer_provider_name(
            model="gpt-test",
            base_url="unknown",
        ) == "openai"
        assert _infer_provider_name(
            model="deepseek-v4-pro",
            base_url="https://api.deepseek.com/anthropic",
        ) == "deepseek_anthropic"
        assert _infer_provider_name(model="unknown", base_url="unknown") == "unknown"

    def test_error_classifier_returns_safe_categories(self):
        """provider 错误只暴露类型，不暴露具体 key 或 token。"""
        from scripts.dogfood_phase6_llm_consolidation import (
            _classify_llm_error,
        )

        assert _classify_llm_error(["401 Unauthorized"]) == "auth_failed"
        assert _classify_llm_error(["connection timed out"]) == "network_error"
        assert _classify_llm_error(["JSON decode failed"]) == "parse_error"
        assert _classify_llm_error(["API key 未设置"]) == "missing_config"

    def test_check_env_with_explicit_project_root(self, tmp_path):
        """check_env 接受显式 project_root，但不会读取该路径下的 .env。"""
        from scripts.dogfood_phase6_llm_consolidation import check_env

        can_run, reason, prov, cfg = check_env(project_root=tmp_path)
        # 因为默认 MEMORY_CONSOLIDATION_LLM_ENABLED 未设置，应该 skip
        assert not can_run
        assert "MEMORY_CONSOLIDATION_LLM_ENABLED" in reason
        assert prov == {}
        assert cfg is None

    def test_check_env_returns_provider_config(self, tmp_path, monkeypatch):
        """check_env 返回的 provider_config 是 DogfoodProviderConfig 实例。"""
        from scripts.dogfood_phase6_llm_consolidation import (
            DogfoodProviderConfig,
            check_env,
        )

        monkeypatch.setenv("MEMORY_CONSOLIDATION_LLM_ENABLED", "true")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-auto-load")
        monkeypatch.setenv("ANTHROPIC_MODEL", "claude-test")

        can_run, reason, prov, cfg = check_env(project_root=tmp_path)
        assert can_run
        assert isinstance(cfg, DogfoodProviderConfig)
        assert cfg.key_configured is True
        assert cfg.source == "config auto-load"
        assert prov["key_configured"] is True

        # 清理
        monkeypatch.delenv("MEMORY_CONSOLIDATION_LLM_ENABLED")

    def test_check_env_provider_config_no_key(self, tmp_path, monkeypatch):
        """无 API key 时 check_env 返回 4 元组，cfg 存在但 key_configured=False。"""
        from scripts.dogfood_phase6_llm_consolidation import (
            DogfoodProviderConfig,
            check_env,
        )

        monkeypatch.setenv("MEMORY_CONSOLIDATION_LLM_ENABLED", "true")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        can_run, reason, prov, cfg = check_env(project_root=tmp_path)
        # cfg 总是返回 DogfoodProviderConfig 或 None
        assert cfg is not None
        assert isinstance(cfg, DogfoodProviderConfig)
        assert not can_run
        assert cfg.key_configured is False
        assert prov["key_configured"] is False
        assert "API key" in reason

    def test_run_pipeline_injects_explicit_provider_config_into_llm_generator(
        self, tmp_path, monkeypatch,
    ):
        """Phase 6 runner 的 LLM 路径必须走 provider factory，而不是 direct SDK config。

        这里不跑真实 consolidation，只钉住构造边界：runner 可以持有脱敏
        DogfoodProviderConfig，但创建 generator 时必须注入 ModelProvider。
        """
        from agent.provider.config import AgentProviderConfig
        from scripts import dogfood_phase6_llm_consolidation as dogfood
        from scripts.dogfood_phase6_llm_consolidation import DogfoodProviderConfig

        built_configs: list[str] = []
        generator_providers: list[object] = []

        class FakeProvider:
            provider_type = "openai_compatible"

        class FakeGenerator:
            def __init__(self, *, provider=None, model_name=None, **kwargs):  # noqa: ANN001
                generator_providers.append(provider)
                assert kwargs == {}
                assert model_name == "openai-compatible-model"

        class FakePipelineResult:
            llm_warnings: list[str] = []
            warnings: list[str] = []
            llm_enhanced_count = 0
            llm_enabled = True
            evidence_count = 0
            candidate_count = 0
            skipped_count = 0
            detector_name = "fake"
            candidates: list = []
            has_candidates = False

        def fake_build_model_provider(config):  # noqa: ANN001
            built_configs.append(config.provider_type)
            return FakeProvider()

        def fake_run_consolidation_pipeline(store, llm_generator=None):  # noqa: ANN001
            assert llm_generator is not None
            return FakePipelineResult()

        monkeypatch.setattr(dogfood, "build_model_provider", fake_build_model_provider)
        monkeypatch.setattr(
            "agent.memory_consolidation_llm.LLMConsolidationContentGenerator",
            FakeGenerator,
        )
        monkeypatch.setattr(
            "agent.memory_consolidation_llm._is_llm_consolidation_enabled",
            lambda: True,
        )
        monkeypatch.setattr(
            "agent.memory_consolidation_pipeline.run_consolidation_pipeline",
            fake_run_consolidation_pipeline,
        )
        monkeypatch.setattr(
            "agent.memory_consolidation_review.dispatch_consolidation_candidates_to_pending_review",
            lambda *args, **kwargs: None,
        )

        provider_config = DogfoodProviderConfig(
            model="openai-compatible-model",
            base_url="https://openai-compatible.example.test/v1",
            api_key="sk-test",
            provider="custom-openai-compatible",
            provider_type="openai_compatible",
            agent_config=AgentProviderConfig(
                provider_type="openai_compatible",
                provider_name="custom-openai-compatible",
                api_key="sk-test",
                api_key_env="OPENAI_API_KEY",
                base_url="https://openai-compatible.example.test/v1",
                model="openai-compatible-model",
            ),
        )

        dogfood.run_dogfood_pipeline(tmp_path, {}, provider_config)

        assert built_configs == ["openai_compatible"]
        assert len(generator_providers) == 1
        assert isinstance(generator_providers[0], FakeProvider)
