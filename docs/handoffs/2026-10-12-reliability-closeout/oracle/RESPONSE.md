执行裁决

当前不能把“日用可靠性收口”标成完成。A1、A2、A4 是可以从附件定位的缺陷；A3 是已发生、但尚未归因的失败；E1、E2 是证据问题，不应先当成产品缺陷修。

我对方案的主要调整是：先修 A2，避免取证工具破坏工作树；A1 按“验证取得时是否仍有可写资源”修，而不是简单追加 stop 工具名；A3 先拆分失败阶段再决定改哪层；最终只补与本次变更相关的 installed 行为和恢复过程证明。

A. 逐项裁决
项目	裁决与优先级	依据、性质	可观察用户影响
A1 / RC-02	同意缺陷成立，P1，阻塞可靠性收口。反对继续只补工具名单。	已有探针同时证明资源门关闭、旧验证被接受、同参验证仍受抑制。原合同明确要求覆盖“服务存活时验证→服务再写→关闭”。这是已知缺陷，不只是缺一个测试。
AUDIT_CONTEXT
 
CODE_CONTEXT
	可能拿旧验证认证最终内容；模型又无法运行同一验证命令，形成“错误完成”或无法收尾。
A2	同意新目录限定，P0 防误删保护，实施顺序第一。	main() 对已存在的 out 直接 rmtree，随后才获取文件清单；manifest 又独立使用覆盖式写入。危险操作成立，但没有证据表明本次已经误删。
CODE_CONTEXT
 
CODE_CONTEXT
	参数误传可删除已有目录，或覆盖源文件、旧 manifest；也会破坏后续审计的可信基础。
A3	同意必须处理，P1；反驳“已经定位共享 group.py”及“单测重跑绿即可关闭”。	全量确实失败，单独重跑通过只证明间歇性。另外两个失败目前只有执行者报告，不能合并归因。
AUDIT_CONTEXT
 
AUDIT_CONTEXT
	超时后可能无法确认清理，用户不知道能否安全继续；也可能是测试或观察链误判，需区分。
A4	同意缺陷成立，P1。	reasoning_expected = deepseek_thinking or deepseek_family_reasoning，确实让官方 Flash 身份覆盖显式 disabled；归一化又在传入身份摘要时强制非空 reasoning。离线实际传输探针与源码一致。
CODE_CONTEXT
 
CODE_CONTEXT
 
AUDIT_CONTEXT
	用户明确关闭思考，正常文本响应仍被拒绝，任务无法继续。
E1	同意旧 3679 不能称 installed 全量；反对从头重复全部安装证明。P1 交付证据门。	113 模块来源与原生安装 4 项已有独立正证据。需要绑定修复后的产物，但不必再做一轮 installed 全库 pytest。
AUDIT_CONTEXT
 
AUDIT_CONTEXT
	否则容易出现“测试的是源码，交付的是另一份安装包”。目前不能据此断言安装功能已坏。
E2	同意原论据不足；反对据此宣判发生重放。P1 过程证据门。	call ID 全唯一不能排除新 ID 重做同一操作；附件没有给出实际重复执行的正证据。
AUDIT_CONTEXT
	可能掩盖重复写入、重复外部调用；但本轮首先应补可数过程证明，不是增加永久参数去重。

Red 要分两类。 A1、A2、A4 必须先有击中当前缺陷的产品回归；A3 必须先有阶段明确的失败证据，再为定位出的原因建立回归。E1、E2 则要求证据判定器能拒绝负对照，不需要为了“先红后绿”人为制造一个产品缺陷。

B. 唯一推荐的最小修复方案
B1. A1：判断验证取得时的写入风险，不把 stop 本身一律当成写入
首先纠正原测试的证明范围

原真实服务测试不只是顺序不符。它执行 stop 后仍把 after_start 交给 registry.derive()；后续构造的重验证状态也是从 after_start 延伸，没有把 stop 的生产结果加入事实链。因此，它没有证明“资源已关闭后的证据判断”，也没有证明最后完整完成门能够通过。
CODE_CONTEXT

推荐合同

把下面这条规则加到现有 workspace 验证的资格判断：

一条验证只有在取得该验证的事实位置上，没有尚未确认关闭的 managed writer，并且其后没有既有规则定义的失效事件，才能作为最终 workspace 验证及同参验证抑制依据。

这里有两个独立问题：

取得时是否可靠。 只读验证不能阻止另一个 same-UID 进程修改 workspace。验证时仍有 writer，结果可以作为当时的诊断观察，但不能成为最终内容的可复用证明。

取得后是否过期。 继续保留现有写入、进程执行、非可信 sandbox、非只读 UNKNOWN 和 compaction 的失效规则。附件已有这些判断，不需要重新设计。
CODE_CONTEXT

实现位置与边界

在 agent/runtime/evidence.py 中增加或提取一个小型纯判断，输入已有 facts 和验证所在位置；复用 active_task_resources() 对验证之前的事实前缀进行资源判断。不能用“当前最后已经没有资源”替代“当时没有资源”。

接入现有 _process_tool_receipt()，以及 _native_sandbox_tool_receipt() 中对应的验证接受位置。后者正文未附，实施前只需补读该函数，不需要全仓库。

agent/runtime/loop.py::_successful_product_request_inventory() 使用同一资格规则，不增加持久化字段、资源 epoch 或第二份运行态缓存。现有资源推导本身就是 durable facts 的解释器，已经供完成门和 compaction 使用。
CODE_CONTEXT
 
CODE_CONTEXT

必须避免一个很容易引入的二次缺陷：

不能简单把“有 writer”并入 trusted_sandbox=False。目前 trusted_sandbox=False 的成功请求会进入 ordinary，而参数抑制查询使用 ordinary ∪ native_validation。这样只是把验证从一个抑制集合搬到另一个，仍然无法重验。应区分：

是否是严格可信只读 sandbox 结果；
这条只读结果是否具备最终验证的复用资格。

writer 存活期间的只读验证，既不进入 native_validation，也不回落到 ordinary。 其他普通工具的成功抑制语义不变。
CODE_CONTEXT
 
CODE_CONTEXT

为什么不推荐“把 stop 也加进集合”

这能修复部分顺序，但会让已经清理后的幂等 stop 无端作废新验证。附件中 stop 明确支持从已有 cleanup receipt 返回同一个 cleanup=confirmed，不能把它等同于新的写入阶段。
CODE_CONTEXT

推荐方案不要求 stop_invalidates 必须为 true。验收应钉住旧验证不可用、同参重验可执行、资源门正确，而不是钉住某个内部布尔值。

A1 精确验收矩阵

以下“验证”特指现有最终 workspace 验证，不扩展到所有浏览器观察或普通工具结果。

ID	场景	必须观察到的结果
A1-01，核心 Red	start(R1) → A → fixture 实际写入 → stop(R1, confirmed)	资源集合为空；A 不能证明最终内容；同参 A 不受成功抑制。
A1-02	上一场景后显式执行同参 A2	新 call ID、新 receipt；A2 可成为最终证据；证据来源不得仍指向 A。
A1-03	start → A → stop → A2 → 重复 stop(同一 ref)	幂等 stop 不重新作废 A2，不增加无意义重验。
A1-04	已有 A，start 被明确拒绝或 KnownNotExecuted	不新增资源，不作废 A，不伪造执行事实。
A1-05	writer 已存活，stop 拒绝、已执行失败或清理未确认	资源门不关闭；不能拿存活期 A 或随后取得的 B 声称最终内容稳定。
A1-06	非只读 UNKNOWN；另设可信只读 UNKNOWN 对照	前者继续保守失效；后者不无端破坏无 writer 的合法只读验证组合。
A1-07	R1、R2 同时存活，先停 R1，再验证 B，最后停 R2	停一个不能代表全部关闭；B 仍不具备最终复用资格；全部关闭后的 C 可以。
A1-08	清理后 A2，再次启动 R3	A2 失效；新资源生命周期不能继承上一次关闭后的信任。
A1-09	真实 checkpoint 保存、退出、新进程重开	同一 durable facts 的判断一致；不能因 owner 内存为空就认为资源已清理。已有可信 cleanup receipt 经现有生产路径形成关闭事实后，才解除资源门。
A1-10	writer 存活期间 compaction；另设关闭后 compaction 对照	存活资源的 owner fact 不得丢失；summary 之前的验证继续按既有规则失效；summary 之后、全部 writer 关闭后的新验证可恢复资格。
A1-11	无 writer，可信只读 A、B 连续成功	A、B 可以同时成立；明确拒绝的写入不破坏两者。
A1-12	start 已执行但失败，尤其在注册 resource_ref 前清理失败	不能因没有 ready receipt 就推导安全关闭；沿用现有 UNKNOWN／执行意图／清理不确定分支，不允许完成。

A1-01 必须用本次临时 workspace 和实际 ToolRuntime 结果完成至少一次真实 server 旅程。用事件或屏障确定 READY → 验证结束 → 写入完成 → stop 确认 → 重验，所有相关 TOOL_CALLS 和 TOOL_RESULT 都进入事实链，参数取实际调用值。

A1-12 是一个必须核验、尚不能定罪的分支：active_task_resources() 只登记成功 ready 的 start；而 managed start 在 ready 前就可能需要清理。是否已有 UNKNOWN 路径承担这段责任，要补读 KernelToolRuntime.invoke() 的异常分类，不能从当前摘录断言已存在资源泄漏。
CODE_CONTEXT
 
CODE_CONTEXT

B2. A2：新目录、完整预检、不覆盖发布；失败不做递归回滚

推荐把输出布局收窄为：

纯文本
仓库之外、本次拥有的已有父目录/
  candidate/       # 调用前必须不存在
  manifest.json    # 调用前必须不存在，与 candidate 同级

这是有意缩小脚本接口：不再接受已有目录，即使为空；不再允许把输出嵌进源仓库；manifest 不放进候选树，也不能指定成任意源路径。对一个取证导出脚本，这比支持任意嵌套位置再补复杂防护更合适。

安全合同
阶段	必须做	明确不做
预检目标	用不跟随叶子软链接的检查确认 out、manifest 均不存在；已有目录、文件、软链接、悬空软链接都拒绝。解析已有父目录后，确认输出与源仓库无包含关系。	不先 resolve() 丢失叶子链接身份后再删除；不自动创建不明父路径。
预检源清单	在任何目标写入前冻结清单；每项必须是审核范围内的普通文件，路径不能越界；拒绝源路径中的软链接；构建残留、私人目录不进入读取清单。	不跟随源链接读取仓库外文件；不因为某文件被 tracked 就自动视为可外送。
复制	排他创建新 out；目标文件排他创建；复制后核对预检内容摘要与目标摘要。发现源内容变化或目标冲突即失败。	不覆盖现有目标；不遇错后继续产出“部分成功”的正式 manifest。
发布 manifest	所有文件成功后，先写本次独占的临时 manifest，再以不覆盖已有名称的方式发布。当前 POSIX 环境可采用同目录临时文件加 os.link()；冲突即失败。	不用会覆盖目的文件的 os.replace() 或普通 Unix rename 充当“排他发布”。
局部失败	非零退出，指出失败阶段和本次新建目录；没有有效正式 manifest 就不是完整候选。允许保留部分 candidate，下一次使用新路径。	不对 out 做递归回滚；不删除调用前已有文件；不自动重试或猜测哪个旧目录可以清理。

lstat 不跟随软链接；POSIX link() 提供原子新增目录项，目标已存在或是软链接时失败。这里使用的是窄范围的标准文件操作，不需要本地攻击者监控框架。系统级路径别名应在父目录规范化时处理，不能粗暴禁止绝对路径上所有软链接。
Python documentation
+1

安全判断使用显式异常和非零退出，不使用可能被优化掉的 assert。

A2 必须先失败的回归
ID	合成输入	断言
A2-01，核心 Red	已有 out，内部有 sentinel	拒绝；sentinel、目录内容完全不变。
A2-02	out 指向合成仓库、祖先、源文件、仓库内新子目录	写入前拒绝；源树无变化。所有危险路径只在单个测试独占的临时树中构造。
A2-03	manifest 为已有文件、源文件、out 本身或候选内路径	拒绝；不创建 out，不覆盖 manifest。
A2-04	out/manifest 叶子链接、悬空链接、父路径链接绕回源树	拒绝或规范化后发现边界冲突；不沿链接写入。
A2-05	清单最后一项缺失、越界、非普通文件、源链接	必须在复制第一项前失败。
A2-06	第 N 次复制失败；manifest 发布冲突	原有数据不变；无正式成功声明；只留下本次部分输出。
A2-07	正常新目录导出	文件集合、逐文件字节摘要、最终 manifest 一致；重复调用同一路径应拒绝。

测试可以在临时源树中替换 Git 清单查询结果，不需要 git init/commit，也不能在真实仓库上触发旧危险分支。

另一个与 E1 直接相关的必修点：新 manifest 必须包含本包新增测试和实际变更文件。 当前清单和“本轮”标签来自固定历史集合，不能据此声称覆盖新一轮；也不能把导出时相对 HEAD 的修改自动称为“会话开始前的用户工作”。新增文件、删除项和相对 cbfa1e7 的变化应显式核对；历史附件原字节不改。
CODE_CONTEXT
 
CODE_CONTEXT

B3. A3：先区分“清组未确认”和“管道未收束”，再定位根因
当前源码能确定什么

_run() 的 timeout 分支把以下两种错误统一打印为 cleanup unconfirmed、返回 125：

terminate_group() 抛 ProcessCleanupError；
它已返回，但后续 proc.communicate(timeout=1.0) 再次超时。

因此，125 不是“还有可执行进程存活”的直接证据，也不是“共享 group 算法错误”的直接证据。
CODE_CONTEXT

另一个具体差异是：共享 primitive 默认 post-KILL 确认预算为 6 秒，但这个调用方明确传了 2 秒。这个差异值得测量，不构成直接把 2 改成 6 的理由。
CODE_CONTEXT
 
CODE_CONTEXT

最小诊断补丁

首先只改 scripts/run_015_e3.py::_run() 的失败诊断，保留返回值和判断语义。至少区分：

纯文本
identity_unverified
group_cleanup_unconfirmed
post_cleanup_output_drain_timeout

保留异常类型、已有异常信息、阶段耗时。对本次合成 fixture，再记录受控 PID、已验证 PGID、直接子进程返回状态、TERM/KILL 时点、最后一次 liveness 结果或 errno，以及管道 EOF 是否到达。无需持久化新产品状态，也不要把整份环境变量或系统所有进程命令行写进报告。

Python 的 communicate() 同时处理管道读取与子进程等待；POSIX 的 signal-0 存在性探测不能等同于“仍能执行”，waitpid() 也不能替原父进程收取任意孙进程状态。这些接口语义说明为什么要拆证据，但不能替代本机的失败轨迹。
Python documentation
+2

诊断预算

本轮最多 8 次真实 fixture 诊断运行，累计诊断预算不超过 10 分钟；单次运行及观察设置明确上限，不超过 60 秒。 纯 Mock 的判定单测不计作真实进程重跑。

分配	目的	必须带来的新证据
2 次	原失败节点：独立环境一次；有依据的相关测试顺序后一次	明确 125 来自哪个阶段；记录 READY、组存在性、leader 回收、EOF 时间关系。第二次不是“再碰一次运气”。
2 次	屏障对照：明确完成后代启动；比较保留父进程收尸与原有 orphan 路径	区分启动时间假设、父子回收责任、真实组清理问题。对照不能替换原验收要求。
各 1 次	精确的 posix-supervisor、managed-web 相关失败节点	检查是否同阶段、同调用参数、同观察现象。只有文件名而无节点名时先补公开失败摘要，不猜共同根因。
最多 2 次	仅用于已经形成的假设的单变量验证	例如只替换一次观察序列，或验证一个已定位的退出竞争。没有新假设就不用这两次。

每次失败后，先完成本次拥有资源的有限清理再进行下一次。预算耗尽时保留 BLOCKED_A3_UNLOCATED，不继续压力循环，不把多次通过率写成修复证明。

归因裁决
观察结果	可以得出的结论	最小处理
组已确认消失，但后续 communicate 超时	清组与输出收束不是同一失败	修调用方对应管道/收束问题；保留非成功结果，不能仅为通过测试改成 124。
leader 已回收，剩余明确为 zombie；稍后才消失	有回收或观察收敛问题，不等同于仍可执行	核对实际父子责任和预算。不能仅凭 Z 状态把现有 group gone 合同放宽成 confirmed。
fixture 尚未完成启动或刚好已按 lifetime 退出，断言就查 PID/PGID	可能是测试的时序假设	用屏障修测试；不延长产品 lifetime，也不能删除 orphan/后代清理反例。
清理后仍有本次拥有的可执行成员，或确有错误组身份	真正资源清理/所有权问题	定位实际责任层；保持 125、禁止完成，修复后增加命中该序列的回归。
未重现且无可区分轨迹	根因仍未知	不改共享 primitive 猜修；不关闭 A3。

是否改 agent/process/group.py，必须由上述证据决定。 只有共享 primitive 对正确输入作出了错误判断，或有可重现的共享算法问题，才修改它；随后 focused 覆盖实际引用它的现有消费者，包括必要的旧 subagent/supervisor 测试。这是共享修复回归，不是新增相关能力。

还有一个应立即修正的测试卫生问题：原失败测试第一条断言之后没有 finally 清理保护；它一旦失败，后面的 PID 检查也不会执行。应为本次 fixture 增加精确 owner 的清理保障，防止失败污染后续诊断。只对本次记录并确认归属的进程/组操作，不使用 pkill，不重新查询一个失去身份绑定的 PID 后就杀其当前所属组。
CODE_CONTEXT

B4. A4：让显式 disabled 优先，不改 enabled 的协议保护

推荐只调整 OpenAICompatibleProvider.generate() 中的期望判断：

纯文本
reasoning_expected =
    显式 enabled
    或（thinking_mode 为 None 且命中既有官方 Flash 身份）

也就是：family 推断只用于未指定模式，不用于覆盖 disabled。

本轮不改 normalize_openai_response() 的普遍严格性，不删除 continuation 身份校验，不增加供应商、模型别名、容量或新的传输路径。

None 下官方 Flash 的默认 reasoning 行为，在这里是保留附件中的既有兼容约定，不是本次重新核实了当前 API。附件的现有测试正是这个约定。
CODE_CONTEXT

A4 最小测试矩阵

这里的 None 是配置未指定，不是字符串 "none"。

ID	配置与输入	期望
A4-01，核心 Red	官方 Flash，disabled，初始用户消息，JSON 纯文本	请求显式发送 disabled；不请求 SSE；响应成功，continuation 为 None，恰好一次 MockTransport 调用。
A4-02，工具续接 Red	disabled，JSON 工具调用 → 配对工具结果 → JSON 文本	两轮可连续完成；不要求 reasoning；tool-call/result 配对保护仍在。
A4-03	官方 Flash，None，JSON 含非空 reasoning	保留现有行为：不发送 thinking/stream，建立并回放同身份 continuation。
A4-04	官方 Flash，None，JSON 缺 reasoning	按现有本地合同拒绝，不静默改变默认模式约定。此项不能冒充当前上游行为证明。
A4-05	enabled，合法 SSE 文本或工具响应	reasoning、结束标记、usage、工具拼接保护继续通过；完整收束后才返回一个 ModelResponse。
A4-06	enabled 返回 JSON；None/disabled 返回 SSE	沿既有传输合同拒绝，不增加自动格式回退或自动重发。
A4-07	enabled/None，历史 assistant 缺 continuation，或 continuation 身份不匹配	HTTP 之前失败，MockTransport 计数为 0。分别覆盖模型身份和目的端点身份不匹配。
A4-08	disabled，历史仍携带 opaque continuation	保持现有 mismatch 拒绝，不静默删除历史载荷。明确“关闭模式修复”不等于支持进行中的 reasoning 会话无损切换模式。
A4-09	非官方精确身份或不同模型	None/disabled 不获得 Flash reasoning 特权；enabled 按现有配置限制拒绝。
A4-10	enabled SSE 缺 reasoning、截断、坏工具片段；disabled JSON 意外携带 reasoning 字段	继续 fail closed，无工具执行、无自动重试；不为了 disabled 正例放宽未知字段保护。

A4-08 的边界来自现有归一化代码：不要求 reasoning 或没有对应身份时，带 continuation 的历史也会报 mismatch。这个限制要写进结果，不应在本包顺便实现历史转换。
CODE_CONTEXT

C. E1、E2：补“最终安装物”和“实际执行次数”，不重造评测平台
C1. E1：最终 wheel 的增量 installed 证明

已经完成的独立导出、113 模块来源验证和原生安装回归，应保留为历史正证据。本轮需要更新的是它们与新字节的绑定，不是重新论证安装验证方法。

最终产品、测试和验证脚本冻结后，做以下四项：

证据项	本轮要求	不要求
新候选身份	用修复后的 A2 导出当前公开源码；清单覆盖新文件、删除项；记录基线、逐文件摘要、manifest 摘要。	不复用旧 653 文件或旧 23 文件“无漂移”的结论。
新 wheel / target	从干净导出构建 non-editable wheel，记录真实 wheel SHA-256，安装到新 target。	不从带 build 残留的目录混入旧模块，不复用旧 wheel。
增量行为	A1 的关键正反例、A4 disabled/continuity、E2 新进程恢复；A3 若改产品共享层，则覆盖其 installed 实际消费者。	不再跑一次 3700 多项 installed 全库。
入口与来源	在最终产物上验证变更模块、实际加载闭包、原生入口；复用现有 packaging 测试。检查来源污染负对照仍可失败。	不重新搭一套来源审计器，也不扩全平台/extras 安装矩阵。
不能漏掉子进程的来源

当前有些 managed-web 测试直接通过测试文件位置拼接源码树中的 agent/process/managed_web_child.py。即使父进程安装了 import guard，这种直接执行脚本也不能自动算作 installed 子进程验证。
CODE_CONTEXT

相反，生产 ManagedWebProcessOwner.start() 从自身 __file__ 定位 child，这条路径适合做 installed 正例。必须记录实际 spawn 的脚本路径及摘要，确认它来自最终安装物。不能只看父进程的模块来源。
CODE_CONTEXT

现有 _019_installed_pytest.py 可以复用 guard 和报告，但其 CLI 正文固定向 pytest 传入整个 tests 目录，没有展示 --test-node 之类的参数，不能编造参数调用。可以用 pytest 原生 PYTEST_ADDOPTS 配合冻结的 -k 表达式选择本包节点；报告必须校验实际执行节点集合，不能仅凭退出码。完成后清除选择条件，避免污染最终全量门。
CODE_CONTEXT
 
pytest文档
+1

环境也是身份的一部分。 最终完整项目门要在符合声明的依赖环境运行，不能继续拿 Textual 8.1.1 的全量结果证明 >=8.2,<9 声明环境。优先使用已授权、依赖符合声明的环境或新的本地离线环境；不是修改声明来迁就旧 venv。
AUDIT_CONTEXT

C2. E2：用可数副作用证明恢复，不用 call ID 代替执行次数
最小 fixture

一个受控假 provider，驱动真实 AgentRuntime.run_turn、真实 ContextManager、真实 ToolRuntime 和磁盘 checkpoint。

使用一个仅测试注册的受治理 callable：每次真正进入 callable，就向本次临时文件追加一条可数记录并 flush/fsync。它不按参数或操作 ID 去重。追加本身就是可观察副作用，避免“重复覆盖相同文件内容，看起来没有变化”的假阴性。

外部验证器读取三个相互核对的来源：

物理效果计数。 实际追加了几条记录。

内核执行账本。 action、run、intent、call、idempotency 身份和执行前后 checkpoint。

恢复过程。 前后 PID、进程启动身份、同一 state root、实际 PAUSE/退出/恢复动作，以及恢复后提供给 provider 的 ContextPack。

测试中的“逻辑操作标签”只属于 fixture 和外部判定器，不进入新的产品去重机制。

最小场景矩阵
ID	场景	必须证明
E2-01	完成效果 X，并保存 RESULT；在下一操作 Y 的安全边界 PAUSE；退出后新进程恢复	X 计数保持 1；Y 可以正常完成，计数从 0 到 1；不是把所有工具都堵住来实现“零重放”。恢复无需重新输入任务全文。
E2-02	同一场景中，受控 provider 用新 call ID再次提出已完成的 X	在没有新的用户重复执行意图下，不能自动再次进入 callable。是否抑制、拒绝或进入既有明确授权边界，按当前内核合同核对；最终物理计数仍为 1。
E2-03	已保存 EXECUTING，效果已追加，但 RESULT 未落盘时终止本次拥有的进程	新进程进入既有 UNKNOWN 恢复；效果计数保持 1；不能推测失败后自动重做。可用同一夹具增加“尚未产生效果”的参数对照，计数应保持 0。
E2-04	用户明确在新的任务/操作上下文再次要求相同调用，经过新的合法授权	参数可完全相同；新增一次效果应允许，计数变成 2。证明没有引入永久参数去重。
E2-05	独立负对照：所有 call ID 不同，但同一逻辑操作实际追加两次	外部判定必须失败。旧“ID 全唯一”的判定会通过，新判定必须拒绝。

E2-02 有一个重要限制：调用内容相同不是违规本身。 违规依据是“这是恢复过程中无新重复意图的同一已完成操作”，因此必须绑定本次合成任务的操作顺序、原结果和授权边界，不能只比较参数 hash。

E2-03 用测试 callable 内的屏障控制崩溃点：先看到真实 EXECUTING checkpoint，再确认物理效果持久化，然后在 callable 返回前终止该测试进程。不手工编辑 checkpoint，不新增生产 failpoint。

这组测试证明的是：

当前安装候选、受控 provider、指定本地恢复窗口下，内核没有自动重放已完成或结果未知的副作用。

它不能追认旧真实旅程的“14 effects 零重放”，也不能证明任意外部服务的 exactly-once。原真实旅程仍保留“过程证明不足”的结论。原验收文档本来也要求实际过程身份，而不是只看最终文件正确。
CODE_CONTEXT

D. 给普通 coding agent 的执行资料包
D1. 包内只保留三个主要载体
载体	内容
EXECUTION_PACK.md	本次冻结裁决、A1—A4/E1—E2 矩阵、修改范围、顺序、命令类别、授权和停止条件。
RESULTS.md	唯一进度与结果记录。每项记录 Red、原因、改动、Green、版本身份、剩余限制；不再维护多份互相矛盾的完成表。
evidence/	本次公开或合成材料的原始输出、节点清单、manifest、环境/产物身份、进程诊断、恢复计数与账本。历史证据只引用，不覆盖。

本次 Oracle 的资料包状态应是待执行，不能预填产品修复 PASS。

D2. 基线与最小补读

开工时核对：

Bash
git rev-parse HEAD
git status --porcelain=v1
git diff --check

预期 HEAD：

纯文本
cbfa1e78c80a521fea2ebcf6169cfb4536ad1f5d

同时核对拟修改文件与附件对应的 Source SHA-256。基线有漂移则停止并报告具体文件，不自动 reset、checkout 或覆盖现有改动。

以下是实施前的最小必要补读，不是索要全仓库：

用途	补读范围
A1	_native_sandbox_tool_receipt() 正文；完成门调用 active_task_resources() 的位置；compaction 使用 owner_fact_ids 的位置。
A1/A3	KernelToolRuntime.invoke() 对已执行异常、UNKNOWN 的分类；managed-web prepare_resource() 及重开 cleanup receipt 的身份绑定。
A3	managed_web_child.py 的监督/退出/回收段；posix_supervisor 的实际清理调用段及对应 fixture 参数；两个历史报告的精确失败节点和公开 traceback。
E2	run_turn 的执行前保存、结果保存、恢复、PAUSE 和磁盘重开入口；已有相关测试夹具。
E1/完整门	pyproject 的依赖、pytest/ruff 配置及必要的 conftest；确认声明环境、默认筛选和离线测试边界。

看不到这些内容时，只把相应结论标成待核验，不指定不存在的异常类型、恢复 API 或命令参数。

D3. 依赖顺序与允许修改范围
阶段	执行动作	范围
S0	基线核对、补读、冻结节点和权限	只读公开源码与配置。
S1	A2 Red → 修复 → focused Green	scripts/build_candidate_manifest.py、专属导出回归。修好前不使用其危险导出路径。
S2	A1 Red → 共享资格判断 → 生命周期矩阵	agent/runtime/evidence.py、agent/runtime/loop.py、对应 kernel/continuity 测试；资源解释 helper 仅在必要时小改。
S3	A4 Red → 模式优先级修复 → provider focused	agent/provider/openai_http.py、对应 provider 测试。
S4	A3 阶段诊断 → 有证据的最小修复	默认先限 _run() 诊断和相关测试；共享 process 层、producer 分类仅在证据命中后改。
S5	E2 外部负对照和新进程恢复证明	测试 fixture、驱动和断言；若暴露真实恢复缺陷，只修命中的既有路径，不创建第二套恢复系统。
S6	冻结当前字节，导出新 wheel，installed focused	复用已有构建与来源 guard。新测试必须纳入导出。
S7	最终一次完整项目门，核对前后身份	不再添加功能；输出最终 RESULTS 和交付身份。

禁止修改：审批模型、UNKNOWN 自动重试规则、执行前后 checkpoint 合同、资源 owner 边界、完成证据门、provider/model/容量、Memory/MCP/SubAgent/sandbox/调度能力、默认后台行为和权限配置。

禁止为减少提示而跳过审批；禁止按文件行数拆模块；禁止重写历史 SHA 绑定文档；禁止 commit、push、发布、登录项或个人浏览器操作。

D4. 验证命令分层

所有命令中的 $PY 指向已核对依赖声明的测试解释器，不是默认假设当前 .venv 合格。

增量 focused

以下是已知文件可直接使用的选择：

Bash
"$PY" -m pytest -q -rx tests/kernel/test_validation_request_freshness.py
"$PY" -m pytest -q -rx tests/provider/test_deepseek_flash.py
"$PY" -m pytest -q -rx \
  tests/reference/test_015_e3_harness.py::test_015_offline_gate_timeout_cleans_owned_process_group

新 A2、E2 测试在落包时固定路径和 node IDs；它们是计划新增，不能在执行记录里冒充基线已有文件。A3 相关测试按冻结节点运行，不使用自动 rerun 插件、并行压力或随机重排。

本地导出、构建、安装

A2 通过后，在仓库外创建本次拥有的父目录；candidate 叶子保持不存在：

Bash
"$PY" scripts/build_candidate_manifest.py \
  --out "$RUN_ROOT/candidate" \
  --manifest "$RUN_ROOT/manifest.json"

"$PY" -m pip wheel \
  --no-index --no-deps --no-build-isolation \
  --wheel-dir "$RUN_ROOT/wheels" \
  "$RUN_ROOT/candidate"

从实际输出解析唯一 wheel，记录摘要，再安装到新 target。依赖只使用当前允许的本地来源；缺依赖则报告阻塞，不自行联网更换环境。

PIP_NO_INDEX=1 只约束 pip，不是禁止所有网络的证明。provider 验证使用 MockTransport；新进程测试使用受控环境和 fake provider；loopback 仅用于本次 fixture。

不要误运行总 E3 入口

本轮不要运行 scripts/run_015_e3.py 的总入口来“顺便验证”。它的设计是完整离线门之后继续真实 provider 旅程，而且离线门包含额外 materialized content 测试。那会重复全量并可能越过本次授权。只运行本包选定的结构/fixture 测试。
CODE_CONTEXT
 
CODE_CONTEXT

E. 全量策略、停止条件与交付格式
E1. 最终只跑一次完整项目门

每个增量只做 focused；installed focused 也放在完整门之前，以便其发现问题时不浪费一次完整门。

最终候选冻结后，在合格环境、完整公开项目范围执行：

Bash
"$PY" -m ruff check .
git diff --check cbfa1e78c80a521fea2ebcf6169cfb4536ad1f5d

PYTEST_ADDOPTS='' \
PYTHONDONTWRITEBYTECODE=1 \
PIP_NO_INDEX=1 \
"$PY" -m pytest tests -q -rx -ra

执行前检查项目配置没有暗含本轮不允许的 -k、--ignore=tests/acceptance 等排除。新增未跟踪文件另做范围和空白检查，不能以 Git diff 没列出它们就认为已检查。

每条命令记录真实退出码、环境、起止时间和原始输出；不能让 tee 的退出码掩盖 pytest 失败。完整 pytest 设有界总等待预算，建议沿用已有 1800 秒量级；超时记录失败并执行本次 owner 的有限清理，不扩大为无限等待。

最终任何失败都阻塞本候选。 单项复测绿不覆盖失败的全量记录；不得临时 skip/xfail A3，也不能把原来的 125 接受成 124。

“最终一次”不是说改了代码还沿用旧门：若完整门之后发生产品、测试或验证逻辑的实质变化，旧门对新候选作废。 完成该修复的 focused 验证后，才允许对新的冻结候选再做一次最终完整门；不是对同一未知失败无限重跑。

E2. 明确停止条件
条件	必须停止的部分
HEAD、源 SHA 或工作树边界不符	停止产品修改，报告漂移，不自动恢复。
A2 无法证明不覆盖源与已有输出	停止候选导出、wheel 和 installed 取证。
A1 某路径在清理未确认时仍能完成	保持阻塞；不能用全局关闭验证功能掩盖。
A3 达到诊断预算仍未归因	标 BLOCKED_A3_UNLOCATED；不能以最后一次绿色宣布收口。
UNKNOWN 被自动再次执行，或 E2 计数不符	阻塞恢复可靠性结论，保留实际账本。
新增测试未进入最终导出、来源落回工作树、子进程来源不明	阻塞 installed 证据。
完整门失败、候选验证后字节变化	阻塞最终通过。
缺当前凭据来源、外发数据、预算或真实旅程授权	只停止真实 API 部分；标记未执行，不编造 PASS。

若前置阻塞已经明确，没有必要再跑全量“碰运气”。可以交付已完成修复和阻塞记录，但不能交付“可靠性收口完成”的结论。

E3. 最终交付必须回答这些问题

最终 RESULTS.md 至少包含：

字段	要求
base_head	精确基线，不能只写 main。
candidate_identity	当前变更/新增/删除清单、公开源文件摘要、manifest SHA、实际 wheel SHA。没有提交时，HEAD 不能代表候选全部身份。
environment	OS、Python、相关依赖实际版本、声明符合性。
A1…A4 / E1 / E2	分项 PASS / FAIL / BLOCKED / NOT_VERIFIED，附对应节点及证据路径。
red_green	产品 Red 与证据负对照分别记录；不把后者包装成产品缺陷。
installed	真实 origin、子进程脚本身份、执行节点、来源污染负对照。
process_diagnostics	所有失败尝试、阶段、耗时和清理结果；不能只保留最后绿色。
replay_evidence	物理计数、内核账本、前后进程身份和显式合法重复对照。
full_gate	ruff、diff、完整 pytest 原始退出码及全部失败/skip 原因。
authorization	本轮真实 API/私人数据/Git 写入等是否执行；缺权限的项目明确未执行。
product_status	继续为 implemented-candidate；区分本地离线收口与真实供应商/平台验证范围。
F. 最小产品判断与延期清单
本包哪些地方应该做重，哪些应该做轻

应当做重的是证据链的准确性，不是功能数量。 A1 必须同时验证最终证据、同参抑制、资源关闭三个结果；A3 必须分清失败阶段；E2 必须数真实 callable 进入次数。少任意一项，都可能产生“看起来已完成”的错误结论。

应当做轻的是验证架构和覆盖规模。 一个 A1 真实 server 主旅程配合参数化事实测试，一个 E2 可数效果 fixture，现有 installed guard 加增量节点，足够支撑本包。不需要复制 14 次效果、不需要再跑一次 installed 全库、不需要长时间压力平台，也不需要增加资源状态机。

只需诚实说明的是覆盖边界。 未授权的真实 API、其他供应商、其他平台、任意网站、进行中的思考模式切换，都不应通过文案变成已支持。

产品交互只补故障的下一步，不重做授权体验

旧正例的 12 次审批和 18 次外发确认，证明有提示负担，却不能证明其中哪些不必要；本轮不据此删审批。
AUDIT_CONTEXT

允许的交互收尾限于已有错误/阻塞出口：

情况	应让用户知道
A1	当前还有哪个本任务资源未确认关闭；先关闭，再执行哪条最终验证。幂等 stop 不应平白要求再次验证。
A2	哪个路径冲突；原数据未覆盖；改用新的输出目录和 manifest 名称。
A3	失败在清组还是输出收束；任务未自动重放；是否还有未确认清理的本任务资源。
A4	disabled 下正常响应应直接工作；历史 continuation 不兼容属于另一边界，不伪装为已支持模式迁移。
E2	恢复的是已保存任务；遇到 UNKNOWN 明确需要用户决策，不能自动重做。

没有相关 UI 源码就不能宣判 UI 已缺失；执行者只需核对现有呈现出口。已有足够信息就不改，没有下一步才做局部错误文案补齐，不新增大 UI。

必须纳入、但不另开项目的遗漏

有三项必须进入本包：

未成功 ready 的 start，其清理不确定由谁承担。 这是 A1/A3 共同的生命周期边界；目前只确认需要核验，不能先报泄漏。

子进程是否真正来自新安装物。 这是 E1/A3 的共同证据边界，父进程 import guard 不足以包办。

最终环境和清单是否对应真正的新候选。 Textual 声明不符、固定历史清单漏新测试，都可能让“全量通过”与实际交付脱节。

除此之外，审批合并、外发授权体验重做、自动清理历史资料、通用副作用幂等平台、持续进程监控、多供应商兼容改造和平台扩展全部延期。

完成标准只有一个：这六项的本轮本地合同闭合，最终字节有对应证据，剩余真实验证边界说清楚。不是把 Agent 平台修到“最好”。

YAML
codex_execution_advice:
  implementation_plan:
    - "S0：核对 cbfa1e78c80a521fea2ebcf6169cfb4536ad1f5d、工作树和附件源 SHA；补读本包列出的最小缺失符号，冻结验收节点与权限。"
    - "S1：先修 A2；通过合成目录 Red 后，实现新输出目录、源与 manifest 完整预检、排他写入及不覆盖发布；失败不递归回滚。"
    - "S2：修 A1；复用 durable resource facts，在验证取得位置判定是否存在未确认关闭的 writer；证据与参数抑制共用资格规则，失格只读验证不得回落 ordinary。"
    - "S3：修 A4；显式 disabled 优先于 Flash family 推断，保留 None 既有约定、enabled SSE 和 continuation 身份保护。"
    - "S4：按阶段拆分 A3 的 125 诊断；在最多 8 次真实 fixture、累计 10 分钟的边界内定位；只有证据命中才修改共享 process 层。"
    - "S5：补 E2；使用真实内核和磁盘 checkpoint、受控假 provider、可数副作用及独立账本，验证新进程恢复、UNKNOWN 不重放和合法同参重复。"
    - "S6：冻结最终文件，导出新候选并构建新 non-editable wheel；执行增量 installed 验证，核对模块和实际子进程文件身份。"
    - "S7：执行最终完整 ruff、diff、pytest 门；核对验证前后文件身份，输出单一 RESULTS、原始证据及明确剩余边界。"
  non_goals:
    - "不增加第二套 model/tool loop、资源状态系统、守护进程、service locator、动态插件、文件监控或大型评测平台。"
    - "不新增 Memory、MCP、SubAgent、sandbox、调度或平台能力，不按文件行数拆分代码。"
    - "不删除审批、UNKNOWN 恢复约束、执行前后 checkpoint、资源清理确认或完成证据门。"
    - "不以参数相同建立永久去重，不将受控 provider 证明冒充真实 API 旅程证明。"
    - "不读取旧私人会话或未授权凭据，不调用真实 API，不更换模型、供应商或容量，不修改权限。"
    - "不 commit、push、发布或改写历史 SHA 绑定证据；Oracle 建议不构成这些操作的授权。"
  optional_subagents: []
  verification:
    - "A1、A2、A4 必须先有命中当前缺陷的 Red；A3 修复须有定位证据及针对性回归；E1、E2 必须有能够拒绝错误证明的独立负对照。"
    - "A1 覆盖 start→验证→实际写入→stop、同参重验、幂等 stop、拒绝、失败与 UNKNOWN、双资源、重开、compaction 和无 writer 的只读 A/B 组合。"
    - "A2 的所有危险路径仅在独占临时树中测试；验证拒绝发生在目标写入前，已有数据不变，局部失败没有有效成功 manifest。"
    - "A3 保留每次诊断的阶段、身份、耗时和清理结果；不吞 125、不使用 pkill、不依靠重跑绿色关闭未知根因。"
    - "A4 使用 MockTransport 覆盖 None、enabled、disabled、JSON/SSE、工具续接及身份不匹配；验证调用次数和失败发生在 HTTP 前还是响应后。"
    - "E1 绑定最终源文件、manifest、wheel、installed 模块与子进程文件身份；只补增量 installed 行为，不重跑 installed 全库。"
    - "E2 同时核对物理效果计数、内核执行账本和新进程恢复；新 call ID 重做同一操作的负对照必须失败，明确新任务的合法同参重复必须允许。"
    - "每个增量只运行 focused；最终在符合声明的环境运行一次完整项目门，清除筛选条件且不排除 acceptance；任何失败如实阻塞。"
    - "最终代码、测试或验证逻辑发生实质变化后，旧完整门对新候选失效；不得通过无限诊断重试、skip 或放宽断言维持 PASS。"
    - "缺少当前凭据来源、外发数据和预算授权时，真实 API 部分标记未执行；最终产品状态继续限定为 implemented-candidate。"
