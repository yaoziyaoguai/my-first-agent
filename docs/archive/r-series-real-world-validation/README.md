# R-series Real-world Validation — Archive

> **Status: CLEAN CLOSE (2026-06-21).** This is an archive record, not active
> documentation. Do not treat these docs as active gaps or an active plan.

## 1. What R-series is

R-series = **Real-world Grounded Validation**. S-series built and proved the governed
runtime kernel fake/local + structurally. R-series proved it works with a **real LLM
provider** on **real tasks** through the **real product path** (interactive CLI).

## 2. Why it started

S-series roadmap mainline closed without ever validating the kernel against a real LLM.
The `NEXT_ROADMAP_DIRECTION.md` recommended R-series as the dependency-funnel: every
later autonomy direction (Memory, Scheduler, MCP, multi-agent) stacks complexity on a
kernel whose real-world behaviour was unverified. R-series graduates the kernel from
"structurally proven" to "real-world proven".

## 3. Final conclusion: CLEAN CLOSE

All R-G01..R-G08 gaps genuinely done. No overclaim, no unwarranted deferred. Independent
audit findings (R-G03/R-G04/R-G05 overclaim) were corrected and then genuinely completed.

## 4. Proven capabilities

- Real provider (`anthropic_compatible` → DeepSeek `deepseek-v4-flash`): no-tools 200,
  tools 200, model returns real tool_use.
- Interactive CLI: governed tool_use → confirmation → approval → tool execution →
  tool_result → final answer → file created (end-to-end PASS, Run 12).
- Evidence/audit: model_response `channel=tool_use` + checkpoint_saved events recorded.
- Provider error clarity: actionable hints + redacted body preview.
- Graceful degradation: runtime survives provider errors without crash.

## 5. Key issues fixed

- **Provider tool-name P0** (`ae94f26`): protocol-generic normalize at the adapter seam
  (dotted internal names → provider-safe, collision-safe, restored on response).
- **Provider error hints** (`5154d92`): 4xx errors include actionable guidance.
- **CLI mode reporting** (`e70fca6`): onboarding references actual provider mode.
- **Status redaction** (`0abcc6d`): synthetic test verifies api_key never printed.
- **Tool-name validation** (`0abcc6d` + `2968da3`): `validate_provider_tool_names()` +
  diagnostic wired into `main.py status`.
- **Force-fake CLI flag** (`d2cb909`): `--provider fake` for safe trial mode.
- **Trial approval harness** (`df68bad` + `af84cb9`): default-off safe-allowlist approval
  wired into main.py confirmation flow.
- **CLI resume validation** (`988353e` + `82d0c57`): checkpoint contract + CLI-level
  subprocess startup test.

## 6. R-G01..R-G08 final status

| Gap | Status |
|---|---|
| R-G01 (status redaction test) | done |
| R-G02 (force-fake CLI flag) | done |
| R-G03 (CLI checkpoint/resume) | done |
| R-G04 (trial approval harness) | done |
| R-G05 (tool-name validation) | done |
| R-G06 (operator docs) | done |
| R-G07 (CLI smoke docs) | done |
| R-G08 (release summary) | done |

## 7. Key commits (R-series chain)

```
eaa19d4 docs(r): finalize R-series closure — all gaps genuinely done
82d0c57 test(r): validate CLI-level resume path via subprocess
af84cb9 fix(r): wire safe trial approval policy into confirmation flow
2968da3 fix(r): wire provider-visible tool-name diagnostics into status
16381dc docs(r): correct real-world validation closure status
d2cb909 feat(r): add explicit fake CLI trial mode
0abcc6d test(r): verify status redacts api keys + guard tool name validity
ae94f26 fix(r): normalize anthropic-compatible provider tool names
5154d92 fix(r): make provider errors actionable with hints and redacted body
e70fca6 fix(r): improve CLI provider mode reporting
```

## 8. Tests / ruff

- **25 R-series tests** (7 test files) all pass.
- **59 confirmation/pending-transition tests** pass (no regression to manual flow).
- **ruff: All checks passed!** on all touched Python files.
- Full pytest **4946+ passed** (S-series + R-series additions, no regression).

## 9. Safety / no-secrets / no-push

- No push performed. No secrets/keys printed/committed. config.yaml/.env gitignored.
- No Scheduler/memory/full-MCP/writable-SubAgent activated.
- No default auto-approve; no confirmation bypass.
- S-series roadmap mainline remains closed; no S6.

## 10. Caveats

- **Trial approval** (`FIRSTAGENT_TRIAL_APPROVAL_POLICY=safe`): default OFF; safe-allowlist
  only (write_file/read_file/edit_file); safe-path only (workspace//tmp/); audit-logged;
  dangerous tools rejected.
- **`--provider fake`**: default OFF; does not modify config.yaml.
- **CLI resume**: checkpoint contract + subprocess startup test done. Complex real Ctrl+C
  mid-task interrupt → resume (with active provider call in flight) is not PTY-validated;
  future module work may deepen this if needed.
- **F-08 (non-interactive trial)**: classified as trial-harness limitation (NOT runtime
  bug). Trial approval harness now supports safe non-interactive trials.
- **Subsequent module-level productization must NOT treat these archived docs as active
  gaps.** R-series is closed.

## 11. Next step

Enter **FirstAgent Product Capability Map** / module-level Goal-Gap loop. R-series proved
the kernel works in the real world; the next decision is which module (Memory, Scheduler,
MCP, SubAgent, Product polish) to productionize first, via a new module-level goal/gap.
