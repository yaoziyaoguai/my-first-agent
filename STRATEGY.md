---
name: my-first-agent
last_updated: 2026-08-03
authority: product-strategy
---

# my-first-agent Strategy

## North star

First Agent 是一个 local-first 的通用个人 Agent：用户在当前目录启动它，用同一个入口提问、讨论和委托任务；它自己判断应该直接回答、做最小澄清，还是建立并持续推进一个 Goal。它不是只为编程服务，也不要求用户预先选择聊天、编程或任务模式。

长期目标是逐步成为用户可控的本机行动入口。能力扩大必须建立在可见状态、精确授权、可靠恢复和可验证完成之上，而不是一次性获得整台电脑的无限权限。

## Product promise

- 简单问题直接回答，不为每句话制造 Goal。
- 明确任务形成 durable Goal，在授权边界内持续推进，不依赖用户反复输入“继续”。
- 只有缺失信息可能实质改变结果、受益人、目标对象、范围、显著成本、敏感数据处理、对外承诺、权限或不可逆后果时才询问。
- 不确定但无风险时，先做无副作用调查或最小可逆行动；不能安全判断时只问一个最小必要问题。
- 重启后从本地事实恢复安全下一步；不猜测多个候选，也不盲目重放结果未知的副作用。
- `VERIFIED_DONE` 只表示验收条件被独立证据满足，不等于模型停止或模型说“完成了”。
- 只记忆用户通过 First Agent 明确说过、确认过，或由 First Agent 受治理完成的事情；不观察 First Agent 之外的本机活动。

## Local-first 的准确含义

local-first 指 Goal、checkpoint、权限、审批、Memory 与 evidence 默认由用户在本机拥有，并且外发可见、可审计、可停止。它不承诺模型推理必然在本机。

使用远程 Provider 前，First Agent 必须披露 destination identity、模型以及可能发送的数据类别。Provider destination 或信任主体变化时，不能静默复用已绑定的 Memory，也不能把 credential 写入 checkpoint、event、日志或模型上下文。

## Stable architecture

- `AgentRuntime.run_turn` 是唯一 production model/tool loop 和 checkpoint 初始化后的状态推进入口。Composition 只允许排他创建空 checkpoint 与 deterministic session locator；它不能写 Goal、处理 action 或推进既有状态。
- 所有用户输入都以 typed action 进入同一 Runtime；CLI、TUI、headless 与未来 UI 只翻译 action 和渲染 state/result/event。
- `ContextManager` 独占模型上下文选择；`ToolRuntime` 独占可调用工具的准备、policy、approval 与执行。
- Provider adapter 只做 `ContextPack -> ModelResponse`，不能分类后另起循环、执行工具或写状态。
- Memory 是受预算的 `ContextSource`；Skill、MCP、SubAgent 是 governed tools；Scheduler 是 external caller。
- 外部 Claude Code/Codex 可用于 Loop Engineering 开发本项目，但不得成为产品内的 CodingLoop、daemon 或第二套 Runtime。

## Fact ownership

First Agent 不建设含义模糊的“三层 Memory”。三类事实分别由不同权威拥有：

1. **Goal continuity**：canonical checkpoint 拥有 Goal contract、当前阶段、未完成条件、审批、effect 状态与 evidence 引用。
2. **Workspace memory**：现有 workspace-scoped Memory 保存仅对该 workspace 有效的长期事实。
3. **Owner preference**：最小跨 workspace 层只保存用户明确表达或完整预览后确认的稳定偏好，并保留 provenance、修订、纠正与停止未来召回的语义。

项目文件、网页、工具输出、模型推断和失败结果不能自动晋级为 owner preference。召回冲突时优先级是当前用户输入 > 当前 Goal > workspace fact > owner preference；不能静默覆盖更高权威事实。

“遗忘”在近期产品中只保证停止未来 active recall，不伪称已经重写历史 checkpoint、审计证据、用户产物或远程 Provider 已接收的副本。

## Capability tracks

### 1. Trusted continuity

统一回答、澄清、Goal 建立、执行、暂停、纠正、恢复和验证，让一条真实用户旅程跨重启成立。这是 012 的唯一交付主线。

### 2. Governed authority expansion

在后续独立里程碑中增加精确、临时、可撤销的多目录、网络、外部服务和系统能力授权。它必须保持静态 composition 或定义新的 durable authority contract，不能引入 dynamic registry、hot reload 或第二个 Runtime。

### 3. Personal continuity hardening

在最小 owner preference seam 经过使用验证后，再增加保留期、容量、导出、物理删除、备份和更细的敏感度控制。

### 4. Outcome-driven improvement

从纠正、成功、失败和恢复中提出 playbook/Skill 候选，在冻结基线、独立 oracle、canary 和 rollback 下晋级。优化器永远不能自行修改 Goal、权限、治理、权威验收或 Runtime source。

### 5. Broader PC action

只有前述连续性、授权和验证边界稳定后，才逐步扩展到更广本机任务。First Agent 不通过环境监控学习用户，也不默认接管整台电脑。

## Completed foundation

### 012 Trusted Continuity MVP — 从对话到可验证行动

012 已交付并通过离线、真实 Provider E3 与独立 review 的冻结旅程：

1. 用户在默认或明确 workspace 启动 First Agent，看到 workspace、Provider disclosure、authority 与 Memory 状态。
2. 简单问题直接回答，不建立虚假 Goal。
3. 真正影响结果的歧义只触发一个最小必要问题，且询问前没有副作用。
4. 明确本地任务在唯一 Runtime 中建立并持久化 Goal，然后使用既有固定 workspace authority 与 tool approval 执行。
5. 进程中断后，唯一安全候选自动恢复；多个候选、identity 变化或结果未知时准确停下。
6. Goal 到达 evidence-backed `VERIFIED_DONE`，或给出包含已完成进展、缺失条件与恢复点的 `BLOCKED`。
7. 新 workspace 只能召回一条已确认 owner preference，不能召回旧 workspace 的 task fact。
8. 用户能查看来源、纠正并停止未来召回；重启后旧版本不再 active recall。

012 明确不实现动态 multi-root、运行中热加载工具、自动学习、replay/canary/promotion、后台常驻服务、跨设备同步或环境活动监控。

### 013 Everyday Workspace Agent — 从可靠内核到日常可用入口（已交付并验证）

013 没有扩大 Agent 权限，而是把 012 已有能力收束成默认产品路径，并已完成交付验证：

1. 用户一次保存不含秘密的 Provider profile（含显式 `request_path`/`strict_tools` opt-in），此后在空或已有目录只运行 `first-agent`。
2. 用户只用自然语言提问、讨论或委托当前 workspace 内的文件任务，不选择 chat/task/code 模式。
3. 简单问题和讨论不制造 Goal；明确产物先持久化 Goal，再持续推进到真实安全边界或验证完成。
4. disclosure、approval、recovery 和多候选恢复用可读语境交互，用户无需复制 digest/request ID。
5. 默认输出只显示用户需要知道的回答、决定、进展、证据和 blocker，不暴露内部协议噪音。
6. 空目录建产物、讨论转产物、已有目录精确修改三条真实 Provider journey 在官方 DeepSeek
   OpenAI-compatible strict endpoint 连续三次未插桩通过（12/12 receipt claims 全 true）。

013 仍不实现 shell、web、browser、动态 multi-root、整机活动监控、后台 daemon 或自主优化。完整合同见
`docs/architecture/013_EVERYDAY_WORKSPACE_AGENT_DESIGN.md`，验收证据见
`docs/acceptance/013_EVERYDAY_WORKSPACE_AGENT_E3.md`。

## Current milestone

013 已交付并验证（见上）。下一里程碑尚未启动；按 capability tracks 的顺序与现有稳定边界另行
批准，不因 013 完成而隐式扩权。

## Success metrics

- 冻结 012 与当前 013 reference suite 的合同测试必须 100% 通过。
- 未经授权或重复 effect、错误跨 workspace task-fact recall、Memory/文件/网页扩大权限、false `VERIFIED_DONE`：任一非零即 stop-ship。
- 必要询问召回率和无效询问率同时报告，不能靠“从不问”或“什么都问”刷分。
- 跨重启成功必须证明没有要求用户复述、没有重复已完成步骤、没有盲目重放 unknown effect。
- 真实 Provider 结果必须记录样本数、配置 identity、原始 receipt 摘要与独立 verdict；mock/fake 不能冒充 E3。

## Non-goals

- 不监控用户未通过 First Agent 进行的系统活动。
- 不把 Graphify、Understand Anything、Claude Code 或其他开发辅助包装成产品能力。
- 不宣称当前 operator-trusted Python tools 是强沙箱。
- 不建立云端多租户、账号系统或大众 GUI。
- 不允许任何执行者通过修改目标、验收、权限或失败记录制造“成功”。

## Marketing

**One-liner:** 一个知道什么时候该聊、什么时候该做，并记得你们共同经历过什么的本地个人 Agent。

**Key message:** 从当前目录和最小权限开始。你只表达需求，First Agent 负责理解、行动、记忆和验证；只有真正改变结果或风险边界时，它才停下来问你。
