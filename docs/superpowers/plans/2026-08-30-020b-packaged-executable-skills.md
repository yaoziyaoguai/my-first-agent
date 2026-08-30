# 020b Packaged Executable Skills Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add statically composed, governed executable Agent Skills whose declared entrypoints run through the one Runtime and the 020a structured native sandbox, with closed manifests, exact package identities, typed bounded results, Runtime-minted receipts, and fail-closed revocation/drift behavior.

**Architecture:** 020b owns the portable executable manifest/requirements contracts, the one packaged registration builder, the one packaged execution adapter, and the closed semantic result seam. It consumes 020a origin/exposure and structured sandbox contracts plus 021's immutable active-set/gate contracts; it owns neither lifecycle loading/composition nor a process executor. 021 calls the builder once while constructing `SkillLifecycleResources.registrations`; every packaged callable then uses the 021 gate and delegates exactly once to the injected 020a `NativeSandboxExecutor`.

**Tech Stack:** Python 3.11, frozen dataclasses/StrEnum/Protocol, strict JSON and YAML parsing, existing `AgentRuntime`/`KernelToolRuntime`, 020a native Seatbelt structured session and hermetic runner, pytest, Ruff.

**Spec:** `docs/superpowers/specs/2026-08-30-governed-executable-skills-and-artifacts-design.md` §§3–5, §7, §12, §13.2, §14.

## Global Constraints

- Begin only after `docs/superpowers/plans/2026-08-30-020a-operator-runtime-structured-sandbox.md` is green. Import its public `ToolExposure`, `InvocationOrigin`, `ExecuteOperatorTool`, origin-bound `ToolPrepareContext`/`ExecutionIntent`, `StructuredResultKind`, `StructuredSandboxInputV1`, `StructuredSandboxIoPlanV1`, `StructuredSandboxProcessDraftV1`, `PackagedSkillSandboxPolicyV1`, `build_packaged_skill_policy`, `prepare_hermetic_skill_process`, `HermeticRuntimeClosureV1`, and the optional `io_plan` path on the single `NativeSandboxExecutor.execute` method. Do not copy, rename, or wrap those contracts.
- The only permitted dependency order is `020a complete → 021 Task 1 lifecycle/active-set contracts → 020b Tasks 1–6 executable contracts, adapter, and builder → 021 Tasks 2–11 lifecycle implementation/promotion → 020b Tasks 7–8 integration/promotion`. Task 7 consumes the completed 021 `SkillLifecycleResources.registrations`; it does not add a composition seam.
- Begin Task 3 only after 021 Task 1 exports `ActiveSkillSetV1`, `MaterializedActivePackageV1`, `StoredPackageV1`, `QualificationRecordV1`, `SkillActivationGate`, `SkillExecutionGuardV1`, and `ActivationGateDecisionV1`. 021 remains the sole owner of those contracts, lifecycle persistence, package storage, qualification, activation/revocation, gate implementations, active loading, and composition. 020b imports them and never recreates a lifecycle identity, protocol, fake production gate, loader, planner, or store.
- Every package/storage/qualification/active/tool-set digest on the wire is exactly bare lowercase hex64 (`[0-9a-f]{64}`), matching 020a. There is no `sha256:` prefix, prefix stripping, dual parser, compatibility representation, or prefix-preserving encoder. Before Task 3, 021 Task 1 and every 021 fixture/codec assertion must already use this representation; if not, 021 is a blocked prerequisite and must be synchronized outside this plan's commits.
- 020b owns `ExecutableSkillManifestV1`, `ExecutableScriptDescriptorV1`, `PortableRequirementsV1`, both strict codecs and digest helpers, `PackagedSkillBindingV1`, `PackagedSkillExecutionAdapter`, `StructuredSandboxToolDraftV1`, `decode_packaged_skill_result`, and `build_packaged_skill_registrations(...)`. 021 owns `SkillActivationGate` and both fake/concrete lifecycle implementations; 020b tests may use a test-local structural fake only.
- 022 consumes and edits the single 020b semantic owners to add the closed Artifact result branches. It must not add a second adapter, registration builder, outer structured decoder, executor, dynamic decoder registry, or package identity. Keep the 020b `skill-result-v1` branch independent of Artifact contracts so a non-Artifact executable Skill is proven before 022.
- `AgentRuntime.run_turn` remains the only production model/tool loop and state-change entry. `ContextManager` remains the only model-context selector. `KernelToolRuntime` remains the only callable invoker, approval/effect-order owner, sandbox-receipt minter, and result-checkpoint source. `NativeSandboxExecutor` remains the only process/confinement owner.
- `allowed-tools` follows the current official Agent Skills specification: an experimental, space-separated string. Parse and bound it for display/provenance only. It never affects `ToolSpec`, registration, `approval_policy`, policy decisions, exposure, egress, sandbox policy, or execution authority. The authoritative source checked on 2026-08-30 is `https://github.com/agentskills/agentskills/blob/main/docs/specification.mdx`.
- `first-agent.json` and `skill.requirements.json` are host extensions with one closed decoder each. Reject duplicate/unknown keys, unknown enums, unsafe paths, forbidden execution vocabulary, malformed/non-finite JSON, invalid bounds, and non-regular declared scripts. Canonical bytes are used for identity; publisher whitespace is not authority. Never accept command/shell/env/stdin/argv templates, hooks, URLs, postinstall, network-on, or danger-full-access.
- Standard progressive disclosure remains: startup/model definitions expose bounded metadata; activation reveals `SKILL.md`; resource reads reveal only `references/` and `assets/`. `scripts/` may be executed only when exactly declared in the decoded manifest and may never be returned by `skill__read_resource`.
- No arbitrary `run_skill`, shell, Python-code, command, executable-path, argv, environment, working-directory, URL, hook, or dynamic import tool is introduced. Entrypoint scripts and fixed runner command come only from qualified package identity.
- The manifest decoder resolves each publisher `script` path to one canonical host descriptor `ExecutableScriptDescriptorV1(relative_path,size_bytes,sha256)`. ToolSpec/binding pin its derived digest. Only `_prepare_components` maps that host value to the frozen 020a runner wire `{path,size,sha256}`; no `to_wire`, alternate encoder, union, or direct `to_payload()` serialization is allowed. The runner performs one descriptor-relative `O_NOFOLLOW` read, verifies size/hash, and compiles/executes only those verified bytes; no bare path request, second path lookup, `runpy.run_path`, or compatibility form remains.
- A trusted/active package is not preapproved. Every sandbox spawn is `HIGH`, `ALWAYS`, `ISOLATED_SANDBOX`, `NONE` egress. A generic/read entrypoint is `EXTERNAL`; Artifact writes are `WRITE` when 022 extends the closed operation enum.
- Exit code 0, child stdout/stderr, model prose, an arbitrary JSON object, or a manifest claim is never completion evidence. A successful packaged result requires a valid 020a structured draft, valid sandbox receipt, exact semantic result decoding, and a Runtime-minted `SkillResultReceiptV1`. Raw request/input/result bytes, absolute workspace/package/session paths, package content, and child diagnostics never enter checkpoint, event, model context, or receipt.
- The static active snapshot is read at startup. No configured-baseline merge, directory watch, hot add/remove, service locator, global registry, mutable decoder map, compatibility fallback, ambient Python/site package, system interpreter fallback, or second loop is allowed. Any active-head change requires restart.
- `agent.skill.__init__` remains leaf-only and never eagerly imports `package_composition`, `tools`, or `execution`. Runtime imports `agent.skill.executable_contracts`, `agent.skill.executable_results`, and `agent.skill.execution` by exact leaf module only. Stable composition entrypoints are imported from `agent.skill.package_composition` directly; a package-root re-export, lazy service locator, or import-order fallback is forbidden.
- All workspace/package reads remain no-follow, regular-file-only, identity/digest-bound and bounded. 020b's generic proof uses JSON/text arguments and no workspace binary input; 022 adds the one binary snapshot/staging/commit owner. This prevents 020b from inventing a competing binary snapshot seam.
- Preserve unrelated work. Do not read or touch `tui/`, `.env`, secrets, credentials, real logs, private package stores, or untracked content. Each task changes only the files it lists.
- Every task follows Red → observe the stated failure → minimum Green → focused pass → checkpoint commit. Do not proceed when a command times out, truncates output, omits an exit status, or leaves failures. Run the full repository gate only in the final task.

## File Responsibilities

- `agent/skill/catalog.py`: official `allowed-tools` display parser plus existing no-follow instruction/resource catalog; it never grants authority.
- `agent/skill/executable_contracts.py`: closed portable `first-agent.json`, inventory-resolved executable-script descriptor, `skill.requirements.json`, packaged binding, result expectation, and receipt contracts. It contains no I/O, process, lifecycle type, store, or registry.
- `agent/skill/executable_codec.py`: the only strict manifest/requirements JSON decoder and canonical encoder.
- `agent/skill/executable_results.py`: the only closed semantic result decoder and `skill-result-v1` text/JSON contracts. 022 adds explicit enum/`match` branches here, never a registry.
- `agent/skill/execution.py`: the sole `PackagedSkillExecutionAdapter`, `StructuredSandboxToolDraftV1`, and packaged callable/gate coordination. It imports 021's `SkillActivationGate`; it receives, but never constructs, the one 020a executor.
- `agent/skill/tools.py`: the sole `build_packaged_skill_registrations(...)` owner and shared progressive-disclosure helpers.
- `agent/runtime/tools.py`: generic Runtime validation of the one packaged structured draft and Runtime minting of sandbox/skill receipts. It does not parse manifests, resolve packages, or spawn processes.
- `agent/skill/package_composition.py` (021-owned, consumed only): owns the active loader, both gate implementations, the call to `build_packaged_skill_registrations(...)`, and the only static composition into `SkillLifecycleResources.registrations`.
- `agent/skill/__init__.py` (021-owned, constrained here): contains no eager import of composition/tools/execution; callers use exact leaf imports so Runtime↔Skill initialization cannot cycle.
- `tests/skill/package_fixtures.py`: deterministic `ActiveSkillSetV1`, test-local structural gate, package, runtime closure, and packaged directory fixtures; no production fake path.
- `tests/fixtures/skills/echo-json/`: one real non-Artifact executable Skill used by E2/E2M.
- `tests/skill/test_executable_*.py`: contract, codec, registration, adapter, drift, receipt, E2, and E2M coverage.
- `tests/architecture/test_020b_packaged_skill_boundaries.py`: absence/ownership assertions for loop, executor, dynamic registry, hot reload, scripts-as-resource, and `allowed-tools` authority.
- `docs/acceptance/020B_PACKAGED_EXECUTABLE_SKILLS_E2.md`: exact materialized evidence commands and expected identities.
- `docs/implementation/020B_EXECUTION_LOG.md`: observed Red/Green evidence, environment qualification, deviations, and promotion result.
- `docs/architecture/capabilities/SKILL_DESIGN.md`, `docs/architecture/CURRENT_CAPABILITY_STATUS.md`, `README.md`: capability truth updated only after E2/E2M evidence exists.

## Unique Owner, Field, and Import Table

| Contract/seam | Exact authoritative fields or signature | Sole owner | Allowed import direction |
| --- | --- | --- | --- |
| `ExecutableSkillManifestV1` | `schema`, `package_name`, `package_version`, byte-sorted `entrypoints`, `manifest_digest` | 020b `agent.skill.executable_contracts` + codec in `agent.skill.executable_codec` | 021 `package_transport → executable_contracts/executable_codec`; never reverse |
| `ExecutableScriptDescriptorV1` | `relative_path`, `size_bytes`, `sha256`, derived `descriptor_digest` | 020b `agent.skill.executable_contracts`; constructed by 021 transport from canonical SCRIPT inventory | manifest/entrypoint/binding carry this host identity; only the adapter request builder maps it to 020a wire fields |
| `PortableRequirementsV1` | `schema`, `runtime`, `abi`, byte-sorted `dependencies`, `runtime_profile`, `requirements_digest` | 020b `agent.skill.executable_contracts` + codec in `agent.skill.executable_codec` | 021 consumes directly; no lifecycle duplicate/re-export/wrapper |
| `StoredPackageV1` / `QualificationRecordV1` | stored: `package`, `storage_identity_digest`, `object_root_descriptor_digest`, `inventory`; qualification: `package_digest`, `storage_identity_digest`, `platform`, `architecture`, `hermetic_runtime_closure_digest`, `sandbox_backend_identity`, `packaged_skill_policy_digest`, `resource_limiter_identity`, `qualified_at`, derived `qualification_digest` | 021 `agent.skill.package_contracts` | 020b may read identities from `MaterializedActivePackageV1`; it never constructs, encodes, qualifies, or re-exports them |
| `ActiveSkillSetV1` | `snapshot_digest`, `instruction_catalog`, byte-sorted `packages`, derived `active_set_digest` | 021 `agent.skill.package_contracts` | 020b `tools/execution → package_contracts`; leaf lifecycle contracts import no 020b module |
| `MaterializedActivePackageV1` | `active`, `stored`, `qualification`, `object_root`, `descriptor`, `manifest`, `requirements`, `runtime_closure` | 021 `agent.skill.package_contracts` and loader in `agent.skill.package_composition` | 020b consumes the complete value; it never reconstructs it from digests |
| `SkillActivationGate` | `acquire_execution_guard(*, expected_snapshot_digest: str, package_digest: str, storage_identity_digest: str, qualification_digest: str) -> SkillExecutionGuardV1 | ActivationGateDecisionV1` | 021 `agent.skill.package_contracts`; concrete in `agent.skill.package_composition` | 020b imports the protocol and calls it; no 020b protocol/concrete |
| `PackagedSkillBindingV1` | `active_snapshot_digest`, `package_digest`, `storage_identity_digest`, `manifest_digest`, `requirements_digest`, `qualification_digest`, `entrypoint_id`, `entrypoint_digest`, `script_descriptor_digest`, `operation`, `format`, `result_kind`, `result_max_chars`, `runtime_profile`, `network`, `arguments_digest`, `request_digest`, `input_descriptors_digest`, `resource_limits_digest`, `structured_invocation_digest`, `command_fingerprint`, `policy_instance_digest`, `sandbox_mode`, `sandbox_network`, `binding_digest` | 020b `agent.skill.executable_contracts` | Runtime stores its exact JSON projection as `ExecutionIntent.safety_binding` |
| `BindingPreparation` | `dict[str, JSONValue] | KnownNotExecuted` | generic seam in existing `agent.runtime.tools` | both ordinary and packaged binding preparers return it; Skill code does not import `agent.runtime.tools` |
| `PackagedSkillExecutionAdapter` | `prepare_binding(...) -> BindingPreparation`; `execute(intent, binding) -> StructuredSandboxToolDraftV1 | KnownNotExecuted` | 020b `agent.skill.execution` | consumes 020a executor and 021 materialized values; neither dependency imports adapter |
| exact runner request | `protocol`, `package_digest`, `entrypoint_id`, `entrypoint_script={path,size,sha256}`, `arguments`, `inputs`, `expected_result_kind`, `resource_limits_digest` | 020a runner parses/executes; 020b `_prepare_components` alone constructs | explicit mapping is `path=relative_path`, `size=size_bytes`, `sha256=sha256`; the complete wire is covered by request/structured-invocation digests |
| `build_packaged_skill_registrations(...)` | `(active_set, activation_gate, execution_adapter, *, max_tool_result_chars) -> tuple[RegisteredTool, ...]` | 020b `agent.skill.tools` | called exactly once by 021 `build_skill_lifecycle_resources` |
| packaged activation/resource binding | activation ToolSpec pins snapshot/active-set/package/storage/qualification/descriptor/catalog; shared resource ToolSpec pins snapshot/active-set/catalog and prepare binds the selected package | private 020b records/callables in `agent.skill.tools` | consumes only the 021 gate; prepare short SH, invoke fresh SH through bounded catalog read |
| active loading and static composition | `build_skill_lifecycle_resources(...) -> SkillLifecycleResources`; registrations are `SkillLifecycleResources.registrations` | 021 `agent.skill.package_composition` | 020b Task 7 consumes resources; it does not edit `agent/composition.py` |

Before 021 calls either executable decoder, `package_transport` must derive `declared_scripts = tuple(ExecutableScriptDescriptorV1(relative_path=entry.relative_path, size_bytes=entry.size_bytes, sha256=entry.sha256) for entry in canonical_inventory if entry.role is PackageRole.SCRIPT)`, require descriptor paths to be byte-sorted and duplicate-free, and call `decode_executable_manifest(raw, declared_scripts=declared_scripts)`. It then exact-compares manifest `package_name/version` to the bounded decoded `SKILL.md` name and operator-declared version. 020b never receives an unvalidated filesystem listing and never scans the package. Passing `tuple[str, ...]`, resolving a descriptor from the mutable package directory, or accepting both forms is a prerequisite failure.

---

### Task 1: Correct `allowed-tools` compatibility without granting authority

**Files:**
- Modify: `agent/skill/catalog.py`
- Modify: `tests/skill/test_catalog.py`
- Modify: `tests/skill/test_tools.py`

**Interfaces:**
- `SkillDescriptor.allowed_tools: tuple[str, ...]`
- `_extract_allowed_tools(value: object) -> tuple[str, ...]`
- Fixed limits: 1,024 UTF-8 bytes total, 32 tokens, 128 UTF-8 bytes per token; ASCII space is the only separator.

- [ ] **Step 1: Write the official-string and no-authority Reds**

Add these exact cases to `tests/skill/test_catalog.py` and `tests/skill/test_tools.py`:

```python
def test_allowed_tools_uses_official_space_separated_string(tmp_path: Path) -> None:
    root = write_skill(
        tmp_path,
        frontmatter="allowed-tools: Bash(git:*) Bash(jq:*) Read",
    )
    descriptor = build_skill_catalog([root]).descriptors[0]
    assert descriptor.allowed_tools == ("Bash(git:*)", "Bash(jq:*)", "Read")


@pytest.mark.parametrize(
    "yaml_value",
    (
        "allowed-tools: [Read, Write]",
        "allowed-tools: ' Read'",
        "allowed-tools: 'Read  Write'",
        "allowed-tools: \"Read\\tWrite\"",
        "allowed-tools: ''",
    ),
)
def test_allowed_tools_rejects_old_list_and_ambiguous_separators(
    tmp_path: Path, yaml_value: str
) -> None:
    root = write_skill(tmp_path, frontmatter=yaml_value)
    with pytest.raises(SkillCatalogError, match="allowed-tools"):
        build_skill_catalog([root])


def test_allowed_tools_never_changes_registration_authority(tmp_path: Path) -> None:
    root = write_skill(tmp_path, frontmatter="allowed-tools: Write Bash(rm:*)")
    catalog = build_skill_catalog([root])
    registration = build_skill_tool_registrations(
        catalog, max_tool_result_chars=4_000
    )[0]
    assert registration.spec.approval_policy is ApprovalPolicy.NEVER
    assert registration.spec.execution_authority is ExecutionAuthorityClass.IN_PROCESS
    assert "allowed_tools" not in registration.spec.safety_policy
    assert "Write" not in registration.spec.description
```

- [ ] **Step 2: Run the Reds and confirm failure**

Run:

```bash
.venv/bin/python -m pytest -q tests/skill/test_catalog.py tests/skill/test_tools.py -rx
```

Expected: the string case fails with `allowed-tools must be a list`, and the list-rejection case fails because the old list is accepted.

- [ ] **Step 3: Implement the minimum bounded display parser**

Replace the current list parser in `agent/skill/catalog.py` and persist its result on the frozen descriptor:

```python
MAX_ALLOWED_TOOLS_BYTES = 1_024
MAX_ALLOWED_TOOL_TOKENS = 32
MAX_ALLOWED_TOOL_TOKEN_BYTES = 128


def _extract_allowed_tools(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, str):
        raise SkillCatalogError("allowed-tools must be a space-separated string")
    if not value or value.strip(" ") != value:
        raise SkillCatalogError("allowed-tools must not be empty or padded")
    if len(value.encode("utf-8")) > MAX_ALLOWED_TOOLS_BYTES:
        raise SkillCatalogError("allowed-tools exceeds the byte limit")
    if any(character.isspace() and character != " " for character in value):
        raise SkillCatalogError("allowed-tools must use ASCII spaces")
    tokens = tuple(value.split(" "))
    if "" in tokens or len(tokens) > MAX_ALLOWED_TOOL_TOKENS:
        raise SkillCatalogError("allowed-tools has invalid token separation or count")
    if any(
        len(token.encode("utf-8")) > MAX_ALLOWED_TOOL_TOKEN_BYTES
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in token)
        for token in tokens
    ):
        raise SkillCatalogError("allowed-tools contains an invalid token")
    return tokens
```

Add `allowed_tools: tuple[str, ...] = ()` to `SkillDescriptor`; include the tuple in descriptor/catalog provenance digests, but keep it out of ToolSpec descriptions and safety policy. In `_build_descriptor`, assign `allowed_tools=_extract_allowed_tools(data.get("allowed-tools"))`.

- [ ] **Step 4: Verify Green and checkpoint commit**

Run:

```bash
.venv/bin/python -m pytest -q tests/skill/test_catalog.py tests/skill/test_tools.py tests/skill/test_integration.py -rx
.venv/bin/ruff check agent/skill/catalog.py tests/skill/test_catalog.py tests/skill/test_tools.py
git diff --check
git add agent/skill/catalog.py tests/skill/test_catalog.py tests/skill/test_tools.py
git commit -m "fix(skill): parse official allowed-tools string"
```

Expected: all commands exit 0; the descriptor preserves bounded display metadata while registration authority is unchanged.

---

### Task 2: Add closed executable manifest and portable requirements contracts

**Files:**
- Create: `agent/skill/executable_contracts.py`
- Create: `agent/skill/executable_codec.py`
- Create: `tests/skill/test_executable_contracts.py`
- Create: `tests/skill/test_executable_codec.py`
- Create: `tests/skill/package_fixtures.py`

**Interfaces:**
- `decode_executable_manifest(raw: bytes, *, declared_scripts: tuple[ExecutableScriptDescriptorV1, ...]) -> ExecutableSkillManifestV1`
- `decode_portable_requirements(raw: bytes) -> PortableRequirementsV1`
- `encode_executable_manifest(value) -> bytes`
- `encode_portable_requirements(value) -> bytes`
- `executable_manifest_digest(manifest: ExecutableSkillManifestV1) -> str`
- `portable_requirements_digest(requirements: PortableRequirementsV1 | None) -> str`
- Closed enums: `SkillRuntimeV1`, `SkillOperationV1`, `SkillFormatV1`, `SkillParameterKindV1`, `SkillResultKindV1`, `SkillRuntimeProfileV1`, `SkillNetworkV1`.

- [ ] **Step 1: Write schema/path/forbidden-field Reds**

Create tests that construct raw bytes directly so duplicate-key rejection is proven before a Python dict can erase duplicates:

```python
def declared_echo_script(content: bytes = b"def run(arguments, inputs):\n    return {}\n") -> ExecutableScriptDescriptorV1:
    return ExecutableScriptDescriptorV1(
        relative_path="scripts/echo.py",
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )


def test_manifest_accepts_one_closed_non_artifact_entrypoint() -> None:
    manifest = decode_executable_manifest(
        valid_manifest_bytes(), declared_scripts=(declared_echo_script(),)
    )
    assert manifest.schema == "first-agent-executable-skill/v1"
    assert manifest.entrypoints[0].script == declared_echo_script()
    assert manifest.entrypoints[0].result.kind is SkillResultKindV1.SKILL_RESULT
    assert manifest.entrypoints[0].network is SkillNetworkV1.OFF


@pytest.mark.parametrize(
    "raw",
    (
        b'{"schema":"first-agent-executable-skill/v1","schema":"future"}',
        manifest_with_top_key("command", "python -c pass"),
        manifest_with_entrypoint_key("shell", True),
        manifest_with_entrypoint_key("env", {"TOKEN": "x"}),
        manifest_with_entrypoint_key("stdin", "inherit"),
        manifest_with_entrypoint_key("argv", ["--user-value"]),
        manifest_with_entrypoint_key("hook", "before"),
        manifest_with_entrypoint_key("url", "https://example.invalid/x"),
        manifest_with_entrypoint_key("postinstall", "scripts/install.py"),
        manifest_with_entrypoint_key("network", "on"),
        manifest_with_entrypoint_key("script", "../escape.py"),
        manifest_with_entrypoint_key("script", "/tmp/escape.py"),
        manifest_with_entrypoint_key("script", "scripts\\escape.py"),
    ),
)
def test_manifest_rejects_open_execution_vocabulary(raw: bytes) -> None:
    with pytest.raises(ExecutableSkillCodecError):
        decode_executable_manifest(raw, declared_scripts=(declared_echo_script(),))


def test_manifest_rejects_undeclared_or_non_script_entry() -> None:
    raw = valid_manifest_bytes(script="scripts/undeclared.py")
    with pytest.raises(ExecutableSkillCodecError, match="declared regular script"):
        decode_executable_manifest(raw, declared_scripts=(declared_echo_script(),))


def test_script_descriptor_is_exact_inventory_identity() -> None:
    descriptor = declared_echo_script()
    manifest = decode_executable_manifest(
        valid_manifest_bytes(), declared_scripts=(descriptor,)
    )
    assert manifest.entrypoints[0].script.to_payload() == {
        "relative_path": "scripts/echo.py",
        "size_bytes": descriptor.size_bytes,
        "sha256": descriptor.sha256,
    }
    changed = replace(descriptor, sha256="f" * 64, descriptor_digest="")
    assert changed.descriptor_digest != descriptor.descriptor_digest


def test_digest_helpers_recompute_and_reject_tampered_self_digests() -> None:
    manifest = decode_executable_manifest(
        valid_manifest_bytes(), declared_scripts=(declared_echo_script(),)
    )
    requirements = decode_portable_requirements(valid_requirements_bytes())
    assert re.fullmatch(r"[0-9a-f]{64}", executable_manifest_digest(manifest))
    assert executable_manifest_digest(manifest) == manifest.manifest_digest
    assert portable_requirements_digest(requirements) == requirements.requirements_digest
    with pytest.raises(ExecutableSkillCodecError, match="manifest digest mismatch"):
        executable_manifest_digest(replace(manifest, package_version="1.0.1"))
    with pytest.raises(ExecutableSkillCodecError, match="requirements digest mismatch"):
        portable_requirements_digest(
            replace(requirements, abi="cpython-3.12")
        )


def test_none_requirements_uses_one_versioned_marker_digest() -> None:
    payload = b'{"schema":"first-agent-no-portable-requirements/v1"}'
    expected = hashlib.sha256(
        b"first-agent-no-portable-requirements-v1\x00" + payload
    ).hexdigest()
    assert portable_requirements_digest(None) == expected
    assert re.fullmatch(r"[0-9a-f]{64}", portable_requirements_digest(None))


def test_requirements_are_portable_and_exact() -> None:
    requirements = decode_portable_requirements(valid_requirements_bytes())
    payload = requirements.to_payload()
    assert set(payload) == {"schema", "runtime", "dependencies", "runtime_profile"}
    encoded = json.dumps(payload, sort_keys=True)
    assert "interpreter" not in encoded
    assert "path" not in encoded
    assert "platform" not in encoded
```

- [ ] **Step 2: Run the codec Reds**

Run:

```bash
.venv/bin/python -m pytest -q tests/skill/test_executable_contracts.py tests/skill/test_executable_codec.py -rx
```

Expected: collection fails because the two executable modules do not exist.

- [ ] **Step 3: Implement the closed leaf contracts**

Create `agent/skill/executable_contracts.py` with these exact v1 enum values and bounds:

```python
class SkillRuntimeV1(StrEnum):
    PYTHON_STRUCTURED = "python-structured-v1"


class SkillOperationV1(StrEnum):
    SKILL_READ = "skill-read"
    ARTIFACT_READ = "artifact-read"
    ARTIFACT_WRITE = "artifact-write"


class SkillFormatV1(StrEnum):
    GENERIC = "generic"
    PDF = "pdf"
    DOCX = "docx"
    XLSX = "xlsx"
    PPTX = "pptx"
    PNG = "png"
    JPEG = "jpeg"
    WEBP = "webp"


class SkillParameterKindV1(StrEnum):
    TEXT = "text"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    JSON = "json"
    WORKSPACE_INPUT_FILE = "workspace-input-file"
    PDF_PAGE_SELECTOR = "pdf-page-selector"
    DOCX_RANGE_SELECTOR = "docx-range-selector"
    XLSX_RANGE_SELECTOR = "xlsx-range-selector"
    PPTX_SLIDE_SELECTOR = "pptx-slide-selector"
    RASTER_REGION_SELECTOR = "raster-region-selector"


class SkillResultKindV1(StrEnum):
    SKILL_RESULT = "skill-result-v1"
    ARTIFACT_OBSERVATION = "artifact-observation-v1"


class SkillRuntimeProfileV1(StrEnum):
    SKILL_STANDARD = "skill-standard-v1"
    ARTIFACT_STANDARD = "artifact-standard-v1"


class SkillNetworkV1(StrEnum):
    OFF = "off"
```

Use frozen dataclasses with exact payload methods:

```python
@dataclass(frozen=True, slots=True)
class SkillParameterV1:
    name: str
    kind: SkillParameterKindV1
    optional: bool
    extensions: tuple[str, ...]

    def to_payload(self) -> dict[str, JSONValue]:
        payload: dict[str, JSONValue] = {
            "name": self.name,
            "kind": self.kind.value,
            "optional": self.optional,
        }
        if self.extensions:
            payload["extensions"] = list(self.extensions)
        return payload


@dataclass(frozen=True, slots=True)
class SkillResultContractV1:
    kind: SkillResultKindV1
    max_chars: int

    def to_payload(self) -> dict[str, JSONValue]:
        return {"kind": self.kind.value, "max_chars": self.max_chars}


@dataclass(frozen=True, slots=True)
class ExecutableScriptDescriptorV1:
    relative_path: str
    size_bytes: int
    sha256: str
    descriptor_digest: str = ""

    def __post_init__(self) -> None:
        parts = self.relative_path.split("/")
        if (
            not self.relative_path.startswith("scripts/")
            or "\\" in self.relative_path
            or self.relative_path.startswith("/")
            or any(part in {"", ".", ".."} for part in parts)
        ):
            raise ValueError("script descriptor path is unsafe")
        if (
            not isinstance(self.size_bytes, int)
            or isinstance(self.size_bytes, bool)
            or self.size_bytes < 0
            or self.size_bytes > 32 * 1024 * 1024
        ):
            raise ValueError("script descriptor size is invalid")
        if re.fullmatch(r"[0-9a-f]{64}", self.sha256) is None:
            raise ValueError("script descriptor sha256 must be bare lowercase hex64")
        digest = canonical_json_digest({
            "domain": "first-agent-executable-script-descriptor-v1",
            **self.to_payload(),
        })
        if self.descriptor_digest and self.descriptor_digest != digest:
            raise ValueError("script descriptor digest mismatch")
        object.__setattr__(self, "descriptor_digest", digest)

    def to_payload(self) -> dict[str, JSONValue]:
        return {
            "relative_path": self.relative_path,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class ExecutableEntrypointV1:
    name: str
    description: str
    runtime: SkillRuntimeV1
    script: ExecutableScriptDescriptorV1
    operation: SkillOperationV1
    format: SkillFormatV1
    parameters: tuple[SkillParameterV1, ...]
    result: SkillResultContractV1
    limits: SkillRuntimeProfileV1
    network: SkillNetworkV1
    entrypoint_digest: str

    def manifest_payload(self) -> dict[str, JSONValue]:
        return {
            "name": self.name,
            "description": self.description,
            "runtime": self.runtime.value,
            "script": self.script.relative_path,
            "operation": self.operation.value,
            "format": self.format.value,
            "parameters": [item.to_payload() for item in self.parameters],
            "result": self.result.to_payload(),
            "limits": {"profile": self.limits.value},
            "network": self.network.value,
        }

    def identity_payload(self) -> dict[str, JSONValue]:
        return {
            **self.manifest_payload(),
            "script": self.script.to_payload(),
        }


@dataclass(frozen=True, slots=True)
class ExecutableSkillManifestV1:
    schema: str
    package_name: str
    package_version: str
    entrypoints: tuple[ExecutableEntrypointV1, ...]
    manifest_digest: str

    def to_payload(self) -> dict[str, JSONValue]:
        return {
            "schema": self.schema,
            "package": {
                "name": self.package_name,
                "version": self.package_version,
            },
            "entrypoints": [item.manifest_payload() for item in self.entrypoints],
        }


@dataclass(frozen=True, slots=True)
class PortableDependencyV1:
    name: str
    version: str

    def to_payload(self) -> dict[str, JSONValue]:
        return {"name": self.name, "version": self.version}


@dataclass(frozen=True, slots=True)
class PortableRequirementsV1:
    schema: str
    runtime: SkillRuntimeV1
    abi: str
    dependencies: tuple[PortableDependencyV1, ...]
    runtime_profile: SkillRuntimeProfileV1
    requirements_digest: str

    def to_payload(self) -> dict[str, JSONValue]:
        return {
            "schema": self.schema,
            "runtime": {"kind": self.runtime.value, "abi": self.abi},
            "dependencies": [item.to_payload() for item in self.dependencies],
            "runtime_profile": self.runtime_profile.value,
        }
```

Validate package/entrypoint/parameter names with `^[a-z][a-z0-9-]{0,63}$`; SemVer with `^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$`; dependency names with `^[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?$`; ABI with `^[a-z0-9][a-z0-9._-]{0,63}$`. Fix bounds at 256 KiB per JSON file, 32 entrypoints, 32 parameters per entrypoint, 64 dependencies, 1,024 description UTF-8 bytes, and `1 <= max_chars <= 64_000`. Require byte-sorted unique entrypoint names, parameter names, dependency `(name, version)` pairs, declared-script descriptor paths, and lowercase dot-prefixed extensions. `entrypoint_digest` is the domain-separated digest of `identity_payload()` and therefore binds the inventory-resolved script path, size, and hash; `manifest_digest` remains the portable digest of canonical `first-agent.json` payload with the publisher's script path string.

- [ ] **Step 4: Implement the one strict codec**

Create `agent/skill/executable_codec.py` around one duplicate-key hook and one exact-key helper:

```python
class ExecutableSkillCodecError(ValueError):
    pass


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ExecutableSkillCodecError(f"duplicate key: {key}")
        result[key] = value
    return result


def _decode(raw: bytes) -> dict[str, object]:
    if len(raw) > 262_144:
        raise ExecutableSkillCodecError("executable JSON exceeds the byte limit")
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_object,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ExecutableSkillCodecError(f"non-finite number: {value}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ExecutableSkillCodecError("executable JSON is malformed") from error
    if not isinstance(value, dict):
        raise ExecutableSkillCodecError("executable JSON must be an object")
    return value


def _keys(value: dict[str, object], required: frozenset[str], optional: frozenset[str] = frozenset()) -> None:
    actual = frozenset(value)
    if not required <= actual or actual - required - optional:
        raise ExecutableSkillCodecError("object has unknown or missing keys")


def _safe_script(
    value: object,
    declared_scripts: tuple[ExecutableScriptDescriptorV1, ...],
) -> ExecutableScriptDescriptorV1:
    if not isinstance(value, str) or not value.startswith("scripts/"):
        raise ExecutableSkillCodecError("script must be a declared regular script")
    parts = value.split("/")
    if "\\" in value or value.startswith("/") or any(part in {"", ".", ".."} for part in parts):
        raise ExecutableSkillCodecError("script path is unsafe")
    matches = tuple(item for item in declared_scripts if item.relative_path == value)
    if len(matches) != 1:
        raise ExecutableSkillCodecError("script must be a declared regular script")
    return matches[0]


def _canonical(payload: dict[str, JSONValue]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _domain_digest(domain: str, payload: dict[str, JSONValue]) -> str:
    return hashlib.sha256(domain.encode("ascii") + b"\x00" + _canonical(payload)).hexdigest()


def _entrypoint_digest(entrypoint: ExecutableEntrypointV1) -> str:
    digest = _domain_digest(
        "first-agent-executable-entrypoint-v1",
        entrypoint.identity_payload(),
    )
    if entrypoint.entrypoint_digest and entrypoint.entrypoint_digest != digest:
        raise ExecutableSkillCodecError("entrypoint digest mismatch")
    return digest


def executable_manifest_digest(manifest: ExecutableSkillManifestV1) -> str:
    digest = _domain_digest(
        "first-agent-executable-manifest-v1",
        manifest.to_payload(),
    )
    if manifest.manifest_digest and manifest.manifest_digest != digest:
        raise ExecutableSkillCodecError("manifest digest mismatch")
    return digest


def portable_requirements_digest(
    requirements: PortableRequirementsV1 | None,
) -> str:
    if requirements is None:
        return _domain_digest(
            "first-agent-no-portable-requirements-v1",
            {"schema": "first-agent-no-portable-requirements/v1"},
        )
    digest = _domain_digest(
        "first-agent-portable-requirements-v1",
        requirements.to_payload(),
    )
    if requirements.requirements_digest and requirements.requirements_digest != digest:
        raise ExecutableSkillCodecError("requirements digest mismatch")
    return digest
```

`decode_executable_manifest` must first require `declared_scripts` to be byte-sorted by `relative_path` and free of duplicate exact/NFC/casefold paths, then call `_keys` at the top, package, every entrypoint, parameter, result, and limits object. It constructs every enum directly so unknown values fail, resolves each publisher script path to exactly one supplied `ExecutableScriptDescriptorV1`, verifies the manifest package name/version against the decoded `SKILL.md` package identity at the caller, computes `entrypoint_digest` from the descriptor-bearing `identity_payload()`, and computes `manifest_digest` from the canonical publisher payload. `encode_executable_manifest` writes the publisher shape with a script path string; the runner request uses the resolved descriptor object. `decode_portable_requirements` accepts exactly:

```json
{"dependencies":[{"name":"first-agent-skill-runtime","version":"1.0.0"}],"runtime":{"abi":"cpython-3.11","kind":"python-structured-v1"},"runtime_profile":"skill-standard-v1","schema":"first-agent-skill-requirements/v1"}
```

It rejects all other top/runtime/dependency keys and computes a bare lowercase hex64 `requirements_digest` over canonical bytes with domain `first-agent-portable-requirements-v1`. Absence is represented only by `portable_requirements_digest(None)`, whose exact domain/payload are frozen above; there is no nullable, empty-file, or all-zero digest. `decode_executable_manifest` likewise returns a bare lowercase hex64 `manifest_digest`. 021 imports `ExecutableSkillManifestV1`, `ExecutableScriptDescriptorV1`, and `PortableRequirementsV1` only from `agent.skill.executable_contracts`, and imports both decoders/digest helpers only from `agent.skill.executable_codec`; any 021 duplicate requirements, script-descriptor, or manifest type/parser is a prerequisite failure.

- [ ] **Step 5: Verify Green and checkpoint commit**

Run:

```bash
.venv/bin/python -m pytest -q tests/skill/test_executable_contracts.py tests/skill/test_executable_codec.py -rx
.venv/bin/ruff check agent/skill/executable_contracts.py agent/skill/executable_codec.py tests/skill/package_fixtures.py tests/skill/test_executable_contracts.py tests/skill/test_executable_codec.py
git diff --check
git add agent/skill/executable_contracts.py agent/skill/executable_codec.py tests/skill/package_fixtures.py tests/skill/test_executable_contracts.py tests/skill/test_executable_codec.py
git commit -m "feat(skill): add closed executable package contracts"
```

Expected: all valid contracts round-trip canonically; every duplicate, extra key, unsafe script, forbidden field, open enum, and nonportable requirement is rejected.

---

### Task 3: Freeze the activation-gate, invocation, and registration identity seams

**Files:**
- Modify: `agent/skill/executable_contracts.py`
- Create: `agent/skill/execution.py`
- Modify: `agent/skill/tools.py`
- Create: `tests/skill/test_packaged_registration.py`
- Create: `tests/skill/test_executable_tools.py`

**Interfaces:**
- Consumes 021 `SkillActivationGate`, `SkillExecutionGuardV1`, `ActivationGateDecisionV1`, `ActiveSkillSetV1`, and `MaterializedActivePackageV1`; defines none of them.
- `PackagedSkillBindingV1.from_safety_binding(binding, arguments) -> PackagedSkillBindingV1`
- `build_packaged_skill_registrations(active_set, activation_gate, execution_adapter, *, max_tool_result_chars) -> tuple[RegisteredTool, ...]`

- [ ] **Step 1: Write static identity, exposure, and gate Reds**

```python
def test_one_entrypoint_becomes_one_exact_model_tool() -> None:
    registration = entrypoint_registration()
    spec = registration.spec
    assert spec.name == "skill__echo-json__echo"
    assert spec.version == "1.0.0"
    assert spec.risk is ToolRisk.HIGH
    assert spec.side_effect is SideEffectClass.EXTERNAL
    assert spec.approval_policy is ApprovalPolicy.ALWAYS
    assert spec.execution_authority is ExecutionAuthorityClass.ISOLATED_SANDBOX
    assert spec.egress is EgressClass.NONE
    assert spec.output_policy is OutputPolicy.BOUNDED_TEXT
    assert registration.exposure is ToolExposure.MODEL
    assert set(spec.safety_policy) == {
        "kind", "active_snapshot_digest", "package_digest",
        "storage_identity_digest", "manifest_digest", "requirements_digest",
        "qualification_digest", "entrypoint_id", "entrypoint_digest",
        "script_descriptor_digest",
        "operation", "format", "sandbox_profile", "network", "runner",
    }


def test_allowed_tools_cannot_change_entrypoint_authority() -> None:
    first = entrypoint_registration(allowed_tools=())
    second = entrypoint_registration(allowed_tools=("Write", "Bash(rm:*)"))
    assert first.spec.safety_policy == second.spec.safety_policy
    assert first.spec.approval_policy == second.spec.approval_policy
    assert first.spec.execution_authority == second.spec.execution_authority


def test_prepare_gate_is_short_and_denial_proves_zero_spawn() -> None:
    trace: list[str] = []
    gate = TestSkillActivationGate(trace=trace, decision=None)
    preparer = entrypoint_binding_preparer(gate=gate)
    prepared = preparer({"text": "hello"})
    assert isinstance(prepared, dict)
    assert trace == ["acquire", "validate", "release"]

    revoked = TestSkillActivationGate(trace=[], decision=ActivationGateDecisionV1.REVOKED)
    preparation = entrypoint_binding_preparer(gate=revoked)({"text": "hello"})
    assert isinstance(preparation, KnownNotExecuted)
    assert preparation.code == "skill_package_revoked"
    assert revoked.spawn_calls == 0


def test_packaged_activation_spec_and_binding_pin_exact_package_identity() -> None:
    registration = packaged_registrations()[0]
    package = active_package_fixture()
    assert registration.spec.safety_policy == {
        "kind": "packaged_skill_activation_v1",
        "active_snapshot_digest": ACTIVE_SNAPSHOT_DIGEST,
        "active_set_digest": ACTIVE_SET_DIGEST,
        "skill_name": "echo-json",
        "package_digest": package.active.package_digest,
        "storage_identity_digest": package.active.storage_identity_digest,
        "qualification_digest": package.qualification.qualification_digest,
        "descriptor_identity_digest": package.descriptor.identity_digest,
        "catalog_digest": ACTIVE_CATALOG_DIGEST,
    }
    binding = registration.prepare_binding({})
    assert isinstance(binding, dict)
    assert binding["operation"] == "activation"
    assert binding["package_digest"] == package.active.package_digest
    assert binding["qualification_digest"] == package.qualification.qualification_digest


def test_shared_resource_spec_binds_active_set_and_prepare_selects_one_package() -> None:
    registration = next(
        item for item in packaged_registrations()
        if item.spec.name == "skill__read_resource"
    )
    assert registration.spec.safety_policy == {
        "kind": "packaged_skill_resource_v1",
        "active_snapshot_digest": ACTIVE_SNAPSHOT_DIGEST,
        "active_set_digest": ACTIVE_SET_DIGEST,
        "catalog_digest": ACTIVE_CATALOG_DIGEST,
    }
    binding = registration.prepare_binding(
        {"skill_name": "echo-json", "path": "references/RESULTS.md"}
    )
    package = active_package_fixture()
    assert isinstance(binding, dict)
    assert binding["operation"] == "resource"
    assert binding["skill_name"] == "echo-json"
    assert binding["package_digest"] == package.active.package_digest
    assert binding["storage_identity_digest"] == package.active.storage_identity_digest
    assert binding["qualification_digest"] == package.qualification.qualification_digest
```

- [ ] **Step 2: Run the registration Reds**

Run:

```bash
.venv/bin/python -m pytest -q tests/skill/test_packaged_registration.py tests/skill/test_executable_tools.py -rx
```

Expected: collection fails because `PackagedSkillBindingV1` and the packaged registration builder do not exist. The test-local gate structurally implements the already-existing 021 protocol.

In the test-local `TestSkillActivationGate`, `decision=None` returns a recording `SkillExecutionGuardV1`; the only enum values it may return are 021's `REVOKED` and `RESTART_REQUIRED`. Do not add an `ALLOW` enum member or a production fake/concrete gate in 020b.

- [ ] **Step 3: Add the one exact prepared binding contract**

Import `SkillActivationGate`, `SkillExecutionGuardV1`, and `ActivationGateDecisionV1` from `agent.skill.package_contracts`; do not define a protocol or concrete gate in `agent/skill/execution.py`. In `agent/skill/executable_contracts.py`, add one digest-bound binding containing no path or bytes:

```python
def _closed_positive_int(value: JSONValue, maximum: int) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 1
        or value > maximum
    ):
        raise ValueError("value must be a bounded positive integer")
    return value


@dataclass(frozen=True, slots=True)
class PackagedSkillBindingV1:
    active_snapshot_digest: str
    package_digest: str
    storage_identity_digest: str
    manifest_digest: str
    requirements_digest: str
    qualification_digest: str
    entrypoint_id: str
    entrypoint_digest: str
    script_descriptor_digest: str
    operation: SkillOperationV1
    format: SkillFormatV1
    result_kind: SkillResultKindV1
    result_max_chars: int
    runtime_profile: SkillRuntimeProfileV1
    network: SkillNetworkV1
    arguments_digest: str
    request_digest: str
    input_descriptors_digest: str
    resource_limits_digest: str
    structured_invocation_digest: str
    command_fingerprint: str
    policy_instance_digest: str
    sandbox_mode: str
    sandbox_network: str
    binding_digest: str = ""

    def identity_values(self) -> dict[str, JSONValue]:
        return {
            "active_snapshot_digest": self.active_snapshot_digest,
            "package_digest": self.package_digest,
            "storage_identity_digest": self.storage_identity_digest,
            "manifest_digest": self.manifest_digest,
            "requirements_digest": self.requirements_digest,
            "qualification_digest": self.qualification_digest,
            "entrypoint_id": self.entrypoint_id,
            "entrypoint_digest": self.entrypoint_digest,
            "script_descriptor_digest": self.script_descriptor_digest,
            "operation": self.operation.value,
            "format": self.format.value,
            "result_kind": self.result_kind.value,
            "result_max_chars": self.result_max_chars,
            "runtime_profile": self.runtime_profile.value,
            "network": self.network.value,
            "arguments_digest": self.arguments_digest,
            "request_digest": self.request_digest,
            "input_descriptors_digest": self.input_descriptors_digest,
            "resource_limits_digest": self.resource_limits_digest,
            "structured_invocation_digest": self.structured_invocation_digest,
            "command_fingerprint": self.command_fingerprint,
            "policy_instance_digest": self.policy_instance_digest,
            "sandbox_mode": self.sandbox_mode,
            "sandbox_network": self.sandbox_network,
        }

    def to_safety_binding(self) -> dict[str, JSONValue]:
        return {**self.identity_values(), "binding_digest": self.binding_digest}

    @classmethod
    def from_safety_binding(
        cls,
        value: Mapping[str, JSONValue],
        arguments: Mapping[str, JSONValue],
    ) -> PackagedSkillBindingV1:
        expected_keys = {
            "active_snapshot_digest", "package_digest", "storage_identity_digest",
            "manifest_digest", "requirements_digest", "qualification_digest",
            "entrypoint_id", "entrypoint_digest", "script_descriptor_digest",
            "operation", "format",
            "result_kind", "result_max_chars", "runtime_profile", "network",
            "arguments_digest", "request_digest", "input_descriptors_digest",
            "resource_limits_digest", "structured_invocation_digest",
            "command_fingerprint", "policy_instance_digest", "sandbox_mode",
            "sandbox_network", "binding_digest",
        }
        if set(value) != expected_keys:
            raise ValueError("packaged Skill binding keys are not closed")
        if canonical_json_digest(dict(arguments)) != value["arguments_digest"]:
            raise ValueError("packaged Skill arguments changed after prepare")
        return cls(
            active_snapshot_digest=str(value["active_snapshot_digest"]),
            package_digest=str(value["package_digest"]),
            storage_identity_digest=str(value["storage_identity_digest"]),
            manifest_digest=str(value["manifest_digest"]),
            requirements_digest=str(value["requirements_digest"]),
            qualification_digest=str(value["qualification_digest"]),
            entrypoint_id=str(value["entrypoint_id"]),
            entrypoint_digest=str(value["entrypoint_digest"]),
            script_descriptor_digest=str(value["script_descriptor_digest"]),
            operation=SkillOperationV1(str(value["operation"])),
            format=SkillFormatV1(str(value["format"])),
            result_kind=SkillResultKindV1(str(value["result_kind"])),
            result_max_chars=_closed_positive_int(value["result_max_chars"], 65_536),
            runtime_profile=SkillRuntimeProfileV1(str(value["runtime_profile"])),
            network=SkillNetworkV1(str(value["network"])),
            arguments_digest=str(value["arguments_digest"]),
            request_digest=str(value["request_digest"]),
            input_descriptors_digest=str(value["input_descriptors_digest"]),
            resource_limits_digest=str(value["resource_limits_digest"]),
            structured_invocation_digest=str(value["structured_invocation_digest"]),
            command_fingerprint=str(value["command_fingerprint"]),
            policy_instance_digest=str(value["policy_instance_digest"]),
            sandbox_mode=str(value["sandbox_mode"]),
            sandbox_network=str(value["sandbox_network"]),
            binding_digest=str(value["binding_digest"]),
        )
```

`__post_init__` applies `re.fullmatch(r"[0-9a-f]{64}", value)` to every `*_digest`/fingerprint except the self field, requires `sandbox_mode == "read-only"`, `sandbox_network == "off"`, and recomputes `binding_digest = canonical_json_digest(identity_values())`. A supplied nonempty self digest must exact-match. There is no dict-only parallel binding and no `sha256:` normalization.

- [ ] **Step 4: Build exact governed content registrations and one stable ToolSpec per entrypoint**

First add the one decision mapper plus the actual entrypoint preparer/callable to `agent/skill/execution.py`. Both prepare and invoke use 021's gate; the callable holds the fresh invoke guard through the adapter return:

```python
def activation_gate_rejection(
    decision: ActivationGateDecisionV1,
) -> KnownNotExecuted:
    if decision is ActivationGateDecisionV1.REVOKED:
        return KnownNotExecuted(
            "skill_package_revoked",
            "The Skill package is no longer active; restart before invoking it.",
        )
    if decision is ActivationGateDecisionV1.RESTART_REQUIRED:
        return KnownNotExecuted(
            "skill_restart_required",
            "The active Skill snapshot changed; restart before invoking it.",
        )
    raise ValueError("unknown activation gate decision")


@dataclass(frozen=True, slots=True)
class _PackagedSkillBindingPreparer:
    snapshot_digest: str
    package: MaterializedActivePackageV1
    entrypoint: ExecutableEntrypointV1
    gate: SkillActivationGate
    adapter: PackagedSkillExecutionAdapter

    def __call__(
        self,
        arguments: dict[str, JSONValue],
    ) -> dict[str, JSONValue] | KnownNotExecuted:
        outcome = self.gate.acquire_execution_guard(
            expected_snapshot_digest=self.snapshot_digest,
            package_digest=self.package.active.package_digest,
            storage_identity_digest=self.package.active.storage_identity_digest,
            qualification_digest=self.package.qualification.qualification_digest,
        )
        if isinstance(outcome, ActivationGateDecisionV1):
            return activation_gate_rejection(outcome)
        try:
            return self.adapter.prepare_binding(
                snapshot_digest=self.snapshot_digest,
                package=self.package,
                entrypoint=self.entrypoint,
                arguments=arguments,
                inputs=(),
            )
        finally:
            outcome.release()


@dataclass(frozen=True, slots=True)
class _PackagedSkillCallable:
    snapshot_digest: str
    package_digest: str
    storage_identity_digest: str
    qualification_digest: str
    gate: SkillActivationGate
    adapter: PackagedSkillExecutionAdapter

    def __call__(
        self,
        intent: ExecutionIntent,
    ) -> StructuredSandboxToolDraftV1 | KnownNotExecuted:
        outcome = self.gate.acquire_execution_guard(
            expected_snapshot_digest=self.snapshot_digest,
            package_digest=self.package_digest,
            storage_identity_digest=self.storage_identity_digest,
            qualification_digest=self.qualification_digest,
        )
        if isinstance(outcome, ActivationGateDecisionV1):
            return activation_gate_rejection(outcome)
        try:
            binding = PackagedSkillBindingV1.from_safety_binding(
                intent.safety_binding,
                intent.arguments,
            )
            return self.adapter.execute(intent, binding)
        finally:
            outcome.release()
```

Then implement the content identity and content registrations directly in `agent/skill/tools.py`. Do not route immutable packaged content through the legacy `build_skill_tool_registrations` path:

```python
@dataclass(frozen=True, slots=True)
class _PackagedContentIdentityV1:
    skill_name: str
    active_snapshot_digest: str
    active_set_digest: str
    package_digest: str
    storage_identity_digest: str
    qualification_digest: str
    descriptor_identity_digest: str
    catalog_digest: str

    def __post_init__(self) -> None:
        digests = (
            self.active_snapshot_digest,
            self.active_set_digest,
            self.package_digest,
            self.storage_identity_digest,
            self.qualification_digest,
            self.descriptor_identity_digest,
            self.catalog_digest,
        )
        if not self.skill_name or any(
            re.fullmatch(r"[0-9a-f]{64}", value) is None for value in digests
        ):
            raise ValueError("packaged content identity is invalid")

    def to_safety_binding(self, operation: str) -> dict[str, JSONValue]:
        if operation not in {"activation", "resource"}:
            raise ValueError("packaged content operation is invalid")
        return {
            "kind": "packaged_skill_content_v1",
            "operation": operation,
            "skill_name": self.skill_name,
            "active_snapshot_digest": self.active_snapshot_digest,
            "active_set_digest": self.active_set_digest,
            "package_digest": self.package_digest,
            "storage_identity_digest": self.storage_identity_digest,
            "qualification_digest": self.qualification_digest,
            "descriptor_identity_digest": self.descriptor_identity_digest,
            "catalog_digest": self.catalog_digest,
        }

    @classmethod
    def from_safety_binding(
        cls,
        value: Mapping[str, JSONValue],
        *,
        expected_operation: str,
        expected_skill_name: str,
    ) -> _PackagedContentIdentityV1:
        expected_keys = {
            "kind", "operation", "skill_name", "active_snapshot_digest",
            "active_set_digest", "package_digest", "storage_identity_digest",
            "qualification_digest", "descriptor_identity_digest", "catalog_digest",
        }
        if (
            set(value) != expected_keys
            or value["kind"] != "packaged_skill_content_v1"
            or value["operation"] != expected_operation
            or value["skill_name"] != expected_skill_name
        ):
            raise ValueError("packaged content binding is not exact")
        identity = cls(
            skill_name=str(value["skill_name"]),
            active_snapshot_digest=str(value["active_snapshot_digest"]),
            active_set_digest=str(value["active_set_digest"]),
            package_digest=str(value["package_digest"]),
            storage_identity_digest=str(value["storage_identity_digest"]),
            qualification_digest=str(value["qualification_digest"]),
            descriptor_identity_digest=str(value["descriptor_identity_digest"]),
            catalog_digest=str(value["catalog_digest"]),
        )
        if identity.to_safety_binding(expected_operation) != dict(value):
            raise ValueError("packaged content binding changed during decode")
        return identity


def _content_identities(
    active_set: ActiveSkillSetV1,
) -> dict[str, _PackagedContentIdentityV1]:
    identities = {
        package.active.name: _PackagedContentIdentityV1(
            skill_name=package.active.name,
            active_snapshot_digest=active_set.snapshot_digest,
            active_set_digest=active_set.active_set_digest,
            package_digest=package.active.package_digest,
            storage_identity_digest=package.active.storage_identity_digest,
            qualification_digest=package.qualification.qualification_digest,
            descriptor_identity_digest=package.descriptor.identity_digest,
            catalog_digest=active_set.instruction_catalog.catalog_digest,
        )
        for package in active_set.packages
    }
    if tuple(identities) != tuple(
        descriptor.name for descriptor in active_set.instruction_catalog.descriptors
    ):
        raise ValueError("packaged content/package mapping is not exact")
    return identities


def _acquire_content_guard(
    gate: SkillActivationGate,
    identity: _PackagedContentIdentityV1,
) -> SkillExecutionGuardV1 | KnownNotExecuted:
    outcome = gate.acquire_execution_guard(
        expected_snapshot_digest=identity.active_snapshot_digest,
        package_digest=identity.package_digest,
        storage_identity_digest=identity.storage_identity_digest,
        qualification_digest=identity.qualification_digest,
    )
    if isinstance(outcome, ActivationGateDecisionV1):
        return activation_gate_rejection(outcome)
    return outcome


@dataclass(frozen=True, slots=True)
class _PackagedContentBindingPreparer:
    operation: str
    identities: Mapping[str, _PackagedContentIdentityV1]
    gate: SkillActivationGate
    pinned_skill_name: str | None = None

    def __call__(
        self,
        arguments: dict[str, JSONValue],
    ) -> dict[str, JSONValue] | KnownNotExecuted:
        skill_name = self.pinned_skill_name or arguments.get("skill_name")
        if not isinstance(skill_name, str) or skill_name not in self.identities:
            return KnownNotExecuted("skill_unavailable", "Skill is not active.")
        identity = self.identities[skill_name]
        outcome = _acquire_content_guard(self.gate, identity)
        if isinstance(outcome, KnownNotExecuted):
            return outcome
        try:
            return identity.to_safety_binding(self.operation)
        finally:
            outcome.release()


@dataclass(frozen=True, slots=True)
class _PackagedActivationCallable:
    identity: _PackagedContentIdentityV1
    catalog: SkillCatalog
    gate: SkillActivationGate
    max_tool_result_chars: int

    def __call__(self, intent: ExecutionIntent) -> str | KnownNotExecuted:
        bound = _PackagedContentIdentityV1.from_safety_binding(
            intent.safety_binding,
            expected_operation="activation",
            expected_skill_name=self.identity.skill_name,
        )
        if bound != self.identity:
            raise ValueError("packaged activation identity drift")
        outcome = _acquire_content_guard(self.gate, self.identity)
        if isinstance(outcome, KnownNotExecuted):
            return outcome
        try:
            activation = self.catalog.read_activation(self.identity.skill_name)
            descriptor = self.catalog.descriptor_for(self.identity.skill_name)
            content = _format_activation(activation, descriptor)
            if len(content) > self.max_tool_result_chars:
                return KnownNotExecuted(
                    "activation_too_large",
                    "Skill activation exceeds the result budget.",
                )
            return content
        except SkillSecurityError:
            return KnownNotExecuted("skill_drift", "Skill content drifted.")
        except SkillCatalogError:
            return KnownNotExecuted("skill_unavailable", "Skill is unavailable.")
        finally:
            outcome.release()


@dataclass(frozen=True, slots=True)
class _PackagedResourceCallable:
    identities: Mapping[str, _PackagedContentIdentityV1]
    catalog: SkillCatalog
    gate: SkillActivationGate

    def __call__(self, intent: ExecutionIntent) -> str | KnownNotExecuted:
        skill_name = intent.arguments["skill_name"]
        path = intent.arguments["path"]
        if not isinstance(skill_name, str) or not isinstance(path, str):
            return KnownNotExecuted("resource_unavailable", "Resource is unavailable.")
        if path == "scripts" or path.startswith("scripts/"):
            return KnownNotExecuted(
                "skill_resource_denied",
                "Executable scripts are not Skill resources.",
            )
        identity = self.identities.get(skill_name)
        if identity is None:
            return KnownNotExecuted("skill_unavailable", "Skill is not active.")
        bound = _PackagedContentIdentityV1.from_safety_binding(
            intent.safety_binding,
            expected_operation="resource",
            expected_skill_name=skill_name,
        )
        if bound != identity:
            raise ValueError("packaged resource identity drift")
        outcome = _acquire_content_guard(self.gate, identity)
        if isinstance(outcome, KnownNotExecuted):
            return outcome
        try:
            return self.catalog.read_resource(skill_name, path)
        except SkillSecurityError:
            return KnownNotExecuted("resource_drift", "Skill resource drifted.")
        except SkillCatalogError:
            return KnownNotExecuted("resource_unavailable", "Resource is unavailable.")
        finally:
            outcome.release()
```

Build the exact content registrations, input schema, entrypoint registration, and public builder in the same module:

```python
class PackagedSkillRegistrationError(ValueError):
    pass


def _entrypoint_schema(
    parameters: tuple[SkillParameterV1, ...],
) -> dict[str, JSONValue]:
    scalar_schemas: dict[SkillParameterKindV1, dict[str, JSONValue]] = {
        SkillParameterKindV1.TEXT: {"type": "string", "maxLength": 64_000},
        SkillParameterKindV1.INTEGER: {"type": "integer"},
        SkillParameterKindV1.BOOLEAN: {"type": "boolean"},
        SkillParameterKindV1.JSON: {},
    }
    if any(item.kind not in scalar_schemas for item in parameters):
        raise PackagedSkillRegistrationError("artifact_extension_required")
    return {
        "type": "object",
        "properties": {
            item.name: dict(scalar_schemas[item.kind]) for item in parameters
        },
        "required": [item.name for item in parameters if not item.optional],
        "additionalProperties": False,
    }


def _packaged_activation_registration(
    identity: _PackagedContentIdentityV1,
    package: MaterializedActivePackageV1,
    catalog: SkillCatalog,
    gate: SkillActivationGate,
    limit: int,
) -> RegisteredTool:
    spec = ToolSpec(
        name=f"skill__{identity.skill_name}",
        version=package.active.version,
        description=_bounded_description(package.descriptor),
        input_schema={
            "type": "object", "properties": {}, "required": [],
            "additionalProperties": False,
        },
        risk=ToolRisk.LOW,
        side_effect=SideEffectClass.READ_ONLY,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.NEVER,
        safety_policy={
            "kind": "packaged_skill_activation_v1",
            "active_snapshot_digest": identity.active_snapshot_digest,
            "active_set_digest": identity.active_set_digest,
            "skill_name": identity.skill_name,
            "package_digest": identity.package_digest,
            "storage_identity_digest": identity.storage_identity_digest,
            "qualification_digest": identity.qualification_digest,
            "descriptor_identity_digest": identity.descriptor_identity_digest,
            "catalog_digest": identity.catalog_digest,
        },
        output_limit_chars=limit,
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
    )
    return RegisteredTool(
        spec=spec,
        func=_PackagedActivationCallable(identity, catalog, gate, limit),
        prepare_binding=_PackagedContentBindingPreparer(
            "activation", {identity.skill_name: identity}, gate, identity.skill_name,
        ),
        policy=_SkillToolPolicy(),
        exposure=ToolExposure.MODEL,
    )


def _packaged_resource_registration(
    active_set: ActiveSkillSetV1,
    identities: Mapping[str, _PackagedContentIdentityV1],
    gate: SkillActivationGate,
    limit: int,
) -> RegisteredTool:
    catalog = active_set.instruction_catalog
    spec = ToolSpec(
        name=RESOURCE_TOOL,
        version="1",
        description="Read one bounded reference/asset from an active packaged Skill.",
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
            "kind": "packaged_skill_resource_v1",
            "active_snapshot_digest": active_set.snapshot_digest,
            "active_set_digest": active_set.active_set_digest,
            "catalog_digest": catalog.catalog_digest,
        },
        output_limit_chars=limit,
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
    )
    return RegisteredTool(
        spec=spec,
        func=_PackagedResourceCallable(identities, catalog, gate),
        prepare_binding=_PackagedContentBindingPreparer(
            "resource", identities, gate,
        ),
        policy=_SkillToolPolicy(),
        exposure=ToolExposure.MODEL,
    )


def _entrypoint_registration(
    snapshot_digest: str,
    package: MaterializedActivePackageV1,
    entrypoint: ExecutableEntrypointV1,
    gate: SkillActivationGate,
    adapter: PackagedSkillExecutionAdapter,
    limit: int,
) -> RegisteredTool:
    return RegisteredTool(
        spec=_entrypoint_spec(snapshot_digest, package, entrypoint, limit),
        func=_PackagedSkillCallable(
            snapshot_digest=snapshot_digest,
            package_digest=package.active.package_digest,
            storage_identity_digest=package.active.storage_identity_digest,
            qualification_digest=package.qualification.qualification_digest,
            gate=gate,
            adapter=adapter,
        ),
        prepare_binding=_PackagedSkillBindingPreparer(
            snapshot_digest=snapshot_digest,
            package=package,
            entrypoint=entrypoint,
            gate=gate,
            adapter=adapter,
        ),
        exposure=ToolExposure.MODEL,
    )


def build_packaged_skill_registrations(
    active_set: ActiveSkillSetV1,
    activation_gate: SkillActivationGate,
    execution_adapter: PackagedSkillExecutionAdapter,
    *,
    max_tool_result_chars: int,
) -> tuple[RegisteredTool, ...]:
    if max_tool_result_chars < 1:
        raise ValueError("max_tool_result_chars must be positive")
    registrations: list[RegisteredTool] = []
    catalog = active_set.instruction_catalog
    identities = _content_identities(active_set)
    for package in active_set.packages:
        registrations.append(
            _packaged_activation_registration(
                identities[package.active.name], package, catalog,
                activation_gate, max_tool_result_chars,
            )
        )
    registrations.append(
        _packaged_resource_registration(
            active_set, identities, activation_gate, max_tool_result_chars,
        )
    )
    for package in active_set.packages:
        manifest = package.manifest
        if manifest is None:
            continue
        for entrypoint in manifest.entrypoints:
            registrations.append(
                _entrypoint_registration(
                    active_set.snapshot_digest,
                    package,
                    entrypoint,
                    activation_gate,
                    execution_adapter,
                    max_tool_result_chars,
                )
            )
    names = tuple(item.spec.name for item in registrations)
    if len(names) != len(set(names)):
        raise ValueError("active Skill tools contain an exact name collision")
    return tuple(registrations)
```

`ActiveSkillSetV1`, `MaterializedActivePackageV1`, complete active/stored/qualification values, and `instruction_catalog` come from 021. Use `package.manifest`, `package.requirements`, and `package.runtime_closure` directly; do not introduce a 020b `package.executable` wrapper or reconstruct materialized identity from digests. The immutable content path above is distinct from 021's temporary legacy gate adapter: it uses the same 021 `SkillActivationGate` protocol and concrete repository guard, but never calls or modifies legacy `build_skill_tool_registrations`. Resource inventory and reads remain limited to `references/` and `assets/`; add an assertion that no `scripts/` entry appears in `catalog.resources`.

Build every entrypoint spec with exact closed fields:

```python
def _entrypoint_spec(snapshot_digest, package, entrypoint, limit):
    side_effect = (
        SideEffectClass.WRITE
        if entrypoint.operation is SkillOperationV1.ARTIFACT_WRITE
        else SideEffectClass.EXTERNAL
    )
    safety_policy = {
        "kind": "packaged_skill_entrypoint_v1",
        "active_snapshot_digest": snapshot_digest,
        "package_digest": package.active.package_digest,
        "storage_identity_digest": package.active.storage_identity_digest,
        "manifest_digest": package.manifest.manifest_digest,
        "requirements_digest": package.requirements.requirements_digest,
        "qualification_digest": package.active.qualification_digest,
        "entrypoint_id": entrypoint.name,
        "entrypoint_digest": entrypoint.entrypoint_digest,
        "script_descriptor_digest": entrypoint.script.descriptor_digest,
        "operation": entrypoint.operation.value,
        "format": entrypoint.format.value,
        "sandbox_profile": "packaged-skill-v1",
        "network": "off",
        "runner": "python-structured-v1",
    }
    return ToolSpec(
        name=f"skill__{package.active.name}__{entrypoint.name}",
        version=package.active.version,
        description=entrypoint.description,
        input_schema=_entrypoint_schema(entrypoint.parameters),
        risk=ToolRisk.HIGH,
        side_effect=side_effect,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.ALWAYS,
        safety_policy=safety_policy,
        output_limit_chars=min(limit, entrypoint.result.max_chars),
        egress=EgressClass.NONE,
        execution_authority=ExecutionAuthorityClass.ISOLATED_SANDBOX,
        source_kinds=(),
    )
```

For 020b, `_entrypoint_schema` supports `text`, `integer`, `boolean`, and `json` with `additionalProperties: false`; Artifact/file/selectors are decoded but registration fails with `artifact_extension_required` until 022 adds their closed schemas. It never accepts executable/script/env/cwd/argv fields. The activation/resource preparer takes a short SH/read/releases; Runtime invoke re-runs that preparer, exact-compares the selected-package binding, then the callable takes a fresh SH and holds it through the complete bounded catalog read. There is no SH→EX upgrade and no gate result is cached.

- [ ] **Step 5: Verify Green and checkpoint commit**

Run:

```bash
.venv/bin/python -m pytest -q tests/skill/test_packaged_registration.py tests/skill/test_executable_tools.py tests/skill/test_tools.py -rx
.venv/bin/ruff check agent/skill/executable_contracts.py agent/skill/execution.py agent/skill/tools.py tests/skill
git diff --check
git add agent/skill/executable_contracts.py agent/skill/execution.py agent/skill/tools.py tests/skill/test_packaged_registration.py tests/skill/test_executable_tools.py
git commit -m "feat(skill): register immutable packaged entrypoints"
```

Expected: one immutable active snapshot produces deterministic activation/resource/entrypoint registrations; every spawn-capable tool is model-visible but always requires exact approval.

---

### Task 4: Add the closed `skill-result-v1` seam and Runtime-minted receipt

**Files:**
- Create: `agent/skill/executable_results.py`
- Modify: `agent/skill/execution.py`
- Modify: `agent/runtime/tools.py`
- Create: `tests/skill/test_executable_results.py`
- Create: `tests/skill/test_executable_receipts.py`
- Modify: `tests/sandbox/test_tools.py`

**Interfaces:**
- `decode_packaged_skill_result(draft, expectation) -> DecodedSkillResultV1`
- `_decode_semantic(draft, expectation) -> tuple[PackagedSkillSemanticOutcomeV1, DecodedSkillResultV1 | None]`
- `StructuredSandboxToolDraftV1`
- `SkillResultReceiptV1.create(result, binding, intent, sandbox_receipt_digest)`; only `KernelToolRuntime` calls it, after it has decoded `draft.process.result_bytes` itself.

- [ ] **Step 1: Write text/JSON, forgery, and evidence Reds**

```python
def test_skill_result_v1_accepts_bounded_text_and_json() -> None:
    text_result = decode_packaged_skill_result(
        structured_result(payload={"schema": "skill-result-v1", "output": {"type": "text", "value": "hello"}}),
        expectation(max_chars=32),
    )
    json_result = decode_packaged_skill_result(
        structured_result(payload={"schema": "skill-result-v1", "output": {"type": "json", "value": {"count": 2}}}),
        expectation(max_chars=32),
    )
    assert text_result.projection == "hello"
    assert json_result.projection == '{"count":2}'


@pytest.mark.parametrize(
    "payload",
    (
        {"schema": "skill-result-v1", "output": {"type": "text", "value": "x"}, "extra": True},
        {"schema": "future", "output": {"type": "text", "value": "x"}},
        {"schema": "skill-result-v1", "output": {"type": "future", "value": "x"}},
        {"schema": "skill-result-v1", "output": {"type": "text", "value": {"not": "text"}}},
    ),
)
def test_skill_result_v1_is_closed(payload: dict[str, object]) -> None:
    with pytest.raises(PackagedSkillResultError):
        decode_packaged_skill_result(structured_result(payload=payload), expectation(max_chars=32))


def test_exit_zero_or_forged_ordinary_output_cannot_mint_skill_receipt() -> None:
    runtime = runtime_with_entrypoint(result="looks successful")
    result = invoke_approved(runtime)
    assert result.is_error is True
    assert result.metadata["code"] == "sandbox_draft_forgery"
    assert "skill_result_receipt" not in result.metadata


def test_runtime_mints_receipt_only_after_sandbox_and_semantic_validation() -> None:
    result = invoke_approved(runtime_with_valid_structured_result())
    receipt = SkillResultReceiptV1.from_payload(result.metadata["skill_result_receipt"])
    assert receipt.sandbox_receipt_digest == result.metadata["receipt_digest"]
    assert receipt.intent_digest
    assert receipt.result_digest == result.metadata["structured_result_digest"]


def test_runtime_redecodes_process_bytes_and_rejects_resigned_wrapper_forgery() -> None:
    draft = valid_packaged_draft()
    forged_result = replace(
        draft.result,
        projection="forged",
        output_digest=hashlib.sha256(b"forged").hexdigest(),
    )
    forged = replace(draft, result=forged_result, draft_digest="")
    forged = replace(
        forged,
        draft_digest=canonical_json_digest(forged.identity_values()),
    )
    result = invoke_approved(runtime_with_packaged_draft(forged))
    assert result.is_error is True
    assert result.executed is True
    assert result.metadata["code"] == "packaged_skill_semantic_forgery"
    assert "skill_result_receipt" not in result.metadata


@pytest.mark.parametrize(
    ("draft", "expected", "outcome"),
    (
        (
            structured_result(payload={"schema": "skill-result-v1", "output": {"type": "text", "value": "ok"}}),
            expectation(max_chars=32),
            PackagedSkillSemanticOutcomeV1.VALID,
        ),
        (
            structured_result(kind="artifact", payload={"schema": "skill-result-v1", "output": {"type": "text", "value": "ok"}}),
            expectation(max_chars=32),
            PackagedSkillSemanticOutcomeV1.RESULT_KIND_MISMATCH,
        ),
        (
            structured_result(payload={"schema": "future", "output": {"type": "text", "value": "ok"}}),
            expectation(max_chars=32),
            PackagedSkillSemanticOutcomeV1.RESULT_SCHEMA_INVALID,
        ),
        (
            structured_result(payload={"schema": "skill-result-v1", "output": {"type": "text", "value": "too-long"}}),
            expectation(max_chars=2),
            PackagedSkillSemanticOutcomeV1.RESULT_LIMIT_EXCEEDED,
        ),
    ),
)
def test_semantic_outcome_taxonomy_is_closed(draft, expected, outcome) -> None:
    actual, decoded = _decode_semantic(draft, expected)
    assert actual is outcome
    assert (decoded is not None) is (outcome is PackagedSkillSemanticOutcomeV1.VALID)


@pytest.mark.parametrize(
    "raw",
    (
        b"\xff",
        b'{"kind":',
        (b'[' * 1_100) + (b']' * 1_100),
        b'{"kind":"observation","payload":{"schema":"skill-result-v1",'
        b'"output":{"type":"future","value":null}},'
        b'"protocol":"first-agent-skill-result-v1"}',
    ),
)
def test_decoder_wraps_utf8_json_enum_and_recursion_failures(raw: bytes) -> None:
    with pytest.raises(PackagedSkillResultError) as raised:
        decode_packaged_skill_result(structured_result_bytes(raw), expectation(max_chars=32))
    assert raised.value.outcome is PackagedSkillSemanticOutcomeV1.RESULT_SCHEMA_INVALID
```

- [ ] **Step 2: Run the result Reds**

Run:

```bash
.venv/bin/python -m pytest -q tests/skill/test_executable_results.py tests/skill/test_executable_receipts.py tests/sandbox/test_tools.py -rx
```

Expected: collection fails because the semantic decoder, packaged draft, and receipt do not exist.

- [ ] **Step 3: Implement one exhaustive semantic decoder, not a registry**

Create `agent/skill/executable_results.py`:

Import `StructuredReadbackOutcome` and `StructuredSandboxProcessDraftV1` from `agent.sandbox.contracts`; do not recreate either 020a type.

```python
class SkillOutputTypeV1(StrEnum):
    TEXT = "text"
    JSON = "json"


class PackagedSkillSemanticOutcomeV1(StrEnum):
    VALID = "valid"
    RESULT_KIND_MISMATCH = "result_kind_mismatch"
    RESULT_SCHEMA_INVALID = "result_schema_invalid"
    RESULT_LIMIT_EXCEEDED = "result_limit_exceeded"


class PackagedSkillResultError(ValueError):
    def __init__(
        self,
        outcome: PackagedSkillSemanticOutcomeV1,
        message: str,
    ) -> None:
        if outcome is PackagedSkillSemanticOutcomeV1.VALID:
            raise ValueError("valid is not an error outcome")
        super().__init__(message)
        self.outcome = outcome


@dataclass(frozen=True, slots=True)
class SkillResultExpectationV1:
    package_digest: str
    entrypoint_digest: str
    result_kind: SkillResultKindV1
    max_chars: int


@dataclass(frozen=True, slots=True)
class DecodedSkillResultV1:
    output_type: SkillOutputTypeV1
    projection: str
    value: JSONValue
    output_digest: str
    result_digest: str

    def identity_values(self) -> dict[str, JSONValue]:
        return {
            "output_type": self.output_type.value,
            "projection": self.projection,
            "value": self.value,
            "output_digest": self.output_digest,
            "result_digest": self.result_digest,
        }


def validate_json_value(value: object, *, depth: int = 0, nodes: list[int] | None = None) -> None:
    if nodes is None:
        nodes = [0]
    nodes[0] += 1
    if depth > 64 or nodes[0] > 10_000:
        raise PackagedSkillResultError(
            PackagedSkillSemanticOutcomeV1.RESULT_LIMIT_EXCEEDED,
            "JSON output exceeds structural limits",
        )
    if value is None or isinstance(value, str | bool | int):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise PackagedSkillResultError(
                PackagedSkillSemanticOutcomeV1.RESULT_SCHEMA_INVALID,
                "JSON output contains a non-finite number",
            )
        return
    if isinstance(value, list):
        for item in value:
            validate_json_value(item, depth=depth + 1, nodes=nodes)
        return
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        for item in value.values():
            validate_json_value(item, depth=depth + 1, nodes=nodes)
        return
    raise PackagedSkillResultError(
        PackagedSkillSemanticOutcomeV1.RESULT_SCHEMA_INVALID,
        "JSON output is not JSON-compatible",
    )


def decode_packaged_skill_result(
    draft: StructuredSandboxProcessDraftV1,
    expectation: SkillResultExpectationV1,
) -> DecodedSkillResultV1:
    try:
        return _decode_packaged_skill_result(draft, expectation)
    except PackagedSkillResultError:
        raise
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        RecursionError,
        TypeError,
        ValueError,
        OverflowError,
    ) as error:
        raise PackagedSkillResultError(
            PackagedSkillSemanticOutcomeV1.RESULT_SCHEMA_INVALID,
            "packaged Skill result is malformed",
        ) from error


def _decode_packaged_skill_result(
    draft: StructuredSandboxProcessDraftV1,
    expectation: SkillResultExpectationV1,
) -> DecodedSkillResultV1:
    if draft.readback_outcome is not StructuredReadbackOutcome.VALID:
        raise PackagedSkillResultError(
            PackagedSkillSemanticOutcomeV1.RESULT_SCHEMA_INVALID,
            "structured readback is not valid",
        )
    if draft.artifact_bytes is not None or draft.artifact_digest is not None:
        raise PackagedSkillResultError(
            PackagedSkillSemanticOutcomeV1.RESULT_KIND_MISMATCH,
            "skill-result-v1 cannot carry an artifact",
        )
    document = json.loads(
        draft.result_bytes.decode("utf-8", errors="strict"),
        parse_constant=lambda value: (_ for _ in ()).throw(
            PackagedSkillResultError(
                PackagedSkillSemanticOutcomeV1.RESULT_SCHEMA_INVALID,
                f"non-finite JSON constant: {value}",
            )
        ),
    )
    if not isinstance(document, dict):
        raise PackagedSkillResultError(
            PackagedSkillSemanticOutcomeV1.RESULT_SCHEMA_INVALID,
            "outer result must be an object",
        )
    if set(document) != {"kind", "payload", "protocol"}:
        raise PackagedSkillResultError(
            PackagedSkillSemanticOutcomeV1.RESULT_SCHEMA_INVALID,
            "outer result keys are invalid",
        )
    if document["protocol"] != "first-agent-skill-result-v1":
        raise PackagedSkillResultError(
            PackagedSkillSemanticOutcomeV1.RESULT_SCHEMA_INVALID,
            "outer result protocol is invalid",
        )
    if document["kind"] != "observation":
        raise PackagedSkillResultError(
            PackagedSkillSemanticOutcomeV1.RESULT_KIND_MISMATCH,
            "outer result kind is invalid",
        )
    if expectation.result_kind is not SkillResultKindV1.SKILL_RESULT:
        raise PackagedSkillResultError(
            PackagedSkillSemanticOutcomeV1.RESULT_KIND_MISMATCH,
            "result kind requires a closed extension",
        )
    payload = document["payload"]
    if not isinstance(payload, dict) or set(payload) != {"schema", "output"}:
        raise PackagedSkillResultError(
            PackagedSkillSemanticOutcomeV1.RESULT_SCHEMA_INVALID,
            "skill result payload is invalid",
        )
    if payload["schema"] != "skill-result-v1":
        raise PackagedSkillResultError(
            PackagedSkillSemanticOutcomeV1.RESULT_SCHEMA_INVALID,
            "skill result schema is invalid",
        )
    output = payload["output"]
    if not isinstance(output, dict) or set(output) != {"type", "value"}:
        raise PackagedSkillResultError(
            PackagedSkillSemanticOutcomeV1.RESULT_SCHEMA_INVALID,
            "skill result output is invalid",
        )
    output_type = SkillOutputTypeV1(output["type"])
    value = output["value"]
    if output_type is SkillOutputTypeV1.TEXT:
        if not isinstance(value, str):
            raise PackagedSkillResultError(
                PackagedSkillSemanticOutcomeV1.RESULT_SCHEMA_INVALID,
                "text output value must be a string",
            )
        projection = value
    else:
        validate_json_value(value)
        projection = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    if len(projection) > expectation.max_chars:
        raise PackagedSkillResultError(
            PackagedSkillSemanticOutcomeV1.RESULT_LIMIT_EXCEEDED,
            "skill result exceeds max_chars",
        )
    result_digest = hashlib.sha256(draft.result_bytes).hexdigest()
    return DecodedSkillResultV1(
        output_type=output_type,
        projection=projection,
        value=value,
        output_digest=hashlib.sha256(projection.encode("utf-8")).hexdigest(),
        result_digest=result_digest,
    )


def _decode_semantic(
    draft: StructuredSandboxProcessDraftV1,
    expectation: SkillResultExpectationV1,
) -> tuple[PackagedSkillSemanticOutcomeV1, DecodedSkillResultV1 | None]:
    try:
        decoded = decode_packaged_skill_result(draft, expectation)
    except PackagedSkillResultError as error:
        return error.outcome, None
    return PackagedSkillSemanticOutcomeV1.VALID, decoded
```

The public wrapper converts every UTF-8, JSON, closed-enum, numeric, overflow, and recursion failure to `PackagedSkillResultError` with exactly one non-`VALID` closed outcome; no raw parser exception crosses the seam. `_decode_semantic` is the only adapter-facing normalization and never catches non-semantic failures. Do not add `RESULT_DECODERS`, callback registration, `entry_points`, `singledispatch`, or string-to-callable maps. 022 extends the `if expectation.result_kind` branch with explicit imports and exhaustive branches in this same function.

- [ ] **Step 4: Add the typed draft and host receipt**

In `agent/skill/execution.py`, add:

```python
@dataclass(frozen=True, slots=True)
class StructuredSandboxToolDraftV1:
    process: StructuredSandboxProcessDraftV1
    semantic_outcome: PackagedSkillSemanticOutcomeV1
    result: DecodedSkillResultV1 | None
    package_digest: str
    entrypoint_digest: str
    draft_digest: str

    def identity_values(self) -> dict[str, JSONValue]:
        return {
            "process_draft_digest": self.process.draft_digest,
            "semantic_outcome": self.semantic_outcome.value,
            "result_digest": None if self.result is None else self.result.result_digest,
            "output_digest": None if self.result is None else self.result.output_digest,
            "package_digest": self.package_digest,
            "entrypoint_digest": self.entrypoint_digest,
        }
```

`__post_init__` requires `result` exactly when outcome is `VALID`, requires every digest to be bare lowercase hex64, and verifies `draft_digest == canonical_json_digest(identity_values())`. The wrapped `result` is a claim from the adapter, not Runtime evidence.

Add `SkillResultReceiptV1` to `agent/skill/executable_results.py` with exact fields `schema`, `package_digest`, `entrypoint_digest`, `structured_invocation_digest`, `result_digest`, `output_digest`, `sandbox_receipt_digest`, `intent_digest`, `receipt_digest`. `create` accepts only the Runtime-recomputed `DecodedSkillResultV1`, the exact parsed `PackagedSkillBindingV1`, the exact `ExecutionIntent`, and the already-minted sandbox receipt digest; it exact-compares package/entrypoint/result/structured-invocation identities before constructing its self digest. `from_payload` requires the exact field set and recomputes `receipt_digest`. The receipt carries no output value, path, package content, or child diagnostics.

- [ ] **Step 5: Normalize the packaged draft inside the existing Runtime owner**

Add one branch before the ordinary structured sandbox branch in `KernelToolRuntime.invoke`:

Import packaged contracts only with `from agent.skill.executable_contracts import ...`, `from agent.skill.executable_results import ...`, and `from agent.skill.execution import StructuredSandboxToolDraftV1`. Never use `from agent.skill import ...`; `agent.skill.__init__` must not import composition to satisfy these leaf imports.

```python
if isinstance(raw_result, StructuredSandboxToolDraftV1):
    return self._packaged_skill_outcome(intent, registration.spec, raw_result)
```

`_packaged_skill_outcome` must:

```python
def _packaged_skill_outcome(self, intent, spec, draft):
    if spec.safety_policy.get("kind") != "packaged_skill_entrypoint_v1":
        return ToolResult(
            tool_call_id=intent.tool_call_id,
            content="Ordinary tool returned a packaged Skill draft.",
            is_error=True,
            executed=True,
            metadata={"code": "sandbox_draft_forgery", "tool_identity": spec.identity_digest},
        )
    if canonical_json_digest(draft.identity_values()) != draft.draft_digest:
        raise IntentConflictError("packaged Skill draft digest mismatch")
    if draft.package_digest != intent.safety_binding.get("package_digest") or draft.entrypoint_digest != intent.safety_binding.get("entrypoint_digest"):
        raise IntentConflictError("packaged Skill draft identity mismatch")
    sandbox_result = self._structured_sandbox_outcome(intent, spec, draft.process)
    if sandbox_result.is_error or not sandbox_result.executed:
        return sandbox_result
    try:
        binding = PackagedSkillBindingV1.from_safety_binding(
            intent.safety_binding, intent.arguments
        )
    except (TypeError, ValueError) as error:
        raise IntentConflictError("packaged Skill binding is invalid") from error
    expectation = SkillResultExpectationV1(
        package_digest=binding.package_digest,
        entrypoint_digest=binding.entrypoint_digest,
        result_kind=binding.result_kind,
        max_chars=binding.result_max_chars,
    )
    try:
        recomputed = decode_packaged_skill_result(draft.process, expectation)
    except PackagedSkillResultError as error:
        code = {
            PackagedSkillSemanticOutcomeV1.RESULT_KIND_MISMATCH:
                "result_kind_mismatch",
            PackagedSkillSemanticOutcomeV1.RESULT_SCHEMA_INVALID:
                "result_schema_invalid",
            PackagedSkillSemanticOutcomeV1.RESULT_LIMIT_EXCEEDED:
                "result_limit_exceeded",
        }[error.outcome]
        return replace(
            sandbox_result,
            content="The packaged Skill produced an invalid structured result.",
            is_error=True,
            metadata={**sandbox_result.metadata, "code": code},
        )
    if (
        draft.semantic_outcome is not PackagedSkillSemanticOutcomeV1.VALID
        or draft.result is None
        or draft.result.identity_values() != recomputed.identity_values()
    ):
        return replace(
            sandbox_result,
            content="The packaged Skill result wrapper did not match sandbox readback.",
            is_error=True,
            metadata={
                **sandbox_result.metadata,
                "code": "packaged_skill_semantic_forgery",
            },
        )
    receipt = SkillResultReceiptV1.create(
        result=recomputed,
        binding=binding,
        intent=intent,
        sandbox_receipt_digest=str(sandbox_result.metadata["receipt_digest"]),
    )
    return replace(
        sandbox_result,
        content=recomputed.projection[:spec.output_limit_chars],
        metadata={
            **sandbox_result.metadata,
            "skill_result_receipt": receipt.to_payload(),
            "skill_result_receipt_digest": receipt.receipt_digest,
            "structured_result_digest": recomputed.result_digest,
            "untrusted_output": True,
        },
    )
```

This method calls the existing 020a receipt path exactly once, then invokes the sole decoder itself over `draft.process.result_bytes`. It never trusts adapter projection/value/digests, and it exact-compares the complete recomputed semantic identity before minting `SkillResultReceiptV1`. A valid semantic payload never bypasses sandbox authority; a valid sandbox exit never bypasses semantic validation.

- [ ] **Step 6: Verify Green and checkpoint commit**

Run:

```bash
.venv/bin/python -m pytest -q tests/skill/test_executable_results.py tests/skill/test_executable_receipts.py tests/sandbox/test_tools.py tests/kernel/test_tool_outcomes.py -rx
.venv/bin/ruff check agent/skill/executable_results.py agent/skill/execution.py agent/runtime/tools.py tests/skill tests/sandbox/test_tools.py
git diff --check
git add agent/skill/executable_results.py agent/skill/execution.py agent/runtime/tools.py tests/skill/test_executable_results.py tests/skill/test_executable_receipts.py tests/sandbox/test_tools.py
git commit -m "feat(skill): validate structured Skill results"
```

Expected: text/JSON are bounded and canonical, ordinary outputs cannot forge receipts, and only Runtime returns a result carrying both sandbox and Skill result receipt digests.

---

### Task 5: Implement the one packaged execution adapter over the 020a sandbox

**Files:**
- Modify: `agent/skill/execution.py`
- Modify: `agent/runtime/tools.py`
- Modify: `tests/skill/package_fixtures.py`
- Create: `tests/skill/test_executable_adapter.py`
- Create: `tests/skill/test_executable_outcomes.py`
- Modify: `tests/kernel/test_tool_outcomes.py`

**Interfaces:**
- `BindingPreparation = dict[str, JSONValue] | KnownNotExecuted`
- `PackagedSkillExecutionAdapter.prepare_binding(*, snapshot_digest, package, entrypoint, arguments, inputs=()) -> dict[str, JSONValue] | KnownNotExecuted`
- `PackagedSkillExecutionAdapter.execute(intent, binding) -> StructuredSandboxToolDraftV1 | KnownNotExecuted`
- One injected `NativeSandboxExecutor`; no constructor creates an executor.

- [ ] **Step 1: Write fixed-command, exact runner-wire, binding-normalization, single-spawn, and taxonomy Reds**

```python
def test_adapter_uses_fixed_runner_and_one_structured_execute_call() -> None:
    executor = RecordingNativeSandboxExecutor(valid_process_draft())
    adapter = packaged_adapter(executor=executor)
    binding = binding_fixture(adapter)
    result = adapter.execute(intent_fixture(binding), binding)
    assert isinstance(result, StructuredSandboxToolDraftV1)
    assert executor.calls == 1
    prepared, policy, io_plan = executor.last_call
    assert prepared.command.argv == (
        "-I", "-m", "first_agent_skill_runner",
        "--package", PACKAGE_DIGEST,
        "--entrypoint", "echo",
    )
    assert io_plan.inputs == ()
    assert io_plan.expected_result_kind is StructuredResultKind.OBSERVATION


def test_adapter_emits_the_exact_020a_runner_request() -> None:
    adapter = packaged_adapter(executor=RecordingNativeSandboxExecutor(valid_process_draft()))
    entrypoint = echo_entrypoint_fixture()
    components = adapter._prepare_components(
        snapshot_digest=ACTIVE_SNAPSHOT_DIGEST,
        package=active_package_fixture(),
        entrypoint=entrypoint,
        arguments={"text": "hello"},
        inputs=(),
    )
    limits = PackagedSkillResourceLimitsV1.for_profile(entrypoint.limits.value)
    script = entrypoint.script
    assert json.loads(components.io_plan.request_bytes) == {
        "protocol": "first-agent-skill-request-v1",
        "package_digest": PACKAGE_DIGEST,
        "entrypoint_id": "echo",
        "entrypoint_script": {
            "path": script.relative_path,
            "size": script.size_bytes,
            "sha256": script.sha256,
        },
        "arguments": {"text": "hello"},
        "inputs": [],
        "expected_result_kind": "observation",
        "resource_limits_digest": limits.limits_digest,
    }
    assert components.io_plan.request_digest == hashlib.sha256(
        components.io_plan.request_bytes
    ).hexdigest()
    assert components.input_descriptors_digest == canonical_json_digest([])
    assert components.resource_limits_digest == limits.limits_digest
    assert components.structured_invocation_digest == structured_invocation_digest(
        components.process, components.policy, components.io_plan
    )


def test_exact_adapter_request_is_accepted_by_the_real_020a_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = runner_contract_package(tmp_path)
    adapter = packaged_adapter(
        package_root=package,
        executor=RecordingNativeSandboxExecutor(valid_process_draft()),
    )
    components = adapter._prepare_components(
        snapshot_digest=ACTIVE_SNAPSHOT_DIGEST,
        package=active_package_fixture(object_root=package),
        entrypoint=echo_entrypoint_fixture(),
        arguments={"text": "wire-contract"},
        inputs=(),
    )
    descriptor = json.loads(components.io_plan.request_bytes)["entrypoint_script"]
    assert set(descriptor) == {"path", "size", "sha256"}
    script_bytes = (package / descriptor["path"]).read_bytes()
    assert descriptor["size"] == len(script_bytes)
    assert descriptor["sha256"] == hashlib.sha256(script_bytes).hexdigest()
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    session = create_structured_session(sessions, components.io_plan)
    monkeypatch.chdir(package)
    monkeypatch.setattr(skill_runner, "apply_hard_limits", lambda _digest: None)
    returned = skill_runner.run_request(Path(session.root) / "request.json")
    assert returned == {
        "kind": "observation",
        "payload": {
            "schema": "skill-result-v1",
            "output": {
                "type": "json",
                "value": {"echo": "wire-contract", "input_slots": []},
            },
        },
        "artifact": None,
    }
    readback = read_structured_session(session, components.io_plan)
    assert readback.outcome is StructuredReadbackOutcome.VALID
    expected_result_document = {
        "protocol": "first-agent-skill-result-v1",
        "kind": returned["kind"],
        "payload": returned["payload"],
    }
    assert readback.result_bytes == json.dumps(
        expected_result_document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    assert readback.artifact_bytes is None


def test_real_runner_rejects_script_descriptor_drift_before_compile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = runner_contract_package(tmp_path)
    adapter = packaged_adapter(
        package_root=package,
        executor=RecordingNativeSandboxExecutor(valid_process_draft()),
    )
    components = adapter._prepare_components(
        snapshot_digest=ACTIVE_SNAPSHOT_DIGEST,
        package=active_package_fixture(object_root=package),
        entrypoint=echo_entrypoint_fixture(),
        arguments={"text": "must-not-run"},
        inputs=(),
    )
    sessions = tmp_path / "drift-sessions"
    sessions.mkdir()
    session = create_structured_session(sessions, components.io_plan)
    script_path = package / "scripts" / "echo.py"
    script_path.chmod(0o700)
    script_path.write_bytes(b"raise AssertionError('ran')\n")
    monkeypatch.chdir(package)
    monkeypatch.setattr(skill_runner, "apply_hard_limits", lambda _digest: None)
    with pytest.raises(skill_runner.RunnerProtocolError, match="script descriptor"):
        skill_runner.run_request(Path(session.root) / "request.json")


def test_adapter_never_uses_ambient_interpreter_or_package_command() -> None:
    executor = RecordingNativeSandboxExecutor(valid_process_draft())
    adapter = packaged_adapter(executor=executor)
    binding = binding_fixture(adapter)
    result = adapter.execute(intent_fixture(binding), binding)
    assert isinstance(result, StructuredSandboxToolDraftV1)
    prepared, _, _ = executor.last_call
    assert prepared.command.executable_identity is not None
    assert prepared.command.executable_identity.resolved_path == RUNTIME_CLOSURE.interpreter_path
    assert prepared.command.executable_identity.resolved_path != "/usr/bin/python3"
    assert "/bin/sh" not in prepared.command.argv


@pytest.mark.parametrize(
    ("executor_result", "expected_code", "executed"),
    (
        (KnownNotExecuted("sandbox_unavailable", "unavailable"), "sandbox_unavailable", False),
        (spawn_failed_structured_draft(), "spawn_failed", False),
        (malformed_result_structured_draft(), "result_malformed", True),
        (nonzero_structured_draft(), "sandbox_process_error", True),
    ),
)
def test_adapter_outcome_taxonomy(executor_result, expected_code, executed) -> None:
    result = invoke_with_executor_result(executor_result)
    assert result.metadata["code"] == expected_code
    assert result.executed is executed


def test_prepare_normalizes_known_not_executed_without_invoking_callable() -> None:
    registration, callable_ = registration_with_binding_preparer(
        KnownNotExecuted("skill_package_revoked", "revoked")
    )
    result = runtime(registration).prepare(tool_call(), model_prepare_context())
    assert result.executed is False
    assert result.metadata["code"] == "skill_package_revoked"
    assert callable_.calls == 0


def test_invoke_normalizes_revalidation_rejection_before_callable() -> None:
    registration, callable_, preparer = mutable_binding_preparer()
    intent = approved_intent(runtime(registration).prepare(tool_call(), model_prepare_context()))
    preparer.result = KnownNotExecuted("prepared_invocation_drift", "drift")
    result = runtime(registration).invoke(intent)
    assert result.executed is False
    assert result.metadata["code"] == "prepared_invocation_drift"
    assert callable_.calls == 0


@pytest.mark.parametrize("bad", (None, [], "binding"))
def test_prepare_rejects_non_dict_non_known_binding(bad: object) -> None:
    registration, _ = registration_with_binding_preparer(bad)
    result = runtime(registration).prepare(tool_call(), model_prepare_context())
    assert result.executed is False
    assert result.metadata["code"] == "binding_failure"
```

The adapter/runner test imports `PackagedSkillResourceLimitsV1`, `StructuredReadbackOutcome`, `StructuredResultKind`, and `structured_invocation_digest` from `agent.sandbox.contracts`, `create_structured_session`/`read_structured_session` from `agent.sandbox.structured_session`, and `first_agent_skill_runner.__main__ as skill_runner`. `runner_contract_package` creates one temporary package containing the exact manifest-declared `scripts/echo.py` from `tests/skill/package_fixtures.py`; the test then uses the real 020a request parser/script loader/result writer. Only the hard-limit syscall is replaced because this in-process contract test must not lower the pytest worker's limits. The materialized E2M in Task 8 replaces nothing.

The helper writes this exact script and no other executable file:

```python
def run(arguments, inputs):
    return {
        "kind": "observation",
        "payload": {
            "schema": "skill-result-v1",
            "output": {
                "type": "json",
                "value": {
                    "echo": arguments["text"],
                    "input_slots": sorted(inputs),
                },
            },
        },
        "artifact": None,
    }
```

- [ ] **Step 2: Run the adapter Reds**

Run:

```bash
.venv/bin/python -m pytest -q tests/skill/test_executable_adapter.py tests/skill/test_executable_outcomes.py -rx
```

Expected: tests fail because the adapter does not emit the closed 020a request with an exact script descriptor, the real runner rejects a bare script path or descriptor drift before compile/exec, and Runtime does not yet normalize `KnownNotExecuted` from prepare/revalidation.

- [ ] **Step 3: Normalize the generic binding-preparer contract in the existing Runtime**

In `agent/runtime/tools.py`, import `KnownNotExecuted` from its 020a owner and make the existing binding seam exactly:

```python
BindingPreparation = dict[str, JSONValue] | KnownNotExecuted
BindingPreparer = Callable[[dict[str, JSONValue]], BindingPreparation]


def _normalize_binding_preparation(
    self,
    *,
    tool_call_id: str,
    prepared: object,
) -> dict[str, JSONValue] | ToolResult:
    if isinstance(prepared, KnownNotExecuted):
        return ToolResult(
            tool_call_id=tool_call_id,
            content=prepared.message,
            is_error=True,
            executed=False,
            metadata={"code": prepared.code},
        )
    if not isinstance(prepared, dict):
        return ToolResult(
            tool_call_id=tool_call_id,
            content="Tool binding preparation returned an invalid value.",
            is_error=True,
            executed=False,
            metadata={"code": "binding_failure"},
        )
    return prepared
```

Use it at the two existing call sites exactly:

```python
# KernelToolRuntime.prepare, before policy and approval construction
prepared = self._prepare_binding(
    registration,
    arguments,
    source_authority=context.source_authority,
)
normalized = self._normalize_binding_preparation(
    tool_call_id=call.tool_call_id,
    prepared=prepared,
)
if isinstance(normalized, ToolResult):
    return normalized
binding = normalized
_canonical_json(binding)


# KernelToolRuntime.invoke, before policy re-evaluation and callable invocation
prepared = self._prepare_binding(
    registration,
    intent.arguments,
    source_authority=intent.source_authority,
)
normalized = self._normalize_binding_preparation(
    tool_call_id=intent.tool_call_id,
    prepared=prepared,
)
if isinstance(normalized, ToolResult):
    return normalized
current_binding = normalized
if current_binding != intent.safety_binding:
    raise IntentConflictError("tool safety preconditions changed after preparation")
```

Change `_prepare_binding`'s return annotation to `BindingPreparation`; if the registration preparer returns `KnownNotExecuted`, return it before attempting the existing source-authority merge. Otherwise retain that merge byte-for-byte. Do not catch arbitrary exceptions, turn an unknown outcome into `KnownNotExecuted`, or add a Skill-specific condition to Runtime.

- [ ] **Step 4: Implement one component builder, exact revalidation, and one executor call**

In `agent/skill/execution.py`, use these 020a imports rather than local copies:

```python
from agent.process.preparation import PreparedProcessV1
from agent.sandbox.contracts import (
    PackagedSkillResourceLimitsV1,
    PackagedSkillSandboxPolicyV1,
    StructuredResultKind,
    StructuredSandboxInputV1,
    StructuredSandboxIoPlanV1,
    structured_invocation_digest,
)
from agent.sandbox.executor import NativeSandboxExecutor
from agent.sandbox.hermetic_runtime import prepare_hermetic_skill_process
from agent.sandbox.packaged_policy import build_packaged_skill_policy
```

Import `_decode_semantic`, `PackagedSkillSemanticOutcomeV1`, and `SkillResultExpectationV1` directly from their one leaf owner `agent.skill.executable_results`; do not reimplement the taxonomy in `execution.py`.

Use constructor injection only. `active_set` is the exact immutable 021 snapshot; `package.object_root.canonical_path` and `package.runtime_closure` are values in the complete 021-owned `MaterializedActivePackageV1`, not values reconstructed or loaded by 020b:

```python
@dataclass(frozen=True, slots=True)
class _PreparedPackagedComponentsV1:
    process: PreparedProcessV1
    policy: PackagedSkillSandboxPolicyV1
    io_plan: StructuredSandboxIoPlanV1
    request_digest: str
    input_descriptors_digest: str
    resource_limits_digest: str
    structured_invocation_digest: str


class PackagedSkillExecutionAdapter:
    def __init__(
        self,
        *,
        active_set: ActiveSkillSetV1,
        workspace_root: Path,
        temp_root: Path,
        state_root: Path,
        home_root: Path,
        system_runtime_roots: tuple[Path, ...],
        system_runtime_digest: str,
        private_roots: tuple[Path, ...],
        sandbox_executor: NativeSandboxExecutor,
    ) -> None:
        self._active_set = active_set
        self._workspace_root = workspace_root
        self._temp_root = temp_root
        self._state_root = state_root
        self._home_root = home_root
        self._system_runtime_roots = tuple(system_runtime_roots)
        self._system_runtime_digest = system_runtime_digest
        self._private_roots = tuple(private_roots)
        self._sandbox_executor = sandbox_executor

    def _prepare_components(
        self,
        *,
        snapshot_digest: str,
        package: MaterializedActivePackageV1,
        entrypoint: ExecutableEntrypointV1,
        arguments: Mapping[str, JSONValue],
        inputs: tuple[StructuredSandboxInputV1, ...] = (),
    ) -> _PreparedPackagedComponentsV1:
        del snapshot_digest
        resource_limits = PackagedSkillResourceLimitsV1.for_profile(
            entrypoint.limits.value
        )
        input_descriptors = [
            {
                "slot": item.slot,
                "size": len(item.content),
                "sha256": item.content_digest,
                "allowed_magic_hex": list(item.allowed_magic_hex),
            }
            for item in inputs
        ]
        request_document = {
            "protocol": "first-agent-skill-request-v1",
            "package_digest": package.active.package_digest,
            "entrypoint_id": entrypoint.name,
            "entrypoint_script": {
                "path": entrypoint.script.relative_path,
                "size": entrypoint.script.size_bytes,
                "sha256": entrypoint.script.sha256,
            },
            "arguments": dict(arguments),
            "inputs": input_descriptors,
            "expected_result_kind": StructuredResultKind.OBSERVATION.value,
            "resource_limits_digest": resource_limits.limits_digest,
        }
        request = json.dumps(
            request_document,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        process = prepare_hermetic_skill_process(
            package.runtime_closure,
            package_root=package.object_root.canonical_path,
            package_digest=package.active.package_digest,
            entrypoint_id=entrypoint.name,
        )
        policy = build_packaged_skill_policy(
            interpreter_path=package.runtime_closure.interpreter_path,
            runtime_roots=package.runtime_closure.readable_roots,
            workspace_root=self._workspace_root,
            package_root=package.object_root.canonical_path,
            temp_root=self._temp_root,
            system_runtime_roots=self._system_runtime_roots,
            state_root=self._state_root,
            home_root=self._home_root,
            private_roots=self._private_roots,
            runtime_closure_digest=package.runtime_closure.closure_digest,
            system_runtime_digest=self._system_runtime_digest,
            resource_limits=resource_limits,
        )
        io_plan = StructuredSandboxIoPlanV1(
            package_digest=package.active.package_digest,
            entrypoint_id=entrypoint.name,
            entrypoint_digest=entrypoint.entrypoint_digest,
            request_bytes=request,
            request_digest=hashlib.sha256(request).hexdigest(),
            inputs=tuple(inputs),
            result_cap_bytes=min(262_144, entrypoint.result.max_chars * 4 + 4_096),
            artifact_cap_bytes=1,
            aggregate_output_cap_bytes=min(
                262_145, entrypoint.result.max_chars * 4 + 4_097
            ),
            expected_result_kind=StructuredResultKind.OBSERVATION,
        )
        return _PreparedPackagedComponentsV1(
            process=process,
            policy=policy,
            io_plan=io_plan,
            request_digest=io_plan.request_digest,
            input_descriptors_digest=canonical_json_digest(input_descriptors),
            resource_limits_digest=resource_limits.limits_digest,
            structured_invocation_digest=structured_invocation_digest(
                process, policy, io_plan
            ),
        )

    def _binding_from_components(
        self,
        *,
        snapshot_digest: str,
        package: MaterializedActivePackageV1,
        entrypoint: ExecutableEntrypointV1,
        arguments: Mapping[str, JSONValue],
        components: _PreparedPackagedComponentsV1,
    ) -> dict[str, JSONValue]:
        values = {
            "active_snapshot_digest": snapshot_digest,
            "package_digest": package.active.package_digest,
            "storage_identity_digest": package.active.storage_identity_digest,
            "manifest_digest": package.manifest.manifest_digest,
            "requirements_digest": package.requirements.requirements_digest,
            "qualification_digest": package.active.qualification_digest,
            "entrypoint_id": entrypoint.name,
            "entrypoint_digest": entrypoint.entrypoint_digest,
            "script_descriptor_digest": entrypoint.script.descriptor_digest,
            "operation": entrypoint.operation.value,
            "format": entrypoint.format.value,
            "result_kind": entrypoint.result.kind.value,
            "result_max_chars": entrypoint.result.max_chars,
            "runtime_profile": entrypoint.limits.value,
            "network": entrypoint.network.value,
            "arguments_digest": canonical_json_digest(arguments),
            "request_digest": components.request_digest,
            "input_descriptors_digest": components.input_descriptors_digest,
            "resource_limits_digest": components.resource_limits_digest,
            "structured_invocation_digest": components.structured_invocation_digest,
            "command_fingerprint": components.process.command.command_fingerprint,
            "policy_instance_digest": components.policy.policy_digest,
            "sandbox_mode": components.policy.mode.value,
            "sandbox_network": components.policy.network.value,
        }
        binding = PackagedSkillBindingV1(**values)
        return binding.to_safety_binding()

    def prepare_binding(
        self,
        *,
        snapshot_digest: str,
        package: MaterializedActivePackageV1,
        entrypoint: ExecutableEntrypointV1,
        arguments: Mapping[str, JSONValue],
        inputs: tuple[StructuredSandboxInputV1, ...] = (),
    ) -> dict[str, JSONValue] | KnownNotExecuted:
        components = self._prepare_components(
            snapshot_digest=snapshot_digest,
            package=package,
            entrypoint=entrypoint,
            arguments=arguments,
            inputs=inputs,
        )
        return self._binding_from_components(
            snapshot_digest=snapshot_digest,
            package=package,
            entrypoint=entrypoint,
            arguments=arguments,
            components=components,
        )

    def execute(
        self,
        intent: ExecutionIntent,
        binding: PackagedSkillBindingV1,
    ) -> StructuredSandboxToolDraftV1 | KnownNotExecuted:
        if self._active_set.snapshot_digest != binding.active_snapshot_digest:
            return KnownNotExecuted(
                "package_identity_drift",
                "The active Skill package changed; restart and approve a fresh invocation.",
            )
        package = next(
            (
                item
                for item in self._active_set.packages
                if item.active.package_digest == binding.package_digest
                and item.active.storage_identity_digest
                == binding.storage_identity_digest
                and item.qualification.qualification_digest
                == binding.qualification_digest
            ),
            None,
        )
        if package is None:
            return KnownNotExecuted(
                "package_identity_drift",
                "The active Skill package changed; restart and approve a fresh invocation.",
            )
        if (
            package.manifest is None
            or package.requirements is None
            or package.runtime_closure is None
        ):
            return KnownNotExecuted(
                "package_identity_drift",
                "The active Skill is no longer executable; restart before invoking it.",
            )
        if (
            package.manifest.manifest_digest != binding.manifest_digest
            or package.requirements.requirements_digest != binding.requirements_digest
        ):
            return KnownNotExecuted(
                "package_identity_drift",
                "The executable Skill identity changed; restart and approve a fresh invocation.",
            )
        entrypoint = next(
            (
                item
                for item in package.manifest.entrypoints
                if item.name == binding.entrypoint_id
            ),
            None,
        )
        if (
            entrypoint is None
            or entrypoint.entrypoint_digest != binding.entrypoint_digest
            or entrypoint.script.descriptor_digest != binding.script_descriptor_digest
        ):
            return KnownNotExecuted(
                "package_identity_drift",
                "The packaged Skill entrypoint changed; restart and approve a fresh invocation.",
            )
        if any(parameter.kind not in {
            SkillParameterKindV1.TEXT,
            SkillParameterKindV1.INTEGER,
            SkillParameterKindV1.BOOLEAN,
            SkillParameterKindV1.JSON,
        } for parameter in entrypoint.parameters):
            return KnownNotExecuted(
                "artifact_extension_required",
                "This entrypoint requires the governed Artifact extension.",
            )
        components = self._prepare_components(
            snapshot_digest=binding.active_snapshot_digest,
            package=package,
            entrypoint=entrypoint,
            arguments=intent.arguments,
            inputs=(),
        )
        recomputed = self._binding_from_components(
            snapshot_digest=binding.active_snapshot_digest,
            package=package,
            entrypoint=entrypoint,
            arguments=intent.arguments,
            components=components,
        )
        if recomputed != intent.safety_binding:
            return KnownNotExecuted(
                "prepared_invocation_drift",
                "The packaged Skill invocation changed before spawn.",
            )
        process_draft = self._sandbox_executor.execute(
            components.process,
            components.policy,
            io_plan=components.io_plan,
        )
        if isinstance(process_draft, KnownNotExecuted):
            return process_draft
        expectation = SkillResultExpectationV1(
            package_digest=binding.package_digest,
            entrypoint_digest=binding.entrypoint_digest,
            result_kind=binding.result_kind,
            max_chars=binding.result_max_chars,
        )
        semantic_outcome, decoded = _decode_semantic(process_draft, expectation)
        values = {
            "process_draft_digest": process_draft.draft_digest,
            "semantic_outcome": semantic_outcome.value,
            "result_digest": None if decoded is None else decoded.result_digest,
            "output_digest": None if decoded is None else decoded.output_digest,
            "package_digest": binding.package_digest,
            "entrypoint_digest": binding.entrypoint_digest,
        }
        return StructuredSandboxToolDraftV1(
            process=process_draft,
            semantic_outcome=semantic_outcome,
            result=decoded,
            package_digest=binding.package_digest,
            entrypoint_digest=binding.entrypoint_digest,
            draft_digest=canonical_json_digest(values),
        )
```

`_PackagedSkillBindingPreparer` calls `prepare_binding` while holding the short 021 gate, then releases it; it returns either the exact JSON or `KnownNotExecuted`, which the generic Runtime normalization handles. `_prepare_components` is the one helper shared by prepare and invoke and the only runner request builder. Its request contains exactly the eight keys accepted by the 020a runner. It maps the strict host `ExecutableScriptDescriptorV1` explicitly as `{path: entrypoint.script.relative_path, size: entrypoint.script.size_bytes, sha256: entrypoint.script.sha256}`; `to_payload()` remains host identity serialization and is never a runner-wire encoder. The 020a runner opens wire `path` descriptor-relative with `O_NOFOLLOW`, reads it once under the wire `size` cap, exact-checks `size/sha256`, then compiles and executes those already-verified bytes without a second path lookup. Input descriptors contain exact `slot/size/sha256/allowed_magic_hex`; `resource_limits_digest` comes from `PackagedSkillResourceLimitsV1.for_profile(entrypoint.limits.value)`, and that same object is passed into policy compilation. The request digest therefore binds the complete script wire descriptor, arguments, input descriptors, expected kind, and limits; `structured_invocation_digest` additionally binds the process command, policy, caps, and input content identities. Invoke recomputes the complete `PackagedSkillBindingV1`, including the host `script_descriptor_digest`, and exact-compares all fields immediately before the single executor call. Do not expose `object_root`, closure paths, workspace root, temp/session path, request bytes, or raw result in draft, receipt, checkpoint, event, or context.

If the executor raises after spawn may have occurred, do not catch it. `EXTERNAL`/`WRITE` propagation enters the existing `AWAITING_RECOVERY`. Only `KnownNotExecuted` or `SPAWN_FAILED` prove zero effect. Nonzero/signal/reaped timeout and post-spawn result errors retain the Runtime-minted sandbox receipt and are terminal executed errors.

- [ ] **Step 5: Verify Green and checkpoint commit**

Run:

```bash
.venv/bin/python -m pytest -q tests/skill/test_executable_adapter.py tests/skill/test_executable_outcomes.py tests/kernel/test_tool_outcomes.py tests/sandbox/test_packaged_runner.py tests/sandbox/test_structured_executor.py tests/sandbox/test_tools.py tests/kernel/test_runtime_recovery.py -rx
.venv/bin/ruff check agent/skill/execution.py agent/runtime/tools.py tests/skill/package_fixtures.py tests/skill/test_executable_adapter.py tests/skill/test_executable_outcomes.py tests/kernel/test_tool_outcomes.py
git diff --check
git add agent/skill/execution.py agent/runtime/tools.py tests/skill/package_fixtures.py tests/skill/test_executable_adapter.py tests/skill/test_executable_outcomes.py tests/kernel/test_tool_outcomes.py
git commit -m "feat(skill): execute packages through structured sandbox"
```

Expected: the real 020a runner accepts the exact adapter request, both prepare and invoke normalize typed pre-effect rejections, exactly one 020a executor call occurs, no ambient process path exists, and every known/unknown outcome maps to the frozen taxonomy.

---

### Task 6: Close prepare/spawn drift, revocation, resource, and draft-forgery races

**Files:**
- Modify: `agent/skill/execution.py`
- Modify: `agent/skill/tools.py`
- Modify: `agent/runtime/tools.py`
- Modify: `tests/skill/package_fixtures.py`
- Create: `tests/skill/test_executable_drift.py`
- Create: `tests/skill/test_executable_resources.py`
- Create: `tests/skill/test_executable_forgery.py`
- Modify: `tests/kernel/test_tool_outcomes.py`

- [ ] **Step 1: Write the race and absence Reds**

```python
def test_revoke_before_invoke_guard_causes_zero_spawn() -> None:
    gate = TestSkillActivationGate(decision=None)
    runtime = runtime_with_entrypoint(gate=gate)
    intent = prepare_approved(runtime)
    gate.decision = ActivationGateDecisionV1.REVOKED
    result = runtime.invoke(intent)
    assert result.executed is False
    assert result.metadata["code"] == "skill_package_revoked"
    assert gate.spawn_calls == 0


def test_head_drift_between_short_prepare_guard_and_long_invoke_guard_requires_restart() -> None:
    gate = TestSkillActivationGate(decision=None)
    runtime = runtime_with_entrypoint(gate=gate)
    intent = prepare_approved(runtime)
    gate.snapshot_digest = "f" * 64
    result = runtime.invoke(intent)
    assert result.executed is False
    assert result.metadata["code"] == "skill_restart_required"
    assert gate.spawn_calls == 0


def test_long_execution_guard_spans_spawn_readback_and_semantic_validation() -> None:
    trace: list[str] = []
    result = invoke_traced_package(trace)
    assert result.is_error is False
    assert trace == [
        "acquire", "validate", "spawn", "readback",
        "semantic_validate", "receipt_draft", "release",
    ]


@pytest.mark.parametrize("operation", ("activation", "resource"))
@pytest.mark.parametrize(
    ("decision", "code"),
    (
        (ActivationGateDecisionV1.REVOKED, "skill_package_revoked"),
        (ActivationGateDecisionV1.RESTART_REQUIRED, "skill_restart_required"),
    ),
)
def test_packaged_content_fresh_invoke_guard_rejects_revoke_or_head_drift(
    operation: str,
    decision: ActivationGateDecisionV1,
    code: str,
) -> None:
    gate = TestSkillActivationGate(decision=None)
    registration, arguments = packaged_content_registration(operation, gate)
    binding = registration.prepare_binding(arguments)
    assert isinstance(binding, dict)
    gate.decision = decision
    result = registration.func(intent_fixture(binding, arguments=arguments))
    assert isinstance(result, KnownNotExecuted)
    assert result.code == code
    assert registration.func.catalog.read_calls == 0


@pytest.mark.parametrize("operation", ("activation", "resource"))
def test_packaged_content_invoke_sh_blocks_exclusive_until_bounded_read_finishes(
    operation: str,
) -> None:
    read_started = threading.Event()
    release_read = threading.Event()
    gate = BlockingTestSkillActivationGate()
    registration, arguments = blocking_packaged_content_registration(
        operation, gate, read_started, release_read,
    )
    binding = registration.prepare_binding(arguments)
    assert isinstance(binding, dict)
    gate.trace.clear()
    invocation = start_thread(
        lambda: registration.func(intent_fixture(binding, arguments=arguments))
    )
    assert read_started.wait(timeout=1.0)
    exclusive, exclusive_acquired = gate.start_exclusive()
    assert exclusive_acquired.wait(timeout=0.1) is False
    assert gate.trace == ["sh-acquire", "read-start", "ex-wait"]
    release_read.set()
    invocation.join(timeout=1.0)
    exclusive.join(timeout=1.0)
    assert not invocation.is_alive() and not exclusive.is_alive()
    assert exclusive_acquired.is_set()
    assert gate.trace == [
        "sh-acquire", "read-start", "ex-wait", "read-end", "sh-release", "ex-acquire",
    ]


def test_scripts_are_neither_listed_nor_readable_as_resources() -> None:
    activation = invoke_activation(packaged_catalog_with_script())
    assert all(not path.startswith("scripts/") for path in activation.resources)
    result = invoke_resource("echo-json", "scripts/echo.py")
    assert result.executed is False
    assert result.metadata["code"] == "skill_resource_denied"


def test_ordinary_isolated_tool_cannot_forge_packaged_draft() -> None:
    result = invoke_forged_packaged_draft(ordinary_isolated_registration())
    assert result.is_error is True
    assert result.metadata["code"] == "sandbox_draft_forgery"
    assert "skill_result_receipt" not in result.metadata
```

- [ ] **Step 2: Run the race Reds**

Run:

```bash
.venv/bin/python -m pytest -q tests/skill/test_executable_drift.py tests/skill/test_executable_resources.py tests/skill/test_executable_forgery.py -rx
```

Expected: the new files fail collection before the final race fixtures exist; once collected, any activation/resource callable that releases SH before its bounded catalog read fails the exclusive-order assertion.

- [ ] **Step 3: Add a deterministic shared/exclusive race fixture and keep the Task 3 callables as the sole production path**

Add this test-only guard to `tests/skill/package_fixtures.py`; it structurally implements the 021 protocol and models the same SH/EX exclusion without becoming a production gate:

```python
@dataclass(slots=True)
class _BlockingGuard:
    owner: BlockingTestSkillActivationGate
    released: bool = False

    def release(self) -> None:
        if self.released:
            raise RuntimeError("guard released twice")
        self.released = True
        with self.owner.condition:
            self.owner.readers -= 1
            self.owner.trace.append("sh-release")
            self.owner.condition.notify_all()


@dataclass(slots=True)
class BlockingTestSkillActivationGate:
    condition: threading.Condition = field(
        default_factory=lambda: threading.Condition(threading.Lock())
    )
    readers: int = 0
    trace: list[str] = field(default_factory=list)

    def acquire_execution_guard(self, **identity):
        assert set(identity) == {
            "expected_snapshot_digest", "package_digest",
            "storage_identity_digest", "qualification_digest",
        }
        with self.condition:
            self.readers += 1
            self.trace.append("sh-acquire")
        return _BlockingGuard(self)

    def start_exclusive(self) -> tuple[threading.Thread, threading.Event]:
        acquired = threading.Event()

        def acquire() -> None:
            with self.condition:
                self.trace.append("ex-wait")
                self.condition.wait_for(lambda: self.readers == 0, timeout=1.0)
                if self.readers != 0:
                    return
                self.trace.append("ex-acquire")
                acquired.set()

        thread = threading.Thread(target=acquire, daemon=True)
        thread.start()
        return thread, acquired


class CapturingThread(threading.Thread):
    def __init__(self, target: Callable[[], object]) -> None:
        super().__init__(target=self._capture, daemon=True)
        self._target_callable = target
        self.error: BaseException | None = None

    def _capture(self) -> None:
        try:
            self._target_callable()
        except BaseException as error:  # test helper must surface worker failure
            self.error = error

    def join(self, timeout: float | None = None) -> None:
        super().join(timeout)
        if self.error is not None:
            raise self.error


def start_thread(target: Callable[[], object]) -> CapturingThread:
    thread = CapturingThread(target)
    thread.start()
    return thread


@dataclass(slots=True)
class RecordingCatalog:
    inner: SkillCatalog
    read_calls: int = 0

    def read_activation(self, name: str):
        self.read_calls += 1
        return self.inner.read_activation(name)

    def read_resource(self, name: str, path: str):
        self.read_calls += 1
        return self.inner.read_resource(name, path)

    def descriptor_for(self, name: str):
        return self.inner.descriptor_for(name)


@dataclass(slots=True)
class BlockingCatalog:
    inner: SkillCatalog
    read_started: threading.Event
    release_read: threading.Event
    trace: list[str]

    def _block(self) -> None:
        self.trace.append("read-start")
        self.read_started.set()
        if not self.release_read.wait(timeout=1.0):
            raise TimeoutError("bounded test catalog read was not released")
        self.trace.append("read-end")

    def read_activation(self, name: str):
        self._block()
        return self.inner.read_activation(name)

    def read_resource(self, name: str, path: str):
        self._block()
        return self.inner.read_resource(name, path)

    def descriptor_for(self, name: str):
        return self.inner.descriptor_for(name)


def packaged_content_registration(operation, gate):
    active_set = active_set_fixture()
    registrations = build_packaged_skill_registrations(
        active_set,
        gate,
        recording_execution_adapter(active_set),
        max_tool_result_chars=8_000,
    )
    if operation == "activation":
        name = "skill__echo-json"
        arguments = {}
    elif operation == "resource":
        name = "skill__read_resource"
        arguments = {
            "skill_name": "echo-json",
            "path": "references/RESULTS.md",
        }
    else:
        raise ValueError("unknown packaged content operation")
    registration = next(item for item in registrations if item.spec.name == name)
    recording = RecordingCatalog(registration.func.catalog)
    return replace(
        registration,
        func=replace(registration.func, catalog=recording),
    ), arguments


def blocking_packaged_content_registration(
    operation, gate, read_started, release_read,
):
    registration, arguments = packaged_content_registration(operation, gate)
    blocking = BlockingCatalog(
        registration.func.catalog.inner,
        read_started,
        release_read,
        gate.trace,
    )
    return replace(
        registration,
        func=replace(registration.func, catalog=blocking),
    ), arguments
```

`blocking_packaged_content_registration` wraps the real packaged activation/resource registration from Task 3 and substitutes only the exact blocking catalog above. It does not replace either production callable or gate-acquisition call. `start_thread` captures and re-raises worker exceptions after `join`; a worker exception is a test failure, never a silent daemon outcome.

The Task 3 `activation_gate_rejection`, `_PackagedSkillBindingPreparer`, `_PackagedSkillCallable`, `_PackagedActivationCallable`, and `_PackagedResourceCallable` remain their sole definitions. Task 5's generic Runtime normalization preserves `KnownNotExecuted` as a typed pre-effect rejection instead of flattening it to `binding_failure`; this adds no Skill-specific Runtime policy. Immediate revalidation inside `KernelToolRuntime.invoke` remains before each callable's fresh acquisition. 022 later extends the same entrypoint callable return path through its host commit without adding a gate or executor.

Keep resource rejection in the existing catalog boundary. Never call `read_resource` for a `scripts/` path, even if the file is declared executable.

- [ ] **Step 4: Verify Green and checkpoint commit**

Run:

```bash
.venv/bin/python -m pytest -q tests/skill/test_executable_drift.py tests/skill/test_executable_resources.py tests/skill/test_executable_forgery.py tests/skill/test_tools.py tests/kernel/test_effect_ordering.py tests/kernel/test_runtime_recovery.py -rx
.venv/bin/ruff check agent/skill/execution.py agent/skill/tools.py agent/runtime/tools.py tests/skill tests/kernel/test_tool_outcomes.py
git diff --check
git add agent/skill/execution.py agent/skill/tools.py agent/runtime/tools.py tests/skill/package_fixtures.py tests/skill/test_executable_drift.py tests/skill/test_executable_resources.py tests/skill/test_executable_forgery.py tests/kernel/test_tool_outcomes.py
git commit -m "test(skill): close package execution races"
```

Expected: revoke/head/package/qualification/manifest/script-descriptor/request drift all fail before spawn; entrypoint and activation/resource SH guards span their entire bounded execution/read; EX mutation starts only after release; scripts remain executable-only, never readable resources.

---

### Task 7: Compose one immutable active set into the one Runtime and prove E2

**Files:**
- Create: `tests/fixtures/skills/echo-json/SKILL.md`
- Create: `tests/fixtures/skills/echo-json/first-agent.json`
- Create: `tests/fixtures/skills/echo-json/skill.requirements.json`
- Create: `tests/fixtures/skills/echo-json/scripts/echo.py`
- Create: `tests/fixtures/skills/echo-json/references/RESULTS.md`
- Modify: `tests/skill/package_fixtures.py`
- Create: `tests/skill/test_executable_integration.py`
- Create: `tests/skill/test_executable_reference_task.py`

- [ ] **Step 1: Write the 021-resource-consumption and run-turn E2 Reds before adding the fixture**

```python
def test_021_lifecycle_registrations_feed_the_only_runtime_once(tmp_path: Path) -> None:
    resources = materialize_echo_lifecycle_resources(tmp_path)
    composition = build_composition(
        provider=scripted_echo_provider(),
        checkpoint_store=recording_checkpoint_store(),
        tool_registrations=resources.registrations,
        event_sink=CollectingSink(),
        system_policy="policy",
        context_limits=ContextLimits(
            max_input_tokens=12_000,
            output_reserve=200,
            max_tool_result_chars=8_000,
        ),
        invocation_limits=InvocationLimits(),
        closeables=(resources.close,),
        workspace_identity_digest=WORKSPACE_DIGEST,
        context_scope_digest=CONTEXT_SCOPE_DIGEST,
    )
    assert isinstance(composition.tool_runtime, KernelToolRuntime)
    assert composition.runtime._tool_runtime is composition.tool_runtime
    names = [definition.name for definition in composition.tool_runtime.definitions()]
    assert names.count("skill__echo-json__echo") == 1
    assert resources.packaged_registrations[0] in resources.registrations


def test_e2_definition_to_context_uses_only_run_turn(
    request: pytest.FixtureRequest,
) -> None:
    listener = listening_loopback_socket()
    request.addfinalizer(listener.close)
    probe_port = listener.getsockname()[1]
    control = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    control.settimeout(2.0)
    control.connect(("127.0.0.1", probe_port))
    control.close()
    harness = executable_skill_harness(
        real_native_sandbox=False, probe_port=probe_port
    )
    first = harness.runtime.run_turn(harness.submit("echo hello"), harness.store.load())
    assert first.status is RunStatus.AWAITING_APPROVAL
    assert first.request is not None
    assert harness.spawn_calls == 0
    second = harness.runtime.run_turn(
        ResolveApproval(
            conversation_id=harness.conversation_id,
            action_seq=harness.store.state.next_action_seq,
            expected_revision=harness.store.state.revision,
            request_id=first.request.request_id,
            binding_digest=first.request.binding_digest,
            approved=True,
        ),
        harness.store.load(),
    )
    assert second.status is RunStatus.COMPLETED
    assert harness.spawn_calls == 1
    fact = harness.latest_tool_fact()
    assert json.loads(fact.content["content"]) == {
        "ambient_canary_visible": False,
        "echo": "hello",
        "input_slots": [],
        "network_connect_denied": False,
    }
    assert fact.content["metadata"]["sandbox_receipt_kind"] == "native_sandbox_v1"
    skill_receipt = fact.content["metadata"]["skill_result_receipt"]
    assert skill_receipt["schema"] == "skill-result-receipt-v1"
    approval_index = next(
        index
        for index, snapshot in enumerate(harness.store.snapshots)
        if snapshot.active_run is not None
        and snapshot.active_run.status is ActiveRunStatus.AWAITING_APPROVAL
    )
    executing_index = next(
        index
        for index, snapshot in enumerate(harness.store.snapshots)
        if snapshot.active_run is not None
        and snapshot.active_run.phase is ContinuationPhase.EXECUTING
    )
    result_index = next(
        index
        for index, snapshot in enumerate(harness.store.snapshots)
        if snapshot.facts
        and snapshot.facts[-1].content.get("metadata", {}).get(
            "skill_result_receipt_digest"
        )
    )
    assert approval_index < executing_index < result_index
    next_pack = harness.provider.calls[-1]
    assert "hello" in json.dumps(next_pack.messages)
    assert harness.provider.calls[-1].budget.included_ids
```

- [ ] **Step 2: Run the integration Reds and confirm the missing tracked package**

Run:

```bash
.venv/bin/python -m pytest -q tests/skill/test_executable_integration.py tests/skill/test_executable_reference_task.py -rx
```

Expected: both tests fail at fixture materialization with `FileNotFoundError: tests/fixtures/skills/echo-json`; they must not fail because 020b is trying to add another composition or gate.

- [ ] **Step 3: Add the real non-Artifact fixture and deterministic test harness**

Use this exact tracked `scripts/echo.py`. It can only return an observation; the package cannot choose a command, environment, or working directory:

```python
import errno
import os
import socket


def run(arguments, inputs):
    text = arguments["text"]
    probe_port = arguments["probe_port"]
    if not isinstance(text, str) or not isinstance(probe_port, int):
        raise ValueError("text/probe_port have invalid types")
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(2.0)
    try:
        probe.connect(("127.0.0.1", probe_port))
    except OSError as error:
        if error.errno not in {errno.EPERM, errno.EACCES}:
            raise
        network_connect_denied = True
    else:
        network_connect_denied = False
    finally:
        probe.close()
    return {
        "kind": "observation",
        "payload": {
            "schema": "skill-result-v1",
            "output": {
                "type": "json",
                "value": {
                    "ambient_canary_visible": os.environ.get(
                        "FIRST_AGENT_E2M_CANARY"
                    )
                    is not None,
                    "echo": text,
                    "input_slots": sorted(inputs),
                    "network_connect_denied": network_connect_denied,
                },
            },
        },
        "artifact": None,
    }
```

`first-agent.json` declares exactly one `echo` entrypoint with `operation: skill-read`, `format: generic`, publisher path `script: scripts/echo.py`, required `text` and bounded integer `probe_port` parameters, `result.kind: skill-result-v1`, `result.max_chars: 4096`, `limits.profile: skill-standard-v1`, and `network: off`. 021 transport resolves that path to the canonical inventory's exact `ExecutableScriptDescriptorV1(relative_path, size_bytes, sha256)` before calling the decoder. `skill.requirements.json` uses the exact portable Task 2 shape with `cpython-3.11`. `SKILL.md` contains `name: echo-json` matching manifest `package.name`; it contains no `version` frontmatter. The operator supplies `declared_version=1.0.0`, which 021 exact-matches to manifest `package.version=1.0.0`. `allowed-tools: Read` exists solely to prove it does not preapprove the spawn. `references/RESULTS.md` is readable; `scripts/echo.py` is absent from resources. The synthetic provider requests the listener's exact port, so the fake/unconfined E2 proves the control path can connect and returns `network_connect_denied: false`; only real E2M may prove denial.

In `tests/skill/package_fixtures.py`, make `materialize_echo_lifecycle_resources` use the public 021 import/qualify/stage/activate/materialize path and then call only `build_skill_lifecycle_resources(...)`. Its returned object is the test's sole source of `registrations`, `active_set`, `activation_gate`, and `close`. `executable_skill_harness` passes `resources.registrations` unchanged to `build_composition`, injects a recording checkpoint store and a scripted provider whose tool call contains exactly `{"text": "hello", "probe_port": probe_port}`, and exposes the already-created `composition.runtime`; it never calls `build_packaged_skill_registrations`, constructs `KernelToolRuntime`, or substitutes a second execution loop.

Use this non-vacuous control helper in both E2 and E2M:

```python
def listening_loopback_socket() -> socket.socket:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(8)
    return listener
```

- [ ] **Step 4: Verify Green and checkpoint commit**

Run:

```bash
.venv/bin/python -m pytest -q tests/skill/test_executable_integration.py tests/skill/test_executable_reference_task.py tests/skill/test_package_composition.py tests/skill/test_integration.py tests/kernel/test_reference_task.py -rx
.venv/bin/ruff check tests/skill/package_fixtures.py tests/skill/test_executable_integration.py tests/skill/test_executable_reference_task.py tests/fixtures/skills/echo-json/scripts/echo.py
git diff --check
git add tests/fixtures/skills/echo-json tests/skill/package_fixtures.py tests/skill/test_executable_integration.py tests/skill/test_executable_reference_task.py
git commit -m "test(skill): prove packaged Skill integration"
```

Expected: 020b consumes the already-complete 021 registrations without editing composition. The synthetic E2 starts at a model-visible ToolDefinition, pauses for approval with zero spawn, resumes only through `AgentRuntime.run_turn`, records `EXECUTING`, spawns once, persists both receipts in the result checkpoint, and places only bounded projection/metadata in the next ContextPack.

---

### Task 8: Prove materialized E2M, architecture absence, and capability truth

**Files:**
- Modify: `tests/skill/package_fixtures.py`
- Create: `tests/skill/test_executable_e2_materialized.py`
- Create: `tests/architecture/test_020b_packaged_skill_boundaries.py`
- Create: `docs/acceptance/020B_PACKAGED_EXECUTABLE_SKILLS_E2.md`
- Create: `docs/implementation/020B_EXECUTION_LOG.md`
- Modify: `docs/architecture/capabilities/SKILL_DESIGN.md`
- Modify: `docs/architecture/CURRENT_CAPABILITY_STATUS.md`
- Modify: `README.md`

- [ ] **Step 1: Write E2M and architecture Reds before changing capability prose**

```python
def test_materialized_e2m_runs_only_through_run_turn_and_real_seatbelt(
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    listener = listening_loopback_socket()
    request.addfinalizer(listener.close)
    probe_port = listener.getsockname()[1]
    monkeypatch.setenv("FIRST_AGENT_E2M_CANARY", "must-not-reach-child")
    control = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    control.settimeout(2.0)
    control.connect(("127.0.0.1", probe_port))
    control.close()
    harness = materialized_echo_harness(probe_port=probe_port)
    qualification = harness.qualify()
    assert qualification.available is True
    assert any(
        definition.name == "skill__echo-json__echo"
        for definition in harness.composition.tool_runtime.definitions()
    )

    paused = harness.runtime.run_turn(
        harness.submit("echo materialized"), harness.store.load()
    )
    assert paused.status is RunStatus.AWAITING_APPROVAL
    assert paused.request is not None
    assert harness.executor_calls == 0
    assert harness.native_spawn_calls == 0

    completed = harness.runtime.run_turn(
        ResolveApproval(
            conversation_id=harness.conversation_id,
            action_seq=harness.store.state.next_action_seq,
            expected_revision=harness.store.state.revision,
            request_id=paused.request.request_id,
            binding_digest=paused.request.binding_digest,
            approved=True,
        ),
        harness.store.load(),
    )
    assert completed.status is RunStatus.COMPLETED
    assert harness.executor_calls == 1
    assert harness.native_spawn_calls == 1

    fact = harness.latest_tool_fact()
    assert json.loads(fact.content["content"]) == {
        "ambient_canary_visible": False,
        "echo": "materialized",
        "input_slots": [],
        "network_connect_denied": True,
    }
    metadata = fact.content["metadata"]
    assert metadata["backend"] == "seatbelt"
    assert metadata["enforcement"] == "confined"
    assert metadata["network"] == "off"
    assert metadata["skill_result_receipt_digest"]
    approval_index = next(
        index
        for index, snapshot in enumerate(harness.store.snapshots)
        if snapshot.active_run is not None
        and snapshot.active_run.status is ActiveRunStatus.AWAITING_APPROVAL
    )
    executing_index = next(
        index
        for index, snapshot in enumerate(harness.store.snapshots)
        if snapshot.active_run is not None
        and snapshot.active_run.phase is ContinuationPhase.EXECUTING
    )
    result_index, result_snapshot = next(
        (index, snapshot)
        for index, snapshot in enumerate(harness.store.snapshots)
        if snapshot.facts
        and snapshot.facts[-1].content.get("metadata", {}).get(
            "skill_result_receipt_digest"
        )
    )
    assert approval_index < executing_index < result_index
    assert result_snapshot.facts[-1].content["metadata"][
        "skill_result_receipt_digest"
    ] == metadata["skill_result_receipt_digest"]
    next_pack = harness.provider.calls[-1]
    assert "materialized" in json.dumps(next_pack.messages)
    assert metadata["skill_result_receipt_digest"] not in json.dumps(
        next_pack.messages
    )


def test_020b_has_one_owner_and_no_dynamic_execution_surface() -> None:
    production = production_python_sources(exclude=("tui",))
    assert definitions(production, "PackagedSkillExecutionAdapter") == ["agent/skill/execution.py"]
    assert definitions(production, "build_packaged_skill_registrations") == ["agent/skill/tools.py"]
    assert definitions(production, "decode_packaged_skill_result") == ["agent/skill/executable_results.py"]
    assert definitions(production, "SkillActivationGate") == ["agent/skill/package_contracts.py"]
    assert definitions(production, "RepositorySkillActivationGate") == ["agent/skill/package_composition.py"]
    assert definitions(production, "run_turn") == ["agent/runtime/loop.py"]
    assert constructor_calls(production, "KernelToolRuntime") == ["agent/composition.py"]
    assert forbidden_tokens(production, {
        "RESULT_DECODERS", "register_result_decoder", "watchdog",
        "dynamic_registry", "run_skill", "shell=True", "os.system(",
    }) == []


def test_agent_skill_package_init_never_eagerly_imports_runtime_coupled_modules() -> None:
    tree = ast.parse(read("agent/skill/__init__.py"))
    forbidden = {
        "agent.skill.package_composition",
        "agent.skill.tools",
        "agent.skill.execution",
    }
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            prefix = "agent.skill." if node.level else ""
            module = prefix + (node.module or "")
            imported.add(module.rstrip("."))
            imported.update(
                f"{module}.{alias.name}".replace("..", ".")
                for alias in node.names
            )
    assert imported.isdisjoint(forbidden)


@pytest.mark.parametrize(
    "statement",
    (
        "import agent.runtime.tools; import agent.skill.package_composition",
        "import agent.skill.package_composition; import agent.runtime.tools",
    ),
)
def test_runtime_and_skill_composition_cold_import_in_both_orders(
    statement: str,
) -> None:
    project = Path(__file__).resolve().parents[2]
    completed = subprocess.run(
        [sys.executable, "-c", statement],
        cwd=project,
        env={
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONIOENCODING": "utf-8",
        },
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=10,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_allowed_tools_and_scripts_have_no_authority_path() -> None:
    skill_sources = production_sources_under("agent/skill")
    assert references_outside(skill_sources, "allowed_tools", allowed={"agent/skill/catalog.py"}) == []
    assert 'RESOURCE_DIRS = ("references", "assets")' in read("agent/skill/catalog.py")
    assert "scripts" not in resource_tool_allowed_roots()
```

The architecture helper functions are ordinary AST/text helpers implemented in the same test file; they ignore `tui/`, `.ua/`, `graphify-out/`, docs, fixtures, and generated files, and inspect only tracked production Python.

- [ ] **Step 2: Run the promotion Reds**

Run:

```bash
.venv/bin/python -m pytest -q tests/skill/test_executable_e2_materialized.py tests/architecture/test_020b_packaged_skill_boundaries.py -rx
```

Expected: E2M fails first because `materialized_echo_harness` is absent; after the harness exists it must still fail unless the real 020a runner/runtime closure/Seatbelt path hides the host canary and denies the child's actual `AF_INET` socket syscall. Architecture Reds identify any duplicate owner, eager `agent.skill` package import, cold import-order cycle, or forbidden surface. Do not skip E2M on the macOS promotion host; a failed local qualification is a blocker recorded in the execution log, not a pass.

- [ ] **Step 3: Add only a real-owner E2M harness**

In `tests/skill/package_fixtures.py`, `materialized_echo_harness` uses the public 021 import/qualify/stage/activate/materialize and `build_skill_lifecycle_resources(...)` path, the release-owned hermetic runtime closure, the production `NativeSandboxExecutor`, production Seatbelt confiner, production structured-session implementation, and `build_composition(tool_registrations=resources.registrations, closeables=(resources.close,), ...)`. It injects only the scripted model, recording store/sink, deterministic IDs/clock, and a spawn-counting wrapper around 020a's actual `run_local_process`; that wrapper must delegate exactly once and may not synthesize a process draft, readback, enforcement fact, receipt, or result. No environment map is passed by the test: the production executor constructs its closed child environment. No socket/process/network function is monkeypatched.

The unsandboxed control performs a successful `AF_INET/SOCK_STREAM connect()` to the exact loopback listener/port passed in the approved request, proving that endpoint is reachable outside confinement. The tracked child probe counts only `errno.EPERM` or `errno.EACCES` as policy denial; `ECONNREFUSED`, timeout, DNS errors, and every other `OSError` escape the script and fail E2M. The child boolean is accepted only together with (a) the exact tracked `scripts/echo.py` digest in the qualified package inventory, (b) the one real spawn/readback receipt chain, and (c) real Seatbelt enforcement facts. Metadata alone is not the denial oracle. Likewise the canary assertion is the tracked child probe plus the closed-environment executor path, not a manifest claim.

- [ ] **Step 4: Run the focused E2M Green before changing capability prose**

Run on the qualified macOS promotion host:

```bash
.venv/bin/python -m pytest -q tests/skill/test_executable_e2_materialized.py tests/architecture/test_020b_packaged_skill_boundaries.py -rx
```

Expected: complete exit 0; the trace proves definition → approval with zero spawn → durable `EXECUTING` → exactly one real spawn → fixed-inode readback → result checkpoint → next `ContextPack`, the child cannot see the ambient canary, and only `EPERM/EACCES` from a real connect counts as network denial. A skip, xfail, timeout, truncated output, unavailable Seatbelt qualification, `ECONNREFUSED`, or timeout is not Green.

- [ ] **Step 5: Record materialized evidence, then update capability docs**

Populate `docs/acceptance/020B_PACKAGED_EXECUTABLE_SKILLS_E2.md` with the exact fixture package/manifest/requirements/script digests, ToolSpec identity, structured invocation digest, sandbox receipt digest, Skill result receipt digest, checkpoint phase subsequence, expected tool fact, expected next ContextPack projection, successful unsandboxed socket control, canary-absence assertion, and the exact commands below. Populate `docs/implementation/020B_EXECUTION_LOG.md` with every observed Red reason, Green command/exit status, host qualification identity, deviations, and unresolved risk. Do not record raw package/result bytes, absolute paths, session paths, private roots, credentials, or the canary value.

Only after the E2M command exits 0, update capability prose to state exactly:

- instruction/resource Skill compatibility remains progressively disclosed;
- executable Skills require a closed `first-agent.json`, portable requirements, immutable active identity, exact invocation approval, and 020a structured native sandbox;
- `allowed-tools` is parsed display metadata and grants nothing;
- generic v1 results are only bounded text/JSON with sandbox plus Skill result receipts;
- package lifecycle persistence is 021 and Artifact PDF/Office/raster support is 022;
- no hot reload, remote registry, arbitrary scripts, network, OCR, visual model, or ambient dependency installation exists.

- [ ] **Step 6: Run the complete verification gate**

Run:

```bash
.venv/bin/python -m pytest -q tests/skill tests/sandbox/test_structured_contracts.py tests/sandbox/test_structured_session.py tests/sandbox/test_structured_executor.py tests/sandbox/test_tools.py tests/kernel/test_effect_ordering.py tests/kernel/test_runtime_recovery.py tests/architecture/test_020b_packaged_skill_boundaries.py tests/architecture/test_single_loop_static.py tests/architecture/test_dependency_dag.py tests/architecture/test_cutover_absence.py -rx
.venv/bin/python -m pytest -q tests/skill/test_executable_e2_materialized.py -rx
.venv/bin/ruff check .
.venv/bin/python -m pytest -q -rx
git diff --check
```

Expected: every command exits 0 with complete output. The materialized E2M uses the real 020a runner, native executor, Seatbelt enforcement, Runtime approval/effect ordering, Runtime-minted receipts, and next ContextPack; no test replaces the actual process/confinement owner.

- [ ] **Step 7: Run the final absence and unfinished-marker audit**

Run:

```bash
rg -n "TO[D]O|TB[D]|place[h]older|implement later|future decoder|dynamic decoder|configured baseline|hot reload|shell=True|os\.system\(|run_skill" agent/skill agent/runtime/tools.py agent/composition.py tests/skill tests/architecture/test_020b_packaged_skill_boundaries.py docs/acceptance/020B_PACKAGED_EXECUTABLE_SKILLS_E2.md docs/implementation/020B_EXECUTION_LOG.md
rg -n "class PackagedSkillExecutionAdapter|def build_packaged_skill_registrations|def decode_packaged_skill_result|class StructuredSandboxToolDraftV1|class KernelToolRuntime|def run_turn" agent
rg -n "allowed_tools" agent/skill agent/runtime agent/composition.py
rg -n "RESOURCE_DIRS|scripts/" agent/skill/catalog.py agent/skill/tools.py tests/skill/test_executable_resources.py
```

Expected: the first command has no production implementation hits; ownership output shows exactly one 020b owner for each named seam, one Runtime class, and one `run_turn`; `allowed_tools` appears only in catalog/display tests; resource roots remain `references/assets`.

- [ ] **Step 8: Checkpoint commit**

```bash
git add tests/skill/test_executable_e2_materialized.py tests/architecture/test_020b_packaged_skill_boundaries.py docs/acceptance/020B_PACKAGED_EXECUTABLE_SKILLS_E2.md docs/implementation/020B_EXECUTION_LOG.md docs/architecture/capabilities/SKILL_DESIGN.md docs/architecture/CURRENT_CAPABILITY_STATUS.md README.md
git commit -m "docs(skill): promote governed executable packages"
```

Expected: the final commit contains evidence-backed capability truth only; it does not claim 021 lifecycle persistence or 022 Artifact formats are complete.

## Definition of Done

- Official `allowed-tools` strings parse with explicit bounds; old lists and ambiguous whitespace fail; the value never influences authority.
- `first-agent.json` and `skill.requirements.json` have one closed decoder each, canonical identities, portable-only requirements, exact inventory-resolved script descriptors, and no arbitrary execution vocabulary; the runner receives no bare script path.
- 021 remains the only owner of `ActiveSkillSetV1`, `StoredPackageV1`, `QualificationRecordV1`, persistent lifecycle state, and the persistent gate; 020b consumes those identities without copying them.
- Every active executable entrypoint has one deterministic `RegisteredTool`/`ToolSpec` whose identity binds active/package/storage/manifest/requirements/qualification/entrypoint/operation/profile/network/runner facts.
- Instruction/resource progressive disclosure remains intact and no script is readable as a resource.
- `PackagedSkillExecutionAdapter` invokes the one 020a `NativeSandboxExecutor` exactly once with the fixed hermetic runner and structured I/O plan; there is no second executor, loop, Runtime, registry, or decoder map.
- `skill-result-v1` accepts only bounded text/canonical JSON. Success requires a valid structured process draft, sandbox receipt, semantic result, and Runtime-minted `SkillResultReceiptV1`; exit 0 or prose alone never completes evidence.
- Prepare and immediately-pre-spawn checks reject snapshot/package/storage/qualification/manifest/requirements/script-descriptor/request drift and revocation with zero spawn. Post-spawn malformed/nonzero outcomes retain executed-error receipts; unknown outcomes enter existing recovery.
- Static startup composition creates one registration tuple and one `KernelToolRuntime`; active-head changes require restart and never hot-refresh definitions.
- Synthetic E2 and real Seatbelt/hermetic E2M pass from ToolDefinition → approval → `EXECUTING` → one spawn → structured readback → receipts → result checkpoint → next ContextPack.
- Architecture absence tests prove no arbitrary runner, dynamic decoder registry, configured baseline, hot reload, scripts-as-resource, provider import, second loop, or second Runtime.
- Capability docs are updated only after all materialized evidence and repository-wide checks pass, and explicitly defer 021 persistence and 022 Artifact formats.
