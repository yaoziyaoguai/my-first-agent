import type { ProgressLedger, Milestone } from "../types";

/** 从 PROGRESS_LEDGER.md 文本中解析里程碑列表 */
export function parseProgressLedger(doc: string): ProgressLedger {
  const milestones: Milestone[] = [];
  const lines = doc.split("\n");
  let currentDate = "";

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    // 日期标题: "## 2026-05-31"
    const dateMatch = line.match(/^##\s+(\d{4}-\d{2}-\d{2})/);
    if (dateMatch) {
      currentDate = dateMatch[1];
      continue;
    }

    // 表格标题行: "| Milestone | Commit | 简述 |" — 跳过它和分隔行
    if (
      line.includes("| Milestone |") ||
      line.includes("|---")
    ) {
      continue;
    }

    // 数据行: "| **title** | commit | summary |"
    if (line.startsWith("|") && currentDate) {
      const cols = line.split("|").map((c) => c.trim());
      // cols[0]="", cols[1]=title, cols[2]=commit, cols[3]=summary, cols[4]=""
      const title = stripBold(cols[1] ?? "");
      const commit = cols[2] === "—" ? "" : (cols[2] ?? "");
      const summary = cols[3] ?? "";

      if (title) {
        milestones.push({ date: currentDate, title, commit, summary });
      }
    }
  }

  return { milestones };
}

function stripBold(text: string): string {
  return text.replace(/\*\*/g, "").trim();
}
