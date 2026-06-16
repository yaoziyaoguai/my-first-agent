# Independent Audit Notes — S1 Priority Audit (2026-06-16 run 3)

> 中间产物（非权威）。本轮是对上一轮 S1 基线文档的**独立二次审计**，不默认相信上一轮排序/状态。

## A. 文档语义核验

1. **S1 = Baseline Usable Product，非 demo** ✓：`S_ROADMAP.md §2`、`S1_GOAL.md §0/§1` 明确 S1 不是 demo/MVP/小阶段。
2. **S 系列 ≠ 代码 v1/v2/v3** ✓：`S_ROADMAP.md §1`、`S1_GOAL.md §8` 明确声明。
3. **S1_GOAL_GAP.md 与 S1_GOAL.md 一致性** ⚠️ **发现不一致**：
   - `S1_GOAL.md §5` 标题为「Release blockers / S1 必修项（必须先解决才能宣布 S1 可用）」，其下列 RB-1（config 卫生）、RB-2（README）。即冻结目标文档把这两项框定为 **release blocker**。
   - 但 `S1_GOAL_GAP.md` 旧版把对应的 G-15/G-16 标为 `must_fix_for_s1`（P1 级），**低于** §5 的 release-blocker 框定。
   - 结论：升级 G-15/G-16 到 **P0 / release_blocker** 反而**恢复**与冻结目标文档 §5 的一致性（不是无据拔高）。
4. **TECH_DEBT.md 只收 S1 不解决的重要项** ✓：TD-001..004 均满足「S1 不解决 + 重要 + 有 revisit trigger」；结尾明确 G-15/G-16/G-07b **不入债**（规则 3）。判定合规。
5. **WORK_LOG.md 记录权威口径** ✓：run 2 已记录 G-15 降级（severity 措辞）并声明「当前权威口径以 S1_GOAL_GAP.md + WORK_LOG 为准；审计文档 §0/§10.1 待后续授权 run 调和」。

## B. 当前权威文档冲突（任务 P0 判据：会误导后续 coding agent）

- **冲突点**：`S1_CURRENT_CODE_ARCHITECTURE_AUDIT.zh.md §0`（第 19 行）「(a) 仓库中提交了真实 provider 密钥」、`§10.1`（第 201 行）「提交了真实密钥 … 当前最高优先风险」。
- **与之矛盾**：G-15 + 本轮独立核验 = HEAD/INDEX/历史均为占位符，**真实 key 从未被提交**（见 `code_evidence_index.md`）。
- **本轮约束**：禁改 `S1_CURRENT_CODE_ARCHITECTURE_AUDIT.zh.md`。
- **处理**：新增 gap **G-19** 追踪「调和审计文档 §0/§10.1 措辞」，P0/release_blocker（按任务判据），Needed action 留给后续授权 run。WORK_LOG run 2 已把此调和列为 next step，G-19 只是把它升格为显式 tracked gap。

## C. G-15 的独立新发现（最实质）

- 上一轮结论（占位符、非已暴露、无需轮换）对**已提交内容**正确。
- **新增事实**：`config/config.yaml` 设了 **skip-worktree**；**工作树**当前含 35 字符真实长度 key（被 git 遮挡）。
- 影响：真实 key 就在被跟踪路径的工作树里，仅靠脆弱本地位遮挡 → must-fix 动作更被强化；severity 仍是「config 卫生 / 发布前必须 untrack」，**不是**「需轮换已暴露密钥」。
- 上一轮 G-15 evidence 写「真实 key 当前在 gitignored `.env`」——本轮发现真实 key **也（或主要）在 skip-worktree 的 config.yaml 工作树**，需在 G-15 evidence 中补充更正。

## D. 逐条 status / blocking 复核结论（详见 gap_priority_matrix.draft.md）

- 枚举非法值修正：旧 G-09 `Status = satisfied（context/state 路径）；evidence 保真见 G-10/G-11` 含括号说明，非合法枚举 → 规范为 `satisfied`（其 S1 要求「tool result 进入 context/state」确已满足；evidence 日志保真属 TD-004）。
- G-07b 维持 `unknown_needs_audit`（只读无法确证 resume API-valid）。
- G-13 维持 `out_of_scope`（main.py 0 引用，by design）。
- G-06(TD-002)/G-11(TD-001) 维持 `defer_to_tech_debt` → 归 P4。
- G-14 L5 边界要求（boundary-clear）**已满足**；激活属 S2+ → 归 P4（标注边界已满足）。
- 无未完成 gap 被删除；新增 G-19、保留 G-07b 子项。

## E. 重点问题回答（任务 C 重点复核）

1. G-09 status 与汇总表一致性：旧 status 非法枚举，已规范为 `satisfied`，汇总同步。
2. G-15：经独立核验为占位符（已提交）+ skip-worktree 工作树真实 key；severity = config hygiene（非轮换），priority 升 P0。
3. G-16 README：是 release blocker（5 个导航链接全失效 + 自述「非面向普通用户产品」与基线定位冲突）→ P0。
4. G-17 acceptance：候选齐备但未指定 → 「acceptance baseline 缺失」→ P0（按任务判据）。
5. G-07b：维持 unknown_needs_audit（先审计/复现 run）。
6. G-13 Scheduler：维持 out_of_scope / s2_or_later。
7. G-06/G-11 转 TECH_DEBT 合理（已在 TD-002/TD-001）→ P4。
8. evidence 正文不持久化：S2+ 可延后（TD-001）→ P4，非 S1 必修。
9. task ledger / progress：legacy Plan 路径达「S1 最小可用」（G-12 partially）；独立 durable ledger = s2_or_later。
10. MCP/Skill/SubAgent/Scheduler 归类：MCP=configurable(默认关)、SubAgent V0=configurable(默认关/local_fake stub)、Skill=experimental/seam、Scheduler=dormant/out-of-scope —— G-13/G-14 表述准确。
