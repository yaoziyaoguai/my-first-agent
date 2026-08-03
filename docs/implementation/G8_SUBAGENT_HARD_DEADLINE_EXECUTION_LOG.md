# G8 SubAgent Hard-Deadline Execution Log

本日志由 General Agent Completion executor（Claude Code session）在独立 reviewer 输出
`GENERAL_AGENT_REVIEW_PASSED`（六项 capability 晋级 `locally-verified`，SubAgent 仍
`implemented-candidate + safe-unavailable + E3-blocked`）之后，于同一隔离后继副本中执行 G8 后写入。
供下一次独立 promotion review 核对；它不是 E3 acceptance，也不替代独立 review receipt。

## 目标

在不创建第二套 Agent/model/tool loop 的前提下，为 SubAgent 提供真实、可证明的 hard-deadline
provider 路径，使 production HTTP provider 经 honest 边界满足 hard-deadline 合同；并收紧独立
reviewer 的 O1（确定性证明 UNCONFIRMED 覆盖 child normalization → parent recovery）。

## 审计结论

- `anthropic_http` / `openai_http` 用 `httpx` socket timeout → `ProviderTimeoutError`：socket/read
  timeout 只能放弃在途请求，**不能证明 provider 已终止**。给 urllib/http adapter 挂 `deadline_contract`
  属性是假保证，按设计禁止。
- `AgentRuntime.run_turn` 捕获所有 provider 异常并分类为终态（`FAILED_RETRYABLE` / `FAILED_FATAL`），
  故 provider 层的 deadline-kill 会被 run_turn 吞成已知终态，无法产生 `UNCONFIRMED`——排除
  “per-call process-bounded provider adapter” 设计。
- `SUBAGENT_DESIGN.md` 原把 “hard wall-clock preemption 和独立 child process termination” 列为
  Deferred（“真正的 hard deadline/preemption 需要后续进程隔离合同”）。G8 即实现该合同。

## 设计：进程隔离 hard-deadline runner

`agent.subagent/process_runner.py::ChildProcessRunner`：

- child 在独立 OS 进程内运行**同一个** `AgentRuntime.run_turn`（经 `runner.build_child_runtime`，
  subagent 包内唯一导入 `agent.runtime.loop` 的位置——由架构 cutover 测试 exempt）。
- parent 拥有该进程的 process group（`start_new_session=True`），在 `hard_deadline_seconds` 后
  `killpg` + `wait` 确认退出。唯一诚实的 hard deadline：进程所有权保证 child 本地终止。
- runner 自身声明 `ProviderDeadlineCapability(receipt_type="process_terminated")`——capability
  来自进程边界，不来自 HTTP adapter。

receipt 语义（确定性，无 race）：

- `TERMINATED`：child exit 0 + stdout 合法结果 JSON（child 已 terminally 报告 `RunStatus`）。
- `UNCONFIRMED`：parent 在 deadline 前 child 未自行退出（被 kill）或非 0 退出/未写合法结果 →
  provider call 可能已发生 → parent unknown-outcome recovery。

credential：`ChildProviderSpec` 只带 `credential_env_name`，credential 值**永不**跨进程序列化；
child 从自身 env 读取。config 是 bounded、owner-only、no-follow 临时文件，用后删除。

## 各单元闭合记录

| 单元 | 闭合内容 | 关键 oracle |
|---|---|---|
| G8 路径 | `ChildProcessRunner` + `child.py` entrypoint + `runtime_factory.py` 共享 helper；composition 按 `deadline_contract.receipt_type` 路由（HTTP→process，synchronous→in-process） | `test_process_runner_*`：TERMINATED+COMPLETED、deadline-kill→UNCONFIRMED、nonterminal→TERMINATED known error、`process_terminated` capability、UNCONFIRMED→`SubAgentUnknownOutcomeError` |
| G8 O1 收紧 | `test_unconfirmed_receipt_overrides_child_normalization` 改为确定性故障注入（child generate 阻塞 5s >> deadline 0.5s），严格断言 `receipt_state=="unconfirmed"`（不再接受 terminated\|unconfirmed 二选一） | UNCONFIRMED 覆盖 would-be child_nonterminal |
| G8 composition | `main.py`：HTTP+`--subagent` 经 `ChildProcessRunner` 组合（不再 reject）；synchronous provider 仍走 `ChildAgentRunner` | `test_http_provider_subagent_composes_process_runner`（exit 0）、`test_subagent_http_without_model_or_base_url_fails_closed` |
| G8 架构 | 新文件登记进 product-tree allowlist；subagent 包内仅 `runner.py` 导入 loop/provider（cutover 不变量保持） | `test_cutover_absence.py` 全绿 |

## 边界遵守

- 不创建第二套 model/tool loop：child 复用 `agent.runtime.loop.AgentRuntime.run_turn`；无 service
  locator、无动态 plugin、无 compatibility fallback。
- 不给 HTTP adapter 挂 `deadline_contract`；hard deadline 仅由进程边界提供。
- 未读取 secret/private/runtime；credential 仅按 env name 在子进程内读取。未 commit/push/tag/remote。
- SubAgent 仍 `implemented-candidate`：G8 合同需独立复审；E3（真实 HTTP provider in child）待 provider
  config。本日志不把 SubAgent 标 `locally-verified`/`accepted`。

## 验证（focused + materialized）

focused（`tests/subagent/` + `tests/architecture/test_cutover_absence.py`）：27 passed。
全量：`ruff check .` 全绿；`pytest -q` → 353 passed（未截断）。
materialized `--content` gate 的结果见 `CURRENT_CAPABILITY_STATUS.md`（本 executor 在写 control 前
重跑，deny-network 边界内）。

## 独立 review findings 修复（G8.1）

独立 reviewer 对 G8 返回 `GENERAL_AGENT_REVIEW_FINDINGS`，本 executor 只修可执行 finding 及其直接
truth/evidence fallout，不扩范围：

- **F-G8-1（stderr deadlock → 假 UNCONFIRMED）**：`_run_child` 原 `stderr=PIPE` 不 drain，child 突发
  >pipe-buffer stderr 会阻塞自身、被 deadline-kill 成假 UNCONFIRMED。改为 `stderr=DEVNULL`：OS 级
  丢弃，deadlock-safe、不缓冲、不进 result（不弱化 hard deadline）。确定性 oracle：child 在返回前
  突发 128KB stderr（>64KB pipe buffer），parent 仍返回 TERMINATED 且结果不含 stderr 内容。
- **F-G8-2（per-run temp dir 泄漏）**：`run` 的 `finally` 原只 `unlink(config.json)`，`mkdtemp` 创建的
  目录泄漏。改为先 `unlink(config.json)` 再 `rmdir(dir)`（空目录），不跟随 symlink、不删除宽泛/未解析
  路径。oracle：成功路径与 deadline/crash cleanup 后 per-run 目录均消失。
- **stdout 有界（reviewer informationally noted）**：parent 原 `proc.stdout.read()` 无界。改为
  `_read_bounded(stdout, _MAX_RESULT_BYTES=8192)`（与 child `_RESULT_LIMIT_CHARS` 一致的 defense-in-depth
  上限）；oversized/malformed → None → UNCONFIRMED。oracle：monkeypatch 上界到极小→正常输出被判
  oversized UNCONFIRMED；`_parse_result` 对 malformed/非 dict/缺 status 返回 None。

不变量保持：唯一 `AgentRuntime.run_turn` loop；process group kill/wait 语义不变；credential 值永不
序列化/日志；架构测试除必要的显式文件登记外未改；SubAgent 仍 `implemented-candidate`（不晋级、不
伪造 review receipt）。

修复后验证：focused（subagent + cutover）31 passed；全量 `ruff clean` + `pytest -q` → 357 passed
（未截断）；`git diff --check` clean；materialized `--content` gate 见 status doc。control seal
仍 `None`（待独立复审重封）。

