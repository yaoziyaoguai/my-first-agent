/** 导航模型: 7 视图定义与切换 */

export type ViewId =
  | "overview"
  | "evidence"
  | "workflow"
  | "commands"
  | "tasks"
  | "gates"
  | "docs";

export interface ViewDef {
  id: ViewId;
  label: string;
  shortcut: string;
}

export interface NavigationState {
  currentView: ViewId;
}

const VIEW_ORDER: ViewId[] = [
  "overview",
  "evidence",
  "workflow",
  "commands",
  "tasks",
  "gates",
  "docs",
];

export const VIEWS: ViewDef[] = [
  { id: "overview", label: "Overview", shortcut: "1" },
  { id: "evidence", label: "Evidence", shortcut: "2" },
  { id: "workflow", label: "Workflow", shortcut: "3" },
  { id: "commands", label: "Commands", shortcut: "4" },
  { id: "tasks", label: "Tasks", shortcut: "5" },
  { id: "gates", label: "Gates", shortcut: "6" },
  { id: "docs", label: "Docs", shortcut: "7" },
];

export function createNavigationState(): NavigationState {
  return { currentView: "overview" };
}

export function navigateTo(
  state: NavigationState,
  viewId: ViewId,
): NavigationState {
  if (!VIEW_ORDER.includes(viewId)) return state;
  return { currentView: viewId };
}

export function navigateNext(state: NavigationState): NavigationState {
  const idx = VIEW_ORDER.indexOf(state.currentView);
  const next = (idx + 1) % VIEW_ORDER.length;
  return { currentView: VIEW_ORDER[next] };
}

export function navigatePrev(state: NavigationState): NavigationState {
  const idx = VIEW_ORDER.indexOf(state.currentView);
  const prev = (idx - 1 + VIEW_ORDER.length) % VIEW_ORDER.length;
  return { currentView: VIEW_ORDER[prev] };
}

export function getCurrentView(state: NavigationState): ViewDef | undefined {
  return VIEWS.find((v) => v.id === state.currentView);
}

export function getViewIndex(viewId: ViewId): number {
  const idx = VIEW_ORDER.indexOf(viewId);
  return idx;
}

export function getViewCount(): number {
  return VIEWS.length;
}

export function formatNavigationLabel(viewId: ViewId): string {
  const view = VIEWS.find((v) => v.id === viewId);
  if (!view) return String(viewId);
  const idx = getViewIndex(viewId);
  return `${view.shortcut}: ${view.label} (${idx + 1}/${VIEWS.length})`;
}
