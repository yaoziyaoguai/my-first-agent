# D-04 — Runtime Gateway Foundation SDD

**创建日期**: 2026-06-02
**状态**: DRAFT
**范围**: B8 TUI runtime gateway — fake/local → real 安全边界设计
**Source**: handoff §8 D-04, §9 Route 1

---

## 1. Current State

B8 TUI Interaction View 目前硬依赖 `fakeRuntimeGateway.ts`：

```typescript
// WorkbenchLayout.tsx (现状)
import { fakeRuntimeSend, makeUserMessage, type RuntimeMessage } from "../data/fakeRuntimeGateway";
import { generateFakePendingActions, createFakeGateway, type PendingAction } from "../data/pendingAction";
```

**fakeRuntimeGateway**：keyword-match deterministic fake assistant 响应，不调用任何真实 runtime。
**pendingAction**：keyword-match 生成 fake pending actions，`ControlledOperationGateway` 只做 approve/reject 文本标记。

**问题**：
- 没有 RuntimeGateway 接口/契约
- 直接 import 函数，无法切换 adapter
- 没有 "blocked real mode" 概念
- 如果未来接入真实 core.chat()，需要重写整个 Interaction View

---

## 2. Target Architecture

```
TUI Input
  │
  ▼
RuntimeGateway (interface)
  ├── FakeRuntimeAdapter      ← 当前默认，keyword-match fake
  └── BlockedRealAdapter      ← 真实 runtime shell，返回 explicit blocked result
  │
  ▼
InteractionProjection
  │
  ▼
InteractionPanel / PendingActionPanel / ContextPanel
```

### 2.1 RuntimeGateway Interface

```typescript
interface RuntimeGateway {
  readonly mode: "fake" | "blocked-real" | "real";
  send(input: RuntimeRequest): Promise<RuntimeResponse>;
  approveAction(actionId: string): Promise<ApprovalResult>;
  rejectAction(actionId: string): Promise<ApprovalResult>;
}
```

### 2.2 RuntimeRequest / RuntimeResponse

```typescript
interface RuntimeRequest {
  userInput: string;
  lens: SelectedLens;
  interactionId: string;
}

interface RuntimeResponse {
  interactionId: string;
  messages: InteractionMessage[];
  pendingActions: PendingAction[];
  contextSnapshot: ContextSnapshot | null;
  source: "fake" | "blocked-real" | "real";
}
```

### 2.3 InteractionMessage (SDD-defined, 当前未用)

SDD §3.3 已定义 `InteractionMessage`（含 `toolCalls`、`memoryProposals`），但实战代码只用 `RuntimeMessage`（role+content+timestamp）。本次对齐到 SDD 类型。

---

## 3. Safety Constraints (D-04 SPEC)

1. **TUI 不直接调用 tool** — 所有 tool execution 必须走 `RuntimeGateway` → `ToolRuntimeMediator`
2. **TUI 不直接写 memory/checkpoint/event log** — 所有 write 走 gateway projection
3. **TUI 不绕过 ToolRuntimeMediator** — gateway adapter 不暴露 tool execution 直通路径
4. **当前不调用真实 provider** — blocked real adapter 返回 explicit blocked result
5. **当前不读取 .env** — BlockedRealAdapter 不需要 env
6. **不创建第二 runtime** — gateway 是 projection 层，不是 runtime
7. **fake adapter remains default** — 保持当前用户体验不变

---

## 4. Adapter Design

### 4.1 FakeRuntimeAdapter (DEFAULT)

- 包装现有 `fakeRuntimeSend` + `generateFakePendingActions` + `createFakeGateway`
- 接口实现，非直接 import
- `source: "fake"` 标注

### 4.2 BlockedRealAdapter

- 实现 `RuntimeGateway` 接口
- 所有 `send()` 返回：
  ```typescript
  {
    source: "blocked-real",
    messages: [{
      role: "system",
      content: "Real runtime not configured. Set MY_FIRST_AGENT_RUNTIME_GATEWAY=real in config."
    }],
    pendingActions: [],
    contextSnapshot: null
  }
  ```
- 不读 .env，不调 core.chat()，不调 provider
- `approveAction`/`rejectAction` 返回 no-op blocked 结果

---

## 5. Out of Scope

- 真实 core.chat() adapter（需用户授权 + 真实 provider）
- 真实 provider 调用
- TUI default entry activation
- .env 读取
- 真实 MCP server 连接

---

## 6. Files

| File | Action | Purpose |
|------|--------|---------|
| `tui/src/services/runtimeGateway.ts` | NEW | RuntimeGateway interface + types |
| `tui/src/services/fakeRuntimeAdapter.ts` | NEW | FakeRuntimeAdapter (wraps existing) |
| `tui/src/services/blockedRealAdapter.ts` | NEW | BlockedRealAdapter (explicit blocked result) |
| `tui/src/services/runtimeGateway.ts` | NEW | 统一导出 + factory |
| `tui/src/services/index.ts` | NEW | services barrel export |
| `tui/src/data/fakeRuntimeGateway.ts` | KEEP | 保留为内部实现，不删除 |
| `tui/src/data/pendingAction.ts` | KEEP | 保留，FakeRuntimeAdapter 包装 |
| `tui/src/components/WorkbenchLayout.tsx` | MODIFY | 从 services 导入，不直接 import data |
| `tui/src/__tests__/runtimeGateway.test.ts` | NEW | gateway interface + adapters tests |
| `docs/design/runtime-gateway-foundation-sdd.md` | NEW | 本文档 |

---

## 7. Verification

- FakeRuntimeAdapter produces responses matching current behavior
- BlockedRealAdapter always returns `source: "blocked-real"` with explicit block message
- No .env read in any adapter
- No real API call
- Existing 412 TUI tests still PASS
- tsc typecheck clean
