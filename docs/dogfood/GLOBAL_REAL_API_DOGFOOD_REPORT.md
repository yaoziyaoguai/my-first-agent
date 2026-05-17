# Global Real API Dogfood Report

这篇报告记录全局 synthetic / real-api dogfood 的脱敏结果。报告不包含 API key、Authorization header、真实 sessions/runs、agent_log 或 memory episode 内容。

## A. Config preflight

- key_source_kind: not_required
- provider_name: synthetic
- model: synthetic
- base_url: not_required
- project_dotenv_loaded: False
- shell_env_conflict_detected: False
- shell_env_fallback_used: False
- auth_status: not_required

## B. Scenario matrix

| Scenario | Mode | Status | Evidence | Risk | Action |
|---|---|---|---|---|---|
| 1. Global task planning and Runtime orchestration | synthetic | pass | Parent Agent owns orchestration; runtime audit plan generated; no high-risk tool execution; no memory write | medium | no action |
| 2. Memory emergence / review / confirmation | synthetic | pass | semantic/procedural/episodic candidates separated; pending_review and inline confirmation respected; reject/timeout/other no-write; accept/edit_accept confirmed path only | high | no action |
| 3. Skill selection + progressive disclosure | synthetic | pass | metadata-only selection; body loaded only after selection; references/scripts/templates not preloaded; disabled skill hidden | medium | no action |
| 4. Skill tool binding / high-risk tool request | synthetic | pass | allowed_tools is upper bound; ToolRegistry remains authority; high-risk action pending confirmation; no shell/network/pip execution | high | no action |
| 5. SubAgent delegation L0 happy path | synthetic | pass | SubAgentRequest created by Parent; context package trimmed; max_iterations enforced; Parent adjudication required | medium | no action |
| 6. SubAgent boundary violations | synthetic | pass | nested delegation blocked; shell/repo write/.env read blocked; direct memory write blocked; no default mode escalation | high | no action |
| 7. ToolRegistry / ToolExecutor permission matrix | synthetic | pass | unknown tool fail closed; hidden/internal not model-visible; high-risk pending confirmation; Skill/SubAgent cannot expand tools | high | no action |
| 8. Checkpoint / Resume safety | synthetic | pass | checkpoint summary excludes full prompt/body/resource; secret-like marker redacted; resume does not replay high-risk tool; schema unchanged | high | no action |
| 9. Confirmation / Ask User integration | synthetic | pass | request_user_input seam used; accept/reject/edit_accept/other/timeout semantics; reject/other/timeout no-write; inline confirmation does not bypass pending_review | high | no action |
| 10. CLI/TUI presentation boundary | synthetic | pass | CLI/TUI display only; no runtime logic; no memory write or tool execution; no full body dump or secret leak | medium | no action |
| 11. Cross-system complex Chinese task | synthetic | pass | Chinese task understood; structured audit generated; no dangerous action; no real repo read outside synthetic workspace | high | no action |
| 12. End-to-end global synthetic workspace | synthetic | pass | runtime orchestration full chain; progressive disclosure; L0 delegation and Parent adjudication; ToolRegistry/Memory/Confirmation/Checkpoint gates | high | no action |

## C. Governance matrix

| Boundary | Status | Evidence | Violation? |
|---|---|---|---|
| Parent orchestration | pass | scenario 1/12 require Parent-owned orchestration | no |
| ToolRegistry authority | pass | scenario 4/7 keep ToolRegistry as authority | no |
| Memory governance | pass | scenario 2/9/12 require no direct write | no |
| Skill progressive disclosure | pass | scenario 3/12 require metadata-first loading | no |
| SubAgent capability gates | pass | scenario 5/6 require L0 and fail-closed gates | no |
| Checkpoint safety | pass | scenario 8/12 require redacted summary only | no |
| Confirmation / Ask User | pass | scenario 4/9/12 require pending confirmation | no |
| CLI/TUI presentation-only | pass | scenario 10 requires display-only adapter | no |
| Secret safety | pass | reports contain sanitized diagnostics only | no |

## D. Secret safety

- .env content read: no
- key printed: no
- key prefix/suffix/length printed: no
- Authorization/Bearer printed: no
- secret written to report/logs: no
- real sessions/runs read: no
- memory episodes content read: no

## E. Result summary

- scenario_count: 12
- pass_count: 12
- fail_count: 0
- blocked_count: 0
- P0_issues_found: 0
- P1_issues_found: 0
- P2_issues_found: 0
- P3_issues_found: 0
- ready_to_push_recommendation: yes

## Issues

### P0
- none
### P1
- none
### P2
- none
### P3
- none
