/** M6 — Agent History Index（mock/local 实现）。
 *  基于 fixture 数据构建 agent/session/run 历史索引。
 *  只读 projection，不写 runtime state。
 *  真实 B7 multi-instance identity 就绪后替换为 filesystem scan。 */

/** 历史 run 的 evidence/gate 摘要 */
export interface RunEvidenceSummary {
  evidenceId: string;
  status: "pass" | "fail" | "partial" | "unknown";
  /** dogfood report 中的关键发现 */
  summary: string;
}

export interface RunGateSummary {
  gateId: string;
  status: "pass" | "fail";
  /** gate 名称，如 "ruff", "pytest", "tsc" */
  label: string;
}

/** 单个 run 的完整历史记录 */
export interface RunHistory {
  runId: string;
  sessionId: string;
  agentId: string;
  /** 该 run 创建时间 */
  createdAt: number;
  /** run 状态 */
  status: "active" | "completed" | "failed" | "paused";
  /** 该 run 下的 evidence 摘要列表 */
  evidenceSummaries: RunEvidenceSummary[];
  /** 该 run 下的 gate 摘要列表 */
  gateSummaries: RunGateSummary[];
  /** commit hash 关联 */
  commitHash: string | null;
}

/** 单个 session 的历史记录 */
export interface SessionHistory {
  sessionId: string;
  agentId: string;
  label: string;
  runs: RunHistory[];
}

/** Agent 的完整历史记录 */
export interface AgentHistoryIndex {
  agentId: string;
  label: string;
  sessions: SessionHistory[];
}

/** HistorySource — 历史数据源接口。
 *  M6 使用 fake/local fixture source。
 *  未来 B7 就绪后替换为 filesystem scan source。 */
export interface HistorySource {
  /** 获取指定 agent 的完整历史索引 */
  getAgentHistory(agentId: string): AgentHistoryIndex | null;
  /** 按 run ID 获取 run 历史 */
  getRunHistory(runId: string): RunHistory | null;
  /** 列出所有已知 agent 的 ID */
  listAgentIds(): string[];
  /** 历史源类型（明确标注 fake/local） */
  source: "fake/local";
}

// ============================================================
// Fake/local fixture data
// ============================================================

const FAKE_RUN_HISTORY_1A1: RunHistory = {
  runId: "run-001a1",
  sessionId: "session-001a",
  agentId: "agent-001",
  createdAt: Date.now() - 7 * 86400000,
  status: "completed",
  evidenceSummaries: [
    { evidenceId: "evidence-001", status: "pass", summary: "Provider config validated successfully" },
    { evidenceId: "evidence-002", status: "pass", summary: "Core loop runtime E2E pass" },
  ],
  gateSummaries: [
    { gateId: "gate-ruff", status: "pass", label: "ruff" },
    { gateId: "gate-pytest", status: "pass", label: "pytest" },
  ],
  commitHash: "abc1234",
};

const FAKE_RUN_HISTORY_1A2: RunHistory = {
  runId: "run-001a2",
  sessionId: "session-001a",
  agentId: "agent-001",
  createdAt: Date.now() - 3 * 86400000,
  status: "completed",
  evidenceSummaries: [
    { evidenceId: "evidence-003", status: "pass", summary: "Memory subsystem validated" },
    { evidenceId: "evidence-004", status: "partial", summary: "Checkpoint: 2/3 cases pass" },
  ],
  gateSummaries: [
    { gateId: "gate-ruff", status: "pass", label: "ruff" },
    { gateId: "gate-pytest", status: "pass", label: "pytest" },
    { gateId: "gate-tsc", status: "pass", label: "tsc" },
  ],
  commitHash: "def5678",
};

const FAKE_RUN_HISTORY_2A1: RunHistory = {
  runId: "run-002a1",
  sessionId: "session-002a",
  agentId: "agent-002",
  createdAt: Date.now() - 5 * 86400000,
  status: "failed",
  evidenceSummaries: [
    { evidenceId: "evidence-001", status: "fail", summary: "Provider config: API key missing" },
    { evidenceId: "evidence-005", status: "unknown", summary: "MCP: not tested in this run" },
  ],
  gateSummaries: [
    { gateId: "gate-ruff", status: "pass", label: "ruff" },
    { gateId: "gate-pytest", status: "fail", label: "pytest" },
  ],
  commitHash: "ghi9012",
};

const FAKE_RUN_HISTORY_3P1: RunHistory = {
  runId: "run-003p1",
  sessionId: "session-003p",
  agentId: "agent-003",
  createdAt: Date.now() - 14 * 86400000,
  status: "completed",
  evidenceSummaries: [
    { evidenceId: "evidence-006", status: "pass", summary: "Skill subsystem: all L3 tests pass" },
    { evidenceId: "evidence-007", status: "pass", summary: "Tool subsystem: all L3 tests pass" },
  ],
  gateSummaries: [
    { gateId: "gate-ruff", status: "pass", label: "ruff" },
    { gateId: "gate-pytest", status: "pass", label: "pytest" },
    { gateId: "gate-tsc", status: "pass", label: "tsc" },
  ],
  commitHash: "jkl3456",
};

/** Fake/local agent history index — 基于 fixture 数据 */
const FAKE_AGENT_HISTORIES: AgentHistoryIndex[] = [
  {
    agentId: "agent-001",
    label: "First Agent v1 (production)",
    sessions: [
      {
        sessionId: "session-001a",
        agentId: "agent-001",
        label: "Core Development Session",
        runs: [FAKE_RUN_HISTORY_1A1, FAKE_RUN_HISTORY_1A2],
      },
    ],
  },
  {
    agentId: "agent-002",
    label: "Test Agent v2 (staging)",
    sessions: [
      {
        sessionId: "session-002a",
        agentId: "agent-002",
        label: "Staging Test Session",
        runs: [FAKE_RUN_HISTORY_2A1],
      },
    ],
  },
  {
    agentId: "agent-003",
    label: "Legacy Agent v0 (historical)",
    sessions: [
      {
        sessionId: "session-003p",
        agentId: "agent-003",
        label: "Legacy Production Session",
        runs: [FAKE_RUN_HISTORY_3P1],
      },
    ],
  },
];

// ============================================================
// Fake HistorySource 实现
// ============================================================

/** 创建 fake/local HistorySource。
 *  基于 fixture 数据，不访问 filesystem，不读取 .env。 */
export function createFakeHistorySource(): HistorySource {
  const agentMap = new Map<string, AgentHistoryIndex>();
  const runMap = new Map<string, RunHistory>();

  for (const agentHistory of FAKE_AGENT_HISTORIES) {
    agentMap.set(agentHistory.agentId, agentHistory);
    for (const session of agentHistory.sessions) {
      for (const run of session.runs) {
        runMap.set(run.runId, run);
      }
    }
  }

  return {
    source: "fake/local",

    getAgentHistory(agentId: string): AgentHistoryIndex | null {
      return agentMap.get(agentId) ?? null;
    },

    getRunHistory(runId: string): RunHistory | null {
      return runMap.get(runId) ?? null;
    },

    listAgentIds(): string[] {
      return Array.from(agentMap.keys());
    },
  };
}

/** 按 run 状态过滤历史 */
export function filterRunsByStatus(
  history: AgentHistoryIndex,
  status: RunHistory["status"],
): RunHistory[] {
  const result: RunHistory[] = [];
  for (const session of history.sessions) {
    for (const run of session.runs) {
      if (run.status === status) {
        result.push(run);
      }
    }
  }
  return result;
}

/** 获取 agent 历史中所有 evidence 的状态汇总 */
export function getEvidenceStatusSummary(
  history: AgentHistoryIndex,
): Map<string, { pass: number; fail: number; partial: number; unknown: number }> {
  const summary = new Map<string, { pass: number; fail: number; partial: number; unknown: number }>();
  for (const session of history.sessions) {
    for (const run of session.runs) {
      for (const ev of run.evidenceSummaries) {
        if (!summary.has(ev.evidenceId)) {
          summary.set(ev.evidenceId, { pass: 0, fail: 0, partial: 0, unknown: 0 });
        }
        const counts = summary.get(ev.evidenceId)!;
        counts[ev.status]++;
      }
    }
  }
  return summary;
}

/** 获取 agent 历史中所有 gate 的状态汇总 */
export function getGateStatusSummary(
  history: AgentHistoryIndex,
): Map<string, { pass: number; fail: number }> {
  const summary = new Map<string, { pass: number; fail: number }>();
  for (const session of history.sessions) {
    for (const run of session.runs) {
      for (const gate of run.gateSummaries) {
        if (!summary.has(gate.gateId)) {
          summary.set(gate.gateId, { pass: 0, fail: 0 });
        }
        const counts = summary.get(gate.gateId)!;
        counts[gate.status]++;
      }
    }
  }
  return summary;
}
