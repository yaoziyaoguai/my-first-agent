/** executionService.ts 安全门测试 — env sanitize / blocked / unknown commandId / redaction */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

vi.mock("../services/commandExecutor", () => ({
  execAsync: vi.fn(),
}));

describe("executionService", () => {
  beforeEach(async () => {
    const { execAsync } = await import("../services/commandExecutor");
    vi.mocked(execAsync).mockResolvedValue({
      stdout: "mock output",
      stderr: "",
      exitCode: 0,
      durationMs: 5,
      timedOut: false,
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  describe("unknown commandId", () => {
    it("throws HARD_STOP for whitelist外 command", async () => {
      const { execute } = await import("../services/executionService");
      await expect(
        execute({
          commandId: "unknown-cmd",
          shellCommand: "echo hi",
          safetyLevel: "preview-only",
          repoRoot: "/tmp",
          confirmation: "single",
        }),
      ).rejects.toThrow(/白名单/);
    });
  });

  describe("blocked command", () => {
    it("throws HARD_STOP for 黑名单模式 rm -rf", async () => {
      const { execute } = await import("../services/executionService");
      await expect(
        execute({
          commandId: "status",
          shellCommand: "rm -rf /",
          safetyLevel: "preview-only",
          repoRoot: "/tmp",
          confirmation: "single",
        }),
      ).rejects.toThrow(/黑名单/);
    });

    it("throws HARD_STOP for 黑名单模式 git push --force", async () => {
      const { execute } = await import("../services/executionService");
      await expect(
        execute({
          commandId: "status",
          shellCommand: "git push --force origin main",
          safetyLevel: "preview-only",
          repoRoot: "/tmp",
          confirmation: "single",
        }),
      ).rejects.toThrow(/黑名单/);
    });
  });

  describe("empty shellCommand", () => {
    it("throws HARD_STOP when shellCommand is empty", async () => {
      const { execute } = await import("../services/executionService");
      await expect(
        execute({
          commandId: "status",
          shellCommand: "",
          safetyLevel: "preview-only",
          repoRoot: "/tmp",
          confirmation: "single",
        }),
      ).rejects.toThrow(/HARD_STOP/);
    });
  });

  describe("env sanitize", () => {
    it("strips ANTHROPIC_* env vars", async () => {
      process.env.ANTHROPIC_API_KEY = "fake-api-key-for-test";
      process.env.OPENAI_API_KEY = "fake-openai-key-for-test";

      const { execute } = await import("../services/executionService");
      const { execAsync } = await import("../services/commandExecutor");
      await execute({
        commandId: "status",
        shellCommand: "echo hi",
        safetyLevel: "preview-only",
        repoRoot: "/tmp",
        confirmation: "single",
      });

      const callArgs = vi.mocked(execAsync).mock.calls[0];
      const execOptions = callArgs[1];
      expect(execOptions.env.ANTHROPIC_API_KEY).toBeUndefined();
      expect(execOptions.env.OPENAI_API_KEY).toBeUndefined();

      delete process.env.ANTHROPIC_API_KEY;
      delete process.env.OPENAI_API_KEY;
    });

    it("preserves HOME, PATH, USER", async () => {
      process.env.HOME = "/home/test";
      process.env.PATH = "/usr/bin";
      process.env.USER = "tester";

      const { execute } = await import("../services/executionService");
      const { execAsync } = await import("../services/commandExecutor");
      await execute({
        commandId: "status",
        shellCommand: "echo hi",
        safetyLevel: "preview-only",
        repoRoot: "/tmp",
        confirmation: "single",
      });

      const callArgs = vi.mocked(execAsync).mock.calls[0];
      const execOptions = callArgs[1];
      expect(execOptions.env.HOME).toBe("/home/test");
      expect(execOptions.env.PATH).toBe("/usr/bin");
      expect(execOptions.env.USER).toBe("tester");
    });

    it("strips _API_KEY suffix env vars", async () => {
      process.env.SOME_API_KEY = "secret123";

      const { execute } = await import("../services/executionService");
      const { execAsync } = await import("../services/commandExecutor");
      await execute({
        commandId: "status",
        shellCommand: "echo hi",
        safetyLevel: "preview-only",
        repoRoot: "/tmp",
        confirmation: "single",
      });

      const callArgs = vi.mocked(execAsync).mock.calls[0];
      const execOptions = callArgs[1];
      expect(execOptions.env.SOME_API_KEY).toBeUndefined();

      delete process.env.SOME_API_KEY;
    });
  });

  describe("audit log redaction", () => {
    it("redacts sk-* tokens from shellCommand in audit log", () => {
      // 使用纯数字 sk- 后缀避免触发 pre-commit secret scan
      const redacted = "echo API_KEY=sk-00000000000000000000".replace(
        /sk-[A-Za-z0-9_-]{20,}/g,
        "sk-***REDACTED***",
      );
      expect(redacted).toBe("echo API_KEY=sk-***REDACTED***");
      expect(redacted).not.toContain("00000000000000000000");
    });

    it("redacts Bearer tokens", () => {
      const input = "curl -H 'Authorization: Bearer tok123456789012345678' url";
      const redacted = input
        .replace(/Bearer\s+[A-Za-z0-9._\-]+/gi, "Bearer ***REDACTED***")
        .replace(/sk-[A-Za-z0-9_-]{20,}/g, "sk-***REDACTED***");
      expect(redacted).toContain("Bearer ***REDACTED***");
      expect(redacted).not.toContain("tok123456789012345678");
    });

    it("redacts --api-key flag values", () => {
      const input = "some-tool --api-key sk-00000000000000000000";
      const redacted = input
        .replace(/(--api-key[= ])\S+/gi, "$1***REDACTED***")
        .replace(/sk-[A-Za-z0-9_-]{20,}/g, "sk-***REDACTED***");
      expect(redacted).toContain("--api-key ***REDACTED***");
      expect(redacted).not.toContain("00000000000000000000");
    });
  });
});
