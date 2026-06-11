# Post-repair architecture audit — roadmap delta (2026-06-11)

## completed (audit round 1)

- a34a51d V2 TargetCatalog production-boundary tests
- 07d290a V1 safe_metadata projector + 1 call site migration
- 44b7527 V4 capability drift table
- 3eab3e6 V5 legacy skill tombstone wording alignment
- fa5b5d2 V3 subagent path-status labels
- 9f07dd3 V6 memory consolidation/emergence drift addendum

## post-audit hardening (this round)

- 8209f21 V6 addendum structural boundary test
- ef7b73f V2 boundary tests hardened (T1 ClassVar tautology + T4 _by_descriptor_id gap)
- c469611 V1 projector order + equivalence test (S1 order-pinning + S6 masker equivalent)
- e9b3381 V6 addendum substantive body assertion (V1 heading-only + V4 body substance)
- fffd544 V4 subagent.delegate SoT alignment (P0-3 — RuntimeDecisionFrame SoT = READY, table was FAKE_DEMO)

## repair round 2 (2026-06-12)

- `4d0d8e5` fix(subagent): align SoT with V0-as-product runtime truth (8 boundary tests).
- `8be4dcb` refactor(target-catalog): extract RuntimeActionTargetCatalog from evidence.py
  (1011 lines moved; back-compat re-export; 11 boundary tests).
- `508d27e` test(safe-metadata): replace inline-equivalence with projector contract.
- `e87a5b0` test(memory): lock four-state consolidation truth + flag compat adapter.
- `b76e645` test(v6-drift): drop brittle sibling-allowlist, keep contract.

## protected_pending (boundary protected, full migration pending)

- RuntimeActionTargetCatalog extraction: **completed** in `8be4dcb`; new module
  `agent/runtime_integration/target_catalog.py`; back-compat re-export.
- safe_metadata projector: 1 of ≥3 known call sites migrated (evidence._checkpoint_safe_summary_adapter).
  Remaining migration sites: tool result preview, memory hook preview.
- safe_metadata projector coverage: now 13 tests including order-pinning + inline equivalence.

## documented_pending (drift recorded, not fixed)

- V4 table tool.gate: SoT and table both PARTIAL/FAKE_LOCAL — **aligned, no fix needed** (P0-1 was false positive).
- V4 table tool.invoke: SoT says PARTIAL/FAKE_LOCAL but tool_executor has production masking logic;
  coverage gap is real but documented, not code-fix-eligible here.
- V4 table memory.recall / skill.select / skill.apply / mcp.discover / mcp.invoke: drift noted,
  SoT enum is source of truth; docs alignment deferred.
- V6 addendum: 3 drifts recorded (emergence not in enum; PROJECT_STATUS silent; no central
  ⛔FROZEN index). Source-of-truth repair spike.

## invalidated_assumption

- "subagent.delegate = FAKE_DEMO" was assumed by V4 table. **Invalidated** by direct
  RuntimeDecisionFrame SoT inspection: SoT says READY/REAL_API_INTERACTIVE. The
  `SubAgentDelegateL0Handler` / `SubAgentDelegateL1Handler` are NOT the current
  production path — `SubAgentV0Handler` is. V4 table corrected.
- "consolidation is fully frozen" was assumed by V6 addendum. **Partially invalid**:
  `agent.memory_consolidation*` modules are tagged ⛔FROZEN, but `memory.consolidate`
  is also a registered RuntimeAction in dispatcher. Two states coexist: pipeline frozen,
  but action handler active. Documented in V6 addendum.

## newly_discovered

- agent.skills tombstone does correctly raise ImportError on `import agent.legacy_skills`
  (V5 fix verified by V4 wording alignment + tree inspection).
- T1 ClassVar tautology: the original V2 test asserted only annotation presence, not
  ClassVar semantics. Hardened to use `typing.get_type_hints` + `get_origin` chain.
- T4 `_by_descriptor_id` test gap: V2 originally missed `is_allowed_descriptor` behavioral
  coverage. Added.
- S1 / S6: projector test did not pin order, did not verify inline equivalence. Hardened.
- V1 / V4: V6 addendum boundary test was heading-only; body never asserted. Hardened.
- Tool.gate P0-1: **false positive** — V4 table tool.gate actually aligned with SoT
  PARTIAL/FAKE_LOCAL. Independent verification matters.

## remaining medium/low risks

- 18 other call sites of `mask_user_visible_secrets` still use direct import (incremental).
- 34 unrelated `_redact_*` / `_sanitize_*` functions across ~25 files.
- `agent/subagents/local.py` pre-existing E501 ruff errors block any commit touching that file.
- `test_catalog_resolve_via_context_invoke_registered_target` uses fragile `Path(...).with_suffix(".py")`
  string-concat trick. Cosmetic; deferred.
- V3 commit message long lines (Chinese); not blocking; deferred.

## final state

- 11 commits ahead of `origin/main` from this audit cycle (not pushed).
- 248 focused tests +2 xfail pass; full suite 4582+ pass.
- ruff clean on touched files.
- No AGENTS.md / .claude/settings.json / graphify-out / agent_log touched.
- TUI / local_demo / SubAgentV0Handler / agent/legacy_skills/ NOT modified.
