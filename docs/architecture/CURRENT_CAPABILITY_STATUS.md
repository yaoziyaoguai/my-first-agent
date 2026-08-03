# Current Capability Status

本文件是当前能力声明的最小权威入口。
架构边界由 `KERNEL_ARCHITECTURE.md`、`EXTENSION_CONTRACTS.md` 与各 capability design 定义；当前 closure 证据见 `docs/audits/2026-07-20-capability-evidence-closure-audit.md`，实施合同见 `docs/plans/2026-07-20-009-close-capability-evidence-gaps-plan.md`。

008 plan/log/manifest 保留为历史，但不再是完成或晋级依据。

## Claim levels

| Level | Meaning | Required evidence |
|---|---|---|
| designed | 稳定边界和非目标已写清 | reviewed design + executable plan |
| implemented-candidate | 当前工作树有实现与局部自动证据 | source + E0/E1；不证明跨边界或 Git delivery |
| locally-verified | fault matrix、production boundary journey、clean materialized-tree gate 与独立 promotion review 通过 | E1 + E2 + E2M + independent review receipt |
| accepted | 用户批准的 reference task 完成并可核对价值与限制 | locally-verified + independent E3 record |

`safe-unavailable` 不是 claim level。
它表示 capability 的 fail-closed boundary 可以被验证，但当前没有可用的生产 adapter/provider。
G8 之前 SubAgent 属于这种限制（HTTP adapter 无 honest hard-deadline）。G8/G8.1 引入进程隔离
`ChildProcessRunner`（parent 拥有 process group、killpg+exit-confirm、`process_terminated` receipt）
并经独立 G8 复核（stderr/temp/stdout-bound 闭合）后，SubAgent 已有真实 hard-deadline provider 路径，
不再 safe-unavailable，已晋级 `locally-verified`（真实 HTTP provider in child 仍为 E3，pending）。

## Current matrix

| Capability | Current claim | Trusted evidence | Blocking closure | Permitted wording |
|---|---|---|---|---|
| Minimal Runtime Kernel | accepted | unique loop/ContextManager/ToolRuntime owners；kernel effect-ordering/recovery/CAS/limits/event fault matrix；materialized `--content` gate 通过；独立 G0–G7 promotion review 完成 | v1 scope only（非 production-ready / 非完整通用 Agent） | minimal foundation；v1 reference task accepted（2026-07-25 独立 review）；非 production-ready、非任意 provider/MCP/Skill 语义 |
| MCP | accepted | governed registration/session seam；spawn 前 executable/ancestor/cwd identity+digest 复验；bounded transport + 持续 stderr drain；execution receipt + unknown-outcome + process-group cleanup + durable safety latch matrix（G2）；materialized gate + 独立 review 通过 | v1 scope only（仅 operator-trusted repo-owned benign stdio fixture） | governed stdio MCP seam；identity/transport closure done；v1 reference task accepted；不等于任意第三方/网络 MCP server |
| Memory | accepted | ContextSource/store/tool seam；strict no-coercion durable load + identity-safe owner-only bounded read + revision CAS；bounded lexical ranking（G3）；materialized gate + 独立 review 通过 | v1 scope only（owner-only 词汇召回，非语义/向量化） | governed Memory seam；strict store closure done；owner-only plaintext；v1 reference task accepted；非语义 Memory、非跨 owner 共享 |
| SubAgent | accepted | 同一 `AgentRuntime` child seam；G8.1 进程隔离 hard-deadline 路径（`ChildProcessRunner`：parent 拥有 process group、killpg+exit-confirm、`process_terminated` receipt；stderr DEVNULL deadlock-safe、per-run temp 目录 rmdir 清理、stdout 有界 overflow→UNCONFIRMED；TERMINATED/UNCONFIRMED 经确定性故障注入证明，UNCONFIRMED 覆盖 normalization→parent recovery）；同步 receipt 路径（`ChildAgentRunner`）保留给声明 synchronous `deadline_contract` 的 provider；materialized gate + 独立 G8 review 通过 | v1 scope only（bounded 单 child，非并发） | bounded child seam + 真实 hard-deadline provider 路径（HTTP adapter 经进程隔离可用）；E2 正向（process-isolated fake provider 经真实进程边界）已证；v1 reference task accepted（真实 HTTP provider in child）；非并发 SubAgent、非任意 child provider |
| Scheduler | accepted | external caller；calendar-valid UTC occurrence identity；conversation_busy + checkpoint_conflict 同一 one-shot reconciliation；needs-human→CLI/TUI 解决→duplicate 报告 authoritative terminal（G5）；materialized gate + 独立 review 通过 | v1 scope only（external caller replay，非 CRUD/持久调度策略） | deterministic external caller；fault matrix closed；v1 reference task accepted；非 Scheduler CRUD、非持久化调度 |
| Skill | accepted | strict frontmatter/read-only governed tools；body+resource+ancestor identity/digest revalidation（同一 opened fd）；bounded metadata disclosure（G1）；materialized gate + 独立 review 通过 | v1 scope only（operator-approved read-only skill） | governed read-only Skill seam；identity/drift closure done；v1 reference task accepted；不等于任意/远程/可执行 Skill |
| TUI | accepted | Textual optional adapter；纯键盘 submit/approve/reject/recovery 成功+失败/resume/cancel、authoritative reopen（零 provider/tool call）、shared event sink/lifecycle、event-fault advisory oracle（R19/R20 + N2 + G6 recovery s/f）；materialized gate + 独立 review 通过 | v1 scope only（单平台键盘 adapter） | 全键盘 adapter；fault matrix closed；v1 reference task accepted；CLI parity 已证；非跨平台/并发会话已验证 |

七项 capability 均已 `accepted`（v1 reference task，2026-07-25 经非实现 session 独立 review 晋级；receipt 见 `docs/acceptance/2026-07-25-E3_INDEPENDENT_REVIEW.md`）。
`accepted` 仅对各自 v1 reference task 的 bounded 任务成立：不是 production-ready，不等于任意 MCP/Skill、语义 Memory、并发 SubAgent、Scheduler CRUD 或跨平台已验证。

009 ordinary candidate 已由独立 reviewer 复核并封存（见 `docs/implementation/009_INDEPENDENT_REVIEW.md`）。
G0 已闭合两个 P2 residual：delivery 的 console-entrypoint origin 断言（N1，`assert_console_entrypoint_origin`
显式验证 `first-agent`/`first-agent-schedule` 来自 non-editable 安装）与 TUI 的 event loss/duplicate/reorder
注入 oracle（N2，证明 advisory 事件不改变 authoritative checkpoint/控制）。
G1–G6 随后闭合了五项 extension capability 的完整 fault matrix（Skill/MCP/Memory/Scheduler/TUI）。
G8 为 SubAgent 引入进程隔离 hard-deadline 路径（`ChildProcessRunner`），使 production HTTP provider
经进程边界获得 honest hard deadline（不再 safe-unavailable）。G8.1 修复了独立复审提出的 stderr
不 drain（F-G8-1，改 DEVNULL）与 temp 目录泄漏（F-G8-2，rmdir 清理）并加 stdout 有界。当前工作树的
materialized `--content` gate 通过（357 passed，未截断，deny-network 边界内）。

G0–G6 fault matrix 与 G7 materialized delivery 已由非实现 executor session 的独立 promotion
reviewer 复核（见 `docs/implementation/009_G0_G7_PROMOTION_REVIEW.md`）。reviewer 在写 controls
前亲自重跑 materialized `--content` gate（347 passed，未截断，deny-network 边界内）、
`--check-membership`、`--control-seal`、`git diff --check` 与 ruff，全部通过；并独立核对了
runtime ownership、exact manifest admission 与各 capability 关键 oracle test body。

据此，Minimal Runtime Kernel、MCP、Memory、Scheduler、Skill、TUI 六项已满足 E1/E2/E2M + 独立
review，晋级为 `locally-verified`（residual limitation 见上表）。G8/G8.1 对 SubAgent 的进程隔离
hard-deadline 路径（`agent/subagent/*`）与 `main.py` 的 subagent 组合路由只触及 SubAgent，未改动
六项已晋级 capability 的代码与 fault-matrix 证据。G8.1 之后的独立 promotion reviewer 已重跑
materialized `--content` gate（357 passed，未截断，deny-network 边界内）、`--check-membership`、
`--control-seal`、`git diff --check` 与 ruff，全部通过；独立核对了 F-G8-1/F-G8-2 修复、stderr_chars
未泄入 HTTP 产品行为、单 loop 与架构约束未削弱。SubAgent 经此复核晋级为 `locally-verified`
（真实 HTTP provider in child 为 E3，pending）。E3 reference task 全部 pending，故没有 `accepted`。
历史 286-test dirty-worktree result 与 008 membership gate 仍不能作为晋级依据。

## E3 reference tasks (2026-07-25)

用户授权的真实 provider E3 已在本隔离副本执行：provider `anthropic_compatible`，
base URL `https://open.bigmodel.cn/api/anthropic`，model code `glm-5.2`（approved
`glm-5.2[1M]` 的 `[1M]` 为上下文窗口标注，非 API model code；endpoint 回显 `glm-5.2`），
credential env `ANTHROPIC_AUTH_TOKEN`，timeout ≤120s。七项 capability 的 reference task
均经正常产品入口（`first-agent` / `first-agent-schedule` / TUI Pilot）与真实 provider
完成，结果与 bounded 证据见 `docs/acceptance/records/2026-07-25-*.md`：

- Kernel: pass（多轮对话、上下文预算、read_file 自动放行、write_file 经审批写入、reject 不产生 effect、checkpoint terminal/counts 可核对）
- Skill: pass（无 skill baseline 对照；governed activation + resource-read 应用 baseline 不具备的合成规则；scripts/URL 不执行）
- MCP: pass（repo-owned benign stdio fixture 单次可数 effect；preview→approval→EXECUTING→result；durable latch 干净清空；重复 action 不增 effect）
- Memory: pass（conv A 经 governed remember → 独立 conv B 同 workspace/profile 召回并应用；baseline 不知；无关 query 不召回）
- SubAgent: pass（真实 HTTP provider in child 经进程隔离 hard-deadline；parent-direct vs parent+child；child 一次 model call、无工具/Memory/workspace；可核对增量）
- Scheduler: pass（external caller fire → needs_human → 正常 CLI resolution → duplicate replay 不增 provider/effect）
- TUI: pass（键盘 submit→approve→terminal；durable pending 重开零 provider 调用；TUI 与 CLI action digest 等价）

E3 暴露并修复一个产品 bug：`main.py` 的 `--mcp-safety-state` 路径原用
`resolve(strict=True)`，但 `McpSafetyLatch` 设计为“文件缺失即 clear”、首次 invocation
才惰性创建——故任何首次 CLI 使用 MCP 都会 `FileNotFoundError` 启动失败。Named Red
`tests/mcp/test_integration.py::test_main_composes_mcp_when_safety_latch_not_yet_created`
复现并验证最小 Green（改为 `resolve(strict=False)`，与 memory store 一致）。

按 promotion rule，晋级 `accepted` 需非实现 session 的独立 review：executor 不自封 `accepted`，
七项 claim 维持 `locally-verified`（E3 evidence 现已存在，待独立 review 晋级）。本节 claim 更新使
`CURRENT_CAPABILITY_STATUS.md` 内容超出 u8 封存 digest，`--control-seal` 因此处于 pending-reviewer
（digest drift），executor 未自行 re-seal、未伪造 reviewer receipt；membership 与 materialized
`--content` gate 仍绿。

2026-07-25 独立 review（非实现 session，GLM 5.2[1M]、effort=max）已通过并晋级七项 capability 为
`accepted`（v1 reference task）。reviewer 亲自执行：provider adapter smoke（真实 `glm-5.2` 经产品入口
返回可核对答案，非 fake/echo）、MCP 首次 `--mcp-safety-state` `strict=True`→`strict=False` 的 Red/Green
（named test PASS + resolve 语义复现 + latch owner/mode/no-follow 安全独立于 composition resolve）、
SubAgent 真实 HTTP provider 经 `getattr(deadline_contract)` 路由到进程隔离 `ChildProcessRunner`（非
in-process）、Memory 跨会话召回、Scheduler duplicate replay 不增 effect、TUI Pilot 键盘路径（`press`
而非内部 API）的结构性核验；并重跑 `git diff --check`、ruff、全量 pytest（375，普通 + warnings-as-errors
零 warning）、`--check-membership`（954）、materialized `--content` gate（deny-network，ALL PASSED）、
`--control-seal`，全部真实 exit 0、无截断。receipt：`docs/acceptance/2026-07-25-E3_INDEPENDENT_REVIEW.md`。
独立 reviewer 已 re-seal 本文件 control digest（`seal_state=sealed-u8`，gate 要求值），未改动其他历史
control file；并清理了 executor E3 遗留的两个孤儿 sleeper 进程（mktemp 外部、无 secret/网络/repo 文件）。

## Active freeze

009 candidate 已封存；七项 capability 已经独立 review 晋级 `accepted`（v1 reference task）。以下保守约束持续生效，避免在 v1 scope 之外被误读为 production-ready：

- 不增加新的 product capability。
- 不扩展六项 v1 scope。
- 不恢复旧 Memory/Skill/MCP/SubAgent/Scheduler/TUI implementation。
- 不把 Graphify、Understand Anything 或其产物纳入产品 Runtime/manifest。

允许的工作：行为/fault tests、delivery verification、truth claims 同步与（用户另行授权的）真实 E3。
真实 E3 仅在用户显式提供 provider 配置后运行。

## Promotion rule

每项 capability 独立晋级：

1. Named Red 对目标 observable behavior 准确失败。
2. 同一 oracle Green，且 production boundary journey/fault matrix 通过。
3. 从 009 exact manifest materialize、non-editable install 后重现相关 gates。
4. `CURRENT_CAPABILITY_STATUS.md` 明确 residual limitation。
5. 用户另行授权并完成 E3 reference task。

完成 1-4 并由非实现 agent/session 审查 exact manifest、关键 test oracle，且在写 controls 前亲自重跑 materialized content gate 后，才可标 `locally-verified`；完成 1-5 才可标 `accepted`。
安全拒绝、FakeProvider scripted answer、submit-only Pilot 或总 test count 都不能跳过步骤。
