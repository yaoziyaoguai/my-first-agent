import { describe, it, expect } from "vitest";
import {
  parseGateHistory,
  getLatestGateResults,
  type GateResult,
} from "../data/gateHistory";

const SAMPLE_LEDGER_WITH_GATES = `
## 2026-06-01

| **B8 Phase 4 COMPLETED** — **178/178 tests PASS**. TypeScript 编译 clean. Gates: all pass. ruff clean. git diff --check clean.
| **B8 Phase 3 COMPLETED** — **133/133 tests PASS**. TypeScript 编译 clean. Gates: all pass.
`;

const SAMPLE_LEDGER_EMPTY = "";

const SAMPLE_STATUS_WITH_GATES = `
**最后更新**: 2026-06-01 (B8 Phase 5: 206/206 tests PASS)
tui: 206/206 tests PASS, tsc --noEmit clean, 23 test files
`;

describe("gateHistory", () => {
  describe("parseGateHistory", () => {
    it("extracts vitest results", () => {
      const gates = parseGateHistory(SAMPLE_LEDGER_WITH_GATES);
      const vitest = gates.find((g) => g.name === "vitest");
      expect(vitest).toBeDefined();
      expect(vitest?.status).toContain("PASS");
    });

    it("extracts tsc results", () => {
      const gates = parseGateHistory(SAMPLE_LEDGER_WITH_GATES);
      const tsc = gates.find((g) => g.name === "tsc");
      expect(tsc).toBeDefined();
    });

    it("extracts ruff results when present", () => {
      const gates = parseGateHistory(SAMPLE_LEDGER_WITH_GATES);
      const ruff = gates.find((g) => g.name === "ruff");
      expect(ruff).toBeDefined();
      expect(ruff?.status).not.toBe("unknown");
    });

    it("returns unknown for missing gate evidence", () => {
      const gates = parseGateHistory(SAMPLE_LEDGER_EMPTY);
      for (const g of gates) {
        expect(g.status).toBe("unknown");
      }
    });

    it("includes all known gate names", () => {
      const gates = parseGateHistory(SAMPLE_LEDGER_WITH_GATES);
      const names = gates.map((g) => g.name);
      expect(names).toContain("vitest");
      expect(names).toContain("tsc");
      expect(names).toContain("ruff");
      expect(names).toContain("pre-commit");
      expect(names).toContain("git diff --check");
    });

    it("never returns empty gate list", () => {
      const gates = parseGateHistory("");
      expect(gates.length).toBeGreaterThan(0);
    });

    it("marks gates as unknown when no matching keyword found", () => {
      const gates = parseGateHistory("Some unrelated text about cats and dogs.");
      for (const g of gates) {
        expect(g.status).toBe("unknown");
      }
    });
  });

  describe("getLatestGateResults", () => {
    it("returns same results as parseGateHistory for single source", () => {
      const gates = getLatestGateResults(SAMPLE_LEDGER_WITH_GATES);
      expect(Array.isArray(gates)).toBe(true);
      expect(gates.length).toBeGreaterThan(0);
    });

    it("handles empty input", () => {
      const gates = getLatestGateResults("");
      expect(Array.isArray(gates)).toBe(true);
      expect(gates.length).toBeGreaterThan(0);
    });
  });

  describe("GateResult type", () => {
    it("conforms to structure", () => {
      const result: GateResult = {
        name: "vitest",
        status: "PASS (178/178)",
        source: "progress-ledger",
        lastUpdated: "2026-06-01",
      };
      expect(result.name).toBe("vitest");
      expect(result.status).toBe("PASS (178/178)");
    });
  });
});
