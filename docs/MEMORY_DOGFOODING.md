# Deterministic Memory UX Dogfooding

This checklist closes Stage 3 with fake scenarios only. It is for reviewing the
Memory UX contract chain without real private data, real storage, real provider
calls, real LLM calls, networking, or real sessions/runs/agent_log reads.

## Scope

- Use fake scenarios only.
- Do not read no real sessions/runs/agent_log content.
- Do not write real memory.
- Do not call a real provider, MCP server, network, or LLM.
- Verify the user can understand retain / edit / reject / use_once choices.
- Verify forget / update are explicit operation intents, not real mutations.
- Verify sensitive redaction in confirmation copy and audit summary.
- Verify fake provider candidates cannot bypass policy or confirmation.
- Verify snapshot rendering preserves provenance, budget, and safety notes.

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
