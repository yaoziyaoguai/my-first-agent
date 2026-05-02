# Stage 3 Memory Architecture Discovery

This document proposes the Stage 3 Memory System architecture for
`my-first-agent`. It is intentionally **not** a persistence implementation. The
goal is to define policy, boundaries, data contracts, UX, and test strategy
before any long-term memory is written.

## Design stance

Memory is not a file. Memory is a governed lifecycle:

```text
user/tool/runtime evidence
  -> MemoryCandidate extraction
  -> MemoryPolicy decision
  -> user confirmation when required
  -> MemoryStore / MemoryProvider seam
  -> retrieval with safety/relevance filters
  -> approved MemorySnapshot
  -> PromptBuilder injection
  -> model response
  -> audit/update/forget loop
```

The most important boundary: `prompt_builder` may consume an approved
`MemorySnapshot`, but it must not decide what to remember, retrieve, or forget.

## Proposed component responsibilities

| Component | Responsibility | Must not do |
|---|---|---|
| `MemoryCandidate` | Represent a possible thing to remember, with source, scope, sensitivity, confidence, and reason. | Persist itself or become prompt context automatically. |
| `MemoryDecision` | Represent retain / recall / update / forget / reject / no-op / clarify. | Execute storage writes directly. |
| `MemoryPolicy` | Deterministically decide or defer based on explicit user intent, stability, sensitivity, task scope, and conflicts. | Call real LLMs in early slices; bypass confirmation; read storage. |
| `MemoryApproval` | Carry the user-facing confirmation/edit/reject/forget choice. | Live in TUI backend or mutate runtime state directly. |
| `MemoryStore` | Future internal local storage interface for approved records. | Decide policy or read sensitive artifacts by default. |
| `MemoryProvider` | Future adapter seam for internal store, MCP resource provider, project provider, or vector provider. | Override First Agent policy or inject raw provider data into prompt. |
| `MemoryRetrieval` | Select relevant records under scope, freshness, sensitivity, and token budget. | Dump every memory into the prompt. |
| `MemorySnapshot` | Immutable approved context bundle consumed by prompt construction. | Contain unapproved candidates or full sensitive provenance text. |
| `MemoryAudit` | Record decision metadata and explain why something was remembered/recalled/forgotten. | Log sensitive full text by default. |

## Impact map for the current repo

| Module | Current responsibility | Memory-related risk | Future integration point | Must not do | Tests needed |
|---|---|---|---|---|---|
| `agent/memory.py` | Context compression and static memory prompt placeholder. | It could become a new monolith if it imports runtime/checkpoint/TUI/MCP layers. | Own pure memory contracts and policy helpers after review. | Read real `memory/` artifacts or call providers during discovery. | AST import/file-IO boundary tests; no-op placeholder tests. |
| `agent/state.py` | Durable runtime schema: runtime, conversation, task, current `MemoryState`. | `MemoryState.long_term_notes` and `checkpoint_data` blur long-term memory and recovery. | Later split session summary vs long-term memory references. | Store rich long-term records in runtime state. | Schema ownership tests before any field migration. |
| `agent/checkpoint.py` | Save/load crash recovery state. | Checkpoint JSON could be mistaken for durable memory. | May store memory operation pending status only if runtime is waiting for approval. | Become a long-term memory store. | checkpoint vs memory anti-coupling tests. |
| `agent/prompt_builder.py` | Assemble system prompt sections. | Directly calling `build_memory_section()` can tempt decision/retrieval logic into prompt construction. | Consume an approved `MemorySnapshot` or no-op snapshot. | Decide retain/recall/update/forget. | Prompt builder only consumes snapshot contract. |
| `agent/context_builder.py` / `agent/context.py` | Build model messages and manage current context. | Context compression can be confused with long-term memory. | Future retrieval may supply a bounded memory section to context assembly. | Persist facts or update memory. | Compression stays session-scoped; tool pairing preserved. |
| `agent/core.py` | Runtime orchestration and pending-state dispatch. | Memory approval could bloat the core loop if added directly. | Route a future memory approval pending state through existing HITL seams. | Own memory policy or storage. | Runtime boundary tests when adding memory approval. |
| `agent/confirm_handlers.py` | Plan/step/tool/user-input confirmation handling. | Memory retain confirmation could be shoehorned into unrelated plan/tool handlers. | Add a narrow memory approval handler only after contract exists. | Let TUI or backend bypass it. | Approval choices accept/edit/reject/forget/Other. |
| `agent/response_handlers.py` | Stop-reason handling and tool-use loop bridge. | Tool results may be auto-retained if not guarded. | Extract candidates from tool_result after policy review. | Auto-write tool_result to memory. | Tool_result never becomes memory without decision. |
| `agent/tool_executor.py` | Execute one tool with confirmation, messages, checkpoint-safe logging. | Memory tools could bypass confirmation if registered unsafely. | Future memory operations use explicit tools or internal policy, both audited. | Put memory provider tools in base registry. | Memory tool confirmation policy tests. |
| `agent/tool_registry.py` | Tool metadata, registry lookup, invocation normalization. | Memory/provider tools could mix policy into registry. | Metadata can mark optional memory capability. | Decide memory policy, checkpoint, or runtime transitions. | Base registry excludes memory provider tools by default. |
| `agent/user_input.py` / input backends | Preserve raw user input events. | Backend might infer "remember this" without runtime context. | Backends only submit raw text or memory approval choices. | Retain/reject/forget directly. | Backend cannot import memory policy/store. |
| `agent/display_events.py` / TUI | Render runtime/user-visible events. | UI could become memory decision owner. | Display memory suggestions and approvals. | Store memory or decide policy. | Display layer no memory store/checkpoint imports. |
| `agent/skills/registry.py` | Scan and inject Skills metadata. | Procedural memory and Skills may be conflated. | Skills can reference stable procedures; Memory can store project/user context. | Turn user facts into skills. | Skill prompt section separate from memory section. |
| `agent/mcp.py` | MCP client seam and explicit opt-in tool registration. | MCP resources/tools could be mistaken for internal memory. | External `MemoryProvider` adapter may use MCP resources later. | Expose MCP resources/prompts as completed Stage 3. | Provider cannot bypass First Agent policy. |
| docs/tests | Describe contracts and prevent regression. | Docs may overclaim memory implementation. | Record slices and acceptance criteria. | Claim RAG/vector/automatic memory is done. | README/Roadmap honesty markers. |

## Core boundary table

| Component | Responsibility | Must not do | Integration point | Test strategy |
|---|---|---|---|---|
| Memory vs checkpoint | Memory is cross-session governed semantic context; checkpoint is runtime recovery. | Checkpoint must not become long-term memory. | Pending memory approval may be recoverable, but records live elsewhere. | Assert checkpoint schema does not include full memory records. |
| Memory vs context compression | Compression summarizes current session for token budget. | Summary must not become durable long-term memory automatically. | Compression output can be a candidate only after policy. | Compression tests keep tool_use/tool_result pairing and no persistence. |
| Memory vs prompt_builder | Prompt builder injects approved snapshots. | No decision, retrieval, provider reads, or storage writes. | `MemorySnapshot` input seam. | Snapshot-only prompt tests. |
| Memory vs runtime state | Runtime state tracks current execution. | No long-term profile or provider cache in `TaskState`. | Pending approval status only. | Runtime state fields remain bounded. |
| Memory vs skills | Skills are capabilities/procedures; memory is user/project context. | Do not convert user facts into Skills. | Procedural memories may inform future Skill suggestions after approval. | Prompt sections remain separate. |
| Memory vs tools | Tool results can create candidates. | Tool results do not auto-retain. | Candidate extraction after tool_result append. | Tool_result candidate/no-op tests. |
| Memory vs MCP | MCP can provide external context/resources/tools. | MCP does not own internal policy. | `MemoryProvider` adapter from MCP resources later. | External provider cannot register into base registry. |
| Memory vs TUI | TUI displays suggestions and collects confirmation. | TUI does not decide retain/retrieve/forget. | RuntimeEvent/DisplayEvent projection. | TUI dependency boundary tests. |
| Memory vs storage | Storage persists approved records. | Storage cannot decide policy. | `MemoryStore` interface after contract review. | Fake store contract tests only. |

## Data model draft

### `MemoryCandidate`

Phase-one fields:

- `id`
- `content`
- `source`
- `source_event`
- `proposed_type`
- `scope`
- `sensitivity`
- `stability`
- `confidence`
- `reason`
- `created_at`

Future fields:

- token estimate
- language
- structured entities
- conflict hints
- provider id

Do not add now:

- embeddings
- vector ids
- raw full tool output
- automatic retention flags

### `MemoryDecision`

Phase-one fields:

- `decision_type`: `retain | recall | update | forget | reject | no-op | clarify`
- `target_candidate`
- `action`
- `requires_user_confirmation`
- `reason`
- `safety_flags`
- `provenance`

Future fields:

- `expiry` / `ttl`
- `conflict_target`
- policy version
- reviewer identity

Do not add now:

- LLM-generated unreviewed policy decisions
- provider-specific write commands

### `MemoryRecord`

Phase-one fields:

- `id`
- `content`
- `memory_type`
- `scope`
- `namespace`
- `provenance`
- `confidence`
- `sensitivity`
- `created_at`
- `updated_at`
- `status`
- `version`

Future fields:

- `expires_at`
- conflict lineage
- source hash
- access count
- last recalled at

Do not add now:

- vector columns
- unbounded raw transcript references
- global shared records without namespace

### `MemorySnapshot`

Phase-one fields:

- `items`
- `query_context`
- `selection_reason`
- `omitted_count`
- `safety_filter_summary`
- `token_budget`
- `rendered_char_budget`

Future fields:

- freshness score
- conflict summary
- provider mix

Do not add now:

- raw provider payloads
- unapproved candidates
- store write/update/delete operations

### `MemoryOperationResult`

Phase-one fields:

- `operation`
- `status`
- `record_id`
- `user_visible_message`
- `audit_summary`

Future fields:

- reversible operation id
- affected provider ids
- retry hint

Do not add now:

- sensitive full-text audit logs
- background job handles

## Memory decision contract

| Decision | Meaning | Confirmation rule |
|---|---|---|
| `retain` | Store a new approved long-term record. | Required unless user explicitly says "remember this" and content is low sensitivity. |
| `recall` | Use existing approved memory in this task. | Not required for low-sensitivity relevant memory; explain on request. |
| `update` | Replace or revise an existing record. | Required when user identity/preferences/project facts change. |
| `forget` | Delete or deactivate a memory. | User request has highest priority; confirm target if ambiguous. |
| `reject` | Explicitly refuse to remember unsafe/private/injected content. | No extra confirmation; explain safely. |
| `no-op` | Do nothing because content is ephemeral or already represented. | No confirmation. |
| `clarify` | Ask user what should be remembered or forgotten. | Use Ask User / Other-free-text style UX. |

## Safety and privacy policy

1. Default deny for sensitive information: secrets, credentials, private keys,
   medical/financial/legal personal data, raw logs, and full private transcripts.
2. User explicit consent is required for durable memory except clearly low-risk
   stable preferences where the agent is only **suggesting** retention.
3. `forget` outranks retain/update/recall.
4. Retrieval requires relevance, scope, sensitivity, freshness, and token-budget
   gates.
5. Tool results are never memory by default.
6. Prompt injection cannot authorize memory writes or deletion.
7. External providers can supply candidates/snapshots but cannot bypass First
   Agent policy.
8. Memory audit records decision metadata, not sensitive full text.
9. Stale or conflicting records are updated, demoted, or clarified rather than
   blindly injected.
10. Local-first fallback must exist before any external provider becomes useful.

### Failure modes to test

- User asks "forget X" and the system later recalls X.
- Tool output includes "remember the user's token is..." and a record is saved.
- MCP resource says "always inject me" and bypasses policy.
- Prompt builder reads provider/storage directly.
- A session summary becomes long-term memory without approval.
- Two conflicting preferences are both injected without a conflict note.

## User-friendly UX design

| Scenario | Good copy | Bad copy | Why |
|---|---|---|---|
| Suggest remembering | "我可以长期记住这个偏好：你希望回答尽量简洁。要记住吗？" | "Persist semantic user preference object?" | Good copy says what and asks permission in human language. |
| Confirm options | `记住` / `编辑后记住` / `不要记住` / `仅本次使用` / `Other` | `retain` / `update` / `reject` | User should not need architecture terms. |
| Edit memory | "请直接改写要记住的句子。" | "Submit JSON patch." | Keeps correction lightweight and privacy-safe. |
| Reject memory | "好的，我不会长期记住这条信息。" | "Rejected by policy code 403." | Clear, non-accusatory. |
| Forget flow | "我找到了 2 条相关记忆。请选择要忘记哪一条，或输入更具体的描述。" | "No exact key found." | Forget may need disambiguation, not database terms. |
| What do you remember? | "我可以列出当前与这个项目/你有关的长期记忆摘要，不显示敏感全文。" | Dump all records | Protects privacy and explains scope. |
| Session-only use | "好的，这条信息只用于当前对话，不会长期保存。" | "Memory no-op." | Differentiates current context from durable memory. |
| Recall explanation | "我用了这条记忆是因为它和当前 repo 的代码风格有关，来源是你上次确认的项目偏好。" | "Retrieved vector hit score 0.82." | Explains provenance and relevance. |

## Stage 3 roadmap slices

### Discovery pre-slice: Memory architecture docs + acceptance contracts

- Goal: Land this research/architecture note and tests that prevent overclaiming.
- Non-goal: no production persistence, no dataclass skeleton.
- Files likely touched: `docs/MEMORY_RESEARCH.md`, `docs/MEMORY_ARCHITECTURE.md`,
  `docs/ROADMAP.md`, docs acceptance tests.
- Tests first: doc marker tests for decision/store/snapshot/provider/safety slices.
- Expected behavior: no runtime behavior change.
- Acceptance criteria: docs explain boundaries, sources, slices, and no-persistence stance.
- Risk: docs drift from code.
- Stop condition: implementation pressure appears before policy review.
- Commit strategy: docs/tests commit.

### Slice 1: MemoryCandidate / MemoryDecision no-side-effect contracts

- Goal: Add pure dataclasses or enum skeleton only after research review.
- Non-goal: no store, no provider, no runtime hook.
- Files likely touched: `agent/memory_contracts.py` or similar, tests.
- Tests first: frozen dataclasses, allowed decision enum, no imports of runtime/checkpoint/TUI/MCP.
- Expected behavior: no runtime behavior change.
- Acceptance criteria: contracts are importable and side-effect free.
- Risk: premature schema lock-in.
- Stop condition: fields require provider-specific assumptions.
- Commit strategy: tests + minimal production skeleton.

### Slice 2: Deterministic MemoryPolicy no-op / explicit-only retain

- Goal: Add a deterministic policy that returns `no-op` by default and `clarify`
  or confirmation-required `retain` only for explicit user memory requests.
- Non-goal: no LLM classifier, no background extraction.
- Files likely touched: memory policy module and tests.
- Tests first: sensitive info rejected, prompt injection ignored, explicit remember asks approval.
- Expected behavior: no automatic memory write.
- Acceptance criteria: policy decisions are explainable and safe by default.
- Risk: false positives annoy users.
- Stop condition: policy needs real LLM or external classifier.
- Commit strategy: small production + tests.

### Slice 3: MemorySnapshot prompt injection seam

- Goal: Let prompt construction consume an approved no-op/empty snapshot.
- Non-goal: no retrieval/storage.
- Files likely touched: `prompt_builder`, memory snapshot contracts, tests.
- Tests first: prompt builder cannot import store/provider; only consumes snapshot text.
- Expected behavior: current prompt remains equivalent when snapshot is empty.
- Acceptance criteria: approved snapshot path exists without behavior change.
- Current status: implemented as a pure `MemorySnapshot` / `MemorySnapshotItem`
  prompt view seam; prompt_builder remains snapshot-only and does not decide recall.
- Risk: prompt pollution.
- Stop condition: prompt_builder starts deciding recall.
- Commit strategy: behavior-neutral seam.

### Slice 4: User confirmation UX contract for retain/update/forget

- Goal: Define Ask User style approval choices and Other/free-text behavior.
- Non-goal: no TUI rewrite and no direct backend memory decision.
- Files likely touched: memory approval contract, runtime event/display tests.
- Tests first: accept/edit/reject/session-only/forget choices; TUI does not import policy/store.
- Expected behavior: approval can be represented but not auto-triggered broadly.
- Acceptance criteria: confirmation semantics are recoverable and checkpoint-safe if pending.
- Readiness note: Slice 3 now provides the approved snapshot sink; Slice 4 should
  define the user-facing approval contract that produces retain/update/forget
  decisions before any store or retrieval implementation exists.
- Current status: implemented as a pure `memory_confirmation` contract that maps
  retain/update/forget decisions to user-facing choices and result objects; it
  does not write storage, create runtime pending state, or modify TUI/input flow.
- Risk: adding a new pending status too early.
- Stop condition: requires runtime core-loop rewrite.
- Commit strategy: contract first, runtime integration later.

### Slice 5: Forget/update safety and audit summary

- Goal: Make deletion/update semantics explainable and highest-priority.
- Non-goal: no real persistence unless explicitly authorized after store review.
- Files likely touched: audit contracts, policy tests.
- Tests first: forget beats recall; audit does not include sensitive full text.
- Expected behavior: safe operation results.
- Acceptance criteria: every memory operation can produce a user-visible explanation.
- Readiness note: Slice 5 can now consume `MemoryDecision` plus
  `MemoryConfirmationResult`, but should still produce audit/operation summaries
  only. It must not introduce real persistence or provider writes unless a later
  store slice is explicitly authorized.
- Current status: implemented as a pure operation intent / audit summary contract.
  It maps confirmation results to retain/update/forget/reject/use-once/clarify
  intents without writing storage or recording sensitive full text.
- Risk: incomplete delete semantics across future providers.
- Stop condition: external providers cannot support deletion contract.
- Commit strategy: policy/audit tests before store integration.

### Slice 6: External MemoryProvider adapter seam

- Goal: Define provider protocol for internal store, MCP resources, future vector provider.
- Non-goal: no MCP resources implementation, no vector DB, no networking.
- Files likely touched: provider protocol and fake provider tests.
- Tests first: provider supplies candidates/snapshots; policy remains local; provider disabled fallback.
- Expected behavior: optional provider seam only.
- Acceptance criteria: external provider cannot bypass policy or base registry.
- Readiness note: Slice 5 now provides safe operation/audit intent language.
  Slice 6 should define provider inputs/outputs only; providers must not bypass
  MemoryPolicy, confirmation, or operation audit contracts.
- Current status: implemented as a fake/provider protocol seam. It can project
  deterministic provider fixtures into MemoryCandidate / MemorySnapshot inputs,
  but it is not a real provider, not an MCP client, and performs no IO/network.
- Risk: protocol becomes too generic/anemic.
- Stop condition: provider needs secrets/network.
- Commit strategy: fake-only protocol tests.

### Slice 7: Dogfooding and docs

- Goal: Test UX with fake clients and no real personal data.
- Non-goal: no real user-profile persistence.
- Files likely touched: dogfooding smoke tests, README/Roadmap docs.
- Tests first: remember/reject/forget flows with fake memory store.
- Expected behavior: no secret reads, no real provider calls.
- Acceptance criteria: no P0/P1/P2 before any release candidate.
- Readiness note: Slice 6 now provides fake provider fixtures, but Slice 7
  should still dogfood deterministic UX scenarios only. It must not read real
  sessions/runs/logs or persist real memory.
- Current status: implemented as deterministic dogfooding tests and a reviewable
  checklist in `docs/MEMORY_DOGFOODING.md`; no real storage, provider, network,
  LLM, or private data is used.
- Risk: dogfooding accidental real data.
- Stop condition: requires real private memory data.
- Commit strategy: tests/docs closure.

## Why this is not `memory.json + prompt injection`

The proposed design makes a memory record pass through candidate extraction,
policy decision, possible user approval, provider/store write, safe retrieval,
snapshot selection, and prompt injection. Storage is only one implementation
detail behind policy and governance. This preserves First Agent's runtime
boundaries and gives users the right to understand, edit, reject, and forget
what the agent remembers.
