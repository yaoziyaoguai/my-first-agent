/** Phase 6A: Static Evidence Browser Panel */
import React from "react";
import { Box, Text } from "ink";
import type { EvidenceFileEntry, EvidenceStatus } from "../data/evidenceBrowser";

interface Props {
  entries: EvidenceFileEntry[];
  selectedIndex: number;
}

const STATUS_COLORS: Record<EvidenceStatus, string> = {
  credible: "green",
  "credible-with-caveats": "yellow",
  "partial-credible": "yellow",
  unknown: "dim",
};

const STATUS_LABELS: Record<EvidenceStatus, string> = {
  credible: "✓ credible",
  "credible-with-caveats": "⚠ credible*",
  "partial-credible": "△ partial",
  unknown: "? unknown",
};

export function EvidenceBrowserPanel({ entries, selectedIndex }: Props) {
  if (entries.length === 0) {
    return (
      <Box flexDirection="column" borderStyle="single" borderColor="dim" padding={1}>
        <Text bold>Evidence Files</Text>
        <Text dimColor>No dogfood result files found in docs/dogfood/</Text>
      </Box>
    );
  }

  return (
    <Box flexDirection="column" borderStyle="single" borderColor="cyan" padding={1}>
      <Text bold>Evidence Files ({entries.length})</Text>
      {entries.slice(0, 10).map((entry, i) => {
        const isSelected = i === selectedIndex;
        const color = STATUS_COLORS[entry.status] ?? "white";
        const label = STATUS_LABELS[entry.status] ?? entry.status;
        const prefix = isSelected ? "▶" : " ";

        return (
          <Box key={i} flexDirection="column" marginBottom={0}>
            <Text>
              {prefix} <Text color={color}>{label}</Text>{" "}
              <Text bold={isSelected}>{entry.fileName}</Text>
            </Text>
            <Text dimColor>
              {"  "}P:{entry.pass} C:{entry.concern} F:{entry.fail}{" "}
              {entry.evidenceId && `(${entry.evidenceId})`}
              {entry.error && ` [${entry.error}]`}
            </Text>
          </Box>
        );
      })}
      {entries.length > 10 && (
        <Text dimColor>(+{entries.length - 10} more files)</Text>
      )}
    </Box>
  );
}
