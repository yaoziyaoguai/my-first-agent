# Oracle交叉审计：尽快交付好用的本地Agent，范围必须收敛

日期2026-10-17，项目my-first-agent。用户要求：上一个Coding Agent执行前包很久了，核对还没做好什么；为了尽快做成日用Agent产品，判断还缺哪些必要能力；Codex+Oracle交叉审计后给普通Coding Agent一份新的、详细但不发散的执行包和Prompt。本轮只审计/制作资料包，不直接实现、不提交/推送、不调用产品付费API或读取私人运行记录。

你是独立顾问。使用5/5档，可自行并行分析正确性/产品力/最小实施范围；不要求本地Codex另开子Agent。不把上一位执行者的DONE或测试数量当事实。我们需要可靠地做普通工作、少提醒/检查/收尾，不追求全平台、全第三方或任意自然语言的数学正确性保证。

## 当前身份与输入

本地main为PR #5合并后的0cc0db1。上一审计交接ef06b10之后35文件5121+/202-；已跟踪树clean，仅未知未跟踪`result.phase.json`（不读、不纳入）。输入只含公开代码/文档/合成测试；无key、profile、私人checkpoint或真实原始日志。

- LOCAL-AUDIT.md：Codex已确认的当前事实与实测反例，分清确定缺陷/报告/待证。
- CHANGE.patch：ef06b10到当前HEAD的产品层diff（不含大量测试/报告）。
- SOURCE-SLICES.md：带路径和行号的当前完成门、上下文、授权、测试、driver及交付文字相关片段。
- README.md：当前产品路径、能力和边界。
- 原VALIDATION.md：上一包冻结验收，不能事后降低其正常任务正例标准。

原架构继续保持：AgentRuntime.run_turn唯一生产model/tool loop；ContextManager独占上下文选择，ToolRuntime独占调用；CLI/TUI只适配action/result；所有副作用经policy/approval+EXECUTING+result。没有权限放宽、第二语义裁判loop、通用义务平台、按文件行数拆分、默认提高请求预算或自动重绑所有旧seal的授权。

## 最重要的新反例

Codex在当前HEAD使用公开D04 fixture，沿真实Runtime/admission/写入/readback/完成门执行；只把现有测试的空coverage负例换成**非空的泛化satisfied coverage**，不补CLI。结果：`verified_done`，4次scripted provider调用，CLI原字节未变，admitted=1、coverage=1，冻结grader两个业务值false，补充`cli_both_names=false`。详细输出与方法在LOCAL-AUDIT。这是确定性产品路径反例，不是又一次付费模型频率测试。

现有D04成功/遗漏测试用_FileTaskProvider固定先写service再写CLI；_claim_for生成一条“完成用户当前权威要求（含已消费correction）”并引用全部fact/criterion。旧包要求原始双组件漏做反例，但当前只阻止了空coverage。这证明完成声明强于实际证据，但不要求Runtime机械理解任意自然语言。请给一个能消除此具体反例、保留正常正例、避免再造框架的方案；若“用户任务整体完成”的现有claim本身不合理，请明确推荐更诚实且可用的产品合同，不能只是换文案后称R2修好了。

## 请回答

1. 上包哪些已经做好应该停止重做，哪些还没闭合？按重要性分级、给具体代码/测试证据和用户影响，标明推断。请挑战Codex的判断，避免顺从。
2. 哪些地方做重/做轻/复杂/太简单？特别审查：完成语义、blocked修复指引、请求/反复收尾成本、Goal targets散文导致复用授权不可用、driver自动“继续”与normal样本注入额外correction、最新安装身份。
3. 产品当前是否已有足够能力做一个**macOS单用户、本地项目任务为主的日用beta**？缺的最小能力是什么，还是主要修复现有链路？从“安装配置→下达普通任务→执行与必要审批→正确收尾→第二任务/重启恢复”判断。明确首版支持/暂缓，别为了凑全功能把Browser/Scheduler/MCP/Memory/并行Agent都列为上线必修。
4. 推荐最多3个主要工作包（交付验证可作为第四包），尽快完成。每包：精确目标/非目标、触碰模块、实施顺序、至少一条区分修前修后的失败例及完整正例、必要离线/安装/真实验收、停止条件。能复用的既有测试不要全重做。不预设重构/新增持久化字段/新增Runtime owner。
5. 真实E1-A报告业务全过但40次请求未终结；E1-B完成。原合同正常样本须自己终结。如何诚实归级并用少量真实样本证明改进，避免无止境dogfood？给建议预算/干预次数记录，明确建议不是授权。
6. 若缺行业判断，仅调研官方/开源primary sources（例如Codex/Pi/Anthropic官方），给直接来源链接，区分已核实事实与建议；不要求照抄别人的全部权限模型。

输出：Executive verdict；已完成/未完成矩阵；≤3+1个执行包；明确不做；证据与授权缺口；最后输出codex_execution_advice（implementation_plan/non_goals/optional_subagents: []/verification）。当前Codex可以读公开源码、写资料包、做合成离线检查；不能从此回答获得产品API、凭据、Git发布或个人系统修改授权。
