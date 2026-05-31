import React from "react";
import { Box, Text } from "ink";
import type { RealEvidenceRow } from "../types";

const statusColor = (s: string) => {
  if (s === "credible") return "green";
  if (s === "credible-with-caveats") return "yellow";
  return "red";
};

export function EvidenceStatusPanel({ rows }: { rows: RealEvidenceRow[] }) {
  return (
    <Box
      flexDirection="column"
      borderStyle="single"
      borderColor="magenta"
      paddingX={1}
      width="50%"
    >
      <Text bold color="magenta">
        Evidence Status
      </Text>
      <Text dimColor>{"─".repeat(30)}</Text>
      {rows.length === 0 && <Text dimColor>No evidence data</Text>}
      {rows.map((row) => (
        <Text key={row.id}>
          <Text color={statusColor(row.status)}>
            {row.id} {row.capability}
          </Text>
          {" — "}
          <Text color={statusColor(row.status)}>{row.status}</Text>
        </Text>
      ))}
    </Box>
  );
}
