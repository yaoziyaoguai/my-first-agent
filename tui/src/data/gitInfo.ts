import type { GitInfo, CommitInfo } from "../types";

/** 解析 git status --short 输出为脏文件列表 */
export function parseGitStatus(stdout: string): string[] {
  return stdout
    .split("\n")
    .map((l) => l.trim())
    .filter((l) => l.length > 0);
}

/** 解析 git log --oneline 输出为 commit 列表 */
export function parseGitLog(stdout: string): CommitInfo[] {
  return stdout
    .split("\n")
    .map((l) => l.trim())
    .filter((l) => l.length > 0)
    .map((line) => {
      const spaceIdx = line.indexOf(" ");
      if (spaceIdx === -1) return { hash: line, message: "" };
      return {
        hash: line.slice(0, spaceIdx),
        message: line.slice(spaceIdx + 1),
      };
    });
}

/** 构建完整 GitInfo */
export function buildGitInfo(
  branch: string,
  headCommit: string,
  statusStdout: string,
  logStdout: string,
): GitInfo {
  return {
    branch,
    headCommit,
    dirtyFiles: parseGitStatus(statusStdout),
    recentCommits: parseGitLog(logStdout),
  };
}
