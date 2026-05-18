# Current Audit Status

这篇文档记录当前代码、测试、dogfood、文档入口的审计状态，方便 push 前快速判断项目是否健康。

不替代独立审计报告，也不作为 tag/release 授权。

## 总体结论

Status: v0.9.0 released; v0.9.x Stabilization / P3 Refactor docs are ready for independent audit.

`v0.9.0` 已作为阶段性里程碑发布并推送 tag。最新对抗性审计摘要曾写 P0/P1/P2 阻塞为 0，但问题清单仍列出两个 P2。本轮按
实际问题清单修复：封死 `agent/model_call.py` 的 legacy SDK stream bypass，并让
`ProviderBackedMessages` 不再静默丢弃 `model` / `max_tokens` / `temperature`。
剩余大文件和 Memory/dogfood 深拆仍记录为 P3 backlog，不阻塞 push。

## v0.9.x Stabilization 计划入口

下一阶段是 Harness Engineering stabilization track：先文档、再独立审计、再按实现 loop 做行为中性 P3 重构。该阶段不做功能扩张，不建设完整 Observability Platform；trace / runtime events / streaming events 只作为 minimal debug/audit support。

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

## Final P3 cleanup

| P3 | Status | Evidence / reason |
|---|---|---|
| Streaming Protocol 文档 event_type 不精确 | fixed | `docs/02-architecture/STREAMING_PROTOCOL.zh.md` 已对齐 `text_delta` / `tool_request` / `final` / `error`；`tests/test_streaming_protocol.py` 增加文档一致性测试 |
| Claude Code / Claude / Python SDK 影响全局架构 | fixed / not global | SDK lazy import 限定在 `agent/provider/anthropic_native.py`；非 provider runtime/memory/skill/subagent 增加边界测试；Claude Code 文档段落标为 prior-art reference；Phase 6 dogfood provider identity 改为显式 `AgentProviderConfig` 优先，不再用 `claude`/`base_url` 猜运行依赖 |
| `core.py` 仍偏大 | deferred | 已抽出 model call / pending confirmation / model output dispatch；剩余主 loop 与 runtime event bridge 受 characterization tests 保护，大拆会触碰状态机和 UI projection，后续先补切片测试 |
| 三套 config 概念重叠 | fixed governance, not unified | 代码注释和 README/docs 明确：`config.py` 是 legacy runtime/CLI 兼容，`agent/provider/config.py` 是 provider/API 权威，`agent/local_config.py` 是本地 customization metadata |
| Memory module 仍偏大 | deferred | Memory governance 不变；后续必须按 Slice M1-M5 先补 characterization tests，再拆 extraction/proposal/review/store/confirmation/consolidation 边界 |
| Large test files | deferred | 大测试文件承载历史 characterization coverage；为了 P3 机械拆分风险高，不阻塞 push |
| Large dogfood runners | partially fixed / deferred | Phase 6 provider preflight 的 Claude/Anthropic 推断风险已修；runner 体量仍大，后续只按 scenario/report/preflight helper 小切片拆 |
| `review_agent_output` dead code | fixed | 无调用点且非 documented public API，已删除，避免继续保留 direct `client.messages.create` 形状 |
| CURRENT_AUDIT_STATUS / docs 状态同步 | fixed | 本节记录 fixed/deferred 状态；`TEST_MATRIX` 同步 provider/streaming/dogfood selected tests |

## Area status

| Area | Status | Evidence | Risk |
|---|---|---|---|
| Runtime/Core/Loop | Healthy with P3 backlog | provider streaming 通过 `ModelProvider.stream` / `agent.model_call`；architecture tests 固定边界 | P3: `core.py` 仍偏大，需 characterization-first |
| ToolRegistry/ToolExecutor | Healthy | ToolRegistry metadata、confirmation、visibility tests | P3: 全局 registry 仍需谨慎测试隔离 |
| Memory | Healthy with P3 cleanup | no silent retain / no auto approve；LLM path 走 provider injection | P3: Memory 模块仍大，后续需 characterization tests first |
| Skill | Healthy | formal `agent/skill_system/`；legacy 隔离；synthetic + real API dogfood 证据 | P3: docs 多，入口需靠新索引 |
| SubAgent | Healthy | L0 complete；T1 synthetic dogfood 16/16；L1-L5 gated/future | none blocking |
| Checkpoint | Healthy | 截断 tool_result；过滤未知字段；Skill/SubAgent summary safe | none blocking |
| Confirmation / Ask User | Healthy | request_user_input / memory confirmation / tool confirmation 复用 runtime 边界 | none blocking |
| CLI/TUI | Healthy | adapter/presentation only；Textual lazy optional | P3: `main.py` 仍承担较多 adapter 兼容 |
| Dogfood | Healthy with naming fix | synthetic checks 是 deterministic validation；real-api 是 provider-backed reasoning/evaluation | real dogfood not default |
| Provider config | Healthy with clarified ownership | `AgentProviderConfig` + factory 覆盖 Anthropic/OpenAI native + compatible 四种 style；三层 config 职责已写入代码注释/README | P3: 物理统一仍是 future，不阻塞 push |
| Security/Secrets | Healthy | `.env` / `agent_log.jsonl` / sessions/runs/memory episodes not tracked | do not read real artifacts in audit |

## Ready to push?

Yes, if the current branch finishes the quality gates listed in `docs/05-testing-dogfood/TEST_MATRIX.zh.md`.
Do not tag yet; tag decision should wait until push/review evidence is accepted.

## Known limitations / P3 backlog

- `core.py` remains a runtime hub. Next safe slice: characterize runtime event bridge and loop dependency assembly before moving any code.
- `memory.py`, `memory_emergence.py`, `memory_fs_store.py`, and `memory_extraction.py` remain large; split only after behavior characterization.
- `tests/test_v0_4_transition_boundaries.py` remains a large historical test file and should be split by transition theme only after preserving discovery and coverage.
- Large Memory tests remain future cleanup: `tests/test_memory_emergence.py`, `tests/test_memory_session_hook.py`, `tests/test_memory_consolidation_real_llm_dogfood.py`, `tests/test_memory_extraction.py`, `tests/test_memory_fs_store.py`.
- Large dogfood runners remain future cleanup: `scripts/dogfood_phase6_llm_consolidation.py`, `scripts/dogfood_global_real_api.py`, `scripts/dogfood_skill_system.py`.
- Fake memory extractor remains keyword-based skeleton; deeper quality improvements belong to LLM extractor / Memory refactor slices, not this P2 cleanup.
- Memory refactor slices:
  - Slice M1: characterization tests for current memory behavior.
  - Slice M2: extraction / proposal / review / store boundary split.
  - Slice M3: confirmation semantics centralization.
  - Slice M4: consolidation / snapshot boundary split.
  - Slice M5: dogfood / docs update.
- Dogfood runner refactor slices:
  - Slice D1: provider preflight helper with existing real/synthetic tests.
  - Slice D2: scenario definitions separated from execution.
  - Slice D3: governance matrix aggregation helper.
  - Slice D4: report rendering helper.
- Config physical unification remains P3 backlog; current governance docs prevent misusing legacy `config.py` as provider dogfood authority.
- Real LLM SubAgent L1/L2 remain gated.
- Sandbox/worktree/parallel SubAgent remain future/contract.
- Real MCP server activation remains opt-in.
- DB/graph/embedding/vector store are not default memory backends.
- Global Real API dogfood must use project `.env` scoped config loading and must block shell env fallback.
- Dogfood provider identity comes from explicit config fields (`provider_type` / `provider_name`), not URL/model inference.
- Global governance matrix is generated from scenario result check fields; uncovered boundaries must not be marked pass.
- Synthetic dogfood evidence comes from deterministic synthetic checks; `expected_evidence` is only scenario definition.

## Latest verification baseline

- full pytest with temp HOME: `2717 passed, 14 skipped` after final P2 provider cleanup.
- synthetic global dogfood: `12/12 passed`.
