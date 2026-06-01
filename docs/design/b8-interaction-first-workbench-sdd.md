# B8 Interaction-first Workbench — SDD

**创建日期**: 2026-06-02
**状态**: DRAFT — 待配套 TDD Plan
**依赖文档**:
- `docs/proposals/b8-interaction-first-workbench-proposal.md`
- `docs/milestones/b8-interaction-first-workbench-milestones.md`
**取代**: `docs/design/b8-ts-tui-workbench-sdd.md`（旧"信息展示中心"方向，归档为历史参考）

---

## 1. Product Position

B8 = First Agent Interaction-first Workbench。First Agent 是一个**通用 Agent Runtime/Workbench**，不是 coding-engine 项目管理工具。

TUI 默认布局为三区域聚焦布局：Agent Lens (25%) / Interaction View (50%) / Context Panel (25%)。Interaction View 是默认焦点区域。

**所有 Operation / AutoRun / Project dashboard / Audit 展示均为 PAUSED，不产品化。** 右侧面板为通用 Context/Inspector placeholder（mock/static），不叫 Audit Lens。

---

## 1.5 Product Boundary

### 1.5.1 B8 Interaction-first Workbench MVP（当前范围）

| 能力 | 状态 | 说明 |
|------|------|------|
| Agent Lens | M1 fixture data | agent/session/run/instance 树形选择 |
| Interaction View | M1 placeholder | 用户 ↔ agent 对话区域 |
| Context Panel | M1 mock/static | 通用 Context/Inspector placeholder |
| Input Bar | M1 基础输入 | 文本输入区域 |
| Status Bar | M1 状态栏 | lens/focus/mode 信息 |

### 1.5.2 PAUSED — 不产品化

以下内容**全部 PAUSED**，不在 WorkbenchLayout 中渲染，不作为产品功能开发：

- PROJECT_STATUS / PROGRESS_LEDGER 解析和展示
- dogfood results / review packet / gate history
- technical debt / docs consistency
- AutoRun / HardStop / Dev Workflow 面板
- command catalog / safety model 面板
- evidence / gate / checkpoint / memory / event 审计面板
- Dashboard.tsx 整页切换（旧 7 视图工作台）
- 所有 project-specific operations 展示

这些是 First Agent 项目自身的工程运维数据，不是 First Agent 通用产品的功能。后续如需产品化，重新设计为通用模型。

### 1.5.3 Legacy Dashboard

`tui/src/components/Dashboard.tsx` 保留在磁盘上但不被 import 或渲染。它是旧 7 视图工作台实现，已归档。

---

## 2. Layout Architecture

### 2.1 顶层布局

```
┌──────────────────┬──────────────────────────────┬──────────────────────┐
│                  │                              │                      │
│   Agent Lens     │     Interaction View         │   Context Panel      │
│   (左侧 25%)     │     (中间 50%)               │   (右侧 25%)         │
│                  │                              │                      │
│   agent/session  │  用户输入 → agent 响应        │  mock/static:        │
│   /run/instance  │  tool calls → results        │  - Selection         │
│   树形切换        │  memory proposals            │  - Tool Calls        │
│                  │  confirmation dialogs         │  - Memory            │
│   current        │                              │  - Checkpoint        │
│   historical     │                              │  - Safety            │
│   superseded     │                              │                      │
│   active/paused  │                              │  通用 placeholder    │
│   completed/fail │                              │  pending generic     │
│                  │                              │  model               │
├──────────────────┴──────────────────────────────┴──────────────────────┤
│  Input Bar / Status Bar                                                │
└────────────────────────────────────────────────────────────────────────┘
```

### 2.2 组件树 (当前 M1)

```
WorkbenchLayout
├── AgentLensPanel
│   └── AgentLensNode (递归树节点)
├── InteractionPanel (placeholder)
├── ContextPanel (mock/static placeholder)
├── InputBar
└── StatusBar
```

### 2.3 焦点管理

| 区域 | 默认焦点 | 切换方式 |
|------|---------|---------|
| Interaction | **是** (default) | Tab |
| Agent Lens | 否 | Tab |
| Context | 否 | Tab |

- 默认焦点在 Interaction 区域
- Tab 键在 interaction → agent-lens → context 三区域间循环切换
- Shift+Tab 反向循环
- 在 AgentLens 内 ↑↓ 导航树节点，Enter 选中 (M2+)
- `q` 退出

### 2.4 Existing Auxiliary Panels — PAUSED

旧 7 视图（Overview/EvidenceStatus/Workflow/Commands/Tasks/Gates/Docs）和所有 project-specific operations 面板**全部 PAUSED**，不渲染。Dashboard.tsx 保留在磁盘但不被 import。

---

## 3. Data Model

### 3.1 Agent Lens

```typescript
type AgentLensNodeType = "agent" | "session" | "run" | "instance";

type AgentLensNodeStatus =
  | "active"
  | "paused"
  | "completed"
  | "failed"
  | "historical"
  | "superseded";

interface AgentLensNode {
  id: string;
  type: AgentLensNodeType;
  label: string;
  status: AgentLensNodeStatus;
  children: AgentLensNode[];
  metadata?: Record<string, string>;
}
```

### 3.2 Selected Lens

```typescript
interface SelectedLens {
  agentId: string | null;
  sessionId: string | null;
  runId: string | null;
  instanceId: string | null;
}

/** 空 selected lens — 未选中任何对象 */
const EMPTY_SELECTED_LENS: SelectedLens = {
  agentId: null,
  sessionId: null,
  runId: null,
  instanceId: null,
};
```

### 3.3 Interaction Message

```typescript
type InteractionRole = "user" | "agent" | "system";

interface InteractionMessage {
  id: string;
  role: InteractionRole;
  content: string;
  timestamp: number;
  toolCalls?: ToolCallRecord[];
  memoryProposals?: MemoryProposal[];
}

interface ToolCallRecord {
  toolName: string;
  parameters: Record<string, unknown>;
  result?: string;
  gateStatus: "allowed" | "blocked" | "requires_confirmation";
}

interface MemoryProposal {
  type: "store" | "update" | "delete";
  key: string;
  value?: string;
  status: "pending" | "approved" | "rejected";
}
```

### 3.4 Pending Action (M5)

```typescript
type PendingActionType = "tool_confirmation" | "memory_proposal";

type PendingActionStatus = "pending" | "approved" | "rejected";

interface PendingAction {
  id: string;
  actionType: PendingActionType;
  toolName?: string;
  parameters?: Record<string, unknown>;
  memoryProposal?: MemoryProposal;
  timestamp: number;
  status: PendingActionStatus;
}
```

### 3.5 Audit Snapshot (M4)

```typescript
interface AuditSnapshot {
  lens: SelectedLens;
  evidence: EvidenceSummary[];
  gate: GateStatusSummary;
  checkpoint: CheckpointSummary | null;
  memory: MemorySummary;
  events: EventRecord[];  // M7 前为空数组
}

interface EvidenceSummary {
  id: string;
  type: string;
  verdict: string;
  status: "pass" | "fail" | "xfail" | "caveat" | "accepted-with-caveats";
  summary: string;
}

interface GateStatusSummary {
  totalGates: number;
  passed: number;
  failed: number;
  xfail: number;
}

interface CheckpointSummary {
  lastCheckpointId: string | null;
  lastCheckpointTime: number | null;
}

interface MemorySummary {
  totalEntries: number;
  recentKeys: string[];
}
```

### 3.6 Event Record (M7)

```typescript
interface EventRecord {
  timestamp: number;
  type: string;
  sessionId?: string;
  runId?: string;
  instanceId?: string;
  data: Record<string, unknown>;
  redactedFields?: string[];
}
```

---

## 4. Runtime Gateway Boundary

### 4.1 接口定义

```typescript
interface RuntimeGateway {
  send(input: string, lens: SelectedLens): Promise<InteractionResponse>;
  approve(actionId: string): Promise<ApprovalResult>;
  reject(actionId: string): Promise<ApprovalResult>;
}

interface InteractionResponse {
  messages: InteractionMessage[];
  pendingActions: PendingAction[];
  auditDelta: Partial<AuditSnapshot>;
}

interface ApprovalResult {
  actionId: string;
  status: "approved" | "rejected";
  result?: string;
}
```

### 4.2 数据流

```
TUI InputBar
  → RuntimeGateway.send(input, selectedLens)
    → (M3) FakeRuntimeGateway: deterministic fake 响应
    → (future) CoreChatGateway: core.chat() main path
      → ToolRuntimeMediator / Memory / Checkpoint / EventLog
  → InteractionView 渲染响应
  → AuditLens 刷新
```

### 4.3 FakeRuntimeGateway (M3)

- 返回 deterministic fake 响应
- 模拟 agent 回复 + tool call + memory proposal
- 不访问 .env / 真实 API / 真实文件系统（除 fixture 数据）
- 用于 M3-M7 开发验证，M8 前不替换

### 4.4 严格禁止

- TUI 直接改 memory
- TUI 直接写 checkpoint
- TUI 直接写 event log
- TUI 直接调用 tool
- TUI 构造 runtime result
- TUI 成为第二 runtime
- InputBar 绕过 RuntimeGateway.send() 直接操作

---

## 5. Dynamic Audit Refresh (M4)

### 5.1 刷新触发条件

| 触发 | 行为 |
|------|------|
| selectedLens 变化 | AuditLens 重新加载所有子面板数据 |
| Interaction 完成（收到 response） | AuditLens 自动或手动 refresh |
| 用户手动 refresh（keybinding） | AuditLens 重新加载 |

### 5.2 数据源映射

| Audit 子面板 | M0-M3 数据源 | M4+ 数据源 |
|-------------|-------------|-----------|
| Evidence | 现有 evidenceBrowser 数据模型，按 selectedLens 筛选 | DynamicAuditState 管理映射 |
| Gate | 现有 gateHistory 数据模型 | 同左 |
| Checkpoint | fake/local fixture | MultiRunStorageContract (M6) |
| Memory | fake/local fixture | MemorySummary projection |
| Event | 空 | events.jsonl reader (M7) |

### 5.3 xfail/caveat 展示规则

- xfail 状态展示为 `xfail`（不是 `pass`）
- caveat 文本完整展示
- accepted-with-caveats 标注为 `accepted-with-caveats`（不是 `pass`）
- 不把 xfail 当 pass 计入统计

### 5.4 Auxiliary Source Kind 规则

以下 source_kind 作为 auxiliary evidence，不参与主语义得分：
- `memory_index`
- `user_profile`

可评分 source_kind：
- `stored_memory`, `retrieved_memory`, `chunk`, `summary`, `generated_answer`

---

## 6. Safety

### 6.1 编译时安全

- `child_process.exec` / `execSync` / `spawn` 在 interaction 路径中不可达
- 所有外部交互通过 `RuntimeGateway` 接口
- `FakeRuntimeGateway` 不访问文件系统、网络、环境变量

### 6.2 运行时安全

- 不读取 `.env`
- 不调用真实 API
- 不执行 shell 命令
- `RuntimeGateway` 是 TUI 的唯一外部交互边界

### 6.3 Redaction (M7)

- EventRecord 中脱敏字段标注 `[redacted]`
- Redaction 策略在 EventSourceContract 中定义

---

## 7. PAUSED — Operations & Project Management Displays

### 7.1 声明

以下内容**全部 PAUSED，不产品化**。它们不属于 First Agent 通用 Workbench 的产品核心：

- PROJECT_STATUS / PROGRESS_LEDGER 解析展示
- dogfood results / review packet / gate history
- technical debt / docs consistency
- AutoRun / HardStop / Dev Workflow 面板
- command catalog / safety model 面板
- evidence / gate / checkpoint / memory / event 审计面板
- Dashboard.tsx（旧 7 视图工作台，保留在磁盘但不 import）

这些是 First Agent 项目自身的工程运维数据，不是 First Agent 通用产品的功能。

### 7.2 Legacy Dashboard

`Dashboard.tsx` 保留在磁盘上但不被任何组件 import 或渲染。不提供整页切换 hotkey。

---

## 8. Default Entry Strategy

### 8.1 原则

- M0-M7 期间 **default entry NOT ACTIVATED**
- M8 评估 readiness，用户显式批准后才激活
- 不自动激活

### 8.2 M8 Readiness Checklist

- [ ] Interaction view 可用
- [ ] Input/paste/IME 基础检查通过
- [ ] q 退出，CLI fallback 正常
- [ ] 安全扫描通过（no secret leak）
- [ ] Runtime bypass guard tests PASS
- [ ] 用户显式确认激活

### 8.3 CLI 保留

- CLI (`python main.py`) 永不被删除
- TUI 出问题时 CLI 始终作为 fallback
- TUI 激活 default entry 后 CLI 仍可用

---

## 9. Technology Constraints

延续旧 SDD 的技术决策：

| 决策 | 选择 |
|------|------|
| Runtime | Node.js v20+ (TypeScript 5.x) |
| TUI 框架 | Ink 5 + React 18 |
| 构建工具 | tsx |
| 测试框架 | Vitest |
| 外部依赖 | 不引入数据库、HTTP server、WebSocket、新的大型依赖 |

---

## 10. Project Structure (当前 M1)

```
tui/
├── src/
│   ├── main.tsx                        # 入口: render(<WorkbenchLayout />)
│   ├── components/
│   │   ├── WorkbenchLayout.tsx         # 顶层三区域布局 (M1)
│   │   ├── AgentLensPanel.tsx          # Agent/Session/Run/Instance 树 (M1)
│   │   ├── InteractionPanel.tsx        # 对话展示区域 placeholder (M1)
│   │   ├── ContextPanel.tsx            # 通用 Context/Inspector placeholder (M1)
│   │   ├── InputBar.tsx               # 底部输入区域 (M1)
│   │   └── StatusBar.tsx              # 底部状态栏 (M1)
│   ├── data/
│   │   └── agentLensFixture.ts         # Fake agent/session/run 树 (M1)
│   ├── types.ts                        # AgentLensNode, SelectedLens, FocusZone
│   └── __tests__/
│       └── layout.test.tsx             # 23 tests (M1)
└── package.json
```

---

## 11. 版本历史

| 日期 | 变更 |
|------|------|
| 2026-06-02 | 初始版本 — interaction-first 架构，替代旧 b8-ts-tui-workbench-sdd.md |
| 2026-06-02 | Product Boundary Reconciliation (Rounds 1-3) — 移除 Project Operations Lens 概念；Audit Lens → Context Panel；所有 Operations/AutoRun/Project dashboard 标记 PAUSED |
