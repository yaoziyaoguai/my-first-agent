import { describe, it, expect } from "vitest";
import {
  VIEWS,
  createNavigationState,
  navigateTo,
  navigateNext,
  navigatePrev,
  getCurrentView,
  type ViewId,
  type NavigationState,
} from "../data/navigation";

describe("Navigation model", () => {
  it("VIEWS contains all 7 expected views", () => {
    const ids = VIEWS.map((v) => v.id);
    expect(ids).toContain("overview");
    expect(ids).toContain("evidence");
    expect(ids).toContain("workflow");
    expect(ids).toContain("commands");
    expect(ids).toContain("tasks");
    expect(ids).toContain("gates");
    expect(ids).toContain("docs");
    expect(VIEWS).toHaveLength(7);
  });

  it("createNavigationState starts at overview", () => {
    const state = createNavigationState();
    expect(state.currentView).toBe("overview");
  });

  it("navigateTo switches to a valid view", () => {
    const state = createNavigationState();
    const next = navigateTo(state, "tasks");
    expect(next.currentView).toBe("tasks");
  });

  it("navigateTo returns same state for invalid view", () => {
    const state = createNavigationState();
    const next = navigateTo(state, "nonexistent" as ViewId);
    expect(next.currentView).toBe("overview");
  });

  it("navigateNext cycles forward through views", () => {
    const state = createNavigationState();
    const s1 = navigateNext(state);
    expect(s1.currentView).toBe("evidence");
    const s2 = navigateNext(s1);
    expect(s2.currentView).toBe("workflow");
  });

  it("navigateNext wraps from last to first", () => {
    const state: NavigationState = { currentView: "docs" };
    const next = navigateNext(state);
    expect(next.currentView).toBe("overview");
  });

  it("navigatePrev wraps from first to last", () => {
    const state = createNavigationState();
    const prev = navigatePrev(state);
    expect(prev.currentView).toBe("docs");
  });

  it("navigatePrev cycles backward through views", () => {
    const state: NavigationState = { currentView: "commands" };
    const prev = navigatePrev(state);
    expect(prev.currentView).toBe("workflow");
  });

  it("navigation state is immutable", () => {
    const state = createNavigationState();
    const next = navigateTo(state, "tasks");
    expect(state.currentView).toBe("overview");
    expect(next.currentView).toBe("tasks");
    expect(state).not.toBe(next);
  });

  it("getCurrentView returns the current ViewDef", () => {
    const state: NavigationState = { currentView: "gates" };
    const view = getCurrentView(state);
    expect(view).toBeDefined();
    expect(view!.id).toBe("gates");
    expect(view!.label).toBeDefined();
  });

  it("getCurrentView returns undefined for unknown view", () => {
    const state: NavigationState = { currentView: "unknown" as ViewId };
    const view = getCurrentView(state);
    expect(view).toBeUndefined();
  });
});
