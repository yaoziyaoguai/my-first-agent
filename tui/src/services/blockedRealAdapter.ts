/** D-04 BlockedRealAdapter — 真实 runtime gateway 的安全阻塞壳。
 *  所有调用返回 explicit blocked result，不读 .env，不调 core.chat()。
 *  不静默 fallback 到 fake——调用方必须明确处理 blocked 状态。 */

import type {
  RuntimeGateway,
  RuntimeRequest,
  RuntimeResponse,
  ApprovalRequest,
  ApprovalResult,
} from "./runtimeGateway";

const BLOCKED_MESSAGE =
  "Real runtime not configured. Set MY_FIRST_AGENT_RUNTIME_GATEWAY=real in config to enable. Currently blocked for safety.";

export function createBlockedRealAdapter(): RuntimeGateway {
  let _msgCounter = 0;

  return {
    mode: "blocked-real",

    async send(request: RuntimeRequest): Promise<RuntimeResponse> {
      _msgCounter += 1;
      return {
        interactionId: request.interactionId,
        messages: [
          {
            id: `blocked-msg-${_msgCounter}`,
            role: "system",
            content: `[blocked-real] ${BLOCKED_MESSAGE}`,
            timestamp: Date.now(),
          },
        ],
        pendingActions: [],
        contextSnapshot: {
          lens: request.lens,
          messageCount: 0,
          lastInteractionTime: null,
          pendingCount: 0,
        },
        source: "blocked-real",
      };
    },

    async approve(request: ApprovalRequest): Promise<ApprovalResult> {
      return {
        actionId: request.actionId,
        status: "rejected",
        outcomeMessage: `[blocked-real] ${BLOCKED_MESSAGE}`,
        resolvedAt: Date.now(),
        source: "blocked-real",
      };
    },

    async reject(request: ApprovalRequest): Promise<ApprovalResult> {
      return {
        actionId: request.actionId,
        status: "rejected",
        outcomeMessage: `[blocked-real] ${BLOCKED_MESSAGE}`,
        resolvedAt: Date.now(),
        source: "blocked-real",
      };
    },
  };
}
