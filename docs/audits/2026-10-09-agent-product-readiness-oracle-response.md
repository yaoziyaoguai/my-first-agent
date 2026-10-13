<!-- 本次 Oracle Web 第 5 档原文。附件引用为 Oracle 页面渲染占位；建议不是实施授权，须结合本地复核报告。 -->

my-first-agent 产品可用性与必要能力审计
A. 直接结论

它已经是 Agent，不是只有聊天界面的工具集合；但“能够完成任务”和“能够自然、连续地使用”之间，仍有一段明确的产品化缺口。

我的判断分两层：

目标用户	当前状态	判断依据
自备模型 API、懂基本终端的个人用户	有条件可用的早期个人 Agent 产品候选。可以开展受支持的、有界的 workspace 工作，但不能据此宣布已达到稳定日用或通用兼容。	有真实的任务入口、审批、工具执行、状态恢复和验收投影；执行者报告 D01/D02/D06 已取得真实模型成果。主要障碍是运行中控制、进度可见性和结果回看，而不是缺少更多工具。
不了解内部实现、希望打开后自然交互的普通用户	尚未打通开箱使用的默认路径。	配置要求用户理解 provider/model/base URL/环境变量；CLI 与 TUI 的中止体验不同；TUI 的草稿、历史和退出路径存在具体问题。换成 Web UI 并不是解决这些问题的前提。

上述真实模型成果是执行者报告：修复后的 D01 为 12 请求，D02 为 12 请求，D06 为 23 请求，记录为 completed；不是本次重跑，也不是对 TUI、流式取消、所有平台或网站的验证。
attachments-bundle

已经形成的优势

最值得保留的是：做事、授权、恢复和“宣布完成”并没有混成一团。 CLI/headless/TUI 的可见调用端都进入同一个 run_turn；TUI 的控制请求另经 ControlInbox，实际执行仍由 Runtime 完成。CLI 也确实有 /new、普通 y/n 审批、暂停/恢复/取消以及来源查看，不是“毫无交互”。
attachments-bundle
attachments-bundle
attachments-bundle

可信交付摘要也已经存在：delivery_summary_message 从状态生成目标、产物路径、证据通过数和任务授权关闭状态，并明确验证范围不等于无限的语义正确性保证。因此，不需要重新建设一套“结果可信系统”，而是需要让已有结果稳定地呈现在用户面前。
attachments-bundle

最影响日常使用的瓶颈是：用户提交任务之后，不总能清楚知道正在做什么、怎样安全停下、刚才的结果在哪里，以及自己的输入是否还在。

本次依据所附 16 个文件快照做静态审查，没有重跑测试、安装包、Chromium 或模型 API。838cb2b… 是给定 HEAD；大量未提交修改意味着它不能单独代表此次修复后的完整产品身份。附件也没有包含所有 Runtime、browser、checkpoint 内部实现，下面不会把报告或测试名称冒充已独立核验的源码事实。

B. 最近修复：已完成与仍缺证据矩阵

总体裁决：不重开 R1/R2/F4 已解决的原问题；但不能接受 R3 中“驱动截止和异常清理已经全部闭合”的完整声明。

项目	实现与自动测试：附件实际支持什么	真实模型报告支持什么	本次独立裁决与最小补证
F1 / R1：旧验证失效、多验证共存、新 lease	RESULTS 报告了 evidence/state/loop 的准入修复。可见测试确实使用生产 session、composition 和 sandbox 注册，经过审批再断言至少两个不同命令指纹的 mandatory criterion，以及 VERIFIED_DONE。同命令二次批准的测试直接调用生产 _mint_sandbox_authority_lease，检查租约 ID 不同。	D01 首轮暴露重复 lease ID；修复后第二轮 12 请求完成。	保留“已实现、有针对性自动测试及真实场景报告”的结论。 测试设计不是只检查源码形状，也不是手工塞入最终已验收 criterion。但 evidence/state/loop 的修改体未附，本次未执行测试，不能签独立通过。需要补证时，仅补相关准入、失效和铸造函数及其对应版本，不重做机制。
F3 / R2：runner→validator 与 typed 完成证据	可见 runner 经 inspect_workspace_sessions 读取唯一合成会话；完成看 GoalStatus.VERIFIED_DONE；相关测试证明调用 ClosedEvidenceRegistry.derive；required checks 从 manifest 构造。roundtrip 测试调用实际 run() 和实际 grade()，分别断言 completed 与 incomplete。	D01/D02/D06 报告均为可消费的 RECORD_VALID/real_model/completed；失败轮保留 incomplete。	接线改进可确认，不再按成功文案或审批记录宣布完成。 validator 和独立 grader 内部实现未附，其全部拒绝规则本次无法独立核验；真实记录内容也未附，不能核对报告的每一项原始凭据。
F2 / R3：browser owner 收尾、新 owner 补记、dead worker	RESULTS 报告 owner shutdown 的可信闭合凭据、未知结果拒绝补记、dead worker 不重复等待。可见本地旅程调用生产 browser composition、KernelToolRuntime 和 session store，设计了正常 shutdown 后新 owner 补记检查；但 browser 实现和相关单测体未附。	D06 第二轮报告 start/open/act/close/stop 闭环。	保留正常收尾修复报告，不据附件缺失判功能不存在。 本地旅程是工具/浏览器边界测试，含驱动构造的审批上下文，不应替代完整 CLI→AgentRuntime 的真实用户旅程。内部实现的最小补证是 owner_shutdown、补记分支及 adapter shutdown 的 dead-worker 分支。
R3：本地测试驱动的截止与异常清理	_run_bounded 只 join(timeout)；超时返回时 worker 仍活着。另有 F2 旅程创建 ExitStack 却没有覆盖整个旅程的 with/finally。	正常完成的 D06 报告不证明超时和异常路径。	存在源码可确定的驱动缺陷与声明过强，不能签这部分全部闭合。 仅影响对应测试驱动及证据资格，不能外推为生产 Runtime 一定泄漏。详见 C4。
F4：archive/restore 锁残留、容量分离、inode 重验	附件只有修复记录及测试描述：容量与残留锁分离、有界清扫、post-flock 重验、12 轮及受控置换检查；没有 sessions.py、checkpoint.py 或 A20 测试体。	没有专门的真实模型证据；此问题也不以真实模型调用作为必要验证方式。	已修复报告保留，本次无法独立核验实现。 最小补证是 _load_candidates、_sweep_retired_locks、try_acquire 的相关段落，以及实际暂停在 open→flock 边界的测试。无需重写归档或放宽容量。

R1 测试的真实装配、终态/指纹断言和二次 lease 断言可直接看到；R2 的 typed 读取、derive 调用以及实际 producer→validator 测试也有代码支持。
attachments-bundle(20261009-082…
attachments-bundle(20261009-082…
attachments-bundle(20261009-082…
attachments-bundle(20261009-082…
attachments-bundle(20261009-082…

F2/F4 的修复范围和测试结果属于记录事实，不能提升为本次实现复验。
attachments-bundle

三个必须保留的证据限定

第一，3673 passed 不是当前快照全量绿的独立证明。 它是 2026-10-04 的执行者 gate；随后 10 月 5 日又修了 browser RFC3339 时间格式。附件没有证明该全量结果覆盖后一次改动及 10 月 9 日全部 dirty tree。与此同时，较早的 NOT RUN 已被后续明确授权后的 D01/D02/D06 记录更新，不能继续把真实模型层写成“从未运行”。
attachments-bundle

第二，离线贯通测试不是自主编码能力测试。 roundtrip fixture 先由测试代码修好 exporter，并创建 exit 0 的验证脚本。这对验证“真实 runner 能否读取 typed 终态并生成可消费记录”是合理的，但不能称为模型自己发现问题、写出修复并运行有业务含义测试的证明。
attachments-bundle(20261009-082…

第三，B03 的拒绝因果值得补强，但不是重开 R1 的理由。 当前结尾只断言没有进入 VERIFIED_DONE，没有在此断言实际写入 fact、被失效的旧验证以及对应拒绝原因。应在原测试中补足这些关键断言，防止未来其他拒绝路径意外让该测试继续绿，而不是增加一套新测试框架。
attachments-bundle(20261009-082…

C. 最多五项必要工作，按优先级排序

这里的 P1 表示直接破坏核心使用旅程，P2 表示应在随后的小切片补齐；不把所有体验改进都称为安全缺陷。

1. P1：把“请求停止”和“退出程序”做成可恢复的交互路径

类型：缺交互产品化；另含一个源码明确的 TUI 缺陷。

用户失败方式。 默认 CLI 在读取一次输入后同步调用 run_turn，直到返回才再次读取输入。因此 /pause、/cancel 的存在，不等于运行中能够输入它们。运行时 Ctrl-C 会落入 KeyboardInterrupt 分支，返回 130，要求重启检查；该提示诚实，但把一个普通“先停一下”的动作变成了中断恢复流程。
attachments-bundle
attachments-bundle

TUI 已有活跃调用的协作取消，不应重做这套机制。但有一个独立问题：

运行中请求退出 → 超过关闭等待期限 → shutdown_blocked=True → worker 后来返回 → _refresh 因 shutdown_blocked 不退出；再次退出和一般动作又被同一标志拒绝。

该标志在可见类中只有初始化为 false 和超时设为 true，没有恢复路径。这是交互闭锁，不是“保守地等待当前 effect”本身。
attachments-bundle(20261009-082…
attachments-bundle

位置。 agent/cli/app.py::run_repl 113–210；agent/tui/app.py::request_close、_on_close_deadline、_refresh、_permitted_state。

最小范围。 默认 CLI 先补一个可靠的 Ctrl-C 协作取消入口，复用已有 Textual-free single-flight adapter / ControlInbox 组合；不必同时支持运行中任意 slash command 或多任务输入。不能在 KeyboardInterrupt 已经解栈后，伪装原调用仍在继续。TUI 则在 worker 返回且 authoritative checkpoint 重载成功后，解除“等待 worker 超时”的界面闩锁，进入已有退出/收尾路径；仍有未知结果时保留准确提示，不伪造取消或清理成功。

可观察验收。 慢模型和慢工具期间能收到停止反馈，但在 Runtime 落盘前只能显示“请求已收到，等待安全边界”；不得启动下一笔普通任务 effect，必要收尾与 unknown 分类仍保留。旧 invocation 的控制不能作用于下一任务。另用受控阻塞验证：退出等待超时后释放 worker，程序仍能正常收口，而不是永久卡住；资源回调不重复执行。没有取消合同的 provider 不承诺瞬间终止，更不承诺远端撤销计费。

2. P1：稳定保留输入与交付结果，而不是不断覆盖同一个状态区域

类型：真实缺陷＋缺交互产品化；不是单纯审美建议。

用户失败方式。 TUI compose 确实只有状态、表单、单行 Input、提示和 Footer，没有会话 transcript。流式显示取累计文本末尾 2000 字符；最终结果并没有相同的 2000 字符裁剪，但仍更新同一 Static。因此不能说“长结果一定被最终截断”，也不能说已经提供了完整、可回看的会话阅读界面。
attachments-bundle

还有两处明确的问题：

草稿被刷新清空。 _refresh 在可输入状态下无条件设置 msg_input.value=""；切换来源引用也调用 _refresh。用户输入半句后切换来源视图，草稿就会被清掉。
attachments-bundle
attachments-bundle
交付摘要可能被结果文本覆盖。 project 已拼入 delivery_summary_message，但 _refresh(result) 在 result.message 非空时重新构造主文本，绕开了那份完整投影；不能保证目标路径和证据数量始终显示。
attachments-bundle
attachments-bundle

现有能力不能抹掉。 last_safe_result 可以恢复最后一条安全结果；CLI 会打印交付摘要，并提示 /new。所以缺的是稳定回看和跨刷新呈现，不是“历史完全没保存”或“没有最终结果”。
attachments-bundle
attachments-bundle

位置。 agent/tui/app.py::compose/_refresh/_drain_delta_events/action_toggle_source_refs；agent/tui/render.py::project；agent/runtime/views.py::delivery_summary_message。

最小范围。 在现有 TUI 内增加只读、可滚动的会话/结果区域，状态提示与 transcript 分开；从现有 canonical facts、last_safe_result 和 GoalView 做允许展示的投影，不新增 Memory 或第二份权威状态。草稿只在明确接纳提交后清空，普通刷新不能清空。提供一个有明确提交动作的多行粘贴入口即可，不建设完整编辑器。交付摘要始终独立于模型文本显示，并区分“本轮调用结束”“任务验收完成”“任务权限关闭”“资源已确认回收”。

可观察验收。 长结果在约定的终端尺寸下能访问开头、中段、末尾并复制；切换来源、刷新、窗口变化不丢未提交草稿；重启后无需再次调用模型就能看到最后结果、任务目标和产物位置；/new 保留旧 checkpoint。审批内容仍需完整、安全呈现，不能以截断预览、摘要批准或放宽原显示保护来换取易用性。

3. P2：让用户看懂当前步骤和停点，先用已有投影，不建设新监控平台

类型：缺交互产品化；CLI 心跳另有接线验证缺口。

用户失败方式。 Working... 能证明输入被接收，文本增量能证明回答正在生成，但不能解释“现在是在读文件、等待审批、运行验证，还是关闭浏览器”。CLI renderer 明确忽略 TOOL_REQUESTED/TOOL_RESULT 和多数进度阶段；TUI 的周期 drain 也主要消费文本增量和模型等待。
attachments-bundle
attachments-bundle

对初读观察的一处校正：CLI 有心跳渲染分支，不等于默认 CLI 的实时心跳接线已证。 main.py 只在 TUI 模式下注入 progress_event_sink，CLI 传 None。composition/loop 的默认处理未附，所以不能签“默认 CLI 一定实时收到心跳”。最小所需证据是这两个位置的 sink 选择及事件发送时序。
attachments-bundle(20261009-082…

位置。 agent/cli/render.py::_event_message；agent/tui/app.py::_drain_delta_events/_refresh；main.py 1637–1646；agent/runtime/views.py::GoalView/project_goal_view。

最小范围。 先把已有 user_outcome、progress_summary、next_step、blocker、resume_condition 展示出来，这些字段已经存在。实时部分复用现有 advisory progress 通道，只显示真实阶段、已等待时间、当前操作和等待用户的原因。不能仅取消 renderer 的忽略分支就宣称完成：架构文档说明普通事件可能锁后交付，必须验证用户在运行期间确实能看到。
attachments-bundle
attachments-bundle

可观察验收。 在受控慢 provider、慢工具中，阶段提示必须早于调用结束出现；工具“请求执行”不能提前显示成“已经执行”；没有真实进度就不造百分比。事件丢失、重复、重排不能改变审批、完成和恢复裁决；刷新最终由 checkpoint 校准。失败/恢复画面至少说明：原任务是什么、最后确认了什么、现在缺什么、用户可以做什么。

4. P2：修正测试驱动生命周期，并让当前证据声明与代码一致

类型：真实测试驱动缺陷＋验证缺口＋文档误导。

失败方式一：超时不等于停止。 _run_bounded 在 worker 仍活着时返回；main --journey all 随后还可以启动下一旅程，最终外层删除同一个 base。于是存在旧旅程继续使用资源、下一旅程开始或目录已经清理的交错。返回 passed=False 是诚实的，但 bounded stop, cleanup proceeds 以及 B13 的完整截止保证不成立。
attachments-bundle(20261009-082…

失败方式二：F2 异常路径没有保证执行清理。 journey_f2_restart_outclosing 注册了回调，却只在正常控制流中显式 close()；open、断言、ledger 读取或第二代 close 抛异常时，并没有包围整段的 with/finally。外层捕获异常不能替它调用这些回调。D06 的 finally 则确实存在，不能把两者混为一谈。
attachments-bundle(20261009-082…
attachments-bundle(20261009-082…

位置。 scripts/f2_f3_local_browser_journeys.py::journey_f2_restart_outclosing 151–200、_run_bounded 401–433、main 436–483；RESULTS.md 的 R3/B12/B13 声明。

最小范围。 仅修这个测试驱动：两代资源的注册和退出都放入覆盖异常路径的 with/finally；要继续声明硬截止，就使用仅限测试驱动的、可终止且可确认退出的受控进程边界，收尾仍调用已有资源 owner，不增加生产 Runtime 组件。未确认旧旅程退出前，不继续复用其 base，也不把删除目录当成资源回收证明；无法确认时记录 cleanup_unknown，不签 PASS。

同时更新最上层当前结论，保留旧记录但标明已被哪条后续记录取代。README 的“D06 尚未真实模型验收”应改为“已有执行者场景报告，当前版本/安装态仍有独立核验边界”，而不是继续写不存在，也不是直接升级全能力 claim。
attachments-bundle
attachments-bundle

还有一个身份限定：runner 的 _SOURCE_ALLOWLIST 没有覆盖此次关键补修所在的 state.py、contracts.py 等文件。因此现有 source_identity 应按局部源码指纹解释，不能自动等同于完整修复版本；补齐相关输入指纹或明确其覆盖范围即可，不需要新建身份框架。
attachments-bundle

可观察验收。 对两代 owner 分别注入异常、对旅程注入超时：其余回调仍被执行，未确认资源不报清理成功，旧 worker 未退出不启动下一共享现场旅程。正常 F2/D06 结果与超时/清理故障分别记录。报告中清楚区分测试驱动、生产修复、真实模型报告和本次版本，不能再用一次正常浏览器通过覆盖故障路径。

5. P2：收束 setup→首次成功任务的默认路径

类型：缺交互产品化＋一处安装指引不一致；进入第二层用户前必须补齐。

用户失败方式。 guided setup 仍要求手填 provider 类型、模型名、URL、环境变量名，保存后再手动 export key。这对第一层用户可以接受，不是安全设计错误；但“profile 已保存”不等于远端模型可用，也不等于用户知道下一步能做什么。
attachments-bundle
attachments-bundle

安装提示另有具体不一致：README 明确不假设 PyPI 已有发布物，推荐本地 wheel；browser 缺包提示却让用户执行 pip install 'first-agent[browser]'。这不能证明 PyPI 包不存在，但两条指引不是同一条已核对的安装路径。
attachments-bundle
attachments-bundle

位置。 main.py::_run_setup/_resolve_runtime_provider/_build_provider、readiness 输出；README 快速开始和 extras 安装说明。

最小范围。 基于仓库已经支持的精确配置提供可选预设，保留手动配置，并显示最终 destination/model/模式供确认；不自动猜兼容性、不静默关 strict、不改 credential 存储边界。复用现有 readiness 检查，明确区分“未启用”“当前不可用”“本地配置完备”，各自给一个准确下一步。先验证一个受支持环境中的 base CLI 默认安装路径，TUI extra 单独验证；不要求全平台安装矩阵。

可观察验收。 从源码目录外运行 non-editable wheel，setup 不发模型请求、不保存 key；缺环境变量、错误配置、未装可选依赖都能给出准确下一步。第一次真实外发仍经过 disclosure。离线 smoke 只证明安装和接线；远端认证、真实模型成功仍需另行授权验证，不能由 readiness 标签冒充。

D. 七个用户旅程短表

这里 available 表示已有入口和实现/场景依据，不表示本次亲自重跑通过；limited 表示能走但有明确限制；unverified 表示证据不足。

用户旅程	当前状态	具体判断
首次安装配置	limited；当前完整安装闭包 unverified	第一层用户可以按 wheel→setup→export 进入；第二层仍需理解较多配置。旧安装 smoke 不能覆盖当前所有 extras 和后续改动。
提交普通多步任务	available，限已支持范围	自然语言入口、Goal、审批、工具和验收链存在；D01/D02/D06 有真实模型完成报告。不能扩展为所有文档格式、所有代码库或所有网站可用。
了解进度并中止	limited	Working、文本增量和 TUI 协作控制存在；CLI 运行中输入受限，工具阶段显示不足，TUI 退出超时有闭锁。
审批与权限	available	CLI 普通 y/n、精确审批、目标/目录级授权及撤销已具备；第二层需要更清楚的可读解释，不需要更宽松的权限。
失败/重启恢复	limited；部分过程证明 unverified	session 选择、pending 决策、unknown recovery 已有路径；恢复界面的任务上下文仍偏薄。D04 的过程项未验证，不等于整个恢复能力不存在。
查阅结果并开始下一任务	limited	CLI 交付摘要和 /new 已有；TUI 可恢复最后结果，但完整回看、摘要稳定呈现、草稿保留有缺口。
日常连续使用	limited；长期稳定性 unverified	多会话、归档恢复和预算机制已有设计/实现报告；不能用一次场景通过或测试总数证明长期日用稳定。F4 保留修复报告，不重新判作已坏。

恢复入口实际会显示任务及部分进展；D04/D05 的过程项也被记录为未验证，而不是删掉检查项换取通过。
attachments-bundle
attachments-bundle
attachments-bundle

E. 哪些做重了，哪些做轻了，接下来只做三个小切片
做重了的部分

不是审批、checkpoint、证据失效做重了，而是可选能力与历史验收叙事在日常产品中占据了过多注意力。

对“处理当前目录资料、改小功能、做受治理浏览器任务”这一定位，继续推进 Scheduler host qualification、扩展能力晋级或全能力重绑，不能优先解决用户眼前的卡点。源码里的 main.run_schedule 存在，也不等于安装命令已经接上它：打包入口指向 agent.automation.cli:main，README 已明确当前安装入口没有可运行 host composition。应继续冻结，而非列为产品成立的紧急缺项。
attachments-bundle
attachments-bundle

TUI 默认审批表单还展示 request/binding 等内部标识；这些可以留给高级详情，不必让普通用户每次都理解它们。隐藏技术噪音不等于削弱底层精确绑定。
attachments-bundle

也不应因为一次局部界面修改，就把所有历史 milestone 全部重新审一遍；但正式 promotion 仍应遵守现有证据政策。局部可用性验证与全项目晋级应分开。

做轻了的部分

做轻的是最常见的前台行为：保留草稿、阅读长结果、知道当前步骤、停止后还有出口、重启后看得懂原任务、配置失败后知道下一步。 这些比新增工具更直接决定用户是否愿意第二天继续使用。

已有的单 Runtime、逐笔/任务级授权、/new、来源投影、交付摘要和恢复边界，足以继续搭建上述闭环。无需重写运行时，也不应该按文件行数拆分。

建议只安排三个顺序小切片
小切片	内容	停止条件
1. 能安全停，不会卡在退出	C1；加最小必要的“当前步骤/取消等待”显示。只改交互 adapter 和接线。	受控慢模型、慢工具、退出超时后返回、unknown recovery 都有明确出口；旧控制不影响下一任务；不提前关活跃资源。
2. 输入不丢，结果拿得走	C2，加 C3 中已有 GoalView 字段的呈现；让 /new 可发现。	草稿不因刷新丢失；长结果可回看复制；重启零模型调用展示现有结果与任务；审批保护和完成判定不变。
3. 默认路径可复现，证据能说明白	C4/C5：修测试驱动、校正文档、完成一个受支持环境的安装路径和代表旅程。	报告准确绑定候选输入/产物身份；离线、本地浏览器、真实模型、未验证项分别记录；不借机开启新能力或全项目 promotion。

第三片中的真实模型任务只能在用户另行授权后执行，且一个有区分性的代表任务即可起步，不需要扩成新一轮大规模基准。

F. 不做清单

暂缓新增 MCP 集成和 Skill 商店、远程自动加载扩展、向量库或复杂长期记忆、自演进系统、并行 Agent/第二套编排循环、后台 daemon 和开箱 Scheduler、个人 Chrome/全桌面控制、任意网站兼容、全平台移植，以及 Web GUI、团队空间、企业权限和云端控制台。

同样不做“为减法而删测试”、按文件长度拆分、重写 Runtime、放松 unknown recovery、取消精确授权，或用模型生成的总结替代 durable evidence。本轮要减少的是用户完成任务所需的额外理解和操作，不是减少正确性与安全边界。

YAML
codex_execution_advice:
  implementation_plan:
    - "仅作为建议，实施须另行授权。切片1：补默认CLI的协作停止入口，复用现有single-flight与ControlInbox；修复TUI退出等待超时后的永久交互闭锁，不改Runtime状态所有权。"
    - "切片2：在现有CLI/TUI内稳定展示Goal、当前步骤、交付摘要与可回看的结果；草稿只在明确接纳提交后清空；补一个明确提交的多行粘贴入口，保留原审批显示保护。"
    - "切片3：修复本地浏览器测试驱动的异常清理和截止证据，校正RESULTS与README的当前声明；核对相关源码身份，并完成一个受支持环境中的non-editable安装和代表用户旅程。"
  non_goals:
    - "不重写AgentRuntime、ContextManager或ToolRuntime，不建立第二套权威状态、Agent循环或编排框架。"
    - "不新增MCP、向量库、并行Agent、后台daemon、Scheduler接线、全平台支持、桌面控制或Web GUI。"
    - "不放宽审批、未知结果恢复、资源关闭和VERIFIED_DONE的证据门槛。"
    - "不因附件缺少内部实现而判功能缺失，不因旧seal漂移而重开全部历史问题。"
    - "不访问私有日志、调用真实模型API、注册后台项、提交、发布或改变权限。"
  optional_subagents: []
  verification:
    - "本次是附件静态审查；3673 passed及D01/D02/D06结果均为执行者报告，不是本次Codex或本审计者重跑。"
    - "每项验证记录实际被测的公开源码范围、相关文件或构建产物指纹、命令、环境、退出码和限制；HEAD与局部source_identity不能冒充完整dirty-tree身份。"
    - "控制验收覆盖运行中取消、无有效控制绑定、迟到控制、退出超时后worker返回及unknown recovery；请求收到不等于已停止，必要收尾之外不再启动普通任务effect。"
    - "显示验收覆盖长结果首中尾可读、草稿跨刷新保留、结果摘要不被模型文本覆盖、重启零模型调用回看，以及new保留旧checkpoint。"
    - "驱动验收分别注入第一代和第二代owner异常及超时；未确认退出不复用或删除现场，未知清理不得标记成功；正常旅程不能替代故障路径证明。"
    - "R1保留已有生产边界测试，针对B03补实际写入与证据失效因果断言；R2离线roundtrip仅证明接线和记录合同，不冒充自主修复能力。"
    - "F2/F4仅在需要独立复验时读取相关函数和关键测试，不要求全仓重审；未附内部实现继续标注本次无法独立核验。"
    - "离线测试、本地Chromium、安装smoke、真实模型与未验证边界分别记录；真实模型验证须另行授权，不自动重跑或重试未知请求。"

