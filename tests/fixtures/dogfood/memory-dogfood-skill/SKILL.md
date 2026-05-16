---
name: memory-dogfood-skill
description: 验证 Memory 边界——Skill 只能提议不能直接写入 MemoryStore
version: 0.1.0
status: active
risk_level: low
tags:
  - memory
  - governance
  - proposal
allowed_tools:
  - read_file
memory_scope: propose_memory
---

# Memory Dogfood Skill

此 Skill 声明 `memory_scope: propose_memory`，表示允许通过 governance
提议 Memory 条目。但 Skill 本身不能：
- 直接写 MemoryStore
- 静默 retain 信息
- 自动批准自己的 proposal
