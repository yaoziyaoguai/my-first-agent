# B8 Interaction-first Workbench Proposal

**创建日期**: 2026-06-02
**状态**: PROPOSAL — 待用户审阅
**取代**: B8 原有 "信息展示中心" 产品方向
**依赖**: B7 current-stage closed (accepted-with-caveats)

---

## 1. Why

### 1.1 问题：B8 为什么会跑偏成信息展示中心

B8 的初始动机是"让 TUI 替代 CLI 成为默认入口"。但实际执行中，所有 Phase 都围绕"能展示什么数据"展开——evidence、gate、audit、docs、debt、task、workflow。结果是 7 个只读视图 + 6 个安全命令，但没有一个视图让用户和 First Agent **交互**。

这不是实现错误，是产品定义缺失：从来没有明确"主入口"意味着什么，TDD 和 gate 自然就按"面板完成度"衡量。

### 1.2 为什么必须转成 interaction-first

First Agent 的核心价值是**对话式 agent runtime**——用户输入 → agent 理解 → tool execution → memory → response。一个不能交互的 TUI 无论展示多少审计数据，都无法成为"主入口"。主入口的第一能力是**交互**，审计是辅助。

### 1.3 为什么保留 audit/evidence/gate 信息

交互过程中，用户需要看到：
- 当前 agent 的状态（哪个 skill 激活、哪个 tool 刚执行）
- 刚产生的 evidence（TOOL_GATE/TOOL_INVOKE/TOOL_RESULT）
- 当前 session/run 的 gate 状态
- 记忆和 checkpoint 变化

这些信息不应该消失——它们应该**随交互动态展示**，而不是在另外的标签页里静态陈列。

---

## 2. Product Position

**B8 = First Agent Interactive Workbench。**

- **不是** AutoRun 控制台
- **不是** 单纯状态看板
- **不是** 第二 runtime
- **是** First Agent 的交互式主入口候选——用户在这里对话、观察、审计、决策

---

## 3. Core Idea

一个界面，三个区域，一个焦点：

```
┌──────────────────┬──────────────────────────────┬──────────────────────┐
│                  │                              │                      │
│   Agent Lens     │     Interaction View         │   Audit Lens         │
│   (左侧 25%)     │     (中间 50%)               │   (右侧 25%)         │
│                  │                              │                      │
│   agent/session  │  用户输入 → agent 响应        │  动态展示:            │
│   /run/instance  │  tool calls → results        │  - evidence          │
│   树形切换        │  memory proposals            │  - gate status       │
│                  │  confirmation dialogs         │  - checkpoint        │
│   current        │                              │  - memory summary    │
│   historical     │                              │  - event stream      │
│   superseded     │                              │                      │
│   active/paused  │                              │  随 selected lens    │
│   completed/fail │                              │  动态变化             │
│                  │                              │                      │
├──────────────────┴──────────────────────────────┴──────────────────────┤
│  Input Bar / Pending Action / Status Bar                               │
└────────────────────────────────────────────────────────────────────────┘
```

### 3.1 Agent Lens（左侧）

- 展示 agent/session/run/instance 树
- 支持切换 selected lens
- 切换后 Interaction View 和 Audit Lens 同步变化
- 状态标记：current / historical / superseded / active / paused / completed / failed

### 3.2 Interaction View（中间）

- 默认焦点区域
- 对话式交互：用户输入 → agent 响应
- 初期 fake/local gateway，未来 core.chat gateway
- 展示 tool calls、memory proposals、confirmation dialogs
- **不直接执行 tool，不直接写 memory/checkpoint**

### 3.3 Audit Lens（右侧）

- 随 selected lens 动态变化
- 展示 evidence、gate、checkpoint、memory summary、event stream
- 支持 interaction 后 refresh
- xfail/caveat/accepted-with-caveats 状态展示正确

### 3.4 Input Bar / Status Bar（底部）

- 用户输入区域
- 待确认操作提示
- 当前 selected lens 信息
- 连接状态

---

## 4. Innovation

相比 Claude Code / Codex 单 session TUI：

| 维度 | Claude Code / Codex | First Agent Workbench |
|------|---------------------|-----------------------|
| Session 切换 | 单 session | 多 agent/session/run/instance 切换 |
| 审计可见性 | 有限（仅当前对话） | 动态审计随 lens 变化 |
| 交互+审计闭环 | 分离（对话 vs 日志文件） | 同一界面闭环 |
| Agent 状态感知 | 隐式 | 显式 Agent Lens |
| 多实例 | 不支持 | 核心设计目标 |

---

## 5. Safety Boundary

所有写操作必须经过 runtime main path：

```
TUI input
  → runtime gateway (fake/local now, core.chat future)
    → main runtime path
      → ToolRuntimeMediator / Memory / Checkpoint / EventLog
```

**严格禁止**：
- TUI 直接改 memory
- TUI 直接写 checkpoint
- TUI 直接写 event log
- TUI 直接调用 tool
- TUI 构造 runtime result
- TUI 成为第二 runtime

---

## 6. AutoRun Boundary

AutoRun 是 Coding Agent（Claude Code / Codex）开发 First Agent 时使用的工程 workflow/skill，**不是 First Agent 产品本身的核心能力**。

- Phase 5 组件（AutoRunPanel/HardStopOverlay/ReviewPacketPanel）保留为 `provisional dev-only, may be removed`
- 不作为 B8 产品主线
- B8 产品主线：Interaction-first Workbench（本文档方向）

---

## 7. Existing Assets Retained

以下 B8 Phase 1-6A 已交付能力全部保留为 auxiliary panels：

| 能力 | 新位置 | 用途 |
|------|--------|------|
| Evidence Browser | Audit Lens 子面板 | 多实例 evidence 历史 |
| Gate History | Audit Lens 子面板 | 当前 run gate 状态 |
| Audit Log | Audit Lens 子面板 | 命令执行审计 |
| Docs Consistency | Audit Lens 子面板 | 文档一致性检查 |
| Command Shell | 保留为 advanced 功能 | 安全命令执行 |
| Dev Workflow Panel | 保留 dev-only | Coding Agent 工程使用 |

---

## 8. What Changes

| 从 | 到 |
|----|----|
| 7 视图平铺（信息展示中心） | 3 区域聚焦布局（交互优先） |
| Phase = 面板数量 | Milestone = 主入口成熟度 |
| 无交互能力 | Interaction View 为核心 |
| 无 lens 概念 | Agent/Session/Run/Instance Lens |
| 静态数据加载 | 动态审计随 lens 刷新 |
| 审计信息在独立标签页 | 审计信息在交互界面右侧 |
| Roadmap 被 AutoRun 污染 | Roadmap 清晰分为产品主线/dev-only |

---

## 9. Non-goals

- 不做 Web UI
- 不做实时 WebSocket 流
- 不替代 Python runtime
- 不做生产级 multi-tenant
- 不追求 feature completeness
- 不引入数据库
- 不引入新的大型依赖

---

## 10. Decision Required

本文档是 proposal，需要用户确认以下决策后进入 Milestone 规划和实现：

1. **产品方向**：接受 "interaction-first workbench" 替代 "信息展示中心"？
2. **布局方案**：接受 Agent Lens / Interaction View / Audit Lens 三区域布局？
3. **Milestone 方式**：接受按"主入口成熟度"而非"面板数量"定义里程碑？
4. **现有资产**：接受保留 Phase 1-6A 面板为 auxiliary，不丢弃？
5. **AutoRun**：接受 AutoRun 永久 dev-only？
