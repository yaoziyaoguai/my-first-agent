# 2026-08-26-002 architecture deepening program

## Scope

延续 001（evidence closure）的深化程序，按序完成三个候选；每个候选要么
「实现并验证」，要么以具体 deletion-test/代码证据在本文档明确拒绝。前置：
001 的 evidence-closure 候选已完成、独立审计通过（1473-pass baseline），
本程序不重开该候选。

非目标：机械拆文件、pass-through 层、service locator、config blob、
dormant flag、compatibility path、单 adapter 假想 seam。不变量：
`AgentRuntime.run_turn` 唯一 production model/tool loop 与状态变更入口；
`ContextManager` 独占模型上下文；`KernelToolRuntime.prepare/invoke` 唯一
外部工具接口与最终权限/effect gate；EXECUTING checkpoint → invoke →
result checkpoint 顺序不变。

验证约定：每阶段只跑 focused suites + touched Ruff + `git diff --check`；
全量 pytest 由监督审计在树稳定后执行一次。

---

## Stage A — Runtime-owned tool governance（已实现）

### 选择与边界

`KernelToolRuntime.prepare` 内的 capability 特定治理知识按簇分布：citation
（sidecar 写入 canonical 化 + manifest builder 准入门 + binding 失败映射，
全部 prepare 侧）、source（source_authority 门 + `_source_result` 归一）、
process（candidate/lease/draft 校验/receipt 铸造）、memory/preference
（admission 门）。本阶段选择 **citation 簇完整迁移**；source/process 簇
留作后续候选（记录于「剩余风险」）。

### 接口（agent/runtime/tool_governance.py，新文件）

- `CitationGovernance.assess_intent(tool_name, side_effect, safety_policy,
  arguments, context) -> CitationIntentRuling`：一次裁决覆盖 sidecar 写入
  canonical 化（exact Runtime manifest + 单 transport newline 归一）与
  manifest builder 五类拒绝（not_required / artifact_not_authorized /
  goal_identity_mismatch / source_not_citable / entries_not_one_to_one）。
- `CitationGovernance.binding_failure(safety_policy) -> GovernanceRejection |
  None`：citation binding 失败映射；非 builder 返回 None，通用兜底留在
  Runtime。
- 裁决只携带治理事实（code/message/canonical 参数）；known-not-executed
  `ToolResult` 仍由 `KernelToolRuntime._error` 统一铸造——最终 gate 不移动。

### Deletion test

删除 `CitationGovernance` → canonical 化、六类拒绝消息与 binding 映射必须
回到 `KernelToolRuntime.prepare` 内联分支（tools.py 净减约 230 行即该知识
的体积）。通过。

### 测试面

- 现有 citation 测试全部经 `KernelToolRuntime.prepare()` 公共接口
  （tests/continuity/test_research_evidence.py），迁移前后不变——它们证明
  唯一外部接口与最终 gate 行为不变。
- 新增 tests/kernel/test_tool_governance.py（10 个接口测试）：直接覆盖裁决
  语义，无需构造 KernelToolRuntime/registrations，fixture 显著小于
  prepare-through 测试。无实现私有测试需要迁移（原本就不存在）。

### Red/Green 证据

- Red：test_tool_governance.py collection error（模块不存在）。
- Green：focused 61 passed（tool_governance + research_evidence +
  cutover_absence + tool_registration_composition）；tests/kernel 199
  passed；tests/process+web+skill 178 passed；touched Ruff 与
  `git diff --check` 干净。

### 变更文件

- 新增 `agent/runtime/tool_governance.py`、`tests/kernel/test_tool_governance.py`
- `agent/runtime/tools.py`：prepare 的 citation 分支替换为单一裁决消费点；
  删除 `_canonical_citation_sidecar_content`；构造 `self._citation_governance`。
- `tests/architecture/test_cutover_absence.py`：expected 集合加入新文件。

### 行为保真

六类拒绝的 code 与 message、canonical 化算法（digest 集合命中 +
`CitationManifestV1.from_json` + goal/artifact 绑定 + 尾换行剥离）、
sidecar 先于 builder 的判定顺序，均逐字迁移；分支插入位置（validate
arguments 与 public_web 门之后、source authority 门之前）不变。

---

## Stage B — POSIX process ownership（已实现共享 seam；初轮拒绝被 Standards blocker 推翻）

### 决策反转的依据

初轮以「单一严格 oracle 消费者」拒绝共享抽象（原始矩阵见下）。Standards
审计确认 `ChildProcessRunner` 对外声称 `process_terminated` 却只 wait
leader：无 verified PGID、无 group-liveness oracle、getpgid OSError 退化
`os.kill(pid)` 单进程信号——subagent 成为严格 oracle 的第二个真实消费者，
「两个 adapter 才是真 seam」条件成立，共享抽象从假想变为真实边界。

### 实现（agent/process/group.py，新文件）

- 接口：`verified_group_identity(pid)`（start_new_session PGID 强校验，
  ESRCH 保留 expected identity）、`group_alive(pgid)`（signal-0 唯一确认
  oracle，非 ESRCH OSError fail closed）、`terminate_group(proc, pgid,
  term_grace_seconds, kill_grace_seconds, verify_budget_seconds)`（TERM→
  bounded wait→probe→KILL→bounded wait→bounded verify；无法确认消失 →
  raise `ProcessCleanupError`）。模块只拥有 OS 层 group 事实，不定义结果/
  receipt taxonomy；grace/预算秒数由调用方产品合同传入。
- `agent/process/runner.py`：ownership 四个私有函数删除，改经
  `process_group.*` qualified 调用（fault-injection seam 统一在
  `agent.process.group`）；draft/group_reaped taxonomy 不变。
- `agent/subagent/process_runner.py`：spawn 即 verified identity（失败 →
  有界 best-effort leader 清理 + `termination_unconfirmed`，绝不静默退化
  单进程信号）；deadline kill 与 leader 退出后的孤儿治理都走
  `terminate_group`；`UNCONFIRMED` 扩展覆盖 termination/cleanup 无法确认；
  outcome 未知叠加 cleanup 失败不再声称 TERMINATED（unknown ≠ terminated）。
- 结果/receipt taxonomy 完整保留在各自 caller：`ProcessExecutionDraftV1`
  （Kernel 铸 receipt）与 `ChildRunResult`/`TerminationReceiptState`。

### Red/Green 证据

- Red（先失败）：`tests/subagent/test_process_termination_contract.py`
  3 个合同测试（identity 失败与正常 kill 不可区分 / TERMINATED 无 probe /
  cleanup 失败 + outcome 未知仍 TERMINATED）+ `tests/process/test_group.py`
  6 个接口测试（模块不存在）。全部按预期断言失败。
- fault-injection：`test_terminate_group_kills_same_group_descendant_and_confirms`
  用同 group descendant 证明整组终结；`_unconfirmable` 注入证明有界预算内
  fail closed。`test_runner_group_cleanup.py` 的 patch seam 随知识迁移到
  `agent.process.group.*`（语义不变）。
- Green：tests/process + tests/subagent 共 119 passed。

### 初轮行为矩阵（保留作历史记录）

### 行为矩阵（agent/process/runner.py vs agent/subagent/process_runner.py）

| 维度 | process/runner.py | subagent/process_runner.py |
|---|---|---|
| PGID identity | `start_new_session` + `_verified_pgid` probe：observed==pid 强校验，mismatch/EPERM → `ProcessCleanupError`；ESRCH 保留 expected identity（:299-320） | kill 时惰性 `os.getpgid(pid)`，无 identity 校验（:198-207） |
| TERM/KILL | TERM→wait(grace)→probe→KILL→wait(grace)→6s 单调 verify 循环；delivery 非证明，liveness 是唯一 oracle（:210-250） | 单次 TERM killpg→wait(1s)→SIGKILL killpg→无界 `proc.wait()`；OSError 回退单进程 `os.kill(pid)`（:175-183, :198-207） |
| Reap | 先 reap direct child 再探测 group；finally 兜底 reap + 显式关流（:143-169） | `proc.wait()` 收尸 + 显式关 stdout；无 group-wide 孤儿处理（:184-196） |
| Liveness 不确定 | signal-0 probe fail-closed；post-spawn 不可确认 → `ProcessCleanupError` → Runtime unknown recovery（:253-272, :323-341） | 不在 OS 层证明；产品层以 `UNCONFIRMED` receipt 覆盖一切不确定（:142-151） |
| Timeout/output | select 增量排空 + stream/combined caps + truncation 标志 + sha256 + 投影（:95-141） | poll 循环；stdout 一次性有界 read（8KiB+1 溢出→None）；stderr DEVNULL 防 deadlock（:155-190） |
| 错误映射 | spawn 失败 → SPAWN_FAILED draft（known-not-executed）；不可确认 → 抛异常；返回 closed `ProcessExecutionDraftV1` 交 Kernel 铸 receipt | 返回 `ChildRunResult` + `TerminationReceiptState.TERMINATED/UNCONFIRMED`（deadline kill/非 0/非法 JSON/oversized/cleanup 失败均 UNCONFIRMED） |
| 身份/审批绑定 | 无（immutable resolved inputs；Goal/lease/approval 在 Kernel） | credential env-name、0600 no-follow 临时 config、PYTHONPATH 钉住同源 agent、200KB 上限 |

### 初轮拒绝理由（已被上面的决策反转取代）

1. **知识图无结构关系**：graphify `path` 在两文件间不存在边——它们不是同一
   簇被拆开的两半，而是两个各自完整的产品 owner。
2. **交集是 pass-through**：真正共享的机械只有 `start_new_session=True`、
   `killpg`、单调 deadline（各约 10 行）。
3. **分歧是合同本身，不是实现偶然**：receipt/draft taxonomy 必须留在
   caller——最终实现正是这样切的（共享 OS 层 ownership，taxonomy 各自保留）。
4. **严格 liveness oracle 当时只有单一真实消费者**——subagent blocker 使其
   成为第二个，此条不再成立。

### 残余风险（现行为准）

- 初轮记录的两条 subagent 风险——`_kill_group` 的 `os.kill(pid)` 单进程
  回退不覆盖 descendant、终局无界 `proc.wait()`——已随共享 verified group
  ownership 的落地消除：kill 与孤儿治理都经 `terminate_group` 的有界
  TERM→KILL→verify，identity/liveness 无法确认时 fail closed，不再声称
  terminated/reaped。
- 平台残余：macOS 可能在原 group 被 KILL 后立即复用 PGID，signal-0 对
  foreign group 返回 EPERM → 诚实 `ProcessCleanupError`（bounded unknown）。
  tests/process/test_runner_group_cleanup.py 已把该 fail-closed 路径作为
  合同接受，不误报 REAPED。
- child runtime 固定为**空 ToolRuntime、无 local_process**（build_child_runtime
  的 docstring 合同）；child group 内不存在任何产品子进程，parent 的 group
  kill 边界即完整的产品进程边界。

---

## Stage C — workspace runtime assembly（teardown 修复已实现；assembly 抽象被拒绝）

### 已实现：scheduler teardown 注册方向

- 事实链：ExitStack 按注册逆序 unwind（最小实验验证）；scheduler 原代码
  `for closeable in reversed(composition.close_stack): callback(closeable)`
  实际产生**构造正序**关闭，违反 Lifecycle ownership 合同的 reverse-close
  不变量与自身注释意图；因 scheduler close_stack 当前为空而潜伏，且现有
  测试只用单 closeable 断言 once-ness，无法暴露方向错误。
- Red：`test_scheduler_close_stack_unwinds_in_reverse_construction_order`
  （两个有序 closeable 钉住顺序）先失败（got 构造正序）。
- Green：main.py 注册改为正序遍历（+2 行解释注释），与 main() 的即时注册
  模式一致；focused：tests/scheduler/test_cli.py + tests/cli/test_entrypoint.py
  共 22 passed。

### 拒绝：更大的 assembly interface

- `build_composition` 是 **CLI/scheduler 的主 workspace 工厂**（不是唯一
  runtime 工厂）：产品差异全部体现为 15 个显式 kwargs（7 必填 + 8 默认，
  2026-08-26 核实）、frozen dataclass、无全局 getter/service locator/
  mutation owner。`build_child_runtime`（agent/subagent/runner.py:51）是
  独立的受限 child 构造器——subagent 包内唯一 import loop 的位置，固定
  in-memory store、空 ToolRuntime、无 ContextSource、max_model_calls=1，
  不是第二套 loop。
- 剩余机械重复只有 workspace resolve+is_dir 校验（3 行×2）与 ContextLimits
  字面量（1 行×2）；`_build_provider`/`_build_provider_descriptor` 已是共享
  helper。提取剩余重复 = shallow pass-through，deletion test 失败（删除后
  4 行回到两个 caller，无复杂度重现）。
- main() 的「closeables 列表进 composition.close_stack + ExitStack 即时注册」
  双记账是两种用途（组合记录 vs 执行 owner），非重复决策路径，保留。

---

## Mega-module 审计（production source）

行数是**审计时点（实施前）的排序依据**，不是拆分理由；实施过的候选另注
当前行数。

| 候选（行数） | 裁决 | 保留/实施理由 |
|---|---|---|
| runtime/contracts.py (3722) | 保留 | 纯合同面：typed dataclass/enums/digest，被全仓 import 与跨模块合同测试钉死。零 information hiding 可迁——deletion test 下没有任何隐藏实现会重现于 caller；拆分只产生 contracts 间 import 分层决策与全仓 churn。 |
| runtime/loop.py (3281) | 保留 | AGENTS.md 冻结的唯一 model/tool loop；体积来自 control 处理与 turn 决策序列必须同 owner。evidence governance 已于候选 1 迁出；继续按簇拆会把决策顺序散布成第二 loop 风险。 |
| runtime/state.py (3180) | 保留 | 012 trusted-continuity 的 canonical 状态机 reducer（facts/goal/control 状态迁移 + identity digest），单一职责高内聚；loop 与全部 continuity 测试消费同一组转移函数。 |
| runtime/checkpoint.py (1804) | 保留，但不是单一职责 | 两个内聚簇：store/lease/CAS（checkpoint error 族 + LocalCheckpointStore/_MemoryLease/InMemoryCheckpointStore，约 L67-390）与 schema codec/迁移 + no-follow 安全校验 helpers（L391-1804，约 1400 行）。codec 提取记为**下一个 Strong bounded candidate**：按「一点一点」规则 deferred 到下一 loop——本轮已落地 tool governance + POSIX group seam 两个大改动，再动 ~1400 行会制造第二个大审查面。session/restart selection 归 agent/continuity（sessions.py/restart.py），不在本文件。 |
| provider/normalize.py (1280) | 排除 | provider codec 本轮明确排除。 |
| runtime/evidence.py (1242) | 保留 | 候选 1 已深化：derive + 两个 assessment 方法的窄接口；不为行数拆。 |
| runtime/tools.py (1197，source 簇迁出后现为 1083) | **Strong 候选，已实施** | 见下。 |
| main.py (1117) | 保留，按簇评估 | 五个簇：parser（argparse 定义）、setup（workspace/state-root/session 校验）、provider composition（_build_provider/_resolve_runtime_provider + credential env 读取）、interactive（main() 的 TUI/REPL 装配与运行）、scheduler（run_schedule()）。parser/setup 提取当前不过 deletion/information-hiding：每个 flag 恰好被一个入口的装配 1:1 消费，抽「setup helper」只是 pass-through 配置层（删除后 ~10 行回到两个 caller，无隐藏复杂度）；provider composition 已是共享 helper（_build_provider/_build_provider_descriptor 两入口共用）。未来触发：出现第三个共享同一 setup 序列的入口（如 worker daemon）时，setup seam 才有第二个真实 adapter。composition root 调用点保留在各自入口，保持产品选择显式——不声称整个文件是一个模块。 |
| runtime/context.py (1111) | 保留 | ContextManager 独占模型上下文选择（AGENTS.md 不变量），单一职责。 |

### 已实施：tools.py 的 source governance 簇（第二个完整簇）

- 选择依据：Stage A 已建立 `tool_governance.py` 为 Runtime 拥有的治理
  home；source 簇（prepare 的 `source_authority_required` 门 + invoke 的
  `_source_result` governed outcome 归一，约 140 行）与 citation 簇同 seam、
  同变化边界（governed source 工具演进）。deletion test：删除
  `SourceGovernance` → authority 门与**八类** outcome 归一拒绝（含
  `SourceReceiptV1.create` 的 Kernel 侧 receipt 铸造）回到
  KernelToolRuntime 分支。process authority governance 簇（~300 行，F1
  lease 语义）记录为下一候选：本轮 process 领域已落地共享 POSIX seam，
  避免同轮叠加审查面。
- 接口：`SourceGovernance.assess_authority(authority_required, arguments,
  context) -> GovernanceRejection | None`（原 prepare 门语义逐字）；
  `normalize_result(intent, spec, raw_result) -> ToolResult`（原
  `_source_result` 逐字迁移：metadata 白名单、bounds、receipt 铸造、
  source_refs/data_classes/truncated 投影）。`CitationRejection` 更名为
  capability-neutral 的 `GovernanceRejection`（仅模块内使用，外部测试只做
  属性访问）。
- Red/Green：首批 5 个接口测试先 ImportError Red（函数级 import 隔离，
  citation 10 个测试持续 Green）；Spec review 补充的 5 个拒绝族测试
  （output/metadata-policy/metadata/receipts-count/receipt-draft 各自
  oversized 或 malformed）直接 Green——八个 rejection code 均有直接接口
  测试。tool_governance + source_contracts 共 29 passed。既有 prepare/invoke
  穿透测试（test_source_contracts.py）不变且通过——唯一外部接口与最终
  gate 未移动。
