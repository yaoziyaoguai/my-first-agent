/** Phase 4: exec 结果类型 + parse/format（纯函数，无副作用） */
import type { SafetyLevel } from "../types";

export interface ExecutionResult {
  commandId: string;
  shellCommand: string;
  safetyLevel: SafetyLevel;
  exitCode: number | null;
  stdout: string;
  stderr: string;
  durationMs: number;
  truncated: boolean;
  timedOut: boolean;
}

const MAX_OUTPUT = 50_000;

function truncate(s: string): { text: string; truncated: boolean } {
  if (s.length > MAX_OUTPUT) {
    return { text: s.slice(0, MAX_OUTPUT) + "\n... [truncated]", truncated: true };
  }
  return { text: s, truncated: false };
}

export function parseExecResult(
  commandId: string,
  shellCommand: string,
  safetyLevel: SafetyLevel,
  exitCode: number | null,
  stdout: string,
  stderr: string,
  durationMs: number,
): ExecutionResult {
  const out = truncate(stdout);
  const err = truncate(stderr);

  return {
    commandId,
    shellCommand,
    safetyLevel,
    exitCode,
    stdout: out.text,
    stderr: err.text,
    durationMs,
    truncated: out.truncated || err.truncated,
    timedOut: false,
  };
}

export function createTimeoutResult(
  commandId: string,
  shellCommand: string,
  safetyLevel: SafetyLevel,
): ExecutionResult {
  return {
    commandId,
    shellCommand,
    safetyLevel,
    exitCode: null,
    stdout: "",
    stderr: "Execution timed out",
    durationMs: 0,
    truncated: false,
    timedOut: true,
  };
}
