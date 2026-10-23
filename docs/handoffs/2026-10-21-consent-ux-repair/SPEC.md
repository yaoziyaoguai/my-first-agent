# 冻结合同：减少确认，不扩大默认权限

日期：2026-10-21。以本文件为最终行为合同；Oracle原答是建议，分歧见RECONCILIATION。
本轮是CLI确认体验修复，不是全产品能力晋级。实现者可选择局部函数/测试组织方式，不可自行
改变下面的许可范围、次数、生命周期、输入含义和验收分母。

## S1. 目标与不可变边界

1. 用户在当前确认处就能选到已有文件/目录复用，不必先查README或抄ID。
2. 明确选择会话外发许可后，不因历史、控制回执、可证明来源的摘要等内部变化重复确认。
3. 远端descriptor下同文件连续三次修改、真实read-back及合法完成声明，必须达到：
   **3次外发决定 + 1次文件决定 = 4次**，三个真实文件效果、最终内容核验和typed终态均成功。
   第三次外发确认是read-back的新workspace_excerpt来源；本轮不为压数字扩权。
   这不是“任意编码任务永远只问4次”的承诺，冻结fixture见VALIDATION U8。
4. 模型/endpoint/工作区/工具定义或实际来源范围改变时仍要决定；效果审批与数据外发是两种权利。
5. 只有 `AgentRuntime.run_turn` 修改权威状态，ContextManager决定上下文，ToolRuntime执行工具；
   保留policy、EXECUTING/result checkpoint、预算、CAS、unknown recovery。禁止自动yes、
   第二套循环/权限引擎、宽松fallback、全局信任工作区、命令前缀/通配授权。

## S2. CLI选择合同

沿用现有英文产品字符串风格，新增说明必须短且准确；不在本轮引入国际化系统。
下面示例是需要表达的内容和选项，不要求每行英文完全相同。

### 文件审批

```text
Approve edit_file for src/example.py
Change: <escaped existing preview>
  y  This operation only
  f  This file / this task / edit_file — up to 16 uses, 60 minutes
  d  Declared task directory src/ / edit_file — up to 16 uses, 60 minutes
  n  Reject
Task changes or closure end the reusable permission.
Revoke: /revoke-goal-target
```

- `f` 完整等价于当前无参数 `/approve-goal-target`，`d` 完整等价于
  `/approve-goal-directory`。必须复用既有scope动作构造，不能复制y分支只改两个布尔值
  （其中artifact/rebind等字段不完全一样）。
- 只有 `project_goal_authorization_scopes` 当前给出的合法选项才展示/接受。不猜父目录；
  无scope时简短解释只可批准本笔。`write_file`与`edit_file`不互相授权。
- 文件y、现有a别名、n、旧slash含义不变。普通聊天的s/f/d仍是普通文本。
  有pending但该选项不适用时给明确错误、零模型/效果，不当作新业务消息。
- 空回车/EOF/Ctrl-C保持原入口安全行为，不新增默认同意：外发空回车拒绝退出，普通文件
  空回车当前是忽略而非同意，不能谎称已执行“拒绝”状态转换。
- 进程不套用“y仅一笔”文案：如实显示现有exact命令lease的8次/60分钟、same-UID风险与
  `/revoke`入口；不改其铸造、暂停清除、耗尽或漂移规则。
- artifact独立确认、unknown outcome消歧等不简化成y/f/d。

### 外发审批

```text
Send to <canonical destination>, model <model>
Workspace: <bound workspace or explicitly no workspace>
This request contains: <actual categories, readable labels>
  y  Approve the exact scope shown above
  s  Allow routine conversation data in this conversation
     up to 32 model sends, expires in 60 minutes
  n  Do not send
Enter: do not send
Routine scope: your messages, conversation and task records, system policy,
listed tool/control definitions, and summaries with verified covered sources.
Tool outputs and other new sources are disclosed separately.
Revoke: /revoke-provider-consent
```

- s只在当前pack全部符合S4常规范围、且scope候选可由Runtime验证时出现。不是对未披露数据
  “先建grant再顺便放行”。当前含未覆盖来源则保留精确选择，说明为何暂不能选s。
- y在legacy模式维持原精确类别request的复用语义，不写成“一次HTTP”。新模式的y按S5说明
  眼前范围是“同来源可在本许可内复用”还是“仅这份待发内容”，不得模糊。
- s对应独立 `GrantProviderConsent` typed action；新增一个
  `RevokeProviderConsent` / `/revoke-provider-consent`，撤销动作本身不触发provider或tool。
- 显示/解析/授予使用同一snapshot候选；action绑定request digest、scope digest、action seq、
  expected revision。Runtime重验，不信CLI填任意allowed set。旧ack不增加宽授权默认值。
- 不建设权限管理面板。授予后简短确认范围、剩余次数和绝对到期时间；到期/耗尽提示原因和
  重新选择办法。常规复用不逐次打印整段审批，也不隐藏需要用户决定的状态。

## S3. 一个会话级有限许可，不再增加Goal级外发许可

新增单槽 `provider_consent_grant`，闭合版本 `routine_conversation_v1`，逻辑字段：

- grant_id；conversation_id；workspace identity（未绑定为明确 `NO_WORKSPACE`，不是通配）；
- 完整provider descriptor identity、canonical destination、model；
- profile版本、allowed类别、已批准的工具定义逐项digest及control schema digest；
- 授予时展示的request/scope digest、用户action_seq；
- issued_at/expires_at（UTC带时区；固定60分钟）、max_uses=32、uses_consumed；
- ACTIVE / REVOKED / INVALIDATED闭合状态；所有权威字段的完整性digest。

到期/耗尽可从时间/次数计算，不另建重复状态机。授予时钟用Runtime已有
`_run_time_factory`的同源可信时钟；测试可注入。旧 `operator-confirmed` 标记不作为期限。
时间倒退早于issued_at也不能放行。字段类型严格（bool不是次数整数），未知版本/枚举拒绝。

基础许可不绑定Goal revision：首次发送可能尚无Goal，正常任务建立/纠正不应重新询问。
这不改变文件/命令原有Goal边界。身份变化、期限或额度约束以更严格者为准；不提升既有
attempt/token/费用上限，不自动续期、不补次数。

| 事件 | 权威行为 |
| --- | --- |
| 新conversation、`/new` | 不继承；保留旧会话供查看，不搬运grant |
| workspace、descriptor、endpoint、model改变 | 旧grant持久化INVALIDATED；A→B→A不复活；缺字段不得补绑 |
| Goal建立/修订 | 常规会话外发可继续；效果授权照原规则失效；文件来源例外的Goal/revision必须重验 |
| pause、重启、resume | 原到期/次数不变；仍有效才复用；不重放未知效果 |
| 60分钟或32次用尽 | 自动复用停止；明确重新选s才生成新grant/新期限；绝不无声续期 |
| revoke | durable REVOKED fence，清除有效精确例外；后续未发送请求重新要求决定 |
| 拒绝n/空回车/退出 | 当前未发送；保留可恢复状态，不视作授予或续期 |

新许可仅用于当前前台交互会话；background occurrence不得铸造或消费它来取得无人批准的能力。
headless显式新typed action走同一校验；旧headless/TUI action只走旧窄语义。

## S4. 真实内容、常规范围、来源边界分开

`ContextPack.data_classes`和当前request的data_classes继续描述**真正发送的类别**，不能填
固定大集合，也不能删分类来降确认数。新增只读的许可投影由ContextManager消费可信元数据生成。

### 常规集合（闭合枚举）

固定为 `system_policy`、`user_messages`、`conversation_history`、`goal`、
`goal_bootstrap`、`runtime_progress`、`control_receipts`，加以下有条件成员：

- `tool_schemas`：当前逐项定义digest是授予时集合的子集；control schema digest匹配。
  compaction无工具或减少工具可过；新增工具/同名改定义/改control schema必须重新披露。
  此处绑定结构定义版本，不把当前Goal值、allowed-control子集或action seq当schema定义；
  合法状态转换导致可用控制子集变化不能被误判为增加新的结构能力。
- `conversation_summary`：只有可信压缩来源证明其全部输入属于常规集合时可自动通过。
  证明由Runtime在成功压缩提交时从实际输入生成，不能来自模型summary正文。

`goal_bootstrap`、`runtime_progress`是Codex复查确认的现有生产类别，不遗漏导致新提示循环。
新增类别默认不允许。`tool_results`、workspace/history检索、Memory/preferences/recalled、
MCP/Skill/SubAgent/web不自动进入常规集合。

### 本轮仅补内置文件结果的稳定来源边界

这是达到S1组合预算必需的窄改动，不做通用污点跟踪平台：

1. 仅内置 `write_file` / `edit_file` 的**成功生产效果结果**可获得稳定文件来源证明。
   受信任文件注册处明确标记该能力，Kernel检查registration完整身份/policy/execution
   identity，再从实际prepared intent生成；只比较工具名、模型arguments或工具返回metadata不够。
2. 证明绑定conversation/workspace、完整tool identity、policy identity、operation、规范化
   exact文件目标、Goal/revision；每次结果另绑定executed intent及结果内容digest以防伪造。
   **复用边界**不含每次变化的调用ID、字节内容或state revision，否则连续修改又要逐笔问。
3. `_tool_result_fact` / `record_tool_result`的可信写入路径保存证明；ContextManager校验
   配对与digest。不允许工具自行带一个相同字段就被当成Kernel证明。错误/未执行/拒绝结果
   及不匹配的结果不获得这种稳定复用。
4. 已有SourceReceiptV1仍负责它原来的检索/证据语义，不把“写入成功”冒充文件内容阅读证据。
   新许可证明是数据外发范围，不改变完成oracle或可引用source ref规则。
5. read/search、多文件目录输出、process stdout及其它来源本轮不新增稳定外发许可。
   可以保留已有精确披露；在新模式中来源无法稳定证明则按S5一次待发内容处理。
6. summary保存其实际输入的可信来源边界并继续传递：含文件例外仍需该例外；含未知来源
   不能被洗成常规summary。旧summary缺证明时不升级。保存在Runtime-owned字段，不能把
   summary的模型返回schema增加一个“我已授权”字段。

允许局部扩展现有contracts、ToolResult/ConversationFact可信元数据、两处文件registration、
ContextManager和summary提交/codec。禁止改造所有工具、创建来源注册服务或新执行框架。

## S5. 精确例外：只留最后一条，不存授权历史列表

### Legacy模式

`provider_consent_grant is None`且从未进入新模式：旧request/receipt/digest/y全部保留。
旧checkpoint不会隐式升级。新增字段必须区分版本，不把legacy digest按新规则重算后自动授信。

### 新模式（包括已到期/已撤销fence）

选择s清除旧精确receipt；正常常规调用不覆盖最后一份**新模式**精确request/receipt。
允许新版本request携带grant_id、真实data_classes、来源边界、scope digest；receipt仍只绑定
其真实展示的request。不要建立第二个receipt仓库。

两种自动路径都必须先检查同一grant有效、身份一致、未到期、剩余次数大于0：

1. 当前全部内容属于S4常规范围；或
2. 当前非常规部分与最后一次明确同意的可信来源边界完全相同，常规部分符合S4，且例外绑定
   同一个grant、provider、workspace和当前Goal/revision。

例外的可复用scope digest只覆盖非核心来源边界及其身份，**不包括常规类别的无害涨落**。
当前request实际类别仍精确，receipt仍绑定当时展示的原request；使用时验证原request和
current projection的许可覆盖关系，不伪造“二者request digest相同”。同文件新结果须有
新的执行真实性证明，但稳定来源边界保持同值。因此A→B→A→B可保留B例外，而不能放行新C。

首次文件输出披露必须显示：具体文件、operation、数据外发目标、后续同来源可在当前grant
剩余时间/次数内复用。此时y确认这条明确范围；不是取得新的文件效果权限。

未知generic、无法稳定验证的来源/旧summary：显示“仅这份待发内容”。y绑定当前实际来源
内容digest和当前待发单元（run、目的normal/compaction、下一次attempt身份），只可消费一次；
不得跨新增结果、后续派发或重启未知结果复用。授权本身新增的纯控制回执不能制造无限重问，
但新用户消息/新source内容必须使待发授权失配。旧材料不因带同名metadata就成为稳定证明。

grant失效后可以明确批准单次待发内容；不得恢复旧32次额度/期限、不得切回legacy的无期限
精确复用。撤销/到期后禁止 `old receipt matches OR grant valid` 这种兜底。
只有显式重新选s才建立新grant，旧例外不转移。

## S6. 派发计数、撤销与竞态

- 新模式有效grant下的所有provider派发，包括首次、常规、精确例外、compaction及显式重试，
  在真正调用前同一次durable transition扣1。失败不退款，quota按尝试不是成功。
  第32次可以，第33次不能自动放行。单次明确许可在已失效grant外只消费其一次票据，不能
  修改旧grant计数或绕过已有provider总预算。
- 复用已持久化provider response只消费结果，不发请求、不再次扣许可。未知结果走原恢复；
  不增加自动重发。在校验后跨过到期点，派发前最后重验；不得因为已扣次就继续发送。
- 普通与compaction共用同一个纯许可判断和计次规则；不能只修一条路径。
- 使用已有conversation mutation lease串行化action与派发；**不新增后台撤销监听器**。
  当前run持有锁时另一进程revoke可以返回 `conversation_busy`，UI必须说未撤销成功，不能
  伪报“已撤销”。已被Runtime接受并落盘的revoke，之后尚未派发的请求必须拦住。
  已交给transport的请求不能撤回，也不能宣称立即中断所有网络。
- 测锁顺序与CAS：revoke先成功→下一发送0；发送方持锁→竞争revoke明确busy、零撤销写入；
  释放后revoke成功→后续发送0。不能用测试绕锁直接写state制造生产中不存在的并发成功。
- 旧pending→pause→新进程→resume必须仍可作答并继续；撤销action不得顺手触发一次发送。

## S7. Schema 11与兼容

新增持久化许可/版本化request/可信来源字段使用schema11；保留当前所有支持的2–10版本的
明确解码路径。旧grant缺省None，旧来源证明缺省“不足以稳定复用”，旧pending/digest不变。
不从旧receipt、文件lease或summary重建grant。v11缺字段、未知键、损坏digest、未知类型、
不合法时间/计数/范围必须严格拒绝。

`_encode_state`必须在grant存在（包括revoked/invalidated）、新request/来源证明存在时写v11，
即使没有Goal/active run；不能落回v2而丢字段。不得批量迁移用户真实会话。
旧二进制不承诺读取v11；旧安装与旧state保留，新安装用新state。不得恢复旧checkpoint来
回退已经发生的效果。

## S8. 本轮不解决什么

不会让任意多来源任务只需一次确认；不同文件/不同操作、新来源、外部写入、未知效果和
到期耗尽仍可能需要人决策。不会保证模型完成业务语义正确，不改变既有E2/E3未闭合状态。
不请求真实API凭据，不提交推送。最终按VALIDATION证明确定性行为，再把新安装交给用户试用。
