# Runtime State Transition Consolidation: Phase 2/3/4 Remaining Plan

> 状态: **READY FOR RE-AUDIT**
>
> 本文是 Phase 2/3/4 的唯一 implementation planning baseline。重新审计通过前，
> 不提交本文，不进入 Phase 2 implementation。
>
> 核对日期: 2026-06-07。事实来源是当前 `agent/` 与 `tests/` 代码，不是旧 review
> report。旧 report、旧 dashboard、旧行数和旧 rule 估算均不再具有权威性。

## 1. Scope And Non-Goals

本计划只收口剩余 task status direct writes。它不重新打开以下已关闭范围：

- Tool Entry
- Checkpoint Gap 4
- MCP Boundary Phase 1
- XPASS(strict)
- Skill/SubAgent 设计
- Memory activation、治理策略或存储架构
- `TaskState` schema 拆分
- `AgentState.reset_task()` 的 transition 化

本计划允许为两处现有 memory status restore 增加窄范围的 memory-specific event 和
resolver，但不得扩展 generic feedback-intent resolver，也不得改变 Memory 的产品策略。

## 2. Non-Negotiable Transition Contract

所有新迁移的 call site 必须严格按以下顺序执行：

1. **prepare local payload only**: 只读 state，构造 request、pending、message、step
   decision 等局部对象；不得修改 state、messages、checkpoint 或外部 dispatcher。
2. **validate/preflight**: 调用 `validate_task_transition()` 或本计划明确的等价
   preflight，得到已解析的 `previous_status`、`next_status` 和
   `checkpoint_action`。
3. **deny safely**: preflight denied 时立即返回安全错误，不执行任何后续动作。
4. **apply transition**: 把同一个 preflight result 交给
   `apply_task_transition()`；apply 必须检查 current status 仍等于 preflight 的
   `previous_status`，否则按 stale-state denied 返回。
5. **documented side effects**: apply allowed 后，才执行该 unit 明确列出的 pending、
   messages、tool log、dispatcher、step index、control event 等副作用。
6. **explicit checkpoint**: 最后由明确的 checkpoint owner 按真实契约执行一次
   `SAVE`、`CLEAR` 或 `NONE`。

### 2.1 Denied invariant

任何 preflight denied 或 stale apply denied 都必须保证：

- no status mutation
- no pending write
- no pending clear
- no messages append
- no tool_result/control_event append
- no tool execution log mutation
- no checkpoint save
- no checkpoint clear
- no `reset_task()`
- no dispatcher/store write
- no continue loop

日志可以记录一条不含私密 payload 的 denied diagnostic，但不得伪装成成功事件。

### 2.2 Shared preflight/apply resolution contract

Phase 2 U1 必须把当前 API 收口为可复用同一 resolution result 的契约：

```python
preflight = validate_task_transition(state, request)
if not preflight.allowed:
    return safe_denied(preflight.reason)

result = apply_task_transition(state, request, preflight=preflight)
if not result.allowed:
    return safe_denied(result.reason)
```

实现约束：

- `validate_task_transition()` 必须解析最终 `next_status`，不能只检查 table key。
- validate 和无 preflight 的 legacy apply 必须复用一个内部只读 resolver。
- 新迁移 call site 必须把 preflight 传给 apply；apply 不得重新解析 dynamic target。
- apply 必须核对 preflight 的 event、owner、previous status、resolved next status 和
  checkpoint action；stale 或不匹配时 denied。
- 现有 Phase 1 callers 可暂时省略 `preflight=` 以保持兼容，但后续新增 caller 不得
  绕过 preflight。

### 2.3 Checkpoint ownership

`checkpoint_action` 是可执行契约，不是注释：

- `SAVE`: caller 在所有 documented side effects 完成后保存一次。
- `CLEAR`: caller 在完成 terminal side effects 后清理一次；不得先 SAVE 再 CLEAR。
- `NONE`: rule 不拥有 checkpoint；文档必须指出唯一的其他 owner。
- 禁止 `SAVE + caller ignore`、`NONE + 无 owner` 和同一语义事件双重保存。

## 3. Verified Current Baseline

### 3.1 Authoritative write inventory

当前生产代码共有 **25** 个 task status direct writes：

- 1 个合法 transition entry: `apply_task_transition()`。
- 23 个 remaining audit targets，编号 W01-W23。
- 1 个 special writer: `AgentState.reset_task()`。

W01-W23 是本计划的唯一 write inventory。Phase 2 迁移 6 个，Phase 3 迁移 11 个，
Phase 4 保留并硬化 6 个 session-only transient writes。

| ID | Current location | Target | Scanner baseline | Planned outcome |
|---|---|---:|---:|---|
| W01 | `transitions.py:393 apply_user_replied_transition` | `running` | yes | Phase 2 migrate |
| W02 | `transitions.py:418 apply_user_replied_transition` | `awaiting_step_confirmation` | yes | Phase 2 migrate |
| W03 | `memory_interaction.py:288 handle_memory_confirmation_reply` | `<origin_status>` | yes | Phase 3 memory unit |
| W04 | `memory_interaction.py:463 _clear_pending_and_save` | `<origin_status>` | yes | Phase 3 memory unit |
| W05 | `response_handlers.py:510 _maybe_advance_step` | `awaiting_step_confirmation` | yes | Phase 2 migrate |
| W06 | `response_handlers.py:690 handle_end_turn_response` | `awaiting_user_input` | yes | Phase 2 migrate |
| W07 | `response_handlers.py:800 handle_end_turn_response` | `awaiting_user_input` | yes | Phase 2 migrate |
| W08 | `core.py:1048 chat` | `awaiting_user_input` | yes | Phase 3 memory unit |
| W09 | `tool_executor.py:272 execute_single_tool` | `awaiting_user_input` | yes | Phase 2 migrate |
| W10 | `task_runtime.py:80 advance_current_step_if_needed` | `done` | yes | Phase 3 migrate |
| W11 | `task_runtime.py:88 advance_current_step_if_needed` | `done` | yes | Phase 3 migrate |
| W12 | `task_runtime.py:96 advance_current_step_if_needed` | `running` | yes | Phase 3 migrate |
| W13 | `task_runtime.py:98 advance_current_step_if_needed` | `done` | yes | Phase 3 migrate |
| W14 | `core.py:1614 _run_planning_phase` | `awaiting_plan_confirmation` | yes | Phase 3 migrate |
| W15 | `core.py:1684 _run_planning_phase` | `awaiting_plan_confirmation` | yes | Phase 3 migrate |
| W16 | `tool_executor.py:397 execute_single_tool` | `awaiting_tool_confirmation` | yes | Phase 3 migrate |
| W17 | `tool_runtime_mediator.py:570 _handle_confirmation_required` | `awaiting_tool_confirmation` | no | Phase 3 migrate |
| W18 | `session.py:593 handle_interrupt_with_checkpoint` | `awaiting_interrupt_choice` | yes | Phase 4 retain |
| W19 | `session.py:608 handle_resume_choice` | `idle` | no | Phase 4 retain |
| W20 | `session.py:620 handle_resume_choice` | `idle` | no | Phase 4 retain |
| W21 | `session.py:636 handle_interrupt_choice` | `running` | yes | Phase 4 retain |
| W22 | `session.py:652 handle_interrupt_choice` | `idle` | yes | Phase 4 retain |
| W23 | `session.py:384 try_resume_from_checkpoint` | `awaiting_resume_choice` | no | Phase 4 retain |

Special writer S01 is `agent/state.py:381 AgentState.reset_task -> idle`.

### 3.2 Authoritative counts

| Metric | Current | After Phase 2 | After Phase 3 | Final Phase 4 |
|---|---:|---:|---:|---:|
| Production direct writes total, including transition entry and reset | 25 | 19 | 8 | 8 |
| W01-W23 audit targets still present | 23 | 17 | 6 | 6 retained session writes |
| Legacy scanner coverage of remaining W targets | 19/23 | 13/17 | 3/6 | superseded |
| Executable final legal-writer inventory | not available | not available | not available | 8/8 |
| Scanner gaps | 4 | 4 | 3 | 0 |
| `TransitionEvent` enum values | 12 | 15 | 17 | 17 |
| `_TRANSITION_TABLE` rules | 10 | 15 | 27 | 27 |
| New events in phase | - | 3 | 2 | 0 |
| New rules in phase | - | 5 | 11 | 0 |
| Session-only transient writes | 6 | 6 | 6 | 6 |

Scanner current gaps are W17, W19, W20 and W23. Final 8 legal writers are transition entry,
S01 reset, and W18-W23 session writes。

文档行数只用于验证实际文件，不参与架构判断。本次重写后的核对值为 **672 行**，
后续编辑必须以当次 `wc -l` 输出为准。

## 4. Phase Roadmap

| Phase | Scope | Writes | Gate |
|---|---|---:|---|
| Phase 2 | Human-waiting entry/exit，memory 除外 | W01-W02, W05-W07, W09 | 本文重新审计 PASS 后可实现 |
| Phase 3 | Memory origin、task runtime、planning、tool confirmation | W03-W04, W08, W10-W17 | Phase 2 closeout 后 |
| Phase 4 | Session transient contract、scanner/inventory、final closeout | W18-W23 + S01 | Phase 3 closeout 后 |

Memory **不在 Phase 2**。原因不是放弃迁移，而是它需要 dynamic target resolution、
idle entry rule 和独立 compatibility contract；把它塞进 Phase 2 会重新引入 generic
resolver 污染和 preflight/apply 不一致。

## 5. Phase 2: Human-Waiting States

### 5.1 Scope and rules

Phase 2 新增 3 个 event：

- `USER_INPUT_RESOLVED`
- `STEP_CONFIRMATION_REQUIRED`
- `USER_INPUT_REQUIRED`

Phase 2 新增 5 条 rule：

| From | Event | To | Action | Owner | Intended callers |
|---|---|---|---|---|---|
| `awaiting_user_input` | `USER_INPUT_RESOLVED` | `running` | `NONE` | wrapper internal | W01 runtime answer |
| `awaiting_user_input` | `STEP_CONFIRMATION_REQUIRED` | `awaiting_step_confirmation` | `NONE` | wrapper internal | W02 collect answer |
| `running` | `STEP_CONFIRMATION_REQUIRED` | `awaiting_step_confirmation` | `SAVE` | caller | W05 `_maybe_advance_step` |
| `running` | `USER_INPUT_REQUIRED` | `awaiting_user_input` | `SAVE` | caller | W06-W07, W09 |
| `idle` | `USER_INPUT_REQUIRED` | `awaiting_user_input` | `SAVE` | caller | W09 no-plan single-step loop |

Phase 2 后 event 数为 15，rule 数为 15。`idle` rule 只覆盖 no-plan 单步 loop 中的 W09，
不进入 generic origin resolver，也不代表 memory migration。Memory 没有 Phase 2 event/rule，W08 也不在
Phase 2 closeout 条件中。

### 5.2 P2-U1: Shared preflight/apply contract and static rules

Files planned for implementation: `agent/transitions.py` and focused transition tests。

- 新增 3 events、5 rules 和第 2.2 节的 `preflight=` contract。
- static rule 的 validate 也必须返回 resolved `next_status`。
- table exactness 只证明 rule 集合无多无少，不证明 caller 已迁移。
- 增加 rule-to-caller usage inventory；每条 rule 至少关联一个真实 handler test。

Denied tests must cover expected-status mismatch、missing rule、stale between validate/apply，
并断言第 2.1 节全部 no-side-effect 条件。

### 5.3 P2-U2: `apply_user_replied_transition` wrapper

决议: wrapper 保留，status mutation 改走 `apply_task_transition()`；checkpoint 继续由
wrapper 内部拥有。对应两条 rules 必须是 `NONE`，caller 不根据 result 再保存。

#### W01 runtime user input answer

Validate 前允许：

- 读取 pending/question/why_needed/content。
- 局部构造 `step_input` control payload 和 transition request。

Validate/apply 前禁止：

- append control event。
- clear pending。
- save/clear checkpoint。
- continue loop。

Allowed order: preflight -> apply -> append `step_input` -> clear pending -> wrapper 保存一次
checkpoint -> return continue。

Denied handler test must snapshot status、pending、messages、checkpoint calls、control events 和
continue result，确认全部不变/不发生。

#### W02 collect input with per-step confirmation

Validate 前允许：读取 plan/index/confirm flag，局部计算 `is_last_step` 和 reply。

Validate/apply 前禁止：append `step_input`、advance step、save/clear、reset、continue。

Allowed order: preflight -> apply -> append `step_input` -> wrapper 保存一次 -> return
confirmation reply。

Denied handler test必须证明 messages 未追加、step index 未变化、无 checkpoint、无 reply-as-
success。非 confirm/last-step 的 `advance_current_step_if_needed()` 路径不在 W02 内迁移，
由 Phase 3 task-runtime unit 原子处理。

### 5.4 P2-U3: `response_handlers` W05-W07

#### W05 step confirmation required

Validate 前只计算 completion、current index、plan length 和 local reply。不得写 observer
event、status、messages 或 checkpoint。

Allowed order: preflight -> apply -> documented progress/observer events -> save once -> return
confirmation reply。

Denied test从 stale/non-running status 调真实 `_maybe_advance_step` 路径，断言 status、step
index、messages、tool log、checkpoint 和返回控制均无成功副作用。

#### W06 collect/clarify step requests input

是否需要 `USER_INPUT_REQUIRED` 必须在 `_append_assistant_response()` 前由只读 plan/response
检查决定。对将进入该 transition 的分支，现有 observer/evidence 日志和
`consecutive_max_tokens` 等 state mutation 也必须延后；validate 前只能形成局部值。需要
transition 时先 preflight/apply，再 append assistant response、提交这些 documented
mutations/events，最后 save。

Denied test必须证明 assistant response 未进入 messages、counter 未变化、无成功 observer
event，也没有 checkpoint 或 continue。

#### W07 fallback/no-progress requests input

把 projected no-progress count、`awaiting_kind` 和 pending request 先算成本地值；不得先增加
counter、append assistant message 或 set pending。

Allowed order: preflight -> apply -> append assistant response -> commit projected counter -> set
pending -> emit documented event -> save once -> stop loop。

Denied test必须覆盖 pending/counter/messages/event/checkpoint 全部不变。

### 5.5 P2-U4: `tool_executor` W09

`request_user_input` 必须在 generic meta-tool log mutation 前识别。Validate 前只允许：

- 读取 current index 和现有 tool log。
- 局部计算 normalized tool id、stale mark ids、meta log entry 和 pending request。

真实来源状态包括有 plan 的 `running`，以及 `_run_planning_phase()` 返回 `ok` 后直接进入
loop 的 no-plan `idle`。W09 必须对这两个来源分别使用显式 rule；其他状态仍 denied。

禁止先写 tool log、删除 stale mark、set pending、append tool_result 或 save。

Allowed order: preflight -> apply -> write meta log -> remove current-step stale marks -> set pending
-> save once -> return stop/awaiting control。

Denied real-handler test必须证明 tool log byte-for-byte 不变、pending/status/messages 不变、无
tool_result、无 checkpoint、无 tool execution/continue。

### 5.6 P2-U5: Inventory and tests

Phase 2 implementation must update together：

- direct-write baseline: remove W01-W02, W05-W07, W09。
- table exactness expected set: 10 -> 15 keys。
- call-site usage inventory: record all five Phase 2 rules and intended callers。
- real handler tests listed above, not resolver-only tests。
- existing Phase 1 transition tests and user-input regressions。

### 5.7 Phase 2 closeout

Phase 2 is complete only when：

1. Six scoped raw writes are gone; W03-W04/W08 remain explicitly Phase 3。
2. All five rules appear in exactness and usage inventory。
3. Each rule has at least one real call-site test。
4. All denied tests prove the full no-side-effect invariant。
5. Wrapper rules are `NONE`; wrapper saves exactly once after side effects。
6. No code claims memory migration is complete。
7. Targeted tests、`git diff --check`、ruff and full pytest pass。

### 5.8 Phase 2 rollback

Dependency order: U1 -> U2/U3/U4 -> U5。

- U2/U3/U4 may be reverted independently only with their handler tests and baseline entries。
- A shared rule may be removed only when its last caller is reverted; usage inventory determines this，
  not table exactness。
- Reverting U1 requires reverting all Phase 2 callers, expected table keys and usage inventory。
- Restoring a raw write requires restoring its exact baseline count in the same rollback。
- Never leave an unused rule、expected-only baseline entry or migrated caller without a rule。

## 6. Phase 3: Memory, Task Runtime, Planning, Tool Confirmation

### 6.1 Phase 3 events and rules

Phase 3 only adds two events：

- `MEMORY_CONFIRMATION_REQUIRED`
- `MEMORY_CONFIRMATION_RESOLVED`

`STEP_ADVANCED`、`TASK_COMPLETED`、`TOOL_CONFIRMATION_REQUIRED` and `PLAN_GENERATED`
already exist in the current 12-value enum and must be reused。

Phase 3 adds 12 rules：

| From | Event | To | Action | Intended callers |
|---|---|---|---|---|
| `idle` | `MEMORY_CONFIRMATION_REQUIRED` | `awaiting_user_input` | `SAVE` | W08 new-session memory |
| `running` | `MEMORY_CONFIRMATION_REQUIRED` | `awaiting_user_input` | `SAVE` | W08 running task memory |
| `awaiting_user_input` | `MEMORY_CONFIRMATION_RESOLVED` | `<memory_origin_status>` | `SAVE` | W03-W04 |
| `running` | `STEP_ADVANCED` | `running` | `SAVE` | W12 caller path |
| `running` | `TASK_COMPLETED` | `done` | `CLEAR` | W10/W11/W13 caller path |
| `awaiting_user_input` | `STEP_ADVANCED` | `running` | `SAVE` | collect answer |
| `awaiting_user_input` | `TASK_COMPLETED` | `done` | `CLEAR` | last collect answer |
| `awaiting_step_confirmation` | `STEP_ADVANCED` | `running` | `SAVE` | step accept |
| `awaiting_step_confirmation` | `TASK_COMPLETED` | `done` | `CLEAR` | last step accept |
| `idle` | `PLAN_GENERATED` | `awaiting_plan_confirmation` | `SAVE` | W14-W15 |
| `idle` | `TOOL_CONFIRMATION_REQUIRED` | `awaiting_tool_confirmation` | `SAVE` | W16-W17 no-plan path |
| `running` | `TOOL_CONFIRMATION_REQUIRED` | `awaiting_tool_confirmation` | `SAVE` | W16-W17 planned-task path |

Phase 3 后 event 数为 17，rule 数为 27。

### 6.2 P3-U1: Memory-specific origin resolver and W03/W04/W08

Memory 采用方案 B: memory-specific events + memory-specific resolver。不得使用 rule metadata
bypass，不修改 `_ORIGIN_STATUS_ALLOWLIST`，不修改 generic `resolve_origin_status()`。

#### Exact API contract

```python
@dataclass(frozen=True, slots=True)
class MemoryOriginResolution:
    allowed: bool
    target_status: str | None
    reason: str
    source_key: str | None

def resolve_memory_origin_status(state: Any) -> MemoryOriginResolution: ...
```

`validate_task_transition()` 对 `<memory_origin_status>` 调用该 resolver，并把 resolved target
写入 preflight `next_status`。`apply_task_transition(..., preflight=preflight)` 直接使用同一
结果，不再次读取 pending 或再次解析。

Resolver rules：

1. 仅当 `awaiting_kind` 为 `memory_confirmation` 或
   `memory_inline_confirmation` 时启用。
2. `"_origin_status"` 是主键。
3. 只有 `_origin_status` 完全缺失时，才读取兼容键 `"origin_status"`。
4. 两个键都缺失时，为兼容当前 `.get("_origin_status", "running")` 行为，fallback 到
   `running`，并在 resolution 中记录 `source_key="legacy_missing_fallback"`。
5. key 存在但值为 `None`、empty、非 string 时 denied，不走 fallback。
6. 两键同时存在且值冲突时 denied。
7. 允许 target 仅为 `idle` 或 `running`，对应本 phase 两条 entry rules。
8. unknown、terminal (`done/failed/cancelled`)、session transient
   (`awaiting_resume_choice/awaiting_interrupt_choice`) 以及其他 confirmation status 均 denied。

这两条 idle/running entry rules 只定义 memory confirmation 的合法来源，不改变 feedback
origin allowlist。特别是：**不得把 `idle` 或 `running` 加入 generic allowlist**。

#### W08 entry ordering

从 MemoryRuntime 得到 confirmation-required result 后，只允许局部构造 pending 和 request。
随后 preflight/apply；allowed 后才 set pending、保存一次、emit requested event。Denied 时不
覆盖已有 pending，不保存，不 emit requested event，并停止 memory confirmation 分支。

必须有真实 `core.chat` tests 覆盖 idle 和 running；还要覆盖其他 status denied 不覆盖原
pending。

#### W03/W04 resolve ordering

解析用户文本和构造 memory action request可以在 local 阶段完成，但不得先调用 dispatcher、
append retain proposal、fallback pending review、clear pending 或 save。

统一顺序：resolve origin locally -> preflight -> apply -> execute documented memory action ->
clear pending -> emit result -> save once。

真实 handler tests必须分别覆盖 normal confirmation 和 inline confirmation，并覆盖 missing
fallback、None/empty、unknown、terminal、session transient、conflicting keys 及 stale-state。
Denied 时 dispatcher/store/pending-review 均不得调用。

### 6.3 P3-U2: Task runtime W10-W13 and every caller

真实调用点共四处：

| Caller | Actual status before advance | Outcomes |
|---|---|---|
| `response_handlers._maybe_advance_step` | `running` | `STEP_ADVANCED` or `TASK_COMPLETED` |
| `transitions.apply_user_replied_transition` | `awaiting_user_input` | `STEP_ADVANCED` or `TASK_COMPLETED` |
| `confirmation.plan.handle_step_confirmation` | `awaiting_step_confirmation` | `STEP_ADVANCED` or `TASK_COMPLETED` |
| `response_handlers._maybe_advance_step` second branch | `running` | same outcomes |

本计划选择 checkpoint ownership 方案 B。原因是 strict order 要求 apply 后才能 append
`step_input`/`step_confirm_yes`，checkpoint 又必须包含这些 side effects；继续由
`advance_current_step_if_needed()` 提前保存无法同时满足两项约束。

因此：

- `advance_current_step_if_needed()` 不再保存 checkpoint。
- 它先纯计算 local `StepAdvanceDecision`，再 preflight/apply，allowed 后提交 step index。
- `STEP_ADVANCED` rule 返回 `SAVE`；caller 在 message/control side effects 后保存一次。
- `TASK_COMPLETED` rule 返回 `CLEAR`；caller 在 completion message 后 clear 并 reset，
  不先保存 done checkpoint。
- 没有 task-runtime rule 使用 `NONE`，也不存在内部 save。

Tests必须覆盖：

- user input answer 后 advance step。
- step confirmation accept 后 advance step。
- running handler 正常 advance。
- 三种来源的 last step -> `TASK_COMPLETED`。
- ActionPlan/no-plan completion behavior。
- SAVE/CLEAR 各只执行一次。
- stale/denied 时 step index、status、messages、control event、checkpoint 均不变，避免 partial
  step/status mismatch。

Task-runtime migration、三个 caller 的 ordering change、六条 rules 和 checkpoint tests 是一个
原子 rollback unit，不能只回退 helper。

### 6.4 P3-U3: Planning W14-W15

Planning `from_status` 已根据生产 caller resolved 为 **`idle` only**：

- `core.chat` 在调用 `_run_planning_phase()` 前执行 `state.reset_task()`。
- feedback-intent new-task path在调用 `start_planning_fn` 前执行 `state.reset_task()`。
- ActionPlan 和 legacy Plan 是同一次 `_run_planning_phase()` 的互斥解析结果，分支本身不
  产生不同 from status。

因此只新增 `(idle, PLAN_GENERATED)`。不得把 W14 猜成 idle、W15 猜成 running，也不新增
running rule。若未来出现未 reset 的生产 caller，应先作为新设计审计，不得静默放宽 table。

两个分支都必须遵守 local plan payload -> preflight -> apply -> set plan/user goal/index ->
append user message -> scheduler handoff/display -> save once。Scheduler handoff失败必须走明确
failure cleanup，不 emit confirmation、不保存 awaiting 状态；不得留下 status/plan 不一致。

Tests覆盖两个 schema 分支、两个生产 caller、idle precondition、running denied no-side-effect 和
scheduler handoff failure cleanup。

### 6.5 P3-U4: Tool confirmation W16-W17

`tool_executor` 的真实来源为 `idle`（no-plan）或 `running`（plan）；mediator 来源为
`running`。因此使用两条同目标 rule，两个 call site 都必须有真实 handler test。

Validate 前只构造 local pending-tool payload；禁止 set pending、append tool result/control event、
save 或执行工具。Allowed 后 apply -> set pending -> documented event -> save once -> stop。

Denied tests必须覆盖 `tool_executor` 和 `ToolRuntimeMediator`，证明无 pending/tool execution/
messages/checkpoint/continue。W17 还必须进入 expanded usage inventory，不能因 `self._state`
scanner gap 被遗漏。

### 6.6 P3-U5: Inventory and closeout

Phase 3 closeout requires：

1. W03-W04/W08/W10-W17 raw writes全部消失。
2. 12 rules 与 usage inventory 一一对应；shared rule列出全部 callers。
3. table exactness expected set为 27 keys，但不宣称它证明 usage。
4. direct-write baseline只剩 W18、W21、W22 三个当前 scanner 可见 session writes。
5. W19/W20/W23 仍明确列为 scanner gaps，等待 Phase 4 executable inventory。
6. Memory generic resolver/allowlist 未改变。
7. Targeted、integration、ruff、full pytest 和 `git diff --check` 通过。

### 6.7 Phase 3 rollback

Dependency order: Phase 2 closeout -> memory/task/planning/tool units -> inventory closeout。

- Memory rollback必须一起恢复 W03/W04/W08、删除 2 events/3 rules、resolver tests、usage
  inventory和 baseline entries。
- Task-runtime rollback必须一起恢复 W10-W13、所有 caller checkpoint ownership、六条 rules、
  handler tests和 baseline counts。
- Planning rollback必须一起恢复 W14-W15、删除 idle rule、两个分支 tests和 usage entry。
- Tool rollback必须一起恢复 W16-W17、删除两条 source rules和两个 caller tests。
- Shared event/rule只有在最后一个 caller回退后才能删除。
- Baseline/inventory rollback必须与 production rollback同批，禁止 expected-only entry、orphan rule
  或 raw write漏登记。

## 7. Phase 4: Session Lifecycle And Final Hardening

### 7.1 Resolved boundary

W18-W23 是 session-only transient writes，不进入 task `_TRANSITION_TABLE`。这是已决议边界，
不是 open question：

- `awaiting_resume_choice` 和 `awaiting_interrupt_choice` 只服务 CLI session routing。
- 它们不参与 plan/step/tool task transition。
- `reset_task()` 保持 S01 special writer。
- Phase 4 不新增 event 或 rule。

### 7.2 P4-U1: Recovery and transient persistence tests

必须补齐以下真实 session tests：

1. `try_resume_from_checkpoint` 在 TTY actionable checkpoint 下只在内存设置
   `awaiting_resume_choice`。
2. `awaiting_resume_choice` 不写入 checkpoint；恢复文件仍保存原 task status。
3. `handle_interrupt_with_checkpoint` 先保存原 task，再在内存设置
   `awaiting_interrupt_choice`；transient status 不持久化。
4. checkpoint recovery path恢复原 plan/status/pending，并 replay 正确 prompt。
5. `handle_resume_choice`: no-resume、restore failed、restore success。
6. `handle_interrupt_choice`: continue、cancel、exit、invalid。
7. `reset_task()` / finalize / clear behavior，包含 checkpoint call count。
8. 所有 invalid/failed路径不得留下 transient status 或伪成功 event。

### 7.3 P4-U2: Executable scanner/inventory

当前 baseline test只扫描 `state.task.status`，且只遍历 actual entries；它不能保护
`self._state`、`self.task`、`get_state()`，也不能发现 expected-only entries。

Phase 4 必须二选一实现可执行保护，默认采用扩展 AST scanner：

- 支持 `state.task.status`。
- 支持 `self._state.task.status`。
- 支持 `self.task.status`。
- 支持 `get_state().task.status`。
- final actual inventory 与 expected inventory 做**双向 equality**，同时发现 unexpected actual
  和 missing expected。
- final expected只包含 transition entry、W18-W23 和 S01，共 8 writes。

若实现时 AST 对 `get_state()` 无法稳定归一化，则改为独立 executable inventory test；不得把
documentation-only list描述成 scanner protection。

### 7.4 P4-U3: Final legal writers

最终合法 direct writers仅为：

1. `agent/transitions.py::apply_task_transition`。
2. `agent/state.py::AgentState.reset_task`，标记 special factory reset。
3. W18-W23 六个 session-only writes。

最终不得保留：

- `apply_user_replied_transition` 裸写。
- memory confirmation handler 裸写。
- confirmation/response handler 裸写。
- task_runtime 裸写。
- planning/tool executor/mediator 裸写。

### 7.5 Phase 4 closeout

- Six session paths有 recovery/transient persistence tests。
- Expanded scanner或独立 inventory test双向覆盖 8 个 final legal writers。
- 23-write inventory全部处于 migrated 或 explicitly retained 状态。
- Rule usage inventory无 orphan caller/rule。
- Architecture docs和 baseline使用相同 legal-writer list。
- Targeted、ruff、full pytest 和 `git diff --check` 通过。

### 7.6 Phase 4 rollback

Dependency order: recovery tests -> executable inventory -> final docs/closeout。

- Revert scanner expansion时必须同时恢复旧 baseline helper、expected inventory和对应 tests；不得
  留下它扫描不到的 expected entries。
- Revert独立 inventory test时必须同步恢复 scanner-gap documentation，不得继续宣称 executable
  protection。
- Session behavior若因测试发现问题而修改，代码、characterization test和 inventory entry必须一起
  rollback。
- S01 documentation与 scanner support一起 rollback，`reset_task()` 本身不在本 phase 重写。
- Phase 4不修改 table；若发现需要 task event，停止并重新审计，不在本 phase临时加 rule。

## 8. Test And Evidence Strategy

### 8.1 What each proof means

- Table exactness: 只证明 table key 集合无 extra/missing。
- Rule usage inventory: 证明每条新增 rule声明了 intended callers。
- Real handler tests: 证明 caller实际执行该 rule和 side-effect order。
- Direct-write scanner/inventory: 证明 raw writer边界。
- Checkpoint spies/roundtrip tests: 证明 SAVE/CLEAR/NONE ownership和 transient persistence。

任何单一测试都不能替代其他层。

### 8.2 Mandatory denied assertion helper

各 phase可共享测试 helper，但 assertion必须覆盖：status、pending、messages、tool log、step index、
dispatcher/store calls、checkpoint save/clear、reset、control/tool events和 continue decision。不得通过
skip、xfail或弱化断言换取 green。

### 8.3 Quality gates

每个 implementation phase都必须运行：

```bash
git diff --check
.venv/bin/ruff check .
.venv/bin/python -m pytest -q -rx
```

并运行该 phase列出的 targeted tests。XPASS(strict) 是 unrelated known issue，本计划不处理，
但 full suite exit code仍必须符合仓库 gate；若 XPASS 阻断，应单独报告而不是改测试。

## 9. Rule Usage Inventory

实现时维护一份 machine-checkable 或测试内显式 inventory，至少包含：

| Phase | Rule group | Required real callers |
|---|---|---|
| 2 | user input resolved | wrapper runtime answer |
| 2 | step confirmation required | wrapper collect answer、response handler |
| 2 | user input required | response handler两处、tool executor |
| 3 | memory required/resolved | core idle/running entry、normal/inline reply handlers |
| 3 | step advanced/completed | response handler、user reply wrapper、step confirmation handler |
| 3 | plan generated | ActionPlan and legacy Plan branches via both production callers |
| 3 | tool confirmation required | tool executor and mediator |

Revert caller时必须更新该 inventory。Table exactness不得再被描述为 orphan-rule protection。

## 10. Resolved Decisions And Readiness

| Question | Resolution |
|---|---|
| Memory in Phase 2? | No; deferred to Phase 3 memory-specific unit |
| Memory bypass? | No metadata bypass; dedicated events + resolver + shared preflight result |
| Memory keys? | `_origin_status` primary; `origin_status` compatibility only when primary absent; both absent -> running legacy fallback |
| Idle memory path? | Explicit `(idle, MEMORY_CONFIRMATION_REQUIRED)` rule; generic allowlist unchanged |
| Wrapper checkpoint owner? | `apply_user_replied_transition`; rules are `NONE` |
| Task-runtime checkpoint owner? | Caller-owned; `STEP_ADVANCED=SAVE`, `TASK_COMPLETED=CLEAR`; helper no longer saves |
| Task-runtime caller states? | running、awaiting_user_input、awaiting_step_confirmation all covered |
| Planning from status? | Resolved: production callers reset to idle; one idle `PLAN_GENERATED` rule |
| Session writes in task table? | No; session-only transient boundary |
| Reset task? | Permanent special writer |
| Phase 2 ready? | Design-ready, but implementation is gated on re-audit PASS |
| Phase 3/4 ready? | Sequenced and specified; implementation waits for previous phase closeout |

There are no unresolved Open Questions in this baseline。任何新 blocker必须新增到对应 phase gate，
不能同时保留 READY 和 unresolved blocker。

## 11. Per-Phase Evidence Packet

每个 phase结束时记录：

- repo status和 ahead/behind。
- changed files及范围理由。
- Red/Green evidence和 denied no-side-effect evidence。
- rule exactness、usage inventory、direct-write inventory结果。
- checkpoint ownership call counts。
- targeted/full quality gates和 exit codes。
- rollback unit映射。
- P0/P1/P2/P3 risk review。
- final verdict和下一 phase gate。

本次任务只修订本文，不实现上述代码或测试，不提交 commit。
