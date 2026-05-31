import { describe, it, expect } from "vitest";
import { loadCommandCatalog, getExecutableCommands, getCommandById, getCommandsByCategory } from "../data/commandCatalog";
import type { CommandCatalog, CommandDefinition, SafetyLevel } from "../types";

const SAMPLE_CATALOG: CommandCatalog = {
  version: "1.0.0",
  commands: [
    {
      id: "status",
      name: "Project Status",
      description: "Show project status",
      category: "diagnostics",
      safetyLevel: "preview-only" as SafetyLevel,
      requiresConfirmation: false,
      executableInPhase2: false,
      shellCommand: "cat docs/PROJECT_STATUS.md",
    },
    {
      id: "autorun",
      name: "AutoRun",
      description: "Run AutoRun workflow",
      category: "workflow",
      safetyLevel: "requires-confirmation" as SafetyLevel,
      requiresConfirmation: true,
      executableInPhase2: false,
      shellCommand: "python main.py auto-run",
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
  ],
};

describe("commandCatalog", () => {
  describe("loadCommandCatalog", () => {
    it("loads and parses commands.json from disk", () => {
      const catalog = loadCommandCatalog();
      expect(catalog.version).toBeDefined();
      expect(catalog.commands.length).toBeGreaterThan(0);
    });

    it("every command has required fields", () => {
      const catalog = loadCommandCatalog();
      for (const cmd of catalog.commands) {
        expect(cmd.id).toBeTruthy();
        expect(cmd.name).toBeTruthy();
        expect(cmd.description).toBeTruthy();
        expect(cmd.category).toBeTruthy();
        expect(cmd.safetyLevel).toBeTruthy();
      }
    });

    it("every safetyLevel is a valid SafetyLevel value", () => {
      const valid: SafetyLevel[] = [
        "read-only",
        "preview-only",
        "requires-confirmation",
        "disabled",
        "future-executable",
      ];
      const catalog = loadCommandCatalog();
      for (const cmd of catalog.commands) {
        expect(valid).toContain(cmd.safetyLevel);
      }
    });

    it("returns empty commands array for missing file (graceful degradation)", () => {
      const catalog = loadCommandCatalog("/nonexistent/path/commands.json");
      expect(catalog.commands).toEqual([]);
    });
  });

  describe("getExecutableCommands", () => {
    it("returns only executableInPhase2=true commands", () => {
      const result = getExecutableCommands(SAMPLE_CATALOG);
      expect(result.every((c) => c.executableInPhase2)).toBe(true);
    });
  });

  describe("getCommandById", () => {
    it("returns command by id", () => {
      const cmd = getCommandById(SAMPLE_CATALOG, "status");
      expect(cmd?.name).toBe("Project Status");
    });

    it("returns undefined for unknown id", () => {
      const cmd = getCommandById(SAMPLE_CATALOG, "nonexistent");
      expect(cmd).toBeUndefined();
    });
  });

  describe("getCommandsByCategory", () => {
    it("groups commands by category", () => {
      const groups = getCommandsByCategory(SAMPLE_CATALOG);
      expect(groups.get("diagnostics")?.length).toBe(1);
      expect(groups.get("workflow")?.length).toBe(1);
      expect(groups.get("execution")?.length).toBe(1);
    });
  });
});
