# Codex 独立执行方案草案（送审快照，不是最终入口）

日期：2026-10-17。任务：把已确认的四个缺口收敛成普通 coding agent 能执行的修复包。
这里只规划，不实现、不提交、不发布、不使用产品 API；本稿接受 Oracle 5/5 交叉审查后才定稿。

## 产品目标与现状

首版只承诺 macOS、单用户、CLI、当前工作区的有界文件/编码任务。保留已有内核和治理，不新增平台能力。
当前 HEAD 是 main 的 `0cc0db1ddbf6d2e9c9526e9588d66e80831b6640`，但真正被审计的是其上的 dirty 工作树：17 个 tracked 文件有上一执行者的改动。不得 reset/checkout 丢掉它们；旧包已大部执行，不能从 HEAD 重做。

当前独立证据：285 focused；3947 passed / 1 skipped / exit 0（672.22s）；ruff/diffcheck 通过。skip 是显式 launchd host gate。四个缺口仍可独立离线重现。因此旧 full PASS 不是发布通过，也不是后来代码的证明。
原审计目录 `docs/audits/2026-10-17-post-closeout-product-audit/` 的 AUDIT、probes.py、PROBE-RESULTS、IDENTITY 必须保留，不改历史反例来造 Green。
唯一可变当前记录仍是 `docs/handoffs/2026-10-11-product-reliability-closure/RESULTS.md`。本包是冻结指令，不能再生第二个 RESULTS。

## 冻结的三包与顺序

顺序 A → B → C。每包只跑 focused；所有产品/driver 修改稳定后一次 full，再物化安装。真实验证若发现本范围内缺陷，先最小复现再修复，刷新失效证据；不能拿旧 wheel 证明新源码。

### A：完成门既不能漏文件，也不能凭空加任务（F1+F2，P1）

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
| Update Python to 3.12 | 不包含 3.12 |
| Implement SPEC.md requirements / 根据 SPEC.md 实现需求 | 不包含 SPEC.md |
| 修改 SPEC.md 的说明 | 包含 SPEC.md，不能按 basename 全局排除 |
| 解释“创建 app/example.py；修改 app/other.py”的含义，不要修改任何文件。 | 不包含引文路径 |
| 日志显示：创建 app/old.py；请说明原因，不要修改文件。 | 不包含日志路径 |
| 如何修改 app/config.py？ / How do I update app/config.py? | 不因说明性问题产生输出义务 |
| 阅读 SPEC.md，然后修改 app/config.py | 只包含 app/config.py |
| 修改 app/live.py；下面代码块只是示例，勿执行：围栏代码块内创建 app/demo.py | 包含 live.py，不含 demo.py |
| 修改 /tmp/out.py / 修改 ../out.py / 修改 dir/../out.py | 不把整条非法路径或截取后缀 out.py 当作有效工作区路径 |

最小设计约束：

- 先在整条 authority fact 内识别/遮蔽当前支持的跨分句引文、围栏代码块，再分句；inline backtick 路径仍可表达真实请求。不把任意所有引号都当非权威，也不新增通用 NLP 框架。
- token 边界允许汉字直接邻接当前受支持的 ASCII 相对路径；保留完整路径验证，不能从 unsafe token 中捞合法后缀。
- 角色按上下文判断，输入 SPEC.md 不等于永远不许修改 SPEC.md；对本表的有限、可区分语法建立正负对照。
- 只取 Goal.created_from_fact_ids 已消费绑定的真实 USER_MESSAGE。模型/summary/tool 内容不能生出 authority。保留 correction 的新增、点名撤回、沉默不清空、未消费不生效、再新增语义。
- 保留 completion 与 blocked guidance 使用同一缺失集合。若修改建议措辞，仅解释现有 proposal/admit/verify/confirm 流程，不新增自动准入/授权/副作用。
- 已正确文件可 confirm-only，不为准入强制改写。既有 scripted 正例已过，真实 r3 有一次重复 claim 到 fatal 的记录，根因未明；只在当前可重现证据支持下做局部修复，不假设存在“强制写入 guard”。
- 不新增持久 schema、第二 model judge、权限、全局 path registry；不删完成门、不降低 grader。

完成条件：上述表的参数化单测 + 两个完整 Runtime 反例转绿 + 双文件正常完成正例 + confirm-only 零改写 + correction/reopen/freshness 回归。不会任意语义都识别，README 明确这是有限下界。

### B：pending 外发确认的 yes/no/空回车在恢复前后完全一致（F3，P1）

真实可达形状：SubmitMessage → PauseGoal → ResumeGoal 后，request 非空、receipt=None、active_run=None、Goal=GOAL_READY。
当前 y 正确，n/no/否 却成为 SubmitMessage(goal_correction)，空回车被略过，而提示是 [y/N]。

主要代码 `agent/cli/app.py`、`agent/cli/render.py`，必要时复用 runtime 的只读 predicate；不得让 CLI 推进状态。已有 `acknowledge_provider_disclosure` reducer 的 exact digest、CAS 与 legal-state 校验仍权威。

冻结行为：

- 活跃 AWAITING_DISCLOSURE 与上述恢复形状，在 request 非空且 receipt=None 时为同一个 answerable pending 决策。
- `y/yes/是` 映射现有 AcknowledgeProviderDisclosure；pending snapshot/token/digest 不漂移绑定。
- `n/no/否`、空回车与纯空格输入在这个 pending 决策中均等于拒绝：安全退出当前 CLI，不提交业务消息，不生成 receipt，不触发新的 provider/工具请求，保留任务供将来显式恢复。
- 文案为“本次待确认内容未发送，任务已保留，退出当前会话”（按产品英文约定落地）。不能笼统声称历史上 Nothing was sent：此前别的请求可能已发送。
- 无 pending 时空回车保留当前忽略行为。PAUSED、已 receipt、普通 runnable、stale request 不被此分支接管；拒绝不顺便成为 cancel。
- `/exit`/EOF/中断保持既有安全退出，不合并 tool approval 与 provider disclosure。data classes/destination/model 变化仍要新的精确确认。

测试矩阵：活跃/恢复 pending × 肯定/否定/空白；PAUSED/已有 receipt/无 pending；同一 snapshot 渲染与解析；stale revision/digest；经历 checkpoint 落盘、新进程恢复的 pending 决定。检查相对执行前的请求数、tool effects、USER_MESSAGE correction、receipt 增量均为零（否定路径），不要只看文字。

首发选择固定为 CLI-only。TUI 当前 active=None 会漏显示该决定，本包**不修 TUI**；README/日用默认安装去掉 [tui] 推荐，TUI 标实验与该限制，不宣称 parity。保留现有 TUI 代码、依赖可选项与测试，不删除能力、不重设计 UI。共享函数若触及 TUI 则跑现有适配回归。

### C：验收器纠正绑定 + 一个当前可安装候选的有限证明（F4，P2/发布门）

先修 `scripts/run_task_trust_d04.py:_consumed/_consumption_view/_staged_evidence` 及其测试：

- `version_changed` 必须是同一 Goal 的数值 revision strictly greater，不能 goal_changed OR state_changed；bool 不作为 int，缺失/字符串/None 必须 fail closed。
- injected_fact_id 必须与 consumption.fact_id 同一条非空 ID，且分别存在于 durable correction facts 与已消费 created_from_fact_ids；不是两个不同 ID 各自存在就通过。
- producer 记录必要 goal_id before/after，evaluator 比对同一 identity；最终恢复 Goal 与该 Goal 一致。state revision 另列诊断，不可替代 Goal revision。
- 不信任 self-reported true flags；由原始标识与版本计算。旧证据缺字段标 incomplete，不加 compatibility fallback。
- 负对照：只有 state 增长、wrong correction、wrong Goal、缺 revision、bool/string revision、回退 revision、同值 revision、标志 true 但数值没变；一个完整合法正例仍过。
- 保留七键 exact true、未知/缺键/non-bool 拒绝，normal 零 correction/零继续/零救场，staged 只有一条计划纠正和一次新 PID 恢复；原 SPEC/grader/manifest 不改。

冻结并交付：

1. A/B/C focused 稳定后 `git diff --check`、ruff、full 集中一次。full 不应每个小改重复。
2. `scripts/build_candidate_manifest.py --out <唯一新父目录>/candidate --manifest <同父目录>/manifest.json`。candidate 叶子必须原先不存在，父目录在仓库外；不删除旧输出。显式纳入新增公开文件，不扫 ignored/private，不用 git add .。
3. 同一源码 manifest 构建 non-editable wheel，记录 wheel SHA，新隔离 venv，在源码外中立 cwd 运行 installed-focused。复用 `_019_installed_pytest.py`；其无 --test-node，真实参数是 --installed-site/--test-tree/--report-path/--origin-log/--basetemp/--required-module，用局部 PYTEST_ADDOPTS 的 -k 精选并核对 node 集合。验证父子进程 module origins，不把源码 fallback 当安装通过。
4. 安装层做 setup（无真实 key）→ 小文件任务 → VERIFIED_DONE → /new → 第二任务，以及恢复拒绝/同意。现有 scripted/MockTransport 路径即可，明确不是 real model。不重跑安装态全库。
5. 真实层在取得当前权限后做 normal fresh、staged pause/new-process resume、already-correct 三个有界样本。already-correct 可接 normal 成功产物的新任务，不再收费重复造 fixture；模型只读验证即可，期望无写入、typed done，不由 operator 添加“可以不改写”提示。
6. 现有 D04 driver 从 source 导入；可以用与 wheel 相同 manifest 的干净候选运行真实层并分别标明 source-real 与 installed-offline，不为“installed-real”名词重写 runner。但不能对用户冒称安装物真实模型已验证。请 Oracle 判断这是本次知情邀请 beta 的足够界限，还是应最小适配安装来源。
7. 当前 summary/README 支持矩阵一致，保留旧历史并明确被哪次复审替代。不刷新所有 015–019 seals、不承诺全部能力可用。

真实授权/预算建议（不代表当前已经批准）：仅指定的合成 workspace；只读取用户明确命名的凭据环境变量/注入来源；key 永不进命令字面量、日志、文档。单样本最多40物理请求，三个样本累计最多80，累计墙钟60分钟；失败/重启跨进程累计。先normal，通过后staged，再already-correct；到任何上限即停并如实 incomplete。401/429/额度耗尽不轮换 key、不换 provider；修复后重跑同样占累计限额。不自动提高 max_tokens/budgets。

没有当前 API 授权时完成 A/B/C 本地与安装门，真实层标 BLOCKED_AUTHORIZATION，汇总一次请用户授权；本包不能授权读取 Pi/Claude 配置或旧私有记录。不能因为没有 key 就停止所有安全工作。

## 不做与停止条件

不做新的 Browser、Scheduler、MCP、Skill、Memory、多 Agent、跨平台、桌面、GUI、自动更新；不按行数拆巨石；不引入泛化 evaluator 平台；不 commit/push/tag/merge/release。
本地修复+安装证据与有界真实结果分别结论。真实未授权不标 release-ready；真实业务对但未 done 标 INCOMPLETE_CLOSURE；漏做却 done 标 FAIL_FALSE_COMPLETION。范围外发现只登记最小证据，不顺手实施。
三包完成或到真实授权/外部阻塞边界即交接，不自动开启第四轮。
