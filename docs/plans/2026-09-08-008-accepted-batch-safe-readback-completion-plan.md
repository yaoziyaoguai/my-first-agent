# Accepted Batch Safe Read-back Completion Plan

- Date: 2026-09-08
- Status: accepted
- Source: Oracle Web session `first-agent-r9-008-next-slice-20260908-d4a7` + Codex current-worktree verification
- Executor: Codex

## Outcome

最终一个成功的 `read_file` 仍可在 closed evidence 已完整时直接完成 Goal，避免要求模型
再抄写一次 Runtime 已发布的 evidence refs；但同一已接纳工具批次尚有普通调用未执行时，
中间 read-back 不得提前终止 run、丢弃剩余调用或掩盖其 approval、limit、recovery 边界。

## Verified defect

`AgentRuntime._drive` 在成功的 model-origin tool result 持久化并发送事件后，先调用
`_finish_if_durable_evidence_is_complete`，再检查当前批次是否完成。`record_tool_result`
会让中间结果保留 `ContinuationPhase.TOOL`、原 `tool_calls` 和推进后的 `batch_cursor`；
但 completion helper 只检查 tool name、Goal 和 evidence，没有检查批次耗尽。若第一个
`read_file` 已满足所有 mandatory criteria，helper 随即 `complete_run` 并清空
`active_run`，同批剩余 accepted calls 因而消失。

## Frozen acceptance contract

1. 成功的中间 `read_file` 已可靠落盘并排队发送 `TOOL_RESULT` 后，不写入 completion
   evidence/claim，不进入 `VERIFIED_DONE`，也不清空 active batch。
2. 若没有既有 interruption，剩余调用继续按原顺序经过 policy、approval、budget、
   `EXECUTING`、result checkpoint 与 recovery；不得无条件 drain batch。
3. 成功的最终 `read_file`（包括单调用批次）保持既有 deterministic completion，不增加
   Provider call。
4. 不把自动完成扩展到非 `read_file` 的最后结果；不新增 pending-completion 状态。
5. durable prefix 在 resume/reopen 后不得重复 invoke；round 007 的 batch convergence、
   dedup、CAS、unknown recovery 和 buffered event ordering 不变。

## Minimal design

在现有私有 `_finish_if_durable_evidence_is_complete` 的 eligibility 中，要求 post-result
active run 已处于 `MODEL` phase 且没有保留 `tool_calls`。这个状态完全由既有 reducer
提供：中间结果为 `TOOL`，最后结果为 `MODEL` 并清空 calls。公共 `run_turn` interface、
contracts、state reducer、ContextManager、ToolRuntime 与 evidence registry 均不修改。

## Vertical TDD

### R1 — evidence-closing read followed by another read

- 真实 workspace 包含 `reports/final.md` 与第二个普通文件。
- 同一 model response 接纳两个 `read_file`；第一个已独立满足 Goal criterion。
- baseline 必须 RED：只产生第一个 result 就完成。
- GREEN：两个调用/result 都精确一次，完成事件在两个 result 之后，Goal 最终
  `VERIFIED_DONE`，且没有额外 Provider call。

### R2 — preserve suffix boundary and final-read optimization

- 复用既有 single/final-read 测试，证明不会增加 Provider call。
- 最小补充 approval/recovery 或 non-read suffix，只在 R1 暴露的新行为需要额外保护时
  增加；不得为设想场景建立新 fixture framework。

## Protected boundaries

- `AgentRuntime.run_turn` 仍是唯一 production model/tool loop 和 state owner。
- 每个工具仍逐项执行并独立完成 `EXECUTING` / result checkpoint。
- approval、unknown outcome、budget、browser takeover 与用户 control 优先级不变。
- completion 仍由 `ClosedEvidenceRegistry` 和 `verify_goal_completion` 决定。
- Runtime event 仍是 lease 释放后的 buffered delivery，不宣称 durable outbox。

## Non-goals

- 不修 background replay、pre-call refusal、MCP `title` schema、context eviction/dedup、
  prose intent routing 等 Oracle B–F findings。
- 不新增第二套 loop、batch coordinator、public contract、checkpoint schema、配置或能力。
- 不访问真实 Provider、网站、profile、credential、private runtime 或未跟踪 `tui/`。
- 不 commit、push、发布或作 production-ready 声明。

## Expected files

- Production: `agent/runtime/loop.py`
- Tests: `tests/continuity/test_verified_done.py`
- Documentation: 本计划；只有现有架构文字与真实行为冲突时才最小更新架构文档。

## Verification

1. R1 在 baseline 上真实 RED，再做最小 Green。
2. focused：`tests/continuity/test_verified_done.py`。
3. protected：runtime errors/recovery/turn、context/compaction、architecture。
4. review actual diff and fix every blocking finding。
5. focused 全部通过后只运行一次最终门禁：
   - `git diff --check`
   - `.venv/bin/ruff check .`
   - `.venv/bin/python -m pytest -q -rx`

## Deferred Oracle queue

下一批已证候选依次独立审计，不在本轮合并：background replay phase mismatch；
pre-call refusal outcome；MCP schema `title`；context-visible result 与 dedup；prose intent
routing。尚无本轮专项 Oracle 覆盖的模块队列为 History/Continuity/Evidence、
Scheduler/Automation、CLI/TUI、Sandbox/Process、Provider、Memory、Skill、SubAgent。

## Implementation and review record

- Oracle Web 使用全新 session `first-agent-r9-008-next-slice-20260908-d4a7`，页面
  实际档位验证为“第 5 项，共 5 项”；`promptSubmitted=true`、新 conversation 与完整
  transcript 均已捕获。结束后 exact Chrome PID 不再存活，临时 Profile 已删除。
- Codex 独立核对 source 后确认同一 defect：中间 result 保持 `TOOL` 与剩余 calls，旧
  helper 却可直接 `complete_run`。deep-module 检查决定保留现有 `run_turn` interface，
  只在 Runtime 私有 completion eligibility 内修复。
- R1 baseline 真实 RED：期望两个 durable results，实际只有 `('read-final',)`；第二个
  accepted read 在首个 evidence-closing read 后被提前完成丢弃。
- 最小 Green 只增加 post-result `MODEL` + empty `tool_calls` eligibility；R1 通过。
  既有 single/final-read 测试补强 `len(provider.calls) == 1`。
- Focused gates：`tests/continuity/test_verified_done.py` 为 `19 passed`；Runtime/Recovery/
  ToolRuntime 为 `75 passed`；Context/Compaction 为 `101 passed`；Architecture 为
  `69 passed`。
- fresh Pi 只读审计使用 `cc-switch-zhipu-glm/glm-5.3`、thinking `max`、无 session、
  no-tools 和显式附件白名单，结论 `PASS`，无阻塞 P0/P1/P2；Pi 未修改文件。
- 最终全量门禁只执行一次：`git diff --check` PASS、全仓 Ruff PASS、pytest
  `3248 passed, 3 skipped in 377.46s (0:06:17)`，完整 exit 0。本轮不把
  scripted/offline 测试冒充真实外部 E3。
