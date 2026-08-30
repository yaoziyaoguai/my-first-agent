# 022 Workspace Artifact Skills Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变 Kernel owner 的前提下，把 workspace 中的 PDF、DOCX、XLSX、PPTX、PNG、JPEG、WebP 变成可受治理地 inspect、extract、create、edit/transform 的 first-party executable Skills，并以 host binary read-back、closed receipt 与独立 E3 reader 证明实际 bytes。

**Architecture:** 022 只增加 Artifact semantic seam、first-party package 与 evidence oracle。所有模型/工具推进仍走 `AgentRuntime.run_turn`，所有 callable 仍由 `ToolRuntime` 调用，所有进程与 OS confinement 仍由 `NativeSandboxExecutor` 执行。020b 唯一 `PackagedSkillExecutionAdapter` 在原 owner 文件内消费 022 的 closed Artifact codec、binary snapshot/commit helper；不得新增 adapter、executor、registration registry 或 outer structured-result decoder。021 的 active package、storage、qualification identity 只读消费，不在 022 重建。

**Tech Stack:** Python 3.11、现有 Kernel Runtime/WorkspaceBoundary/native Seatbelt structured sandbox、`pypdf==6.16.2`、`reportlab==5.0.1`、`python-docx==1.2.0`、`openpyxl==3.1.5`、`python-pptx==1.0.2`、`Pillow==12.3.0`、E3-only `pdfminer.six==20260107`、stdlib `zipfile/xml.etree.ElementTree/zlib`、macOS `/usr/bin/sips`、pytest、Ruff。

**Spec:** `docs/superpowers/specs/2026-08-30-governed-executable-skills-and-artifacts-design.md`

## Global Constraints

- Frozen dependency plans are `docs/superpowers/plans/2026-08-30-020a-operator-runtime-structured-sandbox.md`, `docs/superpowers/plans/2026-08-30-020b-packaged-executable-skills.md`, and `docs/superpowers/plans/2026-08-30-021-skill-package-lifecycle.md`. Implement 022 only after all three plans pass their complete source and materialized gates.
- 020a owns the structured sandbox draft/receipt and the optional `StructuredSandboxIoPlanV1` path on the one `NativeSandboxExecutor.execute` method. 022 may construct an I/O plan and decode its bounded payload; it must not spawn, wrap Seatbelt, read session paths, or mint a second sandbox receipt.
- 020b owns `PackagedSkillExecutionAdapter` and `build_packaged_skill_registrations`. 022 modifies only the existing tracked implementation of that adapter to call the Artifact seam. It must not define another execution adapter, registration builder, outer envelope, or result transport decoder.
- 021 exclusively owns `StoredPackageV1`, `QualificationRecordV1`, `ActiveSkillSetV1`, the lifecycle gate/store/planner, storage identity, qualification identity, active snapshot identity, and execution/exclusive guards. 022 consumes those public values through `SkillActivationGate`; it never scans, installs, activates, revokes, or re-qualifies packages.
- 020b freezes the exact semantic owner paths: `agent/skill/execution.py` owns `PackagedSkillExecutionAdapter`, `_PackagedSkillCallable` and `StructuredSandboxToolDraftV1`; `agent/skill/executable_results.py` owns the only outer semantic result decoder; `agent/skill/tools.py` owns `build_packaged_skill_registrations`, generated ToolSpecs and their prepare-binding path. Task 3 edits all three owners in place and architecture tests require one definition of each owner. Only `_PackagedSkillCallable.__call__` releases the fresh 021 execution guard, exactly once in `finally`; adapter helpers never acquire or release it.
- `AgentRuntime.run_turn` remains the only production model/tool loop. `ContextManager` remains the only model-context selector. `ToolRuntime` remains the only tool-call owner. Provider, CLI and headless adapters remain thin and gain no Artifact parsing.
- `WorkspaceBoundary` remains the only workspace filesystem authority. Every input snapshot, target precondition and fresh read-back uses one no-follow opened regular-file descriptor with bounded I/O. Child code never receives a workspace path, absolute host path, package path, state path, session path, credential or private-root content.
- Write operations have exactly one target and one `atomic_replace` commit. Input/source bytes may be many, but v1 has no directory output, sidecar, multi-file transaction, scratch output, rename plan or compatibility fallback.
- `exit_code == 0`, stdout prose, free-form JSON, package self-report and model prose are never completion evidence. Only the closed structured draft plus host read-back can mint source/mutation receipts; only real E3 with an independent reader promotes semantic correctness.
- A write exception after commit and before result checkpoint remains unknown outcome and enters the existing `AWAITING_RECOVERY` flow. It is never flattened to failure, retried automatically, or classified by package output.
- Scope is exactly PDF, DOCX, XLSX, PPTX, PNG, JPEG and WebP. No OCR, visual model, semantic image understanding, face/object recognition, image generation model, PDF form/signature/encryption/attachment mutation, Office VBA/OLE/external-link mutation, theme/animation fidelity, formula creation/evaluation, charts, comments, embedded media, SVG, GIF, TIFF or multi-frame raster.
- Production packages use release-owned exact dependencies. Installer input cannot choose dependency name/version and cannot run package manager hooks. E3 independent readers are excluded from the hermetic production closure.
- The verifier, not 020a or product Runtime, owns `WheelhouseSealV1` and exact `--wheelhouse/--wheelhouse-seal/--skill-runtime-root` CLI admission. The verifier validates the sealed wheel inventory before an offline install; 020a then qualifies only the resulting installed `skill-runtime-v1` bytes and never parses a wheelhouse or seal.
- All request/result objects are strict, versioned, `additionalProperties=false` equivalents. Strings are NFC; object keys are sorted for digest; floats, NaN and Infinity are rejected; decimal values are canonical strings; optional means absent-or-value and never implicit null; only explicit `| null` accepts null.
- Frozen caps: request 64 KiB, projection 64,000 chars, one input 32 MiB, all inputs 64 MiB, output 64 MiB, at most 16 inputs and 1,000 operations, PDF 500 pages, Office 10,000 ZIP parts/256 MiB expanded, DOCX 10,000 blocks, XLSX 100,000 selected/written cells, PPTX 500 slides/10,000 shapes, raster side 20,000/pixels 50,000,000.
- `SkillFormatV1.RASTER = "raster"` is a portable manifest-only family added in Task 3 at 020b's existing enum owner. `ArtifactFormatV1` remains exactly PDF/DOCX/XLSX/PPTX/PNG/JPEG/WEBP; raster canvas/transcode requests and input magic determine PNG/JPEG/WebP output. No `ArtifactFormatV1.RASTER` or open string fallback exists.
- `agent/skill/__init__.py` is not modified. All new Skill imports use the existing exact leaf modules; no root re-export or eager composition import is added.
- Do not read `.env`, credentials, private runtime data or untracked `tui/`. Fixtures are synthetic and non-sensitive. Do not commit, push, tag or alter remotes while executing this plan; the `git commit` lines below are worker checkpoints to use only when the operator explicitly authorizes commits. Without authorization, record the proposed commit message and continue.
- Every task follows Red → observed failure → minimum Green → observed pass. A timeout, truncation, skip of a required real gate, or missing exit code is not a pass. Focused tests and Ruff run per task; Task 11 runs the complete source/materialized/E3 gates exactly once per frozen candidate.

## File Structure and Responsibilities

### New host-side Artifact seam

- `agent/artifacts/__init__.py`: exports only frozen Artifact enums/contracts; registration and workspace helpers remain leaf imports, and no parser/runtime dependency is imported eagerly.
- `agent/artifacts/contracts.py`: closed enums, all request/structure dataclasses/unions, `ArtifactExpectationV1`, `ArtifactObservationV1`, `ArtifactCommitFactsV1`, `ArtifactMutationDraftV1`, `ArtifactMutationReceiptV1`, `ArtifactStatV1`, caps and canonical identity methods.
- `agent/artifacts/codec.py`: the only Artifact semantic JSON decoder/encoder; exact keys, NFC, bounds, selectors, addresses, conflicts, flags, magic and canonical digests. It decodes only the payload already extracted by 020b's one outer structured-result decoder.
- `agent/artifacts/workspace.py`: `WorkspaceArtifactIo` that delegates descriptor traversal to `WorkspaceBoundary`, creates immutable binary snapshots, validates staged bytes, revalidates target preconditions and performs one exact atomic replace. It does not execute code or decode the outer sandbox envelope.
- `agent/artifacts/tools.py`: `artifact_stat` ToolSpec/callable and host magic sniffing; one ordinary `RegisteredTool`, composed into the existing static tuple.
- `agent/artifacts/evidence.py`: pure exact-join validator used by `ClosedEvidenceRegistry`; no registry and no checkpoint access.

### New release-owned parser runtime

- `agent/artifact_runtime/__init__.py`: child-runtime public dispatcher only.
- `agent/artifact_runtime/common.py`: fixed caps, bounded stream/hash, deterministic JSON, digest helpers, projection truncation and terminal refusal types.
- `agent/artifact_runtime/preflight.py`: PDF header, Office ZIP inventory/expanded-size/active-content scan and raster dimension/frame/metadata header scan before full parser decode.
- `agent/artifact_runtime/pdf.py`: PDF inspect/extract/create/pages-patch implementation.
- `agent/artifact_runtime/docx.py`: DOCX inspect/extract/blocks-create/blocks-patch implementation.
- `agent/artifact_runtime/xlsx.py`: XLSX inspect/extract/cells-create/cells-patch implementation.
- `agent/artifact_runtime/pptx.py`: PPTX inspect/extract/slides-create/slides-patch implementation.
- `agent/artifact_runtime/raster.py`: raster inspect/canvas-create/transform implementation; never OCR or semantic analysis.
- `agent/artifact_runtime/dispatch.py`: maps the closed `(format, request.kind)` pair to exactly one parser function; package/entrypoint identity remains enforced by 020b before this call.

### Bundled first-party packages

- `agent/bundled_skills/pdf-workspace/`, `docx-workspace/`, `xlsx-workspace/`, `pptx-workspace/`, `raster-image-workspace/`: each contains `SKILL.md`, `first-agent.json`, `skill.requirements.json`, declared `scripts/*.py`, bounded references and no mutable runtime dependency.
- `agent/bundled_skills/*/scripts/*.py`: thin declared entrypoints calling `agent.artifact_runtime.dispatch.run_declared_entrypoint`; no filesystem path access, subprocess, network, alternate JSON codec or receipt construction.
- `pyproject.toml`: exact `artifact-runtime` extra, E3-independent-reader dev extra and explicit package-data inclusion for bundled Skills.

### Existing owner files modified in place

- `agent/tools/path_safety.py`: owns the one `BinarySnapshotV1` and adds descriptor-based bounded binary snapshot plus expected-precondition atomic replace primitives used only through `WorkspaceBoundary`.
- `agent/tools/file_ops.py`: appends the one `artifact_stat` registration to the existing file registration tuple.
- `agent/runtime/contracts.py`: adds only `EvidenceOracleKind.ARTIFACT_READBACK`; it reuses the existing `SourceReceiptDraft`, `SourceReceiptV1` and `ToolExecutionOutput` owners unchanged.
- `agent/runtime/evidence.py`: routes `ARTIFACT_READBACK` to the pure 022 join validator inside the existing `ClosedEvidenceRegistry`.
- `agent/composition.py`: remains owned and modified by 021; 022 only adds an architecture assertion that its one `build_packaged_skill_registrations` call consumes the activated first-party packages.
- `agent/skill/execution.py`: adds Artifact semantic handling and optional typed Artifact observation/mutation fields inside the existing `PackagedSkillExecutionAdapter`/`StructuredSandboxToolDraftV1` owners only.
- `agent/skill/executable_results.py`: adds explicit closed Artifact result branches to the existing decoder; no runtime registry or second outer envelope.
- `agent/skill/executable_contracts.py`: adds only the portable manifest-family enum member `SkillFormatV1.RASTER`; it does not add an Artifact byte format.
- `agent/skill/tools.py`: extends the existing per-entrypoint schema/binding owner with the exact 19-kind Artifact argument envelope, source/target preapproval identities and sanitized child arguments; it does not add a registration builder.

### Tests, fixtures and acceptance

- `tests/artifacts/test_contracts.py`, `test_codec.py`, `test_workspace.py`, `test_tools.py`, `test_evidence.py`, `test_adapter_integration.py`: host seam and owner-boundary tests.
- `tests/artifacts/test_pdf.py`, `test_docx.py`, `test_xlsx.py`, `test_pptx.py`, `test_raster.py`: full positive schema/format matrices.
- `tests/artifacts/hostile_fixtures.py`: deterministic byte constructors for corrupt headers, active content, ZIP bombs/collisions, decompression bombs, metadata and multi-frame images.
- `tests/artifacts/test_hostile_inputs.py`: preflight/resource/active-content refusal and non-vacuous controls.
- `tests/artifacts/test_bundled_packages.py`: exact manifests, declared scripts, requirements and package-data materialization.
- `tests/reference/test_022_workspace_artifacts.py`: real Runtime E2 journeys and three-attempt E3 journey reducer.
- `tests/reference/test_022_e3_harness.py`: claim-to-journey closure, receipt mutation and false-control tests.
- `tests/reference/test_022_independent_readers.py`: pdfminer, stdlib ZIP/XML and `sips` independent semantic readers.
- `scripts/run_022_e3.py`: detached real Seatbelt three-attempt runner and closed receipt reducer.
- `scripts/verify_022_materialized_tree.py`: clean offline wheel/install, governed 021 import/stage/activate/restart, real E2M and detached E3 orchestration.
- `docs/acceptance/022_WORKSPACE_ARTIFACT_SKILLS_E3.md`: frozen journey/identity/blocked criteria; generated receipt remains detached mutable evidence.
- `docs/acceptance/022_WORKSPACE_ARTIFACT_SKILLS_RECEIPT.json`: generated only by the final runner, never hand-authored as proof.

### Frozen outcome classification

| Boundary | Result | Commit/evidence |
| --- | --- | --- |
| activation/revocation/identity/input/target precondition fails before spawn | `KnownNotExecuted` | zero spawn, zero commit, no sandbox/artifact receipt |
| structured spawn fails and owner proves no child started | `KnownNotExecuted` | zero commit, no receipt |
| child started then result inode is missing/replaced/symlinked/malformed/truncated/extra | known-executed error | zero commit; sandbox execution facts may be recorded, no mutation receipt |
| child started then parser refuses encrypted/active/unsupported/resource input | known-executed terminal refusal | zero commit, no completion evidence |
| staged artifact size/digest/magic or typed observation mismatches | known-executed error | zero commit, no mutation receipt |
| target/parent precondition drifts before atomic replace | known-executed error | zero commit, no mutation receipt |
| atomic replace succeeds and full structured result checkpoints | executed success | sandbox receipt + mutation receipt + later fresh `artifact_stat` may satisfy `ARTIFACT_READBACK` |
| atomic replace succeeds, then adapter/Runtime crashes before result checkpoint | existing WRITE unknown outcome | no replay; enter `AWAITING_RECOVERY`, inspect fresh target bytes before operator recovery |
| spawn/cleanup outcome cannot be classified by the executor | existing unknown-outcome recovery | no replay and no package/model classification |
| bounded read/extract observation is truncated | executed bounded observation | may inform context but cannot satisfy completion evidence |

---

### Task 1: Freeze every Artifact field and the one semantic codec

**Files:**
- Create: `agent/artifacts/__init__.py`
- Create: `agent/artifacts/contracts.py`
- Create: `agent/artifacts/codec.py`
- Create: `tests/artifacts/test_contracts.py`
- Create: `tests/artifacts/test_codec.py`

**Interfaces:**

```python
ArtifactRequestV1: TypeAlias = (
    PdfInspectRequestV1 | PdfExtractRequestV1 | PdfCreateRequestV1
    | PdfPagesPatchRequestV1 | DocxInspectRequestV1 | DocxExtractRequestV1
    | DocxBlocksRequestV1 | DocxBlocksPatchRequestV1
    | XlsxInspectRequestV1 | XlsxExtractRequestV1 | XlsxCellsRequestV1
    | XlsxCellsPatchRequestV1 | PptxInspectRequestV1 | PptxExtractRequestV1
    | PptxSlidesRequestV1 | PptxSlidesPatchRequestV1
    | RasterInspectRequestV1 | RasterCanvasRequestV1 | RasterTransformRequestV1
)
ArtifactStructureV1: TypeAlias = (
    PdfStructureV1 | DocxStructureV1 | XlsxStructureV1
    | PptxStructureV1 | RasterStructureV1
)

DecodeArtifactRequest: TypeAlias = Callable[[bytes], ArtifactRequestV1]
DecodeArtifactObservation: TypeAlias = Callable[
    [Mapping[str, JSONValue]], ArtifactObservationV1
]
CanonicalArtifactJson: TypeAlias = Callable[[object], bytes]
ArtifactRequestDigest: TypeAlias = Callable[[ArtifactRequestV1], str]
```

- [ ] **Step 1: Write the Red schema matrix**

Write parameterized tests with one valid specimen for every one of the 19 request kinds and five structure kinds. The exact valid matrix is:

```python
VALID_REQUESTS = (
    {"kind": "pdf_inspect_v1", "input_slot": 0, "pages": None},
    {"kind": "pdf_extract_v1", "input_slot": 0,
     "pages": {"kind": "pages_v1", "ranges": [{"first": 1, "last": 2}]}},
    {"kind": "pdf_create_v1", "source_slot": 0, "source_kind": "markdown",
     "page_size": "a4", "metadata": {"title": "T", "author": "A"}},
    {"kind": "pdf_pages_patch_v1", "input_slots": [0],
     "page_order": [{"slot": 0, "page": 1}],
     "rotations": [{"output_page": 1, "degrees": 90}], "metadata": {}},
    {"kind": "docx_inspect_v1", "input_slot": 0, "addresses": None},
    {"kind": "docx_extract_v1", "input_slot": 0,
     "addresses": ["paragraph:0", "table:0/cell:0,0"]},
    {"kind": "docx_blocks_v1", "blocks": [
        {"kind": "paragraph", "style": "heading1", "text": "Title"},
        {"kind": "table", "rows": [["A", "B"], ["1", "2"]]},
    ]},
    {"kind": "docx_blocks_patch_v1", "input_slot": 0,
     "source_structure_digest": "a" * 64,
     "operations": [{"kind": "replace_text", "address": "paragraph:0",
                     "expected": "old", "replacement": "new"}]},
    {"kind": "xlsx_inspect_v1", "input_slot": 0, "selections": None},
    {"kind": "xlsx_extract_v1", "input_slot": 0,
     "selections": [{"sheet": "Data", "range": "A1:B2"}]},
    {"kind": "xlsx_cells_v1", "sheets": [{"name": "Data", "cells": [
        {"address": "A1", "value": {"kind": "string", "value": "marker"}},
        {"address": "B1", "value": {"kind": "number", "value": "12.50"},
         "number_format": "decimal_2"},
    ]}]},
    {"kind": "xlsx_cells_patch_v1", "input_slot": 0,
     "source_structure_digest": "b" * 64,
     "operations": [{"kind": "set_cell", "sheet": "Data", "address": "A2",
                     "value": {"kind": "boolean", "value": True}}]},
    {"kind": "pptx_inspect_v1", "input_slot": 0, "slides": None},
    {"kind": "pptx_extract_v1", "input_slot": 0, "slides": [2, 1]},
    {"kind": "pptx_slides_v1", "slides": [
        {"layout": "title_body", "title": "Release", "body": ["Ready"],
         "images": [{"input_slot": 0, "x_pt": 10, "y_pt": 20,
                     "width_pt": 100, "height_pt": 80}]},
    ]},
    {"kind": "pptx_slides_patch_v1", "input_slot": 0,
     "source_structure_digest": "c" * 64,
     "operations": [{"kind": "replace_text", "address": "slide:1/shape:0",
                     "expected": "Release", "replacement": "Shipped"}]},
    {"kind": "raster_inspect_v1", "input_slot": 0},
    {"kind": "raster_canvas_v1", "format": "png", "width": 320, "height": 200,
     "mode": "rgba", "background": [255, 255, 255, 255],
     "operations": [{"kind": "rectangle", "x": 10, "y": 10,
                     "width": 40, "height": 20, "fill": [0, 0, 0, 255]}]},
    {"kind": "raster_transform_v1", "input_slot": 0,
     "operations": [{"kind": "resize", "width": 160, "height": 100,
                     "filter": "lanczos"}, {"kind": "metadata", "mode": "strip"}]},
)
```

Use this complete field inventory as the mutation-test source; each value is `(required_keys, optional_keys)` and every unlisted key is rejected:

```python
EXACT_KEYS = {
    "pages_v1": (("kind", "ranges"), ()),
    "pdf_page_range": (("first", "last"), ()),
    "pdf_inspect_v1": (("kind", "input_slot", "pages"), ()),
    "pdf_extract_v1": (("kind", "input_slot", "pages"), ()),
    "pdf_create_v1": (("kind", "source_slot", "source_kind", "page_size", "metadata"), ()),
    "pdf_pages_patch_v1": (("kind", "input_slots", "page_order", "rotations", "metadata"), ()),
    "pdf_metadata": ((), ("title", "author")),
    "pdf_page_order": (("slot", "page"), ()),
    "pdf_rotation": (("output_page", "degrees"), ()),
    "pdf_structure_v1": (("kind", "page_count", "pages", "metadata_flags", "active_content_flags"), ()),
    "pdf_page_observation": (("page", "width_pt", "height_pt", "text_digest"), ()),
    "docx_inspect_v1": (("kind", "input_slot", "addresses"), ()),
    "docx_extract_v1": (("kind", "input_slot", "addresses"), ()),
    "docx_blocks_v1": (("kind", "blocks"), ()),
    "docx_blocks_patch_v1": (("kind", "input_slot", "source_structure_digest", "operations"), ()),
    "docx_paragraph": (("kind", "style", "text"), ()),
    "docx_table": (("kind", "rows"), ()),
    "docx_replace_text": (("kind", "address", "expected", "replacement"), ()),
    "docx_delete_block": (("kind", "address"), ()),
    "docx_append_blocks": (("kind", "blocks"), ()),
    "docx_set_cell": (("kind", "address", "expected", "replacement"), ()),
    "docx_structure_v1": (("kind", "blocks", "active_content_flags"), ()),
    "docx_paragraph_observation": (("address", "kind", "text_digest"), ()),
    "docx_table_observation": (("address", "kind", "text_digest", "rows", "columns"), ()),
    "xlsx_selection": (("sheet", "range"), ()),
    "xlsx_inspect_v1": (("kind", "input_slot", "selections"), ()),
    "xlsx_extract_v1": (("kind", "input_slot", "selections"), ()),
    "xlsx_cells_v1": (("kind", "sheets"), ()),
    "xlsx_cells_patch_v1": (("kind", "input_slot", "source_structure_digest", "operations"), ()),
    "xlsx_sheet_write": (("name", "cells"), ()),
    "xlsx_cell_write": (("address", "value"), ("number_format",)),
    "xlsx_scalar_blank": (("kind",), ()),
    "xlsx_scalar_string": (("kind", "value"), ()),
    "xlsx_scalar_number": (("kind", "value"), ()),
    "xlsx_scalar_boolean": (("kind", "value"), ()),
    "xlsx_set_cell": (("kind", "sheet", "address", "value"), ("number_format",)),
    "xlsx_clear_range": (("kind", "sheet", "range"), ()),
    "xlsx_add_sheet": (("kind", "name"), ()),
    "xlsx_remove_sheet": (("kind", "name"), ()),
    "xlsx_rename_sheet": (("kind", "old_name", "new_name"), ()),
    "xlsx_structure_v1": (("kind", "sheets", "active_content_flags"), ()),
    "xlsx_sheet_observation": (("name", "used_range", "selected_cells"), ()),
    "xlsx_cell_observation": (("address", "value_digest", "number_format"), ("formula_digest",)),
    "pptx_inspect_v1": (("kind", "input_slot", "slides"), ()),
    "pptx_extract_v1": (("kind", "input_slot", "slides"), ()),
    "pptx_slides_v1": (("kind", "slides"), ()),
    "pptx_slides_patch_v1": (("kind", "input_slot", "source_structure_digest", "operations"), ()),
    "pptx_image_placement": (("input_slot", "x_pt", "y_pt", "width_pt", "height_pt"), ()),
    "pptx_slide": (("layout",), ("title", "body", "images")),
    "pptx_replace_text": (("kind", "address", "expected", "replacement"), ()),
    "pptx_delete_slide": (("kind", "slide"), ()),
    "pptx_reorder_slides": (("kind", "order"), ()),
    "pptx_replace_image": (("kind", "address", "input_slot"), ()),
    "pptx_structure_v1": (("kind", "slides", "active_content_flags"), ()),
    "pptx_slide_observation": (("slide", "title_digest", "body_digest", "shape_count"), ()),
    "raster_inspect_v1": (("kind", "input_slot"), ()),
    "raster_canvas_v1": (("kind", "format", "width", "height", "mode", "background", "operations"), ()),
    "raster_transform_v1": (("kind", "input_slot", "operations"), ()),
    "raster_rectangle": (("kind", "x", "y", "width", "height", "fill"), ()),
    "raster_ellipse": (("kind", "x", "y", "width", "height", "fill"), ()),
    "raster_line": (("kind", "x1", "y1", "x2", "y2", "width", "color"), ()),
    "raster_text": (("kind", "x", "y", "text", "font", "size", "color"), ()),
    "raster_composite": (("kind", "input_slot", "x", "y", "width", "height"), ()),
    "raster_crop": (("kind", "x", "y", "width", "height"), ()),
    "raster_resize": (("kind", "width", "height", "filter"), ()),
    "raster_rotate": (("kind", "degrees"), ()),
    "raster_transcode": (("kind", "format", "quality"), ()),
    "raster_metadata": (("kind", "mode"), ()),
    "raster_structure_v1": (("kind", "format", "width", "height", "mode", "pixel_digest", "metadata_flags", "frame_count"), ()),
    "artifact_observation_v1": (("format", "raw_sha256", "byte_count", "structure", "structure_digest", "projection", "projection_digest", "active_content_flags", "truncated", "truncation_reason"), ()),
    "artifact_commit_facts_v1": (("target_path", "target_precondition_digest", "committed_device", "committed_inode", "committed_mtime_ns", "committed_snapshot_digest", "output_raw_sha256", "output_byte_count", "detected_format", "commit_outcome"), ()),
    "artifact_mutation_receipt_v1": (("schema", "conversation_id", "run_id", "goal_id", "goal_revision", "tool_call_id", "intent_digest", "tool_identity", "package_digest", "qualification_digest", "entrypoint_digest", "request_digest", "sandbox_receipt_digest", "target_path", "target_precondition_digest", "committed_snapshot_digest", "output_raw_sha256", "output_byte_count", "detected_format", "observation_raw_sha256", "structure_digest", "commit_outcome", "receipt_digest"), ()),
}
```

The tests additionally bind discriminator values to the matching entry: `blank` is the only scalar without `value`; `title` requires title and forbids body, `title_body` requires both, `blank` forbids both; `images`/`body` when present are non-empty; explicit nullable fields are only PDF `pages`, DOCX `addresses`, XLSX `selections`/`used_range`, PPTX `slides`, outer `truncation_reason`, and `target_precondition_digest` in commit facts/mutation receipts (null means the approved target was absent).

For every specimen, mutate each key to absent, extra, wrong type, explicit null, non-NFC text, bool-as-int, and an unknown enum. Add closed tests for all operation variants: four DOCX patch ops, five XLSX patch ops, four PPTX patch ops, five raster draw ops and five raster transform ops. Add selector/address conflict tests, all frozen caps, flag ordering/dedup/format allowlists and all eight `NumberFormatV1` values.

- [ ] **Step 2: Run the Red tests and preserve the failure**

Run: `.venv/bin/python -m pytest -q tests/artifacts/test_contracts.py tests/artifacts/test_codec.py -rx`

Expected: FAIL during collection with `ModuleNotFoundError: No module named 'agent.artifacts'`. Save that exact failure in the implementation log; do not weaken a mutation to make collection pass.

- [ ] **Step 3: Implement the minimum closed contracts**

Define the frozen enums exactly as spec, plus:

```python
MAX_REQUEST_BYTES = 65_536
MAX_PROJECTION_CHARS = 64_000
MAX_INPUT_BYTES = 32 * 1024 * 1024
MAX_ALL_INPUT_BYTES = 64 * 1024 * 1024
MAX_OUTPUT_BYTES = 64 * 1024 * 1024
MAX_INPUTS = 16
MAX_OPERATIONS = 1_000
MAX_PDF_PAGES = 500
MAX_OFFICE_PARTS = 10_000
MAX_OFFICE_EXPANDED_BYTES = 256 * 1024 * 1024
MAX_DOCX_BLOCKS = 10_000
MAX_XLSX_CELLS = 100_000
MAX_PPTX_SLIDES = 500
MAX_PPTX_SHAPES = 10_000
MAX_RASTER_SIDE = 20_000
MAX_RASTER_PIXELS = 50_000_000
TEXT_LIMIT = 32_000
METADATA_TEXT_LIMIT = 512
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
DECIMAL_RE = re.compile(r"-?(0|[1-9][0-9]*)(\.[0-9]{1,12})?\Z")

class NumberFormatV1(StrEnum):
    GENERAL = "general"
    INTEGER = "integer"
    DECIMAL_2 = "decimal_2"
    PERCENT = "percent"
    DATE_ISO = "date_iso"
    DATETIME_ISO = "datetime_iso"
    CURRENCY_USD = "currency_usd"
    CURRENCY_CNY = "currency_cny"
```

Use frozen dataclasses for every object named in spec. Each `__post_init__` calls shared exact validators; no dataclass accepts a raw dict after construction. `ArtifactObservationV1.__post_init__` recomputes `structure_digest` and `projection_digest`, requires `raw_sha256`, validates `truncation_reason is None` iff `truncated is False`, and enforces flag sort/dedup/format membership. `ArtifactMutationReceiptV1.create` computes `receipt_digest` from every preceding field; direct construction with a mismatched digest raises `ValueError`.

Freeze `ArtifactCommitFactsV1` rather than leaving a forward reference: exact fields are `target_path`, `target_precondition_digest`, `committed_device`, `committed_inode`, `committed_mtime_ns`, `committed_snapshot_digest`, `output_raw_sha256`, `output_byte_count`, `detected_format` and `commit_outcome`; the identity fields let Runtime recompute the `BinarySnapshotV1` digest but never enter the durable mutation receipt, and the object contains no bytes or absolute path. Freeze `ArtifactMutationReceiptV1` with exact fields `schema`, `conversation_id`, `run_id`, `goal_id`, `goal_revision`, `tool_call_id`, `intent_digest`, `tool_identity`, `package_digest`, `qualification_digest`, `entrypoint_digest`, `request_digest`, `sandbox_receipt_digest`, `target_path`, `target_precondition_digest`, `committed_snapshot_digest`, `output_raw_sha256`, `output_byte_count`, `detected_format`, `observation_raw_sha256`, `structure_digest`, `commit_outcome`, and `receipt_digest`. `tool_identity` is always the authenticated `ToolSpec.identity_digest`; no `tool_spec_identity` alias is decoded.

- [ ] **Step 4: Implement the one semantic codec**

The decoder starts with bounded UTF-8 JSON, rejects duplicate keys before type dispatch, and never calls `json.loads` in a second module:

```python
def _pairs_no_duplicates(pairs: list[tuple[str, JSONValue]]) -> dict[str, JSONValue]:
    result: dict[str, JSONValue] = {}
    for key, value in pairs:
        normalized = unicodedata.normalize("NFC", key)
        if key != normalized or normalized in result:
            raise ArtifactDecodeError("duplicate or non-NFC object key")
        result[normalized] = value
    return result

def decode_artifact_request(raw: bytes) -> ArtifactRequestV1:
    if len(raw) > MAX_REQUEST_BYTES:
        raise ArtifactDecodeError("request exceeds artifact-standard-v1")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs_no_duplicates,
                           parse_float=_reject_float, parse_constant=_reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise ArtifactDecodeError("request is not closed canonical JSON") from error
    if not isinstance(value, dict):
        raise ArtifactDecodeError("request must be an object")
    kind = value.get("kind")
    if not isinstance(kind, str) or kind != unicodedata.normalize("NFC", kind):
        raise ArtifactDecodeError("request kind must be an NFC string")
    decoder = REQUEST_DECODERS.get(kind)
    if decoder is None:
        raise ArtifactDecodeError("unknown Artifact request kind")
    request = decoder(value)
    if canonical_artifact_json(request) != raw:
        raise ArtifactDecodeError("request bytes are not canonical")
    return request
```

`REQUEST_DECODERS` contains all 19 kinds from `VALID_REQUESTS`. It is an immutable module constant, not a runtime capability registry. Canonical JSON serializes dataclasses/enums, NFC strings, booleans, integers, decimal strings and `None` with `ensure_ascii=False`, `sort_keys=True`, `separators=(",", ":")`; it rejects Python float and unordered set/frozenset.

- [ ] **Step 5: Run the Green tests**

Run: `.venv/bin/python -m pytest -q tests/artifacts/test_contracts.py tests/artifacts/test_codec.py -rx`

Run: `.venv/bin/ruff check agent/artifacts tests/artifacts/test_contracts.py tests/artifacts/test_codec.py`

Expected: both commands exit 0; the mutation loop proves every field and variant fails closed.

- [ ] **Step 6: Commit the checkpoint if authorized**

```bash
git add agent/artifacts/__init__.py agent/artifacts/contracts.py agent/artifacts/codec.py tests/artifacts/test_contracts.py tests/artifacts/test_codec.py
git commit -m "feat(artifacts): freeze closed artifact contracts"
```

---

### Task 2: Add no-follow binary snapshot, exact commit and `artifact_stat`

**Files:**
- Modify: `agent/tools/path_safety.py`
- Modify: `agent/tools/file_ops.py`
- Create: `agent/artifacts/workspace.py`
- Create: `agent/artifacts/tools.py`
- Create: `tests/artifacts/test_workspace.py`
- Create: `tests/artifacts/test_tools.py`
- Modify: `tests/tools/test_path_safety.py`
- Modify: `tests/tools/test_file_tools.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class BinarySnapshotV1:
    normalized_path: str
    device: int
    inode: int
    mtime_ns: int
    raw_sha256: str
    byte_count: int
    snapshot_digest: str
    data: bytes = field(repr=False, compare=False)

SnapshotInputs: TypeAlias = Callable[[Sequence[str]], Sequence[BinarySnapshotV1]]
CommitOne: TypeAlias = Callable[
    [str, str | None, bytes, ArtifactFormatV1, str], ArtifactCommitFactsV1
]

ArtifactStatBindingPreparer: TypeAlias = Callable[
    [Mapping[str, object]], BindingPreparation
]
```

The production registration signature is exactly `build_artifact_stat_registration(boundary: WorkspaceBoundary, *, policy: ToolPolicy, prepare_binding: ArtifactStatBindingPreparer) -> RegisteredTool`; it has no optional policy, default boundary or registry parameter.

- [ ] **Step 1: Write descriptor and drift Reds**

Add tests that create regular binary files containing invalid UTF-8 and NUL bytes, then assert `snapshot_binary` returns exact bytes/digest without replacement decoding. Add parameterized denials for absolute/parent/backslash/private/protected paths, symlink leaf, symlink intermediate directory, FIFO, socket, directory, hardlink (`st_nlink != 1`), input growth beyond 32 MiB and aggregate growth beyond 64 MiB.

Write two race tests with an injected hook immediately after open: replacing the directory entry must not change bytes hashed from the opened fd, but revalidation must reject the changed device/inode/size/mtime/digest before invoke. Write target races for parent replacement, existing-target replacement, absent-target creation, target hardlinking and precondition mismatch; every case asserts zero `os.replace` calls.

```python
def test_commit_one_rejects_target_drift_before_replace(tmp_path, monkeypatch):
    boundary, artifact_io, target = artifact_io_fixture(tmp_path)
    prepared = boundary.inspect_mutation("out.pdf", max_bytes=64 * 1024 * 1024)[0]
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(os, "replace", lambda source, destination: calls.append((source, destination)))
    target.write_bytes(b"drift")
    with pytest.raises(WorkspaceArtifactError, match="target precondition changed"):
        artifact_io.commit_one(
            target="out.pdf",
            expected_precondition_digest=prepared.precondition_digest,
            data=b"%PDF-1.7\nfixture",
            expected_format=ArtifactFormatV1.PDF,
            expected_sha256=hashlib.sha256(b"%PDF-1.7\nfixture").hexdigest(),
        )
    assert calls == []
```

Add `artifact_stat` ToolSpec tests for exact schema `{path}`, `IN_PROCESS`, `READ_ONLY`, `NEVER`, `EgressClass.NONE`, bounded-text output and no source kind. Invoke it on every supported magic and assert result contains only `path`, `byte_count`, `raw_sha256`, `snapshot_digest`, `detected_magic`, `observed_at`; raw bytes and decoded replacement characters never appear.

- [ ] **Step 2: Run the Reds**

Run: `.venv/bin/python -m pytest -q tests/artifacts/test_workspace.py tests/artifacts/test_tools.py tests/tools/test_path_safety.py tests/tools/test_file_tools.py -rx`

Expected: FAIL because `snapshot_binary`, expected-precondition commit and `artifact_stat` are absent.

- [ ] **Step 3: Add the bounded binary primitives to `WorkspaceBoundary`**

Use existing `_open_regular` and descriptor traversal. The read loop hashes and accumulates from the same fd, checks size after EOF and rejects drift:

```python
def snapshot_binary(self, path: str, *, max_bytes: int) -> BinarySnapshotV1:
    parts = self.validate_relative(path)
    normalized = "/".join(parts)
    with self._open_parent(parts) as (parent_fd, name):
        fd = self._open_regular(parent_fd, name)
        try:
            before = os.fstat(fd)
            chunks: list[bytes] = []
            digest = hashlib.sha256()
            total = 0
            while True:
                chunk = os.read(fd, min(65_536, max_bytes + 1 - total))
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise FilePolicyError("workspace binary exceeds the size limit")
                digest.update(chunk)
                chunks.append(chunk)
            after = os.fstat(fd)
            if _stat_identity(before) != _stat_identity(after) or total != after.st_size:
                raise FilePolicyError("workspace binary changed during snapshot")
            raw_sha256 = digest.hexdigest()
            values = {
                "normalized_path": normalized,
                "device": before.st_dev,
                "inode": before.st_ino,
                "mtime_ns": before.st_mtime_ns,
                "raw_sha256": raw_sha256,
                "byte_count": total,
            }
            return BinarySnapshotV1(
                **values,
                snapshot_digest=_digest_values(values),
                data=b"".join(chunks),
            )
        finally:
            os.close(fd)
```

Define `BinarySnapshotV1` once in `agent/tools/path_safety.py`; `agent/artifacts/workspace.py`, `artifact_stat`, adapter bindings and tests import that exact type. There is no `BinaryFileSnapshot`, duplicate host snapshot dataclass or dict-only snapshot identity.

Add `atomic_replace_if_unchanged(path, data, *, expected_precondition_digest, max_bytes)` beside existing `atomic_replace`. It opens/revalidates the target and parent through current no-follow helpers, compares the recomputed binding digest, creates a random regular temp in the exact opened parent with `O_CREAT|O_EXCL|O_NOFOLLOW`, writes/fsyncs with a cap, rechecks target and parent a second time, uses descriptor-relative `os.replace(src, dst, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)`, fsyncs parent and verifies the committed bytes by a fresh opened fd. It unlinks only its exact temp name on pre-commit failure. It never resolves paths with `Path.resolve()`.

- [ ] **Step 4: Implement Artifact host I/O and magic detection**

`WorkspaceArtifactIo.snapshot_inputs` rejects more than 16 paths and aggregate bytes over 64 MiB. `commit_one` verifies digest, byte cap and exact magic before calling `atomic_replace_if_unchanged`. Use this closed magic function:

```python
def detect_artifact_magic(data: bytes) -> ArtifactFormatV1:
    if data.startswith(b"%PDF-"):
        return ArtifactFormatV1.PDF
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ArtifactFormatV1.PNG
    if data.startswith(b"\xff\xd8\xff"):
        return ArtifactFormatV1.JPEG
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ArtifactFormatV1.WEBP
    if data.startswith(b"PK\x03\x04"):
        return office_format_from_closed_content_types(data)
    raise WorkspaceArtifactError("unsupported or mismatched Artifact magic")
```

`office_format_from_closed_content_types` uses bounded ZIP central-directory inspection, requires exactly one `[Content_Types].xml`, parses no external entity and returns DOCX/XLSX/PPTX only for the frozen main-part content type. A generic ZIP is rejected.

- [ ] **Step 5: Register the normal file tool through the existing builder**

Implement `build_artifact_stat_registration(boundary, *, policy, prepare_binding)` and append it after the current real seven registrations in `build_file_tool_registrations`; do not replace them with a shortened example or create a parallel registration collection. Change the current `return (` token to `registrations = (`, leave the seven existing `read_file/list_files/search_paths/search_text/read_file_chunk/write_file/edit_file` `RegisteredTool` blocks unchanged, then add exactly:

```python
return (
    *registrations,
    build_artifact_stat_registration(
        boundary,
        policy=file_policy,
        prepare_binding=safe_binding(
            lambda arguments: artifact_stat_prepare_binding(
                boundary,
                arguments["path"],
                max_bytes=MAX_OUTPUT_BYTES,
            )
        ),
    ),
)
```

The callable returns canonical JSON text from an `ArtifactStatV1` created from a fresh `snapshot_binary(path, max_bytes=MAX_OUTPUT_BYTES)`. `snapshot_digest` binds normalized path, device, inode, size, mtime-ns and raw digest; `observed_at` comes from an injected clock and is excluded only from stable snapshot identity, not from displayed result.

- [ ] **Step 6: Run the Green tests**

Run: `.venv/bin/python -m pytest -q tests/artifacts/test_workspace.py tests/artifacts/test_tools.py tests/tools/test_path_safety.py tests/tools/test_file_tools.py -rx`

Run: `.venv/bin/ruff check agent/tools/path_safety.py agent/tools/file_ops.py agent/artifacts/workspace.py agent/artifacts/tools.py tests/artifacts tests/tools/test_path_safety.py tests/tools/test_file_tools.py`

Expected: both exit 0; every drift test records zero commit.

- [ ] **Step 7: Commit the checkpoint if authorized**

```bash
git add agent/tools/path_safety.py agent/tools/file_ops.py agent/artifacts/workspace.py agent/artifacts/tools.py tests/artifacts/test_workspace.py tests/artifacts/test_tools.py tests/tools/test_path_safety.py tests/tools/test_file_tools.py
git commit -m "feat(artifacts): add bounded binary workspace io"
```

---

### Task 3: Join the single packaged adapter to typed Artifact receipts and evidence

**Files:**
- Modify: `agent/skill/executable_contracts.py`
- Modify: `agent/skill/execution.py`
- Modify: `agent/skill/executable_results.py`
- Modify: `agent/skill/tools.py`
- Modify: `agent/artifacts/contracts.py`
- Modify: `agent/artifacts/codec.py`
- Modify: `agent/artifacts/workspace.py`
- Modify: `agent/runtime/contracts.py`
- Modify: `agent/runtime/tools.py`
- Modify: `agent/runtime/evidence.py`
- Create: `agent/artifacts/evidence.py`
- Create: `tests/artifacts/test_adapter_integration.py`
- Create: `tests/artifacts/test_evidence.py`
- Modify: `tests/skill/test_executable_contracts.py`
- Modify: `tests/skill/test_executable_tools.py`
- Modify: `tests/kernel/test_tool_runtime.py`
- Modify: `tests/kernel/test_evidence_registry.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class ArtifactMutationDraftV1:
    expectation: ArtifactExpectationV1
    observation: ArtifactObservationV1
    process_draft_digest: str
    target_path: str
    target_precondition_digest: str | None
    output_raw_sha256: str
    output_byte_count: int
    detected_format: ArtifactFormatV1
    commit_outcome: ArtifactCommitOutcomeV1
    commit_facts: ArtifactCommitFactsV1

@dataclass(frozen=True, slots=True)
class ArtifactSourceBindingV1:
    input_index: int
    runner_slot: str
    normalized_path: str
    snapshot_digest: str
    raw_sha256: str
    byte_count: int

@dataclass(frozen=True, slots=True)
class ArtifactEntrypointBindingV1:
    request_kind: str
    request_digest: str
    source_bindings: tuple[ArtifactSourceBindingV1, ...]
    sources_digest: str
    target_path: str | None
    target_precondition_digest: str | None
    expected_output_format: ArtifactFormatV1 | None
    binding_digest: str

@dataclass(frozen=True, slots=True)
class StructuredSandboxToolDraftV1:
    process: StructuredSandboxProcessDraftV1
    semantic_outcome: PackagedSkillSemanticOutcomeV1
    result: DecodedSkillResultV1 | DecodedArtifactResultV1 | None
    execution_output: ToolExecutionOutput | None
    source_receipt_drafts: tuple[SourceReceiptDraft, ...]
    artifact_observation: ArtifactObservationV1 | None
    artifact_mutation_draft: ArtifactMutationDraftV1 | None
    package_digest: str
    entrypoint_digest: str
    draft_digest: str

VerifyArtifactReadback: TypeAlias = Callable[
    [Sequence[ConversationFact], str, int, AdmittedCriterion, str, str], EvidenceRecord
]
```

`agent/skill/tools.py` owns this immutable 19-entry registration/binding table. The key is the qualified portable `(format, operation, entrypoint.name)` identity, not a model string; the value freezes the only admitted Artifact request kind and the 020a I/O kind:

```python
ARTIFACT_ENTRYPOINT_BINDINGS = MappingProxyType({
    ("pdf", "artifact-read", "inspect"): ("pdf_inspect_v1", "observation"),
    ("pdf", "artifact-read", "extract"): ("pdf_extract_v1", "observation"),
    ("pdf", "artifact-write", "create"): ("pdf_create_v1", "artifact"),
    ("pdf", "artifact-write", "edit"): ("pdf_pages_patch_v1", "artifact"),
    ("docx", "artifact-read", "inspect"): ("docx_inspect_v1", "observation"),
    ("docx", "artifact-read", "extract"): ("docx_extract_v1", "observation"),
    ("docx", "artifact-write", "create"): ("docx_blocks_v1", "artifact"),
    ("docx", "artifact-write", "edit"): ("docx_blocks_patch_v1", "artifact"),
    ("xlsx", "artifact-read", "inspect"): ("xlsx_inspect_v1", "observation"),
    ("xlsx", "artifact-read", "extract"): ("xlsx_extract_v1", "observation"),
    ("xlsx", "artifact-write", "create"): ("xlsx_cells_v1", "artifact"),
    ("xlsx", "artifact-write", "edit"): ("xlsx_cells_patch_v1", "artifact"),
    ("pptx", "artifact-read", "inspect"): ("pptx_inspect_v1", "observation"),
    ("pptx", "artifact-read", "extract"): ("pptx_extract_v1", "observation"),
    ("pptx", "artifact-write", "create"): ("pptx_slides_v1", "artifact"),
    ("pptx", "artifact-write", "edit"): ("pptx_slides_patch_v1", "artifact"),
    ("raster", "artifact-read", "inspect"): ("raster_inspect_v1", "observation"),
    ("raster", "artifact-write", "create"): ("raster_canvas_v1", "artifact"),
    ("raster", "artifact-write", "transform"): ("raster_transform_v1", "artifact"),
})
```

For these entries only, `_entrypoint_schema` requires exact model arguments `{"request": object, "input_paths": [workspace-relative strings]}` for READ and the same plus required `"target_path"` for WRITE; `additionalProperties` is false, paths are not nullable, input count is `0..16`, and canonical request bytes are at most 65,536. The manifest parameters must exact-match byte-sorted `input_paths:json`, `request:json`, and WRITE-only `target_path:text`; a package with another parameter list is excluded before ToolSpec exposure. `decode_artifact_request` must return the table's exact request kind. `artifact_request_slots(request)` returns the integer-sorted unique referenced input indexes and requires them to be exactly `tuple(range(len(input_paths)))`, preventing an unbound, duplicate or unused input. Host index `i` maps once to runner slot `f"input-{i:02d}"`; `ArtifactSourceBindingV1` and each `StructuredSandboxInputV1` bind both that index and exact slot, and the child rejects input keys other than that complete set.

- [ ] **Step 1: Write Red adapter and receipt tests**

Build the adapter through its existing 020b public constructor and `build_packaged_skill_registrations`, using real `SkillActivationGate` test fakes only at the gate port. Cover read/extract and write separately:

- all 19 qualified entries: generated schema exact-matches the table, prepare canonicalizes `request`, snapshots/binds every source and inspects/binds the WRITE target under the short prepare guard, and safety binding contains only relative paths/digests/counts; request/input/target bytes never enter it;
- read/extract: the fresh invoke guard is acquired by the existing 020b callable, all source snapshots are reopened and exact-compared, one `StructuredSandboxIoPlanV1` uses `expected_result_kind=OBSERVATION`, `artifact_cap_bytes=1`, no non-empty artifact is accepted, and Runtime later mints exact `WORKSPACE_PATH` plus bounded `WORKSPACE_EXCERPT` source receipts;
- write: the same fresh guard spans source/target revalidation, `expected_result_kind=ARTIFACT`, the actual result plus artifact aggregate is at most 64 MiB, typed observation raw digest equals staged bytes, request-derived PNG/JPEG/WebP or fixed document magic exact-matches, one target commit plus fresh host readback occurs, and mutation draft binds the existing process draft digest;
- invocation sanitization: child `arguments` is exactly `{"request": canonical_artifact_payload}` and numbered `inputs` contains only the freshly reopened bytes; `input_paths` and `target_path` never cross the runner wire;
- read that writes non-empty `artifact.bin`, missing/replaced/symlinked/truncated/extra result, staged size/digest/magic mismatch, source drift, target drift and revoked gate all fail without commit;
- package identity, storage identity, qualification identity, active snapshot, entrypoint, request, structured invocation and sandbox policy drift all fail before spawn or before commit at their specified boundary;
- ordinary sandbox callable returning an Artifact field is rejected as `structured_draft_forgery`.

Add an exact guard trace assertion: prepare acquires/releases one short SH; invoke acquires one fresh SH; the existing `_PackagedSkillCallable` releases it exactly once only after revalidation, spawn, staged readback, optional commit and fresh committed readback. `_finish_artifact`, `WorkspaceArtifactIo` and `ToolRuntime` never call `release()`.

Patch adapter test fixtures to raise after atomic replace and before returning the structured draft. Assert the exception propagates through `KernelToolRuntime.invoke` for WRITE so existing Runtime enters unknown recovery; there is no second replace on resume.

- [ ] **Step 2: Write Red evidence mutation tests**

Create one valid checkpointed `TOOL_RESULT` fact with full typed sandbox receipt, typed mutation receipt and fresh `artifact_stat` fact. Assert `ARTIFACT_READBACK` passes. Mutate every frozen join field independently: Goal id/revision, ToolSpec identity, package, qualification, entrypoint, request, sandbox receipt, target path, output digest, stat snapshot/path/digest, observation raw/structure digest, commit outcome and receipt digest. Each mutation must raise `EvidenceVerificationError`. Storage and active-snapshot drift remain adapter admission tests because the frozen mutation receipt does not carry those fields.

Add rejection cases for prose only, exit 0 only, free JSON, `fake`/`mock`, truncated or partial observation, `executed=False`, `is_error=True`, known-executed error without commit, unknown-outcome user classification and a sandbox receipt from a different tool result in the same Goal.

- [ ] **Step 3: Run the Reds**

Run: `.venv/bin/python -m pytest -q tests/artifacts/test_adapter_integration.py tests/artifacts/test_evidence.py tests/skill/test_executable_contracts.py tests/skill/test_executable_tools.py tests/kernel/test_tool_runtime.py tests/kernel/test_evidence_registry.py -rx`

Expected: FAIL because the existing adapter cannot produce Artifact drafts and `EvidenceOracleKind.ARTIFACT_READBACK` is absent.

- [ ] **Step 4: Add Artifact handling inside the one existing adapter**

At the existing enum owner, add only:

```python
class SkillFormatV1(StrEnum):
    # existing values stay unchanged
    RASTER = "raster"
```

Add codec/contract Reds proving `raster` is accepted only as a manifest format, while `ArtifactFormatV1("raster")` fails. The three raster entrypoints use this family; `RasterCanvasRequestV1.format`, the final `raster_transcode` operation, or the bound input magic determines PNG/JPEG/WebP expectation.

Do not add a new `execute` owner. Extend the existing `PackagedSkillBindingV1` with nullable-as-a-group `artifact_request_kind`, `artifact_request_digest`, `artifact_sources_digest`, `artifact_target_path`, `artifact_target_precondition_digest`, and `artifact_expected_output_format`; all six are absent for non-Artifact entries. The existing prepare path in `agent/skill/tools.py` constructs `ArtifactEntrypointBindingV1`, and the adapter serializes only its digest fields into `PackagedSkillBindingV1`. At invoke, while the existing callable holds the fresh long SH guard, reopen every source with `snapshot_binary`, exact-compare input index/runner slot/path/snapshot/raw digest/count, re-inspect the target, exact-compare the target precondition, and rebuild the entire binding before the first spawn.

Construct the 020a I/O plan exactly:

```python
is_write = entrypoint.operation is SkillOperationV1.ARTIFACT_WRITE
io_plan = StructuredSandboxIoPlanV1(
    package_digest=package.active.package_digest,
    entrypoint_id=entrypoint.name,
    entrypoint_digest=entrypoint.entrypoint_digest,
    request_bytes=runner_request_bytes,
    request_digest=hashlib.sha256(runner_request_bytes).hexdigest(),
    inputs=tuple(structured_inputs),
    result_cap_bytes=MAX_OUTPUT_BYTES,
    artifact_cap_bytes=MAX_OUTPUT_BYTES if is_write else 1,
    aggregate_output_cap_bytes=MAX_OUTPUT_BYTES,
    expected_result_kind=(
        StructuredResultKind.ARTIFACT
        if is_write
        else StructuredResultKind.OBSERVATION
    ),
)
```

`runner_request_bytes` is the existing exact eight-key 020a request. Its `arguments` value is only `{"request": artifact_request_payload}` and its `inputs` descriptors come from fresh `BinarySnapshotV1` values; the request digest therefore binds the sanitized typed request and every content identity. No staged artifact can exceed 64 MiB, and actual `len(result_bytes) + len(artifact_bytes)` must remain within the same 64 MiB aggregate.

After the 020a process draft is available, branch only on the already-qualified entrypoint result kind:

```python
if entrypoint.result.kind is SkillResultKindV1.ARTIFACT_OBSERVATION:
    return self._finish_artifact(
        intent=intent,
        binding=binding,
        entrypoint=entrypoint,
        source_snapshots=fresh_snapshots,
        process_draft=process_draft,
    )
return self._finish_existing_result(intent=intent, plan=plan, process_draft=process_draft)
```

`_finish_artifact` calls the existing outer result decoder once in the adapter, obtains `DecodedArtifactResultV1`, validates its observation against `ArtifactExpectationV1`, builds a bounded `ToolExecutionOutput`, constructs deterministic `SourceReceiptDraft` values from the bound snapshots/projection, and delegates staged bytes to `WorkspaceArtifactIo`. The draft's `execution_output.source_receipts` is exactly empty because only Runtime may mint durable receipts; the separate `source_receipt_drafts` field carries the canonical pre-mint facts for Runtime's exact comparison. READ rejects non-empty `process_draft.artifact_bytes`. WRITE requires bytes, exact output digest/magic/format, one commit and a fresh committed `BinarySnapshotV1`. It does not acquire or release the guard; the existing 020b callable holds that guard through its return and is the sole release owner.

Return the existing `StructuredSandboxToolDraftV1` with `execution_output`, canonical `source_receipt_drafts`, `artifact_observation` and optional `artifact_mutation_draft`. Include every field's canonical digest in `identity_values()` and enforce: execution output/observation are required for valid Artifact results; mutation is required exactly for WRITE; mutation/process artifact/committed readback/observation raw digests agree; READ has no mutation or artifact bytes; non-Artifact result kind rejects all four extension fields. The draft carries no raw workspace bytes, but its existing `process` retains bounded session `result_bytes` and optional staged artifact bytes for Runtime's independent verification.

- [ ] **Step 5: Mint receipts only in `ToolRuntime`**

Extend the existing packaged structured outcome branch; do not trust the adapter's decoded object or prose. `KernelToolRuntime._packaged_skill_outcome` independently calls the one outer decoder again on `draft.process.result_bytes` and the exact intent expectation, then recomputes the Artifact observation, execution projection, source drafts and all extension identity digests. Before minting anything it requires exact equality with `draft.result`, `draft.execution_output`, `draft.source_receipt_drafts`, `draft.artifact_observation`, the process artifact digest/size, and `draft.artifact_mutation_draft`. A forged wrapper around authentic process bytes must return `structured_draft_forgery` and mint no receipt.

The exact normalization order is:

```python
runtime_decoded = decode_packaged_skill_result(draft.process, expectation)
runtime_artifact = require_decoded_artifact(runtime_decoded, binding)
runtime_output, runtime_source_drafts = build_artifact_execution_output(
    runtime_artifact,
    binding=binding,
)
runtime_mutation_draft = rebuild_artifact_mutation_draft(
    decoded=runtime_artifact,
    binding=binding,
    process=draft.process,
    commit_facts=(
        draft.artifact_mutation_draft.commit_facts
        if draft.artifact_mutation_draft is not None
        else None
    ),
)
if (
    runtime_decoded != draft.result
    or runtime_artifact.observation != draft.artifact_observation
    or runtime_output != draft.execution_output
    or runtime_source_drafts != draft.source_receipt_drafts
    or runtime_mutation_draft != draft.artifact_mutation_draft
):
    return structured_draft_forgery(intent, spec)
sandbox_result = self._structured_sandbox_outcome(intent, spec, draft.process)
```

`rebuild_artifact_mutation_draft` returns `None` exactly for READ. For WRITE it treats `commit_facts` only as host read-back facts and independently exact-checks their target/precondition against `binding`, their output digest/size/format against both `draft.process.artifact_bytes` and the re-decoded observation, their committed snapshot digest against the canonical fact payload, and their outcome against the single committed-success enum before reconstructing the whole draft/digest. Thus changing any wrapper Artifact field around authentic process bytes triggers `structured_draft_forgery`; the helper never commits or reopens a path.

`_structured_sandbox_outcome` remains the one sandbox receipt minter. Only after it returns an authenticated successful sandbox receipt does Runtime mint `SourceReceiptV1` from the exact-compared drafts, replace the empty `runtime_output.source_receipts` with exactly those minted receipts, and, for WRITE, call `ArtifactMutationReceiptV1.create` using authenticated `ExecutionIntent`, `spec.identity_digest` as `tool_identity`, 021 identities from safety binding, the exact-compared host mutation draft and the newly minted sandbox receipt digest. The callable cannot return any durable receipt directly. Metadata contains typed source receipts, full typed JSON under `artifact_mutation_receipt`, its `receipt_digest`, and the bounded observation; it never contains raw input/output bytes, absolute paths or transient path names. Mutation plus source outputs remain in the same Runtime result checkpoint.

- [ ] **Step 6: Add the closed oracle to the existing registry**

Add `ARTIFACT_READBACK = "artifact_readback"` to `EvidenceOracleKind`; route only that enum in `ClosedEvidenceRegistry.derive`. `agent.artifacts.evidence.verify_artifact_readback` strict-decodes and recomputes both durable receipts, selects the single matching checkpointed tool-result fact, then selects a fresh `artifact_stat` fact observed after the mutation receipt. Predicate exact keys are:

```python
ARTIFACT_READBACK_KEYS = frozenset({
    "receipt_kind", "tool_identity", "package_digest", "qualification_digest",
    "entrypoint_digest", "request_digest", "target_path", "output_raw_sha256",
    "sandbox_receipt_digest", "structure_digest",
})
```

`receipt_kind` must equal `artifact_mutation_v1`; `structure_digest` may be absent. When present, observation must be untruncated, raw digest must equal output digest and its label is exactly `PACKAGE_OBSERVATION_CONFIRMED`. The evidence record never claims independent semantic verification.

- [ ] **Step 7: Run the Green tests**

Run: `.venv/bin/python -m pytest -q tests/artifacts/test_adapter_integration.py tests/artifacts/test_evidence.py tests/skill/test_executable_contracts.py tests/skill/test_executable_tools.py tests/kernel/test_tool_runtime.py tests/kernel/test_evidence_registry.py -rx`

Run: `.venv/bin/ruff check agent/artifacts agent/skill/executable_contracts.py agent/skill/execution.py agent/skill/executable_results.py agent/skill/tools.py agent/runtime/contracts.py agent/runtime/tools.py agent/runtime/evidence.py tests/artifacts tests/skill/test_executable_contracts.py tests/skill/test_executable_tools.py tests/kernel/test_tool_runtime.py tests/kernel/test_evidence_registry.py`

Expected: both exit 0; receipt field-by-field mutation has no passing mutant.

- [ ] **Step 8: Commit the checkpoint if authorized**

```bash
git add agent/skill/executable_contracts.py agent/skill/execution.py agent/skill/executable_results.py agent/skill/tools.py agent/artifacts/contracts.py agent/artifacts/codec.py agent/artifacts/workspace.py agent/artifacts/evidence.py agent/runtime/contracts.py agent/runtime/tools.py agent/runtime/evidence.py tests/artifacts/test_adapter_integration.py tests/artifacts/test_evidence.py tests/skill/test_executable_contracts.py tests/skill/test_executable_tools.py tests/kernel/test_tool_runtime.py tests/kernel/test_evidence_registry.py
git commit -m "feat(artifacts): bind artifact receipts to sandbox readback"
```

---

### Task 4: Freeze the release-owned offline parser closure contract

**Files:**
- Modify: `pyproject.toml`
- Create: `agent/bundled_skills/__init__.py`
- Create: `agent/artifact_runtime/dependencies.py`
- Create: `tests/artifacts/package_assertions.py`
- Create: `tests/artifacts/test_dependency_closure.py`

**Frozen package matrix:**

| Package | Entry points | Exact direct requirements |
| --- | --- | --- |
| `pdf-workspace@1.0.0` | `inspect`, `extract`, `create`, `edit` | `pypdf==6.16.2`, `reportlab==5.0.1` |
| `docx-workspace@1.0.0` | `inspect`, `extract`, `create`, `edit` | `python-docx==1.2.0` |
| `xlsx-workspace@1.0.0` | `inspect`, `extract`, `create`, `edit` | `openpyxl==3.1.5` |
| `pptx-workspace@1.0.0` | `inspect`, `extract`, `create`, `edit` | `python-pptx==1.0.2`, `pillow==12.3.0` |
| `raster-image-workspace@1.0.0` | `inspect`, `create`, `transform` | `pillow==12.3.0`, `reportlab==5.0.1` |

- [ ] **Step 1: Write Red offline-closure tests**

Freeze the exact direct and transitive installed distribution versions as an immutable module constant. Tests build a synthetic release-owned installed closure fixture and call 020a `qualify_hermetic_runtime_closure`; mutate a distribution version, installed file digest, interpreter identity and inventory member and assert fail closed. Task 4 does not open `agent/bundled_skills/*`, because those package directories are created only in Tasks 5–8. It does not test wheelhouse identity; the verifier-only seal is created and tested with its CLI in Task 10. The product runtime and 021 never invoke pip, install a dependency or select a wheel.

```python
EXPECTED_INSTALLED_DISTRIBUTIONS = MappingProxyType({
    "charset-normalizer": "3.5.1",
    "et-xmlfile": "2.0.0",
    "lxml": "6.1.2",
    "openpyxl": "3.1.5",
    "pillow": "12.3.0",
    "pypdf": "6.16.2",
    "python-docx": "1.2.0",
    "python-pptx": "1.0.2",
    "reportlab": "5.0.1",
    "typing-extensions": "4.16.0",
    "xlsxwriter": "3.2.9",
})

def test_installed_artifact_runtime_closure_is_exact(synthetic_installed_closure):
    closure = qualify_hermetic_runtime_closure(synthetic_installed_closure.root)
    assert not isinstance(closure, KnownNotExecuted)
    assert installed_distribution_versions(closure) == EXPECTED_INSTALLED_DISTRIBUTIONS
```

- [ ] **Step 2: Run the Reds**

Run: `.venv/bin/python -m pytest -q tests/artifacts/test_dependency_closure.py -rx`

Expected: FAIL because the frozen Artifact dependency inventory and closure verifier binding are absent.

- [ ] **Step 3: Freeze release dependency closure**

Add these exact production dependencies under `artifact-runtime`. 020a `qualify_hermetic_runtime_closure` verifies every installed file and the release-provided `runtime-closure-v1.json`; 021 only records/verifies that closure digest and never materializes it:

```toml
artifact-runtime = [
    "pillow==12.3.0",
    "XlsxWriter==3.2.9",
    "charset-normalizer==3.5.1",
    "et-xmlfile==2.0.0",
    "lxml==6.1.2",
    "openpyxl==3.1.5",
    "pypdf==6.16.2",
    "python-docx==1.2.0",
    "python-pptx==1.0.2",
    "reportlab==5.0.1",
    "typing-extensions==4.16.0",
]
artifact-e3 = [
    "cffi==2.1.1",
    "charset-normalizer==3.5.1",
    "cryptography==50.0.1",
    "pdfminer.six==20260107",
    "pycparser==3.0",
]
```

Add package data with explicit patterns for `SKILL.md`, `first-agent.json`, `skill.requirements.json`, `scripts/*.py` and `references/*`. Do not include an open recursive glob. Clean materialized gates may install only from a pre-provisioned, digest-sealed local wheelhouse with `--no-index`; absence or digest drift is a closed blocked gate, never permission to use network or ambient pip cache.

- [ ] **Step 4: Freeze only reusable dependency helpers**

Add `expected_portable_requirements(expected)` to the test-only `tests/artifacts/package_assertions.py`, but do not add a scanner/package assertion in Task 4. It returns the 020b exact nested shape and is consumed when each package is created in Tasks 5–8:

```python
def expected_portable_requirements(expected: Mapping[str, str]) -> dict[str, object]:
    return {
        "schema": "first-agent-skill-requirements/v1",
        "runtime": {
            "kind": "python-structured-v1",
            "abi": "cpython-3.11",
        },
        "runtime_profile": "artifact-standard-v1",
        "dependencies": [
            {"name": name, "version": version}
            for name, version in sorted(expected.items())
        ],
    }
```

Each format Task creates its complete `SKILL.md`, `first-agent.json`, nested-shape `skill.requirements.json` and all declared scripts in the same Green checkpoint, then asserts its own exact entrypoint and requirement map. No Task 4 test reads a future package path and no intermediate commit contains a manifest whose script is missing.

- [ ] **Step 5: Run the offline-closure Green tests**

Run: `.venv/bin/python -m pytest -q tests/artifacts/test_dependency_closure.py -rx`

Run: `.venv/bin/ruff check agent/artifact_runtime/dependencies.py agent/bundled_skills tests/artifacts/package_assertions.py tests/artifacts/test_dependency_closure.py`

Expected: both exit 0; exact dependency identities are closed and every synthetic drift is rejected without invoking a package manager.

- [ ] **Step 6: Commit the checkpoint if authorized**

```bash
git add pyproject.toml agent/artifact_runtime/dependencies.py agent/bundled_skills/__init__.py tests/artifacts/package_assertions.py tests/artifacts/test_dependency_closure.py
git commit -m "feat(artifacts): freeze offline parser runtime closure"
```

---

### Task 5: Implement PDF and raster as the first two real consumers

**Files:**
- Create: `agent/artifact_runtime/__init__.py`
- Create: `agent/artifact_runtime/common.py`
- Create: `agent/artifact_runtime/preflight.py`
- Create: `agent/artifact_runtime/pdf.py`
- Create: `agent/artifact_runtime/raster.py`
- Create: `agent/artifact_runtime/dispatch.py`
- Create: `agent/bundled_skills/pdf-workspace/SKILL.md`
- Create: `agent/bundled_skills/pdf-workspace/first-agent.json`
- Create: `agent/bundled_skills/pdf-workspace/skill.requirements.json`
- Create: `agent/bundled_skills/pdf-workspace/scripts/inspect.py`
- Create: `agent/bundled_skills/pdf-workspace/scripts/extract.py`
- Create: `agent/bundled_skills/pdf-workspace/scripts/create.py`
- Create: `agent/bundled_skills/pdf-workspace/scripts/edit.py`
- Create: `agent/bundled_skills/raster-image-workspace/SKILL.md`
- Create: `agent/bundled_skills/raster-image-workspace/first-agent.json`
- Create: `agent/bundled_skills/raster-image-workspace/skill.requirements.json`
- Create: `agent/bundled_skills/raster-image-workspace/scripts/inspect.py`
- Create: `agent/bundled_skills/raster-image-workspace/scripts/create.py`
- Create: `agent/bundled_skills/raster-image-workspace/scripts/transform.py`
- Create: `tests/artifacts/test_bundled_packages.py`
- Modify: `tests/artifacts/package_assertions.py`
- Create: `tests/artifacts/test_pdf.py`
- Create: `tests/artifacts/test_raster.py`

- [ ] **Step 1: Write Red PDF/raster package and PDF journeys**

Write Reds that require both complete package directories, including all manifests/requirements and every declared thin script, before their first scanner success. The tests feed each directory through the 021 canonical scanner and use this exact assertion; it checks the complete byte-sorted entrypoint list, common runtime `python-structured-v1`, byte-sorted READ/WRITE parameters, `artifact-observation-v1` with `max_chars=64_000`, `artifact-standard-v1`, network `off`, exact inventory-resolved script descriptor/digest, and no undeclared executable:

```python
assert_bundled_package(
    "pdf-workspace",
    version="1.0.0",
    family="pdf",
    entrypoints={
        "create": ("artifact-write", "scripts/create.py", "pdf_create_v1"),
        "edit": ("artifact-write", "scripts/edit.py", "pdf_pages_patch_v1"),
        "extract": ("artifact-read", "scripts/extract.py", "pdf_extract_v1"),
        "inspect": ("artifact-read", "scripts/inspect.py", "pdf_inspect_v1"),
    },
    requirements=expected_portable_requirements({
        "pypdf": "6.16.2",
        "reportlab": "5.0.1",
    }),
)
assert_bundled_package(
    "raster-image-workspace",
    version="1.0.0",
    family="raster",
    entrypoints={
        "create": ("artifact-write", "scripts/create.py", "raster_canvas_v1"),
        "inspect": ("artifact-read", "scripts/inspect.py", "raster_inspect_v1"),
        "transform": ("artifact-write", "scripts/transform.py", "raster_transform_v1"),
    },
    requirements=expected_portable_requirements({
        "pillow": "12.3.0",
        "reportlab": "5.0.1",
    }),
)
```

Then generate a three-page synthetic PDF with markers `PDF-PAGE-ONE`, `PDF-PAGE-TWO`, `PDF-PAGE-THREE`. Test full/page-selected inspect and extract; A4/Letter create from Markdown and structured text; title/author flags; merge/select/reorder/delete/rotate; exact text/page/order digests; empty/overlapping/out-of-range selector rejection; 500-page cap; encrypted inspect flag and encrypted extract/edit refusal; JavaScript/attachment/form/signature flags; active-content edit refusal before staged output.

Creation accepts this source grammar only: UTF-8 lines, `# ` heading, `## ` subheading, blank paragraph separator and ordinary paragraph text. Backticks, HTML and links remain literal text. Structured text is canonical JSON `{"blocks":[{"kind":"heading|paragraph","text":str}]}` with 1..10,000 blocks. ReportLab uses release-owned Helvetica/Helvetica-Bold, fixed margins/leading, no current time and deterministic metadata.

- [ ] **Step 2: Write Red raster journeys**

For PNG/JPEG/WebP, test inspect; canvas with rectangle/ellipse/line/text/composite; crop/resize/rotate/transcode/metadata strip/preserve allowlist; RGB/RGBA; deterministic repeat raw digest; width/height/pixel caps; crop/canvas bounds after every operation; JPEG RGBA flattening; EXIF/GPS/ICC/XMP flags; multi-frame refusal; metadata default strip; invalid font/quality/filter/multiple transcode/multiple metadata rejection. Raster projection contains metadata/dimensions/digests only and never base64/pixel bytes.

- [ ] **Step 3: Run the Reds**

Run: `.venv/bin/python -m pytest -q tests/artifacts/test_bundled_packages.py tests/artifacts/test_pdf.py tests/artifacts/test_raster.py -rx`

Expected: FAIL because parser runtime and declared package scripts are absent.

- [ ] **Step 4: Implement shared child contracts and dispatch**

`dispatch.run_declared_entrypoint` receives the outer runner's exact `arguments` and immutable numbered byte mapping, never paths. It strict-decodes `arguments == {"request": object}`, checks input keys equal the request's complete `input-{index:02d}` set, and verifies declared family/request kind before dispatch:

```python
HANDLERS = {
    "pdf_inspect_v1": pdf.inspect,
    "pdf_extract_v1": pdf.extract,
    "pdf_create_v1": pdf.create,
    "pdf_pages_patch_v1": pdf.edit,
    "raster_inspect_v1": raster.inspect,
    "raster_canvas_v1": raster.create,
    "raster_transform_v1": raster.transform,
}

def run_declared_entrypoint(
    *,
    declared_family: str,
    declared_request_kind: str,
    arguments: Mapping[str, object],
    inputs: Mapping[str, bytes],
) -> dict[str, object]:
    if set(arguments) != {"request"}:
        raise TerminalRefusal("artifact arguments are not closed")
    request = decode_artifact_request(arguments["request"])
    if request.kind != declared_request_kind:
        raise TerminalRefusal("request kind does not match the qualified entrypoint")
    indexes = artifact_request_slots(request)
    slots = tuple(f"input-{index:02d}" for index in indexes)
    if set(inputs) != set(slots):
        raise TerminalRefusal("artifact input slots do not match the request")
    ordered_inputs = tuple(inputs[slot] for slot in slots)
    handler = HANDLERS.get(request.kind)
    if handler is None:
        raise TerminalRefusal("qualified Artifact handler is unavailable")
    result = handler(request, ordered_inputs)
    expected_format = expected_artifact_format(
        declared_family=declared_family,
        request=request,
        inputs=ordered_inputs,
    )
    if result.observation.format is not expected_format:
        raise TerminalRefusal("handler returned a mismatched artifact format")
    is_write = request.kind in ARTIFACT_WRITE_REQUEST_KINDS
    if is_write != (result.artifact is not None):
        raise TerminalRefusal("handler returned the wrong artifact result shape")
    return {
        "kind": "artifact" if is_write else "observation",
        "payload": encode_artifact_observation_payload(result.observation),
        "artifact": result.artifact,
    }
```

Every package script is a literal declaration only:

```python
from agent.artifact_runtime.dispatch import run_declared_entrypoint


def run(arguments, inputs):
    return run_declared_entrypoint(
        declared_family="pdf",
        declared_request_kind="pdf_inspect_v1",
        arguments=arguments,
        inputs=inputs,
    )
```

Freeze every file's two literals in `tests/artifacts/test_bundled_packages.py`; the test renders the body above and exact-compares UTF-8 bytes, so a script cannot add an alternate entrypoint path:

```python
SCRIPT_DECLARATIONS = MappingProxyType({
    "pdf-workspace/scripts/create.py": ("pdf", "pdf_create_v1"),
    "pdf-workspace/scripts/edit.py": ("pdf", "pdf_pages_patch_v1"),
    "pdf-workspace/scripts/extract.py": ("pdf", "pdf_extract_v1"),
    "pdf-workspace/scripts/inspect.py": ("pdf", "pdf_inspect_v1"),
    "docx-workspace/scripts/create.py": ("docx", "docx_blocks_v1"),
    "docx-workspace/scripts/edit.py": ("docx", "docx_blocks_patch_v1"),
    "docx-workspace/scripts/extract.py": ("docx", "docx_extract_v1"),
    "docx-workspace/scripts/inspect.py": ("docx", "docx_inspect_v1"),
    "xlsx-workspace/scripts/create.py": ("xlsx", "xlsx_cells_v1"),
    "xlsx-workspace/scripts/edit.py": ("xlsx", "xlsx_cells_patch_v1"),
    "xlsx-workspace/scripts/extract.py": ("xlsx", "xlsx_extract_v1"),
    "xlsx-workspace/scripts/inspect.py": ("xlsx", "xlsx_inspect_v1"),
    "pptx-workspace/scripts/create.py": ("pptx", "pptx_slides_v1"),
    "pptx-workspace/scripts/edit.py": ("pptx", "pptx_slides_patch_v1"),
    "pptx-workspace/scripts/extract.py": ("pptx", "pptx_extract_v1"),
    "pptx-workspace/scripts/inspect.py": ("pptx", "pptx_inspect_v1"),
    "raster-image-workspace/scripts/create.py": ("raster", "raster_canvas_v1"),
    "raster-image-workspace/scripts/inspect.py": ("raster", "raster_inspect_v1"),
    "raster-image-workspace/scripts/transform.py": ("raster", "raster_transform_v1"),
})
```

Each format task exact-checks only the package paths created by that task, so Task 5 does not require later packages to exist. No script defines `__main__`, a second runner/codec, filesystem I/O, receipt construction or exception-to-success conversion. `expected_artifact_format` returns the fixed PDF/DOCX/XLSX/PPTX format for document families; for `raster` it uses only the strict typed canvas format, final transform transcode (or bound source magic when absent), or inspect source magic, and returns only PNG/JPEG/WEBP. It never constructs `ArtifactFormatV1("raster")`.

- [ ] **Step 5: Implement PDF with bounded preflight**

`preflight_pdf` checks `%PDF-`, bounded trailer/startxref shape, encryption and active-content name tokens before `PdfReader`. It does not declare a safe file solely from substring absence; parser inspection confirms catalog/name-tree/AcroForm/signature objects. `inspect` may report all flags. `extract` refuses encryption and emits selected text in page order with a 64,000-character projection cap and explicit truncation. `edit` refuses any active flag.

For create, draw deterministic wrapped lines to a `BytesIO` with `canvas.Canvas(output, invariant=1, pageCompression=1)`, pass fixed producer/creator metadata and no current timestamp, then normalize with `PdfWriter`. For edit, read each input, append exactly `page_order`, apply rotations by output-page number and set only `/Title` and `/Author`. Reopen produced bytes with `PdfReader`, compute the observation, compare requested page count/order and return bytes plus observation.

- [ ] **Step 6: Implement raster with deterministic encoding**

Set `Image.MAX_IMAGE_PIXELS = 50_000_000` and promote Pillow decompression warnings to errors. Preflight parses signature/header dimensions and frame declarations before `Image.open`; then require `n_frames == 1`. Normalize modes to RGB/RGBA. Resolve `sans_regular_v1` and `sans_bold_v1` only to `reportlab/fonts/Vera.ttf` and `reportlab/fonts/VeraBd.ttf` through `importlib.resources`; those files are bound by the hermetic runtime closure digest and their host paths never enter output. Use fixed encoder settings: PNG `optimize=False, compress_level=9`; JPEG `quality=requested_or_85, subsampling=0, optimize=False, progressive=False`; WebP `quality=requested_or_80, method=6, exact=True`.

Every transform applies in array order, immediately checks sides/pixels and records the final format. Default metadata mode is `strip`; `preserve_allowlist` may retain ICC only, never EXIF/GPS/XMP. Compute `pixel_digest` from `mode + width + height + image.tobytes()` and raw digest from encoded bytes. Reopen encoded bytes and require reported dimensions/mode/format to match before returning.

- [ ] **Step 7: Run the Green tests**

Run: `.venv/bin/python -m pytest -q tests/artifacts/test_pdf.py tests/artifacts/test_raster.py tests/artifacts/test_bundled_packages.py -rx`

Run: `.venv/bin/ruff check agent/artifact_runtime agent/bundled_skills/pdf-workspace agent/bundled_skills/raster-image-workspace tests/artifacts/package_assertions.py tests/artifacts/test_bundled_packages.py tests/artifacts/test_pdf.py tests/artifacts/test_raster.py`

Expected: both exit 0; PDF and each raster format repeat three times with identical structure and raw digests.

- [ ] **Step 8: Commit the checkpoint if authorized**

```bash
git add agent/artifact_runtime agent/bundled_skills/pdf-workspace agent/bundled_skills/raster-image-workspace tests/artifacts/package_assertions.py tests/artifacts/test_bundled_packages.py tests/artifacts/test_pdf.py tests/artifacts/test_raster.py
git commit -m "feat(artifacts): add pdf and raster skill consumers"
```

---

### Task 6: Implement DOCX inspect, extract, create and exact patch

**Files:**
- Create: `agent/artifact_runtime/docx.py`
- Modify: `agent/artifact_runtime/common.py`
- Modify: `agent/artifact_runtime/preflight.py`
- Modify: `agent/artifact_runtime/dispatch.py`
- Create: `agent/bundled_skills/docx-workspace/SKILL.md`
- Create: `agent/bundled_skills/docx-workspace/first-agent.json`
- Create: `agent/bundled_skills/docx-workspace/skill.requirements.json`
- Create: `agent/bundled_skills/docx-workspace/scripts/inspect.py`
- Create: `agent/bundled_skills/docx-workspace/scripts/extract.py`
- Create: `agent/bundled_skills/docx-workspace/scripts/create.py`
- Create: `agent/bundled_skills/docx-workspace/scripts/edit.py`
- Modify: `tests/artifacts/test_bundled_packages.py`
- Create: `tests/artifacts/test_docx.py`

- [ ] **Step 1: Write Red DOCX field and journey tests**

Write Reds that require the complete DOCX package directory, including every declared script, and require the 021 scanner plus this exact shared-package assertion to pass before parser tests:

```python
assert_bundled_package(
    "docx-workspace",
    version="1.0.0",
    family="docx",
    entrypoints={
        "create": ("artifact-write", "scripts/create.py", "docx_blocks_v1"),
        "edit": ("artifact-write", "scripts/edit.py", "docx_blocks_patch_v1"),
        "extract": ("artifact-read", "scripts/extract.py", "docx_extract_v1"),
        "inspect": ("artifact-read", "scripts/inspect.py", "docx_inspect_v1"),
    },
    requirements=expected_portable_requirements({"python-docx": "1.2.0"}),
)
```

The helper exact-checks the nested runtime/runtime-profile shape frozen in Task 4 and all common manifest/script properties frozen in Task 5. Each of the four scripts defines only `run(arguments, inputs)` and delegates with its literal family/request kind; an AST assertion rejects `__main__`, `package_main`, path opens and a locally defined decoder. Create a synthetic document with normal/title/heading paragraphs, a 2x2 table and Unicode NFC markers. Assert inspect/extract null selection follows document order; explicit addresses preserve request order; empty document yields an empty `blocks`; paragraph/table/cell digests are exact. Exercise all four patch operations, expected-text mismatch, source-structure mismatch, duplicate/conflicting address, wrong address kind, deletion of absent block, ragged/empty/oversized table and block/operation caps.

Create macro-enabled content-type, `vbaProject.bin`, OLE object, external relationship, Track Changes and embedded executable fixtures. Inspect reports sorted `OFFICE_*` flags; extract does not follow relationships; edit refuses before output. Create output contains none of those flags.

- [ ] **Step 2: Run the Red test**

Run: `.venv/bin/python -m pytest -q tests/artifacts/test_bundled_packages.py tests/artifacts/test_docx.py -rx`

Expected: FAIL because DOCX handler and scripts are absent from dispatch.

- [ ] **Step 3: Add deterministic OOXML serialization**

Add one shared function used by all Office handlers. It accepts bounded ZIP bytes, revalidates the closed inventory, sorts canonical names and rewrites every member with a fixed timestamp, owner-only regular mode and no extra/comment/encryption/data-descriptor semantics:

```python
def canonicalize_ooxml(raw: bytes) -> bytes:
    source = ZipFile(BytesIO(raw), "r")
    inventory = validate_office_zip(source)
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=9) as target:
        for item in sorted(inventory, key=lambda value: value.name.encode("utf-8")):
            info = ZipInfo(item.name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100600 << 16
            target.writestr(info, source.read(item.name), compress_type=ZIP_DEFLATED,
                            compresslevel=9)
    return output.getvalue()
```

`validate_office_zip` runs before XML/parser decode, limits 10,000 parts and 256 MiB expanded bytes, rejects duplicate/NFC/casefold/path collisions, symlink/device modes, encryption, Zip64/data descriptor, suspicious ratios, DTD/entity declarations and wrong Office content types.

- [ ] **Step 4: Implement DOCX behavior**

Load only `BytesIO` with `Document`. Enumerate top-level paragraph/table nodes using `document.iter_inner_content()` and create canonical addresses. Cell text is paragraph text joined with `\n`; table digest serializes the rectangular rows as canonical JSON.

Create uses only `add_paragraph`, built-in `Title/Heading 1/Heading 2/Heading 3` and `add_table`; it never loads external templates. Edit first recomputes structure digest, refuses active flags, resolves all addresses against an immutable index, validates every `expected`, then mutates. `delete_block` removes only the exact paragraph/table XML element; `append_blocks` uses create helpers; `set_cell` replaces all paragraphs in the exact cell with one plain paragraph. Set created/modified/last-printed core properties to `2000-01-01T00:00:00Z`, recompute observation, save to `BytesIO`, canonicalize OOXML, reopen and require the same structure digest before returning bytes.

- [ ] **Step 5: Run the Green test**

Run: `.venv/bin/python -m pytest -q tests/artifacts/test_docx.py tests/artifacts/test_bundled_packages.py -rx`

Run: `.venv/bin/ruff check agent/artifact_runtime/docx.py agent/artifact_runtime/common.py agent/artifact_runtime/preflight.py agent/artifact_runtime/dispatch.py agent/bundled_skills/docx-workspace tests/artifacts/test_bundled_packages.py tests/artifacts/test_docx.py`

Expected: both exit 0; three repeated create/edit runs produce identical raw and structure digests.

- [ ] **Step 6: Commit the checkpoint if authorized**

```bash
git add agent/artifact_runtime agent/bundled_skills/docx-workspace tests/artifacts/test_bundled_packages.py tests/artifacts/test_docx.py
git commit -m "feat(artifacts): add docx workspace skill"
```

---

### Task 7: Implement XLSX inspect, extract, create and exact patch

**Files:**
- Create: `agent/artifact_runtime/xlsx.py`
- Modify: `agent/artifact_runtime/preflight.py`
- Modify: `agent/artifact_runtime/dispatch.py`
- Create: `agent/bundled_skills/xlsx-workspace/SKILL.md`
- Create: `agent/bundled_skills/xlsx-workspace/first-agent.json`
- Create: `agent/bundled_skills/xlsx-workspace/skill.requirements.json`
- Create: `agent/bundled_skills/xlsx-workspace/scripts/inspect.py`
- Create: `agent/bundled_skills/xlsx-workspace/scripts/extract.py`
- Create: `agent/bundled_skills/xlsx-workspace/scripts/create.py`
- Create: `agent/bundled_skills/xlsx-workspace/scripts/edit.py`
- Modify: `tests/artifacts/test_bundled_packages.py`
- Create: `tests/artifacts/test_xlsx.py`

- [ ] **Step 1: Write Red XLSX matrix and journey tests**

Write Reds that require the complete XLSX package directory, including every declared script, and require the 021 scanner plus this exact shared-package assertion to pass before parser tests:

```python
assert_bundled_package(
    "xlsx-workspace",
    version="1.0.0",
    family="xlsx",
    entrypoints={
        "create": ("artifact-write", "scripts/create.py", "xlsx_cells_v1"),
        "edit": ("artifact-write", "scripts/edit.py", "xlsx_cells_patch_v1"),
        "extract": ("artifact-read", "scripts/extract.py", "xlsx_extract_v1"),
        "inspect": ("artifact-read", "scripts/inspect.py", "xlsx_inspect_v1"),
    },
    requirements=expected_portable_requirements({"openpyxl": "3.1.5"}),
)
```

The helper exact-checks the nested runtime/runtime-profile shape frozen in Task 4 and all common manifest/script properties frozen in Task 5. Each script defines only `run(arguments, inputs)` with its literal family/request kind and passes the same AST absence assertions. Test uppercase A1 cells/ranges, rejection of lowercase/noncanonical/whole-row/whole-column/3D/external references, invalid sheet names and casefold duplicate names. Test null selection over all non-empty used cells, explicit selection order, empty-sheet `used_range=None`, row/column-sorted observations and the 100,000-cell cap.

Exercise blank/string/decimal-number/boolean create values and all eight number formats. Confirm a string beginning `=` remains a string. Existing formula is never evaluated and only its exact UTF-8 formula digest appears. Exercise set/clear/add/remove/rename, range overlap, rename/remove conflicts, last-sheet removal and source-structure mismatch. Active VBA/OLE/external relationships/embedded executable fixtures are inspect-only and edits refuse.

- [ ] **Step 2: Run the Red test**

Run: `.venv/bin/python -m pytest -q tests/artifacts/test_bundled_packages.py tests/artifacts/test_xlsx.py -rx`

Expected: FAIL because XLSX handler and scripts are absent.

- [ ] **Step 3: Implement canonical addressing and scalar writes**

Parse A1 with a closed regex, convert columns manually and re-emit the canonical form; do not accept openpyxl's broader address grammar. Use `load_workbook(BytesIO(raw), data_only=False, read_only=False, keep_links=False)`. Map the frozen number formats exactly:

```python
NUMBER_FORMATS = {
    NumberFormatV1.GENERAL: "General",
    NumberFormatV1.INTEGER: "0",
    NumberFormatV1.DECIMAL_2: "0.00",
    NumberFormatV1.PERCENT: "0.00%",
    NumberFormatV1.DATE_ISO: "yyyy-mm-dd",
    NumberFormatV1.DATETIME_ISO: "yyyy-mm-dd hh:mm:ss",
    NumberFormatV1.CURRENCY_USD: '$#,##0.00',
    NumberFormatV1.CURRENCY_CNY: '¥#,##0.00',
}

def write_scalar(cell, scalar: XlsxScalarV1) -> None:
    if scalar.kind == "blank":
        cell.value = None
    elif scalar.kind == "string":
        cell.value = scalar.value
        cell.data_type = "s"
    elif scalar.kind == "number":
        cell.value = Decimal(scalar.value)
        cell.data_type = "n"
    elif scalar.kind == "boolean":
        cell.value = scalar.value
        cell.data_type = "b"
```

- [ ] **Step 4: Implement selection, structure and mutation**

Preflight Office inventory/active content before `openpyxl`. Inspection never loads linked workbooks and never reads cached formula results. Value digest is canonical scalar JSON; formula digest exists only for `data_type == "f"`; unsupported number formats map to `general` for observation and make edit refuse to preserve rather than silently normalize.

Validate the entire operation plan against an immutable workbook model before mutation. Clear every exact cell in a range; rename/remove operations update the model; forbid any set/clear against a removed/renamed ambiguous sheet. Set workbook created/modified properties to `2000-01-01T00:00:00Z`, save, call `canonicalize_ooxml`, reopen with `data_only=False`, and exact-match observed structure before returning.

- [ ] **Step 5: Run the Green test**

Run: `.venv/bin/python -m pytest -q tests/artifacts/test_xlsx.py tests/artifacts/test_bundled_packages.py -rx`

Run: `.venv/bin/ruff check agent/artifact_runtime/xlsx.py agent/artifact_runtime/preflight.py agent/artifact_runtime/dispatch.py agent/bundled_skills/xlsx-workspace tests/artifacts/test_bundled_packages.py tests/artifacts/test_xlsx.py`

Expected: both exit 0; formulas remain unexecuted and deterministic create/edit digests repeat three times.

- [ ] **Step 6: Commit the checkpoint if authorized**

```bash
git add agent/artifact_runtime agent/bundled_skills/xlsx-workspace tests/artifacts/test_bundled_packages.py tests/artifacts/test_xlsx.py
git commit -m "feat(artifacts): add xlsx workspace skill"
```

---

### Task 8: Implement PPTX inspect, extract, create and exact patch

**Files:**
- Create: `agent/artifact_runtime/pptx.py`
- Modify: `agent/artifact_runtime/preflight.py`
- Modify: `agent/artifact_runtime/dispatch.py`
- Create: `agent/bundled_skills/pptx-workspace/SKILL.md`
- Create: `agent/bundled_skills/pptx-workspace/first-agent.json`
- Create: `agent/bundled_skills/pptx-workspace/skill.requirements.json`
- Create: `agent/bundled_skills/pptx-workspace/scripts/inspect.py`
- Create: `agent/bundled_skills/pptx-workspace/scripts/extract.py`
- Create: `agent/bundled_skills/pptx-workspace/scripts/create.py`
- Create: `agent/bundled_skills/pptx-workspace/scripts/edit.py`
- Modify: `tests/artifacts/test_bundled_packages.py`
- Create: `tests/artifacts/test_pptx.py`

- [ ] **Step 1: Write Red PPTX matrix and journey tests**

Write Reds that require the complete PPTX package directory, including every declared script, and require the 021 scanner plus this exact shared-package assertion to pass before parser tests:

```python
assert_bundled_package(
    "pptx-workspace",
    version="1.0.0",
    family="pptx",
    entrypoints={
        "create": ("artifact-write", "scripts/create.py", "pptx_slides_v1"),
        "edit": ("artifact-write", "scripts/edit.py", "pptx_slides_patch_v1"),
        "extract": ("artifact-read", "scripts/extract.py", "pptx_extract_v1"),
        "inspect": ("artifact-read", "scripts/inspect.py", "pptx_inspect_v1"),
    },
    requirements=expected_portable_requirements({
        "pillow": "12.3.0",
        "python-pptx": "1.0.2",
    }),
)
```

The helper exact-checks the nested runtime/runtime-profile shape frozen in Task 4 and all common manifest/script properties frozen in Task 5. Each script defines only `run(arguments, inputs)` with its literal family/request kind and passes the same AST absence assertions. Test null/all and explicit ordered slide selections; 1-based slide and 0-based shape addresses; empty title/body digests; stable document-order slide observations; title/title_body/blank layout constraints; integer point bounds; 100 body/image cap; 500 slide/10,000 shape caps. Exercise exact text replace, slide delete, exact remaining-slide permutation and image replace; expected/source mismatch, non-text/non-image shape, conflicting order/delete, duplicate address and delete-all refuse.

Test external relationships, OLE/VBA/embedded executable, unsupported custom theme/animation/transition as inspect flags. Extract never follows relationships. Edit refuses all active/unsupported preservation flags; create output has none.

- [ ] **Step 2: Run the Red test**

Run: `.venv/bin/python -m pytest -q tests/artifacts/test_bundled_packages.py tests/artifacts/test_pptx.py -rx`

Expected: FAIL because PPTX handler and scripts are absent.

- [ ] **Step 3: Implement PPTX structure and creation**

Open only `Presentation(BytesIO(raw))` after preflight. Extract text from text frames in paragraph/run order; title digest uses the title placeholder text or empty bytes; body digest uses canonical JSON of non-title text strings. Count all shapes, including groups, but do not traverse or execute embedded content.

Create a fresh default presentation and remove its initial slide. Resolve only three built-in layouts by placeholder type, set title/body with plain text, and add input images only after raster preflight confirms single-frame supported format. Convert integer points with `pptx.util.Pt`; never use a user template.

- [ ] **Step 4: Implement a prevalidated patch**

Resolve all addresses and expected strings before mutation. Delete slides by removing their relationship and exact `_sldIdLst` entry. Reorder by an exact permutation of remaining slide ids. Replace image bytes through the existing image relationship while preserving geometry:

```python
image_part, relation_id = slide.part.get_or_add_image_part(BytesIO(image_bytes))
blip = shape._element.blipFill.blip
blip.rEmbed = relation_id
```

Require the addressed shape to be a picture. Set presentation created/modified/last-printed core properties to `2000-01-01T00:00:00Z`, save, canonicalize OOXML, reopen, and exact-match the requested slide order/title/body/shape observations before returning.

- [ ] **Step 5: Run the Green test**

Run: `.venv/bin/python -m pytest -q tests/artifacts/test_pptx.py tests/artifacts/test_bundled_packages.py -rx`

Run: `.venv/bin/ruff check agent/artifact_runtime/pptx.py agent/artifact_runtime/preflight.py agent/artifact_runtime/dispatch.py agent/bundled_skills/pptx-workspace tests/artifacts/test_bundled_packages.py tests/artifacts/test_pptx.py`

Expected: both exit 0; deterministic raw and structure digests repeat three times.

- [ ] **Step 6: Commit the checkpoint if authorized**

```bash
git add agent/artifact_runtime agent/bundled_skills/pptx-workspace tests/artifacts/test_bundled_packages.py tests/artifacts/test_pptx.py
git commit -m "feat(artifacts): add pptx workspace skill"
```

---

### Task 9: Fail closed on hostile headers, active content and resource exhaustion

**Files:**
- Create: `tests/artifacts/hostile_fixtures.py`
- Create: `tests/artifacts/test_hostile_inputs.py`
- Modify: `agent/artifact_runtime/common.py`
- Modify: `agent/artifact_runtime/preflight.py`
- Modify: `agent/artifact_runtime/pdf.py`
- Modify: `agent/artifact_runtime/docx.py`
- Modify: `agent/artifact_runtime/xlsx.py`
- Modify: `agent/artifact_runtime/pptx.py`
- Modify: `agent/artifact_runtime/raster.py`
- Modify: `tests/artifacts/test_adapter_integration.py`

- [ ] **Step 1: Build deterministic hostile fixtures and Red controls**

`hostile_fixtures.py` constructs bytes in memory; it never copies real user files. Include:

- PDF: wrong header, truncated xref, cyclic/oversized object graph, encrypted, `/JavaScript`, `/EmbeddedFiles`, `/AcroForm`, signature field and 501 pages;
- Office: 10,001 ZIP parts, declared/streamed expanded size over 256 MiB, extreme compression ratio, duplicate/casefold/NFC/path-collision entries, `../`/absolute/backslash name, symlink/device mode, encrypted/data-descriptor/Zip64, malformed central directory, DTD/entity XML, wrong/multiple content types, macro/OLE/external relationship/Track Changes/embedded executable/theme/animation parts;
- raster: truncated headers, 20,001 side, 50,000,001 pixels, decompression bomb, invalid chunk length, animated WebP, multi-frame PNG/JPEG, EXIF with GPS, ICC and XMP.

Every denial has a neighboring non-vacuous control that differs only in the hostile property. Split fixtures into `HOSTILE_PREFLIGHT_FIXTURES` (header/container/path/declared-size facts provable without the parser) and `HOSTILE_PARSER_FIXTURES` (cyclic object graph, semantic active content and parser-level limits). Only the first set must be rejected before the full parser. Parser-level fixtures may enter the bounded parser but must terminate with a closed refusal and zero commit.

```python
def zip_with_declared_bomb(*, hostile: bool) -> bytes:
    payload = b"A" * (1_048_576 if hostile else 1_024)
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr("[Content_Types].xml", valid_docx_content_types())
        archive.writestr("word/document.xml", payload)
    raw = output.getvalue()
    return patch_central_directory_size(raw, 256 * 1024 * 1024 + 1) if hostile else raw

@pytest.mark.parametrize("fixture", HOSTILE_PREFLIGHT_FIXTURES)
def test_hostile_input_is_refused_before_full_parser(fixture, monkeypatch):
    monkeypatch.setattr(fixture.module, fixture.parser_name,
                        lambda *args, **kwargs: (_ for _ in ()).throw(
                            AssertionError("full parser reached")))
    with pytest.raises(TerminalRefusal, match=fixture.reason_code):
        fixture.run(fixture.hostile_bytes)
    with pytest.raises(AssertionError, match="full parser reached"):
        fixture.run(fixture.control_bytes)

@pytest.mark.parametrize("fixture", ALL_HOSTILE_FIXTURES)
def test_hostile_control_succeeds_with_real_bounded_parser(fixture):
    assert fixture.run(fixture.control_bytes).observation.raw_sha256

@pytest.mark.parametrize("fixture", HOSTILE_PARSER_FIXTURES)
def test_parser_level_hostile_input_is_terminal_and_never_commits(fixture):
    with pytest.raises(TerminalRefusal, match=fixture.reason_code):
        fixture.run(fixture.hostile_bytes)
    assert fixture.commit_count == 0
```

- [ ] **Step 2: Write Red sandbox/resource tests**

Using the real 020a structured policy with a tiny injected limit profile, run test packages that attempt a third file, unlink/rename fixed outputs, read request/input for write, write inputs, read workspace/home/private sentinels, import `subprocess`, fork/exec a descendant, open TCP/DNS, exceed CPU/AS/FSIZE/NOFILE, overrun result/artifact caps and leave a descendant. Each denial must have an allowed control touching only its declared input and fixed output inode. Assert no workspace commit and cleanup/reap facts are closed.

- [ ] **Step 3: Run the Reds**

Run: `.venv/bin/python -m pytest -q tests/artifacts/test_hostile_inputs.py tests/artifacts/test_adapter_integration.py -rx`

Expected: FAIL because at least one fixture reaches a full parser or escapes a bound until preflight/resource enforcement is complete.

- [ ] **Step 4: Complete preflight and terminal refusal mapping**

Use only bounded header/central-directory reads in preflight. Return closed reason codes:

```python
REFUSAL_CODES = frozenset({
    "artifact_header_invalid", "artifact_input_limit", "artifact_output_limit",
    "pdf_encrypted_unsupported", "pdf_active_content_edit_refused",
    "office_archive_invalid", "office_archive_limit", "office_active_content_edit_refused",
    "office_unsupported_roundtrip", "raster_decompression_limit",
    "raster_multiframe_unsupported", "raster_metadata_policy_refused",
    "artifact_structure_mismatch", "artifact_staged_digest_mismatch",
})
```

Package result contains only code and bounded safe message. Tracebacks/parser exception strings, XML text, absolute paths and session paths are discarded by the child runner. A terminal parser refusal after spawn is a known-executed error with zero commit; pre-spawn snapshot/activation failures remain known-not-executed.

- [ ] **Step 5: Run the Green hostile suite**

Run: `.venv/bin/python -m pytest -q tests/artifacts/test_hostile_inputs.py tests/artifacts/test_adapter_integration.py tests/artifacts/test_pdf.py tests/artifacts/test_docx.py tests/artifacts/test_xlsx.py tests/artifacts/test_pptx.py tests/artifacts/test_raster.py -rx`

Run: `.venv/bin/ruff check agent/artifact_runtime tests/artifacts`

Expected: both exit 0; every denial control reaches its intended parser/session action and every hostile case has zero commit.

- [ ] **Step 6: Commit the checkpoint if authorized**

```bash
git add agent/artifact_runtime tests/artifacts/hostile_fixtures.py tests/artifacts/test_hostile_inputs.py tests/artifacts/test_adapter_integration.py
git commit -m "test(artifacts): close hostile parser and resource inputs"
```

---

### Task 10: Prove the existing static registration path with E2/E2M

**Files:**
- Create: `scripts/verify_022_materialized_tree.py`
- Create: `tests/architecture/test_022_artifact_boundaries.py`
- Create: `tests/reference/test_022_workspace_artifacts.py`
- Modify: `tests/composition/test_composition.py`
- Modify: `tests/kernel/test_source_contracts.py`

- [ ] **Step 1: Write Red architecture and real Runtime journeys**

Architecture tests parse imports/AST and assert:

- one `AgentRuntime.run_turn` production loop and one `KernelToolRuntime.invoke` callable owner;
- one definition each of `PackagedSkillExecutionAdapter`, `build_packaged_skill_registrations` and the outer structured decoder;
- `agent.artifacts` imports no pypdf/ReportLab/docx/openpyxl/pptx/Pillow/subprocess/network module;
- `agent.artifact_runtime` imports no `agent.runtime.loop`, provider, ContextManager, ToolRuntime, lifecycle store or workspace path module;
- CLI/provider/headless modules import no Artifact parser;
- bundled scripts call only the product runner/dispatch and cannot register tools;
- `agent/skill/__init__.py` exports no Artifact symbol and imports neither `agent.artifacts` nor `agent.artifact_runtime`; 022 never lists or edits that file and imports concrete owners directly instead of turning the package initializer into an API aggregator.

Create real `AgentRuntime` journeys with `ScriptedProvider`, real `KernelContextManager`, real `KernelToolRuntime`, real 021 active snapshot/gate, real 020b builder/adapter and injected structured executor at E2. For each format, the scripted model calls the actual generated tool name, then `artifact_stat` after writes, then answers from the next `ContextPack`. Assert ToolDefinition → model call → approval → durable `EXECUTING` → adapter → sandbox draft → ToolResult/source receipt/mutation receipt → next ContextPack.

Negative journeys cover model guessing an unregistered/revoked entrypoint, activation snapshot drift, approval before spawn, wrong Goal revision, provider never seeing raw raster/binary and result projection truncation not satisfying evidence.

- [ ] **Step 2: Run the Reds**

Run: `.venv/bin/python -m pytest -q tests/architecture/test_022_artifact_boundaries.py tests/reference/test_022_workspace_artifacts.py tests/composition/test_composition.py tests/kernel/test_source_contracts.py -rx`

Expected: FAIL because the new first-party package activation fixtures and Artifact Runtime journey assertions are not yet implemented; the existing 021 composition call itself is not modified.

- [ ] **Step 3: Activate packages through 021 and reuse its one static composition call**

In the test fixture, import, stage and activate each exact package only through 021 `ExecuteOperatorTool` actions and approvals, restart composition, and assert that 021's already-existing call produces the exact per-entrypoint registrations. Do not add or move a `build_packaged_skill_registrations` call in 022. The architecture test freezes the only allowed composition shape:

```python
packaged_registrations = build_packaged_skill_registrations(
    active_set=active_skill_set,
    activation_gate=skill_activation_gate,
    execution_adapter=packaged_skill_execution_adapter,
    max_tool_result_chars=max_tool_result_chars,
)
registrations.extend(packaged_registrations)
```

This snippet is an assertion against the 021-owned implementation, not new 022 production code. If any required identity/qualification/runtime closure is unavailable, 021/020b excludes that package or fails startup according to their frozen contract; 022 does not create a fallback file tool. The ordinary file builder already supplies `artifact_stat`.

- [ ] **Step 4: Prove clean materialized E2M**

`scripts/verify_022_materialized_tree.py` owns these verifier-only values; they are not exported from `agent`, persisted by 021 or parsed by 020a:

```python
@dataclass(frozen=True, slots=True)
class WheelRecordV1:
    relative_path: str
    size_bytes: int
    sha256: str

@dataclass(frozen=True, slots=True)
class RequiredDistributionV1:
    name: str
    version: str

@dataclass(frozen=True, slots=True)
class WheelhouseSealV1:
    schema: str
    wheels: tuple[WheelRecordV1, ...]
    inventory_digest: str
    production_distributions: tuple[RequiredDistributionV1, ...]
    independent_reader_distributions: tuple[RequiredDistributionV1, ...]
    seal_digest: str
```

The exact canonical JSON keys are `schema`, `wheels`, `inventory_digest`, `production_distributions`, `independent_reader_distributions`, and `seal_digest`. `schema` is `first-agent-wheelhouse-seal/v1`; `wheels` is a byte-sorted non-empty list of exact `{relative_path,size_bytes,sha256}` records; `production_distributions` is the exact byte-sorted `{name,version}` list from `EXPECTED_INSTALLED_DISTRIBUTIONS`; and `independent_reader_distributions` is exactly `cffi==2.1.1`, `charset-normalizer==3.5.1`, `cryptography==50.0.1`, `pdfminer-six==20260107`, and `pycparser==3.0`. Names use PEP 503 lowercase hyphen normalization. `inventory_digest` binds the complete wheel records with domain `first-agent-wheelhouse-inventory-v1`; `seal_digest` binds the other five fields with domain `first-agent-wheelhouse-seal-v1`. The verifier bounded-parses each verified wheel's single `.dist-info/METADATA` and `.dist-info/WHEEL`, exact-matches normalized Name/Version and compatible CPython/macOS tag, and requires the wheel set to be exactly the union of both distribution sets with no duplicate `(name,version)`; a wheel shared by both sets is installed into each clean environment from the same verified staged bytes. Paths are single canonical `.whl` basenames. Admission allows at most 64 wheels, `1..64 MiB` per wheel and `512 MiB` aggregate. The three CLI path validators use `lstat` plus descriptor-relative `O_NOFOLLOW`; the seal reader rejects symlink/multi-link/non-owner/non-regular input and bounded-reads at most 256 KiB. The verifier opens the supplied wheelhouse directory once, opens every record descriptor-relative with `O_RDONLY|O_NOFOLLOW`, rejects non-regular/multi-link/owner-mismatch/extra/missing members, reads exactly `size_bytes + 1` bounded bytes once, verifies lowercase hex64, then copies those verified bytes into its private fresh staging directory. A self-consistent change must alter either an exact distribution set or verified wheel bytes; the former fails immediately and the latter must still reproduce the frozen installed closure. Delivery evidence therefore binds installed bytes rather than claiming publisher provenance for wheels.

The CLI parser requires all three paths explicitly and accepts no environment/default fallback:

```python
parser.add_argument("--wheelhouse", type=absolute_existing_directory, required=True)
parser.add_argument("--wheelhouse-seal", type=absolute_existing_regular_file, required=True)
parser.add_argument("--skill-runtime-root", type=absolute_absent_path, required=True)
parser.add_argument("--mode", choices=("e2m", "e3"), required=True)
```

The reference test invokes `main(["--mode", "e2m", "--wheelhouse", str(wheelhouse), "--wheelhouse-seal", str(seal), "--skill-runtime-root", str(runtime_root)])` with three `tmp_path` children and asserts omission, relative paths, symlinks, extra wheels, every mutated seal field, unknown/missing distribution and an already-existing runtime root fail before installation. The verifier creates `skill_runtime_root` with `venv.EnvBuilder(with_pip=False, clear=False, symlinks=False)`; the resulting installed interpreter is distinct from `sys.executable`, contains no ambient pip/setuptools distribution, and is part of the later 020a closure. The verifier's installer process then targets that interpreter with this exact argv and a closed environment; it neither resolves nor downloads:

```python
install_argv = [
    sys.executable,
    "-I",
    "-m",
    "pip",
    "--python",
    os.fspath(skill_runtime_python),
    "install",
    "--no-index",
    "--no-cache-dir",
    "--disable-pip-version-check",
    "--no-deps",
    "--only-binary=:all:",
    os.fspath(candidate_wheel),
    *(os.fspath(path) for path in staged_production_wheels),
]
```

`candidate_wheel` is the exact byte-identical result of the two tracked-candidate builds. Only after installation does the verifier call 020a `qualify_hermetic_runtime_closure` on the installed root; 020a sees and qualifies only installed interpreter/distribution/file bytes, never the wheelhouse or seal. Mode `e3` separately creates a no-pip independent-reader venv and installs only `staged_independent_reader_wheels`; its site is never added to the production Skill runtime's `sys.path` or closure.

In the reference test, build the candidate wheel twice and require identical digest. Import/stage/activate the five packages one action at a time through 021, restart composition, and run the same Runtime journeys. Assert distribution origins for `agent`, pypdf, reportlab, docx, openpyxl, pptx and PIL are inside the materialized clean root and not the source tree or user site.

Inject a source-tree sentinel module with the same name as a parser dependency; E2M must still import the materialized distribution. Remove one dependency file and require qualification/registration failure before model exposure.

- [ ] **Step 5: Run the Green E2/E2M suite**

Run: `.venv/bin/python -m pytest -q tests/architecture/test_022_artifact_boundaries.py tests/reference/test_022_workspace_artifacts.py tests/composition/test_composition.py tests/kernel/test_source_contracts.py -rx`

Run: `.venv/bin/ruff check scripts/verify_022_materialized_tree.py tests/architecture/test_022_artifact_boundaries.py tests/reference/test_022_workspace_artifacts.py tests/composition/test_composition.py tests/kernel/test_source_contracts.py`

Expected: both exit 0; E2M reports only materialized origins and no raw binary in provider calls/checkpoints/events.

- [ ] **Step 6: Commit the checkpoint if authorized**

```bash
git add scripts/verify_022_materialized_tree.py tests/architecture/test_022_artifact_boundaries.py tests/reference/test_022_workspace_artifacts.py tests/composition/test_composition.py tests/kernel/test_source_contracts.py
git commit -m "test(artifacts): prove governed artifact skill composition"
```

---

### Task 11: Promote with a sealed materialized real E3 and independent readers

**Files:**
- Create: `tests/reference/test_022_e3_harness.py`
- Create: `tests/reference/test_022_independent_readers.py`
- Create: `scripts/run_022_e3.py`
- Modify: `scripts/verify_022_materialized_tree.py`
- Create: `docs/acceptance/022_WORKSPACE_ARTIFACT_SKILLS_E3.md`
- Generate: `docs/acceptance/022_WORKSPACE_ARTIFACT_SKILLS_RECEIPT.json`

**Independent reader boundary:** PDF uses `pdfminer.six` and never imports pypdf/ReportLab. DOCX/XLSX/PPTX readers use only stdlib `zipfile` plus hardened `ElementTree` and never import python-docx/openpyxl/python-pptx/lxml. Raster uses `/usr/bin/sips` plus host raw SHA-256 and never imports Pillow.

- [ ] **Step 1: Freeze E3 claim and receipt Reds**

Define exact journeys:

```python
JOURNEY_NAMES = (
    "pdf_selected_extract_create_edit",
    "docx_inspect_create_edit",
    "xlsx_inspect_create_edit",
    "pptx_inspect_create_edit",
    "raster_png_inspect_create_transform",
    "raster_jpeg_inspect_create_transform",
    "raster_webp_inspect_create_transform",
    "lifecycle_restart_update_revoke",
    "workspace_home_private_network_process_denials",
    "resource_timeout_cleanup_denials",
    "artifact_receipt_readback_join",
)
ATTEMPT_IDS = ("attempt-1", "attempt-2", "attempt-3")
```

Receipt exact top-level keys are `schema`, `observed_at`, `stage`, `delivery_identity`, `runtime_closure_identity`, `active_snapshot_identity`, `sandbox_backend_identity`, `attempts` for pass/fail; blocked replaces identities with exact `blocked` and has empty attempts. Freeze one canonical sorted entrypoint map whose values have exact keys `tool_name`, `tool_identity`, `package_digest`, `storage_identity_digest`, `qualification_digest`, and `entrypoint_digest`. `tool_identity` is the exact `ToolSpec.identity_digest` name used by `ArtifactMutationReceiptV1`; no receipt or verifier accepts `tool_spec_identity`. Compute:

```python
delivery_identity = canonical_digest(
    {
        "wheel_digest": wheel_digest,
        "runtime_closure_identity": runtime_closure_identity,
        "active_snapshot_identity": active_snapshot_identity,
        "entrypoints": tuple(sorted(entrypoint_bindings, key=lambda item: item["tool_name"])),
    },
    domain="artifact-delivery-v1",
)
```

Each attempt contains exact id, unique workspace/temp/sentinel digests, wheel digest, the full canonical entrypoint map, checkpointed mutation-receipt digests, attempt-record digest and an exact boolean map of every journey. For each write, the independent-reader record exact-joins the mutation receipt's `tool_identity`, `package_digest`, `qualification_digest`, `entrypoint_digest`, target path and pre/post raw digests; the same `tool_identity` selects one entrypoint-map row whose package/qualification/entrypoint fields must agree and supplies the matching `storage_identity_digest`; fresh `artifact_stat` supplies the committed snapshot digest. Package identity alone is insufficient.

Write mutation tests for missing/extra keys, every altered entrypoint-binding field, recomputed delivery digest with a wrong ToolSpec identity, wrong stage, fewer/more/repeated attempts, non-boolean journey, all-true fail stage, mutable receipt included in materialized candidate, reader importing a production dependency, repeated root/sentinel, leaked absolute/home/private string and a fake runner that returns success without observing the actual committed bytes.

- [ ] **Step 2: Implement independent readers**

PDF reader extracts page text/order with `pdfminer.high_level.extract_pages`. Office readers open bounded ZIP members and parse exact namespaces with `ElementTree`; reject DTD/entity text before parse. DOCX reads `word/document.xml` paragraph/table order; XLSX reads workbook relationships, sheets, shared strings and cell/formula XML without evaluating; PPTX reads presentation relationship order and slide text/shape XML. Raster reader runs exact argv:

```python
SIPS_FIELDS = ("format", "pixelWidth", "pixelHeight", "space")

def sips_stat(path: Path) -> dict[str, str]:
    completed = subprocess.run(
        ["/usr/bin/sips", "-g", "format", "-g", "pixelWidth", "-g", "pixelHeight",
         "-g", "space", str(path)],
        check=False, capture_output=True, text=True, timeout=10,
        env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
    )
    if completed.returncode != 0:
        raise IndependentReaderError("sips could not inspect raster output")
    return parse_closed_sips_output(completed.stdout, expected_fields=SIPS_FIELDS)
```

Independent checks bind marker text, page/slide/order, DOCX blocks/cells, XLSX values/formula text, PPTX image/text replacement, raster format/dimensions and host raw digest. Production package structure digest is recorded for comparison but is not reused as the independent oracle.

- [ ] **Step 3: Run the Red harness tests**

Run: `.venv/bin/python -m pytest -q tests/reference/test_022_e3_harness.py tests/reference/test_022_independent_readers.py -rx`

Expected: FAIL because runner/verifier and sealed acceptance contract are absent.

- [ ] **Step 4: Implement the detached runner and materialized verifier**

`verify_022_materialized_tree.py` derives only tracked files from the frozen parent seal plus 022 overlay, explicitly rejects `tui/`, `.env`, receipts, execution logs and source caches, builds wheel twice, installs clean production and independent-reader sites separately, materializes/activates packages through the real 021 lifecycle, verifies exact distribution origins, then calls the detached runner.

Task 11 extends the Task 10 parser with mode-`e3`-only required `--attempts` (`int`, exact value `3`) and `--receipt` (workspace-relative path under `docs/acceptance/`); mode `e2m` rejects both fields. It reuses the already-tested wheelhouse/seal/runtime-root admission and does not add a second materializer.

`run_022_e3.py` creates a fresh workspace/temp/home/private sentinel per attempt, uses real macOS Seatbelt structured sandbox, real Runtime/approval/checkpoint, actual bundled package object and exact target commits. It writes an immutable per-attempt record once; a failed attempt cannot be overwritten. Every denial journey runs its allowed control first. Every positive journey calls an independent reader on fresh committed bytes, not a package projection. It returns `E3_PASS` only when all 11 booleans are true for all three attempts.

Lifecycle journey is exact: import → stage → activate → restart → invoke → update → restart → old identity rejected → revoke → restart → tool absent. It calls only 021 operator actions and the existing registration builder; it never writes the active store directly.

- [ ] **Step 5: Run focused harness Green**

Run: `.venv/bin/python -m pytest -q tests/reference/test_022_e3_harness.py tests/reference/test_022_independent_readers.py -rx`

Run: `.venv/bin/ruff check scripts/run_022_e3.py scripts/verify_022_materialized_tree.py tests/reference/test_022_e3_harness.py tests/reference/test_022_independent_readers.py`

Expected: both exit 0; fake/blind controls are rejected.

- [ ] **Step 6: Run the final source gates once**

```bash
git diff --check
.venv/bin/ruff check .
.venv/bin/python -m pytest -q -rx
```

Expected: all three commands exit 0 with complete, non-truncated output.

- [ ] **Step 7: Run the clean materialized E2M and real E3 once**

Run: `.venv/bin/python scripts/verify_022_materialized_tree.py --mode e3 --wheelhouse /var/tmp/first-agent-022-input/wheelhouse --wheelhouse-seal /var/tmp/first-agent-022-input/wheelhouse-seal.json --skill-runtime-root /var/tmp/first-agent-022-output/skill-runtime --attempts 3 --receipt docs/acceptance/022_WORKSPACE_ARTIFACT_SKILLS_RECEIPT.json`

Expected: exit 0; receipt stage `E3_PASS`; three unique attempts; all journey booleans true; current sealed wheel/runtime/package/qualification/entrypoint/active-snapshot/sandbox identities exact-match. Backend or `/usr/bin/sips` absence produces only the frozen blocked receipt and does not count as completion.

- [ ] **Step 8: Independently validate the generated receipt and candidate immutability**

Run: `.venv/bin/python -m pytest -q tests/reference/test_022_e3_harness.py tests/reference/test_022_independent_readers.py -rx`

Run: `git diff --check`

Expected: both exit 0; candidate tree digest is unchanged by verification; receipt contains no absolute path, raw binary, projection content, credential/private sentinel or transient session name.

- [ ] **Step 9: Commit the checkpoint if authorized**

```bash
git add scripts/run_022_e3.py scripts/verify_022_materialized_tree.py tests/reference/test_022_e3_harness.py tests/reference/test_022_independent_readers.py docs/acceptance/022_WORKSPACE_ARTIFACT_SKILLS_E3.md docs/acceptance/022_WORKSPACE_ARTIFACT_SKILLS_RECEIPT.json
git commit -m "test(artifacts): promote workspace artifacts with real e3"
```

## Rollout Sequence and Tradeoffs

1. Land Tasks 1–3 first as a dark host seam: contracts, binary read-back and evidence exist, but no Artifact package is registered. This validates the hidden load-bearing seam without exposing an incomplete format.
2. Land Task 4 package identities/dependencies, then Task 5 PDF+raster together. Two structurally different consumers are required before treating the seam as general; one document parser alone could hide PDF-specific coupling.
3. Add DOCX, XLSX and PPTX one package at a time in Tasks 6–8. Each package is promotable/revocable independently through 021, while the host Artifact contract stays closed.
4. Close hostile/resource behavior before composition exposure. A format with positive tests but incomplete active-content preservation remains inactive.
5. Promote only after source E2, clean E2M and real three-attempt E3 pass for the exact materialized candidate. A later dependency/package/runtime digest requires a new qualification and E3 receipt.

The deliberate cost is five explicit field unions and five package implementations instead of one generic conversion API. That duplication protects approval/evidence semantics: the model cannot smuggle an unsupported operation through a free-form recipe. The Artifact semantic codec is shared, but parser behavior stays package-owned. Production read-back proves exact bytes and package observation, not independent semantic truth; the independent-reader burden is paid at promotion time rather than falsely on every invocation. Raster uses Pillow in production and `sips` in macOS E3, so portable source tests cannot alone promote raster semantics. OOXML deterministic ZIP rewriting trades preservation breadth for reproducibility; unsupported active or round-trip-sensitive features are refused instead of silently stripped.

## Definition of Done

- All 19 request kinds, five structures, every operation variant, null/empty rule, flag allowlist, number format, selector/address conflict and frozen cap have positive plus mutation tests.
- PDF/DOCX/XLSX/PPTX and PNG/JPEG/WebP each pass inspect/read and their frozen write operation through the real Runtime path.
- Exactly one `PackagedSkillExecutionAdapter`, one `build_packaged_skill_registrations`, one outer structured decoder, one `NativeSandboxExecutor`, one `ToolRuntime` and one `AgentRuntime.run_turn` remain.
- Binary workspace input/output never reaches model context, checkpoint, event, receipt or logs; only bounded projection/digests/relative target survive.
- Every write has one exact approval, one exact target commit, fresh `artifact_stat`, typed mutation receipt and `ARTIFACT_READBACK` exact join. Unknown post-commit outcome remains recovery-only.
- Hostile/active/resource denials have non-vacuous controls and zero commit.
- Exact dependencies and bundled package assets are present in a clean materialized wheel; production imports never fall back to source/user/system site.
- Source gates, E2, E2M and real macOS Seatbelt E3 all pass for the same identities; independent readers verify every format three consecutive times.
