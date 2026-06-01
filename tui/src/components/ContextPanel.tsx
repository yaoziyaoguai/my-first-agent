import React from "react";
import { Box, Text } from "ink";

interface ContextPanelProps {
  focused: boolean;
  lensLabel: string;
}

/** 右侧 Context/Inspector 占位面板 — M1 mock/static placeholder。
 *  不叫 Audit Lens。不渲染 PROJECT_STATUS / PROGRESS_LEDGER / dogfood / debt 等 Operation 内容。
 *  只展示当前 selected lens 的通用辅助信息 placeholder。
 *  具体展示模型后续重新设计。 */
export function ContextPanel({ focused, lensLabel }: ContextPanelProps) {
  const hasSelection = lensLabel !== "none";

  return (
    <Box flexDirection="column" borderStyle="single" paddingLeft={1} paddingRight={1}>
      <Box marginBottom={1}>
        <Text bold color={focused ? "green" : undefined}>
          {focused ? "◆" : "─"} Context
        </Text>
      </Box>

      {hasSelection ? (
        <>
          <Box flexDirection="column" marginBottom={1}>
            <Text bold>Selection</Text>
            <Text dimColor>{lensLabel}</Text>
          </Box>
          <Box flexDirection="column" marginBottom={1}>
            <Text bold>Tool Calls</Text>
            <Text dimColor>Placeholder — pending generic model</Text>
          </Box>
          <Box flexDirection="column" marginBottom={1}>
            <Text bold>Memory</Text>
            <Text dimColor>Placeholder — pending generic model</Text>
          </Box>
          <Box flexDirection="column" marginBottom={1}>
            <Text bold>Checkpoint</Text>
            <Text dimColor>Placeholder — pending generic model</Text>
          </Box>
          <Box flexDirection="column" marginBottom={1}>
            <Text bold>Safety</Text>
            <Text dimColor>local fake mode</Text>
          </Box>
        </>
      ) : (
        <Text dimColor>
          Select an agent to view context.
        </Text>
      )}

      <Box marginTop={1}>
        <Text dimColor>
          Tab: switch zone | q: quit
        </Text>
      </Box>
    </Box>
  );
}
