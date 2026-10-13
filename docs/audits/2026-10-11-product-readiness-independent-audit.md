# First Agent 日用产品就绪度独立审计（2026-10-11）

## 1. 结论与适用范围

**结论：已有真实 Agent 内核与能力，不能评价为“只是聊天包装”；但当前不能认定为稳定、可交付的日用 Agent 产品。最优先的工作是可靠性收口，不是继续增加能力。**

本报告以“单用户、本机、有人监督的日常代码与文件任务”为合格目标，不把多租户云平台、任意操作系统、无人值守无限运行作为门槛。

本轮确认 13 项缺陷/交付问题：7 项 P1、6 项 P2。另列出安装验证、真实任务覆盖与生命周期等未完成证明。P1 表示阻断可靠交付、输入保全或结果可信度，应在本轮产品收口中优先修；不等于已经证明远程可利用的安全漏洞。

本轮只审计。没有修改产品代码、提交或推送代码，没有读取真实密钥、私人会话或运行日志，没有调用真实模型 API，也没有发起新的 Oracle Web 会话。之前的真实模型报告作为历史证据引用，不冒充本轮重跑。

## 2. 审计对象与新鲜证据

- 当前分支：`main`；HEAD：`dee8c25e550cfa957307c1eaadc4ac20a7b9a8d7`。
- 本地 HEAD 与缓存的 `origin/main` 一致；本轮没有联网 fetch，因此不声称核对了远端此刻的最新状态。
- 工作树仍有 **125 个 tracked 文件修改**，合计 8411 行新增、659 行删除；此外有未跟踪文件。不是所有未提交内容都属于本轮，应按依赖审查，不能一键全部纳入交付。
- 至少五个未跟踪的产品模块：`agent/process/managed_web.py`、`agent/process/managed_web_child.py`、`agent/runtime/resource_lifecycle.py`、`agent/subagent/evidence.py`、`agent/tools/directory.py`。
- 审计重点：任务终态与验证新鲜度、未知副作用恢复、用户输入和纠正、暂停与用量、浏览器验收驱动、安装交付与使用指南。
- 采用三项独立的只读审查分工；主审复核了关键源码并重新运行合成反例。没有读取根目录未跟踪的 `tui/`。

本轮实测环境：Python 3.12.2、httpx 0.28.1、Textual 8.1.1、Playwright 1.62.0、pytest 9.0.2、ruff 0.15.12。注意项目声明的 Textual 是 `>=8.2,<9`：UI 实验发生在当前实际环境，尚不能替代受支持依赖环境的验证；下述草稿判据和数据流缺陷另有源码佐证。

### 本轮已完成检查

| 检查 | 结果 | 能证明什么 |
| --- | --- | --- |
| `git diff --check` | PASS | 当前差异无该命令检测的空白错误 |
| `.venv/bin/ruff check .` | PASS | 当前工作树静态规则通过 |
| 关键区域 pytest | **159 passed，28.20 秒，exit 0** | 现有相关测试通过，不代表反例已覆盖 |
| HEAD 公共源码干净导出后启动 | **FAIL，exit 1** | 当前提交的产品依赖不闭合 |
| 当前工作树 `main.py --help` | PASS，exit 0 | 本地工作树可以导入启动 |
| Runtime 合成边界反例 | 成功复现 RC-01/02/03 | 生产 reducer、证据判定、去重与控制收尾存在缺口 |
| TUI Pilot/合成反例 | 成功复现 UI-01 至 UI-05 | 当前环境的输入保全、纠正和显示问题 |
| 独立小型子进程驱动反例 | 成功复现 EV-01/02/03 | 实际验收控制器可超时失效或误判 PASS |
| 安全的虚构异常内容实验 | 成功复现 LOG-01 | 原始异常消息可以输出至默认 stderr |

关键区域测试命令：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -rx -p no:cacheprovider \
  tests/kernel/test_validation_request_freshness.py \
  tests/kernel/test_run_result_usage.py \
  tests/kernel/test_runtime_progress.py \
  tests/tui/test_adapter.py tests/tui/test_app.py tests/tui/test_render.py \
  tests/cli/test_entrypoint.py tests/provider/test_deepseek_flash.py
```

没有重跑全库、真实 API、完整真实浏览器/Seatbelt 场景或跨平台矩阵。上一轮 `3711 passed, 1 skipped` 是历史报告，不是本轮结果。

## 3. P1：必须先修复的七项

### DL-01：已提交 main 不具备自包含启动能力

**影响：其他电脑或干净 checkout 拿到这个提交，连帮助入口都不能启动；开发目录里的通过记录掩盖了缺文件。**

定位：`agent/runtime/state.py:97`；`tests/cli/test_016_packaging.py:134`。

从 HEAD 仅导出公开源码和包元数据，在导出目录用项目解释器启动 `main.py --help`，得到：

```text
ModuleNotFoundError: No module named 'agent.runtime.resource_lifecycle'
```

同一命令在原工作树正常。该模块未跟踪。进一步核对发现已提交调用者还依赖未提交的 `ports.py`、provider config、continuity sessions 等修改，不能只补一个文件就宣布结束。

现有打包测试从脏工作树 ROOT 构建 wheel，再把开发环境的依赖闭包 materialize 到测试 venv。它可以证明“当前工作树产物”的某些性质，不能证明“这个 Git 提交完整”。

**最小修复/验收：** 审查并补齐真正的产品依赖闭包，保留无关用户修改；从明确的干净交付快照构建 wheel，在中立目录和隔离环境实际运行已安装入口、帮助、离线首轮任务及 TUI extra。来源路径不能意外落回开发仓库。Git 提交/推送仍需用户授权。

### RC-01：UNKNOWN 写入恢复后，旧验证仍被认可，重新验证仍可能被抑制

**影响：异常发生前的测试结果可能被当作异常写入之后的有效证据，破坏“最终修改之后必须验证”的承诺。**

定位：`agent/runtime/state.py:2585`、`agent/runtime/evidence.py:1444`、`agent/runtime/loop.py:3985`。

生产 reducer 接受 `ResolveUnknownToolOutcome` 后清掉 `executing_intent`，产生的 recovery fact 仅有 synthetic/is_error/call_id，缺少可信的潜在写入标识。证据判定要求 `executed=true`；去重折叠还只遍历 `run:<id>:` 前缀，因此都跳过 `action:<seq>:recovery`。

合成已有成功 sandbox 验证 → 写入 outcome UNKNOWN → 合法恢复，分别测试 `mark_succeeded` 和 `mark_failed`：两者均出现 `old_validation_accepted=true`、`native_validation_suppression_count=1`。

**证据边界：** 这是实际 reducer/证据/去重代码的内存边界反例，不是一次真实断电，也不证明所有任务都能绕过其余条件到达 `VERIFIED_DONE`。

**最小修复/验收：** 对可能已执行的写入保留可信失效信息，不能靠操作员选择“失败”推断没有副作用；统一证据与去重的判断。不得伪造成功 receipt、自动重放 UNKNOWN 操作。两种恢复、checkpoint 重开以及 compaction 后，旧验证均不能满足义务，显式重新验证必须可执行。

### RC-02：可写的 managed web 进程没有失效旧验证

**影响：本地服务进程可能已改变工作区，旧测试证据和禁止重复验证的记录却继续有效。**

定位：`agent/process/managed_web.py:299`、`agent/runtime/tools.py:817`、`agent/runtime/evidence.py:1453`、`agent/runtime/loop.py:4025`。

`managed_web_start` 属于 `LOCAL_SAME_UID_PROCESS`。其结果采用通用 governed-tool 元数据，没有 `process_receipt`。目前失效判定按少量工具名或 receipt 形状识别副作用，漏掉此路径。

以当前生产结果格式构造事实后，生产判定返回 `mutation_barrier=false`、`old_validation_accepted=true`，去重仍保留一项旧 sandbox 验证。

**证据边界：** 本轮没有启动真实 web server 改文件；确认的是已授权可写能力与证据判定之间的语义缺口。仍存活资源等其他完成门槛可能另行阻止最终交付。

**最小修复/验收：** 根据可信副作用能力和实际生命周期失效证据，而不是只认一种 receipt 外形；覆盖启动、运行期间可能写入、关闭以及失败路径。测试应证明服务写入后旧验证不成立，新验证不会被去重阻断。复用现有治理边界，不增设第二套运行循环。

### UI-01：多行编辑器发送失败或遇到审批门槛会丢草稿

**影响：用户写好的多行需求可以无提示消失，甚至一次模型调用都没发生。**

定位：`agent/tui/app.py:881`、`agent/tui/dialogs.py:183`。

F4 编辑器先关闭，`send` 分支直接调用 `_submit_text`，没有先把编辑后的文本保存到 `draft_text/draft_revision`。

两个反例：审批页 F4 编辑两行后 F6，`dispatched=0` 且草稿/输入为空；正常发送但在持久化前抛出 OSError，`dispatched=1` 而草稿/输入仍为空。

**最小修复/验收：** 发送尝试前先保存完整多行文本；门槛拒绝、排队、未确认接收与失败均不能消费草稿。只有本次动作的持久化接收凭据可以清理对应版本。覆盖审批、暂停、忙碌、失败及编辑器重新打开。

### UI-02：历史相同文字被误当成本次消息已接收

**影响：重复发送“继续”等常用文字时，一次失败的新提交可能被清空，用户误以为已送达。**

定位：`agent/tui/app.py:308`。

`_consume_pending_if_durably_accepted` 遍历全部历史 user facts，只比较文本相同和泛化的 action fact 形状，没有绑定本次 action identity。

历史 `action:1:user="continue"`，新一次相同文本在持久化前失败：生产 UI 仍清空草稿，但事实数量保持 1。

**最小修复/验收：** 使用本次确切 action/conversation 身份识别持久化接收，再结合草稿版本清理。旧消息、迟到回执和其他会话的相同文字均不能消费新草稿。

### EV-01：浏览器验收驱动的超时与输出上限并不可靠

**影响：验收可能卡住、超出预算却标成未超时，大量输出也没有真正限制保留量。该问题位于验收工具，不等同于生产 scheduler 已被证明有同样缺陷。**

定位：`scripts/f2_f3_local_browser_journeys.py:585`、`:610`、`:654`。

`select` 可读后使用文本流 `.read(4096)`，仍可能等待缓冲填满或 EOF；因此不能据此认定读取非阻塞。超时状态又依赖检查时 child 是否仍存活。stdout 超限后继续追加；主循环 stderr 未递减剩余额度。

用只输出一个短片段然后睡眠的受控 Python 子进程验证：预算 0.15 秒，实际 1.308 秒才返回，但 `timeout=false`、`passed=true`。实验有独立 4 秒 watchdog 和自有进程组清理；没有挂起遗留。

**最小修复/验收：** 真正的非阻塞字节读取、单调时钟 deadline latch、有界缓冲和排空；超时事实不因 child 稍后自然退出而消失。分别测试短片段不换行、stdout/stderr 洪水、继承管道的后代；必须断言墙钟时间和保留输出上限，而非只断言结果字段。

### EV-02：真实浏览器验收路径仍缺异常清理 finally

**影响：操作失败时，验收自己可能留下浏览器资源；单独测 cleanup helper 不能证明真正的调用路径收口。**

定位：`scripts/f2_f3_local_browser_journeys.py:256`、`:288`；D06 的 readiness 断言与 owner 注册次序也需核对。

F2 两代资源只在正常路径调用 `generation.close()`，不是注释所说的独立词法 finally。第一代资源创建成功后让 browser-open 抛异常，实际进入 F2 函数的实验得到 `cleanup_calls=0`。

**最小修复/验收：** 真实 owner 路径从创建成功起就受到 finally/ExitStack 保护，先注册再执行可能失败的检查；第一代确认关闭之后才启动第二代。逐点注入创建后、readiness、open、ledger、第二代 close 等故障，确认逆序清理、至多一次调用，并区分任务错误和清理错误。

## 4. P2：同一轮应完成的六项

### RC-03：暂停、纠正、取消时用量丢失

定位：`agent/runtime/loop.py:3239`、`:4076`。

`_poll_control` 先保存清空 active_run 的状态，再进入 `_finish` 读取用量。对三种控制分别注入已有用量 `(3 calls, 1200 input, 230 output)`，返回值 calls 变成 0，持久化结果三字段均为 null。

修复验收：在终态转换之前保存实际用量，返回值、持久化结果和重开后的展示一致；区分 unknown 与 0。这不意味着独立网络计费流水必然丢失，也不意味着本轮实际产生了费用。

### UI-03：连续两条纠正，第二条既未应用又无法手动重发

定位：`agent/tui/app.py:746`、`:839`、`:983`；`agent/runtime/control.py:82`。

真实 Runtime/ControlInbox 配合阻塞式假 provider：连续输入两条纠正，第一条应用后 run 收尾并关闭队列；第二条仍残留在 UI pending map。此时 busy=false、inbox 无绑定、只有一条 receipt。再次 Enter，action_seq 维持 3，提示“请勿重复发送”。

修复验收：将控制请求区分为已应用、已明确丢弃、接收未知；已丢弃的内容保留并允许显式重发，未知的不能自动重复执行。覆盖两条纠正、纠正紧接暂停/取消、终态竞态和重开提示。

### UI-04：F3 回看筛选和分页不满足日用合同

定位：`agent/tui/dialogs.py:41`、`:67`、`:99`、`:114`。

先取最后 20 条 facts 再过滤，导致一条用户消息后跟 20 条工具事实时显示为空；一条 20000 字符 assistant 消息被放成 20012 字符的一页，超过约定的 8000；翻页标题计数没有跟随更新。

修复验收：先筛选可展示消息再按消息数量截取；长消息在保留来源/角色的前提下分段，页长有界、导航计数准确。不要为此增加新 transcript 存储或展示私人工具数据。

### UI-05：刚完成任务的刷新覆盖了权威交付摘要

定位：`agent/tui/app.py:505`；`agent/tui/render.py:134`。

同一个 VERIFIED_DONE 状态初始展示有 Targets、Required evidence 和 permissions closed；收到完成结果后，`_refresh` 用普通 result.message 覆盖为 `completed: All done.`，只余 evidence scope。状态本身没有丢失，但用户最需要的收尾信息缺了。

修复验收：新完成与重开同一状态显示一致的目标、产物、验证范围和未完成项；普通模型话术不能替代权威交付信息。

### EV-03：子进程非零退出或返回别的 journey 仍可 PASS

定位：`scripts/f2_f3_local_browser_journeys.py:693`、`:712`。

驱动只检查少数字段类型，没有要求成功退出，也没有绑定预期 journey。两个独立受控子进程分别“输出成功 JSON 后 exit 7”和“输出另一个 journey 的成功 JSON”，均得到 `passed=true`、空 failure_codes。

修复验收：严格绑定预期执行身份与协议，非零退出、错误 journey、畸形字段必须失败并保留故障证据。若协议设计允许异常退出但清理成功，仍不能把任务标成成功。先用故意失败的样本证明验收器能判 FAIL。

### LOG-01：所谓仅记录日志的原始异常仍会打印到终端

定位：`main.py:1152`；`tests/cli/test_entrypoint.py:729`。

`logging.getLogger(...).error(..., error)` 在默认配置下可由 lastResort handler 输出到 stderr。注入虚构的 `CheckpointSecurityError("SYNTHETIC_PATH_/owner/private/session")` 后，原消息直接可见。现有测试只检查 write_fn 文本，没有检查 stderr。

修复验收：默认用户输出和默认日志都使用稳定错误码/脱敏摘要；如提供详细诊断，只能是明确、受控的 owner 路径。使用虚构敏感标记覆盖 stdout、stderr 和普通日志。**本轮没有观察到真实 API key 泄漏，不能把这个风险夸大为已发生的数据外泄。**

## 5. 尚未证明的项目：不能当成已修好，也不能假定一定坏

### 5.1 干净安装与依赖版本

- 日用指南先执行 `python3 -m pip install wheel`，后续却使用未创建的 `.venv/bin/python main.py`；源码启动与安装后的启动混用。
- 指南写了 browser/web/skill extras，但 `web` 不是当前声明的 extra。
- 当前 Textual 8.1.1 低于声明下限 8.2。需要一个真正符合声明的候选环境，验证 TUI 安装和运行；不能用开发目录里碰巧已安装的依赖替代。
- 正确处理是给出一条完整可执行的首跑路径和有针对性的诊断，不是建设通用插件市场或环境管理平台。

### 5.2 生命周期事故

上一轮记录了 100 次配对检查没有再现 `CheckpointSecurityError`。这支持 **NOT_REPRODUCED**，不支持“根因已知并已修复”。测试矩阵有价值，应保留；仍需把事故状态与普通测试 PASS 分开。

TUI worker 中仍存在先通知 `_on_action_worker_finished`、再返回 worker 的次序；callback 会清理 busy 状态并可能推进退出。本轮没有证明它导致真实资源提前释放，列为待验证的 owner/worker 完成边界，而不计入已确认的 13 项。

### 5.3 持久化与验收真实性

- 部分 freshness 测试把同一内存状态传给新 Runtime，并不等于真实 checkpoint 写入/重开，更不等于 compaction。
- reopen 现有案例不完整覆盖“验证 → 写入 → 真正重开 → 相同参数再次验证”。
- 离线 DU-24 包含实际的受治理写入和控制动作，但 provider 用内部 stage 决定下一步；检查 prompt 中有任务文本不能单独证明计划真实依赖恢复后的上下文。
- 将对象 `del` 掉不能替代 owner 的显式 close 和清理证据。

修复这些证明缺口应复用当前测试设施，只补区别真失败与假成功的反例；不要再建设一层新评测框架。

### 5.4 真实模型 Dogfood

历史 RESULTS 报告了 DeepSeek 的 A/B/C 小型真实任务，包括写入审批、边界纠正及新进程恢复。不能说“从未用真实模型”；但也不能据此宣布中型代码仓库、长任务、TUI 连续纠正、崩溃恢复或全部能力普遍可用。

本轮没有消费真实 API 额度。上一轮给执行者的特定预算不是本轮自动继承的无限授权。

修复上述确定性缺陷之后，最有价值的新证据是 **一个有现有测试、涉及约 2–5 个文件的真实小仓库任务**：让模型自己定位和修改，途中纠正一次，暂停/重开一次，实际测试并交付；确认不覆盖无关改动。外加一个故意无法完成的场景，必须如实报告失败/未验证，而不是补成功话术。真实调用范围与费用届时再沿用有效授权或明确批准。

### 5.5 审计边界

本轮不是对所有 Memory/MCP/Skill/SubAgent、网络安全和跨平台路径的穷尽审计；没有发现问题的模块不能据此获得全面安全背书。也没有证据支持把它们全部重写。

## 6. 从合格产品的角度，必要能力究竟还缺什么

关键不是再列一串工具，而是让已有能力形成可信闭环。

| 用户需要 | 当前判断 | 最小补齐方式 |
| --- | --- | --- |
| 安装后就能启动，知道环境缺什么 | 本地可跑，但提交依赖不闭合、指南混用入口 | 干净快照安装门槛；统一首跑指南与已有诊断 |
| 输入不会丢，随时能纠正和停止 | 功能存在，部分状态组合不可靠 | 精确接收回执、草稿保全、已丢弃纠正可显式重发 |
| 中断后知道做到哪一步、下一步如何继续 | 已有 checkpoint/控制基础，异常语义与恢复证明仍不足 | 保留潜在副作用与用量；真实重开场景验证；清楚展示下一动作 |
| 完成时拿到可核验结果，而非一句“完成了” | 已有 evidence/VERIFIED_DONE，失效判定和即时 UI 收尾有缺口 | 最终产物、改动、验证范围、失败/未验证项一致展示 |
| 能判断时间和费用，避免一直等 | 已有预算/usage，控制收尾会丢用量，验收超时不可靠 | 修复计数与期限，复用当前状态/预算显示，不加后台常驻体系 |
| 能完成有实际意义的编码任务 | 有小型真实任务证据，中型代表性任务证据薄弱 | 在可信验收器上补一条真实仓库闭环，不靠更多脚本数量背书 |

现阶段**不属于合格日用产品的必要新增项**：更多并行 Agent、向量记忆数据库、自动安装远程 Skill、插件市场、接管整个桌面、无人值守无限循环、多租户服务、任意系统兼容保证。除非具体失败任务证明需要，不要把这些纳入修复范围。

## 7. Vibe coding 留下的主要工程问题

“是否由 AI 写成”不是质量证据。本项目的正面基础包括单一 `AgentRuntime.run_turn`、上下文与工具的责任划分、typed actions、审批与 checkpoint、安全文件边界和现有证据结构。这些应保留，不建议推倒重写。

本轮反例揭示的实际问题是：

1. **局部补丁没有覆盖跨模块语义。** 证据失效、去重、UNKNOWN 恢复和新工具各自看似合理，却对“可能已经写过”理解不一致。
2. **测试更接近证明实现写了什么，而不是证明用户最终得到什么。** cleanup helper 通过不等于真实异常路径 finally；有 JSON 不等于正确进程完成；有同文历史不等于本次输入被接收。
3. **发布边界与开发工作树混在一起。** 选择性提交后没有从真正交付快照重新启动，造成缺文件仍被当作已交付。
4. **用户状态丢在适配层缝隙。** 草稿、控制队列、终态显示与运行内核之间缺少完整的一致性检查。
5. **代码体量加剧核对成本，但行数不是缺陷本身。** `loop.py` 4776 行、`state.py` 4408 行、`contracts.py` 6158 行。应该围绕已证明重复或不一致的判定缩小责任面，而非启动按行数机械拆分工程。

需要的是少量有共同语义的修复及反例验收，不是继续堆更多状态、结果包装、平行执行器或报告等级。

## 8. 建议的有界收口顺序

1. **确认交付快照与依赖闭包。** 先让准备交付的代码在干净目录可启动，避免后续所有证据建立在错误版本上。
2. **修复验证可信度。** RC-01/02 与对应去重、重开/compaction 反例一起完成；不增加新工具。
3. **修复用户交互闭环。** UI-01 至 UI-05、RC-03；合并同一区域测试执行，避免每改一行全量重跑。
4. **修复验收器和诊断。** EV-01/02/03、LOG-01；先证明故意失败能正确判 FAIL，再使用它们给产品背书。
5. **统一安装说明并做最终交付验证。** touched tests 后做一次最终 full suite；从同一候选快照做安装验证，再在有效授权内补真实代表性任务。

完成条件不是“测试数量增加”或“模型说做完”，而是：干净候选可启动；上述反例全部转为正确行为；没有相关回归；验证结果对应最终代码；关键用户旅程有真实、范围明确的证据；剩余限制在产品和说明中可见。

## 附录 A：可复核的实验摘要

审计期间的临时合成诊断文件（只用于实验，临时目录可能被系统清理；不是产品入口）：

- `/private/tmp/fa_runtime_audit_20261011.py`
- `/private/tmp/fa_tui_audit_20261011.py`
- `/private/tmp/fa_driver_audit_20261011.py`
- HEAD 公共源码导出：`/private/tmp/first-agent-audit-20261011.F44G8R`

这些反例不含真实用户会话或密钥。Runtime 使用生产消费者配合合成事实/内存存储，TUI 使用 Pilot 和假 provider，driver 只启动本次自有的短期 Python 子进程。诊断脚本 exit 0 仅代表实验完成，不代表产品 PASS。

关键观测：

```text
RC-01 mark_succeeded / mark_failed:
  old_validation_accepted=true; native_validation_suppression_count=1
RC-02 managed-process:
  mutation_barrier=false; old_validation_accepted=true; suppression_count=1
RC-03 pause / correct / cancel:
  before=[3,1200,230]; returned_model_calls_used=0; durable_usage=[null,null,null]
UI-01 approval-gated multiline:
  dispatched=0; draft=""; visible=""
UI-02 historical equal text + new pre-persist failure:
  dispatched=1; facts=1; draft=""; visible=""
UI-03 second correction:
  busy=false; inbox_binding=false; receipts=1; seq_before=3; seq_after=3
UI-04:
  displayable_fact_exists=true; shown=0; pages=0
  long_message_pages=1; page_length=20012
EV-01:
  budget=0.15; elapsed=1.308; timeout=false; passed=true
EV-02:
  browser-open RuntimeError; cleanup_calls=0
EV-03:
  child_exit=7; passed=true
  wrong_journey_record; passed=true
```

## 附录 B：关键源码指纹

指纹对应本轮实际工作树，不用 HEAD 名字替代未提交内容身份。

```text
6b3c877ddc6201c6a6a54341b9727ea882e5934b17cd4cca8c822a6743bcb680  agent/runtime/loop.py
75f51c279c8b433eb16b4a465b9044c5175379cc24a38adaa984bf1b424ab9fb  agent/runtime/state.py
2f0bee2a0e56d4dceb561c3e228887f9e61b31e846b6d311fada768eafc0fde0  agent/runtime/evidence.py
c5a4acce2bf48dc9e0c794a5209174d536d6c2696932890eeac6b8341b03dbe0  agent/tui/app.py
c7b2a13ea590bfca9ecdeefa73daba836d4b5373735a8e3025129c7ae07e586a  scripts/f2_f3_local_browser_journeys.py
fa460613ce814b3336a181cf01ab4ab82b87018d715ce3947a989a45b84d0a47  main.py
```

历史证据入口：

- `docs/handoffs/2026-10-09-daily-use-closure/RESULTS.md`
- `docs/handoffs/2026-10-09-daily-use-closure/AUDIT-2026-10-10.md`
- `docs/handoffs/2026-10-10-reliable-daily-use/RESULTS.md`
- `docs/guides/daily-use.md`
- `docs/architecture/CURRENT_CAPABILITY_STATUS.md`
