import { describe, it, expect } from "vitest";
import { parseGitStatus, parseGitLog } from "../data/gitInfo";

describe("parseGitStatus", () => {
  it("parses clean working tree", () => {
    const r = parseGitStatus("");
    expect(r).toHaveLength(0);
  });

  it("parses untracked files", () => {
    const stdout = "?? demo.md\n?? task_design.md";
    const r = parseGitStatus(stdout);
    expect(r).toHaveLength(2);
    expect(r[0]).toBe("?? demo.md");
  });

  it("parses modified files", () => {
    const stdout = " M src/main.tsx\n M package.json";
    const r = parseGitStatus(stdout);
    expect(r).toHaveLength(2);
  });

  it("parses mixed status", () => {
    const stdout = " M modified.ts\n?? untracked.ts\n D deleted.ts";
    const r = parseGitStatus(stdout);
    expect(r).toHaveLength(3);
  });

  it("handles empty lines", () => {
    const r = parseGitStatus("\n\n?? file.ts\n\n");
    expect(r).toHaveLength(1);
    expect(r[0]).toBe("?? file.ts");
  });
});

describe("parseGitLog", () => {
  it("parses git log oneline output", () => {
    const stdout =
      "891d002 docs(status): finalize real evidence closure state\n29aafd8 fix(skill): close 003 allowed-tools caveats";
    const r = parseGitLog(stdout);
    expect(r).toHaveLength(2);
    expect(r[0]).toMatchObject({
      hash: "891d002",
      message: "docs(status): finalize real evidence closure state",
    });
    expect(r[1].hash).toBe("29aafd8");
  });

  it("handles single commit", () => {
    const r = parseGitLog("abc123 feat: add feature");
    expect(r).toHaveLength(1);
  });

  it("handles empty output", () => {
    const r = parseGitLog("");
    expect(r).toHaveLength(0);
  });

  it("handles commits with long messages", () => {
    const stdout = "abc123 feat: a very long commit message with many details";
    const r = parseGitLog(stdout);
    expect(r).toHaveLength(1);
    expect(r[0].message).toBe(
      "feat: a very long commit message with many details"
    );
  });
});
