# Current Capability Status

这篇文档解决什么问题：用一页说明 First Agent **现在能做什么、不能做什么、下一步是什么**。

不解决什么问题：不替代全量审计、测试矩阵或 dogfood 原始报告；不授权真实 API、MCP、SubAgent L1、sandbox 或新能力建设。

推荐读者：第一次接触项目的人、准备继续 AutoRun 的 Coding Agent、准备做 manual human dogfood 的维护者。

## 当前标签

- ✅ **real API dogfood smoke 通过**：20 cases，19 non-failing / 1 CONCERN / 0 FAIL（kimi-k2.5 via DashScope，2026-05-27）。
- ✅ **fake/local gate 通过**：FakeProvider baseline 可完成本地闭环。
- 🟡 **limited user-usable agent**：核心功能可用，但 interactive confirmation、resume、tool/memory confirmation 覆盖不足。
- 🟡 **evidence 口径仍需硬化**：当前 dogfood 多数是 direct provider smoke，不是完整 runtime E2E。
- ❌ **broadly user-ready agent**：不是当前状态。

## 现在可用

| Area | What works now | Boundary |
|---|---|---|
| Startup / provider banner | 启动时显示 `[provider] mode=...` | 默认 fake/local；真实 provider 需要显式配置 `enabled: true` |
| Fake/local chat | deterministic FakeProvider 可完成本地对话和工具触发 | 不代表真实 LLM 智能 |
| Real API dogfood | 20 cases，19 non-failing / 1 CONCERN / 0 FAIL（kimi-k2.5, 2026-05-27） | 多数是 direct provider smoke；interactive path 覆盖不足 |
| Tool Pipeline | `demo.write_demo_note` / `demo.echo_task_summary` 经 ToolRegistry / ToolExecutor 执行 | 高风险工具仍需要 confirmation；不是 sandbox |
| Memory | explicit retain、confirmation、list、forget、snapshot injection baseline | semantic recall 质量未做人类/真实 LLM 评估 |
| SubAgent | L0 deterministic `demo-stat` / `code-reviewer` demo-only descriptor | 不是 real child LLM，不是 multi-agent orchestration |
| Checkpoint / Resume | 本地 checkpoint/resume 安全边界存在 | 不是生产级 durable execution |
| Runtime events / run summary | CLI/TUI 可消费 RuntimeEvent，turn 结束有 run summary | debug UX 仍偏开发者 |
| Dogfood evidence | real API smoke 19/20 non-failing；fake/local baseline；full gate `~3380 passed, 18 skipped` | interactive y/n、resume、tool/memory confirmation 尚未真实覆盖 |

## 当前不能声称

- 不能声称 manual human dogfood 已完成。
- 不能声称 real API dogfood smoke (19/20) 等于完整用户级产品验证。
- 不能声称 interactive confirmation、resume、tool/memory confirmation 已覆盖。
- 不能声称 Memory recall 有可靠语义价值；目前只证明 deterministic governance baseline。
- 不能声称 SubAgent 是真实多代理系统；当前是 L0 deterministic local demo。
- 不能声称有 sandbox-grade shell/network/file execution。
- 不能声称 Hook / MCP / RAG / embedding / plugin marketplace 已产品化。

## 当前推荐路径

1. 自动化继续时：只做 cleanup-only / source-of-truth repair。
2. 人类准备验证时：走 [Dogfood README](../dogfood/README.md) → 最新 dogfood 报告。
3. 真实 provider：通过 `config/config.yaml`（`enabled: true`）启用；api_key 可写入本地但不 commit。
4. 后续：优先 interactive dogfood harness（y/n、resume、tool/memory confirmation），再做 evidence 口径硬化。

## 事实源

- Capability gap audit (archived): [archive/2026-05-27-cleanup/audit/](../archive/2026-05-27-cleanup/audit/)
- Red-team audit (archived): [archive/2026-05-27-cleanup/audit/](../archive/2026-05-27-cleanup/audit/)
- Dogfood rehearsal (archived): [archive/2026-05-27-cleanup/dogfood/](../archive/2026-05-27-cleanup/dogfood/)
- Current status: [PROJECT_STATUS.md](../PROJECT_STATUS.md)
- Unified runtime contract: [UNIFIED_RUNTIME_FLOW_CONTRACT.md](../real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md)
