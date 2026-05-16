"""Phase 9: Skill System Dogfood 测试。

测试范围（来自 docs/testing/SKILL_SYSTEM_TDD.md Phase 10）：
- 合成 dogfood fixtures，覆盖 dogfood plan 中的每个场景
- 仅本地确定性运行
- 禁止网络、.env、真实 sessions/runs、真实 LLM
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agent.skill_system.loader import SkillLoader
from agent.skill_system.registry import SkillRegistry
from agent.skill_system.schema import load_skill_manifest
from agent.skill_system.selector import SkillSelector
from agent.skill_system.tool_binding import SkillToolBinding

DOGFOOD_ROOT = Path(__file__).parent / "fixtures" / "dogfood"


# ---- Fake ToolRegistry ----

class _FakeToolRegistry:
    """合成 ToolRegistry，用于 dogfood 测试。"""

    def __init__(self, blocked: set[str] | None = None):
        self._blocked = blocked or set()

    def is_registered(self, name: str) -> bool:
        return True

    def get_risk(self, name: str) -> str:
        return "high" if name == "run_shell" else "low"

    def get_confirmation(self, name: str) -> str:
        return "always" if name == "run_shell" else "never"

    def is_hidden(self, name: str) -> bool:
        return name in self._blocked


# ---- Fixtures ----

@pytest.fixture
def dogfood_registry():
    return SkillRegistry(roots=[DOGFOOD_ROOT])


@pytest.fixture
def dogfood_loader(dogfood_registry):
    return SkillLoader(dogfood_registry)


# ==================================================================
# Scenario 1: Git Status Audit
# ==================================================================

def test_dogfood_git_status_audit_descriptor(dogfood_registry):
    desc = dogfood_registry.get_descriptor("git-status-audit")
    assert desc is not None
    assert desc.status == "active"
    assert desc.risk_level == "medium"
    assert "run_shell" in desc.allowed_tools


def test_dogfood_git_status_audit_selector():
    registry = SkillRegistry(roots=[DOGFOOD_ROOT])
    selector = SkillSelector(registry)
    decision = selector.select("Summarize the local git status and identify risky untracked files")
    assert decision.selected is True
    assert decision.skill_name == "git-status-audit"


def test_dogfood_git_status_audit_tool_binding():
    registry = SkillRegistry(roots=[DOGFOOD_ROOT])
    desc = registry.get_descriptor("git-status-audit")
    assert desc is not None
    tool_reg = _FakeToolRegistry()
    binding = SkillToolBinding(desc, tool_reg)
    result = binding.check("run_shell")
    assert result.allowed is True
    assert result.requires_confirmation is True


def test_dogfood_git_status_audit_body(dogfood_loader):
    body = dogfood_loader.load_body("git-status-audit")
    assert "git" in body.lower()
    assert "只读" in body or "read" in body.lower()


# ==================================================================
# Scenario 2: RFC Alignment Audit
# ==================================================================

def test_dogfood_rfc_alignment_audit_selector():
    registry = SkillRegistry(roots=[DOGFOOD_ROOT])
    selector = SkillSelector(registry)
    decision = selector.select("Check whether an implementation plan aligns with the Skill RFC")
    assert decision.selected is True
    assert decision.skill_name == "rfc-alignment-audit"


def test_dogfood_rfc_alignment_audit_readonly(dogfood_registry):
    desc = dogfood_registry.get_descriptor("rfc-alignment-audit")
    assert desc is not None
    assert "run_shell" not in desc.allowed_tools
    assert "read_file" in desc.allowed_tools


# ==================================================================
# Scenario 3: TDD Repair
# ==================================================================

def test_dogfood_tdd_repair_selector():
    registry = SkillRegistry(roots=[DOGFOOD_ROOT])
    selector = SkillSelector(registry)
    decision = selector.select("Given this failing test output, propose the smallest TDD repair")
    assert decision.selected is True
    assert decision.skill_name == "tdd-repair"


def test_dogfood_tdd_repair_memory_scope(dogfood_registry):
    desc = dogfood_registry.get_descriptor("tdd-repair")
    assert desc is not None
    assert desc.memory_scope == "read_context"


# ==================================================================
# Scenario 4: Prompt Writing
# ==================================================================

def test_dogfood_prompt_writing_selector():
    registry = SkillRegistry(roots=[DOGFOOD_ROOT])
    selector = SkillSelector(registry)
    decision = selector.select("Write a concise system prompt section for bounded tool use")
    assert decision.selected is True
    assert decision.skill_name == "prompt-writing"


# ==================================================================
# Scenario 5: Architecture Boundary Audit
# ==================================================================

def test_dogfood_architecture_boundary_audit_selector():
    registry = SkillRegistry(roots=[DOGFOOD_ROOT])
    selector = SkillSelector(registry)
    decision = selector.select("Audit whether a diff adds cross-layer imports")
    assert decision.selected is True
    assert decision.skill_name == "architecture-boundary-audit"


# ==================================================================
# Scenario 6: Invalid SKILL.md
# ==================================================================

def test_dogfood_broken_skill_rejected():
    """broken-skill 的 SKILL.md 没有 frontmatter，解析应失败。"""
    from agent.skill_system.errors import CODE_MISSING_FRONTMATTER, SkillLoadError

    with pytest.raises(SkillLoadError) as exc_info:
        load_skill_manifest(DOGFOOD_ROOT / "broken-skill" / "SKILL.md")
    assert exc_info.value.code == CODE_MISSING_FRONTMATTER


# ==================================================================
# Scenario 7: Disabled / Hidden Skill
# ==================================================================

def test_dogfood_disabled_skill_not_visible(dogfood_registry):
    """disabled 状态的 Skill 不应在可见列表中。"""
    visible = dogfood_registry.list_visible()
    names = {d.name for d in visible}
    assert "internal-release-signer" not in names


def test_dogfood_disabled_skill_descriptor_exists(dogfood_registry):
    """disabled Skill 的 descriptor 存在但 is_visible 返回 False。"""
    desc = dogfood_registry.get_descriptor("internal-release-signer")
    assert desc is not None
    assert desc.is_visible() is False


def test_dogfood_disabled_skill_not_selected():
    """disabled Skill 不能被 selector 选中。"""
    registry = SkillRegistry(roots=[DOGFOOD_ROOT])
    selector = SkillSelector(registry)
    decision = selector.select("Use the internal-release-signer skill")
    assert decision.selected is False or decision.skill_name != "internal-release-signer"


# ==================================================================
# Scenario 8: Ambiguous Skill Selection
# ==================================================================

def test_dogfood_ambiguous_selection():
    """同时匹配 tdd-repair 和 architecture-boundary-audit 时给出替代项。"""
    registry = SkillRegistry(roots=[DOGFOOD_ROOT])
    selector = SkillSelector(registry)
    decision = selector.select("Repair this failing test and check architecture boundaries")
    assert "tdd-repair" in decision.alternatives or decision.skill_name in ("tdd-repair", "architecture-boundary-audit")


# ==================================================================
# 禁止行为
# ==================================================================

def test_dogfood_no_legacy_imports():
    """dogfood fixtures 和测试本身不应导入 legacy_skills。"""
    import ast

    p = Path(__file__)
    tree = ast.parse(p.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("agent.legacy_skills")
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("agent.legacy_skills")


def test_dogfood_registry_deterministic(dogfood_registry):
    """dogfood registry 扫描结果应确定。"""
    first = {d.name for d in dogfood_registry.list_visible()}
    second = {d.name for d in dogfood_registry.list_visible()}
    assert first == second


# ==================================================================
# 扩展场景 A: On-demand Resources（渐进式加载 Level 3）
# ==================================================================

def test_dogfood_on_demand_resources_descriptor(dogfood_registry):
    """on-demand-resources Skill 应正确注册。"""
    desc = dogfood_registry.get_descriptor("on-demand-resources")
    assert desc is not None
    assert desc.status == "active"
    assert desc.risk_level == "low"


def test_dogfood_on_demand_resources_body_loaded(dogfood_loader):
    """body 应在选中后按需加载，Level 3 resources 不自动加载。"""
    body = dogfood_loader.load_body("on-demand-resources")
    assert "渐进式加载" in body
    # body 应包含关于 Level 3 资源仅为 on-demand 的说明
    assert "显式" in body and "请求" in body


def test_dogfood_on_demand_resource_loadable(dogfood_loader):
    """显式请求的 resource 应可加载。—— resource_path 是相对于 category 目录的路径。"""
    content = dogfood_loader.load_resource(
        "on-demand-resources", "references", "guide.md"
    )
    assert "Reference" in content or "Guide" in content


def test_dogfood_on_demand_resource_path_traversal_blocked(dogfood_loader):
    """路径穿越的 resource 请求应被拒绝。"""
    with pytest.raises(Exception):
        dogfood_loader.load_resource(
            "on-demand-resources", "references", "../secrets/.env"
        )


def test_dogfood_on_demand_no_script_execution():
    """script resource 路径不应被加载执行（loader 强制不执行）。"""
    registry = SkillRegistry(roots=[DOGFOOD_ROOT])
    loader = SkillLoader(registry)
    desc = registry.get_descriptor("on-demand-resources")
    assert desc is not None
    # 不允许的 resource category 应报错
    with pytest.raises(Exception):
        loader.load_resource("on-demand-resources", "scripts", "run.sh")


# ==================================================================
# 扩展场景 B: Checkpoint Resume 安全验证
# ==================================================================

def test_dogfood_checkpoint_correlation_no_body():
    """SkillCheckpointCorrelation 不应包含 SDK body 或 resource 内容。"""
    from agent.skill_system.checkpoint import SkillCheckpointCorrelation

    corr = SkillCheckpointCorrelation(
        skill_name="git-status-audit",
        skill_version="0.1.0",
        audit_id="dogfood-audit-001",
        loaded_level=2,
        loaded_resources=("references/guide.md",),
        pending_confirmation=False,
        invocation_status="in_flight",
    )
    assert not hasattr(corr, "body")
    assert not hasattr(corr, "resource_contents")
    assert corr.skill_name == "git-status-audit"


def test_dogfood_checkpoint_no_secrets():
    """checkpoint data 不应包含 secret-like 内容。"""
    from agent.skill_system.checkpoint import is_checkpoint_safe

    assert is_checkpoint_safe({"skill_name": "test", "note": "ok"}) is True
    assert is_checkpoint_safe({"key": "sk-proj-0123456789abcdefghijklmnopqrstuv"}) is False
    assert is_checkpoint_safe({"body": "x" * 100_000}) is False


def test_dogfood_checkpoint_note_builds_from_descriptor(dogfood_registry):
    """checkpoint note 可从 descriptor 构建。"""
    from agent.skill_system.checkpoint import build_invocation_checkpoint_note

    desc = dogfood_registry.get_descriptor("git-status-audit")
    assert desc is not None
    note = build_invocation_checkpoint_note(
        descriptor=desc,
        audit_id="d-audit",
        loaded_level=2,
        invocation_status="in_flight",
    )
    assert "git-status-audit" in note
    assert "d-audit" in note


def test_dogfood_checkpoint_module_no_loop():
    """checkpoint.py 不应实现 Agent loop。"""
    from agent.skill_system import checkpoint as cp

    for attr in dir(cp):
        assert "loop" not in attr.lower(), f"checkpoint has loop attr: {attr}"


# ==================================================================
# 扩展场景 C: Failure Fallback（fail-closed）
# ==================================================================

def test_dogfood_failure_fallback_invalid_skill():
    """无效 SKILL.md 应返回 fail-closed 且不执行工具。"""
    from agent.skill_system.invocation import SkillInvocationRequest, invoke_skill
    from agent.skill_system.loader import SkillLoader

    registry = SkillRegistry(roots=[DOGFOOD_ROOT])
    loader = SkillLoader(registry)

    # 请求一个不存在的 Skill
    request = SkillInvocationRequest(
        skill_name="nonexistent-skill",
        user_goal="test",
    )
    result = invoke_skill(request, registry, loader, audit_id="audit-fail")
    assert result.ok is False
    assert len(result.errors) > 0
    # 失败时不应有可见输出
    assert result.visible_output_preview == ""
    # safe_preview 不应包含 secret
    audit = result.audit_record
    assert audit is not None
    assert "sk-" not in audit.safe_preview.lower()


def test_dogfood_failure_fallback_no_memory_write():
    """invocation 失败时不应有 memory_proposals。"""
    from agent.skill_system.invocation import SkillInvocationRequest, invoke_skill
    from agent.skill_system.loader import SkillLoader

    registry = SkillRegistry(roots=[DOGFOOD_ROOT])
    loader = SkillLoader(registry)
    request = SkillInvocationRequest(skill_name="nonexistent-skill")
    result = invoke_skill(request, registry, loader, audit_id="audit-fail2")
    assert result.ok is False
    assert len(result.memory_proposals) == 0


def test_dogfood_failure_fallback_sanitized_error():
    """失败时的 error safe_preview 不暴露敏感信息。"""
    from agent.skill_system.invocation import SkillInvocationRequest, invoke_skill
    from agent.skill_system.loader import SkillLoader

    registry = SkillRegistry(roots=[DOGFOOD_ROOT])
    loader = SkillLoader(registry)
    request = SkillInvocationRequest(skill_name="nonexistent-skill")
    result = invoke_skill(request, registry, loader, audit_id="audit-fail3")
    assert not result.ok
    for err in result.errors:
        assert "sk-" not in err.safe_preview
        assert err.safe_preview != ""


def test_dogfood_failure_hidden_skill_blocked():
    """disabled Skill 调用被阻止，不返回 body。"""
    from agent.skill_system.invocation import SkillInvocationRequest, invoke_skill
    from agent.skill_system.loader import SkillLoader

    registry = SkillRegistry(roots=[DOGFOOD_ROOT])
    loader = SkillLoader(registry)
    request = SkillInvocationRequest(skill_name="internal-release-signer")
    result = invoke_skill(request, registry, loader, audit_id="audit-dd")
    assert result.ok is False
    assert result.visible_output == ""


# ==================================================================
# 扩展场景 D: Memory Dogfood Skill（Memory 边界）
# ==================================================================

def test_dogfood_memory_skill_descriptor(dogfood_registry):
    """memory-dogfood-skill 应存在且声明 propose_memory。"""
    desc = dogfood_registry.get_descriptor("memory-dogfood-skill")
    assert desc is not None
    assert desc.memory_scope == "propose_memory"


def test_dogfood_memory_skill_selector():
    """selector 应能选中 memory-dogfood-skill。"""
    registry = SkillRegistry(roots=[DOGFOOD_ROOT])
    selector = SkillSelector(registry)
    decision = selector.select("Design a synthetic memory dogfood case for preference evolution")
    assert decision.selected is True
    assert decision.skill_name == "memory-dogfood-skill"


def test_dogfood_memory_skill_body(dogfood_loader):
    """memory-dogfood-skill body 应声明不能直接写 Memory。"""
    body = dogfood_loader.load_body("memory-dogfood-skill")
    assert "propose_memory" in body or "Memory" in body
    assert "不能" in body or "can" in body.lower()


def test_dogfood_memory_proposal_no_direct_write():
    """MemoryProposal 结构体没有 write/persist/save 方法——只能提案。"""
    from agent.skill_system.memory_boundary import MemoryProposal

    proposal = MemoryProposal(
        content="user prefers concise responses",
        category="user_preference",
        confidence=0.8,
        source_skill="memory-dogfood-skill",
    )
    assert not hasattr(proposal, "write")
    assert not hasattr(proposal, "persist")
    assert not hasattr(proposal, "save")


def test_dogfood_memory_boundary_no_auto_approve():
    """propose_memory Skill 也不能自动批准自己的 proposal。"""
    from agent.skill_system.memory_boundary import (
        MemoryContextPolicy,
        check_memory_proposal,
    )
    policy = MemoryContextPolicy(
        can_read=True,
        can_propose=False,  # governance 尚未批准
        approved_categories=frozenset(),
    )
    desc = SkillRegistry(roots=[DOGFOOD_ROOT]).get_descriptor("memory-dogfood-skill")
    assert desc is not None
    result = check_memory_proposal(desc, policy, "user_preference")
    assert result is False  # governance 未批准


# ==================================================================
# 扩展场景 E: Safe Local File Summarization Skill
# ==================================================================

def test_dogfood_safe_file_skill_descriptor(dogfood_registry):
    """safe-local-file-summarization Skill 应正确注册。"""
    desc = dogfood_registry.get_descriptor("safe-local-file-summarization")
    assert desc is not None
    assert desc.status == "active"
    assert desc.risk_level == "medium"
    assert "read_file" in desc.allowed_tools


def test_dogfood_safe_file_skill_body_forbids_sensitive(dogfood_loader):
    """body 应明确禁止 .env / agent_log / sessions / runs。"""
    body = dogfood_loader.load_body("safe-local-file-summarization")
    assert ".env" in body
    assert "agent_log" in body
    assert "sessions" in body or "runs" in body


def test_dogfood_safe_file_skill_no_network_tool():
    """safe-local-file-summarization 不应允许网络工具。"""
    registry = SkillRegistry(roots=[DOGFOOD_ROOT])
    desc = registry.get_descriptor("safe-local-file-summarization")
    assert desc is not None
    assert "fetch_url" not in desc.allowed_tools
    assert "run_shell" not in desc.allowed_tools


# ==================================================================
# 扩展场景 F: High-risk Tool Rejection（独立验证）
# ==================================================================

def test_dogfood_high_risk_tool_descriptor(dogfood_registry):
    """high-risk-tool-skill 应正确注册为 high risk。"""
    desc = dogfood_registry.get_descriptor("high-risk-tool-skill")
    assert desc is not None
    assert desc.risk_level == "high"
    assert "run_shell" in desc.allowed_tools


def test_dogfood_high_risk_confirmation_preserved():
    """高风险工具 run_shell 的 confirmation 不能被 Skill 降低。"""
    registry = SkillRegistry(roots=[DOGFOOD_ROOT])
    desc = registry.get_descriptor("high-risk-tool-skill")
    assert desc is not None
    tool_reg = _FakeToolRegistry()
    binding = SkillToolBinding(desc, tool_reg)
    result = binding.check("run_shell")
    assert result.allowed is True
    # confirmation 仍为 always（ToolRegistry 权威不变）
    assert result.requires_confirmation is True


def test_dogfood_high_risk_unknown_tool_blocked():
    """不在 allowed_tools 中的高风险工具应被 blocked。"""
    registry = SkillRegistry(roots=[DOGFOOD_ROOT])
    desc = registry.get_descriptor("high-risk-tool-skill")
    assert desc is not None
    tool_reg = _FakeToolRegistry()
    binding = SkillToolBinding(desc, tool_reg)
    result = binding.check("fetch_url")
    assert result.allowed is False


# ==================================================================
# 扩展场景 G: prompt-writing / architecture-boundary-audit 集成增强
# ==================================================================

def test_dogfood_prompt_writing_body_loading(dogfood_loader):
    """prompt-writing 的 body 可加载且包含 prompt 相关内容。"""
    body = dogfood_loader.load_body("prompt-writing")
    assert "prompt" in body.lower()
    assert len(body) > 10


def test_dogfood_prompt_writing_tool_binding():
    """prompt-writing 的 allowed_tools 正确绑定。"""
    registry = SkillRegistry(roots=[DOGFOOD_ROOT])
    desc = registry.get_descriptor("prompt-writing")
    assert desc is not None
    tool_reg = _FakeToolRegistry()
    binding = SkillToolBinding(desc, tool_reg)
    result = binding.check("read_file")
    assert result.allowed is True
    # prompt-writing 不应允许 run_shell
    shell_result = binding.check("run_shell")
    assert shell_result.allowed is False


def test_dogfood_architecture_boundary_audit_body(dogfood_loader):
    """architecture-boundary-audit 的 body 可加载。"""
    body = dogfood_loader.load_body("architecture-boundary-audit")
    assert "边界" in body or "boundary" in body.lower() or "import" in body.lower()


def test_dogfood_architecture_boundary_audit_tools(dogfood_registry):
    """architecture-boundary-audit 允许 run_shell 和 read_file。"""
    desc = dogfood_registry.get_descriptor("architecture-boundary-audit")
    assert desc is not None
    assert "run_shell" in desc.allowed_tools
    assert "read_file" in desc.allowed_tools


def test_dogfood_prompt_section_excludes_hidden(dogfood_registry):
    """prompt section 不应包含 disabled Skill。"""
    from agent.skill_system.prompt_section import build_skills_prompt_section

    section = build_skills_prompt_section(dogfood_registry)
    assert "internal-release-signer" not in section


def test_dogfood_invocation_generates_audit(dogfood_registry):
    """invocation 应为 prompt-writing 生成 audit record。"""
    from agent.skill_system.invocation import SkillInvocationRequest, invoke_skill
    from agent.skill_system.loader import SkillLoader

    loader = SkillLoader(dogfood_registry)
    request = SkillInvocationRequest(
        skill_name="prompt-writing",
        user_goal="Write a prompt section",
        selection_reason="keyword match",
    )
    result = invoke_skill(request, dogfood_registry, loader, audit_id="audit-int")
    assert result.ok is True
    assert result.audit_record is not None
    assert result.audit_record.skill_name == "prompt-writing"
    assert result.audit_record.result_status == "ok"
    assert result.audit_record.loaded_levels > 0
