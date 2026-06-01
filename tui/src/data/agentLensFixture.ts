/** Fake Agent/Session/Run/Instance 树 fixture — M1-M7 开发用 */
import type { AgentLensNode } from "../types";

const NOW = Date.now();

/** M1 fixture: 3 agent, 每个 1-2 sessions, 每个 1-2 runs, 部分有 instance */
export const AGENT_LENS_FIXTURE: AgentLensNode[] = [
  {
    id: "agent-001",
    type: "agent",
    label: "First Agent (main)",
    status: "active",
    children: [
      {
        id: "session-001a",
        type: "session",
        label: `Session ${new Date(NOW - 86400000).toISOString().slice(0, 10)}`,
        status: "completed",
        children: [
          {
            id: "run-001a1",
            type: "run",
            label: "Run #1 — B8 M0 docs",
            status: "completed",
            children: [],
            metadata: { commit: "e9b2f0a", duration: "12min" },
          },
          {
            id: "run-001a2",
            type: "run",
            label: "Run #2 — M1 layout",
            status: "active",
            children: [],
            metadata: { commit: "—", duration: "ongoing" },
          },
        ],
      },
      {
        id: "session-001b",
        type: "session",
        label: `Session ${new Date(NOW - 172800000).toISOString().slice(0, 10)}`,
        status: "completed",
        children: [
          {
            id: "run-001b1",
            type: "run",
            label: "Run #1 — B7 close-out",
            status: "completed",
            children: [],
            metadata: { commit: "cdad13f", duration: "45min" },
          },
        ],
      },
    ],
  },
  {
    id: "agent-002",
    type: "agent",
    label: "Codex (rescue)",
    status: "paused",
    children: [
      {
        id: "session-002a",
        type: "session",
        label: `Session ${new Date(NOW - 259200000).toISOString().slice(0, 10)}`,
        status: "completed",
        children: [
          {
            id: "run-002a1",
            type: "run",
            label: "Run #1 — test_mcp fix",
            status: "completed",
            children: [],
            metadata: { commit: "b015b0b", duration: "8min" },
          },
        ],
      },
    ],
  },
  {
    id: "agent-003",
    type: "agent",
    label: "Explorer (subagent)",
    status: "historical",
    children: [
      {
        id: "session-003a",
        type: "session",
        label: `Session ${new Date(NOW - 432000000).toISOString().slice(0, 10)}`,
        status: "completed",
        children: [
          {
            id: "run-003a1",
            type: "run",
            label: "Run #1 — codebase audit",
            status: "completed",
            children: [],
            metadata: { commit: "917c3b4", duration: "22min" },
          },
          {
            id: "run-003a2",
            type: "run",
            label: "Run #2 — evidence scan",
            status: "completed",
            children: [],
            metadata: { commit: "cfd32c0", duration: "15min" },
          },
        ],
      },
    ],
  },
];

/** 空 fixture — 无 agent/session/run */
export const EMPTY_AGENT_LENS: AgentLensNode[] = [];
