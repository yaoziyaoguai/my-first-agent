# Oracle Browser Transcript

Conversation: https://chatgpt.com/c/6aa56966-0d9c-83eb-8ecf-45ed8f41e98d

## Prompt

你是 First Agent 的外部首席架构师、产品负责人和严格 QA。请审计附件所代表的当前工作树，目标不是增加功能数量，而是判断它是否已经足够稳定、简单、好用，能承担个人日常工作；并找出达到该目标前真正必须完成的最小工作。背景事实：项目坚持 AgentRuntime.run_turn 是唯一 production model/tool loop，ContextManager 独占上下文选择，ToolRuntime 独占工具执行，Scheduler 只能是 external caller；Memory、Skill、MCP、SubAgent 只能作为 governed tools；Browser/Sandbox 所有副作用必须经过 policy、approval、EXECUTING checkpoint 与 result checkpoint。最新改动把 019 收轻：manual reconcile 不再需要 macOS wake，cold wake 必须显式 wake enable，任务批准不安装登录项，普通 preflight 只读。完整测试为 3398 passed、3 skipped，但 installed first-agent-schedule 的 trusted host composition 仍未接通，真实后台模型任务尚未证明。请允许内部多视角并行分析，但不要修改文件或提出无边界重写。遇到证据不足必须标记，不得把测试夹具当真实产品能力；不懂时优先调研 Codex、DeepSeek Harness、Claude Code、Pi Agent 等官方文档或 primary source 的普遍做法并给出处。请按以下结构输出：A. executive verdict：当前是否足够日常使用，适合哪些任务、不适合哪些；B. capability evidence matrix：每项能力的 implemented、usable、真实证据、主要摩擦；C. 按 P0 阻断日常使用、P1 重要、P2 可后置、DO NOT BUILD 分类的问题，每项给源码或附件证据、用户影响、最小修复、验收标准；D. 分别列出哪些做重了、做轻了、做复杂了、做得太简单，并明确建议删减还是补齐；E. 只选择最多三个最高价值 vertical slices，按依赖顺序给执行资料包，要求不增加第二套 Runtime/model/tool loop、不借平台或扩展绕过授权、不读取 Pi 或其他产品凭据；F. 产品力评价：首次使用、反馈速度、失败恢复、普通人操作负担、结果正确性；G. 最后严格输出 codex_execution_advice YAML，包含 implementation_plan、non_goals、optional_subagents、verification。

## Answer

## A. Executive verdict

**结论：尚不能认定为“可以放心承担个人日常工作的通用 Agent”；可以用于人工监督下、有界、可复核的 workspace 任务。最值得做的是补齐交付闭环，而不是继续增加能力。**

具体裁决：

| 使用范围                                      | 当前裁决           | 理由                                                              |
| ----------------------------------------- | -------------- | --------------------------------------------------------------- |
| 技术用户监督下的文件整理、需求综合、小范围代码修改                 | **有条件可用**      | 已有真实模型任务的正向记录，但主要来自源码装配和外部 headless 驱动，不是当前安装制品的完整用户旅程          |
| 直接采用其统计报告、把 `VERIFIED_DONE` 理解为“数字和结论均正确” | **不通过**        | 已记录 CSV 报告计数错误，同时通过完成门禁；尚无当前版本闭合证据                              |
| 安装后直接创建、执行和管理持久调度任务                       | **不通过**        | installed `first-agent-schedule` 固定传入 `core=None`，不是用户补一份配置就能解决 |
| 退出交互程序后的真实模型后台工作                          | **不通过**        | 入口未贯通；既有真实基础设施旅程中的安全终态，不等于模型完成用户目标                              |
| 任意网站操作、第三方 MCP、任意 Skill、并发子代理             | **不在当前可用性承诺内** | 现有证据是受限能力、局部测试或特定 fixture，不能外推                                  |

前三类任务的实测记录分别是：统计报告存在错误，代码修改和冲突需求综合通过独立核对；调度入口的固定不可用也有源码与实测双重支持。 

**最小交付线应分两层：先让前台日常工作可靠，再决定是否交付调度。不能因为 Scheduler 没接通，就否定文件任务的已有价值；也不能因为文件任务能跑，就宣布后台 Agent 可用。**

### 审计证据边界

本次附件包含 **20 个文件摘录**，不是完整可执行仓库。核心 `runtime/loop.py`、状态 reducer、完整 ToolRuntime、Provider adapter、019 host 实现和测试主体没有全部附上。因此：

* `3398 passed、3 skipped` 是附件报告的最新全量结果，**不是我本轮重跑的结果**。
* 我对附件中的函数做了四组**内存级、只读局部探针**，确认了流式原样输出、跨轮重复显示、调度失败退出码、SubAgent 静默截断问题；依赖对象使用桩，不冒充完整产品端到端复现。
* 没有修改文件，没有调用真实模型，没有注册系统任务，没有读取 Pi 或其他产品凭据。

架构方面，`build_composition` 确实显式构造一个 ToolRuntime、一个 ContextManager 和一个 AgentRuntime。这支持当前所有权设计，但不能替代未附核心代码的全仓安全证明。

---

## B. Capability evidence matrix

以下所有能力的仓库正式声明仍按 **`implemented-candidate`** 处理。这里的 *usable* 指任务层面的可用性，不等同于 `accepted`；历史 seal 漂移也不意味着实现突然不存在。

| 能力                             | Implemented                | Usable             | 真实证据及边界                                                                                  | 主要摩擦                                                  |
| ------------------------------ | -------------------------- | ------------------ | ---------------------------------------------------------------------------------------- | ----------------------------------------------------- |
| Runtime、文件、workspace/history   | 已装配；核心实现未全部附上              | **有条件**            | 真实模型完成过代码修改、需求综合；最新真实入口的工具选择仍主要是 deterministic Provider 证据。                              | 完成门禁与语义正确性之间仍有距离                                      |
| 安装、setup、默认启动、`/new`           | 有                          | **技术用户可用**         | 安装入口、真实 CLI 第二个 checkpoint、TUI 启动与 Pilot `/new` 有记录。                                     | 当前模型 smoke 借用了测试期临时凭据注入，未证明 First Agent 自有配置的完整首次使用路径 |
| ContextManager、自动压缩、归档         | 文档声明与装配存在                  | **长会话未充分证明**       | 确定性预算、archive-before-reduction、摘要不升权的合同明确；附件没有当前长时间真实使用记录。                               | 不应把压缩合同测试当成长期语义保真证明                                   |
| HTTP Provider                  | 两类 adapter 已接入             | **依具体路线而定**        | 9 月 10 日真实 Anthropic-compatible 多步任务；9 月 12 日 OpenAI-compatible `glm-5.3` 仅单轮无工具 smoke。  | reasoning、strict schema、工具集合的组合限制；两条路线不能互相代证          |
| `local_process`                | 有                          | **有界使用**           | 历史真实 E3；当前注册和审批路径存在。                                                                     | Artifact digest 操作负担；不等于任意 shell 或整机隔离                |
| Sandbox / `shell_exec`         | 有                          | **macOS 有界可用**     | 最新记录包含真实 Seatbelt、workspace/read-only、子孙进程 TCP 阻断测试。                                     | 真实宿主执行不等于真实模型任务闭环；不同执行工具的完成证据需核对                      |
| Web / Tavily                   | 有                          | **当前环境未验证**        | 历史真实任务记录存在；最新 dogfood 未配置 Web。                                                           | 每次 exact query / URL batch 审批；当前路线未跑完整研究任务            |
| Browser                        | 可选装配与治理实现存在                | **本轮不能认定可用**       | 当前环境缺少 browser extra，没有真实 Chromium 页面任务。                                                 | 安装依赖、takeover/restart、strict open-object 组合；不是个人浏览器   |
| Memory / owner preference      | 有                          | **受限可用**           | 真实 CLI store create/load、跨 `/new` 复用有记录；词汇召回和审批写入边界明确。                                   | 更新/遗忘需要的 CAS 元数据是否对模型完整可见，仍需补证                        |
| Skill                          | 只读与 declared entrypoint 均有 | **只读较清楚；执行受限**     | 合成 catalog、真实 Seatbelt executable Skill 测试；不等于真实工作 Skill 的安装交付。                          | 执行参数开放 object 与 strict 冲突；无必要扩展 registry/lifecycle    |
| MCP                            | 有                          | **仅已测 fixture 范围** | 本地 stdio bridge、session/integration 测试；没有当前第三方服务任务。                                      | 显式 catalog、逐次审批、latch recovery；“MCP ready”不是服务可用证明    |
| SubAgent                       | 有                          | **有界辅助，不应依赖完整性**   | 最新只证明注册及 runner/integration 测试，没有真实远程 child；本轮确认返回正文会先被静默截到 2000 字符。                     | 可能丢掉审查结论尾部，却仍作为成功文本交给 parent                          |
| CLI / TUI 反馈与恢复                | 有                          | **基础操作可用，交互仍有缺口**  | CLI/TUI 共用动作与权威状态；最新流式实现存在，但本轮发现 renderer 缺陷。                                            | 非流式路线无有效进度；流式跨轮重复；特殊审批仍暴露 SHA                         |
| 019 portable core / macOS host | 控制面有；安装装配不完整               | **默认安装入口不可用**      | 注入 core 的测试与真实宿主历史记录存在；当前入口固定不可用，后台模型目标未证明。                                              | 从创建、批准、执行到结果打开、人工恢复的产品路径未闭合                           |

---

## C. 问题分级与最小修复

**P0 在这里表示相应日常使用承诺的阻断，不表示已经证明存在 Kernel 越权漏洞。** 对源码确认、历史实测和待补证问题分别标注，不把它们混在一起。

### P0：阻断相应日常使用承诺

### F1．统计结果可能错误，却以已验证完成结束

**证据：附件实测，尚无闭合记录。**

`2026-09-10-product-baseline-tasks.md:24–28` 记录：12 组 errors 中 3 组错误，结论也引用了错误数字，但三个任务均通过 `VERIFIED_DONE`。记录同时说明统计是模型心算，没有执行计算程序。不能据此断言今天每次都会复现，但当前没有证据证明问题已解决。 

**用户影响：** 对数据处理任务，用户仍必须自行重算，Agent 节约的工作可能被复核成本抵消。

**最小修复：** 对明确的统计、计算和验证任务，要求通过现有 governed process 工具完成计算，并把实际验证纳入既有 Goal criteria；展示“验证了什么”，而不是泛称结果正确。没有数值验证时，可以说明文件已生成，不能暗示数值已经核验。

这不是要求建设通用“语义真理引擎”，也不是只追加一句 system prompt。需要同时验证模型选择了计算工具，以及最终完成判断消费了对应证据。

**验收：** 独立 oracle 核对 count、errors、P95 和正文引用；加入修改输入、故意写错报告、仅创建文件、运行无关成功命令等反例。错误或无关证据不能获得“数值已验证”的用户投影。

### F2．019 installed 入口结构性不可用

**证据：源码确认，附件真实入口复现。**

`pyproject.toml:39` 指向 `agent.automation.cli:main`，而该 `main():236–237` 固定调用 `run_cli(core=None)`。因此 `list`、`reconcile` 等默认路径不可能因用户补配置而自然接通。 

**用户影响：** 日常调度功能目前实际上不可交付。这个问题仅阻断调度，不阻断所有前台文件任务。

**最小修复：** 在现有安装入口接入固定、受信任的 host composition：读取 owner 管理的非秘密配置，静态绑定已有 repository、management、reconcile 和 Runtime ports。缺配置仍 fail closed；不得改用 `main.run_schedule` 的旧参数化路径冒充 019 接通。

**验收：** 在仓库外 non-editable 安装环境中，从零完成：

`create → preview → human approve → manual reconcile → 查看真实产物`

重复 reconciliation 不增加模型请求或 effect。`list/show` 不需要先具备可调用模型、浏览器或 Sandbox 的全部运行条件。

---

### P1：重要，直接影响可信交互和可操作性

### F3．CLI 流式文本绕过安全显示边界

**证据：源码确认＋本轮函数级复现。**

`agent/cli/render.py:40–53` 把 delta 原文直接交给输出函数；最终回答则经过 `terminal_text`。`main.py:1091–1094` 的真实装配把 delta writer 接到直接 `print`。本轮向 renderer 输入 ESC、回车和 bidi 字符，确认它们原样抵达输出 sink。 

**证据限制：** 未附完整 delta 铸造链，因此这里证明的是 renderer 边界缺陷，**不是已经证明真实 Provider 可完成终端攻击或工具越权**。

**用户影响：** 增量文本与最终文本遵循不同显示规则，可能破坏终端呈现和审批信息的可读性。

**最小修复：** 在最后输出边界，对 delta 使用与最终文本一致的 literal escaping。原始文本用于协议归一化、结果比较；转义只作用于显示，不修改 checkpoint 或审批内容。

**验收：** CLI 真实输出捕获中不出现允许显示范围之外的控制字符；恶意文本跨 delta 分片仍安全；最终结果、审批 binding、事件故障下的 durable state 完全不变。

### F4．流式状态跨轮累积；非流式路线仍缺有效反馈

**证据：源码确认＋本轮局部复现。**

`_streamed_answer` 只在构造时初始化，后续持续拼接；最终结果与整个累积文本比较。本轮连续模拟两次正常回答，输出是：

`first answer → second answer → second answer`

此外，renderer 明确忽略 `MODEL_PROGRESS`、`TOOL_REQUESTED`、`TOOL_RESULT`，因此仅有 SSE 并没有解决所有路线、尤其工具执行期间的等待反馈。 

**用户影响：** 重复答案、失败后的残留文本，以及看起来没有响应的等待。

**最小修复：** 将流式显示状态按明确的生成/响应生命周期隔离，不按 conversation 永久累积。先提供真实的“处理中／等待模型”及耗时反馈；已有工具事件只有在确认实时性后才展示。**本轮不必为此新增 OpenAI SSE adapter，也不需要即时抢占工具。**

**验收：** 连续两轮、同一 action 多次模型请求、tool-only response、断流后恢复、`/new`、事件重复/丢失均无跨轮污染；提交后立即出现本地反馈，不编造百分比或完成状态。

### F5．Artifact confirmation 把密码学校验工作交给用户

**证据：当前交互源码确认；新文件死路属于附件记录的待复核场景。**

`agent/cli/app.py:214–224` 在存在 artifact requirement 时拒绝普通 `yes`，要求用户手工输入 SHA。附件还记录了新文件场景的预期 digest 难题，但当次统计任务并未实际触发该 criterion，不能称作已复现的通用新建文件阻断。 

**用户影响：** 普通用户必须理解 SHA、文件时点和内部 criterion；容易混淆旧文件摘要、待写入内容摘要、未来输出摘要。

**最小修复：** 先核对 requirement 的准确语义。对已存在且已 read-back 的产物，或当前精确写入 proposal，由 Runtime 生成可信预览及摘要绑定，用户确认内容，CLI 只提交现有 typed approval。不能使用空摘要、自动接受模型自报摘要，或直接删除 criterion。

对于无法提前确定字节的未来输出，采用现有能力可表达的“生成后 read-back／验证”顺序；不能伪造一个执行前就已知的输出 digest。

**验收：** 新建、修改、验证已有文件三条旅程都不要求用户抄 SHA；审批后文件或 proposal 漂移必须拒绝；前端不能自行补权或直接读取文件绕开工具治理。

### F6．“一条真实模型路线能完成日常工作”仍未被当前安装制品证明

**证据：附件实测范围明确；strict 组合限制明确。**

9 月 12 日真实模型仅完成无工具 smoke，First Agent 默认 profile 当时尚未配置。与此同时，strict 模式下，只要工具列表含 Skill entrypoint、Browser 等开放 object，请求即可能在发送前失败，和模型是否调用该工具无关。 

**用户影响：** 单独看各模块都“ready”，组合后却不能完成一次普通任务。

**最小修复：** 只选用户长期使用的一条现有 Provider 路线，用 First Agent 自有 profile 和显式提供的凭据跑完整安装旅程。对明确不兼容的工具 schema，在宣布可用之前给出具体诊断。

不得静默关闭 strict、隐藏用户显式启用的工具、切换模型或读取其他产品配置来“修好”。

**验收：** 安装入口完成多轮、读文件、批准写入、工具结果后续请求、失败恢复、`/new`。另设组合负例，明确指出哪个 schema 不兼容，且网络请求和 effect 均为零。

### F7．019 的管理协议没有转化为可操作的用户流程

**证据：源码确认；退出码已有本轮函数级复现。**

三个独立表现仍在：

* create/update 和生命周期动作暴露 definition JSON、expected/next token、preview digest。
* `open` 只输出 handoff 对象，没有在该 CLI 分支打开恢复会话。
* `run_cli` 除两个 code 外均返回 0。本轮确认 `wake_enable_failed`、`wake_not_enabled`、`wake_state_unknown`、`activation_conflict` 等也返回 0。

**用户影响：** 用户既要充当协议客户端，又可能把失败当成功；遇到需要人工处理的 occurrence，只拿到内部标识。

**最小修复：** 用薄 CLI 适配现有动作：内部获取 CAS token，展示任务、时间、目录、模型、权限、期限和结果位置，绑定用户实际看见的预览。`open` 经可信 identity 解析进入现有 CLI/TUI；定义显式退出码映射，不按字符串猜成功。

还必须说明：当前 source 是批准时捕获的快照，写入发生在 019-owned occurrence workspace，不能让用户误以为在持续读取最新源目录或修改原工作区。 

**验收：** 无需输入 JSON/token/digest 即可完成管理；冲突不重绑旧批准；失败/未知/需人工与成功可区分；打开恢复会话本身零模型、零工具调用，后续操作仍进入唯一 Runtime。

---

### P2：可后置，但应留有明确验收项

| 问题                      | 证据与用户影响                                                                                       | 最小修复                                                  | 验收                                                       |
| ----------------------- | --------------------------------------------------------------------------------------------- | ----------------------------------------------------- | -------------------------------------------------------- |
| **SubAgent 静默截断**       | `tools.py:101–102` 直接切片到 2000 字符；本轮 2025 字符测试丢失尾部结论且没有截断标记。                                   | 使用已有 bounded result/error 机制显式标记不完整，不静默补发 child 请求    | parent 能识别报告不完整；尾部结论被截断时不能当完整审查结论                        |
| **Memory 更新前置条件可获取性疑点** | update/forget 要完整 revision、digest，但 `memory_get` 只返回正文；ContextSource 是否另行提供完整元数据未附，不能断言全链必坏。  | 先做正常工具路径复现；确有缺口时让现有 get 返回必要元数据，不让模型读 store 文件        | 跨会话 remember→get→update→forget 不依赖测试预填内部 revision/digest |
| **离线查看恢复信息受凭据检查阻断**     | `main.py:961–969` 在打开 session 前检查 credential，缺失即退出。                                           | 复用现有只读状态投影，使查看 pending/结果不依赖可调用模型；不注入 FakeProvider 兜底 | 无 key 可查看已保存状态，不能因此发模型请求或推进 effect                       |
| **状态文档与当前实现不同步**        | 架构文档仍把 streaming 列为未交付边界，而当前记录已有 SSE；历史/current 信息混排。                                         | 只同步当前入口、限制和证据日期，不重写历史 receipt                         | 用户能从一个 current 页面区分 implemented、当前实测、未验证；不自动 promotion   |

### DO NOT BUILD

| 不应建设                                                          | 依据与风险                                         | 本轮处置／验收                                            |
| ------------------------------------------------------------- | --------------------------------------------- | -------------------------------------------------- |
| 第二套 Runtime、模型循环、授权 controller，或让 Scheduler 直接调 Provider/Tool | 现有静态装配已经具备唯一所有者；另起执行路径会绕开恢复和审批。               | 不建设；所有新增执行链最终仍落到既有 `run_turn` 和 ToolRuntime        |
| 为修 019 引入 Redis、微服务、跨平台 host、另一套会话 timer                      | 当前缺口是安装装配和用户闭环，不是控制协议不足。                      | 复用现有 core/host；不新增 daemon 或第二份调度状态                 |
| 为能力数量扩充向量 Memory、并发 swarm、任意 Skill/MCP、个人浏览器接管、凭据导入           | 已有能力范围是有意限定，当前缺少的是真实任务证据。                     | 没有具体 reference task 就不扩；绝不读取 Pi、Codex、Claude 等产品凭据 |
| 为获得漂亮状态反复重绑全部历史 promotion                                     | 当前 candidate 与任务可用性是不同问题，旧 acceptance 不能直接继承。 | 先补当前任务证据；只有明确要改变正式声明时才执行对应晋级流程                     |

---

## D. 哪些做重了、做轻了、做复杂了、做得太简单

| 判断        | 具体对象                                                                | 建议                                                         |
| --------- | ------------------------------------------------------------------- | ---------------------------------------------------------- |
| **做重了**   | 在 installed 真实任务未贯通前，持续投入完整 cold-wake、portable qualification、交付封存流程 | **收缩后续工作范围，不拆掉已实现安全协议。** 暂停新 host、新平台、新 promotion 轮次       |
| **做轻了**   | 当前 wheel＋自有配置＋真实模型＋用户操作＋独立产物核对                                      | **补齐。** 这是最需要投入的部分，不需要新基础设施                                |
| **做复杂了**  | 用户直接处理 JSON、CAS token、preview digest、artifact SHA；模型被要求维护大量内部控制细节   | **删减外露复杂度，保留内部约束。** 薄 UI 翻译用户意图，Runtime 继续拥有合法性和 authority |
| **做得太简单** | 用安全终态代替目标完成、用文件回执代替数字正确、用输出切片代替完整性声明、用 exit 0 表示管理请求结束              | **补齐结果语义。** 成功、失败、未知、仅已生成、已完成哪些检查，需要可区分                    |

这些判断针对工程范围和产品体验，**没有 CPU、内存、耗电基准，不能据此说程序“运行很重”**。附件自身也明确了这个证据限制。

### 应当保留的“复杂度”

CAS、exact approval、EXECUTING/result checkpoint、未知结果不自动重试、workspace 隔离、进程清理都直接保护真实风险，不应作为“简化产品”的删除对象。单 child、词汇 Memory、显式静态 composition 也并不天然落后。 

`main.py` 的会话重装配循环不是第二套 model/tool loop；operator-only 浏览器 profile 管理也已有明确边界，不应为了形式统一再造 Runtime action 系统。 

### 官方做法的可借鉴部分

DeepSeek Harness 的 session-local scheduling 在 Agent 空闲后排入普通 follow-up，并明确 durable dispatch 不代表模型成功；Claude Code 的定时提示也在当前 turn 结束后执行，忙时不会为每个错过周期堆积执行。这支持“调度只负责投递，执行继续走既有入口”，**不要求 First Agent 照搬其插件系统或新增会话 timer**。([GitHub][1])

Codex 官方 automations 链接当前指向的 Scheduled tasks 文档，仍建议先手动验证提示、模型、工具和结果，再调度；本地项目任务要求机器及应用运行，并继承 sandbox 边界。这支持先闭合 manual journey，而不是先追求最强无人值守模式。([OpenAI Developers][2])

Pi 官方明确其默认没有内建权限限制系统，因此不能用“Pi 更轻”论证删除 First Agent 的审批与隔离。Apple 的文档也区分了进程定时启动和机器睡眠/关机行为；一个可选 LaunchAgent 合理，但不能宣传成电脑关机或睡眠期间照常完成任务。([GitHub][3])

---

## E. 最多三个最高价值 vertical slices

**依赖顺序：S1 → S2 → S3。前台日常使用的最低线是 S1＋S2；S3 是交付持久调度时才必须通过的附加线。**

### S1．正常安装后，连续完成前台任务，显示安全且清楚

**用户故事：** 我用 First Agent 自己的配置启动，完成一个小任务，开始下一项；等待、失败、重启时都知道发生了什么。

**工作边界：** `main.py`、CLI renderer、共享交互合同、对应 Provider 组合检查和测试。先修 F3/F4，验证 F6；不新增 Provider 家族、插件 registry、即时工具抢占。

**执行顺序：** 固定一条显式 Provider 配置；为四类显示生命周期建立 Named Red；修复最后输出边界和按响应隔离的显示状态；添加真实的等待反馈；最后从仓库外安装 wheel 走正常入口。

**必须交付的证据：** 安装 origin、脱敏配置、真实终端操作记录、两个连续任务与 `/new`、重启后 pending 投影、拒绝审批后的零 effect。无源码路径注入，无其他产品凭据。

**停止条件：** 用户仍需猜测“是不是卡住”，回答仍重复，或失败恢复借助内部 Python API 才能继续，则 S1 不通过。

### S2．完成一项工作，并明确证明结果检查到了哪里

**用户故事：** 我要求统计报告、代码修复或需求综合；Agent 给我可复核结果，而不是仅证明写出了文件。

**工作边界：** 现有 Goal criteria、process/file/read-back 证据消费、artifact approval 投影、三类真实任务测试。对应 F1/F5。

先核对完整 evidence owner 源码，再判断 `local_process` 与 Sandbox 回执是否存在真正的语义错配。019 的 `_U2BProvider` 阻断可能来自 fixture 要求，也可能来自生产证据消费；**先用 Named Red 分辨，不能直接放开后台 `local_process`，也不能把任何 sandbox 成功都视为满足任意 process criterion。**

**验收任务：** 统计报告、已有代码 bug、冲突需求综合，各做三个独立输入变体。统计由独立脚本核对；代码由真实测试和输入文件完整性核对；知识任务逐项对照原文和未决事项。oracle 不能复用模型生成的答案或产品内部“通过”结论。

**必须交付的证据：** 输入与产物 identity、实际工具调用、正常人工审批、验证结果、完成状态投影，以及故意错误产物被拒绝的负例。

**停止条件：** 错误数字仍被视为已核验、无关 exit 0 能充当验证、用户仍需提供未知未来文件的 SHA，则 S2 不通过。九次成功只能支持这组有界任务，不应包装成通用可靠性统计。

### S3．安装后的 019 能完成一次真实 manual occurrence，并能打开结果和恢复

**用户故事：** 我创建并批准一个任务，手动触发一次，看见正确产物；重复触发不会重做，遇到问题能从产品入口处理。

**工作边界：** 现有 `agent.automation.cli`、management、固定 macOS host composition、已有 reconcile/caller、结果与 recovery handoff。对应 F2/F7。

先接只读管理，再接 manual reconcile；CLI 负责输入与投影，Controller 负责定义状态，Runtime 负责模型和工具状态。显示 source 快照时点和结果所在的 owned workspace，不能暗示原目录自动同步。

**验收闭环：** 无 wake 的 create/preview/approve；真实模型完成一次有独立 oracle 的产物任务；重复投递零新增调用；`open` 进入现有人工恢复；冲突、未知、失败返回可区分状态。正常 `list/show/preflight` 不安装登录项、不发模型请求。

**冷启动边界：** 只有 manual 通过、用户另行授权系统注册及模型调用、并且具备显式受信任的凭据交付方式后，才验证既有 cold wake。届时必须是“交互程序退出后，真实模型完成任务”，不能以 launchd 启动成功或 `blocked_terminal` 代替。缺少条件时保持 `not_run`，**不要为完成这一切片顺手建设新的凭据管理平台**。

---

## F. 产品力评价

| 维度          | 当前评价                         | 达到日常可用的关键变化                                            |
| ----------- | ---------------------------- | ------------------------------------------------------ |
| **首次使用**    | 技术用户可以操作，普通用户负担偏高            | 一条真实验证过的自有配置路径；只启用必要能力；不依赖临时驱动或别的产品配置                  |
| **反馈速度**    | 两条 Provider 路线体验不一致，工具期间反馈不足 | 安全的增量输出、按响应隔离状态、立即出现的真实等待反馈                            |
| **失败恢复**    | 安全设计扎实，用户闭环不完整               | 保留 unknown 不重试；把 pending、核对依据和下一步呈现清楚；调度 `open` 真正接入恢复 |
| **普通人操作负担** | 基础写入审批尚可，高级路径仍像开发接口          | 不抄 SHA、token、digest；CAS 和 exact binding 全部留在内部         |
| **结果正确性**   | 是当前最明显的产品短板                  | 从“流程有回执”推进到“明确任务要求得到对应验证”，同时诚实列出未验证部分                  |

性能上不能用旧记录冒充当前基准：9 月 10 日三任务的耗时是约 32–59 秒，不能当作当前 SSE 或 `glm-5.3` 的延迟数据。审批记录中的“1 次”也主要指 write/edit，driver 自动处理了 disclosure，**不等于真实用户总共只被打扰一次**。 

长任务也仍应限制承诺：Everyday 累计 model/tool/token 上限为 `None`，现有停滞熔断只针对连续相同指纹；这不能直接推出长任务的总消耗已受充分约束。本轮先测调用数、累计耗时、审批次数和人工救场，不恢复“小次数就强迫 `/resume`”的旧负担，也不新增计费平台。 

**最终产品判断：核心治理值得保留，能力数量已经足够开始日常使用验证。下一阶段的目标应该是“同一安装制品，真实模型，普通入口，正确结果，失败可处理”，而不是再增加一个模块。**

---

## G. codex_execution_advice

```yaml
codex_execution_advice:
  verdict: "CHANGES_REQUIRED_FOR_TRUSTED_DAILY_USE"
  foreground_status: "有界任务可监督使用；尚未通过可信日常交付线"
  scheduling_status: "installed 入口不可用；真实后台模型任务未证明"
  current_claim: "implemented-candidate"

  audit_basis:
    attachment: "attachments-bundle.txt"
    attachment_sha256: "c6c5b0b4bf1237e1b4aa47c0826a16337a9c2b8dcfbb53d89f70a90d401946ec"
    scope: "20 个文件摘录，不是完整可执行仓库"
    reported_full_suite: "3398 passed, 3 skipped"
    full_suite_rerun_by_this_audit: false
    files_modified_by_this_audit: false
    real_provider_called_by_this_audit: false
    operating_system_tasks_registered_by_this_audit: false
    local_probes:
      - "CLI delta 控制字符原样抵达输出 sink"
      - "连续两轮回答导致第二轮重复输出"
      - "多个调度失败或未知结果映射为退出码 0"
      - "SubAgent 超长正文被静默截断为 2000 字符"
    probe_limitation: "内存级函数探针使用依赖桩，不是生产端到端证明"

  implementation_plan:
    - id: "S1"
      title: "安全且可理解的 installed 前台任务闭环"
      depends_on: []
      priority: "first"
      addresses:
        - "F3"
        - "F4"
        - "F6"
      primary_files:
        - "main.py"
        - "agent/cli/render.py"
        - "agent/cli/app.py"
        - "agent/cli/actions.py"
      inspect_before_edit:
        - "完整 MODEL_TEXT_DELTA 铸造链、响应 identity 和事件生命周期"
        - "Provider schema 投影及当前选定路线的配置合同"
        - "相关 CLI、TUI、Provider 和安装测试"
      steps:
        - "固定一条用户显式配置的现有 Provider 路线，仅使用 First Agent 自有配置"
        - "为 raw delta、连续回答、多模型响应、断流与事件故障增加 Named Red"
        - "在显示边界统一转义；原始协议内容与权威结果保持不变"
        - "按明确响应生命周期隔离流式缓存和去重状态"
        - "提供真实等待反馈，不新增执行循环或伪进度"
        - "对不兼容的已启用工具 schema 提前报告具体原因，不自动降级"
        - "从仓库外 non-editable wheel 安装运行正常 CLI"
      acceptance:
        - "控制字符不得原样进入终端显示"
        - "两轮回答各显示一次，多次模型调用之间无文本污染"
        - "事件丢失、重复、断流不改变 checkpoint 或审批 authority"
        - "setup 后完成真实多轮和工具任务，不依赖源码导入或内部驱动代操作"
        - "拒绝审批后零 effect；/new 与重启保留旧任务证据"
      stop_rule: "本切片未通过前不扩大 Provider 或扩展能力范围"

    - id: "S2"
      title: "可复核结果与无需手抄摘要的审批"
      depends_on:
        - "S1"
      priority: "second"
      addresses:
        - "F1"
        - "F5"
      primary_files:
        - "main.py"
        - "agent/cli/actions.py"
        - "agent/cli/app.py"
        - "agent/cli/render.py"
      inspect_before_edit:
        - "Goal criteria admission、completion evidence derivation 和 Runtime views"
        - "artifact_confirmation_requirement 的输入、旧内容和输出语义"
        - "local_process 与 sandbox receipt 的真实生产消费者"
        - "019 U2B fixture 是否自行引入工具名称相关的完成要求"
      steps:
        - "建立统计、代码修改、冲突需求综合三个独立 ground-truth 任务"
        - "统计和验证目标通过既有 governed process 路径执行"
        - "完成判断消费与任务、输入和产物匹配的验证证据"
        - "只有 Named Red 证明生产错配时才修改 process receipt 消费逻辑"
        - "从可信 proposal 或 durable read-back 生成审批投影，用户确认内容而非抄 SHA"
        - "展示已经完成的检查及未验证范围，不扩大 VERIFIED_DONE 的语义承诺"
      acceptance:
        - "三个任务各三个独立输入变体通过外部 oracle"
        - "统计正文和结构化结果一致，错误报告不得显示为数值已核验"
        - "无关成功命令、仅文件存在、过期证据不能替代所需验证"
        - "新建、修改、验证已有文件均不要求用户预知未来输出摘要"
        - "审批后内容漂移继续 fail closed"
        - "Sandbox 回执不能用于批准范围之外的目标或命令"
      stop_rule: "不建设通用语义判真引擎，不用 prompt-only 修复冒充证据闭环"

    - id: "S3"
      title: "019 installed manual occurrence 与人工恢复闭环"
      depends_on:
        - "S2"
      priority: "third"
      required_for: "持久调度交付；不是前台日常使用的前置条件"
      addresses:
        - "F2"
        - "F7"
      primary_files:
        - "agent/automation/cli.py"
        - "agent/automation/management.py"
        - "agent/automation/composition.py"
        - "agent/automation_hosts/macos_cli.py"
      inspect_before_edit:
        - "未附完整源码的 host factory、repository、reconcile 和 Runtime handoff"
        - "既有 owner root、host profile 和 bounded background authority 合同"
        - "全部 management result code 及其调用方"
      steps:
        - "把 installed main 接到固定的 trusted host composition"
        - "先支持无需调用模型的只读管理，再接 manual reconcile"
        - "用薄 CLI 生成内部 CAS 字段并绑定用户实际看到的预览"
        - "明确 source 快照时点、执行目录、预算、期限和结果位置"
        - "为成功、失败、未知、冲突和需人工结果建立显式退出码映射"
        - "通过可信 identity 将 open handoff 接入现有 CLI 或 TUI"
        - "从正常安装入口完成一次真实模型产物任务并检查重复投递"
      acceptance:
        - "从零创建和批准 manual task 不需要 wake qualification"
        - "批准任务不安装 LaunchAgent"
        - "list、show 和普通 preflight 不发模型请求、不注册后台项"
        - "用户无需输入 definition JSON、CAS token 或 preview digest"
        - "真实模型产物通过独立 oracle"
        - "重复 delivery 或 occurrence 不增加 Provider 请求或 effect"
        - "open 初始投影零模型和零工具调用，后续操作仍经过唯一 Runtime"
        - "未知结果不能通过 cancel、重建任务或重复 reconcile 自动重试"
      cold_wake:
        default: "deferred"
        prerequisites:
          - "manual 闭环已通过"
          - "用户另行授权系统注册和真实模型调用"
          - "已有显式受信任且非借用其他产品的凭据交付方式"
        acceptance: "交互程序退出后，由既有 host 启动真实模型并完成同一类可核对任务"
        forbidden_substitute: "launchd 启动成功、fixture 或 blocked_terminal"
        missing_prerequisite_result: "not_run，不得宣称后台可用"

  non_goals:
    - "不增加第二套 AgentRuntime、model/tool loop、controller 或 durable cursor"
    - "不引入 service locator、动态 registry、兼容 fallback 或休眠 feature flag"
    - "不以 main.run_schedule 旧路径替代 019 trusted composition"
    - "不让 Scheduler、Browser、Sandbox 或扩展自行授权"
    - "不新增 Redis、微服务、跨平台 host 或会话 timer"
    - "不读取或复用 Pi、Codex、Claude 等其他产品凭据和私有会话"
    - "不以关闭 strict、隐藏工具、切换 Provider 或开启 full access 掩盖缺陷"
    - "不扩展向量 Memory、并发 SubAgent、任意 MCP、Skill registry 或个人浏览器"
    - "不自动重绑历史 promotion，不修改历史 acceptance 结论"

  optional_subagents:
    enabled_by_default: false
    purpose: "研发阶段的只读独立复核，不扩展产品 SubAgent 能力"
    max_parallel: 2
    roles:
      - "CLI 显示与审批 binding 审查"
      - "独立产物 oracle 与反例审查"
      - "019 装配、幂等和恢复边界审查"
    restrictions:
      - "不得修改同一工作树"
      - "不得读取真实凭据、用户私有运行数据或注册系统任务"
      - "不得把局部测试结论升级为真实产品能力"
      - "主执行者统一核验结论并按切片验收"

  verification:
    architecture:
      - "AgentRuntime.run_turn 保持唯一 production model/tool loop"
      - "ContextManager 独占上下文选择"
      - "ToolRuntime 独占工具执行"
      - "每次 effect 仍经过 policy、approval 覆盖验证、EXECUTING 和 result checkpoint"
      - "definition 批准不能替代每次执行的 authority 覆盖检查"
      - "未知结果不自动重试，不自动解除 recovery"
    regression_commands:
      - ".venv/bin/ruff check ."
      - ".venv/bin/python -m pytest -q -rx"
      - "git diff --check"
    regression_policy:
      - "先 Named Red，再最小 Green，再相关 fault matrix，最后完整回归"
      - "保留已有测试，不通过删除断言、改成 skip 或放宽超时掩盖失败"
      - "记录 skipped 原因；已有清理超时问题需区分环境抖动与产品缺陷"
    installed_boundary:
      - "记录实际 working-tree identity、wheel hash、解释器和依赖版本"
      - "在仓库外 non-editable 安装，核验入口和 import origin"
      - "禁止 PYTHONPATH 源码污染和测试专用 host factory 代替生产装配"
    real_task_gate:
      - "真实 Provider 仅在用户显式配置并授权有界调用后运行"
      - "凭据仅通过 First Agent 明确指定的认证入口注入，不写日志或 checkpoint"
      - "记录模型请求、effect、disclosure、审批、耗时和人工救场次数"
      - "产物 oracle 独立于模型答案及产品完成状态"
      - "缺少配置、授权或平台条件时标记 not_run 或 blocked，不能算通过"
    claim_policy:
      - "安全拒绝不是任务成功"
      - "真实宿主执行不是模型任务成功"
      - "当前局部探针不是完整产品端到端证明"
      - "通过产品切片不会自动把 implemented-candidate 晋级为 accepted"
```

[1]: https://raw.githubusercontent.com/deepseek-ai/deepseek-harness/master/docs/user/guide/schedule.md "https://raw.githubusercontent.com/deepseek-ai/deepseek-harness/master/docs/user/guide/schedule.md"
[2]: https://developers.openai.com/codex/app/automations "https://developers.openai.com/codex/app/automations"
[3]: https://github.com/earendil-works/pi "https://github.com/earendil-works/pi"
