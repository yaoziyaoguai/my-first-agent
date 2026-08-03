---
title: Capability Reintroduction Stabilization - Plan
type: fix
date: 2026-07-19
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: audit-2026-07-19
execution: code
---

# Capability Reintroduction Stabilization - Plan

## Goal Capsule

- **Objective:** 保留 Minimal Runtime Kernel 和六项已接入 seam，修复 `docs/audits/2026-07-19-capability-reintroduction-audit.md` 的 A1-A19，使当前实现成为可从 Git materialize、可安全本地验证、并对每项能力给出明确 E3 eligibility verdict 的 capability candidates。SubAgent 在没有合格 provider-native hard-deadline receipt 前必须保持 E3-blocked；安全拒绝本身可以成为其 automated/local verification 结果，但不是产品价值验收。
- **Authority:** `AGENTS.md` > `docs/architecture/KERNEL_ARCHITECTURE.md` > `docs/architecture/EXTENSION_CONTRACTS.md` > 本计划 > 各 capability design。旧 worklog 的完成措辞不是行为权威。
- **Execution profile:** Red-first，按 U0-U9 串行。每个 unit 先证明目标缺口，再做最小 Green；不得把测试改成迎合当前行为。
- **Stop conditions:** 需要第二套 loop、service locator、dynamic plugin discovery、compatibility fallback、不可终止 helper thread、真实 credential/private data 或未经用户批准的外部调用时停止并报告。
- **Tail ownership:** Coding Agent 负责代码、自动测试和文档同步；用户独占 E3 reference-task 授权与 accepted 决策。

---

## Product Contract

### Summary

这不是新一轮架构重写。Kernel owner boundaries 保持不变；工作只补齐 delivery、安全分类、人类审批、durable state、lifecycle 和 acceptance honesty。

### Requirements

**Delivery and claims**

- R1. `agent/memory/`、`tests/memory/` 以及所有当前 product/test package 必须被 Git materialize；runtime-state ignore 只能匹配明确的仓库根目录或文件模式，不能吞掉同名源码目录。
- R2. 最终自动门必须从 clean Git materialized tree 安装并收集测试；脏工作树 `pytest`、默认尊重 ignore 的 Ruff 和 `git diff --check` 不能单独作为 delivery proof。`docs/implementation/008_INTENDED_TREE_MANIFEST.json` 的 `entries` 精确列出 add/modify/delete path、ordered `owner_units` 与 add/modify final content digest；同一路径可由多个 unit 按顺序拥有，禁止用单 owner 掩盖后续修改。U0 只冻结不可变的 schema/baseline/control-file paths 和初始 audited membership，U1-U9 更新自己拥有路径的 owner chain，U9 才冻结全部 final digest。manifest 自身是 schema-validated root of trust，不自我哈希；持续变化的 execution log 和依赖 content-gate 结果的 current-status claim 是 post-gate control evidence，不进入 `entries`，其最终 digest 由 manifest 的 `control_files` 单向封存。这些 control files 必须是非执行、非构建输入；verifier 发现它们被 package metadata、test collection 或 runtime 消费时失败。临时 Git index 只应用 `entries` 与三个 exact control-file paths，不得 repository-wide add、stage/改写真实 index 或要求 commit。交付门必须证明所有其他 product/test/package/doc path 有 owner、进入 intended tree 且被对应 checker 扫描。
- R3. README、roadmap、worklog 和 capability status 使用统一 claim vocabulary：designed、implemented-candidate、locally-verified、accepted。E3 未完成时不得写“重接完成”。

**MCP safety and outcome**

- R4. MCP child process 只接收显式 allowlisted environment；empty allowlist 等于 empty environment，不得退化为 inherit-all。credential-looking env 转发必须有 operator-readable profile；credential values 在 composition 时冻结于不可序列化 holder，不能在 approval 后重新从 global environment 取值。
- R5. MCP executable、ancestor、cwd identity/content 在 catalog、prepare、spawn 前通过 descriptor-relative no-follow handle 复验。`cwd` 是必填的 operator-supplied absolute directory；missing、relative、symlink 或 unsafe ancestor 在 composition 前拒绝，绝不继承 process cwd/workspace。cwd identity 进入 config digest、preview、intent binding。drift 在 spawn 前返回 known-not-executed，server process count 为零。v1 仅接受 operator-trusted local executable；最后一次校验到 OS spawn 的同-UID replacement window 是明确残余风险，不得宣称 filesystem/process sandbox。
- R6. MCP approval preview 完整显示 server/tool/executable/cwd/profile/safety generation 和 canonical arguments；argument cap 不大于 escaped preview cap。无法完整显示时 effect 前拒绝，不截断、不 spawn。
- R7. bridge 的所有宿主 timeout/exception 必须携带 commit receipt。call bytes 可能写出后，只有 matching terminal response 且 process-group cleanup confirmed 才能 `EXECUTED`；否则 `UNKNOWN`、latch 保持 ARMED、bridge quarantine、parent recovery。只有证明未写出才 `NOT_EXECUTED`。
- R8. MCP transport 对 stdout、stderr、list、result 和 error 全部 bounded；stderr 持续 drain 且不进入 model/checkpoint。transport owner 产生 sanitized result/error：除实时完整 approval preview 外，raw stderr、catalog/env values、credential sentinels 和绝对私有路径不得进入 ToolResult、model、checkpoint、event、renderer 或 evidence。client capability manifest 只声明 v1 所需 tools 能力；sampling、roots、elicitation、tasks 和 unsolicited server requests fail closed，不得触发 provider/workspace/credential access。partial write、wrong ID、malformed/JSON-RPC error、oversized result、grandchild/cleanup failure 各有确定分类，无自动 retry。
- R9. MCP latch 使用 owner-only/no-follow/strict bounded JSON、stable lock 与 atomic fsync replace；首次 missing target 可合法 bootstrap。operator-only recovery CAS 只有在 marker revision/token/full binding 精确匹配、operator 肯定确认残余进程已终止，且 credential-bearing marker 已确认 rotation 并提供新的 safety generation 时才可 clear；任一条件缺失或否定都保持 ARMED、spawn count 为零。系统记录 attestation，但不声称自动验证外部事实。

**Memory context and persistence**

- R10. Memory source/test 文件先满足 R1；Memory data/lock/temp 通过 stable dirfd/no-follow handles、owner/mode/link/size/strict schema validation 和同锁 revision CAS 读写。unknown fields、digest/revision/timestamp/record invariant 违反 fail closed，源文件不覆盖。
- R11. 每次 Memory source snapshot 来自一次 fresh revision-consistent durable snapshot，遵守 `ContextSourceLimits`；排序固定 `score desc, updated_at desc, record_id asc`。
- R12. Memory candidate 要么完整 bounded 进入 context，要么明确 excluded/clipped 并记录原长/digest；不能用完整 record digest 标记未声明的前缀截断。
- R13. Memory remember/update/forget 的 executable input 必须能完整安全展示。remember preview/binding 包含 scope、store revision 和完整 content；update 是 bounded before/after diff；forget 展示被删除内容。stale preview effect count 为零。
- R14. Memory crash/locking tests 覆盖 independent lock inode、temp collision、replace/fsync points、symlink/hardlink/ancestor swap、多进程 CAS 和 reopen consistency。

**Closure for adapters and delegated execution**

- R15. Scheduler duplicate first-action replay只验证 occurrence identity；report 由最新 authoritative state 生成。pause → human resolution → terminal → duplicate 必须报告 terminal，provider/effect count 不增加。首次 `conversation_busy` 或 `checkpoint_conflict` 只允许 reload 一次并重交完全相同 action；第二次冲突原样结束，禁止 loop。UTC identity 必须 calendar-valid 且 canonical round-trip。
- R16. TUI 从 shared composition 接收与 Runtime 相同的 queue EventSink，events 只 advisory；不得同时把 background worker event 写入 terminal renderer。
- R17. `docs/architecture/capabilities/TUI_DESIGN.md` 的 Authoritative projection matrix 与 rendering/privacy rules 对 U6 是 normative。TUI 纯键盘表达 submit、approve、reject、mark succeeded、mark failed、resume 和合法 paused cancel；startup/reopen 从 checkpoint 投影 pending/interrupted state；`RUNNABLE/EXECUTING` unknown effect 只允许 Resume。active worker 保留最近 authoritative content，始终显示本地 bounded “working；不能安全取消在途 effect”状态，禁用 action controls；event progress 只补充。approval/recovery form 显示完整 escaped bounded preview、request ID、risk/effect class 与 safe summary，action 绑定 raw canonical digest；escaped preview overflow 在 `EXECUTING` 前拒绝。Scheduler handoff 只接受显式 `state-root + relative checkpoint reference + workspace`，不扫描、不猜 cwd。
- R18. CLI、TUI、Scheduler 所有退出路径共用 lifecycle：停止接收新 action，等待 bounded invocation/worker 收口或保留 recovery state，然后 reverse-close resources。TUI active close 必须投影 `closing_requested`；底层违反 deadline 时保持 `shutdown_blocked`、resources 存活、无 force-exit/cancel control。startup failure 也关闭已经构造的 closeables。
- R19. SubAgent ChildProfile 绑定 supported provider trust identity 和 provider-native hard total-deadline/termination-receipt contract；composition 对缺失、soft/inactivity-only 或超过 child cap 的 deadline fail closed。当前 OpenAI/Anthropic HTTP adapters 只有阶段/inactivity timeout，不符合 v1 SubAgent hard-deadline contract，必须拒绝注册；runner 不创建 thread 包装或伪造 timeout。受支持 provider 通过 call-scoped single-use wrapper 记录 `NOT_STARTED | TERMINATED | UNCONFIRMED` receipt；`AgentRuntime.run_turn` 返回或抛错后，runner 必须先读取 receipt 再解释 child RunResult。`UNCONFIRMED` 总是覆盖 child nonterminal/error 分类并向父 ToolRuntime 返回 typed unknown，使 parent 进入 recovery；confirmed termination 才能成为 known-executed error。
- R20. SubAgent objective/handoff 采用 schema/prepare-time bounded rejection，不静默截断；approval 显示完整 executable handoff 与 destination。child 仍是同一个 `AgentRuntime` class、独立 in-memory state、空 ToolRuntime、空 ContextSource、最多一次 model call。只有 `COMPLETED` 是成功；已确定执行过但非完成的 child 结果是 known-executed error，未分类 provider failure 保持 unknown。
- R21. Skill 继续保持 READ_ONLY governed tools；frontmatter 是 bounded strict allowlist，拒绝 unknown/duplicate keys、aliases/cycles；bounded metadata 对模型可见，scan 后 ancestor/file identity 与 digest 都复验。不得引入 prompt hook、scripts、auto activation 或默认目录扫描。

**Evidence honesty**

- R22. 现有 FakeProvider/local fixture tests 统一标为 E0-E2 automated evidence。E3 只按 `docs/acceptance/CAPABILITY_REFERENCE_TASK_PROTOCOL.md` 记录，且必须由用户单独授权外部 destination/effect。
- R23. 每个 finding 至少有一个会在修复前失败的 targeted test；禁止只加 source-shape assertion 而不验证可观察行为。

**Shared Kernel regressions exposed by the audit**

- R24. File tool 对 ASCII private-root names 使用 casefold comparison；read/list/write/edit 对大小写变体执行同一拒绝。不得读取真实 private roots 作为测试数据。
- R25. stale approval/binding/precondition mismatch 必须在 effect count 为零时清除旧 grant 并产生可处理的 known-not-executed Tool Result；不得因 cursor invariant 进入 `FAILED_FATAL`，不得复用旧 grant。
- R26. ContextManager 的 untrusted context candidate 有 provider-neutral strict schema；OpenAI/Anthropic adapters 在无网络 request projection 中把它转换为明确标记、非-system 的 user content，不丢 source/id/digest/untrusted 语义。
- R27. callable outcome taxonomy 区分 known-not-executed、known-executed success、known-executed error 和 unknown。MCP remote `isError`/unsupported content、SubAgent nonterminal 都不得成为 success string；unknown 外部 outcome 不得降级为 known error。

### Acceptance examples

- AE1. Given a clean Git-materialized tree, when `pip install` and test collection run, then Memory imports/tests exist and test count does not depend on ignored files.
- AE2. Given an MCP config with no env names and a parent sentinel secret, when the fixture process prints its environment keys, then the sentinel is absent.
- AE3. Given an MCP call whose bytes are written and the bridge total timeout fires, when Runtime receives the outcome, then it enters one recovery request and no automatic second call occurs.
- AE4. Given a 1,001+ character Memory record, when the model proposes remember/update/forget, then the full executable effect is either safely visible or rejected before `EXECUTING`; it is never silently preview-truncated.
- AE5. Given a scheduled occurrence paused at approval, when a human resolves it with seq 2 and a duplicate external fire replays seq 1, then the report is terminal and provider/effect counts remain unchanged.
- AE6. Given a durable approval checkpoint, when TUI starts, then the approval form is focused without provider/tool calls and can be completed by keyboard to the same action digest/result as CLI.
- AE7. Given current HTTP adapters or any provider without a native hard total-deadline/termination receipt, when `--subagent` composition starts, then startup fails before registration or child call.
- AE8. Given a protected `skills/` directory on a case-insensitive filesystem, when every file operation uses a case variant, then all operations fail before opening the target.
- AE9. Given an approval grant whose precondition changes before resolution, when the exact stale grant is submitted, then the callable count is zero, the run does not become fatal and a new effect requires a new grant.

### Audit trace matrix

Target test names are part of the implementation contract. A Coding Agent may move a test only when it records the new name in the execution log and preserves the same observable assertion.

| Finding | Requirements | Owner unit | Acceptance example | Named target test |
|---|---|---|---|---|
| A1 | R1-R2 | U0/U9 | AE1 | `tests/architecture/test_delivery_manifest.py::test_materialized_tree_contains_and_lints_memory` |
| A2 | R4 | U2 | AE2 | `tests/mcp/test_integration.py::test_empty_env_allowlist_does_not_inherit_parent` |
| A3 | R7 | U3 | AE3 | `tests/mcp/test_tools.py::test_post_send_bridge_timeout_enters_unknown_recovery` |
| A4 | R5-R6 | U2 | — | `tests/mcp/test_tools.py::test_approval_binds_full_arguments_and_executable_identity` |
| A5 | R7-R8 | U3 | — | `tests/mcp/test_bridge.py::test_cleanup_uncertainty_forces_unknown_and_quarantine` |
| A6 | R9 | U3 | — | `tests/mcp/test_safety.py::test_recovery_clear_requires_exact_binding_process_and_rotation_attestations` |
| A7 | R13 | U4 | AE4 | `tests/memory/test_tools.py::test_mutation_previews_are_complete_and_revision_bound` |
| A8 | R10/R14 | U4 | — | `tests/memory/test_store.py::test_strict_snapshot_rejects_replacement_and_tampering` |
| A9 | R11-R12 | U4 | — | `tests/memory/test_integration.py::test_rank_and_projection_preserve_recency_and_digest_evidence` |
| A10 | R15 | U5 | AE5 | `tests/scheduler/test_caller.py::test_human_resolution_duplicate_reports_authoritative_terminal_state` |
| A11 | R16-R18 | U6 | AE6 | `tests/tui/test_app.py::test_pending_reopen_keyboard_journey_and_shared_lifecycle` |
| A12 | R19-R20 | U7 | AE7 | `tests/subagent/test_runner.py::test_provider_without_native_hard_deadline_receipt_is_rejected` |
| A13 | R21 | U8 | — | `tests/skill/test_catalog.py::test_activation_revalidates_metadata_and_file_identity` |
| A14 | R3/R22 | U8 | — | `tests/architecture/test_capability_claims.py::test_e3_claims_require_acceptance_records` |
| A15 | R24 | U1 | AE8 | `tests/tools/test_path_safety.py::test_private_roots_reject_case_variants_for_all_operations` |
| A16 | R25 | U1 | AE9 | `tests/kernel/test_tool_outcomes.py::test_stale_approval_is_nonfatal_nonexecution` |
| A17 | R26 | U1/U4 | — | `tests/provider/test_memory_context_projection.py::test_both_adapters_project_untrusted_context_without_network` |
| A18 | R27 | U1/U3/U7 | — | `tests/kernel/test_tool_outcomes.py::test_known_executed_errors_are_not_success` |
| A19 | R21 | U8 | — | `tests/skill/test_catalog.py::test_frontmatter_rejects_unknown_and_ambiguous_yaml` |

### Scope boundaries

Deferred until this plan's automated DoD is complete and the user either completes the relevant E3 gate or separately authorizes new scope: new capability types, streaming, multiple concurrent child agents, MCP resources/prompts/sampling, Memory semantic/vector retrieval, Scheduler CRUD/timers, TUI dashboards/editors. Automated completion alone does not authorize expansion. TUI v1 accessibility claim 仅限可自动验证的 keyboard reachability、visible focus、deterministic Tab order、text labels 和 non-color decisions；screen-reader/terminal assistive-technology compatibility 未验证且不得宣称。

Permanently excluded: second model/tool loop, agent self-approval, implicit cwd/workspace discovery, dynamic plugin registry, legacy compatibility layer, event-driven authoritative state.

---

## Planning Contract

- KTD1. **Repair seams, do not replace them.** Keep one production `AgentRuntime.run_turn`, one `KernelToolRuntime` per composition and one ContextManager selection path.
- KTD2. **Commit receipt owns outcome classification.** Executor convenience exceptions never override transport knowledge; ambiguous external effects remain unknown.
- KTD3. **Human-readable preview and machine digest are both required.** A digest prevents stale approval but does not prove the user understood the target.
- KTD4. **Durable files share one security shape.** Checkpoint、Memory、MCP latch use explicit roots, dirfd/no-follow handles, strict bounded decode, stable lock, atomic replace and fsync; capability-specific formats remain separate.
- KTD5. **Materialized-tree verification closes ignore gaps.** The final gate tests what another machine receives, not only what happens to exist in the current directory.
- KTD6. **Automated readiness and product acceptance remain separate.** Coding execution ends at a locally-verified candidate; user-authorized E3 records promote capabilities independently.

Implementation order is dependency-driven: U0 makes evidence deliverable; U1 repairs shared Kernel regressions before effectful capability work; U2-U3 repair MCP before any real MCP use; U4 repairs Memory before trusting context; U5-U7 close execution/adapters; U8 aligns Skill/docs; U9 runs materialized-tree and full gates.

---

## Implementation Units

`docs/implementation/008_STABILIZATION_EXECUTION_LOG.md` 是 U0-U9 唯一允许跨 unit 持续更新的证据文件；`docs/implementation/008_INTENDED_TREE_MANIFEST.json` 是唯一 delivery membership source。manifest 不自我哈希；execution log 与 `docs/architecture/CURRENT_CAPABILITY_STATUS.md` 不进入内容树 `entries`，只在 U9 content gate 后由 manifest 单向记录最终 digest。三个 control files 都不能是执行、构建或 test-discovery 输入，也不能把失败改写为 Green。

### U0. Restore delivery integrity and Red baselines

- **Goal:** Make every product/test file visible to Git and turn A1-A19 into reproducible failing tests without changing product behavior yet。只冻结 manifest 的 baseline/control schema 与初始 membership，不在 U0 假装 final digest 已稳定。
- **Files:** `.gitignore`, `scripts/verify_materialized_tree.py`, `docs/implementation/008_INTENDED_TREE_MANIFEST.json`, `tests/architecture/test_cutover_absence.py`, new focused delivery/contract tests under existing capability test packages, `docs/implementation/008_STABILIZATION_EXECUTION_LOG.md`.
- **Test scenarios:** manifest rejects unowned/missing/hash-mismatched/ignored-private paths and represents audited add/modify/delete without broad add；`git check-ignore` on exact product/test paths；clean Git materialization contains and lints Memory；current private-root case bypass、stale approval fatal、provider context rejection、known-executed error flattening、MCP empty-env/timeout、Memory preview、Scheduler replay/concurrency、TUI pending form、SubAgent unsupported deadline 和 Skill unknown-key tests 都因目标缺口而失败。
- **Verification:** review each Red failure against R1-R27; do not proceed with a Red that fails because of fixture setup、ignored source、optional dependency absence或 test-double 绕过 production composition。

### U1. Repair shared Kernel safety regressions

- **Goal:** Satisfy R24-R27 without changing the one-loop/one-ContextManager/one-ToolRuntime ownership model.
- **Files:** `agent/tools/path_safety.py`, `agent/tools/file_ops.py`, `agent/runtime/state.py`, `agent/runtime/tools.py`, `agent/runtime/context.py`, `agent/provider/normalize.py`, OpenAI/Anthropic request builders, `tests/kernel/test_tool_outcomes.py`, and focused tests under `tests/tools/`, `tests/kernel/`, `tests/provider/`.
- **Patterns:** filesystem-semantic private-root comparison; reducer transition that explicitly consumes grants; strict provider-neutral untrusted context projection; typed callable outcomes.
- **Test scenarios:** case variants across read/list/write/edit; approval then target/binding/precondition drift through full Runtime; Memory context projection through both real adapters without network; MCP and SubAgent known-executed error plus unknown non-regression.
- **Verification:** effect/provider/open counts are zero on denied paths; no second loop or capability-specific ToolResult wrapper; existing architecture owner tests and context budget tests remain Green.

### U2. Repair MCP approval, identity and environment boundaries

- **Goal:** Satisfy R4-R6 before any server process can start.
- **Files:** `agent/mcp/catalog.py`, `agent/mcp/tools.py`, `agent/mcp/bridge.py`, `agent/composition.py`, `main.py`, `tests/mcp/test_catalog.py`, `tests/mcp/test_tools.py`, `tests/mcp/test_integration.py`.
- **Patterns:** descriptor-relative verified executable/cwd handle; frozen credential holder; canonical full preview; pre-spawn known-not-executed drift.
- **Test scenarios:** empty allowlist secret absence; credential-looking env requires profile; env value changes after approval do not change frozen execution credential; missing/relative/symlink cwd and executable/ancestor/cwd replacement between catalog/prepare/spawn; arguments and escaped preview overflow; first-use missing latch target.
- **Verification:** server spawn count stays zero on every precondition failure; preview and intent digest bind the same canonical arguments.

### U3. Repair MCP outcome, transport and durable latch

- **Goal:** Satisfy R7-R9 with a complete commit-state fault matrix.
- **Files:** `agent/mcp/contracts.py`, `agent/mcp/bridge.py`, `agent/mcp/safety.py`, `agent/mcp/tools.py`, `main.py`, `tests/fixtures/mcp/stdio_server.py`, `tests/mcp/test_bridge.py`, `tests/mcp/test_session.py`, `tests/mcp/test_safety.py`, `tests/mcp/test_tools.py`, `tests/mcp/test_integration.py`.
- **Patterns:** typed host timeout outcome; bounded concurrent stdout/stderr drain; terminal response + request match + process exit join; ARMED latch retained across uncertainty; operator-only CAS recovery command.
- **Test scenarios:** timeout before call; timeout after first call byte; partial write; wrong request ID; invalid JSON; JSON-RPC error; `isError`; unsupported and oversized content; stdout/stderr overflow；stdout/stderr/error/result synthetic secrets and absolute paths remain absent across ToolResult/model/checkpoint/event/renderer/evidence；server-initiated sampling/roots/elicitation/tasks/unsolicited request；forked grandchild、cleanup failure；host crash/reopen/human outcome resolution；recovery missing/negative/stale process/rotation/generation/binding attestations all retain ARMED；two-process latch race。
- **Verification:** each matrix cell asserts classification, parent RunStatus, latch status, bridge status and exact process/call count.

### U4. Repair Memory durability, approval and context selection

- **Goal:** Satisfy R10-R14 and verify R26 with an actual Memory candidate, without adding retrieval features.
- **Files:** `agent/memory/contracts.py`, `agent/memory/store.py`, `agent/memory/source.py`, `agent/memory/tools.py`, `agent/runtime/context.py`, `agent/composition.py`, `main.py`, `tests/memory/*`, related context/provider tests. U1 remains the sole owner of provider projection implementation.
- **Patterns:** strict immutable store snapshot; stable independent lock file; bounded exact preview snapshot; deterministic rank key; explicit clipping/exclusion evidence.
- **Test scenarios:** strict unknown-field/type/digest/revision failures; no-follow/owner/mode/link/size; lock inode replacement; symlink/hardlink/ancestor swap; temp/fsync/replace crash points; concurrent CAS; external process mutation visible on next snapshot; equal-score recency; long candidate budget; remember/update/forget stale preview and complete display; both provider adapters accept one recalled untrusted context block without network.
- **Verification:** no invalid input reaches `EXECUTING`; effect count is zero for stale/overflow/busy; next ContextPack is reproducible from snapshot digest and BudgetReport; adapter projection preserves untrusted source/id/digest markers and never creates system content.

### U5. Reconcile Scheduler reports after human resolution

- **Goal:** Satisfy R15 while preserving deterministic seq-1 replay and external-caller identity.
- **Files:** `agent/scheduler/caller.py`, `agent/scheduler/contracts.py`, `tests/scheduler/test_caller.py`, `tests/scheduler/test_cli.py`.
- **Test scenarios:** first completed + duplicate; first approval/recovery/limit + human seq-2 resolution + duplicate terminal report; barrier-controlled `conversation_busy`/`checkpoint_conflict` duplicate with one-shot reconciliation and second-conflict no-loop; same IDs with changed scheduled time/message/scope; replay-floor deterministic-run fallback; invalid month/day/leap-day/hour/offset/fractional timestamp.
- **Verification:** report comes from latest checkpoint; Scheduler never emits approval/recovery/Resume itself and never calls provider/tool/store mutation ports directly.

### U6. Complete TUI actions, event plumbing and lifecycle

- **Goal:** Satisfy R16-R18 for one conversation without adding dashboard features.
- **Files:** `docs/architecture/capabilities/TUI_DESIGN.md` (normative, change only if implementation proves a real contradiction), `agent/tui/adapter.py`, `agent/tui/render.py`, `agent/tui/app.py`, `agent/cli/actions.py`, `agent/composition.py`, `main.py`, `tests/tui/*`, `tests/cli/*`, `tests/scheduler/test_cli.py`, related event/lifecycle tests.
- **Patterns:** the complete authoritative projection matrix from TUI design；injected shared queue sink；guaranteed local worker-active projection independent of events；one Textual worker；keyboard forms using shared action builders；one composition lifecycle owner。
- **Test scenarios:** every row in the TUI design authoritative matrix, including ready、terminal reopen、approval/reject、recovery mark succeeded/failed、paused resume/legal cancel、RUNNABLE/EXECUTING restart、other interrupted RUNNABLE、stale owner、actual `conversation_busy` reload、conflict/worker exception reload；event loss/duplicate/reorder；terminal once；worker-active no-cancel status with zero actions；`closing_requested` and `shutdown_blocked`；complete escaped preview/control/bidi/markup/overflow；fixed visible Tab/focus order、text labels、non-color decisions and Enter never default-approves/mark-succeeds；Scheduler `state-root + relative ref + workspace` no-scan initial load with provider/tool count zero；CLI/TUI/Scheduler normal/error/conflict/startup-failure lifecycle verifies stop-accepting → bounded close/recovery preservation → reverse-close exactly once。
- **Verification:** Textual Pilot proves pure keyboard path and action digest/checkpoint/result parity with CLI; adapter creates no thread; no TUI code imports provider or concrete checkpoint mutation APIs.

### U7. Enforce bounded SubAgent provider execution

- **Goal:** Satisfy R19-R20 and R27's exact error classification without background children or recursive delegation.
- **Files:** `agent/subagent/contracts.py`, `agent/subagent/runner.py`, `agent/subagent/tools.py`, `agent/runtime/ports.py`, `agent/provider/protocol.py`, `agent/provider/openai_http.py`, `agent/provider/anthropic_http.py`, `agent/composition.py`, `main.py`, `tests/subagent/*`, focused provider contract tests.
- **Patterns:** explicit provider-native hard-deadline/termination-receipt descriptor; call-scoped single-use receipt wrapper survives Runtime exception normalization; current HTTP adapters declare unsupported and fail registration; same trust-domain identity; prepare-time length rejection; no timeout wrapper thread.
- **Test scenarios:** deterministic fake with a native hard deadline completes within cap；supported fake confirmed-timeout yields known-executed error；`tests/subagent/test_runner.py::test_unconfirmed_native_deadline_receipt_overrides_child_nonterminal_and_enters_parent_recovery` proves an unconfirmed timeout returns typed unknown and parent recovery even when child Runtime produced a nonterminal RunResult；current HTTP provider、provider missing deadline、soft/inactivity-only deadline、deadline larger than child cap and mismatched receipt all reject before child call；objective/handoff limit/limit+1 without truncation；destination/profile mismatch；with a `TERMINATED` receipt, every non-COMPLETED child status and child tool request yields `executed=True/is_error=True/code=child_nonterminal`；deterministic child identity and no duplicate call。不得用“late-returning blocking object”测试暗示 runner 能强制终止同步调用。
- **Verification:** no helper thread remains after return; no child tools/sources/workspace/credential inheritance; parent gets only bounded result/stat summary；receipt state is consumed exactly once and `UNCONFIRMED` can never be flattened by child Runtime error handling.

### U8. Close Skill contract and evidence wording

- **Goal:** Satisfy R21-R22 and correct contradictory documentation.
- **Files:** `agent/skill/catalog.py`, `agent/skill/tools.py`, `tests/skill/*`, `tests/architecture/test_capability_claims.py`, `README.md`, `docs/architecture/CAPABILITY_REINTRODUCTION_ROADMAP.md`, `docs/implementation/CAPABILITY_REINTRODUCTION_WORKLOG.md`, `docs/architecture/CURRENT_CAPABILITY_STATUS.md`.
- **Test scenarios:** bounded metadata visible only after normal definition/activation contract; unknown/duplicate keys、aliases/cycles、node/depth/scalar overflow; ancestor/file replacement; identical-content inode replacement according to frozen identity policy; existing YAML/security/resource/reference wiring non-regression; no default roots/scripts/prompt hook.
- **Verification:** docs identify automated E0-E2 evidence and leave E3 pending; no historical focused test count is used as acceptance status。U8 只统一 vocabulary 并保持所有 final gate 为 pending，不得提前晋级 `locally-verified`。

### U9. Materialize, package and run final automated gates

- **Goal:** Prove a new machine receives the same locally-verified candidate.
- **Files:** `scripts/verify_materialized_tree.py`, `docs/implementation/008_INTENDED_TREE_MANIFEST.json`, `docs/implementation/008_STABILIZATION_EXECUTION_LOG.md`, `docs/architecture/CURRENT_CAPABILITY_STATUS.md`, and packaging/test configuration only where the existing project pattern requires; no production feature additions.
- **Test scenarios:** validate the exact manifest and create an isolated temporary Git index from `HEAD`, applying only its `entries` plus the three declared control-file paths before materialization；从 materialized tree 构建并以 non-editable、`--no-deps --no-build-isolation` 安装到临时 venv/prefix；从原树和 materialized tree 之外的 neutral cwd 启动 package/entrypoint/pytest，清除 `PYTHONPATH`、`PYTHONHOME` 等 import injection，并在测试前断言全部 product module origins 和 console entrypoint 指向临时安装，任何 origin 指向原 dirty tree 都立即失败；Ruff 使用 materialized config 和 explicit materialized paths。已 provisioned project environment 只能提供 test/build dependencies，不能作为被测 product import source。运行 optional-dependency absence imports 和 materialized architecture/fault/full gates。只有用户提供 local wheelhouse 时才用 `--no-index` 另验完整 base/extras dependency installation；所有 pip 步骤设置 no-index/disable-version-check，不得访问 package index。
- **Verification:** U9 uses a two-phase seal. Phase 1: after all behavior gates pass, keep `CURRENT_CAPABILITY_STATUS.md` at pre-promotion claims, freeze every ordinary `entries` digest, and run `.venv/bin/python scripts/verify_materialized_tree.py --content`. Phase 2: use that known result to update only `CURRENT_CAPABILITY_STATUS.md` and the execution log, write both SHA-256 values into `control_files`, then run `.venv/bin/python scripts/verify_materialized_tree.py --control-seal`. The second mode revalidates schema, every ordinary content digest and both post-gate control digests but does not rerun product tests；it must prove the post-gate files are non-executable/non-package/non-test inputs and reject self-digest entries、unsealed controls、changed ordinary content、undeclared control paths and broad-add behavior. No repository file changes after the control seal; the user-facing final report is outside this evidence tree. Compare package/module/test manifests between source and materialized tree; Graphify refresh remains optional and only runs after confirming ignored/private inputs cannot be ingested.

---

## Verification Contract

Run focused tests after each unit. Before declaring the plan's automated work complete, run in this order:

```bash
git diff --check
.venv/bin/ruff check .
.venv/bin/ruff check agent/memory tests/memory
.venv/bin/python -m pytest -q tests/architecture
.venv/bin/python -m pytest -q tests/kernel tests/tools
.venv/bin/python -m pytest -q tests/skill tests/mcp tests/memory tests/subagent tests/scheduler tests/tui tests/cli tests/provider
.venv/bin/python -m pytest -q -rx
```

Then run the U9 clean Git materialized-tree content gate with `.venv/bin/python scripts/verify_materialized_tree.py --content`, use its known result to update only current status and the execution log, seal both digests in the manifest, and finish with `.venv/bin/python scripts/verify_materialized_tree.py --control-seal`. The script owns exact-manifest、temporary-index、offline install 和 two-phase seal procedures；it must refuse manifest self-digests, executable/build/test use of post-gate controls, broad add、real-index mutation、package-index access、unowned paths and any ordinary-content drift between phases.

No test may use real credentials, user private roots, real external MCP/provider or production-like state. Timeout, skip caused by missing required extra, truncated output, ignored test file, missing exit code or dirty-tree-only pass is a failure.

Each A1-A19 audit finding must have a named targeted regression test. Severity controls order, not whether a regression test is required. Review the final diff against the trace matrix before the full suite.

## Risks and residual trust boundaries

- MCP v1 没有 filesystem/process sandbox。即使 immediate pre-spawn identity check Green，同一 UID 的恶意本地进程仍可能竞争替换 executable；因此只支持 operator-trusted local executable，真实 server 必须等 E3 单独授权。
- Memory 是 owner-only 明文文件，会在相关 query 中进入模型上下文；它不抵御同 UID 进程、备份或磁盘泄露。secret-like detection 只能是 defense-in-depth，不能写成保密保证。
- SubAgent v1 只支持 provider-native hard total-deadline/termination receipt；当前 HTTP adapters 明确不支持。v1 不创建无法终止的 helper thread，也不声称能强制 kill 任意 in-process provider。
- U9 temporary-index harness 必须只应用 intended-tree manifest 的 exact paths/status/digests 与三个声明的 control files；若 manifest 对不上当前工作树或发现未归属 product/test/package/doc path，结果是失败，不能 broad-add 或退回脏树测试。manifest 是不自哈希的 root of trust；current status 与 execution log 只能在 content gate 后按已知结果更新并单向封存，control seal 后不得再修改仓库文件。
- U9 默认只做 offline no-deps package materialization；完整 dependency installation 只有显式 local wheelhouse 时验证。没有 wheelhouse 不授权网络，也不能把 dependency resolution 宣称为已验证。
- Textual、MCP SDK 和 YAML parser 仍是 optional dependencies；base install 与各 extra 必须在隔离环境分别证明 import/entrypoint 行为。

---

## Definition of Done

- U0-U9 targeted Red tests failed for the intended reason before Green and now pass.
- A1-A19 are fixed with automated evidence. All capability E3 product-value acceptance remains independently user-owned and pending; E3 is not a finding exemption.
- Clean Git materialization contains every product/test file and reproduces the package imports, console entrypoints and full test result.
- MCP never inherits unapproved environment, never maps a possibly-sent timeout to not-executed, never returns known completion without confirmed cleanup, and has a governed durable recovery path.
- Memory approvals are complete and revision-bound; persistence and source snapshots meet strict bounded no-follow/revision contracts.
- Scheduler reports latest authoritative terminal state after human resolution and duplicate fire.
- TUI completes all existing human actions by keyboard, survives pending restart, uses advisory events correctly and closes shared resources in order.
- SubAgent rejects providers without a provider-native hard total-deadline/termination receipt, including current HTTP adapters, remains zero-tool/one-call/same-trust-domain, and lets an `UNCONFIRMED` call-scoped receipt override child nonterminal normalization into parent recovery.
- Skill remains read-only and closes metadata/identity gaps without expanding scope.
- File tools deny private-root case variants; stale approvals remain safe nonexecuted results; provider adapters accept bounded untrusted context; known-executed errors are never flattened into success.
- `git diff --check`, Ruff, architecture, focused capability suites, full pytest and materialized-tree gates all pass with known exit codes and untruncated summaries.
- `CURRENT_CAPABILITY_STATUS.md` labels the Kernel and six capabilities according to their exact automated result, never accepted. A capability whose fault/closure/materialized-tree gates pass may be `locally-verified` even when E3 is pending；SubAgent 必须另外标明 current HTTP providers unsupported、E3-blocked。Promotion to accepted occurs only through separate user-authorized E3 records.
