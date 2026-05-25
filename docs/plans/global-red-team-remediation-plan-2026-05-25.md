# Global Red-Team Remediation Plan

- **Date:** 2026-05-25
- **Source:** `docs/audit/global-red-team-product-architecture-audit-2026-05-25.md`
- **Status:** active
- **Principle:** cleanup/slimming only — no new capability building

## Executive Summary

本轮只修架构债、代码边界、安全、文档 source-of-truth 和证据问题。
不新增能力。按红队审计 RT-01 到 RT-18 顺序执行。

Execution order:
1. P1 architecture/governance (RT-01, RT-02)
2. P2 security (RT-06)
3. P2 docs/source-of-truth (RT-05)
4. P2/P3 code quality/cleanup (RT-07, RT-12, RT-16)
5. Remaining if context permits (RT-13, RT-14, RT-15, RT-18)

## Findings Breakdown

### P1 — Architecture / Governance

| ID | Finding | Proposed Remediation | Safe-to-Auto-Run | Product Decision | Execution Order |
| --- | --- | --- | --- | --- | --- |
| RT-01 | Default real-provider product path may not auto-build same Phase1 dispatcher/evidence path as fake/dogfood-injected runs. | Write AD clarifying dispatcher/evidence parity expectations; add contract test proving fake/real share evidence path; if gap exists and fix is small/provider-neutral, implement. | yes (AD + tests only) | yes (whether dispatcher is product-default or config-controlled) | 1 |
| RT-02 | core.chat command shortcuts drifting toward second capability runtime. | Characterize existing shortcuts; add typed CommandIntent boundary; ensure command router only produces intents, doesn't execute core side effects; mark remaining shortcuts as CLI-only. | yes (characterization + boundary, no behavior change) | no | 2 |

### P2 — Security / Product / Code Quality

| ID | Finding | Proposed Remediation | Safe-to-Auto-Run | Product Decision | Execution Order |
| --- | --- | --- | --- | --- | --- |
| RT-03 | Manual human dogfood missing. | NOT this loop — manual human only. Deferred. | no | yes | deferred |
| RT-04 | core.py (1138 lines) and loop.py (815 lines) accumulating orchestration. | Slim loop if P1 boundary work allows; otherwise mark as known debt for next cleanup. | yes, only if scoped within RT-02 boundary changes | no | 6 |
| RT-05 | Source of truth fragmented. | Consolidate: one status page, one backlog, one dogfood index, archive old reports, mark AD statuses. | yes | no | 5 |
| RT-06 | Dogfood report contains masked API key fragment (`sk-sp-4***7a7d`). | Replace with `SET`/`CONFIGURED`; add redaction lint test. | yes | no | 3 |
| RT-07 | SubAgent path depends on test fixtures. | Check if `tests/fixtures/subagents` leaks into product registration; if so, isolate to demo-only registry or mark as fixture-only. | yes | no | 4 |
| RT-08 | Dogfood scripts too stateful/bespoke. | Deferred — requires larger script consolidation effort. | no | no | deferred |
| RT-09 | Memory runtime not session-hardened. | Deferred — needs product decision on storage backend. | no | yes | deferred |
| RT-10 | Tool approval is confirmation-based, not sandbox-grade. | Deferred — needs product decision on security posture. | no | yes | deferred |
| RT-11 | Tool/memory results not polished UX. | Deferred — needs manual dogfood first. | partly | no | deferred |

### P3 — Safety / Cleanup / Evidence

| ID | Finding | Proposed Remediation | Safe-to-Auto-Run | Product Decision | Execution Order |
| --- | --- | --- | --- | --- | --- |
| RT-12 | FakeProvider filesystem side effect before confirmation. | Move directory creation from provider arg generation to tool execution path only. | yes | no | 7 |
| RT-13 | Legacy adapter/config/memory paths lack sunset. | Add deprecation comments with cleanup window; no code removal. | yes | no | 8 |
| RT-14 | Trace/run summary too scattered. | Deferred — one debug report command would be useful but needs UX scoping. | yes, if small | no | deferred |
| RT-15 | Hook/MCP surfaces look more real than they are. | Add doc-level honesty labels; no code changes. | yes | no | 9 |
| RT-16 | Direct handler tests can be marketed as E2E. | Review test/report naming; add L1/L2 labels where missing. | yes | no | 10 |
| RT-17 | Streaming/progress UX not polished. | Deferred — freeze schema, review after manual dogfood. | no | no | deferred |
| RT-18 | AutoRun incentivizes additive work. | This loop IS the cleanup-only loop. After completion, next AutoRun stays cleanup-only. | yes, this loop | no | 11 |

## Execution Order

```
Phase 1: Write this plan → commit/push
Phase 2: RT-01 AD + contract test (dispatcher/evidence parity)
Phase 3: RT-02 Command boundary characterization + typed intent layer
Phase 4: RT-06 Secret fragment redaction + lint
Phase 5: RT-05 Docs source-of-truth consolidation
Phase 6: RT-07 SubAgent fixture isolation
Phase 7: RT-12 FakeProvider side-effect fix
Phase 8: RT-13 Legacy path sunset labeling
Phase 9: RT-15 Hook/MCP honesty labels
Phase 10: RT-16 Evidence label audit
Phase 11: RT-18 Cleanup-only AutoRun declaration
```

## Files Likely Touched

| Phase | Files |
|-------|-------|
| RT-01 | `docs/design/real-provider-dispatcher-evidence-parity-ad.md`, `tests/test_provider_contract.py` |
| RT-02 | `agent/core.py`, `agent/cli_commands.py`, `tests/test_command_router.py` |
| RT-06 | `docs/dogfood/real-provider-dogfood-report.md`, `docs/dogfood/real-provider-e2e-report.json`, `tests/test_provider_contract.py` |
| RT-05 | `README.md`, `docs/README.md`, `docs/dogfood/README.md`, `docs/audit/README.md`, `docs/plans/README.md` |
| RT-07 | `agent/core.py`, `agent/subagents/local.py`, `agent/runtime_integration/phase1_hook.py` |
| RT-12 | `agent/provider/fake_provider.py`, `tests/test_fake_provider.py` |
| RT-13 | `agent/provider/legacy_adapter.py`, `config.py`, `agent/memory.py` |
| RT-15 | `docs/design/`, agent/hook*, agent/mcp* |
| RT-16 | `tests/runtime_integration/`, test docstrings |
| RT-18 | `.claude/commands/auto-run.md` or `docs/dev/AUTO_RUN_WORKFLOW.md` |

## Gates Per Phase

Minimum per phase:
- `git diff --check`
- `.venv/bin/ruff check <changed files>`
- Relevant focused tests

If production code changed:
- `HOME=/private/tmp .venv/bin/python -m pytest tests/ -x -q`

## Commit Message Conventions

- `docs(architecture): define real-provider dispatcher evidence parity`
- `refactor(core): constrain command shortcuts behind typed command boundary`
- `docs(security): redact dogfood secret fragments`
- `docs: consolidate current source of truth`
- `fix(subagent): isolate test fixtures from product registry`
- `fix(fake-provider): avoid filesystem side effects before confirmation`
- `docs(legacy): add sunset labels to deprecated paths`
- `docs(honesty): mark Hook/MCP surfaces as deferred/demo`
- `docs(evidence): clarify handler test evidence levels`
- `docs(process): declare cleanup-only AutoRun policy`
