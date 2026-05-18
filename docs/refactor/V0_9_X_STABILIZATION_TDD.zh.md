# v0.9.x Stabilization TDD Plan

Status: Test plan for v0.9.x stabilization / P3 refactor track.

本文定义后续稳定化重构的测试优先策略。每个 Track 都必须先建立或确认 characterization tests，再做行为中性重构。关键测试应添加中文学习型注释或 docstring，解释测试保护的是架构边界、治理语义或状态转换，而不是偶然实现细节。

## 1. 通用 TDD 规则

每个实现 phase 必须：

1. 阅读 RFC / SDD / TDD / Implementation Loop。
2. 先写或扩展 characterization tests。
3. 能红则先确认红，且失败原因与目标一致。
4. 实现最小行为中性改动。
5. 运行 selected test command。
6. 如果触碰 runtime、Memory、ToolRegistry、Checkpoint、Provider、dogfood runner 或 architecture boundary，触发 full pytest with temp HOME。
7. 更新 docs/audit status。
8. 不弱化、删除、skip、xfail 测试来制造绿色。

禁止：

- 读取 `.env`。
- 读取 `agent_log.jsonl`。
- 读取真实 sessions/runs。
- 读取 `memory/episodes/*.jsonl` 内容。
- 调用真实 LLM。
- pip install / git clone。
- 让 synthetic dogfood 冒充 real execution。

## 2. Track C: `core.py` slimming

### Characterization tests

覆盖：

- core behavior unchanged。
- pending confirmation dispatch 行为。
- model output dispatch 行为。
- runtime event bridge 投影。
- checkpoint/resume 行为。
- tool result envelope 行为。
- streaming protocol 行为。

### Refactor tests

覆盖：

- 抽出的 helper 不拥有主 loop。
- helper 输入输出是结构化 decision / projection / transition proposal。
- Parent Runtime 仍应用状态转换。
- `core.py` 不回退 direct SDK / legacy provider bypass。

### Negative tests

覆盖：

- Skill/SubAgent 不能拥有主 Agent loop。
- helper 不能直接执行工具。
- helper 不能直接写 Memory。
- helper 不能保存 checkpoint。
- checkpoint schema 未改变。

### Selected test command

```bash
python -m pytest tests/test_v0_4_transition_boundaries.py tests/test_checkpoint_ownership.py tests/test_streaming_protocol.py -q
```

### Full pytest trigger

触碰 `core.py`、runtime event、checkpoint/resume、confirmation、tool result、streaming 或 provider route 时必须运行：

```bash
HOME=/private/tmp/my-first-agent-v0.9.x-core-home python -m pytest tests/ -x -q
```

### Exit criteria

- core loop 行为不变。
- checkpoint / confirmation / memory / tool result 行为不变。
- architecture boundary tests 通过。
- full pytest 通过。

## 3. Track M: Memory module refactor

### Characterization tests

覆盖：

- memory governance unchanged。
- no silent retain。
- no auto approve。
- `pending_review`。
- inline confirmation。
- rejection / edit / defer 语义。
- filesystem-first store。
- Skill/SubAgent 不直接写 Memory。

### Refactor tests

覆盖：

- emergence detector 只产生 candidate。
- proposal builder 不 approve。
- review queue 保持 pending state。
- store adapter 只写已批准记忆。
- consolidation 不绕过 provider factory。
- snapshot 不改变 governance。

### Negative tests

覆盖：

- 自动路径不能 retain。
- proposal 不能直接写 store。
- Skill/SubAgent memory proposal 不能直接落盘。
- fake extractor 不能被描述成 real LLM quality。
- provider-backed extractor 不能直接构造 SDK client。

### Selected test command

```bash
python -m pytest tests/test_memory_guardrails.py tests/test_memory_emergence.py tests/test_memory_extraction.py tests/test_memory_fs_store.py -q
```

### Full pytest trigger

触碰 Memory governance、confirmation、store、consolidation、snapshot、provider-backed memory path 时必须运行：

```bash
HOME=/private/tmp/my-first-agent-v0.9.x-memory-home python -m pytest tests/ -x -q
```

### Exit criteria

- Phase 4-5 exit criteria：memory governance unchanged、no secret tracking、M1 characterization 和 M2-M3 selected tests 通过。
- Phase 5 完成不等于 Track M 完整完成；M4 consolidation / snapshot 仍按 Loop 明确 defer。
- M5 dogfood/docs exit criteria 由 Phase 8/9 完成：Phase 8 负责 Memory refactor docs update，Phase 9 负责 memory synthetic review scenario 和 final verification。
- Track M complete 需要 Phase 5 + Phase 8 + Phase 9 都完成。
- 不降低 Memory governance 测试要求：memory dogfood 通过、docs updated 仍是 Track M 完整完成条件。

## 4. Track D: Dogfood runner refactor

### Characterization tests

覆盖：

- dogfood trustworthiness unchanged。
- synthetic checks 标记为 deterministic synthetic validation。
- real-api dogfood gated。
- provider preflight 走 provider factory。
- project dotenv scoped loader。
- no shell env fallback。
- report 字段保持可审计。

### Refactor tests

覆盖：

- scenario definition 不执行 provider / shell / MCP。
- execution 层产生 structured result。
- governance matrix aggregation 不伪造 pass。
- report rendering 不修改 result。
- provider preflight helper 统一 identity / gated / scoped dotenv 逻辑。

### Negative tests

覆盖：

- uncovered boundary 不能标记 pass。
- synthetic actual 不能冒充 real execution。
- shell env fallback 被拒绝。
- secret-like value 不出现在 report。
- dogfood runner 不能绕过 provider factory。

### Selected test command

```bash
python -m pytest tests/test_global_real_api_dogfood.py tests/test_provider_real_smoke.py tests/test_architecture_boundaries.py -q
```

### Full pytest trigger

触碰 dogfood runner、provider preflight、governance matrix、report rendering、secret redaction 时必须运行：

```bash
HOME=/private/tmp/my-first-agent-v0.9.x-dogfood-home python -m pytest tests/ -x -q
```

### Exit criteria

- dogfood trustworthiness unchanged。
- global synthetic dogfood 通过。
- real-api dogfood 仍 gated。
- report 说明 evidence source。

## 5. Track G: Config unification

### Characterization tests

覆盖：

- provider config unchanged。
- import `config.py` 不触发 dotenv。
- `agent/provider/config.py` 是 provider/API config authority。
- `agent/local_config.py` 不展开 env secret。
- project dotenv scoped loader 显式 opt-in。

### Refactor tests

覆盖：

- legacy `config.py` 职责被 docstring / tests 固定为 runtime/CLI 兼容。
- provider dogfood 不依赖 legacy config。
- local config 不连接 provider。
- 重复 helper 迁移后调用路径一致。

### Negative tests

覆盖：

- import-time `load_dotenv()` 禁止。
- shell env fallback 禁止。
- provider identity 不能靠 URL/model 猜测。
- secret-like config 不进入 logs / reports / checkpoint。

### Selected test command

```bash
python -m pytest tests/test_provider_config.py tests/test_local_config.py tests/test_global_real_api_dogfood.py -q
```

### Full pytest trigger

触碰 provider config、legacy config、local config、dotenv loader、dogfood real-api config 时必须运行：

```bash
HOME=/private/tmp/my-first-agent-v0.9.x-config-home python -m pytest tests/ -x -q
```

### Exit criteria

- provider config unchanged。
- no secret tracking。
- docs updated。
- ruff + full pytest 通过。

## 6. Track T: Large tests split

### Characterization tests

Large tests split 本身以现有测试为 characterization coverage。拆分前必须记录：

- 原测试文件列表。
- 每个文件的主题分组。
- 关键测试名和断言。
- selected commands。

### Refactor tests

覆盖：

- 拆分后 pytest discover 稳定。
- 旧主题在新文件中仍有对应测试。
- helper fixtures 不引入真实 `.env` / sessions / runs。
- 测试注释解释治理边界。

### Negative tests

覆盖：

- 不删除历史覆盖。
- 不弱化断言。
- 不通过 skip / xfail 隐藏失败。
- 不把多个无关主题塞进新巨石测试文件。

### Selected test command

根据拆分主题选择原文件和新文件，例如：

```bash
python -m pytest tests/test_v0_4_transition_boundaries.py -q
python -m pytest tests/test_memory_emergence.py tests/test_memory_fs_store.py -q
```

### Full pytest trigger

任何测试拆分完成后都必须运行：

```bash
HOME=/private/tmp/my-first-agent-v0.9.x-test-split-home python -m pytest tests/ -x -q
```

### Exit criteria

- characterization coverage preserved。
- pytest discover 稳定。
- no secret tracking。
- full pytest 通过。
- Large tests split 后必须更新所有引用旧测试文件的 selected commands；不允许保留指向已拆分失效文件的命令。

## 7. Track B: Benchmark baseline

### Characterization tests

覆盖：

- benchmark reproducibility。
- golden traces 可生成并比较。
- fixed synthetic inputs hash 稳定。
- governance matrix expected / actual 可比较。
- Memory / Skill / SubAgent sample 行为稳定。

### Refactor tests

覆盖：

- benchmark runner 不读 `.env`。
- benchmark runner 不调用真实 LLM。
- benchmark report 包含 scenario id、input hash、expected boundary、actual boundary、result、regression status。
- failure 能定位具体 boundary。

### Negative tests

覆盖：

- input 变化导致 hash 变化。
- expected boundary 为空时不能默认 pass。
- uncovered 不等于 pass。
- synthetic quality 不能标记 real-api。

### Selected test command

```bash
python -m pytest tests/test_global_real_api_dogfood.py tests/test_skill_dogfood.py tests/test_subagent_dogfood.py -q
```

如果新增 benchmark 测试文件，命令应改为：

```bash
python -m pytest tests/test_stabilization_benchmark_baseline.py -q
```

### Full pytest trigger

触碰 benchmark runner、golden traces、dogfood stable scenarios、governance matrix 时必须运行：

```bash
HOME=/private/tmp/my-first-agent-v0.9.x-benchmark-home python -m pytest tests/ -x -q
```

### Exit criteria

- benchmark reproducibility。
- docs updated。
- dogfood baseline 可复现。
- full pytest 通过。

## 8. Docs/audit status

每个 Track 完成或延期都必须更新：

- `docs/refactor/V0_9_X_AUDIT_CHECKLIST.zh.md` 的执行结果或引用报告。
- `docs/06-audit/CURRENT_AUDIT_STATUS.zh.md` 的 P3 backlog 状态。
- 必要时更新 README 的下一阶段路线入口。

Docs/audit 变更也要运行：

```bash
git diff --check
ruff check agent tests scripts
```

## 9. 总退出标准

v0.9.x stabilization implementation loop 完成前必须满足：

- core behavior unchanged。
- memory governance unchanged。
- dogfood trustworthiness unchanged。
- provider config unchanged。
- no secret tracking。
- benchmark reproducibility。
- docs updated。
- `ruff check agent tests scripts` 通过。
- full pytest with temp HOME 通过。
- independent audit readiness 为 yes。
