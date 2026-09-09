# Round 016：双管道 EOF 与前台进程存活解耦计划

状态：**verified-closed / 未 commit、未 push**

## Outcome

修复现有 `run_local_process()` 把 stdout/stderr 双 EOF 误当成 direct child 已退出的
生命周期缺口。合法前台进程即使主动关闭 fd 1/2，只要仍在已批准 wall deadline 内运行，
runner 就必须继续有界观察而不能经 `_reap()` 提前 SIGKILL；自然退出后保持原
`EXITED` 分类，超时后仍走既有 TERM→KILL→group liveness 证明。

同轮只关闭与“正常采集何时完成”直接耦合的两个异常出口：`select.select()` 或
`os.read()` 失败不得再伪装成正常 break/EOF 和空输出成功，而应治理已验证的原进程组，
关闭 streams、reap direct child，并通过既有 `ProcessCleanupError` 进入 unknown-outcome
recovery。

## Evidence and external grounding

本地源码事实：

1. 当前 drain 循环只以 `out_done and err_done` 为终止条件；
2. 双 EOF 后立即调用的 `_reap()` 会在 `proc.poll() is None` 时直接 `proc.kill()`；
3. 这条 direct-child kill 不经过 `terminate_group()`，因此 draft 可能呈现
   `SIGNALED/SIGKILL`，但 `term_sent=False`、`kill_sent=False`；
4. `select` 的 `OSError/ValueError` 当前直接 `break`，`read` 的 `OSError` 当前被改写为
   `b""`，两者都能把采集失败伪装为正常结果；
5. 已有测试覆盖 leader 先退出但 descendant 持 pipe 的反向边界，却没有覆盖两个 pipe
   先 EOF 而同一 direct child 继续工作的正向边界。

Primary sources：

- Python 将 `Popen.poll()` / `wait()` 定义为 child termination 观察，而
  `communicate()` 明确同时执行“读到 EOF”和“等待进程终止”：
  <https://docs.python.org/3/library/subprocess.html>；
- Linux pipe 合同只说明所有写端关闭后 read 返回 EOF，不说明特定进程已退出：
  <https://man7.org/linux/man-pages/man7/pipe.7.html>；
- OpenAI Codex 当前实现分别等待 `child.wait()` 与 stdout/stderr collector，并对
  collector drain 单独设界：
  <https://github.com/openai/codex/blob/main/codex-rs/core/src/exec.rs>；
- DeepSeek Harness 的 `ShellProcess.done` 与 `readOutput()` 分离，只借鉴职责分离，
  不引入其后台 job runtime：
  <https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/shell.md>。

Oracle Web fresh consultation：
`first-agent-r16-dual-pipe-eof-retry-20260908-2237-c91f`。已验证最高档
`Pro，第 5 项，共 5 项`、committed user turn、完整 answer capture、
`status=completed`，且该 session 的专属 Chrome PID 已退出、临时 Profile 已删除。
Oracle 结论为 `PROCEED / P1`：只做一个前台进程生命周期闭合切片，并把同一循环内
吞噬的 select/read 异常改为窄的 post-spawn failure；不新增第二套 runner、线程、async
或 outcome taxonomy。

## Frozen lifecycle contract

正常采集完成由三个独立事实共同决定：

```text
child_done := proc.poll() is not None
stdout_eof := stdout 的成功 read 返回 b""
stderr_eof := stderr 的成功 read 返回 b""

normal_collection_complete := child_done && stdout_eof && stderr_eof
```

状态组合：

| direct child | pipe 状态 | runner 行为 |
| --- | --- | --- |
| 存活 | 至少一个未 EOF | 继续 bounded select/read，遵守原 deadline |
| 存活 | 双 EOF | 正时长 bounded sleep 后重新 poll，不 kill、不早退、不重置 deadline |
| 已退出 | 至少一个未 EOF | 继续 bounded drain；descendant 持 pipe 时原 deadline 仍生效 |
| 已退出 | 双 EOF | 正常采集结束，进入既有 group liveness 确认/必要清理 |

`pipe EOF`、`direct child termination` 与 `process group gone` 三者互不替代。正常路径只有
确认 direct child 已退出后才能调用 `_reap()`；timeout 和 post-spawn failure 先复用
既有 group cleanup，再由 `finally` 保留 reap/stream-close 兜底。

## Acceptance contract

1. 旧实现上必须用真实 direct child 精确复现：同一 Python child 关闭 fd 1/2，短暂继续
   工作、写入测试自有 marker，再自然退出 0/7；旧实现应提前 SIGKILL 且 marker 缺失。
2. Green 后上述场景必须等待 child 自然完成，marker 精确存在，outcome 为 `EXITED`、
   exit code 为 0/7，且 `term_sent=False`、`kill_sent=False`。
3. 双 EOF 后持续运行仍受原 wall deadline 约束；覆盖接受 TERM 与忽略 TERM 后 KILL，
   不得因 watch 为空而早退、忙等或重新计算整段 deadline。
4. watch 为空且 child 存活时，只允许按当前阶段的有效剩余预算做正时长等待：timeout 前
   取 `deadline - now`，timeout 后取 `hard_drain_deadline - now`；只在 remaining > 0 时
   `time.sleep(min(_SELECT_SLICE, remaining))`，再回到同一循环。不得对负值 sleep，也不得
   `max(0, ...)` 后零延时自旋或重置 deadline。
5. 有 pipe 时 select timeout 同样统一为 `min(_SELECT_SLICE, effective_remaining)`；同步
   group cleanup 返回后重新读取 monotonic time，再选择 timeout 后的 hard-drain 预算，
   不复用 cleanup 前的 `now`。
6. `select.select()` 实际传播的 `OSError/ValueError` 与任一 stream 的 `os.read()`
   `OSError` 不得转成 normal completion、EOF、truncation、timeout 或 `SPAWN_FAILED`。
7. 采集失败必须以 `raise ProcessCleanupError(...) from original_error` 保留原 cause；
   对仍活的已验证原 PGID 复用既有
   `process_group.terminate_group()`，已确认 group gone 时跳过；清理成功后仍抛既有
   `ProcessCleanupError`。若 cleanup 自身也抛 `ProcessCleanupError`，最终异常的
   `__cause__` 仍必须是原始 select/read 异常，cleanup error 只能作为被保留的 context，
   不能覆盖根因；清理无法确认仍保持 fail closed。
8. 异常路径必须关闭 stdout/stderr 并 reap direct child，不得只 kill leader；不得增加
   errno 重试框架、EAGAIN/EINTR 策略或第二套 cleanup budget。
9. 保留 leader 先退出但 descendant 持 pipe、fast-exit ESRCH、PGID EPERM、TERM→KILL、
   post-KILL unconfirmable 等既有 group tests；双 EOF 不能用作 group cleanup 证明。
10. 输出 cap、combined cap、projection、invalid UTF-8、captured-buffer bytes/digest 与
    truncation facts 的现有语义不变；采集异常不得铸造正常空 digest/result draft。
11. `run_local_process` 的 process tool、sandbox executor 等真实消费者继续只消费同一
    runner；approval、fingerprint、lease、checkpoint、receipt 与 recovery schema 不变。
12. 本轮只要求本地真实 child 与既有 Runtime fixtures；不隐含真实 provider、真实外部
    网络、用户私有数据或交付晋级授权。

## Product contract

- 普通用户可以关闭日志输出后继续生成文件或完成收尾，不必通过持续打印来“保活”。
- 同一条获批命令仅改变 stdout/stderr 重定向方式，不应从自然完成变成提前 SIGKILL。
- 修复提升的是已批准前台命令的可预测性与结果可信度，不新增权限、后台执行或重放。
- 采集器失效时不返回看似成功的空输出；Runtime 继续按既有 unknown-outcome recovery
  让用户处理，不自动重复可能已有部分副作用的 intent。

## Non-goals

- 不新增或替换 `AgentRuntime.run_turn`、model/tool loop、第二套 process runner、线程、
  async、PTY、daemon、job handle、pidfd 或平台事件后端。
- 不改变 `agent/process/group.py` 的公开接口、TERM/KILL 算法或既有资源预算。
- 不改变 Tool API、`ProcessExecutionDraftV1`、receipt/checkpoint schema、outcome taxonomy、
  approval/fingerprint/lease 或自动重放规则。
- 不改变 output cap、captured-buffer digest/bytes、projection、truncation facts 或 hard-drain
  保证；这些残余问题另轮处理。
- 不解决同步 `terminate_group()` grace 期间不 drain 的背压问题，不扩大 descendant 终止
  保证，也不重构整个 runner。
- 不修改 sandbox、PATH、git metadata、symlink 或环境策略；不触碰 root untracked
  `tui/`、secret/credential/private/runtime 数据；不 commit、push、tag 或修改 remote。

## Smallest expected change set

Production：

- `agent/process/runner.py`

Tests：

- `tests/process/test_runner.py`
- `tests/process/test_runner_group_cleanup.py`
- 仅在证明既有 recovery consumer 必需时修改最邻近 integration test。

Evidence/status：

- 本计划；
- `docs/architecture/CURRENT_CAPABILITY_STATUS.md`（只在 Green + independent audit 后记录）。

若必须修改上述以外的 product code，停止并重新审查 scope。

## Sequential TDD and proof

1. Red A：真实 direct child 双 EOF 后延迟写 marker 并自然退出 0/7；旧实现只因提前 kill
   失败。
2. Red B：双 EOF 后持续运行的原 deadline/TERM/KILL 约束；旧实现因早退或 flags 错误
   失败。
3. Red C：先用 patched select/read 形成双 EOF，再由受控 clock 的 sleep 推进时间，证明
   空 watch 正时长等待、有限 poll、deadline 不重置；不得让真实 select 在冻结 clock 下
   阻塞测试。
4. Red D：select OSError/ValueError、stdout/stderr read OSError 及部分读取后失败不得返回
   正常 draft；采集失败仍治理原 group。
5. Green：只在现有 runner 内分离 child termination 与两个 EOF；空 watch 使用现有
   `_SELECT_SLICE` 和剩余 wall budget；新增一个窄的采集失败 cleanup/raise helper 仅在
   能减少重复且不形成第二套流程时使用。
6. Focused：`tests/process/test_runner.py`、`test_runner_group_cleanup.py`、
   `test_runner_taxonomy.py`、`test_process_cleanup_recovery.py` 及 sandbox executor 邻接测试。
7. Fresh Pi plan/diff review 使用 `cc-switch-zhipu-glm` / `glm-5.3` /
   `thinking=max`、无 session/tools/skills；P0–P2 必须为零。
8. 最后只运行一次 full gate：`git diff --check`、`.venv/bin/ruff check .`、
   `.venv/bin/python -m pytest -q -rx`。超时、截断或无 exit code 不算 PASS。

## Promotion boundary

本轮 PASS 只关闭前台 runner 的 dual-pipe EOF / direct-child liveness 混淆以及同循环采集
异常伪成功。不重铸 017/018/019 delivery identity，不晋级跨平台或 production-ready
声明，也不关闭 multi-hop symlink、truncation facts 等后续轮次。

## Independent plan review record

- Fresh Pi 使用 `cc-switch-zhipu-glm` / `glm-5.3` / `thinking=max`，以无 session、
  无 tools、无 skills/extensions 的只读方式审查 frozen spec 与现有 runner/group/tests，
  结论 `VERDICT: PASS`，无 P0。
- 其 P1/P2 已在实施前写回验收合同：pre/post-timeout 有效预算分离、select/sleep 统一受
  remaining cap、cleanup 后刷新 monotonic、采集异常 cause 链，以及 fake-clock Red 的
  非阻塞构造。P3 的 post-timeout tail、dead branch 与 fixture 注意事项未扩大本轮 scope。

## Implementation and independent diff review record

- TDD Red 在旧实现上得到 `9 failed`：自然 exit 0/7 均被提前报为 `SIGNALED`，接受/忽略
  TERM 的两个 deadline 场景均提前退出，empty-watch 没有 sleep，四种 select/read 故障
  都返回正常 draft；失败均命中目标行为，不是 fixture/import 错误。
- Green 只修改 `agent/process/runner.py`：正常采集要求 child termination + 双 EOF；
  empty-watch 与 select 共用当前阶段 remaining cap；timeout cleanup 后刷新 monotonic 并
  立即重查完成；select/read 异常只经一个窄 helper 复用原 group cleanup 并从原错误抛出
  既有 `ProcessCleanupError`。首次 Green 为 `8 passed, 1 failed`，唯一失败暴露 cleanup 后
  多等待一个 slice；补上立即重查后为 `9 passed`。
- Focused evidence：完整 `tests/process` 加 sandbox executor/structured executor 邻接集
  `136 passed`；touched Ruff 与 scoped `git diff --check` 均通过。
- Fresh Pi diff audit 使用 `cc-switch-zhipu-glm` / `glm-5.3` / `thinking=max`、无 session、
  无 tools/skills/extensions，结论 `VERDICT: PASS`，P0/P1/P2 均为 none。P3 仅记录不可达
  remaining guard、`NoReturn` 注解、测试 helper 去重与既有 truncation 语义，不扩大本轮。
- 实施前另一次 Pi Red-patch 生成调用在约十分钟后表现为 CLI/连接层无进程但会话不返回，
  被有界终止（exit 130）；它未获得写工具、未修改文件。Codex 按既定 fallback 完成 Red/Green。
- 本轮 final full gate 只运行一次：`git diff --check` PASS、全仓 Ruff PASS、pytest
  `3323 passed, 3 skipped in 362.83s (0:06:02)`，完整 exit 0。其后仅回填本计划文字；
  product code、tests 与 capability status 未再改变。本轮未 commit、未 push，也未重铸
  017/018/019 delivery identity。
