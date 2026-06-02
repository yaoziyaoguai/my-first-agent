/** Slice A — Memory/Checkpoint summary。Visual Target §3.21 */
import React from "react";
import { Box, Text } from "ink";
import { SECTION_HEADER, DIM_TEXT } from "../../theme/visualShellTheme";

interface MemoryCheckpointPanelProps {
  entryCount: number;
  lastCheckpointId: string;
}

export function MemoryCheckpointPanel({
  entryCount,
  lastCheckpointId,
}: MemoryCheckpointPanelProps) {
  if (entryCount === 0 && lastCheckpointId === "—") {
    return (
      <Box flexDirection="column">
        <Text {...SECTION_HEADER}>Memory / CKPT</Text>
        <Text dimColor>no Memory/Checkpoint data</Text>
      </Box>
    );
  }

  return (
    <Box flexDirection="column">
      <Text {...SECTION_HEADER}>Memory / CKPT</Text>
      <Text dimColor>entries: {entryCount}</Text>
      <Text dimColor>ckpt: {lastCheckpointId}</Text>
    </Box>
  );
}
