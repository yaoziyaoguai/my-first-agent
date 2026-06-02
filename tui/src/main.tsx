import React from "react";
import { render } from "ink";
import path from "node:path";

import { WorkbenchLayout } from "./components/WorkbenchLayout";

// Slice A — Visual Shell export (component-level only, NOT default entry).
// To smoke-test standalone: import { TuiShell } and render with FULL_FIXTURE/EMPTY_FIXTURE.
export { TuiShell } from "./components/shell/TuiShell";
export { FULL_FIXTURE, EMPTY_FIXTURE } from "./data/visualShellFixtures";
export type { VisualShellFixture } from "./data/visualShellTypes";
export { ALL_VIEW_LENSES, DEFAULT_VIEW_LENS } from "./data/visualShellTypes";
export type { ViewLens } from "./data/visualShellTypes";

const REPO_ROOT = path.resolve(import.meta.dirname, "..", "..");

/** B8 Interaction-first Workbench — 默认入口。
 *  不渲染 Dashboard / PROJECT_STATUS / AutoRun / dogfood / debt 等 Operation 相关内容。
 *  所有数据自包含（fixture），Context Panel 使用 mock/static placeholder。 */
function App() {
  return <WorkbenchLayout />;
}

render(<App />);
