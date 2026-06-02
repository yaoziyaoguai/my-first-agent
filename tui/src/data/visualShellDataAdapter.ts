/** Slice B — Data adapter: safe data sources → VisualShellFixture。
 *  read-only，可测试，显式标注 data provenance。
 *
 *  不调 runtime，不读 .env，不写 memory/checkpoint/event。
 */

import type {
  VisualShellFixture,
  ViewLens,
  RuntimeDecisionSummary,
  McpStatusData,
  ToolSummaryItem,
  RecentEventItem,
  RuntimeStatusData,
  BottomStatusData,
  TopBarData,
  WorkspaceItem,
  ViewLensItem,
  SessionItem,
  MessageBlockData,
  ToolCallBlockData,
  PendingActionBlockData,
  ToolResultTableData,
  InspectorStatusData,
} from "./visualShellTypes";

// ── Adapter input（safe data sources） ──

export interface SafeDataSources {
  /** selected lens */
  lens: ViewLens;
  /** runtime decision frame summary */
  runtimeDecision: RuntimeDecisionSummary;
  /** MCP bridge status */
  mcpStatus: McpStatusData;
  /** tool summary */
  toolSummary: ToolSummaryItem[];
  /** recent events */
  events: RecentEventItem[];
  /** memory/checkpoint summary */
  memoryCkpt: { entryCount: number; lastCheckpointId: string };
  /** evidence item count */
  evidenceItemCount: number;
  /** evidence detail items（Developer/Evidence lens） */
  evidenceItems?: string[];
  /** provider label */
  providerLabel: string;
  /** runtime status */
  runtimeStatus: RuntimeStatusData;
  /** bottom status */
  bottomStatus: BottomStatusData;
  /** top bar */
  topBar: TopBarData;
  /** workspaces */
  workspaces: WorkspaceItem[];
  /** lenses */
  lenses: ViewLensItem[];
  /** sessions */
  sessions: SessionItem;
  /** interaction messages */
  messages: MessageBlockData[];
  /** tool calls */
  toolCalls: ToolCallBlockData[];
  /** pending actions */
  pendingActions: PendingActionBlockData[];
  /** table results */
  tableResults: ToolResultTableData[];
  /** D-09 skill evidence summary */
  skillEvidence?: {
    status: string;
    summary: string;
  };
}

// ── Adapter output ──

export interface VisualShellViewModel {
  fixture: VisualShellFixture;
  /** data provenance metadata */
  provenance: {
    runtimeDecision: "fake/local";
    mcpStatus: "local-mcp-smoke";
    toolSummary: "fake/local";
    events: "fake/local";
    memoryCkpt: "fake/local";
    evidence: "evidence-derived";
    provider: "docs-derived";
    sessions: "fake/local";
    messages: "fake/local";
    skillEvidence: "evidence-derived" | "fake/local";
  };
}

// ── Adapter ──

export function buildVisualShellViewModel(
  sources: SafeDataSources,
): VisualShellViewModel {
  const inspector = buildInspectorFromSources(sources);

  const fixture: VisualShellFixture = {
    _label: "[safe data — not product-ready]",
    topBar: sources.topBar,
    workspaces: sources.workspaces,
    viewLens: sources.lenses,
    sessions: sources.sessions,
    runtimeStatus: sources.runtimeStatus,
    messages: sources.messages,
    toolCalls: sources.toolCalls,
    pendingActions: sources.pendingActions,
    tableResults:
      sources.tableResults.length > 0 ? sources.tableResults : undefined,
    inspector,
    bottomStatus: sources.bottomStatus,
  };

  return {
    fixture,
    provenance: {
      runtimeDecision: "fake/local",
      mcpStatus: "local-mcp-smoke",
      toolSummary: "fake/local",
      events: "fake/local",
      memoryCkpt: "fake/local",
      evidence: "evidence-derived",
      provider: "docs-derived",
      sessions: "fake/local",
      messages: "fake/local",
      skillEvidence: sources.skillEvidence
        ? "evidence-derived"
        : "fake/local",
    },
  };
}

function buildInspectorFromSources(
  sources: SafeDataSources,
): InspectorStatusData {
  return {
    activeContext: {
      agentId: "agent-001",
      runId: "—",
    },
    runtimeDecision: sources.runtimeDecision,
    toolSummary: sources.toolSummary,
    mcpBridge: sources.mcpStatus,
    recentEvents: sources.events,
    memory: sources.memoryCkpt,
    evidence: {
      itemCount: sources.evidenceItemCount,
      items: sources.evidenceItems,
      skillEvidence: sources.skillEvidence,
    },
  };
}

// ── Convenience: build from defaults ──

export function buildDefaultViewModel(
  overrides?: Partial<SafeDataSources>,
): VisualShellViewModel {
  const defaults: SafeDataSources = {
    lens: "Agent" as ViewLens,
    runtimeDecision: {
      mode: "ACT",
      status: "partial",
      lastDecision: "—",
    },
    mcpStatus: {
      status: "disabled",
      discoverCount: 0,
      invokeReady: false,
    },
    toolSummary: [],
    events: [],
    memoryCkpt: { entryCount: 0, lastCheckpointId: "—" },
    evidenceItemCount: 0,
    providerLabel: "none",
    runtimeStatus: {
      runtime: { status: "ok", label: "unified" },
      provider: { status: "blocked", label: "none" },
      tools: { count: 0, ready: 0 },
      mcp: { status: "disabled", label: "disabled" },
    },
    bottomStatus: {
      version: "v0.x",
      runtime: "unified",
      mode: "ACT",
      lens: "Agent",
      toolCount: 0,
      mcpStatus: "disabled",
      provider: "none",
    },
    topBar: {
      productName: "First Agent TUI",
      mode: "ACT",
      lens: "Agent" as ViewLens,
      provider: "none",
      isFake: true,
    },
    workspaces: [],
    lenses: [
      { lens: "Agent", selected: true },
      { lens: "Runtime", selected: false },
      { lens: "Tools", selected: false },
      { lens: "MCP", selected: false },
      { lens: "Evidence", selected: false },
      { lens: "Debug", selected: false },
    ],
    sessions: {
      agentId: "",
      agentStatus: "historical",
      sessions: [],
    },
    messages: [],
    toolCalls: [],
    pendingActions: [],
    tableResults: [],
  };

  const merged = { ...defaults, ...overrides };
  return buildVisualShellViewModel(merged);
}
