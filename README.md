# my-first-agent

一个从当前目录开始工作的 local-first 日常 Agent。

它使用同一个自然语言入口回答问题、讨论想法或完成有界的当前目录文件任务。底层仍刻意保持为一个模型循环、一个上下文管理器、一个受治理的工具执行路径和一个可恢复状态机；当前不宣称拥有 shell、网页、浏览器或整机控制能力。

## 当前能力

- 多轮文本对话
- 确定性、限额明确的上下文构建
- 串行工具调用与精确审批
- `read_file`、`list_files`、`write_file`、`edit_file`
- 本地 v1 checkpoint、暂停、恢复与未知工具结果处置
- FakeProvider，以及 Anthropic-compatible / OpenAI-compatible 非流式 HTTP adapter
- 同一套 typed action / event / result 合同下的 CLI 与 headless 调用
- 同一自然语言入口中的直接回答、最小澄清与 durable Goal
- Goal pause/resume/cancel/correction、确定性重启与 unknown-effect recovery
- remote Provider 外发前的精确 disclosure acknowledgement
- Runtime-owned evidence gate：只有满足 admitted criteria 才显示 `VERIFIED_DONE`
- 有来源、可纠正、可停止未来召回的 owner preference

Memory、Skill、MCP、SubAgent、Scheduler 和 TUI 不属于 Kernel v1 核心；当前工作树已有六项 implementation candidate，但 2026-07-20 follow-up audit 证明 008 的 delivery final gate 未实现，并发现多项测试只覆盖 source shape、局部 happy path 或安全拒绝，不能宣称全部重接完成。当前声明见 [Current Capability Status](docs/architecture/CURRENT_CAPABILITY_STATUS.md)，证据与修复合同见 [Evidence Closure Audit](docs/audits/2026-07-20-capability-evidence-closure-audit.md)、[Evidence Closure Contract](docs/architecture/CAPABILITY_EVIDENCE_CLOSURE_CONTRACT.md)、[009 Closure Plan](docs/plans/2026-07-20-009-close-capability-evidence-gaps-plan.md) 和 [009 Document Review](docs/audits/2026-07-20-009-document-review.md)。008 artifacts 保留为历史，不再作为晋级依据。

2026-07-25 已在用户授权的真实 provider（`anthropic_compatible` / `glm-5.2` @ `open.bigmodel.cn/api/anthropic`）下完成七项 capability 的 E3 reference task（Kernel / Skill / MCP / Memory / SubAgent / Scheduler / TUI），全部 pass，bounded 证据见 `docs/acceptance/records/2026-07-25-*.md`；其中 MCP 的真实入口暴露并修复了 `main.py` 的 `--mcp-safety-state` 首次启动 `FileNotFoundError` 缺陷。2026-07-25 经非实现 session 的独立 review（receipt：`docs/acceptance/2026-07-25-E3_INDEPENDENT_REVIEW.md`）通过，七项 capability 已晋级 `accepted`（v1 reference task；非 production-ready，不等于任意 MCP/Skill、语义 Memory、并发 SubAgent、Scheduler CRUD 或跨平台已验证）。

Graphify 和 Understand Anything 是 Coding Agent 理解本仓库时可使用的辅助工具，不是 `my-first-agent` 的运行时能力或依赖。

## 快速开始

先把凭据放进你选择的环境变量，再一次性保存不含秘密的 Provider profile：

```bash
python -m pip install -e .
export FIRST_AGENT_API_KEY='set-in-your-shell'
first-agent setup \
  --provider openai_compatible \
  --model your-model \
  --base-url https://provider.example

cd /path/to/any-empty-or-existing-directory
first-agent
```

setup 只保存 provider、model、base URL、credential 环境变量名、thinking mode、request path、
strict tools 开关和 timeout；不会读取或保存 key。此后 `first-agent` 默认使用当前目录，不需要再重复
Provider flags，也不会静默 fallback 到 FakeProvider。

默认启动即持久化：状态保存在 workspace 之外的 owner-only 产品目录
`~/.local/state/my-first-agent/v1`（目录 `0700`、文件 `0600`），按 workspace identity
确定性选择会话。重启后唯一安全候选自动恢复；多个候选要求显式选择，workspace 被替换或
存在结果未知的 effect 时准确停下，不自动调用 Provider/Tool。

开发或测试时仍可显式选择 FakeProvider；它不会成为保存的日常 profile：

```bash
first-agent \
  --workspace "$PWD" \
  --state-root /tmp/first-agent-state \
  --provider fake
```

需要隔离真实配置时，在 setup 和日常启动两边使用同一个显式 `--state-root`；它必须位于 workspace
之外。

旧的 `--state` / `--resume` 手动 checkpoint 工作流已按 012 合同移除；旧 v1 state 文件
不再被加载（strict schema v2 fail closed，不做静默迁移）。

日常安全决定直接在当前提示下回答：Provider disclosure 和文件审批用 `yes/no`（也支持
`y/n/是/否/允许/不允许`）；unknown outcome 必须明确回答 `success`、`failed` 或 `stop`。用户无需复制
digest/request ID。以下 slash command 只保留为高级精确接口：

- `/ack-provider DIGEST`
- `/approve ID`、`/reject ID`
- `/resolve-success ID`、`/resolve-failed ID`
- `/pause`、`/resume`、`/cancel`、`/exit`

普通文本永远走同一个入口：简单问题直接回答；只有会改变 outcome、target、scope、authority、
重大成本或不可逆后果的缺失信息才澄清；明确任务先持久化 Goal，再允许 effectful tool。
用户不需要输入“继续”推动模型内部 progression。自然语言 correction 仍作为普通文本进入同一
Runtime；它会使旧 next step、completion claim 和 evidence binding 失效，再停在准确权限边界。

`RunStatus.COMPLETED` 只表示本次调用安全停止，不表示任务完成。只有状态投影明确显示
`VERIFIED_DONE`，且每个 mandatory criterion 都有 Runtime 从 durable raw facts 重新推导的
evidence，才表示 Goal 已验收。模型说“done”不会改变 Goal 状态。

`/exit`、EOF 和空闲时的 Ctrl-C 只退出当前 CLI，不会伪造一次运行取消。

## HTTP Provider

凭据由组合根从 profile 指定的环境变量读取，不读取 `.env`，也不会进入 profile、checkpoint、事件或模型上下文。日常推荐使用上面的 setup；完整显式参数仍可用于临时覆盖：

```bash
export FIRST_AGENT_API_KEY='...'
first-agent \
  --provider openai_compatible \
  --model your-model \
  --base-url https://provider.example
```

DeepSeek 官方 OpenAI-compatible 入口推荐使用 strict Tool Calls（beta）配置：strict 模式在合同上
保证工具参数与 schema 一致（普通模式没有这一承诺），同时用显式非思考模式避免把
provider-specific opaque `reasoning_content` 引入 checkpoint/replay 合同（官方文档：
[Tool Calls](https://api-docs.deepseek.com/zh-cn/guides/tool_calls/)、
[Create Chat Completion](https://api-docs.deepseek.com/api/create-chat-completion/)）：

```bash
export FIRST_AGENT_API_KEY='set-in-your-shell'
first-agent setup \
  --provider openai_compatible \
  --model deepseek-v4-flash \
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

也可使用 `anthropic_compatible`。两个 adapter 都是有限时、非流式的一次请求路径；具体 endpoint
可由兼容服务的 base URL 决定。第一次外发以及 destination/model/data-class 变化时，Runtime 会先
显示 destination、model 和 data classes；用户在当前提示下确认后才发送，内部 acknowledgement 仍精确
绑定 digest。ack receipt 持久化在 checkpoint，配置或实际数据类别漂移会自动失效。

## Skills

Skill v1 是 operator-trusted 的只读 governed 工具，不是 system prompt hook。每个 Skill 是显式 trust root 下的一级目录，目录名必须等于 `SKILL.md` frontmatter 里的 `name`：

```bash
python -m pip install -e ".[skill]"   # 提供严格 YAML 解析
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

模型按需调用 `skill__code-review` 激活完整 body，或用共享的 `skill__read_resource` 读取该 Skill 的 `references/`、`assets/`。`scripts/`、远程 registry、自动激活、`allowed-tools` 授权、prompt hook 和默认目录扫描都不在 v1 中；scan 后内容漂移会让旧 activation 失效（要求重启重建 catalog）。未配置 `--skill-root` 时 Kernel 行为与基线完全一致，且 base 安装不依赖 PyYAML。

## MCP tools

MCP v1 把 operator-approved 的固定 stdio tool descriptor 映射为具体的 `mcp__<server>__<tool>` governed tool（HIGH + EXTERNAL，每次都需审批）。catalog 是显式 JSON，不含 credential value；transport 由本项目持有 process group 与 commit receipt，并通过 SDK public `ClientSession` 驱动一次有限时 session：`spawn → initialize → tools/list → descriptor verify → tools/call → close`。call 后无法确认结果的失败进入人类 unknown-outcome recovery，绝不自动重试。

```bash
python -m pip install -e ".[mcp]"
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

## 012 验收状态

离线 reference suite 覆盖 answer/clarify、task→approval→restart→read-back→`VERIFIED_DONE`、
unknown effect、multiple-candidate selection、Goal controls、真实 HTTP adapter 的 disclosure send-count、
owner preference poisoning/correct/forget 和 false-completion mutation oracle。真实 Provider E3 必须另行用
四个显式 `FIRST_AGENT_E3_*` 环境变量运行 `scripts/run_012_e3.py`；Mock/Fake 结果不能冒充 E3，
也不能据此宣称 production-ready。操作步骤见
[`docs/acceptance/012_TRUSTED_CONTINUITY_E3.md`](docs/acceptance/012_TRUSTED_CONTINUITY_E3.md)。

## SubAgent delegation

`--subagent` 开启 `subagent__delegate`（HIGH + EXTERNAL，每次审批）。它把一个 bounded 只读 objective 交给一个 isolated child：child 复用同一个 `AgentRuntime.run_turn` 实现，但拥有独立 in-memory state、空 ToolRuntime、无 ContextSource、最多一次 model call，且不继承 parent history/Memory/Skill/MCP/workspace/credential。只有 child 返回 `COMPLETED` 才是成功；其他明确终态成为已知失败，runner/provider 无法分类的异常进入 parent unknown-outcome recovery。

## Scheduler（external caller）

`first-agent-schedule` 是无内置时钟的 occurrence adapter，供 cron/launchd/CI 调用。每次 occurrence 映射为独立 conversation/checkpoint，提交一次确定性 `SubmitMessage`，并输出 machine-readable JSON report：

```bash
first-agent-schedule \
  --workspace "$PWD" \
  --state-root /tmp/first-agent-schedule \
  --schedule-id nightly-build \
  --occurrence-id '2026-07-19T00:00:00Z' \
  --scheduled-for '2026-07-19T00:00:00Z' \
  --message 'run the benign nightly check' \
  --provider fake
```

exit class 只有 `completed`(0) / `needs_human`(1) / `fatal_conflict`(2)。duplicate fire 走 action replay（provider/effect 不重复）；approval/recovery/limit/retryable 一律报告 `needs_human`，交还人类。`--state-root` 必须在 workspace 之外。

## TUI（optional Textual adapter）

`--tui` 启动可选的 Textual 界面（与 CLI/headless 共享同一 typed action、reducer、checkpoint 与 recovery 语义）。它通过 single-flight thread worker 调用同一个 Runtime；`RunResult`/checkpoint 始终权威，events 只作 advisory 显示，不提供伪造的 in-flight 取消。

```bash
python -m pip install -e ".[tui]"
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
