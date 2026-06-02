/** Slice A — Tool summary panel。Visual Target §3.18 */
import React from "react";
import { Box, Text } from "ink";
import type { ToolSummaryItem } from "../../data/visualShellTypes";
import { SECTION_HEADER, DIM_TEXT, statusColor } from "../../theme/visualShellTheme";

interface ToolSummaryPanelProps {
  tools: ToolSummaryItem[];
}

export function ToolSummaryPanel({ tools }: ToolSummaryPanelProps) {
  return (
    <Box flexDirection="column">
      <Text {...SECTION_HEADER}>Tool Summary</Text>
      {tools.length === 0 ? (
        <Text dimColor>—</Text>
      ) : (
        tools.map((t) => (
          <Box key={t.toolName}>
            <Text color={statusColor(t.status)}>
              {t.status === "pass"
                ? "✓"
                : t.status === "pending"
                  ? "⚡"
                  : t.status === "fail"
                    ? "✗"
                    : "—"}
            </Text>
            <Text> </Text>
            <Text dimColor>{t.toolName}</Text>
          </Box>
        ))
      )}
    </Box>
  );
}
