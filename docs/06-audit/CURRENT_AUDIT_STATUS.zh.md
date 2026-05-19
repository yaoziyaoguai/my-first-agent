# Current Audit Status

这篇文档记录当前代码、测试、dogfood、文档入口的审计状态，方便 push 前快速判断项目是否健康。

不替代独立审计报告，也不作为 tag/release 授权。

## 总体结论

Status: v0.9.0 released; v0.9.x Deep Stabilization / Pre-SubAgent-L1 hardening is in local audit-readiness verification.

`v0.9.0` 已作为阶段性里程碑发布并推送 tag。最新对抗性审计摘要曾写 P0/P1/P2 阻塞为 0，但问题清单仍列出两个 P2。本轮按
实际问题清单修复：封死 `agent/model_call.py` 的 legacy SDK stream bypass，并让
`ProviderBackedMessages` 不再静默丢弃 `model` / `max_tokens` / `temperature`。
剩余大文件和 Memory/dogfood 深拆仍记录为 P3 backlog，不阻塞 push。

## v0.9.x Stabilization 计划入口

当前阶段是 Harness Engineering stabilization track：先文档、再独立审计、再按实现 loop 做行为中性 P3 重构。该阶段不做功能扩张，不建设完整 Observability Platform；trace / runtime events / streaming events 只作为 minimal debug/audit support。

- RFC: [V0_9_X_STABILIZATION_RFC.zh.md](../refactor/V0_9_X_STABILIZATION_RFC.zh.md)
- SDD: [V0_9_X_STABILIZATION_SDD.zh.md](../refactor/V0_9_X_STABILIZATION_SDD.zh.md)
- TDD: [V0_9_X_STABILIZATION_TDD.zh.md](../refactor/V0_9_X_STABILIZATION_TDD.zh.md)
- Implementation Loop: [V0_9_X_IMPLEMENTATION_LOOP.zh.md](../refactor/V0_9_X_IMPLEMENTATION_LOOP.zh.md)
- Dogfood / Benchmark Plan: [V0_9_X_DOGFOOD_AND_BENCHMARK_PLAN.zh.md](../refactor/V0_9_X_DOGFOOD_AND_BENCHMARK_PLAN.zh.md)
- Audit Checklist: [V0_9_X_AUDIT_CHECKLIST.zh.md](../refactor/V0_9_X_AUDIT_CHECKLIST.zh.md)

## Fixed P1/P2

| Issue | Status | Evidence |
|---|---|---|
| P1: core.py streaming 绕过 provider factory | fixed locally | `agent/model_call.py` + `agent/provider/streaming.py`；`core.py` 不再 import/实例化 Anthropic SDK |
| P1: Memory LLM 直接构造 Anthropic client | fixed locally | `LLMMemoryExtractor` / `LLMConsolidationContentGenerator` 接收 `ModelProvider`，不直接 import Anthropic |
| P2: config.py import-time load_dotenv 副作用 | fixed locally | `load_legacy_dotenv_config()` 显式 opt-in；普通 import 不调用 `load_dotenv()` |
| P2: synthetic actual_checks 命名误导 | fixed locally | synthetic evidence source 改为 `synthetic_checks`，语义为 deterministic synthetic validation |
| P2: legacy SDK bypass dead path | fixed locally | `agent/model_call.py` 无 provider 时 fail closed，抛 `ProviderNotImplementedError("model_provider_required")`；不再访问 `legacy_client.messages.stream()` |
| P2: ProviderBackedMessages 静默丢弃参数 | fixed locally | legacy facade 显式转发 `model` / `max_tokens` / `temperature`；未知 SDK-style 参数 fail closed |
| P2/P3: core.py provider routing 职责过重 | partially fixed | model call / streaming adapter 已抽离；主 loop 未大拆 |

## v0.9.x Stabilization implementation evidence

| Track | Status | Evidence |
|---|---|---|
| C: core.py slimming | completed locally | `agent/runtime_loop_fields.py` 抽出 runtime loop 字段投影；architecture baseline 明确白名单 `agent.runtime_loop_fields`；Phase 1 full pytest temp HOME 通过 |
| D: Dogfood runner D1-D2 | completed locally | `scripts/dogfood_global_scenarios.py` 承载 definition-only scenarios；`scripts/dogfood_provider_preflight.py` 集中 provider preflight；synthetic global dogfood 12/12 passed |
| G: Config unification G1 | completed locally | `tests/test_config_authority_boundaries.py` 固定 provider config authority 与 local/legacy config 边界；project dotenv scoped loader 继续显式 opt-in |
| M: Memory M1-M3 + M5 docs | completed locally / pending final dogfood | `tests/test_memory_stabilization_m1.py` 锁定 no silent retain、pending_review、inline confirmation、Skill/SubAgent 不直写；`agent/memory_confirmation_forms.py` 集中 confirmation form 语义；M5 dogfood 由 Phase 9 final verification 计入 audit readiness |
| B: Benchmark baseline | completed locally | `scripts/stabilization_benchmark_baseline.py` 生成 deterministic synthetic report；deep stabilization 已从 7 扩展到 19 scenarios，覆盖 Memory/Skill/SubAgent/Checkpoint/Confirmation/Provider/Dogfood 组合边界；post-audit fix 已增加独立 comparator，actual boundary 不再由 expected boundary 赋值 |
| T: Large tests split | completed locally | `tests/test_transition_*.py` 从 `tests/test_v0_4_transition_boundaries.py` 拆出 transition characterization；旧文件降为轻量索引；`tests/test_global_dogfood_boundaries.py` 承载 D1/D2 边界测试 |

## Deep Stabilization hardening

严格红队审计后，本轮修复的深层问题：

- `tests/test_v0_4_transition_boundaries.py` 从 3758 行巨型历史文件降为索引，实际 coverage 拆入 `tests/test_transition_tool_failure_boundaries.py`、`tests/test_transition_tool_success_boundaries.py`、`tests/test_transition_model_output_boundaries.py`、`tests/test_transition_pending_confirmation_boundaries.py`、`tests/test_transition_checkpoint_boundaries.py`。
- benchmark baseline 从 7 个 deterministic scenarios 扩到 19 个，新增 Memory session isolation、Confirmation no-write、Provider factory no bypass、unsupported streaming fail-closed、CLI/TUI presentation-only、dogfood synthetic-not-real-execution 等组合边界。
- Phase 6 LLM consolidation dogfood diagnostics 不再根据 URL/model 猜 provider name；缺失显式 `provider_name` 时为 `unknown`。
- `config.py` 不再在 import 时创建 `sessions/`；`API_KEY` / `BASE_URL` 改为 lazy compatibility attrs，新增显式 legacy getter。
- `openai_compatible` 明确 `supports_streaming=False`，直接调用 `stream()` 时 fail closed，不静默 fallback 到 non-streaming。
- Memory 增加 deterministic session isolation characterization，区分 runtime pending cache 与 filesystem store 持久层。

## Post-audit P2/P3 fixes

独立审计确认 `d17f887` scope 干净且无 P0/P1，但暴露两个 P2 和若干 P3。本节记录 post-audit fix round 的真实处理状态：

- MCP config path policy：pre-existing 风险，非 `d17f887` 引入。最终契约是 home-sensitive、secret-like、sessions/runs、agent_log 等 unsafe path 必须在读取前由 policy 层拒绝，稳定错误码为 `unsafe_path`。`read_failed` 只允许出现在 safe path 通过 policy 后的真实读取失败；SubAgent unsafe profile path 也必须保留 `unsafe_path`，不能被外层 `invalid_profile` 吞掉。
- Memory recall/injection quality：新增 deterministic baseline，覆盖 confirmed memory 可经 `MemoryRuntime/Store -> MemorySnapshot -> prompt_builder` 注入、pending/rejected 不注入、scope 边界不串、secret-like value 不进 prompt、selector/order/budget 可复现。该 baseline 只证明 deterministic retrieval/injection governance，不证明 real LLM semantic quality。
- Memory semantic-quality gate：real LLM recall/injection semantic quality 仍是 future gated evaluation；不得把 Memory 标成 semantic quality completed。该 gap 是 v1.0 quality 风险，不是 v0.9.x safety blocker。
- Benchmark comparator：pre-existing P3，已修。`actual_boundary` 现在来自 deterministic observation/comparator；缺 observation 标为 `not_covered`，不一致标为 `regression`，空 expected 标为 `invalid_definition`，避免 by-construction pass。
- Transition split fixture debt：保留为 future P3。当前 split files 使用局部 import 是为了避免 characterization tests 之间新增 coupling；等模式稳定后再抽 shared helper/fixture。
- CLI/TUI adapter debt：保留为 future P3。当前状态只能写 acceptable with adapter debt，不能写 fully healthy；本轮不做 CLI/TUI 重构。

## Final audit environment fix

第二轮独立审计发现 `tests/test_memory_consolidation_real_llm_dogfood.py::TestProviderConfigAutoLoad::test_check_env_provider_config_no_key`
在存在 ambient shell provider env 的宿主环境中可能失败。根因是
`scripts/dogfood_phase6_llm_consolidation.py` 的 provider config auto-load 在 fake project
无 `.env` 时仍默认回退 shell env，导致 no-key 测试会被外部环境污染。

本轮修复状态：

- fixed locally: `check_env()` / `load_provider_config_for_dogfood()` 默认只使用 project-scoped dotenv values，不再默认 shell env fallback。
- explicit opt-in retained: legacy/manual shell env fallback 需要显式 `allow_shell_env_fallback=True`。
- provider/.env safety preserved: 不读取真实 sessions/runs，不打印 API key / token / prefix / suffix / length，diagnostics 只记录 source kind 和 provider metadata。
- tests updated: no-key context、ambient shell env pollution、project dotenv scoped config、sanitized diagnostics 均有覆盖。

## Final P3 cleanup

| P3 | Status | Evidence / reason |
|---|---|---|
| Streaming Protocol 文档 event_type 不精确 | fixed | `docs/02-architecture/STREAMING_PROTOCOL.zh.md` 已对齐 `text_delta` / `tool_request` / `final` / `error`；`tests/test_streaming_protocol.py` 增加文档一致性测试 |
| Claude Code / Claude / Python SDK 影响全局架构 | fixed / not global | SDK lazy import 限定在 `agent/provider/anthropic_native.py`；非 provider runtime/memory/skill/subagent 增加边界测试；Claude Code 文档段落标为 prior-art reference；Phase 6 dogfood provider identity 改为显式 `AgentProviderConfig` 优先，缺失显式 provider name 时返回 `unknown`，不再用 `claude`/`base_url` 猜运行依赖 |
| `core.py` 仍偏大 | P3 / deferred | 已抽出 model call / pending confirmation / model output dispatch / runtime loop fields projection；剩余主 loop 与 runtime event bridge 受 characterization tests 保护，不建议本轮机械拆分，不阻塞 push |
| 三套 config 概念重叠 | fixed governance, not unified | 代码注释和 README/docs 明确：`config.py` 是 legacy runtime/CLI 兼容，`agent/provider/config.py` 是 provider/API 权威，`agent/local_config.py` 是本地 customization metadata |
| Memory module 仍偏大 | P3 / deferred | M1 characterization 与 session isolation tests 已补；M3 confirmation form 语义已集中；Memory governance 不变；M4 consolidation / snapshot 边界仍 deferred，不建议本轮机械拆分 |
| Large test files | partially fixed / P3 remains | `tests/test_v0_4_transition_boundaries.py` 已拆分；多个 Memory tests 仍承载 characterization coverage，需要 future test split，不阻塞 push |
| Large dogfood runners | P3 / deferred | D1 scenario definition 与 D2 provider preflight 已拆出；runner report / governance matrix 仍可按 D3-D4 后续小切片拆，不建议本轮机械拆分 |
| Benchmark baseline scenarios | fixed for v0.9.x | 当前 deterministic baseline 为 19 scenarios；post-audit fix 已增加独立 comparator，actual boundary 来自 deterministic observation，缺失或不一致不得 pass；future B2 可继续增加报告深度，但仍保持 no real LLM、deterministic only，不能变成 metrics platform |
| `review_agent_output` dead code | fixed | 无调用点且非 documented public API，已删除，避免继续保留 direct `client.messages.create` 形状 |
| CURRENT_AUDIT_STATUS / docs 状态同步 | fixed | 本节记录 fixed/deferred 状态；`TEST_MATRIX` 同步 provider/streaming/dogfood selected tests |

## Area status

| Area | Status | Evidence | Risk |
|---|---|---|---|
| Runtime/Core/Loop | Healthy with P3 backlog | provider streaming 通过 `ModelProvider.stream` / `agent.model_call`；runtime loop fields projection 已抽出；architecture tests 固定边界 | P3: `core.py` 仍偏大，需 characterization-first |
| ToolRegistry/ToolExecutor | Healthy | ToolRegistry metadata、confirmation、visibility tests | P3: 全局 registry 仍需谨慎测试隔离 |
| Memory | Healthy with P3 cleanup, semantic-quality gap explicit | no silent retain / no auto approve；M1 characterization 覆盖 pending_review / inline confirmation / Skill/SubAgent proposal；session isolation tests 覆盖 runtime cache vs filesystem store；deterministic recall/injection baseline 覆盖 store->snapshot->prompt；LLM path 走 provider injection | P2/future: real LLM semantic recall/injection quality 仍需 gated 验证；M4 consolidation / snapshot boundary deferred |
| Skill | Healthy | formal `agent/skill_system/`；legacy 隔离；synthetic + real API dogfood 证据 | P3: docs 多，入口需靠新索引 |
| SubAgent | Healthy | L0 complete；T1 synthetic dogfood 16/16；L1-L5 gated/future | none blocking |
| Checkpoint | Healthy | 截断 tool_result；过滤未知字段；Skill/SubAgent summary safe | none blocking |
| Confirmation / Ask User | Healthy | request_user_input / memory confirmation / tool confirmation 复用 runtime 边界 | none blocking |
| CLI/TUI | Acceptable with P3 adapter debt | adapter/presentation only；Textual lazy optional；benchmark 覆盖 presentation-only boundary | P3: `main.py` 仍承担较多 adapter 兼容，不能写成完全健康 |
| Dogfood | Healthy with D1/D2 split | synthetic checks 是 deterministic validation；scenario definition-only；provider preflight helper sanitized；real-api 是 provider-backed reasoning/evaluation | real dogfood not default |
| Provider config | Healthy with clarified ownership | `AgentProviderConfig` + factory 覆盖 Anthropic/OpenAI native + compatible 四种 style；`config.py` import-time mkdir 已移除；legacy API_KEY/BASE_URL lazy compatibility | P3: 物理统一仍是 future，不阻塞 push |
| Security/Secrets | Healthy | `.env` / `agent_log.jsonl` / sessions/runs/memory episodes not tracked | do not read real artifacts in audit |

## Ready to push?

Yes, if the current branch finishes the quality gates listed in `docs/05-testing-dogfood/TEST_MATRIX.zh.md`.
Do not tag yet; tag decision should wait until push/review evidence is accepted.

## Known limitations / P3 backlog

- `core.py` remains a runtime hub. Next safe slice: characterize runtime event bridge and loop dependency assembly before moving any code.
- `memory.py`, `memory_emergence.py`, `memory_fs_store.py`, and `memory_extraction.py` remain large; M1/M3 is done, M4 consolidation / snapshot split remains deferred.
- `tests/test_v0_4_transition_boundaries.py` has been split by transition theme; keep the old file as a lightweight index and put future transition coverage in the appropriate `tests/test_transition_*.py` file.
- Large Memory tests remain future cleanup: `tests/test_memory_emergence.py`, `tests/test_memory_session_hook.py`, `tests/test_memory_consolidation_real_llm_dogfood.py`, `tests/test_memory_extraction.py`, `tests/test_memory_fs_store.py`.
- Large dogfood runners remain future cleanup: `scripts/dogfood_phase6_llm_consolidation.py`, `scripts/dogfood_skill_system.py`; `scripts/dogfood_global_real_api.py` D1/D2 split is complete while D3/D4 remains future cleanup.
- Fake memory extractor remains keyword-based skeleton; deeper quality improvements belong to LLM extractor / Memory refactor slices, not this P2 cleanup.
- Memory refactor slices:
  - Slice M1: characterization tests for current memory behavior.
  - Slice M2: extraction / proposal / review / store boundary split.
  - Slice M3: confirmation semantics centralization.
  - Slice M4: consolidation / snapshot boundary split.
  - Slice M5: dogfood / docs update.
- Dogfood runner refactor slices:
  - Slice D1: scenario definition vs execution separation.
  - Slice D2: provider preflight helper consolidation.
  - Slice D3: governance matrix aggregation extraction.
  - Slice D4: report rendering extraction.
- Config physical unification remains P3 backlog; current governance docs prevent misusing legacy `config.py` as provider dogfood authority.
- Real LLM SubAgent L1/L2 remain gated.
- Sandbox/worktree/parallel SubAgent remain future/contract.
- Real MCP server activation remains opt-in.
- DB/graph/embedding/vector store are not default memory backends.
- Global Real API dogfood must use project `.env` scoped config loading and must block shell env fallback.
- Dogfood provider identity comes from explicit config fields (`provider_type` / `provider_name`), not URL/model inference; missing provider name is reported as `unknown`.
- Global governance matrix is generated from scenario result check fields; uncovered boundaries must not be marked pass.
- Synthetic dogfood evidence comes from deterministic synthetic checks; `expected_evidence` is only scenario definition.
- Benchmark baseline now has 19 deterministic governance scenarios; future B2 should add comparison/reporting depth only if it stays no real LLM and does not become a metrics platform.
- Benchmark comparator now uses deterministic observations for actual boundary; uncovered or mismatched observations are fail/not_covered/regression, not pass.
- Memory real LLM recall/injection quality remains a future gated track; deterministic tests cover governance, session isolation, and store-to-snapshot-to-prompt injection, not true semantic quality.
- Skill/SubAgent real user dogfood and true multi-process/session productization remain future tracks.
- `openai_compatible` streaming remains unsupported by design and must fail closed until a dedicated provider streaming enhancement lands.

## E2E Runtime Dogfood 诚实重评估（2026-05-19，8aa11a4 基线）

本轮重新运行 E2E Runtime Real API Dogfood 后确认：

- API injection 已验证：`chat(provider=provider)` 直传路径在 3/9 scenario（E01/E08/E09）中通过真实 LLM（kimi-k2.5 via DashScope Anthropic-compatible）。
- `key_source_kind = project_dotenv`，`auth_status = configured`，`shell_env_fallback_used = false`。
- Secret 未打印，`.env` 内容未读取。

**硬结论**：

| 指标 | 状态 |
|------|------|
| 3/9 场景走真正的 chat() 全链路 | 已通过 |
| 6/9 场景只验证子系统 API 正确性，未验证 runtime 集成后的行为 | P3 测试方法学限制 |
| Skill/SubAgent/Memory/Checkpoint 的 runtime-integrated 行为 | 仍无 E2E 覆盖 |
| Capability matrix 命名 mismatch（`_capability_evidence_matrix`） | P3 展示层 bug，待修复 |
| SubAgent L1 | 不能开始，需要 Runtime Integration 完成后再设计 |

**First Agent v0.9.x 能做什么**：
- 通过 project .env scoped loader 安全加载 API key
- 通过 provider injection 运行 `chat()` + 真实 LLM
- 子系统模块 API 在 unit/integration 级别验证通过

**不能做什么（不应声称）**：
- Skill selection 在 Runtime LLM tool calling 触发时能正常工作
- SubAgent delegation 在 Runtime LLM reasoning 触发时能正常工作
- Memory proposal 在对话上下文中被正确触发
- 任何跨模块 runtime-integrated 行为

**根源**：缺少统一的 Runtime Action 抽象——Runtime LLM 没有可审计的 action path 来触发子系统能力。这是架构现实，不是 bug。

**下一步**：Runtime Integration / Runtime Action Harness（`docs/runtime-integration/` 文档包）。

## Runtime Integration 文档入口

Runtime Integration / Runtime Action Harness 设计文档包已就绪（Phase 3: docs-only）：

- RFC: [RUNTIME_INTEGRATION_RFC.zh.md](../runtime-integration/RUNTIME_INTEGRATION_RFC.zh.md)
- SDD: [RUNTIME_INTEGRATION_SDD.zh.md](../runtime-integration/RUNTIME_INTEGRATION_SDD.zh.md)
- TDD: [RUNTIME_INTEGRATION_TDD.zh.md](../runtime-integration/RUNTIME_INTEGRATION_TDD.zh.md)
- Implementation Loop: [RUNTIME_INTEGRATION_IMPLEMENTATION_LOOP.zh.md](../runtime-integration/RUNTIME_INTEGRATION_IMPLEMENTATION_LOOP.zh.md)
- E2E Dogfood Plan: [RUNTIME_INTEGRATION_E2E_DOGFOOD_PLAN.zh.md](../runtime-integration/RUNTIME_INTEGRATION_E2E_DOGFOOD_PLAN.zh.md)
- Audit Checklist: [RUNTIME_INTEGRATION_AUDIT_CHECKLIST.zh.md](../runtime-integration/RUNTIME_INTEGRATION_AUDIT_CHECKLIST.zh.md)

该文档包为后续 coding agent 提供实现蓝图，本阶段不做代码实现。

## Latest verification baseline

- Phase 1 full pytest with temp HOME: `2723 passed, 14 skipped`.
- Phase 2 full pytest with temp HOME: `2721 passed, 14 skipped`.
- Phase 3 full pytest with temp HOME: `2723 passed, 14 skipped`.
- Phase 5 full pytest with temp HOME: `2732 passed, 14 skipped`.
- Post-audit P2/P3 fix full pytest with temp HOME: `2761 passed, 14 skipped`.
- synthetic global dogfood: `12/12 passed`.
- synthetic skill dogfood: `12/12 passed`.
- synthetic subagent dogfood: `16/16 passed`.
- memory synthetic review scenario: `13 passed`.
- benchmark baseline: `19 scenarios, 19 passed, 0 regressions` in local deep stabilization smoke.
