/** Slice A — 所有 22 组件的 [fake/local] 静态 mock 数据。 */
import type {
  VisualShellFixture,
  WorkspaceItem,
  ViewLensItem,
  SessionItem,
  RuntimeStatusData,
  MessageBlockData,
  ToolCallBlockData,
  PendingActionBlockData,
  InspectorStatusData,
  BottomStatusData,
  TopBarData,
} from "./visualShellTypes";

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
