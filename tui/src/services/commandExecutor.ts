/** Phase 4: async command executor — 不阻塞 Ink render loop */
import { exec } from "node:child_process";

export interface ExecOptions {
  cwd: string;
  timeoutMs: number;
  maxBufferBytes: number;
  env: Record<string, string>;
}

export interface ExecResult {
  stdout: string;
  stderr: string;
  exitCode: number | null;
  durationMs: number;
  timedOut: boolean;
}

export function execAsync(
  command: string,
  options: ExecOptions,
): Promise<ExecResult> {
  const start = Date.now();

  return new Promise((resolve) => {
    const child = exec(
      command,
      {
        cwd: options.cwd,
        timeout: options.timeoutMs,
        maxBuffer: options.maxBufferBytes,
        env: options.env,
        windowsHide: true,
      },
      (error, stdout, stderr) => {
        const durationMs = Date.now() - start;

        if (error) {
          const timedOut = (error as NodeJS.ErrnoException).code === "ETIMEDOUT";
          resolve({
            stdout: stdout ?? "",
            stderr: stderr ?? (timedOut ? "Execution timed out" : (error.message ?? "")),
            exitCode: typeof (error as { status?: number }).status === "number"
              ? (error as { status?: number }).status!
              : null,
            durationMs,
            timedOut,
          });
          return;
        }

        resolve({
          stdout: stdout ?? "",
          stderr: stderr ?? "",
          exitCode: 0,
          durationMs,
          timedOut: false,
        });
      },
    );

    // 超时 kill — child_process 的 timeout 选项会触发 SIGTERM，但不会清理子进程的子进程
    const timer = setTimeout(() => {
      child.kill("SIGTERM");
      // Fallback: 1s 后 SIGKILL
      setTimeout(() => {
        try { child.kill("SIGKILL"); } catch { /* 已死 */ }
      }, 1000);
    }, options.timeoutMs);

    child.on("close", () => clearTimeout(timer));
    child.on("exit", () => clearTimeout(timer));
  });
}
