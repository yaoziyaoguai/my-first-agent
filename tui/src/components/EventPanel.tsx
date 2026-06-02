import React from "react";
import { Box, Text } from "ink";
import type { RuntimeTraceItem, InspectorSummary } from "../data/eventSourceContract";

interface EventPanelProps {
  focused: boolean;
  /** 解析后的 events */
  events: RuntimeTraceItem[];
  /** 解析错误数 */
  errorCount: number;
  /** Inspector 摘要 */
  summary: InspectorSummary | null;
  /** 是否有活跃的 agent */
  hasAgent: boolean;
}

const EVENT_TYPE_COLORS: Record<string, string> = {
  agent_start: "green",
  agent_error: "red",
  turn_start: "blue",
  turn_end: "blue",
  tool_gate: "yellow",
  tool_invoke: "yellow",
  tool_result: "green",
  safety_gate: "red",
  memory_write: "magenta",
  memory_proposal: "magenta",
  checkpoint_create: "cyan",
  checkpoint_restore: "cyan",
  skill_select: "blue",
  skill_action: "blue",
  action_plan_start: "green",
  action_plan_complete: "green",
  node_enter: "white",
  node_exit: "white",
  condition_flag: "yellow",
  mcp_bridge_lifecycle: "cyan",
};

function EventRow({ event }: { event: RuntimeTraceItem }) {
  const typeColor = EVENT_TYPE_COLORS[event.eventType] ?? "white";
  const time = event.timestamp.slice(11, 19); // HH:MM:SS

  return (
    <Box flexDirection="row">
      <Text dimColor>{time}</Text>
      <Text> </Text>
      <Text color={typeColor}>[{event.eventType}]</Text>
      <Text dimColor> {event.runId}</Text>
      {event.redacted && <Text color="yellow"> [redacted:{event.redactedFields.length}]</Text>}
    </Box>
  );
}

/** M7 — EventPanel（只读 projection）。
 *  展示解析后的 runtime events，支持 malformed/partial write 安全展示。 */
export function EventPanel({
  focused,
  events,
  errorCount,
  summary,
  hasAgent,
}: EventPanelProps) {
  if (!hasAgent) {
    return (
      <Box flexDirection="column" borderStyle="single" paddingLeft={1} paddingRight={1}>
        <Box marginBottom={1}>
          <Text bold color={focused ? "green" : undefined}>
            {focused ? "◆" : "─"} Events
          </Text>
        </Box>
        <Text dimColor>Select an agent to view events.</Text>
      </Box>
    );
  }

  return (
    <Box flexDirection="column" borderStyle="single" paddingLeft={1} paddingRight={1}>
      <Box marginBottom={1}>
        <Text bold color={focused ? "green" : undefined}>
          {focused ? "◆" : "─"} Events
        </Text>
        {summary && (
          <Text dimColor>
            {" "}— {summary.totalEvents} events, {summary.sessionCount}S/{summary.runCount}R
          </Text>
        )}
        {errorCount > 0 && (
          <Text color="yellow"> — {errorCount} parse error(s)</Text>
        )}
      </Box>

      {events.length === 0 ? (
        <Text dimColor>No events to display.</Text>
      ) : (
        <Box flexDirection="column">
          {events.slice(0, 20).map((event) => (
            <EventRow key={event.eventId} event={event} />
          ))}
          {events.length > 20 && (
            <Text dimColor>
              ... and {events.length - 20} more events
            </Text>
          )}
        </Box>
      )}

      <Box marginTop={1}>
        <Text dimColor>fake/local event stream — read-only projection</Text>
      </Box>
    </Box>
  );
}
