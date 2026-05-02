# Subagent System Safe Local MVP

本文件记录 Roadmap Completion Autopilot 中的 Subagent System 最小安全实现。

## 定位

Subagent 在本阶段只是 **fake/local profile + delegation contract**：

- 读取显式传入的 `tmp_path` 或 `tests/fixtures/subagents`。
- 解析 `SUBAGENT.md` profile。
- 生成 parent-controlled `DelegationRequest` / `DelegationResult`。

它不是：

- 真实 LLM delegation。
- 远程 agent。
- 外部进程。
- autonomous child tool executor。
- runtime handoff。

## Safety rules

- no real subagent dirs
- no real LLM/provider
- no external process spawn
- no remote delegation
- no autonomous child tool execution
- no env expansion
- no secret output
- parent runtime remains in control

`agent.subagents.local` therefore does not import runtime, tool executor, provider,
subprocess, or network modules.

## Fixture example

`tests/fixtures/subagents/code-reviewer/SUBAGENT.md` 是当前 safe local fixture。
它只声明角色、fake model 和允许工具元数据，不会执行任何子任务。

## Validation evidence

`tests/test_subagent_local_mvp_contract.py` 覆盖：

- valid local fixture profile accepted
- invalid profile rejected
- unsafe path rejected
- real LLM delegation rejected
- external process rejected
- tool bypass rejected
- parent policy enforced
- delegation request/result structured and redacted
