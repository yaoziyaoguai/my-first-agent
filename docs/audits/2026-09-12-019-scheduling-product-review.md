# 019 调度与整体产品可用性复核

日期：2026-09-12。范围：当前工作树的调度入口、后台适配器、验收驱动与相关日常能力。
方法：源码检查、历史设计及产品基线复核、当前官方资料、聚焦测试。复核后按 TDD 修改了
manual/cold-wake 授权与预检查边界；没有注册系统任务。

## 判断

launchd 是 macOS 已有的进程管理器，本身不等于重型平台。019 的主要问题是：针对个人日常使用，
冷启动、持久控制协议和验收机制已经较完整，用户可直接启动并完成任务的路径却还没有贯通。
“工程设计偏重”是范围与产品价值的判断；本轮没有 CPU、内存或耗电基准，不能据此断言运行时耗资源。

019 原设计确实调研过业界。`docs/superpowers/specs/2026-08-28-durable-background-runs-design.md:39`
起分别记录 Codex、DeepSeek、持久调度系统和 Apple，893 行起列出来源。问题不在于没有调研，
而在于把个人 Agent 需求扩展成更强的无人值守控制平面后，没有先闭合轻量产品路径。

## 登录项具体是什么

产品 label 为 `com.my-first-agent.schedule`。`agent/automation_hosts/launchd.py:202` 生成一个
LaunchAgent：定期执行固定程序及 `reconcile` 参数，`RunAtLoad=False`，没有 `KeepAlive`。
bootstrap 使用当前用户的 `gui/<uid>` domain。它指 macOS 用户会话中的后台程序，
不涉及网站登录，也不提供模型账号认证。模型凭据是另一项配置。

作用是：交互程序已退出时，由操作系统再次启动一次调度检查。等待期间不需要模型进程常驻。
它不保证关机或睡眠期间按时执行，也不是自动唤醒电脑的电源管理设置。
如果只要求 Agent 运行期间的定时任务，就不需要依赖 OS 自启动。

设计已经明确“一个 owner store 一个全局 LaunchAgent”，不是一个任务一个登录项。
本轮只读查询当前 launchctl 列表和 LaunchAgents 文件名，未发现匹配 First Agent 的项目。
没有读取系统后台项目数据库，因此不能据此断言系统设置的历史展示记录已清空，
也不能把旧截图中的三项认定为当前三个活进程。

## 当前业界做法

| 实现 | 公开承诺 | 适用启示 |
|---|---|---|
| [DeepSeek Schedule](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/user/guide/schedule.md) | 提醒保存在原会话；活跃 Agent 空闲时提交普通 follow-up；进程关闭停止计时，恢复会话后处理过期提醒；dispatch 不等于完成 | 会话内调度可很轻，持久记录与 OS 自动启动是不同需求 |
| [Codex / OpenAI 本地 scheduled tasks](https://developers.openai.com/codex/app/automations) | 当前官方页面要求本地项目任务运行时电脑开着、桌面应用运行；CLI 不提供管理 UI | 本地自动化可以依赖已经运行的应用；公开行为不能用来推断其私有 timer 实现 |
| [Claude Code scheduled tasks](https://code.claude.com/docs/en/scheduled-tasks) | 区分 session `/loop`、Desktop 和 Cloud；session 任务只在进程运行且空闲时触发 | 不必用一种最强执行模式承担所有使用场景 |
| [Apple 定时任务](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/ScheduledJobs.html) | launchd 是系统提供的按需/定时启动机制；睡眠和关机影响触发 | 确实需要退出应用后工作时，一个可选系统适配器是合理方案 |

## 已确认的问题（按产品优先级）

### 1. 高：安装入口固定未装配，补配置文件也不能直接解决

`pyproject.toml:39` 将 `first-agent-schedule` 指向 `agent.automation.cli:main`；
`agent/automation/cli.py:236` 固定执行 `run_cli(core=None)`。另一个 macOS main
（`agent/automation_hosts/macos_cli.py:63`）同样固定构造 unavailable factory。
没有实际读取并绑定 host 配置的安装入口。

本轮真实调用 `first-agent-schedule list` 返回
`{"code":"needs_019_config","reason":"host_profile_unavailable"}`。
此前“只是本机缺少 host profile”的解释不充分：还存在产品装配缺口。
单独执行依赖注入的 core/host fixture，无法证明默认安装命令可用。

建议：先让普通安装命令能读取可信配置、列任务、手动执行一次；再验证外部触发。
读取任务列表不应该要求先具备运行全部工具的环境。

### 2. 已修复：可选唤醒与新任务批准耦合

原实现无条件要求 `wake_qualified`；`preview` 会检查唤醒 readback，`approve` 在适配器
absent 时安装它。用户无法在没有唤醒适配器时批准新的手动任务。

原有 `tests/automation/test_composition.py` 的“没有 cold wake 也能手动 reconcile”测试
先构造已批准任务，再移除 wake；它还明确断言此时 preview 抛出 `wake qualification`。
因此它只证明已批准任务可以手动触发，未证明用户从零创建轻量任务的完整路径。

处置：`wake_adapter_policy_digest=None` 现在表示 manual reconcile，可在无 wake 资格时完成
create/preview/approve，且不会调用安装适配器。cold-wake definition 必须先由 owner 显式执行
`wake enable`；approve 只做精确 readback，absent 返回 `wake_not_enabled`，unknown/drift 返回
`wake_state_unknown`，不再把批准任务变成安装 macOS 后台项的隐式授权。

### 3. 高：019 的真实基础设施 E3 没有证明真实模型完成日常后台任务

`scripts/_019_macos_u2b_host.py:152` 使用 `_U2BProvider`，它是确定性 fixture。
该 fixture 先执行 `sandbox_exec`，随后因为缺少所需 `local_process` 完成回执而提交
`BlockedClaim`。`scripts/run_019_macos_e3.py:660` 的
`authoritative_terminal_observed` 对应 `blocked_terminal`。

这能证明真实 launchd、隔离进程和安全终态，不证明真实模型完成用户目标。
不能将修复方向解释为给后台放开 `local_process`：应先核对“要求执行一个命令”的完成标准能否
认可已有 sandbox 的可信回执，保持沙箱边界，并补充真正完成任务的安装入口验收。

### 4. 已修复：普通预检查不再注册系统后台项

原来的 preflight 在 prerequisites 通过后调用真实 wake probe，并在标准用户 LaunchAgents
目录注册带唯一后缀的测试任务再卸载；测试程序也叫
`first-agent-schedule`。独立实测和多次预检查都可能注册不同身份。

因此多项同名展示有可解释的代码路径，但本轮没有证明旧截图中的每条记录对应哪次测试。
进程和 plist 清理成功也不能证明系统设置展示的历史记录立即消失。

处置：`--preflight` 现在保持只读并以 `launchd_wake_not_probed` 明确表示未做系统探测；
只有显式 `--probe-launchd` 或完整 `--run` 才调用临时 LaunchAgent 注册/观察/清理流程。

### 5. 中：面向人的操作仍暴露过多内部协议

`agent/automation/cli.py:45` 的 create/update 要求 definition JSON，pause/resume/cancel
要求 expected-token 与 next-token，approve 还要求 preview digest。这些内部并发和授权约束
有必要，但目前没有把它们转成用户能直接理解的“时间、任务、目录、次数、预算、暂停”流程。

建议：由薄 CLI/UI 适配层生成内部 token、展示可信预览并提交已有 typed action；冲突时刷新预览。
不另建 controller，不去掉 CAS，也不让模型批准自己。

### 6. 中：真实模型支持和可见反馈仍存在组合缺口

本轮之前已验证：Pi 的智谱 `glm-5.3` 在显式关闭 thinking 后可完成最小真实生成；
OpenAI-compatible normalize（`agent/provider/normalize.py:1210` 附近）拒绝额外 message 字段，
会使某些默认 reasoning 响应不可用。Anthropic 分支已有针对 thinking block 的显式处理。
`agent/provider/openai_http.py:1` 仍是非流式，智谱的这条验证路径不能享受 Anthropic 分支的流式显示。

严格拒绝未支持协议保护了内核，但不等于已经解决用户的模型兼容和等待体验。
建议：针对用户实际使用的一条模型路线完成配置、工具调用、连续多轮、失败恢复和反馈验收，
再决定是否需要扩展 adapter；不要把只读检查就绪或单轮回答当成全部能力可用。

### 7. 高：产品结果正确性证据弱于基础设施证据

`docs/audits/2026-09-10-product-baseline-tasks.md` 已记录：一个 CSV 报告的 12 组 errors 计数
中 3 组错误，但任务仍进入 `COMPLETED / VERIFIED_DONE`。该记录也说明模型当时直接心算，
未用可用工具重算。本轮没有重跑旧任务，不能断言同一错误今天一定复现。

这不是要删除完成检查，而是说明“文件存在、读取成功、过程有回执”与“报告数字正确”仍有距离。
最有价值的补证是实际任务的独立 ground truth：统计脚本重算、代码测试、引用原文核对。
另一个已记录待复核点是 `/approve-artifact <sha256> <path>` 对普通用户的负担，尤其新文件场景。

## 建议的收敛方向

1. 优先补通手动/活跃进程触发的完整使用路径，复用现有调度记录和唯一 Runtime。
2. 定时触发只向现有执行入口投递工作；等待不调用模型；忙时排队；错过多个周期不无限补跑；
   保留预算、截止时间、暂停和未知副作用恢复。是否引入活跃进程 timer 是待确认的产品合同调整。
3. 将“关闭交互程序后继续启动任务”作为明确开启的可选部署方式；macOS 只需要一个稳定命名
   的系统后台项。未来确需服务器再接服务器适配器，不为跨平台承诺提前建设。
4. 用一个真实模型从正常安装入口完成三类日常任务和一个定时任务，记录成功率、耗时、审批次数
   与产物正确性；再决定是否继续扩展 Memory、MCP、Skill 或 SubAgent。

保留：唯一 Runtime/ToolRuntime、审批与副作用回执、工作区保护、预算、进程清理、幂等防重。
这些约束保护真实风险。当前 owner-only Memory、隔离浏览器、受管扩展和单 child 的有限范围
本身不是缺陷，不应为了功能列表而增加向量库、并发框架或新的服务层。

## 本轮验证与局限

- Graphify 现有图只提供 Scheduler 历史文档关系，未覆盖足够的 019 实现细节；以上发现以实际
  源码和测试为准，没有重建图或扫描私有运行数据。
- `first-agent-schedule list` 真实入口复现固定 unavailable；`--help` 可用；该入口装配缺口仍未修复。
- manual/cold-wake 与只读 preflight 的 019 聚焦回归：`328 passed, 3 skipped`。
- 最终完整仓库回归：`3398 passed, 3 skipped in 366.52s`；`ruff check .` 与
  `git diff --check` 均通过。首次全仓回归暴露 3 个仍按“批准即安装”构造的 portable E3
  fixture；改为先显式 `wake enable` 后，96 项精确 E3 与最终全仓复跑均通过。
- 未运行真实 launchd E3，未注册后台项，未调用真实模型，也未 commit 或 push。
- 这是有重点的架构/产品复核，未做全仓安全审计和性能基准，不声称发现全部缺陷。
