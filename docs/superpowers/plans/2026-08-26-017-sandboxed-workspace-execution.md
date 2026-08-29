# 017 Sandboxed Workspace Execution Implementation Plan

> **SUPERSEDED 2026-08-27（用户裁决）**：本计划的 Docker/container 方向与
> 实现（Task 1–10 全部，含 Docker artifacts、snapshot/ChangeBundle、
> egress proxy、E3 receipts 与 seal）已被 corrected native sandbox 设计
> 整体取代——见 `docs/superpowers/specs/2026-08-27-native-sandbox-design.md`
> 与修订后的
> `docs/architecture/017_SANDBOXED_WORKSPACE_EXECUTION_DESIGN.md` /
> `docs/acceptance/017_SANDBOXED_WORKSPACE_EXECUTION_E3.md`。本文件仅作
> 历史记录保留；不作为实现或 promotion 依据。新方向的 implementation
> plan 另行制定。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. The user-selected executor is Claude Code GLM 5.3 at `effort=max`; do not dispatch parallel writers.

**Goal:** 在 Docker 隔离环境中执行有界命令/代码任务，默认断网、无 host bind mount，并以可审查 `ChangeBundle` 交付结果。

**Architecture:** `SandboxEnvironment` 是一个小而深的 external-effect port；Docker adapter 只管理 container/network/proxy/snapshot lifecycle，不认识 Goal 或 checkpoint。所有 sandbox 工具仍由 `KernelToolRuntime` 完成 policy、approval、`EXECUTING` checkpoint 和 invoke；host merge 是独立 governed effect。

**Tech Stack:** Python 3.11、Docker Engine CLI 29+、pytest、现有 `AgentRuntime`/`KernelToolRuntime`/`LocalCheckpointStore`。

**Spec:** `docs/superpowers/specs/2026-08-26-governed-execution-program-design.md`

> **Design correction 2026-08-26（主审裁决，仅修正 Task 4 文字）**：本计划 Task 4 原文
> 的 argv 序列（每条命令 `create→cp→start→wait/logs→copy-out→rm`）与已批准 port
> contract（`provision(spec)` 不携带 command、`execute(handle, command)` 可多次）矛盾，
> 作废。Corrected lifecycle：provision 一次 hardened long-lived container（idle-command
> `sleep infinity`）+ copy-in + start；每条 exact command 一次 bounded `docker exec`
> （`max_command_count` durable 预算）；capture copy-out（fresh empty attempt 目录）；
> close 仅 exact-labelled 精确清理。`docker wait/logs` 不在 lifecycle 内。其余任务不变。

## Global Constraints

- macOS 15/POSIX-first；production backend 只支持 Docker Engine adapter，不提供 same-UID fallback。
- Docker daemon、fixed image digest 和真实 E3 network config 缺失时 fail closed；实现不得自动安装、启动或登录外部服务。
- 默认 `NetworkMode.OFF`；`PACKAGE_REGISTRY` 和 `EXACT_ALLOWLIST` 只能经内部-only Docker network + project-owned CONNECT proxy。
- 不 bind mount host workspace/home/socket；使用 no-follow copy-in snapshot 和 copy-out staging。
- 不读取 `.env`、credential、private/runtime 或未跟踪 `tui/`；这些路径不进入 snapshot、bundle、receipt 或 seal。
- `AgentRuntime.run_turn`、`ContextManager`、`KernelToolRuntime` 的唯一 owner 不变。
- 每个原子任务只跑 focused tests、touched Ruff、`git diff --check`；Task 9 才跑一次 source full gate，Task 10 跑 materialized/full/E3。
- 项目规则覆盖通用 skill 的 commit 模板：不 commit/push；每任务在 017 execution log 记录 diff、focused gate 和下一恢复点。

## File Map

- Create `agent/sandbox/contracts.py`: immutable environment、command、network、receipt、bundle contracts。
- Create `agent/sandbox/ports.py`: `SandboxEnvironment` protocol；不包含 factory/registry。
- Create `agent/sandbox/snapshot.py`: safe workspace snapshot 与 ChangeBundle diff/read-back。
- Create `agent/sandbox/store.py`: owner-only environment lifecycle/intent ledger，用于 crash 定位与恢复。
- Create `agent/sandbox/egress_proxy.py`: closed CONNECT allowlist、DNS/public-IP validation、bounded audit。
- Create `agent/sandbox/docker.py`: Docker CLI lifecycle adapter 和 cleanup confirmation。
- Create `agent/sandbox/tools.py`: `sandbox_exec`、`sandbox_apply_bundle` registrations。
- Modify `agent/runtime/contracts.py`: sandbox authority candidate/lease/receipt 的 durable typed members。
- Modify `agent/runtime/checkpoint.py`: sandbox durable members strict codec。
- Modify `agent/runtime/tools.py`: sandbox candidate/lease matching与 receipt minting；不调用 Docker API。
- Modify `agent/runtime/state.py`: approval、revision/correction/cancel 时的 lease lifecycle。
- Modify `agent/runtime/evidence.py`: sandbox receipt + host read-back closure。
- Modify `agent/composition.py`, `main.py`, `pyproject.toml`: static registration、config 与 CLI projection。
- Create `tests/sandbox/`: contracts、snapshot、proxy、Docker adapter、tool、recovery tests。
- Create `tests/reference/test_017_sandboxed_workspace_execution.py` and harness tests。
- Create `docs/architecture/017_SANDBOXED_WORKSPACE_EXECUTION_DESIGN.md`, `docs/acceptance/017_SANDBOXED_WORKSPACE_EXECUTION_E3.md`, `docs/implementation/017_EXECUTION_LOG.md`。
- Create `scripts/run_017_e3.py`, `scripts/verify_017_materialized_tree.py`。

---

### Task 1: Freeze 017 contracts and backend qualification

**Files:**
- Create: `docs/architecture/017_SANDBOXED_WORKSPACE_EXECUTION_DESIGN.md`
- Create: `docs/acceptance/017_SANDBOXED_WORKSPACE_EXECUTION_E3.md`
- Create: `docs/implementation/017_EXECUTION_LOG.md`
- Create: `tests/sandbox/test_backend_qualification.py`
- Create: `agent/sandbox/qualification.py`

**Interfaces:**
- Produces: `DockerQualification(command_runner, binary="docker", context=None).probe() -> QualificationReport`.
- `QualificationReport` fields: `available`, `client_version`, `server_version`, `linux_containers`, `security_options`, `reason_code`.

- [ ] **Step 1: Write the frozen architecture and E3 matrices**

Copy the approved owner/state/authority/unknown-outcome rules from the spec. Freeze exact Docker qualification codes:
`docker_cli_missing`, `docker_daemon_unavailable`, `docker_server_too_old`, `non_linux_backend`, `security_probe_failed`, `qualified`.
E3 must include zero host mutation before bundle apply, network escape, ambient secret absence, crash cleanup, base drift, receipt forgery and three consecutive real attempts.

- [ ] **Step 2: Write qualification Reds**

```python
def test_unavailable_daemon_never_falls_back_to_local_process(fake_cli):
    report = DockerQualification(fake_cli).probe()
    assert report.available is False
    assert report.reason_code == "docker_daemon_unavailable"
    assert fake_cli.host_process_calls == 0

def test_only_linux_engine_29_or_newer_is_qualified(fake_cli):
    fake_cli.info = {"ServerVersion": "29.3.1", "OSType": "linux"}
    assert DockerQualification(fake_cli).probe().reason_code == "qualified"
```

- [ ] **Step 3: Run Reds**

Run: `.venv/bin/python -m pytest -q tests/sandbox/test_backend_qualification.py -rx`
Expected: FAIL because `agent.sandbox.qualification` does not exist.

- [ ] **Step 4: Implement the bounded probe**

Use argument-vector subprocess calls only: `docker version --format ...` and `docker info --format ...`; cap output at 64 KiB and deadline at 5 seconds. Parse strict JSON into the immutable report. Never call `colima start`, `docker login`, `docker pull` or host `local_process`.

- [ ] **Step 5: Verify and record checkpoint**

Run qualification tests, touched Ruff, and `git diff --check`. Append exact results and `next_task=2` to `017_EXECUTION_LOG.md`.

### Task 2: Define the sandbox domain contracts and port

**Files:**
- Create: `agent/sandbox/__init__.py`
- Create: `agent/sandbox/contracts.py`
- Create: `agent/sandbox/ports.py`
- Test: `tests/sandbox/test_contracts.py`

**Interfaces:**
- Produces `NetworkMode(StrEnum)`: `OFF`, `PACKAGE_REGISTRY`, `EXACT_ALLOWLIST`.
- Produces `SandboxSpecV1`, `SandboxCommandV1`, `SandboxHandleV1`, `SandboxExecutionDraftV1`, `SandboxCleanupReceiptV1`, `ChangeBundleV1`.
- Produces `SandboxEnvironment.provision/execute/capture_changes/close` protocol.

- [ ] **Step 1: Write strict contract Reds**

```python
def test_command_identity_binds_environment_argv_cwd_network_and_limits():
    command = SandboxCommandV1(executable="/bin/sh", argv=("-lc", "pytest -q"), cwd=".", spec=spec())
    changed = replace(command, argv=("-lc", "pytest -x"))
    assert command.identity_digest != changed.identity_digest

def test_allowlist_rejects_ip_localhost_wildcard_and_empty_domain():
    for value in ("127.0.0.1", "localhost", "*.example.com", ""):
        with pytest.raises(ValueError):
            NetworkPolicyV1.exact_allowlist((value,))
```

- [ ] **Step 2: Run Reds**

Run: `.venv/bin/python -m pytest -q tests/sandbox/test_contracts.py -rx`
Expected: import failure for the new contracts.

- [ ] **Step 3: Implement immutable contracts**

All identity digests use existing `canonical_json_digest`. `SandboxSpecV1` requires image digest, workspace snapshot digest, resource profile, network policy, TTL and output cap. The port is:

```python
class SandboxEnvironment(Protocol):
    def provision(self, spec: SandboxSpecV1) -> SandboxHandleV1: ...
    def execute(self, handle: SandboxHandleV1, command: SandboxCommandV1) -> SandboxExecutionDraftV1 | KnownNotExecuted: ...
    def capture_changes(self, handle: SandboxHandleV1) -> ChangeBundleV1: ...
    def close(self, handle: SandboxHandleV1) -> SandboxCleanupReceiptV1: ...
```

- [ ] **Step 4: Add mutation/round-trip tests**

Reject unknown enum members, bool-as-int limits, duplicate domains, non-HTTPS ports, missing digests, partial receipts, unknown keys and mismatched environment identity. Verify canonical JSON is stable across constructor order.

- [ ] **Step 5: Verify and record checkpoint**

Run contracts tests, touched Ruff and diff-check; append `next_task=3`.

### Task 3: Build no-follow workspace snapshots and ChangeBundles

**Files:**
- Create: `agent/sandbox/snapshot.py`
- Test: `tests/sandbox/test_snapshot.py`
- Test: `tests/sandbox/test_change_bundle.py`

**Interfaces:**
- Consumes: `SandboxSpecV1`, `ChangeBundleV1`.
- Produces: `create_workspace_snapshot(workspace, staging_root, policy) -> WorkspaceSnapshotV1`.
- Produces: `build_change_bundle(base, result_root, bundle_root, limits) -> ChangeBundleV1`.
- Produces: `verify_bundle_against_workspace(bundle, workspace) -> BundleVerification`.

- [ ] **Step 1: Write path-safety Reds**

Cover symlink escape, hardlink/special file, directory replacement, `.env`, `.git`, configured state roots, secret/private/runtime names, top-level `tui/`, file-count/byte limits and concurrent source mutation. Assert no denied filename/content enters staging or manifest.

- [ ] **Step 2: Run Reds**

Run: `.venv/bin/python -m pytest -q tests/sandbox/test_snapshot.py tests/sandbox/test_change_bundle.py -rx`
Expected: import failure.

- [ ] **Step 3: Implement descriptor-relative copy-in**

Reuse `WorkspaceBoundary` semantics and `os.open(..., O_NOFOLLOW)`; copy regular files to a product-owned `mkdtemp` staging root, hash while copying, then re-stat source descriptor. Mutation or identity drift returns a closed failure and deletes only the exact staging directory.

- [ ] **Step 4: Implement bounded diff and base verification**

`ChangeBundleV1` records added/modified/deleted paths and blobs under bundle-owned storage. It never contains absolute host paths. Base verification returns `clean`, `base_drift`, or `bundle_corrupt`; it does not apply changes.

- [ ] **Step 5: Verify and record checkpoint**

Run both test files, touched Ruff and diff-check; append `next_task=4`.

### Task 4: Implement Docker lifecycle with network OFF

**Files:**
- Create: `agent/sandbox/docker.py`
- Create: `agent/sandbox/store.py`
- Test: `tests/sandbox/test_docker_adapter.py`
- Test: `tests/sandbox/test_docker_cleanup.py`
- Test: `tests/sandbox/test_sandbox_store.py`

**Interfaces:**
- Consumes: `SandboxEnvironment` contracts and workspace snapshots.
- Produces: `DockerSandboxEnvironment(SandboxEnvironment)` using an injected `DockerCommandRunner`.
- Produces: `SandboxStore.begin/load/compare_and_swap/find_by_request_identity` with closed phases `PREPARING/PROVISIONED/RUNNING/RESULT_OBSERVED/CLEANED/CLEANUP_UNKNOWN`.

- [ ] **Step 1: Write fake-CLI lifecycle Reds（corrected 2026-08-26：multi-command lease）**

Assert provision performs exactly one hardened `docker create`（`--network none --cap-drop ALL --security-opt no-new-privileges --pids-limit/--memory/--memory-swap/--cpus`、request label 用稳定摘要、idle-command `sleep infinity`、无 `--volume`/`-v`）， then one `docker cp` copy-in and one `docker start`; each exact command is a separate bounded `docker exec`（`wait`/`logs` 不在 lifecycle，fake 必须拒绝）。Assert secrets and host paths are absent from argv/output metadata.

- [ ] **Step 2: Write cleanup/unknown Reds**

Cover create-failure read-back classification, cp/start timeout, exec timeout/cap-truncation（kill + verified stopped 或 UNKNOWN）, daemon loss, command budget exhaustion and cleanup confirmation（exact 双 label read-back 绑定后才 rm）. Once start may have occurred, unclassified errors raise existing unknown-outcome; cleanup uncertainty forbids handle reuse.

- [ ] **Step 3: Run Reds**

Run: `.venv/bin/python -m pytest -q tests/sandbox/test_docker_adapter.py tests/sandbox/test_docker_cleanup.py tests/sandbox/test_sandbox_store.py -rx`
Expected: failures because adapter is absent.

- [ ] **Step 4: Implement the adapter**

Use a closed argv builder and injected runner; never `shell=True`. Before the first Docker effect, create an owner-only store record keyed by the Runtime request identity; persist each lifecycle transition with CAS. Name resources with a product prefix plus handle digest, label them with environment/request identity, cap each Docker call, and verify container absence after removal. Restart recovery locates only exact labelled resources from this ledger. Output only bounded stdout/stderr plus raw digests and byte counts.

- [ ] **Step 5: Verify and record checkpoint**

Run Docker fake tests, touched Ruff and diff-check; append `next_task=5`.

### Task 5: Implement the closed egress proxy policies

**Files:**
- Create: `agent/sandbox/egress_proxy.py`
- Modify: `agent/sandbox/docker.py`
- Test: `tests/sandbox/test_egress_proxy.py`
- Test: `tests/sandbox/test_docker_network_policy.py`

**Interfaces:**
- Produces: `admit_connect_target(host: str, port: int, policy: NetworkPolicyV1, resolver) -> tuple[IPAddress, ...]`.
- Produces: `ConnectProxy.serve(policy, audit_sink)` with payload-free `NetworkAttemptV1` records.

- [ ] **Step 1: Write SSRF and bypass Reds**

Reject raw IP, localhost, LAN/private/link-local/multicast/metadata, unlisted domain/port, DNS answer containing any non-public IP, oversized headers and non-CONNECT methods. Re-resolve every CONNECT. Test that direct egress from the sandbox network fails even when proxy variables are ignored.

- [ ] **Step 2: Write preset Reds**

Freeze v1 presets: `python` permits `pypi.org:443` and `files.pythonhosted.org:443`; `node` permits `registry.npmjs.org:443`. No wildcard suffix matching.

- [ ] **Step 3: Run Reds**

Run: `.venv/bin/python -m pytest -q tests/sandbox/test_egress_proxy.py tests/sandbox/test_docker_network_policy.py -rx`
Expected: failures for missing proxy/policy implementation.

- [ ] **Step 4: Implement internal network + proxy sidecar**

Create a per-environment `--internal` Docker network. Attach target only to it; attach proxy to internal plus an external bridge. Inject only `HTTPS_PROXY`/`HTTP_PROXY` pointing at the proxy. Copy the project-owned proxy module into the helper container; never mount Docker socket or host source. Stop proxy and delete both networks during close.

- [ ] **Step 5: Verify and record checkpoint**

Run proxy/network tests, touched Ruff and diff-check; append `next_task=6`.

### Task 6: Add sandbox authority, durable lease and ToolRuntime governance

**Files:**
- Modify: `agent/runtime/contracts.py`
- Modify: `agent/runtime/checkpoint.py`
- Modify: `agent/runtime/tools.py`
- Modify: `agent/runtime/state.py`
- Create: `agent/sandbox/tools.py`
- Test: `tests/sandbox/test_authority.py`
- Test: `tests/sandbox/test_tools.py`
- Test: `tests/continuity/test_sandbox_checkpoint.py`

**Interfaces:**
- Produces durable `SandboxAuthorityCandidateV1`, `SandboxAuthorityLeaseV1`, `SandboxReceiptV1`.
- Produces registrations `sandbox_exec` and `sandbox_capture_changes`.
- Adds `ExecutionAuthorityClass.ISOLATED_SANDBOX` and `EgressClass.GOVERNED_NETWORK`.

- [ ] **Step 1: Write authority Reds**

Assert approval binds Goal/revision/workspace, image, snapshot, command, network, resources and uses/expiry. Revision/correction/cancel/environment drift clears lease. Model fields cannot mint/expand lease. `GOVERNED_NETWORK` requires HIGH + EXTERNAL + ALWAYS approval unless an exact active sandbox lease matches.

- [ ] **Step 2: Write checkpoint mutation Reds**

Round-trip exact typed members; reject partial/unknown/forged values. Restart with matching lease can continue; changed image/snapshot/network cannot. Credential and raw workspace path must be absent from serialized JSON.

- [ ] **Step 3: Run Reds**

Run the three focused files. Expected: missing enum/types/registration failures.

- [ ] **Step 4: Implement minimal governance**

Follow existing `local_process` candidate→approval→lease pattern but keep sandbox-specific matching in `agent/sandbox/tools.py`. `KernelToolRuntime` remains the final gate and only invokes the injected port after the Runtime has persisted `EXECUTING`. A matched lease skips repeated low-risk internal command approval; policy expansion always returns `ApprovalRequired`.

- [ ] **Step 5: Verify and record checkpoint**

Run focused tests, touched Ruff and diff-check; append `next_task=7`.

### Task 7: Govern ChangeBundle host application and evidence closure

**Files:**
- Modify: `agent/sandbox/tools.py`
- Modify: `agent/runtime/evidence.py`
- Modify: `agent/runtime/state.py`
- Test: `tests/sandbox/test_bundle_apply.py`
- Test: `tests/continuity/test_sandbox_verified_done.py`

**Interfaces:**
- Produces `sandbox_apply_bundle` WRITE registration with exact path/digest preview.
- Produces `SandboxBundleReceiptV1` and evidence predicate `sandbox_bundle_v1`.

- [ ] **Step 1: Write host-zero-effect and drift Reds**

Before approval, workspace tree/digests are unchanged. Reject base drift, denied paths, symlink swap, corrupt blob, oversized bundle and unapproved deletion. Crash after any replacement enters unknown recovery; read-back determines exact applied subset without blind replay.

- [ ] **Step 2: Write completion Reds**

Sandbox exit 0 alone cannot satisfy host artifact Goal. `VERIFIED_DONE` requires applied bundle receipt plus filesystem read-back digest, or an explicitly sandbox-artifact-only criterion bound to the artifact receipt.

- [ ] **Step 3: Run Reds**

Run both files; expect missing apply/evidence behavior.

- [ ] **Step 4: Implement journaled apply**

Create an owner-only apply journal before first host write; use no-follow staging and atomic per-file replace. Persist bounded per-path outcomes through the existing ToolResult checkpoint. Recovery reads journal + host digests and asks for classification only when state remains ambiguous.

- [ ] **Step 5: Verify and record checkpoint**

Run focused tests, touched Ruff and diff-check; append `next_task=8`.

### Task 8: Static composition and everyday UX

**Files:**
- Modify: `agent/composition.py`
- Modify: `main.py`
- Modify: `pyproject.toml`
- Test: `tests/sandbox/test_composition.py`
- Test: `tests/cli/test_017_sandbox_experience.py`
- Test: `tests/architecture/test_017_sandbox_boundary.py`

**Interfaces:**
- Consumes an explicitly constructed `SandboxEnvironment`; no dynamic registry.
- Adds non-secret profile fields for Docker binary/context/image digest and state root.

- [ ] **Step 1: Write composition/absence Reds**

Assert one `KernelToolRuntime`, one `AgentRuntime`, Docker adapter absent when not configured/qualified, no local-process fallback, reverse-order close, and no product import of Coding Agent artifacts. CLI explains sandbox unavailable with one action, not traceback.

- [ ] **Step 2: Write approval rendering Reds**

Render image/snapshot/command/network/resources/change paths without internal IDs or absolute private roots. Denial returns zero container/network/host effects. Resume projection distinguishes execution unknown, cleanup unknown, bundle review and base drift.

- [ ] **Step 3: Run Reds**

Run the three focused files.

- [ ] **Step 4: Implement static wiring and optional dependency metadata**

Build Docker adapter once at composition root, append its close method to existing close stack, and pass its registrations into `build_composition`. Configuration stores no credential. Base install continues to work when Docker is absent.

- [ ] **Step 5: Verify and record checkpoint**

Run focused tests, touched Ruff and diff-check; append `next_task=9`.

### Task 9: Deterministic reference suite and one source full gate

**Files:**
- Create: `tests/reference/test_017_sandboxed_workspace_execution.py`
- Create: `tests/reference/test_017_e3_harness.py`
- Modify: `docs/implementation/017_EXECUTION_LOG.md`

**Interfaces:**
- Produces U1 claims and a fake Docker transcript with independent send/effect/tree counters.

- [ ] **Step 1: Implement frozen U1 journeys**

Cover all §4.8 journeys with state/tree/container/network counters. Add mutation oracles for forged receipt, old image/snapshot, hidden host bind, direct egress, cleanup uncertainty, false completion and duplicate effect.

- [ ] **Step 2: Run focused 017 suite**

Run: `.venv/bin/python -m pytest -q tests/sandbox tests/reference/test_017_sandboxed_workspace_execution.py tests/reference/test_017_e3_harness.py -rx`
Expected: all PASS with untruncated output.

- [ ] **Step 3: Run architecture gates**

Run `git diff --check`, `.venv/bin/ruff check .`, and static owner tests proving production `provider.generate`/`ToolRuntime.invoke` remain unique.

- [ ] **Step 4: Run one complete source gate**

Run: `.venv/bin/python -m pytest -q -rx`
Expected: complete exit 0; timeout/truncation is not PASS.

- [ ] **Step 5: Freeze source evidence**

Record exact counts/duration/root, freeze ordinary source, and do not rerun full suite after detached log-only edits.

### Task 10: Materialized Docker E3, seal and fresh review

**Files:**
- Create: `scripts/run_017_e3.py`
- Create: `scripts/verify_017_materialized_tree.py`
- Create: `docs/acceptance/017_SANDBOXED_WORKSPACE_EXECUTION_E3_RECEIPTS.json`
- Create: `docs/implementation/017_DELIVERY_SEAL.json`
- Create: `docs/acceptance/017_SANDBOXED_WORKSPACE_EXECUTION_INDEPENDENT_REVIEW.md`
- Modify: `README.md`
- Modify: `STRATEGY.md`
- Modify: `docs/architecture/CURRENT_CAPABILITY_STATUS.md`

**Interfaces:**
- Produces receipt bound to source root, verifier digest, wheel digest, Docker server/context, image digest and per-attempt environment identities.

- [ ] **Step 1: Build the sealed materialized tree once**

Verifier rejects `.env`, credential/private/runtime, `tui/`, Coding Agent artifacts and undeclared files. Build wheel from the immutable materialized tree, install into a clean venv without host site packages, and run the full offline gate there.

- [ ] **Step 2: Run three real attempts**

Use a fixed image digest and qualified Docker context. Each attempt creates fresh containers/networks and completes the frozen real journeys. Record only bounded booleans/counts/digests; no command output, file content, credential or private path.

- [ ] **Step 3: Verify attestation**

`verify_017_materialized_tree.py --check-membership`, `--control-seal`, and `--attestation` must all exit 0 and prove all three attempts bind the current source/install identity.

- [ ] **Step 4: Run fresh independent review**

Reviewer checks product UX, sandbox escape/network/host-mutation claims, unique Runtime/ToolRuntime owner and exact receipt identity without inheriting executor PASS. Any fix invalidates the seal and requires only affected focused tests, then one final source/materialized/E3 cycle.

- [ ] **Step 5: Promote accurate capability claims**

Only after U3 PASS, update status to delivered: arbitrary shell/code execution **inside the qualified sandbox**, not host arbitrary shell or production-ready cross-platform isolation. Record remaining limits and hand off to the 018 plan.
