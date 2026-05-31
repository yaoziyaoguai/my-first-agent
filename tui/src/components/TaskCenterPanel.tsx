import React from "react";
import { Box, Text } from "ink";
import {
  loadTasks,
  groupTasksByStatus,
  formatTaskStatusLabel,
  type TaskCenterItem,
} from "../data/tasks";

function TaskRow({ task }: { task: TaskCenterItem }) {
  const label = formatTaskStatusLabel(task.status);
  const color =
    task.status === "completed"
      ? "green"
      : task.status === "recommended"
        ? "cyan"
        : task.status === "deferred"
          ? "yellow"
          : task.status === "blocked"
            ? "red"
            : "gray";

  return (
    <Box flexDirection="column" marginBottom={1}>
      <Text>
        <Text color={color}>{label}</Text>
        {"  "}
        <Text bold>{task.label}</Text>
      </Text>
      <Text dimColor>  {task.why}</Text>
    </Box>
  );
}

export function TaskCenterPanel() {
  const tasks = loadTasks();
  const groups = groupTasksByStatus(tasks);
  const order: Array<keyof typeof groups> = [
    "recommended",
    "deferred",
    "blocked",
    "completed",
    "not-started",
  ];

  return (
    <Box
      flexDirection="column"
      borderStyle="single"
      borderColor="magenta"
      paddingX={1}
      width="100%"
    >
      <Text bold color="magenta">
        Task Center — B8/B7 Phase Status
      </Text>
      <Text dimColor>{"─".repeat(50)}</Text>
      {order.map((status) => {
        const items = groups[status];
        if (!items || items.length === 0) return null;
        return (
          <Box key={status} flexDirection="column" marginTop={1}>
            {items.map((task) => (
              <TaskRow key={task.phase} task={task} />
            ))}
          </Box>
        );
      })}
    </Box>
  );
}
