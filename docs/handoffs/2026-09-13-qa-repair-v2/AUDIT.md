# QA 审计：可信结论与勘误

日期：2026-09-13。输入为 [上轮 QA 报告](../../audits/2026-09-13-post-remediation-qa-dogfood.md)。本次重新对照当前源码和公开测试，并使用安装包合成复现。历史报告保留原样；本文件是本包的裁决依据。

## 结论及优先级

| 来源 | 复核结论 | 本包处理 |
|---|---|---|
| QA-01 | 确认 P1：启动枚举接受无 Goal 会话，但选择只接受 SelectGoal，产生死路 | R1：准确选择 conversation；保留历史与权限 |
| QA-02 | 确认生产装配缺口；不是单纯“缺一个用户配置” | R6：准确说明安装命令不可用；完整 host 装配 deferred |
| QA-03 | 确认无 credential 会阻断启动；fail-closed 本身正确，缺少离线状态入口是 P2 可恢复性缺口 | R2：独立只读 status；不做无 key 下的恢复执行 |
| QA-04 | 确认 /help 缺失与 unknown command 无指引，P2 | R3：只读命令帮助 |
| QA-05 | Ctrl-C 在 Textual Input 是 copy，不能据此断言取消坏了；退出键隐藏是 P2 发现性问题 | R4：显示 Ctrl-Q，保持安全退出语义 |
| QA-06 | 确认参数未解析；另发现 direct-script 测试启动含自身的 full suite，P1 测试可靠性风险 | R5：先解析参数，改掉递归测试，确保测试子进程收口 |
| QA-07 | README 已多处写 candidate，并非隐瞒全部状态；是信息组织建议，P3 | R6：针对本包实情做小范围可用性说明 |

## 源码证据与根因

### QA-01

- agent/continuity/sessions.py::_is_nonterminal 将 goal=None 当成 nonterminal。
- _open_workspace_session_locked 对多个候选返回 SELECT_REQUIRED。
- main.py::main 在选择后遇到 candidate.goal_id is None 即 exit 2。
- select_workspace_session 同时要求 SelectGoal 与非空 Goal，无法接纳被展示的无 Goal 候选。
- tests/continuity/test_restart_selection.py 已明确保护“单一无 Goal 闲聊会话原样恢复”。因此不能把所有无 Goal checkpoint 忽略，也不能删除它们。
- 无 Goal 不等于空：它可能有问答、来源、AWAITING_DISCLOSURE、限额暂停等状态。修复必须覆盖这些情况。

上轮实际只在一次菜单中选择了 1；“任意选项均失败”当时包含源码推断。本包 probe_installed.py 在两个独立全新合成场景中分别选择 1、2，作为可重复验证。该脚本只跑 FakeProvider 的 CLI，既不理解自然语言也不证明模型能力。

### QA-02

- pyproject.toml 将 first-agent-schedule 绑定到 agent.automation.cli:main。
- agent/automation/cli.py::main 固定 run_cli(core=None)，实际子命令返回 needs_019_config。
- agent/automation_hosts/macos_cli.py::main 的 factory 也固定抛 host_profile_unavailable；只更换 console entrypoint 没用。
- tests/automation/test_cli.py 与 tests/automation_hosts/test_macos_cli.py 注入 core/factory 测协议，不证明安装后的生产装配。
- 先前 daily-use 包明确未做 S3。此处有既存能力范围缺口，而非本轮已修好又退化的证据。

不能临时创建 MemoryRepository/Fake executor 来让 list 显示空列表；那会造出第二条“看似可用”路径。完整真实配置、持久仓库、workspace owner、provider/sandbox/browser、supervisor、显式 wake 需要独立交付合同。本包将缺口公开保留，不以文案修复冒充 scheduler 功能完成。

### QA-03 与认证阻塞

main.py 在调用 open_workspace_session 之前检查 credential，缺失即退出。open_workspace_session 会创建目录/checkpoint 和 bootstrap lock，所以把它提前调用不等于“只读状态查看”。

可复用的读取部件：WorkspaceIdentityV1.resolve、sessions.load_workspace_checkpoints（有界/no-follow）、LocalCheckpointStore.load、restart.project_restart 及 runtime 的现有只读视图。新只读查询必须校验 state root 及每层父目录、workspace binding；不存在时零创建。

上轮 OpenAI adapter 将 401 与 403 都映射为 provider_auth_error。transport ledger 只有发送前 attempt 计数，没有 HTTP status、response body、usage 或服务端推理记录。因此：
- 有证据证明一次本地 HTTP attempt 与产品返回 authentication failed。
- 没有证据确定是 key 过期/拼错、账户权限、服务端策略还是其他认证问题。
- “确认未进入推理”“成本为 0”“唯一原因是 key 失效”均不成立。
- model 名及 endpoint 的官方文档只能确认配置写法，不能证明请求成功。

本包不再发起真实调用。历史资料包中的 deepseek-flash 名称与当前 README 的 deepseek-v4-flash 不同；后续真实验证应重新核对官方 model 标识，不能照抄旧包自动切模型。

### QA-04 / QA-05

agent/cli/app.py::run_repl 与 _parse_action 缺 /help；Unknown command 没有帮助路径。
TUI 的 action_quit 已走 request_close：active worker 时等待安全收口，超时进入 shutdown_blocked。

当前已安装 Textual 的 Input 绑定 ctrl+c 到 copy；App 绑定 ctrl+q 到 quit，但 show=False。上轮 TUI 输出被截断，只能证明所见片段和 Ctrl-Q exit 0，不证明完整界面所有地方都没有帮助。建议用 Textual Pilot 验证提示与键盘行为，保留 Ctrl-C 复制，不强制抢占输入框键位。

### QA-06：新增重要发现

scripts/run_015_e3.py::main(argv=None) 没解析 argv 就执行 offline_gates_green。
tests/reference/test_015_e3_direct_script.py 启动无参数 E3 driver，等待 5 秒然后 proc.kill()；它只否定 ModuleNotFoundError，超时本身也算成功。
driver 的 offline gates 包含整个 pytest suite，suite 又包含同一测试：存在递归 full suite 启动路径。proc.kill() 只杀直接 driver；driver 创建的 pytest 后代没有明确的进程组清理证明。

本次没有执行该测试或重现递归进程树，避免扩大副作用。以上是源码确认的风险，不能把历史耗时全部归因于它。R5 完成前不要再用该 driver 做全量检查或 --help 探测。

## 本次审计验证

起始基线：HEAD 838cb2b66fbba674311d4d86fc7c4f4322fd8612，加已有 dirty tree。53 项定向现有测试通过（2.42s，exit 0）：
tests/continuity/test_state_root.py、test_restart_selection.py、tests/cli/test_entrypoint.py、test_commands.py、tests/automation/test_cli.py、tests/automation_hosts/test_macos_cli.py。

这些 Green 不覆盖新问题，不是修复完成证据。新的安装 probe 预期在当前未修候选上返回失败，实际记录见 RESULTS。

