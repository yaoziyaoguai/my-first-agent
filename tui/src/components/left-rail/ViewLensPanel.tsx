/** Slice A — 视图模式选择器 (Agent/Runtime/Tools/MCP/Evidence/Debug)。Visual Target §3.5
 *  注意: 这是视图模式 lens，不是 agent/session/run 选择树。后者在 SessionPanel。 */
import React from "react";
import { Box, Text } from "ink";
import type { ViewLensItem } from "../../data/visualShellTypes";
import { SECTION_HEADER, DIM_TEXT } from "../../theme/visualShellTheme";

interface ViewLensPanelProps {
  lenses: ViewLensItem[];
}

export function ViewLensPanel({ lenses }: ViewLensPanelProps) {
  return (
    <Box flexDirection="column">
      <Text {...SECTION_HEADER}>Lenses</Text>
      {lenses.map((l) => (
        <Box key={l.lens}>
          <Text color={l.selected ? "magenta" : undefined} dimColor={!l.selected}>
            {l.selected ? "◉" : " "} {l.lens}
          </Text>
        </Box>
      ))}
    </Box>
  );
}
