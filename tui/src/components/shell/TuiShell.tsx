/** Slice A — 顶层 6 区域布局容器。Visual Target §3.1 */
import React, { useState } from "react";
import { Box, Text } from "ink";
import type { VisualShellFixture, ViewLens } from "../../data/visualShellTypes";
import { TuiTopBar } from "./TuiTopBar";
import { LeftRail } from "./LeftRail";
import { MainWorkArea } from "../work-area/MainWorkArea";
import { InputDock } from "../input/InputDock";
import { ContextInspectorPanel } from "../inspector/ContextInspectorPanel";
import { BottomStatusBar } from "./BottomStatusBar";
import { DIM_TEXT } from "../../theme/visualShellTheme";

/** 宽度断点 — Visual Target §2.3 */
function calcColumnWidths(
  termWidth: number,
): { leftRailW: number; mainW: number; rightInspectorW: number; compact: boolean } {
  if (termWidth < 80) {
    return { leftRailW: 20, mainW: termWidth - 20, rightInspectorW: 0, compact: true };
  }
  if (termWidth < 120) {
    return { leftRailW: 22, mainW: Math.max(34, termWidth - 46), rightInspectorW: 24, compact: false };
  }
  return { leftRailW: 28, mainW: Math.max(56, termWidth - 64), rightInspectorW: 36, compact: false };
}

interface TuiShellProps {
  fixture: VisualShellFixture;
  width?: number;
  height?: number;
}

export function TuiShell({
  fixture,
  width = 120,
  height = 36,
}: TuiShellProps) {
  const [selectedLens, setSelectedLens] = useState<ViewLens>("Agent");
  const evidenceLens = selectedLens === "Evidence";
  const { leftRailW, mainW, rightInspectorW, compact } =
    calcColumnWidths(width);

  return (
    <Box flexDirection="column" width={width}>
      {/* TopBar — 1 row */}
      <TuiTopBar data={fixture.topBar} width={width} />

      {/* 分隔线 */}
      <Box width={width} height={1}>
        <Text dimColor>{"─".repeat(width)}</Text>
      </Box>

      {/* 三列主区域 */}
      <Box flexDirection="row" height={height - 6}>
        {/* LeftRail */}
        <LeftRail
          width={leftRailW}
          height={height - 6}
          workspaces={fixture.workspaces}
          viewLenses={fixture.viewLens}
          sessions={fixture.sessions}
          runtimeStatus={fixture.runtimeStatus}
          fakeLabel={fixture._label}
        />

        {/* MainWorkArea */}
        <Box width={mainW} flexDirection="column">
          <MainWorkArea
            width={mainW}
            messages={fixture.messages}
            toolCalls={fixture.toolCalls}
            pendingActions={fixture.pendingActions}
            fakeLabel={fixture._label}
          />

          {/* InputDock — 底部固定 */}
          <InputDock
            width={mainW}
            placeholder="hey, can you check the config?"
            isFake={fixture.topBar.isFake}
          />
        </Box>

        {/* RightInspector — compact mode 下可隐藏 */}
        {rightInspectorW > 0 && (
          <ContextInspectorPanel
            width={rightInspectorW}
            height={height - 6}
            data={fixture.inspector}
            evidenceLens={evidenceLens}
            fakeLabel={fixture._label}
          />
        )}
      </Box>

      {/* 分隔线 */}
      <Box width={width} height={1}>
        <Text dimColor>{"─".repeat(width)}</Text>
      </Box>

      {/* BottomStatusBar — 1 row */}
      <BottomStatusBar
        data={fixture.bottomStatus}
        width={width}
        evidenceLens={evidenceLens}
      />

      {/* Compact mode 警告 */}
      {compact && (
        <Box width={width} height={1}>
          <Text dimColor>
            [compact mode — RightInspector hidden, use Tab to toggle]
          </Text>
        </Box>
      )}
    </Box>
  );
}
