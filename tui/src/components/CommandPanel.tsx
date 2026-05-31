import React from "react";
import { Box, Text } from "ink";
import type { CommandCatalog, CommandDefinition } from "../types";
import { isSelectable, getSafetyColor } from "../data/safetyModel";
import { buildGroupedCommands } from "../data/commandPanel";

interface Props {
  catalog: CommandCatalog;
  selectedIndex: number;
}

const CATEGORY_LABELS: Record<string, string> = {
  workflow: "Workflow",
  diagnostics: "Diagnostics",
  execution: "Execution",
  gates: "Gates",
  docs: "Docs",
};

export function CommandPanel({ catalog, selectedIndex }: Props) {
  const groups = buildGroupedCommands(catalog);

  // Flatten grouped commands to compute global index
  const flatCommands: Array<{ cmd: CommandDefinition; category: string }> = [];
  for (const [category, cmds] of groups) {
    for (const cmd of cmds) {
      flatCommands.push({ cmd, category });
    }
  }

  const lines: React.ReactNode[] = [];

  let currentCategory = "";
  for (let i = 0; i < flatCommands.length; i++) {
    const { cmd, category } = flatCommands[i];
    const isSelected = i === selectedIndex;
    const selectable = isSelectable(cmd.safetyLevel);
    const color = getSafetyColor(cmd.safetyLevel);

    if (category !== currentCategory) {
      currentCategory = category;
      lines.push(
        <Text key={`cat-${category}`} bold color="cyan">
          {CATEGORY_LABELS[category] ?? category}
        </Text>,
      );
    }

    const prefix = isSelected ? "▶" : " ";
    const name = selectable ? cmd.name : `${cmd.name} (不可选)`;
    const safety = `[${cmd.safetyLevel}]`;

    lines.push(
      <Box key={cmd.id} flexDirection="row">
        <Text color={isSelected ? "green" : undefined} bold={isSelected}>
          {prefix}{" "}
        </Text>
        <Text color={color} dimColor={!selectable}>
          {name.padEnd(22)}{" "}
        </Text>
        <Text dimColor={!selectable} color={color}>
          {safety}
        </Text>
      </Box>,
    );
  }

  return (
    <Box
      flexDirection="column"
      borderStyle="round"
      borderColor="blue"
      paddingX={1}
    >
      <Text bold color="blue">
        Commands
      </Text>
      <Box flexDirection="column" marginTop={0}>
        {lines.length > 0 ? (
          lines
        ) : (
          <Text dimColor>No commands loaded</Text>
        )}
      </Box>
      <Box marginTop={1}>
        <Text dimColor>↑↓ navigate  Enter preview  q quit</Text>
      </Box>
    </Box>
  );
}
