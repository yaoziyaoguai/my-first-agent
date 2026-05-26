# Real API Complex Dogfood Implementation Notes

## Session context

- Date: 2026-05-19
- Branch: main
- Baseline: v0.9.0 tagged, Deep Stabilization complete
- Goal: Design and execute complex multi-stage Real API dogfood covering 10+ scenarios

## Section 1: API config loading

### Approach

使用 `scripts/dogfood_provider_preflight.py` 中的 `load_dogfood_provider_config_private` 作为安全入口。
该函数：
1. 通过 `config._load_project_dotenv_values` 加载项目 .env（不污染 os.environ）
2. 优先使用 project dotenv 值
3. 检测 shell env 冲突
4. 如果 API key 只能从 shell env 获取，标记 `shell_env_fallback_used=true` 并 block
5. 返回脱敏 preflight diagnostic（不含 API key）

### Key design decisions

- key_source_kind 只描述来源类别（project_dotenv / shell_env / missing），不描述 key 内容
- API key 进入 AgentProviderConfig（frozen dataclass, repr=False），仅传给 provider factory
- dogfood runner 本身不访问、不打印、不序列化 API key
- 所有输出都经过 `_sanitize()` 脱敏

## Section 2: Scenario design rationale

### 12 scenarios covering 11 systems

| ID | System focus | Real LLM reasoning needed? |
|---|---|---|
| S01 | Runtime, Skill, SubAgent, ToolRegistry, Confirmation | 架构风险判断需要 LLM 做 contextual reasoning |
| S02 | Memory, Confirmation | 语义分类(candidate/not_remember/secret)需要 LLM 理解用户意图 |
| S03 | Memory, Runtime | recall/injection 质量判断需要 LLM 做 relevance assessment |
| S04 | Skill, ToolRegistry | metadata-first selection 验证 progressive disclosure 逻辑 |
| S05 | SubAgent, Runtime | L0/L1 gap analysis 需要 LLM 理解能力边界 |
| S06 | ToolRegistry, Confirmation | 风险分类需要 LLM 推理但最终权限由 ToolRegistry 决定 |
| S07 | Checkpoint, Runtime | 安全字段选择需要 LLM 理解 secret/sensitive 概念 |
| S08 | Provider, Streaming | 结构化长回答验证 streaming protocol 语义 |
| S09 | Dogfood, Docs | 红队自我批判需要 LLM 诚实评估 |
| S10 | All 7 systems | 端到端综合流程走通 |
| S11 | 中文+5 systems | 中文复杂表达的跨系统理解 |
| S12 | Provider | 连通性 sanity check |

### What is NOT covered by real LLM

- 实际工具执行（所有场景只推理不执行）
- 真实 Memory 写入（只生成 proposal simulation）
- 真实 SubAgent 运行（只评估 readiness）
- 真实 Checkpoint 写入（只评估 safety）
- Streaming protocol 的实际 SSE 事件流（只验证概念理解）

### Design constraints

- 所有场景禁止执行高风险动作
- API key 只从 project .env scoped loader 加载
- 不读取真实 sessions/runs/memory episodes
- 不写入真实 Memory confirmed store

## Section 3: Execution observations

### Preflight result

- key_source_kind: project_dotenv ✓
- project_dotenv_loaded: true ✓
- shell_env_fallback_used: false ✓
- shell_env_conflict_detected: true (shell env has different values than .env — but project .env takes priority, correct behavior)
- provider_type: anthropic_native (DashScope-compatible Anthropic Messages API endpoint)
- model: kimi-k2.5
- base_url: https://coding.dashscope.aliyuncs.com/apps/anthropic
- auth_status: configured

### Scenario results (both runs)

**Run 1** (strict keyword matching): 12/12 pass, but boundary matrix showed "partial" for Memory governance, ToolRegistry authority, Checkpoint safety, Skill progressive disclosure, and Streaming Protocol due to overly strict keyword matching.

**Run 2** (improved keyword matching): 12/12 pass, boundary matrix mostly "yes". Only ToolRegistry authority showing 3/4 (S04 skill selection scenario doesn't explicitly use "ToolRegistry" terminology, which is correct — the scenario focuses on Skill allowed_tools binding).

### Quality score observations

- Average quality: 0.72/1.0
- Range: 0.53 (S12, intentionally concise) to 0.87 (S03 memory recall, S11 Chinese)
- Quality scoring methodology: keyword-based heuristic, not a semantic evaluation. Low scores may reflect brevity rather than poor reasoning.

### Key observations

1. **All 12 scenarios use real LLM calls.** Zero blocked/failed scenarios.
2. **No secret leakage detected.** All outputs sanitized cleanly.
3. **No hallucination/overclaim detected.** LLM correctly stayed in reasoning mode, never claimed to execute tools.
4. **Chinese scenario (S11) scored highest (0.87).** Model handles Chinese complex reasoning well.
5. **S09 self-critique was genuinely brutal.** The LLM correctly identified that most dogfood proves governance baseline, not real capability.

## Section 4: Issues found

### P0: none

### P1: none

### P2: none

### P3 observations

1. **Methodology limitation — keyword-based boundary checks.** The boundary check logic uses keyword matching, which is inherently fragile. A semantically correct but differently-worded response can fail keyword checks even when governance is properly addressed. This is a dogfood methodology issue, not a First Agent issue.

2. **Quality scoring is heuristic, not semantic.** Scores are based on length, structure markers, and keyword presence, not on semantic correctness. S12 scored 0.53 because it was intentionally concise (<300 words), not because the answer was wrong.

3. **Dogfood tests prompt engineering, not system integration.** All 12 scenarios send prompts directly to the LLM through `provider.create()`. They test whether the LLM understands governance concepts — not whether First Agent's Runtime/Memory/Skill/SubAgent/ToolRegistry pipeline correctly applies those concepts in an integrated flow.

4. **S12 provider sanity is minimal.** The sanity check only verifies basic connectivity and concept understanding. It does not verify streaming protocol compliance, error handling, rate limiting, or retry behavior.

5. **No non-deterministic regression baseline.** Each run produces different LLM responses, making it impossible to do exact regression comparison between runs. Quality scores fluctuate.

## Section 5: Deferred risks

1. **Real LLM integration with First Agent systems not tested.** This dogfood only tests LLM reasoning about governance — not the actual integration of LLM reasoning into Runtime/Memory/Skill/SubAgent/ToolRegistry execution paths.

2. **Memory semantic quality remains unquantified.** The dogfood shows the LLM can classify memory candidates, but doesn't measure recall precision, injection relevance, or consolidation quality over time.

3. **SubAgent L0 real execution not tested.** S05 only evaluates readiness conceptually. The actual SubAgent execution path (context package trimming, result adjudication, error handling) has not been tested with real tasks.

4. **Streaming protocol tested only conceptually.** S08 asks the LLM to describe streaming, but doesn't exercise the actual ProviderStreamEvent pipeline or `collect_stream_response` with real SSE events.

5. **Provider compatibility limited to one provider.** Tested only with kimi-k2.5 via DashScope Anthropic-compatible endpoint. Behavior with Anthropic native API, OpenAI native, and other compatible providers is unknown.

6. **No long-conversation or multi-turn testing.** All scenarios are single-turn prompt→response. Real agent usage involves multi-turn conversations with context accumulation.
