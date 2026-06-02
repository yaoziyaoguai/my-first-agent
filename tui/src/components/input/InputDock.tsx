/** Slice A — Input Dock + CommandChipBar。Visual Target §3.14 */
import React from "react";
import { Box, Text } from "ink";
import { CommandChipBar } from "./CommandChipBar";
import { DIM_TEXT } from "../../theme/visualShellTheme";

interface InputDockProps {
  width: number;
  placeholder: string;
  isFake: boolean;
}

export function InputDock({ width, placeholder, isFake }: InputDockProps) {
  return (
    <Box
      flexDirection="column"
      width={width}
      borderStyle="single"
      borderColor="gray"
    >
      {/* 模式提示 */}
      <Box>
        {isFake && <Text dimColor>[fake/local]</Text>}
        <Text dimColor>  mcp: 3 tools  </Text>
        <Text dimColor>[Enter: send]</Text>
      </Box>

      {/* 输入区域 — 3 行占位 */}
      <Box marginTop={0}>
        <Text color="cyan">{"> "}</Text>
        <Text dimColor>{placeholder}</Text>
      </Box>
      <Box height={1}>
        <Text> </Text>
      </Box>
      <Box height={1}>
        <Text> </Text>
      </Box>

      {/* Command chips */}
      <CommandChipBar />
    </Box>
  );
}
