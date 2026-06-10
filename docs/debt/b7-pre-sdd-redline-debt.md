# B7 Pre-SDD Redline Debt

**创建日期**: 2026-06-01
**状态**: B7 pre-SDD cleanup completed — Ready for B7 SDD: YES, Ready for B7 implementation: NO
**依赖**: B7 前红线诚信独立审计

---

## 1. 审计摘要

B7 前红线诚信独立审计确认：当前 First Agent runtime 在单实例路径上已验证通过（8/8 evidence collected, 7/8 credible, 1/8 credible-with-caveats）。但在多实例（multi-instance）场景中存在系统性架构问题——module-level singletons、missing identity fields、no namespace isolation、in-memory-only stores——这些问题必须在 B7 SDD 中解决，不得在 B7 implementation 前散修。

**关键结论**:
- **Ready for B7 SDD: YES** — 现有 runtime contract 已足够支撑 B7 设计
- **Ready for B7 implementation: NO** — P1/P2 项必须先有 SDD 设计，再进入实现
- **P0: none** — 无阻塞安全问题或数据丢失风险（单实例下）
- **B8 current boundary CLOSED** — B8 Phase 1-6A + Polish Loop 1-2 内无未解决问题
- **TUI default entry NOT ACTIVATED**
- **B7 NOT STARTED**

---

## 2. Must Include in B7 SDD

以下项必须在 B7 SDD 中设计解决方案，不得在 SDD 前直接实现。

### 2.1 P1: Architecture-level blockers

| ID | Item | Location | Impact |
|----|------|----------|--------|
| P1-1 | `_active_skill` module-level mutable dict | `agent/skill_system/lifecycle.py` | 多实例并发写同一 dict → 数据竞争；需 session-scoped lifecycle registry |
| P1-2 | `_default_lifecycle` module-level singleton | `agent/skill_system/lifecycle.py` | import-time 构造，无法区分不同 session/instance |
| P1-3 | checkpoint single-file + missing run_id | `agent/checkpoint/` | 多 run 并发写入同一文件会覆盖；需 per-run checkpoint storage |
| P1-4 | `RuntimeActionEvent` missing identity fields | `agent/runtime_integration/schema.py` | 缺 `session_id`/`run_id`/`instance_id` → Phase 6B/7 不可实现 |

### 2.2 P2: Design-level requirements

| ID | Item | Location | Impact |
|----|------|----------|--------|
| P2-1 | `InMemoryMemoryStore` no namespace | `agent/memory/` | 多实例共享同一 in-memory dict，无法隔离 |
| P2-2 | MCP bridge module-level global | `agent/mcp_bridge.py` | session startup 操作需要对多实例可重复 |
| P2-3 | in-memory `action_log` no durable store | `agent/runtime_integration/dispatcher.py` | 重启丢失全部 event history → Phase 7 不可实现 |
| P2-4 | `SESSION_ID` import-time generation | `agent/session.py` | import 时固定，无法区分多 session |
| P2-5 | 004 Part B checkpoint save trigger design constraint | historical validation summary | B7 需重新设计 trigger 条件 |

---

## 3. Must Include in B7 SDD: Cross-Cutting Requirements

以下跨领域需求必须在 B7 SDD 中正式设计。

### 3.1 Redaction / Secret Policy

当前安全策略仅通过 AutoRun 命令中的口头约束和 CLIs/agent hooks 中的黑名单执行。B7 SDD 必须正式定义:
- 哪些字段需要 redaction（api_key, token, authorization header）
- redaction 在 pipeline 的哪个阶段执行（event emission 前 / log 写入前 / TUI 展示前）
- 谁负责 redaction（dispatcher / event log writer / TUI）
- 缺失 redaction 的后果和检测机制

### 3.2 Event Source Contract

Phase 7（Runtime Event Stream Viewer）的前置条件。B7 SDD 必须定义:
- append-only structured event log 格式（JSONL / 其他）
- event 写入者（Python runtime → file）和读取者（TUI tail）的契约
- event ownership（session_id / run_id）
- backpressure / truncation 策略
- 不允许 TUI 成为第二 runtime

### 3.3 Identity / Namespace Model

Phase 6B（Multi-instance History Browser）的前置条件。B7 SDD 必须定义:
- session/run/instance 三级 identity model
- evidence namespace（同一 evidence 的不同 run 结果如何区分）
- multi-run storage contract（文件命名约定、TTL、cleanup）

### 3.4 Checkpoint Namespace

- per-run checkpoint storage（不再单文件覆盖）
- resume 匹配逻辑（如何找到正确的 checkpoint）

---

## 4. B7 SDD Entry Gate

以下条件全部满足后，B7 SDD 才可以开始:

- [x] B8 current boundary CLOSED — B8 Phase 1-6A + Polish 1-2 内无未解决问题
- [x] B7 pre-SDD cleanup completed — 本文档创建，旧审计标记完成
- [x] Category A fix-now items completed
- [ ] 用户显式确认进入 B7 SDD

B7 SDD 完成后，需通过 SDD review gate 才能进入 B7 implementation。

**不允许在 B7 SDD review 通过前直接进入 B7 implementation。**

---

## 5. Fix-Now Items (Completed)

本轮 B7 pre-SDD cleanup 已处理:

| # | Item | Action | Status |
|---|------|--------|--------|
| A1 | `2026-05-28-full-subsystem-capability-completion-audit.md` untracked | `git add` 入库 | ✅ |
| A2 | historical real-provider validation report untracked | recorded during historical cleanup | ✅ |
| A3 | B7 前 debt 表未落到稳定文档 | 创建本文档 | ✅ |
| A4 | Redaction/secret policy 口头约束 | 写入 §3.1 B7 SDD requirement | ✅ |
| A5 | Redteam addendum 无 historical 标记 | 在 header 添加 historical 状态 | ✅ |
| A6 | 旧审计报告无 status 分层 | 每个 audit 添加 status header | ✅ |
| A7 | `2026-05-27-full-capability-red-team-audit.md` 无 superseded 标记 | 标记为 superseded | ✅ |
| A8 | PROJECT_STATUS 口径更新 | 添加 B7 pre-SDD cleanup 状态 | ✅ |

## 6. Deferred Items

| # | Item | 原因 |
|---|------|------|
| C1 | Chinese IME validation | 需实际终端验证，B7 SDD 不阻塞 |
| C2 | TUI default entry activation | 需 B7 readiness + 用户显式确认 |
| C3 | B8 Phase 6B/7 | blocked by B7 identity/event model |
| C4 | 007 confirmation='always' strategy | B7 SDD 决定，不改变当前行为 |
| C5 | `demo.md` / `task_design.md` | 需用户确认是否入库 |

---

## 7. Current State After Cleanup

| 项目 | 状态 |
|------|------|
| B8 current boundary | **CLOSED** |
| B7 SDD | **NOT STARTED** — 等待用户确认 |
| B7 implementation | **NOT STARTED** — SDD gate 未通过 |
| TUI default entry | **NOT ACTIVATED** |
| 007 caveat | **credible-with-caveats** — validation scope note maintained |
| Product readiness | **NOT PRODUCT-READY** |
