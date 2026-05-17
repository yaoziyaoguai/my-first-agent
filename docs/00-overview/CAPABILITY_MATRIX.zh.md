# Capability Matrix

这篇文档解决什么问题：列出 First Agent 当前完成、已 dogfood、gated、future 和明确不支持的能力。

不解决什么问题：不替代具体 RFC，也不授权开启 gated/future capability。

推荐读者：项目维护者、审计者、准备继续实现的 Coding Agent。

| Capability | Status | Dogfood | Default | Notes |
|---|---|---|---|---|
| Runtime/Core/Loop | 已完成基础闭环 | full pytest | on | `core.py` 仍是 hub，后续只做行为中性瘦身 |
| ToolRegistry | 已完成治理基础 | selected tests | on | authority 保留；high-risk confirmation 有效 |
| ToolExecutor | 已完成主路径 | selected tests | on | 负责 tool_result、pending confirmation、checkpoint |
| Memory explicit retain | 已完成 | tests + dogfood evidence | on | 必须经 confirmation |
| Memory pending review | 已完成 | tests | on | no silent retain |
| Memory consolidation/emergence | foundation 已完成 | synthetic + real gated evidence | gated/opt-in | direct store write 仍受 governance |
| Skill System | 已完成 formal safe-local | synthetic + real API dogfood | on for formal local contracts | 不默认安装远程 skill |
| SubAgent L0 | 已完成 | T1 synthetic 16/16 | on for local deterministic contracts | no real LLM / no shell / no external process |
| SubAgent L1 Read-Only | gated | not default | off | 需要 config + audit + dogfood + approval |
| SubAgent L2 Tool-Requesting | gated | not default | off | parent-mediated only |
| SubAgent L3 Sandbox | future/contract | no | off | 不默认创建 sandbox |
| SubAgent L4 Worktree | future | no | off | 不默认创建 worktree |
| SubAgent L5 Parallel Multi-SubAgent | future | no | off | 不默认 nested delegation |
| Checkpoint / Resume | 已完成安全边界 | selected tests | on | 截断大 tool_result，过滤未知字段 |
| Confirmation / Ask User | 已完成主路径 | selected tests | on | 人类控制边界 |
| CLI/TUI | 已完成 adapter boundary | selected tests | on | TUI 可选；simple CLI fallback |
| Real LLM provider | gated | opt-in smoke | off unless configured | 默认测试不调用真实 provider |
| External process | gated/high risk | no default dogfood | off by default | 需 ToolRegistry + confirmation |
| Shell | high risk | no default SubAgent | off by default | `run_shell` 需 confirmation |
| Real MCP | gated | opt-in only | off | 不默认连接 server |
| DB / graph / embedding / vector store | explicitly not supported | no | off | 不是当前默认 backend |
| SaaS / multi-user platform | explicitly not supported | no | off | 项目是 local-first |

## Capability Level 命名

- Capability Level = L0-L5，仅用于 SubAgent 能力层级。
- Dogfood Tier = T1-T6，仅用于 SubAgent dogfood 覆盖层级。
- Implementation Phase = Phase 0-N。
- Audit Priority = P0-P3。
