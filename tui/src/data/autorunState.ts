/** Phase 5: AutoRun state from PROJECT_STATUS.md + git log */
export interface AutoRunState {
  currentPhase: string;
  status: "idle" | "running" | "completed" | "hard_stop";
  lastLoop: string;
  lastCommit: string;
  testsPass: number;
  gatesStatus: "all_pass" | "partial" | "failed";
  nextRecommended: string;
  hardStopReason?: string;
}

export function parseAutoRunState(projectStatusText: string): AutoRunState {
  const phaseMatch = projectStatusText.match(/B8\s+(Phase\s+\d+)/i);
  const testsMatch = projectStatusText.match(/(\d+)\/[\d]+\s+tests?\s+PASS/);
  const nextMatch = projectStatusText.match(
    /B8 Phase \d+\s*[^)]*\)\s*为推荐下一步/,
  );
  const gatesMatch = projectStatusText.match(/all_pass|partial|failed/);

  return {
    currentPhase: phaseMatch?.[1] ?? "",
    status: deriveAutoRunStatus(projectStatusText),
    lastLoop: "",
    lastCommit: "",
    testsPass: testsMatch ? parseInt(testsMatch[1], 10) : 0,
    gatesStatus: (gatesMatch?.[0] as AutoRunState["gatesStatus"]) ?? "all_pass",
    nextRecommended: nextMatch?.[0] ?? "",
  };
}

export function deriveAutoRunStatus(text: string): AutoRunState["status"] {
  if (text.includes("HARD_STOP")) return "hard_stop";
  if (text.match(/COMPLETED.*all\s+gates?\s+pass/)) return "completed";
  return "idle";
}
