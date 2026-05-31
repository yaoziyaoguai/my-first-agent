import React, { useState } from "react";
import { Box, Text, useInput, useApp } from "ink";
import type {
  ProjectStatus,
  ProgressLedger,
  DogfoodResult,
  GitInfo,
  CommandCatalog,
} from "../types";
import { OverviewPanel } from "./OverviewPanel";
import { EvidenceStatusPanel } from "./EvidenceStatusPanel";
import { WorkflowPanel } from "./WorkflowPanel";
import { GatePanel } from "./GatePanel";
import { EvidencePreviewPanel } from "./EvidencePreviewPanel";
import { CommandPanel } from "./CommandPanel";
import { NextActionPanel } from "./NextActionPanel";
import { CommandPreview as CommandPreviewOverlay } from "./CommandPreview";
import { isSelectable } from "../data/safetyModel";

interface Props {
  status: ProjectStatus;
  ledger: ProgressLedger;
  dogfood: DogfoodResult[];
  git: GitInfo;
  catalog: CommandCatalog;
  nextAction: string;
}

export function Dashboard({ status, ledger, dogfood, git, catalog, nextAction }: Props) {
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [showPreview, setShowPreview] = useState(false);
  const { exit } = useApp();

  // Count selectable commands for index clamping
  const selectableCount = catalog.commands.filter((c) => isSelectable(c.safetyLevel)).length;

  useInput((input, key) => {
    if (showPreview) {
      if (key.escape || input === "q") {
        if (input === "q") {
          exit();
          return;
        }
        setShowPreview(false);
      }
      return;
    }

    if (input === "q") {
      exit();
      return;
    }

    if (key.upArrow) {
      setSelectedIndex((prev) => {
        let next = prev - 1;
        while (next >= 0) {
          if (isSelectable(catalog.commands[next].safetyLevel)) return next;
          next--;
        }
        return prev;
      });
      return;
    }

    if (key.downArrow) {
      setSelectedIndex((prev) => {
        let next = prev + 1;
        while (next < catalog.commands.length) {
          if (isSelectable(catalog.commands[next].safetyLevel)) return next;
          next++;
        }
        return prev;
      });
      return;
    }

    if (key.return) {
      const cmd = catalog.commands[selectedIndex];
      if (cmd && isSelectable(cmd.safetyLevel)) {
        setShowPreview(true);
      }
    }
  });

  const selectedCommand =
    selectedIndex >= 0 && selectedIndex < catalog.commands.length
      ? catalog.commands[selectedIndex]
      : null;

  return (
    <Box flexDirection="column" padding={0}>
      {/* Header */}
      <Box flexDirection="column" marginBottom={1}>
        <Text bold backgroundColor="blue" color="white">
          {"  "}First Agent Workbench — B8{"  "}
        </Text>
      </Box>

      {/* Row 1: Overview + Evidence Status */}
      <Box flexDirection="row" marginBottom={1}>
        <OverviewPanel status={status} />
        <EvidenceStatusPanel rows={status.realEvidenceRows} />
      </Box>

      {/* Row 2: Commands + Next Action */}
      <Box flexDirection="row" marginBottom={1}>
        <CommandPanel catalog={catalog} selectedIndex={selectedIndex} />
        <NextActionPanel nextAction={nextAction} />
      </Box>

      {/* Row 3: Workflow (full width) */}
      <Box flexDirection="row" marginBottom={1}>
        <WorkflowPanel milestones={ledger.milestones} />
      </Box>

      {/* Row 4: Gate + Evidence Preview */}
      <Box flexDirection="row" marginBottom={1}>
        <GatePanel git={git} />
        <EvidencePreviewPanel results={dogfood} />
      </Box>

      {/* CommandPreview overlay */}
      {showPreview && selectedCommand && (
        <Box marginBottom={1}>
          <CommandPreviewOverlay command={selectedCommand} />
        </Box>
      )}

      {/* Footer */}
      <Box flexDirection="column">
        <Text dimColor>
          q: quit | ↑↓: navigate | Enter: preview | B8 Phase 2 — command shell | {new Date().toISOString().slice(0, 10)}
        </Text>
      </Box>
    </Box>
  );
}
