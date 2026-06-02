import React from "react";
import { Box, Text } from "ink";
import type { PendingAction } from "../data/pendingAction";

interface PendingActionPanelProps {
  actions: PendingAction[];
  focused: boolean;
  highlightedIdx: number;
  onApprove: (actionId: string) => void;
  onReject: (actionId: string) => void;
}

const RISK_COLORS: Record<string, string> = {
  low: "green",
  medium: "yellow",
  high: "red",
  critical: "red",
};

const TYPE_LABELS: Record<string, string> = {
  tool_confirmation: "TOOL",
  memory_proposal: "MEM",
  checkpoint_save: "CKPT",
  safety_gate: "SAFE",
};

export function PendingActionPanel({
  actions,
  focused,
  highlightedIdx,
  onApprove,
  onReject,
}: PendingActionPanelProps) {
  if (actions.length === 0) return null;

  return (
    <Box flexDirection="column" marginTop={1}>
      <Box marginBottom={1}>
        <Text bold color={focused ? "yellow" : undefined}>
          ⚡ Pending Actions ({actions.length})
        </Text>
      </Box>
      {actions.map((action, idx) => {
        const isHighlighted = focused && idx === highlightedIdx;
        const riskColor = RISK_COLORS[action.riskLevel] || "white";
        const typeLabel = TYPE_LABELS[action.type] || action.type;

        return (
          <Box key={action.actionId} flexDirection="column" marginBottom={1}>
            <Box>
              <Text
                bold={isHighlighted}
                inverse={isHighlighted}
                color={isHighlighted ? "yellow" : undefined}
              >
                {isHighlighted ? "▶" : " "} [{typeLabel}] {action.title}
              </Text>
            </Box>
            <Box paddingLeft={4}>
              <Text dimColor>{action.description}</Text>
            </Box>
            <Box paddingLeft={4}>
              <Text color={riskColor}>Risk: {action.riskLevel}</Text>
              {action.requiresConfirmation && (
                <Text dimColor> | Confirmation: required</Text>
              )}
              <Text dimColor> | Source: {action.source}</Text>
            </Box>
            {action.outcomeMessage && (
              <Box paddingLeft={4}>
                <Text
                  color={
                    action.status === "approved"
                      ? "green"
                      : action.status === "rejected"
                        ? "red"
                        : undefined
                  }
                >
                  → {action.outcomeMessage}
                </Text>
              </Box>
            )}
          </Box>
        );
      })}
      {focused && (
        <Box marginTop={1}>
          <Text dimColor>Enter: approve | Escape: reject | ↑↓: navigate</Text>
        </Box>
      )}
    </Box>
  );
}
