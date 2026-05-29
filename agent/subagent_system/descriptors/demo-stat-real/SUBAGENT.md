---
name: demo-stat-real
description: REAL-EVIDENCE-006 validation — 统计当前项目文件数量、目录结构等确定性指标。继承 parent provider config，不持有独立 API key。
role: analyzer
model: inherit
status: active
risk_level: low
version: 0.1.0
allowed_tools:
  - read_file
allowed_skills: []
memory_scope: none
max_iterations_default: 1
confirmation_policy: inherit_tool_policy
supported_modes:
  - local_fake
---
# demo-stat-real

REAL-EVIDENCE-006 validation subagent。与 demo-stat 功能相同，但 model=inherit
使 L1 handler 能通过 `execute_l1()` 调用真实 provider child loop。

model=inherit 的含义：child 不持有独立 provider config，provider 由 parent
在运行时注入（`l1_handler.set_provider(provider, None)`），descriptor 仅声明
"我接受 parent provider"。

安全约束：
- 不读取 .env
- 不持有 API key
- 工具执行通过 parent ToolRuntimeMediator 中介
- 只用于 opt-in dogfood / validation
