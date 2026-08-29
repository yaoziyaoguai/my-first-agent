# 019 Optional macOS Host Profile — U2B Acceptance Contract

- Status: frozen from `docs/superpowers/specs/2026-08-28-durable-background-runs-design.md` §U2B
- Product status under test: `019-macos-host-profile`
- Portable prerequisite: `019-portable-control-core=accepted/delivered`
- Scope: the exact macOS launchd + POSIX supervisor + Seatbelt + public ephemeral Chromium adapter set only

## 1. Qualification boundary

U2B is optional and platform-specific. A preflight must independently prove macOS, the current
user launchd domain, a strict nested Seatbelt probe and bundled Playwright/Chromium. Missing or
denied prerequisites return the closed `not_qualified` status and write no product receipt. This
does not downgrade the portable core and does not qualify Linux, Windows, cloud or another macOS
adapter identity.

The journey runs from a materialized wheel in one fresh owner-only root. The installed launchd
executable and occurrence child are sealed harness entrypoints; they compose only production 019
ports and the existing single `AgentRuntime`, `ContextManager` and `ToolRuntime`. The deterministic
provider, controlled clock and hostile public TLS fixture are test inputs, never alternate
scheduling, authority or completion paths.

## 2. Three real wakes

Exactly three `launchctl kickstart` wakes target one exact E3 label and the canonical plist:

1. **Due:** launchd invokes `reconcile`; the POSIX supervisor proves READY → durable DISPATCHED →
   start permit, then enters the existing Runtime checkpoint. One real network-off Seatbelt
   command produces exactly one `background_sandbox_v1` receipt. The separately required
   `local_process` class is unavailable, so Runtime produces an authoritative blocked terminal
   result rather than false completion.
2. **Duplicate:** a second wake rereads the terminal occurrence and returns `not_due` with zero
   provider calls, tool calls, process dispatches or effects.
3. **Misfire:** after a controlled sleep jump, a second once-only automation with `catch_up=NONE`
   becomes exactly `misfire_skipped`; it stops before provider, Runtime composition, supervisor,
   sandbox or browser work. A later schedule projection is `MAX_REACHED`, proving no backlog replay.

The same attempt separately runs real 018 public-ephemeral Chromium storage isolation and the
production loopback egress guard. This proves browser availability/isolation non-vacuously without
creating a second model/tool loop.

## 3. Closed evidence and mutations

The receipt contains only booleans, non-negative counts and digests. Private result/provider/process
journals are owner-only and may contain opaque occurrence/process identities, but no task, label,
credential, URL or model-authored payload reaches the plist, launchd-visible diagnostic or public
receipt.

Twelve exact mutation nodes must reject at least: a false claim, counter drift, unknown receipt
field, task/shell plist injection, open diagnostic code, missing sandbox receipt, live process
group, vacuous browser isolation, duplicate/misfire effects and every private sentinel. The due
journey must observe one real child dispatch, three provider calls, one tool call and one sandbox
receipt; the duplicate and misfire deltas are exactly zero.

## 4. Cleanup and receipt

Before writing a receipt, the runner must prove exact LaunchAgent removal, POSIX group disappearance,
browser/Playwright process cleanup and descriptor-relative no-follow deletion of only the bound test
root. Any cleanup unknown preserves the relevant identities for explicit recovery and blocks PASS.

The strict receipt binds the current macOS-profile seal, materialized root, verifier, runner, wheel,
host profile, Seatbelt backend, Chromium identity, launchd adapter, supervisor, sealed fixture,
fresh host-root identity, mutation gate and two different fresh independent review sections.

Only U0/U1, one frozen source/full and materialized/full chain, this qualified U2B receipt,
attestation and both fresh reviews may advance:

`019-macos-host-profile=qualified`

The only additional capability statement is “bounded background execution on the exact qualified
macOS adapter set.” No generic cross-platform, arbitrary shell, personal browser or production-wide
integration claim follows.
