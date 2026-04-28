# Runtime v0.2 · 健康检查 warning 维护指南

本文件配套 `agent/health_check.py` 的三类 warning，给出**只读审计 + 安全归档/清理**
建议。所有命令默认不删除任何东西；任何破坏性操作都需要你手动确认后再执行。

> 范围说明：
> - 这只是 v0.2 RC push 前的健康维护说明，**不修改健康检查逻辑**。
> - 三类 warning 都**不属于 v0.2 RC blocking**（见 `docs/V0_2_RC_DECISION.md`）。
> - 对应的运行产物（`agent_log.jsonl` / `sessions/` / `workspace/`）已经在
>   `.gitignore` 内，不会被误提交。
> - v0.2 release 收口新增 `python main.py health` 子命令，可独立跑健康检查
>   而不进入主对话循环：
>   ```bash
>   .venv/bin/python main.py health
>   ```

## 1. workspace_lint

**来源**：`agent/health_check.py::check_workspace_lint`
对 `workspace/**/*.py` 跑 `ruff check`，有任何 lint 错误就 warn。

**当前状态**：
- `workspace/` 下约 7 个 `.py` 文件（agent 自身写出的 scratch 输出）
- 例：unused import `os` 等典型 lint 错误
- `workspace/` 整体在 `.gitignore` 内，不会进 commit

**安全处理建议**：
```bash
# 只读：看具体哪些文件出问题
.venv/bin/python -m ruff check workspace/
```
- **不要**自动 `--fix`：这些是历史会话 agent 写出的样本，可能是有意保留的「坏代码示例」（比如 `bad.py` / `evil.sh`）。
- 真要清理时，**人工**判断哪些是过期 scratch、哪些是测试 fixture，再手工 `rm`。

## 2. log_size

**来源**：`agent/health_check.py::check_log_size`
`agent_log.jsonl` 超过 10MB 就 warn。

**当前状态**：
- `agent_log.jsonl` ≈ 96MB（约 18w+ 行）
- 已在 `.gitignore`
- v0.2 RC 已复核：**未发现真实 sk-ant- key 泄漏**（`grep -E 'sk-ant-[A-Za-z0-9_]{20,}' agent_log.jsonl` = 0 hits）

**安全归档建议**（**人工执行**，本文件不会自动跑）：
```bash
# 1) 归档当前日志为带时间戳的副本
mv agent_log.jsonl "agent_log.jsonl.bak.$(date +%Y%m%d-%H%M%S)"

# 2) 让程序下次启动时新建空日志即可（不需要主动 touch）

# 3) 可选：把 .bak 移到 ~/Documents/my-first-agent-archives/ 或外部备份盘，
#    不要进项目目录，避免 backup_accumulation 触发新 warning
mkdir -p ~/Documents/my-first-agent-archives/
mv agent_log.jsonl.bak.* ~/Documents/my-first-agent-archives/
```

**未来 milestone（不属于 v0.2 RC 范围）**：
- 在 `agent/logger.py` 引入按大小或按日期的 rotation。
- 不要为了消除 warning 在 v0.2 RC 内大改 logger。

## 3. session_accumulation

**来源**：`agent/health_check.py::check_session_accumulation`
`sessions/*.json` 超过 50 个就 warn。

**当前状态**：
- `sessions/` 下约 125 个 session 快照
- 已在 `.gitignore`

**安全归档建议**（**人工执行**）：
```bash
# 1) 看看每个 session 大小分布
ls -lh sessions/ | head

# 2) 归档而不是删除
mkdir -p ~/Documents/my-first-agent-archives/sessions/
mv sessions/*.json ~/Documents/my-first-agent-archives/sessions/

# 3) 如果你只想保留最近 N 个：
#    （示意，不要在没有 review 的情况下直接跑）
ls -t sessions/*.json | tail -n +51 | xargs -I {} mv {} ~/Documents/my-first-agent-archives/sessions/
```

**未来 milestone（不属于 v0.2 RC 范围）**：
- 引入 session retention 策略（按数量或按时间裁剪）。
- 不要为了消除 warning 在 v0.2 RC 内删除你的历史会话。

## 4. 防误提交保护（已生效）

`.gitignore` 当前覆盖：

```
.env
agent_log.jsonl
sessions/
workspace/
memory/
skills/
blog/
summary.md
state.json
runs/
```

push 前可手动复核一次：
```bash
git ls-files | grep -iE '\.env$|^state\.json$|^summary\.md$|^runs/|^sessions/|agent_log|^workspace/|memory/checkpoint'
# 预期空输出（除 .env.example 这种安全模板外）
```
