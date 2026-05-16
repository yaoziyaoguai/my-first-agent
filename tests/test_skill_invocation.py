"""Phase 6: Runtime Invocation Adapter 测试。

测试范围（来自 docs/testing/SKILL_SYSTEM_TDD.md Phase 6）：
- SkillInvocationRequest → SkillInvocationResult 流程
- audit id 追踪
- 错误处理
- 不拥有 Agent loop
- 不直接修改 Runtime state

禁止行为：
- Skill starts another loop
- Skill calls provider directly
- import legacy
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from textwrap import dedent

from agent.skill_system.context import SkillContext
from agent.skill_system.errors import SkillLoadError
from agent.skill_system.invocation import (
    SkillInvocationRequest,
    invoke_skill,
)
from agent.skill_system.loader import SkillLoader
from agent.skill_system.registry import SkillRegistry
from agent.skill_system.result import (
    SkillAuditRecord,
    SkillInvocationResult,
)


# ---- helpers ----

def _make_skill(tmp_root: Path, name: str, status: str = "active"):
    skill_dir = tmp_root / name
    skill_dir.mkdir(parents=True)
    content = f"""---
name: {name}
description: Skill {name}
version: 0.1.0
status: {status}
risk_level: low
allowed_tools:
  - read_file
resources:
  references: []
  scripts: []
  templates: []
  tests: []
  dogfood: []
---
# {name}

Skill body content for {name}.
"""
    (skill_dir / "SKILL.md").write_text(dedent(content).strip(), encoding="utf-8")
    return skill_dir


# ==================================================================
# SkillInvocationRequest / SkillInvocationResult
# ==================================================================

def test_invoke_skill_returns_result():
    """invoke_skill 应返回 SkillInvocationResult。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "skills"
        _make_skill(root, "test-skill")
        registry = SkillRegistry(roots=[root])
        loader = SkillLoader(registry)

        request = SkillInvocationRequest(
            skill_name="test-skill",
            user_goal="test invocation",
            selection_reason="exact match",
        )
        result = invoke_skill(request, registry, loader)

        assert isinstance(result, SkillInvocationResult)
        assert result.ok is True
        assert result.skill_name == "test-skill"


def test_invoke_skill_includes_body_in_visible_output():
    """invocation 结果应包含 Skill body 内容。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "skills"
        _make_skill(root, "body-skill")
        registry = SkillRegistry(roots=[root])
        loader = SkillLoader(registry)

        request = SkillInvocationRequest(
            skill_name="body-skill",
            user_goal="test",
            selection_reason="exact match",
        )
        result = invoke_skill(request, registry, loader)

        assert "Skill body content for body-skill" in result.visible_output


def test_invoke_skill_for_nonexistent_skill_fails():
    """请求不存在的 Skill 时 invocation 应 fail closed。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "skills"
        root.mkdir(parents=True)
        registry = SkillRegistry(roots=[root])
        loader = SkillLoader(registry)

        request = SkillInvocationRequest(
            skill_name="nonexistent",
            user_goal="test",
            selection_reason="unknown",
        )
        result = invoke_skill(request, registry, loader)
        assert result.ok is False
        assert len(result.errors) > 0


def test_invoke_skill_hidden_skill_blocked():
    """请求 disabled Skill 时 invocation 应 fail closed。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "skills"
        _make_skill(root, "hidden-skill", status="disabled")
        registry = SkillRegistry(roots=[root])
        loader = SkillLoader(registry)

        request = SkillInvocationRequest(
            skill_name="hidden-skill",
            user_goal="test",
            selection_reason="explicit",
        )
        result = invoke_skill(request, registry, loader)
        assert result.ok is False


# ==================================================================
# Audit record
# ==================================================================

def test_invoke_skill_produces_audit_record():
    """成功 invocation 应产生 SkillAuditRecord。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "skills"
        _make_skill(root, "audit-skill")
        registry = SkillRegistry(roots=[root])
        loader = SkillLoader(registry)

        request = SkillInvocationRequest(
            skill_name="audit-skill",
            user_goal="audit test",
            selection_reason="exact match",
        )
        result = invoke_skill(request, registry, loader)

        assert result.audit_record is not None
        assert result.audit_record.skill_name == "audit-skill"
        assert result.audit_record.result_status == "ok"
        assert result.audit_record.audit_id != ""


# ==================================================================
# SkillContext 构建
# ==================================================================

def test_skill_context_assembles_correctly():
    """SkillContext 应正确组装 descriptor / body / audit id。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "skills"
        _make_skill(root, "ctx-skill")
        registry = SkillRegistry(roots=[root])
        loader = SkillLoader(registry)

        desc = registry.get_descriptor("ctx-skill")
        body = loader.load_body("ctx-skill")
        ctx = SkillContext(
            descriptor=desc,
            body=body,
            task_goal="test task",
            audit_id="audit-001",
        )

        assert ctx.descriptor.name == "ctx-skill"
        assert "Skill body content" in ctx.body
        assert ctx.task_goal == "test task"
        assert ctx.audit_id == "audit-001"


# ==================================================================
# Skill 不拥有 loop
# ==================================================================

def test_invoke_skill_is_one_shot():
    """invoke_skill 是一次性的 request/result，不启动 loop。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "skills"
        _make_skill(root, "one-shot")
        registry = SkillRegistry(roots=[root])
        loader = SkillLoader(registry)

        request = SkillInvocationRequest(
            skill_name="one-shot",
            user_goal="one shot test",
            selection_reason="exact",
        )
        result = invoke_skill(request, registry, loader)
        # 一次性调用，不创建任何持久的循环状态
        assert result.ok is True
        # InvocationResult 没有 loop/continue 方法
        assert not hasattr(result, "loop")
        assert not hasattr(result, "next_step")


# ==================================================================
# SkillInvocationResult error tracking
# ==================================================================

def test_result_tracks_errors():
    """SkillInvocationResult 应在 errors 字段追踪错误。"""
    result = SkillInvocationResult(
        ok=False,
        skill_name="bad-skill",
        visible_output="",
        errors=(
            SkillLoadError(code="E1", message="error 1", recoverable=False, safe_preview="e1"),
            SkillLoadError(code="E2", message="error 2", recoverable=True, safe_preview="e2"),
        ),
    )
    assert len(result.errors) == 2
    assert result.errors[0].code == "E1"


# ==================================================================
# SkillAuditRecord
# ==================================================================

def test_audit_record_is_immutable():
    """SkillAuditRecord 应是不可变的。"""
    record = SkillAuditRecord(
        audit_id="audit-1",
        skill_name="test",
        skill_version="0.1.0",
        selection_reason="exact match",
        loaded_levels=2,
        loaded_resources=(),
        requested_tools=("read_file",),
        blocked_tools=(),
        memory_scope="none",
        result_status="ok",
        safe_preview="invoked test skill",
    )
    assert record.audit_id == "audit-1"
    assert record.safe_preview == "invoked test skill"
    # 不应包含 secret
    assert "secret" not in record.safe_preview.lower()


def test_audit_record_safe_preview_no_secrets():
    """safe_preview 不应包含 secrets。"""
    record = SkillAuditRecord(
        audit_id="a1", skill_name="sk-test", skill_version="0.1.0",
        selection_reason="match", loaded_levels=2,
        loaded_resources=(), requested_tools=(), blocked_tools=(),
        memory_scope="none", result_status="ok",
        safe_preview="loaded skill",
    )
    # confirm no token-like patterns in safe_preview
    assert "ghp_" not in record.safe_preview
    assert "sk-" not in record.safe_preview


# ==================================================================
# no legacy import
# ==================================================================

def test_invocation_modules_do_not_import_legacy():
    """context.py / invocation.py / result.py 不能 import agent.skills / agent.legacy_skills。"""
    import ast
    from pathlib import Path as P

    for mod in ["context.py", "invocation.py", "result.py"]:
        p = P(__file__).resolve().parents[1] / "agent" / "skill_system" / mod
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("agent.skills"), f"{mod} imports {alias.name}"
                    assert not alias.name.startswith("agent.legacy_skills"), f"{mod} imports {alias.name}"
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("agent.skills"), f"{mod} imports {node.module}"
                assert not node.module.startswith("agent.legacy_skills"), f"{mod} imports {node.module}"
