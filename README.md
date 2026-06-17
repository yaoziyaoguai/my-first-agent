# my-first-agent

First Agent 是一个 local-first 的 Agent Runtime 项目。S1（Baseline Usable Product / 基本可用产品版）已完成并归档；当前进入 S2 起点：保留真实 runtime 主链路、测试保护网和当前权威文档，让现有能力可以运行、解释、验收并继续增强。

**当前权威入口：[docs/current/S2_BASELINE_STATUS.md](docs/current/S2_BASELINE_STATUS.md)**（S2 起点现状审计）。S2 目标见 [docs/current/S2_GOAL.md](docs/current/S2_GOAL.md)（待确认）；S1 已归档至 [docs/history/S1_BASELINE_USABLE_PRODUCT/](docs/history/S1_BASELINE_USABLE_PRODUCT/)。

## 当前状态

- 阶段：**S1 已完成并归档；S2 起点现状已审计**（见 [docs/current/S2_BASELINE_STATUS.md](docs/current/S2_BASELINE_STATUS.md)），不是历史 demo、sprint 或旧 v1/v2/v3 目标。
- 主入口：`main.py` → `agent/core.py` → `agent/loop.py`。
- 工具执行：`agent/tool_runtime_mediator.py` → `agent/tool_executor.py`。`TOOL_INVOKE` dispatcher path 只记录 evidence，不直接执行工具。
- Memory v0：`agent/memory_runtime.py` / `agent/memory_contracts.py` / `agent/evidence_recorder.py`。
- Skill lifecycle：`agent/skill_system/` + `agent/runtime_integration/skill_lifecycle.py`。
- Sub-agent v0：`agent/runtime_integration/subagent_action.py` + `agent/subagent_system/v0_contract.py`。
- Legacy L1/L2 subagent route 保留为 compatibility/frozen，不是当前 production route。

## 快速开始

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
.venv/bin/python main.py --plain
```

配置模板：

```bash
cp config/config.example.yaml config/config.yaml
```

更多配置示例在 `config/examples/`。`config/config.yaml` 是个人本地配置入口；如果包含真实 key，**不得 commit**。.env / legacy provider profile 只作为历史兼容语境，不是推荐主路径。

## 常用命令

```bash
.venv/bin/python main.py --plain
.venv/bin/python main.py --tui
.venv/bin/python main.py health
.venv/bin/python main.py logs --tail 50
.venv/bin/python -m pytest tests/ -q
```

`--shell` 已弃用，只保留兼容。Health: python main.py health；Logs: python main.py logs --tail 50。

当前为 **safe-local** 默认：默认不调用真实 API、不访问网络、不需要 API key。Skill / MCP / SubAgent / Scheduler 在 S1 中只要求边界清楚，不默认全量生产激活，not a full Textual IDE；演示 skill：`demo-note-maker`；历史能力状态文件名为 `CURRENT_CAPABILITY_STATUS.zh.md`，当前权威口径见 [docs/current/S2_BASELINE_STATUS.md](docs/current/S2_BASELINE_STATUS.md) 与归档 [docs/history/S1_BASELINE_USABLE_PRODUCT/S1_GOAL.md](docs/history/S1_BASELINE_USABLE_PRODUCT/S1_GOAL.md)。

## 文档导航

| 想了解 | 读这里 |
|---|---|
| S 系列版本语义 | [docs/current/S_ROADMAP.md](docs/current/S_ROADMAP.md) |
| S2 起点现状审计 | [docs/current/S2_BASELINE_STATUS.md](docs/current/S2_BASELINE_STATUS.md) |
| S2 目标（待确认） | [docs/current/S2_GOAL.md](docs/current/S2_GOAL.md) |
| S2 gap（待生成） | [docs/current/S2_GOAL_GAP.md](docs/current/S2_GOAL_GAP.md) |
| 技术债 | [docs/current/TECH_DEBT.md](docs/current/TECH_DEBT.md) |
| 执行日志 | [docs/current/WORK_LOG.md](docs/current/WORK_LOG.md) |
| S1（已归档）目标 / backlog / 验收 / 审计 | [docs/history/S1_BASELINE_USABLE_PRODUCT/](docs/history/S1_BASELINE_USABLE_PRODUCT/) |

## 测试

```bash
.venv/bin/ruff check .
.venv/bin/python -m pytest -q -rx
git diff --check
```

## 安全边界

- 不读取或提交真实 `.env`、`agent_log.jsonl`、sessions/runs、真实 MCP config、真实 skill/subagent 目录或 private data。
- 不输出 secret，不展开环境变量里的 secret。
- 不默认调用真实 provider、真实 MCP endpoint 或真实外部服务。
- 不提交 `config/config.yaml`、`.codex/hooks.json`、`graphify-out/` 或本地 generated artifacts。
