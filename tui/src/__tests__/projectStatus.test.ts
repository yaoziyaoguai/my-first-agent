import { describe, it, expect } from "vitest";
import { parseProjectStatus } from "../data/projectStatus";

describe("parseProjectStatus", () => {
  const minimalDoc = `# Project Status — First Agent

**最后更新**: 2026-05-31
**状态**: Score 4.5/5。Credible: 7/8 (001/002/003/004/005/006/008), Credible-with-caveats: 1/8 (007)

## 0. Independent Re-Audit Override

### Current Verdict

| 项目 | 当前复审结论 |
|------|--------------|
| 当前 independent combined review score | 4.5/5 — conservative baseline |
| 总体判断 | 明显改善。not product-ready；B7/B8 excluded |
| REAL-EVIDENCE closure credibility | 7/8 credible, 1/8 credible-with-caveats (007) |

### Corrected REAL-EVIDENCE Closure Credibility

| ID | Capability | Closure credibility | Notes |
|----|------------|---------------------|-------|
| REAL-EVIDENCE-001 | Memory retain/recall/forget | credible | positive assertions fine |
| REAL-EVIDENCE-007 | MCP external flight | credible-with-caveats | validation scope note |

## 2. 推荐下一步

**推荐下一步：B8-lite TS TUI observer**`;

  it("extracts last updated date", () => {
    const r = parseProjectStatus(minimalDoc);
    expect(r.lastUpdated).toBe("2026-05-31");
  });

  it("extracts score", () => {
    const r = parseProjectStatus(minimalDoc);
    expect(r.score).toContain("4.5/5");
  });

  it("extracts credible count", () => {
    const r = parseProjectStatus(minimalDoc);
    expect(r.credibleCount).toContain("7/8");
    expect(r.credibleCount.toLowerCase()).toContain("credible-with-caveats");
  });

  it("extracts overall verdict", () => {
    const r = parseProjectStatus(minimalDoc);
    expect(r.overallVerdict).toContain("明显改善");
    expect(r.overallVerdict).toContain("not product-ready");
  });

  it("extracts recommended next step", () => {
    const r = parseProjectStatus(minimalDoc);
    expect(r.recommendedNext).toContain("B8-lite TS TUI observer");
  });

  it("extracts REAL-EVIDENCE rows", () => {
    const r = parseProjectStatus(minimalDoc);
    expect(r.realEvidenceRows).toHaveLength(2);
    expect(r.realEvidenceRows[0]).toMatchObject({
      id: "REAL-EVIDENCE-001",
      capability: "Memory retain/recall/forget",
      status: "credible",
    });
    expect(r.realEvidenceRows[1]).toMatchObject({
      id: "REAL-EVIDENCE-007",
      capability: "MCP external flight",
      status: "credible-with-caveats",
    });
  });

  it("handles missing sections gracefully", () => {
    const r = parseProjectStatus("# Empty doc");
    expect(r.realEvidenceRows).toHaveLength(0);
    expect(r.recommendedNext).toBe("");
  });

  it("handles empty input", () => {
    const r = parseProjectStatus("");
    expect(r.score).toBe("");
    expect(r.realEvidenceRows).toHaveLength(0);
  });
});
