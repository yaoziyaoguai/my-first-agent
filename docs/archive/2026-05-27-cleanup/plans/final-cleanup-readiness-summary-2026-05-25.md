# Final Cleanup Readiness Summary

- **Date:** 2026-05-25
- **Status:** active — cleanup loops completed, project ready for manual human dogfood

## 项目当前状态

First Agent 是一个 developer-usable / manual-dogfood-ready local agent runtime 原型。
共享 runtime spine（`core.chat()` → `loop.py` → Tool Pipeline / RuntimeAction dispatcher）对 fake 和 real provider 统一。不是 broadly user-usable。

| 状态标签 | 说明 |
|----------|------|
| ✅ manual-dogfood-ready local agent | fake/local 11/11 PASS |
| 🟡 real-provider-dogfood-tested | 历史 Kimi/DashScope 5/6 PASS；当前 deepseek-v4-pro 受 401 阻塞 |
| 🟡 limited user-usable agent | 功能可用但 UX 仍需人类反馈 |
| ❌ broadly user-usable agent | 不是当前 scope |

## 现在可用的能力

| Area | Status | 入口 |
|------|--------|------|
| Fake/local chat | deterministic FakeProvider | `python main.py` 交互模式 |
| Tool Pipeline | demo.write_demo_note / demo.echo_task_summary | FakeProvider tool trigger → ToolRegistry → ToolExecutor |
| Memory | retain/confirm/list/forget/snapshot | `show memories`, `remember`, `forget` |
| SubAgent L0 | demo-stat / code-reviewer deterministic local | `delegate to demo-stat: ...` / NL fixture |
| Checkpoint/Resume | 本地安全边界 | 自动 |
| Run summary | 每 turn 结束后自动输出 | 自动 |
| Provider banner | 启动时显示 mode/model | 自动 |

## 自动验证结果

### Agent-Driven Dogfood Rehearsal

- **Fake/Local**: 11/11 PASS — help, provider banner, normal chat, tool demo, memory list, show subagents, CLI delegate, NL delegate, memory remember, memory forget, real provider banner
- **Real Provider**: SKIPPED — 401 auth error（config/env issue, not code bug）
- **报告**: [agent-driven-human-dogfood-rehearsal-report.md](../dogfood/agent-driven-human-dogfood-rehearsal-report.md)

### Full Gate

- `ruff check agent tests scripts`: All checks passed
- `git diff --check`: Clean
- `HOME=/private/tmp pytest tests/ -x -q`: ~3380 passed, 18 skipped, 0 failed

## 仍需人类完成

以下项目只能由人类主观判断，自动 rehearsal 无法替代：

1. 是否顺手 / 是否看得懂（startup banner, onboarding, help）
2. Tool confirmation UX 是否清晰可信
3. Memory 两阶段确认是否容易理解
4. 错误恢复是否友好
5. Run summary 信息是否充足
6. 真实 LLM 对话质量（需要有效 API key）
7. Tool Pipeline 结果是否用户可见
8. 能力边界说明是否足够清晰

## Real Provider 401 阻塞

- **当前状态**: `anthropic_compatible` provider + `deepseek-v4-pro` model → `ProviderAuthError: http_status:401`
- **根因**: API key 有效性、endpoint Anthropic-format API 兼容性、或 model name 不匹配 — 需要人工验证
- **阻塞范围**: 所有 real provider step
- **不阻塞**: fake/local dogfood、docs cleanup、source-of-truth、ruff/pytest gates

## 已冻结 / Deferred

| 项 | 状态 |
|----|------|
| FakeProvider 智能增强 | frozen |
| Memory real LLM consolidation | frozen |
| Hook system 实现 | deferred |
| MCP confirmation pipeline | deferred |
| SubAgent L1+ orchestration | deferred |
| Sandbox-grade execution | deferred |
| RAG / embedding / plugin marketplace | deferred |
| Streaming UX | freeze event schema |
| Command shortcuts | freeze + allowlist |
| `main.py demo` / `local_demo.py` | legacy demo path, do not expand |

## AutoRun 后续边界

### 可以做的
- docs consistency cleanup
- status guide / source-of-truth 更新
- dogfood checklist / report 小修正
- redaction / status lint fix
- read-only audit

### 不能做的
- 新增 capability / feature
- 新增 runtime branch point / RuntimeActionType
- FakeProvider 智能增强
- Memory / SubAgent / Hook / MCP 扩展
- 绕过 core.chat / loop.py / unified runtime flow
- 读取 .env / 调用真实 API / 真实 LLM
- 声称 human dogfood 已完成
- 把 fake/local 能力写成 broadly user-ready

## 推荐用户下一步

### 最短 fake/local dogfood 路径

```bash
cd /Users/jinkun.wang/work_space/my-first-agent

# 1. 确认状态
git status -sb

# 2. 查看帮助
.venv/bin/python main.py --help

# 3. 进入交互模式
.venv/bin/python main.py
```

交互模式内依次输入：

```text
你好，今天怎么样？
make a demo note
show memories
show subagents
delegate to demo-stat: count files in workspace
remember my name is Alice
show memories
forget id:<从 show memories 输出中复制的短 ID>
quit
```

### 记录方式

只记录实际感受和异常：
- 哪一步看不懂
- 哪个提示容易误解
- Tool approval 文案是否清楚
- Memory confirmation 是否容易理解
- Tool result / run summary 是否足够可见
- 是否出现 crash、卡住、重复提示或不可信输出

需要正式记录时使用 [manual-human-dogfood-record-template.md](../dogfood/manual-human-dogfood-record-template.md) 的结构。

### Stop Conditions for User

- 有 secret 泄漏风险
- 意外文件写入 workspace 以外
- 错误消息包含真实路径或敏感信息
- 程序 crash 或无响应超过 30 秒
- 不确定当前是 fake 还是 real mode 时

## 用户 Human Dogfood 后的建议 Prompt

```
/auto-run /project:auto-run

我已完成 manual human dogfood（fake/local 模式），以下是反馈：

[记录每步发现：困惑、错误、UX 问题]

下一步请基于反馈做 targeted UX / docs fix，仍然只做 cleanup，不新增 capability。
```

---

**最终结论：Manual human dogfood 是当前唯一有意义的非自动下一步。所有 cleanup 和能力建设暂停等待人类反馈。**
