/** M6 — EvidenceNamespace 契约定义。
 *  仅定义契约，不实现真实 filesystem scan。
 *  真实 evidence namespace 依赖 B7 session/run/instance identity model。 */

/** evidence 所属命名空间 */
export type EvidenceNamespaceKind = "global" | "per-run" | "per-session" | "per-instance";

/** EvidenceNamespace 契约：描述一个 evidence 如何定位、存储和失效 */
export interface EvidenceNamespace {
  /** evidence 标识符，如 "evidence-001" */
  evidenceId: string;
  /** 命名空间类型 */
  kind: EvidenceNamespaceKind;
  /** 存储路径模式，如 "docs/dogfood/{evidence_id}-{run_id}.json" */
  storagePattern: string;
  /** TTL 天数，null 表示永不过期 */
  ttlDays: number | null;
  /** 该 evidence 是否支持多 run 历史 */
  multiRun: boolean;
  /** 描述 */
  description: string;
}

/** MultiRunStorageContract — 多实例存储契约。
 *  定义跨 run 的文件命名、布局和清理策略。 */
export interface MultiRunStorageContract {
  /** 文件命名约定 */
  fileNaming: "{evidence_id}-{run_id}.json" | "{date}-{evidence_id}.json" | "{run_id}/{evidence_id}.json";
  /** 存储根目录（相对于项目根） */
  storageRoot: string;
  /** TTL 天数，过期文件可被清理 */
  ttlDays: number;
  /** 是否自动清理过期文件 */
  autoCleanup: boolean;
  /** 最大保留 run 数（超出部分归档） */
  maxRuns: number;
  /** 归档目录（null 表示不归档，直接删除） */
  archiveDir: string | null;
}

/** 预定义的 evidence namespace 清单（fake/local — 基于当前已知 8 个 evidence） */
export const EVIDENCE_NAMESPACE_CATALOG: EvidenceNamespace[] = [
  {
    evidenceId: "evidence-001",
    kind: "global",
    storagePattern: "docs/dogfood/evidence-001-results.json",
    ttlDays: null,
    multiRun: false,
    description: "Provider configuration capability",
  },
  {
    evidenceId: "evidence-002",
    kind: "global",
    storagePattern: "docs/dogfood/evidence-002-results.json",
    ttlDays: null,
    multiRun: false,
    description: "Core loop runtime capability",
  },
  {
    evidenceId: "evidence-003",
    kind: "global",
    storagePattern: "docs/dogfood/evidence-003-results.json",
    ttlDays: null,
    multiRun: false,
    description: "Memory subsystem capability",
  },
  {
    evidenceId: "evidence-004",
    kind: "global",
    storagePattern: "docs/dogfood/evidence-004-results.json",
    ttlDays: null,
    multiRun: false,
    description: "Checkpoint subsystem capability",
  },
  {
    evidenceId: "evidence-005",
    kind: "global",
    storagePattern: "docs/dogfood/evidence-005-results.json",
    ttlDays: null,
    multiRun: false,
    description: "MCP subsystem capability",
  },
  {
    evidenceId: "evidence-006",
    kind: "global",
    storagePattern: "docs/dogfood/evidence-006-results.json",
    ttlDays: null,
    multiRun: false,
    description: "Skill subsystem capability",
  },
  {
    evidenceId: "evidence-007",
    kind: "global",
    storagePattern: "docs/dogfood/evidence-007-results.json",
    ttlDays: null,
    multiRun: false,
    description: "Tool subsystem capability",
  },
  {
    evidenceId: "evidence-008",
    kind: "global",
    storagePattern: "docs/dogfood/evidence-008-results.json",
    ttlDays: null,
    multiRun: false,
    description: "Action scheduler capability",
  },
];

/** 默认 MultiRunStorageContract（fake/local — B7 就绪前不启用） */
export const DEFAULT_STORAGE_CONTRACT: MultiRunStorageContract = {
  fileNaming: "{evidence_id}-{run_id}.json",
  storageRoot: "docs/dogfood/",
  ttlDays: 90,
  autoCleanup: false,
  maxRuns: 50,
  archiveDir: "docs/dogfood/archive/",
};

/** 验证 evidenceId 是否已在 catalog 中注册 */
export function isEvidenceRegistered(evidenceId: string): boolean {
  return EVIDENCE_NAMESPACE_CATALOG.some((ns) => ns.evidenceId === evidenceId);
}

/** 按 kind 过滤 evidence namespace */
export function filterByKind(kind: EvidenceNamespaceKind): EvidenceNamespace[] {
  return EVIDENCE_NAMESPACE_CATALOG.filter((ns) => ns.kind === kind);
}

/** 获取支持多 run 的 evidence 列表 */
export function getMultiRunEvidences(): EvidenceNamespace[] {
  return EVIDENCE_NAMESPACE_CATALOG.filter((ns) => ns.multiRun);
}

/** 验证文件命名是否符合 storage contract */
export function validateFileName(
  fileName: string,
  contract: MultiRunStorageContract,
): boolean {
  switch (contract.fileNaming) {
    case "{evidence_id}-{run_id}.json":
      return /^evidence-\d+-[\w-]+\.json$/.test(fileName);
    case "{date}-{evidence_id}.json":
      return /^\d{4}-\d{2}-\d{2}-evidence-\d+\.json$/.test(fileName);
    case "{run_id}/{evidence_id}.json":
      return /^[\w-]+\/evidence-\d+\.json$/.test(fileName);
  }
}
