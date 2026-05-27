# Low-Complexity Capability Remediation Summary

Date: 2026-05-25

Scope: Capability Gap Audit 后，只自动补齐 low-complexity / high-value / safe-to-auto-run 项。未读取 `.env`，未调用真实 API，未调用真实 LLM，未做 manual human dogfood。

## Selected Items

| Item | Action | Scope | Out of scope |
|---|---|---|---|
| Capability Gap Audit | implemented | 新增低复杂度能力缺口审计 | 不做大能力建设 |
| Current capability/status doc | implemented | 新增一页当前能力状态源，标注旧审计状态页为历史 | 不重写全量 docs |
| CLI help/onboarding clarity | implemented | 帮助文案讲清 fake/local、real provider、Memory、Tools、SubAgents、run summary 边界 | 不新增 CLI runtime |
| Run summary/debug polish | implemented | 零活动摘要、错误 debug hint、summary obvious-secret redaction | 不做 trace backend |
| Manual dogfood preparation | implemented | 最短 fake/local 人工 dogfood 下一步 | 不声称人工 dogfood 已完成 |
| Redaction/source-of-truth lint | implemented | 扩展 overview docs redaction lint，固定旧状态页 historical notice | 不做全仓文档治理 |

## Implemented Changes

1. Added [capability-gap-audit-low-complexity-2026-05-25.md](../audit/capability-gap-audit-low-complexity-2026-05-25.md).
2. Added [CURRENT_CAPABILITY_STATUS.zh.md](../00-overview/CURRENT_CAPABILITY_STATUS.zh.md), linked it from README/docs index, and marked `docs/06-audit/CURRENT_AUDIT_STATUS.zh.md` historical.
3. Updated `render_onboarding()` help output and added focused onboarding tests.
4. Updated `run_summary_event()` to make zero-activity turns explicit, add a local debug hint for errors, and redact obvious secret fragments in summary lists.
5. Added [manual-human-dogfood-next-steps.md](../dogfood/manual-human-dogfood-next-steps.md) and clarified [dogfood README](../dogfood/README.md).
6. Expanded docs redaction/source-of-truth tests and fixed a false-positive `ask-user` vs `sk-*` lint pattern.

## Deferred Items

| Gap | Reason |
|---|---|
| Real provider dogfood | Blocked by 401 config/auth concern; requires user-owned credentials and endpoint verification |
| Real LLM semantic quality | Requires real API and human judgement |
| Memory recall user-perceived value | Needs manual dogfood feedback before product changes |
| Tool approval wording/product UX | Needs human judgement; only docs/help/status cleanup done |
| Hook lifecycle | Full hook system is explicitly deferred |
| MCP confirmation="always" pipeline | Product decision and larger runtime work required |
| SubAgent L1 / multi-agent orchestration | Larger design/build; current L0 remains DEMO-ONLY |
| Sandbox-grade tool execution | Larger security architecture, not auto-run safe |
| FakeProvider intelligence | Frozen; do not invest beyond contract/debug fixture needs |
| Broad `core.py` / `loop.py` refactor | Too much blast radius for this loop |

## Remaining Capability Gaps

- Manual human dogfood is still not complete.
- Real provider is still blocked until config/auth is fixed outside AutoRun.
- Memory semantic recall quality is not proven.
- Tool approval UX, memory confirmation UX, and debug usefulness need human feedback.
- SubAgent remains L0 deterministic demo-only.
- MCP, hooks, sandbox, RAG/embedding, plugin marketplace, and durable execution remain deferred.

## Gates Run

| Item | Command | Exit | Summary |
|---|---|---:|---|
| Repo safety | `pwd` | 0 | `/Users/jinkun.wang/work_space/my-first-agent` |
| Repo safety | `git status -sb` | 0 | clean, `main...origin/main` |
| Repo safety | `git rev-list --left-right --count origin/main...HEAD` | 0 | `0 0` |
| Audit doc | `git diff --check` | 0 | clean |
| Audit doc | `.venv/bin/python -m pytest tests/test_local_trial_readiness.py::test_audit_docs_contain_no_secret_fragments -q` | 0 | `1 passed` |
| Status doc | `git diff --check` | 0 | clean |
| Status doc | `.venv/bin/python -m pytest tests/test_local_trial_readiness.py::test_readme_quickstart_lists_essential_commands tests/test_local_trial_readiness.py::test_local_trial_checklist_referenced_from_readme tests/test_local_trial_readiness.py::test_readme_keeps_local_trial_entry_short -q` | 0 | `3 passed` |
| CLI onboarding RED | `.venv/bin/python -m pytest tests/test_cli_onboarding_status.py -q` | 1 | expected RED, `2 failed` before implementation |
| CLI onboarding | `.venv/bin/python -m pytest tests/test_cli_onboarding_status.py tests/smoke/test_first_usable_task_e2e.py::test_s1_onboarding_renders_with_key_info -q` | 0 | `3 passed` |
| CLI onboarding | `git diff --check` | 0 | clean |
| CLI onboarding | `.venv/bin/ruff check agent tests scripts` | 0 | clean |
| CLI onboarding | `HOME=/private/tmp .venv/bin/python -m pytest tests/ -x -q` | 0 | `3378 passed, 18 skipped` |
| Run summary RED | `.venv/bin/python -m pytest tests/test_display_event_contract.py::test_run_summary_event_zero_activity_is_explicit_for_debuggability tests/test_display_event_contract.py::test_run_summary_event_error_reasons_are_redacted_with_debug_hint -q` | 1 | expected RED, `2 failed` before implementation |
| Run summary | `.venv/bin/python -m pytest tests/test_display_event_contract.py::test_run_summary_event_zero_activity_is_explicit_for_debuggability tests/test_display_event_contract.py::test_run_summary_event_error_reasons_are_redacted_with_debug_hint -q` | 0 | `2 passed` |
| Run summary | `.venv/bin/python -m pytest tests/test_display_event_contract.py -q` | 0 | `16 passed` |
| Run summary | `git diff --check` | 0 | clean |
| Run summary | `.venv/bin/ruff check agent tests scripts` | 0 | clean |
| Run summary | `HOME=/private/tmp .venv/bin/python -m pytest tests/ -x -q` | 0 | `3380 passed, 18 skipped` |
| Dogfood docs | `git diff --check` | 0 | clean |
| Dogfood docs | `.venv/bin/python -m pytest tests/test_local_trial_readiness.py::test_dogfood_reports_contain_no_secret_fragments -q` | 0 | `1 passed` |
| Redaction lint first run | `.venv/bin/python -m pytest tests/test_local_trial_readiness.py::test_overview_docs_contain_no_secret_fragments tests/test_local_trial_readiness.py::test_current_audit_status_is_marked_historical tests/test_local_trial_readiness.py::test_audit_docs_contain_no_secret_fragments tests/test_local_trial_readiness.py::test_dogfood_reports_contain_no_secret_fragments -q` | 1 | found false-positive `ask-user` vs `sk-*`; fixed lint pattern |
| Redaction lint | `git diff --check` | 0 | clean |
| Redaction lint | `.venv/bin/ruff check tests/test_local_trial_readiness.py` | 0 | clean |
| Redaction lint | `.venv/bin/python -m pytest tests/test_local_trial_readiness.py::test_secret_fragment_lint_does_not_flag_ask_user_terms tests/test_local_trial_readiness.py::test_overview_docs_contain_no_secret_fragments tests/test_local_trial_readiness.py::test_current_audit_status_is_marked_historical tests/test_local_trial_readiness.py::test_audit_docs_contain_no_secret_fragments tests/test_local_trial_readiness.py::test_dogfood_reports_contain_no_secret_fragments tests/test_local_trial_readiness.py::test_docs_readme_contain_no_secret_fragments -q` | 0 | `6 passed` |
| Redaction lint | `.venv/bin/ruff check agent tests scripts` | 0 | clean |

No command used an explicit timeout; long full pytest runs were polled until completion.

## Commits Pushed

| Commit | Message |
|---|---|
| `725ac74` | `docs(audit): add low-complexity capability gap audit` |
| `286ad22` | `docs(status): add current capability status guide` |
| `7bf1996` | `fix(cli): clarify startup provider mode in help output` |
| `b9f41e5` | `fix(display): clarify run summary debug output` |
| `f2ac345` | `docs(dogfood): simplify next human dogfood path` |
| `8d36226` | `test(docs): expand redaction and status source checks` |

All commits were pushed to `origin/main`. Post-push checks reported `git rev-list --left-right --count origin/main...HEAD` as `0 0`.

## Next Recommended Action

Further AutoRun should remain cleanup-only unless the user explicitly changes the goal. The next high-value non-automatic step is manual fake/local human dogfood using [manual-human-dogfood-next-steps.md](../dogfood/manual-human-dogfood-next-steps.md). Real provider work should wait until the user fixes credentials/endpoint/model compatibility outside AutoRun.
