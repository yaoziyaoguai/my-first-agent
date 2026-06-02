# First Agent — User Manual Trial Guide

**创建**: 2026-06-02
**目标基线**: `ece15e9` — `docs(project): record unresolved open items by owner`
**用途**: 项目 owner 本机真实终端手动试用指南。不是自动化测试，不是 dogfood 报告。
**目标**: 验证 `docs/debt/first-agent-open-items.md` 中的 USER_MANUAL_TRIAL 项目，不修复它们。

---

## 1. Purpose

本文档是 **First Agent project owner (你)** 用的手动试用操作手册。

与自动化测试 / dogfood 报告 / 审计文档的区别：

| 维度 | 自动测试 | Dogfood 报告 | 本 Trial Guide |
|------|---------|-------------|---------------|
| 执行者 | Agent | Agent + 真实 API | **你** |
| 证据类型 | test pass/fail | L3 real evidence | **manual trial log** |
| 目标 | 代码正确性 | 能力验证 | **用户路径可用性判定** |
| 产出 | pytest exit code | dogfood result JSON | **UMT pass/fail/blocker + evidence** |

关键约束：
- 不修代码，只看当前状态下的真实表现
- 不把 partial workaround 写成 "user-usable"
- 试完后回填 open items 状态，不是关闭它们

---

## 2. Scope

覆盖 `docs/debt/first-agent-open-items.md` §2.2 的全部 3 个 UMT：

| Trial ID | UMT | Description | Source |
|----------|-----|-------------|--------|
| T-IME | UMT-001 | Chinese IME validation | `docs/debt/first-agent-open-items.md` lines 46-47 |
| T-PASTE | UMT-002 | Paste / multiline | `docs/debt/first-agent-open-items.md` lines 47-48 |
| T-COMBO | UMT-003 | Terminal real interaction (IME + paste + multiline 组合) | `docs/debt/first-agent-open-items.md` lines 48-49 |

每个 Trial 引用 `docs/design/b8-input-readiness-validation.md` 中的对应 checklist（I1-I7, P1-P7, M1-M4 等）。

不在 scope：
- MBC hardening (MODEL_BEHAVIOR_CONCERN)
- Product decision (PD-001~003)
- Future debt (FD-001~003)
- 代码修改
- MCP production setup

---

## 3. Preconditions

### 3.1 在你开始之前必须确认

- [ ] 当前仓库路径：`/Users/jinkun.wang/work_space/my-first-agent`
- [ ] `git status` 显示 clean，无 uncommitted changes
- [ ] `git branch --show-current` = `main`
- [ ] `git rev-list --left-right --count @{u}...HEAD` = `0  0` (与 origin/main 同步)
- [ ] `config/config.yaml` 未被 `git status` 列为 modified/staged
- [ ] 不打印、不提交、不复制 `config/config.yaml` 中的 API key
- [ ] 不打开任何可能捕获终端内容的录屏/直播工具（如果有，关闭后再开始）
- [ ] 如果 trial 中需要截图，确认截图不含 API key / secret / 私人数据

### 3.2 环境记录

开始前记录以下信息（用于填入 §9 Result Log）：

```text
Terminal: [iTerm2 / Terminal.app / Ghostty / other: ___]
Terminal version: [___]
OS: [macOS version — 点  → 关于本机]
Shell: [echo $SHELL]
Input method: [macOS 拼音 / 搜狗 / 鼠须管 / 日文假名 / 韩文 / other: ___]
TUI mode: [Textual --tui / Ink npm start — 见 §4]
Python: [python3 --version]
Node: [node --version if using Ink TUI]
```

### 3.3 安全边界

- **禁止** `cat config/config.yaml` 后复制内容到 trial log
- **禁止** 把 API key / secret 放进截图、log、或本文档回填
- **禁止** 在 trial 期间 `git add config/config.yaml`
- 如果 config.yaml 被意外修改且含真实 key：**立即停止**，`git checkout config/config.yaml`

---

## 4. How to Start

项目有两个 TUI 入口，用途不同：

### 入口 A：Textual Shell（推荐用于本 trial）

```bash
cd /Users/jinkun.wang/work_space/my-first-agent
source .venv/bin/activate
python main.py --tui
```

- 后端：基于 Textual（Python TUI 框架）
- 输入方式：Textual Input widget
- 这是 README.md 记录的 `--tui` 入口（`--shell` 已弃用，仍兼容 plain CLI）
- 默认使用 fake provider（不调真实 API，零 secret 风险）
- **推荐从入口 A 开始**

### 入口 B：Ink TUI（备选，如需验证 Ink useInput 行为）

```bash
cd /Users/jinkun.wang/work_space/my-first-agent/tui
npm start
```

- 前端：基于 Ink 5 + React 18（Node.js TUI 框架）
- 输入方式：Ink `useInput` hook
- 这是一个 visual shell prototype，不是生产入口
- 所有数据自包含 fixture，不连接 runtime
- `docs/design/b8-input-readiness-validation.md` 的 IME 分析基于此入口
- **作为辅助对比入口使用**

### 入口比较

| 维度 | 入口 A (Textual --tui) | 入口 B (Ink npm start) |
|------|--------------------------|------------------------|
| IME 行为 | Textual Input widget 处理 | Ink useInput 处理 |
| 粘贴行为 | Textual 原生支持 | Ink 不区分键盘/粘贴 |
| 多行 | Textual 可能有内置支持 | 当前 NOT_IMPLEMENTED |
| 与 runtime 连接 | 是 (fake provider) | 否 (fixture only) |
| 推荐优先级 | **先试这个** | 对比用 |

> **注意**: 如果入口 A 的 exact command 与你本地的不一致（例如 venv 路径不同），使用你本地的正确路径。如果你不确定，先 `ls .venv/bin/python` 确认。

---

## 5. Trial Scenarios

### 5.1 T-IME — Chinese IME Validation (UMT-001)

**Source**: `docs/debt/first-agent-open-items.md` UMT-001
**Input readiness checklist**: `docs/design/b8-input-readiness-validation.md` §2.1 I1-I7

#### T-IME-1: 中文短句输入

| 项 | 内容 |
|----|------|
| **Purpose** | 验证中文拼音 IME 在 TUI 输入框中的组合态/确认态行为 |
| **Setup** | 入口 A (`python main.py --tui`)，确认 TUI 启动成功，输入区域可见 |
| **Actions** | 1. 切换到中文输入法 (macOS 拼音) 2. 在输入框输入拼音 `jintian` (今天) 3. 观察候选词列表是否正常显示（在输入框之外还是覆盖了 TUI 界面） 4. 按空格/数字键确认候选词 5. 输入完整短句: "今天天气不错" 6. 按 Enter 提交 |
| **Expected** | 拼音组合态期间不触发 TUI submit（中间拼音字母不应被当作最终输入提交）；按 Enter 时提交的是"今天天气不错"而非 `jintiantianqibucuo` |
| **Observe** | 候选词窗口是否遮挡 TUI、输入框字符是否正确渲染、是否有乱码/重复字符 |
| **Pass criteria** | 完整中文句子一次性提交成功，中间无乱码/截断/意外提交 |
| **Fail criteria** | 拼音中间态被提交、确认后出现乱码、候选词窗口导致 TUI layout 错位 |
| **Blocker criteria** | 中文输入完全不可用（所有中文字符变成问号/方框/空白） |
| **Evidence** | 提交前后各一张截图、输入框显示截图（不含私人数据） |

#### T-IME-2: 中英文混合输入

| 项 | 内容 |
|----|------|
| **Purpose** | 验证 IME 在中文和英文之间切换时输入不丢字符 |
| **Setup** | 同 T-IME-1 |
| **Actions** | 1. 输入 "今天" (中文 IME) 2. 切换回英文 3. 输入 " I learned Rust async" 4. 再切换中文 5. 输入 " 很有收获" 6. 按 Enter 提交 |
| **Expected** | 完整混合文本: "今天 I learned Rust async 很有收获"，无丢失段 |
| **Fail criteria** | IME 切换导致前半段字符被清除、中英文衔接处出现多余空格或乱码 |

#### T-IME-3: 中文 + 特殊字符/标点

| 项 | 内容 |
|----|------|
| **Purpose** | 验证中文标点和特殊字符在 IME 中的表现 |
| **Setup** | 同 T-IME-1 |
| **Actions** | 1. 输入 "今天学习了以下内容：" 2. 换行或接续输入 "1. Rust async/await 模式" 3. 接续 "2. Python coroutine" 4. 接续 "——以上。" |
| **Expected** | 中文标点（：、/、——、。）全部正确渲染 |
| **Fail criteria** | 中文标点变成乱码、全角/半角混淆、em-dash 无法输入 |

#### T-IME-4: Backspace 中文删除

| 项 | 内容 |
|----|------|
| **Purpose** | 验证按 Backspace 时按完整中文字符删除，不产生半字符乱码 |
| **Setup** | 同 T-IME-1 |
| **Actions** | 1. 输入 "你好世界" 2. 按 Backspace 2 次 3. 输入 "朋友" 4. 按 Enter 提交 |
| **Expected** | 最终提交: "你好朋友"；Backspace 每次删除一个完整中文汉字，不出现半字符乱码 |
| **Fail criteria** | 删除后出现 � 或方框、一次 Backspace 只删了半个汉字 |

#### T-IME-5 (可选): 入口 B Ink useInput 中文行为

| 项 | 内容 |
|----|------|
| **Purpose** | 对比入口 B (Ink) 的中文输入行为，验证 `docs/design/b8-input-readiness-validation.md` 的 IME 分析 |
| **Setup** | `cd tui && npm start`，确认 WorkbenchLayout 渲染成功 |
| **Actions** | 同 T-IME-1，在 InputBar 中输入中文 |
| **Expected** | 观察 Ink useInput 是否如文档所说逐键提交 composition 中间态 |
| **Pass** | 不做 pass/fail 判定，只记录观察结果 |
| **Note** | 入口 B 是 prototype，不作为 production 标准 |

---

### 5.2 T-PASTE — Paste Validation (UMT-002)

**Source**: `docs/debt/first-agent-open-items.md` UMT-002
**Input readiness checklist**: `docs/design/b8-input-readiness-validation.md` §2.2 P1-P7

> **重要**: 以下粘贴操作适用两个入口。如果某个入口粘贴不可用，记录"不可用"并切换到另一个入口对比。

#### T-PASTE-1: 粘贴短文本 (Cmd+V)

| 项 | 内容 |
|----|------|
| **Purpose** | 验证粘贴短文本正确追加到输入框 |
| **Setup** | 入口 A (`python main.py --tui`) |
| **Expected** | 输入框显示 "前缀：Hello, this is pasted text."，提交后完整接收 |
| **Fail criteria** | 粘贴被忽略、粘贴内容覆盖而非追加、粘贴触发意外提交 |

#### T-PASTE-2: 粘贴多行文本

| 项 | 内容 |
|----|------|
| **Purpose** | 验证粘贴多行文本时 TUI 不崩溃、不意外提交 |
| **Setup** | 入口 A |
| **Actions** | 1. 从编辑器复制以下多行文本：<br>`第一行：`<br>`第二行：`<br>`第三行：`<br>（每行都是中文+标点，含换行） 2. Cmd+V 粘贴到 TUI 输入框 3. 观察行为 4. 如果未自动提交，按 Enter |
| **Expected** | 理想：所有行粘贴进输入框，保留换行；可接受：换行被空格替代或只保留第一行但明确截断；不可接受：粘贴瞬间触发 submit 导致只提交第一行、TUI crash |
| **Fail criteria** | 粘贴时意外触发提交、TUI crash/卡死、粘贴内容完全丢失 |
| **Note** | 这是已知高风险场景 — Ink useInput 的 `key.return` 可能被粘贴中的 `\n` 触发 |

#### T-PASTE-3: 粘贴中文 + 英文 + 符号混合

| 项 | 内容 |
|----|------|
| **Purpose** | 验证 CJK + ASCII + emoji 混合粘贴完整保留 |
| **Setup** | 入口 A |
| **Actions** | 复制并粘贴: `今天完成了 3 项任务 ✅：Rust async 重构、Python API 修复、文档更新 📝` |
| **Expected** | 全部字符保留，emoji 不变成乱码 |
| **Fail criteria** | CJK 变成乱码、emoji 丢失或变成问号 |

#### T-PASTE-4: 粘贴后编辑再提交

| 项 | 内容 |
|----|------|
| **Purpose** | 验证粘贴后手动编辑不被阻止 |
| **Setup** | 入口 A |
| **Actions** | 1. 粘贴文本 2. 用方向键移动到中间某位置 (如果支持) 3. 手动输入/删除几个字 4. 按 Enter 提交 |
| **Expected** | 提交的是粘贴+编辑后的最终文本 |
| **Note** | 如果 TUI 不支持光标移动和中间编辑，记录 NOT_SUPPORTED，不判 fail |

#### T-PASTE-5 (可选): 入口 B Ink 粘贴行为对比

| 项 | 内容 |
|----|------|
| **Purpose** | 对比 Ink useInput (过滤 `key.ctrl`) 下的 Cmd+V 行为 |
| **Setup** | `cd tui && npm start` |
| **Actions** | 在 InputBar 中 Cmd+V 粘贴短文本 |
| **Expected** | 如果粘贴无效，只记录，不判 fail |
| **Note** | 入口 B 的 InputBar 有意过滤了 ctrl/meta 组合键，粘贴可能不可用 — 这是预期行为 |

---

### 5.3 T-MLINE — Multiline Input Validation (UMT-002 后半)

**Source**: `docs/debt/first-agent-open-items.md` UMT-002
**Input readiness checklist**: `docs/design/b8-input-readiness-validation.md` §2.3 M1-M4

> **重要**: 多行输入支持取决于 TUI 框架。入口 A (Textual) 可能有内置支持；入口 B (Ink) 明确 NOT_IMPLEMENTED。以下场景先以入口 A 为主。

#### T-MLINE-1: 多行输入与提交区分

| 项 | 内容 |
|----|------|
| **Purpose** | 验证是否能输入多行、是否能区分换行操作和提交操作 |
| **Setup** | 入口 A |
| **Actions** | 1. 在输入框中尝试输入第一行文字 2. 试 Shift+Enter / Option+Enter / Ctrl+Enter 插入换行（如果框架支持） 3. 输入第二行 4. 按 Enter 提交 |
| **Expected** | 理想：Shift+Enter 换行，Enter 提交，两行都进入提交内容；可接受：不支持多行但明确（Enter 直接提交单行） |
| **Fail criteria** | 换行被当作提交、TUI 在换行后崩溃 |
| **Note** | 如果 TUI 框架明确不支持多行输入，记录 NOT_SUPPORTED，不判 fail |

#### T-MLINE-2: 粘贴多行 + 手动追加

| 项 | 内容 |
|----|------|
| **Purpose** | 验证粘贴多行后手动打字不破坏内容 |
| **Setup** | 入口 A |
| **Actions** | 1. 粘贴来自 T-PASTE-2 的多行文本 2. 如果粘贴成功且未自动提交，在末尾手动输入 "——完" 3. 按 Enter 提交 |
| **Expected** | 提交内容包含粘贴的多行文本 + 手动追加的 "——完" |
| **Note** | 取决于 T-PASTE-2 的结果 |

#### T-MLINE-3 (可选): 入口 B 多行对比

| 项 | 内容 |
|----|------|
| **Purpose** | 确认入口 B 多行 NOT_IMPLEMENTED 状态是否准确 |
| **Setup** | `cd tui && npm start` |
| **Actions** | 尝试 Shift+Enter / 粘贴多行 |
| **Expected per docs**: 多行 NOT_IMPLEMENTED |
| **Note** | 只记录，不判 fail |

---

### 5.4 T-COMBO — Combined Terminal Real Interaction (UMT-003)

**Source**: `docs/debt/first-agent-open-items.md` UMT-003

#### T-COMBO-1: IME + 粘贴组合

| 项 | 内容 |
|----|------|
| **Purpose** | 验证中文 IME 输入与粘贴操作之间切换不丢状态 |
| **Setup** | 入口 A |
| **Actions** | 1. 用中文 IME 输入 "需求：" 2. 从编辑器粘贴一段英文: "implement async runtime" 3. 再切回中文 IME 输入 "——优先级高" 4. 按 Enter |
| **Expected** | 最终提交: "需求：implement async runtime——优先级高" |
| **Fail criteria** | 粘贴后 IME 切换导致前段中文被清除 |

#### T-COMBO-2: 粘贴多行 + 中文 IME 追加

| 项 | 内容 |
|----|------|
| **Purpose** | 组合验证 paste + multiline + IME |
| **Setup** | 入口 A |
| **Actions** | 1. 粘贴多行文本 2. 在末尾用中文 IME 追加 "以上" 3. 按 Enter 提交 |
| **Expected** | 根据 T-PASTE-2 和 T-IME-1 的结果确定 |
| **Fail criteria** | 中文追加导致粘贴内容被清除、TUI crash |

#### T-COMBO-3: 切换终端窗口后回来

| 项 | 内容 |
|----|------|
| **Purpose** | 验证 Cmd+Tab 切走后再回来，TUI 输入状态不丢失 |
| **Setup** | 入口 A |
| **Actions** | 1. 用中文 IME 输入 "测试文本" 但不提交 2. Cmd+Tab 切换到另一个应用 3. 等待 5 秒 4. Cmd+Tab 切换回终端 5. 继续输入 "继续输入" 6. 按 Enter |
| **Expected** | 最终提交: "测试文本继续输入"，中间切换不丢已输入内容 |
| **Fail criteria** | 切回后输入内容被清除、TUI 渲染异常 |

#### T-COMBO-4: 调整终端窗口大小

| 项 | 内容 |
|----|------|
| **Purpose** | 验证 resize 终端窗口时 TUI 不崩溃、输入不丢 |
| **Setup** | 入口 A |
| **Actions** | 1. 在输入框中输入一些文字但不提交 2. 拖动窗口改变大小 (横向拉宽、纵向拉高) 3. 观察 TUI 是否重绘正常 4. 继续打字 5. 按 Enter |
| **Expected** | TUI 重绘，输入内容保留 |
| **Fail criteria** | resize 后 TUI crash/render 错位/输入丢失 |

---

### 5.5 T-FLOW — 基础交互流 （附加，不绑定特定 UMT）

作为背景，确认基础 CLI/TUI 交互路径是否通路。这些不替代 UMT trial，但提供上下文。

#### T-FLOW-1: CLI demo 命令

```bash
python main.py demo "create a test note"
```

| 项 | 内容 |
|----|------|
| **Purpose** | 确认 CLI demo 通路正常 (fake provider) |
| **Observe** | 输出是否正常、是否有 Python traceback |
| **Note** | 如果失败，可能是 venv 未激活或依赖未安装 |

#### T-FLOW-2: TUI 基础打字 (英文)

| 项 | 内容 |
|----|------|
| **Setup** | 入口 A |
| **Actions** | 输入 "hello world" → Enter |
| **Purpose** | 确认英文输入通道正常 |
| **Note** | 建立基线 |

---

## 6. Result Log Template

每次试用后填写一行。复制以下表格，多轮试用时追加。

```text
| Trial ID | Date | Environment | Input | Expected | Actual | Result | Evidence path | Notes | Follow-up |
|----------|------|-------------|-------|----------|--------|--------|---------------|-------|-----------|
| T-IME-1  |      | macOS __ / iTerm2 __ / 拼音 / Textual | 今天天气不错 | 完整中文提交 |      |      |      |      |      |
| T-IME-2  |      |             |       |          |        |        |               |       |           |
| T-IME-3  |      |             |       |          |        |        |               |       |           |
| T-IME-4  |      |             |       |          |        |        |               |       |           |
| T-IME-5  |      |             |       |          |        |        |               |       |           |
| T-PASTE-1|      |             |       |          |        |        |               |       |           |
| T-PASTE-2|      |             |       |          |        |        |               |       |           |
| T-PASTE-3|      |             |       |          |        |        |               |       |           |
| T-PASTE-4|      |             |       |          |        |        |               |       |           |
| T-PASTE-5|      |             |       |          |        |        |               |       |           |
| T-MLINE-1|      |             |       |          |        |        |               |       |           |
| T-MLINE-2|      |             |       |          |        |        |               |       |           |
| T-MLINE-3|      |             |       |          |        |        |               |       |           |
| T-COMBO-1|      |             |       |          |        |        |               |       |           |
| T-COMBO-2|      |             |       |          |        |        |               |       |           |
| T-COMBO-3|      |             |       |          |        |        |               |       |           |
| T-COMBO-4|      |             |       |          |        |        |               |       |           |
| T-FLOW-1 |      |             |       |          |        |        |               |       |           |
| T-FLOW-2 |      |             |       |          |        |        |               |       |           |
```

**Result 值**：`PASS` / `FAIL` / `BLOCKED` / `NOT_SUPPORTED` / `PARTIAL`

**Environment 格式**: `macOS <version> / <terminal> / <input-method> / <tui-entry>`

---

## 7. Evidence Policy

### 7.1 收集什么

| 类型 | 说明 |
|------|------|
| Terminal screenshot | 输入框状态、提交前后对比。不含 API key/secret/私人文件路径 |
| Terminal copy text | `Cmd+A` → `Cmd+C` 复制 TUI 中可见文本（不含后台日志） |
| Exact command used | 例如 `python main.py --tui` |
| git state | `git log --oneline -1` + `git status -sb` |
| Time | 每次 trial 时间戳 |

### 7.2 不收集什么

- API key / secret / token / password
- `config/config.yaml` 内容
- `.env` 内容
- 私人文件路径 (HOME 目录以外的个人文件)
- 真实的 runtime logs 如果含 API key（日志默认已脱敏，但检查后再保存）

### 7.3 存储位置

建议截图保存在 `docs/manual-trials/evidence/` 下：

```bash
mkdir -p docs/manual-trials/evidence
```

命名: `trial-<trial-id>-<date>-<seq>.png`

> **注意**: `docs/manual-trials/evidence/` 如果有截图，不要提交到 git（截图体积大，且可能含终端 private data）。可以加到 `.gitignore` 或手动忽略。

---

## 8. How to Update Open Items After Trial

### 8.1 回填流程

1. 完成一组 trial (例如 T-IME-1~4)
2. 打开 `docs/debt/first-agent-open-items.md`
3. 在对应的 UMT 行后追加 trial 结果摘要

### 8.2 结果映射

| Trial Result | 对 UMT 的处理 | 后续 |
|-------------|--------------|------|
| PASS | 标注为 `VERIFIED_ON_MANUAL_TRIAL` + date + evidence path | UMT 可以从 open items 中降级 |
| FAIL | 标注为 `CONFIRMED_FAIL` + trial ID | 新增 bug / open item |
| BLOCKED | 标注为 `BLOCKED` + reason | 记录 blocker；如果是环境依赖，标 REAL_ENV_REQUIRED |
| NOT_SUPPORTED | 标注为 `NOT_SUPPORTED` | 转 FUTURE_DEBT |
| PARTIAL | 标注为 `PARTIAL` + what passed / what didn't | 拆分为多个子项 |

### 8.3 跨分类转换

如果 trial 发现某个 UMT 实际属于其他分类：

| 发现 | 转换目标 | 示例 |
|------|---------|------|
| 行为是模型决定的，代码路径正确 | MBC (MODEL_BEHAVIOR_CONCERN) | "粘贴后模型错误解读内容" |
| 需要产品/架构决策 | PD (PRODUCT_DECISION) | "多行输入应该支持但需要框架迁移" |
| 当前不阻塞，需要未来专项 | FD (FUTURE_DEBT) | "Ink 多行输入 NOT_IMPLEMENTED" |
| 需要外部环境配置 | REAL_ENV_REQUIRED | "需要特定终端版本" |
| 确认是代码 bug | 新增 bug issue | "IME backspace 产生半字符乱码" |

### 8.4 不做什么

- **不直接标 RESOLVED**，除非正向 PASS evidence + 你自己认定
- **不把 no-crash 写成 PASS** — 不 crash 是最低标准，不是 capability
- **不把 partial workaround 写成 "可用"**

---

## 9. Stop Conditions

以下情况**立即停止**：

1. `config/config.yaml` 被修改且 `git diff` 显示它包含真实 key — `git checkout config/config.yaml`
2. 截图/终端输出中出现真实 API key 或 secret
3. TUI 卡死无法恢复 (Ctrl+C 无效且 `kill` 无效)
4. 你发现当前命令与实际仓库代码不一致
5. trial 步骤与 `docs/debt/first-agent-open-items.md` 的描述矛盾
6. 需要 Product Decision 才能继续（例如需要激活 TUI default entry 但不确定要不要做）

停止后：
- 记录在 §6 Result Log，标注 `BLOCKED`
- 不要继续修改代码或配置文件
- 如果是 secret 安全风险，优先处理 secret

---

## 10. Quick Start Checklist

对，这就是给你马上开始用的：

- [ ] Step 1: `cd /Users/jinkun.wang/work_space/my-first-agent && git status -sb` — 确认 clean
- [ ] Step 2: 记录 Environment (Terminal / OS / Shell / Input Method) 到 §6
- [ ] Step 3: 打开 §6 Result Log 模板，复制到编辑器
- [ ] Step 4: `source .venv/bin/activate && python main.py --tui` — 启动入口 A
- [ ] Step 5: 执行 T-FLOW-2 (英文基线) → 填入 Result Log
- [ ] Step 6: 从 T-IME-1 开始 → T-IME-2 → T-IME-3 → T-IME-4
- [ ] Step 7: 执行 T-PASTE-1 → T-PASTE-2 → T-PASTE-3 → T-PASTE-4
- [ ] Step 8: 执行 T-MLINE-1 → T-MLINE-2
- [ ] Step 9: 执行 T-COMBO-1 → T-COMBO-3 → T-COMBO-4
- [ ] Step 10: 汇总 §6 Result Log，按 §8 回填 `docs/debt/first-agent-open-items.md`

### 建议顺序

先安全后风险：
1. 英文基线 (T-FLOW-2)
2. 中文 IME (T-IME-1~4) — 最关键的验证
3. 粘贴 (T-PASTE-1~4) — 注意 T-PASTE-2 有意外提交风险
4. 多行 (T-MLINE-1~2) — 可能 NOT_SUPPORTED
5. 组合场景 (T-COMBO-1~4) — 接近真实使用

---

## 11. References

| Doc | 说明 |
|-----|------|
| `docs/debt/first-agent-open-items.md` | UMT-001~003 source |
| `docs/design/b8-input-readiness-validation.md` | IME/Paste/Multiline checklist |
| `docs/PROJECT_STATUS.md` | 当前项目状态 |
| `docs/handoff/first-agent-current-stage-close-out-2026-06-02.md` | FROZEN close-out handoff |
| `README.md` | 快速启动命令 |
