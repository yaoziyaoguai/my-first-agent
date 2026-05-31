import React from "react";
import { Box, Text } from "ink";
import {
  getReadinessItems,
  getReadinessSummary,
  STATUS_LABELS,
  STATUS_COLORS,
} from "../data/defaultEntryReadiness";

export function DefaultEntryReadinessPanel() {
  const items = getReadinessItems();
  const summary = getReadinessSummary();
  const pct = Math.round((summary.done / summary.total) * 100);

  return (
    <Box flexDirection="column" borderStyle="single" borderColor="magenta" padding={1}>
      <Text bold color="magenta">
        Default Entry Readiness
      </Text>
      <Text dimColor>
        {summary.done}/{summary.total} done ({pct}%) | {summary.blocked} blocked | {summary.pending} pending
      </Text>
      <Text dimColor>{"─".repeat(50)}</Text>

      <Box flexDirection="column" marginTop={1}>
        {items.map((item) => {
          const color = STATUS_COLORS[item.status] ?? "white";
          const label = STATUS_LABELS[item.status] ?? item.status;
          return (
            <Box key={item.id} flexDirection="column" marginBottom={1}>
              <Text>
                <Text color={color}>{label}</Text>
                {"  "}
                <Text bold>{item.label}</Text>
              </Text>
              <Text dimColor>  {item.description}</Text>
            </Box>
          );
        })}
      </Box>

      <Box marginTop={1} flexDirection="column">
        <Text dimColor>{"─".repeat(50)}</Text>
        <Text dimColor>
          CLI fallback retained. TUI not activated as default entry.
        </Text>
      </Box>
    </Box>
  );
}
