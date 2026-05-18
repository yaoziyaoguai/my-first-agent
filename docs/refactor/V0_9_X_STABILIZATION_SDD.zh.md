# v0.9.x Stabilization SDD

Status: Software Design Document for v0.9.x stabilization / P3 refactor track.

本文描述后续稳定化重构的设计边界。它不实现代码，不要求一次性大拆，也不允许绕过 v0.9.0 已建立的 Runtime、ToolRegistry、Memory、Checkpoint、Skill、SubAgent 和 Provider governance。

## 1. 总体设计方向

v0.9.x 的设计目标不是“让文件变少或行数变少”，而是让系统拥有更高内聚、更低耦合、更清晰的数据流和更优美的架构表达。好的重构应该让一个一年后的维护者能快速看懂：

- 这个模块负责什么。
- 它不负责什么。
- 它从哪里接收状态。
- 它把结果交给谁。
- 它遵守哪些 governance 边界。
- 它的测试如何证明行为不变。

后续实现必须先读：

- `docs/refactor/V0_9_X_STABILIZATION_RFC.zh.md`
- `docs/refactor/V0_9_X_STABILIZATION_TDD.zh.md`
- `docs/refactor/V0_9_X_IMPLEMENTATION_LOOP.zh.md`
- `docs/refactor/V0_9_X_DOGFOOD_AND_BENCHMARK_PLAN.zh.md`
- `docs/refactor/V0_9_X_AUDIT_CHECKLIST.zh.md`

关键生产代码和测试应添加中文学习型注释或 docstring，解释架构边界、状态转换、fake/local-only seam、错误处理和 governance 意图。

## 1.1 Observability 设计边界

v0.9.x stabilization 不建设完整 Observability Platform。Trace、runtime events、streaming events、monitoring 字样在本文中只表示 minimal debug/audit support。

允许保留或整理的事件和记录，只能支持：

- 定位 Runtime / Provider / Memory / Skill / SubAgent / ToolRegistry 问题。
- 支持 dogfood 结果证明。
- 支持 audit evidence。
- 支持 checkpoint / confirmation / boundary debugging。

本阶段明确不做：

- 不引入 OpenTelemetry。
- 不做 dashboard。
- 不做 trace viewer。
- 不做 metrics system。
- 不做 span hierarchy 大设计。
- 不做复杂 event pipeline。
- 不为了 observability 扩大 runtime 复杂度。
- 不让 observability 变成新的主架构线。

完整 Observability Track 记录为 future track，后续再统一设计 Runtime trace、event viewer、OpenTelemetry / OpenInference、dashboard / viewer、span model、metrics / evaluation integration。

## 2. Track C: `core.py` slimming

### 2.1 目标

把 `core.py` 从主循环巨石逐步拆成高内聚模块，同时不改变主 loop 语义，不改变 checkpoint / confirmation / memory / tool result 行为。

`core.py` 后续应保留 runtime orchestration 的中心位置。它可以变薄，但不能退化成隐式 glue，也不能把主 loop ownership 交给 Skill、SubAgent、CLI/TUI 或 helper 模块。

### 2.2 候选边界

可以考虑抽出的边界：

- pending confirmation dispatch：处理等待用户确认的 tool / memory / runtime action 分派。
- model output dispatch：把 provider/model output 分派为 tool request、text output、memory proposal、final response。
- runtime event bridge：把内部 runtime 状态投影成 debugging and audit evidence，不拥有状态机，也不扩展成 observability platform。
- state transition helper：封装可测试的状态转换 helper，但不拥有 loop。
- dependency assembly helper：集中组装 runtime 所需 dependency，减少 `core.py` 顶部 import 和初始化噪声。

已抽出的 `model_call` 应继续保持 provider-backed 路径，不回退 legacy SDK bypass。

### 2.3 什么能抽

能抽的是“可独立命名、输入输出明确、不会拥有主 loop 的纯边界或窄适配器”：

- 输入是当前 runtime state / provider output / pending action。
- 输出是明确的 dispatch decision / event projection / transition proposal。
- 不直接读 `.env`。
- 不直接调用真实 LLM。
- 不直接执行工具。
- 不直接写 Memory。
- 不保存 checkpoint。

这些 helper 可以返回结构化结果，由 Parent Runtime 统一应用。

### 2.4 什么不能抽

不能抽的是会改变系统权威的部分：

- 主 Agent loop ownership。
- ToolRegistry authority。
- Memory governance。
- checkpoint schema 和保存时机。
- confirmation policy。
- provider factory authority。
- Skill/SubAgent delegation adjudication。

尤其不能创建一个新的 `runtime_manager.py` 巨石，把 `core.py` 的复杂度搬过去。目标不是迁移巨石，而是建立职责边界。

### 2.5 如何证明 behavior-neutral

Track C 必须用以下证据证明行为中性：

- core loop characterization tests 先红后绿或先锁定现状。
- checkpoint/resume tests 保持通过。
- confirmation / pending review tests 保持通过。
- provider streaming tests 保持通过。
- global synthetic dogfood 的 governance matrix 不退化。
- `git diff` 显示代码移动和职责抽取，不夹带功能变更。

如果抽出 helper 后测试失败，先判断失败是否揭示真实行为依赖。不得通过弱化断言、跳过测试、删除测试来制造绿。

### 2.6 成功标准

- `core.py` 职责更清楚，runtime orchestration 仍由 Parent Runtime 拥有。
- 新模块单一职责清晰，命名能表达设计意图。
- 没有新增跨层 import 循环。
- 没有新巨石。
- 行为中性由 selected tests、full pytest 和 dogfood 证明。

## 3. Track M: Memory module refactor M1-M5

### 3.1 目标

Memory 当前是健康但偏大的核心区域。v0.9.x 的目标是先用 characterization tests 包住行为，再按边界拆分 emergence、proposal、review、store、confirmation、consolidation 和 snapshot。

必须保持：

- no silent retain。
- no auto approve。
- `pending_review`。
- inline confirmation。
- filesystem-first。
- Skill/SubAgent 不直接写 Memory。
- Memory governance 是 authority。

### 3.2 M1: characterization tests

M1 不重构生产代码，先锁住当前语义：

- 用户确认前不得 retain。
- 自动抽取结果只能进入 proposal / pending review。
- inline confirmation 后才允许写入。
- rejection / ignore / edit 路径可追踪。
- fake extractor 与 provider-backed extractor 的边界明确。
- Skill/SubAgent memory proposal 必须经过 parent Runtime / Memory governance。

M1 测试中应加入中文学习型注释，解释为什么这些断言是治理边界，而不只是实现细节。

### 3.3 M2: emergence / proposal / review / store 边界梳理

M2 的候选边界：

- emergence detector：识别可能值得记忆的信号，不决定保存。
- proposal builder：把候选信号转成 memory proposal，不越权批准。
- review queue：承载 `pending_review` 状态和用户可见解释。
- store adapter：负责 filesystem-first 持久化，但只接收已批准写入。

不允许：

- emergence 直接写 store。
- proposal builder 自动 approve。
- review queue 偷偷 drop 用户拒绝证据。
- store adapter 读取 Skill/SubAgent 私有目录或真实 episodes 内容。

### 3.4 M3: confirmation semantics centralization

M3 将 Memory confirmation 语义集中表达：

- `confirm` / `reject` / `edit` / `defer` 的输入输出明确。
- inline confirmation 与 pending review 使用同一组语义对象。
- confirmation 结果由 Memory governance 应用，不由 CLI/TUI 或 Skill/SubAgent 应用。

集中语义不是为了制造抽象层，而是避免多处代码用不同词语表达同一状态转换。

### 3.5 M4: consolidation / snapshot boundary split

M4 拆分 consolidation 与 snapshot 边界：

- consolidation 负责从已批准 Memory 中生成更高层摘要或候选，不越权写入。
- snapshot 负责保存可恢复视图，不改变 Memory governance。
- provider-backed consolidation 必须走 provider factory，不能直接构造 SDK client。
- synthetic consolidation dogfood 不能冒充 real LLM quality。

### 3.6 M5: memory dogfood + docs update

M5 更新 Memory dogfood 和文档：

- synthetic review scenario 覆盖 proposal、pending review、confirmation、store。
- docs 说明 fake/local-only seam 和 real LLM gated 边界。
- CURRENT_AUDIT_STATUS 同步 P3 完成或剩余状态。

### 3.7 成功标准

- Memory 行为不变，边界更清楚。
- 任何自动路径仍无法 silent retain / auto approve。
- Skill/SubAgent 仍不能直接写 Memory。
- Memory dogfood 和 selected tests 通过。

## 4. Track D: Dogfood runner refactor D1-D4

### 4.1 目标

Dogfood runner 当前承担了 scenario、execution、provider preflight、governance matrix 和 report rendering 多种职责。v0.9.x 的目标是拆出高内聚边界，同时不降低 dogfood 可信度。

### 4.2 D1: scenario definition vs execution separation

Scenario definition 应只描述：

- scenario id。
- input / fixture。
- expected boundary。
- expected governance checks。
- gated real-api requirement。

Execution 应负责：

- 运行 synthetic 或 gated real-api 路径。
- 收集 actual checks。
- 标记 evidence source。
- 产出结构化 result。

Scenario definition 不能直接执行 provider、shell、MCP 或写 runtime state。

### 4.3 D2: provider preflight helper consolidation

Provider preflight helper 应统一：

- provider config 是否来自 `agent/provider/config.py`。
- project dotenv scoped loader 是否显式启用。
- real-api dogfood 是否 gated。
- shell env fallback 是否被拒绝。
- provider identity 是否来自 explicit config fields，而不是 URL/model 猜测。

不允许：

- 从 shell env 偷偷读取 key。
- import-time `load_dotenv()`。
- dogfood runner 直接构造 SDK client。
- provider config 回退 legacy `config.py`。

### 4.4 D3: governance matrix aggregation extraction

Governance matrix aggregation 应接收 scenario results，并计算：

- Runtime boundary。
- ToolRegistry boundary。
- Memory governance。
- Skill boundary。
- SubAgent boundary。
- Checkpoint boundary。
- Confirmation boundary。
- CLI/TUI adapter boundary。
- Secret safety。

聚合器不能伪造 pass。未覆盖的 boundary 必须显示为 uncovered / not_run，而不是 pass。

### 4.5 D4: report rendering extraction

Report rendering 应负责：

- human-readable markdown/text report。
- JSON report。
- scenario result 表格。
- regression status。
- skipped/gated reason。

Rendering 不应执行 scenario，也不应修改 result。它只把结构化 evidence 展示出来。

### 4.6 必须保持

- synthetic checks 不冒充 real execution。
- real-api 走 provider factory。
- project dotenv scoped loader。
- no shell env fallback。
- no secret leak。
- dogfood 可信度不下降。

### 4.7 成功标准

- Dogfood runner 模块边界清楚。
- synthetic / real-api evidence source 明确。
- global synthetic dogfood 稳定通过。
- real-api dogfood 仍是 gated。
- report 更可审计，而不是更“好看”。

## 5. Track G: Config unification

### 5.1 目标

Config unification 的目标是减少误导和重叠，而不是一次性删除所有 legacy surface。

当前职责：

- `config.py`：legacy runtime/CLI 兼容职责。
- `agent/provider/config.py`：provider/API config authority。
- `agent/local_config.py`：local runtime config / customization metadata。

### 5.2 设计原则

- provider/API 配置以 `agent/provider/config.py` 为权威。
- legacy `config.py` 只能服务旧 runtime/CLI 兼容，不得成为 dogfood/provider authority。
- `agent/local_config.py` 不展开 env secret，不连接 provider。
- project dotenv scoped loader 必须显式调用，且只在 gated real-api dogfood 或用户明确授权时使用。
- 禁止 import-time `load_dotenv()`。

### 5.3 逐步减少重叠

推荐顺序：

1. 写 config characterization tests，证明当前 import 不读 `.env`。
2. 为 provider dogfood 写 explicit authority tests。
3. 给 legacy config 增加更清晰的注释/docstring 或 deprecation wording。
4. 将重复解析 helper 迁移到 provider config 或 local config 的权威位置。
5. 删除只由本轮迁移导致的 dead code。

### 5.4 成功标准

- 读者能从模块 docstring 看懂三套 config 的职责。
- provider dogfood 不再依赖 legacy config。
- import config 不触发 dotenv。
- no secret tracking tests 保持通过。

## 6. Track T: Large tests split

### 6.1 目标

Large tests split 的目标是保持历史 characterization coverage，同时提高测试可读性和局部运行效率。

### 6.2 设计原则

- 不为了拆而拆。
- 先按主题建立目标文件。
- 保持 pytest discover 稳定。
- 不删除历史覆盖。
- 不弱化断言。
- 测试名称表达行为，而不是实现路径。

### 6.3 推荐主题边界

候选拆分主题：

- runtime transition boundaries。
- memory emergence。
- memory confirmation。
- memory filesystem store。
- memory consolidation dogfood。
- provider compatibility。
- dogfood governance matrix。

拆分前必须列出原文件中的测试主题清单；拆分后必须证明测试数量、关键断言、selected commands 和 full pytest 行为未丢失。

### 6.4 成功标准

- 大测试文件拆分后，每个目标文件主题清楚。
- pytest discover 不变。
- coverage 没有被删减。
- 测试中的中文学习型注释解释治理边界。

## 7. Track B: Benchmark baseline

### 7.1 目标

Benchmark baseline 建立 refactor 前后的可复现比较基础。它不是性能竞赛，而是 regression harness。

### 7.2 Baseline 组成

- golden traces：固定输入下的 runtime event / checkpoint projection / governance result 摘要。
- global dogfood stable scenarios：覆盖 Runtime、ToolRegistry、Memory、Skill、SubAgent、Checkpoint、Confirmation、CLI/TUI、secret safety。
- provider compatibility matrix：Anthropic/OpenAI native + compatible API config shape，不默认真实调用。
- memory quality samples：proposal / pending review / confirmation 的 synthetic sample。
- skill selection samples：metadata-only selection 和 progressive disclosure。
- subagent L0 delegation samples：Parent-controlled local deterministic delegation。
- safety regression scenarios：secret safety、no shell env fallback、no direct tool execution、no direct Memory write。

### 7.3 数据格式

每个 benchmark sample 至少包含：

- scenario id。
- fixed input。
- input hash。
- expected boundary。
- expected governance state。
- actual boundary。
- actual governance state。
- result。
- regression status。

### 7.4 成功标准

- Benchmark 可在无真实 LLM、无 `.env`、无网络安装下运行。
- 结果可复现。
- 失败能定位具体 boundary，而不是只显示 overall failed。
- 不把 synthetic quality 写成 real LLM quality。
