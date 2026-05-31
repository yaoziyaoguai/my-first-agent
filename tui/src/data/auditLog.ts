/** Phase 4: JSONL audit log — append-only, rotation */
import { existsSync, mkdirSync, appendFileSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { SafetyLevel } from "../types";

export const AUDIT_LOG_MAX_BYTES = 10 * 1024 * 1024; // 10MB

export interface AuditLogEntry {
  timestamp: string;
  commandId: string;
  shellCommand: string;
  safetyLevel: SafetyLevel;
  confirmation: "single" | "double" | "skipped-dry-run";
  exitCode: number | null;
  durationMs: number;
  truncated: boolean;
}

export function getAuditLogPath(dir: string): string {
  return resolve(dir, ".tui_audit_log.jsonl");
}

export function writeAuditEntry(entry: AuditLogEntry, dir: string): void {
  if (!existsSync(dir)) {
    mkdirSync(dir, { recursive: true });
  }
  const logPath = getAuditLogPath(dir);
  const line = JSON.stringify(entry) + "\n";
  appendFileSync(logPath, line, "utf-8");
}

export function readAuditEntries(dir: string): AuditLogEntry[] {
  const logPath = getAuditLogPath(dir);
  if (!existsSync(logPath)) {
    return [];
  }
  try {
    const content = readFileSync(logPath, "utf-8");
    const lines = content.trim().split("\n").filter(Boolean);
    return lines.map((line) => JSON.parse(line) as AuditLogEntry);
  } catch {
    return [];
  }
}
