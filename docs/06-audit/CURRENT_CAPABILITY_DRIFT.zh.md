# RuntimeDecisionFrame / capability docs drift (V4 audit)

> 状态：draft — V4 audit output, doc-only
> 创建日期：2026-06-11
> 本轮范围：只读三份文档 + 一份 code source；不改代码、不 git commit production

## 1. 四方源

| 源 | 路径 | 角色 |
|---|---|---|
| Source-of-truth | `agent/runtime_decision_frame.py` | enum 定义 + 当前 status |
| Design doc | `docs/design/runtime-decision-spine.md` | Loop 1.1 实施设计 |
| Status doc | `docs/PROJECT_STATUS.md` | 当前实现地图 |
| Capability doc | `docs/00-overview/CURRENT_CAPABILITY_STATUS.zh.md` | 当前能力摘要 |

## 2. Drift table

行格式：`(branch_point) → source-of-truth | design | PROJECT_STATUS | CAPABILITY`

| Branch | SoT | Design | PROJECT_STATUS | CAPABILITY |
|---|---|---|---|---|
| tool.gate | PARTIAL / FAKE_LOCAL | PARTIAL / FAKE_LOCAL | Mediator → tool_executor | "Tool pipeline Mediator → tool_executor" |
| tool.invoke | PARTIAL / FAKE_LOCAL | PARTIAL / FAKE_LOCAL | "evidence-only marker, 不直接调用" | mentioned via Tool pipeline row |
| tool.result | PARTIAL / FAKE_LOCAL | PARTIAL / FAKE_LOCAL | not called out | not called out |
| memory.recall | PARTIAL / FAKE_LOCAL | PARTIAL / FAKE_LOCAL | "Memory v0 … safe evidence" | "Memory v0 … 不做 raw write" |
| memory.propose | PARTIAL / FAKE_LOCAL | PARTIAL / FAKE_LOCAL | not called out | not called out |
| memory.retain | PARTIAL / FAKE_LOCAL | PARTIAL / FAKE_LOCAL | "explicit retain" | "explicit retain" |
| skill.select | NOT_READY / UNIT_DIRECT_CALL | NOT_READY / GUARD_TEST | "active skill lifecycle" | "Skill 仍是实验性能力" |
| skill.apply | STUB / DOCS_DESIGN | STUB / DOCS_DESIGN | not called out | not called out |
| mcp.discover | DEFERRED / DOCS_DESIGN | DEFERRED / DOCS_DESIGN | "adapter skeleton / harness-aware" | "不默认连接真实外部 MCP server" |
| mcp.invoke | DEFERRED / DOCS_DESIGN | DEFERRED / DOCS_DESIGN | not called out | not called out |
| subagent.delegate | FAKE_DEMO / FAKE_LOCAL | FAKE_DEMO / FAKE_LOCAL | "v0 contract / child 不直接执行" | "L1/L2 legacy route frozen" |
| checkpoint.save | PARTIAL / FAKE_LOCAL | PARTIAL / FAKE_LOCAL | not called out | not called out |
| checkpoint.resume | PARTIAL / FAKE_LOCAL | PARTIAL / FAKE_LOCAL | not called out | not called out |
| trace.summary | PARTIAL / FAKE_LOCAL | PARTIAL / FAKE_LOCAL | "evidence_recorder 统一写入" | mentioned via Evidence row |

## 3. 关键 drift

1. **evidence_level drift on skill.select**: SoT enum is `UNIT_DIRECT_CALL`, design doc says `GUARD_TEST`. Spine is the design that drove the enum, so SoT is post-design drift. If spine wins, source needs fix; if SoT wins, spine is outdated.

2. **terminology drift on subagent**: PROJECT_STATUS uses "v0 contract"; CAPABILITY_STATUS uses "L1/L2 legacy route frozen"; design uses "FAKE_DEMO (L0)". Same concept, three labels. Need canonical term ("FAKE_DEMO" or "L0 deterministic") decided and referenced everywhere.

3. **silent gap on checkpoint + mcp.invoke + memory.propose + tool.result**: PROJECT_STATUS and CAPABILITY_STATUS do not name these. SoT + design both assign PARTIAL/DEFERRED, but the user-facing docs omit them. Risk: external readers think capability exists when it is PARTIAL.

4. **MCP coverage split**: PROJECT_STATUS describes orchestrator path but does not say DEFERRED; CAPABILITY_STATUS says "不默认连接真实外部" (implicit DEFERRED). Both docs lack the explicit "DEFERRED" status word that SoT provides.

5. **skill lifecycle wording**: PROJECT_STATUS says "active skill lifecycle 由 runtime 管" — implies non-trivial runtime involvement. SoT says `skill.select = NOT_READY`, `skill.apply = STUB`. Wording oversells.

## 4. 来源优先级建议

不在本 round 修复；留给下一轮 source-of-truth repair spike。提议：

1. `agent/runtime_decision_frame.py` 是 primary。
2. `runtime-decision-spine.md` 与 `PROJECT_STATUS.md` 应分别明确 ref 到 SoT。
3. `CURRENT_CAPABILITY_STATUS.zh.md` 是 user-facing summary，必须显式引用 status word（READY/PARTIAL/DEFERRED/NOT_READY/FAKE_DEMO/STUB）而不是用 narrative 描述。
4. PROJECT_STATUS.md 不应使用 "active" / "lifecycle" 等隐含 PRODUCTION_PATH 的词修饰 PARTIAL/DEFERRED/STUB 子系统。

## 5. 不做

- 不改任何 production code。
- 不改 RuntimeDecisionFrame 枚举。
- 不改 PROJECT_STATUS 现状文本（属于 source-of-truth repair spike）。
- 不改 CURRENT_CAPABILITY_STATUS 现状文本（属于 source-of-truth repair spike）。
- 不强求 docs alignment — 仅记录 drift。

---

## 6. Memory consolidation / emergence (V6 — addendum)

| Aspect | Source | Wording | Drift |
|---|---|---|---|
| consolidation overall | `agent/memory_consolidation.py:13` | "⛔ FROZEN (2026-05-25): Memory Consolidation pipeline 整体冻结" | OK |
| consolidation engine | `agent/memory_consolidation_engine.py:6` | "⛔ FROZEN (2026-05-25)" | OK |
| consolidation llm | `agent/memory_consolidation_llm.py:6` | "⛔ FROZEN (2026-05-25)" | OK |
| consolidation review | `agent/memory_consolidation_review.py:6` | "⛔ FROZEN (2026-05-25)" | OK |
| emergence module | `agent/memory_emergence.py:1` | "Phase 7 — W5 Emergence Detection Foundation" | 没有显式 "env-gated" 状态词；仅说 "foundation" |
| emergence runtime gate | `agent/memory_runtime_hooks.py:143` | "默认关闭，必须显式设置 MEMORY_EMERGENCE_ENABLED=true" | 与 RuntimeDecisionFrame 没有枚举对齐 |
| RuntimeDecisionFrame 枚举 | `agent/runtime_decision_frame.py` | 只列 `memory.recall/retain/propose`；没有 `memory.emergence` | emergence 不在 canonical status vocabulary |
| CURRENT_CAPABILITY_STATUS row | `docs/00-overview/CURRENT_CAPABILITY_STATUS.zh.md` | 只提 "Memory v0 explicit retain" | emergence 不出现于 user-facing 摘要 |
| PROJECT_STATUS row | `docs/PROJECT_STATUS.md` | "Memory v0 … 不做 raw write 或 auto-adoption" | emergence / consolidation pipeline 状态词缺位 |

### 关键 V6 drift

1. **status-word drift on emergence**: RuntimeDecisionFrame enum 不覆盖 `memory.emergence`，
   emergence 是 env-gated + fail-closed 的 dispatcher 边界，没有 READY/PARTIAL/DEFERRED
   词标注；外部 reader 看到 "Phase 7 foundation" 可能误以为接近 READY。

2. **CURRENT_CAPABILITY_STATUS 与 PROJECT_STATUS 都未提 emergence / consolidation pipeline**：
   只有模块顶部 "⛔ FROZEN" 注释，缺乏 user-facing 状态词。

3. **consolidation pipeline 5 个 ⛔FROZEN 模块**没有集中索引——要靠读者自己 grep 才能
   确认 pipeline 范围。RuntimeDecisionFrame 也没有 `memory.consolidation` 枚举。

### V6 不做

- 不写代码修改。
- 不引入 `memory.emergence` 枚举（属于 source-of-truth repair spike）。
- 不删除 / 改写 frozen consolidation 代码。
- 不修改 emergence runtime hook 行为。
