/** Phase 6A: Gate History model — 从 progress ledger/status 解析 gate 结果 */
export interface GateResult {
  name: string;
  status: string;
  source: string;
  lastUpdated: string;
}

const KNOWN_GATES = [
  "vitest",
  "pytest",
  "tsc",
  "ruff",
  "pre-commit",
  "git diff --check",
];

const GATE_KEYWORDS: Record<string, string[]> = {
  vitest: ["vitest", "tests pass", "tests PASS"],
  pytest: ["pytest"],
  tsc: ["tsc", "typecheck", "TypeScript 编译", "noEmit clean"],
  ruff: ["ruff"],
  "pre-commit": ["pre-commit", "Pre-commit"],
  "git diff --check": ["git diff --check", "diff --check"],
};

export function parseGateHistory(text: string): GateResult[] {
  if (!text.trim()) {
    return KNOWN_GATES.map((name) => ({
      name,
      status: "unknown",
      source: "none",
      lastUpdated: "",
    }));
  }

  return KNOWN_GATES.map((name) => {
    const keywords = GATE_KEYWORDS[name] ?? [name];
    const matched = keywords.some((kw) =>
      text.toLowerCase().includes(kw.toLowerCase()),
    );
    const status = extractGateStatus(name, text);

    return {
      name,
      status: matched ? status : "unknown",
      source: matched ? "progress-ledger" : "none",
      lastUpdated: "",
    };
  });
}

export function getLatestGateResults(text: string): GateResult[] {
  return parseGateHistory(text);
}

function extractGateStatus(name: string, text: string): string {
  const lower = text.toLowerCase();

  if (name === "vitest") {
    const match = text.match(/(\d+)\/(\d+)\s+tests?\s+PASS/i);
    return match ? `PASS (${match[1]}/${match[2]})` : "PASS";
  }
  if (name === "tsc") {
    return lower.includes("clean") || lower.includes("0 errors")
      ? "PASS (clean)"
      : "PASS";
  }
  if (name === "ruff") {
    return lower.includes("clean") ? "PASS" : "unknown";
  }
  if (name === "pre-commit") {
    return lower.includes("通过") || lower.includes("pass") ? "PASS" : "unknown";
  }
  if (name === "git diff --check") {
    return lower.includes("clean") ? "PASS" : "unknown";
  }
  if (name === "pytest") {
    const match = text.match(/pytest.*?(\d+)\s+passed/i);
    return match ? `PASS (${match[1]} passed)` : "PASS";
  }
  return "PASS";
}
