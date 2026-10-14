# 接续执行合同：只完成原四项修复

本包接续而不重做 [2026-10-13 原合同](../2026-10-13-task-trust-repair/WORK-PACKAGES.md)。原合同的排除项和验收边界仍有效；本文件根据当前半成品修正执行顺序与遗漏项。进度只写既有 `docs/handoffs/2026-10-11-product-reliability-closure/RESULTS.md`。

## 0. 接手后先确认现状

- 核对 START-HERE 的交接提交、工作树与 [审计输入身份](oracle-input/SOURCE-IDENTITY.json)。该JSON固定的是审计前半成品，不等同于之后的清理/接手提交。
- 保留R1核心UNKNOWN保护、原子关闭未开始suffix、R3明确指令识别和撤回修复；不重新实现这些机制。
- R2已增加RequirementCoverage、同步部分wire/checkpoint并删除自动readback收尾；这是**部分实现**，不是NOT_STARTED，也不是完成。
- R4未实现；C1未新增要求的跨层回归；最终安装/完整门/真实层未闭合。
- 不修API Key问题，不读取旧运行现场，不因为旧RESULTS里曾有真实调用授权而调用API。

## 1. R1：只补历史拒绝前缀的严格证明

文件：`agent/runtime/state.py::_close_orphaned_tool_batches`；回归放 `tests/kernel/test_runtime_compaction.py`。

当前仅用末结果`rejected=True`判断前缀已在审批处停止。[离线探针A](AUDIT-PROBES.md)证明即使该结果同时`executed=True/is_error=False`，或`unknown_outcome=True`，仍会生成尾部`executed=False`。这是合成损坏历史的校验缺口，不声称正常Runtime会生成该形状。

先Red，再最小修复：

1. 同一批次、顺序连续且无重复的完整prefix，其末结果必须同时具有严格审批拒绝语义：`rejected is True`、`executed is False`、`is_error is True`，且不存在UNKNOWN矛盾。
2. 对缺字段、0/1伪bool、相互矛盾标记、UNKNOWN标记，保持原facts并拒绝自动继续，零provider/tool调用，不补确定未执行。
3. 正常Runtime生成的旧拒绝prefix仍可补未开始suffix；新版正常pause/cancel/correction不退化。不得一刀切关闭正常恢复。
4. 不新增历史迁移器、自动工具重试或新的恢复权限。

最小验证：上述新矩阵 + 原R1-T1/T2/T6/T9。原先已通过的全部R1矩阵保留，在最终相关门复跑；无需每次修改都跑全库。

## 2. R2-A：收口新增claim的身份与数据合同

当前结构可以沿用，不另建义务平台。先用具体负例证明缺口：

- `record_completion_claim` 的receipt `payload_digest`遗漏`requirement_coverage`：相同其他字段、不同coverage得到同一digest。新claim必须把所有语义相关coverage字段纳入既有canonical digest。不得重算/重写历史receipt；模型response自身digest与receipt身份分别验证。
- `checkpoint._completion_claim_from_dict` 的`value.get(...) or []`将显式null/false/0/空字符串/空对象当作空数组。只允许**字段缺失**走旧记录缺字段路径；显式存在时按数组/条目/字符串类型严格解码。合法`[]`可加载但不因此满足完成门。
- `normalize._decode_requirement_coverage`目前接受嵌套未知字段；与严格schema及持久化response解码的精确键集合对齐。strict/portable、OpenAI/Anthropic两条真实adapter的离线wire都需覆盖。
- `contracts._requirement_coverage_from_payload`把非字符串ID元素直接放入tuple；审计已复现`source_fact_ids=[123]`、`criterion_ids=[123]`被构造成功。持久化ModelResponse也必须逐元素检查，不能只检查数组外形。

通过条件：旧字段缺失可读且不默认已复核；新字段合法roundtrip完全保真；pending/重复requirement_id/空或畸形来源、criterion绑定、嵌套未知字段按合同拒绝；source/checkpoint/model-response/provider投影一致。不能把宽松解码直接夸大为权限绕过，也不要借此全面重写序列化层。

导航：`agent/runtime/{contracts,checkpoint,state,context_control}.py`、`agent/provider/normalize.py`；复用 `tests/continuity/test_checkpoint_v4.py`、`tests/kernel/test_contracts.py`、`tests/provider/test_continuity_control.py`，按真实影响选择节点。

## 3. R2-B：复核必须看到原始要求，测试不能替模型复核

### 3.1 当前输入可见性

[离线探针B](AUDIT-PROBES.md)在4000输入预算下证明：原用户fact仍durable、ID仍在trusted_goal，但原文已从ContextPack移除；较高预算下原文可见。不能把“ID都被引用”称为“读过全部当前要求”。

实施者须在现有ContextManager/主loop内提供**有界且绑定当前来源/版本的复核输入**：

- 模型做完成复核时能看到当前Goal关联的权威用户原文及已消费correction，而非仅旧draft、admitted predicates或来源ID。
- 复用已有fact与context机制；不加入第二个模型/evaluator loop，不给provider执行权，不增加全局上下文默认预算。
- 不要求每一轮无条件固定无限历史。若必要原文确实超出边界，必须可读地说明复核材料不足，不能静默截断后假称已全量复核。正常短任务仍有限步骤完成。
- 测试覆盖：预算内原文真实存在；上下文压力下不发生“只有ID却准许声称复核齐全”；correction版本变化；durable reopen/compaction与ContextPack选择分别验证。只断言ID在JSON里不够。

### 3.2 测试辅助不能自动制造coverage

`tests/kernel/fakes.py::bind_runtime_goal`当前会为空coverage自动生成`the current trusted goal is fully satisfied`，掩盖遗漏输入。调整为：

- 自动绑定只处理Runtime动态身份/引用，不为缺失coverage创造“satisfied”的语义。
- 确需正例coverage的scripted fixture显式声明其具体语义/状态。可保留窄helper，调用点明确选择；不设默认“全部完成”来批量漂绿。
- 增加测试：使用`RUNTIME_GOAL_ID`占位但coverage为空时，经过helper后仍为空，并被真实完成门拒绝。
- 原有无关测试只作必要合同适配；不删除断言、不把所有结果改成COMPLETED、不改模型/预算来掩盖问题。

## 4. R2-C：补真正业务验收，再决定是否还有最小修复

当前未看到原合同要求的D04原始输入→admission→执行→外部业务判据的两条回归。现有“精确报告文件”测试只证明自动收尾已删除，不能替代它们。

原合同R2-T1–T7保持有效，其中必须落实：

1. **自动早收尾历史反例**：公开D04本次副本，宽泛draft→先service写入/回读→后续尚有CLI工作。保留当前已修行为，不能在首文件证据齐全时结束。
2. **admission遗漏反例**：原始双组件要求→模型draft漏CLI→service证据有效→缺逐项复核claim。测试不得预补CLI criterion或手填admitted evidence。产品应回到原主loop做复核，能发现并补做CLI。
3. **正例**：service+CLI新旧别名、同名歧义拒绝、负数限制、有界调用次数、原默认成功行为完整。真实Runtime有限步到VERIFIED_DONE，独立grader和补充断言同时通过。
4. **不同名字的双组件例**：产品代码不得识别D04、retry_count或grader名称来特判。
5. **freshness与恢复**：新correction、相关新写入使旧coverage/验证不可用；未完成义务在暂停/新进程恢复后保留。
6. **blocked分支**：当前`completion_evidence_available`仍只凭物理证据指示模型抄refs完成。更新为共享当前覆盖门/正确复核指引；缺业务复核不能被当成业务已完成，也不能因此永久禁止真实blocked。保留有界修复次数和真实阻塞语义。

先冻结workspace外的独立补充业务检查，再修产品。原grader/SPEC/manifest不改，模型自写测试不是唯一验收。

如果已经修掉某条缺陷，该回归在当前树Green是正常的；用已有修前证据或独立公开基线作对照，不为制造Red破坏当前工作树。若反例指向不同原因，记录证据后选择最小补丁，不预设所有真实历史失败都来自自动收尾。

修正当前`test_readback_completion_waits_for_remaining_read`中的错误因果注释：旧helper已要求MODEL phase且无剩余tool_calls，不会因批次第一项read而跳过第二项。应证明的是**整批结束后的自动收尾截断后续主模型业务工作**，不捏造旧实现不存在的缺陷。

**能力边界：** 结构完整但语义理解错误仍可能发生。不要要求Runtime机械证明任意自然语言；也不要只加更长prompt或一个checked布尔值就宣布业务已解决。真实代表任务仍漏做且报完成，则R2为UNRESOLVED。

## 5. R3保持；R4按原合同完成

R3现有明确指令冻结表及禁止/撤回回归保持，不新增词库平台或Web能力。仅在本包其他修改导致回归时处理；不要重新实现它。

补一项已有行为的端到端证明：通过真实process admission先形成已准入校验义务，再输入明确撤回correction，验证旧process admission、旧claim/验证版本及相关授权绑定按现有机制失效、无新执行、剩余文件任务可完成。不能在correction后手工把admitted tuple替换为仅文件criterion。源码`apply_goal_delta`已经移除旧TOOL_RECEIPT并清证据/claim/相关leases，因此这是待补证据，不预判存在新bug；Web分支只作共享函数受影响回归，不另开Web修复任务。

R4原合同未改：

- 默认提示展示无参数`/approve-goal-target`、`/approve-goal-directory`及准确范围；绑定刚显示的同一request_id/digest/revision。
- 保留带exact ID语法；错误旧ID不得回落当前请求。`yes`仍一次批准，目录不得由文件推断。
- Runtime stale/CAS、次数/时效/撤销/敏感路径保护不变；不合并外发确认或新增allow-all。
- 修正`/approve-artifact`帮助参数顺序为实际的`<sha256> <workspace-relative-path>`，只同步相关指南。
- 验收从默认可见提示→parser→typed action→真实Runtime，不能由测试偷偷提供隐藏ID。

文件与原测试见原WORK-PACKAGES的R4，当前无需重做TUI。

## 6. 交付门与最终停止条件

遵守 [原VALIDATION](../2026-10-13-task-trust-repair/VALIDATION.md)，本包只调整接续状态：

- C1仍需writer关闭→同参真实重验→下一轮provider wire有效的组合断言。当前freshness测试改动只是修fixture，不算C1完成。
- C2已有闭合suffix到OpenAI/Anthropic投影测试，但当前fixture两个call都未执行且没有opaque continuation，不能宣称已证明成功prefix/continuation不变。复用该测试补成功prefix+安全闭合suffix、严格旧拒绝prefix自愈投影；断言预期call确实在wire而非空集合相等，原成功内容和实际提供的continuation保持不变，缺失/重复结果被拒绝。无需API。
- 审计初始7项ruff问题已由交接人仅作导入/等价格式修正，ruff与受影响239项通过；无需重复这项清理。接手仍应核对现状，不能把lint通过说成功能修复。
- 按R1、R2合同、R2业务、R4分别focused；各阶段稳定后才扩大检查。
- 最终代码冻结后用全新目录构建candidate/non-editable wheel；记录源与安装模块身份，运行受影响installed节点。不得复用旧wheel或旧本地日志。
- 最终一次`git diff --check`、`.venv/bin/ruff check .`、`PYTEST_ADDOPTS='' PYTHONDONTWRITEBYTECODE=1 PIP_NO_INDEX=1 .venv/bin/python -m pytest -q -rx`。若之后再改代码，只重跑受影响证据并更新最终身份，不无脑反复全量。
- R2 E1-A正常业务与E1-B分阶段新增纠正/新进程恢复按原VALIDATION执行。原完整SPEC不能冒充新增纠正试验；真实调用先核对当前授权、provider/model、凭据注入来源与累计预算。没有授权时继续本地/安装，真实层标BLOCKED_AUTHORIZATION。
- 不commit/push/merge/tag/publish，除非用户在**执行对话**另外明确授权；此次审计人的本地保存授权不传给下一执行者。

只有各R项、C1/C2、installed/full和获授权的真实验收分别闭合才能逐项标完成。源码全绿不等于R2业务或真实产品通过；工作树clean也不等于功能完成。
