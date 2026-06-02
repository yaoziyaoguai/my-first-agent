/** Slice A — 全局状态 label 映射。 */
import type { TextProps } from "ink";

export interface StatusChip {
  label: string;
  color: TextProps["color"];
}

export function formatStatusChip(chip: StatusChip): string {
  return `[${chip.label}]`;
}

export function runtimeModeChip(mode: string): StatusChip {
  return { label: mode, color: "cyan" };
}

export function providerChip(
  provider: string,
  isFake: boolean,
): StatusChip {
  return {
    label: isFake ? "fake/local" : provider,
    color: isFake ? "gray" : "green",
  };
}

export function mcpChip(
  status: "ready" | "partial" | "blocked" | "disabled",
): StatusChip {
  const color =
    status === "ready"
      ? "green"
      : status === "partial"
        ? "yellow"
        : status === "blocked"
          ? "red"
          : "gray";
  return { label: `mcp: ${status}`, color };
}
