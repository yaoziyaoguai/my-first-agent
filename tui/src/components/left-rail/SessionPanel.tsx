/** Slice A — agent/session/run 树形导航。Visual Target §3.6
 *  注意: 这是 agent/session tree，不是视图模式选择。视图模式在 ViewLensPanel。 */
import React from "react";
import { Box, Text } from "ink";
import type { SessionItem } from "../../data/visualShellTypes";
import {
  SECTION_HEADER,
  DIM_TEXT,
  statusColor,
  statusDot,
} from "../../theme/visualShellTheme";

interface SessionPanelProps {
  data: SessionItem;
  focused?: boolean;
  selectedIdx?: number;
}

export function SessionPanel({ data, focused = false, selectedIdx = 0 }: SessionPanelProps) {
  if (!data.agentId) {
    return (
      <Box flexDirection="column">
        <Text {...SECTION_HEADER}>Sessions</Text>
        <Text dimColor>no agents</Text>
      </Box>
    );
  }

  return (
    <Box flexDirection="column">
      <Text {...SECTION_HEADER}>Sessions</Text>
      {/* Agent */}
      <Box>
        <Text color={statusColor(data.agentStatus)}>
          {statusDot(data.agentStatus)}
        </Text>
        <Text> </Text>
        <Text color={data.agentStatus === "active" ? "cyan" : undefined}>
          {data.agentId}
        </Text>
        <Text dimColor> ({data.agentStatus})</Text>
      </Box>
      {/* Sessions + runs */}
      {data.sessions.map((s) => (
        <Box key={s.sessionId} flexDirection="column" marginLeft={2}>
          <Box>
            <Text color={statusColor(s.sessionStatus)}>
              {statusDot(s.sessionStatus)}
            </Text>
            <Text> </Text>
            <Text dimColor={s.sessionStatus === "historical"}>
              {s.sessionId}
            </Text>
          </Box>
          {s.runs.map((r) => (
            <Box key={r.runId} marginLeft={4}>
              <Text color={statusColor(r.runStatus)}>
                {statusDot(r.runStatus)}
              </Text>
              <Text> </Text>
              <Text
                dimColor={r.runStatus !== "running"}
                color={r.runStatus === "running" ? "cyan" : undefined}
              >
                {r.runId}
              </Text>
            </Box>
          ))}
        </Box>
      ))}
    </Box>
  );
}
