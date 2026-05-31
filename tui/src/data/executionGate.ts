/** Phase 4: 确认/dry-run/超时门 */
import type { CommandDefinition } from "../types";

export const EXECUTION_TIMEOUT_MS = 60_000;
export const CONFIRMATION_TIMEOUT_MS = 30_000;

export type ConfirmStatus =
  | "pending"
  | "confirmed"
  | "awaiting-double-confirm"
  | "cancelled"
  | "dry-run";

export interface ConfirmationRequest {
  commandId: string;
  shellCommand: string;
  safetyLevel: string;
  requiresDoubleConfirmation: boolean;
}

export interface ConfirmationResult {
  status: ConfirmStatus;
  commandId: string;
  needsDoubleConfirmText: boolean;
  wouldExecute?: string;
  actuallyExecuted?: boolean;
}

/** autorun 始终需要 double confirmation */
export function needsDoubleConfirmation(commandId: string): boolean {
  return commandId === "autorun";
}

export function createConfirmationRequest(
  cmd: CommandDefinition,
): ConfirmationRequest {
  return {
    commandId: cmd.id,
    shellCommand: cmd.shellCommand ?? "",
    safetyLevel: cmd.safetyLevel,
    requiresDoubleConfirmation: needsDoubleConfirmation(cmd.id),
  };
}

export function confirmExecution(
  req: ConfirmationRequest | ConfirmationResult,
  doubleConfirmText?: string,
): ConfirmationResult {
  if ("needsDoubleConfirmText" in req && req.needsDoubleConfirmText) {
    if (doubleConfirmText === "yes") {
      return {
        status: "confirmed",
        commandId: req.commandId,
        needsDoubleConfirmText: false,
        actuallyExecuted: true,
      };
    }
    return {
      status: "awaiting-double-confirm",
      commandId: req.commandId,
      needsDoubleConfirmText: true,
    };
  }

  if ("requiresDoubleConfirmation" in req && req.requiresDoubleConfirmation) {
    return {
      status: "awaiting-double-confirm",
      commandId: req.commandId,
      needsDoubleConfirmText: true,
    };
  }

  return {
    status: "confirmed",
    commandId: req.commandId,
    needsDoubleConfirmText: false,
    actuallyExecuted: true,
  };
}

export function cancelExecution(commandId: string): ConfirmationResult {
  return {
    status: "cancelled",
    commandId,
    needsDoubleConfirmText: false,
  };
}

export function dryRunExecution(cmd: CommandDefinition): ConfirmationResult {
  return {
    status: "dry-run",
    commandId: cmd.id,
    needsDoubleConfirmText: false,
    wouldExecute: cmd.shellCommand,
    actuallyExecuted: false,
  };
}

export function buildExecutionCommand(
  cmd: CommandDefinition,
): { command: string } {
  if (!cmd.shellCommand) {
    throw new Error(`HARD_STOP: 命令 "${cmd.id}" 缺少 shellCommand`);
  }
  return { command: cmd.shellCommand };
}
