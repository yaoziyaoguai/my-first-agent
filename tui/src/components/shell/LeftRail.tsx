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
}

export function LeftRail({
  width,
  height,
  workspaces,
  viewLenses,
  sessions,
  runtimeStatus,
  fakeLabel,
}: LeftRailProps) {
  return (
    <Box
      width={width}
      height={height}
      flexDirection="column"
      borderStyle="single"
      borderColor="gray"
    >
      <Text dimColor>{fakeLabel}</Text>
      <WorkspacePanel items={workspaces} />
      <Box>
        <Text dimColor>{BORDER_CHARS.h.repeat(width - 4)}</Text>
      </Box>
      <ViewLensPanel lenses={viewLenses} />
      <Box>
        <Text dimColor>{BORDER_CHARS.h.repeat(width - 4)}</Text>
      </Box>
      <SessionPanel data={sessions} />
      <Box>
        <Text dimColor>{BORDER_CHARS.h.repeat(width - 4)}</Text>
      </Box>
      <RuntimeStatusPanel data={runtimeStatus} />
      <Box>
        <Text dimColor>{BORDER_CHARS.h.repeat(width - 4)}</Text>
      </Box>
      <KeysPanel />
    </Box>
  );
}
