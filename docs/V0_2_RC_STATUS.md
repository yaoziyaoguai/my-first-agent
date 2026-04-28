# Runtime v0.2 · Release Candidate Status

> **本文件目的**：把 Runtime v0.2 当前的真实完成范围、未完成事项、3 个
> xfailed 的归属、M5/M6「preflight only」的含义、登记缺口的级别、以及
> 「现在为什么不 push」一次性写清楚。让人工测试者拿到本文档就知道
> 「我能信什么、不能信什么、踩到什么属于已知现状」。
>
> **本文件不引入新功能、不重写 spec、不改路线**。它是状态报告，不是
> 设计文档。

---

## 1. v0.2 RC 已完成范围

**主线 4 个 milestone 已闭环**（spec + 不变量测试 + 必要的代码硬化）：

| Milestone | spec | 测试 | 代码硬化 | commit |
|---|---|---|---|---|
| M1 状态机整理 | `docs/RUNTIME_STATE_MACHINE.md` | `tests/test_runtime_state_invariants.py` | — | `1594cfd` |
| M2 事件边界治理 | `docs/RUNTIME_EVENT_BOUNDARIES.md` | `tests/test_runtime_event_boundaries.py`（11） | — | `fb2f24a` |
| M3 checkpoint 恢复语义 | `docs/CHECKPOINT_RESUME_SEMANTICS.md` | `tests/test_checkpoint_resume_semantics.py`（13） | `agent/checkpoint.py::_filter_to_declared_fields` 字段白名单 | `77d77e0` |
| M4 错误恢复 / loop guard | `docs/RUNTIME_ERROR_RECOVERY.md` | `tests/test_runtime_error_recovery.py`（10） | — | `e54b708` |
| M5/M6 preflight | `docs/V0_2_TOOLING_AND_SECURITY_PREFLIGHT.md` | `tests/test_security_baseline.py`（39） | — | `7254942` |

**LLM Processing 子线已收口**（v0.2 早期落地，不在 RC 主线但确认未退化）：

- M2 LLM Processing MVP（`3863ef9`）
- M3 scan / status 审计（`7521504` + `7b5944b`）
- M4 provider config / preflight（`6c2b55b`）
- M5 真实 provider 错误分类 + live smoke（`5f3e0c3` + `a99498d` + `7b6ec35` + `46abac1`）

**测试基线**：`387 passed, 3 xfailed`（ruff 0 错误）。

---

## 2. v0.2 RC 已知限制（请人工测试者注意）

### 2.1 M5 工具体系：仅 preflight，未实施最小补丁

- 工具注册一致性的负向断言（business tool 不能 meta=True）**未补**。
- `SHELL_BLACKLIST` / `READONLY_COMMANDS` 双向回归测试**未补**。
- `tool_execution_log` 长度截断**未做**。

### 2.2 M6 基础安全：P0+P1 已补，剩余 P2+ 仍待人工 smoke

**v0.2 RC P0 已落地**（commit `fix(runtime): close v0.2 rc security smoke gaps`）：
- ✅ `is_sensitive_file` 现在按扩展名识别 `.pem` / `.key`（`SENSITIVE_SUFFIXES`）。
- ✅ `SHELL_BLACKLIST` 的 fork bomb 正则改为字面匹配，真实命中。
- ✅ `SHELL_BLACKLIST` 的 `>/dev/sd` 去掉前置 `\b`，真实命中。

**v0.2 RC P1 已落地**（commit `fix(runtime): harden v0.2 rc tool safety checks`）：
- ✅ P1-A：`_normalize_shell_command` 在原匹配未命中时跑一次规范化后再匹配，
  覆盖空引号 / 反斜杠 / tab / 多空白 / 大小写绕过。
- ✅ P1-B：`pre_write_check` 增加 `_check_dangerous_content`：私钥头 /
  fork bomb / `> /dev/sd` / `mkfs` payload 全部拒写，即使路径是 `.txt` /
  `.md`。
- ✅ P1-C：负向断言固化（业务工具不能 meta_tool=True / `confirmation`
  字段必须合法 / `is_meta_tool` 与 registry 一致 / 危险命令含规范化覆盖
  必拦截 / 安全命令不被误伤）。

**v0.2 RC P2 后续修复（smoke 中真实暴露）**：
- ✅ `pre_write_check` 增加 `_is_path_inside_project` 项目外硬拦截
  （commit `fix(runtime): block writes outside project workspace`）。
  read_file 项目外仍保持 confirm（写远比读危险，read 已有 sensitive
  block + confirm 双层保护）。
- ✅ FORCE_STOP 不再被误归类为「用户连续拒绝多次操作」
  （commit `fix(runtime): distinguish policy denial from user rejection`）。
  smoke 现象：用户单次输入「读取 ~/.env」/「读取 /tmp/server.pem」
  即被回复「用户连续拒绝多次操作，任务已停止」——根因是
  `tool_executor.py` 的 `confirmation == "block"` 分支只用通用文案，
  且 `response_handlers` 把 FORCE_STOP 一律映射到该误导消息，而
  Runtime 实际上从未存在用户拒绝计数。
  修复：`_describe_policy_denial` 给出具体的「敏感配置/密钥文件」
  原因；FORCE_STOP 总结改为「工具调用被安全策略阻断」；
  `tool_execution_log.status` 改为 `blocked_by_policy`，与未来
  可能引入的 `user_rejected` 计数语义解耦。

**仍未补**（**非 v0.2 RC blocking**，全部已在自动 smoke 中作为已知现状钉死）：
- `is_sensitive_file` 仍**只看文件名/扩展名**，不读内容前缀（改名 `.env → notes.txt`
  仍可绕过 `read_file`）。**P3 / v0.3**：read 路径加内容前缀扫描会引入文件 IO + 性能/
  误伤问题，需要单独设计；当前已通过 write 路径 P1-B 的 `_check_dangerous_content`
  对私钥写入做了拦截，反向泄漏面已收敛。
- `read_file` 项目外路径仅 confirm（write_file 已硬拦截）。**P3**：read 比 write
  风险低一个数量级，且 confirm + sensitive block 已是双层；保留。
- `install_skill` 下载内容**单次确认即执行**。**P3**：依赖 skill 安装设计，超出 RC。
- `_normalize_shell_command` 不处理 `$()` 子 shell / `eval` / 十六进制转义等高级
  绕过。**v0.3 命令解析层**做。

### 2.2.1 v0.2 RC 自动 smoke 覆盖快照

**已 100% 自动化**（运行 `pytest -q` 即覆盖；无需人工跑）：
- 敏感文件 read 拒绝（`.env` / `~/.env` / `/tmp/api.key` / `/tmp/server.pem`
  / `/tmp/notes_password.txt` 等 16 种）：`tests/test_security_baseline.py` +
  `tests/test_v0_2_rc_automated_smoke.py::test_smoke_security_sensitive_file_blocked`。
- policy denial 文案（含具体原因 / 不混用「用户拒绝」措辞 / 不读文件内容
  / `blocked_by_policy` status）：`tests/test_v0_2_rc_p1_negative.py` §8（共 8 项）。
- 项目外写入硬拦截（`~/...` / `/tmp/...` / `/etc/...` / `../` 父目录绕过）：
  `tests/test_v0_2_rc_p1_negative.py` §7。
- 项目内 `workspace/` / `docs/` / `summary.md` 不被项目外检查误伤。
- 写入 `agent/core.py` 等受保护源码拒绝。
- 写入私钥头 / fork bomb / `>/dev/sd` / `mkfs` payload 即使路径 `.txt` 也拒绝。
- shell `:(){...}` fork bomb / `RM -RF /` / `r''m -rf /` 等规范化绕过 / `>/dev/sd`
  全部命中 SHELL_BLACKLIST。
- 安全 shell（`ls -la` / `pwd` / `cat README.md`）不被误伤；calculate /
  read_file / read_file_lines 不打 stdout，不返回 raw dict。
- runtime artifacts (`.env` / `state.json` / `runs/` / `summary.md`) 不进 git。
- 真实用户拒绝路径走 `confirm_handlers` 的 `[系统] 用户拒绝执行该工具`，
  与 FORCE_STOP 完全解耦（`tests/test_complex_scenarios.py::test_mid_step_user_rejects_tool_task_continues`
  + `tests/test_v0_2_rc_p1_negative.py::test_real_user_tool_rejection_path_is_separate_from_force_stop`）。

**仍需人工观察**（自动测试无法替代）：
- TTY 渲染：`uv run` / 真 CLI 中颜色、流式打印、行截断观感。
- 真模型回路：与真实 Anthropic API（`anthropic` provider live）交互体感
  ——已在 `docs/LLM_PROVIDER_LIVE_SMOKE.md` 单独成 playbook，**默认不跑**。
- 主观可读性：拒绝消息和 plan/feedback 的中文表达是否自然。

**v0.2 RC blocking 判定**：当前列表中没有任何项被识别为 blocking。

> 上述全部登记在 `docs/V0_2_TOOLING_AND_SECURITY_PREFLIGHT.md` §3，
> 由 `tests/test_security_baseline.py` 钉死「当前确实如此」，方便补丁
> 落地时翻转为「不再如此」。

### 2.3 M7 / M8 未启动

- 没有 Textual TUI、状态面板、`generation.cancelled` RuntimeEvent。
- Esc 当前只是 Textual 输入编辑边界（见 xfail #2）。

### 2.4 不在 v0.2 范围

- Skill marketplace、sub-agent、LangGraph 风格图状编排。
- 复杂 topic switch / slash command 体系。
- 文件系统沙箱、网络出口白名单、API key 内存隔离。

---

## 3. 3 个 xfailed 的归属与不阻塞 RC 的原因

| 测试 | 文件 | 归属 | 为何不阻塞 RC |
|---|---|---|---|
| `test_user_switches_topic_mid_task` | `tests/test_hardcore_round2.py` | v0.2 输入语义治理（解锁条件：明确的 RuntimeEvent 用户确认流或 LLM 二次分类 + `awaiting_topic_switch_confirmation`） | v0.1 已显式不引入；v0.2 RC 不承诺 topic switch；不靠浅启发式回退 |
| `test_textual_shell_escape_can_cancel_running_generation` | `tests/test_input_backends_textual.py` | v0.2 cancel 生命周期（M8）+ v0.3 TUI Esc 集成（M7） | M7/M8 在 RC 主线之后；当前 Esc 仅属于 Textual 编辑边界 |
| `test_plain_cli_pasted_numbered_multiline_should_be_one_user_intent` | `tests/test_real_cli_regressions.py` | v0.3 高级 TUI（paste burst / bracketed paste / `UserInputEnvelope`） | 普通 CLI `input()` 限制；不通过强制 `/multi` 等命令绕过；属 v0.3 |

3 个 xfail 都被 docstring 显式说明了归属与解锁条件，不会因为「忘了」
而长期挂着。

---

## 4. M5/M6 「preflight only」的含义

**preflight only 不等于「这个 milestone 算完了」**，它的语义是：

1. **只读审计已完成**：清单、机制、缺口都已固化在
   `docs/V0_2_TOOLING_AND_SECURITY_PREFLIGHT.md`。
2. **回归网已建好**：`tests/test_security_baseline.py` 39 条钉死现状，
   未来打补丁能立刻看到行为变化。
3. **最小必须项 vs 延期已切分**：每项预计 < 50 行代码改动。
4. **真实代码补丁尚未提交**：等 §6 manual smoke 跑完后再统一一次性
   PR，避免「未经真实 LLM 验证的代码改动」累积。

进入「真正完成 M5/M6」需要：人工 smoke 通过 → 走 preflight §4 / §5
最小必须项清单 → 一次性 PR → 翻转 baseline 测试中的「已知缺口」断言。

---

## 5. 登记缺口的优先级建议

| 缺口 | 来源 | 建议优先级 | 理由 |
|---|---|---|---|
| ~~`is_sensitive_file` 不识别 `.pem` / `.key` 扩展名~~ | preflight §3 | ✅ **v0.2 RC P0 已修复** | — |
| ~~fork bomb 正则失效~~ | preflight §3 | ✅ **v0.2 RC P0 已修复** | — |
| ~~`>/dev/sd` 边界正则失效~~ | preflight §3 | ✅ **v0.2 RC P0 已修复** | — |
| ~~shell 引号转义绕过~~ | preflight §3 | ✅ **v0.2 RC P1-A 已修复** | — |
| ~~write_file 内容级危险扫描~~ | preflight §3 / §5 新增 | ✅ **v0.2 RC P1-B 已修复** | — |
| ~~工具注册一致性负向断言~~ | preflight §4 | ✅ **v0.2 RC P1-C 已修复** | — |
| `is_sensitive_file` 只看文件名 | preflight §3 | **P2 · 推荐补** | 改名 `.env → notes.txt` 可绕过 read 路径；需要内容前缀扫描 |
| ~~`read_file` / `write_file` 项目外路径仅 confirm~~ | preflight §3 | ✅ **write_file 已硬拦截**；read_file 仍只 confirm（P3） | — |
| `install_skill` 单次确认即执行 | preflight §3 | **P3 · 可延期 v0.3** | 与 Skill 体系整体设计相关，不在 v0.2 范围 |
| `SHELL_BLACKLIST` / `READONLY_COMMANDS` 双向回归 | preflight §4 | ✅ **P0/P1 已建立基础回归网** | — |
| `tool_execution_log` 截断 | preflight §4 | **P3** | 当前 checkpoint 已截断 messages，影响较小 |
| `$()` / `eval` / hex 转义等高级 shell 绕过 | P1-A 边界 | **v0.3 命令解析层** | 需要真实 shell parser，超出 v0.2 RC 范围 |

**人工 smoke 后**：建议把 P0 + P1 一次性合并到 `M5/M6 最小补丁`
PR；P2 / P3 单独排期或延期 v0.3。

---

## 6. 哪些必须人工 smoke 才能定，哪些可以现在就延期

### 必须人工 smoke 后再决定（不能盲目补）

- M4 错误恢复文案是否「人能看懂」（自动化只能验断言，不能验可读性）。
- M3 awaiting_plan / awaiting_tool_confirmation 重启后**复读体验**是否
  完整（自动化只能验字段持久化，不能验渲染顺序）。
- CLI 输出契约在长任务下是否真的不退化（自动化样本有限）。
- M6 已知缺口在真实模型乱拼命令时**会不会被触发**。

### 可以现在就延期到 v0.3（不在 RC 范围）

- 文件系统沙箱、子进程隔离、网络白名单。
- API key 内存隔离 / audit log 签名。
- Textual TUI、generation cancel 完整生命周期、Esc 升级为生成取消。
- Skill 平台化、sub-agent、复杂 topic switch、slash command 体系。
- 工具结果结构化（dict 而非 str）、并行调用、统一超时/重试。

---

## 7. 当前不建议 push 的原因

1. **未做端到端人工 smoke**：M1-M4 全部由不变量测试守护，但「真实模型
   + 真实 CLI 渲染 + 真实 Ctrl+C 恢复」尚未由人观察过。push 前必须
   人工跑过 §1-§5。
2. **M5/M6 仍是 preflight only**：远端如果有协作者拉到「文档说要做
   M5/M6 最小补丁但代码里没有」会困惑；建议人工 smoke 通过后，把
   M5/M6 最小补丁与 preflight 一起 push。
3. **本地 28 commits ahead 是连续 spec + 不变量序列**，整段一起 push
   时间线最干净；分批 push 反而难审计。
4. **没有 PR 模板 / CI 配置可走自动化把关**（仓库目前是个人学习项目），
   push 风险全部落在审阅时刻，越短的窗口越好。

**建议 push 时机**：人工 smoke 通过 → M5/M6 最小补丁完成并通过测试 →
一次性 push（届时本地约 30+ commits ahead）。

---

## 8. 文档索引

- `docs/V0_2_PLANNING.md` — v0.2 全 8 milestone 规划
- `docs/RUNTIME_STATE_MACHINE.md` — M1
- `docs/RUNTIME_EVENT_BOUNDARIES.md` — M2
- `docs/CHECKPOINT_RESUME_SEMANTICS.md` — M3
- `docs/RUNTIME_ERROR_RECOVERY.md` — M4
- `docs/V0_2_TOOLING_AND_SECURITY_PREFLIGHT.md` — M5/M6 审计 + 缺口
- `docs/V0_2_MANUAL_SMOKE_PLAYBOOK.md` — 本 RC 配套人工 smoke 步骤
- `docs/CLI_OUTPUT_CONTRACT.md` — CLI 输出契约（v0.1 冻结）
- `docs/LLM_PROVIDER_LIVE_SMOKE.md` — LLM Processing live smoke 安全规程
