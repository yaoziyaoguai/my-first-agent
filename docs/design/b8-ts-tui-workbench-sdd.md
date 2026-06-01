# B8 TypeScript TUI Workbench — SDD

**创建日期**: 2026-05-31
**最后更新**: 2026-06-01 (Phase 3 SDD — Default Workbench Readiness)
**状态**: Phase 1 COMPLETED, Phase 2 COMPLETED, Phase 3 COMPLETED (133/133 tests PASS)
**类型**: Architecture Extension Loop — 新跨领域关注点

---

## 1. Vision

**最终形态**: TUI 替代 CLI 成为 First Agent 的默认交互入口。开发者通过终端工作台完成所有工程操作（状态查看、命令执行、workflow 编排），CLI 保留为底层能力和 fallback。

**Phase 1 (COMPLETED — `eba77ad`)**: 只读静态仪表盘 — 5 面板 (Overview/EvidenceStatus/Workflow/Gate/EvidencePreview)。

**Phase 2 (COMPLETED — `3c8e178`)**: TUI command shell + Development Workflow launcher（Coding Agent 工程 workflow 入口, provisional dev-only）。CommandCatalog (8 命令, 5 级 SafetyModel), CommandPanel (分组 + ↑↓ 导航), NextActionPanel, CommandPreview (overlay, 不执行)。

**Phase 3 (本轮): TUI Default Workbench Readiness**。TUI 从单屏 dashboard 升级为多视图工作台——7 视图切换、TaskCenter、WorkflowState 解析、EvidenceDetail 展开、DocsConsistency 检测、CommandCatalog v2（workflow stage 绑定）。确立 TUI 为**未来默认入口**（不立即切换），CLI 为**显式 fallback**（永不删除）。定义 Default Entry Readiness Checklist（切换前必须通过）。**仍 preview-only，不执行命令，不调用 API。**

**Phase 3 七大能力域**:
1. Navigation Model — 7 视图切换（Overview/Evidence/Workflow/Commands/Tasks/Gates/Docs）
2. TaskCenterPanel — B8/B7 phase 状态矩阵
3. WorkflowState Model — 从 PROJECT_STATUS/PROGRESS_LEDGER/SDD 解析
4. EvidenceDetail Model — 001-008 详情（status/dogfood/commit/caveats/nextAction）
5. DocsConsistency Model — 关键文档存在性检测
6. CommandCatalog v2 — 命令绑定 workflow stage + risk level
7. Default Entry Readiness — 切换前必须通过的 checklist

**后续 Phase (Phase 4-7 路线图)**: 详见 `docs/roadmap/b8-tui-workbench-roadmap.md`。
- Phase 4: 安全命令执行（confirmation gate + dry-run 优先）
- Phase 5: Development Workflow / Review Panel (provisional dev-only, may be removed)
- Phase 6: 多实例监控（B7 后端就绪后）
- Phase 7: 完整 TUI Agent Workbench（CLI 降级为 fallback，TUI 为主入口）

---

## 2. Phase 1 Scope

### 2.1 目标

一个可通过 `npm start` 启动的终端仪表盘，展示 5 个只读面板：

| 面板 | 名称 | 数据源 | 核心信息 |
|------|------|--------|---------|
| Panel 1 | **Overview** | `docs/PROJECT_STATUS.md` (Section 0-1) | Score、credible 分布、verdict、推荐下一步 |
| Panel 2 | **EvidenceStatus** | `docs/PROJECT_STATUS.md` (§0 Corrected REAL-EVIDENCE Closure Credibility) | 001-008 每条的状态、caveats、分数 |
| Panel 3 | **Workflow** | `docs/PROGRESS_LEDGER.md` | 最近里程碑列表、当前 loop 状态 |
| Panel 4 | **Gate** | git status + git log | dirty/untracked 文件、最近 commits、branch 信息 |
| Panel 5 | **EvidencePreview** | `docs/dogfood/*.json` (最新 N 个) | 最新 dogfood 结果的 PASS/FAIL/CONCERN 摘要 |

### 2.2 非功能需求

- 启动时间 < 2 秒
- 文件读取失败时不崩溃，面板显示错误标记
- 支持 80 列终端宽度
- 所有数据源为本地文件，不发起网络请求

### 2.3 Phase 2: Command Shell + Workflow Launcher

#### 2.3.1 目标

TUI 从只读 observer 升级为交互式 command shell：

1. **CommandCatalog** — 定义可用命令列表（Development Workflow / status / audit / dogfood / gates / docs check），仅展示 metadata，不执行
2. **CommandPanel** — 展示命令列表、描述、risk level、是否需要 confirmation、是否 currently executable
3. **NextActionPanel** — 从 PROJECT_STATUS 读取当前推荐下一步
4. **CommandPreview** — 选中命令后展示将要执行的 shell command 或 prompt，Phase 2 只 preview
5. **SafetyModel** — 五级安全分级: read-only / preview-only / requires-confirmation / disabled / future-executable

#### 2.3.2 安全模型

| 级别 | 含义 | Phase 2 行为 | 示例 |
|------|------|-------------|------|
| `read-only` | 纯数据展示 | 直接展示 | Overview, EvidenceStatus |
| `preview-only` | 展示命令但不可执行 | 展示 shell command 文本 | status check, gate check |
| `requires-confirmation` | 需显式确认 | 展示命令 + 注明 "requires confirmation" | dogfood run |
| `disabled` | Phase 2 不可执行 | 灰显 + 注明 "not available in Phase 2" | git push, real API call |
| `future-executable` | 后续 Phase 支持 | 灰显 + 注明 "planned Phase 3+" | agent run, deploy |

**Phase 2 硬约束**:
- 不执行任何 shell 命令（所有 `exec` 路径编译时不可达）
- 不读取 `.env`
- 不调用真实 API
- 不启动真实 agent run
- 不执行 destructive actions (git push / rm / force)
- TUI 不是第二 runtime — 不绕过 Python main path

#### 2.3.3 TUI ↔ CLI 关系

```
┌─────────────────────────────────────────┐
│              TUI (默认入口)              │
│  ┌──────────┐  ┌──────────┐            │
│  │ Command  │  │ Next     │            │
│  │ Panel    │  │ Action   │            │
│  └──────────┘  └──────────┘            │
│  ┌──────────────────────┐              │
│  │   Command Preview    │              │
│  │ (show, NOT execute)  │              │
│  └──────────────────────┘              │
│         │                              │
│         │ "copy & paste to CLI"        │
│         ▼                              │
│  ┌──────────────────────┐              │
│  │  CLI (底层 fallback)  │              │
│  │  python main.py ...   │              │
│  └──────────────────────┘              │
└─────────────────────────────────────────┘
```

- TUI 是**未来默认入口** — 用户首先打开 TUI
- CLI 是**底层能力和 fallback** — TUI 出问题时回退到 CLI
- Phase 2 用户流程: TUI 浏览命令 → 复制命令 → 粘贴到 CLI 执行
- Phase 2 不废弃 CLI，不删除任何 CLI 功能

---

## 3. Technology Decisions

| 决策 | 选择 | 理由 |
|------|------|------|
| **Runtime** | Node.js v20+ (TypeScript 5.x) | 用户环境已有 Node v20.20.2 |
| **TUI 框架** | Ink 5 + React 18 | 最成熟的 React-based TUI 框架，组件模型熟悉 |
| **构建工具** | tsx (直接执行 TS，Phase 1 不编译) | 最小化工具链，Phase 1 只读无性能瓶颈 |
| **CLI 启动** | `npm start` → `tsx src/main.tsx` | 一行启动，不需要全局安装 |
| **Markdown 渲染** | 手工轻量解析 + ink 原生组件 | Phase 1 数据源结构固定，不需要通用 MD parser |
| **JSON 读取** | Node fs.readFileSync | 同步读取匹配启动时一次性加载模式 |
| **Git 数据** | `git status --short` + `git log --oneline -n 10` 子进程 | 不引入 git 库依赖 |
| **测试框架** | Vitest | 快、TypeScript 原生、与 Vite 生态一致 |

### 3.1 不引入的依赖

- React DOM / 浏览器端渲染
- Express / HTTP server
- 数据库
- WebSocket / SSE client
- git 库 (nodegit/isomorphic-git)
- 外部 API client

---

## 4. Project Structure

```
tui/
├── package.json
├── tsconfig.json
├── vitest.config.ts
├── src/
│   ├── main.tsx                  # 入口: render(<Dashboard />)
│   ├── components/
│   │   ├── Dashboard.tsx         # 顶层布局: 5 面板 flexbox
│   │   ├── OverviewPanel.tsx     # Panel 1
│   │   ├── EvidenceStatusPanel.tsx # Panel 2
│   │   ├── WorkflowPanel.tsx     # Panel 3
│   │   ├── GatePanel.tsx         # Panel 4
│   │   └── EvidencePreviewPanel.tsx # Panel 5
│   ├── data/
│   │   ├── projectStatus.ts      # PROJECT_STATUS.md 解析
│   │   ├── progressLedger.ts     # PROGRESS_LEDGER.md 解析
│   │   ├── dogfoodResults.ts     # dogfood JSON 解析
│   │   └── gitInfo.ts            # git status/log 子进程
│   ├── types.ts                  # 共享类型定义
│   └── __tests__/
│       ├── projectStatus.test.ts
│       ├── progressLedger.test.ts
│       ├── dogfoodResults.test.ts
│       └── gitInfo.test.ts
└── README.md
```

### 4.1 设计约束

- `data/` 层不依赖 React/Ink — 纯函数，输入文件路径，输出结构化数据
- `components/` 层只依赖 `data/` 和 `types.ts` — 不做文件 IO
- `main.tsx` 负责文件 IO + 传给组件 props
- 所有路径相对 `tui/` 包根解析到仓库根 (`..`)

---

## 5. Data Layer Design

### 5.1 `projectStatus.ts`

```typescript
interface ProjectStatus {
  lastUpdated: string;
  score: string;               // "4.5/5 conservative baseline"
  credibleCount: string;       // "7/8 credible + 1/8 credible-with-caveats"
  overallVerdict: string;      // 总体判断段落
  recommendedNext: string;     // 推荐下一步
  realEvidenceRows: RealEvidenceRow[];
}

interface RealEvidenceRow {
  id: string;                  // "REAL-EVIDENCE-001"
  capability: string;
  status: "credible" | "credible-with-caveats" | "partial-credible";
  notes: string;
}
```

**解析策略**: 基于 Section 标记的行级解析。
- `## 0.` 部分: 解析 Current Verdict 表格 + REAL-EVIDENCE closure credibility 表格
- `## 2.` 部分: 解析 "推荐下一步" 段落
- 不引入通用 Markdown parser

### 5.2 `progressLedger.ts`

```typescript
interface ProgressLedger {
  milestones: Milestone[];
}

interface Milestone {
  date: string;                // "2026-05-31"
  title: string;               // milestone 名称
  commit: string;              // commit hash (可为空)
  summary: string;             // 简述
}
```

**解析策略**: 日期标题行 + 表格行 `| **milestone** | commit | 简述 |`

### 5.3 `dogfoodResults.ts`

```typescript
interface DogfoodResult {
  fileName: string;
  pass: number;
  fail: number;
  concern: number;
  summary: string;
}
```

**解析策略**: 读取 `docs/dogfood/` 下最新 5 个 `.json` 文件，按 mtime 排序。

### 5.4 `gitInfo.ts`

```typescript
interface GitInfo {
  branch: string;
  headCommit: string;
  recentCommits: CommitInfo[];
  dirtyFiles: string[];
}

interface CommitInfo {
  hash: string;
  message: string;
}
```

**解析策略**: 子进程执行 `git` 命令，解析 stdout。

### 5.5 `commandCatalog.ts` (Phase 2 NEW)

```typescript
type SafetyLevel = "read-only" | "preview-only" | "requires-confirmation" | "disabled" | "future-executable";

interface CommandDefinition {
  id: string;                    // "autorun", "status", "audit", "dogfood", "gates"
  name: string;                  // 用户可见名称
  description: string;           // 简述
  category: "diagnostics" | "execution" | "workflow" | "gates" | "docs";
  safetyLevel: SafetyLevel;
  requiresConfirmation: boolean;
  executableInPhase2: boolean;
  shellCommand?: string;         // 对应的 CLI 命令 (preview 用)
  relatedSkills?: string[];      // 关联的 Coding Agent dev workflow skills
  riskNote?: string;             // 风险说明
}

interface CommandCatalog {
  version: string;
  commands: CommandDefinition[];
}
```

**数据源**: 硬编码 JSON 配置文件 `tui/src/data/commands.json`，不在代码中动态生成。
Phase 2 不执行任何命令，只展示 metadata + shell command preview。

**Phase 2 命令清单**:

| ID | Name | Category | Safety | Phase 2 行为 |
|----|------|----------|--------|-------------|
| `autorun` | Dev Workflow (provisional) | workflow | `requires-confirmation` | preview-only |
| `status` | Project Status | diagnostics | `preview-only` | preview-only |
| `audit` | Full System Audit | diagnostics | `requires-confirmation` | preview-only |
| `dogfood` | Dogfood Run | execution | `requires-confirmation` | preview-only |
| `gates` | Code Gates | gates | `preview-only` | preview-only |
| `docs-check` | Docs Consistency | docs | `preview-only` | preview-only |
| `agent-run` | Agent Run | execution | `disabled` | disabled (planned Phase 4+) |
| `deploy` | Deploy | execution | `disabled` | disabled (future Phase) |

#### 2.3.4 Phase 3: Default Workbench Readiness

**目标**: TUI 从单屏 dashboard 升级为完整多视图工作台，确立 TUI 为未来默认入口，CLI 为显式 fallback。

**行业参考**:
- **Hermes Agent** (OpenClaw): subagent worktree 隔离 + 结构化输出 + TUI 状态面板
- **Pi TUI** (OpenClaw): Ink-based 终端工作台，command shell 模式
- **Claude Code**: 终端内 agent 交互，slash command 模式
- 共同模式: 终端优先 → 结构化面板 → 命令/状态分离 → fallback CLI 保留

**7 大能力域**:

1. **Navigation Model** — 多 view 切换
   - Views: Overview | Evidence | Workflow | Commands | Tasks | Gates | Docs
   - `←` / `→` 或数字键 1-7 切换视图
   - NavigationBar 组件展示当前 view 及可用 views
   - View state model: `{ currentView: ViewId, views: ViewDef[] }`

2. **TaskCenterPanel** — 开发任务中心 (Coding Agent engineering phase status)
   - 展示 B8/B7 各 Phase 及其状态:
     | Phase | 状态 |
     |-------|------|
     | B8 Phase 1 (Static Dashboard) | completed |
     | B8 Phase 2 (Command Shell) | completed |
     | B8 Phase 3 (Default Workbench Readiness) | recommended (current) |
     | B8 Phase 4 (Safe Execution) | deferred |
     | B8 Phase 5 (Real-time Stream) | deferred |
     | B7 Multi-instance Readiness | blocked |
   - 每项展示: status label + why 说明
   - 数据源: 硬编码 JSON 配置 `tui/src/data/tasks.json`

3. **WorkflowState Model** — 工作流状态解析
   - 从 PROJECT_STATUS / PROGRESS_LEDGER / B8 SDD 解析:
     - currentStage: "B8 Phase 3"
     - completedMilestones: [...]
     - deferredItems: [...]
     - nextRecommended: "B8 Phase 3 Default Workbench Readiness"
   - 纯数据层，不依赖 Claude task list

4. **Evidence Detail Model** — 001-008 详情
   - 扩展现有 RealEvidenceRow 为 EvidenceDetail:
     - status, capability, latestDogfood, latestCommit, caveats, nextAction
   - 数据源: 硬编码 JSON 配置 `tui/src/data/evidenceDetails.json`
   - Phase 3 先做数据模型 + 简单列表 UI

5. **Docs Consistency Model** — 文档一致性
   - 检查关键文档存在性:
     - PROJECT_STATUS.md, PROGRESS_LEDGER.md
     - REAL_EVIDENCE_VALIDATION_DEBT.md
     - B8 SDD
   - 状态: present / missing / unknown
   - 数据层: `checkDocsExist()` 纯函数 + shell command preview

6. **CommandCatalog v2** — 命令与 workflow stage 绑定
   - 扩展现有 CommandCatalog: 每个 command 绑定对应的 workflow stage
   - 新增 `workflowStage` 字段: "audit" | "remediation" | "implementation" | "dogfood" | "gates" | "docs" | "any"
   - 新增 `riskLevel` 字段: "low" | "medium" | "high"
   - 新增命令: "Start B8 Phase 4", "Open final audit prompt", "Run docs check"
   - 仍 preview-only

7. **Default Entry Readiness** — 切换 TUI 为默认入口的前置条件
   - 不立即切换；定义 checklist，后续 Phase 满足全部条件后才切换
   - Checklist (Phase 3 期间记录，不强制全部通过):
     - [ ] 7 视图导航可用且无 crash
     - [ ] TaskCenter 正确反映 B8/B7 状态
     - [ ] WorkflowState 解析与 PROJECT_STATUS 一致
     - [ ] EvidenceDetail 001-008 数据与 docs/debt 一致
     - [ ] DocsConsistency 正确检测所有关键文档
     - [ ] CommandCatalog v2 所有命令有 workflow stage 绑定
     - [ ] 中文 IME 输入就绪（见 §2.3.5）
     - [ ] 74 Phase 1+2 tests 全部 PASS（无回归）
     - [ ] ~37 Phase 3 tests 全部 PASS
     - [ ] tsc --noEmit 零错误
     - [ ] CLI 仍可独立运行（TUI 不破坏 CLI）
     - [ ] npm start 成功渲染所有新面板

**中文 IME 输入就绪** (§2.3.5):
- Ink `useInput` 处理原始按键，中文 IME 组合输入（拼音 → 汉字）可能被拆分为多个 input 事件
- Phase 3 仅使用单键导航（←/→/1-7/q/Esc），不受 IME 影响
- 后续 Phase 如需要文本输入（搜索、过滤），需验证 IME 组合输入不会被错误拦截
- 当前状态: **不阻塞** — 单键导航不经过 IME pipeline

**Phase 3 硬约束 (13 项 "不做")**:
1. 不执行任何 shell 命令
2. 不读取 .env / 不调用真实 API
3. 不改 Python runtime / core path
4. 不引入大型依赖
5. 不把 TUI 做成第二 runtime
6. 不删除 CLI / 不废弃 CLI
7. 不把 TUI 立即设为唯一默认入口
8. 不做 Web UI
9. 不进入 B7 multi-instance implementation
10. 不做 real-time evidence stream
11. 不执行 Coding Agent workflow 命令
12. 不启动 agent run
13. 不写 checkpoint

**Phase 3 数据层新增文件**:
```
tui/src/
├── data/
│   ├── navigation.ts       # NavigationState model
│   ├── tasks.ts             # TaskCenter data (JSON)
│   ├── tasks.json           # B8/B7 phase status 配置
│   ├── workflowState.ts     # WorkflowState parser
│   ├── evidenceDetails.ts   # EvidenceDetail model
│   ├── evidenceDetails.json # 001-008 详情配置
│   └── docsConsistency.ts   # Docs check model
├── components/
│   ├── NavigationBar.tsx    # View switcher
│   ├── TaskCenterPanel.tsx  # Task center
│   ├── EvidenceDetailPanel.tsx # 001-008 详情
│   └── DocsConsistencyPanel.tsx # Docs status
```

---

## 6. Component Design

### 6.1 Dashboard 布局

```
┌──────────────────────────────────────────────────────────────┐
│  First Agent Workbench — B8-lite                    main     │
│                                                              │
│  ┌─────────────────────────┐  ┌────────────────────────────┐│
│  │      Overview           │  │     Evidence Status        ││
│  │                         │  │                            ││
│  │  Score: 4.5/5           │  │  001 Memory      credible  ││
│  │  7/8 cred + 1/8 caveat  │  │  002 Skill       credible  ││
│  │                         │  │  003 Tools       credible  ││
│  │  推荐: B8-lite TS TUI   │  │  ...                       ││
│  └─────────────────────────┘  └────────────────────────────┘│
│                                                              │
│  ┌──────────────────────────────────────────────────────────┐│
│  │                    Workflow                              ││
│  │  2026-05-31  003 Loop 8  29aafd8  003→credible          ││
│  │  2026-05-31  002 SDD vNext  —     SPEC/SDD complete     ││
│  └──────────────────────────────────────────────────────────┘│
│                                                              │
│  ┌─────────────────────────┐  ┌────────────────────────────┐│
│  │      Gate               │  │   Evidence Preview         ││
│  │  branch: main           │  │   real-evidence-003:       ││
│  │  HEAD: 891d002          │  │   13P / 0F / 4C            ││
│  │  dirty: 4 untracked     │  │   real-evidence-008:       ││
│  │                         │  │   14P / 0F / 0C            ││
│  └─────────────────────────┘  └────────────────────────────┘│
└──────────────────────────────────────────────────────────────┘
```

### 6.2 颜色方案

- PASS / credible: green
- CONCERN / credible-with-caveats: yellow
- FAIL / dirty: red
- normal text: white/default
- 分隔线: dim/gray

### 6.3 交互 (Phase 1)

- `q` / `Ctrl+C`: 退出
- Tab 键: 切换面板焦点（高亮边框）— 可选，Phase 1 不做

### 6.4 CommandPanel (Phase 2 NEW)

```
┌────────────────────────────────────────────────────────────┐
│  Commands                                                  │
│                                                            │
│  ▶ autorun        Dev Workflow (prov)     [requires-confirm]  │
│    status         Project Status       [preview-only]      │
│    audit          Full System Audit    [requires-confirm]  │
│    dogfood        Dogfood Run          [requires-confirm]  │
│    gates          Code Gates           [preview-only]      │
│    docs-check     Docs Consistency     [preview-only]      │
│    agent-run      Agent Run            [disabled - Ph 4+]  │
│    deploy         Deploy               [disabled - future] │
│                                                            │
│  ↑↓ navigate  Enter preview  q quit                       │
└────────────────────────────────────────────────────────────┘
```

- 展示所有可用命令，按 category 分组
- 当前选中行高亮（`▶` 前缀）
- safety level 用颜色标记: preview-only=cyan, requires-confirmation=yellow, disabled=dim
- `disabled` 命令灰显，不可选中
- `↑` / `↓` 导航，`Enter` 进入 CommandPreview

### 6.5 NextActionPanel (Phase 2 NEW)

```
┌────────────────────────────────────────────────────────────┐
│  Next Action                                               │
│                                                            │
│  📋 B8-lite Phase 2: TUI command shell + Dev Workflow     │
│                                                            │
│  Why: TUI 从只读 observer 升级为交互式工作台入口            │
│                                                            │
│  Source: PROJECT_STATUS.md §推荐下一步                      │
└────────────────────────────────────────────────────────────┘
```

- 展示 PROJECT_STATUS 中当前推荐下一步
- 只读，从 `parseProjectStatus()` 的 `recommendedNext` 字段获取
- 作为用户决策参考，不是自动触发器

### 6.6 CommandPreview (Phase 2 NEW)

```
┌────────────────────────────────────────────────────────────┐
│  Command Preview — autorun (dev workflow)                   │
│                                                            │
│  Safety:       requires-confirmation                       │
│  Phase 2:      preview-only (copy & paste to CLI)          │
│  Risk:         启动 Coding Agent 工程 loop，可能执行 git push│
│                                                            │
│  Shell command:                                            │
│  cd /path/to/repo && python main.py auto-run               │
│                                                            │
│  ────────────────────────────────────────────────────────  │
│  ⚠  Phase 2 不执行此命令。请复制到终端手动运行。           │
│                                                            │
│  Esc back   q quit                                        │
└────────────────────────────────────────────────────────────┘
```

- 展示选中命令的完整 metadata
- 展示等价 shell command
- 明确标记 "Phase 2 不执行"
- `Esc` 返回 CommandPanel

### 6.7 Phase 2 整体布局

```
┌──────────────────────────────────────────────────────────────┐
│  First Agent Workbench — B8                      main        │
│                                                              │
│  ┌─────────────────────────┐  ┌────────────────────────────┐│
│  │      Overview           │  │     Evidence Status        ││
│  └─────────────────────────┘  └────────────────────────────┘│
│                                                              │
│  ┌─────────────────────────┐  ┌────────────────────────────┐│
│  │      Commands           │  │     Next Action            ││
│  └─────────────────────────┘  └────────────────────────────┘│
│                                                              │
│  ┌──────────────────────────────────────────────────────────┐│
│  │                    Workflow                              ││
│  └──────────────────────────────────────────────────────────┘│
│                                                              │
│  ┌─────────────────────────┐  ┌────────────────────────────┐│
│  │      Gate               │  │   Evidence Preview         ││
│  └─────────────────────────┘  └────────────────────────────┘│
│                                                              │
│  ┌──────────────────────────────────────────────────────────┐│
│  │   Command Preview (conditional, overlay on Enter)       ││
│  └──────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────┘
```

CommandPreview 作为 overlay 显示在底部，按 `Enter` 时出现，按 `Esc` 消失。

### 6.8 交互 (Phase 2)

| 按键 | 行为 |
|------|------|
| `q` / `Ctrl+C` | 退出 |
| `↑` / `↓` | 命令列表导航 |
| `Enter` | 展示选中命令的 CommandPreview |
| `Esc` | 关闭 CommandPreview 返回 CommandPanel |
| `Tab` | 切换面板焦点 |

---

## 7. TDD Plan

### 7.1 Test Layer

| 测试文件 | 覆盖 | 测试数量 (预估) |
|---------|------|----------------|
| `projectStatus.test.ts` | Section 0 解析, REAL-EVIDENCE 行解析, 容错 | 8 |
| `progressLedger.test.ts` | 日期/里程碑解析, 空文件, 格式容错 | 6 |
| `dogfoodResults.test.ts` | JSON 解析, 文件排序, 缺失字段容错 | 6 |
| `gitInfo.test.ts` | git status/log 解析 | 5 |
| **Total** | | **~25** |

### 7.2 RED → GREEN 顺序

1. `projectStatus.test.ts` RED → GREEN
2. `progressLedger.test.ts` RED → GREEN
3. `dogfoodResults.test.ts` RED → GREEN
4. `gitInfo.test.ts` RED → GREEN
5. 组件 smoke tests（Dashboard renders without crash）

### 7.3 Phase 2 Test Layer

| 测试文件 | 覆盖 | 测试数量 (预估) |
|---------|------|----------------|
| `commandCatalog.test.ts` | JSON 加载, command 解析, safety level 验证, 缺失文件容错 | 7 |
| `commandPanel.test.ts` | 命令列表渲染, 分组, 高亮行, disabled 灰显 | 5 |
| `commandPreview.test.ts` | preview 内容渲染, shell command 展示, safety level 颜色, Esc 行为 | 5 |
| `nextActionPanel.test.ts` | 推荐下一步渲染, 空值容错 | 3 |
| `safetyModel.test.ts` | 五级分类, 映射到组件行为, disabled 不可选中 | 4 |
| **Phase 2 Subtotal** | | **~24** |
| **Total (Phase 1 + 2)** | | **74** |

### 7.4 Phase 3 Test Layer (NEW)

| 测试文件 | 覆盖 | 测试数量 (预估) |
|---------|------|----------------|
| `navigation.test.ts` | ViewId enum, NavigationState 切换, 边界 (first/last view), 无效 view 拒绝 | 6 |
| `tasks.test.ts` | TaskCenter JSON 加载, 状态分类 (recommended/deferred/completed/not-started), 缺失文件容错, why 字段 | 6 |
| `workflowState.test.ts` | 解析 currentStage/completedMilestones/deferredItems/nextRecommended, 空文件容错, 格式容错 | 5 |
| `evidenceDetails.test.ts` | 001-008 详情加载, 字段完整性 (status/dogfood/commit/caveats), 缺失文件容错 | 5 |
| `docsConsistency.test.ts` | 文件存在/缺失/未知检测, 容错, shell command preview | 4 |
| `navigationBar.test.ts` | view 渲染, 当前 view 高亮, view 列表展示 | 4 |
| `taskCenterPanel.test.ts` | recommended/deferred/completed/not-started 渲染, why 文本展示 | 4 |
| `noExecution.test.ts` | 确认无 exec/execSync/spawn/child_process 引入, 无 .env 读取 | 3 |
| **Phase 3 Subtotal** | | **~37** |
| **Total (Phase 1 + 2 + 3)** | | **~111** |

### 7.5 Phase 2 RED → GREEN 顺序

1. `commandCatalog.test.ts` RED → GREEN
2. `commandPanel.test.ts` RED → GREEN
3. `commandPreview.test.ts` RED → GREEN
4. `nextActionPanel.test.ts` RED → GREEN
5. `safetyModel.test.ts` RED → GREEN
6. Phase 1 regression（25 tests must still PASS）
7. Dashboard Phase 2 布局 smoke test

---

## 8. Gates

| Gate | Command | 预期结果 |
|------|---------|---------|
| TypeScript 编译检查 | `npx tsc --noEmit` | 0 errors |
| Vitest 测试 | `npx vitest run` | all pass |
| ESLint/oxlint (如配置) | `npx oxlint src/` | 0 errors |
| 启动 smoke | `npm start` (手动) | 面板正常渲染 |
| git diff --check | 来自仓库根 | 无 whitespace errors |

---

## 9. Non-Goals (明确排除)

### 9.1 Phase 1 Non-Goals

- **不连接 runtime**: 不读取 agent_log.jsonl 流，不连接 dispatcher
- **不修改 Python 代码**: 不对 agent/ 做任何改动
- **不读 .env**: 不触碰 secret
- **不调用 API**: 不发起网络请求
- **不控制 agent**: 只读展示
- **不处理 B7**: multi-instance 不在 Phase 1
- **不引入数据库**: 所有状态来自文件
- **不做 Web UI**: 纯终端
- **不做交互式操作**: 不触发 dogfood、不切换 branch
- **不处理实时更新**: Phase 1 一次性加载，不 watch 文件变化

### 9.2 Phase 2 Additional Non-Goals

- **不执行任何 shell 命令**: 所有 `exec` 路径编译时不可达
- **不读取 .env**: 同 Phase 1
- **不调用真实 API**: 不发起网络请求
- **不启动真实 agent run**: 不调用 `python main.py`
- **不执行 destructive actions**: git push / rm / force 等
- **不绕过 Python main path**: TUI 不是第二 runtime
- **不修改 Python 代码**: 同 Phase 1
- **不处理 B7 multi-instance**: 同 Phase 1
- **不处理实时 runtime evidence 流**: Phase 3+
- **不做安全命令执行**: Phase 4+（confirmation gate + dry-run）
- **不废弃 CLI**: CLI 仍然可用，只是 TUI 成为推荐入口

### 9.3 Phase 3 Additional Non-Goals

- **不执行任何 shell 命令**: 同 Phase 2，所有 exec 路径不可达
- **不读取 .env / 不调用真实 API**: 同 Phase 1/2
- **不把 TUI 设为唯一默认入口**: 定义 readiness checklist 但不切换
- **不删除 CLI**: CLI 永不被删除，始终作为 fallback
- **不进入 B7 multi-instance implementation**: 同 Phase 1/2
- **不做 real-time evidence stream**: Phase 5+
- **不执行 Coding Agent workflow 命令 / 不启动 agent run**: Phase 4+
- **不改 Python runtime / core path**: 同 Phase 1/2
- **不写 checkpoint**: TUI 不触发 session checkpoint
- **不做 Web UI**: 同 Phase 1/2
- **不引入大型依赖**: 依赖表面与 Phase 2 一致

---

## 10. Dev Workflow Integration (Phase 3+ — provisional dev-only)

Phase 3 TUI 已是多视图工作台，展示 Coding Agent engineering workflow 命令（provisional dev-only）。后续 Phase 4+ 可以直接通过 TUI 触发执行：

```bash
# 当前 Phase 3 用户流程
# TUI 浏览命令 → 复制 shell command → 粘贴到 CLI 执行

Phase 2 TUI 已是 command shell，展示 Coding Agent dev workflow 命令。后续 Phase 4+ 可以直接通过 TUI 触发执行：

```bash
# 当前 Phase 2 用户流程
# TUI 浏览命令 → 复制 shell command → 粘贴到 CLI 执行

# 未来 Phase 4+ 流程
# TUI 选中命令 → 确认 → 直接执行
```

当前 Phase 2 不做此集成（exec 路径编译时不可达）。

---

## 11. B7 Multi-Instance Field Reservation

B8 不实现 B7，但在数据结构中预留 B7 字段：

```typescript
// types.ts 预留
interface InstanceInfo {
  id: string;
  status: "running" | "stopped";
  // Phase 1: 空数组，B7 就绪后填充
}
```

TUI 面板中暂不渲染多实例信息。

---

## 12. Implementation Plan

### 12.1 Phase 1 (COMPLETED — `eba77ad`)

| Phase | 内容 | 预估文件数 | 预估行数 |
|-------|------|-----------|---------|
| 0 | SDD + design review | 1 (本文档) | ~250 |
| 1 | 项目骨架: package.json, tsconfig, vitest.config | 3 | ~60 |
| 2 | TDD RED: data layer tests | 4 test files | ~150 |
| 3 | GREEN: data layer implementation | 4 src files | ~250 |
| 4 | Components + main.tsx | 7 src files | ~300 |
| 5 | Gates + smoke test | — | — |
| 6 | Docs update + commit/push | 3 docs | ~30 diffs |

**Phase 1 总计**: ~17 个文件, ~800 行 TypeScript (含测试), ~200 行配置/docs diff

### 12.2 Phase 2 (本轮)

| Phase | 内容 | 预估文件数 | 预估行数 |
|-------|------|-----------|---------|
| 0 | SDD update (Phase 2 sections) | 1 | ~150 |
| 1 | commands.json + commandCatalog.ts | 2 | ~80 |
| 2 | TDD RED: commandCatalog + safety model + component tests | 5 test files | ~200 |
| 3 | GREEN: commandCatalog + CommandPanel + NextActionPanel + CommandPreview | 4 src files | ~350 |
| 4 | Dashboard Phase 2 布局重构 + safety model 集成 | 2 src files | ~100 |
| 5 | Gates + smoke test | — | — |
| 6 | Docs update + commit/push | 3 docs | ~30 diffs |

**Phase 2 新增**: ~8 个文件, ~730 行 TypeScript (含测试), ~180 行 docs diff
**Phase 1 + 2 总计**: ~25 个文件, ~1530 行 TypeScript, ~380 行配置/docs diff

---
## 13. Risk Assessment

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| Ink 版本与 Node 20 不兼容 | 低 | 中 | 锁定 Ink 5.x; tsx 已验证可用 |
| Markdown 解析边界情况 | 中 | 低 | 基于固定 section 标记解析，非通用 parser |
| Git 子进程跨平台差异 | 低 | 低 | 仅 macOS 环境，`git status --short` 格式稳定 |
| 终端宽度 < 80 列 | 低 | 低 | 不做响应式，文档注明最小宽度 |
| 依赖安装慢 | 低 | 低 | 仅 ink + react + tsx + vitest，依赖量小 |
| Phase 2: Ink `useInput` 多键绑定冲突 | 中 | 中 | 分层 focus 管理；CommandPreview overlay 独占输入 |
| Phase 2: 命令 JSON schema 演化 | 低 | 低 | 硬编码 schema 版本号；不向后兼容时改 version |
| Phase 2: Phase 1 回归破坏 | 低 | 高 | Phase 1 25 tests 作为回归套件；Dashboard 布局仅扩展不重写 |
