# First Agent 日用闭环修复执行包：实施前设计复核（不是再次开放式审计）

你是独立架构与产品审计者。请用中文给出足够具体、可直接转成普通 Coding Agent 任务的方案。只提出建议，不修改文件/发布/发送消息。

## 目标与授权
用户要求结合刚完成的审计，用 Oracle Web 最高档和本地审计能力，输出详细、无歧义的执行资料包，之后交给另一个 coding agent 实施。本次不实施产品、不使用真实模型 API Key、不启动新的能力优化轮次。用户强调先能用、不要扩大范围、不要漂移。
主执行者可修改公开源码/测试/文档、做临时合成夹具和本地只读 Seatbelt/专属 Chromium 验证，但没有真实产品 provider、MCP、外站、登录项、发布或 Git 写权限。
允许你在内部交叉分析正确性/生命周期/产品交互，但不要要求本地再建多 agent 评审团队；最终 optional_subagents: []。

## 已知事实
仓库 main/HEAD 838cb2b66fbba674311d4d86fc7c4f4322fd8612，但很多 dirty/untracked 工作是用户的；HEAD 不代表当前源码。AGENTS、架构边界在附件：
AgentRuntime.run_turn 唯一 production model/tool loop；ContextManager 独占上下文；ToolRuntime 独占 callable。副作用保留 policy/approval、EXECUTING、result checkpoint。UI/advisory 非状态权威。无第二 loop、新数据库、兼容 fallback、动态 registry、feature flag、全盘快照平台。

上次 Oracle 审计完成后，本地补齐了 143 个 focused tests（28.61s）、Ruff/diff 检查、多个确定性反例，以及 non-editable wheel 窄离线安装 smoke（依赖复用，Fake CLI/TUI，不是全新机器依赖解析或真实 API）。审计全文附件有证据分层。不要把这些旧检查重新说成这次你运行的检查。

特别注意：CORE-01 是上次 Oracle 后本地新增且独立实测的缺陷，上次 Oracle 没看到相关 loop 代码。本次已附当前源码摘录和完整 R1 合成 provider +真实 Runtime/Seatbelt 测试：
成功验证 A/B → 真实 write_file → 新 tool_call_id、同参数 sandbox_exec B → executed=false/duplicate_product_request。旧验证证据正确失效，但新验证被 loop dedup 拦了。不是“同 call ID”的解释。

已确认缺陷：
CORE-01 P1 写后同命令复测误拒绝；
UI-01 P1 TUI Ctrl-Q deadline 后 shutdown_blocked 永久锁住，worker 返回也不能退出；
UI-02 P2 F2 来源切换清空未提交草稿；
UI-03 P2 不同 run/model response 的 streaming 文本串联，缺事件去重/终态屏障；
UI-04 P2 fresh RunResult.message 覆盖原本正确的权威交付摘要；
UI-05 P2 main 非 TUI 传 progress_event_sink=None，默认 CLI 等待心跳没接线；
EV-01 P2 浏览器测试 driver 用 daemon thread.join(timeout) 冒充 hard stop，仍运行时可销毁 base/开始下条；
EV-02 P2 F2 两代资源的 ExitStack 只有正常 close，无异常 finally（D06 已有 finally）。

## 候选冻结范围（请审查并给出最终取舍，不要无限列愿望）
最多三个顺序切片：
S1 工作闭环/安全控制：CORE-01、UI-01、UI-05；同时修 TUI 活跃控制绑定暂未建立/刚结束时 request_control 抛错的可见处理，仍不把“收到请求”说成“已停止”。
S2 连续交互/可信结果：UI-02/03/04；最小只读可回看（现有 checkpoint facts，不另建历史库）、明确 /new 提示、多行粘贴有明确提交路径。
S3 可信验证/交付说明：EV-01/02；一条离线 scripted provider +真实 production Runtime 的“做事→纠正→中断→重开→复测→交付”代表路径；更新当前摘要和相关指纹；最后一次全量 gate和窄 materialized install smoke。真实 API 是未来单独授权的独立门，不使离线 PASS 伪装真实 Dogfood。D04/D05 全场景未证项继续诚实保留。
不新增能力 dashboard/setup 大工程；只修现有 setup/readiness 的错误下一步提示、集中清楚写明支持限制。当前 browser 缺依赖提示 first-agent[browser] 与 README 本地 wheel 安装方式不一致，需给适用路径。
不新增 CLI 并发命令编辑器：候选决定保留 CLI 同步 run_turn 与 Ctrl-C=退出130/重开检查的现行边界，修 CLI 真心跳并如实显示限制；TUI 提供现有 cooperative pause/cancel。请评估这是否足以本轮有界“个人日用修复”，还是必须改 CLI 的某一最小点。别为对称性重写 CLI。
TUI 不做富文本富编辑器、搜索全档案、无限历史；候选是 F3 或 /history 打开当前 checkpoint 已保留事实的有界只读页（明确被压缩部分不是原文），Esc 返回保留草稿；多行使用一个显式 modal，Enter 换行、Ctrl-Enter 提交、Esc 保留草稿/返回，沿现有 typed action，不自动执行粘贴命令。快捷键可选已支持平台稳定键，不杜撰 Textual 行为。
以上新交互请判断哪些是必要最小产品闭环，哪些应明确延后；只给一个选定方案，不把未决“可 A 可 B”丢给执行者。

## 需要你重点裁决的设计细节
1. CORE-01：倾向“成功、受实际 confinement 约束的 read-only native sandbox validation request”单独进入可失效成功集合；用 durable fact/receipt 判定，不信任模型 mode/argv；潜在 workspace mutation 后删除对应 suppression；重建同语义。不是把所有 ISOLATED_SANDBOX 全豁免，不是把 sandbox_exec 简单加进现有观察集合（其它 read-only sandbox 自身是 EXTERNAL，可能相互失效）、不改 action replay/unknown/lease 权限语义。请选最小正确机制，说明可信分类与 live/reopen 一致性；保留 unchanged-input no-progress 和多验证共存。允许窄 private helper，不加持久化 generation/schema，除非证明必要。
2. UI-01：Ctrl-Q 只等待收口，不强杀；deadline 只表示仍等待，worker 终止+authoritative reload 后退出；worker错误/reload失败/unknown checkpoint/重复 Ctrl-Q 要有确定行为。cleanup只由composition owner，UI不能伪造cleaned/取消unknown。对还没Goal的长首个provider调用，cooperativecontrol binding 不存在应显示不能承诺取消，而不是 Textual panic或借下一Goal补发陈旧意图。
3. UI-03：流identity=(conversation_id,run_id,revision,causation_id)，去重event_id，拒绝旧身份回退，final result作为终态屏障；如何在不增加durable状态权威前提保证连续轮次/同run多个modelresponse/迟到event正确，给具体测试。
4. 运行进度：当前 _emit 常规events invocation末尾才deliver。不要仅把TOOL_REQUESTED渲染出来就谎称实时。是否本轮只接 provider heartbeat +明确已有control提示即可，还是要加很窄 tool_started/tool_finished advisory？请选择最小必要值并限定 payload 不含arguments/output/key。
5. EV-01：单独新建旅程子进程/processgroup并不自动保证Playwright worker/managed_web另起session的 descendants已死。请审查附件的所有权与shutdown代码，给不靠“kill所有Chrome/遍历全机进程”的最小可实施方案。可以放弃harddeadline承诺，改成诚实 timeout+cleanup-unconfirmed/停止后续且不销毁活跃目录，但不能用无限后台daemon或缺陷掩盖完成。需要有限测试驱动验收合同，区分workerterminated、resourcecleanupconfirmed、目标任务PASS。这个脚本修复不能演变成新生产supervisor平台。
6. EV-02 两代ExitStack分别登记/清理，即使callback抛错仍尝试其余，准确failure，不吞异常签PASS。
7. 只读回看/多行等新UX必须沿已有数据和typedaction，source内容 literal-safe、预览overflow不能隐藏批准内容。避免读取tool result私有payload/任意archive作为新泄露面；不能承诺context压缩前完整历史。
8. 一条离线correct/resume旅程的可观察断言与付费real-provider后续门：哪些能签本地闭环，哪些仍不能签全部D04/D05或模型自主成功率。

## 输出要求
A. 对候选范围的最终裁决：保留/缩减/延后，列明确最小清单；
B. 每个缺陷的确定实现合同：当前函数入口，选定方案，不改变什么、最小源码面；
C. Red→Green验收矩阵，至少：正路径、相关负路径、fresh/reopen、反例因果断言（不是最终not verified即过）；列适合复用的测试文件/新测试建议名；
D. 三个切片执行顺序、哪些检查只focused、最终一次full/materialized、本地Chromium条件门、真实API授权门；
E. 仍可能误解的地方与停止规则；
F. 最终 YAML codex_execution_advice，键 implementation_plan / non_goals / optional_subagents: [] / verification。

请不要泛泛倡议“加强UX/充分测试”，不要新增后台/插件/跨平台/全量真实D场景；不确定因附件不全的点明确需读哪个公开文件或符号，本地会补核实后才冻结包。
