# Extension Contracts

新增能力是否方便，取决于它能否落在已有边界里，而不是“再加一个模块”。Kernel v1 支持以下显式组合点。

能力重接使用一个小型静态 composition result：Order 0 只收集当前真实消费者需要的 registrations，并构造一个 ToolRuntime、一个 ContextManager 与一个 AgentRuntime；MCP 在出现首个真实 closeable 时增加 ordered close stack，Memory 在定义 `ContextSource` 时再增加 explicit sources tuple。任何阶段都不得提供 global getter、dynamic registry、hot reload、feature flag 或按名字查 service。

## 可以直接扩展

### ToolSource

适合 Skill、MCP 操作和 SubAgent delegation。扩展提供 `ToolSpec`、参数 schema、policy binding 与一个 callable，然后通过 `KernelToolRuntime` 统一执行。它不能自行调用模型、批准自己或写 checkpoint。

窄化例外（SubAgent）：只有 `subagent__delegate` 的 executor 可以调用 composition root 注入的 `ChildAgentRunner` port；该 port 的唯一 production implementation 构造同一个 `AgentRuntime` 类并只调用其 `run_turn`，child 的 provider call 仍只发生在 `agent/runtime/loop.py`。executor 本身不导入或调用 `ModelProvider`/loop。不接受该窄化时，进程内 SubAgent 不属于 ToolSource 扩展。

Skill v1 已经按这个 seam 实现：显式 trust root 经 `agent.skill.catalog` 冻结为不可变 descriptor/digest，`agent.skill.tools` 把每个 Skill 暴露为 `skill__<name>` READ_ONLY activation 工具加共享 `skill__read_resource`；启动时能建立 trusted application runtime（应用自身 interpreter/stdlib/固定 runner）时，声明的 Python entrypoint 额外成为 ALWAYS_APPROVAL + ISOLATED_SANDBOX 工具。`agent.composition.build_tool_registrations` 把它们与文件工具拼接进唯一 `KernelToolRuntime`。它没有 prompt hook、包生命周期、远程 registry 或自动激活。

MCP v1 也按这个 seam 实现：operator-approved 显式 catalog 经 `agent.mcp.catalog` 冻结为具体 `mcp__<server>__<tool>`（HIGH + EXTERNAL + ALWAYS_APPROVAL）；`agent.mcp.bridge` 用 project-owned stdio transport（自持 process group/framing/commit receipt）把消息流注入 SDK public `ClientSession`，独占一条长生命周期 event-loop thread 但 startup 不创建 session；`agent.mcp.safety` 是 owner-only durable CAS 安全 latch，每次调用在 `EXECUTING` 后 arm、process-group 确认退出后 clear。MCP 是首个真实 closeable，把 ordered close stack 加入 composition；teardown 倒序关闭。它不联网 discovery、不缓存 live registry、不自动重试 effectful 调用；call 后未分类结果一律进 human recovery。

唯一窄化例外是受限 SubAgent delegation：它的 callable 只能调用 composition root 注入的 `ChildAgentRunner` port；该 port 的唯一 production implementation 必须复用同一个 `AgentRuntime.run_turn`。callable 仍不得导入或调用 `ModelProvider`、实现 model/tool loop、共享 parent state/cursor 或绕开 parent ToolRuntime effect ordering。若不满足这些条件，进程内 SubAgent 不属于 ToolSource 扩展。

接入检查：

- 是否通过同一个 `prepare → approval/policy → persist EXECUTING → invoke → persist result` 路径？
- 是否有明确 side-effect、输出上限和安全 policy？
- 是否用 fake/local fixture 证明拒绝、审批、恢复与结果配对？

### ContextSource

适合 Memory 等只读、可预算的上下文候选来源。唯一 port 形状是 `ContextSource.snapshot(query) -> ContextSourceSnapshot`；snapshot 原子携带 source identity、revision、digest 与 bounded immutable candidates。它不能返回 `ModelMessage` / `ContextPack`、标记 pinned/system priority、调用 provider/tool/checkpoint 或修改 Runtime state。

`ContextManager` 仍独占 source 调用、排序、预算、projection 与 BudgetReport。ContextSource 必须显式 composition；没有动态 registry。长期内容的修改必须走 governed tools，而不是 source hook。

Memory v1 已经按这个 seam 实现：`ContextQuery`/`ContextCandidate`/`ContextSourceSnapshot` 是不可变叶子合同，`ContextSource` port 只返回一次 revision-consistent snapshot；`KernelContextManager` 显式接收 sources tuple，把候选投影为 untrusted context 块（永不 system）、按 lexical 打分排序、计入总预算且永不挤掉 core，并把 source digest/candidate IDs 写入 `BudgetReport`。`agent.memory.store` 是显式 create/load、owner-only、revision CAS 的本地 store；`agent.memory.source` 提供 immutable candidates；`agent.memory.tools` 的 search/get（READ）与 remember/update/forget（ALWAYS_APPROVAL WRITE）走唯一 ToolRuntime。conversation checkpoint 不保存 store snapshot。

### ModelProvider

适合新的 provider 协议。adapter 只做 `ContextPack → ModelResponse` 的序列化和归一化；它不能循环、调用工具或推进 state。需要 opaque reasoning/encrypted continuity 的模式必须 fail closed，直到合同被明确扩展。

### CheckpointStore

适合替换持久化介质。实现必须保留 load-once snapshot、非阻塞 mutation ownership、revision/token CAS、容量预留和安全恢复语义，不能在冲突时静默 reload/retry。

### EventSink

适合日志、Evidence、TUI 或观察面。sink 是 best-effort 通知者，不能改变决策或同步重入 Runtime；消费者按 `event_id` 去重。

TUI v1 已经按这个 seam 实现：`agent.cli.actions` 是 CLI/TUI 共享的 pure typed-action builder（legality 仍由 shared reducer 裁决）；`agent.tui.adapter` 是 Textual-free 的 single-flight 同步 boundary + thread-safe event queue + 只读 `load_view`；`agent.tui.render` 提供 literal safe-display（ANSI/C0/C1/bidi 以可见 escape 表示，超限 effect 前拒绝）与 authoritative projection matrix；`agent.tui.app` 是 optional Textual app（`--tui`，缺失时给安装提示），worker 只调用一次 `adapter.execute_once`，RunResult/checkpoint 始终权威，events 只 advisory。base install 不导入 Textual。

### External caller

适合 Scheduler、服务 API 或新的 UI。调用方只提交 typed action 并消费 `RunResult` / `RuntimeEvent`，不能直接操作 provider、tools 或已有 conversation state。composition/setup 可以像 CLI 一样排他初始化一个全新的 checkpoint；初始化后只能由 Runtime mutation。并发首次创建的 caller 最多为同一个 action 做一次显式 reload/replay reconciliation，不能循环重试或产生新 sequence。

Scheduler v1 已经按这个 seam 实现：`agent.scheduler.contracts.ScheduledOccurrence` 把一次外部触发确定性地映射为独立 conversation/checkpoint（路径只由 schedule+occurrence ID 派生，conversation/run/action identity 额外绑定 scheduled_for/message/workspace scope）；`create_or_load_occurrence_store` 用排他 `LocalCheckpointStore.initialize` 或 load；`ScheduledOccurrenceCaller` 只接收 pre-bound Runtime/snapshot，唯一 execution call 是 `run_turn`，duplicate fire 走 replay，approval/recovery/limit 一律报告 needs_human。没有 timer/daemon/cron parser 或第二套 loop。

所有 caller 复用 shared reducer 的 action legality；尤其 durable `ContinuationPhase.EXECUTING` 只能 `Resume` 进入 unknown-outcome recovery，`CancelRun` 必须返回 unchanged conflict；进入 `AWAITING_RECOVERY` 后只接受 exact outcome resolution。任何 caller 都不能清除尚未分类、可能已经发生的 effect。

## 需要先设计合同

- **不可信扩展**：需要独立进程/RPC、权限与 credential 隔离设计；当前 Python 扩展默认 operator-trusted。
- **Streaming**：需要独立定义 advisory event、最终响应与中断恢复语义，不能在 adapter 内“先 stream 再重放 create”。

## 明确禁止

- 第二个 model/tool loop
- capability 自己保存 durable cursor
- CLI/TUI 直接执行工具或修改 checkpoint
- 根据工具名字猜风险或绕开统一 policy
- 为“以后可能用”提前加入动态发现、兼容层、feature flag 或 service locator

Graphify 与 Understand Anything 只帮助 Coding Agent 理解和审阅仓库；它们不属于这些产品扩展点。
