import React from "react";
import { Box, Text } from "ink";
import type { ProjectStatus } from "../types";

export function OverviewPanel({ status }: { status: ProjectStatus }) {
  return (
    <Box
      flexDirection="column"
      borderStyle="single"
      borderColor="blue"
      paddingX={1}
      width="50%"
    >
      <Text bold color="blue">
        Overview
      </Text>
      <Text dimColor>{"─".repeat(30)}</Text>
      <Text>
        Score: <Text color="green">{status.score}</Text>
      </Text>
      <Text>Credible: {status.credibleCount}</Text>
      <Text>
        推荐下一步: <Text color="cyan">{status.recommendedNext}</Text>
      </Text>
    </Box>
  );
}
