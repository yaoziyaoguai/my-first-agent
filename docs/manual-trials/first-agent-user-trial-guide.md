# First Agent — Manual Trial Guide（可执行试用剧本）

**创建**: 2026-06-02 | **重写**: 2026-06-03 (executable playbook rewrite)
**基线**: `f6807ef` — v1 engineering closeout
**用途**: 项目 owner 本机真实终端手动试用操作手册。**可作为 Coding Agent 陪跑剧本** — 复制 §5 的 prompt 给 Coding Agent，让它作为只读试用助手。
**目标**: 验证 `docs/debt/first-agent-v2-priority-backlog.md` §1 USER_MANUAL_TRIAL 项目，不修复它们。

---

## 1. Purpose

本文档是 **First Agent project owner（你）** 用的手动试用操作手册，同时也是一个**可执行剧本**：你可以把 §5 的 prompt 复制给一个 Coding Agent，让它作为只读助手陪你跑完整个试用流程。

**本文档不是**：
- 自动化测试（不产生 pytest exit code）
- Dogfood 报告（不调真实 API）
- 修复指南（不修代码）
- v1 验收标准（v1 engineering closeout 已完成）

**本文档是**：
- 你在真实终端中手动验证用户路径的 step-by-step 剧本
- Coding Agent 作为只读助手的操作手册
- v2 USER_MANUAL_TRIAL backlog 的证据来源

---

## 2. Entry Policy

四个入口，按优先级排列。**从 Plain CLI 开始，不要从 Ink prototype 开始。**

| 优先级 | 入口 | 启动命令 | 定位 | Trial 角色 |
|--------|------|---------|------|-----------|
| **1** | Plain CLI | `python main.py` | 稳定主入口 | **基线验证** |
| **2** | Textual TUI | `python main.py --tui` | v1 TUI 候选 | **IME/paste/multiline 主验证路径** |
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
- 不把 partial workaround 写成 "可用"
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
| 主观判断 | "候选词窗口是否遮挡 TUI"、"中文标点是否正常渲染"、"乱码是否可接受" |
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

### 4.3 Coding Agent 禁止做

| 禁止行为 | 原因 |
|---------|------|
| 自动修代码 | trial 目标是验证，不是修复 |
| commit / push / tag | 文档-only 操作，不改变代码基线 |
| 读取 secret | 安全红线 |
| 声称 trial 完成 | 只有你能判定 trial 是否真正完成 |
| 把 no-crash 标 PASS | 不 crash 是最低标准 |
| 激活 TUI default entry | 需产品决策 |
| 连接生产 MCP server | 安全红线 |

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
- 当前基线：v1 engineering closeout (tag v1.0.0-engineering-closeout)
- 试用目标：验证 v2 USER_MANUAL_TRIAL backlog 中的项目

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

按以下 4 个 Phase 顺序引导我执行：

### Phase 1: Plain CLI 基线（必须最先完成）

引导我执行以下 trial cases。每完成一个，让我告诉你结果，你记录。

**T-CLI-1**: 启动 Plain CLI
- 我执行的命令: `cd /Users/jinkun.wang/work_space/my-first-agent && source .venv/bin/activate && python main.py`
- 我需要观察: 启动屏 header 是否正常（含 session/cwd/health 行），`你:` 提示符是否出现
- Pass: header 正常，提示符可交互
- Fail: 启动 crash / header 损坏 / 提示符不可见 / 出现 traceback

**T-CLI-2**: 英文输入
- 我在 `你:` 提示符下输入: `hello` → Enter
- Pass: 输入被接收，有响应返回
- Fail: 无响应 / crash / hang

**T-CLI-3**: 中文输入
- 我输入: `你好世界` → Enter
- Pass: 中文被正确接收，无乱码
- Fail: 中文乱码 / truncated / crash

**T-CLI-4**: quit 退出
- 我输入: `quit` → Enter
- Pass: session finalized，正常退出，exit code 0
- Fail: 退出时 crash / hang / exit code 非 0

**T-CLI-5**: Ctrl+C 中断
- 我操作: 启动后输入一些文本但不提交，按 Ctrl+C
- Pass: 不 crash，有明确的中断响应
- Fail: Ctrl+C 无响应 / crash / 数据损坏

**T-CLI-6**: Ctrl+D / EOF 退出
- 我操作: 启动后按 Ctrl+D
- Pass: 正常退出，无 traceback
- Fail: crash / hang
- 注意: 如果行为不同于预期，记录观察，不做 fail 判定

### Phase 2: Textual TUI 主验证

引导我执行以下 trial cases（入口: `python main.py --tui`）。

**T-FLOW-2**: TUI 英文基线
- 我输入: `hello world` → Enter
- Pass: 英文输入正常响应
- Fail: crash / 无响应

**T-IME-1**: 中文短句输入 (UMT-001)
- 我操作: 切换到中文输入法 → 输入拼音 `jintian` → 观察候选词 → 确认 → 输入完整短句 "今天天气不错" → Enter
- 关键观察: 拼音组合态期间是否触发 TUI submit？候选词窗口是否遮挡 TUI？是否有乱码？
- Pass: 完整中文句子一次性提交成功，中间无乱码/截断/意外提交
- Fail: 拼音中间态被提交 / 确认后出现乱码 / 候选词窗口导致 TUI layout 错位
- P0: 中文输入完全不可用（所有中文字符变成问号/方框/空白）

**T-IME-2**: 中英文混合输入
- 我操作: 输入 "今天" (中文) → 切换英文 → 输入 " I learned Rust async" → 切换中文 → 输入 " 很有收获" → Enter
- Pass: 完整混合文本 "今天 I learned Rust async 很有收获"，无丢失段
- Fail: IME 切换导致前段字符被清除 / 衔接处出现乱码

**T-IME-3**: 中文 + 特殊字符/标点
- 我操作: 输入含中文标点的文本 "今天学习了以下内容：1. Rust async/await 模式 2. Python coroutine ——以上。"
- Pass: 中文标点（：、/、——、。）全部正确渲染
- Fail: 中文标点变成乱码 / 全角半角混淆 / em-dash 无法输入

**T-IME-4**: Backspace 中文删除
- 我操作: 输入 "你好世界" → Backspace 2 次 → 输入 "朋友" → Enter
- Pass: 最终提交 "你好朋友"，Backspace 每次删除一个完整中文汉字
- Fail: 删除后出现 � 或方框 / 一次 Backspace 只删半个汉字

**T-PASTE-1**: 粘贴短文本
- 我操作: 复制 "Hello, this is pasted text." → 在 TUI 输入框中输入 "前缀：" → Cmd+V → Enter
- Pass: 输入框显示 "前缀：Hello, this is pasted text."，提交后完整接收
- Fail: 粘贴被忽略 / 粘贴覆盖而非追加 / 粘贴触发意外提交

**T-PASTE-2**: 粘贴多行文本
- 我操作: 从编辑器复制 3 行文本（每行中文+标点，含换行）→ Cmd+V 粘贴到 TUI 输入框 → 观察行为
- 理想: 所有行粘贴进输入框，保留换行
- 可接受: 换行被空格替代或只保留第一行但明确截断
- 不可接受: 粘贴瞬间触发 submit（只提交第一行）/ TUI crash
- Fail: 意外触发提交 / TUI crash / 粘贴内容完全丢失

**T-PASTE-3**: 粘贴中文 + 英文 + emoji 混合
- 我操作: 复制并粘贴 "今天完成了 3 项任务 ✅：Rust async 重构、Python API 修复、文档更新 📝"
- Pass: 全部字符保留，emoji 不变成乱码
- Fail: CJK 乱码 / emoji 丢失或变问号

**T-PASTE-4**: 粘贴后编辑再提交
- 我操作: 粘贴文本 → 方向键移动光标（如支持）→ 手动输入/删除几个字 → Enter
- Pass: 提交的是粘贴+编辑后的最终文本
- 注意: 如 TUI 不支持光标移动和中间编辑，记录 NOT_SUPPORTED

**T-MLINE-1**: 多行输入与提交区分
- 我操作: 尝试 Shift+Enter / Option+Enter / Ctrl+Enter 插入换行 → 输入第二行 → Enter 提交
- 理想: Shift+Enter 换行，Enter 提交
- 可接受: 不支持多行但明确（Enter 直接提交单行）
- Fail: 换行被当作提交 / TUI 崩溃
- 注意: 如框架不支持多行，记录 NOT_SUPPORTED

**T-MLINE-2**: 粘贴多行 + 手动追加
- 前提: T-PASTE-2 通过
- 我操作: 粘贴多行文本 → 末尾手动输入 "——完" → Enter
- Pass: 提交内容包含粘贴的多行 + "——完"

**T-RESIZE-1**: 调整终端窗口大小
- 我操作: 输入一些文字但不提交 → 拖动窗口改变大小 → 观察 TUI 重绘 → 继续打字 → Enter
- Pass: TUI 重绘正常，输入内容保留
- Fail: resize 后 TUI crash / render 错位 / 输入丢失

**T-EXIT-1**: q 退出
- 我操作: 按 `q`
- Pass: 正常退出，exit code 0
- Fail: crash / hang

**T-EXIT-2**: Ctrl+C 中断
- 我操作: 按 Ctrl+C
- Pass: 不 crash，有明确的退出响应
- Fail: 无响应 / crash

### Phase 3: 综合场景

**T-CONFIG-1**: Provider config UX
- 入口: `python main.py`（fake provider 默认启用）
- 我操作: 正常启动 → 观察 health 行 → 输入触发 tool use 的请求
- Pass: fake provider 正常服务；如不可用有明确提示
- Fail: provider 错误导致 crash / 静默无响应

**T-E2E-1**: 简单端到端任务
- 入口: `python main.py`
- 我操作: 输入 "帮我计算 123 + 456" → 观察 calculate tool 是否被调用 → 确认结果 → quit 退出
- Pass: 完整闭环（请求→tool invoke→结果返回→退出），各阶段无 crash
- Fail: tool 未触发 / 结果错误 / 中途 crash
- 注意: 使用 fake provider 即可，不要求真实 API

**T-COMBO-1**: IME + 粘贴组合
- 入口: `python main.py --tui`
- 我操作: 中文 IME 输入 "需求：" → Cmd+V 粘贴 "implement async runtime" → 切中文输入 "——优先级高" → Enter
- Pass: 最终提交 "需求：implement async runtime——优先级高"
- Fail: 粘贴后 IME 切换导致前段中文被清除

**T-COMBO-2**: 粘贴多行 + 中文 IME 追加
- 我操作: 粘贴多行文本 → 末尾用中文 IME 追加 "以上" → Enter
- Pass: 根据 T-PASTE-2 和 T-IME-1 结果判定

**T-COMBO-3**: 切换应用后回来
- 我操作: 输入 "测试文本" 不提交 → Cmd+Tab 切走 → 等 5 秒 → Cmd+Tab 切回 → 输入 "继续输入" → Enter
- Pass: 最终提交 "测试文本继续输入"
- Fail: 切回后输入内容被清除 / TUI 渲染异常

### Phase 4: 兼容性与 prototype（optional）

**T-SHELL-1**: --shell deprecated 兼容性
- 我执行: `python main.py --shell`
- Pass: stderr 输出 deprecation warning，然后正常进入 plain CLI
- Fail: crash / 无 deprecation warning

**T-FLOW-3**: CLI demo 命令
- 我执行: `python main.py demo "create a test note"`
- Pass: 正常输出，无 Python traceback

**T-INK-1** (optional): Ink 中文行为
- 入口: `cd tui && npm start`
- 我操作: 在 InputBar 中输入中文短句
- 不做 pass/fail 判定，只记录观察

**T-INK-2** (optional): Ink 粘贴
- 入口: `cd tui && npm start`
- 我操作: Cmd+V 粘贴短文本
- 如无效只记录（Ink 有意过滤 ctrl/meta 组合键）

**T-INK-3** (optional): Ink 多行
- 入口: `cd tui && npm start`
- 我操作: 尝试 Shift+Enter / 粘贴多行
- 只记录，不判 fail

## 每次 trial 后你需要做的事

1. 让我确认: PASS / FAIL / BLOCKED / NOT_SUPPORTED / PARTIAL
2. 如果是 FAIL，按 §6 严重度规则判定 P0/P1/P2/P3
3. 记录到 trial report（§8 模板）
4. 告诉我下一个 trial 是什么
5. 如果我连续多个 FAIL 或累了，问我是否暂停

## 全部完成后你需要做的事

1. 汇总所有 trial 结果
2. 按 §7 分类（PASS_WITH_EVIDENCE / PASS_WITH_CAVEAT / FAIL_P0 / FAIL_P1 / FAIL_P2 / FAIL_P3 / BLOCKED / NOT_SUPPORTED / MANUAL_IME_PENDING）
3. 生成最终 trial report
4. 列出建议的 v2 backlog 更新（哪些 UMT 可以更新状态、哪些需要新增）

## 严重度规则

见下方 §6。你必须在判定时使用这套规则。

## 环境记录

开始前让我确认并记录：
- Terminal: [iTerm2 / Terminal.app / Ghostty / other]
- OS: macOS version
- Shell: [zsh / bash]
- Input method: [macOS 拼音 / 搜狗 / 鼠须管 / other]
```

### ---END PROMPT---

---

## 6. Severity Rules

| 严重度 | 定义 | 触发条件 | 示例 |
|--------|------|---------|------|
| **P0** | 数据丢失 / secret 泄露 / 无法退出 / 危险操作 | trial 中发现安全漏洞、数据损坏、或程序完全不可用 | 中文输入完全不可用（所有字符变 ?/方框/空白）；API key 出现在终端输出中 |
| **P1** | 主要入口不可用 / 核心交互断裂 | Plain CLI 或 Textual TUI 的关键路径 fail | Plain CLI 无法启动；Textual TUI crash on startup；IME 中文输入 crash；粘贴 crash |
| **P2** | 重要 UX 问题 / 体验显著下降 | 非崩溃但严重影响使用的问题 | 多行输入 awkward；resize 后 layout 错位但可恢复；错误消息不清晰 |
| **P3** | 视觉瑕疵 / wording / 次要 layout | 不影响核心功能的小问题 | 中文渲染偏移 1-2 字符；颜色不统一；提示文字不准确 |

### 6.1 严重度与 v2 backlog 映射

| Trial 发现 | v2 backlog 操作 |
|-----------|----------------|
| P0 FAIL | 立即新增 P0 issue 到 v2 backlog，阻塞 v2 启动 |
| P1 FAIL | 新增或更新 UMT-001/UMT-002 为 CONFIRMED_FAIL，提升优先级 |
| P2 FAIL | 新增 P2 issue 到 v2 backlog 或更新已有 item |
| P3 FAIL | 新增 P3 issue 到 FUTURE_DEBT |
| BLOCKED | 标注阻塞原因（环境/配置/依赖），记录到 backlog |
| NOT_SUPPORTED | 转 FUTURE_DEBT，标注"当前不支持" |

---

## 7. Result Classification

每个 trial case 完成后标记以下之一：

| 结果 | 含义 | 后续操作 |
|------|------|---------|
| `PASS_WITH_EVIDENCE` | 通过，有截图或终端文本证据 | 记录证据路径，更新 backlog 状态 |
| `PASS_WITH_CAVEAT` | 通过但有已知限制 | 记录 caveat，不标为完全通过 |
| `FAIL_P0` | 失败，严重度 P0 | 立即记录，阻塞 v2 启动 |
| `FAIL_P1` | 失败，严重度 P1 | 更新对应 UMT 状态为 CONFIRMED_FAIL |
| `FAIL_P2` | 失败，严重度 P2 | 新增 v2 backlog item |
| `FAIL_P3` | 失败，严重度 P3 | 转 FUTURE_DEBT |
| `BLOCKED` | 无法执行（环境/依赖/前置条件未满足）| 记录 blocker，等待条件满足 |
| `NOT_SUPPORTED` | 功能不支持（设计如此，非 bug）| 转 FUTURE_DEBT |
| `MANUAL_IME_PENDING` | IME 验证无法自动完成，需人工确认 | 保留为 pending，不标完成 |

---

## 8. Trial Report Template

### 8.1 环境信息

```text
Date: [YYYY-MM-DD HH:MM]
Terminal: [iTerm2 / Terminal.app / Ghostty / other: ___]
OS: [macOS version]
Shell: [zsh / bash]
Input method: [macOS 拼音 / 搜狗 / 鼠须管 / other: ___]
HEAD: [git rev-parse HEAD]
Baseline: f6807ef (v1 engineering closeout)
```

### 8.2 Trial Results

```text
| Trial ID   | Result | Severity | Evidence | Notes |
|------------|--------|----------|----------|-------|
| T-CLI-1    |        | —        |          |       |
| T-CLI-2    |        | —        |          |       |
| T-CLI-3    |        | —        |          |       |
| T-CLI-4    |        | —        |          |       |
| T-CLI-5    |        | —        |          |       |
| T-CLI-6    |        | —        |          |       |
| T-FLOW-2   |        | —        |          |       |
| T-IME-1    |        |          |          |       |
| T-IME-2    |        |          |          |       |
| T-IME-3    |        |          |          |       |
| T-IME-4    |        |          |          |       |
| T-PASTE-1  |        |          |          |       |
| T-PASTE-2  |        |          |          |       |
| T-PASTE-3  |        |          |          |       |
| T-PASTE-4  |        |          |          |       |
| T-MLINE-1  |        |          |          |       |
| T-MLINE-2  |        |          |          |       |
| T-RESIZE-1 |        |          |          |       |
| T-EXIT-1   |        | —        |          |       |
| T-EXIT-2   |        | —        |          |       |
| T-CONFIG-1 |        | —        |          |       |
| T-E2E-1    |        | —        |          |       |
| T-COMBO-1  |        |          |          |       |
| T-COMBO-2  |        |          |          |       |
| T-COMBO-3  |        |          |          |       |
| T-SHELL-1  |        | —        |          |       |
| T-FLOW-3   |        | —        |          |       |
| T-INK-1    |        | —        |          | optional |
| T-INK-2    |        | —        |          | optional |
| T-INK-3    |        | —        |          | optional |
```

### 8.3 Summary

```text
Total: [N] trials
PASS_WITH_EVIDENCE: [N]
PASS_WITH_CAVEAT: [N]
FAIL_P0: [N]
FAIL_P1: [N]
FAIL_P2: [N]
FAIL_P3: [N]
BLOCKED: [N]
NOT_SUPPORTED: [N]
MANUAL_IME_PENDING: [N]
```

### 8.4 v2 Backlog Updates Needed

```text
[列出需要新增/更新的 v2 backlog items，含 UMT ID、新状态、证据]
```

---

## 9. Evidence Policy

### 9.1 收集什么

| 类型 | 说明 |
|------|------|
| Terminal screenshot | 输入框状态、提交前后对比。**不含 API key / secret / 私人文件路径** |
| Terminal copy text | `Cmd+A` → `Cmd+C` 复制 TUI 中可见文本（不含后台日志） |
| Exact command | 例如 `python main.py --tui` |
| git state | `git log --oneline -1` + `git status -sb` |
| Time | 每次 trial 时间戳 |

### 9.2 不收集什么

- API key / secret / token / password
- `config/config.yaml` 内容
- `.env` 内容
- 私人文件路径
- 真实 runtime logs（如含 API key）

### 9.3 存储

```bash
mkdir -p docs/manual-trials/evidence
```

命名: `trial-<trial-id>-<date>-<seq>.png`

**截图不要提交到 git**（体积大，可能含终端 private data）。

---

## 10. Next Steps After Trial

### 10.1 回填 v2 backlog

Trial 完成后，打开 `docs/debt/first-agent-v2-priority-backlog.md`，在 §1 USER_MANUAL_TRIAL 中更新对应 UMT 的状态：

| Trial Result | UMT 更新 |
|-------------|---------|
| 全部 IME trial PASS | UMT-001 状态可更新为 VERIFIED_ON_MANUAL_TRIAL |
| 部分 IME trial FAIL | UMT-001 标注具体 fail 项和严重度 |
| 全部 Paste trial PASS | UMT-002 状态可更新为 VERIFIED_ON_MANUAL_TRIAL |
| T-COMBO 全部 PASS | UMT-003 状态可更新为 VERIFIED_ON_MANUAL_TRIAL |

### 10.2 跨分类转换

如果 trial 发现某个问题不属于 USER_MANUAL_TRIAL：

| 发现 | 转到 | 示例 |
|------|------|------|
| 行为由模型决定，代码路径正确 | MBD (MODEL_BEHAVIOR_DESIGN) | "粘贴后模型错误解读内容" |
| 需要产品/架构决策 | PD (PRODUCT_DECISION) | "多行输入需框架迁移" |
| 当前不阻塞，未来专项 | FD (FUTURE_DEBT) | "Ink 多行 NOT_IMPLEMENTED" |
| 需外部环境配置 | RER (REAL_ENV_REQUIRED) | "需特定终端版本" |
| 确认是代码 bug | 新增 bug issue | "IME backspace 产生半字符乱码" |

### 10.3 不做的事

- **不直接标 RESOLVED**，除非 PASS evidence + 你自己认定
- **不把 no-crash 写成 PASS**
- **不把 partial workaround 写成"可用"**
- **不修代码**（trial 目标是验证，不是修复）

---

## 11. Stop Conditions

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

## 12. References

| Doc | 说明 |
|-----|------|
| `docs/debt/first-agent-v2-priority-backlog.md` | v2 优先项分类（§1 USER_MANUAL_TRIAL） |
| `docs/debt/first-agent-open-items.md` | v1 open items（UMT-001~003 原始定义） |
| `docs/design/b8-input-readiness-validation.md` | IME/Paste/Multiline readiness checklist |
| `docs/design/entry-command-clarification.md` | 入口命令优先级与架构说明 |
| `docs/releases/v1/first-agent-v1-closeout.md` | v1 engineering closeout baseline |
| `docs/PROJECT_STATUS.md` | 当前项目状态 |
| `docs/PROGRESS_LEDGER.md` | 进度历史 |
| `README.md` | 快速启动命令 |
