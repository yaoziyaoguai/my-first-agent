# 源码导航与执行检查

这里只列已经存在的文件。不要为新工作包直接批量改完所有文件；每个小步先读相关实现和测试，
选最少改动。行号是审计时导航，指纹漂移后以实际定义为准。

## 1. 先读的仓库约束

- `AGENTS.md`
- `docs/architecture/KERNEL_ARCHITECTURE.md`（预算说明有已知漂移，不能据此推翻现代码）
- `docs/architecture/EXTENSION_CONTRACTS.md`
- `docs/architecture/CURRENT_CAPABILITY_STATUS.md`
- `docs/plans/2026-07-18-001-refactor-minimal-runtime-kernel-plan.md`

## 2. 现有扩展入口

| 工作包 | 现有实现入口 | 相关现有测试 |
|---|---|---|
| P0/P7 产品入口与安装 | `main.py`、`agent/cli/app.py`、`pyproject.toml` | `tests/cli/test_headless.py`、`test_entrypoint.py`、`test_016_packaging.py` |
| P1 Goal/evidence | `agent/runtime/state.py`、`contracts.py`、`evidence.py`、`loop.py` | `tests/continuity/test_goal_policy.py`、`test_verified_done.py`、`test_sandbox_verified_done.py`；`tests/process/test_j1_production_verified_done.py`、`test_artifact_approval_contract.py` |
| P2 预算/执行/授权 | `main.py:204`、`agent/runtime/loop.py`、`state.py`、`tools.py`、`tool_governance.py`、`agent/transport_audit.py` | `tests/kernel/test_runtime_limits.py`、`test_runtime_approval.py`、`test_runtime_errors.py`；`tests/provider/test_transport_audit.py`、`test_remote_disclosure.py` |
| P2/P3 UI/取消/增量 | `agent/cli/actions.py`、`app.py`、`render.py`；`agent/tui/adapter.py`、`app.py`、`render.py`；`agent/runtime/events.py`、`ports.py` | `tests/cli/test_commands.py`、`test_headless.py`；`tests/tui/test_app.py`、`test_approval_journey.py`；`tests/continuity/test_goal_controls.py` |
| P3 provider | `agent/provider/config.py`、`factory.py`、`openai_http.py`、`anthropic_http.py`、`normalize.py`、`profile.py`、`protocol.py` | `tests/provider/test_kernel_providers.py`、`test_continuity_control.py`、`test_provider_profile.py`、`test_transport_audit.py` |
| P4 仓库工具 | `agent/tools/file_ops.py`、`edit.py`、`write.py`、`directory.py`、`path_safety.py`、`agent/composition.py` | `tests/tools/test_workspace_search.py`、`test_file_tools.py`、`test_path_safety.py` |
| P4 上下文与工作记录 | `agent/runtime/context.py`、`context_control.py`、`context_source.py`、`compaction_rules.py`；`agent/continuity/compaction.py` | `tests/kernel/test_context_manager.py`、`test_context_budgeting.py`、`test_runtime_compaction.py`；`tests/continuity/test_compaction_groups.py`、`test_compaction_commit.py`、`test_context_goal_frame.py` |
| P5 执行环境 | `agent/process/tools.py`、`contracts.py`、`runner.py`、`group.py`、`admission.py`；`agent/sandbox/shell.py` | `tests/process/test_process_cleanup_recovery.py`、`test_runner_group_cleanup.py`、`test_tools.py`；`tests/continuity/test_sandbox_checkpoint.py` |
| P5 浏览器 | `agent/browser/url_policy.py:135`、`tools.py`、`ports.py`、`playwright_adapter.py`（含 BrowserEgressGuard）、`contracts.py` | `tests/browser/test_url_policy.py`、`test_egress_guard.py`、`test_browser_cleanup.py`、`test_tools.py`；`tests/continuity/test_browser_recovery.py` |
| P6 child | `agent/subagent/runner.py:41`、`process_runner.py`、`child.py`、`contracts.py`、`tools.py`、`runtime_factory.py` | `tests/subagent/test_runner.py`、`test_process_runner.py`、`test_integration.py`、`test_tools.py` |
| P6 既有扩展 | `agent/memory/source.py`、`store.py`、`tools.py`；`agent/skill/tools.py`、`catalog.py`；`agent/mcp/tools.py`、`bridge.py`、`safety.py` | `tests/memory/`、`tests/skill/`、`tests/mcp/` 的对应入口/组合/拒绝测试，按实际受影响文件选择 |
| P6 会话管理 | `agent/continuity/sessions.py`、`agent/runtime/checkpoint.py`、`main.py` | `tests/continuity/test_state_root.py`、`test_restart_selection.py`、`test_conversation_archive.py`；`tests/cli/test_entrypoint.py` |
| P7 架构守护 | `docs/architecture/`、`README.md`、`main.py` | `tests/architecture/test_cutover_absence.py`、`tests/cli/test_016_packaging.py` |

特别提醒：`agent/tui/` 是产品源码；根目录未跟踪的 `tui/` 不在范围。
`.ua/`、`graphify-out/` 和本 Coding Agent 的 Skill 不是产品能力，不能打包进去。
Graphify 如用于导航，只查现有图；不确认私有输入排除前不刷新。

## 3. 启动时的无副作用检查

在仓库根执行，每条分别确认 exit code，不用最后一条成功掩盖前面失败：

```sh
git status --short --branch
git rev-parse HEAD
shasum -a 256 -c docs/handoffs/2026-09-13-coding-autonomy-repair/BASELINE.sha256
```

指纹不匹配不是重置理由；记录 changed/missing，读取对应公开代码核对最新实现。
该清单不是全树封存，也不证明未列出的文件没变。

## 4. 优先复用的定向门禁

下面命令只覆盖当前已有回归；实施者仍需为新行为加入 Red。不同包不要把整组每次都跑。

P1：

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -rx tests/continuity/test_goal_policy.py tests/continuity/test_verified_done.py tests/continuity/test_sandbox_verified_done.py tests/process/test_artifact_approval_contract.py
```

P2/P3：

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -rx tests/kernel/test_runtime_limits.py tests/kernel/test_runtime_approval.py tests/kernel/test_runtime_errors.py tests/provider/test_transport_audit.py tests/provider/test_remote_disclosure.py tests/provider/test_kernel_providers.py tests/continuity/test_goal_controls.py tests/tui/test_app.py
```

P4：

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -rx tests/tools/test_workspace_search.py tests/tools/test_file_tools.py tests/tools/test_path_safety.py tests/kernel/test_context_manager.py tests/kernel/test_runtime_compaction.py tests/continuity/test_compaction_commit.py
```

P5：

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -rx tests/browser/test_url_policy.py tests/browser/test_egress_guard.py tests/browser/test_browser_cleanup.py tests/process/test_process_cleanup_recovery.py tests/process/test_runner_group_cleanup.py tests/continuity/test_browser_recovery.py
```

P6：先按改动选择具体测试文件；阶段闭合时可以运行对应目录：

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -rx tests/subagent tests/memory tests/skill tests/mcp tests/continuity/test_state_root.py tests/continuity/test_conversation_archive.py
```

源码稳定后的最终门禁：

```sh
git diff --check
.venv/bin/ruff check .
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -rx
```

完整收集退出码和未截断结果。超时/截断/缺 exit code 不算成功；skips 列明原因和不覆盖的能力。
全量只在最终候选稳定后运行，除非新的风险或全量发现问题要求再次验证。

## 5. 安装候选

复用项目已有的 wheel 验证做法：`pip wheel . --no-deps --no-build-isolation`，输出目录必须是
本次新建的准确临时目录。在新 venv 安装这个具体 wheel，记录 SHA-256、解释器版本和
`agent.__file__` / `main.__file__` 来自 site-packages。

不要直接复制旧包 `launch_deepseek.py` 的预算/模型配置或读取其凭据文档。本包应在选定当前
模型后复用产品入口及安全注入原则，新 launcher 如必需只能做 argv/凭据注入和驱动冻结用户输入，
不得 monkeypatch、生成答案、预定工具路线或自动审批。依赖下载另遵守当前网络授权。

新临时目录只容纳合成数据，不操作真实 state root。归档保留证据应使用准确路径和 manifest；
不得以清理为名删除工作树、用户历史或未知临时内容。

## 6. 必要的一手资料

P0/P7 的评测原则与 P2/P4 的长任务设计沿用上游审计的来源，执行者按实际技术决策复核：

- [Agent 评测：Anthropic](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
- [长任务 harness：Anthropic](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)
- [简单编码基线：mini-SWE-agent](https://mini-swe-agent.com/latest/)
- [运行环境与反馈：OpenAI](https://openai.com/index/harness-engineering/)
- [DeepSeek 官方文档入口](https://api-docs.deepseek.com/zh-cn/)：仅当当前选定模型属于此供应商时使用。

这些来源不授予外部写入或付费权限，不意味着必须照搬其架构，更不代表本项目具有它们的成绩。
