"""TargetCatalog extraction boundary tests.

After the extraction commit, ``RuntimeActionTargetCatalog`` and its
descriptor / binding surface live in
``agent.runtime_integration.target_catalog``. The class remains
importable from ``agent.runtime_integration.evidence`` for back-compat.
"""

from __future__ import annotations

from agent.runtime_integration.schema import RuntimeActionType
from agent.runtime_integration.target_catalog import (
    RuntimeActionTargetCatalog,
    RuntimeActionTargetDescriptor,
)


def test_resolve_returns_descriptor_for_skill_select() -> None:
    """Catalog must resolve a known SKILL_SELECT binding via the new module."""
    binding = RuntimeActionTargetCatalog.resolve(
        action_type=RuntimeActionType.SKILL_SELECT.value,
        handler_name="SkillRuntimeActionHandler",
        handler_identity="agent.runtime_integration.skill_action.SkillRuntimeActionHandler",
        target_module="SkillLoader",
        operation="load_body",
    )
    assert isinstance(binding, RuntimeActionTargetDescriptor)
    assert binding.invocation_adapter_id == "SkillLoader.load_body"


def test_evidence_module_re_exports_target_catalog() -> None:
    """``agent.runtime_integration.evidence`` must re-export the catalog
    so existing import paths and tests keep working."""
    import agent.runtime_integration.evidence as evidence
    import agent.runtime_integration.target_catalog as target_catalog

    assert evidence.RuntimeActionTargetCatalog is target_catalog.RuntimeActionTargetCatalog
    assert evidence.RuntimeActionTargetDescriptor is target_catalog.RuntimeActionTargetDescriptor


def test_callable_identity_still_uses_function_module_path() -> None:
    """After extraction, helper identities resolve to the new module path
    but keep the stable ``function:<module>.<qualname>`` shape."""
    from agent.runtime_integration.target_catalog import (
        _callable_identity,
        _lookup_tool_registry_entry_adapter,
    )

    ident = _callable_identity(_lookup_tool_registry_entry_adapter)
    assert ident.startswith("function:agent.runtime_integration.target_catalog."), ident

