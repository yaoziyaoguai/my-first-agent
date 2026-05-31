import type { CommandDefinition, SafetyLevel } from "../types";

export function buildPreviewLines(cmd: CommandDefinition): string[] {
  const lines: string[] = [
    `Command Preview — ${cmd.name}`,
    `──────────────────────────────────────────────`,
    `Safety:       ${cmd.safetyLevel}`,
    `Phase 2:      ${cmd.executableInPhase2 ? "可执行" : "preview-only（复制到 CLI 手动执行）"}`,
  ];

  if (cmd.riskNote) {
    lines.push(`Risk:         ${cmd.riskNote}`);
  }

  if (cmd.shellCommand) {
    lines.push("");
    lines.push("Shell command:");
    lines.push(`  ${cmd.shellCommand}`);
  }

  lines.push("");
  lines.push("──────────────────────────────────────────────");
  lines.push("⚠  Phase 2 不执行此命令。请复制到终端手动运行。");

  return lines;
}

export function getRiskLabel(level: SafetyLevel): string {
  switch (level) {
    case "preview-only":
      return "低风险 — 只读展示";
    case "requires-confirmation":
      return "中风险 — 需确认执行";
    case "disabled":
    case "future-executable":
      return "高风险或不可用";
    default:
      return "风险未知";
  }
}
