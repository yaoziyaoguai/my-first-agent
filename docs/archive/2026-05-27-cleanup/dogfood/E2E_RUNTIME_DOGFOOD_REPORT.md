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
| E02_skill_selection | partial | direct_subsystem_invocation | SkillRegistry→SkillRegistryValidation→SkillLoader→SkillToolBinding | SkillRegistry, SkillRegistryValidation, SkillLoader, SkillToolBinding | 0.5 | 1 |
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
| Provider call | yes | actual runtime provider call verified in E01,E08 | none | none |
| Skill selection | no | Simulated only in E02,E08 | no real module invocation | P2 |
| Skill progressive disclosure | no | Simulated only in E02 | no real module invocation | P2 |
| SubAgent L0 delegation | no | Simulated only in E03,E08 | no real module invocation | P2 |
| Parent adjudication | no | Simulated only in E03 | no real module invocation | P2 |
| Memory proposal/review | no | Simulated only in E04,E08 | no real module invocation | P2 |
| Memory recall/injection | no | Not covered by any E2E scenario | missing E2E coverage | P3 |
| ToolRegistry gate | no | E05 is partial/direct subsystem invocation；E08/E09 只触达 ToolRegistry API，未形成 RuntimeActionDispatcher + ToolGate handler + target_module_proof 证据链 | requires RuntimeActionDispatcher + ToolGate handler + target_module_proof + dogfood-local fake overlay blocked path evidence | P2 |
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

## E. Important Caveat

**RuntimeActionEvent 不等于 runtime_e2e evidence**。RuntimeActionEvent 只是"收据"——记录了 route() 被调用。target_module_proof（独立观测证据：proof_id + handler_name + target_module + module_invoked=true + observation_independent=true + linked_action_id + linked_target_module）才是"证据"——证明了目标模块被实际执行且观测独立于 handler。仅 handler 自报的 module_invoked=true、handler_name + target_module、free-text invocation_proof 或 handler self-minted target_module_call_id 均不构成 target_module_proof。后续 Runtime Integration 实现必须同时满足 SDD R.6 Runtime E2E 11 项证据链，不能仅凭 RuntimeActionEvent、module_invoked=true 或 handler 自我声明判定 runtime_e2e。

**E05 ToolRegistry 当前不是 runtime_e2e pass**。它只证明 direct subsystem invocation / subsystem_integration。E05 只有在 RuntimeActionEvent、RuntimeActionDispatcher route、ToolGate handler、target_module_proof、dogfood-local fake overlay blocked path evidence 同时存在时，才可升级为 runtime_e2e。fake.* 不得进入 production ToolRegistry 或 production capability matrix；fake high-risk blocked path 的最终 evidence.decision=blocked，不是 confirmation_required，且 dangerous_tool_function_invoked=false。

## F. Hard Truth

- 场景结果: 3 pass, 6 partial, 0 blocked, 0 fail
- 真实 API 调用场景: 3/9
- 能力覆盖: 1 E2E verified, ToolRegistry gate remains partial/subsystem_integration, 12 not verified

## G. Known Issues

### Capability matrix naming mismatch (P3)

`_capability_evidence_matrix()` 中 capability name（如 `"SubAgent"`, `"Skill"`, `"Memory"`）与 `systems_actually_invoked` 中的模块名（如 `"SubAgentRegistry"`, `"SkillRegistry"`, `"FilesystemMemoryStore"`）不匹配，导致 set intersection 失败，大部分 capability 被错误分类为 `e2e_verified=no`（P2 severity）。

**诚实分类应为**：

| Capability | 实际状态 | Evidence |
|---|---|---|
| Provider call | yes (E01/E08 via chat() → real LLM) | 3/9 scenario |
| ToolRegistry gate | partial (E05 direct subsystem invocation；E08/E09 触达 ToolRegistry API，但未证明 RuntimeActionDispatcher + target_module_proof runtime_e2e 链路) | subsystem integration / not runtime_e2e |
| Skill selection | partial (E02 subsystem verified, E08 registry scanned 但未证明 LLM 选择/使用 skill) | direct invocation |
| SubAgent L0 | partial (E03 full subsystem chain verified, 无 runtime LLM reasoning) | direct invocation |
| Memory proposal/review | partial (E04 full consolidation chain verified, 无 runtime LLM-triggered proposal) | direct invocation |
| Checkpoint save/load | partial (E06 direct API verified) | direct invocation |
| Streaming protocol | partial (E07 纯函数, 正确) | deterministic baseline |
| Memory recall/injection | no (未被任何 scenario 覆盖) | not covered |
| Confirmation | partial (E05/E09 验证了 risk classification) | partial |

此问题将在 Runtime Integration / Runtime Action Harness（Track E）中修复。

## H. Recommendation

1. 当前 v0.9.x 不能声称 "9/9 E2E pass"，诚实状态是 3 pass / 6 partial。
2. 下一步：完成 Runtime Integration / Runtime Action Harness 设计与实现，使 Runtime LLM 可以通过受控的 RuntimeAction path 触发子系统能力。
3. 设计文档入口：`docs/runtime-integration/`（RFC、SDD、TDD、Implementation Loop、E2E Dogfood Plan、Audit Checklist）。
