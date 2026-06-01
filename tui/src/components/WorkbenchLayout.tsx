import React, { useState, useCallback } from "react";
import { Box, Text, useInput, useApp } from "ink";
import type { FocusZone, SelectedLens } from "../types";
import { EMPTY_SELECTED_LENS } from "../types";
import { AGENT_LENS_FIXTURE } from "../data/agentLensFixture";
import { AgentLensPanel } from "./AgentLensPanel";
import { InteractionPanel } from "./InteractionPanel";
import { ContextPanel } from "./ContextPanel";
import { InputBar } from "./InputBar";
import { StatusBar } from "./StatusBar";

const FOCUS_ORDER: FocusZone[] = ["interaction", "agent-lens", "context"];

/** B8 Interaction-first Workbench — 唯一默认主界面。
 *  不渲染 Dashboard / PROJECT_STATUS / AutoRun / dogfood / debt 等 Operation 内容。
 *  右侧为 Context/Inspector placeholder（非 Audit Lens）。
 *  所有 Operation / AutoRun / Project management displays: PAUSED。 */
export function WorkbenchLayout() {
  const { exit } = useApp();
  const [focusZone, setFocusZone] = useState<FocusZone>("interaction");
  const [selectedLens] = useState<SelectedLens>(EMPTY_SELECTED_LENS);

  const cycleFocus = useCallback(
    (direction: 1 | -1) => {
      setFocusZone((prev) => {
        const idx = FOCUS_ORDER.indexOf(prev);
        const next =
          (((idx + direction) % FOCUS_ORDER.length) + FOCUS_ORDER.length) %
          FOCUS_ORDER.length;
        return FOCUS_ORDER[next];
      });
    },
    [],
  );

  useInput((input, key) => {
    if (input === "q") {
      exit();
      return;
    }
    if (key.tab) {
      if (key.shift) {
        cycleFocus(-1);
      } else {
        cycleFocus(1);
      }
    }
  });

  const lensLabel = selectedLens.agentId
    ? `Agent: ${selectedLens.agentId}`
    : "none";

  return (
    <Box flexDirection="column">
      {/* 标题 */}
      <Box paddingLeft={1}>
        <Text bold>B8 Interaction-first Workbench</Text>
        <Text dimColor> — M1 (Fixture Data)</Text>
      </Box>

      {/* 三区域 */}
      <Box flexDirection="row" height="80%">
        {/* 左侧 — Agent Selector 25% */}
        <Box width="25%" flexShrink={0}>
          <AgentLensPanel
            nodes={AGENT_LENS_FIXTURE}
            focused={focusZone === "agent-lens"}
            selectedId={selectedLens.agentId}
          />
        </Box>

        {/* 中间 — Interaction View 50% */}
        <Box width="50%" flexShrink={0}>
          <InteractionPanel
            focused={focusZone === "interaction"}
            lensLabel={lensLabel}
          />
        </Box>

        {/* 右侧 — Context / Inspector Placeholder 25% */}
        <Box width="25%" flexShrink={0}>
          <ContextPanel
            focused={focusZone === "context"}
            lensLabel={lensLabel}
          />
        </Box>
      </Box>

      {/* 分隔线 */}
      <Box>
        <Text dimColor>{"─".repeat(80)}</Text>
      </Box>

      {/* 底部输入/状态区域 */}
      <InputBar focused={focusZone === "interaction"} lensLabel={lensLabel} />
      <StatusBar activeLens={lensLabel} focusZone={focusZone} />
    </Box>
  );
}
