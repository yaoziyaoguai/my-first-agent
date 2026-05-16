---
name: safe-local-file-summarization
description: 安全地汇总用户提供的文件，拒绝敏感路径和网络访问
version: 0.1.0
status: active
risk_level: medium
tags:
  - summarization
  - safety
  - local-only
allowed_tools:
  - read_file
memory_scope: none
---

# Safe Local File Summarization

只允许读取用户显式提供的安全路径下的文件。

## 禁止访问

- `.env`
- `agent_log.jsonl`
- `sessions/` / `runs/`
- 任何网络资源
- 任何非 tmp/fixture 路径的文件
