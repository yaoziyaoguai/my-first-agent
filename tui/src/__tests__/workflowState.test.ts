import { describe, it, expect } from "vitest";
import {
  parseWorkflowState,
  type WorkflowState,
} from "../data/workflowState";

const SAMPLE_RAW_STATE = {
  currentStage: "B8 Phase 3",
  completedMilestones: [
    { name: "B8 Phase 1", commit: "eba77ad", date: "2026-05-31" },
    { name: "B8 Phase 2", commit: "3c8e178", date: "2026-06-01" },
  ],
  deferredItems: [
    { name: "B8 Phase 4 (Safe Execution)", reason: "pending TUI maturity" },
    { name: "B8 Phase 5 (Real-time Stream)", reason: "needs runtime infra" },
    { name: "B7 Multi-instance", reason: "backend not ready" },
  ],
  nextRecommended: "B8 Phase 3 Default Workbench Readiness",
};

describe("WorkflowState parser", () => {
  it("parses currentStage", () => {
    const state = parseWorkflowState(SAMPLE_RAW_STATE);
    expect(state.currentStage).toBe("B8 Phase 3");
  });

  it("parses completedMilestones", () => {
    const state = parseWorkflowState(SAMPLE_RAW_STATE);
    expect(state.completedMilestones).toHaveLength(2);
    expect(state.completedMilestones[0].name).toBe("B8 Phase 1");
    expect(state.completedMilestones[0].commit).toBe("eba77ad");
    expect(state.completedMilestones[1].name).toBe("B8 Phase 2");
  });

  it("parses deferredItems", () => {
    const state = parseWorkflowState(SAMPLE_RAW_STATE);
    expect(state.deferredItems).toHaveLength(3);
    expect(state.deferredItems[0].name).toBe("B8 Phase 4 (Safe Execution)");
    expect(state.deferredItems[0].reason).toBeDefined();
  });

  it("parses nextRecommended", () => {
    const state = parseWorkflowState(SAMPLE_RAW_STATE);
    expect(state.nextRecommended).toBe("B8 Phase 3 Default Workbench Readiness");
  });

  it("handles empty completedMilestones", () => {
    const state = parseWorkflowState({
      currentStage: "B8 Phase 1",
      completedMilestones: [],
      deferredItems: [],
      nextRecommended: "",
    });
    expect(state.completedMilestones).toHaveLength(0);
    expect(state.currentStage).toBe("B8 Phase 1");
  });

  it("handles missing optional fields", () => {
    const state = parseWorkflowState({
      currentStage: "initial",
    });
    expect(state.currentStage).toBe("initial");
    expect(state.completedMilestones).toHaveLength(0);
    expect(state.deferredItems).toHaveLength(0);
    expect(state.nextRecommended).toBe("");
  });

  it("returns new object (immutable)", () => {
    const input = { ...SAMPLE_RAW_STATE };
    const state = parseWorkflowState(input);
    expect(state).not.toBe(input as unknown as WorkflowState);
  });
});
