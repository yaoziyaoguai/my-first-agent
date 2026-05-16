---
name: git-status-audit
description: 汇总本地 git 状态并识别有风险的未跟踪文件
version: 0.1.0
status: active
risk_level: medium
tags:
  - git
  - audit
  - local
allowed_tools:
  - run_shell
  - read_file
memory_scope: none
---

# Git Status Audit

汇总当前仓库的 git 状态，识别有风险的文件。

## 工具约束

- `run_shell` 仅限只读 git 命令
- 禁止网络操作
- 禁止 write_file
