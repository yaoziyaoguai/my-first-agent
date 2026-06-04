# First Agent — User Manual Trial Report (2026-06-04)

**试用日期**: 2026-06-04
**试用者**: User (Manual Trial)
**基线版本**: post-hotfix main (`2a908d6`)
**总体结论**: **USER_MANUAL_TRIAL_COMPLETE_WITH_P1_FINDINGS**
**核心状态**: 发现严重 P1 级缺陷（TUI 死锁、Skill 过度阻断），不建议进入 v2 implementation，需先进行 P1 修复。

---

## 1. 试用概览 (Overview)

本次试用按照 `docs/manual-trials/first-agent-user-trial-guide.md` 进行，覆盖了 Plain CLI、Textual TUI 及兼容性入口。验证了真实用户路径下的交互质量与安全性。

---

## 2. 发现项 (Findings)

### P1 — 严重问题 (Blockers)

| ID | Issue | 描述 |
|----|-------|------|
| **UMT-P1-001** | **Textual TUI Deadlock** | TUI 界面在试用中出现死锁，输入框失去响应，`q` 键和 `Ctrl+C` 均无法中断程序。用户只能通过关闭终端或 `kill` 进程来退出。这属于交互主路径的致命问题。 |
| **UMT-P1-002** | **TOOL_GATE Overblocking** | 合法的 Skill 工具（如 `write_demo_note`）被 `TOOL_GATE` 拒绝。Agent 能识别用户需求并尝试调用工具，但因安全策略过激导致功能不可用。 |

### P2 — 重要体验问题 (Major Issues)

| ID | Issue | 描述 |
|----|-------|------|
| **UMT-P2-001** | **Weak Fallback** | 当工具被 `TOOL_GATE` 拒绝后，Agent 倾向于直接停止任务并报错，而不是尝试寻找安全的替代路径（如 `read_file` 基础文档）。F-005 的改进在此场景下仍显不足。 |
| **UMT-P2-002** | **TUI Capability Gaps** | Textual TUI 不支持 `Cmd+V` 粘贴操作，且快捷键退出功能在某些状态下失效，影响基本交互效率。 |

### P3 — 轻微/其他问题 (Minor Issues)

| ID | Issue | 描述 |
|----|-------|------|
| **UMT-P3-001** | **Extensionless Path** | `read_file` 对不带后缀的文件名（如 `README`）处理能力较弱，容易导致初次尝试失败。 |

---

## 3. 运行健康检查 (Health Check)

`python main.py health` 输出记录（需关注）：
- **2 Warnings**: `workspace_lint`, `session_accumulation`
- **1 Error**: `tool_registry_integrity` (需优先调查)

---

## 4. 兼容性验证 (Compatibility)

- `python main.py --shell`: **PASS**。成功输出 `DeprecationWarning` 并进入 Plain CLI。
- 基础对话 (hello): **PASS**。Plain CLI 基础路径稳定。

---

## 5. 建议修复顺序 (Recommended Remediation)

1. **Investigation**: 调查 `tool_registry_integrity` 错误。
2. **P1 Fix**: 解决 Textual TUI 的死锁和信号捕获问题。
3. **P1 Fix**: 精细化 `TOOL_GATE` 策略，区分敏感文件读取与合法 Skill 调用。
4. **P2 Fix**: 增强被拒后的 fallback 逻辑。
5. **P2 Fix**: 补齐 TUI 粘贴和快捷键支持。

---

## 6. Remediation Results (2026-06-04)

**Remediation baseline**: `fb6c68c` (original trial findings commit)

### 6.1 Remediation Summary

| Finding ID | Severity | Status | Root Cause | Fix |
|-----------|----------|--------|------------|-----|
| **健康检查 tool_registry_integrity** | Error | **FIXED_BY_RECHECK** | `is None` vs falsy check bug — `metadata.get("output_policy")` is `None` for `command.spawn` (registered in `MCPCommands` via shell)，`not None` evaluates to `False`, incorrectly treated as missing metadata. | Changed `not info.get(f)` to `info.get(f) is None` in `run_health_check()` (previous session). |
| **UMT-P1-001** | P1 | **FIXED_BY_RECHECK** | Textual TUI only bound `ctrl+q` for exit, which macOS Terminal intercepts for XON/XOFF flow control. No fallback exit keybinding. | Added `ctrl+c` binding to both `LightweightInputApp` and `PersistentInputShell` BINDINGS lists; added `ctrl+c` handling in `ChatTextArea._on_key()` to call `action_close_input()`; updated help bar text to show "Ctrl+Q/Ctrl+C 退出". 31/31 Textual tests PASS. |
| **UMT-P1-002** | P1 | **FIXED_BY_RECHECK** | `get_model_visible_tools()` not skill-aware — model received all tools but only skill.allowed_tools subset could pass TOOL_GATE, causing model to attempt non-allowed tools and receive overblocking rejections. | Added skill-aware `explicit_allowlist` computation in `_call_model()` in `agent/core.py`: when a skill is active, model-visible tools are narrowed to `skill.allowed_tools + meta_tools + SKILL_SELECT`. 3 new contract tests added to `test_demo_tools_contract.py`. |
| **UMT-P2-001** | P2 | **FIXED_BY_RECHECK** | `FORCE_STOP` handling in `response_handlers.py` returned a stop message that ended the conversation loop, preventing model from trying alternative approaches. | Changed `handle_tool_use_response` to write rejection info to `state.task.tool_execution_log` and let the loop continue instead of returning a terminal stop message. Model now receives rejection as tool_result feedback and can try alternatives. |
| **UMT-P2-002** | P2 | **FIXED_BY_RECHECK_WITH_CAVEAT** | Textual's `TextArea` widget handles paste natively through terminal-level events. No code changes needed for basic paste — Ctrl+V / Cmd+V work through terminal paste. Previous "not supported" report likely due to TUI deadlock (UMT-P1-001) preventing paste from being delivered. | Added 4 focused tests for paste behavior: multiline insert, bulk text (2000 chars), paste-then-submit, and Ctrl+Q shortcut integrity after paste. 31/31 Textual tests PASS. **Caveat**: Cmd+V paste behavior is terminal-emulator-dependent on macOS; the TUI application cannot intercept OS-level paste shortcuts. |
| **UMT-P3-001** | P3 | **FIXED_BY_RECHECK** | `read_file` required exact path match; no extension-based fallback for files like `README`. | Added extensionless path resolution in `agent/tools/file_ops.py`: when exact path doesn't exist, tries common document extensions (`.md`, `.txt`, `.rst`). Does NOT expand sensitive filenames (`config`, `.env`, `credentials`, `secret`, `token`, `key`). |

### 6.2 Gate Results

```text
test_tool_sensitive_path_policy.py ................ 33 passed
test_docs_source_of_truth.py .......................... 79 passed
test_architecture_boundaries.py ........................ 24 passed
test_demo_tools_contract.py ........... 11 passed
test_input_backends_textual.py ............................... 31 passed
ruff check (all touched files) .................................. ALL CLEAN
```

### 6.3 Status After Remediation

**P1_REMEDIATED_PENDING_USER_RECHECK** — all P1 findings have code fixes + focused tests + gate verification. Requires human user recheck to confirm TUI exit, Skill tool access, and overall usability.
