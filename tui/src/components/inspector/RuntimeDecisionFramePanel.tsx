/** Slice A — RuntimeDecisionFrame 摘要。Visual Target §3.17 */
import React from "react";
import { Box, Text } from "ink";
import type { RuntimeDecisionSummary } from "../../data/visualShellTypes";
import { SECTION_HEADER, DIM_TEXT, statusColor } from "../../theme/visualShellTheme";

interface RuntimeDecisionFramePanelProps {
  data: RuntimeDecisionSummary;
}

export function RuntimeDecisionFramePanel({
  data,
}: RuntimeDecisionFramePanelProps) {
  return (
    <Box flexDirection="column">
      <Text {...SECTION_HEADER}>Runtime Frame</Text>
      <Text dimColor>mode: {data.mode}</Text>
      <Text color={statusColor(data.status)}>status: {data.status}</Text>
      <Text dimColor>last: {data.lastDecision}</Text>
    </Box>
  );
}
