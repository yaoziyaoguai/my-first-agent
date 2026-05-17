# Current Audit Status

这篇文档记录当前代码、测试、dogfood、文档入口的审计状态，方便 push 前快速判断项目是否健康。

不替代独立审计报告，也不作为 tag/release 授权。

## 总体结论

Status: P1/P2 fixed locally, pending independent re-audit.

最新全面独立审计曾给出 PARTIAL，指出 provider abstraction 仍未覆盖 `core.py` streaming 路径和 Memory LLM 路径，并指出 `config.py` import-time `load_dotenv()` 副作用、synthetic dogfood `actual_checks` 命名误导、`core.py` 巨型文件风险。本轮修复这些 P1/P2，但不 push、不 tag；建议先做独立复审。

## Fixed P1/P2

| Issue | Status | Evidence |
|---|---|---|
| P1: core.py streaming 绕过 provider factory | fixed locally | `agent/model_call.py` + `agent/provider/streaming.py`；`core.py` 不再 import/实例化 Anthropic SDK |
| P1: Memory LLM 直接构造 Anthropic client | fixed locally | `LLMMemoryExtractor` / `LLMConsolidationContentGenerator` 接收 `ModelProvider`，不直接 import Anthropic |
| P2: config.py import-time load_dotenv 副作用 | fixed locally | `load_legacy_dotenv_config()` 显式 opt-in；普通 import 不调用 `load_dotenv()` |
| P2: synthetic actual_checks 命名误导 | fixed locally | synthetic evidence source 改为 `synthetic_checks`，语义为 deterministic synthetic validation |
| P2/P3: core.py provider routing 职责过重 | partially fixed | model call / streaming adapter 已抽离；主 loop 未大拆 |

## Area status

| Area | Status | Evidence | Risk |
|---|---|---|---|
| Runtime/Core/Loop | Healthy with P3 cleanup | provider streaming 通过 `ModelProvider.stream` / `agent.model_call`；architecture tests 固定边界 | P3: `core.py` 仍偏大 |
| ToolRegistry/ToolExecutor | Healthy | ToolRegistry metadata、confirmation、visibility tests | P3: 全局 registry 仍需谨慎测试隔离 |
| Memory | Healthy with P3 cleanup | no silent retain / no auto approve；LLM path 走 provider injection | P3: Memory 模块仍大，后续需 characterization tests first |
| Skill | Healthy | formal `agent/skill_system/`；legacy 隔离；synthetic + real API dogfood 证据 | P3: docs 多，入口需靠新索引 |
| SubAgent | Healthy | L0 complete；T1 synthetic dogfood 16/16；L1-L5 gated/future | none blocking |
| Checkpoint | Healthy | 截断 tool_result；过滤未知字段；Skill/SubAgent summary safe | none blocking |
| Confirmation / Ask User | Healthy | request_user_input / memory confirmation / tool confirmation 复用 runtime 边界 | none blocking |
| CLI/TUI | Healthy | adapter/presentation only；Textual lazy optional | P3: `main.py` 仍承担较多 adapter 兼容 |
| Dogfood | Healthy with naming fix | synthetic checks 是 deterministic validation；real-api 是 provider-backed reasoning/evaluation | real dogfood not default |
| Provider config | Healthy with P3 cleanup | `AgentProviderConfig` + factory 覆盖 Anthropic/OpenAI native + compatible 四种 style | P3: `config.py` / `agent/provider/config.py` / `agent/local_config.py` 尚未完全统一 |
| Security/Secrets | Healthy | `.env` / `agent_log.jsonl` / sessions/runs/memory episodes not tracked | do not read real artifacts in audit |

## Ready to push?

Not yet. Run full verification and independent re-audit first. Do not tag yet.

## Known limitations / P3 backlog

- `tests/test_v0_4_transition_boundaries.py` remains a large historical test file and should be split in a future cleanup.
- Large Memory tests remain future cleanup: `tests/test_memory_emergence.py`, `tests/test_memory_session_hook.py`, `tests/test_memory_consolidation_real_llm_dogfood.py`, `tests/test_memory_extraction.py`, `tests/test_memory_fs_store.py`.
- Large dogfood runners remain future cleanup: `scripts/dogfood_phase6_llm_consolidation.py`, `scripts/dogfood_global_real_api.py`, `scripts/dogfood_skill_system.py`.
- Memory module refactor backlog: split emergence / proposal / review / store / confirmation / snapshot / consolidation with characterization tests first. Current behavior and governance are unchanged.
- Config unification remains P3: `config.py`, `agent/provider/config.py`, and `agent/local_config.py` still overlap conceptually. This round only removed import-time dotenv side effects and kept provider/dogfood on scoped provider config.
- Real LLM SubAgent L1/L2 remain gated.
- Sandbox/worktree/parallel SubAgent remain future/contract.
- Real MCP server activation remains opt-in.
- DB/graph/embedding/vector store are not default memory backends.
- Global Real API dogfood must use project `.env` scoped config loading and must block shell env fallback.
- Dogfood provider identity comes from explicit config fields (`provider_type` / `provider_name`), not URL/model inference.
- Global governance matrix is generated from scenario result check fields; uncovered boundaries must not be marked pass.
- Synthetic dogfood evidence comes from deterministic synthetic checks; `expected_evidence` is only scenario definition.
