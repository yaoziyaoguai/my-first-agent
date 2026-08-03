---
title: 012 Trusted Continuity MVP - Implementation and Acceptance Plan
type: feat
date: 2026-08-02
topic: trusted-continuity
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: docs/architecture/012_TRUSTED_CONTINUITY_DESIGN.md
execution: code
---

# 012 Trusted Continuity MVP — Implementation and Acceptance Plan

## Goal Capsule

- **Objective:** 在当前健康的 Minimal Runtime Kernel 上闭合“同一入口回答/澄清/Goal → durable execution → restart recovery → evidence-backed completion → governed personal preference”参考旅程。
- **Current baseline:** `AgentRuntime.run_turn`、CAS checkpoint、tool approval/effect recovery、CLI/TUI/headless adapters 和六项 bounded capability 已存在；规划时 `git diff --check`、Ruff、`376 passed` 全绿。Goal、默认持久恢复、Provider disclosure、verified completion 和 owner preference 尚不存在。
- **Approach:** breaking checkpoint v2；provider-neutral reserved control block；所有决策和 mutation 仍由唯一 Runtime/reducer 持久化；默认 owner-only state root；Goal/evidence 与 Memory fact 分权；每单元准确 Red → 最小 Green。
- **Delivery shape:** U0–U8 顺序执行。一个 focused Green 不是停止点；必须完成全量门、冻结 reference suite、真实 Provider E3（或准确唯一配置缺口）和 fresh independent review。
- **Hard exclusions:** 第二个 model/tool loop、pre-runtime classifier、产品内 CodingLoop/daemon、dynamic registry、multi-root authority、auto-learning/promotion、compatibility fallback、秘密发现、commit/push。唯一窄例外是现有 architecture 已允许的 composition bootstrap：排他初始化空 checkpoint；初始化后不能推进 state。

## Source of truth and precedence

1. `AGENTS.md` 与现有 Kernel/Extension architecture invariants。
2. `STRATEGY.md`：长期方向。
3. `docs/architecture/012_TRUSTED_CONTINUITY_DESIGN.md`：012 产品/架构权威。
4. 本文：实施顺序、Red/Green 和验收权威。
5. `docs/implementation/012_LOOP_HANDOFF.md`：外部 executor/reviewer 协议。

010 的宽范围 optimizer、dynamic authority、Goal transfer/import/export 等内容不进入本轮。实现者不得为了满足 010 的旧 checklist 扩大 012。

## Key Technical Decisions

| Decision | Chosen approach | Rejected alternative | Reason |
|---|---|---|---|
| Intent/control | reserved provider-neutral `ModelControlBlock`，只由 Runtime 解释 | pre-runtime classifier 或解析 final text | 保持唯一模型 owner，并让状态变化可严格校验 |
| Goal truth | Goal/evidence 内联 canonical `ConversationState` checkpoint v2 | 独立可写 GoalStore 或 event-log rebuild | 避免 split brain，复用现有 CAS/recovery |
| Checkpoint compatibility | breaking v2，旧 v1 显式 fail closed | v1/v2 双写、fallback、隐式迁移 | 项目非生产急迫，安全清晰优于兼容债务 |
| Default recovery | product-owned state root + deterministic workspace/session layout | 可写 catalog、扫描 workspace 或猜最近文件 | 无双写/事务窗口，同时避免误恢复/信息泄露 |
| Continued work | 一个 `run_turn` 内的 control/Goal progression；startup caller 最多提交一个 exact typed action | 产品 CodingLoop/daemon/background retry driver | 不创建第二套循环或无限成本路径 |
| Approval | fixed composition 内的 Goal-bound policy | 动态 authority registry 或所有 write 永远重复审批 | 降低无效打断但不扩大 root/tool/service |
| Completion | Runtime gate 验证 bound evidence | 执行模型自报或 `RunStatus.COMPLETED` | 防止 false completion/reward hacking |
| Memory | provenanced workspace `AgentFact` + user-confirmed owner preference | 自动抽取/合并/跨 workspace task memory | 满足连续性同时限制 poisoning 半径 |
| Remote egress | durable pre-send disclosure + hardened destination | 启动参数视为所有数据类别的永久同意 | local-first 必须让实际外发可见、可绑定 |

这些决策均来自本轮已确认产品边界与现有代码不变量，不是 executor 可自行重新选择的开放问题。

## Requirements trace

| Requirement | Primary unit | Acceptance evidence |
|---|---|---|
| TC-01/02 unified entry/direct answer | U3 | entry-routing tests + reference J1 |
| TC-03 direction boundary | U3 | clarification matrix + zero-effect counters |
| TC-04/05 durable Goal/continuous progress | U1/U3 | v2 checkpoint + tool-before-goal Red + J2 |
| TC-06 visible control | U4 | action legality + CLI/TUI/headless parity |
| TC-07 deterministic recovery | U2/U4 | locator/select/restart/unknown-effect tests |
| TC-08 verified completion | U6 | criterion/evidence mutation oracle + J2 |
| TC-09/10 fact ownership/honest memory | U7 | provenance/poison/cross-workspace/forget tests |
| TC-11 Provider disclosure | U5 | send-count zero-before-ack + destination drift |
| TC-12 parity/observability | U4/U8 | shared view golden tests + integrated suite |
| TC-13 Goal-aware approval | U4 | policy matrix + binding-drift/effect-count tests |

## Global engineering rules

- 每个行为/架构变化先提交准确 Red test；在 execution log 记录测试名、失败原因和退出码，再做最小 Green。
- Provider `generate` 的 production 调用点始终只能位于 `agent/runtime/loop.py`。
- Tool callable 只能由 `ToolRuntime` invoke；reserved control block 不得伪装成普通 tool，也不得进入 tool registry。
- Runtime 每次改变 Goal、control、disclosure、evidence 或 effect state 都先 CAS checkpoint，再继续下一步。
- UI/event 不是 truth；重启只从 checkpoint/deterministic session locator/store 投影。
- 不读取 `.env`、Claude settings/local memory、shell history、secret/private/runtime 文件；不把 key、Authorization、完整 prompt 或私有正文写入证据。
- 不删除/重置隔离副本的既有 dirty baseline，不恢复已切除旧 runtime，不 commit/push。
- 不为了测试方便增加 real/fake 双核心路径；fake/mocked transport 通过依赖注入替代同一 production path。

## U0 — Freeze baseline and delivery controls

### Goal

让 executor 明确自己面对的是当前 dirty-but-green materialized tree，而不是 HEAD 或旧 010 文档中的想象实现。

### Red / checks

1. 新增/更新 architecture inventory test，证明 production tree 中：
   - `AgentRuntime.run_turn` 是唯一 Provider generate owner。
   - `KernelToolRuntime` 是唯一 callable invoke owner。
   - 不存在 `CodingLoop`、`GoalSessionDriver`、intent router model client 或 dynamic service locator。
2. 记录 baseline：`git status --short`、Python/version、Ruff、full pytest；不能把截断/timeout 当 pass。
3. 建立 `docs/implementation/012_EXECUTION_LOG.md`，只记录非秘密命令、exit status、决策、Red/Green、E3/reviewer evidence。

### Green

- Architecture controls 只检查 materialized production files，不从 deleted legacy files 或 stale Graphify 得出结论。
- 现有 009 delivery/materialized-tree tests 保持 Green；如其 manifest 与真实树不一致，只按真实 diff 做最小同步并解释，不放宽断言。

### Exit gate

- Baseline full suite Green。
- execution log 写明工作树不是 clean HEAD，禁止 reset/checkout 恢复旧实现。

## U1 — Canonical Goal/control contracts and checkpoint v2

### Goal

先建立 immutable leaf contracts、reducer invariants 和 strict codec，再允许任何 UI/Provider 行为依赖它们。

### Named Red tests

- `tests/continuity/test_contracts.py`
  - `test_goal_frame_requires_stable_identity_scope_authority_and_criteria`
  - `test_goal_delta_is_bound_to_goal_revision_and_invalidates_stale_claims`
  - `test_run_completed_is_not_goal_verified_done`
  - `test_model_control_variants_are_closed_and_mutually_exclusive`
  - `test_goal_authorization_requires_user_authoritative_source_binding`
  - `test_criterion_admission_binds_user_outcome_and_closed_predicate`
  - `test_fact_admission_binding_rejects_forged_or_cross_workspace_source`
  - `test_provider_descriptor_is_immutable_non_secret_and_canonical`
- `tests/continuity/test_checkpoint_v2.py`
  - `test_goal_control_disclosure_and_evidence_round_trip_in_v2`
  - `test_v1_checkpoint_is_rejected_without_mutating_source`
  - `test_unknown_fields_and_invalid_goal_invariants_fail_closed`
  - `test_checkpoint_capacity_counts_new_bounded_fields`

### Minimal Green

- Add `GoalFrame`, proposed/admitted criteria, lifecycle/outcome, `EvidenceRecord`, interaction state, disclosure request/receipt, model control blocks and exact typed Goal actions.
- Add immutable `GoalAuthorizationBinding`, `CriterionAdmissionBinding`, `FactAdmissionBinding`, `ProviderDescriptor` and correlation-bound `ControlReceipt` leaf contracts. Model output alone cannot mint any authority/admission binding。
- Extend `ConversationState` with bounded canonical fields; keep facts immutable and referenced by ID/digest.
- Add reducer functions for create/progress/delta/pause/cancel/claim/verify with stale-revision rejection.
- Bump local checkpoint to schema v2; strict exact keys, no v1 fallback/dual write/implicit migration.

### Invariants

- `VERIFIED_DONE` cannot coexist with missing/failed/stale criterion evidence or unknown effect。
- correction increments Goal revision and invalidates old plan/next-step/completion claim/evidence bindings while retaining occurred facts。
- cancel/pause cannot erase an `EXECUTING` intent or recovery requirement。

### Exit gate

- U1 tests Green plus all `tests/kernel/test_contracts.py`, `test_state_transitions.py`, `test_checkpoint_*` Green。

## U2 — Default owner-only state root and deterministic session selection

### Goal

普通 `first-agent` 启动默认 durable，不要求用户手写 `--state/--resume`，同时不扫描 workspace 或猜错 Goal。

### Named Red tests

- `tests/continuity/test_state_root.py`
  - `test_default_start_creates_owner_only_product_state_root_outside_workspace`
  - `test_explicit_state_root_override_is_owner_only_and_no_follow`
  - `test_workspace_symlink_alias_resolves_same_identity`
  - `test_replaced_or_drifted_workspace_never_auto_resumes`
  - `test_one_matching_nonterminal_goal_is_selected`
  - `test_multiple_candidates_require_exact_select_goal_action`
  - `test_bounded_workspace_state_enumeration_rejects_unknown_entries_and_overflow`
  - `test_concurrent_first_start_creates_one_valid_checkpoint_per_identity`
  - `test_startup_does_not_scan_workspace_or_secret_paths`
- `tests/continuity/test_restart_selection.py`
  - `test_reopen_projects_goal_summary_without_provider_or_tool_call`
  - `test_executing_checkpoint_enters_existing_unknown_effect_recovery`

### Minimal Green

- Add high-cohesion workspace identity/session locator using deterministic `workspaces/<workspace-digest>/<conversation-id>.json` layout。Composition may bounded-enumerate the exact product-owned workspace state directory and排他初始化一个空 checkpoint；it cannot maintain a mutable catalog, advance Goal or call Provider/Tool。
- Default `~/.local/state/my-first-agent/v1`, explicit `--state-root` override, exact owner/mode/no-follow checks。
- Candidate metadata is loaded from strict checkpoints；there is no revision/terminal/provider mirror or cross-file dual write。
- No legacy in-memory fallback for normal product mode. A test-only injected in-memory store may remain in unit tests。

### Exit gate

- Startup/reopen has provider/tool send count zero。
- single/multiple/drift/EXECUTING cases all match design。
- existing scheduler state-root tests remain Green; scheduler does not become Goal auto-driver in 012。

## U3 — Unified entry and reserved model control

### Goal

在同一次 `SubmitMessage -> AgentRuntime.run_turn` 中实现 answer/clarify/Goal，自始至终没有 pre-runtime classifier 或第二模型循环。

### Named Red tests

- `tests/continuity/test_entry_routing.py`
  - `test_direct_answer_does_not_create_goal`
  - `test_direction_boundary_clarification_has_zero_tool_effect`
  - `test_explicit_task_persists_goal_before_rebuilding_context`
  - `test_task_tool_call_without_durable_goal_fails_before_prepare`
  - `test_control_and_illegal_tool_mix_fails_closed`
  - `test_unknown_or_malformed_control_never_mutates_state`
  - `test_active_goal_plain_done_text_cannot_end_goal`
  - `test_progress_control_continues_without_user_continue_message`
- `tests/provider/test_continuity_control.py`
  - OpenAI/Anthropic compatible reserved structured response normalize to identical `ModelControlBlock`。
  - `control -> durable correlation-bound receipt -> second native request` round trips for both provider payload shapes。
  - ordinary product tools retain existing normalization。
  - adapters never import reducer/checkpoint/tool runtime。

### Minimal Green

- ContextPack exposes one reserved control schema and pinned atomic ControlReceipt group separate from callable tool registrations。
- Provider adapters only serialize/normalize this schema。
- Runtime validates control, CAS persists it, rebuilds ContextPack and continues within the same invocation。
- Initial no-Goal phase exposes no effectful callable path; any task work must first create Goal。
- `ClarificationRequest` records boundary code/missing fields and ends with interaction `CLARIFYING`；next normal `SubmitMessage` resolves it。

### Exit gate

- Production search proves no new model client/call outside runtime loop。
- direct answer, clarification and Goal path each have provider-call/effect-count oracle。
- current provider kernel tests and tool-result feedback tests remain Green。

## U4 — Goal controls, pinned context and surface parity

### Goal

用户看得到 Agent 正在做什么，并能通过所有 surface 使用同样的 safe-boundary controls。

### Named Red tests

- `tests/continuity/test_goal_controls.py`
  - `test_pause_request_becomes_durable_only_at_safe_boundary`
  - `test_cancel_during_executing_cannot_bypass_unknown_effect_recovery`
  - `test_correction_invalidates_old_next_step_and_completion_claim`
  - `test_resume_goal_uses_exact_goal_and_revision`
  - `test_stale_control_action_has_zero_provider_and_tool_calls`
  - `test_control_inbox_is_non_mutating_and_binds_invocation_goal_revision`
  - `test_active_pause_correction_and_cancel_apply_only_at_safe_poll_points`
  - `test_blocked_provider_does_not_claim_immediate_kill`
- `tests/continuity/test_context_goal_frame.py`
  - `test_active_goal_is_trusted_pinned_bounded_core_context`
  - `test_memory_cannot_override_goal_or_current_user_correction`
  - `test_goal_frame_capacity_failure_happens_before_provider`
- `tests/continuity/test_goal_policy.py`
  - `test_model_forged_goal_or_scope_never_authorizes_workspace_write`
  - `test_exact_user_authoritative_binding_can_avoid_duplicate_prompt`
  - `test_path_alias_scope_expansion_and_stale_grant_have_zero_effect`
  - `test_target_scope_cost_sensitive_external_and_irreversible_boundaries_require_approval`
  - `test_new_root_tool_or_service_cannot_be_added_by_goal_policy`
  - `test_goal_revision_or_binding_drift_invalidates_prepared_intent`
  - `test_mcp_subagent_and_preference_risk_is_not_silently_downgraded`
- `tests/continuity/test_views.py`
  - shared `GoalView` fields/legal actions match CLI, TUI and headless for answering, clarifying, ready, executing, needs-authority, paused, approval, recovery, blocked, cancelled and verified-done。
  - reopen projection causes zero provider/tool call。

### Minimal Green

- Add shared action builders and shared state-to-view projection; CLI/TUI only parse/render。
- Add required process-local `ControlInbox` port. CLI/TUI/headless submit exact bound requests；Inbox cannot mutate state。Runtime polls only before provider, before tool prepare and after result CAS, then reducer/CAS applies them。`EXECUTING` recovery has priority。
- ContextManager pins bounded Goal/control/evidence-gap facts ahead of untrusted Memory; no CLI-built prompt。
- Extend `ToolPrepareContext` and policy evaluation with Runtime-verified `GoalAuthorizationBinding`。A model-created Goal never grants authority；only exact user fact/action/approval bindings may allow an operation。All expansion/unknown cases require approval or deny；prepare/invoke persist and re-evaluate the same binding。
- `BLOCKED` view includes progress, blocker, safe attempts and resume condition。

### Exit gate

- Existing CLI/TUI/recovery/approval tests plus U4 suite Green。
- Every user-visible action maps to a typed action and authoritative result；no UI-only mutation。

## U5 — Provider disclosure and destination hardening

### Goal

在任何 remote ContextPack 离机前提供准确、可绑定、可持久化的 disclosure，并消除 ambient destination drift。

### Named Red tests

- `tests/provider/test_remote_disclosure.py`
  - `test_first_remote_generate_requires_disclosure_and_send_count_is_zero`
  - `test_exact_acknowledgement_allows_one_bound_context_pack`
  - `test_model_destination_or_data_class_change_invalidates_receipt`
  - `test_owner_preference_category_requires_new_acknowledgement`
  - `test_event_loss_cannot_bypass_durable_disclosure`
  - `test_fake_local_provider_does_not_request_remote_disclosure`
  - `test_context_pack_closed_data_classes_bind_exact_receipt`
  - `test_provider_descriptor_drift_blocks_before_adapter_send`
- `tests/provider/test_destination_safety.py`
  - reject userinfo/query/fragment, non-loopback plain HTTP and redirect-based destination changes。
  - HTTP client does not inherit ambient proxy/config (`trust_env=False`)。
  - credential/header/key never appears in state/event/view/error/evidence。

### Minimal Green

- Composition injects immutable non-secret `ProviderDescriptor`; ContextManager emits closed `ContextPack.data_classes`。Runtime derives disclosure from their exact digest before `generate`，without importing concrete adapters or reparsing configuration。
- `AcknowledgeProviderDisclosure` exact binding is persisted via reducer；stale/mismatched ack fails closed。
- Provider HTTP adapters keep redirects disabled and enforce canonical safe endpoint policy；custom proxy/CA remains deferred。

### Exit gate

- Mock transport records zero bytes before ack and exact one request after valid ack。
- Existing OpenAI/Anthropic provider contract tests Green。

## U6 — Evidence-backed completion

### Goal

把“模型停了/说完成”与“Goal 已验证”彻底分开。

### Named Red tests

- `tests/continuity/test_verified_done.py`
  - `test_text_done_and_model_completion_claim_cannot_self_verify`
  - `test_missing_failed_stale_or_tampered_evidence_rejects_verified_done`
  - `test_unknown_effect_blocks_verified_done`
  - `test_deterministic_receipts_bound_to_all_mandatory_criteria_verify_goal`
  - `test_subjective_criterion_requires_exact_user_confirmation`
  - `test_goal_correction_invalidates_old_verdicts`
  - `test_fake_or_mock_receipt_cannot_satisfy_real_external_criterion`
  - `test_zero_or_weakened_criterion_and_unrelated_receipt_cannot_verify`
  - `test_filesystem_oracle_rederives_exact_path_and_content_digest_from_raw_facts`
  - `test_model_cannot_directly_create_evidence_record`
- `tests/scheduler/test_contracts.py`
  - Scheduler must not equate turn `RunStatus.COMPLETED` with Goal `VERIFIED_DONE` when Goal mode is present。

### Minimal Green

- Add Runtime-owned closed oracle registry。Admitted criterion includes a machine-checkable predicate bound to user outcome/approval；empty/weakened model proposal has no authority。
- Runtime re-derives bounded `EvidenceRecord` from raw durable tool/user facts and validates goal/revision/criterion/predicate/source digest/oracle identity；model cannot create evidence directly。
- A verifier may be a governed tool/SubAgent, but its statement remains a receipt input; Runtime gate owns terminal mutation。
- Reference journey uses deterministic filesystem oracle so E3 does not rely on another model praising the executor。

### Exit gate

- mutation tests prove every unsupported completion path has zero terminal-state change。
- UI renders criterion/evidence/caveat summary, not only “completed”。

## U7 — Provenanced workspace facts and owner preferences

### Goal

让 First Agent 记得通过它发生的事情，同时阻止 project/web/tool/model 内容污染跨 workspace preference。

### Named Red tests

- `tests/memory/test_agent_fact_scope.py`
  - `test_workspace_fact_requires_source_reference_and_origin`
  - `test_workspace_a_fact_is_never_recalled_in_workspace_b`
  - `test_unbacked_model_assertion_cannot_become_fact`
  - `test_forged_missing_stale_or_cross_workspace_fact_binding_is_rejected`
- `tests/memory/test_owner_preferences.py`
  - `test_explicit_user_confirmed_preference_recalls_across_workspaces`
  - `test_project_file_web_tool_and_model_content_cannot_admit_preference`
  - `test_current_user_and_goal_override_conflicting_preference`
  - `test_explain_returns_provenance_without_secret_or_absolute_path`
  - `test_correct_supersedes_old_revision`
  - `test_forget_stops_future_recall_after_restart`
  - `test_forget_receipt_does_not_claim_history_or_remote_erasure`
  - `test_provider_trust_profile_change_blocks_recall_before_generate`
  - `test_assistant_or_tool_fact_cannot_masquerade_as_user_confirmed_preference`

### Minimal Green

- Narrow workspace `memory_remember` to Runtime-generated `FactAdmissionBinding`; use existing ContextSource/ToolRuntime path。Memory callable consumes verified binding from persisted intent and never reads checkpoint or trusts model-provided source IDs。
- Add separate owner-only preference store under product state root, source and governed CRUD registrations；no automatic extraction/consolidation。
- Cross-workspace preference writes require explicit user statement or exact preview confirmation；model/tool content cannot provide authority。
- Source projection remains untrusted and budgeted；priority is current user > Goal > workspace > preference。

### Exit gate

- malicious README/web/Memory injection suite Green。
- Existing Memory store/source/tool/integration tests are updated to new strict schema and remain Green；no compatibility fallback。

## U8 — Frozen journey, E3, documentation and independent review

### Offline reference suite

Create `tests/reference/test_012_trusted_continuity.py` or a project-equivalent high-cohesion suite with raw mutation/send-count assertions:

- **J1 answer → clarify:** direct question no Goal；material ambiguity one question, no tool effect。
- **J2 task → crash → resume → verify:** explicit temp-workspace file task；Goal CAS precedes tool；crash before effect and after `EXECUTING` are separately exercised；no duplicate write；read-back/digest oracle yields `VERIFIED_DONE`。
- **J3 selection/control:** multiple candidates require select；pause/correct/cancel retain occurred facts and invalidate stale work。
- **J4 disclosure:** remote mock transport receives nothing before exact ack；destination/data-class drift fails closed。
- **J5 memory:** one confirmed preference crosses workspace；workspace fact and malicious instruction do not；correct/forget survive restart。
- **J6 false completion:** model claim, stale evidence and missing receipt never turn terminal Green。

### Real Provider E3

Use the production HTTP adapter and real `AgentRuntime.run_turn`, not FakeProvider or a parallel harness path. Use temporary workspaces/state roots and bounded harmless file actions only.

Required environment contract:

- `FIRST_AGENT_E3_PROVIDER`: `openai_compatible` or `anthropic_compatible`
- `FIRST_AGENT_E3_BASE_URL`: configured endpoint/base URL
- `FIRST_AGENT_E3_MODEL`: exact model name
- `FIRST_AGENT_E3_API_KEY`: credential value, read only by composition

E3 must prove with non-secret receipts:

1. remote disclosure blocks first send and exact acknowledgement unlocks it；
2. simple answer has no Goal；
3. explicit task persists Goal before first product tool；
4. approved local effect happens at most once；
5. deterministic evidence yields `VERIFIED_DONE`；
6. restart projects the same Goal/evidence without extra Provider call；
7. no key/header/full prompt/private content appears in stored artifacts。

If and only if all local gates pass and all four variables are absent, write exactly:

`NEEDS_E3_CONFIG(stage=U8, required=FIRST_AGENT_E3_PROVIDER,FIRST_AGENT_E3_BASE_URL,FIRST_AGENT_E3_MODEL,FIRST_AGENT_E3_API_KEY)`

If config is partial or bounded real attempts fail for a reason executor cannot repair, write a secret-free marker：

`E3_BLOCKED(stage=U8, reason=<incomplete_config|auth_failed|endpoint_unreachable|rate_limit_exhausted|provider_protocol|model_incompatible>)`

The execution log must include only the non-secret configuration identity, attempt count and sanitized error class。Do not stop earlier, search for credentials, retry indefinitely, or claim E3 passed from mocks。

### Documentation

- Update README/operator examples to show one default durable startup path, disclosure, Goal controls, recovery and honest completion semantics。
- Update capability/status claims only after matching tests/records pass；keep E1/E2/E3 distinctions honest。
- `012_EXECUTION_LOG.md` lists full commands, exit codes, failures/reruns, E3 receipt paths, reviewer findings and remaining caveats。

### Independent review

Use a fresh Claude Code session after executor gates. Reviewer must read the original 012 design/plan, full diff, execution log and raw test/E3 evidence；it cannot rely on executor summary。

Reviewer stop-ship checks：

- second loop/pre-runtime classifier/dynamic registry or hidden provider call；
- default non-durable path or unsafe auto-selection；
- task tool before Goal CAS；
- disclosure after send or receipt drift bypass；
- false completion, unknown-effect bypass, stale evidence；
- Memory poisoning/cross-workspace leak/dishonest forget；
- UI-only authority action or missing headless parity；
- secrets/private/runtime artifacts in diff or evidence；
- skipped/truncated/timed-out full gates。

All P0/P1/P2 correctness/security findings must be fixed and reviewed again. Style-only preferences do not expand scope。

## Required verification commands

Run focused tests after each unit, then from repository root run untruncated:

```bash
git diff --check
.venv/bin/ruff check .
.venv/bin/python -m pytest -q -rx
```

If the isolated copy does not contain `.venv`, use the explicitly known project interpreter or create an isolated project venv without reading secret config. Record exact interpreter path/version。

Additional architecture/materialization checks：

```bash
rg -n "\.generate\(" agent --glob '*.py'
rg -n "CodingLoop|GoalSessionDriver|service_locator|dynamic_registry" agent main.py
.venv/bin/python scripts/verify_materialized_tree.py
```

Search output is evidence to inspect, not an automatic pass；legitimate Provider method definitions/tests must be distinguished from production call sites。

## Risks and mitigations

- **Control protocol portability:** Provider 对 tool-like structured output 的细节不同。Mitigation：adapter-level fixtures + identical normalized block；业务 legality 只在 Runtime。
- **Checkpoint cutover invalidates local v1 state:** 这是明确 breaking decision。Mitigation：fail closed、不覆盖源文件、README 说明；不在 012 偷做迁移。
- **Long synchronous calls cannot be instantly killed:** 012 pause/cancel 只承诺 safe-boundary cooperative control。Mitigation：UI 区分 requested/durable；`EXECUTING` 永远先 recovery。
- **Natural-language direction判断仍有概率错误:** Mitigation：first-effect 前 durable Goal、可见 summary、快速 correction、zero unauthorized-effect hard gate。
- **Cross-workspace preference扩大隐私半径:** Mitigation：user-confirmed admission、provenance、Provider trust binding、small bounded store、poison/forget tests。
- **Real Provider nondeterminism/rate limits:** Mitigation：离线 contract suite 与真实 E3 分层；E3 有有限重试但不能重放 effect；准确记录样本和失败。
- **Dirty baseline易被 executor 误删:** Mitigation：U0 materialized baseline、project guardrail、no reset/checkout、fresh reviewer 检查 deletions/untracked files。

## Definition of Done

- [x] U0–U8 Red/Green/exit gates completed with untruncated exit codes。
- [x] All user input/model/tool/state mutation remains under the unique Runtime boundary。
- [x] Default product startup is durable and deterministic；multiple/drift/unknown cases fail safely。
- [x] Direct answer, clarification and task Goal are observably distinct without user mode choice。
- [x] Goal can pause/correct/cancel/resume across CLI/TUI/headless；EXECUTING recovery has priority。
- [x] Remote data cannot be sent before exact disclosure receipt。
- [x] `VERIFIED_DONE` cannot be produced by the executing model alone。
- [x] Workspace fact and owner preference ownership/provenance/correct/forget rules hold across restart。
- [x] Frozen offline suite and full repository gates pass。
- [x] Real Provider E3 passes。`NEEDS_E3_CONFIG` / `E3_BLOCKED` 是合法暂停态，但不满足 DoD，也不能进入 final reviewer pass。
- [x] Fresh independent reviewer has no unresolved correctness/security P0/P1/P2 finding。
- [x] No secret/private/runtime data, no product CodingLoop, no commit/push。

## Implementation notes template

For each unit append to `docs/implementation/012_EXECUTION_LOG.md`：

- unit and contract/test IDs；
- exact Red command, expected vs observed failure, exit status；
- minimal code/design choice and any deviation；
- exact focused/full Green command and exit status；
- provider/tool/effect/send-count evidence where relevant；
- unresolved risk or next unit；
- files changed；
- whether Graphify was used or safely skipped because the graph was stale/private-input risk existed。
