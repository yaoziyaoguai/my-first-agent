---
title: 013 Everyday Workspace Agent - Claude Code Loop Handoff
type: implementation-handoff
date: 2026-08-03
authority: 013-loop-protocol
status: completed
---

# 013 Everyday Workspace Agent — Claude Code Loop Handoff

## 0. Current status（2026-08-03）

U0-U8 与 full gates 已全部闭合：

- strict-control 回执回放 blocker 已用 trusted SYSTEM 回执投影从架构上修复（design §7.2），
  `RESERVED_CONTROL_RECEIPT_NAME` 已彻底移除。
- 真实 E3 在官方 DeepSeek OpenAI-compatible strict beta endpoint 连续三次未插桩通过
  （12/12 claims、3/3 journeys；见 acceptance §7）；早先普通端点观察已声明取代，不作为证据。
- 第一轮 fresh review（session 78c54a88）输出 `013_REVIEW_FINDINGS`：F1 P2 verifier 会把仓库根
  `.codex-tmp-*` loop 临时文件收编进 overlay；F2 P3 scheduler 入口缺
  `strict_control_schema` composition 参数；F3 P3 PAUSED Goal 下普通问答被
  `active_goal_requires_control` repair 耗尽、effectful 边界未按暂停收口。三项均已
  Red → Green 闭合（design §7.3 与 `013_EXECUTION_LOG.md` review-fix 小节）；针对性
  `25 passed`、相关回归 `514 passed`、touched Ruff 与 diff check Green。
- Claude 在更新本文后触发周额度上限；Codex 已按既定 handoff 接手，重算 104-entry seal，并完整
  复跑六项门（源码与 materialized tree 均 `730 passed`）。
- fresh Standards reviewer 输出 `STANDARDS_REVIEW_PASS`（hard violation 0）；fresh Spec reviewer
  输出 `SPEC_REVIEW_PASS`（actionable P0/P1/P2 0）。013 的 reviewer gate 已闭合。

013 开发 loop 已达到 §7 终态；本文其余部分保留为可复现的执行与恢复协议。

## 1. 这是什么

这是 repo 外的开发执行协议，不是 First Agent 产品能力。Claude Code 只作为 coding executor：读取 013
合同、写 Red/Green、实现、运行 gates、修复失败并交给 fresh reviewer。禁止在产品中创建 CodingLoop、
supervisor、daemon 或第二套 Runtime。

用户要求优先使用已经配置好的 Claude Code，并允许它在本仓库内执行普通开发命令；不要读取或修改用户级
Claude 配置。Claude 因额度停止时，Codex 从同一 execution log 和 diff 直接接手，不等待、不重规划。

## 2. Execution envelope

- 工作目录：`/Users/jinkun.wang/work_space/my-first-agent`
- 当前分支：`main`；这是用户独自维护的仓库，不创建 feature branch/PR。
- permission：使用 Claude Code 已配置的最大项目权限。
- model/effort：使用用户当前 Claude Code 已保存的默认选择；启动 receipt 如实记录实际 model，不改 alias/settings。
- 允许把当前项目源码、测试和 013 文档发送给用户已配置的 Claude Provider。
- 不读取/输出 `.env`、secret/private/runtime、Claude memory/settings/auth、shell history。
- 不读取未跟踪 `tui/` 内容，不删除、覆盖、stage 它。
- 不 commit/push/tag/改 remote，除非用户之后明确授权。
- 真实产品 E3 只读协议规定的 `FIRST_AGENT_E3_*`；缺失时先闭合全部离线工作。

## 3. Executor authoritative inputs

按顺序完整读取：

1. `AGENTS.md`
2. `STRATEGY.md`
3. `docs/architecture/KERNEL_ARCHITECTURE.md`
4. `docs/architecture/EXTENSION_CONTRACTS.md`
5. `docs/architecture/012_TRUSTED_CONTINUITY_DESIGN.md`
6. `docs/architecture/013_EVERYDAY_WORKSPACE_AGENT_DESIGN.md`
7. `docs/plans/2026-08-03-001-feat-everyday-workspace-agent-plan.md`
8. `docs/acceptance/013_EVERYDAY_WORKSPACE_AGENT_E3.md`
9. 当前 `git status`、diff、materialized source/tests 和 `013_EXECUTION_LOG.md`

Graphify 只能提供线索；当前物化源码和权威合同优先。

## 4. Executor prompt

```text
你是 my-first-agent 的 013 Everyday Workspace Agent 主执行者。直接在当前 main 工作；用户给了当前仓库内普通文件、Bash、测试的最大权限，不要为可逆开发步骤停下来询问。不要 commit/push/tag/改 remote。

先完整读取 AGENTS.md、STRATEGY.md、KERNEL_ARCHITECTURE.md、EXTENSION_CONTRACTS.md、012 design、013 design、013 plan、013 E3 protocol、当前 git status/diff 和 docs/implementation/013_EXECUTION_LOG.md。不要读取未跟踪 tui/ 内容、.env、secret/private/runtime、Claude settings/auth/memory 或 shell history。

目标：顺序完成 013 U0-U9。用户一次 non-secret setup 后，在任意空或已有目录只运行 first-agent，就能自然语言提问、讨论或委托 bounded workspace file task；无需模式选择、复制 digest/request ID 或为阶段性进度输入“继续”。保持 012 的 durable Goal、最小澄清、精确审批、恢复和 evidence-backed VERIFIED_DONE。

绝对不变量：
1. AgentRuntime.run_turn 是唯一 production model/tool loop 和 checkpoint 初始化后的 state mutation owner。
2. ContextManager 独占上下文，ToolRuntime 独占 callable prepare/policy/invoke；Provider 只做 ContextPack -> ModelResponse。
3. 不创建 pre-runtime model classifier、第二 loop/Runtime、CodingLoop、supervisor、daemon、service locator、compatibility fallback 或 dormant feature flag。
4. 不增加 shell/web/browser/dynamic multi-root/ambient monitoring/self-improvement。
5. Provider profile 只存 non-secret metadata；credential value 只按 env name 在 composition root 注入。
6. CLI 的上下文式 yes/no 只翻译 exact pending typed action，不能自行执行工具或推进 Goal。
7. 保留用户未跟踪 tui/ runtime，不 reset/restore/clean/checkout 丢弃工作树。

工作方式：
- 每个行为/架构变化先写能证明缺口的 Red，记录命令与真实失败，再做最小 Green。
- 持续更新 docs/implementation/013_EXECUTION_LOG.md：unit、Red、Green、exit code、关键决定、changed files、remaining risk。
- focused Green 后自动进入下一 unit；不要把关键任务交给 background Agent 后结束。
- 失败先诊断并修复。timeout、截断、缺 exit code、单测复跑、fake/mock 和模型自报都不是 full pass。
- 只在真实合同冲突、明确缺少 E3 配置、真实 E3 服务失败或全部门完成时停止。

完成前运行未截断：
git diff --check
.venv/bin/ruff check .
.venv/bin/python -m pytest -q -rx
.venv/bin/python scripts/verify_013_materialized_tree.py --check-membership
.venv/bin/python scripts/verify_013_materialized_tree.py --content
.venv/bin/python scripts/verify_013_materialized_tree.py --control-seal

Stop protocol：
- U0-U7 和所有离线门 Green 后，真实配置是唯一缺口：只输出 NEEDS_013_E3_CONFIG(required=FIRST_AGENT_E3_PROVIDER,FIRST_AGENT_E3_BASE_URL,FIRST_AGENT_E3_MODEL,FIRST_AGENT_E3_API_KEY)。
- 真实 E3 bounded attempt 失败：只输出准确 013_E3_BLOCKED(reason=...)，并保存 secret-free receipt。两者都不是完成。
- U0-U9、真实 E3 和 full gates 全通过：输出 013_EXECUTOR_READY_FOR_REVIEW，并列证据路径；这只是交审。
- 其他情况继续工作，不得输出完成 marker。
```

## 5. 简单外部 loop

不搭建持久 supervisor。调用方只保存 Claude CLI 的 stream、exit code 和 session ID：

1. 启动一个 executor session。
2. 无合法 marker 正常退出：resume 同一 session，只让它读 execution log/diff/最后失败继续。
3. 429/quota/overloaded：立即由 Codex 从同一 execution log 接手；之后如再交回 Claude，使用准确 handoff，不并发修改。
4. context/session 损坏：新 executor 读取全部权威文档和 execution log，从第一个未闭合 gate 继续。
5. `013_EXECUTOR_READY_FOR_REVIEW`：启动 fresh reviewer，而非宣称完成。
6. reviewer findings：executor/Codex Red → Green 修复，再用 fresh reviewer 审完整树。

恢复 prompt：

```text
继续同一个 013 executor，不重新规划、不扩大范围。先读 013_EXECUTION_LOG.md、当前 git status/diff 和最后一个完整失败/gate，从第一个未闭合 Red/Green/exit gate 继续。阶段性 Green 不是停止点。继续遵守唯一 AgentRuntime.run_turn、no-secret profile、无第二 loop、无新能力、保留 tui/、不 commit/push。只有 013 handoff 定义的合法 marker 可以停止。
```

## 6. Fresh reviewer prompt

```text
你是 013 Everyday Workspace Agent 的 fresh correctness/security/architecture reviewer。不要相信 executor 的完成声明，第一次先只读审计。

完整读取 AGENTS.md、STRATEGY.md、012/013 designs、013 plan/E3、013 execution log、当前完整 diff、新增/修改测试、materialized manifests 和真实 E3 secret-free receipt。不得读取 .env、secret/private/runtime、Claude config 或未跟踪 tui/ 内容；不 commit/push。

主动构造失败场景：profile 存 secret、symlink/mode/partial write/unknown field、partial CLI/profile merge、无 profile 静默 fake、send-before-disclosure、yes/no 在错误状态被当控制、stale approval/recovery binding、multiple candidate 猜测、第二 model/runtime loop、阶段性继续、quiet output 隐藏安全决定、Goal-after-effect、false VERIFIED_DONE、restart 重复 effect、existing workspace 越界修改、mock 冒充 E3、截断 gate。

运行必要 focused tests 和全部未截断 gates。任何 correctness/security/architecture P0/P1/P2 输出 013_REVIEW_FINDINGS，包含文件/行、复现、期望/实际和修复标准，不得输出 pass。只有所有合同、真实 E3 claims 和 full gates 完整通过时输出 013_REVIEW_PASS，并列实际命令、exit code、receipt 和 residual caveats。
```

## 7. Final stop

只有 fresh `013_REVIEW_PASS` 能结束开发 loop。最终报告必须区分：013 已验证的日常 ask/discussion/local file
能力，与仍延期的 shell/web/browser/整机权限/自我优化。未经用户再次授权，不执行 commit/push。
