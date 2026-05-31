/** AutoRun 任务中心数据模型 */

import tasksJson from "./tasks.json";

export type TaskStatus =
  | "recommended"
  | "deferred"
  | "blocked"
  | "completed"
  | "not-started";

export interface TaskCenterItem {
  phase: string;
  label: string;
  status: TaskStatus;
  why: string;
}

interface TasksConfig {
  version: string;
  tasks: TaskCenterItem[];
}

export function loadTasks(): TaskCenterItem[] {
  const config = tasksJson as TasksConfig;
  return config.tasks;
}

export function getTasksByStatus(
  tasks: TaskCenterItem[],
  status: TaskStatus,
): TaskCenterItem[] {
  return tasks.filter((t) => t.status === status);
}

export function formatTaskStatusLabel(status: TaskStatus): string {
  const labels: Record<TaskStatus, string> = {
    recommended: "▶ recommended (current)",
    deferred: "⏸ deferred",
    blocked: "✗ blocked",
    completed: "✓ completed",
    "not-started": "○ not-started",
  };
  return labels[status];
}

export function groupTasksByStatus(
  tasks: TaskCenterItem[],
): Record<string, TaskCenterItem[]> {
  const groups: Record<string, TaskCenterItem[]> = {};
  for (const task of tasks) {
    if (!groups[task.status]) {
      groups[task.status] = [];
    }
    groups[task.status].push(task);
  }
  return groups;
}
