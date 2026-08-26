---
title: First Agent 1.0 Product Convergence - Implementation Plan
type: feat
date: 2026-08-20
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
authority: 016-plan
status: frozen
execution: code
---

# 016 First Agent 1.0 产品收束实施计划

## Goal Capsule

把 012—015 已交付的可信连续性、workspace/history 知识、公开 Web 研究和受治理本机执行，收束成一条
普通用户能够安装、配置、启动、理解和恢复的 `first-agent` 默认路径。016 不增加能力 owner，不建立第二套
planner/executor loop，也不借“易用性”放松 Provider/Web/file/process 的 deterministic hard gate。

完成定义严格以冻结的
`docs/architecture/016_FIRST_AGENT_1_0_EXPERIENCE_DESIGN.md` 和
`docs/acceptance/016_FIRST_AGENT_1_0_E3.md` 为准：U0、U1、U2 连续三轮真实 receipt、U3 fresh review
全部 Green，README 声明不超过证据。缺少真实在线配置只能得到准确的 `NEEDS_016_E3_CONFIG`，不能冒充完成。

## 实施边界与假设

- `AgentRuntime.run_turn` 保持唯一 production model/tool loop；setup、startup、harness 都不能推进平行 Goal。
- 优先修改 packaging、CLI adapter/projection、composition status、README 和验收 harness。只有 Red test 证明
  现有 Runtime 合同不满足冻结要求时，才允许对 Runtime 做最小改动。
- `first-agent setup`：无参数是 guided flow；完整 provider/model/base-url 参数组是非交互 flow；部分参数组
  直接给出一个可操作错误，绝不与 saved profile 混合。
- `first-agent setup-web`：无配置参数是 guided flow；完整自动化参数必须显式 `--yes`，避免脚本无意写 profile。
  两种路径写同一个 `WebProfileV1`，均不读取 key value 或发送网络请求。
- Web 状态只有 `not_enabled`、`ready`、`temporarily_unavailable` 三种本地 composition 事实。缺 key 时不注册
  Web tools，但不能阻止本地 Agent 启动；启动状态不做网络 health check。
- promotion candidate 版本是 `1.0.0`。版本只来自 installed distribution metadata，测试时不得依赖 cwd
  恰好能 import 仓库根 `main.py`。
- 不读取 `.env`、`tui/`、真实 checkpoint、Memory、Claude/Codex 配置或其他 private/runtime 数据。
- 本计划不含 commit、push、tag、release 或 PyPI 发布。

## Traceability

| 工作包 | Design | E3 journey / claim |
|---|---|---|
| P1 packaging/version/help | §4.1 | J1 / C1-C2 |
| P2 guided provider setup | §4.2、§9 | J2-J3 / C3-C4、C6 |
| P3 optional Web setup/status | §4.2、§4.3、§9 | J3-J4 / C5、C8、C21 |
| P4 startup and safety projection | §4.3、§7、§9 | J4、J10、J12 / C7、C14、C16、C18-C20、C25 |
| P5A typed intent gate | §5.0–§5.2、§8 | J5–J9 / C9-C13 |
| P5 deterministic U1 | §5-§9 | J5-J12 supporting gates / C9-C25 |
| P6 installed-process E3 | §10 | J1-J12 / all 25 claims |
| P7 delivery/docs/review | §10-§11 | U0-U3 / promotion rule |

## Task 1 — 冻结产品合同并建立 Red gate

**Files**

- Modify: `docs/architecture/016_FIRST_AGENT_1_0_EXPERIENCE_DESIGN.md`
- Modify: `docs/acceptance/016_FIRST_AGENT_1_0_E3.md`
- Create: `docs/plans/2026-08-20-001-first-agent-1-0-product-convergence-plan.md`
- Create: `tests/reference/test_016_first_agent_1_0_contract.py`

**Steps**

1. 将经用户确认的 design 与 acceptance 标记为 frozen。
2. 写 contract test：断言 12 journeys、25 claims、唯一 Runtime 红线、五个 E3 env name、denylist、版本
   `1.0.0`、三连真实验收和 fresh reviewer 要求都存在且无 placeholder。
3. 运行新测试，证明当前 packaging/CLI 尚不能满足 P1-P4 的行为断言；保留准确 Red 结果。

**Verify**

```bash
.venv/bin/python -m pytest tests/reference/test_016_first_agent_1_0_contract.py -q
```

## Task 2 — 安装、唯一版本与 help 信息架构

**Files**

- Modify: `pyproject.toml`
- Modify: `main.py`
- Create: `tests/cli/test_016_packaging.py`
- Modify: `tests/cli/test_entrypoint.py`

**Steps**

1. 先写 Red tests：`--version` 为 distribution metadata 的 `1.0.0`；help 首屏先展示普通启动、`setup`、
   `setup-web`，高级参数进入独立 argument group；base extra 不被强制安装。
2. 把 distribution candidate version 改为 `1.0.0`，用 `importlib.metadata.version("first-agent")` 作为唯一
   installed version source；metadata 不存在时只给准确“未安装”产品错误，不用源码常量伪造版本。
3. 重排 argparse help，不改变现有 advanced flag 语义。
4. 在临时目录构建 wheel，并安装到 disposable venv；从 repo 外运行 installed `first-agent --version` 与
   `--help`。测试只检查本地 artifact，不访问网络。

**Verify**

```bash
.venv/bin/python -m pytest tests/cli/test_016_packaging.py tests/cli/test_entrypoint.py -q
```

## Task 3 — Guided provider setup 与准确首次启动

**Files**

- Modify: `main.py`
- Modify: `tests/cli/test_everyday_entrypoint.py`
- Create: `tests/cli/test_016_guided_setup.py`

**Steps**

1. 写 Red tests 覆盖：无参数逐项 prompt、完整 flags 非交互、部分 flags 拒绝、EOF/取消零 profile、无
   Provider/checkpoint/credential read、无 traceback/type name、完成后唯一 shell 下一步。
2. 让 setup parser 的 provider/model/base-url 变为可选；在 `_run_setup` 中严格区分 no-args guided 与
   complete flags。`input_fn` 只接收 non-secret metadata。
3. guided provider 类型只接受 frozen choice，model 非空，base URL 与 env name 继续由
   `ProviderProfileV1` strict validation；错误转成字段级普通语言。
4. 修改未 setup、缺 provider credential、partial explicit group 和 expected startup error 的默认文本：一条
   修复动作，不显示 exception class，不创建 checkpoint、不做 Provider I/O。

**Verify**

```bash
.venv/bin/python -m pytest tests/cli/test_016_guided_setup.py tests/cli/test_everyday_entrypoint.py -q
```

## Task 4 — Guided Web setup 与 optional degradation

**Files**

- Modify: `agent/composition.py`
- Modify: `main.py`
- Modify: `tests/web/test_composition.py`
- Create: `tests/cli/test_016_web_experience.py`

**Steps**

1. 写 Red tests 覆盖：无参数 disclosure→当前确认→保存；拒绝/EOF 零写入；`--yes` 自动化；任何 setup
   路径零 key read/零 Web send；profile 无 key 时本地启动成功且 Web tools 为零。
2. 为 `WebResources` 增加 closed、non-secret readiness projection（`not_enabled|ready|temporarily_unavailable`）
   和缺失 env name；不得增加动态 registry 或假 client。
3. `build_web_resources` 在 profile + missing credential 时返回 unavailable/zero registrations，而不是抛出
   startup failure；profile invalid 仍 fail closed。
4. `_run_web_setup` 的默认人类路径先显示固定 Tavily destination、第三方处理事实、env name 和保存内容，
   只有 affirmative answer 才写；自动化必须使用完整 flags + `--yes`。
5. 证明 startup 为展示状态不触发 `TavilyClient` request。

**Verify**

```bash
.venv/bin/python -m pytest tests/web/test_composition.py tests/cli/test_016_web_experience.py -q
```

## Task 5 — 可读启动、安全提示与恢复投影

**Files**

- Modify: `main.py`
- Modify: `agent/cli/render.py`
- Modify: `agent/process/contracts.py` 或 process preview owner（仅当现有 preview 无法投影普通语言）
- Modify: `tests/cli/test_render.py`
- Modify: `tests/cli/test_commands.py`
- Create: `tests/cli/test_016_startup_projection.py`

**Steps**

1. 写 Red tests：empty/existing workspace 启动摘要包含目录、model、文件/历史、本机程序和三态 Web；默认
   denylist 无命中；恢复唯一 Goal、多个 outcome 候选、unknown outcome、provider retryable、16 次
   no-progress 的状态都有唯一用户动作。
2. 增加纯 projection helper，把 composition/session durable facts 转成 bounded 用户文本；CLI 不读取或改变
   Goal。
3. 将 process approval 首段改为准确中文：以当前 OS 用户权限运行、不是 sandbox、可能访问同 UID 文件/
   网络；保留 exact executable/argv/cwd，technical details 仍可读。
4. provider failure/no-progress 的暂停文本包含最后可信进展（若有）、当前 blocker 与
   `/resume`/`/cancel`；不显示 false completion。
5. 验证提示仍 escape terminal controls，且 expected errors 默认无 traceback/class name。

**Verify**

```bash
.venv/bin/python -m pytest tests/cli/test_016_startup_projection.py tests/cli/test_render.py tests/cli/test_commands.py -q
```

## Task 6 — 补齐 deterministic U1 产品场景

**Files**

- Create: `tests/reference/test_016_first_agent_1_0.py`
- Modify only if Red proves necessary: `agent/cli/app.py`, `agent/runtime/loop.py`,
  `agent/continuity/restart.py`, or their authoritative owners

**Steps**

1. 通过公开 CLI/adapter projection 组合已有 fixtures，覆盖 owner preference 跨重启/correct/forget、
   pause→restart→resume→cancel、multiple candidates、unknown outcome、production adapter failure、Web
   missing-key/outage、16 次 no-progress 与 progress-reset。
2. 每个 safety-critical case 同时断言 durable state、Provider/Web send count、file/process effect count 和
   completion status；不能只做 source-shape assertion。
3. 增加最后一笔成功 `read_file` read-back 已闭合全部 mandatory evidence 的 Red：Runtime 使用同一
   evidence registry 确定性收尾且零额外 Provider send；process/Web/effect result、模型 prose、未准入或
   未满足的 Web/process obligation 不能触发收尾。
4. 增加 false-blocked Red：correction 后未准入的 filesystem criterion 仍要求写入工具；已写 artifact 只缺
   exact read-back 时仍要求 `read_file`。模型不能把失败预读或可修复 evidence gap 终结为 blocked。
5. 增加 repair-budget Red：两个坏 Provider 响应之间有 durable accepted tool batch/GoalProgress 时预算重置；
   没有合法中间响应的连续坏输出仍按既有上限 fail closed。
6. 只有某项 Red 证明现有 owner 不满足冻结行为时，才对该 owner 写更窄的 reproducer并做最小 Green。
7. 重跑 012—015 reference tests，证明 016 只是产品收束，没有改变既有 hard gate。

**Verify**

```bash
.venv/bin/python -m pytest tests/reference/test_016_first_agent_1_0.py -q
.venv/bin/python -m pytest tests/reference -q
```

## Task 6A — Typed intent gate：普通问答、Goal 与澄清先分流

**Files**

- Modify: `agent/runtime/contracts.py`
- Modify: `agent/runtime/state.py`
- Modify: `agent/runtime/context_control.py`
- Modify: `agent/runtime/context.py`
- Modify: `agent/runtime/loop.py`
- Modify: `agent/provider/normalize.py`
- Modify: `tests/continuity/test_entry_routing.py`
- Modify: `tests/provider/test_continuity_control.py`
- Modify: `tests/kernel/test_context_manager.py`
- Modify: `tests/continuity/test_checkpoint_v2.py` only if Red proves round-trip coverage is missing

**Interfaces**

- Consumes: existing `AgentRuntime.run_turn`, `InteractionState`, `ControlReceipt`, `GoalDraftProposal`,
  `DirectResponse` and `ClarificationRequest`.
- Produces: closed `BeginAnswer(correlation_id)` control with wire kind `begin_answer`, plus
  `accept_begin_answer(state, control) -> ConversationState`. It reuses
  `InteractionState.ANSWERING`; no new loop, Provider route or checkpoint schema.

**Vertical Red→Green slices**

1. Initial no-Goal context exposes zero product tools/context sources and advertises exactly the answer/Goal/clarify
   controls. Prove Red through `KernelContextManager.build`, then minimally gate existing projections.
2. Accepting `begin_answer` persists one correlation-bound receipt and `ANSWERING`; the same run rebuilds context with
   read-only tools/context sources, never effectful tools or `goal_proposal`. Prove Red through `AgentRuntime.run_turn`,
   then add the typed control, shared decoder and reducer.
3. A grounded answer can read and finish without Goal/effect; a provider attempt to submit `goal_proposal` after
   `begin_answer` is rejected and cannot mint Goal authority.
4. An explicit artifact/edit/run task accepts `goal_proposal` before the first product read, then follows the existing
   Goal/tool/evidence path. Unknown filenames remain discoverable after Goal creation.
5. A genuine direction boundary returns one clarification with zero source/tool/effect; a locally discoverable boundary
   is repaired toward `begin_answer`, not pushed onto the user.
6. Provider normalization, strict/non-strict schema, receipt projection, checkpoint recovery and a fresh user action all
   preserve the closed transition rules. A compatible endpoint's redundant outer GoalDelta binding is normalized only
   when both fields exactly equal the nested binding; partial/stale/forged values fail closed. New user input clears
   transient `ANSWERING`/`CLARIFYING` before reevaluation.
7. Update J5–J9 deterministic and real harness assertions so pass requires the first product read to occur after the
   accepted `begin_answer` or durable Goal, never merely because the model eventually succeeded.

**Verify**

```bash
.venv/bin/python -m pytest tests/continuity/test_entry_routing.py tests/provider/test_continuity_control.py tests/kernel/test_context_manager.py -q
.venv/bin/python -m pytest tests/reference/test_013_everyday_workspace.py tests/reference/test_016_first_agent_1_0.py tests/reference/test_016_e3_harness.py -q
```

## Task 7 — Installed-process 016 E3 与 materialized gate

**Files**

- Create: `scripts/run_016_e3.py`
- Create: `scripts/verify_016_materialized_tree.py`
- Create: `tests/reference/test_016_e3_harness.py`
- Create when U2 passes: `docs/acceptance/016_FIRST_AGENT_1_0_E3_RECEIPTS.json`
- Create: `docs/implementation/016_EXECUTION_LOG.md`

**Steps**

1. 先写 harness contract tests：五个 required 配置全缺时打印 exact NEEDS marker；部分缺配置打印
   `incomplete_config`；可选 non-secret request path 在 U2 明确阻断四字段 guided journey；secret-free
   repr/output；12 journeys/25 closed booleans；真实 adapter 和 installed console entry 必须被实际驱动。
2. runner 构建当前 materialized source，安装到 disposable environment，并在 repo root 外用 subprocess 驱动
   `first-agent`；不直接 import `main` 冒充 U2。
3. harness 只输入冻结的自然语言、当前提示短回答、J11 correction 和 J12 exit/restart。它不得替 Runtime
   规划；closed oracle 从 state/file/process/send facts 重算 claims。
4. Web profile 必须由 installed `first-agent setup-web` 生成；真实 Web 只能去固定 Tavily endpoint；model
   只能去显式 base URL；两者 `trust_env=False`、no redirect。
5. materialized verifier 显式拒绝 `.env`、`tui/`、private/runtime/credential 输入，验证 source/install identity、
   membership、content、full gate 和 detached receipt schema。Receipt 必须绑定当前 seal/overlay/verifier 与每轮
   installed wheel digest，不能复用旧 root receipt。
6. runner 通过 product-only diagnostic flag 让 model/Web adapter 在调用 HTTP 前追加 payload-free attempt fact，
   并对真实 disclosure、文件/Web/process approval prompt 做 exact bounded 分类；成功响应数不能冒充 send count。
7. U0/U1 全绿且五个 required env name 全缺时输出唯一 NEEDS marker。配置存在时连续跑完整 suite 三次；
   任何失败清零连续计数并输出准确 blocker，不能保存 prompt、正文、绝对路径或 key。

**Verify**

```bash
.venv/bin/python -m pytest tests/reference/test_016_e3_harness.py -q
.venv/bin/python scripts/verify_016_materialized_tree.py --check-membership
.venv/bin/python scripts/verify_016_materialized_tree.py --content
.venv/bin/python scripts/run_016_e3.py
```

## Task 8 — README、交付记录、全量 gates 与 fresh review

**Files**

- Modify: `README.md`
- Modify: `STRATEGY.md`
- Modify: `docs/architecture/CURRENT_CAPABILITY_STATUS.md`
- Modify: `docs/implementation/016_EXECUTION_LOG.md`
- Create after U2: `docs/acceptance/016_FIRST_AGENT_1_0_INDEPENDENT_REVIEW.md`

**Steps**

1. README 首页改为唯一安装命令、`first-agent setup`、可选 `setup-web`、日常启动和准确能力/询问边界；
   高级 capability 移到后面，不把 candidate 写成已交付。
2. 更新 strategy/current status，明确 1.0 的 local-first 范围与尚未提供的整机/浏览器/后台能力。
3. 运行 touched tests、reference suite、materialized membership/content/control seal（若 verifier 定义）、
   `git diff --check`、全量 ruff 和全量 pytest；任何 timeout、截断或无 exit code 都重跑。
4. fresh independent review 从冻结 design/E3 出发检查 diff、完整 gate 输出、三轮 receipt、secret/runtime denylist
   和 README claim；reviewer 不继承 executor pass。修复后重跑所有受影响 gates。
5. 只有 U0-U3 全部成立才把 docs/status 晋级 accepted/delivered；否则执行日志记录唯一真实 blocker。

**Final verify**

```bash
git diff --check
.venv/bin/ruff check .
.venv/bin/python -m pytest -q -rx
.venv/bin/python scripts/verify_016_materialized_tree.py --check-membership
.venv/bin/python scripts/verify_016_materialized_tree.py --content
```

## Stop Conditions

- **Complete**：U0/U1、连续三轮 U2、fresh U3、文档声明和 materialized tree 全部通过。
- **Needs config**：只有真实 U2 配置缺失时，打印冻结的五变量 marker；不读取其他秘密来源。
- **Product blocker**：实现或真实 journey 失败时继续 Red→Green；不得把 provider/model 自报或阶段性 test
  Green 当作终点。
- **User decision**：只有需求会改变用户意图、权限边界、敏感数据处理或不可逆结果时才停下询问。
