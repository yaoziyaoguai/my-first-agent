import { describe, it, expect } from "vitest";
import {
  classifySafetyLevel,
  isSelectable,
  getSafetyColor,
  getPhase2BehaviorLabel,
  SAFETY_LEVELS,
} from "../data/safetyModel";
import type { SafetyLevel } from "../types";

describe("safetyModel", () => {
  describe("SAFETY_LEVELS", () => {
    it("contains exactly 5 levels", () => {
      expect(SAFETY_LEVELS).toHaveLength(5);
    });

    it("is ordered from least to most restrictive", () => {
      const order = SAFETY_LEVELS.map((s) => s.level);
      expect(order).toEqual([
        "read-only",
        "preview-only",
        "requires-confirmation",
        "disabled",
        "future-executable",
      ]);
    });
  });

  describe("classifySafetyLevel", () => {
    it("classifies read-only commands", () => {
      const result = classifySafetyLevel("read-only");
      expect(result.level).toBe("read-only");
      expect(result.selectable).toBe(true);
      expect(result.phase2Executable).toBe(true);
    });

    it("classifies preview-only commands", () => {
      const result = classifySafetyLevel("preview-only");
      expect(result.level).toBe("preview-only");
      expect(result.selectable).toBe(true);
      expect(result.phase2Executable).toBe(false);
    });

    it("classifies requires-confirmation commands", () => {
      const result = classifySafetyLevel("requires-confirmation");
      expect(result.level).toBe("requires-confirmation");
      expect(result.selectable).toBe(true);
      expect(result.phase2Executable).toBe(false);
    });

    it("classifies disabled commands as not selectable", () => {
      const result = classifySafetyLevel("disabled");
      expect(result.level).toBe("disabled");
      expect(result.selectable).toBe(false);
      expect(result.phase2Executable).toBe(false);
    });

    it("classifies future-executable commands as not selectable", () => {
      const result = classifySafetyLevel("future-executable");
      expect(result.level).toBe("future-executable");
      expect(result.selectable).toBe(false);
      expect(result.phase2Executable).toBe(false);
    });
  });

  describe("isSelectable", () => {
    it("returns true for preview-only", () => {
      expect(isSelectable("preview-only")).toBe(true);
    });

    it("returns true for requires-confirmation", () => {
      expect(isSelectable("requires-confirmation")).toBe(true);
    });

    it("returns false for disabled", () => {
      expect(isSelectable("disabled")).toBe(false);
    });

    it("returns false for future-executable", () => {
      expect(isSelectable("future-executable")).toBe(false);
    });
  });

  describe("getSafetyColor", () => {
    it("returns green for read-only", () => {
      expect(getSafetyColor("read-only")).toBe("green");
    });

    it("returns cyan for preview-only", () => {
      expect(getSafetyColor("preview-only")).toBe("cyan");
    });

    it("returns yellow for requires-confirmation", () => {
      expect(getSafetyColor("requires-confirmation")).toBe("yellow");
    });

    it("returns dim for disabled", () => {
      expect(getSafetyColor("disabled")).toBe("dim");
    });

    it("returns dim for future-executable", () => {
      expect(getSafetyColor("future-executable")).toBe("dim");
    });
  });

  describe("getPhase2BehaviorLabel", () => {
    it("returns appropriate label for preview-only", () => {
      expect(getPhase2BehaviorLabel("preview-only")).toContain("preview");
    });

    it("returns confirmation note for requires-confirmation", () => {
      expect(getPhase2BehaviorLabel("requires-confirmation")).toContain("confirm");
    });

    it("returns disabled note for disabled", () => {
      const label = getPhase2BehaviorLabel("disabled");
      expect(label).toContain("Phase 2");
    });
  });
});
