# my-first-agent 演进路线图

> **本文件目的**：用阶段目标 + 毕业标准 + 非目标 + 停止规则，把"该做什么、不该做什么、什么时候停"讲清楚。
>
> **不是**：22 个 block 的待办清单（旧版结构已归档到 `docs/ROADMAP_LEGACY.md`）。
>
> **不是**：架构解读（看 `docs/ARCHITECTURE.md`）。

---

## TL;DR

| 版本 | 主题 | 一句话 |
|---|---|---|
| **v0.1** | 最小 Agent Runtime 跑起来 | 只验"能跑"，不验"优雅"。当前阶段。 |
| **v0.2** | 把 v0.1 粗糙能力工程化 | Runtime 状态机、输入语义、工具体系、checkpoint 恢复、错误恢复、基础权限、**基础 TUI/CLI UX 实现**（Textual backend 完整实现 + 状态面板 + 确认流 UI）。|
| v0.3 | Skill 化 + 能力注册 + observer/eval + **高级 TUI** | Skill 子系统正式化、工具/skill 文档规范、observer/eval 增强、多面板/timeline/event viewer/Esc cancel/paste burst 等高级 UX。 |
| v1.0 | 稳定可扩展的学习型 Agent 框架 | sub-agent / 多 Agent 协作 / 插件化 / 长期记忆 / 正式安全围栏 / 性能 SLA。 |

| **当前阶段：v0.1 已毕业；下一阶段进入 v0.2 planning / engineering**（v0.1 已冻结最小 CLI/TUI 输出契约，只冻结契约不实现完整 Textual TUI）。
**v0.1 结果**：最简版本 simple CLI 已跑通端到端 README -> `summary.md` 真实 smoke，CLI 输出可读到能看清 Agent 在做什么。后续不要把 slash command / 复杂 topic switch / LLM 意图分类 / 完整 Textual TUI / Skill 化 / 安全围栏 / observer 等高级能力回写成 v0.1 已完成。

**全局停止规则**：
- 任何"我觉得这块还差一点"的改动，先回答："这属于当前阶段毕业标准的哪一条？"
- 答不出 → **推迟到对应版本 backlog**，不在当前阶段做。
- v0.1 阶段**禁止**新增 awaiting 子状态 / 新增 RuntimeEvent kind / 新工具 / 新 skill；只允许：修 bug、补缺失文档、补缺失基础测试、写 v0.1 冻结契约。

---

## 当前真实完成度（保守评估）

> ⚠️ **保守口径**：列出的"已具备"只表示"基础链路打通能跑端到端任务"，**不**代表"已工程化、可生产"。任何标注 ✅ 的能力背后都还有大量 v0.2/v0.3 工程化欠账。

| 能力 | 真实完成度 | 备注 |
|---|---|---|
| 基础 Agent Loop | ✅ 相对做得还可以 | `agent/core.py` chat() 主循环 + planner |
| 基础任务编排（plan-step） | ✅ 相对做得还可以 | planner + 主循环 + step 推进 |
| 基础工具注册与调用 | 🟡 仅基础版 | 12 个工具文件 + tool_registry，**接口规范/权限/错误恢复/结果压缩/选择质量/工具测试/工具文档全部缺**，需 v0.2 工程化 |
| 模型消息构建 | 🟡 基础可用 | context_builder + prompt_builder，未做 prompt caching / 上下文压缩 |
| tool_use / tool_result 链路 | ✅ 链路打通 | tool_executor + placeholder + tool_pairing 测试覆盖；结果摘要 / 失败结构化未做 |
| 最小状态流转 | 🟡 跑得起来但混乱 | TaskState + 6+ awaiting 子状态，**未文档化、未画转移图**，需 v0.2 整理 |
| 最小用户确认流 | ✅ 基础够用 | confirm_handlers（plan + tool 确认是 v0.1 范围；step + feedback_intent 是超 v0.1 探索） |
| 基础 checkpoint | 🟡 雏形 | checkpoint.py + roundtrip 测试通过；**中断恢复语义、损坏态自愈、跨版本兼容全未做**，需 v0.2 |
| 核心测试可跑 | ✅ 279 passed / 3 xfailed | 一键 `pytest` 通过，xfail 全部明确归类 |

### "不要高估项"专章

以下能力**不要写成"已完成"**，无论代码里看起来有多少文件：

| 项 | 真实状态 | 归属 |
|---|---|---|
| **Skill 体系** | **非常粗糙，几乎可忽略** | `agent/skills/` 文件齐了（installer/loader/parser/registry/safety），但没有真正成熟的 skill 生命周期、版本管理、安全审查；evil-skill 测试目录恰恰说明 safety 还在原型期 → **v0.3** |
| **Sub-agent / 多 Agent 协作** | **从未真正实现** | 完全没有 → **v1.0** |
| **工具体系成熟度** | 仅基础版 | 工具接口规范 / 权限边界 / 错误恢复 / 结果压缩 / 选择质量 / 工具测试 / 工具文档**全部缺** → **v0.2 主要工作量** |
| **安全围栏 / 沙箱 / 权限模型** | 几乎没有 | `agent/security.py` / `agent/skills/safety.py` 都是雏形 → 基础权限 v0.2，正式围栏 v1.0 |
| **Observer / eval / cost 追踪** | 仅有 runtime_observer 的若干日志事件 | 没有评测 pipeline、没有 cost 计算、没有性能基准 → **v0.3** |
| **TUI / CLI UX** | **拆成三层** | **v0.1**：仅冻结**最小 CLI 输出契约**（文档 + 现有输出对齐契约，**不实现完整 TUI**）。**v0.2 基础 TUI/CLI UX 实现**：Textual backend 完整实现、persistent shell、基础状态面板、RuntimeEvent 友好渲染、确认流 UI、pending 提示、checkpoint resume 提示、基础 observer 入口。**v0.3 高级 TUI**：多面板、快捷键、Esc/generation cancellation、stream abort、timeline/event viewer、复杂调试器、paste burst |
| **复杂 topic switch / awaiting_feedback_intent** | **探索性实现 / 已暂停** | 已有 commit 落地（保留不回退），但**不计入 v0.1 完成度** → **v0.2 输入语义治理** |
| **generation cancel_token / 流中断** | 完全没有 | xfail 已记录 → **v0.2** |
| **LLM 二次意图分类** | 完全没有，红线明确禁止 | 仅 v1.0 探索阶段评估 |

---

## v0.1 · "最小 Agent Runtime 跑起来"

### 阶段目标

用户在 simple CLI 里输入一句自然语言任务，Agent 能完成下面这条最小回路：

```
plan → 用户确认计划 → 工具调用（必要时确认）→ 输出结果 → checkpoint 持久化
```

### 毕业标准（5 条，验"能跑"）

1. simple CLI 主循环可以端到端跑通"读取 README、写一段中文总结到 summary.md"这类任务（手动 smoke 通过）
2. 至少 3 类工具可用：read（file_ops/edit）、write（write）、shell（shell）
3. 状态机至少能区分：`idle / planning / running / awaiting_plan_confirmation / awaiting_tool_confirmation / done / failed / cancelled` —— **存在即可，不要求文档化**
4. checkpoint 写入 + 加载 roundtrip 测试通过 —— **不要求中断恢复 / 损坏态自愈 / 跨版本兼容**
5. `pytest` 一键跑过无 RED；任何 xfail 必须明确归到 v0.2/v0.3/v1.0
6. **最小 CLI/TUI 输出契约已冻结**（写成文档、被 main / RuntimeEvent / DisplayEvent / runtime_observer 实际遵守）—— 普通 CLI 下不再出现裸 print 把 Runtime 调试和用户操作搞乱的回归

### 非目标（v0.1 明确不做、不扩展）

- ❌ 工具体系工程化（接口规范 / 权限边界 / 错误恢复 / 结果压缩 / 工具选择质量 / 工具文档）→ **v0.2**
- ❌ checkpoint 中断恢复 / 损坏态自愈 / 跨版本兼容 → **v0.2**
- ❌ 状态机正式化（转移图 / 状态文档 / spec / 不变量）→ **v0.2**
- ❌ InputIntent / RuntimeEvent / DisplayEvent 边界治理 → **v0.2**
- ❌ awaiting_feedback_intent 后续扩展、复杂 topic switch、slash command 恢复、LLM 二次意图分类 → **v0.2** 或 **v1.0**
- ❌ 错误恢复 / 重试 / 主循环 loop guard / no_progress 检测 → **v0.2**
- ❌ 基础安全权限（path 白名单 / shell 黑名单）→ **v0.2**
- ❌ Skill 化 / 能力注册 / install_skill / update_skill / 工具 & skill 文档规范 → **v0.3**
- ❌ Observer / eval pipeline / cost 追踪 / runtime observability 扩展 → **v0.3**
- ❌ **完整 Textual backend / persistent shell / 状态面板 UI 实现** → **v0.2 基础 TUI/CLI UX 实现**
- ❌ TUI 多面板 / 快捷键 / Esc cancel / 多行编辑 / paste burst / Textual 转默认 → **v0.3 高级 TUI**

> ⚠️ **v0.1 仍要做**："最小 CLI/TUI **输出契约**" 必须冻结（见 B2），但**只冻结契约，不实现完整 TUI**——契约本身是文档 + 现有 main/RuntimeEvent/DisplayEvent/runtime_observer 的输出边界对齐。Textual backend 完整实现归 v0.2。
- ❌ Sub-agent / 多 Agent 协作 / 插件化 / 长期记忆 / 多模型路由 / MCP / 正式安全围栏 → **v1.0**

### 停止规则

- 5 条毕业标准全部 ✅ 且下面 3 条 blocking 全关闭 → **v0.1 范围已冻结**，新功能必须先归类到 v0.2/v0.3/v1.0 backlog
- v0.1 阶段**禁止**：新增 awaiting 子状态、新增 RuntimeEvent kind、新工具、新 skill、新输入后端
- v0.1 阶段**只允许**：修 bug、补缺失文档、补缺失基础测试、写 v0.1 冻结契约

### v0.1 blocking issue（最多 3 条）

- ✅ **B1 · 写 v0.1 冻结契约 + xfail 归类**
  在本 ROADMAP / ARCHITECTURE 顶部明确列出当前 v0.1 范围内的模块/工具/状态白名单；其余特性（awaiting_feedback_intent、Textual backend、Skill 子系统、runtime_observer 扩展事件等）显式标注"已落地但 v0.1 阶段锁定不再扩展"。
  同时把当前 3 个 xfail 各自打上"属于哪个版本要解决"标签：
  - `test_user_switches_topic_mid_task` → v0.2 输入语义治理
  - `test_textual_shell_escape_can_cancel_running_generation` → v0.2 cancel 生命周期 + v0.3 TUI Esc 集成
  - `test_plain_cli_pasted_numbered_multiline_should_be_one_user_intent` → v0.3 高级 TUI（paste burst）

- ✅ **B2 · 冻结最小 CLI/TUI 输出契约**（**不实现完整 Textual TUI**）
  目标：解决我们最早遇到的痛点——CLI 多行输出混乱、状态不可见、确认流提示不清、tool call/tool result 输出边界不稳定，让用户根本判断不出 Agent 在做什么。
  做的是**契约**，不是**实现**：
  - 写一份 `docs/CLI_OUTPUT_CONTRACT.md`（或合入 ARCHITECTURE 章节），明确普通 CLI 下以下内容的统一渲染规则：
    - RuntimeEvent（assistant.delta / tool.* / display.event / control.message / plan.* / user_input.requested 等）
    - plan 展示
    - current step 提示
    - tool call 与 tool result 的边界（前后分隔、长内容截断策略）
    - `pending_user_input_request` 提示（含 awaiting_kind / question / options）
    - checkpoint resume 提示（启动时显式告诉用户"正在从 checkpoint 恢复"）
    - 错误信息（格式 / 何时打印 stack）
    - 多行输出（缩进 / 分隔规则）
  - 明确"哪些内容**不能裸 print**"、"哪些**必须**通过统一输出边界（RuntimeEvent / `render_runtime_event_for_cli` / DisplayEvent）渲染"
  - 现有 `main.py` / `agent/runtime_observer.py` / `agent/display_events.py` 必须**已经遵守该契约**；任何违反契约的现有 print 列入修正项，修正本身可以放进 v0.1 范围（属于"修 bug + 让现状对齐契约"）
  - 验收：契约文档存在 + B3 一次手动 CLI 运行的输出符合契约（清晰可读、无裸 debug print）

- ✅ **B3 · 真实手动 smoke**
  用 simple CLI 真实跑一次"读 README → 写 summary.md"端到端任务（需 `ANTHROPIC_API_KEY`），验证 v0.1 真的跑得起来 **且** 输出符合 B2 冻结的契约；不行就回头修最小路径，**不**借机扩展任何超 v0.1 能力。

  结果：已通过，见 `docs/V0_1_GRADUATION_REPORT.md`。

### 下一步只允许做什么

- ✅ 进入 v0.2 planning / engineering，先写清 milestone 再实现
- ❌ 不要继续推进 P1 awaiting_feedback_intent
- ❌ 不要实现完整 Textual backend / persistent shell（归 v0.2）
- ❌ 不要扩展 Skill 子系统
- ❌ 不要补 LLM 意图分类 / generation cancel / slash command
- ❌ 不要新增工具 / 新增 awaiting 状态
- ⚠️ **B2 只做契约 + 修对齐契约的 print**，不要借机重写 main.py / 重构 RuntimeEvent 体系

---

## v0.2 backlog · "把 v0.1 粗糙能力工程化"

> 仅列举主题，**不展开**实施细节。等 v0.1 毕业后再细化每一项的目标 / 毕业标准。

- Runtime 状态机整理：转移图、状态文档、不变量 spec
- InputIntent / RuntimeEvent / DisplayEvent 边界治理（含 awaiting_feedback_intent 收口、slash 类需求评估）
- **工具体系优化（v0.2 主要工作量）**：
  - 工具接口规范（schema / 错误返回约定 / 描述规范）
  - 工具结果压缩（长输出截断 / 摘要）
  - 工具选择质量（prompt 优化 / 错用监控）
  - 每个工具的单元测试 + 使用文档
- checkpoint 恢复语义：中断态判定 / 损坏态自愈 / 跨版本兼容策略
- 错误恢复 / 重试 / 主循环 loop guard / no_progress 检测
- 基础安全权限：path 白名单、shell 命令最小审查、工作区根目录约束
- generation cancel_token / 流中断生命周期（**只做生命周期与 RuntimeEvent，不做 TUI Esc 集成**——后者归 v0.3）
- 复杂 topic switch（awaiting_feedback_intent 之上的真正成熟方案）
- **基础 TUI / CLI UX 实现**（在 v0.1 冻结的 CLI 输出契约基础上，做最小可用交互界面，让 Runtime 真正可调试、可理解）：
  - **Textual backend 完整实现 + persistent shell**（v0.1 不做，v0.2 做完整版）
  - 基础状态面板（清晰展示当前 goal / plan / current step / status）
  - RuntimeEvent 可读渲染（在 v0.1 契约之上做更友好的 UI）
  - plan / step / tool / user input 确认流 UI
  - `pending_user_input_request` 状态提示 UI（含 awaiting_kind / question / options）
  - checkpoint resume 提示 UI
  - 基础日志 / observer 可视化入口（最小 viewer，不做多面板 / timeline）
  - 验收口径：simple CLI 与 Textual backend 都可用、都遵守 v0.1 输出契约、Textual 可成为可选默认

---

## v0.3 backlog · "Skill 化 + 能力注册 + observer/eval + 高级 TUI"

- Skill 子系统**正式化**（loader / installer / safety / registry 真正做成熟，evil-skill 测试通过）
- 能力注册 + 工具/skill 文档规范统一
- Observer / eval pipeline / cost 追踪 / 性能基准（在 v0.2 基础 observer 入口上做增强）
- **高级 TUI / CLI**（在 v0.2 基础 UX 之上）：
  - 多面板布局（conversation / plan / events / state / log 分区）
  - 快捷键体系
  - Esc / generation cancellation 与 TUI 集成、stream abort
  - timeline / event viewer / 历史回放
  - 复杂调试器（断点、单步、状态 inspect）
  - persistent shell 完善 / 多行编辑 / paste burst UX
  - Textual backend 转默认

---

## v1.0 backlog · "稳定可扩展的学习型 Agent 框架"

- Sub-agent / 多 Agent 协作（**全新实现**）
- 插件化 / 公开 API
- 长期记忆 / 用户偏好自学习
- **正式**安全围栏 / 沙箱 / 权限模型
- 多模型路由 / MCP 集成
- Formal state machine spec
- Self-critique / self-modify
- 性能 SLA / 稳定性 SLA

---

## 进行中工作的版本归属（避免误以为是 v0.1 工作）

| 进行中工作 | 归属 | 处理方式 |
|---|---|---|
| P1 awaiting_feedback_intent 两步分流 | **探索性实现 / 已暂停** → v0.2 输入语义治理 | commit `d6a5aed` + `58c6fcb` 保留不回退；**不再追加 P2/P3**；hardcore xfail 保留 |
| Textual backend / persistent shell | **拆成三层**：CLI 输出契约冻结 → v0.1 / Textual 完整实现 + 基础 UX → v0.2 / 高级 UX → v0.3 | 保留代码标 experimental；v0.1 阶段不实现完整 Textual，但必须冻结输出契约 |
| Skill 子系统 / install_skill / update_skill | v0.3 Skill 化 | 保留代码；v0.1 不扩展，**不要写成已完成** |
| slash command 历史 / 启发式回退讨论 | v0.2 输入语义治理 | 已下线，v0.1 不再讨论 |
| runtime_observer / observability 事件 | v0.3 observer/eval | 现有事件保留；v0.1 不扩展 |
| security.py / safety.py | 基础权限 v0.2 / 正式围栏 v1.0 | 现状是雏形；v0.1 不扩展 |
| hardcore_round2 LLM 意图分类讨论 | v1.0 探索 | 红线禁止；v0.1/v0.2 都不引入 |
| generation cancel_token / Textual Esc | 拆：cancel 生命周期 → v0.2 / Esc 与 TUI 集成 → v0.3 | xfail 保留 |

---

## 附录 A · 本次重写为何砍掉旧的 22 block 结构

旧 ROADMAP（1262 行 / 6 阶段 × 22 block）问题：
- **没有阶段毕业线** —— 只有"必做/推荐/可选"，没有"v0.1 已完成"的认证
- **抽象层级混乱** —— Block 0.1（集成测试）和 Block 5.4（Self-Modifying Agent）并列在同一推进序列
- **被高级能力分散** —— Skill / Textual / sub-agent / observer 在同一个文档里争注意力，让"最简版本能跑"反而不优先

旧 22 block 归类映射：

| 旧 block | 归到新版本 | 备注 |
|---|---|---|
| 0.1 集成测试 | v0.1 已基本达成 | 269 测试通过 |
| 0.2 类型系统 | v0.2 工程化 | |
| 0.3 Prompt Caching | v0.2 工具体系优化 | |
| 0.4 Cost 追踪 | v0.3 observer/eval | |
| 0.5 可观测性基础 | v0.3 observer/eval | |
| 1.1 步骤完成协议化 | v0.1 已基本达成 | mark_step_complete 已落地 |
| 1.2 history.jsonl 审计层 | v0.3 observer/eval | |
| 1.3 错误恢复与重试 | v0.2 错误恢复 | |
| 1.4 流式 tool_use 处理 | v0.2 工具体系 / v0.3 体验 | |
| 1.5 主循环 loop guard | v0.2 错误恢复 | |
| 2.1 Sub-agent | **v1.0** | 从未实现 |
| 2.2 MCP 集成 | v1.0 | |
| 2.3 工具并行执行 | v0.2 或 v1.0 | |
| 2.4 多模型路由 | v1.0 | |
| 3.1 长期记忆提取 | v1.0 | |
| 3.2 向量检索 | v1.0 | |
| 3.3 用户偏好自学习 | v1.0 | |
| 4.1 Review / Self-critique | v1.0 self-critique | |
| 4.2 Budget & 阈值 | v0.3 observer/eval | |
| 4.3 多会话并发 | v1.0 | |
| 4.4 CLI 多行输入 | v0.3 高级 TUI（paste burst / 多行编辑） | |
| 5.1-5.4 研究级 | v1.0 探索 | |

完整旧文档保留在 `docs/ROADMAP_LEGACY.md`，有需要再翻。

---

## 这份文档怎么用

1. **每次开新工作前**先看一眼 TL;DR：当前阶段是什么？这个工作属于当前阶段吗？
2. **想做点什么**前先问"这是当前阶段毕业标准的哪一条"。答不出 → 推迟。
3. **想加新能力**前先看"非目标"列表。在里面 → 推迟。
4. **当前阶段毕业标准全 ✅** → 写一笔 commit 标记冻结，然后才进入下一阶段。
