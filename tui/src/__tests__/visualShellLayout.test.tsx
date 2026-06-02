/**
 * Slice A — Visual Shell layout boundary tests.
 * 验证 6 区域的尺寸契约、宽度自适应规则、最小宽度限制。
 */
import { describe, test, expect } from "vitest";
import React from "react";
import { render } from "ink-testing-library";
import { TuiShell } from "../components/shell/TuiShell";
import { FULL_FIXTURE, EMPTY_FIXTURE } from "../data/visualShellFixtures";

describe("Visual Shell layout boundaries", () => {
  test("full width (120 cols) renders all zones", () => {
    const { lastFrame } = render(
      <TuiShell fixture={FULL_FIXTURE} width={120} height={36} />,
    );
    const output = lastFrame();
    // All 6 zones should be present
    expect(output).toContain("First Agent TUI"); // TopBar
    expect(output).toContain("Chat / Work Area"); // MainWorkArea
    expect(output).toContain("agent:"); // RightInspector (ActiveContextPanel)
    expect(output).toContain("/ask"); // InputDock
    expect(output).toContain("q: quit"); // BottomStatusBar
    expect(output).toContain("Workspaces"); // LeftRail
  });

  test("compact width (< 80 cols) hides RightInspector", () => {
    const { lastFrame } = render(
      <TuiShell fixture={FULL_FIXTURE} width={70} height={30} />,
    );
    const output = lastFrame();
    expect(output).toContain("compact");
    // RightInspector should NOT be rendered at < 80 cols
    expect(output).not.toContain("Context Inspector");
    expect(output).not.toContain("Active Context");
  });

  test("medium width (100 cols) shows RightInspector truncated", () => {
    const { lastFrame } = render(
      <TuiShell fixture={FULL_FIXTURE} width={100} height={36} />,
    );
    const output = lastFrame();
    expect(output).toContain("agent:");
    expect(output).not.toContain("compact");
  });

  test("empty fixture layout structure intact", () => {
    const { lastFrame } = render(
      <TuiShell fixture={EMPTY_FIXTURE} width={120} height={36} />,
    );
    const output = lastFrame();
    // All structural zones still present
    expect(output).toContain("First Agent TUI");
    expect(output).toContain("Chat / Work Area");
    expect(output).toContain("agent:");
    expect(output).toContain("q: quit");
  });

  test("no Dashboard / AutoRun / Project Operations in output", () => {
    const { lastFrame } = render(
      <TuiShell fixture={FULL_FIXTURE} width={120} height={36} />,
    );
    const output = lastFrame();
    // Explicitly verify legacy panels are not restored
    expect(output).not.toContain("Dashboard");
    expect(output).not.toContain("AutoRun");
    expect(output).not.toContain("Project Operations");
    expect(output).not.toContain("Dynamic Audit");
  });

  test("no .env / API key content in output", () => {
    const { lastFrame } = render(
      <TuiShell fixture={FULL_FIXTURE} width={120} height={36} />,
    );
    const output = lastFrame();
    expect(output).not.toContain(".env");
    expect(output).not.toContain("sk-");
    expect(output).not.toContain("api_key");
  });
});
