import React from "react";
import { render } from "ink";
import path from "node:path";

import { WorkbenchLayout } from "./components/WorkbenchLayout";

const REPO_ROOT = path.resolve(import.meta.dirname, "..", "..");

/** B8 Interaction-first Workbench — 默认入口。
 *  不渲染 Dashboard / PROJECT_STATUS / AutoRun / dogfood / debt 等 Operation 相关内容。
 *  所有数据自包含（fixture），Context Panel 使用 mock/static placeholder。 */
function App() {
  return <WorkbenchLayout />;
}

render(<App />);
