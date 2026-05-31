/** Phase 4: exec 结果类型 */
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

export function parseExecResult(
  commandId: string,
  shellCommand: string,
  safetyLevel: SafetyLevel,
  exitCode: number | null,
  stdout: string,
  stderr: string,
  durationMs: number,
): ExecutionResult {
  const MAX_OUTPUT = 50_000;
  const stdoutTruncated = stdout.length > MAX_OUTPUT;
  const stderrTruncated = stderr.length > MAX_OUTPUT;

  return {
    commandId,
    shellCommand,
    safetyLevel,
    exitCode,
    stdout: stdoutTruncated ? stdout.slice(0, MAX_OUTPUT) + "\n... [truncated]" : stdout,
    stderr: stderrTruncated ? stderr.slice(0, MAX_OUTPUT) + "\n... [truncated]" : stderr,
    durationMs,
    truncated: stdoutTruncated || stderrTruncated,
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
