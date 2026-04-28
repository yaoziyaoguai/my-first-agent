# Runtime v0.3 · 基础 CLI Shell 使用指南（Basic Shell Usage）

> **范围**：v0.3 M1（基础 CLI Shell）+ M2 (health) + M3 (skill 状态澄清) +
> M4 (logs viewer) 落地后的人工日常使用方式。**不是**完整 Textual TUI 手册——
> 那个仍在 v0.4+ backlog。

---

## 1. 启动主对话

```bash
python main.py
```

启动屏会显示结构化 header（详见 `docs/CLI_OUTPUT_CONTRACT.md` §12.1）：

```
────────────────────────────────────────────────────────────
  Runtime v0.3 M1 shell
────────────────────────────────────────────────────────────
  session : c45e7e01  (full: c45e7e01-e427-4498-8301-025b7bb0217f)
  cwd     : /your/project
  health  : 3 warn (workspace_lint, log_size, session_accumulation); 详情：python main.py health
────────────────────────────────────────────────────────────
  输入 'quit' 退出。
  Skill 是实验性能力（v0.3 M3 状态澄清，详见 docs/V0_3_SKILL_SYSTEM_STATUS.md）。

  📭 resume : 未发现断点，可以直接开始新任务。
你: 
```

关键边界：
- header 是**单屏**结构化输出，不会刷屏。
- health 是**单行摘要**，不展开长块；想看详情走子命令（见 §3）。
- Skill 文案明确**实验性**，不假装成熟（M3 修复了 v0.2 的误导性
  `/reload_skills` 提示）。
- resume 三态都有可见提示：无 checkpoint / idle 残留已清理 / actionable 任务。

---

## 2. 退出与中断

| 操作 | 行为 |
|---|---|
| 输入 `quit` | finalize 当前 session（保存快照），正常退出 |
| Ctrl+C 一次 | 按是否有 checkpoint 走 `handle_interrupt_*` 流程 |
| Ctrl+C 短时连按两次 | 强制 double-interrupt 退出 |
| EOF（Ctrl+D / pipe close） | finalize 后退出 |

---

## 3. 子命令一览

```bash
# Health 维护报告
python main.py health              # 结构化报告（含 risk + 建议命令）
python main.py health --json       # 机器可读 JSON（schema 稳定）

# Observer / logs 摘要查看（v0.3 M4）
python main.py logs                          # 默认 tail 50
python main.py logs --tail 100
python main.py logs --session abc12345       # session 短哈希前缀
python main.py logs --event tool_executed
python main.py logs --tool calculate
python main.py logs --include-observer       # 显式打开极噪事件类型
```

完整子命令清单与文案锁见 `docs/CLI_OUTPUT_CONTRACT.md` §13。

---

## 4. 工具结局四分类（v0.2 锁定，v0.3 不改）

人工 smoke 时区分以下四类输出：

| 结局 | event | 典型文案 | 触发场景 |
|---|---|---|---|
| 成功 | `tool.completed` | `执行完成。` | calculate 算式、read_file 项目内文件成功 |
| 失败 | `tool.failed` | `执行失败。` | read_file 不存在文件、未注册工具名 |
| 安全策略拒绝 | `tool.rejected` | `被安全策略拒绝：…` 或 `已被工具内部安全检查拒绝。` | read_file `~/.env`、write_file 含 `BEGIN PRIVATE KEY` |
| 用户拒绝 | `tool.user_rejected` | `用户拒绝执行，已跳过。` 或 `用户未批准，改为提供反馈意见。` | confirmation 弹出后输入 `n` |

详见 `docs/CLI_OUTPUT_CONTRACT.md` §8。

---

## 5. 人工 smoke 速查

| 场景 | 命令 / 输入 | 期望 |
|---|---|---|
| 启动屏结构化 | `python main.py`（quit 退出） | 见 §1 截图，不应有裸 dict |
| 健康报告 | `python main.py health` | 4 项 check 各自 status / current_value / path / risk / 建议命令 |
| Health JSON | `python main.py health --json \| python -m json.tool` | overall + checks 字段稳定 |
| 日志摘要 | `python main.py logs --tail 10` | 单行紧凑摘要，无 raw content |
| 工具拒绝事件 | `python main.py logs --event tool_blocked_sensitive_read --tail 5` | 历史 .env 拒绝事件 |
| Skill 文案 | `python main.py \| head -10` | 含「实验性」，不含 `/reload_skills` |
| calculate 成功 | 在主循环输入 `计算 100*100` | tool.completed，结果 10000 |
| read_file 失败 | 在主循环输入 `读 nonexistent.py` | tool.failed |
| read .env 拒绝 | 在主循环输入 `读 ~/.env` | tool.rejected（policy denial） |
| user 拒绝 | 触发需要确认的 write_file，输入 `n` | tool.user_rejected |

部分需要真实 API 的场景标记为 **manual-only**：calculate / read_file 的
完整端到端 LLM 流转。基础渲染契约由 ~650 项自动测试守护。

---

## 6. 与 v0.4+ 的边界

v0.3 基础 CLI Shell **不**包含：

- ❌ 完整 Textual 多面板 / 快捷键 / 滚动条
- ❌ Esc / generation cancellation / stream abort
- ❌ Sub-agent 调用
- ❌ Reflect / Self-Correction / LLM judge
- ❌ Topic switch（v0.1 已撤销）
- ❌ Slash command 复活
- ❌ 完整 Skill runtime（M3 已坦诚化为实验性）
- ❌ 自动归档/删除日志/session/checkpoint
- ❌ `--watch` / `--follow` 实时滚动 logs

以上都在 `docs/V0_3_PLANNING.md` §2 和各 milestone 的「不做」清单里。

---

## 7. 出问题如何定位

1. **启动屏异常** → 检查 `agent/cli_renderer.py` + `agent/session.py::init_session`
2. **health 报告字段缺失** → `agent/health_check.py` + `agent/health_report.py`
3. **logs viewer 报错** → `agent/log_viewer.py`，日志路径来自 `config.LOG_FILE`
4. **看到 `[REDACTED]`** → 是脱敏命中，意味着原始 jsonl 含历史明文遗留；
   按 `python main.py health` 给出的归档命令人工处理
5. **看到「损坏的 jsonl 行」** → viewer 已跳过；不影响其他事件

完整调试入口：`python main.py logs --tail 50` 永远是第一站。
