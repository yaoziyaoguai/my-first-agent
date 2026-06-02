/** Slice A — 快捷键提示。Visual Target §3.8 */
import React from "react";
import { Box, Text } from "ink";
import { SECTION_HEADER, DIM_TEXT } from "../../theme/visualShellTheme";

export function KeysPanel() {
  const keys = [
    "Tab: switch",
    "↑↓: navigate",
    "Enter: select",
    "q: quit",
  ];

  return (
    <Box flexDirection="column">
      <Text {...SECTION_HEADER}>Keys</Text>
      {keys.map((k) => (
        <Box key={k}>
          <Text dimColor>{k}</Text>
        </Box>
      ))}
    </Box>
  );
}
