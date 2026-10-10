# 冻结修复合同与实施顺序

> 版本 1，2026-10-09 冻结。已结合 Oracle Web 5/5 复核与本地源码复核。
> 这里只规定有限修复；[审计](../../audits/2026-10-09-agent-product-readiness-review.md) 提供缺陷事实，[ACCEPTANCE.md](ACCEPTANCE.md) 规定证明义务。
> 原始 Oracle 答复是建议；与本文不同的取舍，以本文及 RESULTS 的裁决说明为准。

## 0. 一次只推进一个可验收切片

| 切片 | 工作项 | 用户可见结果 | 验收 |
|---|---|---|---|
| S1 | CORE-01、UI-01、UI-05、TUI 控制边界反馈 | 修改后能复测；长调用结束后可退出；等待和控制请求不说假话 | DU-01–12 |
| S2 | UI-02/03/04、有限回看/多行入口、/new 可发现性 | 连续对话不丢草稿不串流；看懂并拿到结果 | DU-13–19 |
| S3 | EV-01/02、代表恢复旅程、文档/指纹/最终产物 | 证据真实、错误收尾可处置、支持范围清楚 | DU-20–27 + 最终 gates |

S1 各子项完成 focused 后继续下一项，不每次做全量；三个切片最后统一收 full/materialized。
按仓库默认 main 保留既有工作；本包不要求分支、提交或 PR。

### 代码导航与修改边界

| 项 | 首要修改落点 | 只读理解/回归落点 |
|---|---|---|
| S1-A | agent/runtime/loop.py、evidence.py；R1/F1 与新增 freshness tests | contracts.py、tools.py、state.py、compaction_rules.py；sandbox authority/receipt |
| S1-B/C | agent/tui/app.py、adapter.py；main.py、agent/cli/render.py；对应 TUI/CLI tests | runtime/control.py、progress reporter、composition close owner |
| S2 | agent/tui/app.py、render.py；对应 TUI tests | cli/actions.py、runtime/views.py、state.py 的用户 fact/replay/control receipt |
| S3-A/B | scripts/f2_f3_local_browser_journeys.py；新增 browser driver tests | agent/process/group.py、browser/managed_web owner cleanup |
| S3-C | 新增 tests/acceptance/test_daily_use_recovery_journey.py | 现有 composition、workspace session、typed actions、真实受治理文件/sandbox 工具 |
| S3-D | scripts/run_real_coding_scenario.py、既有 record-contract tests、README.md、main.py readiness 提示、旧 RESULTS 顶部、本包 RESULTS | CURRENT_CAPABILITY_STATUS：不提升等级 |

这些是导航，不是要求把每个文件都改一遍。小 helper 优先留在现有责任模块；仅 S2 的 modal 可提取到新的 `agent/tui/dialogs.py`，避免 app 继续承担分页/编辑细节。无其它新抽象层、新服务或持久 schema。
涉及表外产品代码时，先证明它是某 DU 验收的必要依赖并在 RESULTS 记录；不能以此开启相邻重构。

## S1-A：CORE-01，写后合法复测（最高优先级）

### 根因与入口

`loop.py` 的 `_product_request_digest`、`_successful_product_request_inventory`、`_drive` 在 prepare 前抑制重复成功请求。
当前写入使旧 sandbox validation evidence 失效，却没有释放对应成功请求的 suppression，导致“检查→修改→同命令复测”被挡。
`evidence.py::_may_invalidate_workspace_validation` 与 `_native_sandbox_tool_receipt` 必须共享可信只读 receipt 的判断，不能两边定义不同。

### 冻结机制：三个集合、同一个 durable fact fold

使用以下语义；名称可按局部风格调整，但集合关系和转移不能变：

1. `ordinary_successes`：原有普通成功请求。
2. `mutable_observation_successes`：ordinary 的子集；继续沿用原有文件/browser observation 的 effect 失效语义。
3. `native_validation_successes`：本次新增的可失效验证成功集合；与 ordinary **不重叠**，不能先放 ordinary 再只从新集合删除。

参数级 suppression 查询 ordinary ∪ native_validation；既有 LOCAL_SAME_UID_PROCESS 的 lease-governed 例外、exact typed action replay 和 no-progress 规则不变。
A 与 B 两个成功的可信只读验证可以共存，B 不会让 A 过期。

一次按现有 active-run 范围及 fact 顺序折叠的 helper 负责重建三个集合。
初始化及每次成功保存 tool-result checkpoint 后都调用同一折叠逻辑；不再维护另一份容易漂移的 live 增量算法。
checkpoint 保存失败不提前更新成功缓存。只读现有 retained facts；summary 不作为执行凭据，不读取 archive。
operator 请求可不进入模型请求去重集合，但其已执行 mutation result 必须先参与失效判断；不得读取被隐去的 operator arguments。

### 可信验证分类，不是新增权限

仅已经执行成功、由 ToolRuntime 铸造并保存的 native receipt 可以进入 native_validation：

- executed=true，is_error=false，outcome=exited，exit_code=0；
- `SandboxReceiptV1.from_json` 严格解析和 digest 成立；metadata 投影与 receipt 一致；
- mode=read-only、network=off、backend=seatbelt、enforcement=confined，profile/历史 workspace/原请求执行绑定一致；
- 保留现有 tool identity、receipt 来源检查，拒绝 fake/mock/synthetic。不能凭模型参数、命令名、任意 JSON 的 mode 字段分类。
- 当前 ToolRuntime 对 isolated sandbox 只接受 verifiable draft，普通 callable 返回 ToolResult/ToolExecutionOutput 不能伪造该合同。复用这一来源边界，不把“哈希能对上”当成来源证明。

历史分类只回答“旧成功还能否抑制新请求”。不要求历史 lease 现在仍有效，也不拿当前 Goal revision 去否定历史执行时的只读属性。
**再次执行**仍必须重新 prepare、policy、必要 approval/当前有效 lease、EXECUTING、invoke、result checkpoint；不得复用已过期权限或旧 evidence 宣布完成。

### 输入变化的失效规则

复用并收紧现有 evidence mutation 判断：

- 已执行的 write_file/edit_file/make_directory、same-UID process，以及不能被上述可信 read-only/off 分类证明为只读的已执行 sandbox，按现有可能修改规则使 native_validation 清空；
- 失败、timeout、非零退出不能证明没写；这类已执行结果同样触发；
- executed=false 的拒绝不触发新豁免；
- 对 sandbox 的“不使其它验证失效”例外必须用同一严格 helper，不能只信 metadata 的 mode=read-only；
- 原文件/browser observation 失效规则保留。其它写入/外部 effect 的成功请求不因为本项被无条件解禁；
- UNKNOWN effect 仍先 recovery；没有 receipt 不等于没有副作用，更不能自动重放。

不把 sandbox_exec 塞进现有 `_MUTABLE_OBSERVATION_TOOLS`：其 EXTERNAL 分类会让多个检查互相失效。
不加 durable generation、全盘 workspace hash、输入依赖图、字符串命令白名单或缓存平台。

### 实施与证明

先完成 DU-01 Red；原 B03 改为 A/B → write → 新 ID B → 缺 A → 新 ID A 的因果链。
补 live/reopen/compaction 等价、未变化重复、operator mutation、坏 receipt、lease/replay/UNKNOWN。
compaction 用现有机制压缩可移除的旧闭合 turn；当前 active run 的调用/结果仍须受保护，不创造假 summary 凭据。
不能靠换命令参数/Goal、减 mandatory criteria、删除 no-progress 或放宽审批绕过。
contracts/state/checkpoint 不预设修改；若确需改变公开行为或持久协议，停止该项并说明为什么既有 seam 无法满足合同。

## S1-B：UI-01，可靠退出与真实 worker 生命周期

### 单一飞行门

`adapter.is_active` 只包住 execute_once，不等于整个 UI worker callable 已结束。
`_run_action` 必须在提交工作时同步保存本次 worker handle/dispatch 身份：**已排队尚未开始也算 busy**。
UI 的 business-action/quit gate 检查 pending-or-running handle，加 adapter 状态防御；阻止第二次调度。
移除 `@work(exclusive=True)` 的隐式取消；不得以调度新 action 来取消正在运行的线程。

worker 只返回有界 outcome（结果或已清洗的错误类型），不在返回前同步 `call_from_thread(_refresh)` 触发 exit。
UI 线程在对应 Worker 正常 SUCCESS/ERROR 完成通知后统一 reload/render/close；不混入其它 worker 的通知。
本地 Textual 源码表明 SUCCESS/ERROR 来自被 await 的 callable 返回/抛错；CANCELLED/is_finished 本身不能证明底层线程停止。
本产品路径不主动 cancel worker；若收到意外 CANCELLED，在没有 callable 已结束证据时仍保持未收口，不能 close resources。

### 冻结状态表

| 条件 | 显示/动作 | 资源/状态 |
|---|---|---|
| Ctrl-Q，worker 已排队或正在执行 | closing_requested；拒绝新任务；“等待当前调用收口，不代表已取消” | 不 cancel/kill worker，不提前 close composition |
| 首次请求关闭 | 只启动一个现有 30 秒 deadline timer | 重复 Ctrl-Q 不重置/叠加 timer |
| deadline 到仍未收口 | 等待超时但仍在等，UI 保持响应 | shutdown_blocked 不能成为永久 latch |
| callable 真正返回，权威 reload 成功 | 自动自然退出，无需再按 Ctrl-Q | 正常退出码0；由既有 composition owner 逆序收尾一次 |
| worker 报错，权威 reload 成功 | 明确可能需要恢复；关闭请求仍能收口 | 退出码2；不说“action 未应用”，以 checkpoint 为准 |
| callable 已返回，reload 失败 | 保留固定错误/禁用业务动作，显示“再次 Ctrl-Q 仅重试读取状态” | **重复 Ctrl-Q 只做一次只读 reload 重试**；不自动无限重试、不新建 F5 功能 |
| durable checkpoint 是 unknown effect | 显示未决恢复；本地 worker 已结束后可以离开前台 | 保留 UNKNOWN，不改成 CANCELLED/CLEANED；owner 仍如实收尾 |

无关闭请求的普通完成继续显示，不自动退出；无关闭请求但 reload 失败也允许 Ctrl-Q 进入上述重载/退出流程。
NEW_SESSION_REQUESTED 的既有返回码/装配协议保持，不能与错误码混淆。
close callback 抛错不得吞成成功或再次执行全部 callback；保留现有 main owner 的错误传播。
Ctrl-Q 不是 cancel/pause，不承诺停止远端请求。cooperative 控制继续用已有 TUI 操作。

## S1-C：默认 CLI 心跳与 TUI 控制反馈

### CLI 与 advisory

- `main.py` 的 CLI/TUI 前台把已有 event sink 同时接到 progress_event_sink；默认 CLI 等待时也能收到 started/waiting/finished。
- 用 actual main + 可阻塞 provider 证明返回前已经提示；provider 不多调一次。
- CLI renderer 对去重/终态状态与一次输出使用窄锁；progress thread、delta、result 不乱序覆盖最终结果。不得持锁调用 Runtime/provider。
- TUI 使用既有 UI 线程消费机制，状态优先级为关闭等待/加载失败/控制请求待确认 > provider waiting；finished 仅清除此响应的 waiting，不等于 Goal 完成。
- **不新增 tool advisory**。现有 invocation 末尾投递的 TOOL_REQUESTED/RESULT 不宣称是实时工具进度。
- CLI 仍同步 run_turn：运行期间输入 /pause 不保证即时处理；Ctrl-C 仍退出130并提示重开检查可能已发生的 effect。
- 不为 CLI 引入并发输入编辑器或第二 Runtime loop；主动 pause/cancel/correction 使用 TUI 路径。帮助/等待提示说明此边界。

### TUI cooperative 控制

复用 `TuiAdapter.request_control` / ControlInbox；仅 exact 当前 binding 的 submit 成功才显示“请求已接收，等待安全边界”，不能直接显示“已暂停/已取消/纠正已应用”。

- 没有 Goal/binding、刚关闭或被替换的 binding：固定受控失败，保留草稿；不崩溃、不借未来 Goal 重绑重发。
- adapter 在 submit 前核对界面意图对应的 conversation/Goal/revision/invocation；读取最新 binding 只为验证，不得替换一个已失效的预期 binding。控制成功后等待 matching receipt，不接受另一请求的 receipt 代为清草稿。
- adapter 将已知 binding 缺失和 inbox submit 的绑定失败转换成窄的控制不可用结果/异常；不把所有 RuntimeError 都视为同一种可重试失败。
- store.load 等基础设施错误走有界失败反馈，不泄漏原始异常内容，不借旧 snapshot 继续动作。
- Runtime 产生相应 durable ControlReceipt/用户 fact 后才能显示实际应用状态。
- 同一 binding 的 pending pause/cancel 可在 UI 合并重复点击；不能丢失不同的纠正内容或把未入队请求当成功。
- 关闭期、takeover、unknown effect、审批预览上限、typed legality 的现有优先级不变。关闭时不能先进入 active correction 分支再检查 closing。

## S2-A：草稿、流式身份、交付摘要

### 草稿（UI-02）

UI 本地持有 draft_text、递增 draft_revision 与 pending_submission_identity；不持久化新数据库。
_refresh 是展示，不无条件清 Input；F2/回看/审批/状态/错误刷新都不消费草稿。

消费证明必须来自对应的 durable 接收：

- SubmitMessage：对应 action seq/digest 的 replay 记录及 `action:{seq}:user` 的实际文本 fact；
- correction：对应 request_id/payload 的 ControlReceipt 及 `control:{request_id}:user` fact；
- 仅已入 inbox 时显示“排队等待”，先保留草稿并阻止同一 pending 文本重复发送，待 durable 消费才清除；
- 消费后只清“仍为同一 draft_revision 的那份文本”。用户在等待中输入的新版本不能被迟到回调覆盖；
- 不以 RunStatus.COMPLETED、worker 已排队或没有抛异常作为消费证明；AWAITING_APPROVAL 也可能已消费用户文本；
- parsing/gate/busy/stale/load 失败保留；若接受情况未知，保留并提示“尚不能确认，勿重复发送”，不自动重试。

只读 slash command 仍是现有 adapter 功能，不作为模型消息；不把它清空的副作用套在另一个尚未发送的多行草稿上。

### 流式展示（UI-03）：只修消费方，不新增 producer 身份协议

使用现有 `(conversation_id, run_id, revision, causation_id)` 区分响应、event_id 去重。
已核对：foreground 每次 generate 前保存 record_foreground_model_attempt，background 的 begin_provider_call 同样增加 revision；现有 HTTP adapter 单次 generate 不做内部模型重试；compaction generate 不带 delta observer。
因此本轮**不新增 invocation/attempt ID 或更改 event schema**；用真实 Runtime 重试测试锁定这个前提。

- 每次 UI dispatch 打开展示窗口并保存 expected conversation/起点 revision；已知 run 时精确绑定。新 run 只可绑定本次合法 action 对应的首个事件，不能接受其它 conversation 的先到事件。
- 同 run 的较新 revision 是新响应，清空当前 preview；causation 是不透明标识，不按字典序比较。
- 相同 event_id 忽略；较旧 revision/已封闭 identity 的迟到事件不得切回。delta 与 progress 的 causation 格式不同，不强求二者相同；waiting 按 conversation/run/revision 关联。
- 同一响应的 delta 序号来自现有 event_id 尾部计数。连续消费，重复忽略；缺口/逆序/不可识别身份时降级为“流式预览不完整，等待最终结果”，不猜测拼接。
- 只保留当前响应最后 2000 个可安全展示字符；用单调序号水位避免无限 seen-ID 集合。对不适合序号比较的事件做当前 dispatch 内有限缓存，上限256，溢出降级，不无限增长。
- 每次 run_turn 结果/错误返回（包括 awaiting approval、paused、失败）并处理权威 reload 后关闭窗口；旧 delta/waiting 再来一律忽略，不能覆盖 final。
- F2 等只读 refresh 不关闭窗口、不清 active queue。丢失 advisory 不影响 typed state/审批/evidence。
- 最终文字来自权威结果/facts，不受 preview 2000 字截尾影响；完整 retained 长文通过 F3 阅读。

### 权威交付摘要（UI-04）

`agent/tui/render.py::project` 统一组合本次回答与任务交付摘要，app 不再用 result.message 整块覆盖 projection。

- VERIFIED_DONE 同时保留 final text、delivery_summary_message、verification_scope_message；
- 使用已有 GoalView 的 targets、criteria_total/verified、verification_scope、durable_authorities_closed。不得另算一套“必要证据数”或发明现有 view 没有的 resource-cleaned 字段；
- fresh/reopen 同事实同摘要。snapshot 比 result 更新时，以 snapshot 为状态权威，旧结果不能覆盖新纠正/暂停；
- pending/recovery/takeover 优先；保留既有 takeover 补充提示。COMPLETED 或模型文字不是 VERIFIED_DONE；
- 存在已知未决资源/恢复时保留现有提示；没有资源字段不等于所有资源已清理；
- 保留 safe_display/literal rendering、preview cap、displayed-snapshot 绑定；不解析 raw checkpoint JSON 构造 UI。

## S2-B：冻结的最小交互入口

### F3：当前保留内容回看

只加 F3，不另加 /history 命令或新 archive reader。
打开 modal 时冻结当前只读 snapshot，选最近20条可展示事实，按原顺序，允许翻页/滚动到每条全文尾部：

- USER_MESSAGE / ASSISTANT_MESSAGE：仅 content.text；
- CONTEXT_SUMMARY：仅 objective、constraints、decisions、completed、open_items、key_references 的已有公开摘要文本，标题明确“压缩摘要，非原文”；
- 不展示 provider_continuation/opaque_payload、reasoning、raw tool results、原始 metadata/JSON、私有扩展数据；
- 每个渲染页最多8000个 safe_display 处理后的字符；先安全处理再分段，不在单页把任意长文本直接渲染。页码/标题不计入正文预算；
- 顶部明确“当前 checkpoint 最近20条保留内容；不是完整历史”，不足20条照实显示；
- Esc 返回原界面并保留草稿/焦点；打开/翻页/关闭不提交 action，不调用 provider/tool，不写状态、不随后台刷新跳页。

### F4：多行编辑 modal

复用现有可选 Textual 依赖的 TextArea；不新增编辑器依赖：

- Enter 仅换行；F6 或显式“发送”按钮才提交一次；Esc 保存为草稿返回；
- 单行 Input 收到多行 paste 时转入同一 modal，保留换行，不截成首行、不自动发消息；
- 多行草稿留在 UI 本地，主界面显示“N行草稿，F4继续编辑”；不能把多行内容压进单行 Input 后丢换行；
- modal 内 slash 文本是普通消息内容，不解析成 /approve、/cancel、/new 等命令；普通主 Input 的现有 slash 行为保持；
- 提交仍走同一个 displayed-state / busy / closing / takeover / approval gate；若已有合法 active correction binding，用原 correction 入口，否则按既有 SubmitMessage 路径；
- pending approval 时不提交模型文本/纠正，不把 Enter 穿透给底层批准控件；拒绝后保留草稿。关闭/重载失败/unknown 等不合法状态同样拒绝；
- 普通消息/审批相关动作沿 modal 打开时的 displayed snapshot 绑定；不合法的状态变化后要求返回刷新，不偷偷重绑。active correction 则固定打开时的 ControlBinding（conversation/Goal/revision/invocation）并于发送前核对；仅 provider attempt 导致的无关 state revision 递增不使同一 ControlBinding 失效；
- 使用现有消息/上下文限制，不上调产品预算。消费与迟到回调遵守 S2-A。

### /new 可发现性

在帮助、终态摘要附近显示现有 /new 入口；不把普通追问自动变为新任务。
继续使用既有 new_session_gate：busy/pending/unknown 不放行；允许时回到现有 composition session loop，旧会话和证据不删除。

## S3-A：EV-02，先修旅程异常清理

入口：`journey_f2_restart_outclosing`。
两代 resources 各有独立词法作用域 ExitStack；resources 返回后立即登记其全部 closeables，**在 readiness 断言之前登记**。
第一代退出作用域、清理确认并核对 durable ledger 后，才创建第二代 owner；第一代失败不启动第二代。
每个 callback 最多尝试一次，逆序收尾；一个抛错仍尝试剩余 callback。以 (generation,index,error_type) 聚合有界失败，不泄漏原始异常内容。
任务失败与 cleanup 失败同时保留，不用最后一个异常覆盖另一层失败，不吞成 passed。
不复用手动 close 后又加 callback 的同一个 stack；保留生产“可信正常 shutdown→新 owner 补记”的语义。
DU-20 覆盖两代 open/readiness/ledger/close 各点；D06 已有 finally，保持并补回归，不扩成重写整个 browser owner。

## S3-B：EV-01，限定旅程子进程，不做生产 supervisor

删除 daemon thread.join 超时返回方案。仅此本地验证脚本使用以下固定控制方式：

1. _run_bounded 接收封闭旅程名 f2 或 d06、精确子目录和预算；不接收可执行任意 Python 的 callable/import/eval 配置。
2. 每条旅程单独启动当前解释器的同一脚本隐藏 child 模式，start_new_session=True；用现有 agent/process/group.py 验证该子进程 PGID。主模式的 all 顺序执行，绝不并行。
3. 子进程同步运行既有旅程。父进程保持 stdin 管道开启；子进程在资源创建/各步骤之间非阻塞检查管道 EOF。父进程关闭管道即一次 cooperative stop；子进程看到 EOF 停后续步骤并进入其 own finally，不能由父进程跨线程调用 Playwright close。
4. budget_seconds 默认120，启动资源前拒绝非有限数、零或负值；monotonic 工作截止。到期即锁存 timeout=true，之后即便返回正常结果也不能改回成功。
5. 到期/协议错误后关闭控制管道，最多给15秒 cooperative cleanup。仍未退出时，仅对本次 verified group 用已有 terminate_group：TERM grace=1秒，KILL grace=1秒，post-KILL verify=6秒。
6. 工作预算与清理预算分开；120秒任务的控制等待预算最多143秒（另有 OS 调度开销），**不承诺143秒内所有外部资源一定已清理**。确定性测试可注入较小常量以免真等143秒，生产脚本默认常量保持。
7. 只有成功且资源已确认清理才删除其精确临时目录；失败/unknown 保留本次目录并输出 retained_base。任何一条 timeout、协议失败、target失败或 cleanup-unconfirmed 都停止 all 的下一条；安全情况下其它非真实测试可继续。

### 子进程结果与父进程判定

子进程只在所有 owner finally 结束后输出一条终态 JSON，含：
journey、target_checks_passed、resource_cleanup_confirmed、failure_codes、details（既有有限旅程检查）。
布尔值必须是真 bool；无记录、多记录、缺必需字段、错误类型或非 JSON 均为协议失败。
只输出自己合成测试的数据/有界错误类别，不输出原始 stack、凭据或用户日志。

父进程同时有界排空 stdout/stderr，防管道满造成死锁；上限分别1 MiB / 64 KiB。
超限立刻记录 output_limit，走同一 stop/cleanup 路径，不无限读取或把全部输出写盘。
JSON 格式正确也不能覆盖父进程的 timeout/进程存活事实。

父进程最终记录：
journey、timeout、worker_terminated、resource_cleanup_confirmed、target_checks_passed、passed、retained_base、failure_codes，以及有界 details。
判定固定为：

`passed = not timeout AND worker_terminated AND resource_cleanup_confirmed AND target_checks_passed AND 无协议/控制失败`

- worker_terminated：子进程已 reap，且其 owned group 消失；不是仅 poll()!=None；
- resource_cleanup_confirmed：有效 child 终态 + 全部注册 owner 已正常返回 + 现有 browser/managed_web receipt/ledger 确认，无 cleanup error；
- 子进程/group 被 kill 只证明这一组；managed_web 的独立 session 或其它 owned resources 不因外层 group 消失而自动算 cleaned；
- 没有 child 清理报告时保守为 false，不能靠扫描全系统进程猜 true；
- timeout 后15秒宽限内获得真实清理报告，可以报告 cleanup=true，但 passed 仍 false；
- 不按 chrome/python 进程名 kill，不碰已有用户浏览器，不在活动/unknown 目录上 rmtree。

DU-21/22 必须有“拥有独立 session 的测试后代”反例：外层 group 停止不等于它消失。
测试自己用精确所有权在外层 finally 清掉测试后代；不能为证明泄漏而留下新泄漏。
这不是产品 scheduler、provider hard timeout 或任意程序沙箱；不引入通用 registry/服务。

## S3-C：代表离线恢复旅程

新增 `tests/acceptance/test_daily_use_recovery_journey.py`，只替换 provider 响应：
真实 composition/Runtime/ToolRuntime/LocalCheckpointStore/ControlInbox/typed action builder/审批和工具执行链不可绕过。

1. 新临时 workspace/state；任务明确一个产物和两个验证入口。实际受治理写入，再用 native read-only/off sandbox 跑 A/B。
2. 在可控 provider 等待点提交 CORRECT（改产物要求，不增权限）；到安全边界保存 receipt/fact。
3. 通过正常 Goal 修订/重新准入与审批，按新要求**真的改文件**；记录旧/新 digest 和工具执行次数。
4. 下一可控安全边界提交 PAUSE；必须看到 durable pause receipt 与 Goal PAUSED、run_turn 已返回，再关闭 composition。
5. 新建 store/composition/provider 重开；仅走现有合法 resume/准入动作，不重述原任务，不重新注入纠正。
   新 provider 的脚本决策必须检查 ContextPack 中实际任务、纠正和状态，不能复用旧实例的 Python 步数计数蒙混通过。
6. 完全相同验证命令、全新 call ID 再执行 A/B；权限/Goal revision 变化经原规则重批。assert 新 receipt 真执行，旧验证不能充数。
7. 正常 CompletionClaim 后核对 artifact 字节、当前 evidence、Goal VERIFIED_DONE、现有资源和 durable authorities 闭合。
   原写入/纠正/暂停不重放；正常 /new gate 可进入新会话，旧证据保留，该转换零 provider 调用。

安全边界暂停/重开不是 SIGKILL 崩溃恢复；UNKNOWN 由 DU-06 另测。
脚本 provider 证明指定链路，不证明真实模型自主规划。不改变 D04/D05 required_checks 或其未证结论，不扩成新评测平台。

## S3-D：来源身份、支持范围与交付文档

- 扩充 run_real_coding_scenario.py 的显式 _SOURCE_ALLOWLIST，只补本包相关公开文件：
  loop/state/contracts/evidence/control/checkpoint/views/compaction_rules，CLI app/render/actions，TUI app/render/adapter，
  composition/main，sandbox tools/authority/executor，本地 journey driver、process/group，以及本包实际新增的公开 helper。
  保留现有条目；不递归摄入 .env、state、日志、profile、依赖目录或根 tui/。
- 这仍只是已说明作用域的源码 SHA-256，不是 release seal，不引入新的记录平台/宽松兼容 reader。
  在临时副本分别改 loop/state/TUI/driver 一字节，应改变 identity；原文件不动。producer→validator roundtrip、未授权/预算不足零发送反例保持。
- README 的 D06 状态按三栏说明：10月5日执行者报告、10月9日独立复核范围、本包新验证；旧报告不是本次亲自复验，不抹掉 D01/D06 首轮失败。
- 旧 RESULTS 顶部保留历史身份和新入口；正文 PASS 作为历史保留。不能让旧 B03/B12/B13 覆盖本次反例。
- main 浏览器缺依赖的下一步提示与 README 本地 wheel/源码 extras 路径一致；不假设未发布的 PyPI 包可直接安装。本包只改提示，不安装依赖、不做付费探测。
- README 给短使用路径：非秘密 provider 元信息→用户安全注入 key→CLI/TUI→等待/控制→审批/恢复→结果/F3/F4→/new。
  不承诺完整历史、即时 kill、同步 CLI in-flight /pause、从零依赖安装或所有模型都可靠。
- 不提升 CURRENT_CAPABILITY_STATUS；macOS-first sandbox、专属 Chromium、受限 Skill/MCP/SubAgent、scheduler 未接 host 等限制保留。

最后严格按 ACCEPTANCE 对最终候选收口。真实 API 门当前关闭，不能继承旧授权或聊天中的 key。
