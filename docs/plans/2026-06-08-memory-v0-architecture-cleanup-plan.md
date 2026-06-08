---
title: "Memory v0 Architecture Cleanup Plan"
type: plan
status: active
date: 2026-06-08
---

# Memory v0 Architecture Cleanup Plan

## A. Executive Summary

Memory 已经有 explicit user memory 的基础：用户说 `remember` / `记住` 后，当前代码可以进入 policy、confirmation、store 和 prompt recall 的主路径。  
但 Memory v0 还没有 ready：durability、source-of-truth、checkpoint consistency、working_summary boundary、evidence/log、backend root policy、Skill/SubAgent boundary 都仍是 PARTIAL。  
本计划目标是 durable explicit user memory + safe recall + built-in evidence/log + checkpoint consistency + safe backend，而不是扩展成新的长期画像系统。  
v0 优先 explicit user memory：用户主动记住、查看、更新/纠正、删除，并且每个会影响 store 或未来 prompt 的动作都有内置 evidence/log。  
Sub-agent / child-agent direct memory write 在 v0 中显式 blocked；任何现有 child memory store-write path 都必须先锁死。  
Model-visible memory tools 是 v0 必做的 request-only 能力：模型只能 request/propose/list/request-forget，不能 direct commit memory。  
Skill `memory_scope=none` suppress recall injection 是 v0 closeout 强制条件，不再是可选项。  
Agent-proposed proactive discovery、hidden long-term profiling、Sub-agent memory write、MCP auto-memory、vector/RAG、L2/Emergence production 接入全部暂缓。  
Memory evidence/log 是 v0 一等目标，不是增强项；任何 memory recall/write/proposal/delete/update/summary/child request 影响 prompt、store 或 checkpoint 的行为都必须可追踪、可审计、可脱敏展示。

## B. Current-State Baseline

### 1. Explicit user memory

当前 explicit user memory 是 Memory 最接近可用的主线能力。

- 触发方式：用户输入命中 `agent/memory_policy.py` 的 deterministic prefix，例如 `remember`、`remember that`、`记住`、`请记住`、`forget`、`忘记`、`update memory`、`更新记忆`。
- 主入口：`agent/core.py::chat()` 调用 per-session `MemoryRuntime.evaluate_user_text()`。
- policy：`agent/memory_runtime.py::evaluate_user_text()` 委托 `DeterministicMemoryPolicy.decide()`，产出 retain/forget/update/no-op/block 等 decision。
- confirmation：retain/update 等需要用户确认时，`core.chat()` 写入 `state.task.pending_user_input_request`，通过 `TransitionEvent.MEMORY_CONFIRMATION_REQUIRED` 和 checkpoint save 进入 awaiting user input。
- confirmation reply：`agent/confirmation/memory.py` 分流到 `agent/memory_interaction.py::handle_memory_confirmation_reply()`，调用 `MemoryRuntime.resolve_confirmation(..., direct_write=False)`。
- store write：确认通过后，如果有 dispatcher，`handle_memory_confirmation_reply()` dispatch `RuntimeActionType.MEMORY_PROPOSE`，由 `agent/runtime_integration/memory_retain.py::MemoryRetainHandler` 写入共享 store。
- list/view：`show memories` / `list memories` 等 CLI read-only 命令已通过 `agent/runtime_integration/cli_handlers.py` 和 dispatcher 路径读取 records。
- delete/forget：`forget memory` / `忘记` 路径存在，`agent/runtime_integration/memory_forget.py` 可通过 dispatcher 处理删除。
- update/correct：policy 和 confirmation 表单有 update/edit 概念，但生产 UX、evidence 和测试闭环弱于 retain/delete，需要 v0 收口。
- prompt injection：`agent/core.py::refresh_runtime_system_prompt()` dispatch `RuntimeActionType.MEMORY_RECALL` 后，`agent/runtime_integration/memory_recall.py` 生成 `prompt_section`，最终由 `agent/prompt_builder.py` / `agent/memory.py::build_memory_section()` 注入 system prompt。
- 当前 evidence/log：`MEMORY_PROPOSE`、`MEMORY_RECALL`、`MEMORY_FORGET` 等 RuntimeAction 有 action_log evidence；但 `MemoryRuntime._log` 默认 `_noop_event_logger`，confirmation requested/approved/rejected、direct fallback recall、MemoryRuntime lifecycle 事件没有统一进入 `evidence_recorder` / `events.jsonl` / `log_viewer`。

需要实现前复核：

- `agent/core.py::refresh_runtime_system_prompt()` 在 `dispatcher is None` 时仍会直接调用 `_mem_rt.snapshot_for_prompt()`。当前 `chat()` 调用传入的是 `runtime_action_dispatcher` 参数，而不是一定传入内部 `_phase1_dispatcher`；实现前需要确认默认生产调用是否仍可能走 direct recall fallback。
- `forget/update` 的用户可见语义与 confirmation 要求需要对照现有测试复核，避免把 CLI convenience 和模型可见 runtime capability 混为一谈。

### 2. Agent-proposed memory

当前 agent-proposed memory 具备 foundation，但不是 v0 主链路能力。

- suggestion engine：`agent/memory_suggestions.py::DeterministicSuggestionEngine` 能基于文本产生 candidate。
- runtime hook：`MemoryRuntime._try_suggestions()` 能在 policy no-op 后尝试生成 agent-suggested confirmation request。
- 默认启用：`agent/memory_runtime.py::create_memory_runtime()` 没有默认注入 `suggestion_engine`，所以主 runtime 默认不主动发现。
- turn-end proposal：`agent/runtime_integration/memory_retain.py` / `MemoryTurnEndProposalHandler` 与 `loop.py` turn-end hook 存在 proposal 相关路径，但当前主要是 pending/review 或 confirmed proposal executor，并不等同于“agent 主动提醒用户是否保存”的完整产品闭环。
- proposal→approve/reject：confirmation 基础设施支持 approve/reject，reject 后不写 store；但默认 proposal surfacing、用户提醒、过期、重复抑制、敏感类别治理、evidence taxonomy 都不完整。
- 当前 evidence/log：部分 proposal execution 进入 dispatcher action_log；proposal created/surfaced/rejected/expired 没有统一 memory.* lifecycle taxonomy。

v0 决策：agent-proposed memory 不默认启用；如保留 proposal queue，必须可见化或明确标记为 deferred，并为 skipped/deferred 写入 evidence。

### 3. Hidden / implicit memory

当前存在非 MemoryStore 的隐式记忆/上下文状态，主要是 `working_summary`。

- compression：`agent/memory.py::compress_history()` 会压缩旧消息，并在 prompt 中要求保留用户偏好、当前进度等摘要信息。
- state：`agent/state.py::MemoryState.working_summary` 保存摘要。
- checkpoint：`agent/checkpoint.py` 保存 `state.memory`，因此 `working_summary` 会跟随 checkpoint 进入恢复路径。
- prompt/resume 影响：`agent/context_builder.py::build_planning_messages()` 和 `build_execution_messages()` 会把 `state.memory.working_summary` 注入模型 messages；这会影响后续推理。
- 用户控制：`show memories` / MemoryStore list 不展示 `working_summary`；delete/update/correct memory 命令也不显式管理它。
- governance：`working_summary` 不经过 MemoryStore policy、confirmation、source_type、retention、view/delete/update/consent。
- 当前 evidence/log：summary 创建、更新、恢复、清理没有统一 `memory.summary_*` evidence；checkpoint save 可能有 checkpoint evidence，但不能替代 Memory scratchpad governance evidence。

v0 决策：`working_summary` 必须被定义为 session/checkpoint scratchpad，不是 long-term user memory。它不能冒充用户记忆，不能进入 MemoryStore，也不能绕过 redaction/retention/clear owner/evidence。

### 4. MemoryStore / MemoryRuntime / MemoryState

三者当前职责不同，但 source-of-truth 需要收口。

- `MemoryRuntime`：`agent/memory_runtime.py` 中的协调层，负责 policy evaluation、pending confirmation、confirmation resolution、snapshot_for_prompt、list/remove。
- `MemoryStore`：`agent/memory_store.py` 和 `agent/memory_fs_store.py` 中的 records 存储抽象和 backend，是 explicit long-term memory records 的事实来源候选。
- `MemoryState`：`agent/state.py` 中的 runtime/session 状态，包含 `working_summary`、`long_term_notes`、`checkpoint_data`、`session_id` 等字段。
- checkpoint：保存 `state.memory`，但不保存 MemoryStore 全量 records。
- split-brain 风险：MemoryStore records、checkpoint 中的 `state.memory`、`working_summary` 可能在 resume 后不一致；尤其 InMemory backend 跨进程丢失 records 时，checkpoint 仍可能携带 summary/pending state。

v0 决策：MemoryStore 是 long-term explicit memory source-of-truth；Checkpoint 是 task/session recovery source-of-truth。Checkpoint 只能保存 memory reference metadata，不应成为第二个 long-term memory store。

### 5. Backend

当前 backend 形态存在语义混乱。

- `agent/memory_store.py::InMemoryMemoryStore`：注释中定位为 fake/local/test-only 风格，但 `create_memory_runtime()` 默认使用它。
- `agent/memory_fs_store.py::FilesystemMemoryStore`：真实 filesystem-native backend，`.md` files 是 source of truth，`_meta/index.json` 是派生索引；默认 root 是 `~/.my-first-agent/memory`。
- duplicate/skeleton class：`agent/memory_store.py::FilesystemMemoryStore` 继承 `InMemoryMemoryStore`，只是 filesystem backend 骨架标记；它与真实 filesystem store 同名不同义。
- env selection：`MEMORY_STORE_BACKEND=memory|in_memory|inmemory|filesystem|memory_fs|fs`；`MEMORY_STORE_ROOT` / `MEMORY_ROOT` 控制 filesystem root。
- HOME 默认：未设置 root 时 filesystem backend 写 `Path.home() / ".my-first-agent" / "memory"`。审计测试已在 sandbox 中因 lock 写 HOME 失败。

v0 决策：backend/root policy 必须明确。测试不得写真实 HOME；production durable memory 是否默认 filesystem 或要求用户配置，必须有用户可见语义和 evidence warning。

### 6. Evidence/log

当前项目已有内置 evidence/log 主链路，Memory 必须接入它，而不是另起一套。

- dispatcher/action_log：`agent/runtime_integration/dispatcher.py` 维护 `RuntimeActionEvent` action_log，并可 flush 到 `EventLogWriter`。
- events.jsonl：`agent/event_log.py` 和 `agent/evidence_recorder.py` 支持 per-session `events.jsonl`。
- evidence_recorder：`agent/evidence_recorder.py::record_evidence()` 是业务代码写入 evidence envelope 的公共入口；代码注释明确业务代码不应直接写 `agent_log.jsonl` / `events.jsonl`。
- safe_summary：tool、checkpoint、MCP、Skill 等已有 safe_summary 模式。
- log_viewer：`agent/log_viewer.py` 优先读 per-session `events.jsonl` 并展示摘要。
- 已有 memory action：`RuntimeActionType.MEMORY_TURN_END_PROPOSAL`、`MEMORY_PROPOSE`、`MEMORY_RECALL`、`MEMORY_CONSOLIDATE`、`MEMORY_FORGET`、`SUBAGENT_CHILD_MEMORY_REQUEST`。
- 当前缺口：`MemoryRuntime._log` 默认 noop；`evaluate_user_text()`、confirmation requested/approved/rejected、policy blocked、sensitive blocked、summary created/updated/cleared、backend selected/warning、reference mismatch、default direct recall fallback 没有统一内置 evidence/log 保障。
- 需要实现前复核：哪些 RuntimeActionEvent 当前会被 flush 到 `events.jsonl`，哪些只留在 in-memory action_log；log_viewer 对 memory action 的分类显示是否稳定。

### 7. Cross-subsystem boundary

Memory 已触及 Skill、SubAgent、MCP、ToolRuntimeMediator、Checkpoint/session，但边界还没有 v0 级别闭环。

- Skill：`agent/skill_system/memory_boundary.py` 能基于 descriptor 的 `memory_scope` 判定 read/propose，但 active skill 的 `memory_scope` 未明显全面约束 production recall injection/write。
- SubAgent：`agent/subagent_system/memory_boundary.py` 和 `agent/tool_runtime_mediator.py::mediate_child_memory_request()` 存在；二轮审计已确认 child memory request 当前可 direct write MemoryStore，v0 必须锁死。
- MCP：未见 MCP tool result auto-memory production path；v0 必须保持 out-of-scope。
- ToolRuntimeMediator：普通 model-visible tools 走 ToolRuntimeMediator；Memory 当前主要是 runtime action + CLI meta-command，不是完整 model-visible memory tool。
- Checkpoint/session：pending confirmation 和 `state.memory` 会 checkpoint；MemoryStore records 不由 checkpoint 恢复，存在 backend-dependent resume consistency 风险。

### 8. Child/Sub-agent memory request confirmed direct-write risk

Second-round audits confirmed that `agent/tool_runtime_mediator.py::mediate_child_memory_request()` currently directly writes MemoryStore when `memory_scope != "none"` and store is available.

Confirmed current behavior:

- constructs `MemoryOperationIntent`
- calls `self._store.apply_operation_intent(intent, audit)`
- uses `MemoryConfirmationStatus.AUTO_RETAINED`
- uses `MemoryConfirmationChoice.ACCEPT`
- does not require parent/user confirmation
- `_dispatch_child_memory_evidence()` currently includes raw key / `value_preview` style payload fields

U0 must lock this confirmed behavior with characterization tests before any production behavior changes. U8 must remove this direct-write behavior for Memory v0.

## C. Non-Goals

- 不做 Sub-agent memory write；这不只是 out-of-scope，任何现有 child/sub-agent direct MemoryStore write path 都必须在 v0 被 locked down。
- 不做 MCP tool result auto-memory；v0 必须有测试证明 MCP tool result 不会自动写 MemoryStore。
- 不做 hidden long-term user profiling。
- 不做 vector/embedding/RAG。
- 不做 L2/Emergence 真实接入。
- 不做 external MemoryProvider。
- 不做 broad memory consolidation/extraction pipeline。
- 不做 bulk forget。
- 不做 recursive prompt injection full solution；v0 只要求已有基础防护和 future hook。
- 不重开 Runtime State Transition。
- 不重构整个 `agent/core.py`。
- 不创建第二套 Memory runtime。
- 不让 model 直接 commit memory without user confirmation。
- 不创建独立于现有 evidence/log 体系之外的 Memory 专用日志系统。
- 不允许任何子系统绕过 Memory governance、built-in evidence/log 和 user confirmation 直接写长期 MemoryStore。

## D. Architecture Decisions

### D1. Memory v0 durability semantics

Decision：

- Memory v0 is durable explicit user memory。
- Durable backend is required for Memory v0 closeout。
- Decision: Memory v0 requires an explicit durable root for filesystem persistence.
- Production durable path must be `FilesystemMemoryStore` with explicit safe root，或 explicitly configured durable backend。
- The system must not silently write long-term memory to HOME。
- Filesystem durable backend must satisfy one of:
  - user explicitly configured `MEMORY_STORE_ROOT`
  - user confirmed the root through user-visible first-run setup / setup command
  - tests explicitly use tmp root
- `InMemoryMemoryStore` is allowed only as test/session fallback。
- If `InMemoryMemoryStore` is active and user stores explicit memory, system must emit user-visible warning and `memory.backend_warning` evidence。
- If no durable root is configured, runtime may use InMemory only as session/test fallback with user-visible warning and `memory.backend_warning` evidence。
- A build/config that only uses InMemory cannot claim durable Memory v0 readiness。

Rationale：

- 用户说“记住”时，产品语义天然接近长期记忆；静默使用 process-local store 会导致重启后丢失，破坏信任。
- 当前 `create_memory_runtime()` 默认使用 `InMemoryMemoryStore()`，而代码注释和审计都显示它更像 fake/local/test fallback。
- durable semantics 不等于默认无提示写 HOME；durability requires explicit root configuration or user-visible setup confirmation, plus permissions、用户可见 warning 和 evidence。

Alternatives：

- Alternative A：Memory v0 定义为 session-only。
  - Rejected：这会显著降低“记住”的产品语义，并要求每次用户触发 explicit memory 时都明确告知非持久；它不能作为 v0 的默认长期方向。
- Alternative B：立即默认 filesystem，并写 `~/.my-first-agent/memory`。
  - Rejected：当前 sandbox 测试已经暴露 HOME write 问题；在 root policy、permissions、用户授权、redaction 和 evidence warning 未收口前不应默认写真实 HOME。
- Alternative C：保留当前 InMemory default 并声称 durable v0 ready。
  - Rejected：这是 silent data loss 风险，也是 Memory v0 readiness blocker。InMemory 可以作为 fallback，但不能作为 durable readiness 证据。

### D2. MemoryStore vs Checkpoint source-of-truth

Decision：

- MemoryStore 是 long-term explicit memory source-of-truth。
- Checkpoint 是 task/session recovery source-of-truth。
- Checkpoint 不应成为第二个 long-term memory store。
- Checkpoint 应保存 memory namespace/root/backend/revision/last_seen_ids 或同等 reference metadata，而不是盲目保存完整长期 memory records。
- Resume 后如果 reference/revision 不一致，必须产生 `memory.reference_mismatch` 或等价 warning evidence，并采取明确 fallback。
- 如果当前实现先不做 full store revision，v0 至少要文档化并测试最小一致性行为：resume 后不会静默把 checkpoint summary 当成 MemoryStore records，也不会无证据丢失 recall。

Rationale：

- Checkpoint 保存全量长期 records 会把 task recovery 与长期隐私数据绑在一起，增加泄露和 split-brain 风险。
- MemoryStore 单独作为长期记录源更符合 delete/update/correct、retention、backend migration 的治理边界。
- checkpoint reference metadata 足以帮助 resume 检测“恢复的 runtime 与 memory store 是否一致”，不会把 checkpoint 变成第二个 store。

Alternatives：

- Alternative A：保存完整 MemoryStore snapshot 到 checkpoint。
  - Rejected：会复制 raw memory content，扩大敏感数据面；delete/correction 后旧 checkpoint 仍残留 records，治理复杂。
- Alternative B：Checkpoint 不保存任何 memory reference。
  - Rejected：resume 后 store missing、backend 切换、namespace mismatch 都会静默发生，无法审计 recall divergence。
- Alternative C：Checkpoint 只保存 rendered prompt section。
  - Rejected：rendered prompt section 是模型输入材料，不是 source-of-truth；保存它会引入 stale/sensitive prompt leakage。

### D3. working_summary classification

Decision：

- `working_summary` 是 session/checkpoint scratchpad，不是 long-term user memory。
- 它不能被当作用户长期偏好，不得进入 MemoryStore，不得通过 `show memories` 展示为用户记忆。
- 它必须有 redaction、retention、clear/reset owner。
- 如果它会影响 resume prompt 或 future model messages，创建、更新、清理、恢复必须记录 `memory.summary_created`、`memory.summary_updated`、`memory.summary_cleared`、`memory.summary_redacted` 或等价 evidence。
- `delete memory` / `forget memory` 默认只操作 explicit MemoryStore records；不删除 `working_summary`。如果后续提供 internal state inspector 或 reset session/scratchpad 命令，再单独管理 `working_summary`。
- `working_summary` 应在 session reset、task reset 中按明确 owner 清理，或在 checkpoint retention 过期时清理；具体清理触发需要实现前复核当前 reset/checkpoint ownership。

Rationale：

- `working_summary` 已经影响 prompt/resume，但不经过 user consent 和 MemoryStore governance。把它命名为 scratchpad 能避免隐藏式长期记忆和用户可见 memory 混淆。
- 它对长对话协议合规和上下文压缩有价值，不应简单删除；但必须边界清楚、可审计、可清理。

Alternatives：

- Alternative A：把 `working_summary` 纳入 MemoryStore 并显示给用户。
  - Rejected：summary 是模型生成的上下文压缩结果，不是用户确认的长期事实；直接放进 MemoryStore 会污染 explicit memory。
- Alternative B：完全删除 compression summary。
  - Rejected：会破坏长上下文运行能力，并可能重开 runtime context 架构。
- Alternative C：继续隐式保存，不做 evidence。
  - Rejected：这是 hidden memory governance 风险，阻塞 Memory v0。

### D4. Evidence / log taxonomy

Decision：

- Memory v0 必须统一接入现有内置 evidence/log 体系：`RuntimeActionDispatcher` / `RuntimeActionEvent`、`action_log`、`evidence_recorder`、`events.jsonl`、`safe_summary`、`log_viewer`，以及适用时的 run summary。
- Memory 子系统不得自己另起一套不可统一检索的日志。
- `MemoryRuntime._log` 不得在 production 默认 noop；它必须被接到 built-in evidence helper，或者被替换为 dispatcher/evidence_recorder 的统一 adapter。
- Memory recall/write/delete/update/proposal/confirmation/summary/backend/reference 在 production 路径不得无 evidence。
- 日志中禁止写 raw user prompt、raw assistant prompt、raw memory body、raw secret、raw file content、raw tool result、raw SKILL.md body、raw child/sub-agent payload、raw record_id/raw memory_id。

Required event taxonomy：

Read / recall：

- `memory.recall.requested`
- `memory.recall.completed`
- `memory.recall.skipped`
- `memory.recall.failed`

Proposal：

- `memory.proposed`
- `memory.proposal_skipped`
- `memory.proposal_deferred`
- `memory.proposal_surfaced`
- `memory.proposal_expired`
- `memory.proposal_failed`

Confirmation / governance：

- `memory.approved`
- `memory.rejected`
- `memory.policy_blocked`
- `memory.sensitive_blocked`
- `memory.redacted`

Store mutation：

- `memory.committed`
- `memory.updated`
- `memory.deleted`
- `memory.delete_requested`
- `memory.commit_failed`
- `memory.update_failed`
- `memory.delete_failed`

Child/sub-agent：

- `memory.child_request_received`
- `memory.child_request_deferred`
- `memory.child_request_rejected`
- `memory.child_proposal_created` is reserved for a future proposal-only Sub-agent memory phase, not emitted by v0 rejected/deferred evidence-only lockdown.

Checkpoint / backend：

- `memory.backend_selected`
- `memory.backend_warning`
- `memory.reference_saved`
- `memory.reference_checked`
- `memory.reference_mismatch`
- `memory.restored`
- `memory.restore_skipped`

Hidden/scratchpad：

- `memory.summary_created`
- `memory.summary_updated`
- `memory.summary_cleared`
- `memory.summary_redacted`
- `memory.summary_restored`

Safe fields：

- `event_type`
- `memory_event_version`
- `memory_id_hash` 或 redacted `memory_id`
- `source_type`: `explicit_user` | `agent_proposed` | `hidden_summary` | `system` | `tool_result` | `child_agent` | `subagent`
- `operation`: `recall` | `propose` | `approve` | `reject` | `commit` | `update` | `delete` | `summarize` | `restore`
- `policy_path`
- `decision`: `allowed` | `blocked` | `pending` | `failed` | `skipped`
- `reason`
- `backend`: `in_memory` | `filesystem` | `unknown`
- `namespace` / `session_id` / `run_id`，按项目现有规范脱敏或摘要
- `count`
- `redacted`: `true` / `false`
- `sensitive_category_detected`: `true` / `false`
- `prompt_injection_flagged`: `true` / `false`
- `checkpoint_ref` / `store_revision`，如适用

ID policy：

- evidence must use `memory_id_hash` or redacted id。
- raw `record_id` / raw `memory_id` is forbidden in delete/update/list/forget/recall evidence。
- `MemoryForgetHandler`、delete、update、list、recall events 必须覆盖 id hashing/redaction tests。
- 可用于用户界面的 short id 不得原样进入 durable evidence；需要 hash、redacted short id，或明确标为 non-sensitive display-only 且不进入 events/log evidence。

Forbidden fields：

- raw memory text
- raw user prompt
- raw assistant prompt
- raw SKILL.md body
- raw tool result content
- raw file content
- raw child/sub-agent payload
- secrets / API keys / credentials
- raw record_id / raw memory_id
- full filesystem path，如果可能泄露用户信息；可记录 `path_kind` 或 redacted path hash

log_viewer display：

- 展示 memory recall count、committed/deleted/update summary、proposal pending/rejected/approved、backend warning、summary/scratchpad events。
- 不展示 raw memory body、raw prompt、raw secret、raw filesystem path。
- Memory events 应与 Tool/MCP/Skill/Checkpoint 的现有 evidence 风格一致，避免用户需要查第二套日志。

Required tests：

- recall/propose/approve/reject/commit/delete/update/failed 都有 evidence。
- exact event-name assertions for `memory.proposal_skipped`、`memory.proposal_deferred`、`memory.update_failed`、`memory.child_request_received`、`memory.child_request_deferred`、`memory.child_request_rejected`。
- v0 child lockdown tests must assert `memory.child_proposal_created` is not emitted.
- `events.jsonl` contains safe memory event。
- `action_log` contains lifecycle trace。
- `log_viewer` can parse/display stable memory summary。
- forbidden-field matrix across `events.jsonl`、`action_log`、`log_viewer`、`safe_summary`、run summary if applicable。
- no raw memory text、raw user prompt、raw assistant prompt、raw tool result、raw file content、raw child/sub-agent payload、raw record_id/raw memory_id、secret/API key/credential、full filesystem path leaks to logs。
- production direct recall path without evidence is rejected by architecture test。

Rationale：

- Memory 会影响未来 prompt 和 agent 行为；没有 evidence 的 recall/write/delete 等同于不可审计的行为变化。
- 项目已有 evidence_recorder、RuntimeActionEvent、events.jsonl 和 log_viewer，不应为 Memory 新建平行日志系统。

Alternatives：

- Alternative A：只依赖 `RuntimeActionEvent` action_log。
  - Rejected：action_log 是 route receipt，且可能只在内存中；无法覆盖 MemoryRuntime lifecycle、confirmation、backend warning、summary scratchpad，也不足以证明 durable evidence。
- Alternative B：只让 MemoryRuntime `_log` 写私有日志。
  - Rejected：形成第二套日志，log_viewer/run summary/evidence_recorder 不可统一检索。
- Alternative C：只记录 store mutation，不记录 recall。
  - Rejected：recall 会影响 prompt，是 Memory v0 的核心审计点。

### D5. Model-visible memory tools

Decision：

- Memory v0 includes minimal model-visible request tools。
- Required tools：
  - `MEMORY_REMEMBER_REQUEST` 或 `MEMORY_PROPOSE`：模型只能提出候选，不能直接写长期 store。
  - `MEMORY_LIST` 或 `MEMORY_RECALL_VIEW`：查看用户可见 memory。
  - `MEMORY_FORGET_REQUEST`：模型可提出删除请求，最终需用户确认。
  - optional `MEMORY_UPDATE_REQUEST`：模型可提出更新/纠正请求，最终需用户确认。
- 不允许 `MEMORY_COMMIT` tool。
- model cannot directly commit long-term memory。
- all commit/delete/update operations require user confirmation。
- `MEMORY_UPDATE_REQUEST` tool is optional for v0, but user-facing update/correction capability remains required through explicit user command or existing user-facing path, with `memory.updated` / `memory.update_failed` evidence.
- 所有工具必须注册 `TOOL_REGISTRY`。
- 所有 model-visible memory tools 必须走 `ToolRuntimeMediator`，再进入 RuntimeActionDispatcher/policy/governance。
- 每次工具调用必须产生 `TOOL_GATE` / `TOOL_INVOKE` / `TOOL_RESULT` evidence plus memory.* evidence。

Rationale：

- 当前 Memory 更像 CLI meta-command + runtime action，不是模型可见的一等 capability。
- 模型能“建议记住/删除/更新”，但最终 commit 必须由用户 confirmation 或明确 governance 决策完成。
- 把 request-only tools 纳入 v0 可以让 Memory 成为真实 runtime capability，同时避免 direct commit 的 privacy/user agency 风险。

Alternatives：

- Alternative A：不做 model-visible tools，v0 只保留用户 explicit prefix。
  - Rejected：这会让 Memory v0 仍主要停留在 CLI/meta-command 和 explicit prefix 层，无法声称具备最小 model-visible runtime capability。
- Alternative B：给模型直接 `MEMORY_COMMIT`。
  - Rejected：违反 no silent auto-write 和 user agency。
- Alternative C：让 memory tools 绕过 ToolRuntimeMediator 直接调用 MemoryRuntime。
  - Rejected：会创建第二条 tool execution/governance/evidence 路径。

### D6. Agent-proposed memory scope

Decision：

- v0 不默认启用 agent-proposed proactive discovery。
- v0 只保证 explicit user memory 的闭环和证据。
- 如果保留 proposal queue 或 turn-end proposal handler，它必须做到二选一：
  - 用户可见：产生轻量提醒，例如“有一条待确认记忆”，并可 approve/reject。
  - 明确 skipped/deferred：不展示、不写 store，并记录 `memory.proposal_skipped` 或 `memory.proposal_deferred` safe evidence。
- proposal created / skipped / deferred / surfaced / approved / rejected / expired 必须有 evidence。

Rationale：

- Agent-proposed memory 的隐私和误记风险比 explicit memory 高，当前默认 runtime 未启用 suggestion engine。
- 先收口 explicit memory 能降低 v0 blast radius。

Alternatives：

- Alternative A：v0 默认启用 suggestion engine。
  - Rejected：敏感类别治理、duplicate/debounce、proposal UX、evidence 和 reject no-write 需要先补齐。
- Alternative B：删除所有 proposal foundation。
  - Rejected：现有代码和测试已覆盖部分 foundation；更好的 v0 选择是标记 deferred 并加边界/evidence。

### D7. Backend/root policy

Decision：

- production filesystem root resolution 必须集中到一个函数或明确 adapter，不能散落在 backend constructor 和 tests 中。
- tests 必须显式使用 tmp root，禁止写真实 HOME。
- filesystem persistence requires explicit durable root: user-configured `MEMORY_STORE_ROOT` or user-visible first-run setup / setup command confirmation.
- filesystem backend must not silently write long-term memory to HOME.
- 如果启用 filesystem，路径必须可配置、可审计、用户可理解，并产生 `memory.backend_selected` evidence。
- 未配置 durable root 时，不得 silent fallback 成“看似 durable”的 filesystem；只能使用 InMemory test/session fallback，并产生 user-visible warning + `memory.backend_warning` evidence。
- 如果默认 InMemory，第一次存储 explicit memory 时必须提示非持久，并产生 `memory.backend_warning` evidence。
- 真实 production filesystem class 只能有一个清晰 export；`agent/memory_store.py::FilesystemMemoryStore` skeleton 必须重命名、隔离或从 production export 移除，避免 import 错类。
- filesystem backend 当前 lock/atomic write/corruption recovery 能力要在实现前复核；v0 至少要求不静默失败、不写 HOME 测试路径、index 可重建、失败有 safe evidence。

Rationale：

- 当前 backend selection 与 durability semantics 直接影响用户信任和测试稳定性。
- 同名 `FilesystemMemoryStore` 会造成 fake/real 混淆，后续实现容易引入错误 import。

Alternatives：

- Alternative A：继续允许 tests 使用默认 HOME root。
  - Rejected：当前已失败，且会污染真实用户路径。
- Alternative B：保持两个同名 filesystem store。
  - Rejected：阻塞 source-of-truth closeout。
- Alternative C：filesystem 初始化失败时自动降级 InMemory。
  - Rejected：会静默丢失 durability；只能 fail closed 或用户可见 warning。

### D8. Skill/SubAgent/MCP boundary

Decision：

- Skill `memory_scope=none` suppress recall injection is mandatory for Memory v0 closeout。
- Skill write/propose enforcement may be deferred, but recall suppression cannot be deferred。
- Skill and SubAgent memory_scope value sets are different and must not be mixed.
- Skill memory_scope values are `none` / `read_context` / `propose_memory`.
- SubAgent memory_scope values are `none` / `read_context` / `propose`.
- Skill `memory_scope=read_context` allows recall injection.
- Skill `memory_scope=propose_memory` does not allow direct MemoryStore write.
- Skill `memory_scope=read_context` / `propose_memory` 的具体读写范围必须通过 MemoryRuntime/dispatcher 传递，而不是由 skill 直接访问 store。
- While Skill write/propose enforcement is deferred, Skill must not have any direct MemoryStore write path. Any future Skill memory proposal must route through MemoryRuntime governance, user confirmation, and memory.* evidence. Deferring Skill write/propose enforcement does not allow Skill to bypass MemoryStore policy。
- Sub-agent / child-agent direct memory write is forbidden in v0。
- SubAgent `memory_scope=propose` must be rejected/deferred evidence-only in v0 and must not direct commit.
- Direct calls to the mediator with `read` / `write` / unknown non-none values must also be defended by U8 lockdown and must not write MemoryStore.
- Existing child memory request path is confirmed to direct-write MemoryStore; U0 must characterize it before behavior changes。
- U8 must convert child/sub-agent memory requests to rejected/deferred evidence-only for Memory v0。
- Proposal-only + parent/user confirmation is deferred to a future Sub-agent memory phase unless separately approved。
- `SUBAGENT_CHILD_MEMORY_REQUEST` 不能被解释为 child memory write support；无 handler 或只有 evidence 都必须明确标记为 deferred/blocked。
- MCP tool result auto-memory is out-of-scope。
- MCP tool result must not automatically write MemoryStore。
- v0 必须有测试证明 MCP auto-memory remains disabled。
- Memory tool 不得绕过 `ToolRuntimeMediator`。
- boundary allow/deny/defer 必须有 `memory.policy_blocked`、`memory.child_request_deferred`、`memory.child_request_rejected` 或等价 evidence，且不泄露 raw memory、raw child payload、raw record_id。

Rationale：

- Skill Lifecycle Cleanup 已进入 main，Memory v0 必须尊重 active skill boundary，避免 recall 注入和 skill scope 冲突。
- SubAgent/MCP 会放大 memory governance 风险，v0 不应同时扩写能力。
- 二轮审计已确认 `mediate_child_memory_request()` currently direct-writes store；U0 must preserve that baseline in characterization tests before U8 changes behavior。
- MCP tool result 可能含外部敏感数据；任何未来 MCP memory proposal 都必须 proposal + user confirmation + evidence。

Alternatives：

- Alternative A：v0 完全不处理 Skill memory_scope。
  - Rejected：Memory recall 已经进 prompt，active skill prompt 同时存在时不约束会造成边界污染。
- Alternative B：v0 完整支持 Sub-agent memory write。
  - Rejected：超出 cleanup 范围，且需要 supervisor approval、delegated scope、child evidence 链。
- Alternative C：MCP tool result 自动记忆。
  - Rejected：外部工具结果可能包含敏感数据，必须 deferred。
- Alternative D：保留 child memory request direct store write，但标记为 parent-mediated。
  - Rejected：parent-mediated 不等于 user-confirmed，也不等于 Memory governance；v0 禁止 child/sub-agent direct write MemoryStore。

## E. Proposed v0 Scope

### Must Fix for v0 closeout

1. Default recall path uses dispatcher/evidence, no production silent direct recall.
2. Memory evidence/log taxonomy wired into existing built-in evidence/log system.
3. Durable explicit user memory semantics enforced; InMemory-only config cannot claim durable v0 readiness.
4. MemoryStore/checkpoint source-of-truth decision implemented or protected by reference metadata/warning.
5. `working_summary` classified and bounded as scratchpad.
6. Filesystem root policy fixed; tests use tmp root.
7. Duplicate `FilesystemMemoryStore` class resolved or isolated.
8. Memory lifecycle events wired for recall/propose/approve/reject/commit/delete/update/failure/backend/summary/child request.
9. Minimal model-visible request-only memory tools implemented and blocked from direct commit.
10. Skill `memory_scope=none` recall injection suppression implemented and tested.
11. Child/sub-agent memory direct write lockdown implemented and tested.
12. MCP tool result auto-memory disabled test added.
13. Exact memory evidence taxonomy includes `memory.proposal_skipped`, `memory.proposal_deferred`, `memory.update_failed`, and `memory.child_request_*`.
14. ID hashing/redaction enforced for all memory evidence; delete/update/list/forget/recall must not log raw record_id/raw memory_id.
15. Forbidden-field test matrix covers `events.jsonl`, `action_log`, `log_viewer`, `safe_summary`, and run summary if applicable.
16. `log_viewer` / `events.jsonl` / `action_log` tests prove Memory operations are visible and safe.

### Should Fix

- turn-end proposal user-visible hint.
- list/update/delete UX polish.
- redaction behavior clarified: marker vs destructive removal.
- docs update for user-facing durability and memory scope semantics.
- run summary memory counters.
- `log_viewer` labels for memory events.

### Defer

- agent-proposed memory default enablement.
- L2/Emergence production.
- external MemoryProvider.
- Sub-agent memory write beyond v0 lockdown/proposal-only guard.
- MCP auto memory beyond disabled-state tests.
- vector/RAG.
- bulk forget.
- recursive prompt injection full defense.

## F. Implementation Units

### U0. Inventory and baseline tests

Goal：

- Lock current Memory behavior before changing implementation, especially the confirmed child/sub-agent direct-write behavior.

Files：

- `agent/memory_runtime.py`
- `agent/memory_store.py`
- `agent/memory_fs_store.py`
- `agent/core.py`
- `agent/tool_runtime_mediator.py`
- `agent/runtime_integration/memory_recall.py`
- `agent/runtime_integration/memory_retain.py`
- `agent/runtime_integration/memory_forget.py`
- `agent/context_builder.py`
- `agent/state.py`
- `tests/runtime_integration/`
- `tests/test_memory_*.py`

Approach：

- Add characterization tests for direct recall fallback, `_log` noop, filesystem HOME root, duplicate filesystem class, `working_summary` hidden summary, and current memory test baseline.
- U0 must characterize the confirmed current child/sub-agent memory behavior:
  - `memory_scope="none"` is rejected and does not write store
  - `memory_scope="propose"` currently writes MemoryStore
  - if directly passed, `memory_scope="read"` / `"read_context"` / `"write"` / unknown currently also write MemoryStore
  - current write uses `AUTO_RETAINED` + `ACCEPT`
  - no parent/user confirmation is required
  - current child memory evidence includes raw key and/or `value_preview`-like child payload fields
- Add MCP baseline test proving MCP tool result does not automatically write MemoryStore.
- No production behavior change in U0.

Test scenarios：

- Current default `chat()` path either uses dispatcher recall or exposes a failing test proving direct fallback risk.
- `MemoryRuntime._log` with default factory does not write built-in evidence, captured as a baseline gap.
- Filesystem backend without tmp root attempts HOME root, captured as a failing/gap test if still true.
- `working_summary` is injected into model messages but not shown in `show memories`.
- `mediate_child_memory_request()` confirmed store-write behavior is proven for every supported/unknown memory_scope.
- MCP tool result does not mutate MemoryStore unless explicit memory request/confirmation exists.

Rollback：

- Revert only new characterization tests. No production behavior to roll back.

### U1. Evidence-first recall path

Goal：

- Ensure default pre-loop memory recall uses dispatcher/evidence. Direct snapshot path must be test/bootstrap-only or explicitly tagged.

Files：

- `agent/core.py`
- `agent/runtime_integration/memory_recall.py`
- `agent/runtime_integration/phase1_hook.py`
- `tests/runtime_integration/test_memory_recall_*.py`
- `tests/test_architecture_boundaries.py`

Approach：

- Make production `refresh_runtime_system_prompt()` receive the actual phase1 dispatcher when available.
- Keep direct `_mem_rt.snapshot_for_prompt()` only for module init/test/bootstrap with explicit source tag and no runtime_e2e claim.
- Add architecture test preventing production direct recall without evidence.

Test scenarios：

- `core.chat()` default path emits `RuntimeActionType.MEMORY_RECALL` in `action_log`.
- `events.jsonl` contains safe recall event after flush.
- prompt receives memory section only after dispatcher recall.
- direct fallback is either unreachable in production test or tagged as non-production/no-evidence bootstrap.
- raw memory body and raw record_id are not present in safe evidence.

Rollback：

- Revert dispatcher handoff changes and architecture test. Since this unit only changes recall routing, rollback should restore previous prompt construction without touching store records.

### U2a. Memory evidence schema and safe_summary helpers

Goal：

- Define Memory event taxonomy, safe fields, forbidden fields, id hashing/redaction, and safe_summary helpers before wiring lifecycle code.

Files：

- `agent/runtime_integration/evidence.py`
- `agent/runtime_integration/schema.py`
- `agent/evidence_recorder.py`
- `tests/runtime_integration/test_memory_evidence_schema*.py`

Approach：

- Define memory event version and event names from D4, including proposal skipped/deferred, update_failed, child_request_* and summary restore semantics.
- Define shared safe_summary builder for Memory events.
- Add id hashing/redaction helper for memory_id/record_id.
- Add forbidden-field matrix helper that can be reused by runtime/log_viewer tests.

Test scenarios：

- safe fields include source_type, operation, decision, backend, redacted flags, and hashed/redacted memory id.
- forbidden fields are rejected or redacted before event construction.
- raw record_id/raw memory_id never appears in delete/update/list/forget/recall event payload.
- exact event-name constants match taxonomy.

Rollback：

- Revert schema/helper additions. No runtime behavior or store records should change in this unit.

### U2b. Memory lifecycle runtime evidence wiring

Goal：

- Wire Memory runtime lifecycle events into built-in evidence/log flow without creating a Memory-only log system.

Files：

- `agent/memory_runtime.py`
- `agent/memory_interaction.py`
- `agent/runtime_integration/memory_recall.py`
- `agent/runtime_integration/memory_retain.py`
- `agent/runtime_integration/memory_forget.py`
- `agent/runtime_integration/evidence.py`
- `agent/display_events.py`
- `tests/runtime_integration/test_memory_lifecycle_evidence*.py`

Approach：

- Replace or adapt production `MemoryRuntime._log` so it emits built-in evidence through approved helpers.
- Wire recall/propose/approve/reject/commit/delete/update/failure/backend/summary lifecycle events.
- Ensure failed/blocked paths emit safe evidence.
- Ensure child/sub-agent request events are emitted by U8 through the same helper.

Test scenarios：

- recall/propose/approve/reject/commit/delete/update/update_failed/failed events exist.
- policy blocked and sensitive blocked have safe evidence.
- backend selected/warning events exist.
- summary created/updated/cleared/restored events exist, with restore recorded as `memory.summary_restored`.
- no raw memory text, prompt, tool result, file content, record_id, child payload, or secret appears in event payload.

Rollback：

- Revert lifecycle wiring while keeping U2a helpers if other units depend on them. Store/policy behavior should remain unchanged.

### U2c. Memory evidence visibility tests

Goal：

- Prove Memory evidence appears in the built-in visibility surfaces: `events.jsonl`, `action_log`, `log_viewer`, `safe_summary`, and run summary if applicable.

Files：

- `agent/event_log.py`
- `agent/log_viewer.py`
- `agent/loop.py`
- `tests/runtime_integration/test_memory_event_log*.py`
- `tests/test_log_viewer*.py`

Approach：

- Add tests that flush Memory RuntimeActionEvents to per-session `events.jsonl`.
- Add log_viewer tests for stable memory labels/counts.
- Add safe_summary/run summary forbidden-field matrix tests.
- Avoid adding a Memory-specific log file.

Test scenarios：

- `events.jsonl` has `memory.recall.completed` and other lifecycle events.
- `action_log` has memory lifecycle trace.
- `log_viewer` displays memory event summary without raw content.
- forbidden-field matrix covers `events.jsonl`, `action_log`, `log_viewer`, `safe_summary`, and run summary if applicable.

Rollback：

- Revert visibility tests and display changes. Runtime memory behavior and store records remain untouched.

### U3. Backend and root policy

Goal：

- Make durable backend and root behavior explicit, test-safe, and user-visible.

Files：

- `agent/memory_runtime.py`
- `agent/memory_store.py`
- `agent/memory_fs_store.py`
- `agent/display_events.py`
- `tests/test_memory_store_backend.py`
- `tests/runtime_integration/test_memory_backend_*.py`

Approach：

- Centralize backend/root resolution.
- Require explicit durable root for filesystem persistence: configured `MEMORY_STORE_ROOT` or user-visible setup confirmation.
- Force tests to inject tmp root for filesystem backend.
- Prevent tests from writing real HOME.
- Resolve duplicate `FilesystemMemoryStore` by renaming/isolating/removing production export from skeleton class.
- Emit `memory.backend_selected` and `memory.backend_warning`.
- Enforce D1: durable v0 readiness requires explicit filesystem durable root or explicitly configured durable backend; InMemory-only config cannot claim durable readiness.

Test scenarios：

- `MEMORY_STORE_BACKEND=filesystem` with tmp root uses real filesystem store.
- no test writes under real HOME.
- filesystem backend without explicit durable root does not silently write HOME.
- filesystem backend without explicit durable root either enters user-visible setup path or falls back to InMemory with warning/evidence.
- invalid backend fails closed.
- InMemory explicit store emits user-visible non-durable warning and `memory.backend_warning`.
- duplicate filesystem class cannot be imported as production backend by mistake.
- filesystem init failure does not silently downgrade.
- InMemory-only config fails durable readiness assertion.

Rollback：

- Restore previous backend selection and class exports. If default backend changed, rollback must not delete existing filesystem memory files; it only changes runtime selection.

### U4. Checkpoint/MemoryStore consistency

Goal：

- Prevent checkpoint and MemoryStore from silently diverging after save/resume.

Files：

- `agent/checkpoint.py`
- `agent/state.py`
- `agent/session.py`
- `agent/memory_runtime.py`
- `agent/runtime_integration/checkpoint_save.py`
- `tests/test_checkpoint_*.py`
- `tests/runtime_integration/test_memory_checkpoint_*.py`

Approach：

- Add memory reference metadata to checkpoint if selected: backend, namespace, root kind/hash, revision/last_seen_ids.
- On resume, check reference against current MemoryStore.
- Emit `memory.reference_saved`, `memory.reference_checked`, `memory.reference_mismatch`, `memory.restored` or `memory.restore_skipped`.
- Do not serialize full long-term memory records into checkpoint.

Test scenarios：

- checkpoint saves memory reference metadata, not raw records.
- resume with same store passes reference check.
- resume with missing/mismatched store emits warning evidence.
- checkpoint cannot silently replace MemoryStore records.
- pending memory confirmation resume still works.

Rollback：

- Remove checkpoint metadata read/write and reference checks. Existing checkpoints with metadata should be ignored safely if rollback happens.

### U5. working_summary boundary

Goal：

- Classify `working_summary` as scratchpad and make its lifecycle safe/auditable.

Files：

- `agent/memory.py`
- `agent/context_builder.py`
- `agent/state.py`
- `agent/checkpoint.py`
- `agent/core.py`
- `agent/log_viewer.py`
- `tests/test_memory_summary_*.py`
- `tests/test_checkpoint_*.py`

Approach：

- Add explicit code comments/docs that `working_summary` is scratchpad, not user memory.
- Ensure it never enters MemoryStore records.
- Add redaction/safe_summary around summary creation/update/clear.
- Define reset/clear owner and evidence for creation/update/clear/restore.
- Use `memory.summary_restored` for `working_summary` restore events in v0.
- Keep `show memories` from listing it unless a future internal state inspector is built.

Test scenarios：

- `working_summary` is not shown by `show memories`.
- `working_summary` does not become a MemoryRecord.
- reset/clear behavior matches decision.
- summary evidence contains no raw secret.
- summary restored from checkpoint produces safe restore/check evidence.

Rollback：

- Revert scratchpad evidence and redaction changes. Do not migrate `working_summary` into MemoryStore in rollback.

### U6. Minimal model-visible memory request tools

Goal：

- Provide mandatory v0 model-visible request-only memory tools.

Files：

- `agent/tools/`
- `agent/tool_registry.py`
- `agent/tool_runtime_mediator.py`
- `agent/runtime_integration/schema.py`
- `agent/runtime_integration/memory_retain.py`
- `agent/runtime_integration/memory_forget.py`
- `agent/memory_interaction.py`
- `tests/runtime_integration/test_memory_tool_*.py`

Approach：

- Register request-only tools in `TOOL_REGISTRY`.
- Route all calls through `ToolRuntimeMediator`.
- Tool can propose/list/request forget/update, but cannot commit without user confirmation.
- No `MEMORY_COMMIT` tool.
- Link memory.* evidence to `TOOL_GATE` / `TOOL_INVOKE` / `TOOL_RESULT`.

Test scenarios：

- model-visible remember request creates pending confirmation, not direct store write.
- user rejection writes no record and logs rejection.
- user approval commits through dispatcher/store and logs commit.
- list/view shows only user-visible memory.
- forget/update requests require confirmation and safe evidence.
- model-visible memory request tool path goes through `TOOL_REGISTRY` + `ToolRuntimeMediator`.

Rollback：

- Unregister/remove memory tools and tests. Existing explicit user prefix flow remains available.

### U7. Skill memory_scope recall enforcement

Goal：

- Enforce active Skill `memory_scope=none` suppression for recall injection as mandatory v0 closeout.

Files：

- `agent/skill_system/memory_boundary.py`
- `agent/skill_system/context.py`
- `agent/core.py`
- `agent/prompt_builder.py`
- `agent/runtime_integration/memory_recall.py`
- `tests/runtime_integration/test_skill_memory_scope_*.py`

Approach：

- Pass active skill memory_scope into memory recall request or prompt building.
- Use Skill legal scope values only: `none`, `read_context`, `propose_memory`.
- Do not use `propose` as a Skill scope; `propose` is a SubAgent scope value.
- Suppress memory recall injection when active Skill `memory_scope=none`.
- Allow recall injection when active Skill `memory_scope=read_context`.
- Treat Skill `memory_scope=propose_memory` as not permitting direct MemoryStore write; write/propose enforcement may defer, but direct writes remain forbidden.
- Log allow/block with safe `memory.policy_blocked` or equivalent evidence.
- Defer Skill write/propose enforcement unless needed by U6; do not defer recall suppression.
- While Skill write/propose enforcement is deferred, Skill must not have any direct MemoryStore write path. Any future Skill memory proposal must route through MemoryRuntime governance, user confirmation, and memory.* evidence.

Test scenarios：

- active skill with `memory_scope=none` receives no memory context.
- active skill with `memory_scope=read_context` receives allowed memory context.
- active skill with `memory_scope=propose_memory` does not direct-write MemoryStore.
- tests must not use `propose` as a Skill scope value.
- block/allow evidence exists and contains no raw memory.
- normal no-skill memory recall continues to work.

Rollback：

- Revert skill scope filtering only if it causes a regression. Memory recall returns to global default; no store migration required.

### U8. Child/Sub-agent memory request lockdown

Goal：

- Ensure child/sub-agent requests cannot directly write long-term MemoryStore in v0.
- Current code does directly write MemoryStore. For Memory v0, child/sub-agent memory requests must be converted to rejected/deferred evidence-only.

Files：

- `agent/tool_runtime_mediator.py`
- `agent/subagent_system/executor.py`
- `agent/subagent_system/memory_boundary.py`
- `agent/runtime_integration/schema.py`
- `agent/runtime_integration/evidence.py`
- `tests/runtime_integration/test_subagent_memory_*.py`
- `tests/runtime_integration/test_tool_runtime_mediator_memory_*.py`

Approach：

- Start from U0 characterization.
- Convert current direct-write behavior to rejected/deferred evidence-only.
- Proposal-only + parent/user confirmation is deferred to a future Sub-agent memory phase unless separately approved.
- Emit `memory.child_request_received` and then `memory.child_request_deferred` or `memory.child_request_rejected`.
- Do not allow silent store write under any `memory_scope`.
- Use SubAgent legal scope values in SubAgent tests: `none`, `read_context`, `propose`.
- `memory_scope=propose` must return rejected/deferred status and must not directly commit.
- Direct mediator calls with `read` / `write` / unknown non-none values must also return rejected/deferred status and must not directly commit.
- Ensure raw child/sub-agent payload does not enter evidence/log surfaces.
- U8 must remove raw key/`value_preview` from `SUBAGENT_CHILD_MEMORY_REQUEST` evidence payload.
- Use `child_payload_hash`, `key_hash`, `redacted=true`, `count`, `source_type`, `policy_path`, `decision`, and `reason` fields instead.

Test scenarios：

- `memory_scope=none` does not write store and emits rejected/deferred evidence.
- SubAgent `memory_scope=read_context` / `propose` does not directly commit to MemoryStore.
- direct mediator `memory_scope=read` / `write` / unknown does not directly commit to MemoryStore.
- rejected/deferred path emits evidence and writes nothing.
- raw child payload is absent from `events.jsonl`, `action_log`, `log_viewer`, `safe_summary`, and run summary if applicable.
- raw key and `value_preview` are absent from `SUBAGENT_CHILD_MEMORY_REQUEST` evidence.

Rollback：

- Revert child memory lockdown changes only after confirming rollback does not re-enable silent store write. If rollback would re-enable direct child write, keep a guard test or feature flag disabled.

### U9. Proposal UX minimum or explicit defer

Goal：

- Make residual proposal behavior honest: surfaced to user or explicitly deferred with evidence.

Files：

- `agent/memory_runtime.py`
- `agent/memory_suggestions.py`
- `agent/loop.py`
- `agent/display_events.py`
- `tests/test_memory_suggestions.py`
- `tests/runtime_integration/test_memory_proposal_*.py`

Approach：

- Agent-proposed proactive discovery remains default-off.
- If proposal remains in v0, show a lightweight user hint and provide approve/reject path.
- If proposal is deferred, disable default surfacing and emit `memory.proposal_skipped` or `memory.proposal_deferred`.
- Do not enable proactive discovery without sensitive policy, duplicate suppression, and confirmation lifecycle evidence.

Test scenarios：

- turn-end proposal is either surfaced with user-visible prompt or skipped/deferred with exact evidence event.
- reject does not write store.
- approve commits through dispatcher.
- proposal evidence includes reason/confidence/source_type without raw prompt.

Rollback：

- Disable proposal surfacing and keep explicit memory only. Proposal records created during tests should be pending-only and safe to discard.

## G. Test Plan

### 1. Unit tests

- MemoryStore source-of-truth: `InMemoryMemoryStore` and filesystem store produce consistent record semantics.
- backend root policy: filesystem persistence requires explicit durable root, tests select tmp root, and runtime never silently writes real HOME.
- `working_summary` boundary: summary is scratchpad, not MemoryRecord.
- evidence safe_summary schema: memory.* events include required safe fields and exclude forbidden raw content.
- duplicate filesystem class import: production filesystem backend resolves to `agent/memory_fs_store.py::FilesystemMemoryStore` only.
- memory_id / record_id redaction: delete/update/list/forget/recall events use `memory_id_hash` or redacted id.
- child/sub-agent memory helper classification: current `mediate_child_memory_request()` behavior is characterized before implementation changes.

### 2. Runtime integration tests

- explicit remember → approve → commit → recall → evidence.
- remember → reject → no write → evidence.
- forget/delete → evidence.
- update/correction → evidence.
- recall prompt injection → evidence.
- model-visible tool → `ToolRuntimeMediator` → confirmation → store.
- active skill `memory_scope=none` → no recall injection.
- active skill read scope → bounded recall injection.
- model-visible memory request tool goes through `TOOL_REGISTRY` + `ToolRuntimeMediator`.
- model-visible tool cannot direct commit.
- model-visible approval commits only after confirmation.
- model-visible rejection writes nothing.
- evidence chain links `TOOL_GATE` / `TOOL_INVOKE` / `TOOL_RESULT` and memory.* events.

### 3. Child/Sub-agent memory tests

- `mediate_child_memory_request()` with `memory_scope=none` does not write store.
- SubAgent legal `memory_scope=read_context` / `propose` must not directly commit to MemoryStore.
- Direct mediator `memory_scope=read` / `write` / unknown must not directly commit to MemoryStore.
- Child request must emit `memory.child_request_rejected` or `memory.child_request_deferred` and write nothing.
- `memory.child_request_received` must be emitted for child memory request entry.
- `memory.child_proposal_created` must not be emitted by v0 rejected/deferred evidence-only lockdown; it is reserved for a future proposal-only Sub-agent memory phase.
- raw child/sub-agent payload must not enter `events.jsonl`, `action_log`, `log_viewer`, `safe_summary`, or run summary.

### 4. MCP auto-memory disabled tests

- MCP tool result does not automatically write MemoryStore.
- No MemoryStore mutation occurs after MCP tool result unless an explicit memory request and user confirmation exist.
- If a future MCP memory proposal path is added, it must be proposal + user confirmation + memory.* evidence; v0 must not implement auto-memory.

### 5. Checkpoint/session tests

- checkpoint saves memory reference metadata.
- resume checks memory reference.
- mismatch warning/evidence is emitted.
- MemoryStore is not silently replaced by checkpoint.
- `working_summary` restored/cleared according to decision.
- pending memory confirmation survives resume without double write.

### 6. Backend tests

- InMemory warning if used for explicit memory.
- filesystem tmp root in tests.
- no HOME writes in tests.
- duplicate class import cannot happen.
- filesystem init failure is visible and not silently downgraded.
- durable readiness requires filesystem safe root or explicitly configured durable backend.
- InMemory-only configuration cannot claim durable Memory v0 readiness.

### 7. Exact evidence event-name tests

- `events.jsonl` has `memory.recall.completed`.
- exact assertions for `memory.proposal_skipped`.
- exact assertions for `memory.proposal_deferred`.
- exact assertions for `memory.update_failed`.
- exact assertions for `memory.child_request_received`.
- exact assertions for `memory.child_request_deferred`.
- exact assertions for `memory.child_request_rejected`.
- exact assertion that `memory.child_proposal_created` is not emitted in v0 child request lockdown tests.
- exact assertions for `memory.summary_restored`.

### 8. Evidence/log visibility tests

- `events.jsonl` has memory lifecycle events.
- `action_log` has memory lifecycle trace.
- `log_viewer` displays stable memory event summary.
- `safe_summary` exists for memory events and contains no forbidden fields.
- run summary includes memory counters only if implemented, and contains no forbidden fields.
- failed/blocked/deferred operations still log safely.
- production direct recall path without evidence fails architecture test.

### 9. Forbidden-field matrix tests

Across `events.jsonl`, `action_log`, `log_viewer`, `safe_summary`, and run summary if applicable, the following must not appear:

- raw memory text
- raw user prompt
- raw assistant prompt
- raw tool result
- raw file content
- secret / API key / credential
- full filesystem path
- raw record_id
- raw memory_id
- raw child/sub-agent payload

### 10. ID redaction/hash tests

- delete/update/list/forget/recall evidence uses `memory_id_hash` or redacted id.
- raw record_id is absent from `events.jsonl`.
- raw record_id is absent from `action_log`.
- raw record_id is absent from `log_viewer`.
- raw record_id is absent from `safe_summary`.
- `MemoryForgetHandler` evidence is explicitly covered.

### 11. Skill scope tests

- active skill `memory_scope=none` suppresses recall injection.
- this is mandatory closeout, not optional.
- active Skill `memory_scope=read_context` permits bounded recall injection.
- active Skill `memory_scope=propose_memory` does not mean direct MemoryStore write.
- SubAgent `memory_scope=propose` is rejected/deferred evidence-only in v0.
- Skill/SubAgent scope strings are tested separately to avoid enum confusion.
- scope allow/block evidence contains no raw memory.

### 12. Security/privacy tests

- secret redaction.
- prompt injection flag.
- sensitive category policy.
- hidden summary not listed as user memory.
- delete/correct path.
- memory poisoning attempt does not bypass confirmation.

## H. Architecture Boundary Tests

- `checkpoint.py` must not import MemoryRuntime/MemoryStore implementation directly unless already existing and explicitly approved.
- `transitions.py` must not import Memory subsystem.
- `ToolRuntimeMediator` remains the path for model-visible memory tools.
- `MemoryRuntime` must not create independent event log.
- No production recall path without evidence.
- No tests write to real HOME.
- No duplicate production `FilesystemMemoryStore` export.
- MemoryStore remains long-term source-of-truth; checkpoint stores reference metadata, not raw long-term records.
- `working_summary` remains scratchpad and cannot be listed as user memory.
- Skill `memory_scope=none` suppresses active-skill memory recall injection.
- Child/sub-agent memory request cannot directly write MemoryStore.
- MCP tool result cannot automatically write MemoryStore.
- Model-visible memory tools must be registered in `TOOL_REGISTRY` and mediated by `ToolRuntimeMediator`.
- No `MEMORY_COMMIT` model-visible tool exists.
- Memory evidence must use hashed/redacted ids, not raw record_id/raw memory_id.

## I. Quality Gates

- `ruff check` on changed files.
- `.venv/bin/python -m pytest -q tests/ -k "memory" -rx --tb=short`.
- focused runtime memory tests.
- checkpoint/session memory tests.
- evidence/log viewer tests.
- child/sub-agent memory lockdown tests.
- MCP auto-memory disabled tests.
- model-visible memory tool tests.
- Skill `memory_scope=none` recall suppression tests.
- explicit durable root / no silent HOME write tests.
- forbidden-field matrix tests.
- id hashing/redaction tests.
- architecture boundary tests.
- `git diff --check`.
- full `.venv/bin/python -m pytest -q -rx` optional for final closeout, with known unrelated residuals classified.
- No real LLM/provider/MCP calls.
- No real HOME memory writes in tests.
- No commit or push until user explicitly authorizes.

## J. Rollback Plan

Evidence changes：

- Revert Memory evidence adapter/helper and `log_viewer` display additions.
- Keep store records untouched; rollback affects observability only.
- If event schema version was introduced, old events remain readable as generic evidence entries.

Backend default/root policy：

- Revert backend selection logic while preserving any existing filesystem files.
- Do not delete user memory files during rollback.
- Keep tests isolated to tmp root even if production default is reverted.

Checkpoint metadata：

- Make metadata read optional before removal.
- Rollback can ignore unknown checkpoint memory reference fields.
- Never use rollback to deserialize checkpoint memory reference into MemoryStore records.

Model-visible tools：

- Unregister/remove memory request tools from `TOOL_REGISTRY`.
- Leave explicit user prefix memory flow intact.
- Ensure no pending tool confirmation can commit memory after tool removal.

Child/sub-agent memory lockdown：

- Revert child memory lockdown only if rollback preserves a guard that prevents direct child/sub-agent MemoryStore writes.
- If reverting to a prior implementation would re-enable direct store write, keep rejected/deferred evidence-only behavior instead.
- Do not delete any user MemoryStore files during rollback.

ID hashing/redaction：

- Revert id hashing/redaction helpers only with replacement tests proving raw record_id/raw memory_id still cannot reach evidence/log surfaces.
- If old events contain raw ids, log_viewer must continue to redact them when rendering.

Skill boundary enforcement：

- Revert recall scope filtering only if it causes a regression.
- Keep memory evidence safe even if scope enforcement is rolled back.

working_summary boundary：

- Revert summary evidence/redaction changes without moving summary into MemoryStore.
- If clear/reset ownership changes are reverted, document that scratchpad governance is again incomplete.

## K. Open Questions

The following are not open questions anymore:

- Memory v0 is durable explicit user memory.
- Filesystem persistence requires explicit durable root: user-configured `MEMORY_STORE_ROOT` or user-visible first-run setup / setup command confirmation. Silent HOME writes are forbidden.
- Minimal model-visible request-only memory tools are in v0 scope.
- Skill `memory_scope=none` recall suppression is mandatory.
- Memory v0 uses rejected/deferred evidence-only for child/sub-agent memory requests. Proposal-only + parent/user confirmation is deferred to a future Sub-agent memory phase.
- Use `memory.summary_restored` for `working_summary` restore events in v0.

Remaining open questions:

1. `log_viewer` 是否需要专用 renderer，还是 stable generic label/count 足够？  
   推荐答案：先用 stable generic label/count；如果 forbidden-field 或 usability tests 不足，再加专用 renderer。

2. Checkpoint memory reference 的最小 revision 字段是什么？  
   推荐答案：先用 backend、namespace、root kind/hash、last_seen_ids；如果 filesystem backend 已有 revision/index version，再纳入 `store_revision`。

需要实现前复核：

- 当前 `RuntimeActionEvent` flush 到 `events.jsonl` 的字段映射是否足够承载 memory_event_version 和 safe fields。
- `log_viewer` 是否已有足够 generic evidence display，还是需要 memory-specific renderer。
- `MemoryRuntime._log` 现有事件名与新 taxonomy 的映射是否可兼容旧测试。
- `agent/tool_runtime_mediator.py::mediate_child_memory_request()` 当前 direct-writes MemoryStore；U0 必须用测试锁定已确认的当前行为。

## L. Closeout Criteria

- explicit memory can be retained, recalled, listed, updated/deleted with evidence.
- memory recall affecting prompt always has evidence.
- no production direct recall path without evidence.
- MemoryStore source-of-truth is documented and enforced.
- checkpoint/session restore cannot silently diverge from MemoryStore.
- `working_summary` is bounded and cannot masquerade as user memory.
- backend/root policy prevents test HOME writes.
- Durable explicit user memory semantics are enforced.
- Filesystem persistence requires explicit durable root via `MEMORY_STORE_ROOT` or user-visible setup confirmation.
- No silent long-term memory writes to HOME.
- InMemory-only configuration cannot claim durable v0 readiness.
- Memory events are visible in built-in `events.jsonl`, `log_viewer`, and `action_log`.
- Model-visible request tools are available and request-only.
- Model-visible memory request tool path goes through `TOOL_REGISTRY` and `ToolRuntimeMediator`.
- No model-visible `MEMORY_COMMIT` tool exists.
- Skill `memory_scope=none` suppress recall injection passes.
- Sub-agent/child-agent cannot directly write MemoryStore in v0.
- MCP tool result does not auto-write MemoryStore.
- Child/sub-agent memory request is rejected/deferred evidence-only in v0.
- all Memory logs are redacted and safe.
- all memory-affecting prompt/store/checkpoint/child-request behavior has built-in evidence/log.
- no raw memory/prompt/tool/file/path/record_id/memory_id/child payload/secret leaks in evidence/log.
- no Sub-agent memory write, MCP auto-memory, hidden long-term profiling, vector/RAG, L2/Emergence production, or external MemoryProvider is accidentally enabled by this cleanup.
