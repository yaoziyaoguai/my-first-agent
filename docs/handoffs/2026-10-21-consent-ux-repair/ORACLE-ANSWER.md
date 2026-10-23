1. 执行判决

建议本轮实施一个有明确边界的组合修复：把已有文件授权变成当前提示中可直接选择的选项；新增显式、有期限和次数限制的 provider 会话授权。

这两部分分别解决不同问题：

文件审批的主要问题是交互过轻、默认路径过重。 已经具备可复用授权，却把最醒目的选项留给逐笔 yes，用户很容易连续批准而不知道还有更合适的选择。
Provider disclosure 的主要问题是授权模型过于依赖当前精确类别集合。 普通对话自然产生历史、控制回执或摘要，就可能再次要求用户确认。这里需要新增授权合同，单改文案不够。

我不建议全局信任工作区，也不建议把所有 tool_results 纳入常规会话授权。另一方面，把所有工具结果一律改成每次重新确认，也不能作为合格修复：它可能抵消文件审批减少的收益，让实际编码任务更难用。

本轮建议定为 三个实现包，加一次最终收尾验收。不扩大到 TUI 全量 parity、跨 write_file/edit_file 授权、通用来源分类平台或整个产品重新验收。

本审计完整读取了四份附件，只分析所附文本；没有运行探针、测试或仓库代码，没有核验完整源码哈希，也没有调用真实 provider。 SOURCE-IDENTITY.json 提供了基线和文件身份声明，但附件中的源码摘录不足以独立重算完整文件哈希。
SOURCE-IDENTITY

三个方案的裁决
方案	能解决什么	主要问题	裁决
只改文案、增加短 alias	降低文件范围授权的发现成本和输入成本	普通对话、恢复及压缩中的类别变化仍会触发 provider 确认	作为组合修复的一部分，不能单独交付
显式、有界的会话授权，配合已有文件/目录授权	减少已明确授权范围内的重复确认，保留新来源、新目标和危险效果的决策边界	必须补持久化、来源识别和两个发送路径的一致门禁	推荐
全局信任工作区、自动全允许	表面上减少确认	工作区身份不能约束同 UID 命令的全部能力，也不能等价授权所有未来外发来源	拒绝
2. 证据与差距
2.1 已经足以支持修复的结论
事项	判定	证据及限制
三轮普通对话发生两次确认	确认，P1	附件报告真实 Runtime、ScriptedProvider、三次 provider 调用；第二次确认只增加 conversation_history。证明了离线生产链上的确认负担，不证明真实网络或回答质量。
文件普通 yes 不创建范围授权	确认，P1	app.py:278–299 未传入文件/目录复用标志；scope slash 在 397–418 显式传入。
文件复用功能存在，但主提示仍引导逐笔批准	确认，P1	render.py:343–374 先展示 [y/N]，再展示长 slash 和范围说明。不是“没有能力”，而是决策层级不合适。
恢复后出现连续 disclosure	确认有界前缀	基线分别记录新增 conversation_history、control_receipts，且期间已有 provider 调用；不能据此宣称无限循环或整条恢复旅程失败。
A→B→A→B 类别振荡会改变摘要身份	builder 层确认	探针结果为 [true,true,true,true,false]；尚未证明完整生产 compaction 旅程发生同样四次打断。
普通与 compaction 各有精确 receipt 门禁	源码确认	loop.py:1589–1605、1739–1755。只改一处不能交付。
generic tool_results 可以作为常规低风险来源	不成立	缺少 source receipts 时会进入 generic 桶；当前类别不足以证明真实来源。

上述结论分别由基线输出、探针实现和源码摘录支持；尤其 file_choices() 是适配层探针，不能单独证明真实文件效果。题述已有“两次写入只批准一次”的 Runtime 测试，其完整正文未包含在附件中。
BASELINE
 
baseline_probe
 
SOURCE-SLICES(3)

2.2 两个必须纠正的语义误读
Provider 的旧 yes 不是“一次网络请求”

ProviderDisclosureReceipt 只有 request digest、确认动作序号和时间；没有一次性消耗、次数或到期字段。只要 descriptor、destination、model 和类别集合相同，后续请求可以继续匹配该 receipt。第三轮普通对话没有再次确认，也与这一机制一致。

因此，不能保持旧实现，却把 provider 的 y 文案写成“仅本次发送”。旧语义应描述为：

确认当前披露的精确范围；后续相同范围按既有规则匹配。

依据：contracts.py:1317–1400、loop.py:1739–1755。
SOURCE-SLICES(3)

文件和进程的 yes 也不能统一标成“逐笔”

文件普通 yes 确实不创建 Goal 范围授权；但进程现有预览已经披露 exact lease 的 8 次、60 分钟边界。接手者应核验其实际铸造链，保持既有语义，不能把文件提示中的“只批准一次”照搬到进程。

依据：process/tools.py:225–251、contracts.py:1998–2027。
SOURCE-SLICES(3)

2.3 需要定点补读的证据

以下是实现新增授权所需的补证，不是另开一轮全仓审计：

Provider 实际调用前后的 checkpoint、执行所有权和 CAS 路径。 目前只看到 disclosure 判断，不能证明撤销与真正发送之间已无竞争窗口。
ToolResult 写成 ConversationFact 的生产者。 需要确认哪些来源身份由 Kernel 写入，哪些只是工具返回内容或 metadata 自报。
Compaction summary 的落盘和后续投影。 当前摘录将 summary 分类为 conversation_summary，没有证明它保留了输入来源边界。
完整 checkpoint 编解码、action union/序列化，以及 headless/TUI 的旧动作入口。

这些符号没有补齐前，不能宣称“有限授权的持久化和新来源负控已经闭合”。

3. 单一推荐合同
3.1 授权分工：provider 用会话范围，效果继续用现有 Goal 范围

我选择 会话级 provider 授权，不再增加第二种 Goal 级 provider 授权。

理由是：provider 授权控制上下文外发；文件和进程授权控制具体效果。首次外发可能尚未建立 Goal，如果 provider 授权也绑定 Goal revision，任务刚建立或正常修订就可能再次询问，重新制造本轮要消除的摩擦。

必须在提示中说明：会话授权包含本会话后续的任务说明和对话记录。它不授权任何文件写入、命令执行、浏览器动作或其他工具效果。

项目	冻结合同
授权主体	当前真实用户提交的显式 typed action；模型输出、工具结果、历史文字不能铸造
会话	精确绑定 conversation_id
工作区	精确绑定现有工作区身份；未绑定时使用明确的 NO_WORKSPACE 状态，不能解释成任意工作区
外发目标	完整 provider descriptor identity、canonical destination、model
有效期	自授予起 60 分钟，绝对到期时间
次数	最多 32 次依该授权体系自动放行的 provider 派发；正常、compaction 和重试共同计数
既有预算	原模型 attempts、token、费用等限制继续生效，取更严格者
续期	只能由用户再次显式选择；恢复、重启、成功发送均不自动续期
撤销	一个 typed revoke action；不建设权限管理控制台

32 次、60 分钟是本轮建议冻结的工程值，不是已经证明最优的用户偏好。 它们不需要先做真实 API 实验才能实现。

3.2 实际发送类别与授权范围必须分开

保留：

ContextPack.data_classes：这次实际发送了哪些来源。
ProviderDisclosureRequest.data_classes：这次披露请求的实际类别。

新增：

有限授权中的 allowed_data_classes 或版本化 profile：用户预先允许哪些类别在本会话继续出现。

不得把实际类别改成固定大集合，也不得把工具结果、Memory 或其他来源重新标成 conversation_history。

建议常规 profile 为：

类别	是否进入常规范围	附加条件
system_policy、user_messages、conversation_history、goal、control_receipts	是	必须来自现有可信构建路径；不能把外部内容改名塞入
tool_schemas	有条件	绑定用户确认时已展示的工具定义及控制 schema 身份
conversation_summary	有条件	必须能够证明其输入来源均被该常规范围覆盖
tool_results	否	generic 桶本身不提供来源证明
workspace_excerpt、first_agent_history、Memory、preferences、recalled 等来源	否	另行精确披露
未知类别	否	不自动加入 profile

普通构建确实分别增加 tool_schemas、control_receipts；summary 又被单独映射为 conversation_summary。因此，上述两个附加条件有实际必要，不能只做字符串集合包含判断。依据：context.py:188–207、466–489、676–699。
SOURCE-SLICES(3)

工具 schema 的允许子集也必须精确定义： compaction 不暴露工具，或者暂时少暴露几个已经批准的工具，可以继续；新增工具、同名工具定义改变、控制 schema 改变，必须停止旧授权复用。不能仅按工具名称匹配。

3.3 保留一条精确回执，但给新模式补真实来源边界

这是本方案中最关键的取舍。

不建立“所有历史同意集合”的列表。继续只保留现有最后一条精确 request/receipt。

新增常规授权通过时，不要覆盖这条精确回执：

A 只含常规来源，走会话授权。
B 增加某个具体工具来源，用户明确确认 B。
再回到 A，仍走会话授权，不清掉 B 的回执。
再出现相同 B，可以复用该精确回执。
新来源即使仍叫 tool_results，也不能借 B 的回执进入。

第 5 点要求新模式下的 disclosure request 增加可信来源边界，并纳入 request digest。建议使用版本化的 request 合同，逻辑上至少包含：

所属有限授权的 grant_id；
实际 data_classes；
Kernel/ContextManager 验证出的 source_boundary 及其 digest；
原有 descriptor、destination、model 等身份。

现有 receipt 仍可只绑定 request digest，不必另建一套 receipt 仓库。

哪些来源可以稳定复用

本轮首先支持已经能由 Kernel 证明的内置文件工具结果：

同一会话和工作区；
同一已注册工具身份与 operation；
同一规范化目标；
相关 Goal/revision 或现有授权绑定一致；
结果确实来自该生产执行链，而不是工具 payload 自报。

每次执行身份用于验证结果真实性；可复用边界则取用户实际确认的稳定来源范围。不能把新的执行编号直接当来源边界，否则同一文件每改一次仍会重新确认。

仅有 tool_name="write_file" 不够。 接手者必须补读结果生产链，证明该身份由 Kernel 写入，并且不存在未经分类的追加来源。现有 SourceReceiptV1 可复用的部分应继续复用；不能信任 metadata.data_classes 自报。context_source.py:156–205 已明确展示这种校验边界。
SOURCE-SLICES(3)

对于不能证明稳定边界的 generic 结果：

绑定本次待发送上下文/派发身份；
明示“来源无法稳定核验，本决定仅覆盖这份待发内容”；
不跨新的结果或新的派发自动复用。

Memory、MCP、Skill、SubAgent 的新来源不能因同属 generic 桶而继承文件结果授权。本轮不要求改造这些系统的全部来源生产者。

如果连普通内置文件结果都无法在现有链上形成稳定、可信的来源边界，应停止宣称组合编码流程已修好；不能用每次自动 yes 或删类别来补齐验收。

Summary 的处理

新 summary 应保存由真实 compaction 输入验证得到的来源边界。只有可证明输入均为常规来源时，才允许作为常规 summary 复用。

旧 summary 缺少证明时，不自动升级。带有非核心来源的 summary 继续携带来源约束，不能只凭 conversation_summary 这个标签放行。

这是一处有限的来源继承，不应扩展成全仓通用污点追踪系统。

3.4 有限授权和精确回执必须共用同一个外层限制

禁止实现：

纯文本
旧 exact receipt 匹配 OR 新 grant 有效

这会让到期、耗尽或撤销后的 grant 被旧 receipt 绕过。

新模式的自动复用应满足：

纯文本
当前 grant 身份、状态、期限、额度均有效
并且
  常规范围覆盖当前真实上下文
  或者
  当前 grant 内单独批准的新版精确 request/receipt 完整匹配

两类自动放行都消费同一 32 次额度。

具体要求：

选择新会话授权时，不继承旧模式的 receipt 作为新版例外。
常规上下文通过时，可以保留最后一条新版精确例外。
授权撤销、到期、耗尽或失效后，精确例外也不能自动继续。
用户仍可明确批准新的待发送请求；这次批准不能恢复旧额度或旧期限。
在已撤销/失效的有限模式下，新的逐次批准须绑定当次待发身份，并如实显示范围；不能后台切回旧的无期限复用模式。

旧模式中的 y、旧 pending 和旧 /ack-provider DIGEST 保持原有精确确认语义，不自动铸造新 grant。 新模式下的 y 仍确认眼前披露请求；请求是否允许稳定复用、是否只覆盖当前上下文，必须由该提示明确说明，不能统一写成“只发一次”。

3.5 生命周期合同
情况	必须行为
新会话	不继承授权
更换工作区	旧 grant 持久化失效；不能重新绑定
更换 model、endpoint 或 descriptor	旧 grant 持久化失效；A→B→A 不得复活旧 A 授权
同会话建立或修订 Goal	基础会话外发可以继续；文件/进程授权仍按原 Goal 边界失效
pause/resume	不续期、不补次数；同身份且仍有效时复用
compaction	与正常发送共用判断和计数；实际来源仍如实分类
crash/restart	保留原到期时间、已用次数和撤销状态
n 或空回车	沿原入口语义拒绝/安全退出，本次不发送；不自动创建或扩大授权
撤销	清除可继续放行的精确回执，保留撤销状态或等价 fence；尚未发送的上下文再次拦截
未知来源或来源漂移	不走常规复用；建立新的明确披露
unknown effect	保持现有恢复优先级；授权不能成为自动重做依据

pause_for_provider_disclosure 已明确检查 unknown effect 优先，新增能力不得绕过这一顺序。依据：state.py:1671–1679。
SOURCE-SLICES(3)

3.6 持久化：需要新字段和 schema 11

现有字段不能无损兼任新授权。

现有 receipt 没有范围、到期、计数或撤销信息；现有 request 的类别必须保持“实际发送”；状态又要求 receipt 绑定当前 request。把这些字段改作预授权范围，会混淆含义并破坏严格解码。依据：contracts.py:1317–1400、4291–4296，checkpoint.py:1431–1487。
SOURCE-SLICES(3)

建议新增一个 provider_consent_grant 槽，至少包含：

grant ID、会话和工作区身份；
provider descriptor、destination、model；
profile 版本、允许类别、已批准 schema 身份；
授予所绑定的 pending request/授权范围 digest、动作序号；
issued_at、expires_at、max_uses、uses_consumed；
闭合状态，例如 ACTIVE / REVOKED / INVALIDATED；
完整性 digest。

到期和耗尽可由时间、次数计算，不必再维护一套重复状态。

新增独立的 grant/revoke typed action。旧 AcknowledgeProviderDisclosure 不增加会自动生效的 scope 默认值。新动作必须绑定刚显示的 request、scope digest、state revision，不能由 CLI 自行决定权限内容。

另有一个具体持久化陷阱必须修：

_encode_state 在没有 active run、workspace binding、现有 lease 等条件时，会选择 legacy v2。新增 grant，包括撤销/失效记录，必须纳入当前 schema 的选择条件。

否则普通对话完成、active run 清空后，授权可能保存不完整。原 schema 10 也必须保留为显式历史版本，不能只把 SCHEMA_VERSION=10 改成 11。依据：checkpoint.py:553–627。
SOURCE-SLICES(3)

迁移规则冻结为：

旧 checkpoint → 新 grant 为 None，不从旧 receipt、文件授权或进程 lease 推导。
旧 pending/request/receipt 保持旧 digest 和同意语义。
缺少新来源证明的旧材料不能自动变成新版精确来源授权。
v11 严格验证字段、枚举、时间、次数和 digest。
不批量迁移真实会话，不制作通用降级工具。
新 grant 使用真实带时区时间；当前旧 provider ack 中的 "operator-confirmed" 不能作为 TTL 起点。
3.7 CLI：用户应在第一次相关阻塞提示时直接选择
Provider 提示示例
纯文本
即将向远端模型发送内容
地址：https://example.invalid/...
模型：example-model
工作区：当前项目
本次内容：系统规则、你的消息

请选择：
  y  确认当前列出的精确披露范围
  s  在本会话允许下列常规内容继续发送：
     你的消息、对话记录、任务说明、控制回执、系统规则
     已列明的工具定义，以及来源可核验的对话摘要
     最多 32 次发送，60 分钟后到期
  n  不发送
回车：不发送

工具输出或其他新来源仍会单独披露。
撤销：/revoke-provider-consent

s 只在当前请求和范围候选可被 Runtime 验证时展示。若当前上下文包含无法纳入该范围的来源，不得把 s 当作批准这些来源的隐含入口。

文件提示示例
纯文本
需要批准：edit_file
文件：src/example.py
变更：……

  y  只批准这次修改
  f  执行本次，并在当前任务允许 edit_file 继续修改此文件
     最多 16 次，60 分钟；任务修订、结束或撤销后失效
  d  执行本次，并允许 edit_file 修改任务已列明目录 src/ 下的普通文件
     最多 16 次，60 分钟
  n  拒绝
回车：保持现有拒绝/安全退出行为

撤销文件范围：/revoke-goal-target

输入映射冻结为：

输入	映射
文件 f	与 /approve-goal-target 完全相同的 typed action
文件 d	与 /approve-goal-directory 完全相同的 typed action
Provider s	新的显式有限授权 action
y/n/空回车、现有 a、旧 slash	保持原入口的既有语义，不自动扩大
普通聊天中的 s/f/d	不解释成全局授权
不适用的 pending 中输入 s/f/d	明确拒绝；不降级成另一种批准，也不当业务消息推进

特别注意：f/d 不能实现成复制 y 分支再加布尔值。 现有 y、/approve 与 scope slash 在 authorize_obligation_rebind 等字段上并不完全相同；应复用既有 scope action 的完整构造逻辑。依据：app.py:278–299、397–418。
SOURCE-SLICES(3)

本轮明确不跨 write_file/edit_file 复用；目录必须来自已明确的 Goal 目录，不从当前文件猜父目录。已有要求独立确认的危险动作、artifact 确认和 unknown recovery 继续独立处理。

4. 逐包实现、测试、验收与回滚
工作包 1：有限授权、来源边界和持久化合同

允许修改

agent/runtime/contracts.py
agent/runtime/checkpoint.py
agent/runtime/context.py
agent/runtime/context_source.py
现有 compaction summary、ToolResult→ConversationFact 生产者中的必要字段写入；具体符号需先在公共源码中定位。

实现内容

新 grant、显式 grant/revoke action、严格来源边界合同。
旧 request/receipt 与新模式的版本区分。
常规 profile、schema 身份和 summary 来源证明。
内置文件结果的最小可信来源投影。
schema 11 编解码及旧版本读取。

最小 Red→Green

旧 schema 10 和所有当前已支持旧版本读取后，新 grant 均为空。
旧 pending/receipt 不因读取或确认而自动升级。
无 Goal、无 active run 的授权状态，保存重读后仍保留；撤销记录同样保留。
grant 字段篡改、非法次数、无效时间、未知 profile 拒绝。
新工具定义、来源不明的 summary、generic 新来源不能仅凭类别进入常规范围。
同一真实文件结果来源产生稳定边界；换目标、换工具、换来源产生不同边界。

停止边界

如果必须建设通用来源注册中心、改造全部 MCP/Skill/SubAgent，或重写 ContextManager 才能完成，停止扩大。保留已完成部分并报告具体缺失符号；不得降低来源要求来凑通过。

回滚

此包尚未启用时可以撤回接入；一旦产生 v11 状态，后续回滚必须保留 v11 解码，不能恢复旧 checkpoint 冒充兼容。

工作包 2：单一发送门、额度和撤销闭环

依赖：包 1。

允许修改

agent/runtime/state.py
agent/runtime/loop.py
必要的既有 action 合法性、派发 intent 和结果恢复符号。

实现内容

正常与 compaction 共用一个授权判定。
常规范围通过时保留最后一条新版精确回执。
所有新模式自动复用都受相同 grant 的 TTL、额度和撤销限制。
发送前 durable 计次，沿现有 owner/CAS 协议完成派发。
身份变化持久化失效；不允许 A→B→A 复活。

最小 Red→Green

三轮普通对话：从附件中的两次 provider 确认降到一次，三轮全部完成。
生产链中的 A→B→A→B→B：已确认且来源相同的 B 不因中间 A 而丢失。
第 32 次可用，第 33 次不能自动发送；失败不退款，重启不补额度。
已持久化 provider 结果的恢复不再次调用 provider、不重复消费额度。
build 完成后、真正派发前提交撤销，两条发送路径都不得再调用 provider。
撤销、过期、耗尽后，旧 exact receipt 不能兜底。
unknown effect 仍进入原恢复决策，不能自动重做工具。

撤销竞态的验收不能省略

必须证明“检查 → durable 计次 → transport handoff”与撤销动作有可解释的先后顺序。只在 build 时读一次 state，或者只有一次 CAS，不能证明这一点。

可兑现的用户合同是：撤销已被 Runtime 接受后，尚未开始派发的请求必须停住；已经交给 transport 的请求不能收回。

回滚

关闭新 grant 的自动复用并持久化失效，保留执行、结果、unknown 和计数记录；不恢复到效果发生前的 checkpoint。

工作包 3：CLI 可见选择、兼容与组合旅程

依赖：包 1、包 2。

允许修改

agent/cli/app.py
agent/cli/actions.py
agent/cli/render.py
agent/runtime/views.py
对应 README 段落及现有相关测试。

实现内容

显示和解析共用权威 pending 投影。
增加 s/f/d，保持旧输入语义。
展示“本次实际发送内容”和“未来授权范围”两个不同概念。
增加一个 provider 撤销入口。
旧 TUI/headless 动作不创建新授权；不要求补完整菜单 parity。

最小 Red→Green

f/d 与既有 slash 的完整 typed action 等价，不只比较两个布尔值。
不适用选项拒绝，不静默降级。
用户输入期间 state revision/request 变化，CAS 失败，provider/tool 调用均不发生。
新 CLI 提示 → 人工指定输入 → typed action → durable grant → 实际 provider/tool 效果贯通。
TUI/headless 旧动作、新字段缺省、旧 checkpoint 均不产生额外权限。
进程仍按现有 exact lease 披露，未被文件“一次”文案误导。

回滚

撤回新短选项和相关展示，保留新 schema 读取及撤销能力；不删除现存授权和执行记录来制造“回到旧版”。

最终收尾：固定确认预算
计数口径

每条固定工作流至少记录：

预定工作数、实际完成数；
provider 确认次数、文件/目录确认次数、进程确认次数；
unknown recovery 决定次数；
实际 provider 调用数、工具调用数、唯一效果数；
grant 消耗、撤销状态、最终结果。

/pause、/resume 等控制输入另列，不混入“授权确认减少”。

被拒绝或被拦截的任务可以是安全验收成功，但不能计入业务完成分母。 提示少了、调用也没发生，不是体验改善。

建议冻结的工作流
固定工作流	确认预算	成功分母与必要结果
同 provider 三轮普通对话，首次选 s	Provider 1，效果 0	3/3 完成，实际 provider 调用 3 次，类别如实增长
同 Goal、同工具、同文件连续三次修改，首次 f；本地 ScriptedProvider	文件 1，provider 0	3/3 真实文件效果，最终内容正确
明确 Goal 目录内三个普通文件，首次 d；本地 ScriptedProvider	目录 1，provider 0	3/3 效果；目录外、敏感路径仍拦截
同 exact process identity 连续三次验证；本地 ScriptedProvider	进程 1，provider 0	3/3 合成命令实际完成；身份漂移必须重新决定
远端 descriptor、同文件三次修改，首次 s、f，首次文件结果单独确认	Provider 2，文件 1，合计 3	固定四次模型响应、三次文件效果全部完成；后续同来源结果真正复用
有效授权下完整暂停/恢复和真实 compaction，全部为已批准常规来源	初始 provider 1，之后新增 0	预先冻结的模型步全部结束；生产正常/压缩路径都实际走到；无效果重复
A 为常规来源、B 为同一已单独批准来源的五次生产发送	初始授权 1＋B 确认 1	5/5 实际发送；不能用 builder 摘要比较代替
新敏感来源、新 provider 或换工作区，选择拒绝	新增必要拦截；拒绝后未授权发送 0	记为安全成功、业务未完成
build 后撤销，恢复旧调用链	新批准前发送 0	正常与 compaction 都成立
到期、耗尽、CAS 漂移、unknown outcome	不允许自动续权或自动重做	明确阻断原因，不记为任务完成

表中的新预算是建议验收目标，不是附件已经测得的修复结果。尤其远端 descriptor 的组合编码行必须在实施前固定输入、来源和预期效果，再采集旧基线，不能事后改 fixture 凑出数字。

本地 ScriptedProvider 的三行专门验证效果授权，不可拿它们证明外发确认已经减少。远端 descriptor 的组合行负责检验两类确认叠加后的实际体验。

测试方法限制
输入序列预先固定，例如 s → f → y；多出提示应直接导致测试失败。
不得使用“只要 awaiting 就自动 yes”的循环作为新验收驱动。
不得 monkeypatch 授权判定、来源分类或 provider 门禁。
可以用 ScriptedProvider 和临时合成工作区，不使用真实凭据、会话和私人目录。
普通文件来源无法稳定复用时，组合行标为未通过；不能只拿聊天行宣称本轮闭合。
最终一次完整门及安装态

三个包完成 focused 验证后，在最终候选上运行既有完整门：

纯文本
git diff --check
ruff check
完整 pytest

保留仓库现有准确命令。失败、超时、截断都不算通过；不得靠重复全量运行掩盖不稳定。

安装态必须使用本候选新构建的 wheel，记录：

基线 HEAD、候选公开 diff 身份；
wheel SHA256；
安装路径和实际导入模块位置；
离线安装及固定旅程结果。

在 checkout 之外的临时目录运行，排除 PYTHONPATH 或当前目录把源码树混入安装态。缺少离线依赖时报告阻断，不改为联网安装。

原有 4054 passed/1 skipped、安装态 76、真实 E2/E3 状态保留为历史记录；本轮不能据此改写为“全部产品验收通过”。

5. 未决与排除项
可以直接冻结的工程选择

以下不需要再问用户一轮：

provider 采用会话级授权，文件/进程继续现有 Goal 级边界；
32 次、60 分钟作为第一版固定上限；
独立 grant/revoke action；
schema 11，旧授权不升级；
f/d 严格别名复用；
一个 provider 撤销入口；
正常与 compaction 共用门禁；
不跨 write_file/edit_file；
不建立历史授权列表或权限控制台。
仍需真实用户评估的内容

合成测试能证明“选择这些选项后，确实减少确认且不扩权”，但不能证明：

用户是否一眼理解 s/f/d；
用户是否愿意选择这些范围；
32 次、60 分钟是否适合其真实工作节奏；
多来源真实编码任务的总确认负担是否已可接受。

这应在离线交付后，用一个固定的实际任务观察，而不是先做多轮泛化调研。

真实 API 当前未获授权。 如以后需要，建议单独申请：一个任务、至多 5 次外发尝试且包含重试、独立的新费用上限；用用户当次提供的凭据经现有入口注入。到界即停，不读取历史聊天 key，不借旧预算，不无限复跑。

本轮排除
全局信任工作区、自动 yes、prefix/wildcard/shell allow-all；
把 local_process 宣称为 OS sandbox；
把测试命令或脚本名字当安全证明；
所有 generic 工具结果的广泛自动授权；
通用来源治理平台、第二套权限引擎、第二个 Agent loop；
TUI 全量 parity；
E2/E3、其他产品能力重新验收；
修改业务 grader、历史结果或安装基线以宣称通过；
读取未知 result.phase.json、真实会话、凭据及私人目录；
修改密钥、系统登录项、后台服务、VPN、路由或基础设施；
本轮提交、发布和真实 API 执行。
6. 可直接复制给普通 coding agent 的执行指令
纯文本
任务：First Agent 确认疲劳有界修复。
基线：97f5c584e9e266930fbcf283aa3199b3609e8178。

本执行稿只有在用户另行明确授权实施后才允许修改代码。
当前审计结论不构成实施、真实 API、提交或发布授权。

目标：
1. 把现有文件/目录授权提升为当前 CLI 提示中的 f/d。
2. 新增显式、会话级、60分钟/32次的 provider 有限授权 s。
3. 用固定合成完整工作流证明减少确认且不扩权。

保持唯一 AgentRuntime.run_turn、ContextManager 上下文所有权、
ToolRuntime callable 所有权及现有 policy/checkpoint/恢复链。
不新建 loop、权限引擎、授权历史库或管理控制台。

先核对公共源码基线和已有工作树；不重置、不覆盖未知文件。
定点补读：provider实际派发/owner/CAS/结果恢复、
ToolResult→ConversationFact生产者、summary落盘、
完整checkpoint编解码和旧TUI/headless action入口。
不读取凭据、真实会话、私人目录或未知result.phase.json。

按三包实施，每包先Red后最小Green：
A. grant/来源边界/schema11；
B. 正常和compaction共享发送门、计数、撤销及恢复；
C. CLI s/f/d、旧入口兼容及完整组合旅程。

合同：
- provider绑定conversation、workspace、descriptor、endpoint、model；
  同会话Goal修订不扩大效果权限，文件/进程仍按原Goal边界失效。
- 实际data_classes保持真实；授权profile独立。
- tool_results及Memory/MCP/Skill/SubAgent等不自动进入常规profile。
- tool_schemas绑定已展示定义；summary须保留可验证来源边界。
- 保留最后一条精确request/receipt；常规grant通过时不覆盖它。
- 新模式精确复用须绑定当前grant及可信来源边界，
  同受TTL、次数、撤销限制，禁止旧receipt OR grant兜底。
- 无法证明来源的结果只能明确批准当前待发上下文，不能稳定复用。
- 内置文件来源若无法稳定证明，组合确认预算不得报通过。
- 撤销/身份漂移持久化；A→B→A不得复活；restart不续期不补次数。
- 派发前durable计数；未知派发结果不退款、不自动重发；
  已持久化结果恢复不得再调用provider。
- 旧checkpoint/pending/y/slash不自动升级；新grant须独立显式action。
- schema11保留原10及现有旧版本支持；无active_run时也不能丢grant。
- f/d与既有scope slash完整typed action等价，不简单复制y加布尔值。
- 不跨write/edit；不猜父目录；不放宽process exact lease。

固定验收：
三轮零工具远端descriptor对话：1次provider确认、3/3完成；
同文件三次修改：1次文件确认、3/3真实效果；
明确目录三文件：1次目录确认、3/3效果；
同exact命令三次：1次进程确认、3/3实际执行；
远端descriptor同文件三次修改：2次provider+1次文件确认，
固定4次模型响应和3次效果全部完成；
有效scope下恢复/compaction不得因已授权常规类别涨落新增确认。
新增来源、目标变化、撤销、过期、耗尽、CAS漂移必须保留必要拦截。

输入序列预先固定，多一个提示即失败。
不得自动yes、猴补授权、删类别或把被阻断任务计入业务完成。
同时统计provider/效果/恢复决定、实际调用、唯一效果和完成分母。

局部只跑focused测试；最终候选跑一次既有完整门。
安装态使用新wheel、固定来源、离线依赖、checkout外运行并记录身份。
保留4054/1、76及真实E2/E3历史状态，不改grader或旧报告宣称全产品通过。

安全回滚保留schema11读取和当前效果/结果/unknown记录，
将新grant失效；不得回放效果发生前的旧checkpoint。

交付：改动理由、精确范围、Red→Green、固定确认预算实测、
安全负控、wheel身份、未通过项与回滚说明。
不另起多Agent审计，不真实API，不提交发布，不扩大范围。
YAML
codex_execution_advice:
  implementation_plan:
    - "获得实施授权后核对基线，定点补读派发、来源生产、summary及序列化缺失符号。"
    - "包1：新增有限provider grant、可信来源边界和schema11；旧授权不自动升级。"
    - "包2：正常与compaction共享授权门，完成durable计数、撤销、身份失效和恢复负控。"
    - "包3：增加CLI s/f/d，严格复用文件scope动作，保持旧输入及未升级入口不扩权。"
    - "收尾：固定合成工作流确认预算、最终完整门及来源固定的新wheel离线安装验证。"
  non_goals:
    - "不实施全局信任、自动yes、prefix/wildcard或shell allow-all。"
    - "不改变local_process信任边界，不放宽文件/进程现有授权。"
    - "不跨write_file/edit_file复用，不从当前文件猜目录。"
    - "不将generic tool_results整体纳入常规授权。"
    - "不建立第二套权限引擎、Agent循环、授权历史库或来源治理平台。"
    - "不补全TUI parity，不重开E2/E3或整个产品验收。"
    - "不改grader、历史报告、凭据、登录项、后台服务或基础设施。"
    - "不执行真实API、不读取私人状态、不提交或发布。"
  optional_subagents: []
  verification:
    - "CLI prompt→固定输入→typed action→durable grant→实际provider/tool行为完整贯通。"
    - "普通三轮对话1次provider确认且3/3完成。"
    - "同文件、目录、exact命令分别验证既有范围复用和真实效果。"
    - "远端descriptor组合编码同时统计provider与工具确认，不能仅改善局部数字。"
    - "生产恢复与compaction覆盖来源增长、收缩和A→B→A→B，不能只测builder。"
    - "验证旧schema/pending、CAS漂移、撤销发送窗口、到期耗尽、crash及unknown恢复。"
    - "验证Memory/MCP/Skill/SubAgent新来源不能借generic类别继承授权。"
    - "最终完整门与新wheel离线安装证据固定到同一候选来源；未通过和阻断如实保留。"
