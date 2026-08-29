# 017 Native Sandbox Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking. The user-selected executor is Claude
> Code GLM 5.3 at `effort=max`; do not dispatch parallel writers.

**Goal:** 用 macOS Seatbelt 为 First Agent 提供同机、默认断网、workspace
限写的命令执行，并以 exact approval、durable receipt 与 host read-back 保持
现有 Runtime 完成语义。

**Architecture:** `KernelToolRuntime` 继续独占 admission、approval 与 invoke；
`AgentRuntime.run_turn` 继续是唯一 model/tool loop。新的 `SandboxConfiner` 只把
已准备的 exact process command 编译成 `/usr/bin/sandbox-exec` invocation 并返回
可验证 enforcement facts；实际 foreground process、timeout、输出上限和进程组清理
复用 `agent.process`。Docker/snapshot/ChangeBundle/proxy/store 全部退役，不保留真假
两条 sandbox 路径。

**Tech Stack:** Python 3.11、macOS `/usr/bin/sandbox-exec`、Seatbelt profile、
现有 `AgentRuntime` / `KernelToolRuntime` / `agent.process`、pytest、Ruff。

**Spec:** `docs/superpowers/specs/2026-08-27-native-sandbox-design.md`

## Global Constraints

- 冻结 authority：`docs/superpowers/specs/2026-08-27-native-sandbox-design.md`、
  `docs/architecture/017_SANDBOXED_WORKSPACE_EXECUTION_DESIGN.md`、
  `docs/acceptance/017_SANDBOXED_WORKSPACE_EXECUTION_E3.md`。
- v1 production backend 只实现 macOS `/usr/bin/sandbox-exec`；Linux/Windows
  confined modes 返回 closed unavailable reason，不做模拟 fallback。
- policy closed 三值：`read-only`、`workspace-write`（默认）、
  `danger-full-access`（exact approval 后的 unconfined bypass）。
- network closed 二值：`off`（默认）、`full`（必须绑定同一 exact approval）；
  domain allowlist/proxy deferred。
- confined host filesystem 默认可读；`.git`（含 gitdir target）与 `.codex`
  可读但不可写；credential/private/product runtime roots 与敏感文件路径不可读写。
- confined env 只有 `HOME/TMPDIR/PATH/LANG/LC_CTYPE/TZ`；HOME/XDG/cache 指向
  per-invocation temp，不继承 provider credential。
- `danger-full-access` 不依赖 backend qualification，receipt 必须记录
  `backend=none`、`enforcement=unconfined`；所有 confined backend unavailable
  都 fail closed、零执行。
- 不创建第二套 loop、service locator、dynamic registry、compatibility fallback、
  dormant flag；provider/tool/effect owner 不变。
- 不读取 `.env`、secret/credential/private/runtime 或未跟踪 `tui/`；测试敏感
  读取只用临时 sentinel。
- 不 commit/push/tag/branch。通用 skill 的 commit step 被项目规则覆盖：每个任务
  只在 `docs/implementation/017_EXECUTION_LOG.md` 记录 checkpoint。
- T1–T8 每任务只跑 focused tests、touched Ruff、`git diff --check`；T9 才跑
  一次完整 source gate、一次 materialized gate 与真实三连 E3。失败不得以重跑覆盖。

## File Structure and Cutover Map

### 保留并重写

- `agent/sandbox/__init__.py`：只导出 native public contracts。
- `agent/sandbox/contracts.py`：policy、qualification、invocation、enforcement、draft。
- `agent/sandbox/ports.py`：单一 `SandboxConfiner` protocol。
- `agent/sandbox/qualification.py`：只读 Seatbelt qualification。
- `agent/sandbox/tools.py`：唯一 `sandbox_exec` registration 与 preview/binding。
- `agent/composition.py`、`main.py`：自动 qualification、静态 registration、状态渲染。
- `agent/runtime/contracts.py` / `checkpoint.py` / `state.py` / `tools.py`：
  native exact candidate/one-shot lease/receipt durable 边界。
- `agent/runtime/evidence.py`：删除 bundle oracle，保留 receipt + host read-back closure。

### 新建

- `agent/sandbox/policy.py`：canonical paths、carveouts、Seatbelt profile compiler。
- `agent/sandbox/seatbelt.py`：`SeatbeltConfiner` 与 injected runner。
- `agent/sandbox/executor.py`：prepared process → confined invocation → existing runner。
- `agent/process/preparation.py`：local_process 与 sandbox_exec 共用的 exact command
  admission/revalidation/environment builder。

### 删除且不得留 compatibility import

- `agent/sandbox/apply.py`
- `agent/sandbox/bounded_exec.py`
- `agent/sandbox/docker.py`
- `agent/sandbox/egress_proxy.py`
- `agent/sandbox/profile.py`
- `agent/sandbox/snapshot.py`
- `agent/sandbox/store.py`
- Docker/snapshot/bundle/proxy 对应的 `tests/sandbox/test_*.py`。

### 重写验收材料

- `tests/sandbox/`：native contracts/policy/qualification/Seatbelt/executor/tools/composition。
- `tests/reference/test_017_sandboxed_workspace_execution.py`：U1 fake transcript。
- `tests/reference/test_017_real_runner.py`：11 journeys 的真实/注入 runner oracle。
- `tests/reference/test_017_e3_harness.py`、`tests/architecture/test_017_sandbox_boundary.py`、
  `tests/cli/test_017_sandbox_experience.py`。
- `scripts/run_017_e3.py`、`scripts/verify_017_materialized_tree.py`。
- 旧 `017_*RECEIPTS/WHEEL/SEAL/INDEPENDENT_REVIEW` 不删除文件；T9 为新 identity
  原地重铸。`017_EXECUTION_LOG.md` 保留旧 Docker 历史并追加 superseded 分界。

---

### Task 1: Freeze native contracts and policy identity

**Files:**
- Replace: `agent/sandbox/contracts.py`
- Replace: `agent/sandbox/ports.py`
- Create: `agent/sandbox/policy.py`
- Replace: `tests/sandbox/test_contracts.py`
- Create: `tests/sandbox/test_policy.py`

**Interfaces:**
- Produces `SandboxMode`: `READ_ONLY`, `WORKSPACE_WRITE`, `DANGER_FULL_ACCESS`。
- Produces `SandboxNetworkMode`: `OFF`, `FULL`。
- Produces `SandboxPolicyV1`, `SandboxBackendIdentityV1`,
  `SandboxQualificationV1`, `SandboxEnforcementFactsV1`,
  `ConfinedInvocationV1`, `SandboxExecutionDraftV1`。
- Produces `build_sandbox_policy(*, mode, network, workspace, temp_root,
  state_root, home, private_roots) -> SandboxPolicyV1` and
  `compile_seatbelt_profile(policy) -> str`。
- Produces protocol:

```python
class SandboxConfiner(Protocol):
    def qualify(self) -> SandboxQualificationV1:
        raise NotImplementedError

    def confine(
        self,
        command: ProcessCommandV1,
        policy: SandboxPolicyV1,
        environment: Mapping[str, str],
    ) -> ConfinedInvocationV1 | KnownNotExecuted:
        raise NotImplementedError
```

- [x] **Step 1: Write closed contract Reds**

```python
def test_policy_identity_binds_mode_network_workspace_temp_and_carveouts(tmp_path):
    policy = build_sandbox_policy(
        mode=SandboxMode.WORKSPACE_WRITE,
        network=SandboxNetworkMode.OFF,
        workspace=tmp_path / "work",
        temp_root=tmp_path / "tmp",
        state_root=tmp_path / "state",
        home=tmp_path / "home",
        private_roots=("private",),
    )
    assert policy.policy_digest == canonical_json_digest(policy.identity_values())
    assert policy.workspace_root != policy.temp_root

def test_policy_rejects_unknown_mode_noncanonical_workspace_and_overlapping_temp(tmp_path):
    workspace = tmp_path / "work"
    temp_root = tmp_path / "tmp"
    state_root = tmp_path / "state"
    home = tmp_path / "home"
    for path in (workspace, temp_root, state_root, home):
        path.mkdir()
    with pytest.raises(ValueError):
        SandboxMode("container")
    with pytest.raises(ValueError, match="canonical"):
        build_sandbox_policy(
            mode=SandboxMode.WORKSPACE_WRITE,
            network=SandboxNetworkMode.OFF,
            workspace=workspace / ".." / "work",
            temp_root=temp_root,
            state_root=state_root,
            home=home,
            private_roots=("private",),
        )
```

- [x] **Step 2: Write carveout/profile Reds**

Cover exact workspace `.git` directory, `gitdir: ../metadata` file target, `.codex`,
configured state root, workspace private roots, `.env`, `.env.*`, `.pem/.key/.p12/.pfx`
fixtures, quote/newline/NUL path rejection, symlink workspace drift, `read-only` zero
workspace write allow, `workspace-write` exact workspace/temp allow, and network OFF/FULL.

```python
def test_profile_keeps_git_readable_but_denies_git_writes(policy):
    profile = compile_seatbelt_profile(policy)
    assert deny_write_subpath(policy.git_metadata_roots[0]) in profile
    assert deny_read_subpath(policy.git_metadata_roots[0]) not in profile

def test_profile_denies_exact_credential_fixture_read_and_write(policy):
    profile = compile_seatbelt_profile(policy)
    for path in policy.unreadable_roots:
        assert deny_read_subpath(path) in profile
        assert deny_write_subpath(path) in profile
```

- [x] **Step 3: Run Reds**

Run: `.venv/bin/python -m pytest -q tests/sandbox/test_contracts.py tests/sandbox/test_policy.py -rx`

Expected: FAIL because native contracts and policy compiler are absent.

- [x] **Step 4: Implement immutable contracts and canonical policy builder**

`SandboxPolicyV1.__post_init__` must exact-validate closed enums, canonical absolute
paths, non-overlap, non-bool integers, tuple normalization and digest recomputation.
`danger-full-access` carries no Seatbelt read/write roots and compiles no profile.
Resolve `.git` file targets without reading any repository content beyond the bounded
`gitdir:` pointer; refuse malformed/escaping targets.

- [x] **Step 5: Implement the Seatbelt profile compiler**

Compile fixed clauses only. Escape each path through one function that rejects NUL and
line breaks and quotes `\`/`"`; never concatenate model text as policy source.

```python
def compile_seatbelt_profile(policy: SandboxPolicyV1) -> str:
    if policy.mode is SandboxMode.DANGER_FULL_ACCESS:
        raise ValueError("unconfined bypass has no Seatbelt profile")
    clauses = ["(version 1)", "(allow default)", "(deny file-write*)"]
    clauses += allow_backend_literals()
    clauses += allow_write_roots(policy.writable_roots)
    clauses += deny_write_roots(policy.read_only_roots)
    clauses += deny_read_write_roots(policy.unreadable_roots)
    if policy.network is SandboxNetworkMode.OFF:
        clauses.append("(deny network*)")
    return "\n".join(clauses) + "\n"
```

- [x] **Step 6: Verify Task 1 and record checkpoint**

Run the two focused files, Ruff only on changed files, and `git diff --check`. Append
tests/result plus `next_task=2` to `017_EXECUTION_LOG.md`.

### Task 2: Qualify and wrap macOS Seatbelt without executing user commands

**Files:**
- Replace: `agent/sandbox/qualification.py`
- Create: `agent/sandbox/seatbelt.py`
- Replace: `tests/sandbox/test_backend_qualification.py`
- Create: `tests/sandbox/test_seatbelt.py`

**Interfaces:**
- Consumes Task 1 contracts/profile compiler.
- Produces `SeatbeltCommandRunner.run(argv, *, cwd, env, timeout) -> ProbeResult`.
- Produces `SeatbeltConfiner(binary: str = "/usr/bin/sandbox-exec",
  runner: SeatbeltCommandRunner | None = None)` implementing
  `SandboxConfiner`。
- Qualification reason codes are exact:
  `qualified`, `unsupported_platform`, `sandbox_exec_missing`,
  `seatbelt_profile_refused`, `functional_probe_failed`。

- [x] **Step 1: Write qualification Reds**

```python
def test_qualification_identity_uses_canonical_binary_platform_build_and_probe(fake):
    report = SeatbeltConfiner(runner=fake, platform="darwin").qualify()
    assert report.available is True
    assert report.reason_code == "qualified"
    assert report.backend_identity.executable_path == "/usr/bin/sandbox-exec"
    assert report.backend_identity.functional_probe_digest

def test_qualification_never_runs_user_command(fake):
    SeatbeltConfiner(runner=fake).qualify()
    assert fake.argv == ["/usr/bin/sandbox-exec", "-p", MINIMAL_PROBE_PROFILE,
                         "/usr/bin/true"]
```

Test missing binary, wrong platform, probe nonzero, timeout, signal and malformed output.
Assert no install/start/login/fallback operation occurs.

- [x] **Step 2: Write confine Reds**

```python
def test_workspace_write_wraps_exact_command_and_records_facts(confiner, command, policy):
    invocation = confiner.confine(command, policy, CLOSED_ENV)
    assert invocation.wrapped_executable == "/usr/bin/sandbox-exec"
    assert invocation.wrapped_argv[-2:] == (command.executable_identity.resolved_path, *command.argv)
    assert invocation.enforcement.backend == "seatbelt"
    assert invocation.enforcement.profile_digest == sha256(invocation.profile.encode()).hexdigest()

def test_danger_bypass_does_not_probe_backend(confiner_without_backend, command, danger_policy):
    invocation = confiner_without_backend.confine(command, danger_policy, CLOSED_ENV)
    assert invocation.wrapped_executable == command.executable_identity.resolved_path
    assert invocation.enforcement.backend == "none"
    assert invocation.enforcement.enforcement == "unconfined"
```

Also assert confined unavailable returns `KnownNotExecuted` and wrapped argv never uses
`shell=True`, a shell string, profile file on disk or untrusted profile fragments.

- [x] **Step 3: Run Reds**

Run: `.venv/bin/python -m pytest -q tests/sandbox/test_backend_qualification.py tests/sandbox/test_seatbelt.py -rx`

- [x] **Step 4: Implement bounded functional qualification and pure wrapping**

Qualification is read-only and cached per composition instance, not globally. Backend
identity binds canonical binary path, `platform.system()/platform.release()` facts,
functional probe result and probe profile digest. `confine` never spawns; it only returns
the exact wrapped invocation and enforcement facts.

- [x] **Step 5: Verify Task 2 and record checkpoint**

Run focused tests, touched Ruff and diff-check; append `next_task=3`.

### Task 3: Share exact process preparation and execute the wrapped invocation

**Files:**
- Create: `agent/process/preparation.py`
- Modify: `agent/process/tools.py`
- Create: `agent/sandbox/executor.py`
- Create: `tests/process/test_preparation.py`
- Create: `tests/sandbox/test_executor.py`
- Test: existing `tests/process/test_tools.py`, `tests/process/test_runner*.py`。

**Interfaces:**
- Produces `PreparedProcessV1(command, cwd_path, search_paths, child_path)`。
- Produces `prepare_process(arguments, workspace, captured_path, boundary) -> PreparedProcessV1`。
- Produces `revalidate_process(prepared) -> RevalidatedProcessV1 | KnownNotExecuted`。
- Produces `closed_process_environment(temp_root, captured_path) -> dict[str, str]`。
- Produces `NativeSandboxExecutor.execute(prepared, policy) -> SandboxExecutionDraftV1 | KnownNotExecuted`。

- [x] **Step 1: Protect local_process behavior before extraction**

Add characterization tests for exact executable identity, cwd descriptor, argv/profile
limits, PATH sanitization, HOME/TMPDIR isolation, approval-time vs spawn-time drift and
the same trust preview. Run them Green before moving code.

- [x] **Step 2: Extract preparation without changing local_process behavior**

Move only reusable pure/bounded logic from `agent/process/tools.py` to
`agent/process/preparation.py`. `build_local_process_registration` must call the public
seam; do not create a generic plugin/factory.

```python
prepared = prepare_process(
    arguments,
    workspace=workspace_root,
    captured_path=captured_path,
    boundary=boundary,
)
revalidated = revalidate_process(prepared)
```

- [x] **Step 3: Write sandbox executor Reds**

Assert executor revalidates original executable/cwd after approval, creates exact
per-invocation HOME/TMPDIR, passes closed env to `confiner.confine`, invokes the existing
`run_local_process` once with wrapped executable/argv, and always deletes only its own
temp directories. Cover wrapper spawn failure, timeout/group cleanup, backend unavailable,
profile mismatch and enforcement-facts tampering.

- [x] **Step 4: Implement minimal executor**

```python
def execute(self, prepared: PreparedProcessV1, policy: SandboxPolicyV1):
    current = revalidate_process(prepared)
    if isinstance(current, KnownNotExecuted):
        return current
    with self._invocation_environment() as environment:
        invocation = self._confiner.confine(current.command, policy, environment)
        if isinstance(invocation, KnownNotExecuted):
            return invocation
        process = run_local_process(
            resolved_executable=invocation.wrapped_executable,
            argv=invocation.wrapped_argv,
            cwd=current.cwd_path,
            profile=current.resource_profile,
            environment=dict(invocation.environment),
        )
        return SandboxExecutionDraftV1.from_process(
            process=process,
            original_command_fingerprint=current.command.command_fingerprint,
            enforcement=invocation.enforcement,
        )
```

- [x] **Step 5: Verify Task 3 and record checkpoint**

Run new process/sandbox tests plus existing process tool/runner tests, touched Ruff and
diff-check; append `next_task=4`.

### Task 4: Replace Docker authority with exact native one-shot authority

**Files:**
- Modify: `agent/runtime/contracts.py`
- Modify: `agent/runtime/checkpoint.py`
- Modify: `agent/runtime/state.py`
- Modify: `agent/runtime/tools.py`
- Replace: `agent/sandbox/authority.py`
- Replace: `tests/sandbox/test_authority.py`
- Replace: `tests/sandbox/test_tools.py`
- Modify: relevant `tests/kernel/test_contracts.py` and continuity checkpoint tests。

**Interfaces:**
- `SandboxAuthorityCandidateV1` binds goal/revision/workspace,
  original command fingerprint, `policy_digest`, mode, network, trust notice and preview。
- `SandboxAuthorityLeaseV1` is one-shot: `max_uses == 1`; exact candidate/policy/command
  match only; correction/cancel/terminal state revokes it。
- `SandboxReceiptV1` binds lease, original command, policy, enforcement facts and process
  draft. No environment/image/snapshot/bundle fields remain.
- Checkpoint schema becomes v7; v6 Docker sandbox authority is invalidated fail closed and
  cannot authorize a native command.

- [x] **Step 1: Write authority mutation Reds**

```python
def test_danger_full_access_requires_exact_one_shot_approval(runtime, danger_call):
    pending = runtime.prepare(danger_call, context_without_lease)
    assert pending.decision is PolicyDecision.ASK
    approved = resolve_exact_approval(pending)
    assert approved.sandbox_leases[0].max_uses == 1
    assert second_prepare(danger_call, approved).decision is PolicyDecision.ASK

def test_model_cannot_mint_or_change_sandbox_policy(binding):
    forged = {**binding.arguments, "policy_digest": "0" * 64,
              "backend": "seatbelt", "enforcement": "confined"}
    assert prepare(forged).candidate.policy_digest == runtime_policy.policy_digest
```

Cover stale Goal revision, different argv/cwd/mode/network, expired/revoked/consumed lease,
backend unavailable, `danger-full-access` posing as confined, and forged receipt/facts.

- [x] **Step 2: Write checkpoint v7 Reds**

Round-trip native candidate/lease/receipt with exact-key decoding and digest revalidation.
Feed a v6 Docker lease/image digest document and assert it cannot become an active native
lease. Preserve non-sandbox v2–v6 migrations and all process authority tests.

- [x] **Step 3: Implement native durable contracts and checkpoint codec**

Remove `image_digest`, `workspace_snapshot_digest`, `resource_limits_digest`, reusable
environment and bundle fields. Keep `ApprovalRequest.sandbox_authority_candidate` and
`ConversationState.sandbox_leases` as the single durable seam so no parallel approval path
appears.

- [x] **Step 4: Implement ToolRuntime matching and receipt minting**

`KernelToolRuntime.prepare` builds the candidate from trusted `prepare_binding`; `invoke`
requires exact active lease, consumes it in the existing `EXECUTING` transition, accepts
only `SandboxExecutionDraftV1`, verifies all digests, then mints one durable receipt.
`KnownNotExecuted` mints no receipt. Remove receipt-book/capture/apply branches.

- [x] **Step 5: Verify Task 4 and record checkpoint**

Run sandbox authority/tools, contracts/checkpoint, state approval and effect-ordering tests;
touched Ruff and diff-check; append `next_task=5`.

### Task 5: Register one native sandbox tool and close completion evidence

**Files:**
- Replace: `agent/sandbox/tools.py`
- Modify: `agent/runtime/evidence.py`
- Modify: `agent/runtime/loop.py` only if existing repair guidance names retired tools。
- Create: `tests/continuity/test_sandbox_verified_done.py` (replace old content)
- Modify: `tests/kernel/test_evidence_registry.py`
- Modify: `tests/continuity/test_verified_done.py`

**Interfaces:**
- Only product tool: `sandbox_exec`。
- Arguments exact schema:

```python
{
    "executable": str,
    "argv": list[str],
    "cwd": str,
    "profile": "short" | "standard" | "long",
    "mode": "read-only" | "workspace-write" | "danger-full-access",
    "network": "off" | "full",
}
```

- `sandbox_exec` returns bounded `ToolResult` with closed receipt metadata; it never
  exposes raw Seatbelt profile or unrestricted host paths。

- [x] **Step 1: Write tool schema/preview Reds**

Assert `additionalProperties=False`, defaults are `workspace-write/off`, preview renders
exact executable/argv/cwd/profile/mode/network and risk notice without internal digests.
Assert no `sandbox_capture_changes` or `sandbox_apply_bundle` definition exists.

- [x] **Step 2: Write completion Reds**

```python
def test_exit_zero_without_receipt_and_host_readback_is_not_verified_done(state):
    assert derive_completion(state_with_exit_zero_only(state)).satisfied is False

def test_native_receipt_plus_host_digest_can_verify_artifact(state):
    closed = derive_completion(state_with_native_receipt_and_readback(state))
    assert closed.satisfied is True
```

Cover forged policy/enforcement digest, unconfined facts presented for confined mode,
receipt from another goal/revision and output-only completion.

- [x] **Step 3: Implement the single registration**

`prepare_binding` calls shared process preparation and `build_sandbox_policy`; callable
delegates only to `NativeSandboxExecutor`. Safety policy stays static and declares
`ExecutionAuthorityClass.ISOLATED_SANDBOX`; `danger-full-access` is carried by the typed
candidate, not a second tool.

- [x] **Step 4: Remove bundle evidence and repair guidance**

Delete `SandboxBundleReceiptV1`, `sandbox_bundle_v1`, capture/apply repair entries and all
bundle parsing. Completion uses existing `TOOL_RECEIPT` plus `FILESYSTEM_DIGEST` host
read-back; no new oracle kind.

- [x] **Step 5: Verify Task 5 and record checkpoint**

Run sandbox tool/evidence/verified-done focused suites, touched Ruff and diff-check;
append `next_task=6`.

### Task 6: Compose automatic qualification and everyday UX

**Files:**
- Modify: `agent/composition.py`
- Modify: `main.py`
- Modify: `agent/continuity/restart.py` only to delete Docker-specific recovery kinds。
- Replace: `tests/sandbox/test_composition.py`
- Replace: `tests/cli/test_017_sandbox_experience.py`
- Modify: `tests/cli/test_everyday_entrypoint.py`

**Interfaces:**
- `build_sandbox_resources(workspace, state_root, captured_path, *, confiner=None) -> SandboxResources`。
- `SandboxReadiness`: `READY`, `TEMPORARILY_UNAVAILABLE`, `UNSUPPORTED`。
- Startup automatically probes once and renders one bounded line; no profile/setup command。

- [x] **Step 1: Write composition Reds**

Assert macOS qualified registers exactly one `sandbox_exec`; missing/refused backend
registers no confined execution but still builds a danger-bypass-capable registration that
cannot execute without exact approval. Assert injected fake is the only test substitute and
there is no fallback to `local_process`.

- [x] **Step 2: Write CLI Reds**

Expected user-visible shapes:

```text
Sandbox: ready (macOS Seatbelt; workspace-write, network off)
Sandbox: unavailable (sandbox-exec functional probe failed; confined commands will not run)
Sandbox: unsupported on this platform; confined commands will not run
```

Remove `setup-sandbox`, image digest, Docker binary/context prompts and profile persistence.
No traceback, backend digest, raw path or secret filename appears.

- [x] **Step 3: Implement static composition**

Build one `SeatbeltConfiner`, one `NativeSandboxExecutor`, and one registration. Inject the
same object into qualification and execution. `build_composition` still receives ordinary
registrations; `KernelToolRuntime` has no backend factory/service locator.

- [x] **Step 4: Implement startup projection and remove retired recovery states**

Projection is read-only. Existing unknown-outcome recovery remains; Docker environment,
bundle review/base drift/setup UX is deleted rather than mapped to compatibility strings.

- [x] **Step 5: Verify Task 6 and record checkpoint**

Run sandbox composition/CLI/everyday/restart focused suites, touched Ruff and diff-check;
append `next_task=7`.

### Task 7: Hard cutover and architecture absence gates

**Files:**
- Delete the retired `agent/sandbox` modules listed in the File Structure section。
- Delete Docker/snapshot/bundle/proxy/store test files。
- Replace: `tests/architecture/test_017_sandbox_boundary.py`
- Modify: `tests/architecture/test_cutover_absence.py`
- Replace: `tests/reference/test_017_sandboxed_workspace_execution.py`
- Replace: `tests/reference/test_017_e3_harness.py`

**Interfaces:**
- U1 fake confiner records wrapped argv, policy, env, process sends and durable receipts。
- Architecture gate proves one Runtime/ToolRuntime owner and no Docker lifecycle vocabulary。

- [x] **Step 1: Delete retired code and tests in one cutover**

Delete only the enumerated 017 Docker files. Do not remove unrelated architecture-deepening
work (`agent/process/group.py`, `agent/runtime/tool_governance.py`) or 016 artifacts.

- [x] **Step 2: Add absence Reds**

```python
def test_product_has_no_retired_docker_sandbox_path():
    text = product_source_text()
    for retired in (
        "DockerSandboxEnvironment", "SandboxStore", "ChangeBundle",
        "sandbox_capture_changes", "sandbox_apply_bundle", "egress_proxy",
        "image_digest", "workspace_snapshot_digest",
    ):
        assert retired not in text

def test_only_agent_runtime_calls_provider_and_tool_runtime():
    assert production_generate_callers() == {"agent/runtime/loop.py"}
    assert production_invoke_callers() == {"agent/runtime/loop.py"}
```

- [x] **Step 3: Rewrite U1 fake journeys**

Cover all U1 bullets from frozen E3: closed modes, carveouts, pure confine interface,
canonical path/symlink drift, network separation, closed env, backend unavailable, effect
ordering, receipt+readback completion and mutation oracles. Fake must prove wrapped argv
actually contains `/usr/bin/sandbox-exec -p <profile> <exact command>`; a fake that merely
returns success without observing wrapper input must fail the harness.

- [x] **Step 4: Add Docker residue gate**

Run:

```bash
rg -n "DockerSandbox|docker (create|exec|cp)|ChangeBundle|SandboxStore|egress_proxy|sandbox_capture_changes|sandbox_apply_bundle|image_digest|workspace_snapshot_digest" agent tests scripts docs/architecture/017_* docs/acceptance/017_* docs/superpowers/plans/2026-08-27-017-native-sandbox.md
```

Expected: no product/new-contract hit. The superseded 2026-08-26 plan and historical
execution-log section are the only allowed documentary history and are excluded above.

- [x] **Step 5: Verify Task 7 and record checkpoint**

Run architecture + U1/harness + affected cutover tests, touched Ruff and diff-check;
append `next_task=8`.

### Task 8: Rebuild real E3 runner and fail-closed attestation

**Files:**
- Replace: `scripts/run_017_e3.py`
- Replace: `scripts/verify_017_materialized_tree.py`
- Replace: `tests/reference/test_017_real_runner.py`
- Replace: `docs/acceptance/017_SANDBOXED_WORKSPACE_EXECUTION_WHEEL.json` schema fixture。

**Interfaces:**
- Runner stages: `source_gates`, `materialized_gates`, `backend_qualification`,
  `attempt_1`, `attempt_2`, `attempt_3`, `attestation`。
- Receipt binds delivery root, verifier digest, detached runner digest, wheel digest,
  backend identity and exactly
  11 boolean journey verdicts per attempt。
- Blocked marker: `NEEDS_017_SEATBELT_BACKEND(stage=U2)` only after all local gates Green
  and qualification is the sole confined-journey blocker。

- [x] **Step 1: Write receipt/verifier Reds**

Reject old Docker fields, missing/extra keys, wrong root/verifier/wheel/backend/profile
digest, attempts not exactly three, non-bool verdicts, one false journey, reused workspace/
temp/sentinel, and failed attempt overwritten by retry. Attestation must compare receipt
identity to the current exact materialized root.

- [x] **Step 2: Write non-vacuous journey Reds**

For each denial journey mutate the control prerequisite to false and assert journey FAILS.
Mutate confined result to success/effect present and assert FAILS. Specific controls:

- outside-write parent is demonstrably writable before confinement;
- credential sentinel is demonstrably readable before its exact carveout;
- loopback listener is demonstrably reachable before network OFF;
- child outside target is demonstrably writable before confined child;
- git metadata is demonstrably readable before confined read/write assertions。

- [x] **Step 3: Implement the 11 real journeys**

Use only temp workspaces/fixtures. Never read ambient credentials or arbitrary user paths.
Journey 10 danger bypass writes one test-owned external temp file only. Record bounded enums,
counts and digests; no raw transcript, profile, credential name or absolute fixture path in
receipt/failure detail.

- [x] **Step 4: Implement immutable materialized execution**

Verify source membership/control seal, materialize once, build wheel once per attempt from
that immutable tree, install into clean venv without host packages, run offline gates, then
run the three real attempts. Any tree drift aborts before receipt write.

- [x] **Step 5: Verify Task 8 and record checkpoint**

Run only real-runner/harness/verifier focused tests, touched Ruff and diff-check. Do not run
the real three-attempt pipeline yet. Append `next_task=9`.

### Task 9: One final full gate, real three-attempt E3 and independent delivery review

**Files:**
- Update: `docs/implementation/017_EXECUTION_LOG.md`
- Rewrite from actual evidence:
  `docs/acceptance/017_SANDBOXED_WORKSPACE_EXECUTION_E3_RECEIPTS.json`
- Rewrite from actual evidence: `docs/implementation/017_DELIVERY_SEAL.json`
- Rewrite after fresh review:
  `docs/acceptance/017_SANDBOXED_WORKSPACE_EXECUTION_INDEPENDENT_REVIEW.md`
- Update capability status/README only if all promotion gates pass。

- [ ] **Step 1: Freeze ordinary source and run final source gates once**

Run, capturing full untruncated output and exit codes:

```bash
git diff --check
.venv/bin/ruff check .
.venv/bin/python -m pytest -q -rx
```

Any failure returns to the owning task, runs the failing focused test first, fixes minimally,
then repeats this final sequence only after source is frozen again.

- [ ] **Step 2: Build exact delivery seal and verify membership/control seal**

Explicitly exclude `.env`, secret/private/runtime, `tui/`, Coding Agent artifacts and
superseded receipts. Do not use broad `git add` or infer delivery from working-tree status.

- [ ] **Step 3: Run materialized gate and real E3 exactly once for the frozen root**

Run the verifier materialized/content gate, then `scripts/run_017_e3.py` for three fresh
attempts. Do not retry an individual failed attempt into Green. If and only if backend
qualification is the sole remaining gap, write accurate
`NEEDS_017_SEATBELT_BACKEND(stage=U2)` and stop promotion without claiming completion.

- [ ] **Step 4: Run fresh independent review**

Reviewer checks owner boundaries, native policy fidelity, non-vacuous controls, exact
bypass authority, receipt identity and false completion. Any fix invalidates seal/receipt
and returns to Step 1.

- [ ] **Step 5: Close delivery only on full evidence**

Run membership, control-seal and attestation against the final exact identity. Append actual
commands/counts/digests/verdict to execution log, write independent review, and only then
mark 017 accepted/delivered in user-facing capability docs. No commit/push unless the user
later asks explicitly.

## Self-Review Record

- Spec coverage: Tasks 1–8 map every frozen §2–§13 requirement and all U0/U1/U2/U3
  acceptance bullets; Task 9 owns promotion evidence only。
- Deletion test: removing `SandboxConfiner` would put Seatbelt/profile knowledge back into
  ToolRuntime/process runner; removing shared process preparation would duplicate executable/
  cwd identity admission. No other new abstraction is introduced。
- Type consistency: `ProcessCommandV1` is the only exact command identity consumed by both
  local and sandbox execution; `SandboxPolicyV1.policy_digest` flows candidate → lease →
  enforcement → receipt; `SandboxExecutionDraftV1` is the only sandbox callable result。
- Placeholder scan: every implementation step names concrete types, files, behavior and
  commands; deferred Linux, Windows and domain allowlist are explicit frozen non-goals。
- Verification economy: no per-task full suite; focused Red/Green at Tasks 1–8, one final
  complete source/materialized/E3 sequence at Task 9。
