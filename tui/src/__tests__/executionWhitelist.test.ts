import { describe, it, expect } from "vitest";
import {
  isAllowed,
  isBlocked,
  getPhase4ExecutableCommands,
  buildShellCommand,
  ALLOWED_COMMAND_IDS,
  BLOCKED_PATTERNS,
} from "../data/executionWhitelist";
import type { CommandDefinition, SafetyLevel } from "../types";

const makeCmd = (
  id: string,
  safetyLevel: SafetyLevel,
  shellCommand?: string,
): CommandDefinition => ({
  id,
  name: id,
  description: "",
  category: "diagnostics",
  safetyLevel,
  requiresConfirmation: safetyLevel === "requires-confirmation",
  executableInPhase2: false,
  shellCommand,
});

describe("executionWhitelist", () => {
  describe("ALLOWED_COMMAND_IDS", () => {
    it("includes status, gates, docs-check, autorun, audit, dogfood", () => {
      expect(ALLOWED_COMMAND_IDS).toContain("status");
      expect(ALLOWED_COMMAND_IDS).toContain("gates");
      expect(ALLOWED_COMMAND_IDS).toContain("docs-check");
      expect(ALLOWED_COMMAND_IDS).toContain("autorun");
      expect(ALLOWED_COMMAND_IDS).toContain("audit");
      expect(ALLOWED_COMMAND_IDS).toContain("dogfood");
    });

    it("does not include agent-run or deploy", () => {
      expect(ALLOWED_COMMAND_IDS).not.toContain("agent-run");
      expect(ALLOWED_COMMAND_IDS).not.toContain("deploy");
    });
  });

  describe("isAllowed", () => {
    it("returns true for whitelisted command", () => {
      expect(isAllowed("status")).toBe(true);
      expect(isAllowed("gates")).toBe(true);
      expect(isAllowed("autorun")).toBe(true);
    });

    it("returns false for non-whitelisted command", () => {
      expect(isAllowed("agent-run")).toBe(false);
      expect(isAllowed("deploy")).toBe(false);
      expect(isAllowed("unknown-cmd")).toBe(false);
    });
  });

  describe("isBlocked", () => {
    it("blocks destructive git commands", () => {
      expect(isBlocked("git push --force origin main")).toBe(true);
      expect(isBlocked("git reset --hard HEAD~1")).toBe(true);
      expect(isBlocked("git branch -D feature")).toBe(true);
      expect(isBlocked("git clean -fd")).toBe(true);
    });

    it("blocks rm -rf", () => {
      expect(isBlocked("rm -rf /tmp/test")).toBe(true);
      expect(isBlocked("rm -rf --no-preserve-root /")).toBe(true);
    });

    it("blocks force overwrite", () => {
      expect(isBlocked("git checkout -- .")).toBe(true);
    });

    it("blocks sudo / chmod / chown", () => {
      expect(isBlocked("sudo ls")).toBe(true);
      expect(isBlocked("chmod 777 file")).toBe(true);
      expect(isBlocked("chown user:group file")).toBe(true);
    });

    it("allows safe commands through", () => {
      expect(isBlocked("python main.py status")).toBe(false);
      expect(isBlocked("ruff check .")).toBe(false);
      expect(isBlocked("git diff --check")).toBe(false);
    });
  });

  describe("getPhase4ExecutableCommands", () => {
    it("filters to only whitelisted commands with shellCommand", () => {
      const catalog = {
        version: "1.0.0",
        commands: [
          makeCmd("status", "preview-only", "python main.py status"),
          makeCmd("gates", "preview-only", "ruff check ."),
          makeCmd("autorun", "requires-confirmation", "python main.py auto-run"),
          makeCmd("agent-run", "disabled", "python main.py run"),
          makeCmd("deploy", "disabled"),
        ],
      };
      const result = getPhase4ExecutableCommands(catalog);
      const ids = result.map((c) => c.id);
      expect(ids).toContain("status");
      expect(ids).toContain("gates");
      expect(ids).toContain("autorun");
      expect(ids).not.toContain("agent-run");
      expect(ids).not.toContain("deploy");
    });

    it("excludes whitelisted commands without shellCommand", () => {
      const catalog = {
        version: "1.0.0",
        commands: [
          makeCmd("status", "preview-only", undefined),
        ],
      };
      const result = getPhase4ExecutableCommands(catalog);
      expect(result).toHaveLength(0);
    });
  });

  describe("buildShellCommand", () => {
    it("returns shellCommand for allowed command", () => {
      const cmd = makeCmd("status", "preview-only", "python main.py status");
      const result = buildShellCommand(cmd);
      expect(result).toBe("python main.py status");
    });

    it("throws for non-whitelisted command", () => {
      const cmd = makeCmd("agent-run", "disabled", "python main.py run");
      expect(() => buildShellCommand(cmd)).toThrow();
    });

    it("throws for blocked shell command", () => {
      const cmd = makeCmd("status", "preview-only", "rm -rf /");
      expect(() => buildShellCommand(cmd)).toThrow();
    });
  });

  describe("BLOCKED_PATTERNS", () => {
    it("covers destructive git patterns", () => {
      const destructiveGit = BLOCKED_PATTERNS.filter(
        (p) => p.includes("push") || p.includes("reset") || p.includes("branch") || p.includes("clean"),
      );
      expect(destructiveGit.length).toBeGreaterThanOrEqual(4);
    });

    it("covers system command patterns", () => {
      const sysPatterns = BLOCKED_PATTERNS.filter(
        (p) => p.includes("sudo") || p.includes("chmod") || p.includes("chown"),
      );
      expect(sysPatterns.length).toBeGreaterThanOrEqual(3);
    });
  });
});
