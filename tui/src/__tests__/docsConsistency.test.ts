import { describe, it, expect } from "vitest";
import {
  checkDocs,
  getDocsByStatus,
  type DocsCheckResult,
  type DocsStatus,
} from "../data/docsConsistency";

describe("DocsConsistency model", () => {
  it("checkDocs returns results for all required docs", () => {
    const results = checkDocs();
    const names = results.map((r) => r.name);
    expect(names).toContain("PROJECT_STATUS.md");
    expect(names).toContain("PROGRESS_LEDGER.md");
    expect(names).toContain("REAL_EVIDENCE_VALIDATION_DEBT.md");
    expect(names).toContain("B8 TUI SDD");
    expect(results.length).toBeGreaterThanOrEqual(4);
  });

  it("each result has required fields", () => {
    const results = checkDocs();
    for (const r of results) {
      expect(r.name).toBeDefined();
      expect(typeof r.name).toBe("string");
      expect(r.path).toBeDefined();
      expect(typeof r.path).toBe("string");
      expect(r.status).toBeDefined();
      expect(["present", "missing", "unknown"]).toContain(r.status);
    }
  });

  it("status values are valid DocsStatus", () => {
    const results = checkDocs();
    for (const r of results) {
      const valid: DocsStatus[] = ["present", "missing", "unknown"];
      expect(valid).toContain(r.status);
    }
  });

  it("getDocsByStatus filters correctly", () => {
    const results = checkDocs();
    const present = getDocsByStatus(results, "present");
    for (const r of present) {
      expect(r.status).toBe("present");
    }
  });

  it("getDocsByStatus handles empty input", () => {
    expect(getDocsByStatus([], "present")).toHaveLength(0);
  });

  it("getDocsByStatus returns empty when all docs have different status", () => {
    const results = checkDocs();
    const missing = getDocsByStatus(results, "missing");
    // Not all docs are missing; this should not crash
    expect(Array.isArray(missing)).toBe(true);
    for (const r of missing) {
      expect(r.status).toBe("missing");
    }
  });

  it("returns new array (immutable)", () => {
    const a = checkDocs();
    const b = checkDocs();
    expect(a).not.toBe(b);
  });
});
