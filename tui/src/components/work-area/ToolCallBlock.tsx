/** Slice A — [TOOL] call block. Visual Target §3.11 */
import React from "react";
import { Box, Text } from "ink";
import type { ToolCallBlockData } from "../../data/visualShellTypes";
import { DIM_TEXT, statusColor } from "../../theme/visualShellTheme";

interface ToolCallBlockProps {
  toolCall: ToolCallBlockData;
}

export function ToolCallBlock({ toolCall }: ToolCallBlockProps) {
  return (
    <Box flexDirection="column" marginTop={1}>
      <Box>
        <Text color="yellow">[TOOL]</Text>
        <Text> </Text>
        <Text>{toolCall.toolName}</Text>
        <Text dimColor> — {toolCall.args}</Text>
      </Box>
      {toolCall.result && (
        <Box marginLeft={2}>
          <Text color="green">→ </Text>
          <Text dimColor>{toolCall.result}</Text>
        </Box>
      )}
    </Box>
  );
}
