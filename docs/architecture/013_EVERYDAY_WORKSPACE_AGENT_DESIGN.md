---
title: 013 Everyday Workspace Agent - Product and Architecture Contract
type: architecture
date: 2026-08-03
authority: 013-design
status: implemented-and-verified
---

# 013 Everyday Workspace Agent — 产品与架构合同

## 1. 目标

013 把已经通过 012 验收的 Runtime Kernel 收束成一个日常可用的产品入口。

用户在空目录或已有目录中执行一次 `first-agent`，然后直接用自然语言提问、讨论或委托当前
workspace 内的文件任务。First Agent 自己判断是直接回答、继续讨论、做一个最小必要澄清，还是建立
durable Goal 并持续推进。用户不选择 chat/task/code 模式，也不需要为普通进度反复输入“继续”。

013 不是新建一个更大的 Agent framework，也不是增加整机控制能力。012 已拥有的唯一 Runtime、Goal、
恢复、审批、evidence 和 Memory 边界保持不变；本里程碑只补齐默认配置、入口交互和用户可见体验。

## 2. 用户完成后得到什么

完成 013 后，首次使用分为一次 setup 和此后的日常启动：

```text
$ first-agent setup --provider openai_compatible \
    --model your-model --base-url https://provider.example \
    --credential-env FIRST_AGENT_API_KEY
Provider profile saved. Secret values were not stored.

$ cd any-directory
$ first-agent
First Agent is ready in: any-directory
> 帮我想想这份说明怎么写
...
```

- 简单问题直接回答，不制造 Goal。
- 开放式讨论保持为讨论；只有用户要求产物或可持续任务时才建立 Goal。
- 明确的当前目录文件任务先持久化 Goal，再在固定 workspace 权限内执行和验证。
- 安全确认使用当前语境中的简短回答，不要求复制 digest、request ID 或内部状态名。
- 唯一安全任务自动恢复；多个任务候选以可读摘要让用户选择，不要求理解 checkpoint。
- 默认输出只展示用户需要知道的事实、风险、下一步和证据，不刷模型/工具内部事件。

## 3. 冻结范围

### In scope

1. 一个 owner-only、non-secret `ProviderProfileV1`，支持一次 setup 后无参数启动。
2. `first-agent` 默认使用当前目录和已保存 profile；没有 profile 时给出一条准确 setup 指引，不能静默使用 FakeProvider。
3. Provider disclosure、文件写入 approval、unknown-outcome recovery 和多候选恢复的上下文式终端交互。
4. 面向用户的启动、状态和错误文案；隐藏默认无价值的内部事件噪音。
5. direct answer、discussion-to-artifact、empty/existing workspace file task 三条 reference journey。
6. 真实 Provider E3、fresh independent review 和 materialized full gates。

### Out of scope

- shell/terminal execution、Git 自动操作、网页搜索、浏览器、邮件、日历、MCP 市场。
- workspace 外动态扩权、multi-root、整机控制或 ambient monitoring。
- 后台 daemon、定时自动运行、无限循环或用户离开后的主动任务。
- 自动修改 Runtime、自动生成/晋级 Skill、自主 optimizer/canary/promotion。
- GUI、大众安装器、账号、多用户、云同步或强沙箱。
- 把 Claude Code、Codex、Graphify 或 Understand Anything 作为产品运行时能力。

上述能力只能在未来独立里程碑中，通过现有稳定边界逐项重新批准。

## 4. 不变量

013 不得削弱以下合同：

- `AgentRuntime.run_turn` 是唯一 production model/tool loop 和 checkpoint 初始化后的状态变更入口。
- CLI/TUI/headless 只把用户选择翻译为 typed action，并渲染 `RunResult`/durable state；它们不能根据自然语言推进 Goal。
- `ContextManager` 独占模型上下文选择；`ToolRuntime` 独占 callable tool prepare/policy/invoke。
- Provider adapter 只做 `ContextPack -> ModelResponse`；setup/profile 不能变成第二次模型分类调用。
- effect 仍遵守 policy/approval、`EXECUTING` checkpoint、call 和 result checkpoint 的顺序。
- credential value 只从 profile 指定的环境变量在 composition root 注入，永不写入 profile、checkpoint、event、日志或模型上下文。
- profile、UI 确认和易用性不能扩大 workspace、tool、service 或数据外发 authority。
- FakeProvider 只用于显式开发/测试；日常无参数启动不能假装它是可用的真实 Agent。

## 5. ProviderProfileV1

### 5.1 位置与所有权

默认 profile 保存为默认 product state root 下的固定文件：

```text
~/.local/state/my-first-agent/v1/provider-profile.json
```

显式 `--state-root` 同时选择对应 profile 与 workspace sessions。profile 路径必须在 workspace 外，父目录
为 owner-owned real directory `0700`，文件为 regular/no-follow/single-link `0600`。写入使用同目录临时
文件、`fsync` 和 atomic replace；解析使用 strict schema，未知字段、symlink、owner/mode 不符均 fail closed。

profile 是 composition configuration，不是 conversation checkpoint。它可以由 setup 写入，但不能包含 Goal、
conversation、Memory、approval 或任何 Runtime state mirror。

### 5.2 Strict schema

`ProviderProfileV1` 只包含：

- `schema_version = 1`
- `provider_type = anthropic_compatible | openai_compatible`
- `model`
- canonical `base_url`
- `credential_env`
- `thinking_mode = null | disabled`
- `request_path = null | 显式 "/" 开头路径`（无空白/控制字符/query/fragment）
- `strict_tools = false | true`（仅 `openai_compatible` 可为 true）
- `timeout_seconds`

`request_path` 与 `strict_tools` 是显式 opt-in 配置：strict 模式只在用户 setup 时明确传入
`--strict-tools` 后生效，产品不做任何基于 base URL、model 名或响应形状的 host 启发式推断。
未指定 `request_path` 时 adapter 使用各协议默认路径。

禁止保存 credential value、Authorization header、proxy、请求正文、system prompt 或 shell command。

### 5.3 Setup

唯一 setup 入口为：

```text
first-agent setup --provider ... --model ... --base-url ...
```

可选项只有 `--credential-env`、`--thinking-mode`、`--request-path`、`--strict-tools`、`--timeout`、
`--state-root`。setup：

1. 只做本地 strict validation 和原子写入；不调用 Provider。
2. 不读取 credential value，只检查所选环境变量名称是否合法。
3. 完整 profile 替换必须显式再次执行 setup；没有 partial merge 或旧字段 fallback。
4. 输出 destination/model/credential env name 和“未保存秘密”的事实，不输出 env value。

### 5.4 启动解析

日常 `first-agent` 按以下排他规则解析 Provider：

1. 完整的显式 runtime provider 参数组；
2. 否则读取当前 state root 的 `ProviderProfileV1`；
3. 两者都没有时，显示一条可复制的 setup 指引并在任何 checkpoint/provider/tool I/O 前退出。

显式参数不能与 profile 做 partial merge。`--provider fake` 仍可显式用于开发测试，但不能持久化为日常
profile。真实 Provider 缺 credential env 时，错误只显示环境变量名。

## 6. 一个自然语言工作入口

`first-agent` 的普通文本始终形成 `SubmitMessage`。不新增关键词路由器、preflight classifier 或第二次模型
调用。Runtime 使用既有 provider-neutral control protocol 决定：

- direct answer：没有 durable work，不创建 Goal；
- discussion：讨论、解释、比较、头脑风暴一律 answer-only——除非用户同时显式要求一个 durable
  artifact/文件变更，它们自身永不创建 Goal，也不调用文件工具；
- clarification：只在方向边界缺失时问一个最小问题，问前零工具 effect；
- task：只有显式 create/write/edit/save 一个有界产物/文件的请求才建立 Goal——先 CAS Goal，
  再在同一个 `run_turn` 中持续到明确安全边界；
- correction：作为普通消息进入同一 control protocol，使旧 next step/evidence binding 失效。

这一 intent/progress 生命周期只以模型可见的 system 指令（composition 的
`EVERYDAY_SYSTEM_POLICY`）表达：`goal_progress` 只记录已发生的实质进展，永不替代产品工具
调用，也不得重复既定 next step。没有第二个 classifier、prompt router 或额外模型调用。

系统策略只描述这些行为和当前固定 workspace，不承载隐藏权限。空 workspace 不是错误；需要发现文件时，
模型使用已有 `list_files('.')`。已有 workspace 中只能通过现有 bounded/no-follow 文件工具读取和修改。

## 7. “不需要反复继续”的准确含义

一个成功的 bounded run 在同一次 `AgentRuntime.run_turn` 中自动跨越 GoalProposal、GoalProgress、工具结果和
CompletionClaim，直到：

- 得到直接回答或澄清问题；
- 等待一次真实 disclosure/approval/recovery 决定；
- 达到 verified done；
- 遇到真实 config/authority/capacity/provider failure；
- 被用户 pause/cancel。

阶段性进度文字不能结束 active Goal，也不能要求用户输入“继续”。Everyday composition 不设置累计
model/tool/input/output 任务上限；只要仍有真实进展就继续。provider outage、conversation capacity、unknown
effect、新权限边界、用户控制或紧急停滞熔断属于真实停止条件；UI 必须说明事实和可恢复动作，不能假装已经完成。

显式使用有限 `InvocationLimits` 的 Scheduler/SubAgent 等 caller 仍可得到 `PAUSED_LIMIT`；CLI 外层不自动反复
提交 `Resume` 来绕过这些 caller 选择，也不新增后台 loop。

### 7.1 真实模型控制修复

真实模型不能猜 Runtime 内部 evidence ID。`trusted_goal` 必须投影按 mandatory criterion 顺序生成的
`expected_completion_evidence_refs`；模型在 `completion_claim` 中原样复制，closed evidence registry 仍从
durable raw facts 独立重算证明。知道引用名不等于拥有完成证据。

每个 control call 必须使用新的 `correlation_id`，不得复用已受理的 control receipt。已成功解码但与当前
trusted state 冲突的 completion control 只能在同一个 `run_turn` 内得到有界 repair；repair 仍失败则
fail closed。Provider 响应若无法严格归一化，所有 tool/control 均为零接纳、零执行；Runtime 可在相同可信
上下文上有界重试，超过限额则以 `invalid_provider_response` 终止。everyday composition 显式使用
`max_invalid_repairs=4`，只约束严格协议/control 修复；任务停滞独立使用
`max_no_progress_replans=16`。后者按连续独立 model response 的相同语义指纹计数，同一并行 tool batch 只算一次；
换策略、真实 tool result 或新增 evidence 会重置。任何 repair 都不得宽松解析 JSON、伪造 evidence、重放 effect
或要求用户输入“继续”。

### 7.2 Strict 控制通道与 trusted SYSTEM 回执投影

严格 Tool Calls provider（如 DeepSeek OpenAI-compatible beta）按 schema 逐字段约束模型输出，
这暴露了两类必须在架构层关闭的缺口：

- **portable vs strict control schema**：`ContextPack.control_schema` 同时携带 portable
  `input_schema`（平铺字段、跨协议子集）与 `strict_input_schema`（单一 `payload` wrapper、
  每个 object `additionalProperties: false` 且 `required == properties` 的 anyOf 变体闭包）。
  strict 模式的 OpenAI adapter 必须使用 `strict_input_schema`，缺失即 fail closed
  （`missing_strict_control_schema`）；非 strict 路径继续使用 portable schema。
- **trusted SYSTEM 回执投影**：已受理的 `ControlReceipt` durable tuple 只能投影进 trusted
  SYSTEM 上下文——`FIRST_AGENT_TRUSTED_CONTROL_RECEIPT` 前缀 + canonical JSON（恰好 kind 与
  correlation_id、control_kind、goal_id、goal_revision、accepted_state_revision、payload_digest、
  receipt_digest 七个持久字段），由两种协议 adapter 共用同一投影 helper 与 `context.system`
  保序拼接。回执**永不回放成历史 assistant tool call/result 对**；代码库中不存在任何可被模型
  模仿的回执函数名。strict 模型曾把历史回执调用当作新的可调用工具，这一投影从结构上消除了
  该失效模式。

strict wire 合同（仅 `openai_compatible` 且显式 opt-in）：所有 tool definition 与 control
wrapper 标记 `strict: true`；`temperature=0` 保证控制决策确定性；存在 active Goal（已有
trusted_goal，而非 bootstrap）时 `tool_choice: "required"`，不允许模型以 prose 结束一个未验证
的 active Goal。以上全部发生在 Provider adapter 的 `ContextPack -> ModelResponse` 投影内；
`AgentRuntime.run_turn` 仍是唯一 production loop，没有第二条模型或工具路径。

### 7.3 暂停语义（fresh review F3）

`PAUSED` 的 Goal 不是 active control surface。暂停后普通问答仍然可用：prose 只结束本次
run，不改变仍然暂停的 Goal。为此三层一致收口：

- 模型可见能力层：ContextManager 在暂停时只暴露只读 callable，并且不下发 goal 控制
  schema——strict adapter 因而不会强制 `tool_choice`，问答可以 prose 收尾；
- Runtime 层：effectful tool 在 prepare 之前 fail closed
  （`effectful_tool_requires_resumed_goal`）；模型上报的 goal 控制（进度/修订/完成/阻塞）
  得到有界 `paused_goal_requires_resume` repair，超限 fail closed；
- reducer 层：`record_goal_progress` 拒绝对暂停 Goal 记录进度，进度不能把状态静默翻回
  `EXECUTING`。

任何任务推进或 effect 都必须先显式 `ResumeGoal`；交互级最小澄清不受影响。

## 8. 上下文式安全交互

### Provider disclosure

Runtime 仍先持久化 exact disclosure request，且 acknowledgement 仍绑定 request digest。CLI 展示 destination、
model 和 data classes 后询问“允许发送吗？[y/N]”。`y/yes/是/允许` 只在存在 pending disclosure 时翻译为
`AcknowledgeProviderDisclosure`；其他状态下仍是普通用户文本。拒绝不发送。

### Tool approval

CLI 展示 tool、risk/effect 和 bounded preview 后询问“执行这次操作吗？[y/N]”。肯定/否定只在 exact pending
approval 下翻译为 `ResolveApproval`，使用 durable request/binding；用户不复制 ID。已有精确 slash command
可以作为高级兼容入口保留，但 README 的主路径不依赖它。

### Unknown outcome

未知结果不能用 yes/no 猜测。CLI 只接受语义明确的“已成功 / 未成功 / 先停止”选项，并映射 exact
`ResolveUnknownToolOutcome` 或安全退出；不自动重试 effect。

### Multiple candidates

启动展示有界编号、用户 outcome 和状态；用户选择编号后，CLI 构造 exact `SelectGoal` 并重新装配所选
session。不能按时间、文件名或“最近”猜测。

## 9. 默认输出合同

默认 REPL 只输出：

- workspace 与实际 provider identity；
- 模型的回答或最小澄清问题；
- 用户必须决定的外发、文件修改或 recovery 边界；
- 恢复到的任务摘要；
- `VERIFIED_DONE` 的结果和证据摘要，或准确 blocker/失败类别。

默认不输出 `Model request in progress`、raw tool-call ID、checkpoint path、request digest、revision、内部 enum、
完整绝对 state path 或重复事件。安全交互可在内部继续使用 exact identity；只是 UI 不要求用户手工处理它。

外部可控文本继续 literal render，控制字符/ANSI/bidi 必须可见转义。错误不得包含 credential、header、请求
正文、私有路径内容或完整 system prompt。

## 10. 三条 reference journey

### J1 — Ask / discuss

在空目录中无参数启动，完成一次 disclosure 后询问简单问题，再进行开放式讨论。两次交互均没有 Goal、文件
tool 或伪造完成状态；输出没有内部协议指令。

### J2 — Discussion to artifact

用户先讨论一个模糊想法，Agent 不提前建 Goal。用户随后明确“把结论写成 `notes/idea.md`”，Runtime 先建立
Goal，再按当前 workspace policy 请求必要 approval、写入、read-back，并以 evidence 进入
`VERIFIED_DONE`。普通进度阶段不需要用户输入“继续”。

### J3 — Existing workspace task and restart

在已有文件目录中，用户要求只修改一个明确目标文件。Agent 先检查必要上下文，不修改无关文件；effect 前
中断后，重启恢复同一 Goal；effect 结果未知时要求用户分类而不重放；最终验证目标文件且其他 sentinel 文件
digest 不变。

## 11. Definition of Done

013 只有同时满足以下条件才完成：

1. 新旧架构门证明唯一 Runtime/ContextManager/ToolRuntime/Provider 边界未漂移。
2. profile 的 no-secret、owner-only、no-follow、strict schema、atomic write 和 precedence 测试通过。
3. `first-agent` 无参数在 empty/existing workspace 的 reference journeys 全部通过。
4. 日常 happy path 不要求复制 digest/ID，不要求 mode selection，不出现阶段性“继续”指令。
5. disclosure 前 send count 为零；拒绝、配置漂移和 credential 缺失 fail closed。
6. 文件任务仍满足 Goal-before-effect、approval binding、read-back evidence 和 false-done mutation oracle。
7. restart/multiple-candidate/unknown-effect journey 通过且 effect 不重复。
8. 真实 production adapter E3 的全部 claims 为 true，并保存 secret-free receipt。
9. `git diff --check`、Ruff、完整 pytest、materialized tree gate 均有未截断 exit `0`。
10. fresh independent reviewer 没有 unresolved correctness/security/architecture P0/P1/P2。

任何 fake/mock、阶段性测试、模型自报、timeout、截断输出或缺 exit code 都不能替代上述证据。

## 12. 验证状态（2026-08-03）

条款 1-10 已闭合。真实
Provider E3 在官方 DeepSeek OpenAI-compatible beta endpoint（`deepseek-v4-flash`、strict tools）
连续三次未插桩通过，12/12 claims 全 `true`。证据见
`docs/acceptance/013_EVERYDAY_WORKSPACE_AGENT_E3.md` §7 与
`docs/implementation/013_EXECUTION_LOG.md`。第一轮 fresh review 的三项 finding 已 Red → Green；
随后重算 104-entry seal，六项完整门 Green（源码与 materialized tree 均 `730 passed`），fresh
Standards 与 Spec re-review 无 unresolved P0/P1/P2。
