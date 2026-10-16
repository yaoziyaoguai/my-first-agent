# 四项实际问题的修复合同

本文件与 [START-HERE](START-HERE.md)、[REPRODUCERS](REPRODUCERS.md)、[VALIDATION](VALIDATION.md) 合用。R1–R4 对应审计原顺序；**实施 R1 → R3 → R2 → R4**。

共享 `state.py/loop.py/contracts` 的修改串行进行。不要让多个 agent 同时修改这些文件。独立测试/只读复核可并行，但不要求配置 Pi、Claude 或 Oracle。

## R1 / P1：UNKNOWN 不能洗成确定未执行

### 原因与目标

工具效果已经发生，result checkpoint 和 recovery checkpoint 连续失败后，`_handle_unexpected_error` 仍进入 `fail_run`，丢失 active run；新 healer 随后把缺结果的调用补成 `executed=False`。修复要同时守住未知状态，并停止事后仅凭 orphan 猜测。

### 最小实施边界

1. `agent/runtime/loop.py::_handle_unexpected_error`：durable snapshot 是 EXECUTING 或 AWAITING_RECOVERY 时，持久化失败不能落入清空 run 的路径。保留 intent、batch、cursor、run identity。恢复记录也保存不了时可以返回明确失败，但不能报告尚未落盘的安全终态；存储恢复后通过现有 Resume/Recovery 路径继续，零工具重放。
2. `agent/runtime/state.py::end_run/fail_run`：加入窄不变量，不允许抹去 UNKNOWN。普通无未知副作用的失败仍可正常收尾。
3. 把“确定尚未执行的当前 batch suffix”在**还持有当时 active phase/cursor 的安全转换中**闭合，与清空/替换 run 一起落在同一 CAS。优先复用现有结果形状，不新建 checkpoint 系统。
4. 限制 `_close_orphaned_tool_batches/accept_action` 的历史自愈：没有充分证明就保持未确定，不能凭缺 active_run、缺 result、last_safe_result 或旧 superseded 文案推断未执行。

需要核对的安全丢 run 入口：`_stop_safe_active_run`（pause/cancel）、`apply_control_request` correction、`ResolveApproval(approved=False)`、`CancelRun`、`SubmitMessage` correction、`complete_run`、`end_run/fail_run`。`accept_blocked_claim` 已要求 MODEL，确认后可不改。只为同一故障原因调整这些入口，不做相邻重构。

闭合证明只适用于**当时 active run 拥有的 exact batch 与未开始的 suffix**。既有成功/拒绝结果保持原值；新结果连续位于该批次内，在后续 user/assistant fact 之前。保留 operator origin、脱敏、幂等与 action/revision 冲突保护。

### 历史数据边界

- 新版安全停机已经原子闭合的批次：直接复用，不重复生成结果。
- 仍有 AWAITING_APPROVAL active state：按其 cursor 安全处理；不能广播成全部历史 orphan 都安全。
- 可核实的旧“同批完整连续 prefix，最后一个为 Runtime 拒绝审批结果，缺失项全在其后”：可保留窄自愈。必须验证 exact batch/顺序/拒绝标记；有矛盾、重复、缺 prefix 时不能采用。
- 其余旧 orphan：保留原 facts/checkpoint，以可读错误或动作冲突说明“旧调用结果无法证明，不能自动继续”，不发 provider/tool、不伪造非执行。**不要求本轮造历史迁移器或假装所有旧会话都能无损救活。** 这是纠正原来的无证据恢复，不是删除数据。
- `last_safe_result`、run_id 相等、“safe boundary”文字、旧 `superseded=True` 均不是 per-call 非执行证明；不得新增宽泛 fallback。

### 必须先 Red 的矩阵

| ID | 输入/故障 | 修复后必须成立 |
| --- | --- | --- |
| R1-T1 | 效果执行后 result 保存失败，连续两次 recovery 保存失败，随后存储恢复 | effect=1；durable intent 留存；仍在EXECUTING则Resume进入恢复，已落盘AWAITING_RECOVERY则走既有Resolve流程；不生成未执行事实，不再调用provider/tool |
| R1-T2 | 所有后续保存继续失败 | durable EXECUTING 保留；如实持久化失败，不报告已安全收尾 |
| R1-T3 | result 保存失败但第一次 recovery 保存成功；以及 EXECUTING 保存前失败 | 前者原恢复行为不变；后者 effect=0 |
| R1-T4 | 多调用批次第一项成功、第二项待批准，在 pause/cancel/correction/拒绝处分流 | 已执行 prefix 不变，只闭合未开始 suffix；无重复调用/结果 |
| R1-T5 | complete/end 路径在仍有未执行 tail 时结束 | 同一 CAS 先闭合 tail，结果不放到最终 assistant/user 之后；未知态不能走此分支 |
| R1-T6 | checkpoint 关闭、在新进程重开，恢复/继续 | 正常审批 pause 不再 bricked；未知效果不自动重放；无人工重述任务 |
| R1-T7 | 旧孤儿 + fatal/完成文字/复用run_id/已执行prefix/旧superseded；对照严格拒绝prefix | 前组不伪非执行且零继续；只有有证据的后组可补尾部 |
| R1-T8 | 多批次、跨批同call_id、重复/畸形结果、重复action/revision冲突 | 不跨批借证明，不丢结果，不重复补记，畸形 fail closed |
| R1-T9 | 安全闭合后经 KernelContextManager→OpenAI/Anthropic wire | tool calls/results exact配对，既有成功结果与 continuation 不被重写 |

新增故障回归按保存状态语义注入，不长期固定“第9/10/11次”。跨进程使用本次临时 workspace 与可数非幂等效果，不以最终文件相同代替次数。

导航：`tests/kernel/test_effect_ordering.py`、`test_runtime_errors.py`、`test_runtime_compaction.py`、`tests/continuity/test_resume_effect_no_replay.py`、`tests/provider/test_continuity_control.py`。不默认改 checkpoint schema、provider adapter 或审批策略。

**R1 不通过的捷径：** 吞错、清空run、重试工具、把全部孤儿判safe、把全部正常pause禁掉、只验证一次result保存失败。

## R3 / P1：明确的测试要求不能因连接词漏记

### 导航与边界

`agent/runtime/state.py` 的 `_EXPLICIT_LOCAL_PROCESS_PATTERNS`、`_classify_explicit_requirement`、`_local_process_requirement`、`accept_goal_draft_proposal`、correction义务同步；测试复用 `tests/continuity/test_contracts.py`、`test_entry_routing.py` 和 `test_verified_done.py`。

先复现已知语序差异，再最小修正当前 authoritative user text 的明确命令识别。不是构造通用自然语言权限引擎；模型 `requires_local_process` 仍不能单独授予 authority。未知表述不应被宣称“已完整理解”，也不允许自动扩权。

### 冻结测试输入

下列为直接发给产品的完整 user text，不是网页或工具输出。分别测试模型 flag=True/False 时的义务结果；执行始终仍需原政策/审批。

| 类型 | 用户输入 | 期望 |
| --- | --- | --- |
| 明确执行 | `运行 pytest -q` | 建立必做process验证 |
| 等义连接 | `修复功能，运行 pytest -q` | 同上 |
| 等义连接 | `修复功能并运行 pytest -q` | 同上 |
| 等义连接 | `修好后运行 pytest -q` | 同上 |
| 分步 | `先修复功能，然后执行 pytest -q` | 同上 |
| 英文对照 | `Fix the bug and run pytest -q` | 同上 |
| 显式脚本 | `运行 ./check-result` | 保留既有入口绑定 |
| 禁止 | `不要运行测试，只修改 app.py` | 不创建被禁止的义务，不执行 |
| 后续禁止 | `运行测试。不要运行任何程序，只修改 app.py。` | 保留现行最后明确禁止语义 |
| 只求解释 | `如何运行 pytest -q？` | 不把问题变成执行要求 |
| 要求写例句 | `只写 README，内容包含这句话：运行 pytest -q。不要执行它。` | 不执行，不创建与禁止冲突的义务 |
| 无运行要求 | `只修改 app.py 中的拼写错误` | 模型flag不能单独制造process义务 |

还需端到端断言：有明确校验要求时，仅文件digest齐全仍不能完成；校验成功且证据新鲜才可满足该项；correction 撤回/替换要求后按现有版本绑定失效；工具输出、网页或被引用资料不能创建新的执行权限。

字符串分类单测不足以结案，必须经过 Goal admission 和 completion gate。不能只补一个精确字符串特判；不改公开 Web 识别、工具执行权限、默认预算或 provider 行为。

## R2 / P1：业务漏做时不能宣布完整完成

### 确认事实与尚未确认的因果

确认的是公开真实记录中 D04 业务失败与 VERIFIED_DONE 同时发生。未读取该私有现场，不能事先声称其唯一根因为 auto-finish、deferred criterion 或 R3。以下公开代码形状值得确定性复现：

- `_admit_approved_file_criterion` 把唯一 deferred filesystem criterion 绑定到首个批准文件；宽泛功能要求可能因此变成“service.py 字节已写入”。
- `_finish_if_durable_evidence_is_complete` 在最后 read_file 后可自动生成 claim 并结束，主模型未必有机会再检查 CLI 等尚未完成内容。
- `ClosedEvidenceRegistry` 证明 admitted predicates，不证明用户自然语言要求已经完整拆解。

### 先建立两条可区分的 Red，不先大改架构

在公开 D04 fixture 的本次临时副本上，用 ScriptedProvider 驱动**真实 Runtime、文件工具、审批与回读**，外部运行不变的 `grade_d04`：

1. **自动早收尾反例**：宽泛/deferred目标只写 service 并回读，后续响应原本还会处理CLI。若被早收尾截断，记录 provider 次数、剩余动作、文件状态、产品终态与 grader 两个业务字段。
2. **admission→显式claim遗漏反例**：从原始service+CLI双组件用户要求开始，模型首先提交遗漏CLI的draft，再写service取得合法物理证据，随后提交“全部完成”的claim。测试不得提前补CLI criterion、手工填admitted evidence或直接构造完整Goal；必须记录原始输入→draft→admission→批准/证据→claim全过程。在尚无当前输入逐项覆盖复核时，这个claim不得结束任务；保留下一轮真实主loop复核机会，再由脚本响应指出缺失CLI并继续。另保留“Goal中已有明确义务、claim漏覆盖”的结构反例，两者不能互相替代。

每条只证明其实际触发的原因。不能只修自动收尾就宣称显式 claim 已安全，也不能把 ScriptedProvider 的成功写成真实模型改进。

### 最小完成合同

**物理证据齐全是必要条件，不是完整业务完成的充分条件。** 最终结束必须经过唯一主循环中、针对当前 Goal revision 与当前权威用户输入/最新correction的显式覆盖复核。

- 先复用 `GoalFrame.proposed_criteria`、`created_from_fact_ids`、现有 Goal delta、CompletionClaim 与 evidence refs；发现阶段尚未展开的义务不能仅因首个文件获批就被默认为全部满足。
- 复核应能列出当前用户要求/纠正对应的义务、各项现有验证或证据、未完成/未验证项；不以一个模型自报 `checked=true` 代替映射。
- 复核输入必须包含当前权威用户原文/纠正，而不只回看模型先前漏拆的draft或admitted predicates。引用整条`source_fact_id`、自报空剩余列表、首个文件digest三者的组合也不能充当逐项复核；测试要证明缺失这一步时原来的admission遗漏路径不能直接终结。
- Runtime 负责版本、来源引用、结构覆盖、未完成项和现有证据有效性；模型负责语义映射。复核不能铸造 evidence/permission，也不是新的 oracle 或第二个 evaluator loop。
- 若现有 claim 不足以表达，允许在现有 CompletionClaim/上下文合同中做**最小、revision-bound 的结构扩展**；先在唯一 RESULTS 写出字段、来源、失效条件、checkpoint/wire读写及旧记录行为，再实施。不得做平行义务平台；需通用迁移或全新权限架构则停止该设计并报告超范围。
- 未具备当前覆盖复核时，readback 自动路径不能自行合成“已复核所有业务要求”；返回原 model/tool loop。显式 claim、自动收尾及“证据齐全就强制完成”的 blocked处理必须共享这一门，不能从另一条路绕过。
- correction、目标/义务变更、后续相关写入使旧复核或验证失效；复用已有 freshness/revision 机制，不另建时钟系统。
- `targets` 是范围，可能含目录或无须修改的文件，**不得机械要求所有 targets 都写入/都有digest**。
- 新复核缺失的旧活动 checkpoint 不能被默认视为复核已满足，也不能因此丢掉任务；应在主loop正常补复核或如实受阻。旧已终结历史记录不重新认证或全量迁移。
- CLI/TUI 从真实状态投影验证范围与剩余项；仅把“完成”改成较弱文案、仍关闭未完成任务，不算修好。

这里不承诺机械证明任意自然语言语义。确定性门必须拒绝的是缺复核、版本失效、已声明义务漏覆盖和证据不合格；即使结构完整，模型仍可能把用户原文理解错。后者由独立业务验收揭露，不能把前者通过表述为“所有语义漏项已机械消除”。不得为让恶意/错误模型任意自证都被识别而新增自然语言解析器或第二个模型裁判。真实代表任务仍假完成，R2就是未解决。

### Green 与防伪完成验收

| ID | 场景 | 必须成立 |
| --- | --- | --- |
| R2-T1 | 只修service，CLI旧别名遗漏，现有文件/局部测试均正常 | 外部业务失败仍被保留；产品不能 VERIFIED_DONE/完整交付或自动关闭；不能把等待用户当永久替代工作 |
| R2-T2a | 原始双组件要求→模型draft遗漏第二组件→service证据有效→缺逐项复核却claim全部完成 | 未被测试预补义务；不能终结，主loop仍能拿到原始要求作覆盖复核，再继续补第二组件 |
| R2-T2b | 已声明义务未覆盖，或者复核仅整条fact引用/空剩余列表/首文件digest | 被完成门拒绝并给可修复的下一步，不改成假blocked/假成功；不得把结构通过外推为语义永不误判 |
| R2-T3 | service + CLI的新旧别名、同名冲突、负数限制和有界次数都正确；当前验证完成 | 有限步内能够 VERIFIED_DONE；所有验证范围可读；不以永远拒绝完成规避T1 |
| R2-T4 | 一个不同目录/字段名的双组件同构任务 | 同样防早收尾，产品代码不识别D04/retry_count/grader名字 |
| R2-T5 | correction后复用旧claim/覆盖，验证后再修改，暂停后恢复 | 旧覆盖/验证不能完成新版本；尚未完成义务不会丢失 |
| R2-T6 | readback自动路径、显式claim、blocked强制完成、resource未关闭 | 同一完成门；资源/UNKNOWN/已有freshness保护不退化 |
| R2-T7 | 原本可精确验证的简单文件任务、直接问答、真实完成的任务 | 保持可完成，不引入每轮用户确认或无限额外模型自检 |

**业务检查不能只看现有两个 grader 布尔值。** D04冻结grader并不覆盖全部SPEC：另外增加本次workspace外的独立补充断言，至少覆盖service与CLI负数、两名字同时提供的歧义拒绝、最多`1+max_retries`次、原默认成功行为。补充断言在产品修复前冻结；不改原grader，也不把“service+CLI参考实现”当作自动正确答案。

现有 D04 fixture 的 pytest 只覆盖很少行为，单跑它全绿不足。模型自写测试可作为产物，但不能作为唯一独立验收。

导航：`agent/runtime/state.py`、`loop.py`、`evidence.py`、`contracts.py`、`context_control.py`、`context.py`、`views.py`；仅按需要改被影响投影。复用 `tests/continuity/test_verified_done.py`、`tests/process/test_r1_two_validation_completion.py`、`tests/acceptance/test_coding_autonomy_grader.py`。可新增 `tests/acceptance/test_task_trust_completion.py` 承载本包场景，不能把 grader 导入 production Runtime。

**R2整体通过必须包括 VALIDATION 的有界真实模型层。** 无授权可完成本地与安装层，但 R2 真正日用结果保留未闭合，不伪称修复效果已经实证。

## R4 / P2：接通现有CLI任务范围授权

### 固定交互，不重建权限系统

- 在当前有效文件审批提示里显示两种显式短命令（按适用范围）：`/approve-goal-target`、`/approve-goal-directory`。说明只作用于当前任务/具体文件或已声明目录、有限次数/时效，可撤销；`yes` 仍只批准一次。
- 无参数短命令从**刚显示的同一 authoritative snapshot**绑定当前 request_id/digest/revision，复用 `build_resolve_approval`，设置对应已有 flag。
- 原有带 exact ID 的命令继续支持；传了错误/旧ID必须拒绝，不能悄悄回落到当前请求。
- 无 pending、非文件/不适用请求、目录未被Goal明确列入等，仍由既有规则拒绝；不从文件推断父目录，不放宽敏感路径或审批上限。
- Runtime 对 stale action/revision/CAS 仍是最终裁决者；CLI不持久化权限，不调用工具，不默认帮用户选范围授权。TUI现有语义不改变。
- `/approve-artifact` 帮助改为实际支持的 `<sha256> <workspace-relative-path>`，不改真实解析顺序；同步README本段指引即可。

### 必测

1. 用默认 renderer 输出作为普通用户可见信息，不由测试偷偷提供隐藏 ID；无参数短命令生成精确绑定的typed action。
2. 经真实 Runtime 授权后同目标后续操作可复用；换工具/目标、超次数/时效、撤销、Goal revision变更仍拒绝或重批。
3. `yes` 两个范围 flag 都为 False；错误ID、无请求、不合适目录不授权。
4. 显示后snapshot漂移，旧输入不能授权新请求。
5. 帮助中的artifact命令示例可以被真实parser正确解析。

导航：`agent/cli/app.py`、`render.py`、`actions.py`；复用 `tests/cli/test_commands.py`、`test_contextual_decisions.py`、`test_render.py` 与现有 `tests/continuity/test_goal_policy.py`/`test_goal_controls.py`。不新增全局allow-all、不合并外发确认、不更改授权TTL/次数。

## 必需交付门（不增加功能目标）

- C1：P2-2 writer关闭→真实同参重验→模型下一轮wire有效；不要只调用inventory函数。旧A失格，新A正常执行并成为有效证据。
- C2：P2-3由R1-T9覆盖；healed facts进入真实context/provider投影。离线投影足以证明配对，不为此付费调用API。
- I1：最终产品代码的新wheel、模块来源与受影响行为一致，不用旧物化目录。
- G1：最终source全量、ruff、diff门及准确skip原因。
- E1：R2真实业务正例与纠正/恢复旅程。报告区分业务判据与过程判据，不修改冻结grader。

每个交付门必须指回它证明的R项；不能因这个章节去启动全平台/全能力优化。
