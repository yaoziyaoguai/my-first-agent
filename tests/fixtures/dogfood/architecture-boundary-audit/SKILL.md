---
name: architecture-boundary-audit
description: 审查 diff 是否引入跨层导入
version: 0.1.0
status: active
risk_level: medium
tags:
  - architecture
  - boundary
  - audit
allowed_tools:
  - run_shell
  - read_file
memory_scope: none
---

# Architecture Boundary Audit

审查 diff 中是否存在跨层导入等架构边界问题。
