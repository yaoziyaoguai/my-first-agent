import React from "react";
import { Box, Text } from "ink";
import type { Milestone } from "../types";

export function WorkflowPanel({ milestones }: { milestones: Milestone[] }) {
  const recent = milestones.slice(0, 8);

  return (
    <Box
      flexDirection="column"
      borderStyle="single"
      borderColor="green"
      paddingX={1}
    >
      <Text bold color="green">
        Workflow — Recent Milestones
      </Text>
      <Text dimColor>{"─".repeat(60)}</Text>
      {recent.length === 0 && <Text dimColor>No milestones</Text>}
      {recent.map((m, i) => (
        <Text key={`${m.date}-${i}`}>
          <Text color="yellow">{m.date}</Text>
          {"  "}
          <Text bold>{m.title}</Text>
          {m.commit ? <Text dimColor> {m.commit.slice(0, 7)}</Text> : null}
          {" — "}
          <Text>{m.summary.slice(0, 60)}</Text>
        </Text>
      ))}
    </Box>
  );
}
