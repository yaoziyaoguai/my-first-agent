import { describe, it, expect, vi } from "vitest";
import { loadNextAction } from "../data/nextAction";
import { parseProjectStatus } from "../data/projectStatus";

describe("nextAction", () => {
  describe("loadNextAction", () => {
    it("returns the recommended next action from PROJECT_STATUS", () => {
      const doc = [
        "## 0. Current Verdict",
        "",
        "**Score**: 4.5/5 conservative baseline",
        "",
        "**推荐下一步：B8-lite Phase 2: TUI command shell**",
      ].join("\n");
      const status = parseProjectStatus(doc);
      expect(status.recommendedNext).toContain("B8-lite");
    });

    it("returns fallback message when recommendedNext is empty", () => {
      const doc = [
        "## 0. Current Verdict",
        "",
        "**Score**: 4.5/5",
        "",
        "**推荐下一步：**",
      ].join("\n");
      const status = parseProjectStatus(doc);
      expect(status.recommendedNext).toBe("");
    });

    it("returns fallback when PROJECT_STATUS.md is unavailable", () => {
      const result = loadNextAction("/nonexistent/path/to/file.md");
      expect(result).toContain("暂无推荐");
    });
  });
});
