import { describe, it, expect } from "vitest";
import { parseDogfoodResult } from "../data/dogfoodResults";

describe("parseDogfoodResult", () => {
  it("extracts pass/fail/concern from result JSON", () => {
    const json = {
      pass: 13,
      fail: 0,
      concern: 4,
      summary: "003 hardening v3 results",
      results: [
        { case_id: "H1", verdict: "PASS" },
        { case_id: "H2a", verdict: "CONCERN" },
      ],
    };
    const r = parseDogfoodResult("test-file.json", json);
    expect(r.fileName).toBe("test-file.json");
    expect(r.pass).toBe(13);
    expect(r.fail).toBe(0);
    expect(r.concern).toBe(4);
    expect(r.summary).toBe("003 hardening v3 results");
  });

  it("handles missing fields with defaults", () => {
    const r = parseDogfoodResult("empty.json", {});
    expect(r.pass).toBe(0);
    expect(r.fail).toBe(0);
    expect(r.concern).toBe(0);
    expect(r.summary).toBe("");
  });

  it("handles pass/fail/concern as zero", () => {
    const r = parseDogfoodResult("zero.json", { pass: 0, fail: 0, concern: 0 });
    expect(r.pass).toBe(0);
    expect(r.fail).toBe(0);
    expect(r.concern).toBe(0);
  });

  it("handles null/undefined values", () => {
    const r = parseDogfoodResult("nulls.json", {
      pass: null,
      fail: undefined,
      concern: "not-a-number",
    });
    expect(r.pass).toBe(0);
    expect(r.fail).toBe(0);
    expect(r.concern).toBe(0);
  });

  it("counts verdicts from results array when top-level counts missing", () => {
    const json = {
      results: [
        { case_id: "R1", verdict: "PASS" },
        { case_id: "R2", verdict: "PASS" },
        { case_id: "R3", verdict: "CONCERN" },
        { case_id: "R4", verdict: "FAIL" },
        { case_id: "R5", verdict: "SKIP" },
      ],
    };
    const r = parseDogfoodResult("counts.json", json);
    expect(r.pass).toBe(2);
    expect(r.concern).toBe(1);
    expect(r.fail).toBe(1);
  });
});
