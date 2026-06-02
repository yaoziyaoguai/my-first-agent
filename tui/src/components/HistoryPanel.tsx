import React from "react";
import { Box, Text } from "ink";
import type { AgentHistoryIndex, RunHistory, HistorySource } from "../data/agentHistoryIndex";

interface HistoryPanelProps {
  focused: boolean;
  /** 当前选中的 agentId */
  agentId: string | null;
  /** M6: 历史数据源 */
  historySource: HistorySource;
}

const STATUS_COLORS: Record<string, string> = {
  pass: "green",
  fail: "red",
  partial: "yellow",
  unknown: "gray",
  active: "green",
  completed: "green",
  failed: "red",
  paused: "yellow",
};

function RunRow({ run, highlighted }: { run: RunHistory; highlighted: boolean }) {
  const statusColor = STATUS_COLORS[run.status] || "white";
  const date = new Date(run.createdAt).toLocaleDateString();
  const passCount = run.evidenceSummaries.filter((e) => e.status === "pass").length;
  const totalCount = run.evidenceSummaries.length;

  return (
    <Box flexDirection="column" paddingLeft={2} marginBottom={1}>
      <Box>
        <Text bold={highlighted} color={highlighted ? "yellow" : undefined}>
          {highlighted ? "▶" : " "} Run: {run.runId}
        </Text>
        <Text color={statusColor}> [{run.status}]</Text>
        <Text dimColor> {date}</Text>
        {run.commitHash && <Text dimColor> @{run.commitHash.slice(0, 7)}</Text>}
      </Box>
      <Box paddingLeft={2}>
        <Text dimColor>
          Evidence: {passCount}/{totalCount} pass
        </Text>
      </Box>
      <Box paddingLeft={2}>
        <Text dimColor>
          Gates:{" "}
          {run.gateSummaries.map((g) => (
            <Text key={g.gateId} color={STATUS_COLORS[g.status]}>
              {g.label}({g.status}){" "}
            </Text>
          ))}
        </Text>
      </Box>
    </Box>
  );
}

/** M6 — HistoryPanel（只读 projection，不写 runtime state）。
 *  展示 Agent 的历史 runs、evidence 摘要和 gate 摘要。 */
export function HistoryPanel({ focused, agentId, historySource }: HistoryPanelProps) {
  if (!agentId) {
    return (
      <Box flexDirection="column" borderStyle="single" paddingLeft={1} paddingRight={1}>
        <Box marginBottom={1}>
          <Text bold color={focused ? "green" : undefined}>
            {focused ? "◆" : "─"} History
          </Text>
        </Box>
        <Text dimColor>Select an agent to view history.</Text>
      </Box>
    );
  }

  const history = historySource.getAgentHistory(agentId);

  if (!history) {
    return (
      <Box flexDirection="column" borderStyle="single" paddingLeft={1} paddingRight={1}>
        <Box marginBottom={1}>
          <Text bold color={focused ? "green" : undefined}>
            {focused ? "◆" : "─"} History — {agentId}
          </Text>
        </Box>
        <Text dimColor>No history found for this agent.</Text>
        <Box marginTop={1}>
          <Text dimColor>fake/local mode — fixture data only</Text>
        </Box>
      </Box>
    );
  }

  const allRuns: (RunHistory & { sessionLabel: string })[] = [];
  for (const session of history.sessions) {
    for (const run of session.runs) {
      allRuns.push({ ...run, sessionLabel: session.label });
    }
  }
  allRuns.sort((a, b) => b.createdAt - a.createdAt);

  return (
    <Box flexDirection="column" borderStyle="single" paddingLeft={1} paddingRight={1}>
      <Box marginBottom={1}>
        <Text bold color={focused ? "green" : undefined}>
          {focused ? "◆" : "─"} History — {history.label}
        </Text>
      </Box>

      <Box marginBottom={1}>
        <Text dimColor>
          {history.sessions.length} session(s), {allRuns.length} run(s)
        </Text>
      </Box>

      {allRuns.length === 0 ? (
        <Text dimColor>No runs recorded.</Text>
      ) : (
        <Box flexDirection="column">
          {allRuns.map((run, idx) => (
            <RunRow key={run.runId} run={run} highlighted={focused && idx === 0} />
          ))}
        </Box>
      )}

      <Box marginTop={1}>
        <Text dimColor>fake/local history — read-only projection</Text>
      </Box>
    </Box>
  );
}
