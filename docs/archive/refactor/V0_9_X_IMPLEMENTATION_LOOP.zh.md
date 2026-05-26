# v0.9.x Stabilization Implementation Loop

Status: Execution loop for future Coding Agent.

本文是后续 Coding Agent 一口气推进 v0.9.x Stabilization / P3 Refactor Track 的执行循环。本文不是本轮实现授权；当前文档包完成并通过独立审计后，才进入实现。

## 1. Loop 总原则

后续 Coding Agent 必须按 Harness Engineering 方法执行：

1. 先读文档。
2. 先写或确认 characterization tests。
3. 再做最小行为中性重构。
4. 每个 phase 跑 selected tests。
5. 触碰核心边界时跑 full pytest with temp HOME。
6. 每个 phase 更新 dogfood / docs / audit evidence。
7. 遇到 stop condition 立即停下报告。

稳定化重构追求高内聚（high cohesion）、低耦合（low coupling）、架构优美（architectural elegance）和编程的艺术（the art of programming）。不要机械拆文件，不制造贫血抽象，不制造新巨石。

关键生产代码和测试必须添加中文学习型注释或 docstring，解释架构边界、状态转换、governance 意图、fake/local-only seam 或错误处理取舍。

## 2. Observability 边界

v0.9.x stabilization 不建设完整 Observability Platform。Trace、runtime events、streaming events、monitoring 只能作为 minimal debug/audit support。

允许的事件和记录只服务：

- 定位 Runtime / Provider / Memory / Skill / SubAgent / ToolRegistry 问题。
- 支持 dogfood 结果证明。
- 支持 audit evidence。
- 支持 checkpoint / confirmation / boundary debugging。

禁止在本 loop 中引入：

- OpenTelemetry。
- dashboard。
- trace viewer。
- metrics system。
- span hierarchy 大设计。
- 复杂 event pipeline。
- 为 observability 扩大 runtime 复杂度。
- 把 observability 变成新的主架构线。

完整 Observability Track 是 future track，等 First Agent 核心能力全部达标后再单独设计 Runtime trace、event viewer、OpenTelemetry / OpenInference、dashboard / viewer、span model、metrics / evaluation integration。

## 3. 全局停止条件

任一 phase 出现以下情况必须停止并报告：

- P0/P1/P2 appears。
- checkpoint schema change needed。
- Memory governance change needed。
- ToolRegistry authority change needed。
- real LLM required。
- `.env` needed。
- shell/external process needed。
- behavior changed unexpectedly。
- full pytest fails。
- secret / token / API key 有泄露风险。
- Skill/SubAgent 需要拥有主 Agent loop 才能继续。
- Observability 需求开始超过 minimal debug/audit support。

## 4. Phase 0: Baseline audit and characterization

### Entry criteria

- 当前分支 clean。
- `origin/main...HEAD` 为 `0 0`，或用户明确接受当前分叉状态。
- `v0.9.0` tag 已存在且不需要修改。
- 本文档包已通过独立审计，结论允许进入实现。

### Allowed files

- `docs/refactor/*`
- `docs/06-audit/CURRENT_AUDIT_STATUS.zh.md`
- `docs/05-testing-dogfood/TEST_MATRIX.zh.md`
- 新增或修改 characterization tests，路径限于 `tests/` 中与对应 Track 相关的文件。

### Forbidden files

- `agent/` 生产代码。
- real `.env`。
- `agent_log.jsonl`。
- 真实 `sessions/` / `runs/`。
- `memory/episodes/*.jsonl` 内容。

### Required docs to read

- `docs/refactor/V0_9_X_STABILIZATION_RFC.zh.md`
- `docs/refactor/V0_9_X_STABILIZATION_SDD.zh.md`
- `docs/refactor/V0_9_X_STABILIZATION_TDD.zh.md`
- `docs/refactor/V0_9_X_DOGFOOD_AND_BENCHMARK_PLAN.zh.md`
- `docs/refactor/V0_9_X_AUDIT_CHECKLIST.zh.md`
- `docs/06-audit/CURRENT_AUDIT_STATUS.zh.md`

### Tests first requirement

先运行现有 selected tests，记录 baseline。只有发现缺失 characterization coverage 时，才补测试。

### Implementation scope

- 不改生产代码。
- 确认当前 P3 backlog、selected commands、dogfood baseline、benchmark gap。
- 为 Phase 1-9 建立 evidence packet 模板。

### Exit criteria

- Baseline evidence 清楚。
- Memory characterization baseline 已捕获，后续 Phase 1-3 若影响 Memory，Phase 4 能用该 baseline 对比发现。
- 需要补的 characterization tests 已列出或已补。
- 没有 P0/P1/P2。

### Stop conditions

适用全局停止条件，尤其是 working tree dirty unknown、full pytest baseline 失败、需要真实 LLM 或 `.env`。

## 5. Phase 1: Core slimming C1

### Entry criteria

- Phase 0 完成。
- core behavior characterization tests 已存在或本 phase 先补齐。
- 没有 checkpoint schema、Memory governance、ToolRegistry authority 变更需求。

### Allowed files

- `agent/core.py`
- `agent/loop.py`
- 与 runtime dispatch / event projection 直接相关的新小模块。
- `tests/test_v0_4_transition_boundaries.py`
- `tests/test_checkpoint_ownership.py`
- `tests/test_streaming_protocol.py`
- 必要 docs/audit status。

### Forbidden files

- `agent/memory*` governance 改动。
- `agent/tool*` authority 改动。
- checkpoint schema 大改。
- Skill/SubAgent loop ownership 改动。
- Observability platform / metrics / dashboard / trace viewer 新模块。

### Required docs to read

- RFC Track C。
- SDD Track C。
- TDD Track C。
- `docs/RUNTIME_STATE_MACHINE.md`
- `docs/RUNTIME_EVENT_BOUNDARIES.md`
- `docs/CHECKPOINT_RESUME_SEMANTICS.md`

### Tests first requirement

先写或确认 pending confirmation、model output dispatch、runtime event bridge、state transition 的 characterization tests。事件只用于 debugging and audit evidence。

### Implementation scope

- 只抽一个 C1 小边界。
- helper 返回 structured decision / projection，不应用状态。
- Parent Runtime 继续拥有主 loop。

### Exit criteria

- selected tests 通过。
- full pytest with temp HOME 通过。
- global synthetic dogfood 无退化。
- `core.py` 更薄但职责边界更清楚。

### Stop conditions

适用全局停止条件；如果需要改变 checkpoint schema、Memory governance、ToolRegistry authority 或扩大 observability，立即停。

## 6. Phase 2: Dogfood runner refactor D1-D2

### Entry criteria

- Phase 1 完成或明确延期且无 P0/P1/P2。
- Dogfood runner baseline report 已保存为 comparison evidence。
- Real-api dogfood 仍保持 gated。

### Allowed files

- `scripts/dogfood_global_real_api.py`
- `scripts/dogfood_skill_system.py`
- `scripts/dogfood_subagent_system.py`
- 新增 dogfood scenario / preflight helper 小模块。
- dogfood 相关 tests。
- dogfood 文档和 audit status。

### Forbidden files

- provider SDK direct client path。
- shell env fallback。
- import-time dotenv loading。
- real `.env`。
- synthetic checks 冒充 real execution。

### Required docs to read

- RFC Track D。
- SDD Track D。
- TDD Track D。
- `docs/DOGFOODING_GUIDE.md`
- `docs/dogfood/GLOBAL_REAL_API_DOGFOOD_REPORT.md`

### Tests first requirement

先写 scenario definition vs execution separation 测试，以及 provider preflight helper 的 no shell env fallback / provider factory 测试。

### Implementation scope

- D1：scenario definition 与 execution 分离。
- D2：provider preflight helper consolidation。
- Report rendering 和 governance matrix aggregation 暂不大改，除非测试暴露必须的小边界。

### Exit criteria

- selected dogfood tests 通过。
- global synthetic dogfood 通过。
- real-api 仍 gated。
- report 明确 evidence source。

### Stop conditions

适用全局停止条件；如果 dogfood 可信度下降、provider factory 被绕过、需要真实 LLM 或 `.env`，立即停。

## 7. Phase 3: Config unification G1

### Entry criteria

- Phase 2 完成或延期且 dogfood trustworthiness 未退化。
- 当前 config 职责已由 tests/docstrings 描述清楚。

### Allowed files

- `config.py`
- `agent/provider/config.py`
- `agent/local_config.py`
- config 相关 tests。
- docs/audit status。

### Forbidden files

- import-time `load_dotenv()`。
- shell env fallback。
- provider direct SDK client。
- secret logging。
- 大范围 provider factory 重写。

### Required docs to read

- RFC Track G。
- SDD Track G。
- TDD Track G。
- `docs/LLM_PROVIDER_CONFIG.md`
- `docs/LOCAL_CONFIG_FOUNDATION.md`

### Tests first requirement

先写或确认 import 不读 dotenv、provider config authority、local config no secret expansion、project scoped loader opt-in 的 characterization tests。

### Implementation scope

- G1 只澄清职责和减少最明显重叠。
- legacy `config.py` 保持兼容，不作为 provider/API authority。
- provider dogfood 继续依赖 `agent/provider/config.py`。

### Exit criteria

- selected config tests 通过。
- no secret tracking tests 通过。
- docs 同步三层 config 职责。

### Stop conditions

适用全局停止条件；如果需要读取 `.env`、改变 provider API contract 或引入 import-time dotenv，立即停。

## 8. Phase 4: Memory characterization M1

### Entry criteria

- Phase 3 完成或延期且 provider config 行为未变。
- Memory governance 当前行为可通过现有 tests 初步证明。

### Allowed files

- Memory 相关 tests。
- Memory dogfood fixtures / docs。
- docs/audit status。

### Forbidden files

- `agent/memory*` 生产代码。
- Memory store schema。
- real `memory/episodes/*.jsonl` 内容。
- Skill/SubAgent direct Memory write。

### Required docs to read

- RFC Track M。
- SDD Track M。
- TDD Track M。
- `docs/MEMORY_ARCHITECTURE.md`
- `docs/DOGFOODING_MEMORY_GUIDE.md`

### Tests first requirement

本 phase 只补 M1 characterization tests，覆盖 no silent retain、no auto approve、pending_review、inline confirmation、filesystem-first 和 Skill/SubAgent 不直接写 Memory。

### Implementation scope

- 不改生产 Memory 代码。
- 用中文学习型注释解释每个 governance 断言保护的架构边界。

### Exit criteria

- Memory selected tests 通过。
- M2-M5 需要的重构入口清楚。
- 没有行为变更。

### Stop conditions

适用全局停止条件；如果 characterization 发现 P0/P1/P2 或需要改 Memory governance，立即停。

## 9. Phase 5: Memory boundary refactor M2-M3

### Entry criteria

- Phase 4 M1 完成。
- Memory characterization tests 通过。
- no silent retain / no auto approve 已被测试锁定。

### Allowed files

- `agent/memory.py`
- `agent/memory_emergence.py`
- `agent/memory_fs_store.py`
- `agent/memory_extraction.py`
- 新增 Memory boundary 小模块。
- Memory 相关 tests 和 docs。

### Forbidden files

- checkpoint schema 大改。
- Skill/SubAgent direct Memory write。
- real episodes 内容读取。
- provider direct SDK client。
- auto approve 路径。

### Required docs to read

- SDD M2-M3。
- TDD Track M。
- `docs/MEMORY_ARCHITECTURE.md`
- `docs/PENDING_INTERACTION_MODEL.md`

### Tests first requirement

先写 emergence / proposal / review / store / confirmation semantics 的 failing or characterization tests，再移动边界。

### Implementation scope

- M2：梳理 emergence / proposal / review / store 边界。
- M3：集中 confirmation semantics。
- 不做 M4 consolidation / snapshot，除非 M2-M3 暴露必须的小修。

### Exit criteria

- selected Memory tests 通过。
- full pytest with temp HOME 通过。
- memory synthetic review dogfood 通过。
- docs/audit status 更新。

### M5 归属声明

Phase 5 只完成 M2-M3 的代码边界重构授权，并明确 defer M4 consolidation / snapshot。M5 memory dogfood + docs update 不在 Phase 5 判定为完成：Phase 8 承接 M5 docs update，Phase 9 承接 M5 memory dogfood / final verification。Phase 5 完成不等于 Track M 完整完成。

### Stop conditions

适用全局停止条件；如果出现 silent retain、auto approve、pending_review 语义变化或 checkpoint schema 需求，立即停。

## 10. Phase 6: Benchmark baseline B1

### Entry criteria

- Phase 5 完成或延期且 Memory governance 未变。
- Dogfood stable scenarios 可运行。

### Allowed files

- benchmark baseline 文档。
- synthetic fixtures。
- benchmark runner 小模块或 script。
- benchmark tests。
- docs/audit status。

### Forbidden files

- real API 默认调用。
- `.env` 读取。
- OpenTelemetry / metrics system / dashboard / trace viewer。
- complex event pipeline。

### Required docs to read

- RFC Track B。
- SDD Track B。
- TDD Track B。
- Dogfood/Benchmark Plan。

### Tests first requirement

先写 benchmark reproducibility tests，覆盖 scenario id、input hash、expected boundary、actual boundary、result、regression status。

### Implementation scope

- 建立 golden traces 和 fixed synthetic inputs。
- Trace/runtime events 只作为 debugging and audit evidence。
- 不做 observability 产品化。

### Exit criteria

- benchmark baseline 可复现。
- benchmark report 能定位 boundary regression。
- synthetic inputs 不依赖真实 LLM / `.env`。

### Stop conditions

适用全局停止条件；如果 benchmark 需要 real LLM、`.env`、metrics system 或 span hierarchy，立即停。

## 11. Phase 7: Large tests split T1

### Entry criteria

- Phase 6 完成或延期且 benchmark baseline 不阻塞。
- 目标大测试文件的主题清单已列出。

### Allowed files

- 目标测试文件。
- 新拆分测试文件。
- 测试 fixtures。
- docs/audit status。

### Forbidden files

- 生产代码。
- 测试断言弱化。
- skip / xfail 掩盖失败。
- 删除历史覆盖。

### Required docs to read

- RFC Track T。
- SDD Track T。
- TDD Track T。
- 当前目标测试文件顶部说明和相关架构文档。

### Tests first requirement

拆分前先跑原测试文件并记录结果。拆分后先跑原主题 selected commands，再跑 full pytest。

### Implementation scope

- T1 只拆一个主题清楚的大测试文件或一个小文件组。
- 保持 pytest discover 稳定。
- 在关键测试中加入中文学习型注释。

### Exit criteria

- characterization coverage preserved。
- selected tests 通过。
- full pytest with temp HOME 通过。
- 没有测试覆盖丢失。
- 如果拆分 `tests/test_v0_4_transition_boundaries.py`，必须同步更新 `docs/refactor/V0_9_X_STABILIZATION_TDD.zh.md` 中 Track C selected test command；不允许拆分后保留失效测试命令。

### Stop conditions

适用全局停止条件；如果必须弱化测试或删除覆盖才能通过，立即停。

## 12. Phase 8: Docs/audit refresh

### Entry criteria

- Phase 1-7 已完成或明确延期。
- 所有实际完成的 Track 有 evidence。

### Allowed files

- `docs/refactor/*`
- `docs/06-audit/CURRENT_AUDIT_STATUS.zh.md`
- `docs/05-testing-dogfood/TEST_MATRIX.zh.md`
- README 中的轻量入口。

### Forbidden files

- `agent/` 生产代码。
- `tests/` 行为改动。
- tag / release 文档误导。

### Required docs to read

- 全部 v0.9.x stabilization 文档。
- 当前 audit status。
- test matrix。

### Tests first requirement

本 phase 是 docs/audit refresh，不新增行为测试；必须先确认前面 phase 的 test evidence 完整。

### Implementation scope

- 同步完成/延期状态。
- 承接 M5 docs update：更新 Memory refactor 文档状态。
- 更新 `docs/06-audit/CURRENT_AUDIT_STATUS.zh.md`。
- 更新 Dogfood/Benchmark 文档中 Memory refactor 状态。
- 更新 P0/P1/P2/P3 结论。
- 明确 Observability future track 不在 v0.9.x scope。

### Exit criteria

- docs 与代码和测试 evidence 一致。
- Memory M5 docs update 已完成或明确延期并记录原因。
- CURRENT_AUDIT_STATUS 与实际实现状态一致。
- Dogfood/Benchmark 文档中的 Memory refactor 状态与 Phase 9 验证计划一致。
- audit checklist 可供独立审计。
- `git diff --check` 通过。

### Stop conditions

适用全局停止条件；如果 docs 与代码事实冲突且无法在本 phase 修正，立即停。

## 13. Phase 9: Full pytest + dogfood + independent audit readiness

### Entry criteria

- Phase 8 完成。
- working tree 只包含本 stabilization loop 的 scoped changes。

### Allowed files

- 最终 evidence 文档。
- audit packet。
- 必要的 dogfood report artifacts，且不得包含 secret 或真实 runtime data。

### Forbidden files

- 新功能代码。
- tag。
- push。
- real secret artifacts。
- observability platform artifacts。

### Required docs to read

- Audit Checklist。
- Dogfood/Benchmark Plan。
- CURRENT_AUDIT_STATUS。
- TEST_MATRIX。

### Tests first requirement

先跑 selected commands，再跑 full pytest with temp HOME。失败时先 root cause investigation，不改测试掩盖。

### Implementation scope

- 运行 full pytest。
- 运行 memory synthetic review scenario。
- 运行 global synthetic dogfood。
- 运行 skill / subagent synthetic dogfood。
- 验证 Memory governance unchanged。
- 运行 benchmark baseline comparison。
- 将 M5 dogfood result 计入 audit readiness。
- 准备 independent audit readiness packet。

### Exit criteria

- `ruff check agent tests scripts` 通过。
- full pytest with temp HOME 通过。
- synthetic dogfood 通过。
- memory synthetic review scenario 通过，且 Memory governance unchanged。
- global synthetic dogfood 通过。
- M5 dogfood result 已计入 audit readiness。
- benchmark baseline 可复现。
- P0/P1/P2 为 0。
- independent stabilization implementation audit readiness 为 yes。

### Stop conditions

适用全局停止条件；如果 full pytest 失败、dogfood regression、benchmark 不可复现或出现 P0/P1/P2，立即停。
