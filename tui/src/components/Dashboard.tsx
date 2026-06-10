import React, { useState } from "react";
import { Box, Text, useInput, useApp } from "ink";
import type {
  ProjectStatus,
  ProgressLedger,
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
import { CommandPanel } from "./CommandPanel";
import { NextActionPanel } from "./NextActionPanel";
import { CommandPreview as CommandPreviewOverlay } from "./CommandPreview";
import { NavigationBar } from "./NavigationBar";
import { TaskCenterPanel } from "./TaskCenterPanel";
import { EvidenceDetailPanel } from "./EvidenceDetailPanel";
import { DocsConsistencyPanel } from "./DocsConsistencyPanel";
import { ConfirmOverlay } from "./ConfirmOverlay";
import { DryRunOverlay } from "./DryRunOverlay";
import { ResultPanel } from "./ResultPanel";
import { EvidenceBrowserPanel } from "./EvidenceBrowserPanel";
import { AuditLogPanel } from "./AuditLogPanel";
import { DefaultEntryReadinessPanel } from "./DefaultEntryReadinessPanel";
import type { EvidenceFileEntry } from "../data/evidenceBrowser";
import type { AuditLogEntry } from "../data/auditLog";
import type { AutoRunState } from "../data/autorunState";
import type { ReviewPacket } from "../data/reviewPacket";
import { AutoRunPanel } from "./AutoRunPanel";
import { HardStopOverlay } from "./HardStopOverlay";
import { ReviewPacketPanel } from "./ReviewPacketPanel";
import { isSelectable } from "../data/safetyModel";
import { isAllowed } from "../data/executionWhitelist";
import {
  createConfirmationRequest,
  confirmExecution,
  cancelExecution,
  dryRunExecution,
  type ConfirmationResult,
} from "../data/executionGate";
import type { ExecutionResult } from "../data/commandResult";
import { execute } from "../services/executionService";

interface Props {
  status: ProjectStatus;
  ledger: ProgressLedger;
  git: GitInfo;
  catalog: CommandCatalog;
  nextAction: string;
  evidenceFiles: EvidenceFileEntry[];
  auditEntries: AuditLogEntry[];
  autoRunState: AutoRunState;
  reviewPacket: ReviewPacket;
  repoRoot: string;
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

type Phase4Mode =
  | "preview"    // Phase 2/3 preview mode
  | "confirm"    // confirmation overlay
  | "dry-run"    // dry-run overlay
  | "executing"  // confirmed, executing (future: actual exec)
  | "result";    // showing result

export function Dashboard({ status, ledger, git, catalog, nextAction, evidenceFiles, auditEntries, autoRunState, reviewPacket, repoRoot }: Props) {
  const [nav, setNav] = useState(createNavigationState());
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [evidenceSelectedIndex, setEvidenceSelectedIndex] = useState(0);
  const [showPreview, setShowPreview] = useState(false);
  const [phase4Mode, setPhase4Mode] = useState<Phase4Mode>("preview");
  const [confirmResult, setConfirmResult] = useState<ConfirmationResult | null>(null);
  const [executionResult, setExecutionResult] = useState<ExecutionResult | null>(null);
  const { exit } = useApp();

  const selectableCount = catalog.commands.filter((c) => isSelectable(c.safetyLevel)).length;

  const selectedCommand =
    selectedIndex >= 0 && selectedIndex < catalog.commands.length
      ? catalog.commands[selectedIndex]
      : null;

  const isPhase4Ready = selectedCommand !== null && isAllowed(selectedCommand.id);

  const handleConfirmKey = (input: string, key: { escape?: boolean; return?: boolean }) => {
    if (!selectedCommand) return;

    if (phase4Mode === "confirm" && confirmResult) {
      if (confirmResult.needsDoubleConfirmText) {
        // Double confirmation — only "yes" works, any other input stays
        if (input === "y" || input === "e") {
          // y/e won't work for double confirm — must type "yes"
          return;
        }
        // Any key returns to "preview" mode
        if (input !== "") {
          setPhase4Mode("preview");
          setConfirmResult(null);
        }
        return;
      }

      // Single confirmation
      if (input === "y") {
        const confirmed = confirmExecution(confirmResult);
        if (confirmed.needsDoubleConfirmText) {
          setConfirmResult(confirmed);
          return;
        }
        setConfirmResult(confirmed);
        setPhase4Mode("executing");

        const confirmationType: AuditLogEntry["confirmation"] =
          selectedCommand.id === "autorun" ? "double" : "single";
        execute({
          commandId: selectedCommand.id,
          shellCommand: selectedCommand.shellCommand ?? "",
          safetyLevel: selectedCommand.safetyLevel,
          repoRoot,
          confirmation: confirmationType,
        }).then((execR) => {
          setExecutionResult(execR);
          setPhase4Mode("result");
        });
        return;
      }

      if (input === "n") {
        setConfirmResult(cancelExecution(selectedCommand.id));
        return;
      }

      if (input === "d") {
        const dryResult = dryRunExecution(selectedCommand);
        setConfirmResult(dryResult);
        setPhase4Mode("dry-run");
        return;
      }
      return;
    }

    // In dry-run overlay
    if (phase4Mode === "dry-run") {
      if (input === "y" || input === "e") {
        setPhase4Mode("executing");

        const confirmationType: AuditLogEntry["confirmation"] = "single";
        execute({
          commandId: selectedCommand.id,
          shellCommand: selectedCommand.shellCommand ?? "",
          safetyLevel: selectedCommand.safetyLevel,
          repoRoot,
          confirmation: confirmationType,
        }).then((execR) => {
          setExecutionResult(execR);
          setPhase4Mode("result");
        });
        return;
        return;
      }
      if (input === "n" || key.escape) {
        setPhase4Mode("preview");
        setConfirmResult(null);
        setShowPreview(false);
        return;
      }
      return;
    }

    // In result panel
    if (phase4Mode === "result") {
      if (input === "b" || key.escape) {
        setPhase4Mode("preview");
        setConfirmResult(null);
        setExecutionResult(null);
        setShowPreview(false);
        return;
      }
      return;
    }
  };

  useInput((input, key) => {
    // Phase 4 keys when showPreview is active
    if (showPreview) {
      if (phase4Mode !== "preview") {
        handleConfirmKey(input, key);
        if (key.escape) {
          setPhase4Mode("preview");
          setConfirmResult(null);
        }
        return;
      }

      if (key.escape || input === "q") {
        if (input === "q") {
          exit();
          return;
        }
        setShowPreview(false);
        return;
      }

      // Enter on Phase 4 ready command -> confirm overlay
      if (key.return && isPhase4Ready) {
        const req = createConfirmationRequest(selectedCommand!);
        const result = confirmExecution(req);
        setConfirmResult(result);
        setPhase4Mode("confirm");
        return;
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
          setPhase4Mode("preview");
          setConfirmResult(null);
          setExecutionResult(null);
        }
      }
    }

    // Evidence browser navigation (only in Evidence view)
    if (nav.currentView === "evidence") {
      if (key.upArrow) {
        setEvidenceSelectedIndex((prev) => Math.max(0, prev - 1));
        return;
      }
      if (key.downArrow) {
        setEvidenceSelectedIndex((prev) =>
          Math.min(evidenceFiles.length - 1, prev + 1),
        );
        return;
      }
    }
  });

  const renderCommandsView = () => {
    if (!showPreview) {
      return (
        <Box flexDirection="row" marginBottom={1}>
          <CommandPanel catalog={catalog} selectedIndex={selectedIndex} />
          <NextActionPanel nextAction={nextAction} />
        </Box>
      );
    }

    // Phase 4 overlay states
    return (
      <Box flexDirection="column" marginBottom={1}>
        <Box flexDirection="row" marginBottom={1}>
          <CommandPanel catalog={catalog} selectedIndex={selectedIndex} />
          <NextActionPanel nextAction={nextAction} />
        </Box>
        {phase4Mode === "preview" && selectedCommand && (
          <Box>
            <CommandPreviewOverlay command={selectedCommand} />
          </Box>
        )}
        {phase4Mode === "confirm" && selectedCommand && confirmResult && (
          <Box>
            <ConfirmOverlay
              request={createConfirmationRequest(selectedCommand)}
              result={confirmResult}
            />
          </Box>
        )}
        {phase4Mode === "dry-run" && selectedCommand && confirmResult && (
          <Box>
            <DryRunOverlay result={confirmResult} />
          </Box>
        )}
        {phase4Mode === "result" && executionResult && (
          <Box>
            <ResultPanel result={executionResult} />
          </Box>
        )}
      </Box>
    );
  };

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
          <Box flexDirection="column" marginBottom={1}>
            <Box marginBottom={1}>
              <EvidenceDetailPanel />
            </Box>
            <Box flexDirection="row">
              <EvidenceBrowserPanel
                entries={evidenceFiles}
                selectedIndex={evidenceSelectedIndex}
              />
            </Box>
          </Box>
        );
      case "workflow":
        return (
          <Box flexDirection="column" marginBottom={1}>
            {autoRunState.status === "hard_stop" && autoRunState.hardStopReason && (
              <HardStopOverlay
                reason={autoRunState.hardStopReason}
                loop={autoRunState.lastLoop || undefined}
              />
            )}
            <AutoRunPanel state={autoRunState} />
            <ReviewPacketPanel packet={reviewPacket} />
            <Box marginTop={1}>
              <WorkflowPanel milestones={ledger.milestones} />
            </Box>
          </Box>
        );
      case "commands":
        return renderCommandsView();
      case "tasks":
        return (
          <Box marginBottom={1}>
            <TaskCenterPanel />
          </Box>
        );
      case "gates":
        return (
          <Box flexDirection="column" marginBottom={1}>
            <Box flexDirection="row" marginBottom={1}>
              <GatePanel git={git} />
            </Box>
            <Box>
              <AuditLogPanel entries={auditEntries} />
            </Box>
          </Box>
        );
      case "docs":
        return (
          <Box flexDirection="column" marginBottom={1}>
            <Box marginBottom={1}>
              <DocsConsistencyPanel />
            </Box>
            <Box>
              <DefaultEntryReadinessPanel />
            </Box>
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
          q: quit | ← → / 1-7: switch view | {nav.currentView === "commands" ? "↑↓: navigate | Enter: preview/execute | " : ""}{nav.currentView === "evidence" ? "↑↓: browse evidence | " : ""}B8 Phase 1-6A — boundary closed | {new Date().toISOString().slice(0, 10)}
        </Text>
      </Box>
    </Box>
  );
}
