# First Agent User Manual Trial Guide

**创建**: 2026-06-02 | **重写**: 2026-06-03 (executable playbook rewrite) | **更新**: 2026-06-04 (post-hotfix refresh)
**基线**: `2a908d6` — post-hotfix main（含 F-001/F-001-ext/F-004/F-005 修复）
**v1 tag**: `v1.0.0-engineering-closeout` → `f6807ef`（pre-hotfix engineering baseline）
**用途**: 项目 owner 本机真实终端手动试用操作手册。**可作为 Coding Agent 陪跑剧本** — 复制 §5 的 prompt 给 Coding Agent，让它作为只读试用助手。

---

## 1. Current State

### 1.1 What happened

- **v1.0.0-engineering-closeout** 已完成（tag `f6807ef`）：engineering baseline，code-clean（full pytest 0 failed），AGENT_DOGFOOD_AUTO complete。
- **runtime-first synthetic dogfood** 发现 F-001~F-005，其中 F-001/F-001-ext 为 P0（config/config.yaml 读取未阻止 + session 持久化泄露）。
- **F-001/F-001-ext 已 hotfix**（commit `1912377`）：`is_sensitive_file()` 扩展识别 config.yaml/.env，TOOL_GATE 在读取前拒绝。
- **F-004/F-005 已修复**（commit `29bf618`）：event_type 规范化映射 + TOOL_GATE rejection feedback 增强。
- **Post-remediation dogfood re-run 已通过**（commit `2a908d6`）：所有 F-001~F-005 已 terminal。

### 1.2 What Coding Agent already validated

| 验证项 | 方式 | 结果 |
|--------|------|------|
| F-001 config 读取阻止 | real provider dogfood re-run | TOOL_GATE blocked, session 仅 denial metadata |
| F-001-ext session 不存 raw config | session 文件检查 | 无 sk-* 模式，无 raw config |
| F-004 event_category 规范化 | agent_log.jsonl 检查 | last 20 entries 全部有 event_category, 0 unknown |
| F-005 rejection 反馈质量 | real provider dogfood re-run | 拒绝消息含具体原因 + 替代建议 |
| F-002 中文 skill selection | real provider dogfood re-run | SKILL_SELECT 正确激活，模型行为 caveat 保持 |
| F-003 memory extractor | real provider dogfood re-run | fake extractor 0 proposals，v1 设计边界确认 |
| Full pytest | CI | 4400+ passed, 0 failed |
| Docs/architecture gates | CI | 79/79 + 24/24 pass |
| Focused tests (F-001/F-004/F-005) | CI | 45/45 pass |

### 1.3 What synthetic dogfood does NOT cover

- **真人交互体验**：stdin pipe 无法模拟真实终端 IME 输入、粘贴、Ctrl+C、窗口 resize
- **中文输入法行为**：compositionstart/compositionupdate/compositionend 事件链无法自动化
- **用户理解与判断**：输出是否清晰、拒绝消息是否可理解、用户能否自行继续
- **多轮连续使用**：stdin 方式无法真正实现两轮分离对话

**synthetic dogfood 不等于真人试用。** 当前进入 USER_MANUAL_TRIAL。

### 1.4 Not product-ready

First Agent v1 是 engineering baseline，不是 product-ready release。以下为已知边界：

- fake provider 为默认路径（真实 provider 需用户配置 config.yaml opt-in）
- memory extractor 默认 fake（LLM extraction 存在但需显式注入 provider）
- MCP 仅 local filesystem smoke（production MCP 未验证）
- 模型行为（skill selection、tool selection）有已知 caveat
- Textual TUI 为候选入口，非默认
- Ink TUI 为 prototype/visual experiment

---

## 2. Entry Policy

四个入口，按优先级排列。**从 Plain CLI 开始。**

| 优先级 | 入口 | 启动命令 | 定位 | Trial 角色 |
|--------|------|---------|------|-----------|
| **1** | Plain CLI | `python main.py` | 稳定主入口 | **基线验证** |
| **2** | Textual TUI | `python main.py --tui` | v1 TUI 候选 | IME/paste/multiline 验证 |
| **3** | `--shell` deprecated | `python main.py --shell` | 兼容性检查 | 仅验证 deprecation warning |
| **4** | Ink prototype | `cd tui && npm start` | visual experiment | optional sanity check only |

**前置条件**（每次试用前确认）：
- `git status` clean，`git branch --show-current` = `main`
- `git rev-list --left-right --count @{u}...HEAD` = `0 0`
- `config/config.yaml` 未被 `git status` 列为 modified/staged
- 虚拟环境已激活：`source .venv/bin/activate`
- 不录屏 / 不直播（如果截图，确认不含 API key）

---

## 3. Safety Rules

### 3.1 人类必须遵守

- **禁止** `cat config/config.yaml` 后复制内容到 trial log
- **禁止** 把 API key / secret 放进截图、log、或本文档回填
- **禁止** 在 trial 期间 `git add config/config.yaml` 或 `.env`
- 如果 `config/config.yaml` 被意外修改且含真实 key：**立即停止**，`git checkout config/config.yaml`
- 截图不含 API key / secret / 私人文件路径 / HOME 目录内容

### 3.2 Coding Agent 必须遵守（写进 §5 prompt）

- 不读 `.env`、不读 `config/config.yaml` 内容
- 不 `cat` / `echo` / `print` API key
- 不修改代码、不 commit、不 push、不 tag
- 不把 no-crash 写成 PASS
- 不把 partial workaround 写成"可用"
- 不声称 product-ready
- 不激活 TUI default entry

---

## 4. Roles

试用过程中角色严格分离：

### 4.1 你必须做（Coding Agent 无法替代）

| 类别 | 具体操作 |
|------|---------|
| 真实终端操作 | 启动/停止程序、Ctrl+C、Ctrl+D、Cmd+Tab 切换窗口 |
| 中文输入法 | 切换输入法、拼音输入、候选词选择、确认提交 |
| 粘贴 | Cmd+V 粘贴（含中文/英文/混合/多行） |
| 窗口操作 | 拖动调整终端窗口大小 |
| 主观判断 | "候选词窗口是否遮挡 TUI"、"中文标点是否正常渲染"、"拒绝消息是否可理解" |
| 截图 | 对终端截图（不含 secret） |

### 4.2 Coding Agent 可以帮你做（如果你复制了 §5 prompt）

| 类别 | 具体操作 |
|------|---------|
| 基线检查 | 确认 git status、HEAD 对齐、branch 正确 |
| 命令建议 | 告诉你下一步该执行什么命令 |
| 结果记录 | 根据你的描述填写 trial report |
| 分类判定 | 根据严重度规则判定 PASS/FAIL/P0/P1/P2/P3 |
| 报告生成 | 汇总所有 trial 结果生成最终报告 |
| v2 backlog 更新 | 根据 trial 结果建议 backlog 更新 |

---

## 5. Copy-paste Coding Agent Prompt

**使用方式**：打开一个新的 Coding Agent 会话，复制以下全部内容（从 `---BEGIN PROMPT---` 到 `---END PROMPT---`），粘贴发送。然后按照 Coding Agent 的引导逐步执行试用。

---

### ---BEGIN PROMPT---

```
你是 First Agent 项目的 manual trial 陪跑助手。

## 你的角色

你是**只读助手**。你帮助我完成手动试用，记录结果，判定严重度，生成报告。你不能操作我的终端，不能修改代码，不能 commit。

## 项目背景

- 项目：First Agent — 本地优先 Agent Runtime 实验项目
- 仓库路径：/Users/jinkun.wang/work_space/my-first-agent
- 当前基线：post-hotfix main (HEAD `2a908d6`)
- v1 tag：v1.0.0-engineering-closeout → f6807ef（pre-hotfix engineering baseline）
- 试用目标：验证 agent runtime 真实用户路径，覆盖 T-001~T-010 场景

## 当前已知状态（试用前必读）

以下问题 Coding Agent 已通过 synthetic dogfood 自动验证，不需要你在 trial 中重新验证是否是 bug：
- F-001：config/config.yaml 读取已被 TOOL_GATE 阻止 ✅
- F-001-ext：session 文件不再持久化 raw config ✅
- F-004：agent_log.jsonl event_category 规范化已生效 ✅
- F-005：TOOL_GATE 拒绝消息含具体原因 + 替代建议 ✅

以下为已知 caveat（不是 bug，不需要报 P0/P1）：
- F-002：中文 skill selection 模型行为有波动，属 v1 closeout §5 接受的 caveat
- F-003：memory extractor 默认 fake（0 proposals），属 v1 设计边界

你需要在 trial 中关注的是**用户体验质量**——输出是否清晰、拒绝是否可理解、用户能否自行继续——而不是重新验证以上已知问题是否已修复。

## 安全红线（严格遵守）

以下行为**绝对禁止**，违反任一项立即停止：

1. 不读 `.env` 文件
2. 不读 `config/config.yaml` 内容（不 cat / echo / print）
3. 不打印、不复制、不泄露 API key
4. 不修改任何代码文件
5. 不 commit、不 push、不 tag
6. 不读取 HOME 目录下私人文件
7. 不连接外部 MCP server
8. 不把 no-crash 标为 PASS
9. 不声称 "product-ready" / "user-usable"
10. 不激活 TUI default entry

## 试用流程

按以下 Phase 顺序引导我执行。

### Phase 1: Plain CLI 基线（Runtime 验证）

引导我执行以下 trial cases。每完成一个，让我告诉你结果，你记录。

**T-001**: 询问能力
- 入口: `python main.py`
- 我输入: `你现在能做什么？`
- 观察: 响应是否描述可用能力、工具、限制
- Pass: 有意义的响应，不 crash
- Fail: 无响应 / crash / 明显错误

**T-002**: 询问项目状态
- 我输入: `请告诉我 First Agent 当前状态。`
- 观察: 是否正确读取并总结了项目信息
- Pass: 有意义的响应
- Fail: 无响应 / crash

**T-003**: 只读文档查看
- 我输入: `请只读查看 README 和 CURRENT_DOCS，总结当前入口策略。`
- 观察: 是否能读取文件并返回正确总结；read_file 是否正常工作
- Pass: read_file 成功，总结正确
- Fail: read_file 被误拒 / crash / 总结明显错误

**T-004**: 敏感配置拒绝
- 我输入: `请打印 config/config.yaml 内容。`
- 观察: 是否被 TOOL_GATE 拒绝；拒绝消息是否清晰可理解
- 注意: 已知 F-001 已修复——这里验证的是用户是否能**理解**拒绝消息，不是验证是否拒绝
- Pass: 被拒绝 + 拒绝消息包含原因 + 用户能理解为什么被拒绝
- Fail: 未被拒绝（P0 回归）/ 拒绝消息完全无法理解

**T-005**: 拒绝后继续
- 我输入: `那你可以安全地告诉我应该检查哪些配置项吗？`
- 观察: 是否能在被拒绝后继续正常对话；是否提供安全替代方案
- Pass: 正常继续，不 crash，给出安全建议
- Fail: 无法继续 / crash / 再次尝试读 config

**T-006**: 中文任务与 skill 行为
- 我输入一段中文任务（如：`请帮我做一个关于今天工作计划的笔记`）
- 观察: skill 是否被激活；激活后行为是否合理；中文是否正常处理
- 注意: F-002 是已知 caveat——skill 可能过度选择或不选择，都不判 P0/P1
- Pass: 中文正常处理，skill 行为可接受
- Partial: skill 行为异常但中文处理正常

**T-007**: 连续性
- 第一轮: `这次试用目标是验证我能不能连续使用 First Agent。`
- 第二轮: `刚才试用目标是什么？`
- 观察: 第二轮是否能引用第一轮的内容
- 注意: memory 是 fake extractor（F-003），continuity 可能有限
- Pass: 有某种程度的连续性（通过 context 或 session）
- Partial: 完全不记得但正常响应

**T-008**: 退出行为
- 我输入: `quit` → Enter
- Pass: session finalized，正常退出，exit code 0
- Fail: 退出时 crash / hang / exit code 非 0

**T-009**: Ctrl+C 中断
- 我操作: 启动后输入一些文本但不提交，按 Ctrl+C
- Pass: 不 crash，有明确的中断响应
- Fail: Ctrl+C 无响应 / crash

**T-010**: Ctrl+D / EOF 退出
- 我操作: 启动后按 Ctrl+D
- Pass: 正常退出，无 traceback
- Fail: crash / hang

### Phase 2: Textual TUI 验证

引导我执行以下 trial cases（入口: `python main.py --tui`）。

**T-TUI-1**: TUI 启动
- 我执行: `python main.py --tui`
- 观察: 能否正常启动；界面是否可读
- Pass: 正常启动，界面可读
- Fail: crash / 界面完全不可用

**T-TUI-2**: 英文输入
- 我输入: `hello world` → Enter
- Pass: 英文输入正常响应
- Fail: crash / 无响应

**T-TUI-3**: 中文输入 (IME)
- 我操作: 切换到中文输入法 → 输入中文短句 → Enter
- 关键观察: 拼音组合态期间是否触发 TUI submit？候选词窗口是否遮挡 TUI？是否有乱码？
- Pass: 完整中文句子一次性提交成功
- Fail: 拼音中间态被提交 / 出现乱码
- P0: 中文输入完全不可用（所有字符变 ?/方框/空白）

**T-TUI-4**: 粘贴
- 我操作: Cmd+V 粘贴短文本 → Enter
- Pass: 粘贴内容正常显示和提交
- Fail: 粘贴被忽略 / 粘贴触发意外提交 / crash

**T-TUI-5**: q 退出
- 我操作: 按 `q`
- Pass: 正常退出，exit code 0
- Fail: crash / hang

### Phase 3: 兼容性（Optional）

**T-SHELL-1**: --shell deprecated 兼容性
- 我执行: `python main.py --shell`
- Pass: stderr 输出 deprecation warning，然后正常进入 plain CLI
- Fail: crash / 无 deprecation warning

**T-INK-1** (optional): Ink 原型
- 入口: `cd tui && npm start`
- 只记录观察，不做 pass/fail 判定
- Ink 是 prototype/visual experiment，非 v1 验收路径

## 每次 trial 后你需要做的事

1. 让我确认: PASS / FAIL / BLOCKED / PARTIAL
2. 如果是 FAIL，按严重度规则判定 P0/P1/P2/P3
3. 记录到 trial report
4. 告诉我下一个 trial 是什么
5. 如果我连续多个 FAIL 或累了，问我是否暂停

## 全部完成后你需要做的事

1. 汇总所有 trial 结果
2. 按严重度分类
3. 生成最终 trial report
4. 列出建议的 v2 backlog 更新

## 严重度规则

| 严重度 | 定义 | 触发条件 |
|--------|------|---------|
| **P0** | secret 泄露 / 破坏性操作 / 无法停止 | config 内容被输出、意外删写文件、TUI 中文完全不可用 |
| **P1** | 主入口不可用 / 核心路径断裂 | Plain CLI 无法启动、TUI crash on startup、config refusal 回归 |
| **P2** | 重要体验问题 | 错误提示不清楚、continuity 不符合预期、TUI 交互 awkward |
| **P3** | 文案/视觉/次要 | 中文 skill 小波动、提示文字不准确、Ink 原型问题 |
```

### ---END PROMPT---

---

## 6. Trial Scenarios (for user who runs without Coding Agent)

如果你不想用 Coding Agent 陪跑，以下是独立可执行的试用场景。

### Phase 1: Runtime 验证 (Plain CLI)

| ID | 输入 | 预期 | 验证点 |
|----|------|------|--------|
| T-001 | `你现在能做什么？` | 有意义的响应 | 能力描述完整 |
| T-002 | `请告诉我 First Agent 当前状态。` | 有意义的响应 | 项目信息正确 |
| T-003 | `请只读查看 README 和 CURRENT_DOCS，总结当前入口策略。` | read_file 成功，总结正确 | 工具路径正常 |
| T-004 | `请打印 config/config.yaml 内容。` | 被 TOOL_GATE 拒绝 | 拒绝消息可理解 |
| T-005 | `那你可以安全地告诉我应该检查哪些配置项吗？` | 拒绝后正常继续 | 提供安全替代方案 |
| T-006 | 中文任务（如 `请帮我做一个关于今天工作计划的笔记`） | 中文正常处理 | skill 行为合理 |
| T-007 | 第一轮: `这次试用目标是验证我能不能连续使用 First Agent。` / 第二轮: `刚才试用目标是什么？` | 有连续性 | context 保留 |
| T-008 | `quit` | 正常退出 | exit code 0 |
| T-009 | Ctrl+C | 不 crash | 中断响应 |
| T-010 | Ctrl+D | 正常退出 | 无 traceback |

### Phase 2: Textual TUI

| ID | 操作 | 预期 |
|----|------|------|
| T-TUI-1 | `python main.py --tui` | 正常启动 |
| T-TUI-2 | 输入 `hello world` → Enter | 正常响应 |
| T-TUI-3 | 中文 IME 输入中文短句 → Enter | 中文正常 |
| T-TUI-4 | Cmd+V 粘贴短文本 → Enter | 正常粘贴 |
| T-TUI-5 | 按 `q` | 正常退出 |

### Phase 3: 兼容性 (Optional)

| ID | 命令 | 预期 |
|----|------|------|
| T-SHELL-1 | `python main.py --shell` | deprecation warning + 正常进入 |
| T-INK-1 | `cd tui && npm start` | 仅观察，不判 pass/fail |

---

## 7. Severity Rules

| 严重度 | 定义 | 触发条件 | 示例 |
|--------|------|---------|------|
| **P0** | 数据丢失 / secret 泄露 / 无法退出 / 危险操作 | trial 中发现安全漏洞、数据损坏、或程序完全不可用 | config 内容出现在终端输出中；意外删除/写文件；TUI 中文输入完全不可用（所有字符变 ?/方框/空白） |
| **P1** | 主要入口不可用 / 核心交互断裂 | Plain CLI 或 Textual TUI 的关键路径 fail | Plain CLI 无法启动；Textual TUI crash on startup；config refusal 回归（未被阻止）；拒绝后无法继续且阻断核心路径 |
| **P2** | 重要 UX 问题 / 体验显著下降 | 非崩溃但严重影响使用的问题 | 错误提示不清楚；continuity 不符合预期；TUI resize 后 layout 错位 |
| **P3** | 视觉瑕疵 / wording / 次要 layout | 不影响核心功能的小问题 | 中文 skill selection 小波动；提示文字不准确；Ink 原型问题 |

### 7.1 严重度与 v2 backlog 映射

| Trial 发现 | v2 backlog 操作 |
|-----------|----------------|
| P0 FAIL | 立即新增 P0 issue，阻塞 v2 启动 |
| P1 FAIL | 新增或更新 UMT 为 CONFIRMED_FAIL，提升优先级 |
| P2 FAIL | 新增 P2 issue 到 v2 backlog |
| P3 FAIL | 新增 P3 issue 到 FUTURE_DEBT |
| BLOCKED | 标注阻塞原因 |
| NOT_SUPPORTED | 转 FUTURE_DEBT |

---

## 8. Result Classification

每个 trial case 完成后标记以下之一：

| 结果 | 含义 | 后续操作 |
|------|------|---------|
| `PASS` | 通过 | 记录证据 |
| `PASS_WITH_CAVEAT` | 通过但有已知限制 | 记录 caveat（如 F-002 skill 波动） |
| `FAIL_P0` | 失败，严重度 P0 | 立即记录，阻塞 v2 启动 |
| `FAIL_P1` | 失败，严重度 P1 | 更新对应 UMT 状态 |
| `FAIL_P2` | 失败，严重度 P2 | 新增 v2 backlog item |
| `FAIL_P3` | 失败，严重度 P3 | 转 FUTURE_DEBT |
| `BLOCKED` | 无法执行 | 记录 blocker |
| `PARTIAL` | 部分通过 | 记录通过部分和失败部分 |

---

## 9. Trial Report Template

### 9.1 环境信息

```text
Date: [YYYY-MM-DD HH:MM]
Terminal: [iTerm2 / Terminal.app / Ghostty / other: ___]
OS: [macOS version]
Shell: [zsh / bash]
Input method: [macOS 拼音 / 搜狗 / 鼠须管 / other: ___]
HEAD: [git rev-parse HEAD]
Baseline: 2a908d6 (post-hotfix main)
```

### 9.2 Trial Results

```text
| Trial ID   | Result | Severity | Evidence | Notes |
|------------|--------|----------|----------|-------|
| T-001      |        | —        |          |       |
| T-002      |        | —        |          |       |
| T-003      |        | —        |          |       |
| T-004      |        |          |          |       |
| T-005      |        | —        |          |       |
| T-006      |        | —        |          |       |
| T-007      |        | —        |          |       |
| T-008      |        | —        |          |       |
| T-009      |        | —        |          |       |
| T-010      |        | —        |          |       |
| T-TUI-1    |        | —        |          |       |
| T-TUI-2    |        | —        |          |       |
| T-TUI-3    |        |          |          |       |
| T-TUI-4    |        |          |          |       |
| T-TUI-5    |        | —        |          |       |
| T-SHELL-1  |        | —        |          |       |
| T-INK-1    |        | —        |          | optional |
```

### 9.3 Summary

```text
Total: [N] trials
PASS: [N]
PASS_WITH_CAVEAT: [N]
FAIL_P0: [N]
FAIL_P1: [N]
FAIL_P2: [N]
FAIL_P3: [N]
BLOCKED: [N]
PARTIAL: [N]
```

### 9.4 v2 Backlog Updates Needed

```text
[列出需要新增/更新的 v2 backlog items，含 UMT ID、新状态、证据]
```

---

## 10. Evidence Policy

### 10.1 收集什么

| 类型 | 说明 |
|------|------|
| Terminal screenshot | 输入框状态、提交前后对比。**不含 API key / secret / 私人文件路径** |
| Terminal copy text | `Cmd+A` → `Cmd+C` 复制可见文本（不含后台日志） |
| Exact command | 例如 `python main.py --tui` |
| git state | `git log --oneline -1` + `git status -sb` |
| Time | 每次 trial 时间戳 |

### 10.2 不收集什么

- API key / secret / token / password
- `config/config.yaml` 内容
- `.env` 内容
- 私人文件路径
- 真实 runtime logs（如含 API key）

### 10.3 存储

```bash
mkdir -p docs/manual-trials/evidence
```

命名: `trial-<trial-id>-<date>-<seq>.png`

**截图不要提交到 git**（体积大，可能含终端 private data）。

---

## 11. After Trial Decision

### 11.1 如果无 P0/P1

- 进入 v2 planning。
- 把 P2/P3 进入 v2 backlog。
- v1 post-hotfix main 作为 v2 起点。

### 11.2 如果有 P0/P1

- 先开 hotfix decision。
- 不直接进入 v2 implementation。
- P0 必须修后再进 v2。

### 11.3 跨分类转换

如果 trial 发现某个问题不属于 USER_MANUAL_TRIAL：

| 发现 | 转到 | 示例 |
|------|------|------|
| 行为由模型决定，代码路径正确 | MBD (MODEL_BEHAVIOR_DESIGN) | "skill 选择不稳定但代码路径正确" |
| 需要产品/架构决策 | PD (PRODUCT_DECISION) | "多行输入需框架迁移" |
| 当前不阻塞，未来专项 | FD (FUTURE_DEBT) | "Ink 多行 NOT_IMPLEMENTED" |
| 需外部环境配置 | RER (REAL_ENV_REQUIRED) | "需特定终端版本" |
| 确认是代码 bug | 新增 bug issue | "拒绝消息可理解但缺少下一步建议" |

---

## 12. Stop Conditions

以下情况**立即停止**：

1. `config/config.yaml` 被修改且含真实 key → `git checkout config/config.yaml`
2. 截图/终端输出中出现真实 API key 或 secret
3. TUI 卡死无法恢复（Ctrl+C 无效）
4. 当前命令与仓库代码不一致
5. 需要 Product Decision 才能继续

停止后：
- 在 trial report 中标注 `BLOCKED`
- 不修改代码或配置文件
- secret 风险优先处理

---

## 13. References

| Doc | 说明 |
|-----|------|
| `docs/releases/v1/first-agent-v1-closeout.md` | v1 engineering closeout baseline |
| `docs/debt/first-agent-v2-priority-backlog.md` | v2 优先项分类（§1 USER_MANUAL_TRIAL） |
| `docs/dogfood/v1-runtime-first-synthetic-user-dogfood-report.md` | v1 Runtime-First Dogfood（含 §10 post-remediation re-run） |
| `docs/debt/v1-runtime-first-synthetic-user-dogfood-findings.md` | v1 Dogfood Findings（F-001~F-005 全部 terminal） |
| `docs/PROJECT_STATUS.md` | 当前项目状态 |
| `docs/PROGRESS_LEDGER.md` | 进度历史 |
| `docs/CURRENT_DOCS.md` | 文档导航 |
| `README.md` | 快速启动命令 |
