"""Runtime 拥有的工具治理知识：capability 特定的 intent preparation 裁决。

KernelToolRuntime.prepare/invoke 仍是唯一外部接口与最终权限/effect gate；
本模块只持有从其分支收拢的治理知识，capability callable/adapter 不能自我
授权。已收拢的簇：citation（sidecar 写入 canonical 化、manifest builder
准入、binding 失败映射）与 source（authority 门、governed outcome 归一）。
prepare 裁决只携带治理事实（code/message/canonical 参数），
known-not-executed ToolResult 仍由 KernelToolRuntime 统一铸造；invoke 侧的
source 归一直接产出 ToolResult（receipt 由 Kernel 语义铸造，见
SourceGovernance.normalize_result）。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

from agent.runtime.contracts import (
    CitationManifestV1,
    ExecutionIntent,
    JSONValue,
    PolicyDecision,
    SideEffectClass,
    SourceReceiptV1,
    ToolExecutionOutput,
    ToolPrepareContext,
    ToolResult,
    ToolSpec,
)


class BrowserActionToolPolicy:
    """Runtime-owned browser action policy；callable 不能自行降级 consequence。"""

    identity = "browser-action-tool-policy-v1"

    def evaluate(
        self,
        spec: ToolSpec,
        arguments: dict[str, JSONValue],
        binding: dict[str, JSONValue],
    ) -> PolicyDecision:
        del arguments
        if spec.safety_policy.get("kind") != "browser_action":
            return PolicyDecision.DENY
        return (
            PolicyDecision.ALLOW
            if binding.get("consequence") == "observe"
            else PolicyDecision.REQUIRE_APPROVAL
        )


class BrowserGovernance:
    """BROWSER_SESSION callable outcome 的 closed Runtime normalization。"""

    identity = "browser-tool-governance-v1"
    _KINDS = frozenset(
        {
            "browser_open",
            "browser_observe",
            "browser_action",
            "browser_close",
        }
    )

    def normalize_result(
        self,
        intent: ExecutionIntent,
        spec: ToolSpec,
        draft: ToolExecutionOutput,
    ) -> ToolResult:
        kind = spec.safety_policy.get("kind")
        if (
            kind not in self._KINDS
            or draft.source_receipts
            or draft.metadata.get("browser_result_kind") != kind
        ):
            return ToolResult(
                tool_call_id=intent.tool_call_id,
                content="Browser tool returned an invalid governed outcome.",
                is_error=True,
                executed=draft.executed,
                metadata={
                    "code": "browser_result_contract_mismatch",
                    "tool_identity": spec.identity_digest,
                },
            )
        return ToolResult(
            tool_call_id=intent.tool_call_id,
            content=draft.content[: spec.output_limit_chars],
            is_error=draft.is_error,
            executed=draft.executed,
            metadata={
                **draft.metadata,
                "truncated": len(draft.content) > spec.output_limit_chars,
                "tool_identity": spec.identity_digest,
            },
        )


@dataclass(frozen=True, slots=True)
class GovernanceRejection:
    """prepare 阶段的治理拒绝（known-not-executed），由 Runtime 转 ToolResult。"""

    code: str
    message: str


@dataclass(frozen=True, slots=True)
class CitationIntentRuling:
    """citation intent 裁决：canonical 化参数、拒绝或原样放行。"""

    canonical_arguments: dict[str, JSONValue] | None = None
    rejection: GovernanceRejection | None = None


class CitationGovernance:
    identity = "citation-tool-governance-v1"

    def assess_intent(
        self,
        *,
        tool_name: str,
        side_effect: SideEffectClass,
        safety_policy: dict[str, JSONValue],
        arguments: dict[str, JSONValue],
        context: ToolPrepareContext,
    ) -> CitationIntentRuling:
        """裁决一次 citation 相关的 intent preparation。

        sidecar 写入 canonical 化先于 builder 门（与原 KernelToolRuntime
        分支顺序一致）；非 citation 工具原样放行。
        """

        if (
            tool_name == "write_file"
            and side_effect is SideEffectClass.WRITE
            and isinstance(arguments.get("path"), str)
            and arguments["path"].endswith(".citations.json")
        ):
            canonical_manifest = self._canonical_sidecar_content(arguments, context)
            if canonical_manifest is None:
                exact_pairs = "; ".join(
                    f"{source_ref} -> {source_id}"
                    for source_ref, source_id in context.citable_citation_sources
                ) or "none"
                return CitationIntentRuling(
                    rejection=GovernanceRejection(
                        code="citation_manifest_required",
                        message=(
                            "Do not hand-write this sidecar. Follow these exact steps in order: "
                            "(1) read_file the artifact you just wrote (for example "
                            "research.md) so its exact content digest enters this run; "
                            "(2) call build_citation_manifest with the artifact path, the "
                            "exact artifact content you read back, and one citation pair "
                            "chosen from these exact citable pairs: "
                            f"{exact_pairs}; (3) write_file the sidecar by copying that "
                            "build_citation_manifest ToolResult byte-for-byte as content — "
                            "one transport-added final newline is accepted and removed. Any "
                            "other JSON is rejected before the effect."
                        ),
                    ),
                )
            return CitationIntentRuling(
                canonical_arguments={**arguments, "content": canonical_manifest},
            )

        if safety_policy.get("kind") == "citation_manifest_builder":
            return self._assess_manifest_builder(arguments, context)
        return CitationIntentRuling()

    def binding_failure(
        self,
        safety_policy: dict[str, JSONValue],
    ) -> GovernanceRejection | None:
        """把 binding 失败映射为 citation 专属拒绝；非 builder 返回 None。"""

        if safety_policy.get("kind") != "citation_manifest_builder":
            return None
        return GovernanceRejection(
            code="citation_manifest_invalid",
            message=(
                "The citation manifest arguments are structurally invalid. Use the "
                "current trusted_goal identity, exact artifact read-back text, one "
                "unique bracketed marker that occurs in that text, and each "
                "Runtime-advertised source_ref/source_id pair at most once. No effect "
                "occurred; correct the arguments and retry."
            ),
        )

    def _assess_manifest_builder(
        self,
        arguments: dict[str, JSONValue],
        context: ToolPrepareContext,
    ) -> CitationIntentRuling:
        if not context.citation_manifest_allowed:
            return CitationIntentRuling(
                rejection=GovernanceRejection(
                    code="citation_manifest_not_required",
                    message=(
                        "build_citation_manifest is available only when the active Goal "
                        "explicitly targets a .citations.json sidecar. Do not build a "
                        "manifest for this Goal; after the required file read-back, use "
                        "completion_claim with the advertised evidence refs."
                    ),
                )
            )

        artifact_path = arguments.get("artifact_path")
        if artifact_path not in context.citation_artifact_paths:
            allowed_paths = ", ".join(context.citation_artifact_paths) or "none"
            return CitationIntentRuling(
                rejection=GovernanceRejection(
                    code="citation_artifact_not_authorized",
                    message=(
                        "The citation manifest must describe a non-sidecar artifact target "
                        f"from the active Goal. Allowed artifact_path values: {allowed_paths}. "
                        "Read that artifact and pass its exact content; never cite the "
                        ".citations.json sidecar itself."
                    ),
                )
            )
        if context.goal_id is not None and (
            arguments.get("goal_id") != context.goal_id
            or arguments.get("goal_revision") != context.goal_revision
        ):
            return CitationIntentRuling(
                rejection=GovernanceRejection(
                    code="citation_goal_identity_mismatch",
                    message=(
                        "The citation manifest must copy goal_id and goal_revision exactly "
                        "from the current trusted_goal block. Do not use an earlier revision "
                        "or another identity; rebuild the manifest with the current "
                        "Runtime-owned identity and retry."
                    ),
                )
            )
        citations = arguments.get("citations")
        requested_refs = (
            tuple(
                citation.get("source_ref")
                for citation in citations
                if isinstance(citation, dict)
            )
            if isinstance(citations, list)
            else ()
        )
        requested_pairs = (
            tuple(
                (citation.get("source_ref"), citation.get("source_id"))
                for citation in citations
                if isinstance(citation, dict)
            )
            if isinstance(citations, list)
            else ()
        )
        allowed_pairs = set(context.citable_citation_sources)
        if (
            not requested_refs
            or len(requested_refs) != len(citations)
            or len(requested_pairs) != len(citations)
            or any(pair not in allowed_pairs for pair in requested_pairs)
        ):
            exact_pairs = "; ".join(
                f"{source_ref} -> {source_id}"
                for source_ref, source_id in context.citable_citation_sources
            ) or "none"
            return CitationIntentRuling(
                rejection=GovernanceRejection(
                    code="citation_source_not_citable",
                    message=(
                        "The only permitted citations are Runtime-verified non-truncated "
                        "source_ref/source_id pairs from the active Goal. Copy one of these "
                        f"exact pairs: {exact_pairs}. Remove denied citations; fetch another "
                        "complete source only when this list is empty; then rebuild the "
                        "manifest and rewrite its sidecar."
                    ),
                )
            )
        markers = tuple(
            citation.get("marker")
            for citation in citations
            if isinstance(citation, dict)
        )
        if (
            len(set(requested_pairs)) != len(requested_pairs)
            or len(set(markers)) != len(markers)
        ):
            return CitationIntentRuling(
                rejection=GovernanceRejection(
                    code="citation_entries_not_one_to_one",
                    message=(
                        "Citation manifest entries must be one-to-one. Use each exact source "
                        "pair once with one unique bracketed marker. If the same source "
                        "supports multiple statements, reuse its one marker in the artifact "
                        "instead of duplicating the manifest entry; then rebuild the sidecar."
                    ),
                )
            )
        return CitationIntentRuling()

    @staticmethod
    def _canonical_sidecar_content(
        arguments: dict[str, JSONValue],
        context: ToolPrepareContext,
    ) -> str | None:
        path = arguments.get("path")
        content = arguments.get("content")
        if (
            not context.citation_manifest_allowed
            or path not in context.citation_sidecar_paths
            or not isinstance(content, str)
        ):
            return None
        canonical = content[:-1] if content.endswith("\n") else content
        if (
            hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            not in context.citation_manifest_content_digests
        ):
            return None
        try:
            manifest = CitationManifestV1.from_json(canonical)
        except ValueError:
            return None
        if (
            manifest.goal_id != context.goal_id
            or manifest.goal_revision != context.goal_revision
            or manifest.artifact_path not in context.citation_artifact_paths
        ):
            return None
        return canonical


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class SourceGovernance:
    """governed source 工具的 authority 门与 outcome 归一。

    source callable 只能交出 ``ToolExecutionOutput`` 草稿；metadata 白名单、
    bounds 与 receipt 铸造（``SourceReceiptV1.create(draft, intent)`` 追加
    Runtime 执行身份）都由本归一执行——capability 不能自我授权或自铸 receipt。
    """

    identity = "source-tool-governance-v1"

    def assess_authority(
        self,
        *,
        authority_required: bool,
        arguments: dict[str, JSONValue],
        context: ToolPrepareContext,
    ) -> GovernanceRejection | None:
        """web 类 source 工具只允许 Runtime 验证过、未尝试的 search ref。"""

        if not authority_required:
            return None
        requested_source_ref = arguments.get("source_ref")
        if (
            context.source_authority is None
            or requested_source_ref not in context.web_fetch_source_refs
        ):
            exact_refs = ", ".join(context.web_fetch_source_refs) or "none"
            return GovernanceRejection(
                code="source_authority_required",
                message=(
                    "This tool requires a Runtime-verified, currently unattempted Web "
                    f"Search source reference. Exact permitted refs: {exact_refs}. Copy "
                    "one unchanged from FIRST_AGENT_RUNTIME_WEB_FETCH_REFS; do not use "
                    "a web_extracted_content or citation ref."
                ),
            )
        return None

    @staticmethod
    def normalize_result(
        intent: ExecutionIntent,
        spec: ToolSpec,
        raw_result: object,
    ) -> ToolResult:
        if not isinstance(raw_result, ToolExecutionOutput):
            return ToolResult(
                tool_call_id=intent.tool_call_id,
                content="Source tool returned an invalid output contract.",
                is_error=True,
                executed=True,
                metadata={"code": "source_output_required"},
            )
        if len(raw_result.content) > spec.output_limit_chars:
            return ToolResult(
                tool_call_id=intent.tool_call_id,
                content="Source tool output exceeded the configured limit.",
                is_error=True,
                executed=True,
                metadata={"code": "source_output_oversized"},
            )
        allowed_metadata = spec.safety_policy.get("source_metadata_keys", [])
        if not isinstance(allowed_metadata, list) or any(
            not isinstance(key, str) for key in allowed_metadata
        ):
            return ToolResult(
                tool_call_id=intent.tool_call_id,
                content="Source tool metadata policy is malformed.",
                is_error=True,
                executed=True,
                metadata={"code": "source_metadata_policy_invalid"},
            )
        if set(raw_result.metadata) - set(allowed_metadata):
            return ToolResult(
                tool_call_id=intent.tool_call_id,
                content="Source tool returned unauthorized metadata.",
                is_error=True,
                executed=True,
                metadata={"code": "source_metadata_invalid"},
            )
        metadata_bytes = _canonical_json(raw_result.metadata).encode("utf-8")
        if len(metadata_bytes) > min(spec.output_limit_chars, 8_192):
            return ToolResult(
                tool_call_id=intent.tool_call_id,
                content="Source tool metadata exceeded the configured limit.",
                is_error=True,
                executed=True,
                metadata={"code": "source_metadata_oversized"},
            )
        if len(raw_result.source_receipts) > 16:
            return ToolResult(
                tool_call_id=intent.tool_call_id,
                content="Source tool returned too many receipts.",
                is_error=True,
                executed=True,
                metadata={"code": "source_receipts_oversized"},
            )
        receipts: list[SourceReceiptV1] = []
        for draft in raw_result.source_receipts:
            if draft.source_kind not in spec.source_kinds:
                return ToolResult(
                    tool_call_id=intent.tool_call_id,
                    content="Source tool returned an unauthorized source kind.",
                    is_error=True,
                    executed=True,
                    metadata={"code": "source_kind_invalid"},
                )
            bounded_strings = (
                draft.origin_locator,
                draft.observed_at,
                draft.title or "",
                draft.content,
            )
            if any(len(value) > spec.output_limit_chars for value in bounded_strings):
                return ToolResult(
                    tool_call_id=intent.tool_call_id,
                    content="Source receipt draft exceeded the configured limit.",
                    is_error=True,
                    executed=True,
                    metadata={"code": "source_receipt_oversized"},
                )
            receipts.append(SourceReceiptV1.create(draft, intent))
        metadata = {
            **raw_result.metadata,
            "tool_identity": spec.identity_digest,
            "source_receipts": [
                {
                    **asdict(receipt),
                    "source_kind": receipt.source_kind.value,
                }
                for receipt in receipts
            ],
            "data_classes": sorted({receipt.data_class for receipt in receipts}),
            "source_refs": [
                {
                    "source_ref": f"source-ref:v1:{receipt.receipt_digest}",
                    "receipt_digest": receipt.receipt_digest,
                }
                for receipt in receipts
            ],
            "truncated": any(receipt.truncated for receipt in receipts),
        }
        return ToolResult(
            tool_call_id=intent.tool_call_id,
            content=raw_result.content,
            is_error=raw_result.is_error,
            executed=raw_result.executed,
            metadata=metadata,
        )
