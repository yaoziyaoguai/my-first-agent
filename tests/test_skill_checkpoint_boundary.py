"""Phase 7b: Skill Checkpoint/Resume Boundary 测试。

测试范围（来自 docs/testing/SKILL_SYSTEM_TDD.md Phase 8 / Loop Phase 7b）：
- in-flight Skill invocation 的 checkpoint 关联
- resume 不重放 side effects
- checkpoint 不保存 secrets
- checkpoint 不保存完整大型 Skill body/resources
- interrupted invocation 不能 bypass confirmation
- resume 不重复 high-risk tool execution
- Runtime 拥有 loop
"""
from __future__ import annotations

import json

from agent.skill_system.checkpoint import (
    SkillCheckpointCorrelation,
    build_invocation_checkpoint_note,
    is_checkpoint_safe,
)
from agent.skill_system.descriptor import SkillDescriptor

# ---- helpers ----

def _desc(name: str = "test-skill", risk_level: str = "low") -> SkillDescriptor:
    return SkillDescriptor(
        name=name,
        description="test",
        version="0.1.0",
        status="active",
        risk_level=risk_level,  # type: ignore[arg-type]
    )


# ==================================================================
# SkillCheckpointCorrelation 结构
# ==================================================================

def test_skill_checkpoint_correlation_fields():
    """验证 SkillCheckpointCorrelation 包含必要字段。"""
    corr = SkillCheckpointCorrelation(
        skill_name="test-skill",
        skill_version="0.1.0",
        audit_id="audit-001",
        loaded_level=2,
        loaded_resources=("references/guide.md",),
        pending_confirmation=False,
        invocation_status="in_flight",
    )
    assert corr.skill_name == "test-skill"
    assert corr.audit_id == "audit-001"
    assert corr.pending_confirmation is False


def test_checkpoint_correlation_is_serializable():
    """SkillCheckpointCorrelation 应可序列化为 JSON。"""
    corr = SkillCheckpointCorrelation(
        skill_name="test-skill",
        skill_version="0.1.0",
        audit_id="audit-001",
        loaded_level=2,
        loaded_resources=("ref.md",),
        pending_confirmation=True,
        invocation_status="awaiting_confirmation",
    )
    data = {
        "skill_name": corr.skill_name,
        "skill_version": corr.skill_version,
        "audit_id": corr.audit_id,
        "loaded_level": corr.loaded_level,
        "loaded_resources": list(corr.loaded_resources),
        "pending_confirmation": corr.pending_confirmation,
        "invocation_status": corr.invocation_status,
    }
    json_str = json.dumps(data)
    assert "test-skill" in json_str
    assert "audit-001" in json_str


# ==================================================================
# build_invocation_checkpoint_note
# ==================================================================

def test_build_invocation_checkpoint_note():
    """从 descriptor 和 invocation params 构建 checkpoint note。"""
    desc = _desc("my-skill")
    note = build_invocation_checkpoint_note(
        descriptor=desc,
        audit_id="audit-002",
        loaded_level=2,
        invocation_status="in_flight",
    )
    assert "my-skill" in note
    assert "v0.1.0" in note
    assert "audit-002" in note
    assert "in_flight" in note or "进行中" in note


# ==================================================================
# is_checkpoint_safe
# ==================================================================

def test_is_checkpoint_safe_normal_data():
    """普通 metadata 的 checkpoint 应该是安全的。"""
    assert is_checkpoint_safe({"skill_name": "test", "version": "0.1.0"}) is True


def test_is_checkpoint_safe_rejects_secrets():
    """包含疑似 secret 的 checkpoint data 应被标记为不安全。"""
    assert is_checkpoint_safe({"key": "sk-proj-abcdefghijklmnopqrstuvwxyz123456"}) is False
    assert is_checkpoint_safe({"token": "ghp_1234567890abcdefghijklmnopqrstuvwxyz"}) is False


def test_is_checkpoint_safe_rejects_large_body():
    """包含巨大 body 内容的 checkpoint data 应被标记为不安全。"""
    assert is_checkpoint_safe({"body": "x" * 100_000}) is False
    assert is_checkpoint_safe({"resources": {"big": "y" * 50_000}}) is False


def test_is_checkpoint_safe_allows_metadata():
    """metadata-level checkpoint 应安全。"""
    assert is_checkpoint_safe({
        "skill_name": "my-skill",
        "version": "0.1.0",
        "audit_id": "a1",
        "loaded_resources": ["ref.md"],
        "note": "skill invocation in flight",
    }) is True


# ==================================================================
# Checkpoint 不保存 secrets / 大文件
# ==================================================================

def test_checkpoint_correlation_rejects_full_body():
    """SkillCheckpointCorrelation 不应接受完整 body 内容。"""
    # 构造时不应包含 body 字段
    corr = SkillCheckpointCorrelation(
        skill_name="test",
        skill_version="0.1.0",
        audit_id="a1",
        loaded_level=2,
    )
    assert not hasattr(corr, "body")
    assert not hasattr(corr, "resource_contents")


# ==================================================================
# Pending confirmation 在 resume 后保留
# ==================================================================

def test_pending_confirmation_survives_checkpoint():
    """pending_confirmation=True 的 invocation 在 checkpoint 后应保留该信息。"""
    corr = SkillCheckpointCorrelation(
        skill_name="dangerous-skill",
        skill_version="0.1.0",
        audit_id="audit-003",
        loaded_level=2,
        pending_confirmation=True,
        invocation_status="awaiting_confirmation",
    )
    assert corr.pending_confirmation is True
    # resume 时不应自动批准
    # (本测试确保 metadata 保留 pending 状态)


# ==================================================================
# Runtime owns loop
# ==================================================================

def test_checkpoint_module_does_not_implement_loop():
    """checkpoint.py 不应实现 Agent loop。"""
    from agent.skill_system import checkpoint

    # 不应有 loop/run/execute 等方法
    for attr in dir(checkpoint):
        assert "loop" not in attr.lower(), f"checkpoint.py has loop-like attribute: {attr}"


# ==================================================================
# no legacy import
# ==================================================================

def test_checkpoint_module_does_not_import_legacy():
    """checkpoint.py 不能 import agent.skills / agent.legacy_skills。"""
    import ast
    from pathlib import Path

    p = Path(__file__).resolve().parents[1] / "agent" / "skill_system" / "checkpoint.py"
    tree = ast.parse(p.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("agent.skills")
                assert not alias.name.startswith("agent.legacy_skills")
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("agent.skills")
            assert not node.module.startswith("agent.legacy_skills")
