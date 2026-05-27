# Current Capability Status

这篇文档解决什么问题：用一页说明 First Agent **现在能做什么、不能做什么、下一步是什么**。

不解决什么问题：不替代全量审计、测试矩阵或 dogfood 原始报告；不授权真实 API、MCP、SubAgent L1、sandbox 或新能力建设。

推荐读者：第一次接触项目的人、准备继续 AutoRun 的 Coding Agent、准备做 manual human dogfood 的维护者。

## 当前标签

- ✅ **manual-dogfood-ready local agent**：fake/local 路径可按 checklist 走通。
- ✅ **shared runtime baseline**：fake/real provider 共享 `core.chat()` → `loop.py` → Tool Pipeline / RuntimeAction dispatcher 主路径。
- 🟡 **limited user-usable agent**：功能可用，但 onboarding、approval、debug、memory recall 仍需人类体验反馈。
- ❌ **broadly user-ready agent**：不是当前状态。

## 现在可用

| Area | What works now | Boundary |
|---|---|---|
| Startup / provider banner | 启动时显示 `[provider] mode=...` | 默认 fake/local；真实 provider 需要显式配置 |
| Fake/local chat | deterministic FakeProvider 可完成本地对话和工具触发 | 不代表真实 LLM 智能 |
| Tool Pipeline | `demo.write_demo_note` / `demo.echo_task_summary` 经 ToolRegistry / ToolExecutor 执行 | 高风险工具仍需要 confirmation；不是 sandbox |
| Memory | explicit retain、confirmation、list、forget、snapshot injection baseline | semantic recall 质量未做人类/真实 LLM 评估 |
| SubAgent | L0 deterministic `demo-stat` / `code-reviewer` demo-only descriptor | 不是 real child LLM，不是 multi-agent orchestration |
| Checkpoint / Resume | 本地 checkpoint/resume 安全边界存在 | 不是生产级 durable execution |
| Runtime events / run summary | CLI/TUI 可消费 RuntimeEvent，turn 结束有 run summary | debug UX 仍偏开发者 |
| Dogfood evidence | fake/local rehearsal `11/11 PASS`，full gate 上一轮 `3376 passed, 18 skipped, 0 failed` | 不能替代 manual human dogfood |

## 当前不能声称

- 不能声称 manual human dogfood 已完成。
- 不能声称 fake/local dogfood 等同真实用户可用。
- 不能声称 real provider 当前可用；最近项目配置返回 `401`，归类为 config/auth concern。
- 不能声称 Memory recall 有可靠语义价值；目前只证明 deterministic governance baseline。
- 不能声称 SubAgent 是真实多代理系统；当前是 L0 deterministic local demo。
- 不能声称有 sandbox-grade shell/network/file execution。
- 不能声称 Hook / MCP / RAG / embedding / plugin marketplace 已产品化。

## 当前推荐路径

1. 自动化继续时：只做 cleanup-only / low-complexity remediation。
2. 人类准备验证时：走 [Dogfood README](../dogfood/README.md) → 最新 dogfood 报告。
3. 真实 provider：先修复本机 credentials / endpoint compatibility；AutoRun 不重试真实 API。
4. 后续大设计：只在 manual dogfood 反馈明确后考虑 Memory UX、Tool approval UX、SubAgent L1、sandbox、MCP、hook lifecycle。

## 事实源

- Capability gap audit (archived): [archive/2026-05-27-cleanup/audit/](../archive/2026-05-27-cleanup/audit/)
- Red-team audit (archived): [archive/2026-05-27-cleanup/audit/](../archive/2026-05-27-cleanup/audit/)
- Dogfood rehearsal (archived): [archive/2026-05-27-cleanup/dogfood/](../archive/2026-05-27-cleanup/dogfood/)
- Current status: [PROJECT_STATUS.md](../PROJECT_STATUS.md)
- Unified runtime contract: [UNIFIED_RUNTIME_FLOW_CONTRACT.md](../real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md)
