# 019 macOS Host Profile — Independent Review

Review date: 2026-08-29

Bound delivery identity:

- overlay root: `b7161451a2b9ae5e272689fa4aa478ff55cb372ea8d2558f773147fe76f6ea27`
- seal SHA-256: `c7aa077c875a26945af8b5242838428d6c85478b276ebbd63c25c030da36dd64`
- verifier SHA-256: `4d5da41749c427bcb9cd90271ca0473a6af5432c5bd64f972b7b376bf58fe662`
- runner SHA-256: `ec7e35a9154a872ea1f680d0fec7f6493805110fdaf407d4e0501fe6d380d72e`
- materialized root: `05ba50896ea1e40af28407e9e2593e367b50fb1eccfd12626cccf2f7cb6940a4`
- wheel SHA-256: `d1b20b328bfa4d828332c26d94a8083056d895f5361e790a1ebc63973719b5e5`
- source full gate: `2654 passed, 1 skipped`
- materialized full gate: `2650 passed`

<!-- SPEC_PRODUCT_REVIEW_START -->
## Spec / Product Review

Verdict: PASS

The bounded macOS host profile was reviewed against the frozen U2B contract. It composes the
portable automation authority, owner-only POSIX repository/workspace storage, launchd wake,
READY/start/result supervisor protocol, the existing Runtime, default-deny Seatbelt and governed
browser ports without expanding the portable protocol. Unqualified or identity-drifted host
dependencies return closed configuration failures rather than fake execution.

The post-audit Seatbelt regression is closed on the bound source: the profile permits only the
root directory object required to start the qualified executable, never the root subtree. Real
tests prove an owned file remains readable while a sibling owner file remains unreadable. The
installed U2B schedule and child bind imports to the exact verified materialized bundle rather
than inheriting a caller cwd or `PYTHONPATH`. Manifest digests and immutable source-object
identities remain separately validated at their owning resolver boundaries instead of being
incorrectly equated. The source and clean materialized full suites pass; attestation additionally
requires three fresh real wakes, bounded cleanup and an exact receipt identity.

The installed schedule enters isolated Python mode, clears inherited ambient environment before
product imports and reconstructs only the closed `PATH`/bytecode settings plus the verified
materialized root. The U2B composition explicitly binds the strict background Seatbelt profile
compiler; its former accidental fallback to the 017 policy compiler is covered by a constructor
binding regression and a real occurrence journey. Failed proof runs remove only their own exact
launchd wake after process cleanup is proven, so test artifacts cannot accumulate as login items.
<!-- SPEC_PRODUCT_REVIEW_END -->

<!-- STANDARDS_ARCHITECTURE_REVIEW_START -->
## Standards / Architecture Review

Verdict: PASS

`AgentRuntime.run_turn` remains the sole production model/tool loop and state-transition entry.
The launchd adapter is an external wake caller; the supervisor and occurrence child transport
only typed claim/start/result identities. Provider generation and `ToolRuntime.invoke` remain
owned by `agent/runtime/loop.py`, and the host profile cannot create a second approval or tool
execution path.

Filesystem roots are canonical, owner-only and no-follow; process-group termination is bounded
and fail-closed; background browser actions remain limited to the frozen public-observe authority.
The exact root-directory Seatbelt literal is a startup prerequisite, not a broad read grant.
Materialized browser discovery binds a verified bundle only inside the detached test environment
and does not leak host paths into delivery controls. Ruff, `git diff --check`, source full and
host-sealed materialized full gates are Green for the bound identity.

The launchd-installed boundary does not trust its caller's ambient environment: isolation and
the earliest in-script scrub happen before any product import or child process. Cleanup remains
fail-closed—test wake removal is allowed only after exact process-group cleanup is confirmed—and
the host runner cannot convert an unknown process outcome into a successful receipt.
<!-- STANDARDS_ARCHITECTURE_REVIEW_END -->
