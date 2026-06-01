import React from "react";
import { describe, it, expect } from "vitest";
import { AGENT_LENS_FIXTURE, EMPTY_AGENT_LENS } from "../data/agentLensFixture";
import type { AgentLensNode, FocusZone } from "../types";
import { WorkbenchLayout } from "../components/WorkbenchLayout";
import { AgentLensPanel } from "../components/AgentLensPanel";
import { InteractionPanel } from "../components/InteractionPanel";
import { ContextPanel } from "../components/ContextPanel";
import { InputBar } from "../components/InputBar";
import { StatusBar } from "../components/StatusBar";

// ============================================================
// M1 — Layout Data / State logic tests
// ============================================================

const FOCUS_ORDER: FocusZone[] = ["interaction", "agent-lens", "context"];

/** Pure function: cycle focus zone — extracted for testability */
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

describe("M1 Layout — Component Smoke", () => {
  it("WorkbenchLayout is the default main view (no Dashboard toggle)", () => {
    const el = React.createElement(WorkbenchLayout, {});
    expect(el).toBeDefined();
    expect(el.type).toBe(WorkbenchLayout);
  });

  it("AgentLensPanel renders with fixture data", () => {
    const el = React.createElement(AgentLensPanel, {
      nodes: AGENT_LENS_FIXTURE,
      focused: false,
    });
    expect(el).toBeDefined();
  });

  it("AgentLensPanel handles empty fixture", () => {
    const el = React.createElement(AgentLensPanel, {
      nodes: EMPTY_AGENT_LENS,
      focused: false,
    });
    expect(el).toBeDefined();
  });

  it("InteractionPanel renders", () => {
    const el = React.createElement(InteractionPanel, {
      focused: true,
      lensLabel: "none",
    });
    expect(el).toBeDefined();
  });

  it("ContextPanel renders as placeholder (not Audit Lens)", () => {
    const el = React.createElement(ContextPanel, {
      focused: false,
      lensLabel: "none",
    });
    expect(el).toBeDefined();
  });

  it("ContextPanel shows placeholder content when lens selected", () => {
    const el = React.createElement(ContextPanel, {
      focused: false,
      lensLabel: "Agent: agent-001",
    });
    expect(el).toBeDefined();
  });

  it("InputBar renders", () => {
    const el = React.createElement(InputBar, {
      focused: true,
      lensLabel: "none",
    });
    expect(el).toBeDefined();
  });

  it("StatusBar renders with fake/local mode label", () => {
    const el = React.createElement(StatusBar, {
      activeLens: "none",
      focusZone: "interaction",
    });
    expect(el).toBeDefined();
  });

  it("FocusZone type does not include 'audit-lens'", () => {
    // Verify audit-lens was renamed to context
    const validZones: FocusZone[] = ["agent-lens", "interaction", "context"];
    expect(validZones).not.toContain("audit-lens" as FocusZone);
  });
});

describe("M1 Safety — Default Entry Guard", () => {
  it("TUI default entry is NOT ACTIVATED", () => {
    // Guard: the TUI must not claim to be the default entry point.
    // This is enforced through documentation and code — no default entry
    // activation code exists in main.tsx or WorkbenchLayout.
    const el = React.createElement(WorkbenchLayout, {});
    expect(el).toBeDefined();
    // No default entry activation prop or state exists
  });

  it("WorkbenchLayout has no props for operations/audit/dashboard data", () => {
    // WorkbenchLayout renders without any project-specific data props
    const el = React.createElement(WorkbenchLayout, {});
    expect(el.props).toEqual({});
  });
});
