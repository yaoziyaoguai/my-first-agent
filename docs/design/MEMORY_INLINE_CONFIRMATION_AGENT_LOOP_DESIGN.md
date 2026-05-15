# Phase 7 InlineConfirmation Agent Loop Integration Design

This document is an implementation design note for
[`docs/rfc/MEMORY_CANONICAL_RFC.md`](../rfc/MEMORY_CANONICAL_RFC.md). It is not
a new canonical spec. If this note and the RFC ever disagree, the RFC wins.

## 1. Goal

Connect the existing Phase 7 `inline_confirmation` seam to the Agent Loop so a
`ProceduralCandidate` can be confirmed in the moment without weakening memory
governance.

The target flow is:

```text
ProceduralCandidate
-> InlineConfirmationRequest
-> memory_interaction adapter
-> pending_user_input_request
-> Agent Loop Ask User
-> user response
-> InlineConfirmationResponse
-> apply_inline_confirmation_response()
-> MemoryStore
```

The design keeps three boundaries intact:

- Memory does not drive UI. Memory modules only produce
  `InlineConfirmationRequest` and consume `InlineConfirmationResponse`; they do
  not call TUI, CLI, `print()`, or `input()`.
- Agent Loop does not understand memory internals. The loop only orchestrates a
  pending user confirmation and hands the response back to memory interaction
  code.
- `pending_review` remains the default fallback. Inline confirmation is a
  smoother real-time form, not a bypass around review governance.

## 2. Non-goals

- Do not implement silent procedural retain.
- Do not implement auto approve.
- Do not let memory directly drive UI.
- Do not let `agent/core.py` parse memory-internal fields such as
  `source_evidence`, `correction_pattern`, or `correction_type`.
- Do not change the `pending_review` fallback.
- Do not implement backend abstraction, vector DB, graph, or embedding work.
- Do not change Phase 6 consolidation semantics.
- Do not make `inline_confirmation` part of the non-interactive session-end
  runtime hook.

## 3. Current seams

### InlineConfirmationRequest

Defined in `agent/memory_emergence.py`.

It is a frozen payload for the synchronous T1 confirmation form. It carries the
candidate content, source evidence IDs, correction metadata, confidence,
`confirmation_form="inline_confirmation"`, allowed actions, proposal identity,
and created timestamp.

It does not write memory, call a provider, call UI, or trigger the Agent Loop.

### InlineConfirmationResponse

Defined in `agent/memory_emergence.py`.

It represents the explicit user response:

- `accept`
- `edit_accept`
- `reject`
- `other`

It is intentionally side-effect free. Store writes only happen when this
response is passed to `apply_inline_confirmation_response()`.

### prepare_procedural_inline_confirmation_request()

Defined in `agent/memory_emergence.py`.

It validates that the candidate is procedural and T1, computes the procedural
proposal identity, and returns an `InlineConfirmationRequest`. It does not write
store state and does not interact with the user.

### apply_inline_confirmation_response()

Defined in `agent/memory_emergence.py`.

It is the write boundary:

- `accept` -> `accept_inline_confirmation()` -> procedural store write.
- `edit_accept` -> `accept_inline_confirmation(..., edited_content=...)` ->
  procedural store write with edited content.
- `reject` -> `no_write`.
- `other` -> `needs_followup`, no write.

This helper preserves the explicit-confirmation invariant. It must not be
called by `agent/core.py` directly.

### pending_review dispatch

`dispatch_procedural_candidates_to_pending_review()` in
`agent/memory_emergence.py` writes candidate JSON into `_pending/` with
`confirmation_form="pending_review"`.

This is the asynchronous T1 confirmation form and the non-interactive default.
It does not write the formal procedural store, does not auto approve, and does
not call LLMs.

### memory_interaction.py

`agent/memory_interaction.py` currently bridges Memory confirmation requests to
the existing `awaiting_user_input + pending_user_input_request` mechanism.

Current responsibilities:

- Build JSON-safe pending requests from memory confirmation requests.
- Parse user replies into memory confirmation choices.
- Handle confirmation replies by delegating to memory runtime.
- Clear pending state and save checkpoint after the explicit reply.

This is the right home for the inline adapter because it already owns the
memory-to-agent-input boundary without importing `agent.core`, provider code, or
UI frameworks.

### confirm_handlers.py

`agent/confirm_handlers.py` currently dispatches `awaiting_user_input` by
`pending_user_input_request["awaiting_kind"]`. It already routes
`awaiting_kind="memory_confirmation"` to `memory_interaction`.

Inline confirmation should add a sibling route, not a new top-level task state.

### request_user_input / Ask User

The current real boundary for model-initiated Ask User is the `request_user_input`
meta tool in `agent/tool_executor.py`. It writes a `pending_user_input_request`
with `awaiting_kind="request_user_input"` and sets task status to
`awaiting_user_input`.

Inline memory confirmation should reuse the same persisted pending-request
shape, but not pretend to be the model meta tool. It should use its own
`awaiting_kind`, for example `memory_inline_confirmation`.

## 4. Recommended architecture

```text
Phase 7 emergence detection
-> ProceduralCandidate
-> prepare_procedural_inline_confirmation_request()
-> InlineConfirmationRequest
-> memory_interaction.build_inline_confirmation_pending_request()
-> state.task.pending_user_input_request
-> state.task.status = "awaiting_user_input"
-> Agent Loop / CLI / TUI renders the existing pending request
-> user response
-> confirm_handlers.handle_user_input_step()
-> memory_interaction.handle_inline_confirmation_reply()
-> InlineConfirmationResponse
-> apply_inline_confirmation_response()
-> MemoryStore
```

Fallback path:

```text
inline unavailable / cannot interrupt / timeout / adapter failure
-> dispatch_procedural_candidates_to_pending_review()
-> _pending/
-> existing pending review CLI
```

The Agent Loop should only orchestrate:

1. Notice that memory interaction produced a pending request.
2. Persist the pending request and enter `awaiting_user_input`.
3. Resume when the user replies.
4. Hand the reply to `memory_interaction`.

The loop must not inspect evidence chains, correction patterns, proposal
archives, store metadata, or provider details.

## 5. Ownership boundary

| Concern | Owner | Must not live in |
|---|---|---|
| Emergence detection | `agent/memory_emergence.py` | `agent/core.py`, UI/TUI |
| Procedural candidate schema | `agent/memory_emergence.py` | `agent/core.py`, UI/TUI |
| Inline request payload | `agent/memory_emergence.py` | UI/TUI |
| Inline pending adapter | `agent/memory_interaction.py` | `agent/core.py`, `agent/state.py` |
| Ask User rendering | CLI/TUI/input backend | `agent/memory_emergence.py` |
| User response parsing | `agent/memory_interaction.py` | `agent/core.py`, `agent/memory_emergence.py` |
| Store write after accept/edit | `apply_inline_confirmation_response()` in `agent/memory_emergence.py` | `agent/core.py`, UI/TUI |
| Pending fallback | memory emergence/review service | `agent/core.py` internals |
| Pending archive/review CLI | `agent/memory_review.py` | `agent/core.py`, `agent/state.py` |
| Checkpoint/resume | existing `pending_user_input_request` flow plus `confirm_handlers.py` | memory domain models |
| RuntimeEvent/UI rendering | display/input layers | memory domain models |
| Provider/LLM work | Phase 6 LLM modules only | Phase 7 inline confirmation path |

## 6. Confirmation result semantics

| User result | Memory effect | Notes |
|---|---|---|
| `accept` | Write procedural memory | Must call `apply_inline_confirmation_response()` with an explicit response. |
| `edit_accept` | Write edited procedural memory | Edited content must be non-empty. |
| `reject` | No write | May return a rejected/no-write result; must not create formal memory. |
| `other` / free text | No write / `needs_followup` | Follow-up text is not approval. |
| `timeout` | No write + fallback to `pending_review` | Preserves the candidate without inventing approval. |
| invalid response | No write / retry | Keep pending if retrying; otherwise fallback to `pending_review`. |

Metadata that must survive the accepted write:

- `source_evidence`
- `correction_pattern`
- `correction_type`
- `evidence_summary`
- `confidence`
- `confirmation_form=inline_confirmation`

`silent`, `auto_retained`, and `none` remain disallowed confirmation forms for
procedural memory. Inline confirmation must never create `auto_retained`
procedural records.

## 7. Fallback strategy

The non-interactive session-end runtime hook remains `pending_review` only.
`agent.memory._maybe_run_emergence()` should keep returning
`confirmation_form="pending_review"` and `inline_confirmation="not_triggered"`
unless a future RFC explicitly changes that boundary.

Inline confirmation is allowed only when the runtime has an interactive user
input channel and can safely pause without interrupting an active tool
confirmation or tool execution chain.

Fallback cases:

- no interactive channel
- current loop cannot be interrupted safely
- active tool confirmation or tool-running state
- user timeout
- invalid adapter payload
- handler exception before explicit accept/edit

Fallback action:

1. Do not write procedural memory.
2. Dispatch the candidate to `pending_review` if it has not already been
   preserved.
3. Keep enough proposal identity for deduplication.
4. Report the route as pending review, not as inline success.

Inline failure must not drop the candidate. The fallback can preserve it in
`_pending/` because `dispatch_procedural_candidates_to_pending_review()` already
deduplicates by deterministic proposal identity.

## 8. Minimal implementation plan

### agent/memory_interaction.py

- Needs change: yes.
- Minimal change:
  - Add `build_inline_confirmation_pending_request(request, origin_status)`.
  - Add `parse_inline_confirmation_reply(user_text, pending)`.
  - Add `handle_inline_confirmation_reply(user_text, ctx, store, ...)`.
  - Convert only explicit accept/edit into `InlineConfirmationResponse`.
  - Convert reject/other/timeout into no-write or fallback.
- Why: this module already owns the memory confirmation bridge to
  `pending_user_input_request`.
- Boundary: it should not run emergence detection and should not know UI/TUI
  rendering details.

### agent/confirm_handlers.py

- Needs change: yes.
- Minimal change:
  - Add one `awaiting_kind == "memory_inline_confirmation"` branch in
    `handle_user_input_step()`.
  - Delegate to `memory_interaction.handle_inline_confirmation_reply()`.
- Why: this is the existing dispatcher for `awaiting_user_input` variants.
- Boundary: it should not parse source evidence, correction patterns, or store
  metadata.

### agent/core.py

- Needs change: maybe.
- Minimal change if needed:
  - Only receive a prepared pending request from memory interaction code and set
    `state.task.pending_user_input_request`.
  - Enter `awaiting_user_input` and emit the existing user-input request event.
- Why: core may be the orchestration point that pauses the loop.
- Boundary: no emergence rules, no review archive logic, no direct store write,
  no evidence parsing.

### agent/memory.py

- Needs change: maybe.
- Minimal change if needed:
  - Keep `_maybe_run_emergence()` non-interactive and pending-review-only.
  - If an interactive path needs candidate generation, expose a thin helper that
    returns candidates or requests without writing store.
- Why: session-end runtime behavior must remain stable.
- Boundary: no UI calls and no Ask User calls.

### agent/state.py

- Needs change: likely no.
- Minimal change:
  - Prefer reusing `status="awaiting_user_input"` plus
    `pending_user_input_request["awaiting_kind"]`.
- Why: no new top-level task status is needed.
- Boundary: avoid checkpoint schema churn.

### tests/test_memory_interaction.py

- Needs change: yes, or add coverage to the existing
  `tests/test_memory_interactive_confirmation.py`.
- Minimal change:
  - Test inline request -> pending dict.
  - Test response parsing for accept, edit, reject, other, invalid input.
  - Test JSON round trip.
- Why: this is the missing P1-2 coverage before implementation.

### tests/test_memory_session_hook.py

- Needs change: yes.
- Minimal change:
  - Assert non-interactive emergence hook still dispatches `pending_review`.
  - Assert it still reports `inline_confirmation="not_triggered"`.
- Why: protects fallback default.

### tests/test_checkpoint_ownership.py

- Needs change: yes.
- Minimal change:
  - Update writer/clearer allowlist only for the intentionally added inline
    interaction handler.
- Why: protects the pending-state ownership boundary.

## 9. Test plan

1. `InlineConfirmationRequest` -> `pending_user_input_request`.
2. Pending request includes accept / reject / edit / other.
3. accept -> apply response -> write procedural.
4. edit_accept -> write edited procedural.
5. reject -> no-write.
6. other/free-text -> no-write / needs_followup.
7. timeout -> no-write / fallback pending_review.
8. Non-interactive runtime hook remains pending_review.
9. pending_review fallback does not regress.
10. No silent procedural retain.
11. No auto approve.
12. No direct store write from core.
13. Core does not understand memory internals.
14. Checkpoint ownership / pending writer boundary remains explicit.
15. Tests do not read `.env`.
16. Tests do not read `agent_log.jsonl`.
17. Tests do not read real `sessions/runs`.
18. Tests do not call real LLM.

## 10. Open questions

- Should inline confirmation reuse `awaiting_kind="memory_confirmation"` with a
  subtype, or add `awaiting_kind="memory_inline_confirmation"`?
  - Recommendation: add `memory_inline_confirmation` to keep procedural
    emergence separate from explicit retain/update/forget confirmation.
- Should timeout always fallback to `pending_review`, or can it drop/no-write?
  - Recommendation: fallback to `pending_review` to avoid losing a candidate
    that already passed the emergence gate.
- Should inline confirmation be available in both CLI and TUI?
  - Recommendation: yes, but only through the shared pending request contract;
    no UI-specific memory logic.
- Does Agent Loop need a new `TaskState.status`?
  - Recommendation: no. Reuse `awaiting_user_input` and route by
    `awaiting_kind`.
- Where should interactive emergence candidate generation happen?
  - Recommendation: use a thin memory service/helper that returns a request or
    fallback dispatch result. Do not put detection or store logic in core.
