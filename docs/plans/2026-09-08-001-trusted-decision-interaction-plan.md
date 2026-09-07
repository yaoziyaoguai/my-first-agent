# 2026-09-08-001 Trusted Decision Interaction Plan

## Outcome

终端里的决策请求做到"所见即所批"：用户在终端看到的 pending 决策提示，来自读取输入前
获取的同一个 authoritative checkpoint snapshot；该次输入解析出的 typed action 与
`run_turn` 严格绑定到该 snapshot。若等待输入期间 store 漂移（A→B），现有
expected_revision / token CAS 使该答案零副作用地 fail closed（CONFLICT），绝不把答案
重绑到 B。

同时：

1. 可操作决策提示（approval / recovery / disclosure）的唯一权威是
   `TerminalRenderer.render_pending(state snapshot)`；pending 类 advisory event 不再
   产生第二个可操作提示（warning / informational 保留）。
2. artifact approval 不再显示通用 `[y/N]`，改为展示实际 artifact path 与精确命令格式
   `/approve-artifact <64-lowercase-hex-sha256> <actual-path>`，并说明 `no` 可拒绝；
   不自动填 digest。
3. `agent/sandbox/tools.py::_render_preview` 的 argv 渲染改为逐 token 无损表示
   （镜像 `agent/process/tools.py` 的 `json.dumps(token)` 做法），消除空格 join 造成的
   argv 边界碰撞。

## Non-goals

- 不改 `AgentRuntime.run_turn` 的任何行为；不增加第二套 loop、service locator、
  compatibility fallback、自动授权、重试或重绑定。
- 不改 action / schema / runtime core / contracts / reducer。
- 不扩展到 TUI、browser、scheduler、history、memory、MCP。
- 不改 `/approve-artifact` 的解析与 typed action 语义（已存在且正确）。

## 受保护边界

- `AgentRuntime.run_turn` 仍是唯一 production model/tool loop 与状态变更入口；CLI
  只做 snapshot 加载 → pending 投影 → 输入 → parse → `run_turn` 的翻译。
- 漂移时的零副作用由现有 CAS（`expected_revision` / snapshot token / lease）保证，
  本轮不新增任何冲突处理路径。
- `render_pending` 是只读投影；不暴露内部 request id / binding digest。

## 设计决定

1. `run_repl` 循环重排为：`snapshot = store.load()` → `renderer.render_pending(snapshot.state)`
   → `input_fn("> ")` → parse / run_turn 全部使用同一 snapshot。parse error、只读命令
   （`/sources` 等）与空输入走 `continue`，下一次输入前重新 load + render，答案始终绑定
   其所见 snapshot。
2. `main.py` 移除 `run_repl` 前的一次性 `renderer.render_pending(store.load().state)`：
   交互生命周期的 pending 渲染由 `run_repl` 独占负责，消除启动期双渲染。
3. `TerminalRenderer._event_message` 对 `APPROVAL_REQUESTED` / `RECOVERY_REQUESTED` /
   `DISCLOSURE_REQUESTED` 返回 None（与 `LIMIT_REACHED` 同理：RunResult 之后由
   authoritative state 的 `render_pending` 投影）；`WARNING` 保持输出。
4. `render_pending` 的 approval 分支传入
   `artifact_confirmation_requirement.artifact_path`；`_approval_message` 在该分支输出
   special command 提示（含实际 path、说明 `no` 拒绝、不含 `[y/N]`、不填 digest），
   普通 approval 保持 `Execute this operation? [y/N]`。
5. `_render_preview` argv 用 `" ".join(json.dumps(token) for token in argv)`：literal、
   稳定、可区分列表边界，换行/引号被转义，非 ASCII 以 `\uXXXX` 呈现。

## 文件范围（冻结）

- `agent/cli/app.py`（run_repl 循环重排）
- `agent/cli/render.py`（event 静音 + artifact prompt）
- `agent/sandbox/tools.py`（preview argv）
- `main.py`（移除重复初始 render_pending）
- `tests/cli/test_contextual_decisions.py`（A 竞态、B 输入前显示）
- `tests/cli/test_render.py`（C event 静音、D artifact prompt、render_pending 投影）
- `tests/sandbox/test_tools.py`（E preview 可区分性）
- 新建本 plan 文档。

## 测试计划（先 Red 后 Green）

- A：真实 `LocalCheckpointStore` 两调用者竞态——渲染 A 的 pending 后、input 返回
  `yes` 前 CAS 成 B；断言 recording runtime 收到的 action（request_id /
  expected_revision）与 snapshot 均为 A；再用真实 `AgentRuntime` 证明 drift 时
  `run_turn` 返回 CONFLICT、store 保持 B、provider 零调用。
- B：无任何 event 到达 renderer 时，approval / disclosure / recovery 在每次
  `input_fn` 调用前从 store 当前 snapshot 显示（启动与完成一次 action 后都覆盖）。
- C：`emit` 对三类 pending event 输出为空；WARNING 仍输出。
- D：artifact pending 的 render_pending 输出包含
  `/approve-artifact <64-lowercase-hex-sha256> artifact.out`、实际 path、拒绝说明；
  不含 `[y/N]`、不含 64 位 hex digest。
- E：`["a b","c"]` 与 `["a","b c"]` 的 preview 可区分；换行/引号 token 被转义，
  Unicode 安全呈现。

运行范围：`tests/cli/test_contextual_decisions.py tests/cli/test_render.py
tests/cli/test_commands.py tests/cli/test_walking_skeleton.py
tests/sandbox/test_tools.py`（必要时 `tests/process/test_artifact_approval_contract.py`），
最后对触及文件跑 `ruff check`。

## 验收合同

- 等待输入期间 store 漂移时：输入答案绑定的 request_id / expected_revision 属于其
  所见 snapshot；真实 runtime 路径 CONFLICT、零副作用、无重绑。
- 每次输入前的可操作提示与该输入使用的 snapshot 一致；event 丢失/延迟/重排不影响
  正确提示；pending event 不再产生可操作提示。
- artifact approval 提示含精确 special command 与实际 path；普通 approval 仍是
  `[y/N]`。
- sandbox preview 对 argv 边界无损。

## Implementation notes（实现偏差与验证结果）

1. **测试载体迁移**：为保持浏览器 approval preview 测试意图，
   `tests/cli/test_018_browser_experience.py` 的测试载体从 advisory
   `APPROVAL_REQUESTED` event 迁移为 authoritative
   `render_pending(state)`，断言强度未降低。
2. **J4 harness 修正**：全量门禁发现 `scripts/run_015_e3.py` 的 J4 harness 仍取
   `stop_messages[0]`；新 CLI 生命周期首条是 recovery pending、末条是 contextual
   stop。已改为末条，并在 `tests/reference/test_015_e3_harness.py` 新增两条 production
   投影的逐字验证。Red 为 1 failed / 3179 passed / 3 skipped；targeted Green 为 35
   passed。
3. **Pi 初审 P1**：独立 Pi 初审发现 sandbox executable / cwd 未 JSON quote 的 P1；
   补齐 executable / cwd / argv 三者后 fresh 复审 PASS，无 P0/P1/P2。
4. **验证状态**：focused 最终为 184 passed；最终全量重跑已由 Codex 执行：
   `.venv/bin/python -m pytest -q -rx` → 3180 passed, 3 skipped in 350.30s
   （exit 0）；`.venv/bin/ruff check .` → All checks passed（exit 0）；
   `git diff --check` → 通过（exit 0）。
5. **范围澄清**：`tests/cli/test_018_browser_experience.py` 与
   `scripts/run_015_e3.py` / `tests/reference/test_015_e3_harness.py` 这两处
   测试/harness 文件是必要范围扩张，不是产品 Runtime 扩张。
