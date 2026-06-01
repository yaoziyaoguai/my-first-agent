/** Phase 4: execution service — safety gate + env sanitize + audit log */
import type { SafetyLevel } from "../types";
import type { ExecutionResult } from "../data/commandResult";
import { parseExecResult, createTimeoutResult } from "../data/commandResult";
import { isAllowed, isBlocked } from "../data/executionWhitelist";
import { EXECUTION_TIMEOUT_MS } from "../data/executionGate";
import { writeAuditEntry, type AuditLogEntry } from "../data/auditLog";
import { execAsync, type ExecOptions } from "./commandExecutor";

/** 需从执行环境中清除的敏感环境变量模式 */
const SECRET_ENV_PATTERNS: readonly RegExp[] = [
  /^ANTHROPIC_/i,
  /^OPENAI_/i,
  /^MY_FIRST_AGENT_(LLM_|API_|TOKEN|SECRET|KEY)/i,
  /_API_KEY$/i,
  /_TOKEN$/i,
  /_SECRET$/i,
  /^DASHSCOPE_/i,
  /^DEEPSEEK_/i,
  /^MOONSHOT_/i,
  /^ZHIPU_/i,
  /^GOOGLE_AI_/i,
  /^AWS_ACCESS_KEY/i,
  /^AWS_SECRET/i,
];

/** 保留的非敏感环境变量（TUI 执行需要） */
const KEPT_ENV_VARS: ReadonlySet<string> = new Set([
  "HOME",
  "PATH",
  "USER",
  "SHELL",
  "PWD",
  "LANG",
  "LC_ALL",
  "TERM",
  "NODE_ENV",
  "VIRTUAL_ENV",
  "CONDA_PREFIX",
]);

function sanitizeEnv(): Record<string, string> {
  const clean: Record<string, string> = {};

  for (const [key, value] of Object.entries(process.env)) {
    if (value === undefined) continue;

    // 保留白名单
    if (KEPT_ENV_VARS.has(key)) {
      clean[key] = value;
      continue;
    }

    // 移除敏感变量
    if (SECRET_ENV_PATTERNS.some((p) => p.test(key))) {
      continue;
    }

    // 通过其他变量
    clean[key] = value;
  }

  return clean;
}

/** 脱敏 audit log entry 中的 shellCommand */
function redactShellCommand(shellCommand: string): string {
  // 移除 API key token pattern: sk-*, Bearer *, --api-key=*, KEY=*
  return shellCommand
    .replace(/sk-[A-Za-z0-9_-]{20,}/g, "sk-***REDACTED***")
    .replace(/Bearer\s+[A-Za-z0-9._\-]+/gi, "Bearer ***REDACTED***")
    .replace(/(--api-key[= ])\S+/gi, "$1***REDACTED***")
    .replace(/([A-Z_]*API_KEY[= ])\S+/gi, "$1***REDACTED***")
    .replace(/([A-Z_]*TOKEN[= ])\S+/gi, "$1***REDACTED***");
}

export interface ExecuteOptions {
  commandId: string;
  shellCommand: string;
  safetyLevel: SafetyLevel;
  repoRoot: string;
  confirmation: AuditLogEntry["confirmation"];
}

export async function execute(options: ExecuteOptions): Promise<ExecutionResult> {
  const { commandId, shellCommand, safetyLevel, repoRoot, confirmation } = options;

  // Safety gate
  if (!isAllowed(commandId)) {
    throw new Error(`HARD_STOP: "${commandId}" 不在 Phase 4 白名单中`);
  }
  if (isBlocked(shellCommand)) {
    throw new Error(`HARD_STOP: "${commandId}" 匹配黑名单模式`);
  }
  if (!shellCommand) {
    throw new Error(`HARD_STOP: "${commandId}" 无 shellCommand`);
  }

  const cleanEnv = sanitizeEnv();
  const execOptions: ExecOptions = {
    cwd: repoRoot,
    timeoutMs: EXECUTION_TIMEOUT_MS,
    maxBufferBytes: 10 * 1024 * 1024, // 10MB
    env: cleanEnv,
  };

  const execResult = await execAsync(shellCommand, execOptions);

  const result: ExecutionResult = execResult.timedOut
    ? createTimeoutResult(commandId, shellCommand, safetyLevel)
    : parseExecResult(
        commandId,
        shellCommand,
        safetyLevel,
        execResult.exitCode,
        execResult.stdout,
        execResult.stderr,
        execResult.durationMs,
      );

  // Audit log — 脱敏 shellCommand 后才写入
  writeAuditEntry(
    {
      timestamp: new Date().toISOString(),
      commandId,
      shellCommand: redactShellCommand(shellCommand),
      safetyLevel,
      confirmation,
      exitCode: execResult.exitCode,
      durationMs: execResult.durationMs,
      truncated: result.truncated,
    },
    repoRoot,
  );

  return result;
}
