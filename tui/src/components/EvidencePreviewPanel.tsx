import React from "react";
import { Box, Text } from "ink";
import type { DogfoodResult } from "../types";

export function EvidencePreviewPanel({
  results,
}: {
  results: DogfoodResult[];
}) {
  return (
    <Box
      flexDirection="column"
      borderStyle="single"
      borderColor="cyan"
      paddingX={1}
      width="50%"
    >
      <Text bold color="cyan">
        Evidence Preview
      </Text>
      <Text dimColor>{"─".repeat(30)}</Text>
      {results.length === 0 && <Text dimColor>No dogfood results</Text>}
      {results.map((r) => (
        <Box key={r.fileName} flexDirection="column">
          <Text>
            <Text dimColor>{r.fileName}</Text>
          </Text>
          <Text>
            <Text color="green">{r.pass}P</Text>
            {" / "}
            <Text color="red">{r.fail}F</Text>
            {" / "}
            <Text color="yellow">{r.concern}C</Text>
            {r.summary ? ` — ${r.summary.slice(0, 50)}` : ""}
          </Text>
        </Box>
      ))}
    </Box>
  );
}
