# 016 First Agent 1.0 — Fresh Independent Review

- reviewed_at: `2026-08-26`（Asia/Shanghai）
- status: `PASS`
- reviewer: Codex fresh U3 review context（非本轮 Claude Code executor）
- fixed_point: `96a1d770ad5e98b2faab325bf2aebdc76767ec5d`
- reviewed_subject: 当前未提交 worktree 与其 detached delivery evidence
- delivery_seal_sha256: `9b05e5523d2dafc4486b0f5394961e4846b5eacacb4e8aca400d59ca3bce612b`
- overlay_root_sha256: `3a58a16f540d034f236b91a2300959c5fcf24d60dbcae8ec92f3f7a5e932801d`
- verifier_sha256: `d9c13de5fb35a34c94362946ec66aa536eb7aa6135dce1e412edd84d8a3ce8a9`
- entry_count: `225`

本文件是 016 E3 §U3 要求的 detached independent review receipt。它不进入自己评审的 ordinary
materialized root，不复制 transcript、prompt、credential、绝对临时路径或用户内容。上一版 review
绑定旧的 216-entry identity，不能复用；本次从冻结合同和当前 evidence 重新判断。

## Review scope

本次独立核对：

- `docs/architecture/016_FIRST_AGENT_1_0_EXPERIENCE_DESIGN.md`
- `docs/acceptance/016_FIRST_AGENT_1_0_E3.md`
- `docs/plans/2026-08-20-001-first-agent-1-0-product-convergence-plan.md`
- `docs/plans/2026-08-26-001-deepen-evidence-closure-module-plan.md`
- `docs/plans/2026-08-26-002-architecture-deepening-program.md`
- 根与项目级 `AGENTS.md`
- `docs/architecture/KERNEL_ARCHITECTURE.md`
- `docs/architecture/EXTENSION_CONTRACTS.md`

审查覆盖冻结产品合同、当前 diff、完整 gate 证据、真实三连 receipt、架构 owner、巨石文件裁决、
secret/runtime denylist 与公开声明。reviewer 未继承 executor 的 PASS 结论。

## Evidence checked

### U0 / U1 / materialized delivery

- official runner 的 source full：`1503 passed in 196.23s`，exit 0。
- 同一 invocation 的 sealed materialized clean-room：`1503 passed in 192.49s`，
  `ALL CHECKS PASSED`，exit 0。
- reviewer fresh 复跑 `git diff --check` 与全树 `ruff check .`：Green。
- reviewer fresh 复跑 overlay membership：`225 exact entries`；control seal：Green。
- tracked diff 无 `tui/` 路径；diff-only credential pattern 检查无命中。reviewer 未读取 `.env`、
  secret、private、runtime 或 `tui/` 内容。

### U2

- detached receipt schema：`first-agent-016-e3-receipt-v2`。
- receipt 的 seal、overlay、verifier 与当前 delivery identity 逐字一致。
- 三个独立 installed wheel digest：`2f2393ab…`、`9b5d7ab2…`、`a282a3d4…`。
- 三轮均为 `12` journeys、`25` claims；journey、claim、UX、workspace 与 recovery verdict
  全部为 `true`。
- 三轮 model send attempts 为 `61/61/73`，Web send attempts 为 `13/10/11`，file effects
  为 `8/8/11`，process receipts 为 `3/3/3`；计数并非用模型自报替代。
- reviewer fresh 复跑 `verify_016_materialized_tree.py --attestation`：
  `3 x 12 journeys + 25 true claims`，exit 0。
- 真实 runner 终态：`016_E3_REAL_PASS attempts=3`。receipt 只来自当前 root 的完整三连。

### Architecture and mega-module review

- production model call 仍只有 `AgentRuntime` 中的一处 `provider.generate`；production tool call
  仍只有同一 Runtime 中的一处 `ToolRuntime.invoke`。
- evidence closure 迁移只把缺口、可修工具与修复指引的纯派生知识收进
  `ClosedEvidenceRegistry`；provider/tool/CAS/state ownership 未移动。
- `CitationGovernance` 与 `SourceGovernance` 是 `KernelToolRuntime` 内部的 typed governance
  knowledge；它们不能自行调用 capability、批准 effect 或推进 state，最终 gate 仍由
  `KernelToolRuntime.prepare/invoke` 独占。
- 共享 POSIX process-group seam 只拥有 verified PGID、TERM→KILL 与 bounded liveness；
  local-process draft 和 SubAgent receipt taxonomy 仍由各 caller 拥有，无法确认时 fail closed。
- scheduler 只修正 `ExitStack` 注册方向，使 closeables 按构造逆序关闭；没有引入 assembly
  service locator 或第二套 composition。
- 巨石文件按 cohesion、information hiding 与 deletion test 判断，而非按行数机械拆分。
  `checkpoint.py` codec 是下一轮可研究的 bounded candidate，不是本轮交付缺口。
- README、STRATEGY 与 capability status 的 016 声明保持 local-first、bounded、fail-closed；
  没有扩写为 production-ready、浏览器自动化、整机控制、后台 daemon、自主改写或并行 worker。

## Findings and closure

本轮独立 review 没有发现未闭合的 P0/P1/P2 promotion blocker。旧 independent review 虽为 PASS，
但绑定的是上一版 identity；本文件已用当前 225-entry identity 的 fresh evidence 取代它，而不是把旧
verdict 平移到新代码。

两个架构计划的实现与拒绝项均有 deletion-test 理由、行为回归和当前 root 的 source/materialized/real
E3 证据。未发现 missing/partial requirement、scope creep、第二 loop、authority/effect gate 漂移或
错误的交付声明。

## Verdict

**PASS — U0、U1、U2 与 fresh U3 已在同一 delivery identity 上闭合。该 identity 晋级为
`accepted/delivered` 的 First Agent 1.0 bounded reference delivery。**

此 verdict 只覆盖冻结的 016 范围：local-first 当前目录入口、聊天/澄清/durable Goal、当前 workspace
文件与 First Agent 自有历史、经逐次批准的固定 Tavily 公开 Web，以及经 exact approval 的结构化本机
程序执行和可恢复连续性。它不表示 production-ready，也不包含 authenticated browser、任意 shell、
整机接管、后台常驻、自主改写自身、并行 worker 或第二套 Agent loop。

本审查未 commit、push、tag 或修改 remote。
