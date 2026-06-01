/** AutoRun 文案测试 — provisional dev-only / Development Workflow Panel */
import { describe, it, expect } from "vitest";
import { loadCommandCatalog } from "../data/commandCatalog";

describe("AutoRun — provisional dev-only labeling", () => {
  const catalog = loadCommandCatalog();

  it("autorun command name is 'Development Workflow Panel'", () => {
    const cmd = catalog.commands.find((c) => c.id === "autorun");
    expect(cmd).toBeDefined();
    expect(cmd!.name).toBe("Development Workflow Panel");
  });

  it("autorun description mentions provisional dev-only", () => {
    const cmd = catalog.commands.find((c) => c.id === "autorun");
    expect(cmd).toBeDefined();
    expect(cmd!.description).toMatch(/provisional|dev-only|may be removed/i);
  });

  it("autorun riskNote clarifies it is not First Agent product feature", () => {
    const cmd = catalog.commands.find((c) => c.id === "autorun");
    expect(cmd).toBeDefined();
    // riskNote 应明确标注这是开发期工具，非产品功能
    const risk = cmd!.riskNote ?? "";
    expect(risk).toMatch(/开发期|Coding Agent|workflow/);
    expect(risk).toMatch(/不是.*产品/);
  });

  it("autorun is not marked as executableInPhase2", () => {
    const cmd = catalog.commands.find((c) => c.id === "autorun");
    expect(cmd).toBeDefined();
    expect(cmd!.executableInPhase2).toBe(false);
  });
});
