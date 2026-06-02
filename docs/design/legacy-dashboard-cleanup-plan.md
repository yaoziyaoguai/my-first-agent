# Legacy Dashboard / AutoRun / Project Operations Cleanup Plan

**创建日期**: 2026-06-02
**状态**: DRAFT — 不删除代码，只记录策略选项
**范围**: B8 PAUSED panels、legacy data/services 文件
**Source**: handoff §7 (frozen), §8 D-07

---

## 1. Current State

`tui/src/main.tsx` 只 import `WorkbenchLayout`。WorkbenchLayout 只使用以下活跃组件和数据：

### 1.1 Active Components (10 files)

| File | 用途 |
|------|------|
| `WorkbenchLayout.tsx` | 主布局 |
| `AgentLensPanel.tsx` | Agent 树选择 |
| `InteractionPanel.tsx` | 对话区域 |
| `ContextPanel.tsx` | Context/Inspector |
| `InputBar.tsx` | 输入 |
| `StatusBar.tsx` | 状态栏 |
| `PendingActionPanel.tsx` | 待确认操作 |
| `HistoryPanel.tsx` | 历史 |
| `EventPanel.tsx` | 事件流 |
| `DefaultEntryReadinessPanel.tsx` | Entry readiness |

### 1.2 Active Data Files (5 files)

| File | 用途 |
|------|------|
| `agentLensFixture.ts` | Agent fixture data |
| `agentHistoryIndex.ts` | 历史索引 |
| `defaultEntryReadiness.ts` | M8 readiness checklist |
| `eventSourceContract.ts` | 事件源契约 |
| `eventStreamReader.ts` | 事件流读取 |

### 1.3 Active Services (3 files)

| File | 用途 |
|------|------|
| `runtimeGateway.ts` | RuntimeGateway interface |
| `fakeRuntimeAdapter.ts` | Fake adapter |
| `blockedRealAdapter.ts` | Blocked real adapter |

---

## 2. Legacy Files (on disk, not imported by WorkbenchLayout)

### 2.1 Legacy Components (22 files)

| File | Category | Historical value |
|------|----------|----------------|
| `Dashboard.tsx` | Dashboard | **high** — B8 Phase 1-6 主面板，7-view 架构 |
| `OverviewPanel.tsx` | Dashboard sub-panel | medium |
| `AutoRunPanel.tsx` | Dashboard sub-panel | medium |
| `ReviewPacketPanel.tsx` | Dashboard sub-panel | medium |
| `EvidenceBrowserPanel.tsx` | Dashboard sub-panel | medium |
| `EvidenceDetailPanel.tsx` | Dashboard sub-panel | medium |
| `EvidencePreviewPanel.tsx` | Dashboard sub-panel | medium |
| `EvidenceStatusPanel.tsx` | Dashboard sub-panel | medium |
| `GatePanel.tsx` | Dashboard sub-panel | medium |
| `TaskCenterPanel.tsx` | Dashboard sub-panel | medium |
| `WorkflowPanel.tsx` | Dashboard sub-panel | medium |
| `DocsConsistencyPanel.tsx` | Dashboard sub-panel | low |
| `DogfoodDetailPanel.tsx` | Dashboard sub-panel | low |
| `AuditLogPanel.tsx` | Audit | medium |
| `CommandPanel.tsx` | Command execution | medium |
| `CommandPreview.tsx` | Command execution | medium |
| `ConfirmOverlay.tsx` | Command confirmation | medium |
| `DryRunOverlay.tsx` | Dry run overlay | medium |
| `HardStopOverlay.tsx` | Hard stop overlay | medium |
| `NavigationBar.tsx` | Navigation | low |
| `NextActionPanel.tsx` | Next action | low |
| `ResultPanel.tsx` | Result display | low |

### 2.2 Legacy Data Files (30 files)

All `tui/src/data/` files except the 5 active ones listed in §1.2.

Key categories:
- **Autorun/Runtime**: `autorunAdapter.ts`, `autorunState.ts`, `workflowState.ts`, `reviewPacket.ts`, `progressLedger.ts`, `projectStatus.ts`, `gitInfo.ts`, `noExecution.ts`
- **Evidence/Gate**: `evidenceBrowser.ts`, `evidenceDetails.ts`, `evidenceNamespace.ts`, `executionGate.ts`, `executionWhitelist.ts`, `gateHistory.ts`, `safetyModel.ts`
- **Command**: `commandCatalog.ts`, `commandPanel.ts`, `commandPreview.ts`, `commandResult.ts`, `commands.json`
- **Dogfood/Docs**: `dogfoodResults.ts`, `docsConsistency.ts`, `tasks.ts`, `tasks.json`
- **Interaction (unused)**: `fakeRuntimeGateway.ts`, `pendingAction.ts`, `navigation.ts`, `nextAction.ts`
- **Audit**: `auditLog.ts`

### 2.3 Legacy Services Files (2 files)

| File | Category | Historical value |
|------|----------|----------------|
| `commandExecutor.ts` | Command execution | **high** — 安全命令执行器，白名单 + audit |
| `executionService.ts` | Command execution | **high** — 命令执行服务，safety gate + env sanitize |

---

## 3. Cleanup Strategy Options

### Option A: Full Remove

删除所有 legacy 文件，只保留 active 文件。

**Pros:**
- 最干净的代码库
- 消除 "zombie code" 迷惑未来读者

**Cons:**
- 丢失 B8 Phase 1-6 架构演进历史
- Dashboard 后续如需恢复需从 git history 恢复
- 某些 data 文件（如 `evidenceNamespace.ts`、`executionGate.ts`）可能作为 B7 架构契约参考

**Recommendation**: 不推荐。历史价值 + 契约参考 > 清理整洁度。

### Option B: Archive to docs/archive/tui-legacy/

移动所有 legacy 文件到 `docs/archive/tui-legacy/`，保留为只读历史参考。

**Pros:**
- 活跃代码库干净
- 保留架构演进历史
- 契约参考文件可查

**Cons:**
- 需要更新所有 cross-reference（如果有的话）
- TypeScript import 重连困难（如后续恢复）

**Recommendation**: 中等。如果用户确认 Dashboard 不再恢复，这是最佳选项。

### Option C: On-disk Keep + Header Comment (Recommended)

保留所有文件在 `tui/src/components/` 和 `tui/src/data/`，但：
1. 每个 legacy 文件顶部添加 `/** LEGACY — PAUSED. Not imported. See docs/design/legacy-dashboard-cleanup-plan.md */`
2. `tui/src/main.tsx` 添加注释说明哪些文件是 active 的
3. 不重新 import 或恢复任何 legacy 文件，除非重新写 SPEC → TDD Plan → Review → 用户批准

**Pros:**
- 零风险（不删文件、不改 import）
- 保留所有历史参考
- 未来读者看到 header comment 即刻知道文件状态
- TypeScript 编译不受影响（未 import 的文件不参与编译）

**Cons:**
- 磁盘保留所有文件
- header comment 添加需要 touch 22 + 30 + 2 = 54 files

**Recommendation**: **推荐**。安全、可逆、诚实。

---

## 4. Decision

| Date | Decision | Reason |
|------|----------|--------|
| 2026-06-02 | **Option C — On-disk keep** | 无需产品决策即可执行；零风险；保留架构历史；TypeScript 编译安全 |

---

## 5. Implementation (当用户决定执行时)

如果后续选择 Option B (archive) 或 Option A (remove)，需要：

1. **Pre-flight**:
   - 确认 B8 M1-M8 所有 active 组件 test 覆盖
   - 确认 tsc clean on active files only
   - 备份或 git tag 当前状态

2. **Execution** (Option B):
   ```
   mkdir -p docs/archive/tui-legacy/components
   mkdir -p docs/archive/tui-legacy/data
   mkdir -p docs/archive/tui-legacy/services
   git mv [legacy files] docs/archive/tui-legacy/[dir]/
   tsc --noEmit  # verify clean
   npm test      # verify no regressions
   ```

3. **Execution** (Option A):
   ```
   git rm [legacy files]
   tsc --noEmit
   npm test
   ```

4. **Post-flight**:
   - 更新 PROJECT_STATUS
   - 更新 PROGRESS_LEDGER
   - 更新 handoff §8 D-07

---

## 6. Related

- `docs/handoff/first-agent-current-stage-close-out-2026-06-02.md` — §7 (frozen), §8 D-07
- `docs/design/first-agent-tui-design.md` — §7: 13 项明确不产品化
- `tui/src/main.tsx` — 只 import WorkbenchLayout
- `tui/src/components/Dashboard.tsx` — legacy 7-view 主面板 (last active: B8 Phase 6)
