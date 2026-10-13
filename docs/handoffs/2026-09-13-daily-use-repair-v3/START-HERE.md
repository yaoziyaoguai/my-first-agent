# 日常可用性修复包：从这里开始

你要修复 `my-first-agent` 在普通工作中的五项已识别缺口。你是负责本仓库工作的 coding agent，不是这个产品的运行时身份。资料包自包含，不需要原聊天、Oracle、Pi 或 Claude Code。

## 阅读与执行顺序

1. 完整阅读仓库根 `AGENTS.md`。
2. 完整阅读本目录 [FINDINGS.md](FINDINGS.md)、[WORK-PACKAGES.md](WORK-PACKAGES.md)、[VERIFICATION.md](VERIFICATION.md)、[CREDENTIALS.md](CREDENTIALS.md)。
3. 核对 `docs/architecture/KERNEL_ARCHITECTURE.md` 与 `docs/architecture/EXTENSION_CONTRACTS.md`。当前能力声明见 `docs/architecture/CURRENT_CAPABILITY_STATUS.md`，旧 acceptance 不当成当前通过证据。
4. 执行 D0 → D1 → D2 → D3 → D4 → D5。D0 在任何真实调用前完成；D1–D4 可全部离线。逐项先行为 Red，再最小 Green，更新 [RESULTS.md](RESULTS.md)。

## 明确目标

- 操作者可以明确开放普通 `config/`、`pytest.ini` 等项目路径，真实敏感路径仍保持拒绝。
- 保存文件到不存在的父目录时，Agent 能通过准确审批创建目录再写文件。
- 同一 workspace 第 17 个及后续非终态 conversation 可以从启动列表找到和选择。
- 切换模型时可以显式不加载旧 owner preferences，继续使用原会话，无须删除数据或换 state root。
- 最新候选能够完成只读 TODO 和精确本地命令任务；用真正强制的请求预算复验，不以增加提示词代替任务完成证据。

## 已选定的最小行为

这些是本包的实现合同，无需重新做全面产品设计：

- D1 使用重复的 `--project-path RELATIVE_PATH` 参数，作为只由操作者提供的普通保留路径例外；默认策略保留。具体边界见 D1。
- D2 新增单层 `make_directory` governed tool，逐层建立缺失父目录，各 effect 明确审批。`write_file` 继续只写文件，不引入目录树与文件的一体化事务。
- D3 使用启动列表 `n`/`p` 分页，每页不超过 16；仍只允许选择当前显示的精确 candidate。
- D4 使用 `--without-owner-preferences` 显式跳过全局 owner preference 的加载、source 和工具，不迁移/重绑旧库，不关闭用户显式配置的 workspace Memory。
- D0 在现有 transport attempt ledger 上增加可强制的累计模型请求上限；保留日常入口已有的每 action 8 次上限。

## 工作树与权限

起始 HEAD：`838cb2b66fbba674311d4d86fc7c4f4322fd8612`，`main` ahead 7，已有大量未提交改动。默认留在 main，不 commit/push/tag/改 remote，不 reset/stash/覆盖已有改动。相关起始文件见 [BASELINE.sha256](BASELINE.sha256)，指纹不匹配时先核对该区域，不能回滚覆盖。

根未跟踪 `tui/` 是用户数据，不读取、不打包；已跟踪 `agent/tui/` 是产品源码。不要读取 `.env`、真实会话、Memory/MCP/Skill 私有目录或其他 Agent 配置。本包的授权凭据例外仅限 CREDENTIALS 指定路径，且只在 D0 完成后用于合成 dogfood。禁止新增登录项、后台服务、真实外部账号操作和测试之外的命令执行。

本轮资料包制作只准备文件及离线探针。用户将此入口交给你并要求执行后，按本包完成修复；不要要求用户逐条重复批准已确定的常规实现步骤。

## 架构不变量

`AgentRuntime.run_turn` 是唯一 production model/tool loop。`ContextManager` 选择上下文；`ToolRuntime` 调用 callable；CLI/TUI 只翻译 typed action 和投影。副作用保持 policy/approval → EXECUTING checkpoint → durable result；未知结果不重放。Provider 只转换请求/响应。不得新增旁路 loop、静默 fallback、可由模型修改的权限策略或 durable schema 迁移。

D1/D4 是操作者明确使用的入口参数，不能实现成自动扩权、偷偷跳过绑定错误或常驻 dormant feature flag。D0 的预算文件是操作者诊断记录，不能成为另一个任务状态机。

## 完成与停止

完整 Done：D0–D4 行为、安全反例、source gates、最终 wheel 安装检查通过，且 D5 必测真实任务通过。D5 外部阻塞/失败时可以交付已有离线修复，但必须标为部分完成，不能声称已达到完整 Done。资料包没有要求新增 Scheduler、并行 SubAgent、跨平台 sandbox 或重新晋级。

单次命令退出、提示词断言 Green、配置显示 ready 都不算整个任务完成。相同失败没有新证据时停止该真实案例，先离线诊断。凭据/额度/缺依赖导致真实验证无法进行，不妨碍完成独立的离线修复；此时必须说“离线完成，真实验证未完成”。
