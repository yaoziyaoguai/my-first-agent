---
name: on-demand-resources
description: 验证渐进式加载——Level 3 resources 仅在显式请求时加载
version: 0.1.0
status: active
risk_level: low
tags:
  - progressive-disclosure
  - resources
  - test
allowed_tools:
  - read_file
memory_scope: none
resources:
  references:
    - references/guide.md
  templates:
    - references/template.txt
---

# On-Demand Resources Skill

此 Skill 用于验证渐进式加载行为：
- Level 1 metadata：始终可见
- Level 2 body：仅在选定时加载
- Level 3 resources：仅在显式 on-demand 请求时加载

## 约束

- 不加载 `.env`
- 不加载 `agent_log.jsonl`
- 不访问 `sessions/` / `runs/`
- path traversal 应 fail closed
