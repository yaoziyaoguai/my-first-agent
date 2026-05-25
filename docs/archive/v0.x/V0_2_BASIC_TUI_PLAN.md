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

## 7. 实施前置条件（已部分满足，本轮按 M7-A 切片落地）

- [x] M1-M6 RC 主线闭环（已完成）
- [x] 自动 smoke 全覆盖（已完成）
- [x] M7-A 切片：工具 pre/post hook 拒绝 vs 真实失败 vs 成功 三类区分
      （已落地：`_classify_tool_outcome` + `tool.rejected` 显示事件 +
      `rejected_by_check` 审计 status；测试 `tests/test_cli_output_ux.py`）
- [ ] M7-B/C/D：RuntimeEvent 渲染统一 / checkpoint resume 可见性提升 /
      文档+完整测试覆盖（待用户人工试用反馈再评估范围）

只有上面前 3 条已落地；M7-B/C/D 等待用户人工试用反馈再决定是否启动，
避免在没有真实痛点的情况下提前重构。

### 7.1 M7-A 已交付（实际修复一个真实 bug）

旧 `tool_executor` 只看 `TOOL_FAILURE_PREFIXES` 区分 failed / executed。
工具内部 pre/post hook（`pre_write_check` / `check_shell_blacklist` /
`_check_dangerous_content`）拒绝时返回 `"拒绝执行：..."` 字符串，
**不命中**任何失败前缀，结果：

- UI 显示「执行完成。」（用户看不出工具被拒）
- `tool_execution_log[...]["status"] == "executed"`（审计错记成功）
- 模型在下一轮没收到「不要重复同一调用」的系统提示

修复后：`"拒绝执行："` 走独立的 `rejected_by_check` 分支，emit
`tool.rejected` 显示事件 + 「已被工具内部安全检查拒绝。」，并附加
重复调用阻止提示。这是 RC smoke 之外的第三个真实文案区分缺口。

### 7.2 M7-B 已交付（policy denial / user rejection 显示事件补齐）

真实 main.py smoke 发现两个体验缺口：

1. `confirmation == "block"` 路径（read_file ~/.env / .pem 等）执行后
   FORCE_STOP 总结说「具体拒绝原因见上方工具消息」，但「上方」其实**空无一物**——
   旧实现 block 分支不 emit 任何 display event。
2. 用户输入 'n' 拒绝工具时，CLI 终端没有任何 display event 反馈，用户无法
   确认「我的拒绝是否被系统接受」，紧接着的下一轮 chat 输出会被误解为
   「系统继续执行了」。

修复：

- `tool_executor.py` block 分支补 emit `tool.rejected` event，
  status_text 形如「被安全策略拒绝：路径 'X' 被识别为...」（取
  `_describe_policy_denial` 首行，去掉 `[安全策略] ` 前缀避免重复）。
  这样 FORCE_STOP 的「见上方」承诺成立。
- `confirm_handlers.py` 拒绝/feedback 分支补 emit `tool.user_rejected`
  event，`status_text` 「用户拒绝执行，已跳过。」/「用户未批准，改为
  提供反馈意见。」，与 `tool.rejected` 严格区分。
- `display_events.py` `runtime_display_event` 把 `tool.user_rejected`
  也纳入 `EVENT_TOOL_RESULT_VISIBLE`，UI 一致渲染。

四类工具结局至此**完全互不重叠**，详见 `docs/CLI_OUTPUT_CONTRACT.md` §8.1。

### 7.3 M7-C 已交付（resume 可见性 + 残留 checkpoint 自清）

真实 main.py smoke 发现：旧 `try_resume_from_checkpoint` 只要 checkpoint
文件存在就 prompt。`status='idle' + 0 条消息 + 无 pending` 这种历史残留
也会显示「📌 发现未完成的任务：（未命名任务） 已有 0 条对话历史」，
强迫用户 y/n。同时拒绝时只输出「已清除断点。」一行（与 prompt 同行，
无视觉分隔），用户看不出已经回到对话模式。

修复后：

- 新增 `_checkpoint_has_actionable_resume()`：只在 `awaiting_*` /
  pending_tool / pending_user_input_request / 进行中 plan / 非 idle 且
  有消息 时才提示；其他视作残留，静默 `clear_checkpoint()`。
- prompt 显示中加 `状态：<status>` 字段，让用户看清楚断点处于什么阶段。
- 拒绝路径文案改为带换行的 `[系统] 已清除断点，回到对话模式，可以直接输入新任务。`

### 7.4 实测覆盖（tests/test_cli_output_ux.py 17 个）

- 三类分类正确（rejected_by_check / failed / executed）
- pre-check 拒绝不再误显示 completed
- 真实失败仍走 tool.failed
- 真实成功仍走 tool.completed
- post-confirm 拒绝走 tool.rejected
- runtime event 映射稳定（rejected / user_rejected）
- status 命名空间不与 blocked_by_policy 重叠
- M7-C：5 类 actionable / non-actionable checkpoint 判定
- M7-B：policy denial emit tool.rejected + 不泄漏文件内容；
  user reject emit tool.user_rejected；四类 status_text 关键字互不重叠

### 7.5 真实 main.py smoke 已通过的场景

- 无 checkpoint 启动：直接进入对话模式，无虚假提示
- idle/空残留 checkpoint：被静默清理
- actionable checkpoint：清晰 prompt，y/n 都有可读后续
- 真实 calculate 工具：tool.executing → tool.completed 渲染清晰
- 真实 write_file 项目外路径：tool.executing「已收到确认，开始执行」→
  tool.rejected「已被工具内部安全检查拒绝」，**不再显示「执行完成」**
- 真实 read_file /tmp/server.pem（policy denial）：先看到
  「[工具执行状态] 被安全策略拒绝：...」具体原因，再看到 FORCE_STOP 总结
- 真实 write_file workspace/m7_test.txt + 用户输入 'n'：看到
  「[工具执行状态] 用户拒绝执行，已跳过。」，与策略拒绝文案完全区分
- 文件未真的写出去，亦未出现 `./~` 字面目录

仍建议用户人工观察（M7 范围之外）：fork bomb / `echo > /dev/sd*` 在 shell
工具白名单层的实际行为（自动 smoke 已断言文本，但模型有时会自行拒绝
而不调用工具，需真实人眼判断这种「模型层拒绝」是否符合预期）。

---

## 8. 与 v0.2 PLANNING 的关系

本文件是 `docs/V0_2_PLANNING.md` M7 的细化。它**不**新增 milestone，
**不**改 v0.2 范围，**不**承诺 timeline。
