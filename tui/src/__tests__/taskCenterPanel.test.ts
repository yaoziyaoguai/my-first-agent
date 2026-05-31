import { describe, it, expect } from "vitest";
import {
  formatTaskStatusLabel,
  groupTasksByStatus,
  type TaskCenterItem,
} from "../data/tasks";

const SAMPLE_TASKS: TaskCenterItem[] = [
  { phase: "b8-phase-1", label: "B8 Phase 1", status: "completed", why: "Static dashboard done" },
  { phase: "b8-phase-2", label: "B8 Phase 2", status: "completed", why: "Command shell done" },
  { phase: "b8-phase-3", label: "B8 Phase 3", status: "recommended", why: "Current workbench" },
  { phase: "b8-phase-4", label: "B8 Phase 4", status: "deferred", why: "Need TUI maturity" },
  { phase: "b7", label: "B7 Multi-instance", status: "blocked", why: "Backend not ready" },
];

describe("TaskCenterPanel helpers", () => {
  it("formatTaskStatusLabel returns distinct labels per status", () => {
    const labels = new Set([
      formatTaskStatusLabel("completed"),
      formatTaskStatusLabel("recommended"),
      formatTaskStatusLabel("deferred"),
      formatTaskStatusLabel("blocked"),
      formatTaskStatusLabel("not-started"),
    ]);
    expect(labels.size).toBe(5);
  });

  it("formatTaskStatusLabel includes the status text", () => {
    const label = formatTaskStatusLabel("completed");
    expect(label.length).toBeGreaterThan(0);
    expect(label.toLowerCase()).toContain("completed");
  });

  it("groupTasksByStatus creates groups", () => {
    const groups = groupTasksByStatus(SAMPLE_TASKS);
    expect(Object.keys(groups).length).toBeGreaterThan(0);
  });

  it("groupTasksByStatus groups completed tasks together", () => {
    const groups = groupTasksByStatus(SAMPLE_TASKS);
    const completed = groups["completed"];
    expect(completed).toBeDefined();
    expect(completed!.length).toBe(2);
    expect(completed!.every((t) => t.status === "completed")).toBe(true);
  });

  it("groupTasksByStatus groups recommended tasks", () => {
    const groups = groupTasksByStatus(SAMPLE_TASKS);
    const recommended = groups["recommended"];
    expect(recommended).toBeDefined();
    expect(recommended!.length).toBe(1);
    expect(recommended![0].phase).toBe("b8-phase-3");
  });

  it("groupTasksByStatus handles empty array", () => {
    const groups = groupTasksByStatus([]);
    expect(Object.keys(groups).length).toBe(0);
  });

  it("groupTasksByStatus preserves why field", () => {
    const groups = groupTasksByStatus(SAMPLE_TASKS);
    const recommended = groups["recommended"];
    expect(recommended![0].why).toBe("Current workbench");
  });
});
