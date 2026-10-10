# Round 014：Prepared PATH 批准—执行一致性计划

状态：**verified-closed / 未 commit、未 push**

## Outcome

普通 `sandbox_exec` / `shell_exec` 的 child `PATH` 必须与
`prepare_process()` 已清洗、已写入 `EnvironmentProfileV1`、并参与
`command_fingerprint` 的 `PreparedProcessV1.child_path` 完全相同。
执行器不得再持有第二份 raw PATH authority。

当 prepared PATH、`search_paths` 与 environment policy 自相矛盾时，必须在创建
临时目录、调用 confiner 或 runner 之前返回
`KnownNotExecuted(code="environment_policy_changed")`。该拒绝仍由既有
`ToolRuntime` / `AgentRuntime` 路径落为 durable `executed=False` result；不增加新的
state、checkpoint 或 receipt 类型。

## Evidence and external grounding

本地动态 control（只用临时目录）已证明当前断点：

```text
captured_path=relative:/usr/bin:/bin:/usr/bin
approved_child_path=/usr/bin:/bin
actual_executor_path_today=relative:/usr/bin:/bin:/usr/bin
mismatch=true
```

成功 Oracle Web consultation：
`first-agent-r14-path-binding-20260908-c4f2`，最高档位置 5/5，committed user
turn、完整 answer capture 与精确 Chrome/Profile cleanup 均已验证。其结论为
`PROCEED` / P1：这是 exact-approval correctness defect，但当前证据不表示 Seatbelt
escape、privilege escalation 或 P0 compromise。

Primary sources：

- OpenAI Codex 的 spawn request 携带显式 env map，spawn 边界以 `env_clear()` 后
  `envs(env)` 注入同一 map：
  <https://github.com/openai/codex/blob/main/codex-rs/core/src/spawn.rs>
- Codex 的 environment policy 先构造 env，再交给 spawn；这是“先决定、后消费”
  的 ownership 形状，不证明 Codex 使用本项目的 fingerprint 合同：
  <https://github.com/openai/codex/blob/main/codex-rs/protocol/src/shell_environment.rs>
- DeepSeek Harness 把 launch environment 表达为 immutable snapshot，并明确扁平
  `process.env` 不是 authority：
  <https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/util/launch-environment/README.md>
- Python 文档确认 child env 与 PATH 会影响后续 bare-name executable lookup：
  <https://docs.python.org/3/library/subprocess.html>、
  <https://docs.python.org/3/library/os.html#os.execvpe>。

以上 source facts 支持本项目的推论：已经写入批准 identity 的 prepared PATH 必须沿
同一调用链到达 spawn；不能由 executor 的另一份 raw 配置替换。

## Current failure

`prepare_process()` 已完成正确的一半：

1. `sanitize_captured_path()` 丢弃空项、相对项、缺失/非目录项，canonicalize 并按序
   去重；
2. 产出 `PreparedProcessV1.child_path`；
3. 用该值构造 `EnvironmentProfileV1`；
4. environment policy digest 进入 `ProcessCommandV1.command_fingerprint`。

但普通 `NativeSandboxExecutor.execute()` 又调用：

```python
closed_process_environment(temp_root, self._captured_path)
```

`_verified_invocation()` 随后只证明 confiner 返回了 executor 刚提供的 raw env，无法
证明该 env 就是批准所绑定的 prepared env。`shell_exec` 中固定的 `/bin/sh -c` 可因此
用被 sanitizer 排除的相对 PATH component 解析 workspace helper；`sandbox_exec` 中
已批准的外层程序也可能用该 PATH 查找子程序。实际 helper 仍受所选 sandbox policy
约束，因此不把本缺陷描述为 sandbox escape。

`local_process` 已在 registration construction 时只把 sanitized path 交给 executor
closure，不存在同一个 raw reinsertion 反例；本轮只把它作为 positive control。

## Frozen ownership and data flow

```text
captured startup PATH
  → prepare_process (sanitize once)
  → PreparedProcessV1.child_path + EnvironmentProfileV1
  → ProcessCommandV1.command_fingerprint
  → ToolRuntime exact approval
  → AgentRuntime EXECUTING checkpoint
  → registration fresh prepare / binding compare
  → revalidate_process validates prepared PATH plan
  → ordinary executor builds env from that same prepared.child_path
  → confiner → independent expected-env verification → runner
  → existing draft / receipt / result checkpoint
```

Ownership：

- `agent.process.preparation` 独占 PATH normalization 与 prepared-plan consistency；
- registration 继续独占“fresh prepare 是否等于 approved binding”的比较；
- `NativeSandboxExecutor` 只消费 successful revalidation 后的 prepared 值；
- confiner 只包装 command/policy/env，不能修改预期 env；
- Runtime/ToolRuntime ownership 不变。

## Acceptance contract

1. `revalidate_process(prepared)` 在保留既有 executable/cwd 校验顺序后、返回成功前必须验证：
   `prepared.child_path == os.pathsep.join(prepared.search_paths)`，且
   `prepared.command.environment_policy ==
   admission.build_environment_plan(captured_path=prepared.child_path)`。
   缺失或任一字段不一致统一返回
   `KnownNotExecuted(code="environment_policy_changed")`。
2. 上述检查只验证 frozen prepared bytes；不得重新读取 `os.environ`、重新清洗后静默
   替换、使用 caller 提供的 digest、或把不一致值修正后继续。
3. environment mismatch 必须发生在任何临时目录/session 创建、confiner 调用或
   runner 调用之前；若同一 prepared 值同时存在 executable/cwd 漂移，仍由既有校验顺序
   返回原来的具体 failure code。
4. `NativeSandboxExecutor.__init__` 删除 `captured_path`；不得保留 optional 参数、
   compatibility alias、fallback 或执行时 host lookup。
5. 普通 `io_plan is None` 路径在 revalidation 成功后，只允许从同一个
   `prepared.child_path` 读取并调用：
   `closed_process_environment(temp_root, prepared.child_path)`。runner 最终收到的
   `PATH` digest 必须等于 approved command 的 environment policy `path_digest`。
6. expected env 与交给 confiner 的 dict 必须是独立对象。confiner 返回不同 PATH、
   添加 key，或原地修改输入 dict，都在 runner 前返回既有
   `enforcement_facts_mismatch`。
7. structured I/O 继续显式使用 `PATH=""`，`HOME/TMPDIR=session.root`；不能套用普通
   PATH equality，也不声称空 PATH 能阻止显式绝对路径子进程。
8. `sandbox_exec` 与 `shell_exec` 必须从公开 registration 的 `prepare_binding` 经过
   callable 到 runner 都满足 sanitized PATH；dirty raw spellings 若归一为相同值，
   不应凭空制造新的 environment identity。
9. `local_process` 保持 same-UID disclosure、closed env 与已有批准语义，并以 dirty
   captured PATH 的 positive control 证明 runner 收到 sanitized PATH。
10. macOS 真实 smoke test 使用临时 fake helper：excluded relative directory 与
    approved absolute directory 输出不同 marker；真实 `shell_exec` 必须选择 approved
    helper。不得读取真实 home、凭据或依赖 stdout 作为批准 authority。
11. approval、lease、policy digest、mode/network、exact timeout、wrapped argv、
    process-group/output bounds、cleanup、unknown-outcome 与 checkpoint 顺序不变。
12. 普通路径成功 draft 的 `original_command_fingerprint` 必须对应实际 delivered env；
    structured 路径继续由既有 structured invocation digest 与显式 `PATH=""` 合同绑定。
    pre-spawn mismatch 不 mint successful receipt，也不自动换工具、重试或请求更高权限。

## Product contract

- 不增加一次 approval，也不向 preview/receipt 暴露 raw host PATH。
- 对用户的可理解保证是：“命令以它批准 identity 所绑定的 prepared startup
  environment 启动。”这不表示批准脚本不能自行改 PATH。
- 被过滤相对 PATH 才能找到的 helper 以后会正常报 not found；正确修复方式是明确
  选择可批准的 executable/合法绝对 toolchain directory，不恢复 raw PATH。
- 若检测到 prepared-plan mismatch，既有 `KnownNotExecuted` message 应明确提示重新
  prepare/review；不得引导扩大 filesystem/network 权限。

## Non-goals

- 不合并、删除或新增 `local_process` / `sandbox_exec` / `shell_exec`。
- 不新增 Runtime、runner、backend、daemon、environment registry、UI 设置、模型可控
  `env` 参数或权限层。
- 不修改 environment digest 算法、serialized checkpoint/receipt schema 或历史证据。
- 不 pin 所有传递依赖/子进程，不承诺消除 kernel TOCTOU。
- 不修 Round 013 Oracle 发现的 `.git` pointer、双 pipe EOF、多跳 symlink、
  truncation facts（F3–F6）。
- 不借本轮重构 `local_process`，不按文件大小拆分模块。

## Smallest expected change set

Core production：

- `agent/process/preparation.py`
- `agent/sandbox/executor.py`

Mechanical constructor updates only：

- `agent/sandbox/tools.py`
- `agent/sandbox/shell.py`
- `agent/composition.py`
- 所有测试中的 `NativeSandboxExecutor(...)` call sites

Focused tests：

- `tests/process/test_preparation.py`
- `tests/process/test_tools.py`（positive control，若现有断言不足）
- `tests/sandbox/test_executor.py`
- `tests/sandbox/test_tools.py`
- `tests/sandbox/test_shell.py`
- `tests/sandbox/test_structured_executor.py`（优先复用既有 `PATH=""` positive test）
- `tests/sandbox/test_network_only_macos.py`
- 既有 generic KnownNotExecuted Runtime test；只有无法覆盖 durable route 时才增加
  Runtime-specific fixture。

若需要修改 Runtime state/action/checkpoint、`ProcessCommandV1` serialized identity、
runner、confiner contract 或 tool schema，停止并重新审查范围。

## Sequential TDD and proof

1. Red A：dirty raw PATH 经真实 preparation + ordinary executor，断言 runner PATH 等于
   `prepared.child_path` 且 digest 与 approved environment policy 一致；当前必须失败。
2. Red B：仅替换 `child_path`、`search_paths`、缺失/改变 environment policy，逐一证明
   current revalidation 未 fail closed；`search_paths` 的 tamper 值必须仍解析到同一个
   executable identity，避免先触发既有 executable drift；再以最小 consistency check Green。
3. Red C：confiner 原地修改传入 env；当前 reference 被一同修改而放行。Green：expected
   env 与 confiner input 分离。
4. 删除 executor PATH constructor authority，更新所有 call sites；不加兼容层。
5. Focused regressions：两公开 registration、structured empty PATH、local_process positive
   control、executable/cwd drift、mode/network/timeout/enforcement/cleanup。
6. Real macOS smoke：两个不同 marker 的 helper selection，control 证明两个 fixture 均可
   运行/读取，产品路径只选择 approved absolute helper。
7. Pi 独立 diff audit 无 P0–P2 后，运行 touched-area gates。
8. 最后只运行一次：`git diff --check`、`.venv/bin/ruff check .`、
   `.venv/bin/python -m pytest -q -rx`。超时、截断或缺 exit code 均不算通过。

## Promotion boundary

本轮 PASS 只关闭普通 native sandbox PATH approval/execution mismatch。它不重新铸造
017 detached delivery identity，不晋级跨平台声明，也不关闭 F3–F6 或 Skill
entrypoint 的独立 private-root 审计项。

## Independent plan review record

- Pi 使用 `cc-switch-zhipu-glm` / `glm-5.3` / `thinking=max`，以无 session、无 tools、
  无 skills 的只读方式审查本计划和相关实现/测试，结论为 `VERDICT: PASS`，无
  P0/P1/P2。
- 实施前只读核对确认 `build_skill_execution_config()` 构造的 executor 只由
  `execute_skill_entrypoint()` 以非空 `io_plan` 调用，因此删除其空 `captured_path`
  constructor 参数是机械变化，structured `PATH=""` 行为不变。

## Implementation record

- Red A：dirty raw PATH 的 ordinary executor 测试按预期失败，runner 实收
  `relative:/usr/bin:/bin:/usr/bin`，而 approved `prepared.child_path` 为
  `/usr/bin:/bin`；最小 Green 后使用后者并校验实际 PATH digest。
- Red B：分别证明 `child_path` 与 `search_paths` 不一致、缺失或改变
  `environment_policy` 不能再穿过 revalidation；失败统一为
  `environment_policy_changed`，且 executable/cwd 的既有优先级不变。
- Red C：ordinary 与 structured confiner 原地修改 env 的反例都曾错误到达 runner；
  修复后 expected env 与 confiner input 使用独立 dict，两个路径均在 runner 前拒绝。
- `NativeSandboxExecutor` 已删除 `captured_path` constructor authority；公开 registration、
  Skill composition、017 E3 runner 与测试调用点只做机械更新。registration 自己的
  `captured_path` 仍用于 prepare/binding，没有删除。
- 真实 Darwin smoke 的相对目录 helper 与 approved 绝对目录 helper 都可直接执行；
  `shell_exec` 只选择 approved helper。local_process 的既有相对解释器劫持正对照继续通过。
- 当前 focused 证据：preparation/executor/structured/真实 helper 选择 `41 passed`；
  两公开 registration、composition、Skill structured 与 packaged policy `106 passed`；
  完整 macOS sandbox/reference runner 邻接集 `47 passed`。touched-file Ruff 与
  scoped `git diff --check` 均通过。
- fresh Pi 独立 diff audit 使用 `cc-switch-zhipu-glm` / `glm-5.3` /
  `thinking=max`、无 session/tools/skills，结论 `VERDICT: PASS`，无 P0/P1/P2。
- 本轮最终门禁只运行一次：`git diff --check` PASS、全仓 Ruff PASS、pytest
  `3311 passed, 3 skipped in 374.08s (0:06:14)`，完整 exit 0。本轮未 commit、
  未 push，也未重新 seal 017 delivery identity。
