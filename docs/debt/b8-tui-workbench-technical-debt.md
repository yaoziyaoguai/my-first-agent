# B8 TUI Workbench — Technical Debt

**创建日期**: 2026-06-01
**最后更新**: 2026-06-02 (B8 方向变更 — interaction-first workbench)
**依赖文档**: `docs/roadmap/b8-tui-workbench-roadmap.md`、`docs/PROJECT_STATUS.md`、`docs/milestones/b8-interaction-first-workbench-milestones.md`
**范围**: 仅记录 B8 TUI Workbench 自身的 deferred milestone / missing prerequisite debt。不记录 B7 implementation debt。

**方向变更 note (2026-06-02)**: B8 产品方向从"信息展示中心"改为"interaction-first workbench"。旧 Phase 6B/7 debt 映射到新 M6/M7。M0 为纯文档阶段（proposal + milestones + SDD + TDD plan），不改代码。旧 Phase 1-6A 已交付能力保留为 auxiliary panels。

---

## 1. 当前 B8 Debt 总览

| # | Debt | 映射 Milestone | 状态 | 阻塞原因 | 偿还条件 |
|---|------|---------------|------|---------|---------|
| D-B8-01 | Multi-instance history browser | **M6** | **DEFERRED** | 缺 evidence namespace + multi-run storage contract | M6: EvidenceNamespace + MultiRunStorageContract 契约定义 |
| D-B8-02 | Runtime event stream viewer | **M7** | **DEFERRED** | 缺 append-only runtime event source contract | M7: EventSourceContract + EventStreamReader |
| D-B8-03 | TUI default-entry activation | **M8** | **DEFERRED** | M1-M7 未完成，Default Entry Readiness checklist 未全部通过 | M8: 用户显式批准 |
| D-B8-04 | Chinese IME / multi-line input / paste | **M8** | **PENDING** | Ink 5 useInput 中文 IME 行为待验证 | M8: IME/paste 基础测试 |
| D-B8-05 | Persistent audit log browser UI | N/A (旧 Phase) | **RESOLVED** (2026-06-02) | — | AuditLogPanel 已实现，在 Audit Lens 中复用 |
| D-B8-06 | High-risk commands remain blocked | N/A (旧 Phase) | **BY DESIGN** | 安全约束: no force push/reset --hard/rm -rf | 不计划解除; 属于安全特性 |

---

## 2. 为什么 Phase 6A 可以完成

Phase 6A (静态证据/门禁/Dogfood 浏览器) 已于 2026-06-01 完成 (e3449d4)。

6A 不依赖任何运行时能力:

- **只读取静态文件**: `docs/dogfood/*.json` — 本地 JSON, 不依赖 runtime event source
- **只解析文本摘要**: PROJECT_STATUS.md + PROGRESS_LEDGER.md — gate history 来自文档文本, 不需要真实 gate 执行记录
- **不依赖 multi-instance backend**: 单实例静态文件解析, 不需要 session/run/instance identity
- **不修改 runtime state**: 所有操作只读, 不写 checkpoint, 不触发 tool execution
- **try/catch 全覆盖**: 解析失败 → "unknown" 状态, 不崩溃

6A 是 B8 在当前约束下能做到的最大 evidence 浏览能力。

---

## 3. 为什么 Phase 6B 暂时不能做

Phase 6B 目标是多实例历史浏览器: multi-run evidence 时间线、dogfood 趋势、commit 关联。

当前缺失的前置能力:

### 3.1 session/run/instance identity model

- 每个 AutoRun loop / dogfood run / gate run 需要唯一 identity
- 当前没有 session/run/instance 标识体系
- 不存在跨实例的 "哪次 run 产生了哪个 evidence" 关联

### 3.2 evidence namespace

- 001-008 evidence 是全局 capability, 不属于特定 session/run
- multi-run evidence history 需要区分 "同 evidence 的不同 run 结果"
- 当前无 evidence namespace 设计

### 3.3 dogfood/gate history source

- 当前 dogfood 结果是单文件覆盖写入, 不是 append-only history
- gate 执行历史无持久化记录 (仅存在于 commit message 文本)
- 无结构化 gate run log

### 3.4 multi-run storage contract

- 文件命名约定: `{evidence_id}-{run_id}.json` 或 `{date}-{evidence_id}.json`?
- 无 storage layout / TTL / cleanup 策略
- 不能把当前单文件静态结果硬凑成伪多实例

**结论**: Phase 6B 不是 "现在可以实现但选择不做", 而是 "架构前提不满足, 现在做会导致假证据"。

---

## 4. 为什么 Phase 7 暂时不能做

Phase 7 目标是只读 runtime event stream 查看器: agent_log.jsonl tail + dispatcher event 增量展示。

当前缺失的前置能力:

### 4.1 append-only runtime event source contract

- agent_log.jsonl 当前格式是 debug log, 不是 structured event stream
- dispatcher events 有结构化 schema (RuntimeActionFrame), 但 **没有 append-only event log 输出**
- TUI 不能直接读 dispatcher 内存状态

### 4.2 runtime event ownership / namespace

- 哪个 event 属于哪个 session/run/instance?
- 多实例场景下 event stream 如何隔离?
- 无 event ownership model

### 4.3 backpressure / truncation / redaction strategy

- agent_log.jsonl 可能包含 secret (api_key, token)
- TUI 展示前需要 redaction 策略
- 大规模 event stream 需要 truncation/分页
- 无背压控制 (Python 写入速度 > TUI 轮询速度)

### 4.4 stream lifecycle / reconnect / failure semantics

- agent_log.jsonl 不存在时降级行为?
- Python 进程重启后如何恢复?
- TUI 暂停/恢复/过滤 需要什么 contract?

### 4.5 第二 runtime 风险

- 如果 TUI 直接 tail agent_log.jsonl 且 agent_log.jsonl 只在 Python runtime 产生, 不算第二 runtime
- 但如果为了 TUI 实时流而新增 event 写入路径, 就是第二 runtime → **严格禁止**

**结论**: Phase 7 的缺失不是 UI 层问题, 是 runtime event source contract 层缺失。不能为了 TUI 创建第二 runtime。

---

## 5. 未来偿还条件

这些 debt 的偿还路径:

### 5.1 可能由 B7 readiness 提供的能力

| 能力 | 用于 |
|------|------|
| session/run/instance identity model | Phase 6B, Phase 7 |
| evidence namespace model | Phase 6B |
| append-only structured event log contract | Phase 7 |
| runtime event source contract (Python→TUI read-only) | Phase 7 |

### 5.2 偿还顺序

```
B7 readiness SDD
  → session/run/instance identity model
    → evidence namespace model
      → multi-run storage contract
        → Phase 6B 恢复
  → append-only event log contract
    → event source contract + redaction + backpressure
      → Phase 7 恢复
```

### 5.3 不依赖 B7 的 Polish 可先行

以下 polish 项不依赖任何 B7 能力, 当前即可做:
- AuditLogPanel (auditLog.ts rotation 已就绪)
- DefaultEntryReadinessPanel (静态 checklist)
- Empty/unknown/stale states
- Keyboard hints
- Layout/navigation polish

---

## 6. 当前结论

| 项目 | 状态 |
|------|------|
| B8 旧 Phase 1-6A | **COMPLETED** — 全部能力保留为 auxiliary panels |
| B8 M0 (Direction Correction) | **IN PROGRESS** — proposal + milestones + SDD + TDD Plan 已写，待用户审阅 |
| B8 M1-M8 | **PENDING** — M0 完成后按依赖链依次推进 |
| M6 (Multi-instance History) | **DEFERRED** — 缺 evidence namespace + multi-run storage contract |
| M7 (Event Stream) | **DEFERRED** — 缺 append-only event source contract |
| M8 (Default Entry) | **DEFERRED** — M1-M7 未完成 |
| B7 implementation | **NOT STARTED** — 不在当前阶段 |
| TUI default entry | **NOT ACTIVATED** — M8 前不激活 |
| CLI fallback | **RETAINED** — CLI 为显式 fallback, 永不删除 |
| Product readiness | **NOT PRODUCT-READY** — 不声称 production-ready |

**下一步**: M0 完成 → 用户审阅 proposal → M1 实现。
