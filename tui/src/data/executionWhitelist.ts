/** Phase 4: 命令白名单/黑名单 */
import type { CommandCatalog, CommandDefinition } from "../types";

/** Phase 4 可执行命令白名单 */
export const ALLOWED_COMMAND_IDS: ReadonlySet<string> = new Set([
  "status",
  "gates",
  "docs-check",
  "autorun",
  "audit",
]);

/** 黑名单模式 (防 destructive/irreversible/sysadmin 命令) */
export const BLOCKED_PATTERNS: readonly string[] = [
  "git push --force",
  "git reset --hard",
  "git branch -D",
  "git branch -d",
  "git clean -f",
  "git clean -fd",
  "rm -rf",
  "rm -r",
  "sudo ",
  "chmod ",
  "chown ",
  "git checkout --",
];

export function isAllowed(commandId: string): boolean {
  return ALLOWED_COMMAND_IDS.has(commandId);
}

export function isBlocked(shellCommand: string): boolean {
  const lower = shellCommand.toLowerCase();
  const dangerous = ["git push --force", "git reset --hard", "git branch -d", "git clean -f", "rm -rf", "rm -r", "sudo ", "chmod ", "chown ", "git checkout --"];
  return dangerous.some((pattern) => lower.includes(pattern));
}

export function getPhase4ExecutableCommands(
  catalog: CommandCatalog,
): CommandDefinition[] {
  return catalog.commands.filter(
    (c) => isAllowed(c.id) && c.shellCommand !== undefined,
  );
}

export function buildShellCommand(cmd: CommandDefinition): string {
  if (!isAllowed(cmd.id)) {
    throw new Error(`HARD_STOP: 命令 "${cmd.id}" 不在 Phase 4 白名单中`);
  }
  const sc = cmd.shellCommand;
  if (!sc) {
    throw new Error(`HARD_STOP: 命令 "${cmd.id}" 无 shellCommand 定义`);
  }
  if (isBlocked(sc)) {
    throw new Error(`HARD_STOP: 命令 "${cmd.id}" 匹配黑名单模式`);
  }
  return sc;
}
