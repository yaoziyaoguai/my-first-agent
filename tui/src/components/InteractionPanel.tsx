import React from "react";
import { Box, Text } from "ink";

interface InteractionPanelProps {
  focused: boolean;
  /** 当前选中的 lens 信息 */
  lensLabel: string;
}

/** 中间对话展示区域 — M1 placeholder, M3 接入真实对话 */
export function InteractionPanel({ focused, lensLabel }: InteractionPanelProps) {
  return (
    <Box flexDirection="column" borderStyle="single" paddingLeft={1} paddingRight={1}>
      <Box marginBottom={1}>
        <Text bold color={focused ? "green" : undefined}>
          {focused ? "◆" : "─"} Interaction View
        </Text>
      </Box>
      <Box flexDirection="column" marginTop={1}>
        {lensLabel !== "none" ? (
          <>
            <Text>
              <Text color="blue">[system]</Text> Context: {lensLabel}
            </Text>
            <Box marginTop={1}>
              <Text dimColor>
                M3 will display conversation history here.
                {"\n"}
                Real messages from RuntimeGateway.send() will appear in
                {"\n"}
                this area once the Interaction MVP is implemented.
              </Text>
            </Box>
          </>
        ) : (
          <Text dimColor>
            Select an agent in Agent Lens to begin interaction.
          </Text>
        )}
      </Box>
    </Box>
  );
}
