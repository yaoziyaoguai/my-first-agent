# Runtime v0.2 · 基础 TUI / CLI UX Milestone Plan

> **本文件目的**：把「v0.2 基础 TUI / CLI UX」这一 milestone 的范围、
> 非目标、与 v0.3 高级 TUI 的边界一次性写清楚。
>
> **本文件只做 planning，不做实现**。任何 Textual 代码、状态面板
> 实现、快捷键绑定都不属于本轮工作。

---

## 1. 这个 milestone 在 v0.2 内的位置

`docs/V0_2_PLANNING.md` 中的 **M7 · 基础 TUI / CLI UX 实现**。

它**应该**在 v0.2 RC 主线（M1-M6）闭环后启动，作为「让人工试用更
顺手」的加速器，而不是 v0.3 才开始。

它**不是**：
- v0.3 的高级 Textual 多面板 / timeline / event replay
- generation cancellation 的 Esc 集成
- paste burst / bracketed paste 输入处理

---

## 2. 为什么基础 TUI 是人工试用的加速器

当前 simple CLI（`main.py`）已经满足 `docs/CLI_OUTPUT_CONTRACT.md`，
但它在以下三类场景下让人工试用很慢：

1. **状态可见性**：用户看不到当前 status（`awaiting_plan_confirmation`
   / `awaiting_tool_confirmation` / `awaiting_user_input` / `running`）
   与 plan 的当前 step。需要心算「我现在该回什么」。
2. **拒绝原因可见性**：policy denial / user rejection / tool failure
   三种「执行未完成」原因混在 stdout 里，需要用户翻日志区分。
3. **checkpoint resume 可见性**：Ctrl+C 后重启，用户不知道 Runtime
   恢复到了哪个 step / 是否有 pending tool。

基础 TUI 就是给上面三件事做最小可视化，不引入新业务语义，不依赖
stdout debug capture。

---

## 3. 范围（v0.2 基础 TUI）

### 3.1 必须做

- 一个**最小**状态面板：goal / current step / status / pending tool 名称。
- plan / tool / pending user input 三类**清晰分区**。
- policy denial / user rejection / tool failure **三类不同标签 + 颜色**。
- checkpoint resume 时**显式提示**「上次任务恢复到 step N，pending: X」。
- 所有渲染 100% 走 `RuntimeEvent` / `DisplayEvent`，**禁止**新增
  stdout 解析。
- simple CLI 与基础 TUI **可切换**；simple CLI 行为不变。

### 3.2 不做（明确划入 v0.3 或更晚）

- Textual 多面板 timeline / event viewer / event replay。
- 快捷键大全、modal dialog、自定义主题。
- Esc 取消生成（依赖 v0.2 M8 cancel 生命周期 + v0.3 Esc 集成）。
- paste burst / bracketed paste / `prompt_toolkit` 输入层升级。
- 长输出懒加载、虚拟滚动、search/jump。

---

## 4. 与 v0.3 高级 TUI 的明确边界

| 维度 | v0.2 基础 TUI（M7） | v0.3 高级 TUI |
|---|---|---|
| 渲染框架 | 可选 Textual minimal 或加强后的 simple CLI | Textual 多面板 |
| 事件来源 | 现有 `RuntimeEvent` / `DisplayEvent` | 同上 + timeline / replay |
| 取消 | 不支持 | Esc → `generation.cancelled` |
| 输入 | 仍是 line-based `input()` | bracketed paste / multiline editor |
| 状态可见性 | 单面板，4-5 字段 | 多面板，full state inspector |
| 快捷键 | 无 | 有 |
| 主题 | 无 | 有 |

---

## 5. 完成标准（v0.2 M7）

- 用户在基础 TUI 中能**不看代码**就回答这三个问题：
  1. 「我现在在等什么？」
  2. 「上一个工具调用为什么没成？」（policy / user / tool failure）
  3. 「Ctrl+C 重启后我在 plan 的哪一步？」
- simple CLI 测试基线不退化。
- 不依赖 stdout debug capture。
- 不引入新 RuntimeEvent / 新 status / 新业务语义。

---

## 6. 风险与对策

- **风险 1**：在「最小」面板上叠太多字段，演化成 v0.3 多面板。
  - 对策：本 plan §3.1 字段集合就是上限，新增字段需要单独 spec。
- **风险 2**：Textual 集成把 stdout / debug capture 重新引入。
  - 对策：M2 事件边界 spec 已禁止；本 milestone 复用同一断言
    （扩展 `tests/test_runtime_event_boundaries.py`）。
- **风险 3**：Esc / 快捷键被「顺手做」。
  - 对策：写入 §3.2，PR review 必须拒绝。

---

## 7. 实施前置条件（**当前未满足，所以本轮只做 planning**）

- [x] M1-M6 RC 主线闭环（已完成）
- [x] 自动 smoke 全覆盖（已完成）
- [ ] 用户人工试用 RC，明确「现在 simple CLI 哪些场景最痛」（**未做**）
- [ ] 与 user 确认基础 TUI 是 v0.2 后续而非 v0.3 起点（**未做**）

只有上面 4 条都打钩后，才能开 PR 启动 M7 实现。

---

## 8. 与 v0.2 PLANNING 的关系

本文件是 `docs/V0_2_PLANNING.md` M7 的细化。它**不**新增 milestone，
**不**改 v0.2 范围，**不**承诺 timeline。
