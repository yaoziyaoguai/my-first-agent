# 编码自主性交付结果复审

## 结论与范围

上次回复“离线修复闭环已经完成”过宽，应更正为：**已有一批候选实现与回归通过，但仍有实现缺陷、验收设施缺失，以及当前候选真实任务未验证。**
`docs/handoffs/2026-09-13-coding-autonomy-repair/RESULTS.md:5–7` 的
`IMPLEMENTATION IN PROGRESS / REAL ACCEPTANCE NOT RUN` 才符合证据。

审计基于 HEAD `838cb2b66fbba674311d4d86fc7c4f4322fd8612` 之上的当前 dirty 工作树，不能把全部
未提交差异归为上一轮新增。本次没有修改产品实现、提交、推送、读取真实凭据或调用付费模型。
本报告中的“复现”指本次离线探针；“推断”指代码路径风险，尚未完成全入口复现。

本次采用 review 技能的 Standards / Spec 两轴独立审查，再核对 provider 官方协议和历史脱敏
Dogfood 报告。Graphify 图停留在 9 月 10 日，查询只得到历史定位线索；最新结论来自当前源码，
没有重建可能摄入私有内容的图，也没有用旧图替代当前代码证据。

## Standards 轴：工程边界

### S1 / P1 / 复现：开发服务的后代进程可以越过生命周期

- 位置：`agent/process/managed_web_child.py:47–49`。
- 直接 child 退出时 supervisor 立即返回，没有关闭同组后代。
- 实际离线探针：child 启动长寿命后代后退出；`supervisor_exit=0`；超过指定 2 秒 lifetime 后，
  `descendant_group_alive=True`。测试自有进程组已回收。
- 影响：用脚本或启动器派生服务后退出时，可能留下本任务进程；“父退出/期限到界自动清组”
  并未覆盖这条路径。与 `KERNEL_ARCHITECTURE.md:99` 的承诺冲突。
- 最小处理：直接 child 退出也完成同组清理与确认；补启动器退出、父退出、后代拒绝 TERM 的
  有界测试。不能按端口猜测并杀其他服务。

### S2 / P1 / 复现：默认持久化调用上限漏计压缩

- 位置：`agent/runtime/loop.py:4115`、`:1607`；默认值见 `main.py:226–229`。
- 压缩直接调用 provider，成功后只增加 invocation 局部计数，没有扣 durable `model_calls_used`。
- 使用现有 compaction fixture，设 `max_run_model_calls=1,max_model_calls=None`，得到
  `actual_provider_calls=2, reported_model_calls=1, status=completed`。
- 影响：默认 40 次不能被解释为包含压缩的全部物理请求上限；失败的压缩也存在漏记路径。
- 边界：显式配置 `TransportAttemptLedger` 的 HTTP 发送前总额度另有保护；该 ledger 在
  `main.py:1086–1093` 中是可选的，因此不能用它掩盖默认计数缺口。
- 最小处理：普通、压缩、child 和失败尝试的共同预算，在发送前持久化扣账；补耗尽及恢复反例。

### S3 / P1 / 代码推断：重启后清理事实可能无法闭合

- `agent/runtime/resource_lifecycle.py:68–71` 依靠 durable start/stop facts 配对。
- `agent/process/managed_web.py:429–440` 的退出清理只清内存 owner；重启后旧 `resource_ref`
  在 `:446–452` 被拒绝，无法按原 stop 路径补齐 receipt。
- 因而可能出现“实际服务已关，Goal 仍因旧资源未闭合而不能完成”。本次未完成完整 CLI 旅程，
  不把推断记成端到端 FAIL。
- 最小验证：启动服务 → 安全退出 → 重启选择旧任务 → 确认 ownership/资源已关闭 → 完成。
  如复现，添加受治理的恢复/核对动作，不能直接忽略旧 start fact。

Standards 轴共 3 项，其中 2 项复现、1 项推断；最严重类别是进程收尾与预算边界。未发现新增第二套
production model/tool loop，但这不表示已穷尽所有架构和安全问题。

## Spec 轴：检查、完成与验收

### C1 / P1 / 复现：两个验证命令相互作废

- `agent/runtime/evidence.py:1344–1350`、`:1379–1381` 把任意后续成功 process/sandbox 当作可能修改。
- `agent/runtime/state.py:2861–2867`、`:2915–2919` 又保留不同命令的 mandatory criterion。
- 两份合法、不同 fingerprint 的 ProcessReceiptV1 反例：

```text
commands A then B: A=False B=True
rerun A:           A=True  B=False
```

- 影响：任务要求分别执行测试和 lint 时，即使两者成功且未修改源码，也存在无法同时满足最终
  criteria 的路径。这正会表现为反复检查、无法收尾。
- 最小处理：分别表达操作事实与验证所覆盖的输入版本，允许同一最终输入上的多个验证共同成立；
  不靠重新跑完整套件或删除 mandatory criterion 掩盖问题。

### C2 / P1 / 复现：失败但已执行的修改不会使旧验证失效

- `agent/runtime/evidence.py:1368–1373` 对 `is_error=True` 提前返回 False。
- 已执行的非零退出命令由 `agent/runtime/tools.py:1517`、`:1537` 标为 error；error 不代表没有修改。
- 追加 `executed=True,is_error=True` 的后续 process fact 后，旧验证仍返回
  `process_with_later_failed_mutating_command=True`。
- 最小处理：按可能发生的副作用及输入版本判断，不能按 exit 成败决定 freshness。

### C3 / P1 / 复现：native sandbox 与文件证据仍接受修改前事实

- `agent/runtime/evidence.py:1418–1466` 未检查后续 mutation。
- 使用既有 sandbox verified-done fixture，在 receipt/read-back 后追加成功 `edit_file`，公共
  `REGISTRY.derive` 仍得到 `filesystem-digest:v1=True`、`native-sandbox-receipt:v1=True`。
- 这是 evidence 层的确定反例；本次未声称完整 CLI 已在真实文件上错误宣布完成。
- 影响：RESULTS 对“验证后再写会使旧 receipt 失效”的概括不完整。
- 最小处理：file、process、sandbox 对同一验证输入采用一致的失效规则，并补完整 Runtime 反例。

### C4 / P1 / 确认缺失：独立业务验收尚未实现

- `WORK-PACKAGES.md` 的 P0 要求物化 fixture、外置 grader、输入/动作/候选身份及记录器。
- `scripts/grade_coding_autonomy.py:42–112` 只是 JSON 记录校验器，正确地最多返回 `RECORD_VALID`；
  它没有执行独立测试。`tests/acceptance/` 仅有该记录器的测试。
- `TASK-MANIFEST.json` 列了 D01–D12 的任务文字和检查名称，没有相应完整业务项目、driver、
  hidden grader 与 R01–R03 的可运行定义。
- 这些准备工作不消费真实 Key。缺少它们是实施未完成，不能写成纯外部阻塞。
- 最小处理：先把 D01/D02/D04 三条做成实际可跑项目及独立判定，再按既有合同补齐其余场景；
  不建通用评测平台，不让产品修改 grader 或由执行者代做业务后记产品成功。

Spec 轴共 4 项：3 项 evidence 反例、1 项验收实施缺失；最严重类别是检查结果与完成判定不一致。

## Provider 与产品入口补充

### P1：当前官方模型名与写死的实现不一致

本次访问的 [DeepSeek 官方首页](https://api-docs.deepseek.com/zh-cn/) 推荐 `deepseek-flash`，并说明
旧名 `deepseek-v4-flash` 仍可调用，但已转由新版 Flash 服务。不能继续引用旧审计中“短名错误”
的说法作为当前结论。

`agent/provider/config.py:108`、`agent/provider/profile.py:137` 在思考模式只接受旧名；
`agent/provider/openai_http.py:274` 也只接受旧 response model。本次仅用合成凭据和 MockTransport：

```text
thinking_config deepseek-v4-flash: accepted
thinking_config deepseek-flash:   ProviderConfigurationError
response_model deepseek-v4-flash: accepted
response_model deepseek-flash:    ProviderStreamInterruptedError
```

因此新名配置被拒是确定事实；“服务端若返回新名会误判断流”也是确定的本地行为。服务端对旧 alias
实际返回什么字符串，本次未做付费请求，仍须小规模实测，不能宣称所有旧名调用必定失败。

最小处理：明确支持的当前 model 与返回 identity 合同，核对 thinking、工具调用、续接和 usage；
再跑一次纯回答及一个完整工具回合。不要默默改用户模型、掉 reasoning 字段或降低验证。

[官方 Chat Completions 文档](https://api-docs.deepseek.com/zh-cn/api/create-chat-completion/) 明确支持
`max`，但产品把 enabled 固定为 max、默认输出上限 4096、超时 30 秒的组合尚无当前真实性能证据。
这不是已复现失败，应通过同类任务的成功率、耗时与用量判断是否合适。官方文档还明确 final usage
与单元素 choices 同块；本次没有把不接受空 choices 错报为 DeepSeek 协议问题。

### 已声明限制与文档漂移

- Scheduler：`agent/automation/cli.py:245–246` 固定 `run_cli(core=None)`；`:106–108` 返回
  `needs_019_config`。当前安装入口没有 runnable host composition；help 成功不等于可调度。
  若要将其作为日常功能交付，需要明确 host 配置入口；这不是 API Key 可以解决的问题。
- strict 组合：`README.md:279–284` 已说明 Browser、Skill 脚本及部分 MCP 的开放 schema 会使 strict
  请求在发送前失败。不能宣称同一配置下所有扩展都能一起工作。
- `START-HERE.md:46–48` 仍把目录授权、本地 origin、多步 child 写成待实现，与当前源码和 RESULTS
  相冲突；入口文档需校准，避免接手者重复实现。
- README 的 `/tmp/first-agent-state` 示例在 macOS 符号链接路径防线下会失败，上轮已实际遇到；
  可复制示例应使用合法真实路径，不能只在执行记录中解释。
- 核心模块规模仍大：loop 4671 行、contracts 6137 行、state 4187 行、main 1859 行。行数不是缺陷
  证明，但核心一次承担大量状态、控制和证据语义，提高了上述交叉错误的维护成本。先修清楚边界，
  再只整理实际重复；不按行数拆文件，也不再新增验收框架层。

## 哪些尚未验证，为什么

| 范围 | 当前缺口 | 原因 / 最小补证 |
|---|---|---|
| D01–D03 多文件修复、功能增加、行为等价重构 | 新候选没有真实自主完成记录 | fixture/grader 未落地；还存在 C1–C3 的实现问题 |
| D04/D05 长任务、重启、纠正、200+ 文件仓库 | 离线构件测试，未证明模型会正确使用 | 要用自然目标，实际触发纠正/退出/压缩/截断并验证最终产物 |
| D06 本地网页修复与收尾 | 未跑完整模型＋浏览器旅程 | 浏览器二进制缺失，S1/S3 尚待处理；Key 本身不提供浏览器环境 |
| D07 只读 child 调查后父完成 | 多步与取消有离线测试，当前真实父子任务未跑 | 需共同预算、来源核对和父最终业务结果；过去的 child effect 成功不能替代交付 |
| D08/D11/D12 Skill 脚本、Memory、MCP | 当前组合有回归，无新候选自然任务闭合 | 用合成批准资源验证选择、结果使用、拒绝/错误恢复、最终产物 |
| D09/D10 注入、撤销、故障、预算 | 有局部反例，完整任务矩阵未跑 | 需要预冻结变体；S2 应先修；暂停正确与业务完成分别计分 |
| R01–R03 稳定性 | 全部 NOT RUN | 对 D01/D02/D04 同候选新环境复测，不能把一次好运当稳定 |
| A01–A24 | 当前表全部尚未整项闭合，A02 明记 NOT RUN | 既有测试可映射复用，但不可把尚缺实现/反例写成“只等真实 API” |
| 全量的 3 skips | 本次定点确认具体原因 | 1 个 launchd 实机显式 gate 未开启；2 个 Chromium 二进制未安装 |
| 当前 TUI、发布后依赖矩阵、跨平台 | 没有本轮充分证据 | 安装 smoke 主要证明 base CLI；macOS Seatbelt 不等于 Linux/Windows sandbox |

API Key 可以验证远程模型的真实选择、工具使用、续接和任务完成；它无法补上缺失的测试项目、
真实 Chromium、host composition 或已确认代码错误。

## 真实 Dogfood 确实存在，但要按版本区分

1. `docs/audits/2026-09-13-real-model-rich-dogfood.md` 曾覆盖聊天、读写、命令、Memory、Skill、MCP、
   SubAgent 与 TUI；同时记了拒绝重弹、工具结果后发散、未交付等失败。该报告的模型短名记录
   又被后续文档更正，不能据此确认今天的精确模型身份。
2. `docs/handoffs/2026-09-13-daily-use-repair-v3/RESULTS.md` 记录真实 provider 请求 24 次，以及
   K4 单独窗口 5/8 次补证。K1/K2/K3/K5 和补证 K4 分别验证了 TODO 读取、配置读取、目录报告、
   并发修改保留、准确命令与产物确认。原 K4 的 8 次 FAIL 原样保留。
3. 上一轮新 wheel `ece518bf…ab6311` 只有源码回归、安装来源/入口和 FakeProvider smoke，
   D01–D12/R01–R03 均未运行。旧版本的简单任务不能替代新 Runtime/流协议/child 的验证。

本项目可以、也需要用有效真实 Key 实测。用户历史上已经明确要求并授权过 DeepSeek Dogfood；
新 manifest 的 `real_dispatch_authorized=false`、空模型和零预算是这轮未落实的运行设置，
不是“系统禁止实测”，也不能抹掉历史授权。本次任务是审计，未读取 Key 或发起付费请求，
所以当前 Key 的有效性和余额没有新结论。

下一实测窗口应记录已选模型、只发送合成/授权项目数据、沿用安全注入方式，并设有限请求/时间
预算；不能为达到 PASS 无限重置预算。无需把 Key 放进资料包、Git、日志或回复。

## 距离日常通用 Agent 还有多远

“通用硬件”按上下文理解为通用 Agent。当前可定位为：**具备真实受控执行基础、已有简单任务
实测、仍需监督使用的个人 Agent 候选**。不能定位为“全部功能开箱即用、复杂任务稳定自主完成”。

没有依据给出完成百分比或还需几天。关键差距是可观测结果：一次交办后自行定位、多文件修改、
测试失败后修复、最终版本验证、资源收尾和完整交付。目前 C1–C3/S1–S3 会直接影响这些结果。
更重的权限/证据设施与未物化的业务验收并存；应把投入转向真实任务成功率、等待时长、授权次数
和救场次数，而不是继续增加 capability 名称。

建议最小执行顺序：

1. 修 C1–C3，证明测试＋lint 可以共同闭合、修改后旧证据不能通过；同时修 S1 并复现/处理 S3。
2. 修 S2 与模型 identity 兼容；保持现有单 Runtime 和发送前计数，补针对性反例。
3. 物化 D01/D02/D04 与独立 grader；先跑小额真实协议/工具 smoke，再跑三条完整任务。
   每条记录首次结果、实际模型调用、耗时、授权次数，以及提醒/代测/代收尾三项是否为零。
4. 按已有合同补 D03/D05–D12 和 R01–R03，其中至少一个非评测专用的公开或明确授权项目；
   失败先离线诊断修复，仅重测受影响任务。
5. 对实际要使用的 Browser/Skill/MCP/Memory/child/TUI 形成可用配置矩阵；Scheduler 与跨平台
   是另有产品接入工作的范围，不用它们阻塞前台日常编码能力的交付，但不能声称已开箱即用。

个人日常工作的验收门槛应先是：支持范围内的代表任务多次无业务救场完成，不能靠“全量测试
数量增加”替代这一结果。即使合同全部通过，也不推出任意任务、任意平台、任意第三方零错误。

## 本次验证记录

- 上轮报告的完整源码回归：3597 passed / 3 skipped，392.98 秒；本次未重复全量。
- 本次 focused：`tests/provider/test_deepseek_flash.py`、`tests/acceptance/test_coding_autonomy_grader.py`、
  `tests/kernel/test_runtime_limits.py`、`tests/architecture/test_single_loop_static.py`：37 passed，0.38 秒。
- skip 原因定点核验：禁用实机 launchd gate，运行 launchd/background-browser 两个模块：
  1 passed / 3 skipped，1.73 秒；其中 1 个显式 gate、2 个缺 Chromium。
- 新的失败反例为本次只读/临时合成探针；尚未落成产品回归测试或修复。全绿与反例同时存在，
  正说明既有覆盖不足，不能据 37 passed 宣称这些新问题已解决。
- supervisor 探针自有后代已回收；本次未注册登录项、未改变系统服务；产品源码保持原样。
- 本次新增文件仅本审计报告；原 RESULTS 保留，以便对照纠正先前表述。
