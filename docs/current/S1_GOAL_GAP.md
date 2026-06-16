# S1 Goal Gap — Active To-Do List

> 权威文档（docs/current/）。这是 S1 的真实差距/待办清单，基于：`S1_CURRENT_CODE_ARCHITECTURE_AUDIT.zh.md` + `S1_GOAL.md` + 本轮只读代码审计（证据见 `_tmp_s1_baseline/code_audit_notes.md`）。
>
> 规则（见 AGENTS.md）：不删未完成 gap；不为「看起来完成」改写 gap；完成需证据；确认 S1 不解决的重要项转入 `TECH_DEBT.md` 并标注 TD-ID。
>
> Status ∈ {satisfied, partially_satisfied, unknown_needs_audit, s1_blocker, s1_gap, defer_to_tech_debt, out_of_scope}
> Blocking ∈ {release_blocker, must_fix_for_s1, should_fix_for_s1, optional_for_s1, s2_or_later}

---

### G-01 — 可运行入口
- **Layer**: L1
- **S1 requirement**: 单一可运行入口 + 统一 runtime loop。
- **Current evidence**: `main.py:637 main()` → `main.py:335 main_loop()` → `main.py:195 _run_chat_for_backend()` → `agent/core.py:763 chat()` → `agent/loop.py run_main_loop`。
- **Status**: satisfied
- **Gap**: 无。
- **Blocking level**: must_fix_for_s1（已满足）
- **Needed action**: 无。
- **Verification**: `.venv/bin/python main.py --plain` 可启动。
- **Decision**: 保留为 S1 基线既有能力。

### G-02 — Fake provider 稳定回归
- **Layer**: L1
- **S1 requirement**: FakeProvider 可作为确定性回归基线。
- **Current evidence**: `agent/provider/fake_provider.py:306 FakeProvider`；`tests/golden_e2e/*` 用 `FakeProvider()` 跑全链路；`pytest.ini testpaths=tests`。
- **Status**: satisfied
- **Gap**: 无（acceptance 子集尚未"指定"，见 G-17）。
- **Blocking level**: must_fix_for_s1（已满足）
- **Needed action**: 无。
- **Verification**: `.venv/bin/python -m pytest tests/golden_e2e -q` 通过。
- **Decision**: 作为 AC-1 候选。

### G-03 — Real provider smoke
- **Layer**: L1
- **S1 requirement**: RealProvider 可作为真实 smoke 路径。
- **Current evidence**: real adapters `agent/provider/{anthropic_http,anthropic_native,openai_http,openai_native}.py`，由同一工厂构造；`tests/test_provider_real_smoke.py`、`tests/test_real_mcp_flight.py`（需 key/网络）。
- **Status**: partially_satisfied
- **Gap**: 缺一个 **key-safe** 的真实 smoke 步骤文档。应配合 G-15：真实 key 用 gitignored `.env` / `config/config.local.yaml` 提供，而非写进被跟踪的 `config/config.yaml`。
- **Blocking level**: should_fix_for_s1
- **Needed action**: 用 gitignored `config/config.local.yaml` 写一份 real smoke 步骤（文档动作，未来授权 run 执行；本轮不处理密钥）。
- **Verification**: 一次 real run 产出 `sessions/<id>/events.jsonl` 且 `provider_type` 为真实类型。
- **Decision**: 留在 S1 gap；执行前先解 G-15。

### G-04 — Fake/Real same spine
- **Layer**: L1
- **S1 requirement**: 进入 core 后 fake/real 共享同一 spine。
- **Current evidence**: `agent/provider/protocol.py:77` 薄协议；`factory.py:18/44-45`；`agent/loop.py:249/690`「loop 不读 provider_type」；`agent/core.py:1158-1159` RT-01「fake/real 共享同一 evidence path」；`agent/provider/legacy_adapter.py:29-63` 把 legacy client 转发到同一 provider。
- **Status**: satisfied
- **Gap**: 无（运行层对照证据待补，见 AC-2）。
- **Blocking level**: release_blocker（核心原则，已满足）
- **Needed action**: 无（建议补 same-spine 对照验收，归入 G-17）。
- **Verification**: fake run 与 real run 的 events.jsonl 经过同一事件集合。
- **Decision**: S1 核心不可回退原则。

### G-05 — Provider factory/protocol 边界薄
- **Layer**: L1
- **S1 requirement**: provider 边界足够薄、可替换。
- **Current evidence**: `protocol.py:77` 仅 `create/stream` + 三个能力位；`factory.py:18` 单一分派工厂。
- **Status**: satisfied
- **Gap**: 无。
- **Blocking level**: should_fix_for_s1（已满足）
- **Needed action**: 无。
- **Verification**: `tests/test_provider_contract.py`。
- **Decision**: 保留。

### G-06 — Planning/compress legacy client facade
- **Layer**: L1
- **S1 requirement**: planning/compress 仍回到同一 provider，不另起一条模型路径。
- **Current evidence**: `agent/core.py:171 build_default_model_client()` 返回 (provider, ProviderBackedClient)；`core.py:1369 loop_ctx.client.messages.create`；`legacy_adapter.py:29-63` 转发到同一 `provider.create()`。
- **Status**: defer_to_tech_debt（TD-002）
- **Gap**: planning/compress 仍是 legacy `client.messages.create` 形态，尚未迁移到 provider-neutral `create()`（虽指向同一 provider）。
- **Blocking level**: optional_for_s1
- **Needed action**: 迁移到 provider-neutral 接口（延期）。
- **Verification**: planner/compress 不再 import legacy_adapter。
- **Decision**: 同 provider，S1 可接受；记 TD-002。

### G-07 — Context/Memory/State/Checkpoint 基本可用
- **Layer**: L2
- **S1 requirement**: 上下文/memory/state/checkpoint 达 S1 基本可用。
- **Current evidence**: recall `core.py:1065`、retain `core.py:961`、turn-end `loop.py:285-435`；压缩配对安全 `agent/memory.py:220/261-263`；state `state.py:13/192`；checkpoint save `core.py:1005/1322/1641/1707`、resume `session.py:405`（`main.py:731` 无条件）。
- **Status**: partially_satisfied
- **Gap**: (a) checkpoint 对 >2048B 大 tool_result 做摘要（`evidence_persistence.py`），resume 后该形态是否 API-valid **未验证**；(b) 并存的 `agent/context.py:36` compress_history 无配对守卫（非主路径）。
- **Blocking level**: should_fix_for_s1
- **Needed action**: (a) 验证大结果 resume 形态 → 见下方 unknown 项；(b) → TD-003。
- **Verification**: 构造 >2048B tool_result，save→resume→下一轮模型调用不报错。
- **Decision**: 主体可用；(a) 拆为 G-07b 待审计，(b) 记 TD-003。

### G-07b — Checkpoint 大结果 resume 形态
- **Layer**: L2
- **S1 requirement**: checkpoint/resume 不破坏后续模型调用。
- **Current evidence**: `agent/evidence_persistence.py` summarize（content_persisted=false）；resume 路径未在本轮逐行验证。
- **Status**: unknown_needs_audit
- **Gap**: 大 tool_result 摘要后 resume 的消息形态是否被 API 接受未知。
- **Blocking level**: should_fix_for_s1
- **Needed action**: 只读+一次本地复现验证（未来 run）。
- **Verification**: 同 G-07 verification。
- **Decision**: 先审计再判定 satisfied / 转 TD。

### G-08 — Tool/Policy/Dispatcher/Mediator 基本可用
- **Layer**: L3
- **S1 requirement**: 工具调用、policy gate、dispatcher、mediator 基本可用。
- **Current evidence**: `tool_registry.py:43/142/205/399`；`tool_runtime_mediator.py:225 mediate`；`tool_executor.py:204`；`runtime_integration/tool_gate.py:32`（两 provider 模式一致）；`TOOL_INVOKE` 仅记 evidence、执行在 executor。
- **Status**: satisfied
- **Gap**: 无顶层统一 policy 开关（逻辑分散，但功能在）。
- **Blocking level**: must_fix_for_s1（已满足）
- **Needed action**: 无。
- **Verification**: `tests/runtime_integration/test_tool_pipeline_l3_completion.py`。
- **Decision**: S1 基线既有能力。

### G-09 — Tool result 进入 context/state/evidence
- **Layer**: L3
- **S1 requirement**: tool result 可靠进入 context 与 task state，不被压缩/丢失。
- **Current evidence**: `agent/conversation_events.py:116 append_tool_result`（role=user, tool_result block, 全量 content），`tool_executor.py:546/680` 无条件追加；`state.task.tool_execution_log` 留副本；压缩配对守卫 `memory.py:220`。
- **Status**: satisfied（context/state 路径）；evidence 保真见 G-10/G-11
- **Gap**: 进入 context/state 稳健；evidence 侧只存 safe_summary+size，pending-tool 的 `events.jsonl tool_output=""`（mediator `_route_result:1263`）。
- **Blocking level**: should_fix_for_s1
- **Needed action**: pending-tool 日志保真 → TD-004。
- **Verification**: 工具执行后 `state.conversation.messages` 含对应 tool_result block。
- **Decision**: context/state satisfied；日志保真记 TD-004。

### G-10 — Evidence 支撑 S1 可观测性
- **Layer**: L3
- **S1 requirement**: evidence 能证明一次 run 的路径骨架。
- **Current evidence**: `logger.py:150`→`agent_log.jsonl`；`event_log.py:153`→`sessions/<id>/events.jsonl`；`evidence_recorder.py:728 record_evidence`（含 provider_type、tool gate/invoke/result、memory、checkpoint 事件）。
- **Status**: partially_satisfied
- **Gap**: 路径骨架可证；模型/工具正文不存（见 G-11）。
- **Blocking level**: should_fix_for_s1
- **Needed action**: 指定 S1 可观测最小集（哪些事件必须出现）。
- **Verification**: 一次 run 的 events.jsonl 含 provider_type + tool 事件 + checkpoint。
- **Decision**: 最小可观测已具备；正文保真见 G-11。

### G-11 — Evidence 不持久化模型 request/response 正文
- **Layer**: L3
- **S1 requirement**: 判定「不存正文」属 blocker / gap / debt。
- **Current evidence**: `evidence_recorder.py` 仅 safe_summary + result_size，`content_persisted=false`。
- **Status**: defer_to_tech_debt（TD-001）
- **Gap**: 无法从 evidence 逐字节复原模型交互。
- **Blocking level**: optional_for_s1
- **Needed action**: full-fidelity capture 留 S2+（TD-001）。
- **Verification**: n/a（S1 用骨架级可观测）。
- **Decision**: 非 S1 blocker；最小可观测足够，记 TD-001。

### G-12 — 最小多步任务状态 / progress tracking
- **Layer**: L4
- **S1 requirement**: 存在最小多步任务状态与进度跟踪，可 checkpoint。
- **Current evidence**: legacy Plan 路径 active——`state.py:192 TaskState`（current_plan/current_step_index/status）、`state.py:13 KNOWN_TASK_STATUSES`；`agent/tools/meta.py:45 mark_step_complete` + `config.py:208 STEP_COMPLETION_THRESHOLD=80`；`task_runtime.py:48 is_current_step_completed`；`transitions.py:639 advance_current_step_if_needed`；checkpoint 持久化全量 task state（`checkpoint.py:324`）。ActionPlan/Scheduler 路径 dormant（见 G-13）。
- **Status**: partially_satisfied
- **Gap**: 进度=checkpoint 快照，无独立 durable task ledger；ActionPlan 路径未接入。
- **Blocking level**: should_fix_for_s1
- **Needed action**: 明确「legacy Plan 路径 = S1 的最小多步任务状态」；独立 durable ledger 留 S2+。
- **Verification**: 一个 ≥2 步任务能 plan→advance→done 并 resume（AC-5）。
- **Decision**: legacy Plan 路径作为 S1 最小能力；durable ledger=s2_or_later。

### G-13 — Scheduler 当前 dormant
- **Layer**: L5
- **S1 requirement**: S1 不接入 Scheduler。
- **Current evidence**: `agent/action_scheduler.py` 文件级 dormant 注释；`agent/loop.py:728` 默认 None / `loop.py:1007-1028` 注入 seam；`main.py` 零引用；`tests/test_scheduler_boundary_l2.py` 钉死 main.py 0 引用。
- **Status**: out_of_scope
- **Gap**: 无（S1 by design 不接入，也不删除）。
- **Blocking level**: s2_or_later
- **Needed action**: 保持 dormant；本轮不接入、不删除。
- **Verification**: `tests/test_scheduler_boundary_l2.py` 通过。
- **Decision**: S1 范围外；维持现状。

### G-14 — MCP / Skill / SubAgent 边界
- **Layer**: L5
- **S1 requirement**: 扩展能力边界清楚（active/configurable/dormant/demo-only 明确）。
- **Current evidence**: MCP configurable 默认关（`main.py:587-589 MY_FIRST_AGENT_MCP_ENABLE`，dry-run 默认开）；SubAgent V0 configurable 默认关（`subagent_routing_flag.py:29`），默认 local_fake stub（`subagent_system/executor.py:12/26`），L0 注册/L1-L2 frozen（`phase1_hook.py:170-187`），V0 wiring 源码注明未完成；Skill 实验性（`skill_system/` + `runtime_integration/skill_lifecycle.py`，README:46）。
- **Status**: partially_satisfied
- **Gap**: 边界清楚（满足 S1 要求）；全量生产激活非 S1 目标。
- **Blocking level**: optional_for_s1（边界）/ s2_or_later（激活）
- **Needed action**: S1 仅确认并固定边界；不推进实现。
- **Verification**: 默认 run 不启用 MCP / 不真实委派（local_fake）。
- **Decision**: 边界 satisfied；激活留 S2+。

### G-15 — config/config.yaml 被 git 跟踪（config 卫生 / 未来密钥泄露风险）
- **Layer**: Cross-cutting / Security (config hygiene)
- **S1 requirement**: 安全配置基线——后续随时会被填入真实 key 的本地配置文件不应被 git 跟踪；仓库不得提交真实 provider 密钥。
- **Current evidence**: `git ls-files config/` 显示 `config/config.yaml` **被跟踪**；`.gitignore` 仅忽略 `.env`、`config/config.local.yaml`，**未**忽略 `config/config.yaml`。**独立审计（本轮）已确认**：当前被跟踪的 `api_key` 值长 13、结构 `AA-AAAAAAA_AA`，是**占位符**，**不是真实 provider 密钥**；工作树与 HEAD 一致；config.yaml 历史中从未出现 ≥30 字符的长 key（`ever_long_key: no`）；真实长度 `sk-` 串仅出现在 `tests/` 脱敏测试夹具；真实密钥当前在 gitignored 的 `.env`。
- **Status**: s1_gap
- **Gap**: `config/config.yaml`（用户做真实 provider 测试时会填真实 key 的文件）被 git 跟踪且未 gitignore → **将来可能误提交真实 key**。注意：当前**没有**已暴露的真实密钥。
- **Blocking level**: must_fix_for_s1
- **Needed action**: 将 `config/config.yaml` 从 git 跟踪移除（`git rm --cached`）并加入 `.gitignore`；仓库保留 `config/config.example.yaml`（已存在）或等价模板供拷贝为本地配置；真实 key 仅存放于 gitignored `.env` / `config/config.local.yaml`。**不要求轮换密钥**（无已暴露真实密钥）。（本轮按指令不处理密钥本体、不改 config，仅按授权修正本 gap 的严重级别表述。）
- **Verification**: `git ls-files config/config.yaml` 为空；tracked tree 无真实长度 provider key；`.gitignore` 含 `config/config.yaml`。
- **Decision**: 严重级别由 release_blocker（已暴露真实密钥/需轮换）**降级**为 must_fix_for_s1（config 卫生 / 未来泄露风险）。仍留在 `S1_GOAL_GAP.md`（S1 必修），不入 `TECH_DEBT.md`。审计文档 `S1_CURRENT_CODE_ARCHITECTURE_AUDIT.zh.md` §0/§10.1 的「真实密钥/需轮换」强表述本轮不改，待后续授权 run 调和；当前权威口径以本 gap + `WORK_LOG.md` 为准。

### G-16 — README / quickstart 可用性
- **Layer**: Cross-cutting / UX
- **S1 requirement**: 使用者可按 README/quickstart 跑起来，文档导航有效。
- **Current evidence**: README:17-44 有 quickstart；但 README:5/52-56 导航指向 `docs/PROJECT_STATUS.md`、`docs/00-overview/...`、`docs/README.zh.md`、`docs/dev/...`、`docs/06-audit/README.md` —— 这些已迁入 `docs/history/`，链接失效；README:9 自述「developer prototype，不是面向普通用户的产品」。
- **Status**: s1_gap
- **Gap**: 用户面运行说明与「基本可用产品版」不一致；文档导航失效。
- **Blocking level**: must_fix_for_s1
- **Needed action**: 更新 README 导航指向 `docs/current/`、重述为 S1 基线。（本轮**禁改 README**，仅登记。）
- **Verification**: README 所有文档链接解析到存在的文件。
- **Decision**: S1 必修；本轮不改，留 gap。

### G-17 — 测试分层（acceptance vs harness）
- **Layer**: Cross-cutting / Tests
- **S1 requirement**: 明确哪些是 S1 acceptance tests，哪些只是 seam/harness/demo。
- **Current evidence**: acceptance 候选 `tests/golden_e2e/*`（全链路 + FakeProvider）、`tests/runtime_integration/test_phase1_real_core_loop.py`、`test_mcp_l3_real_core_loop.py`、`tests/smoke/test_first_usable_task_e2e.py`；seam/harness `test_b7_*`、`test_architecture_boundaries.py`、直接 `dispatcher.route` 测试。
- **Status**: partially_satisfied
- **Gap**: 尚未"指定"S1 acceptance 子集与 same-spine 对照验收。
- **Blocking level**: should_fix_for_s1
- **Needed action**: 在 S1 收尾前指定 acceptance 测试集（文档动作）。
- **Verification**: 指定集合在 fake 模式确定性通过。
- **Decision**: 留 S1 gap。

### G-18 — S 与旧 v1/v2/v3 命名区隔
- **Layer**: Cross-cutting / Governance
- **S1 requirement**: 避免旧 v1/v2/v3 命名误导 S 系列目标。
- **Current evidence**: 代码含 `v0.x`/`Phase N`/`Loop N`/`B7` 等命名；`S_ROADMAP.md` 与本 `S1_GOAL.md` 已显式声明 S≠代码 v。
- **Status**: s1_gap
- **Gap**: 命名混淆风险（已由 S 文档收口，但代码标签仍在）。
- **Blocking level**: should_fix_for_s1
- **Needed action**: 维持 S 文档对版本语义的唯一权威；不在代码层做改名（非本轮）。
- **Verification**: 后续文档不再用代码 v 标签当 S 目标。
- **Decision**: 由 `S_ROADMAP.md`/`S1_GOAL.md` 持续收口。

---

## 汇总

| 状态 | 数量 | Gap |
|---|---|---|
| satisfied | 4 | G-01, G-04, G-05, G-08 |
| partially_satisfied | 6 | G-07, G-09, G-10, G-12, G-14, G-17 |
| unknown_needs_audit | 1 | G-07b |
| s1_blocker | 0 | （无；原 G-15 经独立审计降级，见下） |
| s1_gap | 3 | G-15, G-16, G-18 |
| defer_to_tech_debt | 2 | G-06 (TD-002), G-11 (TD-001) |
| out_of_scope | 1 | G-13 |

S1 必修项（must_fix_for_s1）：G-15（`config/config.yaml` 改为不跟踪 + gitignore；**非**已暴露密钥、**无需轮换**）、G-16（用户面运行说明）。本轮按指令未改 config / README，仅按授权修正 G-15 的严重级别表述。原审计文档（本轮不在允许修改清单内）§0/§10.1 仍有「真实密钥/需轮换」强表述，待后续授权 run 调和；当前权威口径以本文件 + `WORK_LOG.md` 为准。
