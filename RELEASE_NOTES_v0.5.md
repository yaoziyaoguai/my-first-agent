# my-first-agent v0.5 Release Notes

> 本文件状态：**release notes 草稿**，commit 在 working branch；**未 tag v0.5.0**、**未 push**。
> tag 决策由人工 review 后单独执行。

## Release Theme

v0.5 的主线**不是**新 UI、不是新 LLM、不是新工具协议；
v0.5 的主线是 **runtime / observer 边界治理与本地证据链对齐**：

- 把主循环里临时变量打包成 `LoopContext`（4a002d6）
- 把 5 类 confirmation transition 的依赖打包成 `ConfirmationContext`（e167125）
- 给本地 `sessions/` 与 `runs/` 增加只读 inventory dry-run（1016738）
- 把 v0.5 之前散落在多文件的 observer 设计假设落成一份审计文档（5f0d024）
- 把 5 个 confirmation handler 的决策出口接入 observer JSONL（17c5262）
- 给同名不同签名的 `log_event` 加 docstring 边界 + signature 守卫（d83ba78）
- 把 `agent/core.py` 三处 user-facing terminal diagnostic `print()` 路由到 RuntimeEvent sink，保留 stdout fallback（49b3816 baseline + 00aa28c migration）

`v0.5` **不**包含真实 LLM、真实 MCP、真实 HTTP/Shell、Web UI、TUI 重写、checkpoint/resume 改造、`_dispatch_pending_confirmation` 重构、StateSnapshot helper、observer 重命名。

## Completed Slices

| # | Slice | Commit | 主要文件 | 改 runtime 行为? | 测试 | 风险备注 |
|---:|---|---|---|---|---|---|
| 1 | `_build_loop_context` helper | `4a002d6` | `agent/core.py`, tests | 否（重构等价；行为完全保持） | 是 | 0 |
| 2 | `_build_confirmation_context` helper | `e167125` | `agent/core.py`, tests | 否（重构等价） | 是 | 0 |
| 3 | sessions/runs inventory dry-run | `1016738` | `agent/local_artifacts.py`, `main.py`, tests | 否（只读 CLI 子命令；不写 fs，不读真实 sessions/runs 正文） | 是 | 0 |
| 4 | observer evidence-chain audit doc | `5f0d024` | `docs/V0_5_OBSERVER_AUDIT.md` | 否（纯文档） | 否 | 0 |
| 5 | confirmation observer evidence | `17c5262` | `agent/confirm_handlers.py`, tests | 是（**仅追加** observer JSONL 写入；不改 state / TransitionResult / `pending_*` 清理时机） | 是 | 低 |
| 6 | log_event signature boundary | `d83ba78` | `agent/logger.py`, `agent/runtime_observer.py` docstring + new test | 否（仅 docstring + inspect.signature 防回归断言；未重命名、未改调用点） | 是 | 0 |
| 7 | terminal diagnostics → RuntimeEvent sink | `49b3816`（baseline）+ `00aa28c`（migration） | `agent/core.py`（3 hunks at L306/L670/L789 + import）, `agent/display_events.py`（3 EVENT_* + 3 factory）, tests | 是（**callback fallthrough**：当 `on_runtime_event` 注入时，3 处诊断走 RuntimeEvent；当 callback 缺失时仍 print 到 stdout） | 是 | 中（见 §Behavior Changes / §Yellow Flags） |

## Behavior Changes

绝大多数 v0.5 切片是**行为中性**：1/2/3/4/6 不改 runtime 任何用户可见路径；5 仅追加 observer JSONL 写入。

唯一动到用户可见路径的是 `00aa28c`（slice 7 D）：

- **改了什么**：`agent/core.py` L306（state 不一致自愈）/ L670（`MAX_LOOP_ITERATIONS` 兜底）/ L789（未知 `stop_reason`）三处历史裸 `print()`。
- **怎么改的**：每处插入 `if turn_state.on_runtime_event is not None: turn_state.on_runtime_event(_evt) else: print(render_runtime_event_for_cli(_evt))` 双向分支。L306 早于 `_emit_runtime_event` 闭包定义、早于 `turn_state` 构造，使用 `chat()` 参数 `on_runtime_event`；L670 / L789 使用 `turn_state.on_runtime_event`。
- **保留了什么**：
  - 无 callback 模式（默认 simple CLI、`main.py --shell`）下 stdout 仍然可见，文案与 v0.4 完全一致。
  - 上方 / 下方 `log_runtime_event(...)` observer JSONL 写入未触动。
  - `clear_checkpoint` / `state.reset_task` / 函数 return value 未触动。
  - `_emit_runtime_event` 闭包内 ASSISTANT_DELTA fallback（L338 / L345 / L350）未触动（AST guard 钉住 `print==3`）。
  - `DEBUG_PROTOCOL=False` 双开关守卫的 16 处 protocol dump print 未触动。
- **不改了什么**：confirmation 分发、checkpoint/resume schema、messages / prompt / provider / compression、`runtime_observer.RuntimeEventKind` 枚举、`agent/logger.log_event` legacy 调用点。

## Quality Gates

最近一次本地验证（last verified at slice 7 D commit `00aa28c`）：

- pytest: **867 passed / 3 xfailed**（3 xfail 全部为已记录的 v0.2 / v0.3 backlog：topic-switch / Esc cancel / paste burst；本轮未新增、未删除、未弱化任何 xfail）
- ruff: All checks passed
- smoke: `health` / `health --json` / `logs --tail 3` / `--shell quit` 全绿
- `git diff --check`: clean
- sensitive files：`.env` / `agent_log.jsonl` / `sessions/` / `runs/` 未被 git track

本次 release notes commit 为 docs-only，不再重跑 pytest；ruff + `git diff --check` 仍执行。

## Known Yellow Flags / Backlog

### YF1 · callback exception contract（v0.5.1 候选）

- **问题描述**：`agent/core.py` L306 / L670 / L789 三处 D 迁移点，以及 `_emit_runtime_event` 闭包内 L335 / L342 / L348 三处既有 callback 调用点，均采用 `if cb is not None: cb(_evt)` 直接调用模式。若 callback 实现内 `raise`，异常会沿调用栈冒到 `chat()` 调用方，可能干扰 `state.reset_task` / `clear_checkpoint` / 紧邻的 `log_runtime_event(...)` observer 写入。
- **是否 release blocker**：**否（yellow flag）**。理由：
  1. 默认 simple CLI 与 `--shell` 路径不传 callback → stdout fallback 路径不受影响；
  2. 已被 v0.4 release 接受的 `_emit_runtime_event` 闭包用同样契约；00aa28c 没有把 contract 变得更弱，只是把 callback 触达面从 3 个 ASSISTANT_DELTA fallback 扩到 6 个 user-facing diagnostic；
  3. 历史裸 `print()` 同样可能在 stdout 关闭 / pipe broken 场景下 raise，对称性未改变；
  4. 测试 867/3 全绿覆盖主路径与 fallback 路径。
- **涉及文件**：`agent/core.py`（6 个 callback 调用点）、`agent/display_events.py`（factory 不需改）、`tests/test_core_loop_terminal_prints.py`（新增 contract 测试）。
- **建议 v0.5.1 最小测试**：传入 raising callback，断言 `state.reset_task()` 仍被调用、`clear_checkpoint` 仍被调用、紧邻的 `log_runtime_event` JSONL 写入仍发生、return value 不变。
- **建议 v0.5.1 最小修复边界**：在 `_emit_runtime_event` 闭包外抽一个 `_safe_invoke_runtime_event_sink(sink, evt)` helper，try/except 包住 callback；except 分支落 stdout fallback + observer JSONL 写一行 `event_type="runtime_event_sink.failed"`。**不**新增 dataclass、**不**改任何 callback 签名、**不**接 TUI。

### 其他 v0.5+ backlog

- `_dispatch_pending_confirmation` characterization tests（仍未做；tests-only，不抽 helper）
- checkpoint/resume evidence tests（v0.4 已较强；仅补 working_summary / pending_user_input_request roundtrip 边界）
- StateSnapshot helper audit-only 设计文档（不接入 runtime）
- `runtime_observer` rename design only（不改代码；docs/V0_5_OBSERVER_AUDIT.md §G4 已守卫）
- local artifacts governance 设计（sessions/runs cleanup policy；不实现 apply）

## Tag Plan

- **本轮不自动 tag**。
- 下一轮如确认 release notes 合格，再单独决策是否打 `v0.5.0`。
- tag 前必须再次确认：
  1. working tree clean；
  2. ahead/behind = 0/0；
  3. HEAD on origin/main；
  4. `.env` / `agent_log.jsonl` / `sessions/` / `runs/` 未被 git track；
  5. pytest / ruff / smoke 重新跑一遍。

## Acknowledgements

v0.5 切片严格遵守"每切片一个 commit、每 commit 一个验证轮、每 commit 在 push 前可独立审计"的纪律；3 个历史 strict xfail（topic-switch / Esc cancel / paste burst）原因不变、归属不变、转正条件不变。
