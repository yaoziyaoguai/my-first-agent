/** Slice B — Safe data sources for wiring into TuiShell。
 *  所有数据来自已知的 safe 状态（docs/evidence/local smoke），不调用真实 runtime。
 *  每个数据项标注来源：fake/local / evidence-derived / docs-derived / local-mcp-smoke。
 */

import type {
  RuntimeDecisionSummary,
  McpStatusData,
  ToolSummaryItem,
  RecentEventItem,
  RuntimeStatusData,
  BottomStatusData,
  TopBarData,
  InspectorStatusData,
  WorkspaceItem,
  ViewLensItem,
  SessionItem,
  MessageBlockData,
  ToolCallBlockData,
  PendingActionBlockData,
  ToolResultTableData,
  ViewLens,
} from "./visualShellTypes";

// ── Source labels（Data Source Policy §4.1） ──

export type DataSourceLabel =
  | "fake/local"
  | "evidence-derived"
  | "docs-derived"
  | "local-mcp-smoke"
  | "blocked:future";

export interface Labeled<T> {
  value: T;
  source: DataSourceLabel;
}

// ── Safe RuntimeDecisionFrame summary ──

export const SAFE_RUNTIME_DECISION: RuntimeDecisionSummary = {
  mode: "ACT",
  status: "partial",
  lastDecision: "see RuntimeDecisionFrame",
};

// ── Safe MCP local smoke status（D-02） ──

export const SAFE_MCP_STATUS: McpStatusData = {
  status: "partial",
  discoverCount: 14,
  invokeReady: true,
};

// ── Safe tool summary ──

export const SAFE_TOOL_SUMMARY: ToolSummaryItem[] = [
  { toolName: "read_file", status: "pass" },
  { toolName: "write_file", status: "pass" },
  { toolName: "grep", status: "pass" },
  { toolName: "glob", status: "pass" },
  { toolName: "execute", status: "idle" },
];

// ── Safe recent events ──

export const SAFE_EVENTS: RecentEventItem[] = [
  { timestamp: "--:--", eventType: "no live events" },
];

// ── Safe memory/checkpoint summary ──

export const SAFE_MEMORY_CKPT = {
  entryCount: 0,
  lastCheckpointId: "—",
};

// ── Safe provider status ──

export const SAFE_PROVIDER_LABEL = "anthropic_compatible [configured]";

// ── Safe runtime status ──

export const SAFE_RUNTIME_STATUS: RuntimeStatusData = {
  runtime: { status: "ok", label: "unified" },
  provider: { status: "ok", label: SAFE_PROVIDER_LABEL },
  tools: { count: 5, ready: 5 },
  mcp: { status: "partial", label: "local smoke" },
};

// ── Safe evidence summary（D-09, 002, 003） ──

export const SAFE_EVIDENCE_ITEMS: string[] = [
  "REAL-EVIDENCE-001: Memory — credible",
  "REAL-EVIDENCE-002: Skill Select — credible (caveats)",
  "REAL-EVIDENCE-003: allowed_tools — credible",
  "REAL-EVIDENCE-004: Checkpoint — credible",
  "REAL-EVIDENCE-005: MCP Bridge — credible",
  "REAL-EVIDENCE-006: SubAgent L1 — credible",
  "REAL-EVIDENCE-007: MCP Invoke — credible-with-caveats",
  "REAL-EVIDENCE-008: Scheduler — credible",
];

// ── Safe D-09 skill evidence summary ──

export const SAFE_SKILL_EVIDENCE = {
  status: "accepted-with-caveats" as const,
  plan3Wired: true,
  nonSteeredPending: true,
  summary: "Plan 3 wired (43/43 PASS). Non-prompt-steered: future real-env task.",
};

// ── Safe bottom status ──

export const SAFE_BOTTOM_STATUS: BottomStatusData = {
  version: "v0.x",
  runtime: "unified",
  mode: "ACT",
  lens: "Agent",
  toolCount: 5,
  mcpStatus: "local smoke",
  provider: SAFE_PROVIDER_LABEL,
};

// ── Safe TopBar ──

export const SAFE_TOP_BAR: TopBarData = {
  productName: "First Agent TUI",
  mode: "ACT",
  lens: "Agent" as ViewLens,
  provider: SAFE_PROVIDER_LABEL,
  isFake: false, // wire safe summary, not pure fixture
};

// ── Safe workspaces（static for now） ──

export const SAFE_WORKSPACES: WorkspaceItem[] = [
  { id: "default", label: "default", status: "active" },
];

// ── Safe lenses ──

export const SAFE_LENSES: ViewLensItem[] = [
  { lens: "Agent", selected: true },
  { lens: "Runtime", selected: false },
  { lens: "Tools", selected: false },
  { lens: "MCP", selected: false },
  { lens: "Evidence", selected: false },
  { lens: "Debug", selected: false },
];

// ── Safe sessions（placeholder — no real runtime） ──

export const SAFE_SESSIONS: SessionItem = {
  agentId: "agent-001",
  agentStatus: "active",
  sessions: [],
};

// ── Safe interaction data（placeholder） ──

export const SAFE_MESSAGES: MessageBlockData[] = [];
export const SAFE_TOOL_CALLS: ToolCallBlockData[] = [];
export const SAFE_PENDING_ACTIONS: PendingActionBlockData[] = [];
export const SAFE_TABLE_RESULTS: ToolResultTableData[] = [];

// ── Safe inspector ──

export function buildSafeInspector(
  runtimeDecision: RuntimeDecisionSummary,
  mcpStatus: McpStatusData,
  toolSummary: ToolSummaryItem[],
  events: RecentEventItem[],
  memoryCkpt: { entryCount: number; lastCheckpointId: string },
  evidenceItemCount: number,
): InspectorStatusData {
  return {
    activeContext: { agentId: "agent-001", runId: "—" },
    runtimeDecision,
    toolSummary,
    mcpBridge: mcpStatus,
    recentEvents: events,
    memory: memoryCkpt,
    evidence: { itemCount: evidenceItemCount },
  };
}
