# First Agent 全局只读审计报告

日期：2026-05-27  
模式：`audit_only`  
范围：只读审计；本报告是本轮唯一写入产物。未修改代码、未修改既有文档、未调用真实 API、未读取真实私有资料、未提交、未 push、未 tag。

## 1. Executive Verdict

**结论：项目已经明显收敛，但还不能称为“真正闭环 / 强可用”。**

当前主线已经从“多入口、多 profile、多 env 暗线”收敛到 `config/config.yaml`、`PROJECT_STATUS`、`PROGRESS_LEDGER`、`AUTO_RUN_WORKFLOW` 这一组事实源；runtime 仍基本是一条 `core.chat -> run_main_loop -> provider/tool/memory/subagent branch point` 的统一路径；fake/local 与 real provider 也没有明显分裂成两套 runtime。

但是有三个问题会让下一个 Coding Agent 再次走偏：

1. **本地 `config/config.yaml` 是 tracked 且 dirty。** 本轮没有读取其内容，但从 `git status -sb` 与 `git diff --stat` 可以确认它有未提交改动。这是 P1 级安全/发布风险，因为该文件被定义为当前唯一推荐配置入口，且可能承载真实 key。
2. **active docs 仍存在互相冲突的当前状态叙述。** `docs/PROJECT_STATUS.md` 与 `docs/PROGRESS_LEDGER.md` 基本可信，但 root `README.md`、`docs/00-overview/CURRENT_CAPABILITY_STATUS.zh.md`、`docs/06-audit/CURRENT_AUDIT_STATUS.zh.md`、`docs/05-testing-dogfood/TEST_MATRIX.zh.md`、`docs/design/config-legacy-sunset-contract.md` 仍会把 agent 引向旧的 401、`.env`、`request_path/auth_scheme/api_key_env` 或 manual dogfood 路径。
3. **latest real API dogfood 是有价值的 smoke evidence，但报告过于乐观。** 报告标注 commit 为 `ffa5677`，而当前 HEAD 是 `f06ceb4`，且关键修复在后续提交；部分 PASS 只证明“模型有输出”或“事件计数出现”，没有证明交互、确认、resume、真实 streaming、memory 持久化 recall 等用户级能力。

本轮没有发现必须立即停修的 P0。但在继续做新能力或更大 real API dogfood 前，建议先处理 P1：**配置安全边界 + active docs/source-of-truth 收敛 + dogfood evidence 口径修正。**

## 2. Current State Assessment

### 2.1 PROJECT_STATUS 是否准确

`docs/PROJECT_STATUS.md` 是目前最可靠的项目状态入口。它准确记录了：

- 当前阶段是 post-real API dogfood 的维护/清理态。
- 推荐配置入口是 `config/config.yaml`。
- legacy env/profile/request-path/auth-scheme 不是推荐路径。
- latest dogfood 是 20 case，结果为 19 PASS / 1 CONCERN / 0 FAIL。
- `auto-run` 必须先读 `PROJECT_STATUS`、`PROGRESS_LEDGER`、`AUTO_RUN_WORKFLOW`。

主要问题是它 **偏乐观**：

- 没有显式记录 `config/config.yaml` 当前 dirty 且 tracked 的发布风险。
- 没有指出 root `README.md` 和多个 active docs 仍在传播旧状态。
- 没有说明 latest dogfood report 的 commit/evidence 与当前 HEAD 有断层。
- “real API dogfood passed” 容易被误读成用户级全能力已通过。

建议状态：保留为事实源，但下一轮必须补足“已知文档冲突”和“dogfood evidence 限制”。

### 2.2 PROGRESS_LEDGER 是否足够接续

`docs/PROGRESS_LEDGER.md` 能让下一个 Coding Agent 理解最近几轮工作：

- provider config 收敛；
- report/plan 产出；
- ISSUE-002 empty response 已修；
- ISSUE-001 event counting 被降级为 harness limitation；
- auto-run workflow 加固；
- P3 backlog 仍有 provider identity、interactive harness、provider profile docs cleanup。

缺口：

- 没有记录本轮 repo safety check 里的 dirty tracked config 风险。
- 没有把 active docs 冲突列为 P1/P2。
- 没有给出“哪些 real dogfood case 是 direct provider smoke，哪些是 runtime E2E”的边界。

结论：可接续，但不足以独立防止 agent 走偏。需要与 `PROJECT_STATUS` 和 `AUTO_RUN_WORKFLOW` 一起读。

### 2.3 会误导 auto-run 的文档

以下文件仍在 active tree 内，不属于 archive，但内容会误导：

- `README.md`
  - 仍称当前阶段是 2026-05-25 的历史状态。
  - 链接多个已归档或不存在的 audit/plan/dogfood 文档。
  - 仍推荐 `.env` API key。
  - 仍描述 `auth_scheme/request_path` 作为兼容模式配置。
  - 仍把 manual human dogfood 当成最高优先级。
- `docs/00-overview/CURRENT_CAPABILITY_STATUS.zh.md`
  - 仍称 real provider 当前不可用，原因是 401。
  - 与 2026-05-27 real API dogfood 状态冲突。
- `docs/06-audit/CURRENT_AUDIT_STATUS.zh.md`
  - 仍称 Cleanup-Only / Awaiting Manual Human Dogfood。
  - 仍把 DeepSeek 401 当成关键当前事实。
- `docs/05-testing-dogfood/TEST_MATRIX.zh.md`
  - 测试基线和 real provider dogfood 命令过期。
  - 仍包含旧 `.env` loader 思路。
- `docs/design/config-legacy-sunset-contract.md`
  - 仍把 legacy env-based secret/config loading 路径写成迁移合同的一部分。
  - 与 `docs/design/unified-project-config-contract.md` 和当前实现冲突。
- `docs/archive/README.md`
  - 归档说明本身过期，仍声称某些旧文档保留在原路径或作为 canonical 参考。

### 2.4 docs/archive 与 active docs 是否分清

分清了一半。

好的部分：

- `docs/audit/README.md` 明确当前状态应看 `PROJECT_STATUS` 与 `PROGRESS_LEDGER`。
- `docs/dogfood/README.md` 正确指向 active dogfood report。
- `docs/plans/README.md` 能列出 active plans 与 archive 边界。

问题：

- root `README.md` 仍引用已归档或不存在的文档。
- `docs/archive/README.md` 的归档边界描述已过期。
- active docs 内仍有旧 “CURRENT” 文档与最新事实源冲突。

### 2.5 当前 next recommended loop 是否合理

`PROJECT_STATUS` 推荐“Docs cleanup / Config sunset / Interactive dogfood harness”方向是合理的，但优先级应调整：

1. 先处理 P1：`config/config.yaml` tracked dirty 的安全边界。
2. 然后做 active docs/source-of-truth 修复，避免 auto-run 继续读到冲突状态。
3. 再做 interactive dogfood harness，补足 y/n、resume、interrupt、tool confirmation、memory confirmation、streaming/progress 覆盖。

## 3. AutoRun Assessment

### 3.1 是否先读 PROJECT_STATUS / PROGRESS_LEDGER / AUTO_RUN_WORKFLOW

是。`.claude/commands/auto-run.md` 的 startup checklist 明确要求先读：

- `docs/PROJECT_STATUS.md`
- `docs/PROGRESS_LEDGER.md`
- `docs/dev/AUTO_RUN_WORKFLOW.md`
- latest dogfood report
- latest remediation plan

这点已经从流程上加固。

### 3.2 是否能根据任务类型选择 loop 起点

基本可以。`AUTO_RUN_WORKFLOW` 与 `.claude/commands/auto-run.md` 都有 task type routing：

- `audit_only`
- `doc_cleanup`
- `bug_fix`
- `dogfood`
- `remediation`
- `architecture_cleanup`
- `release/ship`

对本轮这种 `audit_only`，它应该进入“只读证据收集 + 输出 report”的路线，而不是 TDD 或修复路线。

### 3.3 是否仍可能机械从头开始

风险降低，但未消失。

原因：

- root `README.md` 和多个 “CURRENT” 文档仍会把 agent 拉回旧状态。
- `docs/archive/README.md` 归档边界描述过期。
- latest dogfood report 的 PASS 口径过乐观，agent 可能把 smoke evidence 当成 strong E2E evidence。

### 3.4 是否有 hard stop

有。hard stop 覆盖了：

- dirty repo；
- secret risk；
- real external service；
- broad refactor；
- legacy provider restoration；
- archive 文档被当成当前事实；
- fake/local 证据冒充 real API；
- P0/P1/P2 blocker。

缺口：需要更明确地写入 **不得读取 `config/config.yaml` 真实 key 内容，只能检查 tracked/dirty/staged 状态**。当前有 no secret output 与 no config commit，但还不够精确。

### 3.5 是否有 progress recording rule

有。`AUTO_RUN_WORKFLOW` 要求每个 loop 至少更新一个事实源或报告。

本轮暴露一个边界问题：`audit_only` 同时要求“只读”和“生成报告”。建议把规则表述为：

- `audit_only` 不修改既有代码/文档；
- 允许写入一个新审计报告作为唯一产物；
- 不允许顺手修复被审计文件。

### 3.6 是否能防止 legacy config/provider/profile 复活

流程上可以防止大多数复活：

- `.claude/commands/auto-run.md` 明确禁止推荐 `MY_FIRST_AGENT_LLM_PROVIDER`、`FIRST_AGENT_PROVIDER_PROFILE`、`request_path`、`auth_scheme`、`api_key_env`。
- `docs/dev/AUTO_RUN_WORKFLOW.md` 明确 `config/config.yaml` 是推荐入口。
- provider tests 已覆盖 examples 不再包含 `api_key_env` 等旧字段。

但是 active docs 仍有旧内容，代码中 legacy fallback 也仍存在。短期内还需要 guard tests 扩展到 root README 与 active design/status docs。

### 3.7 是否能防止简单配置过度工程化

大方向可以。当前 workflow 反复强调：

- no profile system resurrection；
- no request_path/auth_scheme user surface；
- no provider over-engineering；
- adapter 内部处理协议细节。

剩余风险来自旧设计文档和 legacy code names，而不是 auto-run 本身。

### 3.8 是否能支撑夜间长任务 dogfood / 修复 / 重跑

部分可以，但还不够稳。

可用部分：

- 有 task routing；
- 有 stop conditions；
- 有 progress ledger；
- 有 dogfood report/plan 路径；
- 有禁止 real API/secret 的 hard stop。

不足：

- 缺少交互式 real/fake dogfood harness。
- latest dogfood script 本身有较多 direct provider smoke case，不适合作为夜间全能力回归唯一依据。
- 长任务结束后的 source-of-truth 更新还依赖 agent 自觉，没有统一 evidence packet schema。

## 4. Runtime Architecture Assessment

### 4.1 是否仍是一条统一 runtime 主流程

大体是。主路径仍是：

```text
agent.core.chat()
  -> build provider/tool/memory/session/checkpoint context
  -> agent.loop.run_main_loop()
  -> agent.model_call.call_model()
  -> provider adapter
  -> runtime action / tool / memory / subagent branch points
```

没有看到 fake runtime 与 real runtime 各自拥有独立主循环的证据。

### 4.2 fake/real 是否共享主路径

基本共享。`build_model_provider_from_env()` 先读 unified config，再落到 legacy fallback，最终构造 `FakeProvider`、OpenAI-compatible、Anthropic-compatible 或 native OpenAI provider。fake 与 real 都进入 `core.chat()` 和 `run_main_loop()`。

需要注意：latest dogfood 中不少 case 直接调用 provider，而不是 agent runtime。因此“fake/real runtime 共享路径”不能从全部 20 case PASS 直接推出，只能从代码结构和部分 runtime case 推出。

### 4.3 tool / memory / subagent / checkpoint 是否是有限 branch point

是有限 branch point，但边界已经偏重。

- Tool 执行集中在 `agent/tool_executor.py` 与 `agent/tool_registry.py`。
- Memory explicit retain / proposal / recall / forget 分布在 `core.py`、`loop.py`、memory modules。
- SubAgent L0 delegation 在 `agent/subagent_system/*`，但 `core.py` 有 CLI/NL shortcut。
- Checkpoint/resume 在 `agent/checkpoint.py` 与 `agent/session.py`，tool/memory confirmation 会写 checkpoint。

风险是 `loop.py` 的 turn-end hook 同时触发大量 RuntimeAction：tool noop、memory propose、skill select、subagent delegate、trace、summary 等。它像一个 evidence fanout，而不只是业务 branch point。

### 4.4 core.py / loop.py 是否过大

是。

- `agent/core.py`：约 1172 行。混合了 chat API、CLI meta command、memory interaction、subagent shortcut、planning context、dispatcher setup、session/checkpoint handling。
- `agent/loop.py`：约 839 行。`run_main_loop()` 本体不算复杂，但 turn-end runtime action hook 过大，承担了太多 evidence、demo、trace、summary 逻辑。

短期不建议大重构，但需要把“用户真实路径”和“turn-end evidence/probe”分得更清楚。

### 4.5 runtime action / event / summary 边界是否清晰

schema 层相对清晰，但语义层不够清晰。

好的部分：

- `RuntimeActionType` 是有限枚举。
- dispatcher 有 `route_from_runtime_loop`、target proof 等约束。
- action log 与 run summary 可以提供统一观察面。

问题：

- 一些 turn-end action 是 `_safe_noop` 或 probing，不代表用户请求真的完成。
- `summary` 可能把 hook evidence 统计成能力完成证据。
- dogfood harness 通过 event name 或 event count 判定 PASS，容易高估。

### 4.6 direct handler 冒充 E2E 的风险

仍存在。

典型位置：

- `core.py` 里 `show memories`、`forget memory`、`show subagents`、`delegate to subagent` 等 CLI shortcut 在进入 main loop 前直接处理。
- memory confirmation reply 也可以在 main loop 前处理。
- dogfood report 中部分 provider case 根本不经过 runtime。

这些 shortcut 可以保留，但不能被当成完整 E2E runtime evidence。

### 4.7 command shortcut 第二能力平面风险

有中等风险。

目前 shortcut 主要服务 CLI/demo/confirmation，尚未变成完整第二 runtime。但如果继续添加命令式 handler，很容易形成两套能力平面：

- 一套在 model/tool/memory runtime；
- 一套在 `core.py` 的字符串 shortcut。

下一轮应明确：shortcut 只能是 thin adapter 或 debug command，不能承载核心能力语义。

## 5. Provider/Config Assessment

### 5.1 config/config.yaml 是否成为唯一推荐入口

实现上基本是。`agent/provider/simple_config.py` 已经把当前推荐路径收敛为：

```yaml
provider:
  enabled: true
  type: anthropic_compatible | openai | openai_compatible
  base_url: ...
  api_key: ...
  model: ...
```

适配器内部决定：

- `anthropic_compatible` 默认 `/v1/messages`；
- OpenAI-compatible 默认 chat completions；
- auth scheme 不再暴露给普通用户。

问题是 repo 状态上 `config/config.yaml` tracked 且 dirty，这会破坏“推荐入口”的安全性。

### 5.2 legacy env/profile/request_path/auth_scheme/api_key_env 残留

残留仍在三层存在：

1. 代码 fallback：
   - `agent/provider/config.py`
   - `agent/provider/profiles.py`
   - `agent/provider/factory.py`
2. diagnostics：
   - legacy diagnostic still suggests env-based config loading in some paths（已迁移至 unified config，legacy 路径仅作 fallback）。
3. active docs：
   - `README.md`
   - `docs/design/config-legacy-sunset-contract.md`
   - 部分旧 testing/status docs。

短期可以保留 code fallback，但必须把“legacy only / not recommended”边界写得更硬，并把 active docs 的推荐路径修掉。

### 5.3 provider adapter 是否暴露协议细节给用户

当前 unified config 路径基本不暴露。协议细节在 adapter/default 内处理。

但 legacy diagnostic 和旧 docs 仍可能向用户暴露 `request_path/auth_scheme/api_key_env`。这是文档与 fallback 风险，不是 unified path 的主要实现问题。

### 5.4 anthropic_compatible 是否仍有错误使用 /v1/chat/completions 的风险

当前 unified path 风险较低。`anthropic_compatible` 默认使用 `/v1/messages`，并通过 Anthropic-style adapter 发送 `messages` 请求。

风险来自旧文档或 legacy config。如果用户被旧文档引导手动设置 `request_path`，仍可能回到错误路径。

### 5.5 diagnostics 是否可能误导用户

可能。

好的部分：

- unified diagnostics 能显示 inline key 已设置但 redacted。
- config missing 时推荐 `config/config.yaml`。

问题：

- legacy diagnostic 仍会建议 env-based config loading（已迁移至 unified config，legacy 路径仅作 fallback）。
- `unsupported_auth_scheme` 的建议仍是修改 `provider.auth_scheme`。
- `build_model_provider_from_env()` 命名本身仍暗示 env 是主入口。

### 5.6 当前 config 方案是否足够简单

方案本身足够简单；风险在工程卫生：

- `config/config.yaml` 不应以可能含真实 key 的 tracked dirty 文件存在。
- example 和 real local config 的边界需要更强。
- legacy fallback 需要从“可被误读的入口”降级为“兼容旧用户，不出现在普通路径”。

## 6. Real API Dogfood Assessment

### 6.1 real API dogfood 是否可信

可信，但只能作为 **real provider smoke + partial runtime dogfood**。

可信点：

- 确实记录了 20 case；
- 覆盖 basic chat、中文、多轮、工具、memory、safety、config、trace 等类别；
- latest report 和 remediation plan 互相引用；
- 后续 commit 修复了 empty response bug。

限制：

- 报告 commit 是 `ffa5677`，当前 HEAD 是 `f06ceb4`，关键 fix 在后续提交，报告不能直接证明当前 HEAD 的完整状态。
- 多数 A/H/I case 是 direct provider call，不是 runtime E2E。
- 一些 PASS 只验证非空输出，没有语义断言。
- B/C/D case 依赖 event count，可能把 no-op/probe evidence 计为能力完成。

### 6.2 20 cases 覆盖是否足够

不足以证明用户级可用。它足够证明：

- provider 可以真实返回文本；
- basic safety prompt 有 refusal；
- runtime 没有在部分路径上崩；
- summary/trace 能产出一些 evidence。

它不足以证明：

- interactive confirmation；
- resume/interrupt；
- tool confirmation；
- memory confirmation；
- streaming UI/progress；
- persistent recall；
- complex multi-turn tool/memory/subagent chain。

### 6.3 19 PASS / 1 CONCERN 是否过于乐观

是。

例子：

- `I1` help case 被 PASS，但输出仍是通用 Claude/assistant 帮助，不是 First Agent 产品帮助。
- `I7` config path 被 PASS，但输出仍提到 generic config / `.env` 风格内容。
- `H5` streaming 只是调用 provider 非 streaming 接口写诗，不能证明 streaming。
- `C4` show memories 在 C1 之后仍返回“暂无已保存的记忆”，却被标成 PASS。
- `B1` tool calling 的 evidence 可能来自 turn-end tool pipeline/noop，而不一定是用户要求的真实工具 side effect。

更准确的表述应是：**19 non-failing smoke outcomes / 1 known concern / multiple untested user-critical flows**。

### 6.4 缺少的真实覆盖

缺少以下交互式覆盖：

- `y/n` confirmation；
- resume；
- interrupt；
- tool confirmation approve/deny；
- memory confirmation approve/deny；
- checkpoint reload；
- streaming/progress UI；
- long-running dogfood restart；
- tool result after confirmation；
- memory retain -> recall -> forget 的同 session 与跨 session 检查。

### 6.5 silent failure / empty response / max loop / summary overclaim 风险

仍有残留风险。

- empty response bug 已有修复 commit，但 latest dogfood report 的 commit 标注不能证明当前 HEAD。
- max loop risk 需要更复杂 case 才能覆盖。
- summary overclaim 是当前最大 evidence 风险：summary/event count 可能统计了 probe/noop，而不是用户可见能力。
- direct provider smoke case 可能掩盖 runtime presentation bug。

### 6.6 是否应再做更复杂 real API dogfood

应该，但顺序是：

1. 先修 docs/source-of-truth 与 config safety。
2. 先建立 fake/local interactive harness，覆盖 stdin/stdout、confirmation、resume、interrupt。
3. 再显式授权 real API 运行同一 harness 的小样本 sweep。

不建议现在直接扩大 real API dogfood，因为 evidence 口径还不够硬。

## 7. Capability Coverage Matrix

| 能力 | maturity | evidence | major gap | next action |
|---|---|---|---|---|
| Basic chat | REAL_DOGFOOD_READY | A1-A8 direct provider smoke；部分 runtime chat；empty response fix 已提交 | 多数 case 不经 runtime；帮助/产品语义弱 | 增加 runtime-level real chat smoke，并区分 provider smoke 与 runtime E2E |
| Tool calling | REAL_DOGFOOD_READY | B1/H2 有 tool-related runtime evidence；tool registry/executor 边界清楚 | event count 可能统计 noop/probe；缺真实 side effect 断言 | 建立 fake-first tool E2E，验证 requested tool、confirmation、result、summary 一致 |
| Tool confirmation | FAKE_READY | `tool_executor` 有 confirmation checkpoint 逻辑；tests 覆盖部分路径 | latest real dogfood 未覆盖 y/n approve/deny | interactive harness 覆盖 approve/deny/resume |
| Memory proposal / retain / recall / forget | FAKE_READY | memory runtime、confirmation、store、C1/C4 case 存在 | C1 concern；C4 显示无记忆；real persistence/recall 不强 | 做 retain -> confirm -> recall -> forget 的交互式 fake/real 分层 dogfood |
| SubAgent delegation | FAKE_READY | L0 local deterministic subagent system；core shortcut 与 runtime action handler 存在 | 仍是 local fake/deterministic；不是真实 child LLM delegation | 保持 L0，不扩 L1；先修 evidence 口径 |
| Checkpoint / resume | FAKE_READY | `checkpoint.py`、`session.py`、tool/memory confirmation checkpoint 逻辑存在 | real interactive resume/interrupt 未覆盖 | subprocess harness 覆盖 checkpoint save/load、resume、interrupt |
| Streaming / progress | FAKE_READY | provider abstraction 支持 streaming capability；events 有 delta/progress | H5 不是真 streaming；OpenAI-compatible streaming fail-closed | fake streaming UI/progress test；real streaming 单独授权后测 |
| Run summary / trace | FAKE_READY | run summary、trace、runtime action log 存在；H/I case 有输出 | summary 可能 overclaim turn-end probes/noops | 标记 evidence type：business action vs probe/noop |
| Safety refusal | REAL_DOGFOOD_READY | G2 real API safety refusal PASS | 只覆盖简单恶意请求；无 tool/policy escalation case | 加 2-3 个 tool/memory/subagent 边界 refusal case |
| Config/onboarding | FAKE_READY | unified config implementation、examples tests、docs contract | dirty tracked config；active docs 仍推荐旧路径 | 配置安全与 docs cleanup 作为下一轮 P1 |
| AutoRun self-steering | FAKE_READY | auto-run command/workflow 已要求事实源导航、task routing、hard stop | 未真实夜间长任务 dogfood；会被 stale docs 干扰 | 用 fake long-task dogfood 验证 stop/progress/report 行为 |
| Docs/source-of-truth | FAKE_READY | `PROJECT_STATUS`、`PROGRESS_LEDGER`、source-of-truth tests | root README/current docs 冲突；guard tests 不覆盖所有 active docs | 修 active docs，并扩 source-of-truth tests |

## 8. Code Quality / Maintainability Findings

### 8.1 已经过大的文件

- `agent/core.py`：约 1172 行。主 chat API、CLI shortcuts、memory/subagent/planning/session/dispatcher setup 混在一起。
- `agent/loop.py`：约 839 行。主循环之外的 turn-end runtime action hook 过重。
- `agent/memory_fs_store.py`：约 875 行。持久化、索引、锁、atomic writes、查询职责较多。
- `agent/tool_executor.py`：约 574 行。仍可接受，但确认、checkpoint、display policy、classification 混合。
- `scripts/real_api_dogfood_sweep.py`：约 813 行。provider call、runtime call、case spec、evaluation、markdown/report generation 混合。
- `scripts/dogfood_e2e_runtime.py`：约 2570 行。过于 stateful，不适合作为长期清晰入口。
- `scripts/dogfood_complex_real_api.py`、`scripts/dogfood_phase6_llm_consolidation.py` 等 dogfood scripts 也偏大。

### 8.2 职责混杂

- `core.py`
  - 同时处理 user-facing chat、debug/CLI command、memory explicit interaction、subagent shortcut、session resume、dispatcher construction。
  - direct command shortcut 是未来第二能力平面的主要风险。
- `loop.py`
  - 主循环本应协调 model/tool progression，但现在 turn-end hook 还承担大量 capability probe/evidence。
- `provider/diagnostics.py`
  - unified diagnostics 与 legacy diagnostics 并存，输出建议可能互相冲突。
- dogfood scripts
  - 混合真实 API、runtime harness、case definition、stateful output、report rendering。

### 8.3 可能该删或降级的 legacy 代码

短期不要盲删，但应进入 legacy sunset loop：

- provider profile fallback；
- env-based provider loader public naming；
- `request_path/auth_scheme/api_key_env` user-facing diagnostic suggestions；
- root README 中旧 DeepSeek/401/manual dogfood 路线；
- active docs 中旧 config migration contract。

### 8.4 测试 taxonomy 仍混乱

当前测试已经很多，但 taxonomy 仍有问题：

- source-of-truth tests 没覆盖 root README。
- active docs stale scan 允许“legacy/deprecated”上下文，可能放过实际误导性推荐。
- dogfood report 的 PASS/CONCERN/FAIL 口径与 pytest tests 的 pass/fail 不是一套语义。
- runtime action/event/summary tests 需要区分 business evidence 与 probe/noop evidence。
- provider config tests 很有价值，但也意味着测试可能读取 `config/config.yaml` 内容；在含真实 key 的本地环境应谨慎运行。

### 8.5 scripts/dogfood 太 stateful 的位置

- `scripts/real_api_dogfood_sweep.py`
  - 会创建输出目录与写 report；
  - `call_agent_chat()` 修改 `HOME`，且 old HOME 为空时不会恢复；
  - case evaluator 与 report generator 耦合；
  - hardcoded model/provider narrative。
- `scripts/dogfood_e2e_runtime.py`
  - 文件巨大，长期维护成本高。
- 多个历史 dogfood scripts 仍在 scripts 根目录，容易让 agent 选择过期入口。

### 8.6 会让下一个 Coding Agent 再次走偏的地方

- root `README.md` 的旧当前状态。
- `docs/00-overview/CURRENT_CAPABILITY_STATUS.zh.md` 和 `docs/06-audit/CURRENT_AUDIT_STATUS.zh.md` 的旧 “CURRENT” 命名。
- `docs/design/config-legacy-sunset-contract.md` 与 unified config contract 冲突。
- latest dogfood report 的 optimistic PASS。
- `core.py` direct handler 很容易吸引 agent 继续添加 shortcut。
- `loop.py` turn-end hook 很容易被继续扩成 capability demo bus。

## 9. Red-Team Findings P0/P1/P2/P3

### P0：必须立刻停修

无。

本轮没有发现已 staged secret、真实 API 被调用、危险命令、tag/push、或必须立即停止开发的证据。

### P1：下一轮必须修

1. **`config/config.yaml` tracked 且 dirty**
   - evidence：`git status -sb` 显示 `M config/config.yaml`；`git diff --stat` 显示该文件 2 行变化。
   - 本轮未读取内容。
   - 风险：真实 API key 或本地私有 provider config 可能进入 commit。
   - 下一步：明确 local real config 与 repo sample 的边界；commit 前必须先处理。

2. **active docs 当前事实冲突**
   - root `README.md`、`CURRENT_CAPABILITY_STATUS.zh.md`、`CURRENT_AUDIT_STATUS.zh.md`、`TEST_MATRIX.zh.md` 仍指向旧状态。
   - 风险：auto-run 虽要求读 facts，但一旦继续读 active docs，仍可能走回 DeepSeek 401、manual dogfood、`.env`、request_path。

3. **latest real API dogfood evidence 口径过强**
   - report commit 与 HEAD 不一致；
   - direct provider smoke 被混入 full capability dogfood；
   - 部分 PASS 缺语义断言。
   - 风险：把 smoke success 当成 USER_USABLE/STRONG readiness。

### P2：应该进入近期 Big Loop

- interactive dogfood harness 缺失：y/n、resume、interrupt、tool confirmation、memory confirmation、streaming/progress 未真实覆盖。
- `core.py` / `loop.py` 过大，且 direct shortcut 与 turn-end evidence fanout 边界不够清晰。
- provider diagnostics 仍可能输出 legacy 建议。
- source-of-truth tests 未覆盖 root README 与所有 active “CURRENT” docs。
- dogfood scripts 过大、过 stateful，且有 HOME mutation 风险。
- memory C1/C4 evidence 不一致，不能证明 retain/recall 用户级闭环。
- run summary 可能 overclaim no-op/probe events。

### P3：可记录，不阻塞

- provider identity / “我是 Claude” / product context 不强。
- OpenAI-compatible streaming 当前 fail-closed。
- `main.py` 等 CLI adapter 仍有薄层债务。
- memory consolidation 与 L2 长期策略未进入真实 dogfood。
- SubAgent 仍是 L0 deterministic local executor。
- docs 中还有一些历史 roadmap/plan 命名不够清晰。

### WONTFIX / 当前不该修

- 不要为 provider identity 立刻做 persona 大改。
- 不要恢复 legacy env/profile/request_path/auth_scheme 作为主路径。
- 不要重写为 LangGraph 或引入大框架。
- 不要恢复 FakeProvider NLU 复杂行为。
- 不要现在做 SubAgent L1-L5、真实 child LLM、多 agent orchestration。
- 不要做 RAG/vector DB/production sandbox/SaaS 化。
- 不要为了 dogfood 扩大真实 API 调用，除非用户显式授权。

## 10. Recommended Next Big Loops

### Loop 1：Source-of-Truth Repair & Guard Hardening

- **why now**：active docs 仍互相冲突，是 auto-run 走偏的最大非代码风险。
- **scope**：
  - 修 root `README.md` 当前状态与链接；
  - 修或降级 `CURRENT_CAPABILITY_STATUS.zh.md`、`CURRENT_AUDIT_STATUS.zh.md`、`TEST_MATRIX.zh.md`；
  - 修 `docs/design/config-legacy-sunset-contract.md` 与 archive boundary；
  - 扩 `tests/test_docs_source_of_truth.py` 覆盖 root README、active current docs、stale 401/manual dogfood/request_path/api_key_env patterns。
- **out of scope**：runtime 行为修改；真实 API；provider 新功能。
- **expected deliverables**：active docs 与 PROJECT_STATUS 一致；source-of-truth tests 捕获旧路径复活。
- **tests/gates**：`tests/test_docs_source_of_truth.py`、link check、`rg` stale pattern scan、`git diff --check`。
- **safe-to-auto-run**：是，但必须避开 `config/config.yaml` 内容。
- **stop conditions**：发现真实 secret、需要处理 tracked config 内容、或需要删除大量历史文档。
- **likely effort**：中。
- **risk**：低到中。

### Loop 2：Config Safety & Legacy Sunset

- **why now**：当前唯一推荐入口 `config/config.yaml` 自身 tracked dirty，直接威胁发布安全。
- **scope**：
  - 明确 `config/config.yaml` 与 examples/local real config 的边界；
  - 确保真实 key 不会被提交；
  - 降级 legacy profile/env/request_path/auth_scheme 用户可见面；
  - 修 diagnostics 中会推荐 legacy 字段的路径；
  - 保留必要 backward compatibility，但不作为推荐入口。
- **out of scope**：新增 provider；真实 API dogfood；大规模 provider framework 重写。
- **expected deliverables**：配置入口简单、安全、文档一致；legacy 只存在于兼容层。
- **tests/gates**：provider config tests、secret guard tests、source-of-truth tests、`git diff --check`、ruff/pytest targeted。
- **safe-to-auto-run**：部分安全。涉及 dirty config 时必须 hard stop，让用户确认处理方式；不能读取或打印 key。
- **stop conditions**：需要查看真实 key 内容；需要改用户本地私密配置；需要真实 API。
- **likely effort**：中。
- **risk**：中。

### Loop 3：Interactive Dogfood Harness

- **why now**：当前 real dogfood 没覆盖用户最容易踩坑的交互路径。
- **scope**：
  - 基于 subprocess stdin/stdout 建立 fake-first harness；
  - 覆盖 y/n、tool confirmation、memory confirmation、resume、interrupt、checkpoint reload、streaming/progress；
  - 输出 structured report，明确 fake/local、real provider smoke、runtime E2E 的证据类型；
  - 后续在用户显式授权时跑少量 real API version。
- **out of scope**：修 runtime 大架构；扩真实 API case 数；新功能。
- **expected deliverables**：可重复交互式 dogfood；每个 case 有 prompt、expected events、expected output、state assertions。
- **tests/gates**：fake harness pytest、subprocess case outputs、no real API default、no private data、`git diff --check`。
- **safe-to-auto-run**：fake/local 部分安全；real API 部分不安全，必须显式授权。
- **stop conditions**：需要真实 API key；需要读取 private config；case 发现 P1/P0 runtime failure。
- **likely effort**：中到大。
- **risk**：中。

### Loop 4：Runtime Evidence Diet / Overclaim Hardening

- **why now**：summary/event/action log 已经能产出很多证据，但语义口径不够硬。
- **scope**：
  - 区分 business action、probe、noop、diagnostic evidence；
  - 调整 run summary，避免把 turn-end probe 统计成用户能力完成；
  - dogfood evaluator 改为检查 evidence type 与 state assertion；
  - 文档化 direct provider smoke vs runtime E2E。
- **out of scope**：大拆 `core.py`/`loop.py`；改 provider 协议；真实 API。
- **expected deliverables**：dogfood PASS 更难、更可信；summary 不 overclaim。
- **tests/gates**：runtime action/event tests、dogfood evaluator tests、existing runtime tests、`git diff --check`。
- **safe-to-auto-run**：是，fake-first。
- **stop conditions**：需要重写主循环；现有 tests 大面积语义不清。
- **likely effort**：中。
- **risk**：中。

### Loop 5：Runtime Hub Slimming（Surgical Only）

- **why now**：`core.py` 和 `loop.py` 过大，会诱导后续继续往 hub 塞逻辑。
- **scope**：
  - 只做行为保持型抽取；
  - 把 CLI meta command、memory explicit interaction、subagent shortcut 分到薄 use-case；
  - turn-end runtime action builder 与 main loop 分离；
  - 加 regression tests 确认行为不变。
- **out of scope**：重写 runtime；新框架；改变 user-visible 行为。
- **expected deliverables**：主路径更薄，shortcut 边界更清楚。
- **tests/gates**：targeted runtime tests、full pytest、ruff、`git diff --check`。
- **safe-to-auto-run**：不建议夜间全自动；适合分小 patch 执行。
- **stop conditions**：diff 扩大到 broad refactor；需要改变 public behavior；tests 无法建立保护网。
- **likely effort**：大。
- **risk**：中到高。

## 11. What Not To Work On

近期不要做：

- provider persona / identity polish；
- “我是 Claude” 类输出修复；
- broad runtime rewrite；
- LangGraph / workflow engine migration；
- 恢复 provider profiles/env/request_path/auth_scheme 主路径；
- FakeProvider NLU 扩写；
- SubAgent L1-L5 或真实 multi-agent；
- MCP server 真实连接；
- RAG/vector DB；
- production sandbox / SaaS / deployment；
- 新 provider adapter；
- 未授权 real API sweep；
- tag/release/push。

这些不是当前收敛瓶颈。当前瓶颈是事实源一致性、配置安全、dogfood evidence 可信度、runtime evidence 口径。

## 12. Final Recommendation

**不要把当前项目标为 STRONG 或完全 USER_USABLE。更准确的状态是：核心架构已收敛，real provider smoke 已跑通，fake/local runtime 证据较丰富，但 active docs 与 dogfood evidence 仍不足以支撑强可用宣称。**

推荐下一步顺序：

1. 处理 `config/config.yaml` tracked dirty 安全边界。
2. 做 Source-of-Truth Repair & Guard Hardening。
3. 做 Config Safety & Legacy Sunset。
4. 建 interactive dogfood harness。
5. 在证据口径变硬之后，再做小规模授权 real API dogfood rerun。

本轮未运行测试、ruff 或 pytest。原因是本轮是 `audit_only`，且 provider/config tests 可能读取本地 `config/config.yaml` 内容；为避免接触真实 key 或私有配置，本轮只做文件级、状态级、文档级与代码结构级只读审计。
