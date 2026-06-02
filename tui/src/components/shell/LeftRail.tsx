/** Slice A — Left Rail container. Visual Target §3.3 */
import React from "react";
import { Box, Text } from "ink";
import type {
  WorkspaceItem,
  ViewLensItem,
  SessionItem,
  RuntimeStatusData,
} from "../../data/visualShellTypes";
import { WorkspacePanel } from "../left-rail/WorkspacePanel";
import { ViewLensPanel } from "../left-rail/ViewLensPanel";
import { SessionPanel } from "../left-rail/SessionPanel";
import { RuntimeStatusPanel } from "../left-rail/RuntimeStatusPanel";
import { KeysPanel } from "../left-rail/KeysPanel";
import { BORDER_CHARS, DIM_TEXT } from "../../theme/visualShellTheme";

interface LeftRailProps {
  width: number;
  height: number;
  workspaces: WorkspaceItem[];
  viewLenses: ViewLensItem[];
  sessions: SessionItem;
  runtimeStatus: RuntimeStatusData;
  fakeLabel: string;
  focused?: boolean;
  selectedIdx?: number;
}

export function LeftRail({
  width,
  height,
  workspaces,
  viewLenses,
  sessions,
  runtimeStatus,
  fakeLabel,
  focused = false,
  selectedIdx = 0,
}: LeftRailProps) {
  return (
    <Box
      width={width}
      height={height}
      flexDirection="column"
      borderStyle="single"
      borderColor={focused ? "green" : "gray"}
    >
      <Box>
        <Text dimColor>{fakeLabel}</Text>
        {focused && <Text color="green" bold> ◉</Text>}
      </Box>
      <WorkspacePanel items={workspaces} />
      <Box>
        <Text dimColor>{BORDER_CHARS.h.repeat(width - 4)}</Text>
      </Box>
      <ViewLensPanel lenses={viewLenses} />
      <Box>
        <Text dimColor>{BORDER_CHARS.h.repeat(width - 4)}</Text>
      </Box>
      <SessionPanel data={sessions} focused={focused} selectedIdx={selectedIdx} />
      <Box>
        <Text dimColor>{BORDER_CHARS.h.repeat(width - 4)}</Text>
      </Box>
      <RuntimeStatusPanel data={runtimeStatus} />
      <Box>
        <Text dimColor>{BORDER_CHARS.h.repeat(width - 4)}</Text>
      </Box>
      <KeysPanel focused={focused} />
    </Box>
  );
}
