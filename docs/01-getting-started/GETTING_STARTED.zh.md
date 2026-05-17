# Getting Started

这篇文档解决什么问题：帮助新开发者在本地安装、运行 fake/local demo、执行常用检查，并理解哪些命令不会触碰真实 secret。

不解决什么问题：不指导配置真实 LLM key，不指导 real MCP server，不指导发布或推送。

推荐读者：第一次接手项目的新开发者、Coding Agent。

## 环境要求

- Python 3.10+，推荐 3.12。
- macOS / Linux shell；Windows 建议 WSL。
- 本地测试不需要真实 API key。

## 安装

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

如果只做文档或只读审计，不需要安装新依赖。不要 `pip install` 未经确认的新包。

## 运行 fake/local demo

```bash
.venv/bin/python main.py demo "create a demo note about today's local run"
```

这个 demo 的边界：

- 不读取 `.env`。
- 不读取 `agent_log.jsonl`。
- 不读取真实 `sessions/` / `runs/`。
- 不调用真实 LLM。
- 不访问网络。
- 只在显式 workspace 中写 demo artifact。

## 运行交互 CLI

```bash
.venv/bin/python main.py
```

交互 CLI 会进入 Parent Agent Runtime。若未配置真实 provider，部分真实模型路径不可用；测试和 synthetic dogfood 不依赖真实 provider。

## 常用维护命令

```bash
.venv/bin/python main.py health
.venv/bin/python main.py health --json
.venv/bin/python main.py logs
.venv/bin/python main.py logs --tail 100
```

注意：`logs` 是用户主动维护命令。审计任务中不要读取 `agent_log.jsonl` 正文，除非用户明确允许。

## 测试

```bash
ruff check agent tests scripts
python -m pytest tests/ -x -q
```

如果需要隔离 HOME：

```bash
HOME=/private/tmp/my-first-agent-test-home python -m pytest tests/ -x -q
```

更多测试命令见 [TEST_MATRIX.zh.md](../05-testing-dogfood/TEST_MATRIX.zh.md)。

## Synthetic dogfood

```bash
python scripts/dogfood_skill_system.py --tmp-root /tmp/my-first-agent-skill-dogfood --mode synthetic
python scripts/dogfood_subagent_system.py --tmp-root /tmp/my-first-agent-subagent-dogfood --mode synthetic
```

Real API dogfood 是 gated：默认不跑，不在没有用户明确允许时读取 `.env` 或调用真实 provider。

## 故障排查

| 现象 | 处理 |
|---|---|
| `Missing ANTHROPIC_API_KEY` | 只有真实 CLI provider 需要 key；跑 tests / synthetic dogfood 不需要 |
| `health` 有 warn | 多数是维护提示，不等于 runtime 失败 |
| checkpoint resume 提示 | 由 `agent/session.py` 判断是否 actionable；不要手动改 checkpoint schema |
| Textual 未安装 | simple CLI fallback 仍可用；不要为文档任务安装新依赖 |
| Real provider smoke skipped | 正常；real provider 测试默认 opt-in |
