# my-first-agent Canonical Roadmap

> **本文件目的**：以 **Agent Loop / Runtime** 为长期主干，按 **8 阶段顺序**
> 定义"该做什么、不该做什么、什么时候停"。
>
> **本文件是 canonical**：与本文件的 8 阶段顺序冲突的旧版"按版本号
> (v0.1/v0.2/v0.3/v1.0) 切片"内容仍保留在本文件后半部分作为**历史毕业证据**
> 与**版本映射表**，但**不**作为后续执行的真值源。
>
> **不是**：架构解读（看 `docs/ARCHITECTURE.md`）。
> **不是**：22 个 block 的待办清单（旧 22-block 结构归档在 `docs/ROADMAP_LEGACY.md`）。

---

## North Star

my-first-agent 的长期形态是 **本地、自用优先、未来可下载后自行配置的一键式
Agent Runtime**。

- ✅ **本地工具产品化**：单机/工作站可装、可配、可关、可审计
- ❌ **不是** SaaS
- ❌ **不是** Web UI
- ❌ **不是** 多用户平台
- ❌ **不是** 云端 agent 服务
- ❌ **不是** 复杂插件市场或 model extension/plugin framework

**最核心难点 = Agent Loop / Runtime**（state machine / dispatch / checkpoint /
tool execution / context boundary）。

后续 **TUI / Memory / sub-agent / Skill / Observability / Tool optimization /
Customization** 都必须**围绕 Agent Loop**；任何上层能力**不得反向污染 runtime
core**。

> **诚实声明**：当前 git 仓库已有 v0.5.1 等多个 tag、`agent/skills/` 已有原型代码、
> `memory/` 目录已有数据文件，**这些不等于对应 stage 已完成**——它们只是早期
> 阶段（Stage 0/1）跑出的副产物，正式毕业以本文件 Stage 3-8 的毕业标准为准。

---

## TL;DR — 8 stage canonical

| Stage | 主题 | 状态 | 主要承载版本 |
|---|---|---|---|
| **0** | Basic Agent Loop / early baseline | ✅ 已毕业 | v0.1（无 tag，毕业标准 ✅） |
| **1** | Agent Loop / Runtime hardening | 🟡 主要落地，**未全收口** | v0.2 / v0.3 / v0.4 / v0.5.0 / v0.5.1 |
| **2** | TUI interaction layer / HITL Input boundary | ✅ **阶段性收口** | v0.6.x |
| **2.5** | **Tooling Foundation Milestone** | ✅ v0.7.0 已 release；post-release dogfooding closure 已完成 | v0.7.0 |
| **3** | Memory system | ⏳ Tooling Foundation 后进入 Discovery | 后续 |
| **4** | Sub-agent / Handoff | 🟡 **Safe Local MVP 已完成；真实 delegation deferred** | 后续 |
| **5** | Skill system | 🟡 **Safe Local MVP 已完成；真实 install/execution deferred** | 后续（可轻量穿插） |
| **6** | Observability foundation | 🟡 **Local Trace Foundation 已完成；runtime wiring 持续打底** | 跨阶段 |
| **7** | Tool system optimization | 🟡 **Structured ToolResult seam 已完成；executor 迁移 deferred** | 靠后 |
| **8** | Customization / local productization | 🟡 **Local Config Foundation 已完成；真实安装/用户目录写入 deferred** | 后期 |

**全局停止规则**：
- 任何"我觉得这块该做"的改动，先回答："这属于哪个 Stage 的毕业标准？"
- 答不出 → **推迟到对应 Stage backlog**，不在当前 Stage 做。
- **Stage 2.5 Tooling Foundation Milestone 已完成**：不要在没有新证据时重开
  工具体系/MCP readiness；MCP CLI、外部 server 验证和 resources/prompts 等必须
  单独规划。
- **Memory System Discovery 后移到工具体系边界清楚之后**；Stage 4/5 的实质实现
  仍必须等 Memory 边界清楚后再启动（Stage 6/7 可作必要补丁）。

---

## Current Position

> **当前处于 Roadmap Completion Autopilot：safe local roadmap closure final review。**
> 注意：这不是重开 Web UI / SaaS / LangGraph / real external integration。

- ✅ v0.6.2 TUI MVP 已封版：paste burst / multiline input intent 已落地并有回归测试。
- ✅ Architecture / Module Debt 治理已阶段性完成：checkpoint ownership、
  runtime boundary、最小 helper extraction 已有 characterization tests 与 commits。
- ✅ HITL/Input boundary 已阶段性收口：User Input Resolution Contract 与
  input backend 不绕过 confirmation handlers 的 tests-only safety net 已建立。
- ✅ 历史 XFAIL backlog 已收口：复杂 topic switch 现在通过
  `awaiting_feedback_intent` 显式三选一完成；Textual Esc 在生成中会取消当前
  Assistant projection，阻止后续 chunk / completion 覆盖“已中断”提示。
- ✅ Memory System Discovery Roadmap Correction 已完成：Memory 是独立逻辑模块，
  RAG / retrieval / vector DB 只是后续 provider / recall backend 候选。
- ✅ Tooling Foundation 已 release 为 `v0.7.0`：base registry /
  ToolSpec metadata / ToolResult legacy seam / FileMutation path safety / MCP
  architecture seam / local stdio MCP validation 均有 tests。
- ✅ Post-release verification 已完成：本地与 remote `origin/main` / `v0.7.0`
  release 状态已核验，tools/MCP milestone 没有 release blocker。
- ✅ Self-dogfooding closure 已完成：第一轮和第二轮 dogfooding 覆盖 code
  reading、sandbox write、Ask User / Other free-text、tool failure、checkpoint /
  resume、MCP local list/call、confirmation pressure；第二轮 smoke coverage 已固化
  在 `tests/test_second_round_dogfooding_smoke.py`。
- ✅ Stage 3 Memory System foundation 已完成并发布：Candidate / Decision、
  explicit-only Policy、Snapshot prompt seam、Confirmation UX、OperationIntent /
  AuditSummary、fake Provider seam、deterministic dogfooding 都已落地。
- ✅ Memory-line Stage 4 safe local store skeleton 已完成并发布：只提供
  fake/local/test-only `MemoryStoreProtocol` + in-memory apply contract，不读取真实
  sessions/runs/logs，不写真实长期记忆，不默认接 runtime，也不让 prompt_builder
  直接读取 store。
- ✅ Memory-line Stage 5 governed snapshot generation 已完成并发布准备：只把
  fake/local `MemoryRecord` 通过 scope / budget / safety / provenance 过滤成
  `MemorySnapshot`，不做真实 retrieval/recall，不做 vectorization，不让
  prompt_builder 直接读 store。
- ✅ Memory-line Stage 6 manual UX dogfooding runbook 已完成并发布准备：只记录
  fake/local deterministic runbook、fixtures、expected behavior 与 safety checks，
  不读取真实 sessions/runs/logs，不接 provider/LLM/MCP/runtime。
- ✅ MCP CLI Config Management safe apply governance 已完成：parser/validator/
  redaction、CLI list/inspect/validate、plan preview、plan-first apply、`--yes`、
  backup、deterministic serialization、redacted diff evidence、safety manifest 都已
  落地；`tests/fixtures/mcp_config/safe-mcp.json` 与 `docs/MCP_CONFIG_MANAGEMENT.md`
  提供 fake fixture / review doc；不读真实 MCP config、不写 home config、不执行
  server command、不联网。
- ✅ Coding-agent execution governance 已落地 AGENTS.md：沉淀 repo path、安全边界、
  quality gates、evidence packet、P0/P1/P2/P3 与 controlled push/tag rules。
- ✅ Skill System Safe Local MVP 已完成：`agent.skills.local` 只读取 tmp_path /
  `tests/fixtures/skills`，生成 capability descriptor，不下载、不安装、不执行代码、
  不读真实 skill dirs、不绕过 parent runtime/tool policy。
- ✅ Subagent System Safe Local MVP 已完成：`agent.subagents.local` 只读取 tmp_path /
  `tests/fixtures/subagents`，生成 profile 与 parent-controlled delegation
  request/result，不做真实 LLM delegation、不 spawn process、不 remote delegation。
- ✅ Skill/Subagent Integration Boundary 已完成：`docs/CAPABILITY_BOUNDARIES.md` 与
  tests 固定 Tool = atomic execution、Skill = local descriptor、Subagent =
  parent-controlled delegation。
- ✅ Observability Local Trace Foundation 已完成：`agent.local_trace` 提供
  local-only trace file schema、`docs/LOCAL_TRACE_FOUNDATION.md`、run_id / trace_id / span_id、model/tool/state/
  checkpoint span 类型、metadata 脱敏与显式 tmp_path recorder；不读取真实 agent_log.jsonl，
  不读取真实 sessions/runs，不接 provider/network，不改 runtime core。
- ✅ Structured ToolResult Envelope Foundation 已完成：`ToolResultEnvelope` 与
  `classify_tool_result`（见 `docs/TOOL_RESULT_ENVELOPE.md`）把 legacy string contract 投影成 status / display event /
  error taxonomy / redacted preview；legacy string contract 仍兼容，未大改 executor。
- ✅ Local Config Foundation 已完成：`agent.local_config` 提供 `ProjectProfile` /
  `SafetyPolicy` / `ModuleToggles` / `ModelProviderConfig` 的显式 safe-path parser；
  `tests/fixtures/local_config/agent.local.json` 与 `docs/LOCAL_CONFIG_FOUNDATION.md`
  提供 fake fixture / review doc；不读取真实 home config，不读取 `.env`，不展开 env
  secret，不接 provider/network。
- ✅ Deferred Roadmap Boundaries 已记录：`docs/DEFERRED_ROADMAP_BOUNDARIES.md` 明确
  real MCP external integration、runtime trace wiring、ToolResult executor migration、
  real Skill/Subagent activation 与 release/tag 都是 planning-only / deferred 边界。
- ✅ Safe-Local Release Readiness 已记录：`docs/SAFE_LOCAL_RELEASE_READINESS.md`
  提供 manual smoke checklist、known limitations、no tag authorization 与 full pytest /
  ruff / diff-check 质量门。
- ✅ Remaining Roadmap Completion Autopilot 已记录：
  `docs/REMAINING_ROADMAP_COMPLETION_AUTOPILOT.md` 汇总 release/tag preparation
  planning、MCP external integration readiness、runtime trace / ToolResult migration
  planning，并明确所有真实 external / broad migration 动作仍 requires explicit user
  authorization。
- ❌ 真实 Skill install / execution 仍 deferred；旧 `agent.skills.installer` 仍是历史原型，
  不属于 Safe Local MVP 默认路径。
- ❌ 真实 LLM subagent delegation 仍 deferred；当前没有 provider 调用、外部进程或
  autonomous child tool execution。
- ❌ 当前没有完整 MCP spec 支持：未接外部 MCP server、未做 resources/prompts/
  sampling/roots、未做 production remote server auth、未做 release packaging。
- ❌ 当前还没进入 Stage 4 sub-agent、Stage 5 Skill 真实外部激活，也不做 Hook / RAG /
  embedding / vector DB 实现。

> 口径：**Tooling Foundation Milestone / Stage 3 Memory foundation 已完成**；
> Memory-line Stage 4/5/6 只是 fake/local storage seam + governed snapshot seam
> + manual UX dogfooding，不是完整长期 memory 产品化。后续若继续，应进入
> Memory Architecture Final Review 或单独回到
> MCP CLI Config Management。Memory 不是 RAG Discovery。
> Retrieval / RAG / vector DB / embedding 只能作为后续 Memory Provider backend
> 或 Knowledge Access strategy 的候选，不是与 Memory 并列的大 Roadmap 能力。

---

## Final Staged Roadmap

### Stage 0 · Basic Agent Loop / early baseline

**主题**：让最简版本能跑端到端任务。

**主要承载**：v0.1（无 tag，毕业标准 ✅，详见 `docs/V0_1_GRADUATION_REPORT.md`）

**已具备**：
- end-to-end loop（`agent/core.py` chat() + planner）
- 12 个工具 + tool_use/tool_result 链路
- 最小确认流（plan + tool 确认）
- checkpoint 雏形（roundtrip 已通）
- CLI 输出契约（`docs/CLI_OUTPUT_CONTRACT.md` 已冻结）

**已知限制**：skill / 安全围栏 / observer 高级化 / TUI MVP / Memory / sub-agent 全是后话。

---

### Stage 1 · Agent Loop / Runtime hardening

**主题**：把 Stage 0 跑通的能力**工程化**：边界、转移、恢复、可观察。

**主要承载**：v0.2 / v0.3 / v0.4 / v0.5.0 / v0.5.1

**毕业标准（必须全部 ✅ 才能宣布 Stage 1 收口）**：

| # | 项 | 当前 | 备注 |
|---|---|---|---|
| 1 | model output classification | ✅ | `classify_model_output` 4-value vocabulary（v0.5.1 钉死） |
| 2 | RuntimeEvent | ✅ | `agent/runtime_events.py` 572 行 |
| 3 | TransitionResult | ✅ | v0.4 落地 |
| 4 | state transitions | ✅ | 4 类 confirmation 走 TransitionResult（v0.4） |
| 5 | pending confirmation dispatch | ✅ | `_dispatch_pending_confirmation` 5 状态分发（v0.5.1） |
| 6 | pending user input | ✅ | feedback_intent transition 已就位 |
| 7 | pending tool | ✅ | ToolSuccess/ToolFailure transition（v0.4） |
| 8 | ToolSuccess / ToolFailure | ✅ | v0.4 |
| 9 | checkpoint / resume | 🟡 | leak guard ✅（v0.4）+ resume → pending dispatch bridge ✅（v0.5.1）；schema 版本管理 / 损坏自愈 / 跨版本兼容**未做** |
| 10 | context compression | ❌ | **未做** — Stage 1 残留 |
| 11 | context builder | 🟡 | 已存在；未做压缩/caching |
| 12 | prompt builder | 🟡 | 已存在；未做 prompt caching |
| 13 | runtime observer / logging | ✅ | v0.5 readability + confirmation evidence + terminal diagnostics → runtime events |

**当前完成度**：约 **80%**。第 9/10/11/12 项是 Stage 1 残留，**不阻塞** Stage 2，
但属于 Stage 1 backlog，**未来必须回补**才能宣布 Stage 1 正式毕业。

---

### Stage 2 · TUI interaction layer / HITL Input boundary ✅**阶段性收口**

**主题**：在不污染 runtime core 的前提下，把 textual.py / simple.py 从"已可用
但未被测试钉死"演进成"边界硬化 + TUI MVP 子集落地（解 Stage 1/2 历史 xfail）+
收口 release"。

**主要承载**：v0.6.x（v0.6.0 docs audit + v0.6.1 三层 boundary safety net +
v0.6.2 TUI MVP + HITL/Input contract closure）

**毕业标准（必须全部 ✅ 才能宣布 Stage 2 收口、才能进入 Stage 3 Memory）**：

| # | 项 | 当前 | 备注 |
|---|---|---|---|
| 1 | textual / simple input backend 已存在 | ✅ | textual.py 549 + simple.py 129 |
| 2 | Ask User / request user input | ✅ | User Input Resolution Contract 钉住 pending request / collect_input / normal input 边界；完整 UI polish 不继续扩大为 HITL 系统 |
| 3 | Other / free-text 路径 | ✅ | feedback/free-text 与普通新任务边界已由 tests 保护 |
| 4 | input backend 不 mutate runtime state | ✅ | v0.6.1 Group A/E + C 已钉 |
| 5 | input backend 不绕过 confirmation handlers | ✅ | `tests/test_input_backend_user_contract.py` C5：不 direct-call handlers、不读 pending/status、不按 awaiting status 分支 |
| 6 | display event contract | ✅ | v0.6.1 Group D 已钉 |
| 7 | display layer 不做 runtime decision | ✅ | v0.6.1 Group A/E AST baseline |
| 8 | no sensitive read | ✅ | v0.6.1 Group A/E 字面扫描；word-boundary regex 防 `.envelope` 假阳性 |
| 9 | historical xfailed inventory | ✅ | XFAIL-3 paste burst、XFAIL-1 topic switch、XFAIL-2 Textual Esc projection 均已闭合；真实 provider stream abort / cancel_token 仍是后续单独 runtime lifecycle 设计 |
| 10 | TUI MVP planning | ✅ | v0.6.2 MVP scope 已收敛到 paste burst / multiline intent |
| 11 | TUI MVP minimum implementation | ✅ | paste burst / multiline input intent 已落地；不顺手做 Esc cancel |
| 12 | TUI MVP regression tests | ✅ | real CLI / user_input / simple backend contract tests 已钉 |

**口径硬约束**：
- **只叫 TUI，不叫 TOI**
- **TUI 不是 Web UI**
- **HITL/Input 已阶段性收口后，不继续扩大成完整 HITL 系统**
- **历史 XFAIL backlog 已收口**；不得再把 XFAIL-1 / XFAIL-2 当成 open backlog 去继续堆 input backend/core.py
- **下一步只进入 Memory System Discovery / Architecture Planning，不直接实现 Memory/RAG**

#### v0.6.2 后 Architecture Debt Exit Criteria / Roadmap Quantification

> **目的**：v0.6.2 TUI MVP 封版后，本小节只用于约束 architecture/module debt
> 治理的退出条件，避免把"继续优化"无限扩大成新功能开发或大规模重构。

**当前阶段性质**：

- 这不是继续做 TUI 新功能；TUI v0.6.2 MVP 已封版，后续 TUI 改造必须单独立项。
- 这是 v0.6.2 后的 architecture/module debt 治理：用少量 characterization
  tests 与最小行为保持型 helper extraction，固定 checkpoint ownership、module
  boundaries、runtime transition ownership 等已识别关键边界。
- helper extraction 的目标不是"优化到完美"，而是消除当前已经被 inventory /
  characterization tests 证明存在的局部 ownership/module debt。

**优化目标**：

1. 固定 checkpoint ownership：明确谁可以 save/load/clear checkpoint，谁不能碰
   checkpoint，尤其是 input/display/TUI 边界层。
2. 固定 module boundaries：防止 input backend、display layer、user_input
   envelope 层获得 runtime state ownership。
3. 固定 runtime transition ownership：让 pending confirmation、pending user input、
   pending tool、tool execution log 等状态变更的 owner 清晰可审计。
4. 只做最小 helper extraction：行为保持、低风险、可 rollback，不引入 gateway、
   新 schema、新 runtime event 或新产品能力。

**验收标准**：

| # | 标准 | 当前要求 |
|---|---|---|
| 1 | Architecture Characterization Pack 1 | 已完成并 push 到 `origin/main` |
| 2 | Checkpoint Ownership Characterization Tests | 已完成、审计 PASS，并 push 到 `origin/main` |
| 3 | Roadmap quantification | 本小节写入可量化退出标准 |
| 4 | helper extraction 类型 | 必须是最小行为保持型重构 |
| 5 | 测试一致性 | helper extraction 前后 targeted tests / full pytest / ruff / diff check 保持通过 |
| 6 | characterization tests | 不允许因为重构弱化、删除、跳过或 xfail characterization tests |
| 7 | TUI scope | 不允许扩大到 TUI 新功能或 TUI 改造 |
| 8 | Memory / sub-agent / Skill | 不允许扩大到 Stage 3/4/5 实质实现 |
| 9 | historical XFAIL closure | 已完成；不得重开旧 XFAIL，真实 provider abort 只能作为后续单独 runtime lifecycle 设计 |
| 10 | checkpoint gateway | 不进入 gateway planning，除非 Roadmap 后续明确作为独立阶段 |

**停止条件**：

当以下条件同时满足时，本轮 Architecture Debt 治理应停止：

1. checkpoint ownership 边界已经被 characterization tests 固定；
2. Roadmap exit criteria 已落文档；
3. 最小 helper extraction 已完成，且测试结果与抽取前保持一致；
4. 已没有继续降低复杂度的高收益、小风险切点。

若下一步收益不清晰、风险变大、需要跨模块大改，必须停步 Ask User。不要为了
"更完美"继续抽象；不要进入新功能；不要做 TUI 改造；不要做 checkpoint gateway
planning；不要进入 Memory / sub-agent / Skill；不要重开历史 XFAIL；不要
push 或 tag，除非用户单独选择对应动作。

---

### Stage 2.5 · Tooling Foundation Milestone ✅**release + dogfooding closure complete**

**主题**：先把本地工具体系的边界审计清楚，再考虑 MCP Client / Tool Bridge。

学习型边界说明：
- 工具体系是本地 Agent 的行动能力基础；如果 tool registry、tool schema、
  tool executor、tool result、approval、logging、checkpoint、runtime 边界不清楚，
  后续 MCP 会把这些模块搅在一起。
- MCP 是外部 tools / context / capabilities 的标准接入协议；它应该作为工具体系的
  外部协议扩展，而不是直接塞进 `core.py` 或让 `tool_executor.py` 变成新巨石。
- Memory / Skill / Hook 都应建立在清晰的工具体系与 runtime 边界之上。

#### A. Tool Module Architecture Audit（下一步）

**目标**：
- 只读审计当前工具模块；
- 梳理 tool registry / tool schema / tool executor / tool result / tool error /
  approval / logging / checkpoint / runtime 边界；
- 识别 `tool_executor` 是否过重；
- 识别 `core.py` 是否知道太多工具细节；
- 识别工具调用是否绕过 HITL/confirmation；
- 识别工具结果是否有统一 contract；
- 识别工具错误是否有统一 contract；
- 识别工具权限和安全边界缺口；
- 识别为 MCP 接入需要预留的 seam。

**非目标**：
- 不实现 MCP；
- 不新增真实外部工具；
- 不新增权限系统；
- 不新增 hook；
- 不新增重依赖；
- 不改 checkpoint 格式；
- 不改 TUI/display contract。

#### B. MCP Client / Tool Bridge Discovery（工具审计之后）

**目标**：
- 研究如何把外部 MCP server 暴露的 tools 映射成本地 tool registry；
- 研究 MCP tool schema 如何适配本地 tool schema；
- 研究 MCP tool result 如何适配本地 tool result contract；
- 研究 MCP 工具调用如何复用本地 HITL/confirmation；
- 研究 MCP 工具错误如何纳入本地错误 contract；
- 研究 MCP client 边界，不把 MCP 逻辑塞进 `core.py` 或 `tool_executor.py`；
- 研究安全边界和用户批准边界。

**非目标**：
- 不直接实现完整 MCP；
- 不做 MCP server；
- 不联网；
- 不接真实私有数据源；
- 不绕过本地工具审批；
- 不做权限系统大改。

#### C. Tooling Foundation implementation checkpoint（MCP 前基础已收口）

**已形成的本地工具体系基础**：
- base registry 已收窄：Skill lifecycle 的 `install_skill` / `load_skill` /
  `update_skill` 不进入当前基础工具集，低价值窄工具 `calculate` 已移除；
- registry 提供内部 ToolSpec 投影：`get_tool_specs()` 暴露 capability /
  risk_level / output_policy / confirmation metadata，但这些治理字段不进入
  model-visible tool schema；
- `tool_registry.execute_tool()` 的外部签名保持不变，但内部已拆成 pre-hook /
  dispatch / post-hook / normalization helpers；confirmation / runtime /
  checkpoint 语义仍不进入 registry；
- FileMutation path safety 已共享：`write_file` 与 `edit_file` 复用 project-root
  helper，`edit_file` 不再能绕过项目根目录边界；`read_file` 仍保持项目外确认语义；
- ToolResult 分类已从 executor 收口到 `tool_result_contract` seam；当前仍是
  legacy string prefix contract，尚未迁移为结构化 ToolResult；
- shell / file / output policy / responsibility boundaries 已有
  characterization tests，保护 MCP 之前的本地工具边界。

**后续 cleanup / milestone 候选（不阻塞本阶段 closure）**：
- `tool_registry.execute_tool()` 仍作为兼容入口存在；是否进一步把 registry
  收敛为纯注册/查询层，应在独立 tool-system cleanup slice 中单独决策；
- `tool_executor.py` 仍负责 pending/checkpoint/log/display 编排，后续只能按
  小 slice 收口，不能大拆；
- ToolResult 仍是 legacy string/prefix contract，没有做结构化迁移；
- 当前 MCP 只完成 client architecture seam + local stdio fixture validation；MCP CLI
  Config Management、外部/reference server validation、resources/prompts/sampling/
  roots 都是后续 milestone，不是本阶段 blocker。

**高内聚 / 低耦合完成标准**：
- tool registry 不做执行；
- tool executor 不做业务决策；
- `core.py` 不知道具体工具细节；
- confirmation handlers 继续处理用户确认语义；
- MCP adapter 不污染本地 tool contract；
- tests 保护工具 contract 和架构边界，而不仅是表面行为。

#### D. MCP Readiness / Minimal Client Architecture + Local Stdio Validation Pack

**已形成的 architecture seam**：
- `MCPServerConfig`：只保存显式配置；配置是 source of truth，未来 CLI 只能管理配置；
- `MCPToolDescriptor`：描述外部 server 暴露的 tool schema，但不等于本地 registry entry；
- `MCPCallResult`：把 fake / stdio MCP client 结果映射回现有 legacy ToolResult string contract；
- `MCPClient` protocol + `FakeMCPClient`：只提供 list_tools / call_tool seam，供测试验证架构；
- explicit opt-in registry adapter：只有 enabled server 经显式调用才会注册 `mcp__server__tool`
  名称；MCP tools 不进入 base/default registry，且默认 `confirmation="always"`。

**已完成的低风险真实验证**：
- `StdioMCPClient`：启动显式配置的本地命令，通过 stdio 发送最小 JSON-RPC request；
- `tests/fixtures/minimal_mcp_stdio_server.py`：本地 test server，只提供
  initialize / tools/list / tools/call，不读取文件、不联网、不访问 secret；
- 端到端测试覆盖 config -> stdio client -> list_tools -> registry opt-in ->
  execute_tool -> legacy ToolResult mapping -> confirmation boundary。

**明确未实现**：
- 未连接外部 / reference MCP server；
- 未声明完整 MCP spec 兼容或 SDK 替代；
- 未实现 HTTP / SSE / Streamable HTTP transport；
- 未支持 resources / prompts / sampling / roots；
- 未读取 `.env` 或真实 secrets；
- 未把 ToolResult 半路迁移成结构化对象；
- 未把 MCP 逻辑塞进 `core.py` / `tool_executor.py` / checkpoint / TUI。

**release / dogfooding closure 状态**：
- `v0.7.0` 已 tag + push，覆盖 Tooling Foundation / MCP readiness milestone；
- post-release verification 已确认本地与 remote release 状态一致；
- self-dogfooding 第一轮与第二轮已完成，未发现 P0/P1/P2；
- 唯一 P3 是多步 always-confirm 工具可能显得确认频率偏高；当前不改
  confirmation policy，只用 dogfooding smoke test 保护"确认多次也不重复执行、
  不漏 tool_result"的安全语义。

**后续顺序**：
1. 人工 review / push 当前 post-release dogfooding closure docs/tests commit；
2. 真实使用一段时间，记录自动化 smoke 无法覆盖的 TUI/UX 问题；
3. 再单独选择 Memory System Discovery、MCP CLI Config Management、外部/reference
   MCP server validation，或 Runtime/Checkpoint/TUI targeted hardening。任何真实
   server / secret / networking 都需要单独授权。

---

### Stage 3 · Memory system

**主题**：跨会话语义沉淀（与 Stage 1 的 checkpoint 是不同关注点）。

**当前已从 Discovery / Architecture Planning 进入最小 contract-first implementation slices。**
仍不做 persistence / retrieval / RAG / vector DB / real provider。

#### Stage 3 kickoff · Memory Discovery readiness（post-tools 第一组工作）

**为什么现在进入这里**：
- Stage 2.5 Tooling Foundation / MCP readiness 已 release 并完成 dogfooding closure；
- 当前没有 P0/P1/P2 要求继续 Runtime/Checkpoint/TUI hardening；
- MCP CLI Config Management 是可选后续 thin adapter，不是 canonical stage；
- Roadmap 的下一条主干是 Memory，但只能先做 Discovery / Architecture Planning。

**第一组允许工作**：
- 梳理 memory vs checkpoint vs session summary vs skill/hook 的边界；
- 用 boundary tests 钉住 `agent.memory` 不反向 import `core` / checkpoint /
  input backend / MCP / tool executor；
- 用 acceptance tests 钉住当前 `build_memory_section()` 仍是静态占位，不读取
  `memory/` 数据文件、不读取 `.env`、不接真实 provider；
- 把 Memory Discovery 问题清单保持在 Roadmap 中，作为后续设计 review 的入口。

**第一组禁止工作**：
- 不实现 long-term memory；
- 不读取或迁移 `memory/` 目录里的历史数据；
- 不引入 embedding / vector DB / RAG dependency；
- 不把 checkpoint schema 塞进 Memory；
- 不让 input backend / TUI / MCP CLI 决定 memory retain/recall；
- 不自动记录用户事实、偏好或项目知识。

**完成定义（readiness）**：
- Roadmap 明确 Memory Discovery 的目标、非目标、停止条件；
- tests 保护 Memory discovery 边界：不读真实 memory artifacts、不依赖 runtime
  hot path、不伪装成已实现完整 Memory System；
- contract-first slices 已启动：MemoryCandidate / MemoryDecision、
  deterministic MemoryPolicy、MemorySnapshot prompt injection seam；
- 后续进入 retain/update/forget implementation 前，必须先有 human approval
  UX contract。

#### Stage 3 Memory System Research & Architecture Discovery

**本轮 research / architecture 产物**：
- `docs/MEMORY_RESEARCH.md`：记录 MemGPT / Letta、LangGraph、MCP
  resources/prompts/tools、external memory provider/store 模式的公开资料调研与
  架构取舍；
- `docs/MEMORY_ARCHITECTURE.md`：提出 First Agent 适用的 Memory System 架构：
  MemoryCandidate -> MemoryPolicy / MemoryDecision -> MemoryApproval ->
  MemoryStore / MemoryProvider -> MemoryRetrieval -> MemorySnapshot ->
  PromptBuilder injection -> MemoryAudit；
- `tests/test_memory_research_architecture_docs.py`：用 docs acceptance tests
  防止后续把 Stage 3 误写成 memory.json + prompt injection 或 provider-first
  implementation。

**本轮仍然不做**：
- 不实现 long-term memory persistence；
- 不读取或迁移 `memory/` 目录里的历史数据；
- 不自动 retain / update / forget；
- 不实现 embedding / vector store / RAG；
- 不接 MCP resources/prompts/sampling/roots；
- 不修改 checkpoint 语义、runtime core loop 或 TUI 主流程。

**下一段 implementation 前置条件**：
- `MEMORY_RESEARCH.md` / `MEMORY_ARCHITECTURE.md` 已作为 Discovery pre-slice
  落地；
- Slice 1 MemoryDecision / MemoryCandidate no-side-effect contract 已落地；
- Slice 2 deterministic MemoryPolicy no-op / explicit-only retain 已落地；
- Slice 3 MemorySnapshot prompt injection seam 已落地：prompt_builder 只消费
  approved snapshot view，不做 retrieval/store/policy；
- Slice 4 retain/update/forget user confirmation UX contract 已落地：
  `memory_confirmation` 只生成用户确认 request/result，不写 store、不改 runtime；
- Slice 5 forget/update safety 与 audit summary contract 已落地：
  `memory_operations` 只生成 operation intent / audit summary，不写 store、不真实
  update/forget；
- Slice 6 External MemoryProvider adapter seam / future MCP resources integration
  已落地：`memory_provider` 只提供 fake/provider protocol，把 deterministic
  fixture 投影为 MemoryCandidate / MemorySnapshot 输入，不接真实 provider/MCP；
- Slice 7 Memory UX dogfooding scenarios / docs / release readiness 已落地：
  使用 deterministic tests + `docs/MEMORY_DOGFOODING.md` checklist，不读取真实
  sessions/runs/logs、不写真实 memory；
- Memory-line Stage 4 safe local MemoryStore skeleton 已落地：`memory_store`
  只接收已确认、已审计的 `MemoryOperationIntent` / `MemoryAuditSummary`，只写
  fake/in-memory record，不接 runtime/checkpoint/prompt_builder，不实现真实
  persistence / retrieval / recall；
- Memory-line Stage 5 governed snapshot generation 已落地：
  `memory_snapshot_generator` 只把 fake/local `MemoryRecord` 过滤成
  `MemorySnapshot`，负责 deterministic ordering、scope/budget/safety/provenance
  过滤，不接 prompt_builder、runtime、provider、MCP，也不实现语义检索；
- Memory-line Stage 6 manual UX dogfooding runbook 已落地：
  `docs/MEMORY_DOGFOODING.md` 覆盖 accept/edit/reject/use_once/forget/update、
  audit summary、sensitive handling、fake store 到 governed snapshot、prompt_builder
  boundary；只使用 fake/local deterministic data；
- 任何真实 persistence / provider / external resource 接入都必须另行授权。

学习型边界说明：
- Memory 是 Agent Runtime 的长期语义层，回答“哪些稳定事实、偏好、项目知识、
  历史决策、可复用流程应在未来会话中被召回”。
- Memory **不是 checkpoint**：checkpoint 保存 runtime crash/resume 状态；
  Memory 保存跨会话语义，不承担恢复 pending tool / pending confirmation。
- Memory **不是 Skill / Hook**：Skill 是可调用能力或知识包，Hook 是生命周期扩展点；
  Memory 是可保留、召回、更新、遗忘的语义记录。
- Memory **不是 RAG 本身**：Retrieval / RAG / vector DB / embedding 只能作为
  后续 provider backend 或 recall strategy 候选，不能作为与 Memory 并列的下一阶段能力。

**Discovery 必须先回答的问题**：
- What should be remembered?
- Who decides what enters memory?
- What is short-term vs long-term memory?
- What is project memory vs user memory?
- What is semantic vs episodic vs procedural memory?
- What is curated vs auto-generated memory?
- What is session summary vs checkpoint?
- What is memory provider seam?
- What is recall interface?
- What is retain/update/forget interface?
- What should remain local-only?
- What must require human approval?
- What should never be remembered?
- How do we avoid RAG-first architecture?
- How do we avoid memory becoming a new monolith?

**Memory type taxonomy（Discovery 起点，不代表立即实现）**：
- semantic memory：用户事实、项目事实、长期偏好；
- episodic memory：历史任务、重要决策、执行经验；
- procedural memory：可复用规则、操作流程、项目约束；
- curated memory：人工确认过的稳定记忆；
- session summary：会话摘要，短期压缩上下文，不等同 long-term memory；
- project memory：项目级上下文，与 repo/workspace 绑定。

**Provider seam 初步方向（后续 discovery，不实现）**：
- 内置 Memory System 应先有清晰的本地数据模型与 lifecycle；
- 同时预留 Memory Provider seam，使外部记忆系统可以作为 provider 接入；
- provider 不可用时必须有 local-first fallback，不影响核心 Agent Loop；
- provider seam 不能让 Memory 反向污染 checkpoint、core.py、input backend 或 Skill；
- Retrieval / RAG / vector DB / embedding 只能是 provider backend/recall strategy 的后续候选，
  当前不得直接引入 embedding、vector DB 或重依赖。

**Lifecycle / scope 设计问题（后续 discovery）**：
- retain / recall / update / forget 的调用入口与审批边界；
- user / project / session / repo scope 的隔离规则；
- 哪些内容必须 human approval 后才能进入 long-term memory；
- 哪些内容只能成为 session summary，不能进入 long-term memory；
- privacy / local-first / no sensitive read 的默认策略；
- memory 注入 prompt 的边界必须经 prompt_builder 或后续明确 seam，不得散落在 runtime。

**毕业标准（待 discovery 后细化）**：
- memory problem statement：解决什么、不解决什么；
- memory vs session messages / checkpoint / skills / hooks 的边界图；
- memory record/schema 初稿；
- memory lifecycle policy：retain / recall / update / forget；
- memory scope policy：user / project / session / repo；
- provider seam design；
- provider unavailable fallback；
- privacy / local-first / human approval rules；
- memory safety tests：注入不污染 runtime、不绕过 permission、不读取敏感资料；
- anti-monolith tests：Memory 不反向依赖 input backend / core 巨石 / checkpoint schema。

**已完成公开调研（research note，不代表 implementation 完成）**：
- MemGPT / Letta：virtual context、memory tiers、memory blocks、stateful agents；
- LangGraph：short-term thread state、long-term namespaced store、semantic /
  episodic / procedural memory；
- MCP resources / prompts / tools：external context / workflow / tool provider
  边界，不能等同于内部 MemoryPolicy；
- 常见 external memory provider/store：local JSON / SQLite / namespaced KV /
  event log / document store / vector store / hybrid retrieval；
- 详见 `docs/MEMORY_RESEARCH.md` 与 `docs/MEMORY_ARCHITECTURE.md`。

**口径硬约束**：
- **Memory Discovery 在 Tooling Foundation Milestone / MCP Tool Bridge Discovery 之后启动**；
- **Memory 优先于 sub-agent / Skill 正式化**；
- **先 Discovery / Architecture Planning，后 implementation**；
- **不直接做 RAG / retrieval / embedding / vector DB**；
- **不新增重依赖**；
- **不让 Memory 变成新巨石**；
- **不允许 agent 自动乱写长期记忆**，进入 long-term memory 的内容必须有明确 retain 规则，
  敏感或稳定偏好类信息必须经过 human approval。

**现状**：`memory/` 目录已有 profile.json / episodes / rules / checkpoint.json 数据文件，
**但未见对应注入/审批/遗忘代码**。这些只能作为历史 artifact / discovery 线索，
不代表 Stage 3 已实现。

---

### Stage 4 · Sub-agent / Handoff

**主题**：在 Stage 3 Memory 收口后，引入特化子 Agent。

**毕业标准**：
- sub-agent registry（注册表）
- sub-agent definition（定义 schema）
- **agent-as-tool first**（先把子 Agent 当工具调用）
- handoff later（任务交接是更晚的事）
- input/output schema（结构化）
- result merge（合并到主 Agent context）
- **main agent keeps final control**（主 Agent 始终是决策者）
- sub-agent **不能绕过** runtime / permission / checkpoint
- tests

**口径硬约束**：
- **不要一开始做复杂 autonomous multi-agent**
- **先做 main agent calls specialist as tool**
- **Stage 3 未收口前不启动 Stage 4 实质实现**

**Safe Local MVP completion（Roadmap Completion Autopilot）**：
- 已新增 `agent.subagents.local`：只支持 fake/local profile 与
  parent-controlled `DelegationRequest` / `DelegationResult`。
- 已新增 `tests/fixtures/subagents/code-reviewer/SUBAGENT.md` 和
  `tests/test_subagent_local_mvp_contract.py`。
- 已新增 `docs/SUBAGENT_LOCAL_MVP.md` 与 `docs/CAPABILITY_BOUNDARIES.md`。
- `docs/SUBAGENT_LOCAL_MVP.md` 记录 fake dogfood example：只构造 profile /
  delegation request/result，不启动 child agent。
- 仍不做真实 LLM delegation、外部进程、remote delegation、handoff 或 child tool
  execution。

---

### Stage 5 · Skill system

**主题**：把 Stage 0 的 skill 原型正式化。

**毕业标准**：
- skills directory（已有 `agent/skills/`）
- SKILL.md（每个 skill 的契约）
- skill discovery（发现机制）
- skill activation（激活语义）
- progressive disclosure（按需暴露能力）
- skill-specific instructions（per-skill prompt）
- **skill / tool 边界**（skill 是高层组合，tool 是原子能力）
- tests

**口径硬约束**：
- **Skill 较轻**，不是当前最难主线
- **Skill 可以在 Memory/sub-agent 后做**，或作为轻量能力穿插（即可在 Stage 3/4
  期间补少量必要的 skill/SKILL.md 标准化，但不做 installer/safety 重做）

**现状**：`agent/skills/{installer,loader,parser,registry,safety}.py` 已存在但是
**原型**；evil-skill 测试目录暴露 safety 仍在原型期 → Stage 5 主战场。

**Safe Local MVP completion（Roadmap Completion Autopilot）**：
- 已新增 `agent.skills.local`：只支持显式 tmp_path / `tests/fixtures/skills` 的
  local capability descriptor。
- 已新增 `tests/fixtures/skills/safe-writer/SKILL.md` 和
  `tests/test_skill_local_mvp_contract.py`。
- 已新增 `docs/SKILL_LOCAL_MVP.md` 与 `docs/CAPABILITY_BOUNDARIES.md`。
- `docs/SKILL_LOCAL_MVP.md` 记录 fake dogfood example：只加载 descriptor /
  redacted display，不执行 skill 或 allowed tools。
- 仍不做真实 Skill install / execution、远程 marketplace、任意代码执行、真实 skill
  目录读取或 tool policy bypass。

---

### Stage 6 · Observability foundation

**主题**：在 Stage 1-5 中**持续打底**，最终形成可本地查询的 trace。

**毕业标准**：
- event log schema（已开始：`agent/runtime_events.py` + observer evidence events）
- run id / trace id / step id
- model call span
- tool call span
- state transition span
- checkpoint span
- memory update span（待 Stage 3）
- sub-agent span（待 Stage 4）
- **local-only trace file**
- **no dashboard yet**

**口径硬约束**：
- observability 底子要**持续打**（v0.5 已开始：observer signature guard、
  confirmation evidence、terminal diagnostics → runtime events）
- **dashboard / panel 是后期**，不是当前

**Local Trace Foundation completion（Roadmap Completion Autopilot）**：
- 已新增 `agent.local_trace`：定义 `TraceEvent` 与 `LocalTraceRecorder`。
- 已新增 `docs/LOCAL_TRACE_FOUNDATION.md`：记录 local-only trace schema 与 deferred
  runtime wiring 边界。
- 支持 local-only trace file JSONL、run_id、trace_id、span_id、parent_span_id、
  step_id、model_call / tool_call / state_transition / checkpoint / memory_update /
  subagent span 类型。
- recorder 只写显式 tmp_path，拒绝 `agent_log.jsonl` / `sessions` / `runs` 等
  真实 runtime artifact 路径。
- metadata 在输出边界脱敏，不展开 env secret；测试覆盖 token/api_key redaction。
- 当前不把 recorder 反向接入 core.py；后续 runtime wiring 只能以小 slice 追加。

---

### Stage 7 · Tool system optimization

**主题**：靠后的 tool 工程化。

**毕业标准**：
- tool registry（已有最小版）
- tool schema cleanup
- permission policy（v0.2 已有 policy denial / unknown tool 分类 / workspace write block 最小集）
- structured tool result
- tool result truncation（长输出截断）
- tool error taxonomy（结构化错误）
- observation formatting
- existing tool cleanup（12 个现有工具的接口规范）
- tests（每个 tool 的单元测试）

**口径硬约束**：
- **靠后**，**除非**阻塞前面阶段
- 当前最小集（policy denial 等）已够 Stage 0-2 用，不必提前

**Structured ToolResult Envelope Foundation completion（Roadmap Completion Autopilot）**：
- 已在 `agent.tool_result_contract` 新增 `ToolResultEnvelope` 与
  `classify_tool_result`。
- 已新增 `docs/TOOL_RESULT_ENVELOPE.md`：记录 legacy compatibility、error taxonomy
  与 executor migration deferred 边界。
- 结构化字段覆盖 status、display_event_type、status_text、error_type、
  safe_preview、content_length 与 preview_truncated。
- `classify_tool_outcome` 继续保留 tuple API，保证 legacy string contract 仍兼容
  现有 `tool_executor` / Anthropic `tool_result.content` 路径。
- 当前不迁移所有工具函数返回值，不改 checkpoint/messages 协议，不把 executor 大拆。

---

### Stage 8 · Customization / local productization

**主题**：本地工具产品化收尾。

**毕业标准**：
- local config（用户/项目两级）
- project profile
- user preferences
- model provider config
- safety policy
- per-project behavior
- module toggles（Stage 3-7 各能力可独立开关）
- install / setup path（一键安装）

**口径硬约束**：
- 这是**本地工具产品化**，**不是** SaaS / Web UI

**Local Config Foundation completion（Roadmap Completion Autopilot）**：
- 已新增 `agent.local_config`：只读取显式 tmp_path fake/local JSON config。
- 已新增 `tests/fixtures/local_config/agent.local.json` 与
  `docs/LOCAL_CONFIG_FOUNDATION.md`，提供不含 secret 的 explicit safe fixture path。
- 数据模型覆盖 `ProjectProfile`、`SafetyPolicy`、`ModuleToggles`、
  `ModelProviderConfig`。
- 默认 fail-closed：network / real MCP / real home writes / modules 全部默认关闭。
- provider config 只保留 env var 名称与脱敏 marker，不读取 `.env`，不展开 env
  secret，不输出真实 token。
- 拒绝 `~` home config、`.env`、`agent_log.jsonl`、`sessions`、`runs` 路径。
- 当前不做 install/setup 写入、不做真实用户目录配置、不改 runtime 启动配置。

---

## Explicit Non-goals

- ❌ Web UI
- ❌ SaaS
- ❌ 多用户平台
- ❌ 云端 agent 服务
- ❌ 复杂插件市场
- ❌ model extension / plugin framework 作为主线
- ❌ dashboard（至少当前不做）
- ❌ RAG / vector DB（**除非未来 Memory/Search 专项明确需要**）
- ❌ 为写文档而写文档
- ❌ 因为 xfail 存在就乱解
- ❌ 为了 UI 好看污染 runtime core
- ❌ **不再使用 TOI 这个词**

---

## Anti-drift Rules

后续每一轮工作必须遵守：

- 每一轮先说**当前 stage**（Stage 0-8 哪一个）
- 每一轮先说 **action type**（planning / coding / audit / docs / release）
- 每一轮必须说明**为什么是 Roadmap 下一步**（指向具体 Stage 毕业标准的某一条）
- **docs 只能服务于 gate**，不能变成默认动作；**docs-only 连续 ≥ 2 commit 后
  必须切换到非 docs**（避免 doc drift / planning inflation）
- coding 必须有 **tests 或 characterization tests** 保护
- release / tag 必须在 audit PASS 后；**tag 必须用户明确授权**
- **xfail 必须先 inventory 再处理**，不顺手解
- **TUI 不能污染 runtime core**（AST baseline 持续守护，见 v0.6.1 Group A/E）
- **Memory ≠ checkpoint**
- **sub-agent 不能绕过 main runtime**
- **Skill 不提前做重**
- **Tool optimization 不提前**
- **Web UI 永不进入路线**，除非用户未来明确改方向
- **不再使用 TOI 这个词**

---

## Historical Near-term Execution Plan

This section is historical execution evidence, not an active menu. Current
safe-local closure status is recorded in `docs/ROADMAP_COMPLETION_AUTOPILOT.md`,
`docs/SAFE_LOCAL_RELEASE_READINESS.md`, and
`docs/DEFERRED_ROADMAP_BOUNDARIES.md`.

HITL/Input Roadmap 已阶段性收口。Memory System Discovery Roadmap Correction
已完成，但 Memory 不是立刻下一步。下一阶段先进入 **Tooling Foundation
Milestone**：先做 Tool Module Architecture Audit，再做 MCP Client / Tool
Bridge Discovery；之后才进入 Memory System Discovery。

接下来最小 slice，按顺序执行（每个 slice 单独 commit + 单独 audit）：

| # | Slice | Stage | Action type | Expected output | Quality gate | Stop condition |
|---|---|---|---|---|---|---|
| 1 | **HITL/Input Roadmap Closure** | Stage 2 | done | User Input Resolution Contract + input backend confirmation boundary safety net 已完成 | 已 push；不继续扩大 HITL | closed |
| 2 | **Memory System Discovery Roadmap Correction** | Stage 3 | done | Memory 被定义为独立逻辑模块；RAG 降级为 provider/backend 候选 | 已 push；未实现 Memory/RAG | closed |
| 3 | **Tool Module Architecture Audit + Foundation boundary contracts** | Stage 2.5 | done | registry/schema/result/output/responsibility boundaries 已有测试与最小 seams | 已完成；未实现真实 MCP transport | closed |
| 4 | **MCP-before cleanup pack** | Stage 2.5 | done | split `execute_tool` 内部职责、修复 `edit_file` project-root parity、移出默认 `install_skill` | 已 commit；不实现真实 MCP transport | closed |
| 5 | **MCP Readiness / Minimal Client Architecture Pack** | Stage 2.5 | done | 本地 MCP config/client/descriptor/fake-client/explicit registry opt-in seam | 已 commit；不接真实 server；不联网；不新增依赖 | closed |
| 6 | **MCP Real Integration Validation Pack** | Stage 2.5 | done | 最小本地 stdio transport + local fixture server 端到端验证 | 不接外部 server；不读 secret；不新增依赖；full pytest + ruff | closed |
| 7 | **MCP 前 final review** | Stage 2.5 | done | 审计本地 ToolSpec / ToolResult / safety / confirmation / executor / MCP seam 是否可阶段性收口 | 不联网；不接外部 MCP server；不新增依赖 | closed |
| 8 | **MCP Client / Tool Bridge Discovery** | Stage 2.5 | archived discovery | 研究外部/reference MCP server 如何映射到本地 tool registry/schema/result/error/approval contract | 不接真实私有数据源；不新增依赖；真实 server 需单独授权 | deferred boundary doc |
| 9 | **Memory System Discovery inventory** | Stage 3 | done | 工具体系边界清楚后，再只读梳理 memory problem space / provider seam / checkpoint/session 边界 | 不改文件；不联网；不实现 Memory | closed |
| 10 | **Skill System Discovery** | Stage 5 | superseded by Safe Local MVP | 在 Tool + Memory 边界稳定后，定义 Skill = Prompt + 工具 + 参考资料 + 操作流程的组合边界 | 不实现真实 Skill activation | safe local MVP complete |
| 11 | **Hook / Lifecycle Event Discovery** | later | deferred | 研究 lifecycle event seam，避免 hooks 绕过 runtime/permission/checkpoint | 不实现 Hook | deferred boundary doc |
| 12 | **Z / Advanced Knowledge Access** | later | deferred | 最后再讨论高级知识访问；RAG/retrieval/vector DB 只能作为 provider/backend 候选 | 不做 RAG/embedding/vector DB | deferred boundary doc |

**严禁打包**：不要把 Discovery、Planning、Tests、Implementation 混进同一个 commit。

**RAG 口径**：RAG / retrieval / vector DB / embedding 不是与 Memory / Skill /
Hook / Tooling Foundation 并列的 Roadmap 大能力；它们只能作为后续 Memory
Provider、Knowledge Access Provider 或 tool-backed retrieval 的实现候选。
当前不得直接上 RAG、embedding、vector DB 或新增重依赖。

---

## 历史毕业证据 / 版本映射

> 以下章节是**历史毕业证据**与**旧版本号 → 新 Stage 映射**，**不**作为后续执行的
> 真值源。新工作以前文 8 阶段毕业标准为准。

### 版本与 Stage 对应关系

| 旧版本号 | 主要归属 Stage | 历史详细文档 |
|---|---|---|
| v0.1（无 tag） | Stage 0 | `docs/V0_1_GRADUATION_REPORT.md` / `docs/V0_1_CONTRACT.md` |
| v0.2.0 (`a32facc`) | Stage 1 + Stage 7 最小集 | `RELEASE_NOTES_v0.2.md` / `docs/V0_2_PLANNING.md` / `docs/V0_2_BASIC_TUI_PLAN.md`（Stage 2 历史) |
| v0.3.0 / v0.3.1 | Stage 1 + Stage 6 readability | `RELEASE_NOTES_v0.3.md` / `docs/V0_3_PLANNING.md` |
| v0.4.0 (`6417606`) | Stage 1 transition + checkpoint guard | `RELEASE_NOTES_v0.4.md` / `docs/V0_4_PLANNING.md` |
| v0.5.0 (`32d4ca1`) | Stage 1 observer evidence | `RELEASE_NOTES_v0.5.md` / `docs/V0_5_OBSERVER_AUDIT.md` |
| v0.5.1 (`240308b` / annotated `ce65bdca`) | Stage 1 dispatch helper + resume bridge | `RELEASE_NOTES_v0.5.1.md` / `docs/audits/v0.5.1_checkpoint_resume_audit.md` |
| v0.6.0 (`22b390c`，docs-only) | Stage 2 scope alignment | `docs/audits/v0.6_tui_scope_gap_audit.md` |
| v0.6.1 (未 tag) | Stage 2 boundary safety net | tests `tests/test_tui_dependency_boundaries.py` + `tests/test_input_backend_user_contract.py` + `tests/test_display_event_contract.py` |

### 旧 v0.1 毕业标准（已全部 ✅，保留作为 Stage 0 历史）

> v0.1 5 条毕业标准与 B1/B2/B3 blocking 的详细历史细节，移至
> `docs/V0_1_GRADUATION_REPORT.md` 与 `docs/V0_1_CONTRACT.md`。
>
> v0.1 阶段已**冻结**：新功能必须先归类到 Stage 1-8 backlog。

### 旧 v0.2/v0.3/v1.0 backlog → 新 Stage 归类

| 旧 backlog 项 | 新 Stage |
|---|---|
| Runtime 状态机整理 / 转移图 / 不变量 spec | Stage 1（已大部分落地，spec 文档化是 Stage 1 残留） |
| InputIntent / RuntimeEvent / DisplayEvent 边界治理 | Stage 1（v0.5.1 已大部分钉死）+ Stage 2（display event contract，v0.6.1 已钉） |
| 工具体系优化（接口/压缩/选择质量/单测/文档） | Stage 7 |
| checkpoint 恢复语义（中断态 / 损坏自愈 / 跨版本） | Stage 1 残留 |
| 错误恢复 / 重试 / loop guard / no_progress | Stage 1 残留 |
| 基础安全权限（path 白名单 / shell 黑名单 / workspace 约束） | Stage 7 最小集（v0.2 已落） |
| generation cancel_token / 流中断生命周期 | Stage 1 已有最小 TUI projection cancel；真实 provider abort 后续单独做 |
| 复杂 topic switch（feedback_intent 之上） | Stage 1 + Stage 2 已通过显式三选一闭合 |
| Textual backend 完整实现 / persistent shell | Stage 2 |
| 基础状态面板 / RuntimeEvent 友好渲染 / 确认流 UI | Stage 2 |
| 高级 TUI（多面板 / 快捷键 / Esc cancel / paste burst / timeline） | Stage 2 |
| Skill 子系统正式化 / loader / safety / registry | Stage 5 |
| Observer / eval pipeline / cost 追踪 / 性能基准 | Stage 6 |
| Sub-agent / 多 Agent 协作 | Stage 4 |
| 长期记忆 / 用户偏好自学习 | Stage 3 |
| 插件化 / 公开 API | （**不做** — 见 Non-goals） |
| 多模型路由 / MCP 集成 | Stage 8 customization 子集（仅本地配置层面） |
| 正式安全围栏 / 沙箱 | Stage 7 + Stage 8 |
| 性能 SLA / 稳定性 SLA | Stage 8 后期 |

### 22-block legacy 结构

完整旧 22-block 文档保留在 `docs/ROADMAP_LEGACY.md`，仅作历史参考。

### 进行中工作的版本归属

| 进行中工作 | 旧归属 | 新 Stage 归属 |
|---|---|---|
| awaiting_feedback_intent 两步分流 | v0.2 输入语义 | Stage 1 + Stage 2 已闭合（hardcore 回归测试转 PASS） |
| Textual backend / persistent shell | v0.2/v0.3 拆分 | Stage 2 |
| Skill 子系统 / install_skill / update_skill | v0.3 | Stage 5 |
| runtime_observer / observability 事件 | v0.3 | Stage 6（持续打底） |
| security.py / safety.py | v0.2 + v1.0 | Stage 7 + Stage 8 |
| hardcore_round2 LLM 意图分类讨论 | v1.0 探索 | **不做主线**（Non-goals） |
| generation cancel_token / Textual Esc | v0.2 + v0.3 | Stage 2 已闭合最小 TUI projection cancel；真实 provider abort 后续单独立项 |

---

## 这份文档怎么用

1. **每次开新工作前**：先看 TL;DR — 当前是 Stage 几？这个工作属于当前 Stage 吗？
2. **想做点什么**前：先问"这是当前 Stage 毕业标准的哪一条"。答不出 → **推迟**。
3. **想加新能力**前：先看 **Explicit Non-goals**。在里面 → **拒绝**。
4. **当前 Stage 毕业标准全 ✅** → 写一笔 audit/commit 标记冻结，再启动下一 Stage。
5. **每一轮**：先报**当前 Stage** + **action type** + **为什么是 Roadmap 下一步**。
6. **doc drift 防御**：连续 docs-only commit ≥ 2 后，下一 slice 默认必须是
   audit / coding / tests，docs-only 需特别授权。
