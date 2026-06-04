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
