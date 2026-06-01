import { describe, it, expect } from "vitest";
import {
  checkDocs,
  getDocsByStatus,
  getDocsByContentStatus,
  scanContentForStaleMarkers,
  type DocsCheckResult,
  type DocsStatus,
  type ContentStatus,
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

  it("each result has required fields including contentStatus", () => {
    const results = checkDocs();
    for (const r of results) {
      expect(r.name).toBeDefined();
      expect(typeof r.name).toBe("string");
      expect(r.path).toBeDefined();
      expect(typeof r.path).toBe("string");
      expect(r.status).toBeDefined();
      expect(["present", "missing", "unknown"]).toContain(r.status);
      expect(r.contentStatus).toBeDefined();
      expect(["stale", "current", "unknown"]).toContain(r.contentStatus);
      expect(Array.isArray(r.staleFindings)).toBe(true);
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

  it("getDocsByContentStatus filters correctly", () => {
    const results = checkDocs();
    const current = getDocsByContentStatus(results, "current");
    for (const r of current) {
      expect(r.contentStatus).toBe("current");
    }
  });
});

describe("Content staleness detection", () => {
  describe("scanContentForStaleMarkers (pure — synthetic content)", () => {
    it("detects stale test count 227/227", () => {
      const findings = scanContentForStaleMarkers(
        "PROJECT_STATUS.md",
        "B8 Phase 1-6A COMPLETED (227/227 tests PASS). Next: Polish Loop.",
      );
      expect(findings.length).toBeGreaterThanOrEqual(1);
      expect(findings.some((f) => f.label.includes("227/227"))).toBe(true);
    });

    it("does NOT flag 241/241 as stale", () => {
      const findings = scanContentForStaleMarkers(
        "PROJECT_STATUS.md",
        "B8 Phase 1-6A COMPLETED (241/241 tests PASS).",
      );
      expect(findings.filter((f) => f.label.includes("227/227"))).toHaveLength(0);
    });

    it("detects stale Phase 3 recommended in PROJECT_STATUS", () => {
      const findings = scanContentForStaleMarkers(
        "PROJECT_STATUS.md",
        "Phase 3 is recommended for current development.",
      );
      expect(findings.some((f) => f.label.includes("Phase 3"))).toBe(true);
    });

    it("does NOT apply Phase 3 check to non-PROJECT_STATUS files", () => {
      const findings = scanContentForStaleMarkers(
        "PROGRESS_LEDGER.md",
        "Phase 3 is recommended for current development.",
      );
      // Phase 3 marker is scoped to PROJECT_STATUS.md only
      expect(findings.filter((f) => f.label.includes("Phase 3"))).toHaveLength(0);
    });

    it("detects Phase 4 deferred status (all files)", () => {
      const findings = scanContentForStaleMarkers(
        "PROGRESS_LEDGER.md",
        '{"phase": "b8-phase-4", "status": "deferred"}',
      );
      expect(findings.some((f) => f.label.includes("Phase 4"))).toBe(true);
    });

    it("detects Phase 5 deferred status (all files)", () => {
      const findings = scanContentForStaleMarkers(
        "PROGRESS_LEDGER.md",
        '{"phase": "b8-phase-5", "status": "deferred"}',
      );
      expect(findings.some((f) => f.label.includes("Phase 5"))).toBe(true);
    });

    it("detects Phase 6A not-started", () => {
      const findings = scanContentForStaleMarkers(
        "PROJECT_STATUS.md",
        "Phase 6A is not started yet.",
      );
      expect(findings.some((f) => f.label.includes("Phase 6A"))).toBe(true);
    });

    it("returns empty for current-sounding content", () => {
      const findings = scanContentForStaleMarkers(
        "PROJECT_STATUS.md",
        "B8 Phase 1-6A COMPLETED (241/241 tests PASS). Phase 3 completed. Phase 4 completed. Phase 5 completed. Phase 6B deferred. B7 not started.",
      );
      expect(findings).toHaveLength(0);
    });

    it("returns unknown-like empty for irrelevant content", () => {
      const findings = scanContentForStaleMarkers(
        "B8 TUI SDD",
        "# B8 TypeScript TUI Workbench SDD\n\nArchitecture document.",
      );
      // No stale markers should match
      expect(findings).toHaveLength(0);
    });

    it("findings contain label and match text", () => {
      const findings = scanContentForStaleMarkers(
        "PROJECT_STATUS.md",
        "227/227 tests PASS.",
      );
      expect(findings.length).toBeGreaterThanOrEqual(1);
      expect(findings[0].label).toBeTruthy();
      expect(findings[0].match).toBe("227/227");
    });
  });
});
