# Local Manual Dogfood Checklist

预计耗时: 10-20 分钟
目标: 验证 First Agent 在 fake/local 安全路径下的核心交互闭环

> 本 checklist 仅使用 FakeProvider（deterministic fake provider），不调用真实 LLM、不访问网络、
> 不需要 API key。所有操作均在本地安全沙箱内完成。

## 前置条件

```bash
cd /Users/jinkun.wang/work_space/my-first-agent
git status -sb          # 确认在 main，working tree clean
.venv/bin/python -c "from agent.provider.fake_provider import FakeProvider; print('ok')"
```

## Checklist

### 1. Onboarding / Help

```bash
.venv/bin/python main.py --help
```

交互模式内：

```
help
```

**期望结果**: 显示能力说明和限制声明，包含 FakeProvider、SubAgent、Memory、Tool 状态。

### 2. 普通对话

```
你好，今天怎么样？
```

**期望结果**: FakeProvider 回显用户消息（"已收到你的消息：「你好，今天怎么样？」"），stop_reason="end_turn"。

### 3. 触发 Demo Tool（Tool Pipeline 验证）

```
帮我创建一个 demo note
```

或

```
make a demo note
```

**期望结果**: 
- 看到 tool_use 触发提示（"触发 demo.write_demo_note，将通过 Tool Pipeline 执行"）
- `workspace/demo/` 下生成 `note.md` 文件
- 文件内容包含 run_id 和 "core.chat() → FakeProvider → Tool Pipeline" 路径

### 4. 查看记忆列表

```
show memories
```

或

```
查看记忆
```

**期望结果**: 显示记忆列表（可能为空），每条记忆显示短 ID（前8位，可直接复制用于 forget）、来源类型（source_type）、时间（created_at，缺失时显示 unavailable）。

### 5. 查看子代理列表

```
show subagents
```

或

```
查看子代理
```

**期望结果**: 显示可用的子代理列表（至少含 demo-stat）。

### 6. CLI 委托子代理

```
delegate to demo-stat: count files in workspace
```

或

```
委托 demo-stat: 统计 workspace 文件数
```

**期望结果**:
- 看到进度事件：`正在委托子代理 demo-stat 执行: ...`
- 看到完成事件：`子代理 demo-stat 完成`
- 返回统计结果摘要

### 7. 自然语言委托子代理

```
帮我统计 demo workspace
```

或

```
summarize demo workspace files
```

**期望结果**: 与 CLI 委托相同——自动识别意图，路由到 demo-stat 执行。CLI 和 NL 委托均会在 run summary 中显示 subagent name。

### 8. 忘记记忆

先确认有哪些记忆（`show memories`），复制输出中显示的短 ID（前8位），然后：

```
forget id:<短ID>
```

或按关键词：

```
忘记 <关键词>
```

**期望结果**:
- 按短 ID 删除：看到 `已移除记忆（ID: <短ID> → <完整ID>）`（前缀匹配成功）
- 如果短 ID 前缀匹配到多条：看到 ambiguity 提示及匹配到的 ID 列表，不会误删
- 如果 ID 不存在：看到 `未找到 ID 为「xxx」的记忆`
- 按关键词删除：看到 `已移除 N 条记忆（匹配「关键词」）`

### 9. 退出

```
quit
```

或

```
exit
```

**期望结果**: 正常退出，无异常。

## 如何报告失败

如果任何步骤未产生期望结果，记录以下信息：

1. 失败的步骤编号和输入
2. 实际输出（复制粘贴完整输出）
3. `.venv/bin/python -m pytest tests/ -x -q` 的测试结果
4. `git log --oneline -3` 的 commit 状态

## 已知限制（诚实声明）

- 所有对话由 FakeProvider 处理——响应是 deterministic 模板化回显，不是真实 LLM 语义理解
- Tool use 是 deterministic 关键词匹配，不是真实 tool_use 推理
- SubAgent delegation（CLI 和 NL）是 local/fake deterministic 关键词匹配，不经过 LLM
- Memory 使用 local/fake store，不读取真实 memory episodes
- Streaming 是 fake/demo 12-char chunking，不是真实 provider SSE streaming
- Progress 事件（subagent.delegating/delegated, memory.forgotten）是 fake/local 路径下的事件
- 以上所有能力不调用真实 API、不联网、不需要 API key
