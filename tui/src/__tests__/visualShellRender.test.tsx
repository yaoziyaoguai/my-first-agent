/**
 * Slice A — Visual Shell render smoke tests.
 * 确保所有区域和关键组件能正常渲染，不崩溃。
 */
import { describe, test, expect } from "vitest";
import React from "react";
import { render } from "ink-testing-library";
import { TuiShell } from "../components/shell/TuiShell";
import { TuiTopBar } from "../components/shell/TuiTopBar";
import { BottomStatusBar } from "../components/shell/BottomStatusBar";
import { LeftRail } from "../components/shell/LeftRail";
import { MainWorkArea } from "../components/work-area/MainWorkArea";
import { InputDock } from "../components/input/InputDock";
import { ContextInspectorPanel } from "../components/inspector/ContextInspectorPanel";
import {
  FULL_FIXTURE,
  EMPTY_FIXTURE,
  MOCK_TOP_BAR,
  MOCK_WORKSPACES,
  MOCK_VIEW_LENSES,
  MOCK_SESSIONS,
  MOCK_RUNTIME_STATUS,
  MOCK_MESSAGES,
  MOCK_TOOL_CALLS,
  MOCK_PENDING_ACTIONS,
  MOCK_INSPECTOR,
  MOCK_BOTTOM_STATUS,
  MOCK_TABLE_RESULTS,
} from "../data/visualShellFixtures";

// ── TuiShell render tests ──

describe("TuiShell render", () => {
  test("renders 6 zones without crash", () => {
    const { lastFrame } = render(
      <TuiShell fixture={FULL_FIXTURE} width={120} height={36} />,
    );
    expect(lastFrame()).toBeTruthy();
    expect(typeof lastFrame()).toBe("string");
  });

  test("renders with compact width", () => {
    const { lastFrame } = render(
      <TuiShell fixture={FULL_FIXTURE} width={79} height={30} />,
    );
    expect(lastFrame()).toBeTruthy();
    expect(lastFrame()).toContain("compact");
  });

  test("renders empty fixture without crash", () => {
    const { lastFrame } = render(
      <TuiShell fixture={EMPTY_FIXTURE} width={120} height={36} />,
    );
    expect(lastFrame()).toBeTruthy();
    expect(lastFrame()).toContain("no messages yet");
    expect(lastFrame()).toContain("no agents");
  });

  test("default lens is Agent, not Evidence", () => {
    const { lastFrame } = render(
      <TuiShell fixture={FULL_FIXTURE} width={120} height={36} />,
    );
    const output = lastFrame();
    // Evidence details should NOT be visible in default Agent lens
    expect(output).not.toContain("Evidence Snapshot");
    // Should show the collapsed evidence summary instead
    expect(output).toContain("evidence:");
  });

  test("[fake/local] labels visible", () => {
    const { lastFrame } = render(
      <TuiShell fixture={FULL_FIXTURE} width={120} height={36} />,
    );
    expect(lastFrame()).toContain("fake/local");
  });
});

// ── TopBar tests ──

describe("TuiTopBar", () => {
  test("renders product name", () => {
    const { lastFrame } = render(
      <TuiTopBar data={MOCK_TOP_BAR} width={120} />,
    );
    expect(lastFrame()).toContain("First Agent TUI");
  });

  test("renders mode/lens/provider chips", () => {
    const { lastFrame } = render(
      <TuiTopBar data={MOCK_TOP_BAR} width={120} />,
    );
    expect(lastFrame()).toContain("Mode: ACT");
    expect(lastFrame()).toContain("Lens: Agent");
    expect(lastFrame()).toContain("fake/local");
  });
});

// ── BottomStatusBar tests ──

describe("BottomStatusBar", () => {
  test("renders global status", () => {
    const { lastFrame } = render(
      <BottomStatusBar
        data={MOCK_BOTTOM_STATUS}
        width={120}
        evidenceLens={false}
      />,
    );
    expect(lastFrame()).toContain("v0.x");
    expect(lastFrame()).toContain("lens: Agent");
    expect(lastFrame()).toContain("q: quit");
  });

  test("shows [EVIDENCE] tag when evidence lens active", () => {
    const { lastFrame } = render(
      <BottomStatusBar
        data={MOCK_BOTTOM_STATUS}
        width={120}
        evidenceLens={true}
      />,
    );
    expect(lastFrame()).toContain("[EVIDENCE]");
  });
});

// ── LeftRail tests ──

describe("LeftRail", () => {
  test("renders all 5 sub-panels", () => {
    const { lastFrame } = render(
      <LeftRail
        width={28}
        height={36}
        workspaces={MOCK_WORKSPACES}
        viewLenses={MOCK_VIEW_LENSES}
        sessions={MOCK_SESSIONS}
        runtimeStatus={MOCK_RUNTIME_STATUS}
        fakeLabel="[fake/local fixture]"
      />,
    );
    expect(lastFrame()).toContain("Workspaces");
    expect(lastFrame()).toContain("Lenses");
    expect(lastFrame()).toContain("Sessions");
    expect(lastFrame()).toContain("Status");
    expect(lastFrame()).toContain("Keys");
  });

  test("shows fake/local label", () => {
    const { lastFrame } = render(
      <LeftRail
        width={28}
        height={36}
        workspaces={MOCK_WORKSPACES}
        viewLenses={MOCK_VIEW_LENSES}
        sessions={MOCK_SESSIONS}
        runtimeStatus={MOCK_RUNTIME_STATUS}
        fakeLabel="[fake/local fixture]"
      />,
    );
    expect(lastFrame()).toContain("[fake/local fixture]");
  });
});

// ── MainWorkArea tests ──

describe("MainWorkArea", () => {
  test("renders messages and tool calls", () => {
    const { lastFrame } = render(
      <MainWorkArea
        width={56}
        messages={MOCK_MESSAGES}
        toolCalls={MOCK_TOOL_CALLS}
        pendingActions={MOCK_PENDING_ACTIONS}
        fakeLabel="[fake/local fixture]"
      />,
    );
    expect(lastFrame()).toContain("hey, can you check the config?");
    expect(lastFrame()).toContain("[TOOL]");
    expect(lastFrame()).toContain("read_file");
    expect(lastFrame()).toContain("Enter: approve");
  });

  test("renders empty state placeholder", () => {
    const { lastFrame } = render(
      <MainWorkArea
        width={56}
        messages={[]}
        toolCalls={[]}
        pendingActions={[]}
        fakeLabel="[fake/local fixture]"
      />,
    );
    expect(lastFrame()).toContain("no messages yet");
  });

  test("renders tool result table blocks", () => {
    const { lastFrame } = render(
      <MainWorkArea
        width={56}
        messages={[]}
        toolCalls={[]}
        pendingActions={[]}
        tableResults={MOCK_TABLE_RESULTS}
        fakeLabel="[fake/local fixture]"
      />,
    );
    const output = lastFrame();
    expect(output).toContain("Field");
    expect(output).toContain("Value");
    expect(output).toContain("status");
    expect(output).toContain("provider");
  });

  test("table results still empty when omitted", () => {
    const { lastFrame } = render(
      <MainWorkArea
        width={56}
        messages={[]}
        toolCalls={[]}
        pendingActions={[]}
        fakeLabel="[fake/local fixture]"
      />,
    );
    expect(lastFrame()).toContain("no messages yet");
  });
});

// ── InputDock tests ──

describe("InputDock", () => {
  test("renders input area with input value", () => {
    const { lastFrame } = render(
      <InputDock width={56} inputValue="test input" isFake={true} />,
    );
    expect(lastFrame()).toContain("test input");
    expect(lastFrame()).toContain("[fake/local]");
  });

  test("renders command chips", () => {
    const { lastFrame } = render(
      <InputDock width={56} isFake={false} />,
    );
    expect(lastFrame()).toContain("/ask");
    expect(lastFrame()).toContain("/help");
  });
});

// ── RightInspector tests ──

describe("ContextInspectorPanel", () => {
  test("renders all sub-panels", () => {
    const { lastFrame } = render(
      <ContextInspectorPanel
        width={36}
        height={36}
        data={MOCK_INSPECTOR}
        evidenceLens={false}
        fakeLabel="[fake/local fixture]"
      />,
    );
    expect(lastFrame()).toContain("Active Context");
    expect(lastFrame()).toContain("Runtime Frame");
    expect(lastFrame()).toContain("Tool Summary");
    expect(lastFrame()).toContain("MCP Bridge");
    expect(lastFrame()).toContain("Events");
    expect(lastFrame()).toContain("Memory / CKPT");
  });

  test("Evidence lens is not default — shows collapsed summary", () => {
    const { lastFrame } = render(
      <ContextInspectorPanel
        width={36}
        height={36}
        data={MOCK_INSPECTOR}
        evidenceLens={false}
        fakeLabel="[fake/local fixture]"
      />,
    );
    expect(lastFrame()).not.toContain("Evidence Snapshot");
    expect(lastFrame()).toContain("evidence:");
  });

  test("Evidence lens shows full snapshot when active", () => {
    const { lastFrame } = render(
      <ContextInspectorPanel
        width={36}
        height={36}
        data={MOCK_INSPECTOR}
        evidenceLens={true}
        fakeLabel="[fake/local fixture]"
      />,
    );
    expect(lastFrame()).toContain("Evidence Snapshot");
  });
});

// ── Slice B — safe data fixture integration tests ──

import {
  SAFE_DATA_FIXTURE,
} from "../data/visualShellFixtures";

describe("TuiShell safe data fixture", () => {
  test("SAFE_DATA_FIXTURE renders all 6 zones", () => {
    const { lastFrame } = render(
      <TuiShell fixture={SAFE_DATA_FIXTURE} width={120} height={36} />,
    );
    const output = lastFrame();
    expect(output).toBeTruthy();
    expect(output).toContain("First Agent TUI");
    // evidence: 8 items appears in the 1-line collapsed summary
    expect(output).toContain("evidence:");
  });

  test("SAFE_DATA_FIXTURE shows safe data label, not fake/local fixture", () => {
    const { lastFrame } = render(
      <TuiShell fixture={SAFE_DATA_FIXTURE} width={120} height={36} />,
    );
    const output = lastFrame();
    expect(output).toContain("[safe data — not product-ready]");
    expect(output).not.toContain("[fake/local fixture]");
  });

  test("SAFE_DATA_FIXTURE MCP bridge shows 14 tools from local smoke", () => {
    const { lastFrame } = render(
      <TuiShell fixture={SAFE_DATA_FIXTURE} width={120} height={36} />,
    );
    // MCP discover count should appear in the output
    expect(lastFrame()).toContain("14");
  });

  test("SAFE_DATA_FIXTURE provider label shows anthropic_compatible", () => {
    const { lastFrame } = render(
      <TuiShell fixture={SAFE_DATA_FIXTURE} width={120} height={36} />,
    );
    expect(lastFrame()).toContain("anthropic_compatible");
  });

  test("SAFE_DATA_FIXTURE bottom status shows correct tool count", () => {
    const { lastFrame } = render(
      <TuiShell fixture={SAFE_DATA_FIXTURE} width={120} height={36} />,
    );
    // bottom bar shows toolCount=5 from SAFE_BOTTOM_STATUS
    expect(lastFrame()).toContain("v0.x");
  });
});

describe("ContextInspectorPanel evidence detail", () => {
  test("Evidence lens shows item names when provided", () => {
    const inspectorWithItems = {
      ...MOCK_INSPECTOR,
      evidence: {
        itemCount: 3,
        items: ["REAL-EVIDENCE-001", "REAL-EVIDENCE-002", "REAL-EVIDENCE-003"],
      },
    };
    const { lastFrame } = render(
      <ContextInspectorPanel
        width={36}
        height={36}
        data={inspectorWithItems}
        evidenceLens={true}
        fakeLabel="[safe data — not product-ready]"
      />,
    );
    const output = lastFrame();
    expect(output).toContain("REAL-EVIDENCE-001");
    expect(output).toContain("REAL-EVIDENCE-002");
    expect(output).toContain("REAL-EVIDENCE-003");
  });

  test("Evidence lens shows skill evidence when provided", () => {
    const inspectorWithSkill = {
      ...MOCK_INSPECTOR,
      evidence: {
        itemCount: 2,
        items: ["E-001"],
        skillEvidence: {
          status: "accepted-with-caveats",
          summary: "Plan 3 wired (43/43 PASS). Non-prompt-steered: future.",
        },
      },
    };
    const { lastFrame } = render(
      <ContextInspectorPanel
        width={36}
        height={36}
        data={inspectorWithSkill}
        evidenceLens={true}
        fakeLabel="[safe data — not product-ready]"
      />,
    );
    const output = lastFrame();
    expect(output).toContain("Skill Evidence (D-09)");
    expect(output).toContain("accepted-with-caveats");
    expect(output).toContain("Plan 3 wired");
  });

  test("Evidence lens without items shows placeholder", () => {
    const inspectorNoItems = {
      ...MOCK_INSPECTOR,
      evidence: { itemCount: 5 },
    };
    const { lastFrame } = render(
      <ContextInspectorPanel
        width={36}
        height={36}
        data={inspectorNoItems}
        evidenceLens={true}
        fakeLabel="[fake/local fixture]"
      />,
    );
    expect(lastFrame()).toContain("no evidence detail");
  });
});
