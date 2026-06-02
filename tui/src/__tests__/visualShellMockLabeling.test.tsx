/**
 * Slice A — Visual Shell mock/fake labeling tests.
 * 验证所有 [fake/local] 标注可见、不伪装成 real/production。
 */
import { describe, test, expect } from "vitest";
import React from "react";
import { render } from "ink-testing-library";
import { TuiShell } from "../components/shell/TuiShell";
import { FULL_FIXTURE } from "../data/visualShellFixtures";

describe("Visual Shell mock labeling", () => {
  const { lastFrame } = render(
    <TuiShell fixture={FULL_FIXTURE} width={120} height={36} />,
  );
  const output = lastFrame();

  test("TopBar shows fake/local provider", () => {
    expect(output).toContain("fake/local");
  });

  test("LeftRail shows fixture label", () => {
    expect(output).toContain("[fake/local fixture]");
  });

  test("InputDock shows fake/local label", () => {
    expect(output).toContain("[fake/local]");
  });

  test("no product-ready claim in output", () => {
    expect(output).not.toContain("product-ready");
    expect(output).not.toContain("production");
  });

  test("no real provider claims", () => {
    expect(output).not.toContain("real provider");
    expect(output).not.toContain("real MCP");
    expect(output).not.toContain("live runtime");
  });

  test("no default entry activated claim", () => {
    expect(output).not.toContain("default entry");
    expect(output).not.toContain("ACTIVATED");
  });
});
