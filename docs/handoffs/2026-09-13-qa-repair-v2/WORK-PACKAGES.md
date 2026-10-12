# 可执行修复合同

## 固定范围

执行的是 R1–R6 的离线产品修复。避免新 registry/service locator、第二套 model/tool loop、durable schema 迁移、历史晋级重绑和后台安装。R2 的 status 是只读观察，不是新任务执行入口；R6 只修不可用说明，完整 Scheduler 功能仍 deferred。

## R5：先消除验收脚本递归（QA-06，P1）

文件：scripts/run_015_e3.py、tests/reference/test_015_e3_direct_script.py、test_015_e3_harness.py。按实际变化收窄。

先写 Red：
1. 在同进程导入 driver 后，以会抛 AssertionError 的 spy 替代 offline_gates_green/真实 provider factory。main(["--help"]) 应标准帮助 exit 0，spy 次数 0；未知参数 exit 2，spy 次数 0。
2. main([]) 仍按原 gate→config→real journey 顺序，不能跳过 seal/attestation。
3. direct-script 的 import 测试必须有正向成功 marker/exit 0，不能依赖“超时前没看到异常”。
4. subprocess interrupt/timeout 用本地合成子进程验证，整组退出可确认；cleanup 未确认时返回明确失败。

最小实现：
- 在 main 最开始使用 argparse 消费传入 argv（None 用 sys.argv[1:]）；不需要新增真实执行选项或 --skip-gates。
- 将 direct-script 测试拆为 bounded --help subprocess + runpy.run_path(..., run_name 非 __main__) 的正向 import/导出对象验证；测试隔离 argv。需要验证 config path 时注入 gate/provider，不启动真实 driver 全流程。
- _run 的取消/超时应管理本次 subprocess 与后代；可复用已存在且适配的 bounded process-group cleanup，禁止全局 pkill。只 catch KeyboardInterrupt 然后 exit 130 而留下 pytest 不算修复。
- 不把超时改成 PASS，不删 import/entrypoint 覆盖。
- 测试 environment 使用合成最小值，不继承真实 E3 key；即便意外进入 HTTP 路径也要由测试 transport/spies 阻止。

Green：两个现有 reference 测试文件和新增 bounded subprocess cleanup tests。此切片完成后才可以做最后全量 pytest。

## R1：让已展示的 conversation 都能安全选择（QA-01，P1）

文件：agent/continuity/sessions.py、main.py、tests/continuity/test_state_root.py、test_restart_selection.py、tests/cli/test_entrypoint.py。

已决定行为：
- 单一安全候选保持原自动恢复。
- 多个候选保留显式选择，标题改为 conversations/tasks；无 Goal 标为 conversation，不称 unfinished Goal。
- 每个可选择项显示有界 conversation identity 与状态以区分；不引入自动按 mtime 选最近会话。
- 用户可选择任一安全无 Goal conversation；选择仅加载/投影，不推进模型/工具、不改 checkpoint bytes。
- 不忽略无 Goal 会话，不清除历史，不自动新建/取消 Goal。

实现方向：
- 在 continuity startup 层增加或扩展一个“选择显示的 SessionCandidate”的窄接口。输入包含 conversation_id、expected_revision、next_action_seq、expected Goal identity（允许无 Goal）；目标必须出自本次可见 candidates。
- fresh-load 后核对该绑定、workspace scope/identity、Goal 有无是否发生变化、终态及未知结果；冲突要返回准确拒绝而非 traceback。
- 把已有 select_workspace_session(SelectGoal) 所用校验收束到共享私有选择逻辑，保留旧 SelectGoal 的严格非空语义。不要为了 CLI 选择将 runtime SelectGoal schema 改为可空；不要复制造成两份校验漂移。
- 无 Goal 候选必须有正确 workspace_binding；legacy unbound 行为保持。
- SELECT_REQUIRED 的列表界面和真正选择都使用当前身份，不允许任意 checkpoint 路径输入。
- _has_unknown_effect 的恢复边界保留；存在 pending disclosure/answering 的无 Goal 会话仍应恢复到原阶段。

验收矩阵：
1. fresh → /new → /exit → restart → 1 或 2 → ready，exit 0；两个场景独立测试。
2. 单无 Goal conversation 仍恢复同一 ID；已有 source facts 与 goal-proposal gate 保持。
3. 两个有不同问答内容的无 Goal conversation，选哪一个就加载哪一个；已有 checkpoint 全部 bytes 不变。
4. 多个有 Goal、混合 Goal/无 Goal、一个终态+一个活跃、pending disclosure、AWAITING_RECOVERY/EXECUTING 均准确。
5. selection 等待期间 revision/action_seq/Goal 有无/binding 漂移；过期编号、替换 workspace、symlink、corrupt checkpoint：拒绝且零 provider/effect。
6. history limit/max candidates/legacy unbound 原防护不变；显示的可选项不能全部不可选。
7. 同一路径覆盖 CLI 和 --tui 启动前 selection；不新增 TUI 自有状态机。

## R2：无凭据的只读 status（QA-03，P2）

文件：main.py；agent/continuity/sessions.py（只读发现接口）；agent/continuity/restart.py/现有 views（确有需要才改）；tests/cli/test_entrypoint.py、tests/continuity/test_state_root.py。

已决定接口：first-agent --workspace PATH --state-root PATH --status。输出已有 conversation/Goal 的有界 ID、状态、summary、pending approval/disclosure/unknown 标志和下一步指引。不自动选中或执行任何任务；多会话列有限摘要。不存在时显示 No saved conversations，exit 0 且不创建目录。错误/不安全状态 exit 2。

- 在 provider profile 解析和 credential 检查之前处理显式 --status。
- 不构造 provider、Web、MCP、Browser、Memory、SubAgent、sandbox probe；不读取 credential/profile 私有内容；不调用 Runtime.run_turn。
- 与 setup/setup-web、--tui、Memory create 等执行性参数冲突时先 exit 2；允许用户沿用非秘密 provider 选项，但 status 不消费这些值。
- 新只读发现函数沿用 workspace identity 与 no-follow/owner-only 有界 loader。逐级验证 state-root/workspaces/scope 目录；零 initialize、mkdir、touch、write lock。避免先 resolve() 跟随不可信 state root symlink。
- 当前 workspace binding 不符只显示需重新确认身份的诊断，不展示错绑 conversation summary。
- 从 durable snapshot 派生 summary/status；不能展示完整 facts、批准参数、Memory 内容、源码路径或原始异常。
- CLI credential-missing/auth-failure 指引可提示 --status 和当前变量名；不建议在命令中粘贴 key。
- 本切片不允许无 credential 下执行 cancel/resolve/resume。它们可能推进 Runtime/provider/effect，属于另一个合同。原认证失败 exit 行为可保留。

Red/Green：
- 造真实合成 pending/unknown/普通/终态 checkpoint；抹掉测试环境所有 provider credentials，status 仍可查看。
- 构造 provider/build resources/run_turn spies，调用均为 0；目录树、checkpoint 和既有 lock 的 bytes/mtime/权限不变（不要求 atime 不变）。
- missing root 零创建；0755、symlink、错 workspace、损坏、超容量 fail closed；多个记录有界且安全净化。
- provider auth 的 401/403 用 MockTransport 验证指引，不实际联网测试失效 key。
- 不向现有可恢复数据写新的 provider trust/profile。

## R3：交互帮助（QA-04，P2）

文件：agent/cli/app.py、必要的 agent/cli/render.py、main.py 的 help epilog、README；tests/cli/test_commands.py、test_contextual_decisions.py。

实现 /help（可选一个小纯帮助函数，不创建通用插件命令框架），unknown command 指向 /help，顶层 --help 提示进入交互后用 /help。

帮助覆盖实际存在的 /new、/sources、/leases、/browser-profiles、/pause、/resume、/cancel、/exit，以及 contextual y/n、unknown recovery 和已存在高级批准接口。按照当前可用状态说明限制，不能声称 /new 在 pending approval 下可用。

测试重点：/help 在 idle/pending approval/disclosure/recovery 都只输出文字，provider/tool 调用数、action_seq/revision/request binding 不变；未知命令同样不消耗 run。

## R4：TUI 退出键可见（QA-05，P2）

文件：agent/tui/app.py、必要的 agent/tui/render.py；tests/tui/test_app.py。

保留 Ctrl-C 复制语义；在 footer/现有 action hints 显示 Ctrl-Q: Quit。绑定继续指向现有 action_quit/request_close，不增加 force-exit 或真实 in-flight cancel。

使用 Textual Pilot 从输入框、approval/recovery form 焦点触发 Ctrl-Q：
- idle 正常退出，资源关闭一次。
- active worker 进入 closing_requested，不接收新 action；完成后安全退出。
- 超过 close deadline 时显示 shutdown_blocked，不强杀 worker、不能先关闭仍被使用的资源。
- 输入框 copy 键不被全局 quit 抢占。
- 不使用整屏 ANSI 文本匹配来证明这些语义。

## R6：准确说明 Scheduler 与当前验证范围（QA-02、QA-07）

文件：agent/automation/cli.py（帮助/未装配诊断）；必要的 agent/automation_hosts/macos_cli.py；README；CURRENT_CAPABILITY_STATUS.md 仅追加明确日期的普通可用性说明；tests/automation/test_cli.py、tests/automation_hosts/test_macos_cli.py。

本包选择“公开现状，保留开发接口”：
- first-agent-schedule --help 明确当前安装入口未提供可用 host composition；管理协议仅可由受信任 host composition 注入。
- 未装配的 list 等保持非成功 code/exit，不展示伪空列表，不假装 create 成功。
- 为保持 machine API，原 stdout JSON code/reason 不变；解释优先在 help/README，若增加 stderr 必须作为明确、经过测试的 CLI 约定。
- 不能告诉用户运行不存在的 setup-schedule 或提供不可工作的 state-root 参数。
- 不将 entrypoint 切到同样 unavailable 的 macos_cli，不能自动装 launchd。
- README 在一处小表说明：日常 CLI 实现及依赖、Browser 缺 extra、安全边界、Scheduler installed 不可用、真实模型本轮认证阻塞。保留历史记录和 candidate claim，不制造新 promotion。

验收：installed --help 清楚解释限制；installed list 仍 exit 2 且既有 JSON 合同保持；注入真实测试 core 的 CLI tests 仍通过；任何命令都不因本切片添加系统登录项。
状态用语：QA-02 功能缺口 deferred，用户提示 fixed。不得把它列为 Scheduler 实现完成。

