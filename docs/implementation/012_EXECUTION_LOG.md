---
title: 012 Trusted Continuity MVP - Execution Log
type: implementation-log
date: 2026-08-02
authority: non-authoritative-evidence
status: in-progress
---

# 012 Trusted Continuity MVP — Execution Log

本文件只记录非秘密命令、退出码、Red/Green 证据、设计决策与 remaining risk。它不是权威合同；
权威文档是 `STRATEGY.md`、`docs/architecture/012_TRUSTED_CONTINUITY_DESIGN.md`、
`docs/plans/2026-08-02-001-feat-trusted-continuity-plan.md`、`docs/implementation/012_LOOP_HANDOFF.md`。

## Environment

- 解释器：`/Users/jinkun.wang/work_space/my-first-agent/.venv/bin/python`（原仓库 venv，**只读执行**；
  不在原仓库安装/卸载包、不写入原仓库）。
- Python：`3.12.2`
- Ruff：`0.15.10`
- 工作目录（隔离副本）：`/Users/jinkun.wang/work_space/my-first-agent-012-loop.SzZaW9`
- 原仓库 `/Users/jinkun.wang/work_space/my-first-agent` 严禁修改。

## 关键边界（贯穿 U0–U8）

- 当前工作树**不是 clean HEAD**。HEAD 为 `7d935ac4af7121c54e1bdcc600763c3f0fbf54c2`，
  但树是 kernel cutover 之后的 dirty-but-green materialized tree。
- **禁止** `git reset` / `git checkout` / `git clean` / `git restore` 丢弃当前工作树，
  也禁止恢复已被 tracked-deleted 的 legacy runtime。旧实现不得被“恢复”。
- 不 commit / push / tag / 改 remote。
- 只修改隔离副本；credential 只按显式 env name 由 composition 读取；不读取/回显 `.env`、
  Claude settings/local memory、shell history、secret/private/runtime 文件。

---

## U0 — Freeze baseline and delivery controls

状态：完成。

### Baseline record（基线健康证据，非 012 完成证据）

git status 汇总（`git status --short | wc -l` = 974）：

- `D`（tracked-deleted legacy runtime，保持删除，不恢复）：923
- `M`（modified）：20
- `??`（untracked，含 kernel 源码与 012 权威文档）：31

基线门（在加入 U0 新测试之前采集）：

- `git diff --check` → exit `0`
- `.venv/bin/python -m ruff check .` → exit `0`
- `.venv/bin/python -m pytest -q -rx` → `376 passed`（`/tmp/012_baseline_pytest.txt`，耗时约 127s）

forbidden-symbol grep（`CodingLoop|GoalSessionDriver|ServiceLocator|service_locator|
dynamic_registry|DynamicRegistry|IntentRouter|IntentClassifier|intent_router|classify_intent`）
在 `agent/**/*.py` → 无匹配（证明这些并行执行/动态扩权符号不存在）。

### Red / Green — architecture inventory guard

新增 `tests/architecture/test_inventory_absence.py`（两个 guard）：

- `test_no_forbidden_parallel_execution_symbols_in_production`
- `test_production_never_uses_dynamic_module_registry`

覆盖计划 U0 第 3 个断言（不存在 `CodingLoop` / `GoalSessionDriver` / intent router model client /
dynamic service locator）。计划前两个断言（`generate` 唯一 owner = `agent/runtime/loop.py`、
callable `invoke` 唯一 owner = `agent/runtime/loop.py`）已由既有
`tests/architecture/test_cutover_absence.py::test_effect_owners_are_unique_in_production_sources`
证明，未重复实现。

因为被禁符号本就不存在，guard 对当前树天然 Green。为证明它**不是空断言**，用一次性 probe 做 Red 演示：
临时写入 `agent/_u0_red_probe.py`（含 `class CodingLoop` 与 `importlib.import_module`），
运行后立即删除，probe 未在工作树留下任何残留。

- Red（probe 存在）：`pytest tests/architecture/test_inventory_absence.py -q` → exit `1`，`2 failed`
  （两个 guard 都命中 probe：`agent/_u0_red_probe.py`）。
- Green（probe 删除后）：同命令 → exit `0`，`2 passed`。
- probe 清理确认：`git status --short agent/_u0_red_probe.py` 无输出。

设计决策：guard 用 AST 精确匹配名字集合，并单独禁止 `importlib` import / `import_module` 调用。
明确豁免 `agent/subagent/process_runner.py` 的 `__import__("contextlib")`（stdlib suppress 惯用法，
非动态扩权），避免误报。

### 009 delivery manifest / verify_materialized_tree.py 现状（诚实说明）

`docs/implementation/009_DELIVERY_MANIFEST.json` 是 **009 里程碑冻结产物**
（`schema=my-first-agent/delivery-manifest/v2`，`baseline_commit=7d935ac...`，956 entries）。
它早于 012，不包含 012 新增的权威/计划文档。

- `scripts/verify_materialized_tree.py --check-membership` → exit `1`，且**仅有 4 条 FAIL**，全部是
  “unknown untracked not admitted”：`STRATEGY.md`、
  `docs/architecture/012_TRUSTED_CONTINUITY_DESIGN.md`、
  `docs/implementation/012_LOOP_HANDOFF.md`、
  `docs/plans/2026-08-02-001-feat-trusted-continuity-plan.md`。
- 没有任何 009 交付文件“missing”或“digest 篡改”类失败。也就是说 009 交付基线完好，membership 失败
  纯粹是 012 权威文档尚未进入冻结的 009 manifest。

决策：**不**把 012 文件伪造进冻结的 009 manifest（其 `control_rule` 要求 post-gate 才写 control digest，
且 self-digest forbidden）。012 的 membership/architecture 可执行真值由 pytest 架构套件承担
（`tests/architecture/*`，使用 fixture / 临时树，随 012 变更保持 Green）。随 012 推进产生的
`agent/runtime/*.py` 等修改会让 `--check-membership` 继续报告差异，这些是合法 012 变更，不是 009 回归。
U8 文档阶段会再明确 012 交付清单如何独立记录，而不放宽 009 断言。

### U0 gates（加入新测试后）

- `git diff --check` → exit `0`
- `.venv/bin/python -m ruff check .` → exit `0`
- `.venv/bin/python -m pytest tests/architecture -q` → exit `0`，`26 passed`（约 48s）
- `.venv/bin/python -m pytest -q -rx` → exit `0`，`378 passed`（约 125s；= 376 基线 + 2 个 U0 guard）

U0 完成：full suite Green（完整退出码，非截断/timeout），新 guard 已证明可捕获违规且对当前树 Green。

### Remaining risk（U0）

- full suite 运行较慢（架构套件含 sandbox install / network 探测），必须以完整退出码为准，
  不接受 timeout/截断作为 pass。
- `verify_materialized_tree.py --content` / `--control-seal` 为重型模式，绑定冻结 009 manifest；
  012 阶段不据其判定完成，改由架构 pytest + U8 独立清单证明。

---

## U1 — Canonical Goal/control contracts and checkpoint v2

状态：完成。

### Executor continuity

Claude Code 以 `claude-opus-4-8`、`effort=xhigh`、`bypassPermissions` 完成 U0 后，在 U1
连续遭遇 provider `524 origin_response_timeout`。没有降级模型、降低 effort 或修改用户 Claude
配置；Codex 按既定 handoff 继续同一隔离副本，并以本日志作为后续交还边界。

### Red / Green — immutable contracts and reducers

新增 `tests/continuity/test_contracts.py`。每个合同先以缺失类型/函数或缺失 codec 行为形成 Red，
再做最小 Green；其中最后一组 lifecycle reducer Red 为：

- Red：`pytest tests/continuity/test_contracts.py -q -rx` → exit `2`，collection 失败，
  `ImportError: cannot import name 'cancel_goal' from 'agent.runtime.state'`。
- Green：contracts + lifecycle reducer + typed action 共 `12 passed`（并与 checkpoint tests
  合跑后为 `16 passed`）。

落地合同与不变量：

- immutable `GoalFrame`、proposed/admitted criteria、closed `GoalStatus` / `InteractionState`、
  `EvidenceRecord`、`CompletionClaim`、revision-bound `GoalDelta`；
- closed model control variants，control 与 callable tool call 互斥；
- user-authoritative `GoalAuthorizationBinding`、`CriterionAdmissionBinding`、
  `FactAdmissionBinding`，以及 non-secret canonical `ProviderDescriptor`；
- exact typed Goal actions 与 canonical action digest；
- create/progress/delta/pause/resume/cancel/claim/verify reducers；所有 Goal identity/revision stale
  输入 fail closed；
- pause/cancel/verify 遇到 `EXECUTING` 或 `AWAITING_RECOVERY` 必须先完成 unknown-effect
  recovery；安全 pause/cancel 不抹除已发生 facts；
- `RunStatus.COMPLETED` 不等于 `GoalStatus.VERIFIED_DONE`；模型 completion claim 必须引用当前
  Goal revision 的 evidence，且所有 mandatory admitted criteria 经 closed oracle/predicate
  对齐后才可 verified。

### Red / Green — strict checkpoint v2

新增 `tests/continuity/test_checkpoint_v2.py`：首次 round-trip Red 证明旧 codec 会丢弃 Goal/control/
disclosure/evidence；随后将 `LocalCheckpointStore` schema 提升为 v2，并为所有新增 canonical fields
加入 exact-key codec。v1、unknown fields、invalid nested invariant 均 fail closed；没有 fallback、dual
write 或隐式 migration；capacity 检查计算完整 v2 payload。

### U1 exit gate

- `pytest tests/continuity/test_contracts.py tests/continuity/test_checkpoint_v2.py -q -rx`
  → exit `0`，`16 passed`。
- 计划要求的 continuity + kernel contracts/state/checkpoint gate：
  `pytest tests/continuity/test_contracts.py tests/continuity/test_checkpoint_v2.py
  tests/kernel/test_contracts.py tests/kernel/test_state_transitions.py
  tests/kernel/test_checkpoint_corruption.py tests/kernel/test_checkpoint_recovery.py
  tests/kernel/test_checkpoint_store.py -q -rx` → exit `0`，`32 passed`。
- `git diff --check` → exit `0`。
- `ruff check .` → exit `0`，`All checks passed!`。

一次早期 gate 命令引用了不存在的 `tests/kernel/test_checkpoint_security.py`，exit `4`、无测试执行；
该结果没有被当作 pass。随后用 `rg --files tests/kernel` 解析真实文件名并执行上述完整、未截断 gate。

---

## U2 — Default owner-only state root and deterministic session selection

状态：完成。

### Executor continuity（诚实记录）

- `claude-opus-4-8` executor 在 U1 后连续遭遇 provider `524 origin_response_timeout`；
  owner 显式切换到 `claude-fable-5`（effort `ultracode`）继续同一隔离副本。模型交接，
  不是代码失败证据。
- 一次针对 `tests/cli/test_entrypoint.py` 的运行被中断并遗留后台进程；supervisor 终止了
  该进程。其结果按未知处理，**没有**被当作 pass；本单元所有 gate 均重新运行到完整退出码。
- 隔离副本没有本地 `.venv`。工具链使用原仓库
  `/Users/jinkun.wang/work_space/my-first-agent/.venv/bin/python`（3.12.2）与同目录 `ruff`
  **只读执行**；cwd 与全部写入均在隔离副本，不改原仓库。
- supervisor 在 524 退避期间对 `agent/continuity/sessions.py` 做过行为保持的最小 Ruff
  清理（stdlib import 排序 + `contextlib.suppress(FileExistsError)`），并复核 targeted
  Ruff Green；本 session 已核对该文件当前内容与语义未变。

### 实现范围（对照设计 §8）

- `agent/continuity/identity.py`：`WorkspaceIdentityV1` 绑定 canonical path + device/inode
  + 版本化 digest；软链接别名解析到同一 identity；不读取 workspace 内容。
- `agent/continuity/sessions.py`：默认 root `~/.local/state/my-first-agent/v1`，显式
  `--state-root` 覆盖；root 必须在 workspace 外、真实目录（逐组件拒绝 symlink）、owner-only
  `0700`/文件 `0600`；deterministic `workspaces/<scope-digest>/<conversation-id>.json`
  layout；bounded enumerate 只扫描当前 exact workspace state 目录（scandir 计数上限、
  unknown entry/orphan lock fail closed），无第二 catalog/mirror；启动选择规则 1–5
  （CREATED / RESUMED / SELECT_REQUIRED / NEEDS_AUTHORITY / RECOVERY_REQUIRED）全部落地；
  `EXECUTING`/`AWAITING_RECOVERY` 一律进入既有 unknown-effect recovery，不自动 invoke。
- `agent/continuity/restart.py`：`project_restart` 纯只读投影，零 Provider/Tool 调用；
  post-bootstrap 状态推进仍唯一属于 `AgentRuntime.run_turn`（composition 例外仅为
  排他初始化空 schema v2 checkpoint）。

### 跨进程 first-start lock：macOS `dir_fd` 失败与 no-follow 修复（决策记录）

早前实现尝试用 directory fd + `dir_fd` 相对 `os.open` 创建 `.bootstrap.lock`，在本机
macOS（Darwin 25.4.0）上真实失败。修复为：保持持有 `O_RDONLY|O_DIRECTORY|O_NOFOLLOW`
目录 fd 防止目录被替换，同时 lock 文件改用**绝对路径** `O_RDWR|O_CREAT|O_NOFOLLOW` 打开，
再以 `fstat` 校验 regular file、owner uid、`nlink==1`、mode `0600` 后 `flock(LOCK_EX)`。
`flock` 是跨进程原语；`test_concurrent_first_start_creates_one_valid_checkpoint_per_identity`
证明并发首启只产生一个合法 checkpoint（CREATED+RESUMED，目录内恰一个 `*.json`）。

### Red / Green — legacy `--state/--resume` 双工作流移除

设计 §8 只允许默认 root + 显式 `--state-root`；§14 禁止 compatibility fallback/双工作流。
`main.py` 残留的 `--state`/`--resume`/`open_checkpoint`（含无 flag 时的
`InMemoryCheckpointStore` 非持久 fallback）违反该合同，予以移除。

- Red：`pytest tests/cli/test_entrypoint.py -q -rx` →
  `test_legacy_state_and_resume_flags_are_removed` FAILED（`DID NOT RAISE SystemExit`，
  parser 仍接受 `--state`），`1 failed, 10 passed`。
- 最小 Green（`main.py`）：删除 `--state`/`--resume` 参数、`open_checkpoint`、
  `InMemoryCheckpointStore`/`LocalCheckpointStore`/`ConversationState`/`uuid4` 孤儿导入；
  产品启动唯一路径为 `open_workspace_session`。**关键细节**：argparse 默认允许前缀缩写，
  删除 `--state` 后它会静默变成 `--state-root` 的别名（复活兼容路径），故产品 parser 设
  `allow_abbrev=False`；scheduler parser 的独立必填 `--state-root` 合同未动。
- `agent/subagent/runner.py` 的 `InMemoryCheckpointStore` 是既有 bounded child-run
  ephemeral store（U1 前设计），不是产品持久路径，保留。

### 测试永不触碰真实默认 state root（test seam）

- 新增根级 `tests/conftest.py` autouse 护栏：`default_state_root(home=None)`（即将派生真实
  用户 home）在测试中直接 AssertionError fail loud；显式 fixture home 或测试自行
  monkeypatch 不受影响。这是 test-only seam，不进入产品代码。
- 为所有 `entrypoint.main(...)` 调用点注入临时 `--state-root`：
  `tests/cli/test_entrypoint.py`（smoke/provider/skill/TUI 生命周期共 8 处）、
  `tests/subagent/test_runner.py`（2 处）、`tests/mcp/test_integration.py`（1 处）。
- legacy 测试改写为权威行为：create-only/load-only 语义已由
  `tests/continuity`/`tests/kernel` checkpoint 套件拥有；新增
  `test_legacy_state_and_resume_flags_are_removed` 与
  `test_state_root_inside_workspace_fails_startup`；smoke 测试改断言默认 durable
  （state root 下出现 `workspaces/*/*.json`），删除旧 “not durable” 警告断言；
  checkpoint-load-failure 测试改经 `open_workspace_session` 注入 FailingStore。

### 架构清单最小同步

首次全量运行暴露 `tests/architecture/test_cutover_absence.py::
test_product_tree_contains_only_kernel_packages` 未收录 012 设计 §16 许可的
`agent/continuity/` 包 → 按 U0 规则最小同步 expected 集合与 package 集合
（加入 4 个 continuity 文件与 `agent.continuity`），未放宽任何断言。

### 文档最小同步

README 快速开始一节描述的“默认内存会话 + --state/--resume”已被本单元作废，按最小
修改同步为默认 durable + `--state-root` 语义并说明 v1 fail closed；完整 operator 文档
（disclosure/Goal controls/恢复语义）仍属 U8。

### U2 gates（全部完整退出码，无截断/timeout）

- supervisor 复核 focused（退避期间）：`pytest tests/continuity/test_state_root.py
  tests/continuity/test_restart_selection.py -q -rx` → exit `0`，`12 passed in 2.29s`。
- 本 session focused Green：`pytest tests/cli/test_entrypoint.py
  tests/continuity/test_state_root.py tests/continuity/test_restart_selection.py -q -rx`
  → `23 passed`。
- touched-area 回归：`pytest tests/subagent/test_runner.py tests/mcp/test_integration.py
  tests/scheduler tests/cli -q -rx` → `53 passed`（scheduler state-root 合同保持 Green，
  scheduler 未成为 Goal auto-driver）。
- `git diff --check` → exit `0`；`ruff check .` → exit `0`，`All checks passed!`。
- full suite：`pytest -q -rx` → 首次 exit `1`（唯一失败即上述架构清单缺 continuity 包），
  最小同步后重跑 → exit `0`，`405 passed in 42.82s`。

启动/重开 provider/tool send count = 0 由
`test_reopen_projects_goal_summary_without_provider_or_tool_call`、
`test_executing_checkpoint_enters_existing_unknown_effect_recovery` 与
`test_startup_does_not_scan_workspace_or_secret_paths` 以 monkeypatch 断言证明。

### Remaining risk（U2）

- 默认 root 的 owner/mode 检查依赖 POSIX 语义，仅在本机 macOS 验证；Linux CI 未运行
  （本项目当前无 CI，与基线一致）。
- `SelectGoal` 目前只有 headless/composition 路径消费（CLI 打印候选后 exit 2）；
  CLI/TUI 的交互式选择投影属 U4 parity 范围。
- Graphify：本单元只改产品 `main.py`/tests/新包清单，未刷新 graph（存在摄入 ignored/
  private 输入风险，安全跳过并在此记录）。

## U3 — Unified entry and reserved model control

### 单一入口与 Runtime control 路由

- `SubmitMessage -> AgentRuntime.run_turn` 保持唯一入口；没有增加 pre-runtime classifier、
  第二 Provider 调用路径或第二状态循环。
- Red/Green 已覆盖 direct answer、方向边界澄清、Goal 在 task tool prepare 前 CAS、无 Goal
  effectful tool fail closed、plain `done` 不终结 Goal，以及 `GoalProgress` 在同一 invocation
  内持久化后自动继续。
- `GoalProgress` Red：`tests/continuity/test_entry_routing.py` 初始 `1 failed, 7 passed`
  （Goal 仍为 `GOAL_READY`）；最小实现只在既有 `_drive` control dispatch 中调用
  `record_goal_progress` 并继续同一 loop，随后 `8 passed`。
- U3 引入的 effectful-tool-before-Goal guard 使若干旧测试 fixture 暴露为不诚实；仅调整测试
  seed 或把真正只验证 approval 的 scheduler fixture 改为 `READ_ONLY + ALWAYS`，没有弱化产品
  guard。该阶段全套件曾完整通过 `413 passed in 59.39s`。

### U3C G1A — 独立 control schema 与 pinned receipt

- `ContextPack` 增加独立 `control_schema`、`control_receipts`；保留控制名只有 contracts
  中的 `RESERVED_CONTROL_NAME` 一个产品真源。Schema 和原子 receipt 投影计入 mandatory
  pinned budget，放不下在 Provider 前 `ContextLimitError`，不冒充产品 tool/user text。
- focused：ContextPack/context/budget 三个目标测试 `3 passed`；相关 context/contracts
  回归 `14 passed`；Ruff、format check、`git diff --check` 均 exit `0`。

### U3C G1B — Provider request wire

- Anthropic/OpenAI 只在 wire 层追加 reserved schema；durable receipt 被投影为各协议的相邻
  原子 assistant-call/result 对，产品 `ContextPack.tools` 与普通 messages 保持不变。
- provider 回归 `39 passed`；seam/import boundary `2 passed`。两条 round-trip fixture 当时只在
  最后的 response parser 断言保持 Red，证明 request wire 已闭合而没有提前掩盖 G2。

### U3C G2 — 严格共享 response parser

- 扩展 Red 后，`tests/provider/test_continuity_control.py` 为 `60 failed, 5 passed`：六种合法
  control × 两 provider、17 个 malformed 变异 × 两 provider、双 reserved 与两种混排顺序
  都准确暴露旧 parser 的降级行为。
- 最小 Green 位于 `agent/provider/normalize.py`：两协议共用一个严格 decoder 和一个
  `_ResponseAccumulator` conflict path；exact keys、bool-not-int、closed enums、nested
  GoalFrame/GoalDelta/criteria、model-emitted receipt、混排与重复 control 全部 fail closed 为
  `ProviderProtocolError`。Provider 仍只依赖 `provider.protocol + runtime.contracts`。
- focused 文件：`65 passed`；本次接手后复跑完整 `tests/provider`：`104 passed`。

### U3 closure gates（本次接手复核）

- `pytest -q tests/provider tests/continuity/test_contracts.py
  tests/continuity/test_checkpoint_v2.py tests/continuity/test_entry_routing.py -rx` → exit `0`，
  `128 passed in 1.23s`。
- `ruff check .` → exit `0`；`git diff --check` → exit `0`。
- `rg -n "\\.generate\\(" agent --glob '*.py'` 只有
  `agent/runtime/loop.py` 一处生产调用；forbidden-loop/classifier 搜索无命中；provider execution
  surface import 搜索无命中。
- 接手后全套件首次复跑为 exit `1`：`479 passed, 1 failed in 185.75s`，唯一失败是
  `tests/mcp/test_session_behavior.py::test_no_subprocess_resource_leaks_after_close` 的一次
  FastMCP 子进程 `session_failure`；立即单独复跑同一测试 exit `0`，`1 passed in 5.75s`。
  该失败不在 U3 改动面且未稳定复现；仍不把该次 full suite 记为 Green，最终门必须再次
  完整复跑。
- `scripts/verify_materialized_tree.py` 的当前 CLI 要求
  `--check-membership|--content|--control-seal`，而 012 plan 的裸命令已漂移；裸命令 exit `2`
  只证明接口不匹配。三项真实 materialization/delivery 门留在 U8 按当前接口闭合。

### Remaining risk（U3）

- U3 的产品、focused 与架构门已闭合；仓库级 full suite 仍需在后续修改后重新取得完整
  exit `0`，不能使用上述 MCP 单测复跑替代。
- Graphify graph 不存在/不适用于当前 cutover，未刷新，所有结论直接核验物化源码。

文件变更：`main.py`、`tests/conftest.py`（新增）、`tests/cli/test_entrypoint.py`、
`tests/subagent/test_runner.py`、`tests/mcp/test_integration.py`、
`tests/architecture/test_cutover_absence.py`、`README.md`、
`agent/continuity/sessions.py`（supervisor Ruff 清理）。

## U4 — Goal controls、surface parity 与 Goal-aware approval

- 接手时 U4–U7 已有部分未验证实现；先运行全套件，得到 `527 passed, 2 failed`。两条准确失败
  都是 architecture inventory：process-local `ControlInbox` 合同错误地与 reducer contract 混在
  `runtime/control.py`，以及 012 许可产品树未物化登记新增高内聚模块。
- 最小修复把 `ControlBinding`/`ControlInboxRequest`/`ControlRequestKind` 移到 immutable
  `runtime/contracts.py`；`runtime/control.py` 只保留 process-local queue，并由 composition、Runtime、
  TUI 共享同一个实例。Architecture focused 复跑 `7 passed`。
- Runtime 在 provider 前、tool prepare 前和 result CAS 后轮询 inbox；pause/correct/cancel 只在安全
  checkpoint 由 reducer 持久化。Goal delta 修订 revision 并清空 stale next-step/claim/evidence；
  authority-changing delta 停在 `NEEDS_AUTHORITY`。`BlockedClaim` 保存 blocker、safe attempts、resume
  condition 并投影为 `BLOCKED`。
- CLI/TUI/headless 使用同一 typed action builder 和 `GoalView.legal_actions`；加入
  `/ack-provider`、`/pause`、Goal-aware `/resume`/`/cancel`。U4/TUI focused 历次闭合为 `31 passed`
  与相关 `13 passed`；后续组合回归包含在 U7 的 `75 passed`。

## U5 — Remote disclosure 与 destination/data-class safety

- 修正 `ContextPack.data_classes`：只披露实际被预算选中的 goal/user/tool/history/workspace-memory/
  owner-preference/recalled-context 组，不再把被淘汰 source 类别伪报为已发送。
- `tests/provider/test_destination_safety.py` 覆盖 URL userinfo/query/fragment、非 loopback plain HTTP、
  redirect、ambient proxy、credential repr/error；production client 固定 `follow_redirects=False`、
  `trust_env=False`。
- durable disclosure receipt 精确绑定 family/model/canonical destination/data classes；owner preference
  新类别和 event loss 均不能绕过新 acknowledgement。Provider/context focused 回归 `128 passed`；
  disclosure + preference/restart 交叉回归 `10 passed`。

## U6 — Runtime-owned completion evidence

- `ClosedEvidenceRegistry` 每次从 raw durable facts 重新推导 evidence，并与既有 exact record 比对；
  tampered stored evidence、unknown effect、fake/mock metadata、zero/weakened mandatory criterion 均拒绝。
  `USER_CONFIRMATION` 只接受 exact durable user confirmation fact。U6 focused `31 passed`。
- 模型 `GoalProposal` 不得携带 admitted criteria；model Goal delta 不得修改 admitted criteria 或
  authority snapshot。exact approved `write_file` 时，Runtime 从 authoritative user fact、Goal/revision、
  approved call path/content digest 铸造一个 closed `FILESYSTEM_DIGEST` criterion；随后必须由 exact
  `read_file` result 才能满足。审批/effect/checkpoint 回归 `33 passed`。

## U7 — Owner preference provenance 与 truthful forget

- 增加 immutable `PreferenceAdmissionBinding`；Runtime 只从当前 durable `USER_MESSAGE` 且 exact 文本
  相等时派生，ToolRuntime 拒绝模型伪造 binding。confirm/correct/forget 全部走同一 governed tool
  path 和 approval。
- owner store 位于固定 product state root，绑定 provider identity digest；correction 持久化
  `supersedes=<record>@<revision>`，forget 写 tombstone 并只承诺停止未来 local active recall，
  explain 不泄露路径。Memory focused `48 passed`；CLI/TUI/composition/continuity/architecture 回归
  `75 passed`；完整 Runtime preference journey 包含在上述交叉 `10 passed`。

## U8 — Frozen journey 与真实 HTTP 可运行性修复

### Offline reference

- 初版 reference 为 `4 passed, 2 failed`；两条都不是产品失败：一个 assertion 错把带 revision 后缀的
  fact ID 当 `endswith(call_id)`，另一个手工 fixture 的 `next_action_seq` 与已有 action fact 冲突。
  修正 oracle/fixture 后 `6 passed`。
- 对照计划发现 J3、destination drift、preference poisoning/correct 和 stale stored evidence 未冻结；
  补齐后 `tests/reference/test_012_trusted_continuity.py` 为 `8 passed`。它现在覆盖 answer/clarify、
  task→approval→fresh store restart→effect once→read-back→`VERIFIED_DONE`、unknown effect、multiple
  candidate、correction/pause/resume/cancel、production HTTP MockTransport disclosure、preference
  poisoning/correct/forget 与 false/stale completion。

### 真实 Provider 前发现并闭合的两条 stop-ship

1. production control schema 当时只描述 `kind/correlation_id`，严格 parser 虽 Green，真实模型无法从
   schema 构造 GoalFrame/CompletionClaim。改为六种 closed discriminated variants，Goal proposal 明确
   `admitted_criteria maxItems=0`，delta schema 不暴露 admission/authority mutation。Provider/entry
   focused `74 passed`，随后 trusted-context focused 纳入 `109 passed`。
2. 模型必须填写的 authoritative source fact ID、workspace digest、authority snapshot 当时没有进入
   ContextPack；Goal 建立后的 `trusted_goal` 也会被 production adapters 当 unknown block 拒绝。
   增加 Runtime-owned `GoalBootstrap` pinned block，模型只能原样引用，`accept_goal_proposal` 再 exact
   校验；composition 从 canonical workspace/provider/tool definitions 生成 authority snapshot；两个
   adapters 对 bootstrap/Goal 做 closed validation 后投影为明确前缀的 canonical text。该修复不增加
   Provider owner 或 mutation path。

### E3 harness

- 新增 `scripts/run_012_e3.py`：只使用 `build_model_provider` production HTTP adapter、静态 composition、
  `LocalCheckpointStore` 与唯一 Runtime；外层最多处理 12 个 disclosure/一个 exact write approval 的
  operator boundary，不实现 model/tool loop。
- Harness 七 claim、环境合同与 secret-free receipt 见
  `docs/acceptance/012_TRUSTED_CONTINUITY_E3.md`。在显式空环境运行 exit `2`，准确输出
  `NEEDS_E3_CONFIG(...)`，没有网络；partial config 输出 `E3_BLOCKED(...incomplete_config)`。
  `tests/reference/test_012_e3_harness.py` 锁定配置 marker 与禁止 Fake/Scripted/CodingLoop，合并后
  `tests/reference` 为 `10 passed`。
- 真实 Provider E3 尚未运行；不得把 MockTransport/reference 记为 E3 或 `accepted`。

### U8 尚待最终记录

- README/operator/E3 文档已更新；本节之后仍需写入最终未截断 Ruff/full pytest/diff/architecture
  search/materialization 结果。
- 只有全部本地门 Green 后，真实四项配置才可以成为唯一缺口；fresh independent reviewer 必须在
  真实 E3 receipt 后执行，当前不得写 `012_REVIEW_PASS`。

### U8 最终离线与 materialized closure

状态：本地 E1/E2/E2M 完成；真实 E3 配置是当前唯一缺口，012 整体仍未满足 Definition of Done。

#### 012 独立交付层

009 manifest 是已封存的 Kernel/capability 候选树，不能由 012 executor 改写真值。新增：

- `scripts/verify_012_materialized_tree.py`
- `docs/implementation/012_DELIVERY_SEAL.json`
- `tests/architecture/test_012_delivery_layer.py`

012 verifier 从 009 pinned baseline/entries 物化 base candidate，再叠加当前 012 exact overlay；seal 用
`base_manifest_sha256 + sorted(path, operation, git_mode, sha256)` 的 canonical root digest 绑定
**79 个** ordinary entries。seal、verifier 与本 execution log 是 controls；verifier 自身 digest 由 seal
绑定，execution log 作为 post-gate factual record 不反向进入其记录的 ordinary root。verifier 没有
generate/write 模式，不改真实 Git index，不读取 denied/private/runtime 路径。

- `python scripts/verify_012_materialized_tree.py --check-membership` → exit `0`，
  `012 overlay membership ok: 79 exact entries`。
- delivery control tests → exit `0`，`2 passed`。

#### Materialized Red 暴露的回归与修复

第一次 012 `--content` 不是 Green：exit `1`，`18 failed, 547 passed`。全部失败都由完整
model-readable continuity control schema 成为 mandatory pinned context 后，旧 Kernel 测试夹具仍使用
`max_input_tokens=1000` 或按旧 schema 固定成本构造极小窗口引起；Runtime 在 intended event/effect
oracle 前正确地返回 `context_core_too_large`。另一个断言仍期待旧 flat `kind.enum` schema，而 production
schema 已是六个 closed `oneOf` variants。

修复没有缩短或放宽 production schema：

- 不测试 context budget 的 effect/event/error/approval 夹具改用 8000-token 测试窗口；
- eviction/budget tests 在旧相对窗口上显式计入 1200-token control-schema 增量；
- schema oracle 改为检查六个 variant 的 exact `kind.const` 顺序。

Kernel rerun：exit `0`，`77 passed`。随后工作树完整 pytest：exit `0`，`565 passed`。

#### 干净 E3 启动 Red 与修复

第一次使用显式空环境直接运行 runner 时，在读取配置前出现
`ModuleNotFoundError: No module named 'agent'`：原测试偷偷注入了 `PYTHONPATH`。修复后 runner 从自己的
文件位置解析 repo root，不依赖 caller ambient `PYTHONPATH`；测试也删除该注入。

- E3 harness focused：exit `0`，`2 passed`。
- `env -i PATH=/usr/bin:/bin <python> scripts/run_012_e3.py` → exit `2`，stdout exact：
  `NEEDS_E3_CONFIG(stage=U8, required=FIRST_AGENT_E3_PROVIDER,FIRST_AGENT_E3_BASE_URL,FIRST_AGENT_E3_MODEL,FIRST_AGENT_E3_API_KEY)`；
  stderr 为空，没有网络请求。

#### 最终未截断 gates

- `git diff --check` → exit `0`。
- `/Users/jinkun.wang/work_space/my-first-agent/.venv/bin/ruff check .` → exit `0`，
  `All checks passed!`。
- `/Users/jinkun.wang/work_space/my-first-agent/.venv/bin/python -m pytest -q -rx` → exit `0`，
  `565 passed in 57.96s`（最终 ordinary tree rerun）。
- `rg -n "\.generate\(" agent --glob '*.py'` → 只有
  `agent/runtime/loop.py:672: response = self._provider.generate(context)`。
- `rg -n "CodingLoop|GoalSessionDriver|service_locator|dynamic_registry" agent main.py` → 无匹配。
- `python scripts/verify_012_materialized_tree.py --check-membership` → exit `0`，79 exact entries。
- `python scripts/verify_012_materialized_tree.py --content` → exit `0`；non-editable install、neutral cwd、
  console entrypoint origin、deny-network preflight、materialized Ruff 与完整 materialized pytest 全部通过；
  `565 passed in 100.18s`，`012 content gate: ALL CHECKS PASSED`。

#### 当前唯一缺口

当前 Codex 进程只检查四个环境变量的 presence（不读取/回显值），四项均 absent。因此真实 Provider E3
尚未运行，不能宣称 012 accepted，也不能开始/伪造 final independent review。准确继续条件是 operator
在运行环境提供 `FIRST_AGENT_E3_PROVIDER`、`FIRST_AGENT_E3_BASE_URL`、`FIRST_AGENT_E3_MODEL`、
`FIRST_AGENT_E3_API_KEY`；E3 七项全部 true 后，再启动 fresh independent reviewer 并修复其所有
P0/P1/P2 correctness/security findings。

### 2026-08-02 Official DeepSeek E3 compatibility closure（取代上述 pending 状态）

状态：真实 Provider E3 已 accepted；普通树与 materialized tree 最终门 Green。012 只剩 fresh
independent reviewer 这一项程序性 DoD，当前没有把本地自审冒充独立审查。

#### 官方合同复核

- 只依据 DeepSeek 官方文档复核：OpenAI-compatible base URL 为 `https://api.deepseek.com`，请求为
  `POST /chat/completions`（`/v1` 兼容）；model 使用 `deepseek-v4-flash`。
- DeepSeek OpenAI 格式默认开启 thinking；thinking + tool calls 要求后续请求回传
  `reasoning_content`。Kernel v1 明确不持久化 provider-specific opaque reasoning，因此通过显式
  `thinking: {"type":"disabled"}` 使用非思考模式，没有增加第二套 continuity/loop。
- strict Tool Calls 只在 Beta endpoint 可用，并要求 closed schema 的全部 object properties 都进入
  `required`；normal endpoint 不保证 schema validation。012 保持 normal endpoint + shared strict
  Runtime decoder fail-closed，不用 Beta-only 行为伪造通用兼容性。
- 官方依据：`https://api-docs.deepseek.com/zh-cn/`、
  `https://api-docs.deepseek.com/zh-cn/api/create-chat-completion/`、
  `https://api-docs.deepseek.com/zh-cn/guides/tool_calls/`、
  `https://api-docs.deepseek.com/zh-cn/guides/thinking_mode/`。

#### Red → Green 与有限真实诊断

- 真实 request admission 证明 `/chat/completions` 与 `/v1/chat/completions` 都可到达；旧 `oneOf` /
  unsupported keyword control schema 被 endpoint 400 拒绝。最终 wire schema 只使用 portable 基础
  JSON Schema；kind-specific exact keys/types/invariants 仍由 `agent/provider/normalize.py` 统一拒绝。
- model 曾在 trusted Goal 后重复 `goal_proposal`、在 no-Goal 阶段直接请求 effectful tool，或 read-back
  后提前返回文本。最终 ContextManager 在 no-Goal 阶段隐藏 effectful tool definitions、trusted Goal
  后不再广告 `goal_proposal`，E3 prompt 明确 completion receipt 前不得宣布结束。Runtime 的 prepare
  guard 保持第二道防线。
- post-review 重新运行暴露两条真实缺陷并修复：checkpoint oracle 只做 raw byte 比较时可能漏掉 JSON
  escaped full prompt/secret；现在先 parse JSON 并递归检查 exact secret/system prompt/header，且不再把
  `goal_authorizations` 之类业务字段子串误报。DeepSeek 还会把 `created_at`/`updated_at` 生成为空串；
  wire schema 现在明确 non-empty ISO-8601，E3 使用确定性时间，immutable `GoalFrame` 仍拒绝空值。
- 本轮共执行 9 个 bounded、独立 temp workspace/state-root 的真实 E3 invocation；失败分类包括
  `malformed_control` 与 active Goal 未到 `VERIFIED_DONE`，均未被记为成功。最后一次 accepted run
  request count 为 5；没有无限重试、没有重放旧 temp effect。
- 产品入口不再只让 E3 特判：`first-agent`、`first-agent-schedule` 和 process-isolated SubAgent 的
  non-secret provider spec 都可显式传 `--thinking-mode disabled`；默认 generic OpenAI-compatible
  adapter 仍不擅自添加 vendor-specific 字段。

#### 非秘密真实 E3 receipt

- Receipt：`docs/acceptance/012_TRUSTED_CONTINUITY_E3_RECEIPT.json`。
- identity：`openai_compatible` / `deepseek-v4-flash` / official DeepSeek destination digest；5 requests；
  Goal `e3-report-create` revision 1。
- 七项全部为 `true`：disclosure-before-send、direct-answer-no-Goal、Goal-before-effect、effect exactly once、
  deterministic evidence → `VERIFIED_DONE`、restart without send、checkpoint excludes secret/header/full
  system prompt。receipt 不含 key、header value、绝对 workspace path 或 request/response body。

#### 最终未截断 gates（receipt 与最后代码之后）

- focused DeepSeek/context/provider：`126 passed`；CLI/SubAgent/provider/E3：`68 passed`。
- `git diff --check` → exit `0`。
- `/Users/jinkun.wang/work_space/my-first-agent/.venv/bin/ruff check .` → exit `0`，
  `All checks passed!`。
- `/Users/jinkun.wang/work_space/my-first-agent/.venv/bin/python -m pytest -q -rx` → exit `0`，
  `575 passed in 43.84s`。
- `python scripts/verify_012_materialized_tree.py --check-membership` → exit `0`，
  `86 exact entries`。
- `python scripts/verify_012_materialized_tree.py --content` → exit `0`；non-editable install、neutral cwd、
  console origin、deny-network preflight、materialized Ruff 与 pytest 全部 Green，
  `575 passed in 44.83s`，`012 content gate: ALL CHECKS PASSED`。
- `rg -n "\.generate\(" agent --glob '*.py'` → 唯一 production call site 为
  `agent/runtime/loop.py:672`；禁止的 `CodingLoop|GoalSessionDriver|service_locator|dynamic_registry` 无匹配。

#### Review 状态

- 本地 fix-first diff review 发现并修复两项：JSON-escaped checkpoint oracle 漏报，以及普通产品入口
  未携带 explicit thinking mode 的 E3/产品配置漂移；修复后的 focused/full/materialized gates 如上。
- 当前无已知 unresolved correctness/security finding，但尚未执行计划要求的 fresh independent Claude
  reviewer，因此不得写 `012_REVIEW_PASS`，也暂不勾选整体 U0–U8 / independent reviewer DoD。
- Graphify 未刷新：现有 graph 对 012 dirty overlay 已 stale，刷新可能摄入不属于候选树的 ignored/private
  输入；本轮使用 exact file/diff/search/test evidence。

### 2026-08-03 Fresh independent final review

状态：`012_REVIEW_PASS`。fresh Claude session `84efc22c-65ff-4506-af89-af42cb78c0e1`
使用 `claude-fable-5`、effort `xhigh`、read-only 工具完成独立审查；没有修改文件、没有读取秘密，
未发现 unresolved correctness/security P0/P1/P2 finding。

Reviewer 没有信任 executor 摘要，而是直接读取 012 design、plan、完整 execution log、E3 protocol/
receipt、delivery seal/verifier、当前完整 diff 与物化源码，并独立重跑：

- `git diff --check` → exit `0`；Ruff → exit `0`，`All checks passed!`。
- ordinary full pytest → exit `0`，`575 passed in 48.22s`。
- overlay membership → exit `0`，`86 exact entries`。
- materialized content gate → exit `0`，`575 passed in 44.10s`，
  `012 content gate: ALL CHECKS PASSED`。
- architecture search 仍只有 `agent/runtime/loop.py:672` 一个 production `.generate(`；禁止的
  second-loop / classifier / service-locator symbols 无匹配。
- working-tree credential pattern scan 只命中 README placeholder 与测试 fixture，无真实 secret。
- DeepSeek destination digest 独立重算后与 receipt 精确一致。

Reviewer 记录的非阻塞 caveat：真实 E3 因 reviewer 无配置不能现场复放；Goal-aware 免重复审批路径当前
仍 fail-closed 地休眠；Scheduler 对 `AWAITING_DISCLOSURE` 的分类可在后续改善；重复/stale control 当前
fail-fatal 而非给模型修复提示；E3 oracle 只匹配完整 system policy；POSIX owner/mode 仅在本机 macOS
验证。这些都不构成 012 的 P0/P1/P2 或虚假完成。

本记录之后由 operator 同步 DoD/E3 review 状态、重算 delivery seal，并重新运行最终门；最终结果追加
在下一节。原仓库、secret/private/runtime、真实 effect 之外的外部状态、commit/push 均未触碰。

### 2026-08-03 Post-review final seal and gates

- 计划 DoD 与 E3 review 状态已同步；delivery overlay 仍为 86 个精确条目。
- `012_DELIVERY_SEAL.json` 的最终 `overlay_root_sha256` 为
  `2bcb48c8702f65d57f29a167b1673c259f3824253c8b020a2f32918e73f355e5`。
- `git diff --check` → exit `0`。
- Ruff full tree → exit `0`，`All checks passed!`。
- overlay membership → exit `0`，`86 exact entries`。
- architecture search → 唯一 production `.generate(` 仍为 `agent/runtime/loop.py:672`；禁止 symbols
  无匹配。
- ordinary full pytest → exit `0`，`575 passed in 58.11s`。
- materialized content gate → exit `0`，`575 passed in 66.35s`，
  `012 content gate: ALL CHECKS PASSED`。

最终状态：U0–U8、真实 DeepSeek E3、fresh independent review 与 post-review seal/full gates 全部闭合；
`012_REVIEW_PASS`。没有 commit/push，也没有修改原仓库。
