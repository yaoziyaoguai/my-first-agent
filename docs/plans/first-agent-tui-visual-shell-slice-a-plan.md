# First Agent TUI Visual Shell — Slice A Implementation Plan

**创建日期**: 2026-06-02
**上游文档**: `docs/design/first-agent-tui-visual-target-v1.md` (Visual Target, ACCEPTED-WITH-CAVEATS)
**状态**: READY — 等待用户批准后进入实现

---

## 0. 前置审计结论

Visual Target 文档独立审计结果：**ACCEPTED-WITH-CAVEATS**。

| 审计维度 | 结论 |
|---------|------|
| 是否清楚描述目标图 | 是 — §1 逐区域描述 + §2.2 ASCII 实现合同足够 |
| 是否清楚表达 | 是 — 22 组件映射表、数据源策略、default/developer lens 分离均明确 |
| 是否避免跑偏 | 强是 — §8 14 条明确禁止 + §4 10 条规则 + 每组件 not allowed 列 |
| 是否足够具体实现 | 是（对 Slice A）— 布局尺寸、ANSI token、边框字符均已指定 |

**Caveats（不阻塞 Slice A，实现时注意）**:
1. **Lens 命名歧义**: 当前代码 `AgentLensPanel` 的 "lens" 指 agent/session/run 选择树。Visual Target `LensPanel` 的 "lens" 指视图模式（Agent/Runtime/Tools/MCP/Evidence/Debug）。Slice A 实现中必须区分两者，建议命名：`SessionTreePanel`（左侧 agent/session/run 树）、`ViewLensPanel`（lens 视图模式选择）。
2. **缺少边缘状态 sketch**: 空消息区、compact mode（<80 列）、evidence lens 视图的 ASCII sketch 缺失。Slice A 实现时应补充空状态渲染。
3. **Fixture 数据结构未定义**: Visual Target 描述 mock 数据应展示什么但不定义具体 TS 接口。Slice A 实现需自行定义。

---

## 1. Slice A 范围

### 1.1 构建什么

Slice A 构建 **Static Visual Shell** — 所有 22 个组件的 skeleton 渲染 + 完整布局 + ANSI theme + mock 数据 + render/layout 测试。

```
Slice A = 6 区域布局 + 22 组件 skeleton + ANSI color tokens + box-drawing borders + [fake/local] 标注 + tests
```

### 1.2 明确不构建

- ❌ 不连接 RuntimeGateway（fake 或 real）
- ❌ 不连接真实 provider
- ❌ 不连接真实 MCP
- ❌ 不处理键盘导航（Tab/↑↓/Enter 交互）
- ❌ 不处理消息发送/接收
- ❌ 不处理 pending action approve/reject
- ❌ 不读取 .env
- ❌ 不激活 default entry
- ❌ 不删除旧组件（Dashboard 等保留在磁盘但不 import）

---

## 2. 布局合同（来自 Visual Target §2）

```
TuiShell:
  TopBar:          height 1 row
  LeftRail:        width 22-28 cols, fixed
  MainWorkArea:    width flexible (largest area), min 40 cols
  RightInspector:  width 30-38 cols, fixed
  InputDock:       height 5 rows (3 input + 1 chips + 1 spacer)
  BottomStatusBar: height 1 row
```

---

## 3. 组件清单与实现顺序

### Phase A1 — 基础设施（先做，其他组件依赖）

| 序号 | 组件 | 文件 | 说明 |
|------|------|------|------|
| A1.1 | Theme tokens | `tui/src/theme.ts` | ANSI color name → Ink color prop 映射，status color 常量 |
| A1.2 | Layout constants | `tui/src/layout.ts` | 终端宽度断点、LeftRail/RightInspector 宽度计算函数 |
| A1.3 | Mock data fixtures | `tui/src/data/visualShellFixtures.ts` | 所有 22 组件的 `[fake/local]` 静态数据 |

### Phase A2 — 6 区域布局骨架

| 序号 | 组件 | 文件 | 对应 Visual Target |
|------|------|------|------|
| A2.1 | TuiShell | `tui/src/components/TuiShell.tsx` | §3.1 — 顶层容器，6 区域布局 |
| A2.2 | TuiTopBar | `tui/src/components/TuiTopBar.tsx` | §3.2 — 1 行，产品名 + 状态 chips |
| A2.3 | LeftRail | `tui/src/components/LeftRail.tsx` | §3.3 — 左侧导航容器 |
| A2.4 | MainWorkArea | `tui/src/components/MainWorkArea.tsx` | §3.9 — 中间主交互区容器 |
| A2.5 | RightInspector (ContextInspectorPanel) | `tui/src/components/ContextInspectorPanel.tsx` | §3.16 — 右侧检查器容器 |
| A2.6 | InputDock | `tui/src/components/InputDock.tsx` | §3.14 — 输入区容器 |
| A2.7 | BottomStatusBar | `tui/src/components/BottomStatusBar.tsx` | §3.22 — 1 行全局状态 |

### Phase A3 — LeftRail 子面板

| 序号 | 组件 | 文件 | 对应 Visual Target |
|------|------|------|------|
| A3.1 | WorkspacePanel | `tui/src/components/WorkspacePanel.tsx` | §3.4 |
| A3.2 | ViewLensPanel | `tui/src/components/ViewLensPanel.tsx` | §3.5 — **注意命名**: 这是视图模式选择，不是 agent/session tree |
| A3.3 | SessionPanel | `tui/src/components/SessionPanel.tsx` | §3.6 — agent/session/run 树形导航 |
| A3.4 | RuntimeStatusPanel | `tui/src/components/RuntimeStatusPanel.tsx` | §3.7 |
| A3.5 | KeysPanel | `tui/src/components/KeysPanel.tsx` | §3.8 |

> **Lens 命名歧义处理**: 当前代码 `AgentLensPanel` 渲染 agent/session/run 选择树。Visual Target `LensPanel`（§3.5）渲染视图模式切换（Agent/Runtime/Tools/MCP/Evidence/Debug）。两者是不同的概念。Slice A 中：
> - **ViewLensPanel** = 视图模式选择器（Visual Target §3.5）
> - **SessionPanel** = agent/session/run 树形导航（Visual Target §3.6），相当于当前 `AgentLensPanel` 的简化版

### Phase A4 — MainWorkArea 子组件

| 序号 | 组件 | 文件 | 对应 Visual Target |
|------|------|------|------|
| A4.1 | MessageBlock | `tui/src/components/MessageBlock.tsx` | §3.10 — user/assistant/system 消息 |
| A4.2 | ToolCallBlock | `tui/src/components/ToolCallBlock.tsx` | §3.11 — `[TOOL]` 前缀 yellow |
| A4.3 | ToolResultTableBlock | `tui/src/components/ToolResultTableBlock.tsx` | §3.12 — ASCII 表格 |
| A4.4 | PendingActionBlock | `tui/src/components/PendingActionBlock.tsx` | §3.13 — `⚡` 前缀 yellow |
| A4.5 | CommandChipBar | `tui/src/components/CommandChipBar.tsx` | §3.15 |

### Phase A5 — RightInspector 子面板

| 序号 | 组件 | 文件 | 对应 Visual Target |
|------|------|------|------|
| A5.1 | ActiveContextPanel | `tui/src/components/ActiveContextPanel.tsx` | §1.6 — 当前 context 摘要 |
| A5.2 | RuntimeDecisionFramePanel | `tui/src/components/RuntimeDecisionFramePanel.tsx` | §3.17 |
| A5.3 | ToolSummaryPanel | `tui/src/components/ToolSummaryPanel.tsx` | §3.18 |
| A5.4 | McpBridgePanel | `tui/src/components/McpBridgePanel.tsx` | §3.19 |
| A5.5 | RecentEventsPanel | `tui/src/components/RecentEventsPanel.tsx` | §3.20 |
| A5.6 | MemoryCheckpointPanel | `tui/src/components/MemoryCheckpointPanel.tsx` | §3.21 |

### Phase A6 — 入口 + 测试

| 序号 | 内容 | 文件 |
|------|------|------|
| A6.1 | 更新 main.tsx | `tui/src/main.tsx` — import TuiShell 但不激活 default entry |
| A6.2 | Render tests | `tui/src/__tests__/visualShellRender.test.tsx` |
| A6.3 | Layout boundary tests | `tui/src/__tests__/visualShellLayout.test.tsx` |
| A6.4 | Mock labeling tests | `tui/src/__tests__/visualShellMockLabeling.test.tsx` |

---

## 4. 与现有代码的关系

### 4.1 保留但不 import 的组件

Slice A 阶段以下组件保留在磁盘上但不被 TuiShell import：

- `Dashboard.tsx` (and its legacy sub-panels: OverviewPanel, TaskCenterPanel, etc.)
- `WorkbenchLayout.tsx`（被 TuiShell 替代前保留，不删除）
- `DefaultEntryReadinessPanel.tsx`
- 所有 `*Panel.tsx` 中的旧 dashboard 面板

### 4.2 复用的现有代码

| 现有文件 | Slice A 如何处理 |
|---------|-----------------|
| `types.ts` | 新增类型但保留现有类型（向后兼容） |
| `data/agentLensFixture.ts` | 数据迁移到 `visualShellFixtures.ts`，旧文件保留 |
| `services/runtimeGateway.ts` | 不 import（Slice A 纯静态） |
| `InputBar.tsx` | 重构为 InputDock 的子组件 |
| `StatusBar.tsx` | 重构为 BottomStatusBar（格式对齐 Visual Target） |

---

## 5. Mock 数据策略

所有 mock 数据集中定义在 `tui/src/data/visualShellFixtures.ts`。每个 fixture 字段携带 `_label: "[fake/local]"` 元数据，组件渲染时必须可见标注。

```typescript
// 示例 fixture 结构
const MOCK_WORKSPACES = {
  _label: "[fake/local fixture]",
  items: [
    { id: "default", label: "default", status: "active" },
    { id: "project-a", label: "project-a", status: "idle" },
  ],
};

const MOCK_SESSIONS = {
  _label: "[fake/local fixture]",
  tree: [
    {
      agentId: "agent-001",
      status: "active",
      sessions: [
        {
          sessionId: "session-abc",
          status: "running",
          runs: [
            { runId: "run-001", status: "done" },
            { runId: "run-002", status: "running" },
          ],
        },
      ],
    },
  ],
};
```

---

## 6. Tests

### 6.1 Render tests (`visualShellRender.test.tsx`)

- TuiShell renders without crash
- All 6 zones render
- All 22 components render their `[fake/local]` label
- Empty state renders correctly (no crash, shows `—`)

### 6.2 Layout tests (`visualShellLayout.test.tsx`)

- TopBar height = 1 row
- BottomStatusBar height = 1 row
- LeftRail width within [22, 28] cols at ≥120 terminal
- RightInspector width within [30, 38] cols at ≥120 terminal
- InputDock height = 5 rows
- MainWorkArea takes remaining space

### 6.3 Mock labeling tests (`visualShellMockLabeling.test.tsx`)

- Every panel that uses mock data shows `[fake/local]` or `[fake/local fixture]`
- TopBar Provider chip shows `[fake/local]`
- MCP status shows `[fake/local]`
- No panel claims real/live/production status

---

## 7. Gate 检查

```bash
cd tui && npm test
cd tui && npm run typecheck
ruff check tui/ --select F,E  # Python files if any touched
git diff --check
```

---

## 8. 不做什么（Slice A 范围守卫）

- 不删除 WorkbenchLayout.tsx（保留到 Slice B 切换）
- 不激活 default entry
- 不连接任何 runtime/provider/MCP
- 不处理键盘事件
- 不 import RuntimeGateway
- 不修改 agent/ 下任何 Python 文件
- 不做宽度自适应响应逻辑（只渲染静态布局）

---

## 9. 文件变更清单

```
NEW:
  tui/src/theme.ts
  tui/src/layout.ts
  tui/src/data/visualShellFixtures.ts
  tui/src/components/TuiShell.tsx
  tui/src/components/TuiTopBar.tsx
  tui/src/components/LeftRail.tsx
  tui/src/components/ViewLensPanel.tsx
  tui/src/components/WorkspacePanel.tsx
  tui/src/components/SessionPanel.tsx
  tui/src/components/RuntimeStatusPanel.tsx
  tui/src/components/KeysPanel.tsx
  tui/src/components/MainWorkArea.tsx
  tui/src/components/MessageBlock.tsx
  tui/src/components/ToolCallBlock.tsx
  tui/src/components/ToolResultTableBlock.tsx
  tui/src/components/PendingActionBlock.tsx
  tui/src/components/CommandChipBar.tsx
  tui/src/components/InputDock.tsx
  tui/src/components/ContextInspectorPanel.tsx
  tui/src/components/ActiveContextPanel.tsx
  tui/src/components/RuntimeDecisionFramePanel.tsx
  tui/src/components/ToolSummaryPanel.tsx
  tui/src/components/McpBridgePanel.tsx
  tui/src/components/RecentEventsPanel.tsx
  tui/src/components/MemoryCheckpointPanel.tsx
  tui/src/components/BottomStatusBar.tsx
  tui/src/__tests__/visualShellRender.test.tsx
  tui/src/__tests__/visualShellLayout.test.tsx
  tui/src/__tests__/visualShellMockLabeling.test.tsx

MODIFIED:
  tui/src/main.tsx  # import TuiShell, render alongside (not replacing) WorkbenchLayout

NOT TOUCHED:
  tui/src/components/WorkbenchLayout.tsx  # preserved, not deleted
  All existing data/*, services/*, components/Dashboard.tsx etc.
  agent/  # zero Python changes
```

---

## 10. 版本历史

| 日期 | 变更 |
|------|------|
| 2026-06-02 | 初始版本 — 基于 Visual Target v1 审计 (ACCEPTED-WITH-CAVEATS) |
