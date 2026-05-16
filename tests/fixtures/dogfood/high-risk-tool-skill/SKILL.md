---
name: high-risk-tool-skill
description: 请求高风险工具但不应绕过 ToolRegistry confirmation
version: 0.1.0
status: active
risk_level: high
tags:
  - high-risk
  - shell
allowed_tools:
  - read_file
  - run_shell
confirmation_policy: inherit_tool_policy
memory_scope: none
---

# High-Risk Tool Skill

此 Skill 请求 `run_shell` 工具，声明为 high risk。

## 关键验证

- ToolRegistry 的 risk/confirmation 权威不变
- Skill 的 `confirmation_policy: inherit_tool_policy` 不能降低工具确认要求
- 未确认时工具不执行
- fail-closed
