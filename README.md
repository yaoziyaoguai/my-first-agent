# my-first-agent

First Agent 是一个 local-first 的 Agent Runtime 实验项目。当前仓库目标是保留真实实现、测试保护网和少量准确文档，减少旧计划和错误方向对后续 Agent 的干扰。

**当前状态入口：[docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md)**。如果其他文档与它冲突，以 `PROJECT_STATUS.md` 为准。

## 当前状态

- 阶段：**developer prototype / local development**，不是面向普通用户的产品。
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

当前为 **safe-local** 默认阶段：默认不调用真实 API、不访问网络、不需要 API key。Skill System 仍为 **实验性**（历史状态说明见 `docs/archive/v0.x/V0_3_SKILL_SYSTEM_STATUS.md`），**not a full Textual IDE**。演示 skill：`demo-note-maker`。能力状态：`CURRENT_CAPABILITY_STATUS.zh.md`。

## 文档导航

| 想了解 | 读这里 |
|---|---|
| 当前状态 | [docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md) |
| 当前能力 | [docs/00-overview/CURRENT_CAPABILITY_STATUS.zh.md](docs/00-overview/CURRENT_CAPABILITY_STATUS.zh.md) |
| 文档入口 | [docs/README.zh.md](docs/README.zh.md) |
| 工程流程 | [docs/dev/AUTO_RUN_WORKFLOW.md](docs/dev/AUTO_RUN_WORKFLOW.md) |
| 审计入口 | [docs/06-audit/CURRENT_AUDIT_STATUS.zh.md](docs/06-audit/CURRENT_AUDIT_STATUS.zh.md) |
| 历史文档 | [docs/archive/](docs/archive/) |

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
