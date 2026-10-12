# 验证与交付证据

本文件是未来执行的验收合同。除 FINDINGS.md 和 evidence 中注明的历史结果外，下列项目均未由资料包准备者执行，不得预填 PASS。

## 分层测试，控制重复工作

| 时机 | 范围 | 目的 |
|---|---|---|
| 修改前 | 当前切片最小既有测试＋新 Named Red | 分清已有失败与本次改动；缺陷测试必须先真实失败 |
| 每个小修复后 | 该 Red＋相邻行为回归 | 证明原因被修复，不反复跑全仓 |
| 切片稳定后 | 相关 fault matrix、安装测试、必要真实旅程 | 证明跨组件行为；真实用例只重跑被新改动影响的项 |
| 本批授权改动交付前 | ruff、全量 pytest、diff check | 对最终代码一次完整回归；失败修复后补相关与最终 gate |

已有测试路径（只选择本切片所需，不把下列全表每次全跑）：

```bash
# S1：显示与当前 provider/CLI 合同
.venv/bin/python -m pytest -q tests/cli/test_render.py tests/cli/test_contextual_decisions.py tests/provider/test_kernel_providers.py tests/kernel/test_event_ordering.py

# S1：安装边界；该模块共享 wheel/隔离 venv，避免手写第二份 harness
.venv/bin/python -m pytest -q tests/cli/test_016_packaging.py

# S2：审批、证据与正确性合同
.venv/bin/python -m pytest -q tests/process/test_artifact_approval_contract.py tests/kernel/test_evidence_registry.py tests/continuity/test_research_evidence.py

# S3（选择该阶段时）：portable 管理/恢复及 host 装配
.venv/bin/python -m pytest -q tests/automation/test_management.py tests/automation/test_reconcile.py tests/automation/test_reconcile_faults.py tests/automation/test_open_handoff.py tests/automation_hosts/test_macos_cli.py tests/automation_hosts/test_macos_composition.py tests/automation_hosts/test_wake_management.py

# 最终仓库要求
git diff --check
.venv/bin/ruff check .
.venv/bin/python -m pytest -q -rx
```

新加入的测试一并运行。若修改共享 CLI/TUI 决策、provider schema、process/sandbox 消费者，再补对应目录回归；按实际 diff 选范围。真实 LaunchAgent probe 不因出现在测试目录就自动获得授权。

测试 runner 必须捕获 exit code 和完整结果摘要。超时、截断、未知退出都不是通过。skipped 必须说明原因；不删除断言、放宽安全断言或把失败改为 skip。权限/环境失败先识别并走正常授权机制，不擅自切换 full access。

## 安装边界

参考现有 `tests/cli/test_016_packaging.py` 的 wheel 构建与依赖闭包。该确定性测试支持离线基础依赖安装，不证明在线依赖解析或所有 extras 的真实安装。

记录 HEAD、当前改动指纹、wheel SHA-256、Python/依赖版本、入口 shebang 与 import origin。使用仓库外独立环境、non-editable 安装及合成 workspace；不得用 PYTHONPATH、内部 factory、源代码路径注入或测试假 Provider 冒充安装产品。

同一最终安装制品用于 S1/S2 真实任务。中途产品代码改了，应重新构建并只重跑受影响验证，再给最终结果绑定正确制品。

## 真实调用条件

使用用户为 First Agent 指定的 model、provider 和 credential 环境变量；不打开 `.env`、其他产品配置或私有日志来找 key。只记录凭据变量名/是否就绪，不记录值、认证 header、完整环境或 profile 私有内容。

当调用授权/配置已明确时沿用，不重复询问。缺失时继续离线工作，并一次性列出所需信息和本次有界真实任务范围。外层验证设置明确运行时限，记录次数/耗时；不在遇到额度限制、超时或模型错误后无限重试。

真实任务由正常产品动作完成，包含披露和审批。确定性假模型可以验证协议，不能替代这些真实任务。若用外部 harness 驱动 CLI，记录哪些输入由用户或脚本提交；“自动应答审批”不能算人类交互可用性通过。

## 最小真实任务矩阵

先写合成输入与独立预期，再给模型任务。QA 期望及核验程序放在 Agent 被批准工作区外，只供执行者核对，避免模型改答案来通过。

| 任务 | 3 个固定输入变体 | 独立判定 |
|---|---|---|
| 数据统计 | 12 组稳定分组；加入零错误/全错误、小样本、边界排名；变体用重排与边界值，预先固定规则 | 明确 CSV 字段、error 定义、空值规则、P95 nearest-rank；独立程序核对 count/errors/P95、单位和正文引用 |
| 小范围代码维护 | 3 个合成项目中的编码/边界处理缺陷，修改前测试各自失败 | 外部保留固定 tests 与输入 SHA，修复后测试通过，原始输入字节未改，diff 局限于请求 |
| 冲突需求综合 | 3 份合成来源构成每组输入；3 组中各有已知冲突、缺权威或未决点 | 事先列出功能点、来源、冲突与不可自行决定项；逐项核对，不以模型自评代替 QA |

这 9 个任务是当前有界任务基线，不是成功率统计，也不是任意能力证明。不为凑绿反复换模型或输入；失败保留并归因。真正修复后重跑受影响变体。

S1 操作旅程可复用上述第一项任务，额外验证连续两轮、披露、批准、拒绝、合法 /new 和重启 pending。拒绝一次写入后确认文件不存在或原字节不变。为了恢复测试创建的是合成状态，禁止读取用户旧会话。

## 安全与正确性反例矩阵

| ID | 反例 | 合格结果 |
|---|---|---|
| N1 | ANSI/CR/bidi 跨 delta 分片 | 终端只显示安全文字；权威内容和审批 binding 不变 |
| N2 | 两轮、同一 action 多模型响应、断流后恢复 | 无跨响应拼接，无重复最终答案，无自动重发 |
| N3 | 事件重复/缺失/显示失败 | checkpoint 与 effect 次数不因 advisory 变化 |
| N4 | 报告错误、只有文件、无关 exit 0 | 不宣称所需业务结果已经验证 |
| N5 | 旧输入/Goal/命令/产物证据 | 精确绑定拒绝复用，无盲目接受 sandbox 成功 |
| N6 | 看预览后 proposal、文件或 revision 漂移 | 原批准 fail closed，不能自动绑定新请求 |
| N7 | 新建/修改/已有文件核验 | 可从内容预览正常确认，无需手抄或猜未来 SHA |
| N8 | strict＋不兼容工具 schema | 明确本地诊断，零网络/effect，无静默降级 |
| N9（S3） | 重复 delivery/occurrence、未知结果、旧批准 | 零重复 model/effect，恢复义务保留 |
| N10（S3） | list/show/preflight/manual 批准 | 零模型调用/系统注册；正确披露快照和输出目录 |

## RESULTS.md 建议格式

```text
代码与安装身份：HEAD、dirty fingerprint、wheel SHA、Python/依赖。
本次范围：S1 / S2；S3 是否由用户明确纳入。

Finding | 状态（fixed / withdrawn / deferred / blocked） | 复现证据 | 根因 | 修改文件 | 回归证据
Gate | 状态（pass / fail / not_run / blocked） | 输入与产物标识 | 命令/操作 | exit code | 证据路径

每次真实任务：model/provider（非秘密）、开始/结束时间、任务输入 SHA、产物 SHA、
模型请求数、工具/effect 数、disclosure 次数、审批次数、人工救场次数、独立 QA 结果。
无法可靠观测的计数写 unknown，并说明限制，不填 0。

失败与未执行项：具体原因、已完成的不受影响工作、解除条件。
范围检查：无新 loop/自授权；未知结果不自动重试；未改 promotion。
用户结论：现在可以做什么；仍需人工核对什么；是否真正通过本次日常交付线。
```

每条证据用合成数据和脱敏摘要，记录可复现的步骤与预期，不保存凭据。原始 Oracle 文档、旧验收报告不可改写成新执行结果。
