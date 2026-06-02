/** Slice A — Workspace list. Visual Target §3.4 */
import React from "react";
import { Box, Text } from "ink";
import type { WorkspaceItem } from "../../data/visualShellTypes";
import {
  SECTION_HEADER,
  DIM_TEXT,
  ACCENT_TEXT,
  statusColor,
  statusDot,
} from "../../theme/visualShellTheme";

interface WorkspacePanelProps {
  items: WorkspaceItem[];
}

export function WorkspacePanel({ items }: WorkspacePanelProps) {
  return (
    <Box flexDirection="column">
      <Text {...SECTION_HEADER}>Workspaces</Text>
      {items.length === 0 ? (
        <Text dimColor>—</Text>
      ) : (
        items.map((w) => (
          <Box key={w.id}>
            <Text color={statusColor(w.status)}>{statusDot(w.status)}</Text>
            <Text> </Text>
            <Text
              color={w.status === "active" ? "cyan" : undefined}
              dimColor={w.status !== "active"}
            >
              {w.label}
            </Text>
          </Box>
        ))
      )}
    </Box>
  );
}
