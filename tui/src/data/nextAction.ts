import { readFileSync } from "node:fs";
import { parseProjectStatus } from "./projectStatus";

export function loadNextAction(docPath?: string): string {
  try {
    const raw = readFileSync(
      docPath ?? "docs/PROJECT_STATUS.md",
      "utf-8",
    );
    const status = parseProjectStatus(raw);
    if (status.recommendedNext && status.recommendedNext.trim().length > 0) {
      return status.recommendedNext;
    }
    return "暂无推荐下一步";
  } catch {
    return "暂无推荐下一步（PROJECT_STATUS.md 不可用）";
  }
}
