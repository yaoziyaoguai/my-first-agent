import React from "react";
import { Box, Text } from "ink";
import {
  VIEWS,
  formatNavigationLabel,
  getViewIndex,
  getViewCount,
  type ViewId,
} from "../data/navigation";

export function NavigationBar({ currentView }: { currentView: ViewId }) {
  const total = getViewCount();
  const currentIdx = getViewIndex(currentView);

  return (
    <Box
      flexDirection="column"
      borderStyle="single"
      borderColor="cyan"
      paddingX={1}
    >
      <Text bold color="cyan">
        Navigation
      </Text>
      <Text dimColor>{"─".repeat(40)}</Text>
      <Box flexDirection="row" gap={1}>
        <Text dimColor>{"← → or 1-7 to switch view |"}</Text>
        <Text>
          Current:{" "}
          <Text bold color="green">
            {formatNavigationLabel(currentView)}
          </Text>
        </Text>
      </Box>
      <Box flexDirection="row" gap={1} marginTop={1}>
        {VIEWS.map((v, i) => {
          const isCurrent = i === currentIdx;
          return (
            <Text key={v.id} color={isCurrent ? "green" : undefined} dimColor={!isCurrent}>
              {isCurrent ? `[${v.shortcut}:${v.label}]` : `${v.shortcut}:${v.label}`}
            </Text>
          );
        })}
      </Box>
    </Box>
  );
}
