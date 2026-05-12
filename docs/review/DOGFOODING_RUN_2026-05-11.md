# Dogfooding Run Report — 2026-05-11

## 1. Summary

- **是否能完整启动**：能，但需手动设置 `export MODEL_NAME=deepseek-v4-pro`，否则启动崩溃
- **通过章节**：3 (demo/health/logs)、5 (tool call)、9 (memory 自动化)、10 (logs)、11 (error handling)
- **部分通过章节**：4 (对话可运行但 env var 需手动补)、6 (request_user_input 未在测试中成功触发)、7 (确认流程展示正常但管道 stdin 下 accept 路径未验证通过)、8 (resume 提示正常但完整恢复未验证)
- **失败章节**：无完全失败章节
- **是否适合进入真实自用**：**不建议**。需先修复 MODEL_NAME 配置不匹配和 runtime 未接入 FilesystemMemoryStore

## 2. Environment

| 项目 | 值 |
|------|-----|
| Python | 3.12.2 |
| 启动命令 | `export MODEL_NAME=deepseek-v4-pro && .venv/bin/python main.py` |
| 当前 commit | `942938e feat(memory): add filesystem memory store and recall API` |
| 使用真实 provider | 是（anthropic_native，deepseek-v4-pro） |
| OS | macOS Darwin 24.5.0 |
| Memory store | InMemoryMemoryStore（runtime 默认），非 FilesystemMemoryStore |

## 3. Test Matrix

| Area | Scenario | Command/Prompt | Expected | Actual | Result | Severity | Notes |
|------|----------|---------------|----------|--------|--------|----------|-------|
| 启动 | fake demo | `main.py demo "..."` | note.md 生成 | note.md 正确生成，2 trace events | pass | - | |
| 启动 | health check | `main.py health` | 结构化报告 | 3 warn（workspace_lint, log_size, session_accumulation），5 pass | pass | - | 391MB agent_log.jsonl, 148 sessions |
| 启动 | logs | `main.py logs --tail 10` | event 列表 | 正常输出，含 session_start/checkpoint_saved | pass | - | |
| 启动 | **shell 冷启动** | `main.py` | session banner | **崩溃**: `ValueError: model_name 必须是非空字符串` | fail | **P1** | config.py 读 MODEL_NAME，.env 用 ANTHROPIC_MODEL |
| 启动 | shell + MODEL_NAME | `MODEL_NAME=... main.py` | session banner | 正常启动，session id, cwd, health 摘要 | pass | - | 需手动 export MODEL_NAME |
| 对话 | 中文自我介绍 | "你好，请用中文介绍..." | 结构化中文回复 | 正确返回能力清单 | pass | - | |
| 对话 | 多轮上下文 | 追问上一轮内容 | 引用前文 | 未单独测试（管道 stdin 限制） | minor | P2 | |
| 工具调用 | run_shell 确认 | "列出当前目录 Python 文件" | 弹出确认提示 | 正确显示 `[需要确认工具调用]` + 工具名/参数预览 + y/n 提示 | pass | - | 状态正确切换到 awaiting_tool_confirmation |
| 工具调用 | 确认 accept | + "y" 确认 | 工具执行 | 管道 stdin 下 y 被 resume prompt 消费，未走到 write | minor | P2 | 非交互式 stdin 边界 |
| 确认 | 确认提示格式 | write_file 请求 | 含工具名/路径/内容预览 | 格式正确，信息充分 | pass | - | |
| 确认 | 状态切换 | - | state=awaiting confirmation | status=awaiting_tool_confirmation, pending_tool 正确 | pass | - | |
| resume | checkpoint 发现 | 重启 agent | 提示未完成任务 | 正确显示 task 状态、step、消息数、待确认工具 | pass | - | |
| resume | reject resume | "n" | 清除断点 | 正确清除，回到新任务模式 | pass | - | |
| resume | 完整 resume 流程 | "y" + 继续 | 恢复 task/确认 | 未在管道下成功验证 | minor | P2 | |
| memory | FS store 44 tests | pytest | 44 passed | 44 passed | pass | - | |
| memory | Runtime 23 tests | pytest | 23 passed | 23 passed | pass | - | |
| memory | Confirmation 25 tests | pytest | 25 passed | 25 passed | pass | - | |
| memory | Contract 10 tests | pytest | 10 passed | 10 passed | pass | - | |
| memory | **Runtime 接入** | 检查 runtime store 类型 | FilesystemMemoryStore | **InMemoryMemoryStore**（旧） | fail | **P1** | FS store 未接入 runtime |
| memory | FS store 磁盘状态 | `~/.my-first-agent/memory/` | .md 文件 + _meta/index.json | index.json 为空（total=0），无 .md 文件 | pass | - | FS store 初始化正确，无写入记录 |
| memory | 会话结束记忆提取 | "quit" | memory_stored event | "正在提取本次对话的记忆..." 打印但无 memory event 日志 | minor | P2 | |
| logs | system_prompt_len | 日志查看 | >0 | 所有 session 均为 system_prompt_len=0 | minor | P2 | 可能是日志记录时机问题 |
| logs | memory events | `--event memory` | memory 相关 event | 无 memory_stored/memory_evaluated 事件 | minor | P2 | |
| error | 不存在工具 | 直接 import 检查 | False | False | pass | - | |
| error | recall 空结果 | `recall(scope='nope')` | [] | [] | pass | - | |
| error | 无效 intent | pytest 单测 | 被拒 | 测试通过 | pass | - | |
| 工具注册 | 工具清单 | import agent.tools | 8 工具 | 3 工具先于格式化错误展示（edit_file, fetch_url, mark_step_complete） | minor | P2 | print 格式化 callable confirmation 时崩溃，不影响实际注册 |

## 4. Issues Found

### P0（无）

本次未发现 P0 问题。敏感信息未被记住，reject 未绕过，agent 可启动。

### P1（2 个）

**P1-1: config.py 环境变量名不匹配导致冷启动崩溃**

- 文件：`config.py:9`
- 问题：`MODEL_NAME = os.getenv("MODEL_NAME")` 读取 `MODEL_NAME`，但 `.env.example` 和 README 文档中描述的是 `ANTHROPIC_MODEL`
- 影响：用户按照 README 设置 `ANTHROPIC_MODEL` 后运行 `.venv/bin/python main.py` 直接崩溃，错误信息 `ValueError: LoopContext.model_name 必须是非空字符串`
- 临时绕过：`export MODEL_NAME=deepseek-v4-pro`
- 建议修复：`config.py:9` 改为 `os.getenv("ANTHROPIC_MODEL")` 或同时 fallback 两个变量名

**P1-2: FilesystemMemoryStore 未接入 runtime**

- 文件：`agent/core.py:92-96`
- 问题：runtime 仍使用 `InMemoryMemoryStore`（默认参数），Phase 4 实现的 `FilesystemMemoryStore`（44 tests green）未接入
- 影响：所有 memory 操作写入内存，会话结束后丢失；`~/.my-first-agent/memory/` 永远为空
- 建议修复：`create_memory_runtime(store=FilesystemMemoryStore())` 或类似方式接入

### P2（6 个）

**P2-1: 管道 stdin 下确认流程不可靠**
- 非交互式 stdin 时，确认/恢复/resume 提示从管道读取而非终端，消费错误输入
- 这是 stdin 管道模式的已知限制，不是 bug；但 DOGFOODING_GUIDE 应标注不能用管道测试确认

**P2-2: system_prompt_len=0**
- 所有 `session_start` event 的 `system_prompt_length` 为 0
- 可能与 `init_session()` 中 `log_event` 的 SYSTEM_PROMPT 引用有关

**P2-3: 会话结束记忆提取无日志**
- "正在提取本次对话的记忆..." 打印但日志中无对应 `memory_evaluated`/`memory_stored` event

**P2-4: 两个 memory 目录并存**
- `memory/`（项目内，旧格式：checkpoint.json + episodes/ + rules/）
- `~/.my-first-agent/memory/`（FS store 新格式，空）
- 用户可能困惑哪一个是真实记忆源

**P2-5: agent_log.jsonl 391MB**
- 日志持续增长无自动归档，health check 建议手动 mv
- 不影响正确性但拖慢启动 grep/observer

**P2-6: DOGFOODING_GUIDE.md 需更新**
- 第 2 节应注明需 `export MODEL_NAME=...` 或确认 .env 中变量名
- 第 8 节 checkpoint 测试应标注 stdin 管道无法可靠验证

## 5. Raw Evidence Summary

| 证据 | 来源 | 摘要 |
|------|------|------|
| demo 输出 | `main.py demo` | fake provider, 2 trace events, note.md 140 bytes |
| health 报告 | `main.py health` | 3 warn, 5 pass, 391MB log, 148 sessions |
| 启动崩溃 | `main.py` (无 MODEL_NAME) | ValueError in LoopContext.__post_init__ |
| 启动成功 | `MODEL_NAME=... main.py` | session banner 正常，health 摘要正常 |
| 对话测试 | piped "你好..." | agent 返回结构化中文自我介绍 |
| 确认提示 | write_file/run_shell | 正确显示 `[需要确认工具调用]` + 状态切换 |
| resume 提示 | 前次未确认残留 | 正确显示 task 状态/step/messages/pending_tool |
| FS store tests | pytest 4 文件 | 44+23+25+10 = 102 passed |
| FS store 磁盘 | `~/.my-first-agent/memory/` | 空 index.json, 0 条记录 |
| Runtime store | `create_memory_runtime()` | InMemoryMemoryStore 类型 |
| 日志 event | `main.py logs` | session_start(sys_prompt_len=0), health_check, plan_skipped, checkpoint_saved |
| 旧 memory 目录 | `memory/` | checkpoint.json + episodes/ + rules/ + profile.json |

## 6. Recommended Fix Order

### 必须立刻修（block 进一步 dogfooding）

1. **P1-1**: `config.py` MODEL_NAME → ANTHROPIC_MODEL（或双 fallback）— 5 分钟修复
2. **P1-2**: runtime 接入 FilesystemMemoryStore — 确认接入路径后约 15 分钟

### dogfooding 前修

3. **P2-3**: 会话结束记忆提取确认是否产生 memory event
4. **P2-2**: system_prompt_len=0 排查

### dogfooding 中观察

5. **P2-4**: 两个 memory 目录并存 — 确认旧目录是否应清理
6. **P2-5**: agent_log.jsonl 归档 — 不影响功能，择机归档
7. **P2-6**: DOGFOODING_GUIDE.md 更新

### 不需要修（设计如此）

- P2-1: 管道 stdin 下确认不工作是 CLI shell 的预期行为，不是 bug

## 7. Final Recommendation

- **是否建议继续 dogfooding**：先修 P1-1 和 P1-2，再继续。当前状态可跑离线测试但交互式 shell 体验有断点
- **是否建议先修 P0/P1**：无 P0；P1-1 阻塞性，P1-2 阻塞 memory 真实验证
- **是否建议 commit 当前文档/实现**：`docs/DOGFOODING_GUIDE.md` 可 commit（但需标注 P2-6）；Memory FS store 实现正确但未接入 runtime，不建议声称"完成"
- **是否需要暂停进入下一阶段**：是。修复 P1-1/P1-2 后重新验证第 4/6/7/8/9.2 节再进入下一阶段
