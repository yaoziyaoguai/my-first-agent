/** Slice A — Command chips 展示。Visual Target §3.15 */
import React from "react";
import { Box, Text } from "ink";
import { DIM_TEXT } from "../../theme/visualShellTheme";

const COMMANDS = ["/ask", "/plan", "/run", "/tools", "/help"];

export function CommandChipBar() {
  return (
    <Box marginTop={0}>
      {COMMANDS.map((cmd) => (
        <Box key={cmd} marginRight={2}>
          <Text dimColor>{cmd}</Text>
        </Box>
      ))}
    </Box>
  );
}
