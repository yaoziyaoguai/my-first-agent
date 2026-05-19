# Deep Stabilization Implementation Notes

## Scope

本轮是 v0.9.x 之后、SubAgent L1 之前的 deep stabilization / hardening。目标不是新增产品能力，而是把红队审计指出的深层稳定性风险转成可维护、可验证的工程边界。

## Audit issue grouping

- P2 execution blockers:
  - `tests/test_v0_4_transition_boundaries.py` 是 3000+ 行历史 characterization 巨石，会阻塞后续 review / merge / refactor。
  - stabilization benchmark baseline 只有 7 个 deterministic scenarios，作为 v1.0 前 governance baseline 太薄。
- Provider / config hardening:
  - `scripts/dogfood_phase6_llm_consolidation.py` 仍用 provider name heuristic fallback，diagnostics 可能误导 provider identity。
  - `config.py` import-time 仍读取 env 并创建 `sessions/` 目录，legacy compatibility 边界不够干净。
  - `openai_compatible` streaming limitation 需要显式能力矩阵与 fail-closed 测试。
- Memory / session blind spots:
  - 当前 Memory 证明偏 storage/governance/synthetic path，缺 deterministic recall/injection characterization。
  - 模块级 runtime/cache 与 filesystem store 的 session isolation 边界需要测试。
- Documentation truthfulness:
  - CLI/TUI、Memory、dogfood、benchmark 状态不能写成“完全健康”；必须记录剩余风险和 future gates。

## Assumptions

- 本轮不读取 `.env`、真实 sessions/runs、`agent_log.jsonl`、`memory/episodes/*.jsonl`。
- 本轮不调用真实 LLM，不做 SubAgent L1/L2，不做 DB/graph/embedding，不扩展 Observability。
- `test_v0_4_transition_boundaries.py` 拆分必须保持测试语义，不以删除 coverage 换取文件变小。
- benchmark baseline 仍是 deterministic synthetic evidence，不是 metrics platform。

## Planned fixes

- Track A: 按行为主题拆分 transition boundary characterization tests，原文件降为兼容索引/说明，不承载 3000+ 行测试体。
- Track B: 将 benchmark baseline 扩展到至少 12 个 deterministic governance scenarios，覆盖 Memory / Skill / SubAgent / Checkpoint / Confirmation / Provider / Dogfood 组合边界。
- Track C: 移除 provider name URL/model 猜测；缺失 `provider_name` 时 diagnostics 使用 `unknown`。
- Track D: 移除 `config.py` import-time directory creation；尽量将 legacy env read 转为显式 getter，同时保持兼容。
- Track E: 增加 Memory session isolation / runtime cache vs filesystem store characterization。
- Track F: 明确 provider capability matrix，特别是 `openai_compatible` streaming unsupported fail-closed。
- Track G: 同步 README / audit / refactor docs / test matrix 的真实状态和剩余 backlog。

## Deferred by constraint

- Memory real LLM recall/injection quality：需要真实 LLM gate，本轮禁止真实 LLM。
- Skill/SubAgent real user dogfood：需要更接近真实用户数据/工作流，本轮只做 deterministic complex scenarios。
- CLI/TUI adapter cleanup：红队指出为 P3；本轮只修审计表述，避免大改 adapter。
- True multi-process/session productization：本轮只做单进程 deterministic characterization。
- `openai_compatible` real streaming：可作为 future enhancement；本轮优先 fail-closed 和能力矩阵。

## Running decisions

- 初始仓库状态 clean，`origin/main...HEAD` 为 `0 0`，HEAD 在 `v0.9.0` tag 上。
- 已读取测试结构：`tests/test_v0_4_transition_boundaries.py` 当前 3758 行，包含 runtime events、tool failure/success、confirmation、feedback、loop context/checkpoint 等多个主题，拆分是 P2，不是 polish。
- Track A 执行：将 transition tests 拆为 tool failure、tool success、model output、pending confirmation、checkpoint/loop context 五个主题文件；原文件降为 30 行索引测试。`python -m pytest tests/test_transition_*.py tests/test_v0_4_transition_boundaries.py -q` 通过 `96 passed`，说明 characterization coverage 保留。
- Track B 执行：先将 benchmark tests 提升为 `>=12` scenarios 且要求 12 个 deep stabilization governance ids，测试按预期从 7 scenarios 失败；随后扩展 deterministic baseline 到 19 scenarios。`tests/test_stabilization_benchmark_baseline.py` 通过 `5 passed`，benchmark CLI 报告 `19 passed, 0 regressions`。
- Track C/D/F 执行：先写红测试证明 provider heuristic、config import side effects、openai-compatible streaming fallback 仍存在；随后移除 provider URL/model guessing（缺失 provider_name 为 `unknown`）、将 `config.API_KEY` / `BASE_URL` 改成 lazy compatibility、移除 import-time `sessions/` mkdir，并让 `openai_compatible.stream()` 直接 `ProviderCapabilityError("streaming_not_supported")`。对应 targeted tests 已通过。
- Track E 执行：新增 `tests/test_memory_session_isolation.py`，覆盖 session A pending cache 不污染 session B、独立 in-memory store 不串、filesystem store 只在 explicit accept 后可由新 store 实例重建、reject 跨 runtime 仍 no-write。测试通过 `4 passed`。剩余真实 LLM recall/injection quality 仍 deferred。
- Verification：targeted tests、synthetic global dogfood、benchmark smoke、`git diff --check`、`ruff check agent tests scripts` 均通过；full pytest with temp HOME 通过 `2750 passed, 14 skipped`。

## Remaining risks after this round

- Memory real LLM recall/injection quality 仍未被证明；本轮只证明 deterministic governance / isolation，不证明真实语义召回质量。
- Skill/SubAgent 仍主要靠 deterministic synthetic dogfood；真实用户 dogfood 需要独立授权和 fixture 设计。
- CLI/TUI 仍有 adapter debt，`main.py` 未在本轮大拆。
- `openai_compatible` streaming 未实现；当前正确状态是 fail-closed，future enhancement 需要单独设计。
- 多进程/多用户 productization 未实现；本轮仅覆盖单进程多 runtime / filesystem store 边界。
