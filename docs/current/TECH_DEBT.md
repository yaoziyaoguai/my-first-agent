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

---

> 说明：以下**不入**技术债（按规则 3，仍是 S1 必解项，留在 `S1_GOAL_GAP.md`）：
> - G-15 `config/config.yaml` 被 git 跟踪（config 卫生 / 未来密钥泄露风险，must_fix_for_s1；经独立审计确认当前为占位符、**非**已暴露真实密钥、**无需轮换**）
> - G-16 README/quickstart 可用性（must_fix_for_s1）
> - G-07b checkpoint 大结果 resume 形态（unknown_needs_audit，先审计）
