# 009 后台工具续跑接管修复计划

状态：accepted

## 目标

修复同一后台 occurrence 在 `RUNNABLE + TOOL` 持久化检查点后崩溃时，精确重放被
Runtime 接纳、却被 `reclaim_background_run` 拒绝并错误终结为
`FAILED_FATAL/runtime_failure` 的合同错位。

用户已授权按既定顺序逐轮闭环；本轮只处理这一条恢复纵向切片，完成后停止。

## 依据

- 现有架构合同：`AgentRuntime.run_turn` 是唯一 model/tool loop 和状态变更入口；
  Scheduler 只是确定性的 external caller。
- Oracle Web 全新会话：`first-agent-r10-009-tool-replay-f3c2`，
  `gpt-5.5-pro`，第 5/5 档，2026-09-08 完成。
- Oracle 结论经本地源代码复核：`start_tool_batch` 会持久化
  `RUNNABLE + TOOL + cursor=0`；中间 `record_tool_result` 会持久化
  `RUNNABLE + TOOL + cursor>0`；`_drive` 已能从 cursor 继续，但 reducer 目前只允许
  `MODEL` phase 接管。

## 冻结合同

1. 只有已有的、精确匹配、未完成后台 `SubmitMessage` 重放路径获得 TOOL 续跑能力。
2. `RUNNABLE` 仅允许 `MODEL` 或 `TOOL` 接管；`MODEL_EXECUTING` 仅允许
   `MODEL` 且已有 durable `persisted_model_response` 时接管。
3. 接管 reduction 只改变 `revision` 和 `owner_invocation_id`；run identity、action
   identity、facts、tool batch、cursor、replay records、usage 和审批状态不变。
4. durable prefix 中的工具不得再次 prepare/invoke；只从保存的 cursor 执行 suffix。
5. `EXECUTING` 且结果未知的工具仍进入现有 recovery，不自动重试；provider intent
   未有 durable response 时仍不得重发。
6. suffix 仍经过现有 policy、approval、capacity、budget、EXECUTING、result 和
   recovery 边界；接管不等于授权或保证完成。
7. 保持 007 批次收敛与 008 最终 readback 完成语义，不改 Scheduler caller。

## 非目标

- 不新增 action、公开接口、checkpoint schema、权限、能力、重试策略或用户设置。
- 不新增第二套 loop、recovery coordinator、daemon、feature flag、service locator 或
  compatibility fallback。
- 不重置 cursor、不重发已接受批次的 provider 请求、不迁移已经 fatal 的历史 occurrence。
- 不承诺事件 exactly-once，不处理其他模块或延后发现。

## TDD 与验收

按纵向 tracer bullet 一次一条：

1. R1：使用真实 `LocalCheckpointStore`、真实 `AgentRuntime` 和 benign counting tool，
   在 tool batch CAS 已落盘、任何工具尚未调用时抛出模拟进程崩溃。基线必须复现
   `runtime_failure`；修复后 reopened store 的同一 occurrence 继续，并且每个工具只执行一次。
2. R2：在多工具批次已有 durable prefix 后崩溃；重启后 prefix 不重做，只执行 suffix，
   保持原 facts/cursor/order。
3. R3：suffix 需要 `ALWAYS` approval 时只到 `AWAITING_APPROVAL`，不得越过治理边界。
4. 复跑已有 provider unknown、tool EXECUTING recovery、terminal replay、CAS/lease 与
   007/008 相邻回归。

生产改动预期仅为 `agent/runtime/state.py` 的既有 predicate；测试集中在
`tests/automation/test_model_call_recovery.py`。若真实 Runtime 无法产生并重开上述 TOOL
检查点，或修复需要扩大 authority/schema/scheduler 范围，立即停止并报告反例。

## 验证顺序

先逐条 Red→Green，再运行 recovery/scheduler/runtime/tool/continuity/architecture 聚焦测试。
新鲜 Pi 审计必须使用 `cc-switch-zhipu-glm` / `glm-5.3` / `thinking=max` 且 PASS。
全部实现和审计修正完成后仅运行一次最终门禁：

```bash
git diff --check
.venv/bin/ruff check .
.venv/bin/python -m pytest -q -rx
```

任何失败、超时或输出截断都不算通过；最终门禁后若再改代码，门禁证据失效。

## 实施与审计记录

- Oracle Web：`first-agent-r10-009-tool-replay-f3c2`，`gpt-5.5-pro` 第 5/5 档；
  `status=completed`、`promptSubmitted=true`，committed user turn 与完整答案已捕获；专属
  Chrome PID 已退出、临时 Profile 已删除。结论：真实 P1，唯一生产改动应在 reducer。
- R1 Red：真实磁盘 batch-admission checkpoint 重开后得到
  `FAILED_FATAL/runtime_failure`；Green 后两个工具各执行一次，batch provider 不重发，
  terminal duplicate 不产生额外调用。
- R2 Red：cursor=2 的 durable prefix 重开后同样错误 fatal；Green 后成功结果与
  known-executed error 均原样保留，只执行剩余 suffix。
- R3 Red：durable prefix 后的 gated suffix 错误 fatal；Green 后停在
  `AWAITING_APPROVAL`，duplicate 不越过审批。
- 邻接守卫：`EXECUTING` checkpoint 重放仍进入 `AWAITING_RECOVERY`，provider/tool
  调用数均为 0。
- 聚焦验证：recovery module 10 passed；Scheduler 21 passed；Runtime/Tool/008 邻接
  78 passed；Context/Architecture 152 passed；touched-file Ruff PASS。
- 新鲜 Pi 审计：`cc-switch-zhipu-glm` / `glm-5.3` / `thinking=max`，只读、无工具，
  `VERDICT: PASS`。审计确认四个场景均直接保护冻结合同，不建议删减。

Pi 记录一个不阻塞 009 的 P3 后续观察：浏览器 takeover 在
`begin_browser_takeover` 与 `mark_executing` 之间的窄崩溃窗口，应在未来 Browser
轮次确认 ToolRuntime 对 pending takeover 的 prepare 明确 fail closed。本轮不扩展处理。

最终全量门禁（实现与独立审计后唯一一次执行）：

- `git diff --check`：PASS。
- `.venv/bin/ruff check .`：PASS（`All checks passed!`）。
- `.venv/bin/python -m pytest -q -rx`：PASS，`3252 passed, 3 skipped in
  330.62s`，exit code 0。

结论：009 accepted/delivered。未 commit、未 push；未进入下一轮。
