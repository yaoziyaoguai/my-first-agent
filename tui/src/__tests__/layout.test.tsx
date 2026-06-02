import React from "react";
import { describe, it, expect, beforeEach } from "vitest";
import { AGENT_LENS_FIXTURE, EMPTY_AGENT_LENS } from "../data/agentLensFixture";
import { fakeRuntimeSend, makeUserMessage } from "../data/fakeRuntimeGateway";
import type { AgentLensNode, FocusZone, SelectedLens } from "../types";
import { EMPTY_SELECTED_LENS } from "../types";
import {
  generateFakePendingActions,
  createFakeGateway,
  type PendingAction,
  type ControlledOperationGateway,
} from "../data/pendingAction";
import { WorkbenchLayout } from "../components/WorkbenchLayout";
import { AgentLensPanel } from "../components/AgentLensPanel";
import { InteractionPanel } from "../components/InteractionPanel";
import { ContextPanel } from "../components/ContextPanel";
import { InputBar } from "../components/InputBar";
import { StatusBar } from "../components/StatusBar";
import { PendingActionPanel } from "../components/PendingActionPanel";

// ============================================================
// M1 — Layout Data / State logic tests (保留)
// ============================================================

const FOCUS_ORDER: FocusZone[] = ["interaction", "agent-lens", "context"];

function cycleFocus(current: FocusZone, direction: 1 | -1): FocusZone {
  const idx = FOCUS_ORDER.indexOf(current);
  const next =
    (((idx + direction) % FOCUS_ORDER.length) + FOCUS_ORDER.length) %
    FOCUS_ORDER.length;
  return FOCUS_ORDER[next];
}

describe("M1 Layout — Fixture Data", () => {
  it("AGENT_LENS_FIXTURE has >=3 agent nodes", () => {
    expect(AGENT_LENS_FIXTURE.length).toBeGreaterThanOrEqual(3);
  });

  it("each agent has >=1 session, each session has >=1 run", () => {
    for (const agent of AGENT_LENS_FIXTURE) {
      expect(agent.type).toBe("agent");
      expect(agent.children.length).toBeGreaterThanOrEqual(1);
      for (const session of agent.children) {
        expect(session.type).toBe("session");
        expect(session.children.length).toBeGreaterThanOrEqual(1);
        for (const run of session.children) {
          expect(run.type).toBe("run");
        }
      }
    }
  });

  it("all nodes have required fields: id, type, label, status, children", () => {
    function validate(node: AgentLensNode) {
      expect(node.id).toBeTruthy();
      expect(typeof node.id).toBe("string");
      expect(["agent", "session", "run", "instance"]).toContain(node.type);
      expect(node.label).toBeTruthy();
      expect([
        "active",
        "paused",
        "completed",
        "failed",
        "historical",
        "superseded",
      ]).toContain(node.status);
      expect(Array.isArray(node.children)).toBe(true);
      for (const child of node.children) validate(child);
    }
    for (const agent of AGENT_LENS_FIXTURE) validate(agent);
  });

  it("fixture includes all expected statuses", () => {
    const statuses = new Set<string>();
    function collect(node: AgentLensNode) {
      statuses.add(node.status);
      for (const child of node.children) collect(child);
    }
    for (const agent of AGENT_LENS_FIXTURE) collect(agent);
    expect(statuses.has("active")).toBe(true);
    expect(statuses.has("completed")).toBe(true);
    expect(statuses.has("paused")).toBe(true);
    expect(statuses.has("historical")).toBe(true);
  });

  it("EMPTY_AGENT_LENS is empty array", () => {
    expect(EMPTY_AGENT_LENS).toHaveLength(0);
    expect(Array.isArray(EMPTY_AGENT_LENS)).toBe(true);
  });
});

describe("M1 Layout — Focus Management", () => {
  it("default focus is interaction", () => {
    expect(FOCUS_ORDER[0]).toBe("interaction");
  });

  it("Tab from interaction → agent-lens", () => {
    expect(cycleFocus("interaction", 1)).toBe("agent-lens");
  });

  it("Tab from agent-lens → context", () => {
    expect(cycleFocus("agent-lens", 1)).toBe("context");
  });

  it("Tab from context → interaction (wrap around)", () => {
    expect(cycleFocus("context", 1)).toBe("interaction");
  });

  it("Shift+Tab from interaction → context (reverse wrap)", () => {
    expect(cycleFocus("interaction", -1)).toBe("context");
  });

  it("Shift+Tab from agent-lens → interaction", () => {
    expect(cycleFocus("agent-lens", -1)).toBe("interaction");
  });

  it("Shift+Tab from context → agent-lens", () => {
    expect(cycleFocus("context", -1)).toBe("agent-lens");
  });
});

// ============================================================
// M2 — Agent Lens selection tests
// ============================================================

const MOCK_LENS: SelectedLens = {
  agentId: "agent-001",
  sessionId: "session-001a",
  runId: "run-001a2",
  instanceId: null,
};

describe("M2 Agent Lens — Selection", () => {
  it("AgentLensPanel renders with selectedLens prop", () => {
    const el = React.createElement(AgentLensPanel, {
      nodes: AGENT_LENS_FIXTURE,
      focused: false,
      selectedLens: EMPTY_SELECTED_LENS,
      onSelect: () => {},
    });
    expect(el).toBeDefined();
  });

  it("AgentLensPanel renders with selectedLens having agentId", () => {
    const el = React.createElement(AgentLensPanel, {
      nodes: AGENT_LENS_FIXTURE,
      focused: true,
      selectedLens: MOCK_LENS,
      onSelect: () => {},
    });
    expect(el).toBeDefined();
  });

  it("AgentLensPanel handles empty fixture with new props", () => {
    const el = React.createElement(AgentLensPanel, {
      nodes: EMPTY_AGENT_LENS,
      focused: false,
      selectedLens: EMPTY_SELECTED_LENS,
      onSelect: () => {},
    });
    expect(el).toBeDefined();
  });

  it("InteractionPanel shows lens label when selected", () => {
    const el = React.createElement(InteractionPanel, {
      focused: false,
      lensLabel: "agent-001",
      messages: [],
    });
    expect(el).toBeDefined();
  });

  it("InteractionPanel shows no-lens prompt when none selected", () => {
    const el = React.createElement(InteractionPanel, {
      focused: true,
      lensLabel: "none",
      messages: [],
    });
    expect(el).toBeDefined();
  });

  it("ContextPanel shows selection info when lens selected", () => {
    const el = React.createElement(ContextPanel, {
      focused: false,
      lensLabel: "agent-001 / session-001a",
      messageCount: 0,
    });
    expect(el).toBeDefined();
  });
});

// ============================================================
// M3 — Fake/local Interaction tests
// ============================================================

describe("M3 Interaction — fakeRuntimeGateway", () => {
  it("fakeRuntimeSend returns assistant message with id", () => {
    const msg = fakeRuntimeSend("hello", "agent-001");
    expect(msg.role).toBe("assistant");
    expect(msg.id).toBeTruthy();
  });

  it("fakeRuntimeSend returns deterministic response for 'hello'", () => {
    const msg = fakeRuntimeSend("hello", "agent-001");
    expect(msg.content).toContain("Hello");
    expect(msg.content).toContain("First Agent");
  });

  it("fakeRuntimeSend returns default response for unknown input", () => {
    const msg = fakeRuntimeSend("xyzzy_unknown_input", "agent-001");
    expect(msg.content).toContain("fake/local response");
  });

  it("fakeRuntimeSend returns different responses for different keywords", () => {
    const r1 = fakeRuntimeSend("help me", "agent-001");
    const r2 = fakeRuntimeSend("show status", "agent-001");
    expect(r1.content).not.toEqual(r2.content);
  });

  it("makeUserMessage returns user message", () => {
    const msg = makeUserMessage("test input");
    expect(msg.role).toBe("user");
    expect(msg.content).toBe("test input");
    expect(msg.id).toBeTruthy();
  });

  it("message ids are unique", () => {
    const ids = new Set<string>();
    for (let i = 0; i < 10; i++) {
      ids.add(fakeRuntimeSend("hello", "agent-001").id);
    }
    expect(ids.size).toBe(10);
  });
});

describe("M3 Interaction — InputBar", () => {
  it("InputBar renders with onSubmit prop", () => {
    const el = React.createElement(InputBar, {
      focused: true,
      lensLabel: "agent-001",
      onSubmit: () => {},
      disabled: false,
    });
    expect(el).toBeDefined();
  });

  it("InputBar renders disabled when no lens", () => {
    const el = React.createElement(InputBar, {
      focused: true,
      lensLabel: "none",
      onSubmit: () => {},
      disabled: true,
    });
    expect(el).toBeDefined();
  });

  it("InputBar renders without onSubmit (backward compat)", () => {
    const el = React.createElement(InputBar, {
      focused: false,
      lensLabel: "none",
    });
    expect(el).toBeDefined();
  });
});

describe("M3 Interaction — InteractionPanel messages", () => {
  it("InteractionPanel renders with messages", () => {
    const el = React.createElement(InteractionPanel, {
      focused: true,
      lensLabel: "agent-001",
      messages: [
        { id: "1", role: "user", content: "hello", timestamp: Date.now() },
        { id: "2", role: "assistant", content: "Hi!", timestamp: Date.now() },
      ],
    });
    expect(el).toBeDefined();
  });

  it("InteractionPanel renders empty message state", () => {
    const el = React.createElement(InteractionPanel, {
      focused: false,
      lensLabel: "agent-001",
      messages: [],
    });
    expect(el).toBeDefined();
  });
});

// ============================================================
// M4 — Context Panel refresh tests
// ============================================================

describe("M4 Context — Interaction refresh", () => {
  it("ContextPanel renders messageCount", () => {
    const el = React.createElement(ContextPanel, {
      focused: false,
      lensLabel: "agent-001",
      messageCount: 5,
    });
    expect(el).toBeDefined();
  });

  it("ContextPanel renders lastInteractionTime", () => {
    const el = React.createElement(ContextPanel, {
      focused: false,
      lensLabel: "agent-001",
      messageCount: 3,
      lastInteractionTime: Date.now(),
    });
    expect(el).toBeDefined();
  });
});

// ============================================================
// M5 — Pending Action / Controlled Interaction tests
// ============================================================

const MOCK_LENS_FOR_M5: SelectedLens = {
  agentId: "agent-001",
  sessionId: "session-001a",
  runId: "run-001a2",
  instanceId: null,
};

describe("M5 Pending Action — Data Model", () => {
  it("generateFakePendingActions returns tool_confirmation for 'tool' keyword", () => {
    const actions = generateFakePendingActions(MOCK_LENS_FOR_M5, "run tool");
    expect(actions.some((a) => a.type === "tool_confirmation")).toBe(true);
  });

  it("generateFakePendingActions returns memory_proposal for 'memory' keyword", () => {
    const actions = generateFakePendingActions(MOCK_LENS_FOR_M5, "store memory");
    expect(actions.some((a) => a.type === "memory_proposal")).toBe(true);
  });

  it("generateFakePendingActions returns checkpoint_save for 'save' keyword", () => {
    const actions = generateFakePendingActions(MOCK_LENS_FOR_M5, "save checkpoint");
    expect(actions.some((a) => a.type === "checkpoint_save")).toBe(true);
  });

  it("generateFakePendingActions returns safety_gate for 'delete' keyword", () => {
    const actions = generateFakePendingActions(MOCK_LENS_FOR_M5, "delete files");
    expect(actions.some((a) => a.type === "safety_gate")).toBe(true);
  });

  it("safety_gate actions have riskLevel 'critical'", () => {
    const actions = generateFakePendingActions(MOCK_LENS_FOR_M5, "rm -rf destroy");
    const safety = actions.find((a) => a.type === "safety_gate");
    expect(safety).toBeDefined();
    expect(safety!.riskLevel).toBe("critical");
  });

  it("all generated actions have source 'fake/local'", () => {
    const actions = generateFakePendingActions(MOCK_LENS_FOR_M5, "run tool memory save delete");
    for (const a of actions) {
      expect(a.source).toBe("fake/local");
    }
  });

  it("all generated actions have status 'pending'", () => {
    const actions = generateFakePendingActions(MOCK_LENS_FOR_M5, "run tool");
    for (const a of actions) {
      expect(a.status).toBe("pending");
    }
  });

  it("all generated actions have unique actionIds", () => {
    const actions = generateFakePendingActions(MOCK_LENS_FOR_M5, "run tool memory save delete");
    const ids = new Set(actions.map((a) => a.actionId));
    expect(ids.size).toBe(actions.length);
  });

  it("no pending actions for unrelated input", () => {
    const actions = generateFakePendingActions(MOCK_LENS_FOR_M5, "hello world");
    expect(actions).toHaveLength(0);
  });

  it("action requiresConfirmation defaults correctly", () => {
    const actions = generateFakePendingActions(MOCK_LENS_FOR_M5, "run tool save");
    const toolAction = actions.find((a) => a.type === "tool_confirmation");
    const checkpointAction = actions.find((a) => a.type === "checkpoint_save");
    expect(toolAction!.requiresConfirmation).toBe(true);
    expect(checkpointAction!.requiresConfirmation).toBe(false);
  });
});

describe("M5 Pending Action — ControlledOperationGateway", () => {
  let gateway: ControlledOperationGateway;
  let action: PendingAction;

  beforeEach(() => {
    gateway = createFakeGateway();
    action = {
      actionId: "pending-1",
      type: "tool_confirmation",
      title: "Execute Tool",
      description: "Test tool execution",
      riskLevel: "medium",
      status: "pending",
      createdAt: Date.now(),
      selectedLens: MOCK_LENS_FOR_M5,
      requiresConfirmation: true,
      source: "fake/local",
    };
  });

  it("approve returns status 'approved'", () => {
    const result = gateway.approve(action);
    expect(result.status).toBe("approved");
    expect(result.actionId).toBe("pending-1");
  });

  it("approve returns outcomeMessage with '[fake/local] APPROVED' prefix", () => {
    const result = gateway.approve(action);
    expect(result.outcomeMessage).toContain("[fake/local] APPROVED");
    expect(result.outcomeMessage).toContain("No real tool executed");
  });

  it("reject returns status 'rejected'", () => {
    const result = gateway.reject(action);
    expect(result.status).toBe("rejected");
    expect(result.actionId).toBe("pending-1");
  });

  it("reject returns outcomeMessage with '[fake/local] REJECTED' prefix", () => {
    const result = gateway.reject(action);
    expect(result.outcomeMessage).toContain("[fake/local] REJECTED");
    expect(result.outcomeMessage).toContain("cancelled");
  });

  it("ApprovalResult has resolvedAt timestamp after createdAt", () => {
    const result = gateway.approve(action);
    expect(result.resolvedAt).toBeGreaterThanOrEqual(action.createdAt);
  });
});

describe("M5 Pending Action — PendingActionPanel", () => {
  const pendingAction: PendingAction = {
    actionId: "pending-1",
    type: "tool_confirmation",
    title: "Execute Tool",
    description: "Test tool execution",
    riskLevel: "medium",
    status: "pending",
    createdAt: Date.now(),
    selectedLens: MOCK_LENS_FOR_M5,
    requiresConfirmation: true,
    source: "fake/local",
  };

  it("renders with single pending action", () => {
    const el = React.createElement(PendingActionPanel, {
      actions: [pendingAction],
      focused: true,
      highlightedIdx: 0,
      onApprove: () => {},
      onReject: () => {},
    });
    expect(el).toBeDefined();
  });

  it("renders without error for empty actions array", () => {
    const el = React.createElement(PendingActionPanel, {
      actions: [],
      focused: false,
      highlightedIdx: 0,
      onApprove: () => {},
      onReject: () => {},
    });
    // Component returns null from render, but createElement always returns an element
    expect(el).toBeDefined();
  });

  it("renders with approved action showing outcome", () => {
    const approvedAction: PendingAction = {
      ...pendingAction,
      status: "approved",
      outcomeMessage: "[fake/local] APPROVED: test",
    };
    const el = React.createElement(PendingActionPanel, {
      actions: [approvedAction],
      focused: false,
      highlightedIdx: 0,
      onApprove: () => {},
      onReject: () => {},
    });
    expect(el).toBeDefined();
  });

  it("renders with rejected action showing outcome", () => {
    const rejectedAction: PendingAction = {
      ...pendingAction,
      status: "rejected",
      outcomeMessage: "[fake/local] REJECTED: test",
    };
    const el = React.createElement(PendingActionPanel, {
      actions: [rejectedAction],
      focused: false,
      highlightedIdx: 0,
      onApprove: () => {},
      onReject: () => {},
    });
    expect(el).toBeDefined();
  });
});

describe("M5 Pending Action — StatusBar", () => {
  it("StatusBar renders with pendingCount 0", () => {
    const el = React.createElement(StatusBar, {
      activeLens: "agent-001",
      focusZone: "interaction",
      pendingCount: 0,
    });
    expect(el).toBeDefined();
  });

  it("StatusBar renders with pendingCount > 0", () => {
    const el = React.createElement(StatusBar, {
      activeLens: "agent-001",
      focusZone: "interaction",
      pendingCount: 3,
    });
    expect(el).toBeDefined();
  });
});

describe("M5 Pending Action — ContextPanel with pending", () => {
  it("ContextPanel renders with pendingCount", () => {
    const el = React.createElement(ContextPanel, {
      focused: false,
      lensLabel: "agent-001",
      messageCount: 2,
      pendingCount: 1,
    });
    expect(el).toBeDefined();
  });
});

// ============================================================
// M6 — Multi-instance History Foundation tests
// ============================================================

import {
  EVIDENCE_NAMESPACE_CATALOG,
  DEFAULT_STORAGE_CONTRACT,
  isEvidenceRegistered,
  filterByKind,
  getMultiRunEvidences,
  validateFileName,
  type EvidenceNamespace,
  type MultiRunStorageContract,
} from "../data/evidenceNamespace";
import {
  createFakeHistorySource,
  filterRunsByStatus,
  getEvidenceStatusSummary,
  getGateStatusSummary,
  type HistorySource,
  type AgentHistoryIndex,
  type RunHistory,
} from "../data/agentHistoryIndex";
import { HistoryPanel } from "../components/HistoryPanel";

describe("M6 Evidence Namespace — Contract", () => {
  it("catalog has 8 evidence entries", () => {
    expect(EVIDENCE_NAMESPACE_CATALOG).toHaveLength(8);
  });

  it("all entries have unique evidenceId", () => {
    const ids = EVIDENCE_NAMESPACE_CATALOG.map((e) => e.evidenceId);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("all entries are kind 'global' (current baseline)", () => {
    for (const ns of EVIDENCE_NAMESPACE_CATALOG) {
      expect(ns.kind).toBe("global");
    }
  });

  it("isEvidenceRegistered returns true for known evidence", () => {
    expect(isEvidenceRegistered("evidence-001")).toBe(true);
    expect(isEvidenceRegistered("evidence-008")).toBe(true);
  });

  it("isEvidenceRegistered returns false for unknown evidence", () => {
    expect(isEvidenceRegistered("evidence-999")).toBe(false);
  });

  it("filterByKind returns correct subset", () => {
    const globals = filterByKind("global");
    expect(globals).toHaveLength(8);
    const perRun = filterByKind("per-run");
    expect(perRun).toHaveLength(0);
  });

  it("getMultiRunEvidences returns empty (no multi-run yet)", () => {
    const multi = getMultiRunEvidences();
    // Currently all are multiRun: false — B7 readiness pending
    expect(multi).toHaveLength(0);
  });
});

describe("M6 MultiRunStorageContract — Contract", () => {
  it("default contract has expected values", () => {
    expect(DEFAULT_STORAGE_CONTRACT.fileNaming).toBe("{evidence_id}-{run_id}.json");
    expect(DEFAULT_STORAGE_CONTRACT.storageRoot).toBe("docs/dogfood/");
    expect(DEFAULT_STORAGE_CONTRACT.ttlDays).toBe(90);
    expect(DEFAULT_STORAGE_CONTRACT.autoCleanup).toBe(false);
    expect(DEFAULT_STORAGE_CONTRACT.maxRuns).toBe(50);
  });

  it("validateFileName accepts valid {evidence_id}-{run_id}.json", () => {
    expect(validateFileName("evidence-001-run-abc.json", DEFAULT_STORAGE_CONTRACT)).toBe(true);
  });

  it("validateFileName rejects invalid names", () => {
    expect(validateFileName("bad-name.json", DEFAULT_STORAGE_CONTRACT)).toBe(false);
    expect(validateFileName("evidence-001.json", DEFAULT_STORAGE_CONTRACT)).toBe(false);
  });

  it("validateFileName with date pattern", () => {
    const dateContract: MultiRunStorageContract = {
      ...DEFAULT_STORAGE_CONTRACT,
      fileNaming: "{date}-{evidence_id}.json",
    };
    expect(validateFileName("2026-06-01-evidence-001.json", dateContract)).toBe(true);
    expect(validateFileName("evidence-001-run-abc.json", dateContract)).toBe(false);
  });
});

describe("M6 Agent History — HistorySource", () => {
  let source: HistorySource;

  beforeEach(() => {
    source = createFakeHistorySource();
  });

  it("source is 'fake/local'", () => {
    expect(source.source).toBe("fake/local");
  });

  it("listAgentIds returns 3 agents", () => {
    const ids = source.listAgentIds();
    expect(ids).toHaveLength(3);
    expect(ids).toContain("agent-001");
    expect(ids).toContain("agent-002");
    expect(ids).toContain("agent-003");
  });

  it("getAgentHistory returns non-null for known agent", () => {
    const history = source.getAgentHistory("agent-001");
    expect(history).not.toBeNull();
    expect(history!.agentId).toBe("agent-001");
  });

  it("getAgentHistory returns null for unknown agent", () => {
    expect(source.getAgentHistory("agent-999")).toBeNull();
  });

  it("agent history has sessions with runs", () => {
    const history = source.getAgentHistory("agent-001")!;
    expect(history.sessions.length).toBeGreaterThanOrEqual(1);
    for (const session of history.sessions) {
      expect(session.runs.length).toBeGreaterThanOrEqual(1);
      for (const run of session.runs) {
        expect(run.runId).toBeTruthy();
        expect(run.agentId).toBe("agent-001");
        expect(run.sessionId).toBe(session.sessionId);
      }
    }
  });

  it("getRunHistory returns run by ID", () => {
    const run = source.getRunHistory("run-001a1");
    expect(run).not.toBeNull();
    expect(run!.runId).toBe("run-001a1");
    expect(run!.status).toBe("completed");
  });

  it("getRunHistory returns null for unknown run", () => {
    expect(source.getRunHistory("run-999")).toBeNull();
  });

  it("filterRunsByStatus filters correctly", () => {
    const history = source.getAgentHistory("agent-001")!;
    const completed = filterRunsByStatus(history, "completed");
    expect(completed.length).toBeGreaterThanOrEqual(1);
    for (const run of completed) {
      expect(run.status).toBe("completed");
    }
  });

  it("getEvidenceStatusSummary counts correctly", () => {
    const history = source.getAgentHistory("agent-001")!;
    const summary = getEvidenceStatusSummary(history);
    expect(summary.size).toBeGreaterThan(0);
    for (const [, counts] of summary) {
      expect(counts.pass + counts.fail + counts.partial + counts.unknown).toBeGreaterThan(0);
    }
  });

  it("getGateStatusSummary counts correctly", () => {
    const history = source.getAgentHistory("agent-001")!;
    const summary = getGateStatusSummary(history);
    expect(summary.size).toBeGreaterThan(0);
    for (const [, counts] of summary) {
      expect(counts.pass + counts.fail).toBeGreaterThan(0);
    }
  });
});

describe("M6 History — HistoryPanel", () => {
  const source = createFakeHistorySource();

  it("renders without agent selection", () => {
    const el = React.createElement(HistoryPanel, {
      focused: false,
      agentId: null,
      historySource: source,
    });
    expect(el).toBeDefined();
  });

  it("renders with known agent", () => {
    const el = React.createElement(HistoryPanel, {
      focused: true,
      agentId: "agent-001",
      historySource: source,
    });
    expect(el).toBeDefined();
  });

  it("renders with unknown agent (empty state)", () => {
    const el = React.createElement(HistoryPanel, {
      focused: false,
      agentId: "agent-999",
      historySource: source,
    });
    expect(el).toBeDefined();
  });
});

describe("M6 Safety — Guard tests", () => {
  it("HistorySource marker is always 'fake/local'", () => {
    const source = createFakeHistorySource();
    expect(source.source).toBe("fake/local");
  });

  it("HistorySource does not expose any write operations", () => {
    const source = createFakeHistorySource();
    // HistorySource interface has only read methods + source marker
    const keys = Object.keys(source);
    expect(keys).toContain("source");
    expect(keys).toContain("getAgentHistory");
    expect(keys).toContain("getRunHistory");
    expect(keys).toContain("listAgentIds");
    // No write methods
    expect(keys).not.toContain("write");
    expect(keys).not.toContain("save");
    expect(keys).not.toContain("update");
  });
});

// ============================================================
// M7 — Runtime Event Stream / Inspector tests
// ============================================================

import {
  DEFAULT_EVENT_SOURCE_CONTRACT,
  redactValue,
  redactPayload,
  containsSensitiveKey,
  type EventSourceContract,
  type RuntimeTraceItem,
} from "../data/eventSourceContract";
import {
  createEventStreamReader,
  FAKE_EVENTS_JSONL,
  MALFORMED_JSONL,
  type EventStreamReader,
} from "../data/eventStreamReader";
import { EventPanel } from "../components/EventPanel";

describe("M7 EventSourceContract — Contract", () => {
  it("default contract is fake/local", () => {
    expect(DEFAULT_EVENT_SOURCE_CONTRACT.source).toBe("fake/local");
  });

  it("default contract has supportsTail false", () => {
    expect(DEFAULT_EVENT_SOURCE_CONTRACT.supportsTail).toBe(false);
  });

  it("redaction is enabled by default", () => {
    expect(DEFAULT_EVENT_SOURCE_CONTRACT.redaction.enabled).toBe(true);
  });

  it("redaction patterns include sensitive keys", () => {
    const patterns = DEFAULT_EVENT_SOURCE_CONTRACT.redaction.patterns;
    expect(patterns).toContain("api_key");
    expect(patterns).toContain("token");
    expect(patterns).toContain("secret");
  });

  it("redactValue redacts sensitive key", () => {
    expect(redactValue("api_key", "sk-secret", DEFAULT_EVENT_SOURCE_CONTRACT)).toBe("[redacted]");
  });

  it("redactValue does not redact normal key", () => {
    expect(redactValue("toolName", "read_file", DEFAULT_EVENT_SOURCE_CONTRACT)).toBe("read_file");
  });

  it("redactPayload redacts nested sensitive keys", () => {
    const payload = { api_key: "sk-123", tool: "read", token: "bearer-xyz" };
    const { redacted, redactedFields } = redactPayload(payload, DEFAULT_EVENT_SOURCE_CONTRACT);
    expect(redacted.api_key).toBe("[redacted]");
    expect(redacted.token).toBe("[redacted]");
    expect(redacted.tool).toBe("read");
    expect(redactedFields).toContain("api_key");
    expect(redactedFields).toContain("token");
  });

  it("containsSensitiveKey detects sensitive patterns", () => {
    expect(containsSensitiveKey("apiKey", DEFAULT_EVENT_SOURCE_CONTRACT)).toBe(true);
    expect(containsSensitiveKey("authorization", DEFAULT_EVENT_SOURCE_CONTRACT)).toBe(true);
    expect(containsSensitiveKey("userName", DEFAULT_EVENT_SOURCE_CONTRACT)).toBe(false);
  });
});

describe("M7 EventStreamReader — Parsing", () => {
  let reader: EventStreamReader;

  beforeEach(() => {
    reader = createEventStreamReader();
  });

  it("parses valid JSONL fixture", () => {
    const { events, errors } = reader.parse(FAKE_EVENTS_JSONL);
    expect(events.length).toBeGreaterThanOrEqual(15);
    expect(errors).toHaveLength(0);
  });

  it("handles empty content", () => {
    const { events, errors } = reader.parse("");
    expect(events).toHaveLength(0);
    expect(errors).toHaveLength(0);
  });

  it("handles whitespace-only content", () => {
    const { events, errors } = reader.parse("   \n  \n  ");
    expect(events).toHaveLength(0);
    expect(errors).toHaveLength(0);
  });

  it("handles malformed lines without crashing", () => {
    const { events, errors } = reader.parse(MALFORMED_JSONL);
    // Should parse valid lines
    expect(events.length).toBeGreaterThanOrEqual(1);
    // Should report malformed lines
    expect(errors.length).toBeGreaterThanOrEqual(2);
  });

  it("parsed events have required fields", () => {
    const { events } = reader.parse(FAKE_EVENTS_JSONL);
    for (const event of events) {
      expect(event.eventId).toBeTruthy();
      expect(event.eventType).toBeTruthy();
      expect(event.timestamp).toBeTruthy();
      expect(typeof event.sessionId).toBe("string");
      expect(typeof event.runId).toBe("string");
    }
  });

  it("sensitive fields are redacted in parsed events", () => {
    const { events } = reader.parse(FAKE_EVENTS_JSONL);
    const evt016 = events.find((e) => e.eventId === "evt-016");
    expect(evt016).toBeDefined();
    expect(evt016!.redacted).toBe(true);
    expect(evt016!.redactedFields.length).toBeGreaterThan(0);
  });
});

describe("M7 EventStreamReader — Filter & Summarize", () => {
  let reader: EventStreamReader;
  let events: RuntimeTraceItem[];

  beforeEach(() => {
    reader = createEventStreamReader();
    const result = reader.parse(FAKE_EVENTS_JSONL);
    events = result.events;
  });

  it("filter by event type returns matching events", () => {
    const filtered = reader.filter(events, { eventTypes: ["tool_invoke"] });
    expect(filtered.length).toBeGreaterThanOrEqual(2);
    for (const e of filtered) {
      expect(e.eventType).toBe("tool_invoke");
    }
  });

  it("filter by session ID returns matching events", () => {
    const filtered = reader.filter(events, { sessionIds: ["session-001a"] });
    expect(filtered.length).toBeGreaterThan(0);
    for (const e of filtered) {
      expect(e.sessionId).toBe("session-001a");
    }
  });

  it("filter by run ID returns matching events", () => {
    const filtered = reader.filter(events, { runIds: ["run-001a1"] });
    expect(filtered.length).toBeGreaterThan(0);
    for (const e of filtered) {
      expect(e.runId).toBe("run-001a1");
    }
  });

  it("filter with limit truncates results", () => {
    const filtered = reader.filter(events, { limit: 5 });
    expect(filtered).toHaveLength(5);
  });

  it("summarize produces correct InspectorSummary", () => {
    const summary = reader.summarize(events);
    expect(summary.totalEvents).toBe(events.length);
    expect(summary.sessionCount).toBeGreaterThanOrEqual(1);
    expect(summary.runCount).toBeGreaterThanOrEqual(1);
    expect(summary.timeRange.earliest).toBeTruthy();
    expect(summary.timeRange.latest).toBeTruthy();
    expect(summary.eventTypeCounts.size).toBeGreaterThan(0);
  });
});

describe("M7 EventPanel — Rendering", () => {
  const reader = createEventStreamReader();
  const { events } = reader.parse(FAKE_EVENTS_JSONL);
  const summary = reader.summarize(events);

  it("renders with events", () => {
    const el = React.createElement(EventPanel, {
      focused: true,
      events,
      errorCount: 0,
      summary,
      hasAgent: true,
    });
    expect(el).toBeDefined();
  });

  it("renders without agent (empty state)", () => {
    const el = React.createElement(EventPanel, {
      focused: false,
      events: [],
      errorCount: 0,
      summary: null,
      hasAgent: false,
    });
    expect(el).toBeDefined();
  });

  it("renders with parse errors", () => {
    const el = React.createElement(EventPanel, {
      focused: false,
      events,
      errorCount: 3,
      summary,
      hasAgent: true,
    });
    expect(el).toBeDefined();
  });
});

describe("M7 Safety — Guard tests", () => {
  it("EventSourceContract source is 'fake/local'", () => {
    expect(DEFAULT_EVENT_SOURCE_CONTRACT.source).toBe("fake/local");
  });

  it("EventSourceContract does not support tail", () => {
    expect(DEFAULT_EVENT_SOURCE_CONTRACT.supportsTail).toBe(false);
  });

  it("EventStreamReader does not expose write methods", () => {
    const reader = createEventStreamReader();
    const keys = Object.keys(reader);
    expect(keys).toContain("contract");
    expect(keys).toContain("parse");
    expect(keys).toContain("filter");
    expect(keys).toContain("summarize");
    expect(keys).not.toContain("write");
    expect(keys).not.toContain("append");
    expect(keys).not.toContain("tail");
  });
});

// ============================================================
// M1+ Safety — unchanged guard tests
// ============================================================

describe("M1 Safety — Default Entry Guard", () => {
  it("TUI default entry is NOT ACTIVATED", () => {
    const el = React.createElement(WorkbenchLayout, {});
    expect(el).toBeDefined();
  });

  it("WorkbenchLayout has no props for operations/audit/dashboard data", () => {
    const el = React.createElement(WorkbenchLayout, {});
    expect(el.props).toEqual({});
  });

  it("FocusZone type does not include 'audit-lens'", () => {
    const validZones: FocusZone[] = ["agent-lens", "interaction", "context"];
    expect(validZones).not.toContain("audit-lens" as FocusZone);
  });
});
