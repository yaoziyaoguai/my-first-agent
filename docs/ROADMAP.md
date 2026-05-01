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
| **2** | **TUI interaction layer**（**当前阶段**） | 🟡 boundary safety net 已立，MVP 未做 | v0.6.x |
| **3** | Memory system | ⏳ 未启动 | 后续 |
| **4** | Sub-agent / Handoff | ⏳ 未启动 | 后续 |
| **5** | Skill system | ⏳ 仅原型，**未正式化** | 后续（可轻量穿插） |
| **6** | Observability foundation | 🟡 持续打底（v0.5 已开始） | 跨阶段 |
| **7** | Tool system optimization | 🟡 仅最小集（v0.2 policy） | 靠后 |
| **8** | Customization / local productization | ⏳ 未启动 | 后期 |

**全局停止规则**：
- 任何"我觉得这块该做"的改动，先回答："这属于哪个 Stage 的毕业标准？"
- 答不出 → **推迟到对应 Stage backlog**，不在当前 Stage 做。
- **当前 Stage 2 未收口前，禁止启动 Stage 3/4/5 的实质实现**（Stage 6/7 可作必要补丁）。

---

## Current Position

> **当前处于 Stage 2: TUI interaction layer (v0.6.x)。**

- ✅ HEAD `bdf0b9f` 与 `origin/main` 同步（ahead/behind 0/0）
- ✅ v0.5.1 已 tag（annotated `ce65bdca` → commit `240308b`）；v0.5.0 → `32d4ca1` 不变
- ✅ v0.6.1 已实现并 push（commits `afd82f5` + `11826cd` + `08bfbe7` + `bdf0b9f`）
- 🟡 **v0.6.1 未 tag / 未 release**
- ✅ v0.6.1 完成 **Group A/E**（dependency boundary 7 tests）+ **Group C**（input contract 7 tests）+ **Group D**（display event contract 5 tests）= **19 characterization tests**
- 🟡 **当前仍有 3 xfailed**：
  1. `tests/test_hardcore_round2.py::test_user_switches_topic_mid_task` — Stage 1/2 输入语义
  2. `tests/test_input_backends_textual.py::test_textual_shell_escape_can_cancel_running_generation` — Stage 1 cancel + Stage 2 TUI Esc
  3. `tests/test_real_cli_regressions.py::test_plain_cli_pasted_numbered_multiline_should_be_one_user_intent` — Stage 2 paste burst
- ❌ **当前还没有正式 TUI MVP**
- ❌ 当前还没进入 Stage 3 Memory
- ❌ 当前还没进入 Stage 4 sub-agent
- ❌ 当前还没进入 Stage 5 Skill 正式化

> pytest 基线 **920 passed / 3 xfailed** — *from the v0.6.1 Group D completion
> run; not re-run in this docs-only commit.*

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

### Stage 2 · TUI interaction layer ⭐**当前阶段**

**主题**：在不污染 runtime core 的前提下，把 textual.py / simple.py 从"已可用
但未被测试钉死"演进成"边界硬化 + TUI MVP 子集落地（解 Stage 1/2 历史 xfail）+
收口 release"。

**主要承载**：v0.6.x（v0.6.0 docs audit + v0.6.1 三层 boundary safety net + v0.6.x next）

**毕业标准（必须全部 ✅ 才能宣布 Stage 2 收口、才能进入 Stage 3 Memory）**：

| # | 项 | 当前 | 备注 |
|---|---|---|---|
| 1 | textual / simple input backend 已存在 | ✅ | textual.py 549 + simple.py 129 |
| 2 | Ask User / request user input | 🟡 | 项目模式必须每轮触发；TUI 中 Ask User UI **未明确实现** |
| 3 | Other / free-text 路径 | 🟡 | v0.6.0 audit §5 风险 5 已点名；characterization test **未补** |
| 4 | input backend 不 mutate runtime state | ✅ | v0.6.1 Group A/E + C 已钉 |
| 5 | input backend 不绕过 confirmation handlers | 🟡 | v0.6.0 audit §5 风险 4；characterization test **未补**（计划 v0.6.4） |
| 6 | display event contract | ✅ | v0.6.1 Group D 已钉 |
| 7 | display layer 不做 runtime decision | ✅ | v0.6.1 Group A/E AST baseline |
| 8 | no sensitive read | ✅ | v0.6.1 Group A/E 字面扫描；word-boundary regex 防 `.envelope` 假阳性 |
| 9 | **current 3 xfailed inventory** | ❌ | **未做**（计划 v0.6.x next） |
| 10 | **TUI MVP planning** | ❌ | **未做** |
| 11 | **TUI MVP minimum implementation** | ❌ | **未做** — 目标 = 解 paste burst + Esc cancel + Ask User UI 至少 1 项 |
| 12 | **TUI MVP regression tests** | ❌ | **未做** |

**口径硬约束**：
- **只叫 TUI，不叫 TOI**
- **TUI 不是 Web UI**
- **Stage 2 收口前不进入 Stage 3 Memory**

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
| 9 | XFAIL-1 / XFAIL-2 | 不允许顺手处理，除非后续单独立项 |
| 10 | checkpoint gateway | 不进入 gateway planning，除非 Roadmap 后续明确作为独立阶段 |

**停止条件**：

当以下条件同时满足时，本轮 Architecture Debt 治理应停止：

1. checkpoint ownership 边界已经被 characterization tests 固定；
2. Roadmap exit criteria 已落文档；
3. 最小 helper extraction 已完成，且测试结果与抽取前保持一致；
4. 已没有继续降低复杂度的高收益、小风险切点。

若下一步收益不清晰、风险变大、需要跨模块大改，必须停步 Ask User。不要为了
"更完美"继续抽象；不要进入新功能；不要做 TUI 改造；不要做 checkpoint gateway
planning；不要进入 Memory / sub-agent / Skill；不要处理 XFAIL-1 / XFAIL-2；不要
push 或 tag，除非用户单独选择对应动作。

---

### Stage 3 · Memory system

**主题**：跨会话语义沉淀（与 Stage 1 的 checkpoint 是不同关注点）。

**毕业标准**：
- session summary（每会话结束的摘要）
- project memory（项目级稳定知识）
- user profile memory（用户偏好；现 `memory/profile.json` 仅是数据文件，无 injection 实现）
- memory storage（持久化策略）
- **memory injection boundary**（注入到 prompt 的边界，必须经 prompt_builder）
- memory update policy（什么时候写、谁能写）
- explicit approval / forget（用户可显式删除 / 忘记）
- memory compression（避免无限增长）
- memory safety tests（注入不污染 runtime / 不绕过 permission）
- **memory vs checkpoint vs runtime state 的清晰边界**

**口径硬约束**：
- **Memory 优先于 sub-agent**
- **Memory ≠ checkpoint**：checkpoint 是 runtime state 持久化（崩溃恢复）；
  Memory 是跨会话**语义沉淀**（个性化、项目知识）
- **Stage 2 未收口前不启动 Stage 3 实质实现**

**现状**：`memory/` 目录已有 profile.json / episodes / rules / checkpoint.json 数据文件，
**但未见对应注入/审批/遗忘代码** → 接近从零。

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

## Near-term Execution Plan

接下来 6 个最小 slice，按顺序执行（每个 slice 单独 commit + 单独 audit）：

| # | Slice | Stage | Action type | Expected output | Quality gate | Stop condition |
|---|---|---|---|---|---|---|
| 1 | **Audit this canonical roadmap commit** | meta | audit | docs-only / 单文件 / 无 TOI / 无 Web UI 路线 / Stage 顺序符合 canonical | working tree clean；只动 `docs/ROADMAP.md` | audit 输出 PASS/FAIL + ask_user |
| 2 | **Push canonical roadmap commit after audit PASS** | meta | release | `git push origin main` | ahead/behind 0/0；origin/main 包含本 commit；v0.5.0/v0.5.1 tag 不变 | push 成功 + ask_user |
| 3 | **v0.6 xfail inventory (read-only audit)** | Stage 2 | audit | 3 xfail 的 root cause / 解锁条件 / 推荐顺序（输出在对话，不写文件） | working tree clean | 输出 + ask_user |
| 4 | **v0.6.2 TUI MVP planning** | Stage 2 | planning | TUI MVP scope（解哪 1 个 xfail + Ask User UI 最小集），输出在对话 | working tree clean | 输出 + ask_user |
| 5 | **v0.6.2 TUI MVP characterization tests** | Stage 2 | coding (tests) | tests-only commit，钉死 TUI MVP 入口边界 | ruff clean / pytest +N passed / 无新 xfail | commit + audit + push |
| 6 | **v0.6.2 TUI MVP minimum implementation** | Stage 2 | coding (production + tests) | 解 1 个最小 xfail 或落地 1 项 Ask User UI | ruff / pytest 减 1 xf 或 +N passed / 无新 xf | commit + audit + push |

**严禁打包**：把上述任意两个 slice 合并到一个 commit。

> Slice 4 完成后，再决定是否在 Slice 5/6 之前插入 v0.6.1 readiness/release notes
> （仅在决定给 v0.6.1 tag 时才做；否则跳过）。

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
| generation cancel_token / 流中断生命周期 | Stage 1 残留 + Stage 2 TUI Esc 集成 |
| 复杂 topic switch（feedback_intent 之上） | Stage 1 残留 + Stage 2 输入语义 |
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
| awaiting_feedback_intent 两步分流 | v0.2 输入语义 | Stage 1 残留（hardcore xfail 钉住） |
| Textual backend / persistent shell | v0.2/v0.3 拆分 | Stage 2 |
| Skill 子系统 / install_skill / update_skill | v0.3 | Stage 5 |
| runtime_observer / observability 事件 | v0.3 | Stage 6（持续打底） |
| security.py / safety.py | v0.2 + v1.0 | Stage 7 + Stage 8 |
| hardcore_round2 LLM 意图分类讨论 | v1.0 探索 | **不做主线**（Non-goals） |
| generation cancel_token / Textual Esc | v0.2 + v0.3 | Stage 1 残留 + Stage 2 |

---

## 这份文档怎么用

1. **每次开新工作前**：先看 TL;DR — 当前是 Stage 几？这个工作属于当前 Stage 吗？
2. **想做点什么**前：先问"这是当前 Stage 毕业标准的哪一条"。答不出 → **推迟**。
3. **想加新能力**前：先看 **Explicit Non-goals**。在里面 → **拒绝**。
4. **当前 Stage 毕业标准全 ✅** → 写一笔 audit/commit 标记冻结，再启动下一 Stage。
5. **每一轮**：先报**当前 Stage** + **action type** + **为什么是 Roadmap 下一步**。
6. **doc drift 防御**：连续 docs-only commit ≥ 2 后，下一 slice 默认必须是
   audit / coding / tests，docs-only 需特别授权。
