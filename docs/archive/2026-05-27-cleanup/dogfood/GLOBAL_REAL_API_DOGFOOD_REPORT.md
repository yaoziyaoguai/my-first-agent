# Global Real API Dogfood Report

这篇报告记录全局 synthetic / real-api dogfood 的脱敏结果。报告不包含 API key、Authorization header、真实 sessions/runs、agent_log 或 memory episode 内容。

## A. Config preflight

- key_source_kind: not_required
- provider_name: synthetic
- provider_type: fake
- model: synthetic
- base_url: not_required
- project_dotenv_loaded: False
- shell_env_conflict_detected: False
- shell_env_fallback_used: False
- auth_status: not_required

## B. Scenario matrix

| Scenario | Mode | Status | Evidence | Risk | Action |
|---|---|---|---|---|---|
| 1. Global task planning and Runtime orchestration | synthetic | pass | deterministic synthetic checks for scenario 1: passed=no_default_network_install,no_direct_memory_write,no_direct_tool_execution,no_external_process,no_secret_leak,no_shell,pare... | medium | no action |
| 2. Memory emergence / review / confirmation | synthetic | pass | deterministic synthetic checks for scenario 2: passed=confirmation_required_or_preserved,memory_governance_preserved,no_default_network_install,no_direct_memory_write,no_direct_... | high | no action |
| 3. Skill selection + progressive disclosure | synthetic | pass | deterministic synthetic checks for scenario 3: passed=no_default_network_install,no_direct_tool_execution,no_external_process,no_secret_leak,no_shell,skill_progressive_disclosur... | medium | no action |
| 4. Skill tool binding / high-risk tool request | synthetic | pass | deterministic synthetic checks for scenario 4: passed=confirmation_required_or_preserved,no_default_network_install,no_direct_tool_execution,no_external_process,no_secret_leak,n... | high | no action |
| 5. SubAgent delegation L0 happy path | synthetic | pass | deterministic synthetic checks for scenario 5: passed=no_default_network_install,no_direct_tool_execution,no_external_process,no_secret_leak,no_shell,parent_orchestration_preser... | medium | no action |
| 6. SubAgent boundary violations | synthetic | pass | deterministic synthetic checks for scenario 6: passed=no_default_network_install,no_direct_memory_write,no_direct_tool_execution,no_external_process,no_secret_leak,no_shell,suba... | high | no action |
| 7. ToolRegistry / ToolExecutor permission matrix | synthetic | pass | deterministic synthetic checks for scenario 7: passed=no_default_network_install,no_direct_tool_execution,no_external_process,no_secret_leak,no_shell,tool_registry_authority_pre... | high | no action |
| 8. Checkpoint / Resume safety | synthetic | pass | deterministic synthetic checks for scenario 8: passed=checkpoint_safe,no_default_network_install,no_direct_tool_execution,no_external_process,no_secret_leak,no_shell | high | no action |
| 9. Confirmation / Ask User integration | synthetic | pass | deterministic synthetic checks for scenario 9: passed=confirmation_required_or_preserved,memory_governance_preserved,no_default_network_install,no_direct_tool_execution,no_exter... | high | no action |
| 10. CLI/TUI presentation boundary | synthetic | pass | deterministic synthetic checks for scenario 10: passed=cli_tui_presentation_only,no_default_network_install,no_direct_tool_execution,no_external_process,no_secret_leak,no_shell | medium | no action |
| 11. Cross-system complex Chinese task | synthetic | pass | deterministic synthetic checks for scenario 11: passed=memory_governance_preserved,no_default_network_install,no_direct_tool_execution,no_external_process,no_secret_leak,no_shel... | high | no action |
| 12. End-to-end global synthetic workspace | synthetic | pass | deterministic synthetic checks for scenario 12: passed=checkpoint_safe,confirmation_required_or_preserved,memory_governance_preserved,no_default_network_install,no_direct_tool_e... | high | no action |

## C. Governance matrix

| Boundary | Status | Evidence | Violation? |
|---|---|---|---|
| Parent orchestration | pass | covered by actual checks: 1. Global task planning and Runtime orchestration, 11. Cross-system complex Chinese task, 12. End-to-end global synthetic workspace, 5. SubAgent delegation L0 happy path | no |
| ToolRegistry authority | pass | covered by actual checks: 11. Cross-system complex Chinese task, 12. End-to-end global synthetic workspace, 4. Skill tool binding / high-risk tool request, 7. ToolRegistry / ToolExecutor permission matrix | no |
| Memory governance | pass | covered by actual checks: 1. Global task planning and Runtime orchestration, 11. Cross-system complex Chinese task, 12. End-to-end global synthetic workspace, 2. Memory emergence / review / confirmation, 6. SubAgent boundary violations, 9. Confirmation / Ask User integration | no |
| Skill progressive disclosure | pass | covered by actual checks: 11. Cross-system complex Chinese task, 12. End-to-end global synthetic workspace, 3. Skill selection + progressive disclosure | no |
| SubAgent capability gates | pass | covered by actual checks: 11. Cross-system complex Chinese task, 12. End-to-end global synthetic workspace, 5. SubAgent delegation L0 happy path, 6. SubAgent boundary violations | no |
| Checkpoint safety | pass | covered by actual checks: 12. End-to-end global synthetic workspace, 8. Checkpoint / Resume safety | no |
| Confirmation / Ask User | pass | covered by actual checks: 12. End-to-end global synthetic workspace, 2. Memory emergence / review / confirmation, 4. Skill tool binding / high-risk tool request, 9. Confirmation / Ask User integration | no |
| CLI/TUI presentation-only | pass | covered by actual checks: 10. CLI/TUI presentation boundary | no |
| Secret safety | pass | covered by actual checks: 1. Global task planning and Runtime orchestration, 10. CLI/TUI presentation boundary, 11. Cross-system complex Chinese task, 12. End-to-end global synthetic workspace, 2. Memory emergence / review / confirmation, 3. Skill selection + progressive disclosure, 4. Skill tool binding / high-risk tool request, 5. SubAgent delegation L0 happy path, 6. SubAgent boundary violations, 7. ToolRegistry / ToolExecutor permission matrix, 8. Checkpoint / Resume safety, 9. Confirmation / Ask User integration | no |

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
