# First Agent：日用闭环修复执行包

日期：2026-10-09。版本：1（已冻结；PACKAGE_READY / NOT_IMPLEMENTED）。
本轮交付的是执行资料，不是产品修复。所有待实施项初始为 NOT_STARTED。
已完成一次全新 Oracle Web 5/5 方案复核，并逐项对照源码裁决；详见 RESULTS 的咨询证据与取舍。

## 1. 给接手 Coding Agent 的指令

你要修复当前 First Agent 的日常工作与交互闭环，不是新增通用能力，也不是重启历史优化轮次。

1. 完整读仓库 `AGENTS.md`、本文件、[FIX-PLAN.md](FIX-PLAN.md)、[ACCEPTANCE.md](ACCEPTANCE.md)，然后读 [RESULTS.md](RESULTS.md)。
2. 以 [RESULTS.md](RESULTS.md) 为本轮唯一进度/决定/证据记录。项目整体能力等级仍由 [CURRENT_CAPABILITY_STATUS.md](../../architecture/CURRENT_CAPABILITY_STATUS.md) 管理，本包不授权晋级。
3. 核对实际工作树、公开文件 [BASELINE.sha256](BASELINE.sha256) 和各待办的当前实现。基线不同先定位差异，保留其他人的工作；不得 reset/checkout 覆盖。
4. 按 S1 → S2 → S3 实施。每个行为变更先写可复现 Red，再最小 Green；局部只跑受影响检查，不每改一处就重跑全量。
5. 不把测试替身、旧成绩或脚本输出的 passed 字符串当作生产链证据。必须满足 ACCEPTANCE 的因果断言。
6. 完成本包所有已授权、可安全推进的事项后，执行最终项目 gate 和隔离安装物 smoke；存在外部环境阻塞的项明确 NOT_RUN，不伪造 PASS。
7. 交付实际 diff 范围、Red/Green、完整命令/退出码、剩余边界和 RESULTS。完成后停止，不开启新一轮。不要 commit/push/tag、修改 remote 或发 PR。

本包不依赖 Oracle、Pi、Claude Code 或特定模型。可用 `dev_co` 管理交接、`tdd` 做实现；缺少技能时照本文执行，不为此安装新工具。不要求再次调用 Oracle，也不要求启动评审团队。

## 2. 成功的定义

用户能在当前受支持环境中，完成“提出任务 → 受治理执行 → 修改后同命令复测 → 查看可靠结果/恢复状态”，并连续使用现有前台而不丢草稿、混淆回答或被退出状态永久锁住。

- **本轮本地闭环**：DU-01–27 和最终 gates 全部通过；其中含脚本 provider +真实 Runtime/ToolRuntime、当前 macOS 的真实只读 sandbox，以及限定本地 Chromium 路径。缺环境须标验证缺口，不能仍签 LOCAL_CLOSED。
- **不是**：所有模型/任务的成功率保证、所有功能 production-ready、从零机器安装支持、跨平台支持、真实 API Dogfood 已通过。
- 产品实际可用边界、离线验证、真实本地进程/浏览器、真实远端模型四者必须分别报告。
- 无真实 API 授权时，真实模型门标为 NOT_RUN_UNAUTHORIZED；可以交付本地修复，不能称“完整真实 Dogfood 闭合”。

## 3. 当前事实与证据入口

- 项目：`/Users/jinkun.wang/work_space/my-first-agent`，默认 main。
- 编包时 HEAD：`838cb2b66fbba674311d4d86fc7c4f4322fd8612`；main 相对缓存 origin/main ahead 7，未 fetch。
- 当前存在大量既有 dirty/untracked 实现。HEAD 和旧 tag 都不代表完整当前源码。
- [2026-10-09 审计](../../audits/2026-10-09-agent-product-readiness-review.md) 是缺陷事实和复现入口；143 tests、Ruff、diff、窄 wheel smoke 是编包前审计成绩，不是本包修复成绩。
- 历史 [2026-10-02 修复记录](../2026-10-02-bounded-reliability-repair/RESULTS.md) 中旧 PASS 与未运行叙述并存；必须按证据日期/作用域解读，不能覆盖本次反例。
- 本轮 [Oracle 问题](ORACLE-PROMPT.md) 与 [独立答复](ORACLE-RESPONSE.md) 是设计依据，不是新增授权。最终以本包冻结的 FIX-PLAN / ACCEPTANCE 为实施合同；审计的愿望/候选项不自动入范围。

接手先运行：

```bash
pwd
git status --short --branch
git rev-parse HEAD
shasum -a 256 -c docs/handoffs/2026-10-09-daily-use-closure/BASELINE.sha256
```

hash 不匹配时只核实对应改动：已被他人修好的项先验证，不重复改；破坏了本合同前提时在 RESULTS 记录。不能恢复审计时的旧文件。

## 4. 架构与数据红线

- 唯一生产 loop / durable state owner：`AgentRuntime.run_turn`。唯一 context owner：ContextManager。唯一工具 callable owner：ToolRuntime。
- UI、headless、测试 driver 只提交 typed action、读取 snapshot 和展示 event/result。不得直接改 Goal、批准自己、构造成功 evidence 绕过真实操作。
- 保留 policy → approval → EXECUTING checkpoint → invoke → result checkpoint；未知副作用优先于暂停/取消/新任务。
- 不增加第二 loop、service locator、动态 registry、兼容 fallback、隐藏开关、通用快照/证明/调度平台。
- 不读取 .env、secret/credential、真实用户日志/会话、私有 Memory/MCP/Skill/SubAgent 数据、浏览器 profile 或未跟踪的仓库根 `tui/`。不要把 `agent/tui/` 公开源码与根 `tui/` 混淆。
- 本次自己新建的合成 workspace/state/profile 可为测试读取；不借此接触用户现有数据。
- 不调用真实模型/MCP/外站、不从历史对话提取 key；凭据值不得进入文档、命令回显、测试输出、checkpoint 或 evidence。
- 本地测试只允许临时 workspace、loopback 服务和专属测试 Chromium；不接管用户 Chrome，不注册/删除登录项，不改系统权限。
- 删除/终止前核对确属本次拥有的精确目录/进程。不可按 Chrome/python 名字全局 kill，不递归清理 home/仓库，不在 worker 活跃时删除其目录。

## 5. 范围外与停止条件

明确不做：新 Web/桌面 GUI；任意 PC 控制；新的 Skill/MCP/Memory/SubAgent 能力；并行 Agent 编排；后台常驻/调度 host 接线；launchd；跨设备/全平台移植；新模型/额度配置；全量 D01–D12；历史 promotion/seal 重绑；按行数拆大文件；全面重写 setup。

- 新发现若不阻断本包验收，记入 RESULTS 的范围外发现后继续原目标。
- 若必须读取真秘密、付费访问、改变安全/产品边界、删除非本任务资源或扩建基础设施，停止受影响项并请求用户决定，不把其它安全工作也无故停下。
- 环境缺少现有可选依赖时记录缺少什么、哪个检查未跑；不自动下载/全局安装、不退回 mock 后声称真实通过。
- 重复尝试没有新证据时更换诊断假设，不无限循环相同失败或昂贵测试。
- 不用“文档已写/旧测试 Green/局部 PASS”宣布包完成。以 ACCEPTANCE 的必需项和 RESULTS 为准。

## 6. 可以直接转发的任务

> 请从本文件开始，完整读取关联 FIX-PLAN、ACCEPTANCE、RESULTS 并核对 BASELINE。按三个切片完成本包，不新增范围。先证明反例，再最小修复，最后做一次完整 gate 和安装物检查。保留现有改动，不使用真实 API/私有数据，不 commit/push。逐项填写27条验收的证据与未证原因，完成后停止。遇到必须改变授权或安全边界的事项，停止该项说明理由，其它安全事项继续。
