import { describe, it, expect } from "vitest";
import {
  buildReviewPacket,
  parseGitLogForReview,
  type ReviewPacket,
} from "../data/reviewPacket";

const SAMPLE_GIT_LOG = `54aad3a feat(tui): add safe command execution with confirmation
17f2493 docs(tui): harden B8 autorun roadmap
2ae13ab feat(tui): add Phase 3 default workbench readiness
3c8e178 feat(tui): add Phase 2 command shell and workflow launcher
eba77ad feat(tui): add B8-lite Phase 1 static dashboard`;

const SAMPLE_TEST_OUTPUT = `Test Files  20 passed (20)
     Tests  178 passed (178)`;

describe("reviewPacket", () => {
  describe("parseGitLogForReview", () => {
    it("extracts commit hashes and messages", () => {
      const commits = parseGitLogForReview(SAMPLE_GIT_LOG);
      expect(commits.length).toBe(5);
      expect(commits[0].hash).toBe("54aad3a");
      expect(commits[0].message).toContain("feat(tui)");
    });

    it("returns empty array for empty log", () => {
      const commits = parseGitLogForReview("");
      expect(commits).toEqual([]);
    });
  });

  describe("buildReviewPacket", () => {
    it("builds review packet from git log and test output", () => {
      const packet = buildReviewPacket("Phase 4", SAMPLE_GIT_LOG, SAMPLE_TEST_OUTPUT);
      expect(packet.currentPhase).toBe("Phase 4");
      expect(packet.recentCommits.length).toBe(5);
      expect(packet.recentCommits[0]).toContain("54aad3a");
    });

    it("includes test summary", () => {
      const packet = buildReviewPacket("Phase 4", SAMPLE_GIT_LOG, SAMPLE_TEST_OUTPUT);
      expect(packet.testSummary).toContain("178");
    });

    it("handles empty test output gracefully", () => {
      const packet = buildReviewPacket("Phase 4", SAMPLE_GIT_LOG, "");
      expect(packet.testSummary).toBeDefined();
    });

    it("handles empty git log gracefully", () => {
      const packet = buildReviewPacket("Phase 4", "", SAMPLE_TEST_OUTPUT);
      expect(packet.recentCommits).toEqual([]);
    });
  });

  describe("ReviewPacket type", () => {
    it("conforms to structure", () => {
      const packet: ReviewPacket = {
        currentPhase: "Phase 4",
        recentCommits: ["54aad3a feat(tui): add phase 4"],
        testSummary: "178/178 PASS",
        gatesResult: "all_pass",
      };
      expect(packet.currentPhase).toBe("Phase 4");
      expect(packet.gatesResult).toBe("all_pass");
    });
  });
});
