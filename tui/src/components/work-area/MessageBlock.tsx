/** Slice A — user/assistant/system message block. Visual Target §3.10 */
import React from "react";
import { Box, Text } from "ink";
import type { MessageBlockData } from "../../data/visualShellTypes";
import { DIM_TEXT } from "../../theme/visualShellTheme";

interface MessageBlockProps {
  message: MessageBlockData;
}

export function MessageBlock({ message }: MessageBlockProps) {
  const prefix =
    message.role === "user" ? "> " : message.role === "system" ? "— " : "";

  const prefixColor =
    message.role === "user" ? "cyan" : message.role === "system" ? "gray" : "gray";

  return (
    <Box flexDirection="column" marginTop={message.role === "assistant" ? 1 : 0}>
      <Box>
        <Text dimColor={message.role !== "user"}>
          {message.role === "user" && (
            <Text color="cyan">{"user > "}</Text>
          )}
          {message.role === "assistant" && (
            <Text dimColor>{"assistant > "}</Text>
          )}
          {message.role === "system" && (
            <Text dimColor>{"— "}</Text>
          )}
          <Text
            dimColor={message.role !== "user"}
            color={message.role === "user" ? undefined : undefined}
          >
            {message.content}
          </Text>
        </Text>
      </Box>
    </Box>
  );
}
