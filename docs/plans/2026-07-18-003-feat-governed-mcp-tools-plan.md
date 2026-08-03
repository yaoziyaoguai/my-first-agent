---
title: Add Governed MCP Tools - Plan
type: feat
date: 2026-07-18
deepened: 2026-07-18
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: ce-plan-bootstrap
execution: code
---

# Add Governed MCP Tools - Plan

## Goal Capsule

- **Objective:** 把 operator 批准的固定 MCP stdio tool descriptors 映射为具体、始终审批的 EXTERNAL tools，并在 invocation 内完成协议协商、descriptor 验证、单次调用和有限时关闭。
- **Prerequisite:** `2026-07-18-002-feat-governed-skill-source-plan.md` 全部完成，尤其是 per-registration policy、intent-aware executor 与 outcome taxonomy。
- **Execution:** 6 个串行、Red-first 单元；先验证 owner-loop lifecycle，再验证单次 stdio protocol session；只使用 local fixture server，不访问真实 MCP server 或网络。
- **Product gate:** 开始前由用户指定并批准一个 operator-trusted local MCP reference task；自动测试仍只用 fixture，真实 reference task 只有在用户另行授权调用时执行。完成后由用户决定是否授权 Memory。
- **Stop conditions:** startup 联网/启动 server、万能 `mcp.call`、remote annotation 降低本地 policy、跨调用 live session、自动 retry 或恢复旧 `mcp_bridge.py` 时停止。
- **Out of scope:** HTTP/OAuth、resources/prompts、Sampling/Roots/Elicitation、Tasks、live discovery/refresh、binary/media、structured result projection。

## Product Contract

### Requirements

- R1. 协议固定 revision `2025-11-25`；optional extra 精确使用 stable `mcp==1.28.1`、`jsonschema>=4.23,<5`，并把 base `httpx` minimum 提升到 `>=0.27.1`；不接 SDK v2。
- R2. 显式 JSON catalog 只含 local descriptor、absolute regular no-follow stdio executable/args/cwd、允许转发的 env **名称**、转发 credential 时必填的非秘密 operator-readable profile label、每个 server 的 operator-controlled 非秘密 `safety_generation`、limits 与本地 policy；禁止 credential value 和 shell command string。executable/ancestor identity 与 content digest 在 catalog、prepare、spawn 前冻结/复验。
- R3. startup 只验证 catalog、显式 safety-state path 与 durable latch；没有 unresolved marker 时才创建 concrete `mcp__<server>__<tool>` registrations，不 spawn、initialize、list 或 call。
- R4. local name、description、input schema、risk/effect/approval/output cap 与 identity 全由本地 catalog 决定；remote annotations/instructions/title/_meta 不参与安全决策。
- R5. 所有 v1 MCP tools 使用 `HIGH + EXTERNAL + ALWAYS_APPROVAL`；config/descriptor/policy/executable identity、credential profile/composition epoch、safety generation 与 exact arguments digest 进入 intent/approval binding。human preview 完整显示 server/tool/executable/profile/safety-generation identity 和 canonical bounded arguments；argument cap 不大于 preview cap，无法完整显示时 effect 前 `executed=false`。
- R6. `McpAsyncBridge` 独占一条长生命周期 event-loop thread，但 startup 没有 session；每次 invocation 在该 loop 内创建、使用并关闭独立 stdio session/process group。本计划作为首个真实 closeable 把 ordered close stack 加入 composition，在停止新 action和 bounded invocation 返回后关闭 bridge。cleanup 无法确认会把 bridge 置为 terminal quarantine。另有显式 owner-only/no-follow durable safety latch：它以 finite-lock + revision/token CAS 从 exact CLEAR→ARMED，每次 invocation 在 Kernel `EXECUTING` 后、spawn 前 arm；已有 marker/conflict/timeout 的 loser known-not-executed 且不 spawn。只有匹配 full binding 的 owner 在整个 process group 确认退出后可 ARMED→CLEAR；unresolved marker 使后续 composition fail closed，human outcome resolution 不能清除。
- R7. invocation 顺序固定为 spawn → initialize/initialized → capability check → bounded `tools/list` all pages → exact descriptor digest verify → local argument schema validate → one `tools/call` → normalize → close。client capability manifest 只声明 v1 所需能力，不注册 Sampling/Roots/Elicitation/Tasks/resource/prompt callback。
- R8. pagination cursor 是 opaque；只有 absent/null 终止，空字符串仍是合法 next cursor；页数、items、bytes 与总时长有上限。
- R9. v1 只接受 bounded text content。`isError=true` 是 known executed error；structured/binary/resource/task result fail closed。
- R10. bridge 返回 immutable typed outcome，显式携带 classification、`call_may_have_been_sent`、`terminal_response_received`、`terminal_request_id_matched` 与 `process_exit_confirmed`。call 前 drift 是 known-not-executed；任意 call bytes 可能写出后，只有完整匹配 terminal result 且 cleanup 已确认才能结束 unknown 区间。JSON-RPC error、wrong ID、partial/malformed response、timeout/disconnect/process crash 默认进入 parent recovery；完整 terminal result 的 `isError`、unsupported/oversized content 是 known executed error。两类都绝不自动 retry。
- R11. child process 只继承 allowlisted env；credential value 由 composition root 冻结在不可序列化 secret holder。每次 credential-bearing composition 生成非秘密 random composition epoch，与 profile label 一起进入 ToolSpec/intent/approval，使旧审批失效；它不作为 rotation proof。durable latch 绑定 config/profile/`safety_generation`/intent digest；stale marker 只能由 operator-only offline command 在精确匹配 marker、确认残留进程终止，并在使用 credential 时确认 rotation 后推进到新 generation，改 catalog/restart/recovery action 都不能绕过。secret value、stderr secret、绝对私有 path、catalog body 不进入 model/checkpoint/event。stdout/stderr 有 byte cap；stderr 日志本身不是失败，stdout contamination fail closed；未协商 request/notification 不得触发 provider、workspace、用户交互或 credential lookup。v1 无 filesystem/process sandbox 保证。
- R12. 新 package 使用 `agent/mcp/`；旧单文件 MCP、bridge/config/service/audit/runtime-integration 路径不恢复。

验收场景：local fixture 强制 lifecycle 顺序；多页 list 包含 empty cursor；drift 时 call count 为零；remote annotations 不能降低审批；`isError` 成为 paired result；call 后断线只产生一个 recovery 且无自动重试；host crash 留下的 latch 在 restart/human resolution 后仍阻止调用，直到 operator recovery；base install 未配置 MCP 时不导入 SDK。

## Planning Contract

- KTD1. **Fixed reviewed catalog, no runtime discovery.** Discovery 本身会 spawn 外部进程，不能在 startup 绕过 approval/checkpoint。
- KTD2. **Concrete tools, no universal dispatcher.** 每个 remote descriptor 进入一个普通 ToolSpec，模型看不到 server/config/credential override。
- KTD3. **Long-lived async owner loop, short-lived sessions.** 避免每次 `asyncio.run()` 与 SDK loop affinity 问题，同时不形成 background connection manager。
- KTD4. **Remote hints are untrusted.** v1 统一 ALWAYS_APPROVAL，后续降级必须有独立本地 policy design。
- KTD5. **Unknown external outcomes remain human-only** `(session-settled: user-approved — chosen over continuing feature-entangled legacy architecture: the user accepted cutting old implementations and rebuilding through stable boundaries.)`。

目标结构：

```text
agent/mcp/{__init__.py,contracts.py,catalog.py,safety.py,bridge.py,tools.py}
tests/mcp/{test_catalog.py,test_safety.py,test_bridge.py,test_session.py,test_tools.py,test_integration.py}
tests/fixtures/mcp/stdio_server.py
```

## System-Wide Impact

- MCP 是首个 closeable capability：它只向 shared composition 注册 tools 与一个 bridge closeable，不能自己构造 Runtime 或拥有 action loop。
- ToolRuntime 在同步调用边界等待 bridge；bridge owner loop 只运行协议 coroutine，不回调 Runtime/state。
- durable safety latch 是显式 operator state，不是 capability cursor；它只在 approved invocation 的 `EXECUTING` 之后 arm，并在 process cleanup 被证明后 clear。unresolved marker 在 composition 前 fail closed。
- Teardown 必须先停止 CLI/Scheduler/TUI 接收新 action并让 bounded invocation 收口，再关闭 bridge/process group；无法确认清理进入 recovery/operational warning。

## Implementation Units

### U1 — Freeze MCP catalog and local policy types

- **Add:** `agent/mcp/contracts.py`, `agent/mcp/catalog.py`, `agent/mcp/safety.py`, `tests/mcp/test_catalog.py`, `tests/mcp/test_safety.py`, bounded JSON fixtures.
- **Modify:** `pyproject.toml` optional `mcp` extra and httpx floor.
- **Red:** duplicate/local-name collision, credential-looking values, shell strings, unsupported transport/schema, excessive depth/size, env-name validation, explicit safety generation, absolute executable/cwd no-follow identity, approval 后 executable/ancestor replacement, deterministic config/descriptor/policy digest and missing optional dependency；owner-only/no-follow latch create/load/finite lock、strict schema、revision/token CAS、ARMED full binding、wrong-owner clear rejection 与 unresolved startup rejection。
- **Green:** immutable catalog/latch types, strict unknown-field rejection, canonical provider-safe namespace mapping, atomic all-or-nothing load and minimal durable CLEAR/ARMED safety-latch store；它不保存 Runtime cursor/result。
- **Verify:** catalog parsing does not import/spawn SDK and errors reveal no values/absolute private paths.

### U2 — Implement async owner-loop lifecycle

- **Add:** `agent/mcp/bridge.py`, `tests/mcp/test_bridge.py`.
- **Red:** exactly one owner event loop/thread；startup creates no session/process；bounded submit of injected fake coroutine；concurrent submit serialization contract；idempotent close；submission after close；typed outcome/exception delivery；terminal quarantine rejects every later submit；no global bridge or Runtime callback。
- **Green:** small `McpAsyncBridge` start/submit/close state machine with injected coroutine factory and explicit `OPEN/QUARANTINED/CLOSED` lifecycle. Do not implement stdio protocol in this unit.
- **Verify:** deterministic owner-loop/thread tests without MCP server, SDK spawn or network.

### U3 — Implement one bounded stdio protocol session

- **Add:** session/process implementation in `agent/mcp/bridge.py`, `tests/mcp/test_session.py`, `tests/fixtures/mcp/stdio_server.py`.
- **Red:** first prove pinned SDK public `ClientSession(read_stream, write_stream)` accepts project-owned streams without private imports or SDK-owned spawn；then prove no session before invoke; ARMED marker is durable before spawn and clears only after exact-owner process-group exit；两个独立进程 barrier-race 同一 CLEAR revision 时只有一个 arm/spawn，loser known-not-executed/call count 0 且不能 clear winner；initialize first; initialized notification; minimal capability manifest; tools capability required; opaque pagination including empty cursor; Sampling/Roots/Elicitation/Tasks/unsolicited requests fail closed; per-stage/total timeout; `call_may_have_been_sent` flips conservatively before first OS write attempt and never rolls back; stdout/stderr cap/redaction; stdout contamination；forked child/process cleanup failure/host-crash simulation leaves latch armed and enters quarantine；process crash and deterministic shutdown.
- **Green:** project-owned `McpStdioTransport` owns process group/framing/commit receipt and injects public streams into per-invocation SDK `ClientSession`; SDK owns JSON-RPC session lifecycle；produce `McpBridgeOutcome` without using SDK `stdio_client`/private hooks. Direct operator-trusted executable only, no shell/sandbox claim. If the public-stream feasibility Red cannot pass on `mcp==1.28.1`, stop this plan instead of weakening classification.
- **Verify:** fixture transcript, commit-state matrix and process cleanup; no external network.

### U4 — Verify descriptor, call once, normalize outcome

- **Add:** `agent/mcp/tools.py`, `tests/mcp/test_tools.py`.
- **Red:** concrete spec identity；preview 含 server/tool/executable/profile/safety generation 与完整 canonical arguments；argument/preview overflow 在 effect 前拒绝；参数、composition epoch 或 safety generation 漂移使审批失效；local JSON Schema；descriptor drift gives `executed=false`; text result; matching `isError`; structured/media/resource rejection；typed outcome commit flags 分别映射 known-not-executed/known executed/unknown；bridge quarantine 后 second call count 为零。
- **Green:** intent-aware executor submits one coroutine, verifies pinned descriptor/composition epoch/safety generation before `tools/call`, maps only typed outcomes, and sanitizes all errors/output.
- **Verify:** remote annotations cannot change local policy and same intent cannot call twice.

### U5 — Compose explicit MCP configuration and lifecycle

- **Modify:** `agent/composition.py`, `main.py`, `README.md`; add `tests/mcp/test_integration.py` and CLI tests.
- **Red:** absent config leaves base imports/definitions unchanged; explicit catalog plus explicit safety-state path composes with file/Skill registrations in one ToolRuntime; invalid catalog or unresolved ARMED marker fails before registrations/Runtime; two compositions started from CLEAR still serialize at invoke-time latch CAS；this first closeable extends composition with reverse-order close stack；bridge closes on normal/startup failure paths; secret holder is non-serializable；new composition epoch invalidates restored approval；host crash → reopen → `ResolveUnknownToolOutcome` 后仍不能 second-submit；仅 exact marker revision/token/full-binding 的 operator recovery command + residual-process confirmation + credential rotation confirmation/new generation（credential-bearing case）可原子解除，单改 catalog generation 不可绕过。
- **Green:** explicit CLI catalog/safety-state options, environment allowlist resolution, frozen secret holder/profile/composition epoch, registration concatenation, first shared ordered close stack, and a separate operator-only safety recovery command that records attestation without claiming external verification.
- **Verify:** fake provider + local fixture approval/call/result journey, crash-to-recovery journey, and durable quarantine reopen journey.

### U6 — Lock architecture and security regression

- **Modify:** `tests/architecture/test_cutover_absence.py`, `tests/architecture/test_dependency_dag.py`, `docs/architecture/EXTENSION_CONTRACTS.md`, `README.md`.
- **Red:** only `agent/mcp/` is allowed; no production real-network test, generic MCP caller, startup discovery, provider/checkpoint import or old MCP namespace.
- **Green:** exact allowlists/docs; keep resources/prompts/tasks/HTTP explicitly absent.
- **Verify:** full gates below.

## Verification Contract

Feature-test venv 先从当前 worktree 安装 `.[dev,skill,mcp]`。base-install absence 另用只安装 `.[dev]` 的 clean temp venv/subprocess 验证；不得让缺包变成 skip，也不得从主 venv 卸载依赖。

```bash
.venv/bin/python -m pytest -q tests/mcp tests/kernel/test_tool_outcomes.py tests/cli
.venv/bin/python -m pytest -q tests/architecture
git diff --check
.venv/bin/ruff check .
.venv/bin/python -m pytest -q -rx
```

Tests must use the repository fixture executable with scrubbed environment and temporary directories. They must not call a real MCP endpoint, inherit user credentials, or treat a timeout/truncated output as pass.

## Definition of Done

- Approved concrete stdio tools traverse the existing prepare/approval/EXECUTING/invoke/result path exactly once.
- Startup has no external effect; invocation enforces lifecycle, pagination, pinned descriptor and local policy.
- Known-not-executed, known executed error and unknown outcome are independently fault-injection tested.
- Bridge/session/process shutdown is bounded and base installs remain MCP-free unless configured.
- 用户批准的 MCP reference task 有完整 arguments preview、effect/result evidence；未授权真实调用时明确保持 product gate 未验收，不伪造价值证明。
- Old MCP architecture is still absent; architecture, lint and full test gates pass.
