# v0.2 Tooling & Security Preflight (M5 / M6)

> **本文目的**：v0.2 主线已完成 M1（状态机）/ M2（事件边界）/ M3（恢复语义）/
> M4（错误恢复）。继续做 M5「工具体系优化」和 M6「基础安全权限」前，先做
> 一次只读审计：
> - 摸清当前工具与安全机制的事实状态。
> - 切分 M5 / M6「最小必须项」与「可推迟到 v0.3」。
> - 列出人工测试前必须验证的工具/权限 smoke 清单。
> - 标记 1-2 个极小且明显的安全边界缺口，便于在不大改架构的前提下做最小补丁。
>
> **核心边界**：M5 / M6 真正实现前，**不**在本轮做大规模工具系统重构、
> 不引入沙箱、不做 OS 级权限隔离、不重写 confirmation 流程。

---

## 1. 当前工具清单（事实记录）

| 工具 | 模块 | confirmation | 关键 pre/post 检查 |
|---|---|---|---|
| `calculate` | tools/calc.py | `never` | 无副作用 |
| `outline` | tools/outline.py | `never` | 无副作用 |
| `read_file` | tools/file_ops.py | `_check_read_permission` | sensitive 文件 → block；项目外 → confirm |
| `read_file_lines` | tools/file_ops.py | `_check_read_permission` | 同上 |
| `write_file` | tools/write.py | `always` | `pre_write_check`：保护源码、同轮单写；`post_write_check`：linter |
| `edit_file` | tools/edit.py | `always` | linter 集成 |
| `run_shell` | tools/shell.py | `always`（READONLY_COMMANDS 例外） | `SHELL_BLACKLIST` 正则黑名单、`SHELL_TIMEOUT=30` |
| `web_search` | tools/web.py | `always` | 无 |
| `load_skill` | tools/skill.py | `never` | 仅读取仓库内 skill |
| `install_skill` | tools/install_skill.py | `always` | `safety_warnings` 仅打印，确认后执行 |
| `update_skill` | tools/update_skill.py | `always` | 同上 |
| **元工具** `request_user_input` | tools/meta.py | `never` | 协议元工具 |
| **元工具** `mark_step_complete` | tools/meta.py | `never` | 协议元工具 |

## 2. 当前安全机制（事实记录）

### 2.1 `agent/security.py`
- `SENSITIVE_PATTERNS = {".env", ".env.local", ".env.production", "id_rsa", ".pem", ".key"}`
- `SENSITIVE_KEYWORDS = {"secret", "credential", "password", "token", "apikey"}`
- `is_sensitive_file(path)`：文件名匹配 → block 读取
- `is_protected_source_file(path)`：PROJECT_DIR 内 + `PROTECTED_EXTENSIONS`（.py 等）+ 已存在 → 拒绝写
- `needs_confirmation(tool, input)`：仅做兜底分派，主路径已迁移到 tool-level `confirmation=` 字段

### 2.2 `agent/tools/shell.py`
- `SHELL_BLACKLIST`：正则黑名单，覆盖 `rm -rf / sudo / mkfs / shutdown / reboot / dd / fork bomb / >/dev/sd / chmod 777 / chown / passwd / kill -9`
- `READONLY_COMMANDS`：`ls / cat / find / grep / wc / head / tail / pwd / which / echo / tree / file / ruff / python -c` 不要求 confirm
- `SHELL_TIMEOUT = 30s`
- 通过 `_check_shell_confirmation` 让 READONLY_COMMANDS 走 silent 路径

### 2.3 `agent/tools/write.py`
- `pre_write_check`：受保护源码拒写、同轮多写拒绝
- `post_write_check`：触发 linter，linter 报错时强制要求模型修复

### 2.4 工具失败兜底（M4 收口）
- 同名同入参失败过的工具不会再次执行（response_handlers `failed_same_input_count`）
- 同名同入参成功调用超过 `MAX_REPEATED_TOOL_INPUTS=3` 次会触发 placeholder + reset
- 所有 placeholder 内容是固定短文案，不泄漏入参

## 3. 已识别的小型安全边界缺口（候选）

下表是「不大改架构就能补丁」的最小缺口；本文档**只登记**，是否做最小修复
留给 M6 决定。

| 缺口 | 现状 | 风险 | 最小修复（候选） |
|---|---|---|---|
| `is_sensitive_file` 只看文件名 | 改名后仍可读 | 用户复制 `.env` → `notes.txt` 可绕过 block | 加内容前 N 字节扫描敏感前缀（`API_KEY=` / `BEGIN PRIVATE KEY` 等） |
| ~~`is_sensitive_file` 不识别 `.pem` / `.key` 扩展名~~ | ✅ **v0.2 RC P0 已修复** | — | — |
| ~~`SHELL_BLACKLIST` 用正则可被简单引号转义绕过~~ | ✅ **v0.2 RC P1-A 已修复**（`_normalize_shell_command` 在原匹配未命中时再跑一次规范化版本，覆盖空引号 / 反斜杠 / 空白 / 大小写绕过） | — | — |
| ~~`SHELL_BLACKLIST` fork bomb 正则失效~~ | ✅ **v0.2 RC P0 已修复** | — | — |
| ~~`SHELL_BLACKLIST` `>/dev/sd` 重定向失效~~ | ✅ **v0.2 RC P0 已修复** | — | — |
| ~~`write_file` 没有内容级危险扫描~~ | ✅ **v0.2 RC P1-B 已修复**（`pre_write_check` 加 `_check_dangerous_content`：私钥头 / fork bomb / `> /dev/sd` / `mkfs` payload 全部拒写，即使路径是 `.txt` / `.md`） | — | — |
| `write_file` 没有项目外写拦截 | 仅检查「项目内 + 受保护扩展名」 | 可写入 `~/.bashrc` 等 | `confirmation=always` 已要求确认；M6 可加「项目外路径 → 显式额外提示」 |
| `read_file` 项目外仅 confirm | 即使确认后可读任意路径 | 用户疏忽确认即泄漏 | 同上：项目外路径在 confirm prompt 上加「⚠️ 项目外」标签 |
| `install_skill` 下载内容确认即执行 | `safety_warnings` 仅打印 | 远程内容含恶意脚本 | M6 可强制要求第二次确认；当前在范围外 |

**v0.2 RC P0 + P1 已落地**：上表第 2 / 3 / 4 / 5 / 6 项（`.pem`/`.key`
扩展名识别、shell 命令规范化、fork bomb 字面匹配、`>/dev/sd` 边界修正、
write_file 内容前缀扫描）。剩余项（`is_sensitive_file` 文件名→内容扫描升级、
项目外路径 ⚠️ 标签、`install_skill` 二次确认）建议人工 smoke 后再判断
是否升入 v0.2 或延期 v0.3。

## 4. M5 工具体系优化 — 最小必须项 vs 可延期

**最小必须项（建议 M5 范围）**：
1. **工具注册一致性测试**：所有 `agent/tools/*.py` 都在 import 时显式
   `register_tool`，且 `confirmation` 字段值在 `{never / always / callable}`
   集合内。补一个 invariant 测试。
2. **元工具与业务工具区分契约固化**：`is_meta_tool` 当前依赖
   `TOOL_REGISTRY[name]["meta"]`；M4 invariant 已 assert
   `request_user_input / mark_step_complete` 是元工具，但缺一条「业务工具
   绝不能 meta=True」的负向断言。补一个测试。
3. **`SHELL_BLACKLIST` / `READONLY_COMMANDS` 双向测试**：补几个回归用例，
   防止有人改正则后悄悄放过 `rm -rf` 或拒掉 `cat`。
4. **`tool_execution_log` 截断长度**：当前 result 进 log 不截断；checkpoint
   时被 `_truncate_messages_for_checkpoint` 保护，但 task.tool_execution_log
   字段本身可能膨胀。补 spec 或最小截断。

**可延期到 v0.3**：
- 工具调用并行 / 超时 / 重试策略统一
- 工具结果结构化（dict 而非 str）
- 工具版本管理 / Skill marketplace
- 沙箱执行 / 子进程隔离
- 网络访问白名单

## 5. M6 基础安全权限 — 最小必须项 vs 可延期

**最小必须项（建议 M6 范围）**：
1. **`is_sensitive_file` 内容前缀扫描**：在文件名匹配之外，读取前 1KB
   匹配明显敏感前缀（`API_KEY=` / `-----BEGIN ` / `aws_secret` 等），
   命中 → block。最小代码改动。
2. **read_file / write_file 项目外路径标签**：在 confirmation prompt 文本
   里加「⚠️ 路径在 PROJECT_DIR 之外」短提示，让用户在 y/n 前看见。
3. **shell 命令规范化后再跑黑名单**：去引号、合并多空白、lower → 重新
   `re.search`，防止简单转义绕过。
4. **测试覆盖**：上述三项各 2-3 个用例。

**可延期到 v0.3**：
- 文件系统沙箱（chroot / namespace）
- 网络出口白名单
- API key 在内存中的进一步隔离
- 子进程权限降级
- audit log 审计签名

## 6. 人工测试前 smoke 清单

人工 smoke 必须覆盖以下场景，确认 v0.2 已稳定到可以发 release candidate：

### 6.1 状态机 / 恢复语义（M1-M3）
- [ ] 发起一段多步任务 → Ctrl+C → 重启 → 看到 awaiting_plan/step_confirmation 提示完整复现
- [ ] `request_user_input` 触发 → Ctrl+C → 重启 → 看到原 question 重放，回答后能正常推进
- [ ] 工具确认 awaiting → Ctrl+C → 重启 → pending_tool 重放
- [ ] 手改 `memory/checkpoint.json` 加未知 key → 重启不 crash 且无未知字段挂到 state

### 6.2 错误恢复 / loop guard（M4）
- [ ] 故意让模型连续 max_tokens 3 次（让模型生成超长输出）→ 看到「连续多次达到最大输出长度」停止文案
- [ ] 故意让模型用普通文本反复求助而不调元工具 → 2 次后看到 awaiting_user_input + no_progress 提示
- [ ] 工具失败（如 read_file 路径不存在）→ messages 中有可读错误，task.last_error 仍为 None

### 6.3 工具与安全（M5/M6 实现前的现状 smoke）
- [ ] `read_file ~/.env` 被 block
- [ ] `write_file agent/core.py` 被拒（受保护源码）
- [ ] `run_shell "rm -rf /"` 被黑名单拦截
- [ ] `run_shell "ls"` 静默执行（READONLY_COMMANDS）
- [ ] 项目外路径写入要求 confirmation 且明确提示

### 6.4 LLM Processing（已收口；只做不退化检查）
- [ ] `python -m llm.cli scan` 正常列出文件
- [ ] `python -m llm.cli process <file>` 用 fake provider 端到端走通
- [ ] `python -m llm.cli status` 输出 schema 完整、不泄漏 secret
- [ ] preflight `--live` 在配 `.env` 后正常返回 token 数 + 延迟（参见 `docs/LLM_PROVIDER_LIVE_SMOKE_REPORT.md`）

## 7. 本轮 preflight 结论

- M1-M4 spec 完整、不变量测试到位、checkpoint 路径硬化已落地。
- M5 / M6 真正实现需要的代码改动**很小**（每项 < 50 行），但需要先做 §6
  人工 smoke 验证 M1-M4 没有遗留问题，再统一在一次 PR 中做 M5+M6 最小补丁。
- 人工 smoke 之前**不**继续在 Runtime 层加新代码，避免「未经 LLM 真实验证
  的修改」累积。

## 8. v0.2 Release Candidate 状态

| Milestone | 状态 | 备注 |
|---|---|---|
| M1 状态机整理 | ✅ | `docs/RUNTIME_STATE_MACHINE.md` |
| M2 事件边界治理 | ✅ | `docs/RUNTIME_EVENT_BOUNDARIES.md` |
| M3 checkpoint 恢复语义 | ✅ | `docs/CHECKPOINT_RESUME_SEMANTICS.md` |
| M4 错误恢复 / loop guard | ✅ | `docs/RUNTIME_ERROR_RECOVERY.md` |
| M5 工具体系优化 | 🟡 preflight only | 本文件 §4 |
| M6 基础安全权限 | 🟡 preflight only | 本文件 §5 |
| M7 基础 TUI / CLI UX | ⏸️ 待人工测试后排期 | — |
| M8 generation cancel | ⏸️ 待人工测试后排期 | — |

**结论**：Runtime v0.2 已具备「人工测试前的 release candidate」条件——
状态机 / 事件边界 / 恢复语义 / 错误恢复四份 spec 闭环，临时事件类型与持久
状态隔离有不变量测试守护，工具与安全机制已完整审计并明确切分。

下一步建议人工跑 §6 smoke 清单，根据结果决定是否在 M5 / M6 做最小补丁。
