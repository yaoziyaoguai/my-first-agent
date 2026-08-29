# 019 Portable Automation Core — Independent Review

Review date: 2026-08-29

Bound delivery identity:

- overlay root: `79859f7c57c00da2ca73daee2737842b21f6430d70847b805d8acc693fde455f`
- seal SHA-256: `f9bf90ad0df0ced05ff4394acef04b563ae136669569a994bf6f3c38a83e68d1`
- verifier SHA-256: `2308298b35123022490cbc2034a315fbc1b02e5b6868b7d4b56c1501b0acc8fe`
- runner SHA-256: `f42bcd99ec522876a247420a5e3aee106a64913a2281cff5d568b3c1132e90de`
- materialized root: `05ba50896ea1e40af28407e9e2593e367b50fb1eccfd12626cccf2f7cb6940a4`
- wheel SHA-256: `d1b20b328bfa4d828332c26d94a8083056d895f5361e790a1ebc63973719b5e5`
- source full gate: `2654 passed, 1 skipped`
- materialized full gate: `2650 passed`

<!-- SPEC_PRODUCT_REVIEW_START -->
## Spec / Product Review

Verdict: PASS

The frozen portable-core contract, C1–C25 claim map and J1–J13 journey map were reviewed
against the sealed source and the deterministic U1/U2A runner. Definition, approval, claim,
dispatch, provider-outcome, budget, owned-workspace, cleanup, handoff and purge transitions all
have closed typed identities and fail-closed mutations. The runner requires three fresh repository,
workspace, supervisor and executor identities and rejects a false or missing journey subcheck,
claim, counter or delivery digest.

The delivered surface remains intentionally narrower than a host scheduler: create is inactive,
activation is human-first and digest-bound, reconcile is an external caller, and missing host
capabilities produce one closed `NEEDS_019_CONFIG` result before effects. No receipt field contains
task text, credentials, absolute paths, model output, browser content or tool output. Source and
materialized full gates passed on the bound identity; the materialized wheel was imported from a
neutral working directory and the installed console entrypoints were checked against their exact
modules.

No host profile is qualified by this review. Durable local management and unattended execution
remain unavailable until a separate host-profile seal, real-host receipt and review pass.

The post-audit reducers were also reviewed against this identity. Snapshot decode reconstructs
the authority grant from the decoded body instead of trusting mutually recomputed digests, and
safe terminal occurrence outcomes are admitted only from claim phases that can truthfully produce
them. J7 now proves cutover after the public dispatched/running transitions rather than relying on
an illegal claimed-to-completed shortcut.
<!-- SPEC_PRODUCT_REVIEW_END -->

<!-- STANDARDS_ARCHITECTURE_REVIEW_START -->
## Standards / Architecture Review

Verdict: PASS

The implementation preserves the architecture invariants. `AgentRuntime.run_turn` remains the
only production model/tool loop; the only provider generation and `ToolRuntime.invoke` sites are
inside `agent/runtime/loop.py`. `ScheduledOccurrenceCaller` delegates to that Runtime and cannot
write checkpoints, call providers or invoke tool callables directly. `KernelToolRuntime` remains
the sole interpreter of background action authority and revalidates the live claim at prepare and
invoke.

`agent/automation` contains only platform-neutral domain, repository-port, lifecycle, reconcile,
workspace and wake contracts. Its sealed boundary scan rejects concrete persistence/process/
sandbox/browser backends and the platform tokens `launchd`, `systemd`, `seatbelt` and `playwright`.
No compatibility fallback, service locator, dormant host flag or second approval path was added.

The delivery chain reconstructs the 009 candidate plus the sealed current delta without writing
Git objects, restores inherited read-only controls needed by the full suite, excludes mutable
receipt/wheel/review/log evidence from the tree being proved, builds a non-editable wheel and
checks exact console origins. Ruff and `git diff --check` passed before the final full gates.
Platform-specific POSIX/macOS code belongs only in the subsequent optional host-profile namespace
and cannot downgrade or silently extend this portable PASS.

The clean-tree verifier binds the already-qualified Playwright browser bundle explicitly while
retaining an empty materialized HOME; it does not inherit user configuration or introduce a
product browser fallback. The browser path is used only by the detached test environment and is
not written to the seal, wheel or receipt.
<!-- STANDARDS_ARCHITECTURE_REVIEW_END -->
