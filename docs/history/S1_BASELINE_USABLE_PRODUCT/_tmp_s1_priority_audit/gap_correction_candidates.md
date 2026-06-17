# Gap Correction Candidates — S1 Priority Audit (2026-06-16 run 3)

> 中间产物（非权威）。列出本轮对 `S1_GOAL_GAP.md` 提议的修正，逐条带理由。**不删未完成 gap；保留原 G-ID。**

## 1. 重排（核心交付）
将文档从「按 G 编号排列的 gap 清单」改为「按 P0→P4 排列的 release backlog」，每条增字段：`Priority`、`Dependencies`、`Recommended execution order`。新增 `Original ID Index`、`Satisfied baseline` 段。

## 2. 优先级升降（带理由）

| Gap | 旧 Blocking | 新 Priority / Blocking | 理由 |
|---|---|---|---|
| G-15 | must_fix_for_s1 | **P0 / release_blocker** | 恢复与冻结 `S1_GOAL.md §5`（RB-1 列为 release blocker）一致；独立发现 skip-worktree 工作树真实 key → 发布前必须 untrack。仍非「需轮换」。 |
| G-16 | must_fix_for_s1 | **P0 / release_blocker** | 恢复与 `S1_GOAL.md §5` RB-2 一致；5 个导航链接全失效，用户无法据 README 跑起来。 |
| G-17 | should_fix_for_s1 | **P0 / release_blocker** | 任务判据「acceptance baseline 缺失导致无法判断 S1 是否可用」；对应 AC-1/AC-2，是 §6 验收前置。 |
| G-19(新) | — | **P0 / release_blocker** | 任务判据「当前文档权威冲突会直接误导后续 coding agent」；审计文档 §0/§10.1 vs G-15。 |
| G-18 | should_fix_for_s1 | **P3 / optional_for_s1** | 命名治理已由冻结 S 文档收口；残留（代码 v 标签）明确非 S1 范围（不改代码）。S1 可动作部分基本完成 → 降级有据，非「为完整而降级」。 |
| G-09 | should_fix_for_s1 | **Satisfied baseline**（log 保真→TD-004 / P4） | 其 S1 要求「tool result 进入 context/state」确已满足；evidence 日志保真是 TD-004（P4）。同时修正非法枚举。 |
| G-03 | should_fix_for_s1 | **P1 / must_fix_for_s1** | AC-3 real smoke + AC-2 same-spine 真实侧证据是 S1 产品承诺；依赖 G-15(key-safe)。 |
| G-12 | should_fix_for_s1 | **P1 / must_fix_for_s1** | AC-5 最小多步任务 + checkpoint/resume 是 S1 must-have（§3.6）。 |
| G-07b | should_fix_for_s1 | **P1 / must_fix_for_s1**（Status 维持 unknown_needs_audit） | resume API-valid 未知，直接影响 AC-5；需先复现审计再判 satisfied/转 TD。 |

## 3. 维持不变（确认上一轮判定正确）
- G-01/G-02/G-04/G-05/G-08：satisfied baseline（独立核验通过）。
- G-06(TD-002)、G-11(TD-001)：defer_to_tech_debt → P4。
- G-13：out_of_scope → P4（main.py 0 引用证实）。
- G-14：L5 边界 satisfied（S1 要求）/ 激活 s2_or_later → P4。
- G-07（L2 umbrella）：partially_satisfied → P2（核心可用；开放子项 = G-07b[P1] + TD-003[P4]）。
- G-10：partially_satisfied → P2（需指定 S1 最小可观测事件集，文档动作）。

## 4. 枚举规范化
- 仅 G-09 旧 Status 含括号非法值 → 改 `satisfied`。
- 新增 G-19 使用合法 Status `s1_gap` / Blocking `release_blocker`。
- 其余 Status/Blocking 取值均在允许集合内。

## 5. 迁移说明（防引用断裂）
- 所有 G-01..G-18 + G-07b 保留原 ID，仅改变所在优先级段；文末 `Original ID Index` 给「旧 ID → 新优先级段」映射。
- G-19 是本轮新增（非重命名、非合并），不影响既有引用。
- 无 gap 被删除/合并。
