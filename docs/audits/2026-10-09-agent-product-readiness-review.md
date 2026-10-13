# First Agent：产品可用性独立审计（2026-10-09）

> 范围：核对当前 coding agent 的修复，并判断成为好用的个人 Agent 产品还缺什么。
> 本轮是审计，不是实施授权。未改产品/测试代码，未 commit/push，未读取真实凭据或私有用户会话。
> 已完成 Oracle Web 第 5 档咨询及本地独立复核。Oracle 原文与交叉核对见文末。

## 1. 本地审计结论

它已经是有实际执行闭环的 Agent，不是只有聊天框的壳。模型能提出行动，经治理工具执行，
保持任务状态、恢复中断，并用 durable evidence 约束完成声明。当前瓶颈主要不是再增加工具种类，
而是把已有能力变成用户能看懂、控制、持续使用的产品。
不过最后的交叉复核还确认一个直接影响干活的缺陷：成功过的沙箱验证，在受治理文件写入后
再次请求，会被防重复机制挡住（CORE-01）。因此不能把当前版本直接判为稳定日用。

- 对懂终端、自己有模型 API 的个人用户：已有可用基础，可在声明的任务/平台边界内试用。
  不能因此声明所有日常任务稳定通过；TUI 仍有本轮复现的阻断问题。
- 对不熟悉内部实现的普通用户：尚不能称为顺畅交付的成品。配置、运行状态、
  退出/恢复、历史回看及交付摘要仍不连贯。
- 保留现有 single-loop / approval / checkpoint / evidence 架构。暂不增加第二套运行循环、
  任意桌面控制、常驻后台、并行 Agent 编排或通用插件市场。

这是一份当前源码审计，不是新 release promotion；不修改 CURRENT_CAPABILITY_STATUS 的 claim level。

## 2. 身份、方法与证据分层

- 工作树：main，HEAD `838cb2b66fbba674311d4d86fc7c4f4322fd8612`，缓存 origin/main ahead 7。
  大量既有 dirty/untracked 工作保留；没有把 HEAD 当作包含全部当前源码的发布身份。
- Graphify 现有图仅作定位，具体结论回到当前源码；未刷新，以免摄入 ignored/private 输入。
- Oracle 输入：16 个明确指定的公开源码/文档/合成测试文件，单 bundle 415.2 KB；
  发送前凭据形状检查未命中。未上传 .env、密钥、私有会话、真实用户日志或未跟踪根目录 tui/。
- 本轮不使用旧对话中的 API Key，不做真实产品 provider 调用。Oracle 外部咨询为本次明确授权。

| 证据 | 本次结果 | 能证明什么 / 不能证明什么 |
|---|---|---|
| 针对性 pytest | **143 passed，28.61s，exit 0** | 覆盖 R1、多项验收 driver、F2、F4、CLI/TUI、progress；含脚本 provider +真实 Runtime/Seatbelt 路径，不等于真实模型普遍成功率 |
| git diff --check | exit 0 | patch 格式；不是行为正确性 |
| Ruff | All checks passed，exit 0 | 静态规则；不是交互验收 |
| 本轮新增诊断探针 | UI、线程、F2 异常清理、CLI 接线、验证重跑等反例实测，详见下节 | 合成 UI/线程/Runtime/Seatbelt 诊断；没有启动真实 provider 或真实用户任务 |
| 执行者 10 月 4 日全量 | 报告 3673 passed / 1 skipped | 本次未独立重跑，不冒充本次全量通过 |
| 执行者 D01/D02/D06 | 报告 12/12/23 请求后 completed | 已有真实模型执行报告；本次未读取私有原始记录或重新付费运行 |
| 安装态 | **新 non-editable wheel 的窄离线 smoke 通过** | 公开 Python 源码 allowlist staging；源码目录外验证安装来源、version、setup、Fake CLI 对话与 TUI mount。依赖复用本机 system-site-packages，不是干净机器依赖解析、浏览器 extras 或真实模型安装验收 |

### 最近修复核对

| 项目 | 本次判断 |
|---|---|
| R1 多项验证闭合 | 有生产准入/结果接线；不同验证首次执行、重开及重复审批相关测试通过。但成功验证在写入后重新执行的生产路径仍被 dedup 阻断（CORE-01）；B03 不能证明这一正向闭环。保留既有修复，补窄缺口，不重做架构 |
| R2 runner→validator | 实际 run(fake provider) 贯通及反例通过，typed 终态与 evidence 重验路径存在。离线贯通不等于新增真实模型验收 |
| F2 / R3a browser cleanup | owner_shutdown 凭据/新 owner 补记、dead-worker 不重等、UNKNOWN 不签成功的聚焦测试通过。未独立重跑所有真实 Chromium 生命周期 |
| F4 archive/锁 | 容量轮转和真实 open→flock 置换重验测试通过；不是无限容量或旧版本混跑保证 |
| R3b journey deadline/异常清理 | **不能接受 B12/B13 的完整闭合结论**。当前实现只是 join 等待超时，F2 的 ExitStack 也未覆盖异常退出；下文有确定性反例 |
| Browser RFC3339 修复 | 源码及执行记录有修复；本次不把旧的 384 passed 计入 143 项之外另作新成绩 |

## 3. 已复现的具体问题

### CORE-01 / P1：修改之后，正常重新运行验证被误当重复请求

位置：`agent/runtime/loop.py:959` 的 successful_product_requests gate、`:1378` 的失效处理、
`:3950` 的持久事实重建，以及 `:4197` 的 _is_lease_governed_tool。

本次实际走生产 session + AgentRuntime +真实只读 Seatbelt +正常审批，得到以下事实顺序：

1. validate-a / sandbox_exec 成功执行。
2. validate-b / sandbox_exec 成功执行。
3. audit-write / write_file 成功执行，文件确实变更。
4. 以**新的 tool_call_id** `audit-validate-b-again-unique`、同一 check-b 参数重新请求验证：
   `executed=false / is_error=true / code=duplicate_product_request`，在 prepare/新审批之前已被拒绝。

这排除了“只是 fixture 重用了 call ID”的解释。_product_request_digest 只绑定工具名与 arguments；
写入后清除的只有 _MUTABLE_OBSERVATION_TOOLS 请求，sandbox_exec 不在其中。
租约工具豁免又仅识别 LOCAL_SAME_UID_PROCESS，不包含原生 sandbox execution authority。
同时 evidence 机制正确要求写后旧验证失效，因此两条规则组合成了“旧验证不能用了，新验证又不让跑”。

影响：正常的“先检查→修改→用同一命令复测”会被拦；用户/模型被迫改参数或换调用流程，
不符合自主收尾的产品承诺。这不是说所有首次测试或所有任务都失败。

最小修复：协调原有 dedup、验证证据失效与 lease 治理，允许输入状态已变后的合法重新验证；
仍由同一 Runtime/ToolRuntime 重新走必要的 policy、审批、执行前 checkpoint 与结果记录。
不要全局关闭 dedup，不允许重放未知副作用，不引入第二套执行 loop。

验收：真实正向旅程中，成功验证→实际受治理写入→相同命令/新请求身份→真实再次执行→
旧证据不能充数、新证据支持完成；checkpoint 重开后仍成立。
另保留 unchanged 输入的停滞约束、exact action 重放去重、unknown recovery 和失效授权负例。

B03 的证据校正：原测试最终仅断言未 VERIFIED_DONE。本次展开其 facts 发现第一次 A/B 均执行，
写入也执行，但写后 B 被 duplicate_product_request 拒绝，最终 evidence_records 为空；
因此它不能独立证明“复测已正确执行但旧证据因写入而被拒绝”的完整因果。应补断言，不据此推翻所有 R1 修复。

### UI-01 / P1：TUI 退出超时后，worker 已返回仍无法正常退出

位置：`agent/tui/app.py:474` 的 request_close、
`:493` 的 _on_close_deadline，以及 `:386` 的 _refresh 退出条件。

- 用户在活跃任务中按 Ctrl-Q。默认等待 30 秒后若 worker 未返回，shutdown_blocked 变为 True。
- worker 后来安全返回时，没有把这个阻塞状态解除。_refresh 退出要求 not shutdown_blocked，
  request_close 又直接拒绝 blocked 状态，输入和其它正常动作也被禁用。
- 本次用现有 _runtime_blocking fixture + Textual Pilot，把同一 deadline 参数缩短到 0.05 秒。
  释放 provider 后观测：is_active=False、shutdown_blocked=True、closing_requested=True、
  app_running=True、input_disabled=True，再按 Ctrl-Q 仍活着。
- 屏幕先显示 paused，之后显示 completed，而不是清楚的退出/收尾状态。

影响：普通的长模型等待就可能把界面带入“任务已经返回，但用户仍要强制关掉程序”的状态。
这是本轮优先级最高的真实产品缺陷。

最小修复：区分“现在尚不能收尾”和“永久关闭失败”；worker 终止且权威快照成功重载后，
允许安全完成退出/重新选择动作。不得用超时即强杀未知副作用的方式取巧。

验收：deadline 前后、worker 成功/失败返回、重复退出、unknown effect 均有测试；
worker 仍活跃时不伪报已退出，worker 已收口时不能永久卡死。扩展现有
test_pilot_close_deadline_violation_is_shutdown_blocked_without_force_exit，
不能只在测试末尾 app.exit() 掩盖恢复路径。

### UI-02 / P2：查看来源会清空尚未发送的草稿

位置：`agent/tui/app.py:363` 的 _refresh 无条件 `msg_input.value = ""`；
`:779` 的 action_toggle_source_refs 调用该刷新。

实测：输入“尚未发送的用户草稿”，按 F2，输入框变成空字符串；没有提交模型或执行工具。

最小修复：仅在成功消费本次输入后清空对应草稿；只读来源切换/状态重绘不应改输入值。
验收：F2、状态重绘、审批来回和错误刷新都保留未提交内容；不能误把旧已提交文本当新输入发送。

### UI-03 / P2：TUI 不同轮次的流式文本串在一起

位置：`agent/tui/app.py:230` 仅 mount 初始化 _streamed_answer；
`:237` drain 不按 conversation/run/revision/causation 划分文本。

实测：不同 run_id 的两个 MODEL_TEXT_DELTA 中间执行 _refresh，第二次显示为：
`· 生成中 · 第一轮旧回答第二轮新回答`。

这属于展示错误，不是 checkpoint 丢失或跨用户数据泄漏。
CLI 已有 stream_identity 隔离，可复用其语义而不另建业务状态 owner。

验收：连续两轮、同轮多个模型响应、迟到/重复事件、最终快照校正均不混段。
advisory 事件不能改变 Goal 或完成结论。

### UI-04 / P2：TUI 新鲜终态的交付摘要被覆盖

位置：`agent/tui/render.py` 的 project 本来调用 delivery_summary_message；
`agent/tui/app.py:295` 又用 result.message 替换整个 projection.main_text，只补回 verification_scope。

实测：同一 VERIFIED_DONE 快照挂载时可见：
“Verified delivery / Targets / Required evidence 1/1 / Durable task permissions closed”。
随后以带 message 的 RunResult 刷新，这些字段消失，只剩模型回答和 Evidence scope。

影响：用户当下最需要知道“交了什么、验了什么、权限是否收回”时反而少了权威摘要。
不是说证据已丢失；它仍在 state 中，是表现层覆盖。

最小修复：最终回答与权威交付摘要组合渲染，CLI/TUI/reopen 语义一致。
验收：fresh result 与 reopen 都保留同一真实目标、证据计数、权限/资源状态；
不能只断言模型文字出现或“completed”出现。

### EV-01 / P2：验收驱动把停止等待误标为有界停止

位置：`scripts/f2_f3_local_browser_journeys.py:401` 的 _run_bounded 和 `:436` 的 main。

实测：给 _run_bounded 传入等待 Event 的无副作用函数，budget=0.02 秒：
返回 timeout 时函数仍活跃；释放 Event 后函数继续运行，证明并未停止。
探针 finally 已释放并确认退出，没有遗留诊断线程。

- daemon=True 不会取消线程，也不能证明线程持有的 Chromium/子进程已清理。
- main 随后可运行下一旅程，并在 ExitStack 清理 base；不能据此签“所有资源已终止”。
- 这反驳的是 B13 的截止/清理证据，不是推翻正常路径 F2/D06 成绩，更不等于生产 Runtime 必然泄漏。

最小修复：只有 owner 终止与清理确认才算收尾；超时必须诚实记为未确认，
并不得在仍活跃的工作者下销毁资源目录或并行推进下一旅程。
若要 hard deadline，复用已有进程 ownership/退出确认模式，限制在这个测试驱动，不建设新调度平台。

验收：受控卡住的旅程到界后，无存活的本次工作者及 owned descendants，
或如实返回 cleanup-unconfirmed 并保留安全处置路径；禁止仅凭 thread.join 超时签闭合。

### EV-02 / P2：F2 旅程异常时没有执行已注册的清理回调

Oracle 指出并经本地故障注入确认。位置：`scripts/f2_f3_local_browser_journeys.py:151`。
函数创建 ExitStack 后，只在正常路径显式 close，没有覆盖整段的 with/finally。

本次用 fake browser resources +真实函数控制流注入错误，不启动 Chromium：

- 第一代 open 抛错：created=[1]，close_callbacks=[]。
- 第二代 close 抛错：created=[1,2]，close_callbacks=[1]。

D06 已有 finally，不能把两条旅程混为一谈。修复限于 F2 驱动生命周期；
验收应逐代注入异常，确保其它已注册回调执行，清理未知不签成功。

### UI-05 / P2：默认 CLI 的模型等待心跳没有接线

Oracle 最初仅标为待证，本地补齐了因果链：`main.py:1645` 在非 TUI 时传
progress_event_sink=None；`agent/composition.py:546` 原样传递；
`agent/runtime/loop.py:4591` 见 None 直接不启动 progress reporter。

真实 main(... --provider fake) 的 composition spy 确认：exit 0、event_sink=TerminalRenderer、
progress_event_sink_is_none=true。因此不能因 CLI renderer 有 heartbeat 分支就声称默认 CLI
确有实时等待心跳。流式文本到达时仍可输出，问题主要发生在尚无文本/非流式等待时。

最小修复：将既有受控 advisory 通道接到默认前台显示，验证提示早于 provider 返回；
不用新监控服务，不造进度百分比，不让 advisory 修改权威状态。

## 4. 缺的是哪些必要产品能力

先修 CORE-01 的正常工作闭环，下面再收束现有能力的三个最小用户闭环。

### 4.1 看得懂、能控制的运行过程

已有 Working、TUI 等待心跳、TUI Ctrl-C 请求、Goal 暂停/恢复。仍有限：

- `agent/cli/render.py:212` 忽略 TOOL_REQUESTED/TOOL_RESULT 和多数阶段；
  用户看到等待，却未必知道正在读文件、跑验证，还是等待审批/清理。
- CLI `agent/cli/app.py:195` 同步调用 run_turn，运行时不能再输入 /pause；
  Ctrl-C 走退出130/重启恢复，不是 TUI 的绑定 ControlInbox。两种入口语义不一致，需清楚标注。
- 默认 CLI 实时心跳接线缺失已确认（UI-05），不能仅改 renderer 就算实现实时进度。
- 中止请求与已停止必须持续区分；不承诺撤销远端模型服务端推理或外部副作用。

最小目标：始终能回答“在做什么、为何等、需要我做什么、能否停、是否已经停”。
重用现有 Runtime 事实/只读 GoalView；不要加第二套控制循环。

### 4.2 连续交互、回看与拿走结果

- 已有 checkpoint、workspace 会话选择、/new、archive/restore，不是缺存储。
- TUI 主要是可覆盖的 Static +单行 Input，没有呈现可回看的完整会话 transcript。
  当前问题是把已有记录提供给人读，而不是再建一个历史数据库。
- TUI 完成提示仅说 Enter follow-up 不开新任务，却未提示已存在的 /new。
- 审批和 recovery 默认显示内部 request/binding；安全绑定要保留，但默认用户需要
  “将改哪里、影响什么、我批准多久、下一步怎么做”。高级诊断信息可后置。
- 先修 UI-02/03/04，再补有界可回看的记录、交付摘要和明确新任务入口，不强制开发 Web/桌面 GUI。
- 为长任务描述保留一种明确提交的多行粘贴入口；不用同时重做两套复杂编辑器。

### 4.3 明确的支持范围、启动检查与证据闭合

- `main.py:476` guided setup 仍要手填协议、模型、base URL、环境变量名，再手动 export key。
  对懂终端的 owner 可用；不能包装为普通用户无门槛 setup。
- 能力 readiness 已存在；优先把“可用/缺依赖/缺配置/当前不支持/怎么处理”集中呈现。
  默认检查不产生付费请求，不索取或打印 key，不自动安装依赖或系统登录项。
- 本轮已补新 wheel 的窄离线安装 smoke；依赖解析/真实 provider/全部 extras 的安装态仍不由它证明。
  后续修改后只对交付候选重跑相关窄 smoke，不扩成全平台矩阵。
- D04 中途纠正/恢复不重复 effect，D05 嵌套指令/截断后搜索/保护路径过程项仍明确未证。
  见 `scripts/coding_scenario_grader.py:366`。这是**证据缺口**，不是这些能力不存在的证明。
- 后续仅补一个真正代表日常使用的“做事→纠正→中断→恢复→验证→交付”旅程。
  用本次新授权的模型与有界预算做真实验证，不能继承旧对话 key 或授权；先离线反例，再最小真实样本。

## 5. 七个用户旅程

| 旅程 | 判断 | 主要依据/边界 |
|---|---|---|
| 首次安装配置 | limited | 新 wheel 离线基础 smoke 通过；完整依赖/真实模型安装路径未验，普通用户配置门槛仍高 |
| 提交普通多步任务 | available / limited | 唯一 Runtime、治理工具、持久 Goal 已有；CORE-01 阻断写后同命令复测，真实 D01/D02 为执行者报告 |
| 了解进度并中止 | limited | 等待心跳已有，工具阶段不清；CLI/TUI 行为不同，TUI 退出卡死已复现 |
| 审批与权限 | available / limited | exact/Goal target/directory 审批与失效已有；术语/提示对普通用户不友好 |
| 失败/重启恢复 | available，但复杂实用性 unverified | checkpoint/unknown/reopen 测试已有；D04 完整真实纠正/恢复过程未证，不可自动重放未知 effect |
| 查阅结果、开始下一任务 | limited | CLI 摘要与 /new 已有；TUI 摘要覆盖、无完整回看、/new 提示不足 |
| 日常连续使用 | limited | F4 容量轮转已复查；草稿、串流、退出问题影响连续使用；没有统计性成功率证据 |

## 6. 做重了、做轻了与暂不做

做重的主要是**面向个人使用的交付/证明表达**：多个历史 seal、identity、PASS/NOT RUN 状态并列，
让人难以知道今天到底可以做什么。并非因此要删除安全围栏、类型合同或 checkpoints。

做轻的是：活跃状态/安全退出、持久记录的可见回看、草稿/流式反馈、完成摘要、配置诊断与恢复提示。
这些是实际用户接触的一层，比新增底层 capability 更紧迫。

已有能力先保留：文件工具、受治理程序/沙箱执行、可选专属浏览器、显式审批、durable Goal、
上下文预算/压缩、workspace 历史、可选 Skill/MCP/Memory/单 child SubAgent。
扩展受限不等于不是 Agent；此审计未逐一证明任意第三方兼容性。

明确暂缓：

- 任意桌面/PC 控制、个人 Chrome 接管、后台无限自治。
- 并发多 Agent/复杂 workflow 引擎、向量数据库、跨设备无限 Memory。
- 全平台 sandbox、任意第三方 MCP/Skill 兼容保证、自动安装/扩权。
- scheduler 开箱接线、launchd 登录项、云平台、多租户。
- 为文件大而拆分、重写内核、再建整套证明框架或增加新 promotion 轮次。
- 新 GUI 技术栈；先修目前 CLI/TUI，是否另做 GUI 应另定用户需求。

## 7. 推荐后续最多三个顺序小切片（尚未实施）

1. **先完成正常工作并能安全停下**：CORE-01 的写后复测闭环、UI-01 的退出闭锁、UI-05 的心跳接线；
   各自做窄 Red/Green。成功标准是修改后同命令真正复测并凭新证据收尾，活跃步骤不被冒充已停止，
   安全返回后能正常退出。不是扩大 sandbox 权限或取消去重。
2. **连续交互与可信交付**：UI-02/03/04；有界回看、/new 提示、恢复摘要。
   成功标准是连续三轮不丢草稿/不串流/可回看；fresh/reopen 的最终权威摘要一致。
3. **一条已验证的日常使用路径**：EV-01/02 驱动截止与异常清理，精简启动/能力状态说明，
   修正文档与相关 source 指纹范围，修复后复验隔离安装物；
   补一个中断纠正恢复的完整代表旅程。真实 API 需独立授权和预算，不扩成 D01–D12 全平台大测试。

每个切片只跑 touched-area 检查；合集结束按项目规则做一次所需 full gate。
不因局部 Green 宣称全部功能可用；也不为每个小改动重复所有验收与全量审计。

### 文档具体矛盾

- README:408 仍称 D06 没有真实模型验收；RESULTS:66 已有 10 月 5 日 D06 第二轮 completed 报告。
- RESULTS 顶部和 follow-up“最终分层结论”仍有 NOT RUN，后面又记用户授权后的真实执行。
- 更新应明确“历史未运行→后来已报告运行→本轮独立复查范围”，不删除真实失败史，也不偷换证据等级。

## 8. 本轮测试命令

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -rx \
  tests/process/test_r1_two_validation_completion.py \
  tests/acceptance \
  tests/continuity/test_f4_lock_accumulation.py \
  tests/browser/test_f2_owner_shutdown_outclosing.py \
  tests/browser/test_browser_cleanup.py \
  tests/tui/test_app.py tests/tui/test_render.py \
  tests/cli/test_render.py tests/cli/test_daily_use_launcher.py \
  tests/cli/test_016_guided_setup.py tests/kernel/test_runtime_progress.py
git diff --check
.venv/bin/ruff check .
```

诊断反例分别复用 tests/tui/test_app.py 的 _adapter、_runtime_blocking、
_RecordingRuntime、_run_id_factory，以及 tests/kernel/fakes.py 的 terminal Goal fixture。
CORE-01 使用 tests/process/test_r1_two_validation_completion.py 的真实 _drive 装配，
以脚本 provider 指定一次已批准写入与新 call ID 的重新验证；没有替换 Runtime/dedup/ToolRuntime。
F2 异常探针只替换资源与调用结果来观察真实函数的 finally 行为；CLI 接线 spy 包装真实 composition。
它们仅用于诊断，本轮没有把新测试写进产品测试树或修改既有断言。

一次 B03 附加诊断和一次 CLI 接线诊断首跑使用了 macOS /var 临时别名，因 no-follow 根路径要求
在启动前被拒绝；改用 Path.resolve() 的真实 /private/var 路径后成功复现以上结果。
这是诊断脚本路径准备问题，不记为产品功能失败，也不计入 143 项成绩。

### 本次安装 smoke

- 明确 allowlist：pyproject.toml、README.md、main.py、agent/ 与 first_agent_skill_runner/ 下公开 .py；
  不含 ignored/private、真实 state、根目录 tui/ 或 repository .env。
- pip wheel/install 均使用 --no-index --no-deps；构建另加 --no-build-isolation。
- wheel：first_agent-1.0.0-py3-none-any.whl，SHA-256
  `55042f044c2553ba4b6e7dd3a6954032d305d97bc9e330eadee23f1f922a79b3`。
- 新 venv 使用 --system-site-packages 复用已存在依赖；**不声称证明从零依赖安装**。
- 在源码目录之外、清空 PYTHONPATH，agent/main 的 import 都确认来自该 venv 的 site-packages。
- version、非秘密 setup、FakeProvider hello→/exit、Textual Pilot mount 均 exit 0。
  未使用真实 key、未调用模型、未启动浏览器、不改用户默认配置。
- 本轮创建的临时 staging/venv/wheel/合成 state 已在检查后清理，不是已部署给用户的安装包；
  都是可从公开输入重新生成的诊断产物，未删除或修改用户原有数据与配置。

## 9. Oracle Web 独立意见与交叉核对

输入：[Oracle prompt](2026-10-09-agent-product-readiness-oracle-prompt.md)。
完整原文：[Oracle response](2026-10-09-agent-product-readiness-oracle-response.md)。

- 全新会话：fa-product-readiness-20261009-0p78h1，没有复用旧 session/followup。
- --doctor 成功，wrapper 使用配置的 Default source；没有读取 profile/cookie 内容。
- 明确最高档 `max`；发送前两次日志与最终 metadata 均为
  **Power, item 5 of 5 (slider ARIA)**，verified=true。不是把 requested CLI model 当网页模型证据。
- committed conversation：`6ac8a407-60b0-83e8-a916-c12cc4bc580a`，新对话 URL 已记录，
  promptSubmitted=true，随后完整答案被捕获，status=completed、CLI exit 0。
- 运行约 13m22s；完成时间 2026-10-09 16:34:29（Asia/Shanghai）。
- session 记录的 Chrome PID 70987 已确认不存活；其临时 userDataDir 已确认不存在。
  没有关闭用户自己的 Chrome，也没碰持久 source profile。

### 采纳、补证与不同之处

1. 采纳 Oracle 的主结论：已是 Agent，技术 owner 有条件可用，普通用户产品闭环未完成；
   前台控制、回看/交付、默认路径比新增能力优先。
2. Oracle 独立发现 UI-01/02/04；本地 Pilot 已复现。UI-03 的跨轮串流为本地补充。
3. Oracle 发现 F2 异常清理遗漏；本地两代故障注入均确认（EV-02）。
4. Oracle 谨慎指出 CLI 心跳接线未证；本地补看 composition/loop 并经过真实入口 spy，
   确认缺失（UI-05），不是停留在猜测。
5. Oracle 要求加强 B03 因果断言；本地展开实际 facts，进一步以新 call ID 复现了 CORE-01。
   **这是本次本地审计新增的核心阻断**，优先于纯交互改进，Oracle 未看到该 loop 源码，
   不能把它说成 Oracle 已完整审查过的结论。
6. Oracle 对 F2/F4 内部实现的限制正确：未附相应源码。这里的 scoped 源码/143 tests 补上了部分证据，
   不将 Oracle 静态审查包装成其亲自运行测试。
7. Oracle 提醒 `_SOURCE_ALLOWLIST` 未涵盖 state.py/contracts.py 等关键补修位置，本地确认。
   现有 source_identity 只能解释为局部指纹；后续补范围或明确限定，不另建 seal 框架。
8. Oracle 不声称最终长文本必然被 2000 字裁剪——2000 cap 在流式显示；本报告也不把
   “缺可回看 transcript”夸大成持久内容已丢失。应测试长结果可读性，再做最小展示改进。
9. 根据本地后续安装 smoke，将 Oracle 的“当前安装态未复验”缩小为“完整依赖、extras 与真实模型
   安装路径未验”。最新基础 wheel/CLI/TUI mount 已有本轮离线证据，不重复留成待办。

本次未开启实施。上述最多三片是下一步建议，用户批准后再执行；不要自动开始新的优化轮次。

## 附：选定输入指纹

以下为本轮未改动的 Oracle 输入/当前公开源码指纹，用于限定结论，不是 release seal。

```text
5de648d3898eda743d72eab06886bfc7f032869323bc67d0f1112538cfec9d80  README.md
d53d29867661b649813ccc44defbffd24ad22244d80e84f72b12b45e075f1aab  pyproject.toml
aea5f373ea44237afaa299df3fe57c9e0f8baf91f99c41c10ae6114a8cff0982  docs/architecture/KERNEL_ARCHITECTURE.md
890ed7d2f9a90735e9343260dc7a9a5396fd45c8fae5c2d5a107aee2eb69cdc5  docs/architecture/CURRENT_CAPABILITY_STATUS.md
8ea89b95708e16cdf70c1bf555c695a679d38ccddca6126d6efedb7e8b868410  docs/handoffs/2026-10-02-bounded-reliability-repair/RESULTS.md
45d165bf7651353b8976d7ff0524e4bcb39384631469ff13e0a509e1d18fb66f  main.py
63a5df341f901fe2cb5c70effc66507bd231c20f147a3e3991be05c52305e7bc  agent/cli/app.py
898f869fa0feaf292b4aaa79db094e1a547b1c65adc3bb939838b8d4d0922eff  agent/cli/render.py
1d7737dc8bdf96192ec0bb7af371cd39d0799be5d7675a8efd00b1411eceab23  agent/tui/app.py
c5359241b1a9fde0548ecd7d2ff348933cfc63b4271a1917cf519e52ef741cf1  agent/tui/render.py
3411034f3417431f137f95ff63e2a2594b0c7c4e9b1e04be206dfc81987d417b  agent/tui/adapter.py
df6be4eb4d1c4d241b2476f3533de8bfddfd870c08e47d187a23adce080ece96  agent/runtime/views.py
d778014cff7e15050b7b63274bb99106561cddfadd70c3774022ee1016a68686  scripts/run_real_coding_scenario.py
02fe44e07b461a283cd065e4aa391d35a4fd8c022aead8a77fddc3738dcdefca  scripts/f2_f3_local_browser_journeys.py
0d0a7d65052ca672fc4214d2498f9c05f66510f99ab63d255378da2f2c09ae48  tests/process/test_r1_two_validation_completion.py
2cd65578a890a9773518c5b59e82bb6e8541bc4fdf528317e8c1ad97dc67b6ff  tests/acceptance/test_f3_runner_roundtrip.py
```
