# Window 3 Closure Audit — CM-1 Config / Provider Import Boundary

> 日期：2026-06-13
> 范围：Window 3，CM-1 config/provider import-boundary spike + scheduler label precision
> Verdict：ACCEPT_WITH_TRACKED_DEBT — WINDOW 3 CLOSED

## 1. Final HEAD

- Plan commit：`0b9673d`
- Implementation commit：`38c3bae`
- Closure docs commit：本文件所在 commit
- Branch：`main`
- Push：no push

## 2. Files Changed

Implementation commit `38c3bae`：

- `tests/test_architecture_boundaries.py` — 新增 W3-T1..W3-T5 boundary tests。
- `docs/06-audit/WINDOW_3_CM1_CONFIG_IMPORT_BOUNDARY_INVENTORY.zh.md` — 新增 CM-1 inventory。
- `agent/action_scheduler.py` — docstring label 从不可达式 overclaim 收紧为
  `dormant-by-default / registered-not-routed in production`。
- `docs/06-audit/WINDOW_2_CLOSURE_AUDIT.zh.md` — 同步 CR-1 label。
- `docs/06-audit/WINDOW_2_COMPAT_INVENTORY.zh.md` — 同步 action_scheduler label。

Closure commit：

- `docs/06-audit/CURRENT_ARCHITECTURE_REPAIR_ROADMAP.zh.md` — CM-1 标为 completed，
  记录 Window 3 evidence 和 tracked debt。
- `docs/06-audit/WINDOW_3_CLOSURE_AUDIT.zh.md` — 本 closure audit。

## 3. Graphify / Source Evidence

Graphify queries used：

1. `graphify query "provider config simple_config profiles local_config mcp_config provider factory provider selection config loading profile loading" --budget 2500`
2. `graphify query "ActionScheduler ActionSchedulerHandler scheduler action types route_from_runtime_loop action_scheduler chat main.py test_scheduler_main_path" --budget 2500`
3. `graphify query "tests/test_architecture_boundaries.py scheduler config boundary" --budget 2500`

Graphify index `graphify-out/graph.json` existed and queries returned nodes. It was used
only for discovery; load-bearing claims were checked against source and tests.
`graphify-out/*` was not staged or committed.

Source facts checked：

- `agent/provider/config.py` defines `AgentProviderConfig` and
  `load_agent_provider_config`.
- `agent/provider/simple_config.py` defines `UnifiedProviderConfig` and
  `load_unified_provider_config`.
- `agent/provider/profiles.py` defines `ProviderProfile`,
  `load_provider_profiles`, `resolve_active_profile`, and
  `profile_to_agent_config`.
- `agent/provider/factory.py` owns provider selection fallback:
  `config/config.yaml` → `FIRST_AGENT_PROVIDER_PROFILE` (legacy env var) →
  `MY_FIRST_AGENT_LLM_PROVIDER` (legacy env var) → fake provider.
- `agent/local_config.py` is local/dev display metadata config, not provider factory owner.
- `agent/mcp_config*.py` is MCP-specific parser/service/presenter/CLI surface.
- `agent/core.py` keeps `chat(..., action_scheduler=None, ...)` and only forwards the
  existing seam; `main.py` production chat calls do not pass `action_scheduler=`.
- `agent/runtime_integration/phase1_hook.py` registers scheduler action types to
  `_scheduler_handler`; tests can manually inject `ActionScheduler`.

## 4. RED / GREEN Evidence

RED evidence was captured in a temporary clone at `/private/tmp/my-first-agent-w3-red`
based on `0b9673d`, applying only the W3 tests patch:

- Command：`.venv/bin/python -m pytest -q tests/test_architecture_boundaries.py -k w3 -rx --tb=short`
- Result：3 failed, 2 passed, 35 deselected
- Intended RED reasons：missing Window 3 inventory doc / missing owner snapshot /
  scheduler docs still used unreachable-style wording.

GREEN evidence after implementation:

- `.venv/bin/python -m pytest -q tests/test_architecture_boundaries.py -rx --tb=short`
  → 40 passed
- `.venv/bin/python -m pytest -q tests/runtime_integration/ -rx --tb=short`
  → 1076 passed, 4 skipped, 6 xfailed
- `.venv/bin/python -m pytest -q tests/golden_e2e/ -rx --tb=short`
  → 8 passed
- `.venv/bin/python -m pytest -q tests/ -rx --tb=short`
  → 4725 passed, 12 skipped, 26 xfailed
- `git diff --check` → exit 0
- `.venv/bin/ruff check agent/action_scheduler.py tests/test_architecture_boundaries.py`
  → All checks passed

## 5. Review Findings

Focused review result：

- 0 Blocker
- 0 High
- No runtime behavior change.
- No CM-2 expansion.
- No `CapabilityStatus`, shared capability contract, or provider registry.
- No scheduler production wiring.
- No North Star modification.
- No `graphify-out/*` commit.

Fresh-context / external reviewer note：project safety rules forbid real LLM/provider calls,
so ce-code-review/gstack-style review was performed as a local focused review rather than
external subagent/provider execution.

## 6. Closure State

CM-1：

- completed
- Evidence：Window 3 inventory + W3-T1/W3-T4 boundary tests
- Conclusion：keep current config surfaces; do not converge in Window 3

Scheduler label correction：

- completed
- Evidence：W3-T2/W3-T3/W3-T5
- Correct label：
  - `dormant-by-default`
  - `registered-not-routed in production`
  - `injectable seam exists`
  - `manually injectable in tests`

Deferred / not started：

- CM-2 remains `accepted_deferred`
- GE-2 remains separate / not started
- No provider registry
- No unified capability status
- No scheduler wiring
- No North Star change

## 7. Tracked Debt

Recorded in Roadmap §9.5：

- W3-D1：provider fallback precedence user-visible presentation
- W3-D2：profiles/env fallback long-term retention/deprecation
- W3-D3：action_scheduler production activation decision remains deferred

All are Low or Low/P3 and have owner / trigger / exit condition.

## 8. Safety Checklist

- no .env read
- no agent_log.jsonl read
- no real sessions/runs read
- no real MCP config read
- no real skill/subagent dirs from project read
- no private data output
- no real LLM/provider/MCP call
- no real MCP endpoint/server reachability check
- no production server command execution
- no tag creation/deletion/push
- no push

## 9. Final Verdict

**ACCEPT_WITH_TRACKED_DEBT — WINDOW 3 CLOSED**

Window 3 met its scope: CM-1 inventory exists and is test-locked; scheduler wording is
precise; scheduler remains dormant-by-default; CM-2/provider registry/scheduler wiring were
not started.
