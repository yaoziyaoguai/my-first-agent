# Current Audit Status

这篇文档解决什么问题：记录当前代码、测试、dogfood、文档入口的审计状态，方便 push 前快速判断项目是否健康。

不解决什么问题：不替代独立审计报告，不作为 tag/release 授权。

推荐读者：维护者、准备 push 的 Coding Agent、独立审计者。

## 总体结论

Status: PASS for current main before push.

当前未发现 P0/P1/P2。主要 P3 是长期维护风险：`core.py` 仍是 runtime hub，历史文档很多且有旧阶段叙事。本轮已重写中文入口文档，但建议 push 前做一次 independent docs quick audit。

## Area status

| Area | Status | Evidence | Risk |
|---|---|---|---|
| Runtime/Core/Loop | Healthy | `agent.loop` 抽出主循环；architecture tests 固定边界 | P3: `core.py` 仍偏大 |
| ToolRegistry/ToolExecutor | Healthy | ToolRegistry metadata、confirmation、visibility tests | P3: 全局 registry 仍需谨慎测试隔离 |
| Memory | Healthy | no silent retain / no auto approve；pending review / inline confirmation | P3: capability 文档仍大而复杂 |
| Skill | Healthy | formal `agent/skill_system/`；legacy 隔离；synthetic + real API dogfood 证据 | P3: docs 多，入口需靠新索引 |
| SubAgent | Healthy | L0 complete；T1 synthetic dogfood 16/16；L1-L5 gated/future | none blocking |
| Checkpoint | Healthy | 截断 tool_result；过滤未知字段；Skill/SubAgent summary safe | none blocking |
| Confirmation / Ask User | Healthy | request_user_input / memory confirmation / tool confirmation 复用 runtime 边界 | none blocking |
| CLI/TUI | Healthy | adapter/presentation only；Textual lazy optional | P3: `main.py` 仍承担较多 adapter 兼容 |
| Tests | Healthy | full pytest baseline passed | skipped real external tests are expected |
| Dogfood | Healthy | Skill synthetic, SubAgent synthetic, gated real API evidence | real dogfood not default |
| Security/Secrets | Healthy | `.env` / `agent_log.jsonl` / sessions/runs/memory episodes not tracked | do not read real artifacts in audit |

## Ready to push?

Yes, after this docs rewrite commit passes checks. Do not tag yet.

## Known limitations

- Real LLM SubAgent L1/L2 remain gated.
- Sandbox/worktree/parallel SubAgent remain future/contract.
- Real MCP server activation remains opt-in.
- DB/graph/embedding/vector store are not default memory backends.
- Documentation history is intentionally preserved; use `docs/README.zh.md` as entrypoint.
