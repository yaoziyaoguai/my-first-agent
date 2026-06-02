/** M5 Pending Action / Controlled Interaction — fake/local 最小闭环。
 *  不调用真实 tool，不写 memory/checkpoint/event log，不绕过 ToolRuntimeMediator。
 *  ControlledOperationGateway 为未来 real RuntimeGateway 留接口。 */

import type { SelectedLens } from "../types";

export type PendingActionType =
  | "tool_confirmation"
  | "memory_proposal"
  | "checkpoint_save"
  | "safety_gate";

export type PendingActionRiskLevel = "low" | "medium" | "high" | "critical";

export type PendingActionStatus =
  | "pending"
  | "approved"
  | "rejected"
  | "expired"
  | "completed";

export interface PendingAction {
  actionId: string;
  type: PendingActionType;
  title: string;
  description: string;
  riskLevel: PendingActionRiskLevel;
  status: PendingActionStatus;
  createdAt: number;
  selectedLens: SelectedLens;
  requiresConfirmation: boolean;
  source: "fake/local";
  /** outcome message — set after approve/reject */
  outcomeMessage?: string;
}

export interface ApprovalResult {
  actionId: string;
  status: "approved" | "rejected";
  outcomeMessage: string;
  resolvedAt: number;
}

let _actionCounter = 0;
function nextActionId(): string {
  _actionCounter += 1;
  return `pending-${_actionCounter}`;
}

/** 从 fake/local interaction 生成 pending actions */
export function generateFakePendingActions(
  lens: SelectedLens,
  input: string,
): PendingAction[] {
  const lower = input.toLowerCase().trim();
  const actions: PendingAction[] = [];
  const now = Date.now();

  if (lower.includes("tool") || lower.includes("execute") || lower.includes("run")) {
    actions.push({
      actionId: nextActionId(),
      type: "tool_confirmation",
      title: "Execute Tool",
      description: `Tool execution requested: "${input}"`,
      riskLevel: "medium",
      status: "pending",
      createdAt: now,
      selectedLens: { ...lens },
      requiresConfirmation: true,
      source: "fake/local",
    });
  }

  if (lower.includes("memory") || lower.includes("remember") || lower.includes("store")) {
    actions.push({
      actionId: nextActionId(),
      type: "memory_proposal",
      title: "Memory Operation",
      description: `Memory proposal: "${input}"`,
      riskLevel: "low",
      status: "pending",
      createdAt: now + 1,
      selectedLens: { ...lens },
      requiresConfirmation: true,
      source: "fake/local",
    });
  }

  if (lower.includes("checkpoint") || lower.includes("save")) {
    actions.push({
      actionId: nextActionId(),
      type: "checkpoint_save",
      title: "Save Checkpoint",
      description: `Checkpoint save: "${input}"`,
      riskLevel: "low",
      status: "pending",
      createdAt: now + 2,
      selectedLens: { ...lens },
      requiresConfirmation: false,
      source: "fake/local",
    });
  }

  if (lower.includes("delete") || lower.includes("destroy") || lower.includes("rm")) {
    actions.push({
      actionId: nextActionId(),
      type: "safety_gate",
      title: "Safety Gate Check",
      description: `Destructive operation requested: "${input}"`,
      riskLevel: "critical",
      status: "pending",
      createdAt: now + 3,
      selectedLens: { ...lens },
      requiresConfirmation: true,
      source: "fake/local",
    });
  }

  return actions;
}

/** ControlledOperationGateway — approve/reject 只走 fake/local gateway。
 *  不调用真实 tool，不写 memory/checkpoint/event log，不绕过 ToolRuntimeMediator。
 *  为未来 real RuntimeGateway 留接口。 */
export interface ControlledOperationGateway {
  approve(action: PendingAction): ApprovalResult;
  reject(action: PendingAction): ApprovalResult;
}

export function createFakeGateway(): ControlledOperationGateway {
  return {
    approve(action: PendingAction): ApprovalResult {
      return {
        actionId: action.actionId,
        status: "approved",
        outcomeMessage: `[fake/local] APPROVED: "${action.title}" — ${action.description}. No real tool executed.`,
        resolvedAt: Date.now(),
      };
    },
    reject(action: PendingAction): ApprovalResult {
      return {
        actionId: action.actionId,
        status: "rejected",
        outcomeMessage: `[fake/local] REJECTED: "${action.title}" — ${action.description}. Operation cancelled.`,
        resolvedAt: Date.now(),
      };
    },
  };
}
