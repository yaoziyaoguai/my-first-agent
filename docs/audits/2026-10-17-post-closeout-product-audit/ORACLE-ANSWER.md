总体裁决

当前 First Agent 已经具备 MVP 所需的核心能力集合，属于可供开发者监督自用的产品候选（implemented-candidate）；当前快照还不适合按“日用收口完成”对外发布。

这次需要继续处理的范围可以收敛为：两个产品修复包，加一个发布证据包。已有 Runtime、精确审批、持久任务、上下文压缩、恢复机制，以及 W2、W3 中已经完成的改进，都应该保留。没有必要重新扩展 Agent 平台或重新验收所有历史能力。

我完整读取了八份附件，并做了完成判定、授权与恢复、产品交付三个方向的内部交叉核对。本次没有执行项目、测试或正则探针，也没有修改文件、调用真实模型或外部系统。下文区分三种证据：我能从源码确认的行为、本地报告记录的离线复现、执行者自报但未附原始证据的结果。审计对象是 0cc0db1 之上的当前未提交候选。
CONSULTATION(2)

一、先核验 LOCAL-FINDINGS
F1：中文与路径之间删掉一个空格，就能漏做而进入 VERIFIED_DONE——成立，首要阻断

这一项的代码因果链是完整的。

agent/runtime/state.py:260–266 的路径识别器使用：

Python
r"(?<![/\w.])("

这里的 \w 没有限定为 ASCII，中文字符也属于它。因此：

纯文本
命令行适配器 retry_app/cli.py 必须使用同一个值
命令行适配器retry_app/cli.py 必须使用同一个值

第二种写法中，路径前面的“器”会阻止匹配。后续文件名也不能补匹配，因为其前面是被禁止的 /。

随后，state.py:502–533 无法提取该路径；1931–1943 的完成下界只检查已经提取出来的集合。集合为空，这层保护就不再约束遗漏的 CLI 文件。
SOURCE-SLICES(1)

LOCAL-FINDINGS 记录的正式 Runtime 离线反例与此完全一致：只完成 service，CLI 原字节未变，外部 cli_both_names=false；带空格时停在 goal_ready，删掉空格后成为 VERIFIED_DONE。这是本地报告的 Runtime 复现，加上本次静态因果核验，不是我独立重跑的结果。
LOCAL-FINDINGS

**这不能用“自然语言不可能全部识别”来豁免。**当前 README 已明确承诺“用户点名的交付文件构成下界，非空泛化声明不能绕过”。上述两种写法表达的是同一个直接文件要求，属于当前承诺内部的词法缺陷。
README(9)

F2：版本号、输入规范、引文和日志被当成交付文件——成立，但影响要限定
本地反例	源码能够解释的原因	我的裁决
Update Python to 3.12 → 3.12	路径模式允许“数字名称＋数字扩展名”；附近的 update 又被识别成交付动词	确认版本号误提取
Implement SPEC.md requirements → SPEC.md	输入规范排除主要覆盖几种中文尾部表达；英文 requirements 未排除	确认输入规范误提取
解释包含多个分句的中文引文	先按分号等断句，再删除需要成对引号的 span；引号已被拆开	确认跨分句引文屏蔽失效
“日志显示：创建 app/old.py……”	没有在该语境中排除日志转述；后面的泛化禁止句也不能撤回已加入的具体路径	确认转述误提取
Could you update app/config.py? → 空集合	could 开头被整体归入疑问句并提前跳过	确认礼貌执行请求被漏识别；放在同一个有限语法修复中

对应代码集中在 state.py:260–299、447–534。
SOURCE-SLICES(1)

这些误提取不是完全无害的纯函数问题。当任务进入 Goal 完成路径，而且误提取的路径没有对应 mandatory FILESYSTEM_DIGEST criterion 时：

完成门会拒绝 completion claim；
如果模型改报 blocked，loop.py:2852–2901 会发现同一“缺口”，并要求把这些文件推进正常批准及最终读回路径，或者提供 durable blocker。

因此，可以确认它们会制造用户没有要求的完成义务，导致错误阻塞、无关确认或修复循环。**不能由此进一步断言已经发生越权写入，或这些输入必然导致 FAILED_FATAL。**工具授权仍是独立边界；纯解释请求也可能直接回答，并不一定进入 Goal 完成门。
SOURCE-SLICES(1)

F3：恢复披露的 yes 修了，no 和 TUI 没闭合——成立；尚无外发绕过证据

yes 的修复有实质内容。

CLI 已能重新显示以下状态中的披露请求：

纯文本
active_run = None
provider_disclosure_request != None
provider_disclosure_receipt = None
Goal.status = GOAL_READY

肯定回答被转换为 AcknowledgeProviderDisclosure；Runtime 在检查当前 request digest 和状态后创建 receipt，并重新建立 active run 继续原任务。这里仍使用原 Runtime，没有另造继续执行路径。
CHANGES

no 的路由确实遗漏了这个恢复状态。

agent/cli/app.py:540–551 只在非空 active run 为 AWAITING_DISCLOSURE 时，把否定输入识别为安全退出。新增的肯定分支则支持恢复后的无 active run 状态，两边不对称。

LOCAL-FINDINGS 实测的 no → SubmitMessage 与此相符。所附源码没有给出 _parse_action 的完整最终 fallback，因此这里应准确表述为：**源码确认拒绝分支缺失，本地检查进一步确认它落成了普通消息。**这会造成拒绝语义失效及对话、Goal 污染风险；没有证据证明它已绕过 receipt 外发。
SOURCE-SLICES(1)
 
LOCAL-FINDINGS

还有一处可以直接确认的交互不一致：

提示是 [y/N]；
app.py:155–156 却在解析决定前把空输入直接跳过。

所以按回车实际是继续等待，而不是提示所暗示的默认拒绝。这应与 no 分支一起修，规模很小。
SOURCE-SLICES(1)

TUI 缺口也成立。agent/tui/render.py:118–138 在 active is None 时提前返回普通 Goal 投影；后面的 disclosure form 无法触达。但按本次建议的 macOS CLI 首发范围，TUI 应列为已知非阻断限制，不需要为了首发重开整个 TUI 验收。

F4：staged 的版本和 correction 归属判据宽松——成立，但需要修正它的定性

第一处没有歧义：

Python
"version_changed": bool(
    consumption.get("goal_version_changed")
    or consumption.get("state_version_changed")
)

_consumption_view:602–615 把 state revision 增长也当成版本推进；_staged_evidence 又把它用于必过项。**这不满足 W3 明确要求的 Goal revision 推进。**
SOURCE-SLICES(1)

第二处也成立：最终聚合分别验证：

注入 fact A 在 durable correction 列表里；
consumption 的 fact B 在其 created_from_fact_ids 里。

没有明确要求 A == B。

但这里必须补上 LOCAL-FINDINGS 没有充分展开的反证：生产观察函数 _consumed:467–495 本身使用的就是 self.injected_fact_id，并检查这个 ID 被当前 Goal 来源引用。

所以，准确裁决是：

最终证据裁决器不能严格拒绝错绑或不一致的阶段摘要；目前没有证据证明真实 staged 旅程已经消费了错误 correction。

这属于 W3 验收伪阳性风险，不能直接改写成 Runtime 的 correction 丢失缺陷。
SOURCE-SLICES(1)

对本地记录还要保留两项审计限定

第一，“已完成 fixture，所以只是测试污染、产品正确”不能作为完整结论。

已完成 fixture 不适合证明“本次实际完成了改动”，这点成立；但用户把一个本来正确的目录交给 Agent 检查，同样是正常使用情境。不能要求先把文件改错、无意义重写，或者换一个未完成目录，产品才会正常收尾。

另一方面，可见的 verify_goal_completion:1871–1969 没有要求必须发生写 effect。附件也没有给出那次 FAILED_FATAL 的具体错误链和 confirm_file 完整路径。因此，目前不能指定“删除强制写入要求”或“修 _finish_no_progress”这样的根因修复。应把它保留为必须通过的定点场景，先核对失败原因。
LOCAL-FINDINGS
 
SOURCE-SLICES(1)

第二，RESULTS 的矛盾目前只是附件转述。

RESULTS 本体未附，不能把 LOCAL-FINDINGS 描述的全部矛盾都标成我独立核实过。可以直接确认的是：README 和状态文档把当前证据指向 RESULTS；状态页仍有旧日期标签。所需动作是整理一个准确的当前摘要，不是重写所有历史记录。
CURRENT_CAPABILITY_STATUS

二、上轮 W1／W2／W3／G 的逐项裁决
项目	裁决	应保留的进展	当前未闭合内容
W1	部分完成	从当前 Goal 绑定的真实 USER_MESSAGE 推导交付下界；完成门与 blocked 指引使用同一判断	F1 可穿透；F2 会制造错误义务；已正确任务的正常收尾尚需定点核验
W2	本轮候选选择增量基本完成，保留	散文 targets 下，只从当前 admitted 文件 criterion 获取精确候选；普通 y 仍单次，复用仍显式 opt-in	附件未完整提供租约铸造、扣次、到期全链，不能声称本次独立重验了全部旧边界
W3	部分完成	normal 不注入、不催促、不救场；staged 只做预定干预；七个 supplement 键严格检查；外层预算参数转发已改	Goal revision 与 state revision 混用；聚合阶段未严格绑定同一个 correction
G	尚不能独立签署完成	candidate manifest 已更新；执行者报告安装和两个真实样本通过	缺当前最终 candidate／wheel／安装来源及真实阶段原始摘要；当前独立 full gate 的结束结果未附

W2 的新增代码值得保留：state.py:2011–2042 限定文件写工具、WRITE、无 egress、安全路径和当前 admitted 精确路径，没有从散文或当前文件推导父目录；普通 yes/no 仍走原 ResolveApproval。不过，不能仅凭注释把全部 admission 来源及租约执行链宣布为已独立验证。
SOURCE-SLICES(1)

W3 也不是“全部没做成”。evaluate_final:562–569 确实拒绝缺键、未知键和非严格 True 的补充判据；normal 和 resume 阶段取消自动“继续”与救场的改动也是真实存在的。剩余问题集中在阶段证据判定。
CHANGES

此外，已有完成门仍保留 unknown 优先、Goal revision、typed oracle、mandatory evidence、predicate digest 和资源关闭等校验。这些防线不应因 F1/F2 被推倒。
SOURCE-SLICES(1)

三、现在究竟是什么产品阶段，有哪些能力
1. 三种使用阶段的判断
使用阶段	当前是否适合	理由
开发者监督自用	可以继续	已有完整任务链路和实质工具能力；当前必须知道假完成与恢复拒绝缺陷，不能只看完成标签交付成果
小范围邀请 beta	当前快照不建议放行；三个有界包收口后适合	F1 与 F3 都发生在拟承诺的日常主路径内，不应把发现这些缺陷的责任交给受邀用户
面向普通用户公开首发	当前不适合	核心缺陷未闭合，最终安装与真实旅程证据未充分绑定；首发对象还应明确限定为拥有模型 API、具备基本终端能力的 macOS 用户

当前状态页将各能力记为 implemented-candidate 是合理的证据声明。历史验收仍能说明已有进展；当前发行结论需要当前候选证据。**无需把所有可选能力重新晋级为 accepted，才能发布一个范围更窄的 CLI beta。**
CURRENT_CAPABILITY_STATUS

2. 能力矩阵

下表中的“已有”指附件支持实现存在及其边界，不表示本次把所有能力重新运行验收了一遍。

分类	能力	当前可准确描述的范围
已有核心实现	对话、澄清、持久任务	同一入口处理直接回答与有界任务；Goal、更正、暂停、恢复、取消、/new 已有
已有核心实现	当前目录文件与检索	读、列目录、写、编辑、逐层建目录；路径、全文、分段和本产品 workspace 历史检索
已有核心实现	本机执行	受治理的 local_process，以及 macOS Seatbelt 下的 sandbox_exec、受限 shell_exec；审批与执行边界明确
已有核心实现	长会话上下文	确定性预算、安全边界自动压缩、压缩前原始归档；摘要不替代任务和授权事实
已有核心实现，但有确定缺口	完成可信度	Runtime evidence gate 已有；明确文件下界存在漏识别与误识别
已有核心实现，但有确定缺口	外发确认与恢复	精确 disclosure receipt 已有；恢复后的拒绝路由及 TUI 投影未闭合
需配置、支持范围有限	Remote provider	OpenAI-compatible、Anthropic-compatible，以及精确配置的流式路径；不能外推为任意兼容服务均已验证
需配置	公开 Web	固定 Tavily Search/Extract，逐次精确批准；未配置时不启用公开 Web 检索
需配置、能力有限	Memory／owner preference	有来源的本地词汇召回与显式批准的信息维护；两者权限和作用域分开，非语义记忆系统
需配置、能力有限	Skill／MCP	显式 trust root／catalog、可选依赖；受限 Skill 和 stdio MCP；开放 object schema 与 strict tools 存在已声明组合限制
需配置、能力有限	SubAgent	一个有界只读 child，复用同一 Runtime；不继承父侧写权限，不是并发多层派生
可选，当前证据有限	TUI／隔离 Chromium	TUI 有恢复披露缺口；browser 为专属隔离环境，D06 真实模型验收尚未完成
控制面有实现，安装入口尚不可直接使用	Scheduler	当前 wheel 未装配可运行 host composition；直接调用返回 needs_019_config，不能描述为开箱可调度
没有或未承诺，首版无需补	更广的平台能力	跨平台沙箱、个人浏览器和桌面控制、任意网站兼容、后台自治、插件市场、并发 multi-agent、语义／向量 Memory、手动 /compact 和 /context

上述范围由 README、架构和扩展合同共同说明；可见 composition.py:472–561 也确实只装配一个 ToolRuntime、ContextManager 和 AgentRuntime。Scheduler 的未配置拒绝分支则在 automation/cli.py:99–108 直接可见。
README(9)
 
EXTENSION_CONTRACTS(1)
 
SOURCE-SLICES(1)

**没有并发 multi-agent，不影响它已经是一个 Agent。**当前最需要解决的是已有任务能否可信地完成、拒绝和恢复，而不是再增加一种运行形态。

四、最多三个首发阻断工作包

以下优先级用于本次发布顺序。前两个是产品修复包，第三个是发布证据包。

工作包 1：P0——修复完成下界，打通已正确任务的正常收尾

因果

F1 使明确漏做进入 VERIFIED_DONE；F2 把非交付内容变成强制义务。两者都是同一提取器及其完成门集成问题，应在一个包内解决。

最小修复边界

明确有限路径语法：中文紧邻当前支持的 ASCII workspace 路径，应与加空格等价；继续防止从绝对路径、越界路径或无效片段中截取出一个貌似合法的文件。
对整条用户事实先处理已支持的完整引文、代码块，再断句。保留正常用于点名路径的 inline-code 表达。
对已复现的版本号、输入规范、日志转述增加有限语境排除，并覆盖明确的礼貌执行请求。使用一致规则，不按 D04 任务文本特判。
完成门和 blocked 指引继续使用同一结果。保持纯派生，不新增持久协议，也不把提取结果自动提升为权限或 criterion。
核验既有 confirm_file／确认路径能否让已经正确的文件成为当前任务证据；只在定位到实际断点后修改对应准入、提示或恢复分支。

Red／Green 验收

场景	Green 必须观察到什么
F1 两种空格写法，使用同一个非空泛化 coverage 的 omission provider	两种都不能在漏做 CLI 时成为 VERIFIED_DONE
同一任务真正补齐 CLI 和当前证据	两种都能正常完成，避免只会拒绝
版本、输入规范、跨句引文、日志反例	不产生相应无关交付义务；至少一个混合正反例走正式 Runtime，证明真正的输出要求仍被保留
已有 correction 与 freshness 用例	新增、点名撤回、无关更正、未消费更正及过期证据仍按原合同处理
全部文件已经正确	零写 effect，通过必要读取、验证和既有确认路径正常完成；用户拒绝必要确认时诚实保持未完成

不要做什么

不建立泛化 NLP 系统或模型裁判；不降低 evidence gate；不靠无意义重写、提高重试次数或 driver 催促把用例做绿。

对已正确 fixture 的真实失败，先补最小错误链。附件还不足以指定它的具体代码根因。

工作包 2：P1——补齐 CLI 恢复后的外发决定

因果

同一个待披露状态在渲染、肯定解析、否定解析和 Runtime legality 中覆盖范围不一致，导致用户看到可以拒绝的提示，却无法按提示拒绝。

最小修复边界

用一个局部、只读的“当前可应答披露决定”判断统一 CLI 渲染及 yes/no 路由，覆盖原 active 状态与恢复后的无 active 状态；Runtime 保留最终合法性裁决。
no 沿用已有安全退出语义：停止本次前台推进，保留任务和未决决定，不提交新的业务消息、不生成 acknowledgement。
保留 [y/N] 时，让回车执行相同拒绝语义。
提示准确说明“此次待发送信息未外发，任务已保留”，避免让用户误以为此前整个任务从未发送过请求。
保留当前 digest、receipt 和 Goal 状态检查，暂停状态仍须先恢复。

Red／Green 验收

通过真实 pause → 新进程 resume 形成该状态，使用脚本 provider 观察请求增量：

y/是：确认当前请求并继续原任务。
n/no/否：不进入 SubmitMessage；无新增 correction；无新 receipt；相对输入前的 provider 请求增量为零。
空回车：与提示约定一致。
旧 digest 或不合法状态下的显式 ack：仍被拒绝。
原 active disclosure 的 yes/no：保留一个回归。

不要做什么

不把拒绝转成自动继续；不扩大同意范围；不把工具审批和 Provider 外发同意合并。

本次按 CLI 首发裁决，TUI 留作非阻断已知限制。若后续把 TUI 一起纳入首发承诺，再在本包中补同一状态投影，不重开整个 UI 项目。

工作包 3：P1——修正 staged 判据，形成一个当前候选的发布证据

因果

当前 driver 的部分成功项不足以证明冻结合同；安装与真实层又主要依赖自报摘要，因此无法据此签署当前候选的 G PASS。

最小修复边界

基于现有 Goal revision 前后值确认严格数值推进；state revision 只作诊断。不要继续用两个布尔的 OR。
强制同一非空 injected_fact_id == consumption.fact_id，且它同时出现在 durable correction 和当前消费来源中。
用已有 observation 绑定同一个 Goal，再核对 pause、新 PID resume 和恢复推进。
保留 normal 无催促、staged 预定单次干预、七键严格检查及预算边界。
产品修复完成后固定一个最终候选，绑定 source／manifest、wheel、安装来源和验收记录；同步一个当前摘要。

Red／Green 验收

只有 state revision 增长：必须失败。
durable correction 为 A、consumption 为 B：必须失败。
同一 correction、同一 Goal、Goal revision 真实推进，其他阶段条件满足：可以通过。
原有缺键、未知键、非 bool、非新 PID 等负例继续拒绝。
安装及真实样本必须绑定最终候选，不能混用此前产品字节的 PASS。

不要做什么

不新增评测平台，不反复刷真实样本，不重晋级所有历史 capability，不伪造 reviewer seal，也不把 commit/push 当成本次审计的隐含授权。

如果已有真实阶段记录包含充分原始字段，可以先用修正后的 evaluator 重判其当时身份的结果。最终产品代码发生变化后，旧结果仍不能直接证明新候选。

五、哪些做重了、做轻了，交互磨损在哪里
做重的主要是当前状态的表达与重复资格证明

当前文档承载了大量 milestone、seal、promotion、历史 gate 和身份漂移叙述。它们有追溯价值，但普通用户很难快速判断：

我该装哪一个候选；
这个候选支持什么；
哪些路径已经验证；
遇到未完成时该怎么继续。

这次合适的减法是：**一个当前摘要、一个支持范围、一个安装来源、一个有限交付门。**历史记录保留并明确标为历史，不需要大规模文档重写。

也不能仅凭接近四千个测试就判定“测试做重了”。附件未提供全部测试正文，无法据数量判断哪些应删除。应减少重复验收轮次，保留承载真实行为和安全边界的验证。
CURRENT_CAPABILITY_STATUS

做轻的是普通输入与普通任务状态的完整性

中文不加空格、礼貌请求、引用一份规范、拒绝一次外发、接手已经正确的文件，都是很普通的使用情境。这些边界值得优先于新增能力处理。

特别是正常收尾：Runtime 应自行推进可执行步骤、使用已有验证工具、报告明确阻塞原因。用户负责必要治理决定，不应反复补一句“继续”“检查另一个文件”“现在可以结束了”。README 已经写了这个产品承诺，W3 取消 driver 救场正是在使验收接近它。
README(9)

审批、外发确认与业务催促，应分开评价
类型	判断
文件或进程审批	保留精确授权；使用已实现的显式精确复用减少重复决定
Provider 外发确认	保留目的地、模型和数据类别的同意边界；优先修拒绝与恢复
已有成果确认	清楚说明是在确认当前文件作为成果证据，避免让用户以为还要重新批准写入
“继续”、重复纠正、替模型补收尾	应尽量为零；遇到真实权限、预算或未知结果边界时明确停下

自报 normal 的 11 次、staged 的 15 次“治理决定”，没有拆出上述类别，不足以证明审批疲劳已经改善，也不足以证明所有决定都多余。利用既有记录分类即可，不需要新增仪表盘。请求数、墙钟和治理次数也不等于供应商实付。
LOCAL-FINDINGS

六、建议的最小发布合同与有限验收集合
最小发布合同

建议第一版明确承诺：

面向拥有模型 API、具备基本终端能力的 macOS 个人用户，通过安装好的 first-agent 在当前目录完成有界文件和代码任务。支持必要澄清、精确审批、拒绝、更正、验证、暂停和重启恢复。VERIFIED_DONE 表示当前约定的完成标准与证据通过；文件摘要和工具退出码不被解释为任意任务语义正确的保证。

只把本次真实样本实际使用、配置与身份有记录的 provider 组合列为首发验证范围。其他 adapter 和可选能力保留相应限制。

当前 README 仍要求用户自己构建 wheel。首发应给出明确的可安装候选及安装说明；这可以是一个确定的 wheel，不需要新建分发平台、自动更新系统或 GUI。
README(9)

有限验收集合
验收组	必要内容	证据要求
完成下界	F1、F2、混合正反例、既有 correction／freshness	正式 Runtime＋脚本 provider；不能只测正则函数
已正确任务	零写 effect，检查及必要确认后正常收尾	先核对已报告 fatal 的最小原因，再验证既有合法完成路径
披露拒绝与恢复	active／恢复状态的 yes、no、回车、过期 ack	CLI 实际输入路径；核对 provider 请求增量、receipt 和用户事实
原授权与未知结果边界	首次 y 单次、显式精确复用、修订／过期失效、unknown 不重放	复用已有关键回归，不扩展完整能力矩阵
driver 可信度	Goal revision、同一 correction、七键、新 PID、无额外催促	有针对性的负对照和一个正向轨迹
清洁安装＋normal	non-editable wheel；源码树外 setup → 启动 → 小任务 → 验证 → 退出重开	可与 E1-A 合并，避免重复真实调用；入口和模块来源均属于该 wheel
staged 真实样本	一次预定 correction，消费后 pause，退出，新 PID resume，完成	同一最终候选；typed terminal 和冻结业务判据一起通过
常见失败	缺凭据／401、断网、预算耗尽；保留任务并给明确下一步	优先使用现有离线 HTTP／故障夹具，不必付费制造失败

最后对最终候选跑一次既有完整门及静态检查即可；不按每个探针反复全测。CONSULTATION 中的 focused 285 通过是本地记录，完整门在提交附件时仍在运行；不能把它写成已经结束的独立 full PASS。
CONSULTATION(2)

**已正确任务还需要一个证据限度：**离线成功只能证明产品确认路径可通。若那次真实 FAILED_FATAL 仍无法解释，应保留“真实 no-op 行为未闭合”，不能因替换 fixture 后成功就销账。是否需要一个额外有界真实定点样本，应由这项最小失败证据决定，不常规追加多轮 dogfood。

**停止条件：**上述确定反例关闭、正向路径成立、最终候选身份一致、有限验收记录齐全后，停止本轮修复。可选能力、更多 provider、全部历史里程碑和泛化语义评测不再进入本轮。

七、目前准确缺少哪些证据

这些缺口影响签署范围，不代表相关工作一定没做过。

最终候选与安装身份。
candidate manifest／内容摘要、wheel 摘要、安装入口和关键模块来源，以及它们之间的关联。HEAD + 17 changed 不能唯一标识交付字节；未提交也不妨碍用明确 manifest 绑定候选。

E1-A／E1-B 的最小可核对摘要。
产品身份、provider 配置身份、Goal ID、correction ID、Goal revision 前后值、PID、typed terminal、冻结判据和实际请求记录。无需 key 或完整私有对话。

已正确 fixture 失败的最小错误链。
首个被拒绝的 typed control／criterion、对应错误、当时准入及证据状态、confirm_file 是否可见可达、最终 fatal 分类。

当前完整门的结束结果及当前 RESULTS 摘要。
执行者自报的 full 3947／1 skip、installed 58／58、两个真实样本 PASS 可以记作已有报告；附件不足以让我把它们升级成“已独立核验的当前交付”。
LOCAL-FINDINGS

费用不需要成为新的前置项目。沿用已有硬请求预算和累计 ledger，分清请求次数、授权上限、估算费用与供应商实付即可；未提供的实付保持未知。
KERNEL_ARCHITECTURE(1)

八、codex_execution_advice

以下仅是后续实施建议，不构成本次产品修改、真实 API、commit/push 或发布授权。

YAML
codex_execution_advice:
  implementation_plan:
    - priority: P0
      work_package: "完成下界与正常收尾"
      actions:
        - "修正中文紧邻路径的有限识别边界。"
        - "先处理完整非权威引文和代码块，再断句。"
        - "排除已复现的版本号、规范输入和日志转述误义务，保留真实输出要求。"
        - "保持权威来源、完成门、blocked 指引及权限边界一致。"
        - "核对已正确 fixture 的最小失败链；验证既有零写入完成路径，仅修查明的断点。"

    - priority: P1
      work_package: "CLI 恢复后的外发决定"
      actions:
        - "统一 live 与恢复后待披露状态的局部判定。"
        - "让 yes/no/空回车与当前提示一致。"
        - "拒绝不进入业务消息，不生成 receipt，不产生新的 provider 请求。"
        - "保留 exact digest、暂停状态和 Runtime legality。"

    - priority: P1
      work_package: "staged 判据与当前候选交付证据"
      actions:
        - "从原始前后值核对 Goal revision 推进，state revision 仅作诊断。"
        - "强制 injected_fact_id 与 consumption.fact_id 相同并绑定同一 Goal。"
        - "保留 normal 无催促、staged 单次预定干预、七键严格检查和既有预算。"
        - "固定最终候选及 wheel 身份，复核安装来源。"
        - "用一个当前摘要对齐源码、安装、真实层结果与已知限制。"

  non_goals:
    - "不新增第二 loop、模型裁判、泛化 NLP 或新持久协议。"
    - "不把识别结果升级成权限，不扩大授权范围，不以免审换体验。"
    - "不靠无意义重写、提高重试次数或 driver 救场使任务通过。"
    - "不新增 GUI、浏览器能力、调度宿主、插件市场或跨平台改造。"
    - "不重验或重晋级所有历史 capability。"
    - "不新建大评测、费用或观测平台。"
    - "不自行调用真实 API、commit、push 或发布。"

  optional_subagents: []

  verification:
    offline:
      - "正式 Runtime 下的 F1 非空泛化 coverage 漏做反例及完整正例。"
      - "F2 误提取及混合正反例。"
      - "已正确任务零写 effect 的正常完成路径。"
      - "CLI 恢复披露的 yes/no/空回车及 stale ack。"
      - "driver 的 state-only revision、不同 correction ID 和既有七键负例。"
      - "复用必要的授权、freshness、unknown 和失败恢复回归。"
    installed:
      - "最终 non-editable wheel，在源码树外验证默认产品入口及模块来源。"
    real:
      - "仅在获得对应授权后完成最终候选的 normal 与 staged 两个有界样本。"
      - "normal 可兼作清洁安装真实旅程；不得混用不同产品身份的证据。"
      - "已正确任务的额外真实验证，仅在最小失败证据仍无法闭合时定点决定。"
    final_gate:
      - "定向验证完成后，对最终候选执行一次既有完整门及静态检查。"
      - "未授权或缺证据的项目如实标记，不写 PASS。"
    stop:
      - "三个包及有限交付门闭合后停止，不继续开放式扩展。"
      - "仍有未闭合项时，只报告具体失败、最小缺证据及其发布影响。"
