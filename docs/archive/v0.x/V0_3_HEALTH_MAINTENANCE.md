# Runtime v0.3 · Health Maintenance

> 范围：`python main.py health` / `python main.py health --json` 的人工维护入口。
> 这是只读报告，不会自动删除、归档或修改 logs / sessions / checkpoints /
> workspace。

## 使用方式

```bash
python main.py health
python main.py health --json
```

报告会列出每个 check 的 `status` / `current_value` / `path` / `risk` /
`action`。`warn` 表示维护建议，不表示 Runtime 不能继续使用。

## 当前检查项

| Check | 含义 |
|---|---|
| `workspace_lint` | `workspace/` 中 Agent 生成的 Python 文件是否有 lint 问题 |
| `backup_accumulation` | `.bak` 文件是否堆积过多 |
| `log_size` | `agent_log.jsonl` 是否过大 |
| `session_accumulation` | `sessions/*.json` 是否堆积过多 |

## Logs 联动

`log_size` 出现 warning 时，先用 logs viewer 看摘要：

```bash
python main.py logs --tail 100
```

确认旧日志已经不需要继续在线排查后，再按 health 报告打印的 `mv` 命令人工归档。
Runtime 不会自动移动或删除这些文件。

## 明确不做

- 不自动删除 `agent_log.jsonl` / `sessions/` / checkpoint / `workspace/`
- 不实现 health TUI 面板或实时刷新
- 不接 Prometheus / Grafana / SRE pipeline
- 不展示 `.env`、key、private key、raw provider response 或完整 checkpoint dict

历史手动维护命令仍可参考 `docs/V0_2_HEALTH_MAINTENANCE.md`；v0.3 的入口以
本文件和 `docs/V0_3_BASIC_SHELL_USAGE.md` 为准。
