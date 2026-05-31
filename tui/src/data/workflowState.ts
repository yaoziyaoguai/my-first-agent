/** 工作流状态解析: 从 PROJECT_STATUS/PROGRESS_LEDGER/SDD 派生 */

export interface MilestoneItem {
  name: string;
  commit: string;
  date: string;
}

export interface DeferredItem {
  name: string;
  reason: string;
}

export interface WorkflowState {
  currentStage: string;
  completedMilestones: MilestoneItem[];
  deferredItems: DeferredItem[];
  nextRecommended: string;
}

interface RawWorkflowState {
  currentStage: string;
  completedMilestones?: Partial<MilestoneItem>[];
  deferredItems?: Partial<DeferredItem>[];
  nextRecommended?: string;
}

export function parseWorkflowState(raw: RawWorkflowState): WorkflowState {
  return {
    currentStage: raw.currentStage,
    completedMilestones: (raw.completedMilestones ?? []).map((m) => ({
      name: m.name ?? "",
      commit: m.commit ?? "",
      date: m.date ?? "",
    })),
    deferredItems: (raw.deferredItems ?? []).map((d) => ({
      name: d.name ?? "",
      reason: d.reason ?? "",
    })),
    nextRecommended: raw.nextRecommended ?? "",
  };
}
