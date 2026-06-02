/** Slice A — Visual Shell 所有数据类型定义。零 any。 */

/** 视图模式 — 来自 Visual Target §3.5 LensPanel */
export type ViewLens =
  | "Agent"
  | "Runtime"
  | "Tools"
  | "MCP"
  | "Evidence"
  | "Debug";

export const ALL_VIEW_LENSES: ViewLens[] = [
  "Agent",
  "Runtime",
  "Tools",
  "MCP",
  "Evidence",
  "Debug",
];

export const DEFAULT_VIEW_LENS: ViewLens = "Agent";

/** 左侧 Workspace */
export interface WorkspaceItem {
  id: string;
  label: string;
  status: "active" | "idle" | "paused";
}

/** 左侧 View Lens 选项 */
export interface ViewLensItem {
  lens: ViewLens;
  selected: boolean;
}

/** Session/run 树形节点 */
export interface SessionItem {
  agentId: string;
  agentStatus: "active" | "paused" | "historical";
  sessions: {
    sessionId: string;
    sessionStatus: "running" | "historical";
    runs: {
      runId: string;
      runStatus: "running" | "done" | "failed";
    }[];
  }[];
}

/** Runtime 状态摘要 */
export interface RuntimeStatusData {
  runtime: { status: "ok" | "error"; label: string };
  provider: { status: "ok" | "blocked" | "error"; label: string };
  tools: { count: number; ready: number };
  mcp: { status: "ready" | "partial" | "blocked" | "disabled"; label: string };
}

/** MainWorkArea 消息块 */
export interface MessageBlockData {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  timestamp?: string;
}

/** Tool call 块 */
export interface ToolCallBlockData {
  id: string;
  toolName: string;
  args: string;
  result?: string;
  status: "running" | "done" | "failed";
}

/** Pending action 块 */
export interface PendingActionBlockData {
  id: string;
  actionType: string;
  target: string;
  status: "pending" | "approved" | "rejected";
}

/** Tool result table 数据 — Slice B readiness */
export interface ToolResultTableData {
  headers: string[];
  rows: string[][];
  maxRows?: number;
}

/** MCP 状态摘要 */
export interface McpStatusData {
  status: "ready" | "partial" | "blocked" | "disabled";
  discoverCount: number;
  invokeReady: boolean;
}

/** Runtime Decision Frame 摘要 */
export interface RuntimeDecisionSummary {
  mode: string;
  status: "ready" | "partial" | "blocked";
  lastDecision: string;
}

/** Tool summary 条目 */
export interface ToolSummaryItem {
  toolName: string;
  status: "pass" | "pending" | "fail" | "idle";
}

/** Recent event 条目 */
export interface RecentEventItem {
  timestamp: string;
  eventType: string;
}

/** Context Inspector 总数据 */
export interface InspectorStatusData {
  activeContext: { agentId: string; runId: string };
  runtimeDecision: RuntimeDecisionSummary;
  toolSummary: ToolSummaryItem[];
  mcpBridge: McpStatusData;
  recentEvents: RecentEventItem[];
  memory: { entryCount: number; lastCheckpointId: string };
  evidence: {
    itemCount: number;
    /** Evidence item labels (Developer/Evidence lens only) */
    items?: string[];
    /** D-09 skill evidence summary */
    skillEvidence?: {
      status: string;
      summary: string;
    };
  };
}

/** BottomStatusBar 数据 */
export interface BottomStatusData {
  version: string;
  runtime: string;
  mode: string;
  lens: string;
  toolCount: number;
  mcpStatus: string;
  provider: string;
}

/** TopBar 数据 */
export interface TopBarData {
  productName: string;
  mode: string;
  lens: ViewLens;
  provider: string;
  isFake: boolean;
}

/** 完整 Visual Shell fixture 容器 */
export interface VisualShellFixture {
  _label: string;
  topBar: TopBarData;
  workspaces: WorkspaceItem[];
  viewLens: ViewLensItem[];
  sessions: SessionItem;
  runtimeStatus: RuntimeStatusData;
  messages: MessageBlockData[];
  toolCalls: ToolCallBlockData[];
  pendingActions: PendingActionBlockData[];
  tableResults?: ToolResultTableData[];
  inspector: InspectorStatusData;
  bottomStatus: BottomStatusData;
}
