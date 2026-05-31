import type { CommandCatalog, CommandDefinition } from "../types";
import { isSelectable } from "./safetyModel";

export function formatCommandRow(
  cmd: CommandDefinition,
  isSelected: boolean,
): string {
  const prefix = isSelected ? "▶" : " ";
  const selectable = isSelectable(cmd.safetyLevel);
  const name = selectable ? cmd.name : `${cmd.name} [不可选]`;
  const safety = `[${cmd.safetyLevel}]`;
  return `${prefix} ${name.padEnd(22)} ${safety}`;
}

export function buildGroupedCommands(
  catalog: CommandCatalog,
): Map<string, CommandDefinition[]> {
  const groups = new Map<string, CommandDefinition[]>();
  for (const cmd of catalog.commands) {
    const existing = groups.get(cmd.category) ?? [];
    existing.push(cmd);
    groups.set(cmd.category, existing);
  }
  return groups;
}
