import type { SafetyLevel } from "../types";

export interface SafetyClassification {
  level: SafetyLevel;
  selectable: boolean;
  phase2Executable: boolean;
  label: string;
}

export const SAFETY_LEVELS: SafetyClassification[] = [
  {
    level: "read-only",
    selectable: true,
    phase2Executable: true,
    label: "只读数据展示",
  },
  {
    level: "preview-only",
    selectable: true,
    phase2Executable: false,
    label: "展示命令但不可执行",
  },
  {
    level: "requires-confirmation",
    selectable: true,
    phase2Executable: false,
    label: "需确认后才能执行",
  },
  {
    level: "disabled",
    selectable: false,
    phase2Executable: false,
    label: "Phase 2 不可用",
  },
  {
    level: "future-executable",
    selectable: false,
    phase2Executable: false,
    label: "后续 Phase 支持",
  },
];

export function classifySafetyLevel(level: SafetyLevel): SafetyClassification {
  const found = SAFETY_LEVELS.find((s) => s.level === level);
  if (found) return found;
  return {
    level: "disabled",
    selectable: false,
    phase2Executable: false,
    label: "未知安全级别",
  };
}

export function isSelectable(level: SafetyLevel): boolean {
  return classifySafetyLevel(level).selectable;
}

export function getSafetyColor(level: SafetyLevel): string {
  switch (level) {
    case "read-only":
      return "green";
    case "preview-only":
      return "cyan";
    case "requires-confirmation":
      return "yellow";
    case "disabled":
    case "future-executable":
      return "dim";
    default:
      return "white";
  }
}

export function getPhase2BehaviorLabel(level: SafetyLevel): string {
  switch (level) {
    case "read-only":
      return "直接展示";
    case "preview-only":
      return "preview — 仅展示命令文本";
    case "requires-confirmation":
      return "preview — 需 confirm 不可执行";
    case "disabled":
      return "Phase 2 不可用";
    case "future-executable":
      return "计划 Phase 3+";
    default:
      return "未知";
  }
}
