# my-first-agent

First Agent 是一个本地优先（local-first）的 Agent Runtime 实验项目。
它的核心不是“更多工具”，而是把主代理运行时（Parent Agent Runtime）、工具注册中心（ToolRegistry）、记忆治理（Memory Governance）、技能系统（Skill System）、子代理系统（SubAgent System）、检查点（Checkpoint）和人工确认（Confirmation / Ask User）放在同一套可审计边界里运行。

当前项目已完成 Memory 主线、Skill System、SubAgent L0 safe-local 基线、Tool Pipeline L3、User Onboarding、Smoke Test，并通过全量测试 (~3380 passed, 18 skipped) 和 dogfood 验证。

**当前阶段（诚实标签，2026-05-25）：**
- ✅ **manual-dogfood-ready local agent** — FakeProvider baseline 9/9 PASS
- 🟡 **real-provider-dogfood-tested** — 历史 Kimi/DashScope 5/6 PASS；当前 deepseek-v4-pro 受 401 config/auth concern 阻塞
- 🟡 **limited user-usable agent** — 核心功能可用，但 UX polish 不足
- ❌ **broadly user-usable agent** — 不在当前 scope

它仍不是 SaaS、不是通用 Agent 框架、不是生产沙箱，也不会默认调用真实 LLM、shell、外部进程或远程 MCP。
新开发者先读本 README，再读 [docs/README.zh.md](docs/README.zh.md)。

> ⚠️ **Memory Consolidation pipeline 已冻结**：6 个 consolidation 文件的 dispatch path / handler path 已验证，但 business operation / real LLM consolidation deferred。参见 [全局审计文档](docs/audit/global-agent-capability-architecture-audit-2026-05-25.md) Section F (F4)。
>
> ⚠️ **FakeProvider 增长已冻结**：FakeProvider 是 deterministic test fixture / debug provider，不继续增强为 fake planner / fake reasoning engine。真实智能通过 real provider dogfood 验证。参见审计文档 Section B.3 (F19)。

**当前阶段：Cleanup-Only / Awaiting Manual Human Dogfood** — Capability Gap Audit + Low-Complexity Remediation 已完成（6 项 safe-to-auto-run 补齐），能力建设暂停。当前一页状态入口：[Current Capability Status](docs/00-overview/CURRENT_CAPABILITY_STATUS.zh.md)。见 [remediation summary](docs/plans/low-complexity-capability-remediation-summary-2026-05-25.md)。

**仍需人类完成：Manual Human Dogfood** — 自动 rehearsal 不是人工 dogfood 的替代品；等用户准备好后，从头按 fake/local 模式记录困惑、错误和 UX 摩擦。入口：[Dogfood README](docs/dogfood/README.md) → [Dogfood Checklist](docs/dogfood/local-manual-dogfood-checklist.md)。

> ⚠️ **v0.9.x 历史文档已归档至 `docs/archive/v0.x/`** — 不再作为当前入口。当前路线以全局审计文档为权威源。

## 当前状态

- Runtime/Core/Loop：主循环仍由 Parent Agent Runtime 拥有，`agent.loop` 已抽出主循环编排，`core.py` 仍是兼容入口和 runtime hub。
- ToolRegistry / ToolExecutor：ToolRegistry 仍是工具 authority；高风险工具保留 confirmation；Skill/SubAgent 不能直接执行工具。
- Memory：已完成 filesystem-first governance、interactive confirmation、pending review、consolidation/emergence foundation；无 silent retain、无 auto approve。
- Skill System：正式命名空间是 `agent/skill_system/`；支持 descriptor、registry、progressive disclosure、tool/memory/checkpoint 边界和 dogfood。
- SubAgent System：正式命名空间是 `agent/subagent_system/`；L0 deterministic/local 基线完成；L1-L5 仍 gated/future。
- Checkpoint / Resume：checkpoint 是安全边界，保存截断摘要和声明字段，避免持久化大 tool result 或未知字段。
- CLI/TUI：CLI/Textual 只是 adapter/presentation，不拥有 Agent loop；`main.py` 仍有 P3 adapter debt，不能视为已 productization。
- 当前验证基线：`ruff` passed；最近 full pytest 基线见 [Current Capability Status](docs/00-overview/CURRENT_CAPABILITY_STATUS.zh.md)；SubAgent synthetic dogfood `16/16`。
- Provider boundary：Claude/Anthropic 只作为 provider adapter 或文档参考出现；官方 SDK lazy import 限定在 `agent/provider/`，不是 `core.py`、Memory、Skill、SubAgent 或 dogfood runner 的运行依赖。

## 核心能力

| 能力 | 当前状态 | 默认行为 |
|---|---|---|
| Parent Agent Runtime | 已完成基础闭环 | 拥有主 loop、状态机、模型调用和分派 |
| ToolRegistry | 已完成治理基础 | 工具注册、风险、confirmation、可见性过滤 |
| Memory | 已完成主线 | 用户确认后写入；自动路径受 governance 限制 |
| Skill System | 已完成 formal safe-local 系统，demo-note-maker 可用 | metadata-first，按需加载，不直接执行工具 |
| SubAgent System | L0 已完成 | local fake/deterministic，Parent adjudication |
| Checkpoint | 已完成安全边界 | 截断 tool result，过滤未知字段 |
| CLI/TUI | 边界收口，仍有 P3 adapter debt | 输入/输出 adapter，不复制 runtime |
| Real LLM / real API dogfood | gated | 需要显式授权和配置 |
| Shell / external process / worktree | gated/future | 不默认开启 |

更完整的能力边界见 [CAPABILITY_MATRIX.zh.md](docs/00-overview/CAPABILITY_MATRIX.zh.md)。
历史 v0.3 Skill 状态和实验性声明见 [V0_3_SKILL_SYSTEM_STATUS.md](docs/archive/v0.x/V0_3_SKILL_SYSTEM_STATUS.md)；当前 formal Skill System 已完成 safe-local 主线，但仍不代表远程安装、自动执行工具或 sub-agent 接管 runtime。

## 架构图文字版

```text
User
  -> CLI / TUI adapter
  -> Parent Agent Runtime
      -> ToolRegistry / ToolExecutor
      -> Memory Governance
      -> Skill System
      -> SubAgent System
      -> Checkpoint / Audit / Dogfood
```

关键边界：

- Parent Agent owns orchestration。
- ToolRegistry remains authority。
- Memory governance remains authority。
- Checkpoint remains safety boundary。
- Confirmation / Ask User remains human-control boundary。
- Skill/SubAgent 都不能拥有主 Agent loop。

Mermaid 版见 [ARCHITECTURE_MAP.zh.md](docs/00-overview/ARCHITECTURE_MAP.zh.md)。

## 快速开始

### 环境要求

- Python 3.10+，推荐 Python 3.12。
- macOS / Linux shell；Windows 建议 WSL。
- 本地开发不需要真实 API key；真实 LLM 只在显式授权的 dogfood / smoke 中使用。

### 安装

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

不要提交 `.env`。默认测试和 fake/local demo 不需要读取 `.env`。
如果需要真实 provider，请从 `.env.example` 复制本地 `.env` 模板后只在本机填写 key；不要把 key 写入仓库。

### 运行 fake/local demo

```bash
.venv/bin/python main.py demo "create a demo note about today's local run"
```

这个 demo 使用 deterministic fake provider，不调用真实 LLM，不访问网络，不依赖 `.env` 中的 key。

> **注意**：`main.py demo` 是独立 demo adapter 路径（`agent/local_demo.py`），用于快速验证本地环境，**不经过完整的 ToolRegistry / Tool Pipeline / unified runtime flow**。它写入 `workspace/demo/` 受控目录。完整的 Runtime Action / Tool Pipeline 路径通过 `python main.py` 交互模式下的 `core.chat()` 统一入口触发。

### 运行 CLI

```bash
.venv/bin/python main.py
python main.py --shell       # Textual TUI shell（实验性）
python main.py --help        # 查看完整能力与限制说明
```

交互模式中输入 `help` 查看 onboarding；输入 `quit` 退出。

如需真实模型，需要自行在本地环境配置 provider key；不要把 key 写入仓库文件、日志、checkpoint 或文档。

当前默认使用 Fake Provider（安全路径，无 API key，不联网）。启动屏和 `--help` 会诚实说明当前可用能力与尚未产品化的部分。

启动屏参考：Health: python main.py health；Logs: python main.py logs --tail 50。Skill System safe-local 基线已完成，demo-note-maker 可用。当前 CLI shell is not a full Textual IDE.

### 本地健康检查和日志摘要

```bash
.venv/bin/python main.py health
.venv/bin/python main.py logs
python main.py health
python main.py logs
```

更详细的上手流程见 [GETTING_STARTED.zh.md](docs/01-getting-started/GETTING_STARTED.zh.md)。

## 测试命令

常用质量门：

```bash
ruff check agent tests scripts
python -m pytest tests/ -x -q
```

本项目有大量 opt-in real provider / real MCP 测试，默认会跳过真实外部集成。
完整测试矩阵见 [TEST_MATRIX.zh.md](docs/05-testing-dogfood/TEST_MATRIX.zh.md)。

## Dogfood 命令

Skill synthetic dogfood：

```bash
python scripts/dogfood_skill_system.py --tmp-root /tmp/my-first-agent-skill-dogfood --mode synthetic
```

SubAgent synthetic dogfood：

```bash
python scripts/dogfood_subagent_system.py --tmp-root /tmp/my-first-agent-subagent-dogfood --mode synthetic
```

Global synthetic dogfood：

```bash
python scripts/dogfood_global_real_api.py --tmp-root /tmp/my-first-agent-global-dogfood --mode synthetic --report-json /tmp/my-first-agent-global-synthetic-dogfood-report.json
```

Global Real API dogfood 是 gated，不默认运行。只有在文档 phase 和用户明确允许时才可执行，并且必须通过 project `.env` scoped loader 加载 provider config，禁止 shell env fallback。

## 配置职责边界

- `config.py`：legacy runtime/CLI 兼容常量，不是 provider dogfood path 的权威配置。
- `agent/provider/config.py`：provider/API 配置权威，供 provider factory 和 real-api dogfood 使用。
- `agent/local_config.py`：本地 agent customization metadata，只读显式 safe path，不展开 env secret，不连接 provider。

## 安全边界

默认行为：

- FakeProvider 安全路径不依赖 `.env`，不调用真实 API；`main()` 会尝试加载 `.env` 以支持 opt-in real provider 配置，但默认 fake 路径不使用其中任何 key。
- 不读取 `agent_log.jsonl` 正文。
- 不读取真实 `sessions/` / `runs/`。
- 不读取 `memory/episodes/*.jsonl` 内容。
- 不打印 API key / token / secret。
- 不默认调用真实 LLM。
- 不默认执行 shell / 外部进程。
- 不默认写 repo / 创建 worktree。
- 不让 Skill/SubAgent 绕过 Parent Runtime、ToolRegistry、Memory governance、Checkpoint、Confirmation。

## Real Provider Opt-in（真实模型接入）

默认 FakeProvider 不调用任何外部 API、不需要 key、不访问网络。若需要切换到真实 LLM provider，按以下步骤 opt-in。

### 前置条件

- 拥有有效的 Anthropic API key（`sk-ant-*`）或兼容端点
- 理解真实 API 调用的**计费风险**——每次 `chat()` 调用都会消耗 token 配额
- 理解数据会**离开本机**发送到 API 端点

### Opt-in 步骤

1. 从模板复制 `.env`（不提交到 git）：

   ```bash
   cp .env.example .env
   ```

2. 编辑 `.env`，设置 provider 和 key：

   ```bash
   # 必填：provider 类型（设置为 anthropic 启用真实路径）
   MY_FIRST_AGENT_LLM_PROVIDER=anthropic_native

   # 必填：Anthropic API key
   ANTHROPIC_API_KEY=sk-ant-...

   # 可选：模型名（默认 claude-sonnet-4-6）
   ANTHROPIC_MODEL=claude-sonnet-4-6
   ```

3. 验证 opt-in 是否生效：

   ```bash
   .venv/bin/python -c "
   import os; os.environ['MY_FIRST_AGENT_LLM_PROVIDER']='anthropic_native'
   from agent.provider.factory import build_model_provider_from_env
   p = build_model_provider_from_env()
   print(f'Provider: {type(p).__name__}')
   "
   ```

   应输出 `Provider: AnthropicNativeProvider`（而非 `FakeProvider`）。

### 支持的 Provider 类型

| `MY_FIRST_AGENT_LLM_PROVIDER` | 说明 |
|---|---|
| `fake`（默认） | Deterministic fake provider，不联网，不需要 key |
| `anthropic_native` | Anthropic Messages API（原生 SDK） |
| `anthropic_compatible` | Anthropic 兼容端点（如 DashScope 代理） |
| `openai_native` | OpenAI Chat Completions API（原生 SDK） |
| `openai_compatible` | OpenAI 兼容端点 |

完整配置变量见 `.env.example` 和 `agent/provider/config.py`。

### Fake vs Real 行为差异

| 行为 | FakeProvider | Real Provider |
|---|---|---|
| 网络访问 | 无 | 需要 HTTPS 出站 |
| API key | 不需要 | 必须配置 |
| 响应质量 | deterministic，模板化 | 真实 LLM 语义理解 |
| Tool use | deterministic tool decision 匹配 | 真实 tool_use 推理 |
| Streaming | deterministic 12-char chunking（fake/demo only，非真实 provider streaming UX） | 真实 SSE streaming |
| 成本 | 零 | 按 token 计费 |
| 延迟 | ~0ms | 数百 ms 到数秒 |

### 重要约束

- **fake/real 共享同一 runtime**：`core.chat()` → `loop.py` → `Tool Pipeline` → `Checkpoint` 路径对 fake 和 real 完全一致，只是 provider adapter 层替换
- `.env` 中的 key **绝不**自动读取——只有在显式设置 `MY_FIRST_AGENT_LLM_PROVIDER` 环境变量后，`build_model_provider_from_env()` 才会加载配置
- 真实 provider 调用**不会被任何自动流程触发**（包括 auto-run workflow、CI、pre-commit hook）——只有用户显式设置环境变量 + 手动运行才会启用
- 所有真实 API 测试默认跳过（需要额外 opt-in env var），详见 `tests/` 中的 `skipIf` 标记

## 当前不支持什么

- 不支持默认真实 LLM SubAgent。
- SubAgent delegation 当前支持 **CLI meta-command**（`delegate to X: task` / `委托 X: task`）和 **safe deterministic NL fixtures**（`帮我统计 demo workspace` / `summarize files`）——都是 local/fake deterministic 关键词匹配，不经过 LLM 自然语言理解，不是 broadly user-ready 产品体验。
- Streaming 当前仅 **FakeProvider deterministic 12-char chunking demo**（debug/fake only），不经过真实 provider SSE/streaming，不是真实 streaming UX。用户主体验是 progress/event UX（工具/子代理/记忆进度事件）。
- 不支持默认 SubAgent 工具执行、sandbox、worktree、parallel multi-subagent。
- 不支持把 Skill 当作远程插件市场或自动安装系统。
- 不支持 DB / graph / embedding / vector store 作为默认 memory backend。
- 不支持多用户 SaaS / 云端 Agent Runtime。
- 不支持绕过人工确认的高风险工具执行。
- Reflect / Self-Correction 是 v0.4+ Roadmap 边界，当前不做，不应写成 v0.3 或当前默认完成态。

## 历史 Smoke Preflight

Runtime v0.1 graduation 仍保留为 canonical smoke 历史基线：B1 complete、B2 complete、B3 complete。
详细证据见 `docs/archive/v0.x/V0_1_GRADUATION_REPORT.md`。

固定 preflight 命令：

```bash
.venv/bin/python -m ruff check agent/ tests/
.venv/bin/python -m pytest -q
```

固定 smoke 任务：

```text
请读取仓库根目录 README.md，并把一段中文总结写入 summary.md。
```

`summary.md` is a local smoke artifact and is ignored by git.

Explicit Non-Goals for v0.1:

- not a mature agent framework
- not a production safety sandbox
- not a complete TUI
- not a Skill or sub-agent platform

## 文档阅读路径

1. 项目入口：[docs/README.zh.md](docs/README.zh.md)
2. 当前一页状态：[CURRENT_CAPABILITY_STATUS.zh.md](docs/00-overview/CURRENT_CAPABILITY_STATUS.zh.md)
3. 了解当前自动化边界：[capability-gap-audit-low-complexity-2026-05-25.md](docs/audit/capability-gap-audit-low-complexity-2026-05-25.md)
4. Manual Human Dogfood Checklist：[docs/dogfood/local-manual-dogfood-checklist.md](docs/dogfood/local-manual-dogfood-checklist.md)
5. 当前审计：[docs/audit/global-red-team-product-architecture-audit-2026-05-25.md](docs/audit/global-red-team-product-architecture-audit-2026-05-25.md)
6. 系统概览：[FIRST_AGENT_OVERVIEW.zh.md](docs/00-overview/FIRST_AGENT_OVERVIEW.zh.md)
7. 架构图：[ARCHITECTURE_MAP.zh.md](docs/00-overview/ARCHITECTURE_MAP.zh.md)
8. 能力矩阵：[CAPABILITY_MATRIX.zh.md](docs/00-overview/CAPABILITY_MATRIX.zh.md)
9. 上手指南：[GETTING_STARTED.zh.md](docs/01-getting-started/GETTING_STARTED.zh.md)
10. 测试与 dogfood：[TEST_MATRIX.zh.md](docs/05-testing-dogfood/TEST_MATRIX.zh.md)
11. 本地试用清单（已归档）：[V0_3_LOCAL_TRIAL_CHECKLIST.md](docs/archive/v0.x/V0_3_LOCAL_TRIAL_CHECKLIST.md)
12. 手工试用反馈模板（已归档）：[V0_3_2_MANUAL_TRIAL_FEEDBACK.md](docs/archive/v0.x/V0_3_2_MANUAL_TRIAL_FEEDBACK.md)
13. Event transition 准备（已归档）：[V0_4_EVENT_TRANSITION_PREP.md](docs/archive/v0.x/V0_4_EVENT_TRANSITION_PREP.md)
14. Skill 实验性状态记录（已归档）：[V0_3_SKILL_SYSTEM_STATUS.md](docs/archive/v0.x/V0_3_SKILL_SYSTEM_STATUS.md)
15. **Runtime Integration 设计文档包**：[RUNTIME_INTEGRATION_RFC.zh.md](docs/runtime-integration/RUNTIME_INTEGRATION_RFC.zh.md) — Runtime Action Harness 蓝图（RFC/SDD/TDD/Implementation Loop/E2E Dogfood Plan/Audit Checklist）

Canonical specs 仍保留在 `docs/rfc/`、`docs/design/`、`docs/testing/`、`docs/roadmap/`、`docs/dogfood/`、`docs/audit/`。

## 下一步 Roadmap

当前阶段（2026-05-25）：
- **Cleanup-Only Remediation 已完成** — PF-01 到 PF-15，修复了 P1/P2 cleanup 问题（provider mode contract, command shortcut freeze, secret redaction, source-of-truth, SubAgent fixture boundary, E2E label, legacy sunset），全量 gate 通过
- **Low-Complexity Remediation 已完成** — 6 项 safe-to-auto-run 补齐（capability gap audit, status guide, CLI help polish, run summary polish, dogfood prep, redaction lint）
- **Manual Human Dogfood** — 当前最高优先级下一步；cleanup 完成后唯一有意义的非自动步骤
- **能力建设暂停** — 不新增 feature，不扩 Agent 能力，AutoRun 保持 cleanup-only

近期已完成：
- 第一轮 Global Red-Team Remediation（RT-01 到 RT-18，6 phases）
- RT-01 dispatcher/evidence parity、RT-12 FakeProvider side effect fix
- RT-02 command shortcut boundary、RT-06 secret redaction、RT-07 SubAgent fixture isolation
- RT-05 docs source-of-truth、RT-16 test evidence labeling

能力建设历史记录（已完成，不再作为当前行动指令）：
- WP1-WP4: First Usable Task MVP — ToolRegistry demo tools、SkillRegistry、User Onboarding、E2E Smoke Test
- Memory 主线、Skill System safe-local 基线、SubAgent L0 deterministic/local 基线
- Tool Pipeline L3、real-provider dogfood (Kimi/DashScope)
