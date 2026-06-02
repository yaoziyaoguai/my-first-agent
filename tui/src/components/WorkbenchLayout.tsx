import React, { useState, useCallback } from "react";
import { Box, Text, useInput, useApp } from "ink";
import type { FocusZone, SelectedLens } from "../types";
import { EMPTY_SELECTED_LENS } from "../types";
import { AGENT_LENS_FIXTURE } from "../data/agentLensFixture";
import { fakeRuntimeSend, makeUserMessage, type RuntimeMessage } from "../data/fakeRuntimeGateway";
import {
  generateFakePendingActions,
  createFakeGateway,
  type PendingAction,
} from "../data/pendingAction";
import { AgentLensPanel } from "./AgentLensPanel";
import { InteractionPanel } from "./InteractionPanel";
import { ContextPanel } from "./ContextPanel";
import { InputBar } from "./InputBar";
import { StatusBar } from "./StatusBar";
import { PendingActionPanel } from "./PendingActionPanel";
import { HistoryPanel } from "./HistoryPanel";
import { createFakeHistorySource, type HistorySource } from "../data/agentHistoryIndex";
import { EventPanel } from "./EventPanel";
import {
  createEventStreamReader,
  FAKE_EVENTS_JSONL,
  type EventStreamReader,
} from "../data/eventStreamReader";
import type { InspectorSummary } from "../data/eventSourceContract";

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
  const [pendingActions, setPendingActions] = useState<PendingAction[]>([]);
  const [highlightedPendingIdx, setHighlightedPendingIdx] = useState(0);

  const gateway = React.useMemo(() => createFakeGateway(), []);
  const historySource: HistorySource = React.useMemo(() => createFakeHistorySource(), []);
  const eventReader: EventStreamReader = React.useMemo(() => createEventStreamReader(), []);
  const { events: fixtureEvents, errors: fixtureErrors } = React.useMemo(
    () => eventReader.parse(FAKE_EVENTS_JSONL),
    [eventReader],
  );
  const eventSummary: InspectorSummary | null = React.useMemo(
    () => (fixtureEvents.length > 0 ? eventReader.summarize(fixtureEvents) : null),
    [eventReader, fixtureEvents],
  );

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

      const actions = generateFakePendingActions(selectedLens, content);
      if (actions.length > 0) {
        setPendingActions((prev) => [...prev, ...actions]);
        setFocusZone("interaction");
      }
    },
    [selectedLens],
  );

  const handleApprove = useCallback(
    (actionId: string) => {
      setPendingActions((prev) =>
        prev.map((a) => {
          if (a.actionId !== actionId) return a;
          const result = gateway.approve(a);
          const outcomeMsg: RuntimeMessage = {
            id: `outcome-${result.actionId}`,
            role: "system",
            content: result.outcomeMessage,
            timestamp: result.resolvedAt,
          };
          setMessages((prevMsgs) => [...prevMsgs, outcomeMsg]);
          return { ...a, status: result.status, outcomeMessage: result.outcomeMessage };
        }),
      );
    },
    [gateway],
  );

  const handleReject = useCallback(
    (actionId: string) => {
      setPendingActions((prev) =>
        prev.map((a) => {
          if (a.actionId !== actionId) return a;
          const result = gateway.reject(a);
          const outcomeMsg: RuntimeMessage = {
            id: `outcome-${result.actionId}`,
            role: "system",
            content: result.outcomeMessage,
            timestamp: result.resolvedAt,
          };
          setMessages((prevMsgs) => [...prevMsgs, outcomeMsg]);
          return { ...a, status: result.status, outcomeMessage: result.outcomeMessage };
        }),
      );
    },
    [gateway],
  );

  const pendingCount = pendingActions.filter((a) => a.status === "pending").length;

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
      return;
    }
    if (pendingCount === 0) return;

    if (key.upArrow) {
      setHighlightedPendingIdx((prev) =>
        prev > 0 ? prev - 1 : pendingActions.length - 1,
      );
      return;
    }
    if (key.downArrow) {
      setHighlightedPendingIdx((prev) =>
        prev < pendingActions.length - 1 ? prev + 1 : 0,
      );
      return;
    }
    if (key.return) {
      const action = pendingActions[highlightedPendingIdx];
      if (action && action.status === "pending") {
        handleApprove(action.actionId);
      }
      return;
    }
    if (key.escape) {
      const action = pendingActions[highlightedPendingIdx];
      if (action && action.status === "pending") {
        handleReject(action.actionId);
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
        <Text dimColor> — M2/M3/M4/M5 MVP (fake/local mode)</Text>
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
            pendingCount={pendingCount}
          />
        </Box>
      </Box>

      {/* M5 — PendingActionPanel */}
      <PendingActionPanel
        actions={pendingActions}
        focused={focusZone === "interaction"}
        highlightedIdx={highlightedPendingIdx}
        onApprove={handleApprove}
        onReject={handleReject}
      />

      {/* M6 — HistoryPanel（只读 projection） */}
      {hasSelection && (
        <HistoryPanel
          focused={focusZone === "context"}
          agentId={selectedLens.agentId}
          historySource={historySource}
        />
      )}

      {/* M7 — EventPanel（只读 projection） */}
      {hasSelection && (
        <EventPanel
          focused={focusZone === "context"}
          events={fixtureEvents}
          errorCount={fixtureErrors.length}
          summary={eventSummary}
          hasAgent={hasSelection}
        />
      )}

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
      <StatusBar
        activeLens={lensLabel}
        focusZone={focusZone}
        pendingCount={pendingCount}
      />
    </Box>
  );
}
