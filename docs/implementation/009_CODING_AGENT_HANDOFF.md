# 009 Product Candidate Closure — Coding Agent Handoff

本交接面向 Claude Code + `glm-5.2[1M]`。它只授权修复 009 的 U1、U7、U8A，
不授权新增 capability、把开发执行方式写入产品、运行 E3、读取秘密或替独立 reviewer 签发结论。
外层 GLM 会话只是开发执行器；下文“不得运行真实 provider”特指不得从
`my-first-agent` 产品代码发起 provider 调用，不是否定这次已授权的 Claude Code 会话。

## 当前事实

- Claude Code 只是外部开发执行器，不是 `my-first-agent` 产品能力。
- `AgentRuntime.run_turn` 仍是唯一 production model/tool loop，不得增加第二套循环。
- 2026-07-21 U8A 报告已被
  `docs/audits/2026-07-21-009-u8a-executor-report-audit.md` 驳回。
- F1/U1、F6/U7、F9/U8A 已重新打开；U8B 尚未开始。
- F3-F5、F7-F8 只有 provisional evidence。本任务不扩写对应 capability；证据不足时诚实
  标记 `blocked`，不能顺手修改 MCP、Memory、SubAgent、Scheduler 或 Skill。

## 唯一目标

形成一个可由 fresh reviewer 独立复核并封存的 009 ordinary candidate：

1. exact manifest 能从 pinned baseline 正确 materialize 当前产品树；
2. TUI 满足 R19-R20 的 typed-action、authoritative reopen、shared event sink 与 close-stack
   lifecycle；
3. executor 的全部本地 gates 与 `--content` 在强制 deny-network 边界内通过；
4. execution log 只记录可核对的 Red/Green/receipt 和 provisional verdict；
5. executor 不编辑 reviewer controls、不运行 `--control-seal`、不写 `locally-verified`。

## Executor 可修改范围

只允许修改以下现有文件，不创建新产品文件：

- `scripts/verify_materialized_tree.py`
- `tests/architecture/test_delivery_manifest.py`
- `tests/architecture/test_delivery_manifest_v2.py`
- `agent/tui/adapter.py`
- `agent/tui/app.py`
- `agent/tui/render.py`
- `agent/cli/actions.py`
- `agent/composition.py`
- `main.py`
- `tests/tui/__init__.py`
- `tests/tui/test_actions.py`
- `tests/tui/test_adapter.py`
- `tests/tui/test_app.py`
- `tests/tui/test_approval_journey.py`
- `tests/tui/test_optional_dependency.py`
- `tests/tui/test_render.py`
- `tests/cli/test_entrypoint.py`
- `tests/scheduler/test_cli.py`
- `docs/implementation/009_DELIVERY_MANIFEST.json`
- `docs/implementation/009_EXECUTION_LOG.md`

以下 reviewer controls 对 executor 只读：

- `docs/implementation/009_INDEPENDENT_REVIEW.md`
- `docs/architecture/CURRENT_CAPABILITY_STATUS.md`

008 artifacts、其他 capability/runtime/provider 文件、`README.md`、plan/design 均只读。

## U1 / delivery repair

先阅读 009 plan 的 R1-R5、R21-R24、U1/U8 和驳回审计 A1/A3-A5，然后以准确 Red
锁定以下行为：

- schema 校验完整 baseline、operation、owner ordering 与 Git mode/type；
- 同一个 no-follow stable descriptor 完成 metadata 与 digest 校验；
- tracked delta、explicit untracked admission 与 manifest operations 一致；
- unknown/denied path fail closed，且 denied 内容永不读取或 hash；
- temporary Git index 不触碰真实 index；
- `--content` 从 exact materialized tree 做 non-editable no-deps install；
- neutral cwd 的 module 与 console entrypoint origin 不得指回 dirty tree；
- `/usr/bin/sandbox-exec` 负向 DNS/TCP probe 必须先证明阻断，Ruff、pytest、entrypoint
  及 descendants 全部继承该边界；不可用时失败，不能 best-effort；
- content gate 不得 ignore delivery tests；
- null/unsealed/missing/drifted reviewer controls 使 `--control-seal` 失败。

先确认同一 oracle 的 Red，再做最小 Green。禁止恢复 manifest generate mode、broad-add、
自动扫描纳入或修改真实 Git index。

Red gate 要求 `tests/architecture/test_delivery_manifest_v2.py` 中存在并收集以下精确 nodeid；
它们必须通过隔离 temp repo/fixtures 观察行为，不能依赖原仓库 `.git`、`.venv` 或产品树临时写入：

- `test_manifest_schema_binds_baseline_operations_owner_order_and_git_identity`
- `test_manifest_validation_uses_one_no_follow_descriptor_for_metadata_and_digest`
- `test_membership_reconciles_tracked_delta_explicit_untracked_and_operations`
- `test_denied_and_unknown_paths_fail_before_content_read_or_hash`
- `test_materialization_uses_temporary_index_without_touching_real_index`
- `test_content_gate_installs_noneditable_and_rejects_dirty_tree_origins`
- `test_content_gate_requires_inherited_deny_network_and_full_suites`
- `test_control_seal_rejects_missing_null_unsealed_and_drifted_controls`

## U7 / TUI repair

先阅读 R19-R20、U7 和驳回审计 A2。准确 Red 至少覆盖：

- Pilot 真实键盘路径：submit、approve、reject、mark succeeded、mark failed、Resume、
  合法 paused Cancel；
- startup/reopen 直接从 checkpoint 投影 pending/interrupted state，且零额外 provider/tool call；
- event loss、duplicate、reorder 不改变 authoritative controls；
- 同一个 `QueueingEventSink` 在 composition 时注入 Runtime 与 `TuiAdapter`；
- TUI、CLI 共用一个 close-stack owner；TUI 正常退出、optional-dependency failure 和异常路径
  reverse-close exactly once；
- active worker close 投影 `closing_requested`，不能安全收口时保持 `shutdown_blocked`，
  不提前关闭 resources。

Textual 是唯一 worker thread owner；adapter 不创建第二层线程。不得增加 streaming、后台任务、
多 conversation dashboard 或假的 in-flight cancel。

先用下列 nodeid/同义测试形成 Red；命名可为匹配现有测试组织做最小调整，但行为不可弱化：

- `test_projection_reopened_executing_is_unknown_effect_resume_only`：重开
  `ContinuationPhase.EXECUTING` 时显示 `interrupted unknown effect`，唯一 action 是 Resume；
- `test_pilot_reopens_durable_approval_without_calls_and_focuses_form`：直接从
  `AWAITING_APPROVAL` checkpoint mount，显示 request/preview/risk/side effect、聚焦表单，Enter
  不得默认批准，provider/tool call 都是零；
- `test_pilot_reopens_durable_recovery_without_calls_and_focuses_form`：直接从
  `AWAITING_RECOVERY` mount，显示 request/summary 与 succeeded/failed 控件并聚焦，零外部调用；
- `test_pilot_reopened_executing_dispatches_resume_only`：Cancel 不 dispatch，Resume 必须提交
  `build_resume(state)`；
- `test_tui_composition_and_adapter_share_one_queue_sink_without_terminal_events`：composition 与
  adapter 使用同一个 queue sink，terminal writer 不接收 model/tool progress；
- `test_tui_normal_exit_reverse_closes_resources_once`、
  `test_tui_optional_dependency_error_reverse_closes_resources_once`、
  `test_startup_failure_after_closeable_construction_reverse_closes_once`、
  `test_scheduler_startup_failure_after_closeable_construction_reverse_closes_once`：所有
  all-exit/partial-startup 路径按 B、A 逆序各关闭一次；
- `test_pilot_active_close_enters_closing_requested_and_stops_actions`：active worker 收到 quit 后
  禁止新 action，不 cancel；worker 安全返回并 reload authoritative checkpoint 后才退出；
- `test_pilot_close_deadline_violation_is_shutdown_blocked_without_force_exit`：deadline 超时后 UI
  与 resources 仍活着，投影 `shutdown_blocked`，不得 force-exit 或提前 teardown。

`RecoveryRequest` 当前合同只有 request/tool/binding/summary；本任务只展示这些真实字段，不能为了
对齐 ApprovalRequest 而暗中扩 checkpoint schema。使用 stdlib `ExitStack` 或同等最小结构统一
composition 生命周期即可，不得新增 lifecycle framework。

## U8A / executor closure

行为文件冻结后：

1. 手工更新 exact manifest 的 operation、owner 与 final SHA-256；不自动 admission。
2. 重跑 manifest membership、focused suites、全量 Ruff/pytest 与 `--content`。
3. 在 `009_EXECUTION_LOG.md` 修正旧 `verified`/pending/统计漂移，逐项记录可核对 evidence。
4. capability 证据不完整就保持 `implemented-candidate` 或写 evidence-backed `blocked`。
5. 不编辑 independent review/current status，不运行 control seal，不声称 E3/accepted。

## 连续执行规则

- Claude Code 在一个实现会话中持续执行：阅读目标、编写 Red、做最小 Green、运行验收、根据失败
  继续修改。不要在计划、阶段性报告或单个测试通过后停止。
- 每个目标都要先观察准确 Red，再做最小 Green，再运行对应 focused suite。测试的
  collection/setup/teardown error、普通异常、权限错误、timeout、截断、skip/xfail 都不是可信 Red
  或 Green。
- 可以使用 Bash 运行本交接要求的本地只读检查、测试和离线 materialized-tree 验收；不得用 Bash
  绕过产品的安全边界或扩大修改范围。
- provider 的 `429`、`5xx`、`Stream idle timeout` 属于开发执行器的瞬时失败：恢复同一会话继续，
  不改变产品实现，也不为此在仓库中增加开发执行基础设施或 runtime state。
- 不 reset、checkout、commit、push、tag、修改 remote，不读取 `.git` history。
- 不读取 `.env*`、credential、`.ua/`、`graphify-out/`、`.claude-runtime/`、真实日志、
  用户 Memory/Skill/MCP/SubAgent 私有目录或原仓库。
- 不运行真实 provider/MCP/E3；测试只用 fake、fixture、temp state 与强制禁网边界。
- provider 临时错误、context compaction 或 gate failure 后，从当前 workspace 与本交接继续，
  不重做已完成证据。

只有需要越过上述写权限、读取秘密/私有数据、真实外部 effect 或改变产品范围时才报告
blocker。任务长、测试多或某个方案失败都不是停止条件。

完成时只输出 executor evidence-ready 报告，并以独立一行写：

`009_EXECUTOR_READY_FOR_INDEPENDENT_REVIEW`

除此之外不得签发最终完成结论。
