# R-series Goal — Real-world Grounded Validation

> Status: **frozen** (R-series real-world validation, frozen 2026-06-21). This is NOT a
> new product stage (no S6) and NOT capability expansion. It validates that the S-series
> governed runtime kernel works in the real world via the real product path (interactive
> CLI + real provider).

## 1. Positioning

R-series = **Real-world Grounded Validation**. S-series built and proved the governed
runtime kernel fake/local + structurally. R-series proves it works with a **real LLM
provider** on **real tasks** through the **real product path** (interactive CLI).

## 2. Capabilities Already Proven (trial evidence)

- **Real provider** (`anthropic_compatible` → DeepSeek `deepseek-v4-flash`): no-tools
  200, tools 200, model returns real tool_use. Provider tool-name P0 FIXED (`ae94f26`).
- **Interactive CLI product path**: governed tool_use → confirmation → approval → tool
  execution → tool_result → final answer → file created (Run 12, end-to-end PASS).
- **Evidence/audit**: model_response `channel=tool_use` + checkpoint_saved events recorded
  during real interactive sessions (Run 14).
- **Graceful degradation**: runtime survives provider errors without crash.
- **Provider error clarity** (R-051 FIXED `5154d92`): 4xx errors now include actionable
  protocol-generic hints + redacted body preview.
- **CLI mode reporting** (R-106 FIXED `e70fca6`): onboarding text references actual
  provider mode.

## 3. Non-goals

- No activation of Scheduler (TD-008), Memory, full MCP (TD-009), writable/multi-agent
  SubAgent (TD-010).
- No UI/demo/commercial packaging.
- No S6 or new product stage.
- No default auto-approve; no confirmation bypass.
- No modification of user's real config/config.yaml.
- No piped/non-interactive mode treated as the product path.

## 4. Success Criteria

- **AC-1** Interactive CLI product path stable: real provider + governed tool_use +
  confirmation + execution + final answer end-to-end. (PROVEN — Run 12.)
- **AC-2** Real provider smoke stable: no-tools 200 + tools 200. (PROVEN — Runs 11/12.)
- **AC-3** Provider/tool protocol boundary clear: tool-name normalize at the seam;
  error hints actionable. (PROVEN — `ae94f26` + `5154d92`.)
- **AC-4** Operator can read mode/error/status: banner consistent, errors actionable,
  status redacts keys. (R-106 done; R-G01 status test pending.)
- **AC-5** Fake/local vs real provider用途清晰: documented; force-fake CLI option
  available. (R-G02/G06/G07 pending.)
- **AC-6** R trial docs and failure taxonomy/triage complete. (DONE — 5 trial docs +
  failure register.)
- **AC-7** Remaining deferred items have explicit rationale. (R_GAP records each.)

## 5. Release Standard

All P0/P1 gaps MUST be closed. P2 gaps SHOULD be closed; high-risk harness items may be
deferred with rationale. R-series closes when all closable gaps are resolved and the
release summary is written.

## 6. Roadmap Fit

R-series is the "Real-world Grounded Validation" major direction recommended in
`NEXT_ROADMAP_DIRECTION.md`. It does not expand the roadmap; it validates the S-series
kernel against reality. After R-series closes, any next direction (Memory, Scheduler, MCP
expansion, product polish) is a new, separately-authorized decision.
