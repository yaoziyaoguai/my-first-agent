---
title: 012 Trusted Continuity MVP - Claude Code Loop Handoff
type: implementation-handoff
date: 2026-08-02
authority: 012-loop-protocol
status: ready
---

# 012 Trusted Continuity MVP — Claude Code Loop Handoff

## 1. What this loop is

这是 First Agent **外部开发过程**：使用已经配置好的 Claude Code 读取 012 权威文档、实现代码、运行验收、修复失败并交给独立 reviewer。它不是 First Agent 产品内的 capability，不得在 `agent/`、`main.py` 或产品 CLI 中创建 CodingLoop、supervisor、daemon 或第二个 Runtime。

## 2. Authorized execution envelope

用户授权 Claude Code 在 012 隔离副本内拥有最大文件、Bash 和测试权限，并要求：

- model selector：`claude-opus-4-8`
- effort：`xhigh`
- permission mode：`dangerously-skip-permissions`

“最大权限”只表示隔离项目内不为普通编辑/命令反复询问，不取消以下边界：

- 不修改原仓库。
- 不修改用户级 Claude settings、auth、base URL、proxy、model aliases 或 credential files。
- 不读取/回显 `.env`、secret、private、Claude memory、shell history 或 runtime session data。
- 不 commit、push、tag、改 remote、force/reset/clean/restore/checkout 丢弃工作树。
- 不把源码、文档或测试发送到用户已配置 Claude Provider 之外的其他服务。
- 真实产品 Provider E3 只使用显式环境合同；不搜索 key。

启动后必须保留 Claude Code `system/init` receipt。Requested selector 与 receipt 中实际 serving model 不一致时，不得把它伪报为 `claude-opus-4-8`；记录差异并停止请求用户决定。

## 3. Authoritative inputs

Executor 按顺序完整读取：

1. `AGENTS.md`
2. `STRATEGY.md`
3. `docs/architecture/KERNEL_ARCHITECTURE.md`
4. `docs/architecture/EXTENSION_CONTRACTS.md`
5. `docs/architecture/012_TRUSTED_CONTINUITY_DESIGN.md`
6. `docs/plans/2026-08-02-001-feat-trusted-continuity-plan.md`
7. 当前 `git status`、materialized source/tests、`docs/implementation/012_EXECUTION_LOG.md`（存在时）

Graphify graph 早于当前 cutover，只能作为线索；任何结论必须直接核验当前物化源码。010 是宽范围历史计划，不得把其 deferred optimizer/dynamic authority 内容重新带入 012。

## 4. Executor prompt

以下文本原样作为首个 Claude Code prompt；supervisor 恢复时只附加最新 gate/failure 与“继续同一目标”，不改产品范围。

```text
你是 my-first-agent 的 012 Trusted Continuity MVP 主执行者。你拥有当前隔离副本内的最大文件/Bash/测试权限；不要请求普通可逆开发步骤的批准。你不是在设计产品内 CodingLoop，而是在外部持续开发 First Agent。

先完整读取 AGENTS.md、STRATEGY.md、docs/architecture/KERNEL_ARCHITECTURE.md、docs/architecture/EXTENSION_CONTRACTS.md、docs/architecture/012_TRUSTED_CONTINUITY_DESIGN.md、docs/plans/2026-08-02-001-feat-trusted-continuity-plan.md、当前 git status 和 materialized source/tests。创建并持续更新 docs/implementation/012_EXECUTION_LOG.md。

目标：严格按计划完成 U0-U8，使同一个 First Agent 入口能够直接回答、最小澄清、建立 durable Goal、在唯一 AgentRuntime.run_turn 内持续执行、跨重启安全恢复、支持 pause/correct/cancel、在远程 Provider 发送前完成 disclosure、以独立 evidence 进入 VERIFIED_DONE，并提供 provenanced workspace fact 与 owner-local preference。用户不选择模式，也不反复输入“继续”。

绝对不变量：
1. AgentRuntime.run_turn 仍是唯一 production model/tool loop 和 checkpoint 初始化后的 state mutation owner。Composition 只可排他创建空 checkpoint 与 deterministic session locator；不得写 Goal、处理 action 或推进既有状态。
2. ContextManager 独占模型上下文；ToolRuntime 独占 callable tool prepare/policy/invoke。
3. Provider adapter 只做 ContextPack -> ModelResponse；不得另起分类调用或推进 state。
4. 不创建 pre-runtime classifier、第二 Runtime、GoalStore 双写、CodingLoop、daemon、dynamic registry、compatibility fallback 或 dormant flag。
5. dynamic multi-root authority、自动学习/optimizer/canary/promotion、PC ambient monitoring 均不在 012。
6. 不恢复 tracked-deleted legacy runtime，不 reset/checkout 当前 dirty baseline。

工作方式：
- 从 U0 开始顺序推进到 U8。每项行为/架构改变先写准确 Red，运行并记录真实失败，再做最小 Green。
- 一个 focused test Green、一个 unit Green、一次 full suite Green 都不是停止点；自动进入下一项。
- 失败时先诊断根因并修复；不要把关键工作丢给 background Agent 后自己结束。
- 只在产品合同真实不可同时满足、需要破坏既定用户边界、或全部本地门通过后唯一缺少真实 E3 配置时停止。
- 不以测试 timeout、截断输出、未取 exit code、mock/fake 或模型自报作为 pass。
- 每个 unit 在 execution log 写 Red/Green 命令、exit code、设计决策、文件、remaining risk。

安全与权限：
- 只修改当前隔离副本；不碰原仓库。
- 不 commit/push/tag/改 remote。
- 不读取或输出 .env、secret/private/runtime、Claude settings/local memory、shell history；credential 只按显式 env name 由 composition 读取。
- 不修改用户级 Claude 配置。
- 真实产品 E3 仅使用计划列出的 FIRST_AGENT_E3_* 环境合同；缺失时先完成所有离线门。

完成前必须运行未截断：
git diff --check
.venv/bin/ruff check .
.venv/bin/python -m pytest -q -rx
.venv/bin/python scripts/verify_materialized_tree.py

如果隔离副本没有 .venv，使用明确已知的项目 Python 或创建 project-only venv，并记录解释；不要读取秘密配置。

Stop protocol：
- 本地门 Green 但 E3 配置缺失时，只输出：
  NEEDS_E3_CONFIG(stage=U8, required=FIRST_AGENT_E3_PROVIDER,FIRST_AGENT_E3_BASE_URL,FIRST_AGENT_E3_MODEL,FIRST_AGENT_E3_API_KEY)
  同时 execution log 必须证明它是唯一缺口。
- E3 配置存在但真实调用无法完成时，只输出：
  E3_BLOCKED(stage=U8, reason=<incomplete_config|auth_failed|endpoint_unreachable|rate_limit_exhausted|provider_protocol|model_incompatible>)
  同时保存不含秘密的失败 receipt；该 marker 是暂停态，不是完成。
- E3 和全部门通过后，输出 012_EXECUTOR_READY_FOR_REVIEW，并附完整 gate/receipt 路径；这只是交给 reviewer，不是最终完成。
- 其他情况下不得输出完成 marker。继续工作。
```

## 5. Supervisor behavior

Supervisor 位于 repo 外的控制目录，只做 Claude Code process supervision；它不包含产品逻辑。

### Launch

- working directory 必须是已核验的 012 隔离副本。
- 使用 Claude Code CLI 的 exact model/effort/permission flags；不写用户 config。
- stdout 使用 `stream-json` 或等价机器可读格式保存到控制目录；stderr 分开保存。
- 保存 session ID、init receipt、exit code 和最后一个合法 marker；不保存 credential/header。

### Continue, do not restart the task

- 正常进程退出但没有合法 stop marker：使用同一 session ID resume，并提供最小恢复 prompt，要求先读 execution log/current diff/last failing output 再继续。
- 429/rate limit/overloaded：记录 provider error 和声明的 reset time；额度恢复后 resume 同一 session。不要创建多个 executor 同时改同一副本。
- context limit/session corruption：新建 executor session，但 handoff 必须包含权威文档、execution log、current diff、未完成 unit 和最后 gate；不能重做已验证工作。
- test timeout/truncated output：视为未知，重新运行到完整 exit code。
- executor 请求普通文件/Bash权限：permission mode 配置错误，修正 launch，不让用户逐项批准。

### Supervisor state machine

- init receipt model mismatch、越界请求或无法由权威文档解决的真实合同冲突 → 停止并找用户。
- `NEEDS_E3_CONFIG(...)` 或 `E3_BLOCKED(...)` → 暂停并把准确配置/失败类别交给用户；两者都不满足 Definition of Done。
- `012_EXECUTOR_READY_FOR_REVIEW` → 启动 fresh reviewer；不得直接宣称完成。
- `012_REVIEW_FINDINGS` → 恢复 executor，按 finding 做 Red → Green，再启动 fresh reviewer 复审完整 diff。
- `012_REVIEW_PASS` → 生成最终报告；只有此状态可以结束 012 loop。
- 无合法 marker 的正常退出、timeout、截断或可恢复 provider error → 恢复同一 executor session 继续。

## 6. Recovery prompt template

```text
继续同一个 012 Trusted Continuity MVP executor session。不要重新规划或改变范围。

先读取 docs/implementation/012_EXECUTION_LOG.md、当前 git diff/status、上一轮 stream 的最后完整 gate/failure。确认上一个 unit 的真实状态，然后从第一个未闭合 Red/Green/exit gate 继续。

阶段性 Green 不是停止点。除非全部离线门已通过且真实 E3 配置是唯一缺口，否则不得输出 NEEDS_E3_CONFIG。若配置存在但 E3 失败，只能输出准确 E3_BLOCKED 并保存非秘密 receipt。NEEDS_E3_CONFIG/E3_BLOCKED 都不是 DoD。除非 U0-U8、真实 E3、full gates 全通过，否则不得输出 012_EXECUTOR_READY_FOR_REVIEW。

继续遵守：唯一 AgentRuntime.run_turn 与 checkpoint 初始化后的 mutation ownership；composition 只可排他创建空 checkpoint；无第二 loop/classifier/GoalStore；不碰原仓库/用户 Claude 配置/秘密/private/runtime；不 commit/push。
```

## 7. Fresh independent reviewer prompt

Reviewer 必须是新 Claude Code session，不能 resume executor。它可以修改同一隔离副本修复 finding，但第一次 pass 先只审计并给 raw findings。

```text
你是 012 Trusted Continuity MVP 的独立 correctness/security/architecture reviewer。不要相信 executor 的完成声明。

完整读取 AGENTS.md、STRATEGY.md、012 design、012 plan、012 execution log、当前完整 diff、全部新增/修改测试和真实 E3 原始非秘密 receipts。以当前 materialized tree 为准；Graphify 可能陈旧。

先只读审计并主动构造失败场景：第二模型调用/第二 mutation owner、task tool before Goal CAS、默认非持久或错误 auto-resume、multiple candidate 猜测、EXECUTING cancel/replay、stale Goal/evidence/approval binding、remote send before disclosure、destination/data-class drift、false VERIFIED_DONE、workspace/owner Memory poisoning、cross-workspace leak、dishonest forget、CLI/TUI/headless parity drift、secret/private/runtime evidence、mock 冒充 E3、截断/超时 gate。

直接运行必要 focused tests 和完整 gates，保存退出码。不要读取 .env/secret/private/runtime 或用户 Claude 配置，不碰原仓库，不 commit/push。

输出：
- 有任何 correctness/security P0/P1/P2：输出 012_REVIEW_FINDINGS，逐项给文件/行、可复现命令、期望/实际、修复标准；不得输出 pass。
- 无上述 finding 且 U0-U8、E3、full gates 的原始证据完整：输出 012_REVIEW_PASS，并列出实际复跑的命令、exit code、E3 receipt 和 residual caveats。
- E3 未运行或证据不完整：不能输出 pass；准确指出唯一缺口。
```

## 8. Fix-and-review loop

1. Reviewer 返回 findings 后，恢复 executor session，只给 findings 与复现证据；executor 逐项 Red → Green 修复并跑 touched/full gates。
2. 再启动新的 reviewer session 或清空 reviewer context 后重新审完整 diff，不能只看修复片段。
3. 重复直到 `012_REVIEW_PASS`。
4. 最终报告仍必须区分：离线 verified、真实 Provider E3 verified、未覆盖/延期能力。不得把 012 描述成已经接管整台 PC 的完整通用 Agent。

## 9. Expected repository artifacts

权威文档保持四份：`STRATEGY.md`、012 design、012 plan、本文。执行时可以新增非权威证据：

- `docs/implementation/012_EXECUTION_LOG.md`
- `docs/acceptance/012_TRUSTED_CONTINUITY_E3.md`
- 必要的 machine-readable, secret-free receipt/manifest

控制目录中的 prompt、stream、session ID、stderr 和 supervisor events 不进入产品 repo，也不作为 First Agent 产品 capability。
