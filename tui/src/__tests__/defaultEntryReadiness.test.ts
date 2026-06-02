import { describe, it, expect } from "vitest";
import {
  getReadinessItems,
  getReadinessSummary,
  STATUS_LABELS,
  STATUS_COLORS,
  type ReadinessItem,
  type ReadinessStatus,
} from "../data/defaultEntryReadiness";

describe("defaultEntryReadiness", () => {
  describe("getReadinessItems", () => {
    it("returns 18 readiness items", () => {
      const items = getReadinessItems();
      expect(items).toHaveLength(18);
    });

    it("each item has id, label, description, status", () => {
      for (const item of getReadinessItems()) {
        expect(item.id).toBeTruthy();
        expect(item.label).toBeTruthy();
        expect(item.description).toBeTruthy();
        expect(item.status).toBeTruthy();
      }
    });

    it("at least 12 items are done (M5/M6/M7/M8 completed)", () => {
      const items = getReadinessItems();
      const done = items.filter((i) => i.status === "done");
      expect(done.length).toBeGreaterThanOrEqual(12);
    });

    it("has blocked-b7 items for multi-instance + event stream", () => {
      const items = getReadinessItems();
      const b7blocked = items.filter((i) => i.status === "blocked-b7");
      expect(b7blocked.length).toBeGreaterThanOrEqual(2);
    });

    it("has blocked-ime item", () => {
      const items = getReadinessItems();
      const imeBlocked = items.filter((i) => i.status === "blocked-ime");
      expect(imeBlocked.length).toBeGreaterThanOrEqual(1);
    });

    it("CLI fallback item is done", () => {
      const items = getReadinessItems();
      const cli = items.find((i) => i.id === "R16");
      expect(cli?.status).toBe("done");
    });

    it("TUI default entry is NOT ACTIVATED (done = explicitly maintained)", () => {
      const items = getReadinessItems();
      const activation = items.find((i) => i.id === "R17");
      expect(activation?.status).toBe("done");
      expect(activation?.label).toContain("NOT ACTIVATED");
    });

    it("no second runtime guard is done", () => {
      const items = getReadinessItems();
      const guard = items.find((i) => i.id === "R18");
      expect(guard?.status).toBe("done");
    });
  });

  describe("getReadinessSummary", () => {
    it("returns correct totals", () => {
      const summary = getReadinessSummary();
      expect(summary.done + summary.blocked + summary.pending).toBe(summary.total);
      expect(summary.total).toBe(18);
    });
  });

  describe("STATUS_LABELS", () => {
    it("has labels for all statuses", () => {
      const statuses: ReadinessStatus[] = [
        "done",
        "blocked-b8-debt",
        "blocked-b7",
        "blocked-ime",
        "pending",
      ];
      for (const s of statuses) {
        expect(STATUS_LABELS[s]).toBeTruthy();
      }
    });
  });

  describe("STATUS_COLORS", () => {
    it("has colors for all statuses", () => {
      const statuses: ReadinessStatus[] = [
        "done",
        "blocked-b8-debt",
        "blocked-b7",
        "blocked-ime",
        "pending",
      ];
      for (const s of statuses) {
        expect(STATUS_COLORS[s]).toBeTruthy();
      }
    });

    it("done is green", () => {
      expect(STATUS_COLORS["done"]).toBe("green");
    });

    it("blocked statuses use yellow", () => {
      expect(STATUS_COLORS["blocked-b8-debt"]).toBe("yellow");
      expect(STATUS_COLORS["blocked-b7"]).toBe("yellow");
    });
  });

  describe("ReadinessItem type", () => {
    it("conforms to structure", () => {
      const item: ReadinessItem = {
        id: "R01",
        label: "Test item",
        description: "Test description",
        status: "done",
      };
      expect(item.id).toBe("R01");
      expect(item.label).toBe("Test item");
      expect(item.description).toBe("Test description");
      expect(item.status).toBe("done");
    });
  });
});
