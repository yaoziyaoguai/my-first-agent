# TUI Visual Shell Slice B — Wire Existing Safe Data

**创建日期**: 2026-06-02
**状态**: PLAN READY — not yet implemented
**依赖**: `docs/design/first-agent-tui-visual-target-v1.md` §4 Data Source Policy
**上游**: Slice A IMPLEMENTED (`088e05b`)

---

## 1. Purpose

将现有 safe data（RuntimeDecisionFrame summary、MCP local smoke status、skill selection evidence summary、checkpoint/memory read-only summary、pending actions）接入 Slice A 的 6-zone 视觉外壳。

不引入新 runtime、不新增真实 API 调用、不激活 default entry。

---

## 2. Non-Goals

- 不调真实 provider (core.chat())
- 不启动真实 MCP server
- 不激活 TUI default entry
- 不声称 product-ready
- 不写 checkpoint/memory/event
- 不恢复 Dashboard / AutoRun / Project Operations
- 不绕过 ToolRuntimeMediator
- 不做 Slice C/D/E

---

## 3. Allowed Data Sources

仅允许以下数据源（safe in-memory / fixture-backed）：

| 数据源 | 用途 | Lens |
|--------|------|------|
| RuntimeDecisionFrame summary (branch point status) | Runner/Inspector 状态 | Runtime/Developer |
| MCP local smoke status | MCP 面板 | MCP/Developer |
| Skill selection evidence summary | 状态展示 | Agent/Developer |
| Checkpoint/memory read-only summary | Memory/CKPT 面板 | Developer/Evidence |
| Pending actions | PendingActionBlock | Agent (default) |
| Selected lens/session/run/instance state | LeftRail selection | 全局 |
| Docs-derived data (PROJECT_STATUS, PROGRESS_LEDGER) | Evidence lens only | Evidence |

**禁止数据源**：
- 真实 provider response
- 真实 MCP server return
- 写入型 memory/checkpoint/event
- .env / config/config.yaml 内容
- raw agent_log.jsonl

---

## 4. Component Wiring Plan

| 组件 | Slice A 状态 | Slice B 变更 | 数据源 |
|------|-------------|-------------|--------|
| MainWorkArea | renders messages/toolCalls/pendingActions | + ToolResultTableBlock (DONE in pre-Slice B cleanup) | fixture |
| LeftRail | 5 sub-panels, static | 可选：selectedLens 驱动 runtime/mcp 状态变化 | fixture |
| ContextInspectorPanel | 6 sub-panels + Evidence toggle | wire real-safe summary data | RuntimeDecisionFrame, MCP bridge, skill evidence |
| BottomStatusBar | pipe-separated status | 可选：live pending count update | pending count |
| InputDock | 3-row placeholder | 不变 | — |
| TopBar | product name + chips | 不变 | — |

---

## 5. First Implementation Step (Pre-Slice B Cleanup — DONE)

ToolResultTableBlock 已接入 MainWorkArea 渲染流（pre-Slice B 最小修复）。
见 `088e05b` 之后的下一个 commit。

- `tui/src/data/visualShellTypes.ts` — 新增 `ToolResultTableData` 接口
- `tui/src/data/visualShellFixtures.ts` — 新增 `MOCK_TABLE_RESULTS`
- `tui/src/components/work-area/MainWorkArea.tsx` — import + render `ToolResultTableBlock`
- `tui/src/components/shell/TuiShell.tsx` — 传递 `tableResults`
- `tui/src/__tests__/visualShellRender.test.tsx` — 2 new tests
- Tests: 461/461 PASS, tsc clean

---

## 6. Test Plan

### Slice B 新增测试

1. **ToolResultTableBlock renders in MainWorkArea** — DONE
2. **empty tableResults handled** — DONE
3. **ContextInspectorPanel with safe data** — table renders, fake/local label visible
4. **Evidence lens not default** — regression guard
5. **LeftRail status reflects fixture data** — regression guard
6. **no provider/MCP call in render** — layout safety guard (已有)
7. **no .env/sk- leak** — safety guard (已有)
8. **Developer/Evidence data not default main screen** — lens regression guard

### 已有测试覆盖（保持不变）

- `visualShellRender.test.tsx` — 20 tests (18 + 2 new)
- `visualShellLayout.test.tsx` — 6 tests
- `visualShellMockLabeling.test.tsx` — 6 tests

---

## 7. Acceptance Criteria

- [x] Slice B plan ready (本文件)
- [x] ToolResultTableBlock wired into MainWorkArea
- [x] 461/461 TUI tests PASS
- [x] tsc clean
- [ ] ContextInspectorPanel wired with safe summary data
- [ ] LeftRail lens selection 驱动 panel 内容变化
- [ ] docs updated (PROJECT_STATUS, PROGRESS_LEDGER, handoff)
- [ ] current-stage remains closed

---

## 8. Constraints

- fake/local boundaries remain explicit — 所有 fixture 保持 `[fake/local]` 标注
- 不把 local MCP smoke 写成 production MCP
- 不把 IME 写成 fully validated
- 不激活 default entry
- 不引入新 npm 依赖
- 不修改 theme/color/border contract

---

## 9. Version History

| 日期 | 变更 |
|------|------|
| 2026-06-02 | 初始版本 — pre-Slice B cleanup (ToolResultTableBlock wiring) + full Slice B scope 定义 |
