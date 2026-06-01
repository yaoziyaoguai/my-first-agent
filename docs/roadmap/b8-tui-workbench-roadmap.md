# B8 TypeScript TUI Workbench — 分阶段路线

**创建日期**: 2026-06-01
**最后更新**: 2026-06-01 (B8 Final Boundary Audit — boundary CLOSED)
**来源**: `/plan-eng-review` → B8 Roadmap / Default Entry Readiness Review → AutoRun Hardening
**依赖文档**: `docs/design/b8-ts-tui-workbench-sdd.md` (Phase 1-3 SDD)、`docs/PROJECT_STATUS.md` (当前状态)、`docs/debt/b8-tui-workbench-technical-debt.md` (Phase 6B/7 deferred debt)

---

## 1. 总览

B8 目标：TUI 替代 CLI 成为 First Agent 的默认交互入口。开发者通过终端工作台完成所有工程操作（状态查看、命令执行、workflow 编排），CLI 保留为底层能力和 fallback。

### 1.1 Phase 全景

```
Phase 1 (COMPLETED)     Phase 2 (COMPLETED)     Phase 3 (COMPLETED)
静态仪表盘              Command Shell            默认入口就绪
5 面板, 28 tests       8 命令, 74 tests         7 视图, 133 tests
eba77ad                 3c8e178                  2ae13ab
    │                       │                       │
    ▼                       ▼                       ▼
┌───────────────────────────────────────────────────────────┐
│              当前基线: Phase 3 COMPLETED                   │
│  133/133 tests PASS, tsc --noEmit clean                  │
│  TUI 为未来默认入口, CLI 为显式 fallback                      │
└───────────────────────────────────────────────────────────┘
    │
    ▼
Phase 4 (COMPLETED)      Phase 5 (COMPLETED)      Phase 6A (COMPLETED)
安全命令执行             AutoRun 工作流集成       静态证据/门禁浏览器
confirmation gate       TUI→AutoRun launcher    JSON 解析 + gate history
    │                       │                       │
    ▼                       ▼                       ▼
Phase 6B (BLOCKED by B7)  Phase 7 (FUTURE)
多实例历史浏览器          运行时 Event Stream 查看器
trend, commit linkage    read-only stream, 不回写
```

### 1.2 各 Phase 交付物

| Phase | 名称 | 状态 | 关键交付物 | 可自动执行 |
|-------|------|------|-----------|-----------|
| **Phase 1** | 静态仪表盘 | **COMPLETED** | 5 面板, 28 tests | — |
| **Phase 2** | Command Shell | **COMPLETED** | CommandCatalog, CommandPanel, 74 tests | — |
| **Phase 3** | 默认入口就绪 | **COMPLETED** | 7 视图导航, 133 tests | — |
| **Phase 4** | 安全命令执行 | **READY** | confirmation gate, dry-run, audit log | ✅ |
| **Phase 5** | AutoRun 工作流集成 | **READY** | TUI→AutoRun launcher, state panel, review packet | ✅ (after P4) |
| **Phase 6A** | 静态证据/门禁/Dogfood 浏览器 | **COMPLETED** | 本地 JSON 解析, gate history, 证据浏览 | ✅ (已自动执行) |
| **Phase 6B** | 多实例历史浏览器 | **BLOCKED** (by B7) | multi-run history, 趋势, commit linkage | ❌ |
| **Phase 7** | 运行时 Event Stream 查看器 | **FUTURE** (after P4-P6B) | read-only stream viewer | ❌ |

---

## 2. 当前状态 (Phase 3 COMPLETED)

### 2.1 已交付

| 能力域 | 状态 | 证据 |
|--------|------|------|
| Navigation Model | **DONE** | 7 视图 (Overview/Evidence/Workflow/Commands/Tasks/Gates/Docs), ←→/1-7 键盘导航 |
| TaskCenterPanel | **DONE** | B8/B7 phase 状态矩阵, 6 entries |
| WorkflowState Model | **DONE** | currentStage, completedMilestones, deferredItems, nextRecommended |
| EvidenceDetail Model | **DONE** | 001-008 详情 (status/dogfood/commit/caveats/nextAction) |
| DocsConsistency Model | **DONE** | 4 关键文档 present/missing/unknown 检测 |
| CommandCatalog v2 | **DONE** | workflowStage + riskLevel 字段, 11 命令 |
| Default Entry Readiness | **DONE** | 12 项 checklist 已定义, TUI 不立即切换为默认入口 |

### 2.2 测试基线

| 指标 | 值 |
|------|---|
| 测试文件 | 17 |
| 测试总数 | 133 |
| 测试结果 | 133 PASS / 0 FAIL |
| TypeScript 编译 | tsc --noEmit clean |
| 依赖 | Ink 5, React 18, tsx, vitest |

### 2.3 技术栈锁定

- **Runtime**: Node.js v20+ (TypeScript 5.x)
- **TUI 框架**: Ink 5 + React 18
- **构建工具**: tsx
- **测试框架**: Vitest
- **不引入**: React DOM, Express, 数据库, WebSocket, git 库, 外部 API client

---

## 3. Phase 4: 安全命令执行 (NEXT — READY)

**状态**: READY for AutoRun。不依赖外部条件。
**优先级**: B8 路线中最高优先级。
**预估文件数**: ~12 (4 新组件 + 4 新数据模型 + 1 配置 + 3 新测试文件)
**预估行数**: ~600 TypeScript (含测试)
**Phase 入口条件**: Phase 3 COMPLETED, 133/133 tests PASS, tsc clean

### 3.1 目标

TUI 从 preview-only 升级为可执行安全命令。用户选中命令 → 确认 → 执行 → 查看结果，全程不离开 TUI。

### 3.2 精确命令白名单与黑名单

#### 3.2.1 白名单 (Phase 4 可执行)

| 命令 ID | Safety 升级前 | Phase 4 行为 | 实际命令 |
|---------|-------------|-------------|---------|
| `status` | preview-only | 执行 | `python main.py status` |
| `gates` | preview-only | 执行 | `cd <repo> && ruff check . && python -m pytest tests/ -x -q` |
| `docs-check` | preview-only | 执行 | Node fs 检查 + `git diff --check` |
| `autorun` | requires-confirmation | **double-confirmation** 后执行 | `/auto-run <user prompt>` |
| `audit` | requires-confirmation | 确认后执行 | `/audit` |
| `dogfood` | requires-confirmation | 确认后执行 | 指定的 dogfood 脚本 |

#### 3.2.2 黑名单 (Phase 4 不可执行)

| 命令类别 | 具体 | 原因 |
|---------|------|------|
| Destructive git | `push --force`, `reset --hard`, `branch -D`, `clean -f` | 不可逆 |
| 文件删除 | `rm -rf`, `git clean` | 不可逆 |
| 强制覆盖 | `git push --force`, `checkout -- .` | 丢失工作 |
| 系统命令 | `sudo`, `chmod`, `chown` | 权限变更 |
| 网络操作 | `curl`, `wget` (非白名单 URL) | 外部请求 |
| agent-run | `python main.py run` | Phase 5+ |
| deploy | 任何部署命令 | future |

### 3.3 Confirmation Model

```
用户选中命令 (Enter)
→ CommandPreview 已显示 (来自 Phase 2, 重用于展示)
→ 按 Enter 触发 "Execute?" 确认覆盖层:
  ┌────────────────────────────────────────────┐
  │  ⚠ Execute Command?                        │
  │                                            │
  │  Command: python main.py status            │
  │  Safety:  preview-only → executing         │
  │  Risk:    read-only, no side effects       │
  │                                            │
  │  [y] Execute   [n] Cancel   [d] Dry-run   │
  └────────────────────────────────────────────┘
→ y: 执行 → 显示 ResultPanel
→ n: 取消 → 返回 CommandPanel
→ d: dry-run → 显示 would-execute 但不实际执行

高风险命令 (requires-confirmation + riskLevel="high"):
→ 需要 double-confirmation:
  ┌────────────────────────────────────────────┐
  │  ⚠⚠ DOUBLE CONFIRMATION REQUIRED            │
  │                                            │
  │  Command: /auto-run <prompt>               │
  │  Risk:    启动完整 AutoRun loop             │
  │           可能执行 git push                 │
  │                                            │
  │  Type "yes" to confirm: _                  │
  └────────────────────────────────────────────┘
```

### 3.4 Dry-Run Model

| 命令类别 | Dry-Run 行为 |
|---------|-------------|
| `status` / `gates` / `docs-check` | 显示 will-execute shell command，不实际执行 |
| `autorun` / `audit` / `dogfood` | 显示 full prompt text，标注 "dry-run: 不实际执行" |
| destructive 类别 | 不在白名单中，dry-run 也不可达 |

Dry-run 结果展示:
```
┌────────────────────────────────────────────┐
│  Dry-Run Result                            │
│                                            │
│  Would execute: python main.py status      │
│  CWD: /path/to/repo                        │
│  Expected: stdout > TUI panel              │
│                                            │
│  [Execute for real]  [Back]               │
└────────────────────────────────────────────┘
```

### 3.5 Result Panel

命令执行后展示结果:
```
┌────────────────────────────────────────────┐
│  Result — status                           │
│                                            │
│  Exit code: 0                              │
│  Duration:  1.2s                           │
│                                            │
│  stdout:                                   │
│  Project Status: Phase 3 COMPLETED         │
│  Score: 4.5/5 conservative baseline        │
│  ...                                       │
│                                            │
│  stderr: (none)                            │
│                                            │
│  [Back to commands]  [Copy to clipboard]   │
└────────────────────────────────────────────┘
```

### 3.6 Audit Log Model

每条 TUI 执行的命令记录到 `tui/.tui_audit_log.jsonl`（不 commit）:

```typescript
interface AuditLogEntry {
  timestamp: string;        // ISO 8601
  commandId: string;        // "status", "gates", etc.
  shellCommand: string;     // actual executed command
  safetyLevel: SafetyLevel;
  confirmation: "single" | "double" | "skipped-dry-run";
  exitCode: number | null;
  durationMs: number;
  truncated: boolean;       // stdout truncated?
}
```

- 文件 append-only，不提供删除 API
- 最大 10MB，超过后轮转 (`.archived-<timestamp>`)
- `.gitignore` 已包含 `tui/.tui_audit_log*`

### 3.7 实现文件

| 文件 | 类型 | 内容 |
|------|------|------|
| `tui/src/data/executionWhitelist.ts` | NEW data | 白名单/黑名单定义, SafetyModel→execution mapping |
| `tui/src/data/executionGate.ts` | NEW data | 确认模型, dry-run 逻辑, 命令构建 |
| `tui/src/data/auditLog.ts` | NEW data | JSONL append, rotation, 读取 |
| `tui/src/data/commandResult.ts` | NEW data | exec 结果解析 (stdout/stderr/exit code) |
| `tui/src/components/ConfirmOverlay.tsx` | NEW component | 确认对话框 (single + double) |
| `tui/src/components/ResultPanel.tsx` | NEW component | 执行结果展示 |
| `tui/src/components/DryRunOverlay.tsx` | NEW component | Dry-run 结果覆盖层 |
| `tui/src/components/ExecDashboard.tsx` | MODIFY | Dashboard 集成确认/结果/dry-run 流 |
| `tui/src/types.ts` | MODIFY | 新增 AuditLogEntry, ExecutionResult 等类型 |
| `tui/src/data/commands.json` | MODIFY | 更新 Phase 4 safety level |
| `tui/src/__tests__/executionWhitelist.test.ts` | NEW test | 白名单/黑名单测试 |
| `tui/src/__tests__/executionGate.test.ts` | NEW test | 确认/拒绝/dry-run/double-confirmation 测试 |
| `tui/src/__tests__/auditLog.test.ts` | NEW test | JSONL 写入/读取/轮转测试 |

### 3.8 Stop Conditions

| 条件 | 行为 |
|------|------|
| 白名单外命令请求执行 | **HARD_STOP** — 报告并拒绝 |
| exec 命令字符串动态构建 (非 hardcoded) | **HARD_STOP** — 报告并拒绝 |
| child_process 引入新子进程模式 (非 `exec`) | **HARD_STOP** — 报告 |
| 确认对话框超时 (30s 无输入) | 自动取消 → 返回 CommandPanel |
| exec 超时 (60s) | kill 子进程 → ResultPanel 显示 timeout |
| Phase 1-3 回归失败 | **HARD_STOP** — 不 commit, 先修回归 |
| 白名单扫描失败 (发现非白名单 exec 路径) | **HARD_STOP** — 不 commit |

### 3.9 测试计划

| 测试文件 | 覆盖 | 预估数量 |
|---------|------|---------|
| `executionWhitelist.test.ts` | 白名单允许/拒绝, 黑名单阻止, 边界 | 8 |
| `executionGate.test.ts` | 确认流程, 取消, dry-run, double-confirmation, timeout | 10 |
| `auditLog.test.ts` | JSONL 写入, 字段完整性, rotation, append-only, .gitignore | 7 |
| **Phase 4 新增** | | **~25** |
| **总计** | | **~158** |

### 3.10 门禁

| Gate | 命令 | 预期 |
|------|------|------|
| TypeScript | `npx tsc --noEmit` | 0 errors |
| Phase 4 tests | `npx vitest run` | all pass |
| Phase 1-3 regression | `npx vitest run` | 133/133 |
| 白名单扫描 | grep `exec(` / `execSync(` / `spawn(` in tui/src/ | 仅白名单文件 |
| no .env access | grep `\.env` / `DOTENV` / `process\.env\.` in tui/src/ | 0 matches |
| git diff --check | — | clean |

---

## 4. Phase 5: AutoRun 工作流集成 (AFTER P4 — READY)

**状态**: READY for AutoRun (Phase 4 完成后)。
**依赖**: Phase 4 (安全命令执行可用)。
**预估文件数**: ~10 (3 新组件 + 4 新数据模型 + 3 新测试文件)
**预估行数**: ~500 TypeScript (含测试)
**Phase 入口条件**: Phase 4 COMPLETED, ~158 tests PASS, Phase 4 gates all pass

### 4.1 目标

TUI 通过 Phase 4 的命令执行基础设施接入 AutoRun workflow。TUI 不重写 AutoRun，不绕过 AutoRun。用户通过 TUI 发起 AutoRun → 确认 → 执行 → 实时查看状态 → 查看 review packet → 识别 HARD_STOP。

### 4.2 核心原则

1. **TUI 不重写 AutoRun** — TUI 只通过 approved command adapter 接入，不实现 AutoRun 逻辑
2. **不绕过 AutoRun workflow** — 所有 AutoRun 操作走 `/auto-run` skill，TUI 只是 launcher
3. **不 unattended execution** — 每个高风险步骤需要用户确认
4. **TUI 是 AutoRun 的 view layer** — AutoRun 的 Python runtime 执行，TUI 展示状态

### 4.3 Approved Command Adapter

TUI 通过以下固定命令模式接入 AutoRun:

```typescript
// 所有 AutoRun 命令都是固定模板，不动态拼接
const AUTORUN_COMMANDS: Record<string, string> = {
  "continue": "cd <repo> && python main.py auto-run --continue",
  "status":   "cd <repo> && python main.py status",
  "audit":    "cd <repo> && python main.py audit --readonly",
  "dogfood":  "cd <repo> && python main.py dogfood --case=<id>",
  "gates":    "cd <repo> && ruff check . && python -m pytest tests/ -x -q",
};
```

禁止:
- 动态构建 `auto-run <user_typed_prompt>`（防止注入）
- 将 TUI 用户输入直接拼接到 shell 命令
- 从 agent_log.jsonl 读取 AutoRun 状态并自行决策下一步

### 4.4 用户流程

```
TUI CommandPanel → 选中 "AutoRun Continue"
→ CommandPreview (Phase 2 复用) — 显示将执行的命令
→ Confirmation Overlay (Phase 4 复用) — 确认执行
→ 执行 (Phase 4 exec path)
→ AutoRun State Panel — 展示当前状态
  ┌────────────────────────────────────────────┐
  │  AutoRun State                             │
  │                                            │
  │  Status: RUNNING                           │
  │  Loop:   Phase 4 implementation            │
  │  Stage:  TDD RED tests                     │
  │  Output: writing phase4 tests...           │
  │                                            │
  │  [View Full Log]  [Stop]                   │
  └────────────────────────────────────────────┘
→ 完成 → Review Packet Display
  ┌────────────────────────────────────────────┐
  │  AutoRun Review — Phase 4                  │
  │                                            │
  │  Tests:   25/25 PASS                       │
  │  TypeScript: clean                          │
  │  Gates:    all pass                        │
  │  Commit:   feat(tui): add phase 4          │
  │                                            │
  │  [View Diff]  [Next Loop]  [Stop]          │
  └────────────────────────────────────────────┘
```

### 4.5 HARD_STOP Display

AutoRun 遇到 HARD_STOP 时:
```
┌────────────────────────────────────────────┐
│  ⛔ HARD_STOP — AutoRun Paused              │
│                                            │
│  Reason: 白名单外命令请求执行              │
│  Detail: attempted exec of "rm -rf"        │
│  Loop:    Phase 4 implementation           │
│                                            │
│  User action needed:                       │
│  1. Review the stop reason above           │
│  2. Fix the issue in your terminal         │
│  3. Resume AutoRun: /auto-run --continue   │
│                                            │
│  [Exit TUI]  [Copy Stop Reason]            │
└────────────────────────────────────────────┘
```

### 4.6 AutoRun State Panel

从 `docs/PROJECT_STATUS.md` + `git log` 派生（不运行 AutoRun Python 进程）:

```typescript
interface AutoRunState {
  currentPhase: string;         // "Phase 4"
  status: "idle" | "running" | "completed" | "hard_stop";
  lastLoop: string;             // "Loop N"
  lastCommit: string;           // hash
  testsPass: number;
  gatesStatus: "all_pass" | "partial" | "failed";
  nextRecommended: string;      // from PROJECT_STATUS
  hardStopReason?: string;
}
```

- 数据源: PROJECT_STATUS.md 解析（已有解析器） + git log
- 不解析 agent_log.jsonl（Phase 5 不读 runtime logs）
- `status: "running"` 仅在 Phase 4 exec path 中 AutoRun 进程活跃时为 true

### 4.7 实现文件

| 文件 | 类型 | 内容 |
|------|------|------|
| `tui/src/data/autorunAdapter.ts` | NEW data | AUTORUN_COMMANDS 固定模板, 命令验证 |
| `tui/src/data/autorunState.ts` | NEW data | PROJECT_STATUS 解析→AutoRunState |
| `tui/src/data/reviewPacket.ts` | NEW data | 从 git log + test output 构建 review summary |
| `tui/src/components/AutoRunPanel.tsx` | NEW component | AutoRun 状态面板 |
| `tui/src/components/HardStopOverlay.tsx` | NEW component | HARD_STOP 展示 |
| `tui/src/components/ReviewPacketPanel.tsx` | NEW component | Review packet 展示 |
| `tui/src/components/Dashboard.tsx` | MODIFY | 新增 AutoRun view 或扩展现有 Commands view |

### 4.8 Stop Conditions

| 条件 | 行为 |
|------|------|
| 用户尝试动态构建 auto-run 命令 | **HARD_STOP** |
| AutoRun 进程返回非零 exit code | 展示错误, 暂停, 不等同于 HARD_STOP |
| git status 显示 dirty (非预期文件) | **HARD_STOP** |
| Phase 1-4 回归失败 | **HARD_STOP** |
| 发现非 AutoRun 标准命令模板被执行 | **HARD_STOP** |
| AutoRun 进程超时 (300s) | kill → 展示 timeout, 暂停 |

### 4.9 测试计划

| 测试文件 | 覆盖 | 预估数量 |
|---------|------|---------|
| `autorunAdapter.test.ts` | 固定命令模板, 注入防护, 验证逻辑 | 6 |
| `autorunState.test.ts` | PROJECT_STATUS 解析, status 映射, 边界 | 5 |
| `reviewPacket.test.ts` | git log 解析, test output 解析, summary 构建 | 4 |
| **Phase 5 新增** | | **~15** |
| **总计** | | **~173** |

### 4.10 门禁

| Gate | 命令 | 预期 |
|------|------|------|
| TypeScript | `npx tsc --noEmit` | 0 errors |
| Phase 5 tests | `npx vitest run` | all pass |
| Phase 1-4 regression | `npx vitest run` | ~158/158 |
| 命令注入扫描 | grep 动态字符串拼接 exec | 0 matches (仅固定模板) |
| no .env | grep `.env` / `process.env.` in new files | 0 matches |
| git diff --check | — | clean |

---

## 5. Phase 6A: 静态证据/门禁/Dogfood 浏览器 (COMPLETED)

**状态**: COMPLETED (2026-06-01)。
**设计决策**: Phase 6 拆分为 6A (静态浏览器，不依赖 B7) 和 6B (多实例历史浏览器，依赖 B7)。

### 5.1 目标

TUI 提供静态证据浏览器：解析本地 `docs/dogfood/*.json` 文件 → EvidenceFileEntry 列表；解析 PROJECT_STATUS + PROGRESS_LEDGER 文本 → GateResult 列表。所有数据来自本地只读文件。

### 5.2 数据源与实现

| 文件 | 类型 | 内容 |
|------|------|------|
| `tui/src/data/evidenceBrowser.ts` | NEW | EvidenceFileEntry 解析, listDogfoodFiles, buildEvidenceFileIndex |
| `tui/src/data/gateHistory.ts` | NEW | GateResult 解析, parseGateHistory, KNOWN_GATES (6) |
| `tui/src/components/EvidenceBrowserPanel.tsx` | NEW | Evidence 文件列表 (status badges: ✓/⚠/△/?, P/C/F counts) |
| `tui/src/components/DogfoodDetailPanel.tsx` | NEW | 选中 evidence 详情 + gate history 列表 |

### 5.3 Stale/Unknown Handling

- Evidence 文件 JSON 解析失败 → status "unknown", error 字段记录原因
- Gate 无匹配 keyword → status "unknown", source "none"
- 空输入 → 返回所有 6 个 known gates 为 "unknown"（不伪造 pass）
- 解析不崩溃 — try/catch 全覆盖

### 5.4 约束

- **不写入 runtime 状态** — 所有数据来自只读文件
- **不修改 evidence 数据** — 浏览不改变
- **不触发 dogfood 执行** — 仅浏览历史结果
- **不执行 gate 命令** — 仅浏览历史
- **不连接外部服务** — 数据全部本地

### 5.5 测试

| 测试文件 | 覆盖 | 数量 |
|---------|------|------|
| `evidenceBrowser.test.ts` | normalizeVerdictCounts, parseDogfoodFile, buildEvidenceFileIndex | 11 |
| `gateHistory.test.ts` | parseGateHistory, getLatestGateResults, GateResult type | 10 |
| **Phase 6A 新增** | | **21** |

### 5.6 Stop Conditions

| 条件 | 行为 |
|------|------|
| 需要读取 .env / secrets | **HARD_STOP** |
| 需要修改 runtime 状态 | **HARD_STOP** |

---

## 5B. Phase 6B: 多实例历史浏览器 (BLOCKED by B7)

**状态**: BLOCKED。B7 multi-instance 后端就绪后开始。

### 5B.1 目标

扩展 6A 的静态浏览器为多实例历史浏览器：multi-run evidence 时间线、dogfood 趋势、commit 关联。依赖 B7 消除模块级单例以支持多实例数据聚合。

### 5B.2 History Model (保留原设计，待 B7)

```typescript
interface EvidenceHistory {
  id: string;
  capability: string;
  timeline: EvidenceSnapshot[];
}

interface EvidenceSnapshot {
  date: string;
  status: "credible" | "credible-with-caveats" | "partial-credible";
  commit: string;
  dogfoodResult: string;
  notes: string;
}

interface DogfoodHistory {
  results: DogfoodResult[];
  trends: { passTrend: number[]; concernTrend: number[] };
}

interface GateHistory {
  entries: GateRun[];
}

interface GateRun {
  date: string;
  commit: string;
  gate: string;
  result: "pass" | "fail";
  details: string;
}
```

### 5B.3 阻塞条件

1. B7 消除模块级单例 (B7 未启动)
2. Phase 6A COMPLETED ✅
3. `docs/debt/REAL_EVIDENCE_VALIDATION_DEBT.md` 中所有 001-008 为最终状态

### 5B.4 Stop Conditions

| 条件 | 行为 |
|------|------|
| B7 未就绪 | **HARD_STOP** — Phase 6B 不能开始 |
| 需要读取 .env / secrets | **HARD_STOP** |
| 需要修改 runtime 状态 | **HARD_STOP** |

### 5B.5 实现文件 (预估，待 Phase 6B SDD 确认)

| 文件 | 类型 | 内容 |
|------|------|------|
| `tui/src/data/evidenceHistory.ts` | NEW data | Evidence 历史时间线 |
| `tui/src/data/dogfoodHistory.ts` | NEW data | Dogfood 结果历史 + 趋势 |
| `tui/src/components/EvidenceHistoryPanel.tsx` | NEW component | Evidence 历史面板 |
| `tui/src/components/DogfoodHistoryPanel.tsx` | NEW component | Dogfood 历史面板 |

| **Phase 6B 新增** | | **~15** |

---

## 6. Phase 7: 运行时 Event Stream 查看器 (FUTURE)

**状态**: FUTURE。Phase 4/5/6 全部完成 + B7 就绪后开始。

### 6.1 目标

TUI 提供只读 runtime event stream 查看器。agent_log.jsonl tail + dispatcher event 增量展示。不回写、不控制、不触发。

### 6.2 Event Source Contract

```
agent_log.jsonl (append-only, Python runtime 写入)
     │
     ▼
tui/src/data/eventStream.ts (只读 tail)
     │
     ▼
EventStreamPanel (Ink useEffect + setInterval 轮询)
```

- **只读**: `fs.createReadStream` with `start` offset, 不写入
- **Append-only**: 检测文件大小变化 → 读增量 → parse JSONL lines
- **轮询间隔**: 500ms (可配置)
- **不直接控制 runtime**: 不通过 stream 发命令
- **不写 checkpoint**: TUI 不触发 checkpoint save
- **不调用工具**: TUI 不触发 tool invocation

### 6.3 Event Model

```typescript
interface StreamEvent {
  line: number;              // JSONL line number
  timestamp: string;         // ISO 8601
  type: string;              // RuntimeActionType
  status: string;            // success / failed / rejected
  summary: string;           // 一行摘要
  truncated: boolean;        // 内容是否截断
}
```

### 6.4 背压/截断/脱敏策略

- **背压**: 积压 > 1000 条未读 event → 跳过中间, 显示 `[N events skipped]`
- **截断**: 单条 event > 2000 字符 → `[truncated]`
- **脱敏**: 复用现有 log hygiene 规则 (sk-***REDACTED***, Bearer ***REDACTED***)
- **安全**: 不读取 `config/config.yaml` 中的真实 key
- **面板行数上限**: 200 行 (超出滚动, 不无限增长)

### 6.5 Stream Panel

```
┌────────────────────────────────────────────┐
│  Runtime Event Stream (live)  [Paused]     │
│                                            │
│  [2026-06-01T12:00:01] TOOL_GATE allowed  │
│  [2026-06-01T12:00:02] TOOL_INVOKE success │
│  [2026-06-01T12:00:02] TOOL_RESULT success │
│  [2026-06-01T12:00:05] SKILL_SELECT success│
│  ...                                       │
│                                            │
│  Events: 142  |  Filter: [all]  |  Auto   │
│  [Pause] [Resume] [Scroll] [Filter] [Exit] │
└────────────────────────────────────────────┘
```

### 6.6 约束

- **不直接控制 runtime**: Stream 是单向的 (Python→TUI)
- **不写 checkpoint**: TUI 不触发 CHECKPOINT_SAVE
- **不调工具**: TUI 不构造 tool_use block
- **不修改 agent_log.jsonl**: 只读，不追加
- **安全降级**: agent_log.jsonl 不存在 → 显示 "no event stream available"

### 6.7 实现文件 (预估，待 Phase 7 SDD 确认)

| 文件 | 类型 | 内容 |
|------|------|------|
| `tui/src/data/eventStream.ts` | NEW data | JSONL tail reader, 增量解析, 背压控制 |
| `tui/src/components/EventStreamPanel.tsx` | NEW component | Stream 展示面板, 暂停/恢复/过滤 |
| `tui/src/data/eventFilter.ts` | NEW data | Event type 过滤, redaction |

### 6.8 Stop Conditions

| 条件 | 行为 |
|------|------|
| Event 包含真实 API key | **HARD_STOP** — 停止展示, 不 commit key |
| agent_log.jsonl 路径指向非预期位置 | **HARD_STOP** |
| 尝试写入 agent_log.jsonl | **HARD_STOP** |
| 尝试构造 tool_use | **HARD_STOP** |

### 6.9 测试计划 (预估)

| 测试文件 | 覆盖 | 预估数量 |
|---------|------|---------|
| `eventStream.test.ts` | tail 读取, 增量解析, 背压, 脱敏, 安全 | 8 |
| `eventFilter.test.ts` | 类型过滤, 空流, 损坏 JSONL | 4 |
| **Phase 7 新增** | | **~12** |
| **总计** | | **~200** |

---

## 7. AutoRun Continuous Execution Contract

### 7.1 连续执行许可

AutoRun 在满足以下所有条件时，可连续执行 Phase 4 → Phase 5 → Phase 6A (Phase 6B/7 blocked):

1. 每个 Phase gate 全部通过
2. 无 HARD_STOP 触发
3. 无需新增主要依赖 (npm install 仅允许 `@types/*` dev 依赖)
4. 无需 Python runtime core 变更
5. 无需读取 .env / secrets
6. 无 destructive commands
7. Context ≥ 10% (低于此阈值: 写 handoff, 跑最小 gates, commit/push safe files, 停止)

### 7.2 禁止行为

AutoRun **不得**:
- 跳过 SDD/TDD/Review/Debug/Gate 任一阶段
- Push 失败 gates
- 进入 B7 implementation
- 将 TUI 设为默认入口 (Default Entry Gate 全部通过前)
- 新增第二条 runtime flow
- 绕过 ToolRuntimeMediator / TOOL_GATE

### 7.3 Phase Transition Gate (每 Phase 完成后强制执行)

| # | 条件 | 检查方法 |
|---|------|---------|
| 1 | 当前 phase tests 全部 PASS | `cd tui && npm test` |
| 2 | TypeScript 编译 clean | `cd tui && npm run typecheck` |
| 3 | git diff --check clean | `git diff --check` |
| 4 | Phase 1-3 回归 133/133 | `cd tui && npm test` |
| 5 | 文档已更新 (PROJECT_STATUS, PROGRESS_LEDGER) | 手动检查 |
| 6 | 无 HARD_STOP | 手动检查 |
| 7 | commit/push 完成 | `git log --oneline -1` |
| 8 | 下一个 Phase roadmap section 为 READY | 读 roadmap §3-§6 |
| 9 | 无 uncommitted/dirty 非预期文件 | `git status --short` |
| 10 | 未跳过 SDD/TDD/Gate | review commit history |

不满足任一条件 → **停止**, 修复后再继续。

### 7.4 Failed Gate Retry Limit

- 同一 Phase 中同一 gate 失败 ≥ 2 次 → **HARD_STOP**
- 回退到上游阶段 (SDD → TDD → Implementation → Gate)
- 第三次尝试前必须写 root cause analysis
- 不得为了通过 gate 而降低断言

### 7.5 Context Low Handoff

Context < 10% 时:
1. 立即完成当前 task (不开始新 task)
2. 写 handoff: `docs/handoff/<date>-b8-phase<N>-handoff.md`
3. 包含: 当前 phase, 已完成 tasks, 未完成 tasks, 失败 gate, next steps
4. 跑最小 gates (`npm test`, `tsc --noEmit`)
5. 如 safe: `git add` + `git commit` + `git push`
6. 停止

### 7.6 When to Stop and Ask User

| 场景 | 行为 |
|------|------|
| 需要重大架构决策 (非 roadmap 已有) | **STOP** — 问用户 |
| 需要新增 npm 依赖 (非 `@types/*`) | **STOP** — 问用户 |
| 需要修改 Python runtime core path | **STOP** — 问用户 |
| 需要读取 .env / real API key | **STOP** — 问用户 |
| Gate 连续失败 2 次 | **STOP** — 报告 root cause |
| Context < 10% | **STOP** — handoff |
| B7 入口条件触发 | **STOP** — B7 不在本轮范围 |
| Default Entry Gate 触发 | **STOP** — 需显式用户确认 |
| TUI exec 路径遇到白名单外命令 | **HARD_STOP** |

---

## 8. 依赖链与风险

### 8.1 依赖链

```
Phase 1 ──► Phase 2 ──► Phase 3 ──► Phase 4 ──► Phase 5 ──► Phase 6A ──► Phase 6B ──► Phase 7
                                                                           ▲
                                                                      B7 后端就绪 (BLOCKED)
```

- **Phase 4** 不依赖外部条件（纯 TUI 前端 + node child_process）
- **Phase 5** 依赖 Phase 4 的命令执行基础设施
- **Phase 6A** 静态浏览器，不依赖 B7 (COMPLETED)
- **Phase 6B** 多实例历史浏览器，依赖 B7 multi-instance 后端 (BLOCKED)
- **Phase 7** 依赖 Phase 4/5/6A/6B 全部完成 (FUTURE)

### 8.2 风险矩阵

| 风险 | 概率 | 影响 | Phase | 缓解 |
|------|------|------|-------|------|
| Ink useInput 中文 IME 文本输入截断 | 中 | 中 | Phase 4+ | Phase 4 早期验证；必要时切换到 raw stdin 模式 |
| child_process exec 白名单绕过 | 低 | 高 | Phase 4 | 编译时检查 no dynamic exec；白名单 hardcoded |
| agent_log.jsonl 写入速度 > 轮询速度 | 低 | 低 | Phase 5 | 增量读取 + debounce 重渲染 |
| B7 架构变更破坏 TUI 数据契约 | 低 | 高 | Phase 6B | 预留 B7 field reservation (SDD §11) |
| Node.js 版本升级导致 Ink 不兼容 | 低 | 中 | 全 Phase | 锁定 Ink 5.x + React 18 |
| Phase 4+ 修改破坏 Phase 1-3 回归 | 中 | 高 | 全 Phase | 133+ tests 回归套件；只扩展不重写 |
| child_process 引入新子进程模式 | 低 | 高 | Phase 4 | 编译时扫描 `spawn`/`fork`/`execFile` |

---

## 9. 关键决策记录

| ID | 决策 | 日期 | 理由 |
|----|------|------|------|
| D-001 | TUI 为未来默认入口，CLI 为显式 fallback | 2026-05-31 | Phase 3 确立；CLI 永不删除 |
| D-002 | 不立即切换 TUI 为默认入口 | 2026-05-31 | Default Entry Readiness checklist 全部通过后才切换 |
| D-003 | Phase 4 启 confirmation gate + dry-run 优先 | 2026-06-01 | 安全命令执行的最小可行方案 |
| D-004 | Phase 6 拆分为 6A/6B | 2026-05-31 | 6A 静态浏览器不依赖 B7，可立即做；6B 多实例历史需 B7 消除模块级单例 |
| D-005 | 不引入 WebSocket/SSE 做实时流 | 2026-06-01 | Phase 7 用文件 tail + polling 保持依赖最小化 |
| D-006 | 不把 TUI 做成第二 runtime | 2026-05-31 | TUI 是 UI 层，不改 Python runtime 行为 |
| D-007 | TUI 不重写 AutoRun | 2026-06-01 | TUI 通过固定命令模板接入，不实现 AutoRun 逻辑 |
| D-008 | AutoRun 连续执行许可 | 2026-06-01 | Phase 4→5→6A 可连续，Phase 6B/7 因 B7 阻塞不连续 |
| D-009 | Phase Transition Gate 10 项检查 | 2026-06-01 | 每 Phase 完成后强制执行 |
| D-010 | Failed gate retry limit = 2 | 2026-06-01 | 同一 gate 连续 2 次失败 → HARD_STOP + root cause |
| D-011 | Context < 10% handoff | 2026-06-01 | 写 `docs/handoff/`, 最小 gates, safe commit/push, 停止 |
| D-012 | Phase 6A 静态浏览器 | 2026-06-01 | JSON 解析 + gate history 文本解析，不依赖 B7，21 tests |

---

## 10. 门禁矩阵

| Gate | Phase 1-3 | Phase 4 | Phase 5 | Phase 6A | Phase 6B | Phase 7 |
|------|----------|---------|---------|---------|---------|---------|
| `npx tsc --noEmit` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `cd tui && npm test` | ✅ 133 | ✅ 188 | ✅ 206 | ✅ 241 | ✅ TBD | ✅ TBD |
| Phase 1-3 regression | — | ✅ 133 | ✅ 133 | ✅ 133 | ✅ 133 | ✅ 133 |
| git diff --check | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 白名单扫描 | N/A | ✅ | ✅ | ✅ | ✅ | ✅ |
| no .env access | N/A | ✅ | ✅ | ✅ | ✅ | ✅ |
| no new deps | N/A | ✅ | ✅ | ✅ | ✅ | ✅ |
| `npm start` smoke | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| CLI 独立运行 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| AutoRun Contract (Phase Transition) | N/A | ✅ | ✅ | ✅ | ✅ | ✅ |

---

## 11. 约束与不做列表

### 11.1 全阶段约束

1. 不把 TUI 做成第二 runtime（不改 Python core path）
2. 不删除 CLI / 不废弃 CLI
3. 不做 Web UI
4. 不引入数据库
5. 不引入 WebSocket / SSE
6. 不读取 .env（除非用户显式确认后执行）
7. 不 commit `config/config.yaml`
8. 不进入 B7 implementation
9. 不把 TUI 立即设为默认入口
10. 不绕过 AutoRun workflow
11. 不执行 destructive commands (force push, rm -rf, hard reset)
12. 不在 gate 失败时 commit/push
13. 不在 context < 10% 时开始新 task

### 11.2 Phase 4 专属约束

14. 所有 exec 路径限于硬编码白名单
15. destructive actions 需 double-confirmation
16. audit log append-only，不可删除

### 11.3 明确不做

- B7 multi-instance implementation
- Python runtime 架构变更
- real-time WebSocket server
- 数据库持久化
- TUI 插件系统
- 远程访问 / Web-based TUI
- 移动端适配
- 真实 API 调用（TUI 层面）

---

## 11.4 B8 Polish / Default Workbench Readiness Loop

### 目标

在不进入 B7、不做实时流、不改 runtime 的情况下，把 TUI 打磨成更接近默认工作台。

### 可做事项

| 优先级 | 项目 | 描述 | 依赖 |
|--------|------|------|------|
| P1 | AuditLogPanel | auditLog.ts rotation 已就绪，UI 未暴露 — 新增只读 audit history 视图 | 无 (auditLog.ts 已有) |
| P1 | DefaultEntryReadinessPanel | 展示 TUI 距默认入口还差什么, Phase 6B/7 debt, CLI fallback retained | 无 (静态配置) |
| P2 | Empty/unknown/stale states | EvidenceBrowserPanel/DocsConsistencyPanel 的 edge case 展示更清晰 | 无 |
| P2 | Keyboard help | 导航提示、快捷键说明, 让 TUI 更像可用工作台 | 无 |
| P2 | Layout polish | panel spacing, selected state, terminal resize behavior (如 Ink 支持) | 无 |
| P3 | Command UX polish | safe/blocked/confirmation 分类更清楚, command preview/result panel 更易读 | 无 |
| P3 | Docs consistency polish | current/historical/superseded 状态展示, next action 更清晰 | 无 |
| P3 | Tests polish | malformed data tests, no .env access tests, navigation state tests | 无 |

### 明确不做

- 不进入 B7
- 不做 Phase 6B / Phase 7
- 不执行真实 AutoRun
- 不调用真实 API
- 不读取 .env
- 不改 Python runtime
- 不做 Web UI
- 不把 TUI 设为默认入口
- 不新增大型依赖

### Polish Loop 1 (当前)

1. **AuditLogPanel** — 只读 audit history 视图, 不执行命令, 不写 runtime state
2. **DefaultEntryReadinessPanel** — 静态 checklist, 展示已完成/blocked/待审核
3. **Better empty states** — EvidenceBrowserPanel 无文件时, DocsConsistencyPanel stale 时
4. **Keyboard hints** — footer 增强, 可选 help overlay

预计新增 tests: ~15。预计总测试数: ~242。

---

## 12. 文档导航

| 想了解 | 读这里 |
|--------|--------|
| B8 SDD (Phase 1-3 设计) | `docs/design/b8-ts-tui-workbench-sdd.md` |
| 当前项目状态 | `docs/PROJECT_STATUS.md` |
| 进度历史 | `docs/PROGRESS_LEDGER.md` |
| B8 路线（本文件） | `docs/roadmap/b8-tui-workbench-roadmap.md` |
| B8 Technical Debt (6B/7) | `docs/debt/b8-tui-workbench-technical-debt.md` |
| 工程流程 | `docs/dev/AUTO_RUN_WORKFLOW.md` |
| 真实证据债务 | `docs/debt/REAL_EVIDENCE_VALIDATION_DEBT.md` |
| TUI 源码 | `tui/src/` |
| TUI 测试 | `tui/src/__tests__/` |

---

## 13. 版本历史

| 日期 | 变更 |
|------|------|
| 2026-06-01a | 初始版本 — B8 Roadmap / Default Entry Readiness Review |
| 2026-06-01b | AutoRun Readiness Hardening — Phase 4/5 补全可执行细节 (命令白名单/黑名单/确认模型/dry-run/audit log/result panel/过渡 gate/stop conditions), Phase 6/7 补全数据模型/约束/测试计划, 新增 AutoRun Continuous Execution Contract (§7) + Phase Transition Gate + Failed Gate Retry Limit + Context Low Handoff |
| 2026-06-01c | Phase 6A COMPLETED — 拆分 Phase 6 为 6A (静态浏览器) + 6B (B7-dependent 多实例历史); 实现 evidenceBrowser.ts, gateHistory.ts, EvidenceBrowserPanel, DogfoodDetailPanel; 21 new tests; 241/241 tests PASS (after Polish Loop); wired into Dashboard evidence view with ↑↓ navigation |
| 2026-06-01d | B8 Completion Review — `docs/reviews/b8-tui-workbench-completion-review.md`。阶段性收口审查通过。260/260 tests PASS。Phase 6B/7 DEFERRED。TUI default entry NOT ACTIVATED。|
