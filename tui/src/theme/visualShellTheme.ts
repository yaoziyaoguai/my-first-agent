/** Slice A — ANSI color token mappings for Ink. */
import type { TextProps } from "ink";

export const ANSI_COLORS = {
  text: "white" as const,
  dim: "gray" as const,
  accent: "cyan" as const,
  success: "green" as const,
  warning: "yellow" as const,
  error: "red" as const,
  info: "blue" as const,
  highlight: "magenta" as const,
};

export const SECTION_HEADER: TextProps = { bold: true, color: "white" };
export const BODY_TEXT: TextProps = { color: "white" };
export const DIM_TEXT: TextProps = { dimColor: true };
export const ACCENT_TEXT: TextProps = { color: "cyan" };
export const SUCCESS_TEXT: TextProps = { color: "green" };
export const WARNING_TEXT: TextProps = { color: "yellow" };
export const ERROR_TEXT: TextProps = { color: "red" };
export const INFO_TEXT: TextProps = { color: "blue" };
export const HIGHLIGHT_TEXT: TextProps = { color: "magenta" };

export const BORDER_CHARS = {
  h: "─",
  v: "│",
  tl: "┌",
  tr: "┐",
  bl: "└",
  br: "┘",
  teeL: "├",
  teeR: "┤",
} as const;

/** 状态颜色映射 */
export function statusColor(
  status: string,
): TextProps["color"] {
  switch (status.toLowerCase()) {
    case "ready":
    case "pass":
    case "healthy":
    case "done":
    case "active":
      return "green";
    case "partial":
    case "pending":
    case "caveat":
      return "yellow";
    case "fail":
    case "blocked":
    case "unsafe":
      return "red";
    case "running":
      return "green";
    case "paused":
    case "historical":
      return "gray";
    default:
      return undefined;
  }
}

/** 状态 dot 符号 */
export function statusDot(status: string): string {
  switch (status.toLowerCase()) {
    case "active":
      return "●";
    case "running":
      return "◉";
    case "paused":
      return "◌";
    case "done":
    case "completed":
      return "✓";
    case "failed":
      return "✗";
    case "historical":
      return "—";
    default:
      return "—";
  }
}
