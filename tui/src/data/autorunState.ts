/** Phase 5: Development workflow state parser — provisional dev-only, may be removed.
 *  AutoRun is a Coding Agent engineering workflow, NOT a First Agent runtime product feature. */
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
  const loopMatch = projectStatusText.match(/Loop\s+([\d.]+)/i);
  const hardStopMatch = projectStatusText.match(
    /HARD_STOP[:\s]+([^\n]+)/i,
  );

  return {
    currentPhase: phaseMatch?.[1] ?? "",
    status: deriveAutoRunStatus(projectStatusText),
    lastLoop: loopMatch?.[1] ?? "",
    lastCommit: "",
    testsPass: testsMatch ? parseInt(testsMatch[1], 10) : 0,
    gatesStatus: (gatesMatch?.[0] as AutoRunState["gatesStatus"]) ?? "all_pass",
    nextRecommended: nextMatch?.[0] ?? "",
    hardStopReason: hardStopMatch?.[1]?.trim(),
  };
}

export function deriveAutoRunStatus(text: string): AutoRunState["status"] {
  if (text.includes("HARD_STOP")) return "hard_stop";
  if (text.match(/COMPLETED.*all\s+gates?\s+pass/)) return "completed";
  return "idle";
}
