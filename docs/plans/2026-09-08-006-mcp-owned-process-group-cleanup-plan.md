# MCP 自有进程组清理证明计划

- Date: 2026-09-08
- Status: verified-closed
- Source: Oracle Web r7 session `first-agent-product-architecture-r7-20260908-c91e` + Codex current-worktree verification
- Executor: Pi, `cc-switch-zhipu-glm/glm-5.3`, thinking `max`

## Outcome

每次 MCP stdio 调用结束时，`process_exit_confirmed=True` 必须证明本次受控 spawn
拥有的 leader 已回收、原 process group 已消失、transport 已完成有界关闭。leader
单独退出、成功发出信号或无法再通过 dead leader 查询 PGID，都不能冒充整个组已清理。

用户可感知结果是：MCP server 派生同组 child 后，即使 leader 先退出，First Agent 也
不会把仍存活的 child 留作隐式后台进程并错误解除 durable safety latch。无法证明清理
完成时，系统保持 fail closed，并如实保留既有 recovery/隔离边界。

## Verified defect

`agent/mcp/bridge.py::_spawn` 以 `start_new_session=True` 创建由本次 invocation 拥有的
POSIX process group，但 `_shutdown_process` 只在 `await process.wait()` 未成功时调用
`killpg`。如果 leader 正常退出、同组 child 继续存活，当前代码会立即设置
`exited=True` 并返回 True。

`run_stdio_session` 随后把这个 True 写入 `commit.process_exit_confirmed`；对已知
`EXECUTED`/`NOT_EXECUTED` outcome，finally 会据此允许 `latch.clear(...)`。因此当前
实现把 leader 终态错误提升为 group cleanup proof。

Oracle 在 Linux 的 benign sleeper 探针中观察到 leader 已退出、child 仍属于原组且仍
存活，同时原方法报告 confirmed 并走 clear。Codex 在当前完整源码中确认这条生产调用链
存在；Linux 探针不冒充 macOS 或声明依赖环境验收，真实 RED/GREEN 必须在本机项目环境
重新取得。

## Frozen lifecycle semantics

- `leader_reaped`、`owned_group_absent`、`transport_closed` 是三项独立事实；只有三者均
  成立才能得到 `process_exit_confirmed=True`。
- `owned_pgid` 只能由本次受控 `start_new_session=True` spawn 路径产生并立即保存；不能
  来自 catalog、server 消息或 leader 退出后的 `os.getpgid(leader_pid)`。
- leader returncode、signal send success 或针对 dead leader 的 `ProcessLookupError` 都
  不能单独证明原 group 已消失。
- 组 probe/kill 的权限错误、其他 OS 错误、timeout、cancellation 或 transport close
  未确认，一律得到 False；不得清 latch。
- 业务 outcome 与资源状态继续独立：`UNKNOWN` 即使 group 已确认清理也保持 ARMED；已知
  result 只有 cleanup proof 成立才可按既有 token/revision/full binding 清 latch。
- 整条 cleanup（stdin close、graceful leader wait、必要的 group kill、leader reap、
  group absence confirmation、process transport close）受一个整体 deadline 约束。
- 不具备所需 POSIX group lifecycle primitive 的 host 必须在 spawn 前零副作用拒绝；不
  实现 Windows fallback，也不把 host adapter 的 qualification 冒充 portable Kernel。

## Minimal internal design

- Production 只改 `agent/mcp/bridge.py`。
- `_spawn` 在调用 `anyio.open_process` 前检查所需 POSIX primitives；成功后从受控 handle
  保存正的 `owned_pgid`（该路径下为新 session leader PID），与 process handle 一起仅在
  bridge 内部传递。
- `_shutdown_process` 显式接收 frozen `owned_pgid`，不在 cleanup 晚期从 leader 反查。
- 保留 shielded cleanup；先有界关闭 stdin/等待 graceful exit，再无论 leader 是否已退
  都检查原 group。组仍存在则向 frozen PGID 发 SIGKILL，并在剩余 deadline 内等待 leader
  回收、反复确认 group 不存在和关闭 transport。
- group absence 只由对 frozen PGID 的明确不存在结果证明；权限/未知错误不是不存在。
- 复用现有 `_CommitState.process_exit_confirmed`、`_finalize_outcome` 与 latch finally；不
  新增 supervisor、registry、后台 reaper、port、公共 schema 或第二套 executor。

## Vertical TDD contract

### U1 — 真实 leader-exit/child-survives 反例

- 在 `tests/fixtures/mcp/behavior_server.py` 增加 test-only mode：server spawn 一个同组
  benign child；child 关闭继承 stdio 后在有界 watchdog 下存活；leader 返回已知成功。
- fixture 通过 pidfile/marker 明确记录 leader PID、child PID 与 PGID，测试亲自确认 child
  确属本次 group，不能只注入布尔值。
- RED 必须是旧实现返回 `process_exit_confirmed=True`/clear，而 child 仍活着；不能把测试
  自身 timeout、管道未关或 fixture 协议错误当作 RED。
- 测试必须在 `finally` best-effort kill frozen group，任何失败都不能留下进程。

### U2 — 组清理成功后才允许已知结果清 latch

- 同一真实 fixture 在修复后必须确认 leader reaped、child 终止、frozen group 消失、
  transport close 完成，然后 `process_exit_confirmed=True`。
- outcome 保持既有已知分类，durable latch 恰好按现有 binding/revision/token clear；不得
  为通过测试绕过真实 latch。

### U3 — 生命周期变体与不确定性

- 覆盖 leader 已先退出但同组 child 存活，证明 cleanup 使用保存的 PGID。
- 覆盖 child 关闭 stdio 与继承 stdout/stderr 的至少一个真实路径，保持整体有界。
- 对 group probe/signal 权限错误或其他不确定性做确定性故障注入：不得返回 True，不得
  clear latch，不得自动重试工具。
- transport close 未完成或失败不能产生 confirmed；测试故障替身不得留下真实 child。

### U4 — cancellation 与 outcome/latch 分离

- 既有 hanging-call、bridge.close cancellation 与 oversized transport tests 继续通过。
- `UNKNOWN + confirmed cleanup` 继续保持 ARMED。
- `known result + unconfirmed cleanup` 必须最终变为既有 UNKNOWN/隔离结果并保持 ARMED。
- submit timeout/replay/restart 不新增 MCP invocation，不产生自授权 clear。

### U5 — 纵向组合回归

- 实际本地 fixture 经现有 `McpExecutor -> KernelToolRuntime -> AgentRuntime -> durable
  McpSafetyLatch` 路径，继续满足 approval、`EXECUTING` checkpoint、invoke、result/recovery
  顺序。
- 若现有纵向测试已充分覆盖上述组合，只强化行为 oracle；不为测试重复搭建第二套 Runtime。

## Protected boundaries

- `AgentRuntime.run_turn` 保持唯一 production model/tool progression 与状态变更入口。
- `KernelToolRuntime` 保持唯一 callable owner；bridge 只拥有 MCP transport lifecycle。
- approval、lease、`EXECUTING` checkpoint、result checkpoint、unknown recovery 顺序不变。
- durable latch 只由 exact owner/full binding 清除；cleanup proof 不推导业务 outcome。
- portable core 与 host adapter 分层不变；本切片不承诺 Windows/Linux/macOS 等价验收。
- 004 的 source-first/history-oldest-first/pinned/atomic grouping 保持不变。
- 005 的成功重置、已知失败收敛、result CAS 顺序、effectful observation invalidation 与
  unknown recovery 保持不变。
- 不新增第二套 loop、service locator、compatibility fallback 或 dormant feature flag。

## Non-goals

- 不修 F2：callable 前已知拒绝被归入 unknown recovery。
- 不修 F3：MCP schema canonicalization 漏掉名为 `title` 的真实参数。
- 不修 F5：context 已淘汰结果与 durable request dedup 的联动。
- 不修 F6：纯文字请求被误标 explicit non-prose outcome。
- 不建立跨 MCP/SubAgent/sandbox 的通用进程管理框架。
- 不追踪主动 `setsid`/`setpgid` 逃离原 owned group 的任意后代；这不是 OS sandbox。
- 不实现 Windows Job Object/backend，不升级依赖，不改变公共 MCP/ToolResult/checkpoint/latch
  schema。
- 不调用真实 Provider、外部 MCP、网站、profile、credential、private runtime 或未跟踪
  `tui/`。
- 本轮不 commit、push、发布、部署或 promotion，除非用户另行要求。

## Expected files

- Production: `agent/mcp/bridge.py`
- Tests: `tests/mcp/test_session_behavior.py` 与
  `tests/fixtures/mcp/behavior_server.py`；仅在真实纵向缺口需要时最小补充
  `tests/mcp/test_session.py`、`tests/mcp/test_bridge.py` 或 `tests/mcp/test_tools.py`
- Documentation: 本计划；现有架构声明只有与本切片行为直接冲突时才最小更新。

扩大 production 文件范围前，Pi 必须报告具体依赖；不得顺手合并其他 findings。

## Verification

实施时按 U1→U4 逐个运行最小测试。全部实现后依次运行：

1. `.venv/bin/python -m pytest -q tests/mcp/test_session_behavior.py`
2. `.venv/bin/python -m pytest -q tests/mcp/test_session.py tests/mcp/test_bridge.py tests/mcp/test_tools.py tests/mcp/test_catalog.py`
3. `.venv/bin/python -m pytest -q tests/kernel/test_runtime_errors.py tests/kernel/test_runtime_recovery.py tests/kernel/test_effect_ordering.py`
4. `.venv/bin/python -m pytest -q tests/kernel/test_context_manager.py tests/kernel/test_context_budgeting.py tests/kernel/test_context_compaction_plan.py tests/kernel/test_runtime_compaction.py`
5. `.venv/bin/python -m pytest -q tests/architecture`
6. fresh Pi 只读审计实际 diff 与真实 child/group/latch oracle，并独立核验 005 batch facts
7. 仅在以上全部通过后运行一次最终门禁：
   - `git diff --check`
   - `.venv/bin/ruff check .`
   - `.venv/bin/python -m pytest -q -rx`

成功要求：同一真实反例先 RED 后 GREEN；所有 process 测试都有独立 watchdog/finally；
known result 只有 cleanup proof 成立才 clear，UNKNOWN 不因清理成功而 clear；所有命令完整
exit 0。离线本地 fixture 不冒充真实外部 MCP E3 或跨平台 qualification。

## Deferred findings ledger

- F2 / P1：`KernelToolRuntime.invoke` 的 callable 前拒绝会被 Runtime 误归 unknown。
- F3 / P1：MCP `_canonical_schema` 递归删除 `title`，会漏掉真实参数 drift。
- F5 / P2：被 context budget 淘汰的成功结果仍会被 durable inventory 拒绝重读。
- F6 / P1：纯文字任务可能被误写入 `explicit_non_prose_outcome=True`。

Oracle 提出的 `005-batch-feedback-atomicity` 已由 fresh Pi 与 Codex 使用完整 Runtime、实际
reducer 和 Provider-visible `ContextPack` 独立复现：上一 response 已进入 no-progress，
下一 response 的 batch 首个失败若换了稳定签名，会在其 result 后插入
`no_progress_replan_required` policy fact；同 batch 的后续 result 因而被拆成独立 group。
这是 005/Context grouping 的独立 P1 候选，不由 006 引入；不得把它混入本切片，下一轮需
重新审计并冻结独立合同。

## Implementation notes

- 2026-09-08 交付（Pi，仅 `agent/mcp/bridge.py` + 两个测试/fixture 文件）：
- RED：新增 `behavior_server.py::spawn_child_leader_exit` 模式（同组 benign child +
  facts/release 双握手）与 `test_leader_exit_child_survives_requires_group_cleanup_proof`；
  旧实现在 `tests/mcp/test_session_behavior.py:456` 处 RED——返回
  `process_exit_confirmed=True` 并 clear latch，而 owned group 中 benign child 仍存活。
- `_spawn` 在 `anyio.open_process` 前调用 `_require_group_lifecycle_primitives()`
  （缺 `os.killpg`/`SIGKILL` → pre-spawn `NOT_EXECUTED`，零副作用），成功后从受控
  handle 冻结正的 `owned_pgid`（start_new_session=True 下 PGID==leader PID）并随
  handle 一起返回，仅在 bridge 内部传递。
- `_shutdown_process(process, owned_pgid, timeout)` 显式接收 frozen PGID，返回值要求
  `leader_reaped and group_absent and transport_closed` 三事实同时成立；无论 leader
  是否已退出都对 frozen PGID probe（`_owned_group_absent`：仅 `killpg(pgid, 0)` 的
  `ProcessLookupError` 证明 absent，权限/未知 OSError 均不是 absent），组仍存在则
  SIGKILL frozen PGID，并在剩余 deadline 内反复确认消失后 `Process.aclose`。
- 单一整体 deadline：graceful wait 至多消费剩余预算一半；transport close 预留
  `_TRANSPORT_CLOSE_RESERVE_SECONDS`（0.5s，≤timeout/2）份额，保证 deadline 到期也
  不会跳过 close 造成 transport 泄漏。shielded 结构与既有 cancellation 语义不变。
- latch/`_finalize_outcome`/UNKNOWN 规则未改：cleanup 不可证明 → confirmed=False →
  已知 EXECUTED 重分类 UNKNOWN、latch 保持 ARMED；UNKNOWN 不因清理成功而 clear。
- 新增 U3/U4 测试：inherit-stdio 路径、killpg 权限故障注入（fail closed + ARMED）、
  transport close 故障替身（真实 benign group 被真实 SIGKILL/reap 清理）、缺 primitive
  零副作用拒绝（pidfile 缺席为铁证）。所有 child 均有 watchdog + finally 清理。
- Codex 独立复跑 5 个新增 lifecycle oracle：`5 passed`；完整 MCP focused suite：
  `57 passed`；Kernel/Context/Architecture protected gates：`205 passed`。每次真实进程测试后
  均检查无 `behavior_server.py`/`_child_sleeper` 残留。
- fresh Pi 以全新只读会话完成独立审计并给出 `PASS`：亲自复跑当前 GREEN 与从 HEAD
  提取的旧 cleanup RED，核对两个 cleanup 调用点共享 frozen PGID、权限/transport/
  cancellation/latch 方向均 fail closed，并独立运行 session behavior `13 passed`、其余
  MCP focused `37 passed`、005 runtime errors `36 passed`、changed-file Ruff 与 diff check。
- fresh Pi 记录三个非阻塞 P2 caveat：PGID 复用的理论竞态、既有双 shutdown 重试可能达到
  2× timeout、subreaper 场景下 orphan zombie 可能使 absence proof 保守失败；三者均不把
  False 提升为 True，本轮不扩展范围。
- 006 没有修改公共 MCP/ToolResult/checkpoint/latch schema、Runtime/Context owner 或
  F2/F3/F5/F6；未刷新 Graphify（未跟踪 `tui/` 的摄入范围无法安全确认）。
- 最终全量门禁通过：`git diff --check`、`.venv/bin/ruff check .` 均为 PASS，
  `.venv/bin/python -m pytest -q -rx` 为 `3238 passed, 3 skipped in 339.61s`；门禁后再次
  检查无 `behavior_server.py`/`_child_sleeper` 残留。本轮没有真实外部 MCP/Provider E3，
  也没有 commit/push。
