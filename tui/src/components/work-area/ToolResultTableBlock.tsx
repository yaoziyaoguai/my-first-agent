/** Slice A — ASCII table for tool results. Visual Target §3.12 */
import React from "react";
import { Box, Text } from "ink";
import { DIM_TEXT } from "../../theme/visualShellTheme";

interface ToolResultTableBlockProps {
  headers: string[];
  rows: string[][];
  maxRows?: number;
}

export function ToolResultTableBlock({
  headers,
  rows,
  maxRows = 10,
}: ToolResultTableBlockProps) {
  const colWidths = headers.map((h, i) => {
    const dataMax = rows
      .slice(0, maxRows)
      .reduce((m, r) => Math.max(m, (r[i] || "").length), 0);
    return Math.max(h.length, dataMax) + 2;
  });

  const padded = (val: string, w: number) =>
    val.padEnd(w).substring(0, w);

  const divider = colWidths.map((w) => "─".repeat(w)).join("┼");
  const headerLine = headers
    .map((h, i) => padded(h, colWidths[i]))
    .join("│");
  const displayedRows = rows.slice(0, maxRows);

  return (
    <Box flexDirection="column" marginTop={1}>
      <Box>
        <Text bold>{headerLine}</Text>
      </Box>
      <Box>
        <Text dimColor>{divider}</Text>
      </Box>
      {displayedRows.map((row, ri) => (
        <Box key={ri}>
          <Text dimColor>
            {row.map((cell, ci) => padded(cell, colWidths[ci])).join("│")}
          </Text>
        </Box>
      ))}
      {rows.length > maxRows && (
        <Box>
          <Text dimColor>... ({rows.length - maxRows} more rows)</Text>
        </Box>
      )}
    </Box>
  );
}
