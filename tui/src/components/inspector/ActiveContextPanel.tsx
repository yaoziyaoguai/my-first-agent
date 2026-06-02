/** Slice A — Active Context panel (section in RightInspector). Visual Target §1.6 */
import React from "react";
import { Box, Text } from "ink";
import { SECTION_HEADER, DIM_TEXT } from "../../theme/visualShellTheme";

interface ActiveContextPanelProps {
  agentId: string;
  runId: string;
}

export function ActiveContextPanel({ agentId, runId }: ActiveContextPanelProps) {
  return (
    <Box flexDirection="column">
      <Text {...SECTION_HEADER}>Active Context</Text>
      <Text dimColor>agent: {agentId}</Text>
      <Text dimColor>run: {runId}</Text>
    </Box>
  );
}
