---
title: Capability Reintroduction Audit
date: 2026-07-19
type: audit
baseline_commit: 7d935ac4af7121c54e1bdcc600763c3f0fbf54c2
scope: current-worktree
---

# Capability Reintroduction Audit

## Executive verdict

这次实现不是推倒重来，也不是“没救”。Minimal Runtime Kernel 的唯一 loop、ContextManager、ToolRuntime、checkpoint/recovery 主干仍然成立，六项能力也都出现了可测试的接入骨架。

但“六项能力重接完成”这一总声明不能通过审计。当前更准确的结论是：**Skill、MCP、Memory、SubAgent、Scheduler、TUI 都有 implementation candidate，其中 Skill 最接近合同；MCP 与 Memory 有阻断性问题；Scheduler、TUI、SubAgent 尚未完成各自闭环；所有真实 product/reference-task gate 都没有足够证据宣称通过。**

因此下一步不是继续增加能力，也不是再次重构 Kernel，而是执行 `docs/plans/2026-07-19-008-stabilize-capability-reintroduction-plan.md`，把已发现的假绿、未知结果分类和人类交互闭环逐项修正。

## Scope and method

审计对象是 2026-07-19 当前工作树，不是 `HEAD`。本次重接的大部分新文件仍是 untracked，普通 `git diff HEAD` 不包含它们；审计因此直接读取当前源码、测试、计划和工作日志。

证据来源按以下优先级使用：

1. `AGENTS.md`、`docs/architecture/KERNEL_ARCHITECTURE.md`、`docs/architecture/EXTENSION_CONTRACTS.md` 的架构不变量。
2. `docs/plans/2026-07-18-002-...` 至 `007-...` 的 Requirements、Implementation Units、Verification Contract 与 Definition of Done。
3. 当前产品源码与当前测试行为。
4. `docs/implementation/CAPABILITY_REINTRODUCTION_WORKLOG.md` 和实现者最终报告只作为待验证声明，不作为完成证据。

`graphify-out/graph.json` 仍指向已删除的旧架构，只用于确认图谱陈旧，不用于当前实现结论。没有运行真实 provider、真实外部 MCP 或读取任何凭据/private runtime data。

## Independent gate results

| Check | Result | What it proves | What it does not prove |
|---|---:|---|---|
| `.venv/bin/python -m pytest -q -rx` | 265 passed in 12.52s | 当前本地测试集合自洽 | 被忽略文件可交付、遗漏的 fault matrix、真实 product gate |
| `.venv/bin/ruff check .` | misleading pass | Ruff 在默认 ignore 范围内无诊断 | ignored Memory；显式检查该目录有 18 个错误 |
| `git diff --check` | passed | tracked diff 无 whitespace error | untracked/ignored 新文件；该命令不会检查它们 |
| Effect-owner search | provisional pass | production provider/tool/checkpoint mutation call site 仍集中在 Kernel；Scheduler/TUI 为 `run_turn` caller，SubAgent 是已批准窄化例外 | 每个 capability 自己的安全合同是否完整 |

## Actionable findings

### A1. P0 — Memory code/tests are ignored by Git and skipped by the advertised lint gate

`.gitignore:35` 使用裸规则 `memory/`，它同时匹配 `agent/memory/` 与 `tests/memory/`。`git check-ignore -v` 已确认 Memory 的五个产品文件和四个测试文件全部被该规则忽略。

可观察后果是：当前机器运行 265 个测试时会收集 Memory 测试，但正常 `git add .`、提交、clone 或交给另一名 Coding Agent 后不会带上 Memory 实现与测试；`main.py` 又无条件 import `agent.memory`，交付树会直接 import 失败。Ruff 默认尊重 ignore，所以 `.venv/bin/ruff check .` 显示通过，而显式运行 `.venv/bin/ruff check agent/memory tests/memory` 得到 18 个错误。这是版本库和质量门的双重假绿。

最小修复是把 runtime-state ignore 规则锚定在仓库根目录，例如 `/memory/`、`/skills/`、`/workspace/`，加入一个验证所有产品/测试 package 均未被 ignore 的 delivery test，并在最终门中使用 Git materialized tree 安装/测试，而不是只测脏工作树。

### A2. P0 — Empty MCP allowlist inherits the complete parent environment

`agent/mcp/bridge.py:434-438` 使用 `env=env or None` 启动 server。catalog 没有 `env_names` 或所有名称都不存在时，`env` 是空 dict，随后被转换为 `None`；subprocess 因此继承完整 parent environment，而不是一个空 allowlist。

可观察后果是：未批准转发的 API key、cloud credential、代理配置和其他环境变量会暴露给本地 MCP process。测试 fixture 也在这个继承环境中运行，所以当前测试没有证明 scrubbed environment。

最小修复是始终传入显式环境 mapping；基础变量若确有运行需要，必须是固定、文档化的最小 allowlist。增加 empty/non-empty allowlist child-env fixture，断言未批准 sentinel 永不出现。

### A3. P0 — Bridge wall-clock timeout is misclassified as not executed

`agent/mcp/bridge.py:55-64` 的总 timeout 可以发生在已 spawn、甚至 `tools/call` 已写出之后，但它只抛出不含 commit receipt 的 `BridgeTimeoutError`。`agent/mcp/tools.py:156-165` 把这个异常无条件映射成 `KnownNotExecuted`。

可观察后果是：外部 effect 已发生但客户端超时的调用会被告诉模型“未执行”，模型随后可以重试并产生重复 effect。这违反 MCP R10 和 Kernel unknown-outcome 边界。

最小修复是让 bridge timeout 返回或抛出携带 owner commit state 的 typed outcome；只有证明 call bytes 未写出时才是 `NOT_EXECUTED`，否则进入 `UNKNOWN`、保留 latch、quarantine bridge，并由 parent Runtime 进入 recovery。

### A4. P1 — MCP approval does not show arguments or executable identity

`agent/mcp/tools.py:110-125` 的 approval preview 忽略 `arguments`，也不显示 executable path/identity。`agent/mcp/catalog.py:275-297` 只在 catalog 构建时冻结一次 executable，`agent/mcp/bridge.py:153` spawn 前没有复验，测试 `tests/mcp/test_catalog.py:136-149` 所谓 “revalidated” 实际只是重新构建第二份 catalog 后比较 digest。

可观察后果是：用户只能看到 server/tool/profile，无法知道本次准确参数；catalog/approval 后 executable 或 ancestor 被替换时，可能启动另一份程序。digest binding 只能证明机器绑定，不能替代可读的人类批准对象。

最小修复是 canonical bounded arguments、command/cwd identity 和 profile/generation 全部进入 preview 与 binding；preview 放不下时在 effect 前拒绝。catalog、prepare 和 spawn 使用 no-follow fd/identity 复验，漂移为 known-not-executed。

### A5. P1 — MCP terminal outcome and process cleanup are not coupled

`agent/mcp/bridge.py:473-483` 即使 `process_exit_confirmed=False` 仍保留原 `EXECUTED` classification。`stderr_cap_bytes` 只出现在 `agent/mcp/bridge.py:141` 的参数中，实际没有 reader/cap；stdout/result 也没有总 byte cap，`agent/mcp/bridge.py:387-426` 会先拼接完整内容再交给上层截断。

可观察后果包括：process tree 未确认退出却向 parent 报告 known result、stderr pipe 填满导致死锁、恶意或损坏 server 用超大 stdout/result 消耗内存。当前 tests 没覆盖 partial write、wrong ID、oversized result、grandchild cleanup 和 close uncertainty 的完整分类矩阵。

最小修复是把 `terminal response matched + process group exit confirmed` 作为离开 unknown 区间的共同条件；并在 transport owner 内实现 bounded stdout/stderr/result、持续 drain、redacted error 与 fault injection。

### A6. P1 — MCP durable latch is neither fully hardened nor recoverable

`agent/mcp/safety.py:119-125` 遇到非 owner-only 目录只执行 `pass`；`agent/mcp/safety.py:127-149` 用普通 `open()` 跟随 symlink，且无 mode、owner、size 与 strict-field 校验。`README.md:102` 宣称存在 operator offline recovery，但仓库没有对应 command；同时 `main.py:247` 对首次使用的 safety-state target 调用 `resolve(strict=True)`，缺失文件无法合法 bootstrap。

可观察后果是 latch 安全边界可被路径替换削弱，host crash 留下 ARMED marker 后产品没有受治理恢复路径，只能手工改/删文件；README 中的操作承诺不可执行。

最小修复是按 checkpoint/store 相同的 dirfd、no-follow、owner-only、bounded strict JSON 规则重写 latch I/O，并实现计划要求的 operator-only CAS recovery command、attestation 和 generation/credential-rotation条件。

### A7. P1 — Memory approval preview is partial and not precondition-complete

`agent/memory/tools.py:26` 把 preview cap 固定为 1,000 chars，而 store 允许 20,000 chars；`agent/memory/tools.py:245-280` 对 remember/update 静默截断，对 forget 只显示 record ID。update 没展示 before/after，forget 没展示被删除内容，remember binding 也没有 store revision。

可观察后果是用户可能批准自己没有看全的持久化内容、修改或删除；审批后的并发 store 漂移要到 `EXECUTING` 之后才被发现。它直接违反 Memory R9 的“不能盲批”。

最小修复是把可执行输入限制收紧到能完整安全展示的 cap，或在 prepare 阶段拒绝；remember 绑定 store revision，update/forget 从同一 revision-consistent precondition snapshot 生成完整 bounded preview/diff，并在 invoke 前复验同一 binding。

### A8. P1 — Memory persistence does not meet its no-follow and strict snapshot contract

`agent/memory/store.py:235-245` 先 `stat(..., follow_symlinks=False)`，随后用普通 `open()` 再按路径打开，存在 check/open race；读取无 byte cap。load 在 `agent/memory/store.py:117-135` 大量使用 `str()`、`int()`、`float()` 强制转换，未验证 content digest、unknown fields、record/store revision invariants。`MemoryContextSource` 每次读取的是进程内 cached `_records`，不是重新验证的 fresh durable snapshot。

可观察后果是损坏或被替换的 store 可能被宽松接受，另一个进程已提交的 Memory 长期不可见，source digest 不能证明当前磁盘 revision。当前测试只覆盖基本 persistence reload，不覆盖计划要求的 crash points、lock inode、symlink/hardlink swap 与 strict schema。

最小修复是稳定 lock 内通过 dirfd/no-follow fd 完成 bounded strict load、revision validation 和 snapshot；mutation 使用唯一 temp identity、file/directory fsync；ContextSource 获取一次 revision-consistent immutable snapshot。

### A9. P2 — Memory ranking and projection do not match the documented algorithm

`agent/memory/source.py:61-63` 的排序 key 是 `(-score, record_id)`，没有 R6 要求的 `updated_at` descending tie-break。`agent/runtime/context.py:220-229` 会静默截断候选 frame，但仍使用原 candidate digest，也没有把该截断记录进 `BudgetReport.clipped_ids`。

可观察后果是同分记录的召回顺序与计划不一致，长记录以“完整记录 digest”标识却只把前缀发给模型，影响上下文可解释性和复现。

最小修复是实现 `score desc, updated_at desc, record_id asc`，并让 source 按 `ContextSourceLimits` 产出完整 bounded candidate；无法完整放入单项上限时明确排除或产生带原长/digest的 clipping evidence。

### A10. P1 — Scheduler replay and concurrent reconciliation do not reach authoritative state

`agent/scheduler/caller.py:61-74` 每次都重交固定 seq 1；Kernel replay 返回 seq 1 当时记录的结果。`agent/scheduler/caller.py:76-94` 直接用这个旧 `RunResult.status` 生成 report，没有在 replay 后根据最新 checkpoint 的 `active_run`/`last_safe_result` reconciliation。

可观察后果是 occurrence 首次暂停、随后由人类以 seq 2 完成后，下一次 duplicate fire 仍会报告旧 `AWAITING_APPROVAL`/`needs_human`，与 authoritative terminal state 冲突。并发首次 fire 的 loser 会收到 `conversation_busy`；caller 只对 `checkpoint_conflict` 做一次 reload，所以把合法 duplicate 错报为 fatal conflict。`agent/scheduler/contracts.py:19-41` 还只用正则验证 UTC 字符串形状，`2026-99-99T99:99:99Z` 也会进入 durable identity。

最小修复是 replay 仅用于验证 exact first-action identity；最终 report 必须来自 reload 后的最新 authoritative occurrence state；`conversation_busy` 与 `checkpoint_conflict` 都只允许一次 exact-action reload/reconcile；canonical UTC 需要 calendar-valid round-trip。补完整 pause → human resolution → completed → duplicate、barrier concurrent fire、replay-floor 和非法日期测试，provider/effect count 不增加。

### A11. P1 — TUI product path only implements submit

`agent/tui/app.py:42-84` 设置 `BINDINGS=[]`，只渲染一个 `Input`，唯一 action path 是 `build_submit`。没有 approval/reject、recovery、resume、paused cancel、Scheduler handoff、close/blocked controls。`tests/tui/test_app.py:43-63` 只有 submit → completed Pilot，却被 worklog 描述为 approval/recovery/terminal parity。

此外，`main.py:271` 把 Runtime event sink 绑定到 `TerminalRenderer`，而 `TuiAdapter` 自己创建的 queue 没有接入 Runtime；TUI 运行时事件会写终端而不是 advisory queue。`agent/tui/render.py:97-104` 对 `RUNNABLE/EXECUTING` 错误展示 `resume` 和 `cancel`，但该 unknown-effect 状态合同只允许 Resume。`main.py:299-309` 从 TUI branch 直接 return，绕过 `main.py:310-325` 的 close-stack finally。

可观察后果是需要人类批准或恢复的任务在 TUI 中无法继续，终端输出可能污染 Textual screen，MCP bridge 在 TUI 退出后不按合同关闭。

最小修复是按 shared action builders 实现全部键盘可达 form/action，使用同一个 queue sink 组装 Runtime，所有入口共享停止接收 action → 等 bounded worker → reverse close stack 的生命周期，并补计划 007 的完整 Pilot matrix。

### A12. P1 — SubAgent has no enforceable deadline or exact handoff contract

计划 005 R5 要求只接受声明并实现有限 request deadline 的 provider profile。`agent/subagent/contracts.py:10-20` 没有 deadline/timeout/trust identity 字段，`agent/subagent/runner.py:39-101` 接受任意 `object` provider 并同步阻塞调用；composition 也不验证 provider timeout 小于 child cap。`agent/subagent/tools.py:69-70,87-88` 对 objective/handoff 静默切片，schema 没有对应 `maxLength`。

可观察后果是一个不返回的 provider 可以无限阻塞 parent 的 `EXECUTING` tool invocation；“bounded child”目前只限制 model/tool 次数和 token，不限制 wall time。超限输入的 intent、approval preview 和实际 child handoff 也会表示三个不同对象。测试全部使用立即返回的 `ScriptedProvider`，且没有边界输入。

最小修复是 ChildProfile 绑定可验证的 provider trust identity 与 provider-native hard total-deadline/termination receipt；当前只提供阶段/inactivity timeout 的 HTTP adapters 必须 fail closed，且不使用不可终止 helper thread 伪造 cancel。objective/handoff 在 prepare 前按 schema 精确拒绝，不静默截断；未来 receipt 无法证明请求终止时保持 parent unknown outcome。

### A13. P2 — Skill implementation omits two planned contract details

Skill 的 bounded safe-load、no-follow final-file reads、digest drift 和 governed read-tool wiring总体成立；A19 所述 strict allowlisted schema 尚未成立。此外 R9 要求 metadata 可见，当前 `ToolDefinition`、activation result 都不包含 descriptor metadata；R11 要求 ancestor/file identity 在 scan 后复验，当前 activation/resource 只复验 content digest，没有比较已冻结 identity。

可观察后果主要是合同与实现不一致，而不是已经发现的越权路径。最小修复是以 bounded provider-visible metadata 投影补足 R9，并用 descriptor-relative dirfd/file identity 复验补足 R11；保持 READ_ONLY、无 prompt hook/scripts。

### A14. P1 — Completion and reference-task claims exceed the evidence

`README.md:17` 说六项尚未成为产品能力，后面又逐项给出使用说明；worklog 同时保留多个“进行中”标题和“全部完成”结论。更重要的是：

- MCP 计划明确真实 reference task 未授权就保持 product gate 未验收，worklog 却在同一文档中宣称 MCP 完成。
- TUI gate 要求纯键盘 approval/recovery/restart journey，实际 Pilot 只有 submit。
- Scheduler gate 要求 human resolution 后 duplicate 报告 terminal，测试缺失且实现不满足。
- SubAgent gate 要求与 parent 直接回答比较成本、时长与增量观点，测试只让 scripted child 注入 `SECRET-OMEGA`。
- Memory 所谓 reference task 在 `tests/memory/test_integration.py:33-38` 直接调用 `store.remember()`，绕过 governed tool、approval 和 `EXECUTING` checkpoint；conversation B 也没有让 provider 生成最终答案。
- Skill 和 Memory 当前测试证明 wiring，不足以证明用户批准的真实任务产生价值。

最小修复不是删除这些测试，而是把它们统一标成 automated wiring evidence；按 `docs/acceptance/CAPABILITY_REFERENCE_TASK_PROTOCOL.md` 完成独立 acceptance evidence 后，才把 capability 从 candidate 提升为 accepted。

### A15. P0 — Case variants bypass private-root isolation in file tools

`agent/tools/path_safety.py:278-290` 已计算 `lowered = part.lower()`，但 private-root 分支仍用原始 `part` 与 `_private_roots` 比较。`agent/tools/file_ops.py:22-40` 依赖这个分支隔离 `.claude`、`.codex`、`memory`、`skills`、`sessions` 等目录。

在当前大小写不敏感文件系统上，`Skills/secret.txt` 会解析到真实 `skills/secret.txt`，却绕过 lower-case private-root deny。只读临时目录复现已经返回了被保护内容；同一边界也被 list/write/edit 使用。

最小修复是 casefold 冻结和比较这些 ASCII private-root names，并对 read/list/write/edit 全部加入大小写变体回归。此项属于 Kernel 文件工具安全回归，必须先于所有 capability stabilization。

### A16. P1 — Stale approval mismatch crashes the active run

`KernelToolRuntime` 会正确把过期 binding/grant 返回为 `approval_mismatch` known-not-executed，但 `agent/runtime/state.py:542-547` 在推进 cursor 时没有清除旧 `approval_grant`，同时把 phase 切到 `MODEL`。`ActiveRun` invariant 随后拒绝 MODEL phase 携带 grant。

完整 fake 复现得到 `awaiting_approval → failed_fatal/runtime_failure`，而不是 effect count 为零、可供模型修正或重新请求审批的普通 Tool Result。这破坏了所有 effectful capability 共享的 stale-approval safety path。

最小修复是在 record-nonexecuted 转换中原子清除 grant，并以完整 `AgentRuntime` 测试 approval 后 precondition drift；断言 callable 为零、不会 `FAILED_FATAL`，需要重审时生成全新的 request/grant。

### A17. P1 — Memory context blocks are rejected by real provider adapters

`agent/runtime/context.py:205` 产生 `{"type": "context"}` block，但 `agent/provider/normalize.py:16,63-65` 的 provider-neutral allowlist 不包含 `context`。只要 Memory 召回一个 candidate，OpenAI/Anthropic adapter 会在 HTTP 前以 `unsupported_context_block` fail closed。

可观察后果是 Memory 的 local ContextManager 测试可以通过，正常 provider composition 却无法使用它。最小修复是定义 provider-neutral untrusted context block schema，并在 OpenAI/Anthropic request builder 中投影为带明确来源/不可信标记的非-system user text；用无网络 request-builder tests 验证。

### A18. P1 — Known-executed failures are flattened into successful ToolResults

`agent/mcp/bridge.py:399-418` 能产生 `EXECUTED + remote_error/unsupported_content`，但 `agent/mcp/tools.py:166-167` 只返回字符串；`agent/subagent/tools.py:77-80` 对 child nonterminal 也只返回普通字符串。`KernelToolRuntime` 因此把两者包装为 `executed=True, is_error=False`。

可观察后果是模型和审计消费者无法区分真实成功、远端 `isError`、unsupported result、child tool request/limit/pause。最小修复是在共享 callable outcome taxonomy 中加入受校验的 known-executed error，精确保持 `executed=True, is_error=True, code`；unclassified 外部失败仍为 unknown，不能借此降级。

### A19. P2 — Skill frontmatter is not a strict allowlisted schema

`agent/skill/catalog.py:254-294` 读取已知字段后继续执行，没有拒绝 top-level unknown keys；同字节 inode replacement 也因 A13 所述 identity 未复验而继续有效。

可观察后果是拼错的安全字段或看似有限制作用的未来字段会被静默忽略，operator 误以为策略已生效。最小修复是冻结精确 key allowlist，拒绝 duplicate keys、aliases/cycles、unknown keys 与超限 YAML graph，并保持 bounded、no-follow、identity+digest runtime revalidation。

## Capability disposition

| Capability | Architecture seam | Automated wiring | Safety/closure | Product gate | Audit disposition |
|---|---|---|---|---|---|
| Kernel | pass | pass | fail: A15-A16 | Kernel walking skeleton only | foundation retained, stabilization first |
| Skill | pass | pass | partial: A13, A19 | not evidenced | candidate, nearest to acceptance |
| MCP | pass | partial | fail: A2-A6, A18 | explicitly not run | blocked |
| Memory | pass | local-only | fail: A1, A7-A9, A17 | wiring bypasses governed write | blocked |
| SubAgent | pass | pass | fail: A12, A18 | no comparative evidence | partial |
| Scheduler | pass | partial | partial: A10 | journey incomplete | partial |
| TUI | pass | submit only | fail closure: A11 | journey incomplete | partial |

## What remains trustworthy

- `AgentRuntime.run_turn` 仍是 production model/tool loop 和 conversation state progression 的中心。
- `KernelContextManager` 仍独占 `ContextPack` 构建与总体预算。
- `KernelToolRuntime` 仍独占 governed callable invocation；Skill/MCP/Memory/SubAgent 没有另建普通 production tool loop。
- Scheduler 仍是 external caller，而不是内置 timer/daemon。
- TUI 仍是 adapter 方向，没有复制 reducer；问题是功能与生命周期没有完成，而不是方向错误。

这些是继续修复而不是再次推倒的理由。

## Review limitations

- 未运行真实 provider、真实外部 MCP、用户 Skill/Memory/private state，因此不宣称真实世界兼容性或性能。
- 当前实现主体未提交；本审计不能证明未来 staged/commit tree 与当前工作树相同。
- Graphify 图谱陈旧，没有刷新；当前结论以源码和测试为准。
- 没有执行会向外部服务发送仓库内容的 cross-model adversarial review。
