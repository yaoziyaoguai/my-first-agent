# Global Architecture Debt Remediation Plan

## 1. Goal

Reduce the current global architecture debt without changing user-visible behavior:

- Lower monolith risk in `agent/core.py`, `main.py`, `agent/memory.py`, and `agent/confirm_handlers.py`.
- Move runtime loop orchestration out of `core.py` while keeping `chat()` as the stable public API.
- Tighten high-risk `TransitionResult` usage around user reply and confirmation state transitions.
- Keep Agent Core, Memory, Tool execution, CLI, and Confirmation responsibilities explicit.
- Add tests that prove behavior and architecture boundaries did not drift.

## 2. Non-goals

- Do not implement Skill.
- Do not implement SubAgent.
- Do not implement new Memory features.
- Do not change Memory governance, approval, pending review, or inline confirmation semantics.
- Do not implement backend abstraction, DB, graph, embedding, or vector store.
- Do not split files mechanically just to reduce line count.

## 3. P1 Repair Plan

### P1-1 `core.py` monolith risk

Extract the main runtime loop orchestration into `agent/loop.py`.

- Move the loop driver and loop field helper behind a small dependency object.
- Keep `core.py` responsible for `chat()` and assembling runtime dependencies.
- Keep UI rendering, Memory internals, and provider-specific behavior out of `agent/loop.py`.
- Preserve checkpoint, request-user-input, tool execution, and memory runtime hook behavior.
- Prove behavior with existing checkpoint, memory session hook, and architecture boundary tests.

### P1-2 `TransitionResult` integration

Do not mechanically migrate every state mutation. Focus on high-risk user reply boundaries.

- Keep `pending_user_input_request -> awaiting_user_input -> handle_user_input_step()` protected.
- Ensure unknown `awaiting_kind` continues through the generic user-input transition path.
- Keep `memory_confirmation` and `memory_inline_confirmation` delegated to Memory interaction services.
- Leave low-risk direct mutations in tool/plan confirmation handlers for later if changing them would obscure behavior.
- Add characterization tests before refactoring so the confirmation boundary stays stable.

## 4. P2 Repair Plan

### P2-1 `main.py` mixed responsibilities

Split CLI support into thin modules:

- `agent/cli/input_backends.py` owns input backend selection and user-input event reading.
- `agent/cli/display.py` owns console/display event bridging.
- `agent/cli/commands.py` owns maintenance command routing.
- `main.py` remains the thin process entrypoint and does not duplicate runtime behavior.

### P2-2 deprecated compatibility bridge

Only remove compatibility code when it is clearly unused and covered by tests. Otherwise keep it in place and make the boundary clearer.

### P2-3 `memory.py` orchestration size

Move consolidation and emergence runtime orchestration to a thin helper module.

- Do not change Memory domain models.
- Do not change `MemoryStore` or `FilesystemMemoryStore`.
- Do not change governance, T1/T2/T3, `pending_review`, or inline confirmation.

### P2-4 `confirm_handlers` unit coverage

Add pure unit tests proving `confirm_handlers` is a router, not a Memory/Tool/Checkpoint business layer.

- Cover `memory_confirmation`, `memory_inline_confirmation`, unknown `awaiting_kind`, reject/other/edit-style replies where practical.
- Use fakes/mocks for `ConfirmationContext`.
- Keep store writes inside Memory interaction services.

## 5. Test Proof

Run and report:

- `ruff check agent tests scripts`
- `python -m pytest tests/test_architecture_boundaries.py tests/test_checkpoint_ownership.py -q`
- `python -m pytest tests/test_memory_interaction.py tests/test_memory_interactive_confirmation.py tests/test_memory_session_hook.py tests/test_memory_emergence.py -q`
- `python -m pytest tests/test_memory_fs_store.py tests/test_memory_consolidation_pipeline.py tests/test_memory_array_filesystem_e2e.py -q`
- Focused CLI/core/transition/confirm-handler tests added in this remediation.
- Full pytest with a temporary `HOME`.
