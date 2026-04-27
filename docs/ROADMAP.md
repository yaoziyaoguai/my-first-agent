# my-first-agent 演进路线图

> **阅读前提**：先读过 `docs/ARCHITECTURE.md`。这份文档假设你已经理解当前代码的分层、状态机、协议配对契约。
>
> **文档定位**：这不是待办清单，是**演进地图**。每一块告诉你：为什么现在该做、业界怎么做、是否有更激进的思路、在你代码里改哪里。
>
> **使用方式**：按阶段顺序推进。每开一个 block，先回头读对应章节，决定"做"或"跳过或推迟"。不是每一块都必须做。

---

## Milestone · Persistent Textual I/O Shell 阶段性完成

> **状态（2026-04-27）：实验分支已形成可回退里程碑**
>
> 当前分支：`experiment-persistent-textual-shell`
>
> 关键提交：
> - `887c6ec feat(input): add persistent textual shell streaming`
> - `4750a26 fix(runtime): allow reused meta tool ids across steps`
> - `177dbc5 chore(runtime): add loop observability logs`

这一阶段把交互入口从裸 `input()` / one-shot TUI 演进到常驻 Textual I/O
Shell，但仍保持 simple backend 作为默认路径。Textual backend 必须显式启用：

```bash
MY_FIRST_AGENT_INPUT_BACKEND=textual python main.py
```

已完成能力：

- simple backend 仍然保留为默认路径，Textual backend 不默认启用。
- `UserInputEvent` / `UserInputEnvelope` 作为输入层边界继续保留。
- conversation view 支持 `You` / `Assistant` 对话显示。
- `Enter` 提交，`Shift+Enter` / `Ctrl+Enter` 换行，`F10` 备用提交，`Esc` 清空，`Ctrl+Q` 退出。
- assistant 输出已先包装成 `RuntimeEvent(assistant.delta)`，再进入 TUI
  conversation view；`on_output_chunk` 只作为旧调用方兼容桥保留。
- 长输出自动滚动到底部，用户能看到末尾确认或总结。
- 已验证可以完成武汉 + 宜昌旅游规划这类长任务。
- `write_file` 工具确认链路已能走通。
- 新增最小 DisplayEvent 桥：工具确认、执行中、完成/失败可通过
  `on_display_event` 投影到 TUI；`write_file` 确认提示会展示工具名、路径和内容
  preview，用户仍用 raw text 确认。
- 新增最小 RuntimeEvent 边界：`assistant.delta`、`display.event`、
  `control.message`、`tool.requested` 可统一从 Runtime 投影到 UI。RuntimeEvent
  不写 checkpoint，不进入 `conversation.messages`，不是 runtime_observer debug
  event，也不是 Anthropic API messages。
- 第二阶段继续迁移旧 print-era 交互路径：计划确认提示走
  `plan.confirmation_requested`，slash command 结果走 `command.result`，
  执行期求助走 `user_input.requested`，工具确认/结果提示规范为
  `tool.confirmation_requested` / `tool.result_visible`。
- runtime observability 已补充 loop / model / progress / checkpoint 相关事件。
- 修复 `mark_step_complete` 跨 step 复用 `tool_use_id` 导致的重复输出 / `no_progress` 循环问题。
- 补充跨任务回归：确认型 pending_tool 完成后，下一条新问题会重新进入 planner，
  不会被旧 pending 状态吞掉。

当前仍需优化：

- Textual backend 仍在实验分支，默认 backend 仍是 simple。
- tool lifecycle 可见性仍需优化，但第一阶段债务已收敛：
  - 已有：`tool.awaiting_confirmation` / `tool.executing` / `tool.completed` /
    `tool.failed` 的最小 DisplayEvent 投影。
  - 已有：`write_file` 长内容 preview，避免 TUI 看起来卡住或让用户看不清写入目标。
  - 已有：模型开始规划工具调用时的 `tool.requested` 已事件化。
  - 待做：工具结果摘要、失败详情结构化、统一 RuntimeEvent iterator。
- checkpoint / runtime observer 已默认收敛为结构化日志；需要 terminal 短日志时
  显式设置 `MY_FIRST_AGENT_DEBUG=1`。仍需继续清理其他 print-era 调试输出。
- stdout capture 只是从 print-era 到 event-era 的过渡方案，不应长期作为 UI
  projection 的数据来源。assistant delta、DisplayEvent、plan confirmation、slash
  command、request_user_input 和 `tool.requested` 已开始脱离 stdout；仍保留它是为
  了兜住 session/interruption、旧调用方和少量异常兜底输出。
- `on_output_chunk` / `on_display_event` callback 是阶段性兼容桥；当前 core 会先
  生成 RuntimeEvent 再转发给旧 callback。长期目标是 `chat_stream` /
  `RuntimeEvent` iterator。
- 第三阶段已收窄 legacy bridge：Textual 主路径收到 RuntimeEvent 后不再合并同轮
  stdout capture，避免重复 completion；RuntimeEvent 到旧 callback 的转发集中在
  main.py 兼容 helper 中。
- 第四阶段已把 simple CLI 接到 RuntimeEvent renderer：simple backend 调用
  `chat(..., on_runtime_event=...)`，assistant delta、control/tool lifecycle 和
  DisplayEvent 都通过 `render_runtime_event_for_cli` 投影到普通终端。启动 prompt、
  session lifecycle、退出/中断提示仍可 direct print；这些不是 Runtime 输出事件。
- 第五阶段已进一步降级 stdout capture：Textual 收到 RuntimeEvent 后不再合并同轮
  captured stdout；slash command 有 RuntimeEvent sink 时不再执行 stdout capture，
  只有没有 sink 的旧调用方才保留 print-era fallback。
- 第六阶段已把旧 callback 明确标记为 deprecated compatibility bridge：
  `on_runtime_event` 是 Textual + simple CLI 的主输出边界；`on_output_chunk` /
  `on_display_event` 只在没有 RuntimeEvent sink 的旧调用方路径中保留，避免同一条
  assistant delta 或 DisplayEvent 同时走新旧双轨。
- 补丁治理阶段已收窄 Textual 旧 callback 入口：`_run_textual_runtime_turn(...)`
  现在始终用 RuntimeEvent sink 调 `core.chat()`，旧 `on_output_chunk` /
  `on_display_event` 只由 main.py 的 RuntimeEvent bridge 兼容转发。这个改动解决的是
  “旧 callback 仍像主入口”的根因，不改变 RuntimeEvent 语义、checkpoint、
  `conversation.messages`、TaskState 或 Anthropic API messages。stdout capture 仍保留
  作为 print-era fallback；删除条件是所有用户可见 print 都完成事件化或明确不再投影。
- TUI-first 架构债务治理已经开始第一刀：Textual 常驻 Shell 被明确为产品主路径，
  simple CLI 降级为 debug/fallback adapter。`main.py` 仍保留 backend dispatch，但
  一轮 Runtime 调用已拆出 `_run_textual_runtime_turn(...)` 和
  `_run_simple_cli_runtime_turn(...)` 两个 adapter 边界，避免 terminal
  `input()`/`print()` 时代的协议继续支配 TUI 主路径。这个阶段不引入 InputIntent，
  不写 checkpoint/messages，不改变 TaskState，也不把 RuntimeEvent 和输入语义混用。
- 输入边界治理已开始第一刀：新增 `InputIntent` 分类层，把 UI adapter 收到的 raw
  input 先归类为普通消息、slash command、confirmation、request_user_input 回复、
  empty/exit/cancel/eof。`InputIntent` 的方向是 UI Adapter -> Runtime，和
  Runtime -> UI 的 `RuntimeEvent` 相反；它不写 checkpoint/messages，不改变
  Anthropic API messages，也不替代 TaskState。当前只用于 adapter 层集中判断，
  confirmation 和 request_user_input 的真正状态推进仍留在 `core.chat()` /
  `confirm_handlers.py`。
- confirmation 输入判断已开始收敛：`classify_confirmation_response(...)` 成为
  plan/step/tool confirmation 共享的 accept/reject/feedback 分类入口。
  `confirm_handlers.py` 不再维护自己的 yes/no/中文词表，但仍是状态推进层，继续负责
  checkpoint 保存、control event、pending_tool 清理和 tool_result placeholder；不能把
  InputIntent 写入 messages/checkpoint，也不能影响 tool_use_id 配对。
- structured slash command / request_user_input 输入收敛已完成第一刀：
  `parse_slash_command(...)` 只解析 UI/control 输入 metadata（`command_name` /
  `command_args` / `is_exit_command`），`main.py::handle_slash_command(...)` 仍负责
  执行命令。slash command 不进入 `conversation.messages`，不写 checkpoint，不混入
  RuntimeEvent 输入；Textual 产品路径和 simple CLI fallback 共享同一分类。当前
  request_user_input reply 在 pending 状态下归为 `request_user_reply`，后续仍由
  `core.chat()` / `confirm_handlers.py` 投影成 `user_replied` / `step_input`，不生成
  tool_result placeholder，也不改变 Anthropic API messages。
- request_user_input 仍需要专项语义决策：当前它是元工具控制信号，tool_use 不进入
  messages，用户回复也不生成 tool_result，而是写成 step_input 给下一轮模型。如果未来
  要改成 Anthropic tool_result 语义，必须一起设计 tool_use_id 配对、checkpoint 兼容、
  API messages migration 和旧会话恢复，不能用 placeholder 补丁临时补齐。
- Runtime 语义深化阶段已补齐 messages 投影边界：`RuntimeEvent` 是输出边界，
  `InputIntent` 是输入边界，二者都不进入 `context_builder` 的 Anthropic messages
  投影。`request_user_input` 回复以 `step_input` 文本进入 execution messages，不生成
  `ru_*` tool_result；业务 tool_result placeholder 仍只服务真实业务 tool_use 配对。
- slash command 结构化治理已落地轻量 `agent.commands`：InputIntent 仍只负责识别
  slash metadata，CommandRegistry 集中执行 `/help`、`/status`、`/clear`、
  `/reload_skills` 并返回 CommandResult，main.py 再投影成 `command.result`
  RuntimeEvent 或 simple CLI print。CommandSpec/CommandResult 不进入
  `conversation.messages`，不写 checkpoint，不改变 TaskState、Anthropic API messages、
  tool_use_id 配对或 tool_result placeholder；未知 slash command 现在由 registry
  消费成明确错误，不再落入模型消息。
- pending 状态下 slash command 的当前行为已经按代码固化：`empty` / `exit` /
  `slash_command` 优先于 pending_user_input_request、pending_tool 和 plan confirmation，
  因此 slash 可以作为 UI/control 输入打断 pending 状态。是否需要禁止或确认这种打断，
  属于后续产品/架构决策，不能在本阶段通过状态机或 checkpoint 补丁临时处理。
- generation cancel / `Esc` 打断模型生成尚未实现；当前 `Esc` 只清空编辑区。已将
  对应 xfail 收紧为 strict 设计标记：删除条件不是“Textual 停止 append chunk”，而是
  Runtime 先具备 cancel_token、stream abort 和 `generation.cancelled` 用户可见事件。
- 并行 tool_use / tool_result 顺序债务已收口到模型协议投影层：raw
  `conversation.messages` 仍是 Runtime append-only 事件流，pending_tool 可能导致
  placeholder 与真实 result 的落地顺序不同；但 `context_builder._project_to_api(...)`
  会按 assistant tool_use 声明顺序合并 result，Anthropic API messages 不再按执行完成
  顺序暴露给模型。旧 xfail 已改为普通回归测试；如果未来想让 raw messages 本身也
  有序，需要单独设计半开 tool_use queue，而不是改 checkpoint schema 或 placeholder
  语义。

下一阶段建议优先聚焦两件事：

1. **request_user_input 语义决策**：明确它长期是 `user_replied/step_input` 控制信号，
   还是要迁移为可配对 tool_result 协议；任何选择都不能破坏 tool_use_id 配对、
   checkpoint 恢复和 Anthropic API messages。
   当前推荐先保持 `step_input` 语义，除非能证明模型协议或上下文理解需要 tool_result
   形态；否则不应为元工具伪造 placeholder。
2. **Slash command policy 决策**：轻量 CommandRegistry 已建立，但 pending 状态下
   command 是否都允许打断仍按现有行为固化。后续若要改成“只有 `/exit` / `/cancel`
   可打断 pending，其它 command 作为回复或暂缓执行”，需要单独设计产品语义和测试，
   不能在 registry 里读取 pending 状态临时补丁。
3. **Seventh-stage cleanup**：继续事件化残留 print-era 用户可见输出，逐步降低
   stdout fallback 使用率；session lifecycle、debug/checkpoint/runtime_observer 仍保持
   在各自边界，不混入 UI event。
4. **RuntimeEvent iterator**：在已有 RuntimeEvent callback 骨架上继续演进为
   `chat_stream` / RuntimeEvent iterator，并逐步移除旧 callback/stdout capture。
   debug/checkpoint 仍不进入 UI RuntimeEvent，继续走结构化日志。
5. **Input boundary later**：普通 CLI 多行粘贴 / paste burst 属于输入层产品化，之后
   单独设计，不和 RuntimeEvent 输出边界混改。
6. **Cancellation design**：之后再为 cancellation / `generation.cancelled` 设计完整
   lifecycle：Textual 只发起取消意图，main.py 传递 cancel_token，core/chat 和模型
   stream 负责 abort，RuntimeEvent 只投影用户可见的取消结果。不能把 Esc 编辑取消、
   InputIntent、CommandResult、checkpoint、runtime_observer 或 simple CLI fallback
   混成一个临时补丁。
7. **Raw tool transaction ordering**：API 投影已按 declaration order 稳定输出，但 raw
   conversation 仍按 Runtime 事件发生顺序追加。如果后续确实需要 raw 层也有序，再设计
   pending tool transaction queue；这会触及 checkpoint 恢复和半开事务，不应顺手改。
8. **Checkpoint/debug hygiene**：checkpoint / runtime observer 已先收敛为默认写
   结构化日志、terminal debug 显式开启；下一步应把其余 print-era debug 也迁移
   到 DisplayEvent / structured logger。

当前验证结果：

- `python -m pytest tests/test_input_backends_textual.py tests/test_main_input.py tests/test_main_loop.py tests/test_meta_tool.py tests/test_runtime_observer.py tests/test_runtime_observability.py -q`
  - `72 passed, 1 xfailed`
- `python -m ruff check agent/ tests/`
  - `All checks passed`
- `python -m pytest tests/ -q`
  - `223 passed, 6 xfailed`

---

## User Input Layer productization（输入层产品化）

> **状态（2026-04-26）：阶段 1 止血中，尚未终局化**

真实 CLI 冒烟测试已经证明：用户自然粘贴编号列表、多行文本或大段说明是正常
产品行为，不能要求用户必须使用 `/multi`。`/multi` 可以继续保留为显式高级协议，
但不能成为唯一正确用法。

### 阶段 1 · Runtime 防御（止血，不是终局）

- `empty_user_input` guard：空输入 / 纯空白不应被当作有效回答，不能 append
  `step_input`、不能清 pending、不能推进 step、不能保存 checkpoint。
- text fallback 收紧：只有“缺少必要信息导致无法继续/完成”的阻塞式文本，才应
  触发 `model.text_requested_user_input`；最终答案后的“如需调整请告诉我”这类
  开放式 follow-up 不应进入 `awaiting_user_input`。
- 补 context projection / request_user_input loop stop 测试：验证现有 Runtime 链路
  没有丢多行答复，也不会在 request_user_input 后继续重复调模型。

这一步只是减少真实使用中的误伤，不代表用户输入层已经产品化。

### 阶段 2 · UserInputEnvelope（正式输入层）

中期应新增 `UserInputEnvelope`，让 CLI / frontend 读入的内容先被包装成明确输入
对象，再交给 `InputResolution`。最小字段：

- `raw_text`
- `normalized_text`
- `input_mode`
- `source`
- `line_count`
- `is_empty`

届时 `read_user_input -> str` 应逐步演进为返回 envelope，
`resolve_user_input(state, user_input: str)` 也应演进为接收 envelope。
日志只打印 `input_mode` / `line_count` / `is_empty` 等元信息，不打印完整用户原文。

### 长期 · 多行粘贴 UX

- 短期：保留 `/multi`，但提示更清楚。
- 中期：评估普通 CLI 下自动 paste burst 合并。
- 长期：考虑 `prompt_toolkit` / bracketed paste / multiline UX。

目标是支持用户自然粘贴多行、编号列表、大段文本，而不是把输入协议负担转嫁给用户。

---

## TaskState status dimensions（状态维度收口）

> **状态（2026-04-26）：第一阶段 helper 收口中，未迁移 schema**

`TaskState.status` 当前仍是一个字符串字段，但实际混合了承载：

- 任务生命周期：`idle` / `running` / `done`
- plan 确认：`awaiting_plan_confirmation`
- step 确认：`awaiting_step_confirmation`
- 用户输入等待：`awaiting_user_input`
- 工具确认：`awaiting_tool_confirmation`

第一阶段只做轻量收口：新增 status 分类常量和 helper，把 `core.py` 里
`current_plan is None` 的硬编码 tuple 替换为 `task_status_requires_plan(...)`。
这样能先让状态一致性规则可测试、可集中维护。

中长期再评估是否拆出：

- `lifecycle_status`
- `plan_status`
- `tool_status`
- `user_input_status`

暂不做 checkpoint schema migration，也不新增 `TaskState` 字段。拆字段前需要先设计
旧 checkpoint 到新状态模型的兼容映射。

---

## 总览：6 个阶段 × 22 个 block

```
阶段 0  工程基建          ← 当前应立即开始（从 3.5→4 的关键）
阶段 1  协议级演进        ← 核心 loop 质量继续升级
阶段 2  能力边界扩展      ← sub-agent / MCP / 并发
阶段 3  记忆与上下文演进  ← 从单会话到长期人格
阶段 4  交互与产品化      ← review / budget / 多会话
阶段 5  突破性探索        ← 研究级尝试（可选）
```

每个阶段的 block 按 **"必做 / 推荐做 / 可选做"** 三级排序。

每个 block 的格式：
1. **问题陈述**：当前代码缺什么、后果是什么
2. **为什么此时做**：不是越早越好，有前置依赖
3. **业界标准**：主流开源/闭源项目怎么做
4. **突破性思路**：更激进、可能失败但有潜在价值的方向
5. **代码落点**：改哪些文件、大致工作量
6. **完成信号**：怎么判断这块做完了

---

## 阶段 0：工程基建（3.5 → 4）

**目标**：把现有 "能跑" 的 agent loop 升级为 "能安全地持续演进"。  
**时间预算**：1-2 周（按业余时间推进）

### Block 0.1 · 集成测试（🔴 必做 · 一切之母）

> **状态（2026-04-26）：✅ 持续扩展，已纳入版本管理**
> - `tests/` 已纳入版本管理（删 `.gitignore: tests/` 后正式入仓），17+ 个测试文件，**~120 passed / 4 xfailed**（xfail 都是显式记录的设计债，不是未修 bug）
> - `tests/conftest.py` 的 `FakeAnthropicClient` + `text_response` / `tool_use_response` / `meta_complete_response` 三套构造器
> - 专项文件：`test_api_projection.py`（协议投影）/ `test_tool_pairing.py`（配对）/ `test_state_invariants.py`（状态机）/ `test_long_running.py`（15 轮连续确认、压缩穿插）/ `test_hardcore_scenarios.py` + `test_hardcore_round2.py`（"为了捕 bug 而写"）/ `test_meta_tool.py`（元工具完成协议 + request_user_input 求助 + 双层兜底）/ `test_completion_handoff.py`（含 `MAX_LOOP_ITERATIONS` 终极兜底）/ `test_main_input.py`（CLI 多行输入协议，2026-04-26 新增）
> - MVP 里提到的三个场景早已覆盖；property-based / TLA+ 仍未做（真到瓶颈再考虑）

**问题陈述（历史）**  
当时 `test_lint.py` 只有 7 行占位。10 几个重构 PR、12 个文件、+534 行改动**完全没有自动化回归保护**。

**为什么此时做（历史）**  
是**所有后续 block 的前置条件**。没有测试你做 prompt caching 不敢改 `_call_model`，做 sub-agent 不敢动 `state` 单例，做 MCP 不敢改 `tool_registry`。每一个改动的风险都在线性积累。

**业界标准**

| 项目 | 测试方案 |
|---|---|
| **aider** | `pytest` + 大量 fixtures 模拟文件系统操作 + 一套 `test_coder.py` 覆盖 edit loop |
| **Claude Code** | 内部有完整的 e2e 框架（我们看不到），但从开源的 skill 示例看是 pytest + mock client |
| **LangChain** | 用 `LangChain Smith` 跑评测 + pytest 单测 |
| **OpenAI SDK 示例** | 用 `responses` 库 mock HTTP 层，断言请求体结构 |

**最低可行方案（MVP）**：写一个 **fake Anthropic client** + 3 个 pytest 场景：

```python
# tests/conftest.py
class FakeAnthropicClient:
    def __init__(self, responses: list):
        self.responses = iter(responses)
    def messages_stream(self, **kwargs):
        return FakeStream(next(self.responses))

# tests/test_chat_flow.py
def test_single_turn_end_turn(fake_client):
    """场景 1：你好 → end_turn"""
    # 配置 fake_client 返回一个 text 块 + end_turn
    # 断言：state.task.status 变化、messages 正确追加

def test_single_tool_cycle(fake_client):
    """场景 2：tool_use → tool_result → end_turn"""

def test_parallel_tool_use_with_confirmation(fake_client):
    """场景 3：多 tool_use，其中一个需确认 → 占位 tool_result 配对"""
```

**突破性思路（可选）**
- **property-based testing**（`hypothesis`）：生成随机 messages 序列 + 随机 stop_reason，断言"永远不会产生非法 tool_use/tool_result 配对"。业余 agent 极少做，但能发现边界 bug。
- **状态机 model-checking**：用 `automat` 或手写 TLA+ lite，显式列出 `task.status` 的所有合法转换，让测试自动枚举所有转换边。

**代码落点**
- 新建 `tests/` 目录
- `tests/conftest.py`（fake client + fixtures）
- `tests/test_chat_flow.py`（主流程）
- `tests/test_protocol.py`（tool pairing 专项）
- `tests/test_state_machine.py`（状态转换）
- 工作量：**1-3 天**（取决于熟悉 pytest 程度）

**完成信号**
- `pytest` 一条命令跑过 5-10 个场景
- 改任何一个 response_handler 如果破坏了协议配对，立刻有测试红
- CI（哪怕只是本地 git hook）阻止破坏测试的 commit

---

### Block 0.2 · 类型系统加强（🟠 推荐做）

**问题陈述**  
当前 `state.task.status: str = "idle"`——字符串。新增一个状态，所有 if 判断散落在 8 个文件里，没有地方强制同步更新。这就是 `awaiting_tool_confirmation` 注释漏写的根源。

**为什么此时做**  
在测试之后、大重构之前。类型标注**本身就是一种测试**——编译期的测试。做完之后，你重构时 mypy/pyright 会立刻标记出所有漏改的点。

**业界标准**

| 方案 | 优缺点 |
|---|---|
| **`typing.Literal`** | 轻量，零依赖。适合枚举值有限的场景。推荐。 |
| **`enum.Enum`** | 更结构化，但要处理 `Enum.RUNNING.value == "running"`。适合复杂状态机 |
| **`pydantic` BaseModel** | 已在用 `PlannerOutput`。可以把整个 `TaskState` 改成 pydantic，运行时也校验 |

推荐 **Literal 优先**，将来需要更多功能再升 Enum：

```python
from typing import Literal

TaskStatus = Literal[
    "idle", "planning", "running",
    "awaiting_plan_confirmation",
    "awaiting_step_confirmation",
    "awaiting_tool_confirmation",
    "done", "failed",
]

@dataclass
class TaskState:
    status: TaskStatus = "idle"
```

配上 `mypy --strict` 或 `pyright`，跑一遍你的项目，会自动标出每处非法值。

**突破性思路**
- **结合运行时 + 静态校验**：状态转换用 `transitions` 库（Python 状态机框架），运行时拒绝非法跳变 + 静态知道合法状态集。业余项目极少，但状态机复杂化后价值高。
- **Pydantic + 数据库迁移风格的 state 版本化**：给 `TaskState` 打 schema 版本号，老 checkpoint 恢复时自动 migrate。你未来改 state 字段时不会 break 老用户。

**代码落点**
- `state.py`：`status: str` → `status: TaskStatus`
- 引入 `mypy` 或 `pyright`，配置 `pyproject.toml`
- 工作量：**半天到一天**

**完成信号**
- mypy/pyright 跑整个 agent/ 目录无 error
- 新增状态值时 IDE 自动补全 + 静态警告漏改的地方

---

### Block 0.3 · Prompt Caching（🟠 推荐做 · 成本拐点）

**问题陈述**  
当前每次 `_call_model` 都发完整 `system_prompt` + 所有 `tools` 定义 + 完整 `messages`。在一次长任务里可能调模型 20 次，**前 80% 的 context 是重复的**。Anthropic 按 input token 计费，你在重复花钱。

**为什么此时做**  
一旦你跑更多 loop、做 sub-agent、跑评测，**成本会指数上升**。Anthropic 的 prompt caching 是**单点改造、收益 90% 以上**的黄金优化。最划算的 1 小时投入。

**业界标准**

Anthropic Prompt Caching（2024 GA）：在 request 里给某个 content block 加 `cache_control: {type: "ephemeral"}`，Anthropic 服务端缓存这一段的 prefix，后续请求命中 prefix 的部分**按 10% 价格收费 + 延迟大幅下降**。

```python
system=[
    {
        "type": "text",
        "text": "你是一个通用智能 Agent...",
        "cache_control": {"type": "ephemeral"}
    }
]

# 或在 tools 里对最后一个工具加 cache_control，它会 cache "system + tools[:N+1]"
tools=[
    {"name": "read_file", ...},
    {"name": "write_file", ..., "cache_control": {"type": "ephemeral"}},
]
```

最佳实践：
1. **system prompt 作为第一个缓存块**（极其稳定，每次都一样）
2. **tools 定义作为第二个缓存块**（仅当新增 tool 时变）
3. **长期 working_summary** 可选作为第三块

**突破性思路**
- **自适应缓存策略**：根据对话长度、调用频率动态决定缓存哪些块。比如对话超过 10 轮，把前 5 轮 messages 也加上 cache_control。
- **跨 session 缓存复用**：Anthropic 的 ephemeral cache 只持续 5 分钟。如果自己维护一个 prompt hash + cache id 映射，理论上可以跨 session 复用（但实现复杂，收益不一定高）。

**代码落点**
- `core.py::_call_model`：把 `system=turn_state.system_prompt` 改成 list 形式 + cache_control
- `tool_registry.py::get_tool_definitions`：最后一个 tool 加 cache_control
- 观察 `response.usage.cache_read_input_tokens` / `cache_creation_input_tokens` 验证命中
- 工作量：**1-2 小时**

**完成信号**
- `response.usage.cache_read_input_tokens > 0` 在第二次及以后调用中稳定出现
- 账单下降 50%+（长任务里）

---

### Block 0.4 · Cost 追踪（🟠 推荐做）

**问题陈述**  
`response.usage` 拿到了但没读。你在花钱，但不知道花多少、花在哪。Stage 3 做 sub-agent 后，多个子 agent 并发调用会让你失控更快。

**为什么此时做**  
做完 caching（0.3）之后立刻做。两个配合：caching 降成本，cost 追踪**让你看见降了多少**。没有度量就无法优化。

**业界标准**

| 项目 | 方案 |
|---|---|
| **aider** | 每次调用打印 `Tokens: 1,234 sent, 567 received. Cost: $0.01 request, $0.12 session` |
| **Claude Code** | 右下角状态栏实时显示 cost，可以 `/cost` 命令查看明细 |
| **LangChain** | `get_openai_callback()` context manager，自动累加 |
| **OpenAI Usage API** | 服务端统计，延迟 1 天 |

**本项目 MVP**：

```python
# state.py
@dataclass
class TaskState:
    # 新增
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0

# core.py::_call_model 里
from config import PRICING  # {"claude-opus-4-5": {"input": 15/1e6, "output": 75/1e6, "cache_read": 1.5/1e6, "cache_creation": 18.75/1e6}}

# response 回来后
u = response.usage
cost = (u.input_tokens * PRICING[MODEL]["input"]
     + u.output_tokens * PRICING[MODEL]["output"]
     + u.cache_read_input_tokens * PRICING[MODEL]["cache_read"]
     + u.cache_creation_input_tokens * PRICING[MODEL]["cache_creation"])
state.task.cost_usd += cost
state.task.input_tokens += u.input_tokens
# ...

# reset_task 里（别忘了！）
self.task.cost_usd = 0.0
self.task.input_tokens = 0
# ...
```

**⚠ 最容易漏的地方**：`reset_task()` 没加这几行 —— 跨任务成本累加就永远清不掉。

**突破性思路**
- **细粒度 cost 归因**：把 cost 归属到具体 plan step / tool call。做出来之后你能回答"哪一步最烧钱"这种问题。
- **Budget 硬阈值**：当 `state.task.cost_usd > budget` 自动中断。避免失控跑飞。
- **多模型路由 based on cost**：简单问题走 haiku，复杂走 opus。aider 有类似设计（`--weak-model` + `--strong-model`）。

**代码落点**
- `config.py`：加 `PRICING` dict
- `state.py::TaskState`：加 cost 字段
- `state.py::reset_task`：加对应清零
- `core.py::_call_model`：读 usage、累加、打印
- 工作量：**半天**

**完成信号**
- 每次 chat 完成打印 "本轮 $0.12，累计 $0.54"
- checkpoint 保存后包含 cost 字段（`_copy_state_dict` 自动带上）

---

### Block 0.5 · 可观测性基础（🟡 可选做）

**问题陈述**  
现在只有 `agent_log.jsonl` 事件日志。没有 metrics（QPS、latency、error rate），没有 trace（一次 chat 跨哪些函数各花了多少时间）。生产化前该补。

**为什么此时做**  
业余项目可以跳过。但如果你想做**评测（evals）**——跑 100 个标准任务，比较不同版本 agent 的通过率、平均步数、平均成本——必须有这层度量。

**业界标准**

| 层级 | 工具 |
|---|---|
| **Metrics（数值指标）** | `prometheus_client`（本地暴露 /metrics）+ Grafana；或简单用 `statsd` |
| **Tracing（调用链）** | OpenTelemetry SDK + Jaeger / Honeycomb / Datadog |
| **Evals** | `promptfoo`、`langsmith`、`inspect`（Anthropic 官方）、自建 |

**本项目 MVP**：最小投入是**包一个 decorator** 打点：

```python
# agent/observability.py
from contextlib import contextmanager
import time

@contextmanager
def span(name: str, **attrs):
    start = time.time()
    try:
        yield
    finally:
        duration = time.time() - start
        log_event("span", {"name": name, "duration_ms": duration*1000, **attrs})

# 用法
with span("call_model", iteration=state.task.loop_iterations):
    response = ...
with span("execute_tool", tool=tool_name):
    result = ...
```

**突破性思路**
- **Execution replay**：把所有事件（user input + API response + tool result）以 append-only 存盘，实现"重放一次历史 session"。调试时用重放代替真实调用，省钱又可复现。
- **Eval 框架**：维护一组 "golden tasks"（比如 20 个标准任务），每次改 agent 跑一遍，记录通过率、步数、成本的 diff。**这是生产化 agent 的标配**。

**代码落点**
- 新建 `agent/observability.py`
- 在 `_call_model` / `execute_tool` / 关键状态转换处加 `with span()`
- 工作量：**1 天**（基础）到 **1 周**（加 evals 框架）

**完成信号**
- 能回答 "上周我跑了多少次 agent、总耗时多少、单次平均 token 数"
- 能用同一组 golden tasks 对比两个版本 agent

---

## 阶段 1：协议级演进

**目标**：把现有 loop 的**脆弱点**（靠关键词判断步骤、tool_use 串行执行等）**协议化**。  
**前置**：阶段 0 的 0.1（测试）必须做完。

### Block 1.1 · 步骤完成协议化（🔴 必做）

> **状态（2026-04-25）：✅ 已完成 · 实际落地比原方案更彻底**

**问题陈述（历史）**  
`is_current_step_completed` 用关键词 `"本步骤已完成"` 检测。模型忘说就卡死。这是架构文档 §6 的难点 #7。

**实际落地（比原方案更彻底的 5 点偏离）**

1. **硬切换，非双保险**  
   原方案建议"工具 + 关键词兜底"。实际：关键词匹配**整个删掉**，只认 `mark_step_complete` 工具信号。  
   理由：两套并存 = 两套心智负担 + 测试要验证两条分支；不如一刀切。代价是"模型忘调工具时卡死"（见 xfail 测试 `test_step_never_progresses_when_model_forgets_to_call_mark_step_complete`），但这是干净的失败模式。

2. **三参数 + 分值，非"summary 一个字段"**  
   ```python
   mark_step_complete(
       completion_score: int,   # 0–100 自评
       summary: str,            # 客观事实：这步做了什么
       outstanding: str,        # 未完成项（<100 时必填）
   )
   ```
   `STEP_COMPLETION_THRESHOLD = 80`（`config.py`）。分值 ≥ 阈值才真推进；< 阈值把 `outstanding` 注入下一轮 step block 让模型继续——**闭环自纠正**，不再卡死只能靠 MAX_LOOP 兜底。

3. **元工具协议：注册表加 `meta_tool=True` 字段**  
   `tool_registry.py::register_tool(meta_tool=False)` + `is_meta_tool(name)` 查询。  
   元工具的执行路径是**独立分支**：
   - `tool_executor`：只写 `state.task.tool_execution_log`（带 `step_index`），**不产生 tool_result**、**不追加到 messages**
   - `response_handlers._serialize_assistant_content`：剔除元工具的 tool_use 块，不写 `state.conversation.messages`
   - 效果：模型后续轮次**看不到**自己前面调过元工具——避免"系统控制信号污染业务对话上下文"的语义混乱

4. **tool_execution_log 增 `step_index` 字段**  
   所有 log 条目（业务 + 元工具）都记录 `step_index`。`get_latest_step_completion(state)` 按 step 隔离读，取"当前步骤的最近一条"（后来居上：模型先报低分再补齐打高分时自然生效）。

5. **Tool-use 轮直接推进，不等 end_turn**  
   抽出 `_maybe_advance_step(state)` 辅助：元工具记录完立刻判 + 推进/等确认/收尾，不跑多一轮 API 调用。  
   驱动原因：元工具若单独出现（没业务工具陪同），下一轮 messages 会是 `assistant(text) → 没有 tool_result`，模型空跑一轮可能"重说一遍" text，和之前的 Kimi 死循环事故同源。提前推进 = 省钱 + 杜绝重复输出。

**代码落点（实际）**
- `config.py`：`STEP_COMPLETION_THRESHOLD = 80`
- `agent/tool_registry.py`：`meta_tool` 字段 + `is_meta_tool()`
- `agent/tools/meta.py`（新）+ `agent/tools/__init__.py`：注册 `mark_step_complete`
- `agent/tool_executor.py`：元工具特殊路径 + log 加 `step_index`
- `agent/response_handlers.py`：`_serialize_assistant_content` 过滤元工具 + `_maybe_advance_step` 抽出
- `agent/task_runtime.py`：`is_current_step_completed(state)` 读 log；新增 `get_latest_step_completion()`
- `agent/context_builder.py`：step block `【完成要求】` 改成"必须调 mark_step_complete"；低分时注入 `【上一轮自评】` + outstanding

**测试（新增 / 改写）**
- `tests/test_meta_tool.py`（新）5 条集成回归：阈值推进 / 低分不推进 + outstanding 注入 / 元工具不进 messages / step_index 正确 / 元工具不占 per-turn 配额
- `tests/test_semantics.py` 3 条原关键词断言重写为 log 查询语义 + 加"多次自评后来居上"
- `tests/conftest.py`：`meta_complete_response(score, summary, outstanding, text)` 构造器
- 11 处其他测试里的 `text_response("...本步骤已完成")` 替换为 `meta_complete_response(...)`
- xfail `test_step_never_progresses_when_model_forgets_completion_keyword` 改名 `..._forgets_to_call_mark_step_complete`，同类型脆弱性继续钉死（没降级，只是换对象）

**剩余隐患**
- 模型连续 N 轮 end_turn 都不调元工具时旧实现只靠 MAX_LOOP 兜底——见下方 Block 1.5（已落地双层兜底，覆盖此项）。
- `STEP_COMPLETION_THRESHOLD` 是全局常量，没按 PlanStep 粒度可配置。"生成长文"和"改 bug"想要不同阈值的话，需要在 `PlanStep` 里加字段。先不做。

**延伸（2026-04-26）· request_user_input 复用元工具协议**

`mark_step_complete` 验证完元工具协议后，第二个落地的元工具是 `request_user_input`——执行期临时向用户索要关键信息。这是 Block 1.1 建立的"系统控制信号 = 元工具"语义的第二次复用：

- 同样 `meta_tool=True` / `confirmation="never"`，走 `tool_executor` 元工具特殊路径
- 副作用：写 `tool_execution_log` + 设 `state.task.pending_user_input_request` + 切 `status = "awaiting_user_input"` + `save_checkpoint`
- 沿用"不进 messages、不生 tool_result"的不变量；用户回复经 `handle_user_input_step` 的求助分支以 `step_input` 控制事件回到当前 step
- **当前 step_index 不推进**——这是和 `collect_input` / `clarify` 类型 step 的关键区别（前者是"执行中卡住要补信息"，后者是"这一步本身就是问用户"）
- **B 防御**：求助元工具触发时同步剔除当前 step_index 的 `mark_step_complete` log 残留——避免"模型违纪同轮调 mark+request 后用户回复触发错误推进"

**为什么把"求助"也做成元工具而不是普通自然语言或业务工具**：自然语言提问会让模型继续 end_turn，runtime 拿不到"我在等用户"的明确信号；普通工具会进 messages 制造噪声并强制配 tool_result。元工具是"runtime 状态事件"——可持久化、可恢复、可测试，与普通对话内容彻底解耦。这是把"需要用户输入"从 prompt 层下沉到状态机层的关键一步。

**代码落点（实际）**
- `agent/tools/meta.py`：注册 `request_user_input(question, why_needed, options, context)`
- `agent/tool_executor.py`：元工具分支按工具名分派；`request_user_input` 写 pending + 切 status + 清 stale mark
- `agent/state.py`：`TaskState` 加 `pending_user_input_request` + reset_task 清空
- `agent/confirm_handlers.py::handle_user_input_step`：求助分支（pending 非 None）vs collect_input 旧路径双轨
- `agent/conversation_events.py`：`step_input` 渲染按 payload 是否含 `question` 走配对文案
- `agent/context_builder.py`：普通步骤纪律段加"信息缺口处理"约束

**剩余隐患**
- 当前按工具名 `if tool_name == "request_user_input"` 硬编码分派；元工具增多时可在 `register_tool` 加 `meta_kind` 字段抽象（按 Parnas 等到第三个元工具再做）
- `options` / `context` 因 `tool_registry` 不支持 optional schema 而被强制 required；prompt 里告诉模型无候选传 `[]` / 无信息传 `""`。`tool_registry` 抽 optional 是单独的小重构

---

### Block 1.2 · 独立审计层（history.jsonl）（🟠 推荐做）

**问题陈述**  
当前 `state.conversation.messages` 既是 "send queue"（发给 API）又是 "history"（本地记录）。压缩时被吃掉的原文就永久丢了（除非恰好那一刻 session snapshot 了）。

**为什么此时做**  
你已经在上一轮对话里意识到这个问题（"全部存下来"），并且同意它属于后期。现在做的理由：**Stage 3 做 sub-agent 之后，数据量会暴涨**，后补成本变高。早做早好。

**业界标准**

| 项目 | 方案 |
|---|---|
| **aider** | 把所有 LLM 请求/响应存在 `.aider.chat.history.md`，纯 append |
| **Claude Code** | `--resume` 依赖完整 session 日志，每一步都落盘 |
| **event sourcing 理念（DDD）** | 所有状态变化都是事件，append-only，状态是事件流的 projection |

**本项目 MVP**：

```python
# agent/history.py
HISTORY_PATH = PROJECT_DIR / "memory" / "history.jsonl"

def append_history(event_type: str, payload: dict):
    entry = {"timestamp": now_iso(), "event_type": event_type, **payload}
    with open(HISTORY_PATH, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

# 在每次 _append_assistant_response / append_tool_result / append_control_event 时调一次
```

**突破性思路**
- **SQLite 而非 JSONL**：SQLite 支持查询（"给我所有 cost > 0.5 的任务"、"给我某个 tool 的所有错误"）。基础设施增加但回报大。
- **向量化**：每条 history 附带 embedding，后续用于长期记忆召回（Block 3.2）。
- **DAG 式 history**：sub-agent 场景下，history 不是线性而是树状（每个 sub-agent 一条分支）。提前考虑这个结构为 2.1 铺路。

**代码落点**
- 新建 `agent/history.py`
- 在 `conversation_events.py` 和 `response_handlers.py` 的 append 点各加一行
- 工作量：**半天到一天**

**完成信号**
- 哪怕压缩吃掉了原文，history.jsonl 里仍有完整记录
- 可以写一个简单的 replay 脚本从 history 重建某次 session

---

### Block 1.3 · 错误恢复与重试（🟡 可选做）

**问题陈述**  
当前 `_call_model` 失败（网络断、5xx、rate limit）直接 raise，整个 chat 崩溃。Anthropic 官方 SDK 自带部分重试，但对 5xx 之外的错误（超时、连接重置）不兜底。

**业界标准**
- **tenacity** 库：`@retry(stop=stop_after_attempt(3), wait=wait_exponential())`
- **官方 SDK 配置**：`Anthropic(max_retries=3)`
- **幂等键**：对于 tool 执行，可选带 idempotency key（你的 `tool_execution_log` 已经部分实现）

**突破性思路**
- **自适应退避**：根据错误类型（rate limit vs 网络错）选不同策略
- **模型降级**：opus 失败自动降到 sonnet 重试
- **checkpoint-level 重放**：整个 chat 失败时，不是从头而是从最近 checkpoint 重放

**代码落点**
- `config.py` 里改 `anthropic.Anthropic(max_retries=3)`
- 或在 `_call_model` 外包一层 `@retry`
- 工作量：**2 小时**

---

### Block 1.4 · 流式 tool_use 处理（🟡 可选做）

**问题陈述**  
当前 `_call_model` 里对流式事件只处理 `content_block_delta` 的 text。模型生成 tool_use 时，`input` 字段也是流式增量生成的（`input_json_delta` 事件）。现在你等 `get_final_message()` 才拿到完整 input——相当于放弃了流式。

**为什么做**
- UX：用户能实时看到"模型在构造参数"
- 性能：长 input（比如 diff）可以边生成边开始预执行

**业界标准**
- OpenAI Realtime API、Anthropic 的 `input_json_delta` 事件
- `partial_json` 库：流式 JSON 解析

**突破性思路**
- **Speculative execution**：tool_use 还没生成完，先用已有部分猜测完整 input 并开始执行。猜错了撤销。

**代码落点**
- `core.py::_call_model` 流事件循环中处理 `input_json_delta`
- 工作量：**1 天**

---

### Block 1.5 · 主循环 loop guard / runtime 兜底（🔴 必做）

> **状态（2026-04-26）：✅ 已完成**

**问题陈述**

Block 1.1 的元工具协议 + 1.1 延伸的 `request_user_input` 是**理想路径**——前提是模型遵守协议。但 LLM 不一定守规矩：可能用普通自然语言追问、可能 end_turn 等下一轮、可能空跑一段时间。`handle_end_turn_response` 的旧实现在 `running` 分支硬塞"请打分或继续"提示，**模型若违纪用文本散问会陷入死循环**：注入 → 散问 → end_turn → 再注入 → … 实测真的炸过（武汉旅游规划场景，模型反复追问已答字段，用户 Ctrl+C 才退出）。

**为什么此时做**

`request_user_input` 落地后必须配套 runtime 兜底，否则它只是"理想协议"——一旦模型违纪，整个 `awaiting_user_input` 机制反而成了死循环的放大器。这是 prompt 约束 vs runtime 约束的经典分工：**prompt 告诉模型应该怎么做，runtime 兜底"做不到时怎么办"**。

**业界标准**

| 方案 | 哲学 |
|---|---|
| **prompt-only 约束** | 只靠提示词告诉模型"必须用工具"。最常见，最脆弱 |
| **runtime fallback** | 模型违纪时 runtime 主动暂停 / 介入。aider 的 `--exit-on-error`、Claude Code 的"卡死检测" |
| **正式状态机 + model checking** | TLA+ 等形式化方法穷举所有违规路径（见 5.1） |

本项目走第二条：**把"模型可能不遵守协议"从 prompt 层下沉到 runtime 层**。

**实际落地（三层防线 + 终极安全阀）**

1. **理想路径**：模型调 `request_user_input`。Block 1.1 延伸已覆盖。

2. **兜底 1 · 启发式**（第一层防线）：assistant 文本含问号 / 中文求助词（`请告诉我 / 请提供 / 请说明 / 请回复 / 请补充 / 麻烦您 / 您能否 / 请确认`）→ 立即切 `awaiting_user_input`，把 assistant 文本作为隐含 question 写进 `pending_user_input_request`，return ""。

3. **兜底 2 · 计数**（第二层防线）：连续 2 次 end_turn 没有任何工具调用、没有 `mark_step_complete`、没有有效推进 → 强制切 `awaiting_user_input`。覆盖陈述句问题之类启发式漏判的场景。新增 `state.task.consecutive_end_turn_without_progress` 字段；`handle_tool_use_response` 开头清零（任意工具调用都算"有效推进"）；`handle_end_turn_response` running 分支自增；`>= 2` 强停。

4. **终极兜底**：`MAX_LOOP_ITERATIONS = 50` 仍保留为最后安全阀，防止其它未知空转模式（比如模型每轮都"看似有进展"调业务工具但永远不调 mark_step_complete 收敛）。专门有测试 `test_max_loop_iterations_terminal_guard_still_fires_when_double_layer_bypassed` 构造"绕过双层兜底但永不收敛"的场景验证终极防线还在。

**突破性思路**

- **行为兜底而非内容判定**：计数兜底基于"有没有工具调用"这个客观事实，不靠语义识别。这避免了启发式词表的脆弱性
- **runtime 是协议合规的最后一道防线**：和 §3 "tool_use ↔ tool_result 配对契约" 的 6 层防御同源——不能假设上层（模型 / 调用方）守规矩
- **"温和软驱动 + 强制兜底"两段式**：第 1 次 end_turn 仍注入"请调用 mark_step_complete 或 request_user_input"（保留模型在思考时的合理停顿空间）；第 2 次才强停（防死循环）。比"第 1 次就停"更友好，比"无限放行"更安全

**代码落点**

- `agent/state.py`：TaskState 加 `consecutive_end_turn_without_progress: int = 0` + reset_task 清零
- `agent/response_handlers.py`：`handle_tool_use_response` 开头清零；`handle_end_turn_response` running 分支替换为双层兜底
- `agent/context_builder.py`：普通步骤纪律段加"禁止只用文本提问后 end_turn——必须调 request_user_input；违纪 runtime 会强制暂停"
- 测试：`test_endturn_with_question_text_triggers_pause` / `test_two_consecutive_endturns_without_progress_trigger_pause` / `test_tool_call_resets_endturn_counter` / `test_max_loop_iterations_terminal_guard_still_fires_when_double_layer_bypassed`
- 工作量（实际）：**1 天**

**剩余隐患 / 取舍**

- 启发式词表硬编码常量。漏判时逐项扩展即可（不要做复杂 NLP 分类器；多刷一屏问题由计数器接住）
- 计数兜底阈值 `>= 2` 是经验值。改 1 太激进（模型走 end_turn 是合理停顿也会被打断），改 3+ 更温和但用户感知更慢
- 关键不变量：**任意工具调用都清零计数器**（业务工具 + 元工具都算）。已加测试钉死

---

## 阶段 2：能力边界扩展

**目标**：从"单 agent 单任务"扩到"多 agent / 外部工具 / 并发"。  
**前置**：阶段 0 全部 + 阶段 1 的 1.1 / 1.2。

### Block 2.1 · Sub-agent（🔴 必做 · 但是重构级别）

**问题陈述**  
当前 `state` 是 `core.py` 模块级全局单例。Sub-agent 需要父子隔离的 state，全局单例挡路。

**业界标准**

| 项目 | 方案 |
|---|---|
| **Claude Code** | 显式 sub-agent，有独立 context window，通过 Task 工具启动 |
| **AutoGPT** | 粗糙的 sub-agent，实际是 prompt 模板套娃 |
| **LangGraph** | 把 agent 建模为 graph node，每个 node 独立 state。强结构化 |
| **OpenAI Swarm** | 极简 "handoff"：父 agent 调用子 agent 工具，子 agent 拿自己的 messages |

推荐先用最简单的 **handoff 模式**：
```python
@register_tool(name="spawn_sub_agent", ...)
def spawn_sub_agent(goal: str, allowed_tools: list[str]) -> str:
    sub_state = create_agent_state(system_prompt=SUB_AGENT_PROMPT, ...)
    sub_state.task.user_goal = goal
    result = chat(goal, state=sub_state)  # ← 这里需要 chat 支持 state 参数
    return result
```

**重构前置**：必须先把 `state` 从全局改成参数。

**突破性思路**
- **共享 long-term memory，独立 working memory**：父子 agent 共享 `state.memory.long_term_notes` 但各有独立的 `conversation.messages` 和 `task`。
- **Agent graph / DAG**：不是父子二元，是 DAG。一个 task 分发给 N 个 sub-agent 并行执行，结果汇总。类似 MapReduce。
- **"Thinking" sub-agent**：主 agent 遇到难题时，启动一个"只思考不行动"的 sub-agent（可以开 extended thinking + 更强模型），返回思考结果。

**代码落点**
- 重构：`chat(state, user_input)` 而不是 `chat(user_input)` 读全局
- 新增：`agent/sub_agent.py`
- 工作量：**3-5 天**（重构是大头）

**完成信号**
- 能从主 agent 启动一个 sub-agent 完成子任务
- 测试覆盖父子并发不互相污染

---

### Block 2.2 · MCP 集成（🟠 推荐做）

**问题陈述**  
当前工具都是本地 Python 函数。MCP（Model Context Protocol，Anthropic 2024 开源）允许你接入**任何实现了 MCP 协议的外部工具服务器**（数据库、浏览器、Slack、GitHub 等）。生态已经很丰富。

**业界标准**

MCP 规范：https://modelcontextprotocol.io/  
Anthropic 官方 SDK：`mcp` Python 包

```python
from mcp import ClientSession, StdioServerParameters

async with ClientSession(StdioServerParameters(...)) as session:
    tools = await session.list_tools()
    # 把这些 tools 转换成你的 tool_registry 格式注册
    for mcp_tool in tools:
        register_tool(name=mcp_tool.name, ...)(make_mcp_proxy(session, mcp_tool))
```

**突破性思路**
- **动态 MCP 发现**：agent 运行时根据任务需求动态连接 MCP server（比如遇到数据库查询时才连 postgres MCP）
- **MCP Registry**：本地维护一个 MCP server 目录，带描述，让 agent 自己选用哪个
- **MCP-as-tools-as-agents**：把 MCP server 本身包装成一个 sub-agent。结合 2.1

**代码落点**
- `agent/mcp_bridge.py`：MCP 客户端 + 工具注册桥接
- `tool_registry.py`：支持 async 工具（MCP 是 async）
- `tool_executor.py::execute_tool`：异步路径
- 工作量：**2-3 天**

**完成信号**
- 能连上至少一个开源 MCP server（推荐 filesystem 或 fetch），模型能自然调用

---

### Block 2.3 · 工具并行执行（🟡 可选做）

**问题陈述**  
模型一次返回多个 tool_use（read 3 个不同文件），现在是**串行**执行。独立的工具应该并行。

**业界标准**
- OpenAI tool_calls 自带 parallel flag
- Anthropic 天然支持一次返回多 tool_use，客户端应并行执行

**本项目改造**：
```python
# 用 asyncio.gather 或 concurrent.futures
import asyncio

async def execute_parallel(tool_use_blocks):
    tasks = [execute_tool_async(b) for b in tool_use_blocks]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return results
```

**突破性思路**
- **依赖分析**：如果 tool B 的 input 引用了 tool A 的 output，自动识别依赖并串行；否则并行。
- **Cost-aware 并行**：并行会同时开 N 个工具，某些工具花钱（如 Claude API）。带 budget 控制。

**代码落点**
- `tool_executor.py`：async 版本
- `response_handlers.py::handle_tool_use_response`：async 循环
- 工作量：**1-2 天**

---

### Block 2.4 · 多模型路由（🟡 可选做）

**问题陈述**  
当前全程用 `MODEL_NAME` 一个模型。规划可以用 haiku，执行用 sonnet，review 用 opus——成本/质量动态权衡。

**业界标准**
- aider 的 `--weak-model` / `--strong-model` 双模型设计
- LiteLLM 跨 provider 路由

**突破性思路**
- **Learned routing**：根据任务历史 embedding 自动选模型。有点研究性质。
- **Cascade**：先 haiku，回答不确定再 sonnet，再不够再 opus。

**代码落点**
- `config.py`：`MODELS = {"planner": "haiku", "executor": "sonnet", "reviewer": "opus"}`
- 各调用点选不同模型
- 工作量：**半天**

---

## 阶段 3：记忆与上下文演进

**目标**：从"单 session 会忘"到"跨 session 有人格 + 长期学习"。  
**前置**：阶段 2 的 2.1（audit 层）。

### Block 3.1 · 长期记忆提取（🟠 推荐做）

**问题陈述**  
当前 `state.memory.long_term_notes` 是空 list，`extract_memories_from_session` 是 stub。每次新 session 从零开始，agent 不知道你喜欢什么、上次卡在哪、用什么工具。

**业界标准**

| 方案 | 原理 |
|---|---|
| **MemGPT**（letta.ai） | 虚拟内存分层：archival（向量）+ recall（SQL）+ core（prompt 注入） |
| **OpenAI "Memory" 功能** | 服务端维护，用户可见可删 |
| **Claude "Memory" (在 api)** | 关键事实手动/自动沉淀到 `CLAUDE.md` 或 memory 系统 |
| **LlamaIndex** | `SummaryIndex`、`VectorStoreIndex` 跨 session |

**MVP**：session 退出时调 LLM 提取 3-5 条关键事实，追加到 `long_term_notes`：

```python
def extract_memories_from_session(messages, client, model):
    prompt = "从这次对话提取 3-5 条值得长期记住的事实（用户偏好、未完成的问题、重要决定）..."
    response = client.messages.create(model=model, messages=[...])
    new_notes = parse(response)
    existing = load_notes()
    # 去重、合并
    save(existing + new_notes)
```

**突破性思路**
- **Agentic memory curation**：让 agent 自己决定什么该记、什么该忘。MemGPT 的思路。
- **Episodic vs semantic memory**：区分"这件事"（episodic）和"这类事的规律"（semantic）。心理学经典分类。
- **Memory contradiction resolution**：新信息和旧记忆冲突时，agent 主动问用户 clarify。

**代码落点**
- `memory.py::extract_memories_from_session` 从 stub 实现
- `memory.py::build_memory_section` 从固定字符串改成读 long_term_notes
- 工作量：**1-2 天**

---

### Block 3.2 · 向量检索（🟡 可选做）

**问题陈述**  
历史长了之后，"全部注入 prompt"不现实。按需检索相关历史更好。

**业界标准**
- `chromadb`、`qdrant`、`sqlite-vss`（SQLite 向量扩展，最轻量）
- embedding 模型：`voyage-3`、`text-embedding-3-small`

**突破性思路**
- **Task-conditioned retrieval**：不是 "相似" 检索，是 "对当前 task 有用" 检索。需要学习一个 utility function
- **Hierarchical retrieval**：先检索 working summary，再按需下钻到 raw messages

**代码落点**
- 新建 `agent/vector_memory.py`
- 依赖：`chromadb` + embedding API
- 工作量：**3-5 天**（依赖工具链复杂）

---

### Block 3.3 · 用户偏好自学习（🟡 研究性）

**问题陈述**  
用户说一次"请用简短的回复"，agent 应该记住并在后续遵守。当前没有机制。

**业界标准**
- 现阶段都是 prompt engineering + memory section
- 学术界 RLHF、DPO 在做这件事但门槛高

**突破性思路**
- **In-context preference learning**：从 history 里抽出所有"用户给了反馈"的时刻，构建 preference pair，注入 system prompt
- **Fine-tuning 专属 adapter**：用户本地数据做 LoRA 微调（现阶段闭源模型不支持，但 Anthropic 有 "Claude Custom" 方向）

---

## 阶段 4：交互与产品化

**目标**：让 agent 从"能工作"到"好用"。

### Block 4.1 · Review / Self-critique Loop（🟠 推荐做）

**问题陈述**  
`state.runtime.review_enabled` 字段已定义，`agent/review.py` 已存在，但主循环没接。Self-critique 是 agent 质量提升的经典手段。

**业界标准**
- **Reflexion** (Shinn et al. 2023)：agent 完成任务后反思，错误类型写入 memory
- **CRITIC** (Gou et al. 2023)：用外部工具验证 LLM 输出
- **aider --auto-test**：每次改代码后跑测试，失败就反馈给 model

**本项目接入**：
```python
# end_turn 且步骤完成后
if state.runtime.review_enabled and is_current_step_completed(...):
    review_result = run_review(state, client, model)
    if review_result.needs_retry:
        # 不推进步骤，喂给模型"审查意见"重新尝试
        messages.append({"role": "user", "content": f"审查意见：{review_result.feedback}"})
        continue
```

**突破性思路**
- **Multi-agent debate**：让 executor 和 reviewer 是不同 agent（甚至不同模型），辩论到一致
- **Cost-aware review**：只对高风险步骤（edit、run_command）启用 review

**代码落点**
- `agent/review.py` 完善（现有是 stub）
- `response_handlers.py::handle_end_turn_response` 接入
- 工作量：**2-3 天**

---

### Block 4.2 · Budget & 阈值（🟡 可选做）

**问题陈述**  
长任务可能花飞。给 agent 一个 budget，超了自动停。

**实现**
```python
# 在 _call_model 之前
if state.task.cost_usd > state.runtime.budget_usd:
    return "已超预算，任务终止"
```

---

### Block 4.3 · 多会话并发（🟡 可选做）

**问题陈述**  
当前单进程单会话。多个用户 / 多个 task 并发需要 session isolation。

**前置**：2.1 的 state 参数化重构。

---

### Block 4.4 · CLI 多行输入（🔴 必做）

> **状态（2026-04-26）：✅ 已完成**

**问题陈述**

`main.py` 用 `input()` 读取用户输入，只能读一行。终端粘贴多行（含 `\n`）时，`input()` 只到第一个 `\n` 就返回，剩下的留在 stdin 缓冲。**结果**：用户一段长回复（含多个字段）被切成多次 `chat()` 调用，每次模型只看到一段——这恰好是 `awaiting_user_input` 场景下"模型反复追问已经回答过的字段"的根因（武汉旅游规划事故的次要根因）。

**为什么这是架构问题不只是 UX**

`step_input` 控制事件设计的前提是"用户一次回复 = 一个原子 user_input"。如果 input 在终端层就被切碎，`handle_user_input_step` 收到的永远是片段，下一轮模型上下文里只有片段——破坏了 `request_user_input → 用户答复 → 完整信息回到下一轮 step` 这条核心链路。即使 1.5 兜底防住了死循环，也保护不了 step_input 的语义完整性。

**业界标准**

| 方案 | 触发方式 |
|---|---|
| Python REPL `\` 续行 | 行末 `\` 转义换行 |
| ipython `%paste` magic | 粘贴特定标记 + 关键字提交 |
| Claude Code | 三引号围栏 / `Esc + Enter` 换行 / 粘贴自动识别 |
| aider | 默认单行；`{` `}` 围栏支持多行 |
| shell heredoc | `<<EOF ... EOF` |

本项目走"显式协议 + 围栏"双通道：

**实际落地**

```python
# main.py
def read_user_input(prompt="你: ", *, reader=input, writer=print) -> str | None:
    first = reader(prompt)
    stripped = first.strip()
    if stripped == "/multi":
        return _collect_multiline(... done="/done", cancel="/cancel" ...)
    if stripped == "```":
        return _collect_multiline(... done="```", cancel=None ...)
    return first       # 单行原样返回（与历史行为一致）
```

支持：
- 普通单行（保留原行为）
- `/multi` + 多行 + `/done` 提交（或 `/cancel` 返回 None 让主循环跳过本轮，不调 chat）
- 三引号围栏粘贴（再次 ``` 结束；无 cancel 路径，需要中断走 Ctrl+C）
- `EOFError` 视作 done（stdin 关闭时不丢已收集的数据）

`reader` / `writer` 通过参数注入，单元测试可替换 `input` / `print` 喂预录序列——**输入逻辑变成可测**，不再依赖终端。

**突破性思路**

- 自动检测粘贴：终端粘贴时多行连贯到达，没有提示符切换。可以加一个简单的"两行间隔 < 50ms 就视为粘贴"启发式
- 自动语法补全：用户输入 `{` 或 `(` 自动进入多行直到配对
- bracketed-paste 终端模式：现代终端支持 `\e[200~` / `\e[201~` 标记区分粘贴和键入，不需要显式触发

**代码落点**

- `main.py`：抽 `read_user_input` + `_collect_multiline`；`MULTI_START / MULTI_DONE / MULTI_CANCEL / PASTE_FENCE` 模块常量；`main_loop` 改用注入式 reader
- `tests/test_main_input.py`（新）：8 条单元测试覆盖单行 / `/multi` + `/done` / `/cancel` / 围栏 / EOF 鲁棒性 / 现有 slash 命令不被新协议拦截
- 工作量（实际）：**半天**

**剩余隐患**

- Ctrl+C 在围栏模式下会被主循环 `KeyboardInterrupt` 分支捕获（双击退出 / checkpoint 处理）。多数情况下合理；想"取消围栏"只能输 ``` 让函数返回（内容为空）后主循环空输入过滤跳过
- 没做"自动检测粘贴"——保持协议显式，避免误判
- 终端 bracketed-paste 模式没接入；如果用户终端不支持 `/multi`/``` 协议（比如脚本管道），仍是单行行为

---

## 阶段 5：突破性探索（研究级）

**说明**：这些 block **风险高、回报不确定**。适合你已经做到 Tier 4 之后，想找"不一样"的方向。

### Block 5.1 · State Machine Formal Spec（研究级）

写一份 `task.status` 状态机的**形式化规范**（TLA+、Alloy 或 Python 自造）。跑 model checker 自动发现非法转换。

**为什么有趣**：Agent 领域没人做这个。你会成为"用形式化方法验证 agent 行为"的早期实践者。

### Block 5.2 · Learned Tool Selection（研究级）

当前 tool 选择靠模型 prompt。能不能训练一个 small model，根据 task description 自动预测"最可能用到哪些 tool"，只把这些 tool 放进 tools 列表？节省 token + 提高精度。

**为什么有趣**：每次都发 100 个 tool 定义是浪费。工具越多浪费越大。

### Block 5.3 · Protocol Extension（研究级）

Anthropic 协议里 tool_use / tool_result 是线性的。能不能扩展成 **DAG** 形状？比如 tool 可以声明"我需要 tool A 的 output 才能执行"，客户端自动并行无依赖的、串行有依赖的。

**为什么有趣**：MCP 本身可能会走这个方向，你可以提前实验。

### Block 5.4 · Self-Modifying Agent（高风险）

让 agent 能修改自己的代码（在沙箱里）、跑测试、验证改动没破坏 loop、再 commit。**安全上风险极高**，但学术界 (Self-Debug, CodeAct) 在做。

**建议**：只在完全隔离的环境做。

---

## 附录 A · 推荐执行顺序（按月规划）

假设每月 20-30 小时业余时间：

| 月 | 工作 | 实际进度 |
|---|---|---|
| **第 1 个月** | 0.1 测试 + 0.2 类型 + 0.3 caching + 0.4 cost | 0.1 ✅（持续扩展至 ~120 tests / 4 xfail，tests/ 已正式入仓）· 0.2/0.3/0.4 未动 |
| **第 2 个月** | 0.5 observability（轻量版）+ 1.1 步骤协议化 + 1.2 history 层 | **1.1 ✅**（2026-04-25 步骤协议化，落地比原方案更彻底）· **1.1 延伸 ✅**（2026-04-26 `request_user_input` 元工具）· **1.5 ✅**（2026-04-26 loop guard / runtime 兜底，双层兜底 + 终极安全阀）· **4.4 ✅**（2026-04-26 CLI 多行输入）· 1.2 / 0.5 未动 |
| **第 3 个月** | 2.1 sub-agent 重构 + 基础 sub-agent 工作 | — |
| **第 4 个月** | 2.2 MCP 接入 | — |
| **第 5 个月** | 3.1 长期记忆 + 4.1 review loop | — |
| **第 6 个月 及以后** | 按兴趣选 3.2/3.3/阶段 5 | — |

**第 2 个月小结**：超出原计划——除了规划好的 1.1 步骤协议化，还顺手补完了元工具协议的第二个用途（`request_user_input`）和配套 runtime 兜底（1.5），以及 CLI 多行输入（4.4）这条链路。**评估**：关键死循环场景已补兜底（启发式 + 计数 + MAX_LOOP 三层），但**不是"主循环完全可靠"**——4 个 xfail 仍代表已识别但未消化的状态机边界（plan_feedback goal 累加、awaiting_step 时换话题误判 feedback、并行 tool_use 顺序、模型忘调元工具卡死）。后续仍需逐个消化 + 真实场景多跑。

**目前该优先挑什么**：

- **0.3 prompt caching** 仍是 ROI 最高的单点改造（1-2 小时改动、长任务账单下降 50%+），优先做
- **0.4 cost 追踪**：紧跟 0.3，没度量就无法验证缓存生效
- **新候选 · context debug dump / 最终 messages 可观测性**：调试 `awaiting_user_input` / 双层兜底场景时，把"最终送给模型的 messages"完整 dump 是高价值低成本动作。可以在 `_call_model` 前加一个 `--debug` 路径或 dump 到独立 jsonl
- **新候选 · Runtime 命名规范落地**：后续新增 ModelOutputResolution / transition spec 时，统一使用 `STATE_` / `EVENT_` / `guard_` / `action_` / `target_state` / `awaiting_kind`，避免 `kind` / `type` / `source` 混用。第一阶段只写规范，不批量 rename 旧代码；ModelOutputResolution 新代码必须按该规范写；等 ModelOutputResolution 稳定后，再考虑小步 rename：`InputResolution.kind -> resolution_kind`，`pending_user_input_request.source` 或新增字段 -> `awaiting_kind`；不做全仓一次性 rename
- **新候选 · checkpoint save ownership 梳理**：现在 `advance_current_step_if_needed` 内部会保存，部分 transition / handler 外层也会保存。行为上可接受，但 ownership 不够清晰，后续应明确到底由 step runtime 还是 transition 层负责落盘，减少重复保存和日志噪声
- **新候选 · pending_user_input_request.source**：当前 `runtime_user_input_answer` 统一覆盖 `request_user_input`、`fallback_question`、`no_progress`。下一步可给 pending 加轻量 `source` 字段，只增强可观测性，不改变状态转移
- **新候选 · 用户答复 strip / 原文保留策略**：CLI 路径会先 strip，但直接调用 `chat()` 时 InputResolution 保留原文。后续需要明确 runtime 层是统一 strip，还是保留原始 answer 以避免丢多行/格式信息
- **新候选 · 清理 dead field**：~~`state.task.consecutive_rejections` 一直是 dead code（见 §11 / xfail），可以删~~ ✅ 已在 P3 清理中删除；`effective_review_request` 同理待清理
- **新候选 · 消化 xfail 中的状态机边界**：4 个 xfail 都是"已识别但暂不修"的设计债，值得逐个挑出来做
- 其余 0.2 类型、1.2 history、0.5 observability 属于"加分但非阻塞"

**Sub-agent（2.1）在此之前仍不建议动**——它要求 `state` 从模块级全局改成参数传递，改动面大、测试成本高；先把基建（caching / cost / debug dump / xfail）和 runtime 兜底（已完成 1.5）收紧，再考虑跨 agent 隔离。

---

## 附录 B · 判断一个 block 做不做的 5 条标准

每开一个 block 前，用这 5 条自问：

1. **当前是不是真的痛？**（有没有实际 bug / 浪费 / 困扰？还是"觉得该做"）
2. **不做会不会阻塞后续 block？**（依赖关系）
3. **投入产出比？**（工作量 vs 收益）
4. **业界有没有成熟方案？**（不要重发明轮子，除非学习目的）
5. **做完之后能不能自己看见差别？**（有没有度量）

5 条里**至少 3 条 yes** 才开干。避免"功能堆砌综合症"。

---

## 附录 C · 常见反模式（要避免）

| 反模式 | 典型表现 | 为什么不好 |
|---|---|---|
| **架构先行** | 没跑 agent 就开始设计"分布式 agent 集群" | 提前设计反而锁死后续空间 |
| **工具堆砌** | 注册 50 个工具，每个都只是 wrapper | 工具越多 token 越贵，模型选错概率越高 |
| **抽象癌** | 每个小功能都抽一层 interface | 小项目用不上，大项目用上了也该延后 |
| **数据不可见** | 加了 metric 但没 dashboard，加了 log 但从不看 | 度量等于无 |
| **复制业界代码** | 见到 aider / LangChain 有什么就抄 | 他们的约束和你不同 |
| **忽略工程配套** | 一路加功能不写测试 | 技术债会指数膨胀 |

---

## 最后：这份文档怎么用

- **不是 todo list**：不要 "今天要完成 Block 0.1"。是 "下一步要开始探索 Block 0.1"。
- **不是蓝图，是地图**：地图告诉你有哪些路，走哪条是你自己决定的。
- **会过时**：6 个月后 Anthropic 可能发布新 feature（比如官方 memory），这份文档里的一些 block 就不需要做。届时删 / 改它。
- **和你一起演进**：每完成一个 block，回来改这份文档，记下"做完这件事我发现 XYZ"。这份文档的最终形态是**你的 agent 设计笔记**。

---

**One last thing**：你 Memory 里写的 "长周期提升" —— 这份文档就是那个长周期的骨架。不要一口气全做。不要因为看着列表长就焦虑。每个月做 1-2 块，半年后你的 agent 会在 Tier 4；一年后可能开始触及 Tier 5 的某些方面。

不用和别人比。和**半年前的自己**比。
