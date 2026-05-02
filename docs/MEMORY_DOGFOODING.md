# Deterministic Memory UX Dogfooding

This checklist started as the Stage 3 deterministic UX review and now includes
the Stage 6 Manual UX Dogfooding Runbook over the fake local store and governed
snapshot seam. It uses fake scenarios only and never uses real private data,
real storage, real provider calls, real LLM calls, networking, or real
sessions/runs/agent_log content.

## Scope

- Use fake scenarios only.
- no real sessions/runs/agent_log content.
- Do not write real memory.
- Do not call a real provider, MCP server, network, or LLM.
- Verify the user can understand retain / edit / reject / use_once choices.
- Verify forget / update are explicit operation intents, not real mutations.
- Verify sensitive redaction in confirmation copy and audit summary.
- Verify fake provider candidates cannot bypass policy or confirmation.
- Verify snapshot rendering preserves provenance, budget, and safety notes.

## Stage 6 Manual UX Dogfooding Runbook

This runbook is for a human reviewer. It is not runtime integration and not
automatic memory activation. Use fake/local deterministic data only.

Hard safety markers:

- Do not use real private data.
- fake/local deterministic data only.
- no real sessions/runs/agent_log.
- no real provider.
- no MCP server.
- no LLM call.
- no network.
- no real long-term memory write.
- No runtime integration.
- No automatic memory activation.

Governance path to review:

```text
DeterministicMemoryPolicy
-> MemoryConfirmationRequest
-> MemoryOperationIntent
-> MemoryAuditSummary
-> InMemoryMemoryStore
-> build_memory_snapshot_from_store
-> MemorySnapshot
-> prompt_builder
```

Learning boundary: this path proves the seams are understandable, not that
First Agent has automatic memory. `prompt_builder` remains formatting-only and
must receive a `MemorySnapshot`; it must not read the fake store directly.

### Fake deterministic fixtures

Use only these fake strings and fake records:

- retain preference: `remember that I prefer concise answers`
- update preference: `update memory: prefer detailed implementation notes`
- forget preference: `forget that I prefer concise answers`
- use_once preference: choose `SESSION_ONLY` for the retain preference
- reject preference: choose `REJECT` for the retain preference
- sensitive candidate: `remember that my api token is sk-secret`
- fake local store record: an `InMemoryMemoryStore` record created from approved
  `MemoryOperationIntent` + `MemoryAuditSummary`
- fake governed snapshot: a `MemorySnapshot` produced by
  `build_memory_snapshot_from_store`

### Manual reviewer checklist

1. accept retain
   - Action: run the fake retain preference through `DeterministicMemoryPolicy`,
     build a `MemoryConfirmationRequest`, choose accept, build
     `MemoryOperationIntent`, build `MemoryAuditSummary`, and apply it to
     `InMemoryMemoryStore`.
   - Expected behavior: one fake `MemoryRecord` is retained with provenance,
     scope, safety summary, and audit id.
   - Safety checks: no real user data; no real long-term memory write; store does
     not call policy or confirmation.
2. edit before retain
   - Action: choose edit and provide `I prefer concise but complete answers.`
   - Expected behavior: operation intent uses the edited text, then fake store
     stores only that approved summary.
   - Safety checks: edited content is still fake; no runtime integration.
3. reject retain
   - Action: choose reject for the retain request.
   - Expected behavior: operation type is reject and fake store write is skipped.
   - Safety checks: rejection cannot be upgraded to retain.
4. use_once
   - Action: choose session-only for the retain request.
   - Expected behavior: operation type is use_once and fake store write is
     skipped.
   - Safety checks: current-session usage is not durable memory.
5. forget intent
   - Action: run the fake forget preference, confirm it, and apply to a fake store
     that already has the matching fake record.
   - Expected behavior: the fake record is removed from in-memory state only.
   - Safety checks: no real files, records, sessions, or logs are deleted.
6. update intent
   - Action: run the fake update preference, choose edit if needed, and apply to
     a fake store with the matching fake record.
   - Expected behavior: the fake record content changes in memory only.
   - Safety checks: update is not real persistence and cannot bypass audit.
7. sensitive redaction
   - Action: run the fake sensitive candidate through policy and confirmation
     boundary checks.
   - Expected behavior: obvious secret-like text is rejected or represented only
     as redacted summary; `sk-secret` must not appear in audit summary or
     snapshot item content.
   - Safety checks: audit summary explanation is understandable without leaking
     sensitive text.
8. store to governed snapshot
   - Action: call `build_memory_snapshot_from_store` with fake store records and
     explicit `MemorySnapshotBuildOptions`.
   - Expected behavior: output is `MemorySnapshot`, with deterministic ordering,
     scope filtering, budget/omitted_count, provenance, and safety_filter_summary.
   - Safety checks: generator does not write store, does not apply operation
     intent, does not call provider/LLM/network, and does not output prompt text.
9. prompt_builder boundary
   - Action: pass the generated `MemorySnapshot` to prompt construction.
   - Expected behavior: `prompt_builder` consumes `MemorySnapshot` only.
   - Safety checks: `prompt_builder` does not import or read `InMemoryMemoryStore`
     and does not perform retrieval.

## Dogfooding checklist

1. Retain preference: start with `remember that I prefer concise answers`, show
   the confirmation question, choose accept, and inspect the retain operation
   intent plus audit summary.
2. Edit before retain: choose edit, provide a rewritten preference, and confirm
   the edited content is used only in operation intent.
3. Reject: choose reject and confirm no write/retain intent is produced.
4. Use once: choose use_once and confirm it is session-only, not durable retain.
5. Forget: start with `forget that I prefer concise answers`, confirm forget,
   and verify it is a forget intent only.
6. Update: start with `update memory: prefer detailed answers`, confirm update,
   and verify it is an update intent only.
7. Sensitive request: use a fake secret-like string and confirm policy rejects
   or confirmation/audit redacts content.
8. Fake provider: use deterministic provider fixtures and verify provider output
   is only candidate/snapshot input.
9. Snapshot rendering: render a fake snapshot and verify source provenance,
   safety filter text, and no retrieval/policy behavior in prompt construction.

## Manual review questions

- Does the UX clearly say what may be remembered and why?
- Can the user edit, reject, or use information only once?
- Are forget/update flows explicit and non-destructive at this stage?
- Does the audit summary explain what happened without logging sensitive full
  text?
- Does the fake provider remain subordinate to First Agent policy,
  confirmation, and operation/audit contracts?
