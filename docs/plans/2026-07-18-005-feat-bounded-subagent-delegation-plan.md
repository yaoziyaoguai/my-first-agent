---
title: Add Bounded SubAgent Delegation - Plan
type: feat
date: 2026-07-18
deepened: 2026-07-18
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: ce-plan-bootstrap
execution: code
---

# Add Bounded SubAgent Delegation - Plan

## Goal Capsule

- **Objective:** 新增一个始终审批的 parent delegation tool；它通过 injected `ChildAgentRunner` 复用同一个 `AgentRuntime.run_turn`，执行一个零工具、单 model call、同步有界的 child run。
- **Prerequisite:** Tool composition foundation 完成，Skill/MCP/Memory 全量非回归通过；先批准并落实 `EXTENSION_CONTRACTS.md` 的窄化 amendment。
- **Execution:** 5 个串行、Red-first 单元。
- **Product gate:** 开始前由用户批准一段 bounded 设计提案作为 independent-review reference task；完成后必须与 parent 直接回答对照成本、时长与增量观点，用户再决定是否保留并授权 Scheduler。
- **Stop conditions:** tool executor 直接调用 provider、出现 bespoke child loop、继承父 tools/context/workspace、递归/后台/并行、durable child lifecycle 或旧 `subagent_system` 被引用时停止。
- **Out of scope:** child tools/Memory/Skill/MCP、multi-call、resume、routing/roles、fan-out、background、streaming、in-flight cancel。

## Product Contract

### Requirements

- R1. `EXTENSION_CONTRACTS.md` 明确：普通 ToolSource 不得调用模型；只有 SubAgent executor 可调用注入的 `ChildAgentRunner` port，其唯一 production implementation 只调用同一 `AgentRuntime.run_turn`。
- R2. `subagent__delegate` 是 `HIGH + EXTERNAL + ALWAYS_APPROVAL`；arguments 只有 bounded objective/handoff，不能传 provider/tool/path/policy/budget override。
- R3. executor 接收冻结 `ExecutionIntent`；child conversation/run ID 从 parent idempotency key 确定性派生。相同 parent replay 不创建第二个 child。
- R4. 静态 ToolSpec identity 绑定 runner version、与 parent 相同的 approved provider trust profile/destination identity、child limit digest 和 workspace scope；每次 `ExecutionIntent` 与 approval binding 再绑定该 ToolSpec identity 以及 objective/handoff digest。approval preview 显示 provider destination 与 bounded objective/handoff，不能只显示 digest。
- R5. child 使用独立 in-memory state/store、同一 `AgentRuntime` class、独立 ContextManager（sources 空）、空 ToolRuntime、无 workspace capability，最多一次 model call、零 tool calls和固定 input/output caps；只接受声明并实现有限 request deadline 的 supported provider profile，timeout 不超过 child profile 上限，否则 startup fail closed。
- R6. child 不自动继承父 history、pending、tool results、Memory、Skill、MCP、credential 或 filesystem；handoff 只有模型显式提交的 bounded text。父模型仍可能手工复制敏感内容，因此同 provider trust domain 与 human-readable approval preview 都是必须的，不能声称自动隔离等于内容安全。
- R7. 只有 child `COMPLETED` 是 parent success；其他明确 `RunStatus` 或 child tool request 都成为 bounded known executed `child_nonterminal` error，并丢弃 child state。
- R8. parent `EXECUTING` 后宿主/runner crash 或无法返回 child `RunStatus` 的 unclassified exception 是 unknown outcome，恢复时进入 parent `AWAITING_RECOVERY`；不自动重建、重试或恢复 child。v1 不用不可终止的 thread 伪造 hard wall-clock cancel。
- R9. child events 不混入 parent event sequence；parent 只获得 bounded output/termination/stat summary，不记录 raw prompt/response/credential/temp checkpoint。
- R10. production provider call site 仍只有 `agent/runtime/loop.py`，ToolRuntime/checkpoint mutation ownership不变。
- R11. 新 package 使用 `agent/subagent/`；旧 `subagents/`、`subagent_system/`、routing/adjudication/runtime-integration 不恢复。

验收场景：拒绝审批 child count 0；批准后 parent EXECUTING 先于 child call；child completed 返回一次 result；child tool call/limit/pause 是 nonterminal error；runner crash 是 parent recovery；same action replay child count 不增加；child tool catalog/context sources 恒为空。

## Planning Contract

- KTD1. **SubAgent is one governed external effect, not orchestration.** 父 Runtime 只看到 tool intent/result/recovery。
- KTD2. **Reuse class and loop, isolate state.** “同一个 Runtime”指同一 implementation，不指共享 conversation/checkpoint/cursor。
- KTD3. **One-call child deliberately cannot act.** v1 先证明安全 delegation boundary，不提前解决 child autonomy。
- KTD4. **Only completed is success.** 不把 child pause/limit/tool request 暗示为可恢复 task。
- KTD5. **不恢复旧 SubAgent 系统** `(session-settled: user-approved — chosen over continuing feature-entangled legacy architecture: the user accepted cutting old implementations and rebuilding through stable boundaries.)`。

目标结构：

```text
agent/subagent/{__init__.py,contracts.py,runner.py,tools.py}
tests/subagent/{test_runner.py,test_tools.py,test_integration.py}
```

## System-Wide Impact

- SubAgent 是唯一允许通过 injected runner 间接触发同一 Runtime implementation 的 ToolSource；effect-owner architecture test 必须把例外收窄到 runner module。
- Child 使用 parent 已批准的同一 provider destination，但拥有独立 state/context/tools；没有 child lifecycle 进入 parent checkpoint。
- Runner 同步执行且不创建 timeout helper thread；boundedness 来自一次 model-call cap、受支持 provider 的 hard request deadline 与有界本地处理。

## Implementation Units

### U1 — Amend and guard the architecture contract

- **Modify:** `docs/architecture/EXTENSION_CONTRACTS.md`, `tests/architecture/test_dependency_dag.py`, `tests/architecture/test_cutover_absence.py` 的 effect-owner guard。
- **Red:** executor importing provider/loop fails; only runner module may import `AgentRuntime`; provider `.generate` remains called only from loop; no second `while` model loop or checkpoint CAS in package.
- **Green:** document and encode the narrow `ChildAgentRunner` exception before feature code.
- **Verify:** architecture tests fail against a synthetic forbidden fixture and pass against the allowed dependency edge.

### U2 — Define child contracts and bounded runner

- **Add:** `agent/subagent/contracts.py`, `agent/subagent/runner.py`, `tests/subagent/test_runner.py`.
- **Red:** deterministic IDs, strict limits, same-provider trust identity, unsupported/different/unbounded provider startup denial, empty tool/source composition, one model call, all RunStatus mappings, tool request under zero budget, bounded output, no helper thread, injected clock/ID/provider profile identity and temporary state disposal。
- **Green:** `ChildAgentRunner` protocol plus production runner factory that constructs `AgentRuntime` with in-memory store and fixed isolation profile, then submits one deterministic `SubmitMessage`.
- **Verify:** fake provider call count exactly one or zero; no filesystem/network.

### U3 — Implement governed delegation registration

- **Add:** `agent/subagent/tools.py`, `tests/subagent/test_tools.py`.
- **Red:** HIGH/EXTERNAL/ALWAYS spec；preview 显示 provider destination 与 exact bounded objective/handoff 并绑定 digest；stale/different profile approval invokes zero；敏感 handoff 仍必须由人可见；no model-supplied overrides; frozen intent handed to runner; same idempotency key stable; completed/nonterminal normalization; unclassified crash exception propagation。
- **Green:** `build_subagent_tool_registrations(runner, profile)` with one intent-aware executor and sanitized result.
- **Verify:** rejected/stale approval invokes zero; approved replay invokes at most once.

### U4 — Compose an explicit opt-in runner

- **Modify:** `agent/composition.py`, `main.py`, `README.md`; add `tests/subagent/test_integration.py` and CLI tests.
- **Red:** no opt-in leaves definitions unchanged; opt-in composes one registration in same ToolRuntime; child only uses parent approved provider through Runtime；different destination、missing hard timeout contract 或 invalid limits startup fail closed；parent pause/recovery/result ordering。
- **Green:** explicit configuration and runner injection in composition root; no registry/lifecycle manager.
- **Verify:** fake-provider parent → approval → child → parent completion journey.

### U5 — Lock absence and full regression

- **Modify:** `tests/architecture/test_cutover_absence.py`, dependency/owner tests, design/docs as needed.
- **Red:** old packages, descriptors, routing flags, adjudication, background/task APIs remain banned.
- **Green:** allow only `agent/subagent/` and documented dependency edge.
- **Verify:** full gates below.

## Verification Contract

Feature-test venv 先从当前 worktree 安装 `.[dev,skill,mcp]`；SubAgent v1 没有新的第三方 runtime extra。base-install absence 使用独立 clean temp venv/subprocess，而不是修改主 venv。

```bash
.venv/bin/python -m pytest -q tests/subagent tests/kernel/test_effect_ordering.py tests/kernel/test_runtime_recovery.py tests/cli
.venv/bin/python -m pytest -q tests/architecture
git diff --check
.venv/bin/ruff check .
.venv/bin/python -m pytest -q -rx
```

Tests must prove counts/order with fake providers and stores. No test may invoke a real provider, inherit actual workspace tools, or preserve child state outside the fixture.

## Definition of Done

- One approved parent tool can run one isolated child through the same `AgentRuntime.run_turn` implementation.
- Child has zero tools/sources/workspace inheritance and exactly the documented bounded termination semantics.
- Replay, stale approval, nonterminal child and unknown runner outcome are independently verified.
- Architecture tests prove no second provider/tool loop and old SubAgent systems remain absent.
- 用户批准的 reference task 至少产生一个可核对的增量观点；若 zero-tool、one-call child 没有增量价值，该阶段保持未授权而不是把架构演示称为产品能力。
- Full quality gates pass; no code for recursive, background or durable delegation exists.
