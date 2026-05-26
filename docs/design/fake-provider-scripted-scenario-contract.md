# FakeProvider Scripted Scenario Contract

- **Date:** 2026-05-26
- **Status:** active
- **Replaces:** implicit "FakeProvider = Chinese NLU" assumption in earlier dogfood tests
- **Supersedes:** keyword/n-gram/stop-word based intent recognition approach in `_resolve_tool_use()`

## 1. What FakeProvider Is

FakeProvider is a **deterministic ModelProvider test double**. It implements the `ModelProvider`
protocol (`create()` / `stream()`) and outputs pre-scripted, fixed responses. Its sole purpose
is to prove that the unified runtime flow (core.chat → loop.py → call_model → Tool Pipeline /
Memory / SubAgent branch points) functions correctly when the model returns structured outputs.

FakeProvider and RealProvider share:

- The same `ModelProvider` protocol (`create()` / `stream()`)
- The same unified runtime path (`core.chat → run_main_loop → call_model`)
- The same Tool Pipeline, Memory hooks, SubAgent routing, summary/evidence paths

They differ only in **how** they produce `ProviderResponse`: FakeProvider uses deterministic
scripted outputs; RealProvider calls external LLM APIs.

## 2. What FakeProvider Is NOT

FakeProvider is **NOT**:

1. **A Chinese NLU system.** It must not attempt to understand arbitrary natural language
   intent through keyword matching, n-gram extraction, stop-word filtering, or any other
   heuristic text analysis.

2. **A planner.** It must not decide which tool to call based on "understanding" the user's
   natural language request.

3. **An intent recognizer.** It must not classify user messages into tool/memory/subagent
   intent categories based on Chinese/English keyword overlap.

4. **A product capability demo.** FakeProvider's scripted tool_use responses prove the
   runtime can handle tool_use events — they do NOT prove the agent understands Chinese.

5. **A substitute for real-provider semantic eval.** Questions like "can the agent correctly
   decide which tool to call when a user asks in natural Chinese" can ONLY be answered by
   real-provider eval with actual LLM inference.

## 3. Scripted Scenario Contract

### 3.1 Scenario Definition

A **scripted scenario** is a fixed mapping: `(input_pattern, tool_set) → ProviderResponse`.

The mapping is deterministic, pre-defined, and does not analyze the semantic content of the
input beyond exact-match or simple structured pattern matching.

### 3.2 Supported Scripted Output Types

| Output Type | Description | Used For |
|---|---|---|
| `final_text` | Plain text response with `stop_reason="end_turn"` | Ordinary chat, echo, limitation message |
| `tool_call` | `ToolUseBlock` with `stop_reason="tool_use"` | Proving Tool Pipeline branch point |
| `malformed_tool_call` | Malformed tool_use (missing name, bad input) | Proving error handling |
| `provider_error` | `ProviderResponseError` | Proving provider error recovery |
| `memory_action_fixture` | Reserved — not yet supported in fake | Future: Memory branch point proof |
| `subagent_action_fixture` | Reserved — not yet supported in fake | Future: SubAgent branch point proof |

### 3.3 Scenario Matching Rules

Only the following matching strategies are valid for scripted scenarios:

1. **Exact match** — user message (after trim + lowercase) equals a known trigger phrase.
   Example: `"create a demo note"` in `_DEMO_TOOL_TRIGGERS`.

2. **Tool name literal in message** — the exact tool name string (e.g. `"demo.echo_task_summary"`)
   appears verbatim in the user message. This is a debug/convenience shortcut.

3. **Structured prefix match** — a known prefix pattern like `"/tool:"` or `"/scenario:"`
   followed by a registered scenario ID. (Not yet implemented; reserved for Phase 2.)

The following strategies are **NOT valid** for FakeProvider:

- Chinese n-gram extraction and overlap scoring (`_tool_desc_keywords`)
- English keyword/token fuzzy matching against tool descriptions (strategy 2)
- Scoring thresholds tuned against false positive rates (threshold 30→40→60)
- Chinese stop-word filtering to suppress false positives
- Any approach that requires analyzing the semantic content of user messages

### 3.4 Unmatched Inputs

When the user message does not match any scripted scenario:

- `_resolve_tool_use()` returns `None`
- `FakeProvider.create()` returns a plain text response (`stop_reason="end_turn"`)
- The response should clearly indicate this is a fake/deterministic mode limitation,
  NOT pretend to understand the request

### 3.5 Legacy Compatibility

The current `_resolve_tool_use()` three-tier strategy (full name → name token → description
keyword → legacy trigger) is **deprecated as a general intent recognition mechanism**.

It is retained temporarily as a **compatibility fixture** with the following constraints:

- Strategies 2 and 3 (name token, description keyword) are marked `DEPRECATED`
- New tests MUST use exact match or explicit scenario IDs, not fuzzy NL matching
- Removal criteria: all dogfood tests and integration tests migrated to scripted scenarios
- Sunset: v0.5+

## 4. Runtime Path Guarantee

FakeProvider's scripted tool_use output proves the following runtime invariants:

1. **Tool Pipeline is reachable** — when the model returns `stop_reason="tool_use"` with a
   valid `ToolUseBlock`, the runtime correctly enters `handle_tool_use_response → ToolExecutor`

2. **Tool result is user-visible** — the tool execution result appears in the final output

3. **Memory branch points are wired** — turn-end hooks (MEMORY_TURN_END_PROPOSAL,
   MEMORY_CONSOLIDATE, MEMORY_RECALL) execute regardless of provider type

4. **SubAgent routing is wired** — SUBAGENT_DELEGATE_L0 routing check runs regardless of
   provider type

5. **Summary/evidence is provider-agnostic** — `_emit_run_summary()` reads from dispatcher
   action_log, not from provider state

6. **Fake/real share one runtime** — no `if fake: return canned reply` shortcut exists;
   all paths go through `core.chat → run_main_loop`

## 5. What Fake/Local Proves

| Capability | How Proven |
|---|---|
| Runtime loop correctness | FakeProvider end_turn → loop terminates |
| Tool Pipeline wiring | FakeProvider tool_use → ToolExecutor → result visible |
| Memory hook wiring | Dispatcher action_log shows memory.* events |
| SubAgent routing wiring | Dispatcher action_log shows subagent.* events |
| Summary honesty | action_log filtering prevents lifecycle no-op overclaim |
| Streaming path | FakeProvider.stream() → deltas → collect → response |
| Provider swap safety | Same runtime path with FakeProvider vs RealProvider |
| Error recovery | Scripted provider_error → runtime handles gracefully |

## 6. What Fake/Local Does NOT Prove

| Capability | Why Not |
|---|---|
| Chinese NL understanding | FakeProvider does no LLM inference |
| Tool selection accuracy | FakeProvider uses scripted triggers, not semantic matching |
| Memory relevance judgment | MemoryPolicy in fake path uses deterministic heuristics |
| SubAgent task decomposition | No real planning occurs in fake path |
| Multi-tool chaining | FakeProvider returns single tool_use; no multi-step planning |
| Conversation quality | Responses are echoes, not reasoned replies |
| Model safety/alignment | No real model inference occurs |
| Production readiness | Requires real LLM for semantic understanding |

## 7. When to Use Real-Provider Semantic Eval

The following questions require real-provider eval (opt-in, gated by
`MY_FIRST_AGENT_RUN_REAL_LLM_E2E=1`):

1. Does the agent correctly identify which tool to call from natural Chinese requests?
2. Does the agent correctly decide when to store/retrieve/consolidate memories?
3. Does the agent correctly delegate to subagents based on task characteristics?
4. Does the agent produce helpful, safe, and contextually appropriate responses?
5. Does the agent correctly handle ambiguous or underspecified requests?

These evals require real LLM API access and are not run by default in CI.

## 8. Test Taxonomy

### Category A: Deterministic Fake Runtime Scenarios

- Use fixed scripted provider outputs
- Prove runtime branch points (tool, memory, subagent wiring)
- No real API, no NLU dependency
- Run on every commit

### Category B: Fake/Local UX Smoke

- Ordinary chat, help, status
- No crash, no max-loop, no overclaim
- No NLU dependency (FakeProvider returns echo/final_text)
- Run on every commit

### Category C: Real-Provider Semantic Eval

- Natural language asks model to decide tool/memory/subagent intent
- Requires real LLM API (opt-in gate)
- Not run by default
- Human judgment required for quality assessment

## 9. Migration Plan

### Immediate (this round)

1. Mark strategies 2/3 in `_resolve_tool_use()` as `DEPRECATED`
2. Add `_DEMO_TOOL_TRIGGERS` as the **only** supported scripted scenario set
3. Update dogfood Case D to use exact trigger phrase (not arbitrary NL)
4. Update test_fake_provider_decision.py to classify NL-dependent tests
5. Update sweep report to clarify what fake does/doesn't prove

### Short-term (v0.4+)

1. Add explicit scenario ID system (`/scenario:tool_write_note`)
2. Add scripted memory/subagent fixtures
3. Remove strategies 2/3 from `_resolve_tool_use()`
4. Remove `_tool_desc_keywords()` Chinese n-gram extraction
5. Remove Chinese stop-word filtering

### Medium-term (v0.5+)

1. Real-provider semantic eval harness
2. Separate eval suite for NL intent accuracy
3. FakeProvider reduces to pure echo + scenario ID dispatch
