# Local Manual Dogfood Report

Date: 2026-05-25
Commit tested: 2c80113 (docs: sync checklist and issue sweep with Phase 1-3 stabilization results)
Executor: `scripts/dogfood_checklist_executor.py` (automated, via `core.chat()` + FakeProvider)

## Result Matrix

| Step | Name | Status | Note |
|------|------|--------|------|
| 1 | Onboarding / Help | PASS | `main.py --help` 显示能力说明、FakeProvider、SubAgent、Memory、Tool 状态 |
| 2 | 普通对话 | PASS | assistant.delta 回显用户消息，run.summary 正确 |
| 3 | 触发 Demo Tool | PASS | 完整 Tool Pipeline: TOOL_REQUEST→CONFIRM→TOOL_RESULT，文件创建在时间戳目录下 |
| 4 | 查看记忆列表 | PASS | 显示"暂无已保存的记忆"（空列表格式正确） |
| 5 | 查看子代理列表 | PASS | 展示 2 个子代理: code-reviewer + demo-stat |
| 6 | CLI 委托子代理 | PASS | delegating/delegated/run_summary 事件完整，返回 demo-stat 统计结果 |
| 7 | 自然语言委托子代理 | PASS | NL 关键词匹配正确路由到 demo-stat，delegating/delegated/run_summary 事件完整 |
| 8 | 忘记记忆 | PASS | 列表格式正确，无效 ID 返回 not found，关键词匹配返回 not found |
| 9 | 退出 | PASS | `quit`/`exit` 正常退出 |

**PASS: 9 / 9, CONCERN: 0, FAIL: 0**

## Execution Details

### Step 1: Onboarding / Help
- Command: `python main.py --help`
- Exit code: 0
- Output contains: FakeProvider, SubAgent, Memory, Tool 状态说明

### Step 2: 普通对话
- Input: `你好，今天怎么样？`
- Events: control.message → assistant.delta → run.summary
- Echo confirmed: "已收到你的消息：「你好，今天怎么样？」"

### Step 3: 触发 Demo Tool
- Input: `make a demo note` → `y` (confirm)
- Pipeline stages: TOOL_REQUEST → TOOL_CONFIRMATION_REQUESTED → TOOL_RESULT
- File created: `workspace/demo/20260524T175708Z/note.md`
- Note: `demo_write_demo_note` uses `_default_demo_note_path()` which creates timestamped subdirectories

### Step 4: 查看记忆列表
- Input: `show memories`
- Output: "暂无已保存的记忆。" (empty store, correct format)

### Step 5: 查看子代理列表
- Input: `show subagents`
- Output: 2 subagents listed (code-reviewer [reviewer], demo-stat [analyzer])

### Step 6: CLI 委托子代理
- Input: `delegate to demo-stat: count files in workspace`
- Events: subagent.delegating → subagent.delegated → run.summary
- Result: deterministic L0 summary returned

### Step 7: 自然语言委托子代理
- Input: `帮我统计 demo workspace`
- Events: subagent.delegating → subagent.delegated → run.summary
- Result: same as CLI delegation path

### Step 8: 忘记记忆
- Sub-steps:
  - `show memories`: 空列表，格式正确
  - `forget id:nonexistent`: "未找到 ID 为「nonexistent」的记忆。"
  - `忘记 test`: "未找到匹配「test」的记忆。"

## Fixes Applied

1. **code-reviewer SUBAGENT.md**: Added `status: active` field (was missing, causing registry load failure)
2. **dogfood script Step 3**: Fixed path detection — `demo_write_demo_note` creates files in timestamped subdirectories (`workspace/demo/YYYYMMDDTHHMMSSZ/note.md`), not flat `workspace/demo/note.md`. Script now scans for new files via `rglob`.

## Remaining Issues

None. All 9 checklist steps pass.

## Readiness Assessment

- **Local manual dogfood**: READY — all steps pass on fake/local/no-secret path
- **Safe to start Next Big Loop**: YES — no blocking issues remain
- **Fake/real shared path**: Confirmed — all steps go through `core.chat()` unified runtime

## Next Big Loop Selection Rationale

With dogfood fully passing, the highest-value Next Big Loop candidates from Section H are:

1. **Real Provider Dogfood Readiness** — `.env` is configured; can do controlled real-LLM verification of the same checklist steps
2. **MEMORY_RECALL implementation revisit** — AD complete, could add real recall value
3. **More natural tool/subagent planning** — current deterministic matching works but could be richer

Selection will be made based on safety preflight for real provider path.
