# 压力下优先保留近期上下文计划

- Date: 2026-09-08
- Status: verified-closed
- Source: Oracle Web r5 session `first-agent-product-architecture-r5-20260908-e47a` + Codex current-main verification
- Executor: Pi, `cc-switch-zhipu-glm/glm-5.3`, thinking `max`

## Outcome

当普通模型上下文超过可用 input budget 时，`KernelContextManager` 必须：

1. 先按现有相对顺序淘汰最低优先级 `ContextSource` candidates；
2. 仍超预算时，从最旧的非 pinned 历史原子组开始淘汰；
3. 保留组仍按原始事实顺序进入 `ContextPack`；
4. pinned core 放不下时继续在 Provider 调用前 fail closed。

用户可感知结果是：长任务在预算压力下优先保留刚确认的约定和较新的工作事实，
不再保留旧内容却先忘掉较新内容。

## Verified defect

当前 `agent/runtime/context.py::KernelContextManager._plan` 的顺序是：

1. `_group_facts` 产生从旧到新的历史组；
2. goal/bootstrap 在前，source groups 在后，runtime progress 最后追加；
3. 一个全局倒序循环排除所有非 pinned groups。

这个循环先排除末尾 source 是正确的，但继续受压时会从新到旧排除历史，
与 `docs/architecture/KERNEL_ARCHITECTURE.md` 承诺的“最旧完整原子组优先淘汰”相反。
现有 `tests/kernel/test_context_compaction_plan.py::test_usage_budget_equals_build_budget_without_sources`
还把较新的 `assistant-1` 被排除固化为预期，必须连同行为一起纠正。

## Interface and deep-module decision

- 外部 seam 保持 `KernelContextManager.build/usage/plan_compaction`，不增加 public method、port 或配置。
- `context.py` 保持一个 deep module：普通 build、usage 与 compaction 共享同一预算 owner。
- 只在 `_plan` 内显式表达两种 eviction order，不引入 strategy、registry、feature flag 或第二个 manager。
- 不按文件行数拆分 `context.py`，也不按 candidate ID、tool name 或 data-class 字符串猜分组类型。

## Minimal internal design

在构造最终 `groups` 时保留明确的区间：

- `history_groups`：事实、goal 与 bootstrap；
- `source_groups`：`_collect_source_groups` 的结果；
- `progress_group`：既有 pinned 尾组。

排除顺序固定为：

1. `source_groups` 的索引按现有倒序遍历，保持现有 source 相对优先级；
2. `history_groups` 的索引按时间正序遍历，跳过 pinned；
3. `progress_group` 继续 pinned，不进入可排除集合。

最终 `selected/excluded` 仍按组合后的原始索引顺序投影，避免改变消息序列和报告确定性。

## Vertical TDD slices

### U1 — 最小历史反例

- RED：通过 public `usage()` 或 `build()` 构造三个从旧到新的等成本、非 pinned 历史组，
  另有当前 pinned user；预算只需排除一组。旧实现必须明确排除 recent，而非 oldest。
- GREEN：只改现有 `_plan`，使 oldest 被排除，较新两组保留。
- 不允许通过扩大 budget、修改 estimator 或直接调用 private `_plan` 让测试通过。

### U2 — source 优先级不倒退

- RED：同时存在 source candidates 与多个历史组；预算先需要排除 source，继续受压再排除一组历史。
- GREEN：先排除既有最低优先级 source，再排除 oldest history；source 相对顺序保持。
- 使用真实 `ContextSource` fake 和 public `build()`；`usage()` 必须保持零 source 调用。

### U3 — 原子组、pinned 与边界

- 覆盖 tool-call/all-results 原子组、最后 user、最后 tool-result group、pending request。
- 覆盖无压力、恰好等于预算、只超一组、多个 pinned 穿插。
- fixed pinned core 超限仍抛 `ContextLimitError`，Provider/tool/checkpoint 零调用。
- 更新现有错误预期，只改变 eviction truth，不放宽断言。

### U4 — compaction 与离线产品旅程

- `build()` 与无-source `usage()` 对相同核心输入保持同一预算决策。
- `plan_compaction` 的 candidate protection、合法 no-candidate、archive-before-CAS 与 replay 不回退。
- 用 scripted Provider 检查真实收到的 `ContextPack`：较新的已确认字段必须存在，旧无关字段可被淘汰；
  结果不能由 fake 固定返回成功来伪造。
- 若已有产品入口 fixture 能最小复用，则覆盖一次临时 workspace 的生成、审批、read-back 与 restart；
  若需要新建第二套 E3 harness，停止扩张，改用现有 Runtime public path 集成测试。

## Protected boundaries

- `AgentRuntime.run_turn` 仍是唯一 production progression 与 state mutation owner。
- `KernelContextManager` 独占 context selection；Provider/CLI/ToolRuntime 不参与淘汰策略。
- `usage()` 不调用 ContextSource、Provider、Tool 或 checkpoint mutation。
- tool call 与其全部 results 不拆分。
- summary 仍是 untrusted data，不重建 Goal、Evidence、Approval 或 Recovery。
- compaction protected facts、archive-before-CAS、replay、approval、lease 与 unknown recovery 语义不变。
- 不改变 checkpoint schema、工具 schema、token estimator、input limit、output reserve 或 compaction threshold。

## Non-goals

- 不修 Oracle F2：pre-call rejection 被投影成 unknown recovery。
- 不修 Oracle F3：invoke failure 无条件 reset no-progress tracker。
- 不修 Oracle F4：MCP schema 对真实 `title` 参数 drift 漏检。
- 不处理 F5-F8 的产品文案、实时进度、旧 scheduler 或兼容残余。
- 不拆 `contracts.py`、`loop.py`、`state.py`、`checkpoint.py`、`tools.py`、`context.py` 或 `main.py`。
- 不新增 Provider、Memory ranking、SubAgent 并发、Skill registry、scheduler daemon 或 browser 能力。
- 不访问真实 Provider、网站、profile、credential、private runtime 或未跟踪 `tui/`。
- 本轮不 commit、push、发布或 promotion，除非用户另行要求。

## Expected files

- Production: `agent/runtime/context.py`
- Tests: 优先复用 `tests/kernel/test_context_manager.py`、
  `tests/kernel/test_context_compaction_plan.py`、`tests/kernel/test_runtime_compaction.py`
- Documentation: 本计划；只有现有架构措辞与实现不一致时才最小更新对应小节。

扩大 production 文件范围前必须先由 Pi 报告具体依赖，不能自行扩张。

## Verification

每个 slice 只跑对应 focused tests。实现完成后依次运行：

1. context manager focused tests；
2. compaction/runtime/continuity touched-area tests；
3. architecture ownership/dependency gates；
4. fresh Pi read-only audit；
5. 仅在前述全部通过后，运行一次最终门禁：
   - `git diff --check`
   - `.venv/bin/ruff check .`
   - `.venv/bin/python -m pytest -q -rx`

成功要求：旧反例真实 RED、新行为 GREEN、source 优先级与消息原序不倒退，所有命令完整 exit 0。
离线证据只声明 E0-E2，不冒充真实模型质量或外部 E3。

## Deferred findings ledger

- F2 / P1：`KernelToolRuntime.invoke` 的部分 callable 前拒绝可能被 Runtime 误归 unknown outcome。
- F3 / P1：invoke 返回 `is_error=True` 或 `executed=False` 后可能无条件重置停滞追踪。
- F4 / P1：MCP `_canonical_schema` 递归删除 `title`，可能漏掉名为 `title` 的真实参数类型 drift。
- 待核验：takeover 后旧 browser session 的预期生命周期；MCP 父进程先退出而同组 child 存活的回收。

这些项目必须独立取证、独立 spec，不能在本轮顺手修复。

## Implementation notes

- Pi 交互执行器完成 U1 Red/初始 Green 后长时间停留在推演；非交互执行器随后无输出、
  无文件进展。Codex 保留其有效 U1 改动，并在同一冻结合同内接手 U2-U4。
- `_plan` 在追加 source 前记录 history 区间；淘汰序列先倒序覆盖全部 source，
  再正序覆盖 history。progress 仍不进入淘汰序列，最终 selected/excluded 仍按原序投影。
- U2 Red 的实际失败为：期望 `candidate-low`，旧的整体正序实现实际排除
  `user-old`；分区淘汰实现后对应公开 `build()` 测试通过。
- focused 证据：context/compaction/runtime touched-area `117 passed`；architecture
  gates `69 passed`；fresh Pi read-only audit 为 `PASS`，无 P0/P1/P2 阻塞问题。
- 最终门禁：`git diff --check`、全量 Ruff 均通过；全量 pytest 为
  `3227 passed, 3 skipped`，完整 exit 0。本轮未执行真实外部 E3、commit 或 push。
