---
title: TUI Displayed Decision Binding Plan
date: 2026-09-08
status: frozen
---

# 010 TUI displayed decision binding

## Outcome

TUI 中的用户手势只解析为用户刚刚看到的 authoritative snapshot 所绑定的 typed
action。若 checkpoint 已由另一 caller 从 A 推进到 B，TUI 可以把 A-bound action
提交给既有 `TuiAdapter.execute_once()`，但不得把同一次手势重新绑定成未展示的 B。
Kernel 仍以执行时加载的最新 checkpoint、revision、request ID 与 binding digest
裁决 stale action。

## Evidence

- 本地只读复现确认：`agent/tui/app.py::_refresh()` 展示 snapshot 后不保留它，
  `_permitted_state()` 和 artifact command path 会再次 `store.load()`。
- Oracle Web 独立审计 `first-agent-r11-010-cli-tui-a7c9`（第 5/5 档）确认该路径可把
  对 approval A 的按键构造成 approval B；普通 revision conflict 无法补救已经发生的
  UI rebinding。
- 现有 CLI 在 render/input/dispatch 周期内使用同一 snapshot；本轮不修改 CLI。

## Frozen acceptance contract

1. `_refresh()` 成功展示的 state/projection 是下一次 idle 用户手势的唯一解析上下文。
2. A 已展示而 store 变成 B 时，approve/reject/recovery/public-observation/provider
   disclosure 与普通 idle action 都只能构造 A-bound action；不得重新构造、自动重试或
   静默同意 B。
3. `/approve-artifact` 的 request、binding、path requirement 与 preview-cap 判定来自
   同一个 displayed snapshot；B 必须先被展示，才可接受一次新的明确输入。
4. `TuiAdapter.execute_once()` 仍在执行时加载最新 snapshot；真实 Kernel 必须拒绝 stale
   A，保持 B 不变，且不增加 provider/tool effect。
5. worker active、closing、shutdown-blocked、single-flight、read-only startup/reopen、
   advisory events 与 literal safe display 行为不变。

## Non-goals

- 不在本轮实现 browser takeover TUI；它是已确认的后续 CLI/TUI 独立切片。
- 不在本轮修复 retained terminal Goal 的空 action/input 问题。
- 不修改 reducer、Runtime、checkpoint、Provider、ToolRuntime 或 browser 模块。
- 不增加 controller/command framework、第二套状态机、自动 retry 或新 worker。
- 不按行数拆分 `agent/tui/app.py`；当前问题是观察绑定，不是文件大小。

## Smallest change set

- `agent/tui/app.py`
- `tests/tui/test_app.py`
- `docs/architecture/capabilities/TUI_DESIGN.md`
- `docs/architecture/CURRENT_CAPABILITY_STATUS.md`

若实现要求修改 Runtime/reducer/browser 或新增基础设施，停止并重新审查范围。

## Sequential TDD

1. Red：Pilot 展示 approval A、store 替换为 B、按 `a`；派发 action 必须仍绑定 A。
2. Green：App 保留最后一次成功展示的 immutable state/projection；idle gate 不再 fresh
   load 决策状态。
3. Coverage：artifact approval、reject、recovery success/failure、public-observation 与
   disclosure 分别证明不重绑；已因 shared fix 首次通过的测试记录为 regression coverage，
   不伪造 Red。
4. Integration：真实 Runtime + fake provider/tool 证明 stale A 对 B 返回 conflict、B 不变、
   provider/tool 调用数不增加；刷新 B 后必须重新明确同意。

## Verification

先运行单个新增测试，再运行 `tests/tui` 与相关 CLI/action-legality tests。代码和审查
完成后，本轮只运行一次最终门禁：

```bash
git diff --check
.venv/bin/ruff check .
.venv/bin/python -m pytest -q -rx
```

Oracle 还确认了两个独立 residual：browser takeover 缺少 TUI 投影/typed controls，
以及 retained terminal Goal 可能无 action 并禁用输入。二者不得打包进 010。
