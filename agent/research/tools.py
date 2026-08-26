"""生成 CitationManifestV1 canonical JSON 的纯 read-only primitive。"""

from __future__ import annotations

import hashlib

from agent.runtime.contracts import (
    ApprovalPolicy,
    CitationManifestV1,
    CitationV1,
    ExecutionAuthorityClass,
    ExecutionIntent,
    OutputPolicy,
    SideEffectClass,
    ToolRisk,
    ToolSpec,
)
from agent.runtime.tools import RegisteredTool


def build_research_tool_registrations() -> tuple[RegisteredTool, ...]:
    return (
        RegisteredTool(
            spec=_manifest_spec(),
            func=_build_manifest,
            prepare_binding=_prepare_manifest,
        ),
    )


def _prepare_manifest(arguments):  # noqa: ANN001
    manifest = _manifest_from_arguments(arguments)
    return {
        "operation": "build_citation_manifest",
        "manifest_digest": manifest.manifest_digest,
    }


def _build_manifest(intent: ExecutionIntent) -> str:
    return _manifest_from_arguments(intent.arguments).to_json()


def _manifest_from_arguments(arguments) -> CitationManifestV1:  # noqa: ANN001
    artifact_content = arguments.get("artifact_content")
    if not isinstance(artifact_content, str) or len(artifact_content) > 50_000:
        raise ValueError("artifact_content must be bounded text")
    raw_citations = arguments.get("citations")
    if not isinstance(raw_citations, list):
        raise ValueError("citations must be a list")
    citations: list[CitationV1] = []
    for item in raw_citations:
        if not isinstance(item, dict) or set(item) != {
            "marker",
            "source_ref",
            "source_id",
        }:
            raise ValueError("citation entry is malformed")
        source_ref = item["source_ref"]
        if (
            not isinstance(source_ref, str)
            or not source_ref.startswith("source-ref:v1:")
            or len(source_ref) != len("source-ref:v1:") + 64
        ):
            raise ValueError("citation source_ref is malformed")
        citations.append(
            CitationV1(
                marker=item["marker"],
                source_id=item["source_id"],
                receipt_digest=source_ref[len("source-ref:v1:") :],
            )
        )
    return CitationManifestV1.create(
        artifact_path=arguments.get("artifact_path"),
        artifact_sha256=hashlib.sha256(artifact_content.encode("utf-8")).hexdigest(),
        goal_id=arguments.get("goal_id"),
        goal_revision=arguments.get("goal_revision"),
        citations=tuple(citations),
    )


def _manifest_spec() -> ToolSpec:
    return ToolSpec(
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        name="build_citation_manifest",
        version="1.0.0",
        description=(
            "Build canonical CitationManifestV1 JSON from the exact artifact content "
            "and Runtime-issued opaque source_ref/source_id pairs. Choose an exact pair "
            "branch from this tool's current citations.items schema; generic Runtime "
            "source frames include non-citable refs. Never invent or mix a pair. This "
            "helper computes the artifact digest but does not verify source truth."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "artifact_path": {"type": "string"},
                "artifact_content": {
                    "type": "string",
                    "maxLength": 50_000,
                    "description": (
                        "Exact raw read_file ToolResult text obtained after writing the "
                        "artifact, byte-for-byte, including its final newline when present. "
                        "Do not reconstruct it from prior write_file arguments. Every literal "
                        "http(s) URL must exactly equal a cited current-Goal "
                        "web_extracted_content receipt origin_locator; links merely mentioned "
                        "inside page content do not qualify."
                    ),
                },
                "goal_id": {"type": "string"},
                "goal_revision": {"type": "integer"},
                "citations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "marker": {
                                "type": "string",
                                "description": (
                                    "Exact bracketed marker present in artifact_content, "
                                    "including square brackets, for example [H1]."
                                ),
                            },
                            "source_ref": {
                                "type": "string",
                                "description": (
                                    "Opaque source_ref from "
                                    "FIRST_AGENT_RUNTIME_SOURCE_REFS; copy unchanged."
                                ),
                            },
                            "source_id": {
                                "type": "string",
                                "description": (
                                    "Opaque paired source_id from "
                                    "FIRST_AGENT_RUNTIME_SOURCE_REFS; copy unchanged."
                                ),
                            },
                        },
                        "required": ["marker", "source_ref", "source_id"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": [
                "artifact_path",
                "artifact_content",
                "goal_id",
                "goal_revision",
                "citations",
            ],
            "additionalProperties": False,
        },
        risk=ToolRisk.LOW,
        side_effect=SideEffectClass.READ_ONLY,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.NEVER,
        safety_policy={"enabled": True, "kind": "citation_manifest_builder"},
        output_limit_chars=20_000,
    )


__all__ = ["build_research_tool_registrations"]
