import React from "react";
import { Box, Text } from "ink";
import { loadEvidenceDetails } from "../data/evidenceDetails";

export function EvidenceDetailPanel() {
  const details = loadEvidenceDetails();

  return (
    <Box
      flexDirection="column"
      borderStyle="single"
      borderColor="green"
      paddingX={1}
      width="100%"
    >
      <Text bold color="green">
        Evidence Details — REAL-EVIDENCE 001-008
      </Text>
      <Text dimColor>{"─".repeat(60)}</Text>
      {details.map((d) => {
        const statusColor =
          d.status === "credible" ? "green" : d.status === "credible-with-caveats" ? "yellow" : "red";
        return (
          <Box key={d.id} flexDirection="column" marginTop={1}>
            <Box flexDirection="row" gap={2}>
              <Text bold>{d.id}</Text>
              <Text>{d.capability}</Text>
              <Text color={statusColor}>[{d.status}]</Text>
            </Box>
            <Box flexDirection="row" gap={2}>
              <Text dimColor>evidence: {d.latestEvidence}</Text>
              <Text dimColor>commit: {d.latestCommit}</Text>
            </Box>
            {d.caveats && d.caveats !== "无" ? (
              <Text color="yellow">  ⚠ {d.caveats}</Text>
            ) : null}
          </Box>
        );
      })}
    </Box>
  );
}
