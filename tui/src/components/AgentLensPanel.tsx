import React from "react";
import { Box, Text } from "ink";
import type { AgentLensNode } from "../types";

interface AgentLensPanelProps {
  nodes: AgentLensNode[];
  focused: boolean;
  /** 选中节点 ID (M2) */
  selectedId?: string | null;
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

function AgentLensTreeNode({
  node,
  depth,
  focused,
  selectedId,
}: {
  node: AgentLensNode;
  depth: number;
  focused: boolean;
  selectedId?: string | null;
}) {
  const isSelected = selectedId === node.id;
  const indent = "  ".repeat(depth);
  const symbol = TYPE_SYMBOLS[node.type] || "?";
  const color = STATUS_COLORS[node.status] || "white";
  const prefix = isSelected ? "▶" : " ";

  return (
    <Box flexDirection="column">
      <Box>
        <Text>
          {indent}
          <Text
            bold={isSelected}
            color={focused && isSelected ? "green" : undefined}
          >
            {prefix}{symbol} {node.label}
          </Text>
          {" "}
          <Text color={color} dimColor={node.status === "historical" || node.status === "superseded"}>
            [{node.status}]
          </Text>
        </Text>
      </Box>
      {node.children.map((child) => (
        <AgentLensTreeNode
          key={child.id}
          node={child}
          depth={depth + 1}
          focused={focused}
          selectedId={selectedId}
        />
      ))}
    </Box>
  );
}

/** 左侧 Agent Lens 面板 — M1 skeleton fixture, M2 navigation/selection */
export function AgentLensPanel({
  nodes,
  focused,
  selectedId,
}: AgentLensPanelProps) {
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
      {nodes.map((node) => (
        <AgentLensTreeNode
          key={node.id}
          node={node}
          depth={0}
          focused={focused}
          selectedId={selectedId}
        />
      ))}
      <Box marginTop={1}>
        <Text dimColor>
          {nodes.length} agent(s) — M1 fixture
        </Text>
      </Box>
    </Box>
  );
}
