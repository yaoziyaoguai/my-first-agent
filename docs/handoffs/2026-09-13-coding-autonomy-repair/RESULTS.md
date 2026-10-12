# 执行与验收记录

## 当前状态

**IMPLEMENTATION IN PROGRESS / REAL ACCEPTANCE NOT RUN**。
已完成一批针对“无需反复催继续、能检查、能诚实收尾”的离线候选实现；F01–F24 尚未全部闭合，
A01–A24 仅有部分合同的定向证据，D01–D12 与 R01–R03 均未运行。不能把本状态写成整包 PASS。
历史 3502 passed / 3 skipped、K1–K5 也不能填入下表作为本包证据。

制包检查与产品验收分开：本包共 9 个文件，包含 24 项问题、24 项离线门禁、12 个产品场景、
3 个稳定性复测和 8 个工作包。制包时检查本地链接、源码路径、编号映射、围栏、空白、
明文 key 格式与 59 个选定基线文件的摘要；这些检查不计作 A/D/R 产品 PASS。

状态只用 NOT STARTED、IN PROGRESS、PASS、FAIL、BLOCKED、NOT RUN。
记录阻塞时保留未运行状态；不允许把本包必需 F/A/D/R 静默改成 DEFERRED。

## 执行身份与授权（由接手者填写）

- 当前 HEAD / branch / dirty 范围：`838cb2b66fbba674311d4d86fc7c4f4322fd8612` / `main`
  （ahead 7）；工作树在接手前已有大量 modified/untracked 文件，本轮未 reset/stash/清理用户改动。
- baseline 核对及已漂移文件：2026-09-13 复核 59 个摘要，其中 15 个相对制包基线漂移：
  `README.md`、`main.py`、`KERNEL_ARCHITECTURE.md`、runtime 的 loop/state/contracts/evidence/tools/checkpoint、
  CLI actions/app、TUI app，以及 goal policy/runtime limits/workspace search 三个测试文件。漂移是实现期间的
  检测信号，不是验收失败或成功结论。
- 本包新增/修改文件与原因：新增离线 grader、manifest 与验收测试；修改 Runtime/CLI/TUI 及相关测试，
  实现 durable run 上限、瞬时重试、exact-file task consent、workspace onboarding、完成摘要、慢请求
  heartbeat/诚实取消确认和验证 freshness。完整归属仍须在最终 diff review 中从接手前 dirty 中拆分。
- 选定模型、provider 协议、推理/输出配置：未选择；没有声明沿用旧模型。
- 真实数据外发与 credential injection 授权：未取得，不保存 key 或原文路径。
- 全窗口实际请求上限 / 每任务上限 / 时间 / 费用上限：未批准；真实 dispatch 必须为 0。
- 统一 ledger / parent-child-compaction 计数校验：已有离线实现/既有测试，未进行本包真实请求校验。
- 任务/评分/环境 manifest 摘要：`TASK-MANIFEST.json` SHA-256
  `d87bbf49dd89197dcd66665ddcd55a113ceffece93d760d237beb99ee0b5f6a6`；明确禁止真实 dispatch，
  provider/model 为空，请求/墙钟预算为 0。grader 目前校验外部结果合同，尚无完整物化 fixture runner。
- 最终离线安装候选：`first_agent-1.0.0-py3-none-any.whl`，SHA-256
  `ece518bf46b71560088e9ebb1763b9213002cab242ea4e3ffd015a1470ab6311`；在临时 non-editable venv
  中从 `site-packages` 加载 `agent`、`main` 和 `first_agent_skill_runner`，`first-agent --version`、
  `first-agent --help`、`first-agent-schedule --help` 以及一次安装态 FakeProvider Runtime turn 均成功。
  wheel 共 161 entries 且不含用户未跟踪的根 `tui/`；当前源码全量也包含 isolated-wheel packaging
  回归。候选仅用于本轮验证，未发布或留在仓库。

首次真实调用前固定上述授权与 manifest。授权变化建立新的清楚记录，不能改旧记录遮盖超额。

## F01–F24 关闭表

每项记录：实现文件及原因、Red/Green 证据、对应 A 与 D/R、失败/局限。
表中 A PASS 不能代替所需 D/R；本表 PASS 表示该问题的整个合同已闭合。

| 问题 | 工作包 | 必需验收 | 状态 | 实现与证据 |
|---|---|---|---|---|
| F01 | P0/P7 | A01、D01–D12 | IN PROGRESS | manifest/record validator 和 held-out 划分已实现；validator 最多返回 `RECORD_VALID`，不会把产品自报检查提升为 PASS；外置 fixture/grader runner 未完成，D 未运行 |
| F02 | P1 | A02、D01/D02 | IN PROGRESS | 已有 typed evidence/criteria gate；尚无 D01/D02 外置行为评分闭环 |
| F03 | P1 | A03、D01/D09 | IN PROGRESS | 中英文、否定、疑问、撤销的 public-state tests 已覆盖；实现仍是受限词法下界，不是通用语义理解 |
| F04 | P1 | A04、D02/D03 | IN PROGRESS | 验证后再写/process/sandbox 会使旧 receipt 失效；外部并发修改和完整输入依赖图未覆盖 |
| F05 | P2 | A05、D01–D04 | IN PROGRESS | 去除 8-call 正常分片并增加跨 resume 的 40-call durable cap；D 未运行 |
| F06 | P2 | A06、D01/D10 | IN PROGRESS | no-progress 与 retry 分类已有反例；仅 timeout/transport/unavailable 最多重试两次，D10 未运行 |
| F07 | P2 | A07、D01–D04/D09 | IN PROGRESS | 文件 consent 支持显式 exact file 或 Goal 已声明目录；均绑定 revision/workspace/operation，16 次/60 分钟/可撤销，敏感路径拒绝。命令与 provider 继续复用各自既有 exact lease/disclosure receipt，不合并成巨型授权；D 未运行 |
| F08 | P2/P3 | A08、D04/D09 | IN PROGRESS | provider heartbeat 与 TUI `Ctrl-C` 请求确认已实现；精确 DeepSeek V4 Flash SSE 可在读取边界响应 bound control，残缺/取消流不推进 Runtime、不自动重发；其他 provider 仍无通用 hard-cancel，D 未运行 |
| F09 | P3 | A09、D01–D04 | IN PROGRESS | `deepseek-v4-flash` + 官方普通 endpoint + thinking enabled/max 的精确 SSE/多工具/opaque continuity 已实现；不支持组合 fail closed，真实 D 未运行 |
| F10 | P4 | A10、D02/D05 | IN PROGRESS | root/instruction/config/test discovery 与截断后 scoped search 有 225-file 合成项目测试；D05 未运行 |
| F11 | P4 | A11、D02/D03 | IN PROGRESS | exact edit/write 的 snapshot/revision/goal authority 与 dirty/untracked 保留已有离线测试；D02/D03 多文件自然任务未运行 |
| F12 | P4 | A12、D04 | IN PROGRESS | context pressure、latest correction、未闭合事实保护及 restart selection 已覆盖；D04 中途修正/退出真实旅程未运行 |
| F13 | P4 | A13、D04/D11 | IN PROGRESS | `GoalProgress` 已要求并持久化 restart-ready 的已做、相关文件、最近有效检查、失败路线及唯一 next step；Memory 保持 advisory，D04/D11 未运行 |
| F14 | P5 | A14、D06 | IN PROGRESS | 新增 task-owned exact `127.0.0.1` binding；每次 browser request 重验 owner/Goal/期限，localhost、其他端口/LAN/跨 origin 保持拒绝；D06 未运行 |
| F15 | P5 | A15、D06/D10 | IN PROGRESS | 新增 governed start/observe/stop、有界日志、hard lifetime 与 parent-EOF process-group supervisor；依赖诊断与 D06/D10 未闭合 |
| F16 | P6 | A16、D07 | IN PROGRESS | child 已有界多步搜索/按行读取；仅只读工具、父侧 freshness 复验、过期来源剔除及 advisory path/line/digest appendix 已实现；parent/child 共享模型尝试 ledger，bound control 可在开始前阻止或在运行中回收 child group；durable run 增加总墙钟发送前门禁，但不伪装为任意 provider 的通用 in-flight hard cancel；D07 未闭合 |
| F17 | P6 | A17、D08/D11/D12 | IN PROGRESS | 当前 Memory/Skill/MCP 组合回归 208 passed；资料包要求的三个自然任务 D08/D11/D12 仍未运行 |
| F18 | P1–P7 | A18 | IN PROGRESS | 唯一 Runtime/ContextManager/ToolRuntime 边界保持；尚无最终调用归因与抽象成本审计 |
| F19 | P7 | A19 | IN PROGRESS | 默认 run/retry/consent 边界已更新文档；尚无帮助文本、实际用量和完整 drift 审计闭环 |
| F20 | P6 | A20 | IN PROGRESS | 稳定分页、完整 ID 状态检查、终态会话 preview/确认归档、容量释放及 lossless restore 已实现；active/unknown、损坏、身份漂移、满容量恢复均 fail closed；未处理真实用户历史 |
| F21 | P1–P6 | A21、D09 | IN PROGRESS | 既有 fail-closed 安全路径和相关回归测试保留；本包完整 egress/审批 adversarial matrix 未执行 |
| F22 | P2/P3/P6 | A22、D10 | IN PROGRESS | durable run cap、可共享 transport ledger 与 2 小时 durable run 墙钟上限已有；Resume/重启和时钟回拨不会获得新预算，下一笔 provider/tool effect 前暂停。真实 parent/child/compaction 计数及 in-flight 到界行为仍待 D10 |
| F23 | P2/P5/P7 | A23、D01–D06 | IN PROGRESS | 完成摘要与 durable authority 清理已实现；active server/browser receipt 受 compaction 保护并阻止误完成，父退出/期限到界自动清组；D01–D06 未运行 |
| F24 | P0/P7 | A24、D01–D12 | IN PROGRESS | record validator 区分 offline/real identity 且不签发产品 PASS；当前 wheel 已验证，外置 grader 与全部 D/R 身份闭合尚未验证 |

## A 门禁结果

填写实际 test node/命令、候选身份、exit code、计数、skips 和必要脱敏输出摘要，不只写 Green。

| 验收 | 状态 | 证据 |
|---|---|---|
| A01 | IN PROGRESS | manifest 身份/预算/held-out 与记录形状有测试；自报检查只得到 `RECORD_VALID`，不再伪装产品 PASS；外置 fixture/grader 未物化 |
| A02 | NOT RUN | — |
| A03 | IN PROGRESS | `tests/continuity/test_contracts.py` 覆盖中英文要求、否定、疑问和修正；D01/D09 未运行 |
| A04 | IN PROGRESS | `tests/process/test_j1_verified_done.py` 证明验证后的新 workspace effect 会使旧 process evidence 失效；完整输入图未实现 |
| A05 | IN PROGRESS | `tests/kernel/test_runtime_limits.py` 覆盖超过 8 次仍可完成及跨 resume 的 durable cap；D 未运行 |
| A06 | IN PROGRESS | runtime error/no-progress tests 覆盖瞬时重试与不可重试分类；D10 未运行 |
| A07 | IN PROGRESS | runtime approval/goal policy/checkpoint/TUI/CLI tests 覆盖 exact-file 与显式 Goal-directory consent 的授予、范围隔离、敏感路径拒绝、耗尽、过期、撤销、v9 收窄迁移和身份漂移；D 未运行 |
| A08 | IN PROGRESS | `tests/kernel/test_runtime_progress.py`、TUI active cancel 与 `tests/provider/test_deepseek_flash.py` 覆盖真实等待秒数、“请求≠停止”、SSE cooperative cancel、残缺流拒绝和零自动重发；精确链路之外无通用 hard-cancel |
| A09 | IN PROGRESS | `tests/provider/test_deepseek_flash.py` 覆盖正常、多工具、reasoning continuity、缺 usage/finish/`[DONE]`、错序、超限和取消；277-test 组合复核 provider/continuity/session，但没有真实模型 D |
| A10 | IN PROGRESS | `tests/tools/test_workspace_search.py` 的 225-file 合成项目覆盖规则/config/test entrypoint 与 scoped continuation |
| A11 | IN PROGRESS | file/edit/write 与 Runtime approval tests 覆盖 stale preview、并发漂移、exact scope 与既有 dirty 保护；D02/D03 未运行 |
| A12 | IN PROGRESS | compaction/restart/goal-control tests 覆盖 latest correction、尾轮保护、恢复不重放 effect；D04 未运行 |
| A13 | IN PROGRESS | `tests/continuity/test_restart_selection.py` 和 provider control tests 证明 restart-ready progress 跨 checkpoint/reopen 保留文件、有效检查、失败路线与下一步；D04/D11 未运行 |
| A14 | IN PROGRESS | browser/process/URL focused 覆盖 exact loopback、逐请求 revalidation、跨 origin/localhost/LAN/其他端口拒绝；D06 未运行 |
| A15 | IN PROGRESS | managed server focused 覆盖 start/observe/stop、端口占用、bounded capture、parent pipe 消失和 hard lifetime；checkpoint 故障完整旅程与依赖诊断场景未运行 |
| A16 | IN PROGRESS | `tests/subagent` 共 52 passed：覆盖多步只读调查、写/shell/network/再派生不开放、过期来源剔除、process hard deadline、开始前取消和运行中 process-group 回收，并由静态架构门禁证明 provider/tool 调用仍只有 `AgentRuntime` 一个 owner；run 总时间有发送前门禁，但 D07 未运行 |
| A17 | IN PROGRESS | `tests/memory tests/skill tests/mcp` 共 208 passed，覆盖现有 governed ToolRuntime 的主要成功/拒绝/错误/清理合同；尚不能替代 D08/D11/D12 自然任务 |
| A18 | IN PROGRESS | 架构边界未新增第二 loop；最终 diff/调用归因审计未完成 |
| A19 | IN PROGRESS | README/架构/本记录已校准候选行为与限制；完整 CLI help/成本检查未完成 |
| A20 | IN PROGRESS | session retirement/archive/restore 与 conversation archive 的组合覆盖 terminal-only、显式 digest/revision preview、容量释放、完整恢复、重启、损坏、symlink/hardlink、满容量及 active/unknown 保护；未处理真实用户历史 |
| A21 | IN PROGRESS | 相关安全回归包含在 344-test 组合中；完整 A21 matrix 未单独执行 |
| A22 | IN PROGRESS | durable cap/ledger 与 run wall-time 有离线测试；当前证明恢复、重启和时钟回拨不重置并在新 effect 前暂停，不证明所有 provider 都能在 in-flight 瞬间 hard-cancel；真实统一计数未运行 |
| A23 | IN PROGRESS | `delivery_summary_message`、Goal authority closure、active resource completion gate 与 compaction protection 有测试；D01–D06 未运行 |
| A24 | IN PROGRESS | manifest/record-validator tests 与当前 non-editable wheel 的 import/entrypoint/FakeProvider Runtime smoke 已通过；validator 不会签发产品 PASS；D/R、外置 grader 与最终候选身份闭合未完成 |

## 真实产品任务

每个 D/R 的单次运行另记：候选/fixture/grader 摘要，模型配置，输入与授权摘要，ledger 起止值，
物理请求数、墙钟时间、主动执行/等待时间、可获得的 token/费用、业务提醒/代测/代收尾/consent 次数，
产品运行的测试、外置 grader 结果、实际 diff 与资源清理。输出中的秘密及私有原文不可存入仓库。

| 场景 | 状态 | 首次/最终结果、人工介入、用量和证据 |
|---|---|---|
| 基线 D01 | NOT RUN | — |
| 基线 D02 | NOT RUN | — |
| 基线 D04 | NOT RUN | — |
| D01 | NOT RUN | — |
| D02 | NOT RUN | — |
| D03 | NOT RUN | — |
| D04 | NOT RUN | — |
| D05 | NOT RUN | — |
| D06 | NOT RUN | — |
| D07 | NOT RUN | — |
| D08 | NOT RUN | — |
| D09 | NOT RUN | — |
| D10 | NOT RUN | 正常完成与预期暂停分开计分 |
| D11 | NOT RUN | — |
| D12 | NOT RUN | — |
| R01（D01 第二次） | NOT RUN | — |
| R02（D02 第二次） | NOT RUN | — |
| R03（D04 第二次） | NOT RUN | — |

## 失败与决策记录

每次填写“现象 → 脱敏证据 → 最近原因 → 离线 Red → 最小修复 → focused Green →
是否需要且有权进行真实复验”。没有新诊断，不重复付费请求。
如发现新增问题，用 N01…登记，写与当前任务的关系，范围外事项只记录、不自动扩展实施。

### 2026-09-13 离线实现检查点

- 最终源码全量使用项目 `.venv`：3597 passed、3 skipped，392.98 秒，exit 0。跳过项为既有平台条件，
  本轮没有把 skip 当 PASS。首次全量为 3596 passed、3 skipped、1 failed：唯一失败是 v5 迁移测试的
  手工旧文档没有删除新 schema 字段 `run_started_at`，因此不再是合法的 v5 fixture；修正夹具后相关
  55 tests 通过，再执行上述最终全量并完整通过。
- 一次误用系统 Python 的全量得到 3513 passed、3 skipped、9 failed；其中 6 个 `-I` subprocess
  因系统环境未安装 `first_agent_skill_runner` 而失败，不是产品回归。改用项目 `.venv` 定点复跑后
  这些节点通过；另外 3 个架构守卫真实发现 `_CountingProvider` 形成第二个 provider 调用点，已删除
  该旁路，改由唯一 `AgentRuntime` 的 `RunResult.model_calls_used` 报告用量，并登记新增 evidence 模块。
- 最终 focused：核心架构/Runtime/SubAgent 53 passed；Kernel/CLI/SubAgent/packaged runner 组合
  630 passed；先前 non-editable installed-wheel packaged runner 23 passed。本轮最终 wheel 另以干净 venv
  验证安装来源、三个入口与一次 FakeProvider Runtime turn；Ruff 与 `git diff --check` 通过。
- validation freshness focused：34 passed；TUI cooperative cancel focused：3 passed；这些结果不与全量计数累加。
- Provider continuity/session focused：277 passed；精确 `deepseek-v4-flash` SSE/opaque continuity、restart-ready progress 与会话 archive/restore 组合通过。官方协议核对后修正了早期错误模型名 `deepseek-flash`；未进行真实 dispatch。
- SubAgent focused：52 passed；child 可在独立 state 中有界多步读 workspace，父侧会重新核对来源 snapshot，越界工具不执行；bound control 可在开始前阻止启动或在运行中回收 process group。该结果尚不包含 D07 真实模型与统一 wall-time 证明。
- Memory/Skill/MCP focused：208 passed；没有因此宣称三个自然输入产品任务已通过。
- P5 focused：474 passed，覆盖 exact loopback browser policy、受管开发服务的真实 start/observe/stop、
  parent pipe 消失、hard lifetime、完成门与 compaction 保护；未使用真实模型，D06 仍 NOT RUN。
- 安装态 smoke 首次把状态目录放在 macOS 的 `/tmp` 别名下，安全路径策略因其实际穿过到
  `/private/tmp` 的 symlink 而 fail closed；改用解析后的真实路径后，同一 wheel 的 Runtime turn exit 0。
  这证明拒绝和正常路径都按合同工作，不把失败隐藏成 PASS。
- 未使用真实模型、未消费 key、未发送项目数据；`TASK-MANIFEST.json` 明确禁止真实 dispatch。
- 未创建登录项/daemon，未启动受管浏览器或开发服务器；未 commit/push。

## 最终交付检查

- [ ] F01–F24 无遗漏，A01–A24 均 PASS。
- [ ] D01–D12 与 R01–R03 达到合同，三类业务救场均为 0；必要授权单列。
- [ ] 至少一个非评测专用的公开/授权项目；否则明确能力结论收窄且未达到完整门槛。
- [x] 全量/ruff/diff check 完整结果与最终产品源码对应。
- [ ] 新 wheel、安装来源与关键真实任务身份闭合。
- [ ] 文档/帮助/默认预算/支持模型/限制准确，没有自动 promotion。
- [ ] 用户 dirty/untracked 不被覆盖，无新登录项/daemon，无本任务残留资源或未知清理被隐瞒。
- [ ] 未读未授权凭据/私有数据，未 commit/push；未把隐式第二 loop 或权限旁路引进产品。
- [ ] 交付总结报告实际完成率与成本，不把“框架保护通过”写成“任意任务都能完成”。

全部勾选后才可以将最上方整体状态改为 IMPLEMENTED AND ACCEPTED。
