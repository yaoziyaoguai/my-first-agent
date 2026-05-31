import { describe, it, expect } from "vitest";
import {
  formatNavigationLabel,
  getViewIndex,
  getViewCount,
  type NavigationState,
  type ViewId,
} from "../data/navigation";

describe("NavigationBar helpers", () => {
  it("formatNavigationLabel shows current view name", () => {
    const label = formatNavigationLabel("overview");
    expect(label).toContain("Overview");
  });

  it("formatNavigationLabel has different output for different views", () => {
    const a = formatNavigationLabel("overview");
    const b = formatNavigationLabel("tasks");
    expect(a).not.toBe(b);
  });

  it("getViewIndex returns 0 for overview", () => {
    expect(getViewIndex("overview")).toBe(0);
  });

  it("getViewIndex returns correct index for each view", () => {
    const order: ViewId[] = ["overview", "evidence", "workflow", "commands", "tasks", "gates", "docs"];
    for (let i = 0; i < order.length; i++) {
      expect(getViewIndex(order[i])).toBe(i);
    }
  });

  it("getViewIndex returns -1 for invalid view", () => {
    expect(getViewIndex("nonexistent" as ViewId)).toBe(-1);
  });

  it("getViewCount returns 7", () => {
    expect(getViewCount()).toBe(7);
  });

  it("formatNavigationLabel returns non-empty string for each view", () => {
    const views: ViewId[] = ["overview", "evidence", "workflow", "commands", "tasks", "gates", "docs"];
    for (const v of views) {
      const label = formatNavigationLabel(v);
      expect(label.length).toBeGreaterThan(0);
    }
  });
});
