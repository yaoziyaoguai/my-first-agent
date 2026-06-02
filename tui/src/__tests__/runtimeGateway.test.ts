/** D-04 RuntimeGateway tests — interface contract + adapter behavior.
 *  Fake gateway must work. Blocked real gateway must return explicit block.
 *  No .env read, no real API call, no second runtime. */

import { describe, it, expect } from "vitest";
import { createFakeRuntimeAdapter } from "../services/fakeRuntimeAdapter";
import { createBlockedRealAdapter } from "../services/blockedRealAdapter";
import type { RuntimeGateway, RuntimeRequest, ApprovalRequest } from "../services/runtimeGateway";

const TEST_LENS = {
  agentId: "test-agent-1",
  sessionId: "s1",
  runId: "r1",
  instanceId: null,
};

function makeRequest(overrides?: Partial<RuntimeRequest>): RuntimeRequest {
  return {
    userInput: "hello",
    lens: TEST_LENS,
    interactionId: "test-ix-1",
    ...overrides,
  };
}

// ═══════════════════════════════════════════════════════════════════
// FakeRuntimeAdapter
// ═══════════════════════════════════════════════════════════════════

describe("FakeRuntimeAdapter", () => {
  const gateway: RuntimeGateway = createFakeRuntimeAdapter();

  it("has mode 'fake'", () => {
    expect(gateway.mode).toBe("fake");
  });

  it("send returns messages with source 'fake'", async () => {
    const response = await gateway.send(makeRequest());
    expect(response.source).toBe("fake");
    expect(response.messages.length).toBeGreaterThanOrEqual(2);
  });

  it("send includes user message first", async () => {
    const response = await gateway.send(makeRequest({ userInput: "hello" }));
    expect(response.messages[0].role).toBe("user");
  });

  it("send includes assistant response second", async () => {
    const response = await gateway.send(makeRequest({ userInput: "hello" }));
    expect(response.messages[1].role).toBe("assistant");
  });

  it("send returns pendingActions for tool-related input", async () => {
    const response = await gateway.send(
      makeRequest({ userInput: "run tool execute test" }),
    );
    expect(response.pendingActions.length).toBeGreaterThan(0);
    expect(response.pendingActions[0].source).toBe("fake");
  });

  it("send returns pendingActions for memory-related input", async () => {
    const response = await gateway.send(
      makeRequest({ userInput: "remember this for me" }),
    );
    const memActions = response.pendingActions.filter(
      (a) => a.type === "memory_proposal",
    );
    expect(memActions.length).toBeGreaterThan(0);
  });

  it("send returns contextSnapshot", async () => {
    const response = await gateway.send(makeRequest());
    expect(response.contextSnapshot).not.toBeNull();
    expect(response.contextSnapshot!.lens.agentId).toBe(TEST_LENS.agentId);
  });

  it("approve returns approved result with source 'fake'", async () => {
    const result = await gateway.approve({
      actionId: "test-action-1",
      lens: TEST_LENS,
    });
    expect(result.source).toBe("fake");
    expect(result.status).toBe("approved");
    expect(result.outcomeMessage).toContain("[fake/local]");
  });

  it("reject returns rejected result with source 'fake'", async () => {
    const result = await gateway.reject({
      actionId: "test-action-1",
      lens: TEST_LENS,
    });
    expect(result.source).toBe("fake");
    expect(result.status).toBe("rejected");
    expect(result.outcomeMessage).toContain("[fake/local]");
  });
});

// ═══════════════════════════════════════════════════════════════════
// BlockedRealAdapter
// ═══════════════════════════════════════════════════════════════════

describe("BlockedRealAdapter", () => {
  const gateway: RuntimeGateway = createBlockedRealAdapter();

  it("has mode 'blocked-real'", () => {
    expect(gateway.mode).toBe("blocked-real");
  });

  it("send returns source 'blocked-real'", async () => {
    const response = await gateway.send(makeRequest());
    expect(response.source).toBe("blocked-real");
  });

  it("send returns explicit blocked message, not silent fallback", async () => {
    const response = await gateway.send(makeRequest());
    expect(response.messages.length).toBe(1);
    expect(response.messages[0].role).toBe("system");
    expect(response.messages[0].content).toContain("[blocked-real]");
    expect(response.messages[0].content).toContain(
      "Real runtime not configured",
    );
  });

  it("send returns empty pendingActions", async () => {
    const response = await gateway.send(makeRequest());
    expect(response.pendingActions).toEqual([]);
  });

  it("approve returns rejected with blocked message", async () => {
    const result = await gateway.approve({
      actionId: "test-action-1",
      lens: TEST_LENS,
    });
    expect(result.source).toBe("blocked-real");
    expect(result.status).toBe("rejected");
    expect(result.outcomeMessage).toContain("[blocked-real]");
  });

  it("reject returns rejected with blocked message", async () => {
    const result = await gateway.reject({
      actionId: "test-action-1",
      lens: TEST_LENS,
    });
    expect(result.source).toBe("blocked-real");
    expect(result.status).toBe("rejected");
    expect(result.outcomeMessage).toContain("[blocked-real]");
  });

  it("blocked message does NOT contain 'fake' (no silent fallback)", async () => {
    const response = await gateway.send(makeRequest());
    expect(response.source).not.toBe("fake");
    expect(response.messages[0].content).not.toContain("[fake/local]");
  });
});

// ═══════════════════════════════════════════════════════════════════
// Interface contract
// ═══════════════════════════════════════════════════════════════════

describe("RuntimeGateway contract", () => {
  it("both adapters implement send/approve/reject", async () => {
    const adapters: RuntimeGateway[] = [
      createFakeRuntimeAdapter(),
      createBlockedRealAdapter(),
    ];
    for (const gw of adapters) {
      const resp = await gw.send(makeRequest());
      expect(resp).toHaveProperty("interactionId");
      expect(resp).toHaveProperty("messages");
      expect(resp).toHaveProperty("pendingActions");
      expect(resp).toHaveProperty("source");

      const appr = await gw.approve({ actionId: "a", lens: TEST_LENS });
      expect(appr).toHaveProperty("status");
      expect(appr).toHaveProperty("outcomeMessage");

      const rej = await gw.reject({ actionId: "a", lens: TEST_LENS });
      expect(rej).toHaveProperty("status");
      expect(rej).toHaveProperty("outcomeMessage");
    }
  });
});
