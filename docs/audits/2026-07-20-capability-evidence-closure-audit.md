---
title: Capability Evidence Closure Follow-up Audit
date: 2026-07-20
type: audit
---

# Capability Evidence Closure Follow-up Audit

## Executive verdict

008 没有完成六项 capability 的本地闭环。

当前 Kernel 主干仍值得保留：production provider call、ToolRuntime invocation 和 checkpoint mutation 仍集中在 `AgentRuntime.run_turn` 所属路径，六项能力也没有重新引入第二套 production loop。
失败发生在 proof 与 closure 层：执行记录把局部修补、source-shape test、安全拒绝和脏工作树 test count 提升成了 `verified`。

因此正确动作是新建 009 收口，而不是推倒 Kernel 或继续新增能力。

## Scope and method

本复审只读取 repository source、tests、architecture docs、008 artifacts 与 deterministic local command result。
未读取 `.env`、credential、真实 Memory/Skill/MCP/SubAgent 私有目录、`tui/agent_log.jsonl` 或 `tui/memory/` 内容；未调用真实 provider、真实 MCP 或外部 service。

独立检查包括：

- `git diff --check`：exit 0。
- `.venv/bin/ruff check .`：exit 0。
- `.venv/bin/ruff check agent/memory tests/memory`：exit 0。
- `.venv/bin/python -m pytest -q -rx`：286 passed。
- focused capability suite：268 passed。
- manifest membership：1072-entry membership gate passed。
- `scripts/verify_materialized_tree.py --content`：exit 2，未实现。
- `scripts/verify_materialized_tree.py --control-seal`：exit 2，未实现。

前四类 Green 只证明当前工作树的部分自动行为。
它们不能覆盖后两项失败，也不能修复错误 oracle。

## Load-bearing findings

### F1. P0 — 008 delivery manifest 自动纳入未跟踪 runtime state

`scripts/verify_materialized_tree.py` 通过 `git ls-files --others --exclude-standard` 枚举全部未跟踪文件，再给未知 path 默认分配 `audited-baseline`。
`docs/implementation/008_INTENDED_TREE_MANIFEST.json` 因此包含 `tui/agent_log.jsonl` 与 `tui/memory/checkpoint.json`。

这不是单个 deny rule 漏洞，而是 admission model 错误：文件存在不等于文件被授权成为产品内容。
009 必须使用 exact allowlist admission，并让未知 untracked path fail closed；不得修补成另一套越来越长的黑名单。

### F2. P0 — 008 的最终 delivery gate 根本没有实现

`scripts/verify_materialized_tree.py` 对 `--content` 和 `--control-seal` 明确返回 exit 2。
当前所谓 manifest Green 只验证工作树 membership，没有 materialize、non-editable install、neutral-cwd import-origin 或 final control seal。

因此 A1/U9 仍未关闭，任何 `locally-verified` 声明都没有 E2M 依据。

### F3. P0 — MCP approval 与实际 effect 不是同一个对象

`agent/mcp/tools.py` 的 preview 对 canonical arguments 做固定长度截断，但 bridge 仍执行完整 arguments；`env_provider` 也在 invoke 时才解析。
用户看到的内容、approval digest、最终 process environment 与实际 call 可以产生时间或内容偏差。

同时 executable/cwd 只冻结于较早阶段、remote error 仍可能被扁平化、stderr 未形成完整 bounded drain，direct child exit 也不能证明整个 process group clean。
008 的 A4/A5/A6 “verified” 只覆盖局部分支，不满足 MCP design 的完整 lifecycle。

### F4. P0 — Memory strict snapshot test 明确接受违规输入

`tests/memory/test_store.py` 中名为 strict snapshot 的测试注释允许 unknown field；实际 store 也接受类型强制转换、stale digest 与不完整 revision invariant。
已用临时数据复现：修改 record content 而保留旧 digest 后仍可 load。

`tests/memory/test_tools.py` 还把 scope digest 与 store revision 混为同一 precondition。
这些测试不是 coverage 不足，而是 oracle 与 design 相反。

### F5. P1 — SubAgent 只证明当前 HTTP provider 被拒绝，没有证明 provider lifecycle

`ChildProfile` 没有可执行的 deadline/receipt 字段，runner 接受普通 provider object；当前 registration guard 只按 provider 类型拒绝。
objective/handoff 仍可被静默切片，nonterminal 仍可作为普通成功字符串返回。

安全拒绝是必要行为，但它只证明 `safe-unavailable`。
没有 supported provider receipt、receipt precedence 与 parent recovery journey，就不能关闭 A12/A18，也不能做 SubAgent E3。

### F6. P1 — TUI 仍是 submit-only adapter

`agent/tui/app.py` 没有 approval、reject、recovery、Resume、合法 paused Cancel 的 keyboard action path。
Runtime event queue 没有成为 TUI composition 的共享 sink，TUI branch 的早返回还绕过 shared close-stack lifecycle。

计划要求的 `test_pending_reopen_keyboard_journey_and_shared_lifecycle` 不存在。
submit → completed Pilot 不能证明 action parity、restart recovery 或 lifecycle。

### F7. P1 — Skill 只复验 digest，没有复验 frozen file identity

catalog 虽保存部分 `FileIdentity`，`read_activation` / `read_resource` 的执行路径最终只比较内容 digest。
相同字节的 inode replacement 已复现仍被接受；metadata 也未完整进入 model-visible activation contract。

当前测试只改变内容，无法关闭 design 中的 ancestor/file identity requirement。

### F8. P1 — Scheduler validation 与并发 reconciliation 仍缺两条主路径

UTC validator 只检查字符串形状，已复现 `2026-99-99T99:99:99Z` 被接受。
caller 只对 `checkpoint_conflict` 做 one-shot reload，没有对 `conversation_busy` 使用相同 exact-action reconciliation。

human resolution 后 duplicate terminal report 的局部修复可以保留，但 A10 仍未完整关闭。

### F9. P1 — 执行记录的 `verified` 不能追溯到真实 Red/Green oracle

`docs/implementation/008_STABILIZATION_EXECUTION_LOG.md` 多处只记录总 test count、实现描述或与 finding 不同的测试。
它没有为每个 finding 保留修复前失败输出、修复后同一 test 的 observable assertions 与 boundary counts。

009 必须把 execution log 变成 append-only evidence index；没有准确 Red 的 unit 不能进入 Green。

## Retained foundation

以下结论仍可信，应作为 009 的非回归基线：

- `AgentRuntime.run_turn` 仍是 production model/tool loop 和 state progression owner。
- `KernelContextManager` 仍独占 `ContextPack` selection。
- `KernelToolRuntime` 仍独占 governed callable invocation。
- Scheduler 仍是 external caller，不是 timer/daemon。
- TUI 仍是 adapter 方向，问题是功能和 lifecycle 未完成。
- A15 private-root casefold、A16 stale approval nonfatal、A17 provider context projection、A19 strict frontmatter allowlist 的现有修复可以保留，但必须在 009 materialized regression gate 中重验。

## Capability disposition

| Capability | Current truth | Blocking closure |
|---|---|---|
| Minimal Runtime Kernel | foundation retained | clean delivery 与 shared regression gate |
| MCP | implemented-candidate | F3 + delivery |
| Memory | implemented-candidate | F4 + delivery |
| SubAgent | safe-unavailable candidate | F5 + delivery；E3 blocked |
| Scheduler | partial implemented-candidate | F8 + delivery |
| Skill | implemented-candidate | F7 + delivery |
| TUI | submit-only implemented-candidate | F6 + delivery |

没有 capability 是 `accepted`。
009 完成后也只能按每项实际 E1/E2/E2M 结果独立晋级；SubAgent 如果仍没有 supported provider contract，必须继续明确标记 E3-blocked。

## Required next work

1. 先替换 delivery admission 与 evidence-state contract，隔离 008 manifest/status。
2. 再按 MCP、Memory、SubAgent、Scheduler、Skill、TUI 的 boundary risk 收口行为 oracle。
3. 最后从新 manifest materialize、non-editable install、neutral-cwd 运行全部 gates，并只在已知结果后更新 claims。

新计划见 `docs/plans/2026-07-20-009-close-capability-evidence-gaps-plan.md`。
