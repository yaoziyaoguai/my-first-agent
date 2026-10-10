---
title: TUI Browser Takeover Controls Plan
date: 2026-09-08
status: frozen
---

# 011 TUI browser takeover controls

## Outcome

tracked Textual TUI 对 authoritative `browser_takeover_pending` 显示一个明确、可完成的
人工接管流程：用户可以按 `b` 请求 Browser done，或按 `c` 请求 Browser cancel。
两者只构造与最后一次成功展示的 immutable snapshot 精确绑定的 typed action；实际
合法性、浏览器 session/lease 校验与 durable mutation 仍只由
`AgentRuntime.run_turn` 及既有 browser completion owner 负责。

## Evidence

- 本地只读检查确认 `agent.tui.render.project()` 完全忽略 takeover pending；TUI 的
  `c` 当前可能解释为 `CancelGoal`、`CancelRun` 或 cooperative cancel，且没有
  `CompleteBrowserTakeover` 路径。
- 既有真实 Runtime 测试证明 takeover pending 可以和 active run 同时存在；完成后由
  原 Kernel loop 继续，不需要 TUI 额外发送 Resume。
- Oracle Web 独立审计
  `first-agent-r12-011-tui-browser-takeover-b4d1`（第 5/5 档）确认这是 P1 的现有工作流
  闭环缺陷，并建议 state-only UI：不增加 session liveness seam；重启或原窗口丢失时
  明确引导 cancel。

## Frozen acceptance contract

1. lifecycle closing/blocked/worker-active 仍阻止新 typed action；显示 takeover snapshot
   时 cooperative cancel/pause/correction 不能绕过该 gate。
2. takeover pending 与 `AWAITING_RECOVERY` 同时存在时，保留既有精确 recovery form；
   pending 与 `EXECUTING` 同时存在时只允许 Resume 进入 Kernel recovery。除此之外，
   takeover form 必须优先于 ready、terminal、Goal、approval/disclosure 与普通 run controls。
3. ordinary takeover form 固定为 `form_kind="browser_takeover"`、
   `focus="browser_takeover"`、actions 恰为 `("browser_done", "browser_cancel")`、
   `terminal_message=None`。展示 request/session/profile/profile revision，以及重启或原窗口
   不可用时 cancel 的说明；不宣称 session 存活、登录成功或站点状态。
4. `b` 与 `c` 分别通过 shared pure builder 构造
   `CompleteBrowserTakeover` / `CancelBrowserTakeover`；CLI 三条既有命令复用 builders，
   grammar 与错误行为不变。
5. action 的 conversation/action-seq/revision/request/session/profile revision 全部来自
   Round 010 的 displayed snapshot。A 已展示、checkpoint 变为 B 时，只能提交 A-bound
   action；Kernel 对 fresh snapshot 裁决，TUI 不重绑、不自动 retry。
6. startup/reopen 只投影 checkpoint，不执行 Runtime/browser/provider/tool。live completion
   由既有 owner 验证并继续原 run；restart completion failure 保留 pending，TUI 显示
   bounded failure 与 cancel guidance；cancel 只取消 takeover，不伪称回滚网页副作用。
7. result/event 只能补充反馈，不能用 `COMPLETED` headline 覆盖仍然存在的 takeover form，
   也不能触发第二次 Resume 或其它 action。
8. safe display 继续 literal；takeover form 超过 cap 时 Browser done fail closed，仍保留
   exact snapshot-bound Browser cancel。

## Non-goals

- 不新增 browser session/liveness/status seam、重连、自动 reopen、自动 done/cancel/retry。
- 不修改 Runtime、reducer、browser owner、state/checkpoint schema 或 composition root。
- 不加入 TUI slash-command 系统、第二个 confirmation modal 或通用 command registry。
- 不处理 retained terminal Goal 的空 action/input residual，也不处理 009 的 browser
  `begin_browser_takeover`→`mark_executing` crash window。
- 不按 LOC 拆文件，不创建浏览器 dashboard，不读取真实 profile、凭据或网页状态。

## Smallest change set

- `agent/cli/actions.py`
- `agent/cli/app.py`
- `agent/tui/render.py`
- `agent/tui/app.py`
- `tests/tui/test_render.py`
- `tests/tui/test_app.py`
- `tests/cli/test_commands.py`
- `docs/architecture/capabilities/TUI_DESIGN.md`
- `docs/architecture/CURRENT_CAPABILITY_STATUS.md`

若实现要求修改 Runtime/reducer/browser/state contract，停止并重新审查范围。

## Sequential TDD

1. Red：普通 pending 覆盖 ready/terminal/Goal/run 投影；Green：增加 authoritative
   takeover form 与字段。
2. Red：真实 pending + `COMPLETED` RunResult 仍显示 waiting form；Green：result feedback
   不覆盖 authoritative pending headline，input/Enter 禁用。
3. Red：CLI/TUI 的 `b` 产生逐字段一致的 Complete action；Green：shared builder + handler。
4. Red：active/no-active pending 的 `c` 都只产生 CancelBrowserTakeover；Green：shared
   builder + takeover-first routing。
5. Red：recovery/EXECUTING 与 worker-active 时 takeover buttons、cooperative control/input
   不能绕过 barrier；Green：最窄 projection/handler gate。
6. Red：显示 A、持久化 B 后按 `b`/`c`；真实 Runtime 拒绝 stale A，B 不变且零
   completion/provider/tool effect；Green 应复用 010 binding，不另建状态。
7. Integration：既有实际 browser owner + deterministic fake 证明同进程 complete；fresh
   owner 证明 restart failure 保留 pending，随后一次新的 `c` 清除 pending，无自动 retry。
8. Coverage：literal display、overflow、event loss/duplicate/reordering 不改变 action authority；
   未因单独改动而失败的新增测试只记为 regression coverage，不伪造 Red。

## Verification

先逐个新测试建立 Red/Green，再运行 touched-area TUI/CLI/takeover tests。实现与独立 Pi
审查完成后，本轮只运行一次最终门禁：

```bash
git diff --check
.venv/bin/ruff check .
.venv/bin/python -m pytest -q -rx
```
