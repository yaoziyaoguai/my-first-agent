# 016 First Agent 1.0 — Fresh Independent Review

- reviewed_at: `2026-08-26`（Asia/Shanghai）
- status: `PASS`
- reviewer: Codex fresh U3 review context（非 016 executor）
- fixed_point: `b9b3593c5c55491e746332409bf27a45a7da78c6`
- reviewed_subject: 当前未提交 worktree 与其 detached delivery evidence
- delivery_seal_sha256: `80d23e4b3a8cf00a88b08ffc943d0fc7067f55a6bfc4762bdb7cedb7644b8f3a`
- overlay_root_sha256: `25e8109724caa41ca726a3b6be9a6368d2627645a26516a8b55ba50f582fd9c2`
- verifier_sha256: `d9c13de5fb35a34c94362946ec66aa536eb7aa6135dce1e412edd84d8a3ce8a9`
- entry_count: `216`

本文件是 016 E3 §U3 要求的 detached independent review receipt。它不进入自己评审的 ordinary
materialized root，不复制 transcript、prompt、credential、绝对临时路径或用户内容。

## Review scope

本次从冻结的以下合同重新核对当前实现与证据，不继承 executor 的通过结论：

- `docs/architecture/016_FIRST_AGENT_1_0_EXPERIENCE_DESIGN.md`
- `docs/acceptance/016_FIRST_AGENT_1_0_E3.md`
- `docs/plans/2026-08-20-001-first-agent-1-0-product-convergence-plan.md`
- 根与项目级 `AGENTS.md`
- `docs/architecture/KERNEL_ARCHITECTURE.md`
- `docs/architecture/EXTENSION_CONTRACTS.md`

审查分为相互独立的 Spec 与 Standards/architecture 两轴。Spec 轴检查遗漏、部分实现、scope creep 与
实现偏离；Standards 轴检查项目规则、唯一 owner、effect/authority、证据诚实性和 materialized 边界。

## Evidence checked

### U0 / U1

- 冻结 design、E3 与 execution plan 均存在，promotion rule 一致。
- official runner 的 source full：`1463 passed`，exit 0。
- sealed materialized clean-room：`1463 passed`，`ALL CHECKS PASSED`，exit 0。
- `ruff check .`、`git diff --check`：Green。
- overlay membership：`216 exact entries`；control seal：Green。
- tracked diff 不包含 `tui/`；常见 credential pattern 的 diff-only 检查无命中。reviewer 未读取
  `.env`、secret、private、runtime 或 `tui/` 内容。

### U2

- detached receipt schema：`first-agent-016-e3-receipt-v2`。
- receipt 的 seal、overlay、verifier 与当前 delivery identity 逐字一致。
- 三个独立 installed wheel digest：`1b328e28…`、`04cbd1e1…`、`32932c30…`。
- 三轮均为 `12` journeys、`25` claims；journey、claim、UX、workspace 与 recovery verdict 全部为
  `true`。
- `verify_016_materialized_tree.py --attestation`：
  `3 x 12 journeys + 25 true claims`，exit 0。
- 真实 runner 终态：`016_E3_REAL_PASS attempts=3`。此前两次不同签名的模型方差失败被 fail-closed
  记录，未冒充成功；当前 receipt 只来自最终完整三连。

### Architecture and product claims

- production model call 仍只有 `AgentRuntime` 中的一处 `provider.generate`。
- production tool call 仍只有同一 Runtime 中的一处 `ToolRuntime.invoke`。
- `ContextManager` 仍独占 `ContextSource.snapshot` 收集；CLI/headless/provider adapter 未形成第二套
  state/tool loop。
- README、STRATEGY 与 capability status 的声明保持 local-first、bounded、fail-closed；没有把 016
  扩写为浏览器自动化、整机控制、后台 daemon、自主改写或 production-ready。

## Findings and closure

Spec 轴最终结论为 PASS，无 missing/partial requirement、scope creep 或实现偏离 blocker。

Standards 轴最初发现一处证据文字错误：execution log 把当前 `max_invalid_repairs` 写成 `1`，而 sealed
product 与冻结测试均为 `8`。executor 只更正该 detached 日志为 `8`，并准确说明第 9 次连续无效 wire
response fail closed；复核后 finding 已关闭。该更正没有改变 ordinary root，membership、control-seal、
attestation 与 diff-check 复跑仍全部 Green。

最终两轴均无 P0/P1/P2 promotion blocker，无遗留 judgement-call finding。

## Verdict

**PASS — U0、U1、U2 与 fresh U3 已在同一 delivery identity 上闭合。该 identity 晋级为
`accepted/delivered` 的 First Agent 1.0 bounded reference delivery。**

此 verdict 只覆盖冻结的 016 范围：local-first 当前目录入口、聊天/澄清/durable Goal、当前 workspace
文件与 First Agent 自有历史、经逐次批准的固定 Tavily 公开 Web，以及经 exact approval 的结构化本机
程序执行和可恢复连续性。它不表示 production-ready，也不包含 authenticated browser、任意 shell、整机
接管、后台常驻、自主改写自身、并行 worker 或第二套 Agent loop。

本审查未 commit、push、tag 或修改 remote。
