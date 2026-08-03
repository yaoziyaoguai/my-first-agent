"""Governed Skill activation/resource tools.

每个 Skill 映射为一个 ``skill__<name>`` READ_ONLY activation tool，另有共享的
``skill__read_resource``。所有读取经 catalog 的 no-follow + digest 校验；漂移返回
``KnownNotExecuted``（READ_ONLY，不进 recovery），完整 activation result 不超过
``max_tool_result_chars`` 且不静默截断。

Skill ``name`` 仅允许小写字母、数字与单个连字符，因此 ``skill__read_resource``（下划线）
永远不会与任何 activation 工具名碰撞，不需要 canonicalization。
"""

from __future__ import annotations

from agent.runtime.contracts import (
    ApprovalPolicy,
    KnownNotExecuted,
    OutputPolicy,
    PolicyDecision,
    SideEffectClass,
    ToolRisk,
    ToolSpec,
)
from agent.runtime.tools import RegisteredTool
from agent.skill.catalog import (
    SkillCatalog,
    SkillCatalogError,
    SkillDescriptor,
    SkillSecurityError,
)

RESOURCE_TOOL = "skill__read_resource"
SKILL_TOOL_POLICY_VERSION = "skill-tool-v1"
_DESCRIPTION_LIMIT = 200


class _SkillToolPolicy:
    """Skill 工具统一为 READ_ONLY + 永不审批；policy identity 进入 intent binding。"""

    identity = SKILL_TOOL_POLICY_VERSION

    def evaluate(
        self,
        spec: ToolSpec,
        arguments,  # noqa: ARG002
        binding,  # noqa: ARG002
    ) -> PolicyDecision:
        return PolicyDecision.ALLOW


def build_skill_tool_registrations(
    catalog: SkillCatalog,
    *,
    max_tool_result_chars: int,
) -> tuple[RegisteredTool, ...]:
    """从 catalog 产出每个 Skill 一个 activation registration + 一个共享 resource registration。"""
    if max_tool_result_chars < 1:
        raise ValueError("max_tool_result_chars must be positive")
    registrations: list[RegisteredTool] = []
    policy = _SkillToolPolicy()
    for descriptor in catalog.descriptors:
        registrations.append(
            RegisteredTool(
                _activation_spec(descriptor, catalog, max_tool_result_chars),
                _make_activation_callable(descriptor.name, catalog, max_tool_result_chars),
                policy=policy,
            )
        )
    registrations.append(
        RegisteredTool(
            _resource_spec(catalog, max_tool_result_chars),
            _make_resource_callable(catalog),
            policy=policy,
        )
    )
    return tuple(registrations)


def _activation_spec(
    descriptor: SkillDescriptor,
    catalog: SkillCatalog,
    max_tool_result_chars: int,
) -> ToolSpec:
    return ToolSpec(
        name=f"skill__{descriptor.name}",
        version="1",
        description=_bounded_description(descriptor),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        risk=ToolRisk.LOW,
        side_effect=SideEffectClass.READ_ONLY,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.NEVER,
        safety_policy={
            "kind": "skill_activation",
            "skill_name": descriptor.name,
            "skill_identity": descriptor.identity_digest,
            "catalog_digest": catalog.catalog_digest,
        },
        output_limit_chars=max_tool_result_chars,
    )


def _resource_spec(catalog: SkillCatalog, max_tool_result_chars: int) -> ToolSpec:
    return ToolSpec(
        name=RESOURCE_TOOL,
        version="1",
        description="Read one bounded resource (references/ or assets/) of an activated skill.",
        input_schema={
            "type": "object",
            "properties": {
                "skill_name": {"type": "string"},
                "path": {"type": "string"},
            },
            "required": ["skill_name", "path"],
            "additionalProperties": False,
        },
        risk=ToolRisk.LOW,
        side_effect=SideEffectClass.READ_ONLY,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.NEVER,
        safety_policy={
            "kind": "skill_resource",
            "catalog_digest": catalog.catalog_digest,
        },
        output_limit_chars=max_tool_result_chars,
    )


def _make_activation_callable(name, catalog, max_tool_result_chars):
    def activate(intent):  # noqa: ARG001
        try:
            activation = catalog.read_activation(name)
            descriptor = catalog.descriptor_for(name)
        except SkillSecurityError:
            return KnownNotExecuted(
                code="skill_drift",
                message="skill content drifted; rebuild the catalog",
            )
        except SkillCatalogError:
            return KnownNotExecuted(
                code="skill_unavailable",
                message="skill is no longer available",
            )
        content = _format_activation(activation, descriptor)
        if len(content) > max_tool_result_chars:
            # 无法完整返回 activation result 时，不能截断后假装成功。
            return KnownNotExecuted(
                code="activation_too_large",
                message="skill activation exceeds the result budget",
            )
        return content

    return activate


def _make_resource_callable(catalog):
    def read_resource(intent):
        skill_name = intent.arguments["skill_name"]
        path = intent.arguments["path"]
        try:
            return catalog.read_resource(skill_name, path)
        except SkillSecurityError:
            return KnownNotExecuted(
                code="resource_drift",
                message="resource drifted; rebuild the catalog",
            )
        except SkillCatalogError:
            return KnownNotExecuted(
                code="resource_unavailable",
                message="resource is not available",
            )

    return read_resource


def _format_activation(activation, descriptor: SkillDescriptor) -> str:
    body = activation.body
    if not descriptor.resources:
        return body
    lines = [
        body.rstrip(),
        "",
        "Available resources (use skill__read_resource):",
    ]
    lines.extend(f"- {resource.relative_path}" for resource in descriptor.resources)
    return "\n".join(lines) + "\n"


def _bounded_description(descriptor: SkillDescriptor) -> str:
    description = descriptor.description
    label = f"Activate the '{descriptor.name}' skill. "
    if len(label) + len(description) <= _DESCRIPTION_LIMIT:
        return label + description
    room = max(0, _DESCRIPTION_LIMIT - len(label) - 1)
    return label + description[:room] + "…"
