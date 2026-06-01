/** commandExecutor.ts async 执行测试 — mock child_process.exec */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { execAsync, type ExecResult } from "../services/commandExecutor";

const MOCK_OPTIONS = {
  cwd: "/tmp/test",
  timeoutMs: 5000,
  maxBufferBytes: 1024 * 1024,
  env: { HOME: "/tmp" },
};

describe("execAsync", () => {
  beforeEach(() => {
    vi.mock("node:child_process", () => ({
      exec: vi.fn(),
    }));
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("returns ExecResult with exitCode 0 on success", async () => {
    const { exec } = await import("node:child_process");
    const mockChild = {
      on: vi.fn(),
      kill: vi.fn(),
      stdout: null as unknown,
      stderr: null as unknown,
    };
    (exec as unknown as ReturnType<typeof vi.fn>).mockImplementation(
      (_cmd: string, _opts: unknown, callback: (error: null, stdout: string, stderr: string) => void) => {
        callback(null, "hello world", "");
        return mockChild;
      },
    );

    const result = await execAsync("echo hello", MOCK_OPTIONS);

    expect(result.exitCode).toBe(0);
    expect(result.stdout).toBe("hello world");
    expect(result.stderr).toBe("");
    expect(result.timedOut).toBe(false);
    expect(result.durationMs).toBeGreaterThanOrEqual(0);
  });

  it("returns non-zero exitCode and stderr on error", async () => {
    const { exec } = await import("node:child_process");
    const mockChild = {
      on: vi.fn(),
      kill: vi.fn(),
    };
    const execErr = Object.assign(new Error("command failed"), {
      code: "ERR_UNKNOWN",
      status: 1,
      stdout: "partial output",
      stderr: "error message",
    });
    (exec as unknown as ReturnType<typeof vi.fn>).mockImplementation(
      (_cmd: string, _opts: unknown, callback: (error: Error & { status?: number; stdout?: string; stderr?: string }, stdout: string, stderr: string) => void) => {
        callback(execErr, execErr.stdout!, execErr.stderr!);
        return mockChild;
      },
    );

    const result = await execAsync("bad command", MOCK_OPTIONS);

    expect(result.exitCode).toBe(1);
    expect(result.stderr).toBe("error message");
    expect(result.timedOut).toBe(false);
  });

  it("returns timedOut=true when ETIMEDOUT", async () => {
    const { exec } = await import("node:child_process");
    const mockChild = {
      on: vi.fn(),
      kill: vi.fn(),
    };
    const execErr = Object.assign(new Error("timed out"), {
      code: "ETIMEDOUT",
      stdout: "",
      stderr: "",
    });
    (exec as unknown as ReturnType<typeof vi.fn>).mockImplementation(
      (_cmd: string, _opts: unknown, callback: (error: Error & { code?: string }, stdout: string, stderr: string) => void) => {
        callback(execErr, "", "");
        return mockChild;
      },
    );

    const result = await execAsync("slow command", MOCK_OPTIONS);

    expect(result.timedOut).toBe(true);
    expect(result.exitCode).toBeNull();
  });

  it("clears timeout on close event", async () => {
    const { exec } = await import("node:child_process");
    const onHandlers: Record<string, () => void> = {};
    const mockChild = {
      on: vi.fn((event: string, handler: () => void) => {
        onHandlers[event] = handler;
      }),
      kill: vi.fn(),
    };
    (exec as unknown as ReturnType<typeof vi.fn>).mockImplementation(
      (_cmd: string, _opts: unknown, callback: (error: null, stdout: string, stderr: string) => void) => {
        // 同步回调 — 模拟快速命令
        callback(null, "ok", "");
        return mockChild;
      },
    );

    const result = await execAsync("echo ok", MOCK_OPTIONS);
    expect(result.exitCode).toBe(0);
    // close handler 应被注册但回调已完成
    expect(mockChild.on).toHaveBeenCalledWith("close", expect.any(Function));
  });
});
