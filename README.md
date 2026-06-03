# my-first-agent

First Agent 是一个本地优先（local-first）的 Agent Runtime 实验项目。

**当前状态入口：[docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md)** — 所有 Coding Agent 和人类开发者的第一优先读取入口。

## 当前状态（2026-06-03）

- ✅ **v1 engineering closeout prepared** — `docs/releases/v1/first-agent-v1-closeout.md`
- ✅ **AGENT_DOGFOOD_AUTO suite 通过** — 873 tests PASS, 0 AGENT_FIX_AUTO, 7 xfailed known/expected
- ✅ **Full pytest: 4406 passed, 0 failed, 37 xfailed** — code-clean baseline
- ✅ **TUI Visual Shell Slice A+B delivered** — 静态 visual shell + safe data wiring, 不接 runtime/provider
- 🟡 **V1 Closeout: USER_MANUAL_TRIAL + PRODUCT_DECISION pending** — 非代码阻塞项
- ❌ **不声称 broadly user-usable** — not product-ready, current-stage remains FROZEN
- 📋 **v2 next source**: [docs/debt/first-agent-v2-priority-backlog.md](docs/debt/first-agent-v2-priority-backlog.md)

最新状态：[docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md)
最新 closeout：[docs/releases/v1/first-agent-v1-closeout.md](docs/releases/v1/first-agent-v1-closeout.md)
最新 dogfood：[docs/dogfood/README.md](docs/dogfood/README.md)

## 快速开始

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
.venv/bin/python main.py demo "create a demo note about today's local run"
```

默认使用 deterministic fake provider，不调用真实 LLM，不访问网络，不需要 API key。

其他入口：`python main.py --tui`（Textual TUI 交互模式），`cd tui && npm start`（Ink Visual Shell）。`--shell` 已弃用，仍兼容 plain CLI。

Health: python main.py health；Logs: python main.py logs --tail 50。

当前为 **safe-local** 阶段：不调用真实 API、不访问网络、不需要 API key。
Skill System 仍为 **实验性**（详见 `V0_3_SKILL_SYSTEM_STATUS`），**not a full Textual IDE**。
演示 skill：`demo-note-maker`。能力状态：`CURRENT_CAPABILITY_STATUS.zh.md`。

## Config

**唯一推荐入口**: `config/config.yaml`（provider section）。

- 默认 faked 安全路径，零 API key 可运行
- 如需真实 provider，编辑 `provider` section 设置 `enabled: true`
- `api_key` 可直接写入 `config/config.yaml`（个人本地项目），**但不得 commit**
- Legacy 路径（`FIRST_AGENT_PROVIDER_PROFILE`、`MY_FIRST_AGENT_LLM_PROVIDER`、`.env`）已 deprecated

参考：[config/config.example.yaml](config/config.example.yaml)、[config/examples/](config/examples/)

## 文档导航

| 想了解 | 读这里 |
|--------|--------|
| 当前项目状态 | [docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md) |
| 进度账本 | [docs/PROGRESS_LEDGER.md](docs/PROGRESS_LEDGER.md) |
| 文档入口 | [docs/README.zh.md](docs/README.zh.md) |
| 工程流程 | [docs/dev/AUTO_RUN_WORKFLOW.md](docs/dev/AUTO_RUN_WORKFLOW.md) |
| 最新 dogfood | [docs/dogfood/README.md](docs/dogfood/README.md) |
| 最新审计 | [docs/audit/b1-b8-current-stage-close-out-audit.md](docs/audit/b1-b8-current-stage-close-out-audit.md) |
| 历史文档 | [docs/archive/](docs/archive/) |

## 测试

```bash
ruff check agent tests scripts
python -m pytest tests/ -x -q
```

## 安全边界

- 默认不调用真实 API、不访问网络
- 不读取 `.env`、`agent_log.jsonl`、sessions/runs/private data
- 不 commit `config/config.yaml`（含真实 key）
- 不 tag / release / force push

## 核心架构

```text
User → CLI/TUI adapter → Parent Agent Runtime
  → ToolRegistry / ToolExecutor
  → Memory Governance
  → Skill System
  → SubAgent System (L0)
  → Checkpoint / Confirmation
```
