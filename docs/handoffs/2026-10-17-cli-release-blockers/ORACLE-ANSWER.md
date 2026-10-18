# Oracle Web 执行包原答（5/5，完整捕获）

以下为顾问原答，保留内容；最终执行以 START-HERE / WORK-PACKAGES / VALIDATION / PROMPT 为准。来源标签沿用原答，不代表顾问运行过代码。

审查结论

**保留 A → B → C 三包结构，但 CODEX-DRAFT 不能原样冻结。**需要修订的是有限规则的边界、恢复决定的完整语义，以及验收证据之间的精确绑定；没有理由新增第四个工作包。

我已完整读取五份材料，先依据审计、探针和源码形成独立判断，再核对草案。本答复是静态审查与执行建议，没有运行项目、探针、测试或真实模型，也没有修改文件。

工作包	独立裁决	优先级与结束目标
A：交付对象来源分类与完成门	F1、F2 同源，应一起修；不能只替换一个正则边界	P1，首发必修。明确文件要求不因中文邻接而漏验，输入、引文、日志与版本不凭空增加义务
B：恢复后待确认外发的完整 CLI 语义	固定 no/Enter = 退出当前 CLI，保留 pending；修复不需要新增 Runtime action 或状态	P1，首发必修。拒绝不再成为业务纠正，显示与可回答状态一致
C：验收器绑定与当前安装物交付证据	F4 是验收器缺陷；必须保留“真实 Runtime 尚未被证明消费错 correction”的界限	验收器为 P2，但本次交付门必须修。最终证据绑定同一候选、同一任务、同一纠正与真实恢复过程

材料中的 3947 passed / 1 skipped 是上一轮已经结束的验证记录，不能代替本轮修复后的行为证据。另有两条界限必须保留：F3 探针没有证明未同意外发；F4 的伪阳性没有证明此前真实 staged 运行一定失败。
AUDIT
PROBE-RESULTS

一、独立执行方案：最多三包
A 包：有界区分交付对象、输入对象与非权威内容
1. 已确认因果与允许改动范围

当前规则存在几个直接相关的缺口：

state.py:261 的 Unicode \w 把相邻汉字排除，导致明确路径消失。
state.py:502–506 先分句再遮蔽引文，破坏了跨分号引文的完整范围。
文件 token 接受 3.12，输入规格规则又只覆盖部分中文表达。
question guard 把 Could you update …? 这样的礼貌请求也整体排除。
当前非权威 span 没有覆盖探针中的明确日志报告语境。
SOURCE-SLICES(2)

允许修改：

agent/runtime/state.py 中现有交付对象提取 helpers、必要的局部模式与判断顺序。
相关现有测试。
agent/runtime/loop.py 的缺口提示仅在确有不一致或错误指引时修改。
README 对识别范围的说明。

不改变 process 要求识别的整体语义，不改变 admission、权限、证据有效性或完成状态机。

2. 先固定两个完整 Runtime Red

A-R1：非空 coverage 仍不能掩盖漏做。

保持 provider 剧本、工具、审批与业务要求不变，只比较：

命令行适配器 retry_app/cli.py 必须使用同一个值
命令行适配器retry_app/cli.py 必须使用同一个值

provider 只完成 service，CLI 仍不满足业务检查。修后两种表达都必须：

下界包含 retry_app/cli.py；
不进入 VERIFIED_DONE；
拒绝原因明确包含缺失路径；
独立检查仍能证实 CLI 未满足要求，不能把 fixture 顺手修好来制造 Green。

A-R2：引文不得阻止合法的 confirm-only 收尾。

保留当前完整反例：真实目标已经正确，经现有 confirm_file 获取合法当前证据，附带解释性跨分句引文。

修后必须：

下界不包含 app/example.py、app/other.py；
不要求为这两个示例新增 criterion；
合法目标可以进入 VERIFIED_DONE；
示例无变更，真实目标内容摘要不变，变更类工具执行增量为零。

这两个 Red 都已有附带探针支持，不需要重新设计任务。
PROBE-RESULTS

3. 最小规则顺序

建议冻结为以下有限处理顺序：

**限定 authority 来源。**仅处理当前 Goal 的 created_from_fact_ids 所绑定的真实 USER_MESSAGE。
**在整条原文上识别非权威范围。**先处理已支持的成对引文、围栏代码块及本轮明确的日志报告范围，再进行分句判断；不修改持久化原文。
**完整校验路径候选。**保留原文区间，防止分句或子串匹配提前切掉非法前后缀。
用有限直接关系区分输出、输入、解释与禁止。
**按已消费事实的顺序更新下界。**新增、点名撤回、再次新增；无关纠正不清空旧要求。
完成门与 blocked guidance 继续使用同一结果。

这里尤其要避免两个“看似最小、实际不完整”的修法：

只把 \w 换成 ASCII 字符类，却允许从非法长 token 中提取合法前缀或后缀。
只新增 requirements 输入后缀，却继续把“修改 SPEC.md 的说明”误判为输入。
4. 冻结的表达合同
输入或对照	完成下界要求
修改 app/config.py、修改app/config.py、修改行内反引号中的 app/config.py	包含 app/config.py
命令行适配器retry_app/cli.py 必须使用同一个值	包含 retry_app/cli.py
Could you update app/config.py?、Would you update app/config.py?	包含该路径
Could you explain how to update app/config.py?、How do I update app/config.py?	不因解释问题产生义务
Update Python to 3.12	不包含 3.12
修改 app/v3.12/config.py	保留有效路径，不能因为包含数字版本片段就排除
Implement SPEC.md requirements、根据 SPEC.md 实现需求	不把 SPEC.md 当输出
修改 SPEC.md 的说明	包含 SPEC.md
根据 SPEC.md 的说明修改 app/config.py	只包含 app/config.py
阅读 SPEC.md，然后修改 app/config.py	只包含 app/config.py
附件中的跨分句解释引文	不包含引文中的示例路径
日志显示：创建 app/old.py；修改 app/other.py；请说明原因	不包含这两个报告对象
日志显示：创建 app/old.py；请修改 app/live.py	只包含明确的新请求 app/live.py
直接修改 live，后接真实换行和围栏中的 demo 示例	包含 live，不包含 demo
绝对路径、父目录逃逸、Windows/URL 前缀或非法附尾	不从整串中截出合法路径作为义务

最后一行至少采用这些有代表性的边界负控：

纯文本
修改 /tmp/out.py
修改 ../out.py
修改 dir/../out.py
修改 dir/out.py/../other.py
修改 dir/out.py\x
修改 C:\tmp\out.py
修改 https://host/out.py
修改 /tmp/中文out.py

如果支持句末问号，还应区分：

礼貌请求中的 app/config.py?；
带非空附尾的 app/config.py?x=1。

后者不能在先按 ? 分句后，被截成一个合法文件要求。这些扩展项是边界负控建议，不应写成旧 probe 已经复现的全部缺陷。

日志范围也必须有明确边界：本轮只处理表内这类显式“日志显示：”报告，并以明确的新直接请求结束报告范围；不扩展为任意日志理解器。

5. Correction 的保留合同

以下语义不能被修复破坏：

原要求 A，已消费纠正增加 B，结果为 {A, B}。
已消费但无关的纠正不改变集合。
已消费、明确点名的“不要修改 A”只撤回 A。
后续已消费“修改 A”可以再次加入 A。
未消费的相同纠正不生效。
模型、summary、tool、引文或日志中的内容，既不能新增义务，也不能撤回真实义务。

当前源码已经限定了 created_from_fact_ids + USER_MESSAGE，应在此基础上修复，不改成扫描全部历史消息。
SOURCE-SLICES(2)

6. Green、依赖与停止边界

**Green：**冻结矩阵通过；两个完整 Runtime 反例转为正确拒绝与合法完成；原有双文件正常完成、confirm-only、correction/reopen/freshness 回归通过。

**依赖：**无前置产品包。

**停止边界：**到此停止添加自然语言规则。保留“有限下界”的说明，不承诺：

任意间接、隐含或跨段落的自然语言要求均可识别；
任意引号、日志格式或混合叙述均可自动确定来源；
中文文件名、Windows 路径或 URL 文件操作；
由提取结果自动生成已准入 criterion 或权限。

支持汉字邻接 ASCII 路径，不等于支持任意 Unicode 文件名，也不等于能够消除连写文本的一切歧义。

B 包：拒绝本次外发并退出 CLI，保留原待确认请求
1. 合同裁决

草案选择可以保留，但必须把语义写准确：

no/Enter 表示本次不发送并退出当前 CLI 进程；任务和待确认请求保持原样。它不是持久化 DENIED，也不是暂停或取消任务。

重新打开时，如果 Goal 已是 GOAL_READY，应直接再次展示 pending，不要求第二次 ResumeGoal。

当前 reducer 已支持 active=None + receipt=None + goal=GOAL_READY 的精确 digest ACK，并由 Runtime 创建恢复回合；CLI 不需要自行推进状态。
SOURCE-SLICES(2)

2. 精确可答状态

用一个小型只读 predicate 统一渲染、肯定、否定与空白处理：

纯文本
request != None
AND receipt == None
AND (
    active != None AND active.status == AWAITING_DISCLOSURE
    OR
    active == None AND goal != None AND goal.status == GOAL_READY
)

**恢复分支必须显式检查 active is None。**当前 parser 的第二个 OR 只检查 goal_ready，比 renderer 和 reducer 对孤儿 pending 的形状更宽。这是源码可见的不一致，不能夸大为已经发生越权推进。
SOURCE-SLICES(2)

当前状态	肯定输入	否定或空白
活跃 AWAITING_DISCLOSURE，request 有、receipt 无	现有 ACK action	不提交 action，退出 CLI，保留 pending
active=None、Goal ready，request 有、receipt 无	同上，由 reducer 恢复推进	同上
active=None、Goal paused，request 有、receipt 无	裸 yes/no 仅提示先 /resume，不提交业务消息	裸 no 同样提示；空白忽略；/exit 正常退出
receipt 已存在	不再次映射这项 disclosure	不作为这项 disclosure 的拒绝处理
其他 active 状态加残留 request	不抢占审批、恢复等现有交互	保留对应交互语义
无 pending	保留原有解析	空白仍忽略

PAUSED 的窄分支属于同因防串义负控：材料没有提供“paused 裸 no 已落盘”的 probe，因此不能另报为已复现缺陷。这个分支只返回解释性提示，不改变 Runtime 权限或状态。

3. 先 Red 与最小修复

Red 使用生产 Runtime 的：

纯文本
SubmitMessage → pending disclosure → PauseGoal → ResumeGoal

固定当前两个失败：no 成为 correction；空白没有按 [y/N] 退出。

最小修复：

在通用空白忽略之前处理“可答 disclosure 中的空白”。
肯定回答绑定展示时的同一个 snapshot与 digest。
否定/空白直接安全退出，不调用 run_turn。
不新增拒绝 receipt，不清 pending，不发 PauseGoal、CancelGoal 或额外 ResumeGoal。
文案限定为：

本次待确认内容未发送。现退出 CLI，任务和待确认请求已保留。

不能笼统声称历史上任何内容都没有发送。

4. 精确验收字段

在无并发写入的受控测试中，否定/空白必须满足：

观测字段	预期
run_turn dispatch 增量	0
物理 provider 请求增量	0
ToolRuntime 调用、tool effects 增量	0
USER_MESSAGE、goal_correction 增量	0
disclosure receipt	仍为 None
request digest	不变
conversation、Goal ID、Goal revision/status	不变
state revision、next action sequence、active run	不变
checkpoint	未由该回答写入
REPL	当前输入后立即返回 0
空白后的再次读取/再次 pending 提示	不发生

**不能只检查退出码。**原 probe 的空白路径也最终返回 0，却是再次提示后才退出。测试应在第二次读取输入时直接失败，避免用随后的 EOF 掩盖默认拒绝仍未实现。
PROBE-RESULTS

负控保留 stale revision/digest、已 receipt、PAUSED、普通审批/恢复、二次披露与 UNKNOWN 不重放。拒绝后另启进程，应读到同一 pending；已有 ready Goal 不重复 resume。

5. TUI 与停止边界

**保留 CLI-only 首发、TUI 实验性这一选择。**不修 TUI 可以成立，前提是默认日用安装不再推荐 [tui]，支持矩阵明确其恢复 pending 显示限制，不宣称 CLI/TUI 等价。

保留 TUI 实现、可选依赖和现有测试；共享代码触及时运行相关回归。B 到上述定点验证和支持说明一致为止，不引入持久拒绝状态或 UI 重设计。

C 包：收紧验收器，并证明一个当前可安装候选
1. 已确认问题与允许改动范围

_consumption_view 目前以 Goal/state 版本变化的 OR 判通过；聚合器没有核验注入与消费 fact 相同，也没有绑定完整恢复链的 Goal 身份。

但 _consumed 本身使用 self.injected_fact_id 检查 created_from_fact_ids，这条正确绑定应保留。**C 修的是报告采集和最终裁决，不重新定义 Runtime 的 correction 消费。**
SOURCE-SLICES(2)

允许修改：

现有 D04 driver 的观察字段、聚合判据与相关测试；
必要的既有安装入口装配；
当前交付记录和支持说明。

不修改产品持久 schema、SPEC、业务 grader 或授权边界。

2. Red、Green、依赖与停止边界

先原样固定两个 evaluator 负例：

Goal revision 不变，仅 state revision 增长。
再把消费 fact 换成另一条。

修后两者必须是 incomplete 且包含具体失败原因。再用一个合法 staged 基准证据做参数化变体，覆盖错误 Goal、缺失/非法 revision、已持久但未消费、错误暂停顺序、同 PID 与错误恢复身份。

保留一个完整 staged 正例，以及 normal 无 correction 正例。没有必要建立通用 evaluator 平台。

C 的离线验收器修复可以独立进行；最终 full、候选冻结、安装及真实验收依赖 A/B/C 修改稳定。精确字段和交付门如下文，不另列第四包。

二、对 CODEX-DRAFT 的逐条裁决

以下按草案行号审查实质条款，替换要求可以直接用于定稿。
CODEX-DRAFT

1. 总体、身份与顺序
草案位置	裁决	定稿要求
8：首版定位	保留	macOS、单用户、CLI、当前工作区的有界文件/编码任务。
9：HEAD 与 dirty 工作树	保留并限定	将其标为“送审身份”。实施前核对当前身份；不得从 HEAD 重做或覆盖已有 dirty 修改。
11：测试记录	保留	明确属于旧身份，不能证明后续源码或安装物。
12：保留原审计	保留	原反例与历史结果保持不可改；新增测试与证据表达修后结果。
13：唯一 RESULTS	保留	更新既有当前记录，不生成第二个并列“当前真相”。
17：focused/full 顺序	修改	“修改稳定后集中一次 full；若后续修复改变了被证明的源码，刷新失效证据，最终 full、manifest、wheel 必须对应同一候选。”不能把“一次”解释为后续代码变化也永不复验。
2. A 包
草案位置	裁决	定稿要求
19–28：问题、范围、两个 Runtime 反例	保留	两个 Red 固定原任务和 provider 行为，不通过修改 fixture 或脚本策略消除反例。
34–35：中文邻接、行内路径	保留	明确支持的是表内 ASCII 相对路径的正文邻接。
36：礼貌请求	修改	“有限接受 Could/Would you [please] + 直接编辑动词 + PATH，同时排除 Could you explain how to update PATH?；不得直接删除全部 question guard。”
37：版本号	保留并补负控	“排除版本形状的无目录 token；保留 app/v3.12/config.py。不按全部数字片段一律排除。”
38–39：SPEC 输入/输出	修改	“直接编辑 PATH 本身优先于‘的说明’等输入后缀；修改 SPEC.md 的说明 是输出，根据 SPEC.md 的说明修改 OTHER 中 SPEC 是输入。”
40、44：引文与围栏	修改	“整 fact 先确定范围；围栏测试使用真实换行与围栏字符，不能把‘围栏代码块内’这段说明文字当成测试。”
41：日志	修改	“报告范围跨分号继承，直到明确的新请求边界；增加连续报告和随后直接请求的成对测试。”
42–43：解释问题、阅读后修改	保留	保持同一 basename 的输入/输出对照。
45：非法路径	修改	“安全校验覆盖完整原始 token；不得在分句或 regex 匹配时先切掉非法前后缀。”
49：遮蔽设计	修改	增加有限日志范围；行内单路径仍可表达请求，不把所有引号或反引号内容一概抹除。
50：token 边界	修改	“不能仅改 lookbehind；补绝对路径、父逃逸、Windows/URL 与非法附尾负控，不扩展支持这些路径。”
51：角色分类	修改	用明确直接关系处理输入/输出；禁止 SPEC basename 黑名单，也不根据文件是否存在或模型是否已写过反推 authority。
52：纠正	保留并补充	非权威内容不仅不能新增，也不能撤回现有义务。
53：共用 gap	保留	只在有因果证据时调整提示；不得固定要求所有文件先写入。
54：already-correct	保留并补触发条件	合法 confirm 路径被错误拒绝，或产品指引与当前缺口矛盾，得到复现后才做局部修复。
55：不新增能力	保留	不新增 schema、judge、权限或 path registry。
57：完成条件	修改	冻结矩阵、两个 Runtime 反例、既有相关回归通过即停止；不继续搜集同义词无限扩规则。
3. B 包
草案位置	裁决	定稿要求
61–62：事实	保留	明确 provider 增量为零，确认的是拒绝失效和意图污染。
64、68：判定与合法状态	修改	使用前文精确 predicate；孤儿分支必须有 active=None，render/yes/no/空白共享只读判断。
69：肯定输入	保留并收紧	用展示时 snapshot 构造 ACK；不得在答案到达后重新绑定新请求。
70：no/空白	修改	“退出当前 CLI 进程；不写拒绝状态，pending 原样保留；已 ready 的任务重开不重复 ResumeGoal。”
71：提示语	修改	使用“本次待确认内容未发送，任务和待确认请求已保留”，避免“会话结束”或历史上全未发送的歧义。
72：PAUSED 等	修改	对 paused 且有无 receipt 的 durable request，裸 yes/no 仅提示先 resume；空白不恢复。其他状态不全局劫持“no”。
73：其他退出与治理	保留	不合并 tool approval、UNKNOWN 分类与 disclosure。
75：测试	修改	补实际 dispatch、facts、receipt、版本及输入读取次数；不能仅用退出码或提示文字判通过。
77：CLI-only/TUI	保留	这是支持范围裁决，不能写成 TUI 缺陷已修复。
4. C 包与交付
草案位置	裁决	定稿要求
81：改 _consumed 等	修改	_consumed 保留现有同 fact 绑定，只补真实观测字段；重点修最终裁决。
83–84：版本与 fact	保留并补充	验证数值、同一 Goal、同一新增 correction；不能借用旧 correction。
85：identity	修改	绑定初始 Goal 到最终 Goal 的整条链，补 conversation、checkpoint、实际 PID；不要求 active run ID 相同。
86：不信 flag	保留	缺字段为证据不完整，不加旧格式降级通过。
87：负控	修改	加持久未消费、暂停顺序、同 PID/错误恢复身份；以合法基准参数化，不建立新平台。
88：旧约束	修改	保留七键、无催促、一次计划纠正与恢复；区分不可改的任务/授权 manifest 与必须新生成的候选身份 manifest。
92：集中 full	保留并绑定身份	最终证据对应最终候选；不重复跑无变化的旧版本。
93：构建命令	保留意图、修改执行前提	先核对现有脚本参数；使用新输出目录和显式公开文件清单，不覆盖旧候选、不扫描私有或 ignored 内容。
94：安装 runner 参数	修改	附件未给该 helper 源码，不能独立确认参数。实施者先读取其 parser，核对实际选中 node；零测试、错误筛选或源码 fallback 均不算通过。
95：安装离线链	保留	明确是 fake/MockTransport，不混写真模型结果。
96：三个真实样本	保留并补边界	already-correct 复用 normal 文件产物，使用新任务和隔离状态；不复用旧 Goal evidence。
97：source-real 替代安装物证明	删除其作为交付门替代的用法	改为下文最小 installed-real 方案；source-real 可保留为分层证据。
98：文档同步	保留	只更新当前结论与首发支持范围，不重晋级全部历史能力。
100：预算	修改	40/80/60 分钟均是待授权建议；以物理 transport 账本累计，不能把 consents 或参数名称当计数证明。
102：未授权时	保留	完成本地与安装离线工作，真实层为 BLOCKED_AUTHORIZATION，不自动寻找 key。
106：非目标	保留	不扩新能力、不做 Git 写入或发布。
107：结果分类	修改	区分可靠业务失败、完成性失败与证据缺失，不能一律归为假完成。
108：停止	保留	三包完成或到明确授权/外部阻塞边界即交接，不自动开第四轮。
三、C 的精确验收字段与判定真值表
1. 字段从哪里来

以下是现有 driver 报告的有限扩充，不改变 ConversationState 或 checkpoint 的持久 schema。

字段组	精确字段与来源
候选与运行环境	candidate_manifest_sha256、wheel_sha256、实际 interpreter、入口、产品模块 origin；来自构建、安装与实际进程
样本与路径	sample_id、mode、workspace_realpath、state_root_realpath；来自 driver 实际采用的路径
会话身份	conversation_id；直接读取既有 state.conversation_id
Goal 原始观察	goal_id、goal_status、goal_revision、created_from_fact_ids；来自既有 observer
状态与事实	state_revision、correction_fact_ids、active_run_status；来自既有 observer
效果	executed_file_effects、effect_tools；沿用现有观测，不能仅填 no_replay=true
注入事实	injected_fact_id，以及对应事实的 fact_id/kind/control/text 最小切片；从实际新增 durable fact 读取
消费切片	保留现有 fact_id、before/after revision、created_from_fact_ids；补 goal_id_before/after，均从实际观测取得
过程	实际输入/action 事件顺序、暂停后的观察、新进程首次加载、恢复后的观察；flags 只作派生摘要
进程	A/B 实际子进程 PID、A 退出结果；由进程记录及父 driver 启动/等待结果核对

现有 observer 已提供多数 Goal、revision、fact 和 effect 字段，应该扩充它，不能再建立一套由模型生成的“可信摘要”。
SOURCE-SLICES(2)

类型要求：

ID：非空字符串，按原值比较。
revision、计数：type(value) is int，且非负；拒绝 bool、字符串、None、缺失。
PID：真实正整数。
fact ID 集合：合法字符串列表；不能把缺失字段当空列表后继续通过。
2. 固定观察时点

保留或补齐以下位置：

初始任务创建 Goal 后首次观察到的 ID，锁定为 G。
phase_a.pre_injection。
实际注入 fact 的持久证据。
首次确认该 fact 已被 G 消费的 consumption。
phase_a.final_observation：实际暂停后、A 退出前。
phase_b.start_observation：B 第一次加载 checkpoint，在任何 ResumeGoal 之前。
实际 ResumeGoal 后的观察。
final_observation。

持久和消费可以在同一次真实快照中都已可见；不要求为了取证新增一个“已持久但未消费”的 Runtime 停点。需要分开的是判据，不是强造中间状态。

3. Correction 与 Goal revision 的精确关系

设 C = injected_fact_id。必须同时满足：

纯文本
G、C 为非空 ID

C 对应本轮计划注入的真实 USER_MESSAGE / goal_correction
C 不属于 pre_injection.correction_fact_ids
C == consumption.fact_id

C 存在于 durable correction facts
C 存在于 consumption.created_from_fact_ids

consumption.goal_id_before == pre_injection.goal_id == G
consumption.goal_id_after == G
后续暂停、恢复加载、恢复后和最终 Goal ID 均为 G

before == pre_injection.goal_revision
before、after 均为严格整数
after > before

另外：

after 直接来自消费时观察，不能来自 goal_version_changed=true 的反推。
C 在消费后的暂停、恢复加载与最终来源中持续存在。
state revision 保留为原始诊断，不能替代 Goal revision 增长。
user_outcome 可以保留作诊断，不增加“包含 correction 文字即正确”的 NLP 判据。
4. 暂停、恢复与身份

必须证明：

实际消费观察之后，才发出计划中的 PauseGoal。
A 最终真实 Goal 状态为 paused，进程结束。
B 是实际不同 PID。
B 在 ResumeGoal 前加载的快照，对应 A 保存的 paused checkpoint：conversation、workspace、state root、Goal ID、Goal/state revision 和关键 fact 集合一致。
存在一次计划 ResumeGoal；恢复后仍为 G。
最终 G 为 verified_done。

这里要求 B 的首次加载与 A 的暂停快照版本相同，是为了证明读到了那份 checkpoint，不是另设“每个步骤 state revision 必须加一”的产品合同。

同时保留当前 staged 的：

纯文本
resume_advanced =
    final.executed_file_effects > resume_start.executed_file_effects
    OR final.goal_revision > resume_start.goal_revision

必须基于同一身份和合法数值计算。不要改成“恢复必须写入文件”，也不要把这个 staged 场景条款套到所有 confirm-only 任务。

**不要求 active run ID 一样。**现有 reducer 可以创建新的 resume-{action_seq}，连续性应绑定 conversation、Goal、checkpoint 与 fact。
SOURCE-SLICES(2)

effect 总数也不能单独证明未重放同一效果；继续复用已有 effect identity/receipt 与 UNKNOWN 恢复回归，不新增真实 UNKNOWN 样本。

5. 七键与过程约束

设 K 为现有独立业务检查器声明的完整七键集合：

纯文本
set(checks) == K
所有值 type(value) is bool
完成时所有值 is True

附件只显示了其中六个键名，未展示第七个；执行者应一次读取现有常量，将 K 原样记录并冻结，不能猜一个名称补进去。

注入前也应先校验检查结果结构合法，再保留现有条件：

已有至少一次文件效果；
legacy_alias 与 cli_both_names 至少一项尚未满足。

不能用缺键冒充 false，也不应擅自收紧为“两项都必须失败”。

过程约束从实际输入/action 记录核验：

normal：零 correction、零“继续”、零救场 resume。
staged：一条计划 correction、一次计划新进程恢复；不追加业务救场。
计划中的那一次 ResumeGoal 不应被误算成“额外救场 resume”。
治理确认与业务催促分开记录，不把 consents 直接等同于催促次数。
6. 判定真值表

下面是验收分类；不要求新增产品 RunStatus。Evaluator 沿用现有 completed/incomplete 接口并记录具体原因即可。

原始证据	验收结论
同 G、同新增 C、真实消费、Goal revision 增长、消费后暂停、新进程正确加载并恢复、typed done、七键全 true	COMPLETED
仅 state revision 增长，Goal revision 不变或回退	INCOMPLETE_EVIDENCE
injected 与 consumed ID 不同，即使两条 fact 各自存在	INCOMPLETE_EVIDENCE
C 已持久，但未进入当前 Goal 来源	INCOMPLETE_EVIDENCE
C 实为注入前已有旧 fact	INCOMPLETE_EVIDENCE
任一关键阶段换成另一 Goal	INCOMPLETE_EVIDENCE
revision 缺失、bool、字符串、None，或 flags 与原始值矛盾	INCOMPLETE_EVIDENCE
pause_sent=true，但未实际 paused，或先暂停后才声称消费	INCOMPLETE_EVIDENCE
PID 相同，或新 PID 加载了另一 conversation/checkpoint	INCOMPLETE_EVIDENCE
没有计划恢复事件或不满足既有 staged advancement	INCOMPLETE_EVIDENCE
typed done，但可靠独立业务检查有 false	FAIL_FALSE_COMPLETION
业务检查全部 true，但没有 typed done	INCOMPLETE_CLOSURE
typed done，但业务检查缺键、未知键、非 bool 或探针异常	INCOMPLETE_EVIDENCE，不能冒称已证实业务失败
真实调用未授权	真实层 BLOCKED_AUTHORIZATION
到预算/时间上限或服务阻塞	如实 incomplete/blocked，不补写通过

旧报告缺新增字段，应记“按本轮门证据不足”，不能倒推出历史运行必然失败。

四、最小交付门、already-correct 与授权边界
1. 交付门裁决

对本轮“当前安装版 CLI beta”的交付口径，我不接受仅用同一 manifest 的 source-real + installed-focused 签 PASS。

两者可以支持修复候选、监督自用及分层证据记录；但尚未直接覆盖“安装入口 → 实际 provider 装配 → 唯一 Runtime”的组合路径。当前 D04 driver 明确存在 from main import main，不能因为使用了 venv Python 就认定产品来自 wheel。
SOURCE-SLICES(2)

最小补法是：把原定三个真实样本直接放到 noneditable 安装环境中运行，仍然只有三个样本。

门	最小内容	通过口径
G1：源码行为门	A/B/C focused、ruff、diff check；修改稳定后一次完整 full	对应最终源码身份，已知反例闭合
G2：候选与安装离线门	冻结公开候选、构建 wheel、隔离 venv、源码外 cwd、安装 focused 与短 CLI 链	产品 imports 确实来自安装物
G3：安装物真实门	原定 normal、staged、already-correct 三样本	同一候选与 wheel、真实 provider、独立业务检查和正确收尾
G4：记录一致性门	唯一 RESULTS、README、支持矩阵一致	清楚区分 local、installed-offline、installed-real 和阻塞项

这些是 C 内的交付检查，不是四个新工作包。

2. installed-real 的最小实施办法
先只读核对现有 packaging entrypoint 和安装测试 adapter。
复用现有安装入口、同一个 JourneyOperator、同一个 Runtime；必要时只修改 driver 的入口装配点。
测试 driver、独立 grader、授权 guard 可以作为外部测试代码存在；产品 main/agent/运行模块必须来自 wheel。
使用安装 venv、源码外中立 cwd，不通过源码 PYTHONPATH 或 sys.path 混入产品。
记录父子进程实际入口和模块 origin，构建、安装、运行回执指向同一 manifest/wheel。
先用 fake 路径验证这一装配，再使用真实预算。

如果 wheel 没有可用入口、必须混入源码才可运行，或现有 operator 无法通过小范围装配接入，就记录具体安装入口阻塞。允许修复本范围内已证明的包装问题，不允许悄悄 source fallback，也不要求为此重写 runner 或新增产品入口框架。

另需区分两个都叫 candidate 的对象：

构建脚本的 源码候选目录；
D04 业务任务的 测试 workspace。

二者在记录和命令变量中应分别命名，避免把产品源码目录当成待修改任务目录。

3. 三个真实样本
样本	起始条件	成功条件
normal fresh	全新未完成 fixture、全新任务状态	零业务催促；typed done；独立七键全 true
staged	独立 fixture/state；满足原注入前提	一次计划 correction；真实消费、暂停、新 PID 恢复；同 G 完成
already-correct	复用 normal 成功文件产物，新 conversation/Goal 和隔离状态	起始已正确；当前任务重新获得合法证据；无改写；typed done

/new 与 setup 的短链可以在安装离线门覆盖；不因此增加第四个付费真实场景。

4. already-correct 的最小复现与修复触发标准

现有材料支持的是：

scripted confirm-only 已经通过；
真实历史一次反复 claim 至 fatal；
根因未明。

完成门切片要求有效的文件准入与证据，没有展示“文件必须先改变”的条件。因此，不能生成“删除强制写入 guard”任务。
AUDIT
SOURCE-SLICES(2)

最小样本应记录：

起始与最终独立七键结果；
任务文件 before/after 摘要；
实际变更类工具/效果记录；
当前 Goal、admitted criteria、证据与 completion claim 的绑定；
typed terminal。

成功时要求摘要不变且实际改写为零。只比较摘要不够，写回相同内容也会保持摘要不变。

若失败，先保留：

首个拒绝 code/message；
当时 Goal ID/revision；
缺少的 criterion/evidence；
实际 advertised tools 与模型选择；
后续 claim 顺序和物理请求数。

只有在当前候选上证明：

合法 confirm/当前证据被错误拒绝；或
产品对同一缺口给出了错误、不可执行的补证指引；

才在 A 范围内形成最小 Red→Green 修复。

若正确路径可通，只有真实模型反复提交非法 claim，就记录真实样本 INCOMPLETE_CLOSURE。不能因此降低完成门、提高重试上限或强制改写，也不能把这个真实收尾失败从报告中删掉。

5. 80 请求、60 分钟和授权

三个样本共享 80 个物理请求、60 分钟，每样本 40 个请求，是待用户批准的建议预算，不是本次咨询已经授予的权限。

获批后应落实为：

纯文本
下一次请求可用额度
= min(该样本剩余额度, 三样本累计剩余额度)

并且：

retries、失败、重启、staged 两阶段、修复后重跑都累计；
staged A/B 不重置该样本账本；
不同样本可以分别保存账本，但总额度按它们的真实物理记录累计；
三样本串行，共享总 deadline；
到任一实际授权上限即停止；
401、429、额度或外部阻塞不触发 key/provider 轮换；
不自动提高 tokens、请求数、重试或时间限制。

当前切片只展示了单 journey 的 deadline；max-model-attempts 名称不能证明它等于物理请求数，max-consents=40 更不是 API 请求额度。实施者必须核对既有 transport ledger/budget 的实际计数语义，不能用参数名称代替证明。
SOURCE-SLICES(2)

**没有当前真实授权时，可以交付：**本地修复、focused/full 证据、候选 manifest、wheel、安装离线结果及精确待执行计划。

**绝不能宣称：**安装物真实模型已验证、三个真实样本通过、真实日用收口或本次 release-ready。真实层应为 BLOCKED_AUTHORIZATION；不自动找 key，不读取未指定的配置或旧私有日志。

五、可直接交接的中文执行 prompt

建议把本次审查结论和五份材料一并交给普通 coding agent。以下是实施交接稿，本轮没有执行这些动作。

纯文本
你接手 First Agent 的有界修复任务。完整读取 CONSULTATION、AUDIT、
PROBE-RESULTS、SOURCE-SLICES、CODEX-DRAFT 和本次终审；CODEX-DRAFT 是被修订对象，
冲突以本次终审的冻结合同为准。

只做 A→B→C 三包。先核对当前源码身份和已有 dirty 修改，保留旧审计、旧反例及历史结果，
不得 reset/checkout 覆盖它们。沿用唯一 RESULTS，不建立第二份当前记录。

A：先固定无空格漏文件假完成、跨分句引文阻塞 confirm-only 两个完整 Runtime Red。
局部修复当前交付路径提取：只读当前 Goal 已消费绑定的 USER_MESSAGE；整 fact 处理引文、
围栏和冻结日志范围；完整校验路径前后缀；按冻结有限语法区分直接输出、规格输入、
解释问题、版本与禁止。保护礼貌直接请求和中文邻接；非权威内容不能新增或撤回义务。
保留 completion/blocked 共用缺失集合及 correction/reopen/freshness。
矩阵、两个 Runtime 反例和既有相关正例通过即停，不继续扩 NLP 规则。

B：以同一个只读 predicate 统一 CLI render/yes/no/空白：
request非空、receipt为空，且 active.awaiting_disclosure，
或 active为空且 Goal ready。yes绑定展示时 snapshot/digest，使用现有 ACK。
no/Enter/空格只退出当前 CLI，不调用 Runtime、不写拒绝状态，保留 pending。
paused 且有该请求时，裸 yes/no仅提示先resume，不变成业务纠正。
验证实际请求、工具、facts、receipt、版本增量和输入读取次数。
CLI-only；TUI标实验和已知限制，不重做 TUI。

C：先让两个原 evaluator 负例被判 incomplete。
从既有 observer 读取原始字段，锁定初始 Goal G 和本轮新增 correction C；
校验 injected C=consumed C、持久与消费分别成立、同 G 且整数 Goal revision严格增长。
绑定消费后暂停、A退出、不同实际PID、B在ResumeGoal前加载同一checkpoint、
一次计划恢复和同G最终完成。flags不能代替证据；不要求active run ID相同。
保留七键严格布尔检查、注入前提和无催促约束；完整七键从现有grader读取，禁止猜测。

修改稳定后集中focused/lint/diff/full，冻结公开源码候选，构建noneditable wheel，
在源码外隔离环境运行安装focused和短CLI离线链；核对实际测试node及父子产品module origins。
构建/安装辅助脚本参数先读现有parser，不按草案猜参数。
区分任务/授权manifest与新候选身份manifest，不改前者制造通过或权限。

真实层只有获得当前明确授权后才能运行。把原定normal、staged、already-correct三个样本
直接复用现有安装入口运行，不增加第四样本，不混入源码，不另造loop或runner框架。
40/样本、80累计物理请求、60分钟累计仅为待批准建议；采用实际获批范围，
失败、重启和重跑全部累计。未授权先完成全部本地和安装离线工作，真实记BLOCKED_AUTHORIZATION。

already-correct复用normal成功文件但新建任务状态；不加“可以不修改”的救场提示。
要求初始/最终业务正确、零改写、当前证据与typed done。失败先定位首个拒绝链并最小复现，
不得预设强制写入、降低完成门或增加重试。

始终保留单Runtime loop、ContextManager/ToolRuntime所有权、精确权限、审批、
EXECUTING/result checkpoint、CAS、UNKNOWN不重放和freshness。
不新增持久schema、能力或自动授权，不commit/push/tag/merge/release，不启动额外agent。
范围外发现只记录最小证据。三包完成或到明确授权/外部阻塞边界即交接，不自动开下一轮。
YAML
codex_execution_advice:
  implementation_plan:
    - "核对送审身份与当前 dirty 工作树，保留历史审计和原始反例，沿用唯一 RESULTS。"
    - "A：先固定两个完整 Runtime Red，局部修复权威来源、完整路径和有限输入/输出分类，完成冻结矩阵与既有相关回归。"
    - "B：统一只读 pending 判定，修复 no/Enter 的纯 CLI 退出语义与 paused 窄范围防串义，保留 snapshot、digest 和 CAS。"
    - "C：修复 evaluator 的同 Goal、同新增 correction、数值 revision 与暂停恢复身份绑定，以原始观察重算结论。"
    - "修改稳定后完成 focused、lint、diff check 和集中 full；冻结公开候选并构建对应 noneditable wheel。"
    - "完成安装离线短链与选定测试，验证实际 node、入口和父子产品模块均来自安装物。"
    - "仅在获得当前授权后，在同一安装物上运行 normal、staged、already-correct 三个真实样本，按实际授权累计物理请求与时间。"
    - "更新唯一 RESULTS、README 和支持矩阵，分别报告源码、安装离线、安装真实及阻塞状态，然后停止。"
  non_goals:
    - "不增加第四包，不扩展为通用自然语言理解或 evaluator 平台。"
    - "不新增第二 loop、持久 schema、自动准入、自动授权或路径 registry。"
    - "不降低完成门、独立业务 grader、freshness、CAS 或 UNKNOWN 不重放要求。"
    - "不预设 already-correct 存在强制写入逻辑，不用增加重试或预算掩盖失败。"
    - "不重做 TUI，不增加 Browser、Scheduler、MCP、Skill、Memory、跨平台或多 Agent 能力。"
    - "不自动寻找凭据，不改授权 manifest，不读取未指定的私有配置或旧日志。"
    - "不将 source-real 冒称 installed-real，不重晋级全部历史 capability。"
    - "不执行 commit、push、tag、merge、release 或部署。"
  optional_subagents: []
  verification:
    - "A：空格/无空格漏做反例都拒绝完成；引文 confirm-only 合法收尾，示例义务与改写增量为零。"
    - "A：有限输入矩阵、完整 unsafe token、已消费 correction、正常双文件与 freshness 回归通过。"
    - "B：no/空白当前输入后立即退出，Runtime/provider/tool/fact/receipt 增量为零，pending保持；stale与paused负控通过。"
    - "C：state-only增长、wrong correction、wrong Goal、非法revision、错误暂停或恢复身份均为incomplete，合法staged正例仍通过。"
    - "交付身份：最终源码manifest、full记录、wheel、实际安装入口与模块origin对应同一候选。"
    - "真实层：仅按当前授权执行；三个样本共享累计预算，不依靠业务催促或源码fallback。"
    - "already-correct：起止独立检查正确、目标摘要不变、实际改写为零、当前Goal typed done；缺任一项如实未通过。"
    - "结果分类：区分假完成、收尾失败、证据不完整和授权/外部阻塞，不用旧通过记录覆盖当前缺口。"

