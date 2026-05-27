# my-first-agent

First Agent 是一个本地优先（local-first）的 Agent Runtime 实验项目。

**当前状态入口：[docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md)** — 所有 Coding Agent 和人类开发者的第一优先读取入口。

## 当前状态（2026-05-27）

- ✅ **Real API dogfood smoke 通过** — 20 cases 中 19 个 non-failing / 1 CONCERN / 0 FAIL
- ✅ **Fake/local gate 通过** — deterministic provider 可完成本地闭环
- 🟡 **证据口径仍需硬化** — interactive confirmation、resume、tool/memory confirmation 覆盖不足
- ❌ **不声称 broadly user-usable**

最新全局审计：[docs/audit/global-readonly-audit-2026-05-27.md](docs/audit/global-readonly-audit-2026-05-27.md)

## 快速开始

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
.venv/bin/python main.py demo "create a demo note about today's local run"
```

默认使用 deterministic fake provider，不调用真实 LLM，不访问网络，不需要 API key。

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
| 最新 dogfood | [docs/dogfood/real-api-full-dogfood-sweep-report-2026-05-27.md](docs/dogfood/real-api-full-dogfood-sweep-report-2026-05-27.md) |
| 最新审计 | [docs/audit/global-readonly-audit-2026-05-27.md](docs/audit/global-readonly-audit-2026-05-27.md) |
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
