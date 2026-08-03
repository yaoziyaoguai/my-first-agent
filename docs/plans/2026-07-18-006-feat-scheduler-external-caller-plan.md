---
title: Add Scheduler External Caller - Plan
type: feat
date: 2026-07-18
deepened: 2026-07-18
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: ce-plan-bootstrap
execution: code
---

# Add Scheduler External Caller - Plan

## Goal Capsule

- **Objective:** 提供一个无内置时钟的 occurrence adapter，让 cron/launchd/CI 把一次外部触发确定性地映射为独立 conversation、首次 typed action 与 machine-readable report。
- **Prerequisite:** 前五个计划的 Definition of Done 全部满足；Runtime replay/checkpoint 行为保持现状。
- **Execution:** 4 个串行、Red-first 单元。
- **Product gate:** 开始前由用户批准一个 benign occurrence 与 human-resolution reference task；完成后提交 duplicate count、handoff 与 terminal report evidence，再由用户决定是否授权 TUI。
- **Stop conditions:** 引入 timer/cron parser/daemon/queue、共享 scheduler cursor、自动 approve/recovery/Resume、直接 provider/tool/CAS 调用或第二个 loop 时停止。
- **Out of scope:** schedule CRUD、timezone/DST、recurrence、misfire、worker pool、backoff、notification 和管理 UI。

## Product Contract

### Requirements

- R1. `ScheduledOccurrence` 严格包含 bounded schedule ID、stable occurrence ID、canonical UTC scheduled time、message 与显式 state-root/workspace scope；不从 current time/cwd 猜 identity。
- R2. checkpoint filename **只**从 `schedule_id + occurrence_id` 确定性派生，保证冲突请求命中同一 state；conversation ID、run ID 与首次 action digest 都绑定完整 occurrence identity（schedule/occurrence ID、scheduled time、message digest、workspace scope）。因此 revision 0 上的 drift 也会立即发生 conversation identity conflict。原始 ID 不直接成为路径。
- R3. 每个 occurrence 使用一个新 conversation 和独立 checkpoint；多次 fire 不追加到共享 conversation。
- R4. 首次 state 固定 revision 0、next action seq 1；scheduler-local concrete create-or-load helper 只封装 path derivation、排他 `LocalCheckpointStore.initialize` 与 load，不新增单实现 factory port，也不暴露/调用 `compare_and_swap`。
- R5. entrypoint 必须先 create/load occurrence store，再把该 store 注入 shared composition builder，最后把同一 store 绑定的 Runtime 与 snapshot 交给 caller；禁止切换已构造 Runtime 的 store或构造第二套 Runtime path。首次提交固定 `SubmitMessage(action_seq=1, expected_revision=0)`；retained duplicate 依赖 replay-before-revision，provider/tool effect 不重复。
- R6. 并发 create loser 若因 stale initial snapshot 收到 `CONFLICT`，最多 reload 一次并重交**完全相同**的 seq 1 action；不得改变 digest/run/message、循环重试或提交新 sequence。
- R7. 相同 occurrence identity 携带不同 message/scheduled time/workspace scope 时必须命中原 checkpoint并发生 identity conflict。seq 1 replay 过期后，只有 authoritative `active_run.run_id`/`last_safe_result.run_id` 与本次 deterministic run ID 精确匹配才可作为 safe duplicate fallback；不匹配一律 conflict。绝不创建旁路文件、覆盖 checkpoint或启动新 run。
- R8. adapter 唯一 production execution call 是 `AgentRuntime.run_turn`；不能直接调用 provider、ToolRuntime、checkpoint mutation 或解释 active cursor。
- R9. report 携带 authoritative occurrence status、initial-action replayed/error、relative checkpoint reference 和安全 pending 摘要。active run 决定 paused 状态；没有 active run 时使用与 deterministic run ID 匹配的 `last_safe_result`。approval/recovery/limit/retryable 一律标 `needs_human`，不自动推进。
- R10. command 输出 bounded machine-readable JSON；exit class 只有 completed / needs-human / fatal-conflict，不泄露 checkpoint、credential 或完整 request binding。
- R11. 新 package 使用 `agent/scheduler/`；旧 action scheduler、scheduled registry、task orchestration/DAG 不恢复。

验收场景：首次 fire 执行；exact duplicate replay；并发 fire provider/effect count 一；同 ID 不同 message conflict；暂停/limit/retryable 只报告人类处理；CLI/TUI 用后续 action 完成人工 resolution 后 duplicate fire 报告当前 terminal state；不同 occurrence 隔离；malformed identity/path fail closed。

## Planning Contract

- KTD1. **Scheduler is an External caller, not a scheduling engine.** 时间计算和 recurrence durability 由外部系统负责。
- KTD2. **One occurrence, one conversation.** 避免多次 fire 与 paused run/replay sequence 争用同一状态。
- KTD3. **Deterministic run identity is durable; replay is the fast path.** 不新增 scheduler effect ledger；优先复用 Kernel action replay，replay window 过期后只用 current state 中匹配的 deterministic run ID 证明 duplicate。
- KTD4. **One bounded replay reconciliation only.** 仅解决 initial create/load race，不是业务 retry loop。
- KTD5. **Human authority never automated** `(session-settled: user-approved — chosen over continuing feature-entangled legacy architecture: the user accepted cutting old implementations and rebuilding through stable boundaries.)`。

目标结构：

```text
agent/scheduler/{__init__.py,contracts.py,caller.py}
tests/scheduler/{test_contracts.py,test_caller.py,test_cli.py}
```

## System-Wide Impact

- Scheduler entrypoint 先选择独立 occurrence store，再将它注入 shared composition 创建唯一 Runtime；caller 不创建/切换 Runtime，也不创建常驻资源或 teardown lifecycle。
- 新 checkpoint 的排他 bootstrap 与 CLI create-only 模式一致；创建后 mutation ownership 立即回到 Runtime。
- Report 的 relative state reference 是给 CLI/TUI 的 human-resolution handoff；它不授予 Scheduler 自动推进 pending state 的权力。

## Implementation Units

### U1 — Define canonical occurrence/report contracts

- **Add:** `agent/scheduler/contracts.py`, `tests/scheduler/test_contracts.py`.
- **Red:** strict IDs/time/message limits, canonical UTC requirement；checkpoint relative path 只由 schedule+occurrence 决定；scheduled/message/scope 改变 conversation/run/action identity，但 same occurrence drift 仍命中同一 relative state ref；revision-0 drift 在 run_turn 前 conflict；JSON serialization bounds and no absolute path/credential fields.
- **Green:** immutable request/report types, digest helpers and explicit status-to-exit-class mapping.
- **Verify:** property-style edge cases for Unicode, separators, overlong input and timezone offsets.

### U2 — Implement atomic create/load and exact action replay

- **Add:** `agent/scheduler/caller.py`, `tests/scheduler/test_caller.py`，包含 concrete create-or-load helper 与只接收 pre-bound Runtime/snapshot 的 caller。
- **Red:** first initialize; existing load; helper 返回 store/snapshot identity；Runtime 绑定另一个 store 时 fail closed；duplicate replay; barrier-controlled concurrent first fire; one bounded stale-snapshot reconciliation；same ID/different message/time/scope 命中原文件并 conflict；seq 1 超过 64-record window 后 exact run ID 仍只报告 current state、drifted run ID conflict；second conflict no loop; paused statuses no follow-up action；pause → seq 2+ human resolution → duplicate seq 1 报告 current terminal state；provider/tool counters exact。
- **Green:** concrete create/load helper, pre-bound Runtime caller, deterministic `SubmitMessage`, at most one exact reload/replay reconciliation，以及基于 authoritative active/last run ID 的 safe report projection。
- **Verify:** no direct provider/ToolRuntime/`compare_and_swap` import or invocation.

### U3 — Add explicit headless command

- **Modify:** `agent/composition.py`, `main.py`, `pyproject.toml` only if a separate console entry is justified, `README.md`; add `tests/scheduler/test_cli.py`.
- **Red:** strict occurrence JSON/arguments; explicit state root/workspace; create/load store happens before composition；composition receives exact returned store；stdout is one stable JSON report; exit classes; malformed/overlap path no mutation; ordinary REPL behavior unchanged.
- **Green:** thin parser adapter runs concrete create/load → shared composition(store=...) → `ScheduledOccurrenceCaller` once.
- **Verify:** subprocess tests with FakeProvider and temp state root; no real cron or network.

### U4 — Lock architecture and absence

- **Modify:** `tests/architecture/test_cutover_absence.py`, `tests/architecture/test_dependency_dag.py`, `docs/architecture/EXTENSION_CONTRACTS.md` and README as needed.
- **Red:** scheduler package cannot import provider/tool implementation, run background threads, parse cron or call checkpoint `compare_and_swap`; only explicit new-store initialize/load factory is allowed；old scheduler/task packages remain absent。
- **Green:** exact package allowlist and external-caller docs.
- **Verify:** full gates below.

## Verification Contract

Feature-test venv 先从当前 worktree 安装 `.[dev,skill,mcp]`；Scheduler v1 没有新的第三方 runtime extra。base-install absence 使用独立 clean temp venv/subprocess。

```bash
.venv/bin/python -m pytest -q tests/scheduler tests/kernel/test_action_legality.py tests/kernel/test_runtime_turn.py
.venv/bin/python -m pytest -q tests/architecture tests/cli
git diff --check
.venv/bin/ruff check .
.venv/bin/python -m pytest -q -rx
```

Concurrency tests must use a barrier and assert exactly one provider/effect call. No test may call a real scheduler, provider, MCP server or private state root.

## Definition of Done

- External occurrence can create/load and submit exactly one deterministic Kernel action.
- Duplicate and concurrent fire converge through replay or the deterministic-run-ID expiry fallback without duplicate provider/tool effects.
- Every non-completed status is reported honestly; no automatic human decision or resume exists.
- No timer, daemon, queue, scheduler state machine or second runtime loop was introduced.
- 用户批准的 Scheduler reference task 从外部 fire 到人工 resolution 可完整走通，且 duplicate provider/effect count 不增加；没有 evidence 不自动进入 TUI。
- Architecture, CLI, concurrency and full quality gates pass.
