/** Phase 5: HARD_STOP overlay — provisional dev-only */
import React from "react";
import { Box, Text } from "ink";

interface Props {
  reason: string;
  detail?: string;
  loop?: string;
}

export function HardStopOverlay({ reason, detail, loop }: Props) {
  return (
    <Box flexDirection="column" borderStyle="double" borderColor="red" padding={1} marginBottom={1}>
      <Text bold color="red">
        ⛔ HARD_STOP — Development Workflow Paused
      </Text>
      <Box marginTop={1}>
        <Text>
          Reason: <Text bold>{reason}</Text>
        </Text>
      </Box>
      {detail && (
        <Box>
          <Text dimColor>Detail: {detail}</Text>
        </Box>
      )}
      {loop && (
        <Box>
          <Text dimColor>Loop: {loop}</Text>
        </Box>
      )}
      <Box marginTop={1} flexDirection="column">
        <Text bold>User action needed:</Text>
        <Text dimColor>1. Review the stop reason above</Text>
        <Text dimColor>2. Fix the issue in your terminal</Text>
        <Text dimColor>3. Resume AutoRun: /auto-run --continue</Text>
      </Box>
    </Box>
  );
}
