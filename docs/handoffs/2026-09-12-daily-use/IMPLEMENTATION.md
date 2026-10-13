# 分阶段实施合同

执行顺序：S1 → S2。S3 只有用户明确纳入时执行。以下新测试名是建议的验收用例，不表示仓库已有同名测试；实际实现复用邻近 fixtures 和既有测试模块。

## 开始前：一次性基线核对

1. 读仓库规则与 evidence/baseline.json，检查 HEAD、工作树改动及将触及的文件。已有改动属于用户，先理解再叠加。
2. 为本次执行建立 EXECUTION-LOG.md：每步写 finding ID、复现、原因、实际改动文件、验证、待办。不要将原审计改成新结论。
3. 确认已有 Python/依赖、正常 CLI 安装方式；不扫描凭据目录。先跑当前切片最小测试组作为对照。
4. 每一步按“复现 → 最小修改 → 聚焦验证 → 检查 diff”推进。遇到证据推翻 finding，就记录撤回理由，不为满足清单制造改动。

## S1：连续前台任务可安全显示、能理解、可恢复

对应 F3/F4/F6。首次预计修改 CLI renderer/app 及其测试；只有消费链确需时才扩至 Runtime/provider/共享 TUI。文件数量不是硬限额，扩展必须能解释与验收的关系。

### S1.1 定位并修复显示生命周期

读取顺序：

- `agent/cli/render.py::TerminalRenderer` 与 `terminal_text`。
- `agent/cli/app.py::run_repl`，`main.py` 的 renderer 装配。
- `agent/runtime/loop.py::AgentRuntime._delta_observer_for`，以及创建 observer 的调用点。
- `agent/provider/anthropic_http.py`、`agent/runtime/ports.py::ModelDeltaObserver`。
- `tests/cli/test_render.py`、`tests/provider/test_kernel_providers.py`、`tests/kernel/test_event_ordering.py`。

当前 delta identity 含 conversation、revision、计数；causation 含 run/revision。需要核对“一次 invocation、多次 provider.generate”是否能据此可靠区分，不能仅按 conversation 或只在 render_result 清空就认为全部修好。只有现有字段确实不足且 Red 证明时才做最小事件合同修改。

Named Red 行为：

| 建议名称 | 输入/动作 | 必须成立 |
|---|---|---|
| delta_literal_display | ESC、CR、bidi/C1、中文、换行；同一序列跨多个 delta | 控制字节不能直达终端；正常文字和允许的换行保留；最终协议内容不变 |
| consecutive_answers_once | 同 renderer 连续两轮最终答案 | 每轮完整显示一次，无第二轮重复 |
| multiple_responses_one_action | 文本→工具→文本、多次模型请求 | 中间文本与最终答案不混成一个响应，不误抑制最终结果 |
| interrupted_stream_recovery | 流产生部分文本后失败，再恢复 | 不把部分文本当完成；恢复显示不继承错误缓存，不自动重发模型请求 |
| advisory_fault_display | 重复、缺失事件或显示 sink 抛错 | 事件不推进权威状态/授权；最终结果可纠正缺失显示 |

显示只转义“最终输出到终端”的文本。内部原始答案用于比较和 normalize；不可把转义后的内容写回模型上下文、checkpoint 或审批 binding。

对事件故障先跑现有合同，避免顺便重写所有事件机制。测试必须包含真实 TerminalRenderer/Runtime 边界；只对新 helper 断言不够。

### S1.2 最小等待反馈

提交被接受后立即显示准确的“处理中”提示，并在结果、审批、失败或退出时收束。只有已证实实时到达的事件才能显示具体“正在调用模型/工具”；缓冲事件不能冒充实时状态。

优先复用现有渲染与计时能力，不为 spinner 新建 model loop、后台执行器、轮询调度器或进度百分比。若显示耗时，应来自本地时钟；不用模型推测。

验收：非流式路线也能及时知道请求已接收；流式、错误、拒绝、KeyboardInterrupt 后提示不残留、不遮盖审批。CLI 关键行为有测试；共享合同变更时回归 tracked `agent/tui/` 的适配器测试。

### S1.3 固定一条真实模型路线，验证正常安装

参考 `main.py` setup/profile 装配、`agent/provider/profile.py`、`agent/provider/normalize.py::_project_strict_wire_schema/context_tools_to_openai`、`tests/provider/test_provider_profile.py`、`tests/cli/test_016_packaging.py`。

用户先前常用 GLM，但不能仅由历史替用户选择当前模型或凭据。沿用当前任务明确指定的 First Agent 配置；没有时先完成离线修复，把所缺 provider/model/credential 环境变量名和真实调用条件一次列明。

只验证一个已存在 Provider family。`thinking_mode=disabled` 是既有显式选项，是否使用由当前配置决定。禁止运行失败后静默关闭 strict、隐藏已启用工具、换模型或导入 Pi/Claude/Codex 凭据。

组合不兼容时，按现有 schema 验证机制提前定位具体 tool/schema path，网络/effect 均为零；若诊断已经明确，只增加必要回归与记录，不再造验证器。

从仓库外运行 non-editable wheel 的正常 console 入口，核验 import origin。完成：启动/披露→读合成文件→正常批准写入→利用工具结果继续第二轮→拒绝一次写入→合法 /new→重启查看合成 pending。允许合成输入和外部进程控制器，禁止内部 API 代写任务状态、auto-approve 伪装成人工交互。

S1 完成：显示反例全闭合、拒绝无 effect、当前安装路线实际多步任务通过。缺真实调用条件时只能标记“本地修复已验证，S1 真实验收未完成”。

## S2：结果验证准确，产物确认由用户看内容

对应 F1/F5。S1 完成后开展正式真实任务；不依赖凭据的 S2 源码分析/Named Red 可以先推进。

### S2.1 先说明现有 evidence 到底证明什么

读取：`agent/runtime/evidence.py::ClosedEvidenceRegistry`、`agent/runtime/state.py::verify_goal_completion` 及 criterion admission、`agent/runtime/loop.py` 完成链、`agent/runtime/views.py`、`agent/process/tools.py`、`agent/sandbox/shell.py`。测试入口为 `tests/kernel/test_evidence_registry.py`、`tests/process/test_artifact_approval_contract.py`、`tests/continuity/test_research_evidence.py`。

产出一页决策记录，回答：

1. 当前 FILESYSTEM_DIGEST、process_v1、native_sandbox_v1 各绑定哪个 Goal/revision、输入、命令、产物和事实时点？
2. “文件字节正确”与“报告数值正确”在哪一层区分？现有 criterion 能表达哪部分？
3. 普通文件审批、artifact confirmation、执行后 read-back 各确认的是哪一时点的字节？
4. U2B fixture 的 local_process 要求是否来自 fixture 自己？必须给生产路径复现后才能改消费者。

发现某个缺口可通过既有 criterion/回执精确表达时，直接复用。若要新增 oracle 类型或持久合同，先写窄设计和反例说明；这属于有实证约束的任务级验证，不能扩大为通用语义评分框架。

### S2.2 建立任务正确性及反例

在合成 workspace 内用现有受治理 process 工具做计算/验证，确保真实模型实际选择并使用它。独立 QA oracle 由执行者预先写定，保存在模型任务作用域外；不采用模型生成的期望答案。

最低三类任务在 VERIFICATION.md 定义。必须同时验证正例与这些反例：

- CSV 某组 errors 加 1、P95 选择错排名、正文与表格不同。
- 只创建文件，没有验证；运行无关 `exit 0`；使用上一个输入或 Goal revision 的回执。
- 验证之后修改产物；同一个成功回执被套用到其他命令/路径/目标。
- 模型报告“已通过”而可信过程没有对应检查。

正确行为：如果只证明生成文件，就如实显示该范围；需要的数值检查未通过时，不能投影“数值已核验”。缺验证保持可解释的未完成或待核验状态，并保留现有恢复路径。

仅在 prompt 中写“务必计算”不算修复闭环；任意命令成功也不能证明报告正确。不要把所有普通写作任务强制变成数值验证任务。

### S2.3 无需手抄 SHA 的产物确认

入口：`agent/cli/actions.py::build_resolve_approval`、`agent/cli/app.py::_parse_action`、`agent/cli/render.py::TerminalRenderer.render_pending`、`tests/process/test_artifact_approval_contract.py`、`tests/cli/test_contextual_decisions.py`；共享决策受影响时再读 `agent/tui/adapter.py`、`agent/tui/render.py` 和对应测试。

先用测试区分三类语义：

| 场景 | 合理的确认依据 | 必须拒绝的捷径 |
|---|---|---|
| 确切写入 proposal | Runtime 已绑定的待写入内容＋可读预览 | 用户确认旧文件摘要，冒充新内容确认 |
| 已存在产物核验 | 治理 read-back 的当前字节和可信 binding | CLI 自己打开任意文件、模型自报摘要 |
| 任意程序未来生成结果 | 先批准有界生成，再 read-back/验证并确认产物 | 执行前伪造不可预知的未来摘要 |

普通人操作应是查看明确内容和效果后确认，内部传递精确 binding。保持 stale preview/CAS 拒绝；不能把旧 yes 自动套到新预览。任何新增 typed action 只在现有合同无法表达且测试证实时引入，不能为 UI 便利绕过 ToolRuntime 读文件。

验收：新建、修改、已有文件核验均不要求手输 SHA；proposal/文件/revision 在审批前后变化时 fail closed；不同路径、旧摘要、伪造模型摘要不被采用。普通 write_file 原有可用交互不回归。

S2 完成：3 类×3 个独立输入变体通过，负例不能获得不实验证声明，安全审批无弱化。9 个通过样本只证明这些有界任务，不代表通用正确率。

## S3：可选的 019 manual 调度交付

只有用户选择交付持久调度时执行。S3 manual 不含系统登录项注册、cold wake、跨平台移植。

读取 `agent/automation/cli.py`、`composition.py`、`management.py`、`reconcile.py`、`store.py`、`agent/automation_hosts/macos_cli.py`、`macos_runtime.py`、`macos_profile.py`、`runtime_executor.py`；测试 `tests/automation/test_open_handoff.py`、`test_reconcile_faults.py`、`tests/automation_hosts/test_macos_cli.py`、`test_macos_composition.py`、`test_wake_management.py`。

顺序：

1. 梳理已有 owner config、factory、repository ports。新增配置字段前确认无法复用；入口静态装配，portable core 不导入 macOS host，不建动态 registry。
2. 接通安装后 list/show，缺模型/Browser/Sandbox 不阻止只读管理；按需装配执行依赖，保持 fail closed。
3. 将人类任务、时间、目录、次数/期限等输入映射到既有 typed 管理动作；展示 source 快照时点、owned occurrence workspace、结果位置。CAS token 由薄适配器处理，发生冲突重展示并重新确认。
4. 列出所有 management/reconcile code，对成功、失败、未知、冲突、需人工写明确映射；根据现有调用者确认具体数字，再固定测试。不得按 code 字符串包含某字推断。
5. 用可信 handoff identity 打开现有 CLI/TUI 恢复入口；初始显示零 model/tool 调用，后续动作仍经唯一 Runtime。
6. non-editable 安装制品完成 create→preview→approve→manual reconcile→核对真实产物→open；重投同 delivery 与 occurrence 均零新增请求/effect。

边界验收：批准任务不安装系统项；list/show/普通 preflight 零网络零注册；snapshot 冲突不自动重绑授权；unknown 不通过重建、cancel 或重投变相重试；source 只读快照和输出目录向用户明确。

不要以旧 `main.run_schedule`、`scripts/_019_macos_u2b_host.py` 测试工厂或脚本替换正式安装入口。真实 host 的 blocked_terminal 不是模型完成任务。

cold wake 若以后另行选择：manual 先通过，已有受信任凭据交付方式，用户授权真实调用和系统注册，再验证应用退出后完成真实目标。缺前提记录 not_run；不顺手创建凭据管理平台。

## 分阶段收尾

每阶段修改一次必要的用户说明与执行日志。稳定后按 VERIFICATION.md 运行对应 gates；整批授权修改结束运行仓库要求的完整检查。新的失败先精确复现，别每修一个断言就重跑所有真实任务。最终检查 diff 每项都可追溯到 finding；不自动 commit/push/promote。
