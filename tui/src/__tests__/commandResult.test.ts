/** commandResult.ts 纯函数测试 — parseExecResult / createTimeoutResult / truncation */
import { describe, it, expect } from "vitest";
import { parseExecResult, createTimeoutResult } from "../data/commandResult";
import type { ExecutionResult } from "../data/commandResult";

const CMD = "test-cmd";
const SHELL = "echo hello";
const SAFETY = "preview-only" as const;

describe("parseExecResult", () => {
  it("returns ExecutionResult with all fields", () => {
    const r = parseExecResult(CMD, SHELL, SAFETY, 0, "hello", "", 42);
    expect(r.commandId).toBe(CMD);
    expect(r.shellCommand).toBe(SHELL);
    expect(r.safetyLevel).toBe(SAFETY);
    expect(r.exitCode).toBe(0);
    expect(r.stdout).toBe("hello");
    expect(r.stderr).toBe("");
    expect(r.durationMs).toBe(42);
    expect(r.truncated).toBe(false);
    expect(r.timedOut).toBe(false);
  });

  it("truncates stdout exceeding MAX_OUTPUT (50KB)", () => {
    const big = "x".repeat(60_000);
    const r = parseExecResult(CMD, SHELL, SAFETY, 0, big, "", 0);
    expect(r.truncated).toBe(true);
    expect(r.stdout).toContain("[truncated]");
    expect(r.stdout.length).toBeLessThan(51_000);
  });

  it("truncates stderr exceeding MAX_OUTPUT (50KB)", () => {
    const big = "x".repeat(60_000);
    const r = parseExecResult(CMD, SHELL, SAFETY, 1, "", big, 0);
    expect(r.truncated).toBe(true);
    expect(r.stderr).toContain("[truncated]");
  });

  it("does not truncate short output", () => {
    const r = parseExecResult(CMD, SHELL, SAFETY, 0, "ok", "", 0);
    expect(r.truncated).toBe(false);
    expect(r.stdout).toBe("ok");
  });

  it("passes through non-zero exitCode", () => {
    const r = parseExecResult(CMD, SHELL, SAFETY, 127, "", "not found", 10);
    expect(r.exitCode).toBe(127);
    expect(r.stderr).toBe("not found");
  });
});

describe("createTimeoutResult", () => {
  it("returns timedOut=true with stderr message", () => {
    const r = createTimeoutResult(CMD, SHELL, SAFETY);
    expect(r.timedOut).toBe(true);
    expect(r.exitCode).toBeNull();
    expect(r.stderr).toContain("timed out");
    expect(r.stdout).toBe("");
    expect(r.truncated).toBe(false);
  });

  it("preserves command metadata", () => {
    const r = createTimeoutResult(CMD, SHELL, "requires-confirmation");
    expect(r.commandId).toBe(CMD);
    expect(r.shellCommand).toBe(SHELL);
  });
});
