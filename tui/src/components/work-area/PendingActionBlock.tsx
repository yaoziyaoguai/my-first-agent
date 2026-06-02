/** Slice A — pending action block. Visual Target §3.13 */
import React from "react";
import { Box, Text } from "ink";
import type { PendingActionBlockData } from "../../data/visualShellTypes";
import { DIM_TEXT } from "../../theme/visualShellTheme";

interface PendingActionBlockProps {
  action: PendingActionBlockData;
}

export function PendingActionBlock({ action }: PendingActionBlockProps) {
  if (action.status !== "pending") return null;

  return (
    <Box flexDirection="column" marginTop={1}>
      <Box>
        <Text color="yellow">⚡ [{action.actionType}] {action.target}</Text>
      </Box>
      <Box>
        <Text dimColor>  Enter: approve  Esc: reject</Text>
      </Box>
    </Box>
  );
}
