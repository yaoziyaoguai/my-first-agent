---
title: 013 Everyday Workspace Agent - Implementation Plan
type: plan
date: 2026-08-03
authority: 013-plan
status: completed-and-verified
---

# 013 Everyday Workspace Agent — 实施计划

## 1. 权威与成功标准

产品合同以 `docs/architecture/013_EVERYDAY_WORKSPACE_AGENT_DESIGN.md` 为准。本计划只定义实现顺序、
Red/Green 证据和停止条件；不得用修改本计划来降低验收标准。

013 成功不是“又增加了一批模块”，而是用户一次 setup 后能在任意空/已有目录直接运行 `first-agent`，
用自然语言完成 ask、discussion 和 bounded file task 三条旅程，同时保持 012 全部安全不变量。

每个单元遵循：准确 Red → 最小 Green → touched regression → 更新
`docs/implementation/013_EXECUTION_LOG.md`。一个单元 Green 不是 loop 停止点。

## 2. 禁止项

- 不创建 CodingLoop、supervisor、daemon、background worker 或第二个 `AgentRuntime` 产品路径。
- 不增加 shell/web/browser/multi-root/dynamic registry/self-improvement。
- 不把 Provider profile 变成 checkpoint、Memory、catalog 或 credential store。
- 不从 `.env`、Claude/Codex settings、shell history、workspace 文件推断配置。
- 不通过硬编码自然语言关键词在 CLI 判断 chat/task；普通文本始终是 `SubmitMessage`。
- 不删除或纳入用户未跟踪的 `tui/` runtime 内容。
- 未经用户再次授权，不 commit/push/tag/改 remote。

## 3. U0 — Freeze baseline

### Red / evidence

1. 记录 `git status --short --branch`、HEAD、Python/Ruff 版本和现有未跟踪路径类别，不读取其内容。
2. 运行未截断 baseline：
   - `git diff --check`
   - `.venv/bin/ruff check .`
   - `.venv/bin/python -m pytest -q -rx`
3. 架构搜索：production `.generate(` 仍只有 `agent/runtime/loop.py`；不存在第二 loop/classifier。

### Exit

基线失败先区分 pre-existing 与本轮问题。不得 reset/restore/clean 用户工作树。

## 4. U1 — Non-secret provider profile

### Red

新增 profile 合同测试，覆盖：

- strict round-trip 与 unknown/missing/type-invalid 字段拒绝；
- credential value 无字段、序列化产物无传入 secret；
- `0700/0600`、owner、regular/no-follow/single-link；
- symlink file/parent、unsafe mode、wrong owner（可模拟）fail closed；
- concurrent/partial write 不产生可加载半文件；
- base URL/model/env name normalization 与控制字符拒绝；
- setup 零 provider/network call，FakeProvider 不可持久化。

### Green

在 provider 或 continuity 边界新增一个小型 profile 模块。只实现 `ProviderProfileV1`、strict load、atomic
save 和 profile-to-`AgentProviderConfig` 投影；不引入通用 config framework。

### Exit

focused tests、provider tests、Ruff、diff check Green；execution log 记录 profile 文件的秘密字段负证明。

## 5. U2 — Setup and no-argument composition

### Red

入口测试必须证明：

- `first-agent setup` 写入指定 state root 的 profile，不创建 conversation，不调用 Provider；
- 无参数 + profile 使用 cwd、真实 provider metadata 和默认 durable session；
- 无 profile 在 checkpoint/provider/tool I/O 前退出并给准确 setup 指引；
- explicit complete provider group 覆盖 profile；partial group 被拒绝，不做字段混合；
- explicit `--provider fake` 仍可用于测试；无参数不能 fallback fake；
- credential env 缺失只报告 env name，不报告环境内容；
- profile 的 destination/model 进入既有 provider descriptor/disclosure binding。

### Green

最小调整 `main.py` parser/composition。setup 是本地配置 action，不进入 Runtime；日常运行仍只构造一套
composition 和一个 `AgentRuntime.run_turn` 路径。不要添加 service locator 或 provider registry。

### Exit

CLI entry/provider/restart focused tests Green；旧显式参数用法保持可运行。

## 6. U3 — Contextual decisions without protocol copying

### Red

为 CLI action translation 增加 table-driven tests：

- disclosure pending 时 `y/yes/是/允许` 形成 exact acknowledgement，`n/no/否/不允许` 安全退出或拒绝；
- approval pending 时肯定/否定绑定 exact request ID + binding digest；
- 同样文本在无 pending request 时仍为普通 `SubmitMessage`；
- unknown outcome 只接受明确 success/failure/stop，模糊输入零 effect；
- slash commands 保持高级兼容，但主提示不暴露 digest/ID；
- stale/replayed response 仍由 action_seq/revision/binding fail closed。

### Green

只在 `agent/cli` adapter 内做 state-aware typed-action translation；不调用模型、不改 reducer 合法性、不直接
执行工具。Renderer 展示 human preview，内部继续使用 exact durable binding。

### Exit

CLI/headless/TUI parity tests 证明 UI 易用性没有创建新的 state owner。

## 7. U4 — Deterministic startup selection and recovery UX

### Red

- 一个安全候选自动恢复，startup provider/tool send count 为零；
- 多候选显示有界编号 + outcome/status，选择后使用 exact `SelectGoal`；
- invalid/out-of-range/stale selection 零 provider/tool effect；
- workspace identity drift 和 unknown effect 使用普通语言准确停下；
- empty workspace 和 symlink alias 的既有 identity 语义不回归。

### Green

组合根只消费 `open_workspace_session` / `select_workspace_session` 的既有 typed contract。允许 startup 交互
选择，但不能修改 session selector 规则、猜最近候选或写第二份 catalog。

### Exit

restart/selection/recovery focused suite 和对应 CLI tests Green。

## 8. U5 — Everyday system policy and quiet rendering

### Red

reference fixtures 与渲染测试覆盖：

- direct answer 和 discussion 不产生 Goal/tool；
- discussion 后明确产物才建立 Goal；
- empty workspace 可通过 `list_files('.')` 后创建目标；
- existing workspace 只改 exact target，sentinel digests 不变；
- default output 不含 request digest、raw tool-call ID、revision、checkpoint path、内部 enum；
- 默认隐藏 model/tool progress 噪音，但保留 disclosure/approval/recovery/warning/final；
- terminal control/ANSI/bidi literal rendering 不回归；
- happy path 没有 mode selection 或阶段性 `/resume`/“继续”指令。

### Green

更新 composition system policy、CLI renderer 和最窄 view projection。不要把产品行为复制到第二个 prompt
router；012 control schema 与 Runtime reducer 仍是语义权威。

### Exit

三条 scripted reference journey 和 renderer/CLI suite Green。

## 9. U6 — Evidence-backed file journeys

### Red

复用并扩展 012 oracle tests：

- Goal CAS 严格早于 effectful tool prepare；
- approval yes/no 不改变 binding；
- write/read-back digest 满足 admitted criterion 后才 `VERIFIED_DONE`；
- 模型 plain “done”、伪造 evidence、旧 Goal revision receipt 和 mutation oracle 均不能通过；
- crash before effect 可恢复，crash at `EXECUTING` 进入 unknown outcome 且 send/invoke count 不增长；
- unrelated file、state root、profile 和 credential env 都不成为 workspace tool 输入。

### Green

优先复用现有 Goal/evidence/file-tool 实现。只有真实 Red 证明缺口时才改 Runtime；不得为了测试重写 012
状态机。

### Exit

continuity/file-tool/provider disclosure/reference journey suites Green。

## 10. U7 — Packaging and clean-room reference gate

### Red / Green

1. 在临时 venv 中从 materialized tree 安装 base package。
2. 使用临时 home/state root 和空/已有 workspace 运行 setup + no-arg CLI journeys。
3. 证明 base install 不需要 TUI/MCP/Skill extras；不读开发仓库 runtime。
4. 更新 README/STRATEGY，只声明物化证据支持的能力；旧高级 flags 移到 reference，不占主路径。
5. 更新 materialized manifest/seal，使新增生产/测试/文档成员受控。

### Exit

clean-room reference gate、packaging metadata、README commands 和 materialized verifier Green。

## 11. U8 — Real Provider E3

按 `docs/acceptance/013_EVERYDAY_WORKSPACE_AGENT_E3.md` 实现一个 production-adapter harness。它必须：

- 只读取四个显式 `FIRST_AGENT_E3_*` 名称；
- 使用临时 home/state/workspace，先写 non-secret profile，再走 no-argument composition；
- disclosure acknowledgement 前真实 HTTP send count 为零；
- 运行 J1、J2、J3 的 bounded prompts；
- 保存 secret-free machine-readable receipt；
- 不把 fake/mock/scripted provider 计为 E3。

缺配置只能在 U0-U7 和全部离线门 Green 后输出准确 `NEEDS_013_E3_CONFIG`。真实 attempt 失败输出准确
`013_E3_BLOCKED`；两者都不是完成。

## 12. U9 — Full gates and fresh review

执行未截断：

```bash
git diff --check
.venv/bin/ruff check .
.venv/bin/python -m pytest -q -rx
.venv/bin/python scripts/verify_013_materialized_tree.py --check-membership
.venv/bin/python scripts/verify_013_materialized_tree.py --content
.venv/bin/python scripts/verify_013_materialized_tree.py --control-seal
```

013 verifier 以冻结的 009 manifest 为 baseline、绑定 012 parent seal，并用新的 closed overlay seal 覆盖
本轮 ordinary files。不得改写 009 manifest 或 012 seal；usage error 不能算 pass。

随后使用 fresh session 做 correctness/security/architecture review。Reviewer 必须主动攻击 profile secret、
symlink/mode、partial precedence、send-before-disclosure、yes/no state confusion、stale binding、第二 loop、false
done、restart replay、quiet renderer 隐藏安全警告、mock 冒充 E3。

有 P0/P1/P2 finding：恢复 executor 做 Red → Green，然后 fresh review 全部 diff。只有
`013_REVIEW_PASS` 才结束 loop。

## 13. Stop protocol

- Offline 唯一缺真实配置：
  `NEEDS_013_E3_CONFIG(required=FIRST_AGENT_E3_PROVIDER,FIRST_AGENT_E3_BASE_URL,FIRST_AGENT_E3_MODEL,FIRST_AGENT_E3_API_KEY)`
- 真实 E3 尝试失败：
  `013_E3_BLOCKED(reason=<incomplete_config|auth_failed|endpoint_unreachable|rate_limit_exhausted|provider_protocol|model_incompatible>)`
- Executor 全部门通过：`013_EXECUTOR_READY_FOR_REVIEW`
- Reviewer 有问题：`013_REVIEW_FINDINGS`
- Fresh review 全通过：`013_REVIEW_PASS`

正常退出但没有合法 marker、阶段性 Green、timeout、截断输出或额度错误都不是完成；外部开发 loop 从
execution log 的第一个未闭合 gate 继续。

## 14. 完成状态（2026-08-03）

U0-U8 全部闭合：真实 E3 在官方 DeepSeek OpenAI-compatible strict beta endpoint 连续三次未插桩
通过（12/12 claims、3/3 journeys）。第一轮 review 前的 full gates Green；证据见
`docs/acceptance/013_EVERYDAY_WORKSPACE_AGENT_E3.md` §7 与
`docs/implementation/013_EXECUTION_LOG.md`。

第一轮 fresh independent review 输出 `013_REVIEW_FINDINGS`（F1 verifier 收编仓库根 loop 临时
文件、F2 scheduler 缺 strict composition 参数、F3 PAUSED Goal 问答被 repair 耗尽），三项均已
Red → Green 闭合（见 execution log 的 review-fix 小节与 design §7.3）。review-fix 后重算
104-entry seal，六项完整门 Green（源码与 materialized tree 均 `730 passed`）；fresh Standards 与
Spec re-review 分别输出 `STANDARDS_REVIEW_PASS`、`SPEC_REVIEW_PASS`，无 unresolved P0/P1/P2。
