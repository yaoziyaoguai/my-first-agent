# ARCHITECTURE NORTH STAR (目标架构北极星)

> 文档级别：Architecture North Star
> 适用对象：my-first-agent 项目的所有核心架构决策
> 状态：**Draft v0 — 待审计与用户确认**
> 创建日期：2026-06-12
> 维护人：Chief Agent Runtime Architect
> 权威等级：本文件在 *目标 / 原则 / 验收* 轴上最高（见 §1 轴 2）；在
>           *运行时事实* 轴上不覆盖代码与可执行测试（见 §1 轴 1、§18），
>           也不覆盖 `docs/06-audit/CURRENT_ARCHITECTURE_REPAIR_ROADMAP.zh.md`
>           中“已 locked” 的运行时事实条目。
> 修改约束：本文件不得自动覆盖代码事实、不得自动把现状当成目标；目标与现状
>           必须分别标注。

---

## 0. 阅读说明

本文档把每条内容归入以下 **五类章节分类**：**Current Runtime Fact**（代码今天
实际怎么跑，引用真实 file/function/test/git evidence） / **Target Architecture**
（我们要去哪） / **Migration State**（正在迁移中的部分） / **Deferred Decision**
（尚未决定） / **Non-Goal**（明确不属于本项目）。现状与目标不可混淆。

> 章节分类（上面五类）与 *证据标签*（下面 `Fact:/Inference:/Open:`）是两个
> 维度：前者说明“这段属于现状还是目标”，后者标注“某条主张的证据强度”。

证据类型前缀：
- `Fact:` 代码 / 文档 / 测试 / commit 的直接证据（file:line 或 test_id）。
- `Inference:` 由多个事实合理推得，但不直接存在于代码中。
- `Open:` 文档编写时无法确认，需要用户或后续审计决定。

> 本文档建立期间**没有修改任何 production code、测试、Roadmap、plan、AGENTS.md**；
> 没有 `git add` / `commit` / `push`。本文件是 *新* 文档，与现有事实集并存。

---

## 1. 文档定位、适用范围和权威等级

**定位**：本文件是 *目标架构* 的唯一权威来源。它约束：

1. 新功能如何在已有边界内加入；
2. 如何识别“双主路径 / 双 source of truth / 旧架构绕路”；
3. 架构 Repair 的 Done 定义；
4. PR Review 中“违反架构”的判定标准。

**适用范围**：

- 项目根：`/Users/jinkun.wang/work_space/my-first-agent`
- 核心代码：`agent/`（特别是 `agent/core.py`、`agent/loop.py`、
  `agent/runtime_decision_frame.py`、`agent/runtime_integration/`、
  `agent/subagent_inline.py`、`agent/runtime_observer.py`（trace writer，
  写数据文件 `agent_log.jsonl`）、`agent/checkpoint.py`、`agent/memory_*.py`）。
- 核心测试：`tests/unit/`、`tests/runtime_integration/`、
  `tests/smoke/`、`tests/test_architecture_boundaries.py`。

**不**约束：外部 framework、gstack、compound-engineering skill 自身的内部
实现；它们是工具，不属于本项目。

**权威等级（双轴）**：权威分两条互不覆盖的轴，冲突时按 *问题类型* 选轴——

**轴 1 · Runtime Fact axis（“现在实际怎么跑”）**：production code +
可执行测试 是当前事实的最高证据。North Star *不得* 覆盖代码事实；
旧实现也 *不得* 反向定义目标架构。此轴排序见 §18。

**轴 2 · Target / Principle axis（“我们要去哪、按什么原则、怎样算通过”）**：
本文件（North Star）是目标架构、设计原则与验收标准的最高依据，自上而下：

1. **North Star（本文件）**—目标与原则。
2. **`docs/06-audit/CURRENT_ARCHITECTURE_REPAIR_ROADMAP.zh.md`**—目标与现状
   之间的施工计划。
3. **Capability / Plan / Audit Delta 文档**—具体变更记录。
4. **代码注释**—最低权威；当与 North Star 在 *目标/原则* 上冲突时，
   代码注释可被本文件覆盖（但代码 *行为事实* 仍归轴 1）。

---

## 2. 项目使命：First Agent 是什么、不是什么

**是什么**：

- 一个 *进程内* 运行的 LLM-driven agent runtime，专注于 **真实、可审计、可恢复**
  的 agent 调度、工具调用、子 agent 编排、记忆治理、状态持久化。
- 第一原则：**安全 > 可恢复 > 可解释 > 灵活**。
- 目标用户：希望以单一进程、清晰边界获得 production-grade agent runtime
  的工程师；不是 prompt 试验场。

**不是什么**：

- 不是多 agent 协作平台、不是 swarm、不是 multi-tenant runtime。
- 不是 model gateway / 推理代理；LLM 调用是内部能力。
- 不是低代码 / prompt-app framework；不接受把 prompt 升级为产品。
- 不是 SaaS、不带服务器边界；部署单位是单一 Python 进程。
- 不为了“像 LangGraph/AutoGen/CrewAI”而引入对应概念。

> `Open:` 是否在远期接受 HTTP / RPC 远程 client 协议（影响 `Core` 的
> 边界定义）— 见 §23。

---

## 3. 当前架构形成背景和主要历史问题

### 3.1 形成背景

- 项目初期以能力实现为主，agent 主循环、工具调用、子 agent、记忆、checkpoint
  是并行能力、边界不严。
- 多次 cleanup / architecture repair / 局部修复积累了一个 *事实层* 和
  *叙述层* 不一致的中间态。
- 现有事实证据：
  - `Fact:` 单一 `Core` 入口 `agent/core.py:chat()`（当前 `def chat` 在 line 763；
    `core.py` 共 2046 行）。引用以符号为准；行号随版本漂移，不作为核心事实。
  - `Fact:` Runtime 主循环 turn-end 由 `agent/loop.py:877 _dispatch_turn_end_checkpoint_save`
    触发，并由 `agent/loop.py:940 run_main_loop` 编排主 turn 循环；
    `agent/loop.py:920+` 是事件日志 flush 路径（`_dispatch_turn_end_event_log_flush`）。
  - `Fact:` 唯一生产主路径 L1-attempt → direct inline-local fallback
    （`agent/subagent_inline.py:37 execute_subagent_delegation`，
    调用栈从 `agent/core.py` 的 `_execute_subagent_delegation` 进入）。
  - `Fact:` V0 子 agent handler 已 `registered + contract-verified` 但
    **未 production-routed**（详见 `docs/06-audit/V0_WIRING_DECISION.zh.md`）。
  - `Fact:` 记忆 consolidation pipeline 已 frozen（2026-05-25）但仍
    runtime-reachable（详见 `tests/runtime_integration/test_memory_consolidation_truth.py`）。
  - `Fact:` 已有 `agent/runtime_integration/dispatcher.py:RuntimeActionDispatcher`
    与 `agent/runtime_integration/phase1_hook.py:build_phase1_dispatcher`
    作为统一的 dispatch 入口。
  - `Fact:` 已有 safe_metadata projector（D1 / D2 / D3 已落地于
    `agent/runtime_integration/safe_metadata.py`）。

### 3.2 主要历史问题

- **双主路径风险**：`runtime_decision_frame` 描述的 SoT 与 `core.chat`
  实际调用的 inline-local fallback 存在时间差；过去审计已经反复发现
  SoT 文档与代码不一致（详见 `docs/06-audit/POST_REPAIR_AUDIT_DELTA.zh.md`）。
- **Capability drift**：能力与文档长期不同步；已有专文档
  `docs/06-audit/CURRENT_CAPABILITY_DRIFT.zh.md` 跟踪。
- **frozen / legacy 模块的“复活”压力**：被冻结的 memory consolidation
  与 L1/L2 子 agent 仍可能被新代码无意复活。
- **safe metadata 边界尚未统一**：曾经每个 trust boundary 各自 inline
  调 `mask_user_visible_secrets`；U5 D1/D2/D3 是首次把 projector
  作为单一 import surface。
- **MCP 协议适配层与 Tool 边界尚未合一**：`agent/mcp_*.py` 多个文件 +
  `agent/tool_registry.py` 共存；MCP 是否进入 Runtime Spine 仍未达成
  决定（`Open:`，见 §23）。
- **测试金字塔未与架构同步**：缺少 Golden E2E 共识，unit / contract /
  architecture / integration 边界需要由本文件锁定。

---

## 4. 架构设计原则及项目化解释

> 这些原则是 *项目本地* 的解释；不照搬外部 framework 概念；如冲突，
> 优先级 A > B > … > L。

### A. Simplicity before complexity

- 只有当某种复杂度能 *被评测或可观测证据* 证明提升结果时才允许引入。
- 禁止为“像某个框架”而增加抽象层。
- `Fact:` 当前项目拒绝 *reflection-loop / multi-agent 框架化* 抽象，
  没有 reflection loop 模块。现有 `agent/planner.py:generate_action_plan`
  是 *生产路径内的 ActionPlan 解析器*（由 `agent/core.py` import，
  `core.py` 注释明确“planner.py 拥有 ActionPlan 解析逻辑”），
  *不是* LangGraph 式 planner 抽象 / reflection loop；原则 A 约束的是后者，不是前者。

### B. One Runtime Spine

- 所有 Tool、Skill、Memory、SubAgent、MCP 都必须进入同一个
  `Runtime → Dispatcher → Handler → Adapter → Side effect` 主流程。
- 禁止长期存在“绕过 dispatcher 的第二条生产主路径”。
- `Fact:` 现有 `agent/runtime_integration/dispatcher.py:RuntimeActionDispatcher.route`
  是统一入口；任何新增 side-effect 必须挂入此入口。
- `Inference:` 这是修复“双主路径”问题的关键目标。

### C. Probabilistic decision, deterministic execution

- LLM 负责 *plan / choice*；Runtime 负责 *validation, permission, execution,
  state transition, retry, error, evidence, stop*。
- `Fact:` 当前 LLM 决定调什么（plan / `tool_request` JSON）；execution
  走 dispatcher + policy gate。证据：`agent/runtime_integration/phase1_hook.py`、
  `agent/loop.py:_dispatch_tool_pipeline`。

### D. Single owner / single source of truth

- 每个关键概念只有一个 owner：
  - Target resolution → `agent/runtime_integration/target_catalog.py:RuntimeActionTargetCatalog`
  - Tool registry → `agent/tool_registry.py:TOOL_REGISTRY`（dict）+ `ToolRegistryEntry`（TypedDict）；
    当前无 `ToolRegistry` 类。
  - Memory write → `Open:` canonical owner *待定*。当前职责是 *拆分* 的：
    `agent/memory.py` 负责压缩 / 抽取及部分协调，持久化由
    `agent/memory_store.py` / `agent/memory_fs_store.py:FilesystemMemoryStore`
    （`apply_operation_intent` / `store_retained_record`）承担，触发与治理由
    `agent/memory_runtime_hooks.py` + `agent/memory_policy.py` 负责。
    谁成为 canonical write owner 属 Repair Roadmap 迁移决策，本文件不预选（见 §10.1 / §23）。
  - Safe metadata → `agent/runtime_integration/safe_metadata.py`
  - Capability status → `agent/runtime_decision_frame.py:RuntimeDecisionFrame`
  - Evidence classification → `agent/runtime_integration/evidence.py:classify_evidence_level`
    （RuntimeActionEvent *类型* 定义在 `schema.py`，见 §14）
- 禁止相同概念在两处被同时 owner。

### E. Explicit state machine

- `Fact:` 当前 dispatcher 执行结果枚举为 7 值：`success`, `rejected`,
  `confirmation_required`, `not_supported`, `failed`, `skipped`,
  `policy_blocked`（`agent/runtime_integration/schema.py:VALID_RESULT_STATUSES`，
  `RuntimeActionResult.__post_init__` 对非法值 raise）。这是已落地事实。
  其中 `confirmation_required` 对应 §13/OD-7 的 human-approval 面，
  `policy_blocked` 对应 §13/§F 的 guardrail 结果。
- `Target / Open:` 完整 *全局 Agent 运行状态机*（候选态：`running`,
  `waiting_user`, `tool_call`, `retry`, `fallback`, `denied`, `failed`,
  `cancelled`, `suspended`, `completed`，§12.1 另引入 `idle`）尚未确定
  canonical 枚举，也未实现为统一状态机。本文件 *不* 选定枚举、*不* 实施
  状态机设计；canonical 化属待决项（见 §12 与 §23）。
- 注意：dispatcher 的 3 值 result 与全局状态机是两个层面，不可混为一谈。

### F. Controlled side effects

- `Target governance sequence:` 所有外部动作应经过
  `policy → permission → validation → execution → evidence` 的治理次序。
- 高风险操作：human approval、idempotency key、retry budget。
- `Inference:` `agent/runtime_integration/phase1_hook.py` 与
  `agent/runtime_integration/dispatcher.py` 体现了该治理次序的主体
  （route + gate + policy + evidence）；但 `permission` 是否作为独立于
  `policy` 的 named stage 尚未逐一映射到 call site，故此处为 Inference 而非 Fact。
  `Open:` “高风险” 集合与 approval UX 尚未由本文件锁定。

### G. First-class observability

- 每次运行能重建：decision, tool, memory, subagent, fallback, error, cost,
  latency, final result。
- `Fact:` `agent/runtime_observer.py:log_event` 写 `agent_log.jsonl`；
  `agent/evidence_recorder.py` 写 evidence。两者关系是
  “receipt-only / side-effect trace”。
- `Open:` “cost / latency” 字段是否进入 observability surface，
  需与 §14 锁定。

### H. Durable and recoverable execution

- 长任务支持：checkpoint, resume, failure recovery, interrupt, human
  介入。
- `Fact:` `agent/checkpoint.py:save_checkpoint` / `load_checkpoint` 已
  存在；当前 turn-end 自动 save。`Open:` resume 协议与 interruption UX
  边界未完整定义。

### I. Governed memory

- 明确：working state, conversation memory, long-term memory,
  consolidation, provenance, write permission, conflict, deletion,
  lifecycle。
- `Fact:` `agent/memory.py` 已有 working / conversation / long-term 分层；
  `agent/memory_policy.py:DeterministicMemoryPolicy` 是写入 gate。
- `Fact:` consolidation pipeline frozen（2026-05-25）但 runtime-reachable。
- `Open:` provenance 格式、deletion 流程、跨 session 冲突尚未由本文件锁定。

### J. Bounded subagents

- SubAgent 是父 Runtime 管理的 *受控执行单元*；不是独立 runtime。
- 必须继承：预算、权限、工具、上下文、trace、停止条件。
- `Fact:` `agent/subagent_inline.py:execute_subagent_delegation` 是当前
  live inline-local 实现；V0 handler 已 registered 但未 routed。
- `Open:` V0 是否在 *本* 目标架构中作为 *生产* SubAgent 主路径（详见
  `docs/06-audit/V0_WIRING_DECISION.zh.md`），**需要用户决定**。

### K. Stable capability interfaces

- Tool / Skill / MCP / Agent 能力必须有：schema, semantics, error model,
  version, 兼容策略。
- MCP 是 *外部协议适配层*，不主导内部架构。
- `Fact:` `agent/tool_registry.py:ToolRegistryEntry` TypedDict 提供
  tool schema；`agent/mcp_models.py` 提供 MCP model schema。
- `Open:` Tool / Skill / MCP 三者的 capability interface 是否应共享
  一个统一 Capability Contract，**需要用户决定**（§23）。

### L. Evaluation-driven evolution

- 复杂能力必须配 benchmark / Golden E2E / 真实评测。
- `Fact:` 当前已有 `tests/runtime_integration/` + `tests/smoke/`，但
  缺少 explicit Golden E2E 集合。
- `Open:` Golden E2E 集合应由本文件锚定，并由 §19 锁定测试金字塔。

---

## 5. 目标架构总览图

> 图中所有方框代表 *目标*。下面的 ASCII 图刻意只用纯 ASCII（`+ - | v ^ >`），
> *不* 用线型区分“待决定 vs 已确定”；该区分由方框内 / 旁的文字标注承载
> （例如 `(recovery)` 支路、`待决策` 字样）。线型语义见图后图例。

```
                     +------------------------+
                     |        User/Input      |
                     |  (TUI / CLI / REPL)    |
                     +-----------+------------+
                                 |
                                 v
                     +------------------------+
                     |    Core  (Core 层)     |
                     |  - entry, mode resolve |
                     |  - chat, delegate, end |
                     +-----------+------------+
                                 |
                                 v
                     +------------------------+
                     |  Agent Runtime Loop    |
                     |  (loop.py: turn loop)  |
                     |  - planning, dispatch  |
                     |  - checkpoint, suspend |
                     +-----+---------+--------+
                           |         |
                           |         +--> (recovery) ->  Checkpoint store
                           v
                     +------------------------+
                     | Decision / Plan        |
                     | (model call + parser)  |
                     +-----------+------------+
                                 |
                                 v
                     +------------------------+
                     | Policy / Guardrails    |
                     | - LLM tool gate        |
                     | - memory policy        |
                     | - subagent budget gate |
                     +-----------+------------+
                                 |
                                 v
            +----------------------------------------+
            |     RuntimeActionDispatcher (spine)    |
            |   agent/runtime_integration/dispatcher  |
            +-----+--------+--------+-------+--------+
                  |        |        |       |
                  v        v        v       v
              +------+ +-------+ +------+ +----------+
              | Tool | | Skill | | MCP  | | SubAgent |
              | reg  | | reg   | | adpt | |  reg     |
              +--+---+ +---+---+ +--+---+ +----+-----+
                 |        |        |          |
                 v        v        v          v
        +--------+--------+--------+-----+----+--------+
        |            Handler / Adapter            |
        | (per action type: per-domain adapter)   |
        +-----+-----+-----+-----+-----+-----+----+
              |     |     |     |     |     |
              v     v     v     v     v     v
        (side effect: tool call, file write, mcp call,
         memory write, subagent invoke, evidence emit)

                  ^                                  ^
                  |                                  |
        +---------+--------+                +-------+--------+
        |   Evidence /     |                |  State Update  |
        |   Trace update   |                |  (memory +     |
        | (observer,       |                |  checkpoint,   |
        |  evidence_rec)   |                |   subagent ctx)|
        +------------------+                +-------+--------+
                                                       |
                                                       v
                                               +---------------+
                                               |   Loop or     |
                                               |   Completion  |
                                               +-------+-------+
                                                       |
                                                       v
                                                  Output
```

辅助横切关注（横切关注不是主路径）：

- **Checkpoint / Resume**：由 Loop 在 turn-end 调用，挂在 `(recovery)` 支路；
  上方 ASCII 图采用统一符号（不区分线型）：
    - `|` / `v` / `->`：控制流与主路径方向（图中所有箭头同形）。
    - `^`：副作用结果向 Evidence / State Update 的回写方向。
    - 文字标注（如 `(recovery)`、`Evidence / Trace update`）承载语义区分，
      不依赖线型；本图刻意只用纯 ASCII，故不引入 `╌ ┄ ═` 等线型符号。
- **AI 风险与对抗提示治理**：旁路流量经 `safe_metadata` projector + MCP sanitizer
  走 `Observability` 边的 evidence 流；这是 governance 维度，不属于主路径。
  图中的 *cross-cutting* 标注标识它横切多个 layer；该 layer 不拥有副作用决策权。
- **Trace / Evaluation**：`agent/runtime_observer.py`（writer）+ `agent_log.jsonl`（sink）
  + Golden E2E；横切、不改变主路径。
- **Human Approval**：仅在高风险 side effect 前插入（pending 决策）。
- **Fallback / Error**：dispatcher + handler 共同处理；fallback
  *不能* 形成第二条生产主路径。
- **Memory Read / Write**：Memory 写入由 Policy gate → Dispatcher
  → MemoryAdapter → state update；读取可经 dispatch 或由 Core 直接
  调 working state。
- **Subagent Child Execution**：SubAgent 复用 Runtime Spine，但受 J 节
  治理。

---

## 6. 唯一 Runtime Spine 的完整时序

> Target。下面的步骤是 *目标*。`Inference:` 其中大部分步骤已有代码事实基础
> （如 T+0 `core.chat`、T+2 model call、T+5 dispatcher route、T+8 evidence emit、
> T+11 turn-end checkpoint 均已落地）；具体覆盖率应由 §20 Rubric 的
> Architecture Gap Audit 实测，本文件不给未经测量的百分比。

```
T+0  User/Input → Core.chat()
T+1  Core 装载 LoopContext, 解析 mode (CLI/NL), 调用 Loop.deps.chat()
T+2  Loop 装配 plan request, 调用 LLM (model call) → model 决策
T+3  Loop 解析 model 决策:
        a) text → 进入显示路径
        b) tool_request  → 进入 RuntimeActionDispatcher
        c) subagent     → 走 SubAgent Handler
        d) memory op    → 走 Memory Policy + Dispatcher
T+4  Policy / Guardrails: 验证 tool/skill/memory/subagent 是否允许
T+5  Dispatcher 路由 → 调用对应 Handler
T+6  Handler → Adapter → Side effect
T+7  Side effect result → Handler → Dispatcher
T+8  Dispatcher 写 evidence (RuntimeActionEvent)
T+9  Loop 决定: continue / retry / fallback / suspend / complete
T+10 若 continue: 更新 LoopContext (state), 回到 T+2
   若 suspend:  save_checkpoint(), 等待 resume
   若 complete: 关闭 observer, 输出
T+11 turn-end: _dispatch_turn_end_checkpoint_save
```

**变体：SubAgent 路径**

```
T+2.SUB  SubAgent handler 接收 parent request
T+3.SUB  继承 parent 的 budget / permission / context
T+4.SUB  SubAgent 复用本 Spine, 但 scope 受 J 节约束
T+5.SUB  SubAgent 完成的 evidence 必须回流到 parent
T+6.SUB  Parent 恢复主 Spine
```

**变体：Fallback / Retry**

- Fallback 仅发生在 *同一条 Spine 内部*，不得形成第二条生产路径。
- 例：L1-attempt → direct inline-local fallback（当前事实）→ V0（target，
  待决策）。

---

## 7. 分层结构与每层职责

| 层 | 文件示例 | 职责 | 禁止 |
|---|---|---|---|
| **User / Input** | `agent/cli/`, `agent/cli_commands.py`, `agent/cli_renderer.py`, 根目录 `tui/` | 接收输入, 渲染输出 | 任何业务决策 |
| **Core** | `agent/core.py` | entry, mode resolve, 提供 chat / delegate / end | 持久化、业务策略 |
| **Runtime Loop** | `agent/loop.py`, `agent/loop_context.py` | turn orchestration, checkpoint, resume | 工具实现细节 |
| **Decision / Plan** | model call + parser in loop | plan & tool_request | 修改状态 |
| **Policy / Guardrails** | `agent/memory_policy.py`, `agent/runtime_integration/phase1_hook.py` | 决策前的 gate | 真实执行 |
| **Dispatcher** | `agent/runtime_integration/dispatcher.py`, `agent/runtime_integration/schema.py` | 统一分发、evidence emit | 业务实现 |
| **Handler / Adapter** | `agent/runtime_integration/*_handler*.py`, `agent/runtime_integration/target_catalog.py` | 域适配 | 跨域决策 |
| **Side effect** | `agent/tool_*.py`, `agent/mcp_*.py`, `agent/memory_*.py`, `agent/runtime_integration/subagent_action.py` | 真实动作 | 重新引入主路径 |
| **Observability** | `agent/runtime_observer.py`（writer，写 `agent_log.jsonl`）, `agent/evidence_recorder.py` | trace/evidence/log | 业务决策 |
| **AI 风险与对抗提示治理** | `agent/runtime_integration/safe_metadata.py`, `agent/mcp_sanitizer.py` | 注入检测、secret masking、untrusted-content 隔离 | 业务实现 |

---

## 8. Core / Runtime / Dispatcher / Handler / Adapter 边界

- **Core** 不得直接调用 Tool / SubAgent；只通过 Runtime Loop。
- **Runtime Loop** 不得直接执行 side effect；只通过 Dispatcher。
- **Dispatcher** 不得包含业务实现；只做路由 + evidence + error。
- **Handler** 不得跨域（tool handler 不写 memory；memory handler 不调
  tool）；只调用 *Adapter*。
- **Adapter** 是该域与外部世界的桥；同一域可有多个 adapter（如
  memory adapter vs memory consolidation adapter）。

> 这条边界过去是 *目标*；`docs/06-audit/POST_REPAIR_AUDIT_DELTA.zh.md`
> 记录了 V4/V5 多次“`subagent_action`/`memory_consolidate` 跨域”风险，
> 本文件是 closure。

---

## 9. Tool / Skill / MCP 的统一能力模型

> Target。`Open:` 三者是否必须共享同一 Capability Contract，**需要用户决定**。

- **能力声明**：
  - `id`, `version`, `schema (input/output)`, `error_model`,
    `idempotency_key_optional`, `permission_class`, `cost_hint`,
    `latency_hint`。
- **Tool**：进程内 Python 实现；`tool_registry` 单一 owner。
- **Skill**：turn-start probe 选出的策略片段；目前作为 *evidence* 存在
  （`RuntimeActionType.SKILL_SELECT`），不直接作为 side effect。
- **MCP**：外部协议适配；进入 Runtime 必须先 wrap 成与 Tool 同 schema
  的内部对象，再走 Dispatcher。
- **统一约束**：
  - 所有 capability 必须有 unit + architecture 边界测试。
  - 所有 capability 写 evidence。
  - capability 的失败不引起 loop 状态机以外的 silent fallback。

---

## 10. Memory 和 Context 的目标模型

### 10.1 分层

> `Open:` 各层的 *canonical write owner* 尚未锁定。下表 owner 列描述的是
> *当前职责拆分的现状*，不是已选定的单一 owner（与 §4.D 一致）。当前
> `agent/memory.py` 负责压缩 / 抽取及部分协调（如 `compress_history`、
> `extract_memories_from_session`），真正的持久化由
> `agent/memory_store.py` / `agent/memory_fs_store.py`
> （`apply_operation_intent` / `store_retained_record`）承担，触发与治理由
> `agent/memory_runtime_hooks.py` + `agent/memory_policy.py` 负责。
> 谁成为各层 canonical owner 属 Repair Roadmap 迁移决策，本文件不预选。

| 层 | 范围 | 当前职责所在（非 canonical owner） | 写入 gate |
|---|---|---|---|
| Working state | 当前 turn | `LoopContext` | Runtime Loop |
| Conversation memory | 本会话 | `memory.py`(协调) → `memory_store`/`memory_fs_store`(持久化) | `DeterministicMemoryPolicy` |
| Long-term memory | 跨会话 | `memory.py`(抽取/协调) → store(持久化)；触发经 `memory_runtime_hooks` | policy + consolidation |
| Provenance | 元数据 | store 持久化时承载；`memory.py` 渲染读取 | 写入时强制 |

### 10.2 Consolidation

- Frozen pipeline (`agent/memory_consolidation_pipeline.py:run_consolidation_pipeline`)
  仍 runtime-reachable；是否在 *目标* 架构下默认 *生产* 路径 **未决定**（§23）。
- Consolidation 写 long-term memory 必须经过 Policy gate。
- `Open:` provenance 字段、conflict 规则、deletion 流程需在 §10 锁定。

### 10.3 Context

- Working state 不进 evidence；只在 LoopContext 内部存在。
- Conversation memory 写入受 Policy gate；失败应 silent-reject 而非
  silent-retain。

---

## 11. SubAgent 的目标模型

> Target。`Open:` V0 是否在 *本* 目标架构中作为生产 SubAgent 主路径。

- **生命周期**：parent-managed；子 agent 启动 = 父 Runtime 调 dispatcher
  → subagent action handler。
- **继承**：budget, permission, tool registry subset, context, trace id。
- **隔离**：子 agent 不直接修改 parent state；只通过 evidence + return
  value。
- **停止条件**：budget 用尽 / 显式 stop / 异常 / 父 Runtime 取消。
- **完成回流**：所有子 agent 完成的 RuntimeActionEvent 必须回流到
  parent 的 evidence 流。
- **当前事实**：inline-local fallback 已是父 Runtime 控制（每次 turn
  单步、bounded、parent-controlled）；V0 handler 已 contract-verified
  但未 routed。
- **目标**：V0 handler 被 *路由* 之前，不算 SubAgent 路径完成；本架构
  *允许* inline-local 作为 production 临时主路径，但记录其作为
  “过渡事实”，并在 wiring 完成后转为 V0。

---

## 12. State, Checkpoint, Persistence, Recovery

### 12.1 状态机

```
idle → running → tool_call → (running | retry | fallback | denied | failed)
                          ↘ suspended → running
                          ↘ cancelled
running → waiting_user → running
running → completed
```

### 12.2 Checkpoint

- Trigger：turn-end 显式 save（`loop.py:_dispatch_turn_end_checkpoint_save`）。
- Schema：`agent/checkpoint.py:CheckpointTruncationConfig` 决定
  truncation；`Inference:` 当前 schema 是事实，但其 *稳定性* /
  *版本化* 仍待审计。
- `Open:` checkpoint 兼容策略（v1→v2 升级、跨进程 resume、跨 host）
  应在 §17 锁定。

### 12.3 Persistence

- 长任务必须可 resume；不允许“所有任务必须一次完成”。
- `Open:` resume 时 evidence 流是否重放、是否打断当前 loop，**未决定**。

---

## 13. Policy, Permission, Guardrail, Human Approval

- **Policy**：`agent/memory_policy.py:DeterministicMemoryPolicy`（memory
  写入），未来如果 tool/skill/subagent 各自引入 policy，应独立 owner。
- **Permission**：由 Dispatcher 在 T+4 调用前的统一检查实现。
- **Guardrail**：mask secrets（`agent/runtime_integration/safe_metadata.py`）、
  secret-like detection（`schema.py:contains_secret_like`）。
- **Human Approval**：`Open:` 是否在 *目标* 架构中保留显式 human
  approval hook（独立于 `MY_FIRST_AGENT_DEBUG=1` 调试路径），
  **需要用户决定**（§23）。

---

## 14. Evidence, Trace, Metrics, Evaluation

- **Evidence**：`RuntimeActionEvent` *类型* 定义在
  `agent/runtime_integration/schema.py`；分类 / 证明逻辑在
  `agent/runtime_integration/evidence.py:classify_evidence_level`；
  持久化在 `agent/evidence_recorder.py`。三者各司其职，不混为一个 owner。
- **Trace**：`agent/runtime_observer.py:log_event` → `agent_log.jsonl`。
- **Metrics**：`Open:` cost / latency 字段是否进入 observability
  surface，**未决定**。
- **Evaluation**：Golden E2E 集合是 *目标*；目前尚无 explicit 集合。
  本文件 §19 锁定测试金字塔。

---

## 15. Error, Retry, Fallback, Cancel, Idempotency

- **Error**：Dispatcher 统一收集 `RuntimeActionResult.status`，取值为 §4.E 列出的
  7 值枚举（`success / rejected / confirmation_required / not_supported /
  failed / skipped / policy_blocked`）。
- **Retry**：必须显式 budget；不允许无限重试。
- **Fallback**：必须 *同一条 Spine 内部*；禁止形成第二条生产主路径。
- **Cancel**：父 Runtime 可取消子 agent / 当前 turn；cancel 写 evidence。
- **Idempotency**：高风险 side effect 鼓励 idempotency key；`Open:` 是否
  把 idempotency key 作为 schema 必须项 **未决定**。

---

## 16. Configuration, Provider, Environment

- **Provider**：LLM provider 是 *内部 adapter*；不主导主路径。
- **Configuration**：环境变量、CLI flag、`.env`、`config.yaml` 各自边界
  必须由 §17 锁定（`Open:`）。
- **Environment boundary**：本项目不接 SaaS、不暴露端口；进程内即部署。
- `Open:` 是否在远期接受 HTTP / RPC 协议，**未决定**（§23）。

---

## 17. Compatibility, Frozen, Deferred, Legacy 生命周期

| 类别 | 定义 | 生命周期 | 治理 |
|---|---|---|---|
| **Active** | 当前主路径 | 滚动迭代 | 严格单 owner |
| **Frozen** | 不再修改、runtime-reachable | 永久保留直到 deprecated | 明确 doc note |
| **Deferred** | 决策待定 | 直至被打开 | 进 Open Decision 列表 |
| **Legacy / Compat** | 仅作下游 / test 使用 | 直至迁移完 | 入口 doc + 删除窗口 |
| **Deprecated** | 已 announce, 进入删除窗口 | 2 个 minor release | 触发删除 review |

> 当前事实：frozen 模块（如 `agent/memory_consolidation_pipeline.py`）
> 通过“docstring 标注 + 单测断言”双重锁（`tests/runtime_integration/test_memory_consolidation_truth.py`）。
> 这是本架构推崇的 *frozen-by-evidence* 模式。

---

## 18. Source-of-truth 层级与文档生成规则

> 本节定义 §1 的 **轴 1 · Runtime Fact axis** 排序（“现在实际怎么跑”谁最权威）；
> 与 §1 轴 2（目标/原则，North Star 最高）互不覆盖、用于不同问题类型。

1. **代码 + 可执行测试** = 运行时事实最高权威。
2. **`docs/06-audit/CURRENT_AUDIT_STATUS.zh.md`** = 现状最高权威（文档侧）。
3. **`docs/06-audit/CURRENT_ARCHITECTURE_REPAIR_ROADMAP.zh.md`** =
   现状→目标的施工计划。
4. **本文件 (North Star)** = 在 *现状事实* 排序中列此位（North Star 不覆盖代码事实）；
   但在 *目标/原则* 轴上是最高权威，见 §1 轴 2。
5. **Capability / Audit Delta 文档** = 单点变更记录。

文档生成规则：不得从 *单一* 旧文档生成结论；所有 current-state 主张
必须用 file/function/test/git 证据。

---

## 19. 测试金字塔：unit, contract, architecture, integration, Golden E2E

| 层 | 目的 | 例子 | 不得做的事 |
|---|---|---|---|
| **Unit** | 函数/类契约 | `tests/unit/test_runtime_decision_frame.py` | 跨层假设 |
| **Contract** | 模块边界 | `tests/runtime_integration/test_subagent_v0_runtime_boundary.py` | 直接测 side effect |
| **Architecture** | 不变量、boundary、SoT | `tests/test_architecture_boundaries.py` | 测功能行为 |
| **Integration** | 端到端流程 | `tests/runtime_integration/test_memory_consolidation_truth.py` | 引入新流程分支 |
| **Golden E2E** | 真实用户路径 | `tests/smoke/`（已存在）→ 应补成显式 Golden E2E | 用 mock 替代 |
| **Adversarial / Safety** | 注入、replay、退化 | `tests/adversarial/`（待补；注入/secret 治理见 §13、§7） | 改 production 行为 |

> `Open:` Golden E2E 集合的 *最小定义* 是什么，**未决定**（§23）。

---

## 20. Architecture Acceptance Rubric

> 每项 0/1/2/3 分。0=未知或未审；1=明显缺失；2=有但不一致；3=满足。
>
> **当前分 = `provisional`（待审）**：本文件 *不* 给出已测量的当前分。各维度
> 实际得分须由一次全仓 *Architecture Gap Audit*（按下表“通过证据 / 不通过示例”
> 逐项取证）产出，再回填。此前任何分数都是占位，不得视为已通过。

| 维度 | 目标定义 | 通过证据 | 不通过示例 | 当前分 | 阈值 |
|---|---|---|---|---|---|
| **Runtime unity** | 单一 Spine 覆盖所有 side effect | 全部 action 经 dispatcher；没有第二条生产主路径 | `agent/core.py` 直接调 tool；L1/L2 handler 注册到生产 dispatcher | `provisional` | 3 |
| **Boundary clarity** | Core/Loop/Dispatcher/Handler/Adapter 各一层不越界 | `loop.py` 不调 tool；dispatcher 不含业务 | handler 写 memory | `provisional` | 3 |
| **SoT consistency** | 每个关键概念单一 owner | `target_catalog` 拥有 target resolution；`safe_metadata` 拥有 mask | `mask_user_visible_secrets` 在多文件 inline 调（已修 D1/D2/D3） | `provisional` | 3 |
| **Side-effect safety** | 5 步 gate（policy/perm/validate/exec/evidence） | 所有 action 写 evidence | silent fallback | `provisional` | 3 |
| **Observability** | 可重建 decision/tool/memory/fallback/error/cost/latency/result | `agent_log.jsonl` + evidence | trace 缺字段 | `provisional` | 3 |
| **Recoverability** | checkpoint + resume + failure recovery | `agent/checkpoint.py` 存在 | resume 协议未定义 | `provisional` | 3 |
| **Memory governance** | policy gate + provenance + lifecycle | `DeterministicMemoryPolicy` | 写 memory 缺 provenance | `provisional` | 3 |
| **Subagent governance** | parent-controlled + bounded | `execute_subagent_delegation` 父控 | V0 未 routed | `provisional` | 3 |
| **Extension cost** | 新能力只通过稳定扩展点加入 | 新增 RuntimeActionType + handler 即可 | 改 Core 主循环 | `provisional` | 3 |
| **Test / evaluation coverage** | 五层金字塔 + Golden E2E | unit / contract / architecture / integration 已有 | 无 explicit Golden E2E | `provisional` | 3 |
| **Compatibility debt** | 显式分类 + 退出窗口 | frozen/legacy 标注存在 | legacy 无删除窗口 | `provisional` | 3 |
| **Documentation accuracy** | docs/runtime fact 一致 | `test_subagent_runtime_truth.py` 锁 SoT | 旧 claim 仍存在 | `provisional` | 3 |

> 评分是 *逐维度* 的 gate，**不取平均**：任何单一维度未过线即不达标，
> 高分维度不能抵消失败维度。全部维度 ≥ 2 才算“架构基本成型”；全部 ≥ 3
> 才算“完成 Architecture Repair Done”（见 §21）。

---

## 21. Architecture Repair Definition of Done

**不等于**：TODO 清零 / frozen 删除 / 全文件变短 / 全仓 lint 零问题。

**等于**：

1. 无违反核心架构不变量的 Blocker / High。
2. 所有真实 production path 均符合目标 Runtime Spine。
3. 所有 Medium 已 *修复* 或 *有明确 owner + 风险 + 退出条件 + 下一步*。
4. 关键路径通过 Golden E2E。
5. capability / docs / runtime fact 一致。
6. 新能力只通过稳定扩展点加入，*不*修改 Core 主循环。
7. 剩余 deferred 不再制造双主路径或双 source of truth。
8. Rubric（§20）每个维度 ≥ 2（逐维度 gate，不取平均）。
9. 所有 `Open:` 决策有 owner + 退出条件。

> DoD 只绑定 *架构不变量 / 运行证据 / Golden E2E / SoT 一致性 / 受治理的
> deferred debt*；**不** 绑定任何具体历史计划的合并状态（如某批 U1–Un）。
> 施工进度（含 Plan `2026-06-12-001` 的 U1–U7）由 Repair Roadmap 跟踪，
> 不进入本架构 DoD。

---

## 22. 当前架构与目标架构的初步差距摘要

> 全部属于 `Migration State`。`Fact:` 是已发生事实；`Gap:` 是
> 仍需迁移的部分。

| 主题 | 现状（Fact / Inference） | 目标 | Gap |
|---|---|---|---|
| SubAgent | V0 registered + contract-verified, NOT production-routed；live 走 inline-local fallback | V0 production-routed, inline-local 退为 fallback | 需要 V0 wiring 决策（已挂 Open） |
| Safe metadata | D1/D2/D3 已落地；projector 是单一 surface | 全部 inline re-import 清零 | 待修复遗留 inline re-import（如有） |
| Memory consolidation | frozen + runtime-reachable | 默认 production 路径 *待定* | 决策 pending（§23） |
| MCP | 多文件、协议适配 | 与 Tool 共享 capability contract | 决策 pending（§23） |
| Checkpoint | save 已落地，resume 协议未锁 | stable resume + 跨 host 兼容 | 决策 pending（§23） |
| Golden E2E | 无显式集合 | 锚定 Golden E2E 集合 | 决策 pending（§23） |
| Capability drift | 已 audit，未根除 | 文档/runtime fact 自动一致 | 持续 CI 化 |
| Cost / Latency | observability 未包含 | cost / latency 字段纳入 | 决策 pending（§23） |
| Human approval | 调试路径 | production 显式 hook | 决策 pending（§23） |

---

## 23. 尚待用户确认的架构决策（Open Decisions）

> 每条都给出 *最小选项* 与影响；最终决定属项目 owner。

1. **OD-1**：V0 是否在 *本* 目标架构中作为 *生产* SubAgent 主路径？
   - 选项 A：保留 inline-local fallback 作为过渡事实，目标架构仍以
     inline-local 为主路径（V0 仅 registered）。
   - 选项 B：V0 wiring 至 production；inline-local 退为 fallback，
     不再作主路径。
   - 影响：决定 SubAgent 主路径的 canonical 形式（影响 §11）。

2. **OD-2**：Tool / Skill / MCP 是否共享统一 Capability Contract？
   - 选项 A：各自独立 schema，Dispatcher 统一 evidence + 错误模型即可。
   - 选项 B：三者必须导出统一 Capability Contract。
   - 影响：决定 §9 与 §18 的 source-of-truth 粒度。

3. **OD-3**：是否在远期接受 HTTP / RPC 远程 client 协议？
   - 选项 A：维持进程内单一部署单位。
   - 选项 B：增加 RPC 协议层；Core 边界扩展。
   - 影响：决定 §1 / §16 的边界。

4. **OD-4**：Consolidation pipeline 是否为默认 production 路径？
   - 选项 A：维持 frozen + runtime-reachable，但默认不走。
   - 选项 B：解锁为默认 long-term memory 写路径。
   - 影响：决定 §10 的 governance 强度。

5. **OD-5**：Golden E2E 集合的最小定义？
   - 选项 A：以 `tests/smoke/` 为 baseline，补 1–2 个 real-user 路径。
   - 选项 B：定义 explicit 5 路径 Golden E2E。
   - 影响：决定 §19 的可执行下限。

6. **OD-6**：Cost / Latency 是否进入 observability 必填字段？
   - 选项 A：可填字段，evidence 记录 best-effort。
   - 选项 B：必填字段，缺则拒绝写。
   - 影响：决定 §14 / §20 的过线条件。

7. **OD-7**：Human approval hook 是否进入 production 主路径？
   - 选项 A：仅作为调试路径，不进入 dispatcher。
   - 选项 B：高风险 side effect 强制 hook。
   - 影响：决定 §13 / §15 的过线条件。

8. **OD-8**：Checkpoint 兼容策略与 resume 协议？
   - 选项 A：进程内、单 host、schema vN→vN+1 forward 兼容。
   - 选项 B：跨 host、跨进程、跨版本；要求 stable identity。
   - 影响：决定 §12 / §17 的可达性。

---

## 24. 明确 Non-Goals

- **不是** 多 agent 协作平台 / multi-tenant runtime。
- **不是** model gateway / inference proxy；LLM 调用是内部能力。
- **不是** 低代码 / prompt-app framework；不接受把 prompt 升级为产品。
- **不是** SaaS，不带 HTTP / RPC 接口（除非用户选 OD-3 = B）。
- **不是** web / mobile / TUI-only 产品；TUI / CLI 是当前入口，未来不
  引入新协议除非用户决定。
- **不会** 为模仿外部 framework（LangGraph / AutoGen / CrewAI / LangChain）
  引入 planner / reflection / multi-agent 抽象，除非评测证据要求。
- **不会** 让 frozen 模块复活作为 production 路径。
- **不会** 在本文件之外的位置重新定义相同概念；本文件是 single
  source of truth（§18）。
- **不会** 把 “当前 fallback” 自动定义为目标架构。
- **不会** 在没有评测证据时增加复杂度（原则 A）。

---

## 附录 A：本次起草使用的证据集

- `agent/core.py:763 chat()` — Core 入口事实。
- `agent/loop.py:920+` — Runtime Loop turn-end 编排事实。
- `agent/loop.py:102 _dispatch_tool_pipeline` — Tool dispatch 路径事实。
- `agent/runtime_integration/dispatcher.py:RuntimeActionDispatcher` — 统一
  dispatcher 事实。
- `agent/runtime_integration/phase1_hook.py:build_phase1_dispatcher` —
  Phase-1 handler 注册事实。
- `agent/runtime_integration/schema.py:RuntimeActionType` — action enum
  事实。
- `agent/runtime_integration/target_catalog.py:RuntimeActionTargetCatalog` —
  target resolution single-owner 事实。
- `agent/runtime_integration/safe_metadata.py` — safe metadata projector
  事实（D1/D2/D3 已落地）。
- `agent/runtime_integration/evidence.py` — evidence classification
  single-owner 事实。
- `agent/subagent_inline.py:execute_subagent_delegation` — live inline-local
  fallback 事实。
- `agent/runtime_integration/subagent_action.py` — V0 / L0 / L1 / L2
  handler 集合事实。
- `agent/runtime_decision_frame.py:RuntimeDecisionFrame` — SoT schema
  事实。
- `agent/runtime_observer.py` — observability 事实。
- `agent/checkpoint.py:save_checkpoint` / `load_checkpoint` — recovery
  事实。
- `agent/memory.py`, `agent/memory_policy.py` — memory 治理事实。
- `agent/memory_consolidation_pipeline.py:run_consolidation_pipeline` —
  consolidation frozen 事实。
- `agent/tool_registry.py` / `agent/mcp_*.py` / `agent/skills/` —
  capability surface 事实。
- `tests/runtime_integration/test_subagent_runtime_truth.py` — SoT lock
  test 事实。
- `tests/runtime_integration/test_memory_consolidation_truth.py` —
  frozen+reachable 锁测试事实。
- `docs/06-audit/CURRENT_ARCHITECTURE_REPAIR_ROADMAP.zh.md` — 施工计划。
- `docs/06-audit/CURRENT_AUDIT_STATUS.zh.md` — 现状权威。
- `docs/06-audit/POST_REPAIR_AUDIT_DELTA.zh.md` — 修复 delta。
- `docs/06-audit/CURRENT_CAPABILITY_DRIFT.zh.md` — capability drift
  跟踪。
- `docs/06-audit/V0_WIRING_DECISION.zh.md` — V0 决策上下文。
- `docs/06-audit/TARGET_CATALOG_REEXPORT_AUDIT.zh.md` — U4 审计事实。
- `docs/plans/2026-06-12-001-fix-architecture-repair-sot-truth-plan.md` —
  U1–U7 实施 plan（只读）。

> **本文件创建期间**：没有修改任何 production code、没有修改任何测试、
> 没有修改 `CURRENT_ARCHITECTURE_REPAIR_ROADMAP.zh.md`、没有修改现有
> plan、没有触碰或提交 `AGENTS.md`、没有 `git add` / `commit` / `push`。
> Pre-existing dirty state（`AGENTS.md`、`docs/plans/`）原样保留。
