# Architecture Decision: Pre-loop MEMORY_RECALL Dual Path

Date: 2026-05-24
Status: decided
References: UNIFIED_RUNTIME_FLOW_CONTRACT.md Section 2, 5.1

## 1. Problem Statement

Memory recall has two implementation paths:

**Path A — Prompt Injection (pre-loop, direct):**
```
chat() → refresh_runtime_system_prompt()
       → _memory_runtime.snapshot_for_prompt()
       → build_system_prompt(memory_snapshot=...)
       → state.set_system_prompt()
```
This path actually injects approved memory into the system prompt. Users see
"已加载 X 条相关记忆" in chat. Does NOT go through RuntimeActionDispatcher.

**Path B — MEMORY_RECALL Dispatch (turn-end, dispatcher):**
```
turn-end hook → dispatcher.route_from_runtime_loop()
              → MEMORY_RECALL → MemoryRecallHandler
              → build_memory_snapshot → evidence
```
This path generates dispatcher evidence. Does NOT inject into system prompt.

Two paths, two different lifecycle points (pre-loop vs turn-end), serving
two different purposes. Are they problematic? Should they be unified?

## 2. Analysis

### 2.1 They Serve Different Purposes

| Concern | Path A (injection) | Path B (dispatch) |
|---|---|---|
| When | Pre-loop (chat entry) | Turn-end (post-model-call) |
| Purpose | Context construction — build system prompt with memory context | Evidence collection — record that memory recall was attempted |
| Goes through dispatcher | No | Yes |
| User-visible effect | Memory in system prompt affects model behavior | Internal evidence only |
| Contract classification | "pre-loop explicit Memory evaluation" (Contract §2) | "turn-end RuntimeAction hook" (Contract §2) |

### 2.2 Both Are Correct For Their Purpose

Path A is the correct place for context injection — it happens before the model
call, directly in the system prompt build phase. Moving it through the dispatcher
would add unnecessary indirection and coupling between context construction and
the evidence system.

Path B is the correct place for evidence — it records what happened at turn-end,
through the dispatcher's evidence model.

### 2.3 Forcing Unification Would Add Risk

If we forced Path A through the dispatcher:
- `refresh_runtime_system_prompt()` would depend on dispatcher availability
- All tests that call `chat()` without a dispatcher would break
- The dispatcher would become a hard dependency of context construction
- This violates the principle that context construction is a core infrastructure
  concern, not a subsystem that should go through the dispatcher

## 3. Decision

**Do not unify the two paths.** They serve different purposes at different
lifecycle points and will remain separate.

However, to close the evidence gap for audit/debug:

1. Add a lightweight pre-loop `on_memory_injected` runtime event that is emitted
   when Path A injects memory into the system prompt (currently done via
   `memory_injected_event()` in `chat()` line 427 — already exists).
2. Document that MEMORY_RECALL (dispatcher) evidence and memory_injected
   (runtime event) evidence are complementary, not competing.
3. For the User-Usable MVP, the injection path is already sufficient — users
   see "已加载 X 条相关记忆" and memory content enters the system prompt.

## 4. Impact on WP-A (Memory That Actually Helps MVP)

This decision means WP-A can proceed immediately without waiting for path
unification. The injection path already works. WP-A should focus on:

- Making the memory recall effect more visible to users
- Adding memory management commands (show/forget)
- Focused E2E test: store → recall → visible in next chat

## 5. Future Consideration

If a future requirement demands unified pre-loop evidence (e.g., every
pre-loop action must produce dispatcher evidence), the right approach is:

1. Add a pre-loop hook in `chat()` (before system prompt refresh)
2. Register MEMORY_RECALL there as a pre-loop dispatch
3. Use the dispatcher's result to decide injection content

This would be an Architecture Extension (new pre-loop hook), not a
modification of the existing turn-end hook. Not needed for MVP.
