# Oracle Web 原始答复：日用闭环实施前设计复核

本次 session：`fa-daily-use-plan-20261009-0qfc99`。最高档 5/5，已捕获完整答复。
这是独立建议，不是实施授权或测试成绩；原始内容及 attachment 引用保留，仅规范化行尾空白。最终裁决以本包 FIX-PLAN / ACCEPTANCE 为准。

---

First Agent 日用闭环修复执行包：实施前设计裁决

结论：保留三个顺序切片，不增加第四片。CLI 保留同步执行边界，足以支撑本轮面向“懂终端、使用自己模型 API 的个人用户”的有界日用修复；不必为了与 TUI 对称而重写 CLI。

但有三个地方必须按下面的合同收紧：

CORE-01 不能用“所有沙箱调用免去重”修复；UI-01 不能把 deadline 或 Textual 的取消状态当作 worker 已结束；EV-01 不能把旅程进程退出当作所有独立会话中的浏览器、服务进程均已清理。

本次是基于附件的源码与设计复核，没有重新运行 pytest、Seatbelt、Chromium 或安装 smoke。143 项 focused tests、已有确定性反例和窄 wheel smoke，均保留为附件记录的历史证据，不计作本次新成绩。
2026-10-09-agent-product-readin…

A. 候选范围的最终裁决
切片	本轮保留的最小清单	明确缩减或延后
S1：工作闭环与安全控制	CORE-01；UI-01；UI-05；活跃控制绑定不存在或刚失效时的可见失败处理	不做 CLI 并发输入、CLI cooperative control；不增加工具阶段事件；不承诺强杀或撤销远端请求
S2：连续交互与可信结果	UI-02/03/04；F3 当前 checkpoint 有界回看；明确 /new 提示；F4 多行输入 modal	不做完整档案、历史搜索、跨会话浏览器、富文本编辑器；不读取 archive 原文
S3：可信验证与交付说明	EV-01/02；一条离线 scripted-provider＋真实 Runtime 的纠正、暂停、重开、复测、交付旅程；现有 readiness 错误提示；当前摘要与相关指纹；最终 full gate、窄安装 smoke	不跑全量真实 D 场景；不自动下载依赖、浏览器；不做真实 provider 调用；不提升 capability claim level
选定的交互方案

**CLI：**继续同步 run_turn。运行期间不接受 /pause 等新输入；运行中的 Ctrl-C 保留退出 130 和重开检查的语义。启动提示、/help、等待提示必须说清这一点。当前实现确实是在同步调用 run_turn 时捕获 KeyboardInterrupt，并提示远端请求或在途 effect 可能已经完成。
source-excerpts

**TUI 回看：**只选 F3，不再加 /history 同义入口。

**TUI 多行：**只选 F4 打开 modal，Enter 换行，F6 或可聚焦的“提交”按钮提交，Esc 保留草稿并返回。不把 Ctrl-Enter 作为必需路径。终端并不保证能区分所有组合键，Textual 官方也明确提示按键支持受终端和操作系统影响。
Textual Documentation

**运行进度：**本轮只接通既有 provider heartbeat，并保留清楚的控制请求提示。不新增 tool_started/tool_finished，也不把 invocation 结束后才交付的 TOOL_REQUESTED/TOOL_RESULT 包装成实时进度。

B. 确定实现合同
B1. CORE-01：独立、可失效的原生只读验证成功集合
当前入口与确定因果

本次修改入口为：

agent/runtime/loop.py::_drive 中 product-request gate 和 result checkpoint 后的 inventory 更新。
AgentRuntime._successful_product_request_inventory。
agent/runtime/evidence.py::ClosedEvidenceRegistry._may_invalidate_workspace_validation，以及原生 sandbox receipt 的可信解析部分。

当前 gate 在 ToolRuntime.prepare 前按工具名与 arguments 的 digest 拒绝重复成功请求；写入后只移除可变观察请求，sandbox_exec 不属于该集合。
source-excerpts

source-excerpts

附件记录的新 call ID 反例已排除“只是复用了 tool_call_id”的解释。应修的是语义成功请求 suppression 与证据失效不一致，不是 action replay。
2026-10-09-agent-product-readin…

选定机制

把当前成功 inventory 拆成三部分：

纯文本
ordinary_successes
    普通成功请求，包括现有可变观察请求。

mutable_observation_successes
    ordinary_successes 的子集，保持现有观察失效语义。

native_validation_successes
    独立集合：由可信原生只读验证 receipt 证明成功的请求。

模型请求的 suppression 判断为：

纯文本
request_digest 属于 ordinary_successes 或 native_validation_successes
且不属于既有 LOCAL_SAME_UID_PROCESS lease 治理例外
→ 按现有 duplicate_product_request 路径拒绝

**原生验证请求不再同时放入 ordinary_successes。**否则清掉验证集合后，普通集合仍会把它挡住。

什么能进入 native_validation_successes

建议在 evidence.py 提取一个窄的私有纯 helper，例如：

Python
_validated_read_only_native_receipt(fact) -> SandboxReceiptV1 | None

这不是新的 registry。它复用现有原生 receipt 校验，至少要求：

要求	判定依据
确实执行且成功	durable TOOL_RESULT 的 executed is True、is_error is False、真实退出码为 0
是原生 sandbox receipt	SandboxReceiptV1 严格解析、摘要一致，非仅检查 metadata 中某个字符串
实际只读隔离	receipt 的 mode=read-only、enforcement=confined，backend/profile 与现有可信投影一致
本轮只覆盖无网络验证	receipt 的 network=off
来源与绑定正确	由现有 ToolRuntime 原生 receipt 路径铸造，metadata 与 receipt 对应字段一致；请求与结果正确配对
不是合成工具证据	不接受 fake/mock/synthetic 标记的工具结果作为真实验证证据

现有 _native_sandbox_tool_receipt 已包含 receipt 解析、metadata 对照、Goal 绑定与退出结果校验，应提取复用，而不是在 loop 里再写一份较弱判断。
source-excerpts

**特别注意：摘要一致不等于来源可信。**还要补读 KernelToolRuntime 的原生 draft→receipt 铸造路径，确认模型可控 metadata 不能冒充这类事实。不得仅凭模型传来的 mode、argv、工具名称或 ISOLATED_SANDBOX 声明授予例外。

历史 receipt 的识别也不要求其旧 lease 现在仍有效。旧 lease 的当前有效性属于新一次 prepare 的权限判断，不是辨认历史执行事实的条件。

什么时候失效

验证集合的失效，与最终 evidence 使用同一套 workspace-validation 事实分类：

已执行的文件写入、编辑、目录创建，清空此前验证 suppression。
已执行的 same-UID process，保持现有保守失效规则；成功退出不能证明没有改写输入。
已执行但失败、超时或未满足可信只读条件的 sandbox，按潜在输入变化处理。
一个成功且可信的只读原生验证，不得使另一个此类验证失效。
executed=False 的拒绝、审批等待、未开始调用，不构成 mutation。
receipt 缺失、损坏或投影矛盾时，不能获得“可信只读、不会失效其他验证”的待遇。

当前 evidence helper 的 sandbox 分支只检查错误、退出码与 mode，没有在该分支完整核对 confinement。**本轮需要把“可信只读例外”接到上述共享 helper，而不是直接把当前较弱分支复制给 dedup。**这是 CORE-01 分类合同的一部分，不另开能力优化项。
source-excerpts

现有普通观察集合仍保留原先的失效方式。因此，只读 sandbox 可以让旧文件观察过期，但不能让另一项可信只读验证过期。

live 与 reopen 必须使用同一个事实折叠

选定实现是：**保留一个按 durable facts 顺序重建的 inventory 函数，入口重建与每次相关 result checkpoint 成功后的 live 更新都调用它。**不要继续维护两份分别写在 live 与 reopen 中的失效算法。

具体要求：

_successful_product_request_inventory 返回上述三个集合。
成功请求仍限当前 active run 的既有产品请求范围，并按当前 Goal/workspace 绑定处理验证 suppression。
mutation barrier 不得因“它是 operator fact”就被提前跳过；operator success 是否参与产品去重，与 operator mutation 是否使旧验证过期是两件事。
summary 不重建成功事实，不从 archive 找回 suppression。
在 result checkpoint 成功前，不把新的成功加入集合。
unknown、CAS 失败、恢复分类仍先走既有安全分支，不能通过重建集合继续执行。

重建所需事实已在有界 checkpoint 内，不需要持久化 generation、新 schema、全盘输入快照或依赖图。事实压缩后的 live/reopen 等价性必须补一个 focused 用例；若现有保留策略不能维持这一点，先停止冻结，不能直接添加新持久化平台。

明确不改

_is_lease_governed_tool 的现有语义、action replay、unknown recovery、lease 有效期/次数/Goal 绑定、审批和 EXECUTING → result checkpoint 顺序均不改变。允许重新到达 prepare，不等于允许直接执行。

B2. UI-01：退出等待不是永久闭锁
当前入口

agent/tui/app.py：

request_close、_on_close_deadline、_safe_exit、_execute、_refresh、_run_action。

当前 deadline 设置 shutdown_blocked=True，后续正常退出又要求其为 False，而再次 Ctrl-Q 直接返回，构成永久闭锁。
app

app

选定生命周期

不新增 durable 状态机。仅把 UI 本地关闭状态明确为：

情况	确定行为
首次 Ctrl-Q，存在 pending/running worker	标记 closing_requested；停止新提交与审批；只启动一个 deadline timer
deadline 到达，worker 未结束	标记 close_overdue，提示仍在等待；不退出、不强杀、不清理 owner
重复 Ctrl-Q，worker 仍未结束	保持同一等待，不重置 deadline，不创建重复 timer
worker 实际返回，authoritative reload 成功	无论 deadline 是否已到，允许退出
worker 抛错，但 reload 成功	显示有界调用失败与真实 checkpoint 状态；有退出请求则以失败退出码交还 composition
reload 失败	留在可见的“无法确认检查点”状态；禁止产品动作；再次 Ctrl-Q 只重试 reload
reload 得到合法的 EXECUTING/AWAITING_RECOVERY	可以退出 UI，但保留未知结果；退出不等于取消或清理已完成

**关闭不要求 Goal 已完成。**一个已经没有执行中的 worker、但 checkpoint 正在等待 recovery 的会话，可以安全结束前台交互；不能为了退出而改写 unknown。

不只看 adapter.is_active

当前 TuiAdapter.execute_once 在 finally 中把 active 清回 False，随后 _execute 还会调用 call_from_thread(_refresh)。因此“adapter 已不 active”与“本轮 worker 已完成回调并返回”不是完全相同的观察点。
adapter

app

选定最小调整：

_run_action 在调度时立即登记本轮 worker handle，覆盖“已排队、尚未进入 adapter”的窗口。
_execute 返回有界 outcome，不在 worker 内同步调用会触发退出的 _refresh。
由对应 worker 的完成通知在 UI 线程执行终态屏障、reload、渲染和关闭。
不使用 exclusive=True 的隐式取消来维持 single-flight；改为显式单飞 gate，禁止覆盖上一 worker。
不主动调用 Textual worker cancel。Textual 官方明确：thread worker 的取消状态不保证线程中的工作已经停止。
Textual Documentation
+1

可使用 Worker.StateChanged 接收正常完成；但 CANCELLED/is_finished 单独不能作为安全退出证明。Textual 8.2.0 的实现对取消的异步包装任务和底层线程工作有这一差别。
GitHub

这里的“worker 结束”指承载本轮 run_turn 的 callable 已返回，不要求线程池中的空闲 OS 线程被销毁。

修正错误提示的事实性

_bounded_worker_error 当前固定写：

action not applied; reloaded from last checkpoint

这对“effect 已发生、随后存储失败”以及“reload 自身失败”都过强。应改成两段：

纯文本
本次调用异常（异常类型）；操作是否生效以检查点为准。

只有 reload 真正成功后，才追加“已重载检查点”，并展示 pending recovery 等实际状态。不得输出原始异常字符串中的路径、参数或秘密。
app

cleanup 所有权

TUI 只结束交互并返回退出码。cleanup 仍仅由 composition owner 执行一次；TUI 不直接调用 browser closeable，不伪造 cleaned，也不把 owner cleanup 失败改成正常退出。

B3. 活跃控制绑定：失败要可见，不补发陈旧意图

入口：

TuiAdapter.request_control
on_input_submitted 的活跃纠正路径
action_cancel
action_pause_goal

当前 adapter 在没有 binding 时抛 RuntimeError；binding 在 current() 与 submit() 之间失效时，ControlInbox.submit 还可能抛 ValueError。
adapter

source-excerpts

选定处理合同：

**没有 binding、binding 已结束、store reload 失败，均不得传播成 Textual panic。**在 adapter 边界转换为窄的、可分类的控制请求失败，UI 显示相应有界提示。

对于尚未建立 Goal 的长首个 provider 调用，固定表达为：

当前调用尚未建立可控制的任务绑定，不能承诺暂停或取消。请求没有排入下一任务。

禁止在下一 Goal 建立时补发。current(binding) → submit(request) 竞争失败后也不自动重试绑定。

request_control 成功返回，只说明请求被当前绑定接受。后续显示仍是：

已收到请求，等待安全边界；尚未确认停止。

真正的暂停、取消或纠正生效，只由 checkpoint 中对应 control_receipt 和 Goal 状态确认。当前 Runtime 已按这一绑定在 _poll_control 中落盘控制结果，应保留。
source-excerpts

同一尚未确认的取消/暂停请求，重复按键不必重复入队。纠正文本在没有 durable 应用证明时保留为待核实草稿，不能悄悄丢失或自动重新发送。

B4. UI-05：接通真实 provider heartbeat，不扩工具事件

入口：

main.py 的 foreground composition 装配。
agent/cli/render.py::TerminalRenderer。
TUI 的 advisory 渲染分支。

主修复是：

Python
progress_event_sink=event_sink

用于现有前台 CLI/TUI 路径，而不是只在 TUI 时传入。当前非 TUI 明确传 None，Runtime 见 None 就不会启动 reporter。
source-excerpts

source-excerpts

附带的必要接线：

CLI renderer 接收 reporter 线程回调后，对事件去重状态与一次完整写出做窄锁保护；不在该锁内执行 Runtime、provider 或 tool。
provider_waiting 必须在阻塞 provider 返回前可见。
provider_finished 只表示该 provider 调用返回，不能显示为任务完成。
TUI 的等待提示不得覆盖关闭等待、控制请求待确认或 reload 失败提示。
provider finished 后，不再继续显示“模型仍在工作”；可显示“模型调用已返回，任务仍在处理”。

本轮不新增工具事件。当前 _emit 是写入 invocation buffer，不能因为渲染了其中的工具事件就宣称实时。
source-excerpts

B5. UI-02：草稿只随明确消费改变

入口：_refresh、on_input_submitted、新增多行 modal 的提交与返回。

**删除 _refresh 中无条件清空输入的行为。**来源切换、状态刷新、审批展示、错误重载、回看开关都不能修改草稿。当前 F2 就会调用这个刷新路径。
app

app

保留一份 UI 本地草稿，记录：

纯文本
draft_text
draft_revision
pending_submission_identity

这些不进入 checkpoint。

提交时绑定本次文本版本与 typed action。清空条件为：已确认该提交被消费，而且当前草稿仍是当时提交的版本。

不能用 RunStatus.COMPLETED 作为唯一消费条件：进入审批的提交已经消费；某些失败返回则可能未消费。必须沿现有 action replay/user fact 或 control receipt 的绑定判断。具体事实 ID 生成位置需要按 E 节补读。

无法确认时保留文本，并提示“提交结果待核实”，不得自动再次发送。用户在等待期间写出的新草稿，不得被上一提交的返回清掉。

B6. UI-03：流式身份、去重、旧事件拒绝和终态屏障

入口：

_drain_delta_events、_refresh、worker 开始/结束处理。
loop.py::_delta_observer_for、provider progress 发射点的窄身份修补。

当前 TUI 只拼接所有 delta，没有身份划分；CLI 虽然已有 identity 切换，但不能直接照搬“遇到不同 identity 就清空”，因为迟到的旧 identity 可能把显示切回去。
app

source-excerpts

选定身份合同

保留：

纯文本
identity = (conversation_id, run_id, revision, causation_id)

同时对 producer 做一个仅 advisory、非持久化的必要修补：

每次实际 provider generate 尝试，使用既有 owner_invocation_id 加 invocation 内递增 response 序号，生成唯一 causation_id。同一次尝试的 delta、started、waiting、finished 共用该身份，event_id 再包含事件类别与局部序号。

这样不必依赖“每次 provider response 都一定推进 durable revision”的未附假设，也避免同 revision 的重试复用 delta event_id。当前 delta 身份主要由 run/revision 构成，局部 counter 每次 observer 新建时重新开始。
source-excerpts

这不增加 durable generation、事件类型、第二 loop 或 provider 重放；只修改已有 advisory 的身份生成和传递。

Consumer 的确定规则
没有本地进行中的 dispatch，不接收新流式预览。
conversation、预期 run 不匹配，拒绝。
已见 event_id，忽略。
低于本轮已接受 revision/response 顺序的身份，拒绝；不得切回。
接受更晚 response 时，清空上一 response 的预览，不把两次回答拼接。
同一 response 的文本片段出现无法可靠恢复的乱序或缺口时，停止拼接该预览，提示“片段不完整，等待最终结果”；不猜测补全。
每次 run_turn 返回都建立终态屏障，不只在 Goal 完成时建立。等待审批、暂停、错误返回也结束本轮 advisory。
屏障之后到来的 delta、waiting 不得覆盖 authoritative projection。
worker error 即使没有 RunResult，也先关闭本轮 advisory；reload 失败不能让旧流继续占据状态区。

_refresh 不再无条件 drain 丢弃队列。普通 F2/重绘不建立终态屏障；只有本轮结束处理才负责封口。

流式预览只保存当前 response 的有界尾部，例如现有 2,000 字符范围；event_id 去重集合只活到本轮封口，不增长成历史库。完整交付文字仍来自 checkpoint/RunResult，不来自这个尾部。

B7. UI-04：权威摘要只在 projection 组合，不在 app 覆盖

入口：

agent/tui/render.py::project
_refresh
复用 delivery_summary_message、verification_scope_message

**删除 _refresh 用 result.message 替换整个 projection.main_text 的分支。**最终回答、任务状态、交付摘要和验证范围在 projection 层统一组合。当前 project 已生成正确摘要，随后 app 又将其覆盖。
render

app

确定规则：

checkpoint 的最新状态优先；旧 revision 的 result.message 不覆盖新状态。
新鲜返回和 reopen 展示相同的真实 targets、mandatory evidence 计数及已有权限/资源投影。
只给 VERIFIED_DONE 展示“Verified delivery”；RunStatus.COMPLETED 不能被翻译成“任务已验证完成”。
browser takeover completion failed 的专用提示保留，作为附加信息。
没有资源清理事实时，不从 completed 文案推导 cleaned。
/new 提示进入终态 hints：“Enter 继续追问；/new 开始新任务，旧记录保留”。
B8. 新 UX：只补两个有界入口
F3：当前 checkpoint 回看

通过 TuiAdapter.load_view() 获取一次只读快照，modal 打开期间固定该 revision，不持续追读，不调用 Runtime。

只投影最近 20 个可显示 fact：

用户消息的公开文字。
assistant 的公开文字。
CONTEXT_SUMMARY 中明确允许展示的摘要字段，标为“压缩摘要，不是原始对话”。

每页限制显示量，例如 8,000 个转义后字符；单条长消息允许前后翻页，不能无提示裁掉后半段。界面明确：

仅显示当前检查点保留的记录，不包含压缩前完整原文或任意 archive。

不 JSON dump fact.content；不展示 tool result 私有 payload、provider continuation、推理字段或其他未列入 allowlist 的内容。现有合同明确 provider continuation 不进入展示，summary 也不是状态权威。
KERNEL_ARCHITECTURE

F4：多行 modal

使用现有可选 Textual 依赖中的普通文本编辑组件，不加富文本依赖。Textual 已提供 TextArea 与 modal screen 的相关能力，但最终按当前安装版本完成 Pilot 验证。
Textual Documentation
+1

行为固定为：

纯文本
F4：打开/继续编辑同一草稿
Enter：换行
F6 或“提交”按钮：显式提交
Esc：保留草稿，返回主界面

多行草稿返回主界面后显示“已保留 N 行草稿，F4 继续编辑”，不能塞进单行 Input 后丢失换行。

多行 modal 的内容统一作为消息或当前绑定的纠正文本提交，不经过 slash-command 解析。粘贴 /new、/approve、shell 命令都只是文本。单行输入收到多行 paste 时转入 modal，不能逐行触发提交。

modal 打开时，隐藏在后面的 approve/recovery 快捷动作不可触发；Esc 返回后才恢复这些动作。审批面继续保持现有 literal-safe 和完整 preview cap：超过 cap 禁止批准，不允许通过回看页、分页或换入口绕过。
render

app

B9. EV-01：有限终止旅程执行者，不承诺所有 descendants 已死
当前问题与方案选择

当前 _run_bounded 启动 daemon thread，join 超时后立即返回；main 还能继续下一旅程并删除 base。这只能证明停止等待。
f2_f3_local_browser_journeys

选定方案：每条旅程使用一个专属子进程执行；父进程有限等待和收口；资源清理仍必须由该旅程的现有 owner 回报。放弃“到 120 秒所有资源必已死亡”的承诺。

不保留现有无限后台 daemon 作为超时处理，也不建设生产 supervisor。

驱动实现合同

只修改 scripts/f2_f3_local_browser_journeys.py 及其测试：

_run_bounded 改为接收闭合的旅程名称 f2/d06，启动本脚本内部 child 入口；不接受任意 callable 路径、eval 或动态 registry。
每条旅程拥有独立子目录；child 内同步执行旅程函数，资源在 child 的现有 owner/finally 中收口。
父进程用 monotonic budget 等待。预算必须是有限正数，非法值在启动前拒绝。
到界锁定 timeout=True，发出一次本地停止请求；child 在现有步骤间观察，停止开始新步骤并进入 finally。
给一个固定、有限的 cleanup grace，例如 15 秒。
child 仍未退出时，只对已验证属于本次 child 的进程组使用现有 TERM→KILL→有界确认 primitive。
此后无论 child 是否被终止，没有完整 owner 清理确认就记录 resource_cleanup_confirmed=False。
任一旅程超时、清理未知或失败，停止后续旅程；未确认资源退出的 base 不删除。

现有 process-group primitive 只证明指定组的存活情况。managed_web 明确用 start_new_session=True 创建自己的进程，不能由外层旅程组消失推导其已消失。
source-excerpts

source-excerpts

结果必须分开记录

建议沿现有 JSON 报告增加以下窄字段：

纯文本
timeout
worker_terminated
resource_cleanup_confirmed
target_checks_passed
passed
retained_base
failure_codes

其中：

纯文本
passed =
    not timeout
    and worker_terminated
    and resource_cleanup_confirmed
    and target_checks_passed

worker_terminated 只指旅程执行者及明确确认的本组范围；不得改名为 all_descendants_terminated。

正常路径的 cleanup 确认来自全部 owner callback 正常完成及现有真实 receipt/ledger；强制终止后不补造 receipt。Playwright 当前 close/shutdown 合同本身会在 worker 未退出或清理不确定时返回/抛出 UNKNOWN，脚本不能覆盖这一判断。
source-excerpts

超时即使后来清理成功，本次 passed 仍为 False，但可以如实把 cleanup 改为 confirmed。

不做的事

不 kill 所有 Chrome，不全机扫进程树，不猜测已失去所有权的 PID，不在 owner 仍调用 Playwright 时并发执行另一套 close。

未确认时保留本次专属目录、opaque session/resource ref 和失败阶段，作为处置依据；这不是自动恢复成功。真实 Chromium 运行出现该结果，就停止该条件门，不带着残留资源继续验证。

另外，现有 F2/D06 脚本直接驱动 KernelToolRuntime，不是完整 AgentRuntime 旅程。其工具层、观察层成绩不得被包装成模型自主完成或完整 D06 业务验收。
f2_f3_local_browser_journeys

f2_f3_local_browser_journeys

B10. EV-02：F2 两代 ExitStack 独立登记、独立收口

入口：journey_f2_restart_outclosing。

选定调整：

**第一代和第二代分别使用自己的 ExitStack，并各自覆盖完整 try/finally。**不复用“close 完再往原 stack 注册”的写法。

每代资源成功返回后，先登记全部 closeables，再进行 readiness assert 或 open 等操作。第一代正常收口并确认 ledger 后，才能创建第二代；第一代 cleanup 失败不继续创建新 owner。

callback 出错时仍尝试其他已登记 callback，并记录 (generation, callback_index, error_type)。完成所有尝试后必须向上报告失败，不能吞异常返回 PASS；同时保留原始任务失败与 cleanup 失败这两个维度。

至少覆盖：

纯文本
gen1 open 失败
gen1 close callback 失败
gen2 open/close 调用失败
gen2 某个 callback 失败但其他 callback 仍执行

每个已登记 callback 恰好尝试一次。调用过 callback 不等于清理成功。

D06 已有 finally，不重新认定其缺少 finally；只让驱动统一正确接收它抛出的清理失败。
f2_f3_local_browser_journeys

f2_f3_local_browser_journeys

B11. readiness 与交付说明：修错误下一步，不建 setup 平台

只修已确认矛盾：

main.py::_BROWSER_UNAVAILABLE_REASONS["browser_package_missing"] 不再无条件提示 pip install 'first-agent[browser]'，因为当前交付路径是本地 wheel，不能假定同名包已在索引发布。
source-excerpts

选定提示：

当前环境缺少 browser extra。请按 README 的本地 wheel 安装步骤，为当前候选 wheel 安装 browser extra；Chromium 二进制需另行准备。程序不会自动安装。

README 分清“已有本地 wheel”与“从源码构建 wheel 后安装”，实际命令使用当前产物路径及版本；不要写死旧 smoke 的 wheel SHA。浏览器下载仅作为用户另行执行的说明，本轮不运行。

集中列清：CLI 同步边界、TUI cooperative control 限制、当前 sandbox 平台限制、专属浏览器边界、离线验证范围。保留原有能力状态，不启动 promotion。

C. Red → Green 验收矩阵

以下用例以原缺陷或必要边界能在 Red 中失败为前提；不为了增加数量拆成大量重复测试。

S1
用例	Green 必须包含的因果断言	复用位置 / 建议名
CORE 正向闭环	A/B 真执行成功→真实 write 改变内容→同参数、新 call ID 的 A/B 再次真执行；新 receipt 支撑完成；最终文件正确	tests/process/test_r1_two_validation_completion.py；新增 test_write_then_same_native_validations_execute_and_complete
CORE reopen	在写入 checkpoint 后重建 store/composition，再请求同命令；不被 duplicate 拒绝，审批/执行正常	同文件，参数化 fresh/reopen
B03 因果修正	写后仅复测 B：新 B executed=True 且不是 duplicate；旧 A 不能充数，完成被缺失的新 A 证据阻止	加强 test_r1_midchain_write_keeps_invalidation_and_blocks_completion
多验证共存/无进展	A→B 均保留；无 mutation 再 A 被 suppression；重复相同失败反馈仍进入既有 no-progress 熔断	同文件及既有 kernel convergence tests
可信分类负例	模型 mode、伪 metadata、未 confined、receipt 损坏、network full 均不获得只读验证例外；executed error mutation 会失效，nonexecuted 不会	evidence/inventory focused 参数化测试
安全边界回归	exact action replay 零重复 invoke；unknown 不自动重跑；失效 lease 不授权；operator mutation 和重开重建一致	复用现有 replay/recovery/lease fixtures
退出 deadline	deadline 前后释放 worker 均能通过正常关闭路径退出；重复 Ctrl-Q 不重复 timer；worker 活跃时不调用 owner cleanup	扩展现有 Pilot close-deadline 用例
退出错误分支	worker error＋reload 成功可退出；reload 失败可见且可重试；合法 unknown 保留，不能伪造 Cancel/Cleaned	tests/tui/test_app.py
绑定竞争	首个 provider 无 Goal；binding 在 current/submit 间结束；均无 panic、无下一 Goal 补发；成功请求在 durable receipt 前不显示已停止	复用 _runtime_blocking、adapter/control fixtures
CLI 真心跳	真实 main 装配的 sink 非 None；provider 尚被 Event 阻塞时 writer 已收到 waiting；调用次数不增加；Ctrl-C 仍退出 130	tests/cli/test_daily_use_launcher.py、tests/cli/test_render.py、tests/kernel/test_runtime_progress.py

CORE 用例不能只断言最终不是 VERIFIED_DONE。必须检查对应调用的 executed、错误码、receipt、新旧 evidence 来源，以及实际文件变化。

S2
用例	Green 必须包含的因果断言	复用位置 / 建议名
草稿保存	F2、普通刷新、审批切换、错误刷新、F3/Esc 均保留草稿；已消费文本不重复发送；上一结果不清除新草稿	tests/tui/test_app.py
连续三轮流式	三轮分别显示，不拼接；同 run 多 response 分段；相同 revision 的不同 provider attempt 也不混合	test_stream_identity_isolates_runs_and_model_responses
迟到/重复/终态屏障	重复 event_id 无重复字；旧 identity 不回退；final 后 delta/waiting 无法覆盖摘要；乱序片段降级预览但最终正确	同一组 stream tests
fresh/reopen 摘要	同一 checkpoint 的 targets、证据计数、权限/资源投影一致；不能只检查“completed”或模型文本存在	tests/tui/test_render.py、tests/tui/test_app.py
F3 安全回看	长消息后半段可达；summary 标明非原文；工具私有 payload/continuation 哨兵不出现；零 provider/tool 调用，不读取 archive	test_history_projects_only_checkpoint_public_text
多行明确提交	paste、Enter、Esc 均不执行；F6/按钮只提交一次；slash 文本不转命令；超限不静默裁剪；modal 内不能批准隐藏 effect	test_multiline_draft_requires_explicit_submission
审批显示不回退	literal-safe 保持；overflow 仍禁 approve/Browser done，包括 /approve-artifact；回看和 modal 不形成旁路	复用现有 preview overflow tests
S3
用例	Green 必须包含的因果断言	复用位置 / 建议名
driver 超时	timeout 为失败；不运行下一旅程；不删除活跃 base；不以 child 退出自动标 cleanup confirmed	建议 tests/acceptance/test_local_browser_journey_driver.py
独立 session 反例	合成 child 创建独立 session 的受控后代；外层组退出仍不能签资源已清理；测试 finally 通过自己持有的精确控制句柄回收	test_timeout_does_not_claim_detached_descendants_cleaned
正常/失败清理	只有 owner 全部确认才签 cleanup；callback 异常或缺失完成报告即失败；task success 不覆盖 cleanup failure	同 driver tests
F2 两代异常	两代分别注入故障；已登记 callback 全部尝试、至多一次；gen1 失败不创建 gen2；失败不返回 PASS	同 driver tests，参数化
离线代表旅程	真实工具效果、纠正 receipt、暂停、重开、复测、新 evidence、交付、无重复 write 均有可观察断言	建议 tests/acceptance/test_daily_correct_resume_journey.py
安装态	从源码目录外 import 到新 venv 的 wheel 安装；Fake CLI、TUI mount/最小交互通过；无真实 key、无模型调用	复用原窄 smoke 流程

**用于测试 driver 超时分类的合成反例可以通过，但该次被测旅程必须明确失败。**不能把“测试正确识别 cleanup-unconfirmed”改写成“旅程 cleanup 已通过”。

D. 执行顺序与验证门
S1：先让任务能复测、前台能收口

先写 CORE Red 与 UI-01/控制绑定 Red，再实施。完成后仅跑 R1、evidence/dedup/recovery 相关测试、TUI lifecycle/control、CLI/progress focused tests，以及 touched-area 静态检查。

**S1 停止点：**新 call ID 的写后复测真实执行；unchanged-input suppression 保留；deadline 后 worker 返回可正常退出；CLI heartbeat 在 provider 返回前出现。

S2：复用 S1 的 worker 完成边界

先修草稿与 projection，再接 stream 身份及终态屏障，最后增加 F3/F4 两个小入口。这样不会为历史页或编辑器再造一套结果生命周期。

只跑 CLI/TUI/progress 和相关 typed-action focused tests，不在每个小改动后重复 full gate。

S3：先修验证器，再运行代表路径

顺序固定为：

纯文本
EV-01/02 合成故障测试
→ 一条离线生产 Runtime 代表旅程
→ 满足条件时跑专属本地 Chromium
→ 更新当前摘要和相关指纹
→ 最终 full gate
→ 新 wheel 的窄离线安装 smoke
离线代表旅程 J1 的固定合同

采用 scripted provider，但真实运行 AgentRuntime、ToolRuntime、checkpoint、审批和本地工具。provider 只能返回 ModelResponse，不能直接写文件、改 Goal、注入 evidence 或跳过审批。

旅程覆盖：

阶段	必须观察的事实
做事	Runtime 建立 Goal；实际写入候选；初次验证真实执行
纠正	通过现有 typed/control 路径提交新要求；先看到“请求收到”，再看到 durable correction receipt/Goal 变化
修改	按纠正执行实际受治理写入；记录精确执行次数与文件 digest
中断	本例选cooperative pause 到安全边界后退出，明确不冒充 crash recovery
重开	重新打开同一 workspace/session，并重建 store、composition、provider；不能复用 provider 的内存计数假装恢复
复测	不重述长任务；从 checkpoint/context 恢复要求；同命令的新调用真正执行，新 receipt 支撑完成
交付	目标文件内容符合纠正；完成证据指向新事实；fresh/reopen 摘要一致；已完成 write 没有重放
新任务	/new 走既有 gate，保留旧 checkpoint；新建入口本身不调用 provider/tool

为使重开真正依赖 durable 状态，新的 scripted provider 应从收到的 context/可信 Goal 投影选择脚本步骤，不能依赖重开前对象中的 calls 下标。

J1 可以签：

该合成任务在声明的本地环境下，完成了真实 Runtime 的纠正、暂停、会话重开、复测与交付闭环。

它不能签模型自主成功率、强制崩溃后的所有恢复分支、全部 D04/D05、外站浏览器或真实 provider dogfood。现有 D04/D05 过程未证项继续保留；不能因为 J1 通过就删除 _PROCESS_ONLY_UNVERIFIED 中的要求。
source-excerpts

本地 Chromium 条件门

仅使用已经安装、通过现有资格检查的专属 Chromium 和本地 fixture。缺依赖或资格不满足时记 blocked/not_run，不下载、不放松 guard、不用 fake qualification 冒充真实条件。

任一真实旅程出现 cleanup-unconfirmed，停止后续该门，保留目录，不强行凑 PASS。

最终 full gate 与安装态

对不再变化的代码候选运行项目要求：

Bash
git diff --check
.venv/bin/ruff check .
.venv/bin/python -m pytest -q -rx

通过后再按已有公开源码 allowlist 构建新 non-editable wheel，在源码目录外、清空 PYTHONPATH 的临时环境里复验。

可继续复用已安装依赖做窄离线 smoke，但必须保持原证据边界：不是干净机器依赖解析，不是全部 extras，不是真实模型安装验收。
2026-10-09-agent-product-readin…

最终 gate 后若又修产品代码，该候选的最终验证需要更新；“最终一次”不是允许拿修改前的 PASS 覆盖修改后的代码。

真实 API 门

本轮不执行。未来需要单独明确 provider/model、凭据注入方式、任务范围、模型请求/费用预算、允许的外部访问和终止条件。不能沿用旧对话 Key 或旧授权，也不能把 scripted provider 标为真实 dogfood。

E. 冻结前补读点、易误解处与停止规则
必须补读的公开符号

这些是附件未给出完整实现的窄缺口，不是新发现的 bug：

补读位置	冻结前要确认什么
loop.py::_drive 完整 result/恢复路径、_tool_result_fact；runtime/tools.py 中 SandboxReceiptV1.create 调用点；contracts.py::SandboxReceiptV1.from_json	原生 receipt 来源、tool_name/调用绑定、未知结果顺序、共享 inventory 接入点
runtime/state.py 中 SubmitMessage 接纳、USER_MESSAGE 生成、replay record、apply_control_request；压缩事实保留路径	草稿消费证明；correction/pause 的真实状态变化；live/reopen 折叠等价
runtime/views.py::project_goal_view/delivery_summary_message，assistant/summary fact 的构造代码	已有交付字段和公开文字 allowlist；不推测不存在的内容字段
browser/tools.py::owner_shutdown、playwright_adapter.py::_worker_main、managed_web.py 的 owner close/stop、managed_web_child.py	全部 closeable 的成功/失败合同；正常 cleanup confirmed 的真实依据
main.py / Composition 的最终 cleanup 与返回码处理；README、pyproject	UI 返回后只清理一次；失败返回码；当前 wheel/extras 的准确说明

补读若与选定合同冲突，应指出具体符号、具体冲突和最小补丁，不能自行扩成新架构审计。

不得混淆

“重复语义请求”不是“同 action replay”；“收到控制请求”不是“已停止”；RunStatus.COMPLETED 不是 VERIFIED_DONE；“调用结束”不是“资源清理完成”；“脚本模型＋真实工具”不是“真实模型”；“当前 checkpoint 回看”不是“压缩前完整历史”。

停止规则

出现以下情况就停止相应切片，不通过放宽判定继续：

CORE 正向复测仍未实际执行，或 B03 仍只能证明最终未完成。
需要取消未知 effect、放宽 lease/审批、全局关闭 dedup 才能使测试通过。
worker 未结束就退出 TUI，或 reload 失败被假装成恢复成功。
history/modal 需要读取未授权 payload、archive，或隐藏批准内容。
浏览器 cleanup 未确认，却要删除目录、继续下一旅程或写 PASS。
修改需要新数据库、第二 loop、动态 registry、持久化 generation 或生产 supervisor，而没有证明其不可替代。
最终测试失败、超时、截断，或安装 import 仍来自源码目录。

工作树以当前文件字节为准；记录本次实际触及公开文件的前后指纹，保留所有既有 dirty/untracked 工作，不 reset、stash、清理、提交或覆盖用户文件。相关 source allowlist 只补本包涉及的闭环关键文件，仍标为局部指纹，不伪装 release seal。
AGENTS

2026-10-09-agent-product-readin…

F. codex_execution_advice
YAML
codex_execution_advice:
  implementation_plan:
    - id: S0
      title: 冻结当前工作树与窄补读
      tasks:
        - 记录 HEAD 与本包公开文件的实际字节指纹，不把 HEAD 当完整当前源码身份。
        - 保留用户全部既有 dirty/untracked 工作，不执行 Git 写操作。
        - 补读 E 节指定符号，确认 receipt 来源、草稿消费证明和 owner cleanup 合同。
        - 将补读冲突记录为具体符号和最小修改，不开启开放式审计。

    - id: S1
      title: 工作闭环与安全控制
      tasks:
        - 先建立新 call ID 的真实写后同命令复测 Red。
        - 将可信原生只读验证成功请求从普通成功集合中分离。
        - 复用可信 receipt 解析与 workspace validation 失效分类。
        - 使用同一 durable-fact fold 支撑 live 和 reopen inventory。
        - 保留 unchanged-input suppression、action replay、unknown 和 lease 语义。
        - 修复 TUI deadline 后永久闭锁，关闭仅等待 worker 收口与 authoritative reload。
        - 覆盖已调度未开始的 worker 窗口，不使用隐式 worker cancellation 维持单飞。
        - 可见处理不存在或刚失效的 cooperative control binding，不补发陈旧请求。
        - 接通默认前台 CLI provider heartbeat，并明确同步 CLI 与 Ctrl-C 的限制。
      exit_criteria:
        - 写后同命令真正重新执行，新 evidence 支撑完成。
        - 多验证共存且未变输入重复请求仍受约束。
        - deadline 后 worker 返回可正常退出，未知结果不被取消或伪造。
        - CLI 等待提示早于 provider 返回。

    - id: S2
      title: 连续交互与可信交付
      tasks:
        - 移除刷新清空草稿，仅在确认消费对应提交版本后清空。
        - 为每次 provider 尝试建立唯一的 advisory response identity，不增加 durable schema。
        - 实现 event_id 去重、旧身份拒绝、乱序预览降级和每次 run_turn 的终态屏障。
        - 在 projection 层组合公开回答、交付摘要和验证范围，禁止 app 覆盖整段。
        - 增加 F3 当前 checkpoint 最近二十个可显示 fact 的只读分页回看。
        - 增加 F4 多行 modal，Enter 换行，F6 或按钮提交，Esc 保留草稿。
        - 多行内容不解析 slash command，modal 不允许操作背后的审批。
        - 明确终态后的 follow-up 与 /new 区别。
      exit_criteria:
        - 连续三轮不丢草稿、不混流。
        - fresh 与 reopen 的权威交付字段一致。
        - 回看不读取私有 tool payload、continuation 或 archive。
        - 多行 paste 不触发自动提交，审批 overflow 仍 fail closed。

    - id: S3
      title: 可信验证与交付说明
      tasks:
        - 将浏览器旅程 driver 改为专属 child process，不保留超时后台 daemon。
        - 分开报告 timeout、worker_terminated、resource_cleanup_confirmed 和 target_checks_passed。
        - 超时后有限收口；未确认 cleanup 时停止后续并保留目录。
        - F2 两代分别使用异常安全 ExitStack，所有已登记 callback 均尝试且失败上报。
        - 增加一条 scripted-provider 加真实 Runtime 的纠正、暂停、重开、复测、交付旅程。
        - 修复 browser extra 的本地 wheel 安装提示，集中说明现有支持限制。
        - 更新当前摘要、证据分层和本包关键公开源码指纹。
        - 对最终代码候选运行 full gate 与新的窄 non-editable wheel smoke。
      exit_criteria:
        - 超时及异常路径不会冒充 task PASS 或 cleanup confirmed。
        - J1 有真实执行次数、文件 digest、控制 receipt 和新 evidence 的因果断言。
        - D04/D05 未覆盖项和真实 API 门继续明确保留。
        - 最终报告对应本次真实候选文件和安装产物。

  non_goals:
    - 不新增第二 production model/tool loop、数据库、动态 registry 或 feature flag。
    - 不全局关闭 dedup，不全豁免 ISOLATED_SANDBOX。
    - 不改变审批、EXECUTING、result checkpoint、unknown recovery 或 lease 权限语义。
    - 不增加 CLI 并发编辑器或 CLI cooperative control。
    - 不增加工具实时阶段事件或能力 dashboard。
    - 不增加完整历史库、archive 搜索、富文本编辑器或跨会话档案浏览。
    - 不建设生产 supervisor，不扫描全机进程，不批量关闭 Chrome。
    - 不运行真实 provider、MCP、外站、登录项或付费调用。
    - 不自动安装依赖或下载 Chromium。
    - 不扩展为全部真实 D 场景或全平台验收。
    - 不提升 capability claim level，不发布，不执行 Git 写操作。

  optional_subagents: []

  verification:
    methodology:
      - 先 Red 后最小 Green，复用既有 fixture，不为测试数量增加重复用例。
      - CORE 正路径必须断言真实执行与新 receipt，不能只断言最终未完成。
      - 每个切片只运行 touched-area focused tests。
      - 本轮之前的 143 项测试和 wheel smoke 只作为历史证据。
      - cleanup-unconfirmed 的负例测试可通过，但被测旅程必须保持失败分类。

    focused:
      S1:
        - R1 两项验证、写后复测及 reopen
        - evidence 分类、dedup、replay、recovery、lease
        - TUI worker lifecycle 与 control binding
        - CLI main 接线、renderer 与 provider progress
      S2:
        - 草稿消费与保留
        - 流式身份、乱序、迟到事件和终态屏障
        - fresh/reopen delivery projection
        - F3 回看 allowlist 与 literal-safe
        - F4 显式提交及审批旁路负例
      S3:
        - child timeout 与独立 session 后代反例
        - F2 两代 ExitStack 故障注入
        - J1 离线真实 Runtime 代表旅程

    chromium_gate:
      condition: 仅既有安装且通过当前资格检查的专属本地 Chromium
      on_unavailable: 标记 blocked 或 not_run，不自动安装或弱化 guard
      on_cleanup_unconfirmed: 停止后续旅程并保留专属目录

    final_full_gate:
      - git diff --check
      - .venv/bin/ruff check .
      - .venv/bin/python -m pytest -q -rx

    materialized_install:
      - 从明确公开源码 allowlist 构建新的 non-editable wheel。
      - 使用临时环境、源码目录外 cwd 和清空的 PYTHONPATH。
      - 确认 agent 与 main 的 import 来自新安装的 site-packages。
      - 验证 version、非秘密 setup、Fake CLI 和最小 TUI 交互。
      - 记录 wheel SHA、实际依赖复用方式及未覆盖的 extras。
      - 不声称完成干净机器依赖解析或真实模型安装验收。

    real_provider_gate:
      status: 本轮未授权，不执行
      prerequisites:
        - 独立明确 provider 与 model
        - 当前凭据的安全注入授权
        - 任务和外部访问范围
        - 请求及费用预算
        - 停止条件与分层报告要求
