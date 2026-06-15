---
title: "refactor: Window 3 — CM-1 config/provider import-boundary spike + registry-status precision"
type: refactor
date: 2026-06-13
---

# refactor: Window 3 — CM-1 config/provider import-boundary spike + registry-status precision

> 本文件是 implementation plan（决策与施工单元），不含代码 diff。本轮**只落本计划文档**：
> 不写 production code、不写 tests、不改 Roadmap、不改 North Star、不 push。

---

## 1. Status

- **PLAN-ONLY — implementation pending.** 本轮是 Window 3 Planning & Roadmap Reposition Audit；
  仅产出本 plan 文档（外加在本文档内记录 Roadmap Reconciliation，不直接改 Roadmap）。
- 计划深度：**Standard**（characterization + spike + 小幅 label 精度修正，behavior-neutral，5 个 unit）。
- 已用 **Graphify**（fresh index，mtime 晚于 HEAD）+ 真实源码行 + **2 个 fresh-context reviewer
  （architecture-strategist + adversarial）** 交叉验证；reviewer 在中心主张上**先分歧后收敛**（见 §7）。

---

## 2. Summary

Window 3 = **真实 Roadmap CM-1**（`Config 入口 import-boundary spike`，Theme 2，P2 `active`），
范围限定为：对 config/provider 入口做一张**可复现的 import-boundary inventory 表**，给出
"收敛 or 保留" 结论（CM-1 的 Roadmap exit condition），并顺手补两处**真正新增、不重复**的
registry-boundary 测试 + 一处**显式有界的 docstring label 精度修正**。

本窗口性质：**spike（inventory）+ 两条新 boundary test + 一处 label 精度修正**，全程
behavior-neutral、doc/test-first、零 runtime 行为变化。

**本窗口明确不是**用户口头的"Capability Model / Registry Boundary 大表征"。两个 fresh-context
reviewer 一致判定：宽泛的"declared/registered/routed/activated/dormant 跨 Tool/Provider/SubAgent/
Scheduler/Skill/MCP 统一 taxonomy" 会（a）漂移成 **CM-2 统一 Capability Contract**（Open OD-2、
红线 #13 禁止）、（b）与已存在的 `docs/CAPABILITY_BOUNDARIES.md` + `docs/06-audit/CURRENT_CAPABILITY_DRIFT.zh.md`
（GE-2 领地）重叠、（c）多数 boundary test 已由 W1/W2 落地 → 新增多为重复或矛盾。故收敛为 CM-1。

---

## 3. Context

- Window 1（`ACCEPT_WITH_TRACKED_DEBT — CLOSED`）：SA-1 V0 production routing（default-off flag
  `SUBAGENT_V0_ROUTING_ENABLED`）+ GE-1 Phase A golden E2E。
- Window 2（`ACCEPT_WITH_TRACKED_DEBT — CLOSED`，HEAD `a8ec4ac`）：SPA-1 masking ownership（Option B）
  + CR-1 action_scheduler governance label + W1-D4 fallback guard + 兼容路径 inventory。
- Window 1/2 已 push 到 `origin/main`。
- Roadmap §14 推荐主线把 SA-2 / GE-2 / RS-1 列为后续；CM-1 在 §13 P2 active 清单中，无依赖、低风险。

Window 3 选择经审计后落在 **CM-1**：它是 Roadmap 中**无依赖、低风险、有清晰 exit condition、
不触发任何 Open Decision** 的 P2 active spike，且能顺势收紧 W1/W2 暴露出的两处 registry-status
表述瑕疵——而不踩 CM-2 / GE-2 的雷。

---

## 4. Source documents（冻结，不改）

- North Star：`docs/architecture/ARCHITECTURE_NORTH_STAR.zh.md`
  sha256 `c73c2b3dbe926f30834a5d9ab20155cc947ab27158339a7c8b221d0d80568cde`
- Roadmap：`docs/06-audit/CURRENT_ARCHITECTURE_REPAIR_ROADMAP.zh.md`（Theme 2 CM-1/CM-2、Theme 8 CR-1、
  §11 OD-2、§12 红线、§9.4 W2 debt）— **本窗口不改，closure 时由 docs-only 流程统一回写**
- Window 1 Plan：`docs/plans/2026-06-12-002-feat-subagent-v0-production-routing-plan.md`
- Window 2 Plan：`docs/plans/2026-06-13-001-window-2-spa1-cr1-plan.md`
- Window 1 Closure：`docs/06-audit/WINDOW_1_CLOSURE_AUDIT.zh.md`
- Window 2 Closure：`docs/06-audit/WINDOW_2_CLOSURE_AUDIT.zh.md`
- AGENTS.md（repo 规则，不改）
- Baseline branch / HEAD：`main` / `a8ec4ac`

---

## 5. Roadmap Reconciliation（用户口头框架 vs Roadmap 真实 item + 代码事实）

> 沿用 Window 2 的 reconciliation 模式：用户用 Theme 级松散名，本窗口按 Roadmap 真实 item ID +
> 代码事实收敛。**本窗口不直接改 Roadmap**；下表是 closure 时 docs-only 流程的回写依据。

| 用户口头框架 | Roadmap / 代码事实（本窗口采用） |
|---|---|
| "CM-1 = Capability Model / Registry Boundary" | **真实 CM-1 = `Config 入口 import-boundary spike`**（Roadmap Theme 2 §CM-1，P2 active），范围是 `provider/config.py` / `simple_config.py` / `profiles.py` / `local_config.py` / `mcp_config*.py` 的 import boundary。**不是** capability model。 |
| "Capability Model / 统一 capability 抽象" | 那是 **CM-2 = Unified Capability Contract**（Roadmap §CM-2，P3 `accepted_deferred`，Open **OD-2**）。红线 §12 #13 禁止"无消费者的统一 Capability Contract"。**本窗口不碰 CM-2。** |
| "Registry Boundary 大表征（declared/registered/routed/inert 跨 6 个 surface）" | 已有 `docs/CAPABILITY_BOUNDARIES.md`（current）+ `docs/06-audit/CURRENT_CAPABILITY_DRIFT.zh.md`；宽泛重做属 **GE-2**（capability docs alignment）领地，且 6 个 surface 机制不统一（见 §6）。本窗口**只做 config/provider import-boundary（CM-1 本体）** + 两条窄 registry 测试。 |
| "顺便纠正 scheduler/handler 的状态标签" | W2 CR-1 标签 **大体准确**（registered-not-routed / inert-in-production），仅 `action_scheduler.py` docstring 中 "逻辑不可达 (unreachable)" 一词 overstate 一档（seam 原则上可达、被 37 个 `test_scheduler_main_path.py` 触达）。本窗口做**一处有界的 docstring 措辞收紧**，不动 W2 的 4 个 CR-1 AST 测试。 |

### 5.1 Roadmap 与代码事实不一致清单（surfaced，本窗口不直接改 Roadmap）

| # | 不一致 | 证据 | 处置 |
|---|---|---|---|
| RC-1 | `agent/action_scheduler.py` docstring（W2 CR-1 label）称 scheduler "逻辑不可达 (inert)"；同一 docstring 后段又描述其 live `run_main_loop()` 接线 | handler registered+routed（`phase1_hook.py:218-226`）；seam 端到端接通（`core.py:697/772/1452/1600/1693/1783`，`loop.py:728/1007-1027`）；`test_scheduler_main_path.py` 37 passed | **U4**：把 "逻辑不可达/unreachable" 收紧为 "production-unreachable / dormant-by-default（seam wired+tested，无生产入口注入 scheduler）"；docstring-only，不动 CR-1 AST 测试 |
| RC-2 | `phase1_hook.py:76` docstring "SubAgent 已接入（SUBAGENT_DELEGATE_L0）" 把 L0(registered) / V0(registered+flag-gated) / L1(referenced-but-unregistered=dead) 三态压成一句 | `phase1_hook.py:170/179` 注册 L0/V0；L1 无注册行；`core.py` live 默认走 L1-attempt→inline-local | **U4（可选）**：docstring 精度修正；若触及风险则降级为 §9 deferred（RC-2 不阻塞） |
| RC-3 | Roadmap CM-1（line ~122）把 `config.py / simple_config.py / profiles.py` 列在 `agent/` 根；实际在 `agent/provider/` | `ls`：无 `agent/config.py`/`agent/simple_config.py`；存在 `agent/provider/config.py`/`simple_config.py`/`profiles.py` | **U2**：inventory 表记录真实路径；closure 时建议 Roadmap 订正 |
| RC-4 | Roadmap §9.4 W2-D 表把 CR-1 记为完整 inert，未记录 "scheduler seam wired+dormant" 的精度债 | 同 RC-1 | closure 时建议在 §9.x 增登 **W3-D1**（label 精度债已 test-locked） |

> 处置原则（遵用户指令）：**发现 Roadmap 与代码事实明显不一致 → 先在本 plan 写 Reconciliation，
> 不直接大改 Roadmap。** Roadmap 状态更新在 Window 3 closure 时由 docs-only 流程统一回写。

---

## 6. Graphify + 源码核验（每条 load-bearing claim 附真实证据）

> Graphify 索引 fresh（`graphify-out/graph.json` mtime `Jun 13 11:26:35` > HEAD commit time
> `11:26:24`；16572 nodes）。未修改/提交 `graphify-out/*`。第一个 NL query 命中 TUI 噪音
> （vocabulary mismatch），改用 symbol-graph query + 真实源码行核验；不仅凭 Graphify summary 下结论。

### 6.1 registry / SoT owner 地图（六个 surface，机制**不统一**）

| Surface | SoT owner（核验位置） | 机制 | declared/registered/routed 状态 |
|---|---|---|---|
| Tool | `agent/tool_registry.py:43` `TOOL_REGISTRY: dict` + `register_tool()`(:142) | module-level dict | declared+registered+routed（TOOL_GATE/REQUEST/INVOKE/RESULT handler） |
| MCP | `agent/mcp.py:register_mcp_tools()`（唯一 `TOOL_REGISTRY` 变更点，已被 `test_architecture_boundaries.py` 锁） | wrap 进 TOOL_REGISTRY | routed via tool registry（North Star §9 一致） |
| SubAgent | `agent/subagent_system/registry.py:20` `SubAgentRegistry`（roots-scoped） | class + 显式 roots | L0 registered+routed(probe)；V0 registered+flag-gated；L1/L2 **未注册=dead** |
| Skill | `agent/skill_system/registry.py:26` `SkillRegistry`（roots-scoped，`list_visible()`） | class + 显式 roots | registered+routed（SKILL_SELECT handler） |
| Scheduler | handler：`action_scheduler_handler.py`；object：`action_scheduler.py:223` `ActionScheduler` | dispatcher handler + 注入 seam | **handler registered+routed；object seam wired+tested；dormant-by-default**（见 6.2） |
| Provider | `agent/provider/config.py:29` `SUPPORTED_PROVIDER_TYPES`（set）+ `factory.py:build_model_provider` | **factory + config 选择，无 registry dict** | 非 registry：按 `provider_type` 选择构造 |
| 路由 SoT | `agent/runtime_integration/dispatcher.py:78` `ActionHandlerRegistry`（per-instance，非 module singleton） | RuntimeActionType→handler | 路由唯一 SoT |
| Target 解析 | `agent/runtime_integration/target_catalog.py` `RuntimeActionTargetCatalog` | evidence-time target-identity 校验 | 独立关注点（**不是** capability inventory） |

**结论（duplicate SoT 检查）**：每个 surface 各拥一个概念，**无同概念双 owner**（符合 North Star §4.D）。
但六个 surface 机制不统一（Tool/MCP→TOOL_REGISTRY；SubAgent/Skill/Scheduler→dispatcher registry；
Provider→factory），所以"统一 registry taxonomy"会失真——这是**不做宽泛表征**的核心技术理由。

### 6.2 scheduler 中心事实（reviewer 先分歧后收敛的最终判定）

- `ActionSchedulerHandler` 在生产 dispatcher **registered**：`phase1_hook.py:218-226`（5 个 type 共享一个 handler）。
- 注入 seam **端到端 wired**：`core.py:697`(chat 参数 default None) → `:711`(continue_fn 闭包) →
  `:772/1202/1229/1251/1256/1333/1735/1751/1783/1868`(穿透) → `:1452`(scheduler 模式强制 ActionPlan schema) →
  `:1600/:1693`(`load_plan`) → `loop.py:728`(LoopDependencies.action_scheduler) → `:1007-1027`(预处理块)。
- `test_scheduler_main_path.py`：**37 passed**（docstring 称 "不再 dead code"）。
- 但 5 个 scheduler action type 的**唯一生产 `route_from_runtime_loop` 调用**在 `action_scheduler.py:495`
  （`_dispatch_evidence` 内）；core.py 每个 threading hop 被 `if action_scheduler is not None` 守卫；
  唯一注入点 `chat(action_scheduler=)`，**`main.py:118/177` 从不传、且不 import `agent.action_scheduler`**；
  37 个测试**全部手工构造 ActionScheduler 并注入**，无一驱动生产入口（测试自身 docstring line 371/393 承认）。
- **最终判定**：W2 CR-1 治理结论 **"registered-not-routed / inert-in-production" 准确且 test-locked**；
  仅 docstring 中 "逻辑不可达 (unreachable)" 一词 overstate 一档（seam 原则上可达）。这是**一行措辞收紧**，
  **不是结构性 mislabel，不重开 W2**。
- 旁证：`runtime_decision_frame.py:381-435` 把 scheduler 路径作为 live decision-frame 文档化
  （"→ dispatcher.route_from_runtime_loop → ActionSchedulerHandler"）——进一步说明它是"真实但 dormant"路径。

### 6.3 CM-1 config 面（真实 spike surface，已核验存在）

`agent/provider/config.py`、`agent/provider/simple_config.py`、`agent/provider/profiles.py`、
`agent/local_config.py`、`agent/mcp_config.py`(+`_cli`/`_presenter`/`_service`)。
Roadmap 把前三个误列在 `agent/` 根（实际在 `agent/provider/`，见 RC-3）。

---

## 7. Fresh-context reviewer 记录（如实报告）

| Reviewer | 调用方式 | 中心主张裁决 | 关键贡献 |
|---|---|---|---|
| architecture-strategist | `Agent(subagent_type=compound-engineering:ce-architecture-strategist)` | **CONFIRMED** dormant-not-inert | 推荐真实 CM-1 + 小 label 修正；列出 CM-2 漂移 / duplicate-SoT / test-duplication 四大风险；registry 地图 |
| adversarial | `Agent(subagent_type=compound-engineering:ce-adversarial-reviewer)` | **REFUTED（95%）** 我的 "W2 materially wrong" overclaim | 厘清 handler≠instance；唯一 route 调用在 :495；37 测试全手工注入；"inert" 准确，仅 "不可达" 一词 overstate；指出 `CAPABILITY_BOUNDARIES.md` 已存在、taxonomy 主观、两条**新**测试机会 |

**综合**：我（主 agent）接受 adversarial 的纠正——W2 CR-1 verdict sound，仅一词需收紧；我此前
"materially wrong" 是 overclaim。两个 reviewer **一致**反对宽泛 capability 表征、**一致**推荐收敛到
真实 CM-1。本 plan 据此定稿。

### 其它技能可用性（如实报告）

- **compound-engineering:ce-plan** — used（本 plan 的工作流）。
- **graphify** — used（symbol-graph query + 源码核验；未改 graphify-out）。
- **superpowers:test-driven-development** — applied as guidance（§10 RED-first 设计遵循其纪律）；
  本轮不写测试，故不实跑 RED/GREEN 循环。
- **superpowers:verification-before-completion** — applied as guidance（§11 验证流程、§13 closure gate）。
- **fresh-context architecture reviewer** — used（ce-architecture-strategist 子 agent，独立 context）。
- **fresh-context adversarial reviewer** — used（ce-adversarial-reviewer 子 agent，独立 context）。
- **gstack / plan-eng-review** —
  `Skill unavailable: gstack /plan-eng-review`
  `Fallback used: 两个 fresh-context reviewer（architecture + adversarial）+ ce-plan confidence pass`
  `Reason: 本环境未注册 gstack 插件 / plan-eng-review 技能；以 compound-engineering reviewer 替代独立审阅`

---

## 8. Scope（本窗口实际要做的内容）

### A. CM-1 — config/provider import-boundary inventory（spike，本体）

- 用**可复现命令**（AST import-graph，非临时 grep）列出每个 config 入口的 import boundary 与调用面：
  `provider/config.py`、`provider/simple_config.py`、`provider/profiles.py`、`local_config.py`、
  `mcp_config*.py`(×4)。
- 判定每个入口：是真有分散调用需收敛，还是仅需文档说明边界（CM-1 exit：得出 "收敛 or 保留" 结论）。
- 产出 inventory 表 + 结论文档；**不预先重构、不合并 config 模块、不改 provider 选择逻辑、不动 `.env`**。

### B. 读取-only registry-status snapshot（描述性，**非**统一 contract）

- 在同一 inventory 文档内追加一张**描述性 per-surface 状态表**（§6.1 的形态）：记录每个 surface
  的 SoT owner、机制、declared/registered/routed/dormant 观察事实。
- **硬约束（CM-2 防火墙）**：该表仅是 **markdown 描述 + 测试断言读取各 surface 自己的代码事实**；
  **不创建任何新的共享 production 符号**（无统一 `CapabilityStatus` enum / Protocol / base class /
  registry-of-registries）。一旦出现共享类型 = 越界进 CM-2 → 停止（§14 stop condition）。

### C. 两条**新增、不重复**的 registry boundary 测试（reviewer 背书）

- **C1（all-entrypoint scheduler-injection scan）**：扫描**所有**非测试 production 入口，断言无任何
  `chat(action_scheduler=<non-None>)` 注入点（CR-1 当前只查 `main.py`，无法防第二个入口静默激活）。
- **C2（registered action-type set lock）**：断言生产 dispatcher 注册的 `RuntimeActionType` 集合精确符合预期，
  且 `SUBAGENT_DELEGATE_L1` / `SUBAGENT_DELEGATE_L2` **不在**其中（锁住 Roadmap 依赖却无测试守护的 dead-L1 事实）。
- 两条都是 **AST/import-graph 级**，不跑真实 runtime、不激活任何路径。

### D. 一处有界的 docstring label 精度修正（RC-1，可选 RC-2）

- `agent/action_scheduler.py` 顶部 CR-1 label："逻辑不可达 (inert)" → "production-unreachable /
  dormant-by-default（seam wired + test-covered，无生产入口注入 scheduler；CR-1 AST 测试锁此 invariant）"。
- **production-docstring-only**；用 diff 断言**无 executable 行变化**；**不动 W2 的 4 个 CR-1 AST 测试**
  （它们不读该 prose 行，保持 green）。
- RC-2（`phase1_hook.py:76` L0/V0/L1 三态压缩）若低风险则一并收紧；触险则降级为 deferred（不阻塞）。

---

## 9. Explicit non-goals

继承用户 §7 禁止 + Roadmap 红线 §12 + 两个 reviewer 加固：

- 不写本轮 production code/tests（**本轮只落 plan 文档**）。
- **不建 CM-2 统一 Capability Contract**；不创建任何跨 surface 共享 `CapabilityStatus` 类型/enum/Protocol/
  registry-of-registries（红线 #13、Open OD-2）。
- **不接入 / 不激活 action_scheduler**；不新增任何 `chat(action_scheduler=)` 生产注入点；不实例化 ActionScheduler。
- 不重构 RuntimeAction；不重写 provider system；不创建 provider registry。
- 不合并 / 不删除 config 模块；不改 provider 选择逻辑；不动 `.env`。
- 不删除 inline-local fallback / L1 attempt / pre-loop seam / 任何 rollback path。
- 不做 production approval hook（OD-7）；不做 L3 lifecycle relocation（SA-2）；不做真实外部 provider E2E。
- **不削弱 / 不重写 W2 的 4 个 CR-1 AST 测试**（红线 #10）；label 修正只改 docstring 措辞。
- 不重做 `docs/CAPABILITY_BOUNDARIES.md` / `CURRENT_CAPABILITY_DRIFT.zh.md`（GE-2 领地）。
- 不改 North Star / Window 1·2 Plan / Roadmap（closure 统一回写）/ AGENTS.md / `.claude/settings.json`。
- 不 push；不 broad cleanup；不 repo-wide format；不提交 `graphify-out/*`。
- 不做广义 declared/registered/routed/inert 六-surface 统一 taxonomy（reviewer 一致反对）。

任一突破 → decision point（§14），不得静默纳入。

---

## 10. RED-first test plan（本轮不创建测试文件，仅设计）

> 遵 superpowers:test-driven-development 纪律：先红后绿。本窗口测试是 **characterization / boundary**，
> "RED" = 因"锁/断言尚不存在"而失败，**非**因行为错误（behavior-neutral）。

| ID | 测试 | RED 原因（今天失败） | 放置 | 需要 production 改动? |
|---|---|---|---|---|
| W3-T1 | config import-boundary inventory 与可复现 AST 命令输出一致（每入口 import 面 + 调用面快照） | 无 inventory 断言 | `tests/test_architecture_boundaries.py`（扩展，AST） | 否（docs+test） |
| W3-T2 | all-entrypoint scan：无非测试 production 入口传 `chat(action_scheduler=<non-None>)` | CR-1 仅查 main.py，无全入口断言 | `tests/test_architecture_boundaries.py`（扩展） | 否 |
| W3-T3 | 生产 dispatcher 注册的 RuntimeActionType 集合 == 预期；`SUBAGENT_DELEGATE_L1/L2` 不在其中 | dead-L1 事实无测试守护 | `tests/test_architecture_boundaries.py`（扩展） | 否 |
| W3-T4 | registry SoT 单一性快照：TOOL_REGISTRY / SubAgentRegistry / SkillRegistry / ActionHandlerRegistry 各为唯一 owner（描述性，读各自代码事实） | 无 per-surface 单 owner 快照 | `tests/test_architecture_boundaries.py`（扩展） | 否 |
| W3-T5 | label 精度回归：`action_scheduler.py` docstring 不再含 "不可达/unreachable" 字样、含 "dormant"；CR-1 4 个 AST 测试仍 green | docstring 含 overstate 词；无精度回归断言 | `tests/test_architecture_boundaries.py`（扩展） | 是（仅 docstring 措辞，U4） |

每条测试说明：
- **RED reason**：上表"RED 原因"列。
- **expected GREEN**：U2/U3 inventory + 断言落地后转绿；U4 docstring 收紧后 W3-T5 转绿。
- **production change needed**：仅 W3-T5 需要 docstring-only 改动（U4），其余 docs+test。
- **docs-only enough**：W3-T1 的 inventory 结论是 docs；W3-T2/T3/T4 是纯 test（读代码事实）。

**明确不加**（reviewer 强制）：
- 不加任何断言 scheduler "routed/activated" 的测试（会同时打破 4 个 CR-1 测试 + 需要生产注入 → regression）。
- 不重复 W1（V0 default-off）/ W2（masking ownership、CR-1 AST）/ 现有 `test_scheduler_main_path.py` 已有覆盖。
- 不加统一 capability-status enum 测试（= CM-2）。
- 不加 provider "registry" 断言（provider 是 factory，无 registry）。

---

## 11. Implementation units（施工姿态：spike + boundary test + 有界 label 修正，behavior-neutral）

### U1. RED baseline + reproducible import-graph command
- **Goal**：写 W3-T1..T5 为 RED；固化"可复现 AST import-graph 命令"（CM-1 spike 的取证工具）。
- **Dependencies**：无。
- **Files**：`tests/test_architecture_boundaries.py`（扩展）；`docs/06-audit/WINDOW_3_CM1_CONFIG_BOUNDARY_INVENTORY.zh.md`（新，inventory 骨架）。
- **Approach**：复用 `tests/test_architecture_boundaries.py` 既有 `ast.parse` / `_collect_agent_imports`(:267) 基础设施；
  inventory 限定 config/provider 入口，不做全仓 call-graph（schedule risk）。
- **Execution note**：characterization-first；RED 因"断言/inventory 尚不存在"失败，非行为错误。
- **Test scenarios**：W3-T1..T5 全部 RED。
- **Verification**：RED 套件因预期原因失败；import-graph 命令输出稳定可复现。

### U2. CM-1 config/provider import-boundary inventory + 结论
- **Goal**：产出 inventory 表 + "收敛 or 保留" 结论（CM-1 exit condition）。
- **Dependencies**：U1。
- **Files**：`docs/06-audit/WINDOW_3_CM1_CONFIG_BOUNDARY_INVENTORY.zh.md`；`tests/test_architecture_boundaries.py`（W3-T1）。
- **Approach**：对每个 config 入口列 import 面 + 被谁调用；判定"分散需收敛"或"边界清晰仅需文档"。记录 RC-3 路径订正。
- **Patterns to follow**：W2 `WINDOW_2_COMPAT_INVENTORY.zh.md` 的 characterization 表格风格。
- **Test scenarios**：W3-T1。
- **Verification**：inventory 与 AST 命令输出一致；结论明确（收敛/保留）。

### U3. Registry-boundary tests（W3-T2/T3/T4，新增不重复）
- **Goal**：补两条 reviewer 背书的新 boundary 测试 + 一条 per-surface 单 owner 快照。
- **Dependencies**：U1。
- **Files**：`tests/test_architecture_boundaries.py`（扩展，AST）。
- **Approach**：W3-T2 全入口扫 `chat(action_scheduler=)`；W3-T3 断言注册 action-type 集合且 L1/L2 不在内；
  W3-T4 per-surface 单 owner 快照（读各 registry 自身代码事实，**不建共享类型**）。
- **Patterns to follow**：W2 CR-1 AST 测试（`_collect_agent_imports`、`ast.FunctionDef` 参数检视）。
- **Test scenarios**：W3-T2、W3-T3、W3-T4。
- **Verification**：三条 green；与现有 boundary 测试无重复断言、无矛盾。

### U4. Bounded docstring label precision（RC-1，可选 RC-2）
- **Goal**：收紧 `action_scheduler.py` "逻辑不可达"→"production-unreachable / dormant-by-default"；W3-T5 转绿。
- **Dependencies**：U1。
- **Files**：`agent/action_scheduler.py`（**仅 docstring 行**）；可选 `agent/runtime_integration/phase1_hook.py`（:76 docstring）；`tests/test_architecture_boundaries.py`（W3-T5）。
- **Approach**：只改 docstring 措辞；用 `git diff` 确认无 executable 行变化；W2 的 4 个 CR-1 AST 测试保持 green
  （它们不读该 prose 行）。RC-2 触险则移入 §15 deferred。
- **Execution note**：behavior-neutral；diff-line 自检 production 仅 comment/docstring 变。
- **Test scenarios**：W3-T5。
- **Verification**：W3-T5 green；CR-1 4 测试仍 green；`test_scheduler_main_path.py` 37 仍 green。

### U5. Closure
- **Goal**：full suite 复验；产出 Roadmap Status Delta 草稿（CM-1→completed 建议 + RC-1..RC-4 订正建议 + W3-D1 债登记）；写 closure audit。
- **Dependencies**：U2..U4。
- **Files**：`docs/06-audit/WINDOW_3_CLOSURE_AUDIT.zh.md`（新）；**不改 Roadmap/North Star/Plan**（Roadmap 回写由 docs-only 流程在独立审计后单独执行）。
- **Test expectation**：none —— docs only。
- **Verification**：full suite 0 unexpected failures；frozen sha256 不变；未 push。

---

## 12. Acceptance criteria

- CM-1：config/provider import-boundary inventory 完成，"收敛 or 保留" 结论明确（CM-1 exit condition 满足）。
- registry/capability boundary 清晰：六个 surface 的 SoT owner + 机制 + declared/registered/routed/dormant 状态可解释，**无新建共享 contract 类型**。
- action_scheduler 仍 **dormant-by-default**（无新生产注入点；W3-T2 锁全入口）；CR-1 4 个 AST 测试仍 green。
- SubAgent V0 routing 不回归（W1 default-off flag 不变）；`SUBAGENT_DELEGATE_L1/L2` 仍未注册（W3-T3 锁）。
- safe metadata ownership（W2 SPA-1）不回归。
- Roadmap 与代码事实对齐：RC-1..RC-4 在本 plan 记录，closure 时建议回写（本窗口不直接改 Roadmap）。
- no default-on；no rollback path deletion；no CM-2；no provider registry。
- full suite 0 unexpected failures；`git diff --check` clean；touched Python 文件 `ruff` clean。
- 0 Blocker / 0 High；tracked debt（W3-D1）登记；closure audit 完成。
- North Star / Window 1·2 Plan sha256 不变；docs/test commit 原子；**未 push**。

---

## 13. Verification flow（superpowers:verification-before-completion）

1. targeted：`pytest tests/test_architecture_boundaries.py -q`（W3-T1..T5 + 现有 CR-1/boundary）。
2. relevant integration：`pytest tests/runtime_integration/test_scheduler_main_path.py tests/runtime_integration/test_safe_metadata_ownership.py -q`（确认无回归）。
3. golden：`pytest tests/golden_e2e/ -q`。
4. full：`.venv/bin/python -m pytest -q -rx`（exit 0；known xfails 保持显式）。
5. `git diff --check`；`.venv/bin/ruff check`（touched 文件）。
6. U4 diff-line 自检：production 仅 docstring/comment 行变。

---

## 14. Risks / rollback

| 风险 | 触发信号 | 检测 | rollback | 阻塞? |
|---|---|---|---|---|
| 漂移成 CM-2 统一 Capability Contract | 出现共享 `CapabilityStatus` 类型/enum/Protocol/registry-of-registries | code review + §9 非目标 | 删除共享符号，回退到描述性表 | **是** |
| 误激活 action_scheduler | 新增 `chat(action_scheduler=)` 注入点 / 实例化 ActionScheduler | W3-T2 全入口扫描 + CR-1 4 测试 | 还原 | **是** |
| 新测试与 W1/W2 重复或矛盾 | 新断言重述 V0 default-off / masking / scheduler-not-routed | diff 对照现有 boundary 测试 | 删除重复断言 | 否 |
| label 修正打破 CR-1 测试 | W2 的 4 个 CR-1 AST 测试转红 | 运行 CR-1 测试 | 只改 docstring，不改 executable | **是若发生** |
| 创建 duplicate registry SoT | 出现维护态的并行 status 列表/dict | review：inventory 必须 derived-from-code | 删除并行 SoT | 否 |
| inventory 误把 provider 当 "registry" | 出现 provider registry 断言 | provider 是 factory（`SUPPORTED_PROVIDER_TYPES` set） | 改表述 | 否 |
| 与 `CAPABILITY_BOUNDARIES.md`/GE-2 重叠膨胀 | inventory 越出 config/provider，扩到全 capability docs | scope 对照 §8A | 重新收敛到 CM-1 | 否（重收敛） |
| Graphify 过期 → 事实错 | 索引 mtime < HEAD | 重查 mtime；`graphify update .`（不提交） | 重跑 | 否 |
| RC-2 docstring 修正触发更大改动 | phase1_hook.py 改动超出 :76 docstring | diff-line 自检 | 降级 RC-2 为 deferred | 否 |
| 把宽泛 taxonomy 当本窗口目标 | 出现六-surface 统一 declared/registered/routed/inert 强断言 | reviewer 一致反对 + §9 | 收敛到 CM-1 + 两条窄测试 | 否（重收敛） |

**Rollback boundary**：U2 inventory = docs-only 可删；U3 = 纯新增测试可独立回退；U4 = docstring-only revert；
全窗口 behavior-neutral，无 runtime 行为可回滚项。

---

## 15. Deferred debt（本窗口结束时登记）

- **W3-D1**：scheduler label 精度债——本窗口把 "逻辑不可达" 收紧为 "dormant-by-default" 并 test-lock；
  scheduler 是否长期保留 dormant seam（vs 删除 vs 接入）属 OD-2/benchmark 后续，**不在本窗口**。
- **W3-D2**：RC-2（`phase1_hook.py:76` L0/V0/L1 三态 docstring）若本窗口降级，留独立 doc-align 窗口。
- **W3-D3**：CM-1 inventory 若结论为"需收敛"，真实 config 模块收敛属独立 refactor 窗口（本窗口只出结论，不重构）。
- **W3-D4**：宽泛 capability/registry 统一表征（用户原始设想）→ 归入 **GE-2**（capability docs alignment）+
  **CM-2**（OD-2 裁决后），不在本窗口。
- **carry-forward**：W2-D1（`_EXTRA_REDACT_PATTERNS` 归属）/ W2-D2（OD-7）/ W2-D4（L1 dead-code 移除）/
  W1-D1/D5/D6/D7 不变。

---

## 16. Closure criteria

仅当全部满足才宣布 Window 3 关闭：
- CM-1 config/provider import-boundary inventory + "收敛 or 保留" 结论完成。
- W3-T1..T5 green；两条新 boundary 测试不重复、不矛盾。
- action_scheduler 仍 dormant（W3-T2 锁全入口）；CR-1 4 测试 + `test_scheduler_main_path.py` 37 测试仍 green。
- W1 V0 default-off / W2 masking ownership 不回归。
- 无 CM-2 共享 contract；无 provider registry；无 rollback path 删除；无 default-on。
- full suite 0 unexpected failures；`git diff --check` clean；touched 文件 `ruff` clean。
- Roadmap Status Delta 草稿产出（CM-1→completed + RC-1..RC-4 订正建议 + W3-D1 登记）；closure audit 写就。
- North Star / Window 1·2 Plan sha256 不变；docs/test commit 原子；**未 push**。
- 最终 verdict：`ACCEPT_WITH_TRACKED_DEBT — WINDOW 3 CLOSED`。

若出现真实 Blocker/High：不改代码，只输出 `CLOSURE_BLOCKED` + 证据。

---

## 17. Sources / Research（真实源码 + Graphify 核验）

- `agent/runtime_integration/phase1_hook.py:64` `build_phase1_dispatcher`，`:170/179` L0/V0 注册，`:218-226` scheduler handler 注册，`:76` L0 docstring（RC-2）。
- `agent/core.py:697/711/772/1452/1600/1693/1783` action_scheduler 穿透 + scheduler 模式；`:2152-2163` V0 route。
- `agent/loop.py:728` `LoopDependencies.action_scheduler`，`:1007-1027` scheduler 预处理块。
- `agent/action_scheduler.py:223` `ActionScheduler`，`:495` 唯一 `route_from_runtime_loop` 调用，`:3-9` CR-1 label（RC-1）。
- `tests/runtime_integration/test_scheduler_main_path.py`（37 passed；docstring line 371/393 承认手工注入）。
- `tests/test_architecture_boundaries.py:2083-2216` W2 CR-1 AST 测试（保持 green）。
- registries：`agent/tool_registry.py:43`，`agent/subagent_system/registry.py:20`，`agent/skill_system/registry.py:26`，`agent/runtime_integration/dispatcher.py:78`，`agent/runtime_integration/target_catalog.py`。
- provider：`agent/provider/config.py:29` `SUPPORTED_PROVIDER_TYPES`，`factory.py:18` `build_model_provider`。
- MCP：`agent/mcp.py:register_mcp_tools`（唯一 TOOL_REGISTRY 变更点）。
- config 面：`agent/provider/{config,simple_config,profiles}.py`、`agent/local_config.py`、`agent/mcp_config*.py`。
- 既有 capability docs（GE-2 领地，不重做）：`docs/CAPABILITY_BOUNDARIES.md`、`docs/06-audit/CURRENT_CAPABILITY_DRIFT.zh.md`。
- Roadmap CM-1/CM-2/OD-2：`docs/06-audit/CURRENT_ARCHITECTURE_REPAIR_ROADMAP.zh.md`。
- Reviewers：ce-architecture-strategist（CONFIRMED dormant-not-inert）、ce-adversarial-reviewer（REFUTED overclaim，95%，"inert" 准确仅一词需收紧）。
