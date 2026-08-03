---
title: 013 Everyday Workspace Agent - Execution Log
type: implementation-log
date: 2026-08-03
authority: non-authoritative-evidence
status: executor-complete-pending-fresh-review
---

# 013 Everyday Workspace Agent — Execution Log

本文件记录 013 的非秘密 Red/Green、命令、exit code、设计决定和 remaining risk。权威合同为：

- `docs/architecture/013_EVERYDAY_WORKSPACE_AGENT_DESIGN.md`
- `docs/plans/2026-08-03-001-feat-everyday-workspace-agent-plan.md`
- `docs/acceptance/013_EVERYDAY_WORKSPACE_AGENT_E3.md`
- `docs/implementation/013_LOOP_HANDOFF.md`

## Preparation audit

- Baseline HEAD：`59703d0b53cdf832e8d706b4c5f1727cddbcc7fc`（`main == origin/main` at preparation）。
- 用户未跟踪路径类别：`tui/`；不读取、不删除、不覆盖、不 stage。
- 012 已有：单一 `AgentRuntime.run_turn`、direct answer/minimal clarification/durable Goal、Goal controls、
  deterministic restart、provider disclosure、approval/recovery、evidence-backed `VERIFIED_DONE`、owner preference。
- 013 真实缺口：默认仍为 FakeProvider；真实 provider 每次需要完整 flags；没有 non-secret one-time profile；
  disclosure/approval/recovery 要求用户复制内部 digest/ID；multiple candidate startup 只打印内部候选后退出；
  默认 renderer 暴露 model/tool event 噪音和内部状态语言。
- Graphify query 只用于定位 `main.py -> sessions/provider/composition -> AgentRuntime -> renderer`；当前源码
  已直接核验，graph 未刷新。

### Pre-executor baseline（2026-08-03）

- `git diff --check` → exit `0`。
- `.venv/bin/ruff check .` → exit `0`，`All checks passed!`。
- `.venv/bin/python -m pytest -q -rx` → exit `0`，`575 passed in 49.83s`，输出未截断。
- Claude Code preflight：CLI `2.1.216` 可用；只检查了公开 `--help`，确认支持
  `--dangerously-skip-permissions`、`--effort`、`--output-format=stream-json` 与 `--resume`。未读取或修改
  Claude settings/auth/model aliases。

## Frozen implementation constraints

- 013 只做产品入口收口，不新增 shell/web/browser/multi-root/self-improvement。
- 不创建产品内 CodingLoop 或第二 Runtime。
- Claude Code 使用用户已有配置；不读取/改写其 settings/auth/model aliases。
- Claude 额度停止后由 Codex从本文件和当前 diff 接手；同一工作树不并发修改。
- 未经用户再次授权，不 commit/push/tag/改 remote。

## U0 — Freeze baseline（executor re-check, 2026-08-03）

- HEAD `59703d0b53cdf832e8d706b4c5f1727cddbcc7fc`，`main...origin/main` 无 ahead/behind。
- 工作树:`M STRATEGY.md` + 013 docs 未跟踪 + 用户未跟踪 `tui/`(未读取)。
- Python 3.12.2、ruff 0.15.10。
- `git diff --check` → exit 0;`.venv/bin/ruff check .` → exit 0(`All checks passed!`)。
- `.venv/bin/python -m pytest -q -rx` → exit 0,`575 passed in 47.36s`,输出未截断。
- 架构搜索:production `.generate(` 仅 `agent/runtime/loop.py:672`(grep agent/ main.py scripts/ 排除 tests)。
- 结论:baseline Green,无 pre-existing 失败;U0 关闭。

## Unit status

| Unit | Status | Evidence |
|---|---|---|
| U0 baseline | **Green (executor verified)** | 575 passed, Ruff/diff exit 0, single `.generate(` site |
| U1 ProviderProfileV1 | **Green** | 见 U1 小节 |
| U2 setup/no-arg composition | **Green** | 26 CLI/scheduler focused tests passed；见 U2 小节 |
| U3 contextual decisions | **Green** | contextual typed-action tests + CLI regression Green |
| U4 startup/recovery UX | **Green** | exact `SelectGoal` 与 restart focused tests Green |
| U5 policy/quiet rendering | **Green** | quiet renderer + everyday policy/reference tests Green |
| U6 file journey/evidence | **Green** | empty/write/edit/restart/read-back journeys Green |
| U7 packaging/reference | **Green** | 013 seal + clean-room 688 passed |
| U8 real Provider E3 | **Green** | 官方 DeepSeek strict beta；连续 3 次未插桩 run 全 exit 0，12/12 claims |
| U9 full gates/review | gates **Green**；fresh review 待运行 | 见 U9 小节 |

## U1 — ProviderProfileV1（2026-08-03）

- Red:新增 `tests/provider/test_provider_profile.py`(69 tests,覆盖 strict schema/round-trip/
  no-secret/owner-only/no-follow/single-link/atomic replace/normalization/控制字符/fake 不可持久化/
  AgentProviderConfig 投影)。首跑 `ModuleNotFoundError: No module named 'agent.provider.profile'`,exit 2。
- Green:新增 `agent/provider/profile.py`。`ProviderProfileV1` frozen dataclass + strict `__post_init__`;
  `save_provider_profile` 用同目录 `.tmp-<hex>` O_EXCL 0600 + fsync + `os.replace(dir_fd)` + dir fsync;
  `load_provider_profile` 用 dir_fd + O_NOFOLLOW + fstat(regular/owner/nlink==1/0600/size≤64KiB) +
  exact-keys strict decode;缺文件返回 `None`(由 caller 给 setup 指引)。
- 秘密字段负证明:dataclass 无 credential 字段;serialized payload 只有 7 个 allowlist key;
  测试 `test_serialized_file_never_contains_ambient_secret` 设置 env 哨兵秘密后断言文件不含它。
- 决定:base_url 只允许 https(loopback http 例外)、无 userinfo/query/fragment;credential_env 按
  `[A-Za-z_][A-Za-z0-9_]{0,127}` 校验名称;timeout ∈ (0, 3600];`thinking_mode=disabled` 仅
  openai_compatible(与 `AgentProviderConfig` 一致);wrong-owner 用 monkeypatch os.getuid 模拟。
- 验证:`pytest tests/provider/test_provider_profile.py -q` → 69 passed, exit 0;
  `pytest tests/provider/ -q` → 197 passed, exit 0;`ruff check .` → 0;`git diff --check` → 0。
- Remaining risk:profile 文件 mode/owner 检查对抗的是误配置而非同 UID 恶意进程(与 kernel 诚实边界一致)。

## U2 — Setup 与无参数 composition（2026-08-03，Codex 接手）

- Claude executor 在开始 U2 前连续两次被上游 `524 origin_response_timeout` 中断；没有 U2 物化改动，
  Codex 按 handoff 从同一 working tree 接手。
- Red：新增 `tests/cli/test_everyday_entrypoint.py`，覆盖 setup 零 conversation/provider、profile 无秘密、
  无 profile 在 checkpoint/provider I/O 前停止、saved profile + cwd、完整显式 group 覆盖、partial group
  不混合、显式 fake 与 credential-env 精确错误。首次运行 → `5 failed, 2 passed`，exit `1`；失败准确
  命中无 setup subcommand、默认 fake、未加载 profile、partial merge 未拒绝和 credential 缺失未生效。
- Green：`main.py` 增加本地 `setup` action 与排他的 provider precedence；runtime provider flags 默认
  `None`，只有显式 `--provider fake` 才使用 FakeProvider；saved profile 在 session bootstrap 之前解析，
  credential value 仍只在 composition root 按 env name 注入。
- 验证：`pytest tests/cli/test_everyday_entrypoint.py tests/cli/test_entrypoint.py
  tests/scheduler/test_cli.py -q -rx` → `26 passed`，exit `0`。touched Ruff 首跑只命中新测试 import
  排序，已用最小格式修复；需在下一 touched gate 复跑确认。

## U3 — Contextual decisions（2026-08-03，Codex）

- Red：新增 `tests/cli/test_contextual_decisions.py`，首跑 `19 failed, 4 passed`；准确命中 disclosure、
  approval、recovery 仍要求 slash protocol，普通 yes/no 没有按 pending durable state 翻译。
- Green：只修改 `agent/cli/app.py` adapter。pending disclosure/approval 下肯定或否定映射 exact typed
  action；unknown outcome 只接受明确 success/failed/stop；无 pending 时同样文本仍是 `SubmitMessage`。
- 安全边界：CLI 不执行 tool、不写 Goal、不持有 binding；stale/replay 继续由 reducer 的
  action_seq/revision/request binding fail closed。

## U4 — Startup selection（2026-08-03，Codex）

- Red：`tests/cli/test_startup_selection_013.py` 首跑 `2 failed`，命中 multiple candidate 只打印内部候选
  后退出、没有 exact selection action。
- Green：`SessionCandidate` 只补 state revision/action sequence 投影；`main.py` 显示有界编号和用户 outcome，
  选择后构造 exact `SelectGoal` 并调用既有 `select_workspace_session`。invalid/out-of-range 不调用
  Provider/Tool、不改变 checkpoint。
- focused selection/state/restart `14 passed`；随后 CLI + continuity `69 passed`。

## U5/U6 — Everyday policy、quiet output 与 evidence journeys（2026-08-03，Codex）

- Renderer 默认隐藏 model/tool progress，保留 disclosure/approval/recovery/warning/final；用户无需看到
  request digest、tool-call ID、revision 或 checkpoint path。控制字符 literal rendering regression Green。
- `EVERYDAY_SYSTEM_POLICY` 只描述 ask/discuss/minimal clarification/Goal-before-effect/read-back；没有加入
  classifier、第二 prompt router 或第二 Runtime。
- reference Red 首先暴露两条过严断言，修正后又准确暴露真实缺口：`edit_file` 审批没有铸造
  filesystem-digest admitted criterion，completion claim 被拒后 provider script exhausted。
- 最小 Green：Runtime 将既有 `write_file` admission 泛化为 exact approved file mutation admission，直接使用
  approval request 中已绑定的 `new_content_digest`；没有从模型文本或 effect 结果伪造 evidence。
- reference 最终覆盖：讨论到 `notes/idea.md`、真空目录 `list_files('.')` 后创建 `idea.md`、已有目录
  `edit_file` 在 approval 前重启、只改目标文件、sentinel digest 不变、read-back 后 `VERIFIED_DONE`。
- touched regression：CLI/continuity/kernel/provider/reference `414 passed`；013 reference + E3 offline/交付层
  focused `9 passed`，Ruff/diff Green。

## U7 — Packaging、README 与 closed materialization（2026-08-03，Codex）

- Red：`tests/architecture/test_013_delivery_layer.py` 首跑 `1 failed, 1 passed`，缺 013 verifier/seal。
- 新增 `verify_013_materialized_tree.py` 与 strict v2 seal：冻结 009 manifest 为 baseline，绑定 012 parent
  seal；013 execution log/seal/verifier 是 control，ordinary code/docs/tests 进入 closed overlay；denied/private/
  runtime（包括用户未跟踪 `tui/`）在读取/hash 前排除。
- 第一轮 membership/control seal 虽 Green（64 entries），content gate 在 non-editable origin import 失败：
  `agent/runtime/control.py` 缺失。根因是继承的 012 overlay 只枚举 009 entries + untracked files，漏掉 baseline
  之后已 commit、但不在 009 manifest 的 tracked paths。
- Red/Green 修复：013 verifier 额外对账 `git diff --name-only --no-renames <baseline>` 与显式 untracked
  admission；新增 temp Git repo 回归测试。closed overlay 增至 100 entries，物化安装可导入完整产品树。
- 第二轮 content gate：`1 failed, 687 passed`，准确命中 architecture allowlist 未批准
  `agent/provider/profile.py`；只将该已由 013 合同批准的 seam 加入 frozen allowlist。
- README 主路径已改为一次 setup + 此后当前目录 `first-agent`；Fake/完整 flags 保留为开发/高级路径。
- 最终源码树：`688 passed in 176.54s`；`.venv/bin/ruff check .`、`git diff --check` exit `0`。
- 最终物化门：membership `100 exact entries`、control seal Green、non-editable/neutral cwd/deny-network
  content gate `688 passed in 148.59s`，`ALL CHECKS PASSED`，输出未截断。

## U8 — Real Provider E3 harness（offline complete，2026-08-03）

- Red：新增 `tests/reference/test_013_e3_harness.py`，脚本缺失时 `4 failed`。
- Green：新增 `scripts/run_013_e3.py`。它只读取四个 `FIRST_AGENT_E3_*`，先走产品 setup，再从 cwd 调用
  `product_main.main([--state-root ...])`，Provider 参数只来自 saved profile；注入的仍是
  `build_model_provider` 创建的 production HTTP adapter + recording wrapper，不存在 fake/scripted/mock path。
- harness 覆盖 J1 ask/discuss、J2 discussion→artifact、J3 existing workspace approval 前退出并 restart；成功
  receipt 固定 12 个 bool claims，只保存 provider/model/destination digest、bounded counts/digests/verdicts。
- offline harness `4 passed`；missing/partial config marker、production-path AST、12-claim schema、unexpected-error
  sanitization Green。
- 配置 presence-only 检查：四个 exact env 均为 `false`；没有读取、打印或从历史消息复用任何值。

## U8 — Real DeepSeek E3（历程与最终 Green，2026-08-03）

- 配置依据：先只读核验 DeepSeek 官方文档 `https://api-docs.deepseek.com/zh-cn/guides/tool_calls/`
  与 `https://api-docs.deepseek.com/api/create-chat-completion/`。API key 只经
  `FIRST_AGENT_E3_API_KEY` 注入 harness 子进程；未进入 argv、stdout、文件、profile、checkpoint 或本文。
- 最小 production adapter probe 首先成功返回 `ModelTextBlock/end_turn`，排除 endpoint/auth/base protocol。
- 第一轮真实 journey 暴露 scripted tests 未覆盖的缺口：Runtime 要求 exact `criterion_evidence_refs`，但
  `trusted_goal` 只投影 criterion ID。Red：context contract 缺
  `expected_completion_evidence_refs`；Green：Runtime 投影精确 refs，control schema/system policy 要求原样复制，
  closed oracle 仍独立重算。focused provider/context/reference → `74 passed`。
- 第二轮暴露 DeepSeek 复用 GoalProposal correlation ID 于 CompletionClaim。Red：013 reference 插入重复
  correlation 后 fatal；Green：schema 要求每次 control 新 ID，completion reducer 冲突在同一 run 内做一次
  bounded repair，重复仍 `invalid_model_control` fail closed。focused → `3 passed` + touched Ruff Green。
- 后续发现同一模型偶发产生 malformed tool/control JSON。没有放宽 normalizer；新增 port-level
  `InvalidProviderResponseError`，严格归一化失败时零接纳/零工具 effect，在相同 trusted context 有界重试，
  超限为 `invalid_provider_response`；everyday 入口显式 `max_invalid_repairs=2`。focused
  provider/runtime/reference → `116 passed`，Ruff Green。
- **普通端点观察被取代**：早先在普通端点 `https://api.deepseek.com`（destination digest
  `7f7852e0…`）取得的一次 exit 0（observed `2026-08-03T05:06:02.475673+00:00`）曾被记录为最终
  receipt。该结论撤回：普通 Tool Calls 不在合同上保证 schema-valid arguments，重复 run 暴露畸形
  参数与回执模仿失败，该观察不作为 013 验收证据。
- **Strict 回执回放 blocker 与修复（Red/Green）**：strict 端点下模型把历史回放的
  ControlReceipt tool call 当作新的可调用工具模仿（先模仿 `first_agent_control_v1`，改名为专用
  receipt 名后转而模仿该名字）。重试/加 retry 不是修复。架构修复：已受理回执改为 trusted SYSTEM
  投影（`FIRST_AGENT_TRUSTED_CONTROL_RECEIPT` + canonical 闭包 durable 八字段行，两协议共用
  `trusted_system_projection`），彻底删除 `RESERVED_CONTROL_RECEIPT_NAME` 与两处历史回放循环。
  Red：`tests/provider/test_continuity_control.py` 重写后 `3 failed, 67 passed`；Green：`70 passed`，
  聚焦六文件套件 `137 passed`，touched+全仓 Ruff、`git diff --check` Green。
- **Scheduler parser 对齐**：`build_schedule_parser` 缺 `--request-path/--strict-tools` 导致
  `tests/cli/test_entrypoint.py` AttributeError。补齐后该文件 Green。
- **harness 修复**：`_RecordingProvider` 成功 `generate` 未清除 stale `last_error`，会把旧错误误报为
  当次失败原因；Red/Green 回归测试后已在成功路径清零。
- **discussion/progress loop 诊断**：strict `tool_choice=required` 下模型在讨论轮反复发
  `goal_progress`、或把讨论升级为 Goal。修复只收紧模型可见 lifecycle 指令
  （`EVERYDAY_SYSTEM_POLICY`）：讨论/解释/比较/头脑风暴 answer-only；仅显式 create/write/edit/save
  建 Goal；`goal_progress` 只记录实质进展、不替代产品工具。没有加入第二 classifier 或 loop。
- **正式三连通过（官方 strict beta）**：`.venv/bin/python scripts/run_013_e3.py` 未插桩连续三次
  exit `0`；`openai_compatible` / `deepseek-v4-flash` / base `https://api.deepseek.com/beta` /
  request path `/chat/completions` / strict tools；destination digest
  `041d0bb552124d18995dbded8c2bd81bfac53ada9e42e6c35cca6c834bdff3c3`。
  observed_at 与 counts：Run1 `07:39:28.151034+00:00`（total 12 / ack 前 0 / restart 前 10）、
  Run2 `07:40:14.636819+00:00`（13 / 0 / 11）、Run3 `07:41:03.676707+00:00`（13 / 0 / 11）。
  三次均 3/3 journeys passed、12/12 claims true；artifact/goal-opaque/sentinel digests 三次一致，
  完整 receipt 见 acceptance §7。credential 已由宿主在 run 后清除。

## U9 — Docs closure、seal 重算与 full gates（2026-08-03）

- 文档收口：design 置 `implemented-and-verified`（新增 §7.2 strict 控制通道 + trusted SYSTEM 回执
  投影、§12 验证状态）；acceptance §7 记录官方 strict beta 三连 receipt 并声明普通端点观察被取代；
  plan 置 `completed-and-verified`；STRATEGY 将 013 移入已交付；README 增加 DeepSeek strict setup
  示例（只出现环境变量名 `FIRST_AGENT_API_KEY`，无任何 secret value）。
- 收口期间回归：host 收紧 trusted lifecycle/control 指令后 pinned 估算增长约 28 tokens，
  `tests/kernel/test_context_budgeting.py`、`tests/kernel/test_context_manager.py` 的静态
  `CONTROL_SCHEMA_BUDGET = 970` 基线过期 → 5 failed。实测最小预算后分别修正为 998/999
  （margin 语义不变），两文件 `11 passed`。
- Delivery seal：在全部 overlay 成员（docs/tests）稳定后用 verifier 自身
  `derive_overlay`/`overlay_root` 重算 `013_DELIVERY_SEAL.json`；`entry_count = 102`。
- Full gates（全部完整输出、未截断）：
  - `git diff --check` → exit `0`。
  - `.venv/bin/ruff check .` → exit `0`，`All checks passed!`。
  - `.venv/bin/python -m pytest -q -rx` → exit `0`，`723 passed in 52.05s`。
  - `verify_013_materialized_tree.py --check-membership` → exit `0`，`102 exact entries`。
  - `verify_013_materialized_tree.py --control-seal` → exit `0`。
  - `verify_013_materialized_tree.py --content` → exit `0`，clean-room 物化安装
    `723 passed in 63.37s`，`ALL CHECKS PASSED`。

## Current stop state

### Fresh review findings closure（2026-08-03）

- fresh reviewer session `78c54a88-57a2-4bc7-b075-351c7503dcd6` 输出
  `013_REVIEW_FINDINGS`：F1 P2 仓库根 `.codex-tmp-*` 会被 013 overlay 收编；F2 P3 scheduler
  `--strict-tools` 未向 composition 传递 `strict_control_schema`；F3 P3 `PAUSED` Goal 的普通 prose
  会耗尽 `active_goal_requires_control` repair，且暂停状态的 effect/control 边界未闭合。
- F1 Red → Green：`DENIED_PREFIXES` 新增窄前缀 `.codex-tmp-`，并证明不可读 loop temp 在 hash
  前被拒、普通未跟踪文件仍进入 overlay。
- F2 Red → Green：scheduler composition 传递 `strict_control_schema=bool(args.strict_tools)`；离线
  disclosure 停点捕获 strict/non-strict 实参，保持首次外发前零发送。
- F3 Red → Green：PAUSED 上下文只暴露只读工具且不下发 goal control schema；Runtime 允许普通 prose
  收尾、在 prepare 前拒绝 effectful tool、对 goal control 做有界 repair；reducer 禁止 GoalProgress
  静默恢复暂停任务。推进必须先显式 `ResumeGoal`。
- Claude executor：F1 focused `4 passed`，F3 `12 passed`，相关回归 `514 passed in 74.83s`。
  随后 Claude 触发 weekly spending limit；Codex 接手复跑三项针对性集合：`25 passed in 4.22s`，
  touched Ruff 与 `git diff --check` 均 exit `0`。

### Review-fix 后完整门与 fresh re-review（2026-08-03）

- 第一次 post-fix seal：`104 exact entries`；`git diff --check`、全仓 Ruff、membership、control seal
  均 exit `0`。
- 完整源码测试：`730 passed in 110.46s`，exit `0`。
- clean-room content gate：non-editable install + deny-network + Ruff + materialized pytest
  `730 passed in 100.13s`，`ALL CHECKS PASSED`，exit `0`。
- secret-shape filename scan在 `agent/tests/scripts/docs/README/STRATEGY/main.py` 无命中；仓库根无
  `.codex-tmp-*` 残留。
- fresh Standards reviewer（固定点 `59703d0b53cdf832e8d706b4c5f1727cddbcc7fc`）输出
  `STANDARDS_REVIEW_PASS`：hard violation 0、actionable judgement call 0。
- fresh Spec reviewer输出 `SPEC_REVIEW_PASS`：actionable P0/P1/P2 0；唯一 P3 是本 execution log
  的 pending 文字过期，已由本节修正。

最终文档状态已固定；随后再次重算 seal 并复跑六项门。未经用户授权仍不 commit/push；用户未跟踪
`tui/` 未读取、未修改、未纳入 seal。

`013_REVIEW_PASS`
