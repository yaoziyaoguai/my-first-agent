# Manual Human Dogfood Next Steps

本页只描述用户准备好时的最短人工 dogfood 路径。今晚 AutoRun 不需要等待人工验证。

## 当前边界

- Agent-driven rehearsal 不是人工 dogfood。
- fake/local rehearsal 已通过，可作为人工验证前的安全 baseline。
- Real provider 当前受 401 config/auth concern 阻塞；人工 dogfood 默认不要走真实 API。
- 不读取 `.env`，不粘贴 secret，不调用真实 LLM。

## 最短路径（fake/local）

```bash
cd /Users/jinkun.wang/work_space/my-first-agent
git status -sb
.venv/bin/python main.py --help
.venv/bin/python main.py
```

进入交互模式后依次输入：

```text
你好，今天怎么样？
make a demo note
show memories
show subagents
delegate to demo-stat: count files in workspace
remember my name is Alice
quit
```

## 记录方式

只记录用户实际感受和异常现象：

- 哪一步看不懂
- 哪个提示容易误解
- tool approval 文案是否清楚
- memory confirmation 是否容易理解
- tool result 和 run summary 是否足够可见
- 是否出现 crash、卡住、重复提示或不可信输出

需要正式记录时，使用 [manual-human-dogfood-record-template.md](manual-human-dogfood-record-template.md) 的结构。不要复制 API key、token、真实私人资料或完整敏感日志。

## Real Provider

Real provider dogfood 只有在用户明确修复并验证 API key、endpoint、model 兼容性后再做。当前 401 是 config/auth concern，不应在 AutoRun 中重试真实 API。
