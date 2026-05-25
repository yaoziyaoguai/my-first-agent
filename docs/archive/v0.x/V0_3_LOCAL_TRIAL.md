# Runtime v0.3.x · Local-First Manual Trial Guide

> 本文件目的：让外部读者 clone 仓库后，在 5-10 分钟内能在自己机器上把
> `my-first-agent` 跑起来，并且**不被未完成的能力（Skill / sub-agent /
> Reflect / 完整 TUI）误导**。
>
> 本仓库是 **local-first** 学习项目：没有云端服务、没有 SaaS、没有远程
> agent service、没有多人协作。所有运行都在你自己机器上。

---

## 1. 试用范围（明确边界）

`my-first-agent` v0.3.x 适合：

- 在本地用一个简单 CLI 让 Agent 完成基础任务（读文件、写文件、跑 shell、
  做规划）
- 观察一个最小 Agent Runtime 的工程化：状态机、checkpoint、事件日志、
  健康检查、CLI 输出契约
- 学习「如何把一个最小 LLM 闭环从能跑做到可观测、可维护」

`my-first-agent` v0.3.x **不**适合：

- 当作生产 Agent 框架使用
- 部署成 SaaS / 多人服务
- 当作 Skill 平台（Skills 是 prompt 注入级别的实验脚手架）
- 当作 sub-agent / multi-agent 协作框架（v1.0 才规划）
- 期待 Reflect / Self-Correction / LLM judge 能力（明确 out of scope）
- 期待完整 Textual 多面板 / generation cancel / Esc cancellation
- 期待 slash command 体系（v0.1 已下线，不会复活）

---

## 2. 准备环境

### 2.1 prerequisites

- Python **3.10 或更高**（开发环境是 3.12）
- macOS 或 Linux shell（Windows 推荐 WSL）
- Anthropic API key（**可选**：仅在你想用真实模型驱动主循环时需要）

### 2.2 clone + venv + install

```bash
git clone <repo-url>
cd my-first-agent

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2.3 配置 .env（可选）

```bash
cp .env.example .env
# 用编辑器打开 .env，按需填写 ANTHROPIC_API_KEY / ANTHROPIC_MODEL
```

`.env` 已在 `.gitignore`，不会被你的 git push 上传。`.env.example` 只是
变量名模板，不含真实 key。

如果你**不填** `ANTHROPIC_API_KEY`：
- 你仍然可以跑全套测试（`pytest -q`）
- 你仍然可以跑 LLM Processing CLI 的 fake provider
- 主对话循环会因缺 key 提示并退出

---

## 3. 跑起来

### 3.1 主对话循环

```bash
.venv/bin/python main.py
```

启动后看到结构化 banner、session id、cwd、health 单行、Skill 实验性提示、
resume 三态。然后输入任务（中文/英文均可）。

输入 `quit` 退出。

### 3.2 健康维护报告

```bash
.venv/bin/python main.py health           # 人类可读
.venv/bin/python main.py health --json    # 机器可读
```

每项检查都展示 `current_value` / `path` / `risk` / 推荐命令。Runtime
**永不**自动归档或删除 `agent_log.jsonl` / `sessions/` / `workspace/`。

### 3.3 日志查看

```bash
.venv/bin/python main.py logs                          # 默认 tail 50
.venv/bin/python main.py logs --tail 100
.venv/bin/python main.py logs --session <id-prefix>
.venv/bin/python main.py logs --event tool_executed
.venv/bin/python main.py logs --tool calculate
.venv/bin/python main.py logs --include-observer       # 显式打开极噪事件
```

输出是单行紧凑摘要，**不会**展示原始 prompt / completion / system_prompt /
api key / 私钥；命中 `sk-ant-` / `BEGIN PRIVATE KEY` / `api_key=…` 等模式
会被替换为 `[REDACTED]`。

### 3.4 LLM Processing CLI（独立子命令，不用 API key）

```bash
.venv/bin/python main.py scan README.md            # 只输出文件元数据
.venv/bin/python main.py preflight                 # 默认 fake provider
.venv/bin/python main.py process README.md         # 默认 fake provider
.venv/bin/python main.py status
```

详见 `docs/LLM_PROCESSING_CAPABILITY_MATRIX.md`。

### 3.5 跑测试

```bash
.venv/bin/python -m ruff check agent/ tests/ llm run_logger.py main.py
.venv/bin/python -m pytest -q
```

预期：ruff 0 错；约 691 passed, 3 xfailed（3 个 xfail 都属于 v0.4+ 未启动
能力，每个都有归属说明）。

---

## 4. 本地会产生什么文件？

| 路径 | 说明 | 是否 gitignore |
|---|---|---|
| `agent_log.jsonl` | 运行时事件日志 | ✅ |
| `sessions/` | session checkpoint 快照 | ✅ |
| `state.json` | 当前 checkpoint 指针；idle 时自动清理 | ✅ |
| `runs/`、`summary.md` | LLM Processing 产物（用 process 才有） | ✅ |
| `workspace/` | 工具写入沙箱 | ✅ |
| `memory/` | 项目内嵌的学习记录（仓库自带） | 已跟踪 |
| `skills/` | 实验性 skills 目录（仓库自带 demo） | 已跟踪 demo |
| `.env` | 你的本地 provider 配置 | ✅ |

如果你 fork 后 push，上面打 ✅ 的产物**不会**被上传。

---

## 5. 如果出问题

- **缺 API key**：基本 CLI shell 需要 `ANTHROPIC_API_KEY`；测试与 LLM
  Processing fake provider 不需要。
- **health 显示 warn**：维护警告而非崩溃，按建议命令处理即可。
- **Skill 不工作**：v0.3 的 Skill 是 prompt 注入级实验脚手架，没有
  marketplace、没有 sub-agent、没有 skill 级 tool 权限白名单；详见
  `docs/V0_3_SKILL_SYSTEM_STATUS.md`。
- **模型 final answer 末尾追问但 Runtime 直接完成**：v0.3 patch 已修
  protocol；如果模型仍如此输出，更新到当前 v0.3.x 版本即可。详见
  `docs/CLI_OUTPUT_CONTRACT.md` §14。
- **测试失败**：先确认 Python 版本、virtualenv、依赖完整、ruff 版本
  匹配 `requirements.txt`。

---

## 6. 不要做的事

- ❌ 不要把 `.env` / `state.json` / `agent_log.jsonl` / `sessions/` /
  `runs/` / `summary.md` 提交进 git
- ❌ 不要把这个项目当作生产 agent 框架
- ❌ 不要在 Skill 子系统上做产品化设计（仍是实验脚手架）
- ❌ 不要期待 sub-agent / Reflect / Self-Correction / 完整 TUI / Esc
  cancel / topic switch / slash command（明确 out of scope）

---

## 7. 进一步阅读

- `README.md` — 项目入口与 v0.1/v0.2/v0.3 状态摘要
- `RELEASE_NOTES_v0.3.md` — v0.3 已交付能力 + 显式不做的事
- `docs/V0_3_PLANNING.md` — v0.3 milestone 与完成标准
- `docs/V0_3_MANUAL_SMOKE_RESULT.md` — v0.3 release 前的人工 smoke 记录
- `docs/V0_3_LOCAL_TRIAL_CHECKLIST.md` — v0.3.2 本地试用任务清单
- `docs/V0_3_BASIC_SHELL_USAGE.md` — Basic CLI Shell 详细使用
- `docs/V0_3_OBSERVER_LOGS.md` — logs 子命令的脱敏边界
- `docs/V0_3_SKILL_SYSTEM_STATUS.md` — Skill 是什么 / 不是什么
- `docs/CLI_OUTPUT_CONTRACT.md` — CLI 输出契约（含 §14 协议边界）
- `docs/V0_3_HEALTH_MAINTENANCE.md` — health 入口与手动维护边界
- `docs/V0_4_PLANNING.md` — v0.4 候选主线（**仅 planning，不是承诺**）
