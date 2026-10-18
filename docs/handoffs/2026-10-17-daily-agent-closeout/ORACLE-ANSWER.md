Executive verdict

我的结论：PR #5 后已有不少实质修复，功能范围也足够支撑“macOS、单用户、CLI、本地项目任务为主”的日用 beta；但当前还不能把“任务结果可信与自主收尾”整体结案。接下来主要是修复现有链路，不需要继续增加能力。

本轮应明确保留四个不同结论：

项目	当前裁决
非空泛化 coverage 导致漏做仍 VERIFIED_DONE	P0，R2 仍未解决。 本地复现报告与源码因果一致。
E1-A 业务通过，40 次请求后未自行终结	P1，正常任务闭环 INCOMPLETE。 安全暂停成立，正常完成验收未通过。
E1-B 新纠正与跨进程恢复	保留公开记录中的有界成功结果。 不能替代 E1-A，也不能直接覆盖后续修改。
当前安装交付	最新身份的证据链未闭合。 不能继承旧 wheel 的 PASS，也没有证据认定当前安装已经损坏。

建议收敛为：

W1：补齐完成约束与收尾指引。
W2：让精确文件授权在普通任务中实际可用。
W3：纠正真实旅程的干预和判定，验证自主收尾。
G1：最终代码身份、安装与交付门。

本次判断绑定附件所述 0cc0db1 快照。我完整阅读了 CONSULTATION，并核对其余附件。没有运行完整产品、真实模型或本地报告中的 Runtime 探针；实际执行的检查仅限从附件原样提取的两个 driver 纯函数，使用合成输入验证判定和参数传递问题。310 passed、E1 请求数和安装结果均属于附件中的执行报告，不是我的独立复跑成绩。
CONSULTATION(1)
 
LOCAL-AUDIT

一、已完成与未完成矩阵

这里区分三种证据：源码可确认、执行记录转述、尚待补证。不能把它们合并成一个笼统的 DONE。

事项	本轮可确认的事实	裁决与接续动作
R1：严格旧拒绝前缀	diff 增加了连续前缀，以及 rejected is True、executed is False、is_error is True 和无 UNKNOWN 矛盾的检查	保留修复，不重做。 完整故障恢复成绩仍依赖既有测试报告；交付门复用必要节点。
R2：身份、解码与来源可见性	coverage 纳入 receipt digest；嵌套未知字段、非法数组和 ID 元素受到检查；Goal 来源被 pin	这些子项已有实质实现。 它们证明结构、身份和输入可见性，不能证明业务覆盖完整。
R2：证据刷新	新读回可从 durable facts 重新导出，并刷新同 ID 的旧 evidence	保留。 不应再把“旧缓存永久卡死”列成未修问题，也不应顺手放宽 freshness。
R3 撤回、C1/C2 组合测试	LOCAL-AUDIT 报告已有实现和测试；附件没有给出这些项目的全部实现与断言	不重新开启修复。 但不能写成本顾问已独立核验所有细项。
R4：无参数范围授权	CLI 当前提示可以直接使用 /approve-goal-target；展示、解析与 Runtime 共用 scope 判断	隐藏 ID 的交互问题已经修了。 后续只处理普通任务中 scope 不适用的问题。
401 与累计预算提示	401 可显示配置的凭据环境变量名；累计预算耗尽时不再建议无效地反复 /resume	局部改进已实现。 不需要另建凭据体系；当前安装态补一次恢复提示验证即可。
R2：非空泛化完成声明	单条 coverage 可以覆盖全部现有 fact/criterion ID，却不覆盖被草稿漏掉的 CLI	P0，未闭合。 需要真实的完成约束变化，增加文案或 coverage 行数不够。
blocked 修复分支	当前仅凭已接纳物理证据可导出，就要求改报 completion，并禁止 blocked	逻辑依据过强。 具体合法 blocker 被误拒仍需合成复现，合并到 W1。
散文 targets 与复用授权	targets 只要求非空，但精确授权要求 path in goal.targets	P1，确定的适用性缺口。 逐笔任务仍能做；不能据此推算审批必然能减少多少。
E1 与 driver	E1-A 未终结；normal 会额外注入 correction；driver 能代发“继续”与 /resume	P1，验收口径和正常收尾未闭合。 保留 evaluator 的 typed＋业务双门，修旅程设计。
I1/G1 当前身份	README 使用旧安装、全量数字描述“当前 identity 完成”；附件缺最终 manifest/wheel/origin 链	交付门待补证。 保留历史成绩，重新绑定本轮最终产物。

上述实现主要可在 CHANGE.patch 的 state.py、checkpoint.py、normalize.py、context.py、CLI 与 main.py 变更中核对；范围授权和完成检查的具体逻辑见 SOURCE-SLICES。
CHANGE
 
SOURCE-SLICES

二、对关键问题的独立裁决
1. 非空反例成立：当前缺的是完成范围的下界

源码链条很清楚：

原始 D04_TASK 明确要求 retry_app/cli.py 使用新参数，并保留旧别名、拒绝歧义。
遗漏测试中的 draft 只有 service target 和 service criterion。
_claim_for() 生成一条泛化声明，引用当前全部来源 fact 和全部 mandatory criterion。
_require_requirement_coverage() 检查的是来源与 criterion 的集合关系，没有独立检查原始要求中的 CLI 是否进入待完成集合。

也就是说，以下形状能满足当前检查：

纯文本
当前 admitted = {service}
coverage = [{
  requirement: “完成用户当前权威要求”,
  source_fact_ids: 全部当前来源,
  status: satisfied,
  criterion_ids: {service}
}]

模型缩小了“需要证明什么”，再声明缩小后的集合已经满足；Runtime 验证了这个集合的身份和证据，却没有发现范围被缩小。

对应源码是：

test_task_trust_completion.py:426–431：原始业务要求；
:842–863：只提 service 的遗漏草稿；
:109–139：泛化 _claim_for；
state.py:1651–1715：实际 coverage 检查；
loop.py:2941–2972：导出证据、保存 claim、验证完成的调用链。
SOURCE-SLICES

LOCAL-AUDIT 报告的 verified_done、CLI 字节未变、两个业务字段失败及 cli_both_names=false，与这条源码链一致。两个冻结的过程字段本来恒为 false，不能把它们另算成两个新缺陷。这条反例已经足够否定“当前完成门挡住了原始双组件漏做”；它不证明真实模型经常如此，也不需要再次付费试出相同现象。
LOCAL-AUDIT

2. 现有遗漏测试有价值，但它证明的事情被说大了

_FileTaskProvider 的阶段已经写死：

写 service → 空 coverage 被拒 → 写 CLI → 读回 → 完成。

735–742 明确安排下一阶段写第二文件。因此现有测试能够证明：

空 coverage 会被拒；
拒绝后能够继续主 loop；
原始输入仍在上下文中；
后续写入、重新读回与完成可以正常衔接。

它没有证明产品识别了 CLI 遗漏。 CLI 是测试脚本按既定步骤补上的。

这个测试应保留，并把说明改准确；在旁边增加“提交非空泛化 claim 后绝不安排补写 CLI”的独立负例。不能通过给旧测试改名字来完成本轮验收。
SOURCE-SLICES

3. 完成合同应诚实收窄，但不能借此给旧 R2 改判

我不建议继续追求“Runtime 证明任意用户任务的全部语义正确”。当前代码自己也说明：requirement 的语义由模型提供，Runtime 检查结构、版本、来源和证据绑定。它没有独立的全业务裁判。
SOURCE-SLICES

更合理的产品合同是：

Agent 负责完成工作并复核用户要求；Runtime 验证明确的交付对象、实际执行结果和当前版本证据；交付时展示具体完成内容与通过的检查。业务正确性声明不得超过这些检查的实际覆盖范围。

但这不等于把 VERIFIED_DONE 的文案改软就算修复。

本轮推荐保留现有终态与冻结正常正例标准，先补“明确交付对象不能被草稿遗漏”的约束。 不预设新增终态、新持久字段或新 owner。若实施者发现只能通过改写完成状态语义才能继续，应单独列出合同变更，旧 R2 保持未解决，不能暗中改原 VALIDATION。

尤其不能接受以下“修复”：

一条 coverage 改成两条；
禁止“全部完成”这类措辞；
再要求模型自审一次；
多引用几个 fact ID；
让 CLI 多读一次或无意义地重写一次，就宣称业务已经验收。
4. E1-A 不是假完成，但它确实没有通过正常完成验收

原 VALIDATION 要求正常样本“产品须自己闭合”，也明确指出诚实未完成仍不满足正例目标。因此应这样记录：

样本	应保留的结果	不能据此宣称的结果
E1-A	业务检查通过；40 次请求后安全停在 paused_limit	正常任务已经自行完成、R2/E1 整体 DONE
E1-B	公开报告中的 staged correction、跨进程恢复与 typed 完成成功	零催促普通任务成功、所有恢复情况成功、当前后续版本全部通过

这里应挑战两种相反的误判：**不能把 E1-A 安全暂停说成假完成，也不能把安全暂停说成正常任务验收通过。**
VALIDATION(1)
 
LOCAL-AUDIT

目前也不能把 40 次请求具体归因于 freshness、blocked 分支、审批次数或模型能力。附件没有逐轮证据。下一次只对新建合成样本记录请求用途和拒绝原因即可，不需要另建监控平台。

5. driver 还存在两个本地摘要没有充分展开的问题

第一，normal 可能把真正完成的正例判失败。

REQUIRED_EVIDENCE["normal"] 要求 correction_injected；但 _next_standard() 看到 typed 完成会立即退出。因此，正常任务已经完成、业务全过、没有额外 correction 时，evaluate_final() 仍会判 incomplete。

我对附件中原样提取的该纯函数做了合成检查，结果为：

纯文本
normal
typed_terminal = true
业务与补充检查 = 全部 true
correction_injected = false

结果：incomplete
原因：correction journey evidence missing: correction_injected

第二，现有 journey --max-resumes 0 不能真正关闭子进程恢复。

_child() 透传 _provider_extra() 的结果；后者没有 --max-resumes 和 --max-consents。实际 operator 又从 run 子命令参数读取这些值。因此只修改外层命令行参数不够，子进程仍可能使用默认值。

这两个问题分别对应 driver 的 95–106、278–282、490–492 和 669–675、790–836。我的纯函数检查也确认后者没有包含这两个参数。
SOURCE-SLICES

同时，evaluate_final() 在缺 typed 终态时确实会判失败，不应把它整体描述成“伪造 PASS 的 driver”。需要保留这个判定主体，修正旅程条件、干预行为和参数传递。

6. 当前哪些地方做重了、哪些做轻了

做轻了的地方：

coverage 的“逐项复核”主要是模型自报，完成范围缺少独立约束；
新 UI 解释了为何不能复用授权，却没有解决普通任务形成精确目标的路径；
正常旅程允许额外纠正、催促和恢复，削弱了自主完成证据；
当前交付身份没有跟随最后的产品修改刷新。

已经偏重、不应继续加码的地方：

再堆一层 completion 字段或自审回合，无法解决当前因果；
blocked 分支在物理证据齐全时强制要求 completion，容易增加无效往返；
为少数收尾失败重跑全部能力、重绑全部旧 seal，交付成本过高；
把长期来源 pin 的上界问题升级成长记忆系统需求，没有当前失败证据。

应该保持的约束：

写入或潜在可写执行后，旧验证可能失效；
UNKNOWN 优先于完成；
用户明确 opt-in 才能复用授权；
同 Goal/revision/workspace、同工具、精确目标、有效期、次数与撤销约束；
Runtime、ContextManager、ToolRuntime 的既有所有权。

这些边界没有被当前证据证明需要放宽。

三、最小接续执行包：三个主要工作包
W1｜P0：补齐明确交付对象的完成约束，并修正收尾指引

精确目标

保持原始 D04 输入、遗漏 draft 和真实 Runtime 路径不变：仅完成 service、提交非空泛化 coverage 时，不得进入 VERIFIED_DONE；完整完成 service＋CLI 后，仍能正常终结并通过独立业务验收。

非目标

不实现任意自然语言义务解析器，不引入第二模型裁判，不内置 D04 grader，不增加通用义务平台，不默认增加请求预算。

触碰模块

现有 Goal admission／首次批准目标绑定、state.py 完成检查、evidence.py 必要证据规则、loop.py 修复指引，以及对应现有测试。只有投影确需调整时才改 context_control.py。

实施前只需补读附件缺失的几处：

完整 Goal admission 与首次批准文件绑定函数；
verify_goal_completion() 的后半段；
FILESYSTEM_DIGEST、TOOL_RECEIPT 的具体 predicate 与 derive；
_rejection_still_blocks_current_goal() 和 blocked 前置检查。

实施顺序

先冻结真实 Red。
在既有 test_task_trust_completion.py 中保留原始任务和遗漏草稿，service 写入、读回后提交非空泛化 claim；provider 后续不安排 CLI 写入。断言禁止 VERIFIED_DONE，同时记录文件字节、业务字段、补充检查、admitted/coverage 和调用数。

建立独立于最终 coverage 的明确交付对象下界。
当前任务中的 retry_app/cli.py 必须…… 是明确交付要求，不能因模型草稿漏列而消失。优先在既有 Goal/admission 中承接，基于当前权威输入及已消费 correction，复用现有 revision、criterion 和证据绑定。

这个下界只处理明确的正向文件交付要求。不能收集所有路径就强制修改：SPEC、输入文件、只读参考、引用中的路径和禁止修改对象必须区别处理。不能把模型最终补写的一条 coverage 当作该下界的独立来源。

完成门拒绝缺失对象，给出实际可修复的缺口。
指引必须说明当前缺哪个交付对象或哪种证据，不能仅要求“再补一条 satisfied”。补做通过既有主 loop、审批和工具路径完成，测试不得预先灌入正确的 admitted 集合。

保留检查的真实含义。
原正常 prompt 已要求 pytest -q，继续要求现有对应执行证据；文件 digest 不能替代执行回执。也不能把 pytest exit 0 宣称为天然覆盖 CLI 的证明。冻结外部 grader 和补充检查继续独立保留。

收尾指引采用符合当前 freshness 的顺序。
完成全部修改和可能产生写入的验证，再做必要最终读回，最后提交 claim。不得通过减少验证约束来让收尾更快。

blocked 分支只修已经证明的误判。
先构造“已有 service 证据，但另一明确要求有 durable blocker”的合成例，核对前置守卫。若能到达错误的强制 completion 分支，复用同一完成缺口判断修复。derive 成功最多证明当前已接纳证据可导出，不能单独证明不存在其他未完成要求。

必要正反例

场景	验收
原始非空泛化 claim，CLI 未做	不得 VERIFIED_DONE；拒绝原因针对实际缺口
相同结构、改名后的双组件任务	同样阻止遗漏，排除 D04 文件名特判
两组件完整实现、证据有效	自行终结；两个业务字段与全部补充检查通过
已正确、无需修改的对象	不得为了凑证据强制无意义改写；只依据实际有效证据判断
最后写入后沿用旧验证	保持拒绝；按既有刷新路径补齐后可完成
合法 blocker／无依据乱报 blocked	两者仍能区别处理，不能一律强推 completion 或一律接受 blocked

复用已有 correction、UNKNOWN、身份与刷新回归，不重新制造一整套测试。

停止条件

原始负例和改名同构负例被挡住，完整正例保持通过，没有测试预灌义务、路径特判或权限放宽。

必须同时说明：这个约束修复的是明确交付对象被漏掉的入口，不会把文件 digest 变成任意业务语义证明。 如果实施开始滑向通用 NLP 义务系统，应停止扩张、记录最小设计缺口；不能以只改文案作为本包完成。

W2｜P1：让已确定的精确文件目标能够被用户选择复用授权

精确目标

普通 SPEC 驱动任务不再因为 targets 是散文，始终无法获得精确文件复用选项。保留逐笔批准为默认，复用仍由用户明确选择。

源码依据是：GoalDraftProposal:1594–1595 仅检查 targets 非空，而 _goal_target_authorization_scope:1863–1866 要求精确成员关系；views.py:203–223 目前只解释“不适用”。
SOURCE-SLICES

非目标

不把任意 pending path 自动变成可复用授权，不推断父目录，不开放目录 allow-all，不让文件授权覆盖 shell/process，不迁移所有旧 Goal。

触碰模块

目标提案说明、现有首次批准与 admission 绑定、_goal_target_authorization_scope()、共享 views，以及已有 CLI／goal policy 测试。

实施顺序

冻结“散文 targets → 同工具对同文件多次写入 → 始终没有复用选项”的完整 CLI/Runtime 反例。
对新 Goal，明确提示已知文件目标使用精确 workspace 相对路径，散文放在 outcome/scope。
对执行中才确定的文件，核对现有首次批准所铸造的目标/criterion。精确 scope 可以来自当前 Goal 下已由 Runtime 接纳并经实际批准绑定的文件目标，而不能来自任意模型字符串。 如果采用这一局部兼容，必须复用现有 provenance 和 revision 约束。
展示与执行继续使用同一 scope 判断。第一次普通 y 不产生复用授权；下一次出现合法候选时，用户明确 opt-in 才产生绑定。

这里有个重要实施限制：当前 context_control.py:260–285 在没有用户 correction 时不允许模型自行发送 goal_delta_proposal。因此不能把“让模型稍后随便发 delta 修 targets”写成现成解决办法。
SOURCE-SLICES

完整正例

普通 SPEC 输入 → 主 loop 确定文件 → 首次精确批准形成当前目标绑定 → 同工具再次修改该文件时出现可用复用选项 → 用户明确选择 → 后续同范围执行按既有绑定复用 → 最终任务完成。

必须保留的负例

普通 y 后下一次操作仍需批准；
换文件、换工具、换 Goal/revision/workspace，旧授权不可用；
次数耗尽、过期或撤销后不可继续复用；
同前缀相邻路径、敏感路径、符号链接和猜测出的父目录不能获得授权；
提示展示后 pending 状态变化，旧输入 fail closed。

停止条件

在上述普通任务路径中，用户确实能够选择合法的精确文件复用授权，且所有原有边界保持。

不设“17 次审批必须降到 3 次”之类指标。 旧 driver 始终回答 y，报告又没有给出同工具、同路径、同 revision 的重复分布，没有依据承诺固定降幅。

W3｜P1：修正正常旅程，暴露并验证真正的自主收尾

精确目标

E1-A 只接受一次普通任务输入和必要治理决定；E1-B 保留一次真正新增的 correction 与计划内跨进程恢复。driver 不再替产品隐藏推进需求。

非目标

不新建评测平台，不增加通用遥测，不通过提高默认预算、自动重试或催促模型取得 PASS。

触碰模块

scripts/run_task_trust_d04.py、已有 driver 测试、唯一 RESULTS 当前摘要。真实样本暴露的产品缺陷，只回到 W1/W2 对应位置修复。

实施顺序

normal 不注入 correction，也不要求 correction evidence。
normal 遇到必须额外输入“继续”才能推进的 idle，记录 incomplete；限额暂停也如实停止，不自动救援后计为普通成功。
staged 只保留冻结的一次 correction、pause/exit、一次计划内新进程 resume。额外催促与限额恢复单列。
修复外层 journey 到 run 子进程的参数透传；离线验证实际事件序列，不只验证 parser 接受参数。
保留 typed 终态、独立业务、补充检查和预算判定主体。
使用现有事件/ledger 记录必要的收尾诊断：完成声明拒绝原因、控制修复次数、验证失效原因及是否发生重复无进展。只记录本次新合成样本。

至少保留这四个判定例

合成输入／旅程	修后要求
normal 已 typed 完成、业务全过、未注入 correction	正确通过
normal 业务全过、未 typed 完成	仍 incomplete
normal 到达需要催促的 idle	不发送“继续”，如实记录未自主推进
staged 未接纳新要求、没有新 PID 或恢复未推进	仍不能通过

E1-B 还应保留 Goal 相关义务的前后投影。当前 driver 接受 state revision 增长作为部分版本推进证据，单纯 state revision 增长并不独立证明新增业务要求已经进入当前任务。这属于受影响复跑时的补证，不足以直接推翻历史 E1-B。
SOURCE-SLICES

停止条件

driver 的上述行为得到离线验证；真实样本能够清楚区分产品自主推进、正常治理决定与额外救援。不得通过调试 driver 把业务或终态失败抹成成功。

四、G1｜唯一交付门：当前身份、安装与两条有限真实旅程
1. 必要真实验收：最多两条，不无限 dogfood

以下是预算建议，不是当前授权：

每条样本最多 40 次物理请求；
两条合计最多 80 次；
总墙钟最多 60 分钟；
产品自身更低限制继续生效；
不提高默认预算来满足验收；
首轮每条只运行一次。失败后必须有具体原因、必要修复和剩余当前授权，才补跑受影响样本。
VALIDATION(1)
样本	输入与干预	必须通过
E1-A 正常任务	完整原 SPEC；一次初始任务；必要治理决定；额外业务提醒、纠正、催促、收尾提示为 0	service＋CLI 实际行为全部通过；durable VERIFIED_DONE；正常自行终结
E1-B staged	原冻结派生方法；一次新增 correction；一次计划内 pause/exit/新 PID resume；必要治理决定	新要求未提前泄露；新增要求确实进入当前任务；恢复后业务全过；durable VERIFIED_DONE

审批次数和请求次数分开记录：

Provider disclosure；
单次效果批准；
用户选择的范围复用授权；
实际效果执行数；
计划内 correction/pause/resume；
额外业务提醒、实现提示、失败解释、催促和收尾干预；
逻辑模型调用数、累计物理请求数、墙钟；
completion/control 修复的次数和原因。

一两个样本只能证明这些有界旅程，不能支持统计成功率声明。

如果发生：

业务失败但产品报完整成功：R2 仍 UNRESOLVED；
业务通过但未终结：样本仍 INCOMPLETE；
没有当前真实授权：交付本地与安装结果，真实层标 BLOCKED_AUTHORIZATION。
2. 最终安装只补一条短链

最后必要产品修改完成后，复用原 build_candidate_manifest.py 和 installed runner：

新 candidate、新 manifest，记录公开输入清单与 SHA。
构建 non-editable wheel，记录 wheel SHA。
在仓库外中立 cwd、新安装目录验证模块来源；新进程也必须证明来自安装目录。
运行原 I1 的必要节点，加上本轮非空遗漏负例、完整正例和精确授权路径；保留污染负对照。
走一条短的安装态日用旅程：
setup／启动 → 合成凭据与错误提示验证 → 完成任务 → 同进程 /new → 第二任务安全暂停 → 退出 → 新进程恢复。
最后集中执行一次原 G1，记录真实退出码、完整摘要和 skip 原因。

不运行安装态全库，不补全平台矩阵，不重验全部历史 capability。之后若又改产品，只刷新失效证据。
VALIDATION(1)

还有一个来源边界要写清楚：现有真实 driver 会把仓库根加入 sys.path，并在仓库根运行子进程。即使解释器环境装有 wheel，也不能因此把该旅程称为 installed-real。 可以分别保留“同一源码身份的真实旅程”和“对应 wheel 的安装态验证”，但不得混写来源。
SOURCE-SLICES

3. README 与结案记录的最小修改

README 已经诚实写出了 E1-A 未终结、Browser/Scheduler 限制和总体 candidate 状态，不是整篇都需要重写。

需要改的是：

把旧 3873 passed / 1 skipped、installed 41 节点绑定到真实历史 identity；
在最终新身份完成前，不再称“当前 identity 上完成”；
R2、E1-A、E1-B、I1/G1 分行记录；
继续使用唯一 RESULTS，不另建第二份 current 进度；
不自动重绑历史 seal，不把旧成绩删除或归零。
README(8)
五、首版支持范围与明确不做

首版支持范围已经可以定下来：

具备基本终端能力、自己提供 API key 的 macOS 单用户，使用一个完成当前验证的 provider 配置和 CLI，完成当前 workspace 的检索、读写、受控执行验证，以及 correction、pause/resume 和第二任务。

从“安装配置 → 普通任务 → 必要审批 → 正确收尾 → 第二任务／重启恢复”看，入口与基础能力都已经存在。当前应修的是完成、授权适用性和验证交付，不能把这些问题解释为缺少另一套 Agent 平台。README 对已有路径和可选能力边界提供了明确说明。
README(8)

本轮明确不做：

Browser D06、Scheduler host composition、MCP 扩展、Memory 语义升级、并行 Agent；
全 provider、全平台、GUI 重做、凭据托管；
第二模型裁判、通用义务平台、默认预算提升；
目录自动放行、隐式复用、放宽 UNKNOWN 或 freshness；
按文件行数拆分、为测试数量增加无价值回归；
自动迁移旧 Goal、自动重绑全部 seal、提交、推送或发布。

本次结论不需要行业材料补充，因此没有外查。附件缺少的主要是局部源码和当前交付证据，不是竞品方案。

当前咨询也没有授予产品 API、凭据读取、Git 发布或个人系统修改权限。真实预算和旅程均为建议；这些限制不妨碍当前 Codex 完成资料包及允许的合成离线工作。

codex_execution_advice
YAML
implementation_plan:
  - id: W1
    priority: P0
    goal: 阻止原始双组件任务在只完成service并提交非空泛化coverage时进入VERIFIED_DONE
    steps:
      - 先冻结原始输入不变、draft遗漏CLI、claim之后不补写CLI的真实Runtime负例
      - 补读现有admission、首次批准目标绑定、完整verify_goal_completion和证据predicate
      - 在现有Goal与admission中保留明确交付对象下界，不从最终coverage反推完整范围
      - 完成门对缺失对象或证据给出具体缺口，不允许增加satisfied文字代替实际完成
      - 保留完整双组件正例、独立业务grader、补充检查和现有freshness规则
      - blocked误拒先做合成复现；成立后复用同一缺口判断修复，不新建owner
    stop:
      - 不得以路径特判、预灌正确criteria、无意义改写或只改文案结案
      - 若需要通用自然语言义务平台则停止扩张，明确报告最小设计缺口
      - 不得通过修改原VALIDATION降低正常任务完整业务与自行终结标准

  - id: W2
    priority: P1
    goal: 让普通SPEC任务中的已确定精确文件目标实际可选复用授权
    steps:
      - 复现散文targets下同工具同文件重复写入始终不可复用的完整交互
      - 修正新Goal的目标表达，复用现有首次批准与Runtime目标绑定
      - 精确候选必须来自当前Goal目标或有现有批准来源的Runtime文件绑定
      - 不把任意pending path或模型字符串直接升级为复用范围
      - 展示与执行共用判断，普通y仍为逐笔，复用必须明确opt-in
      - 保留同Goal、revision、workspace、工具、路径、TTL、次数和撤销约束
    stop:
      - 普通任务中合法复用选项可实际使用且安全负例保持通过即可
      - 不承诺固定审批降幅，不扩展目录或process权限

  - id: W3
    priority: P1
    goal: 使normal和staged旅程准确反映产品自主推进与计划内干预
    steps:
      - normal不注入correction，也不要求correction evidence
      - normal不自动发送继续或在限额后救援，停滞如实记录incomplete
      - staged仅保留冻结的一次新增correction和一次计划内跨进程恢复
      - 修复journey到run子进程的干预参数传递并验证实际事件
      - 保留typed终态、独立业务、补充检查和预算的联合判定
      - 在新合成样本中单列治理决定、计划输入、额外救援和收尾修复成本
    stop:
      - 离线driver正反例通过后才进入已获当前授权的真实样本
      - 不通过额外提示、自动重试或提高默认预算制造PASS

  - id: G1
    priority: delivery_gate
    goal: 为最终候选建立准确的source、wheel、installed和real证据关系
    steps:
      - 复用现有focused测试，最后集中运行一次完整项目门
      - 冻结最终公开输入清单与SHA，构建新non-editable wheel
      - 仓库外验证安装来源及新进程来源，保留污染负对照
      - 覆盖完成任务后new、第二任务、安全暂停和新进程恢复的短安装旅程
      - 更新唯一RESULTS与README当前摘要，历史证据保留原身份
      - 明确区分源码真实旅程与安装态验证，不自动重绑旧seal

non_goals:
  - 新增AgentRuntime循环、Runtime owner或通用义务平台
  - 为覆盖完整性新增第二模型裁判
  - 预设新增持久化字段、终态或整体重构
  - 放宽审批、UNKNOWN、freshness、敏感路径或范围匹配
  - 默认提高请求预算、无限dogfood或重复抽样挑成功
  - 将Browser、Scheduler、MCP、Memory、并行Agent或全平台列为上线必修
  - 修改冻结grader、降低原正常任务正例标准或伪装安装来源
  - 读取私人运行记录、调用未授权API、提交推送或发布

optional_subagents: []

verification:
  offline:
    - 原始非空泛化遗漏负例及改名同构负例
    - 完整双组件正例和受影响的既有correction、freshness、UNKNOWN回归
    - 普通任务精确复用授权的完整交互及原有安全边界
    - normal无需correction的成功例、未终结失败例、子进程参数和干预轨迹
  installed:
    - 最终manifest与wheel SHA一致性及产品模块origin
    - 新进程安装来源和已有污染负对照
    - setup、当前错误提示、完成后new、第二任务与跨进程恢复
  real:
    authorization: 必须来自当前执行对话，本建议不构成API或凭据授权
    suggested_budget: 每样本最多40次物理请求，两样本合计最多80次，总墙钟最多60分钟
    samples:
      - E1-A完整原SPEC，零额外业务提醒和催促，业务全过且自行typed完成
      - E1-B冻结staged输入，新增要求确实生效，计划内新进程恢复后业务全过且typed完成
    failure_rules:
      - 产品完整成功但独立业务失败，R2保持UNRESOLVED
      - 业务通过但未自行终结，样本保持INCOMPLETE
      - 缺当前真实授权，交付本地与安装结果并标记真实层BLOCKED_AUTHORIZATION
      - 仅在具体新假设、必要修复和剩余授权支持下补跑受影响样本
  final_stop:
    - 三个工作包及当前交付门满足后停止，不自动开启下一轮能力扩张

