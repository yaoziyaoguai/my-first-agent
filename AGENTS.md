# AGENTS.md

本文件是 `/Users/jinkun.wang/work_space/my-first-agent` 的项目级规则。

## Project identity

- 项目名是 `my-first-agent`；它不是 Coding Agent 的身份。
- 默认在 `main` 工作。除非用户明确要求，不 commit、push、tag 或修改 remote。
- 当前产品是 Minimal Runtime Kernel foundation，不宣称已经是完整通用 Agent。

## Architecture invariants

- `AgentRuntime.run_turn` 是唯一 production model/tool loop 和状态变更入口。
- `ContextManager` 独占模型上下文选择；`ToolRuntime` 独占 tool callable 调用。
- CLI/headless 只翻译 typed action 和渲染 event/result。
- Provider adapter 只做 `ContextPack → ModelResponse`；不能推进 state 或执行工具。
- 所有副作用都走 policy/approval、`EXECUTING` checkpoint 与 result checkpoint。
- 不得加入第二套 loop、service locator、compatibility fallback 或 dormant feature flag。
- Memory 需要另行批准的 immutable context-source seam；Skill/MCP/SubAgent 只能作为 governed tools；Scheduler 是 external caller；TUI/Evidence 是 event/action adapter。

架构依据：

- `docs/architecture/KERNEL_ARCHITECTURE.md`
- `docs/architecture/EXTENSION_CONTRACTS.md`
- `docs/plans/2026-07-18-001-refactor-minimal-runtime-kernel-plan.md`

## Scope and simplicity

- 只实现用户明确要求或当前合同必需的最小代码。
- 优先复用已有 port；不要为单次使用创建抽象。
- 修改必须可追溯到请求；不要顺手重构相邻代码。
- 新的关键注释/文档默认用中文，解释边界与原因，不逐行复述代码。

## Safety

- 不读取或输出 `.env`、secret、credential、真实日志、会话、Memory/MCP/Skill/SubAgent 私有目录。
- 除非用户明确授权，不做真实 provider/MCP/外部网络调用。
- 凭据只在 composition root 注入，不进入 checkpoint、event 或 context。
- 文件工具保持 workspace-relative、no-follow、敏感路径拒绝、bounded I/O 和写入审批。
- `.ua/`、`graphify-out/` 等 Coding Agent 辅助产物不是产品运行时，不得打包或误当成能力。

## Development workflow

- 行为或架构变化先写 Red test，再做最小 Green 实现。
- 运行 touched-area tests；完成前运行：

```bash
git diff --check
.venv/bin/ruff check .
.venv/bin/python -m pytest -q -rx
```

- 测试失败、超时或输出截断都不能算通过。
- 工作树可能含用户未跟踪内容；不得删除、覆盖或纳入改动。

## Graphify

Graphify 是 Coding Agent 的代码理解辅助，不是 `my-first-agent` 产品能力。
当 `graphify-out/graph.json` 存在时，代码库问题优先使用 `graphify query/path/explain`；CLI 不可用时可只读现有 graph。修改代码后仅在确认不会摄入 ignored/private 输入时刷新，否则安全跳过并报告。
