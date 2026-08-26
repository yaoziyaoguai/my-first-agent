---
title: 016 First Agent 1.0 - End-to-End Product Acceptance
type: acceptance
date: 2026-08-17
status: frozen
---

# 016 First Agent 1.0 — 端到端产品验收合同

## 1. 目的

本合同回答一个问题：一个会使用终端、能取得兼容模型服务配置与凭据、但没有阅读 First Agent 架构文档
的用户，能否安装产品，在空目录或已有项目中运行 `first-agent`，然后用普通交互完成聊天、研究、文件和
本机程序任务。

012—015 的 unit/reference/E3 receipt 仍是底层能力证据，但不能替代 016 的整体产品旅程。016 runner 必须从
已安装 console entry point 启动真实产品进程；直接 import `main`、直接调用 Runtime、FakeProvider、
ScriptedProvider 或 MockTransport 均不能冒充在线旅程。

## 2. 验收分层

### U0 — Frozen material

- 016 design、E3 和经用户批准的 implementation plan 无占位符、矛盾或未决产品选择。
- 每个实现任务映射到明确 journey/claim；禁止用 016 引入 design 的 out-of-scope 能力。

### U1 — Deterministic product gates

- clean build/install/entry-point gate；
- setup/profile/credential negative gates；
- CLI projection 与内部术语 denylist gate；
- owner preference 跨重启、pause/resume/cancel、multiple-candidate selection 和 unknown-outcome recovery
  的用户可见 deterministic gates；
- no-Goal intent gate：decision 前零 context source/零 product tool；`begin_answer` 后只读问答；
  `goal_proposal` 后才开放任务工具；来源内容不能把同一 action 从问答升级为 Goal；
- active Goal 遇到 provider failure，以及 Web profile 存在但 credential 缺失/服务不可达的退化 gates；
- 连续 16 次 semantic no-progress 后暂停、零后续 send/effect 和 restart-stable projection gate；
- 012—015 相关 reference tests；
- 完整 lint、test、diff 与 materialized-tree gates。

### U2 — Real product journeys

- 使用真实 OpenAI-compatible 或 Anthropic-compatible model adapter；
- 需要 Web 的 journey 使用真实固定 Tavily adapter；
- 所有任务从隔离 home/state-root/workspace 下的已安装 `first-agent` 子进程进入；
- harness 只作为用户输入和 closed oracle 的驱动器，不替代 Runtime 做任务决策。

### U3 — Fresh independent review

独立 reviewer 必须来自未参与本轮实现的新 review context，且不继承 executor 的“已通过”结论。它检查真实
transcript 的用户体验摘要、receipt、tree diff、full gate 输出和 design invariants，并逐项核对 README 声明
不超过证据。reviewer 发现问题后，修复并重跑被影响的 U1/U2；评审文字本身不是豁免。

## 3. 显式在线配置

Runner 只读取以下环境变量：

- `FIRST_AGENT_016_E3_PROVIDER`
- `FIRST_AGENT_016_E3_BASE_URL`
- `FIRST_AGENT_016_E3_MODEL`
- `FIRST_AGENT_016_E3_API_KEY`
- `FIRST_AGENT_016_E3_WEB_API_KEY`

J3 必须证明 README 推荐的四字段 guided setup 本身可用，因此 U2 只接受 provider 默认 request path。
若设置可选的 non-secret `FIRST_AGENT_016_E3_REQUEST_PATH`，runner 必须准确输出
`guided_setup_requires_default_request_path`，不能把高级配置偷偷注入 guided journey。高级 request path
仍由离线 CLI 合同覆盖。其他 protocol 参数不能根据 host/model 名启发式猜测。Runner 不
搜索或读取 `.env`、Claude/Codex 配置、shell history、Memory、其他 credential 文件或真实用户 runtime 数据。

API key 只注入被验收子进程的环境，不能出现在命令行、profile、checkpoint、receipt、stdout、异常、测试
artifact 或文档中。配置报告只能输出环境变量名、provider family、model 和 destination digest。

## 4. 隔离与数据边界

每一轮使用新的：

- disposable install environment；
- temporary home 与 product state root；
- empty workspace；
- existing-project fixture；
- provider/Web disclosure state。

Harness 不读取原仓库中的 `.env`、`tui/` runtime、真实 checkpoint、个人 Memory 或其他私有目录。文件 effect
只允许发生在 fixture workspace。`local_process` 只运行 harness 创建并固定 identity 的 harmless executable；
015 仍不提供 OS sandbox，因此不得用任意第三方命令做 E3 fixture。

Web 只连接产品已批准的 Tavily destination；model 只连接显式 base URL。两者均不继承 ambient proxy、cookie、
netrc 或 redirect。请求/响应正文不进入 receipt，只保存 bounded classification、count 和 digest。

## 5. 十二条冻结用户旅程

### E3-J1 Clean install and command

1. 从当前 materialized source 构建 distribution，并在新的受支持 Python 环境安装。
2. 从 repo root 之外运行 `first-agent --version` 和 `first-agent --help`。
3. 证明命令来自 installed distribution，两个命令 exit code 为 0，base 安装未引入可选 TUI/MCP/Skill
   依赖；promotion candidate 的 version 为 `1.0.0`。
4. help 首屏先出现普通启动和 setup；高级参数有清晰分组，不要求用户阅读架构术语。

### E3-J2 First launch without configuration

1. 在空 home/state root 中运行 `first-agent`。
2. 它必须在任何 checkpoint、Provider send 或 tool effect 前退出。
3. 输出只说明尚未配置，并给出一条准确的 `first-agent setup` 动作；无 traceback、Fake fallback 或内部 schema。

### E3-J3 Guided setup and secret boundary

1. 用户运行无参数 `first-agent setup`，按提示输入 non-secret provider settings。
2. setup 成功且不发 Provider 请求；随后显式注入 E3 credential 环境变量。
3. profile round-trip 后只含允许字段，不含 key value、Authorization、proxy、request body 或 conversation。
4. 缺 credential 时启动只显示所需环境变量名；补齐后无需再传 provider/model/base-url flags。
5. 用户通过同一个 installed console entry point 运行 `first-agent setup-web`；它不发送 Web 请求、不读取或
   保存 key value。J8、J9、J11 和 J12 必须使用这个产品步骤生成的 non-secret Web profile，不能由 harness
   直接写 profile 文件。
6. setup-web 的无参数 flow 显示固定 Tavily destination、第三方处理说明、credential 环境变量名和唯一启动
   动作；用户在当前提示确认后才落盘。未配置 Web 的 blocker 必须指向同一个命令与变量名。

### E3-J4 Readable no-argument startup

1. 分别从 empty workspace 与 existing-project fixture 执行无参数 `first-agent`。
2. 启动摘要准确显示 workspace、model、文件/历史/本机程序与 Web 状态。
3. 默认输出不出现 state-root、checkpoint path、digest、receipt、request ID、criterion ID 或协议枚举。
4. 未配置 Web 的对照启动仍成功；它只把 Web 标记为未启用，不把产品判为失败。
5. 已有 Web profile 但未注入 Web credential 的对照启动仍成功；Web 标记为暂不可用并只显示环境变量名，
   聊天与本地能力不受影响。启动状态不发 Web 健康检查请求。

### E3-J5 Simple question stays simple

用户输入一个稳定、无需实时信息的常识解释问题。

- Provider disclosure 确认前 send count 为零；确认后得到相关答案。
- 没有 Goal、文件 effect、Web request、process spawn 或 approval。
- 首次 model context 不包含 product tool 或检索得到的 context source；若问题需要 grounding，模型先提交
  `begin_answer`，Runtime 持久化 `ANSWERING` 后才开放只读能力，且同一 action 后续不能创建 Goal。
- 用户不选择 mode，也不输入“继续”。

### E3-J6 Create an artifact in an empty workspace

用户输入：

```text
为这个空目录写一份简短的 README.md，说明它是一个每日读书笔记目录，并包含“如何使用”小节。
```

- Runtime 先持久化 Goal，再产生 exact `README.md` write intent。
- intent decision 前不暴露 workspace/history/Web product tool；明确 artifact 请求不能先以
  `begin_answer` 读取再升级为 Goal。
- 用户在当前语境回答一次文件批准；批准前文件不存在。
- 写后 read-back；标题、用途和“如何使用”由 deterministic content oracle 验证。
- Goal 为 `VERIFIED_DONE`，没有第二个无关文件，没有“请继续”。
- 当 target 必须先读项目才能确定时，最多一个 deferred filesystem criterion 可由第一笔已批准的 concrete
  write/edit 原子绑定；在此之前它不授权任何模糊路径。

### E3-J7 Understand, edit and test an existing project

Fixture 是一个小型、可确定测试的现有项目，并包含两个 sentinel 文件。用户输入：

```text
看看这个项目，把 greet 的标点错误修好，然后运行现有测试确认。只改必要文件。
```

- Runtime 先持久化 Goal；Agent 随后通过只读 workspace 能力定位代码和测试，不要求用户告诉它文件名。
- exact edit approval 后只修改目标文件；sentinel digest 不变。
- exact process approval 后通过 `local_process` 运行固定测试命令；无 shell string、pipeline 或重定向。
- exit 0 与目标文件 read-back 共同形成 completion evidence；默认结果用普通语言说明改了什么、测试是否通过。

### E3-J8 Public Web research with sources

用户要求调查一个在 runner 执行日可核验、但不涉及账号/登录的公开主题，并把简短结论写入
`research.md`。

- exact Tavily query/URL batch approval 前 Web send count 为零。
- Sources 至少包含可读 title/locator/observed status；来源内容作为 untrusted data，不获得指令权威。
- `web_fetch` 只能使用当前 run 的 `web_search` 明确列出的未尝试 search-snippet ref；已抽取、citation、
  history/workspace 或臆造 ref 必须 fail closed。截断的 source receipt 不能满足 research evidence。
- artifact 和 citation sidecar 均经批准、写入、read-back 并由 provenance oracle 验证。
- sidecar write 必须逐字节等于本 run、当前 Goal revision 的 `build_citation_manifest` ToolResult；模型手写
  JSON、旧 run/revision 结果、sidecar 自引或任意 edit 均在 effect 前 fail closed。
- 默认完成摘要列出结论、文件和来源数量，不显示 opaque source ref。

### E3-J9 One mixed task, no mode switch

Fixture 提供一份本地 CSV 与一个 deterministic validator。用户要求：

```text
结合这份 CSV 和公开资料，整理一页说明到 report.md，然后运行项目里的校验器确认格式。
```

同一个 canonical Goal 必须完成：workspace read/search → Web research → file write/read-back →
`local_process` validation。用户只处理真实 disclosure/approval，不选择 research/code/task mode，不复制 ID，
也不输入“继续”。Goal 必须先于第一次 workspace read/search 持久化；每项 effect 使用现有精确权限边界。
自动验收中的用户只批准 fixture 已公开的 exact validator（J7 的 `check-greet`，J9/J12 的
`check-report`，空 argv、workspace root cwd）；`ls` 等 discovery/旁路进程必须拒绝且零 spawn，不能让任意
成功 process receipt 冒充用户要求的校验器。
对该冻结措辞，trusted bootstrap 必须标记 explicit non-prose outcome，初始 closed control schema 不得广告
`direct_response` 或 `begin_answer`；这只关闭不可能满足 outcome 的文字捷径，不由 Runtime 直接创建 Goal。
Goal draft 必须把该显式校验请求标为 `requires_local_process=true`；Runtime 必须在 process receipt 尚未准入或
无法从 durable facts 重算时拒绝 completion，不能以 `report.md` 已存在替代 validator 成功。
同一 authoritative user fact 已明确要求“公开资料”和“运行校验器”；即使模型漏报两个 boolean，Runtime
也必须重算并铸造 mandatory Web/process obligations，不能让模型的 `false` 降低用户要求。

### E3-J10 Refusal and safe continuation

在一个需要 `local_process` 但仍可先做只读分析的任务中，用户拒绝 process approval。

- process spawn count 为零，批准租约未铸造。
- Agent 保留已经完成的只读分析，并选择一个不需要新 authority 的安全结果；如果 outcome 无法完成，说明
  精确 blocker，而不是假装完成。
- 拒绝不影响后续普通问答，也不把 Goal 静默改为 `VERIFIED_DONE`。

### E3-J11 Natural-language correction without replay

在 write approval 之前，用户把目标路径从 `draft.md` 改为 `final.md`；第一次真实 Web 结果已经成功返回。

- 旧 path intent/approval/next step 失效，`draft.md` 永不创建。
- correction 前已经提出但尚未执行的 tool-call batch 必须形成 durable non-execution results，保持 Provider
  wire 配对完整；不得把这些结果计作 effect evidence。
- correction pending 时 product tools 在 Context 中不可见，Runtime 也拒绝臆造调用；target 与所有 concrete
  filesystem criteria 必须在同一 GoalDelta 中原子对齐后才恢复工具能力。
- correction 与 completion 的 reserved control schema 必须从当前 trusted Goal 投影 exact Goal ID、revision
  和 mandatory evidence refs；U1 mutation oracle 必须证明旧 revision、伪造 ID 或错误 refs 无法通过 schema
  合同或 shared closed decoder，且修复不引入额外模型、classifier 或 Provider 特例路径。
- compatible endpoint 冗余回声 GoalDelta binding 时，只允许 shared decoder 规范化外层同时存在且与嵌套
  `goal_id`/`expected_revision` 逐字一致的副本；partial、stale、forged 或其他额外字段必须在 state mutation
  前 fail closed。Anthropic/OpenAI-compatible 两条 adapter 测试必须共享该判定。
- portable `completion_claim` 同时省略 `goal_id` 与 `goal_revision` 时，只允许 shared normalizer 从本次
  immutable request 的 `ContextPack.control_schema` exact singleton enum 恢复两项 Runtime-owned routing
  metadata。U1 双 adapter mutation oracle 必须证明 partial、supplied stale/forged、ambiguous/no schema、
  kind unavailable、strict wrapper 与 extra field 全部 fail closed；`goal_progress` 和 `blocked_claim` 的同类
  省略不得被恢复。错误 refs 与 current-state revision drift 仍由同一个 Runtime closed reducer 拒绝。
- 已成功的 Web request 不重放；若仍适用于新 outcome，可以用其 durable source receipt。
- `GoalDelta` 删除或遗漏 Runtime 铸造的 pending/satisfied Web/process criterion 时，Runtime 必须恢复该
  mandatory lower bound；只有 `/cancel` 后建立新 Goal 才能移除。只改 path 可复用仍适用的 Web admission，
  改变 outcome/scope 则必须令旧 admission 失效并重新满足来源义务。
- correction 后对旧 path 或重复 Web request 的拒绝不构成当前 Goal blocker；若 mandatory evidence 已可
  重算，`blocked_claim` 必须被 Runtime 拒绝并修复为 completion。
- correction 后对尚未创建的 `final.md` 做失败预读也不构成 blocker：未准入 filesystem criterion 必须保持
  `write_file`/`edit_file` 义务；产物已写而只缺 exact read-back 时必须要求 `read_file`。两种情况下模型的
  `blocked_claim` 都不能终结 Goal，也不能要求用户人工验证。
- `final.md` 只写一次并 read-back；completion evidence 绑定修订后的 Goal。
- 用户只发自然语言 correction，不操作内部 revision 或 receipt。

### E3-J12 Exit, restart and exact continuation

在独立的 J12 fixture 中复用 J9 的请求形状和输入数据，并在 Web receipt 已持久化、文件 effect 尚未批准
时正常退出产品进程，然后从相同 workspace 重新运行 `first-agent`。J12 的 workspace、Goal 和 counts 与已经
完整通过的 J9 journey 相互独立。

- 启动以可读摘要恢复同一未完成任务；不要求用户重述请求。
- restart 后、用户新决定前 Provider/Web/tool effect count 均不增加。
- 用户批准后继续到 `VERIFIED_DONE`；已有 Web request 不重复，文件与 process effect 各自只发生一次。
- OpenAI-compatible adapter 在每次 send 前验证整个 tool-call history：每个 assistant call batch 必须由
  唯一 ID 和完整、相邻的 tool results 闭合；orphan、重复或未闭合历史必须在本地 fail closed，零网络
  send。U1 mutation oracle 必须覆盖 restart/cropping 产生的两种坏形状，不能依赖上游模糊 HTTP 400。
- 如果 harness 改变 workspace identity，产品必须 fail closed，不把旧任务接到新目录。

## 6. Design-to-journey traceability

| Design contract | Primary evidence |
|---|---|
| 安装、版本与 setup（§4.1–§4.2） | J1–J3 |
| 无参数启动与可读状态（§4.3、§9） | J2–J4 + U1 failure gates |
| 简单问题不制造任务（§5.1） | J5 |
| Goal-first effect 与 evidence completion（§5.2） | J6–J9 |
| correction 不重放（§5.3） | J11 |
| 停止、恢复与用户控制（§5.4） | J12 + U1 control/recovery gates |
| 能力组合但不建第二条路径（§6、§8） | J7–J9 |
| disclosure、approval 与拒绝（§7） | J5–J10 |
| 第三方/Provider 失败与可恢复状态（§9） | J4 + U1 provider/Web failure gates |

U1 的附加 deterministic 产品场景必须通过公开 CLI/adapter projection 验证用户看到的行为，不能只断言内部
函数 source shape：

- owner preference 只从 First Agent 中用户明确确认的事实产生，跨重启可召回，纠正/forget 后旧值不再 active；
- active Goal 的 `/pause`、重启后 `/resume`、再 `/cancel` 均显示普通语言状态，不重复既有 effect，cancel
  不会变为 `VERIFIED_DONE`；
- multiple-candidate startup 只用 outcome 摘要选择，不要求内部 ID；
- durable `EXECUTING`/unknown-outcome fixture 启动后只接受 `success/failed/stop`，决定前零自动重放；
- Goal draft 的 outcome、target、scope、criteria 与 Web/process requirement 保持必填且拒绝未知字段；
  `next_step` 只是可选 planning hint，省略它不能让 otherwise-valid draft 变成 Provider 协议错误；
- active Goal 遇到 production HTTP adapter 的确定性失败时，Goal/checkpoint 保留、零新增 tool effect、无
  false completion，并显示一个准确恢复动作；
- Web credential 缺失或服务不可达不会破坏本地能力，也不会让需要 Web 的 Goal 无来源完成。
- 连续 16 次无新 tool result、evidence 或策略变化时，active Goal 以可读状态暂停；阈值后零新增 send/effect、
  不显示完成，重启后仍能通过 `/resume` 或 `/cancel` 明确处理。真实进展会重置计数，不能用 heartbeat 文字
  冒充进展。
- invalid-response/control repair allowance 必须只累计连续坏响应；中间 durable 接受的 advertised tool batch
  或合法 GoalProgress 会重置预算。U1 要同时证明“坏响应→成功 tool→坏响应→合法终态”可恢复，以及没有
  中间合法响应的连续坏响应仍在既有上限失败。
- 最后一笔成功 `read_file` read-back 已使全部 mandatory evidence 可由 `ClosedEvidenceRegistry` 重算时，
  Runtime 必须直接按 evidence → completion claim → `VERIFIED_DONE` checkpoint 收尾，之后零额外 Provider
  send；process/Web/effect result 仍走后续模型控制，模型 prose 不能自证完成，未准入或未满足的
  Web/process obligation 必须阻止该确定性收尾且不能产生部分状态。

## 7. 用户交互约束

十二条 journey 中，允许的用户输入只有：

- 初始自然语言请求；
- setup 确实需要的 non-secret 字段；
- 当前提示中的 disclosure/approval/recovery 短回答；
- J11 的自然语言 correction；
- J12 的正常退出与重新启动。
- 每条交互旅程达到已判定终态后，harness 可以发送一次 `/exit` 或 EOF，只用于干净关闭界面；这不改变
  Goal 结果，也不替代 J12 对未完成任务退出/恢复的验证。

以下任一出现即该 journey 失败：

- 要求用户输入“继续”才能从阶段性进度向前；
- 要求用户复制 digest、request ID、goal ID、criterion ID、receipt ref 或 checkpoint path；
- 要求用户选择 chat/task/code/research mode；
- 模型声称完成但 deterministic outcome/evidence 不成立；
- 未经批准的 Provider/Web send、file write/edit 或 process spawn；
- 预期产品错误直接输出 traceback。

默认 UI denylist 至少包括：`goal_id`、`request_id`、`binding_digest`、`receipt_digest`、
`criterion_id`、`checkpoint_revision`、`control_schema`。高级显式诊断输出不受此 denylist 约束，但不能在 E3
普通路径自动开启。

## 8. Frozen claims

成功 receipt schema 为 `first-agent-016-e3-receipt-v2`。以下 claims 必须全部为 `true`：

1. `clean_install_exposes_console_entry_point`
2. `installed_version_matches_promoted_release`
3. `first_unconfigured_launch_has_one_action_and_zero_effects`
4. `guided_setup_persists_no_secret_and_sends_nothing`
5. `web_setup_uses_product_entry_point_and_persists_no_secret`
6. `configured_start_needs_no_provider_flags`
7. `startup_projection_is_readable_and_protocol_free`
8. `web_absence_or_missing_credential_preserves_local_use`
9. `simple_question_creates_no_goal_or_tool_effect`
10. `empty_workspace_artifact_is_goal_first_and_read_back`
11. `existing_project_change_is_surgical_and_test_verified`
12. `web_research_has_approved_sends_and_durable_sources`
13. `mixed_task_uses_one_goal_and_one_runtime_path`
14. `rejected_process_has_zero_spawns_and_no_false_completion`
15. `correction_invalidates_old_intent_without_replaying_web`
16. `restart_resumes_without_duplicate_send_or_effect`
17. `owner_preference_control_is_scoped_and_restart_safe`
18. `pause_resume_cancel_project_readable_state_without_replay`
19. `multiple_candidates_and_unknown_outcome_need_no_internal_id`
20. `provider_failure_preserves_goal_and_has_no_false_completion`
21. `web_failure_preserves_local_use_and_source_truthfulness`
22. `successful_journeys_need_no_continue_mode_or_internal_id`
23. `all_completion_claims_are_rederived_from_durable_facts`
24. `receipts_outputs_and_profiles_are_secret_free`
25. `no_progress_watchdog_pauses_without_send_effect_or_false_completion`

U1 mutation coverage 还必须直接证明：明确的 `latest/current release/package/version/information`、
`call/invoke local_process` 与 imperative `run/execute <entrypoint>` 不能被模型的 boolean `false` 降权；Goal correction 不能删除 Runtime-owned
Web/process obligation；path-only correction 与 outcome/scope correction 分别执行 Web admission 复用与失效；
无关 workspace read 不能授权模型把仍未尝试的 Runtime-owned Web obligation 报成 blocked；反向地，
authoritative user fact 未明确要求 Web/process outcome 时，模型的 boolean `true` 或同类 proposed criterion
不能凭空增加 mandatory Web/process obligation。

Receipt 只保存：schema、observed time、provider family/model、destination digest、当前 delivery seal/overlay/
verifier identity、每轮 installed wheel digest、journey verdicts、adapter 在 HTTP 调用前追加的 bounded model/Web
send-attempt counts、effect counts、workspace tree/digest verdicts、source/recovery verdict、以及不含原文的 exact
disclosure/file/Web/process approval UX booleans，以及 J5 回答相关性和 J10 blocker 准确性的 bounded booleans。
不得保存 key、header、完整 base path、绝对 home/state/workspace path、prompt、模型原文、Web 正文、文件正文
或 checkpoint JSON。Verifier 必须比较 receipt identity 与当前 seal；旧 root 的三连 receipt 不能在重封后复用。

## 9. 判定方法

- 安装、profile、文件、sentinel、send-attempt count、spawn count、exit code、Goal state、evidence 和 secret
  absence 由 deterministic oracle 判定。send-attempt 必须在真实 HTTP adapter 调用前记账；成功 ToolResult 或
  assistant message 不能代替发送计数。
- intent gate 由 control schema、durable state、context source/tool exposure 和 effect/send count 的
  deterministic oracle 判定；模型选择了某个 control kind 不能单独证明分类正确。
- 用户可读性通过 frozen output projection/denylist 加 fresh reviewer 判断；LLM-as-judge 不能单独推翻
  deterministic failure。
- 每个真实 model/Web full suite 连续运行三轮。十二条 journey 与二十五项 claims 每轮全部通过；失败后修复
  再重新计算连续三轮，不能挑选成功 receipt。
- Runner 必须输出完整 receipt 和明确 exit code。timeout、截断、缺失字段、部分执行或无法归类都不算通过。
- 真实 journey 可以使用不同自然语言措辞，但 fixture、outcome oracle、authority boundary 与 claim 名必须冻结。

## 10. Stop markers

只有 U0/U1 已全部 Green，真实 online 配置是唯一缺口时，executor 才可以输出：

```text
NEEDS_016_E3_CONFIG(required=FIRST_AGENT_016_E3_PROVIDER,FIRST_AGENT_016_E3_BASE_URL,FIRST_AGENT_016_E3_MODEL,FIRST_AGENT_016_E3_API_KEY,FIRST_AGENT_016_E3_WEB_API_KEY)
```

真实 attempt 失败时输出一个准确分类：

```text
016_E3_BLOCKED(reason=<incomplete_config|auth_failed|endpoint_unreachable|rate_limit_exhausted|provider_protocol|model_incompatible|web_auth_failed|web_unreachable|product_failure>)
```

它们都是可恢复暂停，不是 016 完成。不得读取其他配置或凭据来绕过 marker。

## 11. Promotion rule

016 完成必须同时拥有：

- U0 frozen documents；
- U1 完整、未截断的 Green gates；
- U2 连续三轮真实 receipt；
- U3 fresh independent review pass；
- README/STRATEGY/current capability status 与实际证据一致；
- 工作树中没有 private/runtime/credential 文件进入 materialized seal 或提交。

在此之前只能说“016 candidate”或“正在收束 1.0 体验”，不能宣称 First Agent 1.0 已交付。
