import React from "react";
import { Box, Text } from "ink";
import type { CommandDefinition } from "../types";
import { getRiskLabel } from "../data/commandPreview";
import { getSafetyColor } from "../data/safetyModel";

interface Props {
  command: CommandDefinition | null;
}

export function CommandPreview({ command }: Props) {
  if (!command) {
    return null;
  }

  const safetyColor = getSafetyColor(command.safetyLevel);
  const riskLabel = getRiskLabel(command.safetyLevel);

  return (
    <Box
      flexDirection="column"
      borderStyle="round"
      borderColor="yellow"
      paddingX={1}
    >
      <Text bold color="yellow">
        Command Preview — {command.name}
      </Text>

      <Box flexDirection="column" marginTop={0}>
        <Box flexDirection="row">
          <Text bold>Safety:{"  "}</Text>
          <Text color={safetyColor}>{command.safetyLevel}</Text>
        </Box>

        <Box flexDirection="row">
          <Text bold>Phase 2:{"  "}</Text>
          <Text color={command.executableInPhase2 ? "green" : "yellow"}>
            {command.executableInPhase2
              ? "可执行"
              : "preview-only（复制到 CLI 手动执行）"}
          </Text>
        </Box>

        <Box flexDirection="row">
          <Text bold>Risk:{"  "}</Text>
          <Text>{command.riskNote ?? riskLabel}</Text>
        </Box>

        {command.shellCommand && (
          <>
            <Box marginTop={1}>
              <Text bold>Shell command:</Text>
            </Box>
            <Box>
              <Text color="cyan">  {command.shellCommand}</Text>
            </Box>
          </>
        )}

        {command.relatedSkills && command.relatedSkills.length > 0 && (
          <Box marginTop={1}>
            <Text dimColor>Skills: {command.relatedSkills.join(", ")}</Text>
          </Box>
        )}
      </Box>

      <Box marginTop={1}>
        <Text color="yellow">
          ⚠ Phase 2 不执行此命令。请复制到终端手动运行。
        </Text>
      </Box>

      <Box marginTop={0}>
        <Text dimColor>Esc back  q quit</Text>
      </Box>
    </Box>
  );
}
