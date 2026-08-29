# 019 macOS Host Profile Execution Log

本日志只记录可恢复的实现与验证状态；它不是 receipt，也不提升任何 capability status。

## Task 1 — POSIX persistence and owned workspace

- status: `completed`
- portable prerequisite: `019-portable-control-core=accepted/delivered`
- implementation boundary:
  - `PosixAutomationRepository` 使用 0700 root、0600 state/lock、nonblocking `flock`、
    descriptor-relative state I/O、CAS、atomic replace 与 post-replace unknown 映射。
  - `PosixOwnedWorkspaceRepository` 只消费 pre-bound source/root；source traversal/copy、
    artifact admission 与 cleanup 使用 no-follow/identity checks，host source 不被修改。
  - 校验后 workspace replacement 返回 `CLEANUP_UNKNOWN`，替换内容不被删除；metadata
    fsync-after-replace 返回 unknown，并可通过 durable readback/retry 恢复。
  - 原 1437 行草稿已按 POSIX primitives、AutomationStore、workspace lifecycle、descriptor
    traversal 和 strict codec 拆分；`posix_storage.py` 仅保留稳定 exports。
- focused/conformance gate:
  - `53 passed, 1 skipped in 0.87s`
  - skip reason: 当前 Coding sandbox 禁止创建 AF_UNIX socket node；真实 socket-node
    mutation 保留给 final qualified-host U2B，不能由此 Task 的 skip 推导宿主已 qualified。
- static gates:
  - touched Ruff: PASS
  - `git diff --check`: PASS
- ownership check: host storage imports no controller/scheduler/provider/ToolRuntime and adds no
  model/tool loop.
- next_task: `3-macos-composition`

## Task 2 — POSIX supervisor and existing Runtime executor

- status: `completed`
- implementation boundary:
  - `PosixOccurrenceSupervisor` 只拥有一个 `start_new_session=True` child group、bounded
    READY/start/result 私有协议和 TERM→KILL→liveness cleanup；父进程不调用 executor。
  - child spec/frame 使用 64 KiB exact schema；task text、store path、stdout/stderr 与 raw
    exception 不进入 argv 或 public result。
  - PGID 身份不确定会精确回收 leader 后 fail closed；result 后 liveness 不确定映射
    `CLEANUP_UNKNOWN`，绝不报告 cleaned。
  - `RuntimeOccurrenceExecutor` 在 launch 前创建/加载 exact `LocalCheckpointStore`，并只经
    `ScheduledOccurrenceCaller.run_once()` 进入既有 `AgentRuntime`。新 executor 实例从同一
    checkpoint replay 时 provider send 保持零增量。
- focused/process-group gate:
  - `30 passed in 19.78s`
  - files: three Task 2 supervisor/protocol suites, Runtime executor suite, shared process-group,
    local runner cleanup and subagent termination contract.
- static gates:
  - touched Ruff: PASS
  - `git diff --check`: PASS
- ownership check: `agent/automation_hosts` 不直接出现 `provider.generate`、
  `ToolRuntime.invoke` 或 `AgentRuntime.run_turn`；唯一 execution delegation 是已有 scheduler
  caller。
- next_task: `3-macos-composition`

## Task 3 — macOS qualification and static occurrence composition

- status: `implementation_complete_host_gate_pending`
- implementation boundary:
  - `BackgroundSeatbeltPolicyV1` compiles one default-deny, network-off profile with
    only the occurrence workspace, job temp/HOME, qualified runtime roots and exact
    executable literals readable; the existing 017 registration/confiner consume it
    through explicit injected compiler/policy seams, while ordinary 017 defaults stay
    unchanged.
  - `MacOSAutomationHostProfile` binds supervisor, Seatbelt backend/policy,
    Chromium/Playwright identity, provider descriptor/trust/disclosure/environment
    identity and credential availability before composition. Credential values are
    passed transiently to the existing provider factory and never stored in the host
    result or Runtime checkpoint.
  - `build_occurrence` validates the exact definition, active claim, checkpoint,
    snapshot, workspace and budgets, then delegates to the existing
    `build_composition`. The only registrations are `sandbox_exec` plus the five 018
    browser registrations; background authority remains interpreted exclusively by
    `KernelToolRuntime`.
- focused/architecture gate:
  - `163 passed, 4 skipped in 5.22s`
  - skip reasons: this managed Coding sandbox rejects nested `sandbox-exec` and
    loopback fixture sockets with `EPERM`; these skips do not qualify the host and the
    exact real probes remain mandatory in U2B.
- static gates:
  - touched Ruff: PASS
  - `git diff --check`: PASS
  - portable `agent.automation` imports no host module; host code contains no direct
    `run_turn`, provider `generate` or tool `invoke` call.
- Graphify note: the existing graph predates the new host module, so it was used only
  for the established Runtime/composition vocabulary; current-source AST/import and
  single-owner tests are the authoritative boundary evidence.
- next_task: `4-launchd-adapter`

## Task 4 — one global launchd cold-wake adapter

- status: `completed`
- implementation boundary:
  - `LaunchdWakeAdapter` renders one canonical fixed-label plist containing only the bound
    installed executable, the single `reconcile` argument, `RunAtLoad=false` and a bounded
    `StartInterval`. No shell, store locator, automation id, task, URL, profile, credential or
    model-authored value is accepted by the renderer.
  - The adapter binds executable content/file identity and both owner-directory identities before
    installation. Plist and ledger I/O are owner-only, no-follow and crash-safe; exact on-disk
    digests plus closed command exit classes are the only readback inputs.
  - `bootstrap`/`bootout` uncertainty is written as a durable pending ledger phase. Unknown or
    drift cannot be overwritten as a compatibility repair, replacement plist files are never
    removed, and disable refuses while an occurrence worker is active.
  - The portable wake port now owns only configured-policy readback/install/remove results.
    `AutomationManagementService` and the existing thin CLI implement `wake enable/disable` with
    closed codes; no macOS type or path enters the portable action surface. A separate
    `macos_cli.py` wrapper was intentionally not added here because it would only duplicate the
    existing CLI-to-injected-port boundary; the final U2B trusted composition will supply the
    concrete adapter.
- focused/architecture gate:
  - `271 passed, 5 skipped in 5.49s`
  - files: all portable automation tests, all current macOS host tests, portable/host 019 boundary
    gates and the portable-core reference gate.
  - skip reasons remain the current managed Coding sandbox's nested Seatbelt, loopback socket and
    AF_UNIX restrictions. They do not count as U2B host qualification.
- static gates:
  - touched Ruff: PASS
  - `git diff --check`: PASS
  - portable `agent.automation` imports no host module; launchd does not call Runtime, provider or
    ToolRuntime.
- identity note: adding the previously reserved portable `wake disable` operation changes the
  source tree, so the old U2A/Task 3 identities are stale and must be rebuilt in the final frozen
  source chain.
- next_task: `5-macos-u2b`

## Task 5 — frozen host identity and U2B qualification

- status: `materialized_green_host_not_qualified`
- The final current-tree source full gate passed `2633` tests with `11` explicit skips. The macOS
  host seal contains 405 exact entries and binds overlay root
  `d174ba614c2c3df4f0ec53e6c248f4825ea3b44ac915afa71fe16eb79d93cc35`; seal SHA-256 is
  `27d812c1de10a0d686e366c2aec882ac2549534af71f7e0999e85f9720100f03`.
- The host materialized gate passed `2630` tests. It binds materialized root
  `4db74adfc77165b1a4a0547d5ef602f80794fd7b3a440f5ae3fd029e66c366ad` and wheel SHA-256
  `698114eb3fc49353c37083bb22f487e9b2ba181d93614c15edc32c1b1d58c675`.
- Source and materialized preflight both returned the same closed result: macOS browser runtime
  available and launchd cleanup confirmed, but nested Seatbelt unavailable in the managed Coding
  sandbox. Exit code was `2`, status `not_qualified`, reason `seatbelt_unavailable`; no product
  U2B receipt was written and no host capability was promoted.
- The portable core remains platform-neutral. `agent.automation` has no host import; the optional
  concrete implementation is isolated under `agent.automation_hosts`. Host composition exposes
  the existing Runtime resource rather than a second `run_turn` proxy, and static gates still
  enforce one provider/tool loop owner.
- Final U2B requires the same sealed materialized bundle to run in a non-nested macOS user session
  where launchd, Seatbelt and Playwright/Chromium all qualify. Fresh independent Spec/Product and
  Standards/Architecture PASS reviews must then bind that receipt before attestation.

- next_task: `qualified-host-u2b-and-fresh-independent-review`
- No commit or push performed.

## 2026-08-29 — Qualified-host U2B and final delivery closure

- status: `qualified`
- The installed U2B host now binds the strict background Seatbelt compiler, starts Python in
  isolated mode with a closed minimal environment, and removes its exact test-owned wake after a
  process-confirmed failed attempt. Credentials and inherited ambient environment are not copied
  into the child process, plist, checkpoint or receipt.
- The launchd kickstart budget is 30 seconds, exceeding launchd's documented/default 10-second
  throttle interval. A real probe and the final U2B each completed all three wakes.
- The host runner now reuses the portable canonical materialized-tree digest. A Red parity test
  proved the former duplicate algorithm produced a different identity for the same tree; the
  current receipt, wheel artifact and verifier all bind
  `97060d5a2eb997640b9c29310e6f525b6a5e2fab16aee147830d5cd83a36e5fc`.
- Final source gate: `2654 passed, 1 skipped`; final clean host materialized gate: `2650 passed`.
  The first host content attempt had one `READY` scheduling timeout after the otherwise-complete
  suite. The exact node then passed 50 consecutive repetitions, and the complete host content
  gate rerun passed; no timeout budget or product behavior was widened for that non-reproducing
  event.
- Final host seal has 405 exact entries. Overlay root:
  `126a3c799da8846aec5d37c93d58933d4ec1df1a73045b1112246a41afbcf4d3`; seal SHA-256:
  `7baaab98b22cfc406b40156118fbf45763ecf4eaa77f39021e869469c286be7e`;
  runner SHA-256:
  `ec7e35a9154a872ea1f680d0fec7f6493805110fdaf407d4e0501fe6d380d72e`;
  wheel SHA-256:
  `aa633f3581c51a0ce196c7ca2d149a0c0d52a8ec73dd8608705be97b30381614`.
- Qualified preflight proved Playwright/Chromium, launchd wake/cleanup and Seatbelt availability.
  Final U2B recorded 3 real wakes, 1 child dispatch, 3 provider calls, 1 governed tool call, 1
  sandbox receipt and 5 browser observations. Duplicate and misfire provider/tool/effect deltas
  were all zero; process group, browser, LaunchAgent and test-root cleanup checks were true.
- Membership, control-seal and U2B attestation each returned exit 0. Final receipt SHA-256:
  `467dff4ca7b5a0544fcaf3e9c294db69edddc62d70f0859283673c6c78d57427`.

### Current state

- `019-macos-host-profile=qualified`
- `019-u2b-real-wakes=3`
- `next_task=none`
- No commit or push performed.

## 2026-08-29 — Git 交付前最终重封

- portable 最终树变化后，macOS host seal、materialized gate 与真实 U2B receipt 全部重新生成；
  未复用旧身份，也未放宽 launchd、Seatbelt 或 cleanup 边界。
- 最终 host seal：405 entries，overlay root
  `b7161451a2b9ae5e272689fa4aa478ff55cb372ea8d2558f773147fe76f6ea27`，seal SHA-256
  `c7aa077c875a26945af8b5242838428d6c85478b276ebbd63c25c030da36dd64`。
- clean host materialized gate：`2650 tests`，与 portable 共用 canonical materialized root
  `05ba50896ea1e40af28407e9e2593e367b50fb1eccfd12626cccf2f7cb6940a4` 和 wheel SHA-256
  `d1b20b328bfa4d828332c26d94a8083056d895f5361e790a1ebc63973719b5e5`。
- preflight 为 `qualified`；最终 U2B 重新完成 3 次真实 launchd wake，process/browser/
  LaunchAgent/test-root cleanup 均确认。membership、control-seal、attestation 均 exit 0；
  receipt SHA-256
  `e926b7462f84c63568e690a793da02ab099b1f42846619ed49d0538d1641567c`。
- `019-macos-host-profile=qualified`；`next_task=git-delivery`。
