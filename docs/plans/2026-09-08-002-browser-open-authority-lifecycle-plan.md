# Browser Open 精确授权消费与会话租期计划

- Date: 2026-09-08
- Status: superseded-by-2026-09-08-003-profile-writer-lifecycle
- Source: Oracle Web product/architecture audit r4（最高档）+ Codex 本地调用链复核

> 2026-09-08 后续 Oracle r5 与 Codex 复核证明：本计划闭合了两个前置
> TOCTOU 窗口和 session deadline 起点，但 `acquire_writer` 成功后普通 profile
> mutation 仍可在 adapter open 前改变 revision；active `clear` 还会删除锁并误报
> `CLEANED`。因此本计划的实现保留为 003 的前置改动，不能单独作为最终 PASS。

## Outcome

每次获批的 `site_bound_interactive` open 只能消费审批时绑定的 exact profile
revision、browser identity、site policy 与 active 状态；任一字段在最后重验后再次漂移，
都必须在 `BrowserEnvironment.open` 前返回 `KnownNotExecuted`。交互会话的 30 分钟租期
从这次获批 open 真正开始执行时计算，不从 CLI/composition 注册工具时计算。

## Non-goals

- 不改变 `AgentRuntime.run_turn`、`KernelToolRuntime` 或 approval/checkpoint 流程。
- 不改变 public-read 的无 profile 合同，也不把它静默升级为 interactive。
- 不改变 `browser_act` 的 5 分钟 exact-action approval、action budget 或 expiry 判定。
- 不加入自动续租、滑动 deadline、通用 timeout framework、profile selector 或第二套 loop。
- 本切片不处理 scheduler、custom state-root、profile CLI 展示与长任务进度反馈。

## Protected boundaries

- `AgentRuntime.run_turn` 仍是唯一 production model/tool loop 与 state mutation owner。
- `KernelToolRuntime` 仍独占 admission、approval、`EXECUTING` checkpoint 与 invoke。
- `BrowserEnvironment` 只接收已治理的 immutable `BrowserSessionSpecV1`，不读取 approval。
- profile 状态不是 authority；只有本次 intent 的 frozen safety binding 可授权 open。

## Acceptance contract

1. 构造 registrations、首次 prepare、等待审批与带 approval 的 re-prepare 都不读取
   monotonic clock；它们绑定固定 `session_duration_seconds=1800`，不绑定绝对 deadline。
2. `site_bound_interactive` callable 在 exact profile 最终校验和 writer acquisition 后只读取
   一次 monotonic clock，生成 `expiry_monotonic = execution_now + 1800`。
3. 两次顺序 open 各自获得独立 deadline；第二次 open 不续期或改写第一次的 immutable spec。
4. final Runtime binding revalidation 与 callable 之间若 profile revision/status/site policy/
   browser identity 漂移，结果为 `KnownNotExecuted`、`executed=False`，且
   `BrowserEnvironment.open` 调用次数为零。
5. drift/unavailable 在 effect 前失败时不泄漏 writer；adapter 一旦收到 open request 后的
   unknown-outcome 与 quarantine 语义保持不变。
6. legacy absolute-expiry binding 不自动转换：它与新 binding digest 不同，必须重新审批。
7. 既有 adapter expiry 测试继续证明过期 action 为零 effect；public-read 行为保持不变。

## Minimal implementation

- `agent/browser/tools.py`
  - 保存 injected `monotonic_clock` callable，而不是在 `__init__` 计算 deadline。
  - interactive `prepare_open` 绑定 fixed duration，并要求 profile 仍为 active。
  - interactive `open` 对 frozen binding 做最后一次 exact profile 校验；漂移在 effect 前
    返回 closed `KnownNotExecuted`。
  - writer 成功获取后、adapter 调用前生成本次 immutable absolute deadline；构造失败时释放
    writer。
- `tests/browser/test_tools.py`
  - 通过 public `KernelToolRuntime.prepare/invoke` 写一个行为测试后做最小实现，再逐项补齐
    deadline 独立性与 final drift 零 effect。
- `tests/browser/test_interactive_actions.py`
  - 不预设修改；仅运行既有 expiry zero-effect 测试作为回归证据。

## Verification strategy

1. 每个行为按一个 Red → 最小 Green 的 vertical slice 完成。
2. focused：`tests/browser/test_tools.py` 与既有 expired-session adapter case。
3. fresh Pi 只读独立审计，修完 P0/P1/P2 后再跑一次 focused gates。
4. 稳定后只跑一次 final `git diff --check`、Ruff 与 full pytest；中间不反复全量测试。
5. 不访问真实 profile、credential 或第三方网站；本切片的 effect oracle 是 injected
   environment 的零调用/typed spec 记录。

## Review decision

Codex 已复核 `KernelToolRuntime.invoke` 的 re-prepare、`BrowserProfileStore.open/
acquire_writer`、production composition 与 Playwright expiry gate。修复可以完全留在既有
browser governed-tool seam；无需扩张架构或新增能力面，批准进入实现。

## Implementation Notes（2026-09-08，executor）

实现完成、待 Codex 独立审计与一次性 full suite。只改动
`agent/browser/tools.py` 与 `tests/browser/test_tools.py`；
`tests/browser/test_interactive_actions.py` 未修改，只运行既有 expiry case。
所有行为测试均走 public `KernelToolRuntime.prepare/invoke`。

### 实现（agent/browser/tools.py）

- `__init__` 只保存 injected `monotonic_clock` callable，不再在构造阶段固化
  绝对 deadline。
- `prepare_open` interactive 分支要求 profile `ACTIVE`，binding 改携固定
  `session_duration_seconds=1800`（不再含 `session_expiry_monotonic`）。
- `open` interactive 分支在 `acquire_writer` 前对 frozen binding 做最后一次
  exact 校验（revision / status / site policy digest / browser identity），
  任一漂移在 writer 与 effect 前返回 closed
  `KnownNotExecuted(code="browser_open_binding_changed")`；writer 获取成功后、
  adapter 调用前读一次 monotonic clock，生成
  `expiry_monotonic = execution_now + session_duration_seconds`；immutable spec
  构造失败时释放 writer 并返回 closed `KnownNotExecuted`。
- Acceptance 6（legacy absolute-expiry binding 不自动转换）由既有 digest 机制
  结构性保证：binding 形状变化 ⇒ `_intent_digest` 与 approval
  request/binding digest 随之变化，旧 grant 在 prepare 阶段即 `approval_mismatch`，
  旧 intent 在 invoke 阶段被 binding 全等比较拒绝。

### Red → Green 记录（vertical slices）

命令均为仓库根目录下执行。

1. `test_interactive_open_binds_session_duration_until_execution`
   - Red：`.venv/bin/python -m pytest tests/browser/test_tools.py::test_interactive_open_binds_session_duration_until_execution -q`
     → `assert 1 == 0`：构造 registrations 时 `__init__` 已读 monotonic clock。
   - Green：同命令 → `1 passed`（构造/首次 prepare/re-prepare 零次读钟；
     invoke 后恰一次，`expiry == 1000.0 + 1800`）。
2. `test_sequential_interactive_opens_keep_independent_deadlines`
   - 首跑 Red：`RuntimeError: browser open failed after effect; cleanup confirmed`，
     原因是测试 fake（`RecordingEnvironment` 固定 session_ref，第二次
     `sessions.begin` 冲突），非产品行为；补 `UniqueSessionRefEnvironment`
     （每次 open 返回唯一 session_ref）后按计划“实现后补齐”直接
     Green：`1 passed`（两次 open 独立 deadline 2800/6800，总读钟次数 2）。
3. `test_final_drift_before_open_is_known_not_executed_zero_effect[revision|revoked]`
   （`DriftingProfileStore` 在第 4 次 `open()` 读取——即 invoke 内 revalidation
   之后的 callable 内 final 校验——注入 drift）
   - Red[revision]：`assert True is False`：现状静默消费 advance 后的 revision
     并执行 `environment.open`。
   - Red[revoked]：`ProfileRevokedError` 向上传播（unknown-outcome 语义），
     而非 closed `KnownNotExecuted`。
   - Green：同命令 → `2 passed`（executed=False、code
     `browser_open_binding_changed`、`environment.opened == []`、writer.lock
     不存在；revision 场景追加 acquire/release 证明 writer 无泄漏）。
4. `test_interactive_open_prepare_rejects_revoked_profile`
   - Red：revoked profile 仍返回 `ApprovalRequired`（isinstance 断言失败）。
   - Green：同命令 → `1 passed`（prepare 阶段 `binding_failure`，零 effect）。

### 验证（focused + touched-area，未跑 full suite）

- `.venv/bin/python -m pytest tests/browser/test_tools.py tests/browser/test_interactive_actions.py::test_expired_session_rejects_actions_zero_effect -q`
  → `18 passed`（acceptance 7 既有 adapter expiry zero-effect case 在内）。
- touched-area：`tests/browser/test_public_read.py tests/browser/test_composition.py tests/browser/test_receipt_identity.py tests/browser/test_upload.py tests/browser/test_download.py tests/browser/test_browser_cleanup.py` → `67 passed`；
  `tests/cli/test_018_browser_experience.py tests/architecture/test_observation_freshness.py` → `24 passed`（均构造
  `build_browser_tool_registrations`，受 monotonic 行为变化影响）。
- `.venv/bin/ruff check agent/browser/tools.py tests/browser/test_tools.py` →
  `All checks passed!`；`git diff --check`（touched files）→ OK。

### Caveats

- “writer 已获取后 spec 构造失败 → 释放 writer”分支在 public
  prepare/invoke 路径不可达（re-prepare 恒产生固定合法 duration 的 binding），
  属 defense in depth，无 public 行为测试覆盖。
- callable 内 final exact 校验与 `acquire_writer` 内部 metadata 重读之间仍存在
  极窄窗口。~~该窗口内的并发 drift 会以 `ProfileRevisionConflict` /
  `ProfileRevokedError` 传播并按 EXTERNAL unknown-outcome 处理~~
  （原 caveat 有误，已在 post-review fix 中修正并闭合：revoke 在该窗口实际
  显现为 `_verify_reference` 的 `ProfileIntegrityError`（status 不一致），
  不是 `ProfileRevokedError`；且这些异常现在都在 adapter 前被捕获为
  closed `KnownNotExecuted`，见下方 post-review fix 记录）。
- acceptance 6 未新增独立的“旧 grant 失配”直接断言测试，由 slice 1 的 binding
  形状断言（不再含 `session_expiry_monotonic`）与 KernelToolRuntime 既有
  approval/binding digest 全等机制覆盖。
- full pytest 与最终审计由 Codex 在独立审计闭合后只跑一次。

## Post-review fix（2026-09-08，executor r2）

fresh independent review 判定 **FAIL**，指出 P1：callable final profile check
到 `acquire_writer` 二次 metadata read 之间的 revision/revoke，以及 callable
profile `open` 的 notfound/integrity，均发生在 `BrowserEnvironment.open` 之前，
但裸异常被 Runtime 按 EXTERNAL 误归 unknown-outcome；
`ProfileLockHeldError`/`ProfileLockUnknownError` 也应在 adapter 前返回
`browser_open_unavailable`。按 vertical TDD 闭合，仅改动
`agent/browser/tools.py` 与 `tests/browser/test_tools.py`。

### 实现（agent/browser/tools.py）

- interactive `open` 的 `self._profiles.open(...)` final 校验与
  `acquire_writer(profile)` 合入同一个 try：在且只在 adapter 调用前捕获
  store 层异常——`ProfileNotFoundError`/`ProfileIntegrityError`/
  `ProfileRevokedError`/`ProfileRevisionConflict` → closed
  `KnownNotExecuted(code="browser_open_binding_changed")`；
  `ProfileLockHeldError`/`ProfileLockUnknownError` → closed
  `KnownNotExecuted(code="browser_open_unavailable")`。
- 捕获范围严格止于 `self._environment.open` 之前；既有
  `BrowserOpenNotStartedError`、adapter 之后的 unknown-outcome 与 quarantine
  语义不变。`acquire_writer` 抛异常即未创建锁，无需 release。

### Red → Green 记录（vertical slices）

命令均为仓库根目录下执行。

1. `test_writer_reacquire_drift_before_open_is_known_not_executed_zero_effect[revision|revoked]`
   （`AcquireTimeDriftStore` 在 `acquire_writer` 内部 metadata 二次重读前注入
   drift；final 校验读数正常通过）
   - Red[revision]：`ProfileRevisionConflict: profile reference revision stale`
     裸异常经 `runtime.invoke` 传播。
   - Red[revoked]：`ProfileIntegrityError: profile reference does not match
     stored identity` 裸异常传播——证实原 caveat 错误：revoke 在此窗口显现为
     `ProfileIntegrityError`（`_verify_reference` 的 status 不一致），不是
     `ProfileRevokedError`。
   - Green：同命令 → `2 passed`（executed=False、code
     `browser_open_binding_changed`、`environment.opened == []`、
     `writer.lock` 不存在；revision 场景追加 acquire/release 证明无泄漏）。
2. `test_second_open_of_active_profile_returns_unavailable`
   - Red：`ProfileLockHeldError: writer lock already held` 裸异常传播（同一
     active profile 第二次 open 的 public path）。
   - Green：同命令 → `1 passed`（executed=False、code
     `browser_open_unavailable`、`environment.opened` 长度仍为 1；直接
     `profiles.acquire_writer` 仍抛 `ProfileLockHeldError` 证明第一条 session
     的 writer 未被释放或偷取；随后 browser_close CLEANED）。
3. `test_sequential_interactive_opens_keep_independent_deadlines` 改写为
   production-like：同一 profile，第一次 open 后经 browser_close CLEANED
   （writer 释放），再推进 clock、第二次 open；不再依赖两份 profile 同时
   active。改写后实现前后均 `1 passed`（deadline 2800/6800 独立、总读钟
   2 次、session_ref 与 identity_digest 不同）。

### 验证（focused + touched-area，仍未跑 full suite）

- `.venv/bin/python -m pytest tests/browser/test_tools.py tests/browser/test_interactive_actions.py::test_expired_session_rejects_actions_zero_effect -q`
  → `21 passed`。
- touched-area：`.venv/bin/python -m pytest tests/browser/ tests/cli/test_018_browser_experience.py tests/architecture/test_observation_freshness.py -q`
  → `355 passed`。
- `.venv/bin/ruff check agent/browser/tools.py tests/browser/test_tools.py` →
  `All checks passed!`；`git diff --check`（touched files）→ OK。

### 剩余 caveat（r2 更新）

- callable final 校验 / `acquire_writer` 重读窗口内的并发 drift 现已 fail
  closed 为 `browser_open_binding_changed`；writer acquisition 的 guard 临界区
  内部不存在更晚的 pre-adapter metadata 重读。
- "writer 已获取后 spec 构造失败 → 释放 writer" 分支与 acceptance 6 的
  digest 覆盖方式维持 r1 记录不变；full pytest 与最终审计仍由 Codex 只跑
  一次。
