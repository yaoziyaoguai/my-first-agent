# v0.9.x Dogfood and Benchmark Plan

Status: Dogfood / benchmark design for v0.9.x stabilization.

本文定义 v0.9.x Stabilization / P3 Refactor Track 的 dogfood 和 benchmark baseline。目标是证明重构没有破坏现有治理边界，不是建设完整 Observability Platform，也不是默认运行 real API。

## 1. 原则

- Dogfood 证明边界，不粉饰结果。
- Benchmark 证明可复现，不追求漂亮数字。
- Synthetic checks 是 deterministic synthetic validation，不能冒充 real execution。
- Real-api dogfood 是 gated，不能作为每次 refactor 必跑项。
- 不读取 `.env`、`agent_log.jsonl`、真实 sessions/runs、`memory/episodes/*.jsonl` 内容。
- 不调用真实 LLM，除非用户在独立 real-api dogfood 阶段明确授权。
- Trace / runtime events / streaming events 只作为 debugging and audit evidence，不作为独立产品能力扩张。

## 2. Baseline dogfood

### 2.1 Global synthetic dogfood

目标：验证 Runtime、ToolRegistry、Memory、Skill、SubAgent、Checkpoint、Confirmation、CLI/TUI 和 secret safety 的稳定边界。

预期覆盖：

- Parent Runtime owns orchestration。
- ToolRegistry remains authority。
- Memory governance remains authority。
- Skill/SubAgent 不直接执行工具、不直接写 Memory、不拥有主 loop。
- Checkpoint 只保存安全 projection。
- Confirmation 保持人工控制边界。
- Provider path 不绕过 factory。
- Secret-like value 不进入 report。

### 2.2 Skill synthetic dogfood

目标：验证 Formal Skill System 的 metadata-first、progressive disclosure、tool/memory/checkpoint 边界。

预期覆盖：

- Skill descriptor 可发现。
- Skill body 只在选择后加载。
- Level 3 resources 只按需加载。
- `allowed_tools` 只是 upper-bound，不是授权。
- Skill memory proposals 进入 Memory governance。
- Synthetic output 不包含 secret。

### 2.3 SubAgent synthetic dogfood

目标：验证 SubAgent L0 safe-local baseline。

预期覆盖：

- Parent-controlled delegation。
- L0 deterministic/local execution。
- Parent adjudication。
- SubAgent 不拥有主 loop。
- SubAgent 不直接执行 ToolRegistry。
- SubAgent 不直接写 Memory。

### 2.4 Memory synthetic review scenario

目标：验证 Memory proposal、pending review、inline confirmation、store 的 governance。

预期覆盖：

- 自动路径只产生 proposal。
- 未确认前不 retain。
- 用户确认后才写入。
- reject / edit / defer 可解释。
- filesystem-first store。
- Skill/SubAgent memory proposal 不直接落盘。

## 3. Benchmark baseline

### 3.1 Golden traces

Golden traces 是固定 synthetic input 下的可比较 evidence。它们只记录 debugging and audit evidence，不形成完整 observability pipeline。

每条 golden trace 至少包含：

- scenario id。
- input hash。
- runtime boundary summary。
- provider boundary summary。
- memory governance summary。
- checkpoint / confirmation summary。
- dogfood governance result。

禁止：

- 记录 secret。
- 记录真实 sessions/runs 内容。
- 记录完整 prompt / API key / token。
- 设计 span hierarchy 或 metrics system。

### 3.2 Fixed synthetic inputs

每个 benchmark scenario 使用固定输入：

- 输入文本固定。
- fixture 固定。
- expected boundary 固定。
- expected governance matrix 固定。
- input hash 稳定。

输入变化必须导致 hash 变化，避免 benchmark 在无意中比较不同任务。

### 3.3 Expected governance matrix

Governance matrix 应覆盖：

- Runtime。
- Provider。
- ToolRegistry。
- Memory。
- Skill。
- SubAgent。
- Checkpoint。
- Confirmation。
- CLI/TUI adapter。
- Secret safety。

Uncovered boundary 必须标记 `uncovered` 或 `not_run`，不能默认 pass。

### 3.4 Expected memory proposal behavior

Memory benchmark 样本应证明：

- candidate 可以出现。
- proposal 可以进入 pending review。
- 未确认不写入。
- confirmation 后写入。
- rejection 不写入。
- fake extractor 输出只作为 synthetic sample。

### 3.5 Expected skill selection behavior

Skill benchmark 样本应证明：

- metadata-only selection。
- ambiguous selection 不强行猜测。
- disabled / hidden Skill 不可见。
- body/resource 不预加载。
- requested tools 仍受 ToolRegistry authority。

### 3.6 Expected subagent delegation behavior

SubAgent benchmark 样本应证明：

- L0 local deterministic delegation。
- Parent adjudication。
- no SubAgent-owned loop。
- no direct tool execution。
- no direct Memory write。

### 3.7 Safety regression scenarios

Safety baseline 至少覆盖：

- `.env` 不被读取。
- shell env fallback 被拒绝。
- secret-like value redaction。
- runtime data 不被 tracked。
- checkpoint projection 不持久化大 tool result。
- synthetic checks 不冒充 real execution。

## 4. Report format

每个 dogfood / benchmark report entry 使用以下字段：

| Field | Meaning |
|---|---|
| `scenario_id` | 稳定的 scenario id |
| `input_hash` | fixed synthetic input 的 hash |
| `expected_boundary` | 预期保护的架构边界 |
| `actual_boundary` | 实际观察到的边界行为 |
| `result` | `pass` / `fail` / `skipped` / `gated` / `uncovered` |
| `regression_status` | `none` / `regression` / `unknown` / `not_comparable` |

推荐扩展字段：

| Field | Meaning |
|---|---|
| `evidence_source` | `synthetic` / `real_api_gated` / `unit_test` / `benchmark` |
| `expected_governance` | 预期 governance matrix 摘要 |
| `actual_governance` | 实际 governance matrix 摘要 |
| `safe_preview` | 已脱敏的短摘要 |
| `skip_or_gate_reason` | skipped/gated 的原因 |

## 5. 不默认跑 real API

Real-api dogfood 是 gated：

- 不能作为每次 refactor 必跑项。
- 不能在没有用户明确授权时读取 `.env`。
- 不能使用 shell env fallback。
- 必须通过 project `.env` scoped loader。
- 必须走 provider factory。
- 失败时不能用 synthetic pass 掩盖。

默认 stabilization loop 必跑的是 synthetic dogfood、selected tests、benchmark baseline 和 full pytest。Real-api dogfood 只在用户明确授权的独立阶段运行。

## 6. Observability future track

本计划不引入 OpenTelemetry、dashboard、trace viewer、metrics system、span hierarchy 或复杂 event pipeline。

后续等 First Agent 全部核心能力达标后，可以单独启动 Observability Track，统一设计：

- Runtime trace。
- event viewer。
- OpenTelemetry / OpenInference 是否接入。
- dashboard / viewer。
- span model。
- metrics / evaluation integration。

这些都不进入 v0.9.x stabilization implementation scope。
