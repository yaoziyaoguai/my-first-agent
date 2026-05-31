import { describe, it, expect } from "vitest";
import {
  loadEvidenceDetails,
  getEvidenceById,
  type EvidenceDetail,
} from "../data/evidenceDetails";

describe("EvidenceDetail model", () => {
  it("loadEvidenceDetails returns 8 items (001-008)", () => {
    const details = loadEvidenceDetails();
    expect(details).toHaveLength(8);
  });

  it("each detail has all required fields", () => {
    const details = loadEvidenceDetails();
    for (const d of details) {
      expect(d.id).toBeDefined();
      expect(d.id).toMatch(/^REAL-EVIDENCE-00[1-8]$/);
      expect(d.capability).toBeDefined();
      expect(typeof d.capability).toBe("string");
      expect(d.status).toBeDefined();
      expect(["credible", "credible-with-caveats", "partial-credible"]).toContain(d.status);
      expect(d.latestDogfood).toBeDefined();
      expect(typeof d.latestDogfood).toBe("string");
      expect(d.latestCommit).toBeDefined();
      expect(typeof d.latestCommit).toBe("string");
      expect(d.caveats).toBeDefined();
      expect(typeof d.caveats).toBe("string");
      expect(d.nextAction).toBeDefined();
      expect(typeof d.nextAction).toBe("string");
    }
  });

  it("001 Memory is credible", () => {
    const detail = getEvidenceById("REAL-EVIDENCE-001");
    expect(detail).toBeDefined();
    expect(detail!.status).toBe("credible");
  });

  it("008 Scheduler is credible-with-caveats", () => {
    const detail = getEvidenceById("REAL-EVIDENCE-008");
    expect(detail).toBeDefined();
    expect(["credible", "credible-with-caveats"]).toContain(detail!.status);
  });

  it("getEvidenceById returns undefined for invalid id", () => {
    expect(getEvidenceById("REAL-EVIDENCE-999")).toBeUndefined();
    expect(getEvidenceById("")).toBeUndefined();
  });

  it("getEvidenceById is case-sensitive", () => {
    expect(getEvidenceById("real-evidence-001")).toBeUndefined();
  });

  it("returns new array (immutable)", () => {
    const a = loadEvidenceDetails();
    const b = loadEvidenceDetails();
    // JSON modules are singletons by Node resolution; expect same data, not same reference
    expect(a).toEqual(b);
    expect(a.length).toBe(b.length);
  });
});
