# 交给 coding agent 的执行入口

你要修复 my-first-agent 修复后 QA 中已复核的问题。此资料包独立可读，不需要原聊天记录、Oracle、Pi 或 Claude Code。

先读仓库根 AGENTS.md，然后按顺序完整读本目录 [AUDIT.md](AUDIT.md)、[WORK-PACKAGES.md](WORK-PACKAGES.md)、[VERIFICATION.md](VERIFICATION.md)、[CREDENTIALS.md](CREDENTIALS.md)。代码边界以 docs/architecture/KERNEL_ARCHITECTURE.md、EXTENSION_CONTRACTS.md、CURRENT_CAPABILITY_STATUS.md 为准。

目标：用户可以恢复无 Goal 的会话；在没有模型凭据时只读查看保存状态；可以找到帮助和 TUI 退出键；015 driver 帮助与测试不会意外递归启动全量验收。对于尚未装配的 Scheduler，提供准确的不可用说明。验收严格按本包，不把所有历史问题扩成新项目。

执行顺序：R5 → R1 → R2 → R3 → R4 → R6。R5 最先做，修掉测试递归风险后再允许运行最终 full suite。先 Red，再最小实现，再 focused Green；不要每改一个文案就全量重测。全部 implementation 完成后做一次 source full gate 和安装包回归。每个切片在 [RESULTS.md](RESULTS.md) 中留下结果。

工作树在接手前已很脏，HEAD 为 838cb2b66fbba674311d4d86fc7c4f4322fd8612（main ahead 7）；HEAD 不等于被测源码。相关文件起始字节见 [BASELINE.sha256](BASELINE.sha256)。指纹变化时先核对受影响区域，保留已有改动，不 reset/stash/覆盖用户内容。不要 commit/push/tag/改 remote；不修改旧 acceptance/seal/promotion 文件。根未跟踪 tui/ 为用户数据，不读取、不打包。agent/runtime、agent/tui 等已跟踪源码可以读改。

安全/架构合同：
- AgentRuntime.run_turn 仍是唯一 production model/tool loop 和已有 conversation state 变更入口。
- ContextManager 选上下文；ToolRuntime 执行 callable；CLI/TUI/新 status 入口只翻译或渲染。
- 恢复选择要重新检查显示时绑定的 revision、action_seq、conversation/Goal identity 和 workspace identity；不自动批准、不造 Goal、不使用最后修改时间猜用户选择。
- status 必须完全只读；不调用 open_workspace_session 的创建路径、不取 bootstrap write lock、不构造 provider/MCP/Browser/sandbox，不以 FakeProvider 兜底真实配置。
- effects 的 policy、approval、EXECUTING、durable result、unknown outcome、no-follow 和敏感路径约束保持。
- 本包授权改代码、文档和合成测试。最新用户补充另授权使用 CREDENTIALS.md 指定的新 DeepSeek key 做有界合成 dogfood；不授权增加登录项、launchd job、定时任务或外部账号操作。

所有 R1–R6 必做验收可离线完成，不依赖有效 key。离线修复后按 CREDENTIALS.md 使用最新凭据补做真实 DeepSeek 合成验证；不得为了 key 问题停下离线修复，也不从其他 Agent 私有配置或聊天记录取 key。新 key 仅保存交接，服务端有效性尚未验证；不猜旧认证失败的原因。

本包已选定的最小产品行为见 WORK-PACKAGES，不必逐条询问用户。若必须修改 durable checkpoint schema、引入新 model/tool loop、重绑旧 workspace、扩大批准或交付完整 Scheduler host，则超出本包：先记录具体缺口，继续独立可做的切片。

完成后交付：每个 R 的修改文件、Red/Green 证据、最终 wheel identity、installed probe、未验证项。可宣布“本包离线修复验收通过”，不可宣称“所有能力/真实模型端到端通过”。
