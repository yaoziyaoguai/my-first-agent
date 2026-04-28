# Runtime v0.1 · 最小 CLI/TUI 输出契约（B2 冻结版）

> **本文件目的**：v0.1 阶段把"普通 CLI 下用户可见输出的边界"显式锁住，
> 让以后任何人写 `print(...)` 之前都先问一句"我这条 print 在哪个 prefix
> 白名单里？没有就走 RuntimeEvent。"
>
> **本文件范围**：**只**冻结**普通 simple CLI** 下的最小渲染规则与输出边界。
> **不**实现完整 Textual TUI；**不**重写 RuntimeEvent；**不**收口 session.py
> resume 路径的 print；**不**下线 `DEBUG_OUTPUT_PREFIXES`。这些都属于 v0.2 / v0.3。
>
> **引用关系**：本文件由 `docs/V0_1_CLI_OUTPUT_CONTRACT_PLAN.md` (B2 planning)
> 推导而来；任何冲突以 `docs/ROADMAP.md` 为准。

---

## 1. 为什么 B2 是 v0.1 blocking（学习型说明）

我们做这个项目最早最痛的体验是：simple CLI 跑起来，stdout 上同时滚着
assistant 文本、tool 调用 dump、checkpoint 调试日志、protocol REQUEST /
RESPONSE dump、各种 `[DEBUG]` 前缀—— **用户根本判断不出 Agent 在做什么、
该不该回复 y/n**。这不是"功能不够"，是**用户感知边界塌陷**。v0.1 要的
是"最简版本能跑"，如果用户跑起来看不懂，那就**没跑通**。

所以毕业标准 §6 把"最小 CLI/TUI 输出契约冻结"列为 v0.1 必须，本质是把
"普通 CLI 下的用户感知边界"显式锁住。冻结之后：
- 任何"想加一个调试 print"的冲动，先看本文件 §3 prefix 白名单——不在
  里面就**改走 RuntimeEvent**；
- 任何"想直接 `print(state.task)`" 的冲动，先看本文件 §4 禁止项——
  里面有就**直接拒**；
- 回归测试（`tests/test_real_cli_regressions.py`）会守护这条契约不被回退。

---

## 2. 为什么完整 TUI 不是 v0.1 必须

- **完整 Textual backend** 涉及 Textual app 生命周期、focus 管理、
  conversation view 滚动、状态面板布局、双向键盘事件——任何一项都需要
  新增 RuntimeEvent / DisplayEvent 类型或新输入后端，**违反 v0.1 阶段
  "禁止新增 event_type / 新输入后端"的硬性禁令**（ROADMAP §4 停止规则）。
- **基础状态面板**需要先把 `task.status` 经 RuntimeEvent 投影出来，那是
  v0.2 RuntimeEvent 边界治理才会做的事。
- **多面板 / 快捷键 / Esc 取消生成**与 xfail #2
  （`test_textual_shell_escape_can_cancel_running_generation`）同源，
  前置依赖 cancel_token + stream abort，整段是 v0.2 + v0.3 工作量。
- v0.1 只追求"能跑"，**simple CLI 能跑通 + 输出可读** 就够了；Textual 的
  存在是 v0.2 / v0.3 backlog，本轮不能借 B2 顺手做。

---

## 3. 统一渲染入口（已有，文档锁定）

所有"用户可见"内容**必须**经下面任一边界投递；不允许任何模块绕过。

| 内容类型 | 唯一允许的渲染路径 |
|---|---|
| assistant 流式文本 | `assistant_delta()` → `RuntimeEvent(EVENT_ASSISTANT_DELTA)` → `render_runtime_event_for_cli` → 终端 `print(text, end="")` |
| plan 展示 | `format_plan_for_display(plan)` → 包入 `plan.confirmation_requested` RuntimeEvent |
| 当前 step / 步骤完成提示 | `confirm_handlers` 投 RuntimeEvent |
| tool call（请求） | `tool_requested()` RuntimeEvent + `build_tool_status_event` DisplayEvent |
| tool 确认 | `tool.confirmation_requested` + `build_tool_awaiting_confirmation_event`（含 `TOOL_INPUT_PREVIEW_LIMIT=500` 字预览） |
| tool result（短摘要） | `tool_result_visible()` RuntimeEvent；完整结果走 Anthropic `tool_result` 协议，**不进** RuntimeEvent |
| pending_user_input_request | `user_input.requested` / `feedback.intent_requested` RuntimeEvent + `_format_user_input_request` |
| DisplayEvent 通用渲染 | `render_display_event(event)` → `[{title}]\n{body}` |

`agent/display_events.py` 中的 `EVENT_*` 枚举即 v0.1 输出边界**白名单**。
**v0.1 阶段禁止新增 event_type**（与 ROADMAP §4 停止规则一致）。

---

## 4. 允许直接 print 的"adapter 日志"白名单

> 下面这些不走 RuntimeEvent 但**仍允许**直接 print 到普通 CLI——它们是
> session 生命周期 / 系统级回退 / adapter 失败提示，按惯例已经带明确
> 前缀，并被 `main.DEBUG_OUTPUT_PREFIXES` 区分对待。

| 前缀 | 用途 | 出现位置 | 是否需要 env guard |
|---|---|---|---|
| `[系统]` | 系统级回退 / 提示 / 退出文案 | `main.py` / `agent/session.py` / `agent/context.py` / `agent/memory.py` / `agent/review.py` / `agent/health_check.py` / `agent/core.py` 系统级回退 | 否（用户必须看到） |
| `[CHECKPOINT]` | checkpoint adapter 日志 | `agent/checkpoint.py` | save / load / cleared / no file / **loaded keys** 受 `_debug_stdout_enabled()`（环境变量 `MY_FIRST_AGENT_DEBUG=1`）守卫；**failed 始终可见**（用户必须知道） |
| `📌` | resume 提示头 | `agent/session.py:52` | 否 |
| `⚠️` | security 审查警告头 | `agent/security.py` | 否（**标 v0.2 迁移**：迁到 DisplayEvent 后该 print 由 RuntimeEvent 接管） |
| `===` / `---` | 视觉分隔线（启动 banner / security 脚本边界） | `agent/session.py:31` / `agent/security.py` | 否 |

**调试日志类别（必须始终受 env guard，普通 CLI 默认关）**：

| 前缀 | 守卫环境变量 | 出现位置 |
|---|---|---|
| `[DEBUG]` | 任何使用方都必须先确认有 env guard 才能落盘；**不允许**承载用户应当看到的诊断信息 | （历史散落，正在收敛） |
| `[RUNTIME_EVENT]` / `[INPUT_RESOLUTION]` / `[TRANSITION]` / `[ACTIONS]` | `MY_FIRST_AGENT_RUNTIME_DEBUG_LOGS` | `agent/runtime_observer.py` |
| `REQUEST → Anthropic` / `RESPONSE ← Anthropic` | `MY_FIRST_AGENT_PROTOCOL_DUMP` 且 `core.DEBUG_PROTOCOL=True` 双重开关 | `agent/core.py::_debug_print_request` / `_debug_print_response` |

---

## 5. 禁止项（违反即破坏 v0.1 契约）

1. **禁止裸 `print(<dict>)` / `print(<list>)`**——如果一行 print 能把
   `state.task` / checkpoint / messages 整段倒出来，就是违规。
   `agent/session.py` 历史上的 `print("[DEBUG] checkpoint:", checkpoint)`
   就是这一类，B2 已修。
2. **禁止默认开启的 protocol dump**。`core.DEBUG_PROTOCOL` **必须**默认
   `False`，且 `_debug_print_request` / `_debug_print_response` 函数体首部
   **必须**有 env guard（`MY_FIRST_AGENT_PROTOCOL_DUMP`）。
3. **禁止跳过 RuntimeEvent 直接打印** assistant / tool call / tool result /
   plan 展示到终端（已基本做到，文档固化）。
4. **禁止用 `[DEBUG]` 前缀承载用户应当看到的诊断信息**——会被
   `main.DEBUG_OUTPUT_PREFIXES` 兜底过滤吞掉。诊断必须用 `[系统]` 或
   走 `RuntimeEvent(control.message)`。`agent/core.py:519` 历史上的
   `print(f"[DEBUG] 未知的 stop_reason: ...")` 就是这一类，B2 已修。
5. **禁止扩张 `DEBUG_OUTPUT_PREFIXES`**——它是 textual backend 下 stdout
   capture 的兜底过滤，是迁移期妥协。下线归 v0.2，**不**借 B2 改它。

---

## 6. 长内容截断策略

- 工具输入 / 文件内容预览：复用 `TOOL_INPUT_PREVIEW_LIMIT = 500`
  （`agent/display_events.py`）；超过即截断 + 追加
  `...(已截断，原始长度 X 字符)`。
- checkpoint dump（仅 debug 模式）：**只打印 keys，不打印 values**——
  避免会话历史泄到终端。`agent/session.py::try_resume_from_checkpoint`
  已对齐这个规则。

---

## 7. 多行渲染规则

- `render_display_event` 的 `[{title}]\n{body}` 是 v0.1 标准多行格式。
- body 内行首**不**加缩进，由调用方决定段落组织。
- resume / security 等"暂保留 print 旁路"的多行输出也应采用同样的
  "无缩进 + 行间空行隔开"格式，保持视觉一致。
- 多行内容前后**应该**有一个空行作为视觉分隔。

---

## 8. 错误信息规则

- 默认只打**一行人类可读** + 必要 context（如失败的 path / tool 名）。
- stack trace **仅**在显式 debug 模式（`MY_FIRST_AGENT_DEBUG=1` 或
  `MY_FIRST_AGENT_RUNTIME_DEBUG_LOGS=1`）下输出。
- 错误信息**不带** `[DEBUG]` 前缀；用户必须能看到的错误用 `[系统]` 或
  走对应业务 prefix（`[CHECKPOINT] failed:`、`⚠️` 等）。

### 8.1 工具结局四类输出（v0.2 M7 收口）

为避免「用户搞不清是自己拒绝、是策略拒绝、还是工具失败」，所有工具调用
结局必须落入下面四类之一，display event 类型与 status_text 关键字都不能
互相重叠：

| 结局类别 | display event | status_text 关键字 | 触发路径 |
|---|---|---|---|
| 真实成功 | `tool.completed` | 「执行完成。」 | execute_tool 返回正常字符串 |
| 工具运行失败 | `tool.failed` | 「执行失败。」 | 返回值匹配 `TOOL_FAILURE_PREFIXES`（错误：/ HTTP 错误：等） |
| 工具内部安全检查拒绝 | `tool.rejected` | 「已被工具内部安全检查拒绝。」 / 「被安全策略拒绝：...」 | 返回值以「拒绝执行：」开头 **或** confirmation == "block"（如 read_file ~/.env / .pem） |
| 用户拒绝 | `tool.user_rejected` | 「用户拒绝执行，已跳过。」 / 「用户未批准，改为提供反馈意见。」 | confirm_handlers 收到 'n' 或 feedback |

四类全部映射到 RuntimeEvent `EVENT_TOOL_RESULT_VISIBLE`，UI 一致渲染。
**禁止**安全策略拒绝场景显示「执行完成」；**禁止**用 user-related 文案
描述策略拒绝（已由测试守护）。

---

## 9. 契约不冻结的内容（明确不在 v0.1 B2 范围）

> 以下都是**真实存在的债**，但归属 v0.2 / v0.3，本轮**不动**。

| 不冻结项 | 归属 | 理由 |
|---|---|---|
| Textual 输出格式与生命周期 | **v0.2 基础 TUI/CLI UX 实现** | 完整 TUI 工程化 |
| RuntimeEvent metadata schema | **v0.2** | 边界治理 |
| `agent/session.py::_replay_awaiting_prompt` 的 print 旁路（plan / step / pending input 在 resume 路径走裸 print） | **v0.2** | 收口需要扩张 RuntimeEvent，超 v0.1 |
| `agent/security.py` 审查文案 → DisplayEvent | **v0.2** | 工作量超 v0.1 |
| `main.DEBUG_OUTPUT_PREFIXES` 后处理过滤层下线 | **v0.2** | 依赖 RuntimeEvent 收口 |
| `task.status` → RuntimeEvent control.message 投影 | **v0.2** | 新增 event 语义 |
| Observer / log persist 格式 | **v0.3** | observability 治理 |
| 多面板 / 快捷键 / Esc 取消生成 / paste burst / Textual 转默认 | **v0.3 高级 TUI** | UX 工程化 |

**这条边界很关键**：v0.1 是"让现状对齐已写好的契约"，**不是**"让契约
长出新东西"。任何想顺手做的事，都先回到 ROADMAP §4 停止规则。

---

## 10. 回归保护

`tests/test_real_cli_regressions.py` 已新增两条 B2 契约护栏测试：

- `test_b2_resume_does_not_naked_print_checkpoint_dict`——守护 §5.1：
  普通 CLI 下 `try_resume_from_checkpoint` 不会泄整段 checkpoint dict。
- `test_b2_chat_default_does_not_emit_protocol_dump`——守护 §5.2：
  普通 CLI 下默认不会出现 `REQUEST → Anthropic` / `RESPONSE ← Anthropic`
  protocol dump。

任何把 `DEBUG_PROTOCOL` 改回 True 默认值、或重新引入裸 `print(checkpoint)`
的 PR，都会被这两条测试拦下。

---

## 11. 这份文档怎么用

1. **写 print 之前**：本文件 §3 / §4。不在白名单 → 改走 RuntimeEvent。
2. **想加调试输出**：本文件 §4 调试日志类别 + §5 禁止项。**必须**带
   env guard。
3. **想新增 RuntimeEvent kind**：**v0.1 阶段直接拒**（ROADMAP §4 停止规则）。
4. **想动 Textual / 状态面板 / 多面板**：本文件 §9。归 v0.2 / v0.3，
   **不**借 v0.1 顺手做。
5. **B2 是否毕业**：本文件 §10 两条回归测试 + B2 commit 落盘 = 毕业。
   v0.1 是否毕业 = 还差 B3 真实 smoke。

---

## 12. v0.3 M1 · 基础 CLI Shell 输出契约（增量补充）

> 本节是 v0.3 M1 在 v0.1 / v0.2 契约之上的**增量补充**，不重写 §1-§11。
> 对应实现：`agent/cli_renderer.py` + `agent/session.py::summarize_session_status`。

### 12.1 启动 header

`init_session` 必须输出结构化 header，至少包含：
- 阶段标签（默认 `Runtime v0.3 M1 shell`）
- session id（短哈希前 8 位 + 完整 id）
- cwd
- health summary（**单行**紧凑摘要，全 pass 时显示 `all checks passed`，
  有 warn 时显示 `N warn (name1, name2); 详情：python main.py health`）
- 用法提示（`quit` / `/reload_skills`）

**不允许**：
- ❌ 在 header 里 print 健康检查长块（v0.2 的「🏥 项目健康检查报告」长块
  改为只在 `python main.py health` 子命令下显式打印）
- ❌ 把 api_key / base_url / RuntimeEvent / DisplayEvent / raw messages 放进 header
- ❌ 把 health summary 变成多行刷屏

### 12.2 Resume 状态

`try_resume_from_checkpoint` 必须**始终**输出一行可见 resume 状态，三态：
- 无 checkpoint → `📭 resume : 未发现断点，可以直接开始新任务。`
- idle 残留（已静默清理） → `📭 resume : 断点为 idle 残留，已静默清理。`
- actionable → `📌 resume : 发现未完成的任务：<goal>` + 状态/步骤/消息数/待确认工具

**不允许**裸 print 整段 checkpoint dict（沿用 v0.1 §5 禁止项）。

### 12.3 Status line（M1 范围内可选输出）

`render_status_line(summary)` 渲染**单行**状态条：
`[status] status=<x> · step=<i>/<n> · pending_tool=<name> · msgs=<count>`

只在状态变化点打一次，**不**做 inplace 重绘 / 定时刷新（避免 curses 依赖）。

### 12.4 四类工具结局文案

沿用 v0.2 §8.1 的契约**完全不变**。M1 只是在外层补 header / status，
不改 `tool.completed` / `tool.failed` / `tool.rejected` / `tool.user_rejected`
任何文案。

### 12.5 回归保护

由 `tests/test_cli_renderer.py`（13 tests）+
`tests/test_session_summary_and_header.py`（10 tests）守护。任何破坏
header 结构、把 health 长块加回启动屏、或让 summarize_session_status
回显 raw messages / api_key 的 PR 都会被这些测试拦下。
