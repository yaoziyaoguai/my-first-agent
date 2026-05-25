# Architecture Decision: SubAgent L0→L1 Real Delegation

Date: 2026-05-25
Status: decided
References: agent/subagent_system/, UNIFIED_RUNTIME_FLOW_CONTRACT.md

## 1. Problem Statement

当前 SubAgent 执行引擎位于 `executor.py`，`execute_local()` 通过 keyword matching
决定 deterministic 结果。这在 L0（本地、确定性、无 provider、无工具执行）下是正确的。

但 `execution_mode.py` 已经定义了三种高阶模式：
- `REAL_LLM_READONLY` — 通过 provider 调用真实 LLM，但不执行工具
- `REAL_LLM_TOOL_REQUESTING` — LLM 可请求工具，由 parent 裁决后执行
- `SANDBOXED_TOOL_CAPABLE` — 沙箱内自主工具执行

这些模式的 policy gate（`policy.py:SubAgentPolicy`）默认全部关闭。问题是：当前
`execute_local()` 与高阶模式之间存在**结构性断裂**——keyword matching 无法
"逐步演进"为 LLM-based execution。需要明确 L0→L1 的替换策略。

## 2. 当前状态分析

### 2.1 L0 边界已严格执行

从代码审计确认：
- `execute_local()` — 不调用 provider、不执行工具、不 spawn 外部进程
- `policy.py:SubAgentPolicy` — 所有高阶 gate 默认 `False`
- `execution_mode.py:LOCAL_EXECUTION_MODES` — 显式声明 L0 可用模式
- `request.py` — `security_envelope` 约束 nested delegation、shell 等

### 2.2 已有 L1 基础设施

| 组件 | 状态 | 说明 |
|------|------|------|
| `SubAgentExecutionMode` enum | ✅ | 五种模式已定义，含三种高阶模式 |
| `SubAgentPolicy` gate | ✅ | 按模式分 gate，默认全关 |
| `select_execution_mode()` | ✅ | 三重校验（request × descriptor × policy） |
| `executor.py` | ❌ | 只有 `execute_local()`，无 L1 code path |
| `delegation.py` | ❌ | `delegate_once()` 硬编码调用 `execute_local()` |

### 2.3 L0→L1 不可渐进演进

`execute_local()` 的核心逻辑是 `_deterministic_outcome()`——一个基于 keyword
matching 的纯函数。LLM-based execution 需要完全不同的输入（provider、tool registry、
system prompt、message history）和完全不同的输出处理（streaming、tool call
decoding、迭代控制）。让 keyword matching 和 LLM execution 共存于同一个函数
会导致不可维护的 if/else 分支。

**结论：L1 executor 必须是独立模块，替换而非演进。**

## 3. Decision

### 3.1 替换策略：Strategy Pattern with Execution Mode Dispatch

```
delegate_once(request, registry)
  → select_execution_mode(request, descriptor, policy)  # 已存在
  → dispatch to executor by mode:
      LOCAL_FAKE / LOCAL_DETERMINISTIC → execute_local()   # 现有
      REAL_LLM_READONLY                → execute_real_llm_readonly()
      REAL_LLM_TOOL_REQUESTING         → execute_real_llm_tool_requesting()
      SANDBOXED_TOOL_CAPABLE           → execute_sandboxed()
```

**不做：** 在 `execute_local()` 里加 if/else 分支。
**要做：** 新增独立 executor 模块，通过 mode dispatch 选择。

### 3.2 新增模块

```
agent/subagent_system/
├── executor.py          # 重构为 dispatch hub，mode → executor 映射
├── executor_local.py    # 现有 execute_local() 移入
├── executor_l1.py       # 新：REAL_LLM_READONLY + REAL_LLM_TOOL_REQUESTING
└── executor_sandbox.py  # 新：SANDBOXED_TOOL_CAPABLE（后续阶段）
```

### 3.3 L1 Executor 合约

`executor_l1.py` 的 `execute_real_llm_readonly()` 和
`execute_real_llm_tool_requesting()` 必须满足以下合约：

| 约束 | 要求 |
|------|------|
| Provider | 通过 `context_package.provider` 注入，不自行创建 |
| Tool Registry | 只使用 `descriptor.allowed_tools` 子集 |
| System Prompt | 由 `context_package.system_prompt` 提供，不从 config 读取 |
| Budget | `max_iterations` 从 descriptor 读取，上限由 `SubAgentPolicy` 强制 |
| Nested Delegation | **禁止**，与 L0 相同 |
| Memory | 可读取 snapshot，不写入（proposal 由 parent 裁决） |
| Tool Execution | 只对 `REAL_LLM_TOOL_REQUESTING` 模式开放，且 parent 必须先 adjudicate |
| Stop Reason | 必须返回 `SubAgentStopReason` 枚举值 |
| Result | 必须返回兼容的 `SubAgentResult`，填满 `audit` 字段 |

### 3.4 Gate 解锁路径

按风险递增解锁：
1. **REAL_LLM_READONLY** — 最低风险，LLM 只能读不能写
2. **REAL_LLM_TOOL_REQUESTING** — 中等风险，LLM 可请求工具但 parent 最终裁决
3. **SANDBOXED_TOOL_CAPABLE** — 高风险，需 worktree isolation + 沙箱

每个 gate 解锁需要：
- Policy gate 显式 `True`
- Descriptor 的 `supported_modes` 包含该模式
- Request 的 `execution_mode` 显式指定该模式
- 对应的 executor 模块已实现
- L3 evidence（focused test 覆盖 happy path + security boundary）

### 3.5 当前阶段不实现 L1 Executor

本 AD 定义替换策略和合约，**不实现代码**。原因：
- L0 已满足当前 MVP 需求（demo-stat 等 SubAgent 使用 keyword matching 即可）
- 实现 `executor_l1.py` 需要 provider 依赖和 L3 evidence，属于后续 stage
- 先把架构路径定义清楚，避免将来实现时走错方向

## 4. Impact

- `executor.py` 重构为 dispatch hub：提取 `execute_local()` 到 `executor_local.py`
- 新增 `executor_l1.py` 和 `executor_sandbox.py` 骨架（后续阶段填充）
- `delegation.py` 的 `delegate_once()` 改为 mode dispatch
- 所有现有 L0 测试行为不变

## 5. Implementation Sequence (Future)

```
Stage 1 (本 AD): 定义合约、拆分 executor.py → executor_local.py + dispatch hub
Stage 2 (后续): 实现 executor_l1.py (REAL_LLM_READONLY)
Stage 3 (后续): 实现 executor_l1.py (REAL_LLM_TOOL_REQUESTING)
Stage 4 (后续): 实现 executor_sandbox.py (SANDBOXED_TOOL_CAPABLE)
```

每个 stage 独立可测试、可回滚、不阻塞其他子系统。

## 6. Open Questions

- `REAL_LLM_READONLY` 是否需要独立的 system prompt，还是复用 parent 的？
  → 倾向独立 prompt（通过 descriptor 或 context_package 注入），避免 prompt injection
     从 parent 泄漏到 SubAgent
- SubAgent 的 streaming event 如何处理？
  → 第一阶段不暴露；parent 只收到最终的 `SubAgentResult`，不转发中间 delta
- 需要 provider 层兼容性确认
  → L1 executor 通过 `context_package.provider` 注入，与 parent 共享 provider adapter，
     不引入新 provider dependency
