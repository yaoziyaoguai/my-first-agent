# Runtime v0.3.2 · Local Trial Checklist

> 范围：这是给本地学习型试用的一页短清单，用来记录一次真实使用是否顺手。
> 它不是完整 Textual IDE 手册，也不是成熟 Skill runtime、sub-agent 或
> Reflect / Self-Correction 路线图。

## 0. 边界

- 当前交互是 basic CLI shell / TUI-like stdout：`python main.py` 或
  `python main.py --shell`。
- Skill 仍是 experimental / demo-level prompt scaffold，不要按成熟 runtime 试用。
- v0.3 不做完整 Textual 多面板、slash command、sub-agent、Reflect /
  Self-Correction、generation cancellation / stream abort、complex topic switch。
- health/logs 只读：不会自动删除 `agent_log.jsonl`、`sessions/`、checkpoint 或
  `workspace/`。

## 1. 必跑清单

| # | 场景 | 操作 | 观察点 |
|---|---|---|---|
| 1 | 启动 shell | `python main.py --shell` | session/cwd/health/logs/resume/Skill experimental 可见 |
| 2 | 普通 final answer | 输入一个不需要工具的问答任务 | 任务完成后不进入 `awaiting_user_input` |
| 3 | request_user_input | 输入信息不足的多步任务，观察是否明确等待补充 | 只在 `request_user_input` 路径等待用户，不靠 final answer 问号猜状态 |
| 4 | tool success | 让 Agent 计算 `100*100` 或读取 `README.md` | 显示 `tool.completed` / `执行完成。` |
| 5 | policy denial | 让 Agent 读取 `~/.env` 或 `/tmp/server.pem` | 显示 `tool.rejected`，不能显示成执行完成 |
| 6 | user rejection | 触发写文件确认后输入 `n` | 显示 `tool.user_rejected`，不能和 policy denial 混淆 |
| 7 | tool failure | 让 Agent 读取不存在文件 | 显示 `tool.failed` / `执行失败。` |
| 8 | checkpoint/resume | 在 awaiting confirmation/input 时中断后重启 | resume 三态可读；pending tool 预览脱敏、不裸打 dict |
| 9 | health | `python main.py health` 和 `python main.py health --json` | warn 是维护提醒；action 是人工命令，不自动清理 |
| 10 | logs | `python main.py logs --tail 5` | 单行摘要可读；无 raw prompt/result/system_prompt/secret |

## 2. 反馈记录格式

每个问题只记这 6 项，方便归类：

```text
现象：
命令/输入：
期望：
实际：
是否阻塞：yes/no
建议归类：v0.3.2 blocking / v0.3.x patch / v0.4 planning
```

## 3. 归类规则

- **v0.3.2 blocking**：启动失败、普通 shell 卡死、工具四分类混淆、secret 泄漏、
  checkpoint/resume 裸输出内部对象。
- **v0.3.x patch**：文案不清楚、health/logs 入口难找、status line 信息不足、
  request_user_input 提示不够明确。
- **v0.4 planning**：Event-driven State Transition、RuntimeEvent / DisplayEvent /
  CommandResult 边界继续收敛、checkpoint schema 边界强化、observer/logs 更结构化、
  更系统的本地试用反馈闭环。
