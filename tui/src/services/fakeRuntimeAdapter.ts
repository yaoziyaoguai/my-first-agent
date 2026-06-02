/** D-04 FakeRuntimeAdapter — 包装现有 fake/local gateway 行为。
 *  不调用真实 API，不读 .env，不绕过 ToolRuntimeMediator。
 *  作为 RuntimeGateway 接口的默认实现。 */

import type {
  RuntimeGateway,
  RuntimeRequest,
  RuntimeResponse,
  ApprovalRequest,
  ApprovalResult,
  InteractionMessage,
  PendingActionProjection,
  ContextSnapshotProjection,
} from "./runtimeGateway";
import { fakeRuntimeSend, makeUserMessage } from "../data/fakeRuntimeGateway";
import {
  generateFakePendingActions,
  createFakeGateway,
  type PendingAction,
} from "../data/pendingAction";

let _msgCounter = 0;
function nextMsgId(): string {
  _msgCounter += 1;
  return `imsg-${_msgCounter}`;
}

function toInteractionMessage(p: PendingAction["source"]): InteractionMessage {
  // 将 pending action 的 outcome 转为 InteractionMessage
  return {
    id: nextMsgId(),
    role: "system",
    content: "",
    timestamp: Date.now(),
  };
}

/** 将旧 RuntimeMessage 转为新 InteractionMessage */
function wrapFakeMessage(msg: {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  timestamp: number;
}): InteractionMessage {
  return { ...msg, role: msg.role as InteractionMessage["role"] };
}

/** 将旧 PendingAction 转为新 PendingActionProjection */
function wrapPendingAction(a: PendingAction): PendingActionProjection {
  return {
    actionId: a.actionId,
    type: a.type as PendingActionProjection["type"],
    title: a.title,
    description: a.description,
    riskLevel: a.riskLevel,
    status: a.status,
    createdAt: a.createdAt,
    selectedLens: a.selectedLens,
    requiresConfirmation: a.requiresConfirmation,
    source: "fake",
    outcomeMessage: a.outcomeMessage,
  };
}

export function createFakeRuntimeAdapter(): RuntimeGateway {
  const controlledGateway = createFakeGateway();

  return {
    mode: "fake",

    async send(request: RuntimeRequest): Promise<RuntimeResponse> {
      const userMsg = makeUserMessage(request.userInput);
      const assistantMsg = fakeRuntimeSend(
        request.userInput,
        request.lens.agentId,
      );
      const oldPending = generateFakePendingActions(
        request.lens,
        request.userInput,
      );

      const messages: InteractionMessage[] = [
        wrapFakeMessage(userMsg),
        wrapFakeMessage(assistantMsg),
      ];

      const pendingActions: PendingActionProjection[] =
        oldPending.map(wrapPendingAction);

      const contextSnapshot: ContextSnapshotProjection = {
        lens: request.lens,
        messageCount: messages.length,
        lastInteractionTime:
          messages.length > 0
            ? messages[messages.length - 1].timestamp
            : null,
        pendingCount: pendingActions.filter((a) => a.status === "pending")
          .length,
      };

      return {
        interactionId: request.interactionId,
        messages,
        pendingActions,
        contextSnapshot,
        source: "fake",
      };
    },

    async approve(request: ApprovalRequest): Promise<ApprovalResult> {
      const fakeAction: PendingAction = {
        actionId: request.actionId,
        type: "tool_confirmation",
        title: "Fake action",
        description: "Wrapped by FakeRuntimeAdapter",
        riskLevel: "low",
        status: "pending",
        createdAt: Date.now(),
        selectedLens: request.lens,
        requiresConfirmation: true,
        source: "fake/local",
      };
      const result = controlledGateway.approve(fakeAction);
      return {
        actionId: result.actionId,
        status: result.status === "approved" ? "approved" : "rejected",
        outcomeMessage: result.outcomeMessage,
        resolvedAt: result.resolvedAt,
        source: "fake",
      };
    },

    async reject(request: ApprovalRequest): Promise<ApprovalResult> {
      const fakeAction: PendingAction = {
        actionId: request.actionId,
        type: "tool_confirmation",
        title: "Fake action",
        description: "Wrapped by FakeRuntimeAdapter",
        riskLevel: "low",
        status: "pending",
        createdAt: Date.now(),
        selectedLens: request.lens,
        requiresConfirmation: true,
        source: "fake/local",
      };
      const result = controlledGateway.reject(fakeAction);
      return {
        actionId: result.actionId,
        status: result.status === "rejected" ? "rejected" : "approved",
        outcomeMessage: result.outcomeMessage,
        resolvedAt: result.resolvedAt,
        source: "fake",
      };
    },
  };
}
