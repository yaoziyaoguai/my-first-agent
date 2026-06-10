/** 文档一致性检测模型 — 文件存在性 + 内容 staleness */

import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

export type DocsStatus = "present" | "missing" | "unknown";
export type ContentStatus = "stale" | "current" | "unknown";

/** 已知过期标记 — 这些字符串不应出现在当前最新文档中。出现即标记 stale。 */
interface StaleMarker {
  /** 匹配正则 */
  pattern: RegExp;
  /** 人类可读标记名 */
  label: string;
  /** 仅对哪些文档生效 (name 匹配, 空数组 = 所有文档) */
  files: string[];
}

const STALE_MARKERS: StaleMarker[] = [
  {
    // 旧测试数 — 227/227 是 Phase 6A 的状态, 当前应 ≥ 241
    pattern: /\b227\/227\b/,
    label: "old test count 227/227 (current ≥ 241)",
    files: ["PROJECT_STATUS.md", "PROGRESS_LEDGER.md"],
  },
  {
    // 旧 Phase 状态 — Phase 3 不再 recommended
    pattern: /Phase 3.*recommended/i,
    label: "Phase 3 marked as recommended (now completed)",
    files: ["PROJECT_STATUS.md"],
  },
  {
    // Phase 4 不应再标记 deferred
    pattern: /b8-phase-4.*deferred/i,
    label: "Phase 4 marked as deferred (now completed)",
    files: [],
  },
  {
    // Phase 5 不应再标记 deferred
    pattern: /b8-phase-5.*deferred/i,
    label: "Phase 5 marked as deferred (now completed)",
    files: [],
  },
  {
    // Phase 6A 不应标记为 not started
    pattern: /Phase 6A.*not.started/i,
    label: "Phase 6A marked as not-started (now completed)",
    files: ["PROJECT_STATUS.md"],
  },
];

export interface StaleFinding {
  label: string;
  match: string;
}

export interface DocsCheckResult {
  name: string;
  path: string;
  status: DocsStatus;
  /** 内容新鲜度 — 仅在 status === "present" 时有意义 */
  contentStatus: ContentStatus;
  /** 检测到的过期标记 — 仅在 contentStatus === "stale" 时有内容 */
  staleFindings: StaleFinding[];
}

interface DocDef {
  name: string;
  path: string;
}

const REQUIRED_DOCS: DocDef[] = [
  { name: "PROJECT_STATUS.md", path: "../docs/PROJECT_STATUS.md" },
  { name: "PROGRESS_LEDGER.md", path: "../docs/PROGRESS_LEDGER.md" },
  { name: "B8 Interaction-first Workbench SDD", path: "../docs/design/b8-interaction-first-workbench-sdd.md" },
];

function resolvePath(relativePath: string): string {
  return resolve(__dirname, relativePath);
}

/**
 * 纯函数: 扫描文本内容中的已知过期标记。
 * 不读取文件系统 — 可测试。
 */
export function scanContentForStaleMarkers(
  docName: string,
  content: string,
): StaleFinding[] {
  const findings: StaleFinding[] = [];
  for (const marker of STALE_MARKERS) {
    if (marker.files.length > 0 && !marker.files.includes(docName)) {
      continue;
    }
    const match = content.match(marker.pattern);
    if (match) {
      findings.push({ label: marker.label, match: match[0] });
    }
  }
  return findings;
}

/**
 * 检测单个文档的内容 staleness。
 * 对文件内容扫描已知过期标记 (STALE_MARKERS)。
 * 如无法读取文件或无法判定 → unknown。
 */
export function checkContentStaleness(
  docName: string,
  fullPath: string,
): { contentStatus: ContentStatus; staleFindings: StaleFinding[] } {
  try {
    const content = readFileSync(fullPath, "utf-8");
    const findings = scanContentForStaleMarkers(docName, content);
    if (findings.length > 0) {
      return { contentStatus: "stale", staleFindings: findings };
    }
    return { contentStatus: "current", staleFindings: [] };
  } catch {
    return { contentStatus: "unknown", staleFindings: [] };
  }
}

export function checkDocs(): DocsCheckResult[] {
  return REQUIRED_DOCS.map((doc): DocsCheckResult => {
    try {
      const fullPath = resolvePath(doc.path);
      const exists = existsSync(fullPath);

      if (!exists) {
        return {
          name: doc.name,
          path: doc.path,
          status: "missing",
          contentStatus: "unknown",
          staleFindings: [],
        };
      }

      const { contentStatus, staleFindings } = checkContentStaleness(doc.name, fullPath);
      return {
        name: doc.name,
        path: doc.path,
        status: "present",
        contentStatus,
        staleFindings,
      };
    } catch {
      return {
        name: doc.name,
        path: doc.path,
        status: "unknown",
        contentStatus: "unknown",
        staleFindings: [],
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

/** 按内容状态过滤 */
export function getDocsByContentStatus(
  results: DocsCheckResult[],
  contentStatus: ContentStatus,
): DocsCheckResult[] {
  return results.filter((r) => r.contentStatus === contentStatus);
}
