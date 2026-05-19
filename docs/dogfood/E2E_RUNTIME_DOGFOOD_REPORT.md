# End-to-End Runtime Dogfood Report

## A. Safe Config Preflight

- key_source_kind: project_dotenv
- provider_name: anthropic_native
- provider_type: anthropic_native
- model: kimi-k2.5
- base_url: https://coding.dashscope.aliyuncs.com/apps/anthropic
- project_dotenv_loaded: True
- shell_env_conflict_detected: True
- shell_env_fallback_used: False
- auth_status: configured
- provider_available: True
- secret_printed: no
- env_content_read: no

## B. Scenario Matrix

| Scenario | Status | Invocation Mode | Runtime Path Used | Actual Systems | Quality | Issues |
|---|---|---|---|---|---|---|
| E01_runtime_planning | pass | actual_runtime_invoked | SkillRegistry→SubAgentRegistry→ToolRegistry→core.chat()→P... | SkillRegistry, SubAgentRegistry, ToolRegistry, Runtime.chat | 0.8 | 0 |
| E02_skill_selection | partial | direct_subsystem_invocation | SkillRegistry→SkillSelector→SkillLoader→SkillToolBinding | SkillRegistry, SkillSelector, SkillLoader, SkillToolBinding | 0.5 | 1 |
| E03_subagent_l0 | partial | direct_subsystem_invocation | SubAgentRegistry→SubAgentDescriptor→SubAgentRequest→SubAg... | SubAgentRegistry, SubAgentDescriptor, SubAgentRequest, SubAgentDelegation | 0.9 | 1 |
| E04_memory_proposal | partial | direct_subsystem_invocation | FilesystemMemoryStore→ConsolidationLoader→ConsolidationEn... | FilesystemMemoryStore, MemoryEpisodicWrite(synthetic), MemoryConsolidationLoader, MemoryConsolidationEngine | 0.9 | 1 |
| E05_tool_registry | partial | direct_subsystem_invocation | ToolRegistry→VisibilityFilter→RiskClassification→RuntimeR... | ToolRegistry, ToolRegistration, ToolVisibilityFilter, ToolRiskClassification | 0.5 | 1 |
| E06_checkpoint | partial | direct_subsystem_invocation | CheckpointSave→CheckpointLoad→CheckpointClear→CheckpointT... | CheckpointSave, CheckpointTruncationConfig | 0.5 | 1 |
| E07_streaming | partial | direct_subsystem_invocation | ProviderStreamEvent→collect_stream_response→sanitize_stre... | StreamingProtocol, StreamingAggregation, StreamingEdgeCases | 0.95 | 1 |
| E08_full_combined | pass | actual_runtime_invoked | SkillRegistry→SubAgentRegistry→ToolRegistry→core.chat()→P... | SkillRegistry, SubAgentRegistry, ToolRegistry, Runtime.chat | 0.8 | 0 |
| E09_adversarial | pass | actual_runtime_invoked | ToolRegistry→RiskCheck→core.chat() | ToolRegistry, ToolRiskCheck, Runtime.chat | 0.9 | 0 |

## C. Capability Evidence Matrix

| Capability | E2E Verified | Evidence | Gap | Severity |
|---|---|---|---|---|
| Runtime planning | no | Simulated only in E01,E08 | no real module invocation | P2 |
| Provider call | yes | Full E2E runtime path verified in E01,E08 | none | none |
| Skill selection | no | Simulated only in E02,E08 | no real module invocation | P2 |
| Skill progressive disclosure | no | Simulated only in E02 | no real module invocation | P2 |
| SubAgent L0 delegation | no | Simulated only in E03,E08 | no real module invocation | P2 |
| Parent adjudication | no | Simulated only in E03 | no real module invocation | P2 |
| Memory proposal/review | no | Simulated only in E04,E08 | no real module invocation | P2 |
| Memory recall/injection | no | Not covered by any E2E scenario | missing E2E coverage | P3 |
| ToolRegistry gate | yes | Full E2E runtime path verified in E05,E08,E09 | none | none |
| Confirmation | no | Simulated only in E05,E09 | no real module invocation | P2 |
| Checkpoint save/load | no | Simulated only in E06 | no real module invocation | P2 |
| Checkpoint resume safety | no | Simulated only in E06 | no real module invocation | P2 |
| Streaming protocol | no | Simulated only in E07 | no real module invocation | P2 |
| Dogfood/reporting | no | Simulated only in all | no real module invocation | P2 |

## D. Red-team Findings

### P0
- none

### P1
- none

### P2
- E02_skill_selection: P3: direct subsystem call bypasses chat(), does not verify runtime-integrated behavior
- E05_tool_registry: P3: direct subsystem call bypasses chat(), does not verify runtime-integrated behavior

### P3
- E03_subagent_l0: P3: direct subsystem call bypasses chat(), does not verify runtime-integrated behavior
- E04_memory_proposal: P3: direct subsystem call bypasses chat(), does not verify runtime-integrated behavior
- E06_checkpoint: P3: direct subsystem call bypasses chat(), does not verify runtime-integrated behavior
- E07_streaming: P3: direct subsystem call bypasses chat(), does not verify runtime-integrated behavior
- direct_subsystem_invocation only (no chat() runtime path): ['E02_skill_selection', 'E03_subagent_l0', 'E04_memory_proposal', 'E05_tool_registry', 'E06_checkpoint', 'E07_streaming']

## E. Hard Truth

- 场景结果: 3 pass, 6 partial, 0 blocked, 0 fail
- 真实 API 调用场景: 3/9
- 能力覆盖: 2 E2E verified, 0 partial, 12 not verified

## F. Recommendation

3. improve E2E dogfood harness first
