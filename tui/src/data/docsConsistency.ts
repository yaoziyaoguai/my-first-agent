/** 文档一致性检测模型 */

import { existsSync } from "node:fs";
import { resolve } from "node:path";

export type DocsStatus = "present" | "missing" | "unknown";

export interface DocsCheckResult {
  name: string;
  path: string;
  status: DocsStatus;
}

interface DocDef {
  name: string;
  path: string;
}

const REQUIRED_DOCS: DocDef[] = [
  { name: "PROJECT_STATUS.md", path: "../docs/PROJECT_STATUS.md" },
  { name: "PROGRESS_LEDGER.md", path: "../docs/PROGRESS_LEDGER.md" },
  { name: "REAL_EVIDENCE_VALIDATION_DEBT.md", path: "../docs/debt/REAL_EVIDENCE_VALIDATION_DEBT.md" },
  { name: "B8 TUI SDD", path: "../docs/design/b8-ts-tui-workbench-sdd.md" },
];

function resolvePath(relativePath: string): string {
  return resolve(__dirname, relativePath);
}

export function checkDocs(): DocsCheckResult[] {
  return REQUIRED_DOCS.map((doc): DocsCheckResult => {
    try {
      const fullPath = resolvePath(doc.path);
      const exists = existsSync(fullPath);
      return {
        name: doc.name,
        path: doc.path,
        status: exists ? "present" : "missing",
      };
    } catch {
      return {
        name: doc.name,
        path: doc.path,
        status: "unknown",
      };
    }
  });
}

export function getDocsByStatus(
  results: DocsCheckResult[],
  status: DocsStatus,
): DocsCheckResult[] {
  return results.filter((r) => r.status === status);
}
