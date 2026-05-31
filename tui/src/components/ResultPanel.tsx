/** Phase 4: 命令执行结果面板 */
import React from "react";
import { Box, Text } from "ink";
import type { ExecutionResult } from "../data/commandResult";

interface Props {
  result: ExecutionResult;
}

export function ResultPanel({ result }: Props) {
  const exitLabel =
    result.exitCode === 0
      ? "green"
      : result.exitCode === null
        ? "yellow"
        : "red";

  return (
    <Box flexDirection="column" borderStyle="single" borderColor="cyan" padding={1} marginBottom={1}>
      <Text bold>
        Result — {result.commandId}
      </Text>
      <Box>
        <Text>
          Exit code: <Text color={exitLabel}>{result.exitCode ?? "null"}</Text>
          {"  "}Duration: {result.durationMs}ms
        </Text>
      </Box>
      {result.timedOut && (
        <Text color="yellow">⚠ Command timed out</Text>
      )}
      <Box marginTop={1} flexDirection="column">
        <Text bold>stdout:</Text>
        <Text dimColor>
          {result.stdout || "(none)"}
        </Text>
      </Box>
      {result.stderr && result.stderr !== "Execution timed out" && (
        <Box marginTop={1} flexDirection="column">
          <Text bold color="yellow">stderr:</Text>
          <Text dimColor>{result.stderr}</Text>
        </Box>
      )}
      {result.stderr === "Execution timed out" && (
        <Box marginTop={1}>
          <Text color="yellow">{result.stderr}</Text>
        </Box>
      )}
      {result.truncated && (
        <Box marginTop={1}>
          <Text dimColor>... [output truncated]</Text>
        </Box>
      )}
    </Box>
  );
}
