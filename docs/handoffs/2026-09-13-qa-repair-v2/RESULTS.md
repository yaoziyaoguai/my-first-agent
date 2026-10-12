# 执行与审计记录

## 基线与范围

- 实施基线：`main`，HEAD `838cb2b66fbba674311d4d86fc7c4f4322fd8612`，分支接手时 ahead 7；既有 dirty tree 全部保留，HEAD 不等于本次被测源码。
- 按 `R5 → R1 → R2 → R3 → R4 → R6` 实施。没有新增第二套 model/tool loop、service locator、durable schema 迁移、登录项或后台服务。
- Graphify 仅用于已有图的只读定位；没有重建图或摄入 ignored/private 输入。
- 根目录未跟踪 `tui/` 未读取、未修改、未打包。本次未 commit、push、tag 或修改 remote。

## 逐切片结果

| 切片 | Red / 根因 | Green / 修改文件 | 结论 |
|---|---|---|---|
| R5 脚本和递归测试 | `--help`/未知参数在解析前进入 gate；旧 direct-script 测试可能递归启动完整 E3；超时/中断只管理 leader，不能证明后代清理 | `scripts/run_015_e3.py`、`tests/reference/test_015_e3_direct_script.py`、`tests/reference/test_015_e3_harness.py`；参数先解析，合成进程组按精确身份清理，身份无法确认时 fail closed；focused gate `41 passed` | fixed；未全局 `pkill`，没有把 timeout 当 PASS |
| R1 conversation 选择 | 列表展示无 Goal conversation，但选择路径只接受 `SelectGoal`，因此“看得见、选不了” | `agent/continuity/sessions.py`、`main.py`、`tests/continuity/test_state_root.py`、`tests/cli/test_entrypoint.py`；新增窄的 candidate 选择接口，共享 fresh-load 校验，复核 workspace binding、revision、action sequence、conversation/Goal identity | fixed；选择只加载/投影，不造 Goal、不调用 provider/tool、不改 checkpoint |
| R2 只读 status | 日常入口在查看状态前要求 provider/credential，且现有 open 路径可能创建目录或取写锁 | `agent/continuity/sessions.py`、`main.py`、`tests/continuity/test_state_root.py`、`tests/cli/test_entrypoint.py`、`tests/cli/test_everyday_entrypoint.py`；新增 `inspect_workspace_sessions` 与 `--status` 的只读早期路径 | fixed；missing root exit 0 且零创建；危险/损坏/错绑状态 fail closed；不构造 provider/runtime/effect |
| R3 CLI 帮助 | 交互 `/help` 被当作未知命令，用户无法在上下文内发现真实命令与限制 | `agent/cli/app.py`、`agent/cli/render.py`、`main.py` 及 CLI tests；加入纯帮助输出、unknown command 指引和顶层 help epilog | fixed；idle/approval/disclosure/recovery 下不消耗 model/tool/action sequence |
| R4 TUI Quit 提示 | Ctrl-Q 已有关闭语义但界面不可发现 | `agent/tui/app.py`、`agent/tui/render.py` 及 TUI tests；footer/action hints 显示 `Ctrl-Q: Quit`，保留 Ctrl-C copy | fixed；Pilot 覆盖输入框及 approval/recovery 焦点、active close 与 timeout blocked；未新增 force-exit |
| R6 不可用说明 | 安装了 `first-agent-schedule` 命令名，但默认入口没有 runnable host composition，帮助容易让人误以为功能可用 | `agent/automation/cli.py`、`README.md`、相关 automation tests；帮助明确 installed entrypoint unavailable，`list` 继续返回既有 `needs_019_config` 非成功合同 | 用户提示 fixed；完整 Scheduler 功能仍 deferred，未安装 macOS 登录项或后台 job |

R1–R6 的相关组合门禁在实现稳定后为 `205 passed`；随后真实 dogfood 暴露的额外保护改动，其 focused/broader 回归分别为 `11 passed`、`3 passed`、`78 passed`。这些数字是分阶段证据，不相加冒充全量测试数。

## 真实 dogfood 发现与最小补救

用户授权的仓库外凭据只通过本包 launcher 注入，未打印、未写入参数、checkpoint、event、wheel 或本文档。官方目标使用 `https://api.deepseek.com`、`/chat/completions`、`deepseek-v4-flash`，thinking disabled。

合成 workspace：`/private/tmp/first-agent-real-dogfood-v2.2k0BOd`。已执行结果：

- G1 PASS：真实认证成功；1 次模型请求；返回三句中文，无工具或副作用。
- G2 FAIL（产品/模型行为）：只读任务正确读取目标文件，但额外虚构并申请写入 `notes/todo-list.md`。审批被拒绝，文件未创建，未自动重试。
- G3 PASS：写入预览后拒绝；目标文件不存在，无重复审批。
- G4 PASS：批准第一次写入；外部改动使后续批准过期，旧批准未写入；新的预览保留外部改动，第二次批准只改目标标点。
- G5 FAIL（效率/产品行为）：模型先提出 pyenv shim；给出精确 Python 路径后仍反复 discovery/replan。该 journey 产生 58 次 HTTP 模型请求，且没有启动进程、没有生成文件。
- G6–G10 NOT RUN：G5 已使本轮累计达到 78 次模型 HTTP 请求，超过资料包的 50 次操作者总预算，因此停止真实网络 dogfood。ledger 未提供 usage，成本记为 unknown。

G5 暴露出“资料包只有操作者预算，没有产品原子 hard cap”。因此做了一个可直接追溯到真实故障的最小偏离修复：

- `main.py` 的日常入口现在每个用户 action 最多 8 次模型请求，`max_invalid_repairs=7`，到界后持久化暂停，用户可以 restart/resume/cancel；没有限制独立的新用户 action。
- 日常 system policy 明确：只读 inspect-and-answer 不得自行发明保存产物；用户给出精确 executable + argv 后应直接使用，不得转回 shim/discovery 循环。
- `tests/reference/test_016_first_agent_1_0.py`、`tests/reference/test_014_grounded_personal_knowledge.py`、`tests/cli/test_everyday_entrypoint.py` 覆盖 hard cap、恢复语义与 policy。测试内与该产品限制无关的长链行为使用显式 test-only limits，不弱化 production 配置。

这项补救只收紧现有 `AgentRuntime.run_turn` 的 limits 和提示合同，没有增加新 loop 或自授权路径。它能阻止再次出现 58-call 单 action，但不能证明当前模型在 G2/G5 场景会一次做对，因此不把真实模型矩阵标为完整通过。

## 最终候选与验证

- 最终源码身份：仍为上述 HEAD + 当前 dirty tree；本次没有提交。
- source static gates：`git diff --check` exit 0；`.venv/bin/ruff check .` exit 0。
- final full gate：`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -rx -x` exit 0，`3449 passed, 3 skipped in 393.73s`。此前一次被人工中断的输出不计为证据；本次从头到尾单进程完成。
- wheel：`/private/tmp/first-agent-final-v2.jhMT3i/dist/first_agent-1.0.0-py3-none-any.whl`；SHA-256 `d685d4205019c3339aeee5660f1ca3d7c234cba53cb43624d239d849c6d5a358`。
- 安装验证：非 editable 安装到 `/private/tmp/first-agent-final-v2.jhMT3i/venv`，`agent`/`main` 均从该 venv 的 `site-packages` 导入；该 venv 使用 `--system-site-packages`，所以依赖环境不是 clean isolation。
- installed probe：R1-select-1、R1-select-2、R3-interactive-help 全部通过；installed `--status` 在 missing root 下 exit 0 且不创建目录，合成 pending manifest 保持不变。
- installed TUI：真实终端可见 Ctrl-Q 并可退出；active close、deadline timeout 与资源关闭顺序由 Textual Pilot 回归证明，不把 idle 实测扩大解释为所有真实终端场景。
- installed Scheduler：`--help` 明确 unavailable；`list` exit 2 且 JSON code/reason 保持 `needs_019_config`。
- E3 driver：`--help` exit 0、未知参数 exit 2；无 gate/provider 业务执行；合成 timeout/interrupt/descendant cleanup 回归通过，结束后未发现本轮 driver/pytest/launcher/DeepSeek 残留进程。

## 未完成与诚实边界

- R1–R6 的离线修复和安装包回归完成。
- Scheduler runnable host composition 仍 deferred；本包只修正产品说明，没有交付后台调度功能。
- G2、G5 的自然语言决策质量未达到 PASS；本轮新增了行为提示和 8-call 成本保险丝，但按预算没有再次用真实 key 复测。
- G6–G10 未运行，真实模型的 Skill/MCP/Browser/Memory/SubAgent 丰富矩阵仍未被本轮证明。
- wheel 位于临时目录且依赖环境非纯净；它是本轮可复现候选证据，不是发布或 production-ready 声明。
