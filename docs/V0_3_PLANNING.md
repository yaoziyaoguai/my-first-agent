# Runtime v0.3 Planning · Usability Track

> 本文件目的：在 v0.2 已 tag `v0.2.0` 的基础上，定义 v0.3 的目标、非目标、
> milestone 顺序与完成标准，避免 v0.3 又被「Reflect / Self-Correction /
> 完整 TUI / Skill 平台 / sub-agent / generation cancel / topic switch /
> slash command 复活」等高估能力的支线带跑偏。
>
> v0.3 是 Runtime 的 **usability 阶段**：让 Agent 在当前安全边界与输出契约
> 之上，对人工试用更友好、对维护和长期运行更可观测。**它不是新能力大爆炸**。

---

## 1. 目标（in scope）

让 v0.2 已经稳定的 Runtime 在「人工日常使用 + 长期维护」两个场景上更可用：

- 让 CLI 输出的 session / checkpoint / status / goal / plan / current step /
  tool 链路对人工读者更结构化、更可扫读。
- 让 v0.2 已识别的非阻塞健康 warning（workspace_lint / log_size /
  session_accumulation）有可视化 + 可归档 + 可清理的维护流程。
- 让现存的 Skill 系统从「写得很粗糙、提示词偏强」过渡到「明确范围 + 明确
  失败模式 + 明确不做的事」，**不强求成熟化**。
- 让 observer / agent_log.jsonl / sessions 在 size 增长之外，**有最小可读性
  增强**（按 session 检索、关键事件高亮）。

## 2. 非目标（explicitly out of scope）

下面这些**在 v0.3 一律不做**。如果后续真的要做，在 v0.4+ 再单开 milestone：

- ❌ Reflect / Self-Correction / LLM judge / self-evaluation loop
- ❌ 复杂 planner 纠错或 multi-shot replan
- ❌ sub-agent / multi-agent 协作
- ❌ 完整 Textual 多面板 / timeline viewer / event replay
- ❌ generation cancellation（cancel_token + stream abort + Esc cancel）
- ❌ 复杂 topic switch（已撤销过一次，不要复活）
- ❌ slash command 体系
- ❌ Skill marketplace / Skill lifecycle 完整化
- ❌ 真实 LLM live smoke 自动化（仍是 `--live` 手动开关）
- ❌ HTTP transport 重写、阿里云/任何新 provider 接入
- ❌ 健康检查 metric → Prometheus / Grafana 等 SRE pipeline

> 任何写在「非目标」里的能力，如果在 v0.3 进行中被发现需要，**先停下来跟用户
> 确认是否扩 roadmap，不要默默扩**。

---

## 3. Milestone 顺序

按依赖关系 + 用户日常使用频度排序，先小后大：

### v0.3 M1 · 基础 TUI / CLI Shell MVP
让人工使用更顺手。**纯渲染层强化 + 命令行 UX 增强**，不引入 Textual 多面板、
不引入快捷键、不引入 cancel。详见本文 §5。

**状态**：✅ 已完成首个迭代。落地内容：

- 新增 `agent/cli_renderer.py`：纯函数渲染 session header / resume status /
  status line / health 摘要，零运行时副作用。
- 新增 `agent/session.py::summarize_session_status`：把 AgentState 压成
  脱敏摘要 dict（status / user_goal / step_index / message_count /
  pending_tool_name / plan_total_steps / actionable）。
- 重写 `agent/session.py::init_session`：用结构化 header 替代
  「=== My First Agent (Refactored) ===」两行 print，并通过
  `run_health_check(verbose=False)` 把健康检查长块压缩为单行。
- 重写 `agent/session.py::try_resume_from_checkpoint`：用
  `render_resume_status` 渲染三态（无 checkpoint / idle 残留 / actionable），
  「无 checkpoint」也变成可见提示。
- 给 `agent/health_check.py::run_health_check` 加 `verbose=True` 默认参数，
  v0.2 兼容；False 模式只返回 results 不打印长块。
- 测试：`tests/test_cli_renderer.py`（13 tests）+
  `tests/test_session_summary_and_header.py`（10 tests）。
- 真实 smoke：`python main.py` 启动屏幕已是结构化 shell header；
  4 类工具结局文案沿用 v0.2 契约不变。

### v0.3 M2 · Health Maintenance 可视化
基于 v0.2 的 `python main.py health` 子命令扩展为：
- `health --json`：机器可读输出
- `health archive logs|sessions`：把 agent_log.jsonl / sessions 归档到
  可配置目录，**默认只移动不删除**
- `health prune workspace --dry-run`：列出可清理的 workspace 文件，
  默认只列不删
- 文档：`docs/V0_3_HEALTH_MAINTENANCE.md`

完成标准：人工可以「查 → 决定 → 安全归档/清理」三步走完，不再需要看
docs 手抄命令。

### v0.3 M3 · Skill 体系坦诚化
**先承认现状粗糙，再画范围**：
- 列出当前 Skill 系统真正在做的事（提示词 / 注册表 / 偶尔 install）
- 列出当前 Skill 提示词「偏强」的具体表现（v0.2 RC smoke 观察项）
- 给 Skill 加最小契约：什么是 Skill、什么不是 Skill、Skill 可以触发什么
  工具、不可以触发什么工具
- **不**做 Skill marketplace、不做 sub-agent 触发、不做远端 Skill 加载
- 输出文档：`docs/V0_3_SKILL_REDESIGN.md`

完成标准：能用一段中文向新读者说清「v0.3 的 Skill 是什么 / 不是什么」，
并把过强的提示词裁剪到不会让模型反复尝试无意义工具调用。

### v0.3 M4 · Observer / Logs 可读性
- `agent_log.jsonl` 增加按 session_id 索引和按事件类型筛选的最小 CLI
  工具（`python main.py logs --session <id>` / `--event tool.failed`）
- 给敏感字段做最后一道脱敏复核（v0.2 已经查过一轮，M4 把它固化为测试）
- 不引入 SQLite、不引入 ELK、不引入新格式

### v0.3 backlog（**v0.3 不实现**）
- sub-agent / multi-agent
- 完整 Textual 多面板 + 快捷键
- Esc cancel / generation cancellation
- 复杂 topic switch / slash command
- Reflect / Self-Correction / LLM judge
- Skill marketplace / 远端加载
- 真实 LLM live smoke 自动化

---

## 4. 完成标准（v0.3 release readiness 时再核对）

- M1-M4 全部 ship 或显式登记为 partial（带原因）。
- ruff 0 错；pytest 全绿（允许永久 xfail，但每个都必须有归属说明）。
- 至少一次真实人工 smoke（同 v0.2 的格式），结果记录在
  `docs/V0_3_MANUAL_SMOKE_RESULT.md`。
- 防泄漏审计延续：`tests/test_gitignore_runtime_artifacts.py` 通过，
  `git ls-files` 复核命令在 `RELEASE_NOTES_v0.3.md` 写明。
- v0.3 backlog 没有被偷偷做掉。

---

## 5. v0.3 M1 · 基础 TUI / CLI Shell MVP — 最小实现计划

> 本节是计划，**不在本文件落地实现**。实现要等用户明确说「开始 v0.3 M1」。

### 5.1 目标
让用户在普通终端跑 `python main.py` 时，能在不读源码的前提下，**看清楚**：

- 当前 session id（短哈希形式）+ 启动时间
- checkpoint / resume 状态（idle / pending tool / awaiting input / in plan）
- 当前 task status / goal / current plan step
- 每次工具调用：tool name / input 摘要 / 4 类结局
  （completed / failed / rejected / user_rejected）+ status_text
- policy denial / user rejection 的具体原因（不只是「执行失败」）
- 模型回复的明显边界（开始 / 结束 / 总结）
- 总输入/总输出的 token 累计（如果 provider 已经返回）

### 5.2 非目标（M1 不做）
- ❌ 完整 Textual 多面板布局
- ❌ 快捷键（Esc / Ctrl-C 仍然走默认行为）
- ❌ generation cancel / stream abort
- ❌ timeline / event viewer
- ❌ 弹窗 / 滚动面板 / 鼠标交互
- ❌ 主题切换 / 颜色配置文件
- ❌ paste burst（v0.3 backlog 单独条目）

M1 输出**仍然是 plain stdout**，只是更结构化。Textual / 多面板留 v0.4。

### 5.3 涉及文件（预计）
- `agent/display_events.py`：增加 session-header / status-line 渲染
- `agent/cli_renderer.py`（可能新建，从 main.py / display_events.py 抽出渲染）
- `main.py`：在 init_session 后输出 session header；在每次状态变化后刷一个
  紧凑 status line
- `agent/session.py`：暴露 `summarize_session_status() -> dict` 给渲染层用，
  避免渲染层直接访问 state internals
- `docs/V0_3_BASIC_CLI_SHELL_PLAN.md`（新建：M1 范围与契约）
- `docs/CLI_OUTPUT_CONTRACT.md`：扩 §9 加 session-header / status-line 契约
- `tests/test_cli_session_header.py`（新建）
- `tests/test_cli_status_line.py`（新建）

### 5.4 测试策略
- **单元测试**：`summarize_session_status` 在 idle / pending tool /
  awaiting input / in plan 四种状态下返回字段完备且不含敏感字段。
- **渲染测试**：给定 status dict → 渲染器输出固定字符串模板，方便人工
  diff / CI 守护。
- **集成测试**：fake provider + 一段 scripted 对话 → 检查 stdout 中
  session header / status line / 4 类工具结局都按契约出现。
- **不**做 snapshot test 占用大文件；只断言关键关键字与字段。

### 5.5 最小验收标准
- 启动时 stdout 第一屏可看到：session id、启动时间、当前 status、是否有
  resume、健康检查摘要（沿用 v0.2）。
- 每次工具调用前后有清楚的「请求 → 确认 → 执行 → 结局」四段渲染，
  4 类结局文案沿用 v0.2 契约不变。
- 从输出中读不到：api key、私钥内容、headers 原值、base_url 原值、
  raw prompt / completion。
- ruff + pytest 全绿。
- 一次真实人工 smoke（最少 5 类场景：success / failure / pre-check
  rejected / policy denied / user rejected）输出可读、无回归。

### 5.6 风险
- **过度设计风险**：M1 容易被带去做面板 / 颜色 / 快捷键。锚点：M1 输出
  仍是 plain stdout，PR diff 不应包含 textual / rich.live / curses。
- **状态泄漏风险**：`summarize_session_status` 必须返回脱敏字段，
  不能把整个 state 序列化进渲染层。
- **测试脆性风险**：渲染断言用关键字 + 字段，不用整段字符串等价比较。
- **与 v0.2 输出契约冲突风险**：四类工具结局文案必须保持 v0.2 不变；
  M1 只在外层补 session header / status line，不改工具结局渲染。

---

## 6. 跟 ROADMAP 的关系

- 本文件不替代 `docs/ROADMAP.md`，只是 v0.3 阶段的**详细 planning**。
- ROADMAP 后续会同步加一行「v0.3 usability track」并指向本文件，但本轮
  不大改 ROADMAP，避免 v0.2 release commit 之后立刻又写一堆未完成承诺。
