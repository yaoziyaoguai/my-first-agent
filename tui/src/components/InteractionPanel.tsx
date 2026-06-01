import React from "react";
import { Box, Text } from "ink";
import type { RuntimeMessage } from "../data/fakeRuntimeGateway";

interface InteractionPanelProps {
  focused: boolean;
  /** 当前选中的 lens 信息 */
  lensLabel: string;
  /** M3: conversation message history */
  messages: RuntimeMessage[];
}

const ROLE_COLORS: Record<string, string> = {
  user: "green",
  assistant: "blue",
  system: "yellow",
};

const ROLE_LABELS: Record<string, string> = {
  user: "You",
  assistant: "First Agent",
  system: "system",
};

/** 中间对话展示区域 — M1 placeholder, M3 消息列表 */
export function InteractionPanel({
  focused,
  lensLabel,
  messages,
}: InteractionPanelProps) {
  return (
    <Box flexDirection="column" borderStyle="single" paddingLeft={1} paddingRight={1}>
      <Box marginBottom={1}>
        <Text bold color={focused ? "green" : undefined}>
          {focused ? "◆" : "─"} Interaction View
        </Text>
        {lensLabel !== "none" && (
          <Text dimColor> — {lensLabel}</Text>
        )}
      </Box>

      <Box flexDirection="column" marginTop={1}>
        {lensLabel === "none" ? (
          <Text dimColor>
            Select an agent in Agent Lens to begin interaction.
          </Text>
        ) : messages.length === 0 ? (
          <Box flexDirection="column">
            <Text dimColor>
              No messages yet. Type below to start.
            </Text>
            <Box marginTop={1}>
              <Text dimColor>
                fake/local mode — M3 placeholder
              </Text>
            </Box>
          </Box>
        ) : (
          <Box flexDirection="column">
            {messages.map((msg) => (
              <Box key={msg.id} flexDirection="column" marginBottom={1}>
                <Text>
                  <Text bold color={ROLE_COLORS[msg.role] || "white"}>
                    [{ROLE_LABELS[msg.role] || msg.role}]
                  </Text>
                  <Text dimColor>
                    {" "}{new Date(msg.timestamp).toLocaleTimeString()}
                  </Text>
                </Text>
                <Box paddingLeft={2}>
                  <Text>{msg.content}</Text>
                </Box>
              </Box>
            ))}
            <Box marginTop={1}>
              <Text dimColor>
                ─── fake/local mode — M3 MVP ───
              </Text>
            </Box>
          </Box>
        )}
      </Box>
    </Box>
  );
}
