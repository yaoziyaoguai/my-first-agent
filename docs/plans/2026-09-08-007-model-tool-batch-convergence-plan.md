# 模型工具批次收敛原子性计划

- Date: 2026-09-08
- Status: accepted
- Source: Oracle Web session `first-agent-r8-007-batch-atomicity-retry-20260908-b94e` + Codex current-worktree verification
- Executor: Pi, `cc-switch-zhipu-glm/glm-5.3`, thinking `max`

## Outcome

一个已经接纳的模型工具批次中，普通已知工具结果继续逐个执行、逐个 checkpoint、逐个
排队发送事件；但 no-progress 收敛只能在该批普通结果全部产生后判断一次。它不得把
`policy_result` 插入同一批 `ToolResult` 中间，也不得因前面的失败而阻止后面本可成功的
调用。

用户可感知结果是：模型一次提出多个工具动作时，First Agent 会在既有安全边界允许的
范围内先获得完整结果，再要求模型换策略或暂停。一次失败的查询不会仅因排在批次前面，
就让后续成功查询失去执行机会。

## Verified defect

`AgentRuntime._drive` 有三条已接纳结果路径分别执行 no-progress 判断：

1. `agent/runtime/loop.py:829-868`：已成功请求的 duplicate suppression；
2. `agent/runtime/loop.py:990-1058`：`prepare` 返回已知未执行 `ToolResult`；
3. `agent/runtime/loop.py:1187-1310`：`invoke` 返回并已持久化的已知结果。

三条路径都会先可靠记录当前结果和推进 `batch_cursor`，随后却可能在批次仍有剩余调用时
插入 `no_progress_replan_required` 或直接 `_finish_no_progress`。现有
`_NoProgressTracker` 的相同 `observation_id` 只抑制同 response 的第二次计数，不能撤回
第一次过早决策。

真实 Runtime 反例已复现：前一 response 留下 S1，下一 response 发出 `[S2, S3]` 两个
稳定失败签名时，facts/provider context 可出现：

```text
tool_calls(S2, S3)
tool_result(S2)
policy_result(no_progress_replan_required)
tool_result(S3)
```

更严重的同类结果是：若首个失败已达到阈值，Runtime 可在第二个调用前暂停，因而无法
观察第二个调用可能产生的真实成功。

## Correct semantic unit

- 执行与持久化单位仍是单个 tool call/result。
- 已知工具失败的收敛观察单位是一个完成的、已接纳的 model-response tool batch。
- 每个结果仍按调用顺序独立完成 CAS 和 `TOOL_RESULT` event 排队；不得改成 batch-wide
  checkpoint，也不得并发执行工具。
- safety interruption 仍具有更高优先级：approval、真实 unknown outcome、checkpoint
  capacity、tool/background budget、browser takeover、control/cancel 等现有边界可中断
  批次。本计划只禁止 ordinary known-result no-progress 提前打断。
- response 在 tool batch admission 前被拒绝，以及 operator-origin invocation，不进入
  本批收敛语义。

## Completed-batch behavior

### Progress-bearing batch

批次中只要存在一个既有定义下的真实成功，即 `executed=True and is_error=False`：

- 整批视为 progress-bearing；
- 完成后重置 `_NoProgressTracker` 与 `no_progress_since_product_action`；
- 同批其他失败、prepare rejection 或 duplicate 不得重新建立停滞、插入
  no-progress policy 或触发 no-progress pause；
- success 在批次中的位置不得改变上述结果。

这不把“成功返回”提升为用户 Goal 已完成，也不改变 evidence/completion 规则。

### All-failure batch

全部 ordinary results 都不是成功时，只在最后一个结果持久化后评估一次：

- 签名是有序、保留重复项的复合签名；顺序与 multiplicity 仍有意义；
- 每一项复用现有 `_tool_failure_signature` 的稳定字段：product request digest、
  `executed`、`is_error`、bounded content、`metadata.code/outcome/exit_code`；
- tool call ID、receipt/lease/use ordinal、duration、timestamp 等易变字段不得进入签名；
- 单结果批次保持与现有稳定签名等价；
- 同一有序失败批次的独立 response 每批只累计一次；任一非首位稳定失败发生变化也必须
  形成新批签名并重新开始相同签名计数；
- 达阈值时必须在最后一个结果 checkpoint/event 排队之后 `_finish_no_progress`，且不能
  再发送 Provider；未达阈值时至多追加一个 batch-level policy。

### Feedback convention

- 首个普通 all-failure batch 沿用现有语义：只建立停滞，不额外制造 policy；
- 已处于停滞状态的后续 all-failure batch，未达阈值时在整批结果之后追加一个
  `no_progress_replan_required`；
- duplicate suppression 需要的现有纠错提示仍可在整批后追加一次；不得在结果之间插入；
- 同一完成批次不会同时 append policy 和 `_finish_no_progress`。

## Resume and crash contract

- `state.py::record_nonexecuted_tool_result` 与 `record_tool_result` 已正确让 intermediate
  result 保持 `TOOL` phase、final result 回到 `MODEL` phase；不修改这两个 reducer。
- 未完成批次因 approval、recovery 或其他合法 pending 后 resume 时，批次判定必须包含该
  批已经 durable 的结果前缀，不能只看新 `_drive` invocation 产生的后缀。
- 前缀必须绑定最近一个仍对应当前 `active_run.tool_calls/batch_cursor` 的
  `TOOL_CALLS` fact；不能用 conversation-global call ID 搜索代替批次绑定。
- intermediate result 已 durable 后不得重新 invoke；未可靠落盘的 executed intent 仍走
  existing unknown recovery，不能当已知失败。
- tracker 当前是 `_drive` 内存态。本计划不新增跨进程/跨 action 持久化计数器，也不承诺
  final result CAS 与后续 advisory policy CAS 之间的 exactly-once policy replay；必须保证
  该限制不会造成重复 effect 或结果/策略交错。
- 一个已完成批次只能 finalise 一次，不能在返回 MODEL 后的每次循环、compaction 或
  control repair 再次评估。

## Minimal internal design

- Production 首先只改 `agent/runtime/loop.py`。
- 保留三条 result-producing path 的 prepare、approval、EXECUTING、invoke、result CAS、
  event、budget 与 observation invalidation 顺序。
- 去掉三处各自的 per-result convergence side effect，汇合到一个 Runtime-owned 的私有
  completed-batch assessment seam。
- 允许一个小型私有 helper 或有界 invocation-local accumulator；不得新增
  `BatchCoordinator`、port、registry、配置、public contract 或通用 outcome framework。
- final-result reducer 会清空 `active.tool_calls`，因此判断 final position/批次 identity 时
  必须使用 result 前的 active batch，或使用精确绑定的 durable `TOOL_CALLS` fact，不能在
  reducer 后拿空 tuple 猜测。
- resumed prefix 的重建只服务当前 active batch；不得扫描历史以恢复 conversation-wide
  convergence tracker。

若满足 resume-prefix 合同需要修改 production 第二个文件，Pi 必须先报告具体不可避免的
原因；默认 `agent/runtime/state.py`、contracts/checkpoint schema 均不改。

## Vertical TDD contract

### U1 — Result/policy ordering

- 先构造 S1，再让一个已接纳 batch 返回不同稳定签名 `[S2, S3]`。
- 当前代码必须 RED：`POLICY_RESULT` 位于两条 `TOOL_RESULT` 之间。
- GREEN 要求 durable facts 精确为
  `TOOL_CALLS → TOOL_RESULT(S2) → TOOL_RESULT(S3) → POLICY_RESULT`。
- 使用真实 `KernelContextManager` 检查下一次 Provider 输入也保持完整批次结果在前、策略
  反馈在后；仅断言 result count 不合格。

### U2 — Threshold drains ordinary batch

- 两次相同的双调用 all-failure batch，`max_no_progress_replans=2`。
- 当前代码必须 RED：第二批首个结果可提前暂停。
- GREEN 要求四次调用、四个有序结果全部完成后才
  `LIMIT_REACHED/no_progress`；final active run 为 `PAUSED_LIMIT`、Goal 非终态、
  `tool_calls` 已清空，阈值后无额外 Provider send。

### U3 — Mixed success is position independent

- 在已有失败 streak 后覆盖 `[failure, success]`、`[success, failure]` 与
  `[failure, success, failure]`。
- success 必须来自一次真实 invocation，不得用已 suppression 的 duplicate 冒充。
- 每个 mixed batch 都重置 streak、无 no-progress policy/pause；随后需要两个独立相同
  all-failure batch 才能在 allowance=2 时暂停。

### U4 — Success plus duplicate

- 覆盖 `[new failure, success(U), duplicate(U)]`。
- U 只真实调用一次，duplicate 保留 paired nonexecuted result；整批仍 progress-bearing，
  不追加 no-progress policy、不暂停。

### U5 — Whole-batch stable signature

- 两个 batch 首个失败相同、仅第二个稳定失败不同：必须重置相同签名计数。
- 仅改变 call IDs、receipt IDs、lease/use ordinal 或 duration：不得重置。
- 重复 changed batch 时精确在阈值后的 final result 暂停。

### U6 — Three result entry paths

- 至少覆盖 duplicate suppression、prepare-time `ToolResult`、invoked
  `KnownNotExecuted`/`KnownExecutedError`/normalized read-only exception 在 nonfinal 与
  final 位置的代表场景。
- unknown/unadvertised tool 在 admission 前被拒绝的测试不能冒充 accepted-batch coverage。
- 既有 approval、unknown recovery、budget、browser takeover、CAS/action replay 测试必须
  继续通过；实现若改动相关路径，再增加最小 fault-injection regression。

## Protected boundaries — do not touch

- `AgentRuntime.run_turn` 仍是唯一 production model/tool loop 和状态 owner。
- `ContextManager` 仍独占上下文选择；`ToolRuntime` 仍独占 callable 调用。
- per-result EXECUTING/result checkpoint、receipt admission、event queueing 与 recovery 顺序
  不变。
- effectful executed error 仍在 result checkpoint 后使旧 mutable observations 失效。
- duplicate invocation 抑制、successful request inventory、approval、limits、takeover 与
  completion/evidence authority 不放宽。
- Runtime event 仍是 lease 释放后的 buffered delivery，不宣称 exactly-once durable outbox。

## Non-goals

- 不顺手修 read-back 成功可能在 accepted batch 中途 auto-complete 的独立 P1。
- 不顺手修 background replay reclaim eligibility 与 reducer phase 不一致的独立 P1。
- 不修 callable-before-execution refusal、MCP schema `title`、evicted-result reread 或纯文字
  non-prose 分类等既有 finding。
- 不实现 persisted convergence tracker、通用循环检测、并发工具调用、batch-wide result
  commit、durable event outbox 或历史 transcript rewrite。
- 不拆 `loop.py`，不新增第二套 loop、scheduler、service locator、compatibility fallback、
  dormant flag、capability 或用户配置。
- 不访问真实 Provider、外部 MCP、网站、profile、credential、private runtime 或未跟踪
  `tui/`。
- 本轮不 commit、push、发布或 promotion，除非用户另行要求。

## Expected files

- Production: `agent/runtime/loop.py`
- Tests: `tests/kernel/test_runtime_errors.py`；unknown recovery 的 fault injection 最小补充
  `tests/kernel/test_runtime_recovery.py`
- Documentation: 本计划；`docs/architecture/KERNEL_ARCHITECTURE.md` 只最小澄清
  no-progress 的 completed-batch 边界

## Implementation and review record

- 两个承重反例先 RED：policy 插入双结果中间；阈值在双调用第二项前提前暂停。最小实现后两者
  GREEN，且仍逐结果完成 EXECUTING/result CAS 与 event 排队。
- Pi executor 使用 `cc-switch-zhipu-glm/glm-5.3`、thinking `max`，15 分钟内有进程但零输出、
  零文件变化，已终止并由 Codex 接手；fresh 只读 Pi 审计再次保持网络连接 12 分钟但零输出，
  已终止，不能计作审计 PASS。
- 本地 fresh 双轴审查发现并修复两项：resume 事实原先未限定当前 `run_id`；duplicate 恢复原先
  依赖英文展示文案。现按当前 run 的 fact namespace fail closed，并用稳定
  `metadata.code=duplicate_product_request` 重建内部语义。
- 独立复核结果：Standards PASS；Spec PASS。覆盖 mixed success 的三个位置、同批 duplicate、
  ordered composite signature、易变 receipt 字段、prepare/invoke 三类已知结果、approval 的
  成功/拒绝前缀、unknown recovery synthetic 前缀与 old-run decoy。
- Focused gates：结果/恢复/Tool Runtime 59 passed；context/compaction 83 passed；architecture
  69 passed；touched-file Ruff PASS。
- Final gate：`git diff --check` PASS；全仓 Ruff PASS；pytest `3247 passed, 3 skipped`
  （458.24s，exit 0）。全量套件仅执行一次；记录本行后不重复全量测试。

## Verification

实现按 U1-U6 分组执行最小 RED/GREEN。全部完成后：

1. `.venv/bin/python -m pytest -q tests/kernel/test_runtime_errors.py tests/kernel/test_tool_outcomes.py tests/kernel/test_tool_runtime.py tests/kernel/test_runtime_recovery.py`
2. `.venv/bin/python -m pytest -q tests/kernel/test_context_manager.py tests/kernel/test_context_compaction_plan.py tests/kernel/test_runtime_compaction.py`
3. `.venv/bin/python -m pytest -q tests/architecture`
4. fresh Pi 全新只读会话审计实际 diff、旧代码 RED、新代码 GREEN、三条 entry path、
   checkpoint/approval/recovery/limits 不倒退
5. 上述全部通过后仅运行一次最终全量门禁：
   - `git diff --check`
   - `.venv/bin/ruff check .`
   - `.venv/bin/python -m pytest -q -rx`

成功要求：至少两个真实反例先 RED；所有结果在 policy/pause 前 durable；mixed success 的
位置不影响收敛语义；整个失败 batch 的任意稳定成员变化都会形成新签名；所有命令完整
exit 0。离线 scripted Provider/ToolRuntime 证据不冒充真实外部 E3。

## Deferred findings ledger

- P1：`_finish_if_durable_evidence_is_complete` 在单个成功 `read_file` 后运行，未检查当前
  accepted batch 是否还有剩余调用，可能提前 `complete_run`。
- P1：background replay 在 `loop.py` 把 RUNNABLE/TOOL 视为 safely reclaimable，而
  `state.py::reclaim_background_run` 只接受 MODEL phase；需要独立真实复现。
- P1：callable 前拒绝可能被 Runtime 误归 unknown recovery。
- P1：MCP `_canonical_schema` 可能递归删除真实 `title` 参数。
- P2：context 已淘汰结果但 successful-request inventory 仍阻止同参数重读。
- P2：纯文字任务可能被错误标记为 explicit non-prose outcome。

以上必须逐项独立审计、独立 spec；007 不得借机合并。
