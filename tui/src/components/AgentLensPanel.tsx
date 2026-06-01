import React, { useState, useMemo, useCallback } from "react";
import { Box, Text, useInput } from "ink";
import type { AgentLensNode, SelectedLens } from "../types";
import { EMPTY_SELECTED_LENS } from "../types";

interface AgentLensPanelProps {
  nodes: AgentLensNode[];
  focused: boolean;
  selectedLens: SelectedLens;
  onSelect: (lens: SelectedLens) => void;
}

interface FlatNode {
  id: string;
  type: AgentLensNode["type"];
  label: string;
  status: AgentLensNode["status"];
  depth: number;
}

const STATUS_COLORS: Record<string, string> = {
  active: "green",
  paused: "yellow",
  completed: "blue",
  failed: "red",
  historical: "grey",
  superseded: "grey",
};

const TYPE_SYMBOLS: Record<string, string> = {
  agent: "@",
  session: "#",
  run: "▶",
  instance: "●",
};

function flattenTree(
  nodes: AgentLensNode[],
  depth: number = 0,
): FlatNode[] {
  const result: FlatNode[] = [];
  for (const node of nodes) {
    result.push({
      id: node.id,
      type: node.type,
      label: node.label,
      status: node.status,
      depth,
    });
    if (node.children.length > 0) {
      result.push(...flattenTree(node.children, depth + 1));
    }
  }
  return result;
}

function selectedIdFromLens(lens: SelectedLens): string | null {
  return lens.instanceId ?? lens.runId ?? lens.sessionId ?? lens.agentId;
}

/** 左侧 Agent Lens 面板 — M2: keyboard navigation + selection */
export function AgentLensPanel({
  nodes,
  focused,
  selectedLens,
  onSelect,
}: AgentLensPanelProps) {
  const [highlightedIdx, setHighlightedIdx] = useState(0);
  const flat = useMemo(() => flattenTree(nodes), [nodes]);
  const selectedId = selectedIdFromLens(selectedLens);

  useInput(
    (input, key) => {
      if (!focused) return;
      if (key.upArrow) {
        setHighlightedIdx((prev) => Math.max(0, prev - 1));
      }
      if (key.downArrow) {
        setHighlightedIdx((prev) => Math.min(flat.length - 1, prev + 1));
      }
      if (key.return && flat.length > 0) {
        const node = flat[highlightedIdx];
        // 选中该节点对应层级最深的 lens
        const newLens = buildLensFromNode(node, flat);
        onSelect(newLens);
      }
    },
    { isActive: focused },
  );

  if (nodes.length === 0) {
    return (
      <Box flexDirection="column" borderStyle="single" paddingLeft={1} paddingRight={1}>
        <Text bold>Agent Lens</Text>
        <Text dimColor>No agents available</Text>
      </Box>
    );
  }

  return (
    <Box flexDirection="column" borderStyle="single" paddingLeft={1} paddingRight={1}>
      <Box marginBottom={1}>
        <Text bold color={focused ? "green" : undefined}>
          {focused ? "◆" : "─"} Agent Lens
        </Text>
      </Box>
      {flat.map((node, idx) => {
        const isHighlighted = focused && idx === highlightedIdx;
        const isSelected = selectedId === node.id;
        const indent = "  ".repeat(node.depth);
        const symbol = TYPE_SYMBOLS[node.type] || "?";
        const color = STATUS_COLORS[node.status] || "white";

        return (
          <Box key={node.id}>
            <Text>
              {indent}
              <Text
                bold={isSelected}
                color={isHighlighted ? "green" : isSelected ? "blue" : undefined}
                inverse={isHighlighted}
              >
                {isHighlighted ? "▶" : " "}{symbol} {node.label}
              </Text>
              {" "}
              <Text
                color={color}
                dimColor={node.status === "historical" || node.status === "superseded"}
              >
                [{node.status}]
              </Text>
            </Text>
          </Box>
        );
      })}
      <Box marginTop={1}>
        <Text dimColor>
          {flat.length} nodes, {nodes.length} agent(s) — ↑↓ navigate, Enter select
        </Text>
      </Box>
    </Box>
  );
}

/** 根据 flat node 构建 SelectedLens */
function buildLensFromNode(
  node: FlatNode,
  flat: FlatNode[],
): SelectedLens {
  const lens = { ...EMPTY_SELECTED_LENS };
  const nodeIdx = flat.indexOf(node);

  // 向上查找 parent nodes 补全 lens 层级
  for (let i = nodeIdx - 1; i >= 0; i--) {
    const anc = flat[i];
    if (anc.depth === 0 && !lens.agentId) {
      lens.agentId = anc.id;
    }
    if (anc.depth === 1 && anc.depth < node.depth && !lens.sessionId) {
      lens.sessionId = anc.id;
    }
    if (anc.depth === 2 && anc.depth < node.depth && !lens.runId) {
      lens.runId = anc.id;
    }
  }

  // 对当前节点本身
  switch (node.type) {
    case "agent":
      lens.agentId = node.id;
      break;
    case "session":
      if (!lens.sessionId) lens.sessionId = node.id;
      break;
    case "run":
      if (!lens.runId) lens.runId = node.id;
      break;
    case "instance":
      lens.instanceId = node.id;
      break;
  }

  return lens;
}
