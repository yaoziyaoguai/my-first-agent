/** Phase 6A: Dogfood Detail Panel — 选中 evidence 的详情 + gate history */
import React from "react";
import { Box, Text } from "ink";
import type { EvidenceFileEntry } from "../data/evidenceBrowser";
import type { GateResult } from "../data/gateHistory";

interface Props {
  entry: EvidenceFileEntry | null;
  gates: GateResult[];
}

export function DogfoodDetailPanel({ entry, gates }: Props) {
  return (
    <Box flexDirection="column" borderStyle="single" borderColor="green" padding={1}>
      <Text bold color="green">
        Detail & Gates
      </Text>

      {/* Evidence Detail */}
      {entry ? (
        <Box flexDirection="column" marginBottom={1}>
          <Text bold>Evidence: {entry.evidenceId || entry.fileName}</Text>
          <Box marginTop={1} flexDirection="column">
            <Text>
              Pass: <Text color="green">{entry.pass}</Text>{" "}
              Concern: <Text color="yellow">{entry.concern}</Text>{" "}
              Fail: <Text color="red">{entry.fail}</Text>
              {"  "}Cases: {entry.caseCount}
            </Text>
            {entry.date && <Text dimColor>Date: {entry.date}</Text>}
            {entry.status && (
              <Text>
                Status: <Text color={entry.status === "credible" ? "green" : "yellow"}>{entry.status}</Text>
              </Text>
            )}
          </Box>
        </Box>
      ) : (
        <Box marginBottom={1}>
          <Text dimColor>Select an evidence file to view details</Text>
        </Box>
      )}

      {/* Gate History */}
      <Box flexDirection="column" marginTop={1}>
        <Text bold>Gate History</Text>
        {gates.map((g, i) => (
          <Box key={i}>
            <Text>
              {"  "}{g.name}:{" "}
              <Text color={g.status === "unknown" ? "dim" : "green"}>
                {g.status}
              </Text>
            </Text>
          </Box>
        ))}
      </Box>
    </Box>
  );
}
