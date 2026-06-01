import React, { useState } from "react";
import { Box, Text, useInput } from "ink";

interface InputBarProps {
  focused: boolean;
  lensLabel: string;
  /** M3: onSubmit callback — sends user input to fakeRuntimeGateway */
  onSubmit?: (content: string) => void;
  /** M3: disabled when no lens selected */
  disabled?: boolean;
}

/** 底部输入区域 — M1 只接受文本，M3 接入 RuntimeGateway */
export function InputBar({
  focused,
  lensLabel,
  onSubmit,
  disabled = false,
}: InputBarProps) {
  const [value, setValue] = useState("");

  useInput(
    (input, key) => {
      if (!focused) return;
      if (key.return) {
        if (disabled) return;
        const trimmed = value.trim();
        if (trimmed.length > 0 && onSubmit) {
          onSubmit(trimmed);
          setValue("");
        }
        return;
      }
      if (key.backspace || key.delete) {
        setValue((prev) => prev.slice(0, -1));
        return;
      }
      // 可打印字符
      if (input.length === 1 && !key.ctrl && !key.meta) {
        setValue((prev) => prev + input);
      }
    },
    { isActive: focused },
  );

  const hint = disabled
    ? "Select an agent first (Tab to Agent Lens)"
    : focused
      ? "Type and press Enter to send"
      : "Tab to focus";

  return (
    <Box flexDirection="column">
      <Box paddingLeft={1} paddingRight={1}>
        <Text dimColor>
          {lensLabel !== "none"
            ? `Context: ${lensLabel}`
            : "No lens selected"}
        </Text>
      </Box>
      <Box paddingLeft={1} paddingRight={1} gap={1}>
        <Text bold color={focused ? "green" : undefined}>
          {focused ? ">" : " "}
        </Text>
        <Text>
          {value || (
            <Text dimColor>{focused ? "_" : hint}</Text>
          )}
          {focused && <Text dimColor>▊</Text>}
        </Text>
      </Box>
    </Box>
  );
}
