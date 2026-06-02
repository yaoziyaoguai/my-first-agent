/** M8 — Default Entry Readiness Checklist。
 *  评估 TUI 是否可以作为 First Agent 默认入口候选。
 *  所有 blocked 项解除后需用户显式批准。当前 NOT ACTIVATED。 */
export type ReadinessStatus = "done" | "blocked-b8-debt" | "blocked-b7" | "blocked-ime" | "pending";

export interface ReadinessItem {
  id: string;
  label: string;
  description: string;
  status: ReadinessStatus;
}

const STATUS_LABELS: Record<ReadinessStatus, string> = {
  done: "✓ done",
  "blocked-b8-debt": "✗ blocked (B8 deferred)",
  "blocked-b7": "✗ blocked (B7 readiness)",
  "blocked-ime": "✗ blocked (IME/multi-line input)",
  pending: "○ pending",
};

const STATUS_COLORS: Record<ReadinessStatus, string> = {
  done: "green",
  "blocked-b8-debt": "yellow",
  "blocked-b7": "yellow",
  "blocked-ime": "yellow",
  pending: "dim",
};

export function getReadinessItems(): ReadinessItem[] {
  return [
    // ---- Interaction-first Workbench (M1-M4) ----
    {
      id: "R01",
      label: "Interaction-first Workbench 3-zone layout",
      description: "AgentLens(25%) / InteractionView(50%) / Context(25%) + InputBar + StatusBar",
      status: "done",
    },
    {
      id: "R02",
      label: "Agent Lens selection + fixture 树导航",
      description: "agent/session/run/instance 层级树, Tab/Shift+Tab focus cycling",
      status: "done",
    },
    {
      id: "R03",
      label: "Fake/local interaction (M3)",
      description: "FakeRuntimeGateway.send() 关键词匹配响应, InputBar 提交",
      status: "done",
    },
    {
      id: "R04",
      label: "Context Panel interaction refresh (M4)",
      description: "messageCount, lastInteractionTime, pendingCount 动态刷新",
      status: "done",
    },
    // ---- Controlled Interaction (M5) ----
    {
      id: "R05",
      label: "Pending Action / Controlled Interaction (M5)",
      description: "Fake/local PendingAction model + approve/reject via ControlledOperationGateway + PendingActionPanel",
      status: "done",
    },
    // ---- Multi-instance History (M6) ----
    {
      id: "R06",
      label: "EvidenceNamespace contract (M6)",
      description: "8 evidence namespace 定义, MultiRunStorageContract — fake/local, B7 real pending",
      status: "done",
    },
    {
      id: "R07",
      label: "Agent History Index (M6)",
      description: "AgentHistoryIndex + HistorySource + HistoryPanel (fake/local fixture) — 只读 projection",
      status: "done",
    },
    // ---- Runtime Event Stream (M7) ----
    {
      id: "R08",
      label: "EventSourceContract definition (M7)",
      description: "EventSourceContract + redaction + backpressure 策略 — fake/local, B7 real pending",
      status: "done",
    },
    {
      id: "R09",
      label: "EventStreamReader + EventPanel (M7)",
      description: "JSONL parse + malformed/partial write handling + EventPanel — 只读 projection",
      status: "done",
    },
    // ---- Existing auxiliary assets (retained) ----
    {
      id: "R10",
      label: "Auxiliary panels retained",
      description: "Evidence Browser, Gate History, Audit Log, Dev Workflow — 保留为 auxiliary, 不占主界面",
      status: "done",
    },
    {
      id: "R11",
      label: "安全命令执行 (白名单 + confirmation gate)",
      description: "CommandExecutor + ExecutionService + safety gate + audit log — auxiliary only",
      status: "done",
    },
    // ---- Blocked items ----
    {
      id: "R12",
      label: "Multi-instance history (B7 real)",
      description: "真实 evidence namespace + multi-run storage contract 依赖 B7 session/run/instance identity",
      status: "blocked-b7",
    },
    {
      id: "R13",
      label: "Runtime event stream (B7 real)",
      description: "真实 append-only event source contract + tail 依赖 B7 runtime infrastructure",
      status: "blocked-b7",
    },
    {
      id: "R14",
      label: "Chinese IME / multi-line input / paste",
      description: "Ink useInput 中文输入行为待实际终端验证",
      status: "blocked-ime",
    },
    // ---- Gates ----
    {
      id: "R15",
      label: "412/412 tests PASS + tsc clean",
      description: "全量 TUI 测试通过, TypeScript 编译无错误",
      status: "done",
    },
    {
      id: "R16",
      label: "CLI fallback 保留",
      description: "CLI 为显式 fallback, 永不删除",
      status: "done",
    },
    {
      id: "R17",
      label: "TUI default entry NOT ACTIVATED",
      description: "M8 用户显式批准前不激活。所有 blocked 项解除后需用户决策。",
      status: "done",
    },
    {
      id: "R18",
      label: "No second runtime / no real API calls / no .env reads",
      description: "TUI 层面不创建第二 runtime, 不调用真实 API, 不读取 .env",
      status: "done",
    },
  ];
}

export function getReadinessSummary(): {
  done: number;
  blocked: number;
  pending: number;
  total: number;
} {
  const items = getReadinessItems();
  const done = items.filter((i) => i.status === "done").length;
  const blocked = items.filter((i) => i.status.startsWith("blocked")).length;
  const pending = items.filter((i) => i.status === "pending").length;
  return { done, blocked, pending, total: items.length };
}

export { STATUS_LABELS, STATUS_COLORS };
