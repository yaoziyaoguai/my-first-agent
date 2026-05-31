/** REAL-EVIDENCE 单行状态 */
export interface RealEvidenceRow {
  id: string;
  capability: string;
  status: "credible" | "credible-with-caveats" | "partial-credible";
  notes: string;
}

/** PROJECT_STATUS.md 解析结果 */
export interface ProjectStatus {
  lastUpdated: string;
  score: string;
  credibleCount: string;
  overallVerdict: string;
  recommendedNext: string;
  realEvidenceRows: RealEvidenceRow[];
}

/** 单个里程碑 */
export interface Milestone {
  date: string;
  title: string;
  commit: string;
  summary: string;
}

/** PROGRESS_LEDGER.md 解析结果 */
export interface ProgressLedger {
  milestones: Milestone[];
}

/** 单个 dogfood 结果 */
export interface DogfoodResult {
  fileName: string;
  pass: number;
  fail: number;
  concern: number;
  summary: string;
}

/** Git 信息 */
export interface GitInfo {
  branch: string;
  headCommit: string;
  recentCommits: CommitInfo[];
  dirtyFiles: string[];
}

export interface CommitInfo {
  hash: string;
  message: string;
}

/** 安全等级 */
export type SafetyLevel =
  | "read-only"
  | "preview-only"
  | "requires-confirmation"
  | "disabled"
  | "future-executable";

/** 命令类别 */
export type CommandCategory =
  | "diagnostics"
  | "execution"
  | "workflow"
  | "gates"
  | "docs";

/** 单个命令定义 */
export interface CommandDefinition {
  id: string;
  name: string;
  description: string;
  category: CommandCategory;
  safetyLevel: SafetyLevel;
  requiresConfirmation: boolean;
  executableInPhase2: boolean;
  shellCommand?: string;
  relatedSkills?: string[];
  riskNote?: string;
}

/** 命令目录 */
export interface CommandCatalog {
  version: string;
  commands: CommandDefinition[];
}
