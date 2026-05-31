import type { CommandCatalog, CommandDefinition, SafetyLevel } from "../types";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const DEFAULT_PATH = resolve(
  dirname(fileURLToPath(import.meta.url)),
  "commands.json",
);

export function loadCommandCatalog(filePath?: string): CommandCatalog {
  try {
    const raw = readFileSync(filePath ?? DEFAULT_PATH, "utf-8");
    return JSON.parse(raw) as CommandCatalog;
  } catch {
    return { version: "0.0.0", commands: [] };
  }
}

export function getExecutableCommands(
  catalog: CommandCatalog,
): CommandDefinition[] {
  return catalog.commands.filter((c) => c.executableInPhase2);
}

export function getCommandById(
  catalog: CommandCatalog,
  id: string,
): CommandDefinition | undefined {
  return catalog.commands.find((c) => c.id === id);
}

export function getCommandsByCategory(
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
