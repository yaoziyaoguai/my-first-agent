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
并经独立 G8 复核（stderr/temp/stdout-bound 闭合）后，SubAgent 获得真实 hard-deadline provider 路径，
不再 safe-unavailable。以下均为历史演进事实，仅绑定当时 identity：SubAgent 在 G8/G8.1 复核后达到
`locally-verified`，随后 2026-07-25 完成真实 HTTP provider in child 的 E3 并经独立 review 晋级
`accepted`。当前工作树的唯一有效 claim 见下方 Current snapshot。

## Current snapshot (2026-10-16)

本节是唯一权威 current matrix；下方 Historical matrix 与时间线只作历史证据保留。所有 current claim
均相对当前工作树这一 identity：当前工作树相对 016/017/018/019 的旧 seal/check 全部 drift（016
manifest 期望 225、实际 508 entries；018 期望 309、实际 495；019 entry_count/root drift），
fail-closed 校验正常工作，因此没有任何 `locally-verified` / `accepted` / `delivered` 相对当前
identity 成立——各能力保持 `implemented-candidate`。2026-09-09 r18 曾冻结为学习里程碑；r19 产品化
审计（2026-09-09）解除该冻结后，2026-10 可靠性收口在当前 identity 上补齐三层证据：完整测试门 G1
（3873 passed / 1 skipped / 0 failed，exit 0，确认性重跑；唯一 skip 为设计内 launchd host gate）、
安装层 I1（wheel→install→installed 41 节点 exit 0、origin 153/153 安装态、两条污染负对照通过；仅覆盖
本机 macOS 单一组合，未声明跨平台安装 matrix）、真实模型层 E1（deepseek-v4-flash，thinking
disabled，授权预算 61/80 请求：E1-B 运行中追加纠正→暂停→新进程恢复旅程 typed VERIFIED_DONE 全链
PASS；E1-A 业务判据全过但 40 请求窗口耗尽于终态前，产品停在安全暂停未谎报完成）。这些是当前
identity 上的验证事实，不是 promotion，也不改变任何历史 seal 的绑定范围。

## r18 closure record (2026-09-09, 普通实施记录，非 acceptance control)

依据 Oracle r18 咨询（session `first-agent-r18-project-closure-packet-20260909`，档位 Pro 第 5 项，
裁决 PROCEED-then-freeze）执行的一次本地收尾，不改变任何 promotion 状态：

- C1（commit `684f368`，tree `10d36564`）合并 finish-long-session rounds 004–017 的未提交实现与
  测试，并新增三项收尾：multi-hop gitdir symlink 行为以 characterize 测试固定为已声明 limitation
  （`tests/sandbox/test_policy.py`）；工具输出截断事实在模型可见 ToolResult content 中显式标注
  （`agent/runtime/tools.py::_render_model_visible_output`，receipt/metadata 原有事实不变）；补齐
  019 wheel-bound pytest 父进程驱动 `run_wheel_bound_pytest`（此前测试已定义合同但实现缺失，
  首轮 gate 4 failed 均为此根因）。
- `/compact`、`/context`、`/new` CLI 命令在母计划 Outcome 中出现，但截至冻结未实现
  （`agent/cli/app.py` 无对应命令，typed `CompactConversation` action 不存在）；自动压缩经
  Runtime 安全边界生效。README 能力列表只声称已核对代码的真实实现。
  **r19 后续（2026-09-10，产品化小步 2）**：`/new` 已实现——CLI 与 TUI 共享
  `new_session_gate` 合法性判断（active run/pending 决策/活跃 Goal 拒绝；终态或无 Goal
  允许），以 `NEW_SESSION_REQUESTED` 信令在同一进程内经 `open_workspace_session(force_new=True)`
  重建 conversation，旧 checkpoint 与 evidence 原样保留；`/compact`、`/context` 仍未实现。
  **r19 后续（2026-09-10，产品化小步 3）**：anthropic_compatible adapter 改为 SSE 流式
  （`ModelDeltaObserver` 窄观察合同，`MODEL_TEXT_DELTA` advisory 事件直写 EventSink 绕过
  invocation 缓冲）；最终响应仍由流结束后的完整重建走唯一 normalize 路径，断流不铸造响应、
  不自动补发，tool_use partial JSON 只在流收束后解析；含既有 thinking-block 丢弃合同。
  CLI 实时增量显示（与最终 message 完全一致时不重复打印）；TUI 周期 drain 显示。
  不含即时取消/工具抢占/后台化。受管 E3 脚本（013/014/015/018/019）的 provider 包装
  签名随产品合同同步。
  **r19 后续（2026-09-13，编码自主性候选）**：精确 DeepSeek Flash 官方入口现支持
  `thinking=enabled` + `reasoning_effort=max` 的 SSE 路径。opaque `reasoning_content` 与
  provider identity 绑定后 checkpoint/replay，不进入 UI、Memory 或 compaction summary；断流
  不铸造响应且不自动重发。受当前 invocation 绑定的取消可在 SSE 读取边界协作
  停止，最终状态仍只由 `AgentRuntime` 落盘。2026-09-14 增加精确 provider capacity 档案：
  官方 Flash identity 使用 1M context window 与 384K output 上限，并联动有界 SSE 字节预算；
  未知兼容 endpoint 不继承。真实 D01 CSV 修复在 13 次 model attempt 内自主完成，产品测试和
  workspace 外 grader 均 PASS；该单场景证据不改变 capability promotion 状态。
- 后续重开条件（用户明确授权才生效）：现有支持范围内出现可复现的合同缺陷，或出现能回答新学习
  问题的具体 reference task。（2026-09-09 晚用户确认产品化转向，冻结约束由 r19 审计解除；
  小步 1 基线见 `docs/audits/2026-09-10-product-baseline-tasks.md`。）

| Capability | Current claim (2026-09-09) | Historical evidence（只绑定当时 identity） | 可用条件 / 未验证边界 |
|---|---|---|---|
| Minimal Runtime Kernel（current-directory foundation：对话、上下文、审批、文件 effect、checkpoint/暂停恢复、Web、owner preference） | implemented-candidate | G0–G8 fault matrix 与独立 promotion review；2026-07-25 v1 reference task 晋级 `accepted` | v1 scope；非 production-ready / 非完整通用 Agent；claim 不随 identity 变更复用 |
| 015 governed local action（`local_process`） | implemented-candidate | 真实 DeepSeek E3 三连 + 独立评审 + Codex 终裁（当时 delivery identity） | POSIX/macOS-first 冻结合同；非任意 shell / 整机控制 |
| 016 product convergence（First Agent 1.0 安装/setup/默认路径） | implemented-candidate（promotion candidate） | detached 016 review 曾对当时 identity 记录 U3 PASS | U0/U1/U2/U3 需对当前 identity 重新绑定后才可能晋级；本轮未执行 |
| 017 macOS Seatbelt sandbox（`sandbox_exec`） | implemented-candidate | detached 017 review 曾对当时 sealed identity 记录 PASS（3×11 journey 全 true） | 仅 macOS Seatbelt；非跨平台 sandbox；当前 identity 未复核 |
| 018 governed browser（专属隔离 Chromium） | implemented-candidate | detached 018 review 曾对当时 identity 记录 PASS（3×13 receipt） | 非个人 Chrome / 桌面控制 / 任意网站兼容 / production-ready 第三方集成；`browser_act.fields` 为开放 object，与 `--strict-tools` 组合 fail closed |
| 019 portable control core | implemented-candidate | detached 019 core review 曾对当时 identity 两轴 PASS | portable 协议闭合 ≠ 任一 OS 可运行无人值守调度；旧 seal entry_count/root 已 drift |
| 019 macOS host profile | implemented-candidate | 曾对当时 identity 完成真实 persistence / launchd wake / hard-deadline cleanup / 017 composition / U2B qualification | Linux / Windows / cloud 保持 `not_qualified`，不得从 macOS 证据外推 |
| Memory | implemented-candidate | 2026-07-25 v1 reference task 晋级 `accepted` | owner-only 明文词汇召回；非语义 Memory、非跨 owner 共享 |
| MCP | implemented-candidate | 2026-07-25 v1 reference task 晋级 `accepted` | 仅 operator-trusted repo-owned benign stdio fixture；server descriptor schema 含开放 object 时与 `--strict-tools` 组合 fail closed |
| Skill（read-only governed tools） | implemented-candidate | 2026-07-25 read-only reference task 晋级 `accepted` | 非任意 / 远程 Skill、无 lifecycle / 第二套 loop |
| Skill（declared entrypoint 执行路径） | implemented-candidate | 无（自 009 起即 candidate，从未晋级） | 仅 owner-local Python entrypoint、network off、observation result；`arguments` 为开放 object，与 `--strict-tools` 组合 fail closed |
| SubAgent | implemented-candidate | 2026-07-25 v1 reference task 晋级 `accepted`（进程隔离 hard-deadline 路径，真实 HTTP provider in child） | bounded 单 child、非并发；进程边界终止 ≠ 远端服务端撤销推理 |
| TUI | implemented-candidate | 2026-07-25 v1 reference task 晋级 `accepted` | browser takeover 与 terminal follow-up controls 自始为 candidate |
| Scheduler | implemented-candidate | 2026-07-25 v1 reference task 晋级 `accepted` | external caller one-shot replay；非 Scheduler CRUD / 持久调度策略 |

## 016 product convergence status

016 的状态由同一 delivery identity 的证据 fail-closed 派生。它不新增底层能力，而是把 012—015 已有的
对话、workspace/history、公开 Web、文件 effect、本机程序执行和可信连续性收束成可安装、可 guided setup、
无参数启动、可读暂停/恢复的一条默认产品路径。

已实现的 candidate 边界包括：distribution metadata `1.0.0` 与 installed `--version`、guided provider/Web
setup、Web 三态本地降级、可读 startup、安全 process notice，以及连续 16 次 semantic no-progress 后保留
active Goal 的可恢复暂停。某个 delivery identity 是否完成 deterministic U1、materialized tree 与真实
Model + Tavily 十二旅程连续三轮 U2，只能由同一 seal identity 的 receipt 和 fail-closed attestation 判定；
旧 identity 的三连不能随 ordinary source 变化复用，本状态页不单独缓存该结论。

U3 的 authoritative 状态只由 detached `docs/acceptance/016_FIRST_AGENT_1_0_INDEPENDENT_REVIEW.md` 记录。
该文件只有在绑定当前 delivery identity、核对 U0/U1/U2 并明确写明 PASS 时，才把 016 晋级为
`accepted/delivered`；文件缺失、pending、FAIL 或 identity 不匹配时，状态保持 `implemented-candidate`。
真实 U2 证据不能由 Fake/scripted/reference test 或旧 identity receipt 替代。完整边界见
`016_FIRST_AGENT_1_0_EXPERIENCE_DESIGN.md` 与
`docs/acceptance/016_FIRST_AGENT_1_0_E3.md`。

## 017 native sandbox status

017 只扩展受治理的结构化本机执行，不新增 model/tool loop owner。唯一 `sandbox_exec` 继续经过
`KernelToolRuntime` 的 policy/approval、`EXECUTING` checkpoint、one-shot authority lease 与 durable result；
`read-only` / `workspace-write` 由 macOS Seatbelt confined，backend 不可用时零执行且无 `local_process`
fallback。`danger-full-access` 仅在 exact approval 后作为 unconfined bypass，并在 receipt 中明确记录
`backend=none / enforcement=unconfined`。

已交付的 017 sealed identity 曾通过 source gates、clean materialized deny-network gate（3 个需要建立本地
listener 的 closed loopback controls 在同一 clean interpreter 下单独执行）和三次真实 Seatbelt E3，每次
11 条 journey 全部为 true。当前 working tree 的 Round 013 已补齐默认 composition 的 host-home
private-root 输入：`sandbox_exec` 与 `shell_exec` 共用一份 closed、模型不可修改的拒读集合，路径不存在时仍进入
policy identity；真实测试只使用 fake home/sentinel。Round 014 进一步删除 executor 的第二份 raw PATH authority：
普通 sandbox child 只消费 approval identity 已绑定的 sanitized `prepared.child_path`，structured I/O 仍显式使用
空 PATH。Round 015 又把经 bounded parser 验证的普通 `.git` gitfile pointer 与 resolved target 一起纳入既有
可读禁写 metadata policy；真实 Darwin probe 已证明 pointer 覆盖、替换、删除及 writable-workspace 内 target 写入
都被 Seatbelt 拒绝且 bytes 不变，同时 genuine linked worktree 的读取与 `git status` 仍可用。Round 016 进一步
修复共享 foreground runner 将 stdout/stderr 双 EOF 误作 direct child 已退出的生命周期缺口：关闭输出后仍在批准
deadline 内工作的同一 child 现在可自然完成；双 EOF 后的真实 timeout 仍走既有 TERM→KILL/group proof，select/read
采集失败则经既有 `ProcessCleanupError` 进入 unknown recovery，不再铸造正常空结果。这些改动会改变
source identity，在新的 detached seal/E3/independent review 绑定完成前，当前 tree 只能
视为 `implemented-candidate`，不能复用旧 delivery claim。

最终 claim 仍由 detached `docs/acceptance/017_SANDBOXED_WORKSPACE_EXECUTION_INDEPENDENT_REVIEW.md`
fail-closed 派生：只有它绑定当前 seal、verifier、runner、wheel 与 backend identity 并明确 PASS，017 才是
`accepted/delivered`；否则保持 `implemented-candidate`。013 不声称自动识别所有秘密，014 也不承诺 pin 所有
传递依赖，015 也不解决 gitfile symlink/TOCTOU、病态 target 几何或 transitive `commondir`，016 不解决同步
cleanup grace 的输出背压或 post-timeout tail 完整性；尚未关闭的后续问题是 multi-hop symlink 与 truncation
facts。017 本身不提供浏览器自动化、后台 daemon、整机控制或跨平台 sandbox 保证；这些边界是 017 的
能力范围限定，不代表产品其他能力（如 018 governed browser）不存在。

## 018 governed browser tasks status

018 的专属隔离 Chromium（public-read 与 site-bound profile）、唯一 Runtime/ToolRuntime authority、
exact approval、显式 user takeover、SSRF/prompt-injection 边界、download quarantine 与 closed browser
readback evidence oracle 已实现。source、materialized tree 与真实 Chromium 3×13 E3 只能由同一
delivery identity 的 seal/receipt/attestation 证明，旧 receipt 不得复用。

018 的 authoritative promotion 状态只由 detached
`docs/acceptance/018_GOVERNED_BROWSER_TASKS_INDEPENDENT_REVIEW.md` 决定：只有它绑定当前 seal、verifier、
runner、wheel、Chromium identity 与三轮 receipt，并明确记录 `PASS` 时，018 才是
`accepted/delivered`；文件缺失、pending、FAIL 或 identity 不匹配时均保持
`implemented-candidate`。范围不包括个人 Chrome/桌面控制、任意网站兼容、后台 autonomy 或
production-ready 第三方集成声明。

## 019 portable durable automations status

019 分成两个独立交付身份。`019-portable-control-core` 只包含 immutable definition、UTC
schedule resolution、CAS lifecycle、READY/start/result protocol、Runtime/ToolRuntime authority、
owned-workspace port、recovery/open 与 digest-bound purge。它只依赖 typed ports；不 import 或选择
launchd/systemd/Cron、POSIX/Windows process/filesystem、Seatbelt、Playwright 或任何具体 host backend。

portable core 的 authoritative promotion 状态只由 detached
`docs/acceptance/019_CORE_INDEPENDENT_REVIEW.md` 决定：只有它绑定当前 019 seal、verifier、runner、
wheel、materialized full suite 与三轮 13-journey receipt，并在 Spec/Product 和
Standards/Architecture 两轴都记录 `PASS` 时，才是 `accepted/delivered`；否则保持
`implemented-candidate`。即使 portable core accepted，也只表示控制协议可移植且闭合，不表示任一
OS 已具备可运行的无人值守调度。

`019-macos-host-profile` 是后续独立 qualification。只有其真实 owner-only/no-follow persistence、
launchd wake、hard-deadline process cleanup、017 sandbox composition 和 U2B receipt 全部通过，才能
声明“bounded background execution on macOS”。它的缺失或失败不降级 portable core；Linux、Windows、
cloud 仍保持 `not_qualified`，不得从 macOS 证据外推。

## Historical matrix（2026-07-25 bounded v1 reference identity）

本表是 2026-07-25 bounded v1 reference identity 的历史结论快照，不再描述当前工作树；当前 claim 以上方
Current snapshot (2026-09-09) 为准。表中 `accepted` / `locally-verified` 与 Trusted evidence 只对当时
绑定的 identity 成立。本节及其后时间线段落中的 gate 数字与“当前工作树”字样均为写作时点的历史记录。

| Capability | Claim（当时 identity） | Trusted evidence | Blocking closure | Permitted wording |
|---|---|---|---|---|
| Minimal Runtime Kernel | accepted | unique loop/ContextManager/ToolRuntime owners；kernel effect-ordering/recovery/CAS/limits/event fault matrix；materialized `--content` gate 通过；独立 G0–G7 promotion review 完成 | v1 scope only（非 production-ready / 非完整通用 Agent） | minimal foundation；v1 reference task accepted（2026-07-25 独立 review）；非 production-ready、非任意 provider/MCP/Skill 语义 |
| MCP | accepted | governed registration/session seam；spawn 前 executable/ancestor/cwd identity+digest 复验；bounded transport + 持续 stderr drain；execution receipt + unknown-outcome + process-group cleanup + durable safety latch matrix（G2）；materialized gate + 独立 review 通过 | v1 scope only（仅 operator-trusted repo-owned benign stdio fixture） | governed stdio MCP seam；identity/transport closure done；v1 reference task accepted；不等于任意第三方/网络 MCP server |
| Memory | accepted | ContextSource/store/tool seam；strict no-coercion durable load + identity-safe owner-only bounded read + revision CAS；bounded lexical ranking（G3）；materialized gate + 独立 review 通过 | v1 scope only（owner-only 词汇召回，非语义/向量化） | governed Memory seam；strict store closure done；owner-only plaintext；v1 reference task accepted；非语义 Memory、非跨 owner 共享 |
| SubAgent | accepted | 同一 `AgentRuntime` child seam；G8.1 进程隔离 hard-deadline 路径（`ChildProcessRunner`：parent 拥有 process group、killpg+exit-confirm、`process_terminated` receipt；stderr DEVNULL deadlock-safe、per-run temp 目录 rmdir 清理、stdout 有界 overflow→UNCONFIRMED；TERMINATED/UNCONFIRMED 经确定性故障注入证明，UNCONFIRMED 覆盖 normalization→parent recovery）；同步 receipt 路径（`ChildAgentRunner`）保留给声明 synchronous `deadline_contract` 的 provider；materialized gate + 独立 G8 review 通过 | v1 scope only（bounded 单 child，非并发） | bounded child seam + 真实 hard-deadline provider 路径（HTTP adapter 经进程隔离可用）；E2 正向（process-isolated fake provider 经真实进程边界）已证；v1 reference task accepted（真实 HTTP provider in child）；非并发 SubAgent、非任意 child provider |
| Scheduler | accepted | external caller；calendar-valid UTC occurrence identity；conversation_busy + checkpoint_conflict 同一 one-shot reconciliation；needs-human→CLI/TUI 解决→duplicate 报告 authoritative terminal（G5）；materialized gate + 独立 review 通过 | v1 scope only（external caller replay，非 CRUD/持久调度策略） | deterministic external caller；fault matrix closed；v1 reference task accepted；非 Scheduler CRUD、非持久化调度 |
| Skill | accepted（read-only）；implemented-candidate（declared entrypoint） | strict frontmatter/read-only governed tools；声明脚本固定 directory/file identity、size、digest，经 exact approval 与既有 structured sandbox 执行；无 lifecycle/第二套 loop | executable path 尚无真实 release runtime E3；仅 owner-local Python entrypoint、network off、observation result | governed Skill seam；read-only reference task accepted；declared local Python execution 为 candidate，不等于任意/远程 Skill |
| TUI | accepted（v1）；implemented-candidate（browser takeover + terminal follow-up controls） | Textual optional adapter；纯键盘 submit/approve/reject/recovery 成功+失败/resume/cancel、authoritative reopen（零 provider/tool call）、shared event sink/lifecycle、event-fault advisory oracle（R19/R20 + N2 + G6 recovery s/f）；010 补充 displayed-snapshot decision binding；011 增加 state-only browser waiting form、exact Browser done/cancel、recovery-first、A→B stale rejection 与 fresh-owner failure→显式 cancel；012 恢复 terminal Goal discussion，同时保留 claim/evidence、终态零 product tools，并以 hostile registered read/write calls 证明 admission 前拒绝 | 012 的晋级边界为本轮独立 review + final full gate；不提供 browser liveness dashboard、重启旧 browser session、`/new` 或 terminal follow-up 跨重启恢复 | v1 reference task accepted；新增 controls 仅为 candidate；所有 gesture 仍经唯一 Runtime；关闭 Goal 可继续 prose discussion 但不运行 product tools或开始新任务；非跨平台/并发会话或网页副作用回滚保证 |

七项 capability 均已 `accepted`（v1 reference task，2026-07-25 经非实现 session 独立 review 晋级；receipt 见 `docs/acceptance/2026-07-25-E3_INDEPENDENT_REVIEW.md`）。
`accepted` 仅对各自 v1 reference task 的 bounded 任务成立：不是 production-ready，不等于任意 MCP/Skill、语义 Memory、并发 SubAgent、Scheduler CRUD 或跨平台已验证。

009 ordinary candidate 已由独立 reviewer 复核并封存（见 `docs/implementation/009_INDEPENDENT_REVIEW.md`）。
G0 已闭合两个 P2 residual：delivery 的 console-entrypoint origin 断言（N1，`assert_console_entrypoint_origin`
显式验证 `first-agent`/`first-agent-schedule` 来自 non-editable 安装）与 TUI 的 event loss/duplicate/reorder
注入 oracle（N2，证明 advisory 事件不改变 authoritative checkpoint/控制）。
G1–G6 随后闭合了五项 extension capability 的完整 fault matrix（Skill/MCP/Memory/Scheduler/TUI）。
G8 为 SubAgent 引入进程隔离 hard-deadline 路径（`ChildProcessRunner`），使 production HTTP provider
经进程边界获得 honest hard deadline（不再 safe-unavailable）。G8.1 修复了独立复审提出的 stderr
不 drain（F-G8-1，改 DEVNULL）与 temp 目录泄漏（F-G8-2，rmdir 清理）并加 stdout 有界。当时工作树的
materialized `--content` gate 通过（357 passed，未截断，deny-network 边界内；历史记录）。

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

009 candidate 已封存；七项 capability 曾于 2026-07-25 经独立 review 晋级 `accepted`（v1 reference
task；历史结论，仅绑定当时 identity）。以下保守约束持续生效，避免在 v1 scope 之外被误读为 production-ready：

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
