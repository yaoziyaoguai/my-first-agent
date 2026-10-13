你是 my-first-agent 的独立审计与执行包设计顾问。本次唯一目的：帮助普通 coding agent 在现有能力内完成日用可靠性收口，而不是再扩展 Agent 平台。请用中文，直接挑战我的结论，不能仅把下面的问题复述一遍。

Batch 1/1；新的独立咨询。项目是本地 Python coding/general agent（Python >=3.11，当前 macOS/Python 3.12.2）。HEAD 为 cbfa1e7，main 干净；ef9907f 已保存此前多轮源码、测试和文档，cbfa1e7 是交付收据。项目当前仍为 implemented-candidate，不是所有平台/网站均已验证的 production-ready 产品。当前 Codex 这轮只整理执行包，不实现产品修复、不调用真实模型、不 commit/push。

授权和架构边界：AgentRuntime.run_turn 是唯一生产 model/tool loop；ContextManager 独占上下文选择，ToolRuntime 独占 callable 调用；provider 只做 ContextPack→ModelResponse；所有副作用走 policy/approval 与执行前后 checkpoint。不要删除审批、UNKNOWN 不自动重放、资源清理确认和完成证据门。不要引入第二套 loop、守护进程、service locator、动态插件框架、文件监控系统或大型评测平台。不要按文件行数拆代码，不新增 Memory/MCP/SubAgent/sandbox/调度能力。外部研究若确有必要，只用官方文档或开源 primary sources，给链接；看不到来源就注明未核实。

附件 CODE_CONTEXT.txt 是 cbfa1e7 的精确源码摘录（每段有路径/原始行号/源文件 SHA-256；部分为全文），以及公开的原始验收合同。附件 AUDIT_CONTEXT.md 区分了本机已证实事实、执行者报告与尚未证明的项目。没有真实 key、用户会话或私人运行目录。摘录外代码看不到时不要假装已检查；请指出最小必要补充，而不是索要全仓库或私人日志。

请围绕以下四项修复与两项证据缺口作一次高强度、受约束的审计：

1. A1/RC-02：现在只把 managed_web_start 加入验证失效工具集合。独立合成生产格式事实序列 start→只读验证 A→可能继续写入→stop(cleanup confirmed) 后，资源门关闭，但旧 A 仍被接受，同参验证被抑制。原真实 server 测试只覆盖 A→start→write→stop。原合同明确要求 start→A→write→stop。请检查最小正确修复应如何覆盖正常 stop、重复 stop、拒绝、失败/UNKNOWN、两个并行存活资源、重开/compaction 以及纯只读验证组合。不能用无依据的全局禁用验证绕过；也不要为了这个问题造新的状态系统。
2. A2：scripts/build_candidate_manifest.py 无确认 rmtree 已有 --out。我们倾向仅允许不存在的新输出目录并在任何写入前验证目标、manifest 与源边界。请检查误传仓库/祖先/源文件、manifest 覆盖、软链接以及局部失败，推荐最小而足够的安全合同，不要求不切实际的无限本地攻击者防护框架。
3. A3：独立全量 3760 passed / 1 skipped / 1 failed，587.04 秒；失败为 test_015_offline_gate_timeout_cleans_owned_process_group（期待124，得到125 cleanup unconfirmed），单独复测1 passed。另有执行者报告的 posix_supervisor_cleanup 与 managed-web 偶发失败，但根因均未定位。请提出有区分力、有限次数的诊断方案；清楚区分真正未清理、zombie/orphan 可观察性、测试时间假设和实际回归。不能因为重跑绿了就通过，也不能把125吞成124，不能通过 pkill 杀用户进程。是否必须改共享 process/group.py 要以证据决定。
4. A4：官方 Flash identity 的 reasoning_expected 无视显式 disabled；离线 MockTransport 已证实请求发 disabled，正常纯文本响应却抛 missing_reasoning_continuity。请给出 none/enabled/disabled、JSON/SSE、工具续接与身份不匹配的最小测试矩阵；保留 enabled 的保护，不换供应商/模型/容量，不照抄未核实的当前 API 假设。
5. E1：原3679 passed是候选源码态，导入来自.local/candidate且排除tests/acceptance。已另外验证：独立导出→wheel→installed target的113模块来源；原生安装回归4 passed。请判断为了本次有限变更还必须补什么 installed 证据，哪些不必全库重复，如何绑定最终修复后的真实文件身份。不要重复要求已满足且未失效的旧工作，但修改后不能复用旧 wheel 的成功。
6. E2：旧“14 effects零重放”只用tool_call_id全唯一证明，不足以排除新ID重做相同副作用。请设计最小的新进程恢复/计数器/执行账本证明，允许受控假provider验证内核；真实API旅程另列，不混淆。调用内容相同有时也是合法重复，不应创造“按参数永久去重”产品行为。当前授权不包括读取.private/.local旧会话或花真实API；未来执行者须拿到当前凭据来源、数据和预算授权再做真实验证，缺权限不能编造PASS。

产品力也请审：用户希望日常任务可靠完成、少提醒、出错知道下一步。上次真实正例报告需要12次审批与18次外发确认，但我们没有每次交互的必要性证据。本轮要解决真实故障，不借“体验优化”取消权限或新增大 UI。请指出本执行包哪些要求会做重、哪些做轻、哪些仅需诚实说明；明确是否存在必须加入且与这六项共享根因的遗漏。除此之外的想法列为延期，不进入执行范围。

交付要求：

A. 执行裁决：同意/反驳/证据不足逐项表，优先级、依据与可观察用户影响；区分已知缺陷、风险、未验证。
B. 唯一推荐的最小修复方案（需要时简述被拒替代），依赖顺序、涉及文件/符号、每项必须先失败的回归及成功/失败边界；不要生成大段实现代码。
C. 给普通 coding agent 的资料包内容：可以直接执行的步骤、基线核对、精确验收矩阵、允许改/禁止改、验证命令分类、需要外部授权的条件、停止条件与最终交付格式。不要把“修到最好”当任务。
D. 全量测试策略：每个增量只做focused；最终一次完整项目门（ruff、diff、完整pytest），若失败如实阻塞。诊断重试必须有次数、时间和新证据，不无限重跑；最终代码发生实质变化后旧门作废。
E. 最小产品判断与延期清单，禁止借本包扩 scope。
F. 最后以以下 YAML 完成，optional_subagents: []（本次不请求并行 Agent）。Oracle 只提供建议，不能授权提交、推送、真实API、私人数据访问或修改权限。

codex_execution_advice:
  implementation_plan: []
  non_goals: []
  optional_subagents: []
  verification: []
