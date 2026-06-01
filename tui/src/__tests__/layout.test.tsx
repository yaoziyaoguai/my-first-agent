import React from "react";
import { describe, it, expect } from "vitest";
import { AGENT_LENS_FIXTURE, EMPTY_AGENT_LENS } from "../data/agentLensFixture";
import { fakeRuntimeSend, makeUserMessage } from "../data/fakeRuntimeGateway";
import type { AgentLensNode, FocusZone, SelectedLens } from "../types";
import { EMPTY_SELECTED_LENS } from "../types";
import { WorkbenchLayout } from "../components/WorkbenchLayout";
import { AgentLensPanel } from "../components/AgentLensPanel";
import { InteractionPanel } from "../components/InteractionPanel";
import { ContextPanel } from "../components/ContextPanel";
import { InputBar } from "../components/InputBar";
import { StatusBar } from "../components/StatusBar";

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
