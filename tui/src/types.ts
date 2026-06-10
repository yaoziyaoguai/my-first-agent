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

// ============================================================
// B8 Interaction-first Workbench types (M1+)
// ============================================================

/** Agent Lens 树节点类型 */
export type AgentLensNodeType = "agent" | "session" | "run" | "instance";

/** Agent Lens 树节点状态 */
export type AgentLensNodeStatus =
  | "active"
  | "paused"
  | "completed"
  | "failed"
  | "historical"
  | "superseded";

/** Agent Lens 树节点 */
export interface AgentLensNode {
  id: string;
  type: AgentLensNodeType;
  label: string;
  status: AgentLensNodeStatus;
  children: AgentLensNode[];
  metadata?: Record<string, string>;
}

/** 选中的 lens 上下文 */
export interface SelectedLens {
  agentId: string | null;
  sessionId: string | null;
  runId: string | null;
  instanceId: string | null;
}

/** 空 selected lens */
export const EMPTY_SELECTED_LENS: SelectedLens = {
  agentId: null,
  sessionId: null,
  runId: null,
  instanceId: null,
};

/** 三区域焦点 */
export type FocusZone = "agent-lens" | "interaction" | "context";
