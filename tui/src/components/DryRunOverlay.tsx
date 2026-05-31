/** Phase 4: Dry-Run 结果覆盖层 */
import React from "react";
import { Box, Text } from "ink";
import type { ConfirmationResult } from "../data/executionGate";

interface Props {
  result: ConfirmationResult;
}

export function DryRunOverlay({ result }: Props) {
  return (
    <Box flexDirection="column" borderStyle="single" borderColor="cyan" padding={1} marginBottom={1}>
      <Text bold color="cyan">
        🔍 Dry-Run Result
      </Text>
      <Box marginTop={1}>
        <Text>
          Would execute: <Text bold>{result.wouldExecute ?? "(unknown)"}</Text>
        </Text>
      </Box>
      <Box>
        <Text dimColor>Expected: stdout → TUI panel</Text>
      </Box>
      <Box marginTop={1}>
        <Text>[Execute for real]  [Back]</Text>
      </Box>
    </Box>
  );
}
