import React from "react";
import { Box, Text } from "ink";
import type { FocusZone } from "../types";

interface StatusBarProps {
  activeLens: string;
  focusZone: FocusZone;
}

/** 底部状态栏 */
export function StatusBar({ activeLens, focusZone }: StatusBarProps) {
  const zoneLabel: Record<FocusZone, string> = {
    interaction: "Interaction",
    "agent-lens": "Agent Selector",
    context: "Context",
  };

  return (
    <Box
      flexDirection="row"
      justifyContent="space-between"
      paddingLeft={1}
      paddingRight={1}
    >
      <Box gap={2}>
        <Text dimColor>
          Lens: <Text bold>{activeLens || "none"}</Text>
        </Text>
        <Text dimColor>
          Focus: <Text bold>{zoneLabel[focusZone]}</Text>
        </Text>
      </Box>
      <Box gap={2}>
        <Text dimColor>fake/local mode</Text>
        <Text dimColor>Tab: switch zone | q: quit</Text>
      </Box>
    </Box>
  );
}
