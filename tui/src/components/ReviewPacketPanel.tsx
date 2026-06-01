/** Phase 5: Development Workflow Review — provisional dev-only, may be removed */
import React from "react";
import { Box, Text } from "ink";
import type { ReviewPacket } from "../data/reviewPacket";

interface Props {
  packet: ReviewPacket;
}

export function ReviewPacketPanel({ packet }: Props) {
  return (
    <Box flexDirection="column" borderStyle="single" borderColor="green" padding={1} marginBottom={1}>
      <Text bold color="green">
        Development Workflow Review — {packet.currentPhase}
      </Text>
      <Text dimColor>provisional dev-only, may be removed — not a First Agent product feature</Text>
      <Box marginTop={1}>
        <Text>Tests: {packet.testSummary}</Text>
      </Box>
      <Box>
        <Text>
          Gates:{" "}
          <Text color={packet.gatesResult === "all_pass" ? "green" : "red"}>
            {packet.gatesResult}
          </Text>
        </Text>
      </Box>
      {packet.recentCommits.length > 0 && (
        <Box marginTop={1} flexDirection="column">
          <Text bold>Recent Commits:</Text>
          {packet.recentCommits.slice(0, 3).map((c, i) => (
            <Text key={i} dimColor>
              {c}
            </Text>
          ))}
        </Box>
      )}
    </Box>
  );
}
