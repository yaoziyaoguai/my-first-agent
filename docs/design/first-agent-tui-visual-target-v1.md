# First Agent TUI Visual Target v1

**创建日期**: 2026-06-02
**状态**: ACTIVE — TUI 视觉目标定义，供 Coding Agent 严格参照实现
**范围**: 精确描述 First Agent TUI 的视觉外观、布局合同、组件边界、数据源策略
**上游设计**: `docs/design/first-agent-tui-design.md`（设计方向/原则）
**下游实现**: B8 M1-M8 Interaction-first Workbench（当前 fake/local foundation 已交付）

---

核心结论：

First Agent TUI should look like a polished dark terminal workbench with:
- a top status bar
- a left navigation rail
- a large center interaction/work area
- a right context inspector
- a bottom input/status dock
- dense but readable terminal panels
- neon accent highlights (ANSI color, not actual neon)
- clear runtime/tool/MCP/status indicators

---

## 1. Reference Image Description

本项目的目标视觉不存在参考图片。以下描述基于 `docs/design/first-agent-tui-design.md` 的方向定义，精确到可实现的细节层级。

### 1.1 整体

- 深色 terminal-native UI，背景为 terminal 默认黑色（ANSI default background）
- 宽屏三栏布局：左侧固定宽度导航栏 / 中间弹性主工作区 / 右侧固定宽度检查器
- 黑色/深蓝（ANSI blue background 慎用）/深灰（ANSI dim）作为面板底色层次
- 青色（cyan）、绿色（green）、紫色（magenta）、黄色（yellow）作为状态高亮色
- panel 边框使用 box-drawing characters（`─` `│` `┌` `┐` `└` `┘` `├` `┤`），清晰但不刺眼
- 信息密度较高（terminal 垂直空间宝贵），但主交互区保持最大面积和可读性
- 整体像现代化 terminal workbench（如 htop/lazygit 风格），不像普通 web dashboard

### 1.2 顶部 TopBar

- 一条横向 TopBar，高度 1 行
- 左侧显示产品名 `First Agent TUI`
- 中间/右侧显示状态 chips：`Runtime: unified` `Mode: ACT` `Lens: Agent` `Provider: fake/local`
- 状态 chip 使用方括号包裹的小型高亮样式，如 `[fake/local]`（dim 色）、`[Agent]`（cyan 色）
- 不放复杂菜单，不放面包屑，只做环境感知

具体示例：

```
First Agent TUI    Runtime: unified   Mode: ACT   Lens: Agent   Provider: fake/local
```

### 1.3 左侧 LeftRail

- 固定宽度 22-28 列
- 从上到下依次包含以下区块（每区块有 bold white section header）：
  - **Workspaces** — workspace 列表，当前选中项 cyan 高亮，每项一行带 `●` 状态点
  - **Lenses** — lens 列表（Agent / Runtime / Tools / MCP / Evidence / Debug），当前选中 lens 紫色（magenta）标记
  - **Sessions / Recent** — 最近 session/run 列表，紧凑一行一项，带状态符号
  - **Status / Keys** — runtime/provider/tool/MCP 当前状态小提示，dim 色，不抢焦点
- 列表项紧凑：每项 ≤1 行，无多余 padding
- 当前选中项整行 cyan 前景色（或 reverse video），不使用 block cursor
- 左侧是导航，不是项目管理大屏

### 1.4 中间 MainWorkArea

- 中间是最大区域（弹性宽度，80 列终端下约 40-50 列）
- 标题行：`Chat / Work Area`（bold white）
- 展示对话流：
  - 用户消息：`>` 前缀（cyan），后跟消息正文（default white）
  - 助手消息：无前缀或 `assistant` 标签（dim），正文 default white
  - tool call block：`[TOOL]` 前缀（yellow），tool name + 关键参数，与普通消息视觉区分
  - tool result block：缩进展示，`→` 前缀（green），结果摘要
  - table/result block：ASCII box-drawing 表格，header bold，数据行 default
  - pending action block：`⚡` 前缀（yellow），action type + target + 确认提示
- 消息以 block 形式呈现，block 之间空一行
- 中间区域是默认主线，用户视线首先落在这里
- 不能被 evidence / docs / tests 信息抢占

### 1.5 底部 InputDock

- 位于中间区域底部，MainWorkArea 和 BottomStatusBar 之间
- 多行输入区域（至少 3 行可见），placeholder 为 `>` 或 `→`
- 输入区下方一行 command chips：`/ask` `/plan` `/run` `/tools` `/help`
- chips 使用 dim 边框包裹的短标签样式
- 右侧显示 send/execute affordance：`[Enter: send]`（dim）
- 模式提示：`fake/local` `real provider` `MCP: N tools` 在输入区右上方
- 输入区永远可见，不随对话滚动隐藏

### 1.6 右侧 ContextInspector

- 固定宽度 30-38 列
- 包含以下子面板（从上到下堆叠）：
  - **Active Context** — 当前 selectedLens 摘要（agent/session/run ID）
  - **Runtime Decision Frame** — runtime 决策摘要（≤5 行）
  - **Tool Summary** — 最近工具调用状态（tool name + status color）
  - **MCP Bridge** — MCP discover/invoke/lifecycle 状态（≤3 行）
  - **Recent Events** — 最近 runtime events（≤5 条，每条 1 行）
  - **Memory / Checkpoint** — memory 条目数 + 最近 checkpoint ID
  - **Evidence Snapshot** — 仅在 Developer/Evidence lens 下展示，默认 Agent lens 下隐藏或折叠为 1 行摘要
- 每个子面板有短标题（bold white）、状态指示（color dot）、简短摘要（dim，≤2 行）
- 状态颜色：
  - green: READY / PASS / healthy
  - yellow: PARTIAL / PENDING / caveat
  - red: FAIL / BLOCKED / unsafe
  - blue: runtime / context / information
  - purple (magenta): lens / selected workspace
- Evidence Snapshot 只能作为 developer/evidence 子区块，不是默认重点

### 1.7 底部 BottomStatusBar

- 最底部一条状态栏，高度 1 行
- 显示（从左到右）：
  - version: `v0.x`
  - runtime: `runtime: unified`
  - mode: `mode: ACT`
  - lens: `lens: Agent`
  - tool count: `tools: N ready`
  - MCP: `mcp: partial`
  - provider: `provider: fake/local`
  - help hint: `q: quit  Tab: switch`
- 状态栏紧凑，使用 dim 色，不抢主交互区
- 格式示例：

```
v0.x | runtime: unified | mode: ACT | lens: Agent | tools: 3 ready | mcp: partial | fake/local | q: quit  Tab: switch
```

---

## 2. Layout Contract

### 2.1 固定布局定义

```
TuiShell:
  TopBar:          height 1 row
  LeftRail:        width 22-28 cols, fixed
  MainWorkArea:    width flexible (largest area), min 40 cols
  RightInspector:  width 30-38 cols, fixed
  InputDock:       height 5 rows (3 input + 1 chips + 1 spacer), bottom of center area
  BottomStatusBar: height 1 row
```

### 2.2 ASCII Layout Sketch

以下 sketch 是**实现合同**——Coding Agent 必须按此布局渲染：

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ First Agent TUI  Runtime: unified  Mode: ACT  Lens: Agent  Provider: fake/local│
├───────────────┬──────────────────────────────────────────────┬───────────────┤
│ Workspaces    │ Chat / Work Area                             │ Context       │
│ ● default     │                                              │ Inspector     │
│ ● project-a   │ user > hey, can you check the config?        │               │
│               │                                              │ Active Context│
│ Lenses        │ assistant > I'll look at the config file     │ agent: default│
│ ◉ Agent       │   and check for issues.                     │ run: run-002  │
│   Runtime     │                                              │               │
│   Tools       │ [TOOL] read_file — ./src/config.ts           │ Runtime Frame │
│   MCP         │   → 42 lines, no syntax errors              │ mode: ACT     │
│   Evidence    │                                              │ status: ready │
│   Debug       │ ⚡ [TOOL] write_file — ./src/config.ts       │               │
│               │   Enter: approve  Esc: reject               │ Tool Summary  │
│ Sessions      │                                              │ read_file  ✓  │
│ ◉ session-abc │                                              │ write_file ⚡ │
│   ✓ run-001   │                                              │ grep       —  │
│   ◉ run-002   │                                              │               │
│               │                                              │ MCP Bridge    │
│ Status        │                                              │ discover: 3   │
│ runtime: ok   │                                              │ invoke: ready │
│ mcp: partial  │                                              │               │
│ tools: 3      │                                              │ Events        │
│               │                                              │ 12:03 run start│
│ Keys          │                                              │ 12:04 tool call│
│ Tab: switch   │                                              │ 12:04 result  │
│ q: quit       │                                              │               │
│               │                                              │ Memory/CKPT   │
│               │                                              │ entries: 12   │
│               │                                              │ ckpt: ck-004  │
├───────────────┴──────────────────────────────────────────────┴───────────────┤
│ > hey, can you check the config?                                             │
│                                                                              │
│                                                                              │
│ /ask  /plan  /run  /tools  /help                          [Enter: send]     │
├──────────────────────────────────────────────────────────────────────────────┤
│ v0.x | runtime: unified | mode: ACT | lens: Agent | tools: 3 ready | mcp: partial | fake/local | q: quit  Tab: switch │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 2.3 宽度自适应规则

| 终端宽度 | LeftRail | MainWorkArea | RightInspector | 行为 |
|---------|----------|-------------|----------------|------|
| ≥120 列 | 28 列 | ~56 列 | 36 列 | 舒适模式，全功能 |
| 80-119 列 | 22 列 | ~34 列 | 24 列 | 紧凑模式，RightInspector 截断长文本 |
| <80 列 | 20 列 | 剩余宽度 | 隐藏或 0 列 | 最小模式，RightInspector 完全隐藏，Tab 可切换显示 |

### 2.4 最小宽度硬限制

- 低于 60 列：不渲染 TUI，显示 `Terminal too narrow (min 60 cols)` 并退出
- 不做响应式断点矩阵 — terminal 不是 web

---

## 3. Component Mapping

每个组件必须说明 purpose、data source、mock allowed、future real integration、not allowed responsibilities。

### 3.1 TuiShell

| 属性 | 值 |
|------|-----|
| purpose | 顶层布局容器，管理 LeftRail / MainWorkArea / RightInspector / InputDock / BottomStatusBar / TopBar 的尺寸分配和焦点路由 |
| data source | 无直接数据源；接收 selectedLens state 并向下传递 |
| mock allowed | N/A（纯布局） |
| future real integration | 无变化 |
| not allowed | 不处理业务逻辑、不持有 interaction state、不直接读写 memory/checkpoint/event |

### 3.2 TuiTopBar

| 属性 | 值 |
|------|-----|
| purpose | 显示产品名（`First Agent TUI`）和全局状态 chips（runtime/mode/lens/provider） |
| data source | `RuntimeStatusSnapshot`（从 TuiShell 注入）、当前 selectedLens |
| mock allowed | 是 — `[fake/local]` 标注必须可见 |
| future real integration | 从 RuntimeGateway 读取真实 provider/mode 状态 |
| not allowed | 不放菜单、不放面包屑、不显示 secret/token |

### 3.3 LeftRail

| 属性 | 值 |
|------|-----|
| purpose | 左侧导航容器，垂直堆叠 WorkspacePanel / LensPanel / SessionPanel / RuntimeStatusPanel / KeysPanel |
| data source | 无直接数据源；作为容器传递 props |
| mock allowed | 是 — 子面板各自管理数据 |
| future real integration | 无变化（容器角色） |
| not allowed | 不处理导航逻辑（子面板各自处理）、不横向滚动 |

### 3.4 WorkspacePanel

| 属性 | 值 |
|------|-----|
| purpose | 展示 workspace 列表，当前选中项 cyan 高亮，每项一行带 `●` 状态点 |
| data source | `agentLensFixture`（fake/local workspace list） |
| mock allowed | 是 — `[fake/local fixture]` 标注 |
| future real integration | 从 runtime identity 文件系统扫描 workspace |
| not allowed | 不创建/删除/重命名 workspace、不展示 project-specific 工程数据 |

### 3.5 LensPanel

| 属性 | 值 |
|------|-----|
| purpose | 展示 lens 列表（Agent / Runtime / Tools / MCP / Evidence / Debug），当前选中 lens magenta 标记 |
| data source | 静态 lens 枚举列表 |
| mock allowed | 是 — lens 列表为静态定义 |
| future real integration | 可能从 config 动态注册 lens |
| not allowed | 不动态增删 lens、不把 Evidence 作为默认 lens |

### 3.6 SessionPanel

| 属性 | 值 |
|------|-----|
| purpose | 展示 session/run/instance 树形列表，↑↓ 导航，Enter 选中 leaf node |
| data source | `agentLensFixture`（fake/local agent/session/run 树） |
| mock allowed | 是 — `[fake/local fixture]` 标注 |
| future real integration | 从 runtime identity 文件系统扫描 session/run/instance |
| not allowed | 不创建/删除 session、不修改 run state |

### 3.7 RuntimeStatusPanel

| 属性 | 值 |
|------|-----|
| purpose | 展示 runtime/provider/tool/MCP 当前状态（各一行，color dot + status text） |
| data source | `RuntimeStatusSnapshot` |
| mock allowed | 是 — `[fake/local]` 标注 |
| future real integration | 从 RuntimeGateway 读取真实状态 |
| not allowed | 不轮询、不做实时更新、不展示 secret |

### 3.8 KeysPanel

| 属性 | 值 |
|------|-----|
| purpose | 展示快捷键提示（Tab: switch / q: quit / ↑↓: navigate / Enter: select） |
| data source | 静态快捷键映射 |
| mock allowed | N/A（静态内容） |
| future real integration | 无变化 |
| not allowed | 不展示所有快捷键（只展示核心 4-5 个）、不响应按键（纯展示） |

### 3.9 MainWorkArea

| 属性 | 值 |
|------|-----|
| purpose | 中间主交互区域，渲染对话流（MessageBlock / ToolCallBlock / ToolResultTableBlock / PendingActionBlock） |
| data source | `InteractionMessage[]`（从 RuntimeGateway.send() 返回） |
| mock allowed | 是 — fake/local interaction history |
| future real integration | 从 CoreChatGateway 获取真实 agent response |
| not allowed | 不直接调用 core.chat()、不构造假消息、不绕过 RuntimeGateway |

### 3.10 MessageBlock

| 属性 | 值 |
|------|-----|
| purpose | 渲染单条 user / assistant / system 消息 |
| data source | `InteractionMessage` |
| mock allowed | 是 |
| future real integration | 无变化（渲染逻辑不变） |
| not allowed | 不修改消息内容、不截断到无意义短串 |

### 3.11 ToolCallBlock

| 属性 | 值 |
|------|-----|
| purpose | 渲染 tool call（`[TOOL]` 前缀 yellow，tool name + 关键参数摘要） |
| data source | `ToolCallRecord` |
| mock allowed | 是 — fake/local tool call |
| future real integration | 无变化（渲染逻辑不变），但数据源变为真实 tool call |
| not allowed | 不执行 tool、不修改 tool 参数、不隐藏 gateStatus |

### 3.12 ToolResultTableBlock

| 属性 | 值 |
|------|-----|
| purpose | 渲染表格化工具结果（ASCII box-drawing table） |
| data source | `ToolCallRecord.result` |
| mock allowed | 是 |
| future real integration | 无变化 |
| not allowed | 不渲染超过 20 行的表格（截断 + `... (N more rows)` 提示） |

### 3.13 PendingActionBlock

| 属性 | 值 |
|------|-----|
| purpose | 渲染待确认操作（`⚡` 前缀 yellow，action type + target + Enter/Esc 提示） |
| data source | `PendingAction` |
| mock allowed | 是 — fake/local pending actions |
| future real integration | 无变化，但数据源变为真实 pending actions |
| not allowed | 不自动批准/拒绝、不隐藏风险信息 |

### 3.14 InputDock

| 属性 | 值 |
|------|-----|
| purpose | 输入框 + CommandChipBar 的容器 |
| data source | 用户键盘输入 |
| mock allowed | N/A |
| future real integration | 无变化 |
| not allowed | 不绕过 RuntimeGateway.send() 直接操作、不读取 .env |

### 3.15 CommandChipBar

| 属性 | 值 |
|------|-----|
| purpose | 展示 `/ask` `/plan` `/run` `/tools` `/help` command chips |
| data source | 静态 command 列表 |
| mock allowed | N/A（静态内容） |
| future real integration | 可能从 skill registry 动态生成 |
| not allowed | 不执行 command（只展示 + 输入自动补全） |

### 3.16 ContextInspectorPanel

| 属性 | 值 |
|------|-----|
| purpose | 右侧总容器，垂直堆叠所有 inspector 子面板 |
| data source | `ContextSnapshot` |
| mock allowed | 是 — fake/local context data |
| future real integration | 从 RuntimeGateway 获取真实 context snapshot |
| not allowed | 不成为默认焦点、不展示 project-specific 工程运维数据 |

### 3.17 RuntimeDecisionFramePanel

| 属性 | 值 |
|------|-----|
| purpose | 展示 RuntimeDecisionFrame 摘要（mode / status / last decision） |
| data source | `RuntimeDecisionFrame` |
| mock allowed | 是 — fake/local frame |
| future real integration | 从 RuntimeGateway 获取真实 decision frame |
| not allowed | 不展示完整 decision log、不超过 5 行 |

### 3.18 ToolSummaryPanel

| 属性 | 值 |
|------|-----|
| purpose | 展示最近工具调用状态（tool name + status color dot） |
| data source | `ContextSnapshot` 中的 tool summary |
| mock allowed | 是 |
| future real integration | 从 RuntimeGateway 获取真实 tool status |
| not allowed | 不展示完整 tool 参数、不展示 tool 内部实现细节 |

### 3.19 McpBridgePanel

| 属性 | 值 |
|------|-----|
| purpose | 展示 MCP discover / invoke / lifecycle 状态（≤3 行） |
| data source | `McpBridgeStatus` |
| mock allowed | 是 — `[fake/local]` MCP status |
| future real integration | 从真实 MCP client 获取状态 |
| not allowed | 不发起 MCP 连接、不展示 MCP server 配置详情 |

### 3.20 RecentEventsPanel

| 属性 | 值 |
|------|-----|
| purpose | 展示最近 runtime events（≤5 条，每条 1 行，timestamp + event type） |
| data source | `EventRecord[]` |
| mock allowed | 是 — fake/local event fixture |
| future real integration | 从 EventLog 读取真实 events |
| not allowed | 不 tail real process、不展示 redacted 字段的原始值 |

### 3.21 MemoryCheckpointPanel

| 属性 | 值 |
|------|-----|
| purpose | 展示 memory 条目数 + 最近 checkpoint ID（≤2 行） |
| data source | `MemorySummary` + `CheckpointSummary` |
| mock allowed | 是 — fake/local summary |
| future real integration | 从 MemoryStore 和 CheckpointStore 读取真实摘要 |
| not allowed | 不展示 memory 完整内容、不展示 checkpoint 详情 |

### 3.22 BottomStatusBar

| 属性 | 值 |
|------|-----|
| purpose | 展示全局简短状态（version / runtime / mode / lens / tools / MCP / provider / key hints） |
| data source | `RuntimeStatusSnapshot` + 静态 version |
| mock allowed | 是 — `fake/local` 标注 |
| future real integration | 从 RuntimeGateway 读取真实状态 |
| not allowed | 不滚动、不换行、不展示超过 1 行的内容 |

---

## 4. Data Source Policy

### 4.1 允许的数据源

| 数据源 | 说明 | 标注要求 |
|--------|------|---------|
| existing safe runtime state | 已通过安全审计的 runtime 状态 | 无需标注 |
| fake/local fixture | TUI 开发用的假数据 | `[fake/local]` 或 `[fake/local fixture]` |
| docs-derived status | 从 docs 推导的状态（如 milestone 完成状态） | `[docs-derived]` |
| evidence summary | 从本地 evidence 文件提取的摘要 | `[evidence]` |
| future adapter placeholder | 预留接口但未实现的 adapter | `[blocked: B7]` 或 `[future]` |

### 4.2 规则

1. fake/local 数据必须显示 `[fake/local]` 或 `[fake/local fixture]` 标注，标注必须在主视野中可见，不能用 dim 色藏到不可读。
2. docs-derived status 不能伪装成 live runtime status。
3. local MCP smoke 不能伪装成 production MCP。
4. real provider validation 不能伪装成 product-ready。
5. Evidence 只能在 developer/evidence lens 下强展示。默认 Agent lens 下 Evidence 区域折叠为 1 行摘要或完全隐藏。
6. 默认 Agent lens 不显示大面积 PROJECT_STATUS / PROGRESS_LEDGER。
7. TUI 不直接写 memory / checkpoint / event log。所有写操作通过 RuntimeGateway。
8. TUI 不绕过 ToolRuntimeMediator。
9. TUI 不成为第二 runtime。
10. TUI 不读取 `.env`，不打印 secret。Redaction 标注使用 `[redacted]`（不泄露长度/类型信息）。

---

## 5. Default Lens vs Developer Lens

### 5.1 Default Lens（Agent Lens）

用户启动 TUI 后的默认视图：

- **中间**：主交互区（对话流、tool call、pending action）
- **左侧**：Agent/Session/Run 树形导航
- **右侧**：只显示当前 context（Active Context）、runtime frame（≤5 行）、tool summary（最近 N 个）、MCP 简况（≤3 行）、recent events（≤5 条）、memory/checkpoint 摘要（≤2 行）
- **不显示**：Evidence Snapshot（或折叠为 1 行 `evidence: N items`）、PROJECT_STATUS、PROGRESS_LEDGER、dogfood results

### 5.2 Developer/Evidence Lens

用户通过 LensPanel 手动切换到 Evidence lens 后：

- **中间**：仍然主交互区（不替换）
- **右侧**：展开 Evidence Snapshot，包含：
  - Evidence 摘要（从当前 evidence source 提取）
  - docs source-of-truth 状态
  - tests/gates 摘要
  - close-out status
  - RuntimeDecisionFrame 更深层详情

### 5.3 重要约束

- Developer/Evidence Lens **不是默认主界面**
- 不要让 TUI 回到项目管理 Dashboard
- 切换 lens 是用户主动行为，不是自动触发
- StatusBar 在 Evidence lens 下追加 `[EVIDENCE]` 标记

---

## 6. Visual Language

### 6.1 Theme

- 深色 terminal 背景（ANSI default background = 终端默认黑色）
- 面板使用 dim 边框分隔，不使用彩色背景
- 强调色：cyan / green / yellow / magenta（ANSI 标准色）
- 不使用大块白色区域（terminal 不支持也不应该）
- 不做 web dashboard 外观（无圆角卡片、无阴影层级、无渐变背景）

### 6.2 Status Colors

| 颜色 | ANSI | 含义 |
|------|------|------|
| green | `green` | READY / PASS / healthy / done / active |
| yellow | `yellow` | PARTIAL / PENDING / caveat / confirmation |
| red | `red` | FAIL / BLOCKED / unsafe / rejected |
| cyan | `cyan` | selected item / focus indicator / actionable / user input prefix |
| blue | `blue` | runtime / context / information / link |
| magenta | `magenta` | lens indicator / selected workspace / key data point |
| dim | `dim` / `gray` | secondary info / placeholder / separator / hint / disabled |

### 6.3 Typography

- 等宽字体（terminal 默认，不做字体选择）
- Section header：bold white
- 正文：default white
- 次级信息：dim
- 标签/状态文本：紧凑，短标签风格（`[TOOL]`、`[fake/local]`、`⚡`）
- 不在 panel 内写长段落
- 详情应可折叠或移到 developer lens

### 6.4 Borders

- 使用 box-drawing characters：`─` `│` `┌` `┐` `└` `┘` `├` `┤`
- 外层边框 dim 色
- 内部分隔线 dim 色、比外层更细（可用 `·` 或 `┄` 替代 `─`）
- 不使用嵌套过深的 box（最多 2 层边框嵌套）
- 用空行分隔 section，减少对边框的依赖

### 6.5 Density

- 高信息密度是允许的（terminal 天然紧凑）
- 但中间 MainWorkArea 必须保持可读性优先
- 不要让所有 panel 同样响亮 — 左侧和右侧用 dim 降低视觉权重
- 每个 panel 最多展示 8-10 行（超出则截断 + `...`）

---

## 7. Interaction Rules

1. **MainWorkArea is primary.** 默认焦点在中间交互区。
2. **InputDock always visible.** 无论焦点在哪里，输入区始终可见。
3. **User always sees current mode / provider / lens / session.** TopBar 和 BottomStatusBar 双重显示关键状态。
4. **Command chips are visible shortcuts.** 在 InputDock 中展示，输入 `/` 时自动补全。
5. **Keyboard shortcuts must avoid common terminal conflicts.** 不使用 `Ctrl+C`（留给 SIGINT）、`Ctrl+D`（留给 EOF）、`Ctrl+Z`（留给 SIGTSTP）、`Ctrl+S`（留给 terminal flow control）。
6. **No `Ctrl+A` full-screen Dashboard switch.** 不提供整页切换 hotkey。
7. **Pending actions require explicit confirmation** unless user granted scoped permission via RuntimeGateway.
8. **Help must be discoverable.** `/help` chip + `?` key（不占用核心快捷键）。
9. **Exit must be obvious.** `q` 退出，BottomStatusBar 始终显示 `q: quit`。
10. **Developer/Evidence mode must be clearly labeled.** StatusBar 追加 `[EVIDENCE]`，TopBar lens chip 更新。

---

## 8. What Not to Build

以下内容**明确禁止**在 TUI Visual Shell 中构建：

- ❌ no old Dashboard resurrection（`Dashboard.tsx` 保留在磁盘但不 import/渲染）
- ❌ no AutoRun console as main UI
- ❌ no Project Operations mainline
- ❌ no Dynamic Audit Lens productization
- ❌ no evidence-first default screen
- ❌ no product-ready claim
- ❌ no default entry activation in visual shell phase
- ❌ no real provider call during visual shell implementation
- ❌ no real MCP server during visual shell implementation
- ❌ no `.env` access
- ❌ no secret display
- ❌ no second runtime
- ❌ no fake data without `[fake/local]` label
- ❌ no docs-derived status pretending to be live
- ❌ no local MCP smoke pretending to be production

---

## 9. Implementation Slices

### Slice A — Static Visual Shell（当前文档目标）

- 所有 22 个组件的 skeleton（只渲染布局 + 静态文本 + mock 数据）
- 完整的 layout zones（TopBar / LeftRail / MainWorkArea / RightInspector / InputDock / BottomStatusBar）
- 完整的 visual theme（ANSI color tokens、box-drawing borders、dim/bold 层次）
- 所有 mock/fake 数据必须标注 `[fake/local]`
- tests for render and layout boundaries
- **不连接任何真实 runtime/provider/MCP**

### Slice B — Wire Existing Safe Data

- 从 fixture 数据中读取 selectedLens
- fake/local interaction history 渲染
- pending actions（fake/local）渲染
- RuntimeDecisionFrame 摘要（fake/local）
- MCP local smoke status if available（fake/local）

### Slice C — Developer/Evidence Lens

- REAL-EVIDENCE summary 面板（在 Evidence lens 下展示）
- docs source-of-truth 状态
- tests/gates 摘要
- 不是默认视图

### Slice D — Real Adapter Summaries

- D-02 MCP local smoke status → McpBridgePanel
- D-04 runtime gateway validation status → RuntimeDecisionFramePanel
- D-09 skill evidence status → Evidence panel（仅在 developer lens）
- 仍然标注 `[evidence]` / `[docs-derived]`，不声称 product-ready

### Slice E — Interaction Polish

- keyboard navigation（Tab/Shift+Tab/↑↓/Enter/Esc/q）
- resize behavior（宽度自适应规则）
- scrollback（MainWorkArea 消息历史滚动）
- multiline input（Shift+Enter 换行）
- paste handling
- IME validation（CJK 输入兼容性）

### Slice F — Future Default Entry Readiness

- only after explicit user approval
- fallback CLI preserved（`python main.py` 永不被删除）

---

## 10. Acceptance Criteria

本 Visual Target 文档的验收标准：

1. ✅ 后续 Coding Agent 能只看本文档理解 TUI 长什么样（无需看图、无需猜测）。
2. ✅ Layout zones 明确（TopBar / LeftRail / MainWorkArea / RightInspector / InputDock / BottomStatusBar）。
3. ✅ 22 个组件清单明确，每个组件的 purpose / data source / mock allowed / not allowed 已定义。
4. ✅ default lens（Agent）和 developer lens（Evidence）清楚分离。
5. ✅ fake/local 和 real data 边界明确（§4 Data Source Policy + §11 Fake/Local Honesty Rules in `first-agent-tui-design.md`）。
6. ✅ 不会把 TUI 做回 Dashboard（§8 What Not to Build）。
7. ✅ 不会把 Evidence 做成默认主界面（§5 Default Lens vs Developer Lens）。
8. ✅ 不会误接真实 provider / MCP（§4 规则 3/4 + §8）。
9. ✅ Slice A 可独立实现（§9 Implementation Slices — 只做 skeleton + mock + theme + tests）。
10. ✅ 每个后续 slice 都有明确边界（Slice B/C/D/E/F）。

---

## 11. Next Implementation Prompt

**Recommended next prompt:**

> Implement Slice A only: static visual shell + component skeletons + mock/fake data + render tests. Do not wire real runtime, real provider, or real MCP. All fake/local data must be visibly labeled `[fake/local]`. Follow the layout contract in `docs/design/first-agent-tui-visual-target-v1.md` §2.2 ASCII sketch exactly.

---

## 12. Version History

| 日期 | 变更 |
|------|------|
| 2026-06-02 | 初始版本 — 22 组件映射、6 区域布局合同、data source policy、default/developer lens 分离、Slice A-F 实现顺序 |
