import React from "react";
import { Box, Text } from "ink";
import { checkDocs, getDocsByStatus, getDocsByContentStatus } from "../data/docsConsistency";

export function DocsConsistencyPanel() {
  const results = checkDocs();
  const present = getDocsByStatus(results, "present");
  const missing = getDocsByStatus(results, "missing");
  const unknown = getDocsByStatus(results, "unknown");
  const stale = getDocsByContentStatus(results, "stale");

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
          Stale: <Text color={stale.length > 0 ? "yellow" : "green"}>{stale.length}</Text>
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
          // 内容 stale 优先于文件 present
          const displayStatus =
            r.status === "present" && r.contentStatus === "stale"
              ? "stale"
              : r.status;

          const color =
            displayStatus === "present"
              ? "green"
              : displayStatus === "stale"
                ? "yellow"
                : displayStatus === "missing"
                  ? "red"
                  : "gray";

          const icon =
            displayStatus === "present"
              ? "✓"
              : displayStatus === "stale"
                ? "⚠"
                : displayStatus === "missing"
                  ? "✗"
                  : "?";

          return (
            <Box key={r.name} flexDirection="column">
              <Box flexDirection="row" gap={2}>
                <Text color={color}>{icon}</Text>
                <Text>{r.name}</Text>
                <Text dimColor>{r.path}</Text>
                <Text dimColor>
                  {displayStatus === "stale" ? ` (stale: ${r.staleFindings.map((f) => f.label).join(", ")})` : ""}
                </Text>
              </Box>
            </Box>
          );
        })}
      </Box>
    </Box>
  );
}
