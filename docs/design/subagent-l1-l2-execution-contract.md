# SubAgent L1/L2 Execution Contract — Loop 3.2 SDD

日期：2026-05-28
状态：architecture decision complete / implementation pending
上一版设计文档：`docs/design/subagent-boundary-architecture.md`（L0 架构）

---

## 1. 当前真实状态（诚实评估）

### 1.1 当前 SubAgent 是什么

| 项目 | 实际状态 |
|------|---------|
| 执行器 | `execute_local()` — 完全 deterministic，keyword-matching 返回 hardcoded summary |
| provider 调用 | **无** — L0 executor 明确"不调用 provider" |
| 工具执行 | **无** — `tool_requests=()` 永远为空 tuple |
| memory 写入 | **无** — `memory_proposals_count=0` |
| child loop | **无** — 一次 `delegate_once()` = 一次 `execute_local()`，不做迭代 |
| provider 继承 | **无** — `execution_mode="local_fake"` 硬编码，`model="fake"` 强制 |
| parent-mediated tool use | **设计存在，未实现** — ToolBoundary/MemoryBoundary/SkillBoundary 对象定义了但 L0 executor 不使用 |
| dispatcher evidence | **probe only** — `SUBAGENT_DELEGATE_L0` 分类为 probe；turn-end hook 返回 `failed`（无 delegate intent）；CLI shortcuts 绕过 dispatcher |
| RuntimeDecisionFrame | `subagent.delegate` → `FAKE_DEMO`，证据等级 `FAKE_LOCAL_USER_PATH` |
| 红队补审结果 | **0/5 COMPLETE** — 5 项全部降级（DEMO/FAKE_ONLY/STUB/NOT_STARTED） |

### 1.2 哪些 evidence 是 fake / demo / direct-call / no-crash

| Test/Suite | 实际验证 | 不可支撑 COMPLETE 的原因 |
|-----------|---------|------------------------|
| `test_subagent_bounded_execution.py` | L0 executor 不 crash | no-crash ≠ 业务能力 |
| `test_subagent_parent_adapter.py` | `delegate_once()` 调用链不断 | direct-call，非 dispatcher-mediated |
| `test_subagent_cli_tui.py` | CLI delegate 命令渲染 | CLI shortcut，绕过 dispatcher |
| `test_subagent_descriptor_schema.py` | frontmatter 解析 | DOC_GUARD_ONLY |
| `test_subagent_registry.py` | registry 扫描 | DOC_GUARD_ONLY |
| `test_subagent_memory_boundary.py` | MemoryBoundary 对象 | SUBSYSTEM_DIRECT_CALL — boundary 对象存在但未被真实 child loop 使用 |
| `test_subagent_tool_boundary` (if exists) | ToolBoundary 权限检查 | SUBSYSTEM_DIRECT_CALL |
| Trun-end SUBAGENT_DELEGATE_L0 dispatch | probe：返回 failed（no suitable subagent） | probe ≠ 业务能力 |

---

## 2. L0 / L1 / L2 定义

### 2.1 L0 — Deterministic Executor（当前已实现）

```
delegate_once(request, registry)
  → build_context_package()
  → execute_local()          # 不调 provider，不执行工具，不写 memory
  → adjudicate_result()      # 返回 accept/reject/revision
  → SubAgentRun
```

**特征**：
- 不调用任何 provider
- 不执行任何工具（`tool_requests=()` 永远是空）
- 不写 memory（`memory_proposals_count=0`）
- 不做迭代（`delegate_once` = 1 次调用）
- summary 由 `_deterministic_outcome()` keyword-matching 生成
- execution_mode 固定为 `local_fake`

**honest label**：FAKE_DEMO — 这不是 SubAgent，是 command alias

### 2.2 L1 — Parent-Mediated Child Loop

```
delegate_l1(request, registry, *, parent_dispatcher, provider)
  → build_child_context()
  → 进入 child turn loop:
      1. provider.chat(child_messages)       # child 调真实 provider
      2. 解析 provider response:
         a. text → 累积到 child context
         b. tool_use → parent-mediated:
            - child 向 parent 发起 tool request
            - parent 通过现有 ToolRuntimeMediator pipeline 执行:
              TOOL_GATE → TOOL_INVOKE → execute_single_tool → TOOL_RESULT
            - parent 返回 tool_result 给 child
            - 所有 tool execution 有 dispatcher evidence
         c. stop → exit child loop
      3. parent 记录 child trace events
  → parent adjudication → 结果回流 parent main loop
```

**L1 特征**：
- child 调用真实 provider（继承 parent provider config）
- child **不直接执行工具** — 所有工具执行通过 parent ToolRuntimeMediator
- child 可以写 memory proposal（经 parent confirm→retain pipeline）
- child 可以做多轮迭代（受 max_iterations 限制）
- child 有 memory scope（read_context / propose）
- child 有 skill scope（parent 提供 allowed_skills 列表）
- 所有 child action 有 dispatcher evidence（新的 RuntimeActionType）
- parent 保持 execution control：可在任意时刻终止 child loop

### 2.3 L2 — Autonomous Child with Parent Adjudication

L2 在 L1 基础上增加：
- child 有独立 stop condition 判断（不只靠 max_iterations）
- child result 需 parent adjudication（accept/reject/request_revision）后才进入 parent context
- child 可请求 parent 做 revision（parent 返回 revised context 给 child）
- child 可做 nested file read / code search（受 allowed_tools 约束）
- child memory proposals 可以 batch 提交

**L2 不在 Loop 3.2 scope** — L2 需要 L1 完整实现 + explicitly authorized real-provider validation 后才能设计。

---

## 3. 统一 main runtime path 设计

### 3.1 入口：dispatcher-mediated delegation only

**设计决策**：SubAgent delegation 必须走 dispatcher，CLI shortcuts 迁入 dispatcher path。

```
core.chat() → loop.turn_end → dispatcher.route(SUBAGENT_DELEGATE_L1)
  → SubAgentDelegateL1Handler.handle()
    → delegate_l1() → SubAgentRun → parent adjudication
```

不再存在 CLI shortcut 绕过 dispatcher 的路径。CLI delegate 命令（`delegate to <name>: <task>`）在 core.py 中构建 `RuntimeActionRequest`，通过 dispatcher 统一分发。

### 3.2 Parent-Child 边界

| 边界 | Parent 侧 | Child 侧 |
|------|----------|---------|
| provider | 持有真实 provider config | **继承** parent provider（不独立配置） |
| Tool | 通过 ToolRuntimeMediator 执行 | **请求** tool execution，不直接调用 `execute_single_tool` |
| Memory | 持有 memory_runtime + store | 通过 parent confirm→retain pipeline **提案** |
| Skill | 持有 skill_registry + _active_skill | parent 提供 allowed_skills metadata，child **不可**独立 load skill |
| dispatcher | 持有 RuntimeActionDispatcher | child action 通过 parent dispatcher 记录 |
| checkpoint | save/load 控制权 | **无权** save/load checkpoint |

### 3.3 Child Provider 继承

```python
# Child 不独立配置 provider
child_provider = parent.provider  # 同一个 instance，或同配置的新 instance
# Child 不读 config/config.yaml
# Child 不设环境变量
```

### 3.4 Child Tool 执行路径

```
child provider response: tool_use(name="read_file", input={path: "..."})
  ↓
SubAgentL1Executor.parse_response()
  ↓
child 构建 SubAgentToolRequest(name, arguments)
  ↓
parent ToolRuntimeMediator.mediate_child_tool_request(
    tool_name, arguments,
    delegation_id=child_run.delegation_id,
    parent_trace_id=...
)
  ↓
parent dispatcher.route(TOOL_REQUEST)
  → TOOL_GATE (child_allowed_tools enforcement)
  → TOOL_INVOKE → execute_single_tool → TOOL_RESULT
  ↓
parent 返回 SubAgentToolResult 给 child
  ↓
child 将 tool_result 注入 child context
  ↓
child 继续 loop 或 stop
```

**关键 invariant**：
- child **永远不**直接调用 `execute_single_tool()`
- 所有 tool execution 走 parent `ToolRuntimeMediator`
- blocked tool 在 TOOL_GATE 被拦截 → child 收到 blocked result → child 记录 warning
- Skill allowed_tools enforcement 在 TOOL_GATE 层对 child tool request 同样生效

### 3.5 Child Memory Scope

| Scope | 行为 |
|-------|------|
| `none` | child 完全隔离，不可读不可写 |
| `read_context` | parent 在 delegation 开始前通过 dispatcher 做 MEMORY_RECALL，结果以 frozen snapshot 注入 child context；child 不可修改 |
| `propose` | child 可提出 MemoryProposal → parent MEMORY_PROPOSE → confirm pipeline → retain |

### 3.6 Child Skill Scope

- parent 在 delegation 开始前从 `active_skill` 或 descriptor.allowed_skills 提取 skill metadata
- child context 注入 `[Available Skills]` section（类似 prompt_builder.build_skills_section()）
- child **不可**独立 invoke skill — skill execution 也走 parent-mediated 路径

### 3.7 Dispatcher / RuntimeAction Evidence

需要新增 RuntimeActionType（分类均为 business）：

| RuntimeActionType | 含义 | 何时 dispatch |
|------------------|------|-------------|
| `SUBAGENT_DELEGATE_L1` | parent 发起 L1 delegation | `delegate_l1()` 入口 |
| `SUBAGENT_CHILD_TOOL_REQUEST` | child 请求 tool execution | child loop 中解析到 tool_use |
| `SUBAGENT_CHILD_RESULT` | child 完成执行，返回 summary | child loop 退出 |
| `SUBAGENT_PARENT_ADJUDICATION` | parent 裁决 child result | `adjudicate_result()` 后 |

现有 `SUBAGENT_DELEGATE_L0` 保持 probe 分类不变 — L0 仍是 deterministic 非业务路径。

---

## 4. TDD / Test Intent

### 4.1 需要哪些测试证明不是 fake/demo/direct-call

| Test | 验证 | 防止什么误判 |
|------|------|------------|
| `test_l1_child_calls_real_provider` | child loop 调 `provider.chat()`，返回非 deterministic summary | 防止 L0 deterministic summary 冒充 L1 |
| `test_l1_child_tool_request_parent_mediated` | child tool_use → parent TOOL_GATE→TOOL_INVOKE→TOOL_RESULT → child 收到 result | 防止 child 直接调 `execute_single_tool` |
| `test_l1_child_blocked_tool_not_executed` | child 请求不在 allowed_tools 中的工具 → TOOL_GATE rejected → 不进 execute_single_tool | 防止 tool boundary 只在 docs/registry 存在 |
| `test_l1_child_dispatcher_evidence` | 所有 child action 在 dispatcher action_log 有对应条目 | 防止 CLI shortcut 绕过 dispatcher |
| `test_l1_child_memory_propose_through_parent` | `memory_scope=propose` → child proposal → parent MEMORY_PROPOSE → confirm → retain | 防止 child 直接写 store |
| `test_l1_child_inherits_parent_provider` | child 使用与 parent 相同的 provider instance/config | 防止 child 独立配置 provider |
| `test_l1_child_skill_scope_enforced` | child 有 active_skill 时 allowed_tools 受约束 | 防止 child 绕过 Skill enforcement |
| `test_l1_child_no_direct_checkpoint_access` | child 无权 save/load checkpoint | 防止 child 绕过 checkpoint governance |
| `test_l1_not_fakeable` | L1 result 不是 deterministic keyword-match | 防止 deterministic summary 冒充真实 child execution |

### 4.2 测试 evidence 等级

所有 L1 测试初始 evidence level 至少需要：
- `route_from_runtime_loop()` provenance（L3）
- 真实 provider 参与（不能是 FakeProvider）
- 业务 disposition（allowed/executed/success）不是 probe/rejected/noop

真实 provider validation 曾登记为 REAL-EVIDENCE-006；这是历史上下文，不是当前 source of truth。

---

## 5. 实现范围

### 5.1 Loop 3.2a — L1 Code Path（最小可验证切片）

**文件变更**：
- `agent/subagent_system/executor.py` — 新增 `execute_l1()` 或扩展 `execute_local()` 支持 L1 mode
- `agent/subagent_system/delegation.py` — 新增 `delegate_l1()` 
- `agent/runtime_integration/schema.py` — 新增 4 个 RuntimeActionType
- `agent/runtime_integration/subagent_action.py` — handler 更新支持 L1
- `agent/runtime_integration/phase1_hook.py` — 注册新 handler
- `agent/tool_runtime_mediator.py` — 新增 `mediate_child_tool_request()`（复用现有 pipeline）
- `agent/core.py` — CLI delegate shortcut 迁入 dispatcher path
- `agent/runtime_decision_frame.py` — `subagent.delegate` 从 FAKE_DEMO → PARTIAL
- `tests/runtime_integration/test_subagent_l1_parent_mediated.py` — NEW

**不在 scope**：
- 真实 SubAgent L2
- child checkpoint
- child 独立 provider 配置
- child 独立 skill load

### 5.2 Prerequisite — CLI Shortcut 迁入 Dispatcher

在实现 L1 之前，必须先将 CLI delegate shortcut 迁入 dispatcher path：
- `core.py` 中 `detect_delegate_to_subagent` / `detect_nl_delegation` → 构建 `RuntimeActionRequest`
- 通过 `dispatcher.route_from_runtime_loop(SUBAGENT_DELEGATE_L1)` 分发
- 移除直接 `_execute_subagent_delegation()` 调用

这消除第二 runtime path，是 L1 的前置条件。

---

## 6. 状态标记

### 6.1 什么状态只能标 PARTIAL

- L1 code path 完成但无 real provider child loop validation
- Tool boundary 有代码但 child 未实际调用 parent-mediated tool execution
- Memory scope 有代码但 child 未实际通过 parent confirm→retain pipeline
- dispatcher evidence 有但 child result 是 deterministic 的

### 6.2 Code Path Complete 条件

- child loop 调 parent provider
- child tool_use → parent TOOL_GATE→TOOL_INVOKE→TOOL_RESULT → child 收到 result
- child blocked tool 不进 execute_single_tool
- child memory proposal → parent pipeline
- child skill scope 在 TOOL_GATE enforcement
- CLI delegate shortcut 迁入 dispatcher path
- 所有 action 有 dispatcher evidence（action_log 条目）

### 6.3 Real Evidence Debt

- **REAL-EVIDENCE-006**：真实 provider child loop + parent-mediated tool execution + memory scope roundtrip（historical validation caveat；不作为当前 source of truth）

---

## 7. 与已有子系统的边界不变式

### 7.1 Tool runtime

- child 不引入新 tool pipeline — 复用 `ToolRuntimeMediator` → TOOL_GATE→TOOL_INVOKE→TOOL_RESULT
- Skill allowed_tools enforcement 对 child tool request 同样生效
- MCP tools 对 child 不可见（MCP 默认 disabled）

### 7.2 Memory runtime

- child 不持有 MemoryStore reference
- child memory proposal → parent MEMORY_PROPOSE RuntimeActionType → 已有 confirm→retain pipeline
- 不引入 child 独立 memory store

### 7.3 Skill runtime

- child 不可 invoke skill
- child 不可 load SkillRegistry
- child context 中的 skill metadata 是 parent 提供的 frozen snapshot

### 7.4 Checkpoint

- child 不可 save/load checkpoint
- child loop 中断 → parent checkpoint（已有 `CHECKPOINT_SAVE`）

### 7.5 Provider

- child 继承 parent provider instance
- child 不读 config/config.yaml
- child 不读 .env

---

## 8. 参考

- SubAgent L0 架构：`docs/design/subagent-boundary-architecture.md`
- RuntimeDecisionFrame：`agent/runtime_decision_frame.py` §subagent.delegate
- 当前状态入口：`docs/PROJECT_STATUS.md`
- 当前审计入口：`docs/06-audit/CURRENT_AUDIT_STATUS.zh.md`
- 统一 Runtime Flow 合约：`docs/real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md`
- 当前状态入口：`docs/PROJECT_STATUS.md`
