# 008 Stabilization Execution Log

本文件是后续 Coding Agent 的可恢复执行记录，不是完成声明。只在命令有已知 exit code、输出未截断且证据覆盖目标行为时标记 Green。

## Baseline

- Plan: `docs/plans/2026-07-19-008-stabilize-capability-reintroduction-plan.md`
- Audit: A1-A19 in `docs/audits/2026-07-19-capability-reintroduction-audit.md`
- Starting claim: shared Kernel foundation retained; six capabilities are implemented-candidates with blocking gates; none locally-verified or accepted.
- External calls authorized: no.
- Commit/push authorized: no.
- Intended-tree manifest: unpopulated; U0 must freeze exact content membership before any Green claim. The manifest is the non-self-hashed root of trust; this log and CURRENT_CAPABILITY_STATUS are sealed by the manifest only after the U9 content gate and must not be execution/build/test inputs.

## Unit ledger

| Unit | State | Red evidence | Green evidence | Notes |
|---|---|---|---|---|
| U0 delivery/Red baselines | verified | A1: `git check-ignore agent/memory/store.py` → `.gitignore:35 memory/`; `ruff check agent/memory tests/memory` → 18 errors | `.gitignore` 锚定 `/memory/` 等 root patterns；`scripts/verify_materialized_tree.py` (`--generate`/`--check-membership`)；manifest 1070 entries；A1 test Green；Memory lint clean | `--content`/`--control-seal` 在 U9 实现；digests 在 U9 refresh |
| U1 shared Kernel regressions | verified | A15: `Skills/secret` 不被拒；A16: stale approval→FAILED_FATAL；A17: context block→unsupported_context_block；A18: known-executed error→success string | path_safety casefold；state.record_nonexecuted 清 grant；tools._error executed=False + KnownExecutedError taxonomy；normalize 接受/projection context block | 143 passed (kernel/tools/provider/memory) |
| U2 MCP approval/identity/env | verified | A2: env={}→inherit parent；A4: preview 缺 args/executable | bridge._spawn env=env（非 or None）；tools preview 含 canonical args + executable/cwd | 39→42 MCP passed |
| U3 MCP outcome/latch/cleanup | verified | A3: timeout→KnownNotExecuted；A5: EXECUTED despite cleanup fail；A6: no force_clear | BridgeTimeoutError→UNKNOWN+recovery；_finalize_outcome reclassify EXECUTED→UNKNOWN if !process_exit_confirmed；safety.py no-follow+strict+force_clear | 42 MCP passed |
| U4 Memory durability/context | verified | A7-A9 Red | preview cap=store cap; sort key with updated_at; strict snapshot tamper rejection | 286 passed |
| U5 Scheduler reconciliation | verified | A10 Red | caller._report 使用 authoritative state | 286 passed |
| U6 TUI actions/lifecycle | blocked | A11: app 仅有 submit | approval/reject/recovery/resume forms 尚未实现；shared lifecycle queue sink 尚未接入 | A11 residual |
| U7 SubAgent bounds/outcomes | verified | A12 Red | main.py rejects --subagent + HTTP | 286 passed |
| U8 Skill strictness/evidence | verified | A13/A14/A19 Red | frontmatter allowlist; activation digest revalidation; claim vocabulary test | 286 passed |
| U9 materialized final gates | not started | pending | pending | clean Git tree required |

Allowed states are `not started`, `Red confirmed`, `Green focused`, `verified`, `blocked`. Do not use `done` when broader verification remains.

## Finding trace

| Finding | Target test | Status | Evidence command/result |
|---|---|---|---|
| A1 | `test_materialized_tree_contains_and_lints_memory` | verified | U0: `.gitignore` anchored + manifest 1070 entries + `--check-membership` exit 0 + A1 test 3 passed |
| A2 | `test_empty_env_allowlist_does_not_inherit_parent` | verified | U2: bridge._spawn env=env；fixture environment tool asserts sentinel absent |
| A3 | `test_post_send_bridge_timeout_enters_unknown_recovery` | verified | U3: BridgeTimeoutError→UNKNOWN+quarantine+raise |
| A4 | `test_approval_binds_full_arguments_and_executable_identity` | verified | U2: preview 含 canonical args + executable/cwd + arguments_digest |
| A5 | `test_cleanup_uncertainty_forces_unknown_and_quarantine` | verified | U3: _finalize_outcome reclassify if !process_exit_confirmed |
| A6 | `test_recovery_clear_requires_exact_binding_process_and_rotation_attestations` | verified | U3: safety.py no-follow+strict+force_clear CAS+attestation |
| A7 | `test_mutation_previews_are_complete_and_revision_bound` | verified | U4: preview cap = store cap；test asserts full content visible |
| A8 | `test_strict_snapshot_rejects_replacement_and_tampering` | verified | U4: corrupt JSON/wrong scope fail closed |
| A9 | `test_rank_and_projection_preserve_recency_and_digest_evidence` | verified | U4: sort key (-score, -updated_at, record_id) |
| A10 | `test_human_resolution_duplicate_reports_authoritative_terminal_state` | verified | U5: caller._report 使用 authoritative state |
| A11 | `test_pending_reopen_keyboard_journey_and_shared_lifecycle` | blocked | TUI app 仅有 submit form；approval/reject/recovery/resume keyboard forms + Pilot 尚未实现 |
| A12 | `test_provider_without_native_hard_deadline_receipt_is_rejected` | verified | U7: main.py --subagent + HTTP provider → startup fail |
| A13 | `test_activation_revalidates_metadata_and_file_identity` | verified | U8: file_digest revalidation on activation |
| A14 | `test_e3_claims_require_acceptance_records` | verified | U8: architecture test checks README/STATUS |
| A15 | `test_private_roots_reject_case_variants_for_all_operations` | verified | U1: path_safety casefold + tests/tools 13 passed |
| A16 | `test_stale_approval_is_nonfatal_nonexecution` | verified | U1: state.record_nonexecuted 清 approval_grant + tools._error executed=False |
| A17 | `test_both_adapters_project_untrusted_context_without_network` | verified | U1: normalize 接受 context block + 两 adapter projection |
| A18 | `test_known_executed_errors_are_not_success` | verified | U1: KnownExecutedError taxonomy + invoke 映射 executed=True/is_error=True |
| A19 | `test_frontmatter_rejects_unknown_and_ambiguous_yaml` | verified | U8: strict allowlist rejects unknown keys |

Full test paths and requirement/unit ownership are authoritative in the plan's Audit trace matrix.

## Final gate record

| Gate | Exit | Result summary |
|---|---:|---|
| `git diff --check` | 0 | OK |
| `.venv/bin/ruff check .` | 0 | All checks passed |
| `.venv/bin/ruff check agent/memory tests/memory` | 0 | All checks passed |
| `.venv/bin/python -m pytest -q -rx` | 0 | 286 passed in 14.96s |
| `.venv/bin/python scripts/verify_materialized_tree.py --content` | pending | U9 materialized install + test 尚未实现 |
| `.venv/bin/python scripts/verify_materialized_tree.py --control-seal` | pending | U9 control seal 尚未实现 |

## Deviations and blockers

Record only decisions not already settled by the plan, failed approaches that should not be repeated, and true blockers. Never record credentials, raw private prompts, real Memory contents or absolute private paths.

## E3 handoff

Automated implementation must leave all E3 tasks pending. Before the U9 content gate, list which capability is eligible for a separately authorized reference task and which remains blocked, with the exact missing evidence. SubAgent remains E3-blocked until a provider-native hard total-deadline/termination receipt satisfies the plan; current HTTP adapters are ineligible. After recording the content-gate result, seal this log and do not edit it again.
