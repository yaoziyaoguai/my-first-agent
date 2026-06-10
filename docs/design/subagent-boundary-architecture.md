# SubAgent Boundary Architecture

日期：2026-05-27
状态：current — 描述 SubAgent 系统当前架构、边界和已知限制

---

## 1. 架构概览

SubAgent 系统位于 `agent/subagent_system/`，提供 parent-controlled L0 deterministic delegation。

### 核心组件

| 模块 | 职责 |
|------|------|
| `descriptor.py` | SubAgentDescriptor — name/role/allowed_tools/risk_level/max_iterations |
| `registry.py` | SubAgentRegistry — descriptor 加载和查询 |
| `request.py` | SubAgentRequest — 委托请求参数对象 |
| `delegation.py` | delegate_once() — 一次委托的完整执行 |
| `executor.py` | execute_local() — L0 deterministic executor（不调 LLM） |
| `adjudication.py` | adjudicate_result() — parent 对 subagent 结果的裁决 |
| `context.py` | build_context_package() — subagent 执行的上下文构建 |
| `*_boundary.py` | tool/memory/skill 边界隔离机制 |

### 执行流

```
SubAgentRequest → delegate_once() → execute_local() → SubAgentRun → adjudication → 结果回流 parent
```

---

## 2. 两条委托路径

### Path A: Turn-end hook dispatcher (SUBAGENT_DELEGATE_L0)

loop.py 的 turn-end hook 在处理模型输出时，如果检测到 delegation intent，
通过 RuntimeActionDispatcher 分发 SUBAGENT_DELEGATE_L0 action：

```
loop.py → dispatcher.route(request) → SubAgentDelegateL0Handler → delegate_once()
```

证据等级：L3 (REAL_CORE_LOOP_RUNTIME_E2E)，因为走 `route_from_runtime_loop()` 路径。

### Path B: CLI meta-command shortcut

core.py 的 chat() 函数在主循环前检测 CLI delegation 命令（`delegate to <name>: <task>` 格式
或 NL delegation fixture），直接调用 `_execute_subagent_delegation()` → `delegate_once()`：

```
core.py → detect_delegate_to_subagent/nl_delegation → _execute_subagent_delegation() → delegate_once()
```

证据等级：L2 (HARNESS_RUNTIME_E2E)，因为绕过 RuntimeActionDispatcher，不走 `route_from_runtime_loop()`。

---

## 3. 已知限制

### 3.1 L0 deterministic executor only

SubAgent 当前只支持 L0 deterministic execution（`execute_local()`），不涉及真实 LLM 调用。
所有 subagent 行为是 rule-based，功能更接近"命令别名"而非"子代理"。

**原因**：L1+ delegation（真实 LLM child）需要：
- Child LLM provider 配置和管理
- Child context/session 隔离
- Cost/budget 治理
- 更复杂的 adjudication 管线

**当前决策**：L0 是设计选择，不是能力缺失。在 parent runtime 的 confirmation pipeline
和 provider governance 足够成熟之前，不升级 delegation level。

### 3.2 CLI shortcuts 绕过 dispatcher

`detect_delegate_to_subagent` 和 `detect_nl_delegation` 在 core.py 的 chat() 主循环前
直接执行委托，绕过 RuntimeActionDispatcher。

**原因**：Loop 4 (Runtime Entry Consolidation) 将 MUTATING/DELEGATING CLI 命令延后，
等待 confirmation pipeline 就绪。当前 dispatcher 的 SubAgentDelegateL0Handler 要求
`parent_adjudication_required=True`，CLI shortcuts 缺乏此上下文。

**迁移路径**：
1. confirmation pipeline 就绪后，在 core.py 中构建 RuntimeActionRequest
2. 通过 `_p1_dispatcher.route(request)` 统一分发
3. 移除直接的 `_execute_subagent_delegation()` 调用
4. 所有 subagent delegation 证据等级升级为 L3

### 3.3 Boundary 只在 fake 下验证

tool/memory/skill boundary 隔离机制定义了但只在 fake/L0 环境下测试。
Real API 下的 boundary 行为（特别是 child LLM 绕过 boundary 的风险）未验证。

**影响**：当前不可见，因为 L0 executor 是 deterministic 的，不存在绕过风险。
升级到 L1+ 时需重新评估。

---

## 4. 边界隔离

SubAgent 系统实施三层边界隔离：

### Tool boundary (`tool_boundary.py`)
- SubAgentDescriptor.allowed_tools 定义允许工具白名单
- SubAgentRequest.allowed_tools 请求工具必须 ⊆ descriptor.allowed_tools
- shell/external process 工具被硬阻止（`_SHELL_LIKE_TOOLS`）
- 隐藏的内部工具从不暴露给 subagent

### Memory boundary (`memory_boundary.py`)
- memory_scope="none"：完全隔离，不可读写 parent memory
- memory_scope="read_context"：只读快照，不可写入
- memory_scope="propose"：proposal 经 governance 检查后路由到 parent

### Skill boundary (`skill_boundary.py`)
- Skill 只读 L1 metadata，不可 invoke
- Skill 白名单由 descriptor.skill_scope 控制

---

## 5. Demo Descriptors

`agent/subagent_system/descriptors/` 中的 demo descriptors：

| Descriptor | 用途 |
|------------|------|
| `demo-stat.yaml` | 文件统计（DEMO-ONLY） |
| `code-reviewer.yaml` | 代码审查（DEMO-ONLY） |

这些 descriptors 是 demo fixture，不是产品能力。真实 product path 下的 subagent
应通过 agent-level planner/confirmation 管线定义，而非 YAML descriptor。

---

## 6. 参考

- 当前状态入口：`docs/PROJECT_STATUS.md`
- 当前审计入口：`docs/06-audit/CURRENT_AUDIT_STATUS.zh.md`
- Historical Loop 4 completion record has been removed during repository cleanup; use `docs/PROJECT_STATUS.md` for current boundaries.
- SubAgentDelegateL0Handler：`agent/runtime_integration/subagent_action.py`
- CLI delegation detection：`agent/cli_commands.py` → `detect_delegate_to_subagent` / `detect_nl_delegation`
