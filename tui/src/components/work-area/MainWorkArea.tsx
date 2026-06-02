/** Slice A — 中间主交互区。Visual Target §3.9 */
import React from "react";
import { Box, Text } from "ink";
import type {
  MessageBlockData,
  ToolCallBlockData,
  PendingActionBlockData,
} from "../../data/visualShellTypes";
import { MessageBlock } from "./MessageBlock";
import { ToolCallBlock } from "./ToolCallBlock";
import { PendingActionBlock } from "./PendingActionBlock";
import { SECTION_HEADER, DIM_TEXT } from "../../theme/visualShellTheme";

interface MainWorkAreaProps {
  width: number;
  messages: MessageBlockData[];
  toolCalls: ToolCallBlockData[];
  pendingActions: PendingActionBlockData[];
  fakeLabel: string;
}

export function MainWorkArea({
  width,
  messages,
  toolCalls,
  pendingActions,
  fakeLabel,
}: MainWorkAreaProps) {
  const isEmpty =
    messages.length === 0 &&
    toolCalls.length === 0 &&
    pendingActions.length === 0;

  return (
    <Box
      flexDirection="column"
      width={width}
      borderStyle="single"
      borderColor="gray"
    >
      <Box>
        <Text {...SECTION_HEADER}>Chat / Work Area</Text>
        {fakeLabel && (
          <Text dimColor>  [{fakeLabel}]</Text>
        )}
      </Box>

      {isEmpty ? (
        <Box marginTop={1}>
          <Text dimColor>— no messages yet</Text>
        </Box>
      ) : (
        <>
          {/* 消息 */}
          {messages.map((m) => (
            <MessageBlock key={m.id} message={m} />
          ))}

          {/* Tool calls */}
          {toolCalls.map((tc) => (
            <ToolCallBlock key={tc.id} toolCall={tc} />
          ))}

          {/* Pending actions */}
          {pendingActions
            .filter((pa) => pa.status === "pending")
            .map((pa) => (
              <PendingActionBlock key={pa.id} action={pa} />
            ))}
        </>
      )}
    </Box>
  );
}
