---
title: Add Governed Skill Source - Plan
type: feat
date: 2026-07-18
deepened: 2026-07-18
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: ce-plan-bootstrap
execution: code
---

# Add Governed Skill Source - Plan

## Goal Capsule

- **Objective:** 建立共享 Tool composition 基础，并把显式 trust root 中的 Agent Skills 作为只读 governed tools 接入唯一 `KernelToolRuntime`。
- **Authority:** `docs/architecture/CAPABILITY_REINTRODUCTION_ROADMAP.md`、`docs/architecture/capabilities/SKILL_DESIGN.md` 与现有 Kernel invariants。
- **Execution:** 5 个串行、Red-first 单元；先稳定 Tool registration/outcome 合同，再实现 Skill catalog 与 tools。
- **Product gate:** 开始前由用户批准 roadmap 中的具体 Skill reference task；完成后提交该任务的 trace/回答证据，并由用户决定是否授权 MCP。
- **Stop conditions:** 任何实现需要 prompt hook、动态扫描、第二个 registry/runtime、script 执行、读取默认 `.agents/.codex/.claude` 或兼容旧 `skill_system` 时停止。
- **Out of scope:** MCP、Memory、SubAgent、安装/升级、自动激活、`allowed-tools` enforcement 和 scripts。

## Product Contract

### Requirements

- R1. Python 基线提升到 `>=3.11`，Ruff target 同步；base install 不强制安装 Skill 依赖。
- R2. capability factory 返回 `tuple[RegisteredTool, ...]`；`agent/composition.py` 的静态 composition result 只拼接当前真实消费者需要的 registrations，并构造一个 `KernelToolRuntime`、一个 `KernelContextManager` 与一个 `AgentRuntime`。ContextSource 与 ordered close stack 分别留给 Memory、MCP 首个真实消费者引入；不存在 service locator/dynamic registry。
- R3. 每个 registration 绑定自己的 immutable `ToolPolicy`；policy identity 进入 `ExecutionIntent` 和 approval binding，不按工具名路由。
- R4. registered executor 接收冻结的 `ExecutionIntent`；`ToolResult` 明确区分 executed result 与 known-not-executed result，unknown outcome 仍抛给 Runtime recovery。
- R5. shared reducer 对 durable `RUNNABLE/EXECUTING` 的 `CancelRun` 返回 unchanged conflict；所有 caller 只能 `Resume` 进入现有 unknown-outcome recovery，进入 `AWAITING_RECOVERY` 后只接受 exact `ResolveUnknownToolOutcome`，Resume/Cancel 仍 unchanged conflict。该合同必须在任何新 effectful capability 接入前锁定。
- R6. 文件工具行为、policy、approval preview 和 effect ordering 与当前完全一致。
- R7. 只读取一个或多个显式 `--skill-root`，startup 构建 bounded immutable catalog；无配置时没有 Skill registration 或 disabled flag。
- R8. `SKILL.md` 使用 SafeLoader 严格子类解析公开 Agent Skills 核心字段，并拒绝 duplicate keys、aliases/cycles、危险 tag 与超限 node/depth/scalar；name/dir mismatch、duplicate、symlink 或路径漂移 fail closed。
- R9. 每个 Skill 映射为独立 `skill__<manifest-name>` READ_ONLY activation tool，保留已验证 name 中的 `-`，不做 underscore canonicalization；metadata 可见。完整 activation result 必须同时不超过 Skill body/result limit 与 composition 的 `ContextLimits.max_tool_result_chars`，body 只有调用后才完整进入 ToolResult，不能静默截断。
- R10. `skill__read_resource` 只读取 catalog 中 `references/`、`assets/` 的 bounded UTF-8 regular file；拒绝 traversal、symlink、URL 与 `scripts/`。
- R11. catalog、body 与每个 resource 分别冻结 ancestor/file identity 和 digest；policy version 进入 tool identity；scan 后任一局部漂移产生 known-not-executed result，不能 hot refresh。
- R12. Skill 内容是 guidance，不是 authority；不能改变 tool policy、approval、workspace、credential 或 Runtime limits。
- R13. 新 package 使用 `agent/skill/`；旧 `agent/skill_system/`、旧 `agent/skills/` API 与旧测试不得恢复。

验收场景：有效 Skill 仅暴露 metadata；显式 activation 返回完整 body；resource 安全读取；重复名称、symlink、超限和 digest 漂移 fail closed；恶意 Skill 指令不能跳过文件写审批；未配置时 Kernel 结果与 tool definitions 保持基线。

## Planning Contract

- KTD1. **先做 Tool composition foundation，再做第一个能力。** 后续 MCP、Memory、SubAgent 共用同一 registration/policy/outcome 合同，禁止每项能力另写 router。
- KTD2. **Skill 是 governed read tools，不是 ContextSource 或 system prompt hook。** body 通过正常 tool-call/result pairing 进入 ContextManager。
- KTD3. **只实现公开规范的严格 subset。** 使用 PyYAML safe parser；`skills-ref` 仅作规范示例，不作为 production dependency。
- KTD4. **完整激活，不能静默截断。** startup body limit 保证可完整返回；超限 Skill 不进入 catalog。
- KTD5. **不恢复旧实现** `(session-settled: user-approved — chosen over continuing feature-entangled legacy architecture: the user accepted cutting old implementations and rebuilding through stable boundaries.)`。

目标结构：

```text
agent/composition.py
agent/skill/{__init__.py,catalog.py,tools.py}
tests/skill/{test_catalog.py,test_tools.py,test_integration.py}
```

## System-Wide Impact

- `main.py` 退化为参数/adapter 入口；Runtime/ToolRuntime/ContextManager 由一个显式、静态 composition result 组装。
- 后续能力扩展同一个 composition：MCP 首次加入 ordered close stack，Memory 首次加入 sources tuple；不得各自创建 Runtime 或把 lifecycle 塞回 `main.py`。
- Skill 本身没有 background/closeable resource，本计划不预建无消费者的 lifecycle API。

## Implementation Units

### U1 — Freeze shared Tool composition and outcome contracts

- **Modify/add:** `pyproject.toml`, `agent/runtime/contracts.py`, `agent/runtime/state.py`, `agent/runtime/tools.py`, `agent/tools/file_ops.py`, `agent/composition.py`, `main.py`.
- **Add tests:** `tests/kernel/test_tool_registration_composition.py`, `tests/kernel/test_tool_outcomes.py`; extend `tests/tools/test_file_tools.py` and architecture tests.
- **Red:** durable `RUNNABLE/EXECUTING` checkpoint 对 `CancelRun` 返回 unchanged conflict、`Resume` 产生同一 recovery request且 provider/tool count 为零；在 `AWAITING_RECOVERY`，Resume/Cancel 都 unchanged，只有 exact resolution 推进；prove two registrations can use different policy identities; duplicate names fail atomically; executor receives exact frozen intent; `executed=false` advances one tool cursor without recovery; unknown WRITE/EXTERNAL exception enters recovery; existing file tools still approve/execute once；composition 没有 sources/closeable placeholder、global getter 或 dynamic lookup。
- **Green:** lock shared reducer EXECUTING legality; add per-registration policy, intent-aware executor, explicit executed flag/outcome normalization, `build_file_tool_registrations()`, and one static composition result. Keep `KernelToolRuntime` the only caller.
- **Verify:** focused kernel/tool/architecture tests; assert only `agent/runtime/loop.py` invokes ToolRuntime/checkpoint ports.

### U2 — Implement strict immutable Skill catalog

- **Add:** `agent/skill/__init__.py`, `agent/skill/catalog.py`, `tests/skill/test_catalog.py`, fixtures under `tests/fixtures/skill/`.
- **Modify:** `pyproject.toml` with optional `skill = ["PyYAML>=6,<7"]`.
- **Red:** valid metadata, missing dependency error only when configured, name/dir mismatch, duplicate roots/names/keys, exact `code-review`→`skill__code-review` mapping and no normalization collision, YAML custom tag/alias/cycle bomb, symlink, ancestor swap, traversal, non-UTF-8, node/file/body/resource/catalog limits, deterministic per-resource digest and no private absolute path/content in public errors.
- **Green:** immutable descriptor/catalog types, descriptor-relative no-follow reads, strict allowlisted frontmatter and startup snapshot digest. Never scan a default root.
- **Verify:** catalog tests use only temporary fixtures and do not read project/user Skill directories.

### U3 — Map Skills to governed activation/resource tools

- **Add:** `agent/skill/tools.py`, `tests/skill/test_tools.py`.
- **Red:** stable namespaced specs; empty activation schema; full activation result length never exceeds `max_tool_result_chars`; resource allowlist; script/URL rejection; body/resource-only/ancestor inode or digest drift becomes known-not-executed without reading replacement content; malicious text cannot mutate registration policy.
- **Green:** `build_skill_tool_registrations(catalog)` returns activation registrations plus one resource registration, each with bounded identity and read-only policy.
- **Verify:** ToolRuntime integration proves normal pairing；在可容纳预算下下一 ContextPack 含完整 body 且对应 fact 不在 `BudgetReport.clipped_ids`，不可容纳的 pinned group 显式产生 context limit 而不是 partial instructions。

### U4 — Compose explicit CLI configuration

- **Modify:** `agent/composition.py`, `main.py`, `README.md`, optionally `agent/skill/__init__.py` exports.
- **Add/modify tests:** `tests/cli/test_commands.py`, `tests/skill/test_integration.py`.
- **Red:** no root means unchanged definitions; repeated `--skill-root` composes one catalog; invalid root or missing optional dependency fails startup; base imports work without PyYAML.
- **Green:** parse explicit roots, build catalog only when present, concatenate file + Skill registrations, create one ToolRuntime.
- **Verify:** fake-provider activation journey and no-configuration regression.

### U5 — Lock architecture and documentation

- **Modify:** `tests/architecture/test_cutover_absence.py`, `tests/architecture/test_dependency_dag.py`, `docs/architecture/EXTENSION_CONTRACTS.md`, `README.md`.
- **Red:** new `agent/skill/` is the only allowed Skill product package; old `skill_system`, lifecycle/install/update paths and prompt injection remain absent.
- **Green:** update exact allowlists and user docs without compatibility exports or dormant flags.
- **Verify:** full quality gates below.

## Verification Contract

Feature-test venv 先从当前 worktree 安装 `.[dev,skill]`。optional-dependency absence 另用只安装 `.[dev]` 的 clean temp venv/subprocess 验证；不得从主 venv 临时卸载依赖或 skip collection。

Run in order:

```bash
.venv/bin/python -m pytest -q tests/kernel/test_tool_registration_composition.py tests/kernel/test_tool_outcomes.py tests/tools tests/skill tests/cli
.venv/bin/python -m pytest -q tests/architecture
git diff --check
.venv/bin/ruff check .
.venv/bin/python -m pytest -q -rx
```

No test may access a real provider, external network, user Skill root or Coding Agent `.agents/.codex/.claude` directories. A timeout, truncated output, missing exit code or failing full suite is not a pass.

## Definition of Done

- One ToolRuntime composes file and Skill registrations with per-registration policy identity.
- Outcome taxonomy is behavior-tested and existing file effect ordering has no regression.
- Valid Skill metadata/body/resources work only through governed read tools; scripts and dynamic discovery do not exist.
- All architecture absence/DAG checks and full quality gates pass.
- 用户批准的 Skill reference task 证明完整 guidance 确实改善了一个可核对结果；没有该 evidence 不自动进入 MCP。
- Design deviations and dependency/version choices are recorded in this plan or `SKILL_DESIGN.md`; no code for later capabilities is pre-added.
