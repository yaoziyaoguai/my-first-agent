# Runtime v0.3 M4 · Observer / Logs 可读性 MVP

> **范围声明**：M4 是「让现有 jsonl 日志可读」的最小工具，**不是 observability
> 平台**。不引入新存储、不做 LLM judge、不自动删除任何东西。

---

## 1. 现状（M4 接手时的事实）

| 文件 | 大小 / 数量 | 写入者 | 提交? |
|---|---|---|---|
| `agent_log.jsonl` | ~93 MB / 207k 行 | `agent/logger.py::log_event` | ❌ gitignored |
| `sessions/session_<uuid>.json` | ~129 个 | `agent/logger.py::save_session_snapshot` | ❌ gitignored |
| `memory/checkpoint.json` | 单文件 | `agent/checkpoint.py` | ❌ gitignored |
| `runs/*.jsonl` | LLM Processing 审计 | `run_logger.py` | ❌ gitignored |

事件类型分布（top 10）：
```
179916 runtime_observer        ← 占 86%，对人工调试基本无用，默认隐藏
 13009 plan_generated
  6888 plan_skipped
  2882 checkpoint_saved
   926 context_compression_start
   770 tool_requested
   718 tool_executed
   682 llm_call
   666 llm_response
   376 plan_error
```

---

## 2. M4 入口

```bash
# 默认：最近 50 条非 observer 事件
python main.py logs

# 自定义条数
python main.py logs --tail 100

# 按 session 前缀过滤（短哈希 8 位即可）
python main.py logs --session abc12345

# 按事件类型过滤
python main.py logs --event tool_executed
python main.py logs --event tool_blocked_sensitive_read

# 按工具名过滤
python main.py logs --tool calculate

# 显式打开 runtime_observer（噪声大，慎用）
python main.py logs --include-observer --tail 20

# 多条件叠加
python main.py logs --session abc12345 --event tool_rejected --tail 5
```

输出格式（单行紧凑）：
```
<ISO timestamp> [<short_session>] <event>  <safe metadata>
```

示例：
```
2026-04-09T22:25:25.468359 [c2aa2d98] tool_blocked_sensitive_read  tool=read_file path=.env
2026-04-21T23:31:48.339315 [3a7a8d5a] tool_executed  tool=fetch_url result_len=8593
```

---

## 3. 渲染层做了什么

实现位于 `agent/log_viewer.py`，纯函数模块，不写日志、不读 checkpoint。

每类事件**显式枚举允许字段**（`_format_data_summary`），不走 `json.dumps(data)`
fallback。这样 raw content / raw tool_result / system_prompt 永远不会经
viewer 流到 stdout。

| Event | 展示字段 | **不展示** |
|---|---|---|
| `user_input` | `len=N` | content |
| `agent_reply` | `len=N` | content |
| `session_start` | `system_prompt_len=N` | system_prompt 正文 |
| `tool_requested` | tool, path/expression/url/name | content (write_file 正文) |
| `tool_executed` | tool, result_len | result (read_file 正文) |
| `tool_rejected` | tool | input |
| `tool_blocked*` | tool, path | — |
| `llm_call` | message_count | messages |
| `llm_response` | stop_reason | content |
| `checkpoint_saved` | step, message_count | conversation messages |
| `context_compression_done` | old_count, new_count | summary 正文 |
| `health_check` | warn 项名字列表 | 完整 issues 文本 |

未显式枚举的事件走 fallback：仅展示 dict 的标量字段（int/float/bool/str），
跳过嵌套 dict / list / `_FORBIDDEN_FIELDS`。

---

## 4. 防泄漏策略（核心）

历史 `agent_log.jsonl` 里**确实存在**早期未脱敏的 raw content（README 全文、
文件读写正文等）。M4 viewer 的安全边界是：

1. **第一道：白名单**。每个 event 显式枚举可展示字段；`_FORBIDDEN_FIELDS` 集
   合（`content / result / system_prompt / messages / summary / text /
   text_preview / raw_response / completion / prompt / issues`）永远不进入
   渲染。
2. **第二道：兜底脱敏**。`mask_secrets` 对最终单行输出再扫一遍：
   - `sk-ant-...` API key
   - `sk-...` 通用 API key
   - `BEGIN [...] PRIVATE KEY` PEM 头
   - `api_key= / password= / secret= / token=` 形式的赋值
3. **绝不递归 dump 嵌套 dict**。即便有人未来给一个新 event 写了
   `data = {"payload": {"deep": "<secret>"}}`，fallback 路径也不会展开它。
4. **不修改原 jsonl**。`render_logs` 只读，被测试 `test_render_logs_does_not_modify_log` 守护。

如果你在 logs 输出里看到 `[REDACTED]`，说明兜底脱敏命中了，**这是正常的**——
意味着原 jsonl 确实存在历史明文遗留，应在 review 后用 health 报告里的归档
命令把整个旧日志移走（不要 grep 进去贴出来）。

---

## 5. M4 与 health (M2) 的联动

M2 health 报告的 `log_size.action` 文案现在指向 logs viewer：
```
先看摘要再决定归档（不会自动执行，复制粘贴）：
  python main.py logs --tail 100        # v0.3 M4 摘要查看
  mv agent_log.jsonl agent_log.jsonl.bak.<时间戳>
  ...
```

意图：用户先用 logs viewer 确认「这段日志值不值得归档」，再人工执行 mv。
**Runtime 永不自动归档或删除任何用户日志/session/checkpoint。**

---

## 6. 显式非目标

- ❌ 不实现 `--watch` / `--follow` 实时滚动（用 `watch -n 1 'python main.py logs --tail 20'` 即可）
- ❌ 不实现 `--from <date>` / `--until <date>` 时间范围过滤（M4 范围之外）
- ❌ 不实现按事件类型聚合统计（不引入 metric pipeline）
- ❌ 不实现 LLM judge / 自动归因 / 异常检测
- ❌ 不引入 SQLite / DuckDB / ELK / 任何索引存储
- ❌ 不重写 `agent/logger.py::log_event` 写路径
- ❌ 不删除任何用户日志/session/checkpoint
- ❌ 不引入 sub-agent / Reflect / generation cancellation / topic switch /
  slash command / Textual 多面板

---

## 7. 后续可考虑的扩展（不在 v0.3 范围）

如果将来真要把 observer/logs 做到下一步，下面是合理的入口：

1. **logger 写路径脱敏化**：在 `log_event` 里就拒绝写入 `_FORBIDDEN_FIELDS`，
   而不是只在 viewer 里防。这是更彻底的方案，但要重写 logger 调用点的合同。
2. **`--from / --until` 时间过滤**：解析 ISO timestamp。
3. **`logs stats`**：按 event / tool / session 统计 count / 平均延时。
4. **session 级 transcript 拼接**：把单 session 内的 user_input → tool_* →
   agent_reply 串成可读对话（注意此时**必须**先解决脱敏）。
5. **历史日志一键安全归档**：可选脚本，但默认 `--dry-run`，不自动执行。

以上每一项都需要单独 milestone + 用户确认，**不要悄悄加**。
