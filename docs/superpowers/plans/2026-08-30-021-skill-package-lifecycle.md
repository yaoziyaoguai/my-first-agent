# 021 Skill Package Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver one governed, crash-safe Skill package lifecycle from explicit local source through immutable import, host qualification, stage, activation, update, revoke, rollback, restart, and the breaking mutable-root cutover.

**Architecture:** `agent.skill` owns portable package identities, the pure lifecycle planner, the immutable active-set schema, and operator-only registrations. `agent.skill_hosts` owns POSIX source traversal, content-addressed objects, the owner-only ledger, locking, fsync, and crash classification. Lifecycle callables are ordinary `RegisteredTool(exposure=OPERATOR)` values invoked only by the existing `AgentRuntime.run_turn` and `KernelToolRuntime`; the same ledger lock provides short prepare guards, shared execution guards, and exclusive lifecycle guards. Startup loads one immutable active snapshot and gives it to the 020 packaged-Skill registration builder; there is no plugin manager, hot reload, second loop, lifecycle approval store, or compatibility fallback.

**Tech Stack:** Python 3.11 stdlib (`dataclasses`, `enum`, `hashlib`, `json`, `zipfile`, `fcntl`, descriptor-relative `os` calls), the 020a operator-origin/structured-sandbox foundation, the 020b packaged-Skill registration/execution seam, pytest, Ruff, reproducible wheel/materialized-tree verification.

**Spec:** `docs/superpowers/specs/2026-08-30-governed-executable-skills-and-artifacts-design.md` §§3.2, 4–7, 11–15

## Global Constraints

- The only permitted dependency order is `020a complete → 021 Task 1 lifecycle/active-set contracts → 020b Tasks 1–6 executable contracts, adapter, and builder → 021 Tasks 2–11 lifecycle implementation/promotion → 020b Tasks 7–8 integration/promotion`. After 020b Task 6, 021 imports `ExecutableScriptDescriptorV1`, `ExecutableSkillManifestV1`, and `PortableRequirementsV1` only from `agent.skill.executable_contracts`, and imports `decode_executable_manifest`, `decode_portable_requirements`, `executable_manifest_digest`, and `portable_requirements_digest` only from `agent.skill.executable_codec`. It consumes `build_packaged_skill_registrations(active_set, activation_gate, execution_adapter, *, max_tool_result_chars)` and constructs the one `PackagedSkillExecutionAdapter(active_set=active_set, ...)` from their one 020b owner. 021 exclusively owns `ActiveSkillSetV1`, `MaterializedActivePackageV1`, `SkillActivationGate`, the active loader, and the only composition call; 020b Task 7 consumes `SkillLifecycleResources.registrations` and must not edit or rebuild composition. `agent.skill.__init__` remains leaf-only and never re-exports either composition owner.
- `AgentRuntime.run_turn` remains the only production model/tool loop and `ConversationState` writer. `KernelToolRuntime` remains the only tool callable owner. CLI builds typed `ExecuteOperatorTool` actions; it never invokes a planner, store, scanner, or callable directly.
- Lifecycle approval is the existing Runtime approval lease. Do not add a package approval/grant table, plugin manager, dynamic registry, daemon, provider call, credential resolver, or a second execution loop.
- V1 accepts only an explicit local directory or `.skillpkg` ZIP. Reject URL/HTTP/Git sources, remote TOFU, publisher-key discovery, postinstall hooks, shell commands, environment templates, ambient credentials, user site, `PYTHONPATH`, system Python fallback, and automatic dependency installation.
- The closed transport limits are `64 MiB` archive bytes, `10,000` entries, `32 MiB` per expanded file, `256 MiB` aggregate expanded bytes, `100:1` per-file compression ratio, `16` path components, and `1,024` UTF-8 bytes per relative path. Canonical modes are `0500` for directories/declared scripts and `0400` for all other regular files.
- The ZIP subset is UTF-8 canonical NFC relative names, stored/deflate only, regular file/directory only. Reject encryption, Zip64 records/extras, data descriptors, any extra field, duplicate names, absolute/empty/dot/dot-dot/backslash names, local/central mismatch, unsupported file type, Unicode NFC/casefold collision, and every bound violation. Validate both central-directory declarations and streamed expanded counters.
- Directory import uses the same `CanonicalPackageEntryV1` inventory and digest function as ZIP. It pins the root identity, walks descriptor-relative with no-follow opens, rejects symlink/hardlink/FIFO/device/socket/unknown entries, and revalidates root/ancestor/file identities before returning.
- Every package/storage/qualification/active/tool-set digest on the wire is exactly bare lowercase hex64 (`[0-9a-f]{64}`), matching 020a. No `sha256:` prefix, prefix stripping, dual parser, or compatibility encoding exists. `package_digest` is portable and binds canonical tree, `SKILL.md`, `first-agent.json` or the versioned no-executable marker, and the 020b-owned portable `skill.requirements.json` dependency lock. Host interpreter paths/inodes, sandbox identity, installed object identity, timestamps, and platform never enter it.
- `QualificationRecordV1` is host-owned, immutable, and exact. It binds package/storage identity, platform, architecture, hermetic closure, sandbox backend, packaged policy, resource limiter, and `qualified_at`; `qualification_digest` is always derived and is never trusted as an independently persisted field. Every staged, active, and history entry persists the complete qualification record and exposes its derived digest only as a property.
- Import materializes one immutable content-addressed object and does not mutate the lifecycle ledger. A crash after object rename creates an authority-free orphan. No task in 021 deletes objects or prunes the committed-action journal.
- `stage`, `activate`, `revoke`, `rollback`, `begin_cutover`, and `finalize_cutover` are distinct governed actions. Update is exactly `import(new digest) → stage(new digest) → activate(new stage)` with three Runtime approvals; do not add a combined `skill_package_update` tool or CLI-private saga.
- The ledger repository exposes one closed CAS result: `Applied`, `Conflict`, or `UnknownCommitError`. `Conflict` becomes `KnownNotExecuted`; `UnknownCommitError` must escape the callable so the existing durable `EXECUTING → AWAITING_RECOVERY` path owns resolution.
- Prepare holds only a short shared guard while reading the ledger. Packaged execution holds a shared guard from invoke revalidation through bounded child execution, structured read-back, and host commit. Lifecycle CAS and cutover scan hold the exclusive guard. Never upgrade a held shared guard to exclusive.
- Any ledger head drift from the startup snapshot returns `RESTART_REQUIRED`; activation never hot-adds or hot-removes definitions. Revoke blocks future prepare/spawn, waits for already-linearized shared invocations, and never claims to retract a process that already started.
- Activation compiles the complete proposed active set against every Runtime reserved name that would enter the next static composition. Reject byte-exact, NFC, casefold, length, activation/resource/entrypoint, and cross-package collisions before CAS. Forbidden-prefix validation applies only to generated packaged names; reserved lifecycle/operator names are collision authority, not invalid generated output.
- Cutover is breaking. The legacy gate is repository-backed, never a startup copy: prepare takes a short SH/read/releases, invoke takes a fresh SH/read and holds it through the bounded legacy activation/resource read, and begin/finalize use the same EX domain as lifecycle CAS. `begin_cutover` atomically persists `legacy_prepare_disabled_epoch` before scanning; same-process prepares then fail closed immediately while cancel/recovery remains available. Any restart that observes the durable disabled epoch, including a crash after begin or activation but before finalize, does not load the mutable catalog, does not construct legacy registrations, and excludes their names from collision authority. `finalize_cutover` is allowed only after a bounded full checkpoint scan is drained and exact managed packaged identities are restart-verifiable. Afterwards `--skill-root` returns an actionable migration error and is never scanned or imported implicitly.
- All state/package/trust directories are outside the workspace, owner `uid`, exact mode `0700`, descriptor pinned, and no-follow. Ledger/journal files are regular owner-only `0600`, `nlink == 1`; immutable object directories/files use the canonical modes above. No absolute/private path is emitted to model context, events, receipts, or normal CLI output.
- Do not read or modify `agent/tui/`, untracked files, secrets, credentials, `.env`, `.ua/`, or `graphify-out/`. Do not alter 022 artifact schemas or implement PDF/Office/image packages in this plan.
- Follow Red → focused failing run → minimum Green → focused passing run for every task. After every Green, run touched Ruff and `git diff --check`, then make the exact local checkpoint commit listed by that task; do not push or tag.

## File Responsibilities

- Create `agent/skill/package_contracts.py`: closed immutable package, source, storage, qualification, complete materialized active-set, activation-gate, lifecycle action/plan, cutover, journal, CAS, and guard contracts plus bare-hex canonical digest helpers. It does not define executable manifest or portable-requirements contracts.
- Create `agent/skill/package_transport.py`: canonical relative-name/role/mode validation, ZIP-subset decode, shared inventory/package identity, and directory-scan result validation. It imports executable manifest/requirements/script-descriptor contracts and codecs only from the exact 020b modules frozen above, derives byte-sorted `ExecutableScriptDescriptorV1` values from canonical inventory, and contains no duplicate codec, reverse dependency, filesystem traversal, or store mutation.
- Create `agent/skill/package_store.py`: strict ledger codec, pure state transitions, repository/object-source protocols, deterministic conformance adapters, and `SkillPackagePlanner` implementation; no POSIX imports.
- Create `agent/skill/package_tools.py`: the eight operator-only registrations and lifecycle prepare/invoke callables; no Runtime/checkpoint mutation and no direct process spawn.
- Create `agent/skill/package_composition.py`: the only startup `ActiveSkillSetV1` loader, concrete `SkillActivationGate`, static registration assembly, full-set collision compiler, and repository-backed legacy prepare/invoke gate adapter. It reads cutover state before any optional mutable-catalog loader and composes no legacy registration once the durable prepare-disable epoch exists; no dynamic registration or second composition owner.
- Create `agent/skill/cutover.py`: bounded checkpoint classifier and pure drain decision over already-loaded snapshots.
- Create `agent/skill_hosts/__init__.py`: explicit host adapter exports only.
- Create `agent/skill_hosts/posix_packages.py`: no-follow local-directory/ZIP candidate source, immutable content-addressed object writer/read-back, POSIX shared/exclusive guard, owner-only ledger/journal CAS, and restart reconciliation.
- Modify `agent/skill/catalog.py`: reuse descriptor/frontmatter parsing from canonical stored entries and make legacy prepare consult the durable cutover gate; do not retain a parallel mutable identity implementation.
- Modify `agent/skill/tools.py`: add the repository-backed gate around legacy activation/resource behavior only until final cutover; it does not consume active packages or call the 020b builder.
- Keep `agent/skill/__init__.py` leaf-only: it must not import or re-export `package_composition`, `build_skill_lifecycle_resources`, the 020b builder, or concrete POSIX internals. Runtime/composition callers import exact leaf modules.
- Modify `agent/composition.py`: accept one already-built `SkillLifecycleResources`, append its complete `registrations` tuple once, and include active-set/snapshot digests in the fixed authority snapshot. It never calls the 020b builder itself.
- Modify `agent/continuity/sessions.py`: add a bounded state-root checkpoint enumerator used only by cutover; preserve the current workspace-session owner and no-follow checks.
- Modify `agent/runtime/contracts.py`, `agent/runtime/state.py`, `agent/runtime/checkpoint.py`, `agent/runtime/tools.py`, and `agent/runtime/loop.py`: persist exact `tool_identity` plus one generic opaque recovery binding, and let the existing `KernelToolRuntime` dispatch unknown-outcome reconciliation to the exact registration; Runtime never parses lifecycle payloads, recognizes lifecycle names, or replays a callable.
- Modify `agent/cli/actions.py`: build exact lifecycle `ExecuteOperatorTool` actions from parsed operator input and current Goal-bound state.
- Modify `agent/cli/app.py`: render redacted lifecycle results through the existing Runtime result path; do not call lifecycle services.
- Modify `main.py`: add closed `first-agent skill inspect|import|stage|activate|revoke|rollback|begin-cutover|finalize-cutover` subcommands, construct the lifecycle environment before static tool composition, reject post-cutover `--skill-root`, and route one typed operator action through `run_headless`.
- Modify `tests/architecture/test_cutover_absence.py`: admit only the new `agent.skill_hosts` package/files and preserve the unique Provider/Tool/checkpoint ownership assertions.
- Create focused tests under `tests/skill/`, `tests/skill_hosts/`, `tests/cli/`, and `tests/reference/`; create `scripts/run_021_e2.py`, `scripts/verify_021_materialized_tree.py`, `docs/acceptance/021_SKILL_PACKAGE_LIFECYCLE_E2.md`, and `docs/implementation/021_EXECUTION_LOG.md`.

---

### Task 1: Freeze portable identities, lifecycle state, and closed codecs

**Files:**
- Create: `agent/skill/package_contracts.py`
- Create: `tests/skill/test_package_contracts.py`
- Create: `docs/acceptance/021_SKILL_PACKAGE_LIFECYCLE_E2.md`
- Create: `docs/implementation/021_EXECUTION_LOG.md`

**Interfaces:**
- `CanonicalPackageEntryV1(relative_path, role, canonical_mode, size_bytes, sha256)`
- `PackageIdentityV1(name, version, tree_digest, manifest_digest, skill_digest, requirements_digest, package_digest)`
- `StoredPackageV1(package, storage_identity_digest, object_root_descriptor_digest, inventory)`
- `QualificationRecordV1(package_digest, storage_identity_digest, platform, architecture, hermetic_runtime_closure_digest, sandbox_backend_identity, packaged_skill_policy_digest, resource_limiter_identity, qualified_at)` with derived `qualification_digest`, and `BundledReleaseAuthorityV1(application_identity_digest, sealed_installed_manifest_digest, bundled_package_digests, authority_digest)`
- `ActivePackageV1`, `StagedPackageV1`, and `HistoryEntryV1` each contain `qualification: QualificationRecordV1`; their `qualification_digest` accessors delegate to the record's derived digest. `RevocationTombstoneV1`, `CommittedActionV1`, `CutoverStateV1`, and `SkillPackageSnapshotV1` complete the ledger schema.
- `PackageObjectRootV1`, `MaterializedActivePackageV1(active, stored, qualification, object_root, descriptor, manifest, requirements, runtime_closure)`, and `ActiveSkillSetV1(snapshot_digest, instruction_catalog, packages, active_set_digest)` are 021-owned. `manifest` and `requirements` use postponed 020b annotations; Task 1 has no runtime import from 020b.
- `SkillActivationGate.acquire_execution_guard(*, expected_snapshot_digest, package_digest, storage_identity_digest, qualification_digest) -> SkillExecutionGuardV1 | ActivationGateDecisionV1`
- Closed `SkillLifecycleKind`, `TrustBasis`, `CASDisposition`, `ActivationGateDecisionV1`, and typed `SkillLifecycleActionV1`/`SkillLifecyclePlanV1` unions.

- [ ] **Step 1: Write digest-domain and immutable-schema Reds**

```python
def test_package_digest_is_portable_and_qualification_is_host_owned() -> None:
    package = package_identity()
    mac = qualification(package, platform="darwin", architecture="arm64")
    linux = qualification(package, platform="linux", architecture="x86_64")
    assert mac.package_digest == linux.package_digest == package.package_digest
    assert mac.qualification_digest != linux.qualification_digest


def test_snapshot_rejects_unsorted_or_duplicate_monotonic_members() -> None:
    tombstone = RevocationTombstoneV1("a" * 64, 7, "action-7")
    with pytest.raises(ValueError, match="revocations"):
        snapshot(revocations=(tombstone, tombstone))


@pytest.mark.parametrize("invalid", [
    "sha256:" + "a" * 64,
    "A" * 64,
    "a" * 63,
    "a" * 65,
])
def test_every_wire_digest_requires_bare_lowercase_hex64(invalid: str) -> None:
    with pytest.raises(ValueError, match="digest"):
        package_identity(package_digest=invalid)
    with pytest.raises(ValueError, match="digest"):
        qualification(package_digest=invalid)


def test_staged_active_and_history_round_trip_complete_qualification() -> None:
    original = snapshot_with_every_member()
    encoded = json.dumps(
        original.to_payload(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    decoded = SkillPackageSnapshotV1.from_payload(json.loads(encoded))
    expected = qualification()
    assert decoded.staged[0].qualification == expected
    assert decoded.active[0].qualification == expected
    assert decoded.history[0].qualification == expected
    assert decoded.active[0].qualification_digest == expected.qualification_digest
    assert b'"qualification_digest"' not in encoded


def test_active_skill_set_binds_materialized_identities_but_not_raw_fd() -> None:
    first = instruction_only_active_set(directory_fd=11)
    same_identity_other_fd = instruction_only_active_set(directory_fd=22)
    drifted_root = instruction_only_active_set(
        directory_fd=22,
        object_root_descriptor_digest="f" * 64,
    )
    assert first.packages[0].descriptor.identity_digest
    assert first.packages[0].manifest is None
    assert first.packages[0].requirements is None
    assert first.packages[0].runtime_closure is None
    assert first.active_set_digest == same_identity_other_fd.active_set_digest
    assert first.active_set_digest != drifted_root.active_set_digest


def test_lifecycle_plan_binds_action_head_preview_and_next_state() -> None:
    plan = lifecycle_plan()
    assert plan.plan_digest == canonical_digest({
        "action_id": plan.action_id,
        "expected_snapshot_token": plan.expected_snapshot_token,
        "expected_snapshot_digest": plan.expected_snapshot_digest,
        "next_snapshot_digest": plan.next_snapshot_digest,
        "preview_digest": plan.preview_digest,
        "action": plan.action.to_payload(),
    }, domain="skill-lifecycle-plan-v1")
```

- [ ] **Step 2: Run the contract Reds**

Run: `.venv/bin/python -m pytest -q tests/skill/test_package_contracts.py -rx`

Expected: collection fails with `ModuleNotFoundError: No module named 'agent.skill.package_contracts'`.

- [ ] **Step 3: Implement the minimum Green: closed contracts and domain-separated digests**

```python
HEX64 = re.compile(r"[0-9a-f]{64}\Z")


def canonical_digest(value: JSONValue, *, domain: str) -> str:
    payload = json.dumps(
        {"domain": domain, "value": value},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class PackageRole(StrEnum):
    DIRECTORY = "directory"
    SKILL = "skill"
    MANIFEST = "manifest"
    REQUIREMENTS = "requirements"
    SCRIPT = "script"
    REFERENCE = "reference"
    ASSET = "asset"


class TrustBasis(StrEnum):
    BUNDLED_RELEASE = "bundled_release"
    EXACT_LOCAL_APPROVAL = "exact_local_approval"


class SkillLifecycleKind(StrEnum):
    INSPECT_SOURCE = "inspect_source"
    IMPORT = "import"
    STAGE = "stage"
    ACTIVATE = "activate"
    REVOKE = "revoke"
    ROLLBACK = "rollback"
    BEGIN_CUTOVER = "begin_cutover"
    FINALIZE_CUTOVER = "finalize_cutover"


class ActivationGateDecisionV1(StrEnum):
    REVOKED = "revoked"
    RESTART_REQUIRED = "restart_required"


@runtime_checkable
class SkillExecutionGuardV1(Protocol):
    def release(self) -> None:
        """恰好释放一次同一 repository lock domain 的 SH guard。"""


@dataclass(frozen=True, slots=True)
class CanonicalPackageEntryV1:
    relative_path: str
    role: PackageRole
    canonical_mode: int
    size_bytes: int
    sha256: str

    def __post_init__(self) -> None:
        expected_mode = 0o500 if self.role in {PackageRole.DIRECTORY, PackageRole.SCRIPT} else 0o400
        if self.canonical_mode != expected_mode or self.size_bytes < 0 or not HEX64.fullmatch(self.sha256):
            raise ValueError("invalid canonical package entry")


@dataclass(frozen=True, slots=True)
class QualificationRecordV1:
    package_digest: str
    storage_identity_digest: str
    platform: str
    architecture: str
    hermetic_runtime_closure_digest: str
    sandbox_backend_identity: str
    packaged_skill_policy_digest: str
    resource_limiter_identity: str
    qualified_at: str
    qualification_digest: str = field(init=False)

    def __post_init__(self) -> None:
        for value in (
            self.package_digest,
            self.storage_identity_digest,
            self.hermetic_runtime_closure_digest,
            self.sandbox_backend_identity,
            self.packaged_skill_policy_digest,
            self.resource_limiter_identity,
        ):
            if not HEX64.fullmatch(value):
                raise ValueError("qualification contains an invalid digest")
        object.__setattr__(self, "qualification_digest", canonical_digest(self.to_payload(), domain="skill-qualification-v1"))


@dataclass(frozen=True, slots=True)
class ActivePackageV1:
    name: str
    version: str
    package_digest: str
    storage_identity_digest: str
    qualification: QualificationRecordV1
    trust_basis: TrustBasis
    trust_binding_digest: str
    activated_revision: int

    @property
    def qualification_digest(self) -> str:
        return self.qualification.qualification_digest


@dataclass(frozen=True, slots=True)
class StagedPackageV1:
    stage_id: str
    name: str
    version: str
    package_digest: str
    storage_identity_digest: str
    qualification: QualificationRecordV1
    staged_revision: int

    @property
    def qualification_digest(self) -> str:
        return self.qualification.qualification_digest


@dataclass(frozen=True, slots=True)
class HistoryEntryV1:
    history_id: str
    name: str
    version: str
    package_digest: str
    storage_identity_digest: str
    qualification: QualificationRecordV1
    trust_basis: TrustBasis
    trust_binding_digest: str
    superseded_revision: int

    @property
    def qualification_digest(self) -> str:
        return self.qualification.qualification_digest


@dataclass(frozen=True, slots=True)
class PackageObjectRootV1:
    package_digest: str
    storage_identity_digest: str
    object_root_descriptor_digest: str
    canonical_path: Path = field(repr=False, compare=False)
    directory_fd: int = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if any(not HEX64.fullmatch(value) for value in (
            self.package_digest,
            self.storage_identity_digest,
            self.object_root_descriptor_digest,
        )):
            raise ValueError("active object root contains an invalid digest")
        if self.directory_fd < 0:
            raise ValueError("active object root requires an opened directory descriptor")


@dataclass(frozen=True, slots=True)
class MaterializedActivePackageV1:
    active: ActivePackageV1
    stored: StoredPackageV1
    qualification: QualificationRecordV1
    object_root: PackageObjectRootV1
    descriptor: "SkillDescriptor"
    manifest: "ExecutableSkillManifestV1 | None"
    requirements: "PortableRequirementsV1 | None"
    runtime_closure: "HermeticRuntimeClosureV1 | None"

    def __post_init__(self) -> None:
        if (
            self.active.qualification != self.qualification
            or self.stored.package.package_digest != self.active.package_digest
            or self.stored.package.name != self.active.name
            or self.stored.package.version != self.active.version
            or self.qualification.package_digest != self.active.package_digest
            or self.qualification.storage_identity_digest
            != self.object_root.storage_identity_digest
            or self.stored.storage_identity_digest != self.active.storage_identity_digest
            or self.object_root.package_digest != self.active.package_digest
            or self.object_root.storage_identity_digest != self.active.storage_identity_digest
        ):
            raise ValueError("materialized active package identity mismatch")
        if self.descriptor.name != self.active.name:
            raise ValueError("materialized SKILL name mismatch")
        if self.manifest is not None and (
            self.manifest.package_name != self.active.name
            or self.manifest.package_version != self.active.version
            or self.manifest.manifest_digest != self.stored.package.manifest_digest
        ):
            raise ValueError("materialized executable identity mismatch")
        if (self.manifest is None) != (self.requirements is None):
            raise ValueError("manifest and requirements presence must match")
        if self.manifest is None and self.runtime_closure is not None:
            raise ValueError("instruction-only package cannot carry a runtime closure")
        if self.manifest is not None and self.runtime_closure is None:
            raise ValueError("executable package requires a qualified runtime closure")
        if self.requirements is not None and (
            self.requirements.requirements_digest
            != self.stored.package.requirements_digest
        ):
            raise ValueError("materialized requirements identity mismatch")
        if self.runtime_closure is not None and (
            self.runtime_closure.closure_digest
            != self.qualification.hermetic_runtime_closure_digest
        ):
            raise ValueError("materialized runtime closure identity mismatch")

    def identity_payload(self) -> dict[str, JSONValue]:
        return {
            "name": self.active.name,
            "version": self.active.version,
            "package_digest": self.active.package_digest,
            "storage_identity_digest": self.qualification.storage_identity_digest,
            "qualification_digest": self.qualification.qualification_digest,
            "trust_basis": self.active.trust_basis.value,
            "trust_binding_digest": self.active.trust_binding_digest,
            "stored_object_root_descriptor_digest": self.stored.object_root_descriptor_digest,
            "descriptor_identity_digest": self.descriptor.identity_digest,
            "manifest_digest": self.stored.package.manifest_digest,
            "requirements_digest": self.stored.package.requirements_digest,
            "runtime_closure_digest": (
                self.runtime_closure.closure_digest
                if self.runtime_closure is not None
                else None
            ),
            "object_root_package_digest": self.object_root.package_digest,
            "object_root_storage_identity_digest": self.object_root.storage_identity_digest,
            "object_root_descriptor_digest": self.object_root.object_root_descriptor_digest,
        }


@dataclass(frozen=True, slots=True)
class ActiveSkillSetV1:
    snapshot_digest: str
    instruction_catalog: "SkillCatalog"
    packages: tuple[MaterializedActivePackageV1, ...]
    active_set_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not HEX64.fullmatch(self.snapshot_digest):
            raise ValueError("active snapshot digest must be bare lowercase hex64")
        expected_packages = tuple(sorted(self.packages, key=lambda item: item.active.name.encode()))
        if self.packages != expected_packages:
            raise ValueError("active packages must be byte-sorted")
        names = tuple(item.active.name for item in self.packages)
        if len(names) != len(set(names)) or len(names) != len({
            unicodedata.normalize("NFC", name).casefold() for name in names
        }):
            raise ValueError("active packages contain a name collision")
        if self.instruction_catalog.descriptors != tuple(
            item.descriptor for item in self.packages
        ):
            raise ValueError("active instruction catalog does not match packages")
        object.__setattr__(self, "active_set_digest", canonical_digest({
            "snapshot_digest": self.snapshot_digest,
            "packages": [item.identity_payload() for item in self.packages],
            "instruction_catalog_digest": self.instruction_catalog.catalog_digest,
        }, domain="active-skill-set-v1"))


@runtime_checkable
class SkillActivationGate(Protocol):
    def acquire_execution_guard(
        self,
        *,
        expected_snapshot_digest: str,
        package_digest: str,
        storage_identity_digest: str,
        qualification_digest: str,
    ) -> SkillExecutionGuardV1 | ActivationGateDecisionV1:
        """短 prepare 与完整 invoke 共用；调用方决定何时释放返回的 SH guard。"""


@dataclass(frozen=True, slots=True)
class SkillLifecyclePlanV1:
    action_id: str
    expected_snapshot_token: str
    expected_snapshot_digest: str
    next_snapshot: SkillPackageSnapshotV1
    next_snapshot_digest: str
    preview: dict[str, JSONValue]
    preview_digest: str
    action: SkillLifecycleActionV1
    plan_digest: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "plan_digest", canonical_digest({
            "action_id": self.action_id,
            "expected_snapshot_token": self.expected_snapshot_token,
            "expected_snapshot_digest": self.expected_snapshot_digest,
            "next_snapshot_digest": self.next_snapshot_digest,
            "preview_digest": self.preview_digest,
            "action": self.action.to_payload(),
        }, domain="skill-lifecycle-plan-v1"))


@dataclass(frozen=True, slots=True)
class SkillPackageSnapshotV1:
    revision: int
    snapshot_token: str
    active: tuple[ActivePackageV1, ...]
    staged: tuple[StagedPackageV1, ...]
    revocations: tuple[RevocationTombstoneV1, ...]
    history: tuple[HistoryEntryV1, ...]
    cutover: CutoverStateV1
    head_action_id: str | None
    snapshot_digest: str = field(init=False)
```

Implement explicit `to_payload()` methods for `PackageIdentityV1`, `StoredPackageV1`, `QualificationRecordV1`, `BundledReleaseAuthorityV1`, `ActivePackageV1`, `StagedPackageV1`, `RevocationTombstoneV1`, `HistoryEntryV1`, `CommittedActionV1`, `CutoverStateV1`, every lifecycle action, `SkillLifecyclePlanV1`, and `SkillPackageSnapshotV1`. Every digest validator accepts only bare lowercase hex64; prefix-bearing or uppercase values fail without normalization. Each method lists every authoritative field, rejects extra decoded keys, normalizes no value implicitly, and validates tuples as byte-sorted and duplicate-free. The three lifecycle member codecs encode the complete nested `qualification.to_payload()` and decode it with `QualificationRecordV1.from_payload`; no ledger member accepts a naked qualification digest and no codec serializes the derived `qualification_digest`. `ActiveSkillSetV1` is a startup-only materialized contract rather than a ledger codec: its derived digest binds byte-sorted package/storage/qualification/object-root/instruction/executable identities, never raw descriptors. `SkillPackageSnapshotV1.snapshot_token` is injected from exact loaded ledger bytes and is not encoded. `snapshot_digest` excludes that token and recovery-only `head_action_id`; it includes revision, complete active/staged/history qualification payloads, revocations, and cutover state. `CommittedActionV1` lives in the separate append-only journal and is never capped or pruned. The ledger keeps one `head_action_id` so startup can repair a crash between ledger replace and journal fsync without creating a digest cycle.

Freeze the action union with these exact fields: `InspectSourceV1(action_id, source_binding, declared_version)`, `ImportPackageV1(action_id, source_binding, declared_version, transport_digest, package_digest)`, `StagePackageV1(action_id, package_digest, storage_identity_digest, qualification)`, `ActivatePackageV1(action_id, stage_id, proposed_active_set_digest, trust_basis, trust_binding_digest)`, `RevokePackageV1(action_id, package_digest)`, `RollbackPackageV1(action_id, history_id, qualification)`, `BeginCutoverV1(action_id, legacy_tool_identities, managed_packaged_tool_identities, disabled_epoch)`, and `FinalizeCutoverV1(action_id, checkpoint_scan_digest, active_set_digest, active_tool_names_digest, managed_packaged_tool_identities, finalized_epoch)`. Both identity tuples are bare-hex64, byte-sorted, duplicate-free exact ToolSpec identity allowlists; their set digests are derived in the plan/scan and are not accepted as caller-provided authority. Every `action_id` is the operator action/synthetic tool-call ID; there is no second lifecycle-generated ID.

- [ ] **Step 4: Add strict round-trip/mutation Reds, observe failure, then implement the minimum Green codec**

```python
@pytest.mark.parametrize("path", [
    ("active", 0, "qualification", "hermetic_runtime_closure_digest"),
    ("staged", 0, "qualification", "sandbox_backend_identity"),
    ("history", 0, "qualification", "resource_limiter_identity"),
    ("cutover", "legacy_prepare_disabled_epoch"),
])
def test_snapshot_digest_changes_for_every_authority_mutation(path) -> None:
    original = snapshot_with_every_member()
    mutated_payload = mutate(original.to_payload(), path)
    mutated = SkillPackageSnapshotV1.from_payload(mutated_payload)
    assert mutated.snapshot_digest != original.snapshot_digest


def test_snapshot_decoder_rejects_nested_extra_key() -> None:
    payload = snapshot_with_every_member().to_payload()
    payload["active"][0]["future"] = True
    with pytest.raises(SkillPackageCodecError, match="unknown keys"):
        SkillPackageSnapshotV1.from_payload(payload)
```

Use one `expect_keys(payload, required, optional=frozenset())` helper at every object boundary. Encode canonical UTF-8 JSON with sorted keys/no whitespace/no NaN; decode from bounded bytes and recompute every derived digest instead of trusting persisted derived values.

- [ ] **Step 5: Verify Task 1 and commit**

Run:

```bash
.venv/bin/python -m pytest -q tests/skill/test_package_contracts.py -rx
.venv/bin/ruff check agent/skill/package_contracts.py tests/skill/test_package_contracts.py
git diff --check
git add agent/skill/package_contracts.py tests/skill/test_package_contracts.py docs/acceptance/021_SKILL_PACKAGE_LIFECYCLE_E2.md docs/implementation/021_EXECUTION_LOG.md
git commit -m "feat(skill): freeze package lifecycle contracts"
```

Expected: all Task 1 tests pass; the execution log records the exact test count and `next_task=2`.

### Task 2: Implement one closed ZIP/inventory codec

**Files:**
- Create: `agent/skill/package_transport.py`
- Create: `tests/skill/test_package_transport.py`
- Create: `tests/skill/fixtures/package_transport_cases.py`

**Interfaces:**
- Consumes only `agent.skill.executable_contracts.ExecutableScriptDescriptorV1`, `ExecutableSkillManifestV1`, `PortableRequirementsV1`, `agent.skill.executable_codec.decode_executable_manifest(raw: bytes, *, declared_scripts: tuple[ExecutableScriptDescriptorV1, ...]) -> ExecutableSkillManifestV1`, `decode_portable_requirements(raw: bytes) -> PortableRequirementsV1`, `executable_manifest_digest(manifest) -> str`, and `portable_requirements_digest(requirements: PortableRequirementsV1 | None) -> str`, owned and frozen by 020b Task 2 and consumed here only after 020b Tasks 1–6 complete. This import direction is `package_transport → executable_contracts/executable_codec`; both 020b modules import no lifecycle implementation.
- `PackageTransportLimitsV1`
- `CandidateEntryV1(relative_path, role, content)` and `PackageCandidateV1(entries, inventory, declared_version, transport_digest, package)`; `entries` are byte-sorted transient source bytes, while `inventory` and `package` are the durable canonical identities.
- `scan_skillpkg_bytes(raw: bytes, *, declared_version: str, limits: PackageTransportLimitsV1 = DEFAULT_PACKAGE_TRANSPORT_LIMITS) -> PackageCandidateV1`
- `build_candidate(entries: Sequence[CandidateEntryV1], *, declared_version: str, transport_digest: str) -> PackageCandidateV1`
- `decode_skill_document`; executable manifest and portable-requirements decode remain 020b-owned.
- `compute_tree_digest` and `compute_package_identity(entries, inventory, declared_version)`

- [ ] **Step 1: Write the closed ZIP and hostile-input Reds**

```python
@pytest.mark.parametrize("case", hostile_archives(), ids=lambda item: item.case_id)
def test_closed_zip_rejects_every_out_of_subset_case(case) -> None:
    with pytest.raises(PackageTransportError, match=case.reason):
        scan_skillpkg_bytes(case.archive, declared_version="1.0.0")


def test_zip_and_directory_inventory_share_one_package_identity() -> None:
    entries = canonical_fixture_entries()
    zipped = scan_skillpkg_bytes(build_closed_zip(entries), declared_version="1.0.0")
    directory = build_candidate(
        entries,
        declared_version="1.0.0",
        transport_digest=directory_transport_digest(entries),
    )
    assert zipped.package.package_digest == directory.package.package_digest
    assert zipped.inventory == directory.inventory
    assert zipped.transport_digest != directory.transport_digest


def test_same_name_version_with_changed_byte_has_different_digest() -> None:
    first = scan_skillpkg_bytes(package_archive(script=b"print('one')\n"), declared_version="1.0.0")
    second = scan_skillpkg_bytes(package_archive(script=b"print('two')\n"), declared_version="1.0.0")
    assert (first.package.name, first.package.version) == (second.package.name, second.package.version)
    assert first.package.package_digest != second.package.package_digest


def test_manifest_decoder_receives_byte_sorted_canonical_script_descriptors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, tuple[ExecutableScriptDescriptorV1, ...]] = {}

    def record_decoder(raw: bytes, *, declared_scripts):
        observed["declared_scripts"] = declared_scripts
        return executable_manifest(package_name="echo", package_version="1.0.0")

    monkeypatch.setattr(package_transport, "decode_executable_manifest", record_decoder)
    entries = tuple(reversed(executable_fixture_entries(
        name="echo",
        scripts={"scripts/z.py": b"print('z')\n", "scripts/a.py": b"print('a')\n"},
    )))
    candidate = build_candidate(
        entries,
        declared_version="1.0.0",
        transport_digest="a" * 64,
    )
    expected = tuple(
        ExecutableScriptDescriptorV1(
            relative_path=item.relative_path,
            size_bytes=item.size_bytes,
            sha256=item.sha256,
        )
        for item in candidate.inventory
        if item.role is PackageRole.SCRIPT
    )
    assert tuple(item.relative_path for item in expected) == (
        "scripts/a.py", "scripts/z.py",
    )
    assert observed["declared_scripts"] == expected
```

`hostile_archives()` must construct non-vacuous cases for encrypted flag, data-descriptor flag, Zip64 signatures and extra `0x0001`, arbitrary extras, stored/deflate alternatives, bzip/lzma, duplicate central names, local/central name mismatch, absolute/dot/dot-dot/backslash/empty path, invalid UTF-8 flag/name, symlink/FIFO/device mode, NFC/casefold collision, path/depth/count/archive/per-file/expanded/ratio overflow, CRC mismatch, truncated stream, and declared-versus-streamed size mismatch.

- [ ] **Step 2: Run the transport Reds**

Run: `.venv/bin/python -m pytest -q tests/skill/test_package_transport.py -rx`

Expected: collection fails because `agent.skill.package_transport` does not exist.

- [ ] **Step 3: Implement the minimum Green: canonical names, ZIP preflight, streamed bounds, and identity**

```python
@dataclass(frozen=True, slots=True)
class PackageTransportLimitsV1:
    max_archive_bytes: int = 64 * 1024 * 1024
    max_entries: int = 10_000
    max_entry_bytes: int = 32 * 1024 * 1024
    max_expanded_bytes: int = 256 * 1024 * 1024
    max_compression_ratio: int = 100
    max_path_components: int = 16
    max_path_bytes: int = 1_024


def canonical_relative_name(raw: str) -> str:
    if not raw or raw.startswith("/") or "\\" in raw or "\x00" in raw:
        raise PackageTransportError("noncanonical path")
    normalized = unicodedata.normalize("NFC", raw.rstrip("/"))
    parts = normalized.split("/")
    if raw != unicodedata.normalize("NFC", raw) or any(part in {"", ".", ".."} for part in parts):
        raise PackageTransportError("noncanonical path")
    if len(parts) > 16 or len(normalized.encode("utf-8")) > 1_024:
        raise PackageTransportError("path bound")
    return normalized


def _preflight_archive(raw: bytes, limits: PackageTransportLimitsV1) -> None:
    if len(raw) > limits.max_archive_bytes:
        raise PackageTransportError("archive bound")
    if b"PK\x06\x06" in raw or b"PK\x06\x07" in raw:
        raise PackageTransportError("Zip64")


def _stream_member(archive: zipfile.ZipFile, info: zipfile.ZipInfo, limits: PackageTransportLimitsV1) -> bytes:
    if info.flag_bits & 0x1:
        raise PackageTransportError("encrypted")
    if info.flag_bits & 0x8:
        raise PackageTransportError("data descriptor")
    if info.extra:
        raise PackageTransportError("extra field")
    if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
        raise PackageTransportError("compression method")
    if info.file_size > limits.max_entry_bytes:
        raise PackageTransportError("entry bound")
    if info.compress_size == 0 and info.file_size > 0 or info.file_size > max(1, info.compress_size) * limits.max_compression_ratio:
        raise PackageTransportError("compression ratio")
    output = bytearray()
    with archive.open(info, "r") as source:
        while chunk := source.read(min(65_536, limits.max_entry_bytes + 1 - len(output))):
            output.extend(chunk)
            if len(output) > limits.max_entry_bytes:
                raise PackageTransportError("entry bound")
    if len(output) != info.file_size:
        raise PackageTransportError("expanded size mismatch")
    return bytes(output)
```

Before streaming, parse each local header at `ZipInfo.header_offset` and require signature, flags, method, UTF-8 name bytes, CRC, compressed size, and expanded size to equal its central record. Reject central-directory comments, archive comments, duplicate byte names, NFC duplicates, and casefold duplicates. Determine role only from exact paths: `SKILL.md`, `first-agent.json`, `skill.requirements.json`, `scripts/**`, `references/**`, `assets/**`; reject every other top-level path. Directory entries contribute canonical `0500` records; regular-file SHA-256 is over exact expanded bytes.

- [ ] **Step 4: Implement the minimum Green: closed decoders and exact package digest**

```python
def compute_package_identity(entries, inventory, declared_version) -> PackageIdentityV1:
    by_path = {entry.relative_path: entry for entry in entries}
    skill = decode_skill_document(by_path["SKILL.md"].content)
    declared_scripts = tuple(
        ExecutableScriptDescriptorV1(
            relative_path=entry.relative_path,
            size_bytes=entry.size_bytes,
            sha256=entry.sha256,
        )
        for entry in sorted(inventory, key=lambda item: item.relative_path.encode("utf-8"))
        if entry.role is PackageRole.SCRIPT
    )
    manifest = (
        decode_executable_manifest(
            by_path["first-agent.json"].content,
            declared_scripts=declared_scripts,
        )
        if "first-agent.json" in by_path
        else NoExecutableManifestV1(version=declared_version)
    )
    requirements = (
        decode_portable_requirements(by_path["skill.requirements.json"].content)
        if "skill.requirements.json" in by_path
        else None
    )
    tree_digest = canonical_digest(
        [entry.identity_payload() for entry in inventory],
        domain="skill-package-tree-v1",
    )
    package_name = (
        manifest.package_name
        if isinstance(manifest, ExecutableSkillManifestV1)
        else skill.name
    )
    package_version = (
        manifest.package_version
        if isinstance(manifest, ExecutableSkillManifestV1)
        else manifest.version
    )
    if package_name != skill.name:
        raise PackageTransportError("SKILL name does not match executable package name")
    if package_version != declared_version:
        raise PackageTransportError("declared version does not match manifest version")
    if isinstance(manifest, ExecutableSkillManifestV1) and requirements is None:
        raise PackageTransportError("executable package requires portable requirements")
    if not isinstance(manifest, ExecutableSkillManifestV1) and requirements is not None:
        raise PackageTransportError("instruction-only package cannot declare executable requirements")
    if not isinstance(manifest, ExecutableSkillManifestV1) and declared_scripts:
        raise PackageTransportError("instruction-only package cannot contain declared scripts")
    return PackageIdentityV1.create(
        name=package_name,
        version=package_version,
        tree_digest=tree_digest,
        manifest_digest=(
            executable_manifest_digest(manifest)
            if isinstance(manifest, ExecutableSkillManifestV1)
            else manifest.digest
        ),
        skill_digest=skill.digest,
        requirements_digest=portable_requirements_digest(requirements),
    )
```

`build_candidate` canonicalizes and byte-sorts entries, derives the inventory, calls `compute_package_identity(entries, inventory, declared_version)`, and constructs the one `PackageCandidateV1`; no partially initialized candidate exists. 021 defines neither `ExecutableScriptDescriptorV1`, `PortableRequirementsV1`, nor either decoder. It imports the seven named 020b exports directly and passes the exact byte-sorted descriptors `(relative_path, size_bytes, sha256)` derived from canonical `SCRIPT` inventory as `declared_scripts`; it never passes a naked path-string sequence, trusts manifest-declared paths to construct decoder authority, or resolves descriptors from mutable source paths. `NoExecutableManifestV1` remains a 021-local immutable no-executable marker whose digest binds the operator-declared exact SemVer version and domain. `decode_skill_document` reuses the current bounded frontmatter/body rules and parses `allowed-tools` as the official space-separated string required by 020b. The scanner exact-matches `SKILL.md` name to executable `package_name`, operator `declared_version` to executable `package_version`, and requires portable requirements for executable packages. Archive transport digest is bare SHA-256 hex64 over exact archive bytes; directory transport digest is a bare domain-separated digest over canonical `(path, role, size, content_sha256)` inventory, so both source kinds always bind a non-null transport digest.

- [ ] **Step 5: Verify Task 2 and commit**

Run:

```bash
.venv/bin/python -m pytest -q tests/skill/test_package_contracts.py tests/skill/test_package_transport.py -rx
.venv/bin/ruff check agent/skill/package_transport.py tests/skill/test_package_transport.py tests/skill/fixtures/package_transport_cases.py
git diff --check
git add agent/skill/package_transport.py tests/skill/test_package_transport.py tests/skill/fixtures/package_transport_cases.py
git commit -m "feat(skill): add closed skill package transport"
```

Expected: all Task 1–2 tests pass, including every hostile archive case.

### Task 3: Add no-follow local sources and immutable content-addressed objects

**Files:**
- Create: `agent/skill_hosts/__init__.py`
- Create: `agent/skill_hosts/posix_packages.py`
- Create: `tests/skill_hosts/test_posix_package_sources.py`
- Create: `tests/skill_hosts/test_posix_package_objects.py`
- Modify: `tests/architecture/test_cutover_absence.py`

**Interfaces:**
- `LocalSourceLocatorV1(kind, absolute_path, declared_version)` and durable `SourceBindingV1`; the operator-supplied version is part of every inspect/reopen identity and never inferred from a mutable source.
- `PosixPackageSource.inspect(locator: LocalSourceLocatorV1) -> PackageCandidateV1`
- `PosixPackageObjectStore.import_candidate(candidate, source, expected) -> StoredPackageV1`
- `load_exact(package_digest, storage_identity_digest) -> StoredPackageV1`
- `open_exact(package_digest, storage_identity_digest) -> PackageObjectRootV1`; returns one pinned no-follow directory descriptor plus its private canonical host path, both exact-matching the stored object-root digest.
- `read_exact(root: PackageObjectRootV1, relative_path: str, expected_sha256: str, *, max_bytes: int) -> bytes`; descriptor-relative, declared-inventory-only, and no-follow.
- `object_exists_exact(package_digest: str, storage_identity_digest: str) -> bool`

- [ ] **Step 1: Write directory identity, hostile-node, and import crash Reds**

```python
@pytest.mark.parametrize("node_kind", ["symlink", "hardlink", "fifo", "socket"])
def test_directory_source_rejects_unsupported_node_without_object(tmp_path: Path, node_kind: str) -> None:
    source = build_hostile_directory(tmp_path, node_kind)
    store = PosixPackageObjectStore.initialize(tmp_path / "state" / "skill-packages")
    with pytest.raises(PackageSourceSecurityError):
        PosixPackageSource().inspect(
            LocalSourceLocatorV1.directory(source, declared_version="1.0.0")
        )
    assert store.list_object_digests() == ()


def test_import_rejects_source_replacement_after_approval(tmp_path: Path) -> None:
    source = build_valid_directory(tmp_path / "candidate")
    scanner = PosixPackageSource()
    expected = scanner.inspect(LocalSourceLocatorV1.directory(source, declared_version="1.0.0"))
    replace_tree_preserving_leaf_bytes(source)
    with pytest.raises(PackageSourceDriftError):
        scanner.reopen_and_verify(expected.source_binding)


def test_crash_after_object_rename_leaves_readable_orphan_without_ledger_authority(tmp_path: Path) -> None:
    store, repository = stores(tmp_path, fault="after_object_rename")
    with pytest.raises(SimulatedCrash):
        store.import_candidate(candidate(), source(), candidate().source_binding)
    loaded = store.load_exact(candidate().package.package_digest, store.discovered_identity())
    assert loaded.package.package_digest == candidate().package.package_digest
    assert repository.load().active == repository.load().staged == ()
```

- [ ] **Step 2: Run the POSIX source/object Reds**

Run: `.venv/bin/python -m pytest -q tests/skill_hosts/test_posix_package_sources.py tests/skill_hosts/test_posix_package_objects.py tests/architecture/test_cutover_absence.py -rx`

Expected: collection fails because `agent.skill_hosts` does not exist; the architecture inventory also fails until the new exact paths are admitted.

- [ ] **Step 3: Implement the minimum Green: pinned directory/archive source reopening**

```python
def _open_owner_directory(path: Path, *, mode: int) -> int:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    info = os.fstat(fd)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != mode:
        os.close(fd)
        raise PackageSourceSecurityError("unsafe owner directory")
    return fd


def _read_regular_at(parent_fd: int, name: str, *, limit: int) -> tuple[bytes, FileIdentityV1]:
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid() or before.st_nlink != 1:
            raise PackageSourceSecurityError("unsafe source file")
        data = bytearray()
        while chunk := os.read(fd, min(65_536, limit + 1 - len(data))):
            data.extend(chunk)
            if len(data) > limit:
                raise PackageTransportError("entry bound")
        after = os.fstat(fd)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            raise PackageSourceDriftError("source changed while reading")
        return bytes(data), FileIdentityV1.from_stat(after)
    finally:
        os.close(fd)
```

Enumerate with `os.scandir(fd)` under a maximum-entry counter; open every child directory relative to its pinned parent, never concatenate an untrusted absolute path, and record every ancestor identity in `SourceBindingV1`. Archive sources are one regular `nlink == 1` file read to the archive bound, with before/after identity checks. `reopen_and_verify` repeats the complete scan and requires source locator kind, root/file descriptors, transport digest, inventory, and package digest to match.

- [ ] **Step 4: Implement the minimum Green: incoming/read-back/fsync/rename and storage identity**

```python
def import_candidate(self, candidate, source, expected) -> StoredPackageV1:
    verified = source.reopen_and_verify(expected)
    if verified.package.package_digest != candidate.package.package_digest:
        raise PackageSourceDriftError("package digest changed")
    object_name = candidate.package.package_digest
    incoming = f".incoming-{candidate.source_binding.action_id}"
    with self._exclusive_root_fd() as root_fd:
        if self._load_existing(root_fd, object_name, candidate.package) is not None:
            return self._load_existing(root_fd, object_name, candidate.package)
        os.mkdir(incoming, 0o700, dir_fd=root_fd)
        incoming_fd = os.open(incoming, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
        try:
            self._write_inventory(incoming_fd, verified.entries)
            self._write_metadata(incoming_fd, candidate)
            self._read_back_exact(incoming_fd, candidate)
            self._seal_tree(incoming_fd)
            os.fsync(incoming_fd)
        finally:
            os.close(incoming_fd)
        os.replace(incoming, object_name, src_dir_fd=root_fd, dst_dir_fd=root_fd)
        os.fsync(root_fd)
        return self._load_existing(root_fd, object_name, candidate.package)
```

`_write_inventory` creates each directory/file with `O_CREAT|O_EXCL|O_NOFOLLOW`, writes all bytes, `fchmod`s the canonical mode, fsyncs every file and directory, and verifies SHA-256/size on a fresh descriptor. `storage_identity_digest` binds pinned store-root `(dev, ino)`, object-root `(dev, ino)`, canonical inventory, and metadata-file identity; `load_exact` reopens and recomputes all of it. `open_exact` performs the same full verification, duplicates the exact object-root fd into `PackageObjectRootV1`, and transfers descriptor lifetime to `SkillLifecycleResources`. Its `canonical_path` is private in-process sandbox policy input, is excluded from equality/digests/repr, and never enters bindings, checkpoints, events, ToolResult, receipts, or model context. Existing same digest with any mismatch is corruption, never overwritten.

- [ ] **Step 5: Update the exact product inventory, verify Task 3 passes, and commit**

Add only `agent/skill_hosts/__init__.py` and `agent/skill_hosts/posix_packages.py` to the architecture inventory; add `agent.skill_hosts` to the package set. Keep unique ToolRuntime/provider/checkpoint assertions unchanged.

Run:

```bash
.venv/bin/python -m pytest -q tests/skill_hosts/test_posix_package_sources.py tests/skill_hosts/test_posix_package_objects.py tests/architecture/test_cutover_absence.py -rx
.venv/bin/ruff check agent/skill_hosts tests/skill_hosts tests/architecture/test_cutover_absence.py
git diff --check
git add agent/skill_hosts tests/skill_hosts tests/architecture/test_cutover_absence.py
git commit -m "feat(skill): add immutable POSIX package objects"
```

Expected: directory/ZIP parity, identity-replacement, unsupported-node, object-readback, and crash-orphan tests all pass.

### Task 4: Implement one guarded ledger, append-only action journal, and CAS crash semantics

**Files:**
- Create: `agent/skill/package_store.py`
- Modify: `agent/skill_hosts/posix_packages.py`
- Create: `tests/skill/test_package_store.py`
- Create: `tests/skill/test_package_store_conformance.py`
- Create: `tests/skill_hosts/test_posix_package_repository.py`
- Create: `tests/skill_hosts/test_posix_package_repository_crashes.py`

**Interfaces:**
- `SkillPackageRepository.load() -> SkillPackageSnapshotV1`
- `try_acquire_shared() -> SkillExecutionGuardV1 | None`
- `try_acquire_exclusive() -> SkillLifecycleGuardV1 | None`
- `compare_and_swap(guard, expected, next_state, action_id) -> AppliedV1 | ConflictV1`
- `reconcile_action(action_id, next_snapshot_digest) -> ActionReconciliationV1`
- `UnknownCommitError`, `DeterministicSkillPackageRepository`, and `assert_repository_conformance(factory)`

- [ ] **Step 1: Write guard ordering, CAS, journal, and crash Reds**

```python
def test_execution_guard_linearizes_before_revoke(repository) -> None:
    shared = repository.try_acquire_shared()
    assert shared is not None
    assert repository.try_acquire_exclusive() is None
    shared.release()
    exclusive = repository.try_acquire_exclusive()
    assert exclusive is not None
    assert repository.try_acquire_shared() is None
    exclusive.release()


def test_two_repository_handles_share_the_same_process_local_lock_domain(tmp_path: Path) -> None:
    first = PosixSkillPackageRepository.create(tmp_path / "state")
    second = PosixSkillPackageRepository.open(first.root)
    shared = first.try_acquire_shared()
    assert shared is not None
    assert second.try_acquire_exclusive() is None
    shared.release()
    exclusive = second.try_acquire_exclusive()
    assert exclusive is not None
    assert first.try_acquire_shared() is None
    exclusive.release()


def test_forked_child_cannot_reuse_or_extend_parent_guard(tmp_path: Path) -> None:
    repository = PosixSkillPackageRepository.create(tmp_path / "state")
    guard = repository.try_acquire_shared()
    assert guard is not None
    child = fork_and_attempt_guard_reuse(repository, guard)
    assert child.reuse_code == "guard_owner_process_mismatch"
    assert child.inherited_guard_fds == 0
    guard.release()


def test_conflict_is_proved_not_executed_and_does_not_append_journal(repository) -> None:
    stale = repository.load()
    apply_one_mutation(repository)
    with acquired_exclusive(repository) as guard:
        outcome = repository.compare_and_swap(guard, stale, next_snapshot(stale), "action-stale")
    assert outcome == ConflictV1(repository.load().snapshot_digest)
    assert repository.reconcile_action("action-stale", next_snapshot(stale).snapshot_digest).status is ActionCommitStatus.NOT_COMMITTED


def test_restart_round_trip_preserves_complete_qualification_records(tmp_path: Path) -> None:
    repository = PosixSkillPackageRepository.create(tmp_path / "state")
    expected = repository.load()
    qualified = qualification()
    next_state = snapshot_with_members(
        revision=expected.revision + 1,
        staged=(staged(qualification=qualified),),
        active=(active(qualification=qualified),),
        history=(history(qualification=qualified),),
    )
    with acquired_exclusive(repository) as guard:
        assert isinstance(
            repository.compare_and_swap(guard, expected, next_state, "action-qualified"),
            AppliedV1,
        )
    reopened = PosixSkillPackageRepository.open(repository.root)
    loaded = reopened.load()
    assert loaded.staged[0].qualification == qualified
    assert loaded.active[0].qualification == qualified
    assert loaded.history[0].qualification == qualified


def test_nested_qualification_drift_changes_snapshot_identity(repository) -> None:
    original = snapshot_with_members(active=(active(qualification=qualification()),))
    payload = original.to_payload()
    payload["active"][0]["qualification"]["sandbox_backend_identity"] = "f" * 64
    drifted = SkillPackageSnapshotV1.from_payload(payload)
    assert drifted.snapshot_digest != original.snapshot_digest


@pytest.mark.parametrize("boundary", [
    "before_ledger_replace",
    "after_ledger_replace",
    "after_ledger_directory_fsync",
    "after_journal_append",
    "after_journal_fsync",
    "during_immediate_reload",
])
def test_cas_crash_boundary_is_applied_conflict_or_unknown_only(tmp_path: Path, boundary: str) -> None:
    repository = repository_with_fault(tmp_path, boundary)
    expected = repository.load()
    with acquired_exclusive(repository) as guard:
        try:
            outcome = repository.compare_and_swap(guard, expected, next_snapshot(expected), "action-1")
        except UnknownCommitError:
            outcome = "unknown"
    assert outcome in {AppliedV1(next_snapshot(expected).snapshot_digest), "unknown"}
    recovered = PosixSkillPackageRepository.open(repository.root)
    decision = recovered.reconcile_action("action-1", next_snapshot(expected).snapshot_digest)
    assert decision.status in {ActionCommitStatus.COMMITTED, ActionCommitStatus.NOT_COMMITTED}
```

- [ ] **Step 2: Run the repository Reds**

Run: `.venv/bin/python -m pytest -q tests/skill/test_package_store.py tests/skill/test_package_store_conformance.py tests/skill_hosts/test_posix_package_repository.py tests/skill_hosts/test_posix_package_repository_crashes.py -rx`

Expected: collection fails because `agent.skill.package_store` and the repository adapter do not exist.

- [ ] **Step 3: Implement the minimum Green: portable protocol, strict codec, and deterministic adapter**

```python
@runtime_checkable
class SkillPackageRepository(Protocol):
    def load(self) -> SkillPackageSnapshotV1:
        """读取一个不可变 head 与 opaque token。"""

    def try_acquire_shared(self) -> SkillExecutionGuardV1 | None:
        """非阻塞获取 packaged execution guard。"""

    def try_acquire_exclusive(self) -> SkillLifecycleGuardV1 | None:
        """非阻塞获取 lifecycle mutation guard。"""

    def compare_and_swap(
        self,
        guard: SkillLifecycleGuardV1,
        expected: SkillPackageSnapshotV1,
        next_state: SkillPackageSnapshotV1,
        action_id: str,
    ) -> AppliedV1 | ConflictV1:
        """在一个有效 EX guard 下提交一次 exact plan。"""

    def reconcile_action(self, action_id: str, next_snapshot_digest: str) -> ActionReconciliationV1:
        """只按 journal 的 exact pair 分类未知提交。"""


class UnknownCommitError(RuntimeError):
    def __init__(self, action_id: str, next_snapshot_digest: str) -> None:
        super().__init__("skill lifecycle commit outcome is unknown")
        self.action_id = action_id
        self.next_snapshot_digest = next_snapshot_digest
```

The deterministic adapter implements every protocol method and fault boundary in memory, requires a live exact guard object for CAS, rejects guard reuse/release twice, and uses the same ledger codec as POSIX. `decode_ledger` bounds the ledger at `4 MiB`; `decode_journal_line` bounds each canonical JSON line at `1 KiB`, rejects truncated/extra/duplicate/out-of-order revision records, and never truncates or prunes valid history.

- [ ] **Step 4: Implement the minimum Green: POSIX guard, durable CAS, and journal repair**

Before CAS, implement one module-private `RepositoryLockCoordinator` registry keyed by the pinned ledger lock-file `(st_dev, st_ino)`. Every repository handle in the process resolves the same coordinator. Nonblocking SH/EX acquisition first reserves the in-process reader/writer state under one `threading.Lock`, then acquires `fcntl.flock(..., LOCK_SH|LOCK_NB)` or `LOCK_EX|LOCK_NB` on a fresh no-follow owner-only lock fd; OS failure releases the local reservation. Guard release unlocks/closes the fd before releasing the local reservation, records the creating PID, rejects double release/use from another PID, and exposes no upgrade API. Register one `os.register_at_fork(after_in_child=...)` hook that closes all inherited live guard fds and clears the child registry before product code can use a repository. Thus same-process repository instances, other processes, and forked children share one fail-closed domain; the design does not rely on platform-specific same-process `flock` behavior.

```python
def compare_and_swap(self, guard, expected, next_state, action_id):
    self._require_exclusive_guard(guard)
    current = self._load_under_guard(guard)
    self._repair_head_journal(guard, current)
    current = self._load_under_guard(guard)
    if current.snapshot_token != expected.snapshot_token or current.snapshot_digest != expected.snapshot_digest:
        return ConflictV1(current.snapshot_digest)
    committed = replace(
        next_state,
        revision=current.revision + 1,
        head_action_id=action_id,
    )
    if committed.snapshot_digest != next_state.snapshot_digest:
        raise ValueError("next snapshot digest does not match committed revision")
    data = encode_ledger(committed)
    replaced = False
    try:
        self._replace_ledger(guard.directory_fd, data)
        replaced = True
        record = CommittedActionV1(action_id, committed.snapshot_digest, committed.revision)
        self._append_journal_fsync(guard.directory_fd, record)
        reloaded = self._load_under_guard(guard)
        reconciled = self._find_journal_record(guard.directory_fd, action_id, committed.snapshot_digest)
        if reloaded.authoritative_payload() != committed.authoritative_payload() or reconciled != record:
            raise OSError("post-commit read-back mismatch")
        return AppliedV1(committed.snapshot_digest)
    except Exception as error:
        if replaced:
            raise UnknownCommitError(action_id, committed.snapshot_digest) from error
        raise
```

`next_state` is planned with `revision = current.revision + 1`, so the `replace` above confirms rather than changes its digest. `_replace_ledger` writes a unique `0600` temp, fsyncs, `os.replace`s descriptor-relative, and fsyncs the directory. `_repair_head_journal` runs under EX before any later mutation: if ledger `head_action_id` is absent from the journal, append `(head_action_id, snapshot_digest, revision)` and fsync; a conflicting record is corruption. `reconcile_action` acquires EX, performs this repair, scans the full bounded-record journal, and classifies only exact `(action_id, next_snapshot_digest)` as committed.

- [ ] **Step 5: Verify Task 4 and commit**

Run:

```bash
.venv/bin/python -m pytest -q tests/skill/test_package_store.py tests/skill/test_package_store_conformance.py tests/skill_hosts/test_posix_package_repository.py tests/skill_hosts/test_posix_package_repository_crashes.py -rx
.venv/bin/ruff check agent/skill/package_store.py agent/skill_hosts/posix_packages.py tests/skill tests/skill_hosts
git diff --check
git add agent/skill/package_store.py agent/skill_hosts/posix_packages.py tests/skill/test_package_store.py tests/skill/test_package_store_conformance.py tests/skill_hosts/test_posix_package_repository.py tests/skill_hosts/test_posix_package_repository_crashes.py
git commit -m "feat(skill): add guarded package ledger CAS"
```

Expected: deterministic and POSIX implementations pass the same conformance suite; every injected crash has one exact reconciliation classification after reopen.

### Task 5: Implement host qualification and the pure lifecycle planner

**Files:**
- Modify: `agent/skill/package_store.py`
- Create: `tests/skill/test_package_qualification.py`
- Create: `tests/skill/test_package_planner.py`
- Create: `tests/skill/test_active_set_collisions.py`

**Interfaces:**
- Consumes `PortableRequirementsV1` from `agent.skill.executable_contracts`; this task does not decode, construct a parallel schema, or install dependencies.
- `HostQualificationAuthority.qualify(stored, requirements: PortableRequirementsV1 | None, *, qualified_at) -> QualificationRecordV1 | QualificationFailureV1`
- `HostQualificationAuthority.revalidate(stored, record) -> bool`
- `HostQualificationAuthority.runtime_closure_for(stored, record) -> HermeticRuntimeClosureV1 | None`; callable only after successful `revalidate`, returns `None` only for instruction-only packages.
- `SkillPackagePlanner.plan(action, snapshot) -> SkillLifecyclePlanV1`
- `effective_runtime_reserved_names(snapshot, *, always_reserved_names, legacy_registration_names) -> tuple[str, ...]`
- `compile_active_tool_names(active_set, runtime_reserved_names) -> ActiveToolNamePlanV1`
- Pure transitions for stage, activate, revoke, rollback-stage, begin-cutover, and finalize-cutover.

```python
class SkillPackagePlanner(Protocol):
    def plan(
        self,
        action: SkillLifecycleActionV1,
        snapshot: SkillPackageSnapshotV1,
    ) -> SkillLifecyclePlanV1:
        """只构造 exact next state/preview/binding；不读取 host 或写 store。"""


class HostQualificationAuthority(Protocol):
    def qualify(
        self,
        stored: StoredPackageV1,
        requirements: PortableRequirementsV1 | None,
        *,
        qualified_at: str,
    ) -> QualificationRecordV1 | QualificationFailureV1:
        """核对注入的 sealed host closure；不安装或解析依赖。"""

    def revalidate(
        self,
        stored: StoredPackageV1,
        record: QualificationRecordV1,
    ) -> bool:
        """将完整 persisted record 与当前 sealed host facts exact-match；不重写 qualified_at。"""

    def runtime_closure_for(
        self,
        stored: StoredPackageV1,
        record: QualificationRecordV1,
    ) -> HermeticRuntimeClosureV1 | None:
        """返回当前 exact verified 020a closure；不下载、修复或 fallback。"""
```

- [ ] **Step 1: Write qualification and full-set collision Reds**

```python
def test_qualification_rejects_unavailable_exact_dependency_without_installing() -> None:
    authority = DeterministicQualificationAuthority(closure=closure(dependencies=(dep("pypdf", "6.0.0"),)))
    result = authority.qualify(
        stored(),
        requirements(dependencies=(dep("pypdf", "6.1.0"),)),
        qualified_at=UTC,
    )
    assert result == QualificationFailureV1("dependency_closure_mismatch")
    assert authority.install_calls == 0


@pytest.mark.parametrize("drift", [
    "package", "storage", "platform", "architecture", "runtime_closure",
    "sandbox_backend", "packaged_policy", "resource_limiter",
])
def test_revalidate_exact_matches_stored_object_and_complete_record(drift: str) -> None:
    authority = qualification_authority()
    stored_package = stored()
    record = authority.qualify(stored_package, requirements(), qualified_at=UTC)
    assert isinstance(record, QualificationRecordV1)
    assert authority.revalidate(stored_package, record) is True
    drifted_stored, drifted_authority = apply_qualification_drift(
        stored_package, authority, drift,
    )
    assert drifted_authority.revalidate(drifted_stored, record) is False
    assert drifted_authority.install_calls == 0


@pytest.mark.parametrize("drift", ["application_identity", "installed_manifest", "package_digest"])
def test_bundled_release_authority_fails_closed_for_distribution_drift(drift: str) -> None:
    authority = bundled_release_authority()
    observed = mutate_bundled_distribution(authority.expected_distribution, drift)
    assert authority.verify(observed) == BundledAuthorityDecisionV1.INVALID


@pytest.mark.parametrize("right", [
    "skill__pdf",
    unicodedata.normalize("NFD", "skill__café"),
    "SKILL__PDF",
    "skill__read_resource__other",
    "skill__" + "x" * 121,
])
def test_activation_rejects_reserved_and_canonical_name_collisions(right: str) -> None:
    with pytest.raises(ActiveSetCollisionError):
        compile_active_tool_names(active_set(tool_name=right), runtime_reserved_names=("skill__pdf", "skill__read_resource"))


def test_activation_collision_is_checked_against_entire_proposed_set() -> None:
    proposed = active_set(packages=(package_named("alpha", entrypoint="inspect"), package_named("ALPHA", entrypoint="inspect")))
    with pytest.raises(ActiveSetCollisionError):
        compile_active_tool_names(proposed, runtime_reserved_names=("read_file", "write_file"))


def test_reserved_lifecycle_names_are_authority_not_generated_prefix_violations() -> None:
    plan = compile_active_tool_names(
        active_set(tool_name="skill__pdf-workspace__inspect"),
        runtime_reserved_names=(
            "operator__approve",
            "runtime__cancel",
            "skill_package_activate",
        ),
    )
    assert plan.generated_names == ("skill__pdf-workspace__inspect",)


def test_disabled_legacy_name_does_not_block_same_name_packaged_activation() -> None:
    snapshot = snapshot_after_begin_cutover(disabled_epoch=7)
    reserved = effective_runtime_reserved_names(
        snapshot,
        always_reserved_names=("read_file", "skill_package_activate"),
        legacy_registration_names=("skill__pdf-workspace__inspect",),
    )
    assert "skill__pdf-workspace__inspect" not in reserved
    plan = compile_active_tool_names(
        active_set(tool_name="skill__pdf-workspace__inspect"),
        runtime_reserved_names=reserved,
    )
    assert plan.generated_names == ("skill__pdf-workspace__inspect",)
```

- [ ] **Step 2: Write lifecycle transition and stale-plan Reds**

```python
def test_stage_qualifies_but_does_not_activate() -> None:
    stored_package = stored()
    record = qualification()
    action = StagePackageV1(
        action_id="action-1",
        package_digest=stored_package.package.package_digest,
        storage_identity_digest=stored_package.storage_identity_digest,
        qualification=record,
    )
    plan = planner().plan(action, empty_snapshot())
    assert plan.next_snapshot.staged == (StagedPackageV1.from_records(stored(), qualification()),)
    assert plan.next_snapshot.active == ()


def test_revoke_is_monotonic_and_clears_every_reference() -> None:
    plan = planner().plan(RevokePackageV1("action-2", PACKAGE_DIGEST), active_and_staged_snapshot())
    assert all(item.package_digest != PACKAGE_DIGEST for item in plan.next_snapshot.active + plan.next_snapshot.staged)
    assert plan.next_snapshot.revocations[-1].package_digest == PACKAGE_DIGEST
    with pytest.raises(LifecyclePlanRejected, match="revoked"):
        planner().plan(
            RollbackPackageV1("action-3", HISTORY_ID, qualification()),
            plan.next_snapshot,
        )


def test_rollback_only_restages_historical_exact_object() -> None:
    plan = planner().plan(
        RollbackPackageV1("action-r", OLD_HISTORY_ID, qualification(package_digest=OLD_PACKAGE_DIGEST)),
        snapshot_with_history(),
    )
    assert plan.next_snapshot.active == snapshot_with_history().active
    assert plan.next_snapshot.staged[0].package_digest == OLD_PACKAGE_DIGEST
```

- [ ] **Step 3: Run planner Reds**

Run: `.venv/bin/python -m pytest -q tests/skill/test_package_qualification.py tests/skill/test_package_planner.py tests/skill/test_active_set_collisions.py -rx`

Expected: tests fail because the qualification/planner/collision implementations are absent.

- [ ] **Step 4: Implement the minimum Green: exact host qualification without environment repair**

```python
def qualify(self, stored, requirements, *, qualified_at):
    facts = self._runtime_closure.read_verified_facts()
    if requirements is not None:
        if requirements.runtime.value != facts.runtime_kind or requirements.abi != facts.runtime_abi:
            return QualificationFailureV1("runtime_abi_mismatch")
        if requirements.runtime_profile.value != facts.runtime_profile:
            return QualificationFailureV1("runtime_profile_mismatch")
        available = {item.name: item.version for item in facts.exact_dependencies}
        if any(available.get(item.name) != item.version for item in requirements.dependencies):
            return QualificationFailureV1("dependency_closure_mismatch")
    backend = self._sandbox_qualification.require_profile(
        "packaged-skill-v1" if requirements is not None else "instruction-only-v1"
    )
    if not backend.ready:
        return QualificationFailureV1(
            "strict_sandbox_unavailable" if requirements is not None
            else "instruction_profile_unavailable"
        )
    return QualificationRecordV1(
        package_digest=stored.package.package_digest,
        storage_identity_digest=stored.storage_identity_digest,
        platform=self._platform,
        architecture=self._architecture,
        hermetic_runtime_closure_digest=(
            facts.closure.closure_digest
            if requirements is not None
            else INSTRUCTION_ONLY_RUNTIME_DIGEST
        ),
        sandbox_backend_identity=backend.backend_identity,
        packaged_skill_policy_digest=backend.policy_digest,
        resource_limiter_identity=backend.resource_limiter_identity,
        qualified_at=qualified_at,
    )


def revalidate(self, stored, record):
    if (
        stored.package.package_digest != record.package_digest
        or stored.storage_identity_digest != record.storage_identity_digest
    ):
        return False
    facts = self._runtime_closure.read_verified_facts()
    requirements = self._requirements_for(stored)
    backend = self._sandbox_qualification.require_profile(
        "packaged-skill-v1" if requirements is not None else "instruction-only-v1"
    )
    if not backend.ready:
        return False
    expected = QualificationRecordV1(
        package_digest=stored.package.package_digest,
        storage_identity_digest=stored.storage_identity_digest,
        platform=self._platform,
        architecture=self._architecture,
        hermetic_runtime_closure_digest=(
            facts.closure.closure_digest
            if requirements is not None
            else INSTRUCTION_ONLY_RUNTIME_DIGEST
        ),
        sandbox_backend_identity=backend.backend_identity,
        packaged_skill_policy_digest=backend.policy_digest,
        resource_limiter_identity=backend.resource_limiter_identity,
        qualified_at=record.qualified_at,
    )
    return expected == record and expected.qualification_digest == record.qualification_digest


def runtime_closure_for(self, stored, record):
    if not self.revalidate(stored, record):
        raise QualificationDriftError("qualification no longer matches this host")
    if self._requirements_for(stored) is None:
        return None
    closure = self._runtime_closure.read_verified_facts().closure
    if closure.closure_digest != record.hermetic_runtime_closure_digest:
        raise QualificationDriftError("hermetic runtime closure drift")
    return closure
```

The authority receives all host facts and the exact 020b-decoded requirements lookup by composition-root injection. `read_verified_facts()` is a 021 host adapter over the 020a `HermeticRuntimeClosureV1` plus the sealed release dependency inventory; it does not redefine the closure. `_requirements_for(stored)` reads only the stored canonical requirements entry and returns `None` only for the versioned instruction-only marker; it calls the 020b decoder and never reparses a parallel schema. `INSTRUCTION_ONLY_RUNTIME_DIGEST` is the bare canonical digest of the fixed `instruction-only-v1/no-executable-runtime` domain. Instruction-only qualification uses the sealed `instruction-only-v1` profile and therefore does not depend on executable sandbox availability. The authority may verify but never install, download, modify, or resolve credentials. `BundledReleaseAuthorityV1` is valid only when current application-distribution identity, sealed installed-manifest digest, and exact bundled package digest all match.

- [ ] **Step 5: Implement the minimum Green: total planner and complete-name compiler**

```python
class DefaultSkillPackagePlanner:
    def plan(self, action, snapshot):
        next_snapshot = reduce_lifecycle(action, snapshot)
        preview = redacted_preview(action, snapshot, next_snapshot)
        return SkillLifecyclePlanV1(
            action_id=action.action_id,
            expected_snapshot_token=snapshot.snapshot_token,
            expected_snapshot_digest=snapshot.snapshot_digest,
            next_snapshot=next_snapshot,
            next_snapshot_digest=next_snapshot.snapshot_digest,
            preview=preview,
            preview_digest=canonical_digest(preview, domain="skill-lifecycle-preview-v1"),
            action=action,
        )


def canonical_tool_key(name: str) -> tuple[bytes, str, str]:
    if not 1 <= len(name.encode("utf-8")) <= 128:
        raise ActiveSetCollisionError("tool name shape")
    return name.encode("utf-8"), unicodedata.normalize("NFC", name), unicodedata.normalize("NFC", name).casefold()


def effective_runtime_reserved_names(
    snapshot,
    *,
    always_reserved_names,
    legacy_registration_names,
):
    legacy = (
        ()
        if snapshot.cutover.legacy_prepare_disabled_epoch is not None
        else tuple(legacy_registration_names)
    )
    return tuple(sorted(
        (*always_reserved_names, *legacy),
        key=lambda name: name.encode("utf-8"),
    ))


def compile_active_tool_names(active_set, runtime_reserved_names):
    generated = tuple(generated_names(active_set))
    if any(not name.startswith("skill__") for name in generated):
        raise ActiveSetCollisionError("generated tool prefix")
    for name in generated:
        if any(name.startswith(prefix) for prefix in ("skill_package_", "runtime__", "operator__")):
            raise ActiveSetCollisionError("reserved tool prefix")
    names = tuple(sorted(
        (*runtime_reserved_names, *generated),
        key=lambda name: name.encode("utf-8"),
    ))
    seen_bytes: set[bytes] = set()
    seen_nfc: set[str] = set()
    seen_casefold: set[str] = set()
    for name in names:
        raw, nfc, folded = canonical_tool_key(name)
        if raw in seen_bytes or nfc in seen_nfc or folded in seen_casefold:
            raise ActiveSetCollisionError("complete active-set tool collision")
        seen_bytes.add(raw); seen_nfc.add(nfc); seen_casefold.add(folded)
    return ActiveToolNamePlanV1(generated, canonical_digest(list(names), domain="active-tool-names-v1"))
```

`effective_runtime_reserved_names` receives only names already owned by static composition: `always_reserved_names` contains kernel plus lifecycle operator registrations, while `legacy_registration_names` contains the current process's legacy registrations. Before begin, both sets participate. Once the loaded snapshot has a durable `legacy_prepare_disabled_epoch`, legacy names are excluded even if those now-disabled registrations remain in the old immutable Runtime; this lets an explicitly imported same-name packaged Skill activate for the next restart without weakening exact/NFC/casefold checks. The compiler applies forbidden-prefix policy only to `generated`, then collision-checks the combined generated/reserved set. Reserved lifecycle names such as `skill_package_activate` are therefore valid authority inputs and never reject themselves.

`reduce_lifecycle` is exhaustive over the closed action union. Stage verifies `action.qualification.package_digest/storage_identity_digest` against the action's two identity fields and persists that complete record in `StagedPackageV1`; activate copies the complete staged record into `ActivePackageV1` and appends the superseded active record intact to `HistoryEntryV1`. Revoke appends a package-digest tombstone and clears active/staged references without deleting bytes; rollback validates exact history/storage, accepts a freshly produced complete qualification in `RollbackPackageV1`, and only stages. Begin-cutover sets the epoch once; finalize-cutover requires a drained scan digest and records the exact active-set/tool-name digest. Repeated action IDs with different plans are rejected.

- [ ] **Step 6: Verify Task 5 and commit**

Run:

```bash
.venv/bin/python -m pytest -q tests/skill/test_package_qualification.py tests/skill/test_package_planner.py tests/skill/test_active_set_collisions.py -rx
.venv/bin/ruff check agent/skill/package_store.py tests/skill/test_package_qualification.py tests/skill/test_package_planner.py tests/skill/test_active_set_collisions.py
git diff --check
git add agent/skill/package_store.py tests/skill/test_package_qualification.py tests/skill/test_package_planner.py tests/skill/test_active_set_collisions.py
git commit -m "feat(skill): add qualification and lifecycle planner"
```

Expected: qualification has zero installer/network calls; every lifecycle transition and complete-set collision is deterministic and pure.

### Task 6: Expose lifecycle only as eight governed operator tools

**Files:**
- Create: `agent/skill/package_tools.py`
- Create: `tests/skill/test_package_tools.py`
- Create: `tests/skill/test_package_tool_bindings.py`
- Create: `tests/skill/test_package_unknown_commit.py`

**Interfaces:**
- `LifecycleEnvironmentV1(always_reserved_names, legacy_registration_names, ...)`; the first tuple is kernel plus lifecycle operator names, and the second is the legacy registrations composed into this immutable Runtime.
- `LIFECYCLE_TOOL_NAMES`: the exact ordered eight operator registration names consumed by static composition.
- `build_skill_package_registrations(environment: LifecycleEnvironmentV1) -> Sequence[RegisteredTool]`
- Exact registrations: inspect/import/stage/activate/revoke/rollback/begin-cutover/finalize-cutover.

- [ ] **Step 1: Write exposure, approval, private-binding, and model-denial Reds**

```python
def test_lifecycle_registration_matrix_is_exact() -> None:
    registrations = {item.spec.name: item for item in build_skill_package_registrations(environment())}
    assert tuple(registrations) == (
        "skill_package_inspect_source", "skill_package_import", "skill_package_stage",
        "skill_package_activate", "skill_package_revoke", "skill_package_rollback",
        "skill_package_begin_cutover", "skill_package_finalize_cutover",
    )
    assert all(item.exposure is ToolExposure.OPERATOR for item in registrations.values())
    assert registrations["skill_package_inspect_source"].spec.approval_policy is ApprovalPolicy.NEVER
    assert registrations["skill_package_inspect_source"].spec.side_effect is SideEffectClass.READ_ONLY
    for name, item in registrations.items():
        if name != "skill_package_inspect_source":
            assert item.spec.approval_policy is ApprovalPolicy.ALWAYS
            assert item.spec.side_effect is SideEffectClass.EXTERNAL
            assert item.spec.execution_authority is ExecutionAuthorityClass.IN_PROCESS


def test_model_cannot_discover_or_guess_lifecycle_tool() -> None:
    runtime = KernelToolRuntime(build_skill_package_registrations(environment()))
    assert runtime.definitions() == ()
    preparation = runtime.prepare(
        ToolCall("call-1", "skill_package_activate", {"stage_id": "stage-1"}),
        prepare_context(origin=InvocationOrigin.MODEL),
    )
    assert preparation.code == "invocation_origin_mismatch"


def test_source_path_is_durable_private_but_preview_is_redacted(tmp_path: Path) -> None:
    source = build_valid_directory(tmp_path / "private-candidate")
    intent = prepare_operator(
        "skill_package_import",
        {"source": str(source), "declared_version": "1.0.0"},
    )
    assert intent.safety_binding["source_locator"] == str(source.absolute())
    assert str(source.absolute()) not in intent.approval_request.preview
    assert "private-candidate" in intent.approval_request.preview


def test_lifecycle_success_is_bounded_canonical_text_not_source_output() -> None:
    raw = invoke_registration("skill_package_stage", staged_environment())
    assert type(raw) is str
    assert len(raw) <= 16_000
    assert raw == json.dumps(json.loads(raw), sort_keys=True, separators=(",", ":"))
    assert not isinstance(raw, ToolExecutionOutput)
```

- [ ] **Step 2: Run the operator-tool Reds**

Run: `.venv/bin/python -m pytest -q tests/skill/test_package_tools.py tests/skill/test_package_tool_bindings.py tests/skill/test_package_unknown_commit.py -rx`

Expected: collection fails because `agent.skill.package_tools` does not exist.

- [ ] **Step 3: Implement the minimum Green: exact registration factory and durable prepare binding**

```python
LIFECYCLE_TOOL_NAMES = (
    "skill_package_inspect_source",
    "skill_package_import",
    "skill_package_stage",
    "skill_package_activate",
    "skill_package_revoke",
    "skill_package_rollback",
    "skill_package_begin_cutover",
    "skill_package_finalize_cutover",
)


def _spec(name: str, *, inspect: bool = False) -> ToolSpec:
    return ToolSpec(
        name=name,
        version="1",
        description=LIFECYCLE_DESCRIPTIONS[name],
        input_schema=LIFECYCLE_INPUT_SCHEMAS[name],
        risk=ToolRisk.LOW if inspect else ToolRisk.HIGH,
        side_effect=SideEffectClass.READ_ONLY if inspect else SideEffectClass.EXTERNAL,
        approval_policy=ApprovalPolicy.NEVER if inspect else ApprovalPolicy.ALWAYS,
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        egress=EgressClass.NONE,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        safety_policy={"kind": "skill_package_lifecycle_v1", "operation": name.removeprefix("skill_package_")},
        output_limit_chars=16_000,
    )


def build_skill_package_registrations(environment):
    return tuple(
        RegisteredTool(
            spec=_spec(name, inspect=inspect),
            func=_LifecycleCallable(environment, name),
            prepare_binding=_LifecycleBindingPreparer(environment, name),
            exposure=ToolExposure.OPERATOR,
        )
        for name, inspect in (
            (tool_name, tool_name == "skill_package_inspect_source")
            for tool_name in LIFECYCLE_TOOL_NAMES
        )
    )
```

Each input schema has `additionalProperties: false`: inspect/import require `source` plus an exact SemVer `declared_version`; stage requires `package_digest` and `storage_identity_digest`; activate requires `stage_id`; revoke requires `package_digest`; rollback requires `history_id`; begin-cutover has no arguments; finalize-cutover requires `checkpoint_scan_digest` and `active_tool_names_digest`. CLI `--version` maps once to `declared_version`; no callable/action/schema uses a second `version` argument. There is no URL field and no update registration.

`_LifecycleBindingPreparer` acquires a short shared guard, loads one head, and releases it in `finally`. Inspect/import also scan and freeze absolute canonical locator, root descriptor, transport digest, inventory digest, package identity, and source binding. Stage/rollback reopen exact object and freeze a complete qualification. Activate prepare and `environment.rebuild_and_revalidate` both call `effective_runtime_reserved_names(loaded, always_reserved_names=environment.always_reserved_names, legacy_registration_names=environment.legacy_registration_names)`, then freeze/recompute the complete proposed active set and collision-plan digest. Thus begin-cutover immediately removes disabled legacy names from the next-composition collision authority without mutating the current Runtime, and approval cannot substitute a different name set at invoke. Every binding stores the full `SkillLifecyclePlanV1` payload plus a redacted preview; approval projection receives only the preview. `package_tools` is imported from its leaf module; this task makes no `agent.skill.__init__` export.

- [ ] **Step 4: Implement the minimum Green: invoke revalidation and exact outcome mapping**

```python
class _LifecycleCallable:
    def __call__(self, intent: ExecutionIntent):
        prepared = SkillLifecyclePlanV1.from_payload(intent.safety_binding["lifecycle_plan"])
        if self._name == "skill_package_inspect_source":
            result = self._environment.source.reopen_and_verify(
                prepared.action.source_binding
            ).redacted_result()
            return encode_lifecycle_result(result)
        if self._name == "skill_package_import":
            rescanned = self._environment.source.reopen_and_verify(prepared.action.source_binding)
            if rescanned.package.package_digest != prepared.action.package_digest:
                return KnownNotExecuted("source_drift", "The local package source changed; inspect and approve again.")
            imported = self._environment.objects.import_candidate(
                rescanned, self._environment.source, prepared.action.source_binding,
            )
            return encode_lifecycle_result(imported.redacted_result())
        guard = self._environment.repository.try_acquire_exclusive()
        if guard is None:
            return KnownNotExecuted("lifecycle_busy", "A Skill execution or lifecycle action currently holds the package guard.")
        try:
            loaded = self._environment.repository.load_under_guard(guard)
            current_plan = self._environment.rebuild_and_revalidate(prepared, loaded)
            if current_plan.plan_digest != prepared.plan_digest:
                return KnownNotExecuted("lifecycle_plan_drift", "The package head or qualification changed; approve a fresh plan.")
            outcome = self._environment.repository.compare_and_swap(
                guard, loaded, current_plan.next_snapshot, current_plan.action_id,
            )
            if isinstance(outcome, ConflictV1):
                return KnownNotExecuted("lifecycle_conflict", "The package head changed; approve a fresh plan.")
            return encode_lifecycle_result(current_plan.redacted_result())
        finally:
            guard.release()


def encode_lifecycle_result(payload: Mapping[str, JSONValue]) -> str:
    content = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    if len(content) > 16_000:
        raise ValueError("lifecycle result exceeds its closed output cap")
    return content
```

Import remains outside the ledger guard and produces only an immutable orphan-capable object. Successful lifecycle callables return only the bounded canonical string above; `ToolExecutionOutput`, `ToolResult`, receipts, metadata, and Runtime state are owned by `KernelToolRuntime` and are never returned by a lifecycle callable. `UnknownCommitError` is not caught by `_LifecycleCallable`; tests must prove Runtime enters `AWAITING_RECOVERY`. Task 8 adds the generic opaque recovery binding and registration-specific journal reconciliation; it never retries this callable. Object/qualification/revocation/expected-head drift returns `KnownNotExecuted` before CAS.

- [ ] **Step 5: Verify Task 6 and commit**

Run:

```bash
.venv/bin/python -m pytest -q tests/skill/test_package_tools.py tests/skill/test_package_tool_bindings.py tests/skill/test_package_unknown_commit.py tests/kernel/test_effect_ordering.py tests/kernel/test_runtime_recovery.py -rx
.venv/bin/ruff check agent/skill/package_tools.py tests/skill
git diff --check
git add agent/skill/package_tools.py tests/skill/test_package_tools.py tests/skill/test_package_tool_bindings.py tests/skill/test_package_unknown_commit.py
git commit -m "feat(skill): add governed lifecycle operator tools"
```

Expected: all eight registrations use OPERATOR origin; import/stage/activate/revoke/rollback follow existing approval and EXECUTING checkpoints; `Conflict` is known nonexecution and `UnknownCommitError` reaches recovery.

### Task 7: Add the shared execution gate and one immutable startup composition

**Files:**
- Create: `agent/skill/package_composition.py`
- Modify: `agent/skill/catalog.py`
- Modify: `agent/skill/tools.py`
- Modify: `agent/composition.py`
- Create: `tests/skill/test_lifecycle_activation_gate.py`
- Create: `tests/skill/test_package_composition.py`
- Modify: `tests/skill/test_integration.py`
- Modify: `tests/architecture/test_single_loop_static.py`
- Modify: `tests/architecture/test_dependency_dag.py`

**Interfaces:**
- `load_active_skill_set(snapshot, *, object_store, qualification_authority) -> ActiveSkillSetV1`
- `RepositorySkillActivationGate.acquire_execution_guard(*, expected_snapshot_digest: str, package_digest: str, storage_identity_digest: str, qualification_digest: str) -> SkillExecutionGuardV1 | ActivationGateDecisionV1`
- `RepositoryLegacySkillGate.require_prepare_allowed(tool_identity: str) -> None`
- `RepositoryLegacySkillGate.acquire_invoke_guard(tool_identity: str) -> SkillExecutionGuardV1 | KnownNotExecuted`
- `SkillLifecycleResources(active_set, active_snapshot_digest, registrations, packaged_registrations, operator_registrations, managed_packaged_tool_identities, activation_gate, close)` owns every `PackageObjectRootV1.directory_fd`.
- `build_skill_lifecycle_resources(environment, *, max_tool_result_chars, legacy_catalog_loader: Callable[[], SkillCatalog] | None = None)`; the loader is invoked at most once and only when the already-loaded durable snapshot has no `legacy_prepare_disabled_epoch`. `environment` contains `base_runtime_reserved_names` for non-Skill kernel registrations, the already-constructed 020a executor, and explicit workspace/temp/state/home/system/private roots, never an adapter tied to another active set.

- [ ] **Step 1: Write linearization, head-drift, and restart Reds**

```python
def test_prepare_guard_is_short_but_invoke_guard_spans_execute_readback_and_commit() -> None:
    trace: list[str] = []
    gate = tracing_gate(trace)
    adapter = tracing_packaged_adapter(trace)
    registration = packaged_registration(gate, adapter)
    intent = prepare_model(registration)
    assert trace == ["shared_acquire", "head_validate", "shared_release"]
    invoke_model(registration, intent)
    assert trace == [
        "shared_acquire", "head_validate", "shared_release",
        "shared_acquire", "head_validate", "spawn", "readback", "host_commit", "shared_release",
    ]


def test_revoke_wins_before_execution_guard_and_causes_zero_spawn() -> None:
    with acquired_exclusive(repository()) as revoke_guard:
        decision = activation_gate().acquire_execution_guard(
            expected_snapshot_digest=STARTUP_DIGEST,
            package_digest=PACKAGE_DIGEST,
            storage_identity_digest=STORAGE_DIGEST,
            qualification_digest=QUALIFICATION_DIGEST,
        )
        assert decision == ActivationGateDecisionV1.RESTART_REQUIRED
        assert adapter().spawn_calls == 0


def test_any_head_change_requires_restart_without_hot_registration() -> None:
    resources = build_resources(active_snapshot())
    apply_unrelated_stage_mutation(resources.environment.repository)
    decision = resources.activation_gate.acquire_execution_guard(
        expected_snapshot_digest=resources.active_snapshot_digest,
        package_digest=PACKAGE_DIGEST,
        storage_identity_digest=STORAGE_DIGEST,
        qualification_digest=QUALIFICATION_DIGEST,
    )
    assert decision is ActivationGateDecisionV1.RESTART_REQUIRED
    assert names(resources.registrations) == names_from(active_snapshot())


def test_active_loader_materializes_complete_021_owned_shape() -> None:
    loaded = active_snapshot()
    active_set = load_active_skill_set(
        loaded,
        object_store=object_store(),
        qualification_authority=qualification_authority(),
    )
    item = active_set.packages[0]
    assert item.active.package_digest == PACKAGE_DIGEST
    assert item.stored.package.package_digest == PACKAGE_DIGEST
    assert item.qualification == loaded.active[0].qualification
    assert item.descriptor.name == item.active.name
    assert item.manifest.package_name == item.active.name
    assert item.requirements.requirements_digest == item.stored.package.requirements_digest
    assert item.runtime_closure.closure_digest == item.qualification.hermetic_runtime_closure_digest
    assert item.object_root.package_digest == item.active.package_digest
    assert active_set.instruction_catalog.descriptors == (item.descriptor,)
    assert active_set.snapshot_digest == loaded.snapshot_digest


def test_restart_loader_rebuilds_byte_sorted_script_descriptors_from_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, objects, authority = persisted_active_environment(
        scripts={"scripts/z.py": b"print('z')\n", "scripts/a.py": b"print('a')\n"},
    )
    observed: list[tuple[ExecutableScriptDescriptorV1, ...]] = []
    original = package_composition.decode_executable_manifest

    def record_decoder(raw: bytes, *, declared_scripts):
        observed.append(declared_scripts)
        return original(raw, declared_scripts=declared_scripts)

    monkeypatch.setattr(package_composition, "decode_executable_manifest", record_decoder)
    persisted = repository.reopen().load()
    load_active_skill_set(
        persisted,
        object_store=objects.reopen(),
        qualification_authority=authority,
    )
    stored = objects.load_exact(
        persisted.active[0].package_digest,
        persisted.active[0].storage_identity_digest,
    )
    expected = tuple(
        ExecutableScriptDescriptorV1(
            relative_path=item.relative_path,
            size_bytes=item.size_bytes,
            sha256=item.sha256,
        )
        for item in stored.inventory
        if item.role is PackageRole.SCRIPT
    )
    assert tuple(item.relative_path for item in expected) == (
        "scripts/a.py", "scripts/z.py",
    )
    assert observed == [expected]


@pytest.mark.parametrize("drift", [
    "runtime_closure", "sandbox_backend", "packaged_policy", "resource_limiter",
])
def test_restart_loader_rejects_persisted_qualification_after_host_drift(drift: str) -> None:
    repository, objects, authority = persisted_active_environment()
    persisted = repository.reopen().load()
    drifted_authority = authority.with_drift(drift)
    with pytest.raises(ActiveSkillSetLoadError, match="qualification drift"):
        load_active_skill_set(
            persisted,
            object_store=objects.reopen(),
            qualification_authority=drifted_authority,
        )
    assert drifted_authority.install_calls == 0


def test_composition_calls_020b_builder_once_with_same_active_set() -> None:
    resources, calls = build_resources_with_recording_020b_builder(active_snapshot())
    assert len(calls) == 1
    assert calls[0].active_set is resources.active_set
    assert calls[0].activation_gate is resources.activation_gate
    assert resources.registrations == (*calls[0].returned, *resources.operator_registrations)


def test_repository_legacy_gate_reads_current_epoch_without_restart() -> None:
    repository = repository_with_legacy_gate_open()
    gate = RepositoryLegacySkillGate(repository)
    gate.require_prepare_allowed(LEGACY_TOOL_IDENTITY)
    apply_begin_cutover_under_exclusive(repository, disabled_epoch=7)
    with pytest.raises(LegacySkillPrepareDisabled):
        gate.require_prepare_allowed(LEGACY_TOOL_IDENTITY)


def test_pre_finalize_restart_skips_legacy_loader_and_composes_same_name_packaged_only() -> None:
    environment = environment_after_begin_then_same_name_package_activation(
        packaged_tool_name="skill__pdf-workspace__inspect",
        legacy_tool_name="skill__pdf-workspace__inspect",
    )
    loader_calls = 0

    def forbidden_legacy_loader() -> SkillCatalog:
        nonlocal loader_calls
        loader_calls += 1
        raise AssertionError("disabled legacy catalog must not be loaded")

    resources = build_skill_lifecycle_resources(
        environment.reopen_after_crash(),
        max_tool_result_chars=16_000,
        legacy_catalog_loader=forbidden_legacy_loader,
    )
    matching = tuple(
        item for item in resources.registrations
        if item.spec.name == "skill__pdf-workspace__inspect"
    )
    assert loader_calls == 0
    assert matching == tuple(
        item for item in resources.packaged_registrations
        if item.spec.name == "skill__pdf-workspace__inspect"
    )
    assert len(matching) == 1


def test_agent_skill_package_root_stays_leaf_only() -> None:
    tree = ast.parse(Path("agent/skill/__init__.py").read_text(encoding="utf-8"))
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    imported_modules.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    imported_names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert "agent.skill.package_composition" not in imported_modules
    assert "package_composition" not in imported_modules
    assert "agent.skill.executable_composition" not in imported_modules
    assert "executable_composition" not in imported_modules
    assert imported_names.isdisjoint({
        "build_skill_lifecycle_resources",
        "build_packaged_skill_registrations",
        "PackagedSkillExecutionAdapter",
    })
```

- [ ] **Step 2: Run activation/composition Reds**

Run: `.venv/bin/python -m pytest -q tests/skill/test_lifecycle_activation_gate.py tests/skill/test_package_composition.py tests/skill/test_integration.py tests/architecture/test_single_loop_static.py tests/architecture/test_dependency_dag.py -rx`

Expected: tests fail because `package_composition` and the injected legacy gate do not exist.

- [ ] **Step 3: Implement the minimum Green: a closed activation gate**

```python
class RepositorySkillActivationGate(SkillActivationGate):
    def __init__(self, repository, startup_snapshot, object_store, qualification_authority):
        self._repository = repository
        self._startup = startup_snapshot
        self._objects = object_store
        self._qualification = qualification_authority

    def acquire_execution_guard(
        self,
        *,
        expected_snapshot_digest,
        package_digest,
        storage_identity_digest,
        qualification_digest,
    ):
        guard = self._repository.try_acquire_shared()
        if guard is None:
            return ActivationGateDecisionV1.RESTART_REQUIRED
        try:
            current = self._repository.load_under_guard(guard)
            if expected_snapshot_digest != self._startup.snapshot_digest or current.snapshot_digest != self._startup.snapshot_digest:
                guard.release()
                return ActivationGateDecisionV1.RESTART_REQUIRED
            active = next((item for item in current.active if item.package_digest == package_digest), None)
            if active is None or any(item.package_digest == package_digest for item in current.revocations):
                guard.release()
                return ActivationGateDecisionV1.REVOKED
            if (
                active.storage_identity_digest != storage_identity_digest
                or active.qualification_digest != qualification_digest
            ):
                guard.release()
                return ActivationGateDecisionV1.RESTART_REQUIRED
            stored = self._objects.load_exact(active.package_digest, active.storage_identity_digest)
            if not self._qualification.revalidate(stored, active.qualification):
                guard.release()
                return ActivationGateDecisionV1.RESTART_REQUIRED
            return guard
        except (PackageObjectIdentityDrift, PackageObjectCorruption):
            guard.release()
            return ActivationGateDecisionV1.RESTART_REQUIRED
        except Exception:
            guard.release()
            raise
```

The gate never lists packages, constructs tools, mutates a store, or calls the sandbox. The 020b registration uses this method once during prepare and immediately releases a returned guard; invoke calls it again and releases only after `PackagedSkillExecutionAdapter.execute` has completed structured read-back and any host commit.

Implement the legacy gate against that same repository and lock domain:

```python
class RepositoryLegacySkillGate:
    def __init__(self, repository):
        self._repository = repository

    def require_prepare_allowed(self, tool_identity):
        guard = self._repository.try_acquire_shared()
        if guard is None:
            raise LegacySkillGateBusy("lifecycle mutation is in progress")
        try:
            current = self._repository.load_under_guard(guard)
            if current.cutover.legacy_prepare_disabled_epoch is not None:
                raise LegacySkillPrepareDisabled("mutable Skill prepare is disabled")
        finally:
            guard.release()

    def acquire_invoke_guard(self, tool_identity):
        guard = self._repository.try_acquire_shared()
        if guard is None:
            return KnownNotExecuted(
                "legacy_skill_busy",
                "A Skill lifecycle mutation is in progress; prepare again.",
            )
        current = self._repository.load_under_guard(guard)
        if current.cutover.legacy_prepare_disabled_epoch is not None:
            guard.release()
            return KnownNotExecuted(
                "legacy_prepare_disabled",
                "Mutable Skill execution is disabled; import, stage, and activate the package.",
            )
        return guard
```

`agent.skill.tools.build_skill_tool_registrations(..., legacy_gate=gate)` calls `require_prepare_allowed` during every legacy activation/resource prepare. Its callable calls `acquire_invoke_guard` again immediately before touching the mutable catalog and holds the returned SH guard through the complete bounded activation/resource read, releasing it in one `finally`. It never upgrades SH to EX and never caches a cutover epoch.

- [ ] **Step 4: Implement the minimum Green: immutable startup resources and legacy prepare gating**

```python
@dataclass(frozen=True, slots=True)
class SkillLifecycleResources:
    active_set: ActiveSkillSetV1
    active_snapshot_digest: str
    registrations: tuple[RegisteredTool, ...]
    packaged_registrations: tuple[RegisteredTool, ...]
    operator_registrations: tuple[RegisteredTool, ...]
    managed_packaged_tool_identities: frozenset[str]
    activation_gate: SkillActivationGate
    close: Callable[[], None]

    def __post_init__(self) -> None:
        if self.active_snapshot_digest != self.active_set.snapshot_digest:
            raise ValueError("resource snapshot identity mismatch")
        packaged = frozenset(
            item.spec.identity_digest for item in self.packaged_registrations
        )
        if packaged != self.managed_packaged_tool_identities:
            raise ValueError("managed packaged identity allowlist mismatch")
        if any(item not in self.registrations for item in (
            *self.packaged_registrations,
            *self.operator_registrations,
        )):
            raise ValueError("resource registration projections do not match")


def load_active_skill_set(snapshot, *, object_store, qualification_authority):
    materialized: list[MaterializedActivePackageV1] = []
    package_catalogs: list[SkillCatalog] = []
    opened_roots: list[PackageObjectRootV1] = []
    try:
        for active in snapshot.active:
            stored = object_store.load_exact(
                active.package_digest, active.storage_identity_digest,
            )
            if (
                stored.package.name != active.name
                or stored.package.version != active.version
                or active.qualification.package_digest != active.package_digest
                or active.qualification.storage_identity_digest
                != active.storage_identity_digest
                or not qualification_authority.revalidate(stored, active.qualification)
            ):
                raise ActiveSkillSetLoadError("active package identity or qualification drift")
            root = object_store.open_exact(
                active.package_digest, active.storage_identity_digest,
            )
            opened_roots.append(root)
            instruction_catalog = build_stored_skill_catalog(
                root=root,
                inventory=stored.inventory,
                read_exact=object_store.read_exact,
            )
            executable = None
            requirements = None
            manifest_entry = next(
                (item for item in stored.inventory if item.role is PackageRole.MANIFEST),
                None,
            )
            if manifest_entry is not None:
                scripts = tuple(
                    ExecutableScriptDescriptorV1(
                        relative_path=item.relative_path,
                        size_bytes=item.size_bytes,
                        sha256=item.sha256,
                    )
                    for item in sorted(
                        stored.inventory,
                        key=lambda entry: entry.relative_path.encode("utf-8"),
                    )
                    if item.role is PackageRole.SCRIPT
                )
                executable = decode_executable_manifest(
                    object_store.read_exact(
                        root,
                        manifest_entry.relative_path,
                        manifest_entry.sha256,
                        max_bytes=MAX_MANIFEST_BYTES,
                    ),
                    declared_scripts=scripts,
                )
                if (
                    executable.package_name != stored.package.name
                    or executable.package_version != stored.package.version
                    or executable_manifest_digest(executable)
                    != stored.package.manifest_digest
                ):
                    raise ActiveSkillSetLoadError("stored executable manifest drift")
                requirements_entry = next(
                    (
                        item
                        for item in stored.inventory
                        if item.role is PackageRole.REQUIREMENTS
                    ),
                    None,
                )
                if requirements_entry is None:
                    raise ActiveSkillSetLoadError("executable package has no requirements")
                requirements = decode_portable_requirements(
                    object_store.read_exact(
                        root,
                        requirements_entry.relative_path,
                        requirements_entry.sha256,
                        max_bytes=MAX_REQUIREMENTS_BYTES,
                    )
                )
                if portable_requirements_digest(requirements) != stored.package.requirements_digest:
                    raise ActiveSkillSetLoadError("stored requirements drift")
            if instruction_catalog.descriptors[0].name != stored.package.name:
                raise ActiveSkillSetLoadError("stored SKILL name drift")
            package_catalogs.append(instruction_catalog)
            runtime_closure = qualification_authority.runtime_closure_for(
                stored, active.qualification,
            )
            materialized.append(MaterializedActivePackageV1(
                active=active,
                stored=stored,
                qualification=active.qualification,
                object_root=root,
                descriptor=instruction_catalog.descriptors[0],
                manifest=executable,
                requirements=requirements,
                runtime_closure=runtime_closure,
            ))
        packages = tuple(sorted(materialized, key=lambda item: item.active.name.encode()))
        merged_catalog = merge_stored_skill_catalogs(
            tuple(
                next(
                    catalog
                    for catalog in package_catalogs
                    if catalog.descriptors[0].name == item.active.name
                )
                for item in packages
            ),
        )
        return ActiveSkillSetV1(
            snapshot_digest=snapshot.snapshot_digest,
            instruction_catalog=merged_catalog,
            packages=packages,
        )
    except Exception:
        for root in reversed(opened_roots):
            os.close(root.directory_fd)
        raise


def build_skill_lifecycle_resources(
    environment,
    *,
    max_tool_result_chars,
    legacy_catalog_loader=None,
):
    loaded = environment.repository.load()
    legacy = ()
    legacy_names: tuple[str, ...] = ()
    if (
        loaded.cutover.legacy_prepare_disabled_epoch is None
        and legacy_catalog_loader is not None
    ):
        legacy_catalog = legacy_catalog_loader()
        legacy_gate = RepositoryLegacySkillGate(environment.repository)
        legacy = build_skill_tool_registrations(
            legacy_catalog,
            max_tool_result_chars=max_tool_result_chars,
            legacy_gate=legacy_gate,
        )
        legacy_names = tuple(sorted(
            (item.spec.name for item in legacy),
            key=lambda name: name.encode("utf-8"),
        ))
    always_reserved_names = tuple(sorted(
        (*environment.base_runtime_reserved_names, *LIFECYCLE_TOOL_NAMES),
        key=lambda name: name.encode("utf-8"),
    ))
    scoped_environment = dataclasses.replace(
        environment,
        always_reserved_names=always_reserved_names,
        legacy_registration_names=legacy_names,
    )
    active_set = load_active_skill_set(
        loaded,
        object_store=environment.objects,
        qualification_authority=environment.qualification,
    )
    runtime_reserved_names = effective_runtime_reserved_names(
        loaded,
        always_reserved_names=always_reserved_names,
        legacy_registration_names=legacy_names,
    )
    compile_active_tool_names(active_set, runtime_reserved_names)
    gate = RepositorySkillActivationGate(
        environment.repository, loaded, environment.objects, environment.qualification,
    )
    execution_adapter = PackagedSkillExecutionAdapter(
        active_set=active_set,
        workspace_root=environment.workspace_root,
        temp_root=environment.temp_root,
        state_root=environment.state_root,
        home_root=environment.home_root,
        system_runtime_roots=environment.system_runtime_roots,
        system_runtime_digest=environment.system_runtime_digest,
        private_roots=environment.private_roots,
        sandbox_executor=environment.sandbox_executor,
    )
    packaged = build_packaged_skill_registrations(
        active_set, gate, execution_adapter, max_tool_result_chars=max_tool_result_chars,
    )
    operator = build_skill_package_registrations(scoped_environment)
    if tuple(item.spec.name for item in operator) != LIFECYCLE_TOOL_NAMES:
        raise ValueError("lifecycle registration names drifted")
    return SkillLifecycleResources(
        active_set=active_set,
        active_snapshot_digest=loaded.snapshot_digest,
        registrations=(*legacy, *packaged, *operator),
        packaged_registrations=packaged,
        operator_registrations=operator,
        managed_packaged_tool_identities=frozenset(
            item.spec.identity_digest for item in packaged
        ),
        activation_gate=gate,
        close=lambda: close_active_object_roots(active_set.packages),
    )
```

`build_stored_skill_catalog(root, inventory, read_exact)` and `merge_stored_skill_catalogs(catalogs)` are the only new APIs in `agent.skill.catalog`. The first parses the exact stored `SKILL.md` bytes and declared `references/`/`assets/` inventory, creates one descriptor with the pinned object-root/file identities, and sets its private `_paths[name]` to `root.canonical_path`; it never calls `build_skill_catalog` or rescans a mutable root. The second byte-sorts descriptors, merges those exact private paths, computes the ordinary `SkillCatalog.catalog_digest`, and rejects exact/NFC/casefold duplicates. Existing `read_activation`/`read_resource` then retain their no-follow inode/content revalidation against the immutable object. The active loader rebuilds byte-sorted `ExecutableScriptDescriptorV1(relative_path, size_bytes, sha256)` values only from the stored canonical `SCRIPT` inventory and passes those descriptors to the 020b decoder; it never passes naked paths or consults a mutable source.

`environment.base_runtime_reserved_names` is the exact byte-sorted set of non-Skill kernel names; it excludes lifecycle, legacy, and packaged names. Composition adds exact `LIFECYCLE_TOOL_NAMES`, and adds legacy registration names only when the loaded snapshot has no disabled epoch. Activation prepare and startup both use `effective_runtime_reserved_names`, so they compile the same next-composition authority. The repository snapshot is loaded before `legacy_catalog_loader` can run. If `legacy_prepare_disabled_epoch` is present, including after a begin/activation crash before finalize, the loader is not called, no mutable-root registration is created, and disabled legacy names cannot collide with a same-name packaged registration. In a process composed before begin, the legacy registrations remain immutable but their prepare/invoke gate fails closed; the freshly loaded disabled epoch excludes their names only from the approved next composition.

`close_active_object_roots` closes every unique descriptor exactly once during composition shutdown; failure to materialize any package closes all already-opened descriptors and aborts startup before model exposure. The repository-backed legacy gate rejects every new mutable-root activation/resource preparation once `legacy_prepare_disabled_epoch` is set, including in the same process that executed begin-cutover; it is not consulted by Runtime cancel, approval rejection, or recovery. A previously prepared invocation must acquire a new invoke SH guard and therefore cannot bypass a later begin-cutover. `build_composition` receives `SkillLifecycleResources.registrations` as the complete Skill registration tuple, incorporates `active_set.active_set_digest` and `active_snapshot_digest` into `authority_snapshot`, and constructs exactly one `KernelToolRuntime`. It imports `build_skill_lifecycle_resources` from `agent.skill.package_composition`, never from `agent.skill`; 020b Task 7 receives these resources read-only for integration tests and may not call the builder again or modify `agent/composition.py`. Architecture tests assert one call to `build_packaged_skill_registrations`, `agent.skill.__init__` imports neither composition module, `package_composition` imports neither provider nor Runtime loop, no dynamic registry API exists, and only `agent/runtime/loop.py` calls `ToolRuntime.invoke`.

- [ ] **Step 5: Verify Task 7 and commit**

Run:

```bash
.venv/bin/python -m pytest -q tests/skill/test_lifecycle_activation_gate.py tests/skill/test_package_composition.py tests/skill/test_integration.py tests/architecture/test_single_loop_static.py tests/architecture/test_dependency_dag.py -rx
.venv/bin/ruff check agent/skill/package_composition.py agent/skill/catalog.py agent/skill/tools.py agent/composition.py tests/skill tests/architecture
git diff --check
git add agent/skill/package_composition.py agent/skill/catalog.py agent/skill/tools.py agent/composition.py tests/skill/test_lifecycle_activation_gate.py tests/skill/test_package_composition.py tests/skill/test_integration.py tests/architecture/test_single_loop_static.py tests/architecture/test_dependency_dag.py
git commit -m "feat(skill): compose immutable active package set"
```

Expected: the shared/exclusive ordering is non-vacuously traced; a head change never changes the current process's definitions and always requires restart; a disabled epoch survives restart without loading or composing legacy registrations, and the package root remains leaf-only.

### Task 8: Make cutover durable, identity-aware, bounded, and drainable

**Files:**
- Create: `agent/skill/cutover.py`
- Modify: `agent/continuity/sessions.py`
- Modify: `agent/runtime/contracts.py`
- Modify: `agent/runtime/state.py`
- Modify: `agent/runtime/checkpoint.py`
- Modify: `agent/runtime/tools.py`
- Modify: `agent/runtime/loop.py`
- Modify: `agent/skill/package_tools.py`
- Create: `tests/skill/test_cutover.py`
- Create: `tests/continuity/test_skill_cutover_scan.py`
- Modify: `tests/kernel/test_checkpoint.py`
- Modify: `tests/kernel/test_checkpoint_recovery.py`
- Modify: `tests/kernel/test_runtime_recovery.py`

**Interfaces:**
- `load_state_root_checkpoints(state_root, *, max_workspaces=128, max_checkpoints=32_768)`
- `classify_legacy_skill_work(state, *, legacy_tool_identities, managed_packaged_tool_identities) -> LegacyWorkItemV1 | None`
- `scan_cutover_readiness(checkpoints, *, legacy_tool_identities, managed_packaged_tool_identities) -> CutoverScanV1`
- `OpaqueToolRecoveryBindingV1`, `ToolRecoveryDispositionV1`, and `ToolRecoveryDraftV1`
- `ApprovalRequest.tool_identity`, `ExecutionIntent.recovery_binding`, and `ExecutingIntentRecord(tool_identity, recovery_binding)`
- `RegisteredTool(recovery_binding_preparer, reconcile_unknown)` and `KernelToolRuntime.reconcile_unknown(executing) -> ToolResult | None`

- [ ] **Step 1: Write identity-aware drain and conservative legacy Reds**

```python
@pytest.mark.parametrize("status", [
    ActiveRunStatus.AWAITING_APPROVAL,
    ActiveRunStatus.RUNNABLE,
    ActiveRunStatus.AWAITING_RECOVERY,
])
def test_nonterminal_legacy_identity_blocks_finalize(status: ActiveRunStatus) -> None:
    state = state_with_legacy_tool(status=status, tool_identity=LEGACY_TOOL_IDENTITY)
    scan = scan_cutover_readiness(
        (("workspace", "conversation", state),),
        legacy_tool_identities=frozenset({LEGACY_TOOL_IDENTITY}),
        managed_packaged_tool_identities=frozenset({PACKAGED_TOOL_IDENTITY}),
    )
    assert scan.ready is False
    assert scan.blockers[0].required_action in {"reject_or_cancel", "resolve_unknown_outcome"}


def test_packaged_tool_with_same_visible_name_does_not_block_legacy_drain() -> None:
    state = state_with_packaged_tool(name="skill__pdf", tool_identity=PACKAGED_TOOL_IDENTITY)
    assert scan_cutover_readiness(
        (("w", "c", state),),
        legacy_tool_identities=frozenset({LEGACY_TOOL_IDENTITY}),
        managed_packaged_tool_identities=frozenset({PACKAGED_TOOL_IDENTITY}),
    ).ready is True


def test_unrecognized_nonterminal_skill_identity_blocks_finalize() -> None:
    state = state_with_packaged_tool(name="skill__pdf", tool_identity=UNRECOGNIZED_IDENTITY)
    scan = scan_cutover_readiness(
        (("w", "c", state),),
        legacy_tool_identities=frozenset({LEGACY_TOOL_IDENTITY}),
        managed_packaged_tool_identities=frozenset({PACKAGED_TOOL_IDENTITY}),
    )
    assert scan.ready is False
    assert scan.blockers[0].reason == "unrecognized_skill_identity"


def test_old_checkpoint_without_identity_blocks_conservatively() -> None:
    state = migrated_old_state(current_tool_name="skill__legacy")
    scan = scan_cutover_readiness(
        (("w", "c", state),),
        legacy_tool_identities=frozenset(),
        managed_packaged_tool_identities=frozenset({PACKAGED_TOOL_IDENTITY}),
    )
    assert scan.ready is False
    assert scan.blockers[0].reason == "legacy_identity_unavailable"
```

- [ ] **Step 2: Write begin/finalize atomicity and full-enumeration Reds**

```python
def test_begin_cutover_persists_gate_before_scan_and_keeps_it_closed_on_blocker() -> None:
    environment = tracing_cutover_environment(blocked_checkpoint())
    result = invoke_governed("skill_package_begin_cutover", environment)
    assert result.executed is True
    assert environment.trace[:2] == ["exclusive_acquire", "gate_cas_applied"]
    assert environment.repository.load().cutover.legacy_prepare_disabled_epoch is not None
    assert json.loads(result.content)["drained"] is False


def test_finalize_requires_exact_fresh_scan_and_active_name_digest() -> None:
    stale = drained_scan()
    add_checkpoint_after_scan()
    result = invoke_governed(
        "skill_package_finalize_cutover",
        environment(),
        checkpoint_scan_digest=stale.scan_digest,
        active_tool_names_digest=ACTIVE_NAMES_DIGEST,
    )
    assert result == KnownNotExecuted("cutover_scan_drift", "Checkpoint inventory changed; scan and approve again.")


def test_same_process_begin_immediately_rejects_new_legacy_prepare() -> None:
    harness = cutover_concurrency_harness()
    harness.operator_approve_and_resume("begin-cutover")
    assert harness.legacy_prepare().code == "legacy_prepare_disabled"


def test_legacy_prepare_before_begin_does_not_authorize_later_invoke() -> None:
    harness = cutover_concurrency_harness()
    prepared = harness.prepare_legacy_resource()
    assert harness.trace == ["legacy_prepare_sh_acquire", "epoch_read", "sh_release"]
    harness.operator_approve_and_resume("begin-cutover")
    result = harness.invoke_prepared_legacy_resource(prepared)
    assert result == KnownNotExecuted(
        "legacy_prepare_disabled",
        "Mutable Skill execution is disabled; import, stage, and activate the package.",
    )
    assert harness.legacy_resource_read_calls == 0


def test_legacy_invoke_shared_guard_linearizes_before_begin_exclusive() -> None:
    harness = cutover_concurrency_harness()
    running = harness.pause_legacy_invoke_after_shared_guard()
    assert harness.try_begin_cutover().code == "lifecycle_busy"
    running.finish_bounded_resource_read()
    harness.operator_approve_and_resume("begin-cutover")
    assert harness.trace[-5:] == [
        "legacy_invoke_sh_acquire", "resource_read", "sh_release",
        "begin_ex_acquire", "gate_cas_applied",
    ]


def test_applied_cas_then_result_checkpoint_failure_reconciles_without_replay(tmp_path: Path) -> None:
    harness = lifecycle_recovery_harness(tmp_path, fail_result_checkpoint_once=True)
    pending = harness.operator_approve_and_resume("activate", stage_id=harness.stage_id)
    assert pending.status is RunStatus.AWAITING_RECOVERY
    assert harness.lifecycle_callable_calls == 1
    assert harness.repository.load().head_action_id == pending.action_id
    recovered = harness.resume_runtime()
    assert recovered.status is RunStatus.COMPLETED
    assert harness.lifecycle_callable_calls == 1
    assert harness.repository.reconcile_calls == 1
    assert harness.recorded_result.executed is True
```

- [ ] **Step 3: Run the cutover Reds**

Run: `.venv/bin/python -m pytest -q tests/skill/test_cutover.py tests/continuity/test_skill_cutover_scan.py tests/kernel/test_checkpoint.py tests/kernel/test_checkpoint_recovery.py tests/kernel/test_runtime_recovery.py tests/skill/test_package_unknown_commit.py -rx`

Expected: tests fail because tool identities/recovery bindings are not persisted, ToolRuntime has no generic reconciliation dispatch, and the state-root scanner/cutover classifier do not exist.

- [ ] **Step 4: Implement the minimum Green: persist exact tool identity and one opaque recovery binding**

```python
class ToolRecoveryDispositionV1(StrEnum):
    COMMITTED = "committed"
    NOT_COMMITTED = "not_committed"
    STILL_UNKNOWN = "still_unknown"


@dataclass(frozen=True, slots=True)
class OpaqueToolRecoveryBindingV1:
    schema: str
    payload: dict[str, JSONValue]
    binding_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.schema:
            raise ValueError("opaque recovery schema must not be empty")
        _assert_json_compatible(self.payload, path="opaque_recovery.payload")
        object.__setattr__(self, "payload", _freeze_json_dict(self.payload))
        object.__setattr__(self, "binding_digest", canonical_json_digest({
            "schema": self.schema,
            "payload": self.payload,
        }))


@dataclass(frozen=True, slots=True)
class ToolRecoveryDraftV1:
    disposition: ToolRecoveryDispositionV1
    content: str
    code: str

    def __post_init__(self) -> None:
        if not self.code or len(self.content) > 16_000:
            raise ValueError("tool recovery draft is not bounded")


@dataclass(frozen=True, slots=True)
class ExecutingIntentRecord:
    tool_call_id: str
    tool_identity: str | None
    intent_digest: str
    idempotency_key: str
    recovery_binding: OpaqueToolRecoveryBindingV1 | None = None
    side_effect: SideEffectClass = SideEffectClass.WRITE
    egress: EgressClass = EgressClass.NONE
    execution_authority: ExecutionAuthorityClass = field(kw_only=True)
    operation: str = "legacy_effect"
    request_identity: str | None = None
```

Add `tool_identity: str | None` to `ApprovalRequest` and `recovery_binding: OpaqueToolRecoveryBindingV1 | None` to `ExecutionIntent`. `KernelToolRuntime._approval_request` sets the tool identity and binds any registration-produced opaque recovery object into the exact intent digest; `AgentRuntime` passes both to `mark_executing`; checkpoint encode/decode round-trips every nested field and recomputes `binding_digest`. Bump the checkpoint schema once. Only pre-021 schemas may migrate missing tool/recovery fields to `None`; current-schema missing/extra keys fail closed. No Runtime branch parses `schema`/`payload` or recognizes lifecycle action names.

- [ ] **Step 5: Implement the minimum Green: ToolRuntime-owned recovery dispatch and lifecycle journal adapter**

Extend only the existing registration and Runtime owner:

```python
RecoveryBindingPreparer = Callable[
    [dict[str, JSONValue]], OpaqueToolRecoveryBindingV1 | None
]
UnknownOutcomeReconciler = Callable[
    [OpaqueToolRecoveryBindingV1], ToolRecoveryDraftV1
]


@dataclass(frozen=True, slots=True)
class RegisteredTool:
    spec: ToolSpec
    func: ToolCallable
    prepare_binding: BindingPreparer | None = None
    prepare_authority_binding: AuthorityBindingPreparer | None = None
    policy: ToolPolicy | None = None
    exposure: ToolExposure = ToolExposure.MODEL
    recovery_binding_preparer: RecoveryBindingPreparer | None = None
    reconcile_unknown: UnknownOutcomeReconciler | None = None


def reconcile_unknown(
    self,
    executing: ExecutingIntentRecord,
) -> ToolResult | None:
    binding = executing.recovery_binding
    if binding is None or executing.tool_identity is None:
        return None
    registration = self._tools_by_identity.get(executing.tool_identity)
    if registration is None or registration.reconcile_unknown is None:
        return None
    draft = registration.reconcile_unknown(binding)
    if draft.disposition is ToolRecoveryDispositionV1.STILL_UNKNOWN:
        return None
    return ToolResult(
        tool_call_id=executing.tool_call_id,
        content=draft.content,
        is_error=draft.disposition is ToolRecoveryDispositionV1.NOT_COMMITTED,
        executed=draft.disposition is ToolRecoveryDispositionV1.COMMITTED,
        metadata={
            "code": draft.code,
            "tool_identity": executing.tool_identity,
            "recovery_binding_digest": binding.binding_digest,
        },
    )
```

`KernelToolRuntime.__init__` builds `_tools_by_identity` from the same immutable registrations and rejects duplicate identities. `prepare` requires `recovery_binding_preparer` and `reconcile_unknown` to be both present or both absent and permits them only for non-read-only specs. When an `AWAITING_RECOVERY` state has an opaque binding, the existing `AgentRuntime` recovery branch calls `KernelToolRuntime.reconcile_unknown(executing)`; a returned `ToolResult` goes through the existing result checkpoint/advance path, while `None` leaves the existing `RecoveryRequest` pending. It never calls `registration.func` and never switches on tool name, recovery schema, action ID, or lifecycle status.

For the six ledger-CAS registrations only (`stage`, `activate`, `revoke`, `rollback`, `begin_cutover`, `finalize_cutover`), add these registration-owned callbacks in `agent/skill/package_tools.py`:

```python
def build_lifecycle_recovery_binding(binding):
    plan = SkillLifecyclePlanV1.from_payload(binding["lifecycle_plan"])
    return OpaqueToolRecoveryBindingV1(
        schema="skill-lifecycle-journal-reconcile/v1",
        payload={
            "action_id": plan.action_id,
            "next_snapshot_digest": plan.next_snapshot_digest,
            "success_content": encode_lifecycle_result(plan.redacted_result()),
        },
    )


def reconcile_lifecycle_unknown(repository, binding):
    payload = expect_lifecycle_recovery_payload(binding)
    decision = repository.reconcile_action(
        payload["action_id"], payload["next_snapshot_digest"],
    )
    if decision.status is ActionCommitStatus.COMMITTED:
        return ToolRecoveryDraftV1(
            ToolRecoveryDispositionV1.COMMITTED,
            payload["success_content"],
            "lifecycle_commit_reconciled",
        )
    if decision.status is ActionCommitStatus.NOT_COMMITTED:
        return ToolRecoveryDraftV1(
            ToolRecoveryDispositionV1.NOT_COMMITTED,
            "The lifecycle mutation was not committed; prepare and approve a fresh action.",
            "lifecycle_not_committed",
        )
    return ToolRecoveryDraftV1(
        ToolRecoveryDispositionV1.STILL_UNKNOWN,
        "The lifecycle commit outcome is still unknown.",
        "lifecycle_commit_still_unknown",
    )
```

`expect_lifecycle_recovery_payload` exact-matches the schema and the three keys, validates both digests and the bounded canonical `success_content`, and lives only in `agent.skill.package_tools`. Inspect/import have no action-journal recovery binding. This dispatch is a read-only reconciliation of an already-attempted effect; it never replays import, CAS, qualification, or any callable.

- [ ] **Step 6: Implement the minimum Green: bounded state-root enumeration and pure classification**

```python
def classify_legacy_skill_work(
    state,
    *,
    legacy_tool_identities,
    managed_packaged_tool_identities,
):
    active = state.active_run
    if active is None or active.batch_cursor >= len(active.tool_calls):
        return None
    call = active.tool_calls[active.batch_cursor]
    pending = active.pending_request
    identity = (
        pending.tool_identity
        if isinstance(pending, ApprovalRequest)
        else active.executing_intent.tool_identity if active.executing_intent is not None else None
    )
    if identity in legacy_tool_identities:
        return LegacyWorkItemV1.from_state(state, call, "legacy_identity", required_action(active))
    if call.name.startswith("skill__"):
        if identity in managed_packaged_tool_identities:
            return None
        reason = (
            "legacy_identity_unavailable"
            if identity is None
            else "unrecognized_skill_identity"
        )
        return LegacyWorkItemV1.from_state(
            state, call, reason, required_action(active),
        )
    return None
```

`scan_cutover_readiness` requires both identity sets as explicit byte-sorted `frozenset[str]` inputs and rejects overlap. Its managed allowlist is compiled from the exact proposed `ActiveSkillSetV1` ToolSpec identities, never from visible names or prefixes. Presence of `active_run` means the run is nonterminal; after the one `batch_cursor` bounds check, classification does not whitelist any phase/status. Any current `skill__*` call whose persisted identity is absent from that allowlist blocks as legacy/unrecognized, including RUNNABLE or paused work with no persisted identity; only an exact allowlisted managed packaged identity may pass. `load_state_root_checkpoints` pins `state_root/workspaces`, accepts only canonical workspace digest directories and the existing bounded checkpoint/lock names, rejects symlinks/unknown entries, and uses `LocalCheckpointStore.load()` for strict decode. It fails closed when either bound is exceeded; it never silently samples. `CutoverScanV1.scan_digest` binds sorted workspace identity, conversation ID, checkpoint token/revision, `batch_cursor`, tool identity, both identity-set digests, state/status, and blocker resolution action.

- [ ] **Step 7: Implement the minimum Green: begin/finalize under one exclusive guard**

Begin prepare freezes the exact legacy identity set, exact managed packaged identity allowlist, both set digests, and expected head. Invoke acquires EX, revalidates the plan and both identity sets, CASes `legacy_prepare_disabled_epoch`, then—while the same EX guard is held—performs the full checkpoint scan. A blocked scan returns a bounded canonical successful result with redacted conversation IDs and resolution actions; it does not reopen the gate. A crash after gate CAS is reconciled by the generic opaque binding → registration-specific action-journal path and leaves the gate closed.

Finalize prepare/invoke both rescan while EX is held, require zero blockers, exact `scan_digest`, exact managed active-set digest, exact compiled active-tool-name digest, and an already-set gate. CAS writes `finalized_active_set_digest`, `finalized_tool_names_digest`, and `finalized_at_epoch`. Recovery/cancel remain Runtime actions and never consult the legacy prepare gate.

- [ ] **Step 8: Verify Task 8 and commit**

Run:

```bash
.venv/bin/python -m pytest -q tests/skill/test_cutover.py tests/continuity/test_skill_cutover_scan.py tests/kernel/test_checkpoint.py tests/kernel/test_checkpoint_recovery.py tests/kernel/test_runtime_recovery.py tests/skill/test_package_unknown_commit.py -rx
.venv/bin/ruff check agent/skill/cutover.py agent/continuity/sessions.py agent/runtime/contracts.py agent/runtime/state.py agent/runtime/checkpoint.py agent/runtime/tools.py agent/runtime/loop.py agent/skill/package_tools.py tests/skill tests/continuity tests/kernel/test_checkpoint.py tests/kernel/test_checkpoint_recovery.py tests/kernel/test_runtime_recovery.py
git diff --check
git add agent/skill/cutover.py agent/continuity/sessions.py agent/runtime/contracts.py agent/runtime/state.py agent/runtime/checkpoint.py agent/runtime/tools.py agent/runtime/loop.py agent/skill/package_tools.py tests/skill/test_cutover.py tests/continuity/test_skill_cutover_scan.py tests/kernel/test_checkpoint.py tests/kernel/test_checkpoint_recovery.py tests/kernel/test_runtime_recovery.py tests/skill/test_package_unknown_commit.py
git commit -m "feat(skill): add durable mutable-root cutover drain"
```

Expected: begin is durable before scan, blocked drain leaves the gate closed, prepared legacy work cannot bypass a later begin, SH/EX races have one trace, old/unrecognized Skill identities block conservatively, and applied CAS recovery dispatches once without replay.

### Task 9: Add the operator CLI without a lifecycle bypass or combined update saga

**Files:**
- Modify: `agent/cli/actions.py`
- Modify: `agent/cli/app.py`
- Modify: `main.py`
- Create: `tests/cli/test_skill_package_cli.py`
- Modify: `tests/skill/test_integration.py`
- Modify: `tests/architecture/test_cutover_absence.py`

**Interfaces:**
- `build_skill_lifecycle_action(state, *, action_id, command, arguments, submitted_at) -> ExecuteOperatorTool`
- `first-agent skill inspect|import|stage|activate|revoke|rollback|begin-cutover|finalize-cutover`
- Pre-finalization disabled-epoch startup continues with packaged/operator registrations only and never opens `--skill-root`.
- Post-finalization `--skill-root` migration error.

- [ ] **Step 1: Write parser, typed-action, Goal, and bypass Reds**

```python
def test_skill_cli_builds_one_operator_action_and_never_calls_store_directly(monkeypatch) -> None:
    calls: list[ExecuteOperatorTool] = []
    monkeypatch.setattr(main_module, "run_headless", lambda runtime, store, action: calls.append(action) or completed())
    result = main(["--state-root", STATE, "skill", "stage", PACKAGE_DIGEST, STORAGE_DIGEST])
    assert result == 0
    assert len(calls) == 1
    assert calls[0].tool_name == "skill_package_stage"
    assert calls[0].arguments == {"package_digest": PACKAGE_DIGEST, "storage_identity_digest": STORAGE_DIGEST}


def test_skill_cli_without_selected_goal_is_known_rejection() -> None:
    result = invoke_cli_on_new_conversation(
        "skill", "import", str(source()), "--version", "1.0.0",
    )
    assert result.exit_code == 2
    assert result.output == "Skill lifecycle requires an active selected Goal.\n"
    assert object_store_entries() == ()


def test_update_is_three_explicit_actions_not_one_hidden_command() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["skill", "update", "candidate.skillpkg"])
    assert "skill_package_update" not in product_source_text()
```

- [ ] **Step 2: Write post-cutover mutable-root Reds**

```python
def test_finalized_store_rejects_skill_root_without_scanning(tmp_path: Path) -> None:
    root = tmp_path / "must-not-open"
    root.mkdir()
    finalize_lifecycle_store(tmp_path)
    result = run_main(["--state-root", str(tmp_path / "state"), "--skill-root", str(root)])
    assert result.exit_code == 2
    assert "first-agent skill import" in result.output
    assert source_open_count(root) == 0


def test_disabled_pre_finalize_store_skips_skill_root_and_starts_packaged_only(
    tmp_path: Path,
) -> None:
    root = tmp_path / "must-not-open-before-finalize"
    root.mkdir()
    state_root = tmp_path / "state"
    persist_begin_then_same_name_package_activation(state_root)
    started = start_main_with_noop_provider([
        "--state-root", str(state_root),
        "--skill-root", str(root),
    ])
    assert started.exit_code == 0
    assert source_open_count(root) == 0
    assert started.tool_names.count("skill__pdf-workspace__inspect") == 1
    assert started.tool_identity("skill__pdf-workspace__inspect") in (
        started.resources.managed_packaged_tool_identities
    )
```

- [ ] **Step 3: Run CLI Reds**

Run: `.venv/bin/python -m pytest -q tests/cli/test_skill_package_cli.py tests/skill/test_integration.py tests/architecture/test_cutover_absence.py -rx`

Expected: parser rejects `skill` because the subcommands/action builder do not exist.

- [ ] **Step 4: Implement the minimum Green: exact action construction and closed subcommands**

```python
def build_skill_lifecycle_action(state, *, action_id, command, arguments, submitted_at):
    if state.goal is None:
        raise ValueError("Skill lifecycle requires an active selected Goal.")
    tool_name = {
        "inspect": "skill_package_inspect_source",
        "import": "skill_package_import",
        "stage": "skill_package_stage",
        "activate": "skill_package_activate",
        "revoke": "skill_package_revoke",
        "rollback": "skill_package_rollback",
        "begin-cutover": "skill_package_begin_cutover",
        "finalize-cutover": "skill_package_finalize_cutover",
    }[command]
    return ExecuteOperatorTool(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        action_id=action_id,
        tool_name=tool_name,
        arguments=arguments,
        submitted_at=submitted_at,
    )
```

Add exact argparse shapes: inspect/import each take one `source` and required `--version <exact-semver>`; stage takes package+storage digest; activate takes stage ID; revoke takes package digest; rollback takes history ID; begin-cutover takes none; finalize-cutover takes scan+active-name digests. No subcommand accepts URL, command, env, credential, dependency-install, force, no-approval, or auto-activate flags.

The CLI adapter maps parsed `args.version` exactly once:

```python
if args.skill_command in {"inspect", "import"}:
    arguments = {
        "source": args.source,
        "declared_version": args.version,
    }
else:
    arguments = lifecycle_arguments_without_version(args)
```

No `version` key crosses into `ExecuteOperatorTool`; action/transport/planner code uses only `declared_version`.

- [ ] **Step 5: Implement the minimum Green: Runtime routing and cutover startup enforcement**

After the normal session/Goal selection and static composition, build one `ExecuteOperatorTool`, call `run_headless(composition.runtime, store, action)`, and render the returned existing `RunResult`. An approval result exits successfully after displaying the existing request ID/digest; users resolve it through the existing approval command and replay identity. Do not call `RegisteredTool.func`, `KernelToolRuntime.invoke`, repository CAS, or object import from CLI.

At startup, load cutover state before resolving `args.skill_root`. Only when both `legacy_prepare_disabled_epoch` and `finalized_at_epoch` are absent may an explicit root become the lazy `legacy_catalog_loader`. Once begin has durably disabled prepare but finalize has not completed, startup continues so packaged execution, recovery, drain, and finalize remain available, but it passes no legacy loader and never resolves or opens the supplied root. After finalization, any `--skill-root` returns: `Mutable --skill-root is disabled. Import explicitly with 'first-agent skill import <path>', then stage and activate the exact digest.` It must return before resolving or opening the path. There is no restart interval in which a durable disabled epoch reconstructs legacy registrations.

- [ ] **Step 6: Verify Task 9 and commit**

Run:

```bash
.venv/bin/python -m pytest -q tests/cli/test_skill_package_cli.py tests/skill/test_integration.py tests/architecture/test_cutover_absence.py -rx
.venv/bin/ruff check agent/cli/actions.py agent/cli/app.py main.py tests/cli/test_skill_package_cli.py tests/skill/test_integration.py tests/architecture/test_cutover_absence.py
git diff --check
git add agent/cli/actions.py agent/cli/app.py main.py tests/cli/test_skill_package_cli.py tests/skill/test_integration.py tests/architecture/test_cutover_absence.py
git commit -m "feat(skill): route package lifecycle through operator actions"
```

Expected: every CLI mutation reaches one `ExecuteOperatorTool`; there is no direct lifecycle call, combined update command, or post-cutover mutable-root read.

### Task 10: Prove the real lifecycle, restart, update, revoke, rollback, and guard journeys

**Files:**
- Create: `tests/reference/test_021_skill_package_lifecycle.py`
- Create: `tests/reference/test_021_skill_package_crash_matrix.py`
- Create: `scripts/run_021_e2.py`
- Modify: `docs/acceptance/021_SKILL_PACKAGE_LIFECYCLE_E2.md`
- Modify: `docs/implementation/021_EXECUTION_LOG.md`

**Interfaces:**
- `scripts/run_021_e2.py --state-root <fresh-owner-root> --attempt-id <id> --receipt <path>`
- Closed journey IDs `L1` through `L10` and exact claim nodes.

- [ ] **Step 1: Write the reference lifecycle Reds over real Runtime and POSIX stores**

```python
def test_import_stage_activate_restart_update_revoke_restart(tmp_path: Path) -> None:
    harness = LifecycleHarness.real(tmp_path)
    first = harness.make_package("pdf-workspace", "1.0.0", marker="old")
    imported = harness.operator_approve_and_resume("import", source=first)
    assert imported.package_digest not in harness.repository.load().active_digests
    staged = harness.operator_approve_and_resume(
        "stage", package_digest=imported.package_digest, storage_identity_digest=imported.storage_identity_digest,
    )
    assert harness.restart().tool_names == ()
    harness.operator_approve_and_resume("activate", stage_id=staged.stage_id)
    old_runtime = harness.current_runtime
    restarted = harness.restart()
    assert "skill__pdf-workspace__inspect" in restarted.tool_names
    assert restarted.invoke("skill__pdf-workspace__inspect").marker == "old"

    second = harness.make_package("pdf-workspace", "1.1.0", marker="new")
    imported2 = harness.operator_approve_and_resume("import", source=second)
    staged2 = harness.operator_approve_and_resume(
        "stage", package_digest=imported2.package_digest, storage_identity_digest=imported2.storage_identity_digest,
    )
    harness.operator_approve_and_resume("activate", stage_id=staged2.stage_id)
    assert old_runtime.prepare("skill__pdf-workspace__inspect").code == "restart_required"
    updated = harness.restart()
    assert updated.invoke("skill__pdf-workspace__inspect").marker == "new"

    harness.operator_approve_and_resume("revoke", package_digest=imported2.package_digest)
    assert updated.prepare("skill__pdf-workspace__inspect").code == "restart_required"
    assert "skill__pdf-workspace__inspect" not in harness.restart().tool_names


def test_rollback_requalifies_and_requires_separate_activate_approval(tmp_path: Path) -> None:
    harness = active_updated_harness(tmp_path)
    rollback = harness.operator_approve_and_resume("rollback", history_id=harness.old_history_id)
    assert rollback.status == "staged"
    assert harness.active_version == "1.1.0"
    activation = harness.operator("activate", stage_id=rollback.stage_id)
    assert activation.status is RunStatus.AWAITING_APPROVAL
    harness.approve_and_resume(activation)
    assert harness.restart().active_version == "1.0.0"
```

- [ ] **Step 2: Add non-vacuous guard, cutover, identity-drift, and crash journeys**

```python
def test_revoke_waits_for_linearized_execution_and_blocks_next_spawn(tmp_path: Path) -> None:
    harness = active_harness(tmp_path)
    running = harness.pause_after_shared_guard()
    assert harness.try_revoke().code == "lifecycle_busy"
    running.finish_execute_readback_commit()
    harness.operator_approve_and_resume("revoke", package_digest=harness.package_digest)
    assert harness.spawn_count == 1
    assert harness.try_invoke_again().executed is False


def test_restart_and_invoke_fail_closed_for_every_identity_drift(tmp_path: Path) -> None:
    storage_drifts = (
        "store_root_inode", "object_root_inode", "metadata_inode", "object_file_bytes",
    )
    qualification_drifts = (
        "runtime_closure", "sandbox_backend", "packaged_policy", "resource_limiter",
    )
    harnesses = []
    for drift in (*storage_drifts, *qualification_drifts):
        harness = active_harness(tmp_path / drift)
        harness.apply_drift(drift)
        restart = harness.restart_attempt()
        expected_restart_code = (
            "storage_identity_drift"
            if drift in storage_drifts
            else "qualification_drift"
        )
        assert restart.code == expected_restart_code
        assert harness.current_runtime.prepare("skill__pdf-workspace__inspect").code == "restart_required"
        assert harness.spawn_count == 0
        harnesses.append(harness)
    write_journey_record(
        "L4",
        subchecks={
            "storage_drift": True,
            "runtime_drift": True,
            "sandbox_drift": True,
            "policy_drift": True,
            "zero_spawn": True,
        },
        counters=sum_journey_counters(harnesses),
        identities=aggregate_journey_identities(harnesses),
    )


def test_cutover_gate_survives_blocked_drain_and_finalizes_after_recovery(tmp_path: Path) -> None:
    harness = legacy_awaiting_recovery_harness(tmp_path)
    begin = harness.operator_approve_and_resume("begin-cutover")
    assert json.loads(begin.content)["drained"] is False
    assert harness.legacy_prepare().code == "legacy_prepare_disabled"
    replacement = harness.make_package(
        harness.legacy_package_name,
        "1.0.0",
        entrypoint=harness.legacy_entrypoint_name,
        marker="packaged-after-begin",
    )
    imported = harness.operator_approve_and_resume("import", source=replacement)
    staged = harness.operator_approve_and_resume(
        "stage",
        package_digest=imported.package_digest,
        storage_identity_digest=imported.storage_identity_digest,
    )
    harness.operator_approve_and_resume("activate", stage_id=staged.stage_id)

    restarted = harness.crash_and_restart_before_finalize_with_skill_root()
    assert restarted.repository.load().cutover.finalized_at_epoch is None
    assert restarted.legacy_catalog_load_calls == 0
    assert restarted.tool_names.count(harness.legacy_tool_name) == 1
    assert restarted.tool_identity(harness.legacy_tool_name) in (
        restarted.resources.managed_packaged_tool_identities
    )
    assert restarted.invoke(harness.legacy_tool_name).marker == "packaged-after-begin"

    restarted.resolve_legacy_unknown_as_failed()
    scan = restarted.scan_cutover()
    restarted.operator_approve_and_resume(
        "finalize-cutover",
        checkpoint_scan_digest=scan.scan_digest,
        active_tool_names_digest=restarted.active_tool_names_digest,
    )
    assert restarted.restart_with_skill_root().code == "mutable_skill_root_disabled"


def test_applied_cas_then_result_checkpoint_failure_uses_journal_without_replay(tmp_path: Path) -> None:
    harness = active_harness(tmp_path, fail_result_checkpoint_once=True)
    result = harness.operator_approve_and_resume("revoke", package_digest=harness.package_digest)
    assert result.status is RunStatus.AWAITING_RECOVERY
    assert harness.lifecycle_callable_calls == 1
    committed = harness.repository.load()
    assert committed.head_action_id == result.action_id
    resumed = harness.resume_runtime()
    assert resumed.status is RunStatus.COMPLETED
    assert harness.lifecycle_callable_calls == 1
    assert harness.cas_calls == 1
    assert harness.repository.reconcile_calls == 1
    assert harness.recorded_result.metadata["code"] == "lifecycle_commit_reconciled"
    assert harness.restart().tool_names == ()
```

The crash matrix must cover import before/during/after rename, every Task 4 CAS boundary, journal repair followed by a later successful mutation, Runtime result-checkpoint failure after applied CAS, and reconciliation after that later mutation. Assert exact callable counts, ledger revision, journal record count, complete staged/active/history qualification records, tombstone sets, recovery-binding digest, and absence of automatic retry. The result-checkpoint fault must occur only after the ledger/journal read-back returned `AppliedV1`; recovery invokes `KernelToolRuntime.reconcile_unknown` once and never calls the lifecycle callable, planner, qualifier, or CAS again.

- [ ] **Step 3: Run the reference Reds**

Run: `.venv/bin/python -m pytest -q tests/reference/test_021_skill_package_lifecycle.py tests/reference/test_021_skill_package_crash_matrix.py -rx`

Expected: the journey tests fail at the first missing integrated behavior; no skipped/xfail case is accepted.

- [ ] **Step 4: Implement the minimum Green: closed E2 runner**

```python
JOURNEY_NODE_MAP = {
    "L1": (
        "tests/reference/test_021_skill_package_lifecycle.py::test_import_stage_activate_restart_update_revoke_restart",
        ("import_orphan", "stage_not_active", "restart_exposes", "update_restarts", "revoke_absent"),
    ),
    "L2": (
        "tests/reference/test_021_skill_package_lifecycle.py::test_rollback_requalifies_and_requires_separate_activate_approval",
        ("history_exact", "fresh_qualification", "rollback_only_stages", "activate_separate_approval"),
    ),
    "L3": (
        "tests/reference/test_021_skill_package_lifecycle.py::test_revoke_waits_for_linearized_execution_and_blocks_next_spawn",
        ("invoke_sh_linearized", "revoke_ex_blocked", "commit_before_release", "next_spawn_blocked"),
    ),
    "L4": (
        "tests/reference/test_021_skill_package_lifecycle.py::test_restart_and_invoke_fail_closed_for_every_identity_drift",
        ("storage_drift", "runtime_drift", "sandbox_drift", "policy_drift", "zero_spawn"),
    ),
    "L5": (
        "tests/reference/test_021_skill_package_lifecycle.py::test_cutover_gate_survives_blocked_drain_and_finalizes_after_recovery",
        (
            "gate_before_scan",
            "blocked_stays_closed",
            "same_name_activate",
            "pre_finalize_crash_restart",
            "legacy_loader_skipped",
            "packaged_identity_only",
            "fresh_drain",
            "finalized_root_rejected",
        ),
    ),
    "L6": (
        "tests/reference/test_021_skill_package_crash_matrix.py::test_every_cas_boundary_has_one_reconciliation",
        ("applied_or_unknown", "journal_repaired", "later_mutation_safe", "no_retry"),
    ),
    "L7": (
        "tests/reference/test_021_skill_package_lifecycle.py::test_applied_cas_then_result_checkpoint_failure_uses_journal_without_replay",
        ("cas_applied", "result_checkpoint_failed", "opaque_dispatch", "callable_once", "cas_once"),
    ),
    "L8": (
        "tests/reference/test_021_skill_package_crash_matrix.py::test_restart_round_trip_preserves_complete_qualification_records",
        ("staged_record", "active_record", "history_record", "derived_digest", "drift_rejected"),
    ),
    "L9": (
        "tests/reference/test_021_skill_package_lifecycle.py::test_full_active_set_collision_blocks_cas",
        ("full_set_compiled", "reserved_names", "casefold_collision", "zero_cas"),
    ),
    "L10": (
        "tests/reference/test_021_skill_package_lifecycle.py::test_same_process_cutover_prepare_and_invoke_races",
        ("same_process_closed", "prepared_rechecked", "invoke_sh_before_ex", "no_lock_upgrade"),
    ),
}


def closed_subprocess_env(state_root: Path, result_path: Path) -> dict[str, str]:
    runner_home = state_root / f"runner-home-{result_path.stem}"
    runner_tmp = state_root / f"runner-tmp-{result_path.stem}"
    runner_home.mkdir(mode=0o700)
    runner_tmp.mkdir(mode=0o700)
    return {
        "PATH": "/usr/bin:/bin",
        "HOME": str(runner_home),
        "TMPDIR": str(runner_tmp),
        "LANG": "C",
        "LC_ALL": "C",
        "PYTHONHASHSEED": "0",
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "FIRST_AGENT_021_STATE_ROOT": str(state_root),
        "FIRST_AGENT_021_RESULT_PATH": str(result_path),
    }


def run_attempt(repo: Path, state_root: Path, attempt_id: str) -> dict[str, object]:
    journey_results: dict[str, object] = {}
    results_root = state_root / "journey-results"
    results_root.mkdir(mode=0o700)
    for journey_id, (node, expected_subchecks) in JOURNEY_NODE_MAP.items():
        result_path = results_root / f"{journey_id}.json"
        completed = subprocess.run(
            [
                sys.executable, "-m", "pytest", "-q", node, "-rx",
                "--strict-markers", "-o", "xfail_strict=true", "-p", "no:cacheprovider",
            ],
            cwd=repo,
            text=True,
            capture_output=True,
            timeout=900,
            env=closed_subprocess_env(state_root, result_path),
        )
        recorded = load_exact_journey_record(result_path) if result_path.exists() else None
        passed = (
            completed.returncode == 0
            and recorded is not None
            and recorded["journey_id"] == journey_id
            and tuple(sorted(recorded["subchecks"])) == tuple(sorted(expected_subchecks))
            and all(recorded["subchecks"].values())
        )
        journey_results[journey_id] = {
            "node": node,
            "passed": passed,
            "subchecks": (
                recorded["subchecks"]
                if passed
                else {name: False for name in expected_subchecks}
            ),
            "exit_code": completed.returncode,
            "stdout_sha256": hashlib.sha256(completed.stdout.encode()).hexdigest(),
            "stderr_sha256": hashlib.sha256(completed.stderr.encode()).hexdigest(),
        }
    return {
        "attempt_id": attempt_id,
        "passed": all(item["passed"] for item in journey_results.values()),
        "journeys": journey_results,
    }
```

Each journey calls `write_journey_record(journey_id, subchecks, counters, identities)` only after all behavioral assertions pass. That helper requires `set(subchecks) == set(JOURNEY_NODE_MAP[journey_id][1])`, every value exactly `True`, exact non-negative callable/CAS/reconcile counters, and package/storage/qualification/snapshot digests; it creates `FIRST_AGENT_021_RESULT_PATH` once with `O_CREAT|O_EXCL|O_NOFOLLOW`, mode `0600`, canonical JSON, fsync, and no absolute paths. A skipped/xfail/failed test cannot write a passing record, and the runner never copies `os.environ`. The actual runner requires a nonexistent state-root path, creates it owner-only per attempt, uses only synthetic packages, and writes one canonical receipt containing source-tree digest, runner digest, attempt ID, exact nodes, actual subchecks/counters, and exact identities. It rejects an existing root, real credential, remote source, fake CAS result, missing record, skipped test, or any false subcheck.

- [ ] **Step 5: Verify Task 10 passes with three fresh E2 attempts and the full inherited gate**

Run:

```bash
for attempt in 1 2 3; do
  attempt_root="$(mktemp -d)"
  chmod 700 "$attempt_root"
  .venv/bin/python scripts/run_021_e2.py --state-root "$attempt_root/state" --attempt-id "source-$attempt" --receipt "$attempt_root/receipt.json"
done
.venv/bin/python -m pytest -q tests/reference/test_021_skill_package_lifecycle.py tests/reference/test_021_skill_package_crash_matrix.py -rx
.venv/bin/python -m pytest -q tests/sandbox/test_structured_contracts.py tests/sandbox/test_structured_session.py tests/sandbox/test_structured_executor.py tests/sandbox/test_packaged_policy.py tests/sandbox/test_packaged_policy_real.py tests/sandbox/test_hermetic_runtime.py tests/sandbox/test_packaged_runner.py tests/reference/test_020a_operator_structured_sandbox.py -rx
.venv/bin/ruff check .
.venv/bin/python -m pytest -q -rx
git diff --check
```

Expected: three independent attempts and the full repository suite pass with no timeout, truncation, skip, xfail, network, ambient credential, or source-root reuse.

- [ ] **Step 6: Commit the E2 evidence harness**

```bash
git add tests/reference/test_021_skill_package_lifecycle.py tests/reference/test_021_skill_package_crash_matrix.py scripts/run_021_e2.py docs/acceptance/021_SKILL_PACKAGE_LIFECYCLE_E2.md docs/implementation/021_EXECUTION_LOG.md
git commit -m "test(skill): prove package lifecycle restart journeys"
```

Expected: the acceptance document records all `L1..L10` results and exact commands; the execution log records the full-suite count and `next_task=11`.

### Task 11: Seal the wheel/materialized tree and publish the 021 promotion controls

**Files:**
- Create: `scripts/verify_021_materialized_tree.py`
- Create: `tests/reference/test_021_materialized_verifier.py`
- Modify: `pyproject.toml`
- Create: `docs/acceptance/021_SKILL_PACKAGE_LIFECYCLE_SEAL.json`
- Create: `docs/acceptance/021_SKILL_PACKAGE_LIFECYCLE_RECEIPT.json`
- Create: `docs/acceptance/021_SKILL_PACKAGE_LIFECYCLE_WHEEL.json`
- Create: `docs/acceptance/021_SKILL_PACKAGE_LIFECYCLE_INDEPENDENT_REVIEW.md`
- Modify: `docs/architecture/capabilities/SKILL_DESIGN.md`
- Modify: `docs/architecture/CURRENT_CAPABILITY_STATUS.md`
- Modify: `README.md`
- Modify: `docs/implementation/021_EXECUTION_LOG.md`

**Interfaces:**
- `scripts/verify_021_materialized_tree.py check-membership|check-seal|check-wheel|run-materialized|write-seal|write-receipt`
- Exact overlay seal binds the installed 020b Task 6 contract/adapter/builder surface actually consumed by 021; the later 020b Task 8 delivery seal chains forward to this completed 021 seal, never the reverse.

- [ ] **Step 1: Write verifier Reds for missing paths, wrong origins, and forbidden supply-chain behavior**

```python
def test_materialized_verifier_rejects_missing_lifecycle_module(materialized_tree: Path) -> None:
    (materialized_tree / "agent/skill/package_store.py").unlink()
    assert verify.check_membership(materialized_tree) == 1


def test_materialized_verifier_rejects_import_from_checkout(materialized_venv: Path, repo: Path) -> None:
    result = verify.assert_origin(
        materialized_venv, "agent.skill.package_tools", forbidden_root=repo,
    )
    assert result == ["agent.skill.package_tools imported from forbidden checkout"]


@pytest.mark.parametrize("token", ["pip install", "ensurepip", "PYTHONPATH", "http://", "https://"])
def test_product_lifecycle_has_no_dependency_install_or_remote_source_token(token: str) -> None:
    assert token not in product_text(("agent/skill", "agent/skill_hosts"))
```

- [ ] **Step 2: Run verifier Reds**

Run: `.venv/bin/python -m pytest -q tests/reference/test_021_materialized_verifier.py -rx`

Expected: collection fails because `scripts.verify_021_materialized_tree` does not exist.

- [ ] **Step 3: Implement the minimum Green: exact overlay/wheel/materialized verifier**

```python
SCHEMA = "my-first-agent/skill-package-lifecycle-overlay/v1"
SOURCE_DATE_EPOCH = "315532800"
REQUIRED_PATHS = frozenset({
    "agent/skill/package_contracts.py", "agent/skill/package_transport.py",
    "agent/skill/package_store.py", "agent/skill/package_tools.py",
    "agent/skill/package_composition.py", "agent/skill/cutover.py",
    "agent/skill_hosts/__init__.py", "agent/skill_hosts/posix_packages.py",
    "scripts/run_021_e2.py", "scripts/verify_021_materialized_tree.py",
})
BANNED_RUNTIME_IMPORTS = frozenset({"pip", "ensurepip", "venv", "requests"})


def validate_product_imports(repo_root: Path) -> list[str]:
    errors: list[str] = []
    for relative in sorted(REQUIRED_PATHS):
        if not relative.startswith("agent/"):
            continue
        tree = ast.parse((repo_root / relative).read_text(encoding="utf-8"), filename=relative)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [item.name.split(".")[0] for item in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module.split(".")[0]]
            else:
                names = []
            errors.extend(f"{relative} imports forbidden {name}" for name in names if name in BANNED_RUNTIME_IMPORTS)
    return errors
```

Compute `020b_task6_surface_digest` from canonical records for the installed origins/file digests of `agent.skill.executable_contracts`, `agent.skill.executable_codec`, `build_packaged_skill_registrations.__module__`, and `PackagedSkillExecutionAdapter.__module__`, plus their exact public signatures. Chain the 021 seal to that digest and this verifier digest; do not require or reference the later 020b Task 8 delivery seal. Derive membership from tracked overlay entries only; reject untracked/ignored/private sources. Build a wheel with `SOURCE_DATE_EPOCH`, install it into a fresh venv without dependencies or network, assert every `agent.skill`/`agent.skill_hosts` import and `first-agent` entrypoint originates in installed `site-packages`, copy only the synthetic E2 runner/fixtures into a materialized control directory, and execute all Task 10 journeys there. Validate owner/no-follow behavior on the real materialized store, not an in-memory substitute. After this task passes, 020b Tasks 7–8 consume the sealed `SkillLifecycleResources.registrations` and chain their final delivery seal to the 021 seal; they do not reopen composition ownership.

- [ ] **Step 4: Update capability truth and migration documentation**

Record these exact claims:

- Skill package lifecycle is candidate-qualified only after source/full/materialized/E2 gates and detached review pass.
- Supported trust bases are only `bundled_release` and exact local Runtime approval; neither is a publisher signature claim.
- Update is three explicit governed actions; rollback restages historical exact bytes and requires a separate activate approval.
- No automatic dependency install, remote source, ambient credential inheritance, hot reload, object GC, or journal pruning exists.
- Mutable `--skill-root` is a breaking migration: begin gate, explicitly import/stage/activate the replacement, restart packaged-only if interrupted before finalize, drain, finalize, then reject the old root. No compatibility fallback remains.
- 021 does not claim PDF/Office/image artifact semantics; those belong to 022 packages over this lifecycle.

- [ ] **Step 5: Verify Task 11 passes by freezing source and running the promotion chain once**

Run:

```bash
.venv/bin/python -m pytest -q tests/reference/test_021_materialized_verifier.py -rx
.venv/bin/ruff check .
.venv/bin/python -m pytest -q -rx
git diff --check
.venv/bin/python scripts/verify_021_materialized_tree.py write-seal
.venv/bin/python scripts/verify_021_materialized_tree.py check-membership
.venv/bin/python scripts/verify_021_materialized_tree.py check-seal
.venv/bin/python scripts/verify_021_materialized_tree.py check-wheel
.venv/bin/python scripts/verify_021_materialized_tree.py run-materialized
.venv/bin/python scripts/verify_021_materialized_tree.py write-receipt
git diff --check
```

Expected: source full suite, membership, control seal, reproducible wheel, installed-origin checks, materialized full suite, three fresh materialized E2 attempts, and receipt verification all pass. Any source fix invalidates and rebuilds seal/wheel/receipt.

- [ ] **Step 6: Obtain detached review and commit final controls**

The detached review must explicitly cover source/storage identity, archive subset, portable-versus-host identity, no dependency install/credential inheritance, SH/EX linearization, CAS/journal crash matrix, revoke/rollback, full-set collision, cutover drain, and materialized origins. Record reviewer identity, reviewed tree digest, findings disposition, and exact verification receipt digest.

```bash
git add scripts/verify_021_materialized_tree.py tests/reference/test_021_materialized_verifier.py pyproject.toml docs/acceptance/021_SKILL_PACKAGE_LIFECYCLE_SEAL.json docs/acceptance/021_SKILL_PACKAGE_LIFECYCLE_RECEIPT.json docs/acceptance/021_SKILL_PACKAGE_LIFECYCLE_WHEEL.json docs/acceptance/021_SKILL_PACKAGE_LIFECYCLE_INDEPENDENT_REVIEW.md docs/architecture/capabilities/SKILL_DESIGN.md docs/architecture/CURRENT_CAPABILITY_STATUS.md README.md docs/implementation/021_EXECUTION_LOG.md
git commit -m "docs(skill): promote package lifecycle candidate"
```

Expected: the committed controls bind the exact reviewed tree; no later production/source edit exists outside a rebuilt promotion chain.

## Testing and Promotion Matrix

| Gate | Required evidence | Promotion blocker |
| --- | --- | --- |
| U1 contracts/transport | Strict codecs, descriptor-bearing canonical script inventory, domain mutation tests, ZIP/directory parity, every hostile archive/node | Naked script path passed to 020b; any unknown key/type/path accepted; any source effect |
| U1 planner | Qualification separation, complete proposed-set name compilation, generated-only prefix validation, all lifecycle transitions | Reserved lifecycle name rejects itself; disabled legacy name blocks replacement activation; installer/network call; partial-set collision check; rollback bypasses stage/approval |
| U2 POSIX store | Owner/mode/nlink/no-follow, root/object replacement, incoming/read-back/fsync/rename | Same-path replacement accepted; partial object gains authority |
| U2 CAS/guard | Shared/exclusive trace, every replace/journal crash boundary, later-mutation reconciliation | Ambiguous result reported applied/not-executed; action journal loses classification |
| Runtime integration | MODEL denial, OPERATOR Goal/approval/EXECUTING/result/recovery, exact replay identity | CLI/direct callable bypass; operator tool appears in model definitions |
| Restart lifecycle | import→stage→activate→restart→invoke→update→restart→old rejected→revoke→restart absent | Hot registration; stale runtime spawns; revoke deletes bytes |
| Cutover | Durable gate-before-scan, complete checkpoint inventory, identity-aware drain, recovery/cancel path, activation-before-finalize crash restart | Disabled epoch rebuilds/loads legacy registrations; one-shot scan treated as quiescence; identity-less legacy work ignored; fallback root scan |
| E2 | Real Runtime, real POSIX store, synthetic package, three fresh attempts, exact counters | Fake store/runtime, remote/secret fixture, skip/xfail, timeout/truncated output |
| E2M | Sealed tracked overlay, reproducible wheel, installed origins, materialized full suite and E2 | Checkout import, untracked/private member, seal drift, different code than review |

## Migration and Tradeoffs

- The managed store is intentionally incompatible with live mutable `--skill-root`. A permanent compatibility adapter would preserve two trust, identity, and revoke models; this plan instead provides a durable drain and one-way finalization.
- Local directories remain an import transport, not an execution root. This preserves an explicit migration path while ensuring directory and ZIP bytes produce one portable identity.
- Content-addressed objects and an unpruned journal consume disk. This is the cost of stable rollback and action reconciliation; GC and journal compaction require a separate design proving no nonterminal checkpoint references an action/object.
- A shared guard spanning execution/read-back/commit can delay revoke, while nonblocking exclusive acquisition can require an operator retry. This is preferable to falsely revoking a process that has already linearized or deadlocking on a lock upgrade.
- Any ledger mutation forces restart even when definitions would appear unchanged. The conservative epoch rule keeps one immutable ToolRuntime and avoids a hidden dynamic registry.
- Exact dependency closure reduces package portability across application releases and forbids convenient auto-install. It is required to keep qualification reproducible, credential-free, and outside the ambient Python environment.
- `bundled_release` authenticates only the sealed application distribution and exact included digest. `exact_local_approval` authorizes only one package/storage/qualification/preview/head tuple. Neither trust basis claims publisher authenticity or grants future-version trust.
- The extra import copy/read-back and ledger fsyncs cost time and disk I/O. They isolate transport identity from storage identity and make crashes classifiable without granting partial bytes execution authority.

## Final Implementation Review Checklist

- [ ] Every requirement in spec §§3.2, 4–7, 11–15 maps to a task/test above; 022 artifact-format work is absent.
- [ ] `AgentRuntime.run_turn`, `KernelToolRuntime`, `NativeSandboxExecutor`, lifecycle repository, object store, and qualification authority each have one non-overlapping owner.
- [ ] All eight operator registrations are hidden from model definitions and use the existing Goal/approval/checkpoint/recovery flow.
- [ ] Import never mutates the ledger; stage never activates; rollback only stages; activate/revoke/cutover mutate through one EX CAS.
- [ ] Source, object, qualification, active entry, ToolSpec, prepare binding, and invoke revalidation bind the exact required digests.
- [ ] `Conflict` and `UnknownCommitError` remain distinct through Runtime; journal reconciliation survives later mutations.
- [ ] Full active-set collisions include Runtime reserved names and byte/NFC/casefold/length variants; forbidden-prefix validation touches generated packaged names only.
- [ ] Cutover gate remains closed across blockers/crashes, disabled-epoch restart never loads/composes legacy registrations, and finalization requires a fresh complete drain.
- [ ] Both import transport and restart loader derive byte-sorted `ExecutableScriptDescriptorV1(relative_path, size_bytes, sha256)` values from canonical `SCRIPT` inventory; no decoder receives a naked path tuple.
- [ ] `agent.skill.__init__` remains leaf-only; composition and Runtime import exact leaf modules and there is one 021 composition call.
- [ ] No URL/TOFU/dependency install/credential inheritance/hot reload/fallback/GC/journal-prune path exists.
- [ ] Focused, full, E2, wheel, materialized, and detached-review evidence is exact, non-vacuous, and bound to one tree digest.
