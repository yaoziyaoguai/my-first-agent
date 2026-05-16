# Global Dogfooding Guide

项目 owner 从零启动并系统自测 agent 核心能力。不依赖真实 LLM、外部服务、或记忆。

---

## 1. What this guide tests

**覆盖**：启动 agent（fake demo + shell）、对话/多轮上下文、工具调用、`request_user_input`、confirmation flow、checkpoint/resume、memory（retain/reject/edit/session_only/filesystem store/recall）、runtime events/trace/logs、error handling。

**不覆盖**：真实 provider/LLM、真实 MCP、vector DB、embedding、semantic retrieval、L2/L3 proactive memory、consolidation/decay/archival/proceduralization。

---

## 2. Preconditions

```bash
pwd           # 必须是 my-first-agent 根目录
python --version  # 3.10+，开发用 3.12
```

```bash
# 首次或重建 venv
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
```

**安全边界**：不读 `.env`（除非你主动配了 key）；不读真实 `agent_log.jsonl`/`sessions/`/`runs/` 内容；demo 只写 `workspace/demo/` 或 tmp。

---

## 3. Start the agent

| 入口 | 命令 | 说明 |
|------|------|------|
| **推荐：fake demo** | `.venv/bin/python main.py demo "用中文写一句今日笔记"` | 不联网、不读 key、5 秒 |
| 交互式 shell | `.venv/bin/python main.py` | 需 provider/API key |
| health | `.venv/bin/python main.py health` | 只读维护报告 |
| logs | `.venv/bin/python main.py logs` | tail 50 条 event |

不推荐：`python main.py process/scan/status/preflight`（LLM Processing CLI 遗留）。

---

## 4. Basic conversation smoke test

**需交互式 shell + provider**。没配 key 跳至第 5 节。

```bash
.venv/bin/python main.py
```

```
你好，请用中文介绍一下你自己能做什么
```
**预期**：结构化中文自我介绍（写文件、搜索、读代码等）。

多轮测试：
```
刚才你提到的能力里，你觉得哪一项最成熟？
```
**预期**：引用第一轮内容作答。

**失败看**：`agent/core.py`、`agent/context_builder.py`

---

## 5. Tool calling test

**不需要 provider**，fake demo 闭环验证。

```bash
.venv/bin/python main.py demo "create a demo note about today's local run"
```

**预期**：输出 `demo.write_demo_note -> ok`，显示 `workspace/demo/<ts>/note.md` 路径和字节数，Trace summary 含 2 个 span。

验证写入：
```bash
cat workspace/demo/*/note.md
```

**失败看**：`agent/local_demo.py`、`agent/tool_result_contract.py`

---

## 6. Ask User / request_user_input test

`request_user_input` 是元工具（`agent/tools/meta.py:102-145`），调用时 runtime 暂停等用户回复。

**交互式验证**（需 provider）：
```
帮我写一个脚本，但我不确定要 bash 还是 python，你帮我决定一下
```
**预期**：agent 调用 `request_user_input`，options 含 `["bash", "python"]`，终端暂停等输入，用户选择后继续。

**失败看**：
- 没触发：`agent/response_handlers.py` 的 `request_user_input_called` 逻辑
- 触发但没暂停：`agent/tool_executor.py` meta_tool 分支
- 用户输入没注入：`agent/confirm_handlers.py` 的 `_handle_execution_help`

**离线验证**（无需 provider）：
```bash
.venv/bin/python -m pytest tests/test_memory_interactive_confirmation.py -v -x
```

---

## 7. Confirmation flow test

`write` 工具 `confirmation="always"`，执行前必须用户确认。

**交互式验证**（需 provider）：
```
在 workspace/test/confirmation_test.md 里写一行 "hello confirmation test"
```

**预期**：plan 展示 → 用户 accept 写入；用户 reject → 不执行，显示 `user_rejected`。三种决策：`accept`/`reject`/`edit`。拒绝后 `workspace/test/confirmation_test.md` 不应存在。

**失败看**：`agent/confirm_handlers.py`、`agent/tool_executor.py:needs_tool_confirmation`

---

## 8. Checkpoint / resume test

自动保存时机：Ctrl+C 中断且有可恢复 state；`request_user_input` 调用后。

**交互式验证**（需 provider）：
```bash
.venv/bin/python main.py
# 输入有进度任务：帮我列出当前目录所有 .py 文件，统计行数
# 执行中途按 Ctrl+C
```

**预期**：checkpoint 保存提示；下次启动 banner 显示可恢复 checkpoint；resume 后恢复到中断 task state。若显示 "未发现断点"，无可用 checkpoint。

**失败看**：`agent/checkpoint.py`、`agent/session.py:try_resume_from_checkpoint`

未配 key 时标记 **not covered**。

---

## 9. Memory test

覆盖 retain/reject/edit/session_only/sensitive filtering/filesystem store/recall。**不测 semantic/vector search**。

### 9.1 自动化测试（无需 provider）

```bash
.venv/bin/python -m pytest tests/test_memory_fs_store.py -v                         # FS store 44 tests
.venv/bin/python -m pytest tests/test_memory_runtime_integration.py \
  tests/test_memory_interactive_confirmation.py -v                                   # Runtime + 确认 42 tests
.venv/bin/python -m pytest tests/test_memory_store_contract.py -v                    # Contract 10 tests
# 全部（~96 tests）
.venv/bin/python -m pytest tests/test_memory_fs_store.py tests/test_memory_runtime_integration.py \
  tests/test_memory_interactive_confirmation.py tests/test_memory_store_contract.py -v
```

### 9.2 手动验证 store

```bash
.venv/bin/python -c "
from agent.memory_fs_store import FilesystemMemoryStore
store = FilesystemMemoryStore()
records = store.list_records()
print(f'Total: {len(records)}')
for r in records[:5]:
    print(f'  [{r.memory_type}] {r.source_summary[:60]}...')
"
```

### 9.3 关键用例速查

| 场景 | 测试类/文件 | 用例 |
|------|-----------|------|
| retain/forget/update/session_only | `TestStoreOperations` | `test_retain_creates_file` 等 4 个 |
| recall by scope/type/max_items | `TestRecall` | 6 个 |
| topic routing | `TestTopicRouting` | 5 个 |
| sensitive blocked | `test_memory_runtime_integration.py` | `test_sensitive_memory_blocked` |
| reject 不写 store | `test_memory_interactive_confirmation.py` | `test_rejected_memory_not_stored` |

**失败看**：`agent/memory_fs_store.py`、`agent/memory_runtime.py`、`agent/memory_policy.py`

---

## 10. Optional complex real LLM memory dogfood

`scripts/dogfood_complex_real_llm.py` 是 complex real LLM memory dogfood harness，也是 Memory RFC completion 状态下保留的可复用 dogfood harness。它不属于普通测试默认路径，只在明确 opt-in、且项目配置机制已经能自动加载 provider config 时手动运行。

它只使用 synthetic / non-sensitive scenarios，覆盖：

- stable preference consolidation
- contradiction / low-confidence behavior
- procedural-like boundary
- Chinese complex expression
- secret-like synthetic content

治理验证包括：

- T1 pending
- no direct store write
- no auto approve
- no silent procedural retain
- no secret exposed

安全运行方式：

```bash
MEMORY_CONSOLIDATION_LLM_ENABLED=true python scripts/dogfood_complex_real_llm.py
```

约束：

- 真实 LLM provider 必须通过 project `.env` scoped config load 自动加载。
- 不要 `cat` / `grep` `.env`。
- 不要把 API key 放在命令行里。
- 不要打印 API key、prefix、suffix、length、Authorization 或 Bearer header。
- 不要在普通测试中自动调用真实 LLM；CI/pytest 默认应继续走 fake/local/opt-in skip。

---

## 11. Runtime events / trace / logs test

```bash
.venv/bin/python main.py logs                         # tail 50
.venv/bin/python main.py logs --tail 100              # 更多
.venv/bin/python main.py logs --event tool_executed   # 按事件类型
.venv/bin/python main.py logs --tool demo.write_demo_note  # 按工具名
.venv/bin/python main.py logs --include-observer      # 含 observer（极噪）
```

**预期**：结构化列表，含时间戳、event 类型、session id。不要 `cat agent_log.jsonl`。
**失败看**：`agent/log_viewer.py`、`agent/logger.py`、`agent/runtime_observer.py`

---

## 12. Error handling test

```bash
# 不存在工具
.venv/bin/python -c "from agent.tool_registry import TOOL_REGISTRY; print('nonexistent' in TOOL_REGISTRY)"  # False

# recall 空结果
.venv/bin/python -c "from agent.memory_fs_store import FilesystemMemoryStore; print(FilesystemMemoryStore().recall(scope='nope'))"  # []

# 无效 intent 被拒
.venv/bin/python -m pytest tests/test_memory_fs_store.py::TestStoreOperations::test_reject_mutating_without_approval -v
```

---

## 13. Dogfooding log template

| Date | Area | Scenario | Prompt | Expected | Actual | Severity | Notes |
|------|------|----------|--------|----------|--------|----------|-------|
| 2026-05-11 | demo | fake demo | `main.py demo "..."` | note.md | | | |
| | tool | write confirm | write | 确认弹窗 | | | |
| | memory | retain+recall | retain | recall 可见 | | | |
| | checkpoint | resume | Ctrl+C 重启 | 恢复 state | | | |

Severity: `ok` / `minor` / `blocker`

---

## 14. Stop conditions

出现任一立即停止：敏感信息被记住；reject 后工具仍执行；`request_user_input` 没真实等待用户；checkpoint/resume 恢复错误 state；tool result 写错（路径逃逸）；memory 错写（错误 topic file）；测试失败无法定位。

---

## 15. What not to test yet

默认不测真实 LLM/provider；如需 memory consolidation real provider dogfood，只按第 10 节 opt-in harness 执行。仍不测外部 MCP server、vector DB/embeddings/semantic retrieval、L2/L3 proactive memory、decay/archival/proceduralization、Skill 系统（experimental）、Textual TUI（实验性）。

---

## 推荐测试顺序

1. **fake demo**（第 5 节，5 秒，无需 provider）
2. **全部 memory 测试**（第 9.1 节，~96 tests，无需 provider）
3. **health + logs**（第 3、11 节，无需 provider）
4. **error handling**（第 12 节，无需 provider）
5. **如果配了 provider**：交互式 shell 测试对话/确认/checkpoint/request_user_input（第 4、6、7、8 节）
6. **如果明确 opt-in real LLM memory dogfood**：按第 10 节运行 complex harness
