# B8 TypeScript TUI Workbench — 分阶段路线

**创建日期**: 2026-06-01
**来源**: `/plan-eng-review` — B8 Roadmap / Default Entry Readiness Review
**依赖文档**: `docs/design/b8-ts-tui-workbench-sdd.md` (Phase 1-3 SDD)、`docs/PROJECT_STATUS.md` (当前状态)

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
Phase 4 (NEXT)          Phase 5 (PLANNED)       Phase 6 (BLOCKED by B7)
安全命令执行             实时 Evidence 流         多实例监控
confirmation gate       agent_log.jsonl tail    B7 后端就绪后
    │                       │                       │
    ▼                       ▼                       ▼
Phase 7 (FUTURE)
完整 TUI Agent Workbench
CLI 降级为 fallback，TUI 为主入口
```

### 1.2 各 Phase 交付物

| Phase | 名称 | 状态 | 关键交付物 |
|-------|------|------|-----------|
| **Phase 1** | 静态仪表盘 | **COMPLETED** | 5 面板 (Overview/EvidenceStatus/Workflow/Gate/EvidencePreview), 28 tests |
| **Phase 2** | Command Shell | **COMPLETED** | CommandCatalog (8 commands, 5 级 SafetyModel), CommandPanel, CommandPreview, NextActionPanel, 74 tests |
| **Phase 3** | 默认入口就绪 | **COMPLETED** | 7 视图导航, TaskCenterPanel, EvidenceDetailPanel, DocsConsistencyPanel, NavigationBar, CommandCatalog v2, Default Entry Readiness checklist (12 项), 133 tests |
| **Phase 4** | 安全命令执行 | **待规划** | confirmation gate, dry-run 优先, 有限 exec 路径, audit log |
| **Phase 5** | 实时 Evidence 流 | **待规划** | agent_log.jsonl tail, dispatcher stream, 面板自动刷新 |
| **Phase 6** | 多实例监控 | **BLOCKED** | B7 后端就绪后, 多实例状态面板, runtime 指标 |
| **Phase 7** | 完整 Agent Workbench | **未来** | CLI 降级为 fallback, TUI 为主入口, 全功能 agent 操作 |

---

## 2. 当前状态 (Phase 3 COMPLETED)

### 2.1 已交付

| 能力域 | 状态 | 证据 |
|--------|------|------|
| Navigation Model | **DONE** | 7 视图 (Overview/Evidence/Workflow/Commands/Tasks/Gates/Docs), ←→/1-7 键盘导航, NavigationBar |
| TaskCenterPanel | **DONE** | B8/B7 phase 状态矩阵 (recommended/deferred/blocked/completed), 6 entries |
| WorkflowState Model | **DONE** | currentStage/completedMilestones/deferredItems/nextRecommended 解析 |
| EvidenceDetail Model | **DONE** | 001-008 详情 (status/dogfood/commit/caveats/nextAction), JSON 配置 |
| DocsConsistency Model | **DONE** | 4 关键文档 present/missing/unknown 检测, Node existsSync |
| CommandCatalog v2 | **DONE** | workflowStage + riskLevel 字段, 11 命令 |
| Default Entry Readiness | **DONE** | 12 项 checklist 已定义, TUI 不立即切换为默认入口 |
| Chinese IME | **就绪** | 单键导航不受 IME 影响, 文本输入 Phase 4+ 验证 |

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
- **构建工具**: tsx (直接执行 TS)
- **测试框架**: Vitest
- **不引入**: React DOM, Express, 数据库, WebSocket, git 库, 外部 API client

---

## 3. Phase 4: 安全命令执行 (NEXT)

**状态**: 待规划。不在当前阶段实现。
**优先级**: B8 路线中最高优先级 next step。
**预估文件数**: ~8 (3 新组件 + 3 新数据模型 + 2 新测试文件)
**预估行数**: ~500 TypeScript (含测试)
**预估工期**: 1 次 Architecture Extension Loop (SDD + TDD RED + GREEN + gates + docs + commit)

### 3.1 目标

TUI 从 preview-only 升级为可执行安全命令。用户选中命令 → 确认 → 执行 → 查看结果，全程不离开 TUI。

### 3.2 关键设计决策 (待 SDD 确认)

1. **Confirmation gate**: "Are you sure? (y/n)" 对话框，展示将要执行的 shell command
2. **Dry-run 优先**: 破坏性操作默认 dry-run，需显式 `--force` 才执行
3. **Exec 路径**: 通过 `child_process.exec` 执行，输出流式返回
4. **SafetyModel 升级**: `requires-confirmation` 命令变为可执行，`disabled` 命令按阶段解锁
5. **Audit log**: TUI 执行的每条命令记录到 `.tui_audit_log.jsonl`

### 3.3 安全边界 (13 项 Phase 3 约束中的 4 项解除)

- ~~不执行任何 shell 命令~~ → 确认后执行（仅限白名单命令）
- ~~不启动 agent run~~ → 确认后启动（仍需 explicit confirmation）
- ~~不调用真实 API~~ → 确认后调用（复用现有 provider config）
- 仍不读取 .env
- 仍不写 checkpoint
- 仍不绕过 Python runtime

### 3.4 命令白名单 (Phase 4 可执行)

| 命令 | 当前 Safety | Phase 4 行为 |
|------|-----------|-------------|
| `status` | preview-only | 执行: `python main.py status` |
| `gates` | preview-only | 执行: ruff + pytest focused |
| `docs-check` | preview-only | 执行: docs consistency scan |
| `autorun` | requires-confirmation | 确认后执行 `/auto-run` |
| `audit` | requires-confirmation | 确认后执行 |
| `dogfood` | requires-confirmation | 确认后执行 |
| `agent-run` | disabled | disabled (Phase 5+) |
| `deploy` | disabled | disabled (future) |

### 3.5 测试计划 (预估)

| 测试文件 | 覆盖 | 预估数量 |
|---------|------|---------|
| `executionGate.test.ts` | confirmation dialog, deny/approve 路径, timeout | 8 |
| `commandExecution.test.ts` | 白名单执行, stdout/stderr 捕获, exit code 处理 | 7 |
| `auditLog.test.ts` | JSONL 写入, 字段完整性, rotation | 5 |
| `phase4Regression.test.ts` | Phase 1-3 回归 (133 tests still PASS) | — |
| **Phase 4 新增** | | **~20** |
| **总计** | | **~153** |

### 3.6 门禁

| Gate | 命令 | 预期 |
|------|------|------|
| TypeScript | `npx tsc --noEmit` | 0 errors |
| Phase 4 tests | `npx vitest run` | all pass |
| Phase 1-3 regression | `npx vitest run` | 133/133 |
| 白名单扫描 | no unexpected exec paths | pass |
| git diff --check | — | clean |

---

## 4. Phase 5: 实时 Evidence 流 (PLANNED)

**状态**: 待规划。Phase 4 完成后开始。
**依赖**: Phase 4 (安全命令执行), Python runtime event stream
**关键风险**: 文件 tail 性能、JSONL 解析增量、Ink 重渲染频率

### 4.1 目标

TUI 面板从一次性加载升级为实时更新。Overview/EvidenceStatus/Workflow/Gate 面板自动反映最新 runtime 状态。

### 4.2 关键技术点

- `agent_log.jsonl` tail (Node `fs.watch` 或 polling)
- dispatcher event stream (Python 侧输出到 named pipe 或 stdout)
- Ink `useEffect` + `setInterval` 轮询模式
- 增量渲染（只更新变化的面板，不全量重绘）

### 4.3 预估范围

- 新文件: ~5 (1 stream reader + 2 面板升级 + 2 测试)
- 新行数: ~400
- 新测试: ~15

---

## 5. Phase 6: 多实例监控 (BLOCKED by B7)

**状态**: 阻塞。B7 multi-instance 后端就绪后开始。
**阻塞条件**: B7 消除模块级单例, 支持多 agent 实例并发

### 5.1 目标

TUI 展示多 agent 实例的运行状态（running/stopped/error）、资源使用、最近活动。

### 5.2 预估范围

- 新文件: ~4 (1 面板 + 1 数据模型 + 2 测试)
- 新行数: ~300
- 新测试: ~10

---

## 6. Phase 7: 完整 Agent Workbench (FUTURE)

**状态**: 未来。Phase 4-6 全部完成后开始。

### 6.1 目标

TUI 成为默认入口，CLI 降级为显式 fallback。用户通过 TUI 完成全部 agent 操作。

### 6.2 切换条件（全部满足后才切换默认入口）

- [ ] Phase 4: 安全命令执行可用（confirmation gate + dry-run）
- [ ] Phase 5: 实时 evidence 流可用
- [ ] Phase 6: 多实例监控可用（B7 后端就绪）
- [ ] Phase 1-3 回归 133+ tests 全部 PASS
- [ ] Phase 4-6 新增 tests 全部 PASS
- [ ] `npm start` 成功渲染所有面板 + 实时流
- [ ] CLI 仍可独立运行（TUI 不破坏 CLI）
- [ ] 中文 IME 文本输入验证通过
- [ ] audit log 可审计所有 TUI 执行的操作
- [ ] developer dogfood ≥ 1 周无阻塞 bug

---

## 7. 依赖链与风险

### 7.1 依赖链

```
Phase 1 ──► Phase 2 ──► Phase 3 ──► Phase 4 ──► Phase 5 ──► Phase 7
                                         │            │
                                         └── Phase 6 ──┘
                                              ▲
                                         B7 后端就绪
```

- **Phase 4** 不依赖外部条件（纯 TUI 前端 + node child_process）
- **Phase 5** 依赖 Python runtime 提供可消费的 event stream
- **Phase 6** 依赖 B7 multi-instance 后端
- **Phase 7** 依赖 Phase 4/5/6 全部完成

### 7.2 风险矩阵

| 风险 | 概率 | 影响 | Phase | 缓解 |
|------|------|------|-------|------|
| Ink useInput 中文 IME 文本输入截断 | 中 | 中 | Phase 4+ | Phase 4 早期验证；必要时切换到 raw stdin 模式 |
| child_process exec 白名单绕过 | 低 | 高 | Phase 4 | 编译时检查 no dynamic exec；白名单 hardcoded |
| agent_log.jsonl 写入速度 > 轮询速度 | 低 | 低 | Phase 5 | 增量读取 + debounce 重渲染 |
| B7 架构变更破坏 TUI 数据契约 | 低 | 高 | Phase 6 | 预留 B7 field reservation (SDD §11) |
| Node.js 版本升级导致 Ink 不兼容 | 低 | 中 | 全 Phase | 锁定 Ink 5.x + React 18；CI matrix 测试 Node 20/22 |
| Phase 4+ 修改破坏 Phase 1-3 回归 | 中 | 高 | 全 Phase | 133+ tests 作为回归套件；Phase 4+ 只扩展不重写 |

---

## 8. 关键决策记录

| ID | 决策 | 日期 | 理由 |
|----|------|------|------|
| D-001 | TUI 为未来默认入口，CLI 为显式 fallback | 2026-05-31 | Phase 3 确立；CLI 永不删除 |
| D-002 | 不立即切换 TUI 为默认入口 | 2026-05-31 | Default Entry Readiness checklist 12 项全部通过后才切换 |
| D-003 | Phase 4 启 confirmation gate + dry-run 优先 | 2026-06-01 | 安全命令执行的最小可行方案 |
| D-004 | Phase 6 阻塞于 B7 后端 | 2026-05-31 | B7 multi-instance 消除模块级单例后才能多实例监控 |
| D-005 | 不引入 WebSocket/SSE 做实时流 | 2026-06-01 | Phase 5 用文件 tail + polling 保持依赖最小化 |
| D-006 | 不把 TUI 做成第二 runtime | 2026-05-31 | TUI 是 UI 层，不改 Python runtime 行为 |

---

## 9. 门禁矩阵

| Gate | Phase 1-3 | Phase 4 | Phase 5 | Phase 6 | Phase 7 |
|------|----------|---------|---------|---------|---------|
| `npx tsc --noEmit` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `npx vitest run` | ✅ 133 | ✅ ~153 | ✅ ~168 | ✅ ~178 | ✅ ~178+ |
| Phase 1-3 regression | — | ✅ 133 | ✅ 133 | ✅ 133 | ✅ 133 |
| git diff --check | ✅ | ✅ | ✅ | ✅ | ✅ |
| 白名单扫描 | N/A | ✅ | ✅ | ✅ | ✅ |
| `npm start` smoke | ✅ | ✅ | ✅ | ✅ | ✅ |
| CLI 独立运行 | ✅ | ✅ | ✅ | ✅ | ✅ |
| 中文 IME 验证 | ✅ (单键) | 待验证 | 待验证 | 待验证 | ✅ |

---

## 10. 约束与不做列表

### 10.1 全阶段约束

以下约束在所有 Phase 中保持有效：
1. 不把 TUI 做成第二 runtime（不改 Python core path）
2. 不删除 CLI / 不废弃 CLI
3. 不做 Web UI
4. 不引入数据库
5. 不引入 WebSocket / SSE
6. 不读取 .env（除非用户显式确认后执行）
7. 不 commit `config/config.yaml`

### 10.2 Phase 4 专属约束

8. 所有 exec 路径限于硬编码白名单（不动态构建命令）
9. destructive actions (git push / rm / force) 需 double-confirmation
10. audit log 不可删除、不可篡改

### 10.3 明确不做

- B7 multi-instance implementation（Phase 6 之前）
- Python runtime 架构变更
- real-time WebSocket server
- 数据库持久化
- TUI 插件系统
- 远程访问 / Web-based TUI
- 移动端适配

---

## 11. 文档导航

| 想了解 | 读这里 |
|--------|--------|
| B8 SDD (Phase 1-3 设计) | `docs/design/b8-ts-tui-workbench-sdd.md` |
| 当前项目状态 | `docs/PROJECT_STATUS.md` |
| 进度历史 | `docs/PROGRESS_LEDGER.md` |
| B8 路线（本文件） | `docs/roadmap/b8-tui-workbench-roadmap.md` |
| 工程流程 | `docs/dev/AUTO_RUN_WORKFLOW.md` |
| 真实证据债务 | `docs/debt/REAL_EVIDENCE_VALIDATION_DEBT.md` |
| TUI 源码 | `tui/src/` |
| TUI 测试 | `tui/src/__tests__/` |

---

## 12. 版本历史

| 日期 | 变更 |
|------|------|
| 2026-06-01 | 初始版本 — B8 Roadmap / Default Entry Readiness Review |
