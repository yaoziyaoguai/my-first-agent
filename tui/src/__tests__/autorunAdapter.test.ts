import { describe, it, expect } from "vitest";
import {
  AUTORUN_COMMANDS,
  getAutorunCommand,
  validateAutorunTemplate,
  isFixedTemplate,
  ALLOWED_AUTORUN_ACTIONS,
} from "../data/autorunAdapter";

describe("autorunAdapter", () => {
  describe("AUTORUN_COMMANDS", () => {
    it("contains fixed template for each action", () => {
      expect(AUTORUN_COMMANDS).toHaveProperty("continue");
      expect(AUTORUN_COMMANDS).toHaveProperty("status");
      expect(AUTORUN_COMMANDS).toHaveProperty("audit");
      expect(AUTORUN_COMMANDS).toHaveProperty("gates");
    });

    it("all templates are fixed strings (no dynamic parts)", () => {
      for (const cmd of Object.values(AUTORUN_COMMANDS)) {
        expect(typeof cmd).toBe("string");
        expect(cmd.length).toBeGreaterThan(0);
        // No user-input placeholders in templates
        expect(cmd).not.toContain("${");
        expect(cmd).not.toContain("$(");
      }
    });

    it("continue template uses auto-run --continue", () => {
      expect(AUTORUN_COMMANDS["continue"]).toContain("auto-run");
      expect(AUTORUN_COMMANDS["continue"]).toContain("--continue");
    });
  });

  describe("ALLOWED_AUTORUN_ACTIONS", () => {
    it("lists all autorun action keys", () => {
      expect(ALLOWED_AUTORUN_ACTIONS).toContain("continue");
      expect(ALLOWED_AUTORUN_ACTIONS).toContain("status");
      expect(ALLOWED_AUTORUN_ACTIONS).toContain("audit");
      expect(ALLOWED_AUTORUN_ACTIONS).toContain("gates");
    });
  });

  describe("getAutorunCommand", () => {
    it("returns template for valid action", () => {
      const cmd = getAutorunCommand("continue");
      expect(cmd).toBe(AUTORUN_COMMANDS["continue"]);
    });

    it("throws for unknown action", () => {
      expect(() => getAutorunCommand("unknown-action" as any)).toThrow();
    });

    it("throws for dynamic user input injection attempt", () => {
      expect(() => getAutorunCommand("continue; rm -rf /" as any)).toThrow();
    });
  });

  describe("validateAutorunTemplate", () => {
    it("passes for all fixed templates", () => {
      for (const action of ALLOWED_AUTORUN_ACTIONS) {
        expect(() => validateAutorunTemplate(action)).not.toThrow();
      }
    });

    it("rejects unrecognized action", () => {
      expect(() => validateAutorunTemplate("custom-cmd")).toThrow();
    });
  });

  describe("isFixedTemplate", () => {
    it("returns true for all built-in actions", () => {
      for (const action of ALLOWED_AUTORUN_ACTIONS) {
        expect(isFixedTemplate(action)).toBe(true);
      }
    });

    it("returns false for arbitrary strings", () => {
      expect(isFixedTemplate("custom")).toBe(false);
      expect(isFixedTemplate("auto-run --custom")).toBe(false);
    });
  });
});
