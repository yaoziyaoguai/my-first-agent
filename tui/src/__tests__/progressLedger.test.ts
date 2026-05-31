import { describe, it, expect } from "vitest";
import { parseProgressLedger } from "../data/progressLedger";

describe("parseProgressLedger", () => {
  const minimalDoc = `# Progress Ledger — First Agent

**最后更新**: 2026-05-31

## 2026-05-31

| Milestone | Commit | 简述 |
|-----------|--------|------|
| **003 Loop 8** | 29aafd8 | 003 upgraded to credible |
| **002 SDD vNext** | — | SPEC/SDD phase complete |

## 2026-05-30

| Milestone | Commit | 简述 |
|-----------|--------|------|
| **003 hardening** | — | H2 direct+indirect PASS |
`;

  it("extracts milestones with dates", () => {
    const r = parseProgressLedger(minimalDoc);
    expect(r.milestones.length).toBeGreaterThanOrEqual(3);
    expect(r.milestones[0]).toMatchObject({
      date: "2026-05-31",
      title: "003 Loop 8",
      commit: "29aafd8",
    });
    expect(r.milestones[0].summary).toContain("003 upgraded to credible");
  });

  it("extracts milestone with no commit", () => {
    const r = parseProgressLedger(minimalDoc);
    const noCommit = r.milestones.find((m) => m.title === "003 hardening");
    expect(noCommit).toBeDefined();
    expect(noCommit!.commit).toBe("");
  });

  it("assigns correct date to each milestone", () => {
    const r = parseProgressLedger(minimalDoc);
    const may31 = r.milestones.filter((m) => m.date === "2026-05-31");
    const may30 = r.milestones.filter((m) => m.date === "2026-05-30");
    expect(may31.length).toBeGreaterThanOrEqual(2);
    expect(may30.length).toBeGreaterThanOrEqual(1);
  });

  it("handles empty input", () => {
    const r = parseProgressLedger("");
    expect(r.milestones).toHaveLength(0);
  });

  it("handles doc without milestone tables", () => {
    const r = parseProgressLedger("# Just a header\n\nNo tables here.");
    expect(r.milestones).toHaveLength(0);
  });

  it("handles non-standard summary text (no bold markers)", () => {
    const doc = `## 2026-05-31

| Milestone | Commit | 简述 |
|-----------|--------|------|
| plain title | abc123 | plain summary |
`;
    const r = parseProgressLedger(doc);
    expect(r.milestones).toHaveLength(1);
    expect(r.milestones[0].title).toBe("plain title");
  });
});
