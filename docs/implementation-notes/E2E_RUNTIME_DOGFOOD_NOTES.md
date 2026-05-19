# End-to-End Runtime Dogfood Implementation Notes

## Session context

- Date: 2026-05-19
- Branch: main
- Baseline: cf11657 (complex real API dogfood)
- Goal: Design and execute E2E Runtime Dogfood that exercises First Agent's actual
  Runtime/Parent Agent/Memory/Skill/SubAgent/ToolRegistry/Checkpoint/Confirmation paths,
  not just provider.create(prompt) like the previous round.

## Section 1: How this round differs from the previous round

### Previous round (complex real API dogfood)

- All 12 scenarios used `provider.create(prompt)` directly
- LLM was tested for governance *concept understanding*
- Zero system modules were actually invoked
- Proved: LLM understands governance concepts
- Did NOT prove: First Agent's runtime actually works

### This round (E2E runtime dogfood)

- Each scenario attempts to invoke real First Agent modules
- SkillSystem: SkillRegistry, SkillSelector, SkillLoader
- SubAgentSystem: SubAgentRegistry, execute_local, Parent adjudication
- Memory: FilesystemMemoryStore, memory_runtime hooks, consolidation pipeline
- ToolRegistry: tool registration, visibility filtering, risk classification
- Checkpoint: save/load with safety verification
- Provider: through core.chat() with real LLM
- Where full integration is impossible, systems_simulated is explicitly marked
- No fake pass through expected_evidence = actual_evidence

## Section 2: Architecture notes — what can and cannot be invoked

### 可以真实调用的模块

- **SkillRegistry / SkillSelector / SkillLoader / SkillToolBinding**: 通过传入显式 root 路径创建 registry 实例，selector/loader 都接受 registry 参数，可以隔离调用。
- **SubAgentRegistry / SubAgentDescriptor / SubAgentRequest / delegate_once**: SubAgent 系统接受显式 root，`delegate_once(request, registry)` 内置 executor + adjudication 全链路。
- **FilesystemMemoryStore / load_episodic_evidence / run_consolidation_pipeline**: Memory 系统接受显式 root，consolidation pipeline 内部串联 loader→detector→validation。
- **ToolRegistry / get_model_visible_tools / needs_tool_confirmation**: 模块级全局 TOOL_REGISTRY dict，导入即可操作。
- **ProviderStreamEvent / collect_stream_response / sanitize_stream_text**: 纯函数，无外部依赖，可以直接测试。
- **core.chat() 通过 monkeypatch**: 可以 monkeypatch `agent.core._model_provider`、`agent.core.client`、`agent.core_contexts.build_model_provider_from_env`、`agent.tool_executor.execute_tool_call` 来安全调用。

### 必须 monkeypatch 才能调用的路径

- **core.chat() → build_loop_context → build_model_provider_from_env()**: `build_loop_context` 内部硬编码调用 `build_model_provider_from_env()`，不从模块级 `_model_provider` global 读取。必须 monkeypatch `agent.core_contexts.build_model_provider_from_env`。
- **Checkpoint 文件路径**: `save_checkpoint` 使用 `os.getcwd()` 作为相对路径基准，E2E 测试中需要 `os.chdir(tmp)` 来隔离。

### 无法以 E2E 方式调用的路径

- **真实 LLM reasoning 在 Skill/SubAgent/Memory 场景**: SkillSelector 是关键词匹配（非 LLM），SubAgent L0 executor 是确定性执行，ConsolidationEngine 是确定性 detector。这些模块的设计就是非 LLM 的。
- **Memory recall/injection**: 需要在真实多轮对话中测试 recall precision 和 injection relevance，无法在单轮 dogfood 中验证。

## Section 3: Execution observations

### Run 1（原始 harness）: 1 pass / 3 partial / 4 blocked / 1 fail

- 4 个 blocked（E02/E03/E04/E06）：harness 中 import 的函数名与实际模块 API 不匹配
- 1 个 fail（E07）：streaming 测试数据中 sequence 编号冲突
- 0 个场景成功调用 chat()：`build_model_provider_from_env` 未被 monkeypatch

### 修复轮次

1. **`_invoke_chat_e2e` monkeypatch**: 添加 `agent.core_contexts.build_model_provider_from_env` 的 monkeypatch
2. **E02 Skill**: `select_skill_for_task()`→`SkillSelector(registry).select()`, `load_skill_body()`→`SkillLoader(registry).load_body()`, `get_allowed_tools_for_skill()`→`descriptor.allowed_tools`
3. **E03 SubAgent**: `build_subagent_request()`→`SubAgentRequest(...)`, `create_delegation()`→`delegate_once()`
4. **E04 Memory**: `load_consolidation_inputs()`→`load_episodic_evidence()`, `build_consolidation_candidates()`→`run_consolidation_pipeline()`
5. **E06 Checkpoint**: `state.conversation.add_user_message()`→`state.add_user_message()`, `trunc.max_prompt_chars`→`trunc.get("max_result_length", 0)`
6. **E02/E03 workspace**: SKILL.md 缺少 `version` 必填字段，SUBAGENT.md 缺少 `description` 必填字段
7. **E07 streaming**: event sequence 冲突修复

### Run 2（修复后 harness）: 6 pass / 3 partial / 0 blocked / 0 fail

- E01/E08/E09 成功调用 core.chat() 并拿到真实 LLM 响应（3/9 真实 API）
- E02 全部 Skill 系统路径打通（Registry→Selector→Loader→ToolBinding），partial 仅因为 selector 关键词匹配未命中（预期行为）
- E03 SubAgent L0 全链路打通（Registry→Descriptor→Request→Delegation→Executor）
- E04 Memory consolidation 全链路打通（Store→Loader→Pipeline→PendingReview→GovernanceCheck）
- E06 partial：Checkpoint save 成功，但文件路径检查失败（`save_checkpoint` 使用 `os.getcwd()`，chdir 到 tmp 后 sessions/latest/state.json 不在预期位置）
- E05 partial：ToolRegistry registration runtime 部分失败（`register_tool` 需要特定参数签名）
- 0 次 secret 泄露，0 次越权执行，0 次幻觉声称已执行

## Section 4: Issues found

### P0: none

### P1: none

### P2: none

### P3 (methodology/harness)

1. **`build_loop_context` 硬编码 `build_model_provider_from_env()`**: 使 `chat()` 无法从外部注入 provider 进行 E2E 测试，必须 monkeypatch `agent.core_contexts`。建议未来将 provider 作为参数传入。

2. **SKILL.md `version` 字段文档缺失**: SkillDescriptor 要求 version 作为必填字段（schema.py:56 `_REQUIRED_FIELDS`），但 `_setup_synthetic_workspace` 生成的 SKILL.md 没有此字段，导致所有 skill 被静默跳过。建议要么在 schema 中给 version 设置默认值，要么在错误信息中明确说明缺少哪个字段。

3. **SUBAGENT.md `description` 字段文档缺失**: SubAgent descriptor 要求 description 作为必填字段（descriptor.py:140），同样缺少时静默跳过。

4. **`get_checkpoint_truncation_config` 返回 TypedDict 但文档未说明**: 调用方期望 `.max_prompt_chars` 属性访问，实际返回 `{"max_result_length": 2000, "max_tool_results": 50}`。

5. **E2E dogfood harness 初始版本基于「期望 API」编写**: 6/9 场景在首轮运行时因 API 不匹配 blocked/fail，说明公开 API 文档（或 README/docstring）与实际签名之间有差距。

## Section 5: Deferred risks

1. **Memory recall/injection 质量仍无 E2E 覆盖**: 所有场景均为单轮，无法验证 recall precision、injection relevance、跨轮 consolidation 质量。
2. **3/9 真实 chat() 调用**: E02-E07 场景未通过 chat()，而是直接调用子系统模块。这是设计使然（这些模块本身就是非 LLM 的），但意味着端到端路径验证仍不完整。
3. **单一 provider 测试**: 仅用 kimi-k2.5 via DashScope Anthropic-compatible endpoint。Anthropic native/OpenAI 兼容性未知。
4. **SubAgent 真实 LLM reasoning**: L0 executor 是确定性执行，SubAgent 的 LLM-based 推理能力（L1+）完全未测试。
5. **非确定性回归基线缺失**: 每次运行 LLM 响应不同，无法做精确回归对比。

## Section 6: Post-dogfood stabilization (2026-05-19)

### 6.1 API 加载审计 (Part 1)

- `.env` scoped loader 验证通过：`dotenv_values()` → `AgentProviderConfig(frozen, repr=False)` → `build_model_provider()` 链路正确。
- `key_source_kind = "project_dotenv"`, `auth_status = "configured"` 均正确。
- 上一轮 "真实 API 偶尔调不通" 的根因是 harness 中 `build_loop_context` 硬编码调用了 `build_model_provider_from_env()`，而 harness 未 monkeypatch 该函数。**不是 loader 的 bug**。
- preflight 现在正确区分 `shell_env_conflict_detected` 和实际使用的 key source。

### 6.2 core.chat() provider 注入可测试性 (Part 2)

修复了 "P3 methodology issue #1"：
- `build_loop_context()` 和 `chat()` 新增可选 `provider` 参数。
- 传入则直接作为 `model_provider`；不传回退到 `build_model_provider_from_env()`（生产默认安全路径）。
- E2E / dogfood 可显式注入 provider，无需 monkeypatch `agent.core_contexts.build_model_provider_from_env`。
- `tests/test_chat_provider_injection.py`: 6 个测试钉死 invariants。
- `_invoke_chat_e2e` 已更新为使用 `chat(provider=provider)` 直传。

### 6.3 Descriptor 诊断——不再静默跳过 (Part 3A/B)

修复了 "P3 methodology issues #2 and #3"：
- `SkillRegistry._scan_root` 中的 `except SkillLoadError: continue` 现在将错误追加到 `_load_errors` 列表。
- `SubAgentRegistry._scan_root` 同样追加 `SubAgentLoadError`。
- 两者都提供 `get_load_errors()` 公开方法供调用方诊断。
- 6 个新测试（3 skill + 3 subagent）验证缺字段时错误被正确收集。

### 6.4 Checkpoint 路径隔离 (Part 3D)

- `save_checkpoint()` / `load_checkpoint()` / `clear_checkpoint()` / `load_checkpoint_to_state()` 新增可选 `path` 参数。
- 不传则使用模块级 `CHECKPOINT_PATH`（向后兼容）。
- `get_checkpoint_truncation_config()` 返回 TypedDict（非 dataclass），已有文档说明 `["key"]` 访问方式。

### 6.5 E2E dogfood 诚实分级 (Part 4)

Round 2 原始结果：6 pass / 3 partial / 0 blocked / 0 fail。
诚实分级后：**3 pass / 6 partial / 0 blocked / 0 fail**。

关键变化：
- 每个场景增加 `invocation_mode` 字段：`actual_runtime_invoked` | `direct_subsystem_invocation` | `simulated`。
- 只有通过 `chat()` 的 E01/E08/E09 可以 pass。
- E02-E07（直接调用子系统 API）降级为 partial，并标注 P3 测试方法学限制。
- `_apply_honest_grading()` 在 report 构建前执行统一后处理。

**诚实结论**：First Agent 当前所谓 "E2E" 能力被高估了。实际上：
- 3/9 场景走真正的 chat() 全链路（已通过）
- 6/9 场景只验证子系统 API 正确性，未验证 runtime 集成后的行为
- Skill/SubAgent/Memory/Checkpoint 的 runtime-integrated 行为仍无 E2E 覆盖
- 这是 v0.9.x 的已知架构现实，不是紧急 bug；但不应再声称 "9/9 E2E pass"

## Section 7: Re-verification after 8aa11a4 (2026-05-19)

### 7.1 API injection confirmed

Rerun of E2E Runtime Real API Dogfood after provider injection hardening:

- **project .env scoped loader**: working correctly.
- **key_source_kind**: `project_dotenv`.
- **auth_status**: `configured`.
- **shell_env_fallback_used**: `false`.
- **chat(provider=provider) injection**: verified working — E01, E08, E09 all
  successfully called real LLM (kimi-k2.5 via DashScope Anthropic-compatible)
  through the injected provider. No monkeypatching needed.

### 7.2 Rerun results (real-api mode)

| Metric | Count |
|--------|-------|
| Total | 9 |
| pass | 3 (E01, E08, E09) |
| partial | 6 (E02-E07) |
| blocked | 0 |
| fail | 0 |
| actual_runtime_invoked | 3 |
| direct_subsystem_invocation | 6 |
| simulated | 0 |

### 7.3 Root cause confirmed

The "API occasionally unavailable" symptom from Round 1 was NOT a loader bug.
It was the harness failing to inject the provider into `build_loop_context`,
which hardcoded `build_model_provider_from_env()`. 8aa11a4 fixed this by
adding an optional `provider` parameter to `chat()` and `build_loop_context()`.

### 7.4 Capability matrix regression identified

The `_capability_evidence_matrix()` rewritten in 8aa11a4 has a naming mismatch:
capability names (e.g. "SubAgent", "Skill", "Memory") don't match the concrete
module names in `systems_actually_invoked` (e.g. "SubAgentRegistry",
"SkillRegistry", "FilesystemMemoryStore"). This causes most capabilities to
be incorrectly classified as `e2e_verified=no` with P2 severity.

The honest classification should be:
- **Provider call**: yes (E01/E08 via chat() → real LLM)
- **ToolRegistry gate**: yes (E05/E08/E09 actually invoked ToolRegistry API)
- **Skill selection**: partial (E02 subsystem verified, E08 registry scanned but
  not proven that LLM selected/used skills)
- **SubAgent L0**: partial (E03 full subsystem chain verified, no runtime LLM
  reasoning about delegation)
- **Memory proposal/review**: partial (E04 full consolidation chain verified,
  no runtime LLM-triggered proposal)
- **Checkpoint save/load**: partial (E06 direct API verified)
- **Streaming protocol**: partial (E07 pure function, correct)
- **Memory recall/injection**: no (not covered by any scenario)
- **Confirmation**: partial (E05/E09 exercised risk classification)

### 7.5 Hard conclusion (unchanged)

First Agent v0.9.x can:
- Load API keys safely through project .env scoped loader
- Run chat() with real LLM through provider injection
- Verify subsystem module APIs at the unit/integration level

It CANNOT (and should not claim to):
- Verify that Skill selection works when triggered by Runtime LLM tool calling
- Verify that SubAgent delegation works when triggered by Runtime LLM reasoning
- Verify that Memory proposal works when triggered by conversational context
- Verify any cross-module runtime-integrated behavior

This is architecture reality, not a bug. SubAgent L1 cannot begin until:
1. SubAgent delegation is registered as a Runtime tool
2. An E2E scenario verifies LLM-initiated delegation through chat()
