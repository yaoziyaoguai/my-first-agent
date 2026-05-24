---
name: demo-stat
description: 统计当前项目文件数量、目录结构等确定性指标。不调外部 API、不读私人资料。
role: analyzer
model: fake
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
# demo_stat

安全本地 demo subagent，用于演示 SubAgent delegation 的用户可见行为。
