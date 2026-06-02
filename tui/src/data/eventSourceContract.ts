/** M7 — Event Source Contract 定义。
 *  定义 runtime event stream 的 schema、namespace、redaction 和 backpressure 策略。
 *  只读 projection，不 tail real process，不写 runtime event。
 *  真实 append-only event source contract 依赖 B7 runtime infrastructure。 */

/** Runtime event type 分类 */
export type RuntimeEventType =
  | "turn_start"
  | "turn_end"
  | "tool_gate"
  | "tool_invoke"
  | "tool_result"
  | "memory_proposal"
  | "memory_write"
  | "checkpoint_create"
  | "checkpoint_restore"
  | "safety_gate"
  | "skill_select"
  | "skill_action"
  | "mcp_bridge_lifecycle"
  | "agent_start"
  | "agent_error"
  | "action_plan_start"
  | "action_plan_complete"
  | "node_enter"
  | "node_exit"
  | "condition_flag";

/** 单个 runtime event */
export interface RuntimeTraceItem {
  /** event 唯一标识 */
  eventId: string;
  /** event 类型 */
  eventType: RuntimeEventType;
  /** ISO 8601 timestamp */
  timestamp: string;
  /** 所属 agent ID（从 payload.agentId 或顶层字段解析） */
  agentId: string | null;
  /** 所属 session ID */
  sessionId: string;
  /** 所属 run ID */
  runId: string;
  /** 所属 instance ID（可选） */
  instanceId: string | null;
  /** event payload（结构取决于 eventType） */
  payload: Record<string, unknown>;
  /** 是否已脱敏 */
  redacted: boolean;
  /** 脱敏字段列表 */
  redactedFields: string[];
}

/** Event stream filter */
export interface TraceFilter {
  /** 按 event type 过滤（空 = 全部） */
  eventTypes: RuntimeEventType[];
  /** 按 session ID 过滤（空 = 全部） */
  sessionIds: string[];
  /** 按 run ID 过滤（空 = 全部） */
  runIds: string[];
  /** 按 instance ID 过滤（空 = 全部） */
  instanceIds: string[];
  /** 最大返回条数 */
  limit: number;
}

/** Inspector 摘要 */
export interface InspectorSummary {
  totalEvents: number;
  filteredEvents: number;
  eventTypeCounts: Map<string, number>;
  /** 时间范围 */
  timeRange: { earliest: string | null; latest: string | null };
  /** 涉及的 session/run/instance 数量 */
  sessionCount: number;
  runCount: number;
  instanceCount: number;
}

/** EventSourceContract — 定义 event stream 的读取契约。
 *  不 tail real process，不创建写入路径。 */
export interface EventSourceContract {
  /** event schema version */
  schemaVersion: "1.0";
  /** event 来源（fake/local 或 real） */
  source: "fake/local" | "real";
  /** 背压策略 */
  backpressure: {
    maxEventsPerRead: number;
    truncationThreshold: number;
  };
  /** 脱敏策略 */
  redaction: {
    enabled: boolean;
    /** 需要脱敏的 payload key 模式 */
    patterns: string[];
    /** 脱敏后的替代文本 */
    replacement: string;
  };
  /** 是否支持增量读取（tail） */
  supportsTail: false;
}

/** 默认 EventSourceContract（fake/local — B7 就绪前不启用 real source） */
export const DEFAULT_EVENT_SOURCE_CONTRACT: EventSourceContract = {
  schemaVersion: "1.0",
  source: "fake/local",
  backpressure: {
    maxEventsPerRead: 1000,
    truncationThreshold: 10000,
  },
  redaction: {
    enabled: true,
    patterns: [
      "api_key",
      "apiKey",
      "token",
      "secret",
      "password",
      "authorization",
      "credential",
    ],
    replacement: "[redacted]",
  },
  supportsTail: false,
};

/** 脱敏字段值（简单顶层匹配，不递归） */
export function redactValue(key: string, value: unknown, contract: EventSourceContract): unknown {
  if (!contract.redaction.enabled) return value;
  if (containsSensitiveKey(key, contract)) {
    return contract.redaction.replacement;
  }
  return value;
}

/** 递归脱敏 payload */
export function redactPayload(
  payload: Record<string, unknown>,
  contract: EventSourceContract,
): { redacted: Record<string, unknown>; redactedFields: string[] } {
  const redactedFields: string[] = [];
  const redacted = redactObject(payload, contract, redactedFields, "");
  return { redacted, redactedFields };
}

/** 规范化 key（去下划线、去横线、小写）用于 pattern 匹配 */
function normalizeKey(key: string): string {
  return key.toLowerCase().replace(/[_-]/g, "");
}

/** 检查 key 是否匹配 redaction pattern */
export function containsSensitiveKey(key: string, contract: EventSourceContract): boolean {
  const normalized = normalizeKey(key);
  return contract.redaction.patterns.some((p) => {
    const normalizedPattern = normalizeKey(p);
    return normalized.includes(normalizedPattern);
  });
}

/** 递归脱敏对象 */
function redactObject(
  obj: Record<string, unknown>,
  contract: EventSourceContract,
  redactedFields: string[],
  keyPrefix: string,
): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(obj)) {
    const fullKey = keyPrefix ? `${keyPrefix}.${key}` : key;
    if (containsSensitiveKey(key, contract)) {
      redactedFields.push(fullKey);
      result[key] = contract.redaction.replacement;
    } else if (Array.isArray(value)) {
      result[key] = value.map((item, idx) => {
        if (item && typeof item === "object" && !Array.isArray(item)) {
          return redactObject(
            item as Record<string, unknown>,
            contract,
            redactedFields,
            `${fullKey}[${idx}]`,
          );
        }
        return item;
      });
    } else if (value && typeof value === "object") {
      result[key] = redactObject(
        value as Record<string, unknown>,
        contract,
        redactedFields,
        fullKey,
      );
    } else {
      result[key] = value;
    }
  }
  return result;
}
