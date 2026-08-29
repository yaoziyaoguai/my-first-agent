# 017 Sandboxed Workspace Execution — Independent Review

- Date: 2026-08-27
- Status: **PASS**
- Reviewer: fresh Codex CLI read-only session
  `01a042e8-a955-7903-92d9-602eb82acb08`
- Scope: corrected macOS native Seatbelt 017 only；superseded Docker design/history is
  not promotion evidence。

## Bound delivery identity

- ordinary overlay root：
  `0c261e7f3d38a782ccbe880693614e9bd218ea1d979f2a17fb79432fbac4d6a1`
- entry count：`261`
- delivery seal SHA-256：
  `527f47ce26a9eb2f8311fa4a78684dd6854f0e9dfe81dac91a31bc89817989d1`
- verifier SHA-256：
  `420617c05052374a511375a70193c7075ce66293a1e66a6f0f7610a798a7b203`
- runner SHA-256：
  `91e38340414f48809d023b446da3e5e3da04dfe771c3d69fe403572228f73184`
- materialized wheel SHA-256：
  `0ddb10f4bdef4949b9afa395232a626015840e20a9285e46a8aaf428fdf2c3a1`
- U2 receipt SHA-256：
  `c8b9c66b7ad649ce6758328afc750bc15c8222dae3d83192aadf15f53f608d08`
- backend identity digest：
  `ce9f27c161d386d703fca10e466350c627cbc4a4b1d2a188a8099d9a0bb5c244`
- backend：`/usr/bin/sandbox-exec`，Darwin `24.5.0`

## Independent checks

Reviewer personally verified, without modifying repository files:

- `git diff --check` → exit 0。
- `.venv/bin/ruff check --no-cache .` → `All checks passed!`。
- `scripts/verify_017_materialized_tree.py --check-membership` →
  `261 exact entries`。
- `scripts/verify_017_materialized_tree.py --control-seal` → Green。
- hashes for seal/verifier/runner/receipt/wheel match the identity above。
- receipt summary is `U2_PASS`；three attempts each contain exactly 11 true journeys；
  false journeys = 0；workspace/temp/sentinel/journal digests each have 3 unique
  values；all attempts bind the one delivery wheel。
- `tests/architecture/test_017_sandbox_boundary.py` → 6 passed。
- selected non-nested receipt/negative-oracle tests in
  `tests/reference/test_017_real_runner.py` → 8 passed。
- scoped source scan found no retired Docker product path, compatibility fallback,
  second production model/tool loop, or ungoverned shell path；remaining Docker terms
  are negative absence tests or superseded historical text。

The reviewer itself ran inside a Codex read-only Seatbelt sandbox, so a nested
`/usr/bin/sandbox-exec` probe was refused with exit 71. This is a reviewer-environment
limitation, not a backend result. The exact current tree was therefore attested in the
outer non-nested host immediately before re-review:

- membership → `261 exact entries`
- control seal → Green
- attestation →
  `3 real attempts × 11 journeys bind the current delivery + backend identity`

The reviewer inspected this bounded Task 9 record, the digested receipt/seal/verifier,
and the verifier's fail-closed backend/identity checks, then explicitly withdrew the
initial nested-environment finding。

## Architecture and safety verdict

- `AgentRuntime.run_turn` remains the only production model/tool loop and state
  transition owner。
- `ContextManager` still owns context selection；`KernelToolRuntime` still owns tool
  preparation, approval and invocation。
- `sandbox_exec` is one governed structured-command tool；confined modes use the exact
  compiled native policy and never fall back to `local_process`。
- unavailable/confiner-refused paths are known-not-executed；effect ordering remains
  approval → durable `EXECUTING` checkpoint → invocation → durable result。
- `danger-full-access` remains an exact-approved unconfined bypass and records
  `backend=none / enforcement=unconfined` rather than pretending to be sandboxed。
- credential sentinels, denied paths, host read-back and false-completion oracles are
  part of the three real attempts；a sandbox exit code alone cannot complete a host
  artifact Goal。
- materialized loopback controls are exactly three registered tests in the same clean
  interpreter；they prove bounded local-listener behavior and are not evidence of
  public-network access。

## Promotion decision

**PASS.** The identity bound above is `accepted/delivered` for the frozen 017 macOS
native sandbox reference scope。

This does **not** claim arbitrary shell execution, browser automation, background daemon
operation, whole-PC control, Linux/Windows sandbox parity, arbitrary third-party
integration, or production-ready cross-platform isolation。
