# my-first-agent v0.4 Release Notes

## Release Theme

v0.4 把 my-first-agent 从「toy chat loop」推进到「**有边界的学习型 Agent
Runtime**」：所有 5 类 confirmation 与 tool/model output 都走统一的
`TransitionResult` 通道；runtime dependency（client / model_name /
max_loop_iterations）通过 `LoopContext` 依赖注入与 durable state 解耦；
`checkpoint/resume` 加 4 项守卫防 runtime-only 类型泄漏；新增本地日志治理
MVP（warning + dry-run inventory + 受确认 archive `--apply`）。

v0.4 仍是**单用户本地 CLI / TUI 项目**，不接真实 LLM / MCP / HTTP / Shell
/ Web UI，不引入新依赖，不做大规模重构。

## Highlights

### 1) Runtime Transition Boundary

- **ToolFailure** 走 `TransitionResult`（commit `df9825b`，pre-slice
  `9882744`）
- **ToolSuccess** 走 `TransitionResult`（`147602f`）
- **ModelOutput classification** 集中到边界函数（`ee51294`）
- 5 类 **confirmation** 全部 transition 化：
  - plan confirmation（`70ed25f`，pre-test `638beaf`）
  - step confirmation（`30b4176`）
  - tool confirmation（`682b3a6`，pre-test `46ef944`）
  - user_input confirmation（pre-test `eb75714`，复用 v0.3 transition）
  - feedback_intent confirmation（`f22dc4b`，pre-test `e243d37`）

### 2) LoopContext / Core Boundary Prep（Phase 2）

- 新增 `agent/loop_context.py`，`LoopContext` 是 frozen dataclass，
  3 字段（client / model_name / max_loop_iterations）（`5fb38e1`，
  pre-test `af358e8`）
- planning helpers `_run_planning_phase` / `_start_planning_for_handler`
  通过 `loop_ctx` 接收依赖（`9a00cf6`）
- `_run_main_loop → _call_model` 携带 `loop_ctx`（`ac3c6c1`）
- `MAX_LOOP_ITERATIONS` 默认值通过 `loop_ctx.max_loop_iterations` 消费
  （`a68cd12`）
- handler dependency AST 守卫钉死 `confirm_handlers.py` 不准 import 或
  构造 LoopContext（`9fc7500`）
- LoopContext SSOT：仅在 `agent/core.py` 一处构造

### 3) Checkpoint / Resume Guard

- checkpoint JSON **不泄漏** runtime-only 类型名（`37f2125`）
- malicious checkpoint 中 `loop_ctx / client / model_name / transition_result
  / runtime_event / _loop_ctx / callbacks` 等 runtime-only 字段被
  `_filter_to_declared_fields` 过滤（`37f2125`）
- guard 边界 docstring 强化 + fixture invariant self-check（`c03c12c`）
- `working_summary` 在 resume 中 roundtrip 完整（`08e4229`）

### 4) Local Log Governance（v0.4 主线 A）

- `python main.py logs cleanup`（`91e7bc3`）
  - DRY RUN inventory：列出 `agent_log.jsonl` / `sessions/` / `runs/` 的
    路径 / 大小 / gitignored / git_tracked
  - 零副作用、零内容读取
  - ≥10MB 打 `[LARGE]` 标记（与 v0.2 `health/check_log_size` 阈值一致）
- `python main.py logs cleanup --apply`（`149a98e`）
  - 仅对 `agent_log.jsonl` 做受确认的**原子 rename**
    （`Path.rename` → `<stem>.archived-YYYYMMDD-HHMMSS.<suffix>`）
  - 默认仍 dry-run；`--apply` 必须输入精确 `'yes'` 二次确认
  - 目标已存在拒绝覆盖（防 1 秒内重复 `--apply` 竞态）
  - **不** gzip / **不** 删除 / **不** 读取内容
  - **不**动 `sessions/` / `runs/` / `.env`
  - 不需要 file lock（`agent/logger.py` 不持久 fd，rename 后下一次
    `log_event` 自动创建新 `agent_log.jsonl`）

### 5) Safety / Repo Hygiene

- `.env` / `agent_log.jsonl` / `sessions/` / `runs/` 全在 `.gitignore`
  且**未被 track**（v0.4 全程未 commit 任何敏感/巨大产物）
- ruff baseline 持续绿
- 测试纪律：本版本未删任何测试，未新增 skip / xfail；本 v0.4 周期所有新增
  测试均**强化断言**（AST 守卫、fixture invariant self-check、6 种 wrong
  confirm 变体）

## Tests

最近一次完整运行结果：

- `pytest -q`：**815 passed, 3 xfailed**
- `ruff check .`：All checks passed
- 关键测试文件：
  - `tests/test_v0_4_transition_boundaries.py`（v0.4 transition 边界，
    含 89 项 + Phase 2.3 handler AST 守卫）
  - `tests/test_core_loop_boundaries.py`（core loop SSOT 守卫）
  - `tests/test_checkpoint_resume_semantics.py`（16 项，含 runtime
    leak / malicious key drop / working_summary 三项 v0.4 新增守卫）
  - `tests/test_log_cleanup.py`（18 项：8 dry-run inventory + 10
    archive --apply）

3 个保留 xfail（均非本版本新增，文档完整、解锁条件明确）：

- `test_user_switches_topic_mid_task` —— v0.2 输入语义治理
- `test_textual_shell_escape_can_cancel_running_generation` —— v0.2
  cancel 生命周期 + v0.3 TUI Esc 集成
- `test_plain_cli_pasted_numbered_multiline_should_be_one_user_intent`
  —— v0.3 高级 TUI（paste burst）

## Non-goals（v0.4 明确**不**包含）

- TUI 升级（paste burst / 高级输入 / Esc 生成取消）
- Web UI
- 完整 `agent/core.py` slimming（813 行偏胖；属 Phase 3 / v0.5+）
- 真正自动 size-based / age-based log rotation
- gzip / 压缩
- `sessions/` / `runs/` cleanup `--apply`
- 真实 LLM / MCP / HTTP / Shell adapter（仍走 v0.3 mock 路径）
- `cancel_token` / generation lifecycle / 模型 stream abort
- 外部 telemetry
- 多用户 / 生产级系统
- 完整 plugin 架构
- checkpoint schema 大改

## Usage Notes

- 现有 CLI / runtime 行为完全向后兼容；v0.3 用法继续有效。
- 本地日志治理新入口：
  - `python main.py health` → 看 risk 等级 + 建议归档命令
  - `python main.py logs cleanup` → DRY RUN 清单（脚本可读）
  - `python main.py logs cleanup --apply` → 受确认 archive
    （仅 mv，仅 `agent_log.jsonl`，须键入 `yes`）
- 仍然**不要**把 `agent_log.jsonl` / `sessions/` / `runs/` 加入 git。
- v0.4 仍然是**本地学习型 Agent Runtime** 项目，不是生产级框架。

## Known Risks / Open Items

- `agent/core.py` 813 行偏胖；Phase 2 后边界清晰，但 slimming 留给 v0.5。
- `agent_log.jsonl` 仍按 append 增长；v0.4 提供手动 archive 工具，
  但**没有**自动 rotation。
- `sessions/` / `runs/` 治理（list / show / delete --dry-run）尚未做。
- checkpoint / resume 仍可继续补语义测试（如 conversation.messages 顺序、
  tool_traces 隔离）。
- TUI / display layer 不在 v0.4 范围。
- 上述 3 项保留 xfail 是真实产品 gap，需 v0.5+ 引入 cancel_token /
  paste burst / topic-switch 信号源才能转正。
- v0.5 仍需继续按"小 slice + 行为中性"节奏推进，不做大重构。

## Acknowledgements

Co-authored-by: Copilot
