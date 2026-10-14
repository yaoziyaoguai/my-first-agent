# Oracle 原始答复（外部建议，非执行授权）

Session: `mfa-resume-audit-20261014-64be7c`。2026-10-14，已捕获完整答复；输入是修复前半成品。以下保留提取文本，孤立文件名是网页附件引用标签。实际采纳与本地后续证据见 AUDIT.md；不能把Oracle未见到的后续全量/清理结果倒算成它的结论。

A. 执行状态

**结论：当前候选可以接续，但不能结案。R1、R3 的已有成果应保留；R2 应改为 IN_PROGRESS，而不是 NOT_STARTED；R4 仍待实现。当前 Codex 的任务仍是核验、整理接续包和保存交接信息，不是自动开始产品修复。**本次审查未运行测试；下面涉及通过数量的内容，均来自附件中的执行记录。
CONSULTATION

当前状态应这样记录
项目	状态	已有证据与尚缺部分
R1：UNKNOWN 与安全停机	主体已实现，有局部验证证据	已增加 recovery 保存失败后的 UNKNOWN 保留路径、complete_run/end_run 窄守卫，以及在安全转换中闭合未开始 suffix 的实现；新增连续保存失败、暂停重开、未知效果恢复等回归。剩余是历史 healer 的一致性检查、部分组合验收，不能据此重新启动恢复系统设计。
R3：明确执行要求识别	主体已实现，部分边界待证明	中文连接词识别、冻结输入的双向 model flag 测试、工具输出不能铸造义务、correction 撤回和不撤回的对照已有改动。但“已 admitted 的义务如何退役”和相关权限失效，现有附件不足以完整证明。
R2：业务完成可信度	部分完成，必须标 IN_PROGRESS	已增加 RequirementCoverage、完成门、provider/schema/checkpoint/payload 适配，并删除 readback 自动完成路径。现有新增测试主要证明简单文件任务的收尾行为，尚不能证明原 D04 的两条遗漏路径已经闭合。
R4：默认 CLI 范围授权入口	未做	当前无参数命令仍会因缺少 exact request ID 被拒绝；补丁中没有这部分 CLI 产品修复。
C1 / C2	C1 未证明；C2 部分完成	C1 所在文件的改动是修正旧夹具形状，不是新增“writer 关闭→同参重验→下一轮 wire”组合证明。C2 已有真实 ContextManager 和两种 wire 投影测试，但测试输入没有成功 prefix，也没有实际检查 continuation 不变。
I1 / G1 / E1	I1 未证明；G1 当前不通过；E1 未执行	附件没有本候选新 wheel 的安装证据；ruff 已报告 7 项失败；真实 API 当前没有授权。

上述判断分别依据 UNKNOWN 与安全收尾补丁、R3 admission 测试、R2 合同和收尾改动，以及当前 CLI 判断条件。
WORKING-TREE
 
WORKING-TREE
 
WORKING-TREE
 
WORKING-TREE
 
SOURCE-CONTEXT

两个容易误报的交付门需要单独说明：C1 当前改动只调整了只读 UNKNOWN 恢复测试的历史批次；C2 的新用例则确实走了 Runtime 的 pause 转换和真实 wire 投影，但两个调用都未执行，不能把注释中的“成功 prefix 与 continuation 保持不变”计为已验证。
WORKING-TREE
 
WORKING-TREE
 
WORKING-TREE

**377 passed 只能保留为这 8 个文件的定向重跑证据。**它不覆盖全部被修改测试，更不是新字段重开、安装态或真实业务层的完成证明；ruff 失败也不能被该数字抵消。
CONSULTATION

B. 本次接续包应纳入的六项发现
B1. P1｜确定的验收缺陷：测试绑定助手替模型补出了“已复核、全部满足”

位置：tests/kernel/fakes.py::bind_runtime_goal、completion_claim_from_trusted；关联 state.py::_require_requirement_coverage。

当前绑定分支遇到空 requirement_coverage，会从 trusted_goal 取全部来源和 mandatory criterion，自动生成：

纯文本
requirement = "the current trusted goal is fully satisfied"
status = "satisfied"

这已经不是动态 ID 绑定，而是替测试输入生成了本来缺失的完成声明。另一个新增 helper 也默认使用同样的泛化结论。
WORKING-TREE
 
WORKING-TREE

具体失败路径是：

测试原本要提交“没有逐项复核的 claim” → 测试助手补齐 coverage → Runtime 看到结构完整的 claim → 测试没有真正经过缺复核路径。

现有 Runtime 门检查的是来源集合、pending 项和 mandatory criterion 覆盖；它不会判断这句泛化描述是否真的拆解了用户要求。因此，一个错误的泛化映射可能通过结构检查，不能将其通过解释成业务复核已经发生。这不意味着 RequirementCoverage 应删除，而意味着它只能承担结构绑定职责，测试不能替它制造语义完成。
SOURCE-CONTEXT

最小 Red：

在这条动态绑定路径中输入空 coverage，断言绑定后仍为空；只允许替换明确的运行时身份占位。
从原始 service＋CLI 要求开始，经真实 admission、审批、文件写入和回读，仅完成 service，再提交空 coverage claim；断言不能终结，并能进入下一轮主 loop。
下一轮脚本响应显式识别 CLI 缺项并继续，而不是由 helper、测试预置 Goal 或测试提前填入 CLI criterion。

**最小修复：**删除隐式补齐；正例测试显式提供场景相关的 requirement、status 和映射。已有 callable 型脚本响应足够处理动态 ID，不需要新增测试框架。

**边界：**不要反过来要求 Runtime 机械识别所有“表面结构完整、实际理解错误”的自然语言声明。那是独立业务验收要暴露的问题，不是本轮另建语义裁判的理由。原合同也明确区分了这两层。
WORK-PACKAGES

B2. P1｜待证风险：来源 ID 已投影，但主 loop 获得完整权威原文尚未证明

位置：context.py::_goal_group、实际 context 选择/compaction 路径、state.py::_require_requirement_coverage。

当前 trusted_goal 新增的是 source_fact_ids；这个 pinned block 并没有同时携带对应用户和 correction 原文。**pinned 的 Goal 摘要不等于 pinned 的原始要求。**附件未提供完整的事实分组、裁剪、压缩后恢复和最终 wire 投影代码，因此现在既不能断言原文一定丢失，也不能断言它始终可见。
SOURCE-CONTEXT
 
SOURCE-CONTEXT

还有一个需要定点核对的细节：完成门的 authoritative_ids 是 created_from_fact_ids 与当前 state.facts 中 USER_MESSAGE 的交集。若某来源已经不在当前 facts 中，该代码不会仅因其缺失就报错；这是否能在合法 compaction 后发生，取决于尚未提供的保留不变量。
SOURCE-CONTEXT

**最小验证：**通过真实 ContextManager/compaction 路径制造上下文压力，在原始要求和后续 correction 中放入不同的可识别文本，捕获完成复核前真正交给 provider 的上下文，检查：

当前 Goal 的相关来源 ID 能对应到正确原文，correction 顺序没有混淆；
不是只剩模型先前的 draft、摘要或 ID 清单；
无法容纳必要原文时，如实进入既有容量失败/受阻路径，不能静默裁掉后仍完成。

**最小修复仅在 Red 后实施：**优先复用已有权威 fact 分组和保留机制；必要时让当前 Goal 的原始要求与纠正成为受保护输入。不要另建来源存储服务，也不要把所有历史对话永久固定进上下文。

B3. P2｜确定缺陷：新增字段的身份与反序列化合同没有完全同步

位置：state.py::record_completion_claim、provider/normalize.py::_decode_requirement_coverage、checkpoint.py::_completion_claim_from_dict、contracts.py::_requirement_coverage_from_payload。

需要一起收口四个小问题：

问题	实际影响与最小验证
payload_digest 未包含 coverage	两个 claim 在 goal/revision/evidence refs 相同、coverage 不同时，仍得到相同 payload digest。用两个独立起始状态副本比较，避免被 correlation 重复检查提前挡住。
provider 的 nested entry 不拒绝未知字段	schema 声明 additionalProperties=False，但 decoder 只读取已知字段，额外字段会被忽略。加入任意额外键，验证实际 normalize 路径拒绝，而不是只检查 schema。
checkpoint 使用 value.get(...) or []	false/null/0/""/{} 会被吞成空列表。应区分“旧记录缺字段”与“新字段存在但类型错误”。
持久化 ModelResponse 的 ID 数组元素检查较弱	_requirement_coverage_from_payload 检查了数组形状，却直接把元素变成 tuple；新增类型自身主要检查非空，没有与 provider/checkpoint 一样逐元素要求字符串。补非字符串元素的拒绝用例。

这些行为分别可从 digest、decoder 和新 payload parser 直接确认。
SOURCE-CONTEXT
 
SOURCE-CONTEXT
 
SOURCE-CONTEXT
 
WORKING-TREE

**分级保持 P2，不夸大为已经绕过完成门。**例如，错误值被吞成空 coverage 后，完成门仍会拒绝空 coverage；digest 遗漏也不等于模型能绕过现行 claim 校验。这些是新增字段的明确合同不一致，应修，但不是已经证明的权限突破。
SOURCE-CONTEXT

**最小修复：**新 receipt 的 digest 纳入完整 coverage；各入口对键集、数组和元素类型保持一致。旧活动记录缺字段仍可读为空并等待主 loop 补复核；不要重写历史 receipt，也不要开启通用迁移。

B4. P2｜确定的防御缺口，正常路径可达性待证：healer 只认末结果的 rejected=True

位置：state.py::_close_orphaned_tool_batches。

现在已经检查同批、连续且有序的 prefix，但“这是 Runtime 拒绝结果”的判断只有：

Python
facts[cursor].content.get("rejected") is True

没有同步核对 executed is False、is_error is True。所以，在合成或损坏状态中，把一个已执行/成功结果同时标成 rejected=True，仍可能触发 suffix 的“确定未执行”补记。
SOURCE-CONTEXT

但不能据此声称正常结果当前就能携带这个顶层标记。附件缺少普通工具结果的完整生产映射和拒绝结果生成代码。工具输出文本写着“rejected”，或 metadata 中存在同名字段，也不等于这里读取的顶层布尔值。

同时，当前 healer 会跳过由 live call IDs 拥有的批次；不能忽略这个保护，然后宣称正常 durable UNKNOWN 会直接被 healer 洗掉。
SOURCE-CONTEXT

**最小 Red：**在现有严格拒绝 prefix 正例上，分别改成 executed=True、is_error=False、缺少必要字段，期待原 facts 不变、动作冲突、不继续 provider/tool；另保留 live EXECUTING/AWAITING_RECOVERY 的不代答对照。

**最小修复：**严格拒绝事实的联合条件，加上已存在恢复状态所能证明的 exact-batch 矛盾检查。不要创造新的 UNKNOWN 标记，也不要用一个全局“有 UNKNOWN 就禁止一切”的判断破坏正常恢复。

执行者应先定点检查普通 TOOL_RESULT 生产路径、record_tool_result 和 ResolveApproval(approved=False)。只有确认正常生产链也能形成上述矛盾事实，才升级为原 R1 的 P1 可达缺陷。

B5. P2｜确定的验收缺口：R3 撤回测试没有证明已 admitted 义务正确退役

位置：state.py::_apply_correction_lower_bounds、accept_goal_delta_proposal 及相应测试。

新增过滤明确作用于 Runtime 铸造的 process/Web proposed criterion，并刻意不包含 required-governed-tool。这不是新增 Web 能力，也没有修改公开 Web 正向识别规则，但确实比“补中文连接词”多了一项共享 correction 行为变化，应在接续包中明示。可见改动没有直接铸造权限，不能判为已经放宽审批。
SOURCE-CONTEXT
 
SOURCE-CONTEXT

**不能认定 admitted 残留已经发生。**源码摘录恰好停在 admitted_criteria=tuple(，未给出后续过滤表达式；而新 completion 测试在 correction 后直接把 admitted criteria 替换成仅文件 criterion，因此它不能证明真实的旧 process admission 已被退役。
SOURCE-CONTEXT
 
WORKING-TREE

**最小验证：**复用真实 Runtime 的 process admission 路径，先形成已 admitted 的 process 义务，再在合法边界撤回。检查 proposed/admitted、旧 claim 和证据的版本绑定、后续工具调用次数以及最终文件任务可完成性。不能在断言前手工把 admitted tuple 改成期望答案。

**推荐边界：**保留目前这段窄撤回实现，不另立 Web 优化任务；把 Web 分支作为共享函数的受影响回归。定点补读函数尾部、delta 生效路径和既有授权失效路径；若已有机制正确，补证即可，不改权限系统。

B6. P2｜确定缺陷：R4 默认用户入口仍要求用户不可见的身份信息

位置：cli/app.py 的 /approve-goal-target、/approve-goal-directory 分支及默认 renderer。

当前判断 if not separator or argument != request.request_id 会直接拒绝无参数命令；renderer 的设计又是隐藏内部 request identity。这与原 R4 要求的默认交互不一致，问题在入口接线，不是底层缺少范围授权能力。
SOURCE-CONTEXT
 
SOURCE-CONTEXT

**最小 Red：**仅使用默认提示中用户能看到的信息，输入无参数短命令，期待生成绑定刚显示 snapshot 的 typed action，并经真实 Runtime 完成适用范围授权。

**最小修复：**无参数命令绑定刚显示的 request/digest/revision；带显式 ID 的旧命令继续精确校验，错误 ID 不回落到当前请求。必须测试“显示 A 后状态漂移到 B，旧输入不能授权 B”。yes 仍只批准一次，目录仍须已明确列入 Goal。
WORK-PACKAGES

C. 最小接续方案
保留实现，修正证明方式

推荐沿用现有 RequirementCoverage 五字段结构、原 CompletionClaim、Goal delta、evidence registry 和唯一主 loop。不再设计新的义务平台，也不把 coverage 当作语义正确性的证明。

本轮 Runtime 的确定性责任限于：复核存在、来源有效、版本正确、没有声明的 pending、mandatory criterion 没有漏覆盖、现有证据有效。模型负责从原文形成语义映射，业务 grader 负责揭露映射仍然错误的情况。

这里应明确纠正两种过强的机械要求：

不要求每个 target 都写入，也不要求每条 user fact 独立对应一个业务义务；目录、未修改文件、“继续”以及撤回性 correction 不能被机械变成新增完成项。
不按 coverage 行数、措辞黑名单或“一条 requirement 必须独占一个 criterion”判断语义正确。多个具体要求可能共享验证，但不能因此把一个文件 digest 宣传成完整业务证明。原合同已经限制了这类机械化扩张。
WORK-PACKAGES
完成与 blocked 路径保持同一边界

删除 readback 自动完成是值得保留的改动。当前 blocked 分支并没有直接调用 verify_goal_completion 来完成任务，而是在物理证据可推导时要求模型重新提交 claim。因此，不能把它描述为已经证实的完成门旁路。不过，“证据都可推导，所以请报完成”的指引仍应与 R2 新语义一致：物理证据齐全后先依据原文复核；有业务缺项则继续工作或提出必要 delta；仅完整覆盖时提交 claim。
SOURCE-CONTEXT
 
SOURCE-CONTEXT

只需在现有分支中修正必要指引并补交叉回归，不要取消真实 blocker、放开完成条件或新增 evaluator loop。

修正一处错误因果说明

新测试注释声称，旧实现会在同一批次的第一个 read 后跳过第二个 read；但被删除的旧 helper 明确要求已经回到 MODEL phase 且没有剩余 tool_calls，才能自动终结。

本轮应证明的早收尾是：批次结束后，自动结束截断了后续主模型本来还要处理的 CLI 等工作。不要把原有批次保护改写成过去不存在的缺陷。
WORKING-TREE
 
WORKING-TREE

旧状态只做最小兼容

旧活动 checkpoint 缺 coverage：读取为空，不视为已复核，回主 loop 补齐；新字段类型错误：拒绝；旧已终结历史：保持历史，不重新认证。correction 和相关写入后的失效继续复用现有 revision/freshness，不再增加独立复核时钟。
WORK-PACKAGES

D. 可交给普通 coding agent 的分阶段任务与验收
阶段 0：当前 Codex 只完成接续包与交接

在现有 handoff 目录更新唯一 RESULTS.md 的当前摘要，保留历史内容。将 R2 改为 IN_PROGRESS，分别列出实现、source、installed、real 状态，不能再用单一“完成/未开始”掩盖半成品。
VALIDATION

本地只需补读以下四组精确缺口，避免全仓扩审：

缺口	定点源码
healer 拒绝标记的真实来源	普通 TOOL_RESULT 生产映射、record_tool_result、ResolveApproval(approved=False) 完整分支及必要事实校验
权威原文是否始终进入复核	ContextManager 的事实分组、选择、compaction 保留/恢复和最终 provider 投影
R3 已 admitted 义务与授权失效	_apply_correction_lower_bounds 从当前 525 行起的函数尾部、delta 生效及既有 revision 失效处理
新字段往返合同	CompletionClaim、持久化 ModelResponse 的完整双向 codec，以及 receipt digest 的使用位置

交接记录绑定当前 HEAD、公开改动清单与内容身份，保留所有现有成果。**“可接手”不等于必须把 git status 变成零 dirty。**没有当前明确的本地检查点提交授权，就保留未提交修改并如实列出；不能 reset、stash 隐藏或删除，也不能默认 commit/push。
CONSULTATION
 
VALIDATION

以下阶段须由后续实施者取得产品修复授权后执行。

阶段 1：先修当前错误，并恢复测试输入的真实性

仅处理当前 7 项 ruff 问题，包括补 AdmittedCriterion import；不要顺手全库格式化。这个缺失 import 是确定静态错误，但不能仅凭它宣称已运行的所有完成路径都会 NameError。
CONSULTATION

随后修正 tests/kernel/fakes.py：保留动态身份绑定，取消空 coverage 自动变 satisfied；正例显式构造场景映射，反例的空值、错误来源和 stale 版本保持原样。

**阶段出口：**这些受影响路径可正常导入；测试助手不再改变被测试的完成语义。导入失败、依赖失败不计为业务 Red。

阶段 2：冻结 R2 业务验收，再动其剩余产品逻辑

优先新增原合同允许的 tests/acceptance/test_task_trust_completion.py，或在现有文件中等价承载，但执行包必须冻结具体路径与 node ID。场景不得预先构造完整 Goal 或手工填 admitted evidence。
WORK-PACKAGES
 
WORK-PACKAGES

最小场景集合如下：

场景	必须观察的行为
D04 自动早收尾反例	只完成 service 并回读，后续 CLI 脚本响应尚未消费；不能自动关闭任务，后续主 loop 能继续。
D04 admission 遗漏＋显式 claim	原始要求包含 service 和 CLI，draft 漏 CLI；取得 service 物理证据后，缺复核 claim 被拒绝；下一轮仍能获得原始要求并补 CLI。
结构性漏覆盖反例	已声明义务缺 coverage、pending、错误来源或错误 criterion，分别被拒绝；不能用它替代上一条 admission 遗漏场景。
完整业务正例	service、CLI 行为及当前验证均完成，有限步内 VERIFIED_DONE，不能靠永久拒绝收尾通过反例。
非 D04 同构任务	换目录、字段名和业务表述仍成立，生产代码没有 D04、retry_count 或 grader 特判。
失效与重开	correction 后旧 claim/coverage 无效；相关写入后旧验证无效；暂停、落盘、新进程重开后未完成义务没有丢失。

业务验收保持原 grade_d04 不变，并在产品 workspace 外冻结补充断言：service 与 CLI 的负数限制、新旧名称同时提供时的歧义拒绝、最多 1 + max_retries 次、原默认成功行为。模型自写 pytest 不是唯一验收。
WORK-PACKAGES

每条场景同时记录产品状态、当前义务/coverage、实际文件行为、原 grader 两个业务字段、补充断言、模型和工具调用数。grader 的两个过程项及整体退出码保持原样解释，不修改成 PASS。
VALIDATION
 
VALIDATION

已有修复可能让新场景直接 Green。此时记录事实，并在本次独立公开基线快照上建立必要对照；不要为了造 Red 回滚共享脏工作树。

阶段 3：完成 R1、R3 的窄收口

R1 只补 B4 的联合拒绝条件与矛盾反例；保留现有连续保存失败、安全 suffix、恢复和新进程测试。

R3 先通过真实 admission→correction→completion 旅程核实已 admitted 义务退役；已有实现正确就只补证明。保留冻结的正、负、解释、引用和 model flag 对照，不扩展为通用指令理解器。

分别运行原 VALIDATION 的 R1/R3 focused 集合，并显式加入实际修改到、但原 8 文件重跑没有覆盖的相关测试。共享 state.py/loop.py/contracts.py 串行修改，不派本地子 agent。
WORK-PACKAGES
 
VALIDATION

阶段 4：完成 R2 的字段、上下文与收尾闭环

按阶段 2 的失败点逐个最小修复：

同步 B3 的 digest、精确键集和类型规则，覆盖 state claim 与持久化 ModelResponse 两条往返路径。
对 B2 先补真实上下文测试；只有证明存在原文遗漏才修改 ContextManager 保留逻辑。
保留 readback 回主 loop，统一完成与 blocked 修复指引；缺复核或有 pending 后，模型能继续工具/Goal delta，而不是只能换 correlation 再次宣布完成。
保留 UNKNOWN、resource closure、证据 freshness 和有限修复预算；只补受影响的既有状态投影，不重做 CLI/TUI。

原有两个小预算测试被调大属于夹具适配，不能用它代替上下文压力证明，更不能据此修改生产默认预算。
WORKING-TREE
 
WORKING-TREE

阶段 5：完成 R4，并补齐 C1/C2

**R4：**默认提示→无参数短命令→精确 typed action→真实 Runtime 授权。必须覆盖一次性 yes、错误 ID、无 pending、不适用目录、snapshot 漂移，以及现有授权复用/次数/时效/撤销/版本边界。同步 /approve-artifact 帮助为实际解析顺序 <sha256> <workspace-relative-path>，不改 parser 顺序。
WORK-PACKAGES

**C1：**扩展现有测试，实际经过 writer 关闭、同参验证再次执行、旧 A 不再有效、新 A 成为有效证据，并检查模型下一轮 wire；只查 inventory 不足。

**C2：**复用新用例，补“成功 prefix＋安全闭合 suffix”及严格拒绝 prefix 的历史自愈投影。检查预期调用确实出现在 wire 中、结果一一对应、原成功结果和真实存在的 opaque continuation 不变；缺失/重复结果的负例由实际投影拒绝。无需真实 API。
WORK-PACKAGES
 
VALIDATION

阶段 6：真实层 E1——当前只记录授权阻塞

当前状态应写 BLOCKED_AUTHORIZATION。这只阻塞真实层，不阻塞后续已获实施授权范围内的本地和安装工作。

获得当前授权后，沿用原两样本设计，不增样本矩阵：

**E1-A：**全新 D04 正常完成；操作员只做正常治理批准，不提示实现或漏改文件。
**E1-B：**冻结 staged variant，初始上下文不得泄露未来旧别名要求；在已发生正常文件效果后的合法非终结边界注入固定 correction，然后 pause→退出→新 PID resume，不重述业务。

没有观察到合法注入边界记 NOT_OBSERVED；模型已提前完成新增要求、未来要求已泄露或没有实际新进程，均不能计为新增纠正生效。
VALIDATION

原建议的请求和时间上限不是本轮授权。真实 provider/model/endpoint、thinking mode、指定凭据来源、可外发合成材料、累计预算和脱敏证据范围，必须以当次授权为准。任何“产品完整成功、外部业务失败”的样本都使 R2 保持 UNRESOLVED，不能归咎模型后照样结案。
VALIDATION
 
VALIDATION

阶段 7：冻结候选，安装态最小验收，最终一次 source full

所有必要产品修改稳定后，创建本次唯一候选和新 non-editable wheel。新增公开测试/模块显式纳入 manifest，记录源码与 wheel SHA，不能复用旧物化目录。
VALIDATION

层次	必须证明
source	阶段 1–5 的目标反例、完整正例、协议重开和 C1/C2；每个节点有真实结果，不以测试文件总通过数替代。
installed	新 site-packages 来源；R1 保存失败/暂停重开，R3 中文正负，R2 不完整/完整及必要重开，R4 当前请求授权。子进程也必须记录安装态来源，保留 source 污染负对照。
real	仅 E1-A/E1-B；缺授权不伪装为通过，后续改动不能继续引用旧 wheel 的证明。

_019_installed_pytest.py 没有 --test-node 参数；按原合同使用单次命令局部的 PYTEST_ADDOPTS 精确选择，并核对实际收集和执行节点。零节点、skip、xfail 均不能代替所需安装证明。
VALIDATION

最后集中运行：

Bash
git diff --check
.venv/bin/ruff check .
PYTEST_ADDOPTS='' PYTHONDONTWRITEBYTECODE=1 PIP_NO_INDEX=1 \
  .venv/bin/python -m pytest -q -rx

记录实际退出码、完整摘要、skip 原因和最终代码身份；不残留 -k，不删 acceptance，不用自动重跑挑绿。后续再改产品代码，只刷新被改动失效的 focused、安装和 full 证据，不在每个小改后全量重跑。
VALIDATION

E. 产品使用感与推迟边界

这四项修复直接对应四种日用问题：R1 解决“已经发生的效果不能被说成没发生，以及暂停后会话不能继续”；R2 解决“只完成一部分就关闭任务”；R3 解决“用户换个连接词，执行要求就漏记”；R4 解决“明明已有任务范围授权，默认终端却无法自然使用”。

**R2 的合理代价是最终交付前再回到主 loop 做一次明确复核，不是每次工具调用后多做一轮自检。**提示应帮助模型继续完成缺项，而不是只要求它重新抄 ID；真正完成的简单任务仍要有限步结束，真正受阻的任务也不能被强迫谎称成功。

本轮明确推迟的是：任意自然语言的机械正确性证明、所有旧孤儿会话的自动救活、第二套语义裁判/复核平台，以及全平台、多 provider、GUI 或其他能力扩张。它们都不是解决当前四项问题的前提。
WORK-PACKAGES
 
WORK-PACKAGES

最终可以接受的阶段性交付表述是：

四项修复的本地与安装层完成；最终 source 门通过；R2 真实业务层待当前授权。

但这句话必须等对应证据确实齐全才能使用。现在的候选还不满足它；只有真实授权缺失可以单独留下，其余必要实现或本地/安装门不能一起打包成“待授权”。
VALIDATION

F. codex_execution_advice
JSON
{
  "codex_execution_advice": {
    "implementation_plan": [
      {
        "phase": "当前仅整理接续包",
        "actions": [
          "保留当前全部修改，在唯一 RESULTS.md 更新当前摘要：R1/R3 主体已实现但待收口，R2 IN_PROGRESS，R4 待实现，C1 未证明，C2 部分完成，I1 未证明，G1 当前失败，E1 BLOCKED_AUTHORIZATION。",
          "定点核验普通 TOOL_RESULT 与拒绝标记来源、权威原文的 context/compaction 保留、R3 admitted 过滤和授权失效、新字段完整双向 codec。",
          "记录 HEAD、公开改动内容身份和最终 dirty 清单；未获当前明确授权不实施产品修复、不 commit/push，不以 reset/stash/删除换取 clean。"
        ]
      },
      {
        "phase": "后续获得实施授权后",
        "actions": [
          "先修当前 7 项 ruff 问题；取消测试助手对空 coverage 的隐式 satisfied 注入，仅保留动态身份绑定。",
          "冻结原 D04 两条不同因果反例、独立 grader 与补充 SPEC 断言、完整正例、非 D04 同构、失效与新进程重开场景；禁止预补 Goal 义务。",
          "窄收口 R1 严格拒绝事实检查；核验 R3 已 admitted 义务撤回，已有机制正确则只补证。",
          "完成 coverage 的 digest、键集、类型和旧记录合同；原文投影仅在定点 Red 证明遗漏后修改；保留唯一主 loop 和现有证据、资源、UNKNOWN 守卫。",
          "完成 R4 默认提示到精确 typed action 的入口，补 C1 writer 关闭后同参重验与 C2 完整 wire 组合证明。",
          "有当前真实授权才运行 E1-A/E1-B；无授权继续本地与安装交付，不把真实层标 PASS。",
          "最终冻结公开 manifest 和新 wheel，执行安装态最小集合，再集中运行 source full、ruff 和 diff 门。"
        ]
      }
    ],
    "non_goals": [
      "不新增第二 model/tool loop、语义裁判服务或平行义务平台。",
      "不要求机械证明任意自然语言语义，不按 targets、fact 数量或 coverage 行数强制完成。",
      "不新增通用历史迁移或宽泛 orphan 自愈，不重放 UNKNOWN 工具效果。",
      "不扩大 Web 识别、权限策略、授权 TTL/次数、生产默认预算或产品能力范围。",
      "不修改冻结 grader，不读取私有历史日志或凭据，不继承旧 API 授权。",
      "不启动全平台、多 provider、GUI 或无关重构。"
    ],
    "optional_subagents": [],
    "verification": {
      "source": [
        "Red 必须是目标行为失败，不是导入或依赖失败；已修复路径可用独立公开基线对照，不回滚共享工作树。",
        "R2 从原始输入经真实 admission、审批、文件工具、回读和主 loop 验证，不由测试提前填入缺失义务。",
        "新字段覆盖 provider normalize、checkpoint、持久化 ModelResponse、receipt digest、旧活动记录缺字段和错误类型。",
        "保留真实完整正例、真实 blocker、UNKNOWN、resource closure、freshness 和有限修复预算。",
        "C1/C2 使用真实生产投影和合成数据；不以 inventory 或注释替代跨层断言。"
      ],
      "installed": [
        "本次新 non-editable wheel、新安装目录、中立 cwd，产品及子进程模块来源均为新 site-packages。",
        "执行前冻结具体 node ID，执行后核对真实收集集合；零节点、skip、xfail 不计通过。",
        "保留 source 污染负对照，不复跑安装态全库，不复用旧候选证明新代码。"
      ],
      "real": [
        "当前为 BLOCKED_AUTHORIZATION。",
        "授权后仅执行 E1-A 完整业务任务与 E1-B 真正新增纠正加新进程恢复。",
        "完整成功但独立业务失败则 R2 UNRESOLVED；未观察到纠正边界或前置条件不满足不得报 PASS。"
      ],
      "closure": [
        "最终 source full、ruff、diff 门均有准确退出码、完整摘要、skip 原因及代码身份。",
        "四项修复和 C1/C2/I1/G1 各自绑定证据；测试总数不代替完成矩阵。",
        "仅缺真实授权时才可交付本地与安装层完成、R2 真实层待授权。",
        "保留成果和准确 dirty 清单；不自动开启下一轮能力优化。"
      ]
    }
  }
}

