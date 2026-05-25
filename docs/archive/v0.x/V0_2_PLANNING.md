# Runtime v0.2 · Engineering Milestones Plan

> **本文目的**：Runtime v0.1 已毕业，v0.2 要把「能跑」的原型工程化。
> 本文件只做 planning，不实现 v0.2 代码。
>
> **当前结论**：第一个 v0.2 milestone 应该是 **Runtime 状态机整理**。
> 原因很直接：InputIntent / RuntimeEvent 边界、checkpoint 恢复、基础 TUI、
> 基础权限和错误恢复都依赖一个明确的状态集合与状态转移规则。先做 UI 或工具
> 工程化，会继续放大当前状态语义不清的问题。

---

## 1. v0.2 目标

v0.2 的主题是：把 v0.1 粗糙能力工程化。

v0.2 不追求高级 Agent 框架，也不追求完整产品化 TUI。它要把 v0.1 已经跑通的
最小 Runtime 变成更可维护、可恢复、可观察、可扩展的工程底座。

核心目标：

- 明确 Runtime 状态机和合法转移。
- 收口 InputIntent / RuntimeEvent / DisplayEvent 的职责边界。
- 工程化基础工具体系。
- 明确 checkpoint 恢复语义。
- 补基础错误恢复和 loop guard。
- 建立基础安全权限边界。
- 在 v0.1 CLI 输出契约之上实现基础 TUI / CLI UX。

## 2. 非目标

v0.2 不做：

- Skill 子系统正式化、install/update skill 生命周期、skill 安全审查成熟化。
- Sub-agent / 多 Agent 协作。
- MCP / 多模型路由 / 长期记忆 / 用户偏好自学习。
- LLM 二次意图分类作为默认输入语义方案。
- v0.3 高级 TUI：多面板、timeline、event replay、复杂调试器、paste burst。
- Textual Esc 与 generation cancellation 的完整 UI 集成；v0.2 只允许先做
  cancel 生命周期与 RuntimeEvent，UI 集成归 v0.3。
- 正式生产级安全沙箱；v0.2 只做基础权限边界。

## 3. 建议顺序

| 顺序 | Milestone | 为什么排这里 |
|---|---|---|
| 1 | M1 Runtime 状态机整理 | 所有后续边界都依赖合法状态和转移规则 |
| 2 | M2 InputIntent / RuntimeEvent / DisplayEvent 边界治理 | 输出、输入、TUI、observer 都需要统一事件边界 |
| 3 | M3 Checkpoint 恢复语义 | 状态机和事件边界明确后，才能定义恢复哪些状态、如何提示用户 |
| 4 | M4 错误恢复 / loop guard / no-progress 策略 | 防止真实运行卡死或重复追问，保护工程化主循环 |
| 5 | M5 工具体系优化 | v0.2 主要工作量；放在状态和错误边界之后更稳 |
| 6 | M6 基础安全权限 | 依赖工具接口规范，先实现 path / shell 最小权限边界 |
| 7 | M7 基础 TUI / CLI UX 实现 | 在稳定事件边界上做 Textual backend 与状态面板 |
| 8 | M8 Generation cancel 生命周期 | 只做 core lifecycle，不做 v0.3 Esc UI 集成 |

## 4. Milestone 细化

### M1 · Runtime 状态机整理

目标：

- 列出 v0.2 允许的 `TaskState.status` 集合。
- 画出状态转移表：入口、出口、触发事件、持久化行为。
- 明确哪些 awaiting 状态是历史探索、哪些保留、哪些仅作为 v0.2 债务。
- 把状态不变量写成测试或文档可检查规则。

完成标准：

- 新增 `docs/RUNTIME_STATE_MACHINE.md` 或等效章节。
- 状态集合、转移表、checkpoint 影响、用户提示行为都可查。
- 现有测试无 RED。
- 不新增功能性状态，除非文档先说明为什么 v0.2 必须新增。

风险：

- 当前已有探索性状态与 v0.1 之外行为混在一起，容易误删或误判。
- 如果先重构代码再写状态表，会扩大回归面。

建议：

- 先做只读审计 + spec，再用最小测试锁住现状，最后才做代码收口。

### M2 · InputIntent / RuntimeEvent / DisplayEvent 边界治理

目标：

- 明确输入层只负责 raw input -> `InputIntent`，不解释 Runtime 业务语义。
- 明确 RuntimeEvent 是 Runtime 到 UI / CLI 的唯一业务事件通道。
- 明确 DisplayEvent 是展示层结构，不承载状态机决策。
- 收口 v0.1 遗留的 print 旁路，先处理最影响用户理解的路径。

完成标准：

- 文档化三者职责边界和禁止项。
- simple CLI 仍符合 `docs/CLI_OUTPUT_CONTRACT.md`。
- 不新增 v0.3 UI 事件。
- B2 回归测试继续通过。

风险：

- 容易把 Textual 实现和 RuntimeEvent schema 治理混在一起。
- 容易为了修一个输出问题新增过多 event kind。

建议：

- 先收口语义，后做 UI。每新增 event kind 都必须有状态机或恢复语义依据。

### M3 · Checkpoint 恢复语义

目标：

- 定义哪些状态可以恢复，哪些状态启动时应清理或降级。
- 定义 checkpoint 损坏、版本不兼容、缺字段时的行为。
- 定义 resume prompt 与 CLI/TUI 输出契约的关系。

完成标准：

- `checkpoint.json` schema / version 策略有文档。
- 覆盖 awaiting plan / tool / user input / running / done 的恢复测试。
- 损坏 checkpoint 不导致 crash。
- 普通 CLI 不泄漏 checkpoint values。

风险：

- 恢复语义不清会影响状态机、用户确认流和 TUI 状态面板。
- 过早做跨版本兼容可能超出 v0.2。

建议：

- v0.2 只做最小版本字段和损坏态自愈，不做复杂迁移框架。

### M4 · 错误恢复 / loop guard / no-progress 策略

目标：

- 明确模型无进展、重复追问、工具失败、模型连接失败时的最小处理。
- 给主循环加可审计的停止条件和用户可见错误。
- 保留 v0.1 能跑路径，不引入复杂 retry policy。

完成标准：

- loop guard 行为有测试。
- 工具失败和模型连接失败不会裸 traceback 给普通用户。
- no-progress 检测能给出明确原因。
- 不把错误恢复做成自动无限重试。

风险：

- 错误恢复容易和 LLM 意图分类、复杂 topic switch 混淆。

建议：

- 只做结构化失败和有限重试；复杂决策留到后续版本。

### M5 · 工具体系优化

目标：

- 统一工具 schema、描述、错误返回和结果摘要。
- 为基础工具补单元测试和使用文档。
- 让工具选择质量可观察。

完成标准：

- 每个 v0.2 基础工具有 schema、错误约定、测试。
- 长 tool result 有截断或摘要策略。
- 工具调用失败不会破坏 tool_use / tool_result 配对。

风险：

- 工作量最大，容易顺手新增工具。
- 结果压缩可能影响模型后续上下文质量。

建议：

- 不新增工具，先工程化已有 read / write / shell / meta / request_user_input 链路。

### M6 · 基础安全权限

目标：

- 建立工作区根目录约束。
- 给 shell 命令和写文件建立最小审查规则。
- 明确哪些权限是 v0.2 基础权限，哪些是 v1.0 正式安全围栏。

完成标准：

- path traversal、工作区外写入、高风险 shell 命令有测试。
- 用户确认流能展示风险原因。
- 不声称具备生产级沙箱。

风险：

- 安全边界容易半成品却被误以为生产可用。

建议：

- 文档和 UI 文案都必须使用「基础权限」而不是「安全沙箱」。

### M7 · 基础 TUI / CLI UX 实现

目标：

- 在 v0.1 CLI 输出契约和 v0.2 RuntimeEvent 边界上，实现最小可用 Textual backend。
- 提供基础状态面板：goal / plan / current step / status。
- 展示 plan / tool / pending user input / checkpoint resume 的清晰 UI。

完成标准：

- simple CLI 和 Textual backend 都可用。
- Textual backend 不依赖 stdout debug capture 才能正确显示核心 Runtime 信息。
- 状态面板不引入新 Runtime 业务语义。
- 不做多面板 timeline / event replay / paste burst。

风险：

- 如果 M1 / M2 没完成，TUI 会继续依赖 hacky stdout filter。

建议：

- 等 RuntimeEvent 边界稳定后再做 Textual。

### M8 · Generation cancel 生命周期

目标：

- 在 core/model stream 层定义 cancel token 生命周期。
- 定义 `generation.cancelled` 或等价 RuntimeEvent。
- 保证取消后 checkpoint / state / tool pairing 不损坏。

完成标准：

- core 层可取消生成。
- 取消不会留下不一致状态。
- 对应 xfail 的 v0.2 前置条件满足一半：Runtime 生命周期完成。

风险：

- TUI Esc 集成属于 v0.3，v0.2 如果顺手做会扩大范围。

建议：

- v0.2 只做生命周期和测试；Textual Esc UI 集成留给 v0.3。

## 5. 第一批实施建议

第一批只开 M1：

1. 只读审计当前 `TaskState.status`、awaiting 字段、pending tool/user input、
   checkpoint save/load、confirm_handlers。
2. 写 `docs/RUNTIME_STATE_MACHINE.md`。
3. 补最小状态转移测试，先保护现状。
4. 再决定是否做代码收口。

不要在 M1 同时做 Textual、工具体系、安全权限或 topic switch。

## 6. v0.2 Stop Rules

- 每个 milestone 必须有文档化目标和完成标准。
- 没有状态机依据，不新增 awaiting 状态。
- 没有 RuntimeEvent 边界依据，不新增 event kind。
- 不把 v0.3 高级 TUI、Skill 正式化、sub-agent、LLM 二次意图分类带入 v0.2。
- 任何实现前先确认它属于本文件的哪个 milestone。

## 7. 与 v0.1 Graduation 的关系

v0.1 已通过 `docs/V0_1_GRADUATION_REPORT.md` 记录的真实 smoke。v0.2 的所有
工程化工作必须保持 v0.1 的最低能力不回退：

- simple CLI 仍能跑 README -> `summary.md` smoke。
- `docs/CLI_OUTPUT_CONTRACT.md` 仍被遵守。
- `pytest` 无 RED，xfail 归属不被弱化。
- `summary.md` 仍是本地 smoke 产物，不提交。
