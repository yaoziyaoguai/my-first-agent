---
title: 016 First Agent 1.0 - Everyday Product Experience Contract
type: architecture
date: 2026-08-17
authority: 016-design
status: frozen
---

# 016 First Agent 1.0 — 日常产品体验合同

## 1. 为什么是 016

012—015 已分别证明 First Agent 拥有可信连续性、当前 workspace 知识、公开 Web 研究和受治理的本机
程序执行。现在缺少的不是另一项底层能力，而是一个整体产品结论：一个愿意使用终端、并能取得兼容
模型服务配置与凭据的本机用户，能否从安装开始，只通过 `first-agent` 和自然语言稳定完成真实任务。

这里的“普通用户”是“不需要理解 First Agent 内部架构的产品用户”，不是“不需要终端和模型服务配置
的普通消费者”。016 不承诺托管模型账号、图形安装器或代替用户取得第三方 API 凭据。

016 是一次产品收束，不是新 Agent framework。它把已经交付的能力组合成一条默认路径，删除普通使用
中的内部概念泄漏，并用完整用户旅程验收它们能否一起工作。

完成 016 后，First Agent 的准确描述是：

> 一个从当前目录开始工作的 local-first 通用个人 Agent。它能直接聊天，也能围绕明确结果持续研究、
> 创建或修改文件、运行受治理的本机程序并验证结果；只有可能改变用户意图、权限边界、重大成本、
> 敏感数据处理或不可逆结果时才询问用户。

这条“只在必要时询问”不依赖模型自行判断权限。模型只判断是否缺少会改变任务方向的信息；Provider/Web
外发、文件 effect 和 process spawn 是否必须询问，继续由 deterministic policy 和 exact approval hard gate
决定，模型无权跳过。

“通用”表示同一个入口可处理不同类型的日常问题，不表示它已经能控制整台电脑、任意访问外部服务，
或在没有授权的情况下自主扩大能力。

## 2. 016 的用户结果

用户只需要理解四件事：

1. 在希望 First Agent 工作的目录中启动 `first-agent`。
2. 像和一个助手说话一样描述问题或结果。
3. 当 First Agent 准备外发数据、写文件或运行程序时，阅读准确说明并决定是否允许。
4. 退出后可以重新启动；未完成任务会从可信状态继续，不需要重述，也不需要反复输入“继续”。

典型体验：

```text
$ cd ~/work/trip-plan
$ first-agent
First Agent
目录: ~/work/trip-plan
模型: deepseek-v4-flash
能力: 文件、历史、本机程序；网页搜索已启用
状态: 没有未完成任务

> 查一下上海周末天气和适合室内活动的地方，整理到 plan.md
我需要把这次查询发送给 Tavily，并把相关内容发送给当前模型。允许吗？ [yes/no]
...
我准备写入 plan.md。允许吗？ [yes/no]
...
已完成：plan.md 已写入并重新读取验证。来源 4 个。
```

默认界面不得要求用户理解 `GoalFrame`、checkpoint、receipt、digest、request ID、criterion ID、MCP
或 provider protocol。内部合同继续存在，但只能通过普通语言投影。

## 3. 冻结范围

### 3.1 In scope

1. **可复现安装**：在干净的受支持 Python 环境中按 README 安装后，真实产生可执行的
   `first-agent` 命令；版本、help 和首次启动可用。
2. **一次配置、日常无参数启动**：保留 non-secret profile 与环境变量凭据边界；让交互式 setup、
   非交互 setup 和首次缺配置提示都给出唯一、准确的下一步。
3. **可读启动状态**：只显示当前目录、模型、默认可用能力、缺失的可选能力和恢复状态；正常启动不刷
   内部 ID 或协议事件。
4. **已有能力协作**：对话、Goal、文件、history、workspace search、Tavily Web、来源、owner
   preference、`local_process` 和恢复在同一个 Runtime 路径中协作。
5. **普通交互安全边界**：日常任务用自然语言，disclosure/approval/recovery 使用当前提示中的短回答，
   pause/resume/cancel 可以使用稳定的短命令；任何路径都不要求复制内部 ID。
6. **端到端产品验收**：从已安装命令启动真实进程，使用真实模型完成
   `docs/acceptance/016_FIRST_AGENT_1_0_E3.md` 冻结的用户旅程。
7. **面向用户的 README**：首页先解释“它是什么、怎么装、怎么开始、能做什么、何时会问”，架构与
   高级 capability 配置移到后面或独立文档。

### 3.2 Out of scope

- 新建第二套模型/tool loop、planner/executor loop、CodingLoop，或在 CLI/Provider 中另建
  mode router。Runtime 内的 typed intent gate 属于唯一 `AgentRuntime.run_turn` 的入口状态，
  不是第二条执行路径。
- OS sandbox、container、multi-root、任意 shell、浏览器/桌面自动化、邮件、日历或整机控制。
- 后台 daemon、ambient monitoring、观察 First Agent 以外的本机活动。
- 自动修改自身代码、自动生成或晋级 Skill、自动改变安全策略或自主产品优化。
- 新的多 Agent 编排、动态 tool registry、service locator 或 capability marketplace。
- 为了 1.0 重写 Runtime Kernel、Memory、Skill、MCP、SubAgent、Scheduler 或 TUI。
- 把 Graphify、Understand Anything、Claude Code 或 Codex 变成产品运行时能力。

这些项目不是永久否定，而是不能借 016 的“易用性”名义偷偷进入范围。

## 4. 一条默认产品路径

### 4.1 安装

README 只推荐一条经过 clean-environment gate 验证的最小安装路径，且第一条安装命令必须与验收使用的
命令一致。源码开发安装或其他安装方式可以存在，但不属于 016 的默认支持承诺。

冻结的默认安装路径是：

```bash
python -m pip wheel --no-deps --wheel-dir dist .
python -m pip install dist/first_agent-1.0.0-py3-none-any.whl
```

E3 必须从 sealed materialized source 在独立 build copy 中执行同一条 wheel 命令，再把该 exact wheel 安装到
clean venv；每轮 receipt 绑定实际安装的 wheel digest。

安装完成必须满足：

- `first-agent --version` 显示与 distribution metadata 一致的唯一版本；016 candidate 的目标版本为
  `1.0.0`，但在全部 promotion gates 通过前，README/status 仍不得宣称它已交付。
- `first-agent --help` 成功，且帮助首页先展示普通使用与 setup；高级 flags 分组展示。
- `first-agent` 命令来自已安装 distribution，而不是依赖仓库根目录恰好可导入 `main.py`。
- base 安装不强制安装 TUI、MCP、Skill 等可选依赖。
- 命令不存在、Python 版本不支持或依赖不完整时，安装检查给出准确原因，不能把 import traceback 当作
  产品提示。

016 不承诺发布 PyPI、系统安装器或自动升级；只承诺仓库文档声明的本地安装路径真实可用。

### 4.2 Setup

`first-agent setup` 是唯一模型配置入口：

- 无参数时进入简短的 guided setup，逐项询问模型服务类型、model、base URL 和 credential 环境变量名；
  README 面向第一次使用者首先推荐这条路径。
- 完整 flags 保留给自动化和明确知道配置的高级用户；两种入口写入同一个 closed-schema
  `ProviderProfileV1`。四字段 guided flow 不静默开启 `request_path` 或 `strict_tools`；两者保持高级显式 opt-in。
- setup 只验证并保存 non-secret 配置，不读取、回显或保存 key value，也不进行测试调用。
- 完成时给出唯一下一步：如何让指定环境变量在当前 shell 可用，然后运行 `first-agent`。
- 配置缺失或无效时指向具体字段，不输出 Python exception 类型或内部 schema 名。

`first-agent setup-web` 仍是可选的 Tavily 配置入口。未配置 Web 时，聊天、文件、历史和本机执行照常
可用；默认启动只说明“网页搜索未启用”，不能把它渲染为产品故障。已有 Web profile 但对应 credential
环境变量缺失时，Web 标记为“暂不可用”并给出变量名，本地能力仍可启动；只有确实需要 Web 的任务才停在
这个 blocker。启动不为显示状态而做网络健康检查，“已启用”只表示本地配置与 credential 已就绪。

`first-agent setup-web` 的无参数路径是面向用户的默认 flow：先用普通语言说明固定 Tavily destination、
公开查询/URL 会交给第三方处理、默认 credential 环境变量名和 non-secret profile 内容，再在当前提示确认
是否启用。完成后只显示需要设置的环境变量名与唯一下一步；完整 flags 只用于自动化。它不读取 key value，
也不以测试调用代替用户确认。

Memory、Skill、MCP、SubAgent、Scheduler 和 TUI 保持高级、显式 opt-in。016 不把它们塞进首次 setup，
也不因为未配置它们而显示警告。

### 4.3 启动

日常入口是：

```bash
cd <workspace>
first-agent
```

默认 workspace 是启动时的当前 real directory。启动成功后最多显示以下用户事实：

- 当前目录；
- 当前模型的可读名称；
- 当前可用的日常能力：文件/历史、本机程序，以及 Web 是未启用、已就绪还是暂不可用；
- 是新对话、恢复唯一未完成任务，还是需要从多个可读候选中选择；
- 当前需要用户处理的真实阻塞。

默认不得显示绝对 state-root、digest、checkpoint 文件、内部枚举、tool catalog、schema version 或事件流。
高级诊断可以保留精确接口，但不能污染普通启动。

缺失模型 profile、credential 环境变量或 workspace 无效时，必须在任何 Provider send、tool effect 或新
checkpoint 之前退出，并给出一条可执行的修复动作。不存在 FakeProvider fallback。

## 5. 一个自然语言入口的行为合同

### 5.0 Runtime intent gate

每个没有 active Goal 的新用户 action，必须先在唯一 `AgentRuntime.run_turn` 中完成一次 typed intent
decision。用户不选择 mode，也看不到内部分类。decision 只能基于 trusted conversation facts（以最新
trusted user message 作为当前 action authority）、Runtime-owned workspace binding 和既有 durable control
state；在 decision 被接受前，ContextManager 不收集
workspace/history/Web context source，也不暴露任何 product tool。外部内容因此不能反向影响本 action 是问答
还是 Goal，更不能铸造新的任务 authority。

入口只允许四种结果：

1. `direct_response`：无需检索即可完整回答，当前 run 立即结束，不创建 Goal。
2. `begin_answer`：问题需要 workspace/history/Web 等只读 grounding；Runtime 将当前 run 持久化为
   `ANSWERING`，随后才收集 context source 并仅暴露 read-only product tools。同一 action 一旦进入
   `ANSWERING`，`goal_proposal` 就不可再用；检索内容只能支持回答，不能把问答升级为任务 authority。
3. `goal_proposal`：用户要求一个需要持续推进、effect、验证或恢复的可验收结果；Runtime 先铸造 durable
   Goal，再重建上下文并开放该 Goal 下受治理的工具。
4. `clarification_request`：只有缺失边界可能改变用户意图或 authority 时才询问；该路径零 product tool、
   零 effect。可由本机只读能力发现的信息不得直接询问用户，模型应先选择 `begin_answer`；明确任务中
   未知的具体文件位置由 Goal 建立后的只读发现或 deferred filesystem criterion 处理。

新的用户 action 会清除上一轮 transient `ANSWERING`/`CLARIFYING` 交互选择，再重新经过 intent gate。
Provider 只把 typed control 解码成 `ModelResponse`；CLI 只渲染结果。两者都不能自行分类、创建 Goal 或开放
工具。这是唯一 Runtime loop 的入口相位，不是额外模型调用、第二套 loop 或用户可见 mode。

Runtime 可以对 trusted user action 使用一个保守、单向的 **explicit non-prose veto**：只有句首语法已经明确
要求创建/写入/修改/运行/校验等非文字结果时，初始 control schema 才不广告 `direct_response` 与
`begin_answer`。该 veto 不创建 Goal、不调用第二个模型，也不把模糊表达升级成任务；同一个模型仍必须提交
closed `goal_proposal`，或在真实意图/authority 边界提交 `clarification_request`。诸如“如何写 report.md？”
的解释性问题仍保留普通问答路径。这样模型方差不能把明确 effect outcome 静默降级成一段完成宣称。

### 5.1 简单问题和讨论

- 知识问答、解释、比较和头脑风暴默认直接回答。
- 不创建 durable Goal，不调用 effectful tool，不要求用户选择 chat/task/code mode。
- 需要事实 grounding 时先由 Runtime 接受 `begin_answer`，再开放只读来源；完成回答或收到下一条用户消息
  后退出 `ANSWERING`。只读结果不能让同一 action 改走 `goal_proposal`。
- 入口使用同一个“纯文字结果测试”：如果 First Agent 只返回回答文字，不写入、不修改、不运行，也不执行
  用户要求的其他动作，就不能完整满足任一明确 outcome，那么该 action 是 Goal。只有回答文字本身就是全部
  outcome 时，才允许 `direct_response` 或 `begin_answer`。读取、Web 研究、写 artifact 和校验组合在一起时，
  grounding 只是完成任务的手段，整个 action 仍是一个 Goal。
- 只有用户明确要求生成、保存、修改、调查或执行一个可验收结果时，才进入 durable task。
- strict tool-call Provider 也必须通过专用 `direct_response` control 返回普通答案；它只在无 active Goal 时
  可见。active Goal 不能用一段 prose 绕过 evidence、blocker 或 completion 状态机。

### 5.2 任务

- First Agent 根据用户说出的 outcome 建立一个 Goal；用户不手写 plan、criterion 或内部 ID。
- 明确任务在任何 workspace/history/Web product read 之前建立 Goal。即使用户说“看看这个项目再修改”，
  “看看”也是任务内的第一步，不是把整个 action 归类成普通问答。
- 模型只能提出 outcome、scope、target、criterion 和可选 next-step hint 等语义草案；Goal ID、workspace binding、
  authority snapshot、revision、status 与 timestamps 全部由 Runtime 根据 trusted action 铸造，不能由模型
  自报。
- Goal 已存在时，Runtime 必须把当前 Goal ID、revision 和 mandatory completion evidence refs 作为精确枚举
  写入本轮 reserved control schema；correction pending 时，嵌套 GoalDelta 的 Goal ID 与 expected revision 也
  必须由同一可信状态约束。模型可以选择合法 control，但不能猜测、改写或重新铸造这些 Runtime-owned 值；
  portable 与 strict Provider 共用这一份 schema，不增加 classifier、模型调用或第二条 workflow。
- compatible endpoint 若在 `goal_delta_proposal` 外层冗余回声嵌套 GoalDelta 的 `goal_id` 与 revision，shared
  decoder 只可在两字段同时存在、类型正确并与嵌套 binding 逐字一致时将其规范化；partial、stale、forged
  或其他未知字段仍 fail closed，随后同一个 Runtime reducer 继续校验当前 state。这只是 wire
  compatibility，不把 Goal ownership 下放给 Provider adapter。
- portable compatible endpoint 的 `completion_claim` 若同时省略 Runtime-owned `goal_id` 与 `goal_revision`，
  shared provider-neutral normalizer 只可从生成该 response 的同一 immutable `ContextPack.control_schema` 中，
  读取当前允许 `completion_claim` 的 exact singleton enum 并恢复这对 routing metadata。partial omission、
  supplied stale/forged binding、ambiguous schema、strict `payload` wrapper、其他缺失或额外字段仍 fail closed；
  `goal_progress`、`blocked_claim` 不采用此例外，随后同一个 Runtime reducer 仍须校验当前 durable state。
- 明确要求 public/Web/current/latest/online 信息的任务，Goal draft 必须显式带
  `requires_public_web=true`；Runtime 将它铸造成 mandatory `WEB_SOURCE_RECEIPT` criterion。在本 Goal
  尚无成功、非截断的公开 Web receipt 时，所有 write/process effect 都 fail closed，workspace/history
  来源或模型常识不能替代公开来源。作为安全下界，Runtime 还会从 authoritative user fact 中闭合集合的
  明确 public/Web/current/latest/online 措辞重算该义务；模型的 `false` 不能取消用户明说的公开来源要求。
  这包括 `latest/current release/package/version/information` 等直接要求当前外部事实的英文措辞。
- 明确要求 run/test/build/validate/check/execute 本地命令的任务，Goal draft 必须显式带
  `requires_local_process=true`；Runtime 将它铸造成 mandatory `TOOL_RECEIPT` criterion。process approval
  把该义务绑定到 exact executable/argv/cwd，只有成功的 Kernel process receipt 能满足；文件写入、模型文字
  或未准入的 proposal 都不能替代。该字段与 `requires_public_web` 一样属于同一次 Goal 语义提案，不增加
  模型调用或第二套 loop。Runtime 同样从 authoritative user fact 的明确 run/test/build/validate/check/execute
  措辞重算安全下界，包括 `call/invoke local_process`，以及 imperative `run/execute` 后直接跟 bare、绝对路径
  或 `./` entrypoint；模型的 `false` 不能取消用户明说的本地执行要求。
- 这两个 boolean 与模型自报的同类 Web/process criterion 都只是语义提案，不能扩大用户 authority。若
  authoritative user fact 没有明确要求相应 Web 或本地执行 outcome，Runtime 必须丢弃模型自增的该类
  obligation；模型的 `true` 不能让纯文件任务多出外发或 process 验收条件。
- 用户要求运行现有 test/validator 时，workspace discovery 只能用现有只读文件工具，不能浪费
  `local_process` authority 去执行 `list/find/cat` 或解释器包装的探查命令；发现入口后直接请求 exact
  executable 与实际所需 argv。用户拒绝无关 discovery candidate 不证明目标 validator 受阻，模型必须重查并
  提出 exact candidate。
- 需要先阅读现有项目才能知道具体修改文件时，draft 最多允许一个 deferred `FILESYSTEM_DIGEST`
  criterion。它不授权模糊路径；Runtime 只在用户批准第一笔具体 file write/edit 时，将同一 criterion ID
  原子绑定到 exact workspace-relative path。第二个 deferred criterion、未批准路径或非文件 effect 都不能
  完成绑定。
- draft 中非空的 `FILESYSTEM_DIGEST.artifact_path` 必须逐字匹配一个 Goal target；测试/校验结果由
  `requires_local_process` 铸造的 `TOOL_RECEIPT` 证明，不能发明一个不属于 target 的测试输出文件来形成
  无法满足的 artifact approval。即使模型同时把自己发明的 `test-results`/`output`/`log`/`check-*` 路径加入
  targets，只要 authoritative user fact 没有点名该路径，Runtime 仍在 Goal admission 阶段拒绝它。
- 只在缺失信息可能改变 outcome、target、scope、authority、重大成本、敏感数据处理或不可逆结果时询问。
- 无 effect 的只读 workspace/history 检索、构建上下文和展示已批准任务的进度可以直接推进；Provider/Web
  外发、文件 write/edit 和 process spawn 始终停在现有 deterministic disclosure/approval 边界。不得用模型
  对“安全、明显、可逆”的主观判断绕过 hard gate。
- 阶段性进度不是停止条件；不能以“我接下来会……”结束 active Goal，也不能要求用户输入“继续”。
- `blocked_claim` 必须由与当前未满足义务相关的 concrete product attempt 支撑；成功的 workspace/history
  只读观察不能替代尚未尝试的 Runtime-owned Web/process 义务，也不能把它们伪装成 blocker。对应工具仍可用时，
  Runtime 拒绝该 claim，并只提示当前可安全推进的义务工具。
- 同样地，未准入的 filesystem criterion 在当前写入工具仍可用时保持 pending；correction 后对尚未创建的新
  target 做失败预读，不能授权 blocked。若闭合 evidence oracle 明确只缺可用 `read_file` read-back 或既有
  research manifest 的可修复重建步骤，Runtime 必须拒绝 blocked 并投影那个具体工具；只有安全工具实际产生
  durable blocker 且没有已知 evidence repair 时才可接受终态 blocked。
- 健康任务不设累计 model/tool/token 次数上限；但现有连续 semantic no-progress watchdog 保持为 16 次。
  真实 tool result、新 evidence 或策略实质变化会重置计数；达到阈值时任务以普通语言暂停，显示最后可信
  进展、当前 blocker 和 `/resume`/`/cancel`，停止后不得继续 send/effect 或伪装完成。
- Provider invalid-response/control repair allowance 也只约束连续坏响应；一个已广告并 durable 接受的 tool
  batch 或合法 GoalProgress 是新的 trusted observation，必须重置该 allowance。没有中间合法响应的连续
  malformed/control 错误仍按既有 hard limit fail closed，不能靠重复无效输出无限延长。
- 完成必须由现有 Runtime evidence gate 证明；模型自己的“已完成”不是完成证据。
- 一次成功的最终 `read_file` read-back 若已经让同一个 `ClosedEvidenceRegistry` 能重算全部 mandatory
  criteria，Runtime 可以从当前 trusted Goal 确定性复制 exact evidence refs，并按既有 evidence →
  completion claim → `VERIFIED_DONE` checkpoint 顺序收尾，不再增加一次只为抄写 refs 的 Provider send。
  该收尾不铸造新意图或 authority，也不是第二套 loop；process/Web/effect result 仍走后续模型控制，任一
  Web/process/filesystem obligation 尚未准入或尚不可证明时必须零状态变化，继续唯一 model/tool loop。
  模型 prose 或模型自报 completion 仍不能绕过 evidence gate。

### 5.3 修改意图

用户在任务中补充或纠正要求时：

- 仍通过普通文本进入同一 Runtime；
- 旧 next step、completion claim 与不再适用的 evidence binding 失效；
- 已经发生的外部 effect 作为历史事实保留，不能伪装成未发生；
- 未确认结果的 effect 进入既有 unknown-outcome recovery，不能自动重放。
- correction 发生在一个尚未执行完的并行 tool-call batch 中时，Runtime 先为每个未执行 call 写入明确的
  non-execution result，再接受新意图；这样重启后的 Provider wire 仍保持每个 tool call 都有配对结果，且旧
  effect 不会被误执行。
- 从 correction fact 持久化到新 `GoalDelta` 被接受之间，ContextManager 不暴露任何 product tool，控制面只
  接受 `goal_delta_proposal`，ToolRuntime 也独立拒绝臆造调用。若 correction 改变 targets，同一 delta 必须
  原子更新所有 concrete filesystem criteria；只改 target、不改 criterion 的半修订不会消费旧 authority。
- `GoalDelta` 没有取消 Runtime lower-bound 的 typed authority：模型不得删除由 authoritative user fact
  铸造的 mandatory Web/process obligation。用户若不再需要这类根本要求，必须通过 `/cancel` 结束旧 Goal，
  再以新的自然语言任务建立新 Goal；不能由模型在 correction 中静默降权。
- 只改变 artifact path 且 outcome/scope 不变时，仍适用的成功 Web admission 可以复用而不重放请求；改变
  outcome 或 scope 时，旧 Web admission 必须失效，但 Runtime-owned Web obligation 继续保持 pending，直到
  新 outcome 的公开来源重新满足它。process admission 不跨 correction 复用。

### 5.4 停止与恢复

- `/exit`、EOF 或空闲 Ctrl-C 只退出界面，不取消 durable Goal。
- 用户通过当前产品提示或稳定的 `/pause`、`/resume`、`/cancel` 明确控制任务；这些命令不要求内部 ID。
- 重启时唯一安全候选自动恢复；多个候选以 outcome 摘要选择；危险或未知状态准确停下。
- 恢复不得重复已确认 Provider send、文件 effect、Web request 或 process spawn。
- OpenAI-compatible wire 在真正发送前必须重验 tool-call/result 因果链；裁剪或恢复若留下 orphan、重复 batch
  ID、或未闭合 call，adapter 本地 fail closed 且不得把无效历史发给 Provider。这个检查只保护既有单一
  Runtime 的协议边界，不创建恢复 loop 或兼容 fallback。

## 6. 已有能力如何成为一个产品

016 不新增 capability owner，只冻结以下组合关系：

| 用户需要 | 权威实现 | 默认体验 |
|---|---|---|
| 回答与任务推进 | `AgentRuntime.run_turn` | 同一自然语言入口 |
| 上下文选择 | `ContextManager` | 自动选择必要的历史和来源，不倾倒全部数据 |
| 当前目录理解 | workspace search/read tools | 只读操作无需 effect approval |
| 创建和修改文件 | file tools + policy | exact preview 后批准，写后 read-back |
| 公开 Web 研究 | Tavily Web tools | 已 setup 才可用；exact query/URL batch 每次批准 |
| 执行构建、测试等 | `local_process` | exact argv/cwd/风险批准；不是 shell 或 sandbox |
| 记住通过它发生的事 | workspace history + owner preference | 不观察其他应用或用户活动 |
| 退出后继续 | canonical checkpoint/recovery | 不要求复制 ID，不重放 effect |

一个真实任务可以依次使用多项能力，但始终只有一个 Runtime loop、一个 canonical Goal 和一套 checkpoint。
CLI 不得根据任务类型建立平行流程。

`web_fetch` 只能接收当前 run 中成功 `web_search` 明确产生、且尚未尝试的 search-snippet `source_ref`。
ContextManager 把这组 ref 作为动态 closed enum 暴露给模型；citation ref、已抽取内容 ref、历史 ref 或模型
臆造 ref 均不可成为 fetch authority。过长页面在 Web adapter 边界截断，并记录原文 digest 与 truncation
事实；截断 receipt 不能证明研究完成。

Citation sidecar 也不是普通自由文本文件。`build_citation_manifest` 只接受当前 Goal 的 non-sidecar artifact
target 和 Runtime 当前可引用的、非截断 source refs；Runtime 记录其 canonical ToolResult 的 exact content
digest。后续 `write_file` 只有在 path 是 Goal 的 `.citations.json` target、内容逐字节匹配本 run/本 Goal
revision 刚生成的 canonical manifest、且 manifest 指向允许的 artifact target 时才可进入 file approval。
`edit_file` 或模型手写/改写的 JSON 在副作用前拒绝。来源 occurrence receipt 可以在同一 Goal correction 后
继续证明“曾观察”，但 citation authority 必须按当前 Goal revision 重新构建，二者不能混用。

## 7. 安全与授权体验

016 不降低 012—015 已有安全边界。易用性只能改变表达，不能放宽权限。

- Provider disclosure 说明 destination、model 和将发送的数据类别；确认前 send count 为零。
- Web approval 显示 exact query 或 URL batch，并说明 Tavily 是第三方。
- 文件 approval 显示 exact workspace-relative path 和操作类型。
- process approval 先用普通语言说明“这个程序将以你的本机账号权限运行，不是 sandbox，可能访问该账号
  可访问的文件或网络”，再显示 exact executable、ordered argv 和 cwd；资源档案与环境策略用可读摘要
  表达，精确技术字段可以放在同一提示的 advanced detail，但不得被隐藏。
- 拒绝后 effect count 为零。若仍存在安全的只读路径，Agent 可以继续；否则说明准确 blocker。
- 拒绝只约束仍属于当前 Goal 的 exact action。correction 后旧 target 的 action，或已有 mandatory Web
  receipt 后模型提出的重复检索，不得把已可从 durable facts 完整证明的 Goal 终化为 `BLOCKED`；Runtime
  必须拒绝这种 false-blocked claim，并要求从当前 `trusted_goal` 重发 completion claim。
- 用户不批准“以后所有操作”，不批准模糊目录或命令模式。现有 exact binding/lease 规则保持权威。
- 凭据只由 composition root 从明确环境变量读取，不进入 profile、context、checkpoint、event、receipt、
  error 或默认输出。

## 8. 架构红线

016 的实现必须满足：

1. `AgentRuntime.run_turn` 继续是唯一 production model/tool loop 和 state progression owner。
2. setup/profile/startup 只为 composition root 提供 validated configuration；它们不能调用第二个模型做路由。
3. CLI/TUI/headless 只翻译 typed action、显示 projection、读取当前用户决定；不能自行推进 Goal。
4. Provider adapter 仍只做 `ContextPack -> ModelResponse`；不能执行工具、恢复任务或写产品状态。
5. `ContextManager` 独占模型上下文选择，`KernelToolRuntime` 独占 callable tool 执行。
6. Fake 与 real provider 通过依赖注入共享同一产品路径；不得新增“只为 E3 通过”的平行 workflow。
7. 016 所需改动优先落在 packaging、composition、CLI projection、README 和端到端 harness；没有明确 Red
   证据，不改 Runtime 核心合同。
8. 现有高级能力不能被自动扫描或隐式启用；每个新 authority 仍需未来里程碑单独批准。

## 9. 失败体验

以下状态必须可区分，且每个状态只给一个准确下一步：

- **未安装/命令不可用**：回到受支持安装命令。
- **未 setup**：运行 `first-agent setup`。
- **credential 环境变量缺失**：只显示变量名和设置方法，不显示或寻找 value。
- **Provider 不可达、认证失败、限流或协议不兼容**：active Goal 停在最后一个可信 checkpoint，状态为可
  恢复但未完成；不静默切换模型。既有 bounded transport retry 只能在 disclosure 与准确 outcome 边界内
  运行，仍失败时给出重新运行/恢复这一条动作，不能无限自旋或伪装完成。
- **Web 未配置或 credential 缺失**：普通能力继续，只有确实需要 Web 的任务说明如何启用或补齐变量。
- **Web 服务暂时不可达**：保留已有来源和 Goal；不要求 Web 的本地任务继续，需要 Web 才能满足的 outcome
  准确暂停并给出重试动作，不能用无来源猜测冒充研究完成。
- **用户拒绝 authority**：零 effect；尝试安全替代或说明无法继续的原因。
- **未知 effect 结果**：要求用户在当前语境判断 success/failed/stop，不自动重试。
- **多个恢复候选**：展示 outcome 摘要让用户选择，不显示内部 ID 为必填输入。

Python traceback 只能作为显式开发诊断，不得成为上述预期产品状态的默认界面。

## 10. 1.0 完成定义

016 只有在以下条件同时成立时才能从 `proposed-for-review` 晋级：

1. 本文和 016 E3 经用户审定后冻结，implementation plan 的每个需求都可追溯到二者。
2. clean install、version、lint、全量 tests 与 materialized-tree gates 全部 Green，输出完整且 exit code 明确。
3. 016 E3 的十二条用户旅程从已安装 `first-agent` 入口完成；Fake/Mock 不能替代真实模型/Web 场景。
4. 真实场景连续三轮全部通过，且没有用户“继续”、内部 ID copy 或未声明的 mode switch。
5. safety-critical claims 由 deterministic receipt/state/file/process/send-attempt oracle 判定，不依赖模型自评；
   model/Web attempt 在 adapter 调用 HTTP 前追加到 owner-only、payload-free ledger。
6. E3 receipt 必须绑定当前 delivery seal/overlay/verifier 与每轮 installed wheel digest，并保留 bounded exact
   disclosure/approval UX booleans；不保存 transcript 原文、prompt、credential 或用户内容。
7. fresh independent reviewer（未参与本轮实现、也不继承 executor 的通过结论）按 016 E3 的用户体验与
   架构检查项复核通过；发现的问题修复后重新跑相关 gates。
8. README 的产品声明不超过上述证据。

016 完成后仍不宣称 First Agent 已能接管整台电脑。它宣称的是更小但真实的结果：已有能力已经组成一个
目标用户可以安装、理解、信任、退出后继续使用的日常 Agent。

## 11. 016 之后如何选方向

016 完成后不预先承诺 017。先使用真实 dogfood 证据决定：

- 如果重复批准成为主要摩擦，设计更强隔离后再讨论 authority 扩大。
- 如果 current workspace 经常不足，再设计显式 multi-root scope。
- 如果网页只是读取不够，再独立设计浏览器/账号操作与凭据边界。
- 如果反复出现相同任务，再设计 reviewable learning/improvement，而不是允许 Agent 静默改自己。

这保证后续扩展来自真实使用缺口，而不是继续堆积尚未被普通用户使用的能力。
