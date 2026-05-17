# my-first-agent

First Agent 是一个本地优先（local-first）的 Agent Runtime 实验项目。
它的核心不是“更多工具”，而是把主代理运行时（Parent Agent Runtime）、工具注册中心（ToolRegistry）、记忆治理（Memory Governance）、技能系统（Skill System）、子代理系统（SubAgent System）、检查点（Checkpoint）和人工确认（Confirmation / Ask User）放在同一套可审计边界里运行。

当前项目已经完成 Memory 主线、Skill System、SubAgent L0 safe-local 基线，并通过全量测试和 synthetic dogfood。
它仍不是 SaaS、不是通用 Agent 框架、不是生产沙箱，也不会默认调用真实 LLM、shell、外部进程或远程 MCP。
新开发者先读本 README，再读 [docs/README.zh.md](docs/README.zh.md)。

## 当前状态

- Runtime/Core/Loop：主循环仍由 Parent Agent Runtime 拥有，`agent.loop` 已抽出主循环编排，`core.py` 仍是兼容入口和 runtime hub。
- ToolRegistry / ToolExecutor：ToolRegistry 仍是工具 authority；高风险工具保留 confirmation；Skill/SubAgent 不能直接执行工具。
- Memory：已完成 filesystem-first governance、interactive confirmation、pending review、consolidation/emergence foundation；无 silent retain、无 auto approve。
- Skill System：正式命名空间是 `agent/skill_system/`；支持 descriptor、registry、progressive disclosure、tool/memory/checkpoint 边界和 dogfood。
- SubAgent System：正式命名空间是 `agent/subagent_system/`；L0 deterministic/local 基线完成；L1-L5 仍 gated/future。
- Checkpoint / Resume：checkpoint 是安全边界，保存截断摘要和声明字段，避免持久化大 tool result 或未知字段。
- CLI/TUI：CLI/Textual 只是 adapter/presentation，不拥有 Agent loop。
- 当前验证基线：`ruff` passed；full pytest 曾通过 `2684 passed, 14 skipped`；SubAgent synthetic dogfood `16/16`。

## 核心能力

| 能力 | 当前状态 | 默认行为 |
|---|---|---|
| Parent Agent Runtime | 已完成基础闭环 | 拥有主 loop、状态机、模型调用和分派 |
| ToolRegistry | 已完成治理基础 | 工具注册、风险、confirmation、可见性过滤 |
| Memory | 已完成主线 | 用户确认后写入；自动路径受 governance 限制 |
| Skill System | 已完成 formal safe-local 系统 | metadata-first，按需加载，不直接执行工具 |
| SubAgent System | L0 已完成 | local fake/deterministic，Parent adjudication |
| Checkpoint | 已完成安全边界 | 截断 tool result，过滤未知字段 |
| CLI/TUI | 已完成边界收口 | 输入/输出 adapter，不复制 runtime |
| Real LLM / real API dogfood | gated | 需要显式授权和配置 |
| Shell / external process / worktree | gated/future | 不默认开启 |

更完整的能力边界见 [CAPABILITY_MATRIX.zh.md](docs/00-overview/CAPABILITY_MATRIX.zh.md)。

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

### 运行 fake/local demo

```bash
.venv/bin/python main.py demo "create a demo note about today's local run"
```

这个 demo 使用 deterministic fake provider，不调用真实 LLM，不访问网络，不读取 `.env` / `agent_log.jsonl` / `sessions/` / `runs/`。

### 运行 CLI

```bash
.venv/bin/python main.py
```

如需真实模型，需要自行在本地环境配置 provider key；不要把 key 写入仓库文件、日志、checkpoint 或文档。

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

Real API dogfood 是 gated，不默认运行。只有在文档 phase 和用户明确允许时才可执行。

## 安全边界

默认禁止：

- 不读取 `.env`。
- 不读取 `agent_log.jsonl` 正文。
- 不读取真实 `sessions/` / `runs/`。
- 不读取 `memory/episodes/*.jsonl` 内容。
- 不打印 API key / token / secret。
- 不默认调用真实 LLM。
- 不默认执行 shell / 外部进程。
- 不默认写 repo / 创建 worktree。
- 不让 Skill/SubAgent 绕过 Parent Runtime、ToolRegistry、Memory governance、Checkpoint、Confirmation。

## 当前不支持什么

- 不支持默认真实 LLM SubAgent。
- 不支持默认 SubAgent 工具执行、sandbox、worktree、parallel multi-subagent。
- 不支持把 Skill 当作远程插件市场或自动安装系统。
- 不支持 DB / graph / embedding / vector store 作为默认 memory backend。
- 不支持多用户 SaaS / 云端 Agent Runtime。
- 不支持绕过人工确认的高风险工具执行。

## 文档阅读路径

1. 项目入口：[docs/README.zh.md](docs/README.zh.md)
2. 系统概览：[FIRST_AGENT_OVERVIEW.zh.md](docs/00-overview/FIRST_AGENT_OVERVIEW.zh.md)
3. 架构图：[ARCHITECTURE_MAP.zh.md](docs/00-overview/ARCHITECTURE_MAP.zh.md)
4. 能力矩阵：[CAPABILITY_MATRIX.zh.md](docs/00-overview/CAPABILITY_MATRIX.zh.md)
5. 上手指南：[GETTING_STARTED.zh.md](docs/01-getting-started/GETTING_STARTED.zh.md)
6. 测试与 dogfood：[TEST_MATRIX.zh.md](docs/05-testing-dogfood/TEST_MATRIX.zh.md)
7. 当前审计状态：[CURRENT_AUDIT_STATUS.zh.md](docs/06-audit/CURRENT_AUDIT_STATUS.zh.md)

Canonical specs 仍保留在 `docs/rfc/`、`docs/design/`、`docs/testing/`、`docs/roadmap/`、`docs/dogfood/`、`docs/audit/`。

## 下一步 Roadmap

1. 推送当前 main 前，建议再做一次独立文档审计。
2. SubAgent 后续只可按文档 gate 推进 L1/L2；L3/L4/L5 仍是 future/contract。
3. Memory 下一步聚焦真实质量 dogfood 和更清晰的 recall/provider 边界，不引入未授权 backend。
4. Skill 下一步可继续强化真实 dogfood 证据和文档索引，不默认安装远程 skill。
5. Runtime 下一步继续减少 `core.py` hub 压力，但不能破坏现有 checkpoint / confirmation / tool_result 语义。
