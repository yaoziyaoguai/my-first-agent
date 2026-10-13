# 最小修复顺序与问题追踪

新增编号 M1、U1–U5 只是本包导航，不冒充上游已有编号。下列状态是交接时的证据强度。

## E0：接手与验收准备，不消费真实 API

核对基线/dirty；按问题逐个确认已有实现。建立本包 RESULTS 的实际测试映射。
物化验收的详细合同见 ACCEPTANCE；可先准备 D01/D02/D04，后补其余，不能把起始三项当全部。
保留旧失败和旧记录，不重置预算、不重写历史模型结论为当时已经知道的新结论。

## E1：检查结果能一起成立，也会正确过期

| 问题 | 证据与影响 | 最小处理和验收 |
|---|---|---|
| C1 / P1 | 合法 receipt 离线复现：两个成功验证相互作废，导致来回重测不能收尾 | 区分执行事实和验证输入身份；同一最终输入的 tests、lint 均可同时成立 |
| C2 / P1 | 离线复现：已执行却退出失败的命令不使旧验证失效 | 是否可能有修改不能由 exit code 决定；写后退出 1、异常/超时/unknown 均有反例 |
| C3 / P1 | 公共 evidence derive 复现：后续编辑后文件/native sandbox 证据仍有效 | file/process/sandbox 对相关输入保持一致 freshness；补真实合成文件的 Runtime 旅程 |

先读 `agent/runtime/evidence.py`、`state.py`、`tools.py` 及 REPRODUCERS。
优先复用现有 criterion/receipt/version 信息，只有缺少真实边界字段时才扩展。
相关输入包含源码、测试、配置、依赖声明和可信执行入口；外部并发修改同样要识别。
不确定相关性时保守失效；不能为了摘要读取 secrets 或扫描私人目录。
不靠把所有验证合并为一条命令、删 mandatory criterion、信任模型自报“只读”、忽略失败、
或接受任意 exit 0 来通过。验证成功不等于需求正确，业务正确性仍由独立 grader 判断。
若改持久化 schema，先记录准确字段及旧数据迁移/拒绝策略；测试损坏/恢复，不丢旧事实。

出口：复现测试转 Green；多验证最终闭合与修改后拒绝完成的正反例均经 Runtime 证明。

## E2：进程确实收尾，重启后也能证明

| 问题 | 证据与影响 | 最小处理和验收 |
|---|---|---|
| S1 / P1 | 本机合成进程复现：启动器退出后同组后代存活超过 lifetime | 直接 child 退出也关闭本任务进程组；覆盖 EOF、期限、TERM-resistant 后代 |
| S3 / P1 | 代码推断，未完整 CLI 复现：退出只清内存，重启旧 ref 不可 stop，可能卡在未收尾 | 先做完整 start→退出→重开→恢复核对→完成测试；复现后最小 governed reconciliation |

读 `agent/process/managed_web_child.py`、`managed_web.py`、`agent/runtime/resource_lifecycle.py`
及 existing owner/composition/checkpoint 路径。S3 未复现前不要提前设计新恢复框架。
cleanup 必须有准确 ownership 和可验证事实；PID/端口复用不能误杀；不能用“查不到旧 ref”
推断资源不存在，不能虚构 stop receipt。正常、取消、启动后 checkpoint 失败/unknown 均覆盖。
测试只能创建并回收自己的合成进程组；缺平台原语准确 skip，不安装登录项/daemon。

出口：资源存活检查、durable 事实、Goal 完成状态三者一致；别人的服务/文件不受影响。

## E3：预算与当前真实模型链路

| 问题 | 证据与影响 | 最小处理和验收 |
|---|---|---|
| S2 / P1 | 离线复现：run cap=1，压缩+普通共两次 provider，报告只记一次 | 发送前持久化计数，失败不退款，恢复不清零；普通/压缩/child/retry 全有归因 |
| M1 / P1 | 当前短名 thinking 配置被拒，合成新 response model 被误判断流 | 按当日官方合同明确支持 identity；MockTransport 正反例，再小额真实纯回答+工具回合 |

预算读 `agent/runtime/loop.py`、`checkpoint.py`、`agent/transport_audit.py`、
`agent/subagent/runner.py`、`process_runner.py`、`main.py`。分别定义 run 的逻辑调用计数和共享
HTTP ledger 的物理尝试上限，不能把两层数相加或重复扣账；可选 ledger 不能掩盖默认漏计。
parent/child/compaction 的共同上限要覆盖并发抢最后额度、失败、损坏 ledger、重启。
wall-time 的发送前检查不是所有 in-flight 请求的硬中断；准确测试并报告各 adapter 的停止延迟。

模型读 `agent/provider/config.py`、`profile.py`、`openai_http.py`、`normalize.py`。
2026-09-13 审计查得官方推荐 `deepseek-flash`，旧 alias 尚可调用；执行时复核官方文档。
这是明确模型 identity 合同，不是遇错自动换模型/宽松接收任意模型的 fallback。
不能默默改用户配置、去掉 reasoning continuation 或降低 strict。真实 alias 返回值尚未验证。
官方 final usage 与单元素 choices 同块，不要套用其他厂商“必须空 choices”的假设。

出口：默认 run cap 与共享物理 ledger 各自正确；支持/拒绝矩阵准确；真实阶段按 REAL-API 分开记。

## E4：把文字任务变成可跑的独立验收

C4 / P1 / 确认缺失：现有 `scripts/grade_coding_autonomy.py` 仅是记录 validator；
`RECORD_VALID` 不是业务 PASS。现有 TASK-MANIFEST 的描述不是物化的项目、driver 和 hidden grader。

按 ACCEPTANCE 逐项落地。先用 scripted provider 验证夹具/driver 本身，但成绩明确 offline。
driver 是外部用户 action 适配器，不能自己选工具、改代码、注入解法或写自动 resume loop。
既有 validator 强制 product completed，不能表示 D10 正确暂停；新增独立场景判定应明确区分
`scenario_contract_pass` 与 `business_completed`，不要把暂停硬写成 completed 以通过旧脚本。
不建评测平台/服务/数据库。最小 fixtures、独立可运行 grader、薄 driver、脱敏记录足够。

## E5：日常可用性、完整实测与交付

| 编号 | 审计事项 | 本包处理边界 |
|---|---|---|
| U1 / P2 | 安装的 scheduler 入口 core=None / needs_019_config | 如实列为未提供 runnable host；不新建 host，不用 help 成功充当调度通过 |
| U2 / P1 验收缺口 | strict 下 Browser/Skill/部分 MCP schema 组合被拒 | 明确每项支持配置；实测一种显式支持的组合，保留不支持组合的准确拒绝，无自动降级 |
| U3 / P2 | 旧入口“未实现”及 README `/tmp` 示例漂移 | 更新当前导航/限制和可复制例子，采用真实合法状态路径；不放松 no-follow 安全 |
| U4 / P2 | 核心偏重，但实际效果/控制开销未量化 | 记录有用/控制/重试/压缩/child 调用与授权、耗时；只处理当前触及的真实重复，不机械拆分 |
| U5 / P1 验收缺口 | 新候选 D/R、TUI、安装依赖矩阵及运行中到界缺证 | 按验收补证；缺环境明确 BLOCKED/NOT RUN，不借 API Key 解释缺 fixture/浏览器/host |

完成 D/R，保留首次/复测/最终结果；至少一个非评测专用的公开或明确授权项目。
逐项映射 A01–A24，最后源码稳定时跑一次全量和安装态验证，再 fresh diff audit。
产品改变后只复测可信受影响范围；无法界定影响时扩大验证，不能沿用失效证据。

## 上游问题零遗漏映射

下表是责任导航，不是通过状态。每个 F 的具体行为仍以原 ISSUE-REGISTER/SPEC/ACCEPTANCE 为准。

| 上游问题 | 本包阶段 | 必须保留的验收 |
|---|---|---|
| F01、F24 | E0/E4/E5 | A01、A24；全部 D/R 与独立判定/候选身份 |
| F02、F03、F04 | E1/E5 | A02–A04；同义/否定需求、业务验证与 freshness |
| F05、F06、F07、F08 | E3/E5 | A05–A08；自主推进、失败修正、有限授权、进度取消 |
| F09 | E3/E5 | A09；模型协议与真实工具回合 |
| F10、F11、F12、F13 | E4/E5 | A10–A13；探索、多文件、最新纠正与恢复 |
| F14、F15 | E2/E5 | A14、A15；本地网页、生命周期和依赖诊断 |
| F16、F17 | E3/E4/E5 | A16、A17；child、Skill、Memory、MCP |
| F18、F19 | E1–E5 | A18、A19；单一 owner、实际成本和文档 |
| F20 | E5 | A20；合成会话容量、显式归档与完整恢复 |
| F21、F22 | E1/E2/E3/E5 | A21、A22；不可信输入、安全、共享预算与停止 |
| F23 | E1/E2/E5 | A23；最终版本检查、完整交付和本任务资源收尾 |
