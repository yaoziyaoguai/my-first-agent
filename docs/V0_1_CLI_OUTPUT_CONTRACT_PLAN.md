# Runtime v0.1 · B2「冻结最小 CLI/TUI 输出契约」只读审计与实施计划

> **本文件是什么**：v0.1 第二个 blocking（B2）的**只读审计 + 实施计划**，配套 `docs/V0_1_CONTRACT.md`。
>
> **本文件不是什么**：不是契约本身。契约本身将在 B2 实施时落到 `docs/CLI_OUTPUT_CONTRACT.md`（待写），本文档只规划"那份契约该写什么、要修哪些 print 才能真的对齐"。
>
> **写给未来读这份代码的人**：v0.1 阶段我们最痛的不是"功能不够"，而是"普通 CLI 跑起来根本看不清 Agent 在做什么"——assistant 文本、tool 调用、plan 展示、checkpoint 恢复、debug dump 全部交叉混在 stdout 上，状态不可见、确认流提示不稳定。B2 要做的是**冻结契约**让这种混乱不再回归，**而不是**重写一个 TUI。

---

## 1. 当前输出链路证据（基于真实代码审计）

### 1.1 已经存在的统一输出边界（无需重写）

| 模块 | 角色 | 证据 |
|---|---|---|
| `agent/display_events.py` | 定义 `RuntimeEvent` / `DisplayEvent` 数据类型 + `render_runtime_event_for_cli` / `render_display_event` 渲染函数 | `EVENT_*` 枚举（assistant.delta / display.event / control.message / tool.requested / tool.confirmation_requested / tool.result_visible / plan.confirmation_requested / user_input.requested / feedback.intent_requested）已是事实白名单 |
| `agent/core.py::_emit_runtime_event` (line 169-201) | core 内 RuntimeEvent **唯一**投递出口，集中兼容 deprecated `on_output_chunk` / `on_display_event` | 已有"无 sink 时 fallback 到 print"分支 |
| `main.py::_render_runtime_event_for_simple_cli` (line 133-153) | simple CLI 的 RuntimeEvent sink，是终端 print 的合法终点 | assistant.delta `end=""`、其他事件 `\n` 前缀，对齐 `render_display_event` |
| `main.py::_run_textual_runtime_turn` (line 156-238) | Textual sink + stdout capture 兜底（迁移期补丁） | 注释里反复声明"不能继续扩张" |
| `main.py::DEBUG_OUTPUT_PREFIXES` (line 34-44) | 后处理过滤 `[DEBUG] / [CHECKPOINT] / [RUNTIME_EVENT] / [INPUT_RESOLUTION] / [TRANSITION] / [ACTIONS] / event_type=` 防止它们污染 TUI conversation view | 文档自承"不是最终架构" |

### 1.2 普通 CLI 下各类用户可见内容当前如何输出

| 内容 | 当前路径 | 是否符合契约 |
|---|---|---|
| **assistant 流式文本** | `assistant_delta()` RuntimeEvent → `_render_runtime_event_for_simple_cli` → 终端 `print(..., end="")` | ✅ 已统一 |
| **plan 展示** | `format_plan_for_display(plan)` 生成多行文本 → 由 `confirm_handlers.py:113` 包入 `plan.confirmation_requested` RuntimeEvent；**resume 路径** `agent/session.py:83` **直接 print** | ⚠️ 双路径（resume 旁路） |
| **当前 step / 步骤完成提示** | 主路径走 `confirm_handlers` 的 RuntimeEvent；**resume 路径** `session.py:90-91` 直接 print "上一步已完成。回复 y 继续下一步…" | ⚠️ 双路径（resume 旁路） |
| **status（task.status / 状态变化）** | **没有专门事件**。状态本身不投影；用户只能从 plan / step 提示推断 | ⚠️ v0.1 不要求文档化（毕业标准 §3 "存在即可"），但**契约要写明**：status 不直接打印到 CLI |
| **tool call**（请求） | `tool_requested()` RuntimeEvent + `build_tool_status_event` DisplayEvent 包装 | ✅ 已统一 |
| **tool 确认** | `tool.confirmation_requested` + `build_tool_awaiting_confirmation_event`，含 `TOOL_INPUT_PREVIEW_LIMIT=500` 字预览 | ✅ 已统一 |
| **tool result** | `tool.result_visible` RuntimeEvent，仅展示短摘要；完整结果走 Anthropic tool_result | ✅ 已统一 |
| **pending_user_input_request** | `user_input.requested` / `feedback.intent_requested` RuntimeEvent + `_format_user_input_request`；**resume 路径** `session.py:99-111` **直接 print** | ⚠️ 双路径 |
| **checkpoint resume 提示** | `agent/session.py::try_resume_from_checkpoint` 全是裸 print；**第 42 行：`print("[DEBUG] checkpoint:", checkpoint)`——无守卫直接打印整段 dict（含 conversation messages！）** | 🔴 严重违反 |
| **error / 失败信息** | 主要走 `[系统]` / `[CHECKPOINT]` 前缀 print；`checkpoint.py:178,193` 失败路径**未受 `_debug_stdout_enabled` 守卫**（按设计应当——失败必须可见） | ⚠️ prefix 规范需写入契约 |
| **多行输出** | `render_display_event(event)` 用 `[{title}]\n{body}`；plan 自带 `format_plan_for_display`；行首不缩进 | ⚠️ 写入契约 |

### 1.3 散落的违反契约 / 风险 print 清单（按严重度）

> 规则：普通运行时（`MY_FIRST_AGENT_RUNTIME_DEBUG_LOGS` 关）下不应出现的输出。

| 严重度 | 位置 | 问题 | 期望归属 |
|---|---|---|---|
| 🔴 **高** | `agent/session.py:42` `print("[DEBUG] checkpoint:", checkpoint)` | **无守卫直裸 print 整段 checkpoint dict（含 conversation messages）**——这是 ROADMAP B2 列出的"裸 debug print 污染"最典型样本，会把整个会话历史泄到终端；同时 `[DEBUG]` prefix 又被 `DEBUG_OUTPUT_PREFIXES` 兜底过滤掉，于是在 Textual 下被吞掉、在 simple CLI 下又泄漏，**两端都错** | **v0.1 B2 必修** |
| 🔴 **高** | `agent/core.py:588` `DEBUG_PROTOCOL = True` + `_debug_print_request` (line 630-643) | 默认开启，每轮模型调用前打印巨量 `REQUEST → Anthropic` dump（system / tools / 全部 messages 摘要）。**当前 `chat()` 主路径未直接调用它**（`_call_model` 内 line 572 注释掉了 response dump，request dump 也不在主路径调用——需 B2 实施时再核对一次），但常量默认 True + 函数体内有 print，是**潜在回归源**；任何后续把 `_debug_print_request(...)` 取消注释的改动都会立即重新污染 CLI | **v0.1 B2 必修**（默认 False + env guard，**不重写**） |
| 🟡 **中** | `agent/core.py:157,435,519` `[系统] 检测到不一致状态…` / `[系统] 循环次数超过上限…` / `[DEBUG] 未知的 stop_reason…` | 系统级提示走裸 print 而非 RuntimeEvent control.message；其中 `[DEBUG] 未知的 stop_reason` 用了 `[DEBUG]` 前缀，会被 `DEBUG_OUTPUT_PREFIXES` 吞掉——**用户根本看不到这条诊断** | v0.1 B2：契约明确"系统级回退提示**允许**直接 print，但必须用 `[系统]` 前缀；禁止用 `[DEBUG]` 前缀承载诊断" |
| 🟡 **中** | `agent/checkpoint.py:178,193` `[CHECKPOINT] save failed:` / `load failed:` | 失败路径**无**`_debug_stdout_enabled()` 守卫（按设计应当：失败必须可见） | v0.1 B2：契约写明"`[CHECKPOINT]` 是合法 adapter 日志类别，失败必须 print（用户需要知道）；正常路径必须受 env guard" |
| 🟢 **低** | `agent/context.py` / `agent/memory.py` 压缩日志 | 已有 `[系统]` 前缀，归 adapter 日志类别 | v0.1 B2 写入契约白名单 |
| 🟢 **低** | `agent/security.py` 工具脚本预览/审查 print（line 96-142） | 用户必须看到这些内容才能确认；适合走 `DisplayEvent(tool.awaiting_confirmation)` 但工作量超 v0.1 范围 | v0.1 B2：写入契约"security 审查文案**暂时**走直接 print（带 `⚠️` 显式提示），**标记为 v0.2 迁移项**"——本轮**不**迁移 |
| 🟢 **低** | `agent/review.py` / `agent/health_check.py` | 业务报告类输出 | v0.1 B2 写入契约白名单 |
| 🟢 **低** | `agent/session.py` 启动 banner / resume / 退出 / Ctrl+C 菜单 | 大量 `print` 但都是 session 生命周期文案，属 main.py I/O adapter 范畴 | v0.1 B2 写入契约（**保留 print，但文档化 prefix 规范**） |
| 🟢 **低** | `agent/runtime_observer.py:144,173,197,205` `[RUNTIME_EVENT]/[INPUT_RESOLUTION]/[TRANSITION]/[ACTIONS]` | 受 `RUNTIME_DEBUG_LOGS` 环境变量守卫，默认关 | v0.1 B2 写入契约（合法调试日志类别，必须始终带 prefix） |

### 1.4 当前真实风险总结

1. **裸 print**：`session.py:42` 一行就能把整段 checkpoint（含 conversation messages）泄到终端；`core.py::DEBUG_PROTOCOL` 是定时炸弹
2. **输出边界不清**：plan / step / pending_user_input 在主路径走 RuntimeEvent，在 resume 路径走裸 print——两条路径输出格式不一致
3. **RuntimeEvent 渲染不统一**：simple CLI / Textual / 旧 callback 三套 sink 共存，`DEBUG_OUTPUT_PREFIXES` 是后处理 hack 而非源头治理
4. **多行输出混乱**：`render_display_event` 用 `[title]\nbody` 一种格式；`session._replay_awaiting_prompt` 用自己的缩进；`security` 用分隔线——**风格不统一**
5. **状态不可见**：`task.status` 没有 RuntimeEvent 投影；用户只能从 plan / step / tool 文案推断"Agent 现在在干什么"——这是 ROADMAP "看不清 Agent 在做什么"的核心来源
6. **确认流提示不稳定**：plan 确认提示在主路径由 `confirm_handlers:113` 拼接、在 resume 路径由 `session.py:86` 拼接、在 textual 路径由 RuntimeEvent metadata 投影——**三处文案不一致**

---

## 2. v0.1 最小 CLI/TUI 输出契约冻结范围（待写入 `docs/CLI_OUTPUT_CONTRACT.md`）

> **范围原则**：**只冻结契约 + 修对齐契约的现存 print**，**不实现完整 Textual TUI**，**不重写 RuntimeEvent 体系**，**不迁移 session.py resume 路径**。

### 2.1 契约必须写明的 6 件事

1. **统一渲染入口锁定（已有，文档固化）**
   - 所有"用户可见"内容必须经 `RuntimeEvent` → `render_runtime_event_for_cli` 或 `DisplayEvent` → `render_display_event` 投递
   - `EVENT_*` 枚举即 v0.1 输出边界白名单；**v0.1 阶段禁止新增 event_type**（与 ROADMAP §4 停止规则一致）
2. **允许直接 print 的"adapter 日志"白名单（带 prefix 规范）**
   - `[系统]` —— 系统级回退/提示/退出文案（main.py / session.py / context / memory / review / health_check / **core.py 系统级回退**）
   - `[CHECKPOINT]` —— checkpoint adapter 日志（save / load / cleared / no file / **failed 必须始终可见**，正常路径受 `_debug_stdout_enabled` 守卫）
   - `📌` —— resume 提示头（`session.py:52` 已有）
   - `⚠️` —— security 审查警告头（`security.py` 已有，标 v0.2 迁移）
   - `===` / `---` —— 视觉分隔线（session 启动 banner / security 脚本边界）
   - 其余调试前缀（`[DEBUG] / [RUNTIME_EVENT] / [INPUT_RESOLUTION] / [TRANSITION] / [ACTIONS] / event_type=`）一律为**调试日志类别**，必须**始终**受 env guard，普通 CLI 默认**关**
3. **禁止项**
   - 禁止裸 `print(<dict>)` / `print(<list>)`（`session.py:42` 必修）
   - 禁止默认开启的 protocol dump（`core.py::DEBUG_PROTOCOL` 默认必须为 False，且加 env guard）
   - 禁止跳过 RuntimeEvent 直接打印 assistant / tool call / tool result / plan 内容到终端（已基本做到，文档固化）
   - 禁止用 `[DEBUG]` prefix 承载用户应当看到的诊断信息（`core.py:519` 的"未知 stop_reason" 必修——会被 `DEBUG_OUTPUT_PREFIXES` 吞掉）
4. **长内容截断策略**：复用 `TOOL_INPUT_PREVIEW_LIMIT=500`；契约明确"超过 N 字截断 + `...(已截断，原始长度 X 字符)`"——已有实现，写入契约
5. **多行渲染规则**：
   - `render_display_event` 的 `[{title}]\n{body}` 是 v0.1 标准多行格式
   - body 内行首不加缩进，由调用方组织
   - resume / security 等"暂保留 print 旁路"也必须采用同样的不缩进 + 行间空行隔开
6. **错误信息规则**：
   - 默认只打一行人类可读 + 必要 context（如失败的 path / tool name）
   - stack trace 仅在显式 debug 模式（env var 或 `--debug` flag）

### 2.2 契约不冻结的内容（明确不在 v0.1 B2 范围）

- ❌ **不冻结** Textual 输出格式（Textual 完整实现归 v0.2）
- ❌ **不冻结** RuntimeEvent metadata schema（治理归 v0.2）
- ❌ **不冻结** session resume 路径输出（迁移归 v0.2）
- ❌ **不冻结** security 审查文案输出方式（迁移归 v0.2）
- ❌ **不冻结** observer / log persist 格式（治理归 v0.3）

---

## 3. 版本归属切线表

| 工作 | 归属 | 理由 |
|---|---|---|
| 写 `docs/CLI_OUTPUT_CONTRACT.md` | **v0.1 B2** | 契约本身 |
| 修 `session.py:42` 裸 dict print | **v0.1 B2** | 修 bug + 让现状对齐契约（ROADMAP 允许） |
| `core.py::DEBUG_PROTOCOL` 默认 False + env guard | **v0.1 B2** | 同上，潜在回归源必修 |
| `core.py:519` `[DEBUG] 未知的 stop_reason` → `[系统]` 前缀 | **v0.1 B2** | 用户必须能看到这条诊断 |
| 新增回归测试守护契约（不出现裸 dict / protocol dump） | **v0.1 B2** | 契约不能只有文档没有护栏 |
| 完整 Textual backend 实现 | ❌ **v0.2 基础 TUI/CLI UX 实现** | 完整 TUI 需要：Textual app 生命周期、persistent shell、focus 管理、conversation view 滚动、状态面板布局——任何一项都是 v0.2 起步级别工作量 |
| persistent shell（Textual 下交互式 shell 复用） | ❌ **v0.2 基础 TUI/CLI UX 实现** | 涉及子进程生命周期、PTY、tool_executor 重构 |
| 基础状态面板（goal / plan / current step / status 显示区） | ❌ **v0.2 基础 TUI/CLI UX 实现** | 需要先把 task.status 经 RuntimeEvent 投影出来，属 v0.2 RuntimeEvent 治理 |
| RuntimeEvent 友好可读渲染（在 v0.1 契约之上做更友好 UI） | ❌ **v0.2 基础 TUI/CLI UX 实现** | v0.1 只要"能看清"，v0.2 才追求"好看" |
| confirm 流 UI（plan/step/tool 确认按钮化） | ❌ **v0.2 基础 TUI/CLI UX 实现** | 需要 input backend 双向通信，超 v0.1 |
| `pending_user_input_request` 状态提示 UI | ❌ **v0.2 基础 TUI/CLI UX 实现** | 同上 |
| checkpoint resume 提示 UI（启动时显式弹窗） | ❌ **v0.2 基础 TUI/CLI UX 实现** | resume 路径输出本身归 v0.2 迁移 |
| 多面板布局（conversation / plan / events / state / log 分区） | ❌ **v0.3 高级 TUI** | UX 工程化 |
| 快捷键体系 | ❌ **v0.3 高级 TUI** | UX 工程化 |
| **Esc / generation cancellation 与 TUI 集成** | ❌ **v0.3 高级 TUI**（前置：v0.2 cancel 生命周期） | 与 xfail #2 同源 |
| **stream abort** | ❌ **v0.2 cancel 生命周期 + v0.3 TUI 集成** | 与 xfail #2 同源 |
| **timeline / event viewer / 历史回放** | ❌ **v0.3 高级 TUI** | observability 增强 |
| persistent shell 完善 / 多行编辑 / paste burst UX | ❌ **v0.3 高级 TUI**（前置：v0.3 paste burst） | 与 xfail #3 同源 |
| Textual backend 转默认 | ❌ **v0.3 高级 TUI** | 默认变更需要先 v0.2 完整实现 |
| 下线 `DEBUG_OUTPUT_PREFIXES` 后处理过滤层 | ❌ **v0.2** | 依赖 RuntimeEvent 收口完成 |
| `task.status` → RuntimeEvent control.message 投影 | ❌ **v0.2** RuntimeEvent 边界治理 | 新增 event 语义 |

---

## 4. B2 实施计划（**本文档不实施**，仅规划）

### 4.1 最小改动文件清单

- **新增**：
  - `docs/CLI_OUTPUT_CONTRACT.md`（单页中文学习型，§2.1 + §2.2 全部写入；与 `V0_1_CONTRACT.md` 风格一致）
- **必修代码**（只修 bug 对齐契约，不重写）：
  - `agent/session.py:42`：`print("[DEBUG] checkpoint:", checkpoint)` → 改为受 `_debug_stdout_enabled()` 或同等守卫；或直接删除（不影响功能；会话恢复信息已在 line 52-54 由 `📌` 提示）
  - `agent/core.py:588`：`DEBUG_PROTOCOL = True` → `False`，并在 `_debug_print_request` / `_debug_print_response` 函数体首部追加 env guard（如 `if not os.getenv("MY_FIRST_AGENT_PROTOCOL_DUMP"): return`）；不动函数体逻辑
  - `agent/core.py:519`：`print(f"[DEBUG] 未知的 stop_reason: {response.stop_reason}")` → `print(f"[系统] 未知的 stop_reason: {response.stop_reason}")`（让用户能看到该诊断）
- **可选小修**（如审计时再发现）：
  - `agent/checkpoint.py` 失败路径 prefix 已合规，**无需改**
- **不改**：`display_events.py` / `runtime_observer.py` / `main.py` / `confirm_handlers.py` / `planner.py` / 任何工具 / 任何已有测试逻辑

### 4.2 测试策略

- **新增 1 个回归测试**（守护契约不被回退）：在 `tests/test_real_cli_regressions.py` 增加用例
  - 用例 A：跑一次受控的 `try_resume_from_checkpoint`（mock checkpoint 数据），捕获 stdout，**断言**：不含 `[DEBUG] checkpoint:` 也不含 dict 字面量（`{"task":` / `'messages':` 等子串）
  - 用例 B：用 mock client 跑一次 `chat()`（已有测试基础设施够），捕获 stdout，**断言**：不含 `REQUEST → Anthropic` 也不含 `RESPONSE ← Anthropic`
- **不新增**：完整 RuntimeEvent 全量 snapshot 测试（属于 v0.2 治理）
- **不削弱 / 不删除**任何现有测试
- **跑**：`.venv/bin/python -m ruff check tests/ agent/ main.py`（**注意**：当前 ruff 仅在 tests/ 配置过；agent/ 和 main.py 是否过 ruff 需 B2 实施时再确认；若未配置则只跑 `tests/`）+ `.venv/bin/python -m pytest -q`，期望 **271 passed**（基线 269 + 新增 1 个用例 A + 1 个用例 B）/ **3 xfailed**

### 4.3 停止规则

B2 完成的判据（**全部满足才算关 B2**）：
1. ✅ `docs/CLI_OUTPUT_CONTRACT.md` 写完，且明确列出 §2.1 全部 6 件事 + §2.2 不冻结清单
2. ✅ `session.py:42` 裸 dict print 修复
3. ✅ `core.py::DEBUG_PROTOCOL` 默认 False + env guard
4. ✅ `core.py:519` `[DEBUG]` → `[系统]`
5. ✅ 新增 2 个回归测试用例守护契约
6. ✅ `pytest -q` 全绿（271 passed / 3 xfailed）
7. ✅ `ruff check` 通过

任何想顺手做的事（重写 RuntimeEvent / 收口 session.py resume print / Textual UI / DisplayEvent 化 security 审查 / 下线 `DEBUG_OUTPUT_PREFIXES` / 投影 task.status）→ **直接拒**，归 v0.2 / v0.3。

> B2 完成后立即停下，**不进入 B3**（B3 需要 `ANTHROPIC_API_KEY` 真实跑 smoke，由用户决定何时启动）。

### 4.4 回滚方案

如果 B2 实施过程中发现意料外回归（pytest 红 / 真实 CLI 跑出新输出问题）：
- **首选**：单文件 `git checkout HEAD -- <file>` 回滚单点改动；契约文档保留，配套代码改动逐文件回滚
- **次选**：`git revert <B2 commit>`（B2 是单 commit 时最简单）
- **不允许**：用 `--force` reset；不允许直接删契约文档；不允许在回滚后再"绕一下"补丁——回滚后必须重新进入计划阶段
- 回滚后**保留** `docs/V0_1_CLI_OUTPUT_CONTRACT_PLAN.md`（本文件）与 `docs/V0_1_CONTRACT.md`，作为后续重做的依据

---

## 5. 学习型说明

### 5.1 为什么 CLI/TUI 输出契约是 v0.1 blocking

我们做这个项目最早最痛的体验是：simple CLI 跑起来，stdout 上同时滚动 assistant 文本、tool 调用 dump、checkpoint 调试日志、protocol REQUEST/RESPONSE dump、`[DEBUG]` 各种前缀，**用户根本判断不出 Agent 现在在做什么、需不需要回复 y/n**。这不是"功能不够"，是**用户感知边界塌陷**——v0.1 的目标是"最简版本能跑"，如果用户跑起来看不懂、不知道该回复什么，那就**没跑通**。

所以毕业标准 §6 把"最小 CLI/TUI 输出契约冻结"列为 v0.1 必须，本质是把"普通 CLI 下的用户感知边界"显式锁住，让以后任何人写 print 前都先问一句"我这条 print 在哪个 prefix 白名单里？没有就走 RuntimeEvent"。

### 5.2 为什么完整 TUI 不是 v0.1 必须

- **完整 Textual backend** 涉及 Textual app 生命周期、focus 管理、conversation view 滚动、状态面板布局、双向键盘事件——任何一项都需要新增 RuntimeEvent / DisplayEvent 类型或新输入后端，**违反 v0.1 阶段"禁止新增 event_type / 新输入后端"的硬性禁令**
- **基础状态面板**需要先把 `task.status` 经 RuntimeEvent 投影出来，那是 v0.2 RuntimeEvent 边界治理才会做的事
- **多面板 / 快捷键 / Esc 取消生成**与 xfail #2（`test_textual_shell_escape_can_cancel_running_generation`）同源，前置依赖 cancel_token + stream abort，整段是 v0.2 + v0.3 工作量
- v0.1 只追求"能跑"，**simple CLI 能跑通 + 输出可读** 就够了；Textual 的存在是 v0.2/v0.3 backlog，本轮不能借 B2 顺手做

### 5.3 为什么"修裸 print"算 v0.1 范围、"收口 session.py resume print"不算

- **修裸 print**（`session.py:42` / `core.py::DEBUG_PROTOCOL` / `core.py:519` 错用 `[DEBUG]` prefix）属于 ROADMAP §134-142 明确允许的"修 bug + 让现状对齐契约"——它们是**违反契约的现存代码**，不修就等于契约没冻结
- **收口 session.py resume 路径的 print**（把 `_replay_awaiting_prompt` 全部转 RuntimeEvent）属于"扩张 RuntimeEvent 边界 + 改动 session 生命周期"，是新增能力而非修 bug，归 **v0.2 RuntimeEvent 边界治理 + 基础 TUI/CLI UX 实现**

这条边界很关键：**v0.1 是"让现状对齐已写好的契约"，不是"让契约长出新东西"。**

### 5.4 为什么"DEBUG_OUTPUT_PREFIXES 后处理过滤层"不在 v0.1 下线

`DEBUG_OUTPUT_PREFIXES` 是 textual backend 下 stdout capture 的兜底过滤——它存在的根本原因是"还有调试日志没收口到 RuntimeEvent"。下线它需要先把所有 `[DEBUG] / [CHECKPOINT] / [RUNTIME_EVENT] / [INPUT_RESOLUTION] / [TRANSITION] / [ACTIONS]` 全部转走 RuntimeEvent 或彻底删除——那是 v0.2 RuntimeEvent 边界治理，不是 v0.1 该碰的范围。v0.1 阶段它是"承认现状不完美但能跑"的合理妥协，**契约里把它列为已知妥协项**就够了。

---

## 6. 与 `docs/V0_1_CONTRACT.md` 的关系

| 文档 | 角色 |
|---|---|
| `docs/ROADMAP.md` | 真相源（v0.1/v0.2/v0.3/v1.0 阶段目标 + 毕业标准 + 非目标 + 停止规则） |
| `docs/V0_1_CONTRACT.md` | 测试 / xfail 视图（B1 交付物） |
| `docs/V0_1_CLI_OUTPUT_CONTRACT_PLAN.md` | **本文件**：B2 输出链路审计 + 实施计划（**不是契约本身**） |
| `docs/CLI_OUTPUT_CONTRACT.md` | **B2 实施时**才会落盘的契约本身（本文档 §2.1 + §2.2） |

任何冲突以 ROADMAP 为准。
