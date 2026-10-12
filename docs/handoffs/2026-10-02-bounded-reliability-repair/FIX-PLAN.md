# 修复合同与实施顺序

本文只解释 [START-HERE.md](START-HERE.md) 已冻结的范围。验收编号见 [ACCEPTANCE.md](ACCEPTANCE.md)。
以下新增测试名称均是建议名称，不声称仓库当前已经存在；执行者必须记录实际 pytest node。

## F1：成功 process 改写后，旧验证仍可支持 VERIFIED_DONE

### 事实与代码入口

- `agent/runtime/evidence.py::_may_invalidate_workspace_validation`：有 process receipt 时，当前只用 is_error/exit_code 判断失效；exit 0 被当成另一项验证。
- 同一逻辑用于 filesystem readback 与 process validation，旧 read/test 可以跨过成功的变更命令。
- 现有正向合同：`tests/process/test_j1_verified_done.py::test_015_successful_validation_processes_can_coexist_without_workspace_write`。
- 现有工具与完成测试：`tests/process/test_j1_verified_done.py`、`tests/continuity/test_verified_done.py`、`tests/continuity/test_sandbox_verified_done.py`。
- 审计在新建临时目录通过真实 `KernelToolRuntime.prepare/invoke` 执行写文件命令，再经 `AgentRuntime.run_turn` 提交 CompletionClaim，已得到错误的 `verified_done`。

### 先补 Red

1. 复用 filesystem digest/readback criterion 测试与 `_runtime` helper，新建 `reports/final.md`，内容为 A。
2. 经受治理读工具取得 A 的真实 bytes digest / fact，作为 mandatory criterion 的验证证据。
3. 经现有 local_process 注册、精确 approval/lease 和 invoke 执行本地 Python，把文件变为 B，exit 0。
   命令与文件全部限于临时夹具，不调用 provider，不伪造执行结果代替这条核心复现。
4. 把真实 process result 纳入同一 Goal/revision 的事实，提交仍依赖 A 的 CompletionClaim。
5. Red 应显示旧证据仍被接受；修复后必须拒绝，且不能直接删除 mandatory criterion 来通过。
6. 再补“先跑成功验证，后续成功 process 改验证输入”的过程证据反例；不只测文件读回一种 oracle。

### 必须达到的行为

- **成功退出不等于无写入。** 成功但可能改写验证输入的命令不能保留旧验证有效性。
- 验证依据必须绑定到仍然有效的输入/产物身份；发现真实 mutation 后先重新取得必要验证，才可完成。
- 对同一可信输入、没有 mutation 的 tests/lint 等多项验证，仍存在有限步数内达成全部 mandatory criteria 的路径。
- 未执行（policy/prepare 拒绝）的命令不应无理由使已有效证据失效。
- 已执行失败/超时/unknown 的命令不能按“没成功”推断没有副作用。
- 原有受治理写入、workspace-write sandbox 失效规则保留；read-only sandbox 的信任必须来自已有实际隔离，不是模型自报。

### 实现选择边界

先检查现有 receipt、审批绑定、产物读回与 sandbox port 能否表达可信验证输入。允许在必要位置增加窄字段与核验，优先复用已有 port。
在 RESULTS 记下选定机制、可信来源和覆盖范围，不要只改一个条件然后用全套旧测试 Green 宣布解决。

可接受的思路是有证据的输入版本/不可变输入绑定，或已有强制只读边界上的验证；不能用 argv 包含 `pytest`/`ruff`、命令名称或自报 `read_only=true` 来认定无写入。
优先评估复用已有 read-only native sandbox，但不得静默替换用户批准的执行权限或命令合同；不可用时准确说明，不反复交替跑 tests/lint。
若考虑单个复合验证，只能在不削弱用户原 mandatory criteria 且确有一条可执行、可核对的验证路径时采用；不得把“跑过一个命令”偷换成“所有验证通过”。

仅前后 workspace hash 相同不等价于 OS 强制只读：临时改后恢复、未覆盖外部输入和派生进程都需界定。
如采用有界输入摘要，必须明确其受信任过程、输入覆盖和并发边界，缺失/溢出 fail closed；不要借本项新建通用不可变快照平台。

禁止：简单让每个 process 都作废前一个、导致 tests/lint 永久互相失效；每次扫描整个 home/私有目录；引入全盘快照平台；宽松信任旧 checkpoint。
无法在现有权限/输入范围内证明的外部或并发同 UID 写入边界必须明确保留，不声称解决任意主机并发一致性。

主要允许改动：`agent/runtime/evidence.py` 与必要的 `agent/process/*` receipt/执行绑定、`agent/runtime/contracts.py`/`checkpoint.py` 的最小合同接线，以及对应测试。不要顺便重构 loop。

## F2：浏览器正常 shutdown 后，重启无法补记资源关闭

### 事实与代码入口

- `agent/runtime/resource_lifecycle.py::active_task_resources`：成功 open 留下资源义务，只有 exact cleaned close fact 才消除。
- `agent/browser/tools.py::_session`：只认可本进程 `_active`；新进程无法取回旧 handle。
- `agent/composition.py::build_browser_resources` 的 closeables 当前只接 `environment.shutdown`；物理清理与 durable tool fact 脱节。
- `agent/browser/session_store.py` 已有 session identity/phase；优先检查能否在此保留正常关闭确认，不新建平行状态系统。
- helper：`tests/browser/test_tools.py` 的 `RecordingEnvironment`、`_context`，`tests/browser/test_composition.py` 的 composition/shutdown 测试。

### 先补 Red

1. 新建临时 workspace/profile/session root，经真实 composition 或同一注册/ToolRuntime 路径执行 browser_open，保存成功 fact。
2. 正常调用该 composition 的 shutdown；替身 environment 返回 CLEANED，并断言它真实收到 close/shutdown。
3. 用相同的临时持久存储创建一个**新的** composition/工具 owner，不能复用旧 `_active`。
4. 用原 session_ref 经 ToolRuntime prepare browser_close。当前会得到 binding_failure 或会话不在本进程。
5. 旧 open fact 仍让 resource gate 要求 browser_close；修复后必须能够在可信闭合凭据基础上，经正常工具结果路径补记 cleaned fact。
6. 将该 fact 放回真实完成流程，证明资源门槛解除而其他 mandatory evidence 仍受校验。

### 冻结的最小承诺

只要求：**正常 shutdown 获得底层 CLEANED，且最小可信闭合记录成功持久化后**，重启能用旧 opaque ref 正确收尾。
后台不得直接改 Goal/checkpoint 铸造成功；新进程不得重新打开浏览器来伪装关闭旧浏览器。

对于 SIGKILL/断电/物理清理后凭据落盘前崩溃，若无可信清理证明，仍为 UNKNOWN/未完成；清晰说明原因，不能因 PID 不存在、session 过期或 `_active` 为空就认定 CLEANED。
本轮不做任意 crash 的自动回收或新增 recovery loop。

### 必须保持

- 精确绑定 session、workspace/owner、browser identity 与已有存储完整性边界。
- 别的 session/工作区、损坏记录、过期 identity、cleanup UNKNOWN 都不能补记成功。
- 正常的重复 close/restart 不重复执行外部副作用，不错误释放其他 profile writer。
- 对 site-bound profile 的 exact writer lease，正常 cleanup 后仍正确释放；unknown 保留 quarantine/恢复义务。
- close 只消除资源义务，不覆盖其他未知工具 effect，也不直接完成 Goal。

主要允许改动：`agent/browser/tools.py`、`session_store.py` 及必要 contracts、`agent/composition.py` 的 owner shutdown 接线，必要的资源解释代码与对应测试。
`managed_web` 已有正常退出闭合记录可作设计参照，不复制第二套不一致的关闭机制，也不重写 managed_web。

本地真实验证复用 `scripts/browser_e3_fixture.py`、`scripts/browser_e3_journeys.py::RealBrowserFlow` 的测试设施。
不要默认启动完整 `run_018_e3.py` 的多轮 seal/wheel/promotion 流程。

## F3：Dogfood 验收必须基于执行证据，不得自证成功

### F3a：终态与操作证明

入口：`scripts/run_real_coding_scenario.py::DogfoodOperator.next_input`、`_merge_operational_checks`、`run`。

当前错误：`Task is closed.` 既可能是 CANCELLED 的 UI 提示，也可能是模型文本；审批提示则仅代表请求，并不代表已批准、已执行或已成功。

Red 至少覆盖：

1. 模型输出含 `Task is closed.`，真实 Goal 尚活跃，不得签完成。
2. 真实 CANCELLED 状态且最终文件恰巧正确，不得作为自主完成。
3. 只有 local_process/browser/managed_web 的审批提示，无成功 result，执行项必须 false。
4. 准备失败、拒绝、退出非零、超时、UNKNOWN cleanup，均不得借审批名单判通过。

修复要求：

- 保留文字只作 UI/operator 辅助；最终依据 typed RunResult/GoalStatus、绑定本次新建 workspace/state 的持久事实与 receipt。
- 优先复用 CLI 已有 typed renderer/result seam 或受保护的本次合成 state 读取路径，不增加 production loop。
- `product_ran_related_tests` 必须是本轮当前任务实际执行的相关验证命令成功，不能是任意 exit 0 的 local_process。命令/输入证据的新鲜性跟 F1 一致。
- 现有合法的 local_process 与 sandbox_exec 验证均可使用；不能把固定工具名名单当作语义校验。
- browser/server 使用证明要区分 open/start、实际操作、成功结果；cleanup 要有对应 exact resource 的闭合事实和必要底层检查。
- 外部 grader 自己跑的测试不能算作“产品自主运行测试”；指标与证明分开。

### F3b：D06 的独立行为检查

入口：`scripts/coding_scenario_grader.py::grade_d06`、`tests/acceptance/fixtures/d06_local_page`。

当前只检查文件存在并运行 candidate 的 `tests/app.test.mjs`。先写反例：server 立即报错、页面脚本抛异常、候选测试改成空通过，仍被判成功。

最小修复：只针对已存在的 D06，冻结外部断言/测试输入，使其位于产品可写 candidate 之外。
实际启动受管本地服务，使用专属本地浏览器验证“提交唯一测试项→列表出现该项→原行为不回归”，并核对本任务资源清理。
必须分别报告：产品实际做过的操作、独立 grader 的业务确认；后者不能替代前者。
可复用现有外置 Node 行为断言加产品浏览器真实 action/readback；不强制新建第二套浏览器控制器。
Node 结果只能证明相应 JS 行为，不能单独签 browser_behavior；browser readback 必须确实覆盖提交后的列表更新。

候选空测试、硬编码通过标记、正确文件名或静态源码字符串不能签 `browser_behavior=true`。
测试浏览器或本机端口不可用时，明确 NOT RUN/失败原因，不能退回 Node 断言后声称真实浏览器通过。
本轮不建设跨浏览器/任意站点矩阵。

### F3c：D04/D05 未证明的过程项诚实呈现

入口：`grade_d04`、`grade_d05` 与现有 TASK-MANIFEST。

- 最终 RetryService 行为正确，不证明运行中追加要求、重启无重述、没有 effect replay。
- AGENTS 文件存在、噪声文件数量足够、没有 `LEAKED_ENV.txt`，不证明遵从嵌套说明、截断后搜索、没有读取敏感路径。
- **保留原 required_checks，不删项降门槛。** 只能验证业务结果的项正常报告；没有过程证据的 required check 必须 false/未验证，并有 reason；整体 scenario 不得 PASS。
- 可以单独显示业务行为已通过，但不冒充完整场景通过。本轮不增加 correction/resume/secret-read instrumentation 新旅程，不读取任何真秘密。

### F3d：当前 producer/validator/授权合同一致

入口：`scripts/grade_coding_autonomy.py`、runner record 生成与既有 TASK-MANIFEST。

- 当前 runner 生成的字段与 validator 的 exact key set 不一致，缺 manifest digest/notes，且 source/fixture/grader 身份未完整绑定。
- 选择并记录一个最小、明确的记录形状，同步当前 writer 与 reader；不加接受任意旧 JSON 的宽松 fallback。
- 记录至少区分 First Agent 代码/安装来源、被测 candidate、manifest、fixture、独立 grader 身份；可用有界公开文件清单摘要，不收集秘密/真实日志。
- 请求计数记录本次 ledger 起止位置，不把旧 ledger 行数直接算作本次消耗；仅处理此次新建的测试 ledger。
- 离线 scripted 记录只能标 `offline_scripted`，validator 的 `RECORD_VALID` 只表示记录合同有效，不是产品 PASS。
- manifest 默认 `real_dispatch_authorized=false` 且预算为零。本轮不得改成批准状态。
- 在任何 provider 发送前拒绝零授权/零预算、模型配置不匹配；用 spy transport 证明零请求。不要把旧对话的授权或密钥硬写进包。
- 本轮只要求当前 runner 记录可被当前 validator 准确消费、坏记录 fail closed；不实现通用结果平台。

主要允许改动：上述 scripts、现有验收测试、必要的窄 typed adapter；不得为 grader 绕过 ToolRuntime 直接执行生产工具。

## F4：归档锁累积与会话容量

### 事实与 Red

`agent/runtime/checkpoint.py::retire_archived_snapshot` 保留 `.json.lock`；
`agent/continuity/sessions.py::_load_candidates` 却按所有目录项使用 `max_history_checkpoints * 3 + 1` 上限。

复用 `tests/continuity/test_session_retirement.py::_terminal_session`：

1. 新建临时 workspace/state，设 `max_history_checkpoints=2`。
2. 使用不同 UUID，循环创建 terminal 会话→preview archive→exact digest archive；每轮活跃 checkpoint 很少或为零。
3. 至少循环 12 次，逐次检查能继续创建/选择/归档，而不是只测试 2 次。
4. 当前审计第 6 轮归档即出现 enumeration bound 错误；不要把它当成真正历史容量满。
5. 结束后恢复首个 archive，核对 snapshot/evidence digest；再验证真有两个活跃 checkpoint 时容量仍正确拒绝第三个。

### 最小修复合同

- 存活 checkpoint 的容量与历史锁残留分离，不能仅提高常量把故障推迟。
- 保留 bounded I/O/memory、no-follow、owner/mode/nlink 校验，异常项仍 fail closed。
- archive preview token/CAS/restore 的不可变校验保持。
- 不能简单 unlink orphan lock：其他进程可能已经打开旧 inode 等待 flock；重建同名锁会造成两份锁同时被持有。
- 若方案涉及删除/替换锁，必须同时解决 open/flock/inode 竞态并加可控并发反例；不以 sleep 碰运气。
- 若采用清锁方案，需在取得 flock 后重验当前 pathname 与 fd 的 inode/设备和 checkpoint 对应关系；只做新进程校验不保证旧版本混跑安全。写明升级时相关旧进程必须退出，但不得自行停止用户进程。
- 优先在既有锁/扫描结构内找窄方案；若改布局，明确旧合成布局行为，不静默迁移或删用户真实 state。
- 不移除扫描安全上限来获得表面通过；证明测试规模增长下仍有明示的资源边界。

主要允许改动：`agent/continuity/sessions.py`、`agent/runtime/checkpoint.py` 及必要 archive 接线和相关测试。

## L1：只澄清限制，不建设调度/平台

`agent/automation/cli.py::main` 当前用 `core=None`，返回 `needs_019_config / host_profile_unavailable`。
本轮不接 host、不注册登录项。只核对 README、能力状态和本次 RESULTS 不把它称作开箱即用。
现有文档已准确时无需改；不为本包重写全部历史文档。

继续保留：macOS-first 沙箱、隔离 Chromium、受限 Memory/Skill/MCP/SubAgent、当前 candidate 等级。
真实 API 暂未重跑与安装态未证实分别写清，不能靠测试总数或版本号替代。

## 合作与改动合并

单 agent 按顺序实施即可。并行只适合独立测试/审查：F1 与 F4 可能都改 checkpoint，F2 与 F3 共享资源解释，不允许无协调同时修改。
明确文件 owner；任何协作者不得 reset/revert 别人的 dirty 工作。最终由一个 owner 汇总所有新反例、集成验证和 RESULTS。
