/** Phase 5: Approved command adapter for Coding Agent dev workflow — provisional dev-only, may be removed.
 *  Fixed templates only, no dynamic construction. AutoRun is NOT a First Agent runtime product feature. */
export const AUTORUN_COMMANDS: Record<string, string> = {
  continue: "cd <repo> && python main.py auto-run --continue",
  status: "cd <repo> && python main.py status",
  audit: "cd <repo> && python main.py audit --readonly",
  gates: "cd <repo> && ruff check . && python -m pytest tests/ -x -q",
};

export const ALLOWED_AUTORUN_ACTIONS = Object.keys(
  AUTORUN_COMMANDS,
) as readonly string[];

export function isFixedTemplate(action: string): boolean {
  return action in AUTORUN_COMMANDS;
}

export function getAutorunCommand(action: string): string {
  if (!isFixedTemplate(action)) {
    throw new Error(
      `HARD_STOP: 未知 AutoRun action "${action}" — 仅固定模板可用`,
    );
  }
  return AUTORUN_COMMANDS[action];
}

export function validateAutorunTemplate(action: string): void {
  if (!isFixedTemplate(action)) {
    throw new Error(
      `HARD_STOP: AutoRun 命令 "${action}" 不在固定模板中，禁止动态构建`,
    );
  }
}
