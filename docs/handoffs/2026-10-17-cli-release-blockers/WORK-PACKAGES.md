# 三个工作包（2026-10-18 最终合同）

本文件只规定实施，不证明修复已经完成。A → B → C；不重新做旧包已完成部分。

## A：完成门既不能漏文件，也不能凭空加任务（F1+F2，P1）

用户结果：直接点名的输出文件不能因中英空格差异而漏验；规格输入、解释引文、版本号不变成必须生成的文件。不是任意自然语言保证。

主要代码：`agent/runtime/state.py:260–307,447–534,1928–1943`，以及 `agent/runtime/loop.py` 中共用的 blocked guidance。现有测试 `tests/continuity/test_contracts.py`、`tests/acceptance/test_task_trust_completion.py`。

先固定两个完整生产 Runtime 反例：

1. provider 只做 service，给非空泛化 coverage。D04 原任务有空格时拒绝完成；删除“命令行适配器 retry_app/cli.py”中的空格后，当前竟 VERIFIED_DONE，CLI 业务仍失败。修后两者均不得完成，且诊断点名缺失文件。
2. 合法目标文件已正确，用 confirm_file 获得当前证据；附带解释跨分句引文“创建 app/example.py；修改 app/other.py”，明确不要改示例。当前被要求补两个示例 criterion；修后不产生这些义务、零额外写入、合法目标可完成。

行为矩阵（列的是完成下界，不是权限）：

| 输入 | 当前 Goal 下界必须包含/排除 |
| --- | --- |
| 修改 app/config.py / 修改app/config.py / 修改 `app/config.py` | 均包含 app/config.py |
| 命令行适配器retry_app/cli.py 必须使用同一个值 | 包含 retry_app/cli.py |
| Could you update app/config.py? / Would you update app/config.py? | 包含 app/config.py（礼貌请求不是解释疑问） |
| Could you please update app/config.py? / Would you please update app/config.py? | 包含 app/config.py |
| Could you explain how to update app/config.py? | 不包含 app/config.py |
| Update Python to 3.12 | 不包含 3.12 |
| 修改 app/v3.12/config.py | 包含该完整路径，数字版本目录不是排除理由 |
| Implement SPEC.md requirements / 根据 SPEC.md 实现需求 | 不包含 SPEC.md |
| 修改 SPEC.md 的说明 | 包含 SPEC.md，不能按 basename 全局排除 |
| 解释“创建 app/example.py；修改 app/other.py”的含义，不要修改任何文件。 | 不包含引文路径 |
| 日志显示：创建 app/old.py；请说明原因，不要修改文件。 | 不包含日志路径 |
| 如何修改 app/config.py？ / How do I update app/config.py? | 不因说明性问题产生输出义务 |
| 阅读 SPEC.md，然后修改 app/config.py | 只包含 app/config.py |
| 根据 SPEC.md 的说明修改 app/config.py | 只包含 app/config.py |
| 日志显示：创建 app/old.py；修改 app/other.py；请说明原因 | 两个报告对象都不包含 |
| 日志显示：创建 app/old.py；请修改 app/live.py | 只包含 app/live.py |
| 下方冻结的真实换行/围栏样本 | 只包含 app/live.py，不包含两个示例文件 |
| 修改 /tmp/out.py / 修改 ../out.py / 修改 dir/../out.py | 不把整条非法路径或截取后缀 out.py 当作有效工作区路径 |

围栏样本的实际输入（外层四反引号仅为本文件排版，不属于输入；内层三反引号属于输入）：

````text
修改 app/live.py；下面代码块只是示例，勿执行：
```text
创建 app/demo.py
修改 app/example.py
```
````

最小设计约束：

- 先在整条 authority fact 内识别/遮蔽当前支持的跨分句引文、围栏代码块，再分句；inline backtick 路径仍可表达真实请求。不把任意所有引号都当非权威，也不新增通用 NLP 框架。
- 围栏测试使用真实换行和三反引号，不用“代码块内”这段说明文字代替语法。日志只覆盖本表“日志显示：”报告：范围跨分号继承，遇明确新请求“请修改…”终止，不扩展成任意日志理解。
- token 边界允许汉字直接邻接当前受支持的 ASCII 相对路径；保留完整路径验证，不能从 unsafe token 中捞合法后缀。
- 补有限完整 token 负控：`dir/out.py/../other.py`、`dir/out.py\x`、`C:\tmp\out.py`、`https://host/out.py`、`/tmp/中文out.py`、`app/config.py?x=1` 均不截出合法子串。句末问号的礼貌请求仍通过；不能先按问号切掉非法附尾。这里是新回归要求，不冒称这些输入都已在旧 probe 中复现。
- 角色按上下文判断，输入 SPEC.md 不等于永远不许修改 SPEC.md；对本表的有限、可区分语法建立正负对照。
- 有限支持 `Could/Would you [please] + 直接编辑动词 + PATH`，解释型 `explain how to` 仍排除，不直接删整个 question guard。直接修改 PATH 本身优先于“的说明”输入后缀；不按文件是否存在、模型是否写过或 basename 黑名单推导 authority。
- 只取 Goal.created_from_fact_ids 已消费绑定的真实 USER_MESSAGE。模型/summary/tool 内容不能生出 authority。保留 correction 的新增、点名撤回、沉默不清空、未消费不生效、再新增语义。
- 上述非权威来源既不能新增，也不能撤回当前真实义务。不要改 process 要求识别的整体语义；若复用 helper，增加不受本次文件分类影响的回归。
- 保留 completion 与 blocked guidance 使用同一缺失集合。若修改建议措辞，仅解释现有 proposal/admit/verify/confirm 流程，不新增自动准入/授权/副作用。
- 已正确文件可 confirm-only，不为准入强制改写。既有 scripted 正例已过，真实 r3 有一次重复 claim 到 fatal 的记录，根因未明；只在当前可重现证据支持下做局部修复，不假设存在“强制写入 guard”。
- 不新增持久 schema、第二 model judge、权限、全局 path registry；不删完成门、不降低 grader。

完成条件：上述表的参数化单测 + 两个完整 Runtime 反例转绿 + 双文件正常完成正例 + confirm-only 零改写 + correction/reopen/freshness 回归。随后停止扩规则。README 明确这是有限下界，不承诺任意隐含要求、日志/引号、Unicode 文件名、Windows 路径或 URL 的语义识别；支持汉字邻接 ASCII 路径不等于支持所有 Unicode 路径。

## B：pending 外发确认的 yes/no/空回车在恢复前后完全一致（F3，P1）

真实可达形状：SubmitMessage → PauseGoal → ResumeGoal 后，request 非空、receipt=None、active_run=None、Goal=GOAL_READY。
当前 y 正确，n/no/否 却成为 SubmitMessage(goal_correction)，空回车被略过，而提示是 [y/N]。

主要代码 `agent/cli/app.py`、`agent/cli/render.py`，必要时复用 runtime 的只读 predicate；不得让 CLI 推进状态。已有 `acknowledge_provider_disclosure` reducer 的 exact digest、CAS 与 legal-state 校验仍权威。

冻结行为：

- 活跃 AWAITING_DISCLOSURE 与上述恢复形状，在 request 非空且 receipt=None 时为同一个 answerable pending 决策。
- 精确谓词为 `request != None and receipt == None and ((active != None and active.status == AWAITING_DISCLOSURE) or (active == None and goal != None and goal.status == GOAL_READY))`。恢复分支不可省略 `active == None`；render/yes/no/空白共用这一只读判断，Runtime 仍校验 action 合法性。
- `y/yes/是` 映射现有 AcknowledgeProviderDisclosure；pending snapshot/token/digest 不漂移绑定。
- `n/no/否`、空回车与纯空格输入在这个 pending 决策中均等于拒绝：安全退出当前 CLI，不提交业务消息，不生成 receipt，不触发新的 provider/工具请求，保留任务供将来显式恢复。
- 文案为“本次待确认内容未发送，任务已保留，退出当前会话”（按产品英文约定落地）。不能笼统声称历史上 Nothing was sent：此前别的请求可能已发送。
- 拒绝不写持久 DENIED，不清 pending，不发送 Pause/Cancel/Resume。重开时 Goal 已 ready 就直接展示同一 pending，不强迫再 `/resume`。
- 窄范围 PAUSED 保护：仅在 `active=None、Goal=PAUSED、request!=None、receipt=None` 时，裸 yes/no（包含原肯定/否定同义词）只提示先 `/resume`、不提交业务消息；空白仍忽略，`/exit` 正常退出。不是全局截获 no；这是同因负控，不宣称旧 probe 已证明 paused no 写入。
- 无 pending 时空回车保留当前忽略行为。已 receipt、普通 runnable/approval/recovery、stale request 不被孤儿分支接管；拒绝不顺便成为 cancel。
- `/exit`/EOF/中断保持既有安全退出，不合并 tool approval 与 provider disclosure。data classes/destination/model 变化仍要新的精确确认。

测试矩阵：活跃/恢复 pending × 肯定/否定/空白；PAUSED/已有 receipt/无 pending；同一 snapshot 渲染与解析；stale revision/digest；经历 checkpoint 落盘、新进程恢复的 pending 决定。检查相对执行前的请求数、tool effects、USER_MESSAGE correction、receipt 增量均为零（否定路径），不要只看文字。

首发选择固定为 CLI-only。TUI 当前 active=None 会漏显示该决定，本包**不修 TUI**；README/日用默认安装去掉 [tui] 推荐，TUI 标实验与该限制，不宣称 parity。保留现有 TUI 代码、依赖可选项与测试，不删除能力、不重设计 UI。共享函数若触及 TUI 则跑现有适配回归。

## C：验收器纠正绑定 + 一个当前可安装候选的有限证明（F4，P2/发布门）

先修 `scripts/run_task_trust_d04.py:_consumed/_consumption_view/_staged_evidence` 及其测试：

- `version_changed` 必须是同一 Goal 的数值 revision strictly greater，不能 goal_changed OR state_changed；bool 不作为 int，缺失/字符串/None 必须 fail closed。
- injected_fact_id 必须与 consumption.fact_id 同一条非空 ID，且分别存在于 durable correction facts 与已消费 created_from_fact_ids；不是两个不同 ID 各自存在就通过。
- producer 记录必要 goal_id before/after，evaluator 比对同一 identity；最终恢复 Goal 与该 Goal 一致。state revision 另列诊断，不可替代 Goal revision。
- “同一 Goal”不能只比较可能重复使用的可读 ID：现有 observation 可只读投影 `state.conversation_id` 与 `goal.workspace_identity_digest`；与 goal_id 组成这次样本的身份，贯穿注入前、消费、暂停落盘、恢复开始与最终观察。仅增加本轮验收 JSON 的观测字段，不改产品 checkpoint schema，不建立新身份注册表。
- 不信任 self-reported true flags；由原始标识与版本计算。旧证据缺字段标 incomplete，不加 compatibility fallback。
- 负对照：只有 state 增长、wrong correction、wrong Goal、缺 revision、bool/string revision、回退 revision、同值 revision、标志 true 但数值没变；一个完整合法正例仍过。
- 保留七键 exact true、未知/缺键/non-bool 拒绝，normal 零 correction/零继续/零救场，staged 只有一条计划纠正和一次新 PID 恢复；原 SPEC/grader/manifest 不改。

### C.1 精确观测合同（验收 JSON，不是产品持久 schema）

沿用现有 `observe`、`pre_injection`、`consumption`、`start_observation`、`final_observation` 与 operator events，不建新 evaluator 平台。缺少的字段只从真实状态/进程记录补采集：

| 观测时点 | 最低原始字段 |
| --- | --- |
| 首次建立 Goal、注入前 | conversation_id、goal_id、workspace_identity_digest、goal_revision、state_revision、created_from_fact_ids、correction_fact_ids；实际 workspace/state-root 路径 |
| 注入持久与消费 | 本次新增 fact 的 id/kind/control/text（仅本次合成输入）；消费前后 Goal ID/版本、消费时 created_from_fact_ids；保留同一 conversation/workspace 绑定 |
| 消费后暂停、A 退出前 | Goal/status/两个 revision/来源与纠正 fact 集合/active 状态、效果观察、实际 pause 事件及顺序、A PID 与退出结果 |
| B 首次加载、Resume 前 | 同上身份与 paused 快照字段；B 实际 PID；使用的 checkpoint/state-root 路径 |
| 计划 Resume 后、最终 | 同一身份、Goal 状态/版本、来源、效果、实际 resume 事件与终态；候选/wheel/解释器/module origins 单列 |

判据（使用现有 `completed/incomplete + failures`，不新增产品 RunStatus）：

1. 锁定初始 Goal G 与 composite identity；ID 是非空字符串。revision/计数必须 `type(value) is int` 且非负，PID 为正整数；fact ID 集合必须为合法非空字符串列表，缺失不默认成“够用的空集合”。
2. C=`injected_fact_id`，它对应本次实际新增 USER_MESSAGE、control=goal_correction、text 等于计划 CORRECTION；不在 pre_injection.correction_fact_ids。不得借用旧 correction。
3. C 等于 consumption.fact_id，分别证实 durable correction 与进入 G.created_from_fact_ids；消费前 revision 等于 pre_injection.goal_revision，消费后严格增加。布尔摘要不能覆盖原始数值；摘要与原始值矛盾也要明确失败。
4. 首次 Goal、pre_injection、consumption、A paused、B start、Resume 后、final 的 composite identity 全一致；C 在消费后的 paused/reopen/final 来源中持续存在。事实持久与消费可在同一真实快照中观察，不强造 Runtime 中间停点。
5. 从实际输入/action 顺序证实消费后才发 Pause；A 的真实终态 paused 且进程退出；B 为不同真实 PID，Resume 前读到 A 的同一 paused checkpoint。conversation/workspace/state-root/Goal、Goal/state revision 与关键 fact 集合一致；存在一次计划 Resume。不要要求 active_run ID 相同，合法恢复会创建新的 run。
6. 保留本 staged 的 `resume_advanced = 文件效果数增加 OR Goal revision 增加`，但基于同一身份与合法整数。它不是所有任务必须写文件的规则，不能套到 E3。效果总数本身不证明零重放，保留既有 effect identity/receipt/UNKNOWN 回归，不增加真实 UNKNOWN 样本。
7. 七键 K 固定为 `transient_new_name, legacy_alias, default_single_attempt, bounded_attempts, conflict_rejected, negative_invalid, cli_both_names`。注入前与最终都先验证 exact key set 与 bool 类型；注入前保留已有至少一次文件效果且 legacy_alias/cli_both_names 至少一项 false，不以缺键冒充 false、不擅改为两项都 false；最终全部 is True。
8. normal/staged 的计划纠正、恢复、催促次数从实际 input/action events 校验，不只信恒为零的计数字段。原业务/授权 TASK-MANIFEST 与 frozen grader 不改；新构建的 source-manifest 是新的身份文件，不混淆这两种 manifest。

以一个合法 staged fixture 做逐字段负变体：state-only 增长；旧/错/仅持久未消费 correction；错 Goal/会话/工作区；缺失/bool/string/回退/同值 revision；先 pause 后消费或 pause 旗标伪真；同 PID/另一 checkpoint；丢失 C；缺计划恢复；非法七键。都必须具体失败；完整合法 staged 和无 correction 的 normal 仍过。不得把这些新增负控宣称成旧真实旅程都曾失败。

### C.2 现有 driver 的最小安装装配（同样三个真实样本，不另开一套）

最终 beta 门采用 **installed-real**，不以 source-real + installed-offline 代替。先离线验证装配，再用获批 API；缺授权时本地和 installed-offline 仍可交付。

允许仅在现有 `scripts/run_task_trust_d04.py` 增加固定用途安装参数 `--installed-site` 与 `--origin-log`（run/journey 成对提供，并传入子进程；这是本包要新增的测试参数，当前 --help 尚无它们）。不增加产品 CLI 参数、生产 loop 或新 runner。

- 在任何 `main/agent/first_agent_skill_runner` 导入前，复用 `scripts/_019_installed_pytest.py:install_guard`。先核对没有这些产品模块被源码预加载；发现污染就失败，不删除 sys.modules 后假装干净。
- driver/grader/fixture/授权 guard 可来自公开候选测试树；产品模块仅可来自指定 wheel 的 site-packages。ROOT 只供定位测试资料，不得成为产品 fallback；既有 import guard 正是此边界，勿复制一套解析器。
- 父子进程都在源码树外的同一中立 cwd 启动；`_child` 在安装模式不再 `cwd=_ROOT`。显式透传安装参数，使用本次 venv 解释器。记录每个实际进程的 sys.executable、main/runtime/CLI origin，均须在当前 installed-site 内。
- 传一半参数、site 错误、所需产品模块缺失、产品源码提前导入、父正确但 child 回落源码均 fail closed。加一组安装正例与这些有区别的负控，不扩成通用插件系统。
- 保留已有 source 模式供离线诊断，身份标 source，不可签本包 installed-real PASS。安装模式不能悄悄回退。
- 已正确 E3 复用 normal operator/固定输入与同一装配，只用新 state-root，不新增生产模式。真实失败触发条件见 VALIDATION。

如果实际入口无法靠这一局部装配接通，记录最小阻塞与证据；不得重写整个 runner/生产入口或拿 source-real 替代后宣称完成。先说明事实，需扩大范围时再请用户决定。


