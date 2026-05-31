/** Phase 5: AutoRun 状态面板 */
import React from "react";
import { Box, Text } from "ink";
import type { AutoRunState } from "../data/autorunState";

interface Props {
  state: AutoRunState;
}

const STATUS_LABELS: Record<string, string> = {
  idle: "IDLE",
  running: "RUNNING",
  completed: "COMPLETED",
  hard_stop: "HARD_STOP",
};

const STATUS_COLORS: Record<string, string> = {
  idle: "dim",
  running: "cyan",
  completed: "green",
  hard_stop: "red",
};

export function AutoRunPanel({ state }: Props) {
  const statusColor = STATUS_COLORS[state.status] ?? "white";
  const statusLabel = STATUS_LABELS[state.status] ?? state.status;

  return (
    <Box flexDirection="column" borderStyle="single" borderColor="cyan" padding={1} marginBottom={1}>
      <Text bold>AutoRun State</Text>
      <Box>
        <Text>
          Status: <Text color={statusColor}>{statusLabel}</Text>
        </Text>
      </Box>
      {state.currentPhase && (
        <Box>
          <Text>Phase: {state.currentPhase}</Text>
        </Box>
      )}
      {state.lastLoop && (
        <Box>
          <Text>Loop: {state.lastLoop}</Text>
        </Box>
      )}
      {state.testsPass > 0 && (
        <Box>
          <Text>Tests: {state.testsPass}/ PASS</Text>
        </Box>
      )}
      <Box>
        <Text dimColor>Gates: {state.gatesStatus}</Text>
      </Box>
      {state.nextRecommended && (
        <Box>
          <Text dimColor>Next: {state.nextRecommended}</Text>
        </Box>
      )}
      {state.hardStopReason && (
        <Box marginTop={1}>
          <Text color="red">Reason: {state.hardStopReason}</Text>
        </Box>
      )}
    </Box>
  );
}
