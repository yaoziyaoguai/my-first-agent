import React from "react";
import { Box, Text } from "ink";
import type { AuditLogEntry } from "../data/auditLog";

interface Props {
  entries: AuditLogEntry[];
}

export function AuditLogPanel({ entries }: Props) {
  return (
    <Box flexDirection="column" borderStyle="single" borderColor="yellow" padding={1}>
      <Text bold color="yellow">
        Audit Log ({entries.length})
      </Text>

      {entries.length === 0 ? (
        <Box marginTop={1}>
          <Text dimColor>No audit entries yet. Execute a safe command to generate audit records.</Text>
        </Box>
      ) : (
        <Box flexDirection="column" marginTop={1}>
          {entries.slice(-10).reverse().map((entry, i) => {
            const statusColor = entry.exitCode === 0 ? "green" : entry.exitCode === null ? "dim" : "red";
            return (
              <Box key={i} flexDirection="column" marginBottom={0}>
                <Text>
                  <Text dimColor>{entry.timestamp.slice(0, 19)}</Text>
                  {"  "}
                  <Text bold>{entry.commandId}</Text>
                  {"  "}
                  <Text color={statusColor}>
                    {entry.exitCode === null ? "…" : `exit ${entry.exitCode}`}
                  </Text>
                  {"  "}
                  <Text dimColor>({entry.durationMs}ms)</Text>
                  {"  "}
                  <Text dimColor>{entry.confirmation}</Text>
                </Text>
                <Text dimColor>  {entry.shellCommand}</Text>
              </Box>
            );
          })}
          {entries.length > 10 && (
            <Box marginTop={1}>
              <Text dimColor>
                (+{entries.length - 10} more entries — showing last 10)
              </Text>
            </Box>
          )}
        </Box>
      )}
    </Box>
  );
}
