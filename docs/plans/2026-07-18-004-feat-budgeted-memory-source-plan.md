---
title: Add Budgeted Memory Context Source - Plan
type: feat
date: 2026-07-18
deepened: 2026-07-18
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: ce-plan-bootstrap
execution: code
---

# Add Budgeted Memory Context Source - Plan

## Goal Capsule

- **Objective:** 增加一个通用、immutable、budgeted `ContextSource` seam，并用它实现 workspace-scoped Memory 召回；Memory 修改只通过 governed WRITE tools。
- **Prerequisite:** Skill 计划 U1 的 Tool composition/outcome foundation 已完成；MCP 计划全量非回归通过。
- **Execution:** 6 个串行、Red-first 单元；先建立 provider-neutral seam，再实现安全 store、read source 和 mutation tools。
- **Product gate:** 开始前由用户批准“conversation A remember → conversation B recall/apply”的具体项目约定与 provider trust profile；完成后由用户决定是否授权 SubAgent。
- **Stop conditions:** Memory 直接拼 system prompt、写 conversation state、调用 provider、在 session end 自动保存、扫描旧数据、引入 vector/LLM summary/background hook 时停止。
- **Out of scope:** 自动抽取、consolidation、embedding、跨 workspace/global profile、后台维护、导入迁移和加密 key management。

## Product Contract

### Requirements

- R1. `ContextQuery`、`ContextCandidate`、`ContextSourceSnapshot` 是 `runtime.contracts` 的 immutable JSON-safe leaf types；`ContextSource` port 只返回一个 revision-consistent snapshot，不返回 `ModelMessage`/`ContextPack`。
- R2. `KernelContextManager` 显式接收 sources tuple，并独占 source 调用、排序、预算、projection 与 BudgetReport；没有 source registry/dynamic discovery。
- R3. 每次 `build` 从每个 source 取得一个 fresh immutable snapshot；一次 build 不能观察两个 store revision。source digest 和 candidate IDs 进入 BudgetReport，写入在下一次 build 才可见。
- R4. source 不能设置 pinned/system priority。Memory 永远低于 system、current user、pending approval/recovery、active tool batch 和 recent tool results；有独立 item/token cap 且计入总 input budget。
- R5. Memory candidate 投影为 provider-neutral `context` block，明确 `untrusted=true`、source、ID、digest/provenance；OpenAI/Anthropic adapters 只能投影为非-system 文本。
- R6. lexical score 固定为 NFKC+casefold 后的 deterministic token match：ASCII letter/digit 连续串为 token、每个非 ASCII alphanumeric code point 为 token，score=`2 * matched unique query tokens + exact normalized phrase bonus`；再按 approved record recency 降序、record ID 升序；空 query score 为 0，同 query/snapshot byte-equivalent。
- R7. Memory store 是显式路径、严格 versioned JSON、owner-only/no-follow data file 与独立 lock file、store revision CAS；create/load/read/prepare/mutation 的 lock acquisition 使用 monotonic、不可延长的 finite deadline，禁止 blocking forever；持同一稳定 lock 完成 data 校验、同目录 `0600` temp write+fsync、replace 与 directory fsync。与 workspace/checkpoint 不重叠，不发现/迁移旧格式。
- R8. scope 来自 composition root 的 canonical workspace digest；store header 还绑定 operator-approved 的非秘密 provider trust-profile identity（explicit profile ID + provider family + destination）。切换 account/tenant/trust principal 必须使用新 profile ID；cross-workspace、cross-profile lookup/mutation fail closed，store path/inventory/unmatched records 不进入 model/event；v1 无自动 reauthorization。
- R9. `memory_search`/`memory_get` 是 READ_ONLY；`memory_remember`/`memory_update`/`memory_forget` 是 ALWAYS_APPROVAL WRITE。`remember` 绑定 scope、store revision 与新 content digest，不绑定尚不存在的 record；`update`/`forget` 另外绑定并接收现有 record ID、record revision/precondition token 与相应旧/新 content digest。preview 展示 exact bounded content、before/after diff 或被删除内容，不能让用户只看 digest/count 盲批。
- R10. source/read lock timeout 或 transient source unavailable 在 provider 前变成 `FAILED_RETRYABLE/context_source_unavailable`；`Resume` 修复后重新 build。mutation effect 前的 lock timeout 是 known-not-executed `memory_busy`。integrity/auth/version/scope/provider-profile/snapshot inconsistency 是 `FAILED_FATAL`。
- R11. effect 前 CAS mismatch 是 known-not-executed；effect 可能发生后的异常进入 existing unknown-outcome recovery，绝不自动 retry。
- R12. secret-like 检测只是 defense-in-depth：命中时拒绝，但未命中不构成保密保证。v1 是会再次发送给当前 provider 的明文 owner-only local storage，不宣称静态加密、备份隔离或同用户进程隔离。
- R13. 首次使用必须显式二选一：`--memory-create PATH` 只对 missing target 排他创建 revision-0 空 store；`--memory-store PATH` 只加载已存在且合法的 store。普通 Memory tool 不隐式 bootstrap。

验收场景：低预算下 core 不被 Memory 挤掉；同 snapshot 选择确定；provider projection 保持 untrusted；approved write 下一 build 可见；cross-scope/symlink/mode/path-overlap 被拒；source transient failure provider call count 为零且可 Resume；write crash 遵守 EXECUTING/recovery。

## Planning Contract

- KTD1. **ContextSource is generic; Memory is one adapter.** Runtime 合同不出现 `memory_*` 分支或 record store 类型。
- KTD2. **ContextManager remains sole selector.** source 只提供候选和 snapshot identity，不能要求 inclusion 或 authority。
- KTD3. **Read and write paths are separate.** 召回在 build 中只读，修改复用 governed tool effect ordering；conversation checkpoint 不保存 store snapshot、inventory、source cursor 或未选 candidates。模型显式发起的 Memory tool arguments/results 仍像所有 tool facts 一样进入当前 conversation checkpoint。
- KTD4. **Fresh strict snapshot per build.** 不维护 live cache/watch thread，避免一次 provider context 混用两个 revision。
- KTD5. **不恢复旧 Memory 大系统** `(session-settled: user-approved — chosen over continuing feature-entangled legacy architecture: the user accepted cutting old implementations and rebuilding through stable boundaries.)`。

目标结构：

```text
agent/memory/{__init__.py,contracts.py,store.py,source.py,tools.py}
tests/memory/{test_store.py,test_source.py,test_tools.py,test_integration.py}
```

## System-Wide Impact

- Runtime 只增加 generic ContextSource/error contract；Memory package 不进入 state reducer或 provider loop。
- 本计划首次把 explicit sources tuple 接入 shared composition/ContextManager，同时注入 Memory source 和 registrations，并拥有互斥 create/load startup；未配置时这些字段保持空且行为不变。
- Memory plaintext 会跨 conversation 进入当前 provider，approval/event/checkpoint 只保留当前明确 tool mutation 所需的 bounded facts，不保存全库投影。

## Implementation Units

### U1 — Add immutable ContextSource leaf contract

- **Modify:** `agent/runtime/contracts.py`, `agent/runtime/ports.py`, `tests/kernel/test_context_budgeting.py`, `tests/architecture/test_dependency_dag.py`.
- **Red:** source cannot return mutable/non-JSON data; `snapshot(query)` atomically returns source identity/revision/digest/candidates；stable snapshot/candidate identity validation；composition/ContextManager accepts explicit tuple only; empty tuple reproduces byte-equivalent current ContextPack/BudgetReport.
- **Green:** add generic query/candidate/snapshot/report types and snapshot-returning `ContextSource` protocol, then extend the static composition result with the first real sources tuple without importing Memory or adapters.
- **Verify:** leaf import DAG and no provider/tool/checkpoint methods on the port.

### U2 — Extend ContextManager selection and failure mapping

- **Modify:** `agent/runtime/context.py`, `agent/runtime/loop.py`, provider normalizers/adapters, tests under `tests/kernel/` and `tests/provider/`.
- **Red:** priority/budget matrix; source caps; deterministic tie-breaks; context block never system; source digest/item IDs in report; transient vs fatal source error before provider; Resume rebuild; inconsistent/duplicate candidate identity fail closed.
- **Green:** source snapshot collection, candidate grouping/costing/projection, `RetryableContextSourceError` and fatal source error mapping. Preserve atomic conversation groups.
- **Verify:** existing no-source context golden behavior plus OpenAI/Anthropic request normalization tests.

### U3 — Implement secure revisioned Memory store

- **Add:** `agent/memory/contracts.py`, `agent/memory/store.py`, `tests/memory/test_store.py`.
- **Red:** mutually exclusive create/load contract, revision-0 empty schema/scope/provider-profile binding, profile mismatch, concurrent create loser, strict schema/version/unknown fields, owner/mode/link count, symlink/hard-link/lock-inode replacement defenses, path overlap, monotonic finite lock deadline for create/load/read/prepare/mutation, barrier-held lock, all revision checks inside one lock region, file fsync/replace/directory fsync crash points, CAS conflict, cross-scope, deterministic injected clock/IDs and original-byte preservation on invalid load.
- **Green:** minimal local JSON store with stable independent lock file, immutable snapshot and explicit mutation preconditions. Do not inspect/migrate old paths or let `remember` create a missing store.
- **Verify:** all fixtures live under temp directories outside tool workspace.

### U4 — Implement Memory source and read tools

- **Add:** `agent/memory/source.py`, first half of `agent/memory/tools.py`, `tests/memory/test_source.py`.
- **Red:** fresh snapshot each build; exact NFKC/casefold/token/phrase-bonus/recency/ID ranking including CJK and empty query; bounded search/get; empty result; no inventory leakage; held-lock timeout is retryable before provider；source/store transient and integrity classification; approved write only visible next build.
- **Green:** `MemoryContextSource`, `memory_search`, `memory_get`, immutable registrations and sanitized output.
- **Verify:** exact candidate/report determinism and no direct ContextPack construction in Memory package.

### U5 — Implement approved mutation tools

- **Modify:** `agent/memory/tools.py`; add `tests/memory/test_tools.py`.
- **Red:** operation-specific approval contract：remember 只绑定 scope/store revision/new-content digest 且不要求 record identity；update/forget 参数、preview 与 binding 都包含现有 record ID、record revision/precondition token 和相应 content digest；preview 内容/diff 与最终 mutation 精确绑定；无法安全展示或 secret-like content 在 approval 前拒绝；stale store/record/content revision and pre-effect lock timeout return `executed=false`; EXECUTING before mutation; post-commit save/call failure recovery; replay invokes once.
- **Green:** intent-aware mutations backed by store CAS and per-registration policy。Mutation/record 上限不大于 approval preview 上限，preview 显示完整 bounded content/diff；无法完整展示时 effect 前拒绝，digest 只负责绑定。
- **Verify:** one ToolRuntime path and no Memory-specific pending state.

### U6 — Compose, document and lock absence

- **Modify:** `agent/composition.py`, `main.py`, `README.md`, `docs/architecture/EXTENSION_CONTRACTS.md`, architecture tests; add `tests/memory/test_integration.py` and CLI tests.
- **Red:** no config equals exact base behavior；`--memory-create`/`--memory-store` 互斥，create 不覆盖且失败不留半文件，load 不创建；valid store composes source + registrations；invalid/overlap store fails startup；old Memory namespaces/hooks remain absent。
- **Green:** explicit Memory create/load options through shared composition only; update allowlists/docs.
- **Verify:** fake provider journey remember → approve → next message recall, plus full gates.

## Verification Contract

Feature-test venv 先从当前 worktree 安装 `.[dev,skill,mcp]`；Memory v1 没有新的第三方 runtime extra。base-install absence 仍在只安装 `.[dev]` 的 clean temp venv/subprocess 中验证。

```bash
.venv/bin/python -m pytest -q tests/kernel/test_context_budgeting.py tests/provider tests/memory tests/cli
.venv/bin/python -m pytest -q tests/architecture
git diff --check
.venv/bin/ruff check .
.venv/bin/python -m pytest -q -rx
```

Use only synthetic records and temporary owner-only paths. Do not read real user Memory, `.env`, credentials, logs or old runtime data. Concurrency/fault tests must assert provider/tool call counts, not only final status.

## Definition of Done

- Generic ContextSource seam exists without Memory ownership leaking into Runtime contracts.
- Memory candidates are fresh-snapshot, deterministic, untrusted and subordinate to core context budget.
- Explicit approved records can be searched/recalled/updated/forgotten through the single ToolRuntime path.
- Storage, scope, approval, retryable source failure and unknown mutation outcome are fault-injection tested.
- 用户批准的跨 conversation reference task 证明召回内容被预算选择并实际改善回答；没有 evidence 不自动进入 SubAgent。
- No automatic Memory lifecycle or old implementation returns; architecture and full quality gates pass.
