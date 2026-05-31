import { describe, it, expect, vi, beforeEach } from "vitest";

// Mock react and ink
vi.mock("react", () => ({
  useState: (v: unknown) => [v, vi.fn()],
  createElement: vi.fn(),
}));

vi.mock("ink", () => ({
  Box: "Box",
  Text: "Text",
  useInput: vi.fn(),
}));

import { formatCommandRow, buildGroupedCommands } from "../data/commandPanel";
import type { CommandCatalog, CommandDefinition, SafetyLevel } from "../types";

const SAMPLE_COMMANDS: CommandDefinition[] = [
  {
    id: "status",
    name: "Project Status",
    description: "Show status",
    category: "diagnostics",
    safetyLevel: "preview-only" as SafetyLevel,
    requiresConfirmation: false,
    executableInPhase2: false,
  },
  {
    id: "autorun",
    name: "AutoRun",
    description: "Run workflow",
    category: "workflow",
    safetyLevel: "requires-confirmation" as SafetyLevel,
    requiresConfirmation: true,
    executableInPhase2: false,
  },
  {
    id: "agent-run",
    name: "Agent Run",
    description: "Start agent",
    category: "execution",
    safetyLevel: "disabled" as SafetyLevel,
    requiresConfirmation: true,
    executableInPhase2: false,
  },
  {
    id: "deploy",
    name: "Deploy",
    description: "Deploy to prod",
    category: "execution",
    safetyLevel: "future-executable" as SafetyLevel,
    requiresConfirmation: true,
    executableInPhase2: false,
  },
];

describe("commandPanel", () => {
  describe("formatCommandRow", () => {
    it("formats a command with cursor marker when selected", () => {
      const cmd = SAMPLE_COMMANDS[0];
      const result = formatCommandRow(cmd, true);
      expect(result).toContain("▶");
      expect(result).toContain(cmd.name);
    });

    it("formats a command with spaces for padding when not selected", () => {
      const cmd = SAMPLE_COMMANDS[0];
      const result = formatCommandRow(cmd, false);
      expect(result).not.toContain("▶");
      expect(result).toContain(cmd.name);
    });

    it("includes safety level in formatted output", () => {
      const cmd = SAMPLE_COMMANDS[1];
      const result = formatCommandRow(cmd, false);
      expect(result).toContain("requires-confirmation");
    });

    it("marks disabled commands", () => {
      const cmd = SAMPLE_COMMANDS[2];
      const result = formatCommandRow(cmd, true);
      expect(result).toContain("disabled");
    });
  });

  describe("buildGroupedCommands", () => {
    it("groups commands by category", () => {
      const catalog: CommandCatalog = {
        version: "1.0.0",
        commands: SAMPLE_COMMANDS,
      };
      const groups = buildGroupedCommands(catalog);

      expect(groups.size).toBeGreaterThanOrEqual(1);
      const allCmds = [...groups.values()].flat();
      expect(allCmds.length).toBe(SAMPLE_COMMANDS.length);
    });

    it("preserves category names in groups", () => {
      const catalog: CommandCatalog = {
        version: "1.0.0",
        commands: SAMPLE_COMMANDS,
      };
      const groups = buildGroupedCommands(catalog);
      const categories = [...groups.keys()];
      expect(categories).toContain("diagnostics");
      expect(categories).toContain("workflow");
      expect(categories).toContain("execution");
    });

    it("handles empty catalog", () => {
      const groups = buildGroupedCommands({ version: "1.0.0", commands: [] });
      expect(groups.size).toBe(0);
    });
  });
});
