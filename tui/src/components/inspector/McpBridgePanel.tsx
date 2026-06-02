/** Slice A — MCP bridge status panel。Visual Target §3.19 */
import React from "react";
import { Box, Text } from "ink";
import type { McpStatusData } from "../../data/visualShellTypes";
import { SECTION_HEADER, DIM_TEXT, statusColor } from "../../theme/visualShellTheme";

interface McpBridgePanelProps {
  data: McpStatusData;
}

export function McpBridgePanel({ data }: McpBridgePanelProps) {
  if (data.status === "disabled") {
    return (
      <Box flexDirection="column">
        <Text {...SECTION_HEADER}>MCP Bridge</Text>
        <Text dimColor>no MCP data</Text>
      </Box>
    );
  }

  return (
    <Box flexDirection="column">
      <Text {...SECTION_HEADER}>MCP Bridge</Text>
      <Text dimColor>
        discover: {data.discoverCount}
      </Text>
      <Text color={statusColor(data.status)}>
        invoke: {data.invokeReady ? "ready" : "blocked"}
      </Text>
    </Box>
  );
}
