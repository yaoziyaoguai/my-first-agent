import React, { useState } from "react";
import { Box, Text, useInput, useApp } from "ink";
import type {
  ProjectStatus,
  ProgressLedger,
  DogfoodResult,
  GitInfo,
  CommandCatalog,
} from "../types";
import {
  createNavigationState,
  navigateTo,
  navigateNext,
  navigatePrev,
  VIEWS,
  type ViewId,
} from "../data/navigation";
import { OverviewPanel } from "./OverviewPanel";
import { EvidenceStatusPanel } from "./EvidenceStatusPanel";
import { WorkflowPanel } from "./WorkflowPanel";
import { GatePanel } from "./GatePanel";
import { EvidencePreviewPanel } from "./EvidencePreviewPanel";
import { CommandPanel } from "./CommandPanel";
import { NextActionPanel } from "./NextActionPanel";
import { CommandPreview as CommandPreviewOverlay } from "./CommandPreview";
import { NavigationBar } from "./NavigationBar";
import { TaskCenterPanel } from "./TaskCenterPanel";
import { EvidenceDetailPanel } from "./EvidenceDetailPanel";
import { DocsConsistencyPanel } from "./DocsConsistencyPanel";
import { isSelectable } from "../data/safetyModel";

interface Props {
  status: ProjectStatus;
  ledger: ProgressLedger;
  dogfood: DogfoodResult[];
  git: GitInfo;
  catalog: CommandCatalog;
  nextAction: string;
}

const VIEW_ID_MAP: Record<string, ViewId> = {
  "1": "overview",
  "2": "evidence",
  "3": "workflow",
  "4": "commands",
  "5": "tasks",
  "6": "gates",
  "7": "docs",
};

export function Dashboard({ status, ledger, dogfood, git, catalog, nextAction }: Props) {
  const [nav, setNav] = useState(createNavigationState());
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [showPreview, setShowPreview] = useState(false);
  const { exit } = useApp();

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

    // View switching: ← → or 1-7
    if (key.leftArrow) {
      setNav(navigatePrev(nav));
      setSelectedIndex(0);
      return;
    }

    if (key.rightArrow) {
      setNav(navigateNext(nav));
      setSelectedIndex(0);
      return;
    }

    const mappedView = VIEW_ID_MAP[input];
    if (mappedView) {
      const next = navigateTo(nav, mappedView);
      setNav(next);
      setSelectedIndex(0);
      return;
    }

    // Command navigation (only in Commands view)
    const isCommandsView = nav.currentView === "commands";
    if (isCommandsView) {
      if (key.upArrow) {
        setSelectedIndex((prev) => {
          let nextIdx = prev - 1;
          while (nextIdx >= 0) {
            if (isSelectable(catalog.commands[nextIdx].safetyLevel)) return nextIdx;
            nextIdx--;
          }
          return prev;
        });
        return;
      }

      if (key.downArrow) {
        setSelectedIndex((prev) => {
          let nextIdx = prev + 1;
          while (nextIdx < catalog.commands.length) {
            if (isSelectable(catalog.commands[nextIdx].safetyLevel)) return nextIdx;
            nextIdx++;
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
    }
  });

  const selectedCommand =
    selectedIndex >= 0 && selectedIndex < catalog.commands.length
      ? catalog.commands[selectedIndex]
      : null;

  const renderActiveView = () => {
    switch (nav.currentView) {
      case "overview":
        return (
          <Box flexDirection="row" marginBottom={1}>
            <OverviewPanel status={status} />
            <EvidenceStatusPanel rows={status.realEvidenceRows} />
          </Box>
        );
      case "evidence":
        return (
          <Box marginBottom={1}>
            <EvidenceDetailPanel />
          </Box>
        );
      case "workflow":
        return (
          <Box marginBottom={1}>
            <WorkflowPanel milestones={ledger.milestones} />
          </Box>
        );
      case "commands":
        return (
          <Box flexDirection="column" marginBottom={1}>
            <Box flexDirection="row" marginBottom={1}>
              <CommandPanel catalog={catalog} selectedIndex={selectedIndex} />
              <NextActionPanel nextAction={nextAction} />
            </Box>
            {showPreview && selectedCommand && (
              <Box>
                <CommandPreviewOverlay command={selectedCommand} />
              </Box>
            )}
          </Box>
        );
      case "tasks":
        return (
          <Box marginBottom={1}>
            <TaskCenterPanel />
          </Box>
        );
      case "gates":
        return (
          <Box flexDirection="row" marginBottom={1}>
            <GatePanel git={git} />
            <EvidencePreviewPanel results={dogfood} />
          </Box>
        );
      case "docs":
        return (
          <Box marginBottom={1}>
            <DocsConsistencyPanel />
          </Box>
        );
    }
  };

  const viewLabel = VIEWS.find((v) => v.id === nav.currentView)?.label ?? nav.currentView;

  return (
    <Box flexDirection="column" padding={0}>
      {/* Header */}
      <Box flexDirection="column" marginBottom={1}>
        <Text bold backgroundColor="blue" color="white">
          {"  "}First Agent Workbench — B8 | {viewLabel}{"  "}
        </Text>
      </Box>

      {/* Navigation bar (always visible) */}
      <Box marginBottom={1}>
        <NavigationBar currentView={nav.currentView} />
      </Box>

      {/* Active view content */}
      {renderActiveView()}

      {/* Footer */}
      <Box flexDirection="column">
        <Text dimColor>
          q: quit | ← → / 1-7: switch view | {nav.currentView === "commands" ? "↑↓: navigate | Enter: preview | " : ""}B8 Phase 3 — workbench | {new Date().toISOString().slice(0, 10)}
        </Text>
      </Box>
    </Box>
  );
}
