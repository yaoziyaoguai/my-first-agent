# Technical Debt Register

> 权威文档（docs/current/）。跨阶段技术债登记。

## 规则

1. **TECH_DEBT.md 不是未完成任务垃圾桶。** 不得因为「今天没做完」就往这里塞。
2. 只有同时满足以下条件的问题才能进入：
   - 对项目重要；
   - 已确认 **S1 不解决**；
   - 因范围、风险、成本、依赖、时机或产品优先级原因延期；
   - 后续 S2/S3/Sn 需要重新评估。
3. 如果某问题仍是 S1 必须解决的问题，**不得**放入本文件，必须留在 `S1_GOAL_GAP.md`。
4. 每条 debt 必含字段：ID、Date、Stage introduced、Area、Debt、Why not in S1、Current impact、Risk level、Revisit trigger、Status、Evidence。

## 模板

```
### TD-XXX — <一句话标题>
- ID: TD-XXX
- Date: YYYY-MM-DD
- Stage introduced: S1
- Area: <L1/L2/L3/L4/L5/Cross-cutting>
- Debt: <具体技术债>
- Why not in S1: <为何 S1 不解决>
- Current impact: <当前影响>
- Risk level: <low/medium/high>
- Revisit trigger: <何时重新评估>
- Status: <open/in_review/resolved>
- Evidence: <file:line / 审计章节 / commit>
```

---

## 登记项

### TD-001 — Evidence 不持久化模型 request/response 正文
- ID: TD-001
- Date: 2026-06-16
- Stage introduced: S1
- Area: L3 (Evidence)
- Debt: `record_evidence` 仅写 `safe_summary` + `result_size`（`content_persisted=false`），不持久化模型/工具的原始 request/response 正文，无法从 evidence 逐字节复原模型交互。
- Why not in S1: S1 只要求路径骨架级可观测（provider_type + tool gate/invoke/result + memory + checkpoint 事件链），已具备；full-fidelity capture 涉及存储与脱敏复杂度，超出基线。
- Current impact: 无法仅凭 evidence 复现模型对话正文；调试需结合实时日志。
- Risk level: medium
- Revisit trigger: 当产品需要可复现的模型交互审计 / 合规留痕时。
- Status: open
- Evidence: `agent/evidence_recorder.py:728`；`S1_CURRENT_CODE_ARCHITECTURE_AUDIT.zh.md` §8；gap G-11。

### TD-002 — Planning/compress 仍用 legacy client facade
- ID: TD-002
- Date: 2026-06-16
- Stage introduced: S1
- Area: L1 (Runtime Spine)
- Debt: planning/compress 路径仍走 `loop_ctx.client.messages.create`（`ProviderBackedClient` facade），未迁移到 provider-neutral `provider.create()`。
- Why not in S1: facade 已转发到**同一** provider（`legacy_adapter.py:29-63`，`core.py:171`），fake/real same-spine 不受影响；迁移属重构风险，非 S1 必需。
- Current impact: 同一 provider 存在两种调用形态，认知/维护成本略高。
- Risk level: low
- Revisit trigger: 当 planner/compress 做重构、或要删除 `legacy_adapter.py` 时。
- Status: open
- Evidence: `agent/provider/legacy_adapter.py`；`agent/core.py:171/1369`；gap G-06。

### TD-003 — 并存的 agent/context.py compress_history 无配对守卫
- ID: TD-003
- Date: 2026-06-16
- Stage introduced: S1
- Area: L2 (Context)
- Debt: `agent/context.py:36 compress_history`（`recent=messages[-6:]`）无 tool_use/tool_result 配对守卫，与主路径 `agent/memory.py:220`（有守卫）并存。
- Why not in S1: 主链路 `core.py` 用 `agent/memory.py`，不 import `agent/context.py`；该并存实现是否被任何次要入口触达 **unknown**，主路径无风险。
- Current impact: 若某次要入口走 `agent/context.py`，可能 orphan tool_result（当前未确认可达）。
- Risk level: low
- Revisit trigger: 当整合 context 模块、或确认 `agent/context.py` 被某入口调用时。
- Status: open
- Evidence: `agent/context.py:36` vs `agent/memory.py:220/261-263`；gap G-07(b)。

### TD-004 — Pending-tool 的 events.jsonl tool_output 为空
- ID: TD-004
- Date: 2026-06-16
- Stage introduced: S1
- Area: L3 (Evidence)
- Debt: `execute_pending_tool` 未写 `turn_context[tool_use_id]`，导致 mediator `_route_result`（`tool_runtime_mediator.py:1263`）对 pending tool 写入 `events.jsonl` 的 `tool_output=""`。
- Why not in S1: 工具结果仍正确写入 `state.conversation.messages`（`conversation_events.py:116`）与 `state.task.tool_execution_log`；仅 `events.jsonl` 这一处日志保真受影响。
- Current impact: pending-tool 的事件日志缺少 `tool_output` 预览；不影响 context/state/执行正确性。
- Risk level: low
- Revisit trigger: 当增强 events.jsonl 保真 / 排查 pending-tool 事件时。
- Status: open
- Evidence: `agent/tool_executor.py execute_pending_tool`；`agent/tool_runtime_mediator.py:1263`；gap G-09。

### TD-005 — config secret-safety guard 与 G-15 untrack 决策相反
- ID: TD-005
- Date: 2026-06-17
- Stage introduced: S1（由 S1 completion audit 发现）
- Area: Cross-cutting / Tests + Security
- Debt: `tests/test_config_secret_safety.py::test_committed_config_yaml_has_placeholder_key` 断言 `config/config.yaml` **被 git 跟踪且为占位符**；G-15 已按 AC-6 故意 untrack 该文件，导致测试以 `AssertionError: config/config.yaml 未在 git 中追踪` 失败。该 guard 编码的是 G-15 之前的旧策略。
- Why not in S1: 调和该 guard 到 G-15 后的策略是对**安全不变量**测试的语义改写，不在 G-17 acceptance gate 内；在本审计低风险范围内单方面改写安全测试不合适（AGENTS.md：不得弱化/绕过 guard 测试）。
- Current impact: full-suite 失败；**潜在隐患**——失败信息会诱导后续 agent 把 `config/config.yaml` 重新 track 来"修复"测试，从而重新引入 G-15 已消除的 config 卫生风险（当前工作树含真实长度 key）。
- Risk level: medium
- Revisit trigger: 下次把测试套件/安全 guard 对齐到 S1 docs+config 规制时；或在重新评估任何"跟踪 config"策略前。
- Status: resolved（2026-06-17；S1 completion cleanup）
- Resolution: `tests/test_config_secret_safety.py` 已改为验证 G-15 后策略：`config/config.yaml` 不被 git 跟踪且被 `.gitignore` 忽略；`config/config.example.yaml` 作为 tracked template 存在且不含真实 key；`.env` 不被要求恢复或 track。测试只查询 git index / ignore 规则与 tracked templates，不读取本地 ignored `config/config.yaml` 内容。
- Evidence: `tests/test_config_secret_safety.py:68`；G-15（commit 68e7d76）；S1_GOAL.md AC-6；2026-06-17 独立核验 `git ls-files config/config.yaml` 为空、`git check-ignore` 命中 `.gitignore:36`；cleanup verification：`.venv/bin/python -m pytest tests/test_config_secret_safety.py -q -rx` → `9 passed in 0.35s`，`.venv/bin/ruff check tests/test_config_secret_safety.py` → pass。

### TD-006 — 旧 S1-前文档规制 guard 测试族过期失败
- ID: TD-006
- Date: 2026-06-17
- Stage introduced: S1（由 S1 completion audit 发现）
- Area: Cross-cutting / Tests + Docs governance
- Debt: 一组 guard 测试编码了 S1 之前的文档规制（`PROJECT_STATUS.md` 为 source of truth、`docs/00-overview`、`docs/06-audit` Window 闭包文档、README 必须引用 `PROJECT_STATUS.md`）。docs 迁入 `docs/history/`（≤ origin/main）且 README 经 G-16 重写后，这些测试失败：`test_docs_source_of_truth.py`(23)、`test_v6_drift_addendum_boundary.py`(5)、`test_architecture_boundaries.py`(3)、`test_streaming_protocol.py`(1)。其中 `test_root_readme_references_project_status` 由 G-16 删除 README 的 PROJECT_STATUS 引用而新失败，其余多为 FileNotFoundError（既有，origin/main 已存在）。
- Why not in S1: 不在 G-17 acceptance gate 内；把整族 guard 测试对齐到 S1 规制是后续阶段的成体系工作，非低风险审计修复；AGENTS.md 禁止静默弱化 guard 测试。
- Current impact: ~32 个 full-suite 失败（多数在 origin/main 已存在）；遮蔽套件健康度——`pytest -q` 全量为红，尽管被指定的 S1 acceptance gate（G-17）为绿。
- Risk level: low-medium
- Revisit trigger: 把测试套件对齐到 `docs/current` S1 规制时，或后续 docs-governance 阶段。
- Status: open
- Evidence: 2026-06-17 full-suite（37 failed）；相关测试文件未被 S1 commit 修改；`git ls-tree origin/main docs/` 仅 current+history。

### TD-007 — AC-2 运行产物层 same-spine（fake vs real events.jsonl）对照未执行
- ID: TD-007
- Date: 2026-06-17
- Stage introduced: S1（由 S1 completion audit 发现）
- Area: L1 / Verification
- Debt: `S1_GOAL.md §6 AC-2` 要求对照一次 fake run 与一次 real run 的 `sessions/<id>/events.jsonl`，证明二者经过同一事件集合、仅 `provider_type` 不同。real smoke（`tests/test_provider_real_smoke.py`）是 provider + tool_executor 直调测试（源码 L122-130 自述"不是完整 AgentLoop … 不声称 E2E"），**不产生 events.jsonl**；fake 侧（golden_e2e）产生 events.jsonl。因此运行产物层的 fake-vs-real 对照从未执行；same-spine 由 G-04 源码层 + G-03 provider 层证据支撑。
- Why not in S1: 产出 real `events.jsonl` 需要一次受权的 real `core.chat()` 运行 / 真实 provider 调试，超出本审计范围（不做复杂真实调用调试）；G-17 已把 real execution 归入 G-03，G-03 以测试输出为证据。
- Current impact: AC-2 在源码层 + provider 层满足，但在它字面命名的运行产物层未满足；"P0/P1/P2 全部完成"应带此 caveat 阅读。
- Risk level: medium
- Revisit trigger: 当可授权一次 real `core.chat()` 运行产出 `sessions/<id>/events.jsonl`，从而进行文档所述的 fake-vs-real 事件对照时。
- Status: open
- Evidence: `tests/test_provider_real_smoke.py:120-130`；WORK_LOG run 16（"现行 smoke test 不产生 sessions/<id>/events.jsonl"）；S1_GOAL.md §6 AC-2；gap G-04。

---

> 说明：以下 S1 必解项（P0/P1）按规则 3 始终留在 `S1_GOAL_GAP.md`，**未进**技术债；截至 2026-06-17 S1 completion audit，它们**均已 satisfied**（见 `S1_GOAL_GAP.md` §2 / §9 与对应 run）。此处仅作引用索引，状态以 `S1_GOAL_GAP.md` 为准：
> - G-15 `config/config.yaml` untrack + gitignore（**release_blocker / P0 → ✅ satisfied, run 4**；独立审计确认已提交内容为占位符、**非**已暴露真实密钥、**无需轮换**。注：untrack 决策与 guard 测试 `test_config_secret_safety.py` 冲突，见 TD-005）
> - G-16 README/quickstart 可用性（**release_blocker / P0 → ✅ satisfied, run 5**；注：README 重写与 guard 测试 `test_root_readme_references_project_status` 冲突，见 TD-006）
> - G-17 指定 S1 acceptance 集（**release_blocker / P0 → ✅ satisfied, run 10**）
> - G-19 调和审计文档 §0/§10.1 与 G-15 的密钥权威冲突（**release_blocker / P0 → ✅ satisfied, run 11**；纯文档调和，非技术债）
> - G-07b checkpoint 大结果 resume 形态（**must_fix_for_s1 / P1 → ✅ satisfied, run 12**）
