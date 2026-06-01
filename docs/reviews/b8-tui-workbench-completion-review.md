# B8 TUI Workbench — Completion Review

**审查日期**: 2026-06-01
**审查类型**: 阶段性收口审查（不进入 B7，不激活默认入口）
**审查范围**: B8 Phase 1-6A + Polish Loop 1-2
**当前 HEAD**: 65822ad

---

## 1. Scope

本审查评估 B8 TypeScript TUI Workbench 在 **Phase 1-6A + Polish Loop 1-2** 边界内的完成状态。不包括 Phase 6B/7（deferred），不包括 B7 implementation。

审查目标：
1. 判断 B8 当前边界内是否可以阶段性收口
2. 判断 TUI 是否可以进入 default-entry review 阶段
3. 不新增功能，不进入 B7，不激活默认入口

---

## 2. Delivered Capabilities

### 2.1 Phase 1: Static Dashboard (eba77ad)

| 项目 | 详情 |
|------|------|
| 面板 | 5 面板 (Overview/EvidenceStatus/Workflow/Gate/EvidencePreview) |
| 数据源 | PROJECT_STATUS.md, PROGRESS_LEDGER.md, dogfood JSON, git |
| 框架 | Ink 5 + React 18 + TypeScript 5 |
| 测试 | 28 tests PASS |
| 启动 | `npm start` → `tsx src/main.tsx` |

### 2.2 Phase 2: Command Shell (3c8e178)

| 项目 | 详情 |
|------|------|
| 命令 | 8 命令 (autorun/status/audit/dogfood/gates/docs-check/agent-run/deploy) |
| 安全模型 | 5 级: read-only/preview-only/requires-confirmation/disabled/future-executable |
| 组件 | CommandPanel (↑↓ 导航), NextActionPanel, CommandPreview |
| 测试 | 74 tests PASS (28 Phase 1 + 46 Phase 2) |

### 2.3 Phase 3: Default Workbench Readiness (2ae13ab)

| 项目 | 详情 |
|------|------|
| 视图 | 7 视图键盘导航 (←→/1-7): Overview/Evidence/Workflow/Commands/Tasks/Gates/Docs |
| 数据模型 | navigation, tasks, workflowState, evidenceDetails, docsConsistency, noExecution |
| CommandCatalog v2 | workflowStage + riskLevel 字段 |
| Default Entry Checklist | 12 项已定义 |
| 测试 | 133 tests PASS (74 Phase 1+2 + 59 Phase 3) |

### 2.4 Phase 4: Safe Command Execution (54aad3a)

| 项目 | 详情 |
|------|------|
| 白名单 | 6 命令 (status/gates/docs-check/autorun/audit/dogfood) |
| 黑名单 | 7 类 destructives (force push/reset --hard/branch -D/clean -f/rm -rf/sudo/chmod/chown) |
| 确认模型 | single confirmation + double confirmation (high-risk) |
| Dry-run | 预览 will-execute，不实际执行 |
| Audit log | JSONL append-only, 10MB rotation, `.gitignore` 保护 |
| Result panel | exit code/stdout/stderr/timeout 展示 |
| 测试 | 178 tests PASS (133 + 45 Phase 4) |

### 2.5 Phase 5: Development Workflow / Review Panel (fc0c9a2 — provisional dev-only)

| 项目 | 详情 |
|------|------|
| 产品边界 | AutoRun 是 Coding Agent 开发期 workflow，非 First Agent 产品特性 |
| 接入方式 | TUI 通过固定命令模板接入 Coding Agent workflow |
| AUTORUN_COMMANDS | 固定模板: continue/status/audit/dogfood/gates — dev-only |
| 注入防护 | `isFixedTemplate()` / `validateAutorunTemplate()` 验证 |
| 组件 | AutoRunPanel (Development Workflow Panel), HardStopOverlay, ReviewPacketPanel — dev-only |
| 测试 | 287 tests PASS |

### 2.6 Phase 6A: Static Evidence/Gate/Dogfood Browser (e3449d4)

| 项目 | 详情 |
|------|------|
| 数据源 | `docs/dogfood/*.json` 本地文件解析, PROJECT_STATUS + PROGRESS_LEDGER 文本解析 |
| EvidenceBrowser | EvidenceFileEntry 列表 (PASS/CONCERN/FAIL counts) |
| GateHistory | 6 known gates parse (npm test/tsc/git diff --check/ruff/whitelist scan/no .env) |
| 组件 | EvidenceBrowserPanel, DogfoodDetailPanel |
| stale/unknown handling | try/catch 全覆盖，解析失败 → "unknown" |
| 测试 | 241 tests PASS (206 + 21 Phase 6A + 14 audit fix additions) |

### 2.7 Polish Loop 1: Readiness Panels (dde2c9d)

| 项目 | 详情 |
|------|------|
| AuditLogPanel | 只读 audit history 视图 |
| DefaultEntryReadinessPanel | 静态 checklist 展示 |
| Empty states | EvidenceBrowserPanel/DocsConsistencyPanel edge cases |
| Keyboard hints | footer 增强 |

### 2.8 Polish Loop 2: Acceptance Audit Fixes (65822ad)

| 项目 | 详情 |
|------|------|
| P1-1 | `.gitignore` 添加 `.tui_audit_log*` |
| P1-2 | `tasks.json` 更新至当前状态 (Phase 3/4/5/6A completed) |
| P1-3 | 测试数同步修正 (227→241→260) |
| P2-1 | `noExecution.ts` 真实文件扫描 (9 forbidden patterns + allowlist) |
| P2-2 | `docsConsistency.ts` 内容 staleness 检测 (STALE_MARKERS + scanContentForStaleMarkers) |

---

## 3. Gates

### 3.1 Current Baseline

| Gate | Result |
|------|--------|
| `npm test` | **260/260 PASS** (26 test files) |
| `npm run typecheck` (tsc --noEmit) | **0 errors** |
| `git diff --check` | **clean** |
| No `.env` access | **0 matches** (verified by noExecution.ts scanner) |
| Whitelist scan | **only allowed execSync in main.tsx (git operations)** |
| `npm start` smoke | **manual — renders all panels** |

### 3.2 Gate History (per GateHistory data model)

| Gate | Current |
|------|---------|
| npm test | ✅ 260/260 |
| tsc --noEmit | ✅ clean |
| git diff --check | ✅ clean |
| ruff (Python) | ✅ clean (pre-existing only) |
| whitelist scan | ✅ only allowed |
| no .env | ✅ 0 matches |

---

## 4. Safety Boundaries

### 4.1 Enforced

| 边界 | 机制 | 状态 |
|------|------|------|
| No shell execution of unapproved commands | `executionWhitelist.ts` (isAllowed/isBlocked) | ✅ |
| No destructive git commands | 黑名单: push --force/reset --hard/branch -D/clean -f | ✅ |
| No file deletion | 黑名单: rm -rf/sudo/chmod/chown | ✅ |
| No .env/secret access | `noExecution.ts` scanner (9 patterns) + allowlist | ✅ |
| No dynamic command injection | AUTORUN_COMMANDS 固定模板 + isFixedTemplate() | ✅ |
| Audit log protection | `.gitignore` 覆盖 `.tui_audit_log*`, append-only | ✅ |
| Double confirmation for high-risk | executionGate.ts double confirmation model | ✅ |
| Execution timeout | 60s shell exec timeout + 30s confirmation timeout | ✅ |
| CLI fallback retained | CLI 永不删除 | ✅ |
| No second runtime | TUI 不改 Python runtime core path | ✅ |

### 4.2 Known Limitations

| 限制 | 详情 | 风险 |
|------|------|------|
| Chinese IME | Ink useInput 对中文 IME 组合输入行为未完全验证 | 低 — 单键导航不经过 IME pipeline |
| No real-time stream | Phase 7 deferred | Phase 7 依赖 B7 |
| Static evidence only | Phase 6B multi-instance history deferred | Phase 6B 依赖 B7 |

---

## 5. Remaining Technical Debt

### 5.1 Phase 6B: Multi-instance History Browser (DEFERRED)

**阻塞原因** (详见 `docs/debt/b8-tui-workbench-technical-debt.md`):
- 缺 session/run/instance identity model
- 缺 evidence namespace model
- 缺 multi-run storage contract
- 不是 "现在可以实现但选择不做"，而是 "架构前提不满足"

### 5.2 Phase 7: Runtime Event Stream Viewer (DEFERRED)

**阻塞原因**:
- 缺 append-only runtime event source contract
- 缺 runtime event ownership / namespace
- 缺 backpressure / truncation / redaction strategy
- 第二 runtime 风险: 不能为了 TUI 新增 event 写入路径

### 5.3 TUI Default Entry Activation (DEFERRED)

Default Entry Readiness checklist (12 项) 中部分未满足:
- Phase 6B/7 未完成
- Chinese IME 实际验证未完成
- 不阻塞阶段性收口

### 5.4 Non-Blocking Pending Items

| 项目 | 状态 | 说明 |
|------|------|------|
| Chinese IME validation | PENDING | 单键导航不依赖 IME，文本输入 Phase 7+ 才需要 |
| AuditLogPanel browser UI | PENDING | auditLog.ts rotation 已就绪，UI 已部分暴露 |
| B7 implementation | NOT STARTED | 不在本审查范围 |

---

## 6. Current Conclusion

### 6.1 B8 Phase 1-6A: 可以阶段性收口

B8 在当前边界内已达成以下目标：

1. **7 阶段完整交付** (Phase 1/2/3/4/5/6A + Polish Loop 1-2)
2. **260/260 tests PASS**, tsc --noEmit clean
3. **安全边界完整**: 白名单/黑名单/确认模型/dry-run/audit log/注入防护
4. **Dev Workflow Panel (provisional dev-only)**: TUI 可通过固定命令模板安全接入 Coding Agent engineering workflow。AutoRun 是 Coding Agent 开发期工程 skill，非 First Agent 产品特性。
5. **静态证据浏览器**: 本地 JSON 解析 + gate history 文本解析
6. **文档一致性检测**: 文件存在性 + 内容 staleness (STALE_MARKERS)
7. **代码安全扫描**: noExecution.ts 真实文件扫描 (9 forbidden patterns)
8. **所有技术债务已记录**: `docs/debt/b8-tui-workbench-technical-debt.md`
9. **路线图完整**: `docs/roadmap/b8-tui-workbench-roadmap.md`
10. **CLI fallback 保留**: 不删除 CLI，不废弃 CLI

**判断: B8 当前边界内可以阶段性收口。**

### 6.2 TUI Default Entry: 尚未就绪

Default Entry Readiness checklist 中仍有未满足项 (Phase 6B/7 + IME validation)。TUI 当前是 **preview-only 工作台**，不是默认入口。

**判断: TUI 可以进入 default-entry review 讨论阶段，但不应立即激活为默认入口。**

### 6.3 Overall Verdict

| 维度 | 状态 |
|------|------|
| B8 Phase 1-6A | **COMPLETED — 可以阶段性收口** |
| B8 Polish Loop 1-2 | **COMPLETED** |
| 260/260 tests | **PASS** |
| TypeScript | **clean** |
| 安全边界 | **enforced (whitelist/blacklist/confirmation/dry-run/audit log)** |
| Phase 6B | **DEFERRED — blocked by B7** |
| Phase 7 | **DEFERRED — blocked by B7** |
| TUI default entry | **NOT ACTIVATED — checklist not fully met** |
| CLI fallback | **RETAINED** |
| B7 implementation | **NOT STARTED** |
| Product readiness | **NOT PRODUCT-READY** |

**当前阶段建议**: B8 收口。下一步可选 (需用户决策):
- B7 Multi-instance Readiness (大型架构变更)
- 或继续 B8 Polish (静态 UI 改进，不依赖 B7)
- 或 003/006/007/008 证据强化 (Python runtime)

---

## 7. Review Sign-off

| 项目 | 状态 |
|------|------|
| 审查完成日期 | 2026-06-01 |
| 审查者 | Claude Code (plan-eng-review skill) |
| 审查范围 | B8 Phase 1-6A + Polish Loop 1-2 |
| 排除范围 | B7, Phase 6B/7, default entry activation |
| 数据源 | PROJECT_STATUS, PROGRESS_LEDGER, B8 roadmap, B8 SDD, B8 debt, tui/src, tui tests |

---

## A. Appendix: File Inventory

### A.1 TUI Source Files (28 data files)

```
tui/src/data/
├── auditLog.ts              # JSONL audit log (append-only, 10MB rotation)
├── autorunAdapter.ts        # AUTORUN_COMMANDS fixed templates, injection prevention
├── autorunState.ts          # AutoRun state parser from PROJECT_STATUS
├── commandCatalog.ts        # Command catalog loader
├── commandPanel.ts          # Command panel state model
├── commandPreview.ts        # Command preview model
├── commandResult.ts         # Exec result parser (stdout/stderr/exit code)
├── commands.json            # 8 command definitions
├── defaultEntryReadiness.ts # Default entry checklist data
├── docsConsistency.ts       # File existence + content staleness detection
├── dogfoodResults.ts        # Dogfood JSON parser
├── evidenceBrowser.ts       # Evidence file index builder
├── evidenceDetails.json     # 001-008 evidence details
├── evidenceDetails.ts       # Evidence detail loader
├── executionGate.ts         # Confirmation model, dry-run logic
├── executionWhitelist.ts    # Whitelist/blacklist definitions
├── gateHistory.ts           # Gate history parser (6 known gates)
├── gitInfo.ts               # Git status/log parser
├── navigation.ts            # View navigation model
├── nextAction.ts             # Next action model
├── noExecution.ts            # Forbidden pattern scanner
├── progressLedger.ts         # Progress ledger parser
├── projectStatus.ts          # PROJECT_STATUS parser
├── reviewPacket.ts           # Review packet builder from git log + test output
├── safetyModel.ts            # Safety level model (5 levels)
├── tasks.json                # B8/B7 task center data
├── tasks.ts                  # Task center data loader
└── workflowState.ts          # Workflow state parser
```

### A.2 TUI Component Files (23 components)

```
tui/src/components/
├── AuditLogPanel.tsx              # Read-only audit history view
├── AutoRunPanel.tsx               # AutoRun state panel
├── CommandPanel.tsx               # Command list with ↑↓ navigation
├── CommandPreview.tsx             # Command preview overlay
├── ConfirmOverlay.tsx             # Single/double confirmation dialog
├── Dashboard.tsx                  # Top-level layout
├── DefaultEntryReadinessPanel.tsx # Default entry checklist display
├── DocsConsistencyPanel.tsx       # Docs status with stale/content detection
├── DogfoodDetailPanel.tsx         # Evidence file detail + gate history
├── DryRunOverlay.tsx              # Dry-run result overlay
├── EvidenceBrowserPanel.tsx       # Evidence file browser
├── EvidenceDetailPanel.tsx        # 001-008 evidence detail
├── EvidencePreviewPanel.tsx       # Latest dogfood result summary
├── EvidenceStatusPanel.tsx        # REAL-EVIDENCE status table
├── GatePanel.tsx                  # Git status/commits panel
├── HardStopOverlay.tsx            # HARD_STOP display
├── NavigationBar.tsx              # View switcher (←→ / 1-7)
├── NextActionPanel.tsx            # Next recommended action
├── OverviewPanel.tsx              # Project overview
├── ResultPanel.tsx                # Command execution result
├── ReviewPacketPanel.tsx          # Review packet display
├── TaskCenterPanel.tsx            # B8/B7 task center
└── WorkflowPanel.tsx              # Recent milestones
```

### A.3 TUI Test Files (26 files, 260 tests)

```
tui/src/__tests__/
├── auditLog.test.ts              (11 tests)
├── autorunAdapter.test.ts        (11 tests)
├── autorunState.test.ts          (10 tests)
├── commandCatalog.test.ts        (8 tests)
├── commandPanel.test.ts          (7 tests)
├── commandPreview.test.ts        (9 tests)
├── defaultEntryReadiness.test.ts (14 tests)
├── docsConsistency.test.ts       (18 tests)
├── dogfoodResults.test.ts        (5 tests)
├── evidenceBrowser.test.ts       (11 tests)
├── evidenceDetails.test.ts       (7 tests)
├── executionGate.test.ts         (18 tests)
├── executionWhitelist.test.ts    (16 tests)
├── gateHistory.test.ts           (10 tests)
├── gitInfo.test.ts               (9 tests)
├── navigation.test.ts            (11 tests)
├── navigationBar.test.ts         (7 tests)
├── nextActionPanel.test.ts       (3 tests)
├── noExecution.test.ts           (14 tests)
├── progressLedger.test.ts        (6 tests)
├── projectStatus.test.ts         (8 tests)
├── reviewPacket.test.ts          (7 tests)
├── safetyModel.test.ts           (19 tests)
├── taskCenterPanel.test.ts       (7 tests)
├── tasks.test.ts                 (7 tests)
└── workflowState.test.ts         (7 tests)
```
