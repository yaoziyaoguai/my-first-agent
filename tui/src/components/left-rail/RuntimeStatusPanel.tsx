/** Slice A — runtime/provider/tool/MCP 状态摘要。Visual Target §3.7 */
import React from "react";
import { Box, Text } from "ink";
import type { RuntimeStatusData } from "../../data/visualShellTypes";
import { SECTION_HEADER, DIM_TEXT, statusColor } from "../../theme/visualShellTheme";

interface RuntimeStatusPanelProps {
  data: RuntimeStatusData;
}

export function RuntimeStatusPanel({ data }: RuntimeStatusPanelProps) {
  const statuses = [
    { label: `runtime: ${data.runtime.label}`, color: statusColor(data.runtime.status) },
    {
      label: `provider: ${data.provider.label}`,
      color: statusColor(data.provider.status),
    },
    { label: `mcp: ${data.mcp.label}`, color: statusColor(data.mcp.status) },
    {
      label: `tools: ${data.tools.ready}/${data.tools.count}`,
      color: undefined as string | undefined,
    },
  ];

  return (
    <Box flexDirection="column">
      <Text {...SECTION_HEADER}>Status</Text>
      {statuses.map((s) => (
        <Box key={s.label}>
          <Text color={s.color} dimColor={!s.color}>
            {s.label}
          </Text>
        </Box>
      ))}
    </Box>
  );
}
