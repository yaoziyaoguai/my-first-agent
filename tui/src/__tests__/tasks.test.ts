import { describe, it, expect } from "vitest";
import {
  loadTasks,
  getTasksByStatus,
  type TaskCenterItem,
  type TaskStatus,
} from "../data/tasks";

describe("TaskCenter data model", () => {
  it("loadTasks returns non-empty array", () => {
    const tasks = loadTasks();
    expect(tasks.length).toBeGreaterThan(0);
  });

  it("each task has required fields", () => {
    const tasks = loadTasks();
    for (const task of tasks) {
      expect(task.phase).toBeDefined();
      expect(typeof task.phase).toBe("string");
      expect(task.label).toBeDefined();
      expect(typeof task.label).toBe("string");
      expect(task.status).toBeDefined();
      expect(["recommended", "deferred", "blocked", "completed", "not-started"]).toContain(task.status);
      expect(task.why).toBeDefined();
      expect(typeof task.why).toBe("string");
    }
  });

  it("contains B8 Phase 1 and Phase 2 as completed", () => {
    const tasks = loadTasks();
    const phase1 = tasks.find((t) => t.phase === "b8-phase-1");
    const phase2 = tasks.find((t) => t.phase === "b8-phase-2");
    expect(phase1).toBeDefined();
    expect(phase1!.status).toBe("completed");
    expect(phase2).toBeDefined();
    expect(phase2!.status).toBe("completed");
  });

  it("Phase 3/4/5 are completed, Polish is recommended", () => {
    const tasks = loadTasks();
    const phase3 = tasks.find((t) => t.phase === "b8-phase-3");
    const phase4 = tasks.find((t) => t.phase === "b8-phase-4");
    const phase5 = tasks.find((t) => t.phase === "b8-phase-5");
    const polish = tasks.find((t) => t.phase === "b8-polish");
    expect(phase3).toBeDefined();
    expect(phase3!.status).toBe("completed");
    expect(phase4).toBeDefined();
    expect(phase4!.status).toBe("completed");
    expect(phase5).toBeDefined();
    expect(phase5!.status).toBe("completed");
    expect(polish).toBeDefined();
    expect(polish!.status).toBe("completed");
  });

  it("getTasksByStatus filters correctly", () => {
    const tasks: TaskCenterItem[] = [
      { phase: "a", label: "A", status: "completed", why: "done" },
      { phase: "b", label: "B", status: "recommended", why: "current" },
      { phase: "c", label: "C", status: "deferred", why: "later" },
      { phase: "d", label: "D", status: "completed", why: "done too" },
    ];
    const completed = getTasksByStatus(tasks, "completed");
    expect(completed).toHaveLength(2);
    expect(completed.every((t) => t.status === "completed")).toBe(true);

    const recommended = getTasksByStatus(tasks, "recommended");
    expect(recommended).toHaveLength(1);
    expect(recommended[0].phase).toBe("b");
  });

  it("getTasksByStatus returns empty array when no match", () => {
    const tasks: TaskCenterItem[] = [
      { phase: "a", label: "A", status: "completed", why: "done" },
    ];
    expect(getTasksByStatus(tasks, "blocked")).toHaveLength(0);
  });

  it("getTasksByStatus handles empty input", () => {
    expect(getTasksByStatus([], "completed")).toHaveLength(0);
  });
});
