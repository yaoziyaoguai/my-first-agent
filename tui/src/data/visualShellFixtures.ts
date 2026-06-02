/** Slice A — 所有 22 组件的 [fake/local] 静态 mock 数据。
 *  Slice B — 导出 adapter-built SAFE_DATA_FIXTURE。 */
import type {
  VisualShellFixture,
  WorkspaceItem,
  ViewLensItem,
  SessionItem,
  RuntimeStatusData,
  MessageBlockData,
  ToolCallBlockData,
  PendingActionBlockData,
  ToolResultTableData,
  InspectorStatusData,
  BottomStatusData,
  TopBarData,
} from "./visualShellTypes";
import { buildVisualShellViewModel } from "./visualShellDataAdapter";
import {
  SAFE_RUNTIME_DECISION,
  SAFE_MCP_STATUS,
  SAFE_TOOL_SUMMARY,
  SAFE_EVENTS,
  SAFE_MEMORY_CKPT,
  SAFE_PROVIDER_LABEL,
  SAFE_RUNTIME_STATUS,
  SAFE_BOTTOM_STATUS,
  SAFE_TOP_BAR,
  SAFE_WORKSPACES,
  SAFE_LENSES,
  SAFE_SESSIONS,
  SAFE_MESSAGES,
  SAFE_TOOL_CALLS,
  SAFE_PENDING_ACTIONS,
  SAFE_TABLE_RESULTS,
  SAFE_EVIDENCE_ITEMS,
  SAFE_SKILL_EVIDENCE,
} from "./safeDataSources";

export const MOCK_TOP_BAR: TopBarData = {
  productName: "First Agent TUI",
  mode: "ACT",
  lens: "Agent",
  provider: "fake/local",
  isFake: true,
};

export const MOCK_WORKSPACES: WorkspaceItem[] = [
  { id: "default", label: "default", status: "active" },
  { id: "project-a", label: "project-a", status: "idle" },
];

export const MOCK_VIEW_LENSES: ViewLensItem[] = [
  { lens: "Agent", selected: true },
  { lens: "Runtime", selected: false },
  { lens: "Tools", selected: false },
  { lens: "MCP", selected: false },
  { lens: "Evidence", selected: false },
  { lens: "Debug", selected: false },
];

export const MOCK_SESSIONS: SessionItem = {
  agentId: "agent-001",
  agentStatus: "active",
  sessions: [
    {
      sessionId: "session-abc",
      sessionStatus: "running",
      runs: [
        { runId: "run-001", runStatus: "done" },
        { runId: "run-002", runStatus: "running" },
      ],
    },
    {
      sessionId: "session-def",
      sessionStatus: "historical",
      runs: [{ runId: "run-003", runStatus: "failed" }],
    },
  ],
};

export const MOCK_RUNTIME_STATUS: RuntimeStatusData = {
  runtime: { status: "ok", label: "unified" },
  provider: { status: "ok", label: "fake/local" },
  tools: { count: 5, ready: 3 },
  mcp: { status: "partial", label: "mcp: partial" },
};

export const MOCK_MESSAGES: MessageBlockData[] = [
  {
    id: "msg-001",
    role: "user",
    content: "hey, can you check the config?",
    timestamp: "12:03",
  },
  {
    id: "msg-002",
    role: "assistant",
    content: "I'll look at the config file and check for issues.",
    timestamp: "12:03",
  },
];

export const MOCK_TOOL_CALLS: ToolCallBlockData[] = [
  {
    id: "tc-001",
    toolName: "read_file",
    args: "./src/config.ts",
    result: "42 lines, no syntax errors",
    status: "done",
  },
];

export const MOCK_PENDING_ACTIONS: PendingActionBlockData[] = [
  {
    id: "pa-001",
    actionType: "TOOL",
    target: "write_file — ./src/config.ts",
    status: "pending",
  },
];

export const MOCK_INSPECTOR: InspectorStatusData = {
  activeContext: { agentId: "agent-001", runId: "run-002" },
  runtimeDecision: {
    mode: "ACT",
    status: "ready",
    lastDecision: "allowed",
  },
  toolSummary: [
    { toolName: "read_file", status: "pass" },
    { toolName: "write_file", status: "pending" },
    { toolName: "grep", status: "idle" },
  ],
  mcpBridge: {
    status: "partial",
    discoverCount: 3,
    invokeReady: true,
  },
  recentEvents: [
    { timestamp: "12:03", eventType: "run start" },
    { timestamp: "12:04", eventType: "tool call" },
    { timestamp: "12:04", eventType: "result" },
  ],
  memory: { entryCount: 12, lastCheckpointId: "ck-004" },
  evidence: { itemCount: 8 },
};

export const MOCK_TABLE_RESULTS: ToolResultTableData[] = [
  {
    headers: ["Field", "Value"],
    rows: [
      ["status", "ok"],
      ["provider", "fake/local"],
      ["tools", "5"],
    ],
  },
  {
    headers: ["Tool", "Count", "Status"],
    rows: [
      ["read_file", "3", "pass"],
      ["write_file", "1", "pending"],
      ["grep", "0", "idle"],
    ],
    maxRows: 5,
  },
];

export const MOCK_BOTTOM_STATUS: BottomStatusData = {
  version: "v0.x",
  runtime: "unified",
  mode: "ACT",
  lens: "Agent",
  toolCount: 3,
  mcpStatus: "partial",
  provider: "fake/local",
};

export const FULL_FIXTURE: VisualShellFixture = {
  _label: "[fake/local fixture]",
  topBar: MOCK_TOP_BAR,
  workspaces: MOCK_WORKSPACES,
  viewLens: MOCK_VIEW_LENSES,
  sessions: MOCK_SESSIONS,
  runtimeStatus: MOCK_RUNTIME_STATUS,
  messages: MOCK_MESSAGES,
  toolCalls: MOCK_TOOL_CALLS,
  pendingActions: MOCK_PENDING_ACTIONS,
  tableResults: MOCK_TABLE_RESULTS,
  inspector: MOCK_INSPECTOR,
  bottomStatus: MOCK_BOTTOM_STATUS,
};

/** 空状态 fixture — 用于 edge state 测试 */
export const EMPTY_FIXTURE: VisualShellFixture = {
  _label: "[fake/local fixture]",
  topBar: { ...MOCK_TOP_BAR, lens: "Agent" },
  workspaces: [],
  viewLens: MOCK_VIEW_LENSES.map((l) => ({
    ...l,
    selected: l.lens === "Agent",
  })),
  sessions: {
    agentId: "",
    agentStatus: "historical",
    sessions: [],
  },
  runtimeStatus: {
    runtime: { status: "ok", label: "unified" },
    provider: { status: "blocked", label: "none" },
    tools: { count: 0, ready: 0 },
    mcp: { status: "disabled", label: "mcp: disabled" },
  },
  messages: [],
  toolCalls: [],
  pendingActions: [],
  tableResults: [],
  inspector: {
    activeContext: { agentId: "—", runId: "—" },
    runtimeDecision: {
      mode: "ACT",
      status: "partial",
      lastDecision: "—",
    },
    toolSummary: [],
    mcpBridge: {
      status: "disabled",
      discoverCount: 0,
      invokeReady: false,
    },
    recentEvents: [],
    memory: { entryCount: 0, lastCheckpointId: "—" },
    evidence: { itemCount: 0 },
  },
  bottomStatus: {
    ...MOCK_BOTTOM_STATUS,
    toolCount: 0,
    mcpStatus: "disabled",
    provider: "none",
  },
};

/** Slice B — adapter-built fixture from safe data sources。
 *  _label: "[safe data — not product-ready]"
 *  provenance 通过 view model 暴露。 */
const SAFE_VIEW_MODEL = buildVisualShellViewModel({
  lens: "Agent",
  runtimeDecision: SAFE_RUNTIME_DECISION,
  mcpStatus: SAFE_MCP_STATUS,
  toolSummary: SAFE_TOOL_SUMMARY,
  events: SAFE_EVENTS,
  memoryCkpt: SAFE_MEMORY_CKPT,
  evidenceItemCount: SAFE_EVIDENCE_ITEMS.length,
  evidenceItems: SAFE_EVIDENCE_ITEMS,
  providerLabel: SAFE_PROVIDER_LABEL,
  runtimeStatus: SAFE_RUNTIME_STATUS,
  bottomStatus: SAFE_BOTTOM_STATUS,
  topBar: SAFE_TOP_BAR,
  workspaces: SAFE_WORKSPACES,
  lenses: SAFE_LENSES,
  sessions: SAFE_SESSIONS,
  messages: SAFE_MESSAGES,
  toolCalls: SAFE_TOOL_CALLS,
  pendingActions: SAFE_PENDING_ACTIONS,
  tableResults: SAFE_TABLE_RESULTS,
  skillEvidence: SAFE_SKILL_EVIDENCE,
});

export const SAFE_DATA_FIXTURE: VisualShellFixture = SAFE_VIEW_MODEL.fixture;
export const SAFE_DATA_PROVENANCE = SAFE_VIEW_MODEL.provenance;
