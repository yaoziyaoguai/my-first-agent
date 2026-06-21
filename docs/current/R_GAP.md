# R-series Gap Backlog — Real-world Grounded Validation

> Status: **active**. Derived from `R_GOAL.md` + R-series trial evidence
> (`R_TRIAL_FAILURES.md`, `R_TRIAL_SUMMARY.md`). S-series roadmap mainline remains closed.

## Backlog Summary

| Gap | Priority | Title | Status |
|---|---:|---|---|
| R-G01 | P1 | Status api_key redaction synthetic test | proposed/open |
| R-G02 | P2 | Explicit fake/local CLI trial mode | proposed/open |
| R-G03 | P2 | CLI checkpoint/resume product-level validation | proposed/open |
| R-G04 | P2/P3 | Trial-only approval harness design | proposed/open |
| R-G05 | P2 | Provider-visible tool-name validation alignment | proposed/open |
| R-G06 | P2 | Operator docs / troubleshooting | proposed/open |
| R-G07 | P2 | Interactive CLI smoke command documentation | proposed/open |
| R-G08 | final | R-series release summary | proposed/open |

## R-G01 — Status api_key redaction synthetic test
- Priority: P1
- Source: R-004 / F-02
- AC: a synthetic-config test verifies `main.py status` output never contains the raw
  api_key value; only redacted/masked forms appear.
- Status: proposed/open

## R-G02 — Explicit fake/local CLI trial mode
- Priority: P2
- Source: R-015 / F-04
- AC: a CLI flag (e.g. `--provider fake`) forces FakeProvider on the unified path without
  modifying config.yaml; default behavior unchanged.
- Status: proposed/open

## R-G03 — CLI checkpoint/resume product-level validation
- Priority: P2
- Source: R-020 / F-04
- AC: CLI-level Ctrl+C → checkpoint → resume is validated or documented with clear
  limitation if harness-blocked.
- Status: proposed/open

## R-G04 — Trial-only approval harness design
- Priority: P2/P3
- Source: F-08 (non-interactive trial limitation)
- AC: a design doc for a default-off, safe-allowlist, workspace-only, audit-logged
  trial approval harness; implementation deferred unless low-risk.
- Status: proposed/open

## R-G05 — Provider-visible tool-name validation alignment
- Priority: P2
- Source: FakeProvider hid dotted tool names (F-01 root cause)
- AC: a validation function + test that flags provider-visible tool names violating
  `^[a-zA-Z0-9_-]+$`; fake/local surfaces the issue (warn or guard), real provider
  already sanitized at the seam.
- Status: proposed/open

## R-G06 — Operator docs / troubleshooting
- Priority: P2
- Source: R-053 / R-051 / provider protocol repair
- AC: a real-provider troubleshooting section covering: provider_type/base_url/model,
  tool-name protocol, 4xx error interpretation, CLI-first testing model.
- Status: proposed/open

## R-G07 — Interactive CLI smoke command documentation
- Priority: P2
- Source: trial finding (operators misuse piped mode)
- AC: documented steps for interactive CLI real-provider smoke; clear "do not use piped
  mode to judge runtime completeness" guidance.
- Status: proposed/open

## R-G08 — R-series release summary
- Priority: final
- AC: a release summary documenting proven capabilities, fixed issues, deferred items,
  and the R-series close verdict.
- Status: proposed/open
