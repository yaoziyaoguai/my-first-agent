# 修复与验收合同

本文件只定义本轮必须满足的行为；具体实现由执行者在现有架构内选择。行号来自审计基线，接手后按符号定位。各项详细原因见独立审计，不复制整段历史日志。

统一规则：写能在修复前失败的测试；新测试不能通过替换被测生产判定为固定成功来“变绿”。同一公共原因可以用一个修复覆盖多项，但 RESULTS 必须保持逐项可追溯。

## DL-01 / P1：产品依赖闭包

**导航：** `agent/runtime/state.py` 对 `resource_lifecycle` 的导入；`loop.py` 对 `ports` 的导入；`main.py`、`agent/provider/config.py`、`agent/continuity/sessions.py`；`pyproject.toml`；`tests/cli/test_016_packaging.py`。

**Red：** 从审计基线 HEAD 的公开源码干净导出，`main.py --help` 因缺 `agent.runtime.resource_lifecycle` 失败；开发工作树可启动。

**必须做：**

1. 审查 missing import 的完整传递依赖，包含审计列出的五个未跟踪产品模块；不得只创建空模块/空函数绕过 import。
2. 写明候选包含的精确文件、原有修改与本轮修改、纳入理由、依赖关系和哈希。对一个文件中不相干的改动，不能因为方便就全部算本轮完成。
3. 用最终审核清单创建干净候选并构建安装物；不能从原工作树直接构建后声称已证明提交完整。
4. 保留用户现有工作、索引和分支；未授权 Git 写入时交付文件清单与候选即可。

**通过：** 候选中立目录的已安装 `first-agent --help`、基础离线任务、TUI 正向启动均通过，导入位置都在候选环境。刻意从候选删去必要模块的负例必须失败，防止 fallback 到原仓库。wheel 不包含辅助/私人目录。

**不算通过：** 原工作树 pytest 全绿、只核对两个文件哈希、把 `.venv` 整个复制进去、把所有未跟踪文件加入候选、测试时 `PYTHONPATH` 指回开发目录。

## RC-01 / P1：UNKNOWN 潜在写入失效

**导航：** `state.accept_action` 的 `ResolveUnknownToolOutcome`；`ClosedEvidenceRegistry._may_invalidate_workspace_validation`；`AgentRuntime._successful_product_request_inventory`；checkpoint/compaction。

**Red：** 已有成功验证 A → 写入 effect UNKNOWN → `mark_succeeded` 或 `mark_failed`。当前旧 A 仍可用于证据，A 的同参数重跑仍被抑制。

**冻结语义：** “不知道是否已写入”必须保守失效相关旧验证；标记失败不等于从未执行。操作员分类不是真实验证，也不授予新执行权限。

**必须覆盖的回归：**

| 用例 | 必须观察到的行为 |
| --- | --- |
| UNKNOWN 写入后标成功 | 原验证不可满足 criterion；显式同参 A 可再次执行 |
| UNKNOWN 写入后标失败 | 同上，不因失败标签豁免 |
| action-prefix recovery fact | 不能被 run-prefix 过滤漏掉其失效含义 |
| 确定未执行的审批拒绝 | 不伪造成执行/写入，不无端清掉合法 read-only 组合证据 |
| 实际 checkpoint save/close/reopen | 两种恢复选择下失效语义仍在，新 Runtime 无旧缓存依赖 |
| 真实 compaction 后重开 | 保留或保守重建失效结论，不能因为旧事实裁剪而复活旧验证 |
| 最终真正重验 | 取得新 receipt 后才可按原有规则完成，不永久禁止验证 |

**实现边界：** 不重放 UNKNOWN；不伪造 receipt；失效信息必须来自可信执行意图/状态，不采信模型填的 `read_only=true`。优先既有 fact/严格投影，只提取确有复用价值的共同判定，不另建通用事件总线。

## RC-02 / P1：managed writer 生命周期与验证

**导航：** `agent/process/managed_web.py`；`agent/runtime/tools.py` 通用 governed 结果；evidence 失效和 loop 去重。

**Red：** 成功只读验证 A → 当前生产格式的 `managed_web_start` 结果 → 旧 A 仍被接受且同参重跑被抑制。

**冻结语义：** 可信能力允许同 UID 进程写 workspace，就不能因结果没有 `process_receipt` 而视为只读；仍存活的可写进程可能在验证之后继续写。

**必须覆盖：**

1. 使用当前真实 ToolRuntime 产出的结果，不只有手写 metadata。开始时失效旧验证；确定未执行的拒绝不冒充已执行。
2. 用本次拥有的短期 fixture server 在临时 workspace 写 sentinel。启动前的验证不得再用于最终完成。
3. 服务存活时做一次验证，再让服务写入，最后关闭；不能拿存活期的早期验证认证关闭后的最终内容。测试由事件/屏障协调，不靠随机 sleep 猜时序。
4. 正常关闭后显式同参验证可重跑并用于完成；关闭失败/结果不确定时不能宣称已无写入风险。
5. 启动失败但已可能有副作用、stop 超时、真实 checkpoint 重开后的资源状态均保守处理。
6. 原有成功只读 sandbox 的 A/B 并列验证继续有效，不因修复把所有只读执行都当成写入。

**实现边界：** 无新增监控守护进程；复用现有资源状态和工具身份/权限。不要只往一个工具名集合中添加 start 就忽略服务持续运行及 stop 的时间边界。

## RC-03 / P2：控制终态用量保全

**导航：** `AgentRuntime._poll_control/_finish`、终态 reducer、`RecordedRunResult`、现有 usage tests。

**Red：** 注入 3 次调用、1200 输入、230 输出，分别 PAUSE/CORRECT/CANCEL，当前返回 calls=0、持久化三字段=null。

**通过：**

- 三种控制均保存清除 active_run 之前的实际用量；返回值、durable result 和新进程读取一致。
- 已知 0 与 provider 未给出的 unknown 区分；不能把 unknown 编成真实 0。
- 继续/重放相同 action 不重复累计，不能把整会话历史冒充本次 run。
- 普通完成、失败、输出截断路径不回归；没有在本包要求实时货币换算或新的计费服务。

## UI-01 / P1：多行草稿保全

**导航：** `agent/tui/app.py::_on_multiline_result/_submit_text/_restore_draft`；F4 modal。

**Red：** 审批页 F4 输入两行后 F6，dispatch=0 却丢草稿；持久化前异常也丢。

**通过：**

- 所有发送尝试前保存完整文本和本地版本；F6 门槛拒绝/排队/失败不清空。
- 审批、暂停、busy、浏览器接管 pending、普通 idle 和异常时均保留可重新编辑的多行文本。
- modal 内 slash 文本仍是消息，不执行斜杠命令；Esc 保存并返回、不提交。
- 接收未知不自动重发；明确未接收可由用户重试；只由本次 durable 接收确认消费该版本。
- 提交后用户继续编辑的新草稿不被迟到回调清空；同一发送按键不重复 dispatch。

## UI-02 / P1：精确提交回执

**导航：** `_consume_pending_if_durably_accepted` 和 `_pending_submission`。

**Red：** 历史 action:1 的 `continue` 存在，新 action:2 同文在写盘前失败，当前错误清理新草稿。

**通过：**

- 待确认条目绑定确切 conversation/action identity，不以全文相等或“RunStatus.COMPLETED”替代。
- 旧同文、不同会话同文、迟到回执均不能消费本次文本。
- 精确新 action 已写盘但回调抛错：重载后能正确识别已接收，不自动再发。
- 精确新 action 未写盘：保留并明确可重试；无法确认则保留并提示待确认。
- 消费还需匹配草稿版本，不能覆盖用户后续输入。

## UI-03 / P2：第二条纠正可达终态

**导航：** TUI pending control 状态与 worker 收尾；`ControlInbox.close/poll`。

**Red：** 阻塞假 provider 时连续两条纠正，第一条应用后收尾；第二条残留 pending，idle 时 Enter 被拒。

**冻结语义：** applied、已明确丢弃、接收未知必须区分。不能把一个旧 run 的请求自动绑定到新 run；不静默丢文本。

**通过：**

- 第一条已应用时有精确 receipt；队列关闭导致未应用的第二条收到明确结果或能可信查询其结局。
- 已明确丢弃的文本保留，可由用户再次提交且仅提交一次；未知的保留但不自动重试。
- 两条纠正、纠正→暂停、纠正→取消、任务自然结束竞态、迟到旧 run receipt 分别覆盖。
- UI busy 状态和真实 worker 生命周期一致；不靠清空全部 pending map 掩盖未知请求。

## UI-04 / P2：F3 回看有界且准确

**导航：** `agent/tui/dialogs.py::build_f3_pages` 和 review modal。

**Red：** 一条 user + 20 条 tool facts 显示 0；20k assistant 变成单页 20012 字符；翻页页号不更新。

**冻结合同：** 先从保留 facts 中筛选允许展示的 user/assistant 内容，再选择最近 20 条可展示消息；页正文与角色/来源标签合计不超过 8000 字符。导航 chrome 可单独计算，但须在测试写明。

**通过：** 0、1、20、21 条消息；一条超长消息；中文/换行；多页前后导航；翻页过程中新 event 到来不改变已打开快照；正确页号/总页数。tool/private 元数据不进入回看，不新增 transcript 存储。

## UI-05 / P2：交付摘要不被普通回复覆盖

**导航：** TUI `_refresh`、`project`/render 的 VERIFIED_DONE 投影。

**Red：** 同一状态 mount 有目标、证据计数、权限关闭；随后完成刷新只剩 `All done` 和 scope。

**通过：**

- 新完成与重开同一状态呈现相同权威目标、产物、验证范围、剩余项和权限状态；普通消息可附加但不能替代。
- COMPLETED/普通聊天不自动升级 VERIFIED_DONE；部分完成、失败、取消明确区分。
- 产物和证据来自已有状态，不靠解析模型“我完成了”来填。

## EV-01 / P1：验收控制器真正有界

**导航：** `scripts/f2_f3_local_browser_journeys.py::_run_bounded`；`tests/acceptance/test_daily_use_browser_driver.py`。

**Red：** 小片段输出后延迟 EOF，0.15 秒预算在 1.3 秒后仍返回 timeout=false/PASS。

**通过：**

- 非阻塞字节读取，工作 deadline 独立 latch。即使 child 在发现超时前刚退出，超过期限的运行也不变成成功；允许记录 scheduler 分辨率误差，但不能漏掉量级超时。
- stdout/stderr 各有真实字节保留上限；达到上限不继续无限追加。UTF-8 分片可解码但不能把字节计数换成字符计数而少计。
- 排空和清理都有期限，包含继承 pipe 的后代；不能等待无限 EOF。
- 保持 existing work→cooperative→TERM→KILL→确认语义；只清理本次可验证的自有进程组，不能通过 kill-all 清环境。
- 负例矩阵：短片段无换行/不 EOF、stdout 洪水、stderr 洪水、子进程忽略 TERM、后代持有 pipe、刚过 deadline 的自然退出。
- 每个测试断言结果、墙钟上界、缓冲上界与清理。测试中缩小清理宽限，统一给出 `work + coop + term + kill + verify + 1s` 的上界；外层 watchdog 再多留 1s。watchdog 触发必须 FAIL，不能算产品正确超时。

不得删除异常测试、把预算调大掩盖阻塞、只改 verdict 文案，或新建通用进程监督平台。

## EV-02 / P1：真实 journey 的异常清理

**导航：** F2 `journey_f2_restart_outclosing` 两代 owner；D06 资源 readiness/registration；现有 cleanup helper。

**Red：** 实际 F2 函数创建资源后注入 open 异常，close callback 为 0。

**通过：**

1. 资源一旦由调用者取得，先登记到词法 owner，再运行可能失败的 readiness/open/ledger 检查。
2. F2 每代真实路径都有 finally；第一代确认清理和 ledger 后才能创建第二代。
3. 覆盖 gen1 readiness/open/读取 ledger，gen2 open/close，D06 readiness/调用；逐点注入异常。
4. 多资源逆序、至多一次清理；一个清理失败仍尝试剩余清理，按有界错误码保留任务失败和清理失败。
5. constructor 在返回 owner 之前失败的资源由 constructor 自己负责；不能指望调用者清理拿不到的 handle。
6. 不能仅测 `_JourneyCleanup` 辅助类；至少 fault injection 必须走实际 journey 函数，最后跑真实本地浏览器旅程。

## EV-03 / P2：验收协议与退出一致

**导航：** `_run_bounded` JSON 协议、`_run_child` 生产记录、main 对失败目录的保留。

**Red：** 成功 JSON 后 exit 7；成功 JSON 的 journey 是另一条；两者当前均 PASS。

**通过：**

- 先核对 `_run_child` 实际产生的 journey 标识，再定义唯一映射：外部参数 `f2/d06` 与内部规范名如不同，必须显式映射；不能直接比较不相同名称导致正例全失败。
- 一个正常退出、本次预期身份、字段类型合法、目标检查通过且清理确认的记录才允许 PASS。
- 缺字段、重复记录、非 JSON、错误 journey、布尔伪装为 0/1、failure_codes 类型错误、非零退出、signal exit 均失败。
- target success/cleanup failed 和 target failed/cleanup success 区分，但都不能总体 PASS。
- 只有真实 PASS 且清理确认才可删除本次临时目录；失败保留证据，不包含真实秘密。

## LOG-01 / P2：默认诊断无原始敏感消息

**导航：** `main.py::_log_runtime_state_failure`；入口异常测试。

**Red：** 虚构 CheckpointSecurityError 消息含敏感路径标记，直接出现在 stderr。

**通过：** 用户文本、stdout/stderr 和默认日志均无虚构 secret/path 标记；保留稳定错误码、类型和可执行的下一步。分别覆盖未配置 logging 的独立子进程、配置普通 handler 的进程。别仅断言 write_fn。

不要求新增诊断文件或 debug 日志系统；如果保留详细模式，必须显式 opt-in、owner-only、脱敏并沿现有路径，不能自动记录 key/prompt/私有路径。

## Q1：安装与指南（必需证明，不新增产品功能）

- 与 DL-01 共用同一候选；base、`[tui]` 分别验证。browser 已安装路径验证成功，缺失时诊断如实；不要求本轮重测所有 MCP/Skill 扩展。
- Textual 必须满足 `pyproject.toml` 已声明的 `>=8.2,<9`，不能把声明降到开发机的 8.1.1 只为通过。无法获得合规依赖就标对应 gap。
- 指南区分“源码开发启动”和“用户安装物启动”。安装物路径不能要求存在源码 `main.py`；每个被使用的 venv 必须先创建。
- extras 列表严格来自当前元数据，不再写不存在的 `web` extra。
- Python 运行版本、声明最低版本、实际验证版本分开说明；本轮不新增跨 Python/跨 OS 矩阵。
- 候选环境 `pip check`、入口、离线首轮、TUI 正向启动和缺配置提示均核对；外发前仍有原有权限门槛。

## Q2：持久化和 worker-owner 定向证明（必做，不无限诊断）

- 与 RC-01/02 共用真实临时 checkpoint 的 save→owner close→新实例 reopen；用产物/receipt 身份断言，不只是同一对象传新 Runtime。
- 调用真实 compaction 入口，确认失效语义没有被裁剪抹掉；正常只读验证仍能继续。
- 修正 DU-24 的证明表述/测试：假 provider 可以驱动确定性测试，但不能依靠内部 stage 假装上下文恢复；在新进程/新 provider 中由实际收到的 task/correction 决定该测试分支，删除或篡改恢复信息的负例必须失败。不是要求重写整个 fixture 框架。
- TUI 用屏障让 worker 在其 callable 返回前停住，验证 owner cleanup/退出不会先开始；覆盖普通完成、异常、Ctrl-Q pending。若现有路径已经满足，记录测试，不为了“必须改点什么”而重构。
- 历史 CheckpointSecurityError 保持 NOT_REPRODUCED，除非找到同一签名的根因和修复反例。最多一次已有有界诊断矩阵；若没有新证据，不反复跑百轮，不宣称该事故根治。当前必要的定向测试不能由历史矩阵替代。

## Q3：真实代表性任务（授权后执行）

详细步骤和预算边界见 VALIDATION。使用实际 First Agent 入口、真实 provider、实际文件/测试；执行者自己直接写出正确答案不能算 Agent 成功。

必须记录正例的自主定位、修改、纠正、重开、最终检查和产物，以及负例的如实失败/未验证。不能通过扩大模型输出上限、关审批、给额外工具、增加第二套 agent loop 来解决本轮失败。
