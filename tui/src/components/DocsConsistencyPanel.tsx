import React from "react";
import { Box, Text } from "ink";
import { checkDocs, getDocsByStatus } from "../data/docsConsistency";

export function DocsConsistencyPanel() {
  const results = checkDocs();
  const present = getDocsByStatus(results, "present");
  const missing = getDocsByStatus(results, "missing");
  const unknown = getDocsByStatus(results, "unknown");

  return (
    <Box
      flexDirection="column"
      borderStyle="single"
      borderColor="yellow"
      paddingX={1}
      width="100%"
    >
      <Text bold color="yellow">
        Docs Consistency
      </Text>
      <Text dimColor>{"─".repeat(40)}</Text>
      <Box flexDirection="row" gap={2} marginTop={1}>
        <Text>
          Present: <Text color="green">{present.length}</Text>
        </Text>
        <Text>
          Missing: <Text color="red">{missing.length}</Text>
        </Text>
        <Text>
          Unknown: <Text color="gray">{unknown.length}</Text>
        </Text>
        <Text dimColor>| Total: {results.length}</Text>
      </Box>
      <Box flexDirection="column" marginTop={1}>
        {results.map((r) => {
          const color =
            r.status === "present" ? "green" : r.status === "missing" ? "red" : "gray";
          return (
            <Box key={r.name} flexDirection="row" gap={2}>
              <Text color={color}>
                {r.status === "present" ? "✓" : r.status === "missing" ? "✗" : "?"}
              </Text>
              <Text>{r.name}</Text>
              <Text dimColor>{r.path}</Text>
            </Box>
          );
        })}
      </Box>
    </Box>
  );
}
