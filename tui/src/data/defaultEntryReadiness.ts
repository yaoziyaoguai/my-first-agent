/** Phase Polish: Default Entry Readiness Checklist */
export type ReadinessStatus = "done" | "blocked-b8-debt" | "blocked-b7" | "blocked-ime" | "pending";

export interface ReadinessItem {
  id: string;
  label: string;
  description: string;
  status: ReadinessStatus;
}

const STATUS_LABELS: Record<ReadinessStatus, string> = {
  done: "✓ done",
  "blocked-b8-debt": "✗ blocked (B8: Phase 6B/7 deferred)",
  "blocked-b7": "✗ blocked (B7 readiness)",
  "blocked-ime": "✗ blocked (IME/multi-line input)",
  pending: "○ pending",
};

const STATUS_COLORS: Record<ReadinessStatus, string> = {
  done: "green",
  "blocked-b8-debt": "yellow",
  "blocked-b7": "yellow",
  "blocked-ime": "yellow",
  pending: "dim",
};

export function getReadinessItems(): ReadinessItem[] {
  return [
    {
      id: "R01",
      label: "TUI 启动并展示 dashboard",
      description: "npm start 成功渲染 7 视图工作台",
      status: "done",
    },
    {
      id: "R02",
      label: "静态数据源全部解析",
      description: "PROJECT_STATUS / PROGRESS_LEDGER / dogfood JSON / git info",
      status: "done",
    },
    {
      id: "R03",
      label: "7 视图键盘导航",
      description: "← → / 1-7 视图切换, ↑↓ 列表导航",
      status: "done",
    },
    {
      id: "R04",
      label: "安全命令执行 (白名单 + confirmation gate)",
      description: "status/gates/docs-check/autorun/audit/dogfood 可执行",
      status: "done",
    },
    {
      id: "R05",
      label: "Audit log (JSONL append-only + rotation)",
      description: "命令执行审计记录, 10MB 自动 rotation",
      status: "done",
    },
    {
      id: "R06",
      label: "AutoRun workflow 集成",
      description: "固定模板命令, preview→confirm→dry-run→exec 流程",
      status: "done",
    },
    {
      id: "R07",
      label: "Static evidence/gate browser",
      description: "dogfood JSON 解析, gate history 文本解析, 21 tests",
      status: "done",
    },
    {
      id: "R08",
      label: "227/227 tests PASS + tsc clean",
      description: "全量测试通过, TypeScript 编译无错误",
      status: "done",
    },
    {
      id: "R09",
      label: "Audit log browser UI",
      description: "只读 audit history 面板, 不写 runtime state",
      status: "pending",
    },
    {
      id: "R10",
      label: "Phase 6B multi-run evidence history",
      description: "需要 session/run/instance identity + evidence namespace",
      status: "blocked-b8-debt",
    },
    {
      id: "R11",
      label: "Phase 7 runtime event stream viewer",
      description: "需要 append-only event source contract",
      status: "blocked-b8-debt",
    },
    {
      id: "R12",
      label: "B7 multi-instance readiness",
      description: "session/run/instance identity model 就绪后恢复 Phase 6B/7",
      status: "blocked-b7",
    },
    {
      id: "R13",
      label: "Chinese IME / multi-line input / paste",
      description: "Ink useInput 中文输入行为待实际终端验证",
      status: "blocked-ime",
    },
    {
      id: "R14",
      label: "Terminal resize 行为",
      description: "Ink 自动重渲染, 待大窗口/小窗口边界验证",
      status: "pending",
    },
    {
      id: "R15",
      label: "CLI fallback 保留",
      description: "CLI 为显式 fallback, 永不删除",
      status: "done",
    },
    {
      id: "R16",
      label: "用户显式确认 TUI 为默认入口",
      description: "所有 blocked 项解除后需用户决策",
      status: "blocked-b8-debt",
    },
  ];
}

export function getReadinessSummary(): {
  done: number;
  blocked: number;
  pending: number;
  total: number;
} {
  const items = getReadinessItems();
  const done = items.filter((i) => i.status === "done").length;
  const blocked = items.filter((i) => i.status.startsWith("blocked")).length;
  const pending = items.filter((i) => i.status === "pending").length;
  return { done, blocked, pending, total: items.length };
}

export { STATUS_LABELS, STATUS_COLORS };
