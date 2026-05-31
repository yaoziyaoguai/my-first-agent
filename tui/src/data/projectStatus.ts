import type { ProjectStatus, RealEvidenceRow } from "../types";

/** 从 PROJECT_STATUS.md 文本中解析结构化数据 */
export function parseProjectStatus(doc: string): ProjectStatus {
  return {
    lastUpdated: extractLastUpdated(doc),
    score: extractScore(doc),
    credibleCount: extractCredibleCount(doc),
    overallVerdict: extractOverallVerdict(doc),
    recommendedNext: extractRecommendedNext(doc),
    realEvidenceRows: extractRealEvidenceRows(doc),
  };
}

function extractLastUpdated(doc: string): string {
  const m = doc.match(/\*\*最后更新\*\*:\s*(.+)/);
  return m ? m[1].trim() : "";
}

function extractScore(doc: string): string {
  // "Score 4.5/5" 通常出现在状态行
  const m = doc.match(/Score\s+([\d.]+)\/5/);
  return m ? `${m[1]}/5 conservative baseline` : "";
}

function extractCredibleCount(doc: string): string {
  // "Credible: 7/8 ... Credible-with-caveats: 1/8"
  const lines = doc.split("\n");
  for (const line of lines) {
    const lower = line.toLowerCase();
    if (lower.includes("credible:") && lower.includes("credible-with-caveats")) {
      // 清理 markdown 加粗标记
      return line.replace(/\*/g, "").trim();
    }
  }
  return "";
}

function extractOverallVerdict(doc: string): string {
  // 在 Current Verdict 表格中找 "总体判断" 行
  const lines = doc.split("\n");
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].includes("| 总体判断 |")) {
      return lines[i].split("|")[2]?.trim() ?? "";
    }
  }
  return "";
}

function extractRecommendedNext(doc: string): string {
  // "**推荐下一步：...**"
  const m = doc.match(/\*\*推荐下一步[：:]\s*(.+?)\*\*/);
  return m ? m[1].trim() : "";
}

function extractRealEvidenceRows(doc: string): RealEvidenceRow[] {
  const rows: RealEvidenceRow[] = [];
  const lines = doc.split("\n");
  let inTable = false;

  for (const line of lines) {
    // 检测 REAL-EVIDENCE closure credibility 表格
    if (
      line.includes("| ID |") &&
      line.includes("Capability") &&
      line.toLowerCase().includes("credibility")
    ) {
      inTable = true;
      continue;
    }
    if (inTable) {
      // 表格结束: 空行或新的 section
      if (!line.startsWith("|") || line.trim() === "") {
        inTable = false;
        continue;
      }
      // 跳过表头分隔行
      if (line.includes("|---")) continue;

      const cols = line.split("|").map((c) => c.trim());
      // cols[0] 为空 (行首 |), cols[1]=ID, cols[2]=Capability, cols[3]=status, cols[4]=notes
      const id = cols[1] ?? "";
      if (!id.startsWith("REAL-EVIDENCE-")) continue;

      const status = parseCredibilityStatus(cols[3] ?? "");
      rows.push({
        id,
        capability: cols[2] ?? "",
        status,
        notes: cols[4] ?? "",
      });
    }
  }

  return rows;
}

function parseCredibilityStatus(
  text: string,
): "credible" | "credible-with-caveats" | "partial-credible" {
  if (text.includes("credible-with-caveats")) return "credible-with-caveats";
  if (text.includes("partial-credible")) return "partial-credible";
  if (text.includes("credible")) return "credible";
  return "partial-credible";
}
