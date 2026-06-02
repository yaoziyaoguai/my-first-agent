/** M7 — EventStreamReader。
 *  解析 events.jsonl（fake/local fixture）。
 *  支持 malformed line、空文件、partial write 安全处理。
 *  只读 projection，不 tail real process，不写 runtime event。 */

import {
  DEFAULT_EVENT_SOURCE_CONTRACT,
  redactPayload,
  type EventSourceContract,
  type RuntimeTraceItem,
  type TraceFilter,
  type InspectorSummary,
} from "./eventSourceContract";

/** 单行 JSONL 解析结果 */
export type ParseResult =
  | { ok: true; event: RuntimeTraceItem }
  | { ok: false; lineNumber: number; raw: string; error: string };

/** EventStreamReader — 解析 events.jsonl，处理 malformed/missing/partial write */
export interface EventStreamReader {
  /** 解析完整 JSONL 内容 */
  parse(content: string): { events: RuntimeTraceItem[]; errors: ParseResult[] };
  /** 应用过滤并返回结果 */
  filter(
    events: RuntimeTraceItem[],
    filter: Partial<TraceFilter>,
  ): RuntimeTraceItem[];
  /** 生成摘要 */
  summarize(events: RuntimeTraceItem[]): InspectorSummary;
  /** 来源合约 */
  contract: EventSourceContract;
}

/** 创建 EventStreamReader */
export function createEventStreamReader(
  contract: EventSourceContract = DEFAULT_EVENT_SOURCE_CONTRACT,
): EventStreamReader {
  return {
    contract,

    parse(content: string): { events: RuntimeTraceItem[]; errors: ParseResult[] } {
      const events: RuntimeTraceItem[] = [];
      const errors: ParseResult[] = [];

      if (!content || content.trim() === "") {
        return { events, errors };
      }

      const lines = content.split("\n");
      for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        // 跳过空行
        if (line.trim() === "") continue;

        try {
          const raw = JSON.parse(line);

          // 基本 schema 验证
          if (!raw.eventId || !raw.eventType || !raw.timestamp) {
            errors.push({
              ok: false,
              lineNumber: i + 1,
              raw: line,
              error: "Missing required fields: eventId, eventType, timestamp",
            });
            continue;
          }

          const { redacted, redactedFields } = redactPayload(
            raw.payload ?? {},
            contract,
          );

          events.push({
            eventId: raw.eventId as string,
            eventType: raw.eventType,
            timestamp: raw.timestamp as string,
            sessionId: (raw.sessionId as string) ?? "unknown",
            runId: (raw.runId as string) ?? "unknown",
            instanceId: (raw.instanceId as string | null) ?? null,
            payload: redacted,
            redacted: redactedFields.length > 0,
            redactedFields,
          });
        } catch (e) {
          errors.push({
            ok: false,
            lineNumber: i + 1,
            raw: line,
            error: e instanceof Error ? e.message : "Unknown parse error",
          });
        }
      }

      return { events, errors };
    },

    filter(
      events: RuntimeTraceItem[],
      filter: Partial<TraceFilter>,
    ): RuntimeTraceItem[] {
      let result = events;

      if (filter.eventTypes && filter.eventTypes.length > 0) {
        result = result.filter((e) => filter.eventTypes!.includes(e.eventType));
      }
      if (filter.sessionIds && filter.sessionIds.length > 0) {
        result = result.filter((e) => filter.sessionIds!.includes(e.sessionId));
      }
      if (filter.runIds && filter.runIds.length > 0) {
        result = result.filter((e) => filter.runIds!.includes(e.runId));
      }
      if (filter.instanceIds && filter.instanceIds.length > 0) {
        result = result.filter((e) =>
          e.instanceId ? filter.instanceIds!.includes(e.instanceId) : false,
        );
      }
      if (filter.limit && filter.limit > 0) {
        result = result.slice(0, filter.limit);
      }

      return result;
    },

    summarize(events: RuntimeTraceItem[]): InspectorSummary {
      const typeCounts = new Map<string, number>();
      const sessions = new Set<string>();
      const runs = new Set<string>();
      const instances = new Set<string>();
      let earliest: string | null = null;
      let latest: string | null = null;

      for (const e of events) {
        typeCounts.set(e.eventType, (typeCounts.get(e.eventType) ?? 0) + 1);
        sessions.add(e.sessionId);
        runs.add(e.runId);
        if (e.instanceId) instances.add(e.instanceId);

        if (!earliest || e.timestamp < earliest) earliest = e.timestamp;
        if (!latest || e.timestamp > latest) latest = e.timestamp;
      }

      return {
        totalEvents: events.length,
        filteredEvents: events.length,
        eventTypeCounts: typeCounts,
        timeRange: { earliest, latest },
        sessionCount: sessions.size,
        runCount: runs.size,
        instanceCount: instances.size,
      };
    },
  };
}

// ============================================================
// Fake/local fixture events.jsonl
// ============================================================

/** Fake/local fixture events — 模拟 runtime event stream。
 *  不来自真实 Python runtime，不含真实 secret。 */
export const FAKE_EVENTS_JSONL = [
  `{"eventId":"evt-001","eventType":"agent_start","timestamp":"2026-06-01T10:00:00Z","sessionId":"session-001a","runId":"run-001a1","payload":{"agentId":"agent-001","version":"1.0"}}`,
  `{"eventId":"evt-002","eventType":"turn_start","timestamp":"2026-06-01T10:00:01Z","sessionId":"session-001a","runId":"run-001a1","payload":{"turnNumber":1,"userInput":"hello"}}`,
  `{"eventId":"evt-003","eventType":"skill_select","timestamp":"2026-06-01T10:00:02Z","sessionId":"session-001a","runId":"run-001a1","payload":{"skillName":"greeting","confidence":0.95}}`,
  `{"eventId":"evt-004","eventType":"tool_gate","timestamp":"2026-06-01T10:00:03Z","sessionId":"session-001a","runId":"run-001a1","payload":{"toolName":"read_file","allowed":true,"risk":"low"}}`,
  `{"eventId":"evt-005","eventType":"tool_invoke","timestamp":"2026-06-01T10:00:04Z","sessionId":"session-001a","runId":"run-001a1","payload":{"toolName":"read_file","args":{"path":"/tmp/test.txt"}}}`,
  `{"eventId":"evt-006","eventType":"tool_result","timestamp":"2026-06-01T10:00:05Z","sessionId":"session-001a","runId":"run-001a1","payload":{"toolName":"read_file","success":true,"result":"file content here"}}`,
  `{"eventId":"evt-007","eventType":"turn_end","timestamp":"2026-06-01T10:00:06Z","sessionId":"session-001a","runId":"run-001a1","payload":{"turnNumber":1,"assistantResponse":"Hello!"}}`,
  `{"eventId":"evt-008","eventType":"checkpoint_create","timestamp":"2026-06-01T10:01:00Z","sessionId":"session-001a","runId":"run-001a1","payload":{"checkpointId":"ckpt-001","size":1024}}`,
  `{"eventId":"evt-009","eventType":"memory_write","timestamp":"2026-06-01T10:02:00Z","sessionId":"session-001a","runId":"run-001a1","payload":{"memoryKey":"user_name","value":"Alice"}}`,
  `{"eventId":"evt-010","eventType":"agent_error","timestamp":"2026-06-01T10:03:00Z","sessionId":"session-001a","runId":"run-001a1","payload":{"error":"Connection timeout","retryable":true}}`,
  `{"eventId":"evt-011","eventType":"safety_gate","timestamp":"2026-06-01T10:04:00Z","sessionId":"session-001a","runId":"run-001a2","payload":{"trigger":"delete_file","allowed":false,"risk":"critical"}}`,
  `{"eventId":"evt-012","eventType":"action_plan_start","timestamp":"2026-06-01T10:05:00Z","sessionId":"session-001a","runId":"run-001a2","payload":{"planId":"plan-001","nodeCount":3}}`,
  `{"eventId":"evt-013","eventType":"node_enter","timestamp":"2026-06-01T10:05:01Z","sessionId":"session-001a","runId":"run-001a2","payload":{"nodeId":"node-1","nodeType":"action","label":"Read config"}}`,
  `{"eventId":"evt-014","eventType":"node_exit","timestamp":"2026-06-01T10:05:02Z","sessionId":"session-001a","runId":"run-001a2","payload":{"nodeId":"node-1","success":true}}`,
  `{"eventId":"evt-015","eventType":"action_plan_complete","timestamp":"2026-06-01T10:05:03Z","sessionId":"session-001a","runId":"run-001a2","payload":{"planId":"plan-001","allNodesPassed":true}}`,
  // 含敏感字段的 event（测试脱敏）
  `{"eventId":"evt-016","eventType":"tool_invoke","timestamp":"2026-06-01T10:06:00Z","sessionId":"session-001a","runId":"run-001a2","payload":{"toolName":"api_call","args":{"api_key":"sk-very-secret-key","token":"bearer-token-123"}}}`,
].join("\n");

/** Malformed 测试数据 */
export const MALFORMED_JSONL = [
  `{"eventId":"evt-001","eventType":"agent_start","timestamp":"2026-06-01T10:00:00Z","sessionId":"session-001a","runId":"run-001a1","payload":{}}`,
  `this is not json at all`,
  `{"eventId":"evt-003","eventType":"turn_start"`,
  ``,
  `{"eventId":"evt-004","eventType":"tool_gate","timestamp":"2026-06-01T10:00:03Z","sessionId":"session-001a","runId":"run-001a1","payload":{"allowed":true}}`,
].join("\n");
