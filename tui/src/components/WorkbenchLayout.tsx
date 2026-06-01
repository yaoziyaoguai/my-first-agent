import React, { useState, useCallback } from "react";
import { Box, Text, useInput, useApp } from "ink";
import type { FocusZone, SelectedLens } from "../types";
import { EMPTY_SELECTED_LENS } from "../types";
import { AGENT_LENS_FIXTURE } from "../data/agentLensFixture";
import { fakeRuntimeSend, makeUserMessage, type RuntimeMessage } from "../data/fakeRuntimeGateway";
import { AgentLensPanel } from "./AgentLensPanel";
import { InteractionPanel } from "./InteractionPanel";
import { ContextPanel } from "./ContextPanel";
import { InputBar } from "./InputBar";
import { StatusBar } from "./StatusBar";

const FOCUS_ORDER: FocusZone[] = ["interaction", "agent-lens", "context"];

/** 从 SelectedLens 构建人类可读 label */
function lensToLabel(lens: SelectedLens): string {
  const parts: string[] = [];
  if (lens.agentId) parts.push(lens.agentId);
  if (lens.sessionId) parts.push(lens.sessionId);
  if (lens.runId) parts.push(lens.runId);
  if (lens.instanceId) parts.push(lens.instanceId);
  return parts.length > 0 ? parts.join(" / ") : "none";
}

/** B8 Interaction-first Workbench — 唯一默认主界面。
 *  M2: selectedLens 驱动, M3: fake/local interaction, M4: Context refresh。
 *  所有 Operation / AutoRun / Project management displays: PAUSED。 */
export function WorkbenchLayout() {
  const { exit } = useApp();
  const [focusZone, setFocusZone] = useState<FocusZone>("interaction");
  const [selectedLens, setSelectedLens] = useState<SelectedLens>(EMPTY_SELECTED_LENS);
  const [messages, setMessages] = useState<RuntimeMessage[]>([]);

  const cycleFocus = useCallback((direction: 1 | -1) => {
    setFocusZone((prev) => {
      const idx = FOCUS_ORDER.indexOf(prev);
      const next =
        (((idx + direction) % FOCUS_ORDER.length) + FOCUS_ORDER.length) %
        FOCUS_ORDER.length;
      return FOCUS_ORDER[next];
    });
  }, []);

  const handleLensSelect = useCallback((lens: SelectedLens) => {
    setSelectedLens(lens);
    // 切换到新的 lens 时清空消息
    setMessages([]);
  }, []);

  const handleSubmit = useCallback(
    (content: string) => {
      if (!selectedLens.agentId) return;
      const userMsg = makeUserMessage(content);
      const assistantMsg = fakeRuntimeSend(content, selectedLens.agentId);
      setMessages((prev) => [...prev, userMsg, assistantMsg]);
    },
    [selectedLens.agentId],
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

  const lensLabel = lensToLabel(selectedLens);
  const hasSelection = selectedLens.agentId !== null;
  const lastMsg = messages.length > 0 ? messages[messages.length - 1] : null;

  return (
    <Box flexDirection="column">
      {/* 标题 */}
      <Box paddingLeft={1}>
        <Text bold>B8 Interaction-first Workbench</Text>
        <Text dimColor> — M2/M3/M4 MVP (fake/local mode)</Text>
      </Box>

      {/* 三区域 */}
      <Box flexDirection="row" height="80%">
        {/* 左侧 — Agent Selector 25% */}
        <Box width="25%" flexShrink={0}>
          <AgentLensPanel
            nodes={AGENT_LENS_FIXTURE}
            focused={focusZone === "agent-lens"}
            selectedLens={selectedLens}
            onSelect={handleLensSelect}
          />
        </Box>

        {/* 中间 — Interaction View 50% */}
        <Box width="50%" flexShrink={0}>
          <InteractionPanel
            focused={focusZone === "interaction"}
            lensLabel={lensLabel}
            messages={messages}
          />
        </Box>

        {/* 右侧 — Context / Inspector Placeholder 25% */}
        <Box width="25%" flexShrink={0}>
          <ContextPanel
            focused={focusZone === "context"}
            lensLabel={lensLabel}
            messageCount={messages.length}
            lastInteractionTime={lastMsg?.timestamp ?? null}
          />
        </Box>
      </Box>

      {/* 分隔线 */}
      <Box>
        <Text dimColor>{"─".repeat(80)}</Text>
      </Box>

      {/* 底部输入/状态区域 */}
      <InputBar
        focused={focusZone === "interaction"}
        lensLabel={lensLabel}
        onSubmit={handleSubmit}
        disabled={!hasSelection}
      />
      <StatusBar activeLens={lensLabel} focusZone={focusZone} />
    </Box>
  );
}
