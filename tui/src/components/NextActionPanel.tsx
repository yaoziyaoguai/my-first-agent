import React from "react";
import { Box, Text } from "ink";

interface Props {
  nextAction: string;
}

export function NextActionPanel({ nextAction }: Props) {
  return (
    <Box
      flexDirection="column"
      borderStyle="round"
      borderColor="magenta"
      paddingX={1}
    >
      <Text bold color="magenta">
        Next Action
      </Text>
      <Box flexDirection="column" marginTop={0}>
        <Text>{nextAction}</Text>
      </Box>
      <Box marginTop={1}>
        <Text dimColor>Source: PROJECT_STATUS.md 推荐下一步</Text>
      </Box>
    </Box>
  );
}
