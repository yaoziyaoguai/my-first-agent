# 已知工具失败有界收敛计划

- Date: 2026-09-08
- Status: verified-closed
- Source: Oracle Web r6 session `first-agent-product-architecture-r6-20260908-b7c4` + Codex current-worktree verification
- Executor: Pi, `cc-switch-zhipu-glm/glm-5.3`, thinking `max`

## Outcome

同一次 `AgentRuntime._drive` 中，模型反复发起相同工具请求，而工具每次返回相同的
已知失败时，Runtime 必须在既有 `max_no_progress_replans` 阈值准确暂停。暂停前每个
`ToolResult` 都已可靠落盘；暂停后 Goal、已有事实与 active run 保持可恢复，且不再
多发送一次 Provider 请求。

用户可感知结果是：工具持续失败时，任务会清楚地停在“同一操作反复失败”的边界，
而不是继续消耗模型调用或把失败误报成进展。

## Verified defect

`agent/runtime/loop.py::AgentRuntime._drive` 在 invoke 结果持久化后，无论
`ToolResult.executed/is_error` 为何，都会执行：

```python
no_progress.reset()
no_progress_since_product_action = False
```

因此 `KnownNotExecuted`、`KnownExecutedError` 和只读 callable 异常经
`KernelToolRuntime` 规范化得到的错误结果都会清空停滞计数。现有
`test_sixteenth_known_nonexecuted_tool_attempt_pauses_without_extra_send` 只覆盖缺少
必填参数导致的 prepare 拒绝，callable 从未进入；
`test_known_executed_errors_are_not_success` 只覆盖一次失败后模型主动 blocked。

Oracle finding F1 与当前工作树一致。Graphify 只读查询也确认同一 owner 链为
`AgentRuntime._drive → KernelToolRuntime → durable ToolResult → _NoProgressTracker`；
不需要新 port、第二套 loop 或跨模块 owner。

## Result semantics

- 普通工具结果只有 `executed=True` 且 `is_error=False` 才是本轮所指的产品动作成功，
  并按既有语义重置工具失败停滞。
- `executed=False` 或 `is_error=True` 的普通已知结果都必须参与 no-progress 判断。
- browser takeover 等已有专用 pending/return 分支保持原样。
- invoke 抛出的未知异常、以及结果无法可靠持久化，继续进入既有 recovery；不得在本轮
  降级为已知未执行。
- 已执行但失败的 effectful 工具仍必须在结果 checkpoint 成功后使旧 mutable
  observations 失效。

## Persistence and pause ordering

顺序冻结为：

1. `KernelToolRuntime.invoke` 返回已知 `ToolResult`；
2. Runtime 构造 paired result fact；
3. `record_tool_result` 及附带 receipt admission 完成；
4. 结果 state 通过 `_save` CAS 成功；
5. 发出既有 `TOOL_RESULT` event；
6. 保留既有 effectful observation invalidation；
7. 更新 no-progress tracker；
8. 达阈值时复用 `_finish_no_progress`。

不得在第 4 步之前累计失败或暂停。达到阈值后的结果必须是：

- `RunStatus.LIMIT_REACHED`
- `error_code == "no_progress"`
- active run 为既有 `paused_limit`
- Goal 保持非终态
- Provider 不发生阈值后的额外 send

## Stable failure signature

prepare 与 invoke 的已知失败共用一个私有纯 helper。签名只包含：

- 工具名与 canonical arguments（复用现有 product request digest）；
- `executed`、`is_error`；
- 已受 ToolSpec output bound 约束的 result content；
- `metadata.code`、`metadata.outcome`、`metadata.exit_code`。

签名不得包含完整 metadata、`receipt_digest`、lease ID、`use_ordinal`、duration、
timestamp 或其他每次调用可能变化的回执字段。不同请求或不同稳定失败内容形成新签名；
本切片不尝试识别交替参数或交替错误组成的通用循环。

## Minimal internal design

- Production 首先只改 `agent/runtime/loop.py`。
- 在 `AgentRuntime` 内增加一个私有静态纯 helper，例如
  `_tool_failure_signature(request_digest, result)`；不新增 class、port、registry 或配置。
- prepare 拒绝路径改用同一 helper，避免当前完整 metadata digest 把易变回执误当成
  不同失败。
- invoke 结果成功持久化并完成旧观察失效后：
  - 真成功调用 `no_progress.reset()` 并清除
    `no_progress_since_product_action`；
  - 已知失败调用现有 `repair_exhausted(...)`，同一 model response 继续以
    `model_calls` 作为唯一 `observation_id`，从而一个 batch 只计一次 replan 机会；
  - 首次失败设置 `no_progress_since_product_action=True`；后续未达阈值的独立响应可复用
    既有 `no_progress_replan_required` feedback；
  - 达阈值复用 `_finish_no_progress`，不得 fatal、complete 或伪造 blocked。
- 不把暂停决策移入 ToolRuntime；ToolRuntime 仍只判断调用结果是什么。

## Vertical TDD contract

### U1 — 真实 invoke 的 KnownNotExecuted

- RED：合法参数必须进入 callable；连续 16 个独立模型响应返回同请求、同稳定失败；
  第 16 个结果落盘后暂停。
- 断言 callable 调用 16 次、paired results 16 个、Provider 总 send 数没有阈值后额外一次。
- 测试 guard 若被调用必须失败，不能把 guard exception 当成期望结果。

### U2 — KnownExecutedError 与只读异常

- `KnownExecutedError` 连续失败保持 `executed=True/is_error=True`，不进入 success
  inventory、不伪造完成，并在阈值暂停。
- READ_ONLY callable 抛异常后，经真实 `KernelToolRuntime` 规范化为
  `executed=False/is_error=True/code=tool_error`，同样在阈值暂停。
- effectful executed error 仍使此前成功的 mutable observation 失效。

### U3 — 签名稳定性与合理重置

- 仅 receipt ID、duration、lease/use ordinal 等易变字段变化时仍视为同一失败。
- 请求参数或稳定失败正文/code/outcome/exit_code 改变时形成新签名。
- 一个真实成功结果重置连续失败；成功后再次失败从第一次机会重新计数。
- 同一 model response 中多个失败只计一次 replan 机会，但每个 call/result pairing 均保留。

### U4 — recovery、CAS 与恢复边界

- invoke 未知异常仍进入 recovery，且不自动调用第二次。
- 结果持久化失败时不能先记入 no-progress 或声称安全收敛。
- no-progress 暂停保留 Goal 与事实；同一已记录 action replay 不新增 Provider/tool 调用。
- 显式后续 action 沿用现有 legality，不新增跨重启持久化 tracker。

## Protected boundaries

- `AgentRuntime.run_turn` 保持唯一 production model/tool progression 和状态变更入口。
- `KernelToolRuntime` 保持唯一 callable owner；`KernelContextManager` 保持唯一上下文选择
  owner。
- approval、lease、`EXECUTING` checkpoint、result checkpoint 与 recovery 顺序不变。
- 真实 unknown outcome 不自动重试、不自动分类。
- Goal、evidence、successful-request inventory 与 mutable-observation invalidation 语义不放宽。
- 不新增第二套 loop、service locator、compatibility fallback 或 dormant feature flag。
- Skill、MCP、browser、scheduler 不获得自授权路径。

## Non-goals

- 不修 Oracle F2：callable 前拒绝被归入 unknown recovery。
- 不修 Oracle F3：MCP schema canonicalization 漏掉名为 `title` 的真实参数。
- 不修 Oracle F4：MCP 组长退出但同组 child 存活的清理证明。
- 不修 Oracle F5：已淘汰 result 与成功请求 dedup 的联动。
- 不修 Oracle F6：纯文字请求的 non-prose 误分类。
- 不恢复累计 model/tool/token hard limits；不实现通用循环检测。
- 不修改 checkpoint schema、context eviction、compaction、审批或 UI/streaming。
- 不拆 `loop.py` 或其他巨石文件；不新增 capability。
- 不访问真实 Provider、外部 MCP、网站、profile、credential、private runtime 或未跟踪
  `tui/`。
- 本轮不 commit、push、发布或 promotion，除非用户另行要求。

## Expected files

- Production: `agent/runtime/loop.py`
- Tests: 优先 `tests/kernel/test_runtime_errors.py`，必要时最小补充
  `tests/kernel/test_tool_outcomes.py` 或 `tests/kernel/test_runtime_recovery.py`
- Documentation: 本计划；只有现有架构/用户文档与行为直接冲突时才最小更新。

扩大 production 文件范围前，Pi 必须报告具体依赖；不得顺手合并其他 findings。

## Verification

每个 U slice 只跑最小对应测试。全部实现后依次运行：

1. `.venv/bin/python -m pytest -q tests/kernel/test_runtime_errors.py tests/kernel/test_tool_outcomes.py tests/kernel/test_tool_runtime.py tests/kernel/test_runtime_recovery.py`
2. `.venv/bin/python -m pytest -q tests/kernel/test_context_manager.py tests/kernel/test_context_compaction_plan.py tests/kernel/test_runtime_compaction.py`
3. `.venv/bin/python -m pytest -q tests/architecture`
4. fresh Pi 只读审计实际 diff 与关键行为 oracle
5. 仅在以上全部通过后运行一次最终门禁：
   - `git diff --check`
   - `.venv/bin/ruff check .`
   - `.venv/bin/python -m pytest -q -rx`

成功要求：真实 invoke 反例先 RED、新行为 GREEN；结果 checkpoint 在暂停前完成；稳定签名
不受易变回执影响；未知结果与恢复语义不倒退；所有命令完整 exit 0。离线 scripted
Provider/ToolRuntime 证据不冒充真实外部 E3。

## Deferred findings ledger

- F2 / P1：`KernelToolRuntime.invoke` 的 callable 前拒绝可能被 Runtime 误归 unknown。
- F3 / P1：MCP `_canonical_schema` 递归删除 `title`，会漏掉真实参数 drift。
- F4 / P1：MCP `_shutdown_process` 可能把组长退出误当成整个进程组已清理。
- F5 / P2：被 context budget 淘汰的成功结果仍会被 durable request inventory 拒绝重读。
- F6 / P2：纯文字任务可能被误写入 `explicit_non_prose_outcome=True`。

以上必须继续独立取证、独立 spec；本轮不得顺手修复。

## Implementation notes

- Pi 首次实现会话连续约三分钟零输出、零文件变化，终止时 exit 130；Codex 在同一冻结
  合同内接手实现，没有扩大 production 范围。fresh Pi 只读审计随后正常完成并给出
  `PASS`。
- U1 的真实 RED 为：合法参数进入 callable 16 次，16 个已知失败结果均落盘，但旧实现
  又发送一次 Provider 请求并返回 `FAILED_RETRYABLE`；预期 `LIMIT_REACHED / no_progress`
  未出现。
- `AgentRuntime` 现在只在 `executed=True/is_error=False` 时重置失败停滞；其他已知结果在
  result CAS、event 和必要的 mutable-observation invalidation 之后，使用现有
  `_NoProgressTracker` 累计，并在阈值复用 `_finish_no_progress`。
- prepare 与 invoke 通过 `_tool_failure_signature` 共用稳定指纹；完整 metadata 中的
  receipt、lease、ordinal 与 duration 不参与指纹。
- production 只修改 `agent/runtime/loop.py`；测试只修改
  `tests/kernel/test_runtime_errors.py`。新增/强化的公开 Runtime 场景覆盖
  KnownNotExecuted、KnownExecutedError、只读异常、易变回执、batch、成功重置、请求变化
  与已执行失败后的旧观察失效。
- Codex focused 证据：失败/恢复及 effect ordering `55 passed`；context/compaction
  `83 passed`；architecture `69 passed`。fresh Pi 独立复跑失败路径 `50 passed`、包含
  004 的 context 路径 `95 passed`，并核验阈值后零额外 Provider send、Goal/active run
  保留及 unknown recovery 不变。
- 最终门禁：`git diff --check` 与全量 Ruff 通过；全量 pytest 为
  `3233 passed, 3 skipped`，用时 336.68 秒，完整 exit 0。
- 本轮没有真实外部 Provider/MCP E3，也没有 commit、push、发布或 promotion；这些均为
  明确非目标。
