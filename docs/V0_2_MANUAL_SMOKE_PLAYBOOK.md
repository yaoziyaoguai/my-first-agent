# Runtime v0.2 RC · 人工 smoke playbook

> **本文件目的**：把 Runtime v0.2 release candidate 的人工测试拆成
> 可复现、可勾选、可审计的步骤。本文件是「人工跑」清单，**不**是自动化
> 测试，**不**新增功能，**不**推进 M5/M6 实现，**不**做 push。
>
> **范围边界**：
> - ✅ smoke 当前 v0.2 RC 已完成的：M1 状态机 / M2 事件边界 /
>   M3 checkpoint 恢复 / M4 错误恢复。
> - ✅ 观察 M5 工具 / M6 安全的「现状行为」，不修复。
> - ✅ 检查 CLI 输出契约不退化。
> - ✅ 顺手确认 LLM Processing 已收口能力没坏（不是主线）。
> - ❌ 不测 TUI / Textual / Skill / sub-agent / topic switch /
>   slash command / generation cancel —— 这些都不在 v0.2 RC 范围。
>
> **执行人**：用户。
> **执行时机**：本 playbook commit 之后；M5/M6 任何代码改动之前。
> **执行结果**：建议把每条勾选 + 实际现象写入
> `docs/V0_2_RC_SMOKE_REPORT.md`（本轮不创建，等真实跑完后写）。

---

## 0. 前置条件

```bash
cd /Users/jinkun.wang/work_space/my-first-agent
test -f README.md
test -x .venv/bin/python
.venv/bin/python -m pytest -q   # 应该 387 passed, 3 xfailed
```

可选（仅 §6 用）：

```bash
test -f .env                    # 含 ANTHROPIC_API_KEY，仅 LLM Processing live smoke
```

> 如果不准备做 §6 LLM Processing 的 `--live`，**不要** export 真实 key。
> 整个 §1-§5 不需要真实 API。

---

## 1. M1 状态机基本任务流 smoke

**目标**：确认 `plan → 用户确认 → 工具 → end_turn` 最小回路在 simple CLI
下走通，CLI 输出可读。

```bash
.venv/bin/python main.py
```

输入：

```text
请读取仓库根目录 README.md 的前 20 行，并把一段 100 字以内的中文总结写入 workspace/v0_2_smoke_summary.md。
```

预期：

- [ ] 看到 plan 输出，能区分「assistant 正在说话」「tool 正在调用」
      「等用户 y/n」三类信号。
- [ ] 工具调用 confirmation 正常（read_file 项目内不要求 confirm；
      write_file 一定要求 confirm）。
- [ ] 任务结束后 `workspace/v0_2_smoke_summary.md` 真的存在，内容是中文总结。
- [ ] `memory/checkpoint.json` 存在；用 `cat memory/checkpoint.json | head -30`
      看到 task.status / messages 等关键字段，且**没有**裸 dict / protocol
      dump 出现在 stdout。
- [ ] 完成后退出，重新 `python main.py` 不会自动复用上一个任务（v0.1
      契约：task 完成态不会被 silent resume；如有 resume 应有显式提示）。

**清理**：

```bash
rm -f workspace/v0_2_smoke_summary.md memory/checkpoint.json
```

---

## 2. M2 InputIntent / RuntimeEvent / CommandResult / messages / checkpoint 边界观察

**目标**：用一次任务观察「临时事件 vs 持久状态」是否真的分开。

执行 §1 同一条任务，过程中观察以下边界（参考
`docs/RUNTIME_EVENT_BOUNDARIES.md`）：

- [ ] `messages` 只承载 user / assistant / tool_use / tool_result 协议消息；
      **没有** RuntimeEvent / DisplayEvent / CommandResult 字符串混入。
- [ ] CLI 上看到的 plan 渲染、tool 渲染、确认提示——都来自 RuntimeEvent
      投影，不是直接 print state。
- [ ] `memory/checkpoint.json` 中：
  - `task.messages` 存在；
  - **没有** `tool_traces` 字段（临时态不持久化）；
  - 没有 RuntimeEvent / DisplayEvent 列表。

> 自动化已守护：见 `tests/test_runtime_event_boundaries.py`（11 条不变量）。
> 人工只确认「真实跑起来时也满足」。

---

## 3. M3 checkpoint save/load/resume smoke

**目标**：确认 Ctrl+C 中断后能恢复，且损坏 checkpoint 不会让进程崩。

### 3.1 awaiting_plan 中断恢复

```bash
.venv/bin/python main.py
```

输入：

```text
请帮我把 README.md 翻译成英文写入 workspace/readme_en.md，分 3 步规划。
```

- 看到 plan 输出、出现「请确认计划 y/n」时 → **Ctrl+C** 退出。

```bash
.venv/bin/python main.py
```

预期：

- [ ] 启动后看到「检测到未完成任务 / 复现等待计划确认」之类提示。
- [ ] 原 plan 内容能被复读出来，回答 y 后任务能继续。

### 3.2 awaiting_tool_confirmation 中断恢复

重复 3.1，但在「请确认是否写入 workspace/readme_en.md」时 Ctrl+C。

- [ ] 重启后看到 pending tool 重放 + confirm 提示，回答 y 后任务继续。

### 3.3 损坏 checkpoint 不崩

```bash
.venv/bin/python -c "import json,pathlib; p=pathlib.Path('memory/checkpoint.json'); d=json.loads(p.read_text()); d['__unknown_top_level__']='x'; d.setdefault('task',{})['__unknown_field__']='y'; p.write_text(json.dumps(d))"
.venv/bin/python main.py
```

预期：

- [ ] 进程不 crash。
- [ ] 不会把未知字段挂到 TaskState/MemoryState（已由
      `agent/checkpoint.py::_filter_to_declared_fields` 兜底）。

**清理**：

```bash
rm -f workspace/readme_en.md memory/checkpoint.json
```

---

## 4. M4 错误恢复 / loop guard / no-progress 场景

**目标**：确认阈值兜底真的兜底，文案可读。

> 这一节需要让模型**故意**做出长输出 / 反复非工具求助。如果当下不方便手工
> 引导模型，可以跳过 4.1 / 4.2，但 4.3 必须做。

### 4.1 连续 max_tokens（可选）

让模型连续生成长文本（例如「请把 README 完整翻译成英文 + 法文 + 西班牙文 +
日文，不要省略」），观察：

- [ ] 第 3 次连续 max_tokens 时看到「连续多次达到最大输出长度」类停止文案。
- [ ] task 没有死循环。

### 4.2 no_progress（可选）

让模型反复用普通文本说「我需要更多信息」而不调 `request_user_input`：

- [ ] 第 2 次后被引导到 awaiting_user_input 兜底。

### 4.3 工具失败不污染 last_error（必做）

```bash
.venv/bin/python main.py
```

输入：

```text
请读取 /tmp/definitely_does_not_exist_v0_2_smoke.txt 并总结内容。
```

预期：

- [ ] 工具失败提示在 messages / CLI 中可读。
- [ ] 任务能继续（模型可以选择换路径或问用户）。
- [ ] `memory/checkpoint.json` 中 `task.last_error` 仍为 `null`（工具失败
      不污染顶层错误）。

**清理**：

```bash
rm -f memory/checkpoint.json
```

---

## 5. M5 工具现状 smoke + M6 安全现状 smoke + CLI 输出契约

**目标**：观察 M5/M6 实现前的当前真实行为，确认与
`docs/V0_2_TOOLING_AND_SECURITY_PREFLIGHT.md` §1-§3 一致。

### 5.1 M5 工具基本可用

```bash
.venv/bin/python main.py
```

逐条让 agent 执行（每条结束后退出，重置 checkpoint 再来）：

- [ ] `read_file` 读取 `README.md` 成功。
- [ ] `read_file_lines` 读取 `README.md` 第 1-10 行成功。
- [ ] `write_file` 写 `workspace/v0_2_tool_smoke.txt`，**要求 confirm**。
- [ ] `calculate` 算 `(13*17)+1` 返回 222，无 confirm。
- [ ] 让模型读不存在的文件 → 看到可读错误，task 不崩。

### 5.2 M6 安全现状（**预期都被拦截或要求 confirm**）

- [ ] `read_file ~/.env` → 被 block；返回结果以 `[安全策略]` 开头，
      包含「敏感配置/密钥文件」字样；停止消息为「工具调用被安全策略
      阻断，本任务已停止。具体拒绝原因见上方工具消息。」
      **绝不应**出现「用户连续拒绝多次操作」之类把策略拒绝
      误归类为用户拒绝的措辞（v0.2 RC smoke 真实修复点）。
- [ ] `read_file /tmp/server.pem`（必要时 `touch /tmp/server.pem`）
      → 同上，`[安全策略]` + 敏感原因 + 「工具调用被安全策略阻断」结束。
- [ ] `write_file agent/core.py` → 被拒（受保护源码）。
- [ ] `run_shell "rm -rf /"` → 被 `SHELL_BLACKLIST` 拦截。
- [ ] `run_shell "r''m -rf /tmp/x"` → 被拦截（v0.2 RC P1-A 命令规范化）。
- [ ] `run_shell "RM -RF /"` → 被拦截（v0.2 RC P1-A 大小写规范化）。
- [ ] `run_shell ":(){ :|:& };:"` → 被拦截（v0.2 RC P0 修复 fork bomb 正则）。
- [ ] `run_shell "echo data > /dev/sda1"` → 被拦截（v0.2 RC P0 修复 `>/dev/sd` 边界）。
- [ ] `run_shell "ls"` → 静默执行（READONLY_COMMANDS）。
- [ ] `write_file workspace/private.txt` 内容含 `-----BEGIN PRIVATE KEY-----`
      → 被拒（v0.2 RC P1-B 内容前缀扫描），即使路径是 `.txt`。
- [ ] `write_file workspace/safe.md` 内容是普通中文笔记 → 正常通过 confirm 后写入。
- [ ] `write_file ~/v0_2_outside_test.txt`（项目外）→ **被硬拒绝**
      （v0.2 RC smoke 发现的真实缺口已修复；不再询问 confirm）。
- [ ] `write_file /tmp/foo.txt`（项目外绝对路径）→ 同上，硬拒绝。

> ⚠️ **剩余已知缺口**（见
> `docs/V0_2_TOOLING_AND_SECURITY_PREFLIGHT.md` §3）：
> - `read_file ./notes.txt`（内容是 `.env` 改名）当前**不会**被 block
>   （`is_sensitive_file` 仍只看文件名/扩展名，read 路径未做内容前缀扫描）；
> - `run_shell "$(echo rm) -rf /"` / `run_shell "eval ..."` 等高级 shell
>   绕过当前**不会**被拦截（需要 v0.3 命令解析层）。
>
> 这些**预期失败**。看到「未拦截」属于已知现状，请记录而**不要**临时
> 修补；后续 P2 / v0.3 补丁会统一处理。

### 5.3 CLI 输出契约不退化

整段 §1-§5 过程中，**禁止**看到：

- [ ] **没有**裸 `Task(...)` / `MemoryState(...)` / dict 整段 dump 到 stdout。
- [ ] **没有** protocol REQUEST / RESPONSE 整 JSON 直接 dump 到 stdout（仅
      `agent/protocol_logger.py` 写 `agent_log.jsonl`）。
- [ ] **没有**未走 RuntimeEvent 的随手 print。
- [ ] confirm 提示永远在最后一行，y/n 不会被滚走。

> 自动化已守护一部分：`tests/test_real_cli_regressions.py`。

### 5.4 运行产物不入 git

```bash
git status --short
```

- [ ] **不应**看到 `memory/checkpoint.json` / `summary.md` /
      `workspace/v0_2_*` / `agent_log.jsonl` 进入 staged / untracked。
      （除工作区中允许出现的临时文件外，`.gitignore` 应该都覆盖到。）

---

## 6. LLM Processing 已收口能力 · 不退化检查（非主线）

**目的**：仅确认 v0.2 主线工作没有意外破坏 v0.2 LLM Processing 子线。

```bash
.venv/bin/python -m llm.cli scan
.venv/bin/python -m llm.cli process blog/  --provider fake     # 或具体已存在的小文件
.venv/bin/python -m llm.cli status
```

预期：

- [ ] `scan` 列出文件、不 crash。
- [ ] `process` 走 fake provider 端到端通过。
- [ ] `status` 输出 schema 完整、**无**裸 api key / raw prompt /
      raw completion / response body。

可选 live smoke（仅当 `.env` 已配 `ANTHROPIC_API_KEY` 且你愿意花 token）：

- [ ] 按 `docs/LLM_PROVIDER_LIVE_SMOKE.md` 跑一次 preflight `--live`，看到
      token 数 + 延迟。**不要**把 live smoke 产物 commit。

---

## 7. 完成判定

人工 smoke 全部勾选（除 §4.1 / §4.2 / §6 live smoke 可选项外）→
Runtime v0.2 RC 验证通过，可以进入「M5/M6 最小补丁」决策。

如果 §1-§5 任何一项失败：

1. 不要立刻改代码。
2. 把现象写下来（命令、输入、看到了什么、期望是什么）。
3. 找回我（或新会话），按现象决定是回归 bug 还是 spec 误解。

---

## 8. 参考文档索引

- `docs/RUNTIME_STATE_MACHINE.md` — M1
- `docs/RUNTIME_EVENT_BOUNDARIES.md` — M2
- `docs/CHECKPOINT_RESUME_SEMANTICS.md` — M3
- `docs/RUNTIME_ERROR_RECOVERY.md` — M4
- `docs/V0_2_TOOLING_AND_SECURITY_PREFLIGHT.md` — M5/M6 现状 + 缺口
- `docs/CLI_OUTPUT_CONTRACT.md` — CLI 输出契约
- `docs/V0_2_RC_STATUS.md` — v0.2 RC 完成范围 / 限制 / 不 push 原因
- `docs/LLM_PROVIDER_LIVE_SMOKE.md` — LLM live smoke 安全规程
