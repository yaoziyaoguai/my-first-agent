import { describe, it, expect } from "vitest";
import {
  listEvidenceFiles,
  parseEvidenceFile,
  normalizeVerdictCounts,
  buildEvidenceFileIndex,
  type EvidenceFileEntry,
} from "../data/evidenceBrowser";

const SAMPLE_JSON = JSON.stringify({
  date: "2026-05-31",
  evidence_id: "REAL-EVIDENCE-003",
  method: "current regression evidence",
  summary: { PASS: 13, FAIL: 0, CONCERN: 4, SKIP: 0 },
  results: [
    { case: "H2-direct-disallowed", verdict: "PASS", detail: "rejected" },
    { case: "S1-allowed-path", verdict: "PASS", detail: "executed" },
    { case: "request_user_input", verdict: "CONCERN", detail: "model avoidance" },
  ],
});

const SAMPLE_JSON_NO_SUMMARY_COUNTS = JSON.stringify({
  results: [
    { case: "case1", verdict: "PASS" },
    { case: "case2", verdict: "PASS" },
    { case: "case3", verdict: "FAIL" },
    { case: "case4", verdict: "CONCERN" },
    { case: "case5", verdict: "PASS" },
  ],
});

describe("evidenceBrowser", () => {
  describe("normalizeVerdictCounts", () => {
    it("extracts counts from summary object", () => {
      const json = JSON.parse(SAMPLE_JSON);
      const counts = normalizeVerdictCounts(json);
      expect(counts.pass).toBe(13);
      expect(counts.fail).toBe(0);
      expect(counts.concern).toBe(4);
    });

    it("counts results array when no summary counts", () => {
      const json = JSON.parse(SAMPLE_JSON_NO_SUMMARY_COUNTS);
      const counts = normalizeVerdictCounts(json);
      expect(counts.pass).toBe(3);
      expect(counts.fail).toBe(1);
      expect(counts.concern).toBe(1);
    });

    it("returns zeros for empty input", () => {
      const counts = normalizeVerdictCounts({});
      expect(counts.pass).toBe(0);
      expect(counts.fail).toBe(0);
      expect(counts.concern).toBe(0);
    });

    it("returns zeros for null", () => {
      const counts = normalizeVerdictCounts(null);
      expect(counts.pass).toBe(0);
      expect(counts.fail).toBe(0);
      expect(counts.concern).toBe(0);
    });
  });

  describe("parseEvidenceFile", () => {
    it("returns parsed entry for valid JSON", () => {
      const entry = parseEvidenceFile("real-evidence-003-results.json", SAMPLE_JSON);
      expect(entry.fileName).toBe("real-evidence-003-results.json");
      expect(entry.evidenceId).toBe("REAL-EVIDENCE-003");
      expect(entry.pass).toBe(13);
      expect(entry.concern).toBe(4);
      expect(entry.status).toBe("credible-with-caveats");
    });

    it("handles missing evidence_id gracefully", () => {
      const json = JSON.stringify({ summary: { PASS: 5 } });
      const entry = parseEvidenceFile("unknown.json", json);
      expect(entry.evidenceId).toBe("");
      expect(entry.pass).toBe(5);
    });

    it("returns unknown status for malformed JSON", () => {
      const entry = parseEvidenceFile("bad.json", "not valid json {");
      expect(entry.fileName).toBe("bad.json");
      expect(entry.status).toBe("unknown");
      expect(entry.error).toContain("parse error");
    });

    it("handles empty string gracefully", () => {
      const entry = parseEvidenceFile("empty.json", "");
      expect(entry.fileName).toBe("empty.json");
      expect(entry.status).toBe("unknown");
    });
  });

  describe("buildEvidenceFileIndex", () => {
    it("maps evidence IDs to evidence files", () => {
      const files: EvidenceFileEntry[] = [
        {
          fileName: "real-evidence-003-results.json",
          evidenceId: "REAL-EVIDENCE-003",
          pass: 13,
          fail: 0,
          concern: 4,
          status: "credible-with-caveats",
          error: "",
          date: "2026-05-31",
          caseCount: 17,
        },
        {
          fileName: "real-evidence-001-results.json",
          evidenceId: "REAL-EVIDENCE-001",
          pass: 8,
          fail: 0,
          concern: 0,
          status: "credible",
          error: "",
          date: "",
          caseCount: 8,
        },
      ];
      const index = buildEvidenceFileIndex(files);
      expect(index.has("REAL-EVIDENCE-003")).toBe(true);
      expect(index.has("REAL-EVIDENCE-001")).toBe(true);
      expect(index.get("REAL-EVIDENCE-003")?.pass).toBe(13);
    });

    it("skips entries with empty evidenceId", () => {
      const files: EvidenceFileEntry[] = [
        { fileName: "orphan.json", evidenceId: "", pass: 0, fail: 0, concern: 0, status: "unknown", error: "", date: "", caseCount: 0 },
      ];
      const index = buildEvidenceFileIndex(files);
      expect(index.size).toBe(0);
    });
  });

  describe("EvidenceFileEntry type", () => {
    it("conforms to structure", () => {
      const entry: EvidenceFileEntry = {
        fileName: "test.json",
        evidenceId: "REAL-EVIDENCE-001",
        pass: 10,
        fail: 0,
        concern: 2,
        status: "credible",
        error: "",
        date: "2026-06-01",
        caseCount: 12,
      };
      expect(entry.fileName).toBe("test.json");
    });
  });
});
