import { describe, it, expect } from "vitest";
import { buildPreviewLines, getRiskLabel } from "../data/commandPreview";
import type { CommandDefinition, SafetyLevel } from "../types";

const SAMPLE_CMD: CommandDefinition = {
  id: "autorun",
  name: "AutoRun Workflow",
  description: "启动完整 AutoRun 工程 loop",
  category: "workflow",
  safetyLevel: "requires-confirmation" as SafetyLevel,
  requiresConfirmation: true,
  executableInPhase2: false,
  shellCommand: "python main.py auto-run",
  relatedSkills: ["auto-run"],
  riskNote: "可能执行 git push",
};

describe("commandPreview", () => {
  describe("buildPreviewLines", () => {
    it("includes command name in preview title", () => {
      const lines = buildPreviewLines(SAMPLE_CMD);
      expect(lines.some((l) => l.includes("AutoRun"))).toBe(true);
    });

    it("includes safety level", () => {
      const lines = buildPreviewLines(SAMPLE_CMD);
      expect(lines.some((l) => l.includes("requires-confirmation"))).toBe(true);
    });

    it("includes shell command", () => {
      const lines = buildPreviewLines(SAMPLE_CMD);
      expect(lines.some((l) => l.includes("python main.py auto-run"))).toBe(true);
    });

    it("includes Phase 2 non-execution warning", () => {
      const lines = buildPreviewLines(SAMPLE_CMD);
      expect(lines.some((l) => l.includes("Phase 2") || l.includes("不执行"))).toBe(true);
    });

    it("includes risk note when present", () => {
      const lines = buildPreviewLines(SAMPLE_CMD);
      expect(lines.some((l) => l.includes("git push"))).toBe(true);
    });

    it("handles command without shellCommand", () => {
      const cmd: CommandDefinition = {
        ...SAMPLE_CMD,
        shellCommand: undefined,
        riskNote: undefined,
      };
      const lines = buildPreviewLines(cmd);
      expect(lines.length).toBeGreaterThan(0);
    });
  });

  describe("getRiskLabel", () => {
    it("returns low risk for preview-only", () => {
      expect(getRiskLabel("preview-only")).toContain("低");
    });

    it("returns medium risk for requires-confirmation", () => {
      expect(getRiskLabel("requires-confirmation")).toContain("中");
    });

    it("returns high risk for disabled", () => {
      expect(getRiskLabel("disabled")).toContain("高");
    });
  });
});
