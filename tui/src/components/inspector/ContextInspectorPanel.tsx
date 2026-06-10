/** Slice A — RightInspector container。Visual Target §3.16 */
import React from "react";
import { Box, Text } from "ink";
import type { InspectorStatusData } from "../../data/visualShellTypes";
import { ActiveContextPanel } from "./ActiveContextPanel";
import { RuntimeDecisionFramePanel } from "./RuntimeDecisionFramePanel";
import { ToolSummaryPanel } from "./ToolSummaryPanel";
import { McpBridgePanel } from "./McpBridgePanel";
import { RecentEventsPanel } from "./RecentEventsPanel";
import { MemoryCheckpointPanel } from "./MemoryCheckpointPanel";
import {
  SECTION_HEADER,
  DIM_TEXT,
  BORDER_CHARS,
} from "../../theme/visualShellTheme";

interface ContextInspectorPanelProps {
  width: number;
  height: number;
  data: InspectorStatusData;
  evidenceLens: boolean;
  fakeLabel: string;
}

export function ContextInspectorPanel({
  width,
  height,
  data,
  evidenceLens,
  fakeLabel,
}: ContextInspectorPanelProps) {
  return (
    <Box
      width={width}
      height={height}
      flexDirection="column"
      borderStyle="single"
      borderColor="gray"
    >
      <Box>
        <Text {...SECTION_HEADER}>Context Inspector</Text>
        <Text dimColor>  [{fakeLabel}]</Text>
      </Box>

      {/* Active Context */}
      <ActiveContextPanel
        agentId={data.activeContext.agentId}
        runId={data.activeContext.runId}
      />
      <Box>
        <Text dimColor>{BORDER_CHARS.h.repeat(width - 4)}</Text>
      </Box>

      {/* Runtime Frame */}
      <RuntimeDecisionFramePanel data={data.runtimeDecision} />
      <Box>
        <Text dimColor>{BORDER_CHARS.h.repeat(width - 4)}</Text>
      </Box>

      {/* Tool Summary */}
      <ToolSummaryPanel tools={data.toolSummary} />
      <Box>
        <Text dimColor>{BORDER_CHARS.h.repeat(width - 4)}</Text>
      </Box>

      {/* MCP Bridge */}
      <McpBridgePanel data={data.mcpBridge} />
      <Box>
        <Text dimColor>{BORDER_CHARS.h.repeat(width - 4)}</Text>
      </Box>

      {/* Events */}
      <RecentEventsPanel events={data.recentEvents} />
      <Box>
        <Text dimColor>{BORDER_CHARS.h.repeat(width - 4)}</Text>
      </Box>

      {/* Memory / Checkpoint */}
      <MemoryCheckpointPanel
        entryCount={data.memory.entryCount}
        lastCheckpointId={data.memory.lastCheckpointId}
      />

      {/* Evidence Snapshot — 仅在 Evidence lens 下展开 */}
      {evidenceLens ? (
        <>
          <Box>
            <Text dimColor>{BORDER_CHARS.h.repeat(width - 4)}</Text>
          </Box>
          <Box flexDirection="column">
            <Text {...SECTION_HEADER}>Evidence Snapshot</Text>
            <Text dimColor>items: {data.evidence.itemCount}</Text>
            <Text dimColor>source: static evidence fixture</Text>
            {data.evidence.items && data.evidence.items.length > 0 ? (
              data.evidence.items.map((item, i) => (
                <Text key={i} dimColor>
                  {"  "}
                  {item}
                </Text>
              ))
            ) : (
              <Text dimColor>  (no evidence detail)</Text>
            )}
            {data.evidence.skillEvidence && (
              <>
                <Box>
                  <Text dimColor>{BORDER_CHARS.h.repeat(width - 4)}</Text>
                </Box>
                <Text {...SECTION_HEADER}>Skill Evidence (D-09)</Text>
                <Text dimColor>
                  status: {data.evidence.skillEvidence.status}
                </Text>
                <Text dimColor>
                  {data.evidence.skillEvidence.summary}
                </Text>
              </>
            )}
          </Box>
        </>
      ) : (
        <Box marginTop={0}>
          <Text dimColor>
            evidence: {data.evidence.itemCount} items
          </Text>
        </Box>
      )}
    </Box>
  );
}
