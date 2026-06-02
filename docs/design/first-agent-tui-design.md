# First Agent TUI Design Direction

**创建日期**: 2026-06-02
**状态**: ACTIVE — 所有 B8 M1-M8 milestone 交付物的设计依据
**范围**: First Agent Terminal UI 设计语言、交互层级、视觉原则
**约束**: Terminal-native only — 不涉及 web/desktop/mobile，不照抄任何品牌

---

## 1. Product Personality

First Agent 是一个**通用 Agent Runtime/Workbench**。

三个词定义它：

| 维度 | 含义 |
|------|------|
| **终端原生** | 不模仿 GUI。不引入 web-only 概念（圆角卡片、阴影层级、响应式网格）。用 ANSI color、box-drawing character、间距和字号表达层级。 |
| **交互优先** | 默认焦点在 Input。用户输入是主事件流。Agent 响应、tool calls、pending actions 都围绕 interaction 展开。不是信息展示中心。 |
| **克制可观测** | Context/Inspector 不是默认视线焦点。用户主动 Tab 进入才展开细节。状态指示用最少字符传达最多信息。不堆砌面板。 |

First Agent **不是**：
- Coding engine（不绑定到特定领域）
- 项目管理 dashboard（不展示 task board / issue list / CI pipeline）
- 数据可视化平台（不做图表、不画流程图）
- 花哨 demo（不为了看起来复杂而复杂）

First Agent **是**：
- Agent runtime 的终端操作界面
- 用户发起 interaction → 观察 agent 行为 → 做出决策（approve/reject/调方向）
- 一个你可以在里面「和 agent 工作」的终端窗口

---

## 2. Layout Principles

### 2.1 三区域基线

```
┌──────────────────┬──────────────────────────────┬──────────────────────┐
│                  │                              │                      │
│   Agent Lens     │     Interaction View         │   Context Panel      │
│   (25%)          │     (50%)                    │   (25%)              │
│                  │                              │                      │
│   "选谁"          │     "说了什么"                │   "发生了什么"        │
│                  │                              │                      │
├──────────────────┴──────────────────────────────┴──────────────────────┤
│  Input Bar / Status Bar                                                │
└────────────────────────────────────────────────────────────────────────┘
```

### 2.2 区域语义

| 区域 | 宽度 | 职责 | 默认焦点 |
|------|------|------|---------|
| Agent Lens | 25% | 选择 agent/session/run/instance — 树形导航 | 否 |
| Interaction View | 50% | 用户 ↔ agent 对话流 — 主交互区 | **是** |
| Context Panel | 25% | Evidence/Gate/Memory/Event 只读摘要 | 否 |
| Input Bar | 全宽 | 文本输入 → agent | **是**（输入就绪） |
| Status Bar | 全宽 | focus/lens/pending count/快捷提示 | 否 |

### 2.3 不做什么

- **不**做 dashboard 扁平卡片网格（那是项目管理工具，不是 agent workbench）
- **不**做可拖拽面板分隔线（terminal 不支持，也不该支持）
- **不**引入大于 3 个主列（terminal 宽度 80-120 列，再分就不可读）
- **不**做动画过渡（terminal 不需要，闪烁就是坏味道）

### 2.4 焦点管理

- Tab 在 `interaction → agent-lens → context` 三区域间顺序循环
- Shift+Tab 反向循环
- Input Bar 始终可见但焦点受限于 interaction zone
- 焦点变化时 Status Bar 同步更新（不弹框、不闪屏）

---

## 3. Interaction Hierarchy

### 3.1 交互层级

```
Layer 1: Input → Agent     ← 主路径，默认焦点
Layer 2: Agent → Response  ← 对话流展示
Layer 3: Pending Actions   ← 需要用户决策的阻断点
Layer 4: Context/Inspector ← 按需展开的观察层
```

### 3.2 每层行为

| 层 | 触发 | 用户操作 | 视觉权重 |
|----|------|---------|---------|
| L1 Input | 用户主动输入 | 键入 + Enter | 高 — 始终可见，默认焦点 |
| L2 Response | agent 返回 | 阅读，不操作 | 中 — 主内容流 |
| L3 Pending | agent 需要确认 | ↑↓选择 + Enter/Esc | 高 — 阻断式，未决前不继续 |
| L4 Context | Tab 切换到 context zone | 浏览，不操作 | 低 — 按需查看 |

### 3.3 键盘优先级

1. `Enter` — 发送消息 / 确认 pending action
2. `Esc` — 拒绝 pending action / 取消
3. `Tab` / `Shift+Tab` — 焦点区域切换
4. `↑` `↓` — 列表导航（lens 树、pending action 列表）
5. `q` — 退出 TUI

不引入双层快捷键（如 Ctrl+某键）、不引入鼠标依赖。

---

## 4. Context / Inspector Panel Rules

Context Panel 是右侧 25% 区域，定位为**按需展开的只读观察层**。

### 4.1 内容规则

| 可展示 | 不可展示 |
|--------|---------|
| Evidence 状态（pass/fail/pending/caveat） | Evidence 全文 |
| Gate 摘要（gate name + status） | Gate 执行日志 |
| Memory 统计（retained/recalled count） | Memory 完整内容 |
| Event 最近 N 条摘要 | Event 全量 stream |
| Pending count + 最新 pending 摘要 | Pending 完整详情（那是 PendingActionPanel 的事） |
| Session/run 元信息 | 原始 JSON / config dump |

### 4.2 展示原则

- **摘要优先** — 每条 ≤1 行，不折叠、不 truncate 到无意义短串
- **状态色标** — color token 标记 pass/fail/pending/blocked/caveat
- **静态刷新** — 只在 interaction 完成后刷新，不做实时轮询
- **空状态** — 无数据时显示 `—` 或 `no data`，不显示 loading spinner

### 4.3 不做什么

- **不**把 Context Panel 当主视觉焦点（那是 Interaction View）
- **不**在 Context Panel 中展示 project-specific 工程运维数据
- **不**做实时 event tail（那是 B7 之后的事，且只做只读）
- **不**把 old Dashboard audit panels 搬到 Context Panel

---

## 5. Agent Lens Selection Rules

### 5.1 树形结构

```
agent-001 (active)          ← agent
  ├─ session-abc (running)  ← session
  │   ├─ run-001 (done)     ← run
  │   └─ run-002 (running)  ← run (当前选中)
  └─ session-def (historical)
      └─ run-003 (failed)
agent-002 (paused)
```

### 5.2 选择行为

- ↑↓ 在可见节点间移动
- Enter 选中 leaf node（run-level）
- 选中后 Interaction View 切换到对应 context
- 选中后 Context Panel 数据刷新到该 run 的 summary

### 5.3 状态标记

| 状态 | 标记 | 颜色 |
|------|------|------|
| active | ● | green |
| running | ◉ | green |
| paused | ◌ | yellow |
| completed/done | ✓ | dim |
| failed | ✗ | red |
| historical | — | dim |
| superseded | ~ | dim |

### 5.4 数据契约

- M1-M8 阶段：fake/local fixture data
- B7 就绪后：从 runtime identity 文件系统扫描
- 始终只读：不通过 TUI 创建/删除/重命名 agent/session/run

---

## 6. Input / Pending Action Rules

### 6.1 Input Bar

- 始终可见（底部固定）
- Enter 发送，Shift+Enter 换行
- 焦点受限于 interaction zone（Tab 进入/离开）
- 空输入不发送
- 无 agent 选中时 disabled（灰色 + `Select an agent to start` 提示）
- placeholder: `>` 或 `→`（简洁，不写 `Type your message here...` 这种 web 式文案）

### 6.2 Pending Action Panel

- 出现在 Interaction View 下方（不占新面板）
- 列出待确认 actions（tool/memory/checkpoint/safety）
- ↑↓ 导航，Enter 批准，Esc 拒绝
- 每个 action 一行：`[type] [tool name] [risk icon]`
- 处理后显示 outcome message 并自动消失
- 不堆叠超过 5 个 pending（超过时 oldest 自动 expired）

### 6.3 Pending Action 类型标记

| 类型 | 标记 | 风险色 |
|------|------|--------|
| tool_confirmation | TOOL | yellow |
| memory_proposal | MEM | green |
| checkpoint_save | CKPT | dim |
| safety_gate | SAFE | red |

---

## 7. Status and State Language

### 7.1 Status Bar

固定底部一行，格式：

```
[agent/run label]  [focus: interaction|agent-lens|context]  [⚡N pending]  [Tab: switch  q: quit]
```

### 7.2 一致性用词

| 场景 | 用词 | 不用 |
|------|------|------|
| 测试全通过 | `394/394 PASS` | `✅ All tests passed!` |
| 无数据 | `—` | `Nothing to show` |
| 空 agent list | `no agents` | `No agents available. Please create one.` |
| 未选中 lens | `none` | `Please select an agent from the left panel` |
| Fake/local 数据 | `[fake/local]` | `(simulated)` / `(mock)` |
| 阻断 | `blocked` | `not yet available` / `coming soon` |
| 未激活 | `NOT ACTIVATED` | `disabled` / `off` |

### 7.3 语言原则

- **不做 web 式 UX 写作** — 不写完整句子作为状态文本，不写 `please`，不写 `click here`
- **不拟人化** — 不写 `I'm thinking...`、`Let me help you with that`
- **数据优先** — `3 pending` 比 `You have 3 pending actions` 好
- **terminal 原生** — 用符号做标记（`●` `✓` `✗` `⚡`），但不滥用 emoji

---

## 8. Color / Token Suggestions for TUI

### 8.1 调色板

Ink 使用 ANSI color names。以下为建议 token 映射：

| Token | ANSI | 用途 |
|-------|------|------|
| `text` | white (default) | 正文 |
| `dim` | gray/dim | 次级信息、placeholder、分隔线 |
| `accent` | cyan | 选中项、焦点指示、可操作元素 |
| `success` | green | pass、done、completed、active |
| `warning` | yellow | pending、blocked、caveat、confirmation |
| `error` | red | failed、rejected、safety gate triggered |
| `info` | blue | 元信息、link、hint |
| `highlight` | magenta | 关键数据点（需用户注意的非错误信息） |

### 8.2 使用规则

- **一屏不超过 4 种颜色**（text + dim + 至多 2 accent color）
- 红/黄只用于状态标记（单字符符号），不做大段彩色文本
- 彩色背景不用于 terminal（不可靠、不可访问）
- bold 用于 section header，不用于正文强调

### 8.3 具体应用

| 位置 | 颜色 |
|------|------|
| Section header | bold white |
| Selected lens node | cyan |
| User message prefix `>` | cyan |
| Agent message | default white |
| System/outcome message | dim |
| Pending count `⚡N` | yellow (N>0) / dim (N=0) |
| Pass/done marker | green |
| Failed/blocked marker | red/yellow |
| Keybinding hint | dim |
| Separator line | dim |

---

## 9. Typography / Spacing Rules for Terminal

### 9.1 宽度假设

- 目标宽度：**80-120 列**（80 为安全基线，120 为舒适宽度）
- 80 列下三区域约：20 / 40 / 20
- 120 列下三区域约：30 / 60 / 30
- 不做响应式断点 — 低于 80 列时允许截断，不崩溃

### 9.2 字体假设

- 等宽字体（terminal 默认）
- 不做字符宽度假设（CJK 字符占 2 列由 terminal 处理）
- 不用 Unicode fullwidth 字符做对齐（不可靠）

### 9.3 Box-drawing

- 用 `─` `│` `┌` `┐` `└` `┘` `├` `┤` 做分隔
- 分隔线全宽（`"─".repeat(width)`）
- Section 内边距 1 空格
- Panel 间用竖线分隔

### 9.4 间距

- Section header 上下各空一行
- List item 不空行（terminal 垂直空间宝贵）
- 消息之间空一行
- 系统消息（outcome）与 agent 消息之间不额外空行

---

## 10. Do / Don't Examples

### 10.1 状态展示

```
DO:
  394/394 PASS  tsc clean  NOT ACTIVATED

DON'T:
  ✅ All 394 tests passed successfully!
  TypeScript compilation is clean with zero errors.
  Default entry is currently not activated for safety.
```

### 10.2 Pending Action

```
DO:
  ⚡ 2 pending
  [TOOL] write_file — ./src/config.ts  (Enter: approve  Esc: reject)

DON'T:
  ⚠️ You have 2 pending actions that require your attention:
    1. Tool Confirmation: write_file
       The agent wants to write to ./src/config.ts
       Press Enter to approve or Escape to reject.
```

### 10.3 Agent Lens

```
DO:
  ● agent-001 (active)
    ◉ session-abc
      ✓ run-001
      ◉ run-002

DON'T:
  🟢 Agent: agent-001
     Status: Active
     📂 Sessions: 1 active
       📋 Runs: 2 total, 1 completed, 1 in progress
```

### 10.4 Empty State

```
DO:
  no agents

DON'T:
  You don't have any agents configured yet.
  Create your first agent to get started!
```

### 10.5 Fake/local Honesty

```
DO:
  [fake/local] — M3 placeholder

DON'T:
  Agent response (simulated)
```

---

## 11. Fake/Local Honesty Rules

### 11.1 必须公开标注

以下情况**必须**在 UI 中可见标注：

| 情况 | 标注文本 | 位置 |
|------|---------|------|
| Fake/local interaction | `[fake/local mode]` | Interaction View header |
| Fixture data | `[fake/local fixture]` | 对应数据区域 |
| Contract 定义 | `source: "fake/local"` | 数据模型 source 字段 |
| B7-blocked 能力 | `blocked (B7)` | readiness checklist |
| Read-only projection | `read-only projection` | history/event panels |
| Mock gateway | `[fake/local] — no real tool executed` | outcome message |

### 11.2 标注原则

- 不藏在 tooltip/hover 里（terminal 没有）
- 不放在只有切换过去才看到的面板里
- 主路径中的 fake/local 标注必须在主视野中
- 颜色用 dim（不抢视觉焦点但可读）

### 11.3 禁止的声称

- 不得声称 `real agent interaction`（除非真实 provider E2E 通过）
- 不得声称 `multi-instance ready`（除非 B7 实现完成）
- 不得声称 `product-ready`（除非 default entry ACTIVATED + B7 + 用户批准）
- 不得声称 `production validated`（任何情况下）
- 不得把 `no-crash smoke test` 当 `capability PASS`
- 不得把 `guard test pass` 当 `loop pass`

---

## 12. Accessibility / Readability Rules

### 12.1 色彩对比

- 所有文本在黑色/深色 terminal 背景下必须可读
- 不在蓝色背景上放黑色文字、不在红色背景上放白色文字
- dim 文本不能在默认 terminal 背景下不可见（测试：macOS Terminal.app 默认 profile）

### 12.2 键盘可达

- 所有交互操作必须键盘可达
- 不依赖鼠标点击/拖拽/hover
- 不依赖 Emacs/Vim 键位记忆（Ctrl+P/N 等）
- 核心操作（Enter/Esc/Tab/↑↓/q）覆盖所有用户路径

### 12.3 输出安全

- 不输出 ANSI escape sequence 到非 terminal stdout
- 不在用户可见输出中打印 secret/token/api_key
- Redaction indicator `[redacted:N]` 不泄露被脱敏内容的长度/类型信息

### 12.4 CJK 文本

- Chinese IME 输入行为待实际终端验证（R14 blocked-ime）
- 不做 CJK 字符宽度计算（交给 terminal）
- CJK 文本展示不做自动换行假设（等 terminal 处理）

---

## 13. What Not to Build

以下内容**明确不构建**，不是"deferred to future"，是"不在 First Agent TUI 的产品范围内"：

### 13.1 不产品化

| 不构建 | 原因 |
|--------|------|
| Project-management dashboard 作为默认视图 | First Agent 是通用 agent workbench，不是项目管理工具 |
| AutoRun mainline | AutoRun 是 First Agent 项目自身的工程工具，不是 First Agent 产品功能 |
| Dynamic Audit Lens 产品化 | 旧 7 视图工作台已归档，audit 面板保留为 dev-only |
| Task board / issue list | 不在产品范围 |
| CI/CD pipeline 面板 | 不在产品范围 |
| Data visualization charts | terminal 不是图表工具 |

### 13.2 不过度工程

| 不构建 | 原因 |
|--------|------|
| 面板拖拽/缩放 | terminal 不支持，也不需要 |
| 主题系统 | 过早抽象 — 先做好一个主题 |
| 插件系统 | 过早抽象 |
| 多语言 i18n | 过早 — CJK 基础兼容性优先 |
| 配置 UI | CLI + config file 足够 |
| Animation/transition | terminal 不需要 |

### 13.3 不误导

| 不构建 | 原因 |
|--------|------|
| 把 fake/local mock 包装成真实集成 | 欺骗用户和欺骗自己 |
| 把 no-crash smoke 包装成能力验证 | 误导产品质量判断 |
| 把 contract 定义包装成 runtime 实现 | 误导 readiness 判断 |
| Real-time streaming UI（在真实 streaming 就绪前） | 先有 real capability，再有 UI |
| Default entry activation（在用户显式批准前） | 安全门禁 |

---

## 14. Implementation Status

本文档为 B8 M1-M8 实现的**设计依据**。

| Milestone | 状态 | 对齐本文档章节 |
|-----------|------|---------------|
| M1 Layout | DELIVERED | §2 Layout Principles, §9 Typography |
| M2 Agent Lens | DELIVERED | §5 Agent Lens Selection Rules |
| M3 Interaction | DELIVERED | §3 Interaction Hierarchy, §6 Input Rules |
| M4 Context Refresh | DELIVERED | §4 Context Panel Rules |
| M5 Pending Actions | DELIVERED | §6 Pending Action Rules, §3 Interaction Hierarchy |
| M6 History | DELIVERED | §4 Context Panel Rules, §11 Honesty Rules |
| M7 Event Stream | DELIVERED | §4 Context Panel Rules, §11 Honesty Rules |
| M8 Readiness | DELIVERED | §11 Honesty Rules, §13 What Not to Build |

---

## 15. Version History

| 日期 | 变更 |
|------|------|
| 2026-06-02 | 初始版本 — 13 节设计方向定义，对齐 B8 M1-M8 交付物 |
