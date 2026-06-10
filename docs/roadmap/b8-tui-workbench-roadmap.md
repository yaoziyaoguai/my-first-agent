# B8 Interaction-first Workbench — Roadmap

**创建日期**: 2026-06-02
**状态**: M1-M8 DELIVERED-WITH-CAVEATS (current HEAD 2f995b9) — interaction-first workbench fake/local MVP 交付。412/412 TUI tests PASS, tsc clean。TUI default entry NOT ACTIVATED。not product-ready。
**取代**: 旧 B8 Phase 1-7 路线（"信息展示中心"方向，归档为历史参考）
**依赖文档**:
- `docs/proposals/b8-interaction-first-workbench-proposal.md`
- `docs/milestones/b8-interaction-first-workbench-milestones.md`
- `docs/design/b8-interaction-first-workbench-sdd.md`
- `docs/design/first-agent-tui-design.md`
- `docs/plans/b8-interaction-first-workbench-tdd-plan.md`

---

## 1. 方向变更

### 1.1 从"信息展示中心"到"交互优先工作台"

旧 B8 Phase 1-7 路线围绕"面板数量"递进：5 面板 → 7 视图 → 命令执行 → workflow panel → 证据浏览器 → 多实例 → event stream。所有 Phase 都是信息展示，没有一个让用户和 First Agent 交互。

新方向：**B8 = First Agent Interactive Workbench**。Milestone 按"主入口成熟度"定义，不按"面板数量"定义。

### 1.2 旧资产保留

旧 B8 Phase 1-6A 已交付能力保留在磁盘，但不在当前 WorkbenchLayout 默认渲染，也不作为 B8 产品主线：

| 能力 | 当前状态 | 说明 |
|------|----------|------|
| Evidence Browser / Gate History | legacy/auxiliary | 不由 `tui/src/main.tsx` 或 `WorkbenchLayout` import |
| Audit Log / Docs Consistency | legacy/auxiliary | 不复用为 Context Panel 子面板 |
| Command Shell | paused/dev-only | 不在 interaction-first 产品核心 |
| Dev Workflow Panel / AutoRun | paused/dev-only | Coding Agent 工程工具，不是 First Agent 产品能力 |

---

## 2. Milestone 全景

```
M0 (Direction Correction) — 文档阶段，已完成
  │
  ▼
M1 (Layout) ──────► M2 (Agent Lens) ──────► M3 (Interaction MVP)
  │                     │                         │
  ▼                     ▼                         ▼
M4 (Context Inspector) ◄────┘                         │
  │                                                │
  ▼                                                │
M5 (Controlled Action) ◄───────────────────────────┘
  │
  ▼
M6 (Multi-instance History)
  │
  ▼
M7 (Event Stream)
  │
  ▼
M8 (Default Entry Readiness)
```

### 2.1 各 Milestone 交付物

| Milestone | 名称 | 状态 | 关键交付物 | 新增 Tests |
|-----------|------|------|-----------|-----------|
| **M0** | Direction Correction | **COMPLETED** | Proposal + Milestones + SDD + TDD Plan | 0 (regression only) |
| **M1** | Interaction-first Layout | **DELIVERED** | WorkbenchLayout, InputBar, StatusBar, 3-zone layout | 14 |
| **M2** | Agent Lens / Selected Context | **DELIVERED** | AgentLensNode 树, SelectedLens 状态, 树导航 | 15 |
| **M3** | Interaction MVP | **DELIVERED** | RuntimeGateway 接口, FakeRuntimeGateway, InteractionView | 20 |
| **M4** | Context Inspector MVP | **DELIVERED** | InspectorSnapshot, ContextInspectorState, 多子面板 | 15 |
| **M5** | Controlled Action / Pending Confirmation | **DELIVERED** | PendingAction, approve/reject through gateway | 12 |
| **M6** | Multi-instance History Foundation | **DELIVERED** | EvidenceNamespace contract, MultiRunStorageContract | 11 |
| **M7** | Runtime Event Stream / EventPanel | **DELIVERED** | EventSourceContract, EventStreamReader | 12 |
| **M8** | Default Entry Readiness | **DELIVERED-WITH-CAVEATS** | Readiness checklist + safety/runtime bypass guards；user approval pending, default entry NOT ACTIVATED | 8+ regression |

**当前 TUI gate**: 412/412 tests PASS。原 107-test 规划是里程碑设计基线，后续 remediation 又增加了 selected-lens scoping / recursive redaction / event scoping regressions。

---

## 3. 当前基线

| 指标 | 值 |
|------|---|
| TUI tests | 412/412 PASS |
| TypeScript | tsc --noEmit clean |
| Python tests | 非 B8 TUI 主 gate；历史全量 Python 结果见 `PROJECT_STATUS.md`，xfail 不按 pass 计 |
| TUI default entry | NOT ACTIVATED |
| 技术栈 | Ink 5 + React 18, tsx, Vitest |

---

## 4. M0 当前进度

M0 是纯文档阶段，不改代码：

- [x] Proposal 定义 why/what/boundary
- [x] Milestones M0-M8 定义完成
- [x] SDD 定义布局、数据模型、安全边界
- [x] TDD Plan 覆盖所有 milestone 的测试策略
- [x] Roadmap/debt/status 与上述文档一致
- [x] 用户审阅 proposal 并确认 5 项决策
- [x] 412/412 TUI tests PASS, tsc clean (current HEAD)

---

## 5. 约束与不做列表

### 5.1 全 Milestone 约束

1. TUI 不是第二 runtime — 所有写操作通过 RuntimeGateway → main runtime path
2. 不读取 .env / 不调用真实 API（M3-M7 使用 FakeRuntimeGateway）
3. 不删除 CLI / 不废弃 CLI
4. 不做 Web UI
5. 不引入数据库、WebSocket、SSE
6. 不把 TUI 设为默认入口（M8 readiness delivered 后仍需用户显式批准；当前 NOT ACTIVATED）
7. 不进入 B7 multi-instance implementation
8. AutoRun 永久 dev-only

### 5.2 明确不做

- B7 multi-instance orchestrator 实现
- Python runtime 架构变更
- real-time WebSocket server
- TUI 插件系统
- 远程访问 / Web-based TUI
- 真实 API 调用（TUI 层面）

---

## 6. 关键决策记录

| ID | 决策 | 日期 | 理由 |
|----|------|------|------|
| D-013 | B8 产品方向从"信息展示中心"改为"interaction-first workbench" | 2026-06-02 | 主入口的第一能力是交互，审计是辅助 |
| D-014 | Milestone 按"主入口成熟度"定义，不按"面板数量" | 2026-06-02 | 防止 Coding Agent 按面板完成度判断进度 |
| D-015 | M0-M8 依赖链: M1→M2→{M3, M4→M5→M6→M7→M8} | 2026-06-02 | M1-M3 交互核心链，M4-M5 context/controlled 链，M6-M7 历史/流链 |
| D-016 | 所有 M1-M7 期间 default entry NOT ACTIVATED | 2026-06-02 | M8 用户显式批准后才激活 |
| D-017 | AutoRun 永久 dev-only | 2026-06-02 | AutoRun 是 Coding Agent 工程工具，不是 First Agent 产品能力 |

---

## 7. 文档导航

| 想了解 | 读这里 |
|--------|--------|
| B8 产品提案 | `docs/proposals/b8-interaction-first-workbench-proposal.md` |
| B8 Milestones (M0-M8) | `docs/milestones/b8-interaction-first-workbench-milestones.md` |
| B8 SDD (架构设计) | `docs/design/b8-interaction-first-workbench-sdd.md` |
| B8 TDD Plan | `docs/plans/b8-interaction-first-workbench-tdd-plan.md` |
| 当前项目状态 | `docs/PROJECT_STATUS.md` |
| 进度历史 | `docs/PROGRESS_LEDGER.md` |
| B8 Technical Debt | `docs/debt/b8-tui-workbench-technical-debt.md` |
| 旧 B8 SDD (Phase 1-6A 历史参考) | 已在 repository cleanup 中删除 |
| TUI 源码 | `tui/src/` |

---

## 8. 版本历史

| 日期 | 变更 |
|------|------|
| 2026-06-02 | 完全重写 — interaction-first 方向，M0-M8 里程碑替代旧 Phase 1-7 |
| 2026-06-02 | B1-B8 close-out sweep — 对齐 412/412 gate、fake/local boundary、legacy auxiliary 非主线、default entry NOT ACTIVATED |
