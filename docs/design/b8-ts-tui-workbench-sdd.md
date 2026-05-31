# B8 TypeScript TUI Workbench — SDD

**创建日期**: 2026-05-31
**状态**: SPEC/SDD 阶段
**类型**: Architecture Extension Loop — 新跨领域关注点

---

## 1. Vision

**最终形态**: 终端内 Agent Workbench（TUI），开发者可通过键盘驱动的终端界面观察、调试、操控 First Agent 运行时。

**Phase 1 (本轮)**: 只读静态仪表盘 — 从 `docs/` 和 git 读取已有工程数据并展示，不连接运行时。

**后续 Phase（不在本轮范围）**:
- Phase 2: 实时 runtime evidence 流（通过 agent_log.jsonl tail 或 dispatcher stream）
- Phase 3: 交互式操作（触发 dogfood、切换 branch、启动/停止 agent）
- Phase 4: 多实例监控（B7 multi-instance 后端就绪后）
- Phase 5: 完整 TUI Agent Workbench（直接在工作台中与 agent 对话）

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

---

## 10. Future AutoRun Integration (Phase 2+ 预留)

B8-lite 完成后，后续 `/auto-run` 可以在启动时自动唤起 TUI 展示当前状态：

```bash
# 未来 /auto-run step 0
(cd tui && npm start) &  # 后台启动 TUI
```

当前 Phase 1 不做此集成。

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

| Phase | 内容 | 预估文件数 | 预估行数 |
|-------|------|-----------|---------|
| 0 | SDD + design review | 1 (本文档) | ~250 |
| 1 | 项目骨架: package.json, tsconfig, vitest.config | 3 | ~60 |
| 2 | TDD RED: data layer tests | 4 test files | ~150 |
| 3 | GREEN: data layer implementation | 4 src files | ~250 |
| 4 | Components + main.tsx | 7 src files | ~300 |
| 5 | Gates + smoke test | — | — |
| 6 | Docs update + commit/push | 3 docs | ~30 diffs |

**总计**: ~17 个文件, ~800 行 TypeScript (含测试), ~200 行配置/docs diff

---

## 13. Risk Assessment

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| Ink 版本与 Node 20 不兼容 | 低 | 中 | 锁定 Ink 5.x; tsx 已验证可用 |
| Markdown 解析边界情况 | 中 | 低 | 基于固定 section 标记解析，非通用 parser |
| Git 子进程跨平台差异 | 低 | 低 | 仅 macOS 环境，`git status --short` 格式稳定 |
| 终端宽度 < 80 列 | 低 | 低 | 不做响应式，文档注明最小宽度 |
| 依赖安装慢 | 低 | 低 | 仅 ink + react + tsx + vitest，依赖量小 |
