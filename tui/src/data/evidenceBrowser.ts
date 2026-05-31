/** Phase 6A: Static Evidence Browser — 解析 dogfood JSON 文件并归一化 */
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

export type EvidenceStatus =
  | "credible"
  | "credible-with-caveats"
  | "partial-credible"
  | "unknown";

export interface EvidenceFileEntry {
  fileName: string;
  evidenceId: string;
  pass: number;
  fail: number;
  concern: number;
  status: EvidenceStatus;
  error: string;
  date: string;
  caseCount: number;
}

export interface VerdictCounts {
  pass: number;
  fail: number;
  concern: number;
}

export function normalizeVerdictCounts(
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  json: Record<string, any> | null,
): VerdictCounts {
  if (!json || typeof json !== "object") {
    return { pass: 0, fail: 0, concern: 0 };
  }
  const summary = json.summary;
  if (summary && typeof summary === "object") {
    const p = safeInt(summary.PASS);
    const f = safeInt(summary.FAIL);
    const c = safeInt(summary.CONCERN);
    if (p > 0 || f > 0 || c > 0) {
      return { pass: p, fail: f, concern: c };
    }
  }
  // Fallback: count from results array
  if (Array.isArray(json.results)) {
    const counts: VerdictCounts = { pass: 0, fail: 0, concern: 0 };
    for (const item of json.results) {
      const v = item?.verdict;
      if (v === "PASS") counts.pass++;
      else if (v === "FAIL") counts.fail++;
      else if (v === "CONCERN") counts.concern++;
    }
    return counts;
  }
  return { pass: 0, fail: 0, concern: 0 };
}

export function parseDogfoodFile(
  fileName: string,
  content: string,
): EvidenceFileEntry {
  const unknown: EvidenceFileEntry = {
    fileName,
    evidenceId: "",
    pass: 0,
    fail: 0,
    concern: 0,
    status: "unknown",
    error: "",
    date: "",
    caseCount: 0,
  };

  if (!content.trim()) {
    return { ...unknown, error: "empty file" };
  }

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let json: Record<string, any>;
  try {
    json = JSON.parse(content);
  } catch {
    return { ...unknown, error: "JSON parse error" };
  }

  const evidenceId =
    typeof json.evidence_id === "string" ? json.evidence_id : "";
  const date = typeof json.date === "string" ? json.date : "";
  const counts = normalizeVerdictCounts(json);
  const caseCount = Array.isArray(json.results) ? json.results.length : 0;

  const status = deriveEvidenceStatus(counts);

  return {
    fileName,
    evidenceId,
    pass: counts.pass,
    fail: counts.fail,
    concern: counts.concern,
    status,
    error: "",
    date,
    caseCount,
  };
}

export function buildEvidenceFileIndex(
  entries: EvidenceFileEntry[],
): Map<string, EvidenceFileEntry> {
  const index = new Map<string, EvidenceFileEntry>();
  for (const e of entries) {
    if (e.evidenceId) {
      // Use the most recent entry if multiple files map to same ID
      const existing = index.get(e.evidenceId);
      if (!existing || e.date > existing.date) {
        index.set(e.evidenceId, e);
      }
    }
  }
  return index;
}

export function listDogfoodFiles(dir: string): EvidenceFileEntry[] {
  try {
    if (!existsSync(dir)) return [];
    const files = readdirSync(dir).filter((f) => f.endsWith(".json"));
    return files
      .map((f) => {
        const content = readFileSync(resolve(dir, f), "utf-8");
        return parseDogfoodFile(f, content);
      })
      .sort((a, b) => b.date.localeCompare(a.date));
  } catch {
    return [];
  }
}

function deriveEvidenceStatus(counts: VerdictCounts): EvidenceStatus {
  if (counts.fail > 0) return "partial-credible";
  if (counts.concern > 0) return "credible-with-caveats";
  if (counts.pass > 0) return "credible";
  return "unknown";
}

function safeInt(val: unknown): number {
  if (typeof val === "number" && Number.isFinite(val)) return val;
  if (typeof val === "string") {
    const n = parseInt(val, 10);
    return Number.isFinite(n) ? n : 0;
  }
  return 0;
}
