/** Phase 5: Review packet from git log + test output */
export interface ReviewPacket {
  currentPhase: string;
  recentCommits: string[];
  testSummary: string;
  gatesResult: "all_pass" | "partial" | "failed";
}

interface ParsedCommit {
  hash: string;
  message: string;
}

export function parseGitLogForReview(gitLog: string): ParsedCommit[] {
  if (!gitLog.trim()) return [];
  return gitLog
    .trim()
    .split("\n")
    .map((line) => {
      const [hash, ...rest] = line.split(" ");
      return {
        hash: hash ?? "",
        message: rest.join(" "),
      };
    })
    .filter((c) => c.hash.length >= 7);
}

export function buildReviewPacket(
  phase: string,
  gitLog: string,
  testOutput: string,
): ReviewPacket {
  const commits = parseGitLogForReview(gitLog);
  const testMatch = testOutput.match(/Tests\s+(\d+)\s+passed/);

  return {
    currentPhase: phase,
    recentCommits: commits.map((c) => `${c.hash} ${c.message}`),
    testSummary: testMatch
      ? `${testMatch[1]}/ tests PASS`
      : "tests summary unavailable",
    gatesResult: testOutput.includes("failed") ? "failed" : "all_pass",
  };
}
