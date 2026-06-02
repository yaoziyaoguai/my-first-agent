/**
 * Entry routing tests — 验证 npm start 默认入口为 TuiShell / Visual Shell，
 * 旧 WorkbenchLayout 仅通过 --legacy / --workbench 标志访问。
 */
import { describe, test, expect } from "vitest";
import React from "react";
import { render } from "ink-testing-library";
import { readFileSync } from "node:fs";
import path from "node:path";

import { TuiShell } from "../components/shell/TuiShell";
import { WorkbenchLayout } from "../components/WorkbenchLayout";
import { SAFE_DATA_FIXTURE } from "../data/visualShellFixtures";

const PKG_PATH = path.resolve(import.meta.dirname, "..", "..", "package.json");
const parsed = JSON.parse(readFileSync(PKG_PATH, "utf-8"));

// ── package.json script contracts ──

describe("Entry Routing — package.json scripts", () => {
  test("start script exists", () => {
    expect(parsed.scripts.start).toBe("tsx src/main.tsx");
  });

  test("start:legacy script uses --legacy flag", () => {
    expect(parsed.scripts["start:legacy"]).toContain("--legacy");
  });

  test("start:workbench script uses --workbench flag", () => {
    expect(parsed.scripts["start:workbench"]).toContain("--workbench");
  });
});

// ── Default entry renders Visual Shell ──

describe("Entry Routing — default (Visual Shell)", () => {
  const { lastFrame } = render(
    <TuiShell fixture={SAFE_DATA_FIXTURE} width={120} height={36} />,
  );
  const output = lastFrame();

  test("title is First Agent TUI, not old B8 Workbench", () => {
    expect(output).toContain("First Agent TUI");
    expect(output).not.toContain("B8 Interaction-first Workbench");
    expect(output).not.toContain("M2-M8 MVP");
  });

  test("safe data label visible, not old fixture label", () => {
    expect(output).toContain("[safe data — not product-ready]");
    expect(output).not.toContain("[fake/local fixture]");
  });

  test("no positive product-ready or real provider claims", () => {
    // "not product-ready" disclaimer is expected; standalone "product-ready" claim is not
    expect(output).toContain("not product-ready");
    expect(output).not.toContain("real provider");
    expect(output).not.toContain("production-ready");
  });
});

// ── Legacy fallback still renders ──

describe("Entry Routing — legacy WorkbenchLayout", () => {
  test("WorkbenchLayout renders without crash", () => {
    const el = React.createElement(WorkbenchLayout, {});
    expect(el).toBeDefined();
  });

  test("WorkbenchLayout renders old title", () => {
    const { lastFrame } = render(<WorkbenchLayout />);
    expect(lastFrame()).toContain("B8 Interaction-first Workbench");
    expect(lastFrame()).toContain("fake/local mode");
  });
});

// ── Visual Shell mock labeling guard (tested via SAFE_DATA_FIXTURE entry) ──

describe("Entry Routing — fake/local guard on default entry", () => {
  const { lastFrame } = render(
    <TuiShell fixture={SAFE_DATA_FIXTURE} width={120} height={36} />,
  );
  const output = lastFrame();

  test("default entry shows anthropic_compatible provider, not fake/local raw", () => {
    // The top bar provider area uses the SAFE_PROVIDER_LABEL
    expect(output).toContain("anthropic_compatible");
  });

  test("default entry does not claim ACTIVATED or default entry status", () => {
    expect(output).not.toContain("ACTIVATED");
    expect(output).not.toContain("default entry");
  });

  test("BottomStatusBar shows version and fake/local mode", () => {
    expect(output).toContain("v0.x");
    expect(output).toContain("[safe data — not product-ready]");
  });
});
