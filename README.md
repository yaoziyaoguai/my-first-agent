# my-first-agent

一个从当前目录开始工作的 local-first 日常 Agent。

`1.0.0` 的定位不是增加更多能力，而是让第一次安装、guided setup、无参数启动、可选 Web、暂停与恢复
形成一条普通用户可理解的默认路径。该交付曾按 fail-closed 机制验收（detached
`docs/acceptance/016_FIRST_AGENT_1_0_INDEPENDENT_REVIEW.md` 只对当时 delivery identity 记录 U3 PASS）。
2026-09-09 曾冻结为学习里程碑（tag `study-freeze-2026-09-09-candidate`，指向 `901bc55`）；同日
r19 产品化审计解除冻结后，项目转入日常可用性修复（见下方状态快照）。各能力对当前工作树 identity
保持 `implemented-candidate`，历史晋级结论只绑定当时 delivery identity。

它使用同一个自然语言入口回答问题、讨论想法或完成有界的当前目录文件任务。底层仍刻意保持为一个模型循环、一个上下文管理器、一个受治理的工具执行路径和一个可恢复状态机。它可以在逐次批准后通过固定 Tavily 入口查询公开 Web；015 Governed Local Action 已通过真实 E3、独立评审与 Codex 终裁，曾作为已交付能力提供受治理的结构化本机执行（`local_process`：exact 同意批准、Goal 限定租约、closed 环境与资源档案；历史晋级只绑定当时 delivery identity，见下方状态快照）。018 另提供可选的受治理专属隔离 Chromium 能力（candidate）。个人浏览器、任意网站兼容、桌面控制与任意 shell 仍不在交付范围内，也不存在第二套 Agent loop。

## 当前状态快照（2026-10-18）

2026-09-09 r18 冻结（consolidated 候选 commit `684f368` / tree `10d36564`，source full gate
3372 passed / 3 skipped）后，r19 审计解除冻结并转向产品化。2026-10-16 可靠性收口（完整门
3873 passed、installed 41 节点、真实层 61/80 请求）只绑定当时工作树 identity；该 identity 已被
2026-10-17 日用收口修改（W1 明确文件交付对象完成下界、W2 散文 targets 精确文件复用授权、
W3 验收 driver 不催促不救场），旧身份数字不再描述当前工作树。当前 identity 的交付门、安装与
真实层证据逐项记录在唯一
[RESULTS](docs/handoffs/2026-10-11-product-reliability-closure/RESULTS.md)。2026-10-18 CLI 个人试用
收尾补齐验证目录绑定、两种明确审批的语义一致性与业务失败分类。新安装物已完成真实普通编码
样本（业务检查与产品终态均通过）；纠正/恢复样本在累计预算边界暂停、零改写样本未运行，
因此完整真实验收仍未闭合。试用须准备项目依赖并独立检查结果，不能冒用旧身份的真实通过记录。

2026-10-23：consent-ux 冻结合同已实施并通过全库门（4100 passed / 1 skipped / 0 failed）
与真实模型 dogfood（1 次 `s` 覆盖全程常规发送；同一文件 3 次重写仅 1 次审批；读类输出
的逐次披露为本轮合同接受的边界，实测小任务 16 次）；oracle 对抗审计两轮采纳的缺陷已
全部修复。E2/E3 历史真实验收因上游退役 `deepseek-v4-flash` 与 anthropic 兼容端点而阻塞
（详见 RESULTS）。

**开箱即用边界**：Scheduler 安装入口返回 `needs_019_config`（无可用的 host composition，见下文
Durable automations 节）；受治理浏览器（018）为 implemented-candidate 且未完成 D06 真实模型验收；
`--strict-tools` 与含开放 object 的工具 schema 组合会在请求发送前 fail closed（见 HTTP Provider 节）。
历史 PASS（包括 2026-07-25 七项 v1 reference 晋级与 016–019 各独立评审）只对当时绑定的 identity
有效；旧 seal/check 相对当前工作树全部 drift，fail-closed 校验正常工作。权威明细见
[Current Capability Status](docs/architecture/CURRENT_CAPABILITY_STATUS.md)。

## 当前能力

- 多轮文本对话
- 会话级外发许可与文件复用快捷选择（2026-10-21 consent-ux 轮）：远端模型首次发送可选
  `s`（本会话常规对话数据，32 次发送 / 60 分钟，`/revoke-provider-consent` 随时撤销）；
  文件审批处可直接选 `f`（同文件/本任务复用，16 次 / 60 分钟）或 `d`（已声明目录复用），
  均等价于既有 slash 范围命令；写结果的稳定来源在许可内静默复用。读/验证类输出
  （目录列表、读文件、命令 stdout 等）不属于稳定来源，包含它们的每次发送仍会单独披露
- 确定性、限额明确的上下文构建
- 串行工具调用与精确审批；文件修改可由用户显式选择当前任务的精确目标复用授权
- `read_file`、`list_files`、`write_file`、`edit_file`；缺失目录可经独立审批的
  `make_directory` 逐层创建，文件写入仍需另一次精确审批
- 经 exact approval 的结构化 `local_process`；Goal-scoped 权限租约可过期、限次并可撤销
- 经同一治理路径的 `sandbox_exec`（macOS Seatbelt，`read-only` / `workspace-write`）与 `shell_exec`（exact shell command string，`/bin/sh -c`，任何模式下 network off）；两者都走 exact approval、`EXECUTING` checkpoint 与 bounded runner
- 压力触发的自动上下文压缩：只在安全边界（无 pending approval / takeover / unknown effect）分批进行；压缩摘要只作 untrusted context，不替代 Goal、Approval、Recovery、Evidence 或任何 authority
- owner-only、不可变、按 source checkpoint digest 幂等归档的 pre-compaction transcript archive
- 当前 workspace 内的有界路径、全文和分段检索
- 当前 exact workspace 中 First Agent 自己保存的历史检索；不观察其他本机活动
- 固定 Tavily Search/Extract 公开 Web 工具：每次 exact query/URL batch 单独批准
- Runtime 铸造的来源回执、统一 Sources 视图、citation sidecar 与 provenance evidence
- 本地 v1 checkpoint、暂停、恢复与未知工具结果处置
- FakeProvider；通用 OpenAI-compatible 非流式 HTTP adapter；Anthropic-compatible 与精确
  DeepSeek Flash 推理配置的 **流式** HTTP adapter
  （SSE：回答文本增量在生成期间实时到达 CLI/TUI，最终响应仍由 Runtime 一次接纳——增量只是
  advisory 显示，丢失/重复/断流不改变权威结果与 durable state）
- 同一套 typed action / event / result 合同下的 CLI 与 headless 调用
- 同一自然语言入口中的直接回答、最小澄清与 durable Goal
- Goal pause/resume/cancel/correction、确定性重启与 unknown-effect recovery
- remote Provider 外发前的精确 disclosure acknowledgement
- Runtime-owned evidence gate：只有满足 admitted criteria 才显示 `VERIFIED_DONE`；用户原文中
  点名要求创建/修改的明确文件是完成下界——草稿遗漏该文件时，非空泛化声明不能通过完成门。
  这是有限下界（2026-10-18 A 包）：支持汉字直接邻接的 ASCII 相对路径、跨分句引文与围栏
  代码块的排除、日志报告输入的有限语法，不承诺任意隐含要求、日志/引号、Unicode 文件名、
  Windows 路径或 URL 的语义识别；支持汉字邻接 ASCII 路径不等于支持所有 Unicode 路径
- 散文描述的任务（未列精确 targets）同样可用精确文件复用授权：首次批准某文件写入后，后续同
  工具写同一文件时提示无参数 `/approve-goal-target`，显式 opt-in 后铸造同一 Goal/revision 绑定
  的限次租约
- 有来源、可纠正、可停止未来召回的 owner preference

history、workspace 文件和 Web 内容都作为 untrusted data 进入模型上下文。来源回执证明的是“观察来自哪里、
内容与哪次 receipt/digest 绑定”，不证明内容在语义上必然正确，也不代表用户已经接受结果。

Memory、Skill、MCP、SubAgent、Scheduler 和 TUI 不属于 Kernel v1 核心；它们对当前工作树 identity 均为 implementation candidate。2026-07-20 follow-up audit 曾证明 008 的 delivery final gate 未实现、多项测试只覆盖 source shape、局部 happy path 或安全拒绝（历史），该缺口随后由 009 合同与 G0–G8 fault matrix 闭合。当前声明见 [Current Capability Status](docs/architecture/CURRENT_CAPABILITY_STATUS.md)，证据与修复合同见 [Evidence Closure Audit](docs/audits/2026-07-20-capability-evidence-closure-audit.md)、[Evidence Closure Contract](docs/architecture/CAPABILITY_EVIDENCE_CLOSURE_CONTRACT.md)、[009 Closure Plan](docs/plans/2026-07-20-009-close-capability-evidence-gaps-plan.md) 和 [009 Document Review](docs/audits/2026-07-20-009-document-review.md)。008 artifacts 保留为历史，不再作为晋级依据。

2026-07-25 曾在用户授权的真实 provider（`anthropic_compatible` / `glm-5.2` @ `open.bigmodel.cn/api/anthropic`）下完成七项 capability 的 E3 reference task（Kernel / Skill / MCP / Memory / SubAgent / Scheduler / TUI），全部 pass，bounded 证据见 `docs/acceptance/records/2026-07-25-*.md`；其中 MCP 的真实入口暴露并修复了 `main.py` 的 `--mcp-safety-state` 首次启动 `FileNotFoundError` 缺陷。同日经非实现 session 的独立 review（receipt：`docs/acceptance/2026-07-25-E3_INDEPENDENT_REVIEW.md`）七项 capability 晋级 `accepted`。这是绑定 2026-07-25 bounded v1 reference identity 的历史结论；当前工作树相对该 identity 已变更，七项能力对当前 identity 均回到 `implemented-candidate`（v1 reference task 本身即非 production-ready，不等于任意 MCP/Skill、语义 Memory、并发 SubAgent、Scheduler CRUD 或跨平台已验证）。

Graphify 和 Understand Anything 是 Coding Agent 理解本仓库时可使用的辅助工具，不是 `my-first-agent` 的运行时能力或依赖。

## 快速开始

本机已经准备的固定试用入口见 [日用指南](docs/guides/daily-use.md)；
[能力与边界清单](docs/guides/capabilities.md) 区分默认能力、可选候选能力与尚不可用入口。
当前定位是 macOS 单用户 CLI 个人试用，不是无需验收的全自动交付产品。

安装后运行 guided setup。它只询问 provider、model、base URL 和 credential 环境变量名，不读取或保存
credential value，也不会发送模型请求：

```bash
# 先清理旧构建产物：残留的 build/、egg-info 会让 pip wheel 把已删除的旧模块打进新 wheel
rm -rf build first_agent.egg-info
python -m pip wheel --no-deps --wheel-dir dist .
python -m pip install dist/first_agent-1.0.0-py3-none-any.whl
first-agent setup

# 按 setup 最后显示的变量名，在当前 shell 注入 key，例如：
export FIRST_AGENT_API_KEY='set-in-your-shell'

cd /path/to/any-empty-or-existing-directory
first-agent
```

公开 Web 是可选能力。需要时运行同一个 installed command，阅读第三方处理说明并在当前提示确认；key 仍
只放在你选择的环境变量里：

```bash
first-agent setup-web
export FIRST_AGENT_WEB_API_KEY='set-in-your-shell'
```

`setup-web` 不读取或保存 key，只保存固定 destination、credential 环境变量名、timeout、结果上限和第三方
处理告知的摘要。未运行 `setup-web` 时，普通对话、历史和 workspace 文件能力照常工作，不会自动联网。

当前本地开发与候选验证不假设 PyPI 已有发布物；可选能力（Skill 的严格 YAML 解析、MCP SDK、Textual
TUI、018 governed browser）不属于 base 安装闭包。日用默认安装就是 base（CLI/headless），不推荐
安装 `[tui]` extra——TUI 是实验性适配（见下文 TUI 章节的已知限制），需要实验时用同一个本地 wheel
的 non-editable extra 语法安装，例如
`python -m pip install "dist/first_agent-1.0.0-py3-none-any.whl[tui]"`
（各能力的 extra 名见对应章节；本仓库尚未声明任何安装 matrix 验证结论）。

setup 只保存 provider、model、base URL、credential 环境变量名、thinking mode、request path、
strict tools 开关和 timeout；不会读取或保存 key。此后 `first-agent` 默认使用当前目录，不需要再重复
Provider flags，也不会静默 fallback 到 FakeProvider。

默认启动即持久化：状态保存在 workspace 之外的 owner-only 产品目录
`~/.local/state/my-first-agent/v1`（目录 `0700`、文件 `0600`），按 workspace identity
确定性选择会话。重启后唯一安全候选自动恢复；多个候选要求显式选择，超过 16 个时用 `n` / `p`
翻页后按当前页编号选择；workspace 被替换或
存在结果未知的 effect 时准确停下，不自动调用 Provider/Tool。

普通项目中的 `config/`、`pytest.ini` 等保留名字默认仍隐藏；操作者可以只为本次启动明确开放一个
具体普通路径。敏感文件、符号链接、运行时私有状态和未列出的相邻文件不会因此开放：

```bash
first-agent --project-path config/app.yaml --project-path pytest.ini
```

切换 provider/model 但不希望加载旧的跨 workspace owner preferences 时，可使用
`--without-owner-preferences`。这不会删除或迁移旧偏好，也不会关闭另行配置的 workspace Memory。
需要为诊断或付费 dogfood 设置跨重启硬预算时，`--max-model-attempts N` 必须与同一个 owner-only
`--transport-audit-ledger PATH` 配套使用；额度在 HTTP 发出前累计占位，失败请求也不会退还。开启
HTTP SubAgent 时，隔离子进程也使用这一本 ledger 和同一上限，不会另起一份额度。额度耗尽后任务在
安全边界暂停并明确说明 `/resume` 已无法再发送模型请求；以同一 ledger 与更高的
`--max-model-attempts` 重启即可继续原任务（历史消耗与授权边界保留）。

每个 workspace 最多保留 256 个 active-history 会话。到达上限时新会话会被拒绝，既有会话仍可
恢复和选择；产品不会自动删除历史。`--status` 会显示可复制的完整 conversation ID。只允许把已经
`VERIFIED_DONE` 或 `CANCELLED`、且没有未决运行/授权/进程/浏览器资源的会话显式归档：

```bash
first-agent --workspace "$PWD" --status
first-agent --workspace "$PWD" archive CONVERSATION_ID
first-agent --workspace "$PWD" archive CONVERSATION_ID --yes
```

第一次 `archive` 只显示 exact revision 预览，不做修改；加 `--yes` 后才把完整 checkpoint 写入并
重读不可变 owner-only archive，成功后释放 active-history 容量。成功输出包含 exact digest 和恢复
命令；`restore` 同样先预览、再显式确认，且不会删除归档：

```bash
first-agent --workspace "$PWD" restore CONVERSATION_ID SOURCE_CHECKPOINT_DIGEST
first-agent --workspace "$PWD" restore CONVERSATION_ID SOURCE_CHECKPOINT_DIGEST --yes
```

会话在预览后变化、正在使用、归档损坏、workspace identity 不匹配、active history 已满或同 ID
已经存在时都会 fail closed，不覆盖其它会话。

开发或测试时仍可显式选择 FakeProvider；它不会成为保存的日常 profile：

```bash
first-agent \
  --workspace "$PWD" \
  --state-root "$HOME/first-agent-dev-state" \
  --provider fake
```

需要隔离真实配置时，在 setup 和日常启动两边使用同一个显式 `--state-root`；它必须位于 workspace
之外。不要用 `/tmp/...`：macOS 上 `/tmp` 是指向 `/private/tmp` 的符号链接，state-root 的
symlink 合同会 fail-closed 拒绝启动。

旧的 `--state` / `--resume` 手动 checkpoint 工作流已按 012 合同移除；旧 v1 state 文件
不再被加载（strict schema v2 fail closed，不做静默迁移）。

日常安全决定直接在当前提示下回答：Provider disclosure 和文件审批用 `yes/no`（也支持
`y/n/是/否/允许/不允许`）；unknown outcome 必须明确回答 `success`、`failed` 或 `stop`。用户无需复制
digest/request ID。以下 slash command 只保留为高级精确接口：

- `/ack-provider DIGEST`
- `/approve ID`、`/reject ID`
- `/approve-goal-target [ID]`（仅对当前 Goal/revision、当前 workspace、同一文件工具与同一精确
  Goal target 复用；最多 16 次实际执行、60 分钟后到期，任务修订/终态也立即失效；普通
  `yes`、`a`、`/approve` 仍是逐笔批准。文件审批提示在适用范围内直接展示无参数
  `/approve-goal-target`，绑定刚显示的待审批请求；范围不适用时拒绝执行，不静默降级）
- `/approve-goal-directory [ID]`（仅在 Goal 已明确列出父目录时，授权同一文件工具访问该目录下
  的普通项目文件；不会从当前文件自动猜父目录，敏感路径仍拒绝；无参数形式同样绑定刚显示的
  待审批请求；TUI 使用 `Shift+D`）
- `/revoke-goal-target`（撤销当前任务的全部文件授权；TUI 可用 `Shift+A` 授予精确文件）
- `/resolve-success ID`、`/resolve-failed ID`
- `/pause`、`/resume`、`/cancel`、`/exit`
- `/new`（显式开始新任务：旧 Goal 与 checkpoint 原样保留，同一进程内进入新 conversation；
  有 active run 或 pending 决策时拒绝并说明原因；Goal 活跃时先 `/pause` 暂存（park）即可离开，
  终态、已暂停或无 Goal 允许——CLI 与 TUI 共用同一合法性判断）
- `/switch`（切到本 workspace 另一个已保存的 conversation：当前 conversation 原样保留、
  之后仍可再次选中；同一进程内重开会话选择器（含分页），不执行任何 action、不转移
  pending 决策与授权；有 active run 或 pending 决策时拒绝。没有任何非终态候选时新建
  conversation 并说明。已暂停的任务用 `/resume` 回来继续）
- `/sources`、`/sources --advanced`（只读查看当前来源；advanced 才显示 opaque source ref）

普通文本永远走同一个入口：简单问题直接回答；只有会改变 outcome、target、scope、authority、
重大成本或不可逆后果的缺失信息才澄清；明确任务先持久化 Goal，再允许 effectful tool。
用户不需要输入“继续”推动模型内部 progression。自然语言 correction 仍作为普通文本进入同一
Runtime；它会使旧 next step、completion claim 和 evidence binding 失效，再停在准确权限边界。

`RunStatus.COMPLETED` 只表示本次调用安全停止，不表示任务完成。只有状态投影明确显示
`VERIFIED_DONE`，且每个 mandatory criterion 都有 Runtime 从 durable raw facts 重新推导的
evidence，才表示登记的证据项已通过，不表示业务语义已获独立验收或用户已接受结果。
完成摘要会同时提示 `User acceptance: not established by these evidence checks.`；
模型说“done”不会改变 Goal 状态。

`/exit`、EOF 和空闲时的 Ctrl-C 只退出当前 CLI，不会伪造一次运行取消。运行中的第一次
Ctrl-C 走协作取消：请求进入与 TUI 相同的控制通道，当前 provider/tool 步骤返回并到达安全
边界后写入取消终态，会话存活（可用 `/status` 查看权威状态）；再次按 Ctrl-C 只在取消请求
已投递（或已确认不可用）后才生效——落回退出码 130 的强制中断，保存的 state 仍在，提示会
说明可能已发生的远端效果。无活跃任务运行接受控制（goal-less 问答）时，确认不可用的提示
出现后同样以再次按 Ctrl-C 强制中断。

## 有依据的 workspace 知识

First Agent 会按当前问题需要调用 `history_search` / `history_get`、`search_paths` / `search_text` /
`read_file_chunk`，而不是把全部历史或整个目录自动塞进 prompt。历史范围只限当前路径 scope 与 exact
filesystem identity 都匹配的 First Agent canonical checkpoint；legacy unbound、其他 workspace、Claude/Codex
会话、Graphify/UA 产物和用户在 First Agent 之外的活动都不属于可召回历史。

Web 只连接 `https://api.tavily.com`。Search 和 Extract 分别展示 exact query 或已由 Search receipt 授权的
公开 URL batch，得到用户批准后才发送；产品不会直连目标网页、继承 ambient proxy/cookie/netrc，也不会登录
或操作浏览器。公开 query 和 URL 会由 Tavily 按其条款处理；First Agent 不承诺第三方 zero retention、
training exclusion 或 deletion。

复杂研究可以把 history、workspace 与 extracted Web receipts 绑定到本地产物和
`CitationManifestV1` sidecar。只有产物与 sidecar 都经过写入批准、read-back，且 Runtime 从 durable raw facts
重新验证 source linkage 后，Goal 才可能显示 `VERIFIED_DONE`。默认 Sources 视图显示可读 locator、title、
时间、完整/截断/失败状态；`/sources --advanced` 只用于诊断。

## 历史里程碑（012–019）

以下里程碑均已按 fail-closed 机制完成过验收，历史 PASS 只绑定当时 delivery identity；当前工作树相对
各旧 identity 均已 drift，全部能力对当前 identity 为 `implemented-candidate`。权威状态矩阵与完整边界见
[Current Capability Status](docs/architecture/CURRENT_CAPABILITY_STATUS.md)；本节只保留一句话能力与
关键边界。

- **012 Trusted Continuity**：离线 reference suite 覆盖 answer/clarify、task→approval→restart→
  read-back→`VERIFIED_DONE`、unknown effect、Goal controls 与 owner preference oracle；真实 Provider E3
  需四个 `FIRST_AGENT_E3_*` 变量运行 `scripts/run_012_e3.py`，Mock/Fake 不能冒充。协议见
  [`012_TRUSTED_CONTINUITY_E3.md`](docs/acceptance/012_TRUSTED_CONTINUITY_E3.md)。
- **014 Grounded Personal Knowledge**：曾完成离线 gates、真实 Model + Tavily 三连 E3、mandatory
  held-out value journey 与 fresh review；证据 `docs/implementation/014_EXECUTION_LOG.md` §9.3。
- **015 Governed Local Action（`local_process`）**：exact executable/argv/cwd/资源与环境展示后，批准
  产生 Goal-scoped、限次、会过期、可撤销的租约。这不是 shell：不接受命令字符串、pipeline、
  redirection、TTY 或后台任务；合同为 POSIX/macOS-first
  （`docs/plans/2026-08-09-001-feat-governed-local-action-plan.md`）。证据
  `docs/implementation/015_EXECUTION_LOG.md`。
- **017 macOS Seatbelt sandbox（`sandbox_exec`）**：`workspace-write` 只写 workspace 与本次临时目录，
  `read-only` 不写，默认 `network=off`；一次性精确批准；backend 不可用时 confined mode 零执行、不回退
  `local_process`。状态由
  [`017_SANDBOXED_WORKSPACE_EXECUTION_INDEPENDENT_REVIEW.md`](docs/acceptance/017_SANDBOXED_WORKSPACE_EXECUTION_INDEPENDENT_REVIEW.md)
  决定。

## HTTP Provider

凭据由组合根从 profile 指定的环境变量读取，不读取 `.env`，也不会进入 profile、checkpoint、事件或模型上下文。日常推荐使用上面的 setup；完整显式参数仍可用于临时覆盖：

```bash
export FIRST_AGENT_API_KEY='...'
first-agent \
  --provider openai_compatible \
  --model your-model \
  --base-url https://provider.example
```

DeepSeek 现有两条精确支持的配置。需要 strict Tool Calls 时使用 beta 入口与显式非思考模式：
strict 模式在合同上保证工具参数与 schema 一致（普通模式没有这一承诺）。官方文档：
[Tool Calls](https://api-docs.deepseek.com/zh-cn/guides/tool_calls/)、
[Create Chat Completion](https://api-docs.deepseek.com/zh-cn/api/create-chat-completion/)。

```bash
export FIRST_AGENT_API_KEY='set-in-your-shell'
first-agent setup \
  --provider openai_compatible \
  --model deepseek-flash \
  --base-url https://api.deepseek.com/beta \
  --request-path /chat/completions \
  --strict-tools \
  --thinking-mode disabled

cd /path/to/any-directory
first-agent
```

`--request-path` 与 `--strict-tools` 都是显式 opt-in；产品不会按 base URL 或 model 名猜测 strict
模式。013 的真实验收即在此配置下连续三次通过（见
[`docs/acceptance/013_EVERYDAY_WORKSPACE_AGENT_E3.md`](docs/acceptance/013_EVERYDAY_WORKSPACE_AGENT_E3.md)）。

需要 DeepSeek Flash 的思考与流式回答时，使用官方普通入口；开启后推理强度固定为
`max`，不允许同时开启 strict，也不猜测其他模型或兼容 endpoint：

```bash
export FIRST_AGENT_API_KEY='set-in-your-shell'
first-agent setup \
  --provider openai_compatible \
  --model deepseek-flash \
  --base-url https://api.deepseek.com \
  --thinking-mode enabled

first-agent
```

该路径只展示公开回答文本增量。`reasoning_content` 作为与 provider identity 绑定的
opaque continuation 进入 checkpoint/replay，不进入 UI、Memory 或 compaction summary；缺失或身份不匹配时
在 HTTP 前拒绝。流式必须完整收到 finish 与 `[DONE]` 才能推进 Runtime；断流不拼凑响应，
也不自动重发已经开始计费的请求。用户取消会在下一个 SSE 读取边界协作停止，
并由唯一 Runtime 落盘最终状态。官方 endpoint 与 Flash model identity 精确匹配时，provider
capacity 档案把当前公开规格投影为 1M context window、384K 单次 output 上限，并同步扩大有界 SSE
传输预算；未知兼容 endpoint 仍使用保守默认，显式调用者限额优先。2026-09-14 使用真实
DeepSeek Flash 完成 D01 CSV 修复：13 次已记录 model attempt，产品自主写入、读回并运行测试，
外部业务 grader PASS；这只证明该场景，不代表全部任务成功率。

`--strict-tools` 有一个组合限制：当本次请求的工具 schema 含开放 object（object 缺失 `properties`，或
`additionalProperties` 未显式为 `false`）时，OpenAI-compatible strict 投影会在发送请求前以
`unsupported_strict_open_object` fail closed；不会静默关闭 strict，也不会改写生产 schema。已知含开放
object 的工具 schema 包括 declared Skill entrypoint 的 `arguments`、`browser_act` 的 `fields`，以及取决于
server descriptor 的 MCP 工具。触发与模型是否实际调用该工具无关：只要相应工具出现在本次请求的工具
列表中，请求发送前即失败。

也可使用 `anthropic_compatible`。两个 adapter 都是有限时的一次请求路径（anthropic 侧为 SSE 流式）；
具体 endpoint 可由兼容服务的 base URL 决定。第一次外发以及 destination/model/data-class 变化时，Runtime
会先显示 destination、model 和 data classes；用户在当前提示下确认后才发送，内部 acknowledgement 仍精确
绑定 digest。ack receipt 持久化在 checkpoint，配置或实际数据类别漂移会自动失效。

## Skills

Skill v1 是 operator-trusted 的只读 governed 工具，不是 system prompt hook。每个 Skill 是显式 trust root 下的一级目录，目录名必须等于 `SKILL.md` frontmatter 里的 `name`：

```bash
python -m pip install "dist/first_agent-1.0.0-py3-none-any.whl[skill]"   # 先按快速开始构建本地 wheel；提供严格 YAML 解析
mkdir -p /tmp/skills/code-review
cat > /tmp/skills/code-review/SKILL.md <<'EOF'
---
name: code-review
description: Review a diff before approving it.
---
Check correctness, tests, and risks; summarize before approving.
EOF

first-agent --provider fake --skill-root /tmp/skills
```

模型按需调用 `skill__code-review` 激活完整 body，或用共享的 `skill__read_resource` 读取该 Skill 的 `references/`、`assets/`。任意 `scripts/`、远程安装/registry、自动激活、`allowed-tools` 扩权和 prompt hook 仍不支持：唯一可执行路径是 manifest 声明的 owner-local Python entrypoint（`skill__<name>__<entrypoint>`），在固定 directory/file identity 与 digest、exact approval、既有 native sandbox、network off 下运行，证据等级为 implemented-candidate，不是 accepted/production-ready；scan 后内容漂移会让旧 activation 失效（要求重启重建 catalog）。未配置 `--skill-root` 时 Kernel 行为与基线完全一致，且 base 安装不依赖 PyYAML。

## MCP tools

MCP v1 把 operator-approved 的固定 stdio tool descriptor 映射为具体的 `mcp__<server>__<tool>` governed tool（HIGH + EXTERNAL，每次都需审批）。catalog 是显式 JSON，不含 credential value；transport 由本项目持有 process group 与 commit receipt，并通过 SDK public `ClientSession` 驱动一次有限时 session：`spawn → initialize → tools/list → descriptor verify → tools/call → close`。call 后无法确认结果的失败进入人类 unknown-outcome recovery，绝不自动重试。

```bash
python -m pip install "dist/first_agent-1.0.0-py3-none-any.whl[mcp]"
first-agent --provider fake \
  --mcp-catalog /tmp/mcp-catalog.json \
  --mcp-safety-state /tmp/mcp-safety/latch.json
```

`--mcp-catalog` 与 `--mcp-safety-state` 必须一起使用。durable safety latch 记录每次调用的 arm/clear；若上次调用留下未清除 marker（例如宿主 crash），下一次 startup fail closed，只能由 operator offline recovery 解除。未配置 MCP 时 Kernel 行为与基线一致，base 安装不引入 MCP SDK。

## Memory

Memory v1 在 conversation 之间保留 operator 显式批准的信息，并让 ContextManager 在当前预算内决定是否召回。store 是显式路径、owner-only、revision CAS 的本地明文 JSON；首次使用互斥二选一：

```bash
first-agent --provider fake --memory-create /tmp/first-agent-memory/store.json
# 之后会话：
first-agent --provider fake --memory-store /tmp/first-agent-memory/store.json
```

store header 绑定 canonical workspace scope 与非秘密 provider trust profile（`--memory-profile`，默认 `default`）；scope/profile 不匹配时 startup fail closed。模型用 `memory_search`/`memory_get`（只读）与 `memory_remember`/`memory_update`/`memory_forget`（每次审批）修改；召回内容作为 untrusted context 块进入模型上下文，永不提升为 system 权威，也不会挤掉 system/current/pending core。conversation checkpoint 不保存 Memory 快照。未配置 Memory 时 Kernel 行为与基线一致。

owner preference 与 workspace Memory 分权：它使用默认 state root 下固定的
`owner-preferences.json`，只有当前 durable user fact 的 exact 文本才能经 governed tool + approval
确认或纠正；project/web/tool/model 内容不能晋升为跨 workspace preference。forget 只停止未来本机
active recall，并保留 tombstone/provenance；不声称擦除历史或已发送给 remote Provider 的副本。

## SubAgent delegation

`--subagent` 开启 `subagent__delegate`（HIGH + EXTERNAL，每次审批）。它把一个 bounded 只读 objective 交给 isolated child：child 复用同一个 `AgentRuntime.run_turn`，拥有独立 in-memory state、无 ContextSource，并只注册 workspace-scoped 的 `read_file`、`list_files`、`search_paths`、`search_text`、`read_file_chunk`。单次调查最多 6 次 model call、8 次只读 tool call；不继承 parent history/Memory/Skill/MCP，也没有写入、shell、网络或再次派生能力。checkpoint/state 文件仍受保护。

child 返回的 workspace 来源由 runner 按当前文件 snapshot/content digest 再核对，过期或截断来源不会进入结果；可核对项以 path/line/digest appendix 返回，并明确只是 advisory，不能授予父侧写权限或替父侧宣布完成。HTTP child 会与 parent 共享显式配置的累计 model-attempt ledger；额度耗尽时在发送前终止。当前 Goal/invocation 的 pause、correct 或 cancel 请求会传到 process-isolated runner：尚未启动时按 known-not-executed 返回，已经启动时回收整个 child process group，并诚实进入 unknown-outcome recovery，因为远端请求可能已经发生。只有 child 返回 `COMPLETED` 才是成功；其他明确终态成为已知失败，runner/provider 无法分类的异常进入 parent unknown-outcome recovery。Everyday 的 durable run 总墙钟上限为 2 小时，恢复或重启不重置；它在新模型/工具 effect 前生效。单次 provider/process 仍由各自 timeout/cancel 合同约束。

## Scheduler（external caller）

`first-agent-schedule` 是 019 的 typed management/reconcile surface，不含内置时钟，也不
从 CLI 参数发现 workspace、state root、task text、provider 或 credential。控制平面将定义、
UTC due-time、CAS lifecycle 和 one-shot reconciliation 保持为 portable core；合格的本机 host
composition 才能在固定 owner root 上构造它并提供可选 cold wake。

普通任务采用 manual reconcile 时：definition 中的 `wake_adapter_policy_digest` 为 `null`，
不会创建 macOS“登录项与扩展”。只有明确需要退出交互程序后仍由系统启动检查时，才先执行
`first-agent-schedule wake enable`，再批准绑定该 policy digest 的 cold-wake definition；批准任务
本身不会顺带安装系统后台项。普通 `scripts/run_019_macos_e3.py --preflight` 也是只读检查；
只有显式 `--probe-launchd` 或完整 `--run` 才会注册并清理临时 LaunchAgent。

```bash
first-agent-schedule reconcile --delivery-id delivery:one
```

未配置受信任 host profile 时，该入口 fail closed 为 `needs_019_config`，而不是接受任意路径
或凭据来拼装 Runtime。具备 host composition 时，命令只接收 closed typed actions：`create`、
`preview`、`approve`、`list`、`show`、`open`、`update`、`pause`、`resume`、`cancel`、`purge`、
`wake enable/disable` 与 `reconcile`。重复 reconciliation 重放 authoritative result，不会重复
provider/effect；approval、recovery 和 host qualification 始终交还人类。

当前 wheel 中的 `first-agent-schedule` 只装配 portable typed dispatcher，并未装配可运行的
host composition；因此直接执行 `list`、`create` 或 `reconcile` 都会返回
`needs_019_config`/`host_profile_unavailable`（exit 2），不是一个空的可用 Scheduler。
开发用注入测试证明的是控制接口，不代表安装入口可调度。该命令不会自行创建登录项或后台任务。

## TUI（optional Textual adapter，实验性）

`--tui` 启动可选的 Textual 界面（与 CLI/headless 共享同一 typed action、reducer、checkpoint 与 recovery 语义）。它通过 single-flight thread worker 调用同一个 Runtime；`RunResult`/checkpoint 始终权威，events 只作 advisory 显示。慢模型调用会显示真实等待时长；运行中按 `Ctrl-C` 会立即确认取消请求，但只有当前 provider/tool 返回并到达安全边界后才写入取消终态，界面不会把“请求已收到”假报成“已经停止”。

TUI 当前是实验性适配，不与 CLI 宣称功能对等（parity）。`/pause` 后经 `/resume` 恢复的
pending provider 外发确认（active run 已停、Goal 已 ready 的形状）TUI 会与 CLI 同判定地
重新显示该决定（2026-10-25 前的版本不重显，属旧已知限制）；pending 外发确认的
y/n/空回车语义（含安全拒绝退出）仍以 CLI 为准（2026-10-18 B 包），日用首选 CLI。

```bash
python -m pip install "dist/first_agent-1.0.0-py3-none-any.whl[tui]"
first-agent --provider fake --tui
```

未安装 Textual 时 `--tui` 给出明确安装提示，base 安装、普通 CLI 与 headless 都不依赖 Textual。所有外部可控文本统一 literal 渲染（`markup=False`，ANSI/C0/C1/bidi 显示为可见 escape）。

## 开发验证

```bash
.venv/bin/ruff check .
.venv/bin/python -m pytest -q -rx
git diff --check
```

架构与状态语义见 [Kernel Architecture](docs/architecture/KERNEL_ARCHITECTURE.md)。此次重建是 breaking change：旧 CLI、旧状态格式和旧 Python 接口均不兼容，也不会被自动发现或迁移；未跟踪的旧运行数据保持原样。
## Browser（018，可选治理 Chromium）

可选的受治理专属隔离 Chromium 能力：public-read 会话、site-bound 交互 profile，以及绑定本任务
受管开发进程的 exact `127.0.0.1` 页面验收；包含 exact approval、显式 user takeover、egress guard
与 download quarantine。本地模式只接受 `managed_web_start` 返回的 opaque resource，不接受 `localhost`、
其他端口、LAN 或既有本机服务；父进程退出或生命周期到界时监督器回收该进程组，完成前必须有
`browser_close` 与 `managed_web_stop` 的确认 receipt。默认关闭；在快速开始构建的本地 wheel 上安装
`browser` extra 后用 `--browser` 启用。历史 PASS 只绑定当时 identity，当前为
`implemented-candidate`，状态由
[`018_GOVERNED_BROWSER_TASKS_INDEPENDENT_REVIEW.md`](docs/acceptance/018_GOVERNED_BROWSER_TASKS_INDEPENDENT_REVIEW.md)
决定。该本地旅程目前只有离线/本机合成测试证据，尚未完成 D06 真实模型验收；它不是个人浏览器、
桌面控制、任意网站兼容、后台自治或 production-ready 第三方集成。

## Durable automations（019，split delivery）

调度控制面保持 portable：definition、canonical UTC scheduling、CAS lifecycle、bounded authority、
recovery/purge 只依赖 typed ports，不选择 launchd/systemd/Cron/POSIX-Windows API/Seatbelt/Playwright。
macOS host profile（真实 persistence、launchd wake、hard-deadline cleanup、sandbox composition）是独立
qualification；Linux/Windows/cloud 保持 `not_qualified`，不从 macOS 证据外推。当前均为
`implemented-candidate`，核心状态由
[`019_CORE_INDEPENDENT_REVIEW.md`](docs/acceptance/019_CORE_INDEPENDENT_REVIEW.md) 决定。
