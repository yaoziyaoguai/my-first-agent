/** Slice A — 顶层 6 区域布局容器。Visual Target §3.1。
 *  现在包含完整的 fake/local 交互闭环（useInput / useApp / 消息状态 / fake response）。 */
import React, { useState, useCallback } from "react";
import { Box, Text, useInput, useApp } from "ink";
import type {
  VisualShellFixture,
  ViewLens,
  MessageBlockData,
  ToolCallBlockData,
  PendingActionBlockData,
} from "../../data/visualShellTypes";
import { TuiTopBar } from "./TuiTopBar";
import { LeftRail } from "./LeftRail";
import { MainWorkArea } from "../work-area/MainWorkArea";
import { InputDock } from "../input/InputDock";
import { ContextInspectorPanel } from "../inspector/ContextInspectorPanel";
import { BottomStatusBar } from "./BottomStatusBar";
import { DIM_TEXT } from "../../theme/visualShellTheme";

type FocusZone = "agent-lens" | "interaction" | "context";
const FOCUS_ORDER: FocusZone[] = ["interaction", "agent-lens", "context"];

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

/** fake/local 响应生成 — 不调用真实 provider */
function generateFakeResponse(userInput: string): MessageBlockData {
  const lower = userInput.toLowerCase();
  let content: string;

  if (lower.includes("config")) {
    content =
      "[fake/local] Config check: looks good! No syntax errors detected in the current config. " +
      "All required fields present. Provider: fake/local. MCP: local smoke (14 tools discovered).";
  } else if (lower.includes("mcp")) {
    content =
      "[fake/local] MCP Summary: local filesystem server running at /tmp/my-first-agent-mcp-smoke. " +
      "14 tools registered. discover: PASS, invoke: PASS (read_file, write_file). " +
      "Close lifecycle: PASS. Transport: stdio.";
  } else if (lower.includes("help")) {
    content =
      "[fake/local] Available: you can type messages here. Tab cycles focus zones. " +
      "q quits. ↑↓ navigates LeftRail. Enter selects or sends. " +
      "Keywords: config, mcp, help. This is a fake/local interactive demo — no real provider connected.";
  } else {
    content =
      `[fake/local] Received: "${userInput}". ` +
      "This is a fake/local response. No real provider, MCP, or tool execution involved. " +
      "Type 'help' for available commands.";
  }

  return {
    id: `msg-${Date.now()}`,
    role: "assistant",
    content,
    timestamp: new Date().toLocaleTimeString("en-US", { hour12: false }),
  };
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
  const { exit } = useApp();

  // ── Interaction State ──
  const [focusZone, setFocusZone] = useState<FocusZone>("interaction");
  const [inputValue, setInputValue] = useState("");
  const [messages, setMessages] = useState<MessageBlockData[]>(fixture.messages);
  const [toolCalls, setToolCalls] = useState<ToolCallBlockData[]>(fixture.toolCalls);
  const [pendingActions, setPendingActions] = useState<PendingActionBlockData[]>(fixture.pendingActions);
  const [selectedLens, setSelectedLens] = useState<ViewLens>("Agent");
  const [selectedWorkspaceIdx, setSelectedWorkspaceIdx] = useState(0);
  const [selectedSessionRunIdx, setSelectedSessionRunIdx] = useState(0);

  const evidenceLens = selectedLens === "Evidence";
  const { leftRailW, mainW, rightInspectorW, compact } = calcColumnWidths(width);

  // ── Focus cycling ──
  const cycleFocus = useCallback((direction: 1 | -1) => {
    setFocusZone((prev) => {
      const idx = FOCUS_ORDER.indexOf(prev);
      const next = (((idx + direction) % FOCUS_ORDER.length) + FOCUS_ORDER.length) % FOCUS_ORDER.length;
      return FOCUS_ORDER[next];
    });
  }, []);

  // ── Input submit ──
  const handleSubmit = useCallback((text: string) => {
    const userMsg: MessageBlockData = {
      id: `msg-${Date.now()}`,
      role: "user",
      content: text,
      timestamp: new Date().toLocaleTimeString("en-US", { hour12: false }),
    };
    const fakeResp = generateFakeResponse(text);
    setMessages((prev) => [...prev, userMsg, fakeResp]);
  }, []);

  // ── Keyboard ──
  useInput((input, key) => {
    // Global: q quit (must not fire on ctrl+q or meta+q)
    if (input === "q" && !key.ctrl && !key.meta && focusZone !== "interaction") {
      exit();
      return;
    }

    // Global: Tab / Shift+Tab cycle focus
    if (key.tab) {
      cycleFocus(key.shift ? -1 : 1);
      return;
    }

    // ── Interaction zone: text input ──
    if (focusZone === "interaction") {
      if (key.return) {
        const trimmed = inputValue.trim();
        if (trimmed.length > 0) {
          handleSubmit(trimmed);
          setInputValue("");
        }
        return;
      }
      if (key.backspace || key.delete) {
        setInputValue((prev) => prev.slice(0, -1));
        return;
      }
      // Printable characters (not control, not meta)
      if (input.length === 1 && !key.ctrl && !key.meta) {
        setInputValue((prev) => prev + input);
      }
      // q in interaction focus quits only if input is empty
      if (input === "q" && inputValue.length === 0) {
        exit();
      }
      return;
    }

    // ── Agent Lens zone: navigation ──
    if (focusZone === "agent-lens") {
      if (key.upArrow) {
        setSelectedSessionRunIdx((prev) => Math.max(0, prev - 1));
        return;
      }
      if (key.downArrow) {
        setSelectedSessionRunIdx((prev) => prev + 1); // bounded by render
        return;
      }
      if (key.return) {
        // "Select" current item — update active context
        return;
      }
      if (input === "q") {
        exit();
      }
      return;
    }

    // ── Context zone: scroll (placeholder) ──
    if (focusZone === "context") {
      if (input === "q") {
        exit();
      }
      return;
    }
  });

  // ── Build workspace items with selection state ──
  const workspacesWithSelection = fixture.workspaces.map((w, i) => ({
    ...w,
    status: i === selectedWorkspaceIdx ? ("active" as const) : w.status === "active" ? ("idle" as const) : w.status,
  }));

  return (
    <Box flexDirection="column" width={width}>
      {/* TopBar — 1 row */}
      <TuiTopBar
        data={{
          ...fixture.topBar,
          lens: selectedLens,
        }}
        width={width}
      />

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
          workspaces={workspacesWithSelection}
          viewLenses={fixture.viewLens.map((l) => ({
            ...l,
            selected: l.lens === selectedLens,
          }))}
          sessions={fixture.sessions}
          runtimeStatus={fixture.runtimeStatus}
          fakeLabel={fixture._label}
          focused={focusZone === "agent-lens"}
          selectedIdx={selectedSessionRunIdx}
        />

        {/* MainWorkArea */}
        <Box width={mainW} flexDirection="column">
          <MainWorkArea
            width={mainW}
            messages={messages}
            toolCalls={toolCalls}
            pendingActions={pendingActions}
            tableResults={fixture.tableResults}
            fakeLabel={fixture._label}
          />

          {/* InputDock — 底部固定 */}
          <InputDock
            width={mainW}
            inputValue={inputValue}
            focused={focusZone === "interaction"}
            isFake={fixture.topBar.isFake}
          />
        </Box>

        {/* RightInspector — compact mode 下可隐藏 */}
        {rightInspectorW > 0 && (
          <ContextInspectorPanel
            width={rightInspectorW}
            height={height - 6}
            data={{
              ...fixture.inspector,
              activeContext: {
                agentId: fixture.sessions.agentId || "agent-001",
                runId:
                  fixture.sessions.sessions[0]?.runs[selectedSessionRunIdx]?.runId ?? "—",
              },
            }}
            evidenceLens={evidenceLens}
            fakeLabel={fixture._label}
          />
        )}
      </Box>

      {/* 分隔线 */}
      <Box width={width} height={1}>
        <Text dimColor>{"─".repeat(width)}</Text>
      </Box>

      {/* BottomStatusBar */}
      <BottomStatusBar
        data={{
          ...fixture.bottomStatus,
          lens: selectedLens,
          toolCount: toolCalls.length,
        }}
        width={width}
        evidenceLens={evidenceLens}
        focusZone={focusZone}
        messageCount={messages.length}
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
