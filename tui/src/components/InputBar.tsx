import React, { useState } from "react";
import { Box, Text, useInput } from "ink";

interface InputBarProps {
  focused: boolean;
  lensLabel: string;
}

/** 底部输入区域 — M1 只接受文本，M3 接入 RuntimeGateway.send() */
export function InputBar({ focused, lensLabel }: InputBarProps) {
  const [value, setValue] = useState("");

  useInput(
    (input, key) => {
      if (!focused) return;
      if (key.return) {
        // M3: send via RuntimeGateway
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

  return (
    <Box flexDirection="column">
      <Box paddingLeft={1} paddingRight={1}>
        <Text dimColor>
          {lensLabel ? `Context: ${lensLabel}` : "No context selected"}
        </Text>
      </Box>
      <Box paddingLeft={1} paddingRight={1} gap={1}>
        <Text bold color={focused ? "green" : undefined}>
          {focused ? ">" : " "}
        </Text>
        <Text>
          {value || (
            <Text dimColor>
              {focused
                ? "_"
                : "Type your message... (Tab to focus)"}
            </Text>
          )}
          {focused && <Text dimColor>▊</Text>}
        </Text>
      </Box>
    </Box>
  );
}
