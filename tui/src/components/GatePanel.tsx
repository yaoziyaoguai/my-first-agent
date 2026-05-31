import React from "react";
import { Box, Text } from "ink";
import type { GitInfo } from "../types";

export function GatePanel({ git }: { git: GitInfo }) {
  const dirtyCount = git.dirtyFiles.length;

  return (
    <Box
      flexDirection="column"
      borderStyle="single"
      borderColor="yellow"
      paddingX={1}
      width="50%"
    >
      <Text bold color="yellow">
        Gate
      </Text>
      <Text dimColor>{"─".repeat(30)}</Text>
      <Text>
        branch: <Text color="cyan">{git.branch}</Text>
      </Text>
      <Text>
        HEAD: <Text dimColor>{git.headCommit.slice(0, 7)}</Text>
      </Text>
      <Text>
        dirty:{" "}
        <Text color={dirtyCount > 0 ? "yellow" : "green"}>
          {dirtyCount} file{dirtyCount !== 1 ? "s" : ""}
        </Text>
      </Text>
      {git.recentCommits.slice(0, 3).map((c) => (
        <Text key={c.hash}>
          <Text dimColor>{c.hash.slice(0, 7)}</Text> {c.message.slice(0, 40)}
        </Text>
      ))}
    </Box>
  );
}
