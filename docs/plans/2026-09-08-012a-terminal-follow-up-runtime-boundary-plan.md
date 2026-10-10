---
title: Terminal Follow-up Runtime Boundary Supplement
date: 2026-09-08
status: frozen
---

# 012A terminal follow-up Runtime boundary

## Why this supplement exists

012 的真实 Runtime Red test 证明第一次 Oracle 假设不完整：`CANCELLED` 的 prose
follow-up 可运行，但 `VERIFIED_DONE` 在 `SubmitMessage` reducer 无条件清除
`completion_claim` 时违反终态不变量；同时 `ContextManager` 会给两种 terminal Goal
暴露全部 product tools。按 012 的停止条件，本补充规格在修改 reducer 前重新冻结边界，
不回写或掩盖原计划。

Oracle Web 独立补充审计
`first-agent-r13-012-terminal-runtime-boundary-e1b4`（`Pro，第 5 项，共 5 项`）确认
`PROCEED`：终态 discussion 是既有状态机支持的有用能力，但必须是保留关闭记录、零
product-tool authority 的 shared Runtime 行为，不能只是 TUI 解锁。

## Superseding acceptance contract

1. 终态 Goal 上接受普通 `SubmitMessage` 时，reducer 使用 pre-transition authoritative
   status 判定并保留既有 `completion_claim`；非终态/no-Goal 的既有 claim-clearing 行为
   不变。`CANCELLED` 不制造 claim，`VERIFIED_DONE` 不削弱严格 claim/evidence invariant。
2. follow-up 可增加普通 user/assistant facts、conversation revision、run/accounting；Goal
   object、revision、status、criteria、evidence 与原 completion claim 的值保持不变。旧 claim
   不能短路新 provider call、不能为新请求背书或产生新 completion transition。
3. `ContextManager` 对 `VERIFIED_DONE`/`CANCELLED` run 选择空 product-tool set；不能复用
   PAUSED 的 read-only set。历史 tool facts 可作为既有上下文，但不是当前执行 authority。
4. 空 advertisement 必须由现有 Runtime model-response admission fail closed：provider 即使
   返回已注册的 read-only/effectful/多条或 prose+tool call，也不能进入 tool batch、approval、
   disclosure、`EXECUTING` 或 callable invocation。优先复用既有 unadvertised-tool bounded
   rejection；只有测试证明它有缺口时才在该既有边界做最窄修复。
5. terminal model control 不能安装/修正/推进/完成旧 Goal；既有 terminal control legality
   保持权威。普通 assistant command-like prose 只是文本，不制造 human action。
6. provider failure、malformed response、bounded prohibited-call exhaustion、cancel/replay 与
   checkpoint reload 后，原 terminal Goal/claim/evidence 仍合法；不得产生 unknown tool effect。
7. 012 的 displayed-snapshot/CAS、takeover/active/closing priority、CLI/TUI shared submit 与
   truthful follow-up copy 继续适用。

## Product promise

用户可以继续讨论已完成或已取消的任务，但这个关闭的任务不会运行工具或授权后续动作。
这不承诺分类所有“语义上的新内容”，也不宣称回答做了 fresh inspection。

## Non-goals

- 不新增 action、follow-up mode、message classifier、second loop、Goal/session/bootstrap flow。
- 不修改全局 tool registry、普通 tool policy/approval，或把 terminal 解释散落到每个 tool。
- 不开放 read-only terminal tools，不用晚到的 invariant exception 代替 admission denial。
- 不改变 Memory/Skill/MCP/SubAgent/Browser/Scheduler 能力或跨重启恢复语义。

## Additional smallest change set

- `agent/runtime/state.py`
- `agent/runtime/context.py`
- `tests/tui/test_app.py`
- `tests/kernel/test_context_manager.py`
- `tests/kernel/test_runtime_turn.py` 或最接近既有 unadvertised-tool tests 的文件

若 existing unadvertised-tool path 已经在 batch/approval/effect 前拒绝，不修改
`agent/runtime/loop.py`。

## Sequential TDD

1. 已有 Red：真实 verified follow-up `FAILED_FATAL`，provider 零调用；Green：terminal-only
   claim preservation，随后两种 terminal prose follow-up 都保留完整 Goal/claim/evidence。
2. Red：ContextManager 对 terminal state 仍广告 registered tools；Green：显式 terminal
   zero-tool branch，no-Goal/PAUSED/nonterminal 行为保持原样。
3. Security Red/coverage：恶意 provider 在空 advertisement 下返回 registered read-only、
   effectful、mixed/multi calls；证明 callable/approval/disclosure/effect 都为零，并走现有
   bounded unadvertised rejection。若测试已 Green，记录为既有 gate 证据，不改 loop。
4. Real flow：两次连续 terminal prose follow-up 都实际调用 provider、持久化 assistant text，
   不重发旧 completion、不改变 terminal authority。
5. Failure/stale/reload：复用已有 CAS/owner/replay contracts，增加最小可信回归覆盖。

## Verification

完成 focused goal/context/runtime/TUI/CLI gates 和独立 Pi review 后，本轮只运行一次最终：

```bash
git diff --check
.venv/bin/ruff check .
.venv/bin/python -m pytest -q -rx
```
