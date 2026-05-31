import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { existsSync, mkdirSync, readFileSync, rmSync } from "node:fs";
import { resolve } from "node:path";
import {
  writeAuditEntry,
  readAuditEntries,
  getAuditLogPath,
  AUDIT_LOG_MAX_BYTES,
  type AuditLogEntry,
} from "../data/auditLog";

const TEST_DIR = resolve(__dirname, "../../.tmp_audit_test");

function cleanup() {
  if (existsSync(TEST_DIR)) {
    rmSync(TEST_DIR, { recursive: true, force: true });
  }
}

function makeEntry(overrides: Partial<AuditLogEntry> = {}): AuditLogEntry {
  return {
    timestamp: new Date().toISOString(),
    commandId: "status",
    shellCommand: "python main.py status",
    safetyLevel: "preview-only",
    confirmation: "single",
    exitCode: 0,
    durationMs: 1200,
    truncated: false,
    ...overrides,
  };
}

describe("auditLog", () => {
  beforeEach(() => {
    cleanup();
    mkdirSync(TEST_DIR, { recursive: true });
  });

  afterEach(() => {
    cleanup();
  });

  describe("getAuditLogPath", () => {
    it("returns a path ending in .tui_audit_log.jsonl", () => {
      const p = getAuditLogPath(TEST_DIR);
      expect(p.endsWith(".tui_audit_log.jsonl")).toBe(true);
    });

    it("returns a path inside the provided directory", () => {
      const p = getAuditLogPath(TEST_DIR);
      expect(p.startsWith(TEST_DIR)).toBe(true);
    });
  });

  describe("writeAuditEntry", () => {
    it("writes a JSONL line to the audit log", () => {
      const entry = makeEntry();
      writeAuditEntry(entry, TEST_DIR);

      const logPath = getAuditLogPath(TEST_DIR);
      expect(existsSync(logPath)).toBe(true);

      const content = readFileSync(logPath, "utf-8");
      const lines = content.trim().split("\n");
      expect(lines.length).toBe(1);

      const parsed = JSON.parse(lines[0]);
      expect(parsed.commandId).toBe("status");
      expect(parsed.shellCommand).toBe("python main.py status");
      expect(parsed.safetyLevel).toBe("preview-only");
      expect(parsed.exitCode).toBe(0);
      expect(parsed.durationMs).toBe(1200);
    });

    it("appends multiple entries", () => {
      writeAuditEntry(makeEntry({ commandId: "status" }), TEST_DIR);
      writeAuditEntry(makeEntry({ commandId: "gates" }), TEST_DIR);
      writeAuditEntry(makeEntry({ commandId: "autorun" }), TEST_DIR);

      const logPath = getAuditLogPath(TEST_DIR);
      const content = readFileSync(logPath, "utf-8");
      const lines = content.trim().split("\n");
      expect(lines.length).toBe(3);

      const ids = lines.map((l) => JSON.parse(l).commandId);
      expect(ids).toEqual(["status", "gates", "autorun"]);
    });

    it("records all required fields", () => {
      const entry = makeEntry({
        timestamp: "2026-06-01T00:00:00.000Z",
        commandId: "gates",
        shellCommand: "ruff check . && python -m pytest tests/ -x -q",
        safetyLevel: "preview-only",
        confirmation: "single",
        exitCode: 0,
        durationMs: 5000,
        truncated: true,
      });
      writeAuditEntry(entry, TEST_DIR);

      const entries = readAuditEntries(TEST_DIR);
      expect(entries.length).toBe(1);
      const e = entries[0];
      expect(e.timestamp).toBe("2026-06-01T00:00:00.000Z");
      expect(e.commandId).toBe("gates");
      expect(e.shellCommand).toBe("ruff check . && python -m pytest tests/ -x -q");
      expect(e.safetyLevel).toBe("preview-only");
      expect(e.confirmation).toBe("single");
      expect(e.exitCode).toBe(0);
      expect(e.durationMs).toBe(5000);
      expect(e.truncated).toBe(true);
    });
  });

  describe("readAuditEntries", () => {
    it("returns empty array for non-existent log", () => {
      const entries = readAuditEntries(TEST_DIR);
      expect(entries).toEqual([]);
    });

    it("reads all entries in order", () => {
      writeAuditEntry(makeEntry({ commandId: "first" }), TEST_DIR);
      writeAuditEntry(makeEntry({ commandId: "second" }), TEST_DIR);

      const entries = readAuditEntries(TEST_DIR);
      expect(entries.length).toBe(2);
      expect(entries[0].commandId).toBe("first");
      expect(entries[1].commandId).toBe("second");
    });
  });

  describe("AUDIT_LOG_MAX_BYTES", () => {
    it("is defined and positive", () => {
      expect(AUDIT_LOG_MAX_BYTES).toBeGreaterThan(0);
    });

    it("is 10MB", () => {
      expect(AUDIT_LOG_MAX_BYTES).toBe(10 * 1024 * 1024);
    });
  });

  describe("entry immutability", () => {
    it("readAuditEntries returns new objects", () => {
      writeAuditEntry(makeEntry({ commandId: "original" }), TEST_DIR);
      const entries1 = readAuditEntries(TEST_DIR);
      const entries2 = readAuditEntries(TEST_DIR);
      expect(entries1).not.toBe(entries2);
      expect(entries1[0]).not.toBe(entries2[0]);
    });

    it("writeAuditEntry does not modify the original entry", () => {
      const entry = makeEntry({ commandId: "immutable" });
      const original = { ...entry };
      writeAuditEntry(entry, TEST_DIR);
      expect(entry).toEqual(original);
    });
  });
});
