import React from "react";
import { render } from "ink";

import { TuiShell } from "./components/shell/TuiShell";
import { SAFE_DATA_FIXTURE } from "./data/visualShellFixtures";
import { WorkbenchLayout } from "./components/WorkbenchLayout";

// Slice A — Visual Shell exports
export { TuiShell } from "./components/shell/TuiShell";
export { FULL_FIXTURE, EMPTY_FIXTURE, SAFE_DATA_FIXTURE, SAFE_DATA_PROVENANCE } from "./data/visualShellFixtures";
export type { VisualShellFixture } from "./data/visualShellTypes";
export { ALL_VIEW_LENSES, DEFAULT_VIEW_LENS } from "./data/visualShellTypes";
export type { ViewLens } from "./data/visualShellTypes";

// Slice B — safe data adapter exports
export { buildVisualShellViewModel, buildDefaultViewModel } from "./data/visualShellDataAdapter";
export type { SafeDataSources, VisualShellViewModel } from "./data/visualShellDataAdapter";
export {
  SAFE_RUNTIME_DECISION,
  SAFE_MCP_STATUS,
  SAFE_TOOL_SUMMARY,
  SAFE_EVENTS,
  SAFE_MEMORY_CKPT,
  SAFE_PROVIDER_LABEL,
  SAFE_RUNTIME_STATUS,
  SAFE_BOTTOM_STATUS,
  SAFE_TOP_BAR,
  SAFE_WORKSPACES,
  SAFE_LENSES,
  SAFE_SESSIONS,
  SAFE_MESSAGES,
  SAFE_TOOL_CALLS,
  SAFE_PENDING_ACTIONS,
  SAFE_TABLE_RESULTS,
  SAFE_EVIDENCE_ITEMS,
  SAFE_SKILL_EVIDENCE,
} from "./data/safeDataSources";

const isLegacy = process.argv.includes("--legacy") || process.argv.includes("--workbench");

/** 默认入口: Visual Shell (TuiShell + SAFE_DATA_FIXTURE)。
 *  --legacy / --workbench: 旧 B8 Interaction-first Workbench。 */
function App() {
  if (isLegacy) {
    return <WorkbenchLayout />;
  }
  return <TuiShell fixture={SAFE_DATA_FIXTURE} />;
}

render(<App />);
