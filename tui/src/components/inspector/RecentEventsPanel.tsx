/** Slice A — Recent events summary。Visual Target §3.20 */
import React from "react";
import { Box, Text } from "ink";
import type { RecentEventItem } from "../../data/visualShellTypes";
import { SECTION_HEADER, DIM_TEXT } from "../../theme/visualShellTheme";

interface RecentEventsPanelProps {
  events: RecentEventItem[];
}

export function RecentEventsPanel({ events }: RecentEventsPanelProps) {
  return (
    <Box flexDirection="column">
      <Text {...SECTION_HEADER}>Events</Text>
      {events.length === 0 ? (
        <Text dimColor>—</Text>
      ) : (
        events.slice(0, 5).map((e, i) => (
          <Box key={i}>
            <Text dimColor>
              {e.timestamp}
            </Text>
            <Text dimColor> {e.eventType}</Text>
          </Box>
        ))
      )}
    </Box>
  );
}
