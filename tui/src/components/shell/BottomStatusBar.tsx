/** Slice A — Bottom status bar. Visual Target §3.22 */
import React from "react";
import { Box, Text } from "ink";
import type { BottomStatusData } from "../../data/visualShellTypes";
import { DIM_TEXT } from "../../theme/visualShellTheme";

interface BottomStatusBarProps {
  data: BottomStatusData;
  width: number;
  evidenceLens: boolean;
}

export function BottomStatusBar({
  data,
  width,
  evidenceLens,
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
