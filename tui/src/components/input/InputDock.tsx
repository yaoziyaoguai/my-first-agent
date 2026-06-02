/** Slice A — Input Dock + CommandChipBar。Visual Target §3.14。
 *  现在接受 `inputValue` / `focused` 用于交互反馈。 */
import React from "react";
import { Box, Text } from "ink";
import { CommandChipBar } from "./CommandChipBar";
import { DIM_TEXT } from "../../theme/visualShellTheme";

interface InputDockProps {
  width: number;
  inputValue?: string;
  focused?: boolean;
  isFake: boolean;
}

export function InputDock({
  width,
  inputValue = "",
  focused = false,
  isFake,
}: InputDockProps) {
  const placeholder = focused && inputValue.length === 0 ? "_" : "";
  const cursor = focused ? "▊" : "";

  return (
    <Box
      flexDirection="column"
      width={width}
      borderStyle="single"
      borderColor={focused ? "green" : "gray"}
    >
      {/* 模式提示 */}
      <Box>
        {isFake && <Text dimColor>[fake/local]</Text>}
        <Text dimColor>  mcp: 3 tools  </Text>
        <Text dimColor>[Enter: send]</Text>
        {focused && <Text color="green" bold>  ◉</Text>}
      </Box>

      {/* 输入区域 */}
      <Box marginTop={0}>
        <Text color={focused ? "green" : "cyan"}>
          {focused ? "> " : "  "}
        </Text>
        {inputValue.length > 0 ? (
          <Text>{inputValue}{cursor}</Text>
        ) : (
          <Text dimColor>{placeholder}{cursor}</Text>
        )}
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
