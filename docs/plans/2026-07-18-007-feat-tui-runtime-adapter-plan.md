---
title: Add Textual TUI Runtime Adapter - Plan
type: feat
date: 2026-07-18
deepened: 2026-07-18
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: ce-plan-bootstrap
execution: code
---

# Add Textual TUI Runtime Adapter - Plan

## Goal Capsule

- **Objective:** 以 optional Textual UI 表达全部现有 typed actions，并在 single-flight thread worker 中调用同一个 Runtime；checkpoint/RunResult 始终权威，events 只提示。
- **Prerequisite:** Skill、MCP、Memory、SubAgent、Scheduler 合同与 architecture tests 稳定。
- **Execution:** 5 个串行、Red-first 单元；先共享 action builder，再实现 UI adapter/rendering。
- **Product gate:** 开始前由用户批准一个与 CLI 对照的 submit → approval/recovery → terminal reference journey；完成后以 action/state/result parity 和键盘/restart evidence 决定是否保留 TUI。
- **Stop conditions:** TUI 直接执行工具/写 checkpoint、复制状态机、UI-only mutation、event 成为权威、声称 token streaming/in-flight cancellation、后台多 run 或 base import 强依赖 Textual 时停止。
- **Out of scope:** streaming、multi-conversation dashboard、background runs、resource/media、capability management、scheduler/Memory/Skill editors 和 remote UI。

## Product Contract

### Requirements

- R1. optional extra 固定 `textual>=8.2,<9`；base install、headless、普通 CLI 不导入 Textual。未安装时 TUI command 给出明确安装提示。
- R2. Runtime reducer 是唯一 action-legality 权威；CLI 与 TUI 共享一个 pure typed-action builder 只负责按 authoritative state 构造 `SubmitMessage`、`ResolveApproval`、`ResolveUnknownToolOutcome`、`Resume`、`CancelRun`，不能另造 legality/state machine。reducer 必须对 durable `RUNNABLE/EXECUTING` 的 `CancelRun` 返回 unchanged conflict，只允许 `Resume` 进入 recovery；`AWAITING_RECOVERY` 随后只接受 exact resolution，Resume/Cancel 仍 unchanged。
- R3. 每个 action 从 authoritative state 取得 conversation ID、next seq、revision；pending resolution 携带 exact request ID/binding digest。
- R4. 同 conversation 同时最多一个 worker。Textual-free adapter 提供同步 `execute_once()`、single-flight gate/event queue，但不创建 thread；唯一 production thread owner 是 Textual worker，它只调用一次 adapter execution。App startup/reopen 另有一次 authoritative load，只读构建初始 view，不提交 action或调用 provider/tool。
- R5. runtime event callback 只把 immutable event 放入 thread-safe queue，再用 Textual message/UI-thread API 渲染；禁止同步重入 Runtime。
- R6. `RunResult` 与 checkpoint 是状态/final message 权威；events 可重复、丢失、乱序且只能作 advisory display。startup/reopen 的 terminal message 来自 `state.last_safe_result.message`，pending form 来自最新 `RunResult.state` 或重新加载的 `state.active_run.pending_request`；同一 final message 只显示一次。
- R7. worker active 时禁用所有 action controls。Textual thread cancel 不能杀死执行线程，因此 v1 不提供 in-flight cancel；正常交互中的 `CancelRun` 只对 Runtime 已返回的 paused state 开放，另允许 R8 定义的非-`EXECUTING` durable interrupted `RUNNABLE` reopen 场景。
- R8. close/crash 不伪造 CancelRun；重启从 checkpoint 恢复。仅当本地无 worker、`active_run.status == RUNNABLE` 且 phase 是 `EXECUTING` 时，只允许新 sequence `Resume` 进入 existing recovery；其他 interrupted `RUNNABLE` 才允许 `Resume`/`CancelRun`，`AWAITING_RECOVERY` 始终开放 authoritative recovery form。不能重交原 SubmitMessage，in-memory 模式不承诺跨进程恢复。startup/reopen 看到非空 persisted owner 只视为 stale-owner candidate，不是 live lease 证明；只有 Runtime 对一次实际 action 返回 `conversation_busy` 后才禁用 action 并要求 reload，reload 后重新投影而不缓存 busy。
- R9. UI 显示 bounded request preview/risk/effect/error/result，不展示 raw checkpoint、credential、binding body、绝对私有 path、Memory inventory、Skill root 或 MCP env。所有外部可控文本统一 literal rendering：`markup=False`、不解析 link，ANSI/C0/C1/bidi controls 以可见 escape 表示；approval 仍绑定原始 canonical 内容，escape 后完整 preview 超限则 effect 前拒绝而不是截断。
- R10. retained rows/text 有 UI cap；events 明确标注 advisory progress，不宣传 token streaming。
- R11. 新 package 使用 `agent/tui/`；旧 input backend/textual bridge、display/runtime callbacks 不恢复。
- R12. Scheduler handoff 入口显式接收 state root、relative checkpoint reference 与 workspace，按 durable-state 安全规则只读加载同一 conversation；不扫描 root、猜 cwd 或展示其他 checkpoint。
- R13. active worker close 只进入 visible `closing_requested`：停止新 action、声明 effect 未取消、等待 bounded worker；result 返回后才 close resources。deadline 违反时显示 `shutdown_blocked` 且不提前 teardown，不提供伪安全 force-exit action。

验收场景：CLI/TUI 同 state 生成相等 action；worker single-flight；重复/乱序/缺失 event 不改变按钮；approval/recovery/resume/cancel parity；active worker 无 cancel；close/restart 可重建 pending；base env 无 Textual 仍可 import/run CLI。

## Planning Contract

- KTD1. **Action parity before widgets.** 首先抽出纯 action builder，UI 只绑定 intent，不复制 CLI command semantics。
- KTD2. **RunResult/checkpoint authoritative.** events 是 best-effort，不能驱动批准按钮或 revision。
- KTD3. **Single-flight synchronous bridge.** 使用 Textual thread worker，不改变非流式 Kernel。
- KTD4. **No false cancellation.** 不能终止 thread 就不展示 in-flight cancel；关闭 app 也不等于 Runtime action。
- KTD5. **TUI is an adapter, not another Agent** `(session-settled: user-approved — chosen over continuing feature-entangled legacy architecture: the user accepted cutting old implementations and rebuilding through stable boundaries.)`。

目标结构：

```text
agent/tui/{__init__.py,adapter.py,render.py,app.py}
tests/tui/{test_actions.py,test_adapter.py,test_app.py,test_optional_dependency.py}
```

## System-Wide Impact

- TUI 复用 shared composition 的 Runtime/store/close stack；它不重新组装 provider/tools/sources，也不拥有 capability lifecycle。
- 唯一 production worker thread 属于 Textual U4；adapter U2 是可独立测试的同步 boundary，避免 double-thread ownership。
- App close 先停止接受 action；bounded worker 返回后才关闭 MCP bridge 等 shared resources。进程提前退出时 checkpoint/Resume/recovery 仍是唯一事实来源。

## Implementation Units

### U1 — Lock shared action legality and extract typed-action builder

- **Modify:** `agent/cli/app.py`; add a small leaf module under `agent/cli/` only if needed; update CLI tests and extend the Order-0 Kernel legality regression test without changing reducer semantics.
- **Add:** `tests/tui/test_actions.py` without importing Textual.
- **Red:** durable `RUNNABLE/EXECUTING` checkpoint 经 CLI/headless/TUI 构造的 Cancel 都由 reducer 返回 unchanged conflict，Resume 产生同一 recovery request 且 provider/tool count 为零；`AWAITING_RECOVERY` 的 Resume/Cancel 也 unchanged，只有 exact mark succeeded/failed 推进；CLI command and equivalent TUI intent produce equal action/digest across ready, approval, recovery, retry/limit pause and invalid states; exact ID binding; no UI-only action.
- **Green:** preserve the already-locked shared reducer legality；pure builder functions accept intent + `ConversationState` + run ID factory，CLI parser remains a thin text adapter.
- **Verify:** existing CLI messages/exit behavior do not regress.

### U2 — Add Textual-free single-flight adapter

- **Add:** `agent/tui/adapter.py`, `tests/tui/test_adapter.py`.
- **Red:** startup/reopen authoritative load 不调用 Runtime/provider/tool；adapter 自己不创建 thread；one active call gate; exact execute store.load + run_turn count; immutable queued events; duplicate IDs; result-before-controls authority; worker exception 后只读 reload safe projection；只有 local-worker-absent + RUNNABLE/EXECUTING 是 Resume-only，其他 RUNNABLE 才有 Resume/Cancel，AWAITING_RECOVERY 始终显示 resolution form；foreign persisted owner 不永久禁用 recovery，实际 `conversation_busy` 才进入 reload-only，reload 后重新投影；以上场景都不 replay Submit；no action retry/re-entry.
- **Green:** small controller/queue types with injected Runtime/store/dispatcher，提供 read-only initial/reopen state load；no Textual import and no business decision.
- **Verify:** adapter state/gate tests；仅测试并发拒绝时可用 barrier 驱动调用方线程，production adapter 不拥有它们；复用 existing event sink contract。

### U3 — Implement bounded rendering and pending-state projection

- **Add:** `agent/tui/render.py`; extend adapter/render tests.
- **Red:** table-drive all `ActiveRunStatus`/`RunStatus`, terminal reopen from `last_safe_result.message`, stale persisted owner versus actual `conversation_busy`, delivery warnings, worker exception/revision/checkpoint conflict；approval/recovery forms from authoritative state loaded from `RunResult.state` or `store.load()`; Rich markup/link、ANSI/ESC、C0/C1 与 bidi override 逐字可见且不被解释，safe-display expansion 超限时 approval 不可提交，action 仍绑定原始 canonical 参数；stale event ignored for actions; bounded retained rows/text; private fields omitted; final assistant message appears once；每格断言 main text、form、actions、reload 与 focus target。
- **Green:** one pure authoritative view-model/projection matrix and one literal safe-display projection shared by startup, reload, worker result and widgets.
- **Verify:** snapshot-style structured assertions, not terminal escape-code goldens.

### U4 — Build optional Textual app and Pilot flows

- **Add:** `agent/tui/app.py`, `agent/tui/__init__.py`, `tests/tui/test_app.py`, `tests/tui/test_optional_dependency.py`.
- **Modify:** `pyproject.toml`, `agent/composition.py`, `main.py`, `README.md`.
- **Red:** optional import behavior; Textual 是唯一 worker owner；input submit; active controls disabled; advisory event display; completed/pending/error states; approval/reject/recovery/resume/paused cancel; active cancel absent；approval/recovery/RUNNABLE checkpoint 直接启动，provider/tool count 为零；Scheduler state-root/relative-ref/workspace handoff 不扫描其他 state；active close 显示 no-cancel/closing、worker result 后才 teardown、deadline violation 显示 blocked；widgets 对伪造 label/link markup、ESC 与 bidi override 使用 `markup=False` 和可见 escape；所有 action 纯键盘可达，pending form 获焦、固定可见 Tab order、文字标签不靠颜色、Enter 不默认 approve/mark-success。
- **Green:** minimal one-conversation App using thread worker and `post_message`/`call_from_thread`; no dashboard or background manager.
- **Verify:** Textual `App.run_test()`/`Pilot` only, FakeProvider/temp checkpoint, no browser/network.

### U5 — Lock architecture and parity

- **Modify:** `tests/architecture/test_cutover_absence.py`, dependency/owner tests, docs.
- **Red:** TUI cannot import provider/tool/checkpoint concrete mutation APIs, call `compare_and_swap`, add action types, claim streaming, or restore old textual/input backend paths.
- **Green:** exact allowlist and adapter documentation.
- **Verify:** full gates below including base install simulation without Textual.

## Verification Contract

Feature-test venv 先从当前 worktree 安装 `.[dev,skill,mcp,tui]`。Textual/其他 optional-dependency absence 另用只安装 `.[dev]` 的 clean temp venv/subprocess 验证；不得因主 venv 已安装 Textual 而跳过 base-import proof。

```bash
.venv/bin/python -m pytest -q tests/tui tests/cli tests/kernel/test_event_ordering.py tests/kernel/test_action_legality.py
.venv/bin/python -m pytest -q tests/architecture
git diff --check
.venv/bin/ruff check .
.venv/bin/python -m pytest -q -rx
```

Run the optional-dependency tests both with Textual installed and in a subprocess/import environment where it is unavailable. Pilot tests must not contact real providers or private workspace data.

## Definition of Done

- TUI expresses every existing human action with CLI-equivalent typed data and no UI-only mutation.
- Runtime runs single-flight; events remain advisory; result/checkpoint rebuild every actionable state.
- No false streaming or in-flight cancellation promise exists, and close/restart behavior is fail-closed.
- Base installation remains usable without Textual; optional Pilot suite passes when installed.
- Old TUI/input backend architecture remains absent and all quality gates pass.
- 用户批准的 TUI reference journey 与 CLI action digest、checkpoint 和 terminal result 等价，并能纯键盘完成；没有 evidence 不宣称 TUI 重接成功。
