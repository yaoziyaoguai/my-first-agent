/** D-04 RuntimeGateway — B8 TUI 接入 real runtime 的安全边界 contract。
 *  不调用真实 API，不读 .env，不绕过 ToolRuntimeMediator，不创建第二 runtime。 */

import type { SelectedLens } from "../types";

// ── Interaction transcript projection ──────────────────────────────

export type InteractionRole = "user" | "assistant" | "system";

export interface InteractionMessage {
  id: string;
  role: InteractionRole;
  content: string;
  timestamp: number;
  toolCalls?: ToolCallProjection[];
  memoryProposals?: MemoryProposalProjection[];
}

export interface ToolCallProjection {
  toolName: string;
  parameters: Record<string, unknown>;
  result?: string;
  gateStatus: "allowed" | "blocked" | "requires_confirmation";
}

export interface MemoryProposalProjection {
  type: "store" | "update" | "delete";
  key: string;
  value?: string;
  status: "pending" | "approved" | "rejected";
}

// ── Pending Action projection ─────────────────────────────────────

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

export interface PendingActionProjection {
  actionId: string;
  type: PendingActionType;
  title: string;
  description: string;
  riskLevel: PendingActionRiskLevel;
  status: PendingActionStatus;
  createdAt: number;
  selectedLens: SelectedLens;
  requiresConfirmation: boolean;
  source: "fake" | "blocked-real" | "real";
  outcomeMessage?: string;
}

// ── Context snapshot projection ────────────────────────────────────

export interface ContextSnapshotProjection {
  lens: SelectedLens;
  messageCount: number;
  lastInteractionTime: number | null;
  pendingCount: number;
}

// ── Gateway request / response ─────────────────────────────────────

export interface RuntimeRequest {
  userInput: string;
  lens: SelectedLens;
  interactionId: string;
}

export interface RuntimeResponse {
  interactionId: string;
  messages: InteractionMessage[];
  pendingActions: PendingActionProjection[];
  contextSnapshot: ContextSnapshotProjection | null;
  source: "fake" | "blocked-real" | "real";
}

export interface ApprovalRequest {
  actionId: string;
  lens: SelectedLens;
}

export interface ApprovalResult {
  actionId: string;
  status: "approved" | "rejected";
  outcomeMessage: string;
  resolvedAt: number;
  source: "fake" | "blocked-real" | "real";
}

// ── Gateway interface ──────────────────────────────────────────────

export type GatewayMode = "fake" | "blocked-real" | "real";

export interface RuntimeGateway {
  readonly mode: GatewayMode;
  send(request: RuntimeRequest): Promise<RuntimeResponse>;
  approve(request: ApprovalRequest): Promise<ApprovalResult>;
  reject(request: ApprovalRequest): Promise<ApprovalResult>;
}
