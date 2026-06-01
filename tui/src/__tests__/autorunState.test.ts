import { describe, it, expect } from "vitest";
import {
  parseAutoRunState,
  deriveAutoRunStatus,
  type AutoRunState,
} from "../data/autorunState";

const SAMPLE_PROJECT_STATUS = `**最后更新**: 2026-06-01 (B8 Phase 4: Safe Command Execution — 178/178 tests PASS)

## 0. Independent Re-Audit Override

### Current Verdict
| 当前 independent combined review score | 4.5/5 |

## 2. 推荐下一步

**B8 Phase 5 (AutoRun 工作流集成) 为推荐下一步**

| B8 | TUI architecture | **Phase 1-4 COMPLETED** (178/178 tests PASS)。Phase 5 (AutoRun 集成) 为推荐下一步。 |
`;

describe("autorunState", () => {
  describe("parseAutoRunState", () => {
    it("extracts current phase from PROJECT_STATUS", () => {
      const state = parseAutoRunState(SAMPLE_PROJECT_STATUS);
      expect(state.currentPhase).toBe("Phase 4");
    });

    it("extracts next recommended step", () => {
      const state = parseAutoRunState(SAMPLE_PROJECT_STATUS);
      expect(state.nextRecommended).toContain("Phase 5");
      expect(state.nextRecommended).toContain("AutoRun");
    });

    it("defaults to idle status when not running", () => {
      const state = parseAutoRunState(SAMPLE_PROJECT_STATUS);
      expect(state.status).toBe("idle");
    });

    it("returns empty strings for missing fields", () => {
      const state = parseAutoRunState("");
      expect(state.currentPhase).toBe("");
      expect(state.nextRecommended).toBe("");
      expect(state.status).toBe("idle");
    });

    it("extracts testsPass count", () => {
      const state = parseAutoRunState(SAMPLE_PROJECT_STATUS);
      expect(state.testsPass).toBeGreaterThan(0);
    });

    it("extracts hardStopReason from HARD_STOP line", () => {
      const text = "HARD_STOP: context below 10% — user must decide";
      const state = parseAutoRunState(text);
      expect(state.hardStopReason).toBe("context below 10% — user must decide");
    });

    it("returns undefined hardStopReason when no HARD_STOP", () => {
      const state = parseAutoRunState(SAMPLE_PROJECT_STATUS);
      expect(state.hardStopReason).toBeUndefined();
    });
  });

  describe("deriveAutoRunStatus", () => {
    it("returns idle for empty status text", () => {
      expect(deriveAutoRunStatus("")).toBe("idle");
    });

    it("returns hard_stop when HARD_STOP found", () => {
      expect(deriveAutoRunStatus("HARD_STOP — context below 10%")).toBe("hard_stop");
    });

    it("returns completed when all gates pass", () => {
      expect(deriveAutoRunStatus("Phase 4 COMPLETED — all gates pass")).toBe("completed");
    });

    it("returns idle for regular update message", () => {
      expect(deriveAutoRunStatus("Phase 4 next recommended")).toBe("idle");
    });
  });

  describe("AutoRunState type", () => {
    it("conforms to structure", () => {
      const state: AutoRunState = {
        currentPhase: "Phase 4",
        status: "idle",
        lastLoop: "",
        lastCommit: "",
        testsPass: 178,
        gatesStatus: "all_pass",
        nextRecommended: "Phase 5",
      };
      expect(state.status).toBe("idle");
      expect(state.testsPass).toBe(178);
    });
  });
});
