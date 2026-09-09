---
title: TUI Terminal Goal Follow-up Plan
date: 2026-09-08
status: frozen
---

# 012 TUI terminal Goal follow-up

## Outcome

当 durable Goal 已是 `VERIFIED_DONE` 或 `CANCELLED`、没有 active run 且没有
`browser_takeover_pending` 时，tracked Textual TUI 恢复既有普通 `SubmitMessage`
路径，让用户可以在同一应用会话里追问结果。终态 Goal 的 identity、revision、status、
criteria 与 evidence 保持不变；追问不是新任务、不会恢复或替换旧 Goal。

## Evidence

- 本地只读检查确认 `_goal_actions()` 对两种终态都返回空 tuple；TUI 因此显示
  `no actions`、禁用 input，且 Enter handler 的 projection gate 也拒绝 dispatch。
- 普通 CLI 会把终态下的非命令文本翻译为既有 `SubmitMessage`；Kernel admission/reducer
  允许它成为普通 follow-up run，但不会把它标记为 goal correction，也不能安装第二个
  Goal。
- `open_workspace_session()` 有意排除 terminal history，并在没有其它 active candidate 且
  容量允许时新建 conversation；这说明重启是新会话路径，但不是同一 TUI 会话追问的
  合理替代。
- Oracle Web 独立审计
  `first-agent-r13-012-tui-terminal-goal-c6f2`（`Pro，第 5 项，共 5 项`）返回
  `PROCEED`：终态 Goal 边界合理，整段 live conversation 被锁死不合理；只应恢复已经
  存在的 follow-up 能力，不应扩展为新 Goal/session 功能。

## Frozen acceptance contract

1. 只有 `goal.status in {VERIFIED_DONE, CANCELLED}`、`active_run is None`、
   `browser_takeover_pending is None` 时，shared `GoalView.legal_actions` 才恰好暴露
   `("submit",)`；不暴露 pause/resume/correct/cancel Goal actions。
2. TUI 必须从同一 shared projection 获得 `submit`，启用 input 并聚焦；不得加入
   terminal-specific handler、第二套 permission table 或直接 Runtime 调用。
3. UI 明确说明这是 follow-up，不会开始新任务；`VERIFIED_DONE` 与 `CANCELLED` 的文案
   不得混淆。提示必须位于不会被非空 `RunResult.message` 覆盖的 action-hint/input 面。
4. Enter 仍从 Round 010 的 displayed immutable snapshot 构造既有 `SubmitMessage`。
   显示 A、checkpoint 变成 B 后，action 保留 A 的 conversation/action-seq/revision；
   Kernel 必须拒绝 stale action，零 provider/tool effect，TUI 不重绑、不自动重试。
5. 真实 Runtime follow-up 完成后，Goal identity、revision、status、criteria、evidence 与
   completion history 保持原值；第二次 follow-up 仍可用。终态文本不得被解释为
   goal correction、Goal resume 或新 Goal proposal authority。
6. authoritative state 优先：仅有 completed `RunResult`/event 不得解锁非终态或不兼容
   checkpoint；没有 result/event 的 terminal checkpoint 仍应解锁 follow-up。
7. pending browser takeover、approval/disclosure/recovery、`EXECUTING`、active worker、
   closing 与 shutdown-blocked 的现有优先级和 gate 不变。
8. CLI 保留既有终态 follow-up 行为，并与 TUI 产生同类、逐字段绑定的
   `SubmitMessage`；startup/session selector、history capacity 与 checkpoint schema 不变。

## Non-goals

- 不新增 `/new`、live session switch、自动重启、自动创建 conversation 或第二个 Goal。
- 不替换、删除、恢复、修正或重开 terminal Goal；不修改 Goal terminal invariants。
- 不修改 Runtime model/tool loop、provider/tool policy、state/checkpoint schema、session
  bootstrap 或 selection。
- 不承诺 post-terminal follow-up 的跨重启恢复；该恢复分类是独立产品/架构问题。
- 不处理 TUI `/leases`/worker-error heading、`/revoke` input bypass、dead helper 或 browser
  takeover crash window。

## Smallest change set

- `agent/runtime/views.py`
- `agent/tui/app.py`
- `tests/continuity/test_views.py`
- `tests/tui/test_render.py`
- `tests/tui/test_app.py`
- `tests/cli/test_commands.py`
- `docs/architecture/capabilities/TUI_DESIGN.md`
- `docs/architecture/CURRENT_CAPABILITY_STATUS.md`

若实现要求修改 Runtime/reducer/contracts/session bootstrap，停止并重新审查范围。

## Sequential TDD

1. Red：两种 terminal Goal 的 shared/TUI projection 应暴露 submit、input focus，且 pending
   takeover 仍只显示 takeover controls；Green：在 `_goal_actions()` 加最窄显式条件。
2. Red：mounted terminal checkpoint 的 input 启用，提示在非空 result message 后仍准确；
   Green：复用现有 hints/placeholder 渲染，不新增执行分支。
3. Red：CLI/TUI 对 terminal displayed snapshot 构造逐字段一致的 existing
   `SubmitMessage`；Green：只复用现有 builder/handler。
4. Integration：真实 Runtime 对 `VERIFIED_DONE`/`CANCELLED` 执行 deterministic prose
   follow-up，证明 Goal 全部 durable terminal 字段不变、可再次追问、零新 Goal。
5. Stale：显示 terminal A、持久化 B 后 Enter；真实 Kernel conflict，B 不变且 provider/tool
   零调用；Green 不得 fresh-rebind 或自动 retry。
6. Barrier coverage：active/pending/closing/result/event 的现有权威优先级不回归。已被最窄
   shared 条件天然满足的新增测试只记 regression coverage，不伪造 Red。

## Verification

逐个新测试建立 Red/Green，再运行 touched-area goal-view/TUI/CLI tests。实现与独立 Pi
审查完成后，本轮只运行一次最终门禁：

```bash
git diff --check
.venv/bin/ruff check .
.venv/bin/python -m pytest -q -rx
```
