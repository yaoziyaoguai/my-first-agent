import React from "react";
import { Box, Text } from "ink";
import type {
  ProjectStatus,
  ProgressLedger,
  DogfoodResult,
  GitInfo,
} from "../types";
import { OverviewPanel } from "./OverviewPanel";
import { EvidenceStatusPanel } from "./EvidenceStatusPanel";
import { WorkflowPanel } from "./WorkflowPanel";
import { GatePanel } from "./GatePanel";
import { EvidencePreviewPanel } from "./EvidencePreviewPanel";

interface Props {
  status: ProjectStatus;
  ledger: ProgressLedger;
  dogfood: DogfoodResult[];
  git: GitInfo;
}

export function Dashboard({ status, ledger, dogfood, git }: Props) {
  return (
    <Box flexDirection="column" padding={0}>
      {/* Header */}
      <Box flexDirection="column" marginBottom={1}>
        <Text bold backgroundColor="blue" color="white">
          {"  "}First Agent Workbench — B8-lite{"  "}
        </Text>
      </Box>

      {/* Row 1: Overview + Evidence Status */}
      <Box flexDirection="row" marginBottom={1}>
        <OverviewPanel status={status} />
        <EvidenceStatusPanel rows={status.realEvidenceRows} />
      </Box>

      {/* Row 2: Workflow (full width) */}
      <Box flexDirection="row" marginBottom={1}>
        <WorkflowPanel milestones={ledger.milestones} />
      </Box>

      {/* Row 3: Gate + Evidence Preview */}
      <Box flexDirection="row" marginBottom={1}>
        <GatePanel git={git} />
        <EvidencePreviewPanel results={dogfood} />
      </Box>

      {/* Footer */}
      <Box flexDirection="column">
        <Text dimColor>
          q: quit | B8-lite Phase 1 — static dashboard | {new Date().toISOString().slice(0, 10)}
        </Text>
      </Box>
    </Box>
  );
}
