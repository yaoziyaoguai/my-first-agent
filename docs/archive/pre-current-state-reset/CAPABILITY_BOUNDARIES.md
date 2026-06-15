# Capability Boundaries — Skill / SubAgent / Tool / Runtime Facts

**日期**: 2026-06-13
**状态**: current — GE-2 doc-alignment source of truth for capability/runtime facts

---

## 核心定义

**Tool = atomic execution** — 单一、可审计的操作单元。Tool 执行后返回确定结果，不拥有 loop、不调用 LLM、不做规划。当前业务 tool 的 gate/result/evidence 经 `ToolRuntimeMediator` 和 `RuntimeActionDispatcher` 治理，真实 side effect 仍由 mediator 在 gate 通过后调用 `execute_single_tool`。

**Skill = local capability descriptor** — 本地能力描述符，提供渐进式能力发现。Skill 不拥有 Agent loop，调用是 request/result flow。不直接执行工具，不直接写 Memory。当前实现位于 `agent/skill_system/`；`agent/skills/__init__.py` 是 fail-closed tombstone，不是健康的当前能力入口。

**Subagent = parent-controlled delegation** — 父 runtime 控制下的委托执行。Parent 发起、adjudicate 结果、控制作用域。当前 SubAgent V0 已 registered + contract-verified；CLI/NL production call site 只有在 `SUBAGENT_V0_ROUTING_ENABLED` truthy 时路由 V0，默认仍保持 inline-local / `local_fake` rollback/fallback。

---

## 状态词汇

| Term | 含义 |
|---|---|
| `declared` | 文档或 schema 中有目标/概念，不代表 production 已接线。 |
| `registered` | handler / module 可被 dispatcher 或 registry 找到，不代表默认路由。 |
| `routed` | production call site 实际把请求送到该 path。 |
| `default-off` | 功能存在但默认关闭，必须通过显式 flag/env/input 启用。 |
| `dormant` | 代码可构造或测试可注入，但 production 默认不实例化/不调用。 |
| `deferred` | 方向被记录但当前不建设；必须有 trigger / exit。 |
| `blocked_by_decision` | 需要 owner / 产品 / 架构裁决，agent 不擅自实现。 |

这些词不是统一的 `CapabilityStatus` enum。本文件不引入 CM-2 unified capability contract，也不声称 Tool / Skill / MCP / SubAgent 已共享同一 status schema。

---

## Runtime Fact Diff Table

| Surface | Current runtime fact | Evidence / source of truth | Boundary / non-goal |
|---|---|---|---|
| Tool execution | TOOL_GATE / TOOL_RESULT / evidence 走 dispatcher；TOOL_INVOKE 是 evidence-only；真实执行由 mediator 在 allowed gate 后调用 `execute_single_tool`。 | `agent/tool_runtime_mediator.py`；`agent/runtime_integration/tool_gate.py`；`tests/golden_e2e/test_golden_policy_evidence.py` | 不把 `execute_single_tool` 搬进 handler；不创建第二条 tool execution path。 |
| Policy / approval | `ToolGateHandler` 能拒绝 forbidden / not-allowed tool，`confirmation_required` 会进入等待态且不执行工具。 | `agent/runtime_integration/tool_gate.py`；`tests/adversarial/test_minimal_policy_stub.py` | OD-7 production approval hook 仍 deferred；不说 approval production-ready。 |
| Skill | 当前 skill runtime 在 `agent/skill_system/`；legacy `agent/skills` 是 tombstone。Skill 不直接执行工具、不写 memory。 | `agent/skill_system/registry.py`；`agent/skills/__init__.py` | 不恢复 `agent/legacy_skills/` 或旧 `agent/skills` 原型。 |
| SubAgent | V0 handler registered + contract-verified；flag-on 时 CLI/NL delegation 通过 `route_from_runtime_loop` 路由 V0；flag-off 默认 inline-local / `local_fake` rollback。 | `agent/subagent_routing_flag.py`；`agent/core.py`；`tests/runtime_integration/test_subagent_runtime_truth.py`；`tests/golden_e2e/test_golden_subagent_delegation.py` | 不声称 real provider E2E；不删除 inline-local fallback；不做 L3 lifecycle relocation。 |
| Provider / config | Provider selection 仍是 explicit factory branch；config precedence 为 `config/config.yaml` -> legacy profile/env -> fake。 | `agent/provider/factory.py`；`docs/06-audit/WINDOW_3_CM1_CONFIG_IMPORT_BOUNDARY_INVENTORY.zh.md` | 不新增 provider registry；不引入统一 `CapabilityStatus`。 |
| Scheduler | `action_scheduler` 是 dormant-by-default / registered-not-routed in production；`core.chat(..., action_scheduler=None, ...)` 默认不注入，测试可手工注入 seam。 | `agent/action_scheduler.py`；`agent/core.py`；`main.py`；W3 scheduler tests | 不接入 production routing；不把 scheduler 描述成 unreachable。 |
| Memory | consolidation pipeline frozen；`MEMORY_CONSOLIDATION_ENABLED` 与 `MEMORY_EMERGENCE_ENABLED` 默认 off；GE1-B1 golden lock 当前 `disabled_by_env` / env-gated 事实。 | `agent/memory_consolidation_pipeline.py`；`agent/memory_runtime_hooks.py`；`tests/golden_e2e/test_golden_memory_checkpoint.py`；`tests/golden_e2e/fixtures/memory_disabled.json` | 不解冻 memory；不实现 MEM-2 canonical owner；不接真实 LLM consolidation。 |
| Checkpoint / resume | 当前支持 local-file / per-run checkpoint schema v1/v2 与 best-effort load；golden 锁定本地 roundtrip / intra-process restore。 | `agent/checkpoint.py`；`agent/session.py`；`tests/golden_e2e/test_golden_memory_checkpoint.py`；`tests/golden_e2e/fixtures/checkpoint_local_roundtrip.json` | 不实现 SPR-1 cross-host resume 或完整 lifecycle state machine。 |
| Evidence trace / safe metadata | `RuntimeActionEvent` 可 flush 为 evidence trace；policy golden 明确 `claims_real_provider_e2e=false`；secret masking canonical owner 是 `display_events.py`。 | `tests/golden_e2e/test_golden_policy_evidence.py`；`agent/display_events.py`；`tests/runtime_integration/test_safe_metadata_ownership.py` | 不把 fake provider / subsystem evidence 夸成 real provider E2E；不复制 secret masker owner。 |
| MCP / external config | MCP 配置和 wrapper 仍在当前边界内治理；本轮只对文档事实对齐，不触达真实 endpoint。 | `agent/mcp_config*.py`；W3 config import-boundary inventory | 不做 real MCP reachability check；不写真实 home config。 |

---

## 本轮 Doc-Align 结论

- **GE-2**：本表作为 capability docs / runtime fact diff table；Current Fact 以 production code、可执行测试、closure audit inventory 为准。
- **RS-1**：mediated tool execution 是当前受治理拓扑；North Star amendment 若未来需要，必须单独经用户批准，本轮不改 North Star。
- **SPA-2**：permission 当前折叠在 policy gate / `gate_disposition` 内；production approval hook 仍 deferred。
- **MEM-1**：memory 当前是 frozen / env-gated / golden-locked 的最小现实；MEM-2 owner 决策未做。
- **CR-2**：legacy skill 口径为 tombstone / stale historical target，当前能力在 `agent/skill_system/`。
- **CR-3**：TUI / local demo compat label 本轮判定为 no-op；没有 evidence 表明它们是 production primary path。
- **CR-4**：stale docs refs 仅在历史计划/审计证据中保留为历史上下文；当前 source-of-truth 文档不继续把 deleted legacy path 说成 active path。

---

## 不变式 (Invariants)

### Parent control

**parent runtime remains in control** — 所有能力入口最终归 parent runtime 调度。Skill 和 SubAgent 是 parent 的受控分支点，不是独立 runtime。

### Execution boundaries

- **no direct tool execution** — Skill/SubAgent 不能绕过 ToolRegistry、policy gate 和 confirmation 管线直接执行工具
- **no real LLM/provider by default** — L0 / fake-first 路径不调用真实 LLM；real provider 路径需要显式 opt-in 与独立 evidence
- **no external process from SubAgent L0** — SubAgent L0 硬阻止 shell/external process
- **fake-first** — 所有能力先在 fake/local provider 下验证，real API 路径需显式 opt-in
- **local-only by default** — SubAgent 默认不访问网络、不创建外部进程

### Refactoring constraint

**not a broad refactor** — 能力边界加固是行为保持型变更，不引入新能力类型、不重写核心架构。

---

## 参考

- 当前状态入口：`docs/PROJECT_STATUS.md`
- 当前审计入口：`docs/06-audit/CURRENT_AUDIT_STATUS.zh.md`
- Repair roadmap：`docs/06-audit/CURRENT_ARCHITECTURE_REPAIR_ROADMAP.zh.md`
- Window 2 closure audit：`docs/06-audit/WINDOW_2_CLOSURE_AUDIT.zh.md`
- Window 3 config/import inventory：`docs/06-audit/WINDOW_3_CM1_CONFIG_IMPORT_BOUNDARY_INVENTORY.zh.md`
- SubAgent 边界架构：`docs/design/subagent-boundary-architecture.md`
- Skill 系统架构：`docs/design/skill-system-architecture.md`
