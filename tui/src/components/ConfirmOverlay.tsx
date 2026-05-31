/** Phase 4: 执行确认覆盖层 */
import React from "react";
import { Box, Text } from "ink";
import type { ConfirmationRequest, ConfirmationResult } from "../data/executionGate";

interface Props {
  request: ConfirmationRequest;
  result: ConfirmationResult;
}

export function ConfirmOverlay({ request, result }: Props) {
  const isDouble = request.requiresDoubleConfirmation;

  if (result.status === "awaiting-double-confirm") {
    return (
      <Box flexDirection="column" borderStyle="double" borderColor="yellow" padding={1} marginBottom={1}>
        <Text bold color="yellow">
          ⚠⚠ DOUBLE CONFIRMATION REQUIRED
        </Text>
        <Box marginBottom={1}>
          <Text dimColor>
            Command: {request.shellCommand}
          </Text>
        </Box>
        <Text>Type "yes" to confirm: _</Text>
      </Box>
    );
  }

  if (result.status === "confirmed") {
    return (
      <Box flexDirection="column" borderStyle="single" borderColor="green" padding={1} marginBottom={1}>
        <Text bold color="green">
          ✓ Execution confirmed — running...
        </Text>
        <Text dimColor>{request.shellCommand}</Text>
      </Box>
    );
  }

  if (result.status === "cancelled") {
    return (
      <Box flexDirection="column" borderStyle="single" borderColor="red" padding={1} marginBottom={1}>
        <Text bold color="red">
          ✗ Execution cancelled
        </Text>
        <Text dimColor>{request.shellCommand}</Text>
      </Box>
    );
  }

  return (
    <Box flexDirection="column" borderStyle="single" borderColor="yellow" padding={1} marginBottom={1}>
      <Text bold>⚡ Execute Command?</Text>
      <Box marginBottom={1}>
        <Text dimColor>
          Command: {request.shellCommand}
        </Text>
      </Box>
      <Box marginBottom={1}>
        <Text>
          Safety: {request.safetyLevel}
          {isDouble ? " (double confirmation required)" : ""}
        </Text>
      </Box>
      <Text>
        [y] Execute   [n] Cancel   [d] Dry-run
      </Text>
    </Box>
  );
}
