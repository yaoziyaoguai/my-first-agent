# 三个修复包 + 一个交付门

这是 2026-10-17 Codex 本地审计与 Oracle 5/5 交叉审计后的**实施合同**。原始顾问意见见 ORACLE-ANSWER；本文件是经本地源码复核后的执行取舍，不要求照单实现顾问的一切建议。

目标：把现有 macOS、本地项目、单用户 CLI Agent 收口到可试用的日用 beta。不是新增 Agent 平台。全程沿用唯一 `AgentRuntime.run_turn`、ContextManager、ToolRuntime 和既有 policy/approval/checkpoint 边界。

## 顺序、保留项与预算

顺序固定为 **W1 → W2 → W3 → G**。W3 的离线 driver 修正可在等待外部授权时先做；不要并行修改同一 state/loop 文件。无需自动开子 Agent。

R1 严格拒绝 prefix、R2 身份/解码/原文 pin/证据刷新、R3 撤回、C1/C2、provider summary framing 均保留。不得因为旧 R2 整体未闭合而推倒这些工作。

每包先实际 Red，再最小实现和 touched-area 验证；最后只集中跑一次全量。详细命令、真实成本和交付门见 VALIDATION。当前包不授予 commit/push、API、凭据读取或个人系统设置权限。

## W1｜最高优先级：明确交付对象不能从完成范围里消失

### W1.1 要解决什么，不解决什么

必须阻止 PROBES/P1：原用户要求包含 CLI，但模型草稿只列 service；只完成 service 后发一条**非空**泛化 coverage，不能进入 `VERIFIED_DONE`。完整双组件仍能完成，不能为了阻断反例把所有任务都卡住。

本包修复“明确交付对象被草稿遗漏”的可观察入口，**不声称机械证明任意自然语言的全部业务语义**。独立 grader 仍需检查业务；digest 只证明观察到的内容版本，process receipt 只证明实际那次命令结果。不得把它们改称全业务证明。

不新增终态、不改 `VERIFIED_DONE` 为一个更弱状态来凑旧验收、不增加第二模型评审 loop、不建通用义务平台、不将 D04 grader 放进产品。也不能只增加 coverage 行数、禁词或“再想一遍”提示。

### W1.2 已核对的代码入口

- `agent/runtime/state.py`：`_goal_source_text`、显式 process authority 的现有分类路径、`accept_goal_draft_proposal`、`_apply_correction_lower_bounds`、`accept_goal_delta_proposal`、`_admit_approved_file_criterion`、`_require_requirement_coverage`、`verify_goal_completion`。
- `agent/runtime/evidence.py`：`_filesystem_digest`、derive、现有 freshness。
- `agent/runtime/loop.py`：completion_claim 和 blocked_claim 分支；不新增控制循环。
- `agent/runtime/context_control.py`/既有 Goal 投影：只在需要给主模型显示具体缺口时调整。
- `tests/acceptance/test_task_trust_completion.py` 及受影响 continuity/kernel/provider 测试。

当前 `_admit_approved_file_criterion` 已能把随后实际批准的文件绑定成 criterion，即使它不在原 draft；不存在“模型一定要先发一个无用户 correction 的 delta 才能补做 CLI”的前提。后者现在会被正确拒绝。

### W1.3 最小设计边界（先在 RESULTS 写简短设计，再直接实施）

优先使用一个**纯派生的明确交付对象约束**，复用 state 中的 authority 来源、路径规则和 admission：

1. 输入仅为当前 Goal 的 `created_from_fact_ids` 所绑定的真实 USER_MESSAGE 原文，含已消费 correction；不从最终 coverage、模型摘要、工具结果、网页、SPEC 的未受信任正文或任意历史消息反推用户授权。
2. 只识别用户直接提出的、带精确 workspace-relative 文件路径的正向交付要求。有限规则可沿用已有显式 process 要求的做法；不要企图完整解析自然语言。识别范围与未支持情况写清楚。
3. 判别必须区分“输出/需要实现的文件”与“阅读输入、参考、例子、引文、禁止修改”。不能收集所有路径然后强制写入，也不能把这个完成约束当作工具权限。
4. 将约束与**当前** admitted filesystem 目标、当前版本证据对照。缺少明确对象或证据时，完成门给出具体的缺口；没有合法来源的泛化 coverage 不能填补缺口。
5. 优先在完成检查与只读投影中从现有 durable facts 派生，不增加 checkpoint 字段或新 Runtime owner。若确需落入已有 proposed criterion，仍使用现有结构/revision/准入路径，不允许模型自行铸造 admission。
6. 模型按缺口在同一主 loop 继续，通过正常审批、文件工具、执行验证和最终读回闭合。测试不预填正确 criterion，不替模型补文件。
7. correction 新增对象则约束生效；明确撤回/替换旧对象则按该指令更新，沉默或仅修改无关要求不能清空其它对象。未消费 correction 不提前生效。旧活动 checkpoint 重开后按当前 authoritative facts 得到同一约束；已终结历史记录不批量重判/迁移。
8. 对有限规则无法识别的隐含要求，保留现有模型语义职责与独立验收；不得声称这些要求已被该规则确定性证明。若无法在这些边界内修复已冻结反例，报告 W1 的具体设计阻塞，不能另开 NLP 平台或悄悄降低验收。

这里冻结的是行为边界与最小实现方向，不规定正则表达式。实现者必须先用下面判别矩阵检验规则，而不是靠多加匹配词逐例硬凑。若需要改变完成合同、引入新的持久协议或扩大授权，先报出具体差异，不能自行扩大。

### W1.4 判别与行为验收矩阵

| 输入/场景 | 必须观察到的结果 |
| --- | --- |
| 原 P1 输入原字节；draft 只提 service；非空泛化 claim 后不再写 CLI | 未 `VERIFIED_DONE`，反馈缺 CLI 交付对象/当前证据，不是只说 coverage 为空 |
| 把项目/文件名系统性改名，如 `toolbox/runner.py` 必须支持同样输入；同样遗漏 | 同样拒绝，不得匹配 D04/retry_app/cli.py 专名 |
| `更新 app/worker.py；app/command.py 必须使用相同配置`；等义英文直接文件要求 | 两个明确交付对象不能因草稿遗漏而消失 |
| `阅读 SPEC.md，修改 app/worker.py` | SPEC 不变成必须写入的输出；worker 是明确交付对象 |
| `参考 docs/example.py，不要修改它；更新 app/worker.py` | 引用/禁止对象不被强制修改，也不产生复用权限 |
| 用户只是在引用日志/代码块中的 `修改 app/other.py`；相同文本来自 TOOL_RESULT | 不铸造用户交付要求；沿用非权威来源边界 |
| 已正确的目标无需改内容 | 使用现有真实读回/`confirm_file` 或已支持的显式确认链取得有效证据；不能为了充数改写相同文件 |
| 完整 service+CLI 实现与有效证据 | typed `VERIFIED_DONE`，独立业务两项与七项补充检查全 true |
| 后续写入使旧验证失效 | 原 freshness 拒绝保持；按已有刷新路径补齐后可完成 |
| 合成用户新增/撤回要求、暂停、新 store 重开 | 约束与当前事实/revision 一致，不自动增加执行权限，不重放效果 |

最少新增一个“后续永不补 CLI”的负例和一个改名同构负例。保留现有空 coverage 测试，但把它的说明纠正为“空声明拒绝及后续补做链可运行”，不再声称它证明产品自行识别遗漏。

“已正确无需改写”测试证明不会产生多余写入，不证明对任意错误内容可以靠读一次就验收通过。完整正例和真实 E1 仍必须通过冻结外部业务检查。业务错误而产品声称完整成功时，记录失败，不解释成“只是模型的问题”。

### W1.5 收尾与 blocked 指引

- 完成工作/可能写入的测试 → 必要的最终读回 → completion claim；不要要求模型在最终读回后又执行一个使其失效的验证。保留所有既有证据约束。
- `derive` 成功只说明已接纳的证据可导出；不能据此断言不存在尚缺的明确交付对象。完成与 blocked 指引应复用同一缺口判断，不复制两个分歧的规则。
- 先构造“service 已有证据、另一明确要求存在 durable blocker”的完整合成反例并核对已有拒绝守卫。只有实际误拒被复现，才改 blocked 分支；若原守卫已经正确，保存该证据，不为猜测增代码。无依据乱报 blocked 的既有拒绝与 no-progress 界限保持。

W1 停止条件：上述负/正例与相关回归通过，明确写出规则覆盖边界。没有业务假完成的承诺不能超出实测范围；真实 E1 在 G 中验证。

## W2｜精确文件授权要能在普通任务中使用

### 冻结方案

保留现有 Goal target 精确授权路径。在 targets 为散文的任务里，增加**当前 Goal 下已有 Runtime 准入/实际用户批准来源的精确文件候选**；不把任意 pending path 自动提升成候选。

- 新 Goal 的提示明确：已知文件用精确相对路径，散文放 outcome/scope。但提示修改不是 W2 的唯一修复。
- 第一次普通 `y` 只批准一次，不创建租约。现有 `_admit_approved_file_criterion` 已能建立精确文件的 Runtime 绑定。
- 后续同一文件的 pending approval 可基于该当前准入候选展示 `/approve-goal-target`。用户再次**显式 opt-in** 后才通过现有 `_mint_goal_target_authorization` 铸造租约。
- 当前准入候选是可信 Runtime 状态，不可仅依据模型提供的 criterion 名字、description、未确认 digest 或历史文本。沿用当前 Goal/revision/workspace 约束；若当前状态不足以证明来源，就不展示选项，不补造历史。
- 显示、解析、执行用同一个 scope 判断。当前 request identity/digest 和 displayed snapshot/CAS 绑定不变。
- 目录授权仍只来自已有明确目录 target；本包不扩大目录分支。文件授权不覆盖 shell/process、不推断父目录。
- 同工具、同精确路径、60 分钟、16 次、修订失效、终态关闭与显式撤销均保持。默认 `y` 与 `no` 语义不变。

触碰：`state._goal_target_authorization_scope` 与必要的既有准入查询、共享 views、CLI/context 指引及现有测试。没有理由迁移所有旧 Goal 或添加第二张权限表。

### 真正的完整正例

散文 targets → 同一主 loop 首次提出安全普通文件 → 用户 `y` → Runtime 绑定该文件 → 再次同工具写同文件时默认提示出现精确选项 → 用户 `/approve-goal-target` → 第三次同范围执行复用 → 当前任务正常结束。

不能只手填 `goal.targets=("file",)` 或手造 admitted criterion 后测试 parser。至少一个用例必须从首次真实 `ResolveApproval` 开始，走真实 Runtime 与真实 checkpoint/reopen。

### 必要负例

无既有绑定的任意新 pending path不可复用；普通 y 不自动产生租约；换文件/工具/Goal/revision/workspace、过期/耗尽/撤销后拒绝；敏感路径、符号链接、相邻前缀路径、父目录猜测不放行；提示后状态漂移 fail closed。TUI 若复用同一 view，运行受影响适配测试，不重做 UI。

W2 以“路径实际可用且安全边界保持”验收，不指定审批必须降到某个数字。真实旅程分开记录单次审批和显式复用选择。

## W3｜验收驱动不能替产品催促或误判

### 已独立核实的缺陷

1. normal 会注入 correction，还在 REQUIRED_EVIDENCE 中要求 `correction_injected`。因此一个没有额外纠正、已经 typed 完成且业务全过的 normal 样本反而被判 incomplete。
2. normal/staged/resume 可以自动发“继续当前任务”或救场 `/resume`，不能用这种轨迹证明无催促闭环。
3. journey 的 `--max-resumes`、`--max-consents` 未传入 run 子进程；仅给外层加 `--max-resumes 0` 不生效。
4. evaluator 遍历传入 supplemental 字典，没有锁定完整预期集合；修本文件时顺带补缺键/空集合/非 bool 的失败断言，不能改变七项检查的语义。

触碰仅限 `scripts/run_task_trust_d04.py`、现有 driver tests 与 RESULTS；实际模型暴露的产品原因回到 W1/W2 或其同一收尾链修复，不按猜测重写架构。

### 具体改动

- normal：完整原 SPEC，一次初始输入，必要治理决定；不注入、不要求 correction evidence；到需“继续”的 idle 或 limit 时直接如实 incomplete。
- staged：仅冻结的一条新 correction、一次计划内 pause/exit/new PID resume。不得额外业务提醒、主动补文件或自动预算救援。
- journey→run 的干预上限必须按相同值传递，独立于 provider 是否 fake。测试实际子进程 argv/事件，不只测试 parser。无需新建通用调度接口。
- `_consent` 可按本次明确授权的合成文件策略选择显式精确复用；必须验证当前提示/投影确实有候选。不能无条件对任意审批 auto-approve，也不允许审批父目录或其它工具来节省交互。
- staged 的新增要求证据至少包括：纠正前 alias 尚未全部满足、纠正 fact durable 且进入当前来源、Goal revision 真正推进、当前义务/coverage 引用该来源、实际新 PID、恢复有进展、最终 alias/歧义检查通过。只增加 state revision 不够。
- typed 完成、完整外部业务、完整补充检查、预算与本次过程证据必须联合判定。不要让 driver 合成产品终态，不根据一句文字判断完成。
- 只使用已有事件/ledger 给本次新合成样本记录有限诊断：completion/control 拒绝原因与次数、验证失效、重复无进展、物理请求数及干预分类。不能记录 key、原始敏感响应或读取旧运行日志。

### 必须有的 driver 回归

normal 成功且没有 correction→PASS；业务过但未终结→incomplete；需催促→不发“继续”且 incomplete；缺任一补充键→失败；未新增/消费 correction、仅 state revision 增加、未新 PID、恢复未推进→staged 失败；外层 0 次恢复传到 child 且实际不发生额外 resume。

离线 driver 绿后再进入已获授权的真实 E1，不能边消耗 API 边猜 driver。真实 normal 仍未收尾时，保留证据并按具体原因做一处最小修复，预算边界与失败停止规则见 VALIDATION；不提高默认 40 次预算硬跑。

## G｜最终候选与最短日用路径

不是第四轮功能开发。完成 W1–W3 后按 VALIDATION 建新 manifest/wheel/安装来源证明、运行最小 installed 集合、集中 full gate、有授权才做两个真实样本。

现有 driver 会在仓库根加入源码路径并启动子进程，**它不是 installed-real driver**。本包允许“同一冻结源码的真实 E1 + 对应 wheel 的独立安装态证明”，无需为了名词重写整套 driver；必须分别报告来源，不能把装了 wheel 的解释器当成安装态执行证明。

最短用户旅程：isolated setup/启动与错误提示 → 普通任务完成 → `/new` 第二任务 → 安全暂停 → 退出 → 新进程恢复。指南只写这条明确支持路径，使用与当前授权/验证一致的精确模型配置；不承诺全 provider 或跨平台。

更新 `README.md`、`docs/guides/daily-use.md`、`docs/architecture/CURRENT_CAPABILITY_STATUS.md` 的必要当前摘要，并更新唯一 RESULTS。保留历史证据身份，去掉将旧 wheel/3873/41 节点成绩冒充当前身份的文字。无需重写所有历史文档、重绑全部 seal。

## 绝对不在本包内

Browser D06、Scheduler host、登录项、桌面控制、跨平台适配、Memory 语义升级、MCP/Skill 扩展、并行 Agent、TUI 重做、凭据托管、通用评测/遥测平台、按行数拆巨石文件、第二 Runtime loop、默认涨预算、自动放权、历史状态批量迁移、提交推送发布。

满足 W1–W3 与当前授权下可执行的交付门后停止。只缺 API 授权时可交付“本地/安装完成，真实层待授权”；真实业务/终态仍失败时不能宣布日用 beta 已放行。
