# Gap Priority Matrix (draft) — S1 Release Backlog (2026-06-16 run 3)

> 中间产物（非权威）。最终权威版见 `docs/current/S1_GOAL_GAP.md`。

## 优先级总览

| Priority | IDs | 为何此优先级 | 推荐下一步 |
|---|---|---|---|
| **P0 Release Blocker** | G-15, G-16, G-17, G-19 | 安全/config 卫生发布风险；用户无法据 README 启动；acceptance baseline 缺失；权威文档冲突误导后续 agent | 授权后：untrack config.yaml + gitignore；修 README 导航；指定 acceptance 集；调和审计文档措辞 |
| **P1 Must Fix for S1** | G-07b, G-12, G-03 | resume 形态未知（AC-5）；最小多步任务（AC-5）；real smoke（AC-3，依赖 G-15） | 复现大结果 resume；钉死 legacy Plan 为 S1 最小多步并验收；写 key-safe real smoke 步骤 |
| **P2 Should Fix for S1** | G-10, G-07 | 指定 S1 最小可观测事件集；L2 umbrella 核心可用待收口 | 文档动作：列必现事件；G-07b 解后确认 G-07 |
| **P3 Optional for S1** | G-18 | 命名治理已由 S 文档收口，残留属代码层（非 S1 范围） | 维持 S 文档唯一权威；不改代码 |
| **P4 S2 / Tech Debt / Out of Scope** | G-06(TD-002), G-11(TD-001), G-13(out_of_scope), G-14(boundary satisfied/activation s2) | 已确认 S1 不解决 / 边界已满足 / dormant by design | 见 TECH_DEBT.md；S2+ 重评 |
| **Satisfied baseline** | G-01, G-02, G-04, G-05, G-08, G-09 | S1 要求已满足，无开放动作（must-not-regress） | 仅回归保护 |

## 执行依赖（priority 内排序依据）

- P0：`G-15`（先；untrack 也解 G-03 key-safe 前置）→ `G-16` → `G-17` → `G-19`（在 G-15 落定后调和措辞）。
- P1：`G-07b`（resume 未知先审计）→ `G-12`（多步 + resume 验收）→ `G-03`（real smoke，依赖 G-15）。
- P2：`G-10`（先指定可观测集）→ `G-07`（收口 umbrella）。

## 状态分布（重排后）

| Status | 数量 | IDs |
|---|---|---|
| satisfied | 6 | G-01, G-02, G-04, G-05, G-08, G-09 |
| partially_satisfied | 4 | G-07, G-10, G-12, G-17 |
| unknown_needs_audit | 1 | G-07b |
| s1_blocker | 2 | G-15, G-16 |
| s1_gap | 2 | G-18, G-19 |
| defer_to_tech_debt | 2 | G-06(TD-002), G-11(TD-001) |
| out_of_scope | 2 | G-13, G-14(activation) |

（G-03 = partially_satisfied 归 P1；为避免重复计数，上表把 G-03 计入 partially。修正：partially_satisfied = G-03, G-07, G-10, G-12, G-17 共 5。最终文档以逐条 Status 为准。）
