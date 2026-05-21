"""skill.select RuntimeAction handler."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping

from agent.runtime_integration.dispatcher import RuntimeActionContext
from agent.runtime_integration.schema import RuntimeActionRequest
from agent.skill_system.loader import SkillLoader
from agent.skill_system.registry import SkillRegistry


_CONFIDENCE_VALUES = frozenset({"high", "medium", "low"})


class SkillRuntimeActionHandler:
    """把 RuntimeAction skill.select 路由到 SkillRegistry/SkillLoader。

    Handler 只验证 model_decision_metadata，不做 SkillSelector 关键词选择，也不
    根据自然语言补写 selection_reason / selection_confidence。
    """

    def __init__(
        self,
        *,
        registry: SkillRegistry,
        loader: SkillLoader,
        visible_tool_names: set[str] | None = None,
    ) -> None:
        self._registry = registry
        self._loader = loader
        self._visible_tool_names = set(visible_tool_names or ())

    @classmethod
    def from_roots(
        cls,
        roots: Iterable[Path],
        *,
        visible_tool_names: set[str] | None = None,
    ) -> "SkillRuntimeActionHandler":
        registry = SkillRegistry(roots=[Path(root) for root in roots])
        return cls(
            registry=registry,
            loader=SkillLoader(registry),
            visible_tool_names=visible_tool_names,
        )

    def handle(self, request: RuntimeActionRequest, context: RuntimeActionContext):
        payload = _plain_mapping(request.payload)
        metadata = _plain_mapping(payload.get("model_decision_metadata") or {})
        selected_skill_id = metadata.get("selected_skill_id")
        selection_reason = metadata.get("selection_reason")
        selection_confidence = metadata.get("selection_confidence")
        available_metadata = [_plain_mapping(item) for item in payload.get("available_skill_metadata", ())]

        failure = self._validate_payload(
            payload=payload,
            metadata=metadata,
            available_metadata=available_metadata,
        )
        if failure:
            return context.failed(
                handler_name=type(self).__name__,
                target_module="SkillLoader",
                payload={
                    "selected_skill_id": selected_skill_id,
                    "body_load_decision": False,
                    "no_suitable_skill": not bool(available_metadata),
                    "failure_reason": failure,
                },
                observed_call=None,
                evidence_extra={
                    "selected_skill_id": selected_skill_id,
                    "selection_reason": selection_reason,
                    "selection_confidence": selection_confidence,
                    "body_load_decision": False,
                    "no_suitable_skill": not bool(available_metadata),
                    "runtime_e2e_disqualified_reason": failure,
                    "audit_only_skill_exclusion_evidence": self._audit_exclusion_evidence(),
                },
                error_safe_preview=failure,
            )

        descriptor = self._registry.get_descriptor(str(selected_skill_id))
        if descriptor is None or not descriptor.is_visible():
            return context.failed(
                handler_name=type(self).__name__,
                target_module="SkillLoader",
                payload={
                    "selected_skill_id": selected_skill_id,
                    "body_load_decision": False,
                    "no_suitable_skill": True,
                    "failure_reason": "selected skill is not available",
                },
                observed_call=None,
                evidence_extra={
                    "selected_skill_id": selected_skill_id,
                    "selection_reason": selection_reason,
                    "selection_confidence": selection_confidence,
                    "runtime_e2e_disqualified_reason": "selected skill is not available",
                    "audit_only_skill_exclusion_evidence": self._audit_exclusion_evidence(),
                },
                error_safe_preview="selected skill is not available",
            )

        if self._visible_tool_names and not (set(descriptor.allowed_tools) & self._visible_tool_names):
            return context.rejected(
                handler_name=type(self).__name__,
                target_module="SkillLoader",
                payload={
                    "selected_skill_id": selected_skill_id,
                    "body_load_decision": False,
                    "no_suitable_skill": False,
                    "failure_reason": "selected skill has no visible allowed tools",
                },
                observed_call=None,
                evidence_extra={
                    "selected_skill_id": selected_skill_id,
                    "selection_reason": selection_reason,
                    "selection_confidence": selection_confidence,
                    "runtime_e2e_disqualified_reason": "selected skill has no visible allowed tools",
                    "audit_only_skill_exclusion_evidence": self._audit_exclusion_evidence(),
                },
                error_safe_preview="selected skill has no visible allowed tools",
            )

        observed = context.invoke_registered_target(
            target_module="SkillLoader",
            operation="load_body",
            payload={"loader": self._loader, "skill_id": str(selected_skill_id)},
        )
        body = str(observed.value)
        result_payload = {
            "selected_skill_id": selected_skill_id,
            "selection_reason": selection_reason,
            "selection_confidence": selection_confidence,
            "body_load_decision": True,
            "allowed_tools_after_selection": list(descriptor.allowed_tools),
            "no_suitable_skill": False,
            "available_skills_count": len(available_metadata),
            "available_skill_metadata": available_metadata,
            "loaded_body_preview": body[:200],
        }
        return context.success(
            handler_name=type(self).__name__,
            target_module="SkillLoader",
            payload=result_payload,
            observed_call=observed,
            evidence_extra={
                **{key: result_payload[key] for key in (
                    "selected_skill_id",
                    "selection_reason",
                    "selection_confidence",
                    "body_load_decision",
                    "no_suitable_skill",
                )},
                "selection_metadata_source": "RuntimeActionRequest.payload.model_decision_metadata",
                "handler_selected_skill": False,
                "handler_called_llm_for_selection": False,
                "audit_only_skill_exclusion_evidence": self._audit_exclusion_evidence(),
            },
        )

    def _validate_payload(
        self,
        *,
        payload: Mapping[str, Any],
        metadata: Mapping[str, Any],
        available_metadata: list[dict[str, Any]],
    ) -> str | None:
        if not str(payload.get("task_summary") or "").strip():
            return "task_summary is required"
        if not available_metadata:
            return "available_skill_metadata is empty"
        for item in available_metadata:
            if "body" in item or "status" in item:
                return "available_skill_metadata contains forbidden field"
        registry_visible_ids = {descriptor.name for descriptor in self._registry.list_visible()}
        metadata_visible_ids = {str(item.get("skill_id") or "") for item in available_metadata}
        if "" in metadata_visible_ids:
            return "available_skill_metadata contains invalid skill_id"
        if metadata_visible_ids != registry_visible_ids:
            # 中文学习注释：model-visible metadata 必须来自 registry 的 visible
            # list。只禁止 body/status 不够，因为 hidden/disabled id 本身也会泄露
            # capability surface，并可能让模型选择一个本不该看见的 Skill。
            return "available_skill_metadata does not match registry visible skills"
        selected_skill_id = metadata.get("selected_skill_id")
        selection_reason = metadata.get("selection_reason")
        selection_confidence = metadata.get("selection_confidence")
        if not selected_skill_id:
            return "selected_skill_id missing from model_decision_metadata"
        if not selection_reason:
            return "selection_reason missing from model_decision_metadata"
        if selection_confidence not in _CONFIDENCE_VALUES:
            return "selection_confidence missing or invalid"
        compatible_selected = payload.get("selected_skill_id")
        if compatible_selected is not None and compatible_selected != selected_skill_id:
            return "selected_skill_id compatibility field mismatch"
        visible_ids = {item.get("skill_id") for item in available_metadata}
        if selected_skill_id not in visible_ids:
            return "selected_skill_id not present in model-visible metadata"
        return None

    def _audit_exclusion_evidence(self) -> dict[str, Any]:
        descriptors = getattr(self._registry, "_descriptors", {})
        excluded_count = sum(1 for desc in descriptors.values() if not desc.is_visible())
        load_error_count = len(self._registry.get_load_errors())
        categories: list[str] = []
        if excluded_count:
            categories.append("status_hidden_or_disabled")
        if load_error_count:
            categories.append("manifest_invalid")
        return {
            "hidden_or_disabled_exclusion_verified": True,
            "excluded_count": excluded_count + load_error_count,
            "redacted_exclusion_reason_categories": categories,
        }


def _plain_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(key): _plain_mapping(item) if isinstance(item, Mapping) else item for key, item in value.items()}
    return {}
