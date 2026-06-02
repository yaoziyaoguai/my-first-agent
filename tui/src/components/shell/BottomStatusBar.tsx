/** Slice A — Bottom status bar. Visual Target §3.22 */
import React from "react";
import { Box, Text } from "ink";
import type { BottomStatusData } from "../../data/visualShellTypes";
import { DIM_TEXT } from "../../theme/visualShellTheme";

type FocusZone = "agent-lens" | "interaction" | "context";
const ZONE_LABEL: Record<FocusZone, string> = {
  interaction: "Input",
  "agent-lens": "Lens",
  context: "Context",
};

interface BottomStatusBarProps {
  data: BottomStatusData;
  width: number;
  evidenceLens: boolean;
  focusZone?: FocusZone;
  messageCount?: number;
}

export function BottomStatusBar({
  data,
  width,
  evidenceLens,
  focusZone,
  messageCount,
}: BottomStatusBarProps) {
  const parts = [
    data.version,
    `runtime: ${data.runtime}`,
    `mode: ${data.mode}`,
    `lens: ${data.lens}`,
    `tools: ${data.toolCount} ready`,
    `mcp: ${data.mcpStatus}`,
    data.provider,
    evidenceLens ? "[EVIDENCE]" : null,
    focusZone ? `focus: ${ZONE_LABEL[focusZone]}` : null,
    messageCount !== undefined && messageCount > 0 ? `msgs: ${messageCount}` : null,
    "q: quit  Tab: switch",
  ].filter(Boolean);

  const content = parts.join(" | ");
  const padded = content.padEnd(width - 2).substring(0, width - 2);

  return (
    <Box width={width} height={1}>
      <Text dimColor>{padded}</Text>
    </Box>
  );
}
