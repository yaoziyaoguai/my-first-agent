# Runtime v0.1 毕业契约 + xfail 归类清单

> **本文件目的**：给 v0.1「最小 Agent Runtime 跑起来」一份**单页可引用的毕业契约**，把当前测试与 xfail 全部按版本归类，避免任何"我觉得这块还差一点"的工作误入 v0.1。
>
> **它是 ROADMAP 的"测试 / xfail 视图"投影**，不替代 `docs/ROADMAP.md`；任何冲突以 ROADMAP 为准。
>
> **写给未来读这份代码的人**：v0.1 只追求"能跑"，不追求"优雅"。读完这一页，你应该能在 30 秒内判断"我现在想做的这件事，是不是 v0.1 该做的"。

---

## 1. v0.1 阶段目标（一句话）

让用户在 simple CLI 里输入一句自然语言任务，Agent 能完成下面这条最小回路：

```
plan → 用户确认计划 → 工具调用（必要时确认）→ 输出结果 → checkpoint 持久化
```

## 2. 毕业标准（5 条 + 1 条契约，验"能跑"，与 ROADMAP 同步）

1. simple CLI 主循环可以端到端跑通"读 README、写中文总结到 summary.md"这类任务（手动 smoke 已通过，见 `docs/V0_1_GRADUATION_REPORT.md`）
2. 至少 3 类工具可用：read（file_ops/edit）、write（write）、shell（shell）
3. 状态机至少能区分：`idle / planning / running / awaiting_plan_confirmation / awaiting_tool_confirmation / done / failed / cancelled` —— **存在即可，不要求文档化**
4. checkpoint 写入 + 加载 roundtrip 测试通过 —— **不要求中断恢复 / 损坏态自愈 / 跨版本兼容**
5. `pytest` 一键跑过无 RED；任何 xfail 必须明确归到 v0.2 / v0.3 / v1.0
6. **最小 CLI/TUI 输出契约已冻结**（B2，见 `docs/CLI_OUTPUT_CONTRACT.md`）

## 3. 非目标（v0.1 明确不做，每条配"为什么"）

| 不做 | 为什么不在 v0.1 |
|---|---|
| 工具体系工程化（接口规范 / 权限 / 错误恢复 / 结果压缩 / 选择质量 / 文档） | "能跑"≠"工程化"，全部归 **v0.2 主要工作量** |
| checkpoint 中断恢复 / 损坏态自愈 / 跨版本兼容 | v0.1 只验 roundtrip，恢复语义归 **v0.2** |
| 状态机正式化（转移图 / spec / 不变量文档） | v0.1 状态"存在即可"；正式化归 **v0.2** |
| InputIntent / RuntimeEvent / DisplayEvent 边界治理 | 现状能跑，治理归 **v0.2** |
| awaiting_feedback_intent 后续扩展 / 复杂 topic switch / slash command 恢复 | P1 探索性实现已落地不回退，但**不计入 v0.1**；归 **v0.2 输入语义治理** |
| LLM 二次意图分类 | 红线明确禁止；仅 **v1.0** 探索阶段评估 |
| generation cancel_token / 流中断 | 设计债已被 xfail 记录；归 **v0.2** cancel 生命周期 + **v0.3** TUI Esc 集成 |
| 错误恢复 / 重试 / loop guard / no_progress 检测 | 归 **v0.2** |
| 基础安全权限（path 白名单 / shell 黑名单） | 归 **v0.2**；正式围栏归 **v1.0** |
| 完整 Textual backend / persistent shell / 状态面板 UI 实现 | 归 **v0.2 基础 TUI/CLI UX 实现** |
| TUI 多面板 / 快捷键 / Esc cancel / paste burst / Textual 转默认 | 归 **v0.3 高级 TUI** |
| Skill 化 / install_skill / update_skill / skill 文档规范 | `agent/skills/` 是雏形；归 **v0.3** |
| Observer / eval pipeline / cost 追踪 / 性能基准 | 现有 runtime_observer 事件保留，扩展归 **v0.3** |
| Sub-agent / 多 Agent 协作 / 插件化 / 长期记忆 / MCP / 多模型路由 | 全部归 **v1.0** |

## 4. 停止规则

- 5 条毕业标准 + B1 / B2 / B3 全部 ✅ → **立即冻结 v0.1**，新功能必须先归类到 v0.2 / v0.3 / v1.0 backlog 才能动手
- v0.1 阶段**禁止**：新增 awaiting 子状态、新增 RuntimeEvent kind、新工具、新 skill、新输入后端
- v0.1 阶段**只允许**：修 bug、补缺失文档、补缺失基础测试、写 v0.1 冻结契约
- 任何"我觉得这块还差一点"的改动，先回答："这属于 v0.1 毕业标准的哪一条？" 答不出 → 推迟

---

## 5. 测试分类总表

> 分档依据：是否在保护 §1 的最小回路。所有 PASS 测试都至少属于 v0.1 契约护栏；表格关心的是**测试文件主旨**和**含 xfail 的归属**。

### 5.1 v0.1 必须保护（最小 Agent Runtime 契约护栏）

| 测试文件 | 守护点 |
|---|---|
| `tests/test_api_projection.py` | Anthropic 协议投影（Kimi 死循环回归根因） |
| `tests/test_tool_pairing.py` | tool_use ↔ tool_result 配对契约 |
| `tests/test_context_builder.py` | planning / execution 消息构建 |
| `tests/test_memory_and_tools.py` | history 压缩 + 工具注册基础 |
| `tests/test_meta_tool.py` | `mark_step_complete` 元工具 |
| `tests/test_main_loop.py` | 主循环集成 |
| `tests/test_main_input.py` | `read_user_input` 多行输入协议 |
| `tests/test_confirmation_flow.py` | plan / step / tool 确认流 |
| `tests/test_completion_handoff.py` | 完成 handoff 诊断 |
| `tests/test_checkpoint_roundtrip.py` | checkpoint 写入 + 加载 roundtrip |
| `tests/test_state_invariants.py` | `state.py` 不变量 |
| `tests/test_semantics.py` | planner / task_runtime / conversation_events 行为 |
| `tests/test_input_backends_simple.py` | simple backend 窄测试 |
| `tests/test_user_input.py` | `UserInputEvent` / `UserInputEnvelope` 语义 |
| `tests/test_user_replied_transition.py` | `awaiting_user_input + USER_REPLIED` transition |
| `tests/test_input_intents.py` | InputIntent 输入边界回归 |
| `tests/test_input_resolution.py` | InputResolution 架构语义 |
| `tests/test_model_output_resolution.py` | 模型输出解析只读事件 |
| `tests/test_runtime_observability.py` | Runtime 可观测性回归（v0.1 已有事件不回退） |
| `tests/test_runtime_observer.py` | observer 日志格式 |
| `tests/test_long_running.py` | 长程 10+ 轮对话不崩 |
| `tests/test_complex_scenarios.py` | 复杂但合法用户路径 |
| `tests/test_bug_hunting.py` | 进阶 bug 挖掘集成测试 |
| `tests/test_hardcore_scenarios.py` | 硬核用户路径（含已知"代码 bug"的注释，**未挂 xfail marker**，当前都 PASS） |

### 5.2 v0.2 backlog 视角的"提前写好的 spec"

| 测试文件 | 备注 |
|---|---|
| `tests/test_feedback_intent_flow.py` | P1 awaiting_feedback_intent 已落地（commit `d6a5aed`+`58c6fcb`），保留不回退；测试本身全 PASS，但归 **v0.2 输入语义治理** 范畴，**v0.1 不再追加 P2/P3** |
| `tests/test_hardcore_round2.py` | 含 1 条 v0.2 xfail（topic switch），其余 PASS 用例属 v0.1 契约护栏 |
| `tests/test_real_cli_regressions.py` | 含 1 条 v0.3 xfail（paste burst），其余 PASS 用例属 v0.1 契约护栏 |

### 5.3 v0.2 / v0.3 可选依赖

| 测试文件 | 备注 |
|---|---|
| `tests/test_input_backends_textual.py` | 整文件依赖 `textual`；缺失依赖时通过 `pytest.xfail()` 条件跳过——属于"可选依赖缺失"而非契约债。其内的 `test_textual_shell_escape_can_cancel_running_generation` 是**严格 xfail**，归 **v0.2 cancel 生命周期 + v0.3 TUI Esc 集成** |

---

## 6. xfail 归类表（B1 核心交付物）

> 当前 `pytest -q` 报告 **3 个 xfail**（不计可选依赖缺失时整文件跳过的 `test_input_backends_textual.py`）。

| # | 测试 | 当前归属 | 解锁前置条件（满足才允许移除 xfail） |
|---|---|---|---|
| 1 | `tests/test_hardcore_round2.py::test_user_switches_topic_mid_task` | **v0.2 输入语义治理** | 引入 `awaiting_feedback_intent` 之上的成熟 topic-switch 信号源：要么显式控制输入（如 `/newtask` 重新设计），要么 LLM 二次分类配合 `awaiting_topic_switch_confirmation`。**禁止靠浅层启发式回退**（c252695 的 imperative-prefix 已在 `205c4cf` 回退）。**禁止**改写测试为两步交互来"绕过" |
| 2 | `tests/test_input_backends_textual.py::test_textual_shell_escape_can_cancel_running_generation` | **v0.2 cancel 生命周期 + v0.3 TUI Esc 集成** | 先在 `agent/core.py` chat() 引入 `cancel_token`、模型 stream abort、`generation.cancelled` RuntimeEvent（v0.2）；再在 Textual backend 把 Esc 从"取消草稿"升级为"取消生成"（v0.3）。**禁止**把 RuntimeEvent / InputIntent / checkpoint / TaskState 混成临时补丁 |
| 3 | `tests/test_real_cli_regressions.py::test_plain_cli_pasted_numbered_multiline_should_be_one_user_intent` | **v0.3 高级 TUI（paste burst）** | 输入层引入 `prompt_toolkit` / bracketed paste / `UserInputEnvelope` paste burst 包装，把一次粘贴的多行编号列表当作同一个 user intent。**禁止**通过强制用户使用 `/multi` 之类命令绕过 |

> **删除任一 xfail 的判据**：上表"解锁前置条件"全部满足，且**对应版本**已正式立项（不是 v0.1 阶段顺手做）。

---

## 7. 学习型说明：为什么这些不是 v0.1 blocking

写给"觉得 v0.1 还差一截"的未来自己。每条都对应一个真实的"想顺手做"的诱惑：

### 7.1 为什么 P1 feedback intent flow 不是 v0.1 blocking

P1 awaiting_feedback_intent（commit `d6a5aed`+`58c6fcb`）解决的是"plan 出来后用户反馈到底是改 plan 还是开新任务"——这是**输入语义**问题，不是"能不能跑"问题。v0.1 已经有最朴素的"plan_feedback 触发 planner 重算"语义，**够跑**。把 P1 当 v0.1 blocking 会陷入"再加一个 awaiting 子状态、再加一个 RuntimeEvent kind"的扩张惯性，违反 §4 停止规则中的"v0.1 禁止新增 awaiting 子状态"。归 **v0.2 输入语义治理**。

### 7.2 为什么"复杂 topic switch"不是 v0.1 blocking

见 xfail #1。topic switch 的**任何**正确解都需要新的输入信号源（slash 协议 / LLM 二次分类 / 显式 RuntimeEvent 用户确认流），都属于"新增能力"而非"修 bug"。v0.1 的最小回路里，用户只要会回答 y/n + plan_feedback 文本就能跑完任务，**不需要**话题切换能力。

### 7.3 为什么 slash command 不是 v0.1 blocking

slash command 在 commit `205c4cf` 已**整体下线**，因为它本质上是一种"用户必须学会 `/foo` 协议才能用"的产品妥协，与 v0.1 "最简版本能跑"目标背道而驰。任何 slash 类需求都先归 **v0.2 输入语义治理**重新设计，不在 v0.1 阶段恢复字符串协议。

### 7.4 为什么 Textual backend 不是 v0.1 blocking

Textual backend 已经在仓库里（`tests/test_input_backends_textual.py`），但**完整实现**（persistent shell / 状态面板 / 多面板 / Esc 取消生成 / paste burst）会显著扩张 RuntimeEvent / DisplayEvent 边界，违反 §4 停止规则。v0.1 只要 simple CLI 跑得动，Textual 整段归 **v0.2 基础 TUI/CLI UX 实现** + **v0.3 高级 TUI**。

### 7.5 为什么 Skill / sub-agent 不是 v0.1 blocking

`agent/skills/` 文件齐了不代表 skill 体系成熟——`evil-skill` 测试目录的存在恰好说明 safety 还在原型期。Skill 正式化归 **v0.3**。Sub-agent / 多 Agent 协作**从未真正实现**，归 **v1.0**。在 v0.1 阶段动这两块是典型的"被高级能力分散注意力"。

### 7.6 为什么 observer 扩展不是 v0.1 blocking

现有 `runtime_observer` 已经能产出可读日志事件，足以让 v0.1 的最小回路被观察。eval pipeline / cost 追踪 / 性能基准 / 多面板 viewer 全部属于"工程化扩张"，归 **v0.3 observer/eval**。

### 7.7 为什么 generation cancel 不是 v0.1 blocking

cancel 涉及 RuntimeEvent 生命周期 + core 层 `cancel_token` 传递 + 模型 stream abort + UI 层（Textual Esc 或 simple CLI Ctrl-C）联动，**任何一处都是 v0.2 起步级别的设计工作**。v0.1 的最小回路允许"任务跑完才返回控制权"，先能跑再说。

---

## 8. 当前 v0.1 blocking 状态（B1/B2/B3）

| Blocking | 状态 | 说明 |
|---|---|---|
| **B1** 冻结 v0.1 契约 + xfail 归类 | ✅ **本文件** + 3 处 xfail `reason=` 已加版本归属前缀 | 本轮交付 |
| **B2** 冻结最小 CLI/TUI 输出契约 | ✅ 已完成 | 见 `docs/CLI_OUTPUT_CONTRACT.md` + `tests/test_real_cli_regressions.py` 的 B2 护栏 |
| **B3** 真实手动 smoke（需 `ANTHROPIC_API_KEY`） | ✅ 已通过 | 见 `docs/V0_1_GRADUATION_REPORT.md`；README -> `summary.md` 真实 API smoke 已完成 |

> v0.1 是否毕业：**是**。B1 / B2 / B3 已完成；后续工作必须先归入 v0.2 / v0.3 / v1.0。

---

## 9. 这份文档怎么用

1. 任何人想动 `agent/` 代码前，先翻 §3 非目标 + §6 xfail 表 → 在里面 → **推迟**
2. 任何人想"顺手把 xfail 修了" → 必须先满足 §6 对应行的"解锁前置条件" → 否则**推迟**
3. 任何人想新增 awaiting 子状态 / RuntimeEvent kind / 工具 / skill → 违反 §4 → **直接拒**
4. 本文件由 ROADMAP 驱动；ROADMAP 改了，本文件需要同步检视
