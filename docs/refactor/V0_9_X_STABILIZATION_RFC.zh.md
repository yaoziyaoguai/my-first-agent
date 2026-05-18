# v0.9.x Stabilization RFC

Status: Draft plan for v0.9.x stabilization / P3 refactor track.

本文是 v0.9.0 tag 之后的稳定化 RFC。它不是功能扩张提案，也不是立即实施补丁。
后续 Coding Agent 必须先通过本文、SDD、TDD、Implementation Loop、Dogfood/Benchmark Plan 和 Audit Checklist 的独立审计，再进入实现循环。

## 1. 背景

`v0.9.0` 已经是完整阶段性里程碑。当前已经完成：

- Memory 主线：filesystem-first governance、interactive confirmation、pending review、consolidation/emergence foundation。
- Formal Skill System：metadata-first、progressive disclosure、ToolRegistry / Memory / Checkpoint 边界。
- SubAgent L0 safe-local baseline：本地 deterministic delegation、Parent adjudication、L1-L5 gated。
- Provider 四路统一：Anthropic/OpenAI native + compatible APIs 统一走 provider factory。
- Streaming Protocol：provider-backed streaming path 与 runtime event 边界。
- Global Dogfood：Runtime、ToolRegistry、Memory、Skill、SubAgent、Checkpoint、Confirmation、CLI/TUI 和 secret safety 的 synthetic governance matrix。
- 中文文档体系：中文优先入口、架构、测试、审计状态。
- final legacy adapter audit gaps fixed：provider / streaming / legacy SDK bypass 已收口。

因此 v0.9.x 不应继续叠加大功能。下一阶段目标是稳定性、架构优雅度、可维护性和评估基线。这是 Harness Engineering 的 stabilization track：先把现有行为纳入可验证 harness，再做行为中性的结构优化，最后用 dogfood、benchmark、full pytest 和独立审计证明没有破坏边界。

Harness Engineering 在本项目里的含义是：

- 先写清目标、边界、测试、dogfood、benchmark 和审计规则。
- 先建立 characterization tests（特征化测试）和 golden traces（金丝雀轨迹），再移动代码。
- 每个小切片都被 harness 包住：测试证明、dogfood 证明、文档证明、审计证明。
- 重构不是“把文件拆小”，而是让高内聚（high cohesion）、低耦合（low coupling）、架构优美（architectural elegance）和编程的艺术（the art of programming）在证据中成立。

## 2. Goals

v0.9.x stabilization 的目标是 P3 backlog 的可控消化，而不是新能力扩张。

- `core.py` slimming：逐步把主循环巨石拆成高内聚模块，同时保持 Parent Runtime 语义不变。
- Memory module refactor M1-M5：先特征化，再梳理 emergence / proposal / review / store / confirmation / consolidation 边界。
- Dogfood runner refactor D1-D4：把 scenario definition、provider preflight、governance matrix aggregation、report rendering 分离。
- Config unification：减少 `config.py`、`agent/provider/config.py`、`agent/local_config.py` 的职责重叠，保持 provider/API 配置权威清晰。
- Large tests split：拆分大测试文件时保留 characterization coverage，不为了拆而拆。
- Regression benchmark baseline：建立可复现 golden traces、固定 synthetic inputs、governance matrix 和质量样本。
- Docs/audit status 同步：让 README、当前审计状态、测试矩阵和 stabilization 文档保持一致。
- Minimal debug/audit support：只保留定位 Runtime / Provider / Memory / Skill / SubAgent / ToolRegistry 问题所需的 trace / runtime event / audit evidence，不建设完整 Observability Platform。

## 3. Non-goals

v0.9.x stabilization 明确不做：

- 不做 SubAgent L1/L2。
- 不做 SubAgent L3/L4。
- 不做 DB / graph / embedding / vector store。
- 不做 checkpoint schema 大改。
- 不做 Web UI / SaaS。
- 不做 remote Skill marketplace。
- 不做真实 shell / worktree automation。
- 不改变 Memory governance。
- 不改变 ToolRegistry authority。
- 不让 Skill/SubAgent 拥有主 Agent loop。
- 不把 real API dogfood 变成默认必跑项。
- 不引入 import-time `load_dotenv()`。
- 不做完整 Observability Platform。
- 不引入 OpenTelemetry。
- 不做 dashboard。
- 不做 trace viewer。
- 不做 metrics system。
- 不做 span hierarchy 大设计。
- 不做复杂 event pipeline。
- 不为了 observability 扩大 runtime 复杂度。
- 不让 observability 变成新的主架构线。
- 不读取 `.env`、`agent_log.jsonl`、真实 `sessions/`、真实 `runs/`、`memory/episodes/*.jsonl` 内容。

## 4. 核心原则

### 4.1 Behavior-neutral refactor first

第一优先级是行为中性重构。任何模块移动、函数抽取、测试拆分都必须证明：

- core loop 行为不变。
- checkpoint / confirmation / memory / tool result 行为不变。
- provider config 行为不变。
- dogfood 可信度不下降。

如果发现行为变化，默认先停止并定位根因，而不是把测试改成绿。

### 4.2 Characterization tests first

对现有复杂行为先写 characterization tests。尤其是 `core.py`、Memory、dogfood runner、config、large tests 这些承载历史行为的区域，必须先证明当前行为是什么，再讨论移动边界。

### 4.3 No architecture bypass

稳定化不能绕过现有治理边界：

- Parent Runtime owns orchestration。
- ToolRegistry remains authority。
- Memory governance remains authority。
- Checkpoint remains safety boundary。
- Confirmation / Ask User remains human-control boundary。
- Skill/SubAgent 不能直接执行工具、写 Memory、调用 provider 或拥有主 loop。

### 4.4 No dogfood shortcut

Dogfood refactor 不能把结果变成 scripted pass。Synthetic checks 可以是 deterministic validation，但不能冒充 real execution。Real-api dogfood 必须 gated，并且继续走 provider factory 和 project `.env` scoped loader。

### 4.5 No secret access

实现、测试、dogfood、benchmark、审计都不得读取或打印 secret。禁止读取 `.env`、`agent_log.jsonl`、真实 sessions/runs、`memory/episodes/*.jsonl` 内容。禁止通过 shell env fallback 偷偷拿 provider key。

### 4.6 High cohesion / low coupling

每次拆分必须能回答：

- 这个模块的单一职责是什么？
- 它和 Parent Runtime、Memory、ToolRegistry、Provider、Dogfood 的边界是什么？
- 它是否减少真实复杂度，还是只把复杂度搬到另一个地方？
- 后续一年后维护者是否能从命名和数据流读懂设计意图？

不机械拆文件；不制造贫血抽象（anemic abstraction）；不制造新巨石；不为了行数指标牺牲清晰边界。

### 4.7 Evidence-driven root cause

以证据定位问题，而不是表面打补丁。后续实现遇到失败时，必须先看测试输出、dogfood report、runtime events、checkpoint projection、persisted state 和 audit diff，再修改代码。

### 4.8 Chinese learning comments

后续实现时，关键生产代码和测试必须添加中文学习型注释或 docstring，用来解释架构边界、状态转换、governance 意图、fake/local-only seam 或错误处理取舍。不要注释显而易见的语法。

### 4.9 Minimal observability only

v0.9.x stabilization 中的 Observability / Trace / Runtime Event / Monitoring 只做 minimal debug/audit support。允许保留或小幅整理的事件和记录，只能服务以下目标：

- 定位 Runtime / Provider / Memory / Skill / SubAgent / ToolRegistry 问题。
- 支持 dogfood 结果证明。
- 支持 audit evidence。
- 支持 checkpoint / confirmation / boundary debugging。

如果文档或后续实现涉及 trace、runtime events、streaming events，它们只能作为 debugging and audit evidence，不作为独立产品能力扩张。本阶段不引入 OpenTelemetry、不做 dashboard、不做 trace viewer、不做 metrics system、不做 span hierarchy 大设计、不做复杂 event pipeline，也不为了 observability 扩大 runtime 复杂度。

完整 Observability Track 是 future track。First Agent 核心能力全部达标后，才单独设计 Runtime trace、event viewer、OpenTelemetry / OpenInference 是否接入、dashboard / viewer、span model、metrics / evaluation integration。

## 5. Refactor Tracks

### Track C: `core.py` slimming

目标：把 `core.py` 从主循环巨石逐步拆成高内聚模块。主 loop 语义、checkpoint、confirmation、memory、tool result、streaming 行为必须保持不变。

候选方向：

- pending confirmation dispatch。
- model output dispatch。
- runtime event bridge。
- state transition helper。
- loop dependency assembly。

不允许：

- 改变主 Agent loop ownership。
- 改变 checkpoint schema。
- 改变 ToolRegistry 调用权威。
- 改变 Memory confirmation / pending_review 行为。

### Track M: Memory module refactor

目标：按 M1-M5 梳理 Memory 边界。

- M1 characterization tests。
- M2 emergence / proposal / review / store 边界梳理。
- M3 confirmation semantics centralization。
- M4 consolidation / snapshot boundary split。
- M5 memory dogfood + docs update。

必须保持：

- no silent retain。
- no auto approve。
- `pending_review`。
- inline confirmation。
- filesystem-first。
- Skill/SubAgent 不直接写 Memory。

### Track D: Dogfood runner refactor

目标：提升 dogfood runner 的结构质量，同时不降低 dogfood 可信度。

- D1 scenario definition vs execution separation。
- D2 provider preflight helper consolidation。
- D3 governance matrix aggregation extraction。
- D4 report rendering extraction。

必须保持：

- synthetic checks 不冒充 real execution。
- real-api 走 provider factory。
- project dotenv scoped loader。
- no shell env fallback。
- no secret leak。
- report 字段能解释 evidence source。

### Track G: Config unification

目标：减少三套 config 概念重叠，明确配置权威。

- `config.py`：legacy runtime/CLI 兼容职责。
- `agent/provider/config.py`：provider/API config authority。
- `agent/local_config.py`：local runtime customization metadata。

必须保持：

- 不引入 import-time `load_dotenv()`。
- project dotenv scoped loader 继续安全。
- provider dogfood 不退回 legacy `config.py` 或 shell env fallback。

### Track T: Large tests split

目标：让大测试文件按主题可维护，但不丢历史覆盖。

原则：

- characterization coverage preserved。
- 不为了拆而拆。
- 先按主题建立目标文件。
- 保持 pytest discover 稳定。
- 不删除历史覆盖。

### Track B: Benchmark baseline

目标：建立稳定可复现的 regression benchmark baseline。

包含：

- golden traces。
- global dogfood stable scenarios。
- provider compatibility matrix。
- memory quality samples。
- skill selection samples。
- subagent L0 delegation samples。
- safety regression scenarios。

Benchmark 不追求性能数字好看，而是让行为边界和治理矩阵在重构前后可比较。

## 6. 成功标准

v0.9.x stabilization 完成时必须满足：

- 所有 Track 的目标行为都有 characterization tests 或 benchmark sample。
- docs-only 计划、实现 diff、dogfood report、audit checklist 能互相追踪。
- `ruff check agent tests scripts` 通过。
- full pytest with temp HOME 通过。
- synthetic global / skill / subagent / memory review dogfood 通过。
- real-api dogfood 仍是 gated，不作为默认 refactor 必跑项。
- 独立审计确认 P0/P1/P2 为 0；剩余 P3 明确记录。
